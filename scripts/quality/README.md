# scripts/quality

Rule config and frozen allowlists for the top-level `scripts/check_*` source-quality checkers.

## Contents

- `README.md` — this file.
- `_common.py` — shared checker infrastructure (the `Finding` record + §3 JSON schema, allowlist loader, Markdown-table writer, `--base-ref` git-diff resolver) reused by the `scripts/quality/` checkers; stdlib + PyYAML only.
- `analyze_references.yaml` — scan-root / prompt-base / data-selector / ignore config for `scripts/analyze_references.py` (subtask 054 reference-graph analyzer).
- `check_complexity.allow.yaml` — frozen size/complexity baseline for `check_complexity.py` (41 LOC-tier + 64 over-complexity offenders); regenerate with `--update-baseline`.
- `check_complexity.yaml` — thresholds for `check_complexity.py` — LOC tiers (warn>500/review>800/split>1200), ruff `C901` `max-complexity`, test exclusion, and default scan scope.
- `check_dashboard_ux.allow.yaml` — TODO
- `check_dashboard_ux.yaml` — TODO
- `check_dead_code.allow.yaml` — frozen `SAFE_DELETE_CANDIDATE` baseline for `check_dead_code.py` (empty at seed; only shrinks as subtask 057 deletes reviewed candidates); regenerate with `--update-baseline`.
- `check_dead_code.yaml` — classification config for `check_dead_code.py` — graph path, PUBLIC_CONTRACT / dynamic-seam / TEST_ONLY / under-traced-seam path lists, `SAFE_DELETE` eligibility (ruff-corroborated), and the `--check` budget.
- `check_import_boundaries.allow.yaml` — frozen baseline of known import-boundary edges (the 7 B1 seed edges + the sanctioned core→skill edge).
- `check_import_boundaries.yaml` — rule config for `check_import_boundaries.py` (allowed skill→core roots, sanctioned core→skill package, rule toggles).
- `check_prompts.allow.yaml` — frozen inline-prompt baseline for `check_prompts.py` (23 role-marked candidates seeded from the Subtask 036 census, each tagged with its 036/011 §5.x verdict); regenerate with `--update-baseline`.
- `check_prompts.yaml` — heuristics for `check_prompts.py` — role/JSON/rubric markers, min-lines/min-chars thresholds, default scan scope, and vendored `KEEP_INLINE` excludes.
- `check_viz_api_schema.allow.yaml` — frozen baseline for `check_viz_api_schema.py` (1 known client-only F6a drift + 20 legitimately server-only routes: static/SSE/direct-URL/proxy/no-FE-consumer).
- `check_viz_api_schema.yaml` — config for `check_viz_api_schema.py` (routes.py + api.ts targets, the four get/post/pbGet/pbPost helper→method map, declarative-route toggle).
- `generate_quality_report.yaml` — TODO
