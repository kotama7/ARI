# meshpart_kernels — balanced k-way graph partitioning scaffolding (handoff study task C)

Frozen scaffolding seeded into each BFTS node's work dir when `ARI_TASK=meshpart`
(see `ari/evaluator/meshpart_harness.py`). The agent edits `candidate_meshpart.c`
to implement a balanced k-way graph partitioner that minimizes the edge-cut; a
deterministic evaluator scores it with the combined cut+balance objective
`score = bal · q ∈ [0,1]` (no LLM judge).

Why this task exists: it is the **combinatorial-optimization Goldilocks
candidate**. ANY partition is a valid, scoreable solution (no compile-or-die
`None` nodes — the failure mode that floored erfc for weak models), the optimum
is NP-hard (no terminal "solved" state), and the gradient from random → reference
is long and continuous, so mid-capability models (qwen-32b) produce valid-but-
suboptimal partitions that children can refine — the valid-partial-progress
regime the handoff comparison needs.

## Contents

- `README.md` — this file.
- `baseline_meshpart.c` — FROZEN poor baseline (round-robin `i % k`: balanced but
- `candidate_meshpart.c` — the file the agent edits (starts as the baseline).
- `experiment.md` — the task statement handed to the BFTS agent.
- `Makefile` — `make candidate` / `make baseline` / `make selftest`.
- `meshpart_kernel.h` — the `partition()` contract (CSR in, labels out). Frozen.
- `meshpart_main.c` — FROZEN driver: reads `mesh.bin` (CSR), prints the partition.
- `selftest.c` — local self-test: reports edge-cut and imbalance on the seeded
