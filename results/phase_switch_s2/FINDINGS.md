# İŞ 6 — Faz anahtarlama, çekişme altında: NEGATİF SONUÇ

**Sonuç: mekanizma çekişme altında hiçbir şey kazandırmıyor. Rakipsiz
ölçümdeki Pareto baskınlığı, E-core'ların boş olmasına bağlıymış.**

**Tasarım:** 6 tur × 3 kol = 18 koşu, interleaved. Yük her kolda **aynı
yerde**: 16 thread, E-core'lara (16-23) pinli — statik D ile birebir aynı
yerleşim. Tek değişen: LLM'in o çekirdekleri kullanıp kullanmadığı ve
ne zaman.

---

## 1. Ölçülen

| kol | TTFT | ITL p50 | ITL p95 | ITL p99 | decode | J/token | yük it/s |
|---|---|---|---|---|---|---|---|
| A_P8 | 11 570 | 88.22 | 89.94 | 92.22 | 11.30 | 11.363 | 18 048 |
| C_P8_E8 | 11 745 | 98.16 | 99.28 | 99.87 | 10.17 | 12.245 | 18 129 |
| SWITCH | 11 741 | 88.24 | 89.71 | 90.74 | 11.31 | 11.409 | 18 033 |

SWITCH'in A_P8'e karşı **her** farkı gürültü tabanının içinde:

| metrik | fark | anlamlılık |
|---|---|---|
| TTFT | +%1.5 | p<0.01 ama %2 altı |
| ITL p95 | −%0.3 | ns |
| ITL p50 | +%0.0 | ns |
| decode | +%0.1 | ns |
| J/token | +%0.4 | ns |
| yük | −%0.1 | ns |

## 2. Neden: kazanç E-core'ların boşluğuna bağlıydı

Rakipsiz ölçümle karşılaştırma mekanizmayı açığa çıkarıyor:

| kol | TTFT rakipsiz | TTFT çekişme | fark |
|---|---|---|---|
| A_P8 | 10 998 | 11 570 | **+%5.2** |
| C_P8_E8 | 9 753 | 11 745 | **+%20.4** |
| SWITCH | 9 748 | 11 741 | **+%20.4** |

E-core kullanan iki kol (C ve SWITCH) çekişmeden **4 kat** fazla zarar
görüyor. Sebep basit: rakip 16 thread ile 8 E-core'u doyurmuş durumda;
prefill'e E-core eklemek boş kapasite bulmuyor, sıraya giriyor.

A_P8 ise E-core'a hiç dokunmadığı için rakipten neredeyse etkilenmiyor
(+%5.2) — bu da statik D'nin neden iyi bir baseline olduğunu açıklıyor.

**Yani rakipsiz ölçümdeki +%13'lük prefill kazancı bir "bedava kaynak"
kazancıydı: E-core'lar atıl duruyordu. Rakip varken atıl kaynak yok.**

## 3. Rakip hiçbir kolda zarar görmedi

Yük hızı üç kolda da ~18 000 it/s (fark %0.5'in altında), ve S2 v2'deki
statik D ölçümüyle (17 954) uyumlu — kurulum doğrulanmış oluyor.

Bu da beklentimin tersiydi: SWITCH'in prefill sırasında E-core'ları alıp
rakibe fatura çıkaracağını tahmin etmiştim (~15 000 it/s). Çıkarmadı.
Muhtemel açıklama: CFS, LLM'in thread'lerini kalabalık E-core'lar yerine
boş P-core'lara yönlendiriyor; yani LLM E-core'ları maskesinde taşısa bile
pratikte pek kullanmıyor. **Ölçülmedi, yerleşim örneklemesiyle
doğrulanabilir.**

## 4. Ölçütün iç tutarsızlığı — kaydediliyor, düzeltilmiyor

Dondurulmuş ölçüt bu senaryoda **hiçbir kol tarafından geçilemez**, ve
sebebi politikaların yetersizliği değil, ölçütün kendisi:

| kısıt | referansın alındığı koşul | SWITCH | sonuç |
|---|---|---|---|
| TTFT ≤ 9 920 ms | **rakipsiz** (İŞ 4) | 11 741 | KALIR |
| ITL p95 ≤ 91.90 ms | **rakipsiz** (İŞ 4) | 89.71 | GEÇER |
| yük ≥ 17 595 it/s | **çekişmeli** (S2 v2) | 18 033 | GEÇER |

Senaryo çekişmeli olduğuna göre, rakipsiz koşulda ölçülmüş bir TTFT'yi
çekişme altında yakalamak tanım gereği mümkün değil. **Mevcut baseline
A_P8 bile bu kısıtı ihlal ediyor** (11 570 > 9 920).

Yani ölçüt, QoS referanslarını rakipsiz ölçümlerden, rakip referansını
çekişmeli ölçümden alarak iki farklı dünyayı tek sınavda birleştirmiş.
Bu bir tasarım hatasıdır ve bana aittir.

**Ölçüt bu raporda düzeltilmiyor.** Dondurma kuralı gereği revizyon ancak
gerekçesi ve tarihiyle, eski hâli silinmeden yapılır — ve bu kez revizyonun
sonucu bilerek yapılıyor olması, kuralın tam olarak koruduğu şeydir. Karar
kullanıcınındır.

İki okuma da raporlanıyor:

- **Lafzen:** SWITCH 2/3 geçiyor, TTFT'de kalıyor — ama tüm kollar kalıyor.
- **Eşit koşulda:** SWITCH, çekişme altında A_P8 ile **berabere**; ne
  kazanç ne kayıp.

## 5. Bunun sched_ext için anlamı — iddia keskinleşti

Bu negatif sonuç, sched_ext'in katkısını **daha net** tanımlıyor.

Problem şu: LLM'in prefill'i E-core kapasitesine ihtiyaç duyuyor, ama o
kapasiteyi rakip tutuyor. `sched_setaffinity` LLM'e E-core'larda **öncelik
veremez** — yalnızca "orada koşabilirsin" der, "önce sen koş" diyemez.
Maske bölümlemedir, öncelik değil.

sched_ext'in ifade edebileceği ve affinity'nin edemeyeceği şey tam olarak
bu: *"prefill fazındaki LLM thread'leri E-core'larda rakibi preempt etsin;
decode fazına geçince E-core'ları tamamen bıraksın."*

**Ölçülebilir hipotez (Faz 3):** öncelikli preemption ile, çekişme altında
da rakipsiz koşuldaki prefill kazancının bir kısmı geri alınabilir —
rakibe maliyeti, prefill'in kısa süresiyle (zamanın ~%33'ü) sınırlı kalır.

Bu, S2 v2'de tespit edilen "sert bölümlemenin israfı" argümanının somut
hâlidir ve artık **ölçülmüş bir boşluğa** dayanıyor: rakipsiz 9 748 ms ile
çekişmeli 11 741 ms arasındaki **1 993 ms**.

## 6. Sınırlar

- Rakip yalnızca E-core'larda. Rakip serbest bırakılsaydı (S2'nin B kolu)
  tablo değişirdi; ölçülmedi.
- LLM'in E-core'ları pratikte ne kadar kullandığı **ölçülmedi**
  (bölüm 3'teki CFS açıklaması hipotez).
- decode→prefill geri dönüşü hâlâ test edilmedi.
- Tek prompt/üretim uzunluğu.
