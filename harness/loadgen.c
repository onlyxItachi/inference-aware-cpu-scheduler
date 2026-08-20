/* Reproducible competing CPU load for S2.
 *
 * CLAUDE.md suggests `make -j` or stress-ng. Neither is ideal here: a build
 * has I/O phases, changes shape as it progresses, and terminates. stress-ng
 * is not installed and would be another dependency. What the experiment
 * actually needs is a stated, constant number of always-runnable threads
 * competing for CPU -- so that is exactly what this provides.
 *
 * Each thread runs a dependent floating-point chain: dependent so the
 * compiler cannot vectorise or elide it, and so each thread stays genuinely
 * CPU-bound rather than stalling on memory (memory-bound load would
 * confound the bandwidth question K1 left open).
 *
 * Build: gcc -O2 -o loadgen loadgen.c -lpthread
 * Run:   ./loadgen <nthreads>      (runs until SIGTERM/SIGINT)
 */

#include <pthread.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <unistd.h>

static volatile sig_atomic_t running = 1;

static void on_signal(int sig) {
    (void)sig;
    running = 0;
}

/* Per-thread iteration counters, summed at exit.
 * Separate slots rather than one shared atomic: an atomic increment in the
 * hot loop would itself become cross-core traffic and pollute the very
 * contention we are trying to measure. */
static long long *counters;

static void *worker(void *arg) {
    long id = (long)arg;
    double x = 1.0 + (double)id * 0.000001;
    long long iters = 0;
    /* Dependent chain: each iteration needs the previous result. */
    while (running) {
        for (int i = 0; i < 100000; i++) {
            x = x * 1.0000001 + 0.0000001;
            if (x > 1e6) x = 1.0;
        }
        iters++;
    }
    counters[id] = iters;
    /* Consume the result so the loop cannot be optimised away. */
    return (void *)(long)x;
}

int main(int argc, char **argv) {
    int n = (argc > 1) ? atoi(argv[1]) : 8;
    if (n < 1) n = 1;

    struct sigaction sa = {0};
    sa.sa_handler = on_signal;
    sigaction(SIGTERM, &sa, NULL);
    sigaction(SIGINT, &sa, NULL);

    pthread_t *ts = calloc((size_t)n, sizeof(pthread_t));
    counters = calloc((size_t)n, sizeof(long long));

    struct timespec t0, t1;
    clock_gettime(CLOCK_MONOTONIC, &t0);
    for (long i = 0; i < n; i++)
        pthread_create(&ts[i], NULL, worker, (void *)i);

    fprintf(stderr, "loadgen: %d threads running\n", n);
    fflush(stderr);

    for (int i = 0; i < n; i++)
        pthread_join(ts[i], NULL);
    clock_gettime(CLOCK_MONOTONIC, &t1);

    double elapsed = (double)(t1.tv_sec - t0.tv_sec)
                   + (double)(t1.tv_nsec - t0.tv_nsec) / 1e9;
    long long total = 0;
    for (int i = 0; i < n; i++)
        total += counters[i];

    /* Machine-readable, one line, on stdout: the work this load actually
     * completed. Without it, "the LLM got faster" hides "the competitor got
     * slower" -- a one-sided ledger. */
    printf("LOADGEN_RESULT iters=%lld elapsed_s=%.3f rate=%.1f threads=%d\n",
           total, elapsed, elapsed > 0 ? (double)total / elapsed : 0.0, n);
    fflush(stdout);

    free(ts);
    free(counters);
    return 0;
}
