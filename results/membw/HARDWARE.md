# 2d / U6 — bellek tavanı: donanım kaydı

`sudo dmidecode -t memory`, 2026-07-19. Kullanıcı çalıştırdı.

## Ölçülen donanım

| | değer |
|---|---|
| modül sayısı | 2 × 16 GiB SODIMM |
| yerleşim | `Controller0-ChannelA-DIMM0`, `Controller1-ChannelA-DIMM0` |
| tip | DDR5 |
| data width | 64 bit / modül |
| rank | 1 |
| **dereceli hız** | 5600 MT/s |
| **yapılandırılmış hız** | **5200 MT/s** |

İki modül **ayrı denetleyicilerde** → gerçekten çift kanal. Bu tarafta
belirsizlik yok.

Belirleyici satır `Speed` değil **`Configured Memory Speed`**: modüller
5600'e dereceli ama sistem onları 5200'de sürüyor. Tavan hesabı
yapılandırılmış hızla yapılmalı.

## Teorik tavan

```
kanal başına : 5200 × 10^6 T/s × 8 B/T = 41.6 GB/s
iki kanal    : 41.6 × 2               = 83.2 GB/s
```

Referans olarak dereceli hızla: 5600 × 8 × 2 = **89.6 GB/s** (bu sistemde
ulaşılamaz, RAM o hızda çalışmıyor).

## Raporun iddiasıyla karşılaştırma

| | GB/s | tavana oranı |
|---|---|---|
| iki noktalı fit'in verdiği "gerçek akış bant genişliği" | **91.0** | **%109.4** |
| teorik tavan (yapılandırılmış, 5200) | 83.2 | %100 |
| teorik tavan (dereceli, 5600 — ulaşılamaz) | 89.6 | %107.7 |

**Fit teorik tavanı aşıyor.** Yapılandırılmış hıza karşı %9.4, dereceli
hıza karşı bile %1.6 aşım var. Bir ölçüm teorik tavanı aşamaz; dolayısıyla
iki noktalı fit **geçersizdir**.

Bu, aynı hesap sınıfındaki **ikinci** hatadır (birincisi 66 GB/s'ti ve
düzeltilmişti). İki noktalı fit'in kendisi bu iş için yeterince kısıtlı
değil: iki bilinmeyeni iki gözlemle çözerken hata payı doğrudan sonuca
geçiyor ve sonucun fiziksel olarak mümkün olup olmadığı kontrol
edilmemişti.

## Sonuç

- **91 GB/s sayısı rapordan ve makaleden ÇIKARILIR.**
- **C3 iddiası** "decode X GB/s akış bant genişliğiyle sınırlı"dan
  **"bant genişliğinin baskın olduğu bir rejimle tutarlı"** düzeyine
  indirilir.
- Raporun geri kalanı C3'ün nicel hâline bağlı değil; asimetri bulgusu
  (prefill %77–82 / decode %49–63 ölçeklenme) doğrudan ölçüm, fit değil.

Bağımsız ölçüm (`harness/membw.c`, saf okuma + triad) → `membw.txt`.
