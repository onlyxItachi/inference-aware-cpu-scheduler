"""Compare affinity variants against the unpinned baseline.

Every difference is reported against the Faz 0 noise floor (2%). A delta
smaller than that is not a finding, regardless of how tidy it looks.

Also checks that the interleaving did its job: if drift had loaded onto one
arm, that arm's mean round index would be skewed. With a full shuffle each
round every variant should average round ~(rounds+1)/2.
"""

import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bench_lib as bl

NOISE_FLOOR_PCT = 2.0  # results/phase0/FINDINGS.md
BASELINE = "unpinned"

VARIANT_ORDER = ["unpinned", "p_nosmt", "p_all", "p_smt_forced", "e_only"]

VARIANT_DESC = {
    "unpinned":     "pinsiz (serbest)",
    "p_nosmt":      "8 fiziksel P-core, sibling yok",
    "p_all":        "16 mantıksal P-CPU, serbest",
    "p_smt_forced": "4 fiziksel P-core, sibling zorlanmış",
    "e_only":       "8 E-core",
}

METRICS = [
    ("ttft_ms", "TTFT (ms)", "lower"),
    ("itl_p50_ms", "ITL p50 (ms)", "lower"),
    ("itl_p95_ms", "ITL p95 (ms)", "lower"),
    ("itl_p99_ms", "ITL p99 (ms)", "lower"),
    ("itl_max_ms", "ITL max (ms)", "lower"),
    ("decode_tps", "decode (tok/s)", "higher"),
    ("migrations", "migrations", "lower"),
    ("ctx_switches", "ctx switches", "lower"),
]


def welch_t(a, b):
    """Welch's t statistic and approximate two-sided significance.

    Unequal variances are expected here (e_only is far noisier in absolute
    terms), so Student's pooled t would be wrong.
    """
    na, nb = len(a), len(b)
    if na < 2 or nb < 2:
        return None, None
    ma, mb = sum(a) / na, sum(b) / nb
    va = sum((x - ma) ** 2 for x in a) / (na - 1)
    vb = sum((x - mb) ** 2 for x in b) / (nb - 1)
    se2 = va / na + vb / nb
    if se2 <= 0:
        return None, None
    t = (mb - ma) / se2 ** 0.5
    num = se2 ** 2
    den = (va / na) ** 2 / (na - 1) + (vb / nb) ** 2 / (nb - 1)
    df = num / den if den > 0 else min(na, nb) - 1
    return t, df


def sig_label(t, df):
    """Crude two-sided significance without scipy.

    For df>=8, |t| thresholds ~2.31 (p<0.05) and ~3.36 (p<0.01) are close
    enough for a screening verdict; anything marginal gets re-measured
    rather than argued over.
    """
    if t is None:
        return "-"
    a = abs(t)
    if df < 5:
        return "n/a"
    if a >= 3.36:
        return "p<0.01"
    if a >= 2.31:
        return "p<0.05"
    return "ns"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--csv", required=True)
    p.add_argument("--outdir", required=True)
    args = p.parse_args()

    rows = list(csv.DictReader(open(args.csv)))
    if not rows:
        sys.exit("no rows")

    variants = [v for v in VARIANT_ORDER
                if any(r["variant"] == v for r in rows)]
    for r in rows:
        if r["variant"] not in variants:
            variants.append(r["variant"])

    def vals(variant, key):
        out = []
        for r in rows:
            if r["variant"] != variant:
                continue
            v = r.get(key, "")
            if v not in ("", "None"):
                try:
                    out.append(float(v))
                except ValueError:
                    pass
        return out

    out = []
    out.append("# Faz 0 — Affinity Varyantları (interleaved)\n")
    n_rounds = len({r["round"] for r in rows})
    out.append(f"**Turlar:** {n_rounds}  |  **Toplam koşu:** {len(rows)}  |  "
               f"**threads:** {rows[0]['threads']}  |  "
               f"**gürültü tabanı:** ±{NOISE_FLOOR_PCT}%\n")
    out.append("Her tur tüm varyantları bir kez, karıştırılmış sırayla "
               "çalıştırdı. Faz 0'da bulunan termal olmayan oturum drift'i "
               "böylece tek bir kola yüklenmiyor.\n")

    # --- interleaving sanity check
    out.append("\n## Interleaving kontrolü\n")
    out.append("| varyant | n | ortalama tur indeksi |")
    out.append("|---|---|---|")
    expected = (n_rounds + 1) / 2
    for v in variants:
        rs = [float(r["round"]) for r in rows if r["variant"] == v]
        if rs:
            out.append(f"| {v} | {len(rs)} | {sum(rs) / len(rs):.2f} |")
    out.append(f"\n*Beklenen ≈ {expected:.2f}. Belirgin sapma, drift'in o "
               "kola yüklendiğini gösterir.*\n")

    # --- per-variant summary
    out.append("\n## Varyant özetleri (medyan)\n")
    hdr = "| varyant | açıklama | " + " | ".join(
        lbl for _, lbl, _ in METRICS) + " |"
    out.append(hdr)
    out.append("|" + "---|" * (len(METRICS) + 2))
    for v in variants:
        cells = []
        for key, _, _ in METRICS:
            d = bl.describe(vals(v, key))
            cells.append(f"{d['median']:.2f}" if d else "-")
        out.append(f"| **{v}** | {VARIANT_DESC.get(v, '')} | "
                   + " | ".join(cells) + " |")

    # --- spread within each variant
    out.append("\n## Varyant içi saçılım (CV%)\n")
    out.append("| varyant | TTFT | ITL p50 | ITL p95 | decode |")
    out.append("|---|---|---|---|---|")
    for v in variants:
        cells = []
        for key in ("ttft_ms", "itl_p50_ms", "itl_p95_ms", "decode_tps"):
            d = bl.describe(vals(v, key))
            cells.append(f"{d['cv_pct']:.1f}%" if d else "-")
        out.append(f"| {v} | " + " | ".join(cells) + " |")

    # --- comparisons against baseline
    out.append(f"\n## {BASELINE} baseline'ına karşı\n")
    for key, label, better in METRICS:
        base = vals(BASELINE, key)
        if not base:
            continue
        bd = bl.describe(base)
        out.append(f"\n### {label}  *(baseline medyan {bd['median']:.2f})*\n")
        out.append("| varyant | medyan | fark | anlamlılık | karar |")
        out.append("|---|---|---|---|---|")
        for v in variants:
            if v == BASELINE:
                continue
            vv = vals(v, key)
            if not vv:
                continue
            vd = bl.describe(vv)
            delta = (vd["median"] - bd["median"]) / bd["median"] * 100
            t, df = welch_t(base, vv)
            sig = sig_label(t, df)

            if abs(delta) < NOISE_FLOOR_PCT:
                verdict = "gürültü içinde"
            elif sig in ("ns", "-", "n/a"):
                verdict = "belirsiz"
            else:
                improved = (delta < 0) if better == "lower" else (delta > 0)
                verdict = "**DAHA İYİ**" if improved else "**DAHA KÖTÜ**"
            out.append(f"| {v} | {vd['median']:.2f} | {delta:+.1f}% | "
                       f"{sig} | {verdict} |")

    out.append(f"\n---\n\n*Karar kuralı: |fark| < {NOISE_FLOOR_PCT}% ise "
               "gürültü sayılır ve istatistiksel anlamlılığa bakılmaz. "
               "Eşiğin üstündeyse Welch t-testi ile teyit edilir.*\n")

    report = "\n".join(out)
    path = os.path.join(args.outdir, "affinity_report.md")
    with open(path, "w") as f:
        f.write(report)
    print(report)
    print(f"\n-> {path}")


if __name__ == "__main__":
    main()
