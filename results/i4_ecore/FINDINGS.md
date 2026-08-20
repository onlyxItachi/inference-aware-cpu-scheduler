# İŞ 4 — Prefill'e E-core eklemek

**Sonuç: E-core'lar prefill'i belirgin hızlandırıyor, decode'u belirgin
bozuyor. Asimetri eyleme dönük hâliyle ölçüldü — ama dondurulmuş ölçütü
yine de geçmiyor.**

**Tasarım:** 6 tur × 3 kol = 18 koşu, interleaved (`order-seed=77`).
P-core tahsisi her kolda sabit (8 fiziksel P); **tek değişken eklenen
E-core sayısı.**

---

## 1. Ölçülen

| kol | cpus | thread | prefill tok/s | TTFT | decode tok/s | ITL p95 |
|---|---|---|---|---|---|---|
| A_P8 | 8 fiziksel P | 8 | 45.13 | 10 990 | 11.56 | 90.10 |
| B_P8_E4 | +4 E | 12 | 47.77 | 10 384 | 10.19 | 101.47 |
| C_P8_E8 | +8 E | 16 | **51.00** | **9 725** | 10.58 | 98.58 |

A_P8'e karşı (hepsi p<0.01, %2 eşiğinin üstünde):

| | B_P8_E4 | C_P8_E8 |
|---|---|---|
| prefill | **+5.8%** | **+13.0%** |
| TTFT | **−5.5%** | **−11.5%** |
| decode | −11.8% | −8.4% |
| ITL p95 | +12.6% | +9.4% |
| ITL p99 | +12.2% | +8.1% |

## 2. Yorum: statik hiçbir konfigürasyon ikisini birden alamıyor

Bariyer maliyeti endişesi kısmen doğruydu ama **fazlara göre zıt yönde**:

- **Prefill**, E-core'ların eklediği aritmetikten kazanıyor. Compute-bound
  ve %77 verimle ölçekleniyor (K1); yavaş çekirdek bile net katkı yapıyor.
- **Decode**, heterojen bariyerden zarar görüyor. Zaten bandwidth-bound
  (İŞ 2) olduğu için ek çekirdekten kazanç yok, ama her katmanda 3.7 GHz'lik
  thread'i beklemek gecikme ekliyor. ITL p95 %9.4 kötüleşiyor.

**Bu, projenin merkezi hipotezinin en doğrudan kanıtı:** aynı iş yükünün
iki fazı, aynı scheduling kararına (E-core ekle) **zıt tepki** veriyor.
Statik bir politika birini seçmek zorunda; faz-farkındalıklı bir politika
seçmek zorunda değil.

Kâğıt üzerinde ideal politika: **prefill'de P+E, decode'da yalnız P.**
Bu, A_P8'e göre TTFT'yi %11.5 iyileştirir ve ITL'i bozmaz.

## 3. Ama dondurulmuş ölçüt bunu GEÇİRMİYOR

`CLAUDE.md` → Başarı Ölçütü, statik D'ye karşı:

| | değer | tavan/eşik | sonuç |
|---|---|---|---|
| KISIT TTFT | 10 204 ms | ≤ 11 763 ms | **GEÇER** (bol marjla) |
| KISIT ITL p95 | 89.26 ms | ≤ 91.04 ms | **GEÇER** |
| **AMAÇ rakip throughput** | **~11 994 it/s** | **> 18 313 it/s** | **BAŞARISIZ** |

Sebep: politika prefill sırasında (zamanın %33.2'si) E-core'ları rakipten
**alıyor**. Statik D'de rakip E-core'lara %100 zaman sahipti; burada
%66.8'e düşüyor → 17 954 → ~11 994 it/s (**−%33**).

Yani mekanizma LLM'in servis kalitesini iyileştiriyor, rakibe throughput
iade etmiyor — ölçütün ödüllendirdiği şey ikincisi.

## 4. Faz 1'in kapanış tablosu: hiçbir mekanizma ölçütü geçmiyor

| mekanizma | KISIT (LLM QoS) | AMAÇ (rakip throughput) |
|---|---|---|
| decode'da 8→6 çekirdek iadesi | **İHLAL** (ITL +%7.7, bütçenin 3.9 katı) | +%24 olurdu |
| prefill'e E-core ekleme | GEÇER (bol marj) | **BAŞARISIZ** (−%33) |

İki mekanizma da var ve ikisi de gerçek; ama biri kısıtı ihlal ediyor,
diğeri amacı ıskalıyor.

**Ölçüt değiştirilmiyor.** Dondurma kuralının amacı tam olarak buydu:
sonuç görüldükten sonra ölçütü sonuca uydurmak. Burada kaydedilen şey şu:

> Ölçülen faz asimetrisi gerçek ve büyük (+%13 prefill / −%8.4 decode), ama
> değeri **LLM gecikmesi ekseninde** ortaya çıkıyor; dondurulmuş ölçüt ise
> **rakip throughput'u ekseninde** ödül veriyor.

Bu bir çelişki değil, bir ölçüt-hedef uyumsuzluğudur ve Faz 2'ye
girmeden önce **kullanıcının karar vermesi gereken** bir şeydir:

- (a) Ölçüt doğru, proje rakibe iade etmeyi hedefliyorsa → ölçülen
  mekanizmaların hiçbiri yetmez, yeni mekanizma aranmalı.
- (b) Projenin asıl hedefi LLM servis kalitesiyse → ölçüt revize edilmeli,
  **ve revizyonun gerekçesi ile tarihi CLAUDE.md'ye yazılmalı, eski hâli
  silinmemeli.**

Ajan bu kararı kendi başına vermez.

## 5. Sınırlar

- Yalnızca tek prompt uzunluğu (496 token) ve tek üretim uzunluğu (256).
  Prefill payı arttıkça (uzun prompt) E-core kazancının toplam etkisi
  büyür; İŞ 2'nin prompt taraması bu kolda tekrarlanmadı.
- "Prefill'de P+E, decode'da yalnız P" politikası **simüle edilmedi**,
  iki statik koldan hesaplandı. Gerçek bir politika, faz geçişinde thread
  havuzunu yeniden boyutlandırmak zorunda kalır; llama.cpp bunu çalışma
  anında desteklemiyor olabilir — Faz 2'nin ilk teknik sorusu bu.
- Enerji bu kolda kaydedilmedi.
