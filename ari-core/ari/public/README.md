# ari.public

Public API surface for ARI skills — skills must import **only** from
`ari.public.*`. A thin re-export layer over `ari.<module>` internals so
core can refactor freely while the contract stays put.

## Contents

- `README.md` — this file.
- `call_context.py` — explicit run/node/lineage models plus signed transport capability helpers.
- `__init__.py` — exported sub-modules + rationale.
- `claim_gate.py` — re-exports five symbols from `ari.pipeline.claim_gate`: `run_hard_gate` (→ ari-skill-evaluator), `check_emission` (→ ari-skill-coding), `scan_science_data` (→ ari-skill-transform), plus `classify_concept` / `CONCEPT_INVARIANTS` (shared concept→invariant registry).
- `config_schema.py` — re-export of `ari.config` models.
- `clone.py` — digest-verified EAR bundle retrieval and safe extraction.
- `container.py` — re-export of `ari.container`.
- `execution.py` — versioned workspace, bounded execution, complete-log
  artifact, and measurement contracts plus the read-only legacy parser.
- `cost_tracker.py` — re-export of `ari.cost_tracker`.
- `llm.py` — re-export of `ari.llm.client.LLMClient`.
- `paths.py` — re-export of `ari.paths.PathManager`.
- `node_selection.py` — deterministic downstream node/source selection.
- `publish.py` — staged EAR publication and promotion.
- `run_env.py` — re-export of `ari.agent.run_env` capture helpers.
- `result.py` — versioned `ResultEnvelopeV1`, artifact references, typed errors,
  call provenance, immutable async handles, and the legacy response normalizer.
- `skill_lock.py` — immutable run-level provider/schema/phase snapshot contract
  and atomic exact/subset verification helpers.
- `skill_manifest.py` — canonical Skill package, entrypoint, and tool-policy
  contract, declared timeout budgets, async lifecycle, and validation helpers.
- `verified_context.py` — re-export of `ari.pipeline.verified_context` (`render_grounded_block` / `write_verified_context`; used by ari-skill-paper).

## See also

- **Exported sub-modules & rationale** → the `__init__.py` module docstring (authoritative).
- **Stable API reference** → `docs/reference/public_api.md`.
