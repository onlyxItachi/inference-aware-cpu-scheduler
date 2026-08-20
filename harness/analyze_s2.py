"""S2 analysis: how much does contention cost, and how much can placement
alone win back?

Two framings, because they answer different questions:

  vs A (idle reference)  -- what does contention still cost this arm?
  gap closed vs B        -- of the damage Linux's default placement suffers,
                            what fraction does this arm recover?

The second is the one that decides whether a cheap topology-aware sched_ext
policy is worth writing. 100% means placement alone fully neutralised the
competing load; 0% means it did nothing.
"""

import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bench_lib as bl
from analyze_affinity import welch_t, sig_label

NOISE_FLOOR_PCT = 2.0
REF = "A_no_load"        # idle reference
DEFAULT = "B_both_free"  # what Linux does today

# Load throughput with no LLM running, 16 threads, ~42 s.
# See results/s2_v2/load_baseline.md.
LOAD_BASE_FREE = 45302.6   # unpinned, all 24 CPUs
LOAD_BASE_E = 19865.3      # confined to the 8 E-cores

ARM_DESC = {
    "A_no_load":       "LLM P-core, yük yok (referans)",
    "B_both_free":     "LLM serbest, yük serbest (Linux varsayılanı)",
    "C_llmP_loadfree": "LLM P-core, yük serbest",
    "D_llmP_loadE":    "LLM P-core, yük E-core'a sürülmüş",
}

METRICS = [
    ("ttft_ms", "TTFT (ms)", "lower"),
    ("itl_p50_ms", "ITL p50 (ms)", "lower"),
    ("itl_p95_ms", "ITL p95 (ms)", "lower"),
    ("itl_p99_ms", "ITL p99 (ms)", "lower"),
    ("decode_tps", "decode (tok/s)", "higher"),
    ("migrations", "migrations", "lower"),
]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--csv", required=True)
    p.add_argument("--outdir", required=True)
    args = p.parse_args()

    rows = list(csv.DictReader(open(args.csv)))
    arms = []
    for r in rows:
        if r["arm"] not in arms:
            arms.append(r["arm"])
    arms.sort()

    def vals(arm, key):
        return [float(r[key]) for r in rows
                if r["arm"] == arm and r[key] not in ("", "None")]

    def med(arm, key):
        d = bl.describe(vals(arm, key))
        return d["median"] if d else None

    out = []
    out.append("# S2 — Rakip iş yükü altında\n")
    n_rounds = len({r["round"] for r in rows})
    out.append(f"**Turlar:** {n_rounds} | **Koşu:** {len(rows)} | "
               f"**yük:** 16 thread (loadgen) | **eşik:** ±{NOISE_FLOOR_PCT}%\n")

    out.append("\n## Ham tablo (medyan)\n")
    out.append("| kol | açıklama | TTFT | ITL p50 | ITL p95 | decode | migration |")
    out.append("|---|---|---|---|---|---|---|")
    for a in arms:
        out.append(f"| **{a}** | {ARM_DESC.get(a, '')} | "
                   f"{med(a, 'ttft_ms'):.0f} | {med(a, 'itl_p50_ms'):.2f} | "
                   f"{med(a, 'itl_p95_ms'):.2f} | {med(a, 'decode_tps'):.2f} | "
                   f"{med(a, 'migrations'):.0f} |")

    out.append(f"\n## Boşta referansa ({REF}) karşı: çekişme ne kadara mal oluyor?\n")
    for key, label, better in METRICS:
        ref = vals(REF, key)
        if not ref:
            continue
        rm = bl.describe(ref)["median"]
        out.append(f"\n**{label}** *(referans {rm:.2f})*\n")
        out.append("| kol | medyan | fark | anlamlılık |")
        out.append("|---|---|---|---|")
        for a in arms:
            if a == REF:
                continue
            v = vals(a, key)
            if not v:
                continue
            m = bl.describe(v)["median"]
            t, df = welch_t(ref, v)
            out.append(f"| {a} | {m:.2f} | {(m - rm) / rm * 100:+.1f}% | "
                       f"{sig_label(t, df)} |")

    out.append(f"\n## Linux varsayılanının ({DEFAULT}) açığını kapatma oranı\n")
    out.append("Yerleştirme tek başına, çekişmenin verdiği hasarın ne kadarını "
               "geri alıyor? %100 = yükü tamamen etkisizleştirdi.\n")
    out.append("| metrik | referans (A) | varsayılan (B) | C | D | "
               "C kapattı | D kapattı |")
    out.append("|---|---|---|---|---|---|---|")
    for key, label, better in METRICS:
        a_m, b_m = med(REF, key), med(DEFAULT, key)
        if a_m is None or b_m is None:
            continue
        gap = a_m - b_m
        cells = []
        for arm in ("C_llmP_loadfree", "D_llmP_loadE"):
            m = med(arm, key)
            if m is None or abs(gap) < 1e-9:
                cells.append((None, "-"))
                continue
            closed = (m - b_m) / gap * 100
            cells.append((m, f"{closed:.0f}%"))
        out.append(f"| {label} | {a_m:.2f} | {b_m:.2f} | "
                   f"{cells[0][0]:.2f} | {cells[1][0]:.2f} | "
                   f"{cells[0][1]} | {cells[1][1]} |")

    out.append("\n*Negatif oran, o kolun varsayılandan daha kötü olduğunu "
               "gösterir.*\n")

    # --- the other side of the ledger
    if any(r.get("load_rate") for r in rows):
        out.append("\n## Rakibin ödediği bedel\n")
        out.append("LLM tarafındaki kazanç, yükün kaybıyla birlikte "
                   "okunmadan bir politika iddiası kurulamaz.\n")
        out.append(f"Yükün LLM'siz referans hızları: serbest "
                   f"{LOAD_BASE_FREE:,.0f} it/s, sadece E-core "
                   f"{LOAD_BASE_E:,.0f} it/s (%{LOAD_BASE_E / LOAD_BASE_FREE * 100:.0f}).\n")
        out.append("| kol | yük yerleşimi | yük it/s | serbest referansa oran | "
                   "kendi yerleşim referansına oran |")
        out.append("|---|---|---|---|---|")
        for a in arms:
            lr = [float(r["load_rate"]) for r in rows
                  if r["arm"] == a and r.get("load_rate") not in ("", "None", None)]
            if not lr:
                continue
            m = bl.describe(lr)["median"]
            placement = [r["load_cpus"] for r in rows if r["arm"] == a][0]
            own_base = LOAD_BASE_E if placement not in ("unpinned", "none") \
                else LOAD_BASE_FREE
            out.append(f"| {a} | {placement} | {m:,.0f} | "
                       f"{m / LOAD_BASE_FREE * 100:.0f}% | "
                       f"{m / own_base * 100:.0f}% |")
        out.append("\n*İkinci sütun politikanın rakibe toplam faturası; "
                   "üçüncüsü bu faturanın ne kadarının yerleşimden "
                   "(E-core'a sürülmekten) geldiğini, ne kadarının LLM ile "
                   "çekişmeden geldiğini ayırır.*\n")

    report = "\n".join(out)
    path = os.path.join(args.outdir, "s2_report.md")
    with open(path, "w") as f:
        f.write(report)
    print(report)
    print(f"\n-> {path}")


if __name__ == "__main__":
    main()
