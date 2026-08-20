# İŞ 7 — Paylaşılan çekirdek: sched_ext için ilk ölçülmüş boşluk

**Sonuç: öncelik burada gerçekten çalışıyor (boşluğun %41–56'sı geri
geliyor), ama boşluğu KAPATMIYOR. Kalan ~%44–52, projede sched_ext'i
gündeme getirebilecek ilk ölçülmüş artıktır — ancak tamamı scheduler'a
ait değil.**

**Tasarım:** 6 tur × 4 kol = 24 koşu, interleaved, `n_predict=128`.
Rakip: 16 thread loadgen, **LLM'in decode'da kullandığı aynı 8 P-core'a**
(`0,2,4,6,8,10,12,14`) pinli. İŞ 3'ten farkı bu: orada rakip E-core'daydı
ve iki iş hiç aynı CPU için yarışmıyordu, dolayısıyla önceliğin arbitraj
edecek bir şeyi yoktu.

---

## 1. Ölçülen

| kol | TTFT | ITL p50 | ITL p95 | ITL p99 | decode | rakip it/s |
|---|---|---|---|---|---|---|
| S0_static (A_P8) | 30 143 | 396.78 | 496.00 | 527.50 | 2.51 | 20 822 |
| S1_switch | 25 767 | 408.95 | 490.98 | 532.22 | 2.52 | 22 617 |
| S2_nice (+19) | 19 189 | 272.68 | 307.30 | 323.89 | 3.84 | 20 385 |
| **S3_weight (=1)** | **17 992** | **227.58** | **287.86** | **300.58** | **4.55** | 19 633 |

Referanslar: rakipsiz SWITCH TTFT **9 748**, ITL p50 **86.09**.
Çekişmeli taban (S1): TTFT 25 767, ITL p50 408.95.
**Boşluk: TTFT 16 019 ms, ITL p50 322.86 ms.**

| kol | TTFT boşluğu geri gelen | ITL p50 boşluğu geri gelen | rakibin kaybı |
|---|---|---|---|
| nice +19 | **%41.1** (p<0.01) | **%42.2** (p<0.01) | −%9.9 |
| CPUWeight=1 | **%48.5** (p<0.01) | **%56.2** (p<0.01) | −%13.2 |

## 2. İŞ 3'ün yorumu doğrulandı

İŞ 3'te aynı iki mekanizma boşluğun **%1'inden azını** geri almıştı ve
rakip **%0.2** kaybetmişti. O zaman yorum şuydu: "rakip zaman kaybetmiyorsa
ondan zaman istenmemiştir; decode P'de, rakip E'de, ayrık kümeler."

Bu deney o yorumu doğruluyor: aynı çekirdekleri paylaştırdığımızda **aynı
mekanizmalar 40–56 kat daha etkili** oluyor ve rakip gerçekten ödüyor.
Öncelik, çekişme varsa çalışıyor; yoksa çalışmıyor. Beklenen davranış.

## 3. Ağırlık mekanizması doğrulandı — kısmi etki artefakt değil

`CPUWeight=1` ile rakip, 8 P-core'daki çekişmesiz hızının (25 429 it/s)
hâlâ **%77'sini** koruyor. 1:100 ağırlık oranıyla bu ilk bakışta
bağdaşmıyor, o yüzden mekanizma izole olarak sınandı:

> Aynı 2 CPU'da iki loadgen, biri `CPUWeight=1` biri varsayılan:
> **117 it/s vs 6 520 it/s** — oran 1:56.

Yani cgroup ağırlığı **kusursuz çalışıyor**. Kısmi etkinin sebebi
yapılandırma değil, **iş yükünün doğası**:

LLM sürekli çalışan bir iş değil. Decode'da token başına ~86 ms hesap
yapıp bariyerlerde ve tokenler arasında bekliyor. CFS iş-koruyucudur:
LLM boşluk bıraktığı her an rakip serbestçe koşar ve ağırlık orada hiçbir
şey söylemez. Ağırlık yalnızca **ikisi aynı anda koşmak istediğinde**
pay dağıtır.

## 4. Kalan boşluk ne? — iki bileşen, yalnızca biri scheduler'a ait

En iyi öncelik ayarıyla (CPUWeight=1) kalan artık:
**TTFT 8 244 ms, ITL p50 141.49 ms.**

Bu artığın en az iki bileşeni var ve **bu deney onları ayırmıyor**:

**(a) Uyanma-preemption gecikmesi — sched_ext'in hedefleyebileceği kısım.**
Bir decode thread'i uyandığında, o an koşan rakip thread'in derhal
atılması gerekir. CFS bunu vruntime üzerinden dolaylı yapar ve preemption
kendi granülaritesinde gerçekleşir. sched_ext'in ifade edebildiği şey tam
olarak "uyanınca derhal preempt et"tir.

**(b) Cache ve bellek bant genişliği girişimi — hiçbir scheduler'ın
çözemeyeceği kısım.** Rakip, LLM'in boşluklarında koşarken LLC'yi
kirletiyor ve bant genişliği tüketiyor. Decode zaten bandwidth-bound
(İŞ 2, Faz 1). Bu maliyeti ortadan kaldırmanın tek yolu rakibi hiç
koşturmamaktır — ki bu bir scheduling politikası değil.

**Dolayısıyla sched_ext'in üst sınırı 8 244 ms DEĞİL, onun (a) bileşenidir
ve bu bileşen ölçülmedi.** Ayrıştırması için önerilen deney: rakibi
`SCHED_IDLE` ile koşturmak (uyanan normal thread onu her zaman preempt
eder) — kalan fark (b)'ye düşer.

## 5. Faz anahtarlamanın bu senaryodaki durumu

S1_switch, S0_static'e karşı TTFT'de **%14.5 daha iyi** (25 767 vs 30 143)
ama ITL p50'de **%3.1 daha kötü** (408.95 vs 396.78). Yani bu senaryoda
SWITCH artık Pareto baskın **değil** — REVİZYON 2 ölçütünü geçmiyor.

Sebep tutarlı: prefill'de E-core'ları kullanmak hâlâ TTFT kazandırıyor
(rakip E'de değil, P'de), ama decode'da 8 P-core'u 16 rakip thread'le
paylaşmak zorunda ve orada anahtarlamanın verebileceği bir şey yok.

**Bu senaryoda kazandıran şey faz anahtarlama değil, öncelik.**

---

## 6. Karar üzerindeki etkisi

Önceki oturumun sonucu ("sched_ext'e girilmiyor, geri alınabilir boşluk
≤22 ms") **bu senaryo için geçerli değil.** Orada boşluk yoktu çünkü
çekişme yoktu.

Güncel tablo:

| senaryo | en iyi ulaşılan | kalan boşluk | scheduler'a ait mi? |
|---|---|---|---|
| gerçekçi rakip (build) | SWITCH, Pareto baskın | **0 ms** | — |
| doyuran rakip, ayrık çekirdek | öncelik etkisiz | ≤22 ms (ns) | hayır |
| **doyuran rakip, paylaşılan çekirdek** | CPUWeight=1 | **8 244 ms TTFT** | **kısmen — (a) ölçülmedi** |

sched_ext'in yazılması için gereken şey artık net ve dar: **(a)
bileşeninin sıfırdan büyük olduğunu göstermek.** `SCHED_IDLE` deneyi bunu
ucuza yapar ve BPF yazmadan cevaplar.

## 7. Sınırlar

- `n_predict=128` (diğer deneylerde 256). TTFT ve ITL yüzdelikleri
  karşılaştırılabilir; toplam süreler değil.
- Rakip yine sentetik ve doyuran. Gerçekçi bir rakip aynı çekirdeklere
  pinlenirse davranış farklı olabilir; ölçülmedi.
- (a)/(b) ayrıştırması yapılmadı — bölüm 4'ün ana açığı.
- `nice +19` ile `CPUWeight=1` aynı yönde ama farklı güçte; ikisinin
  birlikte kullanımı test edilmedi.
