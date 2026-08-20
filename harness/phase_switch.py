"""İŞ 2 — the project's headline claim, measured instead of projected.

"Prefill on P+E, decode on P only" has so far been computed from two static
arms. This runs it for real: a live phase detector drives sched_setaffinity
on the server's threads mid-request.

Minimal on purpose. This is not Faz 2's policy -- no competing load, no
adaptation, no core-count tuning. One switch, one direction, to find out
whether the mechanism survives contact with the transition cost.

Design notes:

  Thread counts are fixed at context creation, so the arm uses -t 8 -tb 16:
  llama.cpp already routes prefill to the batch threadpool (16 threads) and
  decode to the generation one (8). İŞ 5 showed that alone is not enough --
  decode's 8 threads drift onto E-cores. Affinity is the missing half.

  The sampler runs in EVERY arm, including the static ones that ignore it.
  It costs ~1.7 ms per 20 ms tick; leaving it out of the controls would
  hand the switching arm a handicap the comparison would then hide.

  The switch fires on the detector's own decision, which leads ground truth
  by ~135 ms. That means the last ~135 ms of prefill runs on the narrow
  mask. That cost is real and is part of what is being measured, not
  corrected for.
"""

import argparse
import glob
import json
import os
import signal
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bench_lib as bl
import run_once as ro

HZ = 100
P8 = [0, 2, 4, 6, 8, 10, 12, 14]
E8 = list(range(16, 24))
P8E8 = P8 + E8

RAPL = None
for _p in ("/sys/class/powercap/intel-rapl:0/energy_uj",
           "/sys/class/powercap/intel-rapl:0/intel-rapl:0:0/energy_uj"):
    try:
        with open(_p) as _f:
            _f.read()
        RAPL = _p
        break
    except OSError:
        pass


def read_energy_uj():
    if RAPL is None:
        return None
    try:
        with open(RAPL) as f:
            return int(f.read().strip())
    except OSError:
        return None


def sched_totals(pid):
    sw = mig = 0
    for path in glob.glob(f"/proc/{pid}/task/*/sched"):
        try:
            with open(path) as f:
                for line in f:
                    if line.startswith("nr_switches"):
                        sw += int(line.split(":")[1])
                    elif line.startswith("se.nr_migrations"):
                        mig += int(line.split(":")[1])
        except (OSError, ValueError):
            continue
    return sw, mig


P_FREQ_PATHS = [f"/sys/devices/system/cpu/cpu{c}/cpufreq/scaling_cur_freq"
                for c in P8]


def read_p_freq_khz():
    """Frequency of the P-cores the LLM decodes on.

    Needed for İŞ 4: the warm-up transient seen in the static arm could be a
    frequency ramp rather than a placement effect, and only a time series
    can tell those apart.
    """
    vals = [v for v in (bl._read_int(p) for p in P_FREQ_PATHS) if v]
    return sorted(vals, reverse=True)[:8]


def read_cpu_busy():
    """Per-CPU (total, idle) jiffies, for E-core occupancy.

    İŞ 2 needs to know whether a realistic competitor actually leaves gaps
    on the E-cores -- the synthetic one by construction does not.
    """
    out = {}
    with open("/proc/stat") as f:
        for line in f:
            if line.startswith("cpu") and len(line) > 3 and line[3].isdigit():
                parts = line.split()
                vals = [int(x) for x in parts[1:11]]
                out[int(parts[0][3:])] = (sum(vals), vals[3] + vals[4])
            elif line.startswith("intr"):
                break
    return out


def count_objs(build_dir):
    """Object files present -- the build competitor's unit of work."""
    n = 0
    for _root, _dirs, files in os.walk(build_dir):
        n += sum(1 for f in files if f.endswith(".o"))
    return n


def cputime_jiffies(pid):
    try:
        with open(f"/proc/{pid}/stat") as f:
            data = f.read()
        rest = data[data.rfind(")") + 2:].split()
        return int(rest[11]) + int(rest[12])
    except (OSError, IndexError, ValueError):
        return None


def start_load(loadgen, cpus, nthreads, out_path, nice=0, weight=0,
               sched_idle=False):
    """Competing load, pinned where static D put it: the E-cores.

    Same placement in every arm, so the only thing that varies is whether
    (and when) the LLM also occupies those cores.

    nice / cgroup weight emulate a soft priority so sched_ext's headroom can
    be bounded before any BPF is written: if plain CFS knobs already recover
    the gap, sched_ext's marginal value is small and the claim must be
    rewritten.
    """
    if not nthreads:
        return None
    cmd = []
    if weight:
        # systemd-run --user puts the load in its own cgroup v2 scope, so
        # CPUWeight applies to it alone. Needs no root: the user slice
        # already has the cpu controller delegated.
        cmd += ["systemd-run", "--user", "--scope", "-q",
                f"--property=CPUWeight={weight}"]
    if sched_idle:
        cmd += ["chrt", "--idle", "0"]
    if nice:
        cmd += ["nice", "-n", str(nice)]
    cmd += (["taskset", "-c", cpus] if cpus else []) + [loadgen, str(nthreads)]
    fh = open(out_path, "w")
    proc = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.DEVNULL,
                            start_new_session=True)
    proc._fh, proc._path = fh, out_path
    time.sleep(2.0)
    return proc


def stop_load(proc):
    if proc is None:
        return {}
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        proc.wait(timeout=15)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        proc._fh.close()
    except Exception:
        pass
    try:
        with open(proc._path) as f:
            for line in f:
                if line.startswith("LOADGEN_RESULT"):
                    kv = dict(p.split("=", 1) for p in line.split()[1:])
                    return {"load_iters": int(kv["iters"]),
                            "load_rate": float(kv["rate"]),
                            "load_elapsed_s": float(kv["elapsed_s"])}
    except OSError:
        pass
    return {}


def set_affinity_all(pid, cpus):
    """Apply a CPU mask to every thread of pid. Returns (ok, failed)."""
    ok = fail = 0
    mask = set(cpus)
    for path in glob.glob(f"/proc/{pid}/task/*"):
        try:
            tid = int(os.path.basename(path))
        except ValueError:
            continue
        try:
            os.sched_setaffinity(tid, mask)
            ok += 1
        except OSError:
            fail += 1
    return ok, fail


class PhaseSwitcher(threading.Thread):
    """Samples the normalised ctx-switch rate and switches affinity once."""

    def __init__(self, pid, hi, lo, k, interval_s, narrow_cpus, armed):
        super().__init__(daemon=True)
        self.pid = pid
        self.hi, self.lo, self.k = hi, lo, k
        self.interval_s = interval_s
        self.narrow_cpus = narrow_cpus
        self.armed = armed          # False for the static control arms
        self.stop_flag = threading.Event()
        self.samples = []
        self.switch_t_ns = None
        self.switch_applied = None
        self.switch_cost_us = None
        # Migration burst must be measured per-tid: summing counters across
        # threads understates it (and can go negative) because the batch
        # threadpool's threads park or exit at the phase boundary, removing
        # their counters from the sum.
        self._snap_before = None
        self._snap_after = None
        self.burst = None

    def run(self):
        prev = None
        run_len = 0
        state = "prefill"
        while not self.stop_flag.is_set():
            t = bl.now_ns()
            sw, mig = sched_totals(self.pid)
            cj = cputime_jiffies(self.pid)
            rec = {"t_ns": t, "ctx": sw, "mig": mig, "cpu_j": cj,
                   "freq_p_khz": read_p_freq_khz(),
                   "cpu_busy": read_cpu_busy()}
            if prev is not None and cj is not None and prev["cpu_j"] is not None:
                cpu_s = (cj - prev["cpu_j"]) / HZ
                norm = ((sw - prev["ctx"]) / cpu_s) if cpu_s > 0 else 0.0
                rec["norm"] = norm
                if state == "prefill":
                    if norm > self.hi:
                        run_len += 1
                        if run_len >= self.k:
                            state = "decode"
                            self.switch_t_ns = t
                            self._snap_before = bl.sched_snapshot(self.pid)
                            if self.armed:
                                t0 = bl.now_ns()
                                okc, failc = set_affinity_all(
                                    self.pid, self.narrow_cpus)
                                self.switch_cost_us = (bl.now_ns() - t0) / 1000.0
                                self.switch_applied = {"ok": okc, "fail": failc}
                            run_len = 0
                    else:
                        run_len = 0
            # 200 ms after the switch, close the per-tid burst window. The
            # control arms take the same measurement at the same point, so
            # the switching arm's number can be compared against a baseline
            # rather than read in isolation.
            if (self._snap_before is not None and self._snap_after is None
                    and self.switch_t_ns is not None
                    and t >= self.switch_t_ns + 200e6):
                self._snap_after = bl.sched_snapshot(self.pid)
                self.burst = bl.sched_delta(self._snap_before,
                                            self._snap_after)
            self.samples.append(rec)
            prev = rec
            self.stop_flag.wait(self.interval_s)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--server-bin", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--prompt", required=True)
    p.add_argument("--arm", required=True,
                   choices=["A_P8", "C_P8_E8", "SWITCH", "STATIC"])
    # STATIC: ara kollar (P8+E2/E4/E6) için keyfi cpuset + thread sayısı.
    # Pareto cephesini çizmek iki uç noktayla yapılamaz.
    p.add_argument("--static-cpus", default="",
                   help="STATIC kolu için cpuset, ör. 0,2,4,6,8,10,12,14,16,17")
    p.add_argument("--static-threads", type=int, default=0)
    p.add_argument("--n-predict", type=int, default=256)
    p.add_argument("--interval-ms", type=float, default=20.0)
    p.add_argument("--hi", type=float, default=3000.0)
    p.add_argument("--lo", type=float, default=2100.0)
    p.add_argument("--k", type=int, default=2)
    p.add_argument("--port", type=int, default=8105)
    p.add_argument("--loadgen", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "loadgen"))
    p.add_argument("--load-threads", type=int, default=0)
    p.add_argument("--load-cpus", default="16-23")
    p.add_argument("--competitor", default="none",
                   choices=["none", "loadgen", "build"])
    # İŞ 3: soft priority without sched_ext. Both are ways of telling CFS
    # "this competitor matters less" -- the question is whether CFS turns
    # that into the *latency* priority the LLM needs, or only a throughput
    # share.
    p.add_argument("--load-nice", type=int, default=0)
    p.add_argument("--load-weight", type=int, default=0,
                   help="cgroup v2 cpu.weight for the competitor (0 = off)")
    # SCHED_IDLE is the strongest de-prioritisation Linux offers without
    # privileges: a waking normal thread preempts an idle-class one
    # immediately. That zeroes the wakeup-preemption component of the
    # residual, leaving only interference the scheduler cannot remove.
    p.add_argument("--load-sched-idle", action="store_true")
    p.add_argument("--build-dir", default="llama.cpp/build-compete")
    p.add_argument("--out", required=True)
    args = p.parse_args()

    if args.arm == "A_P8":
        cpus, t_dec, t_bat, armed = P8, 8, 8, False
    elif args.arm == "STATIC":
        cpus = [int(x) for x in args.static_cpus.split(",")]
        n = args.static_threads or len(cpus)
        t_dec = t_bat = n
        armed = False
    elif args.arm == "C_P8_E8":
        cpus, t_dec, t_bat, armed = P8E8, 16, 16, False
    else:
        # prefill: 16 threads across P+E ; decode: 8 threads, mask narrowed to P
        cpus, t_dec, t_bat, armed = P8E8, 8, 16, True

    cpu_str = ",".join(str(c) for c in cpus)
    cmd = ["taskset", "-c", cpu_str, args.server_bin, "-m", args.model,
           "-t", str(t_dec), "-tb", str(t_bat), "-c", "2048", "-b", "2048",
           "-ub", "512", "-np", "1", "--host", ro.HOST,
           "--port", str(args.port)]

    build = None
    load = start_load(args.loadgen, args.load_cpus,
                      args.load_threads if args.competitor == "loadgen" else 0,
                      args.out + ".load", args.load_nice, args.load_weight,
                      args.load_sched_idle)
    log = open(os.devnull, "wb")
    proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT,
                            start_new_session=True)
    load_stats = {}
    try:
        ro.wait_for_health(args.port, proc)
        ro.stream_completion(args.port, {
            "prompt": "Warmup.", "n_predict": 1, "temperature": 0,
            "stream": True, "cache_prompt": False})
        time.sleep(1.0)

        # Warmup may have left the mask narrowed on a previous iteration;
        # every run starts wide.
        set_affinity_all(proc.pid, cpus)

        prompt = open(args.prompt).read()
        sw0, mig0 = sched_totals(proc.pid)
        e0 = read_energy_uj()
        temp0 = bl.package_temp_c()

        switcher = PhaseSwitcher(proc.pid, args.hi, args.lo, args.k,
                                 args.interval_ms / 1000.0, P8, armed)
        switcher.start()
        time.sleep(0.3)

        # A realistic competitor: a clean C++ build. Unlike loadgen it
        # serialises at link steps and dependency joins and blocks on I/O,
        # so it leaves idle capacity behind -- the whole point, since İŞ 6's
        # saturating load made "no gain under contention" nearly tautological.
        # Unpinned on purpose: the Linux default, unlike İŞ 6's E-pinned load.
        #
        # Started here, after warmup, so its compile-heavy phase coincides
        # with the measured request. Work is scored by wall time to
        # completion, not object count: all 340 objects are produced in the
        # first ~15 s and the remaining ~25 s is linking, so an object
        # counter saturates before the window closes.
        build_t0 = None
        if args.competitor == "build":
            # Two passes: one clean build is ~17 s, shorter than the ~32 s
            # measured request, so a single pass would leave the second half
            # of decode uncontended and dilute the comparison.
            build_t0 = bl.now_ns()
            # U8: SCHED_IDLE tavsiyesi şimdiye kadar YALNIZCA sentetik
            # loadgen ile ölçüldü ama "arka plan işi" diye genelleniyor.
            # Gerçek bir build, loadgen'in aksine bloke olur ve fork eder;
            # chrt sarmalayıcısı make'in tüm alt süreçlerine miras kalır.
            # DÜZELTME: eskiden sabit 2 geçiş koşuluyordu ve build ~4 s
            # sürüyordu; ölçüm penceresi ise ~33 s. Yani rakip pencerenin
            # %87'sinde YOKTU ve "çekişmeli" senaryo aslında çekişmesizdi.
            # Ayrıca build.wait() istek bittikten SONRA çağrıldığı için
            # build_wall_s build'i değil isteğin süresini ölçüyordu (36
            # koşuda fark +0.10 s medyan). Şimdi build pencere boyunca
            # döngüde koşuyor ve iş metriği TAMAMLANAN GEÇİŞ SAYISI.
            idle = "chrt --idle 0 " if args.load_sched_idle else ""
            prog = args.out + ".passes"
            open(prog, "w").close()
            build = subprocess.Popen(
                ["sh", "-c",
                 f"while :; do find {args.build_dir} -name '*.o' -delete; "
                 f"{idle}make -C {args.build_dir} -j16 >/dev/null 2>&1 || "
                 f"exit 1; echo x >> {prog}; done"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True)
            time.sleep(2.0)

        t_sent, token_ts, _, _ = ro.stream_completion(args.port, {
            "prompt": prompt, "n_predict": args.n_predict,
            "temperature": 0.0, "seed": 42, "stream": True,
            "cache_prompt": False, "ignore_eos": True})

        switcher.stop_flag.set()
        switcher.join(timeout=5)
        e1 = read_energy_uj()
        temp1 = bl.package_temp_c()
        build_wall_s = build_passes = build_rate = None
        if build is not None:
            # Pencere kapandı: rakibi DURDUR ve o ana kadar bitirdiği
            # geçişleri say. Beklemek yanlış olurdu -- ölçülmek istenen
            # "build ne zaman biter" değil, "pencere boyunca ne kadar iş
            # yaptı".
            build_wall_s = round((bl.now_ns() - build_t0) / 1e9, 2)
            try:
                os.killpg(os.getpgid(build.pid), signal.SIGKILL)
                build.wait(timeout=30)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                pass
            try:
                with open(args.out + ".passes") as fh:
                    build_passes = sum(1 for _ in fh)
                build_rate = round(build_passes / build_wall_s, 4)
            except OSError:
                pass
            build = None
        sw1, mig1 = sched_totals(proc.pid)
    finally:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            proc.wait(timeout=20)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
        load_stats = stop_load(load)
        if build is not None:
            try:
                os.killpg(os.getpgid(build.pid), signal.SIGKILL)
                build.wait(timeout=10)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                pass
        log.close()

    itl = [(token_ts[i] - token_ts[i - 1]) / 1e6
           for i in range(1, len(token_ts))]
    s_itl = sorted(itl)
    ttft_ms = (token_ts[0] - t_sent) / 1e6
    energy_j = ((e1 - e0) / 1e6) if (e0 is not None and e1 is not None
                                    and e1 >= e0) else None

    out = {
        "arm": args.arm,
        "cpus": cpu_str,
        "threads_decode": t_dec,
        "threads_batch": t_bat,
        "armed": armed,
        "ttft_ms": round(ttft_ms, 2),
        "prefill_tps": None,
        "itl_p50_ms": round(bl.percentile(s_itl, 50), 3),
        "itl_p95_ms": round(bl.percentile(s_itl, 95), 3),
        "itl_p99_ms": round(bl.percentile(s_itl, 99), 3),
        "itl_max_ms": round(s_itl[-1], 3),
        "decode_tps": round((len(token_ts) - 1) /
                            ((token_ts[-1] - token_ts[0]) / 1e9), 3),
        "n_tokens": len(token_ts),
        "total_migrations": mig1 - mig0,
        "total_ctx_switches": sw1 - sw0,
        "energy_j": round(energy_j, 1) if energy_j else None,
        "j_per_token": round(energy_j / len(token_ts), 3) if energy_j else None,
        "temp_start_c": temp0,
        "temp_end_c": temp1,
        # switch diagnostics
        "switch_detected": switcher.switch_t_ns is not None,
        "switch_lead_ms": round((switcher.switch_t_ns - token_ts[0]) / 1e6, 1)
        if switcher.switch_t_ns else None,
        "switch_apply_cost_us": round(switcher.switch_cost_us, 1)
        if switcher.switch_cost_us else None,
        "switch_threads_moved": switcher.switch_applied,
        "migration_burst_200ms": (switcher.burst or {}).get("migrations"),
        "ctx_burst_200ms": (switcher.burst or {}).get("ctx_switches"),
        # first tokens after the boundary, where transition cost would show
        "itl_first10_ms": [round(v, 2) for v in itl[:10]],
        "token_ts_ns": token_ts,
        "samples": switcher.samples,
        "itl_tail_mean_ms": round(sum(itl[20:]) / len(itl[20:]), 3)
        if len(itl) > 20 else None,
        "competitor": args.competitor,
        "build_wall_s": build_wall_s,
        "build_passes": build_passes,
        "build_rate": build_rate,
        "load_threads": args.load_threads,
        "load_nice": args.load_nice,
        "load_weight": args.load_weight,
        "load_sched_idle": args.load_sched_idle,
        "load_cpus": args.load_cpus if args.load_threads else "none",
    }
    out.update(load_stats)
    with open(args.out, "w") as f:
        json.dump(out, f, indent=2)
    # Samples and token timestamps go to the file only; echoing them would
    # bury the summary in half a megabyte of telemetry.
    print(json.dumps({k: v for k, v in out.items()
                      if k not in ("samples", "token_ts_ns")}))


if __name__ == "__main__":
    main()
