# Subtask 033: Add Generated Files Gitignore Policy

- **Phase:** Phase 2 — Repository Hygiene
- **Classification:** ADAPT (consolidate + extend existing `.gitignore` files) plus KEEP (all currently tracked artifacts stay tracked)
- **Changes runtime code:** No (see Section 16)

---

## 1. Goal

Establish a single, documented, repository-wide **policy for ignoring generated / build / runtime
artifacts**, and bring every `.gitignore` in the ARI-owned tree into conformance with it.

Concretely:

1. Define one canonical "generated files" ignore contract (Python bytecode/build, test caches,
   lint caches, frontend build output + `node_modules`, VitePress build, LaTeX/HTML report
   intermediates, checkpoint/experiment/staging runtime dirs, container images, secrets).
2. **De-duplicate** the root `/home/t-kotama/workplace/ARI/.gitignore` (it repeats 9 patterns
   verbatim — see Section 6).
3. **Fill the four missing skill `.gitignore` files** (`ari-skill-plot`, `ari-skill-replicate`,
   `ari-skill-transform`, `ari-skill-web` currently have none) and normalize the three minimal /
   internally-duplicated ones (`ari-skill-coding`, `ari-skill-benchmark`, `ari-skill-vlm`) to the
   canonical skill template that the other 10 skills already share.
4. **Close two real gaps** in the root file: `.ruff_cache/` (ruff is the active linter) and
   `.coverage` / `htmlcov/` are only ignored today by side effects, not by an explicit root rule.
5. Optionally add a CI guard asserting that **no ignored file is ever tracked**
   (`git ls-files -i -c --exclude-standard` returns empty — it does today; keep it that way).

The end state is a coherent, low-duplication ignore policy that a fresh contributor can read once
and rely on, and that CI can defend.

## 2. Background

`.gitignore` in this repo grew organically. The root file
(`/home/t-kotama/workplace/ARI/.gitignore`, 138 lines) is well-commented but has accumulated
duplicate blocks from repeated "add Python/build ignores" edits. There are **17 `.gitignore` files
in the ARI-owned tree** (root + `ari-core/` + `docs/` + `report/` + 10 of the 14 `ari-skill-*`
packages); the remaining 4 skills have none, and 3 of the existing skill files diverge from the
otherwise-uniform skill template.

Verified baseline facts (planning date 2026-07-01, read-only):

- `git ls-files -i -c --exclude-standard` returns **0** files — i.e. **nothing currently tracked is
  also ignored**. This is the healthy invariant this subtask must preserve and, ideally, defend in
  CI.
- `git status --porcelain --ignored` reports **128** ignored on-disk entries (all `__pycache__/`,
  `.pytest_cache/`, `.ruff_cache/`, `.venv/`, `node_modules/`, `*.egg-info/`, `ari-core/ari/viz/static/`,
  runtime dirs) — the ignore rules are actively doing their job.
- No `.gitattributes` file exists anywhere in the ARI-owned tree.
- The prior storage-area finding confirms `checkpoints/`, `workspace/`,
  `workspace/{checkpoints,experiments,staging}/` are all ignored and carry **zero tracked files**,
  so this subtask has **no `git rm --cached` migration cost** — it is purely additive/consolidating.

This is Phase 2 (Repository Hygiene). It is deliberately narrow: policy + `.gitignore` text only.

## 3. Scope

In scope:

- The root `.gitignore` and every ARI-owned per-directory `.gitignore` (see Section 5 for the exact
  file list).
- A written policy statement (where generated artifacts live and why each is ignored). Preferred
  home: a short "Generated & ignored files" subsection in `CONTRIBUTING.md`, or a dedicated
  `docs/refactoring/` note. (Chosen at implementation time; keep it in ARI canonical English.)
- OPTIONAL: a minimal CI guard that fails if any tracked file becomes ignored (a one-line
  `git ls-files -i -c --exclude-standard` assertion). This is a nice-to-have, not required for
  acceptance.

## 4. Non-Goals

- **NOT** removing or un-tracking any currently tracked file. All intentionally tracked artifacts
  (Section 10) stay tracked.
- **NOT** implementing the missing `scripts/check_directory_policy.py` or any of the other MISSING
  quality scripts listed in the ground-truth facts — those are separate subtasks. This subtask may
  reference a directory/ignore policy check but must not build that checker.
- **NOT** touching runtime code, imports, prompts, configs, workflows (beyond the optional
  additive CI guard step), frontend source, or directory names.
- **NOT** introducing a global `core.excludesFile` requirement or rewriting the vendored
  `.gitignore` files under `ari-skill-*/vendor/**`, `.venv/`, `ari-skill-idea/vendor/virsci/**`, or
  `ari-skill-paper-re/vendor/paperbench/**` — those belong to third-party subtrees and are out of
  scope.
- **NOT** adding a `.gitattributes` policy (line-endings / linguist) — out of scope; mention only as
  a possible follow-up in Section 17.

## 5. Current Files / Directories to Inspect

ARI-owned `.gitignore` files (verified present unless noted):

| Path | Size / note |
| --- | --- |
| `/home/t-kotama/workplace/ARI/.gitignore` | 138 lines; the primary target. Contains 9 duplicate patterns (Section 6). |
| `/home/t-kotama/workplace/ARI/ari-core/.gitignore` | ~60 lines; the most complete per-package file. Has load-bearing negations (Section 10). |
| `/home/t-kotama/workplace/ARI/docs/.gitignore` | VitePress: `node_modules/`, `.vitepress/dist/`, `.vitepress/cache/`. |
| `/home/t-kotama/workplace/ARI/report/.gitignore` | LaTeX + tex4ht/make4ht intermediates, generated `main.css/main.html`, `html/{en,ja,zh}/`, reference caches. Has load-bearing `!…/main.pdf` and `!…/.gitkeep` negations. |
| `/home/t-kotama/workplace/ARI/ari-skill-benchmark/.gitignore` | 5 lines — minimal; normalize to template. |
| `/home/t-kotama/workplace/ARI/ari-skill-coding/.gitignore` | 5 lines — minimal; normalize to template. |
| `/home/t-kotama/workplace/ARI/ari-skill-evaluator/.gitignore` | canonical ~30-line skill template. |
| `/home/t-kotama/workplace/ARI/ari-skill-hpc/.gitignore` | canonical template. |
| `/home/t-kotama/workplace/ARI/ari-skill-idea/.gitignore` | canonical template. |
| `/home/t-kotama/workplace/ARI/ari-skill-memory/.gitignore` | canonical template. |
| `/home/t-kotama/workplace/ARI/ari-skill-orchestrator/.gitignore` | canonical template. |
| `/home/t-kotama/workplace/ARI/ari-skill-paper/.gitignore` | canonical template. |
| `/home/t-kotama/workplace/ARI/ari-skill-paper-re/.gitignore` | canonical template. |
| `/home/t-kotama/workplace/ARI/ari-skill-vlm/.gitignore` | 12 lines with **internal duplicates** (`.venv/`, `__pycache__/`, `*.pyc` repeated); normalize. |
| `/home/t-kotama/workplace/ARI/ari-skill-plot/.gitignore` | **does not exist** — create. |
| `/home/t-kotama/workplace/ARI/ari-skill-replicate/.gitignore` | **does not exist** — create. |
| `/home/t-kotama/workplace/ARI/ari-skill-transform/.gitignore` | **does not exist** — create. |
| `/home/t-kotama/workplace/ARI/ari-skill-web/.gitignore` | **does not exist** — create. |

Also inspect (read-only, to avoid over-ignoring — do NOT modify):

- `/home/t-kotama/workplace/ARI/scripts/git-hooks/pre-commit` — non-blocking hook running
  `readme_sync.py --write`; it does not touch `.gitignore` but confirms the hook mechanism.
- `/home/t-kotama/workplace/ARI/.github/workflows/refactor-guards.yml` and `readme-sync.yml` — the
  existing CI gates; the optional ignore-hygiene assertion would slot in here or as a new step.
- Config/data dirs that are **tracked and must stay tracked**:
  `ari-core/ari/config/`, `ari-core/ari/configs/`, `ari-core/config/`. (Note: there is **no
  `sonfigs/`** directory anywhere in the repo — the "sonfigs" token in the master prompt is a
  hypothesized typo that does not exist here; do not add any `config*`/`sonfig*` glob to any ignore
  file, or you will hide tracked rubric/profile/default data.)

## 6. Current Problems

1. **Root `.gitignore` self-duplication (confirmed).** Nine patterns appear twice:
   `__pycache__/` (lines 6 & 87), `*.py[cod]` (7 & 88), `*.pyo` (8 & 89), `*.egg-info/` (11 & 90),
   `dist/` (12 & 93), `build/` (13 & 94), `.env` (14 & 48), `*.egg` (15 & 91), and `*.out`
   (21 & 117). `*.out` additionally overlaps with the SLURM `slurm-*.out` and `*.err` rules. This is
   noise that obscures intent and invites drift.
2. **Four skills have no `.gitignore` at all** (`plot`, `replicate`, `transform`, `web`). Their
   Python bytecode / `.venv` / `*.egg-info` are only ignored because the **root** file happens to
   cover `__pycache__/`, `*.egg-info/`, etc. This works today but is inconsistent with the other 10
   skills and fragile (e.g. `.venv/` is only ignored at root via lines 108–109, not per-skill).
3. **Skill `.gitignore` divergence.** 10 skills share an identical ~30-line template; `benchmark`
   and `coding` carry only a 5-line subset; `vlm` carries a 12-line file with **duplicate lines
   inside itself**. No single source of truth for "what a skill ignores".
4. **`.ruff_cache/` is not in the root `.gitignore`.** It is ignored only because ruff
   auto-generates `.ruff_cache/.gitignore` containing `*`. Since ruff **is** the active linter
   (facts: "ruff IS available"), the root file should own this rule explicitly rather than rely on a
   tool-created side file.
5. **`.coverage` / `htmlcov/` are ignored only in `ari-core/.gitignore`**, not at root, even though
   test runs can produce them from the repository root.
6. **No written policy.** There is no document a contributor can read to learn what is generated vs.
   tracked; the rules are spread across 17 files with inline comments only.
7. **No CI defense of the invariant.** `git ls-files -i -c` is clean today, but nothing prevents a
   future commit from tracking a file that a later ignore rule would shadow (a classic source of
   "works on my machine" drift).

None of these is a correctness bug today — the tree is clean — but they are exactly the low-grade
hygiene debt Phase 2 exists to retire.

## 7. Proposed Design / Policy

### 7.1 Canonical policy (the text to document)

A file is **ignored** if and only if it is regenerated deterministically from tracked sources or is
machine/run-specific. Categories:

| Category | Representative patterns | Owned by |
| --- | --- | --- |
| Python bytecode / build | `__pycache__/`, `*.py[cod]`, `*.pyo`, `*.pyd`, `*.egg`, `*.egg-info/`, `.eggs/`, `dist/`, `build/` | root + every package |
| Test / lint caches | `.pytest_cache/`, `.ruff_cache/`, `.coverage`, `htmlcov/` | root + package |
| Virtualenvs / setup | `.venv/`, `venv/`, `.ari_python` | root + package |
| Secrets | `.env`, `*.env.local`, `*.key`, `*.pem`, `*.token` | root (single source) |
| Frontend build | `node_modules/`, `ari-core/ari/viz/frontend/dist/`, `.vite/`, `viz/static/dist/`, `vite.config.ts.timestamp-*.mjs` | root + `ari-core` |
| Docs (VitePress) build | `docs/node_modules/`, `docs/.vitepress/dist/`, `docs/.vitepress/cache/`, `/_site/` | root + `docs` |
| Report (LaTeX/HTML) build | `*.aux/*.bbl/*.blg/...`, generated `main.css/main.html`, `html/{en,ja,zh}/`, reference caches | `report` |
| Runtime storage | `checkpoints/`, `workspace/`, `experiments/`, `staging/`, `logs/`, `*.log`, `*.out`, `*.err`, `slurm-*.out`, `memory/` | root |
| Container images | `*.sif`, `/containers/*`, `/ari-core/containers/*` | root |
| External/local-only inputs | `HPC_PaperBench_Final_Proposal_for_Professors.pdf`, `SC41406.2024.*.pdf` | root |

**Explicit KEEP exceptions (negations) that must survive** (these encode "generated-looking but
tracked" carve-outs):

- `!/containers/README.md`, `!/ari-core/containers/README.md` (root)
- `!ari-core/ari/memory/` — source package, not the runtime `memory/` store (root)
- `!ari/viz/frontend/src/components/PaperBench/results/` and `/**` — a **source** component dir that
  would otherwise be caught by `results*/` (`ari-core`)
- `!en/main.pdf`, `!ja/main.pdf`, `!zh/main.pdf`, `!shared/references_pdf/.gitkeep`,
  `!shared/references_pdf/README.md`, `!shared/references_pdf/*.pdf.meta.yaml` (`report`)

### 7.2 Root `.gitignore` — collapse to de-duplicated sections

Rewrite the root file so each pattern appears once, grouped by the categories above, comments
preserved. Add the two missing rules: `.ruff_cache/` and `.coverage` / `htmlcov/`. Keep all
existing negations byte-for-byte. Net effect: fewer lines, zero behavior change except the two new
(strictly additive) ignores.

### 7.3 Canonical skill `.gitignore` template

Adopt the ~30-line file already used by `evaluator/hpc/idea/memory/orchestrator/paper/paper-re` as
**the** skill template (Python + env + logs/runtime + test cache + editor). Apply it verbatim to:

- the 4 skills missing a file (`plot`, `replicate`, `transform`, `web`), and
- the 3 divergent files (`benchmark`, `coding`, `vlm`) — replacing their minimal/duplicated content.

Do **not** touch the vendored `.gitignore` files under `*/vendor/**`.

### 7.4 Optional CI guard (recommended, not required)

Add one step to an existing workflow (e.g. `refactor-guards.yml`) or a small script:

```bash
# Fail if any tracked file is also matched by an ignore rule.
leaked="$(git ls-files -i -c --exclude-standard)"
if [ -n "$leaked" ]; then echo "Tracked files are gitignored:"; echo "$leaked"; exit 1; fi
```

This defends the invariant established in Section 2 without building the larger
`check_directory_policy.py` (a separate subtask).

## 8. Concrete Work Items

1. **Document the policy** (Section 7.1) in `CONTRIBUTING.md` (new "Generated & ignored files"
   subsection) or a dedicated `docs/refactoring/` note. English only.
2. **De-duplicate the root `.gitignore`**: remove the 9 duplicate patterns (keep the first, better-
   commented occurrence), regroup by category, preserve every comment and every negation.
3. **Add `.ruff_cache/`** and **`.coverage` / `htmlcov/`** to the root `.gitignore`.
4. **Create** `ari-skill-plot/.gitignore`, `ari-skill-replicate/.gitignore`,
   `ari-skill-transform/.gitignore`, `ari-skill-web/.gitignore` from the canonical skill template
   (Section 7.3).
5. **Normalize** `ari-skill-benchmark/.gitignore`, `ari-skill-coding/.gitignore`, and
   `ari-skill-vlm/.gitignore` to the canonical template (fixes `vlm`'s internal duplicates).
6. **Verify no regression**: run `git status --porcelain` (must be clean of newly-untracked source),
   and `git ls-files -i -c --exclude-standard` (must remain empty). Spot-check that
   `git check-ignore -v` still does NOT match any of the KEEP paths in Section 10 (especially
   `ari-core/ari/viz/frontend/src/components/PaperBench/results/ResultsView.tsx`,
   `report/en/main.pdf`, `ari-core/ari/memory/__init__.py`, `containers/README.md`).
7. **(Optional)** Add the CI ignore-hygiene guard (Section 7.4) as a step in an existing workflow.
8. Update the relevant per-directory `README.md` `## Contents` index only if `readme_sync.py --check`
   requires it (new `.gitignore` files are dotfiles and are typically not indexed — confirm with the
   tool, do not hand-edit).

## 9. Files Expected to Change

Modify (text only):

- `/home/t-kotama/workplace/ARI/.gitignore` — de-duplicate + add `.ruff_cache/`, `.coverage`, `htmlcov/`.
- `/home/t-kotama/workplace/ARI/ari-skill-benchmark/.gitignore` — normalize to template.
- `/home/t-kotama/workplace/ARI/ari-skill-coding/.gitignore` — normalize to template.
- `/home/t-kotama/workplace/ARI/ari-skill-vlm/.gitignore` — normalize; remove internal duplicates.

Create:

- `/home/t-kotama/workplace/ARI/ari-skill-plot/.gitignore`
- `/home/t-kotama/workplace/ARI/ari-skill-replicate/.gitignore`
- `/home/t-kotama/workplace/ARI/ari-skill-transform/.gitignore`
- `/home/t-kotama/workplace/ARI/ari-skill-web/.gitignore`

Documentation (one of):

- `/home/t-kotama/workplace/ARI/CONTRIBUTING.md` — add "Generated & ignored files" subsection, **or**
- a new note under `/home/t-kotama/workplace/ARI/docs/refactoring/`.

Optional (only if the CI guard is adopted):

- `/home/t-kotama/workplace/ARI/.github/workflows/refactor-guards.yml` — add one hygiene step, **or**
- a new small script under `/home/t-kotama/workplace/ARI/scripts/`.

Explicitly NOT changed: `ari-core/.gitignore`, `docs/.gitignore`, `report/.gitignore` (already
correct and carry load-bearing negations — leave them), and all `*/vendor/**` and `.venv/**`
`.gitignore` files.

## 10. Files / APIs That Must Not Be Broken

This subtask must not cause any of the following **tracked** paths to become ignored (verify with
`git check-ignore -v <path>` returning no match after the change):

- Public contract surfaces are untouched by definition (no code changes): CLI `ari` (`ari.cli:app`),
  `ari.public.*`, the 14 `ari-skill-*` MCP servers, the dashboard API (`ari/viz/routes.py` +
  `api_*.py`), checkpoint/config file formats. None of these live under an ignore rule.
- Intentionally tracked "generated-looking" data (do NOT ignore):
  - `report/en/main.pdf`, `report/ja/main.pdf`, `report/zh/main.pdf`
  - `report/shared/assets/sample_paper.pdf`, `docs/assets/sample_paper.pdf`
  - `docs/assets/report/{en,ja,zh}.pdf`, `docs/public/report/{en,ja,zh}.pdf`
  - `ari-core/ari/viz/frontend/package-lock.json`, `docs/package-lock.json`, `requirements.lock`
  - `ari-core/ari/viz/frontend/src/components/PaperBench/results/**` (source component dir)
  - `ari-core/ari/memory/**` (source package, distinct from runtime `memory/`)
  - `containers/README.md`, `ari-core/containers/README.md`
  - `report/shared/references_pdf/{.gitkeep,README.md,*.pdf.meta.yaml}`
  - all tracked YAML under `ari-core/config/`, `ari-core/ari/config/`, `ari-core/ari/configs/`
- Scripts called by `.github/workflows/` (`scripts/readme_sync.py`,
  `scripts/docs/*.py`, `scripts/git-hooks/pre-commit`) must keep functioning; the ignore changes are
  orthogonal to them.

## 11. Compatibility Constraints

- **Additive-only ignore rules.** The two new root rules (`.ruff_cache/`, `.coverage`/`htmlcov/`)
  match only tool-generated caches that are already untracked; they cannot hide a tracked file
  (verified: `git ls-files` matches none of these).
- **De-duplication is behavior-preserving.** Removing a duplicate `.gitignore` line does not change
  git's matching outcome. Retain the first (better-commented) occurrence of each duplicated pattern.
- **Negations must be preserved byte-for-byte** and must remain positioned *after* the broad rule
  they carve out from (git evaluates last-match-wins). This is the one place a careless reorder could
  regress `PaperBench/results/**` or `main.pdf`.
- No public contract (CLI / `ari.public.*` / MCP tool schemas / dashboard API / checkpoint & config
  formats / documented import paths / `ari-skill-*` → `ari-core` interfaces) is touched, so no
  compatibility adapter is required.

## 12. Tests to Run

From the repo root:

- `python -m compileall .` — sanity (no `.py` changed, but confirms nothing was accidentally hidden
  from the tree).
- `pytest -q` — full suite must stay green (large suites include
  `ari-core/tests/test_server.py`, `test_gui_errors.py`, `test_workflow_contract.py`,
  `test_wizard.py`).
- `ruff check .` — lint clean (ruff is the active, installed linter).
- Frontend (since a skill/frontend-adjacent path is referenced): from
  `ari-core/ari/viz/frontend/`, `npm test` and `npm run build` should still pass — they do not depend
  on `.gitignore`, but run them to prove the frontend `results/` component dir is still visible to
  the build.
- Gitignore-specific verifications (should all hold):
  - `git ls-files -i -c --exclude-standard` → **empty**.
  - `git status --porcelain` → no source file newly appears as untracked/deleted.
  - `git check-ignore -v` returns **no match** for each path in Section 10.
  - `scripts/docs/check_readme_parity.py` and `scripts/readme_sync.py --check` → pass.
  - `.github/workflows/refactor-guards.yml` and `readme-sync.yml` → pass in CI.

## 13. Acceptance Criteria

1. Root `/home/t-kotama/workplace/ARI/.gitignore` contains **no duplicate non-comment patterns**
   (`grep -vE '^\s*#|^\s*$' .gitignore | sort | uniq -d` prints nothing).
2. `.ruff_cache/`, `.coverage`, and `htmlcov/` are explicit rules in the root `.gitignore`.
3. All **14** `ari-skill-*` packages have a `.gitignore`; the 7 previously
   missing/divergent ones (`plot`, `replicate`, `transform`, `web`, `benchmark`, `coding`, `vlm`)
   match the canonical skill template; no skill `.gitignore` has internal duplicate lines.
4. `git ls-files -i -c --exclude-standard` remains **empty**; `git check-ignore -v` matches none of
   the Section 10 KEEP paths.
5. `python -m compileall .`, `pytest -q`, and `ruff check .` all pass; frontend `npm test` /
   `npm run build` pass.
6. The generated-files policy is documented in English (CONTRIBUTING.md or a `docs/refactoring/`
   note).
7. If adopted, the optional CI hygiene guard passes and would fail on a deliberately-tracked ignored
   file (verify with a throwaway local test, then revert).

## 14. Rollback Plan

All changes are `.gitignore` text (plus optional doc / CI step). Rollback is a single
`git revert <commit>` or `git checkout -- <files>`; there is no data migration, no un-tracking, and
no runtime state to restore. Because the pre-change invariant (`git ls-files -i -c` empty) is
recorded here, a reviewer can confirm a clean revert instantly. If the optional CI guard proves
noisy, it can be removed independently without touching the `.gitignore` work.

## 15. Dependencies

Per the provided dependency graph, subtask **033 does not appear** as either a predecessor or a
successor of any node — it has **no hard graph dependencies** and **gates no other subtask**.

- It is **not** in the set of inventory subtasks that must precede runtime code changes
  (001, 002, 020, 036, 045, 053, 059, 060, 067), and it does not depend on any of them, because
  **033 changes no runtime code** (Section 16). It can therefore run at any point in Phase 2,
  early and in parallel with other hygiene subtasks.
- Soft/advisory relationship only: the broader repository-hygiene / directory-policy effort (the
  future `scripts/check_directory_policy.py`) may later consume the policy documented here, but that
  checker is out of scope and is **not** a blocker for 033.

## 16. Risk Level

**Risk: Low. Changes runtime code: No.**

Rationale: the only artifacts touched are `.gitignore` files (plus an optional doc paragraph and an
optional additive CI step). No Python/TS/config/workflow-logic changes. The single non-trivial
hazard is an over-broad or mis-ordered pattern accidentally ignoring a tracked source file — most
plausibly the PaperBench `results/**` source component dir or a `report/*/main.pdf`. This is fully
mitigated by (a) preserving negations byte-for-byte, (b) not adding any `results*/`, `config*/`, or
`*.pdf` rule at root, and (c) the `git check-ignore` / `git ls-files -i -c` verifications in
Sections 12–13.

## 17. Notes for Implementer

- **Do a dry-run diff first.** Before committing, run `git ls-files -i -c --exclude-standard`
  *after* staging the new/edited `.gitignore` files — it must still print nothing. If it prints a
  path, an ignore rule is too broad; fix or add a negation.
- **Keep the good comments.** The root file's category headers and the rationale comments (e.g. the
  container-README carve-out at lines 64–67, the external-PDF note at 125–131) are valuable — port
  them into the de-duplicated version, don't drop them.
- **The `*.out` rule is intentionally broad** (SLURM job output + compiled binaries). It appears
  three times today; keep exactly one occurrence and leave a comment noting the dual purpose so a
  future editor doesn't "helpfully" delete it.
- **`vlm` is the only skill file with internal duplicates** — replacing it wholesale with the
  canonical template is cleaner than surgical edits.
- **Do not add a `config*`/`sonfig*` glob.** There is no `sonfigs/` directory in the repo; the
  tracked `config/`, `configs/`, and `ari-core/config/` trees hold rubric/profile/default **data**
  that must stay tracked.
- **`.gitattributes` is absent** repo-wide. Adding one (line-ending normalization, `linguist-`
  attributes for `report/` LaTeX or vendored subtrees) is a reasonable *follow-up* but is out of
  scope here — flag it, don't do it.
- **CI hook interplay:** the `scripts/git-hooks/pre-commit` hook only runs `readme_sync.py`; it does
  not read `.gitignore`, so these changes cannot destabilize the commit hook. The authoritative gate
  is CI (`readme-sync.yml`, `refactor-guards.yml`).
- Write the commit message, PR body, and any doc text in **English** (ARI canonical), regardless of
  review-thread language.

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **033** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
