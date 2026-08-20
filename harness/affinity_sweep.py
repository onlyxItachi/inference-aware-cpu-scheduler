"""Faz 0: affinity variants, measured interleaved.

Faz 0 found a session drift that is NOT thermal: over 20 runs TTFT rose
~0.74% with r=+0.671 against run number, while showing no significant
correlation with package temperature. Measuring configurations in blocks
would therefore manufacture a ~0.8% difference between the first and last
arm -- the same order of magnitude as effects we care about.

So: every round runs every variant exactly once, in a shuffled order.
Drift then spreads across all arms instead of loading onto one, and the
round index is recorded so any residual trend stays visible in analysis.

All arms hold threads=8 constant; only placement changes.
"""

import argparse
import csv
import json
import os
import random
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bench_lib as bl

HERE = os.path.dirname(os.path.abspath(__file__))

# (name, taskset cpu list). "" = unpinned.
VARIANTS = [
    ("unpinned",     ""),
    # 8 threads on 8 distinct physical P-cores, no sibling sharing.
    ("p_nosmt",      "0,2,4,6,8,10,12,14"),
    # 8 threads free across all 16 logical P-CPUs; the scheduler is allowed
    # to use siblings but will generally prefer idle physical cores.
    ("p_all",        "0-15"),
    # 8 threads confined to 4 physical cores' 8 siblings: forces SMT
    # contention, at the cost of also halving physical core count.
    ("p_smt_forced", "0-7"),
    ("e_only",       "16-23"),
]

FIELDS = [
    "variant", "round", "run_seq", "timestamp", "ttft_ms", "itl_p50_ms",
    "itl_p95_ms", "itl_p99_ms", "itl_max_ms", "itl_mean_ms", "decode_tps",
    "n_tokens", "prompt_tokens", "temp_start_c", "temp_end_c",
    "temp_delta_c", "migrations", "ctx_switches", "threads_seen",
    "freq_p_avg_mhz", "freq_p_busy_mhz", "freq_e_avg_mhz", "freq_samples",
    "threads", "cpus", "ctx", "batch", "ubatch", "seed", "n_predict",
]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--server-bin", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--prompt", default=os.path.join(HERE, "prompt_512.txt"))
    p.add_argument("--rounds", type=int, default=10)
    p.add_argument("--cooldown", type=int, default=30)
    p.add_argument("--threads", type=int, default=8)
    p.add_argument("--outdir", required=True)
    p.add_argument("--port", type=int, default=8082)
    p.add_argument("--order-seed", type=int, default=1337,
                   help="seeds the per-round shuffle so the order is reproducible")
    args = p.parse_args()

    tokens_dir = os.path.join(args.outdir, "tokens")
    logs_dir = os.path.join(args.outdir, "server_logs")
    os.makedirs(tokens_dir, exist_ok=True)
    os.makedirs(logs_dir, exist_ok=True)

    csv_path = os.path.join(args.outdir, "affinity.csv")
    new_file = not os.path.exists(csv_path)
    csv_f = open(csv_path, "a", newline="")
    writer = csv.DictWriter(csv_f, fieldnames=FIELDS, extrasaction="ignore")
    if new_file:
        writer.writeheader()
        csv_f.flush()

    rng = random.Random(args.order_seed)
    order_log = []
    seq = 0
    total = args.rounds * len(VARIANTS)
    t_start = time.time()

    print(f"[affinity] {args.rounds} rounds x {len(VARIANTS)} variants "
          f"= {total} runs | threads={args.threads} | "
          f"cooldown={args.cooldown}s | order-seed={args.order_seed}",
          flush=True)

    for rnd in range(1, args.rounds + 1):
        order = VARIANTS[:]
        rng.shuffle(order)
        order_log.append([v for v, _ in order])
        print(f"\n=== round {rnd}/{args.rounds} | order: "
              f"{' -> '.join(v for v, _ in order)}", flush=True)

        for name, cpus in order:
            if seq > 0:
                time.sleep(args.cooldown)
            seq += 1

            tag = f"r{rnd:02d}_{name}"
            cmd = [
                sys.executable, os.path.join(HERE, "run_once.py"),
                "--server-bin", args.server_bin,
                "--model", args.model,
                "--prompt", args.prompt,
                "--threads", str(args.threads),
                "--port", str(args.port),
                "--tokens-out", os.path.join(tokens_dir, f"{tag}.json"),
                "--server-log", os.path.join(logs_dir, f"{tag}.log"),
            ]
            if cpus:
                cmd += ["--cpus", cpus]

            t0 = time.time()
            proc = subprocess.run(cmd, capture_output=True, text=True)
            if proc.returncode != 0:
                print(f"  {name:13s} FAILED rc={proc.returncode}\n"
                      f"{proc.stderr[-1200:]}", flush=True)
                continue

            rec = json.loads(proc.stdout.strip().splitlines()[-1])
            rec.update({"variant": name, "round": rnd, "run_seq": seq,
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")})
            writer.writerow(rec)
            csv_f.flush()

            eta = (time.time() - t_start) / seq * (total - seq) / 60
            print(f"  {name:13s} ttft={rec['ttft_ms']:9.1f}  "
                  f"p50={rec['itl_p50_ms']:7.2f}  p95={rec['itl_p95_ms']:7.2f}  "
                  f"tps={rec['decode_tps']:5.2f}  mig={rec['migrations']:6d}  "
                  f"T={rec['temp_start_c']:.0f}->{rec['temp_end_c']:.0f}C  "
                  f"({time.time() - t0:.0f}s, ETA {eta:.0f}m)", flush=True)

    csv_f.close()
    with open(os.path.join(args.outdir, "order_log.json"), "w") as f:
        json.dump({"order_seed": args.order_seed, "rounds": order_log}, f,
                  indent=2)
    print(f"\n[affinity] done -> {csv_path}", flush=True)


if __name__ == "__main__":
    main()
