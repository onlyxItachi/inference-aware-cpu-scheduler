# İŞ 1 — scx scheduler baseline'ları: raporun mantıksal açığı kapandı

**Sonuç: hiçbir scx scheduler'ı EEVDF+SWITCH'i yenmiyor. Faz anahtarlamanın
TTFT kazancı üç scheduler'da da korunuyor ama zayıflayarak; `scx_lavd` ITL
kazancını tamamen siliyor.**

**Tasarım:** 3 scheduler × 2 yerleşim × 2 senaryo × 6 tur = **72 koşu**,
her scheduler bloğu içinde interleaved. Üçü de **aynı oturumda** ölçüldü —
Faz 0'da bulunan oturum içi drift'e karşı bu şarttı.

**Kullanıcı onayı:** CLAUDE.md kural 6 gereği daha önce yapılmayan scheduler
yükleme bu iş için açıkça onaylandı. Kapsam yalnızca hazır scheduler'ları
çalıştırmaktı; BPF yazılmadı, scheduler değiştirilmedi.

**Güvenlik protokolü:** her blok öncesi/sonrası `/sys/kernel/sched_ext/state`
loglandı, yükleme sonrası sistem sağlığı doğrulandı (komut yanıt süresi,
CPU işi, yük), blok sonunda scheduler durduruldu ve state'in "disabled"a
döndüğü teyit edildi. Hiçbir blokta takılma veya anomali görülmedi.

---

## 1. Ölçülen

**TTFT (ms):**

| kol | EEVDF | rustland | lavd |
|---|---|---|---|
| A_P8 / rakipsiz | 11 051 | 10 970 | 10 857 |
| A_P8 / build | 11 708 | 11 519 | 11 509 |
| **SWITCH / rakipsiz** | **9 815** | 10 133 | 10 352 |
| **SWITCH / build** | **10 516** | 10 769 | 10 834 |

**ITL p95 (ms):**

| kol | EEVDF | rustland | lavd |
|---|---|---|---|
| A_P8 / rakipsiz | 90.07 | 91.19 | 91.81 |
| A_P8 / build | 90.58 | 90.38 | 91.88 |
| **SWITCH / rakipsiz** | **87.19** | 87.93 | 91.75 |
| **SWITCH / build** | **87.42** | 88.41 | 91.88 |

## 2. Soru 1 — scx, EEVDF+A_P8'i yeniyor mu?

**Anlamlı biçimde hayır.** TTFT'de marjinal iyileşme var (lavd −%1.8,
rustland −%0.7) ama ikisi de **%2 gürültü tabanının altında**. Buna
karşılık ITL p95'te EEVDF+A_P8 (90.07) her iki scx'ten de iyi.

Yani statik pinning ile karşılaştırıldığında scx scheduler'ları TTFT'de
ölçülemeyecek kadar az kazandırıyor, kuyruk gecikmesinde ise kaybettiriyor.

## 3. Soru 2 — EEVDF+SWITCH'i yeniyor mu?

**Hayır, hiçbiri.** EEVDF+SWITCH dört ölçümün dördünde de en iyisi:
TTFT 9 815 / 10 516 ve ITL p95 87.19 / 87.42.

En yakın rakip rustland+SWITCH (10 133 / 87.93), yani TTFT'de %3.2, p95'te
%0.8 geride.

## 4. Soru 3 — SWITCH'in kazancı scheduler-bağımsız mı?

**TTFT'de evet, ama zayıflayarak. ITL p95'te lavd altında kayboluyor.**

| scheduler | TTFT (rakipsiz) | TTFT (build) | p95 (rakipsiz) | p95 (build) |
|---|---|---|---|---|
| EEVDF | **−%11.2** (p<0.01) | **−%10.2** (p<0.01) | −%3.2 (ns) | −%3.5 (p<0.05) |
| rustland | −%7.6 (p<0.01) | −%6.5 (p<0.01) | −%3.6 (ns) | −%2.2 (ns) |
| **lavd** | −%4.7 (p<0.01) | −%5.9 (p<0.01) | **−%0.1 (ns)** | **−%0.0 (ns)** |

Bu ayrı bir bulgudur ve iki yönü var:

**(a) Mekanizma scheduler'a özgü değil.** Faz anahtarlama EEVDF'e özel bir
hile değil; üç farklı scheduler altında da TTFT kazandırıyor (hepsi
p<0.01). Bu, katkının genelliğini güçlendiriyor.

**(b) Ama kazancın büyüklüğü scheduler'a bağlı.** EEVDF'te −%11.2 olan
kazanç lavd'da −%4.7'ye iniyor. Anlaşılan scheduler ne kadar çok kendi
yerleştirme mantığını dayatıyorsa, faz anahtarlamaya kalan alan o kadar
azalıyor.

**En çarpıcı satır lavd'ın ITL p95'i:** dört hücrenin dördünde de ~91.8 ms.
Yerleşim değişse de değişmiyor. Gecikme-farkındalıklı scheduler kuyruk
davranışını sabitliyor — ama sabitlediği seviye EEVDF+SWITCH'in
87.2'sinden **kötü**, hatta EEVDF+A_P8'in 90.1'inden de kötü.

## 5. Karar üzerindeki etkisi

Raporun "sched_ext'in katkısı yok" sonucu, önceden **hiç sched_ext
scheduler'ı ölçülmeden** verilmişti; bu bir mantıksal açıktı ve doğru
tespit edilmişti. Açık kapandı ve sonuç **değişmedi, güçlendi**:

- sched_ext'in *öncelik ifadesi* gereksizdi (İŞ 3, İŞ 7, İŞ 8'de ölçüldü)
- sched_ext'in *hazır scheduler'ları* da bir şey katmıyor (bu iş)

Karar aynı kalıyor: **sched_ext'e girilmiyor.** Ama gerekçe artık iki
ayaklı ve ikincisi doğrudan ölçülmüş.

## 6. Yan bulgu: scx_lavd scx_loader üzerinden başlatılamıyor

Bu makinede `scxctl start --sched lavd` **çalışmıyor**: scx_loader
scheduler'ı `--autopilot --pinned-slice-us 500` argümanlarıyla başlatıyor
ve `scx_lavd` **SIGSEGV** atıp core dump ediyor (5/5 deneme, root olarak,
`SEGV_MAPERR`).

Elle `sudo scx_lavd --autopilot` ile (yani `--pinned-slice-us` geçilmeden)
sorunsuz başlıyor ve stabil çalışıyor.

Bu projenin bulgusu değil, ortam notudur — ama tekrarlanabilirlik için
kayda değer: bu kernel/sürüm kombinasyonunda scxctl tarifi çalışmıyor.

## 7. Sınırlar

- Yalnızca iki scx scheduler'ı denendi (lavd, rustland). Sistemde 13 tane
  var; `flash`, `bpfland`, `p2dq` gibi diğerleri ölçülmedi.
- Scheduler'lar varsayılan ayarlarıyla çalıştırıldı; lavd'ın performance/
  powersave modları, rustland'ın parametreleri denenmedi.
- Yerleşim kolları yalnızca A_P8 ve SWITCH; C_P8_E8 bu matrise dahil
  edilmedi (süre kısıtı).
- Enerji ölçümü rustland bloğunun ilk 2-3 koşusunda eksik (RAPL izni
  oturum ortasında geri verildi).
