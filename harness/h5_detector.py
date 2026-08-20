"""H5 — a phase detector built only from OS-visible signals, and its evaluation.

Detector (deliberately plain logic, no ML):

    ctx_switch_rate > THRESHOLD  for K consecutive samples  =>  DECODE

Rationale from the data: llama.cpp synchronises its threads at every layer,
and decode runs one full forward pass *per token*. Prefill runs a single
pass over the whole prompt. So decode performs the barrier dance hundreds
of times a second while prefill barely does it at all. The rate difference
is roughly an order of magnitude, which is what makes a fixed threshold
viable.

Two metrics, per the brief:

  ACCURACY  -- per-sample classification against ground truth
  LATENCY   -- how long after the true boundary the detector first says
               DECODE. This is the metric that decides usability: a
               detector that needs 200 ms is useless on short decodes.

On the sign of latency: ground truth here is the first token's arrival at
the HTTP client, which necessarily lags the compute-side phase change by
the cost of finishing the token and pushing it through the socket. A
detector can therefore legitimately fire slightly *before* ground truth.
Negative latencies are reported as-is rather than clamped, and discussed.
"""

import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bench_lib as bl


def rates(samples):
    """[(t_ns, ctx_rate, mig_rate, procs_running, freq_khz)] from cumulative counters."""
    out = []
    for i in range(1, len(samples)):
        a, b = samples[i - 1], samples[i]
        dt = (b["t_ns"] - a["t_ns"]) / 1e9
        if dt <= 0:
            continue
        f = b.get("freq_p_top8_khz") or []
        out.append({
            "t_ns": b["t_ns"],
            "ctx_rate": (b["ctx_switches"] - a["ctx_switches"]) / dt,
            "mig_rate": (b["migrations"] - a["migrations"]) / dt,
            "procs_running": b.get("procs_running"),
            "freq_khz": sum(f) / len(f) if f else None,
        })
    return out


def detect(rs, threshold, k):
    """First index where ctx_rate stays above threshold for k samples."""
    run = 0
    for i, r in enumerate(rs):
        if r["ctx_rate"] > threshold:
            run += 1
            if run >= k:
                return i - k + 1
        else:
            run = 0
    return None


def evaluate(files, threshold, k):
    per_run = []
    for path in files:
        d = json.load(open(path))
        rs = rates(d["samples"])
        if len(rs) < 5:
            continue
        t_first = d["t_first_token_ns"]
        t_sent = d["t_request_sent_ns"]
        t_last = d["t_last_token_ns"]

        idx = detect(rs, threshold, k)
        det_t = rs[idx]["t_ns"] if idx is not None else None
        latency_ms = ((det_t - t_first) / 1e6) if det_t else None

        # Per-sample accuracy, restricted to the request window: before the
        # request is sent there is no phase to classify.
        tp = tn = fp = fn = 0
        for r in rs:
            if not (t_sent <= r["t_ns"] <= t_last):
                continue
            truth_decode = r["t_ns"] >= t_first
            pred_decode = r["ctx_rate"] > threshold
            if truth_decode and pred_decode:
                tp += 1
            elif truth_decode and not pred_decode:
                fn += 1
            elif not truth_decode and pred_decode:
                fp += 1
            else:
                tn += 1
        total = tp + tn + fp + fn
        per_run.append({
            "file": os.path.basename(path),
            "cpus": d.get("cpus"),
            "ttft_ms": d.get("ttft_ms"),
            "latency_ms": latency_ms,
            "accuracy": (tp + tn) / total * 100 if total else None,
            "tp": tp, "tn": tn, "fp": fp, "fn": fn,
            # separation: how far apart are the two phases in this signal
            "prefill_ctx_p95": bl.percentile(
                sorted(r["ctx_rate"] for r in rs
                       if t_sent <= r["t_ns"] < t_first), 95),
            "decode_ctx_p5": bl.percentile(
                sorted(r["ctx_rate"] for r in rs
                       if t_first <= r["t_ns"] <= t_last), 5),
        })
    return per_run


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dir", required=True)
    p.add_argument("--threshold", type=float, default=20000.0)
    p.add_argument("--k", type=int, default=2)
    p.add_argument("--sweep", action="store_true")
    p.add_argument("--out", default="")
    args = p.parse_args()

    files = sorted(glob.glob(os.path.join(args.dir, "r*_*.json")))
    if not files:
        sys.exit(f"no runs in {args.dir}")

    if args.sweep:
        print(f"{'threshold':>10s} {'k':>3s} {'doğruluk%':>10s} "
              f"{'gecikme p50':>12s} {'gecikme p95':>12s} {'kaçırılan':>10s}")
        for th in (5000, 10000, 20000, 30000, 40000):
            for k in (1, 2, 3):
                res = evaluate(files, th, k)
                accs = [r["accuracy"] for r in res if r["accuracy"] is not None]
                lats = sorted(r["latency_ms"] for r in res
                              if r["latency_ms"] is not None)
                missed = sum(1 for r in res if r["latency_ms"] is None)
                print(f"{th:10.0f} {k:3d} "
                      f"{sum(accs) / len(accs):9.2f}% "
                      f"{bl.percentile(lats, 50):11.1f}ms "
                      f"{bl.percentile(lats, 95):11.1f}ms "
                      f"{missed:10d}")
        return

    res = evaluate(files, args.threshold, args.k)
    accs = [r["accuracy"] for r in res]
    lats = sorted(r["latency_ms"] for r in res if r["latency_ms"] is not None)
    seps = [(r["decode_ctx_p5"], r["prefill_ctx_p95"]) for r in res]

    print(f"Dedektör: ctx_switch_rate > {args.threshold:,.0f}/s, "
          f"{args.k} ardışık örnek (20 ms periyot)\n")
    print(f"{'koşu':>22s} {'cpus':>10s} {'doğruluk':>9s} {'gecikme':>10s}")
    for r in res:
        lat = f"{r['latency_ms']:.1f}ms" if r["latency_ms"] is not None else "KAÇIRDI"
        print(f"{r['file']:>22s} {str(r['cpus'])[:10]:>10s} "
              f"{r['accuracy']:8.2f}% {lat:>10s}")

    print(f"\nDoğruluk : medyan {bl.percentile(sorted(accs), 50):.2f}%  "
          f"min {min(accs):.2f}%")
    print(f"Gecikme  : medyan {bl.percentile(lats, 50):+.1f} ms  "
          f"p95 {bl.percentile(lats, 95):+.1f} ms  "
          f"min {min(lats):+.1f}  max {max(lats):+.1f}")
    print(f"Ayrışma  : prefill ctx p95 = "
          f"{max(s[1] for s in seps):,.0f}/s , "
          f"decode ctx p5 = {min(s[0] for s in seps):,.0f}/s")

    if args.out:
        with open(args.out, "w") as f:
            json.dump({"threshold": args.threshold, "k": args.k,
                       "runs": res}, f, indent=2)


if __name__ == "__main__":
    main()
