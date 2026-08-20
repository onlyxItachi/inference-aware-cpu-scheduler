# Faz 2 Devamı — Oturum Raporu

**Tarih:** 2026-07-19
**Yeni ölçüm:** 48 koşu (18 build rakibi + 18 yumuşak öncelik + 12 frekans)
**sched_ext yazılmadı, BPF yazılmadı, `scxctl` çalıştırılmadı.**

**Oturumun sorusu — net cevap bölüm D'de.**

---

# A. ÖLÇÜLEN SAYILAR

## A.1 İŞ 2 — Gerçekçi rakip (`make -j16`, pinsiz), 18 koşu

| kol | TTFT | ITL p50 | ITL p95 | ITL p99 | decode | J/token | build süresi |
|---|---|---|---|---|---|---|---|
| A_P8 | 11 743 | 85.77 | 90.42 | 92.46 | 11.58 | 11.633 | 35.70 s |
| C_P8_E8 | 10 490 | 96.85 | 100.68 | 102.67 | 10.31 | 12.027 | 37.24 s |
| **SWITCH** | **10 480** | **85.72** | **86.54** | **87.44** | **11.65** | **11.157** | **34.37 s** |

SWITCH vs A_P8: TTFT **−%10.8** (p<0.01), ITL p95 −%4.3 (ns, n=6),
ITL p50 −%0.1 (ns), decode +%0.6 (ns), J/token **−%4.1** (p<0.01),
**rakibin build süresi −%3.7** (p<0.01).

Rakipsiz ölçüme göre bozulma: A_P8 +%6.8, C_P8_E8 +%7.5, SWITCH +%7.5 (TTFT).

## A.2 İŞ 3 — Yumuşak öncelik (SWITCH + E-pinli loadgen), 18 koşu

| kol | TTFT | ITL p50 | ITL p95 | decode | rakip it/s | J/token |
|---|---|---|---|---|---|---|
| P1_normal | 11 779 | 88.13 | 89.75 | 11.32 | 17 893 | 11.415 |
| P2_nice19 | 11 756 | 88.02 | 89.65 | 11.34 | 17 850 | 11.396 |
| P3_weight1 | 11 765 | 88.07 | 89.67 | 11.34 | 17 864 | 11.403 |

Ölçülecek boşluk: P1 (11 779) − SWITCH rakipsiz (9 748) = **2 031 ms**.

| kol | geri alınan boşluk | rakibin kaybı |
|---|---|---|
| nice +19 | **%1.1** (ns) | −%0.2 |
| CPUWeight=1 | **%0.7** (ns) | −%0.2 |

## A.3 İŞ 4 — Frekans eğrisi (12 koşu, rakipsiz)

Decode başlangıcından itibaren P-core frekansı (MHz, medyan):

| t (ms) | A_P8 | SWITCH | fark |
|---|---|---|---|
| −100 | 4100 | 4100 | 0 |
| 0 | 4400 | 4303 | **−97** |
| 200 | 4373 | 4300 | −73 |
| 400 | 4314 | 4300 | −14 |
| 600 | 4400 | 4300 | −100 |
| 800 | 4300 | 4300 | 0 |
| ≥900 | 4300 | 4300 | 0 |

Karşılaştırma için ITL transient'i: A_P8 94.9 → 89.9 (ilk 10 token),
kuyruğa ~20 token ≈ **1 800 ms**'de oturuyor. SWITCH'te transient yok.

## A.4 E-core doluluk oranı (mekanizmanın doğrudan ölçümü)

| senaryo / faz | A_P8 | SWITCH |
|---|---|---|
| build rakibi — **prefill** | 5.6% | **90.5%** |
| rakipsiz — **prefill** | 0.0% | **93.8%** |
| build rakibi — **decode** | 0.0% | **0.0%** |
| rakipsiz — **decode** | 0.0% | **0.0%** |

---

# B. YORUMLAR

## B.1 İŞ 6'nın negatif sonucu daraltıldı — mekanizma gerçekçi rakiple çalışıyor

Geçen oturumda "faz anahtarlamanın kazancı çekişme altında kayboluyor"
sonucuna varılmıştı. **Bu genelleme kurulamazmış**, ve sebebi ölçüldü:

| | doyuran loadgen (İŞ 6) | gerçekçi build (bu iş) |
|---|---|---|
| rakip yerleşimi | E-core'lara pinli | pinsiz |
| **prefill'de E-core doluluğu (A_P8 koşarken)** | ~doygun | **%5.6** |
| SWITCH bozulması (TTFT) | +%20.4 | +%7.5 |
| SWITCH vs A_P8 | berabere | **TTFT −%10.8** |

Doyuran loadgen E-core'larda hiç boşluk bırakmıyordu; prefill'e E-core
eklemek sıraya girmek demekti. Build ise E-core'ları neredeyse boş
bırakıyor (pinsiz olduğu için P-core'larda kalıyor) — ve faz anahtarlama o
boşluğu kullanıyor.

**A.4 bunu çıkarım değil ölçüm hâline getiriyor:** SWITCH prefill'de
E-core'ları %90.5 dolduruyor, decode'da **%0.0'a** bırakıyor. Politikanın
yaptığını iddia ettiği şey birebir bu.

Doğru ifade artık şu: *"E-core'larda hiç boşluk bırakmayan bir rakip varsa
faz anahtarlamanın alacağı bir şey yoktur"* — ki bu neredeyse tanım gereği
doğrudur. "Çekişme altında kazanç yok" ifadesi **geri çekilmelidir.**

## B.2 Bu bir takas değil: iki taraf da kazanıyor

En dikkat çekici satır rakibin kendi işi: **SWITCH altında build %3.7 daha
hızlı bitiyor** (34.37 s vs 35.70 s, p<0.01).

Mekanizma tutarlı ve A.4 ile uyumlu: SWITCH prefill'i %10.8 daha erken
bitiriyor, sonra E-core'ları tamamen bırakıp yalnızca 8 P-core tutuyor.
Rakip hem daha erken hem daha geniş kaynağa kavuşuyor.

C_P8_E8 tersini gösteriyor: E-core'ları hiç bırakmadığı için rakibin
build'i **en yavaş** (37.24 s) ve LLM'in ITL'i **en kötü** (100.68).

### REVİZYON 2 ölçütü, senaryo = gerçekçi build rakibi

| kriter | aynı S'teki en iyi statik | SWITCH | sonuç |
|---|---|---|---|
| TTFT | C_P8_E8 10 490 → tavan 10 700 | 10 480 | **GEÇER** |
| ITL p95 | A_P8 90.42 → tavan 92.23 | 86.54 | **GEÇER** |
| rakip | A_P8 build 35.70 s → tavan 36.41 s | 34.37 s | **GEÇER** |

**Üçü de geçiliyor** — Pareto baskınlığının gerçekçi bir çekişme
senaryosunda sağlandığı ilk ölçüm.

## B.3 sched_ext'in üst sınırı: boşluk öncelikle geri ALINMIYOR

İŞ 6'da şu iddia kurulmuştu: 2 031 ms'lik boşluk, rakibi preempt edebilen
bir scheduler ile kısmen geri alınabilir; affinity bunu yapısal olarak
yapamaz.

**İŞ 3 bu iddiayı desteklemiyor.** İki standart öncelik mekanizması da
boşluğun **%1'inden azını** geri aldı (nice +19: %1.1; CPUWeight=1: %0.7,
ikisi de ns).

Kritik ikinci sayı: **rakip neredeyse hiçbir şey kaybetmedi** (−%0.2).
Öncelik düşürüldüğünde rakip zaman kaybetmiyorsa, **ondan zaman
istenmemiş** demektir — yani ortada arbitraj edilecek bir çekişme yok.

Sebebi A.4'te görünüyor: bu senaryoda decode P-core'larda, rakip
E-core'larda, yani **ayrık CPU kümelerinde**. Öncelik, aynı CPU için
yarışmayan iki iş arasında bir şey yapamaz. Boşluk bir öncelik problemi
değil; prefill'in isteyip de bulamadığı E-core kapasitesi problemi — ve o
kapasite gerçekten yok, çünkü loadgen onu tamamen tüketiyor.

**Bu, benim İŞ 6'da kurduğum sched_ext gerekçesini çürütüyor.**

## B.4 Transient'in sebebi frekans DEĞİL

A_P8'in ~%10'luk ısınma transient'i için iki aday vardı: frekans rampası ve
erken yerleşim.

**Frekans elendi, üstelik ters yönde:** A_P8 ilk 700 ms'de SWITCH'ten
**daha yüksek** frekansta (4400 vs 4300 MHz) ama ITL'i **daha kötü**
(94.9 vs 86.7). Ayrıca frekans ~800 ms'de oturuyor, ITL transient'i ~1 800
ms sürüyor — iki eğri ayrışıyor.

**Erken yerleşim hipotezi ayakta kalıyor** (doğrulanmadı, çürütülmedi).
Doğrulaması için önerilen deney: anahtarlama anını ilk token'dan 0 / 50 /
135 / 300 ms önce yapıp transient'in geri gelip gelmediğine bakmak.
Doğrulanırsa dedektörün negatif gecikmesi bir yan etki değil, politikanın
**aktif ve genelleştirilebilir** avantajıdır.

---

# C. ÇÜRÜTÜLEN HİPOTEZLER

| # | hipotez | kimin | çürüten | ne oldu |
|---|---|---|---|---|
| 1 | "Faz anahtarlamanın kazancı çekişme altında kaybolur" | **benim** (İŞ 6 genellemesi) | İŞ 2 | Gerçekçi rakiple kazancın neredeyse tamamı korunuyor (−%11.4 → −%10.8). Genelleme sentetik doyuran yükle sınırlıymış. |
| 2 | "2 031 ms'lik boşluk preemption ile kısmen geri alınabilir; sched_ext'in iddiası budur" | **benim** (İŞ 6 çerçevelemesi) | İŞ 3 | nice +19 → %1.1, CPUWeight=1 → %0.7, ikisi de ns. Rakip −%0.2 kaybetti, yani **ondan bir şey istenmedi**. Boşluk bir öncelik problemi değil. |
| 3 | "Transient'in sebebi P-core frekans rampası olabilir" | senin adayın | İŞ 4 | Elendi ve ters yönde: A_P8 daha yüksek frekansta, daha kötü ITL. Frekans 800 ms'de, ITL 1 800 ms'de oturuyor. |
| 4 | "SWITCH prefill'de E-core alarak rakibe fatura çıkarır" | benim (İŞ 6) | İŞ 2 | Tersi: rakip **daha hızlı** bitiyor (−%3.7, p<0.01). |
| 5 | "`.o` sayısı build rakibinin iş metriği olur" | benim (tasarım) | ölçüm | 340 nesnenin tamamı ilk ~15 s'de üretiliyor, kalan ~25 s linkleme; sayaç pencere kapanmadan doyuyor. Duvar süresine geçildi. |

## Önceki oturumlardan devreden

migration sayısı (4 kez), SMT hipotezi, prefill'in migration duyarlılığı,
naif faz-aware politika, normalizasyonun çekirdek bağımsızlığı, salınım
endişesi, n_batch artefaktı, %99.6 doğruluk şişkinliği.

---

# D. OTURUMUN SORUSU: sched_ext'e giriyor muyuz?

## GÜNCELLEME (İŞ 7, aynı gün): cevap senaryoya bağlı

Aşağıdaki "HAYIR" cevabı, **paylaşılan-çekirdek senaryosu ölçülmeden**
verilmişti ve orada açıkça "sched_ext yeniden gündeme ancak şu ölçülürse
gelir" diye işaretlenmişti. O senaryo ölçüldü
(`results/i7_shared/FINDINGS.md`) ve tablo değişti:

| senaryo | kalan boşluk | scheduler'a ait mi |
|---|---|---|
| gerçekçi rakip (build) | **0 ms** — SWITCH Pareto baskın | — |
| doyuran rakip, **ayrık** çekirdek | ≤22 ms (ns) | hayır |
| doyuran rakip, **paylaşılan** çekirdek | **8 244 ms TTFT** artık | **kısmen** |

Paylaşılan çekirdekte öncelik gerçekten çalışıyor (CPUWeight=1 boşluğun
%48.5'ini, ITL p50'nin %56.2'sini geri alıyor, p<0.01) ama kapatmıyor.
Kalan artığın iki bileşeni var ve **ayrıştırılmadı**: (a) uyanma-preemption
gecikmesi — sched_ext'in hedefleyebileceği kısım; (b) rakibin LLM'in
boşluklarında koşarken yaptığı cache/bant genişliği girişimi — hiçbir
scheduler'ın çözemeyeceği kısım.

**GÜNCELLEME (İŞ 8, aynı gün): kapı kapandı.** `SCHED_IDLE` deneyi
(`results/i7_idle/`) (a)'yı (b)'den ayırdı:

| kol | TTFT geri | ITL p50 geri | rakibin bedeli |
|---|---|---|---|
| CPUWeight=1 | %49.1 | %55.5 | −%13.5 |
| **SCHED_IDLE** | **%83.4** | **%96.8** | −%55.0 |

**ITL boşluğunun %96.8'i (a) idi** — uyanma-preemption gecikmesi. Kalan
artık yalnızca **9.48 ms (boşluğun %3.2'si)** ve indirgenemez.
Ve (a)'yı çözen mekanizma Linux'ta zaten var: `chrt --idle`.

sched_ext'in ekleyebileceği düşünülen şey — "yalnızca decode uyanınca
preempt et, kalan zamanda rakibi tam hızda koştur" — mekanizma gereği
ulaşılamaz: `SCHED_IDLE` zaten iş-koruyucu katı önceliktir ve rakip
bu rejimde çekişmesiz hızının %40'ını, yani LLM'in bariyerlerde bıraktığı
boşlukların tamamını alıyor. Fazlasını vermek QoS'tan çalmak demektir.

**Karar: BPF yazılmıyor. Üç senaryonun üçünde de sched_ext'e ölçülmüş
gerekçe yok.**

Ayrıca bu senaryoda **faz anahtarlama Pareto baskın değil**: S1_switch,
S0_static'e karşı TTFT −%14.5 ama ITL p50 +%3.1. Kazandıran şey
anahtarlama değil, öncelik.

---

## Aşağıdaki cevap İŞ 7 öncesi geçerliydi (tarihsel kayıt)

## Cevap: HAYIR — ve gerekçesi ölçülmüş

Üç bulgu birlikte:

**1. Affinity zaten yetiyor.** Gerçekçi bir rakiple, kullanıcı alanındaki
faz anahtarlayıcı REVİZYON 2 ölçütünün **üç kriterini de** geçiyor ve her
iki tarafı birden iyileştiriyor (LLM TTFT −%10.8, rakip build −%3.7).
sched_ext'in kapatacağı bir açık yok.

**2. Kalan boşluk öncelikle kapanmıyor.** Doyuran rakip senaryosundaki
2 031 ms'nin %1'inden azı iki standart öncelik mekanizmasıyla geri alındı,
ve rakip hiçbir şey kaybetmedi. Bu, boşluğun bir **arbitraj problemi
olmadığını** gösteriyor — ortada aynı CPU için yarışan iki iş yok.
sched_ext'in ekleyeceği öncelik ifadesi burada kullanılacak bir yer bulamaz.

**3. Boşluğun kendisi senaryoya özgü.** E-core'ları tamamen tüketen bir
rakip, faz anahtarlamanın kullanacağı kapasiteyi yok ediyor. Bu bir
scheduling politikası eksikliği değil, kaynak yokluğu.

## Ölçülmüş boşluk: pratikte 0 ms

| senaryo | sched_ext'in geri alabileceği |
|---|---|
| gerçekçi rakip (build) | **0 ms** — affinity zaten Pareto baskın |
| doyuran rakip (loadgen) | **≤ 22 ms** (2 031 ms'nin %1.1'i, ns) |

İkinci satır bir üst sınırdır ve istatistiksel olarak sıfırdan ayırt
edilemez.

## Bunun anlamı: proje daha güçlü, daha küçük bir katkıya yerleşti

CLAUDE.md'nin "ML en son girer, belki hiç girmez" ilkesinin sched_ext'e
uygulanmış hâli. Katkı şu:

> Yerel LLM inference'ında prefill ve decode, aynı scheduling kararına zıt
> tepki veren iki ayrı iş yüküdür. Bu ayrım **uygulamaya dokunmadan**,
> yalnızca `/proc`'tan okunan context-switch hızıyla %99.6 doğrulukla ve
> negatif gecikmeyle tespit edilebilir; ve tespit edilince `sched_setaffinity`
> ile uygulanan basit bir maske değişimi, en iyi statik konfigürasyonu
> Pareto olarak baskılar — gerçekçi bir rakip varken hem LLM'i hem rakibi
> iyileştirerek.

Kernel değişikliği gerektirmiyor, BPF gerektirmiyor, uygulama yaması
gerektirmiyor. **Negatif sonuç değil, kapsamı daralmış ve daha sağlam bir
pozitif sonuç.**

## sched_ext hangi koşulda yeniden gündeme gelir

Ölçülmüş bir gerekçe ortaya çıkarsa:

- LLM ile rakibin **aynı çekirdekleri** paylaşmak zorunda olduğu bir
  senaryo (ör. rakip de P-core'lara pinli, ya da 24 thread'lik doyuran
  pinsiz yük) — orada öncelik gerçekten arbitraj edilecek bir şey bulur.
  Bu senaryo **ölçülmedi**.
- Birbirinden habersiz **birden fazla LLM process'i** (S4).
- Sert bölümlemenin israfının ölçülebilir hâle geldiği bir yapılandırma.

---

# E. AÇIK KALANLAR

| konu | ne gerekiyor | öncelik |
|---|---|---|
| Erken yerleşim hipotezi | anahtarlama anını 0/50/135/300 ms önce yapıp transient'i izlemek | yüksek |
| Paylaşılan-çekirdek senaryosu | rakip de P-core'da; sched_ext'in tek meşru adayı | yüksek |
| decode→prefill geri dönüşü | çok turlu konuşma; hâlâ test edilmedi | yüksek |
| Erken uyarının mekanizması | prompt, istemci gecikmesi, ubatch, frekans elendi | orta |
| S4 (çoklu LLM) | ölçülmedi | orta |
| Farklı build profilleri | tek proje test edildi | düşük |
| scx_lavd / scx_rustland | **kullanıcı onayı** | — |

---

# F. SENARYO TABLOSU — nihai

| senaryo | kazandıran mekanizma | sched_ext'in payı |
|---|---|---|
| rakipsiz | **faz anahtarlama** (affinity) — statikleri Pareto baskılıyor | 0 |
| gerçekçi rakip (`make -j16`, pinsiz) | **faz anahtarlama** — üç kriter de geçiyor, iki taraf da kazanıyor | 0 |
| doyuran rakip, **ayrık** çekirdek | hiçbiri — çekişme yok, alacak bir şey yok | 0 (≤22 ms, ns) |
| doyuran rakip, **paylaşılan** çekirdek | **`chrt --idle`** — ITL boşluğunun %96.8'i | 0 (artık %3.2, indirgenemez) |

Dört senaryonun dördünde de kazandıran mekanizma standart Linux'ta mevcut.

---

# Tek paragraflık özet

Ölçüt REVİZYON 2 ile düzeltildi (senaryo-parametrik). **İŞ 2 geçen oturumun
negatif sonucunu daralttı:** gerçekçi bir rakiple (`make -j16`, pinsiz) faz
anahtarlama kazancının neredeyse tamamını koruyor (TTFT −%10.8) ve rakibin
build'ini de hızlandırıyor (−%3.7) — takas değil, iki taraflı kazanç;
REVİZYON 2'nin üç kriteri de geçiliyor. Mekanizma doğrudan ölçüldü: SWITCH
prefill'de E-core'ları %90.5 dolduruyor, decode'da %0.0'a bırakıyor.
**İŞ 3 ve İŞ 7 birlikte önceliğin ne zaman işe yaradığını gösterdi:** ayrık
çekirdekte hiçbir şey (%1'den az, rakip −%0.2 — ondan zaten bir şey
istenmiyor), paylaşılan çekirdekte çok şey (CPUWeight=1 ile %49–56).
**İŞ 8 kalan artığı ayrıştırdı ve son kapıyı kapattı:** `SCHED_IDLE` ITL
boşluğunun **%96.8'ini** geri alıyor, geriye yalnızca 9.48 ms (%3.2)
indirgenemez artık kalıyor — yani decode gecikmesi neredeyse tamamen bir
uyanma-preemption problemiymiş ve çözümü `chrt --idle` olarak Linux'ta
hazır. sched_ext'in ekleyeceği düşünülen "yalnızca uyanınca preempt et"
davranışı ulaşılamaz bir Pareto noktası: `SCHED_IDLE` zaten iş-koruyucu
katı önceliktir ve rakibe LLM'in bariyerlerde bıraktığı boşlukların
tamamını veriyor. **Oturumun sorusuna nihai cevap: sched_ext'e girmiyoruz,
BPF yazılmıyor.** Dört senaryonun dördünde de kazandıran mekanizma standart
Linux'ta mevcut — üçünde `sched_setaffinity` ile faz anahtarlama, birinde
`chrt --idle`. Bu oturumda kendi iddialarımdan dördü çürüdü ("çekişme
altında kazanç yok", "boşluk preemption ile geri alınır", "SWITCH rakibe
fatura çıkarır", "`.o` sayısı iş metriği olur") ve hepsi C bölümünde
kayıtlı.
