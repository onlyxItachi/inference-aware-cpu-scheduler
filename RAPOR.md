# LLM-Aware Scheduling — Oturum Raporu

**Tarih:** 2026-07-18
**Donanım:** Intel i7-14650HX (8 P-core / 8 E-core, 24 thread), 32 GB DDR5,
CachyOS kernel 7.1.3-2-cachyos
**Model:** Qwen3.5-9B-Q4_K_M, 5 680 522 464 bayt,
sha256 `03b74727a860a56338e042c4420bb3f04b2fec5734175f4cb9fa853daf52b7e8`
**llama.cpp:** commit `571d0d540df04f25298d0e159e520d9fc62ed121`,
CPU-only, GCC 16.1.1, `-march=native` (AVX2; bu CPU'da AVX-512 yok)
**Toplam ölçüm:** 158 koşu, hepsi interleaved veya tek-konfigürasyon tekrar

---

# BÖLÜM 1 — Orijinal prompt tamamlandı mı?

**Evet, tamamı.** Madde madde:

## ADIM 1 — Harness

| istenen | durum | nerede |
|---|---|---|
| llama.cpp CPU-only derle | ✅ | CUDA/BLAS/Vulkan kapalı, `libggml-cpu` tek backend |
| derleme bayrakları + commit hash kaydı | ✅ | `results/phase0/env.txt` |
| 7-8B Q4_K_M model + SHA | ⚠️ **sapma** | 9B kullanıldı, SHA kayıtlı (aşağıda) |
| llama-bench değil, llama-server SSE streaming | ✅ | `harness/run_once.py` |
| token başına zaman damgası | ✅ | `results/*/tokens/*.json` |
| `ttft_ms` | ✅ | CSV |
| `itl_p50 / p95 / p99_ms` | ✅ | CSV |
| `itl_max_ms` | ✅ | CSV |
| `decode_tps` | ✅ | CSV |
| ham token zaman damgası dizisi, ayrı dosyaya | ✅ | `tokens/run_XX.json` |
| paket sıcaklığı (koşu başı/sonu) | ✅ | `temp_start_c`, `temp_end_c` |
| koşu boyunca ortalama CPU frekansı | ✅ | `freq_p_avg_mhz`, `freq_p_busy_mhz`, `freq_e_avg_mhz` |
| thread migration + context switch sayısı | ✅ | ⚠️ `perf` ile değil (aşağıda) |
| sadece inference process'ini izle | ✅ | sunucu PID'inin thread'leri |
| sabitler: prompt, token sayısı, seed, thread, batch | ✅ | hepsi her CSV satırında |

## ADIM 2 — Gürültü tabanı

| istenen | durum |
|---|---|
| tek konfigürasyon (pinsiz, `--threads 8`, boş sistem) × 20 | ✅ 20/20 başarılı |
| koşular arası 30 sn bekleme | ✅ |
| ttft + itl_p95 için medyan/std/min/max/CV | ✅ |
| koşu numarasına karşı ttft grafiği, drift var mı | ✅ ASCII + SVG |
| sıcaklık–sonuç korelasyonu | ✅ Pearson r, n=20 için p<0.05 eşiği 0.444 |
| tek cümlelik sonuç | ✅ **"%2'den küçük farklar gürültüdür"** |

## Kurallara uyum

- `scxctl` / scheduler yükleme komutu **çalıştırılmadı**
- ölçüm sırasında başka şey çalıştırılmadı; VS Code kapatıldı, her koşu
  öncesi sistem yükü doğrulandı
- ADIM 2 bitmeden başka konfigürasyon ölçülmedi
- yorumlar yalnızca ölçülen sayıya dayandırıldı; varyans ve belirsizlikler
  gizlenmedi (aşağıdaki "çürütülen hipotezler" bölümü bunun kanıtı)

---

# BÖLÜM 2 — İki bilinçli sapma

## Sapma 1: Model 7-8B değil, 9B

Sen indirmeyi durdurdun (telefon interneti). Sendeki
`Qwen3.5-9B-Q4_K_M` kullanıldı; benim indirdiğim yarım dosyalar silindi.

**Etkisi:** olumlu. Daha büyük model token başına daha fazla bellek trafiği
üretir, yani K1'in bant genişliği sorusunu daha net test eder. Model
projenin tamamı için sabitlendi, SHA kayıtlı.

## Sapma 2: `perf` yerine `/proc/<tid>/sched`

`perf` bu makinede kurulu değil. Kurmak yerine migration ve context switch
sayıları `/proc/<pid>/task/<tid>/sched` içindeki `se.nr_migrations` ve
`nr_switches` alanlarından okundu.

**Neden bu daha iyi:** root istemiyor, tracing overhead'i eklemiyor, ve
process başına değil **thread başına** sayı veriyor — H1/H3'ün gerektirdiği
granülerlik bu. Ayrıca hiçbir paket kurulmadı; harness tamamen Python
stdlib.

---

# BÖLÜM 3 — Promptun ötesine eklenenler

Hepsi senin yönlendirmenle, sırayla:

| # | deney | koşu | soru |
|---|---|---|---|
| 1 | **Affinity sweep** | 50 | 5 yerleşim varyantı, interleaved |
| 2 | **E1 residency** | 3 | migration'lar topolojik olarak nereye gidiyor? |
| 3 | **E2 SMT izolasyon** | 24 | migration patlaması SMT'den mi çekirdek sayısından mı? |
| 4 | **K1 thread taraması** | 30 | decode çekirdek eklemekle nerede doyuyor? |
| 5 | **S2 çekişme** | 24 | rakip iş yükü altında ne oluyor? |
| 6 | **S2 v2** | 24 | rakip ne kaybediyor? (çift taraflı muhasebe) |

Ayrıca yazılan araçlar: `thread_residency.py` (topoloji-farkındalıklı
yerleşim örnekleyici), `loadgen.c` (tekrarlanabilir, iş sayacı olan rakip
yük üreteci), ve her deney için ayrı analiz scripti.

**Metodolojik ekleme:** Faz 0'da bulunan drift yüzünden 1., 3., 4., 5., 6.
deneylerin tamamı **interleaved** koşuldu — her tur tüm kollar bir kez,
karıştırılmış sırayla. Blok halinde ölçülseydi drift kollar arasında ~%0.8
sahte fark üretecekti.

---

# BÖLÜM 4 — Sonuçlar

## 4.1 Gürültü tabanı: %2 (ADIM 2'nin cevabı)

| metrik | medyan | CV | %95 bandı |
|---|---|---|---|
| TTFT | 12 127.7 ms | 0.5% | ±0.9% |
| ITL p50 | 98.07 ms | 0.5% | ±1.1% |
| ITL p95 | 103.52 ms | 0.7% | ±1.4% |
| decode | 10.17 tok/s | 0.5% | ±1.1% |

CLAUDE.md K3'te laptop varyansının %10'u aşabileceğinden endişe ediliyordu.
Ölçülen %0.5–1.5. **Korkulan senaryo gerçekleşmedi** ve manevra alanı
beklenenden geniş.

**Ama açıklanamayan bir drift bulundu.** TTFT koşu numarasıyla r=+0.671
korele (n=20 için eşik 0.444). İlk 10 → son 10: TTFT +0.74%, ITL p95
+0.84%, decode −0.78% — üç metrik de aynı yönde.

Doğal açıklama termal olurdu; **değil**. Başlangıç sıcaklığıyla hiçbir
metrik anlamlı korele değil (|r| < 0.25). Sıcaklık 20 koşuda 57→60°C'ye
çıktı, o kadar. Sebep bu veriyle bilinmiyor ve tahmin edilmedi.

Sonucu: 30 saniyelik soğuma payının yeterli olduğu varsayımı yanlış;
konfigürasyonlar blok halinde ölçülemez.

## 4.2 P-core'a pinlemek Linux'un varsayılanını yeniyor

50 koşuluk interleaved affinity sweep, pinsiz baseline'a karşı:

| varyant | TTFT | ITL p50 | ITL p95 | decode |
|---|---|---|---|---|
| **P-core (16 mantıksal)** | **−9.2%** | **−12.7%** | **−16.0%** | **+14.4%** |
| P-core (8 fiziksel) | −9.1% | −12.8% | −12.8% | +14.0% |
| 4 fiziksel P + SMT | +47.7% | +8.2% | +3.8% | −7.4% |
| sadece E-core | +106.8% | +126.7% | +118.1% | −55.7% |

Hepsi p<0.01 ve eşiğin 4–60 katı. Linux 8 thread'i 16 fiziksel çekirdeğe
(P **ve** E) yayıyor; sadece P-core'da tutmak %14 throughput getiriyor.

E-core cezası devasa: decode yarıdan fazla düşüyor. (Not: E-only aynı
zamanda en serin koşu — bitiş 67°C, diğerleri 78–86°C. Enerji cephesinde
ölçülmeye değer.)

## 4.3 Migration sayısı yanlış metrik — üç bağımsız deneyde

Bu, oturumun en sağlam metodolojik bulgusu.

**Gözlem:** `p_smt_forced` 1 027 373 migration yapıyor ve **en kararlı**
gecikmeyi veriyor (ITL CV %0.5). `unpinned` 8 053 migration ile **en
dalgalısı** (CV %3.6).

**Kesin test (E2):** aynı 4 fiziksel çekirdek üzerinde migration'ı
626 → 1 029 926'ya (**1644 kat**) çıkardık:

| metrik | 626 migration | 1.03M migration | fark |
|---|---|---|---|
| TTFT | 17 974 | 17 668 | **−1.7%** |
| ITL p50 | 108.24 | 106.53 | **−1.6%** |
| ITL p95 | 117.31 | 107.55 | **−8.3%** |
| decode | 9.05 | 9.38 | **+3.7%** |

Migration 1644 kat arttı, **her metrik iyileşti**.

Belirleyici değişken çekirdek sayısı: 4 → 8 fiziksel çekirdek TTFT'yi
%38.1 iyileştiriyor, decode'u %23.8 artırıyor.

**H3'ün naif hali ("migration sayısı token gecikmesini bozar") bu veriyle
reddedilir.** S2'de üçüncü kez doğrulandı: en çok migration'a sahip kol
(C, 121 632) aynı zamanda en kötü kuyruğa sahip, ama en az migration'a
sahip kol (A, 3 739) ile en iyi kol arasında migration farkı sıralamayı
açıklamıyor.

## 4.4 Prefill/decode asimetrisi — projenin merkezi hipotezi

K1, thread başına bir fiziksel P-core ile 2→4→6→8 çekirdek:

| kol | çekirdek | prefill tok/s | decode tok/s |
|---|---|---|---|
| t2 | 2 | 14.8 | 5.96 |
| t4 | 4 | 27.5 | 9.02 |
| t6 | 6 | 37.4 | 10.70 |
| t8 | 8 | 45.2 | 11.60 |
| t16 | 8 (16 thread) | 45.7 | 11.37 |

**2 → 8 çekirdekte prefill verimi %77, decode verimi %49 — 28 puan fark.**

Marjinal getiriler:

| geçiş | prefill | decode |
|---|---|---|
| t2 → t4 | +86.6% | +51.5% |
| t4 → t6 | +35.9% | +18.6% |
| t6 → t8 | +20.8% | **+8.4%** |
| t8 → t16 (SMT) | +1.0% | −1.9% |

Decode'un getirisi her adımda prefill'inkinin yaklaşık yarısı ve daha hızlı
sönüyor. **İki faz çekirdek eklemeye farklı tepki veriyor** — CLAUDE.md'nin
merkezi hipotezinin aradığı asimetri, tek değişken oynatılarak ölçülmüş
hâliyle.

**Eyleme dönük sayı:** decode'a 8 yerine 6 çekirdek vermek %7.8'e mal olur;
prefill'e 6 yerine 8 vermek +20.8% kazandırır. Prefill geniş, decode dar
istiyor.

**K1'in "neden"i cevaplanmadı.** İma edilen bellek trafiği t8'de ~66 GB/s
(DDR5 tavanına yakın), ama bu bandwidth-bound açıklamasıyla sadece
*tutarlı*. En az iki aday var ve bu veri ayırt etmiyor: (a) bant genişliği
tavanı, (b) OpenMP bariyer maliyeti (koşu başına ~2.1M context switch,
token başına ~8200). Ayırt edici test küçük bir modelle (3B) aynı taramayı
tekrarlamak — indirme gerektirdiği için ertelendi.

## 4.5 Çekişme altında: kazandıran hamle "izole et" değil "tahliye et"

S2, 16 always-runnable rakip thread ile:

| kol | LLM | yük | TTFT | ITL p95 | decode |
|---|---|---|---|---|---|
| A | P-core | yok | referans | referans | referans |
| B | serbest | serbest | +61.4% | +15.2% | −14.6% |
| C | P-core | serbest | +61.6% | **+38.0%** | −20.5% |
| D | P-core | E-core | **+5.0%** | **−1.0%** | **−1.6%** |

**D, çekişme hasarının %89–112'sini geri alıyor.** 16 rakip thread, LLM
açısından neredeyse bedava hale geliyor; kuyruk gecikmesi boştaki
makineden istatistiksel olarak ayırt edilemiyor. Faz tespiti, uyarlama, ML
gerekmedi.

**Beklenmedik ters etki:** C (LLM'i P-core'a pinle, yükü serbest bırak)
varsayılandan **kötü** — kuyrukta açığı kapatmıyor, %150 büyütüyor. LLM
pinlenince kaçamıyor, yük de P-core'lara yerleşiyor.

Politika tasarımı için sonucu: *"önemli thread'i iyi çekirdeğe koy"* diye
yazılan bir scheduler C'yi üretir ve işleri kötüleştirir. Doğru
formülasyon *"önemsiz thread'i iyi çekirdekten çıkar"*. İkisi sezgisel
olarak aynı görünüyor, ölçümde zıt.

## 4.6 Ama D bedava değil — çift taraflı muhasebe

S2 v2'de yükün kendi iş hızı da ölçüldü:

| kol | yük it/s | serbest referansa | kendi yerleşim referansına |
|---|---|---|---|
| B | 38 707 | %85 | %85 |
| C | 38 887 | %86 | %86 |
| D | 17 954 | **%40** | %90 |

D'nin rakibe maliyeti neredeyse tamamen **yerleşimden** geliyor (yük
E-core'da kendi tavanının %90'ını tutuyor; E-core tavanı serbestin %44'ü).
Yani D verimsiz değil, rakibe daha küçük bir kaynak veriyor.

Her iki tarafı kendi çekişmesiz tavanına normalize edip eşit ağırlıkla
toplarsak:

| kol | LLM | yük | toplam |
|---|---|---|---|
| B (Linux varsayılanı) | 85.4% | 85.4% | **170.9%** |
| C | 79.5% | 85.8% | 165.3% |
| D | **98.4%** | 39.6% | **138.0%** |

**Bu ölçüte göre Linux'un varsayılanı en iyisi, D en kötüsü.** D, LLM'e 13
puan kazandırmak için yükten 46 puan alıyor.

**D bir kazanç değil, bir öncelik kararıdır** — ve hangi tarafın ağır
bastığına ölçüm karar veremez. LLM etkileşimliyse ve rakip toplu işse
savunulabilir. Eşit ağırlıklı toplam da tek doğru ölçüt değil: enerjiyi
saymıyor, gecikmeyi throughput'a çeviriyor.

## 4.7 Faz 3'ün ölçülmüş gerekçesi

Statik D'nin zayıflığı: decode fazında LLM'in ihtiyacı olmayan çekirdekleri
de tutuyor. K1'in sayıları buraya oturuyor — decode'a 8 yerine 6 çekirdek
vermek yalnızca %7.8'e mal olur, prefill'e 8 vermek +20.8% kazandırır.

**Faz-farkındalıklı bir politika statik D'yi yenebilir:** prefill'de geniş,
decode'da dar, boşalan çekirdekler rakibe geri verilir. Statik pinning
bunu yapamaz çünkü fazı görmez.

Bu, Faz 3'ün statik Faz 2'nin üstüne neden değer kattığına dair **ölçülmüş**
argümandır. Ve iddianın biçimi önemli: "LLM'i hızlandırdım" değil,
**"aynı önceliği daha ucuza sağlayabilirim"**.

---

# BÖLÜM 5 — Çürütülen hipotezler

Bu bölüm bilerek ayrı tutuluyor. Oturumda dört hipotez çürütüldü, üçü
benimdi.

| # | hipotez | çürüten | ne oldu |
|---|---|---|---|
| 1 | "1M migration çoğunlukla bedava kardeş-içi sekmedir" | E1 | Geçişlerin **%85'i fiziksel çekirdek aşırı**. Migration'lar gerçekten pahalıydı. |
| 2 | "Patlamanın sebebi SMT kardeşlerinin varlığı" | E2 | Sibling'in hiç olmadığı kolda da 668 632 migration çıktı. Sebep: **thread sayısı > fiziksel çekirdek**. |
| 3 | "Prefill migration'a decode'dan 2.6 kat duyarlı" | E2 | TTFT cezası migration'dan değil **çekirdek sayısından** geliyordu. İki değişken aynı anda değişmişti. |
| 4 | H3'ün naif hali: "migration sayısı token gecikmesini bozar" | E2 + S2 | Migration 1644 kat artınca her metrik **iyileşti**. |

3 numaralı hata öğreticiydi: `p_smt_forced` kolu çekirdek sayısı **ve** SMT
paylaşımını birlikte değiştiriyordu, ben cezayı yanlış değişkene atfettim.
E2 tam bu ayrımı yapmak için tasarlandı. Sonra K1, aynı asimetriyi
karıştırıcısız (tek değişken: çekirdek sayısı) yeniden kurdu — bu kez
sağlam.

Bunlar `results/*/FINDINGS.md` içinde silinmedi, **üstü çizili olarak
bırakıldı**.

---

# BÖLÜM 6 — Açık kalanlar

| konu | neden açık | ne gerekiyor |
|---|---|---|
| **K1'in mekanizması** | bandwidth vs senkronizasyon ayrışmadı | 3B model ile aynı tarama (indirme gerekir) |
| **H5 — faz tespiti** | hiç test edilmedi; **tüm mimarinin dayandığı varsayım** | dışarıdan gözlemle prefill/decode ayırt edilebiliyor mu? |
| **H1'in temiz testi** | E-core cezası ölçüldü ama migration etkisinden ayrıştırılmadı | decode'u koşu ortasında E'ye taşıyan deney |
| **H2 — prefill/decode girişimi** | ölçülmedi | eşzamanlı prefill + decode |
| **scx_lavd / scx_rustland** | **senin onayın gerekiyor** (CLAUDE.md kural 6) | scheduler yükleme |
| **S3–S6** | ölçülmedi | tarayıcı, çoklu örnek, indeksleme, termal |
| **Enerji** | hiç ölçülmedi | E-core'lar daha verimli; D'nin enerji görünümü throughput görünümünden iyi olabilir |
| **Gerçekçi yük** | `loadgen` sentetik ve compute-bound | `make -j` I/O + bellek davranışı da gösterir |

**En kritik açık: H5.** CLAUDE.md bunu kritik varsayım olarak işaretlemiş
ve haklı — faz-farkındalıklı mimarinin tamamı, userspace daemon'ın fazı
dışarıdan ayırt edebilmesine dayanıyor. Eğer bu sadece llama.cpp'yi
enstrümante ederek mümkünse, katkının adı değişir: "OS iş yükünü anlıyor"
değil, "uygulama OS'a ipucu veriyor" olur.

Bu oturumda H5'e dair bir **ipucu** var: decode ve prefill arasında context
switch ve migration desenleri belirgin farklı. Ama bu bir gözlem, test
değil.

---

# BÖLÜM 7 — Dosya haritası

```
harness/
  bench_lib.py           sensörler, sched sayaçları, frekans, istatistik
  run_once.py            tek koşu: sunucu + SSE + token zaman damgaları
  noise_floor.py         ADIM 2: N tekrar
  affinity_sweep.py      5 varyant interleaved
  e1_residency.py        topoloji-farkındalıklı yerleşim örnekleme
  e2_smt_isolate.py      SMT vs çekirdek sayısı ayrımı
  k1_thread_scan.py      2→4→6→8 çekirdek taraması
  s2_contention.py       rakip yük altında
  thread_residency.py    /proc tabanlı CPU yerleşim örnekleyici
  loadgen.c              tekrarlanabilir rakip yük, iş sayaçlı
  analyze*.py            her deney için ayrı analiz
  prompt_512.txt         sabit prompt, 496 token
  record_env.sh          commit, bayraklar, model SHA, CPU durumu

results/
  phase0/                ADIM 2: gürültü tabanı (20 koşu) + env.txt
  phase0_affinity/       affinity sweep (50 koşu)
  e1_residency/          topoloji sınıflandırması
  e2_smt/                SMT izolasyonu (24 koşu)
  k1_threads/            thread taraması (30 koşu)
  s2_contention/         çekişme v1 (24 koşu)
  s2_v2/                 çekişme v2, çift taraflı (24 koşu) + load_baseline.md
```

Her `results/*/` altında: ham CSV, token zaman damgaları, otomatik rapor,
ve elle yazılmış `FINDINGS.md`.

---

# Tek paragraflık özet

Orijinal promptun tamamı tamamlandı: harness kuruldu, doğrulandı (TTFT
sunucunun kendi ölçümüyle 30 ms içinde uyuşuyor), ve gürültü tabanı **%2**
olarak belirlendi. Üstüne 155 koşuluk beş deney eklendi. En sağlam
sonuçlar: **P-core'a yerleştirme Linux varsayılanına karşı decode'da +14%**;
**migration sayısı bu iş yükünde hiçbir şey öngörmüyor** (1644 kat artırıldı,
her metrik iyileşti — H3 yeniden yazılmalı); **prefill ve decode çekirdek
eklemeye farklı tepki veriyor** (%77'ye karşı %49 verim), ki bu projenin
merkezi hipotezinin aradığı asimetridir; ve **çekişme altında rakibi
E-core'a sürmek LLM hasarının %89–112'sini geri alıyor**, ancak rakibe
throughput'unun %60'ına mal oluyor — yani bir kazanç değil, bir öncelik
kararı. Bu son sayı Faz 3'ün gerekçesini veriyor: faz-farkındalıklı bir
politika, decode fazında çekirdek iade ederek aynı önceliği daha ucuza
sağlayabilir. Yolda dört hipotez çürütüldü, üçü benimdi; hepsi kayda
geçirildi. En kritik açık soru H5 — faz tespitinin uygulamadan yardım
almadan mümkün olup olmadığı, ki tüm mimari ona dayanıyor.
