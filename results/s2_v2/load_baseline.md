# Yük referans hızları (LLM çalışmıyorken, 16 thread, ~42 s)

Bunlar S2'deki yük hızlarının paydası. Rakibin ödediği bedel ancak buna
karşı ifade edilebilir.

| yerleşim | iter/s | serbeste oran |
|---|---|---|
| serbest (24 CPU) | 45 302.6 | 100.0% |
| P-noSMT (8 fiziksel P-core) | 25 428.8 | 56.1% |
| sadece E-core (8 E-core) | 19 865.3 | 43.8% |

Kritik nokta: yükü E-core'a hapsetmek, **LLM hiç çalışmasa bile** ona
throughput'unun %56.2'sini kaybettiriyor. S2'deki D kolunun rakibe faturası
en az bu kadardır; LLM de eklenince daha fazla olabilir.
