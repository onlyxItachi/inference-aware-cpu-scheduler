# Makale İskeleti — LLM-Aware Scheduling

**Kaynak:** `RAPOR_FINAL.md` (542 koşu, 28 deney) + `CLAUDE.md`
**Hedef venue:** sistem workshop'u / short paper (HotOS–HotStorage tarzı, ya da
EuroSys/ATC workshop'ları). Üst sıra konferans hedeflenmiyor: tek makine, tek
runtime, tek model ailesi.
**Tarih:** 2026-07-19
**Amaç:** makaleyi yazmak değil, iskeletini çıkarmak ve zayıf noktalarını
hakemden önce bulmak.

---

# 1. ABSTRACT

> **Prefill and Decode Are Two Workloads: Externally Detectable Phase Structure
> in CPU LLM Inference**

Local LLM inference on CPUs is usually treated by the OS as a single,
homogeneous multithreaded job. We show it is not. On a hybrid x86 laptop
(8 P-core + 8 E-core), the prefill and decode phases of `llama.cpp` respond in
*opposite directions* to the same placement decision: adding E-cores to the
thread set speeds prefill by 13% while degrading decode tail latency (ITL p95)
by 9.4%. No static affinity configuration wins both. We further show the phase
boundary is observable from outside the application, using only per-thread
context-switch rates read from `/proc`, with no instrumentation, no patch, and
1.7% of one core: prefill recall ≥94.7% for prompts ≥128 tokens. Acting on this
signal with a single `sched_setaffinity` mask swap Pareto-dominates the best
static configuration we measured, improving both LLM time-to-first-token
(−10.8%) and a concurrent `make -j16` build (−3.7%). The gain is confined to
long-prefill turns: with prompt caching, turns 2–5 of a chat session show no
measurable effect. We also report a negative result — neither stock `scx_lavd`
nor `scx_rustland` beat this userspace policy, and 96.8% of the shared-core
interference gap is recovered by `chrt --idle` alone.

(≈195 kelime.)

**Uyarı:** Bu abstract raporun manşetlerini olduğu gibi taşıyor. Bölüm 3'teki
daraltmaları uyguladıktan sonra en az üç sayı değişmek zorunda ("best static
configuration" → "best of the two static configurations we measured"; "−3.7%"
ya gürültü tabanı ölçülüp savunulmalı ya düşürülmeli).

---

# 2. İDDİA LİSTESİ

| # | İddia (tek cümle) | Destek | Güç |
|---|---|---|---|
| **C1** | Prefill ve decode, aynı yerleşim kararına zıt yönde tepki verir: E-core eklemek prefill'i +%13 hızlandırır, decode ITL p95'ini +%9.4 bozar. | §2.6 tablo (9B/4B), §3.2 rakipsiz tablo | **kesin** — en sağlam bulgu, iki modelde, interleaved, eşiğin 4–6 katı |
| **C2** | Bu asimetri ölçeklenme veriminde de görünür: prefill %77, decode %49 (t2→t8). | §2.3 | **kesin** |
| **C3** | Decode'un kötü ölçeklenmesinin baskın sebebi bant genişliği (%72), kalanı model-boyutundan-bağımsız ~24 ms/token sabit maliyet. | §2.6 iki-model ayrıştırması | **spekülatif** — 2 nokta / 2 bilinmeyen, sıfır artık, hata payı yok; 91 GB/s teorik tavanı aşıyor (bkz. U6) |
| **C4** | Faz sınırı uygulamaya dokunmadan, `/proc` ctx-switch hızıyla tespit edilebilir (prefill recall ≥%94.7, prompt ≥128 tok). | §2.5 | **koşullu** — llama.cpp sınıfı bariyer-senkronize runtime; eşik tuning/test ayrımı belirsiz (U9) |
| **C5** | Dedektör faz sınırından **önce** tetikler (−133 ms / −115.6 ms) ve bu bir yer-gerçeği artefaktı değildir. | §2.5, §6 h#15 | **koşullu** — tek alternatif yer-gerçeğine karşı elendi; §8'deki kalan hipotez tam da yer-gerçeği tanımı problemi (U4) |
| **C6** | Faz anahtarlama, ölçülen statik kolları Pareto olarak baskılar (TTFT −%10.8, ITL p95 −%4.3, rakip build −%3.7). | §3.2 iki tablo | **koşullu** — "en iyi statik" yalnızca 2 kol; rakip metriğinin gürültü tabanı yok (U1, U2) |
| **C7** | Kazanç uzun prefill'li turlarda yoğunlaşır; `cache_prompt`'lu kısa turlarda ölçülemez (−%1.2, ns). | §3.4 tur tablosu | **kesin** — yazarın kendi iddiasını daraltması, iyi |
| **C8** | Faz geçişinde üretilen 2 338 migration gecikmeye %0.6 etki eder; migration sayısı yanlış metriktir. | §2.2 | **koşullu** — "sayı" reddedildi, "decode içi migration maliyeti" ayrıştırılmadı (U7) |
| **C9** | Doyuran rakip + paylaşılan çekirdek rejiminde `chrt --idle` ITL boşluğunun %96.8'ini geri alır. | §4.2 tablo | **kesin ama dar** — tek sentetik rakip (U8) |
| **C10** | Hazır scx scheduler'ları (lavd, rustland) en iyi kullanıcı-alanı çözümünü yenemez. | §4.0 matrisi | **koşullu** — 13'ün 2'si, varsayılan ayar, lavd bozuk loader ile (U5) |
| **C11** | Faz anahtarlamanın kazancı scheduler-bağımsızdır ama büyüklüğü scheduler'a bağlıdır (EEVDF −%11.2 → lavd −%4.7). | §4.0 soru 3 | **koşullu** — ilginç, alt-raporlanmış; makalede öne çıkarılmalı |
| **C12** | Asimetriyi sömürmenin getirisi model boyutuyla artar (9B −%11.5/+%9.4 → 4B −%7.4/+%19.3). | §2.6 | **koşullu** — n=2 model, aynı aile/mimari/kuantizasyon; "model boyutu ekseni" demek için iki nokta az |
| **C13** | Bu iş yükü için sched_ext gerekli değildir. | §4.4 | **spekülatif** — C10'un kapsamından çok daha geniş bir sonuç (U5) |
| **C14** | H4 doğrulandı: hibrit CPU'lar Linux varsayımlarını zorlar. | §7 | **spekülatif** — homojen-CPU kontrolü yok (U3) |

---

# 3. DESTEKLENMEYEN İDDİA AVI

En önemli bölüm. Her madde: **rapordaki ifade → sorun → önerilen daraltma /
eksik ölçüm.**

### U1 — "en iyi statik konfigürasyonu Pareto olarak baskılıyor" (§0, §3.2, §5)

Ölçülen statik kollar: **A_P8** ve **C_P8_E8**. Yani "tüm E-core'lar var" ya da
"hiç yok". Ara kol (P8+E2, P8+E4) **hiç ölçülmemiş**. Prefill kazancının çoğunu
daha az ITL hasarıyla veren bir statik ara nokta varsa, Pareto baskınlığı
iddiası çöker — ve §2.3'teki azalan marjinal getiri eğrisi böyle bir noktanın
var olmasını *bekletir*.

→ **Ya P8+E2/E4 ölçülecek, ya ifade "the two static endpoints we measured"
olacak.** Bu, makalenin manşet iddiasını doğrudan tehdit eden en ucuz hakem
itirazı.

### U2 — "hem LLM'i hem rakibi iyileştirerek" / "rakip build −%3.7" (§0, §3.2)

%2 gürültü tabanı **yalnızca LLM metrikleri için** ölçüldü (§1.1: TTFT, ITL,
decode). `make -j16` duvar saati için varyans hiç raporlanmadı — oysa build
süresi page cache durumuna, ccache'e, dosya sistemi durumuna duyarlıdır. −%3.7
iddiası kendi gürültü tabanı olmadan duruyor.

→ **Eksik ölçüm:** rakip metriğinin 20-koşuluk CV'si. O olmadan §3.2'nin "iki
taraflı kazanç" cümlesi tek taraflı kazanca indirilmeli.

### U3 — "H4 DOĞRULANDI: hibrit CPU'lar Linux varsayımlarını zorlar" (§7)

Kanıt: P-pinning varsayılanı %14.4 yeniyor. Bu, **hibritliğin** değil,
**Linux'un bu makinedeki yerleşim kararının** kötü olduğunun kanıtı. Homojen CPU
kontrolü yok; SMT-only bir asimetriyle ayrıştırılmadı. "Hibrit CPU'lar" cinsi
bir genelleme tek SKU'dan çıkarılıyor.

→ **Daraltma:** "On this hybrid SKU, the default scheduler's placement costs
14.4% decode throughput; we do not isolate hybridity as the cause." H4'ü hipotez
tahtasında **DOĞRULANDI → KISMEN** yap.

### U4 — "Erken uyarının mekanizması bilinmiyor ama artefakt olmadığı kanıtlandı" (§2.5, §6 h#15)

İçsel bir mantıksal çatlak var: §8'de kalan **en güçlü hipotez**, "prefill
grafiğinin kuyruğu efektif olarak decode şeklindedir (~116 ms ≈ bir decode
token'ı)". Bu hipotez doğruysa, dedektör *erken* tetiklemiyor — **gerçek bir
decode-benzeri hesap bölgesini doğru tespit ediyor** ve yer-gerçeği yanlış yerde
tanımlanmış. Yani §6 h#15'in "yer-gerçeği artefaktı değil" sonucu ile §8'in
kalan hipotezi birbiriyle çelişiyor: h#15 sadece *bir* alternatif yer-gerçeğini
(client-visible ilk token vs `graph_compute(batched=0)`) eledi, ikisi 0.30 ms
arayla olduğu için **aynı** yer-gerçeği sayılır. Üçüncü bir tanım (grafik içinde
logits hesabının başladığı an) hiç sınanmadı.

→ **Bu, "negatif gecikme"yi manşetten çıkarmak için yeterli gerekçe.** Ya
katman-düzeyi damgayla test edilsin, ya makale "negative detection latency"
iddiasını *"the detector fires ~115 ms before the conventionally-defined phase
boundary; we cannot yet rule out that the tail of the prefill graph is already
decode-shaped"* diye söylesin. Şu hâliyle en gösterişli iddia en zayıf ayakta
duruyor.

### U5 — "sched_ext'e girilmiyor / sched_ext'in katkısı yok" (§0, §4.4, C13)

Ölçülen: 13 scheduler'ın 2'si, **varsayılan ayarlarla**, üstelik lavd loader'ı
bu makinede SIGSEGV atıyor ve elle `--autopilot` ile koşuldu (yani
karşılaştırılan konfigürasyon, kullanıcıların göreceğinden farklı). Ayrıca
hipotez hiçbir zaman "stock scx yardım eder" değildi; hipotez **özel yazılmış**
bir politikaydı. Stock scheduler'ların kaybetmesi, custom bir scheduler'ın
kazanamayacağını göstermez.

→ **Daraltma:** "Two stock scx schedulers at default settings do not beat the
userspace policy; we did not implement a custom BPF scheduler, so this is
evidence about the availability of off-the-shelf alternatives, not about the
reachable ceiling of sched_ext." §4.3'teki "mekanizma gereği ulaşılamaz"
argümanı korunabilir ama o **ayrı** ve daha güçlü bir argüman — onu öne al,
C13'ü ona dayandır, C10'a değil.

### U6 — "gerçek akış bant genişliği 91 GB/s" (§2.4 düzeltme, §2.6, §7 K1)

Bu makinenin RAM'i DDR5, 2 kanal. DDR5-5600 için teorik tavan ≈ 89.6 GB/s.
**Ölçülen değer teorik tavanı aşıyor.** Bu, ya bellek hızının daha yüksek olduğu
(raporda hiç yazmıyor — DDR5 hızı belirtilmemiş), ya modelin bir kısmının
LLC'den servis edildiği (yani "saf akış" varsayımının bozuk olduğu), ya da
iki-noktalı uydurmanın yanlış olduğu anlamına gelir. Üç ihtimalin hiçbiri
kontrol edilmemiş. Üstelik bu sayı, daha önceki 66 GB/s'lik bir **hatanın
düzeltmesi** olarak sunuluyor — yani aynı hesap sınıfı ikinci kez, yine
doğrulanmadan, kesin bir sayı üretiyor.

→ **Eksik ölçüm:** (a) DDR5 hızını `dmidecode`'dan kayda geçir, teorik tavanı
hesapla; (b) bağımsız bir STREAM/`mbw` ölçümü ile taban çizgisi al. Bunlar
olmadan C3 makaleden çıkarılmalı ya da "consistent with a bandwidth-dominated
regime" düzeyine indirilmeli. **91 GB/s sayısı sayısal olarak
raporlanmamalı.**

### U7 — "Migration sayısı yanlış metrik" / "H3'ün naif hali reddedildi" (§2.2)

Deney migration sayısını 1644 kat artırıp her metriğin *iyileştiğini*
gösteriyor — ama migration sayısını artıran müdahale aynı zamanda başka şeyleri
değiştiriyor (raporun kendi ifadesiyle "belirleyici değişken fiziksel çekirdek
sayısı"). Yani bu, migration'ın zararsız olduğunun kanıtı değil, **çekirdek
sayısı etkisinin migration etkisini gölgelediğinin** kanıtı. Reddedilen şey
"migration sayısı gecikmeyle *korele*" iddiası; reddedilmeyen şey "decode
sırasında, token sınırına yakın bir migration o token'ı geciktirir".

→ **Daraltma:** "aggregate migration count is not a useful predictor of tail
latency" — bu doğru ve savunulabilir. "Migration doesn't matter" değil.
§7'deki "NAİF HALİ REDDEDİLDİ" ifadesi zaten doğru kelimeyi kullanıyor; §0 ve
§2.2 başlığı ("yanlış metrik") kullanmıyor.

### U8 — "Bugün kullanılabilecek tek satırlık tavsiye: rakibi `chrt --idle` ile koştur" (§0)

Tek bir rakiple ölçüldü: `loadgen`, always-runnable, compute-bound, sentetik.
Raporun kendisi "Başarı Ölçütü REV2"de bu rakibin "inşası gereği hiç boşluk
bırakmadığını" ve ondan genelleme yapılamayacağını **yazıyor** — sonra §0'da tam
da o genellemeyi yapıyor ("arka-plan-işi"). Gerçek arka plan işleri (I/O bekleyen
indeksleyici, bursty tarayıcı) SCHED_IDLE altında çok farklı davranır ve %55
throughput kaybı da farklı çıkar.

→ **Daraltma:** "for a CPU-saturating background job". Ya da `make -j16` ile de
ölçülüp genelleme desteklensin (bu ucuz: harness zaten var).

### U9 — "prefill recall ≥%94.7", "tek eşikle çalışıyor" (§2.5)

Eşik ve histerezis bandı (`lo=2100`, k=2) hangi veriden seçildi, hangi veride
değerlendirildi? Rapor bunu ayırmıyor. Eğer aynı koşulardan seçilip aynı
koşularda ölçüldüyse, bildirilen recall **in-sample**'dır. Ayrıca yalnızca
recall raporlanıyor: **yanlış-pozitif oranı yok**. Her zaman erken tetikleyen
bir dedektör recall'da mükemmel görünür. §3.4'teki 2 anomali ("−760 ms,
prefill'in en başında") tam da bir FP sınıfı gibi duruyor ama FP olarak
sayılmıyor.

→ **Eksik:** (a) train/test ayrımı ya da leave-one-config-out; (b) precision /
FP-per-turn; (c) eşiğin duyarlılık eğrisi. Bunlar olmadan C4 "koşullu"nun altına
düşer.

### U10 — "%3.3 anomali oranı" (§3.4)

30 turda 1 olay. Wilson %95 GA ≈ **%0.1 – %17**. Üç anlamlı haneli "%3.3"
yanıltıcı. Aynı şekilde "%10 anomali" (3/30) GA'sı ≈ %3–%27.

→ **Daraltma:** "1 of 30 turns (95% CI 0.1–17%)". Makale bu sayıya bir emniyet
argümanı bağlayacaksa (bağlamamalı), n artmalı.

### U11 — "5 turluk oturumda toplam bekleme −%8.2" (§0, §3.4, §5)

Kazancın tamamı tur 1'den geliyor, dolayısıyla bu yüzde **oturum uzunluğunun
keyfi bir fonksiyonu**: 10 turda ≈ −%4, 20 turda ≈ −%2. Manşette yüzde olarak
vermek, ölçek seçiminin sonucu belirlediğini gizliyor.

→ **Daraltma:** mutlak kazancı ver ("~1.19 s saved, independent of session
length"), yüzdeyi ancak oturum uzunluğuyla birlikte.

### U12 — Enerji iddiaları (§3.2 "en az enerjiyi harcıyor −%4.6", §3.4 "J/token −%2.5")

§1.1'deki 20-koşuluk gürültü çalışması **enerjiyi içermiyor**. RAPL'ın koşular
arası varyansı ölçülmemiş, üstelik CLAUDE.md bir noktada RAPL'ın root-only
olduğunu ve bazı taban çizgilerinin eksik olduğunu kaydediyor. −%2.5 ve −%4.6,
bilinmeyen bir gürültü tabanının üstünde mi altında mı bilinmiyor.

→ **Eksik ölçüm:** J/token için CV. Yoksa enerji makalede "reported, not
claimed" olarak ve **eşiksiz** verilmeli, "en az enerjiyi harcıyor" cümlesi
çıkmalı.

### U13 — "Genellik: ikinci model" (§2.6 başlığı, §0)

İkinci model: aynı aile, aynı mimari (`qwen35`), aynı katman sayısı, aynı
kuantizasyon, sadece genişlik farklı. Bu **generality** değil, **width-scaling
sensitivity**. Rapor bunu §2.6 içinde dürüstçe söylüyor ("boyut mu mimari mi
karıştırıcısı yok") ama §0 ve başlık "genellik" diyor.

→ **Daraltma:** "we vary model width within one family; architecture,
quantization, and runtime generality remain untested."

### U14 — "p<0.01" (her yerde)

Hangi test, eşleştirilmiş mi, tek/çift kuyruk, ve **düzeltme yok**. Rapor
onlarca kol × metrik karşılaştırması yapıyor; çoklu karşılaştırma düzeltmesi
hiçbir yerde geçmiyor. Ayrıca %2 "gürültü tabanı" eşiği ile p-değeri **iki
farklı** kabul kriteri ve nerede hangisinin bağlayıcı olduğu tutarlı değil
(§4.0'da bir yerde %2 eşiği p<0.01'i geçersiz kılıyor, başka yerde ikisi
birlikte anılıyor).

→ **Metodoloji bölümünde tek paragraf:** test adı, eşleştirme, ve "%2 eşiği
birincil, p ikincil" (ya da tersi) kararının **açık** ifadesi.

### U15 — Gürültü tabanının transferi (§1.1 → her yer)

%2, **tek konfigürasyonda, rakipsiz, tek oturumda** ölçüldü. Sonra çekişmeli,
E-core'lu, çok turlu, scx-yüklü koşulara aynen uygulanıyor. Çekişme altında
varyansın aynı kaldığı hiç gösterilmedi — ve §3.2'nin oturum notu zaten
oturumlar arası %0.5–0.7'lik bir kayma olduğunu itiraf ediyor.

→ **Eksik ölçüm (ucuz, yüksek getirili):** aynı 20-koşuluk protokolü
*çekişmeli* kolda tekrarla. Tek sayı, makalenin bütün eşik mimarisini
sağlamlaştırır.

### U16 — "OS iş yükünü anlıyor" (§5)

Dedektör LLM process'inin PID'ini ve thread setini bilmek zorunda ve onun
`sched_setaffinity`'sini çağırma yetkisine ihtiyaç duyuyor — yani "hangi process
LLM" bilgisi **dışarıdan verilmiş** bir ipucudur. CLAUDE.md'nin H5 ayrımı ("OS
anlıyor" vs "uygulama ipucu veriyor") açısından bu ara bir konum: uygulama
yamalanmıyor ama politika uygulamanın kimliğini biliyor.

→ **Daraltma / açık varsayım:** "given a designated process, the phase is
inferable without instrumentation." Process **keşfi** kapsam dışı ilan edilsin.

---

# 4. HAKEM SORULARI (en sert 8)

**R1. "Best static configuration"un yalnızca iki uç nokta olduğunu fark ettim.
P8+E4 neden yok?**
→ **Cevap raporda YOK.** Manşet iddiayı doğrudan tehdit ediyor (U1).
*Gerekli:* 2–3 ara statik kol, aynı interleaved protokolle, rakipsiz + build
senaryosunda. Bu, kabul için **zorunlu** ek ölçüm — makaleyi bununla göndermek
gerekir.

**R2. Dedektörünüz faz sınırından önce mi tetikliyor, yoksa sizin faz sınırı
tanımınız mı yanlış?**
→ **Kısmi cevap var** (§2.5, §6 h#15) ama **eledikleri iki yer-gerçeği aynı
olaydan 0.30 ms uzaklıkta**, yani tek bir tanım. §8'in kendi kalan hipotezi bu
soruya "tanım yanlış" diyor. *Gerekli:* llama.cpp grafiği içinde katman-düzeyi
damga; prefill grafiğinin son ~116 ms'sinin decode-şekilli olup olmadığı.
Cevaplanana kadar "negative detection latency" manşetten çıkmalı (U4).

**R3. Bir scheduler yazmadan sched_ext hakkında negatif sonuç bildiriyorsunuz.
Bu nasıl meşru?**
→ **İki katmanlı cevap var, biri zayıf biri güçlü.** Zayıf olan §4.0 (2/13
scheduler, varsayılan ayar — U5). Güçlü olan §4.3: `SCHED_IDLE` zaten
iş-koruyucu katı önceliktir, kalan artık %3.2'dir, ve rakip zaten LLM'in bariyer
boşluklarının tamamını alıyor — yani **tavan mekanizma gereği düşük**. Makale
güçlü argümanı öne almalı; §4.0'ı destek delil olarak arkada tutmalı.

**R4. %2 gürültü tabanınız tek bir rakipsiz konfigürasyondan. Çekişme altında
hâlâ %2 mi?**
→ **Cevap YOK** (U15). *Gerekli:* çekişmeli kolda 20-koşuluk tekrar. Ucuz ve
makalenin tüm eşik iddialarını taşıyor.

**R5. Rakibin −%3.7'lik build kazancı için gürültü tabanı nedir?**
→ **Cevap YOK** (U2). "Two-sided win" bu makalenin en cazip cümlesi ve şu an
desteksiz. *Gerekli:* build duvar saati CV'si; build'in her koşuda gerçekten
temiz başlatılıp başlatılmadığının belgelenmesi.

**R6. 91 GB/s teorik bellek tavanınızın üstünde. Bunu nasıl açıklıyorsunuz?**
→ **Cevap YOK** (U6). Üstelik aynı hesap sınıfı raporda bir kez zaten yanlış
çıkmış (66 GB/s). *Gerekli:* bağımsız STREAM taban çizgisi + DDR5 hızının kayda
geçmesi. Aksi hâlde C3 çıkarılmalı — makalenin geri kalanı C3 olmadan **ayakta
duruyor**, o yüzden çıkarmak ucuz.

**R7. Eşiği hangi veride seçtiniz, hangi veride ölçtünüz? Ve yanlış-pozitif
oranınız nedir?**
→ **Cevap YOK** (U9). Bir dedektör makalesinde recall'ı precision'sız
raporlamak tek başına reject gerekçesi olabilir. *Gerekli:* held-out
değerlendirme + FP/tur.

**R8. Tek makine, tek runtime, tek model ailesi, tek kuantizasyon. Bu sonuçlar
neyin hakkında?**
→ **Kısmi cevap var** ve raporun en olgun yanı: §2.5'in "bariyer-senkronize
runtime" çekincesi, §2.6, §5'in kapsam paragrafı. *Gerekli:* bu çekinceler
**abstract'a ve giriş'e** taşınmalı, tartışmada saklanmamalı. Workshop için tek
makine savunulabilir — ama ancak iddia baştan o kapsamla kurulursa. (İkincil:
bir spin-wait runtime — örn. OpenBLAS threading ya da farklı bir bariyer
stratejisi — ile tek koşu bile H5'in kapsamını dramatik biçimde netleştirir; şu
an §8'de "açık" olarak duruyor ve en yüksek getirili tek ek deney bu.)

**Bonus (hakem sormasa da editör sorar):** Katkı yeni mi? Prefill/decode ayrımı
LLM serving literatüründe (disaggregation) yerleşik. Bu makalenin yeniliği
ayrımın *kendisi* değil, (a) **CPU** tarafında ve **hibrit** çekirdeklerde
ölçülmüş olması, (b) **dışarıdan, enstrümantasyonsuz** tespit edilebilmesi.
Giriş bu farkı ilk paragrafta kurmazsa "known result, new hardware" damgası
yer.

---

# 5. BÖLÜM YAPISI

**Hedef:** 6 sayfa + referans (workshop) ya da 10–12 sayfa (short paper).

| Bölüm | İçerik | Tablolar / Şekiller |
|---|---|---|
| **1. Introduction** | Yerel CPU inference'ın yükselişi; OS onu tek bir job sanıyor; üç katkı cümlesi (C1, C4/C6, C10/C13'ün *daraltılmış* hâli); kapsam çekincesi **burada** (R8) | — |
| **2. Background & Setup** | prefill/decode, hibrit topoloji, llama.cpp threading modeli, sched_ext'in ne olduğu | Tablo: donanım + model + yazılım sürümleri (üretilebilirlik) |
| **3. Methodology** | interleaved protokol + §1.2 drift bulgusu (bu **bağımsız bir metodolojik katkı**, sat), %2 gürültü tabanı, istatistiksel test tanımı (U14), `/proc` tabanlı sayaçlar | §1.1 gürültü tablosu; drift korelasyonu (r=0.671) tek satır |
| **4. The Asymmetry (Characterization)** | C1, C2; mekanizma tartışması | §2.3 verim + marjinal getiri tabloları; §2.6 9B/4B karşılaştırması; §3.2 E-core doluluk tablosu (mekanizma kanıtı — **bu şekil olmalı**) |
| **5. External Phase Detection** | C4, C5 (daraltılmış); dedektör tanımı, maliyet, sınırlar | §2.5 ölçüm tablosu + **yeni**: precision/FP, held-out; zaman serisi şekli (ctx-switch rate + faz sınırı + tetikleme anı) |
| **6. Evaluation** | ↓ alt başlıklar iddia listesiyle eşleşiyor | |
| 6.1 Uncontended | C6-a | §3.2 rakipsiz tablo + **yeni ara statik kollar** (R1) |
| 6.2 Realistic competitor | C6-b | §3.2 build tablosu + rakip gürültü tabanı (R5) |
| 6.3 Saturating competitor | C9 + §3.3 sınırı | §4.2 SCHED_IDLE tablosu |
| 6.4 Multi-turn / prompt cache | C7 | §3.4 tur tablosu; mutlak kazanç (U11) |
| 6.5 Model size | C12 | §2.6 E-core takası tablosu |
| 6.6 Scheduler sensitivity | C10, C11 | §4.0 3×4 matrisi |
| **7. Negative Results & Refuted Hypotheses** | **Bu makalenin imzası.** 17'yi 5–6'ya indir (migration, %87 bandwidth, küçük-model beklentisi, ölçüt hatası, %99.6 doğruluk) | §6 tablosunun kısaltılmış hâli |
| **8. Discussion: Why not sched_ext** | C13, ama **§4.3 argümanına dayalı** (U5) | §4.1 senaryo tablosu |
| **9. Limitations** | U3, U6, U8, U13, U16 açıkça; tek makine | — |
| **10. Related Work** | ↓ bölüm 6 | — |

**Kesilecekler (yer yok, kayıp az):** BLAS elemesi (§2.4), 202 µs anahtarlama
maliyeti, dosya haritası, `scxctl` SIGSEGV notu → dipnot. **Sıkı bir seçim:**
C3 (bandwidth ayrıştırması) U6 çözülmezse tamamen çıkar; makale ondan zarar
görmez.

---

# 6. İLGİLİ ÇALIŞMA HARİTASI

Makale adı uydurulmadı; damar tanımı + arama terimi veriliyor.

**D1 — Hibrit/heterojen CPU scheduling.**
Big.LITTLE'dan Intel Thread Director'a: OS'un asimetrik çekirdeklere iş
yerleştirmesi. Bu iş buraya **negatif** dokunuyor: varsayılan yerleşim bu iş
yükünde %14 kaybettiriyor.
*Ara:* `heterogeneous multicore scheduling Linux`, `big.LITTLE energy aware
scheduling EAS`, `Intel Thread Director hardware feedback interface`,
`asymmetric CPU capacity scheduler`, `utilization clamping uclamp`.
*Aranacak boşluk:* bu literatürün iş yükü modeli genelde "bir task'ın tek bir
karakteri var". Bu makalenin iddiası bir task'ın **zamanla karakter
değiştirdiği**; onu söyleyen önceki iş var mı (phase-aware scheduling, D5) diye
bak.

**D2 — LLM serving sistemleri ve prefill/decode ayrımı.**
En riskli damar: prefill/decode disaggregation GPU tarafında yerleşik.
*Ara:* `prefill decode disaggregation LLM serving`, `chunked prefill continuous
batching`, `inference serving TTFT TBT SLO`, `LLM inference scheduling latency
throughput tradeoff`, `speculative decoding scheduling`.
*Konumlanma:* bu literatür ayrımı **uygulama içinde** yapıyor ve **GPU**'da. Bu
makale ayrımı **OS'ta**, **CPU**'da, **uygulamaya dokunmadan** yapıyor. Bu farkı
giriş paragrafında net kurmazsan reddedilirsin.

**D3 — CPU tarafı LLM inference performansı.**
*Ara:* `llama.cpp CPU inference performance`, `quantized LLM inference commodity
CPU`, `memory bandwidth bound transformer decode`, `roofline analysis LLM
inference`, `AVX GEMM quantized inference`.
*Amaç:* C3'ün (bandwidth vs sabit maliyet) bilinen sonuçlarla çelişip
çelişmediğini kontrol et. U6'yı çözmenin en hızlı yolu da bu: birinin ölçtüğü
CPU decode bandwidth sayısıyla karşılaştır.

**D4 — Uygulama-bilgili / niyet-bilgili OS politikaları.**
*Ara:* `application-aware scheduling hints OS`, `QoS-aware CPU scheduling
interactive latency`, `latency-critical vs batch colocation datacenter`,
`Heracles Caladan Shenango core allocation`, `microsecond-scale scheduling`.
Özellikle **çekirdek tahsisini μs–ms ölçeğinde ayarlayan** sistemler
(Caladan/Shenango damarı) bu işin en yakın akrabası; onlar da "hızlı yol / yavaş
yol" ayrımı yapar. Bu makalenin farkı: sinyal **uygulamadan değil `/proc`'tan**
geliyor. O sistemlerle karşılaştırma **beklenecek**.

**D5 — Program fazı tespiti (klasik).**
*Ara:* `program phase detection basic block vector`, `SimPoint phase behavior`,
`online phase detection hardware counters`, `phase-aware DVFS frequency
scaling`.
2000'lerin mimari literatürü. Bu makalenin dedektörü kavramsal olarak buraya ait
ve **bu bağı kurmak makaleyi güçlendirir**: klasik faz tespiti donanım sayaçları
kullanırdı; burada sinyal senkronizasyon davranışından geliyor. Bu literatürde
precision/recall raporlama standartları da var — U9'u çözerken referans al.

**D6 — sched_ext / BPF ile genişletilebilir scheduling.**
*Ara:* `sched_ext BPF extensible scheduler Linux`, `scx_lavd scx_rustland
scheduler evaluation`, `ghOSt userspace scheduling Google`, `userspace
delegation of scheduling policy`.
*Dikkat:* bu damar bu makalede **negatif sonuç** taşıyor. ghOSt damarı özellikle
önemli çünkü "userspace'e ne kadar delege edilebilir" sorusunu zaten sormuş; bu
makale de fiilen userspace'te kalıyor.

**D7 — Öncelik/izolasyon mekanizmaları (ince ama gerekli).**
*Ara:* `SCHED_IDLE background task interference`, `cgroup cpu.weight interference
isolation`, `noisy neighbor CPU contention mitigation`.
C9 (`chrt --idle`) yeni bir mekanizma değil; yeni olan **bu iş yükünde boşluğun
%96.8'ini aldığının ölçülmesi**. Bu damarı kurmadan C9'u sunarsan "eski aleti
yeniden keşfetmiş" görünürsün; kurarsan "bilinen alet, beklenmedik ölçüde
etkili" olur — ki asıl mesaj bu.

---

# 7. Son not — üç cümlelik teşhis

Çalışmanın en güçlü yanı **çürütme disiplini**; en zayıf yanı, o disiplinin
**kendi manşet iddiasına aynı sertlikte uygulanmamış** olması: "en iyi statik
konfigürasyon" iki uç noktadan ibaret (U1), "negatif gecikme" kendi §8'inin
hipoteziyle çelişiyor (U4), ve "iki taraflı kazanç"ın rakip ayağının gürültü
tabanı hiç ölçülmemiş (U2). Bu üçü kapatılırsa makale workshop için sağlam;
kapatılmazsa ilk hakem üçünü de bulur ve raporun kendi standardıyla vurur.

## Gönderim öncesi zorunlu ek ölçüm listesi

| # | Ölçüm | Kapattığı | Maliyet |
|---|---|---|---|
| 1 | Ara statik kollar (P8+E2, P8+E4), rakipsiz + build | U1 / R1 | orta — harness var |
| 2 | Çekişmeli kolda 20-koşuluk gürültü tabanı | U15 / R4 | düşük |
| 3 | `make -j16` duvar saati CV'si | U2 / R5 | düşük |
| 4 | Dedektör held-out değerlendirme + FP/tur | U9 / R7 | düşük (mevcut veriden) |
| 5 | STREAM taban çizgisi + DDR5 hızı kaydı | U6 / R6 | çok düşük |
| 6 | *(opsiyonel, yüksek getirili)* spin-wait runtime ile tek koşu | R8 | orta |
| 7 | *(opsiyonel)* katman-düzeyi damga ile faz sınırı | U4 / R2 | yüksek |
