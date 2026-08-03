# ari.config

Pydantic configuration models for ARI (`LLMConfig`, `BFTSConfig`, …) and
their env-var overrides (`ARI_BACKEND`, `ARI_MODEL`, …).

## Contents

- `README.md` — this file.
- `__init__.py` — Pydantic config models + env-var overrides.
- `field_registry.py` — canonical inventory of every declared `ARIConfig` leaf plus its metadata overlay (category / level / scope / sensitivity / mutability); pure and deterministic, backs `GET /api/v1/config/schema`.
- `finder.py` — workflow / profile YAML discovery.
- `resolver.py` — resolved-config reconstruction: post-hoc for an existing checkpoint and preview for a new run, emitting values + per-leaf provenance + digest + warnings without running the imperative override chain.
- `skill_runtime.py` — resolve canonical Skill manifests, runtime environments, credentials, and lock identities.

## See also

- **Field-level contract** → the model docstrings in `__init__.py` (authoritative).
- **Settings & env vars reference** → `docs/reference/configuration.md`, `docs/reference/environment_variables.md`.
