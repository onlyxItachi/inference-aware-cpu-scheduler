"""Shared measurement primitives for Faz 0.

Stdlib only, on purpose: the harness must stay reproducible without a
package environment, and must not perturb the machine it measures.

System counters are read from /proc and /sys rather than perf:
  - per-thread migrations  -> /proc/<pid>/task/<tid>/sched : se.nr_migrations
  - per-thread ctx switches-> /proc/<pid>/task/<tid>/sched : nr_switches
This needs no root, adds no tracing overhead, and is per-thread rather
than per-process, which is what the phase hypotheses will eventually need.
"""

import glob
import os
import re
import threading
import time

# ---------------------------------------------------------------- topology

# CLAUDE.md: CPU 0-15 = P-cores (SMT), CPU 16-23 = E-cores (no SMT).
P_CORES_ALL = list(range(0, 16))
P_CORES_NOSMT = [0, 2, 4, 6, 8, 10, 12, 14]
E_CORES = list(range(16, 24))


def _read_int(path):
    try:
        with open(path) as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------- thermals

def find_package_temp_path():
    """Locate the coretemp 'Package id 0' input by label.

    hwmon numbering is not stable across reboots, so never hardcode it.
    """
    for label_path in glob.glob("/sys/class/hwmon/hwmon*/temp*_label"):
        hwmon_dir = os.path.dirname(label_path)
        name = ""
        try:
            with open(os.path.join(hwmon_dir, "name")) as f:
                name = f.read().strip()
        except OSError:
            continue
        if name != "coretemp":
            continue
        try:
            with open(label_path) as f:
                if f.read().strip() == "Package id 0":
                    return label_path.replace("_label", "_input")
        except OSError:
            continue
    return None


PKG_TEMP_PATH = find_package_temp_path()


def package_temp_c():
    if PKG_TEMP_PATH is None:
        return None
    raw = _read_int(PKG_TEMP_PATH)
    return None if raw is None else raw / 1000.0


# ---------------------------------------------------------------- frequency

def _cpu_index(path):
    # "/cpu" appears twice in these paths (.../system/cpu/cpu0/...), so match
    # the numbered component explicitly rather than splitting on it.
    return int(re.search(r"/cpu(\d+)/", path).group(1))


_FREQ_PATHS = sorted(
    glob.glob("/sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_cur_freq"),
    key=_cpu_index,
)


class FreqSampler:
    """Samples per-CPU frequency in a background thread.

    Reports P-core and E-core averages separately: on a hybrid part a single
    system-wide average is meaningless, since idle E-cores drag it down.
    """

    def __init__(self, interval_s=0.25, busy_n=8):
        self.interval_s = interval_s
        self.busy_n = busy_n
        self._stop = threading.Event()
        self._thread = None
        self._p_samples = []
        self._p_busy_samples = []
        self._e_samples = []
        self._p_paths = [p for p in _FREQ_PATHS if _cpu_index(p) < 16]
        self._e_paths = [p for p in _FREQ_PATHS if _cpu_index(p) >= 16]

    def _loop(self):
        while not self._stop.is_set():
            for paths, sink in ((self._p_paths, self._p_samples),
                                (self._e_paths, self._e_samples)):
                vals = [v for v in (_read_int(p) for p in paths) if v]
                if vals:
                    sink.append(sum(vals) / len(vals) / 1000.0)  # MHz
            # A plain average over all P-cores is diluted by idle ones: with
            # -t 8 only half the logical P-cores are busy, and idle cores sit
            # at 800 MHz. The mean of the top-N tracks the cores actually
            # running the workload, which is what the boost/thermal question
            # is about.
            busy = [v for v in (_read_int(p) for p in self._p_paths) if v]
            if busy:
                top = sorted(busy, reverse=True)[:self.busy_n]
                self._p_busy_samples.append(sum(top) / len(top) / 1000.0)
            self._stop.wait(self.interval_s)

    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def summary(self):
        def avg(xs):
            return round(sum(xs) / len(xs), 1) if xs else None
        return {
            "freq_p_avg_mhz": avg(self._p_samples),
            "freq_p_busy_mhz": avg(self._p_busy_samples),
            "freq_e_avg_mhz": avg(self._e_samples),
            "freq_samples": len(self._p_samples),
        }


# ------------------------------------------------------------ sched counters

def sched_snapshot(pid):
    """tid -> (nr_migrations, nr_switches) for every thread of pid."""
    snap = {}
    for task_dir in glob.glob(f"/proc/{pid}/task/*/sched"):
        tid = int(task_dir.split("/task/")[1].split("/")[0])
        mig = sw = None
        try:
            with open(task_dir) as f:
                for line in f:
                    if line.startswith("se.nr_migrations"):
                        mig = int(line.split(":")[1].strip())
                    elif line.startswith("nr_switches"):
                        sw = int(line.split(":")[1].strip())
                    if mig is not None and sw is not None:
                        break
        except (OSError, ValueError):
            continue
        if mig is not None and sw is not None:
            snap[tid] = (mig, sw)
    return snap


def sched_delta(before, after):
    """Counter growth between two snapshots.

    Threads created mid-window count from zero; threads that exited are
    dropped, since their final counts are no longer readable.
    """
    d_mig = d_sw = 0
    for tid, (mig, sw) in after.items():
        b_mig, b_sw = before.get(tid, (0, 0))
        d_mig += mig - b_mig
        d_sw += sw - b_sw
    return {
        "migrations": d_mig,
        "ctx_switches": d_sw,
        "threads_seen": len(after),
    }


# ---------------------------------------------------------------- statistics

def percentile(sorted_vals, q):
    """Linear-interpolated percentile. q in [0,100]. Input must be sorted."""
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = (len(sorted_vals) - 1) * (q / 100.0)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = pos - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def describe(vals):
    """median / mean / std / min / max / CV% for a sample."""
    if not vals:
        return {}
    s = sorted(vals)
    n = len(s)
    mean = sum(s) / n
    var = sum((v - mean) ** 2 for v in s) / (n - 1) if n > 1 else 0.0
    std = var ** 0.5
    return {
        "n": n,
        "median": percentile(s, 50),
        "mean": mean,
        "std": std,
        "min": s[0],
        "max": s[-1],
        "cv_pct": (std / mean * 100.0) if mean else None,
    }


def now_ns():
    return time.perf_counter_ns()
