"""K1 — where does decode stop scaling with cores?

CLAUDE.md's K1: if decode is memory-bandwidth-bound, adding cores stops
helping early, and a scheduler's room to manoeuvre is correspondingly
narrow. That is not bad news -- it may be the finding itself.

Design: N threads on N *distinct physical* P-cores, so thread count and
physical core count rise together and neither SMT sharing nor P/E mixing
contaminates the curve. E2 showed that letting threads outnumber physical
cores triggers a load-balancer migration storm, so every arm here keeps
1 thread per physical core.

  t2   0,2                     2 cores
  t4   0,2,4,6                 4 cores
  t6   0,2,4,6,8,10            6 cores
  t8   0,2,4,6,8,10,12,14      8 cores  (all physical P-cores)
  t16  0-15                   8 cores, 16 threads -- does SMT add anything
                              once physical cores are exhausted?

KNOWN CONFOUND: per CLAUDE.md, CPU 8-11 (physical cores 4-5) are Intel
favored cores clocking to 5200 MHz vs 5000. t6 and t8 include them, t2 and
t4 do not, so the upper arms get a small frequency advantage. This inflates
apparent scaling slightly -- meaning a saturation result is, if anything,
understated. Recorded rather than corrected.

Interleaved, for the non-thermal session drift found in Faz 0.
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

# (name, cpus, threads) -- 1 thread per distinct physical P-core
ARMS = [
    ("t2",  "0,2",                  2),
    ("t4",  "0,2,4,6",              4),
    ("t6",  "0,2,4,6,8,10",         6),
    ("t8",  "0,2,4,6,8,10,12,14",   8),
    ("t16", "0-15",                16),
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
    p.add_argument("--n-predict", type=int, default=256)
    p.add_argument("--outdir", required=True)
    p.add_argument("--port", type=int, default=8085)
    p.add_argument("--order-seed", type=int, default=7)
    args = p.parse_args()

    os.makedirs(os.path.join(args.outdir, "tokens"), exist_ok=True)
    csv_path = os.path.join(args.outdir, "k1.csv")
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
    print(f"[k1] {args.rounds} rounds x {len(ARMS)} arms = {total} runs",
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
                   "--n-predict", str(args.n_predict),
                   "--tokens-out",
                   os.path.join(args.outdir, "tokens", f"{tag}.json"),
                   "--server-log", os.devnull]
            t0 = time.time()
            pr = subprocess.run(cmd, capture_output=True, text=True)
            if pr.returncode != 0:
                print(f"  {name:5s} FAILED\n{pr.stderr[-1000:]}", flush=True)
                continue
            rec = json.loads(pr.stdout.strip().splitlines()[-1])
            rec.update({"arm": name, "round": rnd, "run_seq": seq,
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")})
            w.writerow(rec)
            f.flush()
            eta = (time.time() - t0all) / seq * (total - seq) / 60
            print(f"  {name:5s} ({threads:2d}t) ttft={rec['ttft_ms']:9.1f}  "
                  f"p50={rec['itl_p50_ms']:7.2f}  tps={rec['decode_tps']:6.2f}  "
                  f"mig={rec['migrations']:8d}  "
                  f"({time.time() - t0:.0f}s, ETA {eta:.0f}m)", flush=True)
    f.close()
    print(f"\n[k1] done -> {csv_path}", flush=True)


if __name__ == "__main__":
    main()
