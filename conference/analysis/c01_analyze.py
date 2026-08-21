#!/usr/bin/env python3
"""Derive observation-only TASK-C01 summaries from preserved raw artifacts.

The diagnostic phase marker labels already-recorded samples as prefill/decode.
It is never consumed by the experiment runner while the request is executing.
This analyzer reports the composite observed behavior of stock Linux scheduling
and whatever hardware guidance the platform exposes.  It deliberately does not
classify that behavior as successful/failed and cannot causally isolate Intel
Thread Director/HFI without a separate hardware-guidance ablation.
"""

import argparse
import csv
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT / "harness"
sys.path.insert(0, str(HARNESS))

import bench_lib as bl  # noqa: E402


METRIC_FIELDS = (
    "ttft_ms", "itl_p50_ms", "itl_p95_ms", "itl_p99_ms", "decode_tps",
    "migrations", "ctx_switches", "temp_start_c", "temp_end_c",
    "freq_p_avg_mhz", "freq_p_busy_mhz", "freq_e_avg_mhz",
)
SMOKE_RUNS = 2
FULL_PILOT_RUNS = 6


def read_json(path):
    with Path(path).open(encoding="utf-8") as f:
        return json.load(f)


def round_or_none(value, digits=3):
    return round(value, digits) if value is not None else None


def numeric(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def describe(values):
    values = [float(v) for v in values if v is not None]
    if not values:
        return None
    out = bl.describe(values)
    return {key: round_or_none(value) for key, value in out.items()}


def topology_maps(trace, input_root):
    """Return cpu -> class and cpu -> physical core from trace environment."""
    env_rel = trace.get("environment_file")
    if not env_rel:
        raise ValueError("trace has no environment_file")
    env = read_json(Path(input_root) / env_rel)
    cpus = env.get("topology", {}).get("cpus", {})
    classes = {}
    cores = {}
    for cpu_text, item in cpus.items():
        cpu = int(cpu_text)
        classes[cpu] = item.get("core_class", "unknown")
        cores[cpu] = item.get("core_id")
    if not classes:
        raise ValueError(f"environment {env_rel} has no CPU topology")
    return classes, cores


def transition_kind(previous, current, classes, cores):
    if previous == current:
        return None
    p_class = classes.get(previous, "unknown")
    c_class = classes.get(current, "unknown")
    if p_class == "P" and c_class == "E":
        return "p_to_e"
    if p_class == "E" and c_class == "P":
        return "e_to_p"
    if cores.get(previous) is not None and cores.get(previous) == cores.get(current):
        return "same_core_sibling"
    if p_class == "P" and c_class == "P":
        return "p_to_p"
    if p_class == "E" and c_class == "E":
        return "e_to_e"
    return "unknown"


def phase_summary(samples, classes, cores):
    per_thread = defaultdict(lambda: {
        "active_samples": 0,
        "p_samples": 0,
        "e_samples": 0,
        "unknown_samples": 0,
        "cpu_samples": Counter(),
        "transitions": Counter(),
    })
    active_counts = []
    transitions = Counter()

    for sample in samples:
        active = sample["active_tasks"]
        active_counts.append(len(active))
        for task in active:
            tid = task["tid"]
            cpu = task["cpu"]
            item = per_thread[tid]
            item["active_samples"] += 1
            item["cpu_samples"][cpu] += 1
            core_class = classes.get(cpu, "unknown")
            if core_class == "P":
                item["p_samples"] += 1
            elif core_class == "E":
                item["e_samples"] += 1
            else:
                item["unknown_samples"] += 1

            previous = task.get("previous_active_cpu")
            kind = transition_kind(previous, cpu, classes, cores) \
                if previous is not None else None
            if kind:
                transitions["total_migrations"] += 1
                transitions[kind] += 1
                item["transitions"]["total_migrations"] += 1
                item["transitions"][kind] += 1

    p_samples = sum(item["p_samples"] for item in per_thread.values())
    e_samples = sum(item["e_samples"] for item in per_thread.values())
    unknown_samples = sum(
        item["unknown_samples"] for item in per_thread.values()
    )
    denominator = p_samples + e_samples + unknown_samples
    transition_fields = (
        "total_migrations", "p_to_e", "e_to_p", "p_to_p", "e_to_e",
        "same_core_sibling", "unknown",
    )
    thread_output = {}
    for tid, item in sorted(per_thread.items()):
        total = item["active_samples"]
        thread_output[str(tid)] = {
            "active_samples": total,
            "p_samples": item["p_samples"],
            "e_samples": item["e_samples"],
            "unknown_samples": item["unknown_samples"],
            "p_residency_pct": round_or_none(
                item["p_samples"] / total * 100 if total else None
            ),
            "e_residency_pct": round_or_none(
                item["e_samples"] / total * 100 if total else None
            ),
            "cpu_samples": {
                str(cpu): count for cpu, count in sorted(item["cpu_samples"].items())
            },
            "sampled_transitions_lower_bound": {
                field: item["transitions"].get(field, 0)
                for field in transition_fields
            },
        }

    active_desc = describe(active_counts)
    return {
        "sample_count": len(samples),
        "samples_with_active_threads": sum(1 for x in active_counts if x > 0),
        "active_thread_count": active_desc,
        "unique_active_threads": len(per_thread),
        "active_thread_observations": denominator,
        "p_thread_observations": p_samples,
        "e_thread_observations": e_samples,
        "unknown_thread_observations": unknown_samples,
        "p_residency_pct": round_or_none(
            p_samples / denominator * 100 if denominator else None
        ),
        "e_residency_pct": round_or_none(
            e_samples / denominator * 100 if denominator else None
        ),
        "unknown_residency_pct": round_or_none(
            unknown_samples / denominator * 100 if denominator else None
        ),
        "sampled_transitions_lower_bound": {
            field: transitions.get(field, 0) for field in transition_fields
        },
        "per_thread": thread_output,
    }


def label_samples_offline(trace):
    request = trace.get("request", {})
    labeling = trace.get("phase_labeling", {})
    t_sent = request.get("t_sent_ns")
    t_last = request.get("t_last_token_ns")
    # Recompute the boundary from the preserved raw marker stream here.  The
    # runner records markers only after the request; this is the first point at
    # which they influence phase labels.
    boundary = next(
        (
            marker.get("t_mono_ns")
            for marker in labeling.get("phase_markers", [])
            if marker.get("batched") == 0
            and t_sent is not None
            and marker.get("t_mono_ns", -1) >= t_sent
        ),
        None,
    )
    if None in (t_sent, boundary, t_last):
        raise ValueError("trace is missing request or internal phase timestamps")
    if not (t_sent <= boundary <= t_last):
        raise ValueError(
            f"invalid phase order: sent={t_sent}, boundary={boundary}, last={t_last}"
        )

    previous_ticks = {}
    previous_active_cpu = {}
    labeled = {"prefill": [], "decode": []}
    for sample in sorted(trace.get("samples", []), key=lambda x: x["t_mono_ns"]):
        timestamp = sample["t_mono_ns"]
        tasks = sample.get("tasks", [])
        active = []
        for task in tasks:
            tid = int(task["tid"])
            ticks = int(task["cpu_ticks"])
            # Runnable now, or consumed CPU since the preceding sample.
            is_active = task.get("state") == "R" or (
                tid in previous_ticks and ticks > previous_ticks[tid]
            )
            previous_ticks[tid] = ticks
            if is_active:
                active.append({
                    "tid": tid,
                    "cpu": int(task["cpu"]),
                    "state": task.get("state"),
                    "cpu_ticks": ticks,
                    # Keep the last active observation across the phase
                    # boundary.  A move first observed in decode is therefore
                    # attributed to decode instead of disappearing between two
                    # independently summarized windows.
                    "previous_active_cpu": previous_active_cpu.get(tid),
                })
                previous_active_cpu[tid] = int(task["cpu"])
        if t_sent <= timestamp < boundary:
            labeled["prefill"].append({
                "t_mono_ns": timestamp, "active_tasks": active,
            })
        elif boundary <= timestamp <= t_last:
            labeled["decode"].append({
                "t_mono_ns": timestamp, "active_tasks": active,
            })
    return labeled


def summarize_trace(path, input_root):
    trace = read_json(path)
    if trace.get("arm") != "S0_STOCK_UNPINNED":
        raise ValueError(f"unexpected arm {trace.get('arm')!r}")
    classes, cores = topology_maps(trace, input_root)
    labeled = label_samples_offline(trace)
    prefill = phase_summary(labeled["prefill"], classes, cores)
    decode = phase_summary(labeled["decode"], classes, cores)
    return {
        "raw_trace": str(Path(path).relative_to(input_root)),
        "run": trace.get("run"),
        "interval_ms": trace.get("config", {}).get("interval_ms"),
        "threads": trace.get("config", {}).get("threads"),
        "threads_batch": trace.get("config", {}).get("threads_batch"),
        "prefill": prefill,
        "decode": decode,
        "sampler": trace.get("sampler", {}),
        "whole_request_counters": trace.get("whole_request_counters", {}),
        "temperature": trace.get("temperature", {}),
        "frequency": trace.get("frequency", {}),
    }


def mean_field(run_summaries, path):
    values = []
    for run in run_summaries:
        value = run
        for key in path:
            value = value.get(key) if isinstance(value, dict) else None
        if value is not None:
            values.append(value)
    return sum(values) / len(values) if values else None


def aggregate_characterization(run_summaries):
    groups = defaultdict(list)
    for run in run_summaries:
        groups[run["interval_ms"]].append(run)

    output = {}
    for interval, runs in sorted(groups.items(), key=lambda item: item[0]):
        metrics = {}
        paths = {
            "prefill_p_residency_pct": ("prefill", "p_residency_pct"),
            "prefill_e_residency_pct": ("prefill", "e_residency_pct"),
            "decode_p_residency_pct": ("decode", "p_residency_pct"),
            "decode_e_residency_pct": ("decode", "e_residency_pct"),
            "prefill_active_threads_mean": (
                "prefill", "active_thread_count", "mean"
            ),
            "decode_active_threads_mean": (
                "decode", "active_thread_count", "mean"
            ),
            "prefill_sampled_migrations_lower_bound": (
                "prefill", "sampled_transitions_lower_bound", "total_migrations"
            ),
            "decode_sampled_migrations_lower_bound": (
                "decode", "sampled_transitions_lower_bound", "total_migrations"
            ),
            "prefill_p_to_e_lower_bound": (
                "prefill", "sampled_transitions_lower_bound", "p_to_e"
            ),
            "prefill_e_to_p_lower_bound": (
                "prefill", "sampled_transitions_lower_bound", "e_to_p"
            ),
            "decode_p_to_e_lower_bound": (
                "decode", "sampled_transitions_lower_bound", "p_to_e"
            ),
            "decode_e_to_p_lower_bound": (
                "decode", "sampled_transitions_lower_bound", "e_to_p"
            ),
            "sampler_read_cost_us_p95": ("sampler", "read_cost_us_p95"),
        }
        for name, path in paths.items():
            values = []
            for run in runs:
                value = run
                for key in path:
                    value = value.get(key) if isinstance(value, dict) else None
                if value is not None:
                    values.append(value)
            metrics[name] = describe(values)

        output[f"{interval:g}"] = {
            "interval_ms": interval,
            "run_count": len(runs),
            "prefill_p_residency_pct": round_or_none(
                mean_field(runs, ("prefill", "p_residency_pct"))
            ),
            "prefill_e_residency_pct": round_or_none(
                mean_field(runs, ("prefill", "e_residency_pct"))
            ),
            "decode_p_residency_pct": round_or_none(
                mean_field(runs, ("decode", "p_residency_pct"))
            ),
            "decode_e_residency_pct": round_or_none(
                mean_field(runs, ("decode", "e_residency_pct"))
            ),
            "run_metric_distributions": metrics,
            "runs": runs,
        }
    return output


def summarize_performance(paths, input_root):
    records = []
    for path in paths:
        record = read_json(path)
        if record.get("arm") != "S0_STOCK_UNPINNED":
            continue
        record = dict(record)
        record["raw_result"] = str(Path(path).relative_to(input_root))
        records.append(record)
    metrics = {
        name: describe([numeric(row.get(name)) for row in records])
        for name in METRIC_FIELDS
    }
    return {
        "run_count": len(records),
        "stock_ttft_ms": metrics["ttft_ms"],
        "stock_itl_p95_ms": metrics["itl_p95_ms"],
        "metrics": metrics,
        "runs": records,
    }


def load_reference(spec):
    if "=" not in spec:
        raise ValueError("reference must be NAME=PATH")
    name, path_and_filters = spec.split("=", 1)
    if "::" in path_and_filters:
        raw_path, filter_text = path_and_filters.split("::", 1)
        filters = {}
        for item in filter_text.split(","):
            if "=" not in item:
                raise ValueError(f"invalid reference filter {item!r}")
            key, value = item.split("=", 1)
            filters[key] = value
    else:
        raw_path = path_and_filters
        filters = {}
    path = Path(raw_path)
    if path.suffix.lower() == ".csv":
        with path.open(newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    else:
        value = read_json(path)
        if isinstance(value, list):
            rows = value
        elif isinstance(value, dict) and isinstance(value.get("runs"), list):
            rows = value["runs"]
        elif isinstance(value, dict):
            rows = [value]
        else:
            raise ValueError(f"unsupported reference structure: {path}")
    if filters:
        rows = [
            row for row in rows
            if all(str(row.get(key)) == value for key, value in filters.items())
        ]
    if not rows:
        raise ValueError(f"reference {name!r} selected no rows from {path}")
    metrics = {}
    for field in METRIC_FIELDS:
        desc = describe([numeric(row.get(field)) for row in rows])
        if desc:
            metrics[field] = desc
    return name, {
        "provenance": str(path),
        "filters": filters,
        "row_count": len(rows),
        "metrics": metrics,
    }


def markdown(summary):
    lines = [
        "# TASK-C01 observation summary",
        "",
        "This report contains observations only: the composite stock Linux "
        "scheduling behavior, including whatever hardware guidance the current "
        "platform exposes. It does not decide whether that composite behavior "
        "solves or fails the placement problem.",
        "",
        "The experiment does not causally isolate Intel Thread Director/HFI. "
        "A separate hardware-guidance ablation is required for causal "
        "attribution.",
        "",
        f"Sensitivity smoke complete: {summary['protocol']['smoke_complete']}",
        "",
        "## Phase-specific stock residency",
        "",
        "| interval | runs | prefill P | prefill E | decode P | decode E |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for group in summary["characterization_by_interval_ms"].values():
        lines.append(
            f"| {group['interval_ms']:g} ms | {group['run_count']} | "
            f"{group['prefill_p_residency_pct']}% | "
            f"{group['prefill_e_residency_pct']}% | "
            f"{group['decode_p_residency_pct']}% | "
            f"{group['decode_e_residency_pct']}% |"
        )

    lines += [
        "",
        "Residency percentages use active thread-observations. A thread is "
        "active when its CPU-time counter advanced since the preceding sample "
        "or it was runnable at the sample. Sampled migrations are lower bounds.",
        "",
        "## Phase-specific sampled transitions",
        "",
        "| interval | phase | migrations (mean/run) | P→E | E→P | "
        "active threads (mean) | sampler p95 cost |",
        "|---:|---|---:|---:|---:|---:|---:|",
    ]
    for group in summary["characterization_by_interval_ms"].values():
        dists = group["run_metric_distributions"]
        for phase in ("prefill", "decode"):
            migration = dists[f"{phase}_sampled_migrations_lower_bound"]
            p_to_e = dists[f"{phase}_p_to_e_lower_bound"]
            e_to_p = dists[f"{phase}_e_to_p_lower_bound"]
            active = dists[f"{phase}_active_threads_mean"]
            cost = dists["sampler_read_cost_us_p95"]
            lines.append(
                f"| {group['interval_ms']:g} ms | {phase} | "
                f"{migration['mean'] if migration else None} | "
                f"{p_to_e['mean'] if p_to_e else None} | "
                f"{e_to_p['mean'] if e_to_p else None} | "
                f"{active['mean'] if active else None} | "
                f"{cost['mean'] if cost else None} us |"
            )

    perf = summary["performance"]
    lines += [
        "",
        "## Low-overhead stock performance",
        "",
        f"Runs: {perf['run_count']}",
        "",
        "| metric | mean | median | min | max |",
        "|---|---:|---:|---:|---:|",
    ]
    for metric in ("ttft_ms", "itl_p50_ms", "itl_p95_ms", "itl_p99_ms",
                   "decode_tps", "migrations", "ctx_switches"):
        desc = perf["metrics"].get(metric)
        lines.append(
            f"| {metric} | {desc['mean'] if desc else None} | "
            f"{desc['median'] if desc else None} | "
            f"{desc['min'] if desc else None} | "
            f"{desc['max'] if desc else None} |"
        )

    if summary["references"]:
        lines += [
            "", "## Supplied historical references", "",
            "| reference | rows | TTFT mean | ITL p95 mean | decode tps mean |",
            "|---|---:|---:|---:|---:|",
        ]
        for name, value in summary["references"].items():
            metrics = value["metrics"]
            lines.append(
                f"| {name} | {value['row_count']} | "
                f"{metrics.get('ttft_ms', {}).get('mean')} | "
                f"{metrics.get('itl_p95_ms', {}).get('mean')} | "
                f"{metrics.get('decode_tps', {}).get('mean')} |"
            )
            lines.append(
                f"<!-- provenance: {value['provenance']}; "
                f"filters: {value['filters']} -->"
            )

    if summary["warnings"]:
        lines += ["", "## Warnings", ""]
        lines.extend(f"- {warning}" for warning in summary["warnings"])

    if summary["representative_raw_trace"]:
        lines += [
            "",
            "Representative raw trace: " + summary["representative_raw_trace"],
        ]
    lines.append("")
    return "\n".join(lines)


def analyze(input_dir, output_dir, reference_specs=()):
    input_root = Path(input_dir).resolve()
    output_root = Path(output_dir).resolve()
    traces = sorted(
        input_root.glob("raw/characterization/interval_*ms/traces/trace_run_*.json")
    )
    performance_paths = sorted(
        input_root.glob("raw/performance/perf_run_*.json")
    )
    warnings = []
    run_summaries = []
    for path in traces:
        try:
            run_summaries.append(summarize_trace(path, input_root))
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            warnings.append(f"skipped {path.relative_to(input_root)}: {exc}")

    references = {}
    for spec in reference_specs:
        name, value = load_reference(spec)
        references[name] = value

    characterization = aggregate_characterization(run_summaries)
    performance = summarize_performance(performance_paths, input_root)
    if not run_summaries:
        warnings.append("no valid characterization traces found")
    if not performance_paths:
        warnings.append("no low-overhead performance runs found")

    required_intervals = ("20", "50")
    for interval in required_intervals:
        group = characterization.get(interval)
        count = group["run_count"] if group else 0
        if count < SMOKE_RUNS:
            warnings.append(
                f"{interval} ms characterization has {count}/{SMOKE_RUNS} "
                "sensitivity-smoke runs"
            )
        elif count not in (SMOKE_RUNS, FULL_PILOT_RUNS):
            warnings.append(
                f"{interval} ms characterization has non-protocol run count "
                f"{count}; expected {SMOKE_RUNS} or {FULL_PILOT_RUNS}"
            )
    if performance["run_count"] < SMOKE_RUNS:
        warnings.append(
            f"performance path has {performance['run_count']}/{SMOKE_RUNS} "
            "sensitivity-smoke runs"
        )
    elif performance["run_count"] not in (SMOKE_RUNS, FULL_PILOT_RUNS):
        warnings.append(
            "performance path has non-protocol run count "
            f"{performance['run_count']}; expected {SMOKE_RUNS} or "
            f"{FULL_PILOT_RUNS}"
        )

    protocol = {
        "frozen_threads": 8,
        "frozen_threads_batch": 16,
        "smoke_target_per_path": SMOKE_RUNS,
        "full_pilot_target_per_selected_path": FULL_PILOT_RUNS,
        "full_pilot_requires_checkpoint_review": True,
        "characterization_20ms_runs": (
            characterization.get("20", {}).get("run_count", 0)
        ),
        "characterization_50ms_runs": (
            characterization.get("50", {}).get("run_count", 0)
        ),
        "performance_runs": performance["run_count"],
    }
    observed_configs = sorted({
        (run.get("threads"), run.get("threads_batch"))
        for run in run_summaries + performance["runs"]
    }, key=lambda item: (str(item[0]), str(item[1])))
    protocol["observed_thread_configurations"] = [
        {"threads": threads, "threads_batch": threads_batch}
        for threads, threads_batch in observed_configs
    ]
    protocol["frozen_configuration_match"] = bool(observed_configs) and all(
        threads == 8 and threads_batch == 16
        for threads, threads_batch in observed_configs
    )
    if observed_configs and not protocol["frozen_configuration_match"]:
        warnings.append(
            "one or more runs do not match frozen C01 threads=8, "
            "threads_batch=16"
        )
    protocol["smoke_complete"] = all(
        protocol[key] >= SMOKE_RUNS
        for key in (
            "characterization_20ms_runs",
            "characterization_50ms_runs",
            "performance_runs",
        )
    )

    summary = {
        "schema_version": 1,
        "task": "TASK-C01",
        "generated_at": __import__("time").strftime(
            "%Y-%m-%dT%H:%M:%SZ", __import__("time").gmtime()
        ),
        "interpretation_policy": (
            "observation-only composite stock Linux scheduling behavior; "
            "Thread Director/HFI causal attribution requires a separate ablation; "
            "research interpretation occurs after checkpoint"
        ),
        "protocol": protocol,
        "characterization_by_interval_ms": characterization,
        "performance": performance,
        "references": references,
        "representative_raw_trace": (
            run_summaries[0]["raw_trace"] if run_summaries else None
        ),
        "warnings": warnings,
    }
    output_root.mkdir(parents=True, exist_ok=True)
    summary_path = output_root / "summary.json"
    markdown_path = output_root / "summary.md"
    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, sort_keys=True)
        f.write("\n")
    markdown_path.write_text(markdown(summary), encoding="utf-8")
    return summary


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Analyze TASK-C01 raw traces without research interpretation",
    )
    parser.add_argument(
        "--input", default=str(ROOT / "results" / "conference_c01"),
        help="C01 artifact root containing raw/",
    )
    parser.add_argument(
        "--outdir", default="",
        help="derived output directory; default is the input root",
    )
    parser.add_argument(
        "--reference", action="append", default=[], metavar="NAME=PATH",
        help=("optional flat run-level CSV/JSON reference; filters use "
              "NAME=PATH::key=value,key=value"),
    )
    args = parser.parse_args(argv)
    if not Path(args.input).exists():
        parser.error(f"--input does not exist: {args.input}")
    args.outdir = args.outdir or args.input
    return args


def main(argv=None):
    args = parse_args(argv)
    summary = analyze(args.input, args.outdir, args.reference)
    print(json.dumps({
        "task": summary["task"],
        "characterization_intervals": list(
            summary["characterization_by_interval_ms"]
        ),
        "performance_runs": summary["performance"]["run_count"],
        "summary_json": str(Path(args.outdir) / "summary.json"),
        "summary_md": str(Path(args.outdir) / "summary.md"),
        "warnings": summary["warnings"],
    }, indent=2))


if __name__ == "__main__":
    main()
