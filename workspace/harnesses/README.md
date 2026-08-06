# harnesses — the registered task harnesses

ARI ships **no** task. Each directory here is one benchmark, registered by the
mere presence of its `harness.toml`, and resolved by
`ari/evaluator/harness_registry.py`. Adding, changing or removing a task never
edits the ARI repo.

A harness owns the task-specific half of scoring: seed a node's work_dir with the
frozen scaffolding, then compile and measure the node's candidate. The
task-INDEPENDENT half — the all-or-nothing validity gate, the geomean, and the
BFTS ranking value — stays in ARI's `DeterministicEvaluator` and is never
delegated. For speedup tasks that ranking value is the native valid geomean
speedup, not a `[0,1]` normalization.

## Layout

    <task>/
        harness.toml          # axis / compatibility target+scale / measure_kwargs / sha256 pins
        <task>_harness.py     # seed_work_dir, measure_node, kernels_dir [, profile_node]
        <task>_kernels/       # the frozen C scaffolding (driver, baseline, header, selftest)
        experiment.md         # the goal statement the agent is scored against
        tests/                # the harness's own tests (pytest workspace/harnesses/)

## profile_node — counters for the scored region, never a score

The three speedup harnesses also expose `profile_node(work_dir, ...)`: hardware
counters (IPC, L1D refill rate, the fraction of L1 misses reaching memory) taken
over **the same region the score is built from**, with the same compiler and the
same screened flags, through the same `_compile_kernel`. Its numbers never enter
`speedup`, `valid` or anything the evaluator reads — a profile that could move a
score would be a second scoring channel with none of the first one's anti-gaming
surface — and `seed_work_dir` does not seed the profiled driver, so the node
never sees it.

The region has to be marked, not assumed. `<task>_main_profiled.c` is
`<task>_main.c` plus a counter gate; every added line carries a `/*GATE*/` marker
and `tests/test_profile_region.py` asserts that deleting the marked lines
reproduces the scored driver byte for byte, because a stale copy would profile
last month's timing semantics while looking current. Counting the whole process
instead was measured at **7.16x** the region's cycles, and the driver's serial
NaN-poison pass is pure write-allocate traffic, so it drags the L2D ratio toward
"memory bound" for every candidate.

**What it is blind to.** The harness first-touches its buffers OUTSIDE the timed
window, so page-fault, TLB and NUMA-placement work is mostly not in the region —
this is the same fact `[declares].blind_to` already states. Only scratch the
candidate allocates itself faults inside. First touch is a question for
`tools/check_first_touch.py` and the fixed term in `tools/measure_timed_window.py`,
not for these counters. And like the score it is **one cold call, no warmup**: a
warm profile would describe a regime the score never measures, so repeat the
process rather than the call.

## What each task measures

- `erfc/` — **erfc accuracy-coverage** (task B, the "Goldilocks" task): scipy reference, region-stratified hidden points, score = fraction within rel-tol 1e-9 over a wide domain (`measure_node` returns a score-shaped dict). Long cumulative ladder (center→mid→tail→deeptail) no model one-shots; selftest uses a distinct seed (anti-gaming). Login-testable.
- `gemm/` — **dense GEMM** (task A): fp64 reference oracle, contraction-length correctness bound, fixed shapes, geomean aggregation. Compute-bound counterpart to SpMM with a multi-rung optimization gradient; pure parts login-tested, compile/run runner compute-node only.
- `meshpart/` — **balanced k-way graph partitioning** (task C, the combinatorial "Goldilocks" task): procedural custom mesh (2-D k-NN graph + long edges → CSR, no memorized answer), recursive-spectral reference cut, score = `bal · q ∈ [0,1]` combining balance and edge-cut quality. ANY partition is valid/scoreable (no compile-or-die None) and the optimum is NP-hard, so mid models make valid-but-suboptimal partitions children can refine; selftest mesh uses a distinct seed (anti-gaming). Pure parts login-tested; compile/run runner login-capable too.
- `spmm/` — **SpMM** (handoff study B2b; the default task): fp64 reference oracle, per-element correctness bound (eps model), seeded matrix families, geomean aggregation. Pure parts login-tested; compile/run/timing runner is compute-node only.
- `stencil/` — **3-D 7-point Jacobi stencil** (task D, a genuine memory-bandwidth-bound performance kernel): fp64 nt-sweep reference oracle, nt-scaled per-element correctness bound, fixed grid shapes (one cube + two anisotropic boxes), geomean-speedup aggregation. Plain parallelism saturates the bandwidth roofline (the one-shot rung); SIMD + spatial blocking + NUMA first-touch + temporal/time tiling climb above it.
- `tests/` — what must stay true of every registered harness, one file per property. See below.

## tests/ — one file per way the scoring can go quietly wrong

Each file pins a property whose failure mode is *silence*: the harness keeps
running, the numbers keep looking reasonable, and only the meaning changes.

- `tests/test_registered_harnesses.py` — cross-task parity: every harness still declares what it declared before it was relocated out of the ARI package (target, scale, `measure_node` kwargs, seeded file set). Guards the uniform-call trap described above.
- `tests/test_campaign_matrix.py` — the registered campaign design cannot be overridden by ambient environment. A study whose matrix silently follows whatever was exported is not the study that was registered.
- `tests/test_matched_denominator.py` — the second denominator is built from the *reference* source, not a second copy of the candidate. If it were the candidate, the matched ratio would be 1 by construction and would certify nothing. Structural only; the numeric invariant needs a compute node.
- `tests/test_measurement_environment.py` — the measurement-relevant environment is captured with every result, widely enough to include the variables known to move a score (`XOS_MMM_L_PAGING_POLICY` moves the frozen stencil by 5.9x) and narrowly enough that a credential's *value* never reaches a published result file. Also that the digest actually digests what was captured, and that the record is attached to the result rather than merely computable.
- `tests/test_compare_harnesses.py` — the three ways to fake harness agreement, each of which produces a comforting number: comparing scores instead of orderings, counting a pair the harness cannot resolve, and dropping candidates that failed to build under one harness. Pins that an all-abstained comparison reports `n/a` rather than 100% — the most dangerous available output, since it turns no evidence into a perfect result.
- `tests/test_environment_drift_checker.py` — the exit codes of `tools/check_environment_drift.py` are its contract, so they are pinned rather than confirmed by running it once. Running it once is exactly what let a defect through: a capture matching nothing still yields a digest, so every scoring agreed and a study whose capture was BROKEN read as more consistent than one that worked — the silent-failure shape the checker exists to catch, reproduced inside the checker. 0 = one digest over non-empty records, 1 = drift (and the differing variable must be named), 2 = nothing usable, whether no records or all empty.
- `tests/test_isa_flags.py` — the ISA flag is chosen per compiler. Measured on an aarch64 compute node 2026-08-07: `fcc -O3 -fopenmp -march=native` compiles, but `fcc -Nclang -O3 -fopenmp -march=native` fails with `clang-7: error: the clang compiler does not support '-march=native'` — and `-Nclang` is the mode fcc is worth selecting in (403 GF/s against gcc's 385 on this kernel). So the flag breaks precisely the interesting case. **Note the campaign bypasses this logic entirely**: `ARI_{GEMM,STENCIL}_CFLAGS` is exported with `-march=native` baked in, and `base_cflags` takes the env branch, so `_isa_flags_for` never runs on the campaign path. Pinned in both directions: the vendor compiler must not receive it, and the compilers that accept it must keep it, since dropping it globally would de-optimize the default build that is the denominator of every score.

## What every result now records about WHERE it ran

`measurement_environment()` answers "under what settings" — and every variable in
it is a constant the launcher exports, invariant to the hardware. So a study
spread across allocations of different shape passed every check and reported one
environment. Measured on two partitions of one cluster on 2026-08-07: four NUMA
domains of twelve cores with 64 KiB pages and a cpuset covering the whole node,
against one domain with 4 KiB pages and a cpuset of eight cores plus their SMT
siblings carved out of 192. Nothing in a result told them apart.

`measurement_placement()` records the other half — machine, page size, cpuset and
its size, NUMA domains present and how many the allocation spans, the thread
budget the timed child will actually get, and the binding regime it inherits —
with its own digest, kept SEPARATE so the environment digest stays comparable
with every record already written. `tools/check_environment_drift.py` reads it
back and refuses a study whose runs did not land on the same shape of machine.

It matters because placement is not neutral and nothing sets it. There is no
`numactl`, `taskset`, `mbind` or `set_mempolicy` anywhere on the measurement
path, so `placement_is_set_by_the_study` is a literal `False` in the record. The
scored arrays are first-touched SERIALLY outside the timed window, so every page
lands on one memory domain — measured, 100% on one node — while the threads are
spread across all of them. Only stencil's candidate first-touches anything under
measurement (its own 268 MB), which is why it is the one task whose `sees`
declares `numa_first_touch` and `large_page_policy`, and the one the vendor
paging policy moves by 5.9x.

## measure_kwargs is not decoration

Every `measure_node` above accepts `(work_dir, *, seed=0)`, so a *uniform*
`measure_node(work_dir, seed=seed)` is a LEGAL call against all five — it just
silently measures something else. SpMM at its harness default (n=512/k=32)
instead of the study size (n=20000/k=64) is ~39x smaller, where parallel overhead
dominates, even a perfect kernel scores ~1x, and the BFTS gradient dies: no
crash, plausible numbers, dead experiment. GEMM was never passed a seed at all,
so honouring `ARI_SEED` would break comparability with banked replicates. Each
harness therefore DECLARES its own call in `harness.toml`, and
`tests/test_registered_harnesses.py` captures the actual call to pin it.

## What the integrity pins do and do not buy

`load()` verifies every pinned sha256 before binding a harness, so modified
measurement scaffolding **refuses to score** instead of scoring differently.
That is drift/tamper *detection*, not a sandbox: the agent's `run_bash` runs as
the same uid as the evaluator. The property that IS enforced is that the node's
edits cannot reach the scorer — each harness resolves the driver, the baseline
and `-I` from its own `kernels_dir()` and takes only `candidate_*.c` from
`work_dir`, compiling into a fresh temp dir. The node is deliberately *given*
copies of the scaffolding so it can self-test; those copies never participate in
scoring. Say "the agent's edits cannot reach the scorer", never "the scaffolding
cannot be edited".
