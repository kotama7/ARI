# ari.public

Public API surface for ARI skills — skills must import **only** from
`ari.public.*`. A thin re-export layer over `ari.<module>` internals so
core can refactor freely while the contract stays put.

## Contents

- `README.md` — this file.
- `__init__.py` — exported sub-modules + rationale.
- `claim_gate.py` — re-exports five symbols from `ari.pipeline.claim_gate`: `run_hard_gate` (→ ari-skill-evaluator), `check_emission` (→ ari-skill-coding), `scan_science_data` (→ ari-skill-transform), plus `classify_concept` / `CONCEPT_INVARIANTS` (shared concept→invariant registry).
- `config_schema.py` — re-export of `ari.config` models.
- `container.py` — re-export of `ari.container`.
- `cost_tracker.py` — re-export of `ari.cost_tracker`.
- `llm.py` — re-export of `ari.llm.client.LLMClient`.
- `paths.py` — re-export of `ari.paths.PathManager`.
- `run_env.py` — re-export of `ari.agent.run_env` capture helpers.
- `verified_context.py` — re-export of `ari.pipeline.verified_context` (`render_grounded_block` / `write_verified_context`; used by ari-skill-paper).

## See also

- **Exported sub-modules & rationale** → the `__init__.py` module docstring (authoritative).
- **Stable API reference** → `docs/reference/public_api.md`.
