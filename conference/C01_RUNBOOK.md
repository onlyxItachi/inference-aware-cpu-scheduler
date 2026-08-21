# TASK-C01 sensitivity-smoke runbook

The first checkpoint is a sensitivity smoke: two characterization runs at each
sampling interval and two low-overhead performance runs. Do not start the
six-run pilot until these outputs have been reviewed with ChatGPT. The runner
requires `--full-pilot-approved` before it accepts six runs.

The frozen C01 runtime configuration matches the historical SWITCH policy:

```text
decode:  threads=8
prefill: threads_batch=16
```

This smoke records stock, unpinned Linux behavior. The runner refuses to start
if `sched_ext` is active or if its parent process is restricted to fewer than
all online CPUs. It never changes scheduler, affinity, governor, or power
settings.

C01 characterizes the **composite observed behavior** of stock Linux scheduling
and whatever hardware guidance the current platform exposes. It does not
causally isolate Intel Thread Director/HFI. Such attribution would require a
separate hardware-guidance ablation.

Run the characterization and performance paths separately. Characterization
requires the existing diagnostic binary that emits `PHASE_MARK`; its latency
fields are explicitly perturbed and are not performance evidence. Performance
uses the normal binary and never starts the residency sampler.

Before each command, follow the repository's measurement hygiene: close
unintended background work, allow the machine to cool, and retain the generated
server logs and JSON files. The runner also waits 30 seconds after metadata/model
identity capture before the first request, then 30 seconds between requests.

## 1. Two-run characterization at 20 ms

```bash
python3 conference/experiments/c01_stock_scheduler.py characterize \
  --server-bin llama.cpp/build-diag/bin/llama-server \
  --model models/Qwen3.5-9B-Q4_K_M.gguf \
  --prompt harness/prompt_512.txt \
  --interval-ms 20 \
  --threads 8 \
  --threads-batch 16 \
  --ctx 2048 \
  --batch 2048 \
  --ubatch 512 \
  --n-predict 256 \
  --seed 42 \
  --port 8120 \
  --runs 2 \
  --initial-cooldown 30 \
  --cooldown 30 \
  --outdir results/conference_c01
```

## 2. Two-run characterization at 50 ms

```bash
python3 conference/experiments/c01_stock_scheduler.py characterize \
  --server-bin llama.cpp/build-diag/bin/llama-server \
  --model models/Qwen3.5-9B-Q4_K_M.gguf \
  --prompt harness/prompt_512.txt \
  --interval-ms 50 \
  --threads 8 \
  --threads-batch 16 \
  --ctx 2048 \
  --batch 2048 \
  --ubatch 512 \
  --n-predict 256 \
  --seed 42 \
  --port 8120 \
  --runs 2 \
  --initial-cooldown 30 \
  --cooldown 30 \
  --outdir results/conference_c01
```

## 3. Two-run low-overhead performance

```bash
python3 conference/experiments/c01_stock_scheduler.py performance \
  --server-bin llama.cpp/build/bin/llama-server \
  --model models/Qwen3.5-9B-Q4_K_M.gguf \
  --prompt harness/prompt_512.txt \
  --threads 8 \
  --threads-batch 16 \
  --ctx 2048 \
  --batch 2048 \
  --ubatch 512 \
  --n-predict 256 \
  --seed 42 \
  --port 8120 \
  --runs 2 \
  --initial-cooldown 30 \
  --cooldown 30 \
  --outdir results/conference_c01
```

## 4. Analysis

```bash
python3 conference/analysis/c01_analyze.py \
  --input results/conference_c01 \
  --reference P_ONLY=results/i14_frontier/i14.csv::arm=A_P8,scenario=none \
  --reference P_PLUS_E=results/i14_frontier/i14.csv::arm=C_P8_E8,scenario=none \
  --reference SWITCH=results/i14_frontier/i14.csv::arm=SWITCH,scenario=none
```

Optional historical P-only or P+E run-level CSV/JSON inputs can be attached
without rerunning the frontier:

```bash
python3 conference/analysis/c01_analyze.py \
  --input results/conference_c01 \
  --reference P_ONLY=path/to/runs.csv::arm=A_P8,scenario=none \
  --reference P_PLUS_E=path/to/runs.csv::arm=C_P8_E8,scenario=none \
  --reference SWITCH=path/to/runs.csv::arm=SWITCH,scenario=none
```

The analysis writes `summary.json` and `summary.md` under
`results/conference_c01/`. It reports observations such as phase-specific
P/E residency and transition counts; it does not make a Thread Director/HFI
or Linux success/failure judgment and cannot causally attribute an observation
to hardware guidance without a separate ablation.
