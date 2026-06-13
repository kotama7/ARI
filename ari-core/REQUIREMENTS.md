# ari-core Requirements

## Overview

Core framework for Autonomous Research Infrastructure.
Accepts an experiment specification Markdown, runs autonomous research via
BFTS tree search × Agent loop, and outputs a paper section.

## Design Principles

- **P1 Generic core**: No experiment-domain knowledge in ari-core
- **P2 Deterministic skills**: No LLM calls inside MCP skill servers
- **P3 Multi-objective evaluation**: No scalar score; raw metrics dict drives selection
- **P4 Dependency injection**: Domain knowledge injected from experiment.md at runtime

## Tech Stack

- Python 3.11+
- litellm (LLM routing: Ollama, OpenAI, Anthropic)
- FastMCP (MCP client)
- pydantic (data models)
- pytest (tests)

## Key Interfaces

### BFTSConfig
```python
@dataclass
class BFTSConfig:
    max_nodes: int = 10
    max_depth: int = 3
    max_parallel: int = 2
    timeout_per_node: int = 1200
```

### WorkflowHints
Domain-specific workflow configuration auto-extracted from experiment.md.
Controls tool sequence, metric extraction, and validation behavior.

### NodeLabel
- `DRAFT`: Initial state
- `SUCCESS`: has_real_data=True
- `FAILED`: Evaluation failed or hallucination detected

## Post-BFTS Pipeline

Configured via `config/pipeline.yaml`.
Stages: `generate_paper` → `review` → `reproducibility_check`

Adding a stage requires only a YAML change — no core code modification.

## Pipeline Keyword Extraction

`pipeline.py` contains `_extract_keywords_from_nodes(nodes_json_path)`:
- Reads `nodes_tree.json` produced by BFTS
- Extracts compiler flags, optimization keywords from node memory/artifacts
- Returns a targeted arXiv query string
- Called before the `search_related_work` stage; query injected as `args["query"]`
- **No LLM. No MCP call.** Pure Python deterministic function.

## Story2Proposal integration (execution-grounded contract)

### claim_evidence_hard_gate (Phase B, `ari/pipeline/claim_gate/`)
The only blocking gate. Deterministic verification that the paper's claims and
numbers are consistent with executed evidence (`tree.json` / `results.json` /
`node_report.json` / `figures_manifest.json`):
- claim existence (nodes exist & executed, artifacts present),
- `numeric_assertion` formula-level recompute vs the paper-reported number within
  tolerance (operands `(node_id, metric_path)`),
- numeric coverage per section policy (uncovered result numbers),
- figure existence (referenced figures registered, sources present).
Runs twice: **draft** (after write_paper, informational) and **final** (after
paper_refine). The logic lives in ari-core; the evaluator skill exposes the MCP
tool. `finalize_paper` `depends_on` the **final** gate.

**Verification boundary:** transcription/derivation consistency between the paper
and the recorded results — NOT the truthfulness of the recorded results (that is
ORS / external reproducibility).

**Blocking semantics:** `mode` (in `claim_gate_policy`, overridable by env
`ARI_CLAIM_GATE_MODE`) — `off` never blocks; `warn` (MVP default) reports
errors/warnings but never blocks finalize; `strict` (evaluation) makes the final
gate return `should_block`, which the MCP wrapper turns into a stage failure so
`finalize_paper` is skipped. The draft gate never blocks. The numeric formula
registry is in `ari/pipeline/claim_gate/numeric.py` (mirrored in
ari-skill-transform's `claims.py`).

### claim_gate_policy (Phase B3, `config/workflow.yaml`)
Top-level dict: `mode`, `comparison_scope`,
`numeric_coverage.target_sections.{strict,warn,excluded}`,
`numeric_match.default_tolerance`, `blocking.block_on`. Passed to the gate stages
via `{{claim_gate_policy}}`; loaded by `ari/pipeline/claim_gate/policy.py`.

`comparison_scope` (injected research intent, P4; env `ARI_COMPARISON_SCOPE`):
`any` (default) keeps a cross-environment comparison as a transparency
**warning** (`environment_mismatch`) — correct for cross-architecture studies
where the cross-host comparison is the contribution; `same_environment` makes it
a **blocking** error — correct for single-architecture optimization studies. The
gate never hardcodes "cross-arch = invalid"; validity is the injected intent's
call. The claim generator (ari-skill-transform) honors the same scope when
selecting comparison baselines.

### Pipeline topology (Phase E, `config/workflow.yaml`)
The generate–evaluate–adapt loop is wired in `workflow.yaml` in **dependency
order**, back-ported from the validated checkpoint topology (Step 13):
`write_paper → link_paper_claims_draft → claim_evidence_hard_gate_draft →
review_paper (independent) + evidence_grounded_semantic_review →
merge_reviews (independent vs evidence-grounded split) → paper_refine
(anchor-preserving) → render_paper → link_paper_claims_final →
evidence_grounded_semantic_review_post_refine + claim_evidence_hard_gate_final →
finalize_paper`. `finalize_paper` `depends_on` the **final** hard gate (blocking
contract), `merge_reviews` receives the hard-gate + semantic-review paths, and
because the orchestrator runs stages in file order with **no topological sort**,
the dependency-correct ordering is what makes activation a safe flag flip — a
file-order dependency check confirms zero skip violations when enabled.
`review_paper` / `vlm_review_figures` independence is preserved (they run on the
write_paper draft before `finalize_paper`, which only injects Code-Availability
macros and does not recompile).

The S2P stages are **enabled by default in warn mode** (decision 2026-06-05): the
contract loop runs on every paper build, and the hard gate reports
(numeric recompute / coverage / figure existence) but **never blocks** finalize
(`claim_gate_policy.mode: warn`). To make the FINAL gate blocking (skip
`finalize_paper` on numeric mismatch / uncovered numbers), set
`claim_gate_policy.mode: strict` or `ARI_CLAIM_GATE_MODE=strict`. To opt a single
stage out, set its `enabled: false`. The e2e contract (`test_pipeline_e2e.py`)
asserts the full 24-tool sequence accordingly.

### Evaluation-mechanism relationship (Step 14: hard gate ↔ semantic review ↔ ORS)
ARI runs three complementary evaluators over a generated paper. They are
**orthogonal** (distinct evidence sources, distinct failure modes) and **compose**
rather than overlap:

| mechanism | question answered | evidence read | when | blocking |
|---|---|---|---|---|
| `claim_evidence_hard_gate` | Does the paper faithfully **transcribe/derive the recorded results**? (internal consistency) | `science_data.json` / `results.json` / `node_report.json` / paper / `paper_claim_links` | before `finalize_paper` (draft + final) | yes (strict) |
| `evidence_grounded_semantic_review` | Does the prose **over-claim / mis-interpret** beyond the evidence? (meaning) | paper + hard-gate output + `science_data` | around `paper_refine` | no |
| ORS (`ors_*`; `ari-skill-replicate` rubric + `ari-skill-paper-re` reproduce/grade) | Do the recorded results actually **reproduce** when a third party rebuilds from the paper + published bundle? (external reproducibility) | finalized paper + EAR bundle → auto rubric → `reproduce.sh` → re-execution → PaperBench SimpleJudge grade | after `finalize_paper` | no (downstream grade) |

Confirmed relationship:
- **No overlap (different evidence sources).** The hard gate recomputes the paper's
  numbers from the *same* `results.json` the paper cites — it verifies
  transcription/derivation, never results↔reality. ORS *re-executes* from artifacts
  to produce *fresh* results and scores them against a rubric auto-generated from
  the paper — it verifies results↔reality. A paper can pass the hard gate (faithful
  reporting) yet score low on ORS (non-reproducible), and vice versa; both failure
  modes are real, which is why both exist.
- **Composition / ordering.** The final hard gate gates `finalize_paper`
  (`depends_on`); the ORS chain (`ors_generate_rubric → ors_seed_sandbox →
  ors_build_reproduce → ors_run_reproduce → ors_grade`) `depends_on` `finalize_paper`
  / `ear_publish`, so it grades the *finalized* artifact and never blocks paper
  finalization. Hard gate = precondition (the paper must faithfully report its
  evidence); ORS = independent downstream verdict on whether that evidence reproduces.
- **Semantic review sits between** them: it judges meaning (overclaim,
  interpretation, caption coherence) that neither the deterministic gate nor the
  rubric-scored re-execution measures; non-blocking, feeds `paper_refine`.

This matches plan §6 ("hard gate = internal consistency; ORS = external
reproducibility"). The empirical ORS-vs-gate comparison on a shared checkpoint is a
follow-up: ORS stages were `enabled: false` in the Step-13 validation run (see
Status), so the relationship above is confirmed architecturally (code + data flow),
not yet measured side-by-side.

### Verified-context grounding (handoff: artifact-grounded paper claims)
`run_pipeline` builds `{checkpoint_dir}/verified_context.json` (best node's
root→best lineage, via `ari.pipeline.verified_context.write_verified_context`)
when consolidation is enabled (`ari.config.consolidation_enabled`, **default ON**;
set `ARI_MEMORY_CONSOLIDATE=0`/`false` to disable → not built → no flow change —
validated live: the node-end hook writes provenanced `experiment_result` entries
that this lineage-scopes). `write_paper_iterative` receives the path (a plain input, deliberately
NOT in `load_inputs` so the write_paper stage-config / dependency resolution is
unperturbed) and injects `render_grounded_block(...)` into the system prompt,
instructing the LLM to ground quantitative claims only on verified, artifact-
backed results. Both helpers are exposed to skills via `ari.public.verified_context`
(req-09 contract). Graceful: absent/empty file → nothing injected.

### Working-context injection (Phase 0 — node-start inheritance)
At node start, `LoopRunner.run` injects a deterministic, loop-orchestrated
working context (`ari.agent.loop.build_working_context_messages`), replacing
the old one-shot semantic pre-seed (which joined up to 5 ancestor entries and
truncated to an aggregate 800 chars, dropping most):
(1a) **experiment core** (`get_experiment_context`: goal/metric/hardware) for
every node; (1b) **ancestor core** — each ancestor's `result_summary`
conclusions, fetched per-ancestor (`get_node_memory`, read-only, scoped) and
injected in full (per-entry capped, not aggregate); (2) a small per-entry-capped
semantic supplement, deduped against (1b). Field/entry caps are module
constants (`_CORE_FIELD_CAP` / `_ANCESTOR_SUMMARY_CAP` / `_SUPPLEMENT_CAP`).
Validated live (experiment core + full ancestor conclusions, sibling isolation,
real `memory_access.jsonl`). This *inheritance* path is independent of and
always-on (not gated by `ARI_MEMORY_CONSOLIDATE`); it keeps using
`result_summary`, while the typed/verified layer above feeds paper grounding.

### BFTS planner typed-memory injection — intentionally NOT implemented
Feeding ancestor `failure_case` / `procedure` into `expand()` (so the planner
avoids re-trying ancestor failures) was evaluated against an evidence gate
(PLAN §16.1) and **deliberately skipped**: a real BFTS run (2026-06-04, triad
benchmark, 6 nodes) measured **0% failure-recurrence** — failed nodes shared
only 1/5–1/6 of their `files_changed` with ancestors (they tried distinct
approaches), so the existing inheritance channels (work_dir physical copy +
EXPAND parent `node_report` block + Phase-0 ancestor `result_summary`) already
suffice. Re-evaluate only if a future run shows high (>15–20%) recurrence
(measure via `node_report.json` `files_changed`/status vs ancestors).

### Hypothesis traceability (Phase C — conclusion: no new ledger needed for MVP)
Investigation result: the chain hypothesis → experiment → result → claim is
adequately reconstructable from existing data for ARI's dominant single-active-
idea-per-checkpoint mode — `claim.supported_by.nodes[]` → node in `tree.json` →
the checkpoint's `idea.json` (active idea) + `lineage_decisions.jsonl`
(`active_idea_*`, `chosen_index`/`target_idea_index`). **A new `hypotheses[]`
layer is NOT introduced.** The one identified gap — per-node `idea_index`
disambiguation when multiple ideas spawn nodes within a *single* tree (rare; idea
switches generally fork a child checkpoint) — is documented as a future
enhancement (`Node.idea_index` + per-node creation entries in
`lineage_decisions.jsonl`), not implemented, per "don't build the ledger upfront".

## Status

Story2Proposal Phases A/A2/B/C/D/E: code + unit tests complete
(`tests/test_claim_evidence_hard_gate.py` and the skill suites), and the canonical
`config/workflow.yaml` topology is back-ported to the validated dependency order
(see Pipeline topology).

**Step 13 (end-to-end paper-pipeline run): DONE.** A full 13-stage paper run
completed exit 0 (2026-06-05) over the real cluster-generated checkpoint
`workspace/checkpoints/20260528180541_We_propose_an_implementation_of_CSR-form`
(CSR-SpMM single-architecture study), exercising the whole loop
`transform_data → write_paper → link/gate(draft) → review + semantic → merge →
paper_refine → render_paper → link/semantic/gate(final) → finalize_paper`. Final
hard gate (warn): `numeric_assertions_total=24`, `numeric_claim_reproducible_rate=1.0`,
`numeric_claim_mismatch_count=0`, `numeric_coverage_rate=1.0`,
`uncovered_numeric_count=0`, `execution_grounded_claim_rate=1.0`; `paper_refine`
applied a 30-line diff; `render_paper` recompiled the refined `.tex` to a 7-page
PDF. The run also surfaced and fixed a `render_paper` output-copy defect
(`orchestrator._copy_stage_output_if_distinct`, regression-tested in
`test_pipeline_e2e.py`). Host: login node — the paper pipeline consumes
already-executed provenance and has no compute-node-specific dependency (the
upstream experiment data was generated on the cluster), so this is the appropriate
host for the paper chain. The full provenance lives under the (gitignored)
checkpoint; the metrics above are the tracked record. The Step-13 run itself used
`warn` mode; the strict/blocking path was validated separately (below).

**Strict (blocking) path: VALIDATED** (2026-06-05, on the same real checkpoint,
read-only/`write=False`). Positive: clean paper + `{"mode":"strict"}` + `phase=final`
→ `should_block=False`, 0 errors (strict does not false-positive on good data).
Negative: a reported number corrupted (20.91→99.99) and the paper relinked →
`numeric_mismatch` (reported 99.99 vs recomputed 20.91) → `should_block=True`. The
full chain is confirmed end-to-end: the evaluator wrapper converts `should_block`
into exactly `{"error": ...}` (`ari-skill-evaluator` `_tool_claim_evidence_hard_gate`,
regression-tested in `tests/test_s2p_tools.py`), `stage_runner` raises on an
error-only MCP result, and the orchestrator records the stage error so a dependent
`finalize_paper` is skipped (covered by `test_pipeline_e2e.py::test_mcp_error_dict_detected_as_failure`).

**Step 14 (hard gate ↔ semantic review ↔ ORS relationship): confirmed
architecturally** — see "Evaluation-mechanism relationship" above (the empirical
side-by-side ORS-vs-gate comparison remains a follow-up, since ORS was disabled in
the Step-13 run).

**§10 evaluation experiments (Condition A–D / Ablation 1–6 / human
overclaim-precision spot-check): intentionally NOT run** (decision 2026-06-05).
These are a comparative *research-evaluation* meant to quantify the integration's
effect (e.g. for a publication), not a correctness requirement: the mechanisms
themselves are established by the Phase A–E implementation, the Step-13 end-to-end
run, and the strict-path validation above. Recorded here as an intentional skip per
the master plan's deletion rule (§"削除要件"); revisit only if a quantitative
ablation is later needed for a paper. The empirical ORS-vs-gate comparison is of the
same research-evaluation nature and is likewise out of scope unless explicitly
requested (it would need an ORS-enabled run).

**Activation decision (2026-06-05): S2P stages enabled by default in warn mode**
(see Pipeline topology). The strict/blocking mode remains available via
`claim_gate_policy.mode: strict` / `ARI_CLAIM_GATE_MODE=strict` but is not the
default. Remaining: only the final cleanup (delete the child `PLAN_s2p_*.md` +
master plan, and move the gitignored `experiments/` evaluation artifacts to a
tracked path or drop them). Child plans and the master plan are retained until that
cleanup PR; see `PLAN_s2p_hard_gate.md`, `PLAN_s2p_merge_refine.md`,
`PLAN_s2p_hypothesis_ledger.md`.
