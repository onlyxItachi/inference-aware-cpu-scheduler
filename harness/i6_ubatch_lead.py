"""İŞ 3 — what actually produces the detector's ~135 ms head start?

Prompt length was the wrong variable: the lead stayed fixed at -132..-139 ms
while prefill duration varied 25.8x. n_ubatch is the right one, because it
sets barrier frequency directly -- prefill is chopped into ubatch-sized
chunks and each chunk synchronises the thread pool.

Prompt is held at 496 tokens, so the number of ubatches changes with the
setting: 496/512 = 1 chunk, 496/256 = 2, 496/128 = 4.

  lead scales with ubatch  -> barrier frequency is the mechanism, explained
  lead stays fixed         -> the barrier hypothesis is eliminated too, and
                              the mechanism remains unknown. Say so plainly;
                              do not invent a third story to fit.
"""

import argparse
import json
import os
import random
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
P8 = "0,2,4,6,8,10,12,14"
UBATCHES = [128, 256, 512]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--server-bin", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--prompt", default=os.path.join(HERE, "prompt_512.txt"))
    p.add_argument("--rounds", type=int, default=4)
    p.add_argument("--cooldown", type=int, default=30)
    p.add_argument("--n-predict", type=int, default=192)
    p.add_argument("--outdir", required=True)
    p.add_argument("--port", type=int, default=8106)
    p.add_argument("--order-seed", type=int, default=303)
    args = p.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    rng = random.Random(args.order_seed)
    seq = 0
    total = args.rounds * len(UBATCHES)
    t0all = time.time()
    print(f"[i6] {args.rounds} tur x {len(UBATCHES)} ubatch = {total} koşu",
          flush=True)

    for rnd in range(1, args.rounds + 1):
        order = UBATCHES[:]
        rng.shuffle(order)
        print(f"\n=== tur {rnd}/{args.rounds} | ubatch {order}", flush=True)
        for ub in order:
            if seq > 0:
                time.sleep(args.cooldown)
            seq += 1
            out = os.path.join(args.outdir, f"r{rnd:02d}_ub{ub}.json")
            cmd = [sys.executable, os.path.join(HERE, "h5_capture.py"),
                   "--server-bin", args.server_bin, "--model", args.model,
                   "--prompt", args.prompt, "--cpus", P8, "--threads", "8",
                   "--n-predict", str(args.n_predict), "--interval-ms", "20",
                   "--port", str(args.port), "--out", out,
                   "--ubatch", str(ub)]
            t0 = time.time()
            pr = subprocess.run(cmd, capture_output=True, text=True)
            if pr.returncode != 0:
                print(f"  ub{ub:<4d} FAILED\n{pr.stderr[-800:]}", flush=True)
                continue
            d = json.load(open(out))
            eta = (time.time() - t0all) / seq * (total - seq) / 60
            print(f"  ub{ub:<4d} ttft={d['ttft_ms']:8.0f}ms  "
                  f"p50={d['itl_p50_ms']:6.2f}  "
                  f"({time.time() - t0:.0f}s, ETA {eta:.0f}m)", flush=True)
    print(f"\n[i6] done -> {args.outdir}", flush=True)


if __name__ == "__main__":
    main()
