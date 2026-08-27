# TASK-C03 observation summary

Selected C03 path: **CROSS_VENDOR**. This is a descriptive minimal generality check; it does not automatically declare that placement behavior or external observability generalizes.

The labels `big` and `compact` are operational labels supplied by the experiment configuration. They do not assert architectural equivalence to Intel P/E cores.

## Performance by arm

| arm | n | TTFT mean / median ms | ITL p95 mean / median ms | decode tps mean |
|---|---:|---:|---:|---:|
| BIG_ONLY | 2 | 15196.969 / 15196.969 | 107.126 / 107.126 | 9.505 |
| ALL_CORES | 2 | 9189.506 / 9189.506 | 99.285 / 99.285 | 10.549 |

## ALL_CORES minus BIG_ONLY

Positive latency values mean ALL_CORES was slower; positive throughput means ALL_CORES had higher throughput. These are observations, not a generality verdict.

| metric | absolute difference | relative difference |
|---|---:|---:|
| ttft_ms | -6007.463 | -39.531% |
| itl_p95_ms | -7.841 | -7.319% |
| decode_tps | 1.044 | 10.984% |

## External signal observations

PHASE_MARK is used only here to label samples offline. The detector ran without a marker callback and never changed affinity.

| arm | phase | n | mean | median | p05 | p95 |
|---|---|---:|---:|---:|---:|---:|
| BIG_ONLY | PREFILL | 1454 | 6.227 | 0.0 | 0.0 | 37.5 |
| BIG_ONLY | DECODE | 2562 | 12.434 | 0.0 | 0.0 | 50.0 |
| ALL_CORES | PREFILL | 864 | 36.693 | 20.833 | 0.0 | 136.842 |
| ALL_CORES | DECODE | 2060 | 4.828 | 0.0 | 0.0 | 17.241 |

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
