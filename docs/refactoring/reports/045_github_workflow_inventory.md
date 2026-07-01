# 045 — GitHub Workflow Inventory (frozen baseline)

> **Read-only inventory artifact** produced by subtask
> `docs/refactoring/subtasks/045_inventory_github_workflows.md`. It changes no
> runtime code, no workflow YAML, and no script. It is the frozen CI/CD baseline
> that Phase-9 subtasks **046–052** build on.
>
> Repo: `/home/t-kotama/workplace/ARI` · branch `whole_refactoring` · verified
> **2026-07-01** against the working tree with `find` / `wc` / `grep` / `test -e`.
> Every claim below is grounded in a `file:line` citation; absent paths are
> written "does not exist" (never invented).

## 0. Verification recipe (regenerable)

This artifact is regenerable from the tree with a read-only recipe (no script was
added; nothing is wired into any workflow):

```
find .github -type f | sort                       # enumerate the CI surface
wc -l .github/workflows/*.yml                      # line counts
wc -c .github/workflows/*.yml                      # byte sizes
grep -nE "^\s*':!" .github/workflows/refactor-guards.yml   # ~/.ari allow-list
grep -nE "\-\-ignore=" .github/workflows/refactor-guards.yml # ignored tests
for f in <12 script paths §3>; do test -e "$f" && echo yes || echo no; done
```

Result on the verification date: `.github/` contains **only** `workflows/`, with
**exactly five** files (confirmed by `find .github -type f`; the count was not
assumed). Total **346** lines / **14 532** bytes across the five files.

## 1. Workflow summary table

All five workflows read end to end. Line/byte counts are `wc -l` / `wc -c`.

| Workflow | Lines | Bytes | Trigger(s) | Branch/path filters | Jobs | Runner | Python | Node | `fetch-depth` | `permissions` | `concurrency` |
| --- | ---: | ---: | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `refactor-guards.yml` | 105 | 4565 | `pull_request` | branches: `main`, `refactoring` | `no-home-ari-writes`, `no-new-home-ari-refs` | `ubuntu-latest` (both) | 3.13 (job 1 only) | — | `0` (both jobs) | (none) | (none) |
| `docs-sync.yml` | 91 | 4335 | `pull_request` | branches: `main` | `docs-sync`, `vitepress-build` | `ubuntu-latest` (both) | 3.13 (`docs-sync`) | 20 (`vitepress-build`) | `0` (`docs-sync` only) | (none) | (none) |
| `pages.yml` | 64 | 2047 | `push` + `workflow_dispatch` | push branches: `[main]`; paths: `['docs/**','report/**','README.md']` | `build`, `deploy` | `ubuntu-latest` (both) | — | 20 (`build`) | (default; unset) | `contents: read`, `pages: write`, `id-token: write` | `group: pages`, `cancel-in-progress: false` |
| `docs-change-coupling.yml` | 58 | 2648 | `pull_request` | branches: `main` | `change-coupling` | `ubuntu-latest` | 3.13 | — | `0` | (none) | (none) |
| `readme-sync.yml` | 28 | 937 | `pull_request` | branches: `main` | `contents-in-sync` | `ubuntu-latest` | 3.13 | — | (default; unset) | (none) | (none) |

**Totals:** 5 files · 346 lines · 14 532 bytes. Byte sizes match subtask §13
exactly (4565 / 4335 / 2047 / 2648 / 937). Only `pages.yml` is push-triggered and
the only deploy workflow; all other gating is PR-time to `main`; only
`refactor-guards.yml` also targets the `refactoring` branch.

## 2. Per-workflow step-by-step command list

Hard gate = fails the PR. Advisory = `continue-on-error: true` (non-blocking).

### 2.1 `refactor-guards.yml` (KEEP)

Header (`:1-8`) documents the two guards. Trigger `:12-16` = `pull_request` →
`main` and `refactoring`.

**Job `no-home-ari-writes`** (`:19`, `runs-on: ubuntu-latest`):
- `:22` `uses: actions/checkout@v4` with `fetch-depth: 0` (`:24`).
- `:25-28` `uses: actions/setup-python@v5`, `python-version: "3.13"`.
- `:29-47` **run** "Install dependencies": `python -m pip install --upgrade pip`;
  `pip install -r requirements.txt`; `pip install -e ari-skill-memory`;
  `pip install -e ari-core`; `pip install scipy numpy pandas`;
  `pip install pytest pytest-asyncio pytest-mock respx`.
- `:48-65` **run (HARD)** "Run tests under a redirected HOME":
  `export HOME="$RUNNER_TEMP/fake_home"` → `mkdir -p "$HOME"` →
  `pytest ari-core/tests/ -q` with 4 `--ignore` flags (see §5) →
  fails if `$HOME/.ari` exists after the run (`:61-65`, `exit 1`).

**Job `no-new-home-ari-refs`** (`:67`, `runs-on: ubuntu-latest`):
- `:70` `uses: actions/checkout@v4` with `fetch-depth: 0` (`:72`).
- `:73-105` **run (HARD)** "Detect new ~/.ari references in core":
  `base="$(git merge-base origin/${{ github.base_ref || 'main' }} HEAD)"` (`:82`)
  → `git diff "$base" HEAD -- 'ari-core/ari/**.py'` with 13 `:!` path excludes
  (§5) → grep for added lines matching `Path\.home\(\).*\.ari|~/\.ari`, excluding
  `+++ ` headers and comment lines → `exit 1` if any match (`:101-105`).
- No `setup-python`; no Node; no PyYAML. Uses the `origin/<base_ref>` merge-base
  idiom (§6, **REVIEW_REQUIRED**).

### 2.2 `docs-sync.yml` (KEEP; ADAPT target for 050)

Header `:1-29`. Trigger `:33-36` = `pull_request` → `main`.

**Job `docs-sync`** (`:39`, `ubuntu-latest`):
- `:42-44` `actions/checkout@v4`, `fetch-depth: 0`.
- `:45-48` `actions/setup-python@v5`, `3.13`.
- `:49-50` run: `python -m pip install --upgrade pip pyyaml`.
- **HARD gates** (each a `run:`):
  - `:53-54` `python scripts/docs/check_doc_sources.py`
  - `:55-56` `python scripts/docs/check_i18n_js.py`
  - `:57-58` `python scripts/docs/check_site_i18n.py`
  - `:59-60` `python scripts/docs/check_doc_links.py --html-only`
  - `:61-62` `python scripts/docs/check_readme_parity.py`
  - `:63-64` `python report/scripts/check_i18n.py`
- **ADVISORY** (`continue-on-error: true`):
  - `:67-69` `python scripts/docs/check_translation_freshness.py`
  - `:70-72` `python scripts/docs/check_doc_links.py` (markdown mode)

**Job `vitepress-build`** (`:77`, `ubuntu-latest`):
- `:80` `actions/checkout@v4` (no `fetch-depth`).
- `:81-85` `actions/setup-node@v4`, `node-version: 20`, `cache: npm`,
  `cache-dependency-path: docs/package-lock.json`.
- `:86-87` **HARD** `bash scripts/docs/sync_report_pdf.sh --check`
- `:88-89` **HARD** `npm ci --prefix docs`
- `:90-91` **HARD** `npm run --prefix docs docs:build`

### 2.3 `pages.yml` (KEEP)

Header `:1-16` (includes self-documented rollback at `:13-16`). Trigger
`:18-22` = `push` → `[main]` with `paths: ['docs/**','report/**','README.md']`
plus `workflow_dispatch`. `permissions` `:24-27`; `concurrency` `:29-31`.

**Job `build`** (`:34`, `ubuntu-latest`):
- `:37` `actions/checkout@v4`.
- `:38-42` `actions/setup-node@v4`, `node 20`, `cache: npm`,
  `cache-dependency-path: docs/package-lock.json`.
- `:43-44` run `bash scripts/docs/sync_report_pdf.sh` (note: **no** `--check` —
  actually syncs).
- `:45-46` run `npm ci --prefix docs`.
- `:47-48` run `npm run --prefix docs docs:build`.
- `:49-50` run `bash scripts/docs/assemble_site.sh`.
- `:51` `uses: actions/configure-pages@v5`.
- `:52-54` `uses: actions/upload-pages-artifact@v3`, `path: _site`.

**Job `deploy`** (`:56`, `needs: build`, `ubuntu-latest`):
- `:58-60` `environment: github-pages`.
- `:63-64` `uses: actions/deploy-pages@v4` (the only deploy action in the repo).

`pages.yml:21` path filter names `README.md` only, not `README.ja.md` /
`README.zh.md` (§6, **REVIEW_REQUIRED**).

### 2.4 `docs-change-coupling.yml` (KEEP; canonical `base.sha` idiom)

Header `:1-19`. In-tree critique of `origin/<base_ref>` at `:41-47`. Trigger
`:22-25` = `pull_request` → `main`.

**Job `change-coupling`** (`:28`, `ubuntu-latest`):
- `:31-33` `actions/checkout@v4`, `fetch-depth: 0`.
- `:34-37` `actions/setup-python@v5`, `3.13`.
- `:38-39` run `python -m pip install --upgrade pip pyyaml`.
- `:48-51` **HARD** `python scripts/docs/check_report_cochange.py --base-ref "${{ github.event.pull_request.base.sha }}"`.
- `:54-58` **ADVISORY** (`continue-on-error: true`)
  `python scripts/docs/check_ref_coupling.py --base-ref "${{ github.event.pull_request.base.sha }}"`.

### 2.5 `readme-sync.yml` (KEEP)

Header `:1-9`. Trigger `:13-16` = `pull_request` → `main`.

**Job `contents-in-sync`** (`:19`, `ubuntu-latest`):
- `:22` `actions/checkout@v4` (no `fetch-depth`).
- `:23-26` `actions/setup-python@v5`, `3.13` (stdlib-only; no PyYAML install).
- `:27-28` **HARD** `python scripts/readme_sync.py --check`.

## 3. Script-invocation map (workflow → script → exists)

All 12 targets confirmed present via `test -e` on 2026-07-01.

| Script (repo-relative) | Invoked by | Mode | Exists |
| --- | --- | --- | --- |
| `scripts/docs/check_report_cochange.py` | `docs-change-coupling.yml:50` | Hard | **yes** |
| `scripts/docs/check_ref_coupling.py` | `docs-change-coupling.yml:57` | Advisory | **yes** |
| `scripts/docs/check_doc_sources.py` | `docs-sync.yml:54` | Hard | **yes** |
| `scripts/docs/check_i18n_js.py` | `docs-sync.yml:56` | Hard | **yes** |
| `scripts/docs/check_site_i18n.py` | `docs-sync.yml:58` | Hard | **yes** |
| `scripts/docs/check_doc_links.py` | `docs-sync.yml:60` (`--html-only`, Hard) & `:72` (markdown, Advisory) | Hard + Advisory | **yes** |
| `scripts/docs/check_readme_parity.py` | `docs-sync.yml:62` | Hard | **yes** |
| `scripts/docs/check_translation_freshness.py` | `docs-sync.yml:69` | Advisory | **yes** |
| `scripts/docs/sync_report_pdf.sh` | `docs-sync.yml:87` (`--check`, Hard) & `pages.yml:44` (sync, Hard) | Hard | **yes** |
| `scripts/docs/assemble_site.sh` | `pages.yml:50` | Hard | **yes** |
| `report/scripts/check_i18n.py` | `docs-sync.yml:64` | Hard | **yes** |
| `scripts/readme_sync.py` | `readme-sync.yml:28` (`--check`) | Hard | **yes** |

12/12 present. These are a documented contract (a workflow calls each by exact
path); §10 forbids renaming/moving them.

## 4. Action-pin table

Six marketplace actions, each pinned to a major-version tag.

| Action | Pin | Used by (job) |
| --- | --- | --- |
| `actions/checkout` | `@v4` | `refactor-guards` (both jobs), `docs-sync` (both jobs), `pages/build`, `docs-change-coupling`, `readme-sync` — all 5 workflows |
| `actions/setup-python` | `@v5` | `refactor-guards/no-home-ari-writes`, `docs-sync/docs-sync`, `docs-change-coupling`, `readme-sync` (4 workflows) |
| `actions/setup-node` | `@v4` | `docs-sync/vitepress-build`, `pages/build` (2 workflows) |
| `actions/configure-pages` | `@v5` | `pages/build` |
| `actions/upload-pages-artifact` | `@v3` | `pages/build` |
| `actions/deploy-pages` | `@v4` | `pages/deploy` |

No SHA-pinned actions, no local composite actions (`.github/actions/` does not
exist — §7). Pins are hand-maintained (`dependabot.yml` absent — §7).

## 5. `~/.ari/` path-exclude allow-list + ignored tests (verbatim, for 049 reuse)

**Path-exclude allow-list** — `refactor-guards.yml:83-96`. The base include
pathspec plus **13** `:!` exclude pathspecs (see §8 discrepancy on the "14"
claim). Copied verbatim:

```
# base include pathspec (:83)
git diff "$base" HEAD -- 'ari-core/ari/**.py' \
# 13 exclude pathspecs (:84-96)
  ':!ari-core/ari/_deprecation.py' \
  ':!ari-core/ari/migrations/' \
  ':!ari-core/ari/core.py' \
  ':!ari-core/ari/paths.py' \
  ':!ari-core/ari/memory_cli.py' \
  ':!ari-core/ari/memory/auto_migrate.py' \
  ':!ari-core/ari/memory/file_client.py' \
  ':!ari-core/ari/publish/backends/ari_registry.py' \
  ':!ari-core/ari/clone/resolvers/ari.py' \
  ':!ari-core/ari/registry/__init__.py' \
  ':!ari-core/ari/viz/state.py' \
  ':!ari-core/ari/viz/api_settings.py' \
  ':!ari-core/ari/viz/api_publish.py' \
```

The grep filter that follows (`:97-100`): `| grep -vE '^\+\+\+ '` →
`| grep -E '^\+.*(Path\.home\(\).*\.ari|~/\.ari)'` → `| grep -vE '^\+\s*#'`.

**Ignored tests** — `refactor-guards.yml:57-60` (4 `--ignore` flags on the
`pytest ari-core/tests/ -q` command at `:56`), verbatim:

```
--ignore=ari-core/tests/test_letta_restart_live.py
--ignore=ari-core/tests/test_letta_start_scripts.py
--ignore=ari-core/tests/test_ollama_gpu.py
--ignore=ari-core/tests/test_dashboard_html.py
```

**Reuse label:** subtask **049** (`add_contract_check_workflows`) copies the
allow-list and the merge-base idiom; if `refactor-guards.yml` changes before 049
runs, re-verify against these exact `file:line` citations (§11, §17).

## 6. Diff-guard idiom table

Two idioms coexist; the tree itself documents the preference.

| Idiom | Where | Class | Note |
| --- | --- | --- | --- |
| `git merge-base origin/${{ github.base_ref \|\| 'main' }} HEAD` | `refactor-guards.yml:82` | **REVIEW_REQUIRED** | Resolves a remote-tracking ref that can move mid-run. Do **not** "fix" in 045. |
| `${{ github.event.pull_request.base.sha }}` (immutable) | `docs-change-coupling.yml:51` (hard) and `:58` (advisory) | **KEEP / preferred** | The in-tree rationale is `docs-change-coupling.yml:41-47`. |
| `fetch-depth: 0` (enables merge-base diffs) | `docs-sync.yml:44`, `docs-change-coupling.yml:33`, `refactor-guards.yml:24` & `:72` | KEEP | Same co-change reason. |

In-tree critique verbatim location: `docs-change-coupling.yml:41-47` — states
`base.sha` is "immutable for this run" and "Preferred over the `origin/<base_ref>`
pattern in refactor-guards.yml, which resolves a remote-tracking ref that can move
if the base branch advances mid-run." New workflows (049/050/051) should
standardize on `base.sha`.

## 7. Confirmed-absent components

Each checked directly on 2026-07-01; each returned no such path.

| Component | Status | Owning downstream subtask (net-new) |
| --- | --- | --- |
| `.github/ISSUE_TEMPLATE/` | **does not exist** | 048 (`add_issue_templates_for_refactoring`) |
| `.github/PULL_REQUEST_TEMPLATE.md` (and lowercase `.github/pull_request_template.md`) | **does not exist** | 047 (`add_pr_template_quality_checklist`) |
| `.github/dependabot.yml` | **does not exist** | 052 (`add_dependabot_and_actions_policy`) |
| `CODEOWNERS` (checked `.github/`, repo root, `docs/`) | **does not exist** | 052 (or 046 policy) |
| `.github/actions/` (local composite actions) | **does not exist** | 052 (actions policy) |

Also confirmed: **no `sonfigs/` directory anywhere** (`find -iname '*sonfig*'`
matched only the planning filename
`docs/refactoring/subtasks/003_consolidate_config_configs_sonfigs.md`, no
directory). There are **no** scheduled/cron workflows, no reusable/called
workflows, no matrix builds, and no push-triggered CI other than `pages.yml`.

## 8. CI-coverage gap table (absent check → downstream subtask, no-overlap)

"Enforced today" from reading all five workflows. The **checker scripts** are
Phase-8 deliverables (subtasks 025–035, catalogued in `009_quality_scripts_plan.md`);
Phase-9 subtasks **046–052** own the **CI wiring**. Numbering below follows the
canonical `007_subtask_index.md` index (see §9 discrepancy vs. 012's internal
§15/§16 numbering).

| Absent check | Enforced today? | Downstream subtask (007 index) | Functional overlap with an existing job? |
| --- | --- | --- | --- |
| `ruff` lint | No | 046 design → 049 wiring | None — no workflow runs `ruff`. |
| `python -m compileall` | No | 046 → 049 | None. |
| Import boundaries (`ari.public` / core↔skill) | No | 049 | None; nearest analog is the `refactor-guards.yml` `~/.ari/` diff-grep (a content ban, not an import graph). |
| Complexity / LOC budget | No | 046 → 049 | None; `radon` not installed. |
| Public-API contracts (`ari.public.*`) | No | 049 | None; no gate/snapshot over `ari.public.*`. |
| Viz-API↔frontend schema | No | 049 | None; nothing couples `viz/routes.py`+`api_*.py` to `services/api.ts`. |
| Prompt checks (inline inventory) | **Partial** — `report/scripts/check_prompt_snapshots.py` (Gate 10) byte-verifies `ari/prompts/**/*.md`, but it is **not** wired into any of the five `.github/workflows/` files | 051 (`add_prompt_change_review_workflow`) | Snapshot slice overlaps Gate 10 (MERGE, do not re-implement); the **inline-prompt inventory** slice is net-new. |
| Docs-sync extension | Existing `docs-sync.yml` | 050 (`add_docs_sync_workflow`) | ADAPT/extend the existing gates; do **not** duplicate. |
| PR template | No (absent, §7) | 047 | None. |
| Issue templates | No (absent, §7) | 048 | None. |
| `dependabot.yml` | No (absent, §7) | 052 | None. |
| `CODEOWNERS` | No (absent, §7) | 052 | None. |

None of the proposed Phase-8 checker names exist in the tree today (verified in
`009`/`012`); every new gate is additive with no functional overlap to remove,
only pattern reuse (the §5 allow-list and §6 `base.sha` idiom).

## 9. Cross-check vs. `012` §2 and `007_subtask_index.md`, and discrepancies

**Consistent:**
- `012_github_workflow_integration_plan.md` §2 lists the same five workflows with
  identical line counts (58 / 91 / 64 / 28 / 105) and the same five absent
  components. ✔ Matches the tree.
- `007_subtask_index.md:346-349` (Phase 9): "5 workflows … all gating is
  docs/i18n-oriented; only `refactor-guards.yml` touches Python … No push CI
  except `pages.yml`." ✔ Matches this inventory.
- Byte sizes match subtask 045 §13 (4565 / 4335 / 2047 / 2648 / 937). ✔

**Discrepancies recorded (per §11/§17 — not "fixed" here, and the planning docs
are not edited):**

1. **Allow-list "14" vs. actual 13.** Subtask 045 (§1.5, §3, §8.4, §13) and
   `012` §3.1 describe the `~/.ari/` allow-list as **14** entries at
   `refactor-guards.yml:84-96`. The actual file has **13** `:!` exclude
   pathspecs on lines 84-96 (`grep -nE "^\s*':!"` → 13 hits). "14" is reached
   only if the base **include** pathspec `'ari-core/ari/**.py'` on line **83** is
   counted alongside the 13 excludes (i.e. 1 include + 13 excludes = 14
   pathspecs). The 13 exclude sites themselves are reproduced verbatim in §5. The
   enumerated lists inside `012` §3.1 and subtask 045 §3 also contain 13 named
   sites, so the prose count "14" is the outlier. **REVIEW_REQUIRED** for whoever
   next edits those docs; 045 records the ground truth and does not alter the
   workflow.

2. **`012` §15/§16 internal subtask numbering conflicts with the `007` index.**
   `012` §15/§16 assigns, e.g., `check_complexity`/`dead_code`/`quality_report`
   to "subtask 045", `check_import_boundaries` to "046", templates to "052",
   etc. — a numbering local to `012` that does **not** match
   `007_subtask_index.md`, where 045 = `inventory_github_workflows`, 046 =
   `design_quality_ci_integration`, 047 = PR template, 048 = issue templates,
   049 = contract-check workflows, 050 = docs-sync, 051 = prompt-change review,
   052 = dependabot/actions. This inventory (and §8 above) follows the canonical
   `007` index. **REVIEW_REQUIRED**: reconcile `012` §15/§16 with `007`.

3. **`012` §16 staleness.** `012` §16 says "`docs/refactoring/subtasks/` and
   `docs/refactoring/reports/` are currently **empty** (verified 2026-07-01)."
   As of this run both are populated (73 subtask docs exist; this report is the
   first artifact under `reports/` besides `README.md` and
   `orchestration_status.md`). Minor staleness; recorded, not edited.

## 10. Open questions (REVIEW_REQUIRED — do not resolve in 045)

- **`refactor-guards.yml:82`** uses `git merge-base origin/${{ github.base_ref ||
  'main' }} HEAD` — a mutable remote-tracking ref. Preferred replacement is
  `github.event.pull_request.base.sha` (§6). Resolution is 046/049 work, not 045.
- **`pages.yml:21`** path filter lists `README.md` only, not `README.ja.md` /
  `README.zh.md`; a push that edits only a translated README would not trigger a
  Pages rebuild. Intent unconfirmed. Resolution is 050 work, not 045.

## 11. Classification summary (master vocabulary)

| Item | Class |
| --- | --- |
| `refactor-guards.yml` | KEEP (reuse template for 049) |
| `docs-sync.yml` | KEEP (ADAPT target for 050) |
| `pages.yml` | KEEP |
| `docs-change-coupling.yml` | KEEP (canonical `base.sha` idiom) |
| `readme-sync.yml` | KEEP |
| `base.sha` idiom | KEEP / preferred |
| `origin/<base_ref>` merge-base idiom | REVIEW_REQUIRED |
| `ISSUE_TEMPLATE/`, `PULL_REQUEST_TEMPLATE.md`, `dependabot.yml`, `CODEOWNERS`, `.github/actions/` | net-new (does not exist; 047/048/052) |

## 12. Notes on hygiene gates (for the orchestrator)

- `python -m compileall ari-core ari-skill-memory scripts` → **exit 0** (pass).
  045 adds no `.py`, so this is unaffected.
- `ruff check ari-core` → **661 findings** (the frozen baseline recorded in
  `orchestration_status.md`), unchanged by 045 (no `.py` added/changed). Exit 1
  reflects the pre-existing baseline, not a 045 regression.
- `python scripts/readme_sync.py --check` → **pre-existing** drift in 4 READMEs
  unrelated to 045 (`ari-core/ari/viz/frontend/src/README.md` and two nested
  `PaperBench`/`components` READMEs for `PaperBench/steps/`; `report/shared/README.md`
  for `tables/`). These are outside `docs/refactoring/reports/` and outside 045's
  scope (§4 Non-Goals forbid touching `docs/`, `report/`, frontend). Adding this
  report introduces **no new** drift: `docs/refactoring/reports/README.md` has no
  `## Contents` heading, so it is a curated (unmanaged) README that owns its
  subtree — `readme_sync.py` never enumerates files under it, and no parent
  managed README descends into it. Confirmed by re-running `--check` after
  writing this file (drift list unchanged: same 4 pre-existing entries).
- `pytest` is run centrally by the orchestrator (not re-run here).
