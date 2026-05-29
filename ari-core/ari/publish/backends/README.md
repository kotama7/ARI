# ari.publish.backends

Publish backend implementations, selected by the `backend=` argument to
`ari.publish.publish`. Each module exposes `publish(...)` and `promote(...)`
with the same signature.

## Contents

- `README.md` — this file.
- `__init__.py` — backend contract.
- `ari_registry.py` — ari-registry server backend.
- `gh.py` — GitHub `gh` CLI backend.
- `local_tarball.py` — local-directory backend.
- `zenodo.py` — Zenodo REST backend.

## See also

- **Backend contract** → the `__init__.py` module docstring (authoritative).
