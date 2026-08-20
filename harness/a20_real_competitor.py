"""U2 + U8 — GERÇEK bir rakiple, gerçek bir rakip metriğiyle.

Neden gerekti: eski build rakibi sabit 2 geçiş koşuyordu (~4 s) ama ölçüm
penceresi ~33 s'ydi, yani rakip zamanın %87'sinde YOKTU. Üstüne
`build_wall_s` build'i değil isteğin süresini ölçüyordu (36 koşuda fark
+0.10 s medyan). İkisi birlikte "rakip build −%3.7" iddiasını geçersiz
kıldı: o sayı LLM'in kendi tamamlanma süresinin başka isimle yazılmış
hâliydi.

Şimdi build pencere boyunca döngüde koşuyor ve iş metriği tamamlanan
geçiş sayısı (build_passes / build_rate).

Beş kol iki soruyu birden cevaplıyor:

  U2 — "faz anahtarlama hem LLM'i hem rakibi iyileştiriyor" doğru mu?
       A_P8 / C_P8_E8 / SWITCH, hepsi normal öncelikli rakiple.
       SWITCH'in build_rate'i statiklerinkinden yüksekse iddia ayakta;
       değilse "iki taraflı kazanç" cümlesi düşer.

  U8 — `chrt --idle` tavsiyesi sentetik loadgen'den gerçek işe genelleniyor
       mu? SWITCH sabit, rakibin önceliği değişiyor: normal / idle / weight.

Aynı deneyde ölçülmelerinin sebebi: ikisi de aynı rakibe ve aynı LLM
koluna dayanıyor, ayrı koşulsa iki kez aynı taban ölçülürdü.
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

# (kol adı, phase_switch ek argümanları)
ARMS = [
    ("A_P8",         ["--arm", "A_P8"]),
    ("C_P8_E8",      ["--arm", "C_P8_E8"]),
    ("SWITCH",       ["--arm", "SWITCH"]),
    ("SWITCH_idle",  ["--arm", "SWITCH", "--load-sched-idle"]),
    ("SWITCH_weight", ["--arm", "SWITCH", "--load-weight", "1"]),
]

FIELDS = ["arm", "round", "timestamp", "ttft_ms", "itl_p50_ms", "itl_p95_ms",
          "itl_p99_ms", "decode_tps", "n_tokens", "energy_j", "j_per_token",
          "build_wall_s", "build_passes", "build_rate", "total_migrations",
          "temp_start_c", "temp_end_c", "switch_detected"]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--server-bin", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--prompt", default=os.path.join(HERE, "prompt_512.txt"))
    p.add_argument("--rounds", type=int, default=6)
    p.add_argument("--cooldown", type=int, default=30)
    p.add_argument("--port", type=int, default=8180)
    p.add_argument("--outdir", required=True)
    p.add_argument("--order-seed", type=int, default=2020)
    args = p.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    csv_path = os.path.join(args.outdir, "a20.csv")
    new = not os.path.exists(csv_path)
    f = open(csv_path, "a", newline="")
    w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
    if new:
        w.writeheader(); f.flush()

    rng = random.Random(args.order_seed)
    seq, total = 0, args.rounds * len(ARMS)
    t0all = time.time()
    print(f"[a20] {args.rounds} tur x {len(ARMS)} kol = {total} koşu "
          f"| rakip: make -j16 DÖNGÜDE (pencere boyunca)", flush=True)

    for rnd in range(1, args.rounds + 1):
        order = ARMS[:]
        rng.shuffle(order)
        print(f"\n=== tur {rnd}/{args.rounds}", flush=True)
        for arm, extra in order:
            if seq > 0:
                time.sleep(args.cooldown)
            seq += 1
            out = os.path.join(args.outdir, f"r{rnd:02d}_{arm}.json")
            t0 = time.time()
            r = subprocess.run(
                ["python3", os.path.join(HERE, "phase_switch.py"),
                 "--server-bin", args.server_bin, "--model", args.model,
                 "--prompt", args.prompt, "--competitor", "build",
                 "--port", str(args.port), "--out", out] + extra,
                capture_output=True, text=True)
            if r.returncode != 0 or not os.path.exists(out):
                print(f"  {arm:14s} FAILED {r.stderr.strip()[-180:]}",
                      flush=True)
                continue
            rec = json.load(open(out))
            rec.update({"arm": arm, "round": rnd,
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")})
            w.writerow(rec); f.flush()
            eta = (time.time() - t0all) / seq * (total - seq) / 60
            print(f"  {arm:14s} ttft={rec['ttft_ms']:8.0f} "
                  f"p50={rec['itl_p50_ms']:7.2f} p95={rec['itl_p95_ms']:7.2f} "
                  f"gecis={rec.get('build_passes')} "
                  f"hiz={rec.get('build_rate')} "
                  f"({time.time()-t0:.0f}s, ETA {eta:.0f}m)", flush=True)
    f.close()
    print(f"\n[a20] done -> {csv_path}")


if __name__ == "__main__":
    main()
