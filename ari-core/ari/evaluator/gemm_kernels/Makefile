# GEMM kernel harness (handoff study task A) — manual build.
# The Python runner (ari/evaluator/gemm_harness.py:_default_run_kernel) compiles
# directly with IDENTICAL flags for baseline and candidate (so the speedup
# measures the algorithm, not flags); this Makefile mirrors that for manual use.
# No BLAS is linked — write the kernel yourself.
CC ?= cc
CFLAGS ?= -O3 -fopenmp -march=native

baseline: gemm_main.c baseline_gemm.c gemm_kernel.h
	$(CC) $(CFLAGS) -I. gemm_main.c baseline_gemm.c -o baseline -lm

candidate: gemm_main.c candidate_gemm.c gemm_kernel.h
	$(CC) $(CFLAGS) -I. gemm_main.c candidate_gemm.c -o candidate -lm

# Local developer self-test (NOT the evaluator): correctness + a speedup
# estimate for your candidate. Build & run:  make selftest && ./selftest
selftest: selftest.c candidate_gemm.c gemm_kernel.h
	$(CC) $(CFLAGS) -I. selftest.c candidate_gemm.c -o selftest -lm

clean:
	rm -f baseline candidate selftest

.PHONY: clean
