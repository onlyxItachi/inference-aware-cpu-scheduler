"""Generate prompts at exact target token counts, using the model's own tokenizer.

Token counts must be measured, not estimated: a word-count heuristic would
leave the prompt-length sweep confounded by however far each prompt drifted
from its nominal size.
"""

import argparse
import http.client
import json
import os
import signal
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_once as ro

HERE = os.path.dirname(os.path.abspath(__file__))

BASE = open(os.path.join(HERE, "prompt_512.txt")).read()
# Enough material to reach the longest target.
CORPUS = (BASE + "\n\n") * 6


def tokenize(port, text):
    conn = http.client.HTTPConnection(ro.HOST, port, timeout=60)
    conn.request("POST", "/tokenize", body=json.dumps({"content": text}),
                 headers={"Content-Type": "application/json"})
    n = len(json.loads(conn.getresponse().read()).get("tokens", []))
    conn.close()
    return n


def fit(port, target, tol=3):
    """Binary search on character count to land within tol tokens of target."""
    lo, hi = 1, len(CORPUS)
    best = None
    for _ in range(40):
        mid = (lo + hi) // 2
        text = CORPUS[:mid]
        n = tokenize(port, text)
        if best is None or abs(n - target) < abs(best[1] - target):
            best = (text, n)
        if abs(n - target) <= tol:
            break
        if n < target:
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--server-bin", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--targets", default="32,128,256,496,1024")
    p.add_argument("--outdir", required=True)
    p.add_argument("--port", type=int, default=8099)
    args = p.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    cmd = [args.server_bin, "-m", args.model, "-t", "8", "-c", "4096",
           "--host", ro.HOST, "--port", str(args.port)]
    log = open(os.devnull, "wb")
    proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT,
                            start_new_session=True)
    manifest = {}
    try:
        ro.wait_for_health(args.port, proc)
        for t in [int(x) for x in args.targets.split(",")]:
            text, n = fit(args.port, t)
            path = os.path.join(args.outdir, f"prompt_{t}.txt")
            with open(path, "w") as f:
                f.write(text)
            manifest[t] = {"path": path, "actual_tokens": n,
                           "chars": len(text)}
            print(f"hedef {t:5d} -> gerçek {n:5d} token ({len(text)} karakter)")
    finally:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            proc.wait(timeout=20)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
        log.close()

    with open(os.path.join(args.outdir, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)


if __name__ == "__main__":
    main()
