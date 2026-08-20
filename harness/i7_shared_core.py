"""İŞ 7 — the one scenario left where priority could matter.

İŞ 3 found that nice/cgroup recovered <1% of the gap, but that test was
structurally unable to show anything: the competitor was pinned to E-cores
and the LLM decoded on P-cores, so the two never contended for the same
CPU. Priority cannot arbitrate a fight that is not happening.

Here the competitor is pinned to the SAME P-cores the LLM decodes on, so
they genuinely share. This is the configuration where affinity is powerless
by construction -- the LLM cannot escape, and the only lever left is who
gets the CPU first.

  S0_static   A_P8   + competitor on P8, normal    static baseline
  S1_switch   SWITCH + competitor on P8, normal    contended baseline
  S2_nice     SWITCH + competitor on P8, nice +19  classic priority
  S3_weight   SWITCH + competitor on P8, weight=1  cgroup v2 priority

Reading:
  priority recovers the gap  -> Linux already has the mechanism; sched_ext
                                would have to beat nice/cgroup, not merely
                                match them. Claim stays closed.
  priority does not recover  -> CFS grants a throughput share but not the
                                latency priority decode needs. That is a
                                measured gap sched_ext could target, and
                                the first result in this project that would
                                justify writing BPF.

Either outcome is decisive, which is why it is worth the machine time.
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

# (name, llm_arm, nice, cgroup weight, sched_idle)
ARMS = [
    ("S1_switch",  "SWITCH", 0, 0, False),
    ("S3_weight",  "SWITCH", 0, 1, False),
    ("S4_idle",    "SWITCH", 0, 0, True),
]

FIELDS = [
    "arm", "llm_arm", "round", "timestamp", "load_nice", "load_weight", "load_sched_idle",
    "load_cpus", "ttft_ms", "itl_p50_ms", "itl_p95_ms", "itl_p99_ms",
    "itl_max_ms", "decode_tps", "n_tokens", "load_rate", "load_iters",
    "total_migrations", "energy_j", "j_per_token", "temp_start_c",
    "temp_end_c", "switch_detected", "switch_lead_ms",
]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--server-bin", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--prompt", default=os.path.join(HERE, "prompt_512.txt"))
    p.add_argument("--rounds", type=int, default=6)
    p.add_argument("--cooldown", type=int, default=30)
    p.add_argument("--n-predict", type=int, default=256)
    p.add_argument("--load-threads", type=int, default=16)
    p.add_argument("--outdir", required=True)
    p.add_argument("--port", type=int, default=8108)
    p.add_argument("--order-seed", type=int, default=707)
    args = p.parse_args()

    os.makedirs(os.path.join(args.outdir, "runs"), exist_ok=True)
    csv_path = os.path.join(args.outdir, "i7.csv")
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
    print(f"[i7] {args.rounds} tur x {len(ARMS)} kol = {total} koşu "
          f"| rakip: {args.load_threads} thread, {P8} (LLM ile AYNI)",
          flush=True)

    for rnd in range(1, args.rounds + 1):
        order = ARMS[:]
        rng.shuffle(order)
        print(f"\n=== tur {rnd}/{args.rounds} | "
              f"{' -> '.join(a for a, _, _, _, _ in order)}", flush=True)
        for name, llm_arm, nice, weight, sidle in order:
            if seq > 0:
                time.sleep(args.cooldown)
            seq += 1
            out = os.path.join(args.outdir, "runs", f"r{rnd:02d}_{name}.json")
            cmd = [sys.executable, os.path.join(HERE, "phase_switch.py"),
                   "--server-bin", args.server_bin, "--model", args.model,
                   "--prompt", args.prompt, "--arm", llm_arm,
                   "--n-predict", str(args.n_predict),
                   "--port", str(args.port), "--out", out,
                   "--competitor", "loadgen",
                   "--load-threads", str(args.load_threads),
                   "--load-cpus", P8,
                   "--load-nice", str(nice), "--load-weight", str(weight)]
            if sidle:
                cmd.append("--load-sched-idle")
            t0 = time.time()
            pr = subprocess.run(cmd, capture_output=True, text=True)
            if pr.returncode != 0:
                print(f"  {name:11s} FAILED\n{pr.stderr[-900:]}", flush=True)
                continue
            rec = json.load(open(out))
            rec.update({"arm": name, "llm_arm": llm_arm, "round": rnd,
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")})
            w.writerow(rec)
            f.flush()
            eta = (time.time() - t0all) / seq * (total - seq) / 60
            print(f"  {name:11s} ttft={rec['ttft_ms']:8.0f}  "
                  f"p50={rec['itl_p50_ms']:7.2f}  p95={rec['itl_p95_ms']:7.2f}  "
                  f"tps={rec['decode_tps']:5.2f}  "
                  f"rakip={rec.get('load_rate')}  "
                  f"({time.time() - t0:.0f}s, ETA {eta:.0f}m)", flush=True)
    f.close()
    print(f"\n[i7] done -> {csv_path}", flush=True)


if __name__ == "__main__":
    main()
