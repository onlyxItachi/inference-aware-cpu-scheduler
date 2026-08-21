# Proje: LLM-Aware Scheduling (sched_ext)

# REVISION 3 — Conference Upgrade (2026-08-21)

Bu bölüm, konferans yükseltme çalışmaları için aşağıdaki tarihsel
araştırma çerçevesinden önceliklidir. Tarihsel metin ve sonuçlar denetlenebilir
kayıt olarak korunur; yeni işlerin kapsamını ve iddialarını
`CONFERENCE_UPGRADE_TASKS.md` belirler.

- Prefill/decode ayrımı projenin yeniliği değil, arka plan bilgisidir.
- Heterojen P/E-core'lar arasındaki performans farkı ve bunun doğurduğu yük
  dengesizliği projenin yeniliği değil, arka plan bilgisidir.
- Aday merkezi katkı, **değiştirilmemiş bir inference runtime'ından istek
  düzeyindeki faz bilgisini OS tarafından görülebilen sinyallerle dışarıdan geri
  kazanmak ve bu bilgiyi inference engine iş birliği olmadan, eyleme
  dönüştürülebilir OS düzeyi CPU yerleştirmesinde kullanmaktır**. Bunun merkezi
  katkı olarak savunulabilirliği C01/C02 sonuçlarına bağlıdır; henüz kanıtlanmış
  bir yenilik olarak sunulmaz.
- Varsayılan Linux scheduler'ının ve Intel Thread Director/HFI donanım
  rehberliğinin fazlara göre nasıl davrandığı bilinmiyor kabul edilir. Bu davranış
  C01'de ölçülür; çözdüğü veya çözmediği varsayılmaz.
- AVX yürütme asimetrisi, vektör genişliği ve diğer mikro-mimari
  açıklamalar, nedensel kanıtla desteklenene kadar yalnızca hipotezdir; ölçülmüş
  sonuç veya nedensel gerçek gibi yazılmaz.
- **C01 ve C02 sert araştırma kapılarıdır.** Her kapının çıktıları analiz
  edilip checkpoint onayı verilmeden sonraki araştırma dalına geçilmez.
- C01 ve C02 analiz edilmeden C03 genellik çalışmasına veya C04 mekanizma
  genişletmesine başlanmaz; bu başlıklarda kapsam kendiliğinden büyütülmez.
- Konferans seçimi yalnızca bilimsel uyuma dayanmaz. Yazarın fiziksel katılım
  zorunluluğunu karşılayabilmesi veya uzaktan sunumun resmen mümkün olması da
  zorunlu bir uygunluk kapısıdır.
- Konferans yükseltme dönemindeki ileriye dönük işlerin tek yetkili planı
  `CONFERENCE_UPGRADE_TASKS.md` dosyasıdır. Tarihsel dosyalar geriye dönük
  kanıttır; yeni görev sırası veya yeni iddia yetkisi vermez.

## Amaç

Bu proje **bir scheduler yazma projesi değil**, bir **iş yükü karakterizasyonu**
projesidir. Asıl soru:

> Yerel LLM inference'ında, mevcut Linux scheduling varsayımlarının
> karşılamadığı şaşırtıcı bir davranış var mı?

Böyle bir gözlem bulunursa, ona göre bir sched_ext politikası tasarlanır.
Gözlem yoksa, bunu **negatif bulgu olarak raporlamak da geçerli bir sonuçtur**
ve proje başarısız sayılmaz. Scheduler'ı implemente etmek, gözlemi bulmaktan
daha az önemlidir.

## Merkezi hipotez: iki faz

- **prefill** — promptun tamamının tek seferde işlenmesi. Hesap-yoğun, paralel,
  throughput odaklı. İstediği: geniş çekirdek kullanımı, maksimum CPU.
- **decode** — token token üretim. Gecikmeye duyarlı, muhtemelen bellek bant
  genişliği sınırlı. İstediği: kararlı gecikme, az migration, cache locality,
  P-core.

Linux bu ikisini birbirinden ayırt etmiyor. Eğer gerçekten farklı scheduling
davranışı gerektiriyorlarsa, projenin en güçlü katkısı buradan çıkar.

## Test edilecek hipotezler

- **H1** — Decode thread'leri E-core'a düştüğünde gecikme belirgin biçimde artar.
- **H2** — Prefill, decode'a girişim yapar (aynı çekirdekleri paylaştıklarında).
- **H3** — Thread migration token gecikmesini anlamlı ölçüde etkiler.
- **H4** — Hibrit CPU'lar mevcut Linux scheduling varsayımlarının zayıflığını
  açığa çıkarır.
- **H5** — Faz tespiti (prefill/decode ayrımı) uygulamadan yardım almadan,
  dışarıdan gözlemle mümkündür.

**H5 kritik ve dokümante edilmesi gereken bir varsayımdır.** Tüm phase-aware
mimarisi, userspace daemon'ın fazı ayırt edebilmesine dayanıyor. Eğer bu sadece
llama.cpp'yi enstrümante ederek mümkünse, katkının adı değişir: "OS iş yükünü
anlıyor" değil, "uygulama OS'a ipucu veriyor" olur. İkisi de meşru, ama aynı şey
değil. Faz 1'de açıkça test edilecek.

## Karar kapıları (Hafta 1'de cevaplanmalı)

Bunlar "riskler" değil, projenin yönünü belirleyen **erken kararlar**. Faz 1'den
önce cevaplanır:

- **K1 — Bellek bant genişliği duvarı.** CPU'da decode muhtemelen
  bandwidth-bound. Öyleyse çekirdek eklemek veya pinning decode'u pek
  iyileştirmez ve scheduler'ın manevra alanı dardır.
  *Ölçüm:* thread sayısı 2→4→6→8 artırılırken decode hızının nerede doyduğuna
  bak. Erken doyuyorsa bandwidth-bound.
  *Not:* bu kötü haber değil, bulgunun kendisi olabilir.
- **K2 — Scheduler duyarlılığı.** LLM iş yükü scheduler'a yeterince duyarlı
  olmayabilir; kazanç %2–3'te kalabilir. Bu durumda proje karakterizasyon
  çalışmasına döner.
- **K3 — Gürültü tabanı.** Laptop'ta koşular arası varyans %10'u aşabilir
  (termal, turbo, favored core'a düşüp düşmemek). **Faz 0'ın ilk çıktısı bir
  iyileştirme değil, aynı konfigürasyonun 20 tekrarındaki varyanstır.** Efekt
  boyutu gürültünün altındaysa ölçülen şey rüzgârdır. Bu, laptop'ta çalışmanın
  en gerçek metodolojik tehdidi.

## Bilinçli olarak kapsam DIŞI

Tartışıldı ve gerekçeleriyle reddedildi; yeniden önerilmemeli:

- **Kernel içinde model çalıştırmak (ring 0'da inference).** Scheduling kararı
  mikrosaniye mertebesinde verilir; sıcak yola model inference'ı koymak
  scheduler'ın kendisini sistemdeki en pahalı iş yapar. Kararlılık ve güvenlik
  açısından da kabul edilemez.
- **Scheduling yolunun içinde reinforcement learning.**
- **Genel amaçlı "öğrenen scheduler".** Hedef fonksiyonu yok (throughput mu, p99
  mu, enerji mi?), yer-gerçeği yok, EEVDF geniş cephede çok güçlü bir taban
  çizgisi. Dar problem seçildi çünkü ölçülebilir yer-gerçeği var.
- **GPU scheduling.** Linux CPU scheduler'ı GPU'da hangi kernel'ın çalışacağına
  karar vermez; bunu CUDA stream'leri, sürücü ve GPU'nun donanım zamanlayıcısı
  belirler. sched_ext oraya dokunamaz.
- **Kernel bellek yönetimi değişiklikleri** (KV-cache, CXL, paylaşımlı prefix).
  İlginç ama ayrı bir proje.
- **Production scheduler'ı tamamen değiştirmek.**

Kapsamı dar tutmak kritik.

## Mimari ilke: hızlı yol / yavaş yol ayrımı

- **Sıcak yol (BPF, mikrosaniye):** deterministik, hafif, güvenli. Sorumluluğu:
  dispatching, timeslice kararları, DSQ yönetimi. Paylaşılan BPF map'inden
  parametre okur.
- **Yavaş yol (userspace daemon, saniye):** telemetri toplar, faz tespiti yapar,
  parametreleri uyarlar, loglar.

Model/daemon karar **vermez**; kararı veren ucuz kodu **ayarlar**.

**Daemon asla sert bağımlılık olmamalı.** Çökerse scheduler eski
parametrelerle çalışmaya devam eder.

ML bu projeye **en son** girer — ve belki hiç girmez. Önce elle ayarlanmış
eşiklerle çalışan, işe yaradığı ölçülmüş bir politika olacak.

## Donanım

- CPU: Intel i7-14650HX — 8 P-core + 8 E-core, 24 thread
- **CPU 0–15** = P-core'lar, SMT aktif (fiziksel çekirdek başına 2 thread).
  Fiziksel başına tek thread listesi: `0,2,4,6,8,10,12,14`
- **CPU 16–23** = E-core'lar, SMT yok, 4'erli L2 cluster'lar
- Max frekans: P-core 5000 MHz, E-core 3700 MHz
- **CPU 8–11 (fiziksel core 4–5) 5200 MHz** — Intel favored cores. Gecikmeye en
  duyarlı thread'ler için koz; ayrıca **ölçüm varyansının gizli kaynağı** (bir
  koşunun oraya düşüp düşmemesi sonucu değiştirir).
- RAM: 32 GB DDR5
- GPU: RTX 5070 Laptop, 8 GB VRAM — **bu projede kullanılmıyor**, inference
  CPU-only
- OS: CachyOS, kernel 7.1.3-2-cachyos
- Kernel config `/boot`'ta değil: `zgrep ... /proc/config.gz`
- `/sys/kernel/sched_ext/state` = "disabled" → sched_ext derlenmiş, henüz custom
  scheduler yüklü değil. Normal durum.
- scxctl scheduler adlarında `scx_` öneki yok: `sudo scxctl start --sched lavd`

## Metrikler

**Birincil:**

- **TTFT** — time to first token; prefill gecikmesi.
- **Inter-token latency dağılımı — p50 / p95 / p99.** Ortalama token/sn
  **yetersizdir**: aradaki takılmaları gizler ve avlanan şey tam da odur. Bu,
  token başına zaman damgası gerektirir (llama.cpp server + streaming veya
  per-token timing), toplu throughput sayısı değil.
- **Throughput** — token/sn (ikincil, regresyon kontrolü için).

**Sistem metrikleri:** CPU kullanımı, thread migration sayısı, LLC miss, context
switch, CPU frekansı, **paket sıcaklığı** (zorunlu), scheduler istatistikleri.

## Baseline'lar

Bunların hepsine karşı ölçülmeli, yoksa "EEVDF'i yendim" demek yeterli olmaz:

- Linux EEVDF (varsayılan)
- `scx_lavd`
- `scx_rustland`
- taskset affinity varyantları: pinsiz / P-noSMT / P-SMT / E-only

## Deney senaryoları

- **S1** — sadece LLM
- **S2** — LLM + derleme yükü (`make -j`, `stress-ng`)
- **S3** — LLM + tarayıcı yükü
- **S4** — birden fazla eşzamanlı LLM örneği
- **S5** — arka planda indeksleme
- **S6** — ağır termal koşullar

## Faz planı

**Faz 0 — Baseline ve gürültü tabanı.** Scheduler yazılmaz. Harness kurulur,
K3 (varyans) ölçülür, tüm baseline'lar ve affinity varyantları S1/S2 altında
ölçülür. Çıktı: CSV + varyans raporu.

**Faz 1 — Karakterizasyon ve hipotez testleri.** K1, K2, H1–H5 cevaplanır.
**Önemli: H1–H4'ün hiçbiri scheduler yazmayı gerektirmiyor.** `taskset` ve
cgroup ile decode zorla E-core'a konabilir, prefill ve decode aynı çekirdeklere
sıkıştırılıp girişim ölçülebilir. Aranan "şaşırtıcı gözlem" tek satır BPF
yazmadan bulunabilir.

**Faz 2 — Basit sezgisel scheduler.** Ancak bir hipotez tuttuysa. sched_ext ile
düz mantık, elle konmuş eşikler.

**Faz 3 — Phase-aware scheduling.** Faz ayrımının scheduler'a tanıtılması.

**Faz 4 — Uyarlanabilir scheduler.** Daemon eşikleri telemetriden ayarlar.

## Çalışma kuralları

1. **Ölçüm hakemdir.** "İyileştirdim" kabul edilmez; baseline'a karşı ölçülmüş
   sayı istenir. Her iterasyonda önce/sonra.
2. **Efekt gürültüden büyük olmalı.** Her iddia, K3'te ölçülen varyans tabanıyla
   karşılaştırılarak sunulur. Varyansın altındaki fark bulgu değildir.
3. **Tekrarlanabilirlik.** Thread sayısı, batch size, prompt, tekrar sayısı
   sabit ve kayıtlı. Tek koşu değil, N tekrar → medyan + p95.
4. **Faz atlanmaz.** Faz 0 sayıları çıkmadan scheduler kodu yazılmaz.
5. **Scheduler doğruluğu önce VM'de.** Bozuk bir sched_ext scheduler'ı sistemi
   kilitleyebilir. Stall watchdog ve sysrq acil çıkışı var, ama yarı yazılmış
   scheduler bare metal'de denenmez. Bare metal sadece doğrulanmış scheduler'la
   ve sadece ölçüm için.
6. **Ajan kendi başına scheduler yüklemez / değiştirmez / tehlikeli komut
   çalıştırmaz.** Bunlar kullanıcı onayıyla, kullanıcı ekrana bakarken yapılır.
7. **Benchmark hijyeni.** Ölçüm sırasında tarayıcı, IDE, arka plan derlemesi
   yok (S3 hariç, orada kasıtlı). Koşular arası soğuma payı. Sıcaklık her
   koşuda kaydedilir.
8. **Negatif sonuç da sonuçtur.** Deneyler bir sonucu çıkarmak için değil,
   doğruyu bulmak için tasarlanır.

## Başarı Ölçütü — REVİZYON 2 (2026-07-19, geçerli olan)

**REVİZYON 0 ve 1 aşağıda tarihsel kayıt olarak duruyor, silinmedi.**

### Bu bir hedef değişikliği DEĞİL, ölçme hatasının düzeltilmesidir

REVİZYON 1'de somut bir hata vardı: QoS referansları (TTFT 9 725,
ITL p95 90.10) **rakipsiz** koşulardan, rakip referansı (17 954 it/s)
**çekişmeli** koşudan alınmıştı. İki farklı senaryonun sayıları tek
ölçütte karıştırılmıştı.

Sonucu: senaryo çekişmeli olduğu için rakipsiz bir TTFT'yi yakalamak
tanım gereği imkânsızdı; **mevcut baseline A_P8 bile kendi ölçütünü
ihlal ediyordu** (11 570 > 9 920). Ölçüt hiçbir politika tarafından
geçilemezdi ve bu, politikalar hakkında değil ölçüt hakkında bir
bilgiydi.

Hedef aynı kalıyor: faz farkındalığı, en iyi statik konfigürasyonu
Pareto olarak baskılamalı. Değişen tek şey, karşılaştırmanın **aynı
senaryo içinde** yapılması.

### Senaryo-parametrik ölçüt

Her senaryo **S** için, faz-farkındalıklı politika, **aynı S içinde
ölçülmüş** en iyi statik kollara karşı:

1. **TTFT**'de ve **ITL p95**'te aynı anda yenmeli veya eşitlemeli
   (%2 gürültü tabanı hesaba katılarak — yani ≤ referans × 1.02)
2. **rakip throughput**'unu aynı S'teki en iyi statik kolun %2 altına
   düşürmemeli

Referanslar her senaryoda yeniden ölçülür; senaryolar arası sayı
taşınmaz.

İkincil eksen (raporlanır, kısıt değil): **J/token**.

### Mevcut sonuçların düzeltilmiş okuması

| senaryo S | statik referanslar (aynı S) | SWITCH | sonuç |
|---|---|---|---|
| **rakipsiz** | TTFT 9 753 (C), ITL p95 89.94 (A) | 9 748 / 86.71 | **GEÇER** — ikisini de yeniyor |
| **çekişme, E-pinli loadgen** | TTFT 11 570 (A), ITL p95 89.94 (A), yük 18 048 (A) | 11 741 / 89.71 / 18 033 | **BERABERE** — tüm farklar gürültü içinde |

Çekişme senaryosundaki sonuç bir **başarısızlık değil**: "bu senaryoda
mekanizmanın alacağı bir şey yok" bulgusudur. Rakip E-core'ları
doyurduğu için faz anahtarlamanın kullanabileceği atıl kapasite
kalmamıştır.

**Not:** o senaryonun rakibi (always-runnable, compute-bound, E-pinli
`loadgen`) inşası gereği hiç boşluk bırakmaz. "Çekişme altında kazanç
yok" genellemesi bu veriyle kurulamaz; gerçekçi rakiplerle ayrıca
ölçülmelidir.

---

## Başarı Ölçütü — REVİZYON 1 (DEĞİŞTİRİLDİ 2026-07-19, ARTIK GEÇERLİ DEĞİL)

**Tarihsel kayıt. REVİZYON 2 ile düzeltildi; gerekçe yukarıda.**

**Aşağıdaki "REVİZYON 0" bölümü tarihsel kayıt olarak duruyor, silinmedi.**

### Neden revize edildi

Ölçüt donduğunda İŞ 4'ün mekanizması **henüz yoktu**. Ölçüt, S2 v2'nin
manzarasına göre yazılmıştı; o manzaradaki tek alet "rakibi tahliye et"ti,
yani doğası gereği bir **öncelik takasıydı** — LLM'e vermek için rakipten
almak. Ölçüt de tutarlı biçimde takasın diğer ucunu ödüllendirdi: "rakibe
ne kadar iade edebiliyorsun?"

İŞ 4 **takas olmayan** bir mekanizma buldu: prefill'e E-core vermek TTFT'yi
%11.5 iyileştiriyor ve *kimseden bir şey almıyor* — E-core'lar prefill
sırasında zaten LLM'e ayrılmış P-core'ların yanında atıl duruyordu.
Dondurulmuş ölçüt bu tür bir kazancı **ölçemiyor**, çünkü yazıldığı anda
böyle bir şeyin mümkün olduğu bilinmiyordu.

Yani revizyonun gerekçesi "hedefimiz aslında LLM QoS'uydu" **değildir**.
Gerekçe: **deney uzayı değişti, ölçüt eskidi.**

### Meşruiyet testi: yeni ölçüt eskisinden ZOR olmalı

Yeni ölçüt bir **Pareto baskınlığı** iddiasıdır ve statik hiçbir
konfigürasyonun kazanamayacağı bir sınavdır (İŞ 4 bunu gösterdi: P8
decode'da kazanıyor, P8+E8 prefill'de, hiçbiri ikisinde birden).

**Faz-farkındalıklı politika, en iyi statik konfigürasyonun HER İKİSİNİ DE
aynı anda yenmeli:**

| kriter | referans | koşul |
|---|---|---|
| TTFT | C_P8_E8 = **9 725 ms** | ≤ 9 725 × 1.02 = **9 920 ms** |
| ITL p95 | A_P8 = **90.10 ms** | ≤ 90.10 × 1.02 = **91.90 ms** |
| rakip throughput | statik D = **17 954 it/s** | **≥ 17 595 it/s** (%2 altına düşmesin) |

Üçü **birlikte** sağlanmalı. Biri ihlal edilirse politika başarısızdır.

İkincil eksen (raporlanır, kısıt değil): **J/token**, üç kolda da.

## sched_ext'in ölçülecek katkısı (2026-07-19)

`sched_setaffinity` **sert bir kısıttır: maske bölümlemedir, öncelik
değil.** Decode'da LLM'e 6, rakibe 2 çekirdek verirsen, LLM'in ihtiyacı
olduğunda geri alınamaz; LLM tokenler arası beklerken (ITL 95 ms'nin içinde
boşluk var) o çekirdekler atıl kalır.

sched_ext'in ifade edebildiği ve affinity'nin **yapısal olarak
edemeyeceği** şey: *"rakip P-core'da koşabilir, ama bir decode thread'i
uyandığında derhal preempt edilir"* — bölümleme değil öncelik; boş çekirdek
boşa gitmiyor.

S2 v2'deki 33 puanlık toplam-throughput açığının kaynağı **sert
bölümlemenin israfıydı**.

**sched_ext'in ölçülecek iddiası:** aynı LLM QoS'unu **daha az çekirdek
israfıyla** sağlamak (iş-koruyuculuk / work-conservation). Bu iddia, Faz 2
daemon+affinity sonuçları elde edildikten sonra, ona karşı ölçülür.

---

## Başarı Ölçütü — REVİZYON 0 (DONDURULDU 2026-07-19, ARTIK GEÇERLİ DEĞİL)

**Tarihsel kayıt. 2026-07-19'da REVİZYON 1 ile değiştirildi; gerekçe
yukarıda. Silinmedi çünkü dondurma kuralı, ölçütün sonuca göre sessizce
değiştirilmediğinin denetlenebilir olmasını gerektirir.**

Bu bölüm, Faz 2/3'ün sonuçları görülmeden yazılmıştır. **Sonuçlar
görüldükten sonra değiştirilmez.** Değiştirilirse, değişikliğin gerekçesi ve
tarihi buraya yazılır ve eski hali silinmez.

### Neden "eşit ağırlıklı toplam throughput" reddedildi

S2 v2'de her iki tarafı kendi çekişmesiz tavanına normalize edip toplamıştık:
Linux varsayılanı %170.9, statik D %138.0. Bu ölçüt bu proje için **yanlış**:

- **Gecikmeyi throughput'a çeviriyor.** Projenin birincil metriği ITL
  p95/p99 dağılımı; ortalama token/sn'nin yetersiz olduğu CLAUDE.md'de zaten
  yazılı. Toplam throughput aynı hatayı bir katman yukarıda tekrarlıyor.
- **Kullanıcı bekleme süresini saymıyor.** Etkileşimli bir LLM'de 100 ms'lik
  ITL artışı insan tarafından görülür; arka plan derlemesinde %10 yavaşlama
  görülmez. Eşit ağırlık bu farkı siliyor.
- **Enerjiyi saymıyor.** E-core'lar belirgin daha verimli; throughput
  toplamı bunu görmez.

### Birincil ölçüt: Pareto formülasyonu

> **LLM'in servis kalitesini sabit tutarken, rakibe ne kadar throughput
> iade edebiliyorum?**

**Senaryo:** S2 çekişmesi — 16 always-runnable rakip thread (`harness/loadgen`),
en az 6 tur, interleaved, %2 gürültü tabanı geçerli.

**Kısıt (LLM servis kalitesi), statik D'ye karşı:**

| metrik | statik D (ölçülen) | izin verilen tavan (+%2) |
|---|---|---|
| TTFT | 11 531.93 ms | **≤ 11 762.6 ms** |
| ITL p95 | 89.26 ms | **≤ 91.05 ms** |

**Amaç (maksimize edilecek):** rakip throughput'u.

| | statik D | geçmek için gereken |
|---|---|---|
| rakip iş hızı | 17 954 it/s | **> 18 313 it/s** (%2 üstü) |

**Geçme koşulu:** Her iki kısıt da sağlanacak **ve** rakip throughput'u
gürültü tabanının üstünde artacak. Kısıtlardan biri ihlal edilirse politika
başarısızdır — rakip ne kadar kazanırsa kazansın.

### İkincil eksen: enerji

Birincil ölçütü geçen politikalar ayrıca şunlarla raporlanır:

- **LLM J/token** — statik D'ye karşı, kısıt: ≤ D × 1.02
- **Rakip J/iş birimi** — kısıt yok, raporlanır

*Not: S2 v2 koşulduğunda RAPL root-only olduğu için statik D'nin enerji
taban çizgisi yok. Faz 2/3 karşılaştırmasından önce D, enerji kaydıyla
yeniden ölçülmelidir.*

### Çıta: statik D'nin bu ölçütteki yeri

Statik D (LLM P-core'da, rakip E-core'da) **kısıtları tanımı gereği
sağlıyor** ve 17 954 it/s veriyor. Faz 2/3'ün aşması gereken şey budur.
Linux varsayılanı (B) kısıtı **ihlal ediyor** (TTFT 17 717 ms, ITL p95
103.85 ms) — yani bu ölçütte baştan eleniyor, toplam throughput'u yüksek
olsa bile. Ölçütün amacı tam olarak budur.

### Ön kayıt: naif faz-aware politikanın BAŞARISIZ olması bekleniyor

Mevcut veriyle hesaplanan projeksiyon (yeni koşu yok):

- Faz zaman payları: prefill %33.2 (10.97 s), decode %66.8 (22.08 s)
- Decode'da 8→6 çekirdek iadesi: P kapasitesinin %17.1'i serbest kalır,
  rakip 17 954 → ~22 300 it/s (**+%24**)
- **Ama LLM ITL bedeli %7.7** — gürültü tabanının **3.9 katı**
- Eşit ağırlıklı toplamda bile açık kapanmıyor: 138.0 → 140.0 (Linux 170.9)

Yani **"decode fazında çekirdek iade et" politikası bu ölçütü geçemez.**
Tek çekirdek iadesi bile (interpolasyonla ~%3.9) bütçenin iki katı.

Bu ön kayıt bilerek yapılıyor: Faz 2/3'ün naif hali başarısız olursa, bu
sürpriz değil **öngörülmüş** sonuçtur ve ölçüt sonradan gevşetilmez.

**Aranması gereken mekanizma başka yerde:** en umut verici test edilmemiş
yol, prefill fazında LLM'e **ek** kaynak vermek (E-core'ları da prefill'e
katmak). Prefill %77 verimle ölçekleniyor, decode %49 ile; asimetri
"decode'dan al" yönünde değil "prefill'e ver" yönünde kullanılabilir.
Bu ölçülmedi ve Faz 2 öncesi ölçülmelidir.

## Sözlük

- **TTFT** — time to first token; prefill aşamasının gecikmesi.
- **ITL** — inter-token latency; ardışık tokenler arası süre.
- **prefill / decode** — yukarıda tanımlı iki faz.
- **sched_ext** — BPF ile scheduling politikası yazıp çalışma anında yüklemeyi
  sağlayan kernel çerçevesi (mainline'a 6.12'de girdi).
- **DSQ** — dispatch queue; sched_ext'in kuyruk soyutlaması.
- **bandwidth-bound** — performansın bellek bant genişliğiyle sınırlı olması;
  çekirdek eklemek fayda getirmez.
