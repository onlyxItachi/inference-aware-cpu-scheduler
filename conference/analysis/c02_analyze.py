#!/usr/bin/env python3
"""Observation-only analysis for TASK-C02.

The analyzer compares contemporaneous five-arm runs, derives phase/action
timing from the internal boundary, and computes direction-aware oracle
recovery.  It deliberately does not make the C02 PASS/FAIL decision or causal
claims about Intel Thread Director/HFI.
"""

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT / "harness"
sys.path.insert(0, str(HARNESS))

import bench_lib as bl  # noqa: E402


ARMS = ("STOCK", "STATIC_P", "STATIC_PE", "EXTERNAL", "ORACLE")
EXPECTED_PHASE_SOURCE = {
    "STOCK": "none",
    "STATIC_P": "none",
    "STATIC_PE": "none",
    "EXTERNAL": "external_proc",
    "ORACLE": "internal_oracle",
}
METRICS = (
    "ttft_ms", "itl_p50_ms", "itl_p95_ms", "itl_p99_ms", "decode_tps",
    "total_migrations", "total_ctx_switches", "temp_start_c", "temp_end_c",
    "freq_p_avg_mhz", "freq_p_busy_mhz", "freq_e_avg_mhz", "energy_j",
    "j_per_token", "affinity_cost_us",
)
RECOVERY_RELATIVE_EPSILON = 1e-3


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def numeric(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def rounded(value, digits=3):
    return round(value, digits) if value is not None else None


def describe(values):
    values = [numeric(value) for value in values]
    values = [value for value in values if value is not None]
    if not values:
        return None
    return {
        key: rounded(value)
        for key, value in bl.describe(values).items()
    }


def internal_relative_ms(record, timestamp_field):
    """Use the internal boundary, never first-token arrival, as time zero."""
    internal = numeric(record.get("t_internal_phase_ns"))
    timestamp = numeric(record.get(timestamp_field))
    if internal is None or timestamp is None:
        return None
    return (timestamp - internal) / 1e6


def timing_for_run(record):
    return {
        "marker_delivery_latency_ms": internal_relative_ms(
            record, "t_marker_seen_ns"
        ),
        "external_detect_vs_internal_ms": internal_relative_ms(
            record, "t_external_detect_ns"
        ),
        "external_action_vs_internal_ms": (
            internal_relative_ms(record, "t_affinity_start_ns")
            if record.get("arm") == "EXTERNAL" else None
        ),
        "oracle_action_vs_internal_ms": (
            internal_relative_ms(record, "t_affinity_start_ns")
            if record.get("arm") == "ORACLE" else None
        ),
        "affinity_cost_us": numeric(record.get("affinity_cost_us")),
    }


def recovery(anchor, external, oracle, higher_is_better,
             relative_epsilon=RECOVERY_RELATIVE_EPSILON):
    """Compute un-clamped oracle recovery with metric-aware direction."""
    values = (numeric(anchor), numeric(external), numeric(oracle))
    if any(value is None for value in values):
        return {
            "value": None,
            "status": "NA",
            "explanation": "anchor/external/oracle metric is missing",
        }
    anchor, external, oracle = values
    if higher_is_better:
        numerator = external - anchor
        denominator = oracle - anchor
        direction = "higher_is_better"
    else:
        numerator = anchor - external
        denominator = anchor - oracle
        direction = "lower_is_better"
    scale = max(abs(anchor), abs(oracle), 1.0)
    threshold = scale * relative_epsilon
    if abs(denominator) <= threshold:
        return {
            "value": None,
            "status": "NA",
            "direction": direction,
            "numerator": rounded(numerator),
            "denominator": rounded(denominator),
            "meaningful_denominator_threshold": rounded(threshold, 6),
            "explanation": (
                "oracle-anchor denominator is too close to zero for a "
                "stable recovery ratio"
            ),
        }
    return {
        "value": rounded(numerator / denominator, 6),
        "status": "ok",
        "direction": direction,
        "numerator": rounded(numerator),
        "denominator": rounded(denominator),
        "meaningful_denominator_threshold": rounded(threshold, 6),
        "clamped": False,
    }


def arm_summary(records):
    metrics = {
        metric: describe(record.get(metric) for record in records)
        for metric in METRICS
    }
    timings = [timing_for_run(record) for record in records]
    timing_summary = {
        field: describe(item.get(field) for item in timings)
        for field in (
            "marker_delivery_latency_ms",
            "external_detect_vs_internal_ms",
            "external_action_vs_internal_ms",
            "oracle_action_vs_internal_ms",
            "affinity_cost_us",
        )
    }
    starts = [
        numeric(record.get("temp_start_c")) for record in records
        if numeric(record.get("temp_start_c")) is not None
    ]
    ends = [
        numeric(record.get("temp_end_c")) for record in records
        if numeric(record.get("temp_end_c")) is not None
    ]
    return {
        "n": len(records),
        "metrics": metrics,
        "temperature_range": {
            "start_min_c": min(starts) if starts else None,
            "start_max_c": max(starts) if starts else None,
            "end_min_c": min(ends) if ends else None,
            "end_max_c": max(ends) if ends else None,
        },
        "phase_action_timing": timing_summary,
        "switch_attempts": sum(bool(record.get("switch_attempted"))
                               for record in records),
        "switch_successes": sum(bool(record.get("switch_success"))
                                for record in records),
        "external_detections": sum(bool(record.get("external_detected"))
                                   for record in records),
        "missing_internal_boundaries": sum(
            record.get("t_internal_phase_ns") is None for record in records
        ),
        "runs": records,
    }


def mean(summary, arm, metric):
    desc = summary.get(arm, {}).get("metrics", {}).get(metric)
    return desc.get("mean") if desc else None


def external_oracle_gap(by_arm):
    output = {}
    for metric in ("ttft_ms", "itl_p95_ms", "decode_tps"):
        external = mean(by_arm, "EXTERNAL", metric)
        oracle = mean(by_arm, "ORACLE", metric)
        if external is None or oracle is None:
            output[metric] = None
            continue
        output[metric] = {
            "external_mean": external,
            "oracle_mean": oracle,
            "external_minus_oracle": rounded(external - oracle),
            "external_vs_oracle_pct": (
                rounded((external - oracle) / oracle * 100.0)
                if oracle != 0 else None
            ),
        }
    return output


def recovery_metrics(by_arm):
    return {
        "ttft_recovery": recovery(
            mean(by_arm, "STATIC_P", "ttft_ms"),
            mean(by_arm, "EXTERNAL", "ttft_ms"),
            mean(by_arm, "ORACLE", "ttft_ms"),
            higher_is_better=False,
        ),
        "itl_p95_recovery": recovery(
            mean(by_arm, "STATIC_PE", "itl_p95_ms"),
            mean(by_arm, "EXTERNAL", "itl_p95_ms"),
            mean(by_arm, "ORACLE", "itl_p95_ms"),
            higher_is_better=False,
        ),
        "throughput_recovery": recovery(
            mean(by_arm, "STATIC_PE", "decode_tps"),
            mean(by_arm, "EXTERNAL", "decode_tps"),
            mean(by_arm, "ORACLE", "decode_tps"),
            higher_is_better=True,
        ),
    }


def stock_comparisons(by_arm):
    output = {}
    for comparator in ("STATIC_P", "STATIC_PE", "EXTERNAL", "ORACLE"):
        metrics = {}
        for metric in ("ttft_ms", "itl_p95_ms", "decode_tps"):
            stock = mean(by_arm, "STOCK", metric)
            other = mean(by_arm, comparator, metric)
            metrics[metric] = (
                {
                    "stock_mean": stock,
                    "comparator_mean": other,
                    "stock_minus_comparator": rounded(stock - other),
                    "stock_vs_comparator_pct": (
                        rounded((stock - other) / other * 100.0)
                        if other not in (None, 0) else None
                    ),
                }
                if stock is not None and other is not None else None
            )
        output[f"STOCK_vs_{comparator}"] = metrics
    return output


def load_build_hashes(records, input_root):
    hashes = set()
    missing = []
    for record in records:
        env_rel = record.get("environment_file")
        if not env_rel:
            missing.append(record.get("arm"))
            continue
        try:
            env = read_json(input_root / env_rel)
            value = env["llama_cpp"]["diagnostic_server_binary"]["sha256"]
        except (OSError, KeyError, json.JSONDecodeError):
            missing.append(env_rel)
            continue
        hashes.add(value)
    return sorted(hashes), missing


def validate_rounds(records, warnings):
    rounds = defaultdict(list)
    for record in records:
        rounds[record.get("round")].append(record)
    orders = []
    for round_number, members in sorted(rounds.items()):
        ordered = sorted(members, key=lambda item: item.get("sequence_index", 0))
        arm_counts = Counter(member.get("arm") for member in ordered)
        complete = set(arm_counts) == set(ARMS) and all(
            arm_counts[arm] == 1 for arm in ARMS
        )
        if not complete:
            warnings.append(
                f"round {round_number} does not contain every arm exactly once"
            )
        orders.append({
            "round": round_number,
            "complete": complete,
            "order": [member.get("arm") for member in ordered],
            "randomized_order_seeds": sorted({
                member.get("randomized_order_seed") for member in ordered
            }),
        })
    return orders


def markdown(summary):
    lines = [
        "# TASK-C02 observation summary",
        "",
        "This report compares the composite stock Linux scheduling stack, "
        "static endpoints, an external /proc-triggered policy, and an "
        "internal-marker oracle. It does not causally isolate Thread "
        "Director/HFI and does not automatically declare C02 PASS/FAIL.",
        "",
        "All arms are expected to use the same diagnostic build and the same "
        "live marker-acquisition path. The diagnostic marker establishes "
        "oracle ground truth; only ORACLE routes it to the actuator, and "
        "EXTERNAL does not consume application phase information for "
        "decisions.",
        "",
        "## Per-arm performance",
        "",
        "| arm | n | TTFT mean / median / CV | ITL p50 mean / median | "
        "ITL p95 mean / median / CV | ITL p99 mean | decode tps mean |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for arm in ARMS:
        item = summary["arms"].get(arm, {})
        metrics = item.get("metrics", {})
        ttft = metrics.get("ttft_ms") or {}
        p50 = metrics.get("itl_p50_ms") or {}
        p95 = metrics.get("itl_p95_ms") or {}
        p99 = metrics.get("itl_p99_ms") or {}
        tps = metrics.get("decode_tps") or {}
        lines.append(
            f"| {arm} | {item.get('n', 0)} | "
            f"{ttft.get('mean')} / {ttft.get('median')} / {ttft.get('cv_pct')}% | "
            f"{p50.get('mean')} / {p50.get('median')} | "
            f"{p95.get('mean')} / {p95.get('median')} / {p95.get('cv_pct')}% | "
            f"{p99.get('mean')} | {tps.get('mean')} |"
        )

    lines += [
        "",
        "## Thermal ranges",
        "",
        "| arm | start range C | end range C |",
        "|---|---:|---:|",
    ]
    for arm in ARMS:
        temp = summary["arms"].get(arm, {}).get("temperature_range", {})
        lines.append(
            f"| {arm} | {temp.get('start_min_c')}–{temp.get('start_max_c')} | "
            f"{temp.get('end_min_c')}–{temp.get('end_max_c')} |"
        )

    lines += [
        "",
        "## Phase and action timing",
        "",
        "All offsets use the internal PHASE_MARK boundary as zero; first-token "
        "arrival is not used as phase ground truth.",
        "",
        "| arm | marker delivery mean ms | external detect vs internal mean "
        "ms | action vs internal mean ms | affinity cost mean us | switches "
        "successful / attempted |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for arm in ARMS:
        item = summary["arms"].get(arm, {})
        timing = item.get("phase_action_timing", {})
        marker_delivery = timing.get("marker_delivery_latency_ms") or {}
        detect = timing.get("external_detect_vs_internal_ms") or {}
        action_key = (
            "external_action_vs_internal_ms" if arm == "EXTERNAL"
            else "oracle_action_vs_internal_ms"
        )
        action = timing.get(action_key) or {}
        cost = timing.get("affinity_cost_us") or {}
        lines.append(
            f"| {arm} | {marker_delivery.get('mean')} | "
            f"{detect.get('mean')} | {action.get('mean')} | "
            f"{cost.get('mean')} | {item.get('switch_successes', 0)} / "
            f"{item.get('switch_attempts', 0)} |"
        )

    lines += [
        "",
        "## EXTERNAL vs ORACLE",
        "",
        "| metric | external mean | oracle mean | absolute gap | relative gap |",
        "|---|---:|---:|---:|---:|",
    ]
    for metric, gap in summary["external_vs_oracle"].items():
        gap = gap or {}
        lines.append(
            f"| {metric} | {gap.get('external_mean')} | "
            f"{gap.get('oracle_mean')} | {gap.get('external_minus_oracle')} | "
            f"{gap.get('external_vs_oracle_pct')}% |"
        )

    lines += ["", "## Oracle recovery", ""]
    for name, value in summary["oracle_recovery"].items():
        if value.get("status") == "ok":
            lines.append(f"- {name}: {value['value']} (not clamped)")
        else:
            lines.append(f"- {name}: NA — {value['explanation']}")

    lines += [
        "",
        "## Contemporaneous STOCK comparisons",
        "",
        "Positive latency gaps mean STOCK is slower; positive throughput "
        "gaps mean STOCK has higher throughput. These compare the stock Linux "
        "scheduling stack and do not attribute causality to hardware guidance.",
        "",
        "| comparison | TTFT gap / % | ITL p95 gap / % | decode tps gap / % |",
        "|---|---:|---:|---:|",
    ]
    for name, metrics in summary["stock_comparisons"].items():
        cells = []
        for metric in ("ttft_ms", "itl_p95_ms", "decode_tps"):
            value = metrics.get(metric) or {}
            cells.append(
                f"{value.get('stock_minus_comparator')} / "
                f"{value.get('stock_vs_comparator_pct')}%"
            )
        lines.append(f"| {name} | " + " | ".join(cells) + " |")

    lines += [
        "",
        "## Smoke decision support",
        "",
        f"- Diagnostic build hashes observed: "
        f"{summary['protocol']['diagnostic_build_hashes']}",
        f"- Same diagnostic build across arms: "
        f"{summary['protocol']['same_diagnostic_build']}",
        f"- Equivalent /proc monitoring recorded in every run: "
        f"{summary['protocol']['monitor_overhead_equalized']}",
        f"- Equivalent live marker watcher recorded in every run: "
        f"{summary['protocol']['marker_watcher_equalized']}",
        f"- EXTERNAL switches: "
        f"{summary['arms'].get('EXTERNAL', {}).get('switch_successes', 0)} / "
        f"{summary['arms'].get('EXTERNAL', {}).get('n', 0)}",
        f"- ORACLE switches: "
        f"{summary['arms'].get('ORACLE', {}).get('switch_successes', 0)} / "
        f"{summary['arms'].get('ORACLE', {}).get('n', 0)}",
        "- Review TTFT and decode-tail rows above to assess whether STOCK "
        "retains C01's low-TTFT/worse-decode pattern.",
        "- Review timing and thermal tables before authorizing six rounds.",
    ]

    if summary["warnings"]:
        lines += ["", "## Warnings", ""]
        lines.extend(f"- {warning}" for warning in summary["warnings"])
    lines.append("")
    return "\n".join(lines)


def analyze(input_dir, output_dir=None):
    input_root = Path(input_dir).resolve()
    output_root = Path(output_dir or input_dir).resolve()
    paths = sorted((input_root / "raw" / "runs").glob("round_*.json"))
    records = []
    warnings = []
    for path in paths:
        try:
            record = read_json(path)
        except (OSError, json.JSONDecodeError) as exc:
            warnings.append(f"skipped {path.name}: {exc}")
            continue
        if record.get("status") != "ok" or record.get("arm") not in ARMS:
            warnings.append(f"skipped invalid successful-run record {path.name}")
            continue
        records.append(record)

    grouped = defaultdict(list)
    for record in records:
        grouped[record["arm"]].append(record)
        expected = EXPECTED_PHASE_SOURCE[record["arm"]]
        if record.get("phase_source") != expected:
            warnings.append(
                f"{record['arm']} has phase_source={record.get('phase_source')}; "
                f"expected {expected}"
            )
        expected_marker_use = (
            "live_trigger" if record["arm"] == "ORACLE"
            else "live_record_only"
        )
        if record.get("diagnostic_marker_consumption") != expected_marker_use:
            warnings.append(
                f"{record['arm']} has invalid diagnostic marker routing"
            )
        expected_marker_route = record["arm"] == "ORACLE"
        if record.get("marker_routed_to_actuator") is not expected_marker_route:
            warnings.append(
                f"{record['arm']} has invalid marker-to-actuator route"
            )
        if record["arm"] in ("STOCK", "STATIC_P", "STATIC_PE") and (
            record.get("switch_attempted")
        ):
            warnings.append(f"{record['arm']} attempted an affinity action")

    by_arm = {arm: arm_summary(grouped.get(arm, [])) for arm in ARMS}
    for arm in ARMS:
        if not grouped.get(arm):
            warnings.append(f"no successful {arm} runs found")

    orders = validate_rounds(records, warnings)
    build_hashes, missing_hashes = load_build_hashes(records, input_root)
    if missing_hashes:
        warnings.append(f"missing diagnostic build identity: {missing_hashes}")
    same_build = len(build_hashes) == 1 and not missing_hashes and bool(records)
    if records and not same_build:
        warnings.append("runs do not prove one diagnostic build across all arms")

    phase_sources = sorted({
        (record.get("arm"), record.get("phase_source")) for record in records
    })
    monitor_equalized = bool(records) and all(
        record.get("monitor_overhead_equalized") is True for record in records
    )
    if records and not monitor_equalized:
        warnings.append("not every run records equivalent /proc monitoring")
    marker_watcher_equalized = bool(records) and all(
        record.get("live_marker_watcher") is True for record in records
    )
    if records and not marker_watcher_equalized:
        warnings.append(
            "not every run records the common live PHASE_MARK watcher"
        )

    failure_paths = sorted(
        (input_root / "raw" / "runs" / "failures").glob("*.json")
    )
    summary = {
        "schema_version": 1,
        "task": "TASK-C02",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "interpretation_policy": (
            "descriptive C02 comparison only; stock Linux wording is "
            "composite and Thread Director/HFI causal attribution is excluded"
        ),
        "protocol": {
            "successful_run_count": len(records),
            "round_count_observed": len(orders),
            "arm_counts": {arm: len(grouped.get(arm, [])) for arm in ARMS},
            "round_orders": orders,
            "phase_sources": [
                {"arm": arm, "phase_source": source}
                for arm, source in phase_sources
            ],
            "diagnostic_build_hashes": build_hashes,
            "same_diagnostic_build": same_build,
            "monitor_overhead_equalized": monitor_equalized,
            "marker_watcher_equalized": marker_watcher_equalized,
            "failed_attempt_count": len(failure_paths),
            "failure_artifacts": [
                str(path.relative_to(input_root)) for path in failure_paths
            ],
        },
        "arms": by_arm,
        "external_vs_oracle": external_oracle_gap(by_arm),
        "oracle_recovery": recovery_metrics(by_arm),
        "stock_comparisons": stock_comparisons(by_arm),
        "warnings": warnings,
    }
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_root / "summary.md").write_text(
        markdown(summary), encoding="utf-8"
    )
    return summary


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Analyze TASK-C02 raw runs without declaring PASS/FAIL",
    )
    parser.add_argument(
        "--input", default=str(ROOT / "results" / "conference_c02"),
        help="C02 artifact root containing raw/runs",
    )
    parser.add_argument(
        "--outdir", default="",
        help="derived output directory; defaults to --input",
    )
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
        "successful_runs": summary["protocol"]["successful_run_count"],
        "arm_counts": summary["protocol"]["arm_counts"],
        "summary_json": str(Path(args.outdir) / "summary.json"),
        "summary_md": str(Path(args.outdir) / "summary.md"),
        "warnings": summary["warnings"],
    }, indent=2))


if __name__ == "__main__":
    main()
