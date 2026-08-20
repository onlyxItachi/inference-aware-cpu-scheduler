"""İŞ 2 — H5 in the two conditions its earlier validation avoided.

2a CONTENTION: the earlier validation ran on an idle machine. A competitor
   generates its own context switches, which could raise the floor the
   detector's absolute threshold sits on. Two placements are tested because
   they stress the detector differently:
     B  LLM free, load free      -> load shares the LLM's cores
     D  LLM on P, load on E      -> load is elsewhere, but still busy

2b PROMPT LENGTH: the earlier validation used one 496-token prompt. Two
   things are at stake:
     - does detection survive when prefill is only ~0.4 s (32 tokens)?
     - is the -133 ms early warning FIXED, or does it scale with prefill
       length? If it scales, it is an artefact of batching (the final
       partial ubatch does more barriers per unit of compute), and the
       "early warning" claim must be withdrawn. n_batch/n_ubatch are
       recorded so this can be tested rather than argued.
"""

import argparse
import json
import os
import random
import signal
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
P_NOSMT = "0,2,4,6,8,10,12,14"


def start_load(loadgen, cpus, n, out_path):
    if not n:
        return None
    cmd = (["taskset", "-c", cpus] if cpus else []) + [loadgen, str(n)]
    fh = open(out_path, "w")
    proc = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.DEVNULL,
                            start_new_session=True)
    proc._fh = fh
    time.sleep(2.0)
    return proc


def stop_load(proc):
    if proc is None:
        return
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


def run_capture(args, prompt, cpus, out, ubatch=512):
    cmd = [sys.executable, os.path.join(HERE, "h5_capture.py"),
           "--server-bin", args.server_bin, "--model", args.model,
           "--prompt", prompt, "--cpus", cpus, "--threads", "8",
           "--n-predict", str(args.n_predict), "--interval-ms", "20",
           "--port", str(args.port), "--out", out]
    return subprocess.run(cmd, capture_output=True, text=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--server-bin", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--loadgen", default=os.path.join(HERE, "loadgen"))
    p.add_argument("--mode", choices=["contention", "promptlen"],
                   required=True)
    p.add_argument("--rounds", type=int, default=5)
    p.add_argument("--cooldown", type=int, default=30)
    p.add_argument("--n-predict", type=int, default=256)
    p.add_argument("--outdir", required=True)
    p.add_argument("--port", type=int, default=8100)
    p.add_argument("--order-seed", type=int, default=31)
    args = p.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    rng = random.Random(args.order_seed)

    if args.mode == "contention":
        # (name, llm_cpus, load_cpus, load_threads)
        arms = [
            ("B_both_free",  "",      "",      16),
            ("D_llmP_loadE", P_NOSMT, "16-23", 16),
        ]
        prompt = os.path.join(HERE, "prompt_512.txt")
    else:
        manifest = json.load(open(os.path.join(HERE, "prompts",
                                               "manifest.json")))
        arms = [(f"len{t}", P_NOSMT, None, 0) for t in sorted(
            manifest, key=lambda x: int(x))]
        prompts = {f"len{t}": manifest[t]["path"] for t in manifest}
        prompt = None

    seq = 0
    total = args.rounds * len(arms)
    t0all = time.time()
    print(f"[h5-{args.mode}] {args.rounds} tur x {len(arms)} kol = {total} koşu",
          flush=True)

    for rnd in range(1, args.rounds + 1):
        order = arms[:]
        rng.shuffle(order)
        print(f"\n=== tur {rnd}/{args.rounds} | "
              f"{' -> '.join(a for a, _, _, _ in order)}", flush=True)
        for name, llm_cpus, load_cpus, load_n in order:
            if seq > 0:
                time.sleep(args.cooldown)
            seq += 1
            tag = f"r{rnd:02d}_{name}"
            out = os.path.join(args.outdir, f"{tag}.json")
            pr_path = prompt if prompt else prompts[name]

            load = start_load(args.loadgen, load_cpus, load_n,
                              os.path.join(args.outdir, f"{tag}.load"))
            t0 = time.time()
            try:
                pr = run_capture(args, pr_path, llm_cpus, out)
            finally:
                stop_load(load)

            if pr.returncode != 0:
                print(f"  {name:14s} FAILED\n{pr.stderr[-700:]}", flush=True)
                continue
            d = json.load(open(out))
            eta = (time.time() - t0all) / seq * (total - seq) / 60
            print(f"  {name:14s} ttft={d['ttft_ms']:8.0f}ms  "
                  f"p50={d['itl_p50_ms']:6.2f}  tps={d['decode_tps']:5.2f}  "
                  f"({time.time() - t0:.0f}s, ETA {eta:.0f}m)", flush=True)

    print(f"\n[h5-{args.mode}] done -> {args.outdir}", flush=True)


if __name__ == "__main__":
    main()
