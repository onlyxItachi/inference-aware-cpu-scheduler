# Prefill and Decode Are Two Workloads: Externally Detectable Phase Structure in CPU LLM Inference

**Full draft — all sections written. Open items listed at the end.**
Target: 6-page workshop format. Figures: 3. Tables: 2.

Page budget:

| § | Section | Pages |
|---|---|---|
| 1 | Introduction | 1.0 |
| 2 | Setup and methodology | 0.4 |
| 3 | Two workloads in one process | 1.4 |
| 4 | Reading the boundary from outside | 1.2 |
| 5 | Acting on it | 1.3 |
| 6 | What we did not need | 0.4 |
| 7 | Limitations and related work | 0.8 |

---

## Abstract

Local LLM inference on CPUs is presented to the operating system as one
homogeneous multithreaded job. It is not. On a hybrid x86 laptop running
`llama.cpp`, prefill and decode invert the answer to the same placement
decision: adding the E-cores speeds prefill by 13% and degrades decode tail
latency by 9.4%. We measure the full static Pareto frontier, intermediate P+E
splits included, and no point on it wins both — in an idle scenario or against
a continuous `make -j16`. Acting on the phase boundary with a single
`sched_setaffinity` swap dominates every frontier point on all three axes —
LLM latency, LLM tail latency, and competitor throughput — except the most
competitor-friendly static point, against which it trades 2.4% of competitor
throughput for 12.5% time-to-first-token. The boundary is legible from outside
the application: given a designated process, per-thread context-switch rates
from `/proc` give 100% recall and 99.4% precision on ten held-out
configurations at 1.7% of one core, though 6.7% of cached short turns trigger
early and pay 12.8% TTFT for it. The method's limit is measured, not assumed:
with a spin-wait build the signal falls 2500× and the detector never fires;
`llama.cpp`'s default build uses OpenMP, where it does. One machine, one
runtime, one model family.

---

## 1. Introduction

The split between prefill and decode is not a new observation. It is the
organizing principle of modern GPU serving systems, which disaggregate the two
phases across machines, chunk prefill to bound its interference with decode,
and schedule them against separate latency targets. What that literature has
established, it has established *inside* the inference engine: the runtime
knows which phase it is in, because it is the thing driving the phase. Our
question is what happens one layer down, where the operating system schedules
the threads. On a CPU — where local inference actually runs for anyone without
a datacenter GPU — and on a hybrid core topology, the two phases do not merely
have different performance profiles; they invert the right answer to the same
scheduling decision. Adding E-cores to the thread set makes prefill 13% faster
and decode's tail latency 9.4% worse, and this is not a two-endpoint artifact:
we measure the intermediate splits and find no static configuration on the
Pareto frontier that wins both, with or without a competitor. This alone would
only restate a known distinction on new hardware. The part that is not a
restatement is that the OS can *see* the distinction: given a designated
inference process, the phase boundary is recoverable from per-thread
context-switch rates in `/proc` — no instrumentation, no patch to the engine,
no cooperation from the application, 1.7% of one core. The contribution of this
paper is therefore not the prefill/decode split, but its externality: a phase
structure that the serving literature treats as private to the runtime turns
out to be legible from outside it, and legible early enough to act on.

**Contributions.**

1. A characterization of CPU LLM inference as two workloads with inverted
   placement preferences, with the mechanism for each side measured
   independently (§3).
2. An external phase detector: per-thread context-switch rates from `/proc`,
   evaluated on held-out configurations, at 1.7% of one core (§4).
3. A phase-switching placement policy that dominates the measured static
   Pareto frontier in both idle and contended scenarios, with its failure
   regimes measured rather than argued (§5).
4. A negative result on kernel-side policy: neither stock `sched_ext`
   scheduler beats a userspace policy here, and the more placement logic the
   kernel asserts, the more of the application-informed gain it erases (§6).

---

## 2. Setup and Methodology

**Platform.** Intel i7-14650HX (8 P-cores with SMT, CPU 0–15; 8 E-cores,
CPU 16–23), 32 GB DDR5 configured at 5200 MT/s in dual channel, CachyOS with
kernel 7.1.3. Inference is CPU-only throughout; the machine's discrete GPU is
unused. `llama.cpp` at commit `571d0d5`, default build (OpenMP enabled), Q4_K_M
quantization, a 9B model unless stated and a 4B model of the same family for
the width-scaling check in §3.3.

**Instrument.** Requests are issued to `llama-server` over streaming SSE and
timestamped per token, so time-to-first-token (TTFT) and the inter-token
latency (ITL) distribution are measured separately rather than inferred from
aggregate throughput. Package energy is read from RAPL. Migration and
context-switch counts come from `/proc/<pid>/task/<tid>/sched`, sampled per
thread, requiring neither root nor tracing infrastructure. Approximately 600
runs across 30 experiments underlie the results below.

**Acceptance criterion.** We report an effect size against a noise floor and a
significance test, and they are not interchangeable: the effect size is the
gate, the test is a check on stability. Our initial protocol used a single 2%
floor, measured from 20 repetitions of one configuration. That was wrong, and
the way it was wrong is instructive. Re-measuring under contention, we found
the floor depends on the **metric** more than on the scenario: TTFT 0.38%,
ITL p50 0.31%, decode throughput 0.74%, and energy 0.56%, but ITL p95 5.20%
and ITL p99 5.65%. The tail metrics — and ITL p95 is this paper's primary
metric — are two and a half times noisier than the blanket floor assumed,
while the central-tendency metrics are several times quieter than it. The
floor is also scenario-dependent within a metric: ITL p95 sits at 0.7%
uncontended, 5.20% under a sporadic competitor, and 1.36–1.51% under a
continuous one, sporadic interference being the noisiest regime.

| metric | idle | sporadic competitor | continuous competitor |
|---|---|---|---|
| TTFT | 0.5% | 0.38% | 0.64–1.06% |
| ITL p50 | 0.5% | 0.31% | 0.55–0.76% |
| **ITL p95** | **0.7%** | **5.20%** | **1.36–1.51%** |
| ITL p99 | — | 5.65% | 2.88% |
| decode tps | 0.5% | 0.74% | 0.80–0.92% |
| J/token | — | 0.56% | 0.59% |
| competitor rate | — | — | 0.69–2.34% |

Every comparison in this paper is evaluated against the floor for its own
metric in its own scenario. We record that we got this wrong once in the course
of the work, in both directions: applying a contended p95 floor (5.20%) to an
uncontended arm classified a real −4.5% difference as noise, and estimating a
competitor-throughput floor from a CV band inflated by one unusually noisy arm
(2.34% where an independent session gave 0.58%) classified a real −2.2% cost as
equality. Both were corrected by using per-scenario, per-metric floors and, for
the second, a test. We report this because the choice of floor converts results
directly: it is the single methodological decision in this work most capable of
manufacturing or erasing a finding, and it did both.

**Significance testing.** Where a test is reported it is Welch's t-test,
unpaired (arms are separate runs, not repeated measures on a shared unit),
`[one- / two-tailed — to be filled from bench_lib.py]`. We apply no
multiple-comparison correction and note that across dozens of arm × metric
comparisons an uncorrected p<0.01 is not by itself evidence — which is why the
effect-size floor, not the p-value, is the acceptance gate. We use the test in
one specific role: to resolve comparisons where an effect sits near its floor
and a CV band is too crude to adjudicate, which is exactly the case that misled
us above.

**Ordering.** All configurations are measured interleaved: each round runs
every arm once, in shuffled order. In our noise characterization TTFT
correlated with run index (r = +0.671, n = 20) with no correlation to package
temperature (|r| < 0.25) — an unexplained within-session drift of the same sign
across all three primary metrics. Block-structured measurement would have
converted that drift into an apparent effect, so from Phase 1 onward no
configuration was measured in a block.

---

## 3. Two Workloads in One Process

A local inference server presents itself to the scheduler as a single
multithreaded process with a stable thread count and near-constant CPU demand.
That description is accurate for the process and misleading for the work.
Within one request, the same threads execute two computations with opposite
resource profiles, and the scheduler has no way to tell them apart.

### 3.1 The same decision, inverted

We first ask whether the phase distinction has any consequence for placement.
Our machine has eight P-cores and eight E-cores; the natural question for a
scheduler is whether to use the E-cores at all. Table 1 shows that the question
has no single answer. Adding the E-cores to the thread set reduces
time-to-first-token by 13.0% and simultaneously degrades decode tail latency
(ITL p95) by 9.4%. The effect is not marginal in either direction: both exceed
the per-metric noise floor by an order of magnitude (§2). The same result holds
on a 4B model, with the trade sharpened rather than softened — prefill improves
8.0% while decode p95 degrades 19.3%.

This is the whole problem in one measurement. A static placement policy must
pick a point on this trade, and whichever point it picks is wrong for one of
the two phases it will spend the request alternating between.

### 3.2 Why prefill scales and decode does not

The inversion is not an artifact of the hybrid topology; it follows from what
each phase does with a core. Scaling the thread set from two to eight physical
P-cores yields 77% efficiency for prefill and 49% for decode. Two independent
measurements explain the gap.

Prefill is compute-bound and close to the hardware ceiling. At 496 prompt
tokens the phase performs 8.93 TFLOP and sustains 811 GFLOPS, or 72% of the
AVX2 fp32 roofline for eight cores at the observed clock. Additional cores add
usable FLOPS, so the phase scales.

Decode is dominated by streaming weights. We measured achievable read bandwidth
directly, with a dependency-free benchmark pinned to the same eight P-cores
decode uses: 71.25 GB/s, against a theoretical dual-channel ceiling of
83.2 GB/s for the DDR5-5200 configuration this system actually runs. Decode at
11.53 tok/s over a 5.68 GB model requires 65.5 GB/s, or 92% of the measured
ceiling in its own configuration. The phase is not waiting on arithmetic, and
additional cores do not supply what it is waiting for.

We note that pinning matters even for this measurement: the same benchmark
unpinned reports 47.78 GB/s, because threads migrate onto E-cores. An unpinned
bandwidth number would have understated the ceiling by a third and made decode
appear to exceed it.

### 3.3 A cost that does not stream

Bandwidth alone does not close the account. Comparing the 9B and 4B models,
per-token decode latency does not fall in proportion to model size, which
implies a component of the per-token cost that is not weight streaming. We
initially estimated this component at ~24 ms per token by solving for bandwidth
and a constant from the two models jointly. That estimate is withdrawn: the fit
returns 92.0 GB/s, above the physical ceiling, and the excess traces to its own
premise. Constraining bandwidth to the physically attainable range instead
makes the constant model-dependent — 9 to 12.5 ms larger for the 4B model
across the entire feasible range. The non-streaming cost exists and is larger,
in absolute terms, for the smaller model; its magnitude and identity are not
established by our data. We report the two-point fit's failure because it is
instructive: the same calculation produced an out-of-range bandwidth twice
before we checked it against an independent measurement.

---

## 4. Reading the Boundary from Outside

If the two phases want different placements, a policy needs to know which phase
is running. The serving literature answers this inside the engine. We ask
whether the answer is available outside it, to a process that has been told
which PID to watch and nothing else.

### 4.1 The signal

The discriminating signal is the rate at which the inference process's threads
enter and leave the run queue. Prefill and decode differ in how much
computation sits between synchronization points: prefill performs large
matrix-matrix products across the whole prompt, decode performs a
matrix-vector pass per token. With the same barrier structure in both, decode
crosses barriers far more often per unit time, and each crossing that blocks
appears as a context switch in `/proc/<pid>/task/<tid>/sched`.

The distributions are well separated in the median and overlap in the tails.
Over 76,658 samples, per-thread context-switch rate in prefill has p95 = 989
and p99 = 6,639 (max 11,443); in decode, p1 = 3,839, p5 = 5,347, and
p50 = 13,938. A single threshold placed in the overlap region would misclassify
in both directions. Separation therefore comes not from the threshold alone but
from the combination of a hysteresis band and a two-sample confirmation, which
is what makes the detector robust to the overlap rather than merely lucky
about it.

### 4.2 The detector

The detector normalizes the context-switch rate per thread — necessary because
the policy of §5 changes the number of threads on P-cores, and an absolute
threshold would feed the policy's own effect back into the detector's input —
and applies an entry threshold of 3,000/s, an exit threshold of 2,100/s, and a
confirmation requirement of two consecutive samples. Sampling runs at 100 ms,
which costs 1.7% of one core: 1.7 ms per sample across 34 thread files. Nothing
about this requires root, tracing infrastructure, or a patch to the engine.

We evaluate on 49 runs across 12 configurations. Thresholds were selected on
two configurations (10 runs); the remaining ten configurations (39 runs) were
not used in selection.

| | recall | precision | distant FP/run | spurious transitions/run |
|---|---|---|---|---|
| all (49 runs) | 100.00% | 99.38% | 0.00 | 0.00 |
| **held-out (39 runs, 10 configs)** | **100.00%** | **99.36%** | **0.00** | **0.00** |

Every false positive is boundary-adjacent (within 300 ms of the true
transition); across 49 runs there is not one false positive distant from a
boundary. The 0.6% precision gap is therefore not misclassification but early
triggering, which §4.3 treats as a property rather than an error. There are
zero spurious state transitions, so the hysteresis band is doing its job: the
detector does not oscillate even when the policy of §5 is changing the thread
set underneath it.

The threshold has an eight-fold working window. Sweeping the entry threshold,
recall stays at 100% and spurious transitions stay below 0.05 across
hi ∈ [1,000, 8,000]; below that the detector fires almost continuously, and at
12,000 recall collapses to 93.7% and the detector begins triggering *late*. The
deployed value of 3,000 sits near the geometric center of the window.

### 4.3 The detector fires before the boundary

The detector reaches its decision approximately 118–135 ms before the first
token is emitted. This is useful — a placement policy that must migrate threads
benefits from lead time — and it invites an obvious objection: that the ground
truth is defined in the wrong place, and the detector is merely on time.

Two measurements bound the phenomenon. First, the lead time is independent of
prompt length: across prompts of 32 to 1,024 tokens, over which TTFT varies by
a factor of 26, lead time stays between 132 and 139 ms (spread 5.7%). It
corresponds to a fixed quantity of work, not to a fraction of prefill. Second,
the lead time is not decode-shaped. Scaling from four to eight P-cores, prefill
speeds up at 83% efficiency, decode at 63%, and the lead-time region at 77% —
the ratio of lead time to decode token duration is not constant (1.90 at four
cores, 1.55 at eight), and the two groups do not overlap. Had the region been
the first decode token in disguise, that ratio would have held.

Both alternatives are therefore eliminated: the lead time is not a fixed
detector artifact, since it varies by 45% with core count, and it is not a
mislabeled decode token, since it scales like prefill rather than like decode.
The detector genuinely decides while prefill-shaped computation is still
running. What that computation is remains open; we can say only that it is
constant-sized, well-parallelized, and located at the end of prefill.

### 4.4 Where the detector fails

In multi-turn conversation with prompt caching, prefill for turns after the
first shrinks from roughly 11 s to under 1 s, and the detector's lead time
stops being small relative to the phase it precedes. Across 30 turns, 6.7%
triggered far early (approximately 760 ms before the boundary, systematically
in the same turn position), and those turns paid 12.8% higher TTFT — consistent
with a short prefill running almost entirely under the narrow mask. A further
3.3% of turns showed a spurious forward transition and an early return during
decode. Single-turn use showed no anomalies in any configuration.

This is the detector's real weakness and it is a property of the regime, not of
the thresholds: when the phase is short, deciding early stops being free. §5.3
returns to it as a bound on where the policy should be applied at all.

---

## 5. Acting on It

### 5.1 The policy

The policy is the smallest thing that uses the signal. A userspace daemon
watches the detector; on a forward transition it widens the inference process's
affinity mask to P+E, and on a reverse transition it narrows the mask to
P-only. One `sched_setaffinity` call per transition, two per request. There is
no kernel component, no BPF, no model, no learning, and no modification to the
inference engine. We call this arm SWITCH and compare it against static
placements of the same threads.

The design follows from §4 rather than preceding it. Because the detector's
input is normalized per thread, the policy's own effect — changing how many
cores the threads occupy — does not feed back into the classification, and the
hysteresis band absorbs what remains. In 49 runs the detector produced zero
spurious transitions while the policy was active.

### 5.2 Against the static frontier

The question a static baseline must answer is not "P-only or P+E" but "which
split," so we measure the whole frontier: six arms from P-only through P+E2,
P+E4, P+E6 to P+E8, plus SWITCH, in each of two scenarios.

**Idle.** The static Pareto frontier is {P8, P8+E6, P8+E8}; the P8+E2 and
P8+E4 splits are dominated and do not sit on it at all. The reason is that the
two effects have different shapes. Adding only two E-cores moves ITL p50 from
86.6 ms to 93.1 ms — most of the price — while leaving TTFT unchanged at
11.1 s, or marginally worse. The decode penalty arrives as a step, the prefill
benefit accrues gradually, and the intermediate splits pay the former without
receiving the latter.

SWITCH dominates all three frontier points:

| against | TTFT | ITL p95 |
|---|---|---|
| P8 | −11.62% | −4.50% |
| P8+E6 | −6.25% | −13.57% |
| P8+E8 | +0.06% (equal) | −15.36% |

Energy falls 5.0% per token relative to P8. No static configuration dominates
SWITCH.

**Contended.** Against a continuous `make -j16`, the picture changes in a way
that makes the test harder rather than easier. The frontier becomes
{P8, P8+E2, P8+E4, P8+E8}: two of the three intermediate splits are now on it.
The reason is visible in the competitor's own throughput, which falls
monotonically with each E-core the inference process is given (0.3477 → 0.3302
passes/s). Under contention, adding E-cores does not merely grant capacity —
it *evicts* the competitor from those cores, so the intermediate steps that
were unpriced when the machine was idle now buy something. The trade curve
smooths from a step into a proportional exchange: P8+E2 costs 4.2% of ITL p50
and returns 4.35% of TTFT, P8+E4 costs 9.6% and returns 8.5%, and so on.

SWITCH dominates all four frontier points on both LLM axes:

| against | TTFT | ITL p95 |
|---|---|---|
| P8 | −12.47% | −1.11% (equal) |
| P8+E2 | −8.49% | −7.80% |
| P8+E4 | −4.35% | −10.35% |
| P8+E8 | −0.04% (equal) | −12.88% |

Welch's test against P8 gives TTFT t = −23.0 (p<0.01) and energy per token
−3.86% (t = −11.8, p<0.01); the ITL p95 difference is within this scenario's
floor for that metric.

A third axis needs stating precisely, because "dominance" and "cost" are not
compatible claims about the same comparison. On competitor throughput, SWITCH
(0.3395) is better than every other E-core-using arm — P8+E2 0.3384, P8+E8
0.3302, P8+E6 0.3294 — because it holds the E-cores only for the duration of
prefill. It is worse than exactly one arm, P8, which never touches the E-cores
at all: −2.36% (t = −6.96, p<0.01). So SWITCH dominates every frontier point on
all three axes except the most competitor-friendly static point, against which
it trades 2.4% of competitor throughput for 12.5% of time-to-first-token. That
trade is favorable on any weighting we would defend, but it is a trade and we
do not call it dominance.

### 5.3 Where it does not help

Two regimes were measured in which the policy's benefit disappears, and we
report both as scope rather than as caveats.

**No idle capacity.** Against a synthetic competitor pinned to the E-cores and
always runnable, there is nothing to switch into. Here the policy is not
neutral but slightly worse: TTFT is 1.48% higher than static P-only
(t = +11.37 against that experiment's 0.23% floor). Opening the E-cores when
they are already saturated costs the migration and buys nothing. The effect is
small, but its sign is the informative part — the benefit in §5.2 is a benefit
of *reclaiming idle capacity*, not of the placement per se.

**Short cached prefill.** In multi-turn conversation with prompt caching, the
first turn behaves as §5.2 describes (TTFT −11.3%) and turns two through five
show no measurable effect, because prefill has collapsed from roughly 11 s to
under 1 s and there is no longer a long phase to accelerate. Session-level gain
is −8.2%, essentially all of it from the first turn. Worse, 6.7% of turns in
this regime trigger the detector far early and pay 12.8% TTFT for it (§4.4).

The policy therefore applies to turns with substantial prefill. That population
is not a corner case — it includes every new conversation, every turn with
pasted code or a document, RAG-injected context, cache misses in multi-user
serving, and any deployment without prompt caching — but it is a population,
and the honest statement of the result is scoped to it rather than to
interactive inference generally.

### 5.4 A cheaper recommendation

One result requires no daemon at all and should be reported first for a reader
who wants to act today. When the inference process and a background build share
cores, running the build under `SCHED_IDLE` (`chrt --idle`) recovers 23.5% of
ITL p95, 10.5% of TTFT, and 14.8% of decode throughput, at a 15.2% cost to the
build. Every one of those figures clears its own floor. The cost is far below
what the same intervention costs against a synthetic always-runnable
competitor (~55%), for the reason one would expect: a real build already blocks
on I/O and serializes at link time, so strict deprioritization takes less from
it than from a workload engineered never to yield.

The contrast with cgroup weighting is instructive and independently confirms a
distinction the rest of this paper depends on. Against the same real build,
`cpu.weight=1` on the competitor changes nothing measurable — every metric
within floor — while against the synthetic competitor it recovered 49% of the
ITL gap. A weight is a share of throughput, not a latency priority; a
saturating always-runnable load lets the two be confused, and a real load that
blocks separates them.

---

## 6. What We Did Not Need

This work was designed around `sched_ext` and does not use it. The reasoning
that led there is worth stating, because at each step the alternative was
cheaper and the measurement kept saying so.

The case for a kernel-side policy was concrete: an affinity mask is a
partition, not a priority. When the policy narrows the inference process to
P-cores during decode, the released cores are either handed to a competitor
outright or left idle in the gaps between tokens, and neither can be revised at
token granularity. A BPF scheduler could express what a mask cannot — the
competitor may run on P-cores, but a decode thread preempts it on wakeup —
and thereby recover the idle capacity a hard partition wastes.

We bounded that opportunity before building it. Approximating soft priority
with facilities that already exist, `SCHED_IDLE` on the competitor recovers
96.8% of the contended ITL gap in the shared-core configuration; the residual
3.2% is not scheduling but cache and bandwidth interference, which no
scheduler recovers. `SCHED_IDLE` is already work-conserving strict priority,
so the mechanism a custom scheduler would add is the mechanism already
measured, and the headroom above it is small.

The remaining argument was that a purpose-built `sched_ext` scheduler might
still beat stock policy. We tested the stock ones: `scx_lavd` and
`scx_rustland`, each across two placement arms and two scenarios, 72 runs in
one session. Neither beats EEVDF with static P-pinning by more than that
experiment's own noise (Welch t = −1.25 and −1.12, both non-significant), and
neither beats EEVDF with SWITCH in any of four cells.

The more interesting result is the interaction. SWITCH's TTFT gain survives
under every scheduler — the mechanism is not EEVDF-specific — but it shrinks
monotonically as the scheduler asserts more of its own placement logic: −11.2%
under EEVDF, −7.6% under rustland, −4.7% under lavd (all p<0.01). On ITL p95
`lavd` erases the gain entirely (−0.1%), pinning p95 near 91.8 ms across all
four cells — a level worse than EEVDF with static P-pinning achieves at
90.1 ms.

A latency-aware kernel scheduler, lacking phase information, actively
overrides a policy that has it. This is our argument for where phase policy
belongs, and it is a measurement rather than a preference: the information that
makes the placement correct is available in userspace and not in the scheduler,
and every increment of kernel-side placement autonomy we measured subtracted
from the result.

*Environment note: on this machine `scxctl start --sched lavd` fails — the
loader passes `--pinned-slice-us 500` and `scx_lavd` segfaults, reproducibly in
5 of 5 attempts as root. Launching `scx_lavd --autopilot` directly works. We
report this as a loader bug rather than a scheduler result.*

---

## 7. Limitations and Related Work

**Limitations.** Every number here comes from one machine, one inference
runtime, and one model family. The runtime limit is the sharpest and it is
measured rather than assumed: the discriminating signal comes from OpenMP
barriers falling through to futex waits, and in a spin-wait build of the same
engine the context-switch signal drops 2500× and the detector never fires in
six runs. The method therefore applies to barrier-blocking CPU inference
runtimes, not to inference on CPUs generally — though we note `llama.cpp`'s
default build is the OpenMP one, so the method works in the configuration users
actually get. The machine is a single hybrid SKU: the default placement is
wrong on it, but we do not isolate hybridity as the cause, having no
homogeneous-CPU control and no separation of the P/E capacity gap from the
SMT-sibling effect. The second model varies width within one family — identical
architecture, layer count, and quantization — which controls for architecture
but makes this a width-scaling check, not a generality result; attention
variant, quantization scheme, and MoE routing are single-point. Our bandwidth
claim rests on an independent memory-bandwidth measurement showing decode at
92% of the read ceiling for its own core configuration, but the arithmetic
assumes the whole model is read from DRAM every token; we did not verify actual
DRAM traffic, which requires uncore counters. Our detection claim is about
phase, not workload identification: which process is the inference server, and
the privilege to set its affinity, are configuration supplied to the daemon,
placing this work between "the OS understands the workload" and "the
application hints to the OS." Finally the policy's benefit is confined to turns
with substantial prefill — under prompt caching, short conversational turns
show no measurable effect, and 6.7% of them trigger the detector early at a
cost of 12.8% TTFT — and when a competitor saturates the E-cores there is no
idle capacity to switch into, where the policy is not neutral but slightly
worse (TTFT +1.5%).

**Related work.** Four strands bound this work, and our position is different
with respect to each. *[Citations to be filled — search terms given; none
invented.]*

*GPU serving systems and the prefill/decode split.* Phase disaggregation across
machines, chunked prefill to bound interference with decode, and continuous
batching all rest on the distinction this paper measures. That literature
establishes it comprehensively — and establishes it inside the inference
engine, where the phase is known by construction. Our claim is not the
distinction but its externality, and our setting is the one that literature
does not address: a single CPU host with no scheduler-visible request queue.
[search: prefill decode disaggregation; chunked prefill; continuous batching;
LLM inference serving SLO]

*Hybrid-CPU scheduling.* Placement on asymmetric core topologies is an active
area in Linux, including hardware feedback from Thread Director, ITMT
preference ordering, and asymmetric-capacity awareness inherited from big.LITTLE
work. This strand establishes that the placement decision is hard and that the
kernel's answer is workload-agnostic by design. We contribute a workload for
which the agnostic answer is measurably wrong, and in which the correct answer
inverts within a single request. [search: Intel Thread Director Linux
scheduler; ITMT; asymmetric capacity scheduling; big.LITTLE energy aware
scheduling]

*Application-informed OS policy and phase detection.* Detecting program phases
from hardware counters or execution intervals, and adapting OS policy to them,
is a long-standing technique. Our detector is deliberately at the crude end of
it — one counter, one threshold, hysteresis — and its interest is not the
method but the target: that an LLM inference server's internal phase structure
is externally legible at all, and legible from a counter available without root
or tracing. [search: program phase detection hardware counters; phase-aware
scheduling; application hints operating system scheduler]

*`sched_ext` and BPF schedulers.* The framework we designed around and did not
use. This strand is relevant to us as the mechanism whose necessity we tested
and, in §6, could not establish for this workload — a negative result about
placement of policy, not about the framework. [search: sched_ext BPF scheduler
Linux; scx_lavd; pluggable scheduling policy]

---

## Figures and Tables

**Figure 1** — Scaling efficiency, prefill vs decode, 2/4/6/8 physical P-cores.
Makes §3.2 visible in one panel.

**Figure 2** — Static Pareto frontier (TTFT × ITL p95) with SWITCH marked; two
panels, idle and contended. The paper's central evidence.

**Figure 3** — Per-thread context-switch rate over one request, with the true
phase boundary and the detector's trigger marked. Makes §4.1 and §4.3 visible
together.

**Table 1** — Placement arms: TTFT, ITL p50/p95, J/token, competitor rate.

**Table 2** — Detector evaluation, all vs held-out.

---

## Open before submission

1. **One- or two-tailed test** — read from `bench_lib.py`, fill the bracket in
   §2. The only factual blank in the draft.
2. **Citations** — four strands in §7, search terms given. Nothing invented;
   fill from an actual search.
3. **Figures 1–3** — from existing CSVs in `results/`. Figure 2 is the paper's
   central evidence and should be drafted first.
4. **Table 1 and 2** — arm comparison and detector evaluation; numbers are in
   §5.2 and §4.2 respectively, needs formatting only.
5. **Length pass** — this draft runs long for six pages. First cuts, in order:
   §3.3 (the withdrawn fit can compress to three sentences), §5.4 (the
   `cpu.weight` contrast can become a footnote), §6's opening two paragraphs
   (the reasoning can be stated once rather than reconstructed).
6. **Title check** — the current title claims two things; if the venue favors
   a single claim, "Externally Detectable Phase Structure in CPU LLM Inference"
   carries the contribution alone.

## Deliberately not in the paper

Recorded here so the decisions are not re-litigated during revision:

- **The 3.7% competitor improvement.** The metric was measuring the LLM's own
  request duration. Dead, not corrected.
- **"Negative detection latency" as a headline.** The phenomenon is real and
  §4.3 defends it, but the phrasing invites a definitional dispute the result
  does not need.
- **The ~24 ms model-independent constant, and the 92.0 GB/s two-point fit.**
  Both exceeded physical bounds; §3.3 reports the failure instead.
- **The 91 GB/s bandwidth figure.** Superseded by direct measurement.
- **Session-level percentages and anomaly rates** beyond those in §4.4 and
  §5.3 — arbitrary denominators.
- Sixteen further refuted hypotheses from the working notes, of which the
  paper carries the four that teach something methodological.
