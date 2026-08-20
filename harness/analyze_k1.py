"""K1 analysis: does decode stop scaling with physical cores?

The headline is not either curve alone but the *comparison*. Prefill is
dense GEMM and should scale close to linearly with cores. Decode streams
the whole model per token and, if bandwidth-bound, should flatten early.

If the two curves diverge, that is the prefill/decode asymmetry the project
is looking for -- and unlike the earlier migration claim, it is measured
with only one variable moving (cores), each thread on its own physical
core.
"""

import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bench_lib as bl

NOISE_FLOOR_PCT = 2.0
# Weights streamed per decoded token ~ model file size. A proxy, not exact:
# it ignores KV-cache traffic and assumes no weight stays resident in LLC.
MODEL_BYTES = 5_680_522_464


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
    arms.sort(key=lambda a: int(a[1:]))

    def med(arm, key):
        d = bl.describe([float(r[key]) for r in rows
                         if r["arm"] == arm and r[key] not in ("", "None")])
        return d["median"] if d else None

    def threads(arm):
        return int([r for r in rows if r["arm"] == arm][0]["threads"])

    out = []
    out.append("# K1 — Thread/çekirdek taraması\n")
    n_rounds = len({r["round"] for r in rows})
    out.append(f"**Turlar:** {n_rounds} | **Koşu:** {len(rows)} | "
               f"**eşik:** ±{NOISE_FLOOR_PCT}%\n")
    out.append("Her kolda **thread başına bir fiziksel P-core**. t16 hariç: "
               "8 fiziksel çekirdek üzerinde 16 thread (SMT).\n")

    # --- prefill scaling: tokens/s = prompt_tokens / TTFT
    out.append("\n## Ham eğriler\n")
    out.append("| kol | thread | fiz. çekirdek | TTFT (ms) | prefill tok/s | "
               "decode tok/s | ITL p50 | migration |")
    out.append("|---|---|---|---|---|---|---|---|")
    data = {}
    for a in arms:
        t = threads(a)
        cores = 8 if a == "t16" else t
        ttft = med(a, "ttft_ms")
        ptok = med(a, "prompt_tokens")
        prefill_tps = ptok / (ttft / 1000.0) if ttft else None
        dec = med(a, "decode_tps")
        data[a] = {"threads": t, "cores": cores, "prefill": prefill_tps,
                   "decode": dec, "ttft": ttft}
        out.append(f"| {a} | {t} | {cores} | {ttft:.0f} | {prefill_tps:.1f} | "
                   f"{dec:.2f} | {med(a, 'itl_p50_ms'):.2f} | "
                   f"{med(a, 'migrations'):.0f} |")

    # --- scaling relative to the smallest arm
    base = arms[0]
    b = data[base]
    out.append(f"\n## Ölçeklenme ({base} = 1.00x taban)\n")
    out.append("| kol | çekirdek katı | prefill hızlanma | prefill verim | "
               "decode hızlanma | decode verim |")
    out.append("|---|---|---|---|---|---|")
    for a in arms:
        d = data[a]
        cf = d["cores"] / b["cores"]
        ps = d["prefill"] / b["prefill"]
        ds = d["decode"] / b["decode"]
        out.append(f"| {a} | {cf:.1f}x | {ps:.2f}x | {ps / cf * 100:.0f}% | "
                   f"{ds:.2f}x | {ds / cf * 100:.0f}% |")
    out.append("\n*Verim = hızlanma / çekirdek katı. %100 = mükemmel "
               "ölçeklenme; düşüş doyuma işaret eder.*\n")

    # --- marginal return of each added pair of cores
    out.append("\n## Eklenen her çekirdeğin marjinal getirisi\n")
    out.append("| geçiş | +çekirdek | prefill Δ | decode Δ |")
    out.append("|---|---|---|---|")
    phys = [a for a in arms if a != "t16"]
    for i in range(1, len(phys)):
        prev, cur = data[phys[i - 1]], data[phys[i]]
        dc = cur["cores"] - prev["cores"]
        pd = (cur["prefill"] - prev["prefill"]) / prev["prefill"] * 100
        dd = (cur["decode"] - prev["decode"]) / prev["decode"] * 100
        out.append(f"| {phys[i - 1]} → {phys[i]} | +{dc} | {pd:+.1f}% | "
                   f"{dd:+.1f}% |")
    if "t16" in data:
        prev, cur = data[phys[-1]], data["t16"]
        pd = (cur["prefill"] - prev["prefill"]) / prev["prefill"] * 100
        dd = (cur["decode"] - prev["decode"]) / prev["decode"] * 100
        out.append(f"| {phys[-1]} → t16 | +0 (SMT, thread 8→16) | {pd:+.1f}% | "
                   f"{dd:+.1f}% |")

    # --- implied bandwidth
    out.append("\n## Ima edilen bellek trafiği (decode)\n")
    out.append("| kol | decode tok/s | ima edilen GB/s |")
    out.append("|---|---|---|")
    for a in arms:
        gbs = data[a]["decode"] * MODEL_BYTES / 1e9
        out.append(f"| {a} | {data[a]['decode']:.2f} | {gbs:.1f} |")
    out.append("\n*Token başına ağırlıkların tamamının okunduğu varsayımıyla "
               "kaba bir alt sınır; KV-cache trafiğini ve LLC'de kalan "
               "ağırlıkları saymaz.*\n")

    # --- verdict
    out.append("\n## Karar\n")
    last_phys = data[phys[-1]]
    eff_p = (last_phys["prefill"] / b["prefill"]) / \
            (last_phys["cores"] / b["cores"]) * 100
    eff_d = (last_phys["decode"] / b["decode"]) / \
            (last_phys["cores"] / b["cores"]) * 100
    out.append(f"{base} → {phys[-1]} ({b['cores']} → {last_phys['cores']} "
               f"çekirdek): prefill verimi **%{eff_p:.0f}**, "
               f"decode verimi **%{eff_d:.0f}**.\n")
    gap = eff_p - eff_d
    if gap > 10:
        out.append(f"Prefill, decode'dan **{gap:.0f} puan** daha iyi "
                   "ölçekleniyor. İki faz çekirdek eklemeye farklı tepki "
                   "veriyor — projenin aradığı asimetri için doğrudan, "
                   "tek değişkenli kanıt.\n")
    elif gap < -10:
        out.append(f"Decode prefill'den {-gap:.0f} puan daha iyi "
                   "ölçekleniyor — beklenenin tersi, incelenmeli.\n")
    else:
        out.append("İki faz benzer ölçekleniyor; bu veride asimetri yok.\n")

    report = "\n".join(out)
    path = os.path.join(args.outdir, "k1_report.md")
    with open(path, "w") as f:
        f.write(report)
    print(report)
    print(f"\n-> {path}")


if __name__ == "__main__":
    main()
