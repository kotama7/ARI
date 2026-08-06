# Task 13: Evaluation and Ablation

> **Status**: planned · **Depends on**: 00, 01, 02, 03, 04, 05, 06, 07, 08, 09, 10, 11, 12 · **This is a temporary task plan** — see [INDEX.md](INDEX.md). It will be deleted once its deletion criteria are met.

## 1. Purpose

ARI-RQGM adds a costly institutional layer (adversary/defender/judge, governance audits,
prompt retirement, selective erasure, prompt/meta evolution) on top of BFTS. This task designs
the machinery to answer, with numbers rather than intuition:

1. **Does each RQGM layer earn its cost?** — a ten-condition ablation ladder (B0–B9) that
   turns layers on one at a time and measures the marginal effect of each.
2. **Does RQGM actually catch failures?** — ten deterministic failure injections with known
   ground truth, measuring detection, false accepts/rejects, and detection latency.
3. **What does it cost?** — token, dollar, and wall-clock accounting per condition, reusing
   ARI's existing `cost_tracker` infrastructure.

Nothing in this task changes runtime behavior. It produces an evaluation harness, benchmark
configs, injection fixtures, and a deterministic metric computer that reads only checkpoint
artifacts.

## 2. Scope

- Definition of the **ten ablation conditions B0–B9** as named config presets, each expanding
  to a concrete `ari.mode` + `rqgm.*`/`proposal_router.*` feature-flag set (flags supplied by
  Tasks 01–14, under their own names).
- Definition of **ten failure injections**, each with a deterministic injection mechanism, an
  expected detection channel, and a ground-truth label.
- Definition of **thirteen metrics**, each with a formula and a concrete data source in
  existing or Task-02–12 checkpoint artifacts.
- An **evaluation harness**: `scripts/rqgm_eval/` (run orchestration, condition expansion,
  injection application) plus a pure, LLM-free metric computer inside ari-core
  (`ari/rqgm/evaluation/`, internal — not `ari.public.*`).
- **Comparison policies**: simple_bfts vs ari_rqgm; VirSci on vs off; budget-parity rules.
- A three-tier test strategy (fixture-level unit tests, scripted-component smoke runs,
  full LLM ablation runs) so that CI covers Tiers 1–2 without LLM cost.
- Results destination layout (`workspace/rqgm_eval/<eval_id>/`) and report schema.

## 3. Non-goals

- No implementation in this task plan (design only).
- No new CLI command or `ari.public.*` symbol (zero contract-snapshot churn; the harness is a
  standalone script, per the "config-only activation for v1" decision in Task 01).
- No change to BFTS behavior, the paper pipeline, or the claim gate; the harness only *reads*
  their outputs.
- No RQGM-verbatim reproduction of the paper's Beta-posterior/BB_ε machinery: ARI's detection
  metrics use binary ground truth **by construction** (injected = bad, control = good), and
  scalar science metrics stay scalar. This resolves the "binarize or redesign?" open question
  from the investigation: we do not binarize ARI's rubric scores.
- No curation of an external ground-truth corpus (e.g. HPC-PaperBench alignment is an optional
  future tie-in, not a dependency of this task).
- No per-epoch versioning of paper-pipeline outputs (`full_paper.tex` overwrite-in-place stays;
  each evaluated condition runs in a **fresh checkpoint**, which sidesteps `skip_if_exists`
  cross-condition leakage).

## 4. Existing ARI touchpoints

All paths repo-relative; verified to exist on branch `RQGM`.

**Signals and artifacts the metric computer reads (existing today):**

- `ari-core/ari/checkpoint.py` — `tree.json` / `nodes_tree.json` / `results.json` triple
  (node status, `metrics`, `has_real_data`); byte-fixed formats are a read-only contract.
- `ari-core/ari/orchestrator/bfts.py` — sterile gate clamp (`metrics.get("_sterile") is True`
  retires the node, ~line 499; the clamp is authoritative and metric 1 must respect it) and
  the `_scientific_score`-based utility policy. The reserved keys `_scientific_score` /
  `_axis_scores` are written by `ari-core/ari/evaluator/llm_evaluator.py` and
  mirrored/consumed in `ari-core/ari/cli/bfts_loop.py` and
  `ari-core/ari/orchestrator/node_report/builder.py`.
- `ari-core/ari/orchestrator/node_report/builder.py` — per-node `node_report.json`
  (`SCHEMA_VERSION=1`, sha256 file diffs) → executability evidence for metric 2.
- `ari-core/ari/cost_tracker.py` — global litellm callback → `cost_trace.jsonl` (+
  `cost_summary.json`); per-epoch attribution rides Task 12's additive `epoch` field on
  `CallRecord`. Source for metrics 11–12.
- `ari-core/ari/pipeline/claim_gate/gate.py` — `run_hard_gate(...)` writes
  `evaluation/claim_evidence_hard_gate_{draft,final}.json` with a ready-made `metrics` block
  (`execution_grounded_claim_rate`, `numeric_claim_reproducible_rate`, `numeric_coverage_rate`,
  violation counts). Deterministic detector reused for injections 1–2; `run_hard_gate(write=False)`
  lets the harness re-check fixtures without touching disk.
- `ari-core/ari/pipeline/claim_gate/policy.py` — `{ckpt}/claim_gate_policy.json` merge; the
  harness never relaxes `always_block_on`.
- `ari-core/ari/orchestrator/lineage_decision.py` + `ari-core/ari/cli/lineage.py` —
  `lineage_decisions.jsonl` append-only audit precedent; source for pivot/termination events.
- `ari-core/ari/prompts/_provenance.py` — `prompt_trace.jsonl` / `prompt_versions.json`
  (`hash12` scheme); links records to `prompt_hash` for metrics 8–9.
- `ari-skill-evaluator/src/server.py` — `claim_evidence_hard_gate` MCP wrapper (error-only-dict
  blocking convention) and `evidence_grounded_semantic_review` (`score_delta`).

**Run-driving machinery the harness invokes (existing today):**

- `ari-core/ari/cli/run.py` (`ari run`, `_resolve_cfg`, `--config` precedence) — the harness
  launches each condition via `ari run --config <generated workflow.yaml>` in a fresh
  `ARI_CHECKPOINT_DIR`; no CLI change needed.
- `ari-core/ari/core.py:build_runtime` — conditional wiring point where Task 01's mode switch
  and Task 03's ProposalRouter live; the harness only sets config, never patches code.
- `ari-core/ari/cli/bfts_loop.py:_run_loop` — epoch boundary (Task 05); all per-node hooks are
  best-effort try/except, which the injection smoke runs rely on (a scripted double failing
  must degrade, not crash).
- `ari-core/ari/config/__init__.py` — `ARIConfig` + `load_config` field filtering; ablation
  flags must be typed fields (Task 01's `RQGMConfig`) or they are silently dropped.
- `ari-core/ari/paths.py:PathManager.META_FILES` — every new eval filename
  (`rqgm_eval_metrics.json`, `rqgm_injection_provenance.json`) must be registered here.
- `ari-core/ari/configs/defaults.yaml` — home for numeric eval defaults (seed count, budgets).

**Test/CI infrastructure to plug into:**

- `pytest.ini` + `scripts/run_all_tests.sh` — Tier-1/2 tests live in `ari-core/tests/`
  (CI-hard via `.github/workflows/refactor-guards.yml`); `scripts/tests/` is NOT run by any
  workflow today, so nothing load-bearing goes there.
- `ari-core/tests/test_prompt_snapshots.py` / `test_prompt_extraction.py` — the re-blessable
  byte-golden and hand-pinned-hash patterns reused for injection fixtures.
- `ari-core/tests/test_contract_snapshots.py` + `scripts/snapshot_contracts.py` — the harness
  stays off all four contract surfaces (no public symbol, no CLI command, no MCP tool).
- `scripts/quality/_common.py` — JSON envelope convention if an eval checker is ever promoted
  to CI; `scripts/generate_quality_report.py` registration with `required: false`.
- `ari-core/tests/README.md` — readme-sync gate: every new test file needs a Contents row.

**RQGM artifacts from upstream tasks (planned, consumed here):** `epoch_state.json`,
`rqgm_audit.jsonl` (Task 02); ProposalRecord store + `ProposalSummaryView` (Task 03);
ConstitutionalKernel violation events (Task 04); `GovernanceReport` (Task 05);
`ValidatedAttackRecord` / AdversarialReplayPool (Task 06); PromptSpec lifecycle records
(Task 07); `CleanRoomGenerationRequest` (Task 08); `EpochTransition` / `RetirementEvent`
(Task 09); `SelectiveErasureEvent` / `FrontierRebuildEvent` + `stale` / `valid_for_frontier`
flags (Task 10); meta-tier `ComponentRegistry` entries (Task 11); epoch-tagged cost records
and budget config (Task 12).

## 5. Proposed design

### 5.1 Ablation conditions B0–B9

Each condition is a named preset in `scripts/rqgm_eval/ablation_matrix.yaml`. The harness
expands a preset into a concrete workflow.yaml overlay (written into the fresh run's
checkpoint dir, honoring the checkpoint-copy-first precedent). Presets only set `ari.mode`,
`rqgm.enabled`, and the per-subsystem feature flags defined by Tasks 01–14; Task 13 does not
invent new runtime switches, it *requires* that those tasks expose these flags.

| Cond | Mode | Feature set (additive down the ladder) |
|---|---|---|
| **B0** | `simple_bfts` | Current ARI behavior verbatim (`rqgm.enabled: false`). The control. Uses today's idea-skill path (after Task 03 restores the `generate_ideas` MCP registration regression). |
| **B1** | `simple_bfts` | B0 + ProposalRecord **archival only** (`proposal_router.record_only: true` — Task 03 §6.5's record-only flag, the one key of that block explicitly honored in `simple_bfts` for this rung): records are written, nothing consumes them. Validates that the record layer is behavior-neutral. |
| **B2** | `ari_rqgm` (governance features off) | ProposalRouter enabled **with** VirSciAdapter (`proposal_router.generators.virsci.enabled: true`, `mode: event_triggered`, `max_calls_per_epoch: 2`). No adversary, no governance. |
| **B3** | `ari_rqgm` (governance features off) | ProposalRouter **without** VirSci (`virsci.enabled: false`); CheapGenerator / MutationGenerator / AttackDrivenGenerator / PriorArtDifferentiationGenerator only. |
| **B4** | `ari_rqgm` | B3 + adversary/defender/judge loop (`rqgm.adversarial.enabled: true`, Task 06's flag); ValidatedAttackRecords apply utility penalties; replay pool accumulates. |
| **B5** | `ari_rqgm` | B4 + GovernanceOrchestrator (`rqgm.governance.enabled: true` †): `audit_epoch` runs at boundaries and emits GovernanceReports; RegistryTransitionEngine limited to warning/probation (no retirement). |
| **B6** | `ari_rqgm` | B5 + prompt retirement + selective erasure (`rqgm.frontier_repair.enabled: true`, Task 10's flag; Task 09's transition table has no separate switch — its `rqgm.transition.*` keys are thresholds only): full transition table, FrontierRepairEngine, stale-record exclusion. On retirement without evolution, the role falls back to its shipped baseline PromptSpec (always active-eligible; a design point Task 09 must honor). |
| **B7** | `ari_rqgm` | B6 + prompt evolution incl. clean-room regeneration (`rqgm.prompt_evolution.enabled: true`, Task 07's flag): PromptMutator candidates, replay/shadow evaluation, promotion pipeline, CleanRoomPromptGenerator on retirement. |
| **B8** | `ari_rqgm` | B7 + meta-agent evolution (`rqgm.meta_evolution.enabled: true`, Task 11's flag): PromptMutator / CleanRoomPromptGenerator / ReplayCaseSelector are themselves evolution targets. Pins `rqgm.utility_evolution.enabled: false` (Task 14's flag, which defaults **true**): the utility policy is frozen for the whole run, i.e. the pre-14 system exactly (Task 14 §8.2) — the old I-11 regime, kept as the control the B9 contrast is measured against. |
| **B9** | `ari_rqgm` (full) | B8 + governed utility evolution (`rqgm.utility_evolution.enabled: true`, Task 14's flag): PolicyMutator proposes utility-policy candidates, adoption rewrites the score at epoch boundaries through the governed path, and nodes scored under a retired policy are invalidated (never re-weighted). Equals the full `ari_rqgm` mode. |

† **Governance flag gap (requirement on Task 05).** Task 05 §6.5 defines no governance enable
flag: its `rqgm.governance` block carries tuning keys only (`default_level`,
`full_governance_only_on_top_k`, …) and `audit_epoch` gates on `ari.mode == ari_rqgm` +
`rqgm.enabled` alone. Both the B5 rung and keeping governance *off* in B2–B4 (which already
run in `ari_rqgm` mode) therefore require Task 05 to add `rqgm.governance.enabled`
(default `false`). Per the preamble above, this is a flag Task 13 requires the owning task to
expose, not one it defines; the cross-task dependency is recorded in INDEX.md (see §10).

The ladder is strictly additive from B3 upward; the B2/B3 pair forks only on VirSci, giving
the VirSci-marginal measurement at matched budgets. The marginal value of each layer is the
paired difference: adversarial = B4−B3, governance = B5−B4, retirement/erasure = B6−B5,
evolution = B7−B6, meta = B8−B7, governed utility evolution = B9−B8. The last pair is the only
empirical defense of P1 ("at epoch boundaries the entire score is rewritten"): B8 holds the score
fixed for the run, B9 rewrites it under governance, and nothing else differs.

### 5.2 Comparison policies

**simple_bfts vs ari_rqgm (primary).** B0 vs B9 (and each rung) on the same experiment set,
same models (`ARI_MODEL_*` pinned in the eval config), same node budget (`bfts.max_total_nodes`,
`max_depth` identical across conditions), N seeds per condition (default 3, from
`ari/configs/defaults.yaml`). Fairness is by **node budget**, with token/dollar/wall-clock
reported so RQGM overhead is visible rather than hidden. An optional secondary cost-matched
comparison (B0 granted extra nodes until token spend matches B9) is defined but not required
for completion. Each run gets a fresh checkpoint; no resume, no `skip_if_exists` reuse across
conditions (guarantees cross-condition comparability of pipeline outputs).

**VirSci on/off (secondary).** B2 vs B3 as the primary VirSci contrast; optionally B9±VirSci.
Both must pass on environments without VirSci installed when `virsci.enabled: false`
(Task 03's guarantee); the harness asserts no VirSci prompts appear in `prompt_trace.jsonl`
and no VirSci transcript files exist in the checkpoint for the off condition.

**Regression guard.** B0 doubles as the compatibility check: a B0 smoke run with RQGM code
present must produce the same artifact contract (file set, tree.json schema, reserved metric
keys) as the pre-RQGM baseline. This composes with, not replaces, Task 01's mode smoke tests.

### 5.3 Failure injections (all ten)

Two deterministic mechanisms, no LLM in either (P2):

- **(F) Fixture injection** — a crafted checkpoint fragment (tree.json + science_data.json +
  paper tex + RQGM records) written under `ari-core/tests/fixtures/rqgm_eval/<injection_id>/`;
  detectors are run directly against it. CI-runnable.
- **(S) Scripted-component injection** — a deterministic double (no LLM) substituted for one
  role via config (`rqgm.eval.scripted_components: {role: double_name}`), registered through
  the `ari/_factory.py:BaseRegistry` pattern; the run proceeds with the faulty component and
  detection is measured end-to-end. Smoke-tier.

Any run with injections active writes `rqgm_injection_provenance.json` (the
`bfts_web_provenance.json` precedent) so an injected run can never be mistaken for a real one.
Injection case ids use the `eval_*` namespace, disjoint by construction from governance's
`adv_*` replay cases and `anchor_*` cases — the eval set is held out from what governance
trains/audits on, enforced by a harness check.

| # | Injection | Mech | Payload (deterministic) | Expected detection channel | Min cond |
|---|---|---|---|---|---|
| 1 | **Metric gaming** | F | `science_data.json` with speedup computed against a weakened baseline (mismatched `env_signature` between baseline and proposed configs) | Existing: `run_hard_gate` `environment_mismatch`/`numeric_mismatch`. RQGM: MetricGamingAdversary → ValidatedAttackRecord | B0 (gate) / B4 (adversary) |
| 2 | **Overclaim** | F | `full_paper.tex` asserting numbers with no `% CLAIM` anchor and no evidence node | Existing: gate `missing_evidence`/`uncovered_numeric`; semantic review. RQGM: OverclaimAdversary | B0 / B4 |
| 3 | **Hallucinated prior art** | F | ProposalRecord with fabricated citation entries (ids absent from the frozen S2 snapshot / `related_refs.json`) | PriorArtAdversary; PriorArtDifferentiationGenerator cross-check | B4 |
| 4 | **Adversary overreach** | S | `always_attack` adversary double: attacks every artifact with severity high | Judge marks attacks invalid → validated-attack precision collapses; GovernanceOrchestrator reliability assessment flags the adversary | B4 (attack loop) / B5 (sanction) |
| 5 | **Judge bias** | S | `always_validate` (and dually `never_validate`) judge double | GovernanceSelfAudit / AnchorBoard: judge disagrees with anchor-case expected verdicts beyond threshold | B5 |
| 6 | **Bad generator** | S | Generator double emitting schema-violating or non-executable proposals (missing required ProposalRecord fields; plans referencing nonexistent tools) | ConstitutionalKernel schema check (immediate); `proposal_to_executable_rate` collapse per component → governance demotion | B2 (schema) / B5 (demotion) |
| 7 | **Contaminated prompt** | F | PromptCandidate whose spec violates constitutional constraints (e.g. instructs "always override fixed verifier failures") or embeds retired prompt text | Task 07 static + constitutional validation rejects the candidate before shadow; kernel logs violation | B6 (registry validation) / B7 (full lifecycle) |
| 8 | **Bad prompt mutator** | S | Mutator double emitting candidates that fail schema dry-run and replay | Candidates rejected at validation; never activated (invariant 15); MetaMonitor sanctions the mutator | B7 / B8 (sanction) |
| 9 | **Clean-room violation** | F | `CleanRoomGenerationRequest` whose `allowed_inputs` payload includes `retired_prompt_text` | ConstitutionalKernel access/capability check blocks (invariant 14); contamination-free check (Task 08) fails | B7 |
| 10 | **Stale record leakage** | F | Frontier state where a record with a retired `prompt_hash` has `stale=false`, `valid_for_frontier=true` | `ConstitutionalKernel.validate_selective_erasure` / StaleRecordChecker flags; FrontierRepairEngine repair diff | B6 |

Every injection spec declares `expected_detection` (channel, record type, max latency in
epochs) so detection latency is measurable, and a `ground_truth_label` so false-accept/reject
metrics are computable without human judgment.

### 5.4 Metrics (all thirteen)

Computed post-hoc by a pure function over the checkpoint (`compute_metric_report`), no LLM,
no network, no wall-clock in any derived value except metric 13 (which is metadata, never
hashed). Applicability: metrics 1–3, 12–13 in all conditions; 4–6 in injection runs from the
listed min condition; 7–8 need B5+/B6+; 9–10 need B6+; 11 needs Task 12's epoch cost tags.

| # | Metric | Formula | Data source |
|---|---|---|---|
| 1 | **Best valid scientific score** | max `_scientific_score` over nodes with `status=SUCCESS`, `_sterile≠true`, and (B6+) `stale=false ∧ valid_for_frontier=true` | `tree.json` metrics + Task 10 flags |
| 2 | **proposal_to_executable_rate** | # ProposalRecords whose derived node produced a non-sterile `node_report.json` (nonempty file diff) ÷ # ProposalRecords routed to BFTS | ProposalRecord store (Task 03) + `node_report.json` + `_sterile` |
| 3 | **downstream_success_rate** | # proposal-derived nodes with SUCCESS ∧ `has_real_data` ÷ # executed proposal-derived nodes; secondary: fraction of runs whose `claim_evidence_hard_gate_final` passes | `tree.json`; `evaluation/claim_evidence_hard_gate_final.json` |
| 4 | **False accept rate** | # injected-bad artifacts that end up accepted (in final frontier, or claim marked `supported`, or in the finalized paper) ÷ # injected-bad artifacts | injection specs (ground truth) × frontier/gate/claim records |
| 5 | **False reject rate** | # control (clean) artifacts wrongly rejected (validated attack against them, staled, or gate-blocked) ÷ # control artifacts | control fixture set × ValidatedAttackRecords, erasure events, gate reports |
| 6 | **Validated attack precision** | # ValidatedAttackRecords whose target is labeled-bad ÷ # ValidatedAttackRecords (injection runs) | Task 06 records × injection labels |
| 7 | **False impeachment rate** | # upheld impeachments against correctly-behaving components (control runs, no injected component fault) ÷ # upheld impeachments | GovernanceReport / ImpeachmentOutcome in `rqgm_audit.jsonl` |
| 8 | **Prompt retirement precision** | # retirements of labeled-bad prompts ÷ # RetirementEvents (injection runs) | Task 09 RetirementEvents × injection labels |
| 9 | **Frontier contamination rate** | # frontier records whose `prompt_hash` ∈ retired set ÷ frontier size, measured after each epoch transition (target 0 in B6+) | frontier snapshot + PromptRegistry retired set; recomputed via the kernel check |
| 10 | **Recovery after selective erasure** | # nodes (and epochs) from a retirement-triggered erasure until best valid scientific score ≥ pre-erasure best. Reported **per weight regime**, partitioned on `EpochState.utility_policy["utility_policy_hash"]`: a series is only comparable within one regime, and a governed utility rewrite (Task 14) starts a new one rather than translating the old (§10) | epoch-tagged score series from `tree.json` + `epoch_state.json` (incl. `utility_policy.utility_policy_hash`) + SelectiveErasureEvent timestamps (ordinal, not wall-clock) |
| 11 | **Cost per detected failure** | Σ USD of governance-attributed calls (phase/skill labels + Task 12 `epoch` field) ÷ # true-positive detections | `cost_trace.jsonl` / `cost_summary.json` × detection records |
| 12 | **Token cost** | total and per-phase prompt+completion tokens per run; per-layer delta across the B-ladder | `cost_trace.jsonl` |
| 13 | **Wall-clock cost** | run duration (start/end from `meta.json` + `ari.log`); reported as environment-qualified metadata (host recorded, value never hashed — P2) | `meta.json`, `ari.log` |

### 5.5 Harness architecture

```
scripts/rqgm_eval/
  run_ablation.py          # orchestrator: expand condition -> write workflow.yaml overlay
                           #   -> `ari run --config ...` in fresh ARI_CHECKPOINT_DIR -> collect
  ablation_matrix.yaml     # B0..B9 preset -> mode + feature flags + budgets + seeds
  failure_injections.yaml  # the 10 injection specs (id, mech, payload ref, expected_detection)
  experiments/             # 2-3 small benchmark experiment.md fixtures
ari-core/ari/rqgm/evaluation/          # internal package (NOT ari.public.*)
  metrics.py               # compute_metric_report(checkpoint_dir, *, injections=None) -> dict
  injection.py             # apply_injection(spec, checkpoint_dir); fixture writers
  doubles.py               # scripted component doubles, BaseRegistry-registered
ari-core/tests/fixtures/rqgm_eval/     # injection + control fixture checkpoints
workspace/rqgm_eval/<eval_id>/         # results destination (per-condition checkpoints,
  ablation_report.json, ablation_report.md)
```

Split rationale: metric computation and injection logic live in ari-core so the CI-hard
ari-core suite covers them (nothing in `scripts/tests/` runs in CI today); the run
orchestrator is a thin script because it spawns processes and has no unit-testable logic
worth CI cost. `run_ablation.py` uses argparse, not the `ari` Typer app — zero CLI contract
churn.

**Three evaluation tiers:**

- **Tier 1 (CI, pure fixtures, no LLM):** metric functions on golden fixture checkpoints;
  kernel detection of injections 7/9/10; claim-gate detection of injections 1/2; condition
  preset expansion (each B0–B9 resolves to the exact expected flag set; B0 expansion equals
  the shipped default config).
- **Tier 2 (CI-optional smoke, scripted doubles, stub LLM):** short runs (≤5 nodes) with
  doubles for injections 4/5/6/8; asserts detection records appear within declared latency
  and that a failing double degrades (best-effort hook policy) rather than crashing the run.
- **Tier 3 (manual/experiment-time, real LLMs):** the actual B0–B9 × seeds ablation; produces
  `ablation_report.{json,md}`. Never in CI.

## 6. Data structures / schema changes

All new files registered in `PathManager.META_FILES` (+ `_TRACE_FILES` for JSONL) and, where
JSON-report-adjacent, in `node_report/builder.py::_INTERNAL_JSON_NAMES`.

**`ablation_matrix.yaml` (harness config, sketch):**

```yaml
eval_defaults:
  seeds: [11, 12, 13]
  bfts: {max_total_nodes: 20, max_depth: 4}
  models: {coding: "...", bfts: "...", eval: "..."}   # pinned per eval campaign
conditions:   # overlay keys are the owning tasks' own config paths (§5.1); `inherits`
              # is harness-side deep-merge sugar making the additive ladder explicit
  B0: {mode: simple_bfts, rqgm: {enabled: false}}
  B1: {inherits: B0, proposal_router: {record_only: true}}            # Task 03 §6.5
  B2: {mode: ari_rqgm, rqgm: {enabled: true},                         # governance off (§5.1 †)
       proposal_router: {generators: {virsci: {enabled: true, mode: event_triggered,
                                               max_calls_per_epoch: 2}}}}
  B3: {mode: ari_rqgm, rqgm: {enabled: true},
       proposal_router: {generators: {virsci: {enabled: false}}}}
  B4: {inherits: B3, rqgm: {adversarial: {enabled: true}}}            # Task 06
  B5: {inherits: B4, rqgm: {governance: {enabled: true}}}             # Task 05 (§5.1 † — flag to be added)
  B6: {inherits: B5, rqgm: {frontier_repair: {enabled: true}}}        # Task 10
  B7: {inherits: B6, rqgm: {prompt_evolution: {enabled: true}}}       # Task 07
  B8: {inherits: B7, rqgm: {meta_evolution: {enabled: true},          # Task 11
                            utility_evolution: {enabled: false}}}     # Task 14 (default true)
  B9: {inherits: B8, rqgm: {utility_evolution: {enabled: true}}}      # Task 14
```

**`FailureInjectionSpec` (one entry in `failure_injections.yaml`):**

```yaml
- injection_id: eval_inj_001_metric_gaming
  mechanism: fixture                # fixture | scripted_component
  target_role: null                 # role name when scripted_component
  payload_ref: fixtures/rqgm_eval/metric_gaming/
  ground_truth_label: bad
  expected_detection:
    channels: [claim_gate.environment_mismatch, adversary.metric_gaming]
    record_types: [ValidatedAttackRecord]
    max_latency_epochs: 1
  min_condition: B4                 # earliest rung where the RQGM channel exists
```

**`rqgm_eval_metrics.json` (per run, written by `compute_metric_report`):** the 13 metrics,
each `{value, numerator, denominator, evidence_refs: [record ids / relative paths],
applicable: bool}`, plus `{condition_id, run_id, seed, config_digest, injection_ids,
computed_by_version}`. Deterministic key order; no timestamps inside hashed content.

**`rqgm_injection_provenance.json` (per injected run):** `{injection_ids, specs_digest,
harness_version}` — durable marker that the trajectory is synthetic.

**`ablation_report.json` (per eval campaign):** condition × metric matrix with per-seed
values, medians, and paired deltas vs B0 (and B4−B3, B5−B4, …, B8−B7, B2−B3); companion
`ablation_report.md` rendered deterministically from the JSON.

## 7. API / class changes

All internal; nothing enters `ari.public.*`, the CLI tree, or the MCP tool namespace.

```python
# ari-core/ari/rqgm/evaluation/metrics.py
def compute_metric_report(checkpoint_dir: Path, *, injections: list[dict] | None = None,
                          condition_id: str = "", seed: int | None = None) -> dict: ...
# one pure helper per metric family, individually unit-testable:
def best_valid_scientific_score(tree: dict, stale_index: dict | None) -> dict: ...
def proposal_to_executable_rate(records: list[dict], node_reports: dict) -> dict: ...
def detection_rates(detections: list[dict], injections: list[dict],
                    controls: list[dict]) -> dict: ...   # metrics 4-8
def frontier_contamination(frontier: list[dict], retired_hashes: set[str]) -> dict: ...
def cost_metrics(cost_trace: list[dict], detections: list[dict]) -> dict: ...  # 11-12

# ari-core/ari/rqgm/evaluation/injection.py
def apply_injection(spec: dict, checkpoint_dir: Path) -> None: ...  # deterministic, idempotent
def write_injection_provenance(checkpoint_dir: Path, specs: list[dict]) -> None: ...

# ari-core/ari/rqgm/evaluation/doubles.py
EVAL_DOUBLE_REGISTRY = BaseRegistry("rqgm.eval_double")   # ari/_factory.py pattern
# registered: adversary/always_attack, judge/always_validate, judge/never_validate,
#             generator/schema_violating, prompt_mutator/degenerate
# Doubles are registered in ComponentRegistry with tier "eval_double" and are refused
# outside rqgm.eval.enabled=true (a ConstitutionalKernel capability check).

# scripts/rqgm_eval/run_ablation.py  (argparse)
#   --matrix ablation_matrix.yaml --conditions B0,B3,B9 --eval-id <id>
#   --inject failure_injections.yaml[:ids] --dry-run (expand configs only, no runs)
```

Config additions (typed fields on Task 01's `RQGMConfig`, all default-off):
`rqgm.eval.enabled: false`, `rqgm.eval.scripted_components: {}`,
`rqgm.eval.injection_specs: []`. `load_config`'s field filtering makes untyped keys silently
vanish, so these MUST be model fields, not raw-YAML reads.

## 8. Migration / compatibility

- **Nothing on by default.** `rqgm.eval.*` defaults off; the harness only affects runs it
  launches itself in fresh checkpoints. `simple_bfts` behavior is untouched; B0 is literally
  the shipped default config.
- **No contract-surface change.** No new CLI command/flag, no `ari.public` symbol, no MCP
  tool ⇒ no golden regeneration in `ari-core/tests/fixtures/contracts/`.
- **VirSci optionality respected.** B3–B9 run with `virsci.enabled: false`; Tier-1/2 tests
  pass on machines without VirSci installed. Only B2 (and optional B9+VirSci) needs it, and
  those are Tier-3 manual runs.
- **Doubles cannot leak into production.** The `eval_double` tier is rejected by the kernel's
  capability check unless `rqgm.eval.enabled=true`, and any injected run carries
  `rqgm_injection_provenance.json`.
- **Checkpoint hygiene.** New filenames registered in `META_FILES` so they are never copied
  into node work dirs or surfaced as experiment artifacts; JSONL additions follow the
  append-only, absence-tolerant, never-raise conventions of `record_prompt_use`.
- **Resume-safe.** The harness never resumes across conditions; metric computation reads only
  persisted artifacts, so it works on any completed (or interrupted-and-resumed) checkpoint.

## 9. Tests

Tier-1 tests (all in `ari-core/tests/`, CI-hard via the full-suite run; README Contents rows
added; no litellm/network imports — mirror `test_recorder_is_offline_no_llm_or_network_imports`):

- `test_rqgm_eval_metrics.py` — each metric function against hand-built fixtures with known
  answers; absence-tolerance (missing RQGM records ⇒ `applicable: false`, never an exception);
  determinism (two computations byte-identical); sterile/stale exclusion in metric 1.
- `test_rqgm_eval_conditions.py` — preset expansion: each B0–B9 yields exactly the expected
  mode + flag set; B0 expansion == default config; ladder monotonicity (each rung's feature
  set ⊇ previous, B2/B3 fork excepted); all four mode×VirSci combinations expressible.
- `test_rqgm_eval_injection.py` — `apply_injection` is deterministic (same spec ⇒ byte-identical
  fixture) and idempotent; provenance file written; `eval_*` namespace disjointness check;
  META_FILES registration asserted (pattern of `test_new_filenames_are_meta_files`).
- `test_rqgm_eval_detection_fixture.py` — injection 1/2 fixtures flagged by
  `run_hard_gate(write=False)`; injection 9/10 fixtures flagged by the kernel checks
  (imported from Task 04's module); injection 7 candidate rejected by Task 07 validation.
- `test_rqgm_eval_doubles.py` — doubles are LLM-free; registry keys match the documented set;
  doubles refused when `rqgm.eval.enabled=false`.

Tier-2 smoke (marked `slow`/opt-in, stub LLM backend): one ≤5-node run per scripted injection
(4/5/6/8) asserting the expected detection record appears within `max_latency_epochs` and the
run terminates normally; one B0 smoke asserting artifact-contract equality with a pre-RQGM
golden file list.

Tier-3 is not a test: it is the evaluation campaign itself, executed manually; its smoke
subset (B0 + B3, 1 seed, tiny budget) is documented as the "deletion-criteria smoke run".

## 10. Risks

- **LLM stochasticity confounds the ladder.** Marginal deltas (e.g. B5−B4) may be smaller
  than seed variance. Mitigation: paired seeds, medians over ≥3 seeds, and detection metrics
  (4–8) that are deterministic given the injection labels; accept that Tier-3 conclusions are
  directional, not significance-tested, at v1.
- **Cost.** 10 conditions × 3 seeds × 20 nodes is expensive. Mitigation: the required
  comparison set for completion is the reduced set {B0, B3, B4, B6, B8, B9} plus {B2 vs B3}
  (B9 is required despite the cost: B9−B8 is the only empirical defense of P1);
  the full ladder is the campaign target, not the merge gate.
- **Upstream flag availability.** B1–B9 presume Tasks 01–14 expose per-subsystem flags; if a
  task ships an all-or-nothing switch, mid-ladder rungs collapse. One instance is already
  known: Task 05 defines no `rqgm.governance.enabled` (§5.1 †), so B5 — and governance-off in
  B2–B4 — depends on Task 05 adding it. Mitigation: this plan's §5.1 table is the requirements
  list; INDEX.md records the cross-task dependency.
- **Scripted doubles diverge from real components** and measure a strawman. Mitigation:
  doubles only implement *failure* behavior; detection channels are the same code paths real
  components hit; fixture injections (F) bypass doubles entirely.
- **Cross-epoch score comparability** (global invariant 1 tension: the active
  prompt/evaluator/judge/utility policy is fixed only *within* an epoch, so scoring rules may
  legitimately differ across epochs): metric 10 compares scores across an erasure boundary.
  Epoch re-weighting is enabled: Task 14 repeals I-11, so the utility policy is frozen per epoch
  and rewritten at boundaries through the governed path. Mitigation: metric 10 is reported
  **per-weight-regime, always**, keyed on `EpochState.utility_policy["utility_policy_hash"]`
  (epoch-varying from Task 14 on, and already part of the epoch fingerprint); scores from two
  regimes are never pooled into one recovery series. The B9−B8 pair (§5.1) measures whether
  governed rewriting earns its cost.
- **`skip_if_exists` short-circuits** could contaminate pipeline-derived signals. Mitigated
  by fresh-checkpoint-per-run policy (already in §5.2).
- **Wall-clock nondeterminism** (metric 13) invites P2 violations. Mitigation: metadata-only,
  never hashed, host recorded alongside.

## 11. Completion criteria

This task is complete when all of the following hold:

1. **Ablation conditions defined** — all ten conditions B0–B9 are specified in
   `scripts/rqgm_eval/ablation_matrix.yaml` with exact mode + feature-flag expansions, and a
   Tier-1 test pins each expansion (including B0 == shipped defaults and the additive-ladder
   property).
2. **Failure injection defined** — all ten injections are specified in
   `failure_injections.yaml` with mechanism (fixture/scripted), deterministic payload,
   ground-truth label, expected detection channel, and max detection latency; fixture payloads
   exist under `ari-core/tests/fixtures/rqgm_eval/`.
3. **Metrics defined** — all thirteen metrics have an implemented-signature-level definition
   (formula, numerator/denominator, data source artifact, applicability condition) in
   `ari/rqgm/evaluation/metrics.py` design plus this plan's §5.4 table, with evidence-ref
   output format fixed in the `rqgm_eval_metrics.json` schema.
4. **simple_bfts vs ari_rqgm comparison policy written** — §5.2: same experiment set, pinned
   models, node-budget parity, ≥3 paired seeds, fresh checkpoints, cost reported not
   equalized, B0-as-regression-guard.
5. **VirSci on/off comparison policy written** — §5.2: B2 vs B3 at matched budgets as the
   primary contrast; off-condition asserted VirSci-free via prompt provenance and file-set
   checks; Tier-1/2 pass without VirSci installed.
6. Results destination (`workspace/rqgm_eval/<eval_id>/` + `ablation_report.{json,md}` schema)
   and the three-tier test strategy are specified, including which tiers gate CI.

## 12. Deletion criteria

This plan file may be deleted only when all of the following hold:

- The target feature/design is merged into the main branch.
- Corresponding tests have been added.
- CI is green.
- Key design decisions have been moved to permanent docs or code comments.
- No unresolved open questions remain, or they have been moved to another task plan.
- No downstream task depends solely on this plan file.
- INDEX.md task status has been updated to completed/deleted.
- Developers will not be confused by this file's absence.
- The deleted content remains available in git history.

Task-specific criteria (all must also hold):

- The evaluation script (`scripts/rqgm_eval/run_ablation.py`) and benchmark config
  (`ablation_matrix.yaml`, `failure_injections.yaml`, benchmark experiments) are implemented.
- Ablation conditions B0–B9 are switchable via config alone (no code edits between
  conditions).
- Minimal failure injection is implemented: at least the fixture-mechanism injections
  (1, 2, 7, 9, 10) with their Tier-1 detection tests passing.
- A results destination exists in docs or experiment output: `workspace/rqgm_eval/` layout
  producing `ablation_report.{json,md}`, and the evaluation methodology (conditions, metrics,
  comparison policies) has been migrated to the permanent evaluation guide under `docs/`.
- Tests or a smoke run exist: Tier-1 tests green in CI, and at least one recorded Tier-3
  smoke campaign ({B0, B3}, 1 seed, tiny budget) with its `ablation_report.json` archived in
  experiment output.

## 13. Delete-after checklist

Verify before deleting this file:

- [ ] Implementation is complete.
- [ ] Tests exist.
- [ ] CI is green.
- [ ] Key design decisions have been moved to permanent docs.
- [ ] Unfinished items have been moved to another task plan.
- [ ] INDEX.md has been updated.
- [ ] Deleting this plan file will not strand any developer.
- [ ] The deletion reason can be stated in the commit message.

Task-specific items:

- [ ] All nine ablation presets expand correctly and are pinned by a Tier-1 test.
- [ ] All ten failure-injection specs exist; fixture injections have passing detection tests.
- [ ] All thirteen metrics are computed by `compute_metric_report` and covered by unit tests.
- [ ] `rqgm_eval_metrics.json` / `rqgm_injection_provenance.json` are registered in
      `PathManager.META_FILES`, and README Contents rows exist for every new file
      (readme-sync gate).
- [ ] The B0 regression smoke (artifact-contract equality with pre-RQGM ARI) passed.
- [ ] Tier-1/2 suites pass on an environment without VirSci installed.
- [ ] The comparison policies (simple_bfts vs ari_rqgm; VirSci on/off) are in the permanent
      evaluation guide, and at least one smoke campaign report is archived.
