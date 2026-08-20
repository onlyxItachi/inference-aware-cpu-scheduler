# Faz 2 Eşiği — Oturum Raporu

**Tarih:** 2026-07-19
**Yeni ölçüm:** 48 koşu (18 faz-anahtarlama rakipsiz + 12 ubatch + 18 faz-anahtarlama çekişmeli)
**sched_ext yazılmadı, `scxctl` çalıştırılmadı. Faz 2'nin tam politikası
da yazılmadı — yalnızca merkezi iddia ölçüldü.**

---

# A. ÖLÇÜLEN SAYILAR

## A.1 İŞ 2 — Faz anahtarlama (18 koşu, 6 tur interleaved)

Rakip yük **yok**. Örnekleyici üç kolda da çalışıyor.

| kol | cpus | -t | -tb | dedektör |
|---|---|---|---|---|
| A_P8 | P8 | 8 | 8 | çalışıyor, kullanılmıyor |
| C_P8_E8 | P8+E8 | 16 | 16 | çalışıyor, kullanılmıyor |
| SWITCH | P8+E8 | 8 | 16 | faz geçişinde maskeyi P8'e daraltıyor |

| kol | TTFT | ITL p50 | ITL p95 | ITL p99 | decode | J/token | migration |
|---|---|---|---|---|---|---|---|
| A_P8 | 10 998 | 86.10 | 89.94 | 92.40 | 11.55 | 10.986 | 3 858 |
| C_P8_E8 | 9 753 | 95.92 | 99.84 | 101.39 | 10.41 | 11.248 | 62 120 |
| **SWITCH** | **9 748** | **86.09** | **86.71** | **87.28** | **11.60** | **10.486** | 7 275 |

| SWITCH farkı | vs A_P8 | vs C_P8_E8 |
|---|---|---|
| TTFT | **−%11.4** (p<0.01) | −%0.1 (ns) |
| ITL p95 | **−%3.6** (p<0.01) | **−%13.1** (p<0.01) |
| ITL p50 | −%0.0 (ns) | **−%10.2** (p<0.01) |
| J/token | **−%4.6** (p<0.01) | **−%6.8** (p<0.01) |

### Geçiş maliyeti

| kol | migration (200 ms pencere) | ctx burst | anahtarlama süresi |
|---|---|---|---|
| A_P8 (kontrol) | 22 | 14 594 | — |
| C_P8_E8 (kontrol) | 413 | 33 370 | — |
| **SWITCH** | **2 338** | 17 124 | **202 µs** |

Geçişten sonraki ilk 10 token ITL (ms):

| kol | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | kuyruk |
|---|---|---|---|---|---|---|---|---|---|---|---|
| A_P8 | 94.9 | 92.6 | 91.5 | 91.4 | 91.0 | 90.2 | 90.3 | 90.0 | 90.1 | 89.9 | 86.23 |
| C_P8_E8 | 95.9 | 95.0 | 97.0 | 97.8 | 95.5 | 93.6 | 95.0 | 94.7 | 97.4 | 97.4 | 96.09 |
| SWITCH | 86.7 | 86.0 | 86.4 | 86.1 | 86.0 | 85.9 | 85.9 | 85.8 | 85.9 | 85.8 | 86.18 |

Paket sıcaklıkları: A_P8 56→78°C, C_P8_E8 56→73°C, SWITCH 56→77.5°C.

## A.2 İŞ 3 — Erken uyarının mekanizması: ubatch taraması (12 koşu)

Prompt sabit 496 token; yalnızca `n_ubatch` değişiyor.

| ubatch | prefill parçası | n | prefill | gecikme p50 | gecikme aralığı | ayrışma |
|---|---|---|---|---|---|---|
| 128 | 4 | 4 | 10.94 s | −134.6 ms | −143…−124 ms | 5.1× |
| 256 | 2 | 4 | 10.99 s | −132.0 ms | −137…−121 ms | 5.4× |
| 512 | 1 | 4 | 11.06 s | −142.7 ms | −144…−127 ms | 9.9× |

ubatch 4 kat değişiyor (parça sayısı 4→1); **gecikme oranı 1.06×**,
aralıklar tamamen örtüşüyor.

## A.3 İŞ 6 — Aynı üç kol, S2 çekişmesi altında (18 koşu)

Yük her kolda aynı yerde: 16 thread, E-core'lara (16-23) pinli — statik D
ile birebir aynı yerleşim.

| kol | TTFT | ITL p50 | ITL p95 | ITL p99 | decode | J/token | yük it/s |
|---|---|---|---|---|---|---|---|
| A_P8 | 11 570 | 88.22 | 89.94 | 92.22 | 11.30 | 11.363 | 18 048 |
| C_P8_E8 | 11 745 | 98.16 | 99.28 | 99.87 | 10.17 | 12.245 | 18 129 |
| SWITCH | 11 741 | 88.24 | 89.71 | 90.74 | 11.31 | 11.409 | 18 033 |

SWITCH'in A_P8'e karşı farkları: TTFT +%1.5, ITL p95 −%0.3 (ns), ITL p50
+%0.0 (ns), decode +%0.1 (ns), J/token +%0.4 (ns), yük −%0.1 (ns).
**Hepsi %2 gürültü tabanının içinde.**

Rakipsiz ölçümle karşılaştırma:

| kol | TTFT rakipsiz | TTFT çekişme | fark |
|---|---|---|---|
| A_P8 | 10 998 | 11 570 | **+%5.2** |
| C_P8_E8 | 9 753 | 11 745 | **+%20.4** |
| SWITCH | 9 748 | 11 741 | **+%20.4** |

---

# B. YORUMLAR

## B.1 Merkezi iddia tuttu — ve projeksiyondan güçlü çıktı

Yeni ölçütün iki kısıtı da geçildi:

| kısıt | ölçülen | tavan | sonuç |
|---|---|---|---|
| TTFT ≤ C_P8_E8 × 1.02 | 9 748 ms | 9 920 ms | **GEÇER** |
| ITL p95 ≤ A_P8 × 1.02 | 86.71 ms | 91.90 ms | **GEÇER** |
| rakip ≥ 17 595 it/s | — | — | **test edilmedi** |

SWITCH her iki statik konfigürasyonu da **Pareto olarak baskılıyor**:
C'nin TTFT'sini alıyor (fark ns), A'nın ITL'ini alıyor — üstelik p95'te
A'yı %3.6 **yeniyor**. Projeksiyon "eşitler" diyordu; ölçüm "yener" dedi.

Enerji de bir takas değil: SWITCH üç kolun en verimlisi
(**10.486 J/token**, A'ya −%4.6, C'ye −%6.8).

**Ama sınav eksiktir.** Rakip yük yokken ölçüldü; ölçütün üçüncü kısıtı
test edilmedi. Bu ölçüm **mekanizmanın çalıştığını** gösterir, **politikanın
işe yaradığını** değil. S2 kolları sıradaki adım ve asıl sınav orasıdır.

## B.2 Geçiş maliyeti: 100 kat migration, ölçülebilir sıfır gecikme

Faz sınırında 16 thread'in maskesi aynı anda değişiyor ve ~2 300 ekstra
migration üretiyor — kontrol kolunun **100 katından fazla**, üstelik
koşunun en gecikmeye duyarlı anında.

**Gecikmeye hiç yansımıyor.** SWITCH'in ilk token'ı 86.7 ms, kuyruk
ortalaması 86.18 ms — fark %0.6, gürültü tabanının altında.

Bu, "migration sayısı yanlış metriktir" bulgusunun **dördüncü ve en
düşmanca** doğrulaması. Öncekilerde migration'ı scheduler üretiyordu ve biz
gözlüyorduk; burada migration'ı **biz** ürettik, kasıtlı olarak, en kötü
anda seçerek. Yine hiçbir şey olmadı.

`sched_setaffinity` çağrısı 16 thread için **202 µs**. CLAUDE.md'nin
mimari ayrımına göre bu net biçimde **yavaş yol** işlemidir ve faz başına
bir kez yapılır: 33 saniyelik koşuda sürenin milyonda 6'sı.

## B.3 Açıklanamayan: A'nın ısınma transient'i SWITCH'te yok

A_P8'in ilk token'ı 94.9 ms ve kuyruk ortalamasına (86.23) ancak ~20
token'da iniyor — **%10'luk bir ısınma transient'i**. SWITCH'te bu yok
(86.7 → 85.8, düz). SWITCH'in ITL p95'te A'yı %3.6 yenmesinin sebebi
büyük olasılıkla budur.

Termal açıklama **desteklenmiyor**: A 56→78°C, SWITCH 56→77.5°C.

Aday açıklama: SWITCH'te anahtarlama ilk token'dan ~116 ms **önce**
yapılıyor, yani decode thread'leri ilk token üretilmeden hedef
çekirdeklerine yerleşip oturmuş oluyor; A'da böyle bir erken yerleşim yok.
**Bu hipotez ölçülmedi.** Doğruysa, dedektörün negatif gecikmesi bir yan
etki değil, politikanın **aktif bir avantajı** demektir — ama iddia
kurulmadan önce ölçülmeli.

## B.4 Erken uyarının mekanizması hâlâ bilinmiyor

ubatch 4 kat değiştirildi (prefill 4 parçadan 1 parçaya indi) ve gecikme
1.06× oynadı — yani **sabit**. Bariyer sıklığı hipotezi de eleniyor.

Şimdiye kadar elenenler: prompt uzunluğu (25.8 kat değişimde sabit),
istemci iletim gecikmesi (yalnızca 26.7 ms), ubatch/bariyer sıklığı
(4 kat değişimde sabit).

**Mekanizma açık kalıyor ve uydurulmayacaktır.**

Bir nüans: ubatch **ayrışmayı** değiştiriyor (5.1× → 9.9×). Yani bariyer
sıklığı prefill'in sinyal *seviyesini* açıklıyor — az parça, az bariyer,
düşük prefill ctx hızı — ama sıçramanın *ne zaman başladığını*
açıklamıyor. İki ayrı olgu; ikincisi hâlâ cevapsız.

## B.4b İŞ 6 — mekanizma çekişme altında çalışmıyor (NEGATİF SONUÇ)

Rakipsiz ölçümdeki Pareto baskınlığı **çekişme altında tamamen kayboluyor**.
SWITCH ile A_P8 arasındaki her fark gürültü tabanının içinde.

Sebep ölçülmüş durumda: E-core kullanan iki kol (C ve SWITCH) çekişmeden
**4 kat** fazla zarar görüyor (+%20.4 vs A_P8'in +%5.2). Rakip 16 thread ile
8 E-core'u doyurduğu için prefill'e E-core eklemek boş kapasite bulmuyor,
sıraya giriyor.

**Yani rakipsiz koşuldaki +%13'lük prefill kazancı bir "atıl kaynak"
kazancıydı.** Rakip varken atıl kaynak yok, kazanç da yok.

Rakip hiçbir kolda zarar görmedi (üç kolda da ~18 000 it/s) — bu da
beklentimin tersiydi; SWITCH'in E-core'ları alıp rakibe fatura çıkaracağını
tahmin etmiştim, çıkarmadı.

### Ölçütün iç tutarsızlığı

Dondurulmuş ölçüt bu senaryoda **hiçbir kol tarafından geçilemez**, ve sebep
politikalar değil ölçütün kendisi: TTFT ve ITL p95 referansları **rakipsiz**
ölçümlerden (İŞ 4), rakip referansı **çekişmeli** ölçümden (S2 v2) alınmış.
Senaryo çekişmeli olduğuna göre rakipsiz bir TTFT'yi yakalamak tanım gereği
imkânsız — mevcut baseline A_P8 bile kalıyor (11 570 > 9 920).

Bu bir tasarım hatasıdır ve bana aittir. **Ölçüt bu raporda
düzeltilmiyor**; revizyon ancak gerekçesi ve tarihiyle, sonucu bilerek
yapılır ve karar kullanıcınındır. İki okuma da raporlanıyor: lafzen SWITCH
2/3 geçiyor (TTFT'de kalıyor, ama tüm kollar kalıyor); eşit koşulda SWITCH
A_P8 ile berabere.

### sched_ext'in iddiası keskinleşti

Problem net: LLM'in prefill'i E-core kapasitesine ihtiyaç duyuyor ama o
kapasiteyi rakip tutuyor. `sched_setaffinity` **öncelik veremez** —
"orada koşabilirsin" der, "önce sen koş" diyemez.

sched_ext'in ifade edebileceği ve affinity'nin edemeyeceği şey budur:
*prefill fazındaki LLM thread'leri E-core'larda rakibi preempt etsin,
decode'a geçince E-core'ları tamamen bıraksın.*

**Ölçülmüş boşluk:** rakipsiz 9 748 ms ile çekişmeli 11 741 ms arasındaki
**1 993 ms**. Faz 3'ün hedefi bunun ne kadarını geri alabildiğidir.

## B.5 Ölçüt revizyonu (İŞ 1)

`CLAUDE.md`'de REVİZYON 1 yürürlükte, REVİZYON 0 tarihsel kayıt olarak
duruyor. Gerekçe: ölçüt donduğunda İŞ 4'ün mekanizması yoktu; ölçüt S2 v2
manzarasına göre yazılmıştı ve oradaki tek alet bir **öncelik takasıydı**,
ölçüt de takasın diğer ucunu ödüllendirdi. İŞ 4 **takas olmayan** bir
mekanizma buldu ve eski ölçüt bu tür kazancı yapısal olarak ölçemiyordu.
Deney uzayı değişti, ölçüt eskidi.

Yeni ölçüt eskisinden **zor**: statik hiçbir konfigürasyonun kazanamayacağı
bir Pareto baskınlığı sınavı. Bu oturum onu geçti (iki kısıtta; üçüncüsü
açık).

Ayrıca sched_ext'in ölçülecek katkısı adlandırıldı: `sched_setaffinity`
**sert bölümlemedir, öncelik değil**; boş çekirdek boşa gider. sched_ext'in
iddiası **aynı QoS'u daha az çekirdek israfıyla** sağlamak olacaktır ve
Faz 2 daemon+affinity sonuçlarına karşı ölçülecektir.

---

# C. ÇÜRÜTÜLEN HİPOTEZLER

| # | hipotez | kimin | çürüten | ne oldu |
|---|---|---|---|---|
| 1 | "Erken uyarının mekanizması bariyer sıklığıdır (n_ubatch)" | ortak (İŞ 3 gerekçesi) | ubatch taraması | ubatch 4 kat değişti, gecikme 1.06× oynadı. **Elendi.** Mekanizma hâlâ açık. |
| 2 | "Toplu affinity değişimi geçiş maliyeti yaratır" | ortak (İŞ 2 sorusu) | ilk-10-token ITL | 2 338 migration üretildi, gecikmeye %0.6 yansıdı (gürültü altı). **Maliyet ölçülemedi.** |
| 3 | "SWITCH statikleri *eşitler*" | benim projeksiyonum | rakipsiz ölçüm | Eşitlemedi, **yendi** (ITL p95'te A'ya karşı −%3.6, p<0.01). Projeksiyon muhafazakârmış. |
| 4 | "Faz anahtarlamanın kazancı çekişme altında da geçerlidir" | **örtük varsayımım** | İŞ 6 | **ÇÜRÜDÜ.** Kazanç E-core'ların atıl olmasına bağlıymış; rakip onları doyurunca SWITCH ile A_P8 berabere (tüm farklar gürültü içinde). |
| 5 | "SWITCH prefill'de E-core'ları alıp rakibe fatura çıkarır (~15 000 it/s)" | **benim tahminim** | İŞ 6 | **ÇÜRÜDÜ.** Rakip üç kolda da ~18 000 it/s; fatura çıkmadı. |

**Merkezi iddia rakipsiz koşulda tuttu, çekişme altında çürüdü.** Önceki
oturumun uyarısı ("faz anahtarlama iki statiği de yener iddiası
çürüyebilir") kısmen gerçekleşti: mekanizma çalışıyor ama yalnızca atıl
kaynak varken. Ölçütün tanımladığı senaryoda kazanç sıfır.

## Önceki oturumlardan devreden

| # | hipotez | çürüten |
|---|---|---|
| 1 | "1M migration çoğunlukla bedava kardeş-içi sekmedir" | E1 |
| 2 | "Migration patlamasının sebebi SMT" | E2 |
| 3 | "Prefill migration'a decode'dan duyarlı" | E2 |
| 4 | H3 naif hali: "migration sayısı gecikmeyi bozar" | E2 + S2 + **İŞ 2 (bu oturum)** |
| 5 | "Faz-aware politika statik D'yi yenebilir" (eski ölçütle) | İŞ 1 hesabı |
| 6 | "Normalizasyon çekirdek bağımlılığını giderir" | çekirdek taraması |
| 7 | "Mutlak eşik salınıma yol açar" | salınım testi |
| 8 | "Negatif gecikme n_batch artefaktı" | prompt taraması |
| 9 | "H5 doğruluğu %99.6" | sınıf dengesizliği analizi |

---

# D. HİPOTEZ TAHTASI

| hipotez | durum |
|---|---|
| **Merkezi iddia** — faz anahtarlama statikleri Pareto baskılar | **KOŞULLU**: rakipsiz DOĞRULANDI (TTFT −%11.4 / ITL p95 −%3.6 / J/token −%4.6, p<0.01); **çekişme altında ÇÜRÜDÜ** (tüm farklar gürültü içinde). Kazanç atıl E-core kapasitesine bağlı. |
| **H5** — faz tespiti uygulamadan yardım almadan | DOĞRULANDI (llama.cpp sınıfı runtime, prompt ≥128 token) — ve artık **canlı bir politikayı sürdüğü** gösterildi |
| **H3** — migration token gecikmesini etkiler | **NAİF HALİ REDDEDİLDİ** (4. kez; bu kez migration'ı biz ürettik) |
| **K1** — decode bandwidth-bound | DOĞRULANDI, nicel (~%87 / ~%13) |
| **K3** — gürültü tabanı | %2 |
| **H4** — hibrit CPU'lar Linux varsayımlarını zorlar | **GÜÇLÜ DESTEK**: aynı karar iki faza zıt etki; anahtarlama ikisini birden alıyor |
| **H1** — decode E-core'a düşünce gecikme artar | kısmen |
| **H2** — prefill/decode girişimi | TEST EDİLMEDİ |
| **K2** — scheduler duyarlılığı | VAR (%9–60) |

---

# E. AÇIK KALANLAR

| konu | ne gerekiyor | öncelik |
|---|---|---|
| ~~Rakip yük altında sınav~~ | **YAPILDI (İŞ 6): mekanizma çekişme altında kazanç vermiyor** | — |
| **Ölçütün iç tutarsızlığı** | QoS referansları rakipsiz, rakip referansı çekişmeli; hiçbir kol geçemiyor. **Kullanıcı kararı** | **en yüksek** |
| **sched_ext preemption hipotezi** | prefill'de E-core'da rakibi preempt et; ölçülmüş boşluk 1 993 ms | **en yüksek** |
| LLM'in E-core'ları pratikte ne kadar kullandığı | yerleşim örneklemesi; İŞ 6 §3'teki CFS açıklaması hipotez | yüksek |
| **decode→prefill geri dönüşü** | çok turlu konuşma; yalnızca tek yön test edildi | yüksek |
| sched_ext'in ek değeri | daemon+affinity sonucuna karşı iş-koruyuculuk iddiası | yüksek |
| Erken uyarının mekanizması | prompt, istemci gecikmesi, ubatch elendi | orta |
| B.3'teki transient farkı | erken yerleşim hipotezi ölçülmedi | orta |
| H2 | eşzamanlı prefill + decode | orta |
| Kısa prompt zayıflığı | dedektör mirası (prefill recall %82.7 @32 token) | orta |
| scx_lavd / scx_rustland | **kullanıcı onayı** | — |
| S3–S6 | tarayıcı, çoklu örnek, indeksleme, termal | düşük |

---

# F. YENİ ARAÇLAR

| dosya | işi |
|---|---|
| `harness/phase_switch.py` | canlı dedektör + `sched_setaffinity` ile faz anahtarlama |
| `harness/run_phase_switch.py` | üç kolun interleaved sweep'i |
| `harness/i6_ubatch_lead.py` | ubatch taraması (erken uyarı mekanizması) |

`h5_capture.py` artık `--ubatch` kabul ediyor.

---

# Tek paragraflık özet

Ölçüt revize edildi (gerekçe: "deney uzayı değişti, ölçüt eskidi"; eski hâli
silinmedi) ve yeni ölçüt eskisinden zor: statik hiçbir konfigürasyonun
geçemeyeceği bir Pareto baskınlığı sınavı. **Merkezi iddia rakipsiz koşulda
ölçüldü ve tuttu:** canlı dedektör faz geçişinde `sched_setaffinity` ile
maskeyi daraltıyor, ortaya çıkan politika C'nin TTFT'sini alıyor (9 748 vs
9 753, ns), A'nın ITL p95'ini **yeniyor** (−%3.6, p<0.01) ve en az enerjiyi
harcıyor (−%4.6). Geçiş maliyeti ölçülemedi: en kötü anda kasıtlı 2 338
migration üretildi, gecikmeye %0.6 yansıdı. **Ama çekişme altında kazanç
sıfır:** aynı üç kol 16 rakip thread ile koşulduğunda SWITCH ile A_P8
arasındaki her fark gürültü tabanının içinde kaldı, çünkü rakipsiz kazanç
E-core'ların **atıl olmasına** bağlıymış — rakip onları doyurunca prefill'e
E-core eklemek boş kapasite bulmuyor (E kullanan kollar çekişmeden %20.4,
A_P8 yalnızca %5.2 zarar gördü). Bu oturumda kendi iki tahminim daha çürüdü
(kazancın çekişmede süreceği; SWITCH'in rakibe fatura çıkaracağı). Ayrıca
dondurduğum ölçütün **iç tutarsızlığı** ortaya çıktı: QoS referansları
rakipsiz, rakip referansı çekişmeli ölçümden alınmış, dolayısıyla senaryoda
hiçbir kol — mevcut baseline dahil — geçemiyor; hata bana ait, ölçüt
düzeltilmedi, karar kullanıcının. **Bunun karşılığında sched_ext'in iddiası
keskinleşti ve ölçülmüş bir boşluğa dayandı:** affinity öncelik veremez,
yalnızca bölümler; prefill'in ihtiyaç duyduğu E-core kapasitesini rakip
tutuyor. Rakipsiz 9 748 ms ile çekişmeli 11 741 ms arasındaki **1 993 ms**,
Faz 3'te preemption ile ne kadarının geri alınabileceğinin hedefidir.
