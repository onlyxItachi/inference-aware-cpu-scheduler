"""U1 (rakipli) — statik Pareto cephesi, GERÇEK rakip altında.

§11.1 cepheyi rakipsiz senaryoda kapattı. Rakipli taraf açık kaldı ve
sebebi iki katmanlı:

  - İlk "build patlaması" senaryosunun çekişmeli olmadığı §11.2'de ortaya
    çıktı (rakip pencerenin ~%13'ünde vardı).
  - Düzeltilmiş a20 deneyi gerçek bir rakip kullanıyor ama yalnızca üç kol
    içeriyor (A_P8, C_P8_E8, SWITCH). Ara kollar yok.

Yani "ya bir ara statik konfigürasyon rakip altında SWITCH'i baskılıyorsa?"
sorusunun ölçülmüş cevabı yok. Bu deney onu kapatıyor.

Protokol a20'nin AYNISI (rakip pencere boyunca döngüde `make -j16`, iş
metriği tamamlanan geçiş sayısı). Altı kol da AYNI OTURUMDA koşuluyor;
a20'nin eski üç kol sayılarıyla kıyaslama yapılmıyor, çünkü bölüm 1.2'de
ölçülen oturum-içi drift %0.5-0.7 ve karşılaştırılacak farklar bu
mertebede olabilir.

Ön kayıt (sonradan uydurma olmasın): rakipsiz senaryoda ara kollar
cephede duramadı, çünkü decode hasarı basamak (2 E-core bedelin çoğunu
ödetiyor) ama prefill kazancı kademeli. Rakip altında bu değişebilir:
E-core'lar artık rakiple paylaşılıyor, yani "E-core ekle" hem daha az
kazandırabilir hem de rakibi tahliye ederek dolaylı fayda sağlayabilir.
Sonuç ne çıkarsa raporlanacak; bir ara kol SWITCH'i baskılarsa manşet
iddia daralır.
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
P8 = [0, 2, 4, 6, 8, 10, 12, 14]


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
    p.add_argument("--port", type=int, default=8190)
    p.add_argument("--outdir", required=True)
    p.add_argument("--order-seed", type=int, default=2121)
    args = p.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    csv_path = os.path.join(args.outdir, "a21.csv")
    new = not os.path.exists(csv_path)
    f = open(csv_path, "a", newline="")
    w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
    if new:
        w.writeheader(); f.flush()

    rng = random.Random(args.order_seed)
    seq, total = 0, args.rounds * len(ARMS)
    t0all = time.time()
    print(f"[a21] {args.rounds} tur x {len(ARMS)} kol = {total} koşu "
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
                print(f"  {arm:8s} FAILED {r.stderr.strip()[-180:]}",
                      flush=True)
                continue
            rec = json.load(open(out))
            rec.update({"arm": arm, "round": rnd,
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")})
            w.writerow(rec); f.flush()
            eta = (time.time() - t0all) / seq * (total - seq) / 60
            print(f"  {arm:8s} ttft={rec['ttft_ms']:8.0f} "
                  f"p50={rec['itl_p50_ms']:7.2f} p95={rec['itl_p95_ms']:7.2f} "
                  f"gecis={rec.get('build_passes')} "
                  f"J/tok={rec.get('j_per_token')} "
                  f"({time.time()-t0:.0f}s, ETA {eta:.0f}m)", flush=True)
    f.close()
    print(f"\n[a21] done -> {csv_path}")


if __name__ == "__main__":
    main()
