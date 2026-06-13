# ari.pipeline.claim_gate

Deterministic `claim_evidence_hard_gate` (Story2Proposal architectural
integration, Phase B — *execution data fidelity*). The heavy logic lives here in
ari-core; the evaluator skill exposes a thin MCP tool
(`claim_evidence_hard_gate`) that calls `run_hard_gate`.

It verifies, with no LLM:

- **claim existence** — `supported_by` node ids exist in `tree.json` and are
  executed; referenced artifacts exist.
- **numeric recompute** — `numeric_assertion` operands `(node_id, metric_path)`
  resolve from `results.json` / `tree.json`; the formula re-derives a value; the
  paper-reported number matches within tolerance. This covers both the
  transform-generated assertions AND the writer's inline **forward declarations**
  (`paper_claim_links.writer_assertions`, Story2Proposal (c)) — verified the same
  way (forward, never a reverse search), so a wrong declaration → `numeric_mismatch`.
- **numeric coverage** — result-claim numbers in target sections are backed by a
  `numeric_assertion` (generated or writer-declared); uncovered numbers flagged
  per section policy.
- **figure existence** — referenced figures are registered; sources exist.
- **universal metric invariants** — `invariants.scan_science_data` flags
  physically-impossible metric values (e.g. a normalized metric > 1) via the
  domain-general concept→invariant registry; emits `invariant_violation`.
- **declared `metric_contract` enforcement** — `contract.check_contract` checks a
  config's DECLARED contract: placeholder/provenance, declared invariants,
  correctness, formula recompute, plan-fidelity claim-evidence, and idea-owned
  ceiling/correctness flags (no-op for runs without a `metric_contract`).

Verification boundary: this checks transcription/derivation consistency between
the paper and the recorded results — NOT the truthfulness of the recorded
results (that is ORS / external reproducibility). For how the gate, the
non-blocking semantic review, and ORS compose (orthogonal evidence sources,
ordering, blocking), see "Evaluation-mechanism relationship" in
`ari-core/REQUIREMENTS.md`.

Blocking: in `strict` mode the **final** phase returns `should_block=True` when
its `block_on` errors remain; the MCP wrapper then returns an error-only payload
so the pipeline stage fails and `finalize_paper` is skipped. In addition,
objective-falsehood findings (`always_block_on` — `invariant_violation`,
`correctness_failed`, `correctness_uncovered`, `placeholder_denominator`,
`recompute_mismatch`, `claim_evidence_missing`, `ceiling_unmeasured`) block at
**final** in ANY mode, so `warn` and `off` do block at final on objective
falsehoods. Only the `draft` phase never blocks.

## Contents

- `README.md` — this file.
- `__init__.py` — package init; re-exports `run_hard_gate`.
- `contract.py` — `check_contract` enforces a config's DECLARED `metric_contract` (provenance/placeholder, declared invariants, correctness, formula recompute, plan-fidelity claims, idea-owned ceiling/correctness flags → findings); `check_emission` mirrors the presence checks as producer-side advisory warnings.
- `formula_eval.py` — `safe_eval` whitelisted-AST evaluator for declared metric-contract expressions (arithmetic/comparisons/conditionals/reducers over bound scalars+lists; None on anything unsupported, never `eval`).
- `gate.py` — `run_hard_gate` orchestration (all checks → report + `should_block`).
- `invariants.py` — universal-math invariant registry + `classify_concept` (name→concept) and `scan_science_data` emitting `invariant_violation` findings (declared bounds + name-inferred normalized<=1 / probability[0,1]; no domain knowledge).
- `latex.py` — deterministic LaTeX section + numeric-token parsing (coverage fallback; mirrors ari-skill-paper/src/claim_links.py).
- `numeric.py` — formula registry + `recompute` + `within_tolerance` (Phase B2; mirrored in ari-skill-transform/src/claims.py).
- `policy.py` — `claim_gate_policy` loader (defaults → arg → `claim_gate_policy.json` → env `ARI_CLAIM_GATE_MODE`).
- `resolve.py` — operand/evidence resolution against `tree.json` / `results.json` / `node_report.json`.

## See also

- Requirements: `ari-core/REQUIREMENTS.md` ("Evaluation-mechanism relationship").
- Wiring: `ari-core/config/workflow.yaml` (`claim_gate_policy`, the two gate stages).
