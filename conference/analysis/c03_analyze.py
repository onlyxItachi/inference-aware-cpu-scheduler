#!/usr/bin/env python3
"""Descriptive analysis for TASK-C03's minimal generality check."""

import argparse
import csv
import json
import math
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT / "harness"
sys.path.insert(0, str(HARNESS))

import bench_lib as bl  # noqa: E402


ARMS = ("BIG_ONLY", "ALL_CORES")
METRICS = ("ttft_ms", "itl_p50_ms", "itl_p95_ms", "itl_p99_ms", "decode_tps")
SIGNAL_FIELDS = (
    "arm", "phase", "n", "mean", "median", "p05", "p95", "min", "max",
    "fraction_above_frozen_hi", "fraction_below_frozen_lo",
)


def numeric(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) \
        and math.isfinite(value)


def rounded(value, digits=3):
    return round(value, digits) if value is not None else None


def describe(values):
    values = [float(value) for value in values if numeric(value)]
    if not values:
        return None
    base = bl.describe(values)
    return {key: rounded(value) for key, value in base.items()}


def quantile_summary(values, frozen_hi=3000.0, frozen_lo=2100.0):
    values = sorted(float(value) for value in values if numeric(value))
    if not values:
        return {
            "n": 0, "mean": None, "median": None, "p05": None,
            "p95": None, "min": None, "max": None,
            "fraction_above_frozen_hi": None,
            "fraction_below_frozen_lo": None,
        }
    return {
        "n": len(values),
        "mean": rounded(statistics.fmean(values)),
        "median": rounded(bl.percentile(values, 50)),
        "p05": rounded(bl.percentile(values, 5)),
        "p95": rounded(bl.percentile(values, 95)),
        "min": rounded(values[0]),
        "max": rounded(values[-1]),
        "fraction_above_frozen_hi": rounded(
            sum(value > frozen_hi for value in values) / len(values)
        ),
        "fraction_below_frozen_lo": rounded(
            sum(value < frozen_lo for value in values) / len(values)
        ),
    }


def run_identifier(record):
    return (
        f"round_{record['round']:02d}_seq_{record['sequence_index']:02d}_"
        f"{record['arm'].lower()}"
    )


def load_records(root):
    records = []
    warnings = []
    for path in sorted((root / "raw" / "runs").glob("round_*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            warnings.append(f"skipped {path.name}: {exc}")
            continue
        if record.get("status") != "ok" or record.get("arm") not in ARMS:
            warnings.append(f"skipped invalid run record {path.name}")
            continue
        records.append(record)
    return records, warnings


def phase_signal_samples(record, root):
    """Return raw signal split only during offline analysis by PHASE_MARK."""
    path = root / record["detector_file"]
    trace = json.loads(path.read_text(encoding="utf-8"))
    if trace.get("marker_used_by_detector") is not False:
        raise ValueError(f"{path} does not prove marker-independent detection")
    internal = record.get("t_internal_phase_ns")
    sent = record.get("t_request_sent_ns")
    last = record.get("t_last_token_ns")
    if not all(numeric(value) for value in (internal, sent, last)):
        raise ValueError(f"{path} lacks internal/request timing")
    split = {"PREFILL": [], "DECODE": []}
    preserved = []
    for sample in trace.get("samples", []):
        timestamp = sample.get("t_ns")
        value = sample.get("norm_ctx_per_cpu_s")
        if not numeric(timestamp) or not numeric(value):
            continue
        if timestamp < sent or timestamp > last:
            continue
        phase = "PREFILL" if timestamp < internal else "DECODE"
        split[phase].append(float(value))
        preserved.append({
            "t_ns": timestamp,
            "norm_ctx_per_cpu_s": float(value),
            "offline_phase": phase,
        })
    return split, preserved


def arm_performance(records):
    return {
        "n": len(records),
        "metrics": {
            metric: describe(record.get(metric) for record in records)
            for metric in METRICS
        },
        "temperature": {
            "start_c": describe(record.get("temp_start_c") for record in records),
            "end_c": describe(record.get("temp_end_c") for record in records),
        },
        "detector_transition_successes": sum(
            record.get("t_external_detect_ns") is not None for record in records
        ),
        "detect_vs_internal_ms": describe(
            record.get("detect_vs_internal_ms") for record in records
        ),
        "run_ids": [run_identifier(record) for record in records],
    }


def mean(arms, arm, metric):
    entry = arms.get(arm, {}).get("metrics", {}).get(metric)
    return entry.get("mean") if entry else None


def performance_effect(arms):
    output = {}
    for metric in ("ttft_ms", "itl_p95_ms", "decode_tps"):
        big = mean(arms, "BIG_ONLY", metric)
        all_cores = mean(arms, "ALL_CORES", metric)
        if big is None or all_cores is None:
            output[metric] = None
            continue
        output[metric] = {
            "big_only_mean": big,
            "all_cores_mean": all_cores,
            "all_cores_minus_big_only": rounded(all_cores - big),
            "all_cores_vs_big_only_pct": (
                rounded((all_cores - big) / big * 100.0) if big else None
            ),
            "metric_direction": (
                "higher_is_better" if metric == "decode_tps"
                else "lower_is_better"
            ),
        }
    return output


def range_overlap(prefill, decode):
    if not prefill or not decode:
        return {
            "status": "NA", "ranges_overlap": None,
            "overlap_width": None, "median_gap_prefill_minus_decode": None,
            "explanation": "both phase distributions require samples",
        }
    p = sorted(prefill)
    d = sorted(decode)
    lower = max(p[0], d[0])
    upper = min(p[-1], d[-1])
    return {
        "status": "observed",
        "ranges_overlap": lower <= upper,
        "overlap_width": rounded(max(0.0, upper - lower)),
        "median_gap_prefill_minus_decode": rounded(
            bl.percentile(p, 50) - bl.percentile(d, 50)
        ),
        "method": "raw range overlap plus median difference; descriptive only",
    }


def validate_rounds(records, warnings):
    grouped = defaultdict(list)
    for record in records:
        grouped[record.get("round")].append(record)
    result = []
    for round_number, members in sorted(grouped.items()):
        members = sorted(members, key=lambda item: item["sequence_index"])
        counts = Counter(member["arm"] for member in members)
        complete = counts == Counter(ARMS)
        if not complete:
            warnings.append(
                f"round {round_number} does not contain both arms exactly once"
            )
        result.append({
            "round": round_number,
            "complete": complete,
            "order": [member["arm"] for member in members],
            "randomized_order_seeds": sorted({
                member.get("randomized_order_seed") for member in members
            }),
        })
    return result


def write_signal_csv(path, summaries):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SIGNAL_FIELDS)
        writer.writeheader()
        for arm in ARMS:
            for phase in ("PREFILL", "DECODE"):
                writer.writerow({"arm": arm, "phase": phase, **summaries[arm][phase]})


def markdown(summary):
    lines = [
        "# TASK-C03 observation summary",
        "",
        f"Selected C03 path: **{summary['selected_c03_path']}**. This is a "
        "descriptive minimal generality check; it does not automatically "
        "declare that placement behavior or external observability generalizes.",
        "",
        "The labels `big` and `compact` are operational labels supplied by "
        "the experiment configuration. They do not assert architectural "
        "equivalence to Intel P/E cores.",
        "",
        "## Performance by arm",
        "",
        "| arm | n | TTFT mean / median ms | ITL p95 mean / median ms | decode tps mean |",
        "|---|---:|---:|---:|---:|",
    ]
    for arm in ARMS:
        data = summary["arms"][arm]
        ttft = data["metrics"]["ttft_ms"] or {}
        p95 = data["metrics"]["itl_p95_ms"] or {}
        tps = data["metrics"]["decode_tps"] or {}
        lines.append(
            f"| {arm} | {data['n']} | {ttft.get('mean')} / "
            f"{ttft.get('median')} | {p95.get('mean')} / {p95.get('median')} | "
            f"{tps.get('mean')} |"
        )
    lines += [
        "", "## ALL_CORES minus BIG_ONLY", "",
        "Positive latency values mean ALL_CORES was slower; positive throughput "
        "means ALL_CORES had higher throughput. These are observations, not a "
        "generality verdict.", "",
        "| metric | absolute difference | relative difference |",
        "|---|---:|---:|",
    ]
    for metric, value in summary["all_cores_vs_big_only"].items():
        value = value or {}
        lines.append(
            f"| {metric} | {value.get('all_cores_minus_big_only')} | "
            f"{value.get('all_cores_vs_big_only_pct')}% |"
        )
    lines += [
        "", "## External signal observations", "",
        "PHASE_MARK is used only here to label samples offline. The detector "
        "ran without a marker callback and never changed affinity.", "",
        "| arm | phase | n | mean | median | p05 | p95 |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for arm in ARMS:
        for phase in ("PREFILL", "DECODE"):
            data = summary["signal"]["distributions"][arm][phase]
            lines.append(
                f"| {arm} | {phase} | {data['n']} | {data['mean']} | "
                f"{data['median']} | {data['p05']} | {data['p95']} |"
            )
    lines += ["", "## Frozen-threshold behavior", ""]
    lines.append(
        "Frozen zero-shot detector: interval=20 ms, hi=3000, lo=2100, k=2."
    )
    for arm in ARMS:
        arm_data = summary["arms"][arm]
        lines.append(
            f"- {arm}: transitions {arm_data['detector_transition_successes']} / "
            f"{arm_data['n']}; detect relative to internal boundary "
            f"{arm_data['detect_vs_internal_ms']}"
        )
    lines += [
        "",
        "Offsets are external criterion crossings relative to the first "
        "internally marked unbatched decode computation. Negative values are "
        "not automatically labeled prediction or anticipation.",
        "",
        "## Checkpoint questions",
        "",
        "- Does ALL_CORES change TTFT in the expected direction?",
        "- Does it also change decode-tail latency or throughput?",
        "- Are prefill/decode signal distributions observably distinct?",
        "- Did the unchanged frozen threshold transition in every run?",
        "- Do temperature ranges suggest a machine-state confound?",
    ]
    if summary["warnings"]:
        lines += ["", "## Warnings", ""]
        lines.extend(f"- {warning}" for warning in summary["warnings"])
    lines.append("")
    return "\n".join(lines)


def analyze(input_dir, output_dir=None):
    root = Path(input_dir).resolve()
    output = Path(output_dir or input_dir).resolve()
    records, warnings = load_records(root)
    selected_paths = sorted({record.get("selected_c03_path") for record in records})
    if len(selected_paths) > 1:
        warnings.append("records mix more than one C03 generality path")
    selected_path = selected_paths[0] if len(selected_paths) == 1 else None
    grouped = defaultdict(list)
    for record in records:
        grouped[record["arm"]].append(record)
        if record.get("detector_mode") != "zero_shot":
            warnings.append(
                f"{run_identifier(record)} is not frozen zero-shot evidence"
            )
    for arm in ARMS:
        if not grouped[arm]:
            warnings.append(f"no successful {arm} runs found")
    arms = {arm: arm_performance(grouped[arm]) for arm in ARMS}

    signal_values = {
        arm: {"PREFILL": [], "DECODE": []} for arm in ARMS
    }
    preserved_counts = {}
    for record in records:
        try:
            split, preserved = phase_signal_samples(record, root)
        except (OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
            warnings.append(f"signal trace skipped for {run_identifier(record)}: {exc}")
            continue
        for phase in ("PREFILL", "DECODE"):
            signal_values[record["arm"]][phase].extend(split[phase])
        preserved_counts[run_identifier(record)] = len(preserved)
    signal_summary = {
        arm: {
            phase: quantile_summary(signal_values[arm][phase])
            for phase in ("PREFILL", "DECODE")
        }
        for arm in ARMS
    }
    separation = {
        arm: range_overlap(
            signal_values[arm]["PREFILL"], signal_values[arm]["DECODE"]
        )
        for arm in ARMS
    }
    rounds = validate_rounds(records, warnings)
    failure_paths = sorted((root / "raw" / "runs" / "failures").glob("*.json"))
    summary = {
        "schema_version": 1,
        "task": "TASK-C03",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "selected_c03_path": selected_path,
        "interpretation_policy": (
            "descriptive observations only; no automatic generality outcome"
        ),
        "protocol": {
            "successful_run_count": len(records),
            "arm_counts": {arm: len(grouped[arm]) for arm in ARMS},
            "round_orders": rounds,
            "failed_attempt_count": len(failure_paths),
            "failure_artifacts": [str(path.relative_to(root)) for path in failure_paths],
        },
        "arms": arms,
        "all_cores_vs_big_only": performance_effect(arms),
        "signal": {
            "ground_truth": "first internally marked unbatched decode computation",
            "marker_use": "offline labeling only",
            "distributions": signal_summary,
            "separation": separation,
            "raw_labeled_sample_counts_by_run": preserved_counts,
            "raw_signal_preserved": (
                len(preserved_counts) == len(records)
                and all(count > 0 for count in preserved_counts.values())
            ),
        },
        "warnings": warnings,
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output / "summary.md").write_text(markdown(summary), encoding="utf-8")
    write_signal_csv(output / "signal_summary.csv", signal_summary)
    return summary


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Analyze TASK-C03 raw evidence without declaring generality"
    )
    parser.add_argument(
        "--input", default=str(ROOT / "results" / "conference_c03")
    )
    parser.add_argument("--outdir", default="")
    args = parser.parse_args(argv)
    if not Path(args.input).exists():
        parser.error(f"--input does not exist: {args.input}")
    args.outdir = args.outdir or args.input
    return args


def main(argv=None):
    args = parse_args(argv)
    summary = analyze(args.input, args.outdir)
    print(json.dumps({
        "task": summary["task"],
        "selected_c03_path": summary["selected_c03_path"],
        "successful_runs": summary["protocol"]["successful_run_count"],
        "summary_json": str(Path(args.outdir) / "summary.json"),
        "summary_md": str(Path(args.outdir) / "summary.md"),
        "signal_summary_csv": str(Path(args.outdir) / "signal_summary.csv"),
        "warnings": summary["warnings"],
    }, indent=2))


if __name__ == "__main__":
    main()
