# ari-skill-evaluator/src

MCP server package for the evaluator skill — a data extractor (not a judge):
LLM-generated extractors pull metrics out of node artefacts and return
`(metrics, has_real_data, extractor_code)`. `__init__.py` is empty; the
package is imported via `where = ["src"]` (see `pyproject.toml`).

## Contents

- `README.md` — this file.
- `__init__.py` — empty package marker.
- `server.py` — MCP entry point: `make_metric_spec`, plus the Story2Proposal tools `claim_evidence_hard_gate` (thin wrapper over ari-core's deterministic gate; Phase B) and `evidence_grounded_semantic_review` (non-blocking LLM overclaim review; Phase D).
- `prompts/` — TODO
  - `claims_extract_sys.md` — LLM system prompt: extract falsifiable claims + their `required_evidence` measurement names from an experiment plan (JSON-only output) for the hard gate.
  - `contract_flags_sys.md` — LLM system prompt: decide the two gate contract flags (`correctness_required`, `ceiling_must_be_measured`) for an experiment plan (JSON-only output).
  - `metric_extract_sys.md` — TODO
  - `semantic_review_sys.md` — TODO

## See also

- The skill root `README.md` and the `server.py` module docstring for the tools & outward interface.
