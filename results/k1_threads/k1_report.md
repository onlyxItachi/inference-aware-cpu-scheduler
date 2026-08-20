# K1 — Thread/çekirdek taraması

**Turlar:** 6 | **Koşu:** 30 | **eşik:** ±2.0%

Her kolda **thread başına bir fiziksel P-core**. t16 hariç: 8 fiziksel çekirdek üzerinde 16 thread (SMT).


## Ham eğriler

| kol | thread | fiz. çekirdek | TTFT (ms) | prefill tok/s | decode tok/s | ITL p50 | migration |
|---|---|---|---|---|---|---|---|
| t2 | 2 | 2 | 33599 | 14.8 | 5.96 | 161.20 | 39 |
| t4 | 4 | 4 | 18005 | 27.5 | 9.02 | 108.25 | 618 |
| t6 | 6 | 6 | 13246 | 37.4 | 10.70 | 93.27 | 2376 |
| t8 | 8 | 8 | 10969 | 45.2 | 11.60 | 85.88 | 2918 |
| t16 | 16 | 8 | 10856 | 45.7 | 11.37 | 87.92 | 2223170 |

## Ölçeklenme (t2 = 1.00x taban)

| kol | çekirdek katı | prefill hızlanma | prefill verim | decode hızlanma | decode verim |
|---|---|---|---|---|---|
| t2 | 1.0x | 1.00x | 100% | 1.00x | 100% |
| t4 | 2.0x | 1.87x | 93% | 1.52x | 76% |
| t6 | 3.0x | 2.54x | 85% | 1.80x | 60% |
| t8 | 4.0x | 3.06x | 77% | 1.95x | 49% |
| t16 | 4.0x | 3.10x | 77% | 1.91x | 48% |

*Verim = hızlanma / çekirdek katı. %100 = mükemmel ölçeklenme; düşüş doyuma işaret eder.*


## Eklenen her çekirdeğin marjinal getirisi

| geçiş | +çekirdek | prefill Δ | decode Δ |
|---|---|---|---|
| t2 → t4 | +2 | +86.6% | +51.5% |
| t4 → t6 | +2 | +35.9% | +18.6% |
| t6 → t8 | +2 | +20.8% | +8.4% |
| t8 → t16 | +0 (SMT, thread 8→16) | +1.0% | -1.9% |

## Ima edilen bellek trafiği (decode)

| kol | decode tok/s | ima edilen GB/s |
|---|---|---|
| t2 | 5.96 | 33.8 |
| t4 | 9.02 | 51.3 |
| t6 | 10.70 | 60.8 |
| t8 | 11.60 | 65.9 |
| t16 | 11.37 | 64.6 |

*Token başına ağırlıkların tamamının okunduğu varsayımıyla kaba bir alt sınır; KV-cache trafiğini ve LLC'de kalan ağırlıkları saymaz.*


## Karar

t2 → t8 (2 → 8 çekirdek): prefill verimi **%77**, decode verimi **%49**.

Prefill, decode'dan **28 puan** daha iyi ölçekleniyor. İki faz çekirdek eklemeye farklı tepki veriyor — projenin aradığı asimetri için doğrudan, tek değişkenli kanıt.
