# K1 — Thread/çekirdek taraması

**Turlar:** 6 | **Koşu:** 30 | **eşik:** ±2.0%

Her kolda **thread başına bir fiziksel P-core**. t16 hariç: 8 fiziksel çekirdek üzerinde 16 thread (SMT).


## Ham eğriler

| kol | thread | fiz. çekirdek | TTFT (ms) | prefill tok/s | decode tok/s | ITL p50 | migration |
|---|---|---|---|---|---|---|---|
| t2 | 2 | 2 | 18577 | 26.7 | 10.27 | 94.79 | 14 |
| t4 | 4 | 4 | 10116 | 49.0 | 15.61 | 63.92 | 348 |
| t6 | 6 | 6 | 7346 | 67.5 | 17.94 | 55.36 | 2298 |
| t8 | 8 | 8 | 6155 | 80.6 | 18.54 | 53.94 | 3894 |
| t16 | 16 | 8 | 6084 | 81.5 | 18.03 | 55.41 | 2196193 |

## Ölçeklenme (t2 = 1.00x taban)

| kol | çekirdek katı | prefill hızlanma | prefill verim | decode hızlanma | decode verim |
|---|---|---|---|---|---|
| t2 | 1.0x | 1.00x | 100% | 1.00x | 100% |
| t4 | 2.0x | 1.84x | 92% | 1.52x | 76% |
| t6 | 3.0x | 2.53x | 84% | 1.75x | 58% |
| t8 | 4.0x | 3.02x | 75% | 1.80x | 45% |
| t16 | 4.0x | 3.05x | 76% | 1.76x | 44% |

*Verim = hızlanma / çekirdek katı. %100 = mükemmel ölçeklenme; düşüş doyuma işaret eder.*


## Eklenen her çekirdeğin marjinal getirisi

| geçiş | +çekirdek | prefill Δ | decode Δ |
|---|---|---|---|
| t2 → t4 | +2 | +83.6% | +51.9% |
| t4 → t6 | +2 | +37.7% | +14.9% |
| t6 → t8 | +2 | +19.4% | +3.3% |
| t8 → t16 | +0 (SMT, thread 8→16) | +1.2% | -2.7% |

## Ima edilen bellek trafiği (decode)

| kol | decode tok/s | ima edilen GB/s |
|---|---|---|
| t2 | 10.27 | 58.3 |
| t4 | 15.61 | 88.7 |
| t6 | 17.94 | 101.9 |
| t8 | 18.54 | 105.3 |
| t16 | 18.03 | 102.4 |

*Token başına ağırlıkların tamamının okunduğu varsayımıyla kaba bir alt sınır; KV-cache trafiğini ve LLC'de kalan ağırlıkları saymaz.*


## Karar

t2 → t8 (2 → 8 çekirdek): prefill verimi **%75**, decode verimi **%45**.

Prefill, decode'dan **30 puan** daha iyi ölçekleniyor. İki faz çekirdek eklemeye farklı tepki veriyor — projenin aradığı asimetri için doğrudan, tek değişkenli kanıt.
