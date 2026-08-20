# Faz 0 Harness

Ölçüm altyapısı. Scheduler yok, `scxctl` yok — sadece ölçüm.

## Bağımlılıklar

Yok. Sadece Python stdlib. Bilinçli bir tercih: harness'ın kendisi
ölçtüğü makineyi kirletmemeli ve bir paket ortamı olmadan
tekrarlanabilir olmalı.

`perf` de kullanılmıyor. Migration ve context switch sayıları
`/proc/<pid>/task/<tid>/sched` içindeki `se.nr_migrations` ve
`nr_switches` alanlarından okunuyor. Bu yaklaşım:

- root istemiyor,
- tracing overhead'i eklemiyor,
- process başına değil **thread başına** sayı veriyor — ki faz
  hipotezleri (H1, H3) tam olarak bunu gerektirecek.

## Dosyalar

| dosya | işi |
|---|---|
| `bench_lib.py` | sensörler, sched sayaçları, frekans örnekleyici, istatistik |
| `run_once.py` | tek ölçüm koşusu: sunucuyu başlat, stream et, token başına zaman damgası al |
| `noise_floor.py` | aynı konfigürasyonu N kez koşar, CSV'ye yazar |
| `analyze.py` | yayılım + drift + termal korelasyon → `report.md` + SVG |
| `record_env.sh` | commit, derleme bayrakları, model SHA, CPU/governor durumu |
| `prompt_512.txt` | sabit prompt, 496 token |

## Ölçüm tasarımındaki kritik kararlar

**Her koşu için yeni sunucu.** `llama-server` istekler arasında prompt
prefix'ini cache'liyor. Sabit prompt ile 2. koşudan itibaren TTFT sıfıra
çökerdi — prefill'i değil cache'i ölçerdik. Hem sunucu yeniden başlatılıyor
hem de `cache_prompt=false` gönderiliyor.

**`temperature=0` + `ignore_eos=true`.** Her koşu birebir aynı işi
yapmalı. Greedy decoding ve zorunlu token sayısı ile iş yükü
byte-for-byte tekrarlanabilir; koşular arası fark sampling değil
**makine gürültüsü** olur. Faz 0'ın bütün amacı bu.

**Prompt 496 token, `ubatch=512`'nin altında.** 512'yi aşsaydı prompt iki
ubatch'e bölünür, prefill'e bir batch sınırı girerdi. Tek ubatch daha
temiz bir prefill baseline'ı veriyor.

**Warmup farklı bir promptla.** Allocator ve compute buffer'ları
ısıtır ama ölçülecek promptu cache'e sokmaz.

**Frekans: aktif çekirdek ortalaması.** `-t 8` ile 16 mantıksal P-core'un
yarısı boşta ve 800 MHz'de duruyor; düz ortalama bunu seyreltiyor
(2427 MHz gösteriyordu, aktif çekirdekler 3954 MHz'deyken).
`freq_p_busy_mhz` en yüksek N çekirdeğin ortalaması.

## Doğrulama

Harness'ın TTFT'si sunucunun kendi `prompt eval time` değeriyle
30 ms içinde uyuşuyor (11538 ms vs 11508 ms) — aradaki fark HTTP + SSE
overhead'i.

## Kullanım

```bash
./harness/record_env.sh

python3 harness/noise_floor.py \
  --server-bin llama.cpp/build/bin/llama-server \
  --model models/Qwen3.5-9B-Q4_K_M.gguf \
  --threads 8 --runs 20 --cooldown 30 \
  --outdir results/phase0

python3 harness/analyze.py \
  --csv results/phase0/runs.csv \
  --outdir results/phase0
```

## Ölçüm hijyeni

Koşu sırasında tarayıcı / IDE / arka plan derlemesi olmamalı
(CLAUDE.md kural 7). VS Code'un dosya izleyicileri ve extension'ları
düzensiz CPU spike'ı üretir ve tam ölçmeye çalıştığımız varyansa karışır.
