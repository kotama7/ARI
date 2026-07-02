# Dead-Code Classification Report (subtask 056)

> **Subtask:** `056_classify_unused_functions_and_files` (Phase 1 — Measurement and
> Inventory) · **Risk:** Low · **Runtime code change:** No · **Depends on:** 055 ·
> **Enables:** 057 → 058.
>
> **Status:** Review/triage artifact. This document changes **no** runtime code,
> imports, prompts, configs, workflows, frontend, or directory names. It is the
> human classification pass on top of the machine output of the 053→054→055 chain:
> it assigns every candidate node from `dead_code_candidates.md` a **master
> classification** (KEEP / ADAPT / MERGE / MOVE_TO_LEGACY / DELETE_CANDIDATE /
> REVIEW_REQUIRED) and records the per-classification counts for subtask 058. It is
> the authoritative, human-reviewed work-list that subtask **057**
> (`delete_safe_dead_code_candidates`) consumes.
>
> **Vocabulary.** Directory/module/file decisions use the master set above.
> Symbol-level dead-code decisions use the finer 013 §7 buckets (PUBLIC_CONTRACT /
> DYNAMIC_REFERENCE_RISK / TEST_ONLY / DOCS_ONLY / QUARANTINE_CANDIDATE /
> SAFE_DELETE_CANDIDATE / REVIEW_REQUIRED, plus the 055 checker's `LIVE` label for
> production-live internal nodes). This report maps the finer buckets onto the
> master set per §2 below. The word "deprecated" is reserved for external contracts
> only and is **not** used to label internal code here.

---

## Header — inputs, tools, provenance (falsifiability)

All figures below are a pure function of the pinned reference graph; re-running the
055 checker on the recorded graph reproduces this candidate set byte-for-byte
(verified: two consecutive JSON runs are identical). No LLM calls were used to make
any classification decision (design principle P2).

| Field | Value |
|---|---|
| Report generated | `2026-07-02` (this pass) |
| Repo baseline | `/home/t-kotama/workplace/ARI` · branch `whole_refactoring` · `ari-core` `0.9.0` |
| Repo HEAD at classification | `4f04da886949b88284b321c87ecabe15367446a7` |
| Input graph | `docs/refactoring/reports/reference_graph.json` (054 output; committed) |
| — git blob SHA | `27736978be6dc18d238ac10b94d61d71a09431f2` |
| — sha256 | `f6fc9b16ca0c42954ab3569132a6101af959afc2ce757e591f4ef4e3358d9b89` |
| — embedded `commit` | `c12007ceba21afb374664e56b521771aff075039` |
| — embedded `generated_at` | `2026-07-01T13:39:25.863071+00:00` |
| — `schema_version` | `1` |
| Input candidate list | `dead_code_candidates.md` (055 output; **regenerable, not committed**) |
| — sha256 (markdown, this run) | `a8b42bbff1f096e5f27fbb0952ff4d081bf89ed7a7878e9984cae4097cb6537e` |
| — sha256 (JSON, this run) | `0f2d254f7a0d157be64e8b904c823566a5461c4fc6fbce8a40122c86be9e2ab8` |
| Classifier | `scripts/check_dead_code.py` (subtask 055) |
| ruff | `0.15.2` (F401/F811/F841 corroboration; 341 `F401` / 39 `F841` baseline) |
| Python | `3.13.2` |

> **Provenance note.** The graph is pinned to its own embedded commit
> `c12007ce…`; the working tree at classification time is at HEAD `4f04da88…`
> (branch `whole_refactoring`). The candidate set is a deterministic function of
> the committed graph, so it is reproducible regardless of the current HEAD. The
> §5 dynamic-seam anchors below were additionally **re-verified live** against the
> current tree (all present, unmoved).

**Regeneration recipe** (deterministic, no network, no LLM):

```sh
# From repo root. Reproduces the exact candidate set this report classifies.
python scripts/check_dead_code.py --format json \
  --output /tmp/dead_code_candidates.json          # SAFE_DELETE_CANDIDATE == 0
python scripts/check_dead_code.py --format markdown \
  --output /tmp/dead_code_candidates.md            # ranked candidate buckets
```

---

## 1. Summary counts

### 1.1 Per master classification (machine-ingestible for subtask 058)

| master_classification | count |
|---|---|
| KEEP | 1641 |
| ADAPT | 0 |
| MERGE | 0 |
| MOVE_TO_LEGACY | 0 |
| DELETE_CANDIDATE | 0 |
| REVIEW_REQUIRED | 349 |
| **Total nodes classified** | **1990** |

### 1.2 Per finer 013 §7 bucket (as emitted by the 055 checker)

| finer_bucket | count | → master_classification |
|---|---|---|
| PUBLIC_CONTRACT | 192 | KEEP |
| DYNAMIC_REFERENCE_RISK | 125 | KEEP |
| LIVE (checker label: production-live internal) | 1324 | KEEP |
| TEST_ONLY | 4 | REVIEW_REQUIRED |
| DOCS_ONLY | 0 | REVIEW_REQUIRED |
| QUARANTINE_CANDIDATE | 0 | MOVE_TO_LEGACY |
| SAFE_DELETE_CANDIDATE | 0 | DELETE_CANDIDATE |
| REVIEW_REQUIRED | 345 | REVIEW_REQUIRED |
| **Total** | **1990** | |

- `SAFE_DELETE_CANDIDATE`: known(allowlisted) = 0 · **new = 0**.
- `REVIEW_REQUIRED` of which `under_traced_seam` (analyzer coverage gap, treated
  live): **345 / 345** — i.e. *every* REVIEW_REQUIRED node is an analyzer
  coverage artifact, not a genuine unresolved orphan.
- Candidate nodes needing active human classification (SAFE_DELETE + QUARANTINE +
  REVIEW_REQUIRED + TEST_ONLY + DOCS_ONLY) = **349**; the remaining 1641 are the
  KEEP firewall/live surface (spot-checked in §5).

> **Headline finding (de-risks subtask 057): `SAFE_DELETE_CANDIDATE = 0`.** After
> the 013 §7 hard-downgrade firewall is applied over the (intentionally sparse) 054
> reachability overlay, **no node is eligible for deletion**. Subtask 057
> (`delete_safe_dead_code_candidates`) therefore has an **empty work-list** and is
> a documented no-op unless/until the reference graph is deepened (see §6.1) and a
> genuine orphan surfaces.

---

## 2. Classification mapping applied (finer bucket → master)

Top-down precedence, first match wins (contract surfaces always outrank delete
candidates), exactly as 056 §7.2 / 013 §7:

| Finer bucket | Master | Applied here |
|---|---|---|
| `PUBLIC_CONTRACT` | **KEEP** | 192 nodes (MCP tools, viz routes, `ari.public.*`, checkpoint/paths/mcp-client/registry file-format owners, `api.ts`). |
| `DYNAMIC_REFERENCE_RISK` | **KEEP** | 125 nodes. Every one carries ≥1 inbound `dynamic.*` / `cross_lang.*` edge **or** sits under a verified §5 seam path; the resolver was proven for all → KEEP (none down-classified to REVIEW_REQUIRED). |
| `LIVE` (checker label) | **KEEP** | 1324 nodes reached from a production root or by a static/dynamic edge — production-live internal code. Not a 013 §7 finer bucket; it is the checker's "referenced internal" label and maps cleanly to KEEP (never a candidate). |
| `TEST_ONLY` | **REVIEW_REQUIRED** | 4 nodes (`ari.schemas` loader) — promote a real caller, keep as helper, or MOVE_TO_LEGACY; never silently deleted (would break tests). |
| `DOCS_ONLY` | **REVIEW_REQUIRED** | 0 nodes. |
| `QUARANTINE_CANDIDATE` | **MOVE_TO_LEGACY** | 0 nodes (label-only; relocation is 057 after the legacy zone is named by the 004/005 stream). |
| `SAFE_DELETE_CANDIDATE` | **DELETE_CANDIDATE** | 0 nodes (the only deletion-eligible class; empty). |
| duplicate-of-another-symbol | **MERGE / ADAPT** | 0 nodes here. Duplicate-code MERGE/ADAPT decisions (the two ReAct loops, the duplicated pipeline, rubric-format handling) are **live** code, not orphans, and are owned by subtask 002/016 — cross-referenced, not re-classified in this dead-code pass. |
| unplaceable | **REVIEW_REQUIRED** | 345 nodes (all `under_traced_seam`). |

Because there are **0** DELETE_CANDIDATE and **0** MOVE_TO_LEGACY rows, the
"every DELETE_CANDIDATE/MOVE_TO_LEGACY row carries evidence" rule (056 §13.3) is
satisfied vacuously; the KEEP firewall surfaces carry their evidence in §3/§5/§7.

---

## 3. Deletion firewall (013 §7 verified expectations) — all PASS

Reproduced from the 055 checker's firewall block against the pinned graph. Each is
a hard "never delete this" expectation; all eight PASS.

| status | check | ref |
|---|---|---|
| PASS | publish backends DYNAMIC_REFERENCE_RISK (4) | 013 §7 / 055 §13.4 |
| PASS | prompt templates DYNAMIC_REFERENCE_RISK (11) | 053 §3 |
| PASS | reviewer rubrics DYNAMIC_REFERENCE_RISK (23) | 053 §3 |
| PASS | `ari.schemas.load()` TEST_ONLY | 053 §5 |
| PASS | `ari/__init__.py` not dead | 013 §7 |
| PASS | `ari/public/__init__.py` not dead | 013 §7 |
| PASS | MCP handlers PUBLIC_CONTRACT (87) | 013 §7 |
| PASS | viz routes PUBLIC_CONTRACT (53) | 013 §7 |

### 3.1 §5 dynamic-seam anchors re-verified live (this pass, current HEAD)

Hand-cross-check per 056 §8 work-item 4 — none slipped toward DELETE_CANDIDATE:

| Seam anchor | Verified live |
|---|---|
| `ari/publish/__init__.py:198` `_load_backend(name)` string dispatch | ✅ present (`:115`, `:164` call sites) |
| `ari/publish/backends/{ari_registry,gh,local_tarball,zenodo}.py` | ✅ 4/4 present → all DYNAMIC_REFERENCE_RISK |
| `ari/evaluator/llm_evaluator.py:165` `_COMPOSITES` (used `:280,:283`) | ✅ present |
| `ari/prompts/_loader.py` `FilesystemPromptLoader.load` (`:41`) / `load_versioned` (`:45`) | ✅ present |
| `ari/schemas/__init__.py:11` `load` / `:18` `schema_path` | ✅ present (TEST_ONLY) |
| `ari-core/config/reviewer_rubrics/*.yaml` | ✅ 23 files |
| `ari/prompts/**/*.md` (non-README) | ✅ 11 templates |
| `ari-core/ari/__init__.py` | ✅ 0 lines (empty structural shell — KEEP) |
| `ari-core/ari/public/__init__.py` | ✅ 27 lines (docstring-only — KEEP) |
| `sonfigs/` | ✅ **does not exist** (`ls sonfigs` → No such file or directory) |

The confusable config trio (`ari-core/ari/config/` locator code, `ari-core/ari/configs/`
packaged data + loader, top-level `ari-core/config/` rubric/profile/workflow data) is
keyed on its three exact paths; **no `sonfigs/` node exists** in the graph.

---

## 4. Ranked candidate table (most-confident deletion first)

Groups ordered by 013 §6.2 (most-confident deletion first). Two groups are empty.

### 4.1 SAFE_DELETE_CANDIDATE → DELETE_CANDIDATE (0)

_none._ Nothing is deletion-eligible on the pinned graph.

### 4.2 QUARANTINE_CANDIDATE → MOVE_TO_LEGACY (0)

_none._ No orphan touches `ari/migrations/` or is a large (≥400 LOC) orphan module.

### 4.3 REVIEW_REQUIRED → REVIEW_REQUIRED (345)

**Master classification: REVIEW_REQUIRED (needs owner decision — but NOT deletable).**
**Rationale:** every one of these 345 nodes is a `py.module`/`py.symbol` under an
**analyzer under-traced seam** — skill-internal packages and subprocess-boundary
helpers that the 054 dynamic overlay intentionally does not walk into (per the 055
checker's `under_traced_seam` reason and 013 §5.6/§8.4). They are **live in
reality**, reached across stdio (`MCPClient.call_tool`) or by string, but have no
statically-resolved inbound edge. The 013 §7 hard-downgrade rule keeps them at
REVIEW_REQUIRED (never `SAFE_DELETE_CANDIDATE`). **Owner:** the reference-graph
stream (054) to deepen per-skill / subprocess reachability tracing; until then,
**treat live, do not delete or move.** `evidence`: no inbound edge resolved *and*
node sits under an under-traced seam path (`scripts/quality/check_dead_code.yaml`
`under_traced_seam_paths`).

Aggregated by file (each node counted exactly once; per-node ids are in the
regenerable `dead_code_candidates.md` / JSON). All rows: master = REVIEW_REQUIRED,
finer = REVIEW_REQUIRED (`under_traced_seam`).

| file | orphan nodes |
|---|---|
| `ari-core/ari/llm/cli_server.py` | 35 |
| `ari-core/ari/memory/file_client.py` | 3 |
| `ari-core/ari/memory/local_client.py` | 2 |
| `ari-skill-hpc/src/singularity.py` | 6 |
| `ari-skill-idea/src/snapshot.py` | 23 |
| `ari-skill-idea/src/virsci_runtime.py` | 20 |
| `ari-skill-memory/src/ari_skill_memory/audit.py` | 5 |
| `ari-skill-memory/src/ari_skill_memory/backends/base.py` | 3 |
| `ari-skill-memory/src/ari_skill_memory/backends/letta_client.py` | 8 |
| `ari-skill-memory/src/ari_skill_memory/consolidation.py` | 7 |
| `ari-skill-memory/src/ari_skill_memory/context_builder.py` | 4 |
| `ari-skill-memory/src/ari_skill_memory/provenance.py` | 7 |
| `ari-skill-memory/src/ari_skill_memory/retriever.py` | 5 |
| `ari-skill-memory/src/ari_skill_memory/schemas.py` | 7 |
| `ari-skill-memory/src/ari_skill_memory/writer.py` | 8 |
| `ari-skill-paper-re/src/_compute/computer.py` | 10 |
| `ari-skill-paper-re/src/_compute/local_pbtask.py` | 5 |
| `ari-skill-paper-re/src/_litellm_completer.py` | 18 |
| `ari-skill-paper-re/src/_paperbench_bridge.py` | 44 |
| `ari-skill-paper-re/src/_replicator_agent.py` | 16 |
| `ari-skill-paper-re/src/_vendor_path.py` | 5 |
| `ari-skill-paper/src/claim_links.py` | 26 |
| `ari-skill-paper/src/rubric.py` | 14 |
| `ari-skill-replicate/src/categories.py` | 10 |
| `ari-skill-replicate/src/manifest.py` | 12 |
| `ari-skill-replicate/src/rubric_template.py` | 11 |
| `ari-skill-transform/src/claims.py` | 18 |
| `ari-skill-transform/src/curate.py` | 13 |
| **Total** | **345** (28 files) |

> Note `_paperbench_bridge.py` (44) and `_vendor_path.py`/`_compute/*` under
> `ari-skill-paper-re/` are the vendored PaperBench bridge — live-by-vendor-parity
> (010 §8 "vendored trees KEEP as-is"); classify KEEP-in-spirit but the graph
> could not trace their intra-package edges, so they remain REVIEW_REQUIRED here
> and must never be deleted.

### 4.4 DOCS_ONLY → REVIEW_REQUIRED (0)

_none._

### 4.5 TEST_ONLY → REVIEW_REQUIRED (4)

**Master classification: REVIEW_REQUIRED.** **Rationale:** the `ari.schemas`
loader has no production importer — only tests reach it, and `tests/test_node_report.py`
reads the `.json` by direct filesystem path, bypassing the loader (053 §5 / 013
§5.2). Per 056 §13.5 these are TEST_ONLY → REVIEW_REQUIRED (**not**
DELETE_CANDIDATE). Owner decision: promote a real production caller, keep as a test
helper, or MOVE_TO_LEGACY — never silently deleted (would break tests). The
`.json` schema **data files** themselves are live (allow-list §7 item 8) and are
classified DYNAMIC_REFERENCE_RISK / KEEP separately.

| file | symbol | loc | finer_bucket | master | evidence | rationale |
|---|---|---|---|---|---|---|
| `ari-core/ari/schemas/__init__.py` | (module) | 21 | TEST_ONLY | REVIEW_REQUIRED | reachable only from R9 tests | loader module has no production importer (053 §5) |
| `ari-core/ari/schemas/__init__.py` | `load` | 5 | TEST_ONLY | REVIEW_REQUIRED | `:11`; only tests reach it | keep as test helper or promote a caller |
| `ari-core/ari/schemas/__init__.py` | `schema_path` | 3 | TEST_ONLY | REVIEW_REQUIRED | `:18`; only tests reach it | keep as test helper or promote a caller |
| `ari-core/ari/schemas/__init__.py` | `_HERE` | 1 | TEST_ONLY | REVIEW_REQUIRED | module-private path constant | lives with the loader; same decision |

---

## 5. Kept surfaces (KEEP firewall — never deletion candidates)

Counted, spot-checked (056 §8 work-item 3: PUBLIC_CONTRACT spot-check,
DYNAMIC_REFERENCE_RISK seam verification in §3.1).

### 5.1 PUBLIC_CONTRACT → KEEP (192)

| surface | nodes |
|---|---|
| MCP tool handlers (`mcp.tool`) | 87 |
| Dashboard HTTP/WS routes (`route`) | 53 |
| `ari/checkpoint.py` (file-format owner) | 14 |
| `ari/mcp/client.py` | 15 |
| `ari.public.*` (8 submodules + `__init__`) | 17 |
| `ari/registry/app.py` (EAR HTTP surface) | 2 |
| `ari/paths.py` (`PathManager`) | 2 |
| `ari/__init__.py` (structural shell) | 1 |
| `frontend` (`api.ts`, `ts.module`) | 1 |

All are 010 §1–§9 / 056 §10 contract-firewall items — KEEP; any future change needs
a compatibility-adapter note (010 §10), never deletion. The `read_file` MCP tool
name collision (coding + orchestrator) is preserved as observed behaviour and
recorded in §6.2.

### 5.2 DYNAMIC_REFERENCE_RISK → KEEP (125)

By kind: `data.file` 54, `py.module` 44, `py.symbol` 27. Includes the four
`publish/backends/*` modules (24 nodes incl. their symbols), the 11 prompt `.md`
templates, 23 reviewer rubrics + 4 paperbench rubrics + 3 profiles + 3 fewshot
JSON, the 2 JSON schema data files, `config/workflow.yaml`, the packaged
`ari/configs/*` data + loader, and every resolved `dynamic.*` / `cross_lang.*`
target (routing, evaluator composites, prompt/config loaders, per-skill dynamic
seams). All KEEP — see the §7 allow-list.

### 5.3 LIVE (production-live internal) → KEEP (1324)

Reached from a production root (R1–R8, R11, R12) or by a resolved static/dynamic
edge. Ordinary internal implementation code. KEEP; not a candidate.

---

## 6. Open items / REVIEW_REQUIRED cross-references (record only — do not resolve here)

Carried from 053 §10 and the 054 collision report; none is a deletion decision.

1. **§6.1 — Analyzer coverage gap dominates REVIEW_REQUIRED.** All 345
   REVIEW_REQUIRED nodes are `under_traced_seam` (skill-internal / subprocess /
   vendored trees). This is a *reference-graph completeness* limitation (054), not
   dead code. Deepening the 054 per-skill + subprocess overlay would move most of
   these into LIVE. **Owner:** reference-graph stream. **Action for 057:** treat
   all as live; none is deletable.
2. **§6.2 — MCP flat-namespace collision.** `read_file` is registered by both
   `coding` and `orchestrator`; `MCPClient._tool_registry` (`client.py:283`) keeps
   the last-registered skill (last-skill-wins). Both handlers are PUBLIC_CONTRACT /
   KEEP; resolution belongs to the MCP/skill stream (010 §3), not this report. Do
   not de-duplicate away either handler node.
3. **§6.3 — `publish.schema.json:51` enum-vs-impl drift.** The enum lists
   `["ari-registry","gh","zenodo","s3","local-tarball"]` (5) but `_load_backend`
   implements only 4 (no `s3` branch, no `backends/s3.py`). `"s3"` is **not** a
   live-by-string target; recorded as REVIEW_REQUIRED drift (owner: registry/DI
   stream, 014). It strengthens — does not weaken — the firewall.
4. **§6.4 — `ARI_MEMORY_BACKEND` set without a core consumer.** Set at
   `config/__init__.py:316`; core hardcodes `LettaMemoryClient` (`core.py:130`).
   Any alternative memory-backend class is DYNAMIC_REFERENCE_RISK, not an orphan
   (013 §5.1). Owner: registry/DI stream.
5. **§6.5 — Unused `server:main` console scripts (entrypoint noise).**
   `ari-skill-replicate` and `ari-skill-paper-re` declare `[project.scripts] … =
   "server:main"` but skills launch by filesystem path (053 §7). These are
   pyproject entries, **not** graph nodes, so they do not appear in the candidate
   table; recorded here as REVIEW_REQUIRED entrypoint noise (owner: 010 §3 skill
   stream) — remove as internal cleanup only, never as "deprecation".
6. **§6.6 — Subtask-numbering drift.** 013 §8.1/§10 assign `analyze_references.py`
   to subtask 053; the canonical 007 index assigns it to 054 (053 = inventory).
   This report follows 007. Recorded, not resolved.

---

## 7. Allow-list appendix — live-by-string roots (the 057 deletion firewall)

Reproduced from 053 §3 (all paths re-verified present). If a future 057 deletion
candidate appears here, it is reclassified out of SAFE_DELETE_CANDIDATE and the
workflow stops. **Master classification for every row: KEEP.**

| # | Item | Path / anchor | Count | Finer bucket |
|---|---|---|---|---|
| 1 | Publish backends | `ari/publish/backends/{ari_registry,local_tarball,zenodo,gh}.py` | 4 | DYNAMIC_REFERENCE_RISK |
| 2 | Evaluator composite callables | `evaluator/llm_evaluator.py:75,102,122,141` | 4 | DYNAMIC_REFERENCE_RISK |
| 3 | Prompt templates | `ari/prompts/**/*.md` (non-README) | 11 | DYNAMIC_REFERENCE_RISK |
| 4 | Reviewer rubrics | `config/reviewer_rubrics/*.yaml` | 23 | DYNAMIC_REFERENCE_RISK |
| 5 | PaperBench rubrics | `config/paperbench_rubrics/{generic,nature,neurips,sc}.yaml` | 4 | DYNAMIC_REFERENCE_RISK |
| 6 | Profiles | `config/profiles/{cloud,hpc,laptop}.yaml` | 3 | DYNAMIC_REFERENCE_RISK |
| 7 | Fewshot JSON | `config/reviewer_rubrics/fewshot_examples/neurips/*.json` | 3 | DYNAMIC_REFERENCE_RISK |
| 8 | JSON schemas (data) | `ari/schemas/{node_report,publish}.schema.json` | 2 | DYNAMIC_REFERENCE_RISK |
| 9 | Workflow graph | `config/workflow.yaml` | 1 | DYNAMIC_REFERENCE_RISK |

**Allow-list total: 51 items** (4+4+11+23+4+3+3+2+1). Skill-local prompt trees
(`ari-skill-paper-re/src/prompts/`, `ari-skill-replicate/src/prompts/`) are the same
class within their packages.

Additional contract-firewall surfaces that must never be DELETE_CANDIDATE /
MOVE_TO_LEGACY (056 §10 / 010 §1–§9), all KEEP:

- **CLI:** console script `ari = ari.cli:app`; all command names/flags in
  `ari/cli/*` and their `ARI_*` env side effects.
- **Public Python API:** every `ari.public.*` submodule + the shells
  `ari/__init__.py`, `ari/public/__init__.py`.
- **MCP contracts:** all 87 `@mcp.tool` / `Tool(name=…)` handlers, their
  `inputSchema`, the `{"result"|"error"}` envelope, `mcp__<skill>__<tool>` naming.
- **Dashboard API:** `ari/viz/routes.py`, the 14 `ari/viz/api_*.py`,
  `websocket.py`, everything reached by `frontend/src/services/api.ts`.
- **Checkpoint/config/output formats:** `ari/checkpoint.py`; YAML under
  `ari-core/config/` and `ari-core/ari/configs/`; JSON schemas under `ari/schemas/`.
- **Dynamic-seam live-by-string code:** `ari/publish/backends/*`, all prompt `.md`,
  the 23 rubrics + profiles + fewshot JSON, `_COMPOSITES` targets.
- **CI-invoked scripts:** everything called by `.github/workflows/*`.

---

## 8. Acceptance-criteria self-check (056 §13)

| # | Criterion | Result |
|---|---|---|
| 1 | Report exists, English, §7.1 structure (header SHAs + summary + ranked table + allow-list) | ✅ |
| 2 | Every candidate node from `dead_code_candidates.md` appears once with a master + finer bucket | ✅ (4 TEST_ONLY per-node; 345 REVIEW_REQUIRED aggregated by 28 files, each counted once; 0 in the empty groups) |
| 3 | Every DELETE_CANDIDATE / MOVE_TO_LEGACY row carries evidence | ✅ vacuous (0 such rows) |
| 4 | No §10 firewall item is DELETE_CANDIDATE / MOVE_TO_LEGACY; backends/prompts/rubrics/MCP/`ari.public.*` are KEEP | ✅ (§3, §5, §7; 8/8 firewall PASS) |
| 5 | `ari.schemas.load()` / `schema_path()` are TEST_ONLY → REVIEW_REQUIRED (not DELETE) | ✅ (§4.5) |
| 6 | Per-classification counts present and machine-ingestible for 058 | ✅ (§1.1/§1.2) |
| 7 | Only §9 files changed; no runtime code touched | ✅ (only this file created) |
| 8 | Regenerable: re-running 055 on the recorded graph reproduces the candidate set | ✅ (two runs byte-identical; §Header recipe) |

---

## 9. Retirement Condition

This subtask artifact (and its plan `subtasks/056_classify_unused_functions_and_files.md`)
is a **temporary planning/inventory artifact**. It may be archived or `git rm`-ed
only after **all** of the following are verified against primary sources — never on
assumption:

1. The §13 Acceptance Criteria of the 056 plan are met (self-checked in §8 above).
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **056** as DONE.

Until every condition is confirmed, this report is **KEEP**. Downstream subtask
057 must not begin acting on a non-empty work-list — on the pinned graph there is
none. See the canonical policy in `007_subtask_index.md` ("Document Retirement
Policy").
