"""2b / U15 — çekişmeli gürültü tabanı.

%2 tabanı §1.1'de TEK konfigürasyonda, RAKİPSİZ, tek oturumda ölçüldü.
Sonra çekişmeli, E-core'lu, çok turlu ve scx-yüklü her senaryoya
uygulandı. Bu bir transfer varsayımıdır ve sınanmadı: çekişme yeni bir
varyans kaynağı ekler (rakibin kendi zamanlaması, build'in faz yapısı,
paylaşılan LLC), yani çekişmeli taban rakipsiz tabandan BÜYÜK olabilir.

Eğer büyükse, makalenin çekişme altında yaptığı bütün "gürültünün
üstünde" iddiaları yeniden değerlendirilmelidir. Tek sayı, bütün eşik
mimarisini taşıyor.

§1.1'in protokolü aynen: aynı konfigürasyon, N tekrar, arka arkaya,
aralarında soğuma.
"""

import argparse
import json
import os
import statistics
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
METRICS = ["ttft_ms", "itl_p50_ms", "itl_p95_ms", "itl_p99_ms",
           "decode_tps", "j_per_token", "build_wall_s"]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--server-bin", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--prompt", default=os.path.join(HERE, "prompt_512.txt"))
    p.add_argument("--arm", default="SWITCH")
    p.add_argument("--competitor", default="build")
    p.add_argument("--runs", type=int, default=20)
    p.add_argument("--cooldown", type=int, default=30)
    p.add_argument("--port", type=int, default=8150)
    p.add_argument("--outdir", required=True)
    args = p.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    recs = []
    print(f"[a17] {args.runs} x {args.arm} + {args.competitor} "
          f"(§1.1 protokolü, çekişmeli)", flush=True)
    for i in range(1, args.runs + 1):
        if i > 1:
            time.sleep(args.cooldown)
        out = os.path.join(args.outdir, f"r{i:02d}.json")
        t0 = time.time()
        r = subprocess.run(
            ["python3", os.path.join(HERE, "phase_switch.py"),
             "--server-bin", args.server_bin, "--model", args.model,
             "--prompt", args.prompt, "--arm", args.arm,
             "--competitor", args.competitor, "--port", str(args.port),
             "--out", out], capture_output=True, text=True)
        if r.returncode != 0 or not os.path.exists(out):
            print(f"  {i:2d} FAILED {r.stderr.strip()[-160:]}", flush=True)
            continue
        d = json.load(open(out))
        recs.append(d)
        print(f"  {i:2d}/{args.runs} ttft={d['ttft_ms']:8.0f} "
              f"p95={d['itl_p95_ms']:7.2f} tps={d['decode_tps']:5.2f} "
              f"build={d.get('build_wall_s')} ({time.time()-t0:.0f}s)",
              flush=True)

    print(f"\n{'metrik':>14s} {'n':>3s} {'medyan':>10s} {'CV':>7s} "
          f"{'yayılım':>8s}")
    print("-" * 46)
    summary = {}
    for m in METRICS:
        v = [d[m] for d in recs if d.get(m) is not None]
        if len(v) < 3:
            continue
        mean, sd = statistics.mean(v), statistics.stdev(v)
        summary[m] = {"n": len(v), "median": round(statistics.median(v), 3),
                      "cv_pct": round(sd / mean * 100, 3),
                      "spread_pct": round((max(v) - min(v)) / mean * 100, 2)}
        print(f"{m:>14s} {len(v):3d} {statistics.median(v):10.2f} "
              f"{summary[m]['cv_pct']:6.2f}% {summary[m]['spread_pct']:7.2f}%")

    json.dump({"summary": summary, "arm": args.arm,
               "competitor": args.competitor, "runs": recs},
              open(os.path.join(args.outdir, "summary.json"), "w"), indent=1)
    print(f"\n[a17] -> {args.outdir}/summary.json")
    print("Karşılaştırma: rakipsiz taban %2 (§1.1). Yukarıdaki CV'ler bunun")
    print("üstündeyse, çekişme altındaki tüm 'gürültünün üstünde' iddiaları")
    print("bu yeni tabana göre yeniden değerlendirilmelidir.")


if __name__ == "__main__":
    main()
