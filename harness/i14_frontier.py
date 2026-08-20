"""U1 — statik Pareto cephesi: ara kollar.

Manşet iddia ("faz anahtarlama statikleri Pareto olarak baskılıyor") şimdiye
kadar YALNIZCA iki uç noktaya karşı ölçüldü: A_P8 (hiç E-core yok) ve
C_P8_E8 (tüm E-core'lar). Bir hakemin ilk soracağı şey ara noktalardır:
belki P8+E2 hem TTFT'yi hem ITL'yi aynı anda iyileştiriyor ve SWITCH'in
yaptığını statik olarak yapıyor.

Bu deney o soruyu kapatıyor. Altı kol × iki senaryo, interleaved.

Beklenti önceden yazılıyor (sonradan uydurma olmasın): SWITCH cephenin
DIŞINDA kalır, çünkü prefill kazancının tamamını alıp decode hasarını
sıfırlıyor. Tutmazsa iddia "iki uç noktayı yener"e daraltılır ve öyle
yazılır.
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
P8 = [0, 2, 4, 6, 8, 10, 12, 14]

# (kol adı, phase_switch argümanları)
def _static(n_e):
    cpus = P8 + list(range(16, 16 + n_e))
    return ["--arm", "STATIC",
            "--static-cpus", ",".join(map(str, cpus)),
            "--static-threads", str(len(cpus))]

ARMS = [
    ("A_P8",    ["--arm", "A_P8"]),
    ("P8_E2",   _static(2)),
    ("P8_E4",   _static(4)),
    ("P8_E6",   _static(6)),
    ("C_P8_E8", ["--arm", "C_P8_E8"]),
    ("SWITCH",  ["--arm", "SWITCH"]),
]

SCENARIOS = ["none", "build"]

FIELDS = ["arm", "scenario", "round", "timestamp", "ttft_ms", "itl_p50_ms",
          "itl_p95_ms", "itl_p99_ms", "decode_tps", "n_tokens", "energy_j",
          "j_per_token", "total_migrations", "temp_start_c", "temp_end_c",
          "switch_detected", "build_wall_s"]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--server-bin", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--prompt", default=os.path.join(HERE, "prompt_512.txt"))
    p.add_argument("--rounds", type=int, default=6)
    p.add_argument("--cooldown", type=int, default=30)
    p.add_argument("--outdir", required=True)
    p.add_argument("--port", type=int, default=8140)
    p.add_argument("--order-seed", type=int, default=1414)
    args = p.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    csv_path = os.path.join(args.outdir, "i14.csv")
    new = not os.path.exists(csv_path)
    f = open(csv_path, "a", newline="")
    w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
    if new:
        w.writeheader(); f.flush()

    cells = [(a, s) for s in SCENARIOS for a in ARMS]
    rng = random.Random(args.order_seed)
    seq, total = 0, args.rounds * len(cells)
    t0all = time.time()
    print(f"[i14] {args.rounds} tur x {len(cells)} hücre = {total} koşu",
          flush=True)

    for rnd in range(1, args.rounds + 1):
        order = cells[:]
        rng.shuffle(order)
        print(f"\n=== tur {rnd}/{args.rounds}", flush=True)
        for (arm, extra), scen in order:
            if seq > 0:
                time.sleep(args.cooldown)
            seq += 1
            out = os.path.join(args.outdir, f"r{rnd:02d}_{arm}_{scen}.json")
            cmd = ["python3", os.path.join(HERE, "phase_switch.py"),
                   "--server-bin", args.server_bin, "--model", args.model,
                   "--prompt", args.prompt, "--port", str(args.port),
                   "--competitor", scen, "--out", out] + extra
            t0 = time.time()
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0 or not os.path.exists(out):
                print(f"  {arm:8s} {scen:5s} FAILED rc={r.returncode} "
                      f"{r.stderr.strip()[-200:]}", flush=True)
                continue
            with open(out) as fh:
                rec = json.load(fh)
            rec.update({"arm": arm, "scenario": scen, "round": rnd,
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")})
            w.writerow(rec); f.flush()
            eta = (time.time() - t0all) / seq * (total - seq) / 60
            print(f"  {arm:8s} {scen:5s} ttft={rec.get('ttft_ms',0):8.0f} "
                  f"p95={rec.get('itl_p95_ms',0):7.2f} "
                  f"tps={rec.get('decode_tps',0):5.2f} "
                  f"build={rec.get('build_wall_s')} "
                  f"({time.time()-t0:.0f}s, ETA {eta:.0f}m)", flush=True)
    f.close()
    print(f"\n[i14] done -> {csv_path}", flush=True)


if __name__ == "__main__":
    main()
