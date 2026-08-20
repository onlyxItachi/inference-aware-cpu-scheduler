"""Faz 0 / K3 analysis: how much does one configuration disagree with itself?

Produces:
  - spread stats (median, std, min, max, CV%) per metric
  - drift check: does run number predict the result? (system heating up)
  - thermal check: does package temperature predict the result?
  - ASCII plots to stdout, standalone SVG scatter plots to disk
  - report.md

No third-party dependencies, so this runs anywhere the harness runs.
"""

import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bench_lib as bl

# With n=20, |r| >= 0.444 is significant at p<0.05 (two-tailed).
# Below that, a visible trend line is not evidence of anything.
R_CRIT_N20 = 0.444

METRICS = [
    ("ttft_ms", "TTFT (ms)"),
    ("itl_p50_ms", "ITL p50 (ms)"),
    ("itl_p95_ms", "ITL p95 (ms)"),
    ("itl_p99_ms", "ITL p99 (ms)"),
    ("itl_max_ms", "ITL max (ms)"),
    ("decode_tps", "decode (tok/s)"),
    ("migrations", "migrations"),
    ("ctx_switches", "ctx switches"),
    ("freq_p_avg_mhz", "P-core freq (MHz)"),
    ("temp_end_c", "pkg temp end (C)"),
]


def pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = sum((x - mx) ** 2 for x in xs) ** 0.5
    dy = sum((y - my) ** 2 for y in ys) ** 0.5
    if dx == 0 or dy == 0:
        return None
    return num / (dx * dy)


def linreg_slope(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den


def ascii_plot(xs, ys, ylabel, height=14, width=60):
    """Terminal scatter of ys against xs."""
    lo, hi = min(ys), max(ys)
    if hi == lo:
        hi = lo + 1e-9
    grid = [[" "] * width for _ in range(height)]
    xlo, xhi = min(xs), max(xs)
    xspan = (xhi - xlo) or 1
    for x, y in zip(xs, ys):
        col = int((x - xlo) / xspan * (width - 1))
        row = height - 1 - int((y - lo) / (hi - lo) * (height - 1))
        grid[row][col] = "*"
    lines = []
    for i, row in enumerate(grid):
        val = hi - (hi - lo) * i / (height - 1)
        lines.append(f"{val:9.2f} |{''.join(row)}")
    lines.append(" " * 10 + "+" + "-" * width)
    lines.append(" " * 11 + f"run {int(xlo)}" +
                 " " * (width - 12) + f"run {int(xhi)}")
    return f"{ylabel} vs run number\n" + "\n".join(lines)


def svg_scatter(xs, ys, xlabel, ylabel, path):
    W, H, PAD = 640, 360, 60
    lo, hi = min(ys), max(ys)
    if hi == lo:
        hi = lo + 1e-9
    xlo, xhi = min(xs), max(xs)
    xspan = (xhi - xlo) or 1

    def px(x):
        return PAD + (x - xlo) / xspan * (W - 2 * PAD)

    def py(y):
        return H - PAD - (y - lo) / (hi - lo) * (H - 2 * PAD)

    pts = "".join(
        f'<circle cx="{px(x):.1f}" cy="{py(y):.1f}" r="4" '
        f'fill="#2b6cb0" fill-opacity="0.75"/>'
        for x, y in zip(xs, ys)
    )
    slope = linreg_slope(xs, ys)
    trend = ""
    if slope is not None:
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        y1, y2 = my + slope * (xlo - mx), my + slope * (xhi - mx)
        trend = (f'<line x1="{px(xlo):.1f}" y1="{py(y1):.1f}" '
                 f'x2="{px(xhi):.1f}" y2="{py(y2):.1f}" '
                 f'stroke="#e53e3e" stroke-width="2" '
                 f'stroke-dasharray="6,4"/>')
    ticks = ""
    for i in range(5):
        v = lo + (hi - lo) * i / 4
        y = py(v)
        ticks += (f'<line x1="{PAD}" y1="{y:.1f}" x2="{W - PAD}" y2="{y:.1f}" '
                  f'stroke="#e2e8f0" stroke-width="1"/>'
                  f'<text x="{PAD - 8}" y="{y + 4:.1f}" font-size="11" '
                  f'text-anchor="end" fill="#4a5568">{v:.1f}</text>')
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">
<rect width="{W}" height="{H}" fill="white"/>
{ticks}
<line x1="{PAD}" y1="{H - PAD}" x2="{W - PAD}" y2="{H - PAD}" stroke="#2d3748" stroke-width="1.5"/>
<line x1="{PAD}" y1="{PAD}" x2="{PAD}" y2="{H - PAD}" stroke="#2d3748" stroke-width="1.5"/>
{trend}{pts}
<text x="{W / 2}" y="{H - 18}" font-size="13" text-anchor="middle" fill="#2d3748">{xlabel}</text>
<text x="18" y="{H / 2}" font-size="13" text-anchor="middle" fill="#2d3748" transform="rotate(-90 18 {H / 2})">{ylabel}</text>
</svg>"""
    with open(path, "w") as f:
        f.write(svg)


def fmt_row(label, d):
    if not d:
        return f"| {label} | - | - | - | - | - |"
    return (f"| {label} | {d['median']:.2f} | {d['std']:.2f} | "
            f"{d['min']:.2f} | {d['max']:.2f} | {d['cv_pct']:.1f}% |")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--csv", required=True)
    p.add_argument("--outdir", required=True)
    args = p.parse_args()

    with open(args.csv) as f:
        rows = list(csv.DictReader(f))
    if not rows:
        sys.exit("no rows in CSV")

    def col(name):
        out = []
        for r in rows:
            v = r.get(name, "")
            if v not in ("", "None"):
                try:
                    out.append(float(v))
                except ValueError:
                    pass
        return out

    runs = col("run")
    n = len(rows)
    out = []
    out.append("# Faz 0 — Gürültü Tabanı (K3)\n")
    out.append(f"**Runs:** {n}  ")
    r0 = rows[0]
    out.append(f"**Config:** threads={r0['threads']}, cpus={r0['cpus']}, "
               f"ctx={r0['ctx']}, batch={r0['batch']}, ubatch={r0['ubatch']}, "
               f"seed={r0['seed']}, n_predict={r0['n_predict']}, "
               f"prompt_tokens={r0['prompt_tokens']}\n")

    out.append("\n## Spread (same config, repeated)\n")
    out.append("| metric | median | std | min | max | CV% |")
    out.append("|---|---|---|---|---|---|")
    stats = {}
    for key, label in METRICS:
        vals = col(key)
        stats[key] = bl.describe(vals)
        out.append(fmt_row(label, stats[key]))

    out.append("\n## Drift — does run number predict the result?\n")
    out.append("| metric | Pearson r vs run | slope /run | verdict |")
    out.append("|---|---|---|---|")
    for key, label in [("ttft_ms", "TTFT"), ("itl_p95_ms", "ITL p95"),
                       ("decode_tps", "decode tps"),
                       ("temp_end_c", "pkg temp end")]:
        vals = col(key)
        if len(vals) != len(runs):
            continue
        r = pearson(runs, vals)
        s = linreg_slope(runs, vals)
        verdict = ("DRIFT" if r is not None and abs(r) >= R_CRIT_N20
                   else "no trend")
        out.append(f"| {label} | {r:+.3f} | {s:+.4f} | {verdict} |"
                   if r is not None else f"| {label} | - | - | - |")

    out.append(f"\n*n={n}; |r| >= {R_CRIT_N20} is significant at p<0.05. "
               "Below that, treat any apparent slope as noise.*\n")

    out.append("\n## Thermal coupling\n")
    out.append("| pair | Pearson r | verdict |")
    out.append("|---|---|---|")
    tstart = col("temp_start_c")
    for key, label in [("ttft_ms", "TTFT"), ("itl_p95_ms", "ITL p95"),
                       ("decode_tps", "decode tps")]:
        vals = col(key)
        if len(vals) != len(tstart) or not tstart:
            continue
        r = pearson(tstart, vals)
        if r is None:
            continue
        verdict = "COUPLED" if abs(r) >= R_CRIT_N20 else "no coupling"
        out.append(f"| start temp vs {label} | {r:+.3f} | {verdict} |")

    # Plots
    for key, label in [("ttft_ms", "TTFT (ms)"),
                       ("itl_p95_ms", "ITL p95 (ms)"),
                       ("decode_tps", "decode (tok/s)")]:
        vals = col(key)
        if len(vals) != len(runs):
            continue
        print(ascii_plot(runs, vals, label))
        print()
        svg_scatter(runs, vals, "run number", label,
                    os.path.join(args.outdir, f"{key}_vs_run.svg"))

    # Noise floor: the number every later claim is measured against.
    out.append("\n## Noise floor\n")
    out.append("| metric | CV% | 95% of repeats fall within |")
    out.append("|---|---|---|")
    floor = {}
    for key, label in [("ttft_ms", "TTFT"), ("itl_p50_ms", "ITL p50"),
                       ("itl_p95_ms", "ITL p95"),
                       ("decode_tps", "decode tps")]:
        d = stats.get(key)
        if not d:
            continue
        band = 1.96 * d["std"] / d["median"] * 100 if d["median"] else 0
        floor[key] = band
        out.append(f"| {label} | {d['cv_pct']:.1f}% | ±{band:.1f}% |")

    worst = max(floor.values()) if floor else 0
    out.append(f"\n**Sonuç:** Bu makinede, bu konfigürasyonda, "
               f"**%{worst:.1f}'ten küçük farklar gürültüdür.** "
               "Bunun altındaki hiçbir fark bulgu olarak raporlanamaz.\n")

    report = "\n".join(out)
    path = os.path.join(args.outdir, "report.md")
    with open(path, "w") as f:
        f.write(report)
    print(report)
    print(f"\n-> {path}")


if __name__ == "__main__":
    main()
