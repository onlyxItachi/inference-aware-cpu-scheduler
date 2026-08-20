# İŞ 5 — llama.cpp thread havuzu runtime'da ayrılabiliyor mu?

**Cevap ikiye ayrılıyor: thread SAYISI evet, CPU AFFINITY hayır (server'da).**

Bu, Faz 2'nin kapsamını belirleyen teknik ön koşuldu.

---

## 1. Kaynak incelemesi

### Var olanlar

| yetenek | nerede | durum |
|---|---|---|
| `llama_set_n_threads(ctx, n_threads, n_threads_batch)` | `include/llama.h:973` | public API, runtime |
| İki ayrı threadpool | `llama-context.h:355` (`threadpool`, `threadpool_batch`) | mimaride var |
| Faza göre havuz seçimi | `llama-context.cpp:2442`: `batched ? threadpool_batch : threadpool` | **prefill/decode ayrımı zaten yapılıyor** |
| CPU maskesi | `ggml.h:2912`: `cpumask[]`, `strict_cpu` | threadpool parametresi |
| CLI bayrakları | `arg.cpp`: `-C/--cpu-mask`, `-Cb/--cpu-mask-batch`, `--cpu-strict` | parse ediliyor |

### Eksik olan

`ggml_threadpool_new` ve `llama_attach_threadpool` çağrıları **yalnızca**:

- `tools/completion/completion.cpp:202` (llama-cli)
- `tools/llama-bench/llama-bench.cpp:2328`

**`tools/server/server.cpp` bu çağrıları hiç yapmıyor.** Dolayısıyla
llama-server'da `-C/-Cb` maskeleri parse edilip **sessizce yok sayılıyor**.

Buna karşılık thread *sayısı* server'a bağlı:
`common.cpp:1599-1600` → `cparams.n_threads` ← `-t`,
`cparams.n_threads_batch` ← `-tb`.

Kurulum bloğu `completion.cpp:184-202`, yaklaşık **25 satır**.

## 2. Ampirik doğrulama (15 koşu, 5 tur interleaved)

| kol | cpus | -t | -tb | prefill | TTFT | decode | ITL p95 |
|---|---|---|---|---|---|---|---|
| A | P8 | 8 | 8 | 45.14 | 10 989 | 11.62 | 86.72 |
| B | P8+E8 | 8 | 16 | **51.14** | 9 700 | 10.13 | **104.77** |
| C | P8+E8 | 16 | 16 | 51.13 | 9 701 | 10.55 | 98.80 |

A'ya karşı:

| | B (-t8 -tb16) | C (-t16 -tb16) |
|---|---|---|
| prefill | **+%13.3** (p<0.01) | +%13.3 (p<0.01) |
| TTFT | −%11.7 (p<0.01) | −%11.7 (p<0.01) |
| decode | −%12.8 (p<0.01) | −%9.1 (p<0.01) |
| ITL p95 | **+%20.8** | +%13.9 |

*(ITL p95'te Welch df'i n=5'te küçük kaldığı için etiket üretilmedi; etki
gürültü tabanının ~10 katı.)*

### İki sonuç

**(a) `-tb` gerçekten çalışıyor.** B, prefill kazancının tamamını alıyor
(+%13.3, C ile birebir aynı). llama-server'ın faz-başına thread sayısı
ayrımı işlevsel — kaynak okuması ampirik olarak doğrulandı.

**(b) Ama affinity olmadan yetmiyor.** B'nin ITL p95'i **+%20.8**, hatta
C'den (+%13.9) *daha kötü*. Sebep: B'nin 8 decode thread'i P+E cpuset'inde
serbest yüzüyor ve bir kısmı E-core'a düşüyor; C'de en azından 16 thread
tüm çekirdekleri kaplayıp her fiziksel çekirdekte iş tutuyor.

**Yani İŞ 4'ün politikası ("prefill'de P+E, decode'da yalnız P") thread
sayısıyla yaklaşık olarak bile kurulamıyor. Affinity ayrımı şart.**

## 3. Faz 2 için üç yol

| yol | maliyet | katkının adı |
|---|---|---|
| (1) llama-server'a ~25 satır yama | en ucuz | "uygulama kendi yerleşimini yapıyor" |
| (2) llama-cli kullanmak | sıfır kod | ama SSE token zaman damgaları kaybolur — harness'ın temeli |
| (3) userspace daemon + `sched_setaffinity` | orta | **"OS iş yükünü anlıyor"** |

**(3) projenin tezine en uygun olanı** ve dikkat çekici bir özelliği var:
uygulamayı hiç değiştirmeden, herhangi bir process üzerinde çalışır — ve
**sched_ext gerektirmez**. Gereken iki parça da elimizde:

- faz tespiti: H5 doğrulandı (%99.6, −135 ms erken uyarı, %1.7 daemon maliyeti)
- yerleşim değiştirme: `sched_setaffinity`, sıradan bir syscall

## 4. Bunun projenin çerçevelemesine etkisi

Ortaya çıkan soru şu: **faz-farkındalıklı yerleşim kullanıcı alanında
yapılabiliyorsa, sched_ext'in katkısı ne?**

llama.cpp'nin kendi mimarisi zaten iki fazı ayırıyor (iki threadpool,
`batched ? ... : ...`). Yerleşim de daemon'dan yapılabiliyor. sched_ext'in
savunulabilir katkısı, bu ikisinin **yapamayacağı** şey olmalı — aday:
birbirinden habersiz birden fazla process'i koordine etmek, ya da rakip iş
yükünü LLM'in fazına göre yönetmek (ki dondurulmuş ölçütün amacı da tam
olarak budur).

**Önerilen Faz 2 sıralaması:** önce daemon + `sched_setaffinity` ile
politikayı kur ve dondurulmuş ölçüte karşı ölç. sched_ext'e ancak bu
yetersiz kalırsa geç — o zaman sched_ext'in neyi *ek olarak* sağladığı
ölçülmüş olur. Bu, CLAUDE.md'nin "ML en son girer, belki hiç girmez"
ilkesiyle aynı mantık.

## 5. Sınırlar

- Yama (yol 1) denenmedi; `completion.cpp` bloğunun server'a taşınmasının
  gerçekten yeterli olduğu **varsayım**, ölçülmedi.
- Daemon + `sched_setaffinity` yaklaşımının faz geçişinde thread'leri
  taşıma maliyeti (migration + cache kaybı) ölçülmedi. İronik biçimde bu,
  projenin "migration sayısı önemsiz" bulgusuyla test edilebilir bir
  gerilim oluşturuyor.
- Tek prompt uzunluğu (496) ve tek üretim uzunluğu (256).
