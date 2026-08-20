# Faz 0 — Gürültü Tabanı (K3)

**Runs:** 20  
**Config:** threads=8, cpus=unpinned, ctx=2048, batch=2048, ubatch=512, seed=42, n_predict=256, prompt_tokens=496


## Spread (same config, repeated)

| metric | median | std | min | max | CV% |
|---|---|---|---|---|---|
| TTFT (ms) | 12127.67 | 57.11 | 12026.53 | 12235.68 | 0.5% |
| ITL p50 (ms) | 98.07 | 0.53 | 97.52 | 99.09 | 0.5% |
| ITL p95 (ms) | 103.52 | 0.77 | 102.22 | 104.97 | 0.7% |
| ITL p99 (ms) | 105.97 | 1.02 | 103.65 | 107.68 | 1.0% |
| ITL max (ms) | 107.79 | 1.63 | 104.03 | 110.74 | 1.5% |
| decode (tok/s) | 10.17 | 0.06 | 10.07 | 10.24 | 0.5% |
| migrations | 8125.00 | 263.26 | 7660.00 | 8722.00 | 3.2% |
| ctx switches | 2106701.00 | 7608.88 | 2096569.00 | 2126894.00 | 0.4% |
| P-core freq (MHz) | 2536.85 | 16.22 | 2515.90 | 2571.10 | 0.6% |
| pkg temp end (C) | 81.50 | 1.96 | 78.00 | 84.00 | 2.4% |

## Drift — does run number predict the result?

| metric | Pearson r vs run | slope /run | verdict |
|---|---|---|---|
| TTFT | +0.671 | +6.4816 | DRIFT |
| ITL p95 | +0.337 | +0.0436 | no trend |
| decode tps | -0.348 | -0.0033 | no trend |
| pkg temp end | +0.381 | +0.1263 | no trend |

*n=20; |r| >= 0.444 is significant at p<0.05. Below that, treat any apparent slope as noise.*


## Thermal coupling

| pair | Pearson r | verdict |
|---|---|---|
| start temp vs TTFT | +0.247 | no coupling |
| start temp vs ITL p95 | -0.224 | no coupling |
| start temp vs decode tps | -0.095 | no coupling |

## Noise floor

| metric | CV% | 95% of repeats fall within |
|---|---|---|
| TTFT | 0.5% | ±0.9% |
| ITL p50 | 0.5% | ±1.1% |
| ITL p95 | 0.7% | ±1.4% |
| decode tps | 0.5% | ±1.1% |

**Sonuç:** Bu makinede, bu konfigürasyonda, **%1.4'ten küçük farklar gürültüdür.** Bunun altındaki hiçbir fark bulgu olarak raporlanamaz.
