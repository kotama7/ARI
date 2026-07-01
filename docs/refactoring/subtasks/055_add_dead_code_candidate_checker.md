# Subtask 055: Add Dead Code Candidate Checker

- **Phase:** Phase 1 — Measurement and Inventory
- **Subtask ID:** 055
- **Title (index):** `add_dead_code_candidate_checker`
- **Primary deliverable:** a new, self-contained Python checker
  `scripts/check_dead_code.py` (plus its `scripts/quality/` config + allowlist)
  that **classifies** the reference-graph produced by subtasks 053/054 into the
  §7 dead-code vocabulary of `docs/refactoring/013_reference_graph_and_dead_code_plan.md`
  and emits a ranked, human-reviewable candidate list. It **classifies only** — it
  deletes, moves, quarantines, and renames **nothing**.
- **Runtime code change:** **No** (dev tooling only — see Section 16).
- **Repo root:** `/home/t-kotama/workplace/ARI` (git branch `main`; `ari-core`
  version `0.9.0`, from `ari-core/pyproject.toml`).
- **Canonical language:** English.
- **Classification vocabulary.** Directory/module-level decisions use the master
  set `KEEP` / `ADAPT` / `MERGE` / `MOVE_TO_LEGACY` / `DELETE_CANDIDATE` /
  `REVIEW_REQUIRED`. Symbol-level dead-code decisions use the finer set from
  `013` §7: `PUBLIC_CONTRACT` / `DYNAMIC_REFERENCE_RISK` / `TEST_ONLY` /
  `DOCS_ONLY` / `QUARANTINE_CANDIDATE` / `SAFE_DELETE_CANDIDATE` /
  `REVIEW_REQUIRED`. The word "deprecated" is reserved for external contracts
  only (public API, CLI, MCP, dashboard API, documented import paths,
  `ari-skill-*` stable interfaces) and is **never** used to label an internal
  orphan.

---

## 1. Goal

Deliver `scripts/check_dead_code.py`: a deterministic, stdlib + PyYAML + ruff-CLI
checker that consumes the `reference_graph.json` artifact built by subtasks 053
(static graph) and 054 (dynamic-edge overlay), applies the §7 precedence rules of
`docs/refactoring/013_reference_graph_and_dead_code_plan.md`, and emits a ranked
`dead_code_candidates.md` (design doc §6.2) grouped by classification. The checker
also folds in the already-available ruff unused-symbol signal (`F401` 341, `F841`
39, `F811` 8 — measured 2026-07-01) as corroborating evidence, and offers a
`--check` CI-ratchet mode that fails **only** when a *new* `SAFE_DELETE_CANDIDATE`
appears above a frozen budget.

This checker establishes the dead-code classification gate that **does not exist
anywhere in the repo today**: `grep` over `*.py/*.sh/*.yml/*.md` confirms no
`check_dead_code` implementation exists (only planning-doc mentions), `vulture` is
**not installed** (`import vulture` → `ModuleNotFoundError`), and ruff's `F401`
signal is present but **not wired into any of the 5 workflows**. Its verdict for
the checker family is `KEEP` (net-new) per `docs/refactoring/009_quality_scripts_plan.md`
§4/§10 and `013` §8.3/§10.

Success = a fresh coding session, given a valid `reference_graph.json` from 053/054,
can (1) reproduce a deterministic `dead_code_candidates.md` (byte-identical on two
runs of the same commit, per `013` §6.4), (2) classify every node into exactly one
§7 bucket with precedence `PUBLIC_CONTRACT`/`DYNAMIC_REFERENCE_RISK` outranking
`SAFE_DELETE_CANDIDATE`, (3) place the four `ari/publish/backends/*` modules, the
`ari/prompts/**/*.md` templates, and the 23 `ari-core/config/reviewer_rubrics/*.yaml`
in `DYNAMIC_REFERENCE_RISK` (kept), the `ari.schemas.load()` loader in `TEST_ONLY`,
and never mark the empty `ari/__init__.py` or docstring-only `ari/public/__init__.py`
as dead, and (4) fail `--check` **only** on net-new orphans above the budget,
never on the historical baseline.

## 2. Background

ARI has a mature *documentation/i18n* gate family under `scripts/docs/`
(`check_doc_sources.py`, `check_doc_links.py`, `check_i18n_js.py`,
`check_readme_parity.py`, `check_ref_coupling.py`, `check_report_cochange.py`,
`check_site_i18n.py`, `check_translation_freshness.py`) and a *report-build* gate
family under `report/scripts/` (`check_prompt_snapshots.py` Gate 10, etc.). It has
**no source-code reachability / dead-code suite**.
`docs/refactoring/013_reference_graph_and_dead_code_plan.md` is the parent design;
it defines a three-tool chain (§8, §10):

| Subtask | Deliverable | Deletes code? |
|---|---|---|
| **053** | `analyze_references.py` — static Python/TS reference graph + root seeding; emits `reference_graph.json` (`013` §6.1, §8.1). | No |
| **054** | Dynamic-edge overlay — enumerate the §5 seams + MCP collision report; injects `dynamic.*` / `cross_lang.http` edges (`013` §8.2). | No |
| **055 (this)** | `check_dead_code.py` — classifier over the §7 vocabulary; emits `dead_code_candidates.md`; `--check` ratchet (`013` §8.3). | **No** |
| 056 | Quarantine mechanism (`MOVE_TO_LEGACY` holding zone) for `QUARANTINE_CANDIDATE`. | No (relocates) |
| 057 | Execute deletions — remove **only** reviewed `SAFE_DELETE_CANDIDATE`. | **Yes (only here)** |
| 058 | `generate_quality_report.py` — fold dead-code counts into the quality report. | No |

**055 is a pure classifier/reporter.** Deletion happens only in 057. This subtask
produces the evidence surface (`dead_code_candidates.md`) that human review and
subtasks 056/057/058 consume.

Why static import analysis alone is insufficient (grounded, from `013` §2/§5 —
each verified by inline inspection): several categories of live code are reachable
**only** through string keys, filesystem paths, subprocess boundaries, or
cross-language HTTP that a Python AST import graph never records:

- **String-keyed backend dispatch** — `ari-core/ari/publish/__init__.py:198`
  `_load_backend(name)` lazily imports one of
  `ari-core/ari/publish/backends/{ari_registry,local_tarball,zenodo,gh}.py`
  (213/48/139/134 LOC) **by string name**; these four modules have no static
  importer. A naive graph flags them dead — they are the live `ari publish` path.
- **Prompt keys as paths** — `ari-core/ari/prompts/**/*.md` templates are loaded
  via `ari-core/ari/prompts/_loader.py` `FilesystemPromptLoader.load(key)` (e.g.
  `evaluator/llm_evaluator.py:255 .load("evaluator/extract_metrics")`,
  `orchestrator/bfts.py:744 .load("orchestrator/bfts_expand")`); no `import`
  references the `.md` files.
- **Rubric/config DATA reached by name** — `ari-core/config/reviewer_rubrics/*.yaml`
  (23 files), `paperbench_rubrics/*.yaml`, `profiles/{cloud,hpc,laptop}.yaml`,
  selected by `ari paper --rubric` / `ARI_RUBRIC`; no import references them.
- **MCP tool dispatch** — the 14 `ari-skill-*/src/server.py` handlers are reachable
  only by string tool name over stdio via `ari-core/ari/mcp/client.py`
  `MCPClient.call_tool(...)` (`client.py:227`). ari-core never imports skill
  modules for dispatch.
- **Cross-language HTTP/WS** — `ari-core/ari/viz/frontend/src/services/api.ts`
  (863 LOC) calls endpoints across `ari-core/ari/viz/routes.py` (1197) + the 14
  `ari-core/ari/viz/api_*.py` modules + `websocket.py`; a Python-only graph never
  sees these edges.
- **Empty `__init__` masking** — `ari-core/ari/__init__.py` is **empty** and
  `ari-core/ari/public/__init__.py` is **docstring-only**; a tool assuming
  "public API = names in `__init__.__all__`" would mark the whole 148-LOC contract
  surface dead — the opposite of the truth.

The unifying rule (`013` §2): **absence of a static import edge is necessary but
not sufficient evidence of deadness.** 055's classifier trusts the 053/054 graph
(which already overlays the dynamic edges) and applies precedence so contract and
dynamic-seam nodes can never fall into `SAFE_DELETE_CANDIDATE`.

Tooling baseline (measured, confirmed this planning session):

| Tool | State | Consequence |
|---|---|---|
| `vulture` | **NOT installed** (`import vulture` → `ModuleNotFoundError`) | do not assume vulture; lean on ruff + the 053/054 graph. |
| `radon` | **NOT installed** | irrelevant to dead-code; not used here. |
| `ruff` | **installed, 0.15.2** | supplies `F401` (341), `F841` (39), `F811` (8) as corroborating unused-symbol hints. |
| `python` / `compileall` / `pytest` | available (3.13.2) | AST fallback + test gate. |
| `PyYAML` | available (`pyyaml>=6.0` in `ari-core/pyproject.toml`) | config/allowlist parsing. |
| `node` / `npm` | available; **no `pnpm`** | not needed — TS reachability comes from the 053/054 graph, not a build. |

Crucially, `ari-core/ari` is **30,277 LOC** of production Python (with `viz/` alone
**8,131** / 27%), plus ≈25.5k LOC across the 14 `ari-skill-*` packages, and the
`ari/public/` frozen surface is only **148 LOC**. The genuine `SAFE_DELETE_CANDIDATE`
set is expected to be **small** and dominated by leftover helpers surfaced by ruff
`F401`/`F841` chains and fully-superseded internal utilities (`013` §7 "Expected
shape of results").

## 3. Scope

In scope:

1. Create **`scripts/check_dead_code.py`** — the classifier, conforming to the
   house style of `scripts/docs/` (`#!/usr/bin/env python3`, module docstring
   citing `docs/refactoring/013_reference_graph_and_dead_code_plan.md` §7/§8.3,
   `argparse`, `REPO_ROOT = Path(__file__).resolve().parents[1]`, stdlib + PyYAML
   + ruff CLI only, `SystemExit(2)` on environment/usage error). It lives at the
   `scripts/` top level beside `readme_sync.py` (source-code gate family), **not**
   under `scripts/docs/`.
2. **Input contract.** Consume the `reference_graph.json` produced by subtasks
   053 (static edges) + 054 (dynamic overlay), whose schema is fixed in `013`
   §6.1 (`schema_version`, `roots[]`, `nodes[]` with `category`/`reachable_from`/
   `edges_in`, `edges[]` with `evidence`, `collisions[]`). Path is configurable
   via `--graph` (default `docs/refactoring/reports/reference_graph.json`).
3. **Classification.** Apply the §7 precedence rules top-down (first match wins):
   `PUBLIC_CONTRACT` → `DYNAMIC_REFERENCE_RISK` → `PUBLIC_CONTRACT`-adjacent
   `REVIEW_REQUIRED` → `TEST_ONLY` → `DOCS_ONLY` → `QUARANTINE_CANDIDATE` →
   `SAFE_DELETE_CANDIDATE` → `REVIEW_REQUIRED` (default). A node is
   `SAFE_DELETE_CANDIDATE` **only** if it fails *every* liveness test (§3–§5 of
   `013`); when in doubt the classifier **downgrades** to `REVIEW_REQUIRED` /
   `QUARANTINE_CANDIDATE`, never up.
4. **Corroborating ruff signal (reuse, do not re-derive).** Ingest
   `ruff check ari-core --output-format json` and attach `F401`/`F841`/`F811`
   findings as `evidence` on the matching graph nodes; ruff is the authority on
   unused *imports/locals*, the 053/054 graph is the authority on *cross-module
   reachability*. Do not let a bare `F401` alone promote a node to
   `SAFE_DELETE_CANDIDATE` if the graph shows any inbound edge.
5. **Output** (`013` §6.2): a ranked `dead_code_candidates.md` (most-confident
   deletions first), grouped by classification, one row per candidate node:
   `file`, `symbol`, `loc`, `classification`, `reachable_from` (empty for
   orphans), `evidence`, one-line rationale. Also a stable JSON form for the 058
   aggregator. Default output dir `docs/refactoring/reports/` (configurable via
   `--output`).
6. **`scripts/quality/` config + allowlist** per `009` §4/§8 and `013` §8.3:
   `scripts/quality/check_dead_code.yaml` (roots override, classification config,
   `--check` budget) and `scripts/quality/check_dead_code.allow.yaml` (frozen
   known-orphan baseline keyed by symbol qualname / module path). Reuse
   `scripts/quality/_common.py` (JSON emitter, allowlist loader, Markdown-table
   writer, `--base-ref` resolver) **if already bootstrapped** by an earlier
   quality-checker subtask; otherwise extend it minimally (see Section 15).
7. **`--check` ratchet mode** (`013` §8.3): exit non-zero **only** when a
   `SAFE_DELETE_CANDIDATE` not on the allowlist appears (net-new dead code above
   budget), mirroring the `readme_sync.py --check` / `check_*` gate pattern. This
   subtask does **not** wire it into any workflow.
8. Keep the `readme_sync.py` gate green: adding `scripts/check_dead_code.py` and
   any new `scripts/quality/*` files obliges updating `scripts/README.md`'s
   `## Contents` (and `scripts/quality/README.md`) because `readme-sync.yml` runs
   `python scripts/readme_sync.py --check` (exit 1 on missing/extra paths).

Out of scope (owned by sibling subtasks; do **not** implement here):

- **Building the reference graph** — that is subtask 053 (`analyze_references.py`,
  static) + 054 (dynamic overlay). 055 *consumes* `reference_graph.json`; it does
  not walk the AST or resolve dynamic seams itself. If the graph is absent, 055
  exits `2` (environment error), it does not silently regenerate it.
- **Quarantining any code** — subtask 056 (`MOVE_TO_LEGACY` holding zone). 055
  only *labels* `QUARANTINE_CANDIDATE`.
- **Deleting any code** — subtask 057, the **only** deletion step. 055 labels
  `SAFE_DELETE_CANDIDATE`; it removes nothing.
- **The quality-report rollup** — subtask 058 (`generate_quality_report.py`)
  folds 055's counts into the repo report.
- Installing `vulture`/`radon`, or adding a `[tool.ruff]` block to
  `ari-core/pyproject.toml`.
- Wiring `--check` into any of the 5 workflows as a hard gate (advisory,
  warning-mode-first — `009` §6/§7, `013` §8.3).

## 4. Non-Goals

- **No runtime code changes.** No edits to any file under `ari-core/ari/`,
  `ari-skill-*/`, the frontend, `ari-core/config/`, `ari-core/ari/configs/`,
  `ari-core/ari/config/`, prompts, or `.github/workflows/`.
- **No deletions, moves, renames, or quarantines.** 055 emits a *candidate list*;
  it never touches the code it names. The four `ari/publish/backends/*` modules,
  the `ari/prompts/**/*.md` templates, the 23 reviewer rubrics, and the empty
  `ari/__init__.py` all stay exactly where they are.
- **No graph construction.** 055 does not re-implement 053/054's AST walk,
  dynamic-seam scan, or cross-language edge matching. It trusts and validates the
  `reference_graph.json` schema (`013` §6.1) and fails `2` on a missing/malformed
  graph.
- **No new runtime dependency.** No `vulture`, no `radon`; the checker depends only
  on the ruff CLI (present) + stdlib + PyYAML (`pyyaml>=6.0`, already a core dep).
- **No `[tool.ruff]` in `ari-core/pyproject.toml`.** `F401`/`F841`/`F811` are
  ruff *defaults* (rule families `F`/`E` active without config); the checker
  invokes `ruff check ... --output-format json` per-run and does not persist a
  ruff config (that would silently change the repo-wide lint posture and is a
  separate decision).
- **No LLM calls, no network** (design principle P2 + `013` §6.4 determinism).
  Same commit ⇒ byte-identical `dead_code_candidates.md`.
- **No hard CI gate** in this subtask; `--check` ships advisory and is not added
  to any workflow.
- **No auto-promotion.** The classifier must never upgrade a node into
  `SAFE_DELETE_CANDIDATE` on ambiguity — it downgrades to `REVIEW_REQUIRED`.
- **No `pnpm`** usage (absent); frontend reachability comes from the 053/054 graph.

## 5. Current Files / Directories to Inspect

All paths verified present on `main` at planning time unless marked. Line counts
are `wc -l`.

**Parent design (read first, before implementing):**
- `docs/refactoring/013_reference_graph_and_dead_code_plan.md` (512 lines) — §3
  root set, §4 node/edge/category kinds, §5 dynamic seams, §6.1 `reference_graph.json`
  schema (the input contract), §6.2 `dead_code_candidates.md` shape (the output
  contract), §6.4 determinism, §7 classification precedence table (the core
  algorithm), §8.3 checker role, §9 deletion/quarantine workflow, §10 subtask map.
- `docs/refactoring/009_quality_scripts_plan.md` — §3 common script contract, §5.10
  `check_dead_code.py` design block, §8 `scripts/quality/` placement + `_common.py`,
  §6/§7 warning-mode-first rollout, §10 subtask table (`check_dead_code` = 055).

**House-style reference (the convention to copy):**
- `scripts/docs/check_doc_sources.py` — canonical checker shape: shebang, docstring
  citing a design doc, `argparse` with `--json`, `Finding`-style dataclass with
  `as_dict()`, exit `1` on error / `SystemExit(2)` on missing PyYAML.
- `scripts/docs/check_ref_coupling.py` — `--base-ref origin/main` git-diff
  resolution to mirror for `--check` net-new detection; fails CLOSED under a strict
  flag (pattern for the ratchet).
- `scripts/readme_sync.py` — lives at `scripts/` top level, uses
  `REPO_ROOT = Path(__file__).resolve().parents[1]`; the new checker sits beside
  it with the same `parents[1]`.

**Directory the checker is added to / reads / writes:**
- `scripts/` — top level (has `readme_sync.py`, `run_all_tests.sh`, `git-hooks/`,
  `docs/`, `setup/`, `letta/`, `registry/`, `fewshot/`, `README.md`). The new
  `check_dead_code.py` goes **here**.
- `scripts/quality/` — **does not exist today** (`ls scripts/quality` → "No such
  file or directory"). Holds `_common.py` + `<name>.yaml` + `<name>.allow.yaml`
  per `009` §8; bootstrapped by whichever quality-checker subtask runs first
  (`check_complexity` per `009` §8, or `analyze_references` in this chain). 055
  reuses it or extends it minimally.
- `scripts/README.md` — its `## Contents` block (currently lists `readme_sync.py`,
  `run_all_tests.sh`, `docs/` checkers, `git-hooks/pre-commit`, etc.) must gain
  `check_dead_code.py` and the `quality/` entry (or be regenerated via
  `readme_sync.py --write`).
- `docs/refactoring/reports/` — currently **empty**; the default output dir for
  `reference_graph.json` (input, from 053/054) and `dead_code_candidates.md`
  (output, from 055). Generated artifacts here should be gitignored or README-synced
  per subtask 033 (`add_generated_files_gitignore_policy`) — coordinate, see
  Section 11.

**Graph-source anchors the checker's classification depends on (read to validate
§7 handling; do NOT edit):**
- `ari-core/ari/publish/__init__.py:198` `_load_backend(name)` + the four
  `ari-core/ari/publish/backends/{ari_registry,local_tarball,zenodo,gh}.py` →
  must classify `DYNAMIC_REFERENCE_RISK`.
- `ari-core/ari/prompts/_loader.py` `FilesystemPromptLoader.load(key)` +
  `ari-core/ari/prompts/**/*.md` (agent/system.md; evaluator/{extract_metrics,peer_review}.md;
  orchestrator/{bfts_expand,bfts_expand_select,bfts_select,lineage_decision,root_idea_selector}.md;
  pipeline/keyword_librarian.md; viz/{wizard_chat_goal,wizard_generate_config}.md)
  → `DYNAMIC_REFERENCE_RISK`.
- `ari-core/config/reviewer_rubrics/*.yaml` (23 files), `paperbench_rubrics/*.yaml`,
  `profiles/{cloud,hpc,laptop}.yaml` → `DYNAMIC_REFERENCE_RISK`.
- `ari-core/ari/schemas/__init__.py` `load(name)`/`schema_path(name)` (only
  reached by `ari-core/tests/test_node_report.py`, via direct path) →
  `TEST_ONLY`.
- `ari-core/ari/__init__.py` (empty) and `ari-core/ari/public/__init__.py`
  (docstring-only) → **not** dead; structural contract shells owned by the
  public-API stream, `PUBLIC_CONTRACT`-adjacent.
- The 14 `ari-skill-*/src/server.py` MCP handlers + `ari-core/ari/mcp/client.py`
  (`call_tool`, `client.py:227`) → `PUBLIC_CONTRACT` (MCP surface).
- `ari-core/ari/viz/routes.py` (1197) + 14 `ari-core/ari/viz/api_*.py` +
  `websocket.py`, consumed by `ari-core/ari/viz/frontend/src/services/api.ts`
  (863) → `PUBLIC_CONTRACT` (dashboard API).

**Confirmed absent (state explicitly, do not chase):**
- `scripts/quality/` and `scripts/check_dead_code.py` (to be created). No
  `vulture`, no `radon`. No `[tool.ruff]` in `ari-core/pyproject.toml`; no
  `ruff.toml`/`.ruff.toml`. No `sonfigs/` directory anywhere. No top-level
  `pyproject.toml`. The `reference_graph.json` input does not exist yet — it is
  produced by predecessors 053/054.

## 6. Current Problems

1. **No dead-code / reachability gate exists.** `grep` over `*.py/*.sh/*.yml/*.md`
   confirms no `check_dead_code` implementation; the only hits are planning docs
   (`013`, `009`, `012`, `006`, `002`, `001`, `007`, and subtask `028`'s "do not
   create" list). Unreferenced helpers accumulate with no automated visibility.
2. **`vulture` is not installed** — the obvious off-the-shelf dead-code tool is
   unavailable, so the checker must lean on the 053/054 graph plus ruff's already
   present `F401`/`F841`/`F811` signal rather than assume a new dependency.
3. **A naive import-graph would be dangerous here.** Without the §5 dynamic
   overlay, the four `publish/backends/*` modules, every `prompts/**/*.md`, the 23
   reviewer rubrics, and every MCP handler would be flagged dead — all live. The
   classifier must trust the 053/054 dynamic edges and precedence, or it will
   produce false `SAFE_DELETE_CANDIDATE`s that endanger the contract firewall.
4. **`ari.schemas.load()` is genuinely TEST_ONLY** and must be labelled as such,
   not deleted: only `ari-core/tests/test_node_report.py` reaches it (by direct
   path), so removing it would break a test while looking safe to a shallow scan.
5. **Empty/near-empty `__init__` files invite false positives.**
   `ari-core/ari/__init__.py` (empty) and `ari-core/ari/public/__init__.py`
   (docstring-only) look dead to an `__all__`-based tool but are the structural
   shells of the 148-LOC public contract.
6. **MCP flat namespace collisions.** `MCPClient._tool_registry`
   (`ari-core/ari/mcp/client.py:283`) maps tool names globally, so two skills'
   handlers can clobber (last wins). The graph (054) surfaces a collision report;
   the classifier must key `mcp.tool` candidates by `(skill, tool_name)` and never
   dedupe two distinct handlers into one "dead" node.
7. **Historical debt must not become red CI.** 30,277 LOC of core + 25.5k of
   skills predate this gate. `--check` must ship warning-mode-first with a frozen
   allowlist so only *net-new* orphans can fail, never the existing baseline
   (`009` §6, `013` §8.3).
8. **Adding a `scripts/` file trips the README-sync gate** unless `scripts/README.md`
   is updated in the same change (`readme-sync.yml` runs `readme_sync.py --check`,
   exit 1 on drift). Writing generated reports under `docs/refactoring/reports/`
   similarly needs the gitignore/README-sync decision of subtask 033.

## 7. Proposed Design / Policy

Deliver `scripts/check_dead_code.py` plus its `scripts/quality/` config/allowlist,
following `013` §6/§7/§8.3 and `009` §3/§5.10/§8.

**7.1 Placement & bootstrap.** The checker lives at `scripts/check_dead_code.py`
(`REPO_ROOT = Path(__file__).resolve().parents[1]`), alongside `readme_sync.py`,
not under `scripts/docs/`. It uses `scripts/quality/` for its config/allowlist and
reuses `scripts/quality/_common.py` (JSON-schema emitter, allowlist loader,
Markdown-table writer, `--base-ref` git-diff resolver mirroring
`check_ref_coupling.py`'s `origin/main` default). If `_common.py` is not yet
present when 055 runs, extend it minimally and keep it generic for the sibling
checkers.

**7.2 Input: `reference_graph.json` (from 053/054).** The checker reads the graph
whose schema is frozen in `013` §6.1: `roots[]`, `nodes[]` (each with `id`, `kind`
∈ {`py.module`,`py.symbol`,`ts.module`,`ts.symbol`,`data.file`,`route`,`mcp.tool`},
`file`, `loc`, `category[]`, `reachable_from[]`, `edges_in[]`), `edges[]` (each
with `from`/`to`/`kind`/`evidence`), and `collisions[]`. It validates
`schema_version == 1` and the presence of the required keys; a missing or
malformed graph is a `SystemExit(2)` environment error (055 does **not**
regenerate it). Path via `--graph` (default
`docs/refactoring/reports/reference_graph.json`).

**7.3 Classification algorithm (`013` §7 precedence — first match wins).** For
each node lacking a resolved inbound edge from a *production* root, evaluate in
order and assign exactly one label:

| Order | Class | Rule (from `013` §7) | Program action |
|---|---|---|---|
| 1 | `PUBLIC_CONTRACT` | `category` includes `PUBLIC_CONTRACT`, or reachable via R4/R5 MCP name+schema+envelope, R6 dashboard endpoint, R7 `ari.public.*`, R2 CLI name/flag/env side-effect, or a checkpoint/config file format. | `KEEP`. Never deleted. |
| 2 | `DYNAMIC_REFERENCE_RISK` | target of any `dynamic.*` edge, or in a known §5 seam even if the resolver could not be proven (all four `publish/backends/*`, `_COMPOSITES` callables, prompt/rubric/schema data files, `ARI_MEMORY_BACKEND`-gated memory classes). | `REVIEW_REQUIRED`/`KEEP`. Treated as live. |
| 3 | `REVIEW_REQUIRED` (contract-adjacent) | entrypoint noise: the unused `server:main` console scripts in `ari-skill-replicate`/`ari-skill-paper-re`; CLI groups behind `except Exception` (`cli/__init__.py:82-100`). | `REVIEW_REQUIRED`. Human: `ADAPT` vs `MOVE_TO_LEGACY`. |
| 4 | `TEST_ONLY` | reachable only from R9 tests (e.g. `ari.schemas.load()`/`schema_path()`). | `REVIEW_REQUIRED`. Never silently deleted (breaks tests). |
| 5 | `DOCS_ONLY` | referenced only by `docs/` / `README*` prose (R10), no code edge. | `REVIEW_REQUIRED`. Coordinate with `check_doc_sources.py`. |
| 6 | `QUARANTINE_CANDIDATE` | no prod/test/docs edge, but too intertwined/risky to delete (large modules, anything touching checkpoint/migration formats, `ari/migrations/`). | `MOVE_TO_LEGACY` (subtask 056). |
| 7 | `SAFE_DELETE_CANDIDATE` | `orphan`: no inbound edge under **any** kind (static/dynamic/cross-lang/test/docs); not in any §5 seam; not a contract surface; small blast radius. | `DELETE_CANDIDATE` — the **only** deletable class, and only in subtask 057. |
| 8 | `REVIEW_REQUIRED` (default) | anything the tooling cannot confidently place. | Human triage. |

**Hard downgrade rule:** a node reaches `SAFE_DELETE_CANDIDATE` only if it fails
*every* liveness test in `013` §3–§5. On any ambiguity the classifier **must
downgrade** to `REVIEW_REQUIRED`/`QUARANTINE_CANDIDATE`, never upgrade. The word
"deprecated" is not applied to any internal orphan.

**7.4 Ruff corroboration (reuse, do not re-derive).** Run
`ruff check ari-core --output-format json` (optionally per-skill `src/` on
`--target`) and attach `F401`/`F841`/`F811` findings to the matching node's
`evidence`. Ruff is authoritative on unused *imports/locals*; the 053/054 graph is
authoritative on *cross-module reachability*. A bare `F401`/`F841` never by itself
promotes a node to `SAFE_DELETE_CANDIDATE` when the graph shows any inbound edge —
it is corroborating detail, not the decision.

**7.5 Allowlist / baseline.** `scripts/quality/check_dead_code.allow.yaml` freezes
the current known-orphan set keyed by stable identity (symbol qualname / module
path) with an optional justification. Allowlisted findings report as `known`,
never `new`, and never fail `--check`. Ratchet direction: entries shrink as 057
deletes reviewed candidates; the baseline never grows silently. Regenerate via
`--update-baseline` (deliberate freeze, analogous to
`report/scripts/snapshot_prompts.py`).

**7.6 Canonical flags (`009` §3 — accept all; ignore inapplicable):**

| Flag | Meaning |
|---|---|
| `--graph <file>` | Input `reference_graph.json` (default `docs/refactoring/reports/reference_graph.json`). |
| `--target <path>` | Restrict the ruff-corroboration scan (default `ari-core/ari`; repeatable for per-skill). |
| `--config <file>` | YAML config (default `scripts/quality/check_dead_code.yaml`). |
| `--output <file>` | Write `dead_code_candidates.md` (default `docs/refactoring/reports/dead_code_candidates.md`). |
| `--format markdown\|json` | `json` = 058-aggregator building block (stable schema); `markdown` = human report (default). |
| `--warning-only` | Force exit 0 regardless of findings (advisory; default posture while new). |
| `--check` | Ratchet: exit non-zero **only** for a `SAFE_DELETE_CANDIDATE` not on the allowlist (net-new dead code above budget). |
| `--base-ref <ref>` | Diff-scope the ratchet (default `origin/main`, mirroring `check_ref_coupling.py`). |
| `--update-baseline` | Regenerate `check_dead_code.allow.yaml` from the current graph. |

**7.7 Output schema.** JSON matches `009` §3:
`{ "checker": "check_dead_code", "version": 1, "graph": <path>, "commit": <sha>,
"summary": {counts per classification}, "collisions": [...],
"findings": [ {id, classification, file, symbol, loc, reachable_from: [...],
evidence: [...], rationale, allowlisted: bool} ] }`. Markdown = the ranked
`dead_code_candidates.md` table of `013` §6.2, grouped by classification,
most-confident deletions first. Exit convention: `0` clean or `--warning-only`;
`1` net-new `SAFE_DELETE_CANDIDATE` above budget under `--check`; `2`
usage/environment error (missing/malformed graph, ruff not on PATH), matching
`check_doc_sources.py`'s `SystemExit(2)`.

**7.8 Determinism (`013` §6.4).** Stable node ordering (sort by `id`), no
wall-clock in row bodies (only a single top-level `generated_at`), no LLM, no
network. Two runs on the same commit + same input graph ⇒ byte-identical
`dead_code_candidates.md`.

**7.9 Rollout (warning-mode-first, `009` §6/§7).** Land advisory:
`--warning-only` default, frozen allowlist, **no** hard workflow gate. Any later CI
wiring is a separate subtask and uses `continue-on-error: true`. Internal-quality
checkers like `check_dead_code` may remain advisory indefinitely (`009` §7); the
first hard-gate candidates are the external-contract checkers, not this one.

## 8. Concrete Work Items

1. Read `docs/refactoring/013_reference_graph_and_dead_code_plan.md` §6/§7/§8.3/§9
   and `docs/refactoring/009_quality_scripts_plan.md` §3/§5.10/§8. Confirm the
   `reference_graph.json` schema (`013` §6.1) that 053/054 emit is the input
   contract. Copy the checker shape from `scripts/docs/check_doc_sources.py`.
2. Ensure `scripts/quality/` and `scripts/quality/_common.py` exist (reuse if a
   prior quality-checker subtask created them; else create minimally: JSON emitter
   matching `009` §3 schema, allowlist YAML loader, Markdown table writer,
   `--base-ref` resolver mirroring `check_ref_coupling.py`).
3. Write `scripts/check_dead_code.py`:
   - `REPO_ROOT = Path(__file__).resolve().parents[1]`; shebang; docstring citing
     `013` §7/§8.3.
   - Load + validate `reference_graph.json` (`--graph`); `SystemExit(2)` on
     missing/malformed graph or `schema_version != 1`.
   - Implement the §7 precedence classifier (Section 7.3) with the hard-downgrade
     rule; key `mcp.tool` nodes by `(skill, tool_name)` and never dedupe collisions
     (consume the `collisions[]` array into the report).
   - Run `ruff check <targets> --output-format json`; attach `F401`/`F841`/`F811`
     as node evidence; handle "ruff missing" → `SystemExit(2)`.
   - Allowlist load + `known`/`new` tagging; implement `--check`, `--warning-only`,
     `--format`, `--output`, `--base-ref`, `--update-baseline`.
   - Emit ranked `dead_code_candidates.md` (`013` §6.2) + JSON (`009` §3).
     Deterministic ordering.
4. Write `scripts/quality/check_dead_code.yaml` (roots override, classification
   config, `--check` budget, ruff targets).
5. Generate `scripts/quality/check_dead_code.allow.yaml` via `--update-baseline`
   against a real 053/054 graph; verify the four `publish/backends/*`, the
   `prompts/**/*.md`, and the 23 reviewer rubrics are **not** in the
   `SAFE_DELETE_CANDIDATE` list (they must be `DYNAMIC_REFERENCE_RISK`), and that
   `ari.schemas.load()` lands in `TEST_ONLY`.
6. Add `scripts/quality/README.md` (per-directory README convention) if not yet
   present.
7. Update `scripts/README.md` `## Contents` to list `check_dead_code.py` and the
   `quality/` subtree — or run `python scripts/readme_sync.py --write` and stage
   the result — so `readme_sync.py --check` stays green.
8. Decide the `docs/refactoring/reports/` artifact policy in coordination with
   subtask 033: gitignore the generated `reference_graph.json` /
   `dead_code_candidates.md`, or add a README-synced `## Contents`. Do not leave
   `readme-sync.yml` red.
9. Ensure the new `.py` files are **ruff-clean** (`ruff check scripts/check_dead_code.py
   scripts/quality/` → 0 findings) so the repo-wide `ruff check .` count does not
   rise above the 661 baseline.
10. Optional: add a small self-test (e.g. `ari-core/tests/test_check_dead_code.py`)
    with a synthetic minimal `reference_graph.json` fixture covering (a) precedence
    (a `PUBLIC_CONTRACT` node with no static importer stays `KEEP`), (b) the
    hard-downgrade rule, and (c) allowlist suppression under `--check`.
11. Run the Section-12 gates; confirm the baseline is unchanged and the checker
    reproduces a deterministic candidate list under `--warning-only`.

## 9. Files Expected to Change

Runtime code: **none**.

Created (dev tooling / config / docs only):
- `scripts/check_dead_code.py` — the classifier.
- `scripts/quality/check_dead_code.yaml` — classification config / `--check` budget.
- `scripts/quality/check_dead_code.allow.yaml` — frozen known-orphan baseline.
- `scripts/quality/_common.py` — shared checker infrastructure (**only if not
  already bootstrapped** by an earlier quality-checker subtask; else reused/extended).
- `scripts/quality/README.md` — per-directory README (**only if not already present**).
- *(optional)* `ari-core/tests/test_check_dead_code.py` — self-test with a synthetic
  graph fixture.

Updated (non-runtime):
- `scripts/README.md` — `## Contents` gains `check_dead_code.py` and the `quality/`
  entry (required for `readme_sync.py --check`).
- *(coordinated with subtask 033)* `.gitignore` and/or `docs/refactoring/reports/README.md`
  — to keep the generated `reference_graph.json` / `dead_code_candidates.md` from
  tripping `readme-sync.yml`.

Explicitly **not** changed:
- `ari-core/pyproject.toml` (no `[tool.ruff]`, no new dep).
- Any of `.github/workflows/{docs-change-coupling,docs-sync,pages,readme-sync,refactor-guards}.yml`.
- Any file under `ari-core/ari/`, `ari-skill-*/`, the frontend,
  `ari-core/config/`, `ari-core/ari/configs/`, or `ari-core/ari/config/`.
- The `reference_graph.json` producer (`analyze_references.py` / dynamic overlay) —
  those are subtasks 053/054.

## 10. Files / APIs That Must Not Be Broken

This subtask adds a read-only classifier over an existing JSON artifact and touches
no runtime surface, so it breaks nothing directly. It must nonetheless preserve
(and its **classification output** must respect the contract firewall of `013` §9):

- **CLI** `ari = ari.cli:app` — untouched; the checker adds no `ari` subcommand and
  is invoked as `python scripts/check_dead_code.py`. CLI command names/flags/`ARI_*`
  env side-effects are `PUBLIC_CONTRACT` and must never be classified deletable.
- **`ari.public.*`** (148 LOC frozen surface: `claim_gate`, `config_schema`,
  `container`, `cost_tracker`, `llm`, `paths`, `run_env`, `verified_context`) — not
  imported, not modified; classified `PUBLIC_CONTRACT`. The empty `ari/__init__.py`
  and docstring-only `ari/public/__init__.py` are structural shells, not dead.
- **MCP tool contracts** (14 `ari-skill-*/src/server.py`; `ari-core/ari/mcp/client.py`
  `call_tool`) — the checker *reads* graph nodes for these; every `mcp.tool` handler
  + `inputSchema` + `{"result"|"error"}` envelope + `mcp__<skill>__<tool>` name is
  `PUBLIC_CONTRACT`, never deletable. Handle the flat-namespace collision report
  without dropping either handler.
- **Dashboard API** (`ari/viz/routes.py` + 14 `api_*.py` + `websocket.py`, consumed
  by `frontend/src/services/api.ts`) — `PUBLIC_CONTRACT`; every route reachable via
  a `cross_lang.http` edge stays `KEEP`.
- **`ari-skill-*` → `ari-core` stable interfaces** (incl. the sanctioned
  `ari-core → ari_skill_memory` edge) — preserved; not classified deletable.
- **Checkpoint / output / config file formats** — untouched; the checker writes
  only its own report. Nodes touching `ari/checkpoint.py` / `ari/migrations/` are at
  most `QUARANTINE_CANDIDATE`, never `SAFE_DELETE_CANDIDATE`.
- **Scripts invoked by `.github/workflows/`** — the `readme_sync.py --check` gate
  (`readme-sync.yml`) must stay green, which is why `scripts/README.md` (and the
  reports-dir policy) are updated in the same change. The other four workflows are
  not modified.
- **`scripts/git-hooks/pre-commit`** — runs `readme_sync.py --write` (non-blocking);
  the new files must be README-sync-consistent so the hook reports no lingering
  `— TODO`.

## 11. Compatibility Constraints

- **No `[tool.ruff]` added to `ari-core/pyproject.toml`.** `F401`/`F841`/`F811` are
  ruff-default `F`-family rules already active; the checker runs
  `ruff check ... --output-format json` per-invocation, so the repo-wide
  `ruff check .` baseline (661 findings, 341 `F401`) is unchanged for everyone else.
- **No new dependency.** `vulture`/`radon` are not installed and are not added; the
  checker depends only on the ruff CLI (present) + stdlib + PyYAML
  (`pyyaml>=6.0`, already a core dep). Adding `vulture` is a separate reviewed
  change to `[project.optional-dependencies].dev`, not part of this subtask.
- **Input-schema coupling to 053/054.** The checker's contract is the
  `reference_graph.json` schema of `013` §6.1 (`schema_version == 1`). It must
  validate that schema and fail `2` on drift, so a change to 053/054's output is a
  loud error, not a silent misclassification. Keep the parser tolerant of extra
  keys (forward-compatible) but strict on required ones.
- **Determinism (P2 + `013` §6.4).** No LLM, no network; stable `id` sort; single
  top-level timestamp. Same commit + graph ⇒ byte-identical report. This matches
  the `scripts/docs/` convention (PyYAML the only non-stdlib dep) and the "no LLM
  calls" contract of deterministic tooling like `ari-skill-memory` and
  `scripts/readme_sync.py`.
- **README-sync parity.** Adding `scripts/check_dead_code.py` (and any new
  `scripts/quality/*`) obliges updating `scripts/README.md`; generated reports under
  `docs/refactoring/reports/` need the gitignore/README decision of subtask 033.
  Otherwise `readme_sync.py --check` (and `readme-sync.yml`) fails.
- **Warning-mode-first.** Default `--warning-only`; ship a frozen allowlist; do
  **not** wire `--check` into any workflow in this subtask. Promotion to a hard gate
  is a later, explicit subtask (`009` §6/§7 — and internal-quality checkers may stay
  advisory indefinitely).
- **`ruff --output-format json` shape** is a ruff-version detail (0.15.2); parse
  tolerantly and fail `2` only if ruff itself is unavailable, not merely because
  there are zero `F401`/`F841` findings.
- **Contract-firewall precedence.** The §7 ordering (PUBLIC_CONTRACT and
  DYNAMIC_REFERENCE_RISK outrank SAFE_DELETE_CANDIDATE) is a compatibility
  constraint, not a style choice: it is what prevents 055 from ever proposing a
  contract-surface node for the 057 deletion step.

## 12. Tests to Run

- `python -m compileall .` — confirms the new `.py` files (and nothing else)
  compile; no runtime `.py` was accidentally touched.
- `pytest -q` — full suite must pass unchanged from baseline (heaviest:
  `ari-core/tests/test_server.py` 1844, `test_gui_errors.py` 1650,
  `test_workflow_contract.py` 1606, `test_wizard.py` 1133). If the optional
  self-test was added, it runs here.
- `ruff check .` — baseline is **661 findings**; must not increase. The new
  `scripts/check_dead_code.py` and any new `scripts/quality/*.py` must themselves be
  ruff-clean (`ruff check scripts/check_dead_code.py scripts/quality/`).
- `python scripts/readme_sync.py --check` — must exit 0 after `scripts/README.md`
  (and the reports-dir policy) are updated (this is the gate `readme-sync.yml` runs).
- **Checker self-run (smoke), against a real or fixture `reference_graph.json`:**
  - `python scripts/check_dead_code.py --warning-only` → exit 0; emits a ranked
    `dead_code_candidates.md`.
  - `python scripts/check_dead_code.py --format json` → valid JSON per the §7.7 /
    `009` §3 schema.
  - Run twice on the same graph → byte-identical `dead_code_candidates.md`
    (determinism, `013` §6.4).
  - `python scripts/check_dead_code.py --check` on the allowlisted baseline → exit 0;
    a synthetic net-new orphan node in the fixture graph → exit 1.
  - Missing `--graph` file → `SystemExit(2)` (environment error, not silent regen).
- **Frontend (`npm test` / `npm run build` under `ari-core/ari/viz/frontend/`) is
  NOT applicable** — this subtask adds a Python classifier and does not touch
  frontend code or require a build (`npm`, not `pnpm`, in this env). Frontend
  reachability is supplied by the 053/054 graph, not built here.

If `compileall` / `pytest` / `ruff check .` regress beyond the 661 baseline, the
session touched something outside the intended file set and must revert.

## 13. Acceptance Criteria

1. `scripts/check_dead_code.py` exists, is `#!/usr/bin/env python3`, uses
   `REPO_ROOT = Path(__file__).resolve().parents[1]`, depends only on stdlib +
   PyYAML + the ruff CLI, and its docstring cites
   `docs/refactoring/013_reference_graph_and_dead_code_plan.md` §7/§8.3.
2. `scripts/quality/check_dead_code.yaml` and `scripts/quality/check_dead_code.allow.yaml`
   exist; `scripts/quality/_common.py` + `scripts/quality/README.md` exist (reused
   or created).
3. The checker consumes `reference_graph.json` (validates `schema_version == 1`) and
   exits `2` on a missing/malformed graph — it does **not** build the graph itself.
4. The §7 precedence classifier assigns exactly one label per node, with the hard
   downgrade rule (ambiguity → `REVIEW_REQUIRED`, never up to
   `SAFE_DELETE_CANDIDATE`). Verified expectations hold: the four
   `ari/publish/backends/*`, the `ari/prompts/**/*.md`, and the 23
   `ari-core/config/reviewer_rubrics/*.yaml` land in `DYNAMIC_REFERENCE_RISK`;
   `ari.schemas.load()` lands in `TEST_ONLY`; `ari/__init__.py` and
   `ari/public/__init__.py` are **not** dead; MCP handlers + `viz` routes are
   `PUBLIC_CONTRACT`.
5. Ruff `F401`/`F841`/`F811` findings attach as corroborating evidence but never by
   themselves promote a node with an inbound graph edge to `SAFE_DELETE_CANDIDATE`.
6. All of `--graph`, `--target`, `--config`, `--output`, `--format markdown|json`,
   `--warning-only`, `--check`, `--base-ref`, `--update-baseline` are accepted; exit
   convention is `0`/`1`/`2` per Section 7.7.
7. `--check` on the allowlisted baseline exits `0`; a synthetic net-new
   `SAFE_DELETE_CANDIDATE` makes it exit `1`.
8. Two runs on the same commit + graph produce a **byte-identical**
   `dead_code_candidates.md` (`013` §6.4).
9. `python scripts/readme_sync.py --check` passes (README + reports-dir policy
   updated).
10. `python -m compileall .`, `pytest -q`, and `ruff check .` pass with the `ruff`
    count **≤ 661** (no new lint debt from the added scripts).
11. No runtime code, config, prompt, workflow, frontend, or directory under
    `ari-core/ari/` / `ari-skill-*/` / the frontend was created, edited, moved,
    renamed, or deleted. No code was deleted or quarantined (those are 056/057). The
    word "deprecated" is not applied to any internal code.

## 14. Rollback Plan

Trivial and complete — the subtask's artifacts are new tooling/config files plus one
README edit (and an optional reports-dir gitignore), none imported by runtime code:

- `git rm scripts/check_dead_code.py`,
  `git rm scripts/quality/check_dead_code.yaml scripts/quality/check_dead_code.allow.yaml`
  (and `_common.py`/`README.md` only if this subtask created them, not if reused).
- `git checkout -- scripts/README.md` to restore the `## Contents` block (or re-run
  `python scripts/readme_sync.py --write`).
- Revert the subtask-033-coordinated `.gitignore` / `docs/refactoring/reports/README.md`
  change if made.
- If the optional self-test was added, `git rm ari-core/tests/test_check_dead_code.py`.

No runtime state, no migrations, no config-format change, no schema change, no
workflow change, **no deletions of production code** → nothing else to undo.
Rollback cannot affect the running system, checkpoints, MCP tools, the dashboard, or
any preserved contract.

## 15. Dependencies

Per the program dependency graph (chain `053 -> 054 -> 055 -> 056 -> 057 -> 058`)
and the parent design `013` §10 (which lists 055's "Depends on" as **053, 054**):

- **Predecessors (hard, incoming edges): `053` and `054`.**
  - `053 -> 054 -> 055`: subtask 055 depends transitively on **053**
    (`analyze_references.py`, static reference graph + root seeding, emits
    `reference_graph.json`, `013` §8.1) and directly on **054** (dynamic-edge
    overlay: publish backends, `_COMPOSITES`, prompt/rubric/schema paths, MCP tools,
    `ARI_*` env pairs, cross-lang HTTP + collision report, `013` §8.2). 055 cannot
    run before both complete, because it *consumes* their `reference_graph.json`
    (with dynamic edges already injected). Without 054's overlay, the four
    `publish/backends/*` and every prompt/rubric would be false orphans.
  - 054 also creates/uses `scripts/quality/`; 055 reuses
    `scripts/quality/_common.py` (JSON emitter, allowlist loader, Markdown writer,
    `--base-ref` resolver) rather than duplicating it (`009` §8).
- **Successor (outgoing edge in the given chain): `055 -> 056`.** Subtask 056
  (quarantine mechanism / `MOVE_TO_LEGACY`) depends on 055's `QUARANTINE_CANDIDATE`
  labels.
- **Further consumers (per `013` §10 DAG, consistent with the chain):** subtask
  **057** (the only deletion step) consumes 055's `SAFE_DELETE_CANDIDATE` list (and
  056's quarantine), and subtask **058** (`generate_quality_report.py`) folds 055's
  per-classification counts into the repo quality report (`013` §6.3). These are
  downstream of 055 in the chain; 055 itself performs neither quarantine nor
  deletion.
- **Gate context.** The inventory/measurement subtasks that must precede any runtime
  code change are `001, 002, 020, 036, 045, 053, 059, 060, 067`. **053 is on that
  list**, and 055 sits downstream of 053/054. 055 is itself **not** a runtime code
  change (it adds tooling and emits a report), so it neither blocks nor is blocked by
  the runtime-editing cohort beyond its 053/054 predecessors. The first runtime edits
  in this stream are 056 (relocate) and 057 (delete), which come **after** 055.
- **Cross-doc numbering note (non-blocking).** `009` §10 also numbers
  `check_dead_code.py` as **055** and its reference-graph feeder
  `analyze_references.py` as **043**; this document follows the authoritative chain
  in the provided dependency graph and `013` §10 (`053 -> 054 -> 055`), where the
  feeder is 053 and its dynamic overlay is 054.

This is consistent with the provided graph chain `053 -> 054 -> 055 -> 056 -> 057
-> 058` and the inventory-gate list.

## 16. Risk Level

- **Risk: Low.**
- **Changes runtime code? No.** The deliverables are dev tooling
  (`scripts/check_dead_code.py`, `scripts/quality/check_dead_code.{yaml,allow.yaml}`,
  optionally `scripts/quality/_common.py`/`README.md`), a documentation README
  update (`scripts/README.md`, coordinated `docs/refactoring/reports/` policy), and
  an optional test. None is imported by the `ari` package, any `ari-skill-*` server,
  the CLI, the dashboard, or any of the 5 workflows. The checker is a read-only
  classifier over a JSON artifact and modifies no runtime code, imports, prompts,
  configs, workflows, frontend, or directory names. It deletes and quarantines
  nothing (those are subtasks 057/056).
- Residual risks: (a) **false `SAFE_DELETE_CANDIDATE`** if 054's dynamic overlay is
  incomplete — mitigated by the hard-downgrade rule (ambiguity → `REVIEW_REQUIRED`),
  the schema-validation `exit 2` on a stale/partial graph, and the mandatory human
  review before any 057 deletion; (b) `ruff --output-format json` shape differing
  across ruff versions — mitigated by tolerant parsing and the `exit 2` env-error
  path; (c) accidentally raising the `ruff check .` baseline by shipping a non-clean
  script — mitigated by the Section-12 ruff gate; (d) forgetting the
  `scripts/README.md` / reports-dir README update and failing `readme-sync.yml` —
  mitigated by the explicit `readme_sync --check` gate in Section 12. All are
  contained to tooling and caught by the standard gates.

## 17. Notes for Implementer

- **You are a classifier, not a graph builder.** Do not re-implement the AST walk or
  dynamic-seam scan — that is 053/054. Read `reference_graph.json`, validate its
  `013` §6.1 schema, and classify. If the graph is missing/malformed, `exit 2`;
  never silently regenerate or fall back to a naive import scan (that path produces
  the exact false positives `013` §2 warns against).
- **Precedence is the safety property.** Implement `013` §7 top-down, first-match-
  wins, and enforce the hard downgrade: on any doubt, `REVIEW_REQUIRED` /
  `QUARANTINE_CANDIDATE`, **never** up to `SAFE_DELETE_CANDIDATE`. Add a unit test
  that a `PUBLIC_CONTRACT` node with zero static importers still classifies `KEEP`.
- **Verify the known-live examples before trusting your output.** After the first
  real run, confirm the four `ari/publish/backends/*` modules, every
  `ari/prompts/**/*.md`, and the 23 `ari-core/config/reviewer_rubrics/*.yaml` are
  `DYNAMIC_REFERENCE_RISK` (not orphans), `ari.schemas.load()` is `TEST_ONLY`, and
  `ari/__init__.py` / `ari/public/__init__.py` are not flagged. If any of these
  shows up as `SAFE_DELETE_CANDIDATE`, the graph or your precedence is wrong — stop
  and fix, do not allowlist around it.
- **MCP collisions: key by `(skill, tool_name)`.** The flat namespace
  (`MCPClient._tool_registry`, `ari-core/ari/mcp/client.py:283`) can clobber; never
  dedupe two distinct handlers into one node, and surface 054's `collisions[]` in
  the report so the hazard is visible.
- **Ruff corroborates, it does not decide.** Attach `F401` (341), `F841` (39),
  `F811` (8) as evidence, but a node with any inbound graph edge is not
  `SAFE_DELETE_CANDIDATE` no matter what ruff says. `vulture`/`radon` are absent —
  do not assume them.
- **Determinism is a contract (`013` §6.4).** Sort by `id`, keep one top-level
  timestamp, no LLM, no network. CI/reviewers will diff `dead_code_candidates.md`
  across runs; a non-deterministic report is a bug.
- **Reuse `scripts/quality/_common.py`.** It should already exist from an earlier
  quality-checker subtask (`009` §8); reuse the JSON emitter / allowlist loader /
  Markdown writer / `--base-ref` resolver rather than copy-pasting. If you must
  extend it, keep it generic for siblings.
- **Keep the README + reports-dir gates green in the same commit.** After adding
  files, run `python scripts/readme_sync.py --write`, stage `scripts/README.md` (and
  `scripts/quality/README.md`), settle the `docs/refactoring/reports/` artifact
  policy with subtask 033 (gitignore vs README-sync), then verify `--check` exits 0.
- **Warning-mode-first, no CI wiring here.** Ship `--warning-only` default and a
  frozen allowlist. Do **not** edit any of the 5 workflows; internal-quality
  checkers like this one may stay advisory indefinitely (`009` §7). Promotion to a
  hard gate is a separate, explicitly-scoped subtask.
- **Match the house style.** Mirror `scripts/docs/check_doc_sources.py`: shebang,
  docstring citing the design doc, `argparse`, a small dataclass with `as_dict()`,
  `SystemExit(2)` on environment error, `--format json` as the aggregator building
  block. Consistency with the existing checker family is a review criterion.

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **055** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
