# ari.public

Public API surface for ARI skills — skills must import **only** from
`ari.public.*`. A thin re-export layer over `ari.<module>` internals so
core can refactor freely while the contract stays put.

## Contents

- `README.md` — this file.
- `analysis.py` — versioned deterministic analysis requests and result contracts.
- `call_context.py` — explicit run/node/lineage models plus signed transport capability helpers.
- `__init__.py` — exported sub-modules + rationale.
- `claim_gate.py` — canonical deterministic gate plus versioned metric
  admission, gate-report, semantic-review, and conservative migration-reader
  contracts; also exports the shared concept/invariant checks.
- `config_schema.py` — re-export of `ari.config` models.
- `clone.py` — digest-verified EAR bundle retrieval and safe extraction.
- `container.py` — re-export of `ari.container`.
- `execution.py` — versioned workspace, bounded execution, complete-log
  artifact, and measurement contracts plus the read-only legacy parser.
- `evaluation.py` — stable evaluator-contract surface shared by idea,
  transform, evaluator, paper, and offline published-run readers.
- `figures.py` — declarative `FigureSpecV1`, digest-bound render/batch
  manifests, explicit feedback lineage, and the isolated legacy reader.
- `visual_review.py` — criteria profiles, artifact-bound review findings,
  raw/model/cost provenance, and failure-preserving review batches.
- `cost_tracker.py` — re-export of `ari.cost_tracker`.
- `llm.py` — re-export of `ari.llm.client.LLMClient`.
- `paths.py` — re-export of `ari.paths.PathManager`.
- `node_selection.py` — deterministic downstream node/source selection.
- `publish.py` — staged EAR publication and promotion.
- `run_env.py` — re-export of `ari.agent.run_env` capture helpers.
- `result.py` — versioned `ResultEnvelopeV1`, artifact references, typed errors,
  call provenance, immutable async handles, and the legacy response normalizer.
- `science_data.py` — canonical `ScienceDataV1` raw/derived/interpretation
  sections, explicit pre-v1 migration reader, flat gate projection, and shared
  numeric-formula registry.
- `skill_lock.py` — immutable run-level provider/schema/phase snapshot contract
  and atomic exact/subset verification helpers.
- `skill_manifest.py` — canonical Skill package, entrypoint, and tool-policy
  contract, declared timeout budgets, async lifecycle, and validation helpers.
- `verified_context.py` — re-export of `ari.pipeline.verified_context` (`render_grounded_block` / `write_verified_context`; used by ari-skill-paper).

## See also

- **Exported sub-modules & rationale** → the `__init__.py` module docstring (authoritative).
- **Stable API reference** → `docs/reference/public_api.md`.
