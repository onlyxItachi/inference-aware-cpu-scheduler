# S2 — Rakip iş yükü altında

**Turlar:** 6 | **Koşu:** 24 | **yük:** 16 thread (loadgen) | **eşik:** ±2.0%


## Ham tablo (medyan)

| kol | açıklama | TTFT | ITL p50 | ITL p95 | decode | migration |
|---|---|---|---|---|---|---|
| **A_no_load** | LLM P-core, yük yok (referans) | 10979 | 86.06 | 90.13 | 11.54 | 3739 |
| **B_both_free** | LLM serbest, yük serbest (Linux varsayılanı) | 17717 | 100.96 | 103.85 | 9.86 | 21680 |
| **C_llmP_loadfree** | LLM P-core, yük serbest | 17743 | 101.70 | 124.40 | 9.18 | 121632 |
| **D_llmP_loadE** | LLM P-core, yük E-core'a sürülmüş | 11532 | 87.76 | 89.26 | 11.36 | 15808 |

## Boşta referansa (A_no_load) karşı: çekişme ne kadara mal oluyor?


**TTFT (ms)** *(referans 10978.65)*

| kol | medyan | fark | anlamlılık |
|---|---|---|---|
| B_both_free | 17717.42 | +61.4% | p<0.01 |
| C_llmP_loadfree | 17743.50 | +61.6% | p<0.01 |
| D_llmP_loadE | 11531.93 | +5.0% | p<0.01 |

**ITL p50 (ms)** *(referans 86.06)*

| kol | medyan | fark | anlamlılık |
|---|---|---|---|
| B_both_free | 100.96 | +17.3% | p<0.01 |
| C_llmP_loadfree | 101.70 | +18.2% | p<0.01 |
| D_llmP_loadE | 87.76 | +2.0% | p<0.01 |

**ITL p95 (ms)** *(referans 90.13)*

| kol | medyan | fark | anlamlılık |
|---|---|---|---|
| B_both_free | 103.85 | +15.2% | p<0.01 |
| C_llmP_loadfree | 124.40 | +38.0% | p<0.01 |
| D_llmP_loadE | 89.26 | -1.0% | ns |

**ITL p99 (ms)** *(referans 91.95)*

| kol | medyan | fark | anlamlılık |
|---|---|---|---|
| B_both_free | 105.54 | +14.8% | p<0.01 |
| C_llmP_loadfree | 126.19 | +37.2% | p<0.01 |
| D_llmP_loadE | 90.33 | -1.8% | ns |

**decode (tok/s)** *(referans 11.54)*

| kol | medyan | fark | anlamlılık |
|---|---|---|---|
| B_both_free | 9.86 | -14.6% | p<0.01 |
| C_llmP_loadfree | 9.18 | -20.5% | p<0.01 |
| D_llmP_loadE | 11.36 | -1.6% | p<0.01 |

**migrations** *(referans 3739.00)*

| kol | medyan | fark | anlamlılık |
|---|---|---|---|
| B_both_free | 21680.00 | +479.8% | p<0.01 |
| C_llmP_loadfree | 121632.50 | +3153.1% | p<0.01 |
| D_llmP_loadE | 15808.50 | +322.8% | p<0.01 |

## Linux varsayılanının (B_both_free) açığını kapatma oranı

Yerleştirme tek başına, çekişmenin verdiği hasarın ne kadarını geri alıyor? %100 = yükü tamamen etkisizleştirdi.

| metrik | referans (A) | varsayılan (B) | C | D | C kapattı | D kapattı |
|---|---|---|---|---|---|---|
| TTFT (ms) | 10978.65 | 17717.42 | 17743.50 | 11531.93 | -0% | 92% |
| ITL p50 (ms) | 86.06 | 100.96 | 101.70 | 87.76 | -5% | 89% |
| ITL p95 (ms) | 90.13 | 103.85 | 124.40 | 89.26 | -150% | 106% |
| ITL p99 (ms) | 91.95 | 105.54 | 126.19 | 90.33 | -152% | 112% |
| decode (tok/s) | 11.54 | 9.86 | 9.18 | 11.36 | -41% | 89% |
| migrations | 3739.00 | 21680.00 | 121632.50 | 15808.50 | -557% | 33% |

*Negatif oran, o kolun varsayılandan daha kötü olduğunu gösterir.*


## Rakibin ödediği bedel

LLM tarafındaki kazanç, yükün kaybıyla birlikte okunmadan bir politika iddiası kurulamaz.

Yükün LLM'siz referans hızları: serbest 45,303 it/s, sadece E-core 19,865 it/s (%44).

| kol | yük yerleşimi | yük it/s | serbest referansa oran | kendi yerleşim referansına oran |
|---|---|---|---|---|
| B_both_free | unpinned | 38,707 | 85% | 85% |
| C_llmP_loadfree | unpinned | 38,887 | 86% | 86% |
| D_llmP_loadE | 16-23 | 17,954 | 40% | 90% |

*İkinci sütun politikanın rakibe toplam faturası; üçüncüsü bu faturanın ne kadarının yerleşimden (E-core'a sürülmekten) geldiğini, ne kadarının LLM ile çekişmeden geldiğini ayırır.*
