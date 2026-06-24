CC ?= cc
CFLAGS ?= -O2 -I.
LDLIBS ?= -lm

candidate: candidate_meshpart.c meshpart_main.c meshpart_kernel.h
	$(CC) $(CFLAGS) candidate_meshpart.c meshpart_main.c -o candidate $(LDLIBS)

baseline: baseline_meshpart.c meshpart_main.c meshpart_kernel.h
	$(CC) $(CFLAGS) baseline_meshpart.c meshpart_main.c -o baseline $(LDLIBS)

selftest: candidate_meshpart.c selftest.c meshpart_kernel.h
	$(CC) $(CFLAGS) candidate_meshpart.c selftest.c -o selftest $(LDLIBS)

# THE iteration command. Always recompiles the self-test against your CURRENT
# candidate_meshpart.c and runs it, so you can never test a stale binary.
check: candidate_meshpart.c selftest.c meshpart_kernel.h
	@$(CC) $(CFLAGS) candidate_meshpart.c selftest.c -o selftest $(LDLIBS)
	@./selftest

clean:
	rm -f candidate baseline selftest

.PHONY: check clean
