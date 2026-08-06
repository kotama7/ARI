#define _GNU_SOURCE

#include <errno.h>
#include <math.h>
#include <sched.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#ifndef ARI_MEMORY_SAFETY_BUILD
#define ARI_MEMORY_SAFETY_BUILD 0
#endif

static volatile double result_sink;

static uint64_t monotonic_ns(void) {
    struct timespec value;
    if (clock_gettime(CLOCK_MONOTONIC_RAW, &value) != 0) {
        perror("clock_gettime");
        exit(2);
    }
    return (uint64_t)value.tv_sec * UINT64_C(1000000000) + (uint64_t)value.tv_nsec;
}

static int pin_to_first_allowed_cpu(void) {
    cpu_set_t allowed;
    if (sched_getaffinity(0, sizeof(allowed), &allowed) != 0) {
        return 0;
    }
    for (int cpu = 0; cpu < CPU_SETSIZE; ++cpu) {
        if (CPU_ISSET(cpu, &allowed)) {
            cpu_set_t selected;
            CPU_ZERO(&selected);
            CPU_SET(cpu, &selected);
            return sched_setaffinity(0, sizeof(selected), &selected) == 0;
        }
    }
    return 0;
}

__attribute__((noinline))
static double serial_accumulator(const double *a, const double *b, size_t count) {
    double sum = 0.0;
    for (size_t index = 0; index < count; ++index) {
        sum += a[index] * b[index];
    }
    return sum;
}

__attribute__((noinline))
static double parallel_accumulator(const double *a, const double *b, size_t count) {
    double sum0 = 0.0;
    double sum1 = 0.0;
    double sum2 = 0.0;
    double sum3 = 0.0;
    double sum4 = 0.0;
    double sum5 = 0.0;
    double sum6 = 0.0;
    double sum7 = 0.0;
    size_t index = 0;
    for (; index + 7 < count; index += 8) {
        sum0 += a[index + 0] * b[index + 0];
        sum1 += a[index + 1] * b[index + 1];
        sum2 += a[index + 2] * b[index + 2];
        sum3 += a[index + 3] * b[index + 3];
        sum4 += a[index + 4] * b[index + 4];
        sum5 += a[index + 5] * b[index + 5];
        sum6 += a[index + 6] * b[index + 6];
        sum7 += a[index + 7] * b[index + 7];
    }
    double sum = (sum0 + sum1) + (sum2 + sum3) + (sum4 + sum5) + (sum6 + sum7);
    for (; index < count; ++index) {
        sum += a[index] * b[index];
    }
    return sum;
}

static int compare_u64(const void *left, const void *right) {
    uint64_t a = *(const uint64_t *)left;
    uint64_t b = *(const uint64_t *)right;
    return (a > b) - (a < b);
}

static uint64_t clock_overhead_ns(void) {
    uint64_t best = UINT64_MAX;
    for (int trial = 0; trial < 10000; ++trial) {
        uint64_t begin = monotonic_ns();
        uint64_t end = monotonic_ns();
        if (end - begin < best) {
            best = end - begin;
        }
    }
    return best;
}

static uint64_t measure(
    double (*function)(const double *, const double *, size_t),
    const double *a,
    const double *b,
    size_t count,
    int iterations,
    uint64_t timer_overhead
) {
    uint64_t begin = monotonic_ns();
    double value = 0.0;
    for (int iteration = 0; iteration < iterations; ++iteration) {
        value += function(a, b, count);
    }
    uint64_t end = monotonic_ns();
    result_sink = value;
    uint64_t elapsed = end - begin;
    return elapsed > timer_overhead ? elapsed - timer_overhead : 0;
}

int main(int argc, char **argv) {
    size_t count = argc > 1 ? (size_t)strtoull(argv[1], NULL, 10) : (size_t)16777216;
    int trials = argc > 2 ? atoi(argv[2]) : 9;
    int iterations = argc > 3 ? atoi(argv[3]) : 4;
    if (count < 8 || trials < 1 || trials > 31 || iterations < 1) {
        fprintf(stderr, "invalid benchmark dimensions\n");
        return 2;
    }

    double *a = NULL;
    double *b = NULL;
    if (posix_memalign((void **)&a, 64, count * sizeof(*a)) != 0 ||
        posix_memalign((void **)&b, 64, count * sizeof(*b)) != 0) {
        fprintf(stderr, "allocation failed\n");
        free(a);
        free(b);
        return 2;
    }

    /* Explicit serial first-touch occurs before every warmup or timed sample. */
    for (size_t index = 0; index < count; ++index) {
        a[index] = (double)((int)(index % 97) - 48);
        b[index] = (double)((int)(index % 31) - 15);
    }

    int affinity_pinned = pin_to_first_allowed_cpu();
    double baseline_value = serial_accumulator(a, b, count);
    double candidate_value = parallel_accumulator(a, b, count);
    if (baseline_value != candidate_value) {
        fprintf(stderr, "differential correctness failure: %.17g != %.17g\n",
                baseline_value, candidate_value);
        free(a);
        free(b);
        return 1;
    }

    /* One untimed warmup per implementation; setup and first-touch stay outside timing. */
    result_sink = serial_accumulator(a, b, count);
    result_sink = parallel_accumulator(a, b, count);

    uint64_t overhead = clock_overhead_ns();
    uint64_t baseline[31];
    uint64_t candidate[31];
    for (int trial = 0; trial < trials; ++trial) {
        if ((trial & 1) == 0) {
            baseline[trial] = measure(serial_accumulator, a, b, count, iterations, overhead);
            candidate[trial] = measure(parallel_accumulator, a, b, count, iterations, overhead);
        } else {
            candidate[trial] = measure(parallel_accumulator, a, b, count, iterations, overhead);
            baseline[trial] = measure(serial_accumulator, a, b, count, iterations, overhead);
        }
    }
    qsort(baseline, (size_t)trials, sizeof(*baseline), compare_u64);
    qsort(candidate, (size_t)trials, sizeof(*candidate), compare_u64);
    uint64_t baseline_median = baseline[trials / 2];
    uint64_t candidate_median = candidate[trials / 2];
    double speedup = candidate_median == 0 ? 0.0 :
        (double)baseline_median / (double)candidate_median;
    int performance_pass = speedup >= 1.05;

    printf("{\"schema_version\":\"ari.intel-performance-patterns-clean-task/v1\","
           "\"correctness\":\"pass\",\"memory_safety\":\"%s\","
           "\"performance_verdict\":\"%s\",\"count\":%zu,\"trials\":%d,"
           "\"iterations_per_trial\":%d,\"warmup_iterations_per_variant\":1,"
           "\"first_touch_policy\":\"serial-before-warmup-outside-timed-region\","
           "\"sample_order\":\"alternating-baseline-candidate\","
           "\"timer\":\"CLOCK_MONOTONIC_RAW\",\"timer_overhead_ns\":%llu,"
           "\"timed_region\":\"kernel-call-only\",\"affinity_policy\":\"first-allowed-cpu\","
           "\"affinity_pinned\":%s,\"baseline_median_ns\":%llu,"
           "\"candidate_median_ns\":%llu,\"speedup\":%.9f}\n",
           ARI_MEMORY_SAFETY_BUILD ? "pass" : "not_run_in_this_binary",
           performance_pass ? "pass" : "fail", count, trials, iterations,
           (unsigned long long)overhead, affinity_pinned ? "true" : "false",
           (unsigned long long)baseline_median,
           (unsigned long long)candidate_median, speedup);

    free(a);
    free(b);
    return ARI_MEMORY_SAFETY_BUILD || performance_pass ? 0 : 1;
}
