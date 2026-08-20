# K1 — Thread/çekirdek taraması: Sonuç

**Tasarım:** 6 tur × 5 kol = 30 koşu, interleaved (`order-seed=7`).
Her kolda **thread başına bir fiziksel P-core** (E2'nin bulgusu gereği:
thread sayısı fiziksel çekirdeği aşınca load balancer patlıyor).
`t16` istisna: 8 fiziksel çekirdek üzerinde 16 thread, SMT'nin katkısını
ölçmek için. Eşik: %2.

| kol | çekirdek | TTFT | prefill tok/s | decode tok/s | ITL p50 | migration |
|---|---|---|---|---|---|---|
| t2 | 2 | 33599 | 14.8 | 5.96 | 161.20 | 39 |
| t4 | 4 | 18005 | 27.5 | 9.02 | 108.25 | 618 |
| t6 | 6 | 13246 | 37.4 | 10.70 | 93.27 | 2 376 |
| t8 | 8 | 10969 | 45.2 | 11.60 | 85.88 | 2 918 |
| t16 | 8 (16 thread) | 10856 | 45.7 | 11.37 | 87.92 | 2 223 170 |

---

## 1. Prefill ve decode farklı ölçekleniyor — asimetri var

2 → 8 çekirdek (4 kat):

| faz | hızlanma | verim |
|---|---|---|
| prefill | 3.06x | **%77** |
| decode | 1.95x | **%49** |

**28 puanlık fark.** Eklenen her çekirdek çiftinin marjinal getirisi:

| geçiş | prefill | decode |
|---|---|---|
| t2 → t4 | +86.6% | +51.5% |
| t4 → t6 | +35.9% | +18.6% |
| t6 → t8 | +20.8% | **+8.4%** |

Decode'un getirisi her adımda prefill'inkinin yaklaşık yarısı kadar ve
daha hızlı sönüyor. **Projenin merkezi hipotezinin aradığı asimetri budur**
— ve bu kez tek değişken (çekirdek sayısı) oynatılarak, her thread kendi
fiziksel çekirdeğinde, 6 tur interleaved ölçülmüş haliyle.

Not: bu, migration'a atfedilip E2 tarafından çürütülen önceki asimetri
iddiasının **yerine geçen** sonuçtur. O iddia yanlış değişkene dayanıyordu;
bu ölçümde karıştırıcı yok.

## 2. Decode 8 çekirdekte tam doymuş değil, ama net yavaşlıyor

CLAUDE.md K1 "erken doyuyorsa bandwidth-bound" diyor. Dürüst cevap:
**decode doymadı ama doyuma gidiyor.** t6→t8 hâlâ +8.4% veriyor, yani
gürültü tabanının 4 katı — sıfır değil. Ancak verim %100'den %49'a
düşmüş durumda ve 8 fiziksel P-core'un ötesini bu makinede test edemeyiz
(o kadar var).

## 3. Sebep bandwidth mi, senkronizasyon mu? — HENÜZ AYRIŞTIRILMADI

İma edilen bellek trafiği t8'de **~66 GB/s** (t2'de 33.8). Bu, DDR5
dual-channel'ın pratik tavanına yakın ve bandwidth-bound açıklamasıyla
tutarlı.

**Ama tutarlılık kanıt değil.** En az iki aday var ve bu veri ikisini
ayırt etmiyor:

- **(a) Bellek bant genişliği tavanı.** Token başına ağırlıkların tamamı
  RAM'den okunuyor.
- **(b) Senkronizasyon maliyeti.** Koşu başına ~2.1 milyon context switch
  ölçülmüştü (token başına ~8200). Her katmanda OpenMP bariyeri var;
  thread arttıkça bariyer maliyeti de artar. Klasik Amdahl seri kesri.

66 GB/s rakamı ayrıca kaba: token başına *bütün* ağırlıkların okunduğunu
varsayıyor, LLC'de kalanları ve KV-cache trafiğini saymıyor.

**Ayırt edici test:** aynı taramayı belirgin daha küçük bir modelle
(ör. 3B Q4) tekrarlamak. Bandwidth-bound ise küçük model orantılı olarak
daha yüksek tok/s verir ama **aynı GB/s tavanına** dayanır; senkronizasyon
sınırlıysa ölçeklenme eğrisinin *şekli* korunur. Bu, ikinci bir model
indirmeyi gerektiriyor — kullanıcının bağlantısı sınırlı olduğu için
şimdilik ertelendi.

Yani **K1 kısmen cevaplandı**: decode'un çekirdek eklemeye getirisi
prefill'in yarısı ve hızla sönüyor. *Neden* sönüdüğü açık değil.

## 4. Fiziksel çekirdek tükendikten sonra SMT hiçbir şey katmıyor

t8 → t16 (aynı 8 çekirdek, thread 8 → 16): prefill **+1.0%**,
decode **−1.9%** — ikisi de %2 eşiğinin içinde, yani fark yok.
Buna karşılık migration 2 918'den **2 223 170**'e fırlıyor.

E2'nin desenini bağımsız olarak doğruluyor: **thread sayısı fiziksel
çekirdek sayısını aştığında load balancer patlıyor** — ve bu patlama yine
ölçülebilir bir zarar vermiyor, ama ölçülebilir bir fayda da vermiyor.

## 5. Scheduler için doğrudan çıkarım

Elde eyleme dönük bir sayı var:

- Decode'a 8 yerine 6 çekirdek vermek throughput'un **%7.8'ine** mal olur.
- Prefill'e 6 yerine 8 çekirdek vermek **+%20.8** kazandırır.

Yani **prefill geniş, decode dar** istiyor — CLAUDE.md'nin faz hipotezinin
tam olarak öngördüğü şey, artık ölçülmüş büyüklüklerle. Faz-farkındalıklı
bir politikanın kâr edeceği alan burasıdır: decode fazında serbest kalan
çekirdekler başka işe verilebilir, decode'a maliyeti tek haneli yüzde.

Bu, S2 (LLM + derleme yükü) senaryosunun neden sıradaki doğru deney
olduğunu da gösteriyor: bu takasın gerçek bir rakip iş yükü varken de
geçerli olup olmadığı orada ölçülür.

---

## Faz 0 / Faz 1 durumu

**Cevaplanan:** K3 (gürültü tabanı %2), affinity varyantları, H3'ün naif
hali (reddedildi), K1 (kısmen — asimetri var, mekanizma belirsiz).

**Açık:** K1'in mekanizması (ikinci model gerekiyor), H1'in temiz testi
(E-core cezası ölçüldü ama migration etkisinden ayrıştırılmadı), H2 ve H5,
`scx_lavd` / `scx_rustland` baseline'ları (kullanıcı onayı gerekir),
S2–S6 senaryoları.
