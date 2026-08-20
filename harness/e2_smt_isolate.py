"""E2 — separate "fewer physical cores" from "SMT siblings available".

p_smt_forced (8 threads on CPU 0-7) changed two things at once relative to
p_all: physical cores dropped 8 -> 4, AND SMT sibling sharing began. Its
~1.03M migrations therefore cannot be attributed to either cause.

Arms A-C all sit on the SAME four physical cores; only sibling availability
and oversubscription differ:

  A  0-7      8 threads   4 cores, siblings available   <- the storm case
  B  0,2,4,6  8 threads   4 cores, NO sibling, 2:1 oversubscribed
  C  0,2,4,6  4 threads   4 cores, 1:1, clean
  D  0-15     8 threads   8 cores                       <- reference

Discriminating logic: if B also storms, the cause is oversubscription and
contention, not SMT. If B stays calm, then merely *having a sibling to move
to* is what invites the scheduler to thrash -- a move it prices as free
because L1/L2 are shared, while it evidently is not free for throughput.

Note C changes thread count, so its throughput is not directly comparable
to A/B; it is here as the uncontended reference on the same four cores.

Interleaved for the same reason as the affinity sweep: Faz 0 found a
non-thermal session drift.
"""

import argparse
import csv
import json
import os
import random
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))

# (name, cpus, threads)
ARMS = [
    ("A_4core_smt",     "0-7",     8),
    ("B_4core_nosmt",   "0,2,4,6", 8),
    ("C_4core_1to1",    "0,2,4,6", 4),
    ("D_8core_ref",     "0-15",    8),
]

FIELDS = [
    "arm", "round", "run_seq", "timestamp", "cpus", "threads", "ttft_ms",
    "itl_p50_ms", "itl_p95_ms", "itl_p99_ms", "itl_max_ms", "itl_mean_ms",
    "decode_tps", "n_tokens", "prompt_tokens", "temp_start_c", "temp_end_c",
    "temp_delta_c", "migrations", "ctx_switches", "threads_seen",
    "freq_p_avg_mhz", "freq_p_busy_mhz", "freq_e_avg_mhz", "seed",
    "n_predict", "ctx", "batch", "ubatch",
]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--server-bin", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--prompt", default=os.path.join(HERE, "prompt_512.txt"))
    p.add_argument("--rounds", type=int, default=6)
    p.add_argument("--cooldown", type=int, default=30)
    p.add_argument("--outdir", required=True)
    p.add_argument("--port", type=int, default=8084)
    p.add_argument("--order-seed", type=int, default=99)
    args = p.parse_args()

    os.makedirs(os.path.join(args.outdir, "tokens"), exist_ok=True)
    csv_path = os.path.join(args.outdir, "e2.csv")
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
    print(f"[e2] {args.rounds} rounds x {len(ARMS)} arms = {total} runs",
          flush=True)

    for rnd in range(1, args.rounds + 1):
        order = ARMS[:]
        rng.shuffle(order)
        print(f"\n=== round {rnd}/{args.rounds} | "
              f"{' -> '.join(a for a, _, _ in order)}", flush=True)
        for name, cpus, threads in order:
            if seq > 0:
                time.sleep(args.cooldown)
            seq += 1
            tag = f"r{rnd:02d}_{name}"
            cmd = [sys.executable, os.path.join(HERE, "run_once.py"),
                   "--server-bin", args.server_bin, "--model", args.model,
                   "--prompt", args.prompt, "--threads", str(threads),
                   "--cpus", cpus, "--port", str(args.port),
                   "--tokens-out",
                   os.path.join(args.outdir, "tokens", f"{tag}.json"),
                   "--server-log", os.devnull]
            t0 = time.time()
            pr = subprocess.run(cmd, capture_output=True, text=True)
            if pr.returncode != 0:
                print(f"  {name:16s} FAILED\n{pr.stderr[-1000:]}", flush=True)
                continue
            rec = json.loads(pr.stdout.strip().splitlines()[-1])
            rec.update({"arm": name, "round": rnd, "run_seq": seq,
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")})
            w.writerow(rec)
            f.flush()
            eta = (time.time() - t0all) / seq * (total - seq) / 60
            print(f"  {name:16s} ttft={rec['ttft_ms']:9.1f}  "
                  f"p50={rec['itl_p50_ms']:7.2f}  tps={rec['decode_tps']:5.2f}  "
                  f"mig={rec['migrations']:8d}  cs={rec['ctx_switches']:9d}  "
                  f"({time.time() - t0:.0f}s, ETA {eta:.0f}m)", flush=True)
    f.close()
    print(f"\n[e2] done -> {csv_path}", flush=True)


if __name__ == "__main__":
    main()
