/* U6 — bağımsız bellek bant genişliği taban çizgisi.
 *
 * Rapor decode'u iki noktalı bir fit'ten çözümleyip 91 GB/s "gerçek akış
 * bant genişliği" veriyor. DDR5 2 kanal için teorik tavan ~89.6 GB/s
 * (DDR5-5600) — yani fit tavanı AŞIYOR. Aynı hesap sınıfı bir kez zaten
 * yanlış çıkmıştı (66 GB/s). Fit'i doğrulayacak bağımsız bir ölçüm gerekli.
 *
 * İKİ çekirdek ölçülüyor, çünkü hangisiyle karşılaştırıldığı sonucu
 * değiştirir:
 *
 *   read : saf okuma (toplama). LLM decode'u ağırlıkları okur ve
 *          neredeyse hiç yazmaz -- 91 GB/s iddiasının DOĞRU muhatabı budur.
 *   triad: a[i] = b[i] + s*c[i], 2 okuma + 1 yazma. Klasik STREAM sayısı.
 *          Write-allocate yüzünden okuma-ağırlıklı yükten düşük çıkar;
 *          buna karşı kıyaslamak decode'u haksız yere iyi gösterir.
 *
 * Diziler LLC'den (30 MB) çok büyük seçildi, aksi halde ölçülen şey cache.
 * Bağımlılık yok: libc + pthreads.
 */

#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define N (64ull * 1024 * 1024)   /* 64M double = 512 MB / dizi */
#define REPS 5

static double *a, *b, *c;
static int nthreads;
static int kind;                  /* 0 = read, 1 = triad */
static double sinks[64];

static double now(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec + ts.tv_nsec / 1e9;
}

static void *worker(void *arg)
{
    long id = (long)arg;
    size_t lo = N * id / nthreads, hi = N * (id + 1) / nthreads;
    if (kind == 0) {
        double s = 0.0;
        for (size_t i = lo; i < hi; i++)
            s += a[i];
        /* Bu bariyer ZORUNLU. Onsuz GCC -O2, dizinin sabitle dolduğunu
         * görüp toplamı kapalı forma çeviriyor ve döngüyü tamamen
         * eliyor; ölçüm o zaman bant genişliğini değil pthread
         * oluşturma maliyetini veriyor (ilk denemede 12 498 GB/s
         * "ölçüldü" -- teorik tavanın 150 katı). */
        __asm__ __volatile__("" : "+x"(s) :: "memory");
        sinks[id] = s;
    } else {
        for (size_t i = lo; i < hi; i++)
            a[i] = b[i] + 3.0 * c[i];
    }
    return NULL;
}

static double run(void)
{
    pthread_t th[64];
    double t0 = now();
    for (long i = 0; i < nthreads; i++)
        pthread_create(&th[i], NULL, worker, (void *)i);
    for (int i = 0; i < nthreads; i++)
        pthread_join(th[i], NULL);
    return now() - t0;
}

int main(int argc, char **argv)
{
    nthreads = argc > 1 ? atoi(argv[1]) : 8;
    if (nthreads > 64)
        nthreads = 64;

    a = malloc(N * sizeof(double));
    b = malloc(N * sizeof(double));
    c = malloc(N * sizeof(double));
    if (!a || !b || !c) {
        fprintf(stderr, "malloc failed\n");
        return 1;
    }
    /* İlk dokunuş: sayfalar gerçekten tahsis edilsin, ölçüm page fault
     * ölçmesin. */
    /* Sabit DEĞİL: sabitle doldurulursa derleyici toplamı kapalı forma
     * çevirebilir. Ayrıca ilk dokunuş burada olur, ölçüm page fault
     * ölçmesin. */
    for (size_t i = 0; i < N; i++) {
        a[i] = (double)(i & 1023); b[i] = a[i] + 1.0; c[i] = a[i] + 2.0;
    }

    for (kind = 0; kind <= 1; kind++) {
        /* okuma: N*8 bayt. triad: 2 okuma + 1 yazma = N*24 bayt. */
        double bytes = (double)N * (kind == 0 ? 8.0 : 24.0);
        double best = 1e30;
        for (int r = 0; r < REPS; r++) {
            double dt = run();
            if (dt < best)
                best = dt;
        }
        double gbs = bytes / best / 1e9;
        /* Bu makinenin teorik tavanı: 2 kanal x 64 bit @ 5200 MT/s
         * (dmidecode "Configured Memory Speed"). Ölçüm bunu aşıyorsa
         * ölçüm bozuktur -- fizik değil. Sessizce geçmesin. */
        const double CEILING = 83.2;
        printf("%-6s threads=%2d  %7.2f GB/s  (%.1f ms, best of %d, "
               "%.0f MB moved)%s\n",
               kind == 0 ? "read" : "triad", nthreads, gbs, best * 1e3,
               REPS, bytes / 1e6,
               gbs > CEILING ? "   <-- TAVANI AŞIYOR, ÖLÇÜM BOZUK" : "");
        fflush(stdout);
    }
    return 0;
}
