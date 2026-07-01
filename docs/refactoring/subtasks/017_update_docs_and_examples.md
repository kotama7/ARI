# Subtask 017: Update Docs And Examples

> Phase 10: Docs and Tests · Risk: Low–Medium · Changes runtime code: **No** (see Section 16)

---

## 1. Goal

Reconcile the ARI documentation tree (`docs/`), the root README triples, and every
embedded example (config snippets, CLI invocations, REST/MCP tables, `from ari.*`
import snippets) with the **final** state of the code after the runtime-changing
refactor phases (config consolidation, interface/protocol extraction, registry/factory
work, prompt externalization, viz/dashboard refactor, dead-code removal). The
deliverable is a docs tree where:

1. Every `sources[].path` in doc front-matter still resolves (the hard gate
   `scripts/docs/check_doc_sources.py` stays green), with `last_verified` bumped.
2. Every inline example (import path, CLI command, config key, REST endpoint,
   directory name) reflects the post-refactor reality.
3. The `en` / `ja` / `zh` mirrors stay in lock-step (parity matrix + heading shape +
   translation freshness), and the VitePress build still succeeds.
4. Known pre-existing drift that this phase is the natural owner of is fixed
   (the dangling `docs/_archive/` references; the `~/.ari/agent.env` fallback line).

This subtask is **content reconciliation only** — it classifies as `ADAPT` on the
doc files (rewrite paths/examples in place) and `KEEP` on the documentation
*information architecture* (Diátaxis groups, i18n mirror layout, source-traceability
mechanism). It introduces no new doc pages and renames none.

## 2. Background

`docs/` is the VitePress `srcDir` (config `docs/.vitepress/config.ts`, 135 lines),
English at the tree root, `ja/` and `zh/` mirrors. Content inventory (verified
2026-07-01): **en 42 md, ja 41, zh 41** (the single gap is
`reference/internal_boundaries.md`, en-only by design — parity matrix line 126 marks
ja/zh as "—"). Diátaxis groups in sidebar order: `getting-started`, `concepts`,
`guides`, `guides/paperbench`, `reference`, `about`.

Docs are coupled to source by **two machine-checked mechanisms**, so a refactor that
moves a module makes a docs gate fail rather than leaving a silently stale doc:

- **Front-matter `sources:`** — every live doc declares repo-root-relative source
  `path:` entries + a `last_verified` date. `scripts/docs/check_doc_sources.py`
  hard-gates that every `path` exists (default run, no `--require-all`). Measured
  surface: **397 `- path:` entries across 120 docs** (en+ja+zh). This is the primary
  mechanical work of this subtask — every path a refactor moved must be re-pointed.
- **Root README triples** — `README.md` / `README.ja.md` / `README.zh.md` share one
  heading *shape* (`check_readme_parity.py`, hard gate) and embed a CLI command table
  (README.md lines ~214–318) and a REST endpoint table (lines ~284–307) that name
  live code surfaces (`ari run`, `/api/launch`, port `8765`, etc.).

Because this is Phase 10, the code has already moved by the time this subtask runs.
This subtask does **not** decide where things go — it records where they *ended up*.
See `docs/refactoring/reports/010_contract_preservation_policy.md` (the contracts
that must survive) and `007_subtask_index.md` (the subtask ledger) for the source of
truth on what changed. The `docs/README.md` "Source traceability" section (lines
200–241) is the canonical description of the gate family this subtask must keep green.

**No `examples/` directory exists in ARI itself.** A repo-wide search finds only
vendored `examples/` under `ari-skill-*/vendor/**` and `.venv/**` (out of scope) and
`ari-core/config/reviewer_rubrics/fewshot_examples/` (rubric data, not doc examples).
"Examples" in this subtask therefore means the **inline** code/config/CLI/REST
examples embedded in the markdown docs and the root READMEs, plus the fewshot rubric
example JSON only insofar as a doc path points at it. There is **no `sonfigs/`**
directory anywhere in the repo — do not add references to one.

## 3. Scope

In scope:

- All `docs/**/*.md` content files (en + ja + zh), excluding `docs/refactoring/**`
  (planning workspace, not published) and `docs/_archive/**` (already removed).
- The three root READMEs: `README.md`, `README.ja.md`, `README.zh.md`.
- Front-matter `sources[].path` re-pointing and `last_verified` bumps.
- Inline examples: `from ari.*` import snippets, `ari …` CLI commands, YAML config
  keys/blocks, REST endpoint tables, MCP tool names, directory-name references.
- The two carried-over drift items this phase owns (Section 6 items 3 and 4).
- Keeping the docs gate family (Section 12) green after the edits.

Out of scope (owned by other subtasks / phases):

- Adding, renaming, splitting, or deleting doc *pages* or Diátaxis groups. The IA is
  `KEEP`. (A page only disappears here if the source it documents was deleted by an
  earlier subtask and no replacement exists — that is a `REVIEW_REQUIRED` handoff,
  not a unilateral deletion.)
- The VitePress config/theme, i18n JS switcher dictionaries, landing `index.html`,
  `site.css`/`tokens.css`, or the report PDF pipeline — owned by the homepage/site
  effort; touch only if a refactor renamed something they reference (unlikely).
- The `report/` LaTeX tree and its tri-language co-change gate — separate build.
- Writing new doc-source checkers (`check_docs_source_sync.py` etc.) — those are
  their own subtasks (see Section 6 of the master facts); this subtask uses the
  **existing** `scripts/docs/` checkers, it does not author new ones.
- Any runtime code, prompts, configs, workflows, or frontend code.

## 4. Non-Goals

- **Not** flipping `check_doc_sources.py` to `--require-all` (the coverage gate) —
  that staged-rollout decision belongs to a quality-scripts subtask, not here.
- **Not** modifying `scripts/docs/*.py` checker logic. If a checker needs a rule
  change to accommodate a refactor, that is a handoff, not an edit in this subtask.
- **Not** editing `.github/workflows/*.yml`. The five existing workflows
  (`docs-sync.yml`, `docs-change-coupling.yml`, `pages.yml`, `readme-sync.yml`,
  `refactor-guards.yml`) are `KEEP`; this subtask must satisfy them, not rewrite them.
- **Not** using the word "deprecated" for internal module moves. Reserve it strictly
  for external contracts (public API, CLI, MCP, dashboard API, documented import
  paths). A moved-internally module is `ADAPT` in prose, never "deprecated".
- **Not** re-syncing the report PDFs (`docs/public/report/*.pdf`,
  `docs/assets/report/*.pdf`) — they are already byte-identical to
  `report/{lang}/main.pdf` and gated by `sync_report_pdf.sh --check`; leave them.
- **Not** touching translations to "improve" them — only mirror the same structural
  and path edits made to the English source, per the docs co-change rule.

## 5. Current Files / Directories to Inspect

Doc trees (content to reconcile):

| Path | What lives here | Notes |
| --- | --- | --- |
| `docs/getting-started/` | `index, quickstart, first_experiment_tutorial, faq` (+README) | Tutorial; heaviest CLI/example content |
| `docs/concepts/` | `PHILOSOPHY, architecture, bfts, memory, verifiable_research_memory, publication-lifecycle` (+README) | Explanation; `architecture.md` names module layout |
| `docs/guides/` | `hpc_setup, extension_guide, experiment_file, cookbook, migration, testing, troubleshooting` (+README) | How-to; `cookbook.md` + `experiment_file.md` carry YAML examples |
| `docs/guides/paperbench/` | `paperbench_quickstart, paperbench_gui, paper_import, multi_node_setup, compute_node_safety, paperbench_troubleshooting` (+README) | PaperBench how-to |
| `docs/reference/` | 15 md incl. `cli_reference, configuration, environment_variables, file_formats, internal_boundaries, mcp_tools, public_api, registry, rest_api, rubric_schema, skills, api_paperbench, execution_profile, glossary` (+README) | Reference; **most path-coupled** — richest `sources:` blocks |
| `docs/about/` | `index, compatibility, release_policy` (+README) | Project meta |
| `docs/ja/**`, `docs/zh/**` | Mirrors of all the above **except** `reference/internal_boundaries.md` | 41 md each; no `README.md`, no section `index.md` |

Front-matter / example anchors (verified):

| Path | Why inspect |
| --- | --- |
| `docs/reference/cli_reference.md` | `sources:` → `ari-core/ari/cli`, `ari-core/ari/memory_cli.py`, `ari-core/ari/cli_ear.py`; CLI command table |
| `docs/reference/configuration.md` | `sources:` → `ari-core/config/workflow.yaml`, `ari-core/ari/config/__init__.py`, `ari-core/ari/configs`, `ari-core/ari/viz/api_settings.py`; config-precedence prose (mentions the `config`/`configs` split — high refactor-risk) |
| `docs/reference/public_api.md` | Documents `ari.public.*`; carries `from ari.public...` snippets |
| `docs/reference/rest_api.md` | REST endpoint list; couples to `ari/viz/routes.py` + `api_*.py`; port `8765` |
| `docs/reference/mcp_tools.md`, `docs/reference/skills.md` | MCP tool names + `ari-skill-*/src/server.py` paths |
| `docs/reference/internal_boundaries.md` | en-only; documents import boundaries → highest sensitivity to module moves |
| `docs/reference/file_formats.md` | Checkpoint/config file formats; couples to `ari/checkpoint.py`, `ari/paths.py` |
| `docs/guides/cookbook.md` | `sources:` → `ari-core/config/profiles`, `config/workflow.yaml`, `ari/evaluator/llm_evaluator.py`, `ari/orchestrator/bfts.py`; ships `laptop/hpc/cloud` YAML profile examples |
| `docs/guides/experiment_file.md` | `sources:` → `ari-core/ari/pipeline/experiment_md.py`, `ari-skill-evaluator`; `experiment.md` example |
| `docs/guides/extension_guide.md`, `docs/guides/migration.md` | Carry `from ari` import snippets and path references |
| `docs/reference/rubric_schema.md`, `docs/guides/paperbench/compute_node_safety.md`, `.../paperbench_troubleshooting.md` | Carry `from ari` / path snippets (grep-confirmed) |

Coupling drivers and gates (inspect, do not edit the checkers):

| Path | Role |
| --- | --- |
| `docs/README.md` (242 lines) | Diátaxis index + authoritative translation-parity matrix; **carries the 4 dangling `_archive` references** (lines 5, 20, 86, 135) |
| `README.md` / `README.ja.md` / `README.zh.md` | Root triples: CLI table (~214–318), REST table (~284–307), port 8765 |
| `scripts/docs/check_doc_sources.py` (7,665 B) | Hard gate: every `sources[].path` exists; exempts `_archive`/`node_modules`/`.vitepress`; `--require-all` = coverage (off by default) |
| `scripts/docs/check_readme_parity.py` | Hard gate: root README heading-shape parity |
| `scripts/docs/check_doc_links.py` | `--html-only` hard gate; markdown-link mode **advisory** (this is why the `_archive` links drift silently) |
| `scripts/docs/check_translation_freshness.py` | Advisory: ja/zh `last_verified` not behind en |
| `scripts/docs/check_ref_coupling.py` | Advisory (diff-based): changed source → bump the doc's `last_verified` |
| `.github/workflows/docs-sync.yml` | Runs the full-tree hard gates + `vitepress-build` |
| `.github/workflows/docs-change-coupling.yml` | Runs diff-based co-change/coupling checks |
| `docs/refactoring/reports/010_contract_preservation_policy.md` | Contracts the doc examples must keep describing accurately |

## 6. Current Problems

1. **Path-coupling breaks the moment a refactor moves a module.** 397 `sources[].path`
   entries across 120 docs point at concrete files (e.g. `ari-core/ari/config/__init__.py`,
   `ari-core/ari/orchestrator/bfts.py`, `ari-core/ari/publish`, `ari-core/ari/registry`).
   `check_doc_sources.py` is a **hard gate** — any subtask in Phases 3–9 that renamed or
   relocated one of these files will have left the docs gate red, and this subtask is
   where those are re-pointed. There is no auto-rewrite; it is manual, per-path,
   times three languages.

2. **Inline examples drift invisibly.** Import snippets (`from ari.*` confirmed in
   `reference/public_api.md`, `reference/rubric_schema.md`, `reference/skills.md`,
   `guides/extension_guide.md`, `guides/migration.md`, `guides/paperbench/*`), CLI
   commands, and YAML config keys are **not** covered by `check_doc_sources` (it only
   validates `sources:` front-matter, not fenced code). A refactor that renamed
   `ari.config`→something, split `_load_backend`, or moved a CLI subcommand would leave
   these examples wrong with **no failing gate** — they must be reconciled by reading.

3. **Dangling `docs/_archive/` references (carried-over drift, confirmed).**
   `docs/_archive/` was removed in a prior "plan-deletion" commit (verified:
   `ls docs/_archive` → No such file; `git ls-files docs | grep _archive` → empty).
   `docs/README.md` still links it in **4 places** (lines 5, 20, 86 `[Refactor
   audit](_archive/refactor_audit.md)`, and parity-matrix row 135 for en/ja/zh). The
   hard gates stay green because `check_doc_sources` exempts `_archive` and
   `check_doc_links` markdown mode is **advisory** — so this is silent drift. This
   subtask is the natural owner: classify the archive row as `DELETE_CANDIDATE` (remove
   the dead links + the "Archive" section + the naming-convention `_archive` mention).

4. **`~/.ari/agent.env` fallback line (potential contradiction, `REVIEW_REQUIRED`).**
   `docs/reference/environment_variables.md:211` states `ARI_AGENT_ENV_PATH` "Falls
   back to `~/.ari/agent.env`", while the **same file** (line 19), `guides/migration.md`,
   and `concepts/architecture.md:541` state `$HOME/.ari/` was **removed in v0.5.0**.
   Whether code still falls back is **unconfirmed** against
   `ari-core/ari/config/__init__.py` / `paths.py`. Do not blindly delete: verify against
   the (post-refactor) code, then either correct the prose or, if the fallback truly
   still exists, reconcile the "removed in v0.5.0" claims. Mirror the fix to ja/zh.

5. **Translation lock-step is a gate, not a nicety.** Any en edit must land in ja+zh in
   the same change with all three `last_verified` bumped, or
   `check_translation_freshness` (advisory) flags staleness and
   `check_readme_parity` (hard) fails if a README heading-shape diverges. A partial
   update is worse than none.

6. **VitePress build is a hard gate.** `docs-sync.yml` runs `npm ci --prefix docs` +
   `npm run --prefix docs docs:build`. A broken intra-doc link introduced while
   re-pointing examples, or a malformed front-matter block, can fail the build even
   though the markdown-link checker is only advisory.

## 7. Proposed Design / Policy

**Classification:** `ADAPT` the doc *content*; `KEEP` the doc IA and the
source-traceability mechanism; `DELETE_CANDIDATE` only the dead `_archive` links.

### 7.1 Drive the update from the code, not from guesses

Treat the completed refactor's change-log as the worklist. For every subtask in
Phases 2–9 that moved/renamed a file, changed a CLI subcommand, altered a config key,
changed a REST endpoint, changed an MCP tool name, or removed a module, derive the
before→after mapping and apply it to docs. The `007_subtask_index.md` ledger and each
subtask's own "Files Expected to Change" section are the authoritative mapping source.

### 7.2 Front-matter `sources:` — mechanical, verifiable

1. Run `python scripts/docs/check_doc_sources.py` to get the exact list of
   now-missing paths (hard-gate failures). This is the objective worklist.
2. For each failing `path`, locate the file's new home (git history / the subtask
   ledger) and update the `path`. If a source was **deleted** with no replacement,
   the doc content it backed is likely stale too → escalate as `REVIEW_REQUIRED`
   (do not just drop the `sources` entry to silence the gate).
3. Bump `last_verified` on every edited doc to the edit date, in **en + ja + zh**.
4. Re-run the checker until zero errors.

### 7.3 Inline examples — read, don't grep-and-replace blindly

- **Imports:** confirm each `from ari.*` snippet still imports something real against
  the post-refactor `ari.public.*` surface and internal modules. Public API snippets
  must resolve through `ari.public` (the stable surface), not a moved internal path.
- **CLI:** every `ari <subcommand>` in `reference/cli_reference.md` and the root README
  CLI table must match the post-refactor `ari.cli:app` command set.
- **REST:** every endpoint in `reference/rest_api.md` and the root README REST table
  must resolve to a route in `ari/viz/routes.py` / `api_*.py`; keep port **8765**.
- **MCP:** tool names in `reference/mcp_tools.md` / `skills.md` must match the
  `ari-skill-*/src/server.py` tool contracts.
- **Config:** YAML keys/blocks in `cookbook.md`, `configuration.md`, `experiment_file.md`
  must match the post-refactor config schema and the `config/` (code) vs `configs/`
  (packaged defaults) vs top-level `config/` (rubric data) split. Never introduce
  `sonfigs/` — it does not exist.

### 7.4 Carried-over drift

- **`_archive` (`DELETE_CANDIDATE`):** remove the 4 dead references in `docs/README.md`
  (the naming-convention row, the "Archive" TOC section, the parity-matrix `_archive`
  row). This also clears the advisory `check_doc_links` markdown finding.
- **`~/.ari/agent.env` (`REVIEW_REQUIRED`):** verify against code first (Section 6.4),
  then correct whichever side is wrong, mirrored to ja/zh.

### 7.5 Preserve every checked invariant

Do not create work for the gates: keep the parity matrix (`docs/README.md`) accurate,
keep en/ja/zh in lock-step, keep heading shapes identical across the README triple,
keep the `internal_boundaries.md` en-only exception, and leave the report PDFs and the
i18n JS switcher alone.

## 8. Concrete Work Items

1. **Baseline the gates.** From repo root run `check_doc_sources.py`,
   `check_readme_parity.py`, `check_doc_links.py --html-only`,
   `check_doc_links.py` (advisory), `check_translation_freshness.py`, and the
   VitePress build; capture the pre-edit failure/warning set as the worklist.
2. **Re-point front-matter `sources`.** For every hard-gate `path` failure, update the
   `path` to the module's new location in en + ja + zh; bump `last_verified`.
   Escalate deleted-with-no-replacement sources as `REVIEW_REQUIRED`.
3. **Reconcile inline imports.** Read every `from ari.*` snippet (public_api,
   rubric_schema, skills, extension_guide, migration, paperbench/*) and correct to the
   post-refactor surface; prefer `ari.public.*` for public examples.
4. **Reconcile CLI examples.** Align `reference/cli_reference.md` command table and the
   root README CLI table (README.md ~214–318 + triples) to the post-refactor
   `ari.cli:app` subcommands.
5. **Reconcile REST examples.** Align `reference/rest_api.md` and the root README REST
   table (~284–307) to the post-refactor `ari/viz/` routes; keep port 8765.
6. **Reconcile config/YAML examples.** Update `cookbook.md`, `configuration.md`,
   `experiment_file.md` (and ja/zh) to the post-refactor config layout; verify the
   `config`/`configs`/top-level `config` distinction is described correctly; ensure no
   `sonfigs`.
7. **Fix the `_archive` drift.** Remove the 4 dead references in `docs/README.md`
   (Section 6.3) and confirm advisory markdown-link check no longer reports them.
8. **Resolve the `~/.ari/agent.env` line.** Verify against code; correct prose in
   `reference/environment_variables.md` (+ja/zh) accordingly.
9. **Mirror everything to ja/zh** in the same change; bump all three `last_verified`.
10. **Re-run all gates to green** (Section 12); confirm the VitePress build passes.
11. **Update per-directory `docs/**/README.md`** only where a refactor changed what a
    group documents (these are `## Contents` indexes gated by `readme-sync.yml`).

## 9. Files Expected to Change

Documentation content (this is a docs-only subtask; **no runtime code**):

- `docs/**/*.md` — any file whose `sources[].path` moved or whose inline examples
  drifted, in **en + ja + zh** (up to 42 en + 41 ja + 41 zh = 124 files; realistically
  a subset driven by the gate worklist). Excludes `docs/refactoring/**`.
- `docs/README.md` — remove the 4 dangling `_archive` references (lines 5, 20, 86, 135).
- `docs/reference/environment_variables.md` (+`docs/ja/…`, `docs/zh/…`) — the
  `~/.ari/agent.env` reconciliation.
- `README.md`, `README.ja.md`, `README.zh.md` — CLI table + REST table + directory/path
  mentions, kept heading-shape-parallel.
- `docs/**/README.md` (per-directory `## Contents` indexes) — only where group content
  descriptions changed.

Explicitly **not** changed by this subtask (inspect only):
`scripts/docs/*.py` (the checkers), `.github/workflows/*.yml`, `docs/.vitepress/**`,
`docs/index.html` / `site.css` / `tokens.css` / `i18n/**`, `docs/public/report/*.pdf`,
`docs/assets/report/*.pdf`, `report/**`, and all `ari-core/` / `ari-skill-*/` runtime
code, prompts, configs, and frontend.

## 10. Files / APIs That Must Not Be Broken

This subtask does not change contracts; it **describes** them, so the docs must
continue to describe them accurately:

- **CLI:** the `ari` console script and its subcommands (`ari.cli:app`). Doc CLI tables
  must match the real command set, no invented commands.
- **Public API:** `ari.public.*` (`claim_gate`, `config_schema`, `container`,
  `cost_tracker`, `llm`, `paths`, `run_env`, `verified_context`). Import snippets in
  `reference/public_api.md` must resolve through this surface.
- **MCP:** the 14 `ari-skill-*` tool contracts documented in `reference/mcp_tools.md` /
  `skills.md`.
- **Dashboard API:** the REST endpoints in `reference/rest_api.md` and the root README
  table (`/api/*`, `/state`, `/memory/*`), port 8765.
- **Checkpoint / config file formats:** `reference/file_formats.md`,
  `reference/configuration.md` must match `ari/checkpoint.py` and the config schema.
- **Docs-gate contracts:** the front-matter `sources:` schema, the `docs/README.md`
  parity matrix, the README heading-shape parity, the report-PDF sync — all must stay
  satisfied. The en-only status of `reference/internal_boundaries.md` must be preserved
  (do not add ja/zh mirrors of it).

## 11. Compatibility Constraints

- **Front-matter schema is fixed.** Keep the `sources:` list-of-mappings shape with
  `path` (repo-root-relative, posix) and optional `role` ∈
  {implementation, schema, config, prompt, test, vendor, doc}. Bump `last_verified`;
  do not remove the block to silence a gate.
- **Tri-language lock-step.** Every en edit lands in ja + zh in the same change; keep
  the parity matrix and heading shapes identical (hard gate `check_readme_parity`).
- **`internal_boundaries.md` stays en-only** (parity-matrix row 126 "—"; VitePress
  `srcExclude` + `readme_sync` skip already account for it).
- **No new pages, no group renames.** IA is `KEEP`; a page is only removed if its sole
  source was deleted upstream — and that is a `REVIEW_REQUIRED` escalation, not a
  silent delete.
- **No checker or workflow edits.** Satisfy `scripts/docs/*` and
  `.github/workflows/docs-*.yml` as-is.
- **"deprecated" is reserved for external contracts.** Describe internal module moves
  as relocations, not deprecations.
- **Do not touch report PDFs or the i18n JS switcher**; leaving them avoids the
  `sync_report_pdf.sh --check` and `check_site_i18n` gates.

## 12. Tests to Run

Repo-wide sanity (docs-only change, but run anyway per template):

- `python -m compileall .` — byte-compile sanity (should be unaffected; confirms no
  stray edit into a `.py`).
- `pytest -q` — full suite (docs edits should not change results; a green run confirms
  no accidental non-doc edit).
- `ruff check .` — lint (`ruff` **is** available; `radon` is **not** installed).

Docs-specific gates (the ones that actually validate this subtask — run from repo root):

- `python scripts/docs/check_doc_sources.py` — **must be 0 errors** (primary gate).
- `python scripts/docs/check_readme_parity.py` — root README heading parity (hard).
- `python scripts/docs/check_doc_links.py --html-only` — HTML href integrity (hard).
- `python scripts/docs/check_doc_links.py` — markdown links (advisory; verify the
  `_archive` findings are **gone** after Work Item 7).
- `python scripts/docs/check_translation_freshness.py` — ja/zh not behind en (advisory;
  should be clean after `last_verified` bumps).
- `python scripts/docs/check_i18n_js.py` and `python scripts/docs/check_site_i18n.py` —
  should be untouched (no i18n JS / landing edits).
- Report co-change / PDF sync (`check_report_cochange.py`, `sync_report_pdf.sh --check`)
  — should be untouched.

Frontend (VitePress) build — this **is** a hard gate for docs:

- `npm ci --prefix docs` then `npm run --prefix docs docs:build` — the VitePress build
  must succeed (mirrors the `vitepress-build` job in `docs-sync.yml`). Note: docs use
  **npm** (there is a `docs/package-lock.json`); there is **no pnpm**.

## 13. Acceptance Criteria

- `python scripts/docs/check_doc_sources.py` reports **0 errors** — every
  `sources[].path` in every doc (en+ja+zh) resolves against the post-refactor tree.
- `check_readme_parity.py` and `check_doc_links.py --html-only` pass; the advisory
  markdown-link check no longer reports the `_archive/refactor_audit.md` links.
- The 4 dangling `_archive` references in `docs/README.md` are removed; the parity
  matrix contains no `_archive` row.
- `reference/environment_variables.md` no longer contradicts itself about
  `~/.ari/agent.env` (verified against code), mirrored to ja/zh.
- No inline `from ari.*` import, `ari` CLI command, REST endpoint, MCP tool name, or
  config key in the docs references a moved/renamed/removed surface without being
  updated; spot-check confirms examples run/resolve against the post-refactor code.
- All edited docs have `last_verified` bumped in en + ja + zh; translation-freshness is
  clean.
- `npm run --prefix docs docs:build` succeeds; `pytest -q`, `python -m compileall .`,
  and `ruff check .` pass.
- No file outside `docs/**` (except the three root READMEs) is modified.

## 14. Rollback Plan

- Pure docs/markdown change with no schema/format/runtime impact: a single
  `git revert` of the subtask commit restores the prior docs verbatim. There is no
  on-disk state, migration, or generated artifact to unwind.
- Because `check_doc_sources` is a hard gate, a *partial* revert that re-introduces a
  moved path would fail CI immediately — so revert whole, not per-file, unless
  re-running the checker confirms the subset is self-consistent.
- Keep the commit split into logical units (front-matter re-pointing / inline examples
  / `_archive` cleanup / `~/.ari` fix / README triples) so any single unit can be
  reverted without disturbing the others. Each unit must independently pass
  `check_doc_sources` + `check_readme_parity` before it is considered landable.

## 15. Dependencies

Per the master dependency graph, **017 has no explicit predecessor edge** — it is a
terminal Phase-10 "docs reconciliation" leaf. Its real dependency is *logical*: it
documents the **end state** of the code, so it must run **after** every subtask that
renamed/moved a module, changed the CLI, changed the config layout, altered a REST or
MCP contract, externalized prompts, or removed a module. Running 017 before those land
would just re-break `check_doc_sources`.

- **Inventory gate (must precede any runtime-code change, and therefore precede the
  refactors this subtask documents): 001, 002, 020, 036, 045, 053, 059, 060, 067.**
  These are already complete by Phase 10.
- **Most directly reflected in docs (schedule 017 after these clusters):**
  - **003** (config consolidation) → `configuration.md`, `cookbook.md`, `file_formats.md`
    (the `config`/`configs` split prose). 003 also fans out to 027, 028.
  - **007** (core interfaces/protocols) → `internal_boundaries.md`, `public_api.md`;
    007 fans out to 008–014 (incl. **014** registry/factory, whose moves touch
    `reference/registry.md` and any `ari.publish`/`ari.registry` snippets).
  - **020**-cluster (021–024, 030), **036**-cluster (037–044), **045**-cluster
    (046–052) — whatever these rename/move surfaces in `sources[].path`.
  - **053 → 054 → 055 → 056 → 057 → 058** (reference-root inventory → dead-code
    deletion chain): if 057 deletes a module a doc documents, 017 owns the follow-up
    (re-point or `REVIEW_REQUIRED` page removal).
  - **059**-cluster (060–073) — viz/dashboard + docs/site tooling; any REST route or
    `ari/viz/` path change flows into `rest_api.md` and the README REST table.
- **Adjacent, not blocking:** the companion Phase-10 test subtask(s) — coordinate so a
  doc example and its backing test describe the same post-refactor surface.

Net: gate 017 on completion of all runtime-changing subtasks in Phases 2–9 (the
inventory gate plus the 003/007/020/036/045/053-chain/059 clusters). It should be one
of the **last** subtasks executed.

## 16. Risk Level

**Low–Medium.** **Changes runtime code: No.**

Rationale: this subtask edits only markdown (`docs/**` + the three root READMEs). It
cannot break the running system — `import ari`, the CLI, the dashboard, and the MCP
servers are untouched. The residual risk is (a) leaving a `sources[].path` unfixed and
failing the hard `check_doc_sources` gate, (b) breaking the VitePress build with a
malformed link/front-matter, or (c) desyncing the en/ja/zh mirror and failing
`check_readme_parity`. All three are caught by the Section 12 gates before merge, which
is why "re-run every docs gate to green" is a hard acceptance criterion. The one place
to slow down is item 4 (`~/.ari/agent.env`), which requires reading the post-refactor
code before editing prose — get that verification wrong and the docs stay contradictory.

## 17. Notes for Implementer

- **Let the gate write your worklist.** Run `python scripts/docs/check_doc_sources.py`
  first; its error list *is* the front-matter worklist. Do not hand-scan 397 paths.
- **`check_doc_sources` only validates front-matter `sources:`, not fenced code.** The
  inline `from ari.*` / `ari …` / YAML examples have **no gate** — the only defense is
  reading them against the post-refactor code. Grep for `from ari` (confirmed in
  `public_api.md`, `rubric_schema.md`, `skills.md`, `extension_guide.md`,
  `migration.md`, `guides/paperbench/compute_node_safety.md`,
  `guides/paperbench/paperbench_troubleshooting.md`, plus ja/zh mirrors).
- **The confusable config trio is a live trap in `configuration.md`.**
  `ari-core/ari/config/` = Python code (locates config files);
  `ari-core/ari/configs/` = packaged data (`defaults.yaml`, `model_prices.yaml`,
  `_loader.py`); top-level `ari-core/config/` = rubric/profile data
  (`default.yaml`, `profiles/`, `paperbench_rubrics/`, `reviewer_rubrics/`). Make sure
  the docs describe the *post-refactor* arrangement of these three. **There is no
  `sonfigs/`** anywhere — never introduce it.
- **`docs/_archive/` is gone; its references are silent drift.** Remove all 4 in
  `docs/README.md` (naming-convention row line 20, prose line 5, TOC line 86, parity row
  135). Gates stayed green because `_archive` is exempt in `check_doc_sources` and
  markdown-link checking is advisory — do not assume "green CI" meant "no drift".
- **`~/.ari/agent.env` (`env vars` line 211): verify before editing.** The same file
  (line 19), `guides/migration.md`, and `concepts/architecture.md:541` say `$HOME/.ari/`
  was removed in v0.5.0. Read the post-refactor `ari-core/ari/config/__init__.py` /
  `paths.py` to learn whether the fallback still exists, then correct the wrong side.
  Do not delete the line on assumption.
- **Tri-language or nothing.** Every en edit → ja + zh in the same commit, all three
  `last_verified` bumped. `internal_boundaries.md` is the one intentional en-only doc —
  do **not** create ja/zh mirrors for it (that would break the parity matrix, not fix it).
- **Public examples go through `ari.public.*`.** When re-pointing an import snippet in
  `public_api.md`, prefer the stable `ari.public` surface over a moved internal path so
  the example stays valid across future internal moves.
- **Docs use npm, not pnpm.** Build with `npm ci --prefix docs` +
  `npm run --prefix docs docs:build`. `radon` is not installed; `ruff` is.
- **`docs/refactoring/**` is a planning workspace, not published** (not a VitePress
  sidebar group). Do not add `sources:` front-matter to files there and do not treat
  them as content. Note: `check_doc_sources` `rglob`s all of `docs/`, so under the
  (currently-off) `--require-all` flag these planning files would be flagged as
  coverage gaps — that is a `REVIEW_REQUIRED` note for whoever eventually flips that
  flag, **not** this subtask's problem to fix.

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **017** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
