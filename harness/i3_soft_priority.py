"""İŞ 3 — bound sched_ext's headroom before writing any BPF.

İŞ 6 left a measured gap: SWITCH runs at 9 748 ms with no competitor and
11 741 ms against an E-pinned saturating load. The argument for sched_ext is
that priority (preempt the competitor) can recover part of that, where
affinity structurally cannot.

Before accepting that, it has to be checked against the priority mechanisms
Linux already has. Both arms below tell CFS "this competitor matters less":

  nice +19        classic priority, weight ratio ~1:68 against nice 0
  CPUWeight=1     cgroup v2, weight ratio 1:10000 against the default 100

Same competitor placement as İŞ 6 (E-pinned loadgen, 16 threads) so the
numbers are comparable to it.

Reading:
  gap largely recovered -> sched_ext's marginal value is small; say so and
                           rewrite the claim
  gap not recovered     -> the likely reason is that CFS weight grants a
                           *throughput share* but not *latency priority*.
                           That turns the claim from "affinity cannot express
                           priority" into "CFS priority is also insufficient,
                           and here is the measured residual" -- a much
                           stronger position.

The competitor's own throughput is recorded too: nice and weight are not free.
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

# (name, nice, cgroup weight)
ARMS = [
    ("P1_normal", 0, 0),
    ("P2_nice19", 19, 0),
    ("P3_weight1", 0, 1),
]

FIELDS = [
    "arm", "round", "timestamp", "load_nice", "load_weight", "ttft_ms",
    "itl_p50_ms", "itl_p95_ms", "itl_p99_ms", "decode_tps", "n_tokens",
    "load_rate", "load_iters", "total_migrations", "energy_j", "j_per_token",
    "temp_start_c", "temp_end_c", "switch_detected", "switch_lead_ms",
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
    p.add_argument("--port", type=int, default=8107)
    p.add_argument("--order-seed", type=int, default=404)
    args = p.parse_args()

    os.makedirs(os.path.join(args.outdir, "runs"), exist_ok=True)
    csv_path = os.path.join(args.outdir, "i3.csv")
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
    print(f"[i3] {args.rounds} tur x {len(ARMS)} kol = {total} koşu",
          flush=True)

    for rnd in range(1, args.rounds + 1):
        order = ARMS[:]
        rng.shuffle(order)
        print(f"\n=== tur {rnd}/{args.rounds} | "
              f"{' -> '.join(a for a, _, _ in order)}", flush=True)
        for name, nice, weight in order:
            if seq > 0:
                time.sleep(args.cooldown)
            seq += 1
            out = os.path.join(args.outdir, "runs", f"r{rnd:02d}_{name}.json")
            cmd = [sys.executable, os.path.join(HERE, "phase_switch.py"),
                   "--server-bin", args.server_bin, "--model", args.model,
                   "--prompt", args.prompt, "--arm", "SWITCH",
                   "--n-predict", str(args.n_predict),
                   "--port", str(args.port), "--out", out,
                   "--competitor", "loadgen", "--load-threads", "16",
                   "--load-cpus", "16-23",
                   "--load-nice", str(nice), "--load-weight", str(weight)]
            t0 = time.time()
            pr = subprocess.run(cmd, capture_output=True, text=True)
            if pr.returncode != 0:
                print(f"  {name:11s} FAILED\n{pr.stderr[-900:]}", flush=True)
                continue
            rec = json.load(open(out))
            rec.update({"arm": name, "round": rnd,
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")})
            w.writerow(rec)
            f.flush()
            eta = (time.time() - t0all) / seq * (total - seq) / 60
            print(f"  {name:11s} ttft={rec['ttft_ms']:8.0f}  "
                  f"p50={rec['itl_p50_ms']:6.2f}  p95={rec['itl_p95_ms']:7.2f}  "
                  f"tps={rec['decode_tps']:5.2f}  "
                  f"rakip={rec.get('load_rate')}  "
                  f"({time.time() - t0:.0f}s, ETA {eta:.0f}m)", flush=True)
    f.close()
    print(f"\n[i3] done -> {csv_path}", flush=True)


if __name__ == "__main__":
    main()
