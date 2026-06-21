# erfc task harness — manual build (mirrors erfc_harness.py:_default_run_kernel).
# No erf/erfc from libm allowed — implement the numerics yourself.
CC ?= cc
CFLAGS ?= -O2

baseline: erfc_main.c baseline_erfc.c erfc_kernel.h
	$(CC) $(CFLAGS) -I. erfc_main.c baseline_erfc.c -o baseline -lm

candidate: erfc_main.c candidate_erfc.c erfc_kernel.h
	$(CC) $(CFLAGS) -I. erfc_main.c candidate_erfc.c -o candidate -lm

# Local self-test: per-region accuracy of your candidate vs the seeded reference
# points (ref_points.csv). Build & run:  make selftest && ./selftest
selftest: selftest.c candidate_erfc.c erfc_kernel.h
	$(CC) $(CFLAGS) -I. selftest.c candidate_erfc.c -o selftest -lm

clean:
	rm -f baseline candidate selftest

.PHONY: clean
