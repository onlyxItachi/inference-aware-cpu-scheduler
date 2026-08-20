"""Where do the threads actually sit? Topology-aware residency sampling.

Motivation: p_smt_forced produced ~1.03M migrations yet the *smoothest*
inter-token latency of any variant (CV 0.5%), while unpinned produced 8.7k
migrations and the jitteriest (CV 3.6%). Raw migration count clearly is not
the quantity that matters. What should matter is topological distance:
CLAUDE.md's own note says a move between the two SMT siblings of one
physical core is nearly free (shared L1/L2), while crossing a physical core
-- or worse, a P/E boundary -- discards private cache state.

This samples each thread's current CPU (/proc/<tid>/stat field 39) and asks
whether a thread's movement stays inside one sibling pair or spans physical
cores.

IMPORTANT — aliasing: at ~21k migrations/s, no /proc sampler can count
transitions. So transition counts here are a *lower bound* and are reported
as such. The primary output is instead the residency footprint: the set of
CPUs each thread is observed on. That statistic is robust to aliasing --
if a thread only ever ping-pongs between siblings, it is never observed
elsewhere, no matter how coarsely we sample.
"""

import argparse
import glob
import json
import os
import sys
import time
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bench_lib as bl


def read_topology():
    """cpu -> (core_id, is_pcore); plus core_id -> sibling cpu list."""
    cpu_core = {}
    core_cpus = defaultdict(list)
    for path in glob.glob("/sys/devices/system/cpu/cpu[0-9]*/topology/core_id"):
        cpu = bl._cpu_index(path)
        with open(path) as f:
            core = int(f.read().strip())
        maxf = bl._read_int(
            f"/sys/devices/system/cpu/cpu{cpu}/cpufreq/cpuinfo_max_freq") or 0
        cpu_core[cpu] = (core, maxf > 4000000)  # P-cores boost >4GHz
        core_cpus[core].append(cpu)
    return cpu_core, {k: sorted(v) for k, v in core_cpus.items()}


def sample_cpus(pid):
    """tid -> current CPU, from /proc/<tid>/stat field 39."""
    out = {}
    for path in glob.glob(f"/proc/{pid}/task/*/stat"):
        try:
            with open(path) as f:
                data = f.read()
        except OSError:
            continue
        # comm may contain spaces and parens; everything after the last ')'
        # is field 3 onward, so field N lives at index N-3.
        rest = data[data.rfind(")") + 2:].split()
        if len(rest) < 37:
            continue
        tid = int(path.split("/task/")[1].split("/")[0])
        out[tid] = int(rest[36])
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--pid", type=int, required=True)
    p.add_argument("--duration", type=float, default=20.0)
    p.add_argument("--interval", type=float, default=0.002)
    p.add_argument("--label", default="")
    p.add_argument("--out", default="")
    args = p.parse_args()

    cpu_core, core_cpus = read_topology()

    residency = defaultdict(Counter)   # tid -> Counter(cpu)
    transitions = Counter()            # class -> lower-bound count
    last = {}
    n_samples = 0

    t_end = time.time() + args.duration
    while time.time() < t_end:
        cur = sample_cpus(args.pid)
        if not cur:
            break
        n_samples += 1
        for tid, cpu in cur.items():
            residency[tid][cpu] += 1
            prev = last.get(tid)
            if prev is not None and prev != cpu:
                pc, p_is_p = cpu_core.get(prev, (-1, False))
                cc, c_is_p = cpu_core.get(cpu, (-1, False))
                if pc == cc:
                    transitions["sibling (same physical core)"] += 1
                elif p_is_p and c_is_p:
                    transitions["P-core -> P-core"] += 1
                elif not p_is_p and not c_is_p:
                    transitions["E-core -> E-core"] += 1
                else:
                    transitions["P <-> E boundary"] += 1
            last[tid] = cpu
        time.sleep(args.interval)

    # Footprint: how many distinct CPUs / physical cores each thread touched.
    # Only threads with real occupancy are interesting; the server has many
    # idle helper threads that never move.
    busy = {tid: c for tid, c in residency.items() if sum(c.values()) >= 10}
    footprints = Counter()
    core_spans = Counter()
    for tid, c in busy.items():
        cpus = set(c)
        cores = {cpu_core.get(x, (-1, False))[0] for x in cpus}
        footprints[len(cpus)] += 1
        core_spans[len(cores)] += 1

    # A thread confined to exactly one sibling pair is the signature of
    # "expensive migration count is actually cheap sibling ping-pong".
    confined = sum(1 for tid, c in busy.items()
                   if len({cpu_core.get(x, (-1, False))[0] for x in c}) == 1)

    result = {
        "label": args.label,
        "pid": args.pid,
        "samples": n_samples,
        "interval_s": args.interval,
        "threads_observed": len(residency),
        "threads_busy": len(busy),
        "threads_confined_to_one_physical_core": confined,
        "distinct_cpus_per_thread": dict(sorted(footprints.items())),
        "distinct_physical_cores_per_thread": dict(sorted(core_spans.items())),
        "transitions_lower_bound": dict(transitions.most_common()),
        "top_cpu_occupancy": dict(
            Counter({cpu: sum(c[cpu] for c in busy.values())
                     for cpu in {x for c in busy.values() for x in c}}
                    ).most_common(24)),
    }

    text = json.dumps(result, indent=2)
    if args.out:
        with open(args.out, "w") as f:
            f.write(text)
    print(text)


if __name__ == "__main__":
    main()
