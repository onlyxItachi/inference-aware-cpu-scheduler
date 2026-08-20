"""E1 — classify migrations by topology, not by count.

Runs one inference while sampling where every thread physically sits, then
reports whether a thread's movement stays inside one SMT sibling pair
(nearly free: shared L1/L2) or crosses physical cores (discards private
cache state).

CAVEAT, stated up front: the sampler itself does thousands of /proc reads
per second, so the latency numbers produced here are perturbed and are NOT
comparable to the affinity sweep's. E1 exists to answer a topology
question, not a performance one. Latency is reported only to confirm the
run was in a normal regime.
"""

import argparse
import json
import os
import subprocess
import signal
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bench_lib as bl
import run_once as ro
import thread_residency as tr


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--server-bin", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--prompt", required=True)
    p.add_argument("--cpus", default="")
    p.add_argument("--threads", type=int, default=8)
    p.add_argument("--n-predict", type=int, default=192)
    p.add_argument("--interval", type=float, default=0.005)
    p.add_argument("--port", type=int, default=8083)
    p.add_argument("--label", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()

    prompt = open(args.prompt).read()

    cmd = []
    if args.cpus:
        cmd += ["taskset", "-c", args.cpus]
    cmd += [args.server_bin, "-m", args.model, "-t", str(args.threads),
            "-tb", str(args.threads), "-c", "2048", "-b", "2048",
            "-ub", "512", "-np", "1", "--host", ro.HOST,
            "--port", str(args.port)]

    log = open(os.devnull, "wb")
    proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT,
                            start_new_session=True)
    result = {}
    try:
        ro.wait_for_health(args.port, proc)
        ro.stream_completion(args.port, {
            "prompt": "Warmup.", "n_predict": 1, "temperature": 0,
            "stream": True, "cache_prompt": False})
        time.sleep(1.0)

        payload = {"prompt": prompt, "n_predict": args.n_predict,
                   "temperature": 0.0, "seed": 42, "stream": True,
                   "cache_prompt": False, "ignore_eos": True}

        holder = {}

        def do_request():
            holder["r"] = ro.stream_completion(args.port, payload)

        req = threading.Thread(target=do_request)
        sched_before = bl.sched_snapshot(proc.pid)
        req.start()

        # Sample for as long as the request runs.
        cpu_core, _ = tr.read_topology()
        residency = {}
        transitions = {}
        last = {}
        n = 0
        from collections import Counter, defaultdict
        residency = defaultdict(Counter)
        transitions = Counter()
        while req.is_alive():
            cur = tr.sample_cpus(proc.pid)
            n += 1
            for tid, cpu in cur.items():
                residency[tid][cpu] += 1
                prev = last.get(tid)
                if prev is not None and prev != cpu:
                    pc, p_is_p = cpu_core.get(prev, (-1, False))
                    cc, c_is_p = cpu_core.get(cpu, (-1, False))
                    if pc == cc:
                        transitions["sibling"] += 1
                    elif p_is_p and c_is_p:
                        transitions["P->P"] += 1
                    elif not p_is_p and not c_is_p:
                        transitions["E->E"] += 1
                    else:
                        transitions["P<->E"] += 1
                last[tid] = cpu
            time.sleep(args.interval)
        req.join()
        sched_after = bl.sched_snapshot(proc.pid)

        t_sent, token_ts, _, _ = holder["r"]
        itl = [(token_ts[i] - token_ts[i - 1]) / 1e6
               for i in range(1, len(token_ts))]

        busy = {tid: c for tid, c in residency.items()
                if sum(c.values()) >= max(5, n * 0.05)}
        spans = Counter()
        confined = 0
        for tid, c in busy.items():
            cores = {cpu_core.get(x, (-1, False))[0] for x in c}
            spans[len(cores)] += 1
            if len(cores) == 1:
                confined += 1

        delta = bl.sched_delta(sched_before, sched_after)
        result = {
            "label": args.label,
            "cpus": args.cpus or "unpinned",
            "threads": args.threads,
            "samples": n,
            "interval_s": args.interval,
            # ground truth from the kernel, unaffected by sampling rate
            "kernel_migrations_total": delta["migrations"],
            "kernel_ctx_switches_total": delta["ctx_switches"],
            "threads_busy": len(busy),
            "threads_confined_to_one_physical_core": confined,
            "pct_threads_confined": round(
                confined / len(busy) * 100, 1) if busy else None,
            "physical_cores_spanned_per_thread": dict(sorted(spans.items())),
            "sampled_transitions_lower_bound": dict(transitions.most_common()),
            "cpu_occupancy": dict(Counter(
                {cpu: sum(c[cpu] for c in busy.values())
                 for cpu in {x for c in busy.values() for x in c}}
            ).most_common(24)),
            "itl_p50_ms_PERTURBED": round(sorted(itl)[len(itl) // 2], 2)
            if itl else None,
            "n_tokens": len(token_ts),
        }
    finally:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            proc.wait(timeout=20)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
        log.close()

    with open(args.out, "w") as f:
        json.dump(result, f, indent=2)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
