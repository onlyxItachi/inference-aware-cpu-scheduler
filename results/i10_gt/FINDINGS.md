# İŞ 2 — Yer-gerçeği teşhisi: erken uyarı GERÇEK

**Sonuç: "negatif gecikme" bir yer-gerçeği artefaktı değil. İçsel faz
sınırı ile ilk token'ın istemciye varışı pratikte aynı an (0.30 ms), ve
dedektör ikisinden de ~116 ms önce tetikleniyor.**

---

## 1. Yöntem

llama.cpp'ye **yalnızca teşhis amaçlı** geçici bir zaman damgası eklendi:

- **Yer:** `llama_context::graph_compute(gf, batched)` — threadpool
  seçiminin yapıldığı nokta
- **Ne:** `batched` değeri her değiştiğinde `CLOCK_MONOTONIC` damgası
  stderr'e. İlk `batched == false` çağrısı = gerçek içsel prefill→decode
  sınırı
- **Nerede:** ayrı bir binary (`build-diag`). **Ana ölçüm binary'si
  değişmedi**; yama uygulandı, derlendi, kaynak hemen eski hâline
  döndürüldü (`grep PHASE_MARK src/` → 0)

**Saat tabanı doğrulandı:** Python `perf_counter_ns` ile C
`clock_gettime(CLOCK_MONOTONIC)` arasındaki fark 0.002 ms — aynı taban,
dönüşüm gerekmiyor. Bu doğrulanmadan sonuç geçersiz olurdu.

## 2. Ölçülen (6 koşu)

İstek gönderimine göre tipik zaman çizelgesi:

| an | zaman |
|---|---|
| dedektör tetikleniyor | 10 963 ms |
| sunucu `prompt eval` tamamlandı | 11 043 ms |
| ilk token istemciye vardı | 11 076 ms |
| **içsel sınır** (`graph_compute(batched=0)`) | **11 077 ms** |

Medyanlar (n=6):

| ölçüm | değer |
|---|---|
| içsel sınır → ilk token | **−0.30 ms** |
| dedektör → ilk token | −115.33 ms |
| **dedektör → içsel sınır** | **−115.64 ms** |
| aralık | −123.0 … −105.8 ms |

## 3. Yorum: hipotez elendi, iddia ayakta

Beklenen alternatif şuydu: llama.cpp içeride decode'a çoktan başlamıştır,
token istemciye ulaşana kadar sampling + detokenization + SSE + soket
geçer, dolayısıyla "erken uyarı" aslında ölçüm noktasının yanlış
seçilmesinden ibarettir.

**Veri bunu desteklemiyor.** İçsel sınır ile istemci varışı **0.30 ms**
arayla. Üstelik sıralama da anlamlı: `batched=0` mark'ı ilk token'dan
*sonra* geliyor, çünkü **ilk token'ı prefill grafiği üretiyor** (son
pozisyonun logits'i). İlk decode grafiği ikinci token için başlıyor.

Yani `prompt eval` → ilk token → ilk decode grafiği zinciri sıkı; arada
kayda değer bir gecikme yok. Dedektör gerçekten **~116 ms erken**.

**Sonuç: iddia geri çekilmiyor.** B.3'teki erken yerleşim hipotezi de
düşmüyor; aksine anlamını koruyor — dedektörün negatif gecikmesi
politikaya gerçek bir hazırlık payı veriyor.

## 4. Mekanizma: hâlâ açık, ama artık daha dar

Elenen adaylar: prompt uzunluğu (25.8 kat değişimde sabit), ubatch/bariyer
sıklığı (4 kat değişimde 1.06×), P-core frekansı (ters yönde),
**ve şimdi yer-gerçeğinin konumu**.

Geriye kalan ve bu ölçümle *daha olası* hale gelen bir hipotez var, ama
**test edilmedi**:

> llama.cpp prefill sırasında logits'i yalnızca **son pozisyon** için
> hesaplar. Dolayısıyla prefill grafiğinin kuyruğu — son katmanlar ve
> çıkış projeksiyonu — efektif olarak tek-token'lık, yani **decode
> şeklinde** bir iştir. Bu bölüm decode'a benzer bariyer deseni üretiyor
> ve dedektör onu görüyor olabilir.

Bu, gözlenen ~116 ms'lik payla da tutarlı: tek bir decode token'ı bu
konfigürasyonda ~86 ms sürüyor.

Doğrulaması için `graph_compute` içine katman düzeyinde damgalar gerekir;
bu oturumda yapılmadı ve **hipotez olarak işaretlenmiştir**.

## 5. Sınırlar

- Teşhis binary'si yalnızca A_P8 konfigürasyonunda koşuldu (SWITCH değil).
- `n_predict=128`, teşhis derlemesi; mutlak TTFT değerleri ana ölçümlerle
  birebir kıyaslanmamalı (yakın: 11 096 vs 11 051).
- `batched` bayrağı graph düzeyinde; graph içindeki faz benzeri geçişleri
  göremez — bölüm 4'teki hipotezin testi tam da bunu gerektiriyor.
