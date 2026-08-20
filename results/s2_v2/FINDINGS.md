# S2 v2 — Çift taraflı muhasebe ile

**Tasarım:** S2 ile aynı (6 tur × 4 kol, interleaved), tek fark:
`loadgen` artık tamamladığı iş miktarını raporluyor, ve yükün LLM'siz
referans hızları ayrıca kalibre edildi (`load_baseline.md`).

İlk S2 turunda D "çekişme hasarının %92'sini geri alıyor" diye
raporlanmıştı ve bunun **tek taraflı bir muhasebe** olduğu işaretlenmişti.
Bu tur o eksiği kapatıyor — ve sonuç, okumayı değiştiriyor.

---

## 1. LLM tarafı: ilk sonuç aynen doğrulandı

| metrik | B (Linux varsayılanı) | C (LLM pinli) | D (yük E'ye sürülmüş) |
|---|---|---|---|
| TTFT | +61.4% | +61.6% | **+5.0%** |
| ITL p50 | +17.3% | +18.2% | **+2.0%** |
| ITL p95 | +15.2% | +38.0% | **−1.0%** |
| ITL p99 | +14.8% | +37.2% | **−1.8%** |
| decode | −14.6% | −20.5% | **−1.6%** |

*(boştaki referans A'ya göre)*

D, açığın %89–112'sini kapatıyor. C ise yine varsayılandan **kötü**
(kuyrukta −150%), ilk turdaki ters etki tekrarlandı: LLM'i izole etmek
değil, rakibi tahliye etmek kazandırıyor.

## 2. Rakibin faturası: D bedava değil

| kol | yük yerleşimi | yük it/s | serbest referansa | kendi yerleşim referansına |
|---|---|---|---|---|
| B | serbest | 38 707 | %85 | %85 |
| C | serbest | 38 887 | %86 | %86 |
| D | E-core | **17 954** | **%40** | **%90** |

Ayrıştırma temiz: D'nin rakibe maliyeti neredeyse tamamen **yerleşimden**
geliyor, LLM ile çekişmeden değil. Yük E-core'da kendi tavanının %90'ını
tutuyor — yani D verimsiz değil, sadece rakibe **daha küçük bir kaynak**
veriyor. E-core'lar zaten serbest referansın %44'ü kadar.

## 3. Toplam sistem görünümü — D bir kazanç değil, bir ÖNCELİK KARARI

Her iki tarafı kendi çekişmesiz tavanına normalize edip eşit ağırlıkla
toplarsak:

| kol | LLM | yük | eşit ağırlıklı toplam |
|---|---|---|---|
| B (Linux varsayılanı) | 85.4% | 85.4% | **170.9%** |
| C | 79.5% | 85.8% | 165.3% |
| D | **98.4%** | 39.6% | **138.0%** |

**Bu ölçüte göre Linux'un varsayılanı en iyisi, D en kötüsü.**

D, LLM'e 13 puan kazandırmak için yükten 46 puan alıyor. Bu bir bedava
öğle yemeği değil; bir takas. Ve hangi tarafın ağır bastığına **ölçüm karar
veremez** — bu bir değer yargısı:

- LLM etkileşimli (kullanıcı token bekliyor), rakip toplu iş (derleme) ise
  D savunulabilir ve LLM tarafında neredeyse sıfır bozulma veriyor.
- İkisi de throughput cinsinden eşit değerliyse varsayılan daha iyi.

Eşit ağırlıklı toplam da tek doğru ölçüt değil; enerjiyi saymıyor
(E-core'lar daha verimli) ve gecikmeyi throughput'a çeviriyor. Birden fazla
çerçeveden bakılması gereken bir yer burası.

**İlk S2 raporunda D'yi "kazanç" diye sunmamak doğru olmuş.** Çift taraflı
sayılar gelince "kazanç" tanımı değişti.

## 4. Bu, faz-farkındalıklı politikanın asıl gerekçesi

Statik D'nin sorunu şu: decode fazında LLM'in ihtiyacı olmayan çekirdekleri
de tutuyor. K1'in sayıları burada devreye giriyor:

- decode'a 8 yerine 6 çekirdek vermek yalnızca **%7.8**'e mal olur
- prefill'e 8 çekirdek vermek **+%20.8** kazandırır

Yani **faz-farkındalıklı bir politika statik D'yi yenebilir**: prefill
sırasında geniş, decode sırasında dar; boşalan çekirdekler rakibe geri
verilir. Statik pinning bunu yapamaz çünkü fazı görmez.

Bu, Faz 3'ün (phase-aware scheduling) neden statik Faz 2'nin üstüne değer
kattığına dair **ölçülmüş** bir argümandır — ve projenin merkezi
hipotezinin savunulabilir hâli. Statik politika tek başına "önceliği
LLM'e ver" demekten ibaret; faz farkındalığı ise **aynı önceliği daha ucuza**
sağlamayı vaat ediyor.

## Sınırlar

- `loadgen` sentetik ve compute-bound; gerçek `make -j` I/O ve bellek
  davranışı da gösterir. Sonuçlar bu yük sınıfı için geçerli.
- Yük hızı, koşunun tamamı (model yükleme + warmup + istek) boyunca
  ortalanıyor, sadece ölçülen istek penceresi değil. Kollar aynı yapıya
  sahip olduğu için karşılaştırma adil, ama mutlak değerler bir miktar
  seyreltilmiş.
- Enerji ölçülmedi. E-core'lar daha verimli olduğundan D'nin enerji
  cephesindeki görünümü throughput cephesinden daha iyi olabilir.
