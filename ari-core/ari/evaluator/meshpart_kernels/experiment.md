# Experiment: balanced k-way graph partitioning (minimize edge-cut)

Goal: implement `void partition(int n, int k, const int *xadj, const int *adjncy,
int *part)` that splits the `n` vertices of a graph into `k` parts so as to
**minimize the number of cut edges** while keeping the parts **balanced**
(max part size ≤ 1.05 · n/k). A fixed deterministic evaluator scores you — there
is no LLM judge.

## What you produce

Your working directory is **already seeded** — list it:

- `candidate_meshpart.c` — the file you edit (starts as the poor round-robin baseline).
- `meshpart_kernel.h` — the `partition()` contract (do not change the signature).
- `meshpart_main.c` — the FROZEN driver (do not edit).
- `baseline_meshpart.c` — the FROZEN poor baseline.
- `selftest.c` — local self-test (reports your edge-cut and imbalance vs baselines).
- `selftest_mesh.bin` — a seeded mesh for the self-test.
- `Makefile` — **`make check`** is your iteration command (see below).

**Edit ONLY `candidate_meshpart.c`.** The evaluator recompiles *that* file against
its own driver and scores it — so your final algorithm MUST live in
`candidate_meshpart.c`. Do not create your own `main()`, your own test program, or
your own toy graph; iterate with `make check` on the provided mesh.

**Edit `candidate_meshpart.c`.** You MAY `#include <stdlib.h>` and `<math.h>`.
Do NOT use any external partitioning library (METIS, Scotch, …) — implement the
algorithm yourself. **Do NOT write your own `main()`** — the harness provides it
(a duplicate `main` will fail to link).

## The graph (CSR adjacency)

Undirected graph: `xadj` has length `n+1`; vertex `i`'s neighbors are
`adjncy[xadj[i] .. xadj[i+1]-1]`. Every edge appears in both endpoints' lists.
Write each vertex's part label (`0..k-1`) into `part[0..n-1]`. The mesh is a 2-D
proximity graph with a few long-range edges, so good cuts follow spatial/graph
clusters — round-robin or block-by-index labels cut almost every edge.

## How you are judged (fixed, deterministic)

The evaluator runs your `partition` on a HIDDEN mesh and reports a single
**score in [0, 1]** combining cut quality and balance:

- `imb = max_part_size / (n/k)`   (1.0 = perfect balance)
- `bal = 1` if `imb ≤ 1.05`, else it decays linearly to 0 by `imb = 2.05`
- `q   = clamp((random_cut − your_cut) / (random_cut − 0.9·reference_cut), 0, 1)`
- **`score = bal · q`** — you must be BOTH balanced AND low-cut. A degenerate
  "everything in one part" has cut 0 but `imb = k` → `bal = 0` → **score 0**.

So an imbalanced or worse-than-random partition scores ~0; matching a strong
reference cut at good balance scores ~1. Partial credit is continuous: every
edge you uncut (while staying balanced) raises the score.

## Notes

- **Iterate with `make check`** (and ONLY `make check`). It recompiles the
  self-test against your *current* `candidate_meshpart.c` and runs it, so you
  never test a stale binary. It prints your `edge_cut` and `imbalance`, plus the
  `random_cut` (the baseline you must beat) and a `good_reference_cut` (a
  reachable target) on the seeded mesh (NOT the evaluator's hidden mesh, so you
  cannot hardcode). If your `edge_cut` is not below `random_cut`, your partition
  is splitting graph-neighbors apart — put adjacent vertices in the SAME part.
  Lower the cut while keeping imbalance ≤ 1.05.
- A reasonable recipe: build `k` balanced regions (e.g. BFS/greedy growth from
  spread-out seeds, or recursive bisection), then refine the boundary with
  Kernighan–Lin / Fiduccia–Mattheyses swaps that reduce the cut without breaking
  balance. Keep what lowers the cut; revert what doesn't.
- This is NP-hard — you are not expected to find the optimum, only to drive the
  cut down round by round from the random baseline toward the reference.
