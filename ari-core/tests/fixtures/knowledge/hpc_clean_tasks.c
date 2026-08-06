/* Independently authored clean tasks for the three built-in HPC knowledge
 * skills.  Each task carries its own baseline, so every check below compares
 * a candidate against code written for this task only -- none of the pinned
 * scoring harnesses in workspace/harnesses is read, linked, or timed here.
 *
 *   ./hpc_clean_tasks <gemm|spmm|stencil> <selftest|bench>
 *
 * selftest prints one KEY=VALUE line per check and exits non-zero on any
 * failure.  bench prints alternating baseline/candidate timings.
 */
/* _GNU_SOURCE: CPU_ZERO/CPU_SET and pthread_setaffinity_np are GNU extensions. */
#define _GNU_SOURCE
#include <math.h>
#include <pthread.h>
#include <sched.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define GEMM_N 256
#define GEMM_BS 64
#define SPMM_ROWS 4000
#define SPMM_PER_ROW 16
#define SPMM_K 8
#define STENCIL_NX 512
#define STENCIL_NY 512
#define STENCIL_STEPS 16
#define STENCIL_THREADS 2

static double now_seconds(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC_RAW, &ts);
    return (double)ts.tv_sec + (double)ts.tv_nsec * 1e-9;
}

/* A deterministic generator, so every replay and every sanitizer build sees
 * byte-identical inputs. */
static unsigned long long seed_state = 88172645463325252ULL;
static void seed_reset(unsigned long long value) { seed_state = value; }
static double next_unit(void) {
    seed_state ^= seed_state << 13;
    seed_state ^= seed_state >> 7;
    seed_state ^= seed_state << 17;
    return (double)((seed_state >> 11) & 0x1FFFFFFFFFFFFFULL) / 9007199254740992.0;
}

/* ---------------------------------------------------------------- GEMM --- */

static void gemm_baseline(const double *a, const double *b, double *c, int n) {
    for (int i = 0; i < n; ++i)
        for (int j = 0; j < n; ++j) {
            double sum = 0.0;
            for (int k = 0; k < n; ++k) sum += a[i * n + k] * b[k * n + j];
            c[i * n + j] = sum;
        }
}

static void gemm_candidate(const double *restrict a, const double *restrict b,
                           double *restrict c, int n) {
    memset(c, 0, (size_t)n * (size_t)n * sizeof(double));
    for (int ii = 0; ii < n; ii += GEMM_BS)
        for (int kk = 0; kk < n; kk += GEMM_BS)
            for (int jj = 0; jj < n; jj += GEMM_BS) {
                int i_max = ii + GEMM_BS < n ? ii + GEMM_BS : n;
                int k_max = kk + GEMM_BS < n ? kk + GEMM_BS : n;
                int j_max = jj + GEMM_BS < n ? jj + GEMM_BS : n;
                for (int i = ii; i < i_max; ++i)
                    for (int k = kk; k < k_max; ++k) {
                        double aik = a[i * n + k];
                        for (int j = jj; j < j_max; ++j)
                            c[i * n + j] += aik * b[k * n + j];
                    }
            }
}

static double max_abs_diff(const double *x, const double *y, size_t count) {
    double worst = 0.0;
    for (size_t i = 0; i < count; ++i) {
        double delta = fabs(x[i] - y[i]);
        if (delta > worst) worst = delta;
    }
    return worst;
}

static double max_abs(const double *x, size_t count) {
    double worst = 0.0;
    for (size_t i = 0; i < count; ++i)
        if (fabs(x[i]) > worst) worst = fabs(x[i]);
    return worst;
}

static void gemm_fill(double *a, double *b, int n, unsigned long long seed) {
    seed_reset(seed);
    for (int i = 0; i < n * n; ++i) a[i] = next_unit() - 0.5;
    for (int i = 0; i < n * n; ++i) b[i] = next_unit() - 0.5;
}

static int gemm_selftest(void) {
    int n = GEMM_N;
    size_t count = (size_t)n * (size_t)n;
    double *a = malloc(count * sizeof(double));
    double *b = malloc(count * sizeof(double));
    double *b2 = malloc(count * sizeof(double));
    double *bs = malloc(count * sizeof(double));
    double *ref = malloc(count * sizeof(double));
    double *got = malloc(count * sizeof(double));
    double *aux = malloc(count * sizeof(double));
    double *aux2 = malloc(count * sizeof(double));
    if (!a || !b || !b2 || !bs || !ref || !got || !aux || !aux2) return 2;
    gemm_fill(a, b, n, 0x5EEDULL);

    gemm_baseline(a, b, ref, n);
    gemm_candidate(a, b, got, n);
    double scale = max_abs(ref, count);
    double differential = max_abs_diff(ref, got, count) / (scale > 0 ? scale : 1.0);
    printf("differential_relative=%.3e\n", differential);

    /* Metamorphic 1: doubling A must double C exactly in exact arithmetic and
     * to rounding here. */
    for (size_t i = 0; i < count; ++i) aux[i] = 2.0 * a[i];
    gemm_candidate(aux, b, aux2, n);
    for (size_t i = 0; i < count; ++i) aux[i] = 2.0 * got[i];
    double scaling = max_abs_diff(aux, aux2, count) / (2.0 * (scale > 0 ? scale : 1.0));
    printf("metamorphic_scaling=%.3e\n", scaling);

    /* Metamorphic 2: C(A, B1+B2) == C(A,B1) + C(A,B2). */
    seed_reset(0xC0FFEEULL);
    for (size_t i = 0; i < count; ++i) b2[i] = next_unit() - 0.5;
    for (size_t i = 0; i < count; ++i) bs[i] = b[i] + b2[i];
    gemm_candidate(a, b2, aux, n);
    gemm_candidate(a, bs, aux2, n);
    for (size_t i = 0; i < count; ++i) aux[i] += got[i];
    double additivity = max_abs_diff(aux, aux2, count) / (2.0 * (scale > 0 ? scale : 1.0));
    printf("metamorphic_additivity=%.3e\n", additivity);

    free(a); free(b); free(b2); free(bs); free(ref); free(got); free(aux); free(aux2);
    int ok = differential < 1e-12 && scaling < 1e-12 && additivity < 1e-12;
    printf("selftest=%s\n", ok ? "pass" : "fail");
    return ok ? 0 : 1;
}

static void gemm_bench(int replays, int trials) {
    int n = GEMM_N;
    size_t count = (size_t)n * (size_t)n;
    double *a = malloc(count * sizeof(double));
    double *b = malloc(count * sizeof(double));
    double *c = malloc(count * sizeof(double));
    if (!a || !b || !c) { printf("bench=alloc_failed\n"); return; }
    gemm_fill(a, b, n, 0x5EEDULL);
    gemm_baseline(a, b, c, n);   /* warm both paths before any timing */
    gemm_candidate(a, b, c, n);
    for (int r = 0; r < replays; ++r) {
        double base = 0.0, cand = 0.0;
        for (int t = 0; t < trials; ++t) {
            double t0 = now_seconds(); gemm_baseline(a, b, c, n);
            double t1 = now_seconds(); gemm_candidate(a, b, c, n);
            double t2 = now_seconds();
            if (t == 0 || t1 - t0 < base) base = t1 - t0;
            if (t == 0 || t2 - t1 < cand) cand = t2 - t1;
        }
        printf("replay=%d baseline_s=%.9f candidate_s=%.9f\n", r, base, cand);
    }
    free(a); free(b); free(c);
}

/* ---------------------------------------------------------------- SpMM --- */

typedef struct { int rows; int *row_ptr; int *col; double *val; } Csr;

static void csr_build(Csr *m, int rows, int per_row, unsigned long long seed) {
    seed_reset(seed);
    m->rows = rows;
    m->row_ptr = malloc((size_t)(rows + 1) * sizeof(int));
    m->col = malloc((size_t)rows * (size_t)per_row * sizeof(int));
    m->val = malloc((size_t)rows * (size_t)per_row * sizeof(double));
    int cursor = 0;
    for (int i = 0; i < rows; ++i) {
        m->row_ptr[i] = cursor;
        int previous = -1;
        for (int j = 0; j < per_row; ++j) {
            /* Strictly increasing column indices keep the row sorted-unique. */
            int step = 1 + (int)(next_unit() * (double)(rows / per_row - 1));
            int column = previous + step;
            if (column >= rows) column = rows - 1;
            if (column <= previous) column = previous + 1;
            if (column >= rows) break;
            previous = column;
            m->col[cursor] = column;
            m->val[cursor] = next_unit() - 0.5;
            cursor++;
        }
    }
    m->row_ptr[rows] = cursor;
}

static void csr_free(Csr *m) { free(m->row_ptr); free(m->col); free(m->val); }

static int csr_validate(const Csr *m) {
    if (m->row_ptr[0] != 0) return 0;
    for (int i = 0; i < m->rows; ++i) {
        if (m->row_ptr[i + 1] < m->row_ptr[i]) return 0;
        for (int p = m->row_ptr[i]; p < m->row_ptr[i + 1]; ++p) {
            if (m->col[p] < 0 || m->col[p] >= m->rows) return 0;
            if (p > m->row_ptr[i] && m->col[p] <= m->col[p - 1]) return 0;
        }
    }
    return 1;
}

static void spmm_baseline(const Csr *m, const double *x, double *y, int k) {
    for (int i = 0; i < m->rows; ++i)
        for (int c = 0; c < k; ++c) {
            double sum = 0.0;
            for (int p = m->row_ptr[i]; p < m->row_ptr[i + 1]; ++p)
                sum += m->val[p] * x[(size_t)m->col[p] * k + c];
            y[(size_t)i * k + c] = sum;
        }
}

static void spmm_candidate(const Csr *restrict m, const double *restrict x,
                           double *restrict y, int k) {
    for (int i = 0; i < m->rows; ++i) {
        double acc[SPMM_K];
        for (int c = 0; c < k; ++c) acc[c] = 0.0;
        for (int p = m->row_ptr[i]; p < m->row_ptr[i + 1]; ++p) {
            double v = m->val[p];
            const double *row = &x[(size_t)m->col[p] * k];
            for (int c = 0; c < k; ++c) acc[c] += v * row[c];
        }
        for (int c = 0; c < k; ++c) y[(size_t)i * k + c] = acc[c];
    }
}

static int spmm_selftest(void) {
    Csr m;
    csr_build(&m, SPMM_ROWS, SPMM_PER_ROW, 0xABCDULL);
    int structural = csr_validate(&m);
    printf("csr_validation=%s\n", structural ? "pass" : "fail");
    size_t dense = (size_t)SPMM_ROWS * SPMM_K;
    double *x = malloc(dense * sizeof(double));
    double *ref = malloc(dense * sizeof(double));
    double *got = malloc(dense * sizeof(double));
    if (!x || !ref || !got) { csr_free(&m); return 2; }
    for (size_t i = 0; i < dense; ++i) x[i] = next_unit() - 0.5;
    spmm_baseline(&m, x, ref, SPMM_K);
    spmm_candidate(&m, x, got, SPMM_K);
    double scale = max_abs(ref, dense);
    double differential = max_abs_diff(ref, got, dense) / (scale > 0 ? scale : 1.0);
    printf("differential_relative=%.3e\n", differential);
    free(x); free(ref); free(got); csr_free(&m);
    int ok = structural && differential < 1e-12;
    printf("selftest=%s\n", ok ? "pass" : "fail");
    return ok ? 0 : 1;
}

static void spmm_bench(int replays, int trials) {
    Csr m;
    csr_build(&m, SPMM_ROWS, SPMM_PER_ROW, 0xABCDULL);
    size_t dense = (size_t)SPMM_ROWS * SPMM_K;
    double *x = malloc(dense * sizeof(double));
    double *y = malloc(dense * sizeof(double));
    if (!x || !y) { printf("bench=alloc_failed\n"); csr_free(&m); return; }
    for (size_t i = 0; i < dense; ++i) x[i] = next_unit() - 0.5;
    spmm_baseline(&m, x, y, SPMM_K);
    spmm_candidate(&m, x, y, SPMM_K);
    for (int r = 0; r < replays; ++r) {
        double base = 0.0, cand = 0.0;
        for (int t = 0; t < trials; ++t) {
            double t0 = now_seconds(); spmm_baseline(&m, x, y, SPMM_K);
            double t1 = now_seconds(); spmm_candidate(&m, x, y, SPMM_K);
            double t2 = now_seconds();
            if (t == 0 || t1 - t0 < base) base = t1 - t0;
            if (t == 0 || t2 - t1 < cand) cand = t2 - t1;
        }
        printf("replay=%d baseline_s=%.9f candidate_s=%.9f\n", r, base, cand);
    }
    free(x); free(y); csr_free(&m);
}

/* ------------------------------------------------------------- stencil --- */

typedef struct {
    const double *in; double *out; int y0; int y1; int index;
    pthread_barrier_t *barrier; int steps; double **flip; double **flop;
} StencilWork;

static void stencil_sweep(const double *in, double *out, int y0, int y1) {
    for (int y = y0; y < y1; ++y)
        for (int x = 1; x < STENCIL_NX - 1; ++x)
            out[y * STENCIL_NX + x] = 0.2 * (in[y * STENCIL_NX + x]
                + in[(y - 1) * STENCIL_NX + x] + in[(y + 1) * STENCIL_NX + x]
                + in[y * STENCIL_NX + x - 1] + in[y * STENCIL_NX + x + 1]);
}

static void stencil_baseline(double *a, double *b, int steps) {
    for (int s = 0; s < steps; ++s) {
        stencil_sweep(a, b, 1, STENCIL_NY - 1);
        double *swap = a; a = b; b = swap;
    }
}

/* Pin each worker to a distinct CPU from the mask this process was given.
 * Without it the two threads can land on different chiplets and the candidate
 * loses to its own serial baseline -- a placement result, not a kernel one.
 * The chosen CPU id is never recorded: only the policy is. */
/* One thread per distinct physical core. Taking the first allowed CPUs is not
 * enough: on an SMT machine with an unrestricted mask those are siblings of a
 * single core, and two threads sharing one core cannot beat the serial
 * baseline. Siblings are read from topology, never from a CPU-count guess. */
static int first_sibling_of(int cpu) {
    char path[128];
    snprintf(path, sizeof(path),
             "/sys/devices/system/cpu/cpu%d/topology/thread_siblings_list", cpu);
    FILE *handle = fopen(path, "r");
    if (!handle) return cpu;
    int first = cpu;
    if (fscanf(handle, "%d", &first) != 1) first = cpu;
    fclose(handle);
    return first;
}

/* Topology is read once, before any timing: reading sysfs inside the timed
 * region made the candidate look 3x slower than its baseline. */
static int core_leaders[CPU_SETSIZE];
static int core_leader_count = 0;

static void detect_cores(void) {
    cpu_set_t allowed;
    CPU_ZERO(&allowed);
    if (sched_getaffinity(0, sizeof(allowed), &allowed) != 0) return;
    for (int cpu = 0; cpu < CPU_SETSIZE && core_leader_count < CPU_SETSIZE; ++cpu) {
        if (!CPU_ISSET(cpu, &allowed)) continue;
        int leader = first_sibling_of(cpu);
        int known = 0;
        for (int i = 0; i < core_leader_count; ++i) known |= (core_leaders[i] == leader);
        if (!known) core_leaders[core_leader_count++] = leader;
    }
}

static void pin_to_allowed_cpu(int index) {
    if (core_leader_count == 0) return;
    cpu_set_t one;
    CPU_ZERO(&one);
    CPU_SET(core_leaders[index % core_leader_count], &one);
    pthread_setaffinity_np(pthread_self(), sizeof(one), &one);
}

static void *stencil_worker(void *argument) {
    StencilWork *work = argument;
    pin_to_allowed_cpu(work->index);
    double *a = *work->flip, *b = *work->flop;
    for (int s = 0; s < work->steps; ++s) {
        stencil_sweep(a, b, work->y0, work->y1);
        pthread_barrier_wait(work->barrier);  /* every read of b is after its write */
        double *swap = a; a = b; b = swap;
    }
    return NULL;
}

static void stencil_candidate(double *a, double *b, int steps) {
    pthread_t threads[STENCIL_THREADS];
    StencilWork work[STENCIL_THREADS];
    pthread_barrier_t barrier;
    pthread_barrier_init(&barrier, NULL, STENCIL_THREADS);
    int interior = STENCIL_NY - 2;
    for (int t = 0; t < STENCIL_THREADS; ++t) {
        work[t] = (StencilWork){ .index = t, .y0 = 1 + t * interior / STENCIL_THREADS,
            .y1 = 1 + (t + 1) * interior / STENCIL_THREADS,
            .barrier = &barrier, .steps = steps, .flip = &a, .flop = &b };
        pthread_create(&threads[t], NULL, stencil_worker, &work[t]);
    }
    for (int t = 0; t < STENCIL_THREADS; ++t) pthread_join(threads[t], NULL);
    pthread_barrier_destroy(&barrier);
}

static void stencil_fill(double *a, double *b, unsigned long long seed) {
    seed_reset(seed);
    size_t count = (size_t)STENCIL_NX * STENCIL_NY;
    for (size_t i = 0; i < count; ++i) a[i] = next_unit() - 0.5;
    memcpy(b, a, count * sizeof(double));
}

static int stencil_selftest(void) {
    size_t count = (size_t)STENCIL_NX * STENCIL_NY;
    double *a = malloc(count * sizeof(double)), *b = malloc(count * sizeof(double));
    double *c = malloc(count * sizeof(double)), *d = malloc(count * sizeof(double));
    double *u = malloc(count * sizeof(double)), *v = malloc(count * sizeof(double));
    if (!a || !b || !c || !d || !u || !v) return 2;

    /* Trajectory equivalence: compare after every single step, not only at
     * the end, so a candidate that drifts and re-converges still fails. */
    stencil_fill(a, b, 0xBEEFULL);
    stencil_fill(c, d, 0xBEEFULL);
    double worst = 0.0;
    for (int s = 1; s <= STENCIL_STEPS; ++s) {
        stencil_fill(a, b, 0xBEEFULL);
        stencil_fill(c, d, 0xBEEFULL);
        stencil_baseline(a, b, s);
        stencil_candidate(c, d, s);
        const double *lhs = (s % 2) ? b : a;
        const double *rhs = (s % 2) ? d : c;
        double scale = max_abs(lhs, count);
        double step = max_abs_diff(lhs, rhs, count) / (scale > 0 ? scale : 1.0);
        if (step > worst) worst = step;
    }
    printf("trajectory_relative=%.3e\n", worst);

    /* Metamorphic: the sweep is linear, so solving a sum equals the sum of
     * the solutions. */
    stencil_fill(a, b, 0x11ULL);
    stencil_fill(c, d, 0x22ULL);
    size_t i;
    for (i = 0; i < count; ++i) u[i] = a[i] + c[i];
    memcpy(v, u, count * sizeof(double));
    stencil_candidate(a, b, STENCIL_STEPS);
    stencil_candidate(c, d, STENCIL_STEPS);
    stencil_candidate(u, v, STENCIL_STEPS);
    const double *sa = (STENCIL_STEPS % 2) ? b : a;
    const double *sc = (STENCIL_STEPS % 2) ? d : c;
    const double *su = (STENCIL_STEPS % 2) ? v : u;
    for (i = 0; i < count; ++i) b[i] = sa[i] + sc[i];
    double scale = max_abs(su, count);
    double linearity = max_abs_diff(b, su, count) / (scale > 0 ? scale : 1.0);
    printf("metamorphic_linearity=%.3e\n", linearity);

    free(a); free(b); free(c); free(d); free(u); free(v);
    int ok = worst < 1e-12 && linearity < 1e-9;
    printf("selftest=%s\n", ok ? "pass" : "fail");
    return ok ? 0 : 1;
}

static void stencil_bench(int replays, int trials) {
    size_t count = (size_t)STENCIL_NX * STENCIL_NY;
    double *a = malloc(count * sizeof(double)), *b = malloc(count * sizeof(double));
    if (!a || !b) { printf("bench=alloc_failed\n"); return; }
    stencil_fill(a, b, 0xBEEFULL);
    stencil_baseline(a, b, 2);
    stencil_candidate(a, b, 2);
    for (int r = 0; r < replays; ++r) {
        double base = 0.0, cand = 0.0;
        for (int t = 0; t < trials; ++t) {
            stencil_fill(a, b, 0xBEEFULL);
            double t0 = now_seconds(); stencil_baseline(a, b, STENCIL_STEPS);
            double t1 = now_seconds();
            stencil_fill(a, b, 0xBEEFULL);
            double t2 = now_seconds(); stencil_candidate(a, b, STENCIL_STEPS);
            double t3 = now_seconds();
            if (t == 0 || t1 - t0 < base) base = t1 - t0;
            if (t == 0 || t3 - t2 < cand) cand = t3 - t2;
        }
        printf("replay=%d baseline_s=%.9f candidate_s=%.9f\n", r, base, cand);
    }
    free(a); free(b);
}

/* ------------------------------------------------------------------ cli -- */

int main(int argc, char **argv) {
    detect_cores();
    if (argc < 3) { fprintf(stderr, "usage: %s <task> <selftest|bench>\n", argv[0]); return 2; }
    int replays = 4, trials = 3;
    int bench = strcmp(argv[2], "bench") == 0;
    if (strcmp(argv[1], "gemm") == 0) {
        if (bench) { gemm_bench(replays, trials); return 0; }
        return gemm_selftest();
    }
    if (strcmp(argv[1], "spmm") == 0) {
        if (bench) { spmm_bench(replays, trials); return 0; }
        return spmm_selftest();
    }
    if (strcmp(argv[1], "stencil") == 0) {
        if (bench) { stencil_bench(replays, trials); return 0; }
        return stencil_selftest();
    }
    fprintf(stderr, "unknown task\n");
    return 2;
}
