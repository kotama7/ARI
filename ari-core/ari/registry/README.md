# ari.registry

Minimal HTTP registry for curated EAR bundles: upload/download/promote
artifacts with token auth and a sqlite-backed token store.

## Contents

- `README.md` — this file.
- `__init__.py` — endpoints + storage-layout docstring.
- `app.py` — FastAPI app builder.
- `auth.py` — sqlite-backed bearer-token auth.
- `cli.py` — `ari registry` serve / token / gc CLI.
- `storage.py` — filesystem storage backend.

## See also

- **Endpoints & storage layout** → the `__init__.py` module docstring (authoritative).
- **Reference** → `docs/reference/registry.md`, `docs/reference/rest_api.md`.
