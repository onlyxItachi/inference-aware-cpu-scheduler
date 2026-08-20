# E2 — Migration patlamasının sebebi: SMT mi, çekirdek sayısı mı?

**Tasarım:** 6 tur × 4 kol = 24 koşu, interleaved (`order-seed=99`).
A, B, C **aynı 4 fiziksel çekirdek** üzerinde; yalnızca sibling erişimi ve
thread sayısı değişiyor. Eşik: %2.

| kol | cpus | thread | fiziksel çekirdek | TTFT | ITL p50 | decode | **migration** |
|---|---|---|---|---|---|---|---|
| A_4core_smt | `0-7` | 8 | 4 | 17668 | 106.53 | 9.38 | **1 029 926** |
| B_4core_nosmt | `0,2,4,6` | 8 | 4 | 18235 | 120.08 | 8.21 | **668 632** |
| C_4core_1to1 | `0,2,4,6` | 4 | 4 | 17974 | 108.24 | 9.05 | **626** |
| D_8core_ref | `0-15` | 8 | 8 | 10943 | 85.93 | 11.62 | 2 524 |

---

## 1. SMT hipotezi çürüdü

Patlamanın "kardeş çekirdeğin var olmasından" kaynaklandığı düşünülmüştü.
Değil: **B'de hiç sibling yok ve yine de 668 632 migration var.**

Ayırt edici desen thread sayısı ile fiziksel çekirdek sayısının oranı:

| durum | thread vs fiziksel çekirdek | migration |
|---|---|---|
| A | 8 > 4 | 1 029 926 |
| B | 8 > 4 | 668 632 |
| C | 4 = 4 | 626 |
| D | 8 = 8 | 2 524 |

**Patlama, hesap thread'i sayısı fiziksel çekirdek sayısını aştığında
oluşuyor.** SMT'nin varlığı büyüklüğü değiştiriyor (A > B) ama olayın
sebebi değil. Thread'ler çekirdeklerden çoksa load balancer sürekli
"dengesizlik" bulup thread'leri karıştırıyor.

## 2. Migration sayısının ölçülebilir bir zararı yok

En net test bu. **Aynı 4 fiziksel çekirdek**, migration 626 → 1 029 926
(**1644 kat**):

| metrik | C (626 mig) | A (1.03M mig) | fark |
|---|---|---|---|
| TTFT | 17974 | 17668 | **−1.7%** |
| ITL p50 | 108.24 | 106.53 | **−1.6%** |
| ITL p95 | 117.31 | 107.55 | **−8.3%** |
| decode | 9.05 | 9.38 | **+3.7%** |

Migration 1644 kat arttı ve **her metrik iyileşti**. (A'nın 8, C'nin 4
thread'i olduğu için A'nın bir miktar önde olması zaten bekleniyordu;
buradaki nokta, patlamanın hiçbir zarar getirmemesi.)

**H3'ün naif hali bu veriyle reddedilir:** ham migration sayısı bu iş
yükünde token gecikmesini öngörmüyor.

## 3. Belirleyici değişken fiziksel çekirdek sayısı

4 → 8 fiziksel çekirdek (ikisi de 8 thread): TTFT **−38.1%**,
ITL p50 **−19.3%**, decode **+23.8%**. Hepsi eşiğin 10–19 katı, p<0.01.

Karşılaştırma için: C'nin migration'ı D'ninkinden **az** (626 vs 2524) ama
TTFT'si %64 **kötü**. Çekirdek sayısı açıklıyor, migration açıklamıyor.

## 4. Aşırı abonelik, sibling yokken gerçekten zararlı

C → B (aynı 4 mantıksal CPU, thread 4 → 8): decode **−9.3%**,
ITL p50 **+10.9%**. Yani çekirdek başına iki thread sıkıştırmak, gidecek
kardeş çekirdek yoksa yarım thread sayısından **daha kötü**.

Buna karşılık A (aynı 8 thread, sibling var) B'den **+14.3%** daha hızlı.
Yani bu rejimde **SMT faydalı** — milyonluk migration onun bir semptomu,
maliyeti değil.

## 5. Doyum işareti

Aynı 4 çekirdek üzerinde thread'i 4'ten 8'e çıkarmak (C → A) decode'a
yalnızca **+3.7%** kazandırıyor. Çekirdek sayısını ikiye katlamak ise
(A → D) **+23.8%**. Hesap kaynağı çekirdek düzeyinde doymuş görünüyor.

Bu, K1'in ("decode bandwidth-bound mu?") *işaretidir ama cevabı değildir* —
K1 ancak 2→4→6→8 thread taramasıyla cevaplanır. Şu an elimizde 4 ve 8
thread'in yalnızca kısıtlı çekirdek kümelerindeki hali var.

---

## Bu deneyin projeye kazandırdığı

İki hipotez çürütüldü (biri benim, biri H3'ün naif hali). Kalan sağlam
sonuçlar:

- **Fiziksel çekirdek sayısı ve P/E yerleşimi belirleyici; migration sayısı
  değil.** Bir sched_ext politikası bu iş yükü için migration'ı azaltmayı
  değil, thread'leri P-core'da ve çekirdek başına birden fazla hesap
  thread'i olmayacak şekilde tutmayı hedeflemeli.
- **H3 yeniden yazılmalı.** Ham sayı yerine yalnızca P↔E sınırı geçen
  migration'lar aday; o da (affinity bulgusu 4) henüz E-core yavaşlığından
  ayrıştırılmadı.
