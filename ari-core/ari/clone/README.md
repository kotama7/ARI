# ari.clone

`ari clone` — fetch + verify + extract curated EAR bundles. Owns the
orchestration (digest-checked, atomic, no post-fetch code execution);
scheme resolvers live in `resolvers/`.

## Contents

- `README.md` — this file.
- `__init__.py` — clone orchestration + design constraints.
- `resolvers/` — scheme dispatch.
  - `README.md` — resolvers index.
  - `__init__.py` — resolver contract + `_RESOLVERS` table.
  - `ari.py` — `ari://` resolver.
  - `doi.py` — `doi:` (Zenodo) resolver.
  - `file.py` — `file://` resolver.
  - `gh.py` — `gh:` resolver.
  - `https.py` — `https://`/`http://` resolver.

## See also

- **Design constraints & flow** → the `__init__.py` module docstring (authoritative).
- **EAR bundle format** → `docs/reference/file_formats.md`.
