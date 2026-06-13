# ari.config

Pydantic configuration models for ARI (`LLMConfig`, `BFTSConfig`, …) and
their env-var overrides (`ARI_BACKEND`, `ARI_MODEL`, …).

## Contents

- `README.md` — this file.
- `__init__.py` — Pydantic config models + env-var overrides.
- `finder.py` — workflow / profile YAML discovery.
- `Plan.md` — G1 HandoffConfig＋env override の実装計画（handoff study）.

## See also

- **Field-level contract** → the model docstrings in `__init__.py` (authoritative).
- **Settings & env vars reference** → `docs/reference/configuration.md`, `docs/reference/environment_variables.md`.
