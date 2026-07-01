# Subtask 043: Add Prompt Checker Script

- **Phase:** Phase 7 — Prompt Management
- **Subtask ID:** 043
- **Title (index):** `add_prompt_checker_script`
- **Primary deliverable:** a new, self-contained Python checker
  `scripts/check_prompts.py` (plus its config/allowlist under `scripts/quality/`)
  that **inventories still-hardcoded LLM prompts** in the runtime tree as
  externalization candidates, and **defers snapshot-consistency to the existing
  Gate 10** (`report/scripts/check_prompt_snapshots.py`) rather than
  re-implementing it.
- **Runtime code change:** **No** (dev tooling only — see Section 16).
- **Repo root:** `/home/t-kotama/workplace/ARI` (git branch `main`; `ari-core`
  version `0.9.0`, from `ari-core/pyproject.toml`).
- **Canonical language:** English.
- **Classification vocabulary (used where relevant):** `KEEP` / `ADAPT` /
  `MERGE` / `MOVE_TO_LEGACY` / `DELETE_CANDIDATE` / `REVIEW_REQUIRED`. The word
  "deprecated" is reserved for external contracts only (public API, CLI, MCP,
  dashboard API, documented import paths, `ari-skill-*` stable interfaces).

> **Numbering note (read once).** The canonical map is
> `docs/refactoring/007_subtask_index.md:90`:
> `| 043 | add_prompt_checker_script | 7 | Low | 036 | check_prompts.py | No | No |`.
> Two *earlier* planning drafts number this checker differently — the quality
> plan's private table (`009_quality_scripts_plan.md:245`) calls it "030", and
> the prompt plan's §13 table (`011_prompt_management_plan.md:596`) calls it
> "044". **Both are stale internal numberings; this subtask is 043** per the
> index and the program dependency graph (`036 -> 043`). The *design content*
> for the checker lives in `009_quality_scripts_plan.md` §5.7/§8; the *prompt
> context* lives in `011_prompt_management_plan.md`.

---

## 1. Goal

Deliver `scripts/check_prompts.py`: a deterministic, stdlib+PyYAML-only quality
checker that scans the runtime code tree for **inline/hardcoded LLM prompt
strings that have not yet been externalized** into `ari-core/ari/prompts/**` (or
the skill-local `ari-skill-*/src/prompts/**` directories), reports each as an
externalization candidate (file, line, snippet, size), and suppresses accepted
ones via a frozen allowlist. It is the automated, repeatable, CI-runnable
successor to the one-shot inventory produced by Subtask 036.

The checker explicitly **does not** re-implement the snapshot-byte verification
that `report/scripts/check_prompt_snapshots.py` (**Gate 10**, 93 lines) already
performs over `ari-core/ari/prompts/**/*.md`; where snapshot consistency is in
scope it **invokes or defers to Gate 10**. Its verdict is `KEEP` for the
inline-inventory slice (net-new) and `MERGE`/defer for the snapshot slice
(`009_quality_scripts_plan.md` §5.7).

Success = a fresh coding session, running only this checker plus its frozen
allowlist, can (1) reproduce the inline-prompt candidate set that Subtask 036
inventoried by hand (the evaluator judge prompts, the paper-skill prompts, the
plot/vlm/transform/web role prompts), (2) fail CI **only** on *net-new* inline
prompts under `--fail-on-regression`, and (3) never turn the existing,
already-catalogued inline prompts into red CI on unrelated PRs.

## 2. Background

ARI's prompt layer is **partially externalized** (`011_prompt_management_plan.md`
§1–2, verified 2026-07-01):

- **Core loader.** `ari-core/ari/prompts/_loader.py` (49 lines) defines a
  `PromptLoader` `Protocol` + `FilesystemPromptLoader`; `load(key)` reads
  `{base}/{key}.md`, `load_versioned(key)` returns `(text, sha256[:12])`.
  Re-exported by `ari-core/ari/prompts/__init__.py` and
  `ari-core/ari/protocols/__init__.py`.
- **Externalized templates.** 11 `.md` templates + 5 per-directory `README.md`
  under `ari-core/ari/prompts/{agent,evaluator,orchestrator,pipeline,viz}/`
  (e.g. `agent/system.md`, `evaluator/{extract_metrics,peer_review}.md`, the
  five `orchestrator/*.md`, `pipeline/keyword_librarian.md`,
  `viz/wizard_{chat_goal,generate_config}.md`).
- **Skill-local templates.** `ari-skill-replicate/src/prompts/*.md` and
  `ari-skill-paper-re/src/prompts/replicator.md` exist but are loaded with
  ad-hoc `Path.read_text()`, not the core loader (REVIEW_REQUIRED — owned by
  Subtask 038/040, not here).
- **Existing snapshot coverage.** `ari-core/tests/test_prompt_extraction.py`
  (107 lines) hardcodes the expected `sha256` of every externalized core
  template. Separately, `report/scripts/check_prompt_snapshots.py` (**Gate 10**,
  93 lines; run via `report/Makefile` target `check-prompt-snapshots` → `--root
  <repo>`) byte-verifies `ari-core/ari/prompts/**/*.md` against
  `report/shared/appendix/prompts/**` via `% snapshot-from: <rel>@<sha256>`
  headers.

**What is still missing** is exactly the thing this checker adds: a repeatable
scan for the substantial system prompts that **remain inline** in the largest
runtime files. Per the routed prompt inventory and `011_prompt_management_plan.md`
§3/§5.x, the high-value inline targets are:

- `ari-skill-evaluator/src/server.py:790` `_SEMANTIC_SYSTEM_PROMPT` (~18 L judge
  rubric + JSON schema) and `:191` `_METRIC_EXTRACT_SYS` (~11 L).
- `ari-skill-paper/src/server.py` (2956 L, largest skill file) inline
  reviewer/writer/editor prompts at `:542, 1487, 1638, 1660, 2544`.
- `ari-skill-plot/src/server.py:90,560,663`; `ari-skill-vlm/src/server.py:97,112`;
  `ari-skill-transform/src/server.py:834,867`; `ari-skill-web/src/server.py:465,483`.
- `ari-skill-paper/src/review_engine.py:58,105,443` (venue peer-reviewer / Area
  Chair — MOVE_TO_CONFIGURABLE_PROMPT / MERGE_DUPLICATE).

`grep` counts for the role marker "you are" (case-insensitive) at planning time:
`ari-skill-paper/src/server.py` 9, `ari-skill-plot/src/server.py` 3,
`ari-skill-{transform,evaluator,vlm,web}/src/server.py` 2 each. **Note a
gotcha:** `ari-core/ari/agent/loop.py` (1630 L) returns **0** "you are" hits —
its system prompt is *already externalized* to `agent/system.md`. So the
heuristic must key on multi-line string literals with role/JSON markers
("You are", "Return JSON", "```json", numbered rubric rules), **not** on "You
are" alone, or it will both miss extracted prompts and false-positive on
docstrings.

`KEEP_INLINE` cohort the checker must **not** flag (allowlist these):
`ari-skill-idea/src/server.py:245-266` (VirSci fallback; primary path execs
vendored `utils/prompt.py`) and `ari-skill-paper-re/src/_paperbench_bridge.py`
(2376 L, 59 triple-quotes, mostly vendored PaperBench templates).

Tooling baseline (measured, confirmed this planning session):

| Tool | State | Consequence |
|---|---|---|
| `python` / `compileall` / `pytest` | available (3.13.2; pytest 9.0.2) | stdlib `ast`/`tokenize` scan; test gate. |
| `PyYAML` | available (`pyyaml>=6.0`, `ari-core/pyproject.toml`) | config/allowlist parsing. |
| `ruff` | installed (0.15.2) | only for keeping the new script ruff-clean; not the engine. |
| `radon`/`vulture` | **NOT installed** | irrelevant here — this checker is an `ast`/regex prompt scan, not a complexity/dead-code gate. |
| `node`/`npm` | available; **no `pnpm`** | not needed — prompts are Python string literals. |

## 3. Scope

In scope:

1. Create **`scripts/check_prompts.py`** — the checker, conforming to the house
   style of `scripts/docs/` (`#!/usr/bin/env python3`, module docstring citing
   `docs/refactoring/009_quality_scripts_plan.md` §5.7, `argparse`,
   `REPO_ROOT = Path(__file__).resolve().parents[1]` like `scripts/readme_sync.py`,
   stdlib+PyYAML only, `SystemExit(2)` on environment error).
2. **Inline-prompt inventory (the NEW slice).** Walk Python files under the
   configured targets (default `ari-core/ari` + each `ari-skill-*/src`), parse
   with `ast` to find module/class-level string constants and multi-line
   f-strings, and flag those that match configurable *prompt heuristics*
   (role markers, JSON-schema markers, minimum line/char length). Emit each as a
   candidate: `{file, line, name, lines, chars, markers, allowlisted}`.
3. **Snapshot-consistency slice (defer, do not duplicate).** Provide a
   `--with-snapshots` mode that **shells out to** Gate 10
   (`report/scripts/check_prompt_snapshots.py --root <REPO_ROOT>`) and folds its
   pass/fail into the report, rather than re-reading `.md` bytes. Default OFF so
   the two gates stay independently runnable (`009_quality_scripts_plan.md`
   §5.7: "call Gate 10 or leave it alone").
4. **Config + allowlist** under `scripts/quality/`:
   - `scripts/quality/check_prompts.yaml` — heuristic patterns (marker list,
     `min_lines`, `min_chars`), target globs, exclude globs.
   - `scripts/quality/check_prompts.allow.yaml` — the frozen inline-prompt
     baseline (seeded from the Subtask 036 census + the `KEEP_INLINE` cohort).
5. **Reuse or bootstrap `scripts/quality/_common.py`.** This directory does
   **not** exist today (`ls scripts/quality` → absent). If an earlier
   quality-script subtask (e.g. 025/026/029/030/031) has already created
   `_common.py`, **reuse it**; otherwise create the minimal shared helper (JSON
   emitter, allowlist loader, Markdown-table writer, `--base-ref` resolver
   mirroring `scripts/docs/check_ref_coupling.py`). Add the per-directory
   `scripts/quality/README.md` required by the README-sync convention if this
   subtask is the one that creates the directory.
6. The canonical flag set and exit convention from `009_quality_scripts_plan.md`
   §3 (see Section 7).
7. Keep the `readme_sync.py` gate green: adding `scripts/check_prompts.py` (and,
   if newly created, the `scripts/quality/` subtree) requires updating
   `scripts/README.md`'s `## Contents` block (66 lines today), because
   `readme-sync.yml` runs `python scripts/readme_sync.py --check` and fails on
   missing/extra paths.

Out of scope (owned by sibling subtasks; do not implement here):

- **Actually externalizing any inline prompt.** Moving `_SEMANTIC_SYSTEM_PROMPT`
  or the paper-skill prompts into `.md` templates is the runtime work of
  Subtasks 039/040/041 (`007_subtask_index.md:87-89`). This subtask only
  *detects* candidates; it moves no prompt text.
- **The prompt registry / provenance layer** (`ari/prompts/_registry.py`,
  `rendered_prompt_hash`, run-metadata fields) — Subtasks 038/044.
- **Re-implementing snapshot byte-verification** — that is Gate 10's job; this
  checker defers to it (Section 7.3).
- **Adding prompt *snapshot tests*** — Subtask 042 (`add_prompt_snapshot_tests`),
  which extends `ari-core/tests/test_prompt_extraction.py`.
- **Wiring the checker into any workflow as a hard gate** — warning-mode-first
  (Section 7.6); no `.github/workflows/*` edits in this subtask.

## 4. Non-Goals

- **No runtime code changes.** No edits to any file under `ari-core/ari/`,
  `ari-skill-*/`, the frontend, `ari-core/config/`, `ari-core/ari/configs/`, the
  `ari-core/ari/prompts/` templates, or `.github/workflows/`.
- **No prompt-text moves / renames.** The checker reports inline prompts; it does
  not extract, rename, or relocate them. Every inline "You are …" string stays
  exactly where it is.
- **No new runtime dependency.** No `radon`/`vulture`; the checker depends only on
  stdlib + PyYAML (already a core dep) + the ability to shell out to the existing
  Gate 10 script (already in-repo).
- **No re-implementation of Gate 10.** `check_prompts.py` must **not** re-derive
  the `% snapshot-from:` SHA-256 logic in
  `report/scripts/check_prompt_snapshots.py`; it invokes that script.
- **No LLM calls, no network** (preserves the `scripts/docs/` determinism
  convention and design principle P2: `ari-skill-memory` and this quality tooling
  are explicitly LLM-free).
- **No hard CI gate** in this subtask; if wired at all, advisory
  (`continue-on-error: true`) only, and that wiring is a separate subtask.
- **No `pnpm`** usage (absent); no frontend scan (prompts are Python literals).

## 5. Current Files / Directories to Inspect

All paths verified present on `main` at planning time unless marked. Line counts
are `wc -l`.

**House-style reference (the convention to copy):**
- `scripts/docs/check_doc_sources.py` (223 L) — canonical checker shape: shebang,
  docstring citing a design doc, `argparse` with `--json`, `REPO_ROOT =
  Path(__file__).resolve().parents[2]`, a `Finding` class with `as_dict()`, exit
  `1` on error / `SystemExit(2)` on missing PyYAML, level split
  error/warning/coverage.
- `scripts/docs/check_ref_coupling.py` — `--base-ref origin/main` git-diff
  resolution to mirror for `--fail-on-regression` / `--base-ref`.
- `scripts/readme_sync.py` (350 L) — lives at `scripts/` **top level** and uses
  `REPO_ROOT = Path(__file__).resolve().parents[1]`; the new checker sits beside
  it and uses the same `parents[1]` (source-code gate family, per
  `009_quality_scripts_plan.md` §8).

**The gate this checker defers to (must NOT duplicate):**
- `report/scripts/check_prompt_snapshots.py` (**Gate 10**, 93 L) — byte-verifies
  `ari-core/ari/prompts/**/*.md` against `report/shared/appendix/prompts/**`;
  CLI is `--root <repo-root>`. Invoked by `report/Makefile` target
  `check-prompt-snapshots`. `check_prompts.py --with-snapshots` shells out to
  this, it does not reimplement it.
- `report/scripts/snapshot_prompts.py` (91 L) — the refresh side of Gate 10
  (`make snapshot-prompts`); context only, not called by this checker.

**Prompt layer the checker measures against (externalized = "already done"):**
- `ari-core/ari/prompts/_loader.py` (49 L), `__init__.py`, `README.md`, and the
  11 `.md` templates under `agent/`, `evaluator/`, `orchestrator/`, `pipeline/`,
  `viz/` (each dir has its own `README.md`).
- `ari-skill-replicate/src/prompts/*.md`, `ari-skill-paper-re/src/prompts/replicator.md`
  (skill-local externalized templates; loaded ad-hoc — REVIEW_REQUIRED, not this
  subtask's target).
- `ari-core/tests/test_prompt_extraction.py` (107 L) — existing snapshot pin;
  Subtask 042 extends it. Read to understand the byte-identical discipline.

**Scan targets (where inline prompts still live):**
- Default Python targets: `ari-core/ari` and each `ari-skill-*/src`.
- High-value files (Section 2): `ari-skill-paper/src/server.py` (2956),
  `ari-skill-transform/src/server.py` (2465), `ari-skill-evaluator/src/server.py`
  (983), `ari-skill-plot/src/server.py` (802), `ari-skill-vlm/src/server.py`,
  `ari-skill-web/src/server.py`, `ari-skill-paper/src/review_engine.py`,
  `ari-core/ari/agent/loop.py` (1630 — expected **clean**, prompt already
  externalized: a good negative-control).
- **Excluded by default / allowlisted:** `**/tests/**`, `node_modules/`,
  `__pycache__/`, `vendor/` submodules (`ari-skill-idea/vendor/virsci`,
  `ari-skill-paper-re/vendor/paperbench`), `ari-skill-paper-re/src/_paperbench_bridge.py`
  (vendored, `KEEP_INLINE`), `ari-skill-idea/src/server.py` fallback block.

**Directory the checker is added to / may create:**
- `scripts/` — top level (has `readme_sync.py`, `sc_paper_dogfood.py`,
  `sc_paper_stage23_chain.py`, `run_all_tests.sh`, `git-hooks/`, `docs/`,
  `setup/`, `letta/`, `registry/`, `fewshot/`, `README.md`). `check_prompts.py`
  goes **here** (source-code gate family), not under `scripts/docs/`.
- `scripts/quality/` — **does not exist today**; reuse if an earlier
  quality-script subtask created it, else create it here.
- `scripts/README.md` (66 L) — `## Contents` must be updated (or regenerated via
  `readme_sync.py --write`) to list the new file(s).

**Design inputs (read before implementing):**
- `docs/refactoring/009_quality_scripts_plan.md` — §3 (common script contract),
  §5.7 (`check_prompts.py` design block, verbatim source of this subtask), §8
  (placement / `scripts/quality/` / `_common.py`), §6 (warning-mode-first).
- `docs/refactoring/011_prompt_management_plan.md` — §2 (prompt locations), §3/§5.x
  (inline-prompt categories + KEEP/EXTRACT/MERGE/MOVE/REVIEW verdicts, the exact
  candidate list), §10 (snapshot-test policy — relationship to Gate 10).
- `docs/refactoring/007_subtask_index.md:90` — the authoritative 043 row.
- The Subtask **036** output (`inventory_hardcoded_prompts`) — the exhaustive
  line-level census that seeds this checker's allowlist and validates its
  heuristics. **This subtask's hard predecessor** (Section 15).

**Confirmed absent (state explicitly, do not chase):**
- `scripts/check_prompts.py` (net-new — `grep` over `scripts/**` returns nothing).
- `scripts/quality/` (to be reused or created). No `radon`/`vulture`. No
  `sonfigs/` anywhere. No top-level `pyproject.toml`. No `prompt_registry` /
  `rendered_prompt_hash` symbols in `ari-core` yet (those arrive with 038/044).

## 6. Current Problems

1. **The inline-prompt inventory is a one-shot manual artifact.** Subtask 036
   produces an exhaustive census by hand, but nothing keeps it current: a new
   inline "You are …" prompt added to `ari-skill-paper/src/server.py` (already
   2956 L) after 036 lands is invisible until someone re-audits by hand. There is
   **no repeatable gate** that re-derives the candidate set.
2. **Large files hide high-value prompts.** The biggest system prompts are buried
   in the biggest files (`ari-skill-paper/src/server.py` 2956, `transform` 2465,
   `evaluator` 983). A wording change is indistinguishable from a code change in
   the diff, and reviewers cannot see prompt drift.
3. **"You are" alone is a bad signal.** `ari-core/ari/agent/loop.py` (1630) has 0
   "you are" hits because its prompt is externalized, while `_paperbench_bridge.py`
   is full of vendored "You are allowed to browse…" text that must **not** be
   flagged. A naive grep both under- and over-reports; the checker needs
   structural heuristics (multi-line literal + role/JSON markers + length) plus a
   `KEEP_INLINE` allowlist.
4. **Snapshot verification already exists and must not be duplicated.**
   `report/scripts/check_prompt_snapshots.py` (Gate 10) already byte-verifies
   `ari-core/ari/prompts/**/*.md`. A new checker that re-derives SHA-256 headers
   would be redundant and could drift from Gate 10 (`009_quality_scripts_plan.md`
   §5.7 / §4: PARTIAL OVERLAP — keep the inventory slice, defer the snapshot
   slice).
5. **Historical inline prompts must not become red CI.** The evaluator/paper/
   plot/vlm/transform/web inline prompts predate this gate. Turning them into hard
   failures would block every unrelated PR; the checker must ship
   warning-mode-first with a frozen allowlist seeded from the 036 census
   (`009_quality_scripts_plan.md` §6).
6. **Adding a `scripts/` file trips the README-sync gate** unless `scripts/README.md`
   is updated in the same change — `readme-sync.yml` runs `readme_sync.py --check`
   (exit 1 on missing/extra paths).

## 7. Proposed Design / Policy

Deliver `scripts/check_prompts.py` plus its `scripts/quality/` config/allowlist,
following `009_quality_scripts_plan.md` §3/§5.7/§8.

**7.1 Placement & bootstrap.** The checker lives at `scripts/check_prompts.py`
(`REPO_ROOT = Path(__file__).resolve().parents[1]`), alongside `readme_sync.py`,
**not** under `scripts/docs/` (docs/i18n family) — it is a source-code gate.
*(Note: `011_prompt_management_plan.md` §10.4/§13 loosely says
"`scripts/docs/check_prompts.py`"; that is superseded by `009` §8's explicit
placement decision, which co-locates the source-code gates at `scripts/` top
level. Follow `009` §8 and match the sibling checkers.)* It reuses
`scripts/quality/_common.py` if present, else creates it (JSON emitter, allowlist
loader, Markdown-table writer, `--base-ref` resolver). It creates
`scripts/quality/check_prompts.yaml`, `scripts/quality/check_prompts.allow.yaml`,
and (if it is the directory's creator) `scripts/quality/README.md`.

**7.2 Detection heuristic (the NEW slice).** Parse each in-scope `.py` with
`ast`; for every module/class-level `str`/`Constant` assignment and multi-line
(f-)string literal, compute:
- `lines` (physical newlines in the literal), `chars`,
- `markers`: presence of any configured role/JSON marker
  (`"You are"`, `"Return JSON"`, `"```json"`, `"reviewer"`, `"rubric"`, numbered
  hard-constraint rules, etc. — the full list lives in `check_prompts.yaml`).

Flag as a candidate when `lines >= min_lines` **and** `chars >= min_chars`
**and** `markers` is non-empty, unless the `(file, name/line)` is allowlisted.
This structurally catches `_SEMANTIC_SYSTEM_PROMPT` (`evaluator/server.py:790`)
and the paper prompts while ignoring short f-string one-liners and docstrings.
Report `name` (the assigned constant name when available, e.g.
`_SEMANTIC_SYSTEM_PROMPT`) so candidates are human-addressable.

**7.3 Snapshot slice — defer to Gate 10.** With `--with-snapshots`, run
`python report/scripts/check_prompt_snapshots.py --root <REPO_ROOT>` as a
subprocess and record its exit code + stdout in the report under a
`snapshots` section. Default is **off**. The checker never re-reads
`report/shared/appendix/prompts/**` or re-derives `% snapshot-from:` SHA-256s
(`009_quality_scripts_plan.md` §5.7).

**7.4 Canonical flags (`009_quality_scripts_plan.md` §3 — accept all, ignore
inapplicable ones):**

| Flag | Meaning |
|---|---|
| `--target <path>` | Restrict scan (default `ari-core/ari` + each `ari-skill-*/src`; repeatable). |
| `--config <file>` | YAML config (default `scripts/quality/check_prompts.yaml`). |
| `--output <file>` | Write report to a file instead of stdout. |
| `--format markdown\|json` | `json` = aggregator building block (stable schema); `markdown` = human inventory table. |
| `--warning-only` | Force exit 0 regardless of findings (advisory; the **default posture** while new). |
| `--fail-on-regression` | Exit non-zero **only** for candidates above the frozen allowlist (net-new inline prompts). |
| `--base-ref <ref>` | For diff-scoped regression checks (default `origin/main`, mirroring `check_ref_coupling.py`). |
| `--with-snapshots` | Additionally invoke Gate 10 and fold its result in (default off). |
| `--update-baseline` | Regenerate `check_prompts.allow.yaml` from the current tree (deliberate freeze, analogous to `report/scripts/snapshot_prompts.py`). |

**7.5 Allowlist / baseline.** `check_prompts.allow.yaml` freezes the currently
known inline prompts keyed by `(file, constant-name-or-line)` with a verdict tag
(`EXTRACT_TEMPLATE` / `MERGE_DUPLICATE` / `MOVE_TO_CONFIGURABLE_PROMPT` /
`KEEP_INLINE` / `REVIEW_REQUIRED`) and optional justification, **seeded from the
Subtask 036 census**. Vendored/fallback strings
(`_paperbench_bridge.py`, `ari-skill-idea/src/server.py:245-266`) are tagged
`KEEP_INLINE`. Allowlisted candidates are reported as `known`, never `new`, and
never fail `--fail-on-regression`. Ratchet direction: entries with
`EXTRACT_TEMPLATE` shrink as Subtasks 039/041 externalize them; the baseline
never grows silently.

**7.6 Output schema & exit convention.** JSON matches `009_quality_scripts_plan.md`
§3: `{ "checker": "check_prompts", "version": 1, "target": <str>,
"summary": {candidates, known, new, by_verdict{...}, snapshots: pass|fail|skipped},
"findings": [ {id, severity, file, line, name, lines, chars, markers[],
verdict, allowlisted: bool} ] }`. Markdown = a triage table (file, line, name,
lines, markers, verdict, allowlisted?). Exit convention: `0` clean or
`--warning-only`; `1` new candidates (non-warning, or net-new under
`--fail-on-regression`) **or** Gate 10 failed under `--with-snapshots`; `2`
usage/environment error (e.g. Gate 10 script missing, `ast` parse failure on a
target), matching `check_doc_sources.py`'s `SystemExit(2)`.

**7.7 Rollout (warning-mode-first, `009_quality_scripts_plan.md` §6).** Land as
advisory: `--warning-only` default, frozen allowlist, **no** hard workflow gate.
`011_prompt_management_plan.md` §10.4 notes a *later* wiring into
`scripts/run_all_tests.sh` / `refactor-guards.yml`; that promotion is a separate,
explicitly-scoped subtask and uses `continue-on-error: true` (like
`docs-sync.yml`'s advisory `translation_freshness` step). This subtask does
**not** modify any of the 5 existing workflows.

## 8. Concrete Work Items

1. Read `009_quality_scripts_plan.md` §3/§5.7/§8, `011_prompt_management_plan.md`
   §2/§3/§5.x/§10, and the **Subtask 036** census output. Copy the checker shape
   from `scripts/docs/check_doc_sources.py`.
2. Reuse `scripts/quality/_common.py` if it exists; otherwise create
   `scripts/quality/` and write the minimal `_common.py` (JSON emitter matching
   the §3 schema; allowlist YAML loader; Markdown table writer; `--base-ref`
   resolver mirroring `check_ref_coupling.py`).
3. Write `scripts/check_prompts.py`:
   - `REPO_ROOT = Path(__file__).resolve().parents[1]`; shebang; docstring citing
     `009_quality_scripts_plan.md` §5.7 and `011_prompt_management_plan.md`.
   - `ast`-based walk over target `.py` files with the exclusions from Section 5
     (`tests/`, `node_modules/`, `__pycache__/`, `vendor/`, the two `KEEP_INLINE`
     files) and `--target` override.
   - Heuristic classification (`min_lines`, `min_chars`, marker list from config);
     emit candidates with `name`/line.
   - `--with-snapshots` → subprocess `report/scripts/check_prompt_snapshots.py
     --root <REPO_ROOT>`; fold exit code into the report. Handle "script missing"
     → `SystemExit(2)`.
   - Allowlist load + `known`/`new` tagging; `--fail-on-regression`,
     `--warning-only`, `--format`, `--output`, `--base-ref`, `--update-baseline`.
4. Write `scripts/quality/check_prompts.yaml` (markers, `min_lines`, `min_chars`,
   target/exclude globs).
5. Generate `scripts/quality/check_prompts.allow.yaml` via `--update-baseline` on
   the current tree; **reconcile it against the Subtask 036 census** — every
   036-catalogued inline prompt should appear, tagged with its 036 verdict; the
   two `KEEP_INLINE` files must be present. If the heuristic misses a
   036-listed prompt or flags something 036 marked `KEEP_INLINE`, tune the
   markers/thresholds, do not hand-edit findings away.
6. Add `scripts/quality/README.md` (per-directory README convention) **if** this
   subtask created `scripts/quality/`.
7. Update `scripts/README.md` `## Contents` to list `check_prompts.py` (and the
   `quality/` subtree if newly created) — or run `python scripts/readme_sync.py
   --write` and stage the result — so `readme_sync.py --check` stays green.
8. Ensure the new `.py` files are **ruff-clean** so the repo-wide `ruff check .`
   baseline does not rise.
9. Optional self-test (e.g. `ari-core/tests/test_check_prompts.py` or
   `scripts/quality/tests/`) covering: a synthetic module with an inline
   role-marked multi-line prompt is flagged; an allowlisted one is suppressed;
   `ari-core/ari/agent/loop.py` yields **no** candidate (negative control).
   Additive — no existing `scripts/docs/` checker has dedicated tests, so this is
   not required for parity.
10. Run the Section-12 gates; confirm the checker reproduces the 036 candidate set
    under `--warning-only` and that `--fail-on-regression` is green on the clean
    tree.

## 9. Files Expected to Change

Runtime code: **none**.

Created (dev tooling / config / docs only):
- `scripts/check_prompts.py` — the checker.
- `scripts/quality/check_prompts.yaml` — heuristic thresholds/markers.
- `scripts/quality/check_prompts.allow.yaml` — frozen inline-prompt baseline
  (seeded from the Subtask 036 census).
- `scripts/quality/_common.py` — shared checker infrastructure **only if not
  already created by an earlier quality-script subtask** (025/026/029/030/031).
- `scripts/quality/README.md` — per-directory README **only if this subtask
  creates `scripts/quality/`**.
- *(optional)* `ari-core/tests/test_check_prompts.py` — self-test.

Updated (non-runtime):
- `scripts/README.md` — `## Contents` gains `check_prompts.py` (and the
  `quality/` entry if newly created) for `readme_sync.py --check`.

Explicitly **not** changed:
- `report/scripts/check_prompt_snapshots.py` / `snapshot_prompts.py` (invoked,
  not edited).
- Any `ari-core/ari/prompts/**` template, `ari-core/tests/test_prompt_extraction.py`,
  or any inline prompt in `ari-skill-*/src/*.py`.
- Any of `.github/workflows/{docs-change-coupling,docs-sync,pages,readme-sync,refactor-guards}.yml`.
- Any file under `ari-core/ari/`, `ari-skill-*/`, the frontend,
  `ari-core/config/`, or `ari-core/ari/configs/`.

## 10. Files / APIs That Must Not Be Broken

This subtask adds a read-only static-analysis script and touches no runtime
surface, so it breaks nothing directly. It must nonetheless preserve:

- **CLI** `ari = ari.cli:app` — untouched; the checker adds no `ari` subcommand
  and is invoked as `python scripts/check_prompts.py`.
- **`ari.public.*`** (`claim_gate`, `config_schema`, `container`, `cost_tracker`,
  `llm`, `paths`, `run_env`, `verified_context`) — not imported, not modified.
- **MCP tool contracts** (14 `ari-skill-*/src/server.py`) — the checker *reads*
  these files for inline prompts; it must not edit them or change any tool
  contract. The sanctioned `ari-core → ari_skill_memory` edge is irrelevant here.
- **`FilesystemPromptLoader` / `PromptLoader` Protocol** (`ari-core/ari/prompts/`)
  — the checker measures *against* the externalized set; it does not alter the
  loader, the templates, or their keys.
- **Gate 10** (`report/scripts/check_prompt_snapshots.py`) — invoked via its
  documented `--root` CLI; its behavior and the `% snapshot-from:` header format
  must remain the single source of truth for snapshot bytes.
- **Dashboard API** (`ari/viz/routes.py` + `api_*.py` + `websocket.py`) — not a
  target and not modified.
- **Checkpoint / output / config file formats** — untouched; the checker writes
  only its own report (stdout or `--output`).
- **Scripts invoked by `.github/workflows/`** — the `readme_sync.py --check` gate
  (`readme-sync.yml`) must stay green, which is why `scripts/README.md` is updated
  in the same change. `scripts/git-hooks/pre-commit` runs `readme_sync.py --write`
  (non-blocking); the new files must be README-sync-consistent so the hook does
  not report a lingering `— TODO`. The other four workflows are not modified.

## 11. Compatibility Constraints

- **Do not duplicate Gate 10.** The snapshot-consistency slice is delegated to
  `report/scripts/check_prompt_snapshots.py` via subprocess; re-deriving its
  SHA-256 header logic would create a second, drift-prone source of truth
  (`009_quality_scripts_plan.md` §5.7). If Gate 10 changes its CLI, this checker's
  `--with-snapshots` path adapts; it holds no copy of Gate 10's internals.
- **No new dependency.** stdlib `ast`/`tokenize`/`subprocess` + PyYAML (already a
  core dep). No `radon`/`vulture`.
- **Determinism (P2).** No LLM, no network — same input tree ⇒ same candidate
  report. Matches the `scripts/docs/` convention (PyYAML the only non-stdlib dep)
  and ARI's LLM-free quality-tooling posture.
- **Byte-identical downstream extraction.** This checker only *detects*; the
  actual externalization (Subtasks 039/041) must keep
  `ari-core/tests/test_prompt_extraction.py` green (byte-identical extraction is
  the migration safety net, `011_prompt_management_plan.md` §12). Nothing here
  changes prompt bytes, so those hashes are untouched.
- **README-sync parity.** Adding a file under `scripts/` (and possibly creating
  `scripts/quality/`) obliges updating `scripts/README.md` (and adding
  `scripts/quality/README.md`); otherwise `readme_sync.py --check` (and
  `readme-sync.yml`) fails.
- **Warning-mode-first.** Default `--warning-only`, frozen allowlist, **no** hard
  CI gate in this subtask. Promotion to `--fail-on-regression` in CI is a later,
  explicit subtask (`009_quality_scripts_plan.md` §6; `011` §10.4).
- **Allowlist keying stability.** Key allowlist entries by `(file,
  constant-name)` where a name exists, falling back to `(file, line)`; a keyed
  entry must survive small line drift in a large file (e.g.
  `ari-skill-paper/src/server.py`, 2956 L) so an unrelated edit above a prompt
  does not resurface it as `new`.

## 12. Tests to Run

- `python -m compileall .` — confirms the new `.py` files (and nothing else)
  compile; no runtime `.py` was accidentally touched.
- `pytest -q` — full suite must pass unchanged from baseline (heaviest:
  `ari-core/tests/test_server.py` 1844, `test_gui_errors.py` 1650,
  `test_workflow_contract.py` 1606; and the prompt pin
  `ari-core/tests/test_prompt_extraction.py` 107). If a self-test was added, it
  runs here.
- `ruff check .` — the new `scripts/check_prompts.py` (and `scripts/quality/_common.py`
  if created) must be ruff-clean so the repo-wide count does not increase.
- `python scripts/readme_sync.py --check` — must exit 0 after `scripts/README.md`
  (and any new `scripts/quality/README.md`) is updated (this is the gate
  `readme-sync.yml` runs).
- **Checker self-run (smoke):**
  - `python scripts/check_prompts.py --warning-only` → exit 0; the Markdown
    inventory lists the evaluator/paper/plot/vlm/transform/web inline prompts and
    yields **no** candidate for `ari-core/ari/agent/loop.py` (negative control).
  - `python scripts/check_prompts.py --format json` → valid JSON per the §3 schema.
  - `python scripts/check_prompts.py --fail-on-regression` on the clean tree →
    exit 0 (all current inline prompts allowlisted).
  - `python scripts/check_prompts.py --with-snapshots --warning-only` → exit 0 and
    reports Gate 10's result (equivalent to `make check-prompt-snapshots`).
- **Frontend (`npm test` / `npm run build` under `ari-core/ari/viz/frontend/`) is
  NOT applicable** — this subtask adds a Python static-analysis script and does
  not touch frontend code (`npm`, not `pnpm`, in this env).

If `compileall` / `pytest` / `ruff check .` regress beyond baseline, the session
touched something outside the intended file set and must revert.

## 13. Acceptance Criteria

1. `scripts/check_prompts.py` exists, is executable-style
   (`#!/usr/bin/env python3`), uses `REPO_ROOT = Path(__file__).resolve().parents[1]`,
   depends only on stdlib + PyYAML, and its docstring cites
   `009_quality_scripts_plan.md` §5.7.
2. `scripts/quality/check_prompts.yaml` and `scripts/quality/check_prompts.allow.yaml`
   exist; `_common.py` and `scripts/quality/README.md` exist (reused or created).
3. The inline-inventory slice reports the known inline prompts — the evaluator
   judge prompts (`ari-skill-evaluator/src/server.py:191,790`), the paper-skill
   prompts (`ari-skill-paper/src/server.py`), and the plot/vlm/transform/web role
   prompts — and yields **no** candidate for `ari-core/ari/agent/loop.py`
   (already externalized). The allowlist matches the Subtask 036 census.
4. The snapshot slice is **delegated**: `--with-snapshots` invokes
   `report/scripts/check_prompt_snapshots.py --root <REPO_ROOT>` and does not
   re-derive `% snapshot-from:` SHA-256s.
5. All of `--target`, `--config`, `--output`, `--format markdown|json`,
   `--warning-only`, `--fail-on-regression`, `--base-ref`, `--with-snapshots`,
   `--update-baseline` are accepted; exit convention is `0`/`1`/`2` per Section 7.6.
6. `--fail-on-regression` on the clean tree exits `0` (every current inline prompt
   is allowlisted); a synthetic net-new role-marked inline prompt makes it exit `1`.
7. `python scripts/readme_sync.py --check` passes (README updated for the new
   files).
8. `python -m compileall .`, `pytest -q`, and `ruff check .` pass with no new lint
   debt from the added scripts.
9. No runtime code, config, prompt template, workflow, frontend, or directory
   under `ari-core/ari/` / `ari-skill-*/` / the frontend was created, edited,
   moved, renamed, or deleted. No inline prompt was extracted or moved. The word
   "deprecated" is not applied to any internal code.

## 14. Rollback Plan

Trivial and complete — the subtask's artifacts are new tooling files plus one
README edit, none imported by runtime code:

- `git rm scripts/check_prompts.py` and `git rm scripts/quality/check_prompts.yaml
  scripts/quality/check_prompts.allow.yaml`.
- If this subtask *created* `scripts/quality/`, `git rm -r scripts/quality/`
  (including `_common.py` and `README.md`); if it *reused* an existing
  `scripts/quality/`, leave `_common.py` in place and remove only the
  `check_prompts.*` files.
- `git checkout -- scripts/README.md` to restore the `## Contents` block (or
  re-run `python scripts/readme_sync.py --write`).
- If the optional self-test was added, `git rm ari-core/tests/test_check_prompts.py`.

No runtime state, no migrations, no config-format change, no schema change, no
workflow change, no change to Gate 10 → nothing else to undo. Rollback cannot
affect the running system, checkpoints, MCP tools, the dashboard, the prompt
loader, or any preserved contract.

## 15. Dependencies

Per the program dependency graph
(`036 -> 037, 038, 039, 040, 041, 042, 043, 044`) and
`docs/refactoring/007_subtask_index.md:90`:

- **Predecessor (hard, incoming edge):** `036 -> 043`. Subtask 043 **depends on
  Subtask 036** (`inventory_hardcoded_prompts`), the exhaustive line-level census
  of every inline prompt with a per-string KEEP_INLINE/EXTRACT/MERGE/MOVE/REVIEW
  verdict. That census is the ground truth that (a) seeds
  `check_prompts.allow.yaml` and (b) validates the checker's heuristics
  (the checker must reproduce the 036 candidate set). 043 must not start until
  036 is complete.
- **036 is an inventory/measurement gate.** It is one of the nine inventory
  subtasks (001, 002, 020, 036, 045, 053, 059, 060, 067) that **must precede any
  runtime code change**. 043 sits downstream of 036 and is itself **not** a
  runtime code change (it adds tooling), so it neither blocks nor is blocked by
  the runtime-editing Phase-7 cohort (039/040/041/044) beyond sharing the 036
  predecessor.
- **No outgoing hard edge from 043** in the provided graph — 043 is not a
  predecessor of any other subtask.
- **Sibling coordination (same predecessor 036, no edge between them):**
  - 037 `define_prompt_template_policy`, 038 `introduce_prompt_registry_and_loader`,
    039/040/041 `extract_*_prompts`, 042 `add_prompt_snapshot_tests`,
    044 `add_prompt_version_tracking_to_run_metadata`.
  - **042 overlaps Gate 10** on the snapshot side (`007_subtask_index.md:309`);
    coordinate so 043's `--with-snapshots` calls Gate 10 and 042 extends the
    pytest snapshot pins — neither re-implements the other.
  - As 039/041 externalize inline prompts, 043's allowlist should shrink
    (`EXTRACT_TEMPLATE` entries removed as they land). Keep the allowlist format
    simple so those subtasks can drop entries cleanly.
- **Shared tooling (no hard edge):** if the Phase-8 quality-script subtasks
  (025/026/029/030/031) have already created `scripts/quality/_common.py`, reuse
  it; there is no build-order edge requiring them first, but 043 must tolerate
  both "directory exists" and "directory absent" states.

This is consistent with the provided graph edge `036 -> 043`, the inventory-gate
list, and the canonical subtask index.

## 16. Risk Level

- **Risk: Low.**
- **Changes runtime code? No.** The deliverables are dev tooling
  (`scripts/check_prompts.py`, `scripts/quality/check_prompts.{yaml,allow.yaml}`,
  optionally `_common.py` + `scripts/quality/README.md`), a documentation README
  update (`scripts/README.md`), and an optional test. None is imported by the
  `ari` package, any `ari-skill-*` server, the CLI, the dashboard, the prompt
  loader, or any of the 5 workflows. The checker is read-only static analysis and
  modifies no runtime code, imports, prompts, configs, workflows, frontend, or
  directory names.
- Residual risks: (a) heuristic **false negatives** (missing an inline prompt the
  036 census caught) or **false positives** (flagging a docstring/vendored string)
  — mitigated by reconciling the allowlist against the 036 census and using the
  `agent/loop.py` negative control; (b) Gate 10's CLI shifting under
  `--with-snapshots` — mitigated by treating a missing/failed Gate 10 script as
  exit `2` and keeping the slice default-off; (c) forgetting the `scripts/README.md`
  update and failing `readme-sync.yml` — mitigated by the explicit `readme_sync
  --check` gate in Section 12. All are contained to tooling and caught by the
  standard gates.

## 17. Notes for Implementer

- **036 first, then freeze.** Do not invent the candidate list — run against the
  tree and diff your findings against the Subtask 036 census. If they disagree,
  the census is the reference for *which strings count as prompts*; tune the
  heuristic (markers, `min_lines`, `min_chars`) until they line up, then freeze
  the allowlist. Record the reconciliation in the PR.
- **Structure, not "You are".** `ari-core/ari/agent/loop.py` (1630 L) has 0 "you
  are" hits (its prompt is externalized) and `_paperbench_bridge.py` is full of
  vendored "You are allowed to browse…" that must be ignored. Key on *multi-line
  literal + role/JSON marker + length*, exclude the vendored/fallback files, and
  use `agent/loop.py` as a negative control in the self-test.
- **Defer, never duplicate, Gate 10.** The snapshot slice is
  `subprocess.run([... , "report/scripts/check_prompt_snapshots.py", "--root",
  str(REPO_ROOT)])`. Do not copy its `HEADER_RE` / SHA-256 logic. Keep
  `--with-snapshots` default-off so the two gates run independently.
- **Placement = `scripts/` top level** (`parents[1]`), matching `readme_sync.py`
  and `009_quality_scripts_plan.md` §8 — **not** `scripts/docs/` (that family is
  docs/i18n) despite the loose `011` §10.4 wording. Match the sibling checkers'
  argparse/`--json`/exit conventions.
- **Reuse `_common.py` if present.** This may or may not be the first
  `scripts/quality/` checker depending on whether a Phase-8 subtask landed first;
  write the code to import `_common.py` if it exists and create the minimal
  version otherwise. Do not fork a second helper.
- **Allowlist verdicts carry the classification vocabulary.** Tag each entry
  (`EXTRACT_TEMPLATE`, `MERGE_DUPLICATE`, `MOVE_TO_CONFIGURABLE_PROMPT`,
  `KEEP_INLINE`, `REVIEW_REQUIRED`) so the checker's output doubles as the
  living version of the 036 inventory and the extraction subtasks (039/041) can
  see what remains.
- **Warning-mode-first, no CI wiring here.** Ship `--warning-only` as the default
  and a frozen allowlist. Do **not** edit any workflow; promotion to a
  `--fail-on-regression` CI gate (or wiring into `scripts/run_all_tests.sh` /
  `refactor-guards.yml`) is a separate, explicitly-scoped subtask.
- **Keep the README gate green in the same commit.** After adding the files, run
  `python scripts/readme_sync.py --write`, stage the updated `scripts/README.md`
  (and any new `scripts/quality/README.md`), then verify `--check` exits 0 —
  otherwise `readme-sync.yml` fails on the PR.
- **Match the house style.** Mirror `scripts/docs/check_doc_sources.py`: shebang,
  docstring citing the design doc, `argparse`, a small `Finding`/dataclass with
  `as_dict()`, `SystemExit(2)` on environment error. Consistency with the existing
  checker family is a review criterion.

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **043** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
