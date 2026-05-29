# ari.orchestrator.node_report

Per-node `node_report.json` builder (`builder`) plus a thin shim
(`legacy_reconstruct`) re-exporting the v0.5 reconstruction logic from
`ari.migrations.v05_to_v07.node_reports`.

## Contents

- `README.md` — this file.
- `__init__.py` — re-exports the builder + legacy shim.
- `builder.py` — v0.7+ `node_report.json` builder.
- `legacy_reconstruct.py` — v0.5 → v0.7 reconstruct shim.

## See also

- **Re-exported public symbols** → the `__init__.py` module docstring (authoritative).
- **`node_report.json` format** → `docs/reference/file_formats.md`.
