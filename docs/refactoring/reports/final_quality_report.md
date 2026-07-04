# Final Quality Report — ARI Refactoring Program

> **⚠ Superseded in part by the 2026-07-04 DONE-verification audit.** After this
> report was generated, a 73-way adversarial audit re-checked every subtask against
> primary sources and found **1 NOT_DONE (040) + 18 CONCERN**. All were then fixed
> or documented: 040 completed (`49754b7`), four `scripts/tests` HEAD failures
> repaired (031/054/073, `267c53f`), nine doc concerns closed (`9a40eb4`), and 063
> reclassified DONE→DONE\*. The authoritative post-audit roster is the **Completion
> Status table in `docs/refactoring/007_subtask_index.md`** (59 DONE + 14 DONE\*,
> 0 BLOCKED) and the audit entry in `orchestration_status.md`. Figures below that
> predate the audit (e.g. the DONE/DONE\* split, 040's status) are point-in-time.

> **Artifact of subtask 019** (`docs/refactoring/subtasks/019_final_quality_report.md`),
> the terminal deliverable of the 73-subtask refactoring program.
> **REPORT ONLY — no runtime code, prompt, config, workflow, or frontend was
> modified.** This document and its machine sibling
> `final_quality_report.json` are the only files produced. Every number below was
> captured from a command actually run at generation time (cited inline) or cited
> from the orchestrator ledger where noted; nothing is estimated or fabricated.
> Metrics with no tool are written "newly measured" / "unmeasured", never guessed.

## 0. Provenance (determinism stamp)

| Field | Value |
|---|---|
| Repo root | `/home/t-kotama/workplace/ARI` |
| Branch | `whole_refactoring` |
| Git SHA (`git rev-parse HEAD`) | `2927b8ff678c352ce7f386dd0705a1175a12fb17` |
| ari-core version | `0.9.0` |
| Ruff version | `0.15.2` |
| Python | `3.13.2` |
| Generated (UTC) | `2026-07-03` (aggregator JSON stamp `2026-07-03T10:13:11Z`) |
| Working tree at generation | clean except this report pair (verified `git status --porcelain`) |

### 0.1 Exact commands run for this report (reproducible; P2)

| # | Command | Purpose |
|---|---|---|
| C1 | `python scripts/generate_quality_report.py --run-checkers --format json --output docs/refactoring/reports/final_quality_report.json` | Live aggregate roll-up (the JSON deliverable) |
| C2 | `python scripts/generate_quality_report.py --run-checkers --format markdown` | Human roll-up (embedded in §4/§5) |
| C3 | `ruff check ari-core --statistics` | Final ari-core lint census |
| C4 | `ruff check . --statistics` | Final whole-tree lint census |
| C5 | `python -m compileall -q ari-core scripts` | Byte-compile smoke gate |
| C6 | `git ls-files … \| xargs wc -l` | Final LOC / large-file census |

The aggregator (subtask **031**, `scripts/generate_quality_report.py`) invoked
**7** checkers as subprocesses with `--format json`; all 7 returned status `ok`.
Numbering note (019 §2): the authoritative `007_subtask_index.md` maps
`generate_quality_report.py` → **031** (not 009 §10's "058"); the script run is the
one at `scripts/generate_quality_report.py`. The `dead_code_baseline.json` and
`reference_graph.{json,md}` consumed here are the **committed** 054/058 artifacts —
019 §8 does not call for regenerating them, so they were left untouched (the
dead-code delta below confirms the live tree still matches that committed snapshot).

## 1. Executive verdict

**PASS (advisory).** Every external-contract checker is green and reports **zero
net-new findings** against its frozen baseline:

- `check_public_api_contracts` → **0 breaks / 0 regressions** (`ari.public.*` intact).
- `check_import_boundaries` → **9 findings, all allowlisted, 0 net-new** (the known
  skill→core edges; no new boundary violation introduced).
- `check_dead_code` → **SAFE_DELETE_CANDIDATE = 0**, delta vs committed baseline = 0
  across all buckets.
- Aggregate: **852 findings, 0 net-new vs baseline** (`totals.new_vs_baseline = 0`).
- `ruff check ari-core` ratcheted **661 → 634** (monotone decrease, policy honored).
- `compileall` exit 0; test suite **2656 passed / 2 xfailed / 0 failed** (cited from
  the orchestrator ledger — not re-run here, see §3.5).

One WARN caveat (not a contract break): `check_viz_api_schema` is **stale** against
the subtask-063 frontend split (§5, §7). The dashboard wire contract itself is
preserved and guarded by the frozen `test_contract_snapshots`.

## 2. Program completion roster (from `orchestration_status.md` ledger)

All **73** subtasks (001–073) are resolved. Counts grepped from the ledger table:

| Status | Count | IDs |
|---|---:|---|
| **DONE** (full scope) | **59** | all not listed below |
| **DONE\*** (partial-scope / deferred residue) | **13** | 003, 005, 010, 011, 015, 016, 021, 023, 039, 062, 064, 070, 072 |
| &nbsp;&nbsp;↳ of which **no-op** (verified nothing to change) | 3 | 015, 016, 039 |
| **TODO** | **1** | 019 (this report — the last subtask) |
| **BLOCKED** | **0** | — |

Additionally, **6** verify-only design/policy subtasks are DONE with a pre-existing
deliverable (commit `93d9662*` in the ledger, no new artifact this run): 004, 007,
037, 046, 061, 068. These are full DONE, not partial.

The **9 inventory gates** (001, 002, 020, 036, 045, 053, 059, 060, 067) all landed
before any runtime change (hard gate OPEN, ledger §"Hard gate"). The **27
runtime-code-change subtasks** each landed as a scoped, revertable commit.

### 2.1 What DONE\* means per subtask (deferred residue carried to §8 backlog)

| ID | Scope landed | Residue deferred (→ §8) |
|---|---|---|
| 003 | config-trio consolidation shim | Phase-B data-move of the `config/`/`configs/` split |
| 005 | run-dir layout + back-compat reader | full `runs/<id>/…` bucketed-write flip |
| 010 | artifact/checkpoint/trace store wrap | 4 skill→core boundary burn-down (still allowlisted) |
| 011 | BFTS strategy / ReAct split | `AgentLoop.run` decomposition (blocked by frozen tests) |
| 015 | **no-op** — subsumed by 021/023/024/062 | route-registry dispatch (blocked by `test_contract_snapshots`) |
| 016 | **no-op** — every 002 dup owned elsewhere | `cli/lineage.py` relocation (blocked by `test_core_viz_direction`) |
| 021 | `.env`/launch-service extraction | `{ok}`/`{error}`+`_status` envelope unification |
| 023 | file-I/O service extraction | (folded into 015 route-registry item) |
| 039 | **no-op** — agent/BFTS prompts already externalized | speculative inner-scaffold extraction (needs new snapshots) |
| 062 | backend routes→services | route-registry + envelope (co-baseline with 063 FE) |
| 064 | FE state/component boundaries | remaining >800-LOC god-components (StepResources, WorkflowPage) |
| 070 | settings-panel disclosure | Settings tabs deferred; plaintext-secret persistence → 071 |
| 072 | empty/loading/error states | — |

## 3. Baseline → final delta table

Baseline column = the frozen 2026-07-01 measurement (subtask 001,
`001_complexity_baseline.md`). Final column = live commands C3–C6 above.

### 3.1 Ruff — `ari-core` cohort (`ruff check ari-core --statistics`, C3)

| Rule | Baseline (2026-07-01) | Final (2026-07-03) | Δ |
|---|---:|---:|---:|
| **Total** | **661** | **634** | **−27** |
| `F401` unused-import | 341 | 317 | −24 |
| `E402` import-not-at-top | 135 | 133 | −2 |
| `E702` multi-stmt-semicolon | 54 | 54 | 0 |
| `F841` unused-variable | 39 | 39 | 0 |
| `E701` multi-stmt-colon | 37 | 36 | −1 |
| `F541` f-string-no-placeholder | 28 | 28 | 0 |
| `E741` ambiguous-name | 11 | 11 | 0 |
| `F811` redefined-while-unused | 8 | 8 | 0 |
| `E401` multi-imports-one-line | 7 | 7 | 0 |
| `E731` lambda-assignment | 1 | 1 | 0 |
| (auto-fixable) | 358 | 334 | −24 |

Ratchet policy honored: the number only decreased and no new rule class appeared.
No `ruff --fix` was run (still deferred, per plan). Orchestrator baseline note: 661
→ 660 after subtask 003 removed one dead import; the ratchet target ≤634 is now met.

### 3.2 Ruff — whole tree (`ruff check . --statistics`, C4)

| Metric | Baseline | Final | Δ |
|---|---:|---:|---:|
| Total (distinct cohort: +skills/+scripts/+report) | 1199 | 1172 | −27 |
| Auto-fixable | 544 | 520 | −24 |

This cohort differs from §3.1 (it lints `ari-skill-*`, `scripts/`, `report/`); the
1172 vs 634 gap is a cohort difference, **not** a regression (per 001 §3.2).

### 3.3 LOC census (C6, git-tracked, tests excluded)

| Cohort | Baseline | Final | Δ | Reading |
|---|---:|---:|---:|---|
| core-prod files (`ari-core/ari/**/*.py`) | 139 | 158 | +19 | new abstraction modules |
| core-prod LOC | 30,277 | 32,983 | +2,706 | +9% total |

Total LOC **rose** because decomposition adds abstraction modules (protocols,
adapters, service extractions, DTOs, path resolver, prompt loader, split components)
— the program's goal was to shrink **god-files**, not total LOC. §3.4 shows the
per-file effect.

### 3.4 Large-file census (the actual refactoring target)

Production-Python `>1200` LOC — count unchanged (5 → 5), but the two decomposed core
files fell out of the top band; the top skills servers are Phase-9/10 KEEP surfaces:

| File | Baseline | Final | Δ | Note |
|---|---:|---:|---:|---|
| `ari-skill-paper/src/server.py` | 2956 | 2934 | −22 | skill KEEP surface |
| `ari-skill-transform/src/server.py` | 2465 | 2465 | 0 | skill KEEP surface |
| `ari-skill-paper-re/src/_paperbench_bridge.py` | 2376 | 2376 | 0 | vendored KEEP_INLINE |
| `ari-core/ari/agent/loop.py` | 1630 | 1646 | +16 | **decomposition deferred (011)** |
| `ari-skill-paper-re/src/server.py` | 1395 | 1395 | 0 | — |

Biggest single-file wins (now well under the 1200 split line):

| File | Baseline | Final | Δ | Owning subtask |
|---|---:|---:|---:|---|
| `ari-core/ari/pipeline/orchestrator.py` | 913 | **153** | **−760** | 012 WorkflowDriver |
| `ari-core/ari/viz/routes.py` | 1197 | **760** | **−437** | 021/023/062 service extraction |
| `ari-core/ari/orchestrator/bfts.py` | 845 | **701** | −144 | 007-1 BFTSPromptBuilder |

Frontend `>800` LOC — offenders **5 → 3**:

| File | Baseline | Final | Δ | Note |
|---|---:|---:|---:|---|
| `Results/resultSections.tsx` | 1590 | **21** | −1569 | barrel; 6 render-fns → `Results/sections/*.tsx` (012-1/064) |
| `services/api.ts` | 863 | **32** | −831 | barrel; 17 endpoint modules → `services/api/*.ts` (063) |
| `Settings/SettingsPage.tsx` | 1049 | **506** | −543 | disclosure decomposition (070) |
| `Wizard/StepResources.tsx` | 1160 | 1168 | +8 | **still >800 — deferred (064)** |
| `Workflow/WorkflowPage.tsx` | 964 | 967 | +3 | **still >800 — deferred (064)** |
| `Results/sections/OrsChainSection.tsx` | — | 925 | new | split product of resultSections |

### 3.5 Tests (cited — NOT re-run by 019)

| Metric | Baseline (001) | Final (ledger) | Δ |
|---|---:|---:|---:|
| pytest `ari-core/tests` | 2413 passed / 16 skipped | **2656 passed / 2 xfailed / 0 failed** | +243 passed |

The final figure is cited from `orchestration_status.md` (baseline line 17; final
lines 304 & 317 — "Full suite green after fix: 2656 passed / 2 xfailed / 0 failed").
Per the 019 run directive the full suite was **not** re-executed here; `compileall`
(the report-bearing half) was run live and passed (C5, exit 0).

### 3.6 Cyclomatic complexity (newly measured)

| Metric | Baseline | Final |
|---|---|---|
| Engine | none (`radon` absent, no `C901`) | ruff `C901`, `max-complexity=15` (subtask 025) |
| Functions over max | unmeasured (definitionally 0) | **38** flagged (all allowlisted, 0 net-new) |
| Worst offender | — | `agent/loop.py::run` **CC 168** (deferred, allowlisted) |

Complexity was an unmeasured baseline of zero; subtask 025 established the
measurement. The 38 over-threshold functions are all pre-existing debt (allowlisted);
`run` at CC 168 is the AgentLoop.run decomposition that 011 deferred (§8).

### 3.7 Dead code (`check_dead_code`, via aggregator; committed 054/058 baseline)

| Classification | Count | Δ vs committed baseline |
|---|---:|---:|
| **SAFE_DELETE_CANDIDATE** | **0** | +0 |
| QUARANTINE_CANDIDATE | 0 | +0 |
| REVIEW_REQUIRED (under-traced seam) | 345 | +0 |
| PUBLIC_CONTRACT | 192 | +0 |
| DYNAMIC_REFERENCE_RISK | 125 | +0 |
| TEST_ONLY | 4 | +0 |
| LIVE (internal, not a candidate) | 1324 | — |
| total nodes | 1990 | — |

`SAFE_DELETE_CANDIDATE = 0` (the 013 §7 hard-downgrade firewall over the sparse 054
graph) means subtask **057** correctly deleted **nothing** — a documented no-op. The
all-zero delta confirms the live tree still matches the committed `dead_code_baseline.json`.

## 4. Aggregate checker roll-up (live, command C1/C2)

| Checker | Path | Status | Findings | Allowlisted | Net-new |
|---|---|---|---:|---:|---:|
| `check_complexity` | `scripts/check_complexity.py` | ok | 62 | 55 | 0 |
| `check_import_boundaries` | `scripts/check_import_boundaries.py` | ok | 9 | 9 | 0 |
| `check_public_api_contracts` | `scripts/check_public_api_contracts.py` | ok | 0 | 0 | 0 |
| `check_viz_api_schema` | `scripts/check_viz_api_schema.py` | ok | 98 | 20 | 0 |
| `check_prompts` | `scripts/check_prompts.py` | ok | 17 | 17 | 0 |
| `check_dead_code` | `scripts/check_dead_code.py` | ok | 666 | 0 | 0 |
| `check_directory_policy` | `scripts/check_directory_policy.py` | ok | 0 | 0 | 0 |
| **Totals** | — | **7 ok / 0 unavailable** | **852** | — | **0** |

`check_prompts` verdict split: EXTRACT_TEMPLATE 9, REVIEW_REQUIRED 7, MERGE_DUPLICATE
1 — all allowlisted inventory (snapshots deferred to Gate 10). `check_directory_policy`
0 findings confirms the config trio is correctly separated and **no `sonfigs/`
directory exists** (it never did — the token is an upstream typo).

Two configured checkers are **not** wired into the aggregator config and so are not
in the 7 above (they exist under `scripts/` and were run by their own subtasks):
`check_docs_source_sync.py` (027) and `check_dashboard_ux.py` (073, React i18n
parity). Their absence from the roll-up is a config scope choice, not a failure.

## 5. Per-area breakdown (LOC × findings, live)

Largest finding concentrations track the known hotspots. Full table in
`final_quality_report.json` (`areas[]`); highlights:

| Area | LOC | Findings |
|---|---:|---:|
| `ari-core/ari/viz` | 8532 | 182 |
| `ari-skill-paper-re/src` | 5843 | 108 |
| `ari-skill-memory/src` | 2876 | 73 |
| `ari-skill-paper/src` | 4256 | 62 |
| `ari-skill-idea/src` | 1916 | 46 |
| `ari-skill-transform/src` | 3180 | 43 |
| `ari-core/ari/public` | 148 | 17 |
| `ari-core/ari/protocols` | 410 | 0 |

`ari-core/ari/public` stays a thin **148 LOC** (unchanged from baseline — the frozen
contract layer did not grow real logic). `viz` remains the densest core area but its
worst file (`routes.py`) fell 1197 → 760 (§3.4).

## 6. Contract-certification matrix

One row per preserved contract (019 §10). Source = the checker whose JSON certifies it.

| Contract | Source checker / evidence | Status |
|---|---|---|
| CLI `ari` (command tree, options, env side-effects) | `snapshot_contracts.py` fixtures + suite (2656 passed) | **PASS** |
| `ari.public.*` (8 modules, 148 LOC) | `check_public_api_contracts` → 0 breaks/0 regressions | **PASS** |
| 14 `ari-skill-*` MCP tool contracts + `mcp__<skill>__<tool>` naming | contract-snapshot fixtures (034) + suite green | **PASS** |
| `ari-skill-* → ari.public` import boundary | `check_import_boundaries` → 9 known, 0 net-new | **PASS (known debt)** |
| core → `ari_skill_memory` sanctioned edge | `check_import_boundaries` (allowlisted exception) | **PASS** |
| Dashboard REST/WS API ↔ `services/api.ts` | `check_viz_api_schema` → **checker stale post-063** | **WARN — see §7** |
| Checkpoint / output / config file formats | `check_directory_policy` 0 + `test_contract_snapshots` green | **PASS** |
| Config trio separated; **no `sonfigs/`** | `check_directory_policy` → 0 findings | **PASS** |
| Prompt templates (`prompts/**/*.md`) byte-integrity | `check_prompts` (Gate 10 snapshots) + suite green | **PASS** |
| README / docs usage; scripts called by workflows | untouched by 019; `check_docs_source_sync` (run separately) | **not re-checked here** |

No contract is falsely marked PASS; the one WARN and the one "not re-checked" row are
explicit.

## 7. Open findings, allowlist coverage & the viz-schema caveat

- **Allowlist coverage:** of 852 aggregate findings, **0 are net-new** — every finding
  is either pre-existing debt on an allowlisted identity or a report-only inventory
  row. The refactoring introduced **no new** lint/complexity/boundary/dead-code
  regression above the frozen baselines.
- **`check_viz_api_schema` staleness (WARN, not a break):** the checker's `client_file`
  is hard-pinned to `ari-core/ari/viz/frontend/src/services/api.ts`, which subtask
  **063** reduced from 863 LOC to a **32-line barrel** that re-exports 17 modules under
  `services/api/*.ts`. The checker therefore parses the barrel, finds **0 client call
  sites** (`matched: 0`, `client_only: 0`), and reports all **98** routes as
  "server-only". This is a **checker-staleness artifact of the 063 split, not 98 dead
  endpoints** — the dashboard wire contract is preserved (063 kept endpoint paths +
  both error regimes) and guarded by the frozen `test_contract_snapshots` viz-route
  literals. Fix belongs to a follow-up that repoints `check_viz_api_schema` at the
  `services/api/` directory (same class of trunk-staleness the task flags for
  `check_docs_source_sync` on refactored sources). Tracked in §8.

## 8. Go-forward backlog (open REVIEW_REQUIRED / deferred items)

Carried from the ledger's "Blocked / Human-decision notes" and the DONE\* residue.
None blocks program closure; each is a scoped follow-up.

| # | Item | Owner / trigger to unblock |
|---|---|---|
| B1 | **Route-registry dispatch** for `viz/routes.py` (`if/elif` → table) | blocked by `test_contract_snapshots` pinning `self.path` literals — must re-baseline snapshots + FE envelope together (015/062) |
| B2 | **`{ok}`/`{error}` + `_status` envelope unification** | needs coordinated backend+`services/api/` FE change (021/062/063) |
| B3 | **`AgentLoop.run` decomposition** (CC 168, loop.py 1646) | blocked by frozen agent-loop tests / monkeypatch surfaces (011) |
| B4 | **Config Phase-B data-move** (`config/` vs `configs/` physical split) | shim landed (003); data relocation deferred |
| B5 | **`runs/<id>/…` bucketed-write flip** | back-compat reader landed (005); write-path flip deferred |
| B6 | **`check_viz_api_schema` trunk-staleness** (repoint at `services/api/`) | §7 — same class as `check_docs_source_sync` on refactored sources |
| B7 | **`check_docs_source_sync` staleness on refactored sources** | re-verify `sources:` front-matter after Phase 3–5 file moves (027) |
| B8 | **`publish.schema.json:51` `"s3"` enum vs no `s3` backend** | enum-vs-impl drift; correctly excluded from live-by-string allowlist (014) |
| B9 | **`read_file` MCP tool-name collision** (coding + orchestrator, last-skill-wins) | flat `_tool_registry` clobber; REVIEW_REQUIRED (010/014) |
| B10 | **4 skill→core boundary violations** (idea→lineage, paper-re→clone, transform→orchestrator+publish) | allowlisted; burn-down deferred (010-4) |
| B11 | **`cli/lineage.py` → `orchestrator/lineage_actions.py` relocation** | blocked by `test_core_viz_direction` allow-list until viz-launcher edge inverted (016) |
| B12 | **Plaintext-secret persistence** (`semantic_scholar_key`, `letta_api_key` in `settings.json`) | routed to 071; REVIEW_REQUIRED |
| B13 | **`ARI_AGENT_ENV_PATH → ~/.ari/agent.env` fallback** vs v0.5.0 checkpoint-scoping | verify code path before editing docs (013/017) |
| B14 | **Remaining frontend god-files** `StepResources.tsx` (1168), `WorkflowPage.tsx` (967) >800 | deferred component split (064) |
| B15 | **Deferred CI wiring** (049 contracts.yml, 050 docs-sync append, 051 prompt-review) | additive-CI-last; checkers now exist |
| B16 | **`check_directory_policy` / `check_dashboard_ux` / `check_docs_source_sync` not in aggregator config** | optional: add to `generate_quality_report.yaml` checker list |
| B17 | **`readme_sync` reconciliation** for the two new report files (§9) | left to the orchestrator per this run's directive |

## 9. `readme_sync` note (report footprint)

This subtask adds `final_quality_report.md` + `final_quality_report.json` under
`docs/refactoring/reports/`. Per the 019 run directive, **the per-directory
`README.md` was NOT edited** (README reconciliation is the orchestrator's job). If
`scripts/readme_sync.py --check` flags the new files, that reconciliation is deferred
to the orchestrator (backlog B17). No other file was touched.

## 10. §13 Acceptance-criteria self-check

| # | Criterion (019 §13) | Status |
|---|---|---|
| 1 | `final_quality_report.md` + `.json` exist; MD counts == JSON `summary` counts (852 findings, 7 checkers, SAFE_DELETE 0) | **PASS** |
| 2 | Header pins timestamp, ari-core 0.9.0, git SHA, exact checker/aggregator paths (031 resolved) | **PASS** |
| 3 | Baseline-delta table covers every §2 metric; complexity marked "newly measured"; nothing fabricated | **PASS** |
| 4 | Contract-certification matrix: one row per §10 contract, PASS/WARN/not-checked — none falsely PASS | **PASS** |
| 5 | `compileall` + `ruff` recorded and at/under baseline (634 ≤ 661); `git status` shows only report files | **PASS** |
| 6 | `reports/README.md` — deferred to orchestrator (not added by 019 this run) | **N/A (deferred, B17)** |
| 7 | No claim any §10 contract was changed; no reference to a nonexistent `sonfigs/` | **PASS** |

pytest criterion (§13.5) satisfied via citation (§3.5): 2656 passed / 2 xfailed / 0
failed, per the orchestrator ledger — not re-run here by directive.

## 11. Retirement Condition

This report is the terminal deliverable and a temporary planning artifact. It may be
archived/deleted (`git rm`) only after subtask 019's §13 Acceptance Criteria are met,
the implementing change is merged into `main`, and
`docs/refactoring/007_subtask_index.md` marks subtask **019** DONE — verified against
primary sources, never on assumption. See the canonical policy in
`007_subtask_index.md` ("Document Retirement Policy").
