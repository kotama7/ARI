/* Measure the core clock with the kernel PMU, because this machine offers no
 * other way to see it.
 *
 * WHY THIS EXISTS. `perf` is not installed here and no module provides it
 * (checked on a compute node with the vendor entry module loaded), there is no
 * `cpufreq` directory under cpu0, and /proc/cpuinfo reports only "BogoMIPS 200".
 * Concluding from that that the clock is unobservable was wrong: the PMU IS
 * exposed as /sys/bus/event_source/devices/armv8_pmuv3_0 and
 * perf_event_paranoid is 0, so unprivileged cycle counting is permitted through
 * perf_event_open(2) directly — the missing piece was the tool, not the counter.
 *
 * Counts CPU cycles across a fixed wall interval on one pinned thread while that
 * thread is busy, so cycles/second is the frequency the core actually ran at,
 * not a nominal one. Reported alongside a second, longer interval: a governor
 * ramping would show up as a difference between them. */
#define _GNU_SOURCE
#include <linux/perf_event.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/syscall.h>
#include <time.h>
#include <unistd.h>

static long perf_open(struct perf_event_attr *a, pid_t p, int c, int g, unsigned long f) {
    return syscall(__NR_perf_event_open, a, p, c, g, f);
}
static double now(void) {
    struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t);
    return (double)t.tv_sec + (double)t.tv_nsec * 1e-9;
}

static int measure(double seconds, double *ghz) {
    struct perf_event_attr attr;
    memset(&attr, 0, sizeof(attr));
    attr.type = PERF_TYPE_HARDWARE;
    attr.size = sizeof(attr);
    attr.config = PERF_COUNT_HW_CPU_CYCLES;
    attr.disabled = 1;
    attr.exclude_kernel = 1;
    attr.exclude_hv = 1;
    int fd = (int)perf_open(&attr, 0, -1, -1, 0);
    if (fd < 0) { perror("perf_event_open"); return -1; }

    ioctl(fd, PERF_EVENT_IOC_RESET, 0);
    ioctl(fd, PERF_EVENT_IOC_ENABLE, 0);
    double t0 = now();
    volatile double x = 1.0;
    while (now() - t0 < seconds) { for (int i = 0; i < 100000; ++i) x = x * 1.0000001 + 1.0; }
    double dt = now() - t0;
    ioctl(fd, PERF_EVENT_IOC_DISABLE, 0);

    long long cycles = 0;
    if (read(fd, &cycles, sizeof(cycles)) != sizeof(cycles)) { perror("read"); close(fd); return -1; }
    close(fd);
    (void)x;
    *ghz = (double)cycles / dt * 1e-9;
    printf("  %.1f s busy: %lld cycles -> %.4f GHz\n", dt, cycles, *ghz);
    return 0;
}

int main(void) {
    double a = 0.0, b = 0.0;
    if (measure(1.0, &a) || measure(3.0, &b)) return 1;
    printf("  agreement between the two intervals: %.2f%%\n", (b - a) / a * 100.0);
    return 0;
}
