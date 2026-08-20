# llm-phase-pin

llama.cpp'nin **prefill** ve **decode** fazlarını dışarıdan tespit edip CPU
affinity'sini fazına göre değiştiren küçük bir daemon. Uygulamaya
dokunmuyor, kernel değişikliği istemiyor, yalnızca Python stdlib.

```
prefill  ->  P-core + E-core     (compute-bound, çekirdek eklemek işe yarar)
decode   ->  yalnız P-core       (bandwidth-bound, E-core zarar veriyor)
```

## Kurulum

```bash
cp llm-phase-pin ~/.local/bin/ && chmod +x ~/.local/bin/llm-phase-pin
```

Bağımlılık yok. Root gerekmez — kendi süreçlerinize affinity uygulamak
için yeterli yetkiniz zaten var.

## Kullanım

```bash
# Önce izleyin, hiçbir şey değiştirmeden
llm-phase-pin --match llama-server --dry-run

# Memnunsanız gerçekten uygulayın
llm-phase-pin --match llama-server

# Ya da PID ile
llm-phase-pin --pid 12345
```

Ctrl+C ile çıkınca **orijinal affinity maskesi geri yüklenir**.

P/E çekirdek numaraları `sysfs`'ten otomatik çıkarılır; makineye özgü
numara gömülü değildir.

---

## Ne kadar kazandırır — ve nerede kazandırmaz

Bu bölüm dürüst olsun diye ayrıntılı. Aracı kurup hayal kırıklığına
uğramanız, işe yaramadığını sanmanızdan daha kötü.

### Kazandırdığı yer: uzun prefill'li turlar

Ölçülen (9B Q4_K_M, 496 token prompt, 8 P-core + 8 E-core):

| durum | TTFT | ITL p95 | arka plan derlemesi |
|---|---|---|---|
| statik P-core pinning | 11 743 ms | 90.42 ms | 35.70 s |
| **llm-phase-pin** | **10 480 ms** | **86.54 ms** | **34.37 s** |

**TTFT −%10.8, ITL p95 −%4.3, ve arka planda koşan `make -j16` de %3.7
daha hızlı bitiyor.** Takas değil; prefill erken bittiği için E-core'lar
rakibe daha erken geri dönüyor.

Somut senaryolar:
- Yeni bir sohbetin ilk turu (sistem promptu + bağlam)
- Yapıştırılan kod/doküman
- RAG — her istekte büyük bağlam
- `cache_prompt` kapalı kurulumlar
- Tek atımlık uzun-prompt işleri: özetleme, çeviri, kod analizi

### Kazandırmadığı yerler

**Cache'li kısa sohbet turları.** `cache_prompt=true` ile 2. turdan
itibaren prefill yalnızca yeni tokenları işler ve 11 000 ms'den ~870 ms'ye
düşer. Ölçülen etki: **−%1.2, istatistiksel olarak sıfırdan ayırt
edilemiyor.** 5 turluk bir sohbette toplam kazanç %8.2 ve tamamı ilk
turdan geliyor.

Bu yüzden `--min-prefill-ms` (varsayılan 300) var: prefill bu süreyi
geçmeden E-core açılmıyor. Kazanç zaten yalnızca uzun prefill'de olduğu
için bu koruma bedava, ve kısa turlarda politikayı hiç devreye sokmuyor.

**E-core'ları doyuran arka plan yükü.** Arka planda E-core'ları tamamen
dolduran bir iş varsa (ör. 16 thread'lik hesap yükü oraya pinlenmişse)
prefill'e verilecek atıl kapasite kalmaz; ölçülen fark gürültü içinde
kalıyor.

**GGML_OPENMP=OFF ile derlenmiş llama.cpp.** Aşağıya bakın — bu araç
orada **hiç çalışmaz**.

---

## Nasıl çalışıyor

Sinyal: `/proc/<pid>/task/<tid>/sched` içindeki `nr_switches` toplamının
**CPU-saniye başına** oranı.

Decode her token için tam bir forward pass yapar ve her katmanda
thread'leri senkronize eder. Prefill ise tüm promptu tek pass'te işler.
Sonuç: decode saniyede yüz binlerce context switch üretirken prefill
neredeyse hiç üretmez. Ölçülen ayrışma **~5 kat**, ve sabit bir eşikle
ayrılabiliyor.

CPU-saniyeye normalize etmek, sinyali çekirdek sayısından büyük ölçüde
bağımsız kılıyor — politika maskeyi daralttığında sinyal çökmüyor.

### Nereden geldi bu varsayılanlar

| bayrak | varsayılan | gerekçe |
|---|---|---|
| `--hi` | 3000 | ölçülen prefill p99'un (1589) ~1.9 katı |
| `--lo` | 2100 | ölçülen decode p1'in (4307) ~0.49 katı; histerezis bandı |
| `--k` | 2 | tek örneklik sapmaları filtreler; salınımı önleyen asıl mekanizma bu |
| `--interval-ms` | 100 | doğruluk 20 ms ile aynı, maliyet tek çekirdeğin %1.7'si |
| `--min-prefill-ms` | 300 | kısa cache'li turlarda politikayı devre dışı bırakır |

Tespit gecikmesi **negatif**: dedektör faz sınırından ~115 ms *önce*
karar veriyor. Bu ölçüldü ve bir artefakt olmadığı llama.cpp'nin içine
geçici zaman damgası koyularak doğrulandı.

---

## Sınırlar — okumadan kurmayın

**1. OpenMP şart.** `-DGGML_OPENMP=OFF` ile derlenmiş llama.cpp ggml'in
kendi spin-wait threadpool'unu kullanır. Ölçülen: context switch sayısı
**6 200 kat** düşüyor (koşu başına 2 028 081 → 328) ve sinyal tamamen
kayboluyor. Alternatif kanallar (CPU kullanımı, çalışan süreç sayısı) da
faz ayrımı vermiyor. Bu derlemede araç bir işe yaramaz — `--dry-run` ile
kontrol edin, faz geçişi göremezsiniz.

**2. Tek yapılandırmada ölçüldü.** Intel i7-14650HX (8 P + 8 E),
CachyOS kernel 7.1.3, llama.cpp `571d0d5`, CPU-only, Qwen3.5 9B/4B Q4_K_M.
Başka CPU, başka model ailesi, GPU offload — hiçbiri denenmedi.

**3. Kazanç model boyutuyla küçülüyor.** 4B modelde prefill kazancı %13
yerine %8, ITL hasarı ise %9.4 yerine %19.3. Küçük modellerde politikanın
değeri tartışmalı.

**4. Kısa promptlarda dedektör zayıflıyor.** 32 token'lık promptta prefill
recall %82.7'ye düşüyor (uzun promptta ≥%94.7). Çok turlu cache'li
kullanımda 30 turun 3'ünde anormal geçiş gözlendi.

**5. Çoklu sunucu desteklenmiyor.** Tek PID izler.

---

## İlgili: paylaşılan çekirdek durumu

LLM ile arka plan işi **aynı çekirdekleri paylaşmak zorundaysa** (ör.
ikisi de aynı P-core'lara pinliyse) bu araç yardımcı olmaz — orada sorun
yerleşim değil, önceliktir. Ölçülen en iyi çözüm standart Linux'ta:

```bash
chrt --idle 0 <arka-plan-isi>
```

Bu, ITL gecikme boşluğunun **%96.8'ini** geri alıyor. Bedeli arka plan
işinin throughput'unun ~%55'i. Ara nokta isteyenler için:

```bash
systemd-run --user --scope -p CPUWeight=1 <arka-plan-isi>   # boşluğun %49'u, maliyet %13.5
```

---

## Lisans / durum

Araştırma çıktısı, üretim yazılımı değil. Ölçüm verisi ve metodoloji
projenin `results/` ve `RAPOR_FINAL.md` dosyalarında.
