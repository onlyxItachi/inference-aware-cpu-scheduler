"""2f / U8 — `chrt --idle` tavsiyesi gerçek bir rakiple de tutuyor mu?

§0'daki "bugün kullanılabilecek tek satırlık tavsiye" YALNIZCA sentetik
`loadgen` ile ölçüldü: always-runnable, hiç bloke olmayan, tek bir
cpuset'e sabitlenmiş bir yük. Tavsiye ise "arka plan işi" diye
genelleniyor.

Gerçek bir build bu varsayımların hiçbirini sağlamaz: fork eder, I/O'da
bloke olur, link aşamasında serileşir ve pinlenmediği için P ve E
çekirdeklerine yayılır. SCHED_IDLE'ın kazancı uyanma-preemption'ından
geliyorsa, sürekli uyuyup uyanan bir build'de etki FARKLI çıkabilir --
daha büyük de olabilir, daha küçük de.

Kollar i7_shared'daki üçlüyle aynı, yalnızca rakip değişti:

  B1_normal  build normal öncelikte      (taban)
  B3_weight  build cgroup CPUWeight=1    (throughput payı kısıtlaması)
  B4_idle    build chrt --idle           (gecikme önceliği)

Not: build pinlenmiyor, çünkü −%3.7 iddiası da pinsiz build'den geldi ve
tavsiye o konfigürasyon için veriliyor. Bu, i7_shared'ın P8'e sabitlenmiş
loadgen'inden daha SEYRELTİK bir çekişmedir; etki küçük çıkarsa bunun
tavsiyenin yanlışlığı mı yoksa çekişmenin seyrekliği mi olduğu ayrıca
belirtilmelidir.
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

ARMS = [
    ("B1_normal", []),
    ("B3_weight", ["--load-weight", "1"]),
    ("B4_idle",   ["--load-sched-idle"]),
]

FIELDS = ["arm", "round", "timestamp", "ttft_ms", "itl_p50_ms", "itl_p95_ms",
          "itl_p99_ms", "decode_tps", "n_tokens", "energy_j", "j_per_token",
          "build_wall_s", "total_migrations", "temp_start_c", "temp_end_c",
          "switch_detected"]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--server-bin", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--prompt", default=os.path.join(HERE, "prompt_512.txt"))
    p.add_argument("--rounds", type=int, default=6)
    p.add_argument("--cooldown", type=int, default=30)
    p.add_argument("--port", type=int, default=8160)
    p.add_argument("--outdir", required=True)
    p.add_argument("--order-seed", type=int, default=1818)
    args = p.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    csv_path = os.path.join(args.outdir, "a18.csv")
    new = not os.path.exists(csv_path)
    f = open(csv_path, "a", newline="")
    w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
    if new:
        w.writeheader(); f.flush()

    rng = random.Random(args.order_seed)
    seq, total = 0, args.rounds * len(ARMS)
    t0all = time.time()
    print(f"[a18] {args.rounds} tur x {len(ARMS)} kol = {total} koşu "
          f"| rakip: make -j16 (pinsiz), LLM kolu SWITCH", flush=True)

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
                 "--prompt", args.prompt, "--arm", "SWITCH",
                 "--competitor", "build", "--port", str(args.port),
                 "--out", out] + extra, capture_output=True, text=True)
            if r.returncode != 0 or not os.path.exists(out):
                print(f"  {arm:10s} FAILED {r.stderr.strip()[-180:]}",
                      flush=True)
                continue
            rec = json.load(open(out))
            rec.update({"arm": arm, "round": rnd,
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")})
            w.writerow(rec); f.flush()
            eta = (time.time() - t0all) / seq * (total - seq) / 60
            print(f"  {arm:10s} ttft={rec['ttft_ms']:8.0f} "
                  f"p50={rec['itl_p50_ms']:7.2f} p95={rec['itl_p95_ms']:7.2f} "
                  f"build={rec.get('build_wall_s')}s "
                  f"({time.time()-t0:.0f}s, ETA {eta:.0f}m)", flush=True)
    f.close()
    print(f"\n[a18] done -> {csv_path}")


if __name__ == "__main__":
    main()
