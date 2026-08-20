# Faz 0 — Affinity Varyantları (interleaved)

**Turlar:** 10  |  **Toplam koşu:** 50  |  **threads:** 8  |  **gürültü tabanı:** ±2.0%

Her tur tüm varyantları bir kez, karıştırılmış sırayla çalıştırdı. Faz 0'da bulunan termal olmayan oturum drift'i böylece tek bir kola yüklenmiyor.


## Interleaving kontrolü

| varyant | n | ortalama tur indeksi |
|---|---|---|
| unpinned | 10 | 5.50 |
| p_nosmt | 10 | 5.50 |
| p_all | 10 | 5.50 |
| p_smt_forced | 10 | 5.50 |
| e_only | 10 | 5.50 |

*Beklenen ≈ 5.50. Belirgin sapma, drift'in o kola yüklendiğini gösterir.*


## Varyant özetleri (medyan)

| varyant | açıklama | TTFT (ms) | ITL p50 (ms) | ITL p95 (ms) | ITL p99 (ms) | ITL max (ms) | decode (tok/s) | migrations | ctx switches |
|---|---|---|---|---|---|---|---|---|---|
| **unpinned** | pinsiz (serbest) | 12107.20 | 98.55 | 103.71 | 105.51 | 107.91 | 10.13 | 8052.50 | 2103400.50 |
| **p_nosmt** | 8 fiziksel P-core, sibling yok | 11003.34 | 85.97 | 90.43 | 92.15 | 95.54 | 11.55 | 3237.00 | 2028686.50 |
| **p_all** | 16 mantıksal P-CPU, serbest | 10988.56 | 86.06 | 87.10 | 90.36 | 94.88 | 11.59 | 3275.50 | 2029203.00 |
| **p_smt_forced** | 4 fiziksel P-core, sibling zorlanmış | 17887.07 | 106.63 | 107.68 | 108.25 | 108.72 | 9.37 | 1027373.00 | 2380327.50 |
| **e_only** | 8 E-core | 25032.00 | 223.36 | 226.21 | 227.33 | 228.01 | 4.48 | 2237.00 | 2034433.50 |

## Varyant içi saçılım (CV%)

| varyant | TTFT | ITL p50 | ITL p95 | decode |
|---|---|---|---|---|
| unpinned | 0.4% | 0.6% | 0.7% | 0.6% |
| p_nosmt | 0.3% | 0.2% | 2.1% | 0.4% |
| p_all | 0.4% | 0.2% | 1.8% | 0.3% |
| p_smt_forced | 0.7% | 0.2% | 0.4% | 0.2% |
| e_only | 0.4% | 0.3% | 0.4% | 0.4% |

## unpinned baseline'ına karşı


### TTFT (ms)  *(baseline medyan 12107.20)*

| varyant | medyan | fark | anlamlılık | karar |
|---|---|---|---|---|
| p_nosmt | 11003.34 | -9.1% | p<0.01 | **DAHA İYİ** |
| p_all | 10988.56 | -9.2% | p<0.01 | **DAHA İYİ** |
| p_smt_forced | 17887.07 | +47.7% | p<0.01 | **DAHA KÖTÜ** |
| e_only | 25032.00 | +106.8% | p<0.01 | **DAHA KÖTÜ** |

### ITL p50 (ms)  *(baseline medyan 98.55)*

| varyant | medyan | fark | anlamlılık | karar |
|---|---|---|---|---|
| p_nosmt | 85.97 | -12.8% | p<0.01 | **DAHA İYİ** |
| p_all | 86.06 | -12.7% | p<0.01 | **DAHA İYİ** |
| p_smt_forced | 106.63 | +8.2% | p<0.01 | **DAHA KÖTÜ** |
| e_only | 223.36 | +126.7% | p<0.01 | **DAHA KÖTÜ** |

### ITL p95 (ms)  *(baseline medyan 103.71)*

| varyant | medyan | fark | anlamlılık | karar |
|---|---|---|---|---|
| p_nosmt | 90.43 | -12.8% | p<0.01 | **DAHA İYİ** |
| p_all | 87.10 | -16.0% | p<0.01 | **DAHA İYİ** |
| p_smt_forced | 107.68 | +3.8% | p<0.01 | **DAHA KÖTÜ** |
| e_only | 226.21 | +118.1% | p<0.01 | **DAHA KÖTÜ** |

### ITL p99 (ms)  *(baseline medyan 105.51)*

| varyant | medyan | fark | anlamlılık | karar |
|---|---|---|---|---|
| p_nosmt | 92.15 | -12.7% | p<0.01 | **DAHA İYİ** |
| p_all | 90.36 | -14.4% | p<0.01 | **DAHA İYİ** |
| p_smt_forced | 108.25 | +2.6% | p<0.01 | **DAHA KÖTÜ** |
| e_only | 227.33 | +115.5% | p<0.01 | **DAHA KÖTÜ** |

### ITL max (ms)  *(baseline medyan 107.91)*

| varyant | medyan | fark | anlamlılık | karar |
|---|---|---|---|---|
| p_nosmt | 95.54 | -11.5% | p<0.01 | **DAHA İYİ** |
| p_all | 94.88 | -12.1% | p<0.01 | **DAHA İYİ** |
| p_smt_forced | 108.72 | +0.8% | ns | gürültü içinde |
| e_only | 228.01 | +111.3% | p<0.01 | **DAHA KÖTÜ** |

### decode (tok/s)  *(baseline medyan 10.13)*

| varyant | medyan | fark | anlamlılık | karar |
|---|---|---|---|---|
| p_nosmt | 11.55 | +14.0% | p<0.01 | **DAHA İYİ** |
| p_all | 11.59 | +14.4% | p<0.01 | **DAHA İYİ** |
| p_smt_forced | 9.37 | -7.4% | p<0.01 | **DAHA KÖTÜ** |
| e_only | 4.48 | -55.7% | p<0.01 | **DAHA KÖTÜ** |

### migrations  *(baseline medyan 8052.50)*

| varyant | medyan | fark | anlamlılık | karar |
|---|---|---|---|---|
| p_nosmt | 3237.00 | -59.8% | p<0.01 | **DAHA İYİ** |
| p_all | 3275.50 | -59.3% | p<0.01 | **DAHA İYİ** |
| p_smt_forced | 1027373.00 | +12658.4% | p<0.01 | **DAHA KÖTÜ** |
| e_only | 2237.00 | -72.2% | p<0.01 | **DAHA İYİ** |

### ctx switches  *(baseline medyan 2103400.50)*

| varyant | medyan | fark | anlamlılık | karar |
|---|---|---|---|---|
| p_nosmt | 2028686.50 | -3.6% | p<0.01 | **DAHA İYİ** |
| p_all | 2029203.00 | -3.5% | p<0.01 | **DAHA İYİ** |
| p_smt_forced | 2380327.50 | +13.2% | p<0.01 | **DAHA KÖTÜ** |
| e_only | 2034433.50 | -3.3% | p<0.01 | **DAHA İYİ** |

---

*Karar kuralı: |fark| < 2.0% ise gürültü sayılır ve istatistiksel anlamlılığa bakılmaz. Eşiğin üstündeyse Welch t-testi ile teyit edilir.*
