"""S2 — does the "prefill wide, decode narrow" trade survive real contention?

K1 measured the phase asymmetry on an idle machine. A scheduler policy has
to earn its keep when something else wants the CPU too, so this re-measures
with 16 always-runnable competing threads.

Arms answer two questions in sequence:

  A no_load        LLM on P-cores, nothing else       reference
  B both_free      LLM free, load free                what Linux does today
  C llmP_loadfree  LLM pinned to P, load still free   does isolating the LLM help...
  D llmP_loadE     LLM pinned to P, load pinned to E  ...and does banishing the
                                                      competitor to E-cores help more?

D is the interesting one: it is the simplest topology-aware policy a
sched_ext scheduler could implement -- no phase detection, no adaptation,
just "latency-sensitive work owns the P-cores". If D recovers most of A,
that is a strong argument that the cheap policy is worth writing. If it
does not, the phase-aware machinery has to justify itself some other way.

Load is 16 threads in every loaded arm, so demand is constant and only
placement changes. Interleaved, for the Faz 0 session drift.
"""

import argparse
import csv
import json
import os
import random
import signal
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
P_NOSMT = "0,2,4,6,8,10,12,14"

# (name, llm_cpus, load_cpus, load_threads)
ARMS = [
    ("A_no_load",       P_NOSMT, None,      0),
    ("B_both_free",     "",      "",        16),
    ("C_llmP_loadfree", P_NOSMT, "",        16),
    ("D_llmP_loadE",    P_NOSMT, "16-23",   16),
]

FIELDS = [
    "arm", "round", "run_seq", "timestamp", "llm_cpus", "load_cpus",
    "load_threads", "cpus", "threads", "ttft_ms", "itl_p50_ms",
    "itl_p95_ms", "itl_p99_ms", "itl_max_ms", "itl_mean_ms", "decode_tps",
    "n_tokens", "prompt_tokens", "temp_start_c", "temp_end_c",
    "temp_delta_c", "migrations", "ctx_switches", "threads_seen",
    "freq_p_avg_mhz", "freq_p_busy_mhz", "freq_e_avg_mhz", "seed",
    "n_predict", "load_iters", "load_rate", "load_elapsed_s",
]


def start_load(loadgen, cpus, nthreads, out_path):
    if not nthreads:
        return None
    cmd = []
    if cpus:
        cmd += ["taskset", "-c", cpus]
    cmd += [loadgen, str(nthreads)]
    fh = open(out_path, "w")
    proc = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.DEVNULL,
                            start_new_session=True)
    proc._out_fh = fh
    proc._out_path = out_path
    time.sleep(2.0)  # let it reach steady state before the LLM starts
    return proc


def stop_load(proc):
    """Stop the load and return the work it completed.

    SIGTERM (not KILL) so loadgen's handler runs and it gets to print its
    counters -- the whole point of measuring the competitor's side.
    """
    if proc is None:
        return {}
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        proc.wait(timeout=15)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        proc._out_fh.close()
    except Exception:
        pass
    try:
        with open(proc._out_path) as f:
            for line in f:
                if line.startswith("LOADGEN_RESULT"):
                    kv = dict(p.split("=", 1) for p in line.split()[1:])
                    return {"load_iters": int(kv["iters"]),
                            "load_rate": float(kv["rate"]),
                            "load_elapsed_s": float(kv["elapsed_s"])}
    except OSError:
        pass
    return {}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--server-bin", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--loadgen", default=os.path.join(HERE, "loadgen"))
    p.add_argument("--prompt", default=os.path.join(HERE, "prompt_512.txt"))
    p.add_argument("--rounds", type=int, default=6)
    p.add_argument("--cooldown", type=int, default=30)
    p.add_argument("--threads", type=int, default=8)
    p.add_argument("--outdir", required=True)
    p.add_argument("--port", type=int, default=8086)
    p.add_argument("--order-seed", type=int, default=21)
    args = p.parse_args()

    os.makedirs(os.path.join(args.outdir, "tokens"), exist_ok=True)
    csv_path = os.path.join(args.outdir, "s2.csv")
    new = not os.path.exists(csv_path)
    f = open(csv_path, "a", newline="")
    w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
    if new:
        w.writeheader()
        f.flush()

    rng = random.Random(args.order_seed)
    seq = 0
    total = args.rounds * len(ARMS)
    t0all = time.time()
    print(f"[s2] {args.rounds} rounds x {len(ARMS)} arms = {total} runs",
          flush=True)

    try:
        for rnd in range(1, args.rounds + 1):
            order = ARMS[:]
            rng.shuffle(order)
            print(f"\n=== round {rnd}/{args.rounds} | "
                  f"{' -> '.join(a for a, _, _, _ in order)}", flush=True)
            for name, llm_cpus, load_cpus, load_n in order:
                if seq > 0:
                    time.sleep(args.cooldown)
                seq += 1
                tag = f"r{rnd:02d}_{name}"

                load = start_load(
                    args.loadgen, load_cpus, load_n,
                    os.path.join(args.outdir, "tokens", f"{tag}.load"))
                try:
                    cmd = [sys.executable, os.path.join(HERE, "run_once.py"),
                           "--server-bin", args.server_bin,
                           "--model", args.model, "--prompt", args.prompt,
                           "--threads", str(args.threads),
                           "--port", str(args.port),
                           "--tokens-out", os.path.join(
                               args.outdir, "tokens", f"{tag}.json"),
                           "--server-log", os.devnull]
                    if llm_cpus:
                        cmd += ["--cpus", llm_cpus]
                    t0 = time.time()
                    pr = subprocess.run(cmd, capture_output=True, text=True)
                finally:
                    load_stats = stop_load(load)

                if pr.returncode != 0:
                    print(f"  {name:16s} FAILED\n{pr.stderr[-1000:]}",
                          flush=True)
                    continue
                rec = json.loads(pr.stdout.strip().splitlines()[-1])
                rec.update({"arm": name, "round": rnd, "run_seq": seq,
                            "llm_cpus": llm_cpus or "unpinned",
                            "load_cpus": ("none" if not load_n
                                          else (load_cpus or "unpinned")),
                            "load_threads": load_n,
                            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")})
                rec.update(load_stats)
                w.writerow(rec)
                f.flush()
                eta = (time.time() - t0all) / seq * (total - seq) / 60
                lr = load_stats.get("load_rate")
                print(f"  {name:16s} ttft={rec['ttft_ms']:9.1f}  "
                      f"p50={rec['itl_p50_ms']:7.2f}  "
                      f"p95={rec['itl_p95_ms']:7.2f}  "
                      f"tps={rec['decode_tps']:6.2f}  "
                      f"load={('%.0f' % lr) if lr else '     -'}  "
                      f"({time.time() - t0:.0f}s, ETA {eta:.0f}m)", flush=True)
    finally:
        subprocess.run(["pkill", "-f", os.path.basename(args.loadgen)],
                       stderr=subprocess.DEVNULL)
        f.close()
    print(f"\n[s2] done -> {csv_path}", flush=True)


if __name__ == "__main__":
    main()
