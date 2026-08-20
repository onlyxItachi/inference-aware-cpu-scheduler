# LLM-Aware Scheduling

**Prefill ve decode aynı scheduling kararına zıt tepki veren iki ayrı iş
yüküdür — ve bu ayrım uygulamaya dokunmadan, dışarıdan görülebilir.**

Bu bir scheduler projesi değil, bir **iş yükü karakterizasyonu** projesidir.
Sorulan soru şuydu: *yerel LLM inference'ında, mevcut Linux scheduling
varsayımlarının karşılamadığı şaşırtıcı bir davranış var mı?* Cevap evet
çıktı, ama beklenen yerden değil — ve bulunan şeyi kullanmak için ne kernel
değişikliği ne BPF ne de uygulama yaması gerekti.

**750 koşu, 36 deney, 23 çürütülmüş hipotez.** Hiçbiri silinmedi.

---

## Bulgu

Hibrit bir x86 laptop'ta (8 P-core + 8 E-core), `llama.cpp` CPU-only:

| karar | prefill'e etkisi | decode'a etkisi |
|---|---|---|
| E-core'ları da işe kat | **%13 hızlanıyor** | kuyruk gecikmesi **%9.4 bozuluyor** |

Aynı maske değişimi bir fazda kazanç, diğerinde kayıp. Linux bu iki fazı
birbirinden ayırt etmiyor, çünkü ikisi de aynı process'in aynı thread'leri.

**Statik hiçbir konfigürasyon ikisini birden alamıyor.** Ara noktalar dahil
tüm statik Pareto cephesi ölçüldü (P8, P8+E2, P8+E4, P8+E6, P8+E8) — hem
rakipsiz hem de pencere boyunca koşan gerçek bir `make -j16` altında.
Cephedeki hiçbir nokta her iki eksende birden kazanmıyor.

## Çözüm: dışarıdan faz tespiti + tek bir `sched_setaffinity`

Faz sınırı uygulamanın dışından okunabiliyor. Sinyal:
`/proc/<pid>/task/<tid>/sched` içindeki **CPU-saniye başına context switch
hızı**. Decode her token için tam bir forward pass yapar ve her katmanda
thread'leri senkronize eder; prefill tüm promptu tek pass'te işler. Ayrışma
~5 kat ve sabit bir eşikle ayrılıyor.

Dedektör (`harness/h5_detector_v2.py`, araç hâli `tool/llm-phase-pin`):

- eşik seçiminde kullanılmayan **10 konfigürasyonda %100 recall /
  %99.4 precision** (prompt ≥128 token)
- maliyeti **tek çekirdeğin %1.7'si**
- gecikmesi **negatif**: faz sınırından **115.6 ms önce** karar veriyor.
  Bu bir artefakt değil — llama.cpp'nin içine geçici zaman damgası konularak
  içsel sınıra (`graph_compute(batched=0)`) karşı doğrulandı.

Tespit edilince tek bir maske değişimi uygulanıyor:

```
prefill  ->  P-core + E-core     (compute-bound; çekirdek eklemek işe yarar)
decode   ->  yalnız P-core       (bandwidth-bound; E-core zarar veriyor)
```

### Sonuç: statik cepheyi baskılıyor

Gerçek rakip altında (döngüde `make -j16`, 6 kol × 6 tur, interleaved):

| kol | TTFT (ms) | ITL p50 | ITL p95 | rakip hız | J/token |
|---|---|---|---|---|---|
| A_P8 | 14 421 | 108.89 | 250.26 | **0.3477** | 16.018 |
| P8_E2 | 13 794 | 113.49 | 268.42 | 0.3384 | 16.413 |
| P8_E4 | 13 196 | 119.31 | 276.05 | 0.3320 | 16.672 |
| P8_E6 | 13 085 | 121.76 | 280.82 | 0.3294 | 16.828 |
| C_P8_E8 | 12 628 | 122.01 | 284.06 | 0.3302 | 16.796 |
| **SWITCH** | **12 623** | **108.30** | **247.47** | 0.3395 | **15.399** |

Statik cephe {A_P8, P8_E2, P8_E4, C_P8_E8} — dördünü de SWITCH baskılıyor.
**Hiçbir statik konfigürasyon SWITCH'i baskılamıyor.** Rakipsiz senaryoda
da aynı sonuç ({A_P8, P8_E6, C_P8_E8}, üçü de baskılanıyor).

Welch testi (n=6+6), SWITCH vs A_P8: TTFT **−%12.47** (p<0.01),
J/token **−%3.86** (p<0.01), ITL p95 −%1.11 (ns), ITL p50 −%0.54 (ns),
**rakip hızı −%2.36** (p<0.01).

### Bu bir takastır, iki taraflı kazanç değil

Rakip **yavaşlıyor**: −%2.2 … −%2.4, iki bağımsız deneyde, p<0.01.
LLM'in TTFT'sinde %12'lik kazanç, rakibin throughput'unda %2.4'lük kayıp
karşılığında alınıyor. Takasın oranı elverişlidir ama takas olduğu
yazılmalıdır.

> Bu projenin erken bir sürümünde "rakip de %3.7 hızlanıyor" yazıyordu.
> **Geçersiz:** metrik `build.wait()` yanlış yerde çağrıldığı için rakibi
> değil LLM isteğinin süresini ölçüyordu (§11.2). E-core kullanan her kol
> rakibe zarar veriyor; SWITCH bu grubun **en az** zarar vereni, çünkü
> E-core'ları yalnızca prefill boyunca tutuyor.

---

## Nerede işe yaramaz — bunu okumadan kurmayın

**1. Kısa, cache'li sohbet turlarında.** `cache_prompt=true` ile 2. turdan
itibaren prefill 11 047 ms'den ~870 ms'ye düşüyor ve etki sıfırdan ayırt
edilemez oluyor (−%1.2, ns). 5 turluk bir oturumda toplam bekleme −%8.2 ve
**tamamı ilk turdan** geliyor. Kazanç **uzun prefill'li turlarda** yoğunlaşır:
sohbetin ilk turu, yapıştırılan kod/doküman, RAG, tek atımlık uzun-prompt
işleri. Bu rejimde dedektör de zayıflıyor: 30 cache'li turun 3'ünde anomali
(%10) — turların **%6.7'sinde** prefill'in en başında erken tetikleme (bedeli
o turlarda **%12.8 TTFT**), **%3.3'ünde** decode sürerken geri dönüş, yani
öngörülen arıza modu. Tek turlu rejimde dedektör pratikte kusursuzdu.

**2. `GGML_OPENMP=OFF` derlemesinde.** Spin-wait threadpool'da context switch
sinyali **2 500 kat** düşüyor ve dedektör 6 koşunun 6'sında da hiç
tetiklenmiyor. Kapsam artık ölçülmüş: **bariyerde bloke olan (futex)**
runtime'lar. llama.cpp'nin varsayılan derlemesi OpenMP kullanır. vLLM, ollama
gibi başka motorlar denenmedi.

**3. Çok kısa promptlarda.** 32 token'lık promptta prefill recall %82.7'ye
düşüyor.

**4. E-core'ları doyuran arka plan yükü varsa.** Prefill'e verilecek atıl
kapasite kalmaz; o rejimde E-core açmak nötr değil, küçük ama ölçülebilir
biçimde zararlıdır (TTFT %1.48 kötü, t=+11.37).

**5. LLM ile rakip aynı çekirdekleri paylaşmak zorundaysa.** Orada sorun
yerleşim değil **önceliktir**; aşağıya bakın.

**6. Tek makine, tek runtime, tek model ailesi.** Intel i7-14650HX, CachyOS
kernel 7.1.3, llama.cpp `571d0d5`, Qwen3.5 9B/4B Q4_K_M. Başka CPU, başka
model ailesi, GPU offload — hiçbiri denenmedi. Asimetri 4B'de de var ama
**sömürmenin getirisi model büyüdükçe artıyor** (9B: TTFT −%11.5 / ITL +%9.4;
4B: −%7.4 / +%19.3).

---

## Bugün kullanılabilecek tek satır

LLM ile arka plan işi **aynı çekirdekleri paylaşıyorsa**, rakibi idle
önceliğinde koştur:

```bash
chrt --idle 0 <arka-plan-isi>
```

Gerçek bir iş yüküyle ölçüldü (döngüde `make -j16`):

| | LLM ITL p95 | LLM TTFT | rakibe maliyeti |
|---|---|---|---|
| `chrt --idle` | **−%23.5** | −%10.5 | −%15.2 |
| `CPUWeight=1` | +%1.0 (etkisiz) | −%0.4 (etkisiz) | −%0.5 |

Daemon yok, yama yok, kernel değişikliği yok.

> `CPUWeight=1` bir "ara nokta" olarak önerilmişti; **geri çekildi.**
> Sentetik yükte boşluğun %49'unu alıyordu, gerçek build'de hiçbir şey
> yapmıyor (tüm metriklerde ≤%1, gürültü içinde).

---

## Negatif sonuç: sched_ext'e girilmedi

Proje sched_ext hipoteziyle başladı. **BPF yazılmadı — yazılmasına gerek
olmadığı ölçüldü.** Dört senaryonun dördünde de kazandıran mekanizma
standart Linux'ta mevcut (`sched_setaffinity`, `chrt`).

Mantıksal açığı kapatmak için hazır scx scheduler'ları da ölçüldü
(`scx_lavd`, `scx_rustland`, kullanıcı onayıyla, her yükleme öncesi/sonrası
`sched_ext/state` loglanarak): **hiçbiri en iyi kullanıcı-alanı çözümünü
yenemedi.** Sistemdeki 13 scx scheduler'ından yalnızca ikisi, varsayılan
ayarlarla denendi.

sched_ext'in kalan tek teorik adayı: birbirinden habersiz çoklu LLM
process'leri (S4) — ölçülmedi.

---

## Metodoloji notları

**Gürültü tabanı tek bir sayı değil.** Proje boyunca %2 varsayıldı; bu
varsayım da çürütüldü. Taban hem metriğe hem senaryoya bağlı:

| metrik | ölçülen taban |
|---|---|
| **ITL p95** (birincil) | **%0.7** rakipsiz / **%5.20** aralıklı rakip / **%1.36–1.51** sürekli rakip |
| TTFT | %0.38–1.06 çoğu deneyde — ama scx deneyinde **%3.12** |
| ITL p50 | %0.31–0.76, deneye göre |
| J/token | %0.56–0.63, deneye göre |

Tek bir taban her yere uygulanamıyor: %2 varsayımı kimi yerde fazla gevşek,
kimi yerde fazla sıkıydı ve bu raporda bir sonucu **her iki yönde de** yanlış
etiketledi. Aynı büyüklükteki bir fark bir senaryoda bulgu, diğerinde
gürültüdür. Her
iddia kendi deneyinin tabanına karşı sunulur; kritik karşılaştırmalarda
CV bandı değil Welch testi kullanılır (CV sezgisi n=6'da gerçek bir farkı
bir kez gürültüye gömdü).

**Ortalama token/sn yetersizdir.** Birincil metrik ITL p50/p95/p99
dağılımıdır; ortalama throughput aradaki takılmaları gizler ve avlanan şey
tam olarak odur. Her koşu token başına zaman damgası kaydeder.

**Her koşu için yeni sunucu + `cache_prompt=false`.** Aksi hâlde 2. koşudan
itibaren prefill'i değil prompt cache'ini ölçerdik. `temperature=0` +
`ignore_eos=true` ile iş yükü byte-for-byte tekrarlanabilir; koşular arası
fark sampling değil makine gürültüsüdür.

**Harness'ın sıfır bağımlılığı var** — sadece Python stdlib, `perf` bile yok.
Migration ve context switch sayıları `/proc/<pid>/task/<tid>/sched`'den
okunuyor: root istemiyor, tracing overhead'i eklemiyor, ve process başına
değil **thread başına** sayı veriyor.

---

## Depo haritası

```
README.md                 bu dosya
CLAUDE.md / AGENTS.md     proje tanımı + başarı ölçütü (REVİZYON 0/1/2, hepsi korundu)
PAPER.md                  makale taslağı (İngilizce, 6 sayfalık workshop formatı)
MAKALE_ISKELET.md         makale iskeleti

RAPOR_FINAL.md            *** OTORİTE *** kapanış raporu + hakem itirazlarına
                          karşı ölçümler (§11)
RAPOR.md                  Faz 0 + erken Faz 1        \
RAPOR_FAZ1.md             H5, bandwidth, BLAS         | tarihsel kayıt;
RAPOR_FAZ1_KAPANIS.md     ölçüt dondurma, E-core      | bazı sayıları
RAPOR_FAZ2_ESIK.md        faz anahtarlama, ubatch     | RAPOR_FINAL §6/§11'de
RAPOR_FAZ2_DEVAM.md       gerçekçi rakip, öncelik    /  düzeltildi

harness/                  ölçüm altyapısı, sıfır bağımlılık — harness/README.md
tool/llm-phase-pin        faz-farkındalıklı pinning daemon'ı — tool/README.md
patches/                  llama.cpp yaması (uygulama-bilgili yerleşim karşılaştırması)
results/                  36 deney; her dizinde elle yazılmış FINDINGS.md
llama.cpp/                submodule, commit 571d0d5
models/                   symlink, depo dışı
```

**Çelişki görürsen `RAPOR_FINAL.md` geçerlidir.** §6 (çürütülen 23 hipotez)
ve §11 (hakem itirazları) eski raporlardaki ve `tool/README.md`'deki bazı
sayıları geçersiz kılar. Hiçbiri silinmedi — dondurma kuralı, iddiaların
sonuca göre sessizce değiştirilmediğinin denetlenebilir olmasını gerektirir.

---

## Tekrar üretme

```bash
git submodule update --init            # llama.cpp @ 571d0d5

# Ölçümlerde kullanılan bayraklar (record_env.sh bunları kaydeder).
# GGML_OPENMP AÇIK kalmalı — kapalıysa faz sinyali tamamen kayboluyor.
cmake -S llama.cpp -B llama.cpp/build \
      -DCMAKE_BUILD_TYPE=Release \
      -DGGML_CUDA=OFF -DGGML_BLAS=OFF -DGGML_VULKAN=OFF \
      -DGGML_NATIVE=ON \
      -DLLAMA_CURL=OFF -DLLAMA_BUILD_TESTS=OFF
cmake --build llama.cpp/build -j

# models/ depo dışına symlink; GGUF'ları oraya koyun
```

Faz 0 (gürültü tabanı):

```bash
./harness/record_env.sh

python3 harness/noise_floor.py \
  --server-bin llama.cpp/build/bin/llama-server \
  --model models/Qwen3.5-9B-Q4_K_M.gguf \
  --threads 8 --runs 20 --cooldown 30 \
  --outdir results/phase0

python3 harness/analyze.py --csv results/phase0/runs.csv --outdir results/phase0
```

Aracı denemek:

```bash
tool/llm-phase-pin --match llama-server --dry-run   # önce izleyin
tool/llm-phase-pin --match llama-server             # sonra uygulayın
```

Ctrl+C ile çıkınca orijinal affinity maskesi geri yüklenir. P/E çekirdek
numaraları `sysfs`'ten çıkarılır, gömülü değildir.

**Ölçüm hijyeni (CLAUDE.md kural 7):** koşu sırasında tarayıcı, IDE, arka
plan derlemesi olmamalı. Koşular arası soğuma payı bırakılır, sıcaklık her
koşuda kaydedilir. Ham JSON/log çıktıları (`results/**/*.json`, `*.log`,
`*.passes`, `*.load`, `*.serverlog`) gitignore'da — büyükler ve harness'tan
yeniden üretilebilir. Depoda tutulanlar: özet **CSV**'ler, otomatik raporlar
ve her deneyin elle yazılmış **`FINDINGS.md`**'si.

---

## Durum

Araştırma çıktısı, üretim yazılımı değil. Ölçüm verisi ve metodoloji
`results/` ve `RAPOR_FINAL.md` içinde.

MIT lisanslı ([`LICENSE`](LICENSE)). Submodule olarak çekilen `llama.cpp` de
MIT'tir ve kendi lisansı altında kalır.
