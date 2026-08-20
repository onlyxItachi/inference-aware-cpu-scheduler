"""2a / U1 — statik Pareto cephesi ve SWITCH'in konumu.

Manşet iddia: faz anahtarlama, en iyi STATİK konfigürasyonu Pareto olarak
baskılıyor. Şimdiye kadar yalnızca iki uç nokta (A_P8, C_P8_E8) ölçüldüğü
için iddia "iki noktayı yeniyor"dan ibaretti. Ara kollar eklendi.

Pareto tanımı burada: (TTFT, ITL p95) düzleminde, ikisi de KÜÇÜK iyi.
Bir kol X, kol Y'yi baskılar (dominate) ⇔ X her iki eksende de Y'den
kötü değil VE en az birinde gürültü tabanının dışında iyi.

%2 gürültü tabanı her karşılaştırmada uygulanıyor: X'in Y'yi "yendiği"
sayılması için X ≤ Y × 0.98 gerekir; X ≤ Y × 1.02 ise "eşit" sayılır.
Bu, tek yönlü bir kayırma yaratmasın diye her iki yönde de uygulanır.
"""

import argparse
import csv
import os
import statistics
import sys
from collections import defaultdict

# Gürültü tabanı hem METRİĞE hem SENARYOYA göre değişiyor -- tek bir %2
# sayısı yanlış, ama tek bir metrik-vektörü de yanlış. İlk sürümde
# aralıklı-rakip senaryosunun p95 tabanı (%5.20) rakipsiz kola da
# uygulanmıştı; bu, rakipsiz koldaki gerçek bir farkı "eşit" gösteriyordu.
#
#   none  : §1.1, 20 koşu, rakipsiz          TTFT %0.5, p50 %0.5, p95 %0.7
#   build : §11.4 (a17), 20 koşu, SWITCH+build  TTFT %0.38, p50 %0.31, p95 %5.20
#
# p95'in rakipsizken kararlı, aralıklı rakiple gürültülü, sürekli ağır
# rakiple yine kararlı (%1.51) olması tesadüf değil: varyansı yaratan
# sporadik girişimdir.
NOISE = {
    "none":  {"ttft_ms": 0.005, "itl_p95_ms": 0.007,
              "itl_p50_ms": 0.005, "itl_p99_ms": 0.014},
    "build": {"ttft_ms": 0.0038, "itl_p95_ms": 0.0520,
              "itl_p50_ms": 0.0031, "itl_p99_ms": 0.0565},
}
AXES = ["ttft_ms", "itl_p95_ms"]


def load(path):
    g = defaultdict(lambda: defaultdict(list))
    for r in csv.DictReader(open(path)):
        scen = r.get("scenario") or "none"
        for k, v in r.items():
            if k in ("arm", "scenario", "round", "timestamp") or not v:
                continue
            try:
                g[(scen, r["arm"])][k].append(float(v))
            except ValueError:
                pass
    return g


def med(g, cell, key):
    v = g[cell].get(key)
    return statistics.median(v) if v else None


def cmp_noise(a, b, axis, scen):
    """a'nın b'ye karşı durumu: -1 daha iyi, 0 eşit, +1 daha kötü."""
    n = NOISE[scen][axis]
    if a <= b * (1 - n):
        return -1
    if a >= b * (1 + n):
        return 1
    return 0


def dominates(g, x, y):
    """x, y'yi Pareto olarak baskılıyor mu?"""
    res = [cmp_noise(med(g, x, ax), med(g, y, ax), ax, x[0]) for ax in AXES]
    return all(r <= 0 for r in res) and any(r < 0 for r in res)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--csv", default="results/i14_frontier/i14.csv")
    args = p.parse_args()
    g = load(args.csv)

    scens = sorted({s for s, _a in g})
    for scen in scens:
        arms = [a for s, a in g if s == scen]
        # ölçüm sırası değil, mantıksal sıra
        order = ["A_P8", "P8_E2", "P8_E4", "P8_E6", "C_P8_E8", "SWITCH"]
        arms = [a for a in order if a in arms]

        print(f"\n{'='*78}\n### SENARYO: {scen}\n{'='*78}")
        print(f"{'kol':>9s} {'n':>3s} {'TTFT':>9s} {'ITL p50':>9s} "
              f"{'ITL p95':>9s} {'ITL p99':>9s} {'tps':>7s} {'J/tok':>7s} "
              f"{'build':>7s}")
        print("-" * 78)
        for a in arms:
            c = (scen, a)
            n = len(g[c].get("ttft_ms", []))
            bw = med(g, c, "build_wall_s")
            print(f"{a:>9s} {n:3d} {med(g,c,'ttft_ms'):9.0f} "
                  f"{med(g,c,'itl_p50_ms'):9.2f} {med(g,c,'itl_p95_ms'):9.2f} "
                  f"{med(g,c,'itl_p99_ms'):9.2f} "
                  f"{med(g,c,'decode_tps'):7.2f} "
                  f"{med(g,c,'j_per_token'):7.3f} "
                  f"{(f'{bw:7.1f}' if bw else '      -')}")

        statics = [a for a in arms if a != "SWITCH"]
        # Statik cephe: başka hiçbir STATİK kol tarafından baskılanmayanlar.
        frontier = [a for a in statics
                    if not any(dominates(g, (scen, b), (scen, a))
                               for b in statics if b != a)]
        print(f"\nstatik Pareto cephesi: {', '.join(frontier)}")
        dominated = [a for a in statics if a not in frontier]
        if dominated:
            print(f"baskılanan statikler : {', '.join(dominated)}")

        if "SWITCH" not in arms:
            continue
        sw = (scen, "SWITCH")
        print(f"\nSWITCH'in cephedeki her noktaya karşı durumu:")
        print(f"{'karşı':>9s} {'TTFT':>18s} {'ITL p95':>18s} {'sonuç':>22s}")
        print("-" * 70)
        beats_all = True
        for a in frontier:
            c = (scen, a)
            row = []
            for ax in AXES:
                x, y = med(g, sw, ax), med(g, c, ax)
                d = (x - y) / y * 100
                r = cmp_noise(x, y, ax, scen)
                tag = {-1: "iyi", 0: "eşit", 1: "KÖTÜ"}[r]
                row.append((d, tag))
            dom = dominates(g, sw, c)
            eq = all(t != "KÖTÜ" for _d, t in row)
            verdict = ("BASKILIYOR" if dom else
                       "berabere" if eq else "baskılanmıyor")
            if not dom:
                beats_all = False
            print(f"{a:>9s} "
                  f"{row[0][0]:+9.2f}% ({row[0][1]:>4s}) "
                  f"{row[1][0]:+9.2f}% ({row[1][1]:>4s}) "
                  f"{verdict:>22s}")

        # SWITCH'i baskılayan statik var mı? İddia için ölümcül olan bu.
        beaten_by = [a for a in statics if dominates(g, (scen, a), sw)]
        print(f"\nSWITCH'i baskılayan statik: "
              f"{', '.join(beaten_by) if beaten_by else 'YOK'}")
        print(f"SWITCH cephedeki TÜM noktaları baskılıyor mu: "
              f"{'EVET' if beats_all else 'HAYIR'}")

        # rakip throughput kısıtı (varsa)
        if med(g, sw, "build_wall_s"):
            best = min((med(g, (scen, a), "build_wall_s"), a)
                       for a in statics if med(g, (scen, a), "build_wall_s"))
            x = med(g, sw, "build_wall_s")
            print(f"\nrakip build: SWITCH {x:.1f}s vs en iyi statik "
                  f"{best[0]:.1f}s ({best[1]}) → "
                  f"%{(x-best[0])/best[0]*100:+.2f}")


if __name__ == "__main__":
    main()
