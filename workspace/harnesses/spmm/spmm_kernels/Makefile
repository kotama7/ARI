# SpMM kernel harness (handoff study B2b) — manual build.
# The Python runner (ari/evaluator/spmm_harness.py:_default_run_kernel) compiles
# directly with IDENTICAL flags for baseline and candidate (so the speedup
# measures the algorithm, not flags); this Makefile mirrors that for manual use.
CC ?= cc
CFLAGS ?= -O3 -fopenmp
# Keep the local build consistent with the evaluator: candidate-only tuning
# flags are read from the same file after allowlist screening by the scorer.
CANDFLAGS := $(shell test -f candidate_flags.txt && grep -v '^\#' candidate_flags.txt | tr '\n' ' ')

baseline: spmm_main.c baseline_spmm.c spmm_kernel.h
	$(CC) $(CFLAGS) -I. spmm_main.c baseline_spmm.c -o baseline -lm

candidate: spmm_main.c candidate_spmm.c spmm_kernel.h
	$(CC) $(CFLAGS) $(CANDFLAGS) -I. spmm_main.c candidate_spmm.c -o candidate -lm

# Local developer self-test (NOT the evaluator): correctness + a speedup
# estimate for your candidate. Build & run:  make selftest && ./selftest
selftest: selftest.c candidate_spmm.c spmm_kernel.h
	$(CC) $(CFLAGS) $(CANDFLAGS) -I. selftest.c candidate_spmm.c -o selftest -lm

clean:
	rm -f baseline candidate selftest

.PHONY: clean
