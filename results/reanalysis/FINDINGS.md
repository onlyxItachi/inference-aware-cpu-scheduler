# KOVA 1 — yeniden analiz (yeni koşu yok)

Üç madde, tamamı mevcut telemetriden. Scriptler: `harness/a14_leadscale.py`,
`harness/a15_detector_eval.py`.

---

## 1a / U4 — erken uyarı × çekirdek sayısı

**Kullanılan veri:** `results/h5_cores` ve `results/h5_promptlen`
(5 prompt uzunluğu × 4 koşu). c4 ve c8 n=3'ten **n=6'ya çıkarıldı** (bu
tek amaç için 6 ek koşu); c6 n=3'te kaldı, 4→8 karşılaştırması onu
kullanmıyor.

### Ölçülen

Çekirdek sayısı taraması (prompt sabit, 496 token):

| çekirdek | n | TTFT (prefill) | ITL (decode) | erken uyarı | erken/ITL |
|---|---|---|---|---|---|
| 4 | 6 | 18 362 ms | 109.8 ms | **208.8 ms** | 1.90 |
| 6 | 3 | 13 311 ms | 94.0 ms | **150.4 ms** | 1.60 |
| 8 | 6 | 11 023 ms | 86.8 ms | **134.9 ms** | 1.55 |

Oran grupları n=6'da da örtüşmüyor (4 çekirdek 1.71–1.97, 8 çekirdek
1.45–1.62), yani oranın çekirdek sayısıyla değişmesi gerçek.

Prompt uzunluğu taraması (çekirdek sabit, 8):

| prompt | TTFT | erken uyarı | erken/TTFT | erken/ITL |
|---|---|---|---|---|
| 32 | 880 ms | 131.6 ms | %14.94 | 1.53 |
| 128 | 2 885 ms | 133.7 ms | %4.63 | 1.55 |
| 256 | 5 665 ms | 139.3 ms | %2.46 | 1.62 |
| 496 | 10 907 ms | 132.8 ms | %1.22 | 1.54 |
| 1024 | 22 687 ms | 139.2 ms | %0.61 | 1.61 |

### İki değişmez

1. **Erken uyarı prompt uzunluğundan bağımsız.** TTFT 26 kat değişirken
   (880 → 22 687 ms) erken uyarı 132–139 ms'de kalıyor; yayılım %5.7.
   Yani sabit miktarda bir işe karşılık geliyor, prefill'in bir oranına
   değil.
2. **Ama çekirdek sayısına bağımlı, ve decode gibi DEĞİL ölçekleniyor.**
   4→8 çekirdek (2× kaynak):

   | | hızlanma | verim |
   |---|---|---|
   | prefill (TTFT) | 1.666× | **%83** |
   | decode (ITL) | 1.265× | %63 |
   | **erken uyarı** | 1.547× | **%77** |

   *Not: n=3'lük ara analizde erken uyarı %82 çıkmış ve prefill'le özdeş
   görünmüştü. n=6'da %77'ye indi — prefill'e yakın ama onunla AYNI
   değil. Aşağıdaki karar bu farka değil, decode'dan (%63) ayrı
   olmasına dayanıyor.*

### Karar

Kullanıcının koyduğu iki dalın **ikisi de kapanıyor**:

* **"Erken uyarı mutlak olarak sabit" → ELENDİ.** 209 → 135 ms, yayılım
  %45. Dedektör artefaktı değil, gerçek bir işi ölçüyor.
* **"Oran sabit, yani bölge decode-şeklinde" (§8 hipotezi) → ELENDİ.**
  Oran sabit değil (1.90 → 1.55, örtüşmeyen gruplar). Daha belirleyicisi:
  bölge decode gibi (%63) değil **%77 verimle** ölçekleniyor. Bölge
  gerçekten decode-şeklinde olsaydı decode'un ölçeklenme verimini
  gösterirdi; göstermiyor.

**Yani yer-gerçeği tanımı yanlış yerde DEĞİL.** Erken tetikleme gerçekten
erken: dedektör, hâlâ prefill-şeklinde hesap yapılırken karar veriyor.
§8'in "kurtarma" açıklaması ölçümle çürütüldü.

### Mekanizma hakkında ne biliyoruz

Kapalı olmayan tek şey mekanizma, ama arama uzayı daraldı. Aranan şey:
**prompt uzunluğundan bağımsız, sabit büyüklükte, %77 verimle
paralelleşen (yani decode'un %63'ünden belirgin iyi), prefill'in en
sonunda yapılan bir iş.**

Test EDİLMEMİŞ bir aday: son katman / çıkış projeksiyonu (lm_head),
llama.cpp'de prefill sırasında yalnızca son pozisyon için hesaplanır —
prompt uzunluğundan bağımsız ve büyük bir paralel GEMM'dir. Bu bir
tahmindir, ölçülmedi; U4'ün kapanışı bu adaya bağlı değil.

---

## 1b / U9 — precision, FP ve held-out

**Kullanılan veri:** 12 konfigürasyon, 49 koşu (h5, h5_cores,
h5_contention, h5_promptlen) + 30 tur (i11_multiturn).

### Eşik nereden seçildi, nerede değerlendirildi

Eşikler (hi=3000, lo=2100, k=2) **h5 ailesinden** (pinned/unpinned,
10 koşu) seçildi. Kalan 10 konfigürasyon (39 koşu) eşik seçiminde
kullanılmadı → held-out olarak değerlendirilebilir.

### Örnek düzeyinde (yer-gerçeği: ilk token)

| | recall | precision | uzak FP/koşu | fazla geçiş/koşu |
|---|---|---|---|---|
| tümü (49 koşu) | %100.00 | %99.38 | **0.00** | **0.00** |
| held-out (39 koşu, 10 konfig) | %100.00 | %99.36 | 0.00 | 0.00 |

**Kritik ayrım:** FP'lerin **tamamı sınıra bitişik** (≤300 ms). Sınırdan
uzak tek bir FP yok, 49 koşunun hiçbirinde. Yani precision'daki %0.62'lik
açık gürültü değil, erken tetiklemenin kendisi — 1a'da ölçülen ~130 ms,
20 ms örnekleme periyodunda ~6-7 örnek eder ve gözlenen FP sayısı tam
olarak budur.

Salınım da yok: 49 koşuda toplam **sıfır** fazla durum geçişi.

### Eşik duyarlılığı

±%30 tamamen düz (recall %100, precision %99.38, hiçbir metrikte değişim
yok). Bu, eşiğin iyi seçildiğini değil, **±%30'un çalışma penceresinin
çok içinde kaldığını** gösterir. Gerçek pencereyi bulmak için tarama
genişletildi:

| hi | recall | precision | uzak FP/koşu | fazla geçiş | erken uyarı |
|---|---|---|---|---|---|
| 300 | %100.00 | %96.71 | 26.98 | **16.45** | −10 838 ms (çöp) |
| 1 000 | %100.00 | %99.11 | 2.04 | 0.04 | −121 ms |
| 2 100 | %100.00 | %99.37 | 0.00 | 0.00 | −118 ms |
| **3 000** | %100.00 | %99.38 | 0.00 | 0.00 | −118 ms |
| 5 000 | %99.99 | %99.45 | 0.00 | 0.00 | −113 ms |
| 8 000 | %99.93 | %99.65 | 0.00 | 0.33 | −97 ms |
| 12 000 | %93.71 | %100.00 | 0.00 | 0.65 | **+50 ms (GEÇ)** |
| ≥20 000 | — | — | — | — | hiç tetiklenmiyor |

Sinyal ayrımı (49 koşu, 76 658 örnek): prefill p50=62, p95=989,
p99=6 639, max=11 443. Decode p1=3 839, p5=5 347, p50=13 938.
Dağılımlar 3 800–11 400 aralığında **örtüşüyor**; ayrımı yapan histerezis
ve k=2.

**Çalışma penceresi hi ∈ [1 000, 8 000]** (8× aralık). Dağıtılan değer
3 000, bu pencerenin geometrik ortasına yakın (geo. ort. 2 828). Altında
salınım patlıyor, üstünde tetikleme geç kalıyor ve sonra kayboluyor.

### §3.4'ün "−760 ms" anomalileri artık sınıflandırıldı

Çok turlu veride (30 tur, `i11_multiturn`), ≤−300 ms dışına düşen
tetiklemeler **uzak FP** sayıldı:

| kategori | sayı | oran |
|---|---|---|
| uzak-erken tetikleme (−770, −759 ms) | 2 / 30 | **%6.7** |
| fazla ileri geçiş | 1 / 30 | %3.3 |
| decode ortasında erken geri dönüş | 1 / 30 | %3.3 |
| geç tetikleme (>0 ms) | 0 / 30 | %0 |

Her iki uzak-FP de **tur 4**'te ve iki ayrı koşuda — rastgele değil,
sistematik. Bedeli ölçüldü:

| | n | TTFT | ITL p50 | ITL p95 |
|---|---|---|---|---|
| normal tur | 28 | 867 ms | 86.98 | 89.18 |
| anomali tur | 2 | **978 ms (+%12.8)** | 87.13 | 89.13 |

Yani anomali gerçek bir maliyet üretiyor (TTFT +%12.8) ama yalnızca
TTFT'de; ITL etkilenmiyor. Mekanizma tutarlı: 760 ms erken tetikleme,
~870 ms'lik kısa bir prefill'in neredeyse tamamının dar maskede koşması
demek.

### İddianın yeni hâli

> Dedektör, eşik seçiminde kullanılmayan 10 konfigürasyonda %100 recall
> ve %99.4 precision veriyor; sınırdan uzak yanlış pozitif üretmiyor ve
> salınmıyor. Eşik hi ∈ [1 000, 8 000] aralığının tamamında çalışıyor.
> **Tek turlu** kullanımda anomali gözlenmedi; **çok turlu** kullanımda
> turların %6.7'sinde erken tetikleme oluyor ve o turlarda TTFT %12.8
> kötüleşiyor.

Son cümle yeni ve rapora eklenmeli: dedektörün zayıf noktası çok turlu
kullanımdaki kısa prefill'lerdir.

---

## 1c / U12 — enerji gürültü tabanı

**Kullanılan veri:** J/token içeren, aynı konfigürasyonda ≥4 tekrarı olan
tüm gruplar (26 grup).

### Ölçülen taban

| | J/token CV |
|---|---|
| medyan (26 grup) | **%0.63** |
| min | %0.08 |
| max | %3.66 |

Oturum içi, aynı kol, ardışık koşular çok kararlı (%0.1–0.7). Yüksek
uçtaki değerler oturumlar arası yayılmış gruplardan geliyor
(`i9_sched`, n=34, CV %3.3–3.6).

**Doğru taban, iddianın kendi veri setinin CV'sidir** — genel bir sayı
değil.

### İddiaların denetimi

| iddia | ölçülen etki | kendi kolunun CV'si | karar |
|---|---|---|---|
| §3.2 "en az enerji, −%4.6" | −%4.55 | %0.15 / %0.40 | **GEÇERLİ** — etki CV'nin ~11 katı |
| §3.4 "J/token −%2.5" | −%2.16 | **%2.98** (SWITCH kolu) | **DÜŞTÜ** — etki kendi gürültüsünün altında |

§3.4'ün enerji iddiası **"reported, not claimed"** seviyesine iniyor.
Ayrıca dikkat çekici: çok turlu SWITCH kolunun enerji CV'si (%2.98) aynı
deneydeki A_P8 kolunun dört katı (%0.71) — 1b'de bulunan tur-4
anomalileriyle tutarlı.

---

## Kova 1 özeti

| madde | durum | sonuç |
|---|---|---|
| **U4** | kapandı | İki rakip açıklama da elendi; erken uyarı prompt-bağımsız sabit iş, %77 verimle ölçekleniyor (decode %63 değil). Yer-gerçeği tanımı doğru. |
| **U9** | kapandı | Held-out %100 recall / %99.4 precision, uzak FP yok, salınım yok, eşik penceresi 8×. Çok turlu zayıflık nicelendi (%6.7, TTFT +%12.8). |
| **U12** | kapandı | Taban %0.63 (medyan). §3.2 iddiası geçerli, **§3.4 iddiası düştü**. |
