# ari.clone.resolvers

Scheme dispatch for `ari clone` (`file://`, `https://`, `ari://`, `gh:`,
`doi:`). Each resolver materialises an artifact on disk for the caller.

## Contents

- `README.md` — this file.
- `__init__.py` — resolver contract + `_RESOLVERS` table.
- `ari.py` — `ari://` resolver.
- `doi.py` — `doi:` (Zenodo) resolver.
- `file.py` — `file://` resolver.
- `gh.py` — `gh:` resolver.
- `https.py` — `https://`/`http://` resolver.

## See also

- **Resolver contract & how to add one** → the `__init__.py` module docstring (authoritative).
