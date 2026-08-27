# TASK-C03 observation summary

Selected C03 path: **CROSS_VENDOR**. This is a descriptive minimal generality check; it does not automatically declare that placement behavior or external observability generalizes.

The labels `big` and `compact` are operational labels supplied by the experiment configuration. They do not assert architectural equivalence to Intel P/E cores.

## Performance by arm

| arm | n | TTFT mean / median ms | ITL p95 mean / median ms | decode tps mean |
|---|---:|---:|---:|---:|
| BIG_ONLY | 2 | 12182.535 / 12182.535 | 106.899 / 106.899 | 9.529 |
| ALL_CORES | 2 | 7400.417 / 7400.417 | 98.785 / 98.785 | 10.632 |

## ALL_CORES minus BIG_ONLY

Positive latency values mean ALL_CORES was slower; positive throughput means ALL_CORES had higher throughput. These are observations, not a generality verdict.

| metric | absolute difference | relative difference |
|---|---:|---:|
| ttft_ms | -4782.118 | -39.254% |
| itl_p95_ms | -8.114 | -7.59% |
| decode_tps | 1.103 | 11.575% |

## External signal observations

PHASE_MARK is used only here to label samples offline. The detector ran without a marker callback and never changed affinity.

| arm | phase | n | mean | median | p05 | p95 |
|---|---|---:|---:|---:|---:|---:|
| BIG_ONLY | PREFILL | 1169 | 7.789 | 0.0 | 0.0 | 44.444 |
| BIG_ONLY | DECODE | 2558 | 12.933 | 0.0 | 0.0 | 50.0 |
| ALL_CORES | PREFILL | 700 | 25.326 | 16.0 | 0.0 | 84.25 |
| ALL_CORES | DECODE | 2110 | 4.897 | 0.0 | 0.0 | 17.58 |

## Frozen-threshold behavior

Frozen zero-shot detector: interval=20 ms, hi=3000, lo=2100, k=2.
- BIG_ONLY: transitions 0 / 2; detect relative to internal boundary None
- ALL_CORES: transitions 0 / 2; detect relative to internal boundary None

Offsets are external criterion crossings relative to the first internally marked unbatched decode computation. Negative values are not automatically labeled prediction or anticipation.

## Checkpoint questions

- Does ALL_CORES change TTFT in the expected direction?
- Does it also change decode-tail latency or throughput?
- Are prefill/decode signal distributions observably distinct?
- Did the unchanged frozen threshold transition in every run?
- Do temperature ranges suggest a machine-state confound?
