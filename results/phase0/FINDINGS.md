# Faz 0 — Gürültü Tabanı: Sonuç

**Tarih:** 2026-07-18
**Konfigürasyon:** pinsiz, `--threads 8`, boş sistem, 20 koşu, koşular arası 30 sn
**Model:** Qwen3.5-9B-Q4_K_M (5.68 GB)
**llama.cpp:** commit `571d0d5`, CPU-only, `-march=native` (AVX2)
**Prompt:** 496 token sabit metin, 256 token üretim, greedy (`temperature=0`,
`ignore_eos=true`) — yani her koşu birebir aynı işi yapıyor.

Ham veri: `runs.csv`, token zaman damgaları: `tokens/`, otomatik analiz:
`report.md`, ortam: `env.txt`.

---

## 1. Ana sayı

| metrik | medyan | CV% | tekrarların %95'i |
|---|---|---|---|
| TTFT | 12127.7 ms | 0.5% | ±0.9% |
| ITL p50 | 98.07 ms | 0.5% | ±1.1% |
| ITL p95 | 103.52 ms | 0.7% | ±1.4% |
| ITL p99 | 105.97 ms | 1.0% | — |
| ITL max | 107.79 ms | 1.5% | — |
| decode | 10.17 tok/s | 0.5% | ±1.1% |

**K3'ün cevabı: bu makinede %2'den küçük farklar gürültüdür.**

Bu eşik iki bileşenden geliyor: koşular arası saçılım (en geniş metrik olan
ITL p95 için ±%1.4) ve aşağıda anlatılan oturum içi drift (~%0.8). İkisi
toplanınca güvenli eşik %2 oluyor. Projenin geri kalanında bunun altındaki
hiçbir fark bulgu olarak raporlanmayacak.

## 2. Beklenenden iyi çıktı

CLAUDE.md K3'te laptop varyansının %10'u aşabileceği yazıyordu. Ölçülen
%0.5–1.5. Yani korkulan senaryo gerçekleşmedi ve manevra alanı beklenenden
geniş: sonraki fazlarda %3–5'lik efektler bile gürültünün üstünde kalır.

Bunun muhtemel sebebi iş yükünün kendisi. Aşağıda görüleceği gibi decode
bellek bant genişliğine dayanmış durumda; bant genişliği ise frekans ve
çekirdek seçiminden çok daha kararlı bir kaynak. Ölçtüğümüz şey büyük ölçüde
RAM'in hızı, ve RAM turbo yapmıyor.

## 3. Drift var — ve termal değil

TTFT koşu numarasıyla anlamlı biçimde korele: **r = +0.671** (n=20 için
p<0.05 eşiği 0.444), eğim **+6.5 ms/koşu**. İlk 10 ve son 10 koşunun
medyanları:

| metrik | ilk 10 | son 10 | fark |
|---|---|---|---|
| TTFT | 12081.9 ms | 12171.6 ms | **+0.74%** |
| ITL p95 | 103.23 ms | 104.10 ms | **+0.84%** |
| decode | 10.21 tok/s | 10.13 tok/s | **−0.78%** |
| migrations | 8095 | 8185 | +1.11% |

Üç performans metriği de aynı yönde, yaklaşık aynı büyüklükte kötüleşiyor.
Tesadüf değil; sistem oturum boyunca yavaşça yavaşlıyor.

**Ama sebebi paket sıcaklığı değil.** Başlangıç sıcaklığı ile hiçbir metrik
anlamlı korele değil (TTFT r=+0.25, ITL p95 r=−0.22, decode r=−0.10; hepsi
0.444 eşiğinin altında). Sıcaklık 20 koşuda 57°C'den ancak 60°C'ye tırmandı
ve bitiş sıcaklığının koşu numarasıyla korelasyonu bile anlamlı değil
(r=+0.38).

Yani **elimizde açıklanamayan ~%0.8'lik bir oturum içi drift var.** Bu
veriyle sebebini söyleyemem — tahmin etmeyeceğim. Sayfa cache durumu, bellek
parçalanması, uzun süreli turbo bütçesi ya da tamamen başka bir şey olabilir.
Faz 1'de sıcaklığın yanında bunları da kaydetmek gerekecek.

### Bunun metodolojik sonucu

Konfigürasyonlar **blok halinde** ölçülmemeli. "Önce 20 koşu A, sonra 20 koşu
B" yapılırsa, drift A ile B arasında %0.8'lik sahte bir fark üretir — ki bu
aramaya değer efektlerin bir kısmıyla aynı mertebede. Faz 1'den itibaren
**koşu sırası konfigürasyonlar arasında karıştırılacak (interleaved).**

Bu, gürültü tabanının kendisinden daha önemli bir bulgu olabilir: 30 saniyelik
soğuma payı yeterli sanılıyordu, değil.

## 4. Kayda değer ham gözlemler (Faz 1'in işi, burada peşine düşülmedi)

Bunlar Faz 0'ın sorusu değil ama veri zaten toplandı, not düşüyorum:

- **Decode bant genişliğine dayanmış olabilir.** Token başına 10.17 tok/s ×
  5.68 GB = ~57.8 GB/s. DDR5 dual-channel'ın pratik tavanına çok yakın.
  K1'in ("çekirdek eklemek işe yarar mı?") cevabı büyük ihtimalle "hayır",
  ama bu **thread taraması yapılmadan söylenemez** — K1 ölçümü 2→4→6→8
  thread ile yapılacak.
- **Koşu başına ~8125 thread migration.** ~38 saniyelik bir koşuda saniyede
  ~214 migration. H3 ("migration token gecikmesini etkiliyor mu?") için
  doğrudan malzeme.
- **Koşu başına ~2.1 milyon context switch**, yani üretilen token başına
  ~8200 tane. 34 thread'li bir süreçte bu, her katmanda OpenMP bariyer
  senkronizasyonuna işaret ediyor. Prefill/decode ayrımının dışarıdan
  görülebilirliği (H5) açısından ilginç bir sinyal olabilir.
- **Prefill / decode oranı yalnızca ~4×** (40 tok/s vs 10 tok/s). CPU'da
  beklenenden dar bir aralık; iki fazın kaynak profilinin ne kadar
  ayrıştığı sorusuna bağlanıyor.

## 5. Faz 0 durumu

Harness kuruldu ve doğrulandı (TTFT, sunucunun kendi `prompt eval time`
değeriyle 30 ms içinde uyuşuyor). K3 cevaplandı. **Eşik: %2.**

Faz 0'ın kalanı — tüm baseline'lar (EEVDF / lavd / rustland) ve affinity
varyantları (pinsiz / P-noSMT / P-SMT / E-only), S1 ve S2 altında — henüz
ölçülmedi. Sıradaki iş o; ve artık interleaved sırayla ölçülecek.
