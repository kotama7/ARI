# scripts/quality

Rule config and frozen allowlists for the top-level `scripts/check_*` source-quality checkers.

## Contents

- `README.md` — this file.
- `_common.py` — shared checker infrastructure (the `Finding` record + §3 JSON schema, allowlist loader, Markdown-table writer, `--base-ref` git-diff resolver) reused by the `scripts/quality/` checkers; stdlib + PyYAML only.
- `analyze_references.yaml` — scan-root / prompt-base / data-selector / ignore config for `scripts/analyze_references.py` (subtask 054 reference-graph analyzer).
- `check_bundle_budget.yaml` — budget config for `check_bundle_budget.py` — dist path, route-chunk regex, and the KiB-gzip budgets (entry/route/shared/total + Settings/Wizard route overrides) so a budget change is a one-line reviewable diff.
- `check_complexity.allow.yaml` — frozen size/complexity baseline for `check_complexity.py` (41 LOC-tier + 64 over-complexity offenders); regenerate with `--update-baseline`.
- `check_complexity.yaml` — thresholds for `check_complexity.py` — LOC tiers (warn>500/review>800/split>1200), ruff `C901` `max-complexity`, test exclusion, and default scan scope.
- `check_dashboard_ux.allow.yaml` — frozen raw/debug-exposure baseline for `check_dashboard_ux.py` (13 line-independent REVIEW_REQUIRED surfaces — 2 dangerous-HTML, the `{ } Raw` tab, 2 `/api/env-keys` readbacks, 8 `JSON.stringify` dumps; the i18n and route↔nav sections are empty because both are clean today); it records ownership by 070/071, never an authorization to edit a surface.
- `check_dashboard_ux.yaml` — extraction config for `check_dashboard_ux.py` — the `i18n/` dir + `en/ja/zh` locales, the five raw-pattern kinds with their scopes/regexes (`json_dump` scoped to `components/` so `services/api.ts` body serialization is not miscounted), and the `App.tsx`/`Sidebar.tsx` route↔nav targets plus the hidden-route allowlist.
- `check_dead_code.allow.yaml` — frozen `SAFE_DELETE_CANDIDATE` baseline for `check_dead_code.py` (empty at seed; only shrinks as subtask 057 deletes reviewed candidates); regenerate with `--update-baseline`.
- `check_dead_code.yaml` — classification config for `check_dead_code.py` — graph path, PUBLIC_CONTRACT / dynamic-seam / TEST_ONLY / under-traced-seam path lists, `SAFE_DELETE` eligibility (ruff-corroborated), and the `--check` budget.
- `check_directory_policy.allow.yaml` — frozen allowlist for `check_directory_policy.py`, empty at seed (every rule verified clean 2026-07-02: trio intact, no `sonfigs/` dir, no tracked artifacts) and documenting the finding-id shapes (`trio-missing:`/`trio-kind:`/`trio-marker:`/`config-collision:`/`banned-dir:`/`storage:`/`artifact:`) future entries must use.
- `check_directory_policy.yaml` — rule config for `check_directory_policy.py` — the three config-trio paths with their required kind + marker files, legal config-family names and scan parents, the banned `sonfig*` globs, the storage-family names/allowlist, and the forbidden tracked-artifact dirs/suffixes.
- `check_import_boundaries.allow.yaml` — frozen baseline of known import-boundary edges (the 7 B1 seed edges + the sanctioned core→skill edge).
- `check_import_boundaries.yaml` — rule config for `check_import_boundaries.py` (allowed skill→core roots, sanctioned core→skill package, rule toggles).
- `check_prompts.allow.yaml` — frozen inline-prompt baseline for `check_prompts.py` (23 role-marked candidates seeded from the Subtask 036 census, each tagged with its 036/011 §5.x verdict); regenerate with `--update-baseline`.
- `check_prompts.yaml` — heuristics for `check_prompts.py` — role/JSON/rubric markers, min-lines/min-chars thresholds, default scan scope, and vendored `KEEP_INLINE` excludes.
- `check_viz_api_schema.allow.yaml` — frozen baseline for `check_viz_api_schema.py` (1 known client-only F6a drift + 20 legitimately server-only routes: static/SSE/direct-URL/proxy/no-FE-consumer).
- `check_viz_api_schema.yaml` — config for `check_viz_api_schema.py` (routes.py + api.ts targets, the four get/post/pbGet/pbPost helper→method map, declarative-route toggle).
- `generate_quality_report.yaml` — checker roster for `generate_quality_report.py` — eight entries (`module_or_path`, `argv`, `json_flag`, `weight`), all `required: false` so an absent checker reports `unavailable` instead of failing the run — plus the optional per-area LOC override.
- `baselines/` — committed quality baselines the checkers consume (relocated out of the retired `docs/refactoring/` tree).
  - `053_reference_roots.json` — hand-verified reference-root record (`git_head` 2a20bd9 / `verified_date` 2026-07-01, no generator). `analyze_references` seeds reachability from R4's skill-name lists, R6's `api_modules` and R7's `submodules`, and backstops non-literal prompt loads from `dynamic_seams[].prompt_load_sites`; every other section (`mcp_tools`, `live_by_string_allow_list`, `config_triple`, `negatives`, `review_required`) is a dated census no tool reads, and its tool inventory still names tools since removed — so nothing below `static_roots`/`dynamic_seams` may be read as a live root. Full breakdown in `scripts/README.md`.
  - `dead_code_baseline.json` — frozen dead-code counts; `generate_quality_report` reports the before/after delta.
  - `hardcoded_prompt_inventory.json` — prompt census consumed by `check_prompts` (`CENSUS_JSON`).
  - `hardcoded_prompt_inventory.md` — human-readable companion of the prompt census.
  - `public_api_snapshot.json` — frozen `ari.public.*` API surface; `check_public_api_contracts` diffs against it.
  - `reference_graph.json` — the code/data reference graph (`analyze_references` output; `check_dead_code` input).
  - `reference_graph.md` — human-readable companion of the reference graph.
