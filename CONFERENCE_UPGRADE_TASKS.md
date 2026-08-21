# Conference Upgrade Master Plan
## inference-aware-cpu-scheduler

**Repository:** `Fetiiii/inference-aware-cpu-scheduler`  
**Purpose:** Upgrade the current research artifact into a defensible main-conference-quality paper **without turning the project into a 4–5 month research program**.

---

## 0. Operating principle

This file is the **forward-looking authority** for the conference-upgrade phase.

Historical files such as:

- `PAPER.md`
- `RAPOR_FINAL.md`
- `RAPOR.md`
- `RAPOR_FAZ*.md`
- `MAKALE_ISKELET.md`

must remain as historical records. Old results should not be silently rewritten to fit the new story.

The research workflow is deliberately gated:

> **Implement one TASK → run the required experiment(s) → collect artifacts → STOP → analyze the outputs with ChatGPT → decide whether the next TASK still makes sense.**

Codex is the implementation agent. It must **not** decide novelty, reinterpret results, broaden scope, or launch the next task automatically.

---

# 1. Frozen research position

The conference-upgrade phase must use the following scientific position unless a later checkpoint explicitly changes it.

## 1.1 Claims that are NOT treated as novelty

The paper must not claim novelty for any of the following by themselves:

1. Prefill and decode are different workloads.
2. Hybrid P/E cores have different performance characteristics.
3. Hybrid-core LLM inference can suffer from load imbalance / slow-worker effects.
4. Runtime-internal policies can use different execution plans for prefill and decode.
5. Generic program phases can be detected and used for scheduling.

These are background / prior-art territory.

## 1.2 Candidate central contribution

The strongest candidate contribution is:

> **An unmodified CPU LLM inference runtime exposes enough OS-visible behavior to recover its request-level phase transition externally, and that externally recovered phase information is sufficiently accurate and timely to drive useful phase-aware CPU placement without inference-engine cooperation.**

The project should therefore be judged primarily on:

- external observability,
- policy usefulness,
- comparison with an application-informed oracle,
- comparison with stock hardware-guided scheduling,
- generality / scope boundaries.

## 1.3 Current research questions

**RQ1 — Placement inversion**  
Does optimal CPU placement change across prefill and decode on heterogeneous CPUs?

**RQ2 — Mechanism**  
What hardware/runtime effects explain the inversion?

**RQ3 — External observability**  
Can the phase transition be recovered outside the inference engine?

**RQ4 — Actionability**  
Does externally recovered phase information produce a useful scheduling policy, and how close is it to perfect phase knowledge?

**RQ5 — Generality**  
Is the result specific to one CPU/runtime/model configuration, or does some part of it generalize?

---

# 2. Non-negotiable research rules

These apply to every TASK.

1. **Measurement is the judge.**
   A hypothesis is not a result until the experiment supports it.

2. **Negative results are valid results.**
   Never reshape an experiment merely to obtain the expected sign.

3. **No automatic progression.**
   Codex must stop after the stated outputs are produced.

4. **No new research branch without checkpoint approval.**
   Interesting side observations go into a `FOLLOWUPS.md` note, not directly into the active roadmap.

5. **Historical results are immutable records.**
   New results may supersede them, but old reports remain preserved.

6. **Dangerous scheduler/system operations require the user.**
   Codex must not autonomously load schedulers, alter boot/kernel configuration, change governors, enable/disable sched_ext, or run privileged system-modifying commands.

7. **Benchmark runs are performed by the user on the actual machine.**
   Codex may prepare scripts and exact commands.

8. **Primary performance experiments use interleaved/randomized arm order.**
   No block-structured arm measurement unless specifically justified.

9. **New claims must map to explicit artifacts.**
   Every major paper claim should eventually have:
   - raw result,
   - analysis output,
   - figure/table,
   - text claim.

10. **Venue fit includes attendance feasibility.**
    A venue requiring physical presentation by an author is not automatically a valid target.

---

# 3. Required checkpoint package

At the end of **every TASK**, do not simply say "done".

Prepare a checkpoint package containing:

```text
TASK:
STATUS:
COMMIT / BRANCH:
FILES CHANGED:
COMMANDS TO RUN:
RAW ARTIFACTS:
DERIVED ARTIFACTS:
KEY NUMBERS:
WARNINGS / ANOMALIES:
QUESTIONS FOR ANALYSIS:
```

For experiment TASKs, also include:

```text
RUN COUNT:
ARM ORDER:
MACHINE STATE:
TEMPERATURE RANGE:
FAILED RUNS:
EXCLUDED RUNS + REASON:
```

Then:

> **STOP. Do not begin the next TASK. Bring this checkpoint package and the generated artifacts to ChatGPT for analysis.**

---

# 4. Task map

| Task | Purpose | Priority | Opens next task only if |
|---|---|---:|---|
| C00 | Freeze conference-upgrade context | P0 | Repository context is clean |
| C01 | Stock scheduler / HFI characterization | P0 | Stock scheduler does not already solve the problem trivially |
| C02 | Clean external-vs-oracle comparison | P0 | External policy remains close enough to oracle |
| C03 | Minimal generality check | P1 | Core contribution survives C01/C02 |
| C04 | Bounded mechanism reconnaissance | P1 | Time remains and evidence is promising |
| C05 | Statistical hardening | P0 | Main experiment set is frozen |
| C06 | Figure/table evidence pipeline | P0 | Statistics are frozen |
| C07 | Conference paper rewrite | P0 | Evidence package is stable |
| C08 | Venue + attendance gate | P0 | Official venue policies are verified |

---

# TASK-C00 — Conference Upgrade Freeze

## Goal

Make the repository understand the **new research state** before any new experiment code is written.

The current `AGENTS.md` / `CLAUDE.md` still contain historical assumptions such as the scheduler not distinguishing the two phases. Those assumptions were useful during discovery, but must not be treated by Codex as current facts.

## Required changes

### 1. Add this file to the repository

Recommended path:

```text
CONFERENCE_UPGRADE_TASKS.md
```

This file becomes the forward-looking task authority.

### 2. Update `AGENTS.md`

Add a new top-level section:

```text
REVISION 3 — Conference Upgrade (2026-08-21)
```

It must state:

- prefill/decode distinction is background, not novelty;
- hybrid-core imbalance is background, not novelty;
- candidate novelty is external phase observability + external OS action;
- stock Linux / Thread Director / HFI behavior must be measured rather than assumed;
- AVX / microarchitecture explanations are hypotheses until causally supported;
- C01 and C02 are hard gates;
- no generality/mechanism expansion before those gates;
- physical-attendance feasibility is part of venue selection;
- this master task file governs new work.

### 3. Keep `CLAUDE.md` consistent

If `CLAUDE.md` mirrors `AGENTS.md`, update the corresponding revision so the two files cannot give conflicting research instructions.

### 4. Do NOT rewrite historical reports

Do not alter experimental numbers in:

- `PAPER.md`
- `RAPOR_FINAL.md`
- phase reports
- README result tables

during C00.

## Acceptance criteria

- [ ] New conference-upgrade authority exists.
- [ ] AGENTS/CLAUDE point to it.
- [ ] Historical results untouched.
- [ ] No experiment code changed.
- [ ] No novelty statement is presented as experimentally proven if it has not yet been tested.

## Checkpoint package

Send:

- `git diff -- CONFERENCE_UPGRADE_TASKS.md AGENTS.md CLAUDE.md`
- list of files changed
- commit SHA if committed

## STOP

**Do not start C01 before ChatGPT reviews the context freeze.**

---

# TASK-C01 — Stock Scheduler / Hardware-Guidance Characterization

## Research question

> Under default unpinned Linux scheduling, does the stock scheduler already reproduce the phase-optimal placement behavior that the paper attributes to explicit phase-aware control?

This is a critical reviewer objection.

The experiment must not assume that Thread Director/HFI either does or does not solve the problem.

## Existing code to reuse

Inspect and reuse where appropriate:

- `harness/e1_residency.py`
- `harness/thread_residency.py`
- `harness/bench_lib.py`
- `harness/run_once.py`
- `harness/i10_ground_truth.py`

Do not duplicate already-tested measurement primitives.

## Important flaw in existing `e1_residency.py`

The existing script:

- samples residency,
- reports topology movement,
- but treats the request largely as one window,
- and explicitly warns that high-frequency `/proc` sampling perturbs latency.

C01 must therefore separate:

### A. Characterization runs
Used for:
- P/E residency,
- migration topology,
- phase-specific placement.

Latency from these runs is **not** primary evidence.

### B. Performance runs
Used for:
- TTFT,
- ITL p50/p95,
- decode throughput.

These should avoid heavy residency sampling.

## Ground truth

For **offline evaluation only**, it is acceptable to use the diagnostic phase marker already supported by the repository (`PHASE_MARK` / internal boundary).

The scheduler/policy must not receive this information.

The ground-truth instrumentation is only used to label samples as:

```text
prefill
decode
```

## Minimum experiment arms

### Arm S0 — Stock unpinned
No `taskset` restriction. Default Linux behavior.

### Reference arms
Use existing known references where possible:

- P-only reference
- P+E reference

These references need not be rerun in the first C01 pilot unless hardware/software state has changed materially.

## Required telemetry

For each stock-scheduler characterization run:

### Prefill window
- percentage of samples on P cores,
- percentage on E cores,
- per-thread P/E residency,
- P→E transitions,
- E→P transitions,
- total migrations,
- active thread count.

### Decode window
Same metrics separately.

### System metadata
- kernel version,
- CPU topology,
- governor / power profile,
- model hash/path,
- llama.cpp commit/build identity,
- start/end package temperature,
- frequency summary.

## Recommended output files

```text
conference/
  experiments/
    c01_stock_scheduler.py
  analysis/
    c01_analyze.py
results/
  conference_c01/
    env.json
    trace_run_*.json
    perf_runs.csv
    summary.json
    summary.md
```

Exact layout may vary, but raw and derived data must be separate.

## Sampling design

Start with a low enough interval to identify phase residency without reproducing the 5 ms perturbation problem.

Recommended pilot intervals:

```text
20 ms
50 ms
```

Use the least intrusive interval that still gives a stable phase-residency picture.

Do **not** optimize the interval for a desired result.

## Pilot run count

First checkpoint:

```text
6 characterization runs
6 low-overhead performance runs
```

Interleave/reference ordering where applicable.

Do not automatically scale to 20+ runs before analysis.

## Primary outputs

1. `prefill_p_residency_pct`
2. `prefill_e_residency_pct`
3. `decode_p_residency_pct`
4. `decode_e_residency_pct`
5. phase-specific migration counts
6. stock TTFT / ITL p95

## Interpretation gate

### Strong result for the paper
Stock Linux does **not** naturally reproduce:

```text
prefill -> wider P+E usage
decode  -> narrow P-only behavior
```

in a way that reaches the explicit phase-aware frontier.

### Ambiguous result
Stock scheduler partially shifts behavior by phase but not enough to match explicit policy.

This is still publishable and may become a stronger comparison.

### Threatening result
Stock scheduler already produces placement and performance close to SWITCH without explicit phase information.

If this happens, **STOP the research expansion** and reassess the main contribution before C02.

## Acceptance criteria

- [ ] Phase-specific residency is measured, not inferred from whole-request averages.
- [ ] Trace runs are separated from primary performance runs.
- [ ] Diagnostic ground truth does not influence scheduling.
- [ ] Raw traces are preserved.
- [ ] No claim about HFI/Thread Director is made without the measured result.
- [ ] Experiment metadata is sufficient to reproduce the run.

## Checkpoint package

Include:

- summary table,
- 1 representative raw trace,
- all run-level CSV/JSON outputs,
- sampling overhead observation,
- stock vs known P/P+E references,
- any unexpected migrations or phase behavior.

## STOP

**Analyze C01 with ChatGPT before C02.**

---

# TASK-C02 — Clean External vs Oracle Phase Policy

## Research question

> How much performance is lost because the phase is inferred externally rather than known perfectly by the application?

This converts detector accuracy into a systems-level result.

## Existing code to reuse

Relevant files:

- `harness/i10_ground_truth.py`
- `harness/i13_app_vs_daemon.py`
- `harness/phase_switch.py`
- `harness/h5_detector_v2.py`
- `harness/bench_lib.py`
- `harness/run_once.py`

## Why `i13_app_vs_daemon.py` is not yet a clean oracle

The existing comparison changes more than phase knowledge.

The application-informed arm uses a patched/internal threadpool affinity path, while the daemon arm uses external `sched_setaffinity`.

Therefore the result may mix:

- perfect phase knowledge,
- different threadpool behavior,
- different implementation paths.

C02 must isolate **only the phase-information source**.

## Required experimental design

All policy arms must use:

- the same server build,
- the same model,
- the same thread counts,
- the same affinity-changing implementation,
- the same sampling overhead,
- the same prompt,
- the same request structure.

The only variable should be:

```text
Where does the phase transition signal come from?
```

## Required arms

### A_STATIC
Static baseline.

Choose the static anchor(s) required for the metric.

At minimum retain the existing P-only and P+E references needed to interpret TTFT and decode tail latency.

### B_EXTERNAL
Same affinity controller, phase source:

```text
/proc-based external detector
```

### C_ORACLE
Same affinity controller, phase source:

```text
internal PHASE_MARK / true phase boundary
```

## Overhead equalization

Important:

The ORACLE arm should still run the detector sampling loop in **unarmed / observation-only mode**, so ORACLE is not unfairly advantaged by avoiding the detector’s measurement overhead.

If STATIC is included in normalized gain calculations, either:

- run equivalent observation overhead there as well, or
- explicitly report why not and avoid interpreting the difference as detector cost.

## Affinity action

Use the same operation in B_EXTERNAL and C_ORACLE.

Preferred:

```text
sched_setaffinity
```

Do not compare an internal threadpool-mask mechanism against an external process-affinity mechanism in the clean oracle result.

## Run design

Pilot:

```text
6 randomized/interleaved rounds
x 3 arms
```

If static references are already stable and reused, document their provenance exactly.

## Primary metrics

- TTFT
- ITL p50
- ITL p95
- decode tps
- J/token if RAPL remains stable
- migration count
- switch timestamp
- true phase-boundary timestamp
- detector-vs-oracle timing gap

## Core derived metrics

### External–Oracle gap

For latency metric `M`:

```text
gap_pct = (M_external - M_oracle) / M_oracle * 100
```

### Gain recovery

Use a metric-appropriate static anchor.

Example concept:

```text
recovered_gain =
    (static_anchor - external)
    /
    (static_anchor - oracle)
```

Do not hard-code this formula blindly for metrics where the sign/direction differs.

The analysis script must explicitly encode whether lower or higher is better.

## Decision gate

### Strong
External policy recovers roughly **90% or more** of oracle benefit on the primary long-prefill regime and does not introduce a meaningful decode-tail regression.

### Acceptable
External is measurably worse than oracle but still captures most of the practical benefit.

The paper becomes:

> Application cooperation is better, but not required to capture most of the gain.

### Threatening
External policy is substantially worse than oracle, especially if timing error destroys the multi-objective advantage.

If this happens, stop before generality work and reassess whether the paper should be reframed as characterization rather than external scheduling.

## Acceptance criteria

- [ ] Same server build across arms.
- [ ] Same affinity mechanism across EXTERNAL and ORACLE.
- [ ] Same detector sampling overhead across EXTERNAL and ORACLE.
- [ ] Randomized/interleaved order.
- [ ] Raw per-run results preserved.
- [ ] Phase timestamps preserved.
- [ ] No use of first-token arrival as oracle ground truth when internal ground truth is available.

## Checkpoint package

Include:

- run table,
- external-oracle timing difference,
- TTFT/ITL comparison,
- gain-recovery values,
- energy if valid,
- failed/missed detector transitions,
- server log excerpt proving oracle phase events.

## STOP

**C02 is a hard gate. Analyze with ChatGPT before any generality or mechanism work.**

---

# TASK-C03 — Minimal Generality Check

## Purpose

Answer the most dangerous remaining limitation:

> Is the observed phenomenon / external signal only an artifact of one Intel CPU + one runtime/model setup?

This task is intentionally **minimal**.

Do not reproduce the full historical 36-experiment campaign on a second machine.

## Preferred path — Cross-vendor AMD system

If the Ryzen AI 9 HX 370 machine is available, use it.

The code must not assume Intel CPU numbering.

## Portability requirement

Create a parameterized runner accepting explicit topology:

```text
--big-cpus
--compact-cpus
--threads-big
--threads-all
```

Avoid encoding Intel-specific:

```text
0-15 = P
16-23 = E
```

into new conference code.

## Required minimum arms

```text
BIG_ONLY
ALL_CORES
```

Optional only if cheap:

```text
one intermediate split
```

## Required minimum measurements

For each arm:

- TTFT
- ITL p50/p95
- decode tps
- temperature
- frequency summary

For detector generality:

- raw context-switch trace,
- phase ground truth if diagnostic instrumentation is available,
- prefill and decode signal distributions.

## Important rule

Do **not** retune the detector threshold and then claim zero-shot generalization.

Separate:

### Signal generality
Do the distributions separate at all?

### Threshold transfer
Does the Intel-selected detector work unchanged?

### Recalibrated detector
If a new threshold is needed, report it explicitly as recalibration.

These are different claims.

## First-stage run count

```text
6 BIG_ONLY
6 ALL_CORES
```

interleaved.

Detector trace sample count should be enough to inspect the distributions but need not reproduce all Intel experiments.

## Three scientifically valid outcomes

### Outcome A
Placement inversion and external signal both generalize.

Strong cross-vendor evidence.

### Outcome B
Placement inversion generalizes but detector signal does not.

Result:

> Phenomenon is broader than the specific external signal.

Still valuable.

### Outcome C
Placement inversion does not generalize.

Result:

> Intel-specific architectural/runtime boundary is identified.

Also valuable if stated honestly.

## Fallback path — Second model family

If cross-vendor hardware access becomes impractical, replace C03 with:

```text
same Intel platform
+ different model architecture/family
+ P-only vs P+E
+ detector trace
```

A different family is preferred over merely another width of the same family.

## Acceptance criteria

- [ ] Only one generality axis is pursued in the first pass.
- [ ] No full cross-product matrix.
- [ ] Topology is explicit and portable.
- [ ] Threshold transfer and threshold recalibration are clearly separated.
- [ ] Negative cross-platform result is retained.
- [ ] No more than the planned minimal run set before checkpoint review.

## Checkpoint package

Include:

- machine topology record,
- exact CPU lists,
- big-only/all-core results,
- signal distribution summary,
- whether original thresholds transferred,
- any platform-specific implementation issue.

## STOP

**Analyze C03 with ChatGPT before deciding whether the paper needs any further generality experiments.**

---

# TASK-C04 — Bounded Mechanism Reconnaissance

## Purpose

Investigate the friend-proposed microarchitectural hypothesis **without allowing it to consume the project**.

The goal is not:

> Prove AVX2 decomposition explains the entire decode regression.

The goal is:

> Determine whether there is sufficiently clean evidence to justify one mechanism subsection or one follow-up experiment.

## Time/scope limit

C04 is explicitly bounded.

If the evidence is messy after the reconnaissance phase:

> **STOP and keep the current bandwidth-bound characterization.**

Do not open a multi-week compiler/microarchitecture project.

## Stage 1 — Actual hot-path inspection

Before any synthetic GEMV benchmark:

1. identify the actual Q4_K_M decode hot path,
2. inspect relevant llama.cpp/ggml kernels,
3. record whether the hot path uses:
   - YMM,
   - XMM,
   - AVX2 integer ops,
   - FMA,
   - unpack/shuffle/dequantization operations,
4. record compiler/build flags.

Recommended artifacts:

```text
results/conference_c04/
  build_flags.txt
  symbols.txt
  disassembly_excerpt.txt
  source_map.md
```

## Stage 2 — Lightweight runtime counters

If permissions allow, collect a minimal diagnostic set separately from primary paper benchmarks.

Possible examples:

- cycles
- instructions
- IPC
- cache misses
- context switches
- migrations

Do not silently require privileged perf settings.

If hardware counters are unavailable, record that and continue with non-privileged evidence.

## Stage 3 — P vs E worker evidence

Ask:

> During decode, do slower/compact workers create observable synchronization tail / straggler behavior?

Prefer existing runtime evidence before adding invasive instrumentation.

If clean instrumentation is necessary, it must be diagnostic-only and clearly separated from primary performance runs.

## Optional Stage 4 — Vector-width ablation

Open this only if stages 1–3 support it.

Preferred causal design:

```text
P-core: 128-preferred vs 256
E-core: 128-preferred vs 256
```

and evaluate the interaction effect.

Do not assume `-mprefer-vector-width=128` changes explicit-intrinsic code.

Verify generated code.

## Synthetic GEMV rule

A synthetic GEMV microbenchmark is **explanatory supporting evidence**, not proof about llama.cpp.

Sequence must be:

```text
real workload effect
→ actual hot-path evidence
→ controlled microbenchmark
```

not the reverse.

## Successful C04 outcomes

### Positive
A clean mechanism is isolated.

Add one bounded mechanism claim.

### Negative
AVX/vector-width explanation is not dominant.

This is a valid result.

### Inconclusive
Evidence is mixed.

Do not make causal claims.

## Acceptance criteria

- [ ] Real Q4_K_M path inspected before synthetic benchmark.
- [ ] No causal statement from architecture documentation alone.
- [ ] Generated code verified before vector-width interpretation.
- [ ] Diagnostic instrumentation does not contaminate primary performance numbers.
- [ ] Scope does not expand automatically.

## Checkpoint package

Include:

- hot-path identification,
- disassembly excerpts,
- counter summary,
- P/E observations,
- conclusion classified as:
  - `SUPPORTED`
  - `REFUTED`
  - `INCONCLUSIVE`

## STOP

**Analyze C04 with ChatGPT. Do not extend mechanism work unless explicitly approved.**

---

# TASK-C05 — Statistical Hardening

## Purpose

Convert the historical exploratory measurement process into a paper-grade inferential analysis.

Do this only after the main experiment set is frozen.

## Primary metrics

Freeze in advance:

1. TTFT
2. ITL p95
3. competitor throughput, when a competitor is present

Secondary:

- ITL p50
- decode tps
- J/token
- migrations
- detector timing

## Statistical unit

For tail latency:

> **one run’s p95 is one observation**

Do not treat individual token latencies as independent experimental replicates.

## Required reporting

For each primary comparison:

- raw arm means/medians as appropriate,
- absolute difference,
- relative effect size,
- 95% confidence interval,
- Welch test or another predeclared test where appropriate,
- run count,
- scenario-specific noise characterization as secondary context.

## Noise floor

Historical per-metric/per-scenario noise floors remain valuable.

But in the conference analysis:

> noise floor is measurement-stability context, not the sole inferential decision rule.

## Multiple comparisons

For a predeclared family of primary comparisons, add an explicit correction strategy such as Holm.

Do not correct every exploratory number in the repository as if it were a confirmatory family.

## Bootstrap

If bootstrap CIs are used:

- fixed seed,
- run-level resampling,
- sufficient iterations,
- script records parameters.

## Recommended outputs

```text
conference/analysis/
  stats.py
  bootstrap.py
  tables.py

results/conference_stats/
  primary_comparisons.csv
  confidence_intervals.csv
  corrected_tests.csv
  stats_report.md
```

## Reproducibility

The analysis must regenerate all final numeric claims from raw CSV/JSON.

No hand-copied result should exist only in the paper.

## Acceptance criteria

- [ ] Primary metric family frozen before final analysis.
- [ ] Run-level statistical units.
- [ ] Effect sizes + CIs always reported for primary claims.
- [ ] Multiple comparison strategy documented.
- [ ] Random seeds fixed.
- [ ] All paper numbers trace to raw results.

## Checkpoint package

Include:

- `stats_report.md`
- primary comparison CSV
- any discrepancy with historical report numbers
- list of claims that changed classification after statistical hardening

## STOP

**Review C05 with ChatGPT before generating final figures.**

---

# TASK-C06 — Final Evidence Figures and Tables

## Purpose

Build the compact evidence package the final paper will use.

Figures must be generated from analysis artifacts, not manually assembled.

## Core figure set

### Figure A — Static Pareto frontier
Two panels if still justified:

- idle
- contended

Must show SWITCH clearly.

### Figure B — External phase signal
One representative request:

- context-switch signal,
- internal true phase boundary,
- external detection point.

### Figure C — Stock scheduler characterization
Phase-specific P/E residency or equivalent visualization from C01.

### Figure D — External vs Oracle
Show:

- STATIC
- EXTERNAL
- ORACLE

for the main latency metrics.

### Optional Figure E — Generality
Only if C03 produced a clear story.

### Optional Figure F — Mechanism
Only if C04 produced `SUPPORTED`.

## Table set

At minimum:

### Table 1
Core policy comparison:
- TTFT
- ITL p95
- decode tps
- competitor throughput
- J/token if stable

### Table 2
Detector:
- recall
- precision
- false/spurious transitions
- overhead
- timing relative to internal boundary

### Table 3
Oracle recovery / generality if space allows.

## Figure-generation rules

Every final figure must have:

```text
raw source(s)
→ analysis transform
→ plotting script
→ generated PDF/SVG
```

No spreadsheet-only hidden manipulation.

## Acceptance criteria

- [ ] All figures script-generated.
- [ ] Every plotted point traces to a raw result.
- [ ] CIs/error bars used where appropriate.
- [ ] No decorative figure that consumes space without supporting a claim.
- [ ] Optional figures omitted if evidence is weak.

## Checkpoint package

Send:

- generated figures,
- figure source CSVs,
- scripts,
- proposed captions,
- one-line claim supported by each figure.

## STOP

**Review the evidence package with ChatGPT before paper rewriting.**

---

# TASK-C07 — Conference Paper Rewrite

## Purpose

Write a new conference-oriented paper without corrupting the historical 6-page draft.

## File strategy

Keep:

```text
PAPER.md
```

as historical workshop-era draft.

Create:

```text
PAPER_CONFERENCE.md
```

or a venue-neutral LaTeX paper directory once the venue is known.

## Proposed story

### 1. Introduction
Lead with the distinction:

- prior work knows phases internally,
- the OS normally receives no explicit request-level phase identity,
- the contribution is external observability + actionable placement.

### 2. Background / closest prior art
Cover:

- CPU LLM prefill/decode specialization,
- heterogeneous-core LLM balancing,
- hardware-guided hybrid scheduling,
- generic phase-aware OS work.

### 3. Experimental setup
Include:
- platform,
- model/runtime,
- measurement protocol,
- interleaving,
- primary metrics,
- statistical design.

### 4. Placement inversion
Use the established frontier result.

### 5. What stock scheduling does
C01.

### 6. External phase observability
Detector result.

### 7. External vs oracle policy
C02.

### 8. Generality / scope
C03.

### 9. Mechanism
Only if C04 supports a clean claim.

### 10. Failure regimes / limitations
Preserve:
- short cached prefill,
- spin-wait failure,
- no idle E-core capacity,
- single-runtime limitations that remain.

## Claim discipline

Every main contribution sentence must be classified:

```text
BACKGROUND
MEASURED CLAIM
INTERPRETATION
LIMITATION
```

during drafting.

Do not let interpretation silently become measured fact.

## Closest-work language

The paper must explicitly distinguish itself from runtime-internal methods.

Avoid:

> We are the first to exploit prefill/decode differences on heterogeneous CPUs.

Prefer:

> Prior systems exploit phase and core heterogeneity from inside the inference runtime; we study whether equivalent request-level phase information is externally recoverable and actionable without engine cooperation.

## Acceptance criteria

- [ ] No stale workshop page-budget language.
- [ ] No novelty claim contradicted by known prior art.
- [ ] C01/C02 results integrated.
- [ ] Negative results retained.
- [ ] Every primary number traceable to C05/C06 artifacts.
- [ ] Limitations are explicit.
- [ ] Historical `PAPER.md` preserved.

## Checkpoint package

Send:

- full new draft,
- claim-evidence mapping,
- unresolved citation list,
- unresolved technical questions,
- page/word count.

## STOP

**Review the full paper with ChatGPT before venue-specific formatting.**

---

# TASK-C08 — Venue and Attendance Gate

## Purpose

Select a venue that is not only scientifically appropriate, but actually publishable under the authors’ travel constraints.

## Hard constraint

Do not assume:

- another coauthor can travel,
- a friend can present,
- remote presentation will be granted after acceptance.

## Required verification for each candidate venue

Use official sources only.

Record:

1. submission deadline,
2. notification date,
3. conference location,
4. proceedings/indexing status,
5. accepted-paper presentation rule,
6. whether physical author attendance is mandatory,
7. explicit remote-presentation policy,
8. visa/hardship exception policy,
9. registration requirement,
10. travel grant availability.

## Venue status categories

### GREEN
Remote presentation is explicitly allowed for accepted research papers, or written organizer confirmation exists.

### YELLOW
Policy is ambiguous; chairs must be contacted before submission.

### RED
At least one author must physically attend and no usable exception is available.

## Required artifact

```text
VENUE_GATE.md
```

with a table of official evidence and source dates.

## Important

Scientific quality target and submission venue are separate.

The paper may be prepared to SIGMETRICS/MLSys-level quality even if a specific venue becomes RED because of attendance.

## Acceptance criteria

- [ ] No venue chosen from reputation alone.
- [ ] Attendance policy verified before submission.
- [ ] Ambiguous policy resolved in writing if possible.
- [ ] No duplicate-submission conflict.
- [ ] Final venue chosen only after C07 evidence package is stable.

## STOP

**Make the final submission decision with ChatGPT.**

---

# 5. Project-level kill criteria

The conference-upgrade effort must stop or be reframed if any of these occur.

## Kill / major-reframe gate 1 — after C01

If stock Linux/hardware guidance already provides essentially the same phase-optimal behavior and performance as the explicit policy, the external-control contribution needs major reassessment.

Do not attempt to rescue it with weeks of mechanism work.

## Kill / major-reframe gate 2 — after C02

If the external detector is far from the oracle in policy-level outcomes, then:

- reconsider the detector,
- or reframe as characterization,
- but do not automatically proceed to cross-platform experiments.

## Scope kill — after C04

If mechanism evidence remains inconclusive, stop mechanism work.

The project is not allowed to become an AVX/compiler archaeology project merely because the hypothesis is interesting.

## Time kill

The project must not absorb the next 4–5 months.

The intended upgrade is a bounded sprint centered on:

```text
C00
→ C01
→ analysis
→ C02
→ analysis
→ C03 if justified
→ C04 only if cheap/promising
→ C05–C08
```

---

# 6. Codex execution contract

For each Codex invocation:

1. Give Codex **one TASK only**.
2. Tell it to read:
   - `CONFERENCE_UPGRADE_TASKS.md`
   - `AGENTS.md`
   - relevant existing harness files.
3. Tell it not to start later TASKs.
4. Tell it not to rewrite historical results.
5. Tell it to preserve raw outputs.
6. Tell it to provide exact run commands.
7. The user performs the benchmark.
8. Bring outputs back to ChatGPT.
9. Only then authorize the next TASK.

Suggested final line for every Codex prompt:

> **Implement only TASK-CXX. Do not begin any later task. When implementation and local non-destructive checks are complete, print the checkpoint package defined in CONFERENCE_UPGRADE_TASKS.md and stop. Do not run privileged scheduler/system modifications.**

---

# 7. Current starting point

Start with:

```text
TASK-C00
```

After C00 is merged/committed and reviewed, move to:

```text
TASK-C01
```

No other conference-upgrade code should be written before that checkpoint.
