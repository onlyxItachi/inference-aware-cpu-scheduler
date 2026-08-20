# İŞ 3 — İkinci model (4B): asimetri model boyutuyla nasıl ölçekleniyor?

**Sonuç: asimetri korunuyor ama faz anahtarlamanın kazancı küçük modelde
azalıyor. Ve yol boyunca Faz 1'in bir sayısı düzeltildi: decode'un
darboğazı sandığımızdan daha az bant genişliği, daha çok token başına
sabit maliyet.**

**Model:** Qwen3.5-4B-Q4_K_M, 2.74 GB, `unsloth/Qwen3.5-4B-GGUF`
sha256 `00fe7986ff5f6b46…`

**Karıştırıcı yok:** 9B ile **aynı mimari** (`qwen35`), **aynı katman
sayısı** (32); yalnızca genişlik farklı (embedding 4096 → 2560). Farklı
aileden bir model seçilseydi "boyut mu mimari mi" ayrılamazdı.

**Ölçüm:** K1 taraması 24 koşu + E-core kolu 18 koşu, interleaved.

---

## 1. K1 taraması: asimetri korunuyor, hafifçe genişliyor

| | 9B | 4B |
|---|---|---|
| prefill verimi (t2→t8) | %77 | %75 |
| **decode verimi (t2→t8)** | **%49** | **%45** |
| t6→t8 marjinal prefill | +%20.8 | +%19.4 |
| **t6→t8 marjinal decode** | **+%8.4** | **+%3.3** |

Beklenti şuydu: küçük modelin ağırlıkları cache'e daha çok sığar, decode
daha iyi ölçeklenir, asimetri daralır. **Gerçekleşmedi** — decode verimi
%49'dan %45'e *düştü*.

## 2. Neden: bant genişliği değil, sabit maliyet

Ham "ima edilen bant genişliği" iki modelde tutarsız çıkıyor:
9B t8'de 65.9 GB/s, 4B t8'de 50.8 GB/s. Sabit bir donanım tavanı olsaydı
ikisi de aynı yerde doymalıydı.

Dahası hız oranı: 4B, 9B'nin **1.60 katı** hızlı, oysa boyut oranı
**2.07**. Küçük model byte başına daha verimsiz.

İki model, iki bilinmeyen — çözülebilir:

```
token_suresi = model_GB / BW + sabit
```

| çekirdek | BW (GB/s) | sabit (ms) | sabitin 9B payı | 4B payı |
|---|---|---|---|---|
| t2 | 41.7 | 31.6 | %19 | %32 |
| t4 | 62.9 | 20.5 | %18 | %32 |
| t6 | 78.0 | 20.6 | %22 | %37 |
| **t8** | **91.0** | **23.8** | **%28** | **%44** |
| t16 | 90.5 | 25.2 | %29 | %45 |

İki düzeltme çıkıyor:

**(a) Gerçek akış bant genişliği 91 GB/s, 66 değil.** Faz 1'de raporlanan
"~66 GB/s, DDR5 tavanına yakın" değeri, token başına sabit maliyeti
yanlışlıkla bant genişliğine yıkıyordu. Gerçek akış hızı t8'de 91 GB/s ve
t16'da artmıyor — **donanım tavanı 8 çekirdekte gerçekten dolduruluyor.**

**(b) Token başına ~24 ms sabit maliyet var ve model boyutundan
bağımsız.** Paralelleşmiyor, dolayısıyla ölçeklenmeyi sınırlayan asıl
şey bu. 9B decode süresinin %28'i, 4B'nin **%44'ü**.

Bu, 4B'nin neden daha kötü ölçeklendiğini tam olarak açıklıyor: model
küçüldükçe sabit maliyetin payı büyüyor.

### Faz 1'in "%87 bandwidth / %13 senkronizasyon" ifadesiyle ilişkisi

Çelişki yok, iki farklı şey ölçülmüş:

- **İŞ 2 (çift örnek, Faz 1):** bariyeri *ikiye bölmenin* marjinal
  getirisi = +%7.4. Bu, sabit maliyetin **bir kısmını** geri alır (her
  yarının hâlâ kendi bariyeri var).
- **Bu iş (iki model):** akış-dışı bileşenin **toplamı** = %28.

İkisi tutarlı: toplam sabit maliyet %28, bariyeri bölerek geri alınabilen
kısmı %7.4. Ama Faz 1'in "decode ~%87 bandwidth-bound" ifadesi **fazla
iddialıydı** ve %72 olarak düzeltilmelidir.

## 3. E-core kolu: asimetri var, ama takas kötüleşiyor

| | 9B | 4B |
|---|---|---|
| prefill kazancı (C_P8_E8 vs A_P8) | **+%13.0** | +%8.0 |
| TTFT kazancı | −%11.5 | −%7.4 |
| decode kaybı | −%8.4 | −%13.3 |
| **ITL p95 kaybı** | **+%9.4** | **+%19.3** |

Hepsi p<0.01. Asimetrinin **yönü** korunuyor (aynı karar prefill'i
iyileştirip decode'u bozuyor) ama **büyüklüğü ters yönde değişiyor**:
küçük modelde kazanç azalıyor, hasar iki katına çıkıyor.

Sabit maliyet bulgusuyla tutarlı: 4B'de decode zaten %44 oranında sabit
maliyetten oluşuyor, ve bariyere yavaş E-core eklemek doğrudan o maliyeti
büyütüyor.

## 4. Cevap: faz anahtarlama model büyüdükçe daha çok kazandırıyor

Karakterizasyon iddiası artık "bir modelde gözlendi"den şuraya taşındı:

> Prefill/decode asimetrisi model boyutundan bağımsız olarak **vardır**,
> ama onu sömürmenin getirisi **model boyutuyla artar**. Küçük modellerde
> decode, model boyutundan bağımsız sabit bir token maliyetine daha çok
> hâkim olur; bu maliyet paralelleşmediği için ek çekirdek ya da E-core
> eklemek daha az kazandırır ve kuyruk gecikmesine daha çok zarar verir.

Pratik sonucu: faz-farkındalıklı politika **büyük modellerde daha
değerli**. 9B'de TTFT −%11.5 / p95 +%9.4 olan takas, 4B'de
−%7.4 / +%19.3'e dönüşüyor — yani 4B için "prefill'e E-core ver"
politikası çok daha zayıf, hatta ITL kısıtı altında savunulamaz olabilir.

## 5. Sınırlar

- **İki noktalı uydurma.** BW/sabit ayrıştırması iki modelden çözüldü ve
  sabit maliyetin model boyutundan bağımsız olduğunu **varsayıyor**.
  Üçüncü bir model (ör. 1.5B veya 14B) bunu sınardı; yapılmadı.
- Sabit maliyetin ne olduğu **doğrudan ölçülmedi** — OpenMP bariyerleri en
  güçlü aday (koşu başına ~2.1M context switch, token başına ~8200) ama
  KV-cache işlemleri, sampling ve grafik kurulumu da bu terime giriyor.
- 4B için faz anahtarlama (SWITCH kolu) **ölçülmedi**; yalnızca statik
  E-core kolları karşılaştırıldı.
- Tek prompt/üretim uzunluğu, tek quantizasyon (Q4_K_M).
