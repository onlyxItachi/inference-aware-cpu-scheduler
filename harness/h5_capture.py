"""H5 capture — system-signal time series alongside ground-truth token times.

The question: can the prefill/decode boundary be found from OS-visible
signals alone, with no help from the application?

Ground truth is the arrival of the first token, which the streaming client
already records. Everything else here is deliberately restricted to what a
userspace daemon could read about *any* process, without instrumenting it:

  /proc/stat                     per-CPU jiffies, procs_running
  /proc/<pid>/stat               thread-group utime+stime
  /proc/<pid>/task/<tid>/sched   ctx switches, migrations  (summed)
  cpufreq scaling_cur_freq       per-CPU frequency
  RAPL energy_uj                 package energy (if readable)

All timestamps share one perf_counter_ns timebase with the token stream,
so signal and ground truth can be aligned exactly.

Sampling cost is real (34 thread files per tick) and is recorded in the
output, because a detector that only works with an unaffordable sampler is
not a usable detector.
"""

import argparse
import glob
import json
import os
import signal
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bench_lib as bl
import run_once as ro

RAPL_CANDIDATES = [
    "/sys/class/powercap/intel-rapl:0/energy_uj",
    "/sys/class/powercap/intel-rapl:0/intel-rapl:0:0/energy_uj",
]


def find_rapl():
    for p in RAPL_CANDIDATES:
        try:
            with open(p) as f:
                f.read()
            return p
        except OSError:
            continue
    return None


RAPL_PATH = find_rapl()
P_FREQ = [f"/sys/devices/system/cpu/cpu{c}/cpufreq/scaling_cur_freq"
          for c in range(16)]


def read_energy_uj():
    if RAPL_PATH is None:
        return None
    try:
        with open(RAPL_PATH) as f:
            return int(f.read().strip())
    except OSError:
        return None


def read_proc_stat():
    """Per-CPU busy jiffies + procs_running, from one file read."""
    per_cpu = {}
    procs_running = None
    with open("/proc/stat") as f:
        for line in f:
            if line.startswith("cpu") and line[3].isdigit():
                parts = line.split()
                cpu = int(parts[0][3:])
                vals = [int(x) for x in parts[1:11]]
                idle = vals[3] + vals[4]          # idle + iowait
                per_cpu[cpu] = (sum(vals), idle)  # (total, idle)
            elif line.startswith("procs_running"):
                procs_running = int(line.split()[1])
            elif line.startswith("procs_blocked"):
                break
    return per_cpu, procs_running


def read_pid_cputime(pid):
    try:
        with open(f"/proc/{pid}/stat") as f:
            data = f.read()
        rest = data[data.rfind(")") + 2:].split()
        return int(rest[11]) + int(rest[12])  # utime + stime (fields 14,15)
    except (OSError, IndexError, ValueError):
        return None


def read_sched_totals(pid):
    """Summed ctx switches and migrations across all threads."""
    sw = mig = 0
    n = 0
    for path in glob.glob(f"/proc/{pid}/task/*/sched"):
        try:
            with open(path) as f:
                for line in f:
                    if line.startswith("nr_switches"):
                        sw += int(line.split(":")[1])
                    elif line.startswith("se.nr_migrations"):
                        mig += int(line.split(":")[1])
        except (OSError, ValueError):
            continue
        n += 1
    return sw, mig, n


class Sampler(threading.Thread):
    def __init__(self, pid, interval_s):
        super().__init__(daemon=True)
        self.pid = pid
        self.interval_s = interval_s
        self.stop_flag = threading.Event()
        self.samples = []
        self.sample_cost_ns = []

    def run(self):
        while not self.stop_flag.is_set():
            t0 = bl.now_ns()
            per_cpu, procs_running = read_proc_stat()
            sw, mig, nthreads = read_sched_totals(self.pid)
            cputime = read_pid_cputime(self.pid)
            freqs = [v for v in (bl._read_int(p) for p in P_FREQ) if v]
            energy = read_energy_uj()
            t1 = bl.now_ns()

            self.samples.append({
                "t_ns": t0,
                "ctx_switches": sw,
                "migrations": mig,
                "threads": nthreads,
                "cputime_jiffies": cputime,
                "procs_running": procs_running,
                "cpu_busy": {str(c): per_cpu[c] for c in sorted(per_cpu)},
                "freq_p_top8_khz": sorted(freqs, reverse=True)[:8],
                "energy_uj": energy,
            })
            self.sample_cost_ns.append(t1 - t0)
            self.stop_flag.wait(self.interval_s)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--server-bin", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--prompt", required=True)
    p.add_argument("--cpus", default="0,2,4,6,8,10,12,14")
    p.add_argument("--threads", type=int, default=8)
    p.add_argument("--n-predict", type=int, default=256)
    p.add_argument("--interval-ms", type=float, default=20.0)
    p.add_argument("--ubatch", type=int, default=512)
    p.add_argument("--port", type=int, default=8087)
    p.add_argument("--out", required=True)
    args = p.parse_args()

    prompt = open(args.prompt).read()
    cmd = []
    if args.cpus:
        cmd += ["taskset", "-c", args.cpus]
    cmd += [args.server_bin, "-m", args.model, "-t", str(args.threads),
            "-tb", str(args.threads), "-c", "2048", "-b", "2048",
            "-ub", str(args.ubatch), "-np", "1", "--host", ro.HOST,
            "--port", str(args.port)]

    log = open(os.devnull, "wb")
    proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT,
                            start_new_session=True)
    try:
        ro.wait_for_health(args.port, proc)
        ro.stream_completion(args.port, {
            "prompt": "Warmup.", "n_predict": 1, "temperature": 0,
            "stream": True, "cache_prompt": False})
        time.sleep(1.0)

        sampler = Sampler(proc.pid, args.interval_ms / 1000.0)
        sampler.start()
        time.sleep(0.5)  # a little pre-request baseline

        temp0 = bl.package_temp_c()
        t_sent, token_ts, _, _ = ro.stream_completion(args.port, {
            "prompt": prompt, "n_predict": args.n_predict,
            "temperature": 0.0, "seed": 42, "stream": True,
            "cache_prompt": False, "ignore_eos": True})
        temp1 = bl.package_temp_c()

        time.sleep(0.3)  # a little post-request tail
        sampler.stop_flag.set()
        sampler.join(timeout=5)
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

    itl = [(token_ts[i] - token_ts[i - 1]) / 1e6
           for i in range(1, len(token_ts))]
    costs = sorted(sampler.sample_cost_ns)
    result = {
        "cpus": args.cpus or "unpinned",
        "threads": args.threads,
        "ubatch": args.ubatch,
        "interval_ms": args.interval_ms,
        "rapl_path": RAPL_PATH,
        "energy_available": RAPL_PATH is not None,
        # ground truth, same timebase as samples
        "t_request_sent_ns": t_sent,
        "t_first_token_ns": token_ts[0],
        "t_last_token_ns": token_ts[-1],
        "token_ts_ns": token_ts,
        "ttft_ms": (token_ts[0] - t_sent) / 1e6,
        "itl_p50_ms": sorted(itl)[len(itl) // 2],
        "decode_tps": (len(token_ts) - 1) /
                      ((token_ts[-1] - token_ts[0]) / 1e9),
        "n_tokens": len(token_ts),
        "temp_start_c": temp0,
        "temp_end_c": temp1,
        "sampler_cost_us_p50": costs[len(costs) // 2] / 1000.0 if costs else None,
        "sampler_cost_us_p95": costs[int(len(costs) * 0.95)] / 1000.0
        if costs else None,
        "n_samples": len(sampler.samples),
        "samples": sampler.samples,
    }
    with open(args.out, "w") as f:
        json.dump(result, f)
    print(json.dumps({k: v for k, v in result.items()
                      if k not in ("samples", "token_ts_ns")}, indent=2))


if __name__ == "__main__":
    main()
