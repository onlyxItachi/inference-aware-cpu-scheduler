# TASK-C03 observation summary

Selected C03 path: **CROSS_VENDOR**. This is a descriptive minimal generality check; it does not automatically declare that placement behavior or external observability generalizes.

The labels `big` and `compact` are operational labels supplied by the experiment configuration. They do not assert architectural equivalence to Intel P/E cores.

## Performance by arm

| arm | n | TTFT mean / median ms | ITL p95 mean / median ms | decode tps mean |
|---|---:|---:|---:|---:|
| BIG_ONLY | 6 | 15437.755 / 15346.599 | 109.055 / 108.29 | 9.363 |
| ALL_CORES | 6 | 9035.452 / 8946.066 | 100.666 / 100.499 | 10.422 |

## ALL_CORES minus BIG_ONLY

Positive latency values mean ALL_CORES was slower; positive throughput means ALL_CORES had higher throughput. These are observations, not a generality verdict.

| metric | absolute difference | relative difference |
|---|---:|---:|
| ttft_ms | -6402.303 | -41.472% |
| itl_p95_ms | -8.389 | -7.692% |
| decode_tps | 1.059 | 11.31% |

## Protocol and conservative interpretation

These measurements were collected on the AMD Ryzen AI 9 HX 370 using the C03
AVX2-constrained diagnostic build amendment. The amendment reduces AMD-only
AVX-512 vector-width capability as an additional cross-vendor confound. It
addresses only one vector-width difference and does not make the architectures
equivalent or isolate core topology.

In this four-run smoke, adding the configured compact-core representatives
improved prefill performance. Unlike the historical Intel placement result,
decode-tail latency and decode throughput also improved. Therefore, the Intel
placement inversion did not reproduce on this AMD platform/configuration. This
is a valid negative generality result, not an experiment failure. C03 did not
test the microarchitectural mechanism behind the difference.

## External signal observations

PHASE_MARK is used only here to label samples offline. The detector ran without a marker callback and never changed affinity.

| arm | phase | n | mean | median | p05 | p95 |
|---|---|---:|---:|---:|---:|---:|
| BIG_ONLY | PREFILL | 4434 | 6.308 | 0.0 | 0.0 | 37.5 |
| BIG_ONLY | DECODE | 7802 | 12.426 | 0.0 | 0.0 | 50.0 |
| ALL_CORES | PREFILL | 2569 | 28.977 | 16.667 | 0.0 | 102.609 |
| ALL_CORES | DECODE | 6257 | 4.817 | 0.0 | 0.0 | 17.241 |

## Frozen-threshold behavior

Frozen zero-shot detector: interval=20 ms, hi=3000, lo=2100, k=2.
- BIG_ONLY: transitions 0 / 6; detect relative to internal boundary None
- ALL_CORES: transitions 0 / 6; detect relative to internal boundary None

The frozen Intel thresholds produced 0 / 4 transitions, so zero-shot threshold
transfer failed in this smoke. The reported signal distributions may still
contain phase information, but this smoke does not establish generalized
cross-platform external observability.

Offsets are external criterion crossings relative to the first internally marked unbatched decode computation. Negative values are not automatically labeled prediction or anticipation.

## Checkpoint questions

- Does ALL_CORES change TTFT in the expected direction?
- Does it also change decode-tail latency or throughput?
- Are prefill/decode signal distributions observably distinct?
- Did the unchanged frozen threshold transition in every run?
- Do temperature ranges suggest a machine-state confound?

## Raw artifact archival note

This PR does not contain the raw detector, phase, or server logs. Archive the
complete collaborator-side `results/conference_c03/` directory separately
before the final paper evidence freeze. No absent raw artifact is reconstructed
or represented by this note.
