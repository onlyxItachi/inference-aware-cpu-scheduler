"""a21 analizi — rakipli statik Pareto cephesi.

§11.4'ün dersi burada uygulanıyor: gürültü tabanı DIŞARIDAN getirilmiyor,
bu deneyin kendi kol-içi CV'lerinden hesaplanıyor. Rakipsiz senaryonun
tabanını (%0.7) rakipli kola uygulamak — ya da tersi — bu raporda bir kez
fiilen yanlış sonuç üretti.

Taban olarak kol-içi CV'lerin MEDYANI kullanılıyor: tek bir kolun CV'si
o kola özgü bir aksaklığı yansıtabilir, medyan buna dayanıklı.
"""

import argparse
import csv
import statistics
import sys
from collections import defaultdict

AXES = ["ttft_ms", "itl_p95_ms"]
ORDER = ["A_P8", "P8_E2", "P8_E4", "P8_E6", "C_P8_E8", "SWITCH"]
METRICS = ["ttft_ms", "itl_p50_ms", "itl_p95_ms", "itl_p99_ms",
           "decode_tps", "build_rate", "j_per_token"]


def load(path):
    g = defaultdict(lambda: defaultdict(list))
    for r in csv.DictReader(open(path)):
        for k, v in r.items():
            if k in ("arm", "round", "timestamp") or not v:
                continue
            try:
                g[r["arm"]][k].append(float(v))
            except ValueError:
                pass
    return g


def med(g, arm, key):
    v = g[arm].get(key)
    return statistics.median(v) if v else None


def floors(g, arms):
    """Bu senaryonun kendi tabanı: metrik başına kol-içi CV medyanı."""
    out = {}
    for m in METRICS:
        cvs = []
        for a in arms:
            v = g[a].get(m)
            if v and len(v) > 2 and statistics.mean(v):
                cvs.append(statistics.stdev(v) / statistics.mean(v))
        if cvs:
            out[m] = statistics.median(cvs)
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--csv", default="results/frontier_contended/a21.csv")
    args = p.parse_args()
    g = load(args.csv)
    arms = [a for a in ORDER if a in g]
    F = floors(g, arms)

    print("=" * 84)
    print("### RAKİPLİ SENARYO — statik cephe + SWITCH")
    print("=" * 84)
    print(f"{'kol':>9s} {'n':>3s} {'TTFT':>9s} {'ITLp50':>8s} {'ITLp95':>8s} "
          f"{'ITLp99':>8s} {'tps':>6s} {'geçiş':>6s} {'rakipHız':>9s} "
          f"{'J/tok':>7s}")
    print("-" * 84)
    for a in arms:
        n = len(g[a].get("ttft_ms", []))
        jt = med(g, a, "j_per_token")
        print(f"{a:>9s} {n:3d} {med(g,a,'ttft_ms'):9.0f} "
              f"{med(g,a,'itl_p50_ms'):8.2f} {med(g,a,'itl_p95_ms'):8.2f} "
              f"{med(g,a,'itl_p99_ms'):8.2f} {med(g,a,'decode_tps'):6.2f} "
              f"{med(g,a,'build_passes'):6.1f} {med(g,a,'build_rate'):9.4f} "
              f"{(f'{jt:7.3f}' if jt else '      -')}")

    print("\n### BU SENARYONUN GÜRÜLTÜ TABANI (kol-içi CV medyanı)")
    for m in METRICS:
        if m in F:
            print(f"  {m:14s} %{F[m]*100:.2f}")

    def cmp(x, y, ax):
        n = F.get(ax, 0.02)
        if x <= y * (1 - n):
            return -1
        if x >= y * (1 + n):
            return 1
        return 0

    def dominates(a, b):
        r = [cmp(med(g, a, ax), med(g, b, ax), ax) for ax in AXES]
        return all(v <= 0 for v in r) and any(v < 0 for v in r)

    statics = [a for a in arms if a != "SWITCH"]
    frontier = [a for a in statics
                if not any(dominates(b, a) for b in statics if b != a)]
    print(f"\nstatik Pareto cephesi: {', '.join(frontier)}")
    dom = [a for a in statics if a not in frontier]
    print(f"baskılanan statikler : {', '.join(dom) if dom else '(yok)'}")

    if "SWITCH" not in arms:
        return
    print("\n### SWITCH'in cephedeki her noktaya karşı durumu")
    print(f"{'karşı':>9s} {'TTFT':>19s} {'ITL p95':>19s} {'sonuç':>16s}")
    print("-" * 68)
    beats_all = True
    for a in frontier:
        row = []
        for ax in AXES:
            x, y = med(g, "SWITCH", ax), med(g, a, ax)
            r = cmp(x, y, ax)
            row.append(((x - y) / y * 100, {-1: "iyi", 0: "eşit", 1: "KÖTÜ"}[r]))
        d = dominates("SWITCH", a)
        if not d:
            beats_all = False
        v = ("BASKILIYOR" if d else
             "berabere" if all(t != "KÖTÜ" for _x, t in row) else "TAKAS")
        print(f"{a:>9s} {row[0][0]:+10.2f}% ({row[0][1]:>4s}) "
              f"{row[1][0]:+10.2f}% ({row[1][1]:>4s}) {v:>16s}")

    beaten = [a for a in statics if dominates(a, "SWITCH")]
    print(f"\nSWITCH'i baskılayan statik: "
          f"{', '.join(beaten) if beaten else 'YOK'}")
    print(f"SWITCH cephedeki TÜM noktaları baskılıyor mu: "
          f"{'EVET' if beats_all else 'HAYIR'}")

    print("\n### RAKİP TARAFI (build_rate, taban "
          f"%{F.get('build_rate',0)*100:.2f})")
    base = med(g, "A_P8", "build_rate")
    for a in arms:
        r = med(g, a, "build_rate")
        d = (r - base) / base * 100
        tag = "eşit" if abs(d) <= F.get("build_rate", 0.02) * 100 else \
              ("iyi" if d > 0 else "KÖTÜ")
        print(f"  {a:>9s} {r:.4f}  A_P8'e karşı %{d:+6.2f}  ({tag})")

    print("\n### DECODE HASARI BASAMAK MI? (rakipsizdeki bulgu tutuyor mu)")
    a0 = med(g, "A_P8", "itl_p50_ms")
    t0 = med(g, "A_P8", "ttft_ms")
    for a in arms:
        if a == "SWITCH":
            continue
        print(f"  {a:>9s} ITL p50 %{(med(g,a,'itl_p50_ms')-a0)/a0*100:+6.2f}  "
              f"TTFT %{(med(g,a,'ttft_ms')-t0)/t0*100:+6.2f}")


if __name__ == "__main__":
    main()
