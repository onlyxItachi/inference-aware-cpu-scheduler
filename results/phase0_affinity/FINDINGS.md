# Faz 0 — Affinity Varyantları: Sonuç

**Tasarım:** 10 tur × 5 varyant = 50 koşu, **interleaved** (her tur tüm
varyantlar bir kez, karıştırılmış sırayla, `order-seed=1337`).
Tüm kollarda `threads=8` sabit; yalnızca yerleşim değişiyor.
Eşik: **%2** (`results/phase0/FINDINGS.md`).

Interleaving tuttu: her varyantın ortalama tur indeksi tam **5.50**
(beklenen 5.50). Faz 0'daki oturum drift'i hiçbir kola yüklenmedi.

---

## Ana tablo (medyan)

| varyant | yerleşim | TTFT | ITL p50 | ITL p95 | decode | migration |
|---|---|---|---|---|---|---|
| **p_all** | 16 mantıksal P-CPU, serbest | 10989 | 86.06 | 87.10 | **11.59** | 3 276 |
| **p_nosmt** | 8 fiziksel P-core | 11003 | 85.97 | 90.43 | 11.55 | 3 237 |
| unpinned *(baseline)* | serbest | 12107 | 98.55 | 103.71 | 10.13 | 8 053 |
| p_smt_forced | 4 fiziksel P-core, sibling | 17887 | 106.63 | 107.68 | 9.37 | **1 027 373** |
| e_only | 8 E-core | 25032 | 223.36 | 226.21 | 4.48 | 2 237 |

Varyant içi saçılım her kolda CV %0.2–2.1 — yani bütün farklar gürültünün
çok üstünde. Tüm karşılaştırmalar p<0.01 (tek istisna aşağıda).

## 1. P-core'a pinlemek serbest bırakmayı açık farkla yeniyor

`unpinned`'e karşı `p_all`: TTFT **−9.2%**, ITL p50 **−12.7%**,
ITL p95 **−16.0%**, decode **+14.4%**. Hepsi eşiğin 4–8 katı.

Linux'un varsayılan yerleşimi bu iş yükü için açıkça yetersiz. Scheduler
8 thread'i 16 fiziksel çekirdeğe (P **ve** E) yayıyor; sadece P-core'da
tutmak %14 throughput getiriyor. Bu, projenin temel iddiası için doğrudan
kanıt: mevcut varsayımlar bu iş yükünü karşılamıyor.

## 2. `p_all` ile `p_nosmt` ayırt edilemiyor — ve bu da bir sonuç

TTFT farkı %0.1, decode farkı %0.3 — ikisi de eşiğin çok altında.
Beklendiği gibi: 8 thread 16 mantıksal P-CPU'ya bırakıldığında Linux zaten
8 ayrı fiziksel çekirdek seçiyor, sibling'leri kendiliğinden kullanmıyor.

Tek istisna ITL p95: `p_all` 87.10, `p_nosmt` 90.43 (%3.7 fark, eşiğin
üstünde). Yani SMT'yi *yasaklamak* kuyruk gecikmesini bir miktar
kötüleştiriyor — muhtemelen scheduler'ın manevra alanını daraltarak.
Küçük ama gerçek.

## 3. E-core cezası devasa — H1 için güçlü ön kanıt

`e_only`: TTFT **+106.8%**, ITL p50 **+126.7%**, decode **−55.7%**.
Gürültü tabanının 60 katından fazla. E-core'lar hem daha düşük frekanslı
(3700 vs 5000 MHz) hem de dar; decode bunların ikisinden de zarar görüyor.

Not: `e_only` termal olarak en serin koşu (bitiş 67°C, diğerleri 78–86°C).
Enerji açısından ölçülmeye değer, ama gecikme açısından felaket.

## 4. Migration sayısı jitter'ı ÖNGÖRMÜYOR

En önemli metodolojik bulgu bu.

| varyant | migration | ITL CV |
|---|---|---|
| p_smt_forced | 1 027 373 | **0.5%** (en kararlı) |
| unpinned | 8 053 | **3.6%** (en dalgalı) |

`p_smt_forced` 127 kat fazla migration yapıyor ve **en kararlı** gecikmeyi
veriyor. `unpinned` en az migration'lardan biriyle en dalgalısı.

H3'ün naif hali ("migration sayısı token gecikmesini bozar") bu veriyle
**desteklenmiyor**. E1 (`results/e1_residency/`) nedenini gösteriyor:
önemli olan sayı değil, geçilen sınır. `unpinned` tek P↔E sınırı geçen
varyant (2 469 geçiş) ve tek dalgalı olan. `p_all`'da hiç P↔E yok, CV %1.8.

**H3 yeniden formüle edilmeli:** "migration sayısı" değil,
"**P↔E sınırı geçen migration sayısı**".

## 5. ~~Prefill ve decode migration'a çok farklı duyarlı~~ — E2 TARAFINDAN ÇÜRÜTÜLDÜ

**Bu bölümün ilk hali yanlıştı ve düzeltildi. Kayıt için bırakılıyor.**

İlk iddia şuydu: `p_smt_forced`'ın `p_all`'a karşı TTFT +62.8% / ITL p50
+23.9% farkı, prefill'in migration'a decode'dan ~2.6 kat duyarlı olduğunu
gösteriyor.

**E2 bunu çürüttü** (`results/e2_smt/FINDINGS.md`). Aynı 4 fiziksel çekirdek
üzerinde migration sayısı 626'dan 1 029 926'ya (**1644 kat**) çıkarıldığında
TTFT *kötüleşmedi*, %1.7 **iyileşti**. Buna karşılık çekirdek sayısı 4'ten
8'e çıkarıldığında TTFT %38.1 iyileşti.

Yani `p_smt_forced`'ın TTFT cezası migration'dan değil, **8 yerine 4 fiziksel
çekirdek kullanmasından** geliyordu. İki değişken aynı anda değiştiği için
sebep yanlış değişkene atfedilmişti — E2 tam da bunu ayırmak için
tasarlanmıştı ve işini gördü.

Doğru ifade: **bu veride migration sayısı, çekirdek sayısı kontrol
edildiğinde ne TTFT'yi ne ITL'i açıklıyor.** Prefill/decode asimetrisi
iddiası bu ölçümlerle desteklenmiyor; asimetri varsa başka bir deneyle
gösterilmeli.

## Çürütülen hipotez (kayda geçsin)

`p_smt_forced`'ın 1M migration'ının çoğunun **kardeş-içi ve bedava** olduğu
tahmin edilmişti (aynı fiziksel çekirdek, paylaşılan L1/L2). E1 bunu
çürüttü: örneklenen geçişlerin **%85'i fiziksel çekirdek aşırı**
(P→P 18 566, sibling 3 360). Sekiz hesap thread'i 4 fiziksel çekirdeğin
tamamına yayılıyor. Migration'lar gerçekten pahalı; buna rağmen decode
gecikmesi kararlı kalıyor — açıklama "migration ucuzdu" değil,
"decode migration'a duyarsız" olmalı.

## Sıradaki

- **E2** (`results/e2_smt/`): `p_smt_forced`'da çekirdek sayısı mı SMT mi
  suçlu? Dört kol aynı 4 fiziksel çekirdek üzerinde.
- K1 thread taraması (2→4→6→8) — "bandwidth-bound" iddiası ancak bununla
  kurulabilir.
- Kalan Faz 0 baseline'ları: `scx_lavd`, `scx_rustland` (kullanıcı onayıyla).
- S2 (derleme yükü altında) senaryosu.
