"""İŞ 3 — uygulama-bilgili affinity vs dışarıdan tespitli affinity.

Projenin en güçlü cümlesi olabilecek iddia şu: *OS bunu uygulamanın yardımı
olmadan da yapabiliyor.* Şimdiye kadar bu iddia ölçülmedi — yalnızca
dışarıdan tespitin işe yaradığı gösterildi, uygulamanın kendi bilgisiyle
yapabileceğinin **aynısı** olup olmadığı değil.

  A_APP     yamalı server: -C/-Cb ile prefill P+E, decode P-only.
            Uygulama fazı ZATEN biliyor (graph_compute batched bayrağı);
            hiçbir tahmin yok, hiçbir gecikme yok.
  B_DAEMON  yamasız server + bizim daemon: fazı /proc'tan tespit edip
            sched_setaffinity uyguluyor. Tahmin var, ~115 ms erken
            tetikleme var, örnekleme maliyeti var.

İkisi eşitse bu ölçülmüş bir iddiadır. A açık ara öndeyse, katkının adı
"uygulamayı değiştirmek gerekmiyor" değil "uygulamayı değiştirmek daha
iyi ama gerekmiyor" olur — ve bu da dürüstçe yazılır.

Not: bu karşılaştırma yamanın upstream'e kabul edilip edilmemesinden
bağımsızdır. Kabul edilirse daemon büyük ölçüde gereksizleşir; o zaman
katkı "tek yol" değil "uygulamaya dokunmadan da çözülebileceğinin kanıtı"
olur.
"""

import argparse
import csv
import json
import os
import random
import signal
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bench_lib as bl
import run_once as ro
from phase_switch import (P8, P8E8, PhaseSwitcher, set_affinity_all,
                          read_energy_uj, sched_totals)

HERE = os.path.dirname(os.path.abspath(__file__))
MASK_P8 = "5555"        # 0,2,4,6,8,10,12,14
MASK_P8E8 = "FF5555"    # + 16..23

ARMS = ["A_APP", "B_DAEMON"]

FIELDS = [
    "arm", "round", "timestamp", "ttft_ms", "itl_p50_ms", "itl_p95_ms",
    "itl_p99_ms", "itl_max_ms", "decode_tps", "n_tokens", "energy_j",
    "j_per_token", "total_migrations", "temp_start_c", "temp_end_c",
    "switch_detected", "switch_lead_ms",
]


def run_arm(args, arm):
    if arm == "A_APP":
        # Uygulama fazı kendi biliyor: iki threadpool, iki maske.
        cmd = [args.server_tp, "-m", args.model, "-t", "8", "-tb", "16",
               "-C", MASK_P8, "-Cb", MASK_P8E8, "--cpu-strict", "1",
               "-c", "2048", "-b", "2048", "-ub", "512", "-np", "1",
               "--host", ro.HOST, "--port", str(args.port)]
        armed = False
    else:
        # Yamasız server, geniş cpuset; fazı daemon tespit edip daraltacak.
        cmd = ["taskset", "-c", ",".join(map(str, P8E8)),
               args.server_plain, "-m", args.model, "-t", "8", "-tb", "16",
               "-c", "2048", "-b", "2048", "-ub", "512", "-np", "1",
               "--host", ro.HOST, "--port", str(args.port)]
        armed = True

    log = open(os.devnull, "wb")
    proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT,
                            start_new_session=True)
    try:
        ro.wait_for_health(args.port, proc)
        ro.stream_completion(args.port, {
            "prompt": "Warmup.", "n_predict": 1, "temperature": 0,
            "stream": True, "cache_prompt": False})
        time.sleep(1.0)
        if arm == "B_DAEMON":
            set_affinity_all(proc.pid, P8E8)

        prompt = open(args.prompt).read()
        sw0, mig0 = sched_totals(proc.pid)
        e0 = read_energy_uj()
        temp0 = bl.package_temp_c()

        # Örnekleyici HER İKİ kolda da çalışıyor; yalnızca B'de armed.
        # Aksi halde A, örnekleme maliyetinden muaf olur ve karşılaştırma
        # daemon'ı haksız yere cezalandırır.
        sw = PhaseSwitcher(proc.pid, 3000.0, 2100.0, 2, 0.020, P8, armed)
        sw.start()
        time.sleep(0.3)

        t_sent, token_ts, _, _ = ro.stream_completion(args.port, {
            "prompt": prompt, "n_predict": args.n_predict,
            "temperature": 0.0, "seed": 42, "stream": True,
            "cache_prompt": False, "ignore_eos": True})

        sw.stop_flag.set()
        sw.join(timeout=5)
        e1 = read_energy_uj()
        temp1 = bl.package_temp_c()
        sw1, mig1 = sched_totals(proc.pid)
    finally:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            proc.wait(timeout=20)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
        log.close()

    itl = [(token_ts[i] - token_ts[i - 1]) / 1e6
           for i in range(1, len(token_ts))]
    s_itl = sorted(itl)
    energy_j = ((e1 - e0) / 1e6) if (e0 and e1 and e1 >= e0) else None
    return {
        "arm": arm,
        "ttft_ms": round((token_ts[0] - t_sent) / 1e6, 2),
        "itl_p50_ms": round(bl.percentile(s_itl, 50), 3),
        "itl_p95_ms": round(bl.percentile(s_itl, 95), 3),
        "itl_p99_ms": round(bl.percentile(s_itl, 99), 3),
        "itl_max_ms": round(s_itl[-1], 3),
        "decode_tps": round((len(token_ts) - 1) /
                            ((token_ts[-1] - token_ts[0]) / 1e9), 3),
        "n_tokens": len(token_ts),
        "energy_j": round(energy_j, 1) if energy_j else None,
        "j_per_token": round(energy_j / len(token_ts), 3) if energy_j else None,
        "total_migrations": mig1 - mig0,
        "temp_start_c": temp0, "temp_end_c": temp1,
        "switch_detected": sw.switch_t_ns is not None,
        "switch_lead_ms": round((sw.switch_t_ns - token_ts[0]) / 1e6, 1)
        if sw.switch_t_ns else None,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--server-tp", required=True, help="yamalı (threadpool) server")
    p.add_argument("--server-plain", required=True, help="yamasız server")
    p.add_argument("--model", required=True)
    p.add_argument("--prompt", default=os.path.join(HERE, "prompt_512.txt"))
    p.add_argument("--rounds", type=int, default=6)
    p.add_argument("--cooldown", type=int, default=30)
    p.add_argument("--n-predict", type=int, default=256)
    p.add_argument("--outdir", required=True)
    p.add_argument("--port", type=int, default=8130)
    p.add_argument("--order-seed", type=int, default=1313)
    args = p.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    csv_path = os.path.join(args.outdir, "i13.csv")
    new = not os.path.exists(csv_path)
    f = open(csv_path, "a", newline="")
    w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
    if new:
        w.writeheader(); f.flush()

    rng = random.Random(args.order_seed)
    seq, total = 0, args.rounds * len(ARMS)
    t0all = time.time()
    print(f"[i13] {args.rounds} tur x {len(ARMS)} kol = {total} koşu",
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
            t0 = time.time()
            try:
                rec = run_arm(args, arm)
            except Exception as exc:
                print(f"  {arm:9s} FAILED: {exc}", flush=True)
                continue
            rec.update({"round": rnd,
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")})
            w.writerow(rec); f.flush()
            eta = (time.time() - t0all) / seq * (total - seq) / 60
            print(f"  {arm:9s} ttft={rec['ttft_ms']:8.0f}  "
                  f"p50={rec['itl_p50_ms']:6.2f}  p95={rec['itl_p95_ms']:7.2f}  "
                  f"tps={rec['decode_tps']:5.2f}  J/tok={rec['j_per_token']}  "
                  f"({time.time() - t0:.0f}s, ETA {eta:.0f}m)", flush=True)
    f.close()
    print(f"\n[i13] done -> {csv_path}", flush=True)


if __name__ == "__main__":
    main()
