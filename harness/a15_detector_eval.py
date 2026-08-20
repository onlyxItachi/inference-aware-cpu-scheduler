"""1b / U9 — dedektör değerlendirmesi: precision, FP, held-out, duyarlılık.

Rapor şu ana kadar YALNIZCA recall veriyor. Bir dedektör iddiası için bu
yetersiz: her örneğe "decode" diyen bir dedektörün recall'ü %100'dür.

Ayrıca eşikler (hi=3000, lo=2100, k=2) h5 koşularından SEÇİLDİ ve büyük
ölçüde aynı ailede değerlendirildi. Bu in-sample'dır. Buradaki
leave-one-config-out, eşiği hiç görmediği bir konfigürasyonda sınıyor.

Yer-gerçeği: ilk token'ın varışı. Bu tanımın kendisi tartışmalı (bkz. U4 /
a14_leadscale) — dedektörün "erken" saydığı örneklerin gerçekte prefill'in
decode-şekilli kuyruğu olması mümkün. Bu yüzden FP'ler burada ikiye
ayrılıyor: sınıra bitişik olanlar (erken tetikleme) ve olmayanlar (gerçek
gürültü). Ayrım yapılmazsa tek bir precision sayısı iki farklı olguyu
gizler.
"""

import glob
import json
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from h5_detector_v2 import series, run_state_machine

HI, LO, K = 3000.0, 2100.0, 2

GROUPS = [
    ("pinned",     "results/h5/*_pinned.json"),
    ("unpinned",   "results/h5/*_unpinned.json"),
    ("c4",         "results/h5_cores/*_c4.json"),
    ("c6",         "results/h5_cores/*_c6.json"),
    ("c8",         "results/h5_cores/*_c8.json"),
    ("free",       "results/h5_contention/*_B_both_free.json"),
    ("llmP_loadE", "results/h5_contention/*_D_llmP_loadE.json"),
    ("len32",      "results/h5_promptlen/*_len32.json"),
    ("len128",     "results/h5_promptlen/*_len128.json"),
    ("len256",     "results/h5_promptlen/*_len256.json"),
    ("len496",     "results/h5_promptlen/*_len496.json"),
    ("len1024",    "results/h5_promptlen/*_len1024.json"),
]

# Sınıra bitişik sayılan pencere. Erken tetikleme bu projede ~130-215 ms
# ölçüldü; 300 ms onu rahatça kapsıyor ama "-760 ms" anomalilerini KAPSAMAZ,
# yani onlar gerçek FP olarak sayılır. Eşik keyfi değil, ölçülen erken
# uyarı dağılımının üstünde ilk yuvarlak sayı.
ADJACENT_MS = 300.0


def score(path, hi, lo, k):
    d = json.load(open(path))
    s = series(d["samples"])
    if len(s) < 5:
        return None
    tf = d["t_first_token_ns"]
    t0, tl = d["t_request_sent_ns"], d["t_last_token_ns"]
    win = [x for x in s if t0 <= x["t_ns"] <= tl]
    if not win:
        return None

    state, run = "prefill", 0
    tp = tn = fp_adj = fp_far = fn = 0
    flips = 0
    first_decode = None
    for x in win:
        v = x["norm"]
        prev = state
        if state == "prefill":
            if v > hi:
                run += 1
                if run >= k:
                    state, run = "decode", 0
            else:
                run = 0
        else:
            if v < lo:
                run += 1
                if run >= k:
                    state, run = "prefill", 0
            else:
                run = 0
        if state != prev:
            flips += 1
            if state == "decode" and first_decode is None:
                first_decode = x["t_ns"]
        truth = x["t_ns"] >= tf
        pred = state == "decode"
        if pred and truth:
            tp += 1
        elif not pred and not truth:
            tn += 1
        elif pred and not truth:
            # sınıra bitişik mi, yoksa prefill'in ortasında mı?
            if (tf - x["t_ns"]) / 1e6 <= ADJACENT_MS:
                fp_adj += 1
            else:
                fp_far += 1
        else:
            fn += 1

    lead = ((first_decode - tf) / 1e6) if first_decode else None
    return {"tp": tp, "tn": tn, "fp_adj": fp_adj, "fp_far": fp_far,
            "fn": fn, "flips": flips, "lead_ms": lead, "n": len(win)}


def agg(rows):
    t = {k: sum(r[k] for r in rows) for k in
         ("tp", "tn", "fp_adj", "fp_far", "fn", "n")}
    fp = t["fp_adj"] + t["fp_far"]
    return {
        "runs": len(rows),
        "recall": t["tp"] / (t["tp"] + t["fn"]) * 100 if t["tp"] + t["fn"] else None,
        "prec_all": t["tp"] / (t["tp"] + fp) * 100 if t["tp"] + fp else None,
        "prec_far": t["tp"] / (t["tp"] + t["fp_far"]) * 100 if t["tp"] + t["fp_far"] else None,
        "fp_far_per_run": t["fp_far"] / len(rows),
        "extra_flips_per_run": sum(max(0, r["flips"] - 1) for r in rows) / len(rows),
        # Eşik çok yüksekse hiç tetikleme olmaz; bu bir hata değil, taramanın
        # ölçmek istediği çöküşün ta kendisi.
        "lead_ms": (statistics.median(_l) if (_l := [r["lead_ms"] for r in rows
                    if r["lead_ms"] is not None]) else None),
    }


def collect(hi=HI, lo=LO, k=K):
    out = {}
    for name, pat in GROUPS:
        rows = [r for r in (score(p, hi, lo, k) for p in sorted(glob.glob(pat)))
                if r]
        if rows:
            out[name] = rows
    return out


def main():
    data = collect()
    print("=== KONFİGÜRASYON BAŞINA (eşik hi=3000 lo=2100 k=2) ===")
    print(f"{'config':>11s} {'n':>3s} {'recall':>7s} {'prec(tüm)':>10s} "
          f"{'prec(uzak)':>11s} {'uzakFP/koşu':>12s} {'fazlaGeçiş':>11s} "
          f"{'erken':>8s}")
    print("-" * 82)
    allrows = []
    for name, rows in data.items():
        a = agg(rows)
        allrows += rows
        print(f"{name:>11s} {a['runs']:3d} {a['recall']:6.2f}% "
              f"{a['prec_all']:9.2f}% {a['prec_far']:10.2f}% "
              f"{a['fp_far_per_run']:12.2f} {a['extra_flips_per_run']:11.2f} "
              f"{a['lead_ms']:7.0f}ms")
    g = agg(allrows)
    print("-" * 82)
    print(f"{'TOPLAM':>11s} {g['runs']:3d} {g['recall']:6.2f}% "
          f"{g['prec_all']:9.2f}% {g['prec_far']:10.2f}% "
          f"{g['fp_far_per_run']:12.2f} {g['extra_flips_per_run']:11.2f} "
          f"{g['lead_ms']:7.0f}ms")

    print("\n=== LEAVE-ONE-CONFIG-OUT ===")
    print("Eşik h5 (pinned/unpinned) ailesinden seçildi. Aşağıdaki her satır,")
    print("eşiğin seçiminde kullanılmayan bir konfigürasyondaki performansı.")
    heldout = {n: r for n, r in data.items() if n not in ("pinned", "unpinned")}
    h = agg([r for rows in heldout.values() for r in rows])
    print(f"  held-out konfig sayısı : {len(heldout)}")
    print(f"  held-out koşu sayısı   : {h['runs']}")
    print(f"  out-of-sample recall   : {h['recall']:.2f}%")
    print(f"  out-of-sample precision: {h['prec_all']:.2f}% "
          f"(sınır-dışı FP hariç: {h['prec_far']:.2f}%)")
    print(f"  uzak FP / koşu         : {h['fp_far_per_run']:.2f}")

    print("\n=== EŞİK DUYARLILIĞI (±%30) ===")
    print(f"{'ölçek':>7s} {'hi':>7s} {'lo':>7s} {'recall':>8s} "
          f"{'prec(tüm)':>10s} {'uzakFP/koşu':>12s} {'fazlaGeçiş':>11s}")
    print("-" * 62)
    for mult in (0.70, 0.85, 1.00, 1.15, 1.30):
        d2 = collect(HI * mult, LO * mult, K)
        a = agg([r for rows in d2.values() for r in rows])
        print(f"{mult:6.2f}x {HI*mult:7.0f} {LO*mult:7.0f} {a['recall']:7.2f}% "
              f"{a['prec_all']:9.2f}% {a['fp_far_per_run']:12.2f} "
              f"{a['extra_flips_per_run']:11.2f}")


if __name__ == "__main__":
    main()
