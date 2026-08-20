# LLM-Aware Scheduling — Final Rapor

**Proje:** Yerel LLM inference'ında, mevcut Linux scheduling varsayımlarının
karşılamadığı şaşırtıcı bir davranış var mı?

**Tarih aralığı:** 2026-07-18 / 20
**Toplam ölçüm:** **750 koşu** (60 sohbet turu dahil), 36 deney
**Donanım:** Intel i7-14650HX (8 P-core + 8 E-core, 24 thread), 32 GB DDR5,
CachyOS kernel 7.1.3-2-cachyos
**Modeller:**
- Qwen3.5-9B-Q4_K_M, 5.68 GB, sha256 `03b74727a860a563…`
  (GGUF: `general.architecture=qwen35`, 32 katman, embd 4096, head 16/kv 4,
  `file_type=15` = Q4_K_M — İŞ 4'te metadata'dan doğrulandı)
- Qwen3.5-4B-Q4_K_M, 2.74 GB, sha256 `00fe7986ff5f6b46…`
  (aynı mimari ve katman sayısı, embd 2560 — genellik ölçümü için)
**llama.cpp:** commit `571d0d5`, CPU-only, GCC 16.1.1, `-march=native` (AVX2)

**BPF yazılmadı, scheduler kodu yazılmadı.** Kapanış oturumunda, kullanıcı
onayıyla, **hazır scx scheduler'ları ölçüldü** (`scx_lavd`, `scx_rustland`);
her yükleme öncesi/sonrası `sched_ext/state` loglandı ve blok sonunda
scheduler durdurulup "disabled"a dönüş doğrulandı.

---

# 0. Yönetici özeti

Proje sorusuna **evet** cevabı bulundu, ama beklenen yerden değil.

**Bulunan davranış:** Prefill ve decode, aynı scheduling kararına **zıt
tepki veren** iki ayrı iş yüküdür. E-core eklemek prefill'i %13
hızlandırırken decode'un kuyruk gecikmesini %9.4 bozar. Statik hiçbir
konfigürasyon ikisini birden alamaz.

**Bulunan çözüm:** Bu ayrım, uygulamaya hiç dokunmadan, yalnızca
`/proc`'tan okunan context-switch hızıyla ve **negatif gecikmeyle** tespit
edilebiliyor (prompt ≥128 token için prefill recall ≥%94.7; ham
örnek-başına doğruluk %99.6 ama o sayı sınıf dengesizliğiyle şişkin —
bkz. bölüm 6/9. Eşik seçiminde kullanılmayan 10 konfigürasyonda
**%100 recall / %99.4 precision**, sınırdan uzak yanlış pozitif yok —
bölüm 11.5). Tespit edilince `sched_setaffinity` ile uygulanan basit
bir maske değişimi, ara konfigürasyonlar dahil **statik Pareto
cephesinin tamamını baskılıyor** — hem rakipsiz hem gerçek rakip altında
(bölüm 11.1, 11.1b). Kazanç TTFT ekseninde (−%11.8 / −%12.5); bedeli
rakibin throughput'unda **%2.4** (p<0.01) — yani takas, iki taraflı
kazanç değil (bölüm 11.2).

**Uygulamaya karşı ölçüldü:** llama-server'a `-C`/`-Cb` maskelerini bağlayan
bir yama yazıldı ve **uygulama-bilgili yerleşim** ile **dışarıdan tespitli
yerleşim** karşılaştırıldı. Altı metriğin beşinde fark **%1'in altında**,
altıncısı (ITL p99) +%2.34 — ama o metriğin kendi tabanı %9.07, yani
**altısı da ns**. Yani *OS bunu uygulamanın yardımı olmadan da
yapabiliyor* artık ölçülmüş bir iddia (bölüm 3.5).

**Kapsam (önemli):** bu kazanç **uzun prefill'li turlarda** gerçekleşir.
Çok turlu sohbette `cache_prompt` ile prefill 11 047 ms'den ~870 ms'ye
düşüyor ve etki sıfırdan ayırt edilemez hâle geliyor (tur 2–5: −%1.2, ns).
5 turluk bir oturumda toplam kullanıcı bekleme süresi **−%8.2** ve bunun
**tamamı ilk turdan** geliyor (bölüm 3.4).

**Bugün kullanılabilecek tek satırlık tavsiye:** LLM ile rakip iş **aynı
çekirdekleri paylaşmak zorundaysa**, rakibi `chrt --idle` ile koştur. Bu,
ITL boşluğunun **%96.8'ini** geri alıyor — daemon yok, yama yok, kernel
değişikliği yok:

```
chrt --idle 0 <arka-plan-isi>
```

Bedeli rakibin throughput'unun ~%55'i; ara nokta isteyen `CPUWeight=1`
kullanabilir (boşluğun %49'u, rakibe maliyeti %13.5).

> **Yukarıdaki sayılar sentetik rakiple (`loadgen`) ölçüldü. Gerçek bir
> iş yüküyle (`make -j16`, döngüde) yeniden ölçüldü (§11.8):**
>
> | | `chrt --idle` | `CPUWeight=1` |
> |---|---|---|
> | LLM ITL p95 | **−%23.5** | +%1.0 (etkisiz) |
> | LLM TTFT | −%10.5 | −%0.4 (etkisiz) |
> | rakibe maliyeti | −%15.2 | −%0.5 |
>
> **`chrt --idle` tavsiyesi genelleniyor** ve gerçek işte bedeli sentetik
> rakiptekinden çok daha ucuz (%15.2 vs ~%55). **`CPUWeight=1` ise
> genellenmİYOR:** sentetik yükte boşluğun %49'unu alıyordu, gerçek
> build'de hiçbir şey yapmıyor (tüm metriklerde ≤%1, gürültü içinde).
> Ara nokta arayanlar için o öneri geri çekilmiştir.

**Bulunmayan şey:** sched_ext'e ölçülmüş bir gerekçe. Dört senaryonun
dördünde de kazandıran mekanizma standart Linux'ta mevcut — ve kapanış
oturumunda **hazır scx scheduler'ları da ölçüldü**: ne `scx_lavd` ne
`scx_rustland` en iyi kullanıcı-alanı çözümünü yenebildi.

**Genellik:** asimetri ikinci bir model boyutunda (4B) da var — hatta
ölçeklenme verimi farkı hafifçe *genişliyor* (9B'de 77/49, 4B'de 75/45) —
ama onu **sömürmenin getirisi model büyüdükçe artıyor**: E-core takası
9B'de TTFT −%11.5 / ITL p95 +%9.4 iken 4B'de −%7.4 / +%19.3'e dönüşüyor.
Verim farkı ile sömürülebilir kazanç iki ayrı şeydir (bölüm 2.6).

**Yol boyunca çürütülen hipotez sayısı: 23** (çoğu benim). Hepsi bölüm 6'da
kayıtlı ve hiçbiri silinmedi.

---

# 1. Metodolojik temel (Faz 0)

## 1.1 Gürültü tabanı: %2

Her iddianın eşiği. Aynı konfigürasyon 20 kez koşuldu:

| metrik | medyan | CV | %95 bandı |
|---|---|---|---|
| TTFT | 12 127.7 ms | 0.5% | ±0.9% |
| ITL p50 | 98.07 ms | 0.5% | ±1.1% |
| ITL p95 | 103.52 ms | 0.7% | ±1.4% |
| decode | 10.17 tok/s | 0.5% | ±1.1% |

CLAUDE.md'de laptop varyansının %10'u aşabileceğinden endişe ediliyordu;
ölçülen %0.5–1.5. Manevra alanı beklenenden genişti.

> **Bu tablo tek bir konfigürasyona aittir ve genelleştirilemez (§11.4).**
> Aynı protokol farklı konfigürasyonlarda tekrarlandığında ITL p95'in CV'si
> %0.7 değil **%5.20** çıkabiliyor. Taban hem metriğe hem senaryoya
> bağlı — ve en gürültülü hâli, rakibin *aralıklı* olduğu durumdur:
>
> | senaryo | ITL p95 CV |
> |---|---|
> | rakipsiz (bu tablo) | %0.7 |
> | aralıklı/zayıf rakip | **%5.20** |
> | sürekli ağır rakip | %1.36 – %1.51 (iki deney) |
>
> Sürekli çekişme p95'i *kararlı* kılıyor; asıl varyans kaynağı sporadik
> girişimdir. Bölüm 11 boyunca her karşılaştırma kendi senaryosunun
> tabanıyla değerlendirildi, %2 ile değil.

## 1.2 Termal olmayan, açıklanamayan drift

TTFT koşu numarasıyla anlamlı korele (r = +0.671, n=20). İlk 10 → son 10:
TTFT +0.74%, ITL p95 +0.84%, decode −0.78% — üçü aynı yönde.

**Sıcaklıkla korelasyon yok** (|r| < 0.25). Sebebi bu veriyle
bilinmiyor ve tahmin edilmedi.

**Metodolojik sonucu — projenin geri kalanını belirledi:** konfigürasyonlar
blok halinde ölçülemez. Faz 1'den itibaren **tüm deneyler interleaved**
koşuldu (her tur tüm kollar bir kez, karıştırılmış sırayla).

## 1.3 Harness tasarımı

Sıfır bağımlılık (yalnızca Python stdlib). `perf` kurulmadı: migration ve
context-switch sayıları `/proc/<pid>/task/<tid>/sched`'den okunuyor — root
istemiyor, tracing overhead'i yok, ve **thread başına** sayı veriyor.

Üç tuzak yaşandı ve çözüldü:
- llama-server prompt prefix'ini cache'liyor → her koşuda yeni sunucu +
  `cache_prompt=false`; yoksa 2. koşudan itibaren TTFT çöker
- Prompt `ubatch`'i aşarsa prefill bölünür → 496 token, tek ubatch
- P-core frekans ortalaması boştaki çekirdeklerle seyreliyor → aktif
  çekirdek ortalaması ayrı raporlanıyor

Doğrulama: harness'ın TTFT'si sunucunun kendi `prompt eval time`
değeriyle **26.7 ms** içinde uyuşuyor. Kapanış oturumunda llama.cpp'nin
içinden de doğrulandı: içsel faz sınırı ile istemcinin ilk token'ı görmesi
**0.30 ms** arayla (bölüm 2.5).

---

# 2. Karakterizasyon (Faz 1)

## 2.1 Yerleşim Linux'un varsayılanını yeniyor

50 koşu, 5 varyant, interleaved. Pinsiz baseline'a karşı:

| varyant | TTFT | ITL p50 | ITL p95 | decode |
|---|---|---|---|---|
| **P-core (16 mantıksal)** | **−%9.2** | **−%12.7** | **−%16.0** | **+%14.4** |
| 4 fiziksel P + SMT | +%47.7 | +%8.2 | +%3.8 | −%7.4 |
| sadece E-core | +%106.8 | +%126.7 | +%118.1 | **−%55.7** |

Hepsi p<0.01 ve eşiğin 2–63 katı. Linux 8 thread'i 16 fiziksel çekirdeğe
(P **ve** E) yayıyor; sadece P-core'da tutmak %14 throughput getiriyor.

## 2.2 Migration sayısı yanlış metrik — dört bağımsız doğrulama

Projenin en sağlam metodolojik bulgusu.

**Kesin test:** aynı 4 fiziksel çekirdek üzerinde migration 626 → 1 029 926
(**1644 kat**) çıkarıldı:

| metrik | 626 mig | 1.03M mig | fark |
|---|---|---|---|
| TTFT | 17 974 | 17 668 | −%1.7 |
| ITL p95 | 117.31 | 107.55 | −%8.3 |
| decode | 9.05 | 9.38 | +%3.7 |

Migration 1644 kat arttı, **her metrik iyileşti**. Belirleyici değişken
fiziksel çekirdek sayısı: 4 → 8 çekirdek TTFT'yi %38.1 iyileştiriyor.

Dördüncü ve en düşmanca doğrulama Faz 2'de geldi: faz geçişinde
**kasıtlı olarak** 2 338 migration üretildi (kontrolün 100 katı), koşunun
en gecikmeye duyarlı anında — ilk token ile kuyruk ortalaması arasındaki
fark %0.6'da kaldı.

**H3'ün naif hali reddedildi.**

## 2.3 Prefill/decode asimetrisi — projenin merkezi bulgusu

Thread başına bir fiziksel P-core, 2→8 çekirdek:

| faz | hızlanma | verim |
|---|---|---|
| prefill | 3.06× | **%77** |
| decode | 1.95× | **%49** |

Marjinal getiriler:

| geçiş | prefill | decode |
|---|---|---|
| t2 → t4 | +%86.6 | +%51.5 |
| t4 → t6 | +%35.9 | +%18.6 |
| t6 → t8 | +%20.8 | **+%8.4** |
| t8 → t16 (SMT) | +%1.0 | −%1.9 |

## 2.4 Asimetrinin mekanizması — iki tarafı da açıklandı

**Decode neden kötü ölçekleniyor: ağırlıklı olarak akış (bandwidth).**
Model indirmeden ayrıştırıldı — aynı 8 çekirdek üzerinde tek örnek
(8 thread) vs iki bağımsız örnek (4'er thread):

| hipotez | tahmin | ölçülen |
|---|---|---|
| saf senkronizasyon duvarı | 2 × 9.02 = 18.04 (+%56) | |
| saf bant genişliği duvarı | 11.54 (+%0) | |
| **gerçek** | | **12.39 (+%7.4)** |

Bariyeri ikiye bölmek, senkronizasyon hipotezinin öngördüğünün ~%13'ünü
getirdi. Yan bulgu: iki küçük bariyer bir büyükten token başına %4.5 daha
az enerji harcıyor.

> **DÜZELTME (kapanış oturumu, bölüm 2.6):** Bu deneyden çıkarılan
> "~%87 bandwidth, ~%13 senkronizasyon" ifadesi **fazla iddialıydı**.
> İkinci bir model ölçülünce akış-dışı bileşenin toplamı %28 çıktı
> (bandwidth payı %72). Bu deney bariyeri *bölmenin marjinal getirisini*
> ölçüyor (%7.4), toplam sabit maliyeti değil.
>
> **DÜZELTMENİN DÜZELTMESİ (§11.7):** yukarıdaki %28/%72 bölünmesi, artık
> geçersiz olan iki noktalı fit'ten geliyordu. Fit'in BW'si ölçülen
> tavanla değiştirilirse aynı model 9B için akış-dışı payı **%0–7.2**
> verir (BW 66.1–71.25 aralığında). Yani **düzeltme aşırı düzeltmeydi:
> Faz 1'in "~%87 bandwidth" ifadesi, onu düzelten "%72"den fiziksel
> gerçeğe daha yakınmış.** 9B decode'u ≥%93 akış-baskın.
>
> Model bağımlılığı da buradan çıkıyor: aynı hesap 4B için akış-dışı
> payı **%23–29** verir. Akış-dışı maliyet 9B'de ihmal edilebilir,
> 4B'de değil. *(Hepsi fit'in kendi seri varsayımı — token süresi =
> akış + sabit — ve "model dosyası kadar bayt okunuyor" kabulü altında.)*

**Prefill neden iyi ölçekleniyor: donanım tavanına yakın.**

```
prefill iş yükü = 2 × 9e9 × 496 = 8.93 TFLOP
ölçülen         = 811 GFLOPS
AVX2 fp32 tavanı = 8 × 4.4 GHz × 32 flop/cy = 1126 GFLOPS
→ tavanın %72'si
```

BLAS karıştırıcısı da reddedildi: `GGML_LLAMAFILE` açık/kapalı fark
etmiyor (45.0 vs 45.2 tok/s); kurulu netlib referans BLAS prefill'i
**40 kat kötüleştiriyor**.

> **DÜZELTME:** Faz 1'de "ima edilen bellek trafiği ~66 GB/s, DDR5 tavanına
> yakın" diye raporlanmıştı. O hesap token başına sabit maliyeti
> yanlışlıkla bant genişliğine yıkıyordu. İki modelli ayrıştırma sabit
> maliyeti ayırıyor (bölüm 2.6) ve tavanın 8 çekirdekte dolduğunu
> gösteriyor.
>
> **DÜZELTMENİN DÜZELTMESİ (§11.7):** bu ayrıştırmanın verdiği **91 GB/s
> sayısı geçersizdir** — hem teorik tavanı (83.2 GB/s, ölçülen DDR5-5200
> çift kanal) hem bağımsız ölçülen maksimumu (77.65 GB/s) aşıyor. Sayı
> kaldırıldı. Tavanın 8 çekirdekte dolduğu bulgusu ise **bağımsız
> ölçümle doğrulandı**: decode 65.5 GB/s istiyor, 8 P-core'un ölçülen
> okuma tavanı 71.25 GB/s — **%92 doluluk**.

## 2.5 H5 — faz tespiti uygulamadan yardım almadan

**Dedektör (düz mantık, ML yok):**

```
ctx_switch_rate (CPU-saniye başına) > eşik, k ardışık örnek  =>  DECODE
```

Sinyal `/proc/<pid>/task/<tid>/sched`'den. **Uygulamaya hiç dokunulmuyor.**

Neden çalışıyor: llama.cpp thread'lerini her katmanda senkronize ediyor.
Decode her **token** için tam forward pass yapıyor; prefill tüm prompt için
**tek** pass. Ayrışma **5.4 kat**.

| ölçüm | değer |
|---|---|
| ham örnek-başına doğruluk | %99.60 (min %99.48) — *sınıf dengesizliğiyle şişkin* |
| **prefill recall** (dürüst metrik) | **≥%94.7** (prompt ≥128 token); 32 token'da %82.7 |
| tespit gecikmesi | **−133 ms** (sınırdan ÖNCE) |
| kaçırma | 0 / 10 |
| daemon maliyeti (100 ms periyot) | tek çekirdeğin **%1.7'si** |

**Zor koşullarda:**
- **Çekişme bozmuyor, iyileştiriyor** (ayrışma 4.6–6.1× → 5.5–9.1×);
  sinyal yalnızca LLM process'inden toplandığı için rakibin ctx trafiği
  paydaya girmiyor
- **Kısa prompt gerçek sınır:** 32 token'da prefill recall %82.7'ye
  düşüyor (sabit 135 ms erken uyarı, 880 ms'lik prefill'in %15'i).
  Pratik eşik: **prompt ≥ 128 token**
- 4/6/8 çekirdek tahsisinde tek eşikle çalışıyor

**Çekince ÖLÇÜLDÜ (kapanış oturumu).** Sinyalin OpenMP bariyerlerinin
futex'e düşmesinden geldiği bir tahmin değil, artık bir ölçüm: llama.cpp
`-DGGML_OPENMP=OFF` ile yeniden derlendi (ggml kendi **spin-wait**
threadpool'unu kullanır — aynı kod, farklı bariyer mekanizması) ve 6+6
koşu interleaved ölçüldü.

| | OpenMP | spin-wait |
|---|---|---|
| ctx switch / koşu | 2 032 021 | **820** |
| faz ayrışması | 10.2× | **−1.6×** (yok) |
| dedektör tetiklendi | **6/6** | **0/6** |
| tespit gecikmesi | −139.4 ms | — |

**Sinyal 2 500 kat düşüyor ve dedektör hiç tetiklenmiyor.** Alternatif
kanallar da kurtarmıyor: aktif çekirdek oranı 0.94× vs 0.95×,
`procs_running` 1.00× — hiçbirinde faz ayrımı yok.

*(Spin derlemede raporlanan %100 prefill recall aldatıcıdır: dedektör her
şeye "prefill" dediği için trivial olarak %100.)*

Spin-wait'in kendi maliyeti de ölçüldü: TTFT −%2.2 (hafif iyi), ama
**ITL p50 +%2.8, ITL p95 +%16.2, decode −%4.3** (hepsi p<0.01) — yani
spin-wait gecikme dağılımını belirgin bozuyor.

**Sonuç:** iddia **llama.cpp sınıfı, bariyer-senkronize ve bariyerde
bloke olan (futex) CPU runtime'ları** ile sınırlıdır. Bu artık varsayım
değil, ölçülmüş kapsamdır.

**Erken uyarının mekanizması bilinmiyor** — ama artefakt olmadığı
kanıtlandı. Elenenler: prompt uzunluğu (25.8 kat değişimde sabit),
ubatch/bariyer sıklığı (4 kat değişimde 1.06×), P-core frekansı (ters
yönde), **ve yer-gerçeğinin konumu** (İŞ 2: içsel faz sınırı
`graph_compute(batched=0)` ile ilk token yalnızca **0.30 ms** arayla;
dedektör ikisinden de **−115.6 ms** önce). Uydurulmadı. *(Bölüm 8'de "kalan en
güçlü hipotez" diye kaydedilen açıklama — prefill kuyruğunun zaten
decode-şekilli olduğu — sonradan §11.6'da ölçümle çürütüldü; mekanizma
hâlâ açık.)*

*Not: buradaki −133 ms istemci varışına karşı, İŞ 2'deki −115.6 ms içsel
sınıra karşı ve farklı konfigürasyonda (n_predict 128, teşhis derlemesi)
ölçüldü. İkisi aynı olguyu farklı referansla veriyor.*
## 2.6 Genellik: ikinci model (4B) ve decode'un gerçek darboğazı

Tüm bulgular tek model üstündeydi. Aynı ailenin 4B varyantı ölçüldü —
**aynı mimari (`qwen35`), aynı katman sayısı (32)**, yalnızca genişlik
farklı, yani "boyut mu mimari mi" karıştırıcısı yok.

### Asimetri korunuyor, hafifçe genişliyor

| | 9B | 4B |
|---|---|---|
| prefill verimi (t2→t8) | %77 | %75 |
| **decode verimi (t2→t8)** | **%49** | **%45** |
| t6→t8 marjinal decode | +%8.4 | **+%3.3** |

Beklenti "küçük model cache'e daha çok sığar, decode daha iyi ölçeklenir"
idi. **Gerçekleşmedi.**

### Neden: akış-dışı bir maliyet var, ve payı model boyutuna bağlı

*(Bu alt bölümün başlığı önce "darboğaz bant genişliği değil, sabit token
maliyeti"ydi. §11.7 o çerçeveyi tersine çevirdi: 9B'de darboğaz büyük
ölçüde **bant genişliğidir** (≥%93); akış-dışı maliyet asıl olarak
**küçük** modelde belirleyici. Başlık düzeltildi, gerekçe aşağıda.)*

Ham "ima edilen bant genişliği" iki modelde tutarsız (9B 65.9, 4B 50.8
GB/s) ve 4B yalnızca 1.60 kat hızlı, oysa boyut oranı 2.07. İki model iki
bilinmeyen verir:

> **Sonradan gelen okuma (§11.7):** bu "tutarsızlık" aslında bulgunun
> kendisiymiş. Bağımsız ölçülen tavana (71.25 GB/s) oranlanınca:
> **9B naif olarak tavanın %93'ünde, 4B yalnızca %71'inde.** Yani 9B
> bellek doymuş durumda, 4B değil. Fit'in çözmeye çalıştığı tutarsızlığın
> sebebi "paylaşılan bir BW + paylaşılan bir sabit" olamayacağıydı —
> ama çözüm sabiti paylaştırmak değil, **akış-dışı payın modele göre
> değişmesiydi**. Aşağıdaki fit bunu ters yönden yaptı ve BW'yi fiziksel
> tavanın üstüne itti.

```
token_süresi = model_GB / BW + sabit
```

| çekirdek | BW (GB/s) | sabit (ms) ⚠ | sabitin 9B payı ⚠ | 4B payı ⚠ |
|---|---|---|---|---|
| t2 | 41.7 | 31.6 | %19 | %32 |
| t4 | 62.9 | 20.5 | %18 | %32 |
| **t8** | **91.0** ⚠ | **23.8** | **%28** | **%44** |
| t16 | 90.5 ⚠ | 25.2 | %29 | %45 |

> ⚠ **Bu iki BW değeri fiziksel olarak imkânsızdır (§11.7).** Teorik
> tavan 83.2 GB/s, bağımsız ölçülen maksimum 77.65 GB/s.
>
> **Ve sabit maliyet ile pay sütunlarının hepsi bu itirazdan
> etkileniyor** (tabloda ⚠ ile işaretli). İlk yazdığım
> "sabit maliyet ayrı bir kaynaktan geliyor" notu yanlıştı: fit iki
> bilinmeyeni **birlikte** çözüyor, ikisi tek bir denklem çiftinin
> çıktısı. BW imkânsız çıkıyorsa aynı fit'in sabiti de güvenilmezdir.
>
> Ölçülen tavan zorlandığında ne olduğu (t8, 9B 85.88 ms / 4B 53.94 ms):
>
> | BW | 9B sabit | 4B sabit | fark |
> |---|---|---|---|
> | 66.1 (9B için alt sınır) | −0.05 ms | 12.48 ms | +12.53 |
> | 71.25 (ölçülen tavan) | 6.16 ms | 15.48 ms | +9.32 |
>
> Fiziksel olarak mümkün BW aralığı **[66.1, 71.25]** ve bu aralığın
> **her** noktasında 4B'nin sabiti 9B'ninkinden büyük. Yani "sabit maliyet
> model boyutundan bağımsızdır" varsayımı, BW'yi 92 GB/s'ye iten şeyin
> kendisidir. İki noktalı model, ölçülen bellek tavanıyla **bağdaşmıyor**.

**İki düzeltme:**

1. **Akış bant genişliği fit'ten okunamıyor.** ~~91 GB/s~~ — sayı
   geçersiz (§11.7). Bağımsız ölçüm: 8 P-core'da saf okuma **71.25 GB/s**,
   ve decode bunun **%92'sini** kullanıyor (65.5 GB/s ihtiyaç). Tavanın
   8 çekirdekte dolduğu sonucu ayakta, ama artık fit'e değil doğrudan
   ölçüme dayanıyor.
2. **Token başına akış-dışı bir maliyet var** — paralelleşmiyor ve
   ölçeklenmeyi sınırlıyor. Ama ~~"24 ms, model-boyutundan bağımsız"~~
   nicelemesi geçersiz (yukarıdaki ⚠). Ölçülen tavanla tutarlı okuma:
   9B'de ~0–6 ms, 4B'de ~12–15 ms — yani **küçük modelde belirgin daha
   büyük**, bağımsız değil. Bu, 4B'nin neden daha kötü ölçeklendiğini
   yine açıklıyor, hatta daha güçlü biçimde.

*(Bu ayrıştırma iki noktalı bir uydurmadır ve bağımsızlık varsayımı
ölçülen bellek tavanıyla **çelişerek** düştü — yukarıdaki ⚠ ve §11.7.
Akış-dışı maliyetin gerçek büyüklüğünü ve model bağımlılığını bağımsız
olarak belirlemek üçüncü bir model ya da doğrudan DRAM trafiği ölçümü
ister; ikisi de yapılmadı.)*

### E-core takası küçük modelde kötüleşiyor

| | 9B | 4B |
|---|---|---|
| prefill kazancı (C_P8_E8 vs A_P8) | **+%13.0** | +%8.0 |
| TTFT kazancı | −%11.5 | −%7.4 |
| **ITL p95 kaybı** | **+%9.4** | **+%19.3** |

Asimetrinin **yönü** korunuyor, **büyüklüğü ters yönde** değişiyor: küçük
modelde kazanç azalıyor, hasar iki katına çıkıyor. Akış-dışı maliyet
bulgusuyla tutarlı: 4B'de decode süresinin daha büyük bir kısmı akış
dışıdır ve bariyere yavaş E-core eklemek doğrudan o kısmı büyütüyor.
*(Buradaki "%44" gibi kesin paylar fit'ten geliyordu ve fit düştü —
§11.7; yönün kendisi ölçüm, pay değil.)*

### Karakterizasyon iddiasının model boyutu ekseni

> Prefill/decode asimetrisi model boyutundan bağımsız olarak **vardır**,
> ama onu sömürmenin getirisi **model boyutuyla artar**. Faz-farkındalıklı
> politika büyük modellerde daha değerlidir; 4B ölçeğinde "prefill'e
> E-core ver" takası ITL kısıtı altında savunulamaz hale gelebilir.

*İkinci bir daraltma bölüm 3.4'te geliyor: kazanç yalnızca **uzun
prefill'li turlarda** gerçekleşiyor. İddianın nihai hâli için bölüm 5.*


---

# 3. Politika (Faz 2)

## 3.1 Uygulanabilirlik: llama.cpp faz ayrımını zaten yapıyor

| yetenek | durum |
|---|---|
| İki ayrı threadpool (`batched ? threadpool_batch : threadpool`) | mimaride **var** |
| Thread sayısı per-faz (`-t` / `-tb`) | server'da **çalışıyor** (`-tb 16` prefill'e +%13.3) |
| CPU affinity per-faz (`-C` / `-Cb`) | **server'a bağlanmamış** — `llama_attach_threadpool` yalnızca `tools/completion` ve `llama-bench`'te |

Thread sayısı tek başına yetmiyor: `-t 8 -tb 16` prefill kazancını alıyor
ama decode'un 8 thread'i E-core'a düşüp ITL p95'i **+%20.8** bozuyor.
**Affinity ayrımı şart.**

## 3.2 Faz anahtarlayıcı ve sonuçları

Canlı dedektör + `sched_setaffinity`: prefill'de P+E, decode'da yalnız P.
Anahtarlama 16 thread için **202 µs** (yavaş yol işlemi, faz başına bir kez).

**Mekanizma doğrudan ölçüldü** — E-core doluluk oranı:

| faz | A_P8 (statik) | SWITCH |
|---|---|---|
| prefill | %5.6 | **%90.5** |
| decode | %0.0 | **%0.0** |

**Rakipsiz (18 koşu):**

| kol | TTFT | ITL p95 | J/token |
|---|---|---|---|
| A_P8 | 10 998 | 89.94 | 10.986 |
| C_P8_E8 | 9 753 | 99.84 | 11.248 |
| **SWITCH** | **9 748** | **86.71** | **10.486** |

> **Oturum notu:** Bu tablo Faz 2 oturumundan. Bölüm 4.0'daki EEVDF sütunu
> aynı konfigürasyonu kapanış oturumunda yeniden ölçüyor ve %0.5–0.7 farklı
> sayılar veriyor (A_P8 11 051, SWITCH 9 815). Fark **gürültü tabanının
> altında** ve bölüm 1.2'deki oturum-içi drift'le tutarlı. Çelişki değil;
> scheduler karşılaştırması için 4.0'daki aynı-oturum sayıları geçerlidir.

C'nin TTFT'sini alıyor (ns), A'nın ITL p95'ini **yeniyor** (−%3.6, p<0.01),
en az enerjiyi harcıyor (−%4.6).

**Gerçekçi rakiple (`make -j16`, pinsiz, 18 koşu):**

| kol | TTFT | ITL p95 | J/token | rakibin build süresi |
|---|---|---|---|---|
| A_P8 | 11 743 | 90.42 | 11.633 | 35.70 s |
| C_P8_E8 | 10 490 | 100.68 | 12.027 | 37.24 s |
| **SWITCH** | **10 480** | **86.54** | **11.157** | **34.37 s** |

*(Aynı oturum notu geçerli: 4.0'da bu konfigürasyon A_P8 11 708 /
SWITCH 10 516 olarak yeniden ölçüldü — fark %0.3, gürültü içinde.)*

> **DÜZELTME (§11.2): bu paragrafın rakip tarafı GEÇERSİZDİR.**
> Buradaki "−%3.7", `build_wall_s` alanından geliyordu ve o alan build'i
> değil **LLM isteğinin süresini** ölçüyordu (`build.wait()` istek
> bittikten sonra çağrılıyordu; 36 koşuda fark +0.10 s medyan). Ayrıca
> rakip yalnızca ~4.3 s koşuyordu, pencere ise ~33 s — yani rakip
> zamanın %87'sinde yoktu.
>
> Gerçek rakiple yeniden ölçüldü (§11.2, §11.1b): **SWITCH rakibi
> yavaşlatıyor** — −%2.21 (p<0.05) ve bağımsız bir deneyde −%2.36
> (p<0.01). Yani rakip tarafında kazanç değil, küçük bir **maliyet** var.
> LLM TTFT kazancı ise duruyor ve büyüyor: −%11.8 … −%12.5.

**LLM tarafında kazanç, rakip tarafında küçük bir maliyet:** LLM TTFT
−%10.8 (bu senaryoda; gerçek rakiple −%11.8 … −%12.5), rakibin
throughput'u −%2.2 … −%2.4 (p<0.01). SWITCH prefill'i erken bitirip
E-core'ları bırakıyor; E-core kullanan statik kolların en az zarar
vereni odur, ama zarar sıfır değil. *"İki taraflı kazanç" iddiası
ölçülemedi ve kaldırıldı — bkz. §11.2 ve §6.*

Başarı ölçütünün (REVİZYON 2) üç kriteri de geçiliyor — **bu senaryoda**.
Ölçüt senaryo-parametrik olduğu için her senaryoda ayrı değerlendirilir;
çok turlu senaryo (bölüm 3.4) ölçüte karşı **değerlendirilmedi**, orada
statik referans zaten tur 2–5'te SWITCH ile ayırt edilemiyor.

## 3.3 Sınır: doyuran rakip

Rakip 16 thread ile E-core'ları **doyurursa** faz anahtarlamanın alacağı
atıl kapasite kalmıyor. Bu bir başarısızlık değil, kapsam tespitidir — ve
neredeyse tanım gereği doğrudur.

> **DÜZELTME (son denetim):** burada önce "SWITCH ile A_P8 berabere
> kalıyor, tüm farklar gürültü içinde" yazıyordu. Bu deneyin kendi
> tabanıyla ve Welch testiyle bakınca **üç metrikten ikisi berabere, biri
> değil**:
>
> | metrik | taban | SWITCH − A_P8 | t | karar |
> |---|---|---|---|---|
> | ITL p95 | %0.69 | −%0.26 | −1.36 | berabere |
> | rakip hızı | %0.26 | −%0.08 | −0.24 | berabere |
> | **TTFT** | **%0.23** | **+%1.48** | **+11.37** | **SWITCH kötü** |
>
> Yani doyuran rakip altında faz anahtarlama nötr değil, **küçük ama
> ölçülebilir biçimde zararlı** (TTFT +%1.48). Mekanizma tutarlı:
> prefill için açılan E-core'lar rakip tarafından doyurulmuş olduğundan,
> SWITCH prefill thread'lerini çekişmeli çekirdeklere yayıyor; A_P8 ise
> onları çekişmesiz P-core'da tutuyor.
>
> Bu, kapsam tespitini **güçlendiriyor**: "kazanç yok" değil, "atıl
> kapasite yoksa açmaya çalışmak zarar veriyor". Politikanın bu senaryoyu
> tanıyıp anahtarlamaması gerekir — ölçülmedi, mekanizmada da yok.

## 3.4 Çok turlu (etkileşimli) kullanım — kazanç ilk turda yoğunlaşıyor

Politika "etkileşimli yerel LLM" için tasarlanmıştı ama **hiç etkileşimli
senaryoda ölçülmemişti**: her önceki ölçüm tek bir prefill→decode geçişi
içeriyordu. Ayrıca dedektörün **geri dönüş yönü (decode→prefill) hiç
ölçülmemişti**; histerezis bandı yalnızca ileri yön verisinden seçilmişti.

12 koşu × 5 sohbet turu = **60 tur**, `cache_prompt=true`, çift yönlü
politika (→decode P8'e daralt, →prefill P8+E8'e genişlet).

| tur | A_P8 TTFT | SWITCH | fark |
|---|---|---|---|
| **1** | 11 047 | **9 802** | **−%11.3** (p<0.01) |
| 2 | 858 | 846 | −%1.5 |
| 3 | 865 | 851 | −%1.6 |
| 4 | 870 | 877 | +%0.7 |
| 5 | 876 | 881 | +%0.6 |

**Tur 2–5 toplu: TTFT −%1.2 (ns), ITL p95 −%0.5 (ns).**

Sebep açık: `cache_prompt` ile 2. turdan itibaren prefill yalnızca yeni
tokenları işliyor ve **11 047 → ~870 ms**'ye düşüyor. E-core eklemenin
hızlandıracağı iş kalmıyor.

**Oturum düzeyinde:** 5 turun toplam TTFT'si 14 513 → 13 327 ms
(**−%8.2**). 1 186 ms'lik kazancın **tamamı tur 1'den**; tur 2–5
birlikte ~59 ms geri veriyor.

J/token 9.957 → 9.707 (−%2.5) ölçüldü, ama **bu bir iddia değildir**:
bu deneydeki SWITCH kolunun kendi J/token CV'si %2.98, yani etki kendi
gürültüsünün altında (§11.3). Raporlanıyor, iddia edilmiyor.

### Geri dönüş yönü: güvenli, ama sıfır hatalı değil

Öngörülen risk: ileri yönde avantaj olan erken tetikleme (bu deneyde
ölçülen ileri geçiş medyanı **−112 ms** / **−127 ms**), geri dönüşte
**decode hâlâ sürerken E-core açmak** demek olabilirdi.

Geri dönüş medyanı **+35 ms** — decode bittikten *sonra*, yani güvenli
yönde geç. Histerezisin `lo` eşiği (2100) decode sinyalinin (~5800) çok
altında olduğu için beklenen davranış.

**Ama SWITCH'in 30 turunda 3 anomali (%10):**

| anomali | sayı | etkisi |
|---|---|---|
| ileri geçiş ~−760 ms (prefill'in en başında) | 2 | o turda prefill E-core'suz koştu |
| **decode sürerken geri dönüş** | **1** | öngörülen arıza modu — gerçekleşti |

Öngörülen arıza modu **nadir ama sıfır değil** (%3.3). Tek turlu rejimde
dedektör pratikte kusursuzdu; çok turlu cache'li rejimde anomali oranı
%10. Bu, bilinen kısa-prompt zayıflığının etkileşimli karşılığıdır:
~870 ms'lik prefill, ~120 ms'lik erken uyarı payı için zaten dar.

**Sonuç:** iddia çürümedi ama **kapsamı daraldı** — "etkileşimli LLM için"
değil, "**uzun prefill'li turlar için**".

## 3.5 Uygulama-bilgili yerleşime karşı: eşit

Şimdiye kadar gösterilen şey dışarıdan tespitin **işe yaradığıydı**;
uygulamanın kendi faz bilgisiyle yapabileceğinin **aynısı** olup olmadığı
değil. Bu karşılaştırma için `llama_attach_threadpool()`'u server'a bağlayan
bir yama yazıldı (`patches/`, +54 satır) — `-C`/`-Cb` bayrakları
`common/arg.cpp`'de zaten ayrıştırılıyordu ama server'da sessizce yok
sayılıyordu.

| kol | faz bilgisi |
|---|---|
| **A_APP** | yamalı server, `-C 5555 -Cb FF5555 --cpu-strict 1` — uygulama fazı **zaten biliyor**, tahmin yok |
| **B_DAEMON** | yamasız server + daemon — `/proc`'tan tespit, ~122 ms erken tetikleme |

Örnekleyici her iki kolda da çalıştı; aksi hâlde A örnekleme maliyetinden
muaf olurdu. 6 tur × 2 kol = 12 koşu, interleaved.

| kol | TTFT | ITL p50 | ITL p95 | ITL p99 | decode | J/token |
|---|---|---|---|---|---|---|
| A_APP | 9 855 | 87.66 | 90.48 | 93.13 | 11.36 | 10.669 |
| B_DAEMON | 9 860 | 87.25 | 91.35 | 95.31 | 11.29 | 10.710 |

Fark: TTFT +%0.05, ITL p50 −%0.47, ITL p95 +%0.96, decode −%0.58,
J/token +%0.37 — **hepsi ns ve %1'in altında**. Altıncısı ITL p99
+%2.34.

*(Bu p99 farkı ilk yazımda "eşiğin hemen üstünde" diye nitelenmişti —
düz %2 eşiğine göre. Bu deneyin kendi p99 tabanı ölçüldüğünde
**%9.07** çıkıyor (kol-içi CV medyanı, n=6) ve Welch t=−0.27 veriyor.
Yani +%2.34 eşiğin "hemen üstünde" değil, gürültünün **derinlerinde**.
Altı metriğin altısı da ns.)*

**Yorum:** faz bilgisinin kaynağı ölçülebilir bir fark yaratmıyor. Tespit
yeterince doğru ve yeterince erken olduğu için "tahmin" olması pratikte
maliyet üretmiyor.

**Yama kabul edilirse ne olur:** llama-server kullanıcıları aynı sonuca
daemon'sız ulaşır ve daemon büyük ölçüde gereksizleşir. Bu kötü değil —
o zaman katkının adı "bu problemi çözmenin tek yolu" değil,
**"uygulamayı hiç değiştirmeden de çözülebileceğinin kanıtı"** olur, ve
bu ölçüm tam olarak o kanıttır. Daemon'ın kalan dar avantajı: kaynağı
değiştirilemeyen ya da yeniden derlenemeyen kurulumlar.

---

# 4. sched_ext kararı

## 4.0 Önce mantıksal açık kapatıldı: scx scheduler'ları ölçüldü

Bu raporun önceki hâlinde "sched_ext'in katkısı yok" deniyordu ama **hiç
sched_ext scheduler'ı ölçülmemişti**. Ölçülen şey sched_ext'in *öncelik
ifadesinin* gereksizliğiydi; scheduler'ın kendisinin bir şey katıp
katmadığı değil. Bu haklı bir eleştiriydi ve kapanış oturumunda kullanıcı
onayıyla kapatıldı: **3 scheduler × 2 yerleşim × 2 senaryo × 6 tur =
72 koşu**, üçü de aynı oturumda.

**TTFT (ms) / ITL p95 (ms):**

| kol | EEVDF | rustland | lavd |
|---|---|---|---|
| A_P8 / rakipsiz | 11 051 / 90.07 | 10 970 / 91.19 | 10 857 / 91.81 |
| A_P8 / build | 11 708 / 90.58 | 11 519 / 90.38 | 11 509 / 91.88 |
| **SWITCH / rakipsiz** | **9 815 / 87.19** | 10 133 / 87.93 | 10 352 / 91.75 |
| **SWITCH / build** | **10 516 / 87.42** | 10 769 / 88.41 | 10 834 / 91.88 |

**Üç sorunun cevabı:**

1. **scx, EEVDF+A_P8'i yeniyor mu?** Anlamlı biçimde hayır. TTFT'de
   marjinal (lavd −%1.8, rustland −%0.7); ITL p95'te EEVDF daha iyi.

   *(Bu ilk yazıldığında düz %2 eşiğine dayandırılmıştı. §11.4'ten sonra
   deneyin kendi tabanı hesaplandı: **TTFT için kol-içi CV medyanı %3.12**
   — bu deney diğerlerinden belirgin gürültülü. Welch testi de aynı
   sonucu veriyor: lavd t=−1.25, rustland t=−1.12, ikisi de **ns**.
   Yani sonuç ilk gerekçesinden daha sağlam çıktı, daha zayıf değil.)*
2. **EEVDF+SWITCH'i yeniyor mu?** **Hayır, hiçbiri.** EEVDF+SWITCH dört
   ölçümün dördünde de en iyisi.
3. **SWITCH'in kazancı scheduler-bağımsız mı?** TTFT'de **evet, ama
   zayıflayarak**: EEVDF −%11.2 → rustland −%7.6 → lavd −%4.7 (hepsi
   p<0.01). ITL p95'te **lavd kazancı tamamen siliyor** (−%0.1) — p95'i
   dört hücrede de ~91.8'e sabitliyor, ama sabitlediği seviye
   EEVDF+A_P8'in 90.1'inden bile kötü.

Üçüncüsü ayrı bir bulgudur ve iki yönü var: mekanizma **scheduler'a özgü
değil** (üç scheduler'da da çalışıyor), ama **kazancın büyüklüğü
scheduler'a bağlı** — scheduler ne kadar çok kendi yerleştirme mantığını
dayatıyorsa faz anahtarlamaya kalan alan o kadar azalıyor.

*Ortam notu: bu makinede `scxctl start --sched lavd` çalışmıyor — loader
`--pinned-slice-us 500` geçiyor ve `scx_lavd` SIGSEGV atıyor (5/5, root
olarak). Elle `sudo scx_lavd --autopilot` ile sorunsuz.*

## 4.1 Dört senaryo — ve üstüne scheduler ekseni

| senaryo | kazandıran mekanizma | sched_ext'in payı |
|---|---|---|
| rakipsiz | faz anahtarlama (affinity) | **0** |
| gerçekçi rakip (`make -j16`) | faz anahtarlama | **0** |*
| doyuran rakip, **ayrık** çekirdek | hiçbiri — atıl kapasite yok; faz anahtarlama TTFT'de %1.48 *zarar* veriyor (§3.3) | **0** |
| doyuran rakip, **paylaşılan** çekirdek | **`chrt --idle`** | **0** (artık %3.2) |

\* *Bu satırdaki "gerçekçi rakip" senaryosunun rakibi sonradan
ölçüldüğünde pencerenin yalnızca ~%13'ünde mevcut çıktı (§11.2). Rakip
pencere boyunca koşacak şekilde düzeltilip yeniden ölçüldüğünde
mekanizma değişmedi (faz anahtarlama hâlâ kazandıran), ama çekişme çok
daha sert: A_P8'de ITL p95 91.6 → 259.5 ms.*

Ve buna **hazır scx scheduler'ları** eklendi (4.0): ikisi de en iyi
kullanıcı-alanı çözümünün altında kaldı.

## 4.2 Öncelik ne zaman işe yarar

**Ayrık çekirdekte hiç:** decode P-core'da, rakip E-core'da. nice+19 ve
CPUWeight=1 boşluğun %1'inden azını geri aldı ve **rakip yalnızca %0.2
kaybetti** — öncelik düşünce rakip zaman kaybetmiyorsa ondan zaten zaman
istenmemiştir.

**Paylaşılan çekirdekte çok:** aynı 8 P-core'da:

| kol | TTFT | ITL p50 | rakip |
|---|---|---|---|
| normal | 25 838 | 383.04 | 22 551 |
| CPUWeight=1 | 17 937 | 218.12 | 19 497 |
| **SCHED_IDLE** | **12 418** | **95.57** | 10 157 |

Boşluk 16 090 ms / 296.95 ms. Geri alınan: CPUWeight=1 %49.1 / %55.5,
**SCHED_IDLE %83.4 / %96.8**.

> **Genellik ölçüldü (§11.8):** bu tablo sentetik `loadgen` ile. Gerçek
> bir `make -j16` rakibiyle tekrarlandığında **SCHED_IDLE genelleniyor**
> (ITL p95 −%23.5, bedeli rakibe −%15.2 — sentetikteki ~%55'ten çok daha
> ucuz), ama **CPUWeight=1 genellenmİYOR**: gerçek build'de tüm
> metriklerde ≤%1, yani hiçbir şey yapmıyor. Sentetik always-runnable bir
> yükte throughput payı ile gecikme önceliği karışabiliyor; bloke olan
> gerçek bir yükte ayrışıyor.

## 4.3 Kalan artık ve neden sched_ext onu alamaz

`SCHED_IDLE` sonrası artık: **ITL p50'de 9.48 ms — boşluğun %3.2'si.**
Yani decode gecikmesi neredeyse tamamen bir **uyanma-preemption**
problemiymiş, ve çözümü Linux'ta hazır.

sched_ext'in vaadi "yalnızca decode uyanınca preempt et, kalan zamanda
rakibi tam hızda koştur" idi. **Mekanizma gereği ulaşılamaz:**
`SCHED_IDLE` zaten iş-koruyucu katı önceliktir ve rakip bu rejimde
çekişmesiz hızının %40'ını — yani LLM'in bariyerlerde bıraktığı
boşlukların tamamını — alıyor. Fazlasını vermek QoS'tan çalmak demektir.

## 4.4 Karar

**sched_ext'e girilmiyor. BPF yazılmıyor.**

Gerekçe artık **iki ayaklı ve ikisi de doğrudan ölçülmüş**:

- sched_ext'in *öncelik ifadesi* gereksiz (İŞ 3, İŞ 7, İŞ 8): paylaşılan
  çekirdekte boşluğun %96.8'ini `chrt --idle` zaten alıyor, kalan %3.2
  indirgenemez
- sched_ext'in *hazır scheduler'ları* da katkı sağlamıyor (4.0): ne lavd
  ne rustland EEVDF+SWITCH'i yenebildi

Bu bir başarısızlık değil, CLAUDE.md'nin "ML en son girer, belki hiç
girmez" ilkesinin sched_ext'e uygulanmış hâlidir. Kernel değişikliği
gerektiren bir çözüm aranmadan önce, gerektirmeyen çözümlerin yetmediği
**ölçülmeliydi** — ölçüldü ve yettiler.

---

# 5. Projenin katkısı

> Yerel LLM inference'ında prefill ve decode, aynı scheduling kararına zıt
> tepki veren iki ayrı iş yüküdür. Bu ayrım **uygulamaya dokunmadan**,
> yalnızca `/proc`'tan okunan context-switch hızıyla ve **negatif
> gecikmeyle** tespit edilebilir (eşik seçiminde kullanılmayan 10
> konfigürasyonda %100 recall / %99.4 precision, prompt ≥128 token); ve
> tespit edilince `sched_setaffinity` ile uygulanan basit bir maske
> değişimi, **uzun prefill'li turlarda** statik Pareto cephesinin
> tamamını — ara konfigürasyonlar dahil, rakipsiz ve gerçek rakip
> altında — baskılar. Kazanç **TTFT ekseninde** (−%11.8 / −%12.5) ve
> J/token'da (−%3.9); bedeli rakibin throughput'unda **%2.4** (p<0.01).
> Takastır, iki taraflı kazanç değil.

**Kapsam (İŞ 11 ile daraltıldı):** kazanç prefill'in uzun olduğu turlarda
gerçekleşir — sohbetin ilk turu, belge/kod yapıştırma, RAG, tek atımlık
uzun-prompt işleri. Kısa mesajlı, `cache_prompt`'lu sohbet turlarında etki
**ölçülemiyor** (−%1.2, ns). 5 turluk bir oturumda toplam bekleme −%8.2 ve
tamamı ilk turdan.

Kernel değişikliği gerektirmiyor, BPF gerektirmiyor, uygulama yaması
gerektirmiyor. Daemon maliyeti tek çekirdeğin %1.7'si.

**CLAUDE.md'nin H5 ayrımına göre:** katkının adı "OS iş yükünü anlıyor" —
parantezle *bariyerde **bloke olan** (futex) CPU inference runtime'ları
için.* Bu parantez artık tahmin değil: spin-wait derlemede sinyalin
tamamen kaybolduğu ölçüldü (bölüm 2.5).

---

# 6. Çürütülen hipotezler (23)

Disiplin gereği hiçbiri silinmedi. Çoğu benimdi.

| # | hipotez | çürüten |
|---|---|---|
| 1 | "1M migration çoğunlukla bedava kardeş-içi sekmedir" | E1 (%85'i çekirdek aşırı) |
| 2 | "Migration patlamasının sebebi SMT" | E2 (sibling'siz kolda da 668k) |
| 3 | "Prefill migration'a decode'dan duyarlı" | E2 (ceza çekirdek sayısından) |
| 4 | H3 naif hali: "migration sayısı gecikmeyi bozar" | E2 + S2 + faz geçişi (4 kez) |
| 5 | "Faz-aware politika statik D'yi yenebilir" (eski ölçütle) | %7.8'i QoS bütçesine değil prefill kazancına kıyaslamıştım |
| 6 | "Normalizasyon çekirdek bağımlılığını giderir" | Kalkmıyor, yarıya iniyor (2.91×→1.52×) |
| 7 | "Mutlak eşik salınıma yol açar" | Salınım hiç oluşmadı; koruyan k=2 |
| 8 | "Negatif gecikme n_batch artefaktı" | Prefill 25.8 kat değişti, gecikme sabit |
| 9 | "H5 doğruluğu %99.6" | Sınıf dengesizliğiyle şişkindi; gerçek prefill recall 32 token'da %82.7 |
| 10 | "Erken uyarının mekanizması bariyer sıklığı" | ubatch 4 kat değişti, gecikme 1.06× |
| 11 | "Toplu affinity değişimi geçiş maliyeti yaratır" | 2 338 migration, gecikmeye %0.6 |
| 12 | "Faz anahtarlamanın kazancı çekişme altında kaybolur" | Gerçekçi rakiple −%11.4 → −%10.8 korundu. *(O rakip sonradan pencerenin %13'ünde mevcut çıktı; pencere boyunca koşan gerçek rakiple yeniden ölçüldü ve kazanç yine korundu: −%11.8 — §11.2.)* |
| 13 | "2 031 ms preemption ile geri alınabilir" | nice/cgroup %1'den az, rakip −%0.2 |
| 14 | "Transient'in sebebi frekans" | A_P8 daha yüksek frekansta ama daha kötü ITL |
| 15 | "Negatif gecikme bir yer-gerçeği artefaktıdır" | **İŞ 2:** içsel sınır (`graph_compute(batched=0)`) ile ilk token 0.30 ms arayla; dedektör ikisinden de 115.6 ms önce. Erken uyarı **gerçek**. |
| 16 | "Küçük modelde decode daha iyi ölçeklenir, asimetri daralır" | **benim tahminim, İŞ 3:** 4B decode verimi %49 → **%45**'e *düştü*. Darboğaz cache değil, model-boyutundan-bağımsız sabit maliyet. |
| 17 | "Decode ~%87 bandwidth-bound" | **benim ifadem, Faz 1:** iki modelli ayrıştırma akış-dışı bileşeni %28 verdi (bandwidth %72). **Ama bu düzeltme sonradan aşırı düzeltme çıktı** (§11.7): o fit ölçülen bellek tavanıyla bağdaşmıyor; tavanla kısıtlanınca 9B için akış-dışı pay %0–7.2, yani bandwidth **≥%93**. Orijinal "%87" ifadesi düzeltmesinden daha yakınmış. Madde tarihsel kayıt olarak duruyor. |
| 18 | "Faz anahtarlama hem LLM'i hem rakibi iyileştiriyor (rakip build −%3.7)" | **benim iddiam, §3.2:** metrik rakibi hiç ölçmüyordu — `build.wait()` yanlış yerde olduğu için `build_wall_s` LLM isteğinin süresini kaydediyordu (36 koşuda fark +0.10 s). Gerçek rakiple rakip **yavaşlıyor**: −%2.21 (p<0.05) ve bağımsız bir deneyde −%2.36 (p<0.01) — kazanç değil, küçük bir maliyet (§11.2, §11.1b). |
| 19 | "Gerçek akış bant genişliği 91 GB/s" | **benim düzeltmem, §2.6:** teorik tavan 83.2, ölçülen maksimum 77.65 GB/s. Fit tavanı aşıyor, yani geçersiz. Aynı hesabın **ikinci** başarısızlığı (ilki 66 GB/s'ti). Doğrusu ölçümle: 8 P-core'da 71.25 GB/s (§11.7). |
| 20 | "Erken uyarı, prefill'in zaten decode-şekilli olan kuyruğudur" (§8 kurtarma hipotezi) | **benim hipotezim:** doğruysa oran sabit kalmalı ve bölge decode gibi ölçeklenmeliydi. Ölçüldü: oran 1.90→1.55 (gruplar örtüşmüyor), bölge **%77** verimle ölçekleniyor, decode'un %63'üyle değil. Erken tetikleme gerçekten erken (§11.6). |
| 23 | "Doyuran rakip altında SWITCH ile A_P8 berabere kalıyor, tüm farklar gürültü içinde" | **benim ifadem, §3.3:** deneyin kendi tabanıyla (TTFT %0.23) ve Welch testiyle bakınca üç metrikten ikisi berabere ama **TTFT'de SWITCH %1.48 kötü** (t=+11.37). Atıl kapasite yokken E-core açmak nötr değil, küçük ama ölçülebilir biçimde zararlı. Kapsam tespitini zayıflatmıyor, güçlendiriyor. |
| 22 | "Token başına ~24 ms sabit, **model boyutundan bağımsız** maliyet var" | **benim ifadem, §2.6:** bu, iki noktalı fit'in *varsayımıydı*, bulgusu değil. Sabiti paylaştırmaya zorlamak BW'yi 92 GB/s'ye — ölçülen tavanın (71.25) %29 üstüne — itiyor. Fiziksel BW aralığında ([66.1, 71.25]) 4B'nin sabiti 9B'ninkinden **her zaman 9–12.5 ms büyük**. Akış-dışı maliyet var ama model boyutundan bağımsız değil (§11.7). |
| 21 | "%2 gürültü tabanı her metriğe ve senaryoya uygulanabilir" | **benim varsayımım, §1.1:** taban hem metriğe hem deneye göre değişiyor. ITL p95: %0.7 (rakipsiz) / **%5.20** (aralıklı rakip) / %1.36–1.51 (sürekli rakip). TTFT: %0.38–1.06 çoğu deneyde ama scx deneyinde **%3.12**. Yani %2 kimi yerde fazla gevşek, kimi yerde fazla sıkı — ve her iki yönde de bu raporda bir sonucu yanlış etiketledi (§11.4, §4.0). |

Ayrıca bir **ölçüm hatası** düzeltildi: Faz 1'de "ima edilen bant genişliği
~66 GB/s" denmişti; aradaki fark, token başına sabit maliyetin yanlışlıkla
bant genişliğine yıkılmasıydı. *(Bu düzeltmenin yerine konan 91 GB/s
sayısı da sonradan geçersiz çıktı — bkz. §11.7 ve aşağıda 19. madde.)*

Ve iki **ölçüt hatası** kayda geçirildi ve düzeltildi:
- REVİZYON 1: QoS referansları rakipsiz, rakip referansı çekişmeli
  koşudan alınmıştı → hiçbir kol geçemiyordu (**benim hatam**)
- `.o` sayısı build rakibinin iş metriği olarak seçilmişti → 340 nesnenin
  tamamı ilk 15 s'de üretiliyor, sayaç pencere kapanmadan doyuyor

---

# 7. Hipotez tahtası — nihai

| hipotez | durum |
|---|---|
| **H4** — hibrit CPU'lar Linux varsayımlarını zorlar | **DOĞRULANDI**: aynı karar iki faza zıt etki; P-pinning +%14.4 |
| **H5** — faz tespiti uygulamadan yardım almadan | **DOĞRULANDI, kapsamı ölçülmüş**: bariyerde bloke olan (futex) runtime'lar, prompt ≥128 token. Spin-wait derlemede sinyal yok (0/6). Erken uyarı içsel sınıra karşı doğrulandı: −115.6 ms, artefakt değil. |
| **K1** — decode bandwidth-bound | **DOĞRULANDI, güçlü biçimde**: decode ortalama 65.5 GB/s trafik üretiyor, 8 P-core'un ölçülen okuma tavanı 71.25 GB/s → **%92 doluluk**; 9B için akış-dışı pay en fazla %7.2 (4B'de %23–29). Bant genişliğinin baskın olduğu bir rejim. Fit'ten okunan **91 GB/s ve "24 ms model-bağımsız sabit" değerlerinin ikisi de geçersiz** (§11.7, §2.6 ⚠) — iki noktalı ayrıştırma ölçülen tavanla bağdaşmıyor. Niteliksel sonuç artık fit'e değil doğrudan ölçüme dayanıyor. |
| **K3** — gürültü tabanı | **CEVAPLANDI, ama tek sayı değil**: taban hem metriğe hem senaryoya bağlı. Merkezi eğilim metriklerinde %2 fazlasıyla güvenli (TTFT %0.38–0.5, ITL p50 %0.31–0.5, J/token %0.56). **ITL p95 — birincil metrik — senaryoya göre %0.7 (rakipsiz) / %5.20 (aralıklı rakip) / %1.51 (sürekli ağır rakip)** arasında değişiyor; en gürültülü hâli sporadik girişimdir. Tek bir tabanı her yere uygulamak, bu raporda bir kez gerçek bir farkı gürültü diye eledi (§11.4). |
| **K2** — scheduler duyarlılığı | **VAR**: statik yerleşim %9–60 etki |
| **H1** — decode E-core'a düşünce gecikme artar | **kısmen**: E-only −%55.7, E-karışımı ITL p95 +%9.4; koşu-içi taşınmadan ayrıştırılmadı |
| **H3** — migration token gecikmesini etkiler | **NAİF HALİ REDDEDİLDİ** (4 kez) |
| **H2** — prefill/decode girişimi | **TEST EDİLMEDİ** |
| **Politikanın etkileşimli geçerliliği** | **KISMEN**: kazanç uzun prefill'li turlarda (tur 1 −%11.3, p<0.01); cache'li kısa turlarda ölçülemiyor (ns). Oturum toplamı −%8.2. Geri dönüş güvenli ama %3.3 anomali. |

---

# 8. Açık kalanlar

| konu | ne gerekiyor |
|---|---|
| ~~H5 genelliği~~ | **ÖLÇÜLDÜ (bölüm 2.5)**: `GGML_OPENMP=OFF` spin-wait derlemesinde sinyal 2 500 kat düşüyor, dedektör 0/6 tetikleniyor. Kapsam artık ölçülmüş: bariyerde **bloke olan** runtime'lar. |
| **Bloke olmayan başka runtime'lar** | vLLM/ollama gibi farklı motorlar denenmedi; spin-wait sonucu bunların da kapsam dışı kalacağını *ima ediyor* ama ölçülmedi |
| **Erken uyarının mekanizması** | prompt, istemci gecikmesi, ubatch, frekans, yer-gerçeğinin konumu **ve "kuyruk decode-şeklindedir" hipotezi** elendi — sonuncusu §11.6'da ölçümle çürütüldü: bölge %77 verimle ölçekleniyor, decode'un %63'üyle değil, ve erken/ITL oranı sabit değil (1.90→1.55). Kalan kısıt: **prompt uzunluğundan bağımsız, sabit büyüklükte, %77 verimle paralelleşen, prefill sonunda yapılan bir iş.** Aday (lm_head projeksiyonu) **ölçülmedi**; katman düzeyinde damga gerekir. |
| **Akış-dışı token maliyetinin kimliği VE büyüklüğü** | ~~"~24 ms/token, model-boyutundan bağımsız"~~ — bu niceleme §11.7'de düştü (fit ölçülen bellek tavanıyla bağdaşmıyor; §6 madde 22). Maliyetin **varlığı** duruyor, **büyüklüğü ve model bağımlılığı** açık: tavanla tutarlı okuma 9B'de ~0–6 ms, 4B'de ~12–15 ms verir. OpenMP bariyerleri en güçlü aday; KV-cache, sampling ve grafik kurulumu da bu terime giriyor. Üçüncü bir model ya da doğrudan DRAM trafiği ölçümü gerekir. |
| Diğer scx scheduler'ları | sistemde 13 tane var; yalnızca lavd ve rustland ölçüldü, varsayılan ayarlarla |
| **Erken yerleşim hipotezi** | anahtarlama anını 0/50/135/300 ms önce kaydırıp transient'i izlemek |
| ~~decode→prefill geri dönüşü~~ | **ÖLÇÜLDÜ (bölüm 3.4)**: geri dönüş +35 ms, güvenli yönde geç; ama 30 turda 1 kez decode sırasında tetiklendi |
| **Çok kısa kullanıcı mesajları** | prefill <150 ms rejimi — erken uyarı payı prefill'den uzun olur; dedektörün bilinen zayıf noktası, test edilmedi |
| **Çok turlu + çekişmeli** | İŞ 11 rakipsiz koşuldu; sohbet + arka plan yükü birlikte ölçülmedi |
| **H2** | eşzamanlı prefill + decode girişimi |
| **S4 (çoklu LLM)** | birbirinden habersiz process'ler — sched_ext'in kalan tek teorik adayı |
| **Ara öncelik noktaları** | CPUWeight=10, nice+5 — takas eğrisi üç noktadan çıkarıldı |
| **Enerji ekseni** | J/token kaydedildi ama optimize edilmedi |
| S3, S5, S6 | tarayıcı, indeksleme, termal senaryolar |
| **Kol başına gürültü tabanı** | §11.4'ün CV'leri tek bir koldan (`SWITCH+build`, 20 koşu) ölçülüp diğerlerine aynı varsayılarak uygulandı; §11.1'in *rakipsiz* kararları hâlâ buna dayanıyor. §11.1b'de düzeltildi (altı kolun her birinin kendi CV'si, n=6, medyan alınarak) ama n=6'lık CV'ler 20 koşuluk bir tabandan gürültülüdür. Tam çözüm: kol başına 20 koşu. |
| **"%92 bellek doluluğu" varsayımı** | §11.7'nin hesabı modelin **tamamının her token'da DRAM'den okunduğunu** varsayar. Sonuç bu varsayımla tutarlı ama onu kanıtlamaz; gerçek DRAM trafiği uncore sayaçları ister ve ölçülmedi. |
| **Fit'in düşük çekirdekteki geçerliliği** | §2.6'nın iki noktalı ayrıştırması t8/t16'da fiziksel tavanı aşıyor, ama t2/t4 değerleri (41.7 / 62.9 GB/s) tavanın altında. Fit'in nerede bozulduğu ve neden çekirdek sayısıyla yukarı kaydığı çözülmedi. |

---

# 9. Dosya haritası

```
CLAUDE.md                 proje tanımı + başarı ölçütü (REVİZYON 0/1/2, hepsi korundu)
RAPOR.md                  Faz 0 + erken Faz 1
RAPOR_FAZ1.md             H5, bandwidth ayrıştırması, BLAS
RAPOR_FAZ1_KAPANIS.md     ölçüt dondurma, zor koşullar, E-core prefill
RAPOR_FAZ2_ESIK.md        faz anahtarlama ölçümü, ubatch
RAPOR_FAZ2_DEVAM.md       gerçekçi rakip, öncelik, SCHED_IDLE
RAPOR_FINAL.md            bu dosya (kapanış oturumunda güncellendi)

harness/                  51 dosya, sıfır bağımlılık
  bench_lib.py            sensörler, sched sayaçları, istatistik
  run_once.py             tek koşu: SSE + token zaman damgaları
  h5_capture.py           telemetri zaman serisi + yer-gerçeği
  h5_detector_v2.py       normalize sinyal + histerezis + salınım testi
  phase_switch.py         canlı dedektör + sched_setaffinity
  loadgen.c               tekrarlanabilir rakip, iş sayaçlı
  i9_scheduler_baseline.py  scx scheduler matrisi (yerleşim × senaryo)
  i10_ground_truth.py     içsel faz sınırı vs istemci yer-gerçeği
  i11_multiturn.py        çok turlu sohbet, çift yönlü anahtarlama
  i14_frontier.py         statik Pareto cephesi, ara kollar (§11.1)
  a14_leadscale.py        erken uyarı × çekirdek/prompt (§11.6)
  a15_detector_eval.py    precision, held-out, eşik duyarlılığı (§11.5)
  a16_build_noise.py      build duvar süresi tabanı + hijyen kaydı (§11.2)
  a17_contended_noise.py  metrik-başına gürültü tabanı (§11.4)
  a19_frontier_analysis.py  Pareto analizi, metrik-başına taban
  a20_real_competitor.py  gerçek rakip: U2 + U8 birlikte (§11.2, §11.8)
  a21_frontier_contended.py  rakipli statik cephe, 6 kol (§11.1b)
  a22_contended_frontier_analysis.py  senaryo-içi taban + Pareto
  membw.c                 bağımsız bellek bant genişliği tabanı (§11.7)
  ... (deney başına ayrı koşucu ve analiz)

results/                  36 deney, 750 koşu
  */FINDINGS.md           her deneyin elle yazılmış yorumu
```

Her `results/*/` altında: ham CSV, token zaman damgaları, otomatik rapor,
elle yazılmış bulgular.

---

# 10. Kapanış

Proje bir scheduler yazma projesi değil, bir iş yükü karakterizasyonu
projesi olarak tanımlanmıştı ve öyle bitti. Aranan "şaşırtıcı gözlem"
bulundu: **prefill ve decode aynı scheduling kararına zıt tepki veriyor**,
ve bu ayrım dışarıdan, ucuza, uygulamaya dokunmadan görülebiliyor.

Scheduler yazılmadı çünkü **yazılmasına gerek olmadığı ölçüldü**.
CLAUDE.md'nin 8. çalışma kuralı bunu baştan meşru kılmıştı:

> **Negatif sonuç da sonuçtur.** Deneyler bir sonucu çıkarmak için değil,
> doğruyu bulmak için tasarlanır.

Buradaki sonuç negatif değil, **kapsamı daralmış ve daha savunulabilir bir
pozitif sonuçtur**: kernel değişikliği gerektirmeyen, uygulama yaması
gerektirmeyen, %1.7 maliyetli bir kullanıcı-alanı politikası, en iyi
statik konfigürasyonu Pareto olarak baskılıyor.

Kapanış oturumu bu sonucu **dört** yerden sınadı (beşincisi için aşağı
bakınız); üçünde ayakta kaldı,
dördüncüsü **kapsamını daralttı**:
**hazır sched_ext scheduler'ları** ölçüldü (hiçbiri yenemedi), manşet
iddianın **yer-gerçeği** llama.cpp'nin içinden doğrulandı (erken uyarı
gerçek), ve **ikinci bir model boyutunda** tekrarlandı (asimetri var, ama
getirisi model boyutuyla artıyor). Dördüncüsü — **çok turlu etkileşimli
kullanım** — iddiayı çürütmedi ama sınırını çizdi: kazanç uzun prefill'li
turlarda yoğunlaşıyor, cache'li kısa sohbet turlarında ölçülemiyor. Bu
yüzden katkının adı "etkileşimli LLM için" değil, "**uzun prefill'li
turlar için**".

Yol boyunca 23 hipotez çürüdü, çoğu benimdi. Projeyi ayakta tutan şey
hangi hipotezin doğru çıktığı değil, her birinin gürültü tabanına karşı
ölçülmüş olması ve yanlış çıkanların silinmemesiydi.

**Beşinci bir sınama sonradan eklendi (bölüm 11):** makale iskeleti hakem
gözüyle taranınca 16 desteklenmeyen iddia çıktı ve ölçüm gerektirenler
kapatıldı.

Sonuç manşet iddiayı **güçlendirdi**: ara konfigürasyonlar da ölçülünce
statik Pareto cephesi hem rakipsiz hem gerçek rakip altında tamamen
baskılandı — ve rakipli senaryoda cephe daha kalabalık olduğu için
(dört noktadan ikisi ara kol) bu, iki uç noktaya karşı kazanmaktan daha
güçlü bir sonuçtur.

Ama beş yan iddia **düştü**, hepsi de "ölçüm yanlıştı" değil *"ölçülen
şey sanılan şey değildi"* sınıfında: rakip throughput metriği rakibi hiç
ölçmüyordu; bant genişliği fit'i fiziksel tavanın üstündeydi ve aynı
fit'in sabit maliyeti de onunla birlikte düştü; %2'lik gürültü tabanı
her metriğe ve senaryoya uygulanamıyordu. Ve bir iddia yön değiştirdi:
faz anahtarlama rakibe fayda sağlamıyor, ona küçük bir maliyet (%2.4)
yüklüyor — takas, iki taraflı kazanç değil.

---

# 11. Hakem itirazlarına karşı ölçümler

Makale iskeleti hakem gözüyle incelendiğinde 16 desteklenmeyen iddia
çıktı. Bu bölüm, bunlardan **ölçüm ve yeniden analiz gerektirenleri**
kapatıyor. İfade daraltmaları bu bölümün konusu değil.

**Bölüm numaraları değişmedi.** §2.6, §3.2, §4.0 ve diğerleri aynı içeriği
gösteriyor; bu bölümde bulunan düzeltmeler ilgili yerlere çapraz atıfla
bağlandı ve düşen iddialar §6'ya eklendi.

Bu oturumda §6'ya **beş yeni çürütülmüş madde** girdi (18–22) ve manşet
iddia **genişledi**. Düşenlerin hiçbiri "ölçüm gürültülüydü" türünden
değil; hepsi **"ölçülen şey sanılan şey değildi"** sınıfında — yani daha
fazla koşuyla ortaya çıkmazlardı, daha fazla koşu yanlış sayıyı daha dar
hata payıyla verirdi:

| # | düşen | gerçekte olan |
|---|---|---|
| 18 | rakip build −%3.7 (iki taraflı kazanç) | metrik LLM'in kendi süresini okuyordu; gerçekte rakip %2.4 yavaşlıyor |
| 19 | akış bant genişliği 91 GB/s | fiziksel tavanın üstünde |
| 20 | erken uyarı = decode-şekilli kuyruk | bölge prefill gibi ölçekleniyor |
| 21 | %2 tabanı her yere uygulanır | taban metriğe ve senaryoya bağlı |
| 22 | 24 ms model-bağımsız sabit maliyet | bağımsızlık varsayımı BW'yi imkânsıza itiyordu |

Ayrıca §3.4'ün "J/token −%2.5" enerji iddiası *reported, not claimed*
seviyesine indi (§11.3).

---

## 11.1 U1 — statik Pareto cephesi: ara kollar ölçüldü

**İtiraz:** "en iyi statik konfigürasyonu Pareto olarak baskılıyor" iddiası
yalnızca iki uç noktaya (A_P8, C_P8_E8) karşı ölçülmüştü. Ara noktalar
(P8+E2/E4/E6) hiç denenmemişti; belki biri statik olarak SWITCH'in
yaptığını yapıyordu.

**Ölçüm:** 6 kol × 2 senaryo × 6 tur = 72 koşu, interleaved, sıfır hata.
`harness/i14_frontier.py`, `results/i14_frontier/`.

### Rakipsiz

| kol | TTFT | ITL p50 | ITL p95 | J/token |
|---|---|---|---|---|
| A_P8 | 11 078 | 86.57 | 91.25 | 11.100 |
| P8_E2 | 11 157 | 93.14 | 95.83 | 11.582 |
| P8_E4 | 10 422 | 98.58 | 102.63 | 11.793 |
| P8_E6 | 10 443 | 96.44 | 100.83 | 11.560 |
| C_P8_E8 | 9 785 | 96.68 | 102.96 | 11.417 |
| **SWITCH** | **9 790** | **86.57** | **87.15** | **10.541** |

Statik Pareto cephesi: **{A_P8, P8_E6, C_P8_E8}**. P8_E2 ve P8_E4
baskılanıyor — cephede durmuyorlar.

**Neden:** decode hasarı basamak, prefill kazancı kademeli. Yalnızca 2
E-core eklemek ITL p50'yi 86.57 → 93.14'e taşıyor (bedelin çoğu) ama
TTFT'ye hiç fayda vermiyor (11 078 → 11 157, hatta hafif kötü). Kazanç
ancak E4'ten sonra başlıyor. Ara noktalar tam fiyatı ödeyip malın bir
kısmını alıyor; Pareto anlamında yeri olmamasının sebebi bu.

SWITCH cephedeki **üç noktanın üçünü de** baskılıyor:

| karşı | TTFT | ITL p95 | sonuç |
|---|---|---|---|
| A_P8 | −%11.62 | −%4.50 | **her ikisinde de iyi** |
| P8_E6 | −%6.25 | −%13.57 | **her ikisinde de iyi** |
| C_P8_E8 | +%0.06 (eşit) | −%15.36 | baskılıyor |

SWITCH'i baskılayan statik yok.

### Kısa build patlaması altında

Statik cephe {A_P8, C_P8_E8}; üç ara kolun üçü de baskılanıyor.
SWITCH A_P8'i baskılıyor (TTFT −%10.5, p95 −%2.5 → bu senaryonun p95
tabanı %5.20 olduğu için "eşit"). C_P8_E8'e karşı ise **takas**:
TTFT +%0.76 (kendi tabanının iki katı, gerçek ama minik — 10.5 s'de
80 ms), ITL p95 −%11.8.

**Senaryolar arasındaki fark tabanların farkından geliyor**, etkilerin
değil: p95 avantajı iki senaryoda da benzer büyüklükte (−%4.5 / −%2.5)
ama rakipsizken taban %0.7, aralıklı rakiple %5.20. Aynı fark birinde
bulgu, diğerinde gürültü.

*Not: bu senaryonun rakibi sanıldığı kadar çekişmeli değildi; bkz. §11.2.*

### İddianın yeni hâli

> Eski: "iki uç noktayı yeniyor."
> **Yeni: rakipsiz senaryoda, ara noktalar dahil statik Pareto cephesinin
> tamamını baskılıyor. Hiçbir statik konfigürasyon onu baskılamıyor.**
> Kısa build patlaması altında A_P8'i baskılıyor, C_P8_E8'e karşı küçük
> bir TTFT karşılığında büyük bir p95 kazancı takas ediyor.

Hakemin ilk sorusu **rakipsiz senaryo için** kapandı ve cevap iddiayı
daraltmadı. Rakipli senaryo aşağıda ayrıca ölçüldü.


### 11.1b — aynı soru, GERÇEK rakip altında

Yukarıdaki cephe rakipsiz senaryoda kapandı. Rakipli taraf iki sebeple
açıktı: ilk "build patlaması" senaryosunun çekişmeli olmadığı §11.2'de
ortaya çıktı, ve düzeltilmiş deney (a20) yalnızca üç kol içeriyordu.
Yani "ya bir ara statik konfigürasyon rakip altında SWITCH'i baskılıyorsa?"
sorusunun cevabı yoktu.

**Ölçüm:** 6 kol × 6 tur = 36 koşu, interleaved, sıfır hata. Rakip:
pencere boyunca döngüde `make -j16`, iş metriği tamamlanan geçiş sayısı.
Altı kol da **aynı oturumda** (a20'nin sayılarıyla kıyaslanmadı; oturum
içi drift %0.5–0.7). `harness/a21_frontier_contended.py`,
`results/frontier_contended/`.

| kol | TTFT | ITL p50 | ITL p95 | ITL p99 | tps | rakip hız | J/token |
|---|---|---|---|---|---|---|---|
| A_P8 | 14 421 | 108.89 | 250.26 | 269.60 | 7.84 | **0.3477** | 16.018 |
| P8_E2 | 13 794 | 113.49 | 268.42 | 294.60 | 7.42 | 0.3384 | 16.413 |
| P8_E4 | 13 196 | 119.31 | 276.05 | 309.84 | 7.12 | 0.3320 | 16.672 |
| P8_E6 | 13 085 | 121.76 | 280.82 | 320.67 | 6.98 | 0.3294 | 16.828 |
| C_P8_E8 | 12 628 | 122.01 | 284.06 | 328.69 | 6.92 | 0.3302 | 16.796 |
| **SWITCH** | **12 623** | **108.30** | **247.47** | **269.59** | **7.84** | 0.3395 | **15.399** |

Bu senaryonun **kendi** gürültü tabanı (kol-içi CV medyanı): TTFT %0.64,
ITL p50 %0.76, ITL p95 %1.36, ITL p99 %2.88, tps %0.92, rakip hız %0.69,
J/token %0.59.

#### Rakipsiz bulgu BURADA TUTMUYOR

§11.1'de ara kolların cephede duramamasının sebebi "decode hasarı
basamak, prefill kazancı kademeli"ydi. Rakip altında bu **değişiyor**:

| | rakipsiz | rakipli |
|---|---|---|
| P8_E2'nin TTFT'ye etkisi | **+%0.71 (kötü)** | **−%4.35 (iyi)** |
| P8_E2'nin ITL p50'ye etkisi | +%7.59 | +%4.22 |

Rakipsizken 2 E-core eklemek bedelin çoğunu ödetip **hiçbir şey
kazandırmıyordu** — o yüzden kesin baskılanıyordu. Rakip altında aynı
adım TTFT'yi %4.35 iyileştiriyor ve ITL bedeli yarıya iniyor. İki eksen
de artık kabaca orantılı ilerliyor:

| kol | ITL p50 | TTFT |
|---|---|---|
| P8_E2 | +%4.22 | −%4.35 |
| P8_E4 | +%9.57 | −%8.49 |
| P8_E6 | +%11.82 | −%9.27 |
| C_P8_E8 | +%12.05 | −%12.43 |

Yani basamak fonksiyonu yerine **düzgün bir takas eğrisi** var. Sonucu:
**statik cephe kalabalıklaşıyor** — {A_P8, P8_E2, P8_E4, C_P8_E8}; dört
statikten üçü cephede, yalnızca P8_E6 baskılanıyor (C_P8_E8 tarafından:
TTFT −%3.5 daha iyi, p95 farkı taban içinde).

**Mekanizma için ölçülmüş kanıt:** rakibin hızı E-core sayısıyla
monoton düşüyor (0.3477 → 0.3302). Yani rakipli senaryoda "E-core ekle"
adımı LLM'e kapasite vermenin yanında **rakibi o çekirdeklerden
tahliye ediyor**; rakipsiz senaryoda tahliye edilecek kimse yoktu ve
adım karşılıksız kalıyordu. *(Tahliye kanalının varlığı ölçüldü;
TTFT kazancının ne kadarının ondan geldiği ayrıştırılmadı.)*

#### SWITCH'in konumu

| karşı | TTFT | ITL p95 | sonuç |
|---|---|---|---|
| A_P8 | −%12.47 | −%1.11 (eşit) | **BASKILIYOR** |
| P8_E2 | −%8.49 | −%7.80 | **BASKILIYOR** |
| P8_E4 | −%4.35 | −%10.35 | **BASKILIYOR** |
| C_P8_E8 | −%0.04 (eşit) | −%12.88 | **BASKILIYOR** |

**SWITCH cephedeki dört noktanın dördünü de baskılıyor. Hiçbir statik
SWITCH'i baskılamıyor.** Üstelik bu, §11.1'dekinden **daha güçlü** bir
sonuçtur: orada cephe üç noktalıydı ve üç ara koldan ikisi zaten
baskılıydı; burada cephe dört noktalı ve üç ara koldan **ikisi cephede**
— yani SWITCH'in aşması gereken statik seçenek kümesi daha zengin.

Welch testi (n=6+6), SWITCH vs A_P8: TTFT −%12.47 (t=−23.0, **p<0.01**),
ITL p95 −%1.11 (ns), ITL p50 −%0.54 (ns), J/token −%3.86 (t=−11.8,
**p<0.01**), rakip hız −%2.36 (t=−6.96, **p<0.01**).

#### Rakip tarafı: küçük ama gerçek bir maliyet

| kol | rakip hız | A_P8'e karşı |
|---|---|---|
| A_P8 | 0.3477 | — (rakip için en iyi) |
| **SWITCH** | 0.3395 | **−%2.36** |
| P8_E2 | 0.3384 | −%2.68 |
| C_P8_E8 | 0.3302 | −%5.02 |
| P8_E6 | 0.3294 | −%5.26 |

E-core kullanan her kol rakibe zarar veriyor; **SWITCH bu grubun en az
zarar vereni**, çünkü E-core'ları yalnızca prefill boyunca tutuyor.
Rakip için mutlak en iyi kol hâlâ A_P8'dir (E-core'lara hiç dokunmaz) —
ama o kol LLM'e %12.5 daha kötü TTFT veriyor.

### İddianın yeni hâli

> **Rakipsiz senaryoda:** üç ara koldan ikisi (P8_E2, P8_E4) cephede
> duramıyor — E-core eklemenin ilk adımı karşılıksız. Cephe
> {A_P8, P8_E6, C_P8_E8}; SWITCH üçünü de baskılıyor.
>
> **Gerçek rakip altında:** takas eğrisi düzgünleşiyor ve cephe
> kalabalıklaşıyor ({A_P8, P8_E2, P8_E4, C_P8_E8}), **ama SWITCH
> dördünü birden baskılamaya devam ediyor.** Bedeli rakibin
> throughput'unda %2.36 — gerçek (p<0.01) ama E-core kullanan statik
> kolların yarısından az.

Hakemin R1'i artık her iki senaryo için de cevaplanmış durumda.


---

## 11.2 U2 — "rakip build −%3.7" GEÇERSİZ

**İtiraz:** iddianın kendi gürültü tabanı yoktu ve build'in her koşuda
temiz başladığı belgelenmemişti.

Taban ölçülmeye çalışılırken iddianın kendisi çöktü. İki ayrı kusur
üst üste binmiş:

### Kusur 1 — metrik yanlış değişkeni okuyordu

`phase_switch.py`'de `build.wait()` ölçülen istek tamamlandıktan *sonra*
çağrılıyordu. Build çok daha önce bittiği için `wait()` anında dönüyor ve
`build_wall_s` build süresini değil **LLM isteğinin süresini** kaydediyordu.

Doğrulama — iddianın çıktığı deney (`switch_build`) ve i14'ün 36 build
koşusu:

| kol | build_wall_s | LLM istek süresi | fark |
|---|---|---|---|
| A_P8 | 35.70 | 35.59 | +0.11 |
| SWITCH | 34.37 | 34.33 | +0.04 |
| C_P8_E8 | 37.24 | 37.19 | +0.05 |

i14'ün 36 build koşusunda fark: medyan +0.10 s, sd 0.15 s.

Yani "rakip build −%3.7", SWITCH'in kendi tamamlanma süresinin başka
isimle yazılmış hâliydi. Rakip hakkında hiçbir bilgi taşımıyordu.

### Kusur 2 — rakip pencerenin %87'sinde yoktu

20 koşuluk temiz ölçüm (`harness/a16_build_noise.py`): tek geçiş
**2.151 s** (CV %3.27, n=20). Rakip 2 geçiş koşuyordu → ~4.3 s. Ölçüm
penceresi ~33 s.

Hijyen belgelendi: ccache derleme yolunda **değil** (`/usr/bin/cc` →
gerçek gcc, PATH'te ccache yok, CMake launcher yok), her koşu 0 nesneyle
başladı, page cache 12.9–13.0 GB aralığında sabit.

Veri bunu doğruluyor: build senaryosunda TTFT +%6.7 kötüleşiyor ama
ITL p50 değişmiyor (86.57 → 86.66) — rakip yalnızca prefill sırasında
vardı.

İki kusur bağımsız değil: build isteği aşacak kadar uzun olsaydı
`wait()` gerçekten beklerdi. **Tek kök neden, rakibin ölçüm penceresine
göre çok kısa olması.**

### Düzeltme ve yeniden ölçüm

Rakip pencere boyunca döngüye alındı, iş metriği **tamamlanan geçiş
sayısı** oldu (`build_passes`, `build_rate`). Etkisi dramatik: aynı
A_P8 kolunda ITL p95 91.6 → 259.5 ms. Eski senaryo çekişmeli değildi.

**Yeniden ölçüm (30 koşu, 5 kol, 6 tur, sıfır hata)** —
`harness/a20_real_competitor.py`, `results/real_competitor/`:

| kol | TTFT | ITL p50 | ITL p95 | tps | rakip geçiş | rakip hız |
|---|---|---|---|---|---|---|
| A_P8 | 14 281 | 110.32 | 252.40 | 7.70 | 17.0 | 0.3455 |
| C_P8_E8 | 12 514 | 122.77 | 296.84 | 6.86 | 17.0 | 0.3287 |
| SWITCH | 12 594 | 109.88 | 250.52 | 7.78 | 16.0 | 0.3378 |

Bu senaryonun kendi gürültü tabanı (kol-içi CV medyanı, n=6):
TTFT %1.06, ITL p50 %0.55, ITL p95 %1.51, rakip hız %2.34, tps %0.80.

**SWITCH, rakibe A_P8'den fazla iş yaptırmıyor:** −%2.21. C_P8_E8'e
karşı +%2.75.

> **DÜZELTME (§11.1b):** bu farkı ilk yazımda "gürültü içinde" saydım,
> çünkü tabanı kol-içi CV bandıyla tahmin etmiştim (%2.34) — o tahmin
> bu deneydeki A_P8 kolunun alışılmadık yüksek CV'sinden (%2.34, başka
> oturumda %0.58) şişmişti. **Welch testiyle bakınca aynı veri
> t=−2.96, p<0.05 veriyor.** Bağımsız bir deneyde (§11.1b, n=6+6) aynı
> büyüklükteki fark tekrarlandı: **−%2.36, t=−6.96, p<0.01.**
>
> Doğru okuma: **SWITCH rakibe küçük ama gerçek bir maliyet yüklüyor**
> (~%2.2–2.4), eşitlik değil. Yine de E-core kullanan statik kolların
> (−%2.7 … −%5.3) en az zarar vereni odur.
>
> *Ders: CV-bandı sezgisi n=6'da bir farkı yanlışlıkla gürültüye
> gömebiliyor. Kritik karşılaştırmalarda test kullanılmalı.*

LLM tarafında ise A_P8'e karşı TTFT **−%11.8** (tabanın 11 katı), ITL p50
−%0.4 ve p95 −%0.7 (ikisi de eşit), tps +%1.0.

### İddianın yeni hâli

> Eski: "takas değil, iki taraflı kazanç — LLM TTFT −%10.8, rakibin
> build'i −%3.7."
> **Yeni: SWITCH, LLM'in TTFT'sini %11.8–12.5 iyileştirirken rakibe
> %2.2–2.4 maliyet yüklüyor (p<0.01, iki bağımsız deneyde). Rakip
> tarafında kazanç YOK — küçük bir kayıp var.**

**"İki taraflı kazanç" cümlesi desteklenmiyor ve kaldırıldı** (§6,
madde 18). Doğru çerçeve bir takastır: LLM'in TTFT'sinde %12'lik kazanç,
rakibin throughput'unda %2.4'lük kayıp karşılığında. Takasın oranı
elverişlidir ama takas olduğu yazılmalıdır.

Ayrıca not: eski senaryodaki "−%3.7" ile buradaki "−%2.21" birbirinin
düzeltilmiş hâli değil — eskisi rakibi hiç ölçmüyordu. Sayıların
yakınlığı tesadüftür.

---

## 11.3 U12 — enerji gürültü tabanı

**İtiraz:** §1.1'in 20 koşuluk çalışması J/token içermiyordu; −%4.6 ve
−%2.5 iddialarının tabanı yoktu.

**Yeniden analiz:** J/token içeren ve aynı konfigürasyonda ≥4 tekrarı
olan 26 grup.

| | J/token CV |
|---|---|
| medyan | **%0.63** |
| min | %0.08 |
| max | %3.66 |

Oturum içi ardışık koşular çok kararlı (%0.1–0.7); yüksek uçtaki değerler
oturumlar arasına yayılmış gruplardan (`i9_sched`, n=34, CV %3.3–3.6).
**Doğru taban genel bir sayı değil, iddianın kendi veri setinin CV'sidir.**

| iddia | etki | kendi kolunun CV'si | karar |
|---|---|---|---|
| §3.2 "en az enerji, −%4.6" | −%4.55 | %0.15 / %0.40 | **GEÇERLİ** (~11×) |
| §3.4 "J/token −%2.5" | −%2.16 | **%2.98** | **DÜŞTÜ** |

§3.4'ün enerji iddiası *reported, not claimed* seviyesine indi ve o
bölümde yerinde düzeltildi. Yan gözlem: çok turlu SWITCH kolunun enerji
CV'si (%2.98) aynı deneydeki A_P8'in dört katı (%0.71) — §11.5'te bulunan
tur-4 anomalileriyle tutarlı.

---

## 11.4 U15 — gürültü tabanı metrikten metriğe değişiyor

**İtiraz:** %2 tabanı tek konfigürasyonda, rakipsiz, tek oturumda
ölçülmüş; sonra her senaryoya uygulanmıştı.

**Ölçüm:** §1.1'in protokolü aynen, 20 koşu, `SWITCH + build`
(`harness/a17_contended_noise.py`).

| metrik | CV | yayılım |
|---|---|---|
| TTFT | %0.38 | %1.2 |
| ITL p50 | %0.31 | %1.4 |
| decode tps | %0.74 | %3.5 |
| J/token | %0.56 | %2.7 |
| **ITL p95** | **%5.20** | **%23.9** |
| **ITL p99** | **%5.65** | **%27.2** |

**Sonuç, beklenenden farklı çıktı.** Sorulan "çekişmeli taban rakipsiz
tabandan büyük mü?"ydü; cevap "senaryo değil, **metrik** belirleyici":

- Merkezi eğilim metrikleri (TTFT, ITL p50, tps, J/token) %2'nin **çok
  altında** — orada taban fazlasıyla güvenli, hatta gereksiz gevşek.
- **Kuyruk metrikleri %2'nin iki buçuk katı gürültülü.** Ve ITL p95 bu
  projenin birincil metriği; başarı ölçütü doğrudan onun üzerine kurulu.

### Etkisi

Cephe analizi (§11.1) **senaryo-başına ve metrik-başına** tabanla yeniden
hesaplandı. Bu iki aşamada oldu ve ilki hatalıydı — kayda geçiriliyor:

1. Önce tüm senaryolara §11.4'ün (aralıklı rakip) tabanları uygulandı.
   Bu, **rakipsiz** koldaki gerçek bir p95 farkını (−%4.5) yanlışlıkla
   "eşit" gösterdi: o kola %5.20'lik taban ait değil.
2. Düzeltildi: her senaryo kendi tabanıyla değerlendiriliyor.

Nihai etki:

- **Rakipsiz:** SWITCH, A_P8'i **her iki eksende de** yeniyor (TTFT
  −%11.6, p95 −%4.5; taban %0.5 / %0.7). Ara kol P8_E6 daha sıkı tabanla
  cepheye giriyor ve o da baskılanıyor.
- **Aralıklı rakiple:** p95 avantajı (−%2.5) %5.20'lik tabanın içinde
  kalıyor → "eşit"; baskılama TTFT ekseninden geliyor. Ayrıca +%0.76'lık
  TTFT farkı %0.38'lik tabanın iki katı olduğu için anlamlı hale geliyor.

**Ders:** taban seçimi sonucu doğrudan çeviriyor. Yanlış senaryodan
alınmış bir taban, gerçek bir farkı gürültü diye eleyebiliyor — ve bu
hata bu raporda bir kez fiilen yapıldı.

**Sınır:** bu CV'ler tek bir koldan (`SWITCH+build`, 20 koşu) ölçüldü ve
diğer kollara aynı oldukları varsayılarak uygulandı; §11.1'in kararları
hâlâ buna dayanıyor. **§11.1b'de düzeltildi** — orada altı kolun her
birinin kendi CV'si hesaplanıp medyanı alındı. Ama n=6'lık CV'ler
20 koşuluk bir tabandan gürültülüdür; tam çözüm kol başına 20 koşudur ve
yapılmadı.

*İki tabanın karşılaştırması, senaryo bağımlılığını da gösteriyor:*

| | ITL p95 tabanı | rakip hız tabanı |
|---|---|---|
| §11.4 (aralıklı rakip, tek kol, n=20) | %5.20 | — |
| §11.1b (sürekli rakip, 6 kol, n=6) | %1.36 | %0.69 |
| §11.2 (a20, 5 kol, n=6) | %1.51 | %2.34 |

Rakip hız tabanının a20'de (%2.34) a21'dekinin (%0.69) üç katı çıkması,
o deneydeki A_P8 kolunun tek başına gürültülü olmasından geliyordu —
ve §11.2'de bir sonucu yanlış yöne çevirdi (bkz. oradaki düzeltme).

---

## 11.5 U9 — dedektör: precision, held-out, duyarlılık

**İtiraz:** yalnızca recall raporlanıyordu; eşiğin hangi veriden seçilip
hangi veride değerlendirildiği belirsizdi; §3.4'ün "−760 ms" anomalileri
hiçbir sınıfa girmiyordu.

**Yeniden analiz:** 12 konfigürasyon, 49 koşu + 30 çok turlu tur.
`harness/a15_detector_eval.py`.

### Eşik seçimi ve held-out

Eşikler (hi=3000, lo=2100, k=2) **h5 ailesinden** (pinned/unpinned, 10
koşu) seçildi. Kalan 10 konfigürasyon (39 koşu) eşik seçiminde
kullanılmadı:

| | recall | precision | uzak FP/koşu | fazla geçiş/koşu |
|---|---|---|---|---|
| tümü (49 koşu) | %100.00 | %99.38 | 0.00 | 0.00 |
| **held-out (39 koşu, 10 konfig)** | **%100.00** | **%99.36** | **0.00** | **0.00** |

**FP'lerin tamamı sınıra bitişik (≤300 ms).** 49 koşunun hiçbirinde
sınırdan uzak tek bir FP yok. Yani precision'daki %0.6'lık açık gürültü
değil, erken tetiklemenin kendisi. Salınım da yok: toplam sıfır fazla
durum geçişi.

### Eşik duyarlılığı

±%30 tamamen düz çıktı — ama bu eşiğin iyiliğini değil, ±%30'un çalışma
penceresinin çok içinde kaldığını gösteriyor. Tarama genişletildi:

| hi | recall | precision | fazla geçiş | erken uyarı |
|---|---|---|---|---|
| 300 | %100.00 | %96.71 | **16.45** | −10 838 ms (çöp) |
| 1 000 | %100.00 | %99.11 | 0.04 | −121 ms |
| **3 000** | %100.00 | %99.38 | 0.00 | −118 ms |
| 8 000 | %99.93 | %99.65 | 0.33 | −97 ms |
| 12 000 | %93.71 | %100.00 | 0.65 | **+50 ms (GEÇ)** |
| ≥20 000 | — | — | — | hiç tetiklenmiyor |

**Çalışma penceresi hi ∈ [1 000, 8 000]** — 8 kat genişlik. Dağıtılan
değer 3 000, bu pencerenin geometrik ortasına yakın (2 828).

Sinyal ayrımı (76 658 örnek): prefill p95=989, p99=6 639, max=11 443;
decode p1=3 839, p5=5 347, p50=13 938. Dağılımlar 3 800–11 400 aralığında
**örtüşüyor** — ayrımı yapan tek eşik değil, histerezis + k=2.

### "−760 ms" anomalileri sınıflandırıldı

| kategori | sayı | oran |
|---|---|---|
| uzak-erken tetikleme (−770, −759 ms) | 2 / 30 | **%6.7** |
| fazla ileri geçiş | 1 / 30 | %3.3 |
| decode ortasında erken geri dönüş | 1 / 30 | %3.3 |
| geç tetikleme | 0 / 30 | %0 |

*Kategoriler tur bazında örtüşüyor: "fazla ileri geçiş" ve "decode
ortasında erken geri dönüş" **aynı turdur** (r01, tur 5). Ayrı turlar
sayıldığında toplam **3 anomalili tur / 30 = %10** — §3.4'teki sayıyla
aynı. Yukarıdaki tablo olay tipine göre, §3.4'teki tura göre sayıyor.*

Her iki uzak-FP de **tur 4**'te, iki ayrı koşuda — sistematik, rastgele
değil. Bedeli:

| | n | TTFT | ITL p50 | ITL p95 |
|---|---|---|---|---|
| normal tur | 28 | 867 ms | 86.98 | 89.18 |
| anomali tur | 2 | **978 ms (+%12.8)** | 87.13 | 89.13 |

Maliyet gerçek ama yalnızca TTFT'de. Mekanizma tutarlı: 760 ms erken
tetikleme, ~870 ms'lik kısa bir prefill'in neredeyse tamamının dar
maskede koşması demek.

### İddianın yeni hâli

> Dedektör, eşik seçiminde kullanılmayan 10 konfigürasyonda %100 recall
> ve %99.4 precision veriyor; sınırdan uzak yanlış pozitif üretmiyor,
> salınmıyor, ve hi ∈ [1 000, 8 000] aralığının tamamında çalışıyor.
> **Tek turlu** kullanımda anomali gözlenmedi; **çok turlu** kullanımda
> turların %6.7'sinde erken tetikleme oluyor ve o turlarda TTFT %12.8
> kötüleşiyor.

Son cümle yeni: dedektörün zayıf noktası çok turlu kullanımdaki kısa
prefill'lerdir.

---

## 11.6 U4 — erken uyarının mekanizması

**İtiraz:** "mekanizma bilinmiyor ama artefakt olmadığı kanıtlandı"
denmişti. §8'in kurtarma hipotezi şuydu: prefill grafiğinin kuyruğu zaten
decode-şeklidir ve süresi ≈ bir decode token'ı; doğruysa dedektör erken
değil, yer-gerçeği tanımı yanlış yerdedir.

**Ayırt edici tahmin:** erken uyarı süresi decode token süresiyle
orantılı ölçeklenmeli.

**Veri:** `h5_cores` (c4 ve c8 bu amaç için n=6'ya çıkarıldı) ve
`h5_promptlen`. `harness/a14_leadscale.py`.

### İki değişmez

**1. Erken uyarı prompt uzunluğundan bağımsız.**

| prompt | TTFT | erken uyarı | erken/ITL |
|---|---|---|---|
| 32 | 880 ms | 131.6 ms | 1.53 |
| 128 | 2 885 ms | 133.7 ms | 1.55 |
| 256 | 5 665 ms | 139.3 ms | 1.62 |
| 496 | 10 907 ms | 132.8 ms | 1.54 |
| 1024 | 22 687 ms | 139.2 ms | 1.61 |

TTFT 26 kat değişirken erken uyarı 132–139 ms'de sabit (yayılım %5.7).
Sabit miktarda bir işe karşılık geliyor.

**2. Ama çekirdek sayısına bağımlı ve decode gibi ölçeklenmiyor.**

| çekirdek | n | TTFT | ITL | erken uyarı | erken/ITL |
|---|---|---|---|---|---|
| 4 | 6 | 18 362 ms | 109.8 ms | 208.8 ms | 1.90 |
| 6 | 3 | 13 311 ms | 94.0 ms | 150.4 ms | 1.60 |
| 8 | 6 | 11 023 ms | 86.8 ms | 134.9 ms | 1.55 |

4→8 çekirdek (2× kaynak) ölçeklenme verimi:

| | hızlanma | verim |
|---|---|---|
| prefill (TTFT) | 1.666× | **%83** |
| decode (ITL) | 1.265× | %63 |
| **erken uyarı** | 1.547× | **%77** |

*Not: §2.3'teki %77/%49 ile karıştırılmamalı — o, 2→8 çekirdek aralığı
için. Verim dar ve yüksek aralıkta doğal olarak yüksek çıkar. Buradaki
karşılaştırmanın geçerliliği için önemli olan, üç sayının da **aynı
aralıktan ve aynı koşulardan** gelmesidir.*

### Karar: iki rakip açıklama da elendi

* **"Erken uyarı sabit bir dedektör artefaktı" → ELENDİ.** 209 → 135 ms,
  yayılım %45. Gerçek bir işi ölçüyor.
* **"§8: bölge decode-şeklinde, oran sabit" → ELENDİ.** Oran sabit değil
  (1.90 → 1.55; 4 ve 8 çekirdek grupları örtüşmüyor: 1.71–1.97 vs
  1.45–1.62). Daha belirleyicisi bölge **%77 verimle** ölçekleniyor,
  decode'un %63'üyle değil.

**Yani yer-gerçeği tanımı yanlış yerde değil.** Erken tetikleme gerçekten
erken: dedektör, hâlâ prefill-şeklinde hesap sürerken karar veriyor.
§8'in kurtarma açıklaması ölçümle çürütüldü.

### Mekanizma hâlâ açık, ama arama uzayı daraldı

Aranan şey: **prompt uzunluğundan bağımsız, sabit büyüklükte, %77 verimle
paralelleşen, prefill'in en sonunda yapılan bir iş.**

Test edilmemiş bir aday: son katman / çıkış projeksiyonu (lm_head),
llama.cpp'de prefill sırasında yalnızca son pozisyon için hesaplanır —
prompt uzunluğundan bağımsız ve büyük bir paralel GEMM'dir. **Bu bir
tahmindir, ölçülmedi;** yukarıdaki eleme buna bağlı değil.

---

## 11.7 U6 — "91 GB/s gerçek akış bant genişliği" GEÇERSİZ

**İtiraz:** rapor 91 GB/s veriyordu; DDR5 çift kanal için teorik tavan
bunun altında. Ölçülen değer tavanı aşıyorsa fit yanlıştır. Üstelik aynı
hesap sınıfı bir kez zaten yanlış çıkmıştı (66 GB/s).

### Donanım kayda geçirildi

`sudo dmidecode -t memory`: 2 × 16 GiB DDR5 SODIMM, ayrı denetleyicilerde
(`Controller0-ChannelA`, `Controller1-ChannelA`) → gerçekten çift kanal.
Data width 64 bit/modül.

**Belirleyici satır `Speed` değil `Configured Memory Speed`:** modüller
5600 MT/s'ye dereceli ama sistem onları **5200 MT/s**'de sürüyor.

```
kanal başına : 5200 × 10^6 T/s × 8 B/T = 41.6 GB/s
iki kanal    :                           83.2 GB/s
```

| | GB/s | tavana oranı |
|---|---|---|
| **raporun fit'i** | **91.0** | **%109.4** |
| teorik tavan (yapılandırılmış, 5200) | 83.2 | %100 |
| teorik tavan (dereceli 5600, ulaşılamaz) | 89.6 | %107.7 |

**Fit teorik tavanı aşıyor** — yapılandırılmış hıza karşı %9.4, dereceli
hıza karşı bile %1.6. Bir ölçüm teorik tavanı aşamaz.

### Bağımsız ölçüm

`harness/membw.c` (bağımlılıksız, saf okuma + triad ayrı ayrı).
Saf okuma ölçülüyor çünkü decode ağırlıkları okur, neredeyse hiç yazmaz;
triad'a (2 okuma + 1 yazma) karşı kıyaslamak decode'u haksız yere iyi
gösterirdi.

**Pinleme belirleyici çıktı:**

| konfigürasyon | saf okuma | triad | teorik tavana oran |
|---|---|---|---|
| 8 thread, pinsiz | 47.78 | 56.97 | %57 |
| **8 thread, P-core'a pinli** (decode'un konfigürasyonu) | **71.25** | 66.91 | **%86** |
| 16 thread, tüm P (SMT dahil) | **77.65** | 66.58 | %93 |
| 24 thread, pinsiz | 63.63 | 57.87 | %76 |

Pinsiz ölçüm yanıltıcıdır — thread'ler E-core'a düşüyor ve bant genişliği
neredeyse yarıya iniyor. İlk ölçüm bu tuzağa düştü ve düzeltildi.

| | GB/s |
|---|---|
| raporun fit'i | **91.0** |
| ölçülen maksimum (16 P thread) | 77.65 |
| teorik tavan | 83.2 |

Fit, teorik tavanı %9.4, **ölçülen maksimumu %17.2 aşıyor.**

### Beklenmeyen sonuç: C3 sayısal olarak düşerken niteliksel olarak güçlendi

Bağımsız ölçüm elde olunca doğrudan bir çapraz kontrol mümkün oldu:

```
decode'un ihtiyacı : 5.68 GB (model) x 11.53 tok/s = 65.5 GB/s
kendi konfigürasyonundaki tavan (8 P-core, saf okuma) = 71.25 GB/s
                                              doluluk = %92
```

**Decode, kendi konfigürasyonunun bellek tavanının %92'sinde çalışıyor.**
K1'in niteliksel iddiası ("decode bant genişliğine dayanmış") böylece
iki noktalı bir fit'e değil, bağımsız bir ölçüme dayanır hâle geldi —
ve daha güçlü bir zeminde duruyor.

*Uyarı: bu hesap modelin tamamının her token'da DRAM'den okunduğunu
varsayar. %92 doluluk bu varsayımla tutarlı ama onu kanıtlamaz; gerçek
DRAM trafiğini ölçmek uncore sayaçları gerektirir ve yapılmadı.*

### İkinci sonuç: fit'in SABİT maliyeti de düşüyor

İlk yazımda "sabit maliyet sütunu bu itirazdan etkilenmiyor" demiştim.
**Yanlıştı.** Fit iki bilinmeyeni tek bir denklem çiftinden çözüyor;
ikisi bağımsız değil. t8'de (9B 85.88 ms, 4B 53.94 ms):

```
BW = (5.68 − 2.74) GB / (85.88 − 53.94) ms = 92.0 GB/s   → imkânsız
sabit = 85.88 − 5680/92.0                 = 24.2 ms
```

BW'yi fiziksel sınıra zorlarsak sabit maliyet **model boyutuna göre
ayrışıyor**:

| BW | 9B sabit | 4B sabit | fark |
|---|---|---|---|
| 66.1 (9B için alt sınır: sabit ≥ 0) | −0.05 ms | 12.48 ms | +12.53 |
| 71.25 (ölçülen tavan) | 6.16 ms | 15.48 ms | +9.32 |

Fiziksel olarak mümkün tüm BW aralığında ([66.1, 71.25]) 4B'nin sabiti
9B'ninkinden 9–12.5 ms büyük. Yani **"sabit maliyet model boyutundan
bağımsızdır" varsayımı, BW'yi imkânsıza iten şeyin kendisidir.**

Sonuç: §2.6'nın "token başına ~24 ms model-bağımsız sabit maliyet"
bulgusu da geçersizdir (§6, madde 22). Akış-dışı bir maliyetin **varlığı**
duruyor — 4B'nin daha kötü ölçeklenmesi hâlâ onunla açıklanıyor, hatta
daha güçlü biçimde, çünkü küçük modelde bu maliyet oransal olarak değil
**mutlak olarak da** büyük görünüyor. Nedeni bu veriyle bilinmiyor.

### Üçüncü sonuç: bir DÜZELTME de aşırı düzeltmeymiş

Fit düşünce, ondan türeyen akış/akış-dışı bölünmesi de düşüyor — ve
düzeltilmiş hâli **orijinaline geri yaklaşıyor**. Aynı seri modelde
BW'yi fiziksel aralığa koyarsak, 9B için t8'de:

| BW | akış payı | akış-dışı payı |
|---|---|---|
| 92.0 (fit, imkânsız) | %71.9 | **%28.1** |
| 71.25 (ölçülen tavan) | %92.8 | %7.2 |
| 66.1 (akış-dışı = 0 sınırı) | ~%100 | ~%0 |

| ifade | akış-dışı pay (9B) |
|---|---|
| Faz 1 orijinali ("~%87 bandwidth") | ~%13 |
| §6 madde 17'nin düzeltmesi (fit'ten) | %28 |
| **fiziksel sınırla** | **%0 – %7.2** |

**Yani "%87 fazla iddialıydı, doğrusu %72" düzeltmesi yanlış yöne
gitmişti.** Fiziksel olarak mümkün aralıkta 9B decode'u **≥%93
akış-baskın** — orijinal ifade, onu düzelten sayıdan gerçeğe daha
yakınmış. Madde 17 tarihsel kayıt olarak duruyor ama artık kendi
düzeltmesiyle birlikte okunmalı.

Model bağımlılığı aynı hesaptan çıkıyor: 4B için akış-dışı pay
**%23–29**. Yani akış-dışı maliyet 9B'de ihmal edilebilir, 4B'de
belirleyici — §2.6'nın "küçük model neden daha kötü ölçekleniyor"
sorusunun cevabı bu, "her iki modelde de ~24 ms sabit maliyet var"
değil.

*(Hepsi fit'in kendi seri varsayımı altında: token süresi = akış +
akış-dışı, örtüşme yok. Örtüşme varsa akış-dışı payın üst sınırı daha
da düşer.)*

### Sonuç

- **91 GB/s sayısı rapordan ve makaleden çıkarıldı.**
- **C3 iddiası niceliksel olarak düştü ama niteliksel olarak GÜÇLENDİ.**
  "Decode 91 GB/s akış bant genişliğiyle sınırlı" gitti; yerine bağımsız
  ölçüme dayanan **"9B decode'u kendi konfigürasyonunun bellek tavanının
  %92'sinde çalışıyor ve ≥%93 akış-baskın"** geldi. Bu, iki noktalı bir
  fit'ten değil doğrudan ölçümden geliyor.
- Raporun geri kalanı bu sayıya bağlı değil: asimetri bulgusu (prefill
  %83 / decode %63 ölçeklenme verimi) doğrudan ölçüm, fit değil.

İki noktalı fit'in kendisi bu iş için yeterince kısıtlı değildi: iki
bilinmeyeni iki gözlemle çözerken hata doğrudan sonuca geçiyor ve
sonucun fiziksel olarak mümkün olup olmadığı kontrol edilmemişti. Bu,
aynı hesabın **ikinci** başarısızlığıdır.

---

## 11.8 U8 — `chrt --idle` tavsiyesi gerçek işe genelleniyor mu?

**İtiraz:** §0'ın "bugün kullanılabilecek tek satırlık tavsiyesi"
(`chrt --idle`) yalnızca sentetik `loadgen` ile ölçülmüştü ama "arka plan
işi" diye genelleniyordu. Gerçek bir build fork eder, I/O'da bloke olur,
link aşamasında serileşir — SCHED_IDLE'ın kazancı uyanma-preemption'ından
geliyorsa etki farklı çıkabilirdi.

**Ölçüm:** §11.2'nin deneyinde, LLM kolu SWITCH sabit, rakibin önceliği
değişken. Rakip: pencere boyunca döngüde `make -j16`.

| | TTFT | ITL p50 | ITL p95 | tps | rakip hız |
|---|---|---|---|---|---|
| SWITCH (normal) | 12 594 | 109.88 | 250.52 | 7.78 | 0.3378 |
| **SWITCH + `chrt --idle`** | **11 268** | **98.19** | **191.60** | **8.93** | 0.2863 |
| SWITCH + CPUWeight=1 | 12 538 | 110.24 | 252.98 | 7.71 | 0.3360 |

`chrt --idle`'ın SWITCH'e göre farkı (taban: bu senaryonun kol-içi CV'si):

| metrik | fark | taban | karar |
|---|---|---|---|
| TTFT | −%10.53 | %1.06 | **gerçek** |
| ITL p50 | −%10.63 | %0.55 | **gerçek** |
| **ITL p95** | **−%23.52** | %1.51 | **gerçek, büyük** |
| decode tps | +%14.76 | %0.80 | **gerçek** |
| rakip hız | **−%15.23** | %2.34 | **gerçek maliyet** |

**Tavsiye genelleniyor — hem de güçlü biçimde.** Sentetik loadgen'de
görülen etki gerçek bir build'de de var: p95 %23.5 düzeliyor. Üstelik
bedeli sentetik rakiptekinden **çok daha ucuz**: rakip %15.2 yavaşlıyor,
loadgen'de bu ~%55'ti. Sebebi makul: gerçek build zaten bloke olduğu için
SCHED_IDLE'ın elinden aldığı zaman daha az.

**CPUWeight=1 ise genellenmiyor.** Tüm metriklerde ≤%1, hepsi taban
içinde — gerçek build'de **hiçbir şey yapmıyor**. Oysa sentetik yükte ITL
boşluğunun %49'unu alıyordu. Bu, raporun daha önce kurduğu ayrımı
bağımsız olarak doğruluyor ve keskinleştiriyor: cgroup ağırlığı bir
*throughput payı* kısıtıdır, *gecikme önceliği* değil. Sentetik,
always-runnable bir yükte ikisi karışabiliyor; bloke olan gerçek bir
yükte ayrışıyor ve ağırlığın işe yaramadığı görülüyor.

**§0'daki ara-nokta önerisi (`CPUWeight=1`) bu ölçümle geri
çekilmiştir.**

---

## 11.9 R8 — GGML_OPENMP=OFF

Bu madde önceki oturumda ölçüldü ve §2.5'e işlendi; burada yalnızca
tamlık için tekrarlanıyor.

| | OpenMP | spin-wait |
|---|---|---|
| ctx/koşu | 2 032 021 | **820** |
| ayrışma | 10.2× | **yok** |
| dedektör tetiklendi | 6/6 | **0/6** |

Sinyal 2 500 kat düşüyor ve dedektör hiç tetiklenmiyor. En büyük kapsam
çekincesi tahmin olmaktan çıkıp **ölçüm** oldu: yöntem, bariyerde bloke
olan (futex) runtime'lara bağlıdır. Spin-wait derlemenin kendi maliyeti
de ölçüldü: TTFT −%2.2, ITL p95 +%16.2, decode −%4.3.
