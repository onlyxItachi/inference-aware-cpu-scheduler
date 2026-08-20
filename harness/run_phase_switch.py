"""Interleaved sweep for İŞ 2: static A, static C, and the live switcher."""

import argparse
import csv
import json
import os
import random
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ARMS = ["A_P8", "C_P8_E8", "SWITCH"]

FIELDS = [
    "arm", "round", "timestamp", "cpus", "threads_decode", "threads_batch",
    "ttft_ms", "prefill_tps", "itl_p50_ms", "itl_p95_ms", "itl_p99_ms",
    "itl_max_ms", "decode_tps", "n_tokens", "total_migrations",
    "total_ctx_switches", "energy_j", "j_per_token", "temp_start_c",
    "temp_end_c", "switch_detected", "switch_lead_ms",
    "switch_apply_cost_us", "migration_burst_200ms", "ctx_burst_200ms",
    "itl_tail_mean_ms", "itl_first10_ms", "load_threads", "load_cpus",
    "load_rate", "load_iters", "competitor", "build_wall_s",
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
    p.add_argument("--port", type=int, default=8105)
    p.add_argument("--order-seed", type=int, default=202)
    p.add_argument("--load-threads", type=int, default=0)
    p.add_argument("--load-cpus", default="16-23")
    p.add_argument("--competitor", default="none",
                   choices=["none", "loadgen", "build"])
    args = p.parse_args()

    os.makedirs(os.path.join(args.outdir, "runs"), exist_ok=True)
    csv_path = os.path.join(args.outdir, "switch.csv")
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
    print(f"[switch] {args.rounds} tur x {len(ARMS)} kol = {total} koşu",
          flush=True)

    for rnd in range(1, args.rounds + 1):
        order = ARMS[:]
        rng.shuffle(order)
        print(f"\n=== tur {rnd}/{args.rounds} | {' -> '.join(order)}",
              flush=True)
        for arm in order:
            if seq > 0:
                time.sleep(args.cooldown)
            seq += 1
            out = os.path.join(args.outdir, "runs", f"r{rnd:02d}_{arm}.json")
            cmd = [sys.executable, os.path.join(HERE, "phase_switch.py"),
                   "--server-bin", args.server_bin, "--model", args.model,
                   "--prompt", args.prompt, "--arm", arm,
                   "--n-predict", str(args.n_predict),
                   "--port", str(args.port), "--out", out,
                   "--load-threads", str(args.load_threads),
                   "--load-cpus", args.load_cpus,
                   "--competitor", args.competitor]
            t0 = time.time()
            pr = subprocess.run(cmd, capture_output=True, text=True)
            if pr.returncode != 0:
                print(f"  {arm:10s} FAILED\n{pr.stderr[-900:]}", flush=True)
                continue
            rec = json.load(open(out))
            rec["prefill_tps"] = round(496 / (rec["ttft_ms"] / 1000.0), 2)
            rec.update({"round": rnd,
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")})
            rec["itl_first10_ms"] = json.dumps(rec.get("itl_first10_ms"))
            w.writerow(rec)
            f.flush()
            eta = (time.time() - t0all) / seq * (total - seq) / 60
            lead = rec.get("switch_lead_ms")
            print(f"  {arm:10s} ttft={rec['ttft_ms']:8.0f}  "
                  f"p50={rec['itl_p50_ms']:6.2f}  p95={rec['itl_p95_ms']:7.2f}  "
                  f"tps={rec['decode_tps']:5.2f}  "
                  f"J/tok={rec['j_per_token']}  "
                  f"lead={lead if lead is not None else '-'}  "
                  f"burst={rec.get('migration_burst_200ms')}  "
                  f"rakip={rec.get('load_rate') or rec.get('build_wall_s')}  "
                  f"({time.time() - t0:.0f}s, ETA {eta:.0f}m)", flush=True)
    f.close()
    print(f"\n[switch] done -> {csv_path}", flush=True)


if __name__ == "__main__":
    main()
