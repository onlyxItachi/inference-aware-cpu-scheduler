# İŞ 11 — Çok turlu (etkileşimli) kullanım: iddianın kapsamı daraltıldı

**Sonuç: kazancın tamamı ilk turdan geliyor. Cache'li sonraki turlarda
faz anahtarlamanın etkisi sıfırdan ayırt edilemiyor. "Etkileşimli LLM için"
iddiası **"uzun prefill'li turlar için"** olarak daraltılmalıdır.**

**Neden bu deney gerekliydi:** politika "etkileşimli yerel LLM" için
tasarlandı ama hiç etkileşimli senaryoda ölçülmemişti. Her önceki ölçüm
**tek** bir prefill→decode geçişi içeriyordu; gerçek sohbet ise
prefill→decode→prefill→decode… Ayrıca dedektörün **geri dönüş yönü
(decode→prefill) hiç ölçülmemişti**; histerezis bandı yalnızca ileri yön
verisinden seçilmişti.

**Tasarım:** 2 kol × 6 tur = 12 koşu, her koşu **5 sohbet turu** (toplam
60 tur), interleaved. `cache_prompt=true`, aynı sunucu, turlar arası 0.8 s
kullanıcı payı. Politika bu kez **çift yönlü**: →decode maskeyi P8'e
daraltır, →prefill P8+E8'e genişletir.

---

## 1. Ölçülen: kazanç yalnızca tur 1'de

| tur | A_P8 TTFT | SWITCH | fark | A_P8 p95 | SWITCH | fark |
|---|---|---|---|---|---|---|
| **1** | 11 047 | **9 802** | **−%11.3** (p<0.01) | 91.48 | 89.18 | −%2.5 (ns) |
| 2 | 858 | 846 | −%1.5 | 91.36 | 89.05 | −%2.5 |
| 3 | 865 | 851 | −%1.6 | 88.67 | 89.07 | +%0.5 |
| 4 | 870 | 877 | +%0.7 | 88.97 | 88.37 | −%0.7 |
| 5 | 876 | 881 | +%0.6 | 88.75 | 90.83 | +%2.3 |

**Toplu:**

| | TTFT | ITL p95 |
|---|---|---|
| tur 1 | **−%11.3** (p<0.01) | −%2.5 (ns) |
| tur 2–5 | −%1.2 (**ns**) | −%0.5 (**ns**) |

Sebep açık: `cache_prompt=true` ile 2. turdan itibaren prefill yalnızca
yeni tokenları işliyor ve **11 047 ms'den ~870 ms'ye** düşüyor. Prefill'e
E-core eklemenin hızlandıracağı iş kalmıyor.

## 2. Oturum düzeyinde

| | A_P8 | SWITCH |
|---|---|---|
| 5 turun toplam TTFT | 14 513 ms | **13 327 ms** (−%8.2) |
| J/token | 9.957 | **9.707** (−%2.5) |

1 186 ms'lik oturum kazancının **tamamı tur 1'den** (tek başına 1 245 ms);
tur 2–5 birlikte ~59 ms geri veriyor.

Yani 5 turluk bir sohbette kullanıcının toplam bekleme süresi %8.2
kısalıyor — gerçek ama "her turda %11" değil.

## 3. Geri dönüş yönü: güvenli, ama tam temiz değil

İlk kez ölçüldü. Öngörülen risk şuydu: ileri yönde avantaj olan −115 ms'lik
erken tetikleme, geri dönüşte **decode hâlâ sürerken E-core'ları açmak**
demek olabilir.

| | A_P8 | SWITCH |
|---|---|---|
| geçiş/koşu | 10 (ideal 10) | 10 (ideal 10) |
| kaçırılan ileri geçiş | 0 | 0 |
| ileri geçiş (medyan) | −111.9 ms | −126.9 ms |
| **geri dönüş (medyan)** | **+34.3 ms** | **+36.3 ms** |
| geri dönüş aralığı | +26…+64 ms | +26…+64 ms |

**Geri dönüş güvenli yönde geç:** decode bittikten ~35 ms *sonra*
tetikleniyor. Mekanizması tutarlı — histerezisin `lo` eşiği (2100),
decode'un tipik sinyalinin (~5800) çok altında.

**Ama sıfır değil.** SWITCH kolunun 30 turunda **3 anomali** (%10):

| anomali | sayı | etkisi |
|---|---|---|
| ileri geçiş ~−760 ms (prefill'in en başında) | 2 | o turda prefill E-core'suz koştu — politika kaybı |
| **decode sürerken geri dönüş** | **1** | öngörülen arıza modu; E-core'lar decode sırasında açıldı |

Öngörülen arıza modu **gerçekleşti ama nadir** (1/30 tur, %3.3). QoS'a
ölçülebilir bir zarar vermedi (o turun p95'i diğerlerinden ayırt
edilemiyor), ama mekanizma teyit edildi.

Tek turlu rejimde dedektör pratikte kusursuzdu (0 kaçırma, 0 salınım).
Çok turlu cache'li rejimde anomali oranı **%10**. Bu, bilinen kısa-prompt
zayıflığının (32 token'da prefill recall %82.7) etkileşimli senaryodaki
karşılığıdır: ~870 ms'lik bir prefill, 135 ms'lik erken uyarı payı için
zaten dar.

## 4. İddianın düzeltilmiş hâli

**Eski:** "etkileşimli yerel LLM için faz-farkındalıklı politika"

**Yeni:** "**uzun prefill'li turlar için** faz-farkındalıklı politika"

Somut olarak nerede kazandırır:
- Sohbetin ilk turu (sistem promptu + belge + bağlam)
- Uzun bir belge/kod yapıştırıldığı her tur
- RAG gibi her turda büyük bağlam enjekte eden akışlar
- Tek atımlık uzun-prompt iş yükleri (özetleme, çeviri, kod analizi)

Nerede kazandırmaz:
- Kısa mesajlı, cache'li sohbet turları — etkisi ölçülemiyor (ns)

Bu bir daralma ama iddianın çürütülmesi değil: etkileşimli kullanımda
kullanıcının **en uzun beklediği** an zaten ilk turdur, ve oturum
düzeyinde toplam bekleme %8.2 kısalıyor.

## 5. Sınırlar

- 5 tur, tur başına 96 token, tek prompt şablonu. Daha uzun sohbetlerde
  KV cache büyüdükçe decode yavaşlar; bu eğilim ölçülmedi.
- Turlar arası bekleme sabit 0.8 s. Gerçek kullanıcı düşünme süreleri çok
  daha değişken ve daha uzun; uzun boşluklar dedektörün durumunu
  etkileyebilir (ölçülmedi).
- Çok kısa kullanıcı mesajları (3-5 kelime, prefill <150 ms) test
  edilmedi — dedektörün erken uyarı payının prefill'den uzun olacağı
  rejim tam orası.
- Rakip yük yok. Çok turlu + çekişmeli senaryo ölçülmedi.
