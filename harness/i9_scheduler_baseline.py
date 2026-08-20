"""İŞ 1 — scx scheduler baseline'ları: raporun mantıksal açığını kapatmak.

Projenin manşet sonucu "sched_ext'in katkısı yok" idi, ama hiçbir sched_ext
scheduler'ı ölçülmemişti. Ölçülen şey sched_ext'in BELİRLİ BİR
KULLANIMININ (öncelik ifadesi) gereksizliğiydi; scheduler'ın kendisinin
bir şey katıp katmadığı değil.

Bu sweep, halihazırda YÜKLÜ olan scheduler altında yerleşim × senaryo
matrisini koşar. Scheduler değişimi bu scriptin işi değil (kullanıcı
onaylı, elle ve doğrulanarak yapılır) — script yalnızca hangi scheduler'ın
aktif olduğunu etiketler.

  yerleşim:  A_P8 (statik pinning) | SWITCH (faz anahtarlama)
  senaryo:   none (rakipsiz)       | build (make -j16, pinsiz)

Cevaplanacak sorular:
  1. scx scheduler'ı EEVDF+A_P8'i yeniyor mu?
  2. Yeniyorsa EEVDF+SWITCH'i de yeniyor mu?
  3. SWITCH'in kazancı scheduler değişince korunuyor mu — yani faz
     anahtarlama scheduler-bağımsız mı, yoksa EEVDF'e özgü müydü?

Üçüncüsü ayrı bir bulgudur ve hangisi çıkarsa çıksın raporlanır.
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

# (placement, competitor)
CELLS = [
    ("A_P8", "none"),
    ("SWITCH", "none"),
    ("A_P8", "build"),
    ("SWITCH", "build"),
]

FIELDS = [
    "sched", "arm", "competitor", "round", "timestamp", "ttft_ms",
    "itl_p50_ms", "itl_p95_ms", "itl_p99_ms", "itl_max_ms", "decode_tps",
    "n_tokens", "energy_j", "j_per_token", "build_wall_s",
    "total_migrations", "total_ctx_switches", "temp_start_c", "temp_end_c",
    "switch_detected", "switch_lead_ms", "sched_ext_state",
]


def sched_ext_state():
    try:
        with open("/sys/kernel/sched_ext/state") as f:
            return f.read().strip()
    except OSError:
        return "unavailable"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--server-bin", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--prompt", default=os.path.join(HERE, "prompt_512.txt"))
    p.add_argument("--sched-label", required=True,
                   help="etiket: eevdf / rustland / lavd")
    p.add_argument("--rounds", type=int, default=6)
    p.add_argument("--cooldown", type=int, default=30)
    p.add_argument("--n-predict", type=int, default=256)
    p.add_argument("--outdir", required=True)
    p.add_argument("--port", type=int, default=8109)
    p.add_argument("--order-seed", type=int, default=909)
    args = p.parse_args()

    os.makedirs(os.path.join(args.outdir, "runs"), exist_ok=True)
    csv_path = os.path.join(args.outdir, "sched.csv")
    new = not os.path.exists(csv_path)
    f = open(csv_path, "a", newline="")
    w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
    if new:
        w.writeheader()
        f.flush()

    state0 = sched_ext_state()
    print(f"[i9] scheduler={args.sched_label} | sched_ext state={state0} | "
          f"{args.rounds} tur x {len(CELLS)} hücre = "
          f"{args.rounds * len(CELLS)} koşu", flush=True)

    rng = random.Random(args.order_seed)
    seq = 0
    total = args.rounds * len(CELLS)
    t0all = time.time()

    for rnd in range(1, args.rounds + 1):
        order = CELLS[:]
        rng.shuffle(order)
        print(f"\n=== tur {rnd}/{args.rounds} | "
              f"{' -> '.join(f'{a}/{c}' for a, c in order)}", flush=True)
        for arm, comp in order:
            if seq > 0:
                time.sleep(args.cooldown)
            seq += 1
            tag = f"r{rnd:02d}_{args.sched_label}_{arm}_{comp}"
            out = os.path.join(args.outdir, "runs", f"{tag}.json")
            cmd = [sys.executable, os.path.join(HERE, "phase_switch.py"),
                   "--server-bin", args.server_bin, "--model", args.model,
                   "--prompt", args.prompt, "--arm", arm,
                   "--n-predict", str(args.n_predict),
                   "--port", str(args.port), "--out", out,
                   "--competitor", comp]
            t0 = time.time()
            pr = subprocess.run(cmd, capture_output=True, text=True)
            if pr.returncode != 0:
                print(f"  {arm}/{comp:5s} FAILED\n{pr.stderr[-800:]}",
                      flush=True)
                continue
            rec = json.load(open(out))
            st = sched_ext_state()
            rec.update({"sched": args.sched_label, "competitor": comp,
                        "round": rnd, "sched_ext_state": st,
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")})
            w.writerow(rec)
            f.flush()
            # Scheduler kaybolduysa ölçüm geçersizdir; hemen görülmeli.
            if st != state0:
                print(f"  !! sched_ext state DEĞİŞTİ: {state0} -> {st}",
                      flush=True)
            eta = (time.time() - t0all) / seq * (total - seq) / 60
            print(f"  {arm:6s}/{comp:5s} ttft={rec['ttft_ms']:8.0f}  "
                  f"p50={rec['itl_p50_ms']:6.2f}  p95={rec['itl_p95_ms']:7.2f}  "
                  f"tps={rec['decode_tps']:5.2f}  "
                  f"J/tok={rec['j_per_token']}  "
                  f"build={rec.get('build_wall_s')}  "
                  f"({time.time() - t0:.0f}s, ETA {eta:.0f}m)", flush=True)
    f.close()
    print(f"\n[i9] done ({args.sched_label}) -> {csv_path}", flush=True)


if __name__ == "__main__":
    main()
