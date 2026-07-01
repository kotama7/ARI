# scripts/quality

Rule config and frozen allowlists for the top-level `scripts/check_*` source-quality checkers.

## Contents

- `README.md` — this file.
- `_common.py` — shared checker infrastructure (the `Finding` record + §3 JSON schema, allowlist loader, Markdown-table writer, `--base-ref` git-diff resolver) reused by the `scripts/quality/` checkers; stdlib + PyYAML only.
- `analyze_references.yaml` — scan-root / prompt-base / data-selector / ignore config for `scripts/analyze_references.py` (subtask 054 reference-graph analyzer).
- `check_complexity.allow.yaml` — frozen size/complexity baseline for `check_complexity.py` (41 LOC-tier + 64 over-complexity offenders); regenerate with `--update-baseline`.
- `check_complexity.yaml` — thresholds for `check_complexity.py` — LOC tiers (warn>500/review>800/split>1200), ruff `C901` `max-complexity`, test exclusion, and default scan scope.
- `check_import_boundaries.allow.yaml` — frozen baseline of known import-boundary edges (the 7 B1 seed edges + the sanctioned core→skill edge).
- `check_import_boundaries.yaml` — rule config for `check_import_boundaries.py` (allowed skill→core roots, sanctioned core→skill package, rule toggles).
