# ari.public

Public API surface for ARI skills — skills must import **only** from
`ari.public.*`. A thin re-export layer over `ari.<module>` internals so
core can refactor freely while the contract stays put.

Knowledge–Capability–Assurance APIs are intentionally separate:
`ari.public.knowledge` exposes non-executable procedural content,
`ari.public.providers` is the semantic facade over existing MCP Provider
contracts, `ari.public.capability_binding` resolves executable authority, and
`ari.public.assurance` resolves independent verification. These read-only
surfaces do not expose catalog promotion, lock rewriting, tolerance changes,
or force-pass operations.

## Contents

- `README.md` — this file.
- `__init__.py` — exported sub-modules + rationale.
- `analysis.py` — versioned deterministic analysis requests and result contracts.
- `assurance.py` — Verification Contracts, Harness catalogs, locks, and Attestations.
- `call_context.py` — explicit run/node/lineage models plus signed transport capability helpers.
- `capability_binding.py` — Capability ontology and deterministic binding contracts.
- `claim_gate.py` — canonical deterministic gate plus versioned metric
- `clone.py` — digest-verified EAR bundle retrieval and safe extraction.
- `config_schema.py` — re-export of `ari.config` models.
- `container.py` — re-export of `ari.container`.
- `cost_tracker.py` — re-export of `ari.cost_tracker`.
- `evaluation.py` — stable evaluator-contract surface shared by idea,
- `execution.py` — versioned workspace, bounded execution, complete-log
- `figures.py` — declarative `FigureSpecV1`, digest-bound render/batch
- `knowledge.py` — non-executable Knowledge Skill catalogs, pinned external
- `latex_claims.py` — canonical lexical LaTeX claim/number/citation/figure parser.
- `lineage.py` — stable recursion-lineage lookup and ancestor artifact traversal.
- `llm.py` — re-export of `ari.llm.client.LLMClient`.
- `manuscript.py` — stable public exports for Manuscript Complete contracts and runtime operations.
- `memory.py` — content-addressed memory records, retrievals, events, and backups.
- `node_selection.py` — deterministic downstream node/source selection.
- `paper.py` — immutable paper build, revision, model-call, compile, review, and
- `paths.py` — re-export of `ari.paths.PathManager`.
- `providers.py` — canonical Provider aliases and semantic catalog projections.
- `publish.py` — staged EAR publication and promotion.
- `research_contract.py` — stable immutable research, metric, retrieval, evidence, and survey contracts.
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
