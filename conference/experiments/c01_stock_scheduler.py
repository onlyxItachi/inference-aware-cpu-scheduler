#!/usr/bin/env python3
"""TASK-C01 stock-scheduler characterization and performance runner.

The two subcommands intentionally produce different evidence:

``characterize``
    Samples per-thread CPU placement during one request.  The diagnostic
    ``PHASE_MARK`` stream is copied from the server log into the raw trace and
    is used only later by ``c01_analyze.py`` to label samples.  It never feeds
    back into placement or any other runtime decision.  Latency from this path
    is marked perturbed and is not primary performance evidence.

``performance``
    Calls the validated ``harness/run_once.py`` measurement path.  It collects
    token timing, low-overhead /proc counter deltas, temperature, and frequency
    without starting the residency sampler.

Both modes run the required S0_STOCK_UNPINNED arm: no taskset wrapper and no
explicit affinity call.  The script is an experiment preparer/runner only; it
does not interpret whether Linux or hardware guidance "solves" anything.
"""

import argparse
import csv
import hashlib
import json
import os
import platform
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT / "harness"
sys.path.insert(0, str(HARNESS))

import bench_lib as bl  # noqa: E402
import run_once as ro  # noqa: E402
import thread_residency as tr  # noqa: E402


ARM = "S0_STOCK_UNPINNED"
MARK_RE = re.compile(r"PHASE_MARK batched=(\d+) t_mono_ns=(\d+)")
DEFAULT_THREADS = 8
DEFAULT_THREADS_BATCH = 16
SMOKE_RUNS = 2
FULL_PILOT_RUNS = 6
PERF_FIELDS = [
    "arm", "run", "timestamp", "protocol_stage", "ttft_ms", "itl_p50_ms", "itl_p95_ms",
    "itl_p99_ms", "itl_max_ms", "itl_mean_ms", "decode_tps", "n_tokens",
    "prompt_tokens", "temp_start_c", "temp_end_c", "temp_delta_c",
    "migrations", "ctx_switches", "threads_seen", "freq_p_avg_mhz",
    "freq_p_busy_mhz", "freq_e_avg_mhz", "freq_samples", "threads",
    "threads_batch", "cpus", "ctx", "batch", "ubatch", "seed",
    "n_predict", "server_affinity", "residency_sampler_enabled",
    "environment_file",
]


def utc_timestamp():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def protocol_stage(args):
    return (
        "full_pilot_after_review"
        if args.runs == FULL_PILOT_RUNS else "sensitivity_smoke"
    )


def path_tag(interval_ms):
    value = f"{interval_ms:g}".replace(".", "p")
    return f"interval_{value}ms"


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(value, f, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)


def read_text(path):
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return None


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as f:
        while True:
            chunk = f.read(8 * 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def parse_cpu_list(value):
    cpus = set()
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, hi = (int(x) for x in part.split("-", 1))
            cpus.update(range(lo, hi + 1))
        else:
            cpus.add(int(part))
    return sorted(cpus)


def online_cpus():
    value = read_text("/sys/devices/system/cpu/online")
    if value:
        return parse_cpu_list(value)
    return list(range(os.cpu_count() or 1))


def sched_ext_state():
    return read_text("/sys/kernel/sched_ext/state") or "not-present"


def stock_preflight():
    """Fail closed if the requested arm is not actually stock and unpinned."""
    state = sched_ext_state()
    if state not in ("disabled", "not-present"):
        raise RuntimeError(
            "S0_STOCK_UNPINNED requires sched_ext to be disabled; observed "
            f"/sys/kernel/sched_ext/state={state!r}. The script will not "
            "change scheduler state."
        )

    allowed = sorted(os.sched_getaffinity(0))
    online = online_cpus()
    if allowed != online:
        raise RuntimeError(
            "S0_STOCK_UNPINNED requires the invoking process to be allowed on "
            f"all online CPUs; allowed={allowed}, online={online}. Remove any "
            "parent taskset/cpuset restriction before running C01."
        )
    return {"sched_ext_state": state, "allowed_cpus": allowed,
            "online_cpus": online}


def git_head(path):
    try:
        proc = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True,
        )
        return proc.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def file_identity(path, include_hash=True):
    resolved = Path(path).resolve()
    stat = resolved.stat()
    return {
        "path": str(Path(path)),
        "resolved_path": str(resolved),
        "size_bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sha256": sha256_file(resolved) if include_hash else None,
        "sha256_skipped": not include_hash,
    }


def topology_metadata():
    cpu_core, core_cpus = tr.read_topology()
    cpus = {}
    for cpu in sorted(cpu_core):
        core_id, is_pcore = cpu_core[cpu]
        cpus[str(cpu)] = {
            "core_id": core_id,
            "core_class": "P" if is_pcore else "E",
            "siblings": core_cpus.get(core_id, []),
            "cpuinfo_max_freq_khz": bl._read_int(
                f"/sys/devices/system/cpu/cpu{cpu}/cpufreq/cpuinfo_max_freq"
            ),
        }
    return {
        "classification": "thread_residency.read_topology; max_freq > 4GHz => P",
        "cpus": cpus,
        "core_siblings": {str(k): v for k, v in sorted(core_cpus.items())},
    }


def power_metadata():
    governors = set()
    drivers = set()
    preferences = set()
    for cpu in online_cpus():
        base = Path(f"/sys/devices/system/cpu/cpu{cpu}/cpufreq")
        governor = read_text(base / "scaling_governor")
        driver = read_text(base / "scaling_driver")
        preference = read_text(base / "energy_performance_preference")
        if governor:
            governors.add(governor)
        if driver:
            drivers.add(driver)
        if preference:
            preferences.add(preference)
    return {
        "governors": sorted(governors),
        "drivers": sorted(drivers),
        "energy_performance_preferences": sorted(preferences),
        "platform_profile": read_text("/sys/firmware/acpi/platform_profile"),
        "intel_pstate_no_turbo": read_text(
            "/sys/devices/system/cpu/intel_pstate/no_turbo"
        ),
    }


def capture_environment(args, mode, preflight):
    server = file_identity(args.server_bin, include_hash=True)
    model = file_identity(args.model, include_hash=not args.skip_model_hash)
    prompt = file_identity(args.prompt, include_hash=True)
    return {
        "schema_version": 1,
        "task": "TASK-C01",
        "arm": ARM,
        "mode": mode,
        "captured_at": utc_timestamp(),
        "kernel": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
        },
        "os_release": read_text("/etc/os-release"),
        "preflight": preflight,
        "topology": topology_metadata(),
        "power": power_metadata(),
        "package_temp_c_at_capture": bl.package_temp_c(),
        "llama_cpp": {
            "repository_commit": git_head(ROOT / "llama.cpp"),
            "server_binary": server,
        },
        "model": model,
        "prompt": prompt,
        "config": {
            "protocol_stage": protocol_stage(args),
            "threads": args.threads,
            "threads_batch": args.threads_batch or args.threads,
            "ctx": args.ctx,
            "batch": args.batch,
            "ubatch": args.ubatch,
            "n_predict": args.n_predict,
            "runs": args.runs,
            "full_pilot_approved": args.full_pilot_approved,
            "initial_cooldown_s": args.initial_cooldown,
            "cooldown_s": args.cooldown,
            "port": args.port,
            "sampling_interval_ms": getattr(args, "interval_ms", None),
        },
    }


def register_environment(outdir, environment):
    outdir = Path(outdir)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    suffix = environment["mode"]
    if environment["config"]["sampling_interval_ms"] is not None:
        suffix += "_" + path_tag(environment["config"]["sampling_interval_ms"])
    env_path = outdir / "raw" / "environment" / f"env_{stamp}_{suffix}.json"
    atomic_json(env_path, environment)

    index_path = outdir / "env.json"
    if index_path.exists():
        try:
            previous = json.loads(index_path.read_text(encoding="utf-8"))
            sessions = previous.get("sessions", [])
        except (OSError, json.JSONDecodeError):
            sessions = []
    else:
        sessions = []
    rel = str(env_path.relative_to(outdir))
    if rel not in sessions:
        sessions.append(rel)
    # env.json is both a directly useful snapshot and an index of the
    # immutable per-invocation environment records.
    index = dict(environment)
    index["sessions"] = sessions
    index["latest"] = rel
    atomic_json(index_path, index)
    return rel


def server_command(args):
    threads_batch = args.threads_batch or args.threads
    # Deliberately no taskset prefix and no affinity operation for S0.
    return [
        args.server_bin, "-m", args.model,
        "-t", str(args.threads), "-tb", str(threads_batch),
        "-c", str(args.ctx), "-b", str(args.batch),
        "-ub", str(args.ubatch), "-np", "1",
        "--host", ro.HOST, "--port", str(args.port),
    ]


def terminate_process_group(proc):
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        proc.wait(timeout=20)
    except ProcessLookupError:
        return
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass


def parse_phase_markers(log_path, offset):
    with Path(log_path).open("rb") as f:
        f.seek(offset)
        text = f.read().decode("utf-8", "replace")
    return [
        {"batched": int(batched), "t_mono_ns": int(t_mono_ns)}
        for batched, t_mono_ns in MARK_RE.findall(text)
    ]


def perturbed_metrics(t_sent, token_ts):
    itl = [
        (token_ts[i] - token_ts[i - 1]) / 1e6
        for i in range(1, len(token_ts))
    ]
    values = sorted(itl)
    span_s = (token_ts[-1] - token_ts[0]) / 1e9 if len(token_ts) > 1 else 0
    return {
        "diagnostic_only": True,
        "reason": "high-frequency residency sampling perturbs latency",
        "ttft_ms_perturbed": (token_ts[0] - t_sent) / 1e6 if token_ts else None,
        "itl_p50_ms_perturbed": bl.percentile(values, 50),
        "itl_p95_ms_perturbed": bl.percentile(values, 95),
        "decode_tps_perturbed": ((len(token_ts) - 1) / span_s)
        if span_s > 0 else None,
    }


def run_characterization_once(args, run_number, trace_path, log_path,
                              environment_file):
    prompt = Path(args.prompt).read_text(encoding="utf-8")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = log_path.open("wb")
    proc = subprocess.Popen(
        server_command(args), stdout=log, stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    request = None
    freq = bl.FreqSampler(busy_n=args.threads)
    freq_started = False
    holder = {}
    samples = []
    warmup_offset = 0
    sched_before = {}
    sched_after = {}
    temp_start = temp_end = None
    server_affinity = []
    try:
        ro.wait_for_health(args.port, proc)
        server_affinity = sorted(os.sched_getaffinity(proc.pid))
        ro.stream_completion(args.port, {
            "prompt": "Warmup.", "n_predict": 1, "temperature": 0,
            "stream": True, "cache_prompt": False,
        })
        time.sleep(1.0)
        log.flush()
        warmup_offset = os.path.getsize(log_path)

        payload = {
            "prompt": prompt,
            "n_predict": args.n_predict,
            "temperature": 0.0,
            "seed": args.seed,
            "stream": True,
            "cache_prompt": False,
            "ignore_eos": True,
        }

        def do_request():
            try:
                holder["result"] = ro.stream_completion(args.port, payload)
            except BaseException as exc:  # passed back to the main thread
                holder["exception"] = exc

        temp_start = bl.package_temp_c()
        sched_before = bl.sched_snapshot(proc.pid)
        freq.start()
        freq_started = True

        # One pre-request baseline gives the offline analyzer a CPU-time
        # counter to compare against for the first in-window sample.  Its
        # timestamp is before t_sent, so it cannot be mislabeled as prefill.
        t0 = time.perf_counter_ns()
        baseline_tasks = tr.sample_tasks(proc.pid)
        t1 = time.perf_counter_ns()
        samples.append({
            "t_mono_ns": (t0 + t1) // 2,
            "read_cost_ns": t1 - t0,
            "tasks": [
                {"tid": tid, **task}
                for tid, task in sorted(baseline_tasks.items())
            ],
        })

        request = threading.Thread(target=do_request, name="c01-request")
        request.start()

        interval_s = args.interval_ms / 1000.0
        next_sample = time.perf_counter() + interval_s
        while request.is_alive():
            delay = next_sample - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
            if not request.is_alive():
                break
            t0 = time.perf_counter_ns()
            tasks = tr.sample_tasks(proc.pid)
            t1 = time.perf_counter_ns()
            samples.append({
                "t_mono_ns": (t0 + t1) // 2,
                "read_cost_ns": t1 - t0,
                "tasks": [
                    {"tid": tid, **task} for tid, task in sorted(tasks.items())
                ],
            })
            next_sample += interval_s

        request.join()
        if "exception" in holder:
            raise holder["exception"]
        sched_after = bl.sched_snapshot(proc.pid)
        temp_end = bl.package_temp_c()
    finally:
        if request is not None and request.is_alive():
            request.join(timeout=2)
        if freq_started:
            freq.stop()
        terminate_process_group(proc)
        log.close()

    t_sent, token_ts, _text, _final = holder["result"]
    markers = parse_phase_markers(log_path, warmup_offset)
    boundary = next(
        (m["t_mono_ns"] for m in markers
         if m["batched"] == 0 and m["t_mono_ns"] >= t_sent),
        None,
    )
    costs = sorted(s["read_cost_ns"] for s in samples)
    trace = {
        "schema_version": 1,
        "task": "TASK-C01",
        "path": "characterization",
        "arm": ARM,
        "run": run_number,
        "timestamp": utc_timestamp(),
        "environment_file": environment_file,
        "config": {
            "protocol_stage": protocol_stage(args),
            "threads": args.threads,
            "threads_batch": args.threads_batch or args.threads,
            "n_predict": args.n_predict,
            "interval_ms": args.interval_ms,
            "cpus": "unpinned",
            "server_affinity": server_affinity,
        },
        "clock": "CLOCK_MONOTONIC via time.perf_counter_ns",
        "phase_labeling": {
            "method": "offline diagnostic PHASE_MARK",
            "used_during_scheduling": False,
            "phase_markers": markers,
            "first_decode_boundary_ns": boundary,
        },
        "request": {
            "t_sent_ns": t_sent,
            "t_first_token_ns": token_ts[0] if token_ts else None,
            "t_last_token_ns": token_ts[-1] if token_ts else None,
            "token_ts_ns": token_ts,
            "n_tokens": len(token_ts),
        },
        "samples": samples,
        "sampler": {
            "n_samples": len(samples),
            "read_cost_us_p50": bl.percentile(costs, 50) / 1000 if costs else None,
            "read_cost_us_p95": bl.percentile(costs, 95) / 1000 if costs else None,
        },
        "whole_request_counters": bl.sched_delta(sched_before, sched_after),
        "temperature": {"start_c": temp_start, "end_c": temp_end},
        "frequency": freq.summary(),
        "latency": perturbed_metrics(t_sent, token_ts),
        "status": "ok" if boundary is not None else "missing_phase_boundary",
    }
    atomic_json(trace_path, trace)
    if boundary is None:
        raise RuntimeError(
            f"no measured-request PHASE_MARK batched=0 found; raw trace saved "
            f"to {trace_path}. Use the diagnostic server build for "
            "characterization."
        )
    return trace


def write_performance_csv(perf_dir):
    records = []
    for path in sorted(perf_dir.glob("perf_run_*.json")):
        records.append(json.loads(path.read_text(encoding="utf-8")))
    csv_path = perf_dir / "perf_runs.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=PERF_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    return csv_path


def run_characterization(args, environment_file):
    interval_dir = (
        Path(args.outdir) / "raw" / "characterization" / path_tag(args.interval_ms)
    )
    trace_dir = interval_dir / "traces"
    log_dir = interval_dir / "server_logs"
    trace_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    print(
        f"[C01 characterize] arm={ARM} runs={args.runs} "
        f"interval={args.interval_ms:g}ms stage={protocol_stage(args)} "
        "(latency is diagnostic/perturbed)",
        flush=True,
    )
    for run in range(1, args.runs + 1):
        trace_path = trace_dir / f"trace_run_{run:03d}.json"
        log_path = log_dir / f"server_run_{run:03d}.log"
        if trace_path.exists():
            if args.resume:
                print(f"  run {run:03d}: existing trace, skipped", flush=True)
                continue
            raise FileExistsError(
                f"{trace_path} exists; use --resume to keep completed runs"
            )
        if run > 1:
            print(f"  cooldown {args.cooldown}s", flush=True)
            time.sleep(args.cooldown)
        started = time.time()
        try:
            trace = run_characterization_once(
                args, run, trace_path, log_path, environment_file
            )
        except BaseException as exc:
            failure = {
                "task": "TASK-C01", "path": "characterization", "arm": ARM,
                "run": run, "timestamp": utc_timestamp(),
                "interval_ms": args.interval_ms,
                "threads": args.threads,
                "threads_batch": args.threads_batch or args.threads,
                "error_type": type(exc).__name__, "error": str(exc),
                "partial_trace": str(trace_path) if trace_path.exists() else None,
                "server_log": str(log_path),
            }
            atomic_json(
                interval_dir / f"trace_run_{run:03d}.failure.json", failure
            )
            raise
        print(
            f"  run {run:03d}: samples={trace['sampler']['n_samples']} "
            f"sample_cost_p95={trace['sampler']['read_cost_us_p95']:.1f}us "
            f"T={trace['temperature']['start_c']}->{trace['temperature']['end_c']}C "
            f"wall={time.time() - started:.0f}s",
            flush=True,
        )
    print(f"[C01 characterize] raw -> {interval_dir}", flush=True)


def run_performance(args, environment_file):
    perf_dir = Path(args.outdir) / "raw" / "performance"
    token_dir = perf_dir / "tokens"
    log_dir = perf_dir / "server_logs"
    perf_dir.mkdir(parents=True, exist_ok=True)
    token_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    print(
        f"[C01 performance] arm={ARM} runs={args.runs} "
        f"stage={protocol_stage(args)} residency_sampler=disabled",
        flush=True,
    )
    for run in range(1, args.runs + 1):
        out_path = perf_dir / f"perf_run_{run:03d}.json"
        if out_path.exists():
            if args.resume:
                print(f"  run {run:03d}: existing result, skipped", flush=True)
                continue
            raise FileExistsError(
                f"{out_path} exists; use --resume to keep completed runs"
            )
        if run > 1:
            print(f"  cooldown {args.cooldown}s", flush=True)
            time.sleep(args.cooldown)

        measure_args = SimpleNamespace(
            server_bin=args.server_bin,
            model=args.model,
            prompt=args.prompt,
            threads=args.threads,
            threads_batch=args.threads_batch,
            cpus="",
            ctx=args.ctx,
            batch=args.batch,
            ubatch=args.ubatch,
            seed=args.seed,
            n_predict=args.n_predict,
            port=args.port,
            tokens_out=str(token_dir / f"tokens_run_{run:03d}.json"),
            server_log=str(log_dir / f"server_run_{run:03d}.log"),
        )
        started = time.time()
        try:
            rec = ro.measure(measure_args)
        except BaseException as exc:
            failure = {
                "task": "TASK-C01", "path": "performance", "arm": ARM,
                "run": run, "timestamp": utc_timestamp(),
                "threads": args.threads,
                "threads_batch": args.threads_batch or args.threads,
                "error_type": type(exc).__name__, "error": str(exc),
            }
            atomic_json(perf_dir / f"perf_run_{run:03d}.failure.json", failure)
            raise
        rec.update({
            "arm": ARM,
            "run": run,
            "timestamp": utc_timestamp(),
            "protocol_stage": protocol_stage(args),
            # Repeat both values even though run_once already reports them;
            # C01 metadata must make the frozen 8-decode/16-prefill protocol
            # explicit and self-contained in every raw row.
            "threads": args.threads,
            "threads_batch": args.threads_batch or args.threads,
            "server_affinity": sorted(os.sched_getaffinity(0)),
            "residency_sampler_enabled": False,
            "environment_file": environment_file,
        })
        atomic_json(out_path, rec)
        write_performance_csv(perf_dir)
        print(
            f"  run {run:03d}: ttft={rec['ttft_ms']:.1f}ms "
            f"p95={rec['itl_p95_ms']:.2f}ms tps={rec['decode_tps']:.2f} "
            f"mig={rec['migrations']} "
            f"T={rec['temp_start_c']}->{rec['temp_end_c']}C "
            f"wall={time.time() - started:.0f}s",
            flush=True,
        )
    csv_path = write_performance_csv(perf_dir)
    print(f"[C01 performance] raw -> {csv_path}", flush=True)


def add_common_args(parser):
    parser.add_argument("--server-bin", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument(
        "--prompt", default=str(HARNESS / "prompt_512.txt"),
    )
    parser.add_argument("--outdir", default=str(ROOT / "results" / "conference_c01"))
    parser.add_argument(
        "--runs", type=int, default=SMOKE_RUNS,
        help=("1-2 for the sensitivity smoke; 6 only after checkpoint review "
              "and with --full-pilot-approved"),
    )
    parser.add_argument(
        "--initial-cooldown", type=int, default=30,
        help="cooldown after environment/model identity capture and before run 1",
    )
    parser.add_argument("--cooldown", type=int, default=30)
    parser.add_argument("--threads", type=int, default=DEFAULT_THREADS)
    parser.add_argument(
        "--threads-batch", type=int, default=DEFAULT_THREADS_BATCH,
        help=("prefill threads; frozen C01 default is 16; 0 explicitly requests "
              "the same value as --threads"),
    )
    parser.add_argument("--ctx", type=int, default=2048)
    parser.add_argument("--batch", type=int, default=2048)
    parser.add_argument("--ubatch", type=int, default=512)
    parser.add_argument("--n-predict", type=int, default=256)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--port", type=int, default=8120)
    parser.add_argument(
        "--skip-model-hash", action="store_true",
        help="record path/size/mtime but omit the potentially expensive SHA-256",
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="skip existing successful run files instead of overwriting raw data",
    )
    parser.add_argument(
        "--full-pilot-approved", action="store_true",
        help="confirm checkpoint review authorized the 6-run full pilot",
    )


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Prepare/run TASK-C01 stock unpinned measurements",
    )
    sub = parser.add_subparsers(dest="mode", required=True)
    char = sub.add_parser(
        "characterize",
        help="intrusive phase-specific residency trace (not latency evidence)",
    )
    add_common_args(char)
    char.add_argument(
        "--interval-ms", type=float, required=True,
        help="sampling interval in milliseconds; sensitivity smoke uses 20 and 50",
    )
    perf = sub.add_parser(
        "performance",
        help="low-overhead stock performance path with no residency sampler",
    )
    add_common_args(perf)
    args = parser.parse_args(argv)

    if args.runs not in (1, SMOKE_RUNS, FULL_PILOT_RUNS):
        parser.error(
            f"--runs must be 1, {SMOKE_RUNS} (smoke), or "
            f"{FULL_PILOT_RUNS} (review-approved full pilot)"
        )
    if args.runs == FULL_PILOT_RUNS and not args.full_pilot_approved:
        parser.error(
            "6-run C01 pilot requires checkpoint review and "
            "--full-pilot-approved"
        )
    if args.initial_cooldown < 0 or args.cooldown < 0:
        parser.error("--initial-cooldown and --cooldown must be non-negative")
    for name in ("threads", "ctx", "batch", "ubatch", "n_predict", "port"):
        if getattr(args, name) <= 0:
            parser.error(f"--{name.replace('_', '-')} must be positive")
    if args.threads_batch < 0:
        parser.error("--threads-batch must be non-negative")
    if args.mode == "characterize" and args.interval_ms <= 0:
        parser.error("--interval-ms must be positive")
    for name in ("server_bin", "model", "prompt"):
        if not Path(getattr(args, name)).exists():
            parser.error(f"--{name.replace('_', '-')} does not exist: {getattr(args, name)}")
    return args


def main(argv=None):
    args = parse_args(argv)
    preflight = stock_preflight()
    environment = capture_environment(args, args.mode, preflight)
    environment_file = register_environment(args.outdir, environment)
    if args.initial_cooldown:
        print(
            f"[C01] initial cooldown {args.initial_cooldown}s after metadata capture",
            flush=True,
        )
        time.sleep(args.initial_cooldown)
    if args.mode == "characterize":
        run_characterization(args, environment_file)
    else:
        run_performance(args, environment_file)


if __name__ == "__main__":
    main()
