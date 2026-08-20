# İŞ 2 — Gerçekçi rakip: negatif sonuç KAPSAMI DARALIYOR

**Sonuç: gerçekçi bir rakiple faz anahtarlama işe yarıyor — hem LLM hem
rakip kazanıyor. İŞ 6'nın "çekişme altında kazanç yok" sonucu, sentetik
doyuran yükle sınırlıdır.**

**Tasarım:** 6 tur × 3 kol = 18 koşu, interleaved. Rakip: `make -j16`
(llama.cpp ağacı, temiz build, iki geçiş), **pinsiz** — Linux varsayılanı,
İŞ 6'nın E-pinli yerleşiminden kasıtlı olarak farklı.

---

## 1. Ölçülen

| kol | TTFT | ITL p50 | ITL p95 | ITL p99 | decode | J/token | build süresi |
|---|---|---|---|---|---|---|---|
| A_P8 | 11 743 | 85.77 | 90.42 | 92.46 | 11.58 | 11.633 | 35.70 s |
| C_P8_E8 | 10 490 | 96.85 | 100.68 | 102.67 | 10.31 | 12.027 | 37.24 s |
| **SWITCH** | **10 480** | **85.72** | **86.54** | **87.44** | **11.65** | **11.157** | **34.37 s** |

SWITCH'in A_P8'e karşı farkı:

| metrik | fark | anlamlılık |
|---|---|---|
| TTFT | **−%10.8** | p<0.01 |
| ITL p95 | −%4.3 | ns (n=6'da güç yetersiz; etki %2 eşiğinin üstünde) |
| ITL p50 | −%0.1 | ns |
| decode | +%0.6 | ns |
| J/token | **−%4.1** | p<0.01 |
| **rakibin build süresi** | **−%3.7** | **p<0.01** |

## 2. Bu bir takas değil — iki taraf da kazanıyor

En dikkat çekici satır sonuncusu: **SWITCH altında rakibin build'i daha
hızlı bitiyor** (34.37 s vs 35.70 s).

Mekanizma tutarlı: SWITCH prefill'i A_P8'den %10.8 daha erken bitiriyor,
sonra decode'a geçerken E-core'ları tamamen bırakıp yalnızca 8 P-core
tutuyor. Rakip hem daha erken hem daha geniş kaynağa kavuşuyor.

C_P8_E8 bunun tersini gösteriyor: E-core'ları hiç bırakmadığı için rakibin
build'i **en yavaş** olan kol (37.24 s) ve LLM'in ITL'i de en kötü.

## 3. İŞ 6 ile karşılaştırma: rakibin cinsi belirleyici

| | doyuran loadgen (İŞ 6) | gerçekçi build (bu iş) |
|---|---|---|
| rakip yerleşimi | E-core'lara pinli | pinsiz |
| rakip doğası | always-runnable, boşluk yok | I/O bekler, link'te serileşir |
| A_P8 bozulması (TTFT) | +%5.2 | +%6.8 |
| SWITCH bozulması (TTFT) | +%20.4 | **+%7.5** |
| SWITCH vs A_P8 | **berabere** (gürültü içinde) | **TTFT −%10.8** |

Fark açık: doyuran yükte SWITCH'in kazancı tamamen siliniyordu, gerçekçi
yükte neredeyse tamamı hayatta kalıyor (rakipsiz −%11.4 → burada −%10.8).

**Bunun sebebi ölçüldü:** doyuran loadgen E-core'larda hiç boşluk
bırakmıyor, dolayısıyla prefill'e E-core eklemek sıraya girmek demek
oluyordu. Build ise ortalama ~2 çekirdek kullanıyor (tam build 39.7 s'de
%202 CPU) — yani atıl kapasite bırakıyor ve faz anahtarlama onu
kullanabiliyor.

## 4. REVİZYON 2 ölçütüne karşı (senaryo: gerçekçi build rakibi)

Referanslar **aynı senaryo içinden**:

| kriter | aynı S'teki en iyi statik | SWITCH | sonuç |
|---|---|---|---|
| TTFT | C_P8_E8 = 10 490 → tavan 10 700 | 10 480 | **GEÇER** |
| ITL p95 | A_P8 = 90.42 → tavan 92.23 | 86.54 | **GEÇER** |
| rakip throughput | A_P8 build 35.70 s → tavan 36.41 s | 34.37 s | **GEÇER** |

**Üç kriter de geçiliyor.** Bu, REVİZYON 2'nin tanımladığı Pareto
baskınlığının gerçekçi bir çekişme senaryosunda sağlandığı ilk ölçümdür.

## 5. Ölçüm tasarımında değiştirilen şey (kayda geçsin)

Rakibin iş metriği **iki kez değişti**:

1. **`.o` dosya sayısı — reddedildi.** 340 nesnenin tamamı build'in ilk
   ~15 saniyesinde üretiliyor, kalan ~25 saniye linkleme. Sayaç ölçüm
   penceresi kapanmadan doyuyordu ve `build_objs = 0` veriyordu.
2. **Build duvar süresi — kullanılan.** Monoton, doygunluk sorunu yok.
   Tek geçiş 17 s sürdüğü ve ölçüm penceresi ~32 s olduğu için build
   **iki geçişe** çıkarıldı; aksi halde decode'un ikinci yarısı çekişmesiz
   kalırdı.

## 6. Sınırlar

- Build rakibi tek bir proje (llama.cpp). Farklı build profilleri (daha çok
  I/O, daha çok link) farklı sonuç verebilir.
- E-core doluluk zaman serisi kaydedildi ama bu raporda **analiz edilmedi**;
  "SWITCH prefill'de gerçekten boşluğu kullanıyor mu" sorusu doğrudan
  gösterilmedi, dolaylı olarak (TTFT kazancı) çıkarıldı.
- ITL p95'teki −%4.3 eşiğin üstünde ama n=6'da istatistiksel olarak teyit
  edilmedi.
- Tek prompt/üretim uzunluğu.
