# ari.pipeline

Generic workflow execution engine driven entirely by `workflow.yaml` (no
hardcoded tool names). Adding a skill or stage is a YAML change, not a
code change. Public surface (`run_pipeline`, `load_workflow`, …) is
re-exported from the package root.

## Contents

- `README.md` — this file.
- `__init__.py` — sub-module map + public re-exports.
- `context_builder.py` — best-nodes context + keyword extraction.
- `experiment_md.py` — `experiment.md` helpers.
- `orchestrator.py` — top-level entry points (`build_scientific_data`, `run_pipeline`).
- `stage_control.py` — loop_back / VLM-feedback control.
- `stage_runner.py` — stage execution helpers (retry, ReAct, subprocess).
- `verified_context.py` — artifact-grounded verified context for write_paper (best node's root→best lineage → `verified_context.json`; `render_grounded_block`). Exposed via `ari.public.verified_context`.
- `yaml_loader.py` — workflow/pipeline loaders + `{{var}}` resolution.
- `claim_gate/` — deterministic `claim_evidence_hard_gate` (Story2Proposal Phase B). See its `README.md`.
  - `README.md` — claim_gate index.
  - `__init__.py` — package init; re-exports `run_hard_gate`.
  - `gate.py` — `run_hard_gate` orchestration (all checks → report + `should_block`).
  - `latex.py` — deterministic LaTeX section + numeric-token parsing (coverage fallback; mirrors ari-skill-paper/src/claim_links.py).
  - `numeric.py` — formula registry + `recompute` + `within_tolerance` (Phase B2; mirrored in ari-skill-transform/src/claims.py).
  - `policy.py` — `claim_gate_policy` loader (defaults → arg → `claim_gate_policy.json` → env `ARI_CLAIM_GATE_MODE`).
  - `resolve.py` — operand/evidence resolution against `tree.json` / `results.json` / `node_report.json`.

## See also

- **Sub-module map & re-exports** → the `__init__.py` module docstring (authoritative).
- **Workflow file & stages** → `docs/concepts/architecture.md`, `docs/guides/experiment_file.md`.
- **Split history** → `git log -- ari-core/ari/pipeline/`.
