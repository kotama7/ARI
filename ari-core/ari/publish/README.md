# ari.publish

`ari ear publish` — package a curated EAR and ship it to a backend
(`local_tarball`, `ari_registry`, `zenodo`, `gh`). Emits a deterministic
`bundle.tar.gz` + `publish_record.json`, then injects the ref into the
paper's Code Availability section.

## Contents

- `README.md` — this file.
- `__init__.py` — publish flow + artifacts.
- `backends/` — publish backend implementations.
  - `README.md` — backends index.
  - `__init__.py` — backend contract.
  - `ari_registry.py` — ari-registry server backend.
  - `gh.py` — GitHub `gh` CLI backend.
  - `local_tarball.py` — local-directory backend.
  - `zenodo.py` — Zenodo REST backend.

## See also

- **Publish flow & artifacts** → the `__init__.py` module docstring (authoritative).
- **Publication lifecycle** → `docs/concepts/publication-lifecycle.md`.
