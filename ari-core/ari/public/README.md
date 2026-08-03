# ari.public

Public API surface for ARI skills — skills must import **only** from
`ari.public.*`. A thin re-export layer over `ari.<module>` internals so
core can refactor freely while the contract stays put.

## Contents

- `README.md` — this file.
- `__init__.py` — exported sub-modules + rationale.
- `analysis.py` — versioned deterministic analysis requests and result contracts.
- `call_context.py` — explicit run/node/lineage models plus signed transport capability helpers.
- `claim_gate.py` — canonical deterministic gate plus versioned metric
- `clone.py` — digest-verified EAR bundle retrieval and safe extraction.
- `config_schema.py` — re-export of `ari.config` models.
- `container.py` — re-export of `ari.container`.
- `cost_tracker.py` — re-export of `ari.cost_tracker`.
- `evaluation.py` — stable evaluator-contract surface shared by idea,
- `execution.py` — versioned workspace, bounded execution, complete-log
- `figures.py` — declarative `FigureSpecV1`, digest-bound render/batch
- `latex_claims.py` — canonical lexical LaTeX claim/number/citation/figure parser.
- `lineage.py` — TODO
- `llm.py` — re-export of `ari.llm.client.LLMClient`.
- `memory.py` — content-addressed memory records, retrievals, events, and backups.
- `node_selection.py` — deterministic downstream node/source selection.
- `paper.py` — immutable paper build, revision, model-call, compile, review, and
- `paths.py` — re-export of `ari.paths.PathManager`.
- `publish.py` — staged EAR publication and promotion.
- `research_contract.py` — TODO
- `result.py` — versioned `ResultEnvelopeV1`, artifact references, typed errors,
- `run_env.py` — re-export of `ari.agent.run_env` capture helpers.
- `science_data.py` — canonical `ScienceDataV1` raw/derived/interpretation
- `skill_lock.py` — immutable run-level provider/schema/phase snapshot contract
- `skill_manifest.py` — canonical Skill package, entrypoint, and tool-policy
- `verified_context.py` — re-export of `ari.pipeline.verified_context` (`render_grounded_block` / `write_verified_context`; used by ari-skill-paper).
- `visual_review.py` — criteria profiles, artifact-bound review findings,

## See also

- **Exported sub-modules & rationale** → the `__init__.py` module docstring (authoritative).
- **Stable API reference** → `docs/reference/public_api.md`.
