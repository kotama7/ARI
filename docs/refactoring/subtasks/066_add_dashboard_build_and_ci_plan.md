# Subtask 066: Add Dashboard Build and CI Plan

- **Subtask ID:** 066
- **Phase:** Phase 5 — Dashboard Frontend
- **Classification:** `KEEP` (additive planning/design deliverable; the existing Vite/Vitest toolchain is kept, not replaced). No target source file, workflow, or build config is modified by authoring or by executing this subtask.
- **Changes runtime code:** **No** (see Section 16 — this subtask produces a Markdown design plan only)
- **Planning date:** 2026-07-01
- **Repo root:** `/home/t-kotama/workplace/ARI` (git branch `main`, `ari-core` version `0.9.0`)

> **Planning-phase notice.** This document is a plan for a *future* coding session. Authoring it changes no runtime code, imports, prompts, configs, workflows, frontend source, or directory names. The only file created by authoring *this* plan is this `.md` itself. The subtask it describes (066) is itself a **design/planning** subtask: when executed, subtask 066 produces one *additional* Markdown design document (the "Dashboard frontend build & CI plan"), and still writes **no** `.github/workflows/*.yml`, **no** changes to `ari-core/ari/viz/frontend/**` (package.json, vite.config.ts, tsconfig.json, source), and **no** changes to `setup.sh` / `scripts/setup/install_frontend.sh`. The actual workflow YAML and any build-config edits are owned by the GitHub-integration implementation subtasks (Section 15).

---

## 1. Goal

Produce the **authoritative, subtask-actionable plan** for how the ARI dashboard **React/TypeScript frontend** (`ari-core/ari/viz/frontend/`) gets a reproducible build contract and a **CI gate** — precise enough that a workflow-implementation subtask can wire it into GitHub Actions without further design work, and **without rewriting any of the five existing workflows**.

Concretely, the deliverable plan must specify:

1. A **reproducible build contract** for the dashboard frontend: deterministic install (`npm ci` against the already-tracked `package-lock.json`), pinned Node major (20, matching existing workflows), and the fact that the build output (`ari-core/ari/viz/static/dist/`) is a generated, git-ignored artifact.
2. A **CI job** (new `frontend.yml`, or an added job — decision recorded in the plan) that runs on PRs touching `ari-core/ari/viz/frontend/**` and executes: `npm ci` → `npm run typecheck` → `npm test` → `npm run build`.
3. A recorded decision on whether the new build job lets subtask-owners **un-ignore** the pytest test `test_dashboard_html.py`, which is currently listed in `refactor-guards.yml`'s ignore set precisely because CI never builds the frontend.
4. Explicit `REVIEW_REQUIRED` items that this plan must *not* silently implement: adding ESLint/Prettier (absent today) and adding a frontend-i18n key-parity gate (`en.ts` vs `ja.ts`/`zh.ts` drift).

The single deliverable of subtask 066 is a Markdown plan document under `docs/refactoring/reports/` (that directory exists and is currently empty — verified 2026-07-01). It is the input spec consumed by the workflow-implementation subtasks (Section 15).

---

## 2. Background

### 2.1 The frontend toolchain (verified)

`ari-core/ari/viz/frontend/` is a **Vite 5 + React 18.3 + TypeScript 5.5** ESM app (`package.json` `"type":"module"`). Runtime deps are minimal: `react`, `react-dom`, `d3` (7.9), `reactflow` (11.11). Tests use **Vitest 2** + Testing Library + jsdom. The tracked `package.json` declares exactly six scripts:

```
dev        → vite
build      → vite build
typecheck  → tsc --noEmit
preview    → vite preview
test       → vitest run
test:watch → vitest
```

There is **no `lint` script** and **no ESLint/Prettier/EditorConfig** anywhere in the frontend tree (verified: `find … -iname '*eslint*' -o -iname '*prettier*'` → 0 hits outside `node_modules`). `tsconfig.json` is `strict` with `noUnusedLocals` / `noUnusedParameters` / `noFallthroughCasesInSwitch`, so `npm run typecheck` already provides meaningful static coverage.

Build config (`vite.config.ts`): `base: "/static/dist/"`, `build.outDir → ../static/dist`, `emptyOutDir: true`, `@ → src` alias, and a dev-server proxy of `/api`, `/state`, `/ws` to `localhost:8765`. Test config (`vitest.config.ts`): jsdom environment, globals, `setupFiles: ['./vitest.setup.ts']`, `include: ['src/**/__tests__/**/*.test.tsx', 'src/**/*.test.tsx']`.

Only **2** frontend test files exist today (verified):
- `ari-core/ari/viz/frontend/src/components/PaperBench/__tests__/PaperBenchWizard.test.tsx`
- `ari-core/ari/viz/frontend/src/components/PaperBench/__tests__/PaperImportDialog.test.tsx`

### 2.2 How the build is produced and served today

`scripts/setup/install_frontend.sh` (invoked as step 5/6 by `setup.sh`) runs `npm install --no-audit --no-fund` then `npx vite build`. Two behaviours matter for CI design:
- It uses **`npm install`, not `npm ci`** — non-deterministic, and it can rewrite `package-lock.json`.
- The build is **non-fatal**: on failure it only `warn`s ("dashboard will use fallback HTML") and returns 0. This is correct for an interactive installer but is the opposite of what CI needs.

At serve time, `ari-core/ari/viz/server.py:58` sets `REACT_DIST_DIR = Path(__file__).parent / "static" / "dist"` and `REACT_INDEX = REACT_DIST_DIR / "index.html"`. Note: `server.py:57` also references `DASHBOARD_PATH = Path(__file__).parent / "dashboard.html"`, but that fallback file **does not exist** on disk at `ari-core/ari/viz/dashboard.html` (verified). The plan must not assume a fallback HTML page exists; the effective contract is "serve the built `static/dist/`."

### 2.3 What CI does — and does NOT — do today

There are exactly **five** workflows under `.github/workflows/` (`docs-change-coupling.yml`, `docs-sync.yml`, `pages.yml`, `readme-sync.yml`, `refactor-guards.yml`). Node/npm appears in CI in exactly two places, and **both build the VitePress docs site (`docs/`), not the dashboard frontend**:
- `docs-sync.yml:81-85` (`vitepress-build` job): `setup-node@v4`, `node-version: 20`, `cache: npm`, `cache-dependency-path: docs/package-lock.json`.
- `pages.yml:38-42`: same, for the Pages deploy build.

**No workflow runs `npm ci` / `typecheck` / `vitest` / `vite build` against `ari-core/ari/viz/frontend/`.** The dashboard frontend is therefore **entirely un-gated in CI**: a PR can land a TypeScript type error, a broken component test, or a bundle that fails to build, and every existing check stays green.

This gap is made explicit by `refactor-guards.yml`: its `no-home-ari-writes` job runs `pytest ari-core/tests/ -q` but **ignores four tests**, one of which is `test_dashboard_html`. That pytest test (`ari-core/tests/test_dashboard_html.py`) asserts `static/dist/index.html` and `dist/assets/*.js` + `*.css` exist — i.e. it asserts *the Vite build ran*. It is ignored precisely because CI never builds the frontend. A frontend-build CI job is the missing piece that would let this test become enforceable.

### 2.4 Hygiene state (correcting the skeleton)

The refactoring skeleton claims "committed `node_modules/` in git". **This is false in the current tree** (verified): `git ls-files` returns 0 files under `node_modules`; `.gitignore:113` ignores `ari-core/ari/viz/frontend/node_modules/` and `.gitignore:114` ignores `ari-core/ari/viz/static/dist/`. `node_modules/` exists on disk (~112 MB) only as a normal working install. `package-lock.json` (140 KB) **is** tracked — which is exactly what `npm ci` requires. So the frontend is already in good shape for a deterministic CI install; the plan does **not** need a "remove committed deps" step. The one confirmable hygiene nit is minor i18n key drift: `src/i18n/en.ts` is 444 lines vs `ja.ts`/`zh.ts` at 441 each.

### 2.5 Why this is a plan, not an implementation

Per the master GitHub-integration design (`docs/refactoring/012_github_workflow_integration_plan.md`) and the Phase-5 dashboard plans (`008_viz_dashboard_refactoring_plan.md`, `014_dashboard_ux_refactoring_plan.md`), workflow YAML is owned by the Phase-9 GitHub-integration subtasks. Subtask 066 is the **subtask-level realization** for the dashboard-frontend slice: it turns the design prose into a concrete, per-step CI spec (job name, triggers, path filter, cache key, exact commands, fatal-on-failure semantics) that a fresh implementer can execute. It mirrors the plan-only pattern already established by subtask 032 (`032_add_quality_script_ci_plan.md`), which likewise produces a Markdown spec and writes no YAML.

---

## 3. Scope

In scope for subtask 066 (the plan it must produce):

1. **Build-contract spec.** Deterministic install policy (`npm ci` against tracked `package-lock.json`), Node major pin (20), output-artifact policy (`static/dist/` is generated + git-ignored; never commit it), and a statement that `setup.sh`/`install_frontend.sh` stay non-fatal at *install* time while *CI* is fatal.
2. **CI-job spec.** One job that, on PRs touching `ari-core/ari/viz/frontend/**`, runs `npm ci` → `npm run typecheck` → `npm test` → `npm run build`, with `setup-node@v4`, `node-version: 20`, `cache: npm`, and `cache-dependency-path: ari-core/ari/viz/frontend/package-lock.json`.
3. **Placement decision.** Record whether the job lives in a **new `frontend.yml`** (recommended, keeps concerns isolated) or is appended to an existing workflow, and how it coordinates with the Phase-9 GitHub-integration subtasks (Section 15) so it is not duplicated.
4. **`test_dashboard_html` reconciliation.** Record the decision + follow-up owner for un-ignoring `test_dashboard_html` in `refactor-guards.yml` once a CI job guarantees a build exists (or explicitly keep it ignored and rely on the FE job's `npm run build` step instead — the plan must pick one and justify it).
5. **`REVIEW_REQUIRED` backlog.** ESLint/Prettier adoption and a frontend-i18n key-parity gate — documented as future options with a recommended default, not implemented.

Out of scope (owned elsewhere — do **not** do them in this plan or its executing subtask):
- Writing/editing any `.github/workflows/*.yml` (owned by the Phase-9 workflow-implementation subtasks; see Section 15).
- Editing `ari-core/ari/viz/frontend/package.json`, `vite.config.ts`, `vitest.config.ts`, `tsconfig.json`, or any `src/**` file.
- Editing `setup.sh` or `scripts/setup/install_frontend.sh`.
- Adding ESLint/Prettier config files or a `lint` npm script (this plan only records the decision).
- Any frontend-component refactor, API-schema change, or i18n-string edit (owned by sibling Phase-5 subtasks).

---

## 4. Non-Goals

- **Not** replacing Vite/Vitest with another toolchain. The existing stack is `KEEP`.
- **Not** introducing `pnpm` or `yarn`. Only `npm` is available in this repo's CI (verified: docs workflows use `npm ci`; no `pnpm`). The plan must standardize on `npm`.
- **Not** committing `static/dist/` build artifacts to git, and **not** un-ignoring `node_modules/`.
- **Not** changing the dashboard API surface (`ari/viz/routes.py` + `api_*.py`), the `services/api.ts` client, or any endpoint schema — those are owned by subtasks 020–024 and other Phase-5 items.
- **Not** making the interactive installer (`install_frontend.sh`) fatal on build failure; its warn-and-continue behaviour is intentional for laptops without Node.
- **Not** authoring a separate dependency-update policy (`dependabot.yml` is absent and is owned by subtask 052).

---

## 5. Current Files / Directories to Inspect

Real repository paths the implementer must read before writing the plan:

**Frontend build/test config (verified present):**
- `ari-core/ari/viz/frontend/package.json` — scripts + deps (no `lint` script)
- `ari-core/ari/viz/frontend/package-lock.json` — 140 KB, **tracked** (enables `npm ci`)
- `ari-core/ari/viz/frontend/vite.config.ts` — `base:/static/dist/`, `outDir:../static/dist`
- `ari-core/ari/viz/frontend/vitest.config.ts` — jsdom, include globs
- `ari-core/ari/viz/frontend/vitest.setup.ts` — jest-dom + fetch/EventSource stubs
- `ari-core/ari/viz/frontend/tsconfig.json` — `strict`, `noUnusedLocals`, `noEmit`
- `ari-core/ari/viz/frontend/src/components/PaperBench/__tests__/PaperBenchWizard.test.tsx`
- `ari-core/ari/viz/frontend/src/components/PaperBench/__tests__/PaperImportDialog.test.tsx`

**Serve-time + build-integration (verified):**
- `ari-core/ari/viz/server.py` (`:57` `DASHBOARD_PATH` — file does not exist; `:58` `REACT_DIST_DIR`; `:59` `REACT_INDEX`)
- `scripts/setup/install_frontend.sh` — `npm install` + `npx vite build`, non-fatal
- `setup.sh` (step 5/6 loads `install_frontend.sh`)
- `.gitignore` (`:113` `node_modules/`, `:114` `static/dist/`)

**Test that depends on a build existing (verified):**
- `ari-core/tests/test_dashboard_html.py` — asserts `static/dist/index.html` + `dist/assets/*.{js,css}`
- `ari-core/tests/README.md:39` — lists `test_dashboard_html.py`

**CI reference patterns to reuse (verified):**
- `.github/workflows/docs-sync.yml` (`:79-91` `vitepress-build` job — the closest existing Node/npm CI pattern)
- `.github/workflows/pages.yml` (`:38-42` `setup-node@v4`, `node-version:20`, npm cache)
- `.github/workflows/refactor-guards.yml` — the ignore-list containing `test_dashboard_html`; the `git merge-base` diff idiom; the path-exclude allow-list convention
- `.github/workflows/docs-change-coupling.yml` (header ~lines 40-47) — documents why `github.event.pull_request.base.sha` is preferred over `origin/<base_ref>` for diff-scoped jobs

**Companion design docs (read for coherence, do not edit):**
- `docs/refactoring/008_viz_dashboard_refactoring_plan.md`
- `docs/refactoring/012_github_workflow_integration_plan.md`
- `docs/refactoring/014_dashboard_ux_refactoring_plan.md`
- `docs/refactoring/subtasks/032_add_quality_script_ci_plan.md` (plan-only precedent)
- `docs/refactoring/subtasks/045_inventory_github_workflows.md`, `049_add_contract_check_workflows.md`, `050_add_docs_sync_workflow.md`, `052_add_dependabot_and_actions_policy.md`

**Output location for the plan produced by executing 066:**
- `docs/refactoring/reports/` (exists; empty as of 2026-07-01)

---

## 6. Current Problems

1. **Zero CI coverage of the dashboard frontend.** No workflow runs `typecheck`, `vitest`, or `vite build` against `ari-core/ari/viz/frontend/`. A type error, a failing component test, or a build-breaking change can merge with all checks green. This is the core gap subtask 066 must close (via a plan, then a later implementation subtask).
2. **The one pytest that *would* catch a broken build is disabled.** `test_dashboard_html` is in `refactor-guards.yml`'s ignore set because CI never runs the Vite build, so `static/dist/index.html` is absent in the runner. The build assertion is therefore dead weight until a build step exists.
3. **Non-deterministic install path.** `install_frontend.sh` uses `npm install`, which can mutate the tracked `package-lock.json`. CI must use `npm ci` (fails if lockfile and `package.json` disagree; never mutates the lockfile) to guarantee reproducibility.
4. **Build failures are silently swallowed at install time.** `install_frontend.sh` warns-and-continues on `vite build` failure. Fine for the installer, but there is no *other* place that turns a broken build into a hard failure — so CI must own that.
5. **Frontend i18n key drift is unguarded.** `en.ts` (444) vs `ja.ts`/`zh.ts` (441) differ by 3 lines; the existing `scripts/docs/check_i18n_js.py` gate covers the *docs* site's `*.js` surfaces, **not** the frontend's `src/i18n/*.ts`. No gate covers frontend translation parity. (Flagged `REVIEW_REQUIRED`; not necessarily in the first CI job.)
6. **Skeleton misinformation.** The refactoring skeleton's "committed node_modules" claim is false and would send an implementer down a non-existent cleanup path. The plan must record the corrected state so no one wastes effort.

---

## 7. Proposed Design / Policy

The plan that subtask 066 produces must record the following policy. All of it is *design*, implemented later.

### 7.1 Build contract (`KEEP` the toolchain, `ADAPT` the invocation)

- **Toolchain:** keep Vite 5 / Vitest 2 / TS 5.5 exactly as configured. No tool swaps.
- **Install:** CI uses `npm ci --prefix ari-core/ari/viz/frontend` (deterministic; requires the tracked `package-lock.json`, which exists). The interactive installer keeps `npm install` — unchanged.
- **Node version:** pin `node-version: 20` to match `docs-sync.yml`/`pages.yml`, so the repo has one Node major across all jobs.
- **Artifact policy:** `ari-core/ari/viz/static/dist/` is a generated artifact; it stays git-ignored (`.gitignore:114`) and is produced by CI on demand, never committed. `node_modules/` stays git-ignored (`.gitignore:113`).

### 7.2 CI job spec (the heart of the plan)

Recommended shape (the plan records it precisely; a later subtask writes the YAML):

- **Home:** a **new** workflow file `.github/workflows/frontend.yml`. Rationale: keeps the dashboard build isolated from the docs and refactor-guard concerns, and gives the Phase-9 implementer a single well-scoped file to add. (Alternative — appending a job to `refactor-guards.yml` — is recorded but not recommended, to avoid coupling a Node job to that file's Python-sandbox job.)
- **Trigger:** `pull_request` to `main` (and `refactoring`, matching `refactor-guards.yml`'s branch set, so Phase-5 PRs on the refactoring branch are gated too).
- **Path filter:** `paths: ['ari-core/ari/viz/frontend/**']` so the job only runs when frontend files change (keeps unrelated PRs fast).
- **Runner setup:** `actions/checkout@v4` → `actions/setup-node@v4` with `node-version: 20`, `cache: npm`, `cache-dependency-path: ari-core/ari/viz/frontend/package-lock.json`.
- **Steps (all fatal — the job fails on any non-zero):**
  1. `npm ci --prefix ari-core/ari/viz/frontend`
  2. `npm run --prefix ari-core/ari/viz/frontend typecheck` (`tsc --noEmit`)
  3. `npm run --prefix ari-core/ari/viz/frontend test` (`vitest run`)
  4. `npm run --prefix ari-core/ari/viz/frontend build` (`vite build`)

The `--prefix` idiom is exactly how the docs workflows already invoke npm (`npm ci --prefix docs`, `npm run --prefix docs docs:build`), so it is an established pattern in this repo.

### 7.3 `test_dashboard_html` reconciliation (record a decision)

Two viable options; the plan must pick one:
- **Option A (recommended):** rely on the FE job's `npm run build` step to gate the bundle, and **keep** `test_dashboard_html` ignored in `refactor-guards.yml` (that pytest runs in a Python-only runner with no Node install, so building there would be redundant and slow). The plan notes that step 4 of §7.2 fully subsumes the intent of `test_dashboard_html`.
- **Option B:** in a follow-up owned by the Phase-9 subtask, drop `test_dashboard_html` from the ignore list *only* in a runner that first runs the Vite build. More moving parts; not recommended.

### 7.4 `REVIEW_REQUIRED` backlog (documented, not implemented)

- **ESLint/Prettier:** absent today. `tsconfig` strictness already catches unused vars and type errors, so lint is additive polish, not a correctness gate. Record as a future subtask; do **not** add config or a `lint` script in the first CI job.
- **Frontend-i18n key parity:** a `check_i18n_js`-style gate over `src/i18n/{en,ja,zh}.ts` would catch the 444/441 drift. Record as `REVIEW_REQUIRED`; if adopted, prefer reusing the existing `scripts/docs/check_i18n_js.py` approach rather than a new bespoke checker.

### 7.5 Diff-scoped idiom (if any step becomes diff-scoped)

If a later step needs a merge-base diff (e.g. a lint-changed-files gate), it must use `github.event.pull_request.base.sha` (immutable for the run), per the guidance documented in `docs-change-coupling.yml`'s header — not `refactor-guards.yml`'s `origin/${{ github.base_ref }}` idiom.

---

## 8. Concrete Work Items

The executing session for subtask 066 performs **only** these (all produce the single plan `.md`, no code/YAML):

1. **Create** `docs/refactoring/reports/<NNN>_dashboard_build_and_ci_plan.md` (pick the next free report index; the directory is currently empty).
2. **Record the build contract** (§7.1): `npm ci`, Node 20, artifact/ignore policy, corrected node_modules state.
3. **Write the exact CI-job spec** (§7.2) as a ready-to-transcribe block: workflow name, triggers, path filter, cache key, and the four fatal steps with the `--prefix ari-core/ari/viz/frontend` invocations.
4. **Record the `test_dashboard_html` decision** (§7.3) with the chosen option and its follow-up owner.
5. **Record the `REVIEW_REQUIRED` backlog** (§7.4) for ESLint/Prettier and frontend-i18n parity, each with a recommended default.
6. **Cross-reference** the Phase-9 GitHub-integration subtasks (Section 15) so the workflow file is added exactly once, and note reuse of `setup-node@v4` / Node 20 / npm-cache / `--prefix` patterns from `docs-sync.yml` + `pages.yml`.
7. **State the correction** to the skeleton's false "committed node_modules" claim so no downstream effort is wasted.
8. **Add a self-check checklist** the workflow-implementation subtask can tick off (job runs on frontend-only PRs, all four steps fatal, cache hits on the frontend lockfile).

---

## 9. Files Expected to Change

**Authoring this subtask (066):**
- **Create:** `/home/t-kotama/workplace/ARI/docs/refactoring/subtasks/066_add_dashboard_build_and_ci_plan.md` (this file) — the only file changed.

**Executing subtask 066 later (still plan-only):**
- **Create:** `docs/refactoring/reports/<NNN>_dashboard_build_and_ci_plan.md` (one new Markdown design doc).

**Explicitly NOT changed by 066 (owned by later implementation subtasks):**
- `.github/workflows/frontend.yml` — does not exist; created by a Phase-9 workflow-implementation subtask, not here.
- `.github/workflows/refactor-guards.yml` — untouched (any `test_dashboard_html` ignore-list edit is a later, separately-owned change).
- `ari-core/ari/viz/frontend/package.json`, `vite.config.ts`, `vitest.config.ts`, `tsconfig.json`, `src/**` — untouched.
- `scripts/setup/install_frontend.sh`, `setup.sh` — untouched.
- `.gitignore` — untouched (frontend ignores are already correct at lines 113–114).

---

## 10. Files / APIs That Must Not Be Broken

This subtask writes no code, so nothing is at runtime risk. The plan it produces must nonetheless **preserve these contracts** and forbid any later step from breaking them without a compatibility note:

- **Dashboard build output contract:** `ari-core/ari/viz/server.py` serves `static/dist/index.html` (`REACT_DIST_DIR`, `server.py:58`). The CI build must keep producing `static/dist/` with `base:/static/dist/`; do not change `vite.config.ts`'s `outDir`/`base`.
- **Dashboard API + client contract:** `ari/viz/routes.py` + `api_*.py` endpoints and `services/api.ts` (863 lines) stay unchanged; a build job must not alter the API surface.
- **npm-only CI convention:** existing docs workflows use `npm`; the plan must not introduce `pnpm`/`yarn` and break that convention.
- **Installer contract:** `setup.sh` step 5/6 → `install_frontend.sh` must keep working on machines without Node (warn-and-continue). CI fatality is additive, not a change to the installer.
- **CLI / public API / MCP / checkpoint / config contracts:** untouched by a frontend-build job; the plan must not propose any change to `ari` CLI, `ari.public.*`, `ari-skill-*` servers, or checkpoint/config formats.
- **Existing 5 workflows:** must not be rewritten; a new `frontend.yml` is additive.

---

## 11. Compatibility Constraints

- **Deterministic install requires the lockfile.** `npm ci` fails if `package-lock.json` is missing or inconsistent with `package.json`. It is tracked (140 KB) and consistent today; the plan must warn that any future `package.json` change must be committed together with a regenerated `package-lock.json`, or CI will break.
- **Node major must stay aligned.** Node 20 is used by both existing Node jobs; the frontend job must match to avoid a second Node toolchain in CI.
- **Path-filtered jobs and required-checks.** If the job is later made a *required* status check, GitHub treats a path-filtered job that is skipped as "pending". The plan must flag this (either don't mark it required, or use a always-runs guard job) so frontend-untouched PRs are not blocked forever.
- **No secrets needed.** The build/typecheck/test/build steps need no tokens, API keys, or network beyond the npm registry; the plan must confirm the job requires no `secrets`.
- **Artifact hygiene stays intact.** `.gitignore:113-114` already ignore `node_modules/` and `static/dist/`; the plan must not propose committing either.

---

## 12. Tests to Run

Authoring this subtask changes only one Markdown file, so no code tests are strictly required. Still, the executing session must confirm the surrounding tree is untouched and green:

**Python (repo root):**
- `python -m compileall .` — byte-compiles all `.py`; confirms no accidental Python edits.
- `pytest -q` (or the sandboxed `pytest ari-core/tests/ -q` the CI uses) — baseline green; confirm `test_dashboard_html` status is unchanged (still ignored in `refactor-guards.yml`).
- `ruff check .` — lint clean; confirms no stray Python touched.

**Frontend (the toolchain this plan targets — run to validate the CI spec is executable):**
- `npm ci --prefix ari-core/ari/viz/frontend`
- `npm run --prefix ari-core/ari/viz/frontend typecheck` (`tsc --noEmit`)
- `npm run --prefix ari-core/ari/viz/frontend test` (`vitest run` — the 2 PaperBench tests)
- `npm run --prefix ari-core/ari/viz/frontend build` (`vite build` → `static/dist/`)

**Docs/planning gates (this file is a new Markdown doc):**
- `python scripts/readme_sync.py --check` — per-directory `## Contents` indexes still match; run `--write` if the subtasks directory has a tracked index that must list this file.
- `python scripts/docs/check_doc_links.py` (advisory) — any links added in the plan resolve.

Note: these frontend commands are exactly what the CI-job spec (§7.2) prescribes, so running them locally doubles as verification that the plan is executable.

---

## 13. Acceptance Criteria

Subtask 066 (this planning subtask) is complete when:

1. `docs/refactoring/subtasks/066_add_dashboard_build_and_ci_plan.md` exists, follows the 17-section template, and is self-contained.
2. The plan specifies the **exact CI-job spec** (§7.2): file (`frontend.yml`), trigger, `paths` filter, `setup-node@v4` + Node 20 + npm cache keyed on `ari-core/ari/viz/frontend/package-lock.json`, and the four fatal `--prefix` steps (`npm ci`, `typecheck`, `test`, `build`).
3. The plan records the **`test_dashboard_html` decision** (keep-ignored + rely on the build step, or un-ignore behind a build — one chosen and justified).
4. The plan records the **`REVIEW_REQUIRED`** backlog (ESLint/Prettier, frontend-i18n parity) with recommended defaults, and does **not** implement them.
5. The plan explicitly **corrects** the skeleton's false "committed node_modules" claim and confirms `.gitignore:113-114` + tracked `package-lock.json`.
6. The plan writes **no** YAML, **no** frontend/source/config edits, and **no** installer edits (verified by `git status` showing only the two `.md` files).
7. `python -m compileall .`, `pytest -q`, and `ruff check .` remain green; the four frontend commands in Section 12 succeed on a clean checkout.

---

## 14. Rollback Plan

Trivial: this subtask adds Markdown only.
- **Authoring rollback:** `git rm docs/refactoring/subtasks/066_add_dashboard_build_and_ci_plan.md` (and, if the executing session ran, the report `.md` under `docs/refactoring/reports/`), then `git commit`. No runtime, workflow, or build state is affected.
- **No migration, no data, no schema, no config** is touched, so there is nothing to reverse beyond deleting the file(s).
- When the *implementation* subtask later adds `.github/workflows/frontend.yml`, its own rollback is `git rm` of that single new workflow (additive; removing it restores the exact pre-existing 5-workflow CI).

---

## 15. Dependencies

Per the provided dependency graph, the only hard predecessor is:

- **059 → 066.** Subtask **059** is the Phase-5 dashboard-frontend inventory/foundation subtask (parent of all Phase-5 children 060–073; it is in the "must precede any runtime code change" set: `001, 002, 020, 036, 045, 053, 059, 060, 067`). Its exact human title is not in the provided facts; it is referenced here strictly as the sole direct predecessor the graph specifies. Subtask 066 must not start until 059's dashboard-frontend inventory is available.

Sibling Phase-5 subtasks under the same parent (**059 → 060…065, 067…073**) are **peers**, not blockers, but the plan should stay coherent with them (they cover other dashboard-frontend concerns).

Soft / coordinate-with (not graph-hard blockers — cross-cutting CI ownership; the plan must reference them so the workflow file is added exactly once and reuses proven patterns):
- **045** `inventory_github_workflows` — the source of the "5 workflows, all docs-oriented" baseline this plan builds on.
- **046** `design_quality_ci_integration` and **032** `add_quality_script_ci_plan` — the master CI-integration design + plan-only precedent to mirror.
- **049** `add_contract_check_workflows`, **050** `add_docs_sync_workflow`, **052** `add_dependabot_and_actions_policy` — the Phase-9 workflow-implementation subtasks that own the actual YAML; the FE-build job created from this plan must be wired by (or coordinated with) them so it is not duplicated.

No subtask depends on 066 in the provided graph (066 is a leaf under 059).

---

## 16. Risk Level

**Risk: Low. Changes runtime code: No.**

Authoring subtask 066 modifies exactly one Markdown file and touches no runtime code, imports, prompts, configs, workflows, frontend source, or directory names. When *executed*, the subtask produces one additional Markdown design doc under `docs/refactoring/reports/` and still writes no YAML and no code — so it too changes no runtime code. The material risk is entirely deferred to the later implementation subtask that transcribes the CI-job spec into `.github/workflows/frontend.yml`; even that is low-risk and additive (a new, path-filtered, secret-free job that removing fully reverts).

---

## 17. Notes for Implementer

- **Do not confuse the two npm surfaces.** `docs/` (VitePress) already has CI (`docs-sync.yml` `vitepress-build`, `pages.yml`). This subtask is about the *dashboard* frontend at `ari-core/ari/viz/frontend/`, which has **none**. Reuse the docs jobs' `setup-node@v4` / Node 20 / npm-cache / `--prefix` mechanics, but key the cache on `ari-core/ari/viz/frontend/package-lock.json`, not `docs/package-lock.json`.
- **The lockfile already supports `npm ci`.** `ari-core/ari/viz/frontend/package-lock.json` is tracked and consistent; you do not need to generate it. Just switch the *CI* install to `npm ci` (leave `install_frontend.sh`'s `npm install` alone).
- **`dashboard.html` is a phantom fallback.** `server.py:57` references `.../dashboard.html`, but the file does not exist. Do not design around a fallback page; the real serve contract is `static/dist/`.
- **`test_dashboard_html` is the canary.** It is ignored in `refactor-guards.yml` only because CI never builds the frontend. Once §7.2 step 4 (`vite build`) runs in CI, the build is guaranteed; recommend Option A (keep the pytest ignored, rely on the build step) to avoid installing Node into the Python sandbox job.
- **Correct the skeleton.** `node_modules/` is **not** committed (`.gitignore:113`); `static/dist/` is **not** committed (`.gitignore:114`). Record this so no one adds a bogus "remove vendored deps" step.
- **Only 2 frontend tests exist today** (both PaperBench). `npm test` runs fast; the `test` step will pass on the current tree. If a peer Phase-5 subtask adds tests, the same job covers them automatically (Vitest `include` globs already match `src/**/*.test.tsx`).
- **Keep it npm-only.** No `pnpm`/`yarn` in this repo's CI; standardize on `npm ci`/`npm run`.
- **Path-filter + required-checks interaction.** If the FE job is made a required check, a frontend-untouched PR (skipped job) can hang as "pending". Flag this and either leave it non-required or add an always-runs guard job that resolves to success.
- **Precedent to imitate:** `docs/refactoring/subtasks/032_add_quality_script_ci_plan.md` is the closest sibling — a plan-only CI subtask that writes a Markdown spec and zero YAML. Match its tone and its explicit "non-actions" framing.

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **066** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
