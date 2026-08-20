"""Faz 0 / K3: repeat ONE configuration N times and record the spread.

This does not compare anything. Its only output is how much the same
configuration disagrees with itself on this machine. Every later claim in
the project is measured against that number.

Each run gets a fresh server process and a cooldown gap, so thermal state
is the main thing allowed to drift between runs -- and we record it, to see
whether it does.
"""

import argparse
import csv
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bench_lib as bl

HERE = os.path.dirname(os.path.abspath(__file__))

FIELDS = [
    "run", "timestamp", "ttft_ms", "itl_p50_ms", "itl_p95_ms", "itl_p99_ms",
    "itl_max_ms", "itl_mean_ms", "decode_tps", "n_tokens", "prompt_tokens",
    "temp_start_c", "temp_end_c", "temp_delta_c", "migrations",
    "ctx_switches", "threads_seen", "freq_p_avg_mhz", "freq_e_avg_mhz",
    "freq_samples", "threads", "cpus", "ctx", "batch", "ubatch", "seed",
    "n_predict",
]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--server-bin", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--prompt", default=os.path.join(HERE, "prompt_512.txt"))
    p.add_argument("--runs", type=int, default=20)
    p.add_argument("--cooldown", type=int, default=30)
    p.add_argument("--threads", type=int, default=8)
    p.add_argument("--cpus", default="")
    p.add_argument("--outdir", required=True)
    p.add_argument("--port", type=int, default=8081)
    args = p.parse_args()

    tokens_dir = os.path.join(args.outdir, "tokens")
    logs_dir = os.path.join(args.outdir, "server_logs")
    os.makedirs(tokens_dir, exist_ok=True)
    os.makedirs(logs_dir, exist_ok=True)

    csv_path = os.path.join(args.outdir, "runs.csv")
    new_file = not os.path.exists(csv_path)
    csv_f = open(csv_path, "a", newline="")
    writer = csv.DictWriter(csv_f, fieldnames=FIELDS, extrasaction="ignore")
    if new_file:
        writer.writeheader()
        csv_f.flush()

    label = args.cpus or "unpinned"
    print(f"[noise_floor] {args.runs} runs | threads={args.threads} "
          f"| cpus={label} | cooldown={args.cooldown}s", flush=True)

    for i in range(1, args.runs + 1):
        if i > 1:
            print(f"  cooldown {args.cooldown}s "
                  f"(pkg {bl.package_temp_c()}C)", flush=True)
            time.sleep(args.cooldown)

        cmd = [
            sys.executable, os.path.join(HERE, "run_once.py"),
            "--server-bin", args.server_bin,
            "--model", args.model,
            "--prompt", args.prompt,
            "--threads", str(args.threads),
            "--port", str(args.port),
            "--tokens-out", os.path.join(tokens_dir, f"run_{i:02d}.json"),
            "--server-log", os.path.join(logs_dir, f"run_{i:02d}.log"),
        ]
        if args.cpus:
            cmd += ["--cpus", args.cpus]

        t0 = time.time()
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            print(f"  run {i:02d} FAILED rc={proc.returncode}\n"
                  f"{proc.stderr[-1500:]}", flush=True)
            continue

        rec = json.loads(proc.stdout.strip().splitlines()[-1])
        rec["run"] = i
        rec["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        writer.writerow(rec)
        csv_f.flush()

        print(f"  run {i:02d}  ttft={rec['ttft_ms']:8.1f}ms  "
              f"p50={rec['itl_p50_ms']:6.2f}  p95={rec['itl_p95_ms']:6.2f}  "
              f"max={rec['itl_max_ms']:7.2f}  tps={rec['decode_tps']:5.2f}  "
              f"mig={rec['migrations']:6d}  "
              f"T={rec['temp_start_c']}->{rec['temp_end_c']}C  "
              f"({time.time() - t0:.0f}s)", flush=True)

    csv_f.close()
    print(f"[noise_floor] done -> {csv_path}", flush=True)


if __name__ == "__main__":
    main()
