"""İŞ 2 — is decode limited by memory bandwidth or by synchronisation?

K1 showed decode scaling to 8 cores at only 49% efficiency, consistent with
a bandwidth ceiling but equally consistent with OpenMP barrier cost. This
separates them without downloading a second model:

  A  one instance,  8 threads on 8 physical P-cores
  B  two instances, 4 threads each, on disjoint sets of 4 physical P-cores

Both arms use the same 8 cores and stream the same weights. What differs is
the synchronisation structure: A has one 8-way barrier per layer, B has two
independent 4-way barriers.

  total throughput unchanged  -> the wall is memory bandwidth
  total throughput rises      -> the wall was synchronisation
                                 (two small barriers beat one big one)

Both instances must decode *concurrently* for the comparison to be honest,
so requests are fired from threads and the overlap is recorded.

Note on memory: llama.cpp mmaps the weights, so both instances share the
same physical pages. That is what we want -- the two arms then differ in
synchronisation, not in how much distinct data must be resident.
"""

import argparse
import csv
import json
import os
import random
import signal
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bench_lib as bl
import run_once as ro

HERE = os.path.dirname(os.path.abspath(__file__))

# (arm, [(cpus, threads, port), ...])
ARMS = [
    ("A_single_8t", [("0,2,4,6,8,10,12,14", 8, 8091)]),
    ("B_dual_4t",   [("0,2,4,6", 4, 8092), ("8,10,12,14", 4, 8093)]),
]

FIELDS = [
    "arm", "round", "timestamp", "n_instances", "total_decode_tps",
    "inst_tps", "inst_ttft_ms", "inst_itl_p50_ms", "overlap_pct",
    "total_migrations", "total_ctx_switches", "temp_start_c", "temp_end_c",
    "energy_j", "wall_s",
]


def launch(server_bin, model, cpus, threads, port):
    cmd = ["taskset", "-c", cpus, server_bin, "-m", model,
           "-t", str(threads), "-tb", str(threads), "-c", "2048",
           "-b", "2048", "-ub", "512", "-np", "1",
           "--host", ro.HOST, "--port", str(port)]
    log = open(os.devnull, "wb")
    proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT,
                            start_new_session=True)
    proc._log = log
    return proc


def kill(proc):
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        proc.wait(timeout=20)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        proc._log.close()
    except Exception:
        pass


def read_energy():
    for p in ("/sys/class/powercap/intel-rapl:0/energy_uj",
              "/sys/class/powercap/intel-rapl:0/intel-rapl:0:0/energy_uj"):
        try:
            with open(p) as f:
                return int(f.read().strip())
        except OSError:
            continue
    return None


def run_arm(args, spec):
    procs = []
    try:
        for cpus, threads, port in spec:
            procs.append(launch(args.server_bin, args.model, cpus, threads,
                                port))
        for proc, (_, _, port) in zip(procs, spec):
            ro.wait_for_health(port, proc)
        # warm each instance on a different prompt
        for _, _, port in spec:
            ro.stream_completion(port, {
                "prompt": "Warmup.", "n_predict": 1, "temperature": 0,
                "stream": True, "cache_prompt": False})
        time.sleep(1.5)

        prompt = open(args.prompt).read()
        payload = {"prompt": prompt, "n_predict": args.n_predict,
                   "temperature": 0.0, "seed": 42, "stream": True,
                   "cache_prompt": False, "ignore_eos": True}

        results = [None] * len(spec)
        sched_before = [bl.sched_snapshot(p.pid) for p in procs]
        temp0 = bl.package_temp_c()
        e0 = read_energy()

        barrier = threading.Barrier(len(spec))

        def worker(i, port):
            barrier.wait()  # fire together
            results[i] = ro.stream_completion(port, payload)

        t_wall0 = bl.now_ns()
        threads_ = [threading.Thread(target=worker, args=(i, port))
                    for i, (_, _, port) in enumerate(spec)]
        for t in threads_:
            t.start()
        for t in threads_:
            t.join()
        t_wall1 = bl.now_ns()

        e1 = read_energy()
        temp1 = bl.package_temp_c()
        sched_after = [bl.sched_snapshot(p.pid) for p in procs]
    finally:
        for proc in procs:
            kill(proc)

    per_inst = []
    decode_windows = []
    for (t_sent, token_ts, _, _) in results:
        itl = [(token_ts[i] - token_ts[i - 1]) / 1e6
               for i in range(1, len(token_ts))]
        span_s = (token_ts[-1] - token_ts[0]) / 1e9
        per_inst.append({
            "tps": (len(token_ts) - 1) / span_s,
            "ttft_ms": (t_sent and (token_ts[0] - t_sent) / 1e6),
            "itl_p50_ms": sorted(itl)[len(itl) // 2],
        })
        decode_windows.append((token_ts[0], token_ts[-1]))

    # How much of the decode phases actually overlapped. If this is low the
    # comparison is invalid -- the instances took turns instead of competing.
    if len(decode_windows) > 1:
        lo = max(w[0] for w in decode_windows)
        hi = min(w[1] for w in decode_windows)
        overlap = max(0, hi - lo)
        shortest = min(w[1] - w[0] for w in decode_windows)
        overlap_pct = overlap / shortest * 100 if shortest else 0
    else:
        overlap_pct = 100.0

    d_mig = d_sw = 0
    for before, after in zip(sched_before, sched_after):
        d = bl.sched_delta(before, after)
        d_mig += d["migrations"]
        d_sw += d["ctx_switches"]

    energy_j = ((e1 - e0) / 1e6) if (e0 is not None and e1 is not None
                                     and e1 >= e0) else None

    return {
        "n_instances": len(spec),
        "total_decode_tps": sum(x["tps"] for x in per_inst),
        "inst_tps": json.dumps([round(x["tps"], 3) for x in per_inst]),
        "inst_ttft_ms": json.dumps([round(x["ttft_ms"], 1) for x in per_inst]),
        "inst_itl_p50_ms": json.dumps(
            [round(x["itl_p50_ms"], 2) for x in per_inst]),
        "overlap_pct": round(overlap_pct, 1),
        "total_migrations": d_mig,
        "total_ctx_switches": d_sw,
        "temp_start_c": temp0,
        "temp_end_c": temp1,
        "energy_j": round(energy_j, 1) if energy_j else None,
        "wall_s": round((t_wall1 - t_wall0) / 1e9, 2),
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--server-bin", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--prompt", default=os.path.join(HERE, "prompt_512.txt"))
    p.add_argument("--rounds", type=int, default=6)
    p.add_argument("--cooldown", type=int, default=30)
    p.add_argument("--n-predict", type=int, default=256)
    p.add_argument("--outdir", required=True)
    p.add_argument("--order-seed", type=int, default=11)
    args = p.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    csv_path = os.path.join(args.outdir, "i2.csv")
    new = not os.path.exists(csv_path)
    f = open(csv_path, "a", newline="")
    w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
    if new:
        w.writeheader()
        f.flush()

    rng = random.Random(args.order_seed)
    seq = 0
    total = args.rounds * len(ARMS)
    t0all = time.time()
    print(f"[i2] {args.rounds} rounds x {len(ARMS)} arms = {total} runs",
          flush=True)

    for rnd in range(1, args.rounds + 1):
        order = ARMS[:]
        rng.shuffle(order)
        print(f"\n=== round {rnd}/{args.rounds} | "
              f"{' -> '.join(a for a, _ in order)}", flush=True)
        for name, spec in order:
            if seq > 0:
                time.sleep(args.cooldown)
            seq += 1
            t0 = time.time()
            try:
                rec = run_arm(args, spec)
            except Exception as exc:
                print(f"  {name:12s} FAILED: {exc}", flush=True)
                continue
            rec.update({"arm": name, "round": rnd,
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")})
            w.writerow(rec)
            f.flush()
            eta = (time.time() - t0all) / seq * (total - seq) / 60
            print(f"  {name:12s} TOPLAM tps={rec['total_decode_tps']:6.2f}  "
                  f"örnekler={rec['inst_tps']}  "
                  f"örtüşme={rec['overlap_pct']:.0f}%  "
                  f"E={rec['energy_j']}J  "
                  f"({time.time() - t0:.0f}s, ETA {eta:.0f}m)", flush=True)
    f.close()
    print(f"\n[i2] done -> {csv_path}", flush=True)


if __name__ == "__main__":
    main()
