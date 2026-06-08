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

Verification boundary: this checks transcription/derivation consistency between
the paper and the recorded results — NOT the truthfulness of the recorded
results (that is ORS / external reproducibility). For how the gate, the
non-blocking semantic review, and ORS compose (orthogonal evidence sources,
ordering, blocking), see "Evaluation-mechanism relationship" in
`ari-core/REQUIREMENTS.md`.

Blocking: in `strict` mode the **final** phase returns `should_block=True` when
blocking errors remain; the MCP wrapper then returns an error-only payload so the
pipeline stage fails and `finalize_paper` is skipped. `draft` phase and
`warn`/`off` mode never block.

## Contents

- `README.md` — this file.
- `__init__.py` — package init; re-exports `run_hard_gate`.
- `contract.py` — TODO
- `formula_eval.py` — TODO
- `gate.py` — `run_hard_gate` orchestration (all checks → report + `should_block`).
- `invariants.py` — TODO
- `latex.py` — deterministic LaTeX section + numeric-token parsing (coverage fallback; mirrors ari-skill-paper/src/claim_links.py).
- `numeric.py` — formula registry + `recompute` + `within_tolerance` (Phase B2; mirrored in ari-skill-transform/src/claims.py).
- `policy.py` — `claim_gate_policy` loader (defaults → arg → `claim_gate_policy.json` → env `ARI_CLAIM_GATE_MODE`).
- `resolve.py` — operand/evidence resolution against `tree.json` / `results.json` / `node_report.json`.

## See also

- Master plan: `Story2Proposal計画書.md` §6–§8; child plan: `ari-core/PLAN_s2p_hard_gate.md`.
- Wiring: `ari-core/config/workflow.yaml` (`claim_gate_policy`, the two gate stages).
