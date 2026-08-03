# ari-skill-evaluator/src

MCP server package for the evaluator skill — a data extractor (not a judge):
LLM-generated extractors pull metrics out of node artefacts and return
`(metrics, has_real_data, extractor_code)`. `__init__.py` is empty; the
package is imported via `where = ["src"]` (see `pyproject.toml`).

## Contents

- `README.md` — this file.
- `__init__.py` — empty package marker.
- `server.py` — MCP entry point: `make_metric_spec`, plus the Story2Proposal tools `claim_evidence_hard_gate` (thin wrapper over ari-core's deterministic gate; Phase B) and `evidence_grounded_semantic_review` (non-blocking LLM overclaim review; Phase D).
- `prompts/` — the server's four LLM system prompts, externalised as `.md` and read via the skill-local `_load_prompt` (mirrors ari-core's `load_versioned` without importing it).
  - `metric_contract_proposal_sys.md` — constrained prompt for provenance-bound, review-required metric proposals.
  - `semantic_review_sys.md` — LLM system prompt: evidence-grounded semantic review — reasoning / data_interpretation / visual_semantics scores, overclaim warnings and suggested revisions (JSON-only); numbers are already gated deterministically.

## See also

- The skill root `README.md` and the `server.py` module docstring for the tools & outward interface.
