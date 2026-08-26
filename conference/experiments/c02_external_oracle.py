#!/usr/bin/env python3
"""TASK-C02 clean external-vs-oracle phase-policy experiment.

Every arm uses one diagnostic llama-server binary, the same /proc monitor,
and the same live PHASE_MARK watcher.  EXTERNAL can trigger the shared
userspace affinity actuator only from the /proc detector.  ORACLE runs that
detector observation-only and alone routes the live marker to the same
actuator.  In all other arms the live marker is recorded only as offline
ground truth.

This runner prepares and executes only the C02 experiment.  It never changes
the system scheduler, governor, power profile, or sched_ext state.
"""

import argparse
import csv
import glob
import hashlib
import json
import os
import random
import re
import subprocess
import sys
import threading
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT / "harness"
EXPERIMENTS = Path(__file__).resolve().parent
sys.path.insert(0, str(HARNESS))
sys.path.insert(0, str(EXPERIMENTS))

import bench_lib as bl  # noqa: E402
import c01_stock_scheduler as c01  # noqa: E402
import run_once as ro  # noqa: E402
import thread_residency as tr  # noqa: E402
from phase_switch import cputime_jiffies, read_energy_uj, sched_totals  # noqa: E402


ARMS = ("STOCK", "STATIC_P", "STATIC_PE", "EXTERNAL", "ORACLE")
PHASE_SOURCES = {
    "STOCK": "none",
    "STATIC_P": "none",
    "STATIC_PE": "none",
    "EXTERNAL": "external_proc",
    "ORACLE": "internal_oracle",
}
SMOKE_ROUNDS = 2
FULL_PILOT_ROUNDS = 6
DEFAULT_ORDER_SEED = 2202
DEFAULT_INTERVAL_MS = 20.0
DEFAULT_HI = 3000.0
DEFAULT_LO = 2100.0
DEFAULT_K = 2
HZ = 100
MARK_RE = re.compile(r"PHASE_MARK batched=(\d+) t_mono_ns=(\d+)")

CSV_FIELDS = (
    "round", "sequence_index", "global_sequence_index", "arm",
    "randomized_order_seed", "timestamp", "phase_source", "threads",
    "threads_batch", "initial_cpus", "final_cpus", "ttft_ms",
    "itl_p50_ms", "itl_p95_ms", "itl_p99_ms", "decode_tps", "n_tokens",
    "total_migrations", "total_ctx_switches", "temp_start_c", "temp_end_c",
    "freq_p_avg_mhz", "freq_p_busy_mhz", "freq_e_avg_mhz", "freq_samples",
    "energy_j", "j_per_token", "external_detected", "switch_attempted",
    "switch_success", "t_request_sent_ns", "t_internal_phase_ns",
    "t_marker_seen_ns", "t_external_detect_ns", "t_trigger_ns", "trigger_source",
    "t_affinity_start_ns", "t_affinity_done_ns",
    "t_first_token_ns", "t_last_token_ns", "affinity_cost_us",
    "affinity_tids_succeeded", "affinity_tids_failed", "environment_file",
    "token_file", "server_log", "phase_log",
)


def cpu_list_text(cpus):
    return ",".join(str(cpu) for cpu in cpus)


def discover_cpu_sets():
    """Derive one logical CPU per P core plus every E CPU from topology."""
    cpu_core, core_cpus = tr.read_topology()
    p_cpus = []
    e_cpus = []
    for core_id, siblings in sorted(core_cpus.items()):
        if not siblings:
            continue
        is_pcore = bool(cpu_core[siblings[0]][1])
        if is_pcore:
            p_cpus.append(min(siblings))
        else:
            e_cpus.extend(sorted(siblings))
    p_cpus = sorted(set(p_cpus))
    e_cpus = sorted(set(e_cpus))
    if not p_cpus or not e_cpus:
        raise RuntimeError(
            "C02 requires heterogeneous P/E topology; discovered "
            f"P={p_cpus}, E={e_cpus}"
        )
    return p_cpus, e_cpus


def arm_specs(p_cpus, e_cpus):
    wide = list(p_cpus) + list(e_cpus)
    return {
        "STOCK": {
            "threads": 8, "threads_batch": 16,
            "initial_cpus": None, "final_cpus": None,
            "phase_source": "none",
        },
        "STATIC_P": {
            "threads": 8, "threads_batch": 8,
            "initial_cpus": list(p_cpus), "final_cpus": list(p_cpus),
            "phase_source": "none",
        },
        "STATIC_PE": {
            "threads": 16, "threads_batch": 16,
            "initial_cpus": wide, "final_cpus": wide,
            "phase_source": "none",
        },
        "EXTERNAL": {
            "threads": 8, "threads_batch": 16,
            "initial_cpus": wide, "final_cpus": list(p_cpus),
            "phase_source": "external_proc",
        },
        "ORACLE": {
            "threads": 8, "threads_batch": 16,
            "initial_cpus": wide, "final_cpus": list(p_cpus),
            "phase_source": "internal_oracle",
        },
    }


def build_schedule(rounds, order_seed):
    """Return independently randomized, reproducible five-arm rounds."""
    schedule = []
    global_index = 0
    for round_number in range(1, rounds + 1):
        round_seed = order_seed + round_number
        order = list(ARMS)
        random.Random(round_seed).shuffle(order)
        for sequence_index, arm in enumerate(order, 1):
            global_index += 1
            schedule.append({
                "round": round_number,
                "sequence_index": sequence_index,
                "global_sequence_index": global_index,
                "arm": arm,
                "randomized_order_seed": round_seed,
            })
    return schedule


def server_command(args, spec):
    command = []
    if spec["initial_cpus"] is not None:
        command += ["taskset", "-c", cpu_list_text(spec["initial_cpus"])]
    command += [
        args.server_bin, "-m", args.model,
        "-t", str(spec["threads"]),
        "-tb", str(spec["threads_batch"]),
        "-c", str(args.ctx), "-b", str(args.batch),
        "-ub", str(args.ubatch), "-np", "1",
        "--host", ro.HOST, "--port", str(args.port),
    ]
    return command


def _snapshot_totals(snapshot):
    return {
        "migrations": sum(value[0] for value in snapshot.values()),
        "ctx_switches": sum(value[1] for value in snapshot.values()),
        "threads": len(snapshot),
    }


class AffinityActuator:
    """The single affinity implementation used by EXTERNAL and ORACLE."""

    def __init__(self, pid, target_cpus):
        self.pid = pid
        self.target_cpus = tuple(target_cpus)
        self._lock = threading.Lock()
        self._before = None
        self.record = None

    def apply(self, trigger_ns, trigger_source):
        with self._lock:
            if self.record is not None:
                return self.record
            before = bl.sched_snapshot(self.pid)
            start_ns = bl.now_ns()
            succeeded = []
            failed = []
            for task_dir in sorted(glob.glob(f"/proc/{self.pid}/task/*")):
                try:
                    tid = int(Path(task_dir).name)
                except ValueError:
                    continue
                try:
                    os.sched_setaffinity(tid, set(self.target_cpus))
                    succeeded.append(tid)
                except OSError as exc:
                    failed.append({
                        "tid": tid,
                        "errno": exc.errno,
                        "error": str(exc),
                    })
            done_ns = bl.now_ns()
            immediate = bl.sched_snapshot(self.pid)
            self._before = before
            self.record = {
                "trigger_source": trigger_source,
                "t_trigger_ns": trigger_ns,
                "t_affinity_start_ns": start_ns,
                "t_affinity_done_ns": done_ns,
                "affinity_cost_us": (done_ns - start_ns) / 1000.0,
                "target_cpus": list(self.target_cpus),
                "tids_succeeded": succeeded,
                "tids_failed": failed,
                "n_tids_succeeded": len(succeeded),
                "n_tids_failed": len(failed),
                "counters_before": _snapshot_totals(before),
                "counters_after_immediate": _snapshot_totals(immediate),
                "counter_delta_during_calls": bl.sched_delta(before, immediate),
                "counter_delta_200ms": None,
            }
            return self.record

    def capture_200ms_delta(self):
        with self._lock:
            if self.record is None or self._before is None:
                return
            if self.record["counter_delta_200ms"] is not None:
                return
            after = bl.sched_snapshot(self.pid)
            self.record["counter_delta_200ms"] = bl.sched_delta(
                self._before, after
            )


def actuation_routes(arm, actuator):
    """Wire exactly one allowed decision source to the common actuator."""
    return {
        "external_proc": actuator.apply if arm == "EXTERNAL" else None,
        "internal_oracle": actuator.apply if arm == "ORACLE" else None,
    }


class ProcPhaseMonitor(threading.Thread):
    """Run the same /proc detector loop in every arm."""

    def __init__(self, pid, interval_s, hi, lo, k, actuator,
                 external_callback=None):
        super().__init__(daemon=True, name="c02-proc-monitor")
        self.pid = pid
        self.interval_s = interval_s
        self.hi = hi
        self.lo = lo
        self.k = k
        self.actuator = actuator
        self.external_callback = external_callback
        self.stop_flag = threading.Event()
        self.samples = []
        self.external_detect_ns = None
        self.flip_count = 0
        self._state = "prefill"
        self.decision_start_ns = None

    def arm_for_request(self):
        """Enable/reset phase decisions immediately before request send."""
        self._state = "prefill"
        self.external_detect_ns = None
        self.flip_count = 0
        self.decision_start_ns = bl.now_ns()
        return self.decision_start_ns

    def run(self):
        previous = None
        run_length = 0
        while not self.stop_flag.is_set():
            read_start = bl.now_ns()
            switches, migrations = sched_totals(self.pid)
            cpu_jiffies = cputime_jiffies(self.pid)
            timestamp = bl.now_ns()
            record = {
                "t_ns": timestamp,
                "ctx_switches": switches,
                "migrations": migrations,
                "cputime_jiffies": cpu_jiffies,
                "read_cost_ns": timestamp - read_start,
                "norm_ctx_per_cpu_s": None,
                "state": self._state,
            }
            if (
                previous is not None
                and cpu_jiffies is not None
                and previous["cputime_jiffies"] is not None
            ):
                cpu_s = (cpu_jiffies - previous["cputime_jiffies"]) / HZ
                norm = (
                    (switches - previous["ctx_switches"]) / cpu_s
                    if cpu_s > 0 else 0.0
                )
                record["norm_ctx_per_cpu_s"] = norm
                if (
                    self.decision_start_ns is None
                    or timestamp < self.decision_start_ns
                ):
                    self._state = "prefill"
                    run_length = 0
                elif self._state == "prefill":
                    run_length = run_length + 1 if norm > self.hi else 0
                    if run_length >= self.k:
                        self._state = "decode"
                        self.flip_count += 1
                        run_length = 0
                        if self.external_detect_ns is None:
                            self.external_detect_ns = timestamp
                            if self.external_callback is not None:
                                self.external_callback(timestamp, "external_proc")
                else:
                    run_length = run_length + 1 if norm < self.lo else 0
                    if run_length >= self.k:
                        self._state = "prefill"
                        self.flip_count += 1
                        run_length = 0
                record["state"] = self._state
            self.samples.append(record)
            previous = record
            action = self.actuator.record
            if (
                action is not None
                and action["counter_delta_200ms"] is None
                and timestamp >= action["t_affinity_done_ns"] + 200_000_000
            ):
                self.actuator.capture_200ms_delta()
            self.stop_flag.wait(self.interval_s)

    def summary(self):
        costs = sorted(sample["read_cost_ns"] for sample in self.samples)
        return {
            "interval_ms": self.interval_s * 1000.0,
            "hi": self.hi,
            "lo": self.lo,
            "k": self.k,
            "n_samples": len(self.samples),
            "read_cost_us_p50": (
                bl.percentile(costs, 50) / 1000.0 if costs else None
            ),
            "read_cost_us_p95": (
                bl.percentile(costs, 95) / 1000.0 if costs else None
            ),
            "external_detect_ns": self.external_detect_ns,
            "decision_start_ns": self.decision_start_ns,
            "flip_count": self.flip_count,
        }


class PhaseMarkWatcher(threading.Thread):
    """Common live marker acquisition path used by every C02 arm."""

    def __init__(self, log_path, offset, decision_callback=None, poll_s=0.001):
        super().__init__(daemon=True, name="c02-phase-marker")
        self.log_path = Path(log_path)
        self.offset = offset
        self.decision_callback = decision_callback
        self.poll_s = poll_s
        self.stop_flag = threading.Event()
        self.markers = []
        self.t_internal_phase_ns = None
        self.t_marker_seen_ns = None

    def observe_line(self, text):
        """Record marker delivery; optionally route decode to ORACLE only."""
        for batched_text, timestamp_text in MARK_RE.findall(text):
            marker = {
                "batched": int(batched_text),
                "t_mono_ns": int(timestamp_text),
                "t_marker_seen_ns": bl.now_ns(),
            }
            self.markers.append(marker)
            if marker["batched"] == 0 and self.t_internal_phase_ns is None:
                self.t_internal_phase_ns = marker["t_mono_ns"]
                self.t_marker_seen_ns = marker["t_marker_seen_ns"]
                if self.decision_callback is not None:
                    self.decision_callback(
                        marker["t_mono_ns"], "internal_oracle"
                    )

    def run(self):
        buffer = b""
        with self.log_path.open("rb") as source:
            source.seek(self.offset)
            while not self.stop_flag.is_set():
                chunk = source.read()
                if not chunk:
                    self.stop_flag.wait(self.poll_s)
                    continue
                buffer += chunk
                lines = buffer.split(b"\n")
                buffer = lines.pop()
                for line in lines:
                    self.observe_line(line.decode("utf-8", "replace"))


def phase_mark_watcher_for_arm(arm, log_path, offset, actuator, poll_s=0.001):
    """Instantiate the identical watcher path with strict arm routing."""
    marker_route = actuation_routes(arm, actuator)["internal_oracle"]
    return PhaseMarkWatcher(
        log_path,
        offset,
        decision_callback=marker_route,
        poll_s=poll_s,
    )


def parse_phase_markers_offline(log_path, offset):
    """Post-request ground truth. Never participates in EXTERNAL decisions."""
    with Path(log_path).open("rb") as source:
        source.seek(offset)
        text = source.read().decode("utf-8", "replace")
    return [
        {"batched": int(batched), "t_mono_ns": int(timestamp)}
        for batched, timestamp in MARK_RE.findall(text)
    ]


def first_internal_boundary(markers, t_request_sent_ns):
    return next(
        (
            marker["t_mono_ns"]
            for marker in markers
            if marker["batched"] == 0
            and marker["t_mono_ns"] >= t_request_sent_ns
        ),
        None,
    )


def thermal_throttle_snapshot():
    values = {}
    patterns = (
        "/sys/devices/system/cpu/cpu*/thermal_throttle/core_throttle_count",
        "/sys/devices/system/cpu/cpu*/thermal_throttle/package_throttle_count",
    )
    for pattern in patterns:
        for path in sorted(glob.glob(pattern)):
            value = bl._read_int(path)
            if value is not None:
                values[path] = value
    return values


def thermal_throttle_delta(before, after):
    common = sorted(set(before) & set(after))
    if not common:
        return None
    return {
        "per_path": {path: after[path] - before[path] for path in common},
        "total": sum(after[path] - before[path] for path in common),
    }


def token_metrics(t_sent, token_ts):
    if len(token_ts) < 2:
        raise RuntimeError(f"got {len(token_ts)} tokens; need at least 2")
    itl = [
        (token_ts[index] - token_ts[index - 1]) / 1e6
        for index in range(1, len(token_ts))
    ]
    ordered = sorted(itl)
    span_s = (token_ts[-1] - token_ts[0]) / 1e9
    return {
        "ttft_ms": round((token_ts[0] - t_sent) / 1e6, 3),
        "itl_p50_ms": round(bl.percentile(ordered, 50), 3),
        "itl_p95_ms": round(bl.percentile(ordered, 95), 3),
        "itl_p99_ms": round(bl.percentile(ordered, 99), 3),
        "itl_max_ms": round(ordered[-1], 3),
        "itl_mean_ms": round(sum(itl) / len(itl), 3),
        "decode_tps": round((len(token_ts) - 1) / span_s, 3),
        "n_tokens": len(token_ts),
        "itl_ms": [round(value, 4) for value in itl],
    }


def run_stem(item):
    return (
        f"round_{item['round']:02d}_seq_{item['sequence_index']:02d}_"
        f"{item['arm'].lower()}"
    )


def run_arm(args, item, spec, environment_file):
    outdir = Path(args.outdir)
    stem = run_stem(item)
    run_path = outdir / "raw" / "runs" / f"{stem}.json"
    token_path = outdir / "raw" / "tokens" / f"{stem}.json"
    server_log_path = outdir / "raw" / "server_logs" / f"{stem}.log"
    phase_log_path = outdir / "raw" / "phase_logs" / f"{stem}.json"
    for path in (run_path, token_path, server_log_path, phase_log_path):
        path.parent.mkdir(parents=True, exist_ok=True)

    log_handle = server_log_path.open("wb")
    proc = None
    monitor = None
    marker_watcher = None
    freq = None
    try:
        proc = subprocess.Popen(
            server_command(args, spec),
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        ro.wait_for_health(args.port, proc)
        prompt = Path(args.prompt).read_text(encoding="utf-8")
        prompt_tokens = ro.tokenize(args.port, prompt)
        ro.stream_completion(args.port, {
            "prompt": "Warmup.", "n_predict": 1, "temperature": 0,
            "stream": True, "cache_prompt": False,
        })
        time.sleep(1.0)
        log_handle.flush()
        warmup_offset = os.path.getsize(server_log_path)
        server_affinity_initial = sorted(os.sched_getaffinity(proc.pid))

        actuator = AffinityActuator(proc.pid, spec["final_cpus"] or [])
        routes = actuation_routes(item["arm"], actuator)
        monitor = ProcPhaseMonitor(
            proc.pid,
            interval_s=args.interval_ms / 1000.0,
            hi=args.hi,
            lo=args.lo,
            k=args.k,
            actuator=actuator,
            external_callback=routes["external_proc"],
        )
        monitor.start()
        marker_watcher = phase_mark_watcher_for_arm(
            item["arm"], server_log_path, warmup_offset, actuator
        )
        marker_watcher.start()
        time.sleep(0.3)

        temp_start = bl.package_temp_c()
        energy_start = read_energy_uj()
        sched_before = bl.sched_snapshot(proc.pid)
        throttle_before = thermal_throttle_snapshot()
        freq = bl.FreqSampler(busy_n=spec["threads"])
        freq.start()

        monitor_armed_ns = monitor.arm_for_request()
        t_sent, token_ts, text, _final = ro.stream_completion(args.port, {
            "prompt": prompt,
            "n_predict": args.n_predict,
            "temperature": 0.0,
            "seed": args.seed,
            "stream": True,
            "cache_prompt": False,
            "ignore_eos": True,
        })

        freq.stop()
        frequency = freq.summary()
        freq = None
        throttle_after = thermal_throttle_snapshot()
        sched_after = bl.sched_snapshot(proc.pid)
        energy_end = read_energy_uj()
        temp_end = bl.package_temp_c()
        monitor.stop_flag.set()
        monitor.join(timeout=5)
        marker_watcher.stop_flag.set()
        marker_watcher.join(timeout=5)
        log_handle.flush()

        markers = parse_phase_markers_offline(server_log_path, warmup_offset)
        internal_boundary = first_internal_boundary(markers, t_sent)
        if internal_boundary is None:
            raise RuntimeError(
                "diagnostic PHASE_MARK missing for measured request; all C02 "
                "arms require the same diagnostic server build"
            )
        if (
            marker_watcher.t_internal_phase_ns != internal_boundary
            or marker_watcher.t_marker_seen_ns is None
        ):
            raise RuntimeError(
                "live PHASE_MARK watcher did not preserve the measured "
                "internal boundary and local marker-seen timestamp"
            )
        if (
            item["arm"] == "ORACLE"
            and (
                actuator.record is None
                or actuator.record["t_trigger_ns"] != internal_boundary
            )
        ):
            raise RuntimeError(
                "ORACLE did not actuate from the measured internal boundary"
            )

        metrics = token_metrics(t_sent, token_ts)
        energy_j = (
            (energy_end - energy_start) / 1e6
            if energy_start is not None
            and energy_end is not None
            and energy_end >= energy_start
            else None
        )
        sched_counters = bl.sched_delta(sched_before, sched_after)
        action = actuator.record
        monitor_summary = monitor.summary()
        phase_log = {
            "schema_version": 1,
            "task": "TASK-C02",
            "arm": item["arm"],
            "phase_source": spec["phase_source"],
            "diagnostic_marker_use": (
                "live_trigger" if item["arm"] == "ORACLE"
                else "live_record_only"
            ),
            "markers_live": marker_watcher.markers,
            "markers_offline_cross_check": markers,
            "t_internal_phase_ns": internal_boundary,
            "t_marker_seen_ns": marker_watcher.t_marker_seen_ns,
            "t_external_detect_ns": monitor.external_detect_ns,
            "marker_routed_to_actuator": item["arm"] == "ORACLE",
            "proc_monitor": monitor_summary,
            "proc_samples": monitor.samples,
            "actuation": action,
        }
        c01.atomic_json(phase_log_path, phase_log)
        c01.atomic_json(token_path, {
            "schema_version": 1,
            "task": "TASK-C02",
            "arm": item["arm"],
            "t_request_sent_ns": t_sent,
            "t_monitor_armed_ns": monitor_armed_ns,
            "t_first_token_ns": token_ts[0],
            "t_last_token_ns": token_ts[-1],
            "token_ts_ns": token_ts,
            "itl_ms": metrics.pop("itl_ms"),
            "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "n_chars": len(text),
        })

        record = {
            "schema_version": 1,
            "task": "TASK-C02",
            **item,
            "timestamp": c01.utc_timestamp(),
            "status": "ok",
            "phase_source": spec["phase_source"],
            "diagnostic_server": True,
            "diagnostic_marker_consumption": (
                "live_trigger" if item["arm"] == "ORACLE"
                else "live_record_only"
            ),
            "monitor_mode": (
                "armed_external" if item["arm"] == "EXTERNAL"
                else "observation_only"
            ),
            "monitor_overhead_equalized": True,
            "live_marker_watcher": True,
            "marker_routed_to_actuator": item["arm"] == "ORACLE",
            "monitor_interval_ms": args.interval_ms,
            "monitor_read_cost_us_p50": monitor_summary["read_cost_us_p50"],
            "monitor_read_cost_us_p95": monitor_summary["read_cost_us_p95"],
            "detector_hi": args.hi,
            "detector_lo": args.lo,
            "detector_k": args.k,
            "external_detector_flip_count": monitor.flip_count,
            "threads": spec["threads"],
            "threads_batch": spec["threads_batch"],
            "initial_cpus": (
                "unpinned" if spec["initial_cpus"] is None
                else cpu_list_text(spec["initial_cpus"])
            ),
            "final_cpus": (
                "unchanged" if spec["final_cpus"] is None
                else cpu_list_text(spec["final_cpus"])
            ),
            "server_affinity_after_warmup": server_affinity_initial,
            "prompt_tokens": prompt_tokens,
            **metrics,
            **frequency,
            "total_migrations": sched_counters["migrations"],
            "total_ctx_switches": sched_counters["ctx_switches"],
            "threads_seen": sched_counters["threads_seen"],
            "temp_start_c": temp_start,
            "temp_end_c": temp_end,
            "energy_j": round(energy_j, 3) if energy_j is not None else None,
            "j_per_token": (
                round(energy_j / metrics["n_tokens"], 6)
                if energy_j is not None else None
            ),
            "thermal_throttle_before": throttle_before or None,
            "thermal_throttle_after": throttle_after or None,
            "thermal_throttle_delta": thermal_throttle_delta(
                throttle_before, throttle_after
            ),
            "external_detected": monitor.external_detect_ns is not None,
            "switch_attempted": action is not None,
            "switch_success": (
                action is not None
                and action["n_tids_succeeded"] > 0
                and action["n_tids_failed"] == 0
            ),
            "t_request_sent_ns": t_sent,
            "t_internal_phase_ns": internal_boundary,
            "t_marker_seen_ns": marker_watcher.t_marker_seen_ns,
            "t_external_detect_ns": monitor.external_detect_ns,
            "t_trigger_ns": action["t_trigger_ns"] if action else None,
            "trigger_source": action["trigger_source"] if action else None,
            "t_affinity_start_ns": (
                action["t_affinity_start_ns"] if action else None
            ),
            "t_affinity_done_ns": (
                action["t_affinity_done_ns"] if action else None
            ),
            "t_first_token_ns": token_ts[0],
            "t_last_token_ns": token_ts[-1],
            "affinity_cost_us": action["affinity_cost_us"] if action else None,
            "affinity_tids_succeeded": (
                action["n_tids_succeeded"] if action else 0
            ),
            "affinity_tids_failed": action["n_tids_failed"] if action else 0,
            "environment_file": environment_file,
            "token_file": str(token_path.relative_to(outdir)),
            "server_log": str(server_log_path.relative_to(outdir)),
            "phase_log": str(phase_log_path.relative_to(outdir)),
        }
        c01.atomic_json(run_path, record)
        return record
    finally:
        if freq is not None:
            freq.stop()
        if monitor is not None:
            monitor.stop_flag.set()
            monitor.join(timeout=2)
        if marker_watcher is not None:
            marker_watcher.stop_flag.set()
            marker_watcher.join(timeout=2)
        if proc is not None:
            c01.terminate_process_group(proc)
        log_handle.close()


def write_runs_csv(outdir):
    outdir = Path(outdir)
    rows = []
    for path in sorted((outdir / "raw" / "runs").glob("round_*.json")):
        rows.append(json.loads(path.read_text(encoding="utf-8")))
    csv_path = outdir / "c02_runs.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS,
                                extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return csv_path


def preserve_failed_artifacts(outdir, stem, stamp):
    """Move partial per-run artifacts aside so --resume cannot overwrite them."""
    outdir = Path(outdir)
    candidates = (
        ("server_logs", ".log"),
        ("tokens", ".json"),
        ("phase_logs", ".json"),
    )
    preserved = []
    for directory, suffix in candidates:
        source = outdir / "raw" / directory / f"{stem}{suffix}"
        if not source.exists():
            continue
        destination = (
            outdir / "raw" / directory / "failures"
            / f"{stem}_{stamp}{suffix}"
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, destination)
        preserved.append(str(destination.relative_to(outdir)))
    return preserved


def environment_record(args, preflight, specs, p_cpus, e_cpus):
    power = c01.power_metadata()
    power["intel_pstate_status"] = c01.read_text(
        "/sys/devices/system/cpu/intel_pstate/status"
    )
    return {
        "schema_version": 1,
        "task": "TASK-C02",
        "captured_at": c01.utc_timestamp(),
        "experiment": "clean external_proc vs internal_oracle phase source",
        "diagnostic_binary_disclosure": (
            "All arms use the same diagnostic server build and live marker "
            "watcher. PHASE_MARK is oracle ground truth; only ORACLE routes "
            "it to the actuator, and EXTERNAL does not consume it for "
            "decisions."
        ),
        "kernel": {
            "system": __import__("platform").system(),
            "release": __import__("platform").release(),
            "version": __import__("platform").version(),
            "machine": __import__("platform").machine(),
        },
        "preflight": preflight,
        "topology": c01.topology_metadata(),
        "cpu_sets": {"p_physical": p_cpus, "e": e_cpus,
                     "wide": p_cpus + e_cpus},
        "power": power,
        "thermal_throttle_paths": sorted(thermal_throttle_snapshot()),
        "package_temp_c_at_capture": bl.package_temp_c(),
        "llama_cpp": {
            "repository_commit": c01.git_head(ROOT / "llama.cpp"),
            "diagnostic_server_binary": c01.file_identity(
                args.server_bin, include_hash=True
            ),
        },
        "model": c01.file_identity(
            args.model, include_hash=not args.skip_model_hash
        ),
        "prompt": c01.file_identity(args.prompt, include_hash=True),
        "arm_configs": specs,
        "protocol": {
            "rounds": args.rounds,
            "runs": args.rounds * len(ARMS),
            "order_seed": args.order_seed,
            "interval_ms": args.interval_ms,
            "detector_hi": args.hi,
            "detector_lo": args.lo,
            "detector_k": args.k,
            "live_marker_watcher_all_arms": True,
            "cooldown_s": args.cooldown,
            "initial_cooldown_s": args.initial_cooldown,
            "full_pilot_approved": args.full_pilot_approved,
            "ctx": args.ctx,
            "batch": args.batch,
            "ubatch": args.ubatch,
            "n_predict": args.n_predict,
            "seed": args.seed,
        },
        "c01_gate": {
            "status": "CLOSED/PASS",
            "sampling_interval_ms": 50,
            "prefill_p_residency_pct": 52.827,
            "prefill_e_residency_pct": 47.173,
            "decode_p_residency_pct": 78.234,
            "decode_e_residency_pct": 21.766,
            "decode_e_residency_range_pct": [19.138, 23.792],
            "interpretation": (
                "composite stock Linux scheduling stack partially adapts but "
                "does not reproduce explicit phase-aware placement"
            ),
        },
    }


def register_environment(outdir, environment):
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    path = Path(outdir) / "raw" / "environment" / f"env_{stamp}.json"
    c01.atomic_json(path, environment)
    return str(path.relative_to(Path(outdir)))


def ensure_plan(outdir, rounds, order_seed, specs):
    outdir = Path(outdir)
    plan_path = outdir / "raw" / "plan.json"
    proposed = {
        "schema_version": 1,
        "task": "TASK-C02",
        "rounds": rounds,
        "order_seed": order_seed,
        "arms": list(ARMS),
        "arm_configs": specs,
        "schedule": build_schedule(rounds, order_seed),
    }
    if plan_path.exists():
        existing = json.loads(plan_path.read_text(encoding="utf-8"))
        same_protocol = (
            existing.get("order_seed") == order_seed
            and existing.get("arms") == list(ARMS)
            and existing.get("arm_configs") == specs
        )
        prefix_matches = (
            existing.get("schedule")
            == proposed["schedule"][:len(existing.get("schedule", []))]
        )
        if not same_protocol or not prefix_matches:
            raise RuntimeError(
                f"existing {plan_path} does not match requested protocol"
            )
        if existing.get("rounds", 0) > rounds:
            raise RuntimeError(
                f"existing {plan_path} already contains more rounds than "
                "requested; do not shrink a persisted experiment plan"
            )
        if existing.get("rounds", 0) < rounds:
            # An explicitly approved full pilot extends the reviewed smoke;
            # all existing round entries remain byte-for-byte identical.
            c01.atomic_json(plan_path, proposed)
        else:
            proposed = existing
    else:
        c01.atomic_json(plan_path, proposed)
    return proposed


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Run TASK-C02's five-arm randomized clean external-vs-oracle "
            "comparison"
        )
    )
    parser.add_argument("--server-bin", required=True,
                        help="single diagnostic PHASE_MARK llama-server build")
    parser.add_argument("--model", required=True)
    parser.add_argument("--prompt", default=str(HARNESS / "prompt_512.txt"))
    parser.add_argument("--outdir", default=str(ROOT / "results" / "conference_c02"))
    parser.add_argument("--rounds", type=int, default=SMOKE_ROUNDS)
    parser.add_argument("--order-seed", type=int, default=DEFAULT_ORDER_SEED)
    parser.add_argument("--interval-ms", type=float, default=DEFAULT_INTERVAL_MS)
    parser.add_argument("--hi", type=float, default=DEFAULT_HI)
    parser.add_argument("--lo", type=float, default=DEFAULT_LO)
    parser.add_argument("--k", type=int, default=DEFAULT_K)
    parser.add_argument("--ctx", type=int, default=2048)
    parser.add_argument("--batch", type=int, default=2048)
    parser.add_argument("--ubatch", type=int, default=512)
    parser.add_argument("--n-predict", type=int, default=256)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--port", type=int, default=8130)
    parser.add_argument("--initial-cooldown", type=int, default=30)
    parser.add_argument("--cooldown", type=int, default=30)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--skip-model-hash", action="store_true")
    parser.add_argument(
        "--full-pilot-approved", action="store_true",
        help="required for six rounds after explicit smoke checkpoint approval",
    )
    args = parser.parse_args(argv)
    if args.rounds not in (1, SMOKE_ROUNDS, FULL_PILOT_ROUNDS):
        parser.error(
            f"--rounds must be 1, {SMOKE_ROUNDS} (smoke), or "
            f"{FULL_PILOT_ROUNDS} (approved full pilot)"
        )
    if args.rounds == FULL_PILOT_ROUNDS and not args.full_pilot_approved:
        parser.error(
            "six-round C02 pilot requires explicit checkpoint approval and "
            "--full-pilot-approved"
        )
    if args.interval_ms != DEFAULT_INTERVAL_MS:
        parser.error(
            f"C02 freezes --interval-ms at {DEFAULT_INTERVAL_MS:g} ms"
        )
    if args.k <= 0:
        parser.error("--k must be positive")
    if args.lo >= args.hi:
        parser.error("--lo must be lower than --hi")
    for name in ("ctx", "batch", "ubatch", "n_predict", "port"):
        if getattr(args, name) <= 0:
            parser.error(f"--{name.replace('_', '-')} must be positive")
    if args.initial_cooldown < 0 or args.cooldown < 0:
        parser.error("cooldowns must be non-negative")
    for name in ("server_bin", "model", "prompt"):
        if not Path(getattr(args, name)).exists():
            parser.error(
                f"--{name.replace('_', '-')} does not exist: {getattr(args, name)}"
            )
    return args


def main(argv=None):
    args = parse_args(argv)
    preflight = c01.stock_preflight()
    p_cpus, e_cpus = discover_cpu_sets()
    specs = arm_specs(p_cpus, e_cpus)
    plan = ensure_plan(args.outdir, args.rounds, args.order_seed, specs)
    environment_file = register_environment(
        args.outdir,
        environment_record(args, preflight, specs, p_cpus, e_cpus),
    )
    if args.initial_cooldown:
        print(f"[C02] initial cooldown {args.initial_cooldown}s", flush=True)
        time.sleep(args.initial_cooldown)

    failures = 0
    completed = 0
    for item in plan["schedule"]:
        stem = run_stem(item)
        run_path = Path(args.outdir) / "raw" / "runs" / f"{stem}.json"
        if run_path.exists():
            if args.resume:
                print(f"  {stem}: existing result, skipped", flush=True)
                continue
            raise FileExistsError(f"{run_path} exists; use --resume")
        if completed > 0:
            print(f"[C02] cooldown {args.cooldown}s", flush=True)
            time.sleep(args.cooldown)
        print(
            f"[C02] round={item['round']} seq={item['sequence_index']} "
            f"arm={item['arm']} phase_source={PHASE_SOURCES[item['arm']]}",
            flush=True,
        )
        try:
            record = run_arm(
                args, item, specs[item["arm"]], environment_file
            )
        except Exception as exc:
            failures += 1
            stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
            failure = {
                "schema_version": 1,
                "task": "TASK-C02",
                **item,
                "timestamp": c01.utc_timestamp(),
                "error_type": type(exc).__name__,
                "error": str(exc),
                "preserved_artifacts": preserve_failed_artifacts(
                    args.outdir, stem, stamp
                ),
            }
            failure_path = (
                Path(args.outdir) / "raw" / "runs" / "failures"
                / f"{stem}_{stamp}.json"
            )
            c01.atomic_json(failure_path, failure)
            print(f"  FAILED: {exc}", flush=True)
        else:
            print(
                f"  ttft={record['ttft_ms']:.1f}ms "
                f"p95={record['itl_p95_ms']:.2f}ms "
                f"tps={record['decode_tps']:.2f} "
                f"switch={record['switch_success']} "
                f"T={record['temp_start_c']}->{record['temp_end_c']}C",
                flush=True,
            )
        completed += 1
        write_runs_csv(args.outdir)
    csv_path = write_runs_csv(args.outdir)
    print(f"[C02] run table -> {csv_path}", flush=True)
    if failures:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
