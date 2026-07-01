# Subtask 052: Add Dependabot And Actions Policy

Phase: Phase 9 — GitHub Integration
Classification: **KEEP** (additive) — introduces new supply-chain automation and a written GitHub Actions policy without altering any runtime code path.

---

## 1. Goal

Introduce **automated dependency-update management** and a **written GitHub Actions supply-chain / versioning policy** for the ARI monorepo:

1. Add `.github/dependabot.yml` covering every real dependency ecosystem in the repo:
   - `github-actions` (the 5 workflows under `.github/workflows/`),
   - `pip` (the root `requirements.txt` plus the Python package manifests: `ari-core/pyproject.toml` + the 13 skill `pyproject.toml` files),
   - `npm` (the two committed manifests: `docs/package.json` and `ari-core/ari/viz/frontend/package.json`).
2. Write a short, enforceable **Actions policy** (action-version pinning strategy, least-privilege `permissions:`, and how Dependabot PRs are grouped/reviewed) so the additive automation has a documented owner and merge convention.

This subtask is **configuration + documentation only**. It does not touch Python, TypeScript, prompts, configs consumed at runtime, or directory names.

---

## 2. Background

The repo has 5 GitHub Actions workflows and **no supply-chain automation whatsoever**. Verified by direct inspection on planning date 2026-07-01:

- `.github/` contains **only** `workflows/` (5 files). `find .github -type f` returns exactly the 5 workflow YAMLs.
- `.github/dependabot.yml` — **does not exist** (`ls` → "No such file or directory").
- `CODEOWNERS` — **does not exist** at repo root, `.github/`, or `docs/` (all three checked, all absent).
- `.github/actions/` (local composite actions) — **does not exist**.
- `.github/ISSUE_TEMPLATE/` and `.github/PULL_REQUEST_TEMPLATE.md` — **do not exist** (owned by sibling Phase 9 subtasks, not this one).

The 5 workflows pin GitHub Actions at **major-version tags only** (no SHA pinning). Verified `uses:` set across all workflows:

| Action | Ref used |
| --- | --- |
| `actions/checkout` | `@v4` |
| `actions/setup-python` | `@v5` |
| `actions/setup-node` | `@v4` |
| `actions/configure-pages` | `@v5` |
| `actions/upload-pages-artifact` | `@v3` |
| `actions/deploy-pages` | `@v4` |

All are first-party `actions/*`; there are **no third-party actions** and **no local `.github/actions/`**. Without Dependabot for the `github-actions` ecosystem, these tags silently drift (a `@v4` tag is mutable and moves under the repo's feet).

Python dependencies are declared in **two forms simultaneously**: the root `requirements.txt` (runtime pin list, mirrors core deps) and per-package `pyproject.toml` manifests. `requirements.lock` (7.7 KB) is a resolved lockfile but is **not** a standard `pip-tools`/`requirements.txt`-format file Dependabot updates directly — Dependabot's `pip` ecosystem reads `requirements.txt` and `pyproject.toml`.

Frontend/docs JS dependencies live in exactly two committed npm trees (`node_modules/` is gitignored and **not** tracked — verified `git ls-files` returns 0 entries under `ari-core/ari/viz/frontend/node_modules/`; `.gitignore` lines 112/113/135 ignore all three `node_modules/` paths).

Prior context: this is the "Add Dependabot And Actions Policy" leaf of the Phase 9 GitHub-integration fan-out (`045 -> 046..052`). It is a self-contained additive task with no runtime blast radius.

---

## 3. Scope

In scope:

- Create `.github/dependabot.yml` with `github-actions`, `pip`, and `npm` update configs for the real manifest locations enumerated in Section 5.
- Author a concise **GitHub Actions policy** (Section 7 defines its content) documenting: action-version pinning strategy, `permissions:` least-privilege expectation for new workflows, Dependabot grouping/schedule/labels, and the review/merge convention for Dependabot PRs. Place it where the repo already documents contributor process (`CONTRIBUTING.md` addendum) and/or as commentary headers in `dependabot.yml`.
- Optionally (see Section 7, item P4) add an explicit top-level `permissions: contents: read` block to the 4 read-only workflows (`docs-change-coupling.yml`, `docs-sync.yml`, `readme-sync.yml`, `refactor-guards.yml`) — **without** removing the elevated `pages: write` / `id-token: write` that `pages.yml` legitimately needs.

Out of scope (owned by sibling Phase 9 subtasks or explicitly deferred):

- `CODEOWNERS`, `ISSUE_TEMPLATE/`, `PULL_REQUEST_TEMPLATE.md`, `.github/actions/` scaffolding.
- Rewriting or refactoring the 5 existing workflow bodies.
- Any change to `requirements.lock` regeneration tooling.
- The vendored-`node_modules` hygiene question (already gitignored/untracked here; not a Dependabot concern).

---

## 4. Non-Goals

- Do **not** modify runtime code, imports, prompts, configs consumed by `ari`, MCP servers, the dashboard backend/frontend, or any directory name.
- Do **not** rewrite the 5 existing workflows wholesale. The only permitted workflow edit is the additive least-privilege `permissions:` block (P4), which is optional and must preserve every existing capability.
- Do **not** SHA-pin actions as a hard requirement in this subtask (the policy documents the *decision*; mass SHA-pinning of existing workflows is deferred — see Section 7 P2).
- Do **not** add the `gitsubmodule` ecosystem for the two vendored forks (`ari-skill-idea/vendor/virsci`, `ari-skill-paper-re/vendor/paperbench`). They are pinned external forks (`openai/preparedness`, a `Virtual-Scientists` fork); auto-bumping submodule SHAs is undesirable. State this decision explicitly in the config comments.
- Do **not** add a `docker` ecosystem: there are **no Dockerfiles** in-tree outside `vendor/` (verified — `containers/` holds only a 140-byte `README.md`).

---

## 5. Current Files / Directories to Inspect

All paths verified to exist (unless marked "does not exist"):

**GitHub config (target dir):**
- `/home/t-kotama/workplace/ARI/.github/workflows/refactor-guards.yml` (4565 B)
- `/home/t-kotama/workplace/ARI/.github/workflows/docs-change-coupling.yml` (2648 B)
- `/home/t-kotama/workplace/ARI/.github/workflows/docs-sync.yml` (4335 B)
- `/home/t-kotama/workplace/ARI/.github/workflows/pages.yml` (2047 B)
- `/home/t-kotama/workplace/ARI/.github/workflows/readme-sync.yml` (937 B)
- `/home/t-kotama/workplace/ARI/.github/dependabot.yml` — **does not exist** (to be created)

**Python (`pip`) manifests:**
- `/home/t-kotama/workplace/ARI/requirements.txt` (runtime dep list)
- `/home/t-kotama/workplace/ARI/requirements.lock` (7.7 KB resolved lock; not a Dependabot-updated format)
- `/home/t-kotama/workplace/ARI/ari-core/pyproject.toml`
- `/home/t-kotama/workplace/ARI/ari-skill-benchmark/pyproject.toml`
- `/home/t-kotama/workplace/ARI/ari-skill-coding/pyproject.toml`
- `/home/t-kotama/workplace/ARI/ari-skill-evaluator/pyproject.toml`
- `/home/t-kotama/workplace/ARI/ari-skill-hpc/pyproject.toml`
- `/home/t-kotama/workplace/ARI/ari-skill-idea/pyproject.toml`
- `/home/t-kotama/workplace/ARI/ari-skill-memory/pyproject.toml`
- `/home/t-kotama/workplace/ARI/ari-skill-paper/pyproject.toml`
- `/home/t-kotama/workplace/ARI/ari-skill-paper-re/pyproject.toml`
- `/home/t-kotama/workplace/ARI/ari-skill-plot/pyproject.toml`
- `/home/t-kotama/workplace/ARI/ari-skill-replicate/pyproject.toml`
- `/home/t-kotama/workplace/ARI/ari-skill-transform/pyproject.toml`
- `/home/t-kotama/workplace/ARI/ari-skill-vlm/pyproject.toml`
- `/home/t-kotama/workplace/ARI/ari-skill-web/pyproject.toml`
- `/home/t-kotama/workplace/ARI/ari-skill-orchestrator/pyproject.toml` — **does not exist** (this one skill ships no Python manifest; 13 of 14 skills have `pyproject.toml`). Do **not** add a `pip` entry for it.

**npm manifests:**
- `/home/t-kotama/workplace/ARI/docs/package.json` (+ `docs/package-lock.json`)
- `/home/t-kotama/workplace/ARI/ari-core/ari/viz/frontend/package.json` (+ `.../frontend/package-lock.json`)

**Policy landing spot:**
- `/home/t-kotama/workplace/ARI/CONTRIBUTING.md` (16.5 KB — existing contributor doc; candidate host for the Actions policy addendum)
- `/home/t-kotama/workplace/ARI/SECURITY.md` (2.3 KB — cross-reference target for supply-chain posture)

**Excluded from any config entry (verify, then skip):**
- `/home/t-kotama/workplace/ARI/ari-skill-idea/vendor/virsci/**` and `/home/t-kotama/workplace/ARI/ari-skill-paper-re/vendor/paperbench/**` — git submodules with their own nested `pyproject.toml` files; **must not** be scanned by the `pip` ecosystem.
- `.venv/` and every `node_modules/` — gitignored, untracked.

---

## 6. Current Problems

1. **No dependency-update automation of any kind.** `.github/dependabot.yml` is absent; no Renovate config exists either. GitHub Actions, pip packages, and npm packages all drift with zero notification.
2. **Mutable major-version action tags.** All 6 distinct actions are pinned at floating major tags (`@v4`, `@v5`, `@v3`). No policy states whether SHA-pinning is required, so security-sensitive supply-chain assumptions are undocumented.
3. **No written Actions policy.** There is no documented convention for `permissions:` scoping, action-version bumping, or how a maintainer should treat an automated dependency PR. Only `pages.yml` declares `permissions:` (correctly: `pages: write`, `id-token: write`); the other 4 workflows inherit default (broad) token scopes.
4. **Duplicated Python dep sources.** `requirements.txt` and the 14 `pyproject.toml` files can diverge; without Dependabot nudges the divergence is invisible until a build breaks.
5. **Uneven manifest coverage.** `ari-skill-orchestrator/` has **no** `pyproject.toml` while the other 13 skills do — an implementer naively globbing "one pip entry per skill" would produce a broken Dependabot entry pointing at a nonexistent manifest.

None of these are correctness bugs in ARI runtime; they are supply-chain hygiene and governance gaps.

---

## 7. Proposed Design / Policy

### 7.A `.github/dependabot.yml` (version 2)

Define one `updates:` block per real manifest location. Recommended shape (concrete directories from Section 5):

- **github-actions**, `directory: "/"`
  - `schedule.interval: "weekly"`, weekday e.g. Monday.
  - `groups:` a single `actions` group (`patterns: ["*"]`) so the 6 first-party action bumps land in **one** PR rather than six.
  - `labels: ["dependencies", "github-actions"]`.
- **pip**, one entry each for the directories that actually contain a Dependabot-readable manifest:
  - `directory: "/"` (root `requirements.txt`).
  - `directory: "/ari-core"` (`pyproject.toml`).
  - `directory: "/ari-skill-benchmark"`, `/ari-skill-coding`, `/ari-skill-evaluator`, `/ari-skill-hpc`, `/ari-skill-idea`, `/ari-skill-memory`, `/ari-skill-paper`, `/ari-skill-paper-re`, `/ari-skill-plot`, `/ari-skill-replicate`, `/ari-skill-transform`, `/ari-skill-vlm`, `/ari-skill-web` (13 skill manifests).
  - **Omit** `/ari-skill-orchestrator` (no manifest — verified).
  - Prefer a `groups:` block per ecosystem (e.g. group all pip minor/patch bumps) to cap PR volume across 15 pip directories.
  - `labels: ["dependencies", "python"]`.
  - Consider `open-pull-requests-limit` tuned low (e.g. 5) to avoid a PR flood across many directories.
- **npm**, two entries:
  - `directory: "/docs"` and `directory: "/ari-core/ari/viz/frontend"`.
  - `labels: ["dependencies", "javascript"]`; group minor/patch.

> **Alternative (implementer discretion):** Dependabot now supports multi-directory entries via `directories:` (a list) for a single ecosystem. Collapsing the 15 pip directories into one `pip` block with a `directories:` list is acceptable and reduces file size, provided each listed directory is verified to hold a manifest and `/ari-skill-orchestrator` is excluded.

Add an inline comment block at the top of `dependabot.yml` recording the two deliberate exclusions: (a) `gitsubmodule` for the two vendored forks, (b) `ari-skill-orchestrator` (no manifest).

### 7.B GitHub Actions policy (documentation)

Record these decisions (P1–P5) in a short "GitHub Actions & Dependencies" section appended to `CONTRIBUTING.md`, cross-linked from `SECURITY.md`:

- **P1 — Ecosystems tracked.** github-actions, pip, npm (as configured in `dependabot.yml`). Submodule forks and the manifest-less `ari-skill-orchestrator` are intentionally untracked.
- **P2 — Action version pinning.** Current standard: first-party `actions/*` pinned at **major tag** (`@v4`, etc.); Dependabot owns the bumps. SHA-pinning is **recommended but not mandated** for now; mandatory SHA-pinning of any future **third-party** action is required (none exist today). Full SHA-pin migration of existing workflows is deferred to a follow-up.
- **P3 — Grouping & cadence.** Weekly schedule; grouped PRs per ecosystem; `dependencies` label on every Dependabot PR.
- **P4 — Least-privilege permissions.** New workflows MUST declare a top-level `permissions:` block scoped to what they need. Existing read-only workflows (`docs-change-coupling.yml`, `docs-sync.yml`, `readme-sync.yml`, `refactor-guards.yml`) should gain `permissions: {contents: read}`. `pages.yml` retains `pages: write` + `id-token: write` (required for Pages deploy) — do not narrow it.
- **P5 — Review convention.** A human maintainer reviews and merges Dependabot PRs; CI (`refactor-guards.yml` pytest + docs gates) must pass. No auto-merge is enabled in this subtask.

---

## 8. Concrete Work Items

1. **Create** `/home/t-kotama/workplace/ARI/.github/dependabot.yml` (`version: 2`) with the `github-actions`, `pip` (15 verified manifest directories), and `npm` (2 directories) update blocks per Section 7.A, including the exclusion comment block.
2. **Verify each `directory:`** points at a real manifest before committing (re-run the Section 5 existence checks). Confirm `/ari-skill-orchestrator` is absent from the pip list.
3. **Append** a "GitHub Actions & Dependencies" policy section (P1–P5) to `/home/t-kotama/workplace/ARI/CONTRIBUTING.md`, and add a one-line cross-reference in `/home/t-kotama/workplace/ARI/SECURITY.md`.
4. **(Optional, P4)** Add `permissions: {contents: read}` at the top of the 4 read-only workflows. Leave `pages.yml` untouched. If a workflow step needs more (none identified), scope narrowly.
5. **Update per-directory `## Contents` README indexes only if a README under `.github/` exists** — none does today, so `scripts/readme_sync.py` is unaffected. Confirm no new tracked directory needs a README index.
6. **Validate** `dependabot.yml` locally (see Section 12) before opening the PR.

---

## 9. Files Expected to Change

**New file (created):**
- `/home/t-kotama/workplace/ARI/.github/dependabot.yml`

**Edited (documentation / policy):**
- `/home/t-kotama/workplace/ARI/CONTRIBUTING.md` (append policy section)
- `/home/t-kotama/workplace/ARI/SECURITY.md` (add one cross-reference line)

**Optional edits (P4 least-privilege `permissions:` only; additive, non-breaking):**
- `/home/t-kotama/workplace/ARI/.github/workflows/docs-change-coupling.yml`
- `/home/t-kotama/workplace/ARI/.github/workflows/docs-sync.yml`
- `/home/t-kotama/workplace/ARI/.github/workflows/readme-sync.yml`
- `/home/t-kotama/workplace/ARI/.github/workflows/refactor-guards.yml`
- (`/home/t-kotama/workplace/ARI/.github/workflows/pages.yml` — **not** to be edited; its elevated permissions are intentional.)

No Python, TypeScript, YAML config under `config/`/`configs/`, prompt, or checkpoint files change.

---

## 10. Files / APIs That Must Not Be Broken

This subtask touches **only** repo-governance files, so the standard ARI contracts are structurally untouched — but the implementer must not perturb them via careless workflow edits:

- **CLI** `ari = ari.cli:app` — unaffected (no code change).
- **Public Python API** `ari.public.*` (`claim_gate`, `config_schema`, `container`, `cost_tracker`, `llm`, `paths`, `run_env`, `verified_context`) — unaffected.
- **MCP tool contracts** — the 14 `ari-skill-*` `src/server.py` servers and `ari/mcp/client.py` — unaffected.
- **Dashboard API** — `ari/viz/routes.py` + `api_*.py` endpoints, `websocket.py`, and `frontend/src/services/api.ts` — unaffected.
- **Checkpoint/output/config file formats** — unaffected.
- **Scripts called by `.github/workflows`** — the 12 scripts invoked by the 5 workflows (e.g. `scripts/docs/check_report_cochange.py`, `scripts/readme_sync.py`, `scripts/docs/sync_report_pdf.sh`, `scripts/docs/assemble_site.sh`) MUST keep working. Any P4 `permissions:` addition must be `contents: read` at minimum, which these read-only checks already satisfy.
- **`pages.yml` deploy capability** — the `pages: write` + `id-token: write` permissions and `configure-pages@v5` / `upload-pages-artifact@v3` / `deploy-pages@v4` chain must remain intact; do not let Dependabot config or P4 edits interfere with the only deploy workflow.

---

## 11. Compatibility Constraints

- `dependabot.yml` is **inert** with respect to a local checkout: it only affects GitHub's hosted Dependabot service. It cannot break `pytest`, `compileall`, `ruff`, or the frontend build.
- Dependabot **opens PRs** that later, separately, bump dependency versions. Those future bump PRs are **not** part of this subtask and are gated by existing CI (`refactor-guards.yml`, docs gates). This subtask only lands the config + policy.
- The `pip` ecosystem must not recurse into the two git submodules (`ari-skill-idea/vendor/virsci`, `ari-skill-paper-re/vendor/paperbench`); Dependabot scopes to the exact `directory:` given, so listing only the 15 first-party directories keeps vendor manifests out.
- No public contract, documented import path, or MCP/dashboard schema changes — so **no compatibility adapter is required**.
- The word "deprecated" is not used for any internal code here; nothing external is being retired.

---

## 12. Tests to Run

Because this subtask introduces no runtime code, the standard suite should stay green as a **regression guard** (proving nothing was collaterally broken), and the real validation is YAML/schema validation of the new config:

- `python -m compileall .` — must succeed unchanged (no `.py` touched).
- `pytest -q` — full suite; expect no new failures attributable to this change. (CI's `refactor-guards.yml` runs `pytest ari-core/tests/ -q` under a redirected `HOME`, ignoring `test_letta_restart_live`, `test_letta_start_scripts`, `test_ollama_gpu`, `test_dashboard_html`.)
- `ruff check .` — must remain clean (ruff is available in-repo).
- **Frontend (only if P4/npm entries prompt a frontend touch — not expected):** `npm ci --prefix ari-core/ari/viz/frontend && npm run --prefix ari-core/ari/viz/frontend build` should still pass. Not required unless frontend files change (they should not).
- **Dependabot config validation (primary check for this subtask):**
  - YAML well-formedness: `python -c "import yaml,sys; yaml.safe_load(open('.github/dependabot.yml'))"` (pyyaml is already a repo dep).
  - Schema/directory sanity: manually re-verify every `directory:` resolves to a real manifest (the Section 5 existence checks). Optionally lint workflows with `actionlint` if available (advisory; not installed by default — do not add it as a hard gate).
  - `python scripts/readme_sync.py --check` — confirm no `## Contents` index drift (should be a no-op; `.github/` has no README index today).

---

## 13. Acceptance Criteria

1. `.github/dependabot.yml` exists, is valid YAML `version: 2`, and lints/parses cleanly.
2. It contains exactly: one `github-actions` block (`/`), `pip` blocks for the **15 verified** Python-manifest directories (root + `ari-core` + 13 skills, **excluding** `ari-skill-orchestrator`), and two `npm` blocks (`/docs`, `/ari-core/ari/viz/frontend`).
3. Every `directory:` (or `directories:` list entry) resolves to an actual manifest on disk; the two vendored submodule trees are **not** listed.
4. The Actions policy (P1–P5) is present in `CONTRIBUTING.md` and cross-referenced from `SECURITY.md`.
5. (If P4 applied) the 4 read-only workflows declare `permissions: {contents: read}`; `pages.yml` is unchanged and still declares `pages: write` + `id-token: write`.
6. `python -m compileall .`, `pytest -q`, and `ruff check .` show no new failures.
7. No file outside the Section 9 list is modified. No runtime code, prompt, config-data, or directory name changed.

---

## 14. Rollback Plan

Fully reversible with `git revert` of the single commit:

1. `git rm .github/dependabot.yml` (or revert the add).
2. Revert the `CONTRIBUTING.md` / `SECURITY.md` additions.
3. Revert the optional `permissions:` blocks in the 4 workflows.

Because `dependabot.yml` is inert locally and the policy is documentation, rollback carries **no runtime risk** and no data/state migration. If Dependabot begins opening unwanted PRs after merge, they can be closed individually and/or the ecosystem block removed, independent of the rest of the change.

---

## 15. Dependencies

Per the Phase 9 dependency graph, `045 -> 046, 047, 048, 049, 050, 051, 052`, so:

- **052 depends on 045** — the Phase 9 GitHub-integration foundation/inventory subtask must land first. 052 is one leaf of that fan-out and should reuse whatever `.github/` conventions and labels 045 establishes.
- No other subtask (046–051) is a hard prerequisite; 052 is independent of its sibling leaves and may proceed as soon as 045 is merged.
- 052 introduces **no runtime code**, so the "inventory subtasks that must precede any runtime code change" (001, 002, 020, 036, 045, 053, 059, 060, 067) are **not** blockers for 052 beyond the already-required 045. This subtask does not gate, and is not gated by, the runtime-refactor chains (`053 -> 054 -> ... -> 058`, `036 -> ...`, `059 -> ...`).

---

## 16. Risk Level

**Risk: Low.**

**Changes runtime code: No.** This subtask adds a GitHub-service configuration file (`.github/dependabot.yml`) and contributor documentation, plus optional additive least-privilege `permissions:` blocks on read-only workflows. It touches no Python, TypeScript, prompt, runtime config-data, checkpoint format, CLI, MCP, or dashboard code. `dependabot.yml` is inert in a local checkout and only influences GitHub's hosted service. The main residual risks are (a) pointing a `pip` entry at the manifest-less `ari-skill-orchestrator` (mitigated by the explicit exclusion and the Section 13 verification step) and (b) a malformed `permissions:` edit narrowing a capability the deploy workflow needs (mitigated by leaving `pages.yml` untouched).

---

## 17. Notes for Implementer

- **The one gotcha:** `ari-skill-orchestrator/` has **no** `pyproject.toml` (verified — 13 of 14 skills ship one). Do not add a `pip` block for it or Dependabot will error on a missing manifest.
- **Do not** add a `gitsubmodule` ecosystem: `ari-skill-idea/vendor/virsci` (a `Virtual-Scientists` fork) and `ari-skill-paper-re/vendor/paperbench` (`openai/preparedness`) are pinned external forks; auto-bumping their SHAs is undesirable. Record this in the config comments.
- **Do not** add a `docker` ecosystem: no in-tree Dockerfiles exist outside `vendor/` (`containers/` holds only a 140-byte README). If a future subtask adds Dockerfiles, extend `dependabot.yml` then.
- `requirements.lock` (7.7 KB) is a resolved lockfile, **not** a Dependabot-managed `requirements.txt`-format file — Dependabot updates `requirements.txt` and `pyproject.toml`, so `requirements.lock` may drift; note this in the policy as a known limitation (regenerate it manually when a pip bump PR is merged).
- **Consider `directories:` (list form)** to collapse the 15 pip blocks into one entry and keep the file compact — but verify each listed directory has a manifest first.
- **Version-drift note for any workflow you touch:** `docs-change-coupling.yml`'s header (lines ~42–47) critiques `refactor-guards.yml`'s `origin/<base_ref>` merge-base idiom as inferior to `github.event.pull_request.base.sha`. This is irrelevant to `dependabot.yml`, but if P4 edits ever grow into workflow-body changes, prefer `base.sha`. For this subtask, restrict workflow edits to the additive `permissions:` block only.
- **Grounding note on hygiene:** the top-level "grounded facts" mention "committed `node_modules/` in git" — as of this planning date that is **not** the current state: `node_modules/` is gitignored (`.gitignore` lines 112/113/135) and `git ls-files` returns 0 tracked entries under the frontend `node_modules/`. Dependabot's `npm` ecosystem reads `package.json` / `package-lock.json` regardless, so this does not affect the config.
- There is **no** `sonfigs/` directory anywhere in the repo; it is irrelevant to this subtask (mentioned only to preempt confusion — the real trio is `ari-core/ari/config/` code vs `ari-core/ari/configs/` packaged defaults vs top-level `config/` rubric data).
- The doc is self-contained: all target paths are enumerated in Sections 5 and 9 with verified existence status.

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **052** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
