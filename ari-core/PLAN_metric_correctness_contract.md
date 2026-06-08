# PLAN: Rigorous Metric-Correctness Contract (domain-general)

Status: design complete, not yet implemented. Origin: design discussion 2026-06-08
(CSR-SpMM checkpoint `20260608153628_We_propose_an_implementation_of_CSR-form`
shipped a paper claiming roofline-normalized geomean = 3.15 (>1, physically
impossible) and 3102 GB/s (>DRAM peak), neither blocked).

## 0. Goal, non-goals, principle

- **Goal**: rigorously enforce that a generated paper's **primary metric is
  scientifically correct** (not merely plausible), as a set of **necessary
  conditions that BLOCK finalize on violation** — without baking
  domain (roofline/HPC) knowledge into the harness.
- **Non-goals**: positively *certify* arbitrary-metric correctness (impossible);
  centrally recompute domain-specific rooflines in harness code.
- **Principle (verified buildable against current code)**:
  **harness owns ENFORCEMENT+EVALUATION (general); idea/rubric LLM DECLARES the
  semantics (domain); a deterministic concept→invariant registry AUDITS the
  declaration (general math).** The existing `claim_evidence_hard_gate`
  (`ari-core/ari/pipeline/claim_gate/`) already *is* this general substrate and
  hardcodes no roofline/GFLOP/cache formula — we extend it, we do not fight it.

## 1. Already done (Phase 0 — canonical metric NAME at every node)

- `fix-1`: `make_metric_spec` prefers idea-stage `primary_metric`
  (`evaluation_criteria.json`/`idea.json` via `ARI_CHECKPOINT_DIR`), seed regex
  fallback. (`ari-skill-evaluator/src/server.py` `_tool_make_metric_spec`,
  `_load_primary_metric_from_checkpoint`.)
- `fix-2`: node `survey` reuses the frozen VirSci snapshot corpus before live S2.
- `Option A`: ReAct tool order = `generate_ideas → make_metric_spec → survey →
  run_bash` (root only), so `make_metric_spec` runs AFTER the idea exists.
  (`workflow.py:_PREFERRED_ORDER`, `loop.py` root opening + idea-injection
  rechain.)

These unify the metric **name/spec**. They do NOT unify the **computation**, nor
check **correctness/invariants**. This plan adds that layer.

## 2. The DECLARATION: `metric_contract` (domain-supplied, registry-audited)

Extend the existing declaration channel (`make_metric_spec` output →
`evaluation_criteria.json`/`idea.json`) with a `metric_contract`. The idea/rubric
LLM emits it; the registry (§3.1) audits/augments it.

```json
{
  "primary_metric": "<prose, existing>",
  "higher_is_better": true,
  "metric_contract": {
    "key": "roofline_norm_throughput_gmean",
    "concept": "normalized",
    "formula": "geomean_over(K, achieved_gflops / ceiling)",
    "operands": {
      "achieved_gflops": "measurements.gflops_byK",
      "ceiling":         "measurements.roofline_ceiling_byK"
    },
    "invariants": [
      {"type":"bound","expr":"value","op":"<=","rhs":1.0},
      {"type":"order","lhs":"measurements.gflops_byK","op":"<=","rhs":"measurements.roofline_ceiling_byK"},
      {"type":"order","lhs":"measurements.model_sec","op":"<=","rhs":"measurements.sec"}
    ],
    "regime": {
      "select_ceiling": "if measurements.effective_bw > inputs.dram_peak_bw then measurements.cache_bw else inputs.dram_peak_bw"
    },
    "correctness_check": {
      "command": "./spmm_reachwalk --verify --M 256 --N 256 --K 64",
      "pass_predicate": "max_abs_err < 1e-4",
      "must_cover": "production_kernel"
    },
    "required_measured": ["ceiling","roofline_ceiling_byK","dram_peak_bw","cache_bw"]
  }
}
```

Mapping to the necessary conditions:
- **A correctness** ← `correctness_check` (run by harness, pass required).
- **B harness-owned compute** ← `formula` + `operands` (harness recomputes from
  resolved measurements; cannot use a node-injected scalar metric verbatim).
- **C regime** ← `regime.select_ceiling` is a DECLARED conditional (the single
  generality hazard: harness only *evaluates* it, never infers cache-residency).
- **D model self-consistency** ← `order` invariant `model_sec <= sec`.
- **E bound** ← `bound` invariant `value <= 1` (registry also injects this).
- provenance/no-placeholder ← `required_measured` (operands must have measurement
  provenance, §3.5).

## 3. New harness components (all domain-general)

### 3.1 `claim_gate/invariants.py` — concept→invariant registry (NEW, general math)
Deterministic table; pure universal mathematics, no domain thresholds:
```
normalized | efficiency | fraction_of_peak  -> value in (.., 1]
probability | fraction                       -> value in [0, 1]
percent                                       -> value in (.., 100]
speedup                                       -> value > 0
```
AUDIT role: union the registry's invariants with the declared ones; registry
*wins on omission* (if the LLM forgets `<=1` for a `normalized` metric, the
registry adds it). This closes "LLM-declared spec is itself wrong/incomplete."

### 3.2 `claim_gate/predicates.py` — declared bound/ordering/range checker (NEW)
Evaluate `{bound, order, range}` predicates over operands resolved by the
EXISTING `resolve.py:resolve_operand` (opaque `(node_id, metric_path)`), reusing
`numeric.within_tolerance` for equality. Emits findings:
`invariant_violation` (E), `model_inconsistent` (D), `regime_inconsistent` /
`achieved_exceeds_ceiling` (C). **No roofline knowledge — only declared predicates.**

### 3.3 `claim_gate/correctness.py` — declared correctness runner (NEW)
Runs `metric_contract.correctness_check.command`, evaluates `pass_predicate`
against stdout, requires pass; verifies `must_cover=production_kernel` (the check
exercised the same binary/symbols that produced the headline numbers — heuristic:
same compiled artifact / function names). Emits `correctness_failed`,
`correctness_uncovered`. **General: runs whatever the experiment declared.**

### 3.4 generalize `numeric.py` formula evaluation (NEW, careful sandbox)
Today `FORMULAS` is a closed set of 8 callables (`numeric.py:56-65`). Add a
declared-formula path: a **restricted-AST arithmetic evaluator** (whitelist
`+ - * / min max geomean reduce_over(K, …)`; **NO `eval`/`exec`**) so an
experiment can declare `formula` over named operands. Keep the named-formula
registry as the fast path; declared-formula is opt-in (B).

### 3.5 measured-vs-fabricated provenance (NEW — schema + check)
`results.json` measurements gain `_provenance: {source: microbench|benchmark|declared|constant, step}`.
The gate's B-check requires every `required_measured` operand to have
`source ∈ {microbench, benchmark}`; `declared`/`constant` → `placeholder_denominator`
finding. **This is what actually kills the `bw=400` placeholder denominator** that
caused 3.15 (current provenance only proves container-origin, not genuineness —
`resolve.py` resolves any number in `measurements{}`).

### 3.6 blocking wiring (REUSE `policy.py`)
Add to a new always-block tier (objective falsehoods, unlike subjective review):
`correctness_failed`, `correctness_uncovered`, `invariant_violation`,
`model_inconsistent`, `regime_inconsistent`, `achieved_exceeds_ceiling`,
`placeholder_denominator`. These block at `phase==final` regardless of warn/strict
(they are deterministically false). Subjective review stays warn/strict as today.

## 4. Node-side contract (what nodes MUST emit)
Enforced via the agent contract (idea-injection / post-survey hint already carry
the plan; add: *"if you report a metric with a `metric_contract`, you MUST emit
`required_measured` operands with measurement provenance and run the declared
`correctness_check`; otherwise the claim is blocked"*):
- run a **peak-FLOP/s** + **STREAM-bandwidth** microbench (kernel already has
  microbench scaffolding) → emit ceilings with `_provenance: microbench`;
- run the **reference correctness check on the production kernel** → emit residual;
- emit per-K `achieved` + `ceiling` so the harness recomputes the metric (B).
Fail-closed: a `metric_contract`-bearing claim lacking these is blocked, but
experiments with no `metric_contract` keep current (warn) behaviour
(backward-compat).

## 5. Synthesis reconciliation (transform + write_paper)
Ties in the earlier (i)/(ii) decisions (exclude bound-violators + log; block).
- `build_science_claims` (`ari-skill-transform/src/claims.py`): when a
  `metric_contract` exists, use `contract.key` as the canonical primary; STOP the
  `_autodetect_primary_metric` fallback. Attach the contract to `science_data`.
- **Invariant gate at configurations build**: per-node values violating the
  registry/declared invariants → mark `anomalous=true` and **EXCLUDE from the
  `configurations` handed to `write_paper`** (decision 2), logging to an
  `anomalies[]` list (transparency). → removes 3.15 *before* the LLM sees it.
- `write_paper` (`ari-skill-paper/src/server.py`): pass `metric_contract`;
  instruct the LLM to use only `contract.key` for the primary concept and never
  present same-concept variants side by side.
- `claim_gate` FINAL: §3.2 predicate checker re-verifies invariants on assembled
  paper claims; any violation / same-concept contradiction → **block** (backstop).

## 6. Phasing (cheap, high-value first; each phase is shippable)

- **Phase 1 — "catch the impossible" (cheapest, highest value, NO node changes) — DONE 2026-06-08**
  §3.1 registry + §3.6 blocking. Shipped:
  - `claim_gate/invariants.py` (NEW): domain-general concept→invariant registry
    (`normalized<=1`, `probability∈[0,1]`); name-classifier with exclusion list
    (`grad_norm`/percent/speedup not bounded); `scan_science_data()` over config
    result metrics; declared-bound path for future `metric_contract`.
  - `claim_gate/gate.py`: invariant scan pass → `invariant_violation` errors;
    `should_block` now also fires on `always_block_on` types at FINAL regardless
    of warn/strict; `invariant_violation_count` metric.
  - `claim_gate/policy.py`: `blocking.always_block_on=["invariant_violation"]` +
    `always_block_on()` accessor.
  - Tests `tests/test_claim_gate_invariants.py` (27, multi-domain generality).
  VERIFIED on the real CSR checkpoint: `scan_science_data` flags 3 violations
  (`geo_mean_norm_roofline_throughput`=3.15 etc.); `run_hard_gate(phase=final,
  mode=warn)` → `should_block=True` (draft → False). 166 passed / 0 fail, no
  regression. E-check catches the 3.15 (`>1`); D (`model_sec<=sec`) deferred to
  Phase 2 as a DECLARED order invariant (not a universal one — a generic model is
  not always a lower bound; only valid when the contract declares it).
- **Phase 2/3/4 HARNESS — DONE 2026-06-08** (declared-contract enforcement, all
  domain-general; no producer yet so dormant on legacy runs):
  - `claim_gate/formula_eval.py` (NEW): safe restricted-AST evaluator (no
    eval/exec) for declared expressions — arithmetic, lists/elementwise,
    reducers (geomean/mean/min/max), comparisons, `A if c else B`. Powers
    invariants, regime conditional, correctness predicate, owned-recompute.
  - `claim_gate/contract.py` (NEW): `check_contract()` enforces a declared
    `metric_contract` per config — A correctness (`correctness_failed`/
    `correctness_uncovered`), B provenance (`placeholder_denominator`: a
    `required_measured` ceiling must be microbench/benchmark, not constant) +
    owned recompute (`recompute_mismatch`), C regime (`ceiling_select` declared
    conditional binds the ceiling; harness never infers cache/DRAM), D/E declared
    invariants (`invariant_violation`).
  - `gate.py`: calls `contract.check_contract`; `contract_violation_count`.
  - `policy.py`: `always_block_on` += correctness_failed/correctness_uncovered/
    placeholder_denominator/recompute_mismatch.
  - Synthesis (§5): `ari-skill-transform/src/server.py` annotates
    `_anomalies` + per-config `_anomalous_metrics` via the SAME public registry
    (`ari.public.claim_gate.scan_science_data`); `ari-skill-paper/src/server.py`
    tells the writer to never quote `_anomalous_metrics`.
  - Producer scaffold: `ari-skill-evaluator/src/server.py make_metric_spec` emits
    a `metric_contract` (key/concept/invariants from the public registry) for the
    agent to complete; `ari.public.claim_gate` re-exports the registry (req-09).
  - Tests: `tests/test_claim_gate_contract.py` (formula_eval safety + general
    eval; contract correctness/provenance/regime/recompute; gate blocking).
- **Phase 4 — REMAINING (needs a real compute-node run, per memory rule)**:
  the NODE-SIDE execution that fills the scaffold — the agent must run a
  reference correctness check + peak/STREAM microbenches and emit the residual +
  measured ceilings with `_provenance`, and complete the `metric_contract`
  (formula/correctness/required_measured). Until then the declared checks are
  armed but dormant; the universal invariant (Phase 1) already blocks the 3.15.
  Validate end-to-end with a live BFTS run asserting the gate blocks an
  uncovered-correctness / placeholder-denominator paper.

## 7. Generality guardrails (PR review checklist)
- No `roofline`/`GFLOP`/`cache`/`DRAM`/`bandwidth` string in harness CODE paths
  (only in: declarations, the general-math registry, test fixtures). Existing
  soft leaks (`dynamic_axes._HPC_PLAN_KEYWORD_AXES`, `latex._PERF_UNIT_RE`) are in
  the LLM-judge/prose-parser layers, NOT the blocking gate — do not add to them.
- Every domain value (formula, ceiling, regime rule, correctness command) is
  DECLARED in `metric_contract`, never inferred by the harness.
- **Item C**: harness only EVALUATES the declared conditional; if you find
  yourself writing `if effective_bw > dram_peak` in harness code, STOP — it must
  come from `regime.select_ceiling`.
- Registry holds only universal invariants (normalized≤1, prob∈[0,1]); no domain
  thresholds.

## 8. Testing / validation
- Unit: registry, predicate checker, restricted-AST formula evaluator,
  correctness runner — with fixtures across **ML (accuracy∈[0,1]) + HPC (roofline
  ≤1) + theory (runtime ordering)** metric shapes to PROVE generality.
- Integration (regression on real data): re-run the gate on checkpoint
  `20260608153628_...` and assert it now BLOCKS on `model_inconsistent`/
  `invariant_violation` for the 3.15 (Phase 1) and `correctness_uncovered`
  (Phase 2).
- Real-env (per memory `feedback_validate_on_real_env_not_fakes`): a live BFTS run
  on a compute node to confirm node-side microbench + correctness emission. Do
  NOT treat unit-green as done.

## 9. Risks / open issues
- Formula sandbox: must be restricted-AST, never `eval`/`exec`.
- `must_cover=production_kernel` (A) auto-verification is non-trivial (proving the
  correctness check exercised the headline code path) — start with a declared
  assertion + same-artifact heuristic.
- Node burden: microbench + correctness add runtime; gate fails-closed only for
  `metric_contract`-bearing claims.
- The two formula registries (`numeric.py` ↔ `claims.py`) are kept in sync by a
  docstring contract today; the declared-formula generalization should collapse
  the duplication.
