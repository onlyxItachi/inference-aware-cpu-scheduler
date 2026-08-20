"""İŞ 5 — is llama-server's built-in -t/-tb split enough on its own?

Source reading (this session) found a split result:

  thread COUNT per phase  -- IS wired into llama-server
      common.cpp: cparams.n_threads (decode) / n_threads_batch (prefill)
  CPU AFFINITY per phase  -- is NOT
      ggml_threadpool_new + llama_attach_threadpool are called only in
      tools/completion and llama-bench, never in the server, so -C/-Cb
      cpumasks are parsed and then ignored there.

İŞ 4 showed the win comes from running prefill on P+E and decode on P only.
The question this answers: can thread count alone approximate that, with no
patch and no scheduler?

  A  -t 8  -tb 8   on P-cores        reference (İŞ 4's A_P8)
  B  -t 8  -tb 16  on P+E            phase-aware by thread count only
  C  -t 16 -tb 16  on P+E            İŞ 4's C_P8_E8, for comparison

B is the interesting arm. Its decode threads are only 8, but its cpuset
still contains the E-cores, so nothing stops the kernel putting those 8
threads on E-cores -- which is exactly the placement İŞ 4 showed costs
ITL p95 ~9%. If B keeps A's ITL while gaining C's prefill, the policy is
free today. If B's ITL degrades toward C, affinity separation is required
and thread count alone is insufficient.
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
P8 = "0,2,4,6,8,10,12,14"
P8E8 = "0,2,4,6,8,10,12,14,16-23"

# (name, cpus, threads_decode, threads_batch)
ARMS = [
    ("A_t8_tb8_P",     P8,   8,  8),
    ("B_t8_tb16_PE",   P8E8, 8, 16),
    ("C_t16_tb16_PE",  P8E8, 16, 16),
]

FIELDS = [
    "arm", "round", "run_seq", "timestamp", "cpus", "threads",
    "threads_batch", "ttft_ms", "prefill_tps", "itl_p50_ms", "itl_p95_ms",
    "itl_p99_ms", "decode_tps", "n_tokens", "prompt_tokens", "temp_start_c",
    "temp_end_c", "migrations", "ctx_switches", "freq_p_busy_mhz",
    "freq_e_avg_mhz", "seed", "n_predict",
]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--server-bin", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--prompt", default=os.path.join(HERE, "prompt_512.txt"))
    p.add_argument("--rounds", type=int, default=5)
    p.add_argument("--cooldown", type=int, default=30)
    p.add_argument("--n-predict", type=int, default=256)
    p.add_argument("--outdir", required=True)
    p.add_argument("--port", type=int, default=8104)
    p.add_argument("--order-seed", type=int, default=101)
    args = p.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    csv_path = os.path.join(args.outdir, "i5.csv")
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
    print(f"[i5] {args.rounds} tur x {len(ARMS)} kol = {total} koşu",
          flush=True)

    for rnd in range(1, args.rounds + 1):
        order = ARMS[:]
        rng.shuffle(order)
        print(f"\n=== tur {rnd}/{args.rounds} | "
              f"{' -> '.join(a for a, _, _, _ in order)}", flush=True)
        for name, cpus, td, tb in order:
            if seq > 0:
                time.sleep(args.cooldown)
            seq += 1
            cmd = [sys.executable, os.path.join(HERE, "run_once.py"),
                   "--server-bin", args.server_bin, "--model", args.model,
                   "--prompt", args.prompt, "--threads", str(td),
                   "--threads-batch", str(tb), "--cpus", cpus,
                   "--port", str(args.port),
                   "--n-predict", str(args.n_predict),
                   "--server-log", os.devnull]
            t0 = time.time()
            pr = subprocess.run(cmd, capture_output=True, text=True)
            if pr.returncode != 0:
                print(f"  {name:15s} FAILED\n{pr.stderr[-900:]}", flush=True)
                continue
            rec = json.loads(pr.stdout.strip().splitlines()[-1])
            rec["prefill_tps"] = round(
                rec["prompt_tokens"] / (rec["ttft_ms"] / 1000.0), 2)
            rec.update({"arm": name, "round": rnd, "run_seq": seq,
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")})
            w.writerow(rec)
            f.flush()
            eta = (time.time() - t0all) / seq * (total - seq) / 60
            print(f"  {name:15s} prefill={rec['prefill_tps']:6.2f}  "
                  f"ttft={rec['ttft_ms']:8.0f}  decode={rec['decode_tps']:5.2f}  "
                  f"p95={rec['itl_p95_ms']:7.2f}  "
                  f"({time.time() - t0:.0f}s, ETA {eta:.0f}m)", flush=True)
    f.close()
    print(f"\n[i5] done -> {csv_path}", flush=True)


if __name__ == "__main__":
    main()
