# İŞ 3 — Uygulama-bilgili vs dışarıdan tespitli affinity

**Sonuç: eşitler. Dışarıdan tespit, uygulamanın kendi faz bilgisiyle
yaptığının aynısını yapıyor — altı metriğin beşinde fark gürültü içinde.**

Bu, projenin en güçlü cümlesini ölçülmüş hâle getiriyor:
*OS bunu uygulamanın yardımı olmadan da yapabiliyor.*

---

## 1. Kollar

| kol | nasıl | faz bilgisi |
|---|---|---|
| **A_APP** | yamalı server, `-C 5555 -Cb FF5555 --cpu-strict 1` | uygulama **zaten biliyor** (`graph_compute` batched bayrağı); tahmin yok, gecikme yok |
| **B_DAEMON** | yamasız server + bizim daemon | `/proc`'tan tespit, ~122 ms erken tetikleme, örnekleme maliyeti |

Örnekleyici **her iki kolda da** çalıştı (A'da armed=False). Aksi hâlde
A, örnekleme maliyetinden muaf olur ve karşılaştırma daemon'ı haksız yere
cezalandırırdı.

6 tur × 2 kol = 12 koşu, interleaved.

## 2. Ölçülen

| kol | TTFT | ITL p50 | ITL p95 | ITL p99 | decode | J/token |
|---|---|---|---|---|---|---|
| A_APP | 9 855 | 87.66 | 90.48 | 93.13 | 11.36 | 10.669 |
| B_DAEMON | 9 860 | 87.25 | 91.35 | 95.31 | 11.29 | 10.710 |

B'nin A'ya karşı farkı:

| metrik | fark | anlamlılık | karar |
|---|---|---|---|
| TTFT | +%0.05 | ns | eşit |
| ITL p50 | −%0.47 | ns | eşit |
| ITL p95 | +%0.96 | ns | eşit |
| **ITL p99** | **+%2.34** | ns | gürültü içinde (bu kolun p99 tabanı %9.07) |
| decode | −%0.58 | ns | eşit |
| J/token | +%0.37 | ns | eşit |

**Beş metrikte fark %1'in altında**, altıncısı (ITL p99) +%2.34.
Bu ilk yazımda "%2 eşiğinin hemen üstünde" diye nitelenmişti; sonradan
bu kolun kendi p99 tabanı ölçüldü: **%9.07** (kol-içi CV medyanı, n=6),
Welch t=−0.27. Yani +%2.34 eşiğin hemen üstünde değil, gürültünün
derinlerinde — **altı metriğin altısı da ns**.

## 3. Yorum

Dışarıdan tespitin uygulama-bilgili yerleşimle **eşit** çıkması iki şey
söylüyor:

**(a) Faz bilgisinin kaynağı önemli değil.** Uygulamanın kesin bilgisiyle
`/proc`'tan çıkarılan tahmin arasında ölçülebilir fark yok. Tespit
yeterince doğru (%99.6 ham, prefill recall ≥%94.7) ve yeterince erken
(−122 ms) olduğu için, "tahmin" olması pratikte maliyet üretmiyor.

**(b) Katkının adı netleşiyor.** Bu ölçüm olmadan iddia "daemon işe
yarıyor"du. Şimdi "daemon, uygulamanın kendi bilgisiyle yapabileceğinin
aynısını, uygulamaya dokunmadan yapıyor" — ki bu çok daha güçlü ve
denetlenebilir bir ifade.

### Upstream yaması kabul edilirse ne olur

Yama (`patches/0001-server-attach-threadpools-honor-cpu-mask.patch`)
kabul edilirse llama-server kullanıcıları `-C`/`-Cb` ile aynı sonuca
daemon'sız ulaşır ve **daemon büyük ölçüde gereksizleşir**.

Bu kötü değil. O durumda katkının adı "bu problemi çözmenin tek yolu"
değil, **"uygulamayı hiç değiştirmeden de çözülebileceğinin kanıtı"**
olur. Ve bu ölçüm tam olarak o kanıttır — yama olmadan da, yamayla
aynı sonucun alınabildiği gösterilmiştir.

Daemon'ın yamaya göre kalan avantajı dar ama gerçek: **kaynak kodu
değiştirilemeyen ya da yeniden derlenemeyen** kurulumlarda (paket
yöneticisinden gelen binary, kapalı dağıtım, çalışan sunucuya müdahale)
tek seçenek odur.

## 4. Yama hakkında

`tools/server/server-context.cpp`, +54 satır. `common/arg.cpp` zaten
`-C`/`-Cb`/`--cpu-strict` bayraklarını **her araç için** ayrıştırıyor ama
`llama_attach_threadpool()` yalnızca `tools/completion` ve `llama-bench`'te
çağrılıyordu — server'da bayraklar sessizce yok sayılıyordu (hata da
vermiyordu).

Doğrulandı: yamalı server'da prefill sırasında 16 thread P8+E8 maskesinde,
decode sırasında thread'ler tek tek P-core'lara sabitleniyor
(`--cpu-strict`).

Kaynak ağacı yamadan sonra **eski hâline döndürüldü**; yama ayrı dosyada
duruyor, ana ölçüm binary'si değişmedi.

## 5. Sınırlar

- Tek senaryo (rakipsiz, 496 token prompt, 256 token üretim). Çekişme
  altında veya çok turlu kullanımda karşılaştırma yapılmadı.
- Yama upstream'e **gönderilmedi**; kabul edilip edilmeyeceği bilinmiyor
  ve bu rapordaki hiçbir sonuç ona bağlı değil.
- A_APP kolu `--cpu-strict 1` kullanıyor (her worker tek çekirdeğe
  sabit); daemon ise maske uyguluyor (çekirdek seçimini scheduler'a
  bırakıyor). İkisi tam olarak aynı mekanizma değil ama sonuç eşit.
