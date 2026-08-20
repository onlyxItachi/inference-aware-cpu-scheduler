# S2 — Rakip iş yükü altında

**Turlar:** 6 | **Koşu:** 24 | **yük:** 16 thread (loadgen) | **eşik:** ±2.0%


## Ham tablo (medyan)

| kol | açıklama | TTFT | ITL p50 | ITL p95 | decode | migration |
|---|---|---|---|---|---|---|
| **A_no_load** | LLM P-core, yük yok (referans) | 11018 | 85.96 | 90.01 | 11.58 | 2990 |
| **B_both_free** | LLM serbest, yük serbest (Linux varsayılanı) | 17640 | 100.87 | 103.56 | 9.88 | 20335 |
| **C_llmP_loadfree** | LLM P-core, yük serbest | 17739 | 101.39 | 121.95 | 9.66 | 48314 |
| **D_llmP_loadE** | LLM P-core, yük E-core'a sürülmüş | 11550 | 87.77 | 88.75 | 11.37 | 12611 |

## Boşta referansa (A_no_load) karşı: çekişme ne kadara mal oluyor?


**TTFT (ms)** *(referans 11017.97)*

| kol | medyan | fark | anlamlılık |
|---|---|---|---|
| B_both_free | 17639.79 | +60.1% | p<0.01 |
| C_llmP_loadfree | 17739.06 | +61.0% | p<0.01 |
| D_llmP_loadE | 11549.85 | +4.8% | p<0.01 |

**ITL p50 (ms)** *(referans 85.96)*

| kol | medyan | fark | anlamlılık |
|---|---|---|---|
| B_both_free | 100.87 | +17.3% | p<0.01 |
| C_llmP_loadfree | 101.39 | +18.0% | p<0.01 |
| D_llmP_loadE | 87.77 | +2.1% | p<0.01 |

**ITL p95 (ms)** *(referans 90.01)*

| kol | medyan | fark | anlamlılık |
|---|---|---|---|
| B_both_free | 103.56 | +15.0% | p<0.01 |
| C_llmP_loadfree | 121.95 | +35.5% | p<0.01 |
| D_llmP_loadE | 88.75 | -1.4% | ns |

**ITL p99 (ms)** *(referans 90.48)*

| kol | medyan | fark | anlamlılık |
|---|---|---|---|
| B_both_free | 106.23 | +17.4% | p<0.01 |
| C_llmP_loadfree | 123.76 | +36.8% | p<0.01 |
| D_llmP_loadE | 90.45 | -0.0% | ns |

**decode (tok/s)** *(referans 11.58)*

| kol | medyan | fark | anlamlılık |
|---|---|---|---|
| B_both_free | 9.88 | -14.7% | p<0.01 |
| C_llmP_loadfree | 9.66 | -16.6% | p<0.01 |
| D_llmP_loadE | 11.37 | -1.8% | p<0.01 |

**migrations** *(referans 2990.00)*

| kol | medyan | fark | anlamlılık |
|---|---|---|---|
| B_both_free | 20335.00 | +580.1% | p<0.01 |
| C_llmP_loadfree | 48314.00 | +1515.9% | p<0.05 |
| D_llmP_loadE | 12611.00 | +321.8% | p<0.05 |

## Linux varsayılanının (B_both_free) açığını kapatma oranı

Yerleştirme tek başına, çekişmenin verdiği hasarın ne kadarını geri alıyor? %100 = yükü tamamen etkisizleştirdi.

| metrik | referans (A) | varsayılan (B) | C | D | C kapattı | D kapattı |
|---|---|---|---|---|---|---|
| TTFT (ms) | 11017.97 | 17639.79 | 17739.06 | 11549.85 | -1% | 92% |
| ITL p50 (ms) | 85.96 | 100.87 | 101.39 | 87.77 | -3% | 88% |
| ITL p95 (ms) | 90.01 | 103.56 | 121.95 | 88.75 | -136% | 109% |
| ITL p99 (ms) | 90.48 | 106.23 | 123.76 | 90.45 | -111% | 100% |
| decode (tok/s) | 11.58 | 9.88 | 9.66 | 11.37 | -13% | 87% |
| migrations | 2990.00 | 20335.00 | 48314.00 | 12611.00 | -161% | 45% |

*Negatif oran, o kolun varsayılandan daha kötü olduğunu gösterir.*
