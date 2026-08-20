"""One measured inference run against a freshly started llama-server.

Why a fresh server per run: llama-server caches prompt prefixes across
requests. With a fixed prompt, run 2+ would hit that cache and TTFT would
collapse to near zero -- measuring the cache, not prefill. We both restart
the server and pass cache_prompt=false.

Why ignore_eos + temperature 0: every run must do *identical* work. Greedy
decoding with a forced token count makes the workload byte-for-byte
repeatable, so any spread across runs is machine noise, not sampling noise.
That is the whole point of Faz 0.
"""

import argparse
import http.client
import json
import os
import signal
import socket
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bench_lib as bl

HOST = "127.0.0.1"


def wait_for_health(port, proc, timeout_s=180):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"server exited early, rc={proc.returncode}")
        try:
            conn = http.client.HTTPConnection(HOST, port, timeout=2)
            conn.request("GET", "/health")
            resp = conn.getresponse()
            body = resp.read()
            conn.close()
            if resp.status == 200:
                return True
        except (OSError, http.client.HTTPException):
            pass
        time.sleep(0.25)
    raise RuntimeError("server did not become healthy in time")


def post_json(port, path, payload, timeout_s=600):
    conn = http.client.HTTPConnection(HOST, port, timeout=timeout_s)
    body = json.dumps(payload)
    conn.request("POST", path, body=body,
                 headers={"Content-Type": "application/json"})
    return conn


def tokenize(port, text):
    conn = post_json(port, "/tokenize", {"content": text})
    data = json.loads(conn.getresponse().read())
    conn.close()
    return len(data.get("tokens", []))


def stream_completion(port, payload):
    """Send a streaming request; timestamp every token as it arrives.

    Timestamps are taken the moment a chunk carrying non-empty content is
    parsed off the socket. Chunks with empty content (keepalives, the final
    stats frame) are not tokens and must not be counted.
    """
    conn = post_json(port, "/completion", payload)
    sock = conn.sock
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    t_sent = bl.now_ns()
    resp = conn.getresponse()
    if resp.status != 200:
        raise RuntimeError(f"HTTP {resp.status}: {resp.read()[:200]}")

    token_ts = []
    pieces = []
    final = None

    buf = b""
    while True:
        chunk = resp.read1(4096)
        if not chunk:
            break
        ts = bl.now_ns()
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            line = line.strip()
            if not line.startswith(b"data:"):
                continue
            raw = line[5:].strip()
            if not raw or raw == b"[DONE]":
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                continue
            content = obj.get("content", "")
            if content:
                token_ts.append(ts)
                pieces.append(content)
            if obj.get("stop"):
                final = obj
    conn.close()
    return t_sent, token_ts, "".join(pieces), final


def measure(args):
    prompt = open(args.prompt).read()

    cmd = []
    if args.cpus:
        cmd += ["taskset", "-c", args.cpus]
    # -t governs decode (generation), -tb governs prefill (batch). llama-server
    # wires these separately (common.cpp: cparams.n_threads /
    # n_threads_batch), so they are the one phase-aware knob the server
    # already exposes. Default -tb to -t unless asked otherwise.
    threads_batch = args.threads_batch if args.threads_batch > 0 else args.threads
    cmd += [
        args.server_bin,
        "-m", args.model,
        "-t", str(args.threads),
        "-tb", str(threads_batch),
        "-c", str(args.ctx),
        "-b", str(args.batch),
        "-ub", str(args.ubatch),
        "-np", "1",
        "--host", HOST,
        "--port", str(args.port),
    ]

    log = open(args.server_log, "wb")
    proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT,
                            start_new_session=True)
    try:
        wait_for_health(args.port, proc)
        prompt_tokens = tokenize(args.port, prompt)

        # Warmup on a *different* prompt: initialises allocators and compute
        # buffers without seeding the cache for the prompt we actually measure.
        warm = {"prompt": "Warmup.", "n_predict": 1, "temperature": 0,
                "stream": True, "cache_prompt": False}
        stream_completion(args.port, warm)
        time.sleep(1.0)

        payload = {
            "prompt": prompt,
            "n_predict": args.n_predict,
            "temperature": 0.0,
            "seed": args.seed,
            "stream": True,
            "cache_prompt": False,
            "ignore_eos": True,
        }

        temp_start = bl.package_temp_c()
        sched_before = bl.sched_snapshot(proc.pid)
        freq = bl.FreqSampler()
        freq.start()

        t_sent, token_ts, text, final = stream_completion(args.port, payload)

        freq.stop()
        sched_after = bl.sched_snapshot(proc.pid)
        temp_end = bl.package_temp_c()
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

    if len(token_ts) < 2:
        raise RuntimeError(f"got {len(token_ts)} tokens, expected {args.n_predict}")

    ttft_ms = (token_ts[0] - t_sent) / 1e6
    itl_ms = [(token_ts[i] - token_ts[i - 1]) / 1e6
              for i in range(1, len(token_ts))]
    itl_sorted = sorted(itl_ms)
    decode_span_s = (token_ts[-1] - token_ts[0]) / 1e9

    rec = {
        "ttft_ms": round(ttft_ms, 3),
        "itl_p50_ms": round(bl.percentile(itl_sorted, 50), 3),
        "itl_p95_ms": round(bl.percentile(itl_sorted, 95), 3),
        "itl_p99_ms": round(bl.percentile(itl_sorted, 99), 3),
        "itl_max_ms": round(itl_sorted[-1], 3),
        "itl_mean_ms": round(sum(itl_ms) / len(itl_ms), 3),
        "n_tokens": len(token_ts),
        "decode_tps": round((len(token_ts) - 1) / decode_span_s, 3)
        if decode_span_s > 0 else None,
        "prompt_tokens": prompt_tokens,
        "temp_start_c": temp_start,
        "temp_end_c": temp_end,
        "temp_delta_c": round(temp_end - temp_start, 2)
        if (temp_start is not None and temp_end is not None) else None,
    }
    rec.update(bl.sched_delta(sched_before, sched_after))
    rec.update(freq.summary())

    # Config echoed into every row so a CSV row is self-describing.
    rec.update({
        "threads": args.threads,
        "threads_batch": threads_batch,
        "cpus": args.cpus or "unpinned",
        "ctx": args.ctx,
        "batch": args.batch,
        "ubatch": args.ubatch,
        "seed": args.seed,
        "n_predict": args.n_predict,
    })

    if args.tokens_out:
        with open(args.tokens_out, "w") as f:
            json.dump({
                "t_sent_ns": t_sent,
                "token_ts_ns": token_ts,
                "itl_ms": [round(v, 4) for v in itl_ms],
                "text_sha_prefix": text[:80],
                "n_chars": len(text),
            }, f)

    return rec


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--server-bin", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--prompt", required=True)
    p.add_argument("--threads", type=int, default=8)
    p.add_argument("--threads-batch", type=int, default=0,
                   help="prefill thread count; 0 = same as --threads")
    p.add_argument("--cpus", default="")
    p.add_argument("--ctx", type=int, default=2048)
    p.add_argument("--batch", type=int, default=2048)
    p.add_argument("--ubatch", type=int, default=512)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--n-predict", type=int, default=256)
    p.add_argument("--port", type=int, default=8081)
    p.add_argument("--tokens-out", default="")
    p.add_argument("--server-log", default="/dev/null")
    args = p.parse_args()
    print(json.dumps(measure(args)))


if __name__ == "__main__":
    main()
