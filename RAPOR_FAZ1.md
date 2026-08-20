# Faz 1 — Oturum Raporu

**Tarih:** 2026-07-18 / 19
**Donanım, model, binary:** önceki oturumla aynı
(`RAPOR.md`, model sha256 `03b74727…`, llama.cpp `571d0d5`)
**Bu oturumda yeni ölçüm:** 23 koşu (10 H5 + 12 İŞ 2 + doğrulama koşuları)
**Scheduler yazılmadı, `scxctl` çalıştırılmadı.**

Rapor üç bölüme ayrılmıştır: **ölçülen sayılar**, **yorumlar**,
**çürütülen/çürütülmeyen hipotezler**.

---

# A. ÖLÇÜLEN SAYILAR

## A.1 İŞ 1 / H5 — faz tespiti

Dedektör: `ctx_switch_rate > 20 000/s`, 2 ardışık örnek. Sinyal
`/proc/<pid>/task/<tid>/sched`'den; **uygulama enstrümante edilmedi**.

| ölçüm | değer |
|---|---|
| doğruluk (10 koşu) | medyan **%99.60**, min %99.48 |
| tespit gecikmesi | medyan **−133 ms**, p95 −121 ms |
| kaçırılan geçiş | **0 / 10** |
| prefill ctx hızı (p95) | 5 803/s |
| decode ctx hızı (p5) | 31 584/s |
| ayrışma | **5.4 kat** |

Hem pinli (5 koşu) hem pinsiz (5 koşu) konfigürasyonda çalıştı.

**Negatif gecikmenin ayrıştırılması:** sunucunun `prompt eval time` =
11 013.8 ms, aynı koşuda istemci TTFT = 11 040.5 ms → istemci gecikmesi
**26.7 ms**. Yani −133 ms'nin ~27 ms'si iletim, kalan **~106 ms'si**
sıçramanın prefill kuyruğunda başlaması.

**Örnekleme periyodu taraması** (veri seyreltilerek):

| periyot | doğruluk | gecikme p50 | gecikme p95 | daemon maliyeti |
|---|---|---|---|---|
| 20 ms | %99.58 | −133.1 ms | −120.7 ms | %8.6 |
| 60 ms | %99.63 | −101.6 ms | −79.5 ms | %2.9 |
| **100 ms** | **%99.66** | **−78.7 ms** | **−20.7 ms** | **%1.7** |
| 200 ms | %99.69 | +49.6 ms | +140.6 ms | %0.9 |

*(maliyet = tek çekirdeğin yüzdesi; örnek başına 1.7 ms, 34 thread dosyası)*

## A.2 İŞ 2 — decode'un duvarı

12 koşu, 6 tur interleaved. **Örtüşme her koşuda ≥%99** (geçerlilik şartı).

| kol | toplam decode tok/s | J/token | duvar |
|---|---|---|---|
| A: 1 örnek × 8 thread | 11.54 | 10.97 | 33.1 s |
| B: 2 örnek × 4 thread | **12.39** | **10.48** | 63.3 s |

- toplam throughput **+7.4%** (p<0.01)
- enerji/token **−4.5%** (p<0.01)
- B'de tek örnek hızları: `[6.20, 6.09]`, `[6.27, 6.18]`, `[6.27, 6.13]`
- ima edilen bant genişliği: A 65.5 GB/s, B 70.4 GB/s

Referans nokta (K1, önceki oturum): **4 çekirdek tek başına 9.02 tok/s.**

## A.3 İŞ 3 — BLAS

| derleme | prefill | TTFT | decode |
|---|---|---|---|
| mevcut (`GGML_LLAMAFILE=ON`) | 45.0 tok/s | 11 013 ms | 11.23 |
| `GGML_LLAMAFILE=OFF` | 45.2 tok/s | 10 977 ms | 11.54 |
| `GGML_BLAS=ON` (netlib referans) | **1.1 tok/s** | **440 202 ms** | 11.52 |

Roofline:

| | değer |
|---|---|
| prefill iş yükü (2·N_param·N_token) | 8.93 TFLOP |
| ölçülen | **811 GFLOPS** |
| AVX2 fp32 tavanı (8×4.4 GHz×32 flop/cy) | 1126 GFLOPS |
| tavanın yüzdesi | **%72** |

## A.4 Enerji

RAPL düğümleri oturum başında root-only'di; izin oturum ortasında verildi.
Bu yüzden **H5 koşularının bir kısmında enerji yok**, İŞ 2'nin tamamında
var. İŞ 2 enerji sonuçları A.2'de.

---

# B. YORUMLAR

Bunlar ölçüm değil, ölçümden çıkarılan sonuçlardır.

## B.1 H5 doğrulandı — ama runtime'a bağlı

Prefill/decode sınırı, yalnızca `/proc`'tan okunabilen sinyallerle %99.6
doğrulukla ve negatif gecikmeyle tespit edilebiliyor. 100 ms örnekleme
yeterli ve maliyeti tek çekirdeğin %1.7'si — CLAUDE.md'nin "yavaş yol
(userspace daemon, saniye)" mimarisiyle uyumlu.

**Çekince (önemli):** dedektör llama.cpp'yi enstrümante etmiyor, ama
ayırt edici sinyal llama.cpp'nin thread mimarisinin sonucu. Yüksek ctx
switch hızı, OpenMP bariyerlerinin futex üzerinden uyuyup uyanmasından
geliyor. Bariyerde spin-wait yapan farklı bir runtime bu sinyali
üretmeyebilir.

Doğru ifade: *"OS iş yükünü anlıyor — llama.cpp sınıfı, bariyer-senkronize
CPU inference runtime'ları için."* "Her LLM runtime'ı için" iddiası bu
veriyle kurulmadı ve kurulmamalı.

Erken tetikleme bir kusur değil, avantaj: politika faz geçişini ~100 ms
öncesinden haber alıyor. Maliyeti, 11 s'lik prefill'in son %1'inde yanlış
sınıflandırma.

## B.2 Decode bandwidth-bound — nicel olarak

İŞ 2'nin gücü, iki rakip hipotezin **sayısal tahmin yapmasında**:

| hipotez | tahmin edilen toplam |
|---|---|
| saf senkronizasyon duvarı (paylaşılan kaynak yok) | 2 × 9.02 = 18.04 (**+56%**) |
| saf bant genişliği duvarı | 11.54 (**+0%**) |
| **ölçülen** | **12.39 (+7.4%)** |

Bariyeri ikiye bölmek, senkronizasyon hipotezinin öngördüğü kazancın
yalnızca **~%13'ünü** getirdi (7.4/56). Doğrudan kanıt: 4 çekirdek tek
başına 9.02 tok/s yaparken, ikinci örnek eşzamanlı koşunca **6.2'ye
düşüyor** (−%31). İki örneğin paylaştığı tek şey bellek yolu.

**K1'in açık bıraktığı mekanizma sorusu kapandı:** decode ağırlıklı olarak
bandwidth-bound; senkronizasyon gerçek ama ikincil (~%7.4'lük pay).

Yan bulgu: iki küçük bariyer bir büyükten token başına %4.5 daha az enerji
harcıyor — bariyerde bekleyen thread'ler bedava değil.

## B.3 Asimetri artık ölçülmüş değil, AÇIKLANMIŞ

Önceki oturumun merkezi bulgusu (prefill %77 / decode %49 ölçeklenme
verimi) bu oturumda hem savunuldu hem mekanik açıklamasına kavuştu:

- **prefill neden iyi ölçekleniyor:** compute-bound ve donanım tavanının
  %72'sinde — çekirdek eklemek doğrudan FLOPS ekliyor (İŞ 3)
- **decode neden kötü ölçekleniyor:** bandwidth-bound (İŞ 2)

İkisi aynı iş yükünün iki fazı ve **farklı kaynaklara** dayanıyorlar.
Projenin merkezi hipotezi için bundan daha temiz bir dayanak yok.

## B.4 Scheduler için birleşik tablo

Üç oturumun sayıları aynı politikaya işaret ediyor:

| bulgu | kaynak | politika sonucu |
|---|---|---|
| decode'a 8 yerine 6 çekirdek = −%7.8 | K1 | decode fazında çekirdek iade et |
| prefill'e 6 yerine 8 çekirdek = +%20.8 | K1 | prefill fazında geniş ver |
| decode bandwidth-bound (+%7.4 tavan) | İŞ 2 | decode'u hızlandırmaya çalışma |
| rakibi E'ye sürmek hasarın %89–112'sini alır | S2 | tahliye et, izole etme |
| faz tespiti %99.6, −133 ms, %1.7 maliyet | H5 | fazı görmek mümkün ve ucuz |

Politika şu hale geliyor: **fazı 100 ms periyotla izle; prefill'de
P-core'ları LLM'e geniş ver; decode'a girince çekirdek iade et ve rakibi
E-core'a sür.** Her bileşeni ayrı ayrı ölçülmüş durumda.

## B.5 Hâlâ bir öncelik kararı

Önceki oturumun S2 v2 uyarısı geçerli: rakibi E-core'a sürmek eşit
ağırlıklı toplam throughput'ta Linux varsayılanının **gerisinde** kalıyor
(138.0% vs 170.9%). Faz farkındalığının vaadi bu farkı kapatmak — decode
fazında çekirdek iade ederek — ama **bu henüz ölçülmedi**, çünkü scheduler
yazılmadı. Faz 2/3'ün asıl sınavı bu olacak.

---

# C. HİPOTEZ DURUMU

## C.1 Bu oturumda çürütülenler

**Yok.** Bu oturumda kurulan hipotezlerin hiçbiri çürümedi; ikisi
doğrulandı (H5, bandwidth), biri reddedildi (BLAS karıştırıcısı).

## C.2 Bu oturumda REDDEDİLEN endişe

| endişe | sonuç |
|---|---|
| "prefill yapay olarak zayıf, asimetri derleme artefaktı olabilir" | **Reddedildi.** Prefill AVX2 tavanının %72'sinde; tinyBLAS açık/kapalı fark etmiyor; referans BLAS 40 kat kötüleştiriyor. |

## C.3 Önceki oturumlardan devreden çürütülmüş hipotezler

Disiplinin sürekliliği için tekrar listeleniyor (detay: `RAPOR.md` §5):

| # | hipotez | çürüten |
|---|---|---|
| 1 | "1M migration çoğunlukla bedava kardeş-içi sekmedir" | E1 (%85'i çekirdek aşırı) |
| 2 | "Migration patlamasının sebebi SMT" | E2 (sibling'siz kolda da 668k) |
| 3 | "Prefill migration'a decode'dan duyarlı" | E2 (ceza çekirdek sayısından) |
| 4 | H3 naif hali: "migration sayısı gecikmeyi bozar" | E2 + S2 (1644 kat arttı, iyileşti) |

## C.4 Hipotez tahtası — güncel

| hipotez | durum |
|---|---|
| **H5** — faz tespiti uygulamadan yardım almadan | **DOĞRULANDI** (bu runtime için; B.1 çekincesi) |
| **K1** — decode bandwidth-bound mu | **DOĞRULANDI, nicel** (~%87 bandwidth, ~%13 senkronizasyon) |
| **K3** — gürültü tabanı | **CEVAPLANDI**: %2 |
| **H1** — decode E-core'a düşünce gecikme artar | **kısmen**: E-only cezası ölçüldü (decode −%55.7) ama koşu-içi taşınmadan ayrıştırılmadı |
| **H3** — migration token gecikmesini etkiler | **NAİF HALİ REDDEDİLDİ**; yalnızca P↔E geçişleri aday, o da E-core yavaşlığından ayrıştırılmadı |
| **H4** — hibrit CPU'lar Linux varsayımlarını zorlar | **DESTEKLENİYOR**: P-pinning +%14.4, tahliye politikası %89–112 |
| **H2** — prefill/decode girişimi | **TEST EDİLMEDİ** |
| **K2** — scheduler duyarlılığı | **kısmen**: statik yerleşim %14–60 arası etki gösterdi, yani duyarlılık var |

---

# D. AÇIK KALANLAR

| konu | ne gerekiyor |
|---|---|
| **H5 genelliği** | ikinci bir runtime (spin-wait yapılandırması ya da farklı motor) |
| **H5 çekişme altında** | 16 rakip thread varken dedektör test edilmedi |
| **H5 kısa decode** | yalnızca 256 token test edildi; 5-10 token'lık üretimde davranış bilinmiyor |
| **H2** | eşzamanlı prefill + decode girişimi |
| **H1 temiz testi** | decode'u koşu ortasında E-core'a taşıyan deney |
| **scx_lavd / scx_rustland** | **kullanıcı onayı gerekir** (CLAUDE.md kural 6) |
| **S3–S6** | tarayıcı, çoklu örnek, indeksleme, termal |
| **Faz 2/3'ün asıl sınavı** | faz farkındalığı, S2 v2'deki toplam-throughput açığını kapatabiliyor mu |

---

# E. YENİ ARAÇLAR

| dosya | işi |
|---|---|
| `harness/h5_capture.py` | telemetri zaman serisi + yer-gerçeği, tek zaman tabanında |
| `harness/h5_runs.py` | iki yerleşimde interleaved H5 koşuları |
| `harness/h5_detector.py` | eşik dedektörü + doğruluk/gecikme değerlendirmesi |
| `harness/i2_dual_instance.py` | çift örnek eşzamanlı koşu, örtüşme doğrulamalı |
| `llama.cpp/build-nollamafile/` | `GGML_LLAMAFILE=OFF` kontrol derlemesi |
| `llama.cpp/build-blas/` | `GGML_BLAS=ON` kontrol derlemesi |

Telemetri artık RAPL paket enerjisini de kaydediyor (izin verildikten
sonraki koşularda).

---

# Tek paragraflık özet

Üç iş de tamamlandı. **H5 doğrulandı:** prefill/decode sınırı, uygulamaya
hiç dokunmadan, yalnızca `/proc`'tan okunan context-switch hızıyla %99.6
doğrulukla ve **negatif** gecikmeyle (−133 ms, yani sınırdan önce) tespit
ediliyor; 100 ms örneklemede maliyet tek çekirdeğin %1.7'si. Çekincesi:
sinyal llama.cpp'nin bariyer mimarisinin sonucu, dolayısıyla iddia bu
runtime sınıfıyla sınırlı. **K1'in mekanizması nicel olarak kapandı:** iki
bağımsız örneği ayrı çekirdek setlerinde koşturmak toplam throughput'u
yalnızca %7.4 artırdı; saf senkronizasyon hipotezi %56 öngörüyordu, yani
duvarın ~%87'si bellek bant genişliği. **BLAS karıştırıcısı reddedildi:**
prefill AVX2 tavanının %72'sinde çalışıyor, tinyBLAS açık/kapalı fark
etmiyor, kurulu referans BLAS ise prefill'i 40 kat kötüleştiriyor — yani
asimetri derleme artefaktı değil. Bunun sonucunda merkezi bulgu artık
sadece ölçülmüş değil **açıklanmış**: prefill compute-bound ve tavana yakın,
decode bandwidth-bound; iki faz farklı kaynaklara dayanıyor. Faz 2/3 için
politika bileşenlerinin hepsi ayrı ayrı ölçüldü, ama faz farkındalığının
S2 v2'de görülen toplam-throughput açığını kapatıp kapatmadığı henüz
ölçülmedi — asıl sınav o.
