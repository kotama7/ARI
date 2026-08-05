# 3-D Jacobi stencil kernel harness — manual build.
# The Python runner (ari/evaluator/stencil_harness.py:_default_run_kernel)
# compiles directly with IDENTICAL flags for baseline and candidate (so the
# speedup measures the algorithm, not flags); this Makefile mirrors that for
# manual use.
CC ?= cc
CFLAGS ?= -O3 -fopenmp -march=native
# Your own tuning flags (design C): the scorer reads this same file and applies
# it to YOUR kernel only, so a local build matches the build you are scored on.
# v2: parse candidate_flags.txt EXACTLY as the evaluator does - unescape a
# literal backslash-n/t, then strip '#' to end of line. v1's grep -v '^\#'
# dropped only whole comment LINES, so a trailing comment reached the local
# build but not the scored one (27 nodes diverged), and a literal backslash-n
# destroyed the flags in 54 files. The three seds must stay SEPARATE
# processes: GNU sed's '.' matches an embedded newline in the pattern space.
CANDFLAGS := $(shell test -f candidate_flags.txt && sed 's/\\n/\n/g' candidate_flags.txt | sed 's/\\t/ /g' | sed 's/\#.*//' | tr '\n' ' ')

baseline: stencil_main.c baseline_stencil.c stencil_kernel.h
	$(CC) $(CFLAGS) -I. stencil_main.c baseline_stencil.c -o baseline -lm

candidate: stencil_main.c candidate_stencil.c stencil_kernel.h
# v2: mirror the evaluator's SPLIT build. The frozen driver is compiled with
# the DEFAULT flags only; the candidate flags reach the kernel object and the
# link (the link matters: -ffast-math there pulls crtfastmath.o, which sets
# FTZ/DAZ process-wide). v1 put CANDFLAGS on the driver too, so a local build
# could differ from the scored one.
	$(CC) $(CFLAGS) -I. -c stencil_main.c -o main_cand.o
	$(CC) $(CFLAGS) $(CANDFLAGS) -I. -c candidate_stencil.c -o kern_cand.o
	$(CC) $(CFLAGS) $(CANDFLAGS) main_cand.o kern_cand.o -o candidate -lm

# Local developer self-test (NOT the evaluator): correctness + a speedup
# estimate for your candidate. Build & run:  make selftest && ./selftest
selftest: selftest.c candidate_stencil.c stencil_kernel.h
	$(CC) $(CFLAGS) $(CANDFLAGS) -I. selftest.c candidate_stencil.c -o selftest -lm

# Convenience: build + run the self-test in one step.
# v2: build, run, and on SUCCESS snapshot the source+flags into .lastgood/.
# Two jobs in one. It collapses the agent's build-then-run into a single
# step (stencil already had it and fused 71.8% of its shell calls this way,
# against 20-25% for the other two). And the snapshot is what makes a
# last-known-good rollback possible: in the previous campaign 86.8% of
# invalid nodes had never recompiled their final edit, so a node that ends
# broken usually has a working state a few edits back.
check: selftest
	./selftest
	@mkdir -p .lastgood && cp -f candidate_stencil.c .lastgood/ 2>/dev/null || true
	@test -f candidate_flags.txt && cp -f candidate_flags.txt .lastgood/ || true
	@echo "snapshot: .lastgood/ updated (selftest passed)"

clean:
	rm -f baseline candidate selftest main_cand.o kern_cand.o

.PHONY: clean check
