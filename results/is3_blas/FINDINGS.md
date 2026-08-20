# İŞ 3 — BLAS karıştırıcısı: asimetri derleme artefaktı mı?

**Cevap: HAYIR. Prefill yapay olarak zayıf değil; 4.4'ün iddiası ayakta.**

Endişe meşruydu: prefill 45 tok/s ölçülmüştü ve "9B Q4/AVX2 için düşük
olabilir" denmişti. Düşükse, ölçtüğümüz prefill/decode asimetrisinin bir
kısmı iş yükünün değil derlemenin özelliği olurdu.

Üç bağımsız kontrol yapıldı.

---

## 1. Mevcut derleme zaten optimize GEMM yolunda

`build/CMakeCache.txt`: **`GGML_LLAMAFILE=ON`** — llama.cpp'nin kendi
optimize CPU GEMM yolu (tinyBLAS) derlenmiş ve binary'de sembolleri var.
Yani derleme "BLAS'sız" değil, llama.cpp'nin *önerdiği* yapılandırmada.

## 2. tinyBLAS açık/kapalı: fark yok

| derleme | prefill | decode |
|---|---|---|
| mevcut (`GGML_LLAMAFILE=ON`) | 45.0 tok/s | 11.23 tok/s |
| `GGML_LLAMAFILE=OFF` | 45.2 tok/s | 11.54 tok/s |

Fark %2 eşiğinin içinde. **Beklenen sonuç:** Q4_K_M nicelenmiş ağırlıklarda
matris çarpımı ggml'in kendi quantized dot-product kernel'lerinden geçiyor;
tinyBLAS esas olarak F16/F32 yolları için. Yani bu model formatında
tinyBLAS zaten devrede değil.

## 3. Referans BLAS: 40 kat DAHA KÖTÜ

`GGML_BLAS=ON` ile derlendi (netlib referans BLAS, `libcblas` + `libblas`;
`cblas_sgemm` sembolü için bağlantı elle düzeltildi):

| derleme | prefill | TTFT | decode |
|---|---|---|---|
| mevcut | 45.0 tok/s | 11 013 ms | 11.23 tok/s |
| **BLAS=ON (referans)** | **1.1 tok/s** | **440 202 ms** | 11.52 tok/s |

**Prefill 40 kat yavaşladı.** Sebebi: llama.cpp BLAS yolunda Q4_K
ağırlıkları önce F32'ye açmak zorunda, sonra optimize olmayan tek-thread
netlib `cblas_sgemm` çağırıyor. Decode değişmedi (11.52) — beklendiği gibi,
BLAS yalnızca batch/prompt yolunu etkiliyor.

## 4. Roofline: prefill donanım tavanının %72'sinde

Karıştırıcı sorusunun asıl cevabı bu — göreli karşılaştırma değil, mutlak
verim:

```
prefill iş yükü = 2 × N_param × N_token = 2 × 9e9 × 496 = 8.93 TFLOP
ölçülen         = 8.93 TFLOP / 11.013 s = 811 GFLOPS
AVX2 fp32 tavanı = 8 çekirdek × 4.4 GHz × 32 flop/cycle = 1126 GFLOPS
                   (8 float/vektör × 2 FMA × 2 FMA birimi)
```

**811 / 1126 = %72.**

İyi optimize edilmiş gerçek bir GEMM tipik olarak teorik tavanın %70–90'ını
alır. Prefill bu bandın içinde. **Yapay olarak zayıf değil, donanımın
yakınında çalışıyor.**

## 5. Yapılmayan ve nedeni

Brief "K1 taramasını BLAS binary'siyle tekrarla" diyordu. **Yapılmadı**,
kullanıcı onayıyla:

- Bu makinede **optimize BLAS yok**; yalnızca netlib referans BLAS kurulu.
- Onunla K1 taraması koşu başına 440 s TTFT demek → 30 koşu ≈ **6+ saat**,
  ve ölçülen şey "optimumun 40 katı uzağındaki bir konfigürasyonun
  ölçeklenmesi" olurdu — karıştırıcı sorusuna cevap vermez.
- Karıştırıcı sorusu zaten 1–4 ile kapandı.

OpenBLAS indirme seçeneği sunuldu (~30-40 MB) ama alınmadı; ayrıca Q4_K_M'de
BLAS yolu F32'ye açmayı gerektirdiği için optimize BLAS'ın bile native
quantized kernel'leri geçmesi beklenmiyor.

---

## Sonuç: 4.4'ün iddiası zayıflatılmadı

Asimetri (**prefill %77 / decode %49 ölçeklenme verimi**) bir derleme
artefaktı değil. Üstelik artık **iki tarafı da mekanik olarak açıklanmış**
durumda:

- **Prefill neden iyi ölçekleniyor:** compute-bound ve donanım tavanının
  %72'sinde; çekirdek eklemek doğrudan FLOPS ekliyor.
- **Decode neden kötü ölçekleniyor:** İŞ 2 bandwidth-bound olduğunu
  gösterdi (iki bağımsız örnek toplamı yalnızca +%7.4).

Asimetri ölçülmüş bir olgu olmaktan çıkıp **açıklanmış** bir olguya
dönüştü.
