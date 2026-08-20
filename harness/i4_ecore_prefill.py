"""İŞ 4 — does prefill get faster if E-cores are added to it?

The frozen success criterion (CLAUDE.md) rules out the obvious phase-aware
move: returning cores during decode costs ITL ~7.7%, nearly 4x the 2% QoS
budget. The remaining direction is the opposite one -- give the LLM *extra*
cores during prefill, which K1 showed scales at 77% efficiency versus
decode's 49%.

Whether that works is genuinely open. llama.cpp runs one thread pool with a
barrier at every layer, so the slowest participant gates each barrier.
E-cores peak at 3.7 GHz against the P-cores' 5.0. Adding them adds
arithmetic but may also add barrier wait. Either outcome is informative:

  prefill faster -> "give prefill more" is a real mechanism, and phase
                    awareness has somewhere to earn its keep
  prefill slower -> heterogeneous barriers dominate, and the last
                    candidate mechanism for Phase 3 is closed off too

Arms hold P-core allocation constant and only add E-cores, so the E-cores
are the single variable.
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
    ("A_P8",     "0,2,4,6,8,10,12,14",                   8),
    ("B_P8_E4",  "0,2,4,6,8,10,12,14,16,17,18,19",      12),
    ("C_P8_E8",  "0,2,4,6,8,10,12,14,16-23",            16),
]

FIELDS = [
    "arm", "round", "run_seq", "timestamp", "cpus", "threads", "ttft_ms",
    "prefill_tps", "itl_p50_ms", "itl_p95_ms", "itl_p99_ms", "decode_tps",
    "n_tokens", "prompt_tokens", "temp_start_c", "temp_end_c", "migrations",
    "ctx_switches", "freq_p_busy_mhz", "freq_e_avg_mhz", "seed", "n_predict",
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
    p.add_argument("--port", type=int, default=8101)
    p.add_argument("--order-seed", type=int, default=77)
    args = p.parse_args()

    os.makedirs(os.path.join(args.outdir, "tokens"), exist_ok=True)
    csv_path = os.path.join(args.outdir, "i4.csv")
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
    print(f"[i4] {args.rounds} tur x {len(ARMS)} kol = {total} koşu",
          flush=True)

    for rnd in range(1, args.rounds + 1):
        order = ARMS[:]
        rng.shuffle(order)
        print(f"\n=== tur {rnd}/{args.rounds} | "
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
                print(f"  {name:10s} FAILED\n{pr.stderr[-900:]}", flush=True)
                continue
            rec = json.loads(pr.stdout.strip().splitlines()[-1])
            rec["prefill_tps"] = round(
                rec["prompt_tokens"] / (rec["ttft_ms"] / 1000.0), 2)
            rec.update({"arm": name, "round": rnd, "run_seq": seq,
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")})
            w.writerow(rec)
            f.flush()
            eta = (time.time() - t0all) / seq * (total - seq) / 60
            print(f"  {name:10s} ({threads:2d}t) prefill={rec['prefill_tps']:6.2f} tok/s  "
                  f"ttft={rec['ttft_ms']:8.0f}ms  decode={rec['decode_tps']:5.2f}  "
                  f"p95={rec['itl_p95_ms']:6.2f}  "
                  f"({time.time() - t0:.0f}s, ETA {eta:.0f}m)", flush=True)
    f.close()
    print(f"\n[i4] done -> {csv_path}", flush=True)


if __name__ == "__main__":
    main()
