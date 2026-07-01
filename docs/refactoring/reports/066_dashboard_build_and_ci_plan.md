# 066 — Dashboard Frontend Build & CI Plan (authoritative)

> **Deliverable of subtask** `docs/refactoring/subtasks/066_add_dashboard_build_and_ci_plan.md`
> (§9 "Executing subtask 066 later" → this single Markdown file). **Planning only.**
> Authoring this document changes **no** runtime code, **no** `.github/workflows/*.yml`,
> **no** `ari-core/ari/viz/frontend/**` source or build config, **no**
> `setup.sh` / `scripts/setup/install_frontend.sh`, and **no** config, prompt, or
> directory name. The only file it creates is this one.
>
> It turns subtask 066's design prose (§7) into a concrete, per-step CI spec — job
> name, triggers, path filter, cache key, exact commands, fatal-on-failure
> semantics — that a workflow-implementation subtask can transcribe into GitHub
> Actions **without further design work** and **without rewriting any of the five
> existing workflows**. It mirrors the plan-only pattern already established by
> `docs/refactoring/reports/032_quality_script_ci_integration.md`.
>
> **Repo baseline:** `/home/t-kotama/workplace/ARI` · git branch
> `whole_refactoring` · `ari-core` version `0.9.0` · verified against the working
> tree **2026-07-01**. Every path/line cited below was read from the live tree;
> absent paths are written "does not exist" (never invented). Structural facts are
> cross-checked against the frozen inventories
> `docs/refactoring/reports/dashboard_structure_inventory.md` (059) and
> `docs/refactoring/reports/045_github_workflow_inventory.md`.
>
> **Classification vocabulary:** KEEP / ADAPT / MERGE / MOVE_TO_LEGACY /
> DELETE_CANDIDATE / REVIEW_REQUIRED. The word "deprecated" is reserved for
> external contracts only; the `origin/<base_ref>` idiom is described as
> "not preferred / do not copy", not "deprecated". There is **no `sonfigs/`**
> anywhere in the repo — it is irrelevant to this frontend-build plan and is
> mentioned only to close the loop.

---

## 1. Purpose and status of this plan

The ARI dashboard React/TypeScript frontend (`ari-core/ari/viz/frontend/`) is
**entirely un-gated in CI**: no workflow runs `typecheck`, `vitest`, or
`vite build` against it, so a PR can land a TypeScript type error, a broken
component test, or a bundle that fails to build with every existing check green.
This document is the **single authoritative** spec for closing that gap:

- the reproducible build contract (deterministic install, pinned Node major,
  generated-artifact policy);
- one CI job that runs `npm ci → typecheck → test → build` on PRs touching the
  frontend;
- the placement decision (new `frontend.yml` vs an added job) and how it
  coordinates with the Phase-9 GitHub-integration subtasks so the workflow is
  added exactly once;
- the `test_dashboard_html` reconciliation decision + follow-up owner;
- the `REVIEW_REQUIRED` backlog (ESLint/Prettier, frontend-i18n parity) recorded
  with recommended defaults, not implemented.

This is a **plan**, not an implementation. The actual `.github/workflows/frontend.yml`
and any `refactor-guards.yml` ignore-list edit are owned by the Phase-9
workflow-implementation subtasks (§9 below), not by executing subtask 066.

---

## 2. Grounded frontend build baseline (what exists today)

Verified by reading `ari-core/ari/viz/frontend/` on 2026-07-01.

**Toolchain (`package.json`).** A Vite 5 + React 18.3 + TypeScript 5.5 ESM app
(`"type":"module"`, `"private":true`). Dependencies:

| Kind | Packages (pinned range) |
|---|---|
| runtime deps (4) | `react ^18.3.1`, `react-dom ^18.3.1`, `d3 ^7.9.0`, `reactflow ^11.11.4` |
| dev deps | `typescript ^5.5.4`, `vite ^5.4.2`, `vitest ^2.1.0`, `@vitejs/plugin-react ^4.3.1`, `@testing-library/{jest-dom ^6.4.5, react ^16.0.0, user-event ^14.5.2}`, `jsdom ^25.0.0`, `@types/{d3,react,react-dom}` |

**npm scripts — exactly 6** (there is **no `lint` script**):

```
dev        → vite
build      → vite build
typecheck  → tsc --noEmit
preview    → vite preview
test       → vitest run
test:watch → vitest
```

**No linter/formatter.** ESLint / Prettier / EditorConfig **do not exist**
anywhere in the frontend tree. `tsconfig.json` is `strict` with `noUnusedLocals`,
`noUnusedParameters`, `noFallthroughCasesInSwitch`, `noEmit`, `jsx: react-jsx`,
`moduleResolution: bundler` — so `npm run typecheck` already gives meaningful
static coverage without a lint step.

**Build config (`vite.config.ts`).** `base: "/static/dist/"`;
`build.outDir → resolve(__dirname, "../static/dist")`; `emptyOutDir: true`;
`@ → src` alias; dev-server proxy of `/api` + `/state` → `http://localhost:8765`
and `/ws` → `ws://localhost:8765`. **These `outDir`/`base` values are the serve
contract (§8) and must not change.**

**Test config (`vitest.config.ts`).** `environment: 'jsdom'`, `globals: true`,
`setupFiles: ['./vitest.setup.ts']`, `include: ['src/**/__tests__/**/*.test.tsx',
'src/**/*.test.tsx']`, `css: false`.

**Only 2 frontend test files exist** (verified):
- `ari-core/ari/viz/frontend/src/components/PaperBench/__tests__/PaperBenchWizard.test.tsx`
- `ari-core/ari/viz/frontend/src/components/PaperBench/__tests__/PaperImportDialog.test.tsx`

`npm test` therefore runs fast and passes on the current tree. Any peer Phase-5
subtask that adds `src/**/*.test.tsx` is picked up automatically by the same
`include` globs.

**Lockfile is tracked and `npm ci`-ready.** `package-lock.json` is git-tracked
(140,743 bytes ≈ 140 KB) and consistent with `package.json` today. `node_modules/`
is **not** git-tracked (`git ls-files … /node_modules` → 0) and exists on disk
(~112 MB) only as a normal working install.

**Install path today (`scripts/setup/install_frontend.sh`, step 5/6 of `setup.sh`).**
Runs `npm install --no-audit --no-fund` then `npx vite build`. Two behaviours
matter for CI design:
1. It uses **`npm install`, not `npm ci`** — non-deterministic; it can rewrite the
   tracked `package-lock.json`.
2. It is **non-fatal**: on `vite build` failure it only `warn`s
   ("dashboard will use fallback HTML") and `return 0`; it also returns 0 if
   Node/npm are absent. Correct for an interactive laptop installer — the exact
   opposite of what CI needs.

**Serve-time contract (`ari-core/ari/viz/server.py`).**
`:57 DASHBOARD_PATH = Path(__file__).parent / "dashboard.html"`,
`:58 REACT_DIST_DIR = Path(__file__).parent / "static" / "dist"`,
`:59 REACT_INDEX = REACT_DIST_DIR / "index.html"`. **`dashboard.html` does not
exist on disk** — `DASHBOARD_PATH` is a phantom fallback. The effective serve
contract is "serve the built `static/dist/`"; the plan must not design around a
fallback HTML page.

**i18n drift (minor, confirmed).** `src/i18n/en.ts` = 444 lines vs `ja.ts` = 441
and `zh.ts` = 441 (a 3-line divergence). No gate covers frontend translation
parity (see §6.2).

---

## 3. Grounded CI baseline (what exists — and does NOT — today)

There are **exactly five** workflows under `.github/workflows/`:
`docs-change-coupling.yml`, `docs-sync.yml`, `pages.yml`, `readme-sync.yml`,
`refactor-guards.yml`.

**Node/npm appears in CI in exactly two places — both build the VitePress docs
site (`docs/`), NOT the dashboard frontend:**
- `docs-sync.yml` `vitepress-build` job: `actions/setup-node@v4` (`:81`),
  `node-version: 20` (`:83`), `cache: npm`, `cache-dependency-path: docs/package-lock.json`
  (`:85`), `npm ci --prefix docs` (`:89`), `npm run --prefix docs docs:build` (`:91`).
- `pages.yml`: `setup-node@v4` (`:38`), `node-version: 20` (`:40`),
  `cache-dependency-path: docs/package-lock.json` (`:42`), `npm ci --prefix docs`
  (`:46`), `npm run --prefix docs docs:build` (`:48`).

**No workflow runs `npm ci` / `typecheck` / `vitest` / `vite build` against
`ari-core/ari/viz/frontend/`.** The dashboard frontend is un-gated in CI — the
core gap this plan closes.

**The one pytest that would catch a broken build is disabled.**
`refactor-guards.yml` (triggers: `pull_request` to `main` and `refactoring`) runs
`pytest ari-core/tests/ -q` under a sandboxed `HOME`, but explicitly
`--ignore`s four tests (`:56-60`), one of which is `test_dashboard_html.py`. The
in-file comment (`:52-55`) states the artefact "is produced by a separate frontend
build job; this guard only cares about `~/.ari/` writes, not frontend bundling."
`ari-core/tests/test_dashboard_html.py` asserts the Vite build ran:
`test_react_build_exists` → `static/dist/index.html` exists (`:14`);
`test_build_has_assets` → `static/dist/assets/*.js` and `*.css` exist (`:64-71`).
It is ignored precisely because CI never builds the frontend; a frontend-build CI
job is the missing piece that would make it enforceable. (Listed in
`ari-core/tests/README.md:39`.)

**Diff-scope idioms available to reuse.** `refactor-guards.yml:82` uses
`git merge-base origin/${{ github.base_ref || 'main' }} HEAD` — the movable
`origin/<base_ref>` pattern. `docs-change-coupling.yml:42-51` documents that
`${{ github.event.pull_request.base.sha }}` (immutable for the run) is
**preferred**. This plan's job does not need a diff scope (§4.2), but any later
diff-scoped step must use `base.sha`.

---

## 4. Build-contract & CI-job spec (the heart of the plan)

### 4.1 Build contract (`KEEP` toolchain, `ADAPT` invocation)

- **Toolchain:** keep Vite 5 / Vitest 2 / TS 5.5 exactly as configured. **No tool
  swaps**, no `pnpm`/`yarn` (npm-only is the repo convention — both docs jobs use
  `npm ci`).
- **Install:** CI uses **`npm ci`** (deterministic; fails if `package-lock.json`
  is missing or inconsistent with `package.json`; never mutates the lockfile),
  invoked with `--prefix ari-core/ari/viz/frontend`. The interactive installer
  keeps `npm install` — **unchanged**.
- **Node version:** pin `node-version: 20` to match `docs-sync.yml` / `pages.yml`,
  so the repo has one Node major across all CI jobs.
- **Artifact policy:** `ari-core/ari/viz/static/dist/` is a generated artifact —
  it stays git-ignored and is produced by CI on demand, never committed.
  `node_modules/` stays git-ignored. (Ignore lines confirmed live: see §5.)

### 4.2 CI-job spec (ready-to-transcribe)

| Field | Value |
|---|---|
| **Home** | a **new** workflow file `.github/workflows/frontend.yml` (recommended — isolates the dashboard build from the docs and refactor-guard concerns; gives the Phase-9 implementer one well-scoped file). Alternative (recorded, **not** recommended): append a job to `refactor-guards.yml`, which couples a Node job to that file's Python-sandbox job. |
| **Trigger** | `pull_request` targeting `main` **and** `refactoring` (matches `refactor-guards.yml`'s branch set, so Phase-5 PRs on the refactoring branch are gated too). |
| **Path filter** | `paths: ['ari-core/ari/viz/frontend/**']` — the job runs only when frontend files change, keeping unrelated PRs fast. |
| **Runner** | `ubuntu-latest`. |
| **Setup** | `actions/checkout@v4` → `actions/setup-node@v4` with `node-version: 20`, `cache: npm`, `cache-dependency-path: ari-core/ari/viz/frontend/package-lock.json`. |
| **Steps (all fatal — job fails on any non-zero exit)** | 1. `npm ci --prefix ari-core/ari/viz/frontend` · 2. `npm run --prefix ari-core/ari/viz/frontend typecheck` (`tsc --noEmit`) · 3. `npm run --prefix ari-core/ari/viz/frontend test` (`vitest run`) · 4. `npm run --prefix ari-core/ari/viz/frontend build` (`vite build` → `static/dist/`). |
| **Secrets** | none required — install/typecheck/test/build need no tokens or network beyond the npm registry. |

The `--prefix` idiom is exactly how the docs workflows already invoke npm
(`npm ci --prefix docs`, `npm run --prefix docs docs:build`), so it is an
established pattern in this repo — reused here with the frontend lockfile as the
cache key.

**ILLUSTRATIVE YAML sketch (do NOT commit this file as part of subtask 066 — it
is owned by the Phase-9 implementer, §9):**

```yaml
# .github/workflows/frontend.yml  — ILLUSTRATIVE; transcribed by a Phase-9 subtask
name: frontend
on:
  pull_request:
    branches: [main, refactoring]
    paths: ['ari-core/ari/viz/frontend/**']
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: npm
          cache-dependency-path: ari-core/ari/viz/frontend/package-lock.json
      - run: npm ci      --prefix ari-core/ari/viz/frontend
      - run: npm run     --prefix ari-core/ari/viz/frontend typecheck
      - run: npm run     --prefix ari-core/ari/viz/frontend test
      - run: npm run     --prefix ari-core/ari/viz/frontend build
```

### 4.3 `test_dashboard_html` reconciliation — DECISION: Option A

**Chosen: Option A (recommended).** Rely on step 4 (`npm run … build`) of §4.2 to
gate the bundle, and **keep** `test_dashboard_html` in `refactor-guards.yml`'s
ignore list. Rationale: that pytest runs in a Python-only sandbox runner with no
Node install; building the frontend there would be redundant and slow, and §4.2
step 4 fully subsumes the intent of `test_dashboard_html` (it fails the PR if the
Vite bundle does not build). **Follow-up owner:** the Phase-9 workflow-implementer
(§9) records, in the PR that adds `frontend.yml`, that `test_dashboard_html`
stays ignored by design and points to `frontend.yml` step 4 as its replacement.
No edit to `refactor-guards.yml`'s ignore list is required.

Rejected: Option B (un-ignore `test_dashboard_html` only inside a runner that
first runs the Vite build) — more moving parts, installs Node into the Python
sandbox job, no added coverage over Option A.

### 4.4 `REVIEW_REQUIRED` backlog (documented, not implemented)

- **ESLint / Prettier** — absent today. `tsconfig` strictness already catches
  unused vars and type errors, so lint is additive polish, not a correctness gate.
  **Recommended default:** defer to a future subtask; do **not** add config or a
  `lint` script in the first CI job.
- **Frontend-i18n key parity** — `src/i18n/en.ts` (444) vs `ja.ts` / `zh.ts`
  (441) drift by 3 lines; the existing `scripts/docs/check_i18n_js.py` covers the
  **docs-site** `*.js` surfaces, not the frontend `src/i18n/*.ts`. **Recommended
  default:** if adopted later, reuse the `check_i18n_js.py` approach over a new
  bespoke checker; keep it out of the first CI job. (Tracked for subtask 073.)

---

## 5. Skeleton correction — `node_modules` is NOT committed

The refactoring skeleton's claim "committed `node_modules/` in git" is **false in
the current tree** and must not send an implementer down a non-existent cleanup
path. Verified live:

- `git ls-files ari-core/ari/viz/frontend/node_modules` → **0 files**.
- `.gitignore` ignores (**exact live line numbers, 2026-07-01**):
  - `:108` `node_modules/`
  - `:109` `ari-core/ari/viz/frontend/node_modules/`
  - `:110` `ari-core/ari/viz/static/dist/`
  - `:128` `docs/node_modules/`
- `package-lock.json` (140 KB) **is** tracked — exactly what `npm ci` requires.

> **Line-number note (grounding).** Subtask 066 (§2.4/§9/§10) and the 059
> inventory cite these ignores at `.gitignore:113/114`. The **live tree** places
> them at `108/109/110` (the file has shifted since those docs were captured).
> This report grounds against the live tree: **108/109/110**. The *facts*
> (node_modules and static/dist both ignored; lockfile tracked) are unchanged;
> only the line indices differ. No `.gitignore` edit is proposed.

The plan therefore needs **no** "remove committed deps" step and **no**
"un-ignore node_modules" step; the frontend is already in good shape for a
deterministic `npm ci` install.

---

## 6. Compatibility constraints & follow-ups

### 6.1 Constraints the implementer must honor

- **Deterministic install requires the lockfile.** `npm ci` fails if
  `package-lock.json` is missing or inconsistent with `package.json`. It is
  tracked and consistent today; any future `package.json` change must be committed
  together with a regenerated `package-lock.json`, or CI breaks.
- **Node major must stay aligned.** Node 20 matches both existing Node jobs; the
  frontend job must match to avoid a second Node toolchain in CI.
- **Path-filter × required-checks interaction.** If the FE job is later made a
  *required* status check, GitHub reports a path-filtered job that is *skipped* on
  a frontend-untouched PR as "pending", which can block the PR forever. Flag this:
  either leave the job **non-required**, or add an always-runs guard job that
  resolves skipped runs to success.
- **No secrets.** The four steps require no tokens/API keys; the job must declare
  no `secrets`.
- **Artifact hygiene stays intact.** `static/dist/` and `node_modules/` remain
  git-ignored; the plan proposes committing neither.

### 6.2 Coordinate-with (so the workflow file is added exactly once)

The **hard predecessor** is **059** (`inventory_dashboard_frontend_backend_structure`,
this report's structural baseline). Beyond that, this plan is a peer of the other
Phase-5 subtasks (060–065, 067–073) and must be wired by / coordinated with the
Phase-9 GitHub-integration subtasks, which **own the actual YAML**:

- **045** `inventory_github_workflows` — source of the "5 workflows, all
  docs-oriented" baseline (§3).
- **046** `design_quality_ci_integration` + **032**
  `add_quality_script_ci_plan` — the master CI-integration design and the
  plan-only precedent this report mirrors.
- **049** `add_contract_check_workflows`, **050** `add_docs_sync_workflow`,
  **052** `add_dependabot_and_actions_policy` — the Phase-9 subtasks that write
  workflow YAML. **The `frontend.yml` job specified in §4.2 must be added by (or
  in coordination with) these so it is created exactly once**, reusing the
  `setup-node@v4` / Node 20 / npm-cache / `--prefix` mechanics proven in
  `docs-sync.yml` + `pages.yml` (but keyed on the *frontend* lockfile, not
  `docs/package-lock.json`).

---

## 7. Self-check checklist (for the workflow-implementation subtask)

The Phase-9 implementer transcribing §4.2 into `.github/workflows/frontend.yml`
should be able to tick every box:

- [ ] Workflow file is **new** (`frontend.yml`); the five existing workflows are untouched.
- [ ] Triggers on `pull_request` to `main` **and** `refactoring`.
- [ ] `paths: ['ari-core/ari/viz/frontend/**']` — runs only on frontend-touching PRs.
- [ ] `setup-node@v4`, `node-version: 20`, `cache: npm`, `cache-dependency-path: ari-core/ari/viz/frontend/package-lock.json` (cache hits on the frontend lockfile).
- [ ] Four steps present, **all fatal**: `npm ci` → `typecheck` → `test` → `build`, each with `--prefix ari-core/ari/viz/frontend`.
- [ ] No `secrets`, no `pnpm`/`yarn`, no ESLint/Prettier, no `lint` step.
- [ ] `refactor-guards.yml`'s `test_dashboard_html` ignore is left in place (Option A); the PR notes `frontend.yml` step 4 as its replacement.
- [ ] Required-check decision recorded (non-required, or an always-runs guard job) to avoid "pending" on frontend-untouched PRs.
- [ ] `.gitignore` untouched (`static/dist/` + `node_modules/` already ignored at `:108-110`).

---

## 8. Preserved contracts (this plan guards, never breaks)

Per subtask 066 §10 and `docs/refactoring/010_contract_preservation_policy.md`,
the plan and every later step it authorizes must preserve:

- **Dashboard build-output contract.** `server.py:58` serves `static/dist/index.html`
  via `REACT_DIST_DIR`; CI must keep producing `static/dist/` with
  `base: "/static/dist/"` — **do not change `vite.config.ts`'s `outDir`/`base`.**
- **Dashboard API + client contract.** `ari/viz/routes.py` + `api_*.py` endpoints
  and `services/api.ts` (863 LOC) stay unchanged; a build job must not touch the
  API surface (§4/§5 of doc 010; owned by subtasks 020–024, 060–065).
- **npm-only CI convention.** No `pnpm`/`yarn`.
- **Installer contract.** `setup.sh` step 5/6 → `install_frontend.sh` keeps
  working on machines without Node (warn-and-continue). CI fatality is *additive*,
  never a change to the installer.
- **CLI / `ari.public.*` / MCP / checkpoint / config contracts.** Untouched by a
  frontend-build job; the plan proposes no change to any of them.
- **The five existing workflows.** Not rewritten; `frontend.yml` is additive.

---

## 9. Non-goals of subtask 066 (this executing pass)

- **Not** writing/editing any `.github/workflows/*.yml` (owned by Phase-9 subtasks, §6.2).
- **Not** editing `package.json`, `vite.config.ts`, `vitest.config.ts`,
  `tsconfig.json`, or any `src/**` file.
- **Not** editing `setup.sh` or `scripts/setup/install_frontend.sh` (its
  warn-and-continue behaviour is intentional and KEEP).
- **Not** adding ESLint/Prettier config or a `lint` script (records the decision only, §4.4).
- **Not** swapping Vite/Vitest, introducing `pnpm`/`yarn`, committing
  `static/dist/`, or un-ignoring `node_modules/`.
- **Not** authoring a dependency-update policy (`dependabot.yml` is absent, owned
  by subtask 052).
- **Not** any frontend-component refactor, API-schema change, or i18n-string edit.

---

## 10. Self-verification (against subtask 066 §12/§13)

- Deliverable = this one Markdown file under `docs/refactoring/reports/`; no YAML,
  no source/config/installer edits (`git status` shows only this `.md`). ✅
- The **exact CI-job spec** (§4.2) is recorded: `frontend.yml`, trigger, `paths`
  filter, `setup-node@v4` + Node 20 + npm cache keyed on the frontend lockfile,
  and the four fatal `--prefix` steps (`npm ci`, `typecheck`, `test`, `build`). ✅
- The **`test_dashboard_html` decision** is recorded and justified (Option A —
  keep ignored, rely on the build step) with a follow-up owner (§4.3). ✅
- The **`REVIEW_REQUIRED` backlog** (ESLint/Prettier, frontend-i18n parity) is
  recorded with recommended defaults and **not** implemented (§4.4). ✅
- The skeleton's false "committed node_modules" claim is **corrected** and the
  `.gitignore` ignores + tracked lockfile confirmed against the live tree, with
  the stale-line-number note (§5). ✅
- Toolchain facts grounded against the live tree: Vite 5 / React 18.3 / TS 5.5 /
  Vitest 2, **6** npm scripts, npm-only, output `viz/static/dist/`, 2 frontend
  tests, `dashboard.html` does not exist. ✅

---

## 11. Retirement Condition

This report is the deliverable of a **temporary planning artifact** (subtask 066).
It may be archived or deleted (`git rm`) only after **all** of the following are
verified against primary sources (repository state, merged diff, index) — never on
assumption:

1. The **§13 Acceptance Criteria** of
   `docs/refactoring/subtasks/066_add_dashboard_build_and_ci_plan.md` are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **066** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read the subtask's own conditions and check each against the current
repository — see the canonical policy in `docs/refactoring/007_subtask_index.md`
("Document Retirement Policy").
