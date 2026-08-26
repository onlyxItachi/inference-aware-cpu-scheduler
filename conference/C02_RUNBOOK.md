# TASK-C02 smoke runbook

Run this only after implementation review. The authorized first execution is
two randomized rounds containing all five arms once per round: 10 runs total.
Do not run six rounds until the smoke artifacts have been analyzed with
ChatGPT and explicit full-pilot approval has been given.

## What this experiment isolates

All five arms use the same diagnostic `llama-server` build, model, prompt,
measurement path, cooldown policy, `/proc` observation loop, and live
`PHASE_MARK` watcher.

| arm | `-t` | `-tb` | initial placement | action | `phase_source` |
|---|---:|---:|---|---|---|
| STOCK | 8 | 16 | unpinned | none | `none` |
| STATIC_P | 8 | 8 | physical P8 | none | `none` |
| STATIC_PE | 16 | 16 | physical P8 + E8 | none | `none` |
| EXTERNAL | 8 | 16 | physical P8 + E8 | narrow to P8 | `external_proc` |
| ORACLE | 8 | 16 | physical P8 + E8 | narrow to P8 | `internal_oracle` |

EXTERNAL and ORACLE call the same userspace `os.sched_setaffinity` actuator on
the same thread set. They differ only in the phase-transition source. EXTERNAL
is armed only from the normalized `/proc` context-switch detector. ORACLE runs
that detector observation-only and is armed from `PHASE_MARK`.

The diagnostic marker is present in every arm because every arm uses the same
binary. The same live watcher observes and records it in STOCK, STATIC_P,
STATIC_PE, EXTERNAL, and ORACLE. Only ORACLE routes the observed marker to the
affinity actuator. STOCK and both STATIC arms can only record it; EXTERNAL can
only use it as offline ground truth, while its scheduling decision comes
exclusively from the `/proc` detector. This diagnostic binary must not be
described as a literally unmodified inference engine; the external policy
itself consumes no application-provided phase signal.

The marker's embedded `CLOCK_MONOTONIC` timestamp is recorded as
`t_internal_phase_ns`. The watcher's local observation/parsing time is recorded
separately as `t_marker_seen_ns`; their difference is
`marker_delivery_latency_ms`. These timestamps must not be conflated.

C02 measures the composite stock Linux scheduling stack. It does not causally
isolate Intel Thread Director/HFI.

## Prerequisites and machine hygiene

- Use `llama.cpp/build-diag/bin/llama-server`, which emits `PHASE_MARK`.
- Keep `sched_ext` disabled and invoke the runner without a parent taskset or
  cpuset restriction. The runner checks these conditions and never changes
  them.
- Close unintended background work and let the machine cool before starting.
- Do not change the governor, EPP, turbo state, or power profile between runs.
- Ensure TCP port 8130 is free.
- The topology is obtained through the validated `thread_residency` helper.
  On the current machine it resolves to one logical CPU from each of eight
  physical P cores plus all eight E cores.

The default detector settings preserve the validated external policy:
20 ms sampling, normalized context-switch thresholds `hi=3000`, `lo=2100`,
and two consecutive samples. The same monitor and live marker watcher run in
all arms. The per-run metadata records whether the marker is record-only or is
routed to the actuator; only ORACLE may record the latter. The runner rejects
other detector intervals for this frozen C02 protocol; C01's 50 ms
characterization interval is not used here.

## 1. Execute the authorized two-round smoke

```bash
python3 conference/experiments/c02_external_oracle.py \
  --server-bin llama.cpp/build-diag/bin/llama-server \
  --model models/Qwen3.5-9B-Q4_K_M.gguf \
  --prompt harness/prompt_512.txt \
  --rounds 2 \
  --order-seed 2202 \
  --interval-ms 20 \
  --hi 3000 \
  --lo 2100 \
  --k 2 \
  --ctx 2048 \
  --batch 2048 \
  --ubatch 512 \
  --n-predict 256 \
  --seed 42 \
  --port 8130 \
  --initial-cooldown 30 \
  --cooldown 30 \
  --outdir results/conference_c02
```

If an interrupted smoke is resumed, use the identical command with
`--resume`. Existing successful raw runs are skipped and never overwritten.
The persisted `raw/plan.json` prevents changing the seed, arm configuration,
or round order during a resume.

The six-round pilot is gated in the runner and requires explicit approval
after smoke analysis. No six-round command is provided at this checkpoint.

## 2. Analyze the smoke

```bash
python3 conference/analysis/c02_analyze.py \
  --input results/conference_c02
```

The analyzer reports observations and recovery ratios without declaring the
research gate PASS or FAIL. Bring `summary.json`, `summary.md`, `c02_runs.csv`,
the failure directory if present, and at least one ORACLE phase log to ChatGPT.

## Artifacts

Raw, immutable evidence is written under:

```text
results/conference_c02/raw/
  environment/
  plan.json
  runs/
  tokens/
  server_logs/
  phase_logs/
```

Derived/index artifacts are:

```text
results/conference_c02/c02_runs.csv
results/conference_c02/summary.json
results/conference_c02/summary.md
```

Each run records both thread counts, phase source, round and randomized order,
`t_internal_phase_ns`, `t_marker_seen_ns`, `t_external_detect_ns`, affinity
start/end timestamps, token timestamps, affinity-call timing and TID counts,
migrations/context switches, temperatures, frequency summaries, and read-only
thermal-throttle counters when the kernel exposes them.

## Smoke review questions

Review, without automatic PASS/FAIL classification:

1. Is one diagnostic build hash present across all arms?
2. Does contemporaneous STOCK retain the low-TTFT/worse-decode pattern?
3. Did EXTERNAL switch successfully in both runs?
4. Was marker-delivery latency stable across all five arms, and did ORACLE
   actuation align with the embedded internal boundary?
5. What is EXTERNAL's detection/action timing error relative to that boundary?
6. Are EXTERNAL and ORACLE close enough to authorize six rounds?
7. Do temperature ranges or throttle-counter changes identify a confounded arm?
