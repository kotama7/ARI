# ari.public

Public API surface for ARI skills — skills must import **only** from
`ari.public.*`. A thin re-export layer over `ari.<module>` internals so
core can refactor freely while the contract stays put.

## Contents

- `README.md` — this file.
- `__init__.py` — exported sub-modules + rationale.
- `config_schema.py` — re-export of `ari.config` models.
- `container.py` — re-export of `ari.container`.
- `cost_tracker.py` — re-export of `ari.cost_tracker`.
- `llm.py` — re-export of `ari.llm.client.LLMClient`.
- `paths.py` — re-export of `ari.paths.PathManager`.
- `run_env.py` — re-export of `ari.agent.run_env` capture helpers.

## See also

- **Exported sub-modules & rationale** → the `__init__.py` module docstring (authoritative).
- **Stable API reference** → `docs/reference/public_api.md`.
