# TASK-C03 minimal generality smoke runbook

## Frozen selection

**SELECTED C03 PATH: `CROSS_VENDOR`**

C03 changes exactly one generality axis: the heterogeneous CPU
vendor/platform. It does not run the fallback model path in the same campaign.
The implementation can validate a future `FALLBACK_MODEL` configuration, but
that path is not selected or authorized by this runbook. Do not execute both
paths.

The first checkpoint is only two randomized rounds containing `BIG_ONLY` and
`ALL_CORES` once per round: four measured requests total. A six-round run is
not authorized and no full-run command is provided here.

## Required configuration review

Before running, fill in the four hardware-specific placeholders in the smoke
command after inspecting the second system:

- `<BIG_CPU_LIST>`: explicit Linux CPU list for the operationally faster core
  class, such as a comma/range expression.
- `<COMPACT_CPU_LIST>`: explicit, non-overlapping Linux CPU list for the other
  core class.
- `<BIG_THREAD_COUNT>`: runtime thread count for `BIG_ONLY`.
- `<ALL_THREAD_COUNT>`: runtime thread count for `ALL_CORES`.

`big` and `compact` are operational experiment labels supplied by this
configuration. They do not claim architectural equivalence to Intel P/E
cores. The runner records the exact masks and refuses overlapping, offline, or
disallowed CPUs.

Use the same diagnostic `llama-server` build, model, prompt, request length,
and runtime settings in both arms. The diagnostic build must emit
`PHASE_MARK batched=... t_mono_ns=...`. If the first internally marked
unbatched decode computation cannot be recovered, the runner stops and
preserves the failure/server log; do not substitute first-token arrival or a
weaker ground truth.

The live marker watcher is record-only in both arms. It labels detector samples
offline and never supplies a detector or placement decision. C03 applies only
the arm's initial static `taskset` mask; it contains no external, oracle,
dynamic-affinity, contention, stock, or sched_ext arm.

## Frozen zero-shot detector

The first smoke uses the unchanged Intel detector configuration:

```text
mode     = zero_shot
interval = 20 ms
hi       = 3000
lo       = 2100
k        = 2
```

This tests zero-shot threshold transfer separately from signal generality.
Changing any value while labeling the run `zero_shot` is rejected.
Recalibrated thresholds are a later, separately labeled inspection and are not
part of this smoke.

## Two-round CROSS_VENDOR smoke (only authorized benchmark command)

Replace the four angle-bracketed topology/thread values before execution:

```bash
python3 conference/experiments/c03_generality.py \
  --path CROSS_VENDOR \
  --big-cpus '<BIG_CPU_LIST>' \
  --compact-cpus '<COMPACT_CPU_LIST>' \
  --threads-big <BIG_THREAD_COUNT> \
  --threads-all <ALL_THREAD_COUNT> \
  --server-bin llama.cpp/build-diag/bin/llama-server \
  --model models/Qwen3.5-9B-Q4_K_M.gguf \
  --prompt harness/prompt_512.txt \
  --rounds 2 \
  --order-seed 3304 \
  --detector-mode zero_shot \
  --interval-ms 20 \
  --hi 3000 \
  --lo 2100 \
  --k 2 \
  --ctx 2048 \
  --batch 2048 \
  --ubatch 512 \
  --n-predict 256 \
  --seed 42 \
  --port 8140 \
  --initial-cooldown 30 \
  --cooldown 30 \
  --outdir results/conference_c03
```

If execution is interrupted, repeat the identical command with `--resume`.
The persisted plan must match exactly; completed run JSON files are skipped and
never overwritten.

## Analysis after all four runs

```bash
python3 conference/analysis/c03_analyze.py \
  --input results/conference_c03
```

The analyzer writes `c03_runs.csv`, `signal_summary.csv`, `summary.json`, and
`summary.md`. It reports `ALL_CORES` minus `BIG_ONLY`, phase-labeled raw signal
distributions, range overlap/separation observations, unchanged-threshold
transition counts, and detection timing relative to the first internally
marked unbatched decode computation. It does not declare that a phenomenon
generalizes and does not perform C05-level inference.

## Artifacts

Raw evidence remains separate under:

```text
results/conference_c03/raw/
  environment/
  plan.json
  runs/
  detector/
  phase_logs/
  server_logs/
```

Derived/index artifacts are:

```text
results/conference_c03/c03_runs.csv
results/conference_c03/signal_summary.csv
results/conference_c03/summary.json
results/conference_c03/summary.md
```

Bring the raw detector traces, phase logs, summary files, failure directory if
present, exact topology configuration, and machine-state metadata to the C03
checkpoint review. Do not start C04 from this runbook.
