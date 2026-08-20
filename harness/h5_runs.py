"""Collect H5 telemetry runs across two placements, interleaved.

Two placements rather than one so the detector is not tuned to a single
configuration: if a threshold only separates the phases when the process is
pinned, it is not a general phase detector.
"""

import argparse
import os
import random
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))

CONFIGS = [
    ("pinned",   "0,2,4,6,8,10,12,14"),
    ("unpinned", ""),
]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--server-bin", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--prompt", default=os.path.join(HERE, "prompt_512.txt"))
    p.add_argument("--rounds", type=int, default=5)
    p.add_argument("--cooldown", type=int, default=30)
    p.add_argument("--outdir", required=True)
    p.add_argument("--order-seed", type=int, default=5)
    args = p.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    rng = random.Random(args.order_seed)
    seq = 0
    total = args.rounds * len(CONFIGS)
    t0all = time.time()
    print(f"[h5] {args.rounds} rounds x {len(CONFIGS)} = {total} runs",
          flush=True)

    for rnd in range(1, args.rounds + 1):
        order = CONFIGS[:]
        rng.shuffle(order)
        for name, cpus in order:
            if seq > 0:
                time.sleep(args.cooldown)
            seq += 1
            out = os.path.join(args.outdir, f"r{rnd:02d}_{name}.json")
            cmd = [sys.executable, os.path.join(HERE, "h5_capture.py"),
                   "--server-bin", args.server_bin, "--model", args.model,
                   "--prompt", args.prompt, "--cpus", cpus,
                   "--threads", "8", "--n-predict", "256",
                   "--interval-ms", "20", "--out", out]
            t0 = time.time()
            pr = subprocess.run(cmd, capture_output=True, text=True)
            if pr.returncode != 0:
                print(f"  {name:9s} FAILED\n{pr.stderr[-800:]}", flush=True)
                continue
            eta = (time.time() - t0all) / seq * (total - seq) / 60
            print(f"  r{rnd:02d} {name:9s} ok  "
                  f"({time.time() - t0:.0f}s, ETA {eta:.0f}m)", flush=True)
    print("[h5] done", flush=True)


if __name__ == "__main__":
    main()
