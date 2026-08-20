"""İŞ 3 — a detector that survives its own policy's feedback.

Problem with v1: the threshold is absolute (20 000 switches/s) while the
signal scales with how many cores the process is running on. If the policy
reacts to "decode" by cutting 8 cores to 6, the signal falls by ~25% on its
own -- margin shrinks from 58% to 18% -- and under contention the loop can
close: detect decode -> cut cores -> signal drops -> detect prefill ->
restore cores -> detect decode -> ...

Three fixes:

3a NORMALISE per CPU-second, not per wall-second.
   signal = Δctx_switches / Δcpu_time_consumed
   This is switches per unit of CPU work, so it is invariant to core count
   by construction. The normaliser is read from /proc/<pid>/stat
   (utime+stime), needs no knowledge of the policy's own decisions, and
   self-calibrates if the process changes its thread count.

3b HYSTERESIS: separate rising and falling thresholds, so a signal sitting
   near one boundary cannot flip the state every sample.

3c OSCILLATION TEST: replay recorded data through a closed loop in which
   core count follows the phase decision, and rescale the signal as the
   policy would have caused. v1 (absolute) should oscillate; v2
   (normalised) should not.
"""

import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bench_lib as bl

HZ = 100  # getconf CLK_TCK


def series(samples):
    """Per-sample raw and CPU-normalised context-switch rates."""
    out = []
    for i in range(1, len(samples)):
        a, b = samples[i - 1], samples[i]
        dt = (b["t_ns"] - a["t_ns"]) / 1e9
        if dt <= 0 or a.get("cputime_jiffies") is None \
                or b.get("cputime_jiffies") is None:
            continue
        dctx = b["ctx_switches"] - a["ctx_switches"]
        cpu_s = (b["cputime_jiffies"] - a["cputime_jiffies"]) / HZ
        out.append({
            "t_ns": b["t_ns"],
            "raw": dctx / dt,
            "norm": (dctx / cpu_s) if cpu_s > 0 else 0.0,
            "cores": cpu_s / dt,
        })
    return out


def run_state_machine(vals, hi, lo, k=2):
    """Hysteresis state machine. Returns (first_decode_index, flip_count)."""
    state = "prefill"
    run = 0
    first = None
    flips = 0
    for i, v in enumerate(vals):
        if state == "prefill":
            if v > hi:
                run += 1
                if run >= k:
                    state = "decode"
                    flips += 1
                    if first is None:
                        first = i - k + 1
                    run = 0
            else:
                run = 0
        else:
            if v < lo:
                run += 1
                if run >= k:
                    state = "prefill"
                    flips += 1
                    run = 0
            else:
                run = 0
    return first, flips


def evaluate(files, hi, lo, k, signal="norm"):
    res = []
    for path in files:
        d = json.load(open(path))
        s = series(d["samples"])
        if len(s) < 5:
            continue
        tf, t0, tl = (d["t_first_token_ns"], d["t_request_sent_ns"],
                      d["t_last_token_ns"])
        win = [x for x in s if t0 <= x["t_ns"] <= tl]
        if not win:
            continue
        vals = [x[signal] for x in win]
        first, flips = run_state_machine(vals, hi, lo, k)
        lat = ((win[first]["t_ns"] - tf) / 1e6) if first is not None else None

        # per-sample accuracy using the same hysteresis state trace
        state, run, ok = "prefill", 0, 0
        for x in win:
            v = x[signal]
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
            if (x["t_ns"] >= tf) == (state == "decode"):
                ok += 1
        pre = sorted(x[signal] for x in win if x["t_ns"] < tf)
        dec = sorted(x[signal] for x in win if x["t_ns"] >= tf)
        res.append({
            "file": os.path.basename(path),
            "accuracy": ok / len(win) * 100,
            "latency_ms": lat,
            "flips": flips,
            "prefill_p95": bl.percentile(pre, 95) if pre else None,
            "decode_p5": bl.percentile(dec, 5) if dec else None,
            "ttft_ms": d.get("ttft_ms"),
            "prompt_hint": d.get("cpus"),
        })
    return res


def oscillation_test(files, hi, lo, k, signal, full_cores=8, cut_cores=6):
    """Closed loop: core count follows the phase decision.

    While the state is 'decode' the policy would be running on cut_cores, so
    a raw (per-wall-second) signal must be scaled by cut/full. A normalised
    signal is unaffected -- that is exactly what is being tested.
    """
    total_flips = 0
    per_run = []
    for path in files:
        d = json.load(open(path))
        s = series(d["samples"])
        tf, t0, tl = (d["t_first_token_ns"], d["t_request_sent_ns"],
                      d["t_last_token_ns"])
        win = [x for x in s if t0 <= x["t_ns"] <= tl]
        state, run, flips = "prefill", 0, 0
        for x in win:
            v = x[signal]
            if signal == "raw" and state == "decode":
                v *= cut_cores / full_cores      # policy cut the cores
            if state == "prefill":
                if v > hi:
                    run += 1
                    if run >= k:
                        state, run, flips = "decode", 0, flips + 1
                else:
                    run = 0
            else:
                if v < lo:
                    run += 1
                    if run >= k:
                        state, run, flips = "prefill", 0, flips + 1
                else:
                    run = 0
        per_run.append(flips)
        total_flips += flips
    return per_run, total_flips


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dirs", nargs="+", required=True)
    p.add_argument("--hi", type=float, default=2500.0)
    p.add_argument("--lo", type=float, default=1800.0)
    p.add_argument("--k", type=int, default=2)
    p.add_argument("--signal", default="norm", choices=["norm", "raw"])
    p.add_argument("--distribution", action="store_true")
    p.add_argument("--oscillation", action="store_true")
    args = p.parse_args()

    files = []
    for d in args.dirs:
        files += sorted(glob.glob(os.path.join(d, "r*_*.json")))
    if not files:
        sys.exit("no runs found")

    if args.distribution:
        print(f"{'koşu':>26s} {'prefill p95':>12s} {'decode p5':>11s} {'oran':>7s}")
        for path in files:
            d = json.load(open(path))
            s = series(d["samples"])
            tf, t0, tl = (d["t_first_token_ns"], d["t_request_sent_ns"],
                          d["t_last_token_ns"])
            win = [x for x in s if t0 <= x["t_ns"] <= tl]
            pre = sorted(x[args.signal] for x in win if x["t_ns"] < tf)
            dec = sorted(x[args.signal] for x in win if x["t_ns"] >= tf)
            if not pre or not dec:
                continue
            a, b = bl.percentile(pre, 95), bl.percentile(dec, 5)
            print(f"{os.path.basename(path):>26s} {a:12.0f} {b:11.0f} "
                  f"{b / a if a else 0:6.1f}x")
        return

    if args.oscillation:
        print(f"Salınım testi (decode'da {8}->{6} çekirdek varsayımı), "
              f"k={args.k}\n")
        print(f"{'sinyal':>8s} {'hi':>8s} {'lo':>8s} {'toplam geçiş':>14s} "
              f"{'koşu başına max':>16s} {'ideal':>7s}")
        for sig, hi, lo in (("raw", 20000, 20000),
                            ("raw", 20000, 14000),
                            ("norm", args.hi, args.hi),
                            ("norm", args.hi, args.lo)):
            per, tot = oscillation_test(files, hi, lo, args.k, sig)
            print(f"{sig:>8s} {hi:8.0f} {lo:8.0f} {tot:14d} "
                  f"{max(per):16d} {1:7d}")
        print("\n*ideal = 1 (koşu başına tek prefill->decode geçişi). "
              "Fazlası salınımdır.*")
        return

    res = evaluate(files, args.hi, args.lo, args.k, args.signal)
    accs = [r["accuracy"] for r in res]
    lats = sorted(r["latency_ms"] for r in res if r["latency_ms"] is not None)
    print(f"Dedektör v2: sinyal={args.signal}, hi={args.hi:,.0f}, "
          f"lo={args.lo:,.0f}, k={args.k}\n")
    print(f"{'koşu':>26s} {'doğruluk':>9s} {'gecikme':>10s} {'geçiş':>6s}")
    for r in res:
        lat = f"{r['latency_ms']:.1f}ms" if r["latency_ms"] is not None else "KAÇIRDI"
        print(f"{r['file']:>26s} {r['accuracy']:8.2f}% {lat:>10s} "
              f"{r['flips']:6d}")
    print(f"\nDoğruluk: medyan {bl.percentile(sorted(accs), 50):.2f}%  "
          f"min {min(accs):.2f}%")
    if lats:
        print(f"Gecikme : medyan {bl.percentile(lats, 50):+.1f} ms  "
              f"p95 {bl.percentile(lats, 95):+.1f} ms")
    print(f"Geçiş   : max {max(r['flips'] for r in res)} "
          f"(ideal 1; fazlası salınım)")


if __name__ == "__main__":
    main()
