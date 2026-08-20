# İŞ 1 / H5 — Faz tespiti uygulamadan yardım almadan mümkün mü?

**Cevap: DOĞRULANDI** — ama tek ve önemli bir çekince ile (bölüm 5).

**Veri:** 10 yeni koşu (5 pinli `0,2,4,6,8,10,12,14` + 5 pinsiz, interleaved),
20 ms periyotla sistem telemetrisi + yer-gerçeği olarak token zaman
damgaları, tek `perf_counter_ns` zaman tabanında.

**Neden yeni koşu gerekti:** mevcut 158 koşuda zaman serisi olarak yalnızca
token zaman damgaları vardı; `migrations` ve `ctx_switches` koşu başı/sonu
snapshot farkıydı, frekansın da sadece ortalaması saklanmıştı.

---

## 1. Dedektör

Düz mantık, ML yok:

```
ctx_switch_rate > 20 000/s  ardışık 2 örnek boyunca  =>  DECODE
```

Sinyal `/proc/<pid>/task/<tid>/sched` içindeki `nr_switches` toplamından
türetiliyor — yani **uygulamaya hiç dokunulmuyor**, herhangi bir process
için dışarıdan okunabilir.

**Neden çalışıyor:** llama.cpp thread'lerini her katmanda senkronize
ediyor. Decode her **token** için bir tam forward pass yapıyor; prefill ise
tüm prompt için **tek** pass yapıyor. Sonuç: decode saniyede yüzlerce kez
bariyer dansı yaparken prefill neredeyse hiç yapmıyor.

## 2. Ölçülen ayrışma

| faz | ctx switch hızı |
|---|---|
| prefill (p95) | 5 803/s |
| decode (p5) | 31 584/s |

**5.4 kat boşluk.** Sabit eşiğin çalışmasını mümkün kılan bu.

## 3. Doğruluk ve gecikme

| koşu tipi | doğruluk | gecikme |
|---|---|---|
| pinli (5 koşu) | %99.54 – %99.60 | −120 ila −135 ms |
| pinsiz (5 koşu) | %99.48 – %99.65 | −127 ila −166 ms |
| **hepsi** | **medyan %99.60**, min %99.48 | **medyan −133 ms**, p95 −121 ms |

Hiçbir koşuda kaçırma yok. Dedektör iki farklı yerleşimde de çalışıyor,
yani tek konfigürasyona uydurulmuş değil.

### Gecikme neden negatif?

Dedektör, yer-gerçeğinden **önce** tetikleniyor. Yer-gerçeği "ilk token'ın
HTTP istemcisine varışı"; sıçrama ise ondan ~133 ms önce başlıyor —
kabaca bir token üretim periyodu (ITL ~95 ms) kadar.

İki aday açıklama vardı; **ayrı bir ölçümle ayrıştırıldı**:

- (a) istemci gecikmesi (örnekleme + detokenize + soket),
- (b) sıçramanın prefill'in son bölümünde başlaması.

Sunucunun kendi `prompt eval time` değeri 11 013.8 ms, aynı koşuda istemci
TTFT'si 11 040.5 ms → **istemci gecikmesi yalnızca 26.7 ms.**

Yani −133 ms'nin yaklaşık **27 ms'si (a)**, kalan **~106 ms'si (b)**:
ctx switch sıçraması, prefill compute'u bitmeden önce, prefill'in
kuyruğunda başlıyor. **Açıklama (b) baskın.**

**Pratik sonucu:** tespit gecikmesi bir darboğaz değil, tersine dedektör
sınırı erken yakalıyor. Bunun maliyeti, 11 saniyelik prefill'in son
~106 ms'sinde (yani prefill'in **%1'inde**) "decode" demek — bir scheduler
için ihmal edilebilir. Bu erken tetikleme aslında bir avantaj: politika,
faz geçişine hazırlanmak için ~100 ms öncesinden haber almış oluyor.

Bu, brief'te sorulan "200 ms sonra tespit eden dedektör kısa decode'larda
işe yaramaz" endişesinin karşılanmış olması demek: burada gecikme sıfırın
**altında**.

## 4. Maliyet: örnekleme periyodu taraması

Örnekleyicinin kendi maliyeti örnek başına 1.7 ms (34 thread dosyası).
Veriyi seyrelterek daha yavaş örnekleme simüle edildi:

| periyot | doğruluk | gecikme p50 | gecikme p95 | daemon maliyeti |
|---|---|---|---|---|
| 20 ms | %99.58 | −133.1 ms | −120.7 ms | %8.6 |
| 40 ms | %99.59 | −117.0 ms | −92.6 ms | %4.3 |
| 60 ms | %99.63 | −101.6 ms | −79.5 ms | %2.9 |
| **100 ms** | **%99.66** | **−78.7 ms** | **−20.7 ms** | **%1.7** |
| 200 ms | %99.69 | +49.6 ms | +140.6 ms | %0.9 |

*(maliyet = tek bir çekirdeğin yüzdesi)*

**Önerilen: 100 ms.** Doğruluk bozulmuyor, gecikme p95'te hâlâ negatif, ve
maliyet tek çekirdeğin %1.7'si. 200 ms'de gecikme pozitife dönüyor
(p95 +141 ms) — brief'in uyardığı bölgeye girer.

Bu, CLAUDE.md'nin "yavaş yol (userspace daemon, saniye)" mimarisiyle
uyumlu: daemon saniyede 10 kez örnekleyip fazı bilebilir.

## 5. ÇEKİNCE — bu sonucun sınırı

Dedektör llama.cpp'yi **enstrümante etmiyor**, ama ayırt edici sinyal
llama.cpp'nin **thread mimarisinin bir sonucu**. Yüksek ctx switch hızı,
OpenMP bariyerlerinin futex üzerinden uyku/uyanma yapmasından geliyor.

Farklı bir runtime — örneğin bariyerlerde futex'e düşmeden spin-wait yapan
ya da başka bir threading modeli kullanan bir motor — bu sinyali
üretmeyebilir. O durumda aynı dedektör çalışmaz.

Yani doğru ifade şu: **"OS, bu iş yükünün fazını uygulamadan yardım almadan
ayırt edebiliyor"** — bu runtime için. **"Her LLM runtime'ı için ayırt
edebilir"** iddiası bu veriyle kurulmuş değil ve kurulmamalı.

CLAUDE.md'nin H5 için çizdiği ayrım korunuyor: katkının adı "uygulama OS'a
ipucu veriyor" değil, "OS iş yükünü anlıyor" — ama parantezle: *llama.cpp
sınıfı, bariyer-senkronize CPU inference runtime'ları için*.

Genelleme testi için ikinci bir runtime (ör. ollama farklı derlemeyle, ya
da bir spin-wait yapılandırması) gerekir; bu oturumda yapılmadı.

## 6. Ölçülemeyenler

- İlk koşularda **enerji yok**: RAPL düğümleri root-only'di, izin oturum
  ortasında verildi. Sonraki koşularda kaydedildi.
- Dedektör **çekişme altında test edilmedi**. S2'deki gibi 16 rakip thread
  varken sistem geneli ctx switch hızı yükselir; dedektör süreç-başına
  saydığı için etkilenmemesi beklenir ama **ölçülmedi**.
- Yalnızca tek prompt uzunluğu (496 token) ve tek üretim uzunluğu (256).
  Çok kısa decode'larda (ör. 5 token) davranış test edilmedi.

---

## Karar

**H5 doğrulandı.** Prefill/decode sınırı, yalnızca `/proc`'tan okunabilen
sistem sinyalleriyle, %99.6 doğrulukla ve negatif gecikmeyle tespit
edilebiliyor; maliyeti tek çekirdeğin %1.7'si.

Faz-farkındalıklı mimarinin dayandığı varsayım **bu runtime için**
ayakta. Genelliği test edilmedi ve iddia edilmiyor.
