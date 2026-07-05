# 3-D Jacobi stencil kernel harness — manual build.
# The Python runner (ari/evaluator/stencil_harness.py:_default_run_kernel)
# compiles directly with IDENTICAL flags for baseline and candidate (so the
# speedup measures the algorithm, not flags); this Makefile mirrors that for
# manual use.
CC ?= cc
CFLAGS ?= -O3 -fopenmp -march=native

baseline: stencil_main.c baseline_stencil.c stencil_kernel.h
	$(CC) $(CFLAGS) -I. stencil_main.c baseline_stencil.c -o baseline -lm

candidate: stencil_main.c candidate_stencil.c stencil_kernel.h
	$(CC) $(CFLAGS) -I. stencil_main.c candidate_stencil.c -o candidate -lm

# Local developer self-test (NOT the evaluator): correctness + a speedup
# estimate for your candidate. Build & run:  make selftest && ./selftest
selftest: selftest.c candidate_stencil.c stencil_kernel.h
	$(CC) $(CFLAGS) -I. selftest.c candidate_stencil.c -o selftest -lm

# Convenience: build + run the self-test in one step.
check: selftest
	./selftest

clean:
	rm -f baseline candidate selftest

.PHONY: clean check
