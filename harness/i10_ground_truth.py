"""İŞ 2 — is the detector's "-135 ms early warning" real, or a ground-truth artefact?

The project's most striking claim is that the phase detector fires ~135 ms
*before* the boundary. But "the boundary" was defined as the first token's
arrival at the HTTP client, and llama.cpp starts decoding before that: the
token still has to be sampled, detokenised, serialised into SSE and pushed
through a socket. A 26.7 ms client lag was measured against the server's own
`prompt eval time`, but that number is llama.cpp's own accounting and it is
not obvious where it puts the final layer and logits.

This compares four instants on one timeline:

  t_internal   first graph_compute(batched=false)  -- the real boundary,
                 from the diagnostic build's PHASE_MARK (CLOCK_MONOTONIC)
  t_prompt_eval  server's own prompt-eval completion, from its log
  t_first_token  client-side arrival (the old ground truth)
  t_detect       when the detector said "decode"

Python's perf_counter uses CLOCK_MONOTONIC on Linux, so PHASE_MARK and the
harness timestamps share a clock without conversion.

Reading:
  t_internal ~135 ms before t_first_token -> the "early warning" is an
      artefact of where ground truth was placed. The detector is on time,
      not early; the claim is withdrawn and the early-placement hypothesis
      built on it falls with it.
  t_internal near t_first_token -> the early warning is real, the mechanism
      stays open, and early placement remains a live hypothesis.
"""

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bench_lib as bl
import run_once as ro
from phase_switch import PhaseSwitcher, P8

MARK_RE = re.compile(r"PHASE_MARK batched=(\d+) t_mono_ns=(\d+)")
EVAL_RE = re.compile(r"prompt eval time\s*=\s*([\d.]+) ms")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--server-bin", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--prompt", required=True)
    p.add_argument("--n-predict", type=int, default=128)
    p.add_argument("--port", type=int, default=8110)
    p.add_argument("--out", required=True)
    args = p.parse_args()

    cpu_str = ",".join(str(c) for c in P8)
    cmd = ["taskset", "-c", cpu_str, args.server_bin, "-m", args.model,
           "-t", "8", "-tb", "8", "-c", "2048", "-b", "2048", "-ub", "512",
           "-np", "1", "--host", ro.HOST, "--port", str(args.port)]

    log_path = args.out + ".serverlog"
    log = open(log_path, "wb")
    proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT,
                            start_new_session=True)
    try:
        ro.wait_for_health(args.port, proc)
        ro.stream_completion(args.port, {
            "prompt": "Warmup.", "n_predict": 1, "temperature": 0,
            "stream": True, "cache_prompt": False})
        time.sleep(1.0)
        log.flush()
        # Everything logged so far belongs to startup and warmup; only marks
        # emitted after this offset can belong to the measured request.
        warmup_offset = os.path.getsize(log_path)

        prompt = open(args.prompt).read()
        switcher = PhaseSwitcher(proc.pid, 3000.0, 2100.0, 2, 0.020, P8, False)
        switcher.start()
        time.sleep(0.3)

        t_sent, token_ts, _, _ = ro.stream_completion(args.port, {
            "prompt": prompt, "n_predict": args.n_predict,
            "temperature": 0.0, "seed": 42, "stream": True,
            "cache_prompt": False, "ignore_eos": True})

        switcher.stop_flag.set()
        switcher.join(timeout=5)
        time.sleep(0.5)
        log.flush()
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

    with open(log_path, "rb") as f:
        f.seek(warmup_offset)
        tail = f.read().decode("utf-8", "replace")

    marks = [(int(b), int(t)) for b, t in MARK_RE.findall(tail)]
    # The measured request runs prefill (batched=1) then decode (batched=0).
    # The boundary is the first batched=0 mark at or after the request start.
    t_internal = None
    for batched, t in marks:
        if batched == 0 and t >= t_sent:
            t_internal = t
            break

    evals = [float(x) for x in EVAL_RE.findall(tail)]
    t_first = token_ts[0]

    out = {
        "t_sent_ns": t_sent,
        "t_internal_ns": t_internal,
        "t_first_token_ns": t_first,
        "t_detect_ns": switcher.switch_t_ns,
        "prompt_eval_ms": evals[-1] if evals else None,
        "ttft_ms": (t_first - t_sent) / 1e6,
        # positive => internal boundary happened BEFORE the client saw a token
        "internal_before_first_token_ms":
            ((t_first - t_internal) / 1e6) if t_internal else None,
        "detect_vs_first_token_ms":
            ((switcher.switch_t_ns - t_first) / 1e6)
            if switcher.switch_t_ns else None,
        "detect_vs_internal_ms":
            ((switcher.switch_t_ns - t_internal) / 1e6)
            if (switcher.switch_t_ns and t_internal) else None,
        "n_marks": len(marks),
        "n_tokens": len(token_ts),
    }
    with open(args.out, "w") as f:
        json.dump(out, f, indent=2)
    print(json.dumps(out))


if __name__ == "__main__":
    main()
