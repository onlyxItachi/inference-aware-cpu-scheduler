# S2 — Rakip iş yükü altında: Sonuç

**Tasarım:** 6 tur × 4 kol = 24 koşu, interleaved (`order-seed=21`).
Yük: 16 always-runnable thread (`harness/loadgen.c`, bağımlı FP zinciri —
kasıtlı olarak compute-bound, ki K1'in açık bıraktığı bandwidth sorusunu
karıştırmasın). Yük talebi her kolda sabit; yalnızca yerleşim değişiyor.
Eşik: %2.

| kol | LLM | yük | TTFT | ITL p50 | ITL p95 | decode | migration |
|---|---|---|---|---|---|---|---|
| A | P-core | yok | 11018 | 85.96 | 90.01 | 11.58 | 2 990 |
| B | serbest | serbest | 17640 | 100.87 | 103.56 | 9.88 | 20 335 |
| C | P-core | serbest | 17739 | 101.39 | **121.95** | 9.66 | 48 314 |
| D | P-core | E-core | **11550** | **87.77** | **88.75** | **11.37** | 12 611 |

---

## 1. Ucuz, topoloji-farkındalıklı politika işe yarıyor

**D, çekişmenin verdiği hasarın %87–109'unu geri alıyor.**

| metrik | B (Linux varsayılanı) | D | D'nin kapattığı açık |
|---|---|---|---|
| TTFT | +60.1% | **+4.8%** | %92 |
| ITL p50 | +17.3% | **+2.1%** | %88 |
| ITL p95 | +15.0% | **−1.4%** (ns) | %109 |
| ITL p99 | +17.4% | **−0.0%** (ns) | %100 |
| decode | −14.7% | **−1.8%** | %87 |

*(fark sütunları boştaki referans A'ya göre)*

16 rakip thread, doğru yerleştirmeyle LLM açısından neredeyse **bedava**
hale geliyor. Kuyruk gecikmesinde (p95, p99) fark boştaki makineden
istatistiksel olarak ayırt edilemiyor.

Bunun için faz tespiti, uyarlama, ML gerekmedi. Tek kural: *gecikmeye
duyarlı iş P-core'lara sahip olsun, rakip E'ye gitsin.* **Faz 2'de basit
bir sezgisel sched_ext politikası yazmak için aranan gerekçe budur.**

## 2. Beklenmedik: LLM'i tek başına pinlemek ZARARLI

C kolu (LLM P-core'a pinli, yük serbest) varsayılandan **daha iyi değil,
kuyrukta daha kötü**:

- ITL p95: A'ya göre **+35.5%** (B ise +15.0%)
- ITL p99: **+36.8%** (B ise +17.4%)
- açığı kapatma oranı: **−136%** — yani açığı kapatmıyor, büyütüyor
- migration: 48 314 (B'nin iki katından fazla, A'nın 16 katı)

Sezgisel açıklama: LLM'i P-core'a hapsedip yükü serbest bırakınca yük de
P-core'lara yerleşiyor ve **LLM artık kaçamıyor**. Pinsizken en azından
E-core'lara yayılıp bir miktar nefes alabiliyordu; pinliyken 8 P-core
üzerinde 16 rakip thread'le sıkışıyor.

**Çıkarım:** kazandıran hamle *LLM'i izole etmek* değil, **rakibi tahliye
etmek**. Bu ikisi sezgisel olarak aynı şey gibi görünüyor ama ölçümde zıt
sonuç veriyorlar. Bir sched_ext politikası "önemli thread'i iyi çekirdeğe
koy" diye yazılırsa C'yi üretir ve işleri kötüleştirir; "önemsiz thread'i
iyi çekirdekten çıkar" diye yazılmalı.

## 3. Migration yine hiçbir şey öngörmüyor

C en çok migration'a sahip (48 314) **ve** en kötü kuyruğa. D daha az
migration'a sahip (12 611) ve en iyi kuyruğa. Ama A yalnızca 2 990
migration'la D'ye çok yakın sonuç veriyor.

Sıralama migration'la değil, **rakip thread'in nerede olduğuyla**
açıklanıyor. `migration-count-is-not-the-metric` bulgusu üçüncü kez,
bağımsız bir deneyde doğrulandı.

---

## Dürüst sınır: yükün kendi throughput'u ÖLÇÜLMEDİ

D'nin "%92 açık kapattı" sayısı **tek taraflı bir muhasebedir.** D, 16 yük
thread'ini 8 E-core'a sürüyor; yükün kendi iş çıkarma hızı bundan mutlaka
zarar görüyor — ama `loadgen` iş hızını raporlamıyor, dolayısıyla bedeli
ölçmedim.

Yani şu an gösterilen şey: *"rakibi E-core'a sürersen LLM neredeyse hiç
etkilenmez."* Gösterilmeyen şey: *"bu, rakibe neye mal olur."* Sistem
düzeyinde bir politika iddiası için ikisi de gerekli. Aksi halde "önemli
işi hızlandırdım" demek, "diğer işi yavaşlattım"ı gizler.

**Düzeltmesi kolay:** `loadgen`'e iterasyon sayacı ekleyip koşu sonunda
toplam iş miktarını yazdırmak, sonra S2'yi tekrarlamak. Bir sonraki adım
olarak öneriliyor; bu yapılmadan D "kazanç" olarak sunulmamalı,
"LLM tarafında kazanç" olarak sunulmalı.

## Faz durumu

Faz 0 ve Faz 1'in çekirdeği tamamlandı sayılabilir. Faz 2 (basit sezgisel
sched_ext politikası) için gerekçe artık ölçülmüş durumda: D'nin yaptığı
şey bir scheduler politikası olarak ifade edilebilir ve kazancı gürültü
tabanının 40 katı.

**Açık kalanlar:** yükün maliyeti (yukarıda), K1'in mekanizması (ikinci
model gerekiyor), H2 ve H5, `scx_lavd` / `scx_rustland` baseline'ları
(kullanıcı onayı gerekir), S3–S6.
