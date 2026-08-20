# Faz 1 Kapanış — Oturum Raporu

**Tarih:** 2026-07-19
**Yeni ölçüm:** 72 koşu (10 çekişme + 20 prompt taraması + 18 E-core +
9 çekirdek taraması + 15 thread-sayısı testi)
**Scheduler yazılmadı, `scxctl` çalıştırılmadı.**

Bölümler: **ölçülen sayılar** / **yorumlar** / **çürütülen hipotezler** /
**hipotez tahtası** / **açık kalanlar**.

---

# A. ÖLÇÜLEN SAYILAR

## A.1 İŞ 1 — Faz payları ve naif politikanın projeksiyonu

Mevcut veriden hesap, yeni koşu yok:

| | değer |
|---|---|
| prefill süresi (8 çekirdek) | 10.97 s (**%33.2**) |
| decode süresi (256 token) | 22.08 s (**%66.8**) |
| toplam | 33.04 s |

Decode'da 8→6 çekirdek iadesi:

| | değer |
|---|---|
| decode tok/s | 11.60 → 10.70 (**−%7.7**) |
| toplam koşu süresi | 33.04 → 34.89 s (+%5.6) |
| serbest kalan P kapasitesi | **%17.1** |
| 8→7 iadesi (interpolasyon) | −%3.9 |

Eşit ağırlıklı toplam tablosu:

| senaryo | LLM | yük | toplam |
|---|---|---|---|
| B (Linux varsayılanı) | 85.4% | 85.4% | **170.9%** |
| D (statik) | 98.4% | 39.6% | 138.0% |
| faz-aware projeksiyon | 90.8% | 49.2% | **140.0%** |

## A.2 İŞ 2a — H5 çekişme altında (10 koşu)

Normalize sinyal (ctx/CPU-saniye), prefill p95 vs decode p5:

| koşu tipi | ayrışma aralığı |
|---|---|
| çekişme, B (LLM serbest) | 6.7 – 9.1× |
| çekişme, D (LLM P-core'da) | 5.5 – 7.8× |
| **boş sistem (referans)** | **4.6 – 6.1×** |

Ham sinyal çekişme altında: prefill p95 = 3 158–5 579, decode p5 =
29 723–41 488. Mutlak eşik 20 000 hâlâ ayırıyor.

Dedektör performansı (hi=3000, lo=2100, k=2, normalize):

| veri | doğruluk | gecikme p50 | geçiş |
|---|---|---|---|
| boş sistem | %99.60 | −144.1 ms | 1 (ideal) |
| çekişme | %99.62 | −160.2 ms | 1 (ideal) |
| prompt taraması | %99.54 | −135.1 ms | 1 (ideal) |

## A.3 İŞ 2b — Prompt uzunluğu taraması (20 koşu)

| prompt | token | prefill | gecikme p50 | gecikme/prefill |
|---|---|---|---|---|
| 32 | 33 | 0.88 s | −131.6 ms | −%14.9 |
| 128 | 127 | 2.88 s | −133.7 ms | −%4.6 |
| 256 | 255 | 5.66 s | −139.3 ms | −%2.5 |
| 496 | 493 | 10.91 s | −132.8 ms | −%1.2 |
| 1024 | 1022 | 22.69 s | −139.2 ms | −%0.6 |

**Gecikme aralığı −132…−139 ms (oran 0.94×), prefill süresi aralığı
0.88…22.69 s (oran 25.8×).**

Sınıf dengesizliği düzeltmesi:

| prompt | ham doğruluk | **prefill recall** | dengeli | "hep decode" tabanı |
|---|---|---|---|---|
| 32 | %99.33 | **%82.7** | %91.4 | %96.1 |
| 128 | %99.38 | %94.7 | %97.3 | %88.4 |
| 256 | %99.45 | %97.3 | %98.6 | %79.5 |
| 496 | %99.57 | %98.7 | %99.3 | %66.9 |
| 1024 | %99.66 | %99.3 | %99.7 | %49.5 |

## A.4 İŞ 3 — Normalizasyon ve salınım

Çekirdek tahsisi taraması (9 koşu, 4/6/8 fiziksel P-core):

| tahsis | aktif çekirdek | HAM decode | NORM decode | NORM prefill |
|---|---|---|---|---|
| c4 | 3.82 | 35 587 | 9 400 | 300 |
| c6 | 5.70 | 70 210 | 12 545 | 487 |
| c8 | 7.28 | 103 622 | 14 319 | 607 |

| | 4→8 çekirdek değişim oranı | çekirdek korelasyonu |
|---|---|---|
| HAM sinyal | **2.91×** | r = +0.999 |
| NORMALIZE sinyal | **1.52×** | r = +0.994 |

Dedektör, gerçek farklı tahsislerde:

| tahsis | normalize (3000/2100) | ham (20000/14000) |
|---|---|---|
| c4 | %99.47, −214.9 ms, 1 geçiş | %99.95, +14.7 ms, 1 geçiş |
| c6 | %99.53, −150.4 ms, 1 geçiş | %99.53, −148.7 ms, 1 geçiş |
| c8 | %99.60, −130.6 ms, 1 geçiş | %99.60, −130.6 ms, 1 geçiş |

Salınım testi (çekişme verisi, kayıtlı sinyalin politika kaynaklı yeniden
ölçeklenmesi):

| k | ham, histerezissiz | ham + histerezis | norm + histerezis |
|---|---|---|---|
| **k=2** | **10 geçiş (ideal)** | **10 (ideal)** | **10 (ideal)** |
| k=1 | 118 geçiş (max 37) | 16 (max 5) | 14 (max 3) |

8→6, 8→5, 8→4, 8→3 iadelerinin hepsinde k=2 ile salınım yok.

## A.5 İŞ 4 — Prefill'e E-core (18 koşu)

| kol | prefill tok/s | TTFT | decode tok/s | ITL p95 |
|---|---|---|---|---|
| A_P8 (8 fiziksel P) | 45.13 | 10 990 | 11.56 | 90.10 |
| B_P8_E4 (+4 E) | 47.77 | 10 384 | 10.19 | 101.47 |
| C_P8_E8 (+8 E) | **51.00** | **9 725** | 10.58 | 98.58 |

A_P8'e karşı, hepsi p<0.01:

| | B_P8_E4 | C_P8_E8 |
|---|---|---|
| prefill | +%5.8 | **+%13.0** |
| TTFT | −%5.5 | **−%11.5** |
| decode | −%11.8 | −%8.4 |
| ITL p95 | +%12.6 | +%9.4 |
| ITL p99 | +%12.2 | +%8.1 |

## A.6 İŞ 5 — llama.cpp thread havuzu runtime'da ayrılabiliyor mu (15 koşu)

**Kaynak incelemesi:**

| yetenek | durum |
|---|---|
| `llama_set_n_threads(ctx, n_threads, n_threads_batch)` | public API, runtime |
| İki ayrı threadpool (`threadpool` / `threadpool_batch`) | mimaride var |
| Faza göre havuz seçimi (`llama-context.cpp:2442`) | `batched ? threadpool_batch : threadpool` |
| `cpumask[]` + `strict_cpu` (`ggml.h:2912`) | threadpool parametresi |
| `-C/--cpu-mask`, `-Cb/--cpu-mask-batch` | parse ediliyor |
| **`ggml_threadpool_new` / `llama_attach_threadpool` çağrısı** | **yalnızca `tools/completion` ve `llama-bench`; server'da YOK** |
| Thread sayısı server'a bağlı mı (`common.cpp:1599`) | **evet** |

**Ampirik doğrulama:**

| kol | cpus | -t | -tb | prefill | TTFT | decode | ITL p95 |
|---|---|---|---|---|---|---|---|
| A | P8 | 8 | 8 | 45.14 | 10 989 | 11.62 | 86.72 |
| B | P8+E8 | 8 | 16 | **51.14** | 9 700 | 10.13 | **104.77** |
| C | P8+E8 | 16 | 16 | 51.13 | 9 701 | 10.55 | 98.80 |

A'ya karşı: B prefill **+%13.3** (p<0.01), ITL p95 **+%20.8**;
C prefill +%13.3 (p<0.01), ITL p95 +%13.9.

---

# B. YORUMLAR

## B.1 Başarı ölçütü donduruldu (İŞ 1)

`CLAUDE.md` → "Başarı Ölçütü" bölümü eklendi, Faz 2 kodu yazılmadan önce.
Eşit ağırlıklı toplam throughput **reddedildi** (gecikmeyi throughput'a
çeviriyor, kullanıcı bekleme süresini ve enerjiyi saymıyor). Yerine Pareto
formülasyonu kondu:

> LLM'in servis kalitesini sabit tutarken rakibe ne kadar throughput
> iade edebiliyorum?

Somut kabul kriteri: statik D'ye karşı **TTFT ≤ 11 762.6 ms** ve
**ITL p95 ≤ 91.05 ms** kısıtları altında, rakip throughput'u
**> 18 313 it/s** (D'nin 17 954'ünün %2 üstü).

Ölçüt ayrıca bir **ön kayıt** içeriyor: naif "decode'da çekirdek iade et"
politikasının başarısız olması bekleniyor.

## B.2 H5 zor koşullarda: çekişme sorun değil, kısa prompt sorun

**Çekişme dedektörü bozmuyor, iyileştiriyor** (ayrışma 4.6–6.1× → 5.5–9.1×).
Sebep yapısal: sinyal yalnızca LLM process'inin thread'lerinden toplanıyor,
rakibin ctx trafiği tanımı gereği paydaya girmiyor. Çekişme altında
prefill'in CPU-saniye başına ctx hızı da düşüyor, bu da ayrışmayı açıyor.

**Kısa prompt gerçek bir sınır.** 32 token'da prefill 0.88 s ve sabit
~135 ms'lik erken uyarı bunun %15'ini yiyor → prefill recall %82.7'ye
düşüyor. Pratik eşik: **prompt ≥ 128 token** için dedektör güvenilir
(prefill recall ≥ %94.7).

## B.3 Erken uyarı gerçek, artefakt değil

Negatif gecikme prefill süresi 25.8 kat değişirken **sabit** kalıyor
(−132…−139 ms, oran 0.94×). n_batch/kısmi blok hipotezi bunu öngörmezdi:
o hipotez gecikmenin prefill süresiyle ölçeklenmesini gerektirirdi.

Sabit ~135 ms, bir token üretim periyoduna (ITL ~95 ms) yakın. Muhtemel
mekanizma: prefill'in son forward pass'i ile ilk token'ın üretimi arasındaki
geçişte bariyer deseni zaten decode'unkine dönüyor. **Ölçüldü, mekanizması
kesinleştirilmedi.**

Pratik değeri: politika faz geçişini ~135 ms öncesinden haber alıyor.
Maliyeti prefill'in son %1'i (496 token) ila %15'i (32 token).

## B.4 Faz asimetrisi eyleme dönük hâliyle ölçüldü — ve statik çözümü yok

İŞ 4 projenin en doğrudan kanıtı: **aynı scheduling kararı (E-core ekle)
iki faza zıt etki yapıyor.**

- Prefill compute-bound (%77 verim, donanım tavanının %72'sinde) → yavaş
  çekirdek bile net katkı: **+%13**
- Decode bandwidth-bound (İŞ 2, Faz 1) → ek çekirdekten kazanç yok, ama her
  katmanda 3.7 GHz'lik thread'i beklemek gecikme ekliyor: **ITL p95 +%9.4**

Statik bir politika birini seçmek zorunda. Faz-farkındalıklı politika
değil — kâğıt üzerinde "prefill'de P+E, decode'da yalnız P" TTFT'yi %11.5
iyileştirir ve ITL'i bozmaz.

## B.5 Ama dondurulmuş ölçütü HİÇBİR mekanizma geçmiyor

| mekanizma | KISIT (LLM QoS) | AMAÇ (rakip throughput) |
|---|---|---|
| decode'da 8→6 iade | **İHLAL** (ITL +%7.7 = bütçenin 3.9 katı) | +%24 olurdu |
| prefill'e E-core | GEÇER (TTFT 10 204 ≤ 11 763; p95 89.26 ≤ 91.04) | **BAŞARISIZ** (−%33) |

İkisi de gerçek mekanizma; biri kısıtı ihlal ediyor, diğeri amacı ıskalıyor.

**Ölçüt değiştirilmedi.** Dondurmanın amacı buydu. Kaydedilen tespit:

> Ölçülen faz asimetrisi gerçek ve büyük, ama değeri **LLM gecikmesi
> ekseninde** ortaya çıkıyor; dondurulmuş ölçüt **rakip throughput'u
> ekseninde** ödül veriyor.

Bu bir ölçüt–hedef uyumsuzluğudur ve **kullanıcının kararıdır**:

- (a) Ölçüt doğruysa → ölçülen mekanizmalar yetmez, yenisi aranmalı.
- (b) Projenin asıl hedefi LLM servis kalitesiyse → ölçüt revize edilmeli,
  gerekçesi ve tarihi CLAUDE.md'ye yazılmalı, eski hâli silinmemeli.

Ajan bu kararı kendi başına vermez.

## B.6 Mekanizma uygulanabilir — ama server'da değil, ve sched_ext'siz

İŞ 5 iki şeyi ayrı ayrı kanıtladı:

**(a) `-tb` gerçekten çalışıyor.** B kolu prefill kazancının tamamını
alıyor (+%13.3, C ile birebir aynı). llama-server'ın faz-başına thread
sayısı ayrımı işlevsel — llama.cpp faz ayrımını mimarisinde zaten yapıyor
(`batched ? threadpool_batch : threadpool`).

**(b) Ama affinity olmadan yetmiyor.** B'nin ITL p95'i **+%20.8**, hatta
C'den (+%13.9) *daha kötü*: 8 decode thread'i P+E cpuset'inde serbest
yüzüyor ve bir kısmı E-core'a düşüyor. **İŞ 4'ün politikası thread
sayısıyla yaklaşık olarak bile kurulamıyor.**

Üç yol var:

| yol | maliyet | katkının adı |
|---|---|---|
| llama-server'a ~25 satır yama | en ucuz | "uygulama kendi yerleşimini yapıyor" |
| llama-cli kullanmak | sıfır kod | SSE token zaman damgaları kaybolur |
| **daemon + `sched_setaffinity`** | orta | **"OS iş yükünü anlıyor"** |

Üçüncüsü projenin tezine en uygun olanı, uygulamayı hiç değiştirmeden
herhangi bir process'te çalışır, ve gereken iki parça da hazır: faz
tespiti (H5 doğrulandı) ve `sched_setaffinity` (sıradan syscall).

**Ve sched_ext gerektirmez.** Ortaya çıkan çerçeveleme sorusu: faz-aware
yerleşim kullanıcı alanında yapılabiliyorsa, sched_ext'in katkısı ne
olacak? Savunulabilir aday: birbirinden habersiz birden fazla process'i
koordine etmek, ya da rakip iş yükünü LLM'in fazına göre yönetmek — ki
dondurulmuş ölçütün amacı zaten budur.

**Önerilen Faz 2 sıralaması:** önce daemon + `sched_setaffinity` ile
politikayı kur ve ölçüte karşı ölç; sched_ext'e ancak bu yetersiz kalırsa
geç. O zaman sched_ext'in neyi *ek olarak* sağladığı ölçülmüş olur. Bu,
CLAUDE.md'nin "ML en son girer, belki hiç girmez" ilkesiyle aynı mantık.

---

# C. ÇÜRÜTÜLEN HİPOTEZLER

Bu oturumda **beş** düzeltme; dördü benim iddialarım.

| # | hipotez | kimin | çürüten | ne oldu |
|---|---|---|---|---|
| 1 | "Faz-aware politika statik D'yi yenebilir; decode'a 8 yerine 6 çekirdek *yalnızca* %7.8'e mal olur" | **benim** (Faz 1 raporu §4.7, B.5) | İŞ 1 hesabı | %7.8'i prefill'in +%20.8'ine karşı kıyaslamıştım; **%2'lik QoS bütçesine karşı 3.9 kat.** Politika kısıtı ihlal ediyor. |
| 2 | "Normalizasyon çekirdek sayısı bağımlılığını giderir" | **benim** (İŞ 3a önerisi) | çekirdek taraması | Bağımlılık kalkmıyor, **yarıya iniyor** (2.91× → 1.52×; r=+0.994). İddia bu hâliyle yanlış. |
| 3 | "Mutlak eşik, politika çekirdek kısınca salınıma yol açar" | **ortak** (İŞ 3 gerekçesi) | salınım testi + c4/c6/c8 | **Salınım hiçbir konfigürasyonda oluşmadı** (8→3 iadesinde bile). Koruyan şey histerezis değil, zaten v1'de olan **k=2** kuralı. |
| 4 | "Negatif gecikme n_batch artefaktı olabilir" | senin alternatifin | prompt taraması | **Reddedildi.** Prefill 25.8 kat değişirken gecikme sabit (0.94×). Erken uyarı gerçek. |
| 5 | "H5 doğruluğu %99.6" | **benim** (Faz 1 raporu) | sınıf dengesizliği analizi | Ham örnek-başına doğruluk **şişkin**. 32 token'da "hep decode" diyen boş dedektör %96.1 alıyor; gerçek prefill recall **%82.7**. Metrik değiştirildi. |

**Not (#2 ve #3 birlikte):** İŞ 3'ün gerekçesi olan arıza modu ortaya
çıkmadı, önerdiğim çözüm de iddia ettiğim şekilde çalışmadı. Yine de v2
tutuldu: normalize sinyal artık **her tahsiste tek eşikle** çalışıyor
(c4/c6/c8'de %99.47–99.60) ve kalıntı sürüklenme (1.52×), faz ayrışmasının
(24–31×) çok altında. Yani v2 gereksizdi ama zararsız ve marj sağlıyor.

## Önceki oturumlardan devreden

| # | hipotez | çürüten |
|---|---|---|
| 1 | "1M migration çoğunlukla bedava kardeş-içi sekmedir" | E1 (%85'i çekirdek aşırı) |
| 2 | "Migration patlamasının sebebi SMT" | E2 (sibling'siz kolda da 668k) |
| 3 | "Prefill migration'a decode'dan duyarlı" | E2 (ceza çekirdek sayısından) |
| 4 | H3 naif hali: "migration sayısı gecikmeyi bozar" | E2 + S2 (1644 kat arttı, iyileşti) |

---

# D. HİPOTEZ TAHTASI

| hipotez | durum |
|---|---|
| **H5** — faz tespiti uygulamadan yardım almadan | **DOĞRULANDI, kapsamı belirtilerek:** llama.cpp sınıfı bariyer-senkronize runtime'lar; prompt ≥128 token; boş sistem **ve** çekişme altında; 4–8 çekirdek tahsisinde; prefill recall ≥%94.7, gecikme −135 ms sabit, daemon maliyeti %1.7 (100 ms periyot) |
| **K1** — decode bandwidth-bound | **DOĞRULANDI, nicel** (~%87 bandwidth / ~%13 senkronizasyon) |
| **K3** — gürültü tabanı | **CEVAPLANDI**: %2 |
| **H4** — hibrit CPU'lar Linux varsayımlarını zorlar | **GÜÇLÜ DESTEK**: aynı karar (E-core ekle) iki faza zıt etki (+%13 / −%9.4); P-pinning +%14.4 |
| **H1** — decode E-core'a düşünce gecikme artar | **kısmen**: E-only −%55.7, E-karışımı ITL p95 +%9.4; koşu-içi taşınmadan ayrıştırılmadı |
| **H3** — migration token gecikmesini etkiler | **NAİF HALİ REDDEDİLDİ** |
| **H2** — prefill/decode girişimi | **TEST EDİLMEDİ** |
| **K2** — scheduler duyarlılığı | **VAR**: statik yerleşim %9–60 arası etki |

---

# E. AÇIK KALANLAR

| konu | ne gerekiyor |
|---|---|
| **Ölçüt–hedef uyumsuzluğu (B.5)** | **kullanıcı kararı** — Faz 2'ye girmeden |
| ~~Thread havuzu runtime'da ayrılabiliyor mu~~ | **CEVAPLANDI (İŞ 5):** thread sayısı evet, affinity server'da hayır |
| **sched_ext'in katkısı ne olacak (B.6)** | daemon + `sched_setaffinity` yeterliyse sched_ext'in ek değeri gösterilmeli |
| Yama yolunun yeterliliği | `completion.cpp:184-202` bloğunun server'a taşınması yeterli mi — **varsayım, ölçülmedi** |
| Faz geçişinde thread taşıma maliyeti | daemon yaklaşımı geçişte affinity değiştirir; migration + cache kaybı maliyeti ölçülmedi (projenin "migration önemsiz" bulgusuyla test edilebilir gerilim) |
| H5 genelliği | ikinci runtime (spin-wait yapılandırması) |
| H5 çok kısa üretim | 5–10 token'lık decode test edilmedi |
| Erken uyarının mekanizması | ölçüldü, açıklanmadı |
| H2 | eşzamanlı prefill + decode |
| H1 temiz testi | koşu-içi E-core'a taşıma |
| scx_lavd / scx_rustland | **kullanıcı onayı** |
| S3–S6 | tarayıcı, çoklu örnek, indeksleme, termal |
| E-core kolunda enerji | kaydedilmedi |

---

# F. YENİ ARAÇLAR

| dosya | işi |
|---|---|
| `harness/h5_hard.py` | çekişme ve prompt uzunluğu modlarında H5 koşuları |
| `harness/h5_detector_v2.py` | normalize sinyal + histerezis + salınım testi |
| `harness/make_prompts.py` | tokenizer ile tam hedefe oturan prompt üretimi |
| `harness/i4_ecore_prefill.py` | prefill'e E-core ekleme deneyi |
| `harness/i5_tb_only.py` | thread sayısı ayrımı tek başına yetiyor mu |
| `harness/prompts/` | 33/127/255/493/1022 token'lık sabit promptlar |

`harness/run_once.py` artık `--threads-batch` kabul ediyor (prefill thread
sayısı, decode'dan bağımsız).

---

# Tek paragraflık özet

Üç işin üçü de bitti, üstüne dördüncüsü eklendi. **Başarı ölçütü Faz 2 kodu
yazılmadan donduruldu** ve eşit ağırlıklı toplam throughput reddedilip
Pareto formülasyonu kondu; ölçüt naif politikanın başarısız olacağı ön
kaydını da içeriyor. **H5 zor koşullarda test edildi:** çekişme dedektörü
bozmuyor, iyileştiriyor (rakibin ctx trafiği paydaya girmiyor); kısa prompt
ise gerçek sınır — 32 token'da prefill recall %82.7'ye düşüyor, pratik eşik
≥128 token. **Negatif gecikme artefakt değil:** prefill süresi 25.8 kat
değişirken sabit −135 ms kalıyor. **İŞ 3'ün gerekçesi olan salınım hiç
oluşmadı** ve normalizasyon iddiam da yanlış çıktı (bağımlılık kalkmıyor,
yarıya iniyor) — ikisi de çürütülenler bölümüne yazıldı. **İŞ 4 projenin en
doğrudan kanıtını verdi:** E-core eklemek prefill'i %13 hızlandırıp decode'un
ITL p95'ini %9.4 bozuyor, yani aynı karar iki faza zıt etki yapıyor ve statik
çözümü yok. Buna rağmen **dondurulmuş ölçütü hiçbir mekanizma geçmiyor**:
decode'da çekirdek iadesi kısıtı 3.9 kat ihlal ediyor, prefill'e E-core ise
kısıtları geçip amacı %33 ıskalıyor. Ortaya çıkan şey bir ölçüt–hedef
uyumsuzluğudur: asimetrinin değeri LLM gecikmesi ekseninde, ölçütün ödülü
rakip throughput'u ekseninde. Ölçüt değiştirilmedi; bu karar kullanıcınındır
ve Faz 2'ye girmeden önce verilmelidir. **İŞ 5 ise Faz 2'nin teknik ön
koşulunu cevapladı:** llama.cpp faz ayrımını mimarisinde zaten yapıyor ve
thread sayısı server'da runtime'da ayrılabiliyor (`-tb` prefill'e +%13.3
kazandırıyor), ama CPU affinity ayrımı server'a bağlanmamış — dolayısıyla
İŞ 4'ün politikası thread sayısıyla kurulamıyor (decode ITL p95 +%20.8).
Politikayı uygulamanın en tez-uyumlu yolu, uygulamayı hiç değiştirmeyen
**userspace daemon + `sched_setaffinity`**; ki bu da sched_ext
gerektirmiyor. Bu, Faz 2'ye girmeden yanıtlanması gereken ikinci soruyu
doğuruyor: sched_ext'in bu yaklaşımın üstüne katacağı ölçülebilir değer
nedir?
