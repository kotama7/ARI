# ari.evaluator

LLM-driven metric extraction and dynamic axis generation — the BFTS judge
that scores each completed node into the multi-axis composite the
orchestrator consumes.

Also home to the **deterministic** (non-LLM) judge used by the handoff study.
That judge owns only the task-INDEPENDENT half of scoring — the all-or-nothing
validity gate, the geomean, and the native ranking value. The task-specific half
(seed the work_dir, compile, measure) belongs to a **harness**, and ARI ships
none: harnesses are registered under `$ARI_WORKSPACE/harnesses/<task>/` and
resolved through `ari/harness_registry.py` (top level, not here: where a harness
lives is a file-layout question, and this package is barred from `ari.paths` by
report 003 §7 B5). A benchmark is an experiment asset with
its own lifecycle, not a framework feature, so adding/changing/removing a task
never edits this package.

## Contents

- `README.md` — this file.
- `__init__.py` — public symbols + axis design.
- `abi_probe.py` — subprocess entry point for the ABI symbol audit: `dlopen` the built candidate library, `dlsym` each symbol the declared contract names, write the answer to a file. Exists only so that the audit does NOT happen in the scorer. `dlopen` runs the object's ELF constructors, so while this ran in-process a candidate got a code slot inside the process that scores every later node — measured: a candidate declaring `-Ofast` links `crtfastmath.o`, whose constructor sets the MXCSR FTZ/DAZ bits process-wide and with no matching unset, and `5e-324 * 1.0` returned `5e-324` before the audit and `0.0` after it, so oracles whose bound depends on denormals (spmm's exact 0.0 for an empty row) silently changed answer for every subsequent candidate. Screening flag spellings does not close it — the same flush was measured from a plain `-O2` candidate with its own `__attribute__((constructor))` — and neither does saving/restoring the FP registers, since a constructor runs arbitrary code. Still `dlopen`+`dlsym` rather than reading `.dynsym`, so the audit and the verification it gates cannot disagree about what "exported" means.
- `assurance_measure.py` — scores a node against a PINNED PROBLEM instead of a workspace harness: resolves `ARI_PROBLEM` (no default — an unset task used to fall through to a different benchmark), seeds the work dir once (never over an inherited candidate, which IS the handoff), and turns a `NativePerfReportV1` into the dict `_score` already consumes. Owns no scoring. Two error classes are load-bearing: a `PerfBuildError` is the candidate's and is scored 0.0, everything else is the instrument's and is raised so the node goes unranked. Validity means CORRECTNESS, not the regression verdict — against a competent denominator the second would rank every early candidate 0.0 and leave the search no gradient.
- `deterministic_evaluator.py` — `DeterministicEvaluator`: non-LLM judge; writes `metrics._scientific_score` to drive BFTS selection (handoff study). Selected via `ARI_EVALUATOR=deterministic`; task via `ARI_TASK`. Owns the scoring CONTRACT only (geomean over the family set, native geomean speedup as the BFTS ranking value, "invalid if any required family fails" — no zeros mixed into the geomean). Speedup-shaped harnesses report a geomean speedup; score-shaped ones store a bounded `[0,1]` score in the same field for analyzer reuse (it is NOT a speedup — the analyzer reports each on its native axis). When the measurement could not be taken at all (`evaluation_status="infrastructure_error"`) it emits `metrics={}` and NO top-level `scientific_score`: an outage is not a candidate result, and a 0.0 there ranked a missing harness exactly like a kernel that ran and lost.
- `dynamic_axes.py` — venue/run-specific evaluation-axis derivation.
- `handoff_stats.py` — run-level analysis statistics for the handoff study: native-outcome permutation tests, run-level bootstrap confidence intervals, Holm correction, and per-arm summaries. Pure; consumed by `workspace/analyze_handoff_ablation.py`.
- `llm_evaluator.py` — `LLMEvaluator`: extraction + multi-axis composite scoring.

## Where the harnesses went

The five study harnesses (`gemm`, `spmm`, `stencil`, `erfc`, `meshpart`) and their
frozen C fixtures used to live here as `<task>_harness.py` + `<task>_kernels/`.
They now live in the workspace, one directory per task, each with its own
`harness.toml`, `experiment.md` and tests:

    $ARI_WORKSPACE/harnesses/<task>/
        harness.toml          # target / scale / measure_kwargs / sha256 pins
        <task>_harness.py     # seed_work_dir, measure_node, kernels_dir
        <task>_kernels/       # the frozen C scaffolding
        experiment.md         # the goal statement the agent is scored against
        tests/                # the harness's own tests

See `$ARI_WORKSPACE/harnesses/README.md` for what each task measures.

## See also

- **Public symbols (`LLMEvaluator`, `MetricSpec`) & axis design** → the `__init__.py` module docstring (authoritative).
- **Harness contract & integrity model** → the `ari/harness_registry.py` module docstring (authoritative).
- **Plan / Venue contract** → `docs/concepts/architecture.md`.
- **History** → `git log -- ari-core/ari/evaluator/`.
