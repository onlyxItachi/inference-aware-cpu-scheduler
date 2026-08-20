# İŞ 2 — Merkezi iddia: projeksiyon değil, ölçüm

**Sonuç: iddia TUTTU. Faz-anahtarlamalı politika her iki statik
konfigürasyonu da Pareto olarak baskılıyor ve yeni ölçütün iki kısıtını da
geçiyor.**

**Tasarım:** 6 tur × 3 kol = 18 koşu, interleaved (`order-seed=202`),
496 token prompt, 256 token üretim, rakip yük **yok** (temiz sinyal).

| kol | cpus | -t | -tb | canlı dedektör |
|---|---|---|---|---|
| A_P8 | P8 | 8 | 8 | çalışıyor, **kullanılmıyor** |
| C_P8_E8 | P8+E8 | 16 | 16 | çalışıyor, **kullanılmıyor** |
| SWITCH | P8+E8 | 8 | 16 | çalışıyor, **faz geçişinde maskeyi P8'e daraltıyor** |

Örnekleyici üç kolda da çalışıyor (örnek başına ~1.7 ms). Yalnızca
anahtarlama koluna yüklenseydi karşılaştırma bu handikapı gizlerdi.

---

## 1. Ölçülen

| kol | TTFT | ITL p50 | ITL p95 | ITL p99 | decode | J/token | migration |
|---|---|---|---|---|---|---|---|
| A_P8 | 10 998 | 86.10 | 89.94 | 92.40 | 11.55 | 10.986 | 3 858 |
| C_P8_E8 | 9 753 | 95.92 | 99.84 | 101.39 | 10.41 | 11.248 | 62 120 |
| **SWITCH** | **9 748** | **86.09** | **86.71** | **87.28** | **11.60** | **10.486** | 7 275 |

SWITCH'in her iki statiğe karşı farkı:

| | vs A_P8 | vs C_P8_E8 |
|---|---|---|
| TTFT | **−%11.4** (p<0.01) | −%0.1 (ns) |
| ITL p95 | **−%3.6** (p<0.01) | **−%13.1** (p<0.01) |
| ITL p50 | −%0.0 (ns) | −%10.2 (p<0.01) |
| J/token | **−%4.6** (p<0.01) | **−%6.8** (p<0.01) |

## 2. Yeni ölçütün sınavı

| kısıt | ölçülen | tavan | sonuç |
|---|---|---|---|
| TTFT ≤ C_P8_E8 × 1.02 | 9 748 ms | 9 920 ms | **GEÇER** |
| ITL p95 ≤ A_P8 × 1.02 | 86.71 ms | 91.90 ms | **GEÇER** |
| rakip ≥ 17 595 it/s | — | — | **bu ölçümde rakip yük yok** |

İlk iki kısıt geçildi. Üçüncüsü henüz test edilmedi ve bu **eksik bir
sınavdır** — S2 kolları sonraki adım.

**Dikkat:** SWITCH ITL p95'te A'yı yalnızca *eşitlemedi*, **%3.6 yendi**
(gürültü tabanının üstünde, p<0.01). Beklenti eşitlemekti; yenmesi
açıklanmadı (bkz. bölüm 4).

## 3. Geçiş maliyeti: 100 kat migration, sıfır gecikme

Bu deneyin en çarpıcı sonucu.

| kol | 200 ms penceresinde migration | ctx burst | anahtarlama süresi |
|---|---|---|---|
| A_P8 (kontrol) | 22 | 14 594 | — |
| C_P8_E8 (kontrol) | 413 | 33 370 | — |
| **SWITCH** | **2 338** | 17 124 | **202 µs** |

Faz sınırında 16 thread'in maskesi aynı anda değiştiriliyor ve bu
**~2 300 ekstra migration** üretiyor — kontrol kolunun 100 katından fazla,
üstelik koşunun en gecikmeye duyarlı anında.

Geçişten hemen sonraki 10 token'ın ITL'i (ms):

| kol | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | kuyruk |
|---|---|---|---|---|---|---|---|---|---|---|---|
| A_P8 | 94.9 | 92.6 | 91.5 | 91.4 | 91.0 | 90.2 | 90.3 | 90.0 | 90.1 | 89.9 | 86.23 |
| C_P8_E8 | 95.9 | 95.0 | 97.0 | 97.8 | 95.5 | 93.6 | 95.0 | 94.7 | 97.4 | 97.4 | 96.09 |
| **SWITCH** | **86.7** | **86.0** | **86.4** | **86.1** | **86.0** | **85.9** | **85.9** | **85.8** | **85.9** | **85.8** | **86.18** |

**SWITCH'te geçiş maliyeti gecikmeye hiç yansımıyor** — ilk token 86.7 ms,
kuyruk ortalaması 86.18 ms, aradaki fark %0.6 (gürültü tabanının altında).

Bu, projenin "migration sayısı yanlış metriktir" bulgusunun **dördüncü ve
en düşmanca** doğrulaması: bu kez migration'ı scheduler değil **biz**
ürettik, kasıtlı olarak, en kötü anda — ve yine hiçbir şey olmadı.

`sched_setaffinity` çağrısının kendisi 16 thread için **202 µs** sürüyor;
CLAUDE.md'nin "sıcak yol mikrosaniye mertebesinde" ilkesine göre bu bir
**yavaş yol** işlemidir ve faz başına bir kez yapılır — 33 saniyelik bir
koşuda 202 µs, sürenin milyonda 6'sı.

## 4. Açıklanamayan: statik A'nın ısınma transient'i SWITCH'te yok

A_P8'in ilk token'ı 94.9 ms, kuyruk ortalamasına (86.23) ancak ~20 token'da
iniyor — yaklaşık **%10'luk bir ısınma transient'i**. SWITCH'te bu transient
**yok** (86.7 → 85.8, düz).

Termal açıklama **desteklenmiyor**: paket sıcaklıkları neredeyse aynı
(A: 56→78°C, SWITCH: 56→77.5°C).

Aday açıklama (test edilmedi): SWITCH'te anahtarlama ilk token'dan ~116 ms
önce yapılıyor, yani decode thread'leri ilk token üretilmeden önce hedef
çekirdeklerine yerleşmiş ve oturmuş oluyor. A'da böyle bir erken yerleşim
yok. **Bu bir hipotezdir, ölçülmedi.**

Pratik sonucu: dedektörün negatif gecikmesi (erken uyarı) burada bir
**avantaja** dönüşmüş olabilir — ama bu iddia kurulmadan önce ölçülmeli.

## 5. Enerji

SWITCH üç kolun en verimlisi: **10.486 J/token**, A'ya karşı **−%4.6**,
C'ye karşı **−%6.8** (ikisi de p<0.01).

Yani faz anahtarlama gecikmeyi iyileştirirken enerjiyi de düşürüyor —
bir takas değil. (E-core kolunda enerji ilk kez burada kaydedildi;
önceki oturumun açığı kapandı.)

## 6. Sınırlar — sınav eksik

- **Rakip yük yok.** Ölçütün üçüncü kısıtı test edilmedi. S2 kolları
  (16 rakip thread) altında hem QoS hem rakip throughput'u yeniden
  ölçülmeli. Asıl sınav orası; bu ölçüm mekanizmanın çalıştığını gösterir,
  politikanın işe yaradığını değil.
- **Tek yönlü anahtarlama.** Yalnızca prefill→decode. Çok turlu bir
  konuşmada decode→prefill geri dönüşü de gerekir ve test edilmedi.
- **Tek prompt/üretim uzunluğu** (496/256).
- Anahtarlama, dedektörün kararına göre yapılıyor; dedektörün kısa
  promptlardaki zayıflığı (prefill recall %82.7 @ 32 token) bu politikaya
  da miras kalır.
- ITL p95'teki %3.6'lık *fazladan* kazanç açıklanmadı.
