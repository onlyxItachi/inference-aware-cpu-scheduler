# İŞ 8 — SCHED_IDLE ayrıştırması: sched_ext'in son kapısı da kapandı

**Sonuç: paylaşılan çekirdek senaryosundaki ITL boşluğunun %96.8'i
uyanma-preemption gecikmesiymiş, ve onu çözen mekanizma Linux'ta zaten var
(`chrt --idle`). sched_ext'e ölçülmüş bir gerekçe kalmadı.**

**Tasarım:** 6 tur × 3 kol = 18 koşu, interleaved, `n_predict=128`.
Rakip: 16 thread loadgen, LLM'in decode'da kullandığı **aynı 8 P-core'a**
pinli. Üç kol da SWITCH; değişen tek şey rakibin scheduling sınıfı.

---

## 1. Ölçülen

| kol | TTFT | ITL p50 | ITL p95 | decode | rakip it/s |
|---|---|---|---|---|---|
| S1_switch (normal) | 25 838 | 383.04 | 485.82 | 2.58 | 22 551 |
| S3_weight (CPUWeight=1) | 17 937 | 218.12 | 288.91 | 4.66 | 19 497 |
| **S4_idle (SCHED_IDLE)** | **12 418** | **95.57** | **98.12** | **10.43** | 10 157 |

Rakipsiz referans: TTFT 9 748, ITL p50 86.09, p95 86.71.
Boşluk (S1 − rakipsiz): **TTFT 16 090 ms, ITL p50 296.95 ms.**

| kol | TTFT geri alınan | ITL p50 geri alınan | rakibin bedeli |
|---|---|---|---|
| CPUWeight=1 | %49.1 | %55.5 | −%13.5 |
| **SCHED_IDLE** | **%83.4** | **%96.8** | **−%55.0** |

Her ikisi de p<0.01.

## 2. (a)/(b) ayrıştırması — İŞ 7'nin ana açığı kapandı

İŞ 7'de kalan 8 244 ms'lik artığın iki bileşeni olduğu ve
ayrıştırılmadığı yazılmıştı:

- **(a) uyanma-preemption gecikmesi** — sched_ext'in hedefleyebileceği kısım
- **(b) cache / bant genişliği girişimi** — hiçbir scheduler'ın çözemeyeceği

`SCHED_IDLE`, uyanan normal bir thread'in idle-sınıfı thread'i **derhal**
preempt etmesini garanti eder, yani (a)'yı tanım gereği sıfırlar. Kalan
fark (b)'dir:

| artık | değer | boşluğun oranı |
|---|---|---|
| TTFT | 2 670 ms | %16.6 |
| **ITL p50** | **9.48 ms** | **%3.2** |

**Yani ITL boşluğunun %96.8'i (a) idi.** Decode gecikmesi neredeyse
tamamen bir preemption-gecikmesi problemiymiş — ve çözümü zaten mevcut.

TTFT artığının daha büyük olması (%16.6) tutarlı: prefill compute-bound ve
rakip, LLM'in bıraktığı boşluklarda koşarken LLC'yi kirletiyor. Bu kısım
gerçekten indirgenemez.

## 3. Neden sched_ext bunu iyileştiremez

Akla gelen itiraz şu: `SCHED_IDLE` künt bir alet, rakibi *her zaman*
eziyor; sched_ext yalnızca decode thread'i uyandığında preempt edip geri
kalan zamanda rakibi tam hızda koşturabilir. Böylece S4'ün gecikmesi
S3'ün rakip throughput'uyla birleşir.

Hesap üzerinde bu **+9 340 it/s'lik (+%92) bir Pareto hedefi** gibi
görünüyor. Ama mekanizma bunu desteklemiyor:

`SCHED_IDLE` zaten tam olarak "rakip yalnızca hiçbir normal thread
koşmak istemediğinde koşsun" demektir — yani **iş-koruyucu, katı
öncelikli**. Rakip bu rejimde çekişmesiz hızının hâlâ %40'ını alıyor
(10 157 / 25 429), çünkü LLM decode sırasında bariyerlerde boşluk
bırakıyor ve rakip **tam olarak o boşlukları** dolduruyor.

Rakibe bundan fazlasını vermenin tek yolu, LLM'in koşmak istediği anlarda
ona CPU vermektir — ki bu doğrudan gecikmeyi bozar. **Hedeflenen Pareto
noktası ulaşılabilir değil**, çünkü `SCHED_IDLE` boşluğun tamamını zaten
rakibe veriyor ve fazlasını vermek QoS'tan çalmak demek.

Dolayısıyla sched_ext'in bu senaryoda ekleyebileceği ölçülmüş bir şey yok:
QoS ekseninde artık %3.2 ve o da indirgenemez; throughput ekseninde
`SCHED_IDLE` zaten iş-koruyucu optimumda.

## 4. Bir uyarı: bu kol bir politika önerisi değil

`SCHED_IDLE`, rakibe throughput'unun %55'ine mal oluyor. Bu bir üst sınır
ölçümüdür — (a)'nın büyüklüğünü izole etmek için kuruldu. Gerçek bir
sistemde hangi ayarın seçileceği bir öncelik kararıdır:

| ayar | LLM ITL p50 | rakip |
|---|---|---|
| normal | 383.04 | 22 551 |
| CPUWeight=1 | 218.12 | 19 497 |
| SCHED_IDLE | 95.57 | 10 157 |

Bu üç nokta bir takas eğrisi çiziyor ve **hepsi standart Linux
mekanizmalarıyla erişilebilir.** Ara noktalar (CPUWeight=10, nice+5 vb.)
ölçülmedi ama aynı eğri üzerinde olmaları beklenir.

## 5. Sınırlar

- Ara ağırlık değerleri taranmadı; eğrinin şekli üç noktadan çıkarıldı.
- `SCHED_IDLE` + `CPUWeight` birlikte test edilmedi.
- Rakip sentetik ve doyuran. Gerçekçi bir rakip aynı çekirdeklere
  pinlenirse (b) bileşeni farklı olabilir.
- `n_predict=128`; TTFT ve ITL yüzdelikleri karşılaştırılabilir, toplam
  süreler değil.
- (b)'nin kendisi ayrıştırılmadı (cache mi bant genişliği mi).
