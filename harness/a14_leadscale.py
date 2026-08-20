"""1a / U4 — erken uyarı süresi çekirdek sayısıyla ölçekleniyor mu?

§8'in hipotezi: prefill grafiğinin kuyruğu zaten decode-şeklidir ve süresi
≈ bir decode token'ı kadardır. Doğruysa dedektörün "erken" tetiklemesi
aslında erken DEĞİL — gerçek bir decode-şekilli bölgenin başlangıcını doğru
buluyor, yalnızca yer-gerçeği tanımı (ilk token) yanlış yerde duruyor.

Ayırt edici tahmin: erken uyarı süresi decode token süresiyle ORANTILI
ölçeklenmeli. Çekirdek sayısı değişince ITL değişir; oran sabit kalırsa
hipotez desteklenir, erken uyarı mutlak olarak sabit kalırsa elenir.

Mevcut h5_cores koşularından hesaplanıyor; yeni ölçüm yok.
"""

import glob
import json
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from h5_detector_v2 import series, run_state_machine

HI, LO, K = 3000.0, 2100.0, 2


def analyse(path):
    d = json.load(open(path))
    s = series(d["samples"])
    vals = [x["norm"] for x in s]
    first, _flips = run_state_machine(vals, HI, LO, K)
    if first is None:
        return None
    t_decide = s[first]["t_ns"]
    t_first_tok = d["t_first_token_ns"]
    ts = d["token_ts_ns"]
    itl = [(ts[i] - ts[i - 1]) / 1e6 for i in range(1, len(ts))]
    return {
        "cores": d["threads"],
        "itl_p50": statistics.median(itl),
        # negatif = ilk token'dan ÖNCE karar verildi (erken uyarı)
        "lead_ms": (t_decide - t_first_tok) / 1e6,
    }


def main():
    rows = []
    for p in sorted(glob.glob(os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "results", "h5_cores", "*.json"))):
        r = analyse(p)
        if r:
            rows.append(r)

    by = {}
    for r in rows:
        by.setdefault(r["cores"], []).append(r)

    print(f"{'çekirdek':>9s} {'n':>3s} {'ITL p50':>9s} {'erken uyarı':>12s} "
          f"{'oran':>7s}")
    print("-" * 46)
    ratios = []
    for c in sorted(by):
        g = by[c]
        itl = statistics.median(x["itl_p50"] for x in g)
        lead = statistics.median(x["lead_ms"] for x in g)
        ratio = abs(lead) / itl
        ratios.append(ratio)
        print(f"{c:9d} {len(g):3d} {itl:8.1f}ms {lead:11.1f}ms {ratio:7.2f}")

    print()
    if len(ratios) >= 2:
        spread_r = (max(ratios) - min(ratios)) / statistics.mean(ratios)
        leads = [abs(statistics.median(x["lead_ms"] for x in by[c]))
                 for c in sorted(by)]
        itls = [statistics.median(x["itl_p50"] for x in by[c])
                for c in sorted(by)]
        spread_l = (max(leads) - min(leads)) / statistics.mean(leads)
        spread_i = (max(itls) - min(itls)) / statistics.mean(itls)
        print(f"ITL yayılımı        : %{spread_i*100:.1f}")
        print(f"erken uyarı yayılımı: %{spread_l*100:.1f}")
        print(f"ORAN yayılımı       : %{spread_r*100:.1f}")
        print()
        print("Yorum: ITL anlamlı değişirken ORAN sabit kalıyorsa hipotez")
        print("desteklenir; erken uyarı sabit kalıyorsa (yayılım ~0) elenir.")


if __name__ == "__main__":
    main()
