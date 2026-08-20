# İŞ 2 — Decode'un duvarı: bant genişliği mi, senkronizasyon mu?

**Cevap: ağırlıklı olarak bant genişliği. Senkronizasyonun payı var ama küçük
(~%7.4).**

**Tasarım:** 6 tur × 2 kol = 12 koşu, interleaved (`order-seed=11`).
Model indirilmedi; ayrım aynı 8 fiziksel P-core üzerinde senkronizasyon
yapısını değiştirerek yapıldı.

| kol | yapı | çekirdek |
|---|---|---|
| A | 1 örnek, 8 thread | `0,2,4,6,8,10,12,14` |
| B | 2 bağımsız örnek, 4'er thread | `0,2,4,6` + `8,10,12,14` (ayrık) |

A'da katman başına tek 8-yollu bariyer; B'de iki bağımsız 4-yollu bariyer.
İkisi de aynı ağırlıkları okuyor (llama.cpp mmap kullandığı için iki örnek
aynı fiziksel sayfaları paylaşıyor).

**Geçerlilik kontrolü:** iki örneğin decode pencereleri her koşuda
**≥%99 örtüştü**. Örnekler sırayla değil, gerçekten eşzamanlı koştu.

---

## 1. Ölçülen

| kol | toplam decode tok/s | J/token | duvar süresi |
|---|---|---|---|
| A (1×8 thread) | 11.54 | 10.97 | 33.1 s |
| B (2×4 thread) | **12.39** | **10.48** | 63.3 s |

- **Toplam throughput: +7.4%** (p<0.01, gürültü tabanının 3.7 katı)
- **Enerji/token: −4.5%** (p<0.01)

B'deki tek tek örnek hızları: `[6.20, 6.09]`, `[6.27, 6.18]`, `[6.27, 6.13]`
— iki örnek dengeli, biri diğerini aç bırakmıyor.

## 2. Yorum: iki uç tahmin arasında nerede duruyoruz?

Bu deneyin gücü, iki rakip hipotezin **sayısal tahmin** yapmasında.

K1'den biliyoruz: **4 çekirdek tek başına 9.02 tok/s** veriyor (o ölçümde
diğer 4 çekirdek boştaydı, yani bant genişliği o örneğe kalıyordu).

| hipotez | tahmini toplam | gerçekleşen |
|---|---|---|
| saf **senkronizasyon** duvarı (paylaşılan kaynak yok) | 2 × 9.02 = **18.04** (+56%) | |
| saf **bant genişliği** duvarı | ~11.54 (**+0%**) | |
| **ölçülen** | | **12.39 (+7.4%)** |

Bariyeri ikiye bölmek, saf senkronizasyon hipotezinin öngördüğü kazancın
yalnızca **~%13'ünü** getirdi (7.4 / 56). Geri kalan ~%87, iki örneğin
paylaştığı bir kaynak tarafından yenmiş durumda — bu kaynak bellek bant
genişliğidir.

Bunun doğrudan kanıtı B'deki tek örnek hızları: 4 çekirdek tek başına 9.02
yaparken, ikinci örnek eşzamanlı koşunca **6.2'ye düşüyor** (−%31). İki
örnek arasında paylaşılan tek şey bellek yolu.

## 3. K1'in açık sorusuna cevap

K1 raporunda decode'un %49 ölçeklenme veriminin sebebi belirsiz
bırakılmıştı; iki aday vardı:

- (a) bellek bant genişliği tavanı — **baskın sebep, kanıtlandı**
- (b) OpenMP bariyer maliyeti — **gerçek ama küçük, ~%7.4'lük pay**

**Sonuç: K1'in mekanizması artık kısmen değil, nicel olarak cevaplandı.**
Decode bandwidth-bound; senkronizasyon ikincil bir katkı.

İma edilen bellek trafiği: A'da 65.5 GB/s, B'de 70.4 GB/s. B'nin biraz
daha yükseğe çıkabilmesi, tavanın kesin bir duvar değil, doyma eğrisi
olduğunu gösteriyor.

## 4. Scheduler için ne demek

Bu, sched_ext politikasının **manevra alanını daraltan** bir sonuç
(CLAUDE.md K1 bunu zaten öngörmüştü: "bu kötü haber değil, bulgunun kendisi
olabilir"):

- Decode'a çekirdek eklemek bant genişliği tavanına çarptığı için sınırlı
  fayda verir. Politika, decode'u hızlandırmaya değil, **decode'un
  ihtiyacı olmayan çekirdekleri serbest bırakmaya** odaklanmalı.
- Bu, K1'in "decode'a 8 yerine 6 çekirdek vermek %7.8'e mal olur" bulgusu
  ve S2'nin tahliye sonucuyla aynı yöne işaret ediyor.

Ayrıca **enerji ekseninde küçük ama gerçek bir bulgu**: iki küçük bariyer,
bir büyük bariyerden token başına %4.5 daha az enerji harcıyor. Bariyerde
bekleyen thread'ler bedava değil.

## 5. Sınırlar

- İki örnek aynı modeli okuyor ve mmap sayesinde aynı fiziksel sayfaları
  paylaşıyor. Farklı modeller kullanılsaydı bant genişliği baskısı daha da
  yüksek olurdu; bu ölçüm **iyimser** taraftadır.
- B'nin duvar süresi iki katına yakın (63 s vs 33 s) çünkü iki kat token
  üretiyor. Gecikmeye duyarlı tek bir istek için A hâlâ daha iyi:
  B'de tek bir örneğin ITL'i belirgin kötü (6.2 vs 11.5 tok/s).
  **B toplam throughput'u artırır, tekil gecikmeyi kötüleştirir.**
- Yalnızca 2 örnek test edildi; 3-4 örnekte eğrinin nereye gittiği
  ölçülmedi.
