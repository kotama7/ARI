# Subtask 036: Inventory Hardcoded Prompts

> Phase 7: Prompt Management · Risk: Low · Runtime code change: **No** · Depends on: — (root inventory)
>
> Planning document only. Nothing here modifies runtime code, imports, prompts,
> templates, configs, workflows, frontend, or directory names. It hands a fresh
> coding session an executable plan to produce a **read-only inventory** of every
> prompt string in the ARI tree — the ones already externalized under
> `ari-core/ari/prompts/`, the ones externalized-but-loaded-ad-hoc inside skills,
> and the ones still hardcoded inline in Python — and to classify each so the
> downstream Phase-7 extraction subtasks (037–044) can act behind a frozen
> baseline. All paths are repository-real and verified against the tree at planning
> date 2026-07-01 (ari-core `0.9.0`, branch `main`).

## 1. Goal

Produce a **complete, machine-checkable inventory of every prompt** used by ARI's
LLM call sites, spanning three storage regimes:

1. **Core externalized templates** — the 11 `.md` files under
   `ari-core/ari/prompts/` loaded through `FilesystemPromptLoader`
   (`_loader.py`, 49 LOC), each already pinned by sha256 in
   `ari-core/tests/test_prompt_extraction.py` (107 LOC).
2. **Skill-local externalized templates** — the 5 `.md` files under
   `ari-skill-replicate/src/prompts/` and `ari-skill-paper-re/src/prompts/` that
   are read with ad-hoc `Path.read_text()` and therefore get **no** version hash.
3. **Still-inline hardcoded prompts** — substantial `"You are …"` system prompts
   and JSON-schema instruction blocks embedded directly in the largest skill
   `server.py` files and in a handful of core modules.

For every prompt the inventory records: a stable **key/identifier**, its **storage
regime** (core-loader / skill-read_text / inline), the **owning file + line**, the
**call site(s)** that consume it, the **`str.format` placeholders** or dynamic
inputs it interpolates, an approximate **length**, whether it is **vendored**
(mirrors an upstream PaperBench/VirSci string), and a **classification** drawn from
the Phase-7 vocabulary (§7.2). 036 writes **no runtime code**; its only deliverable
is a reference artifact under `docs/refactoring/reports/` (see §9). This inventory
is the **frozen baseline** that subtasks 037, 038, 039, 040, 041, 042, 043, and 044
consume. Per `docs/refactoring/007_subtask_index.md:83`, 036's deliverable is the
"Hardcoded-prompt inventory" and it is one of the nine inventory subtasks that MUST
precede any runtime code change (`007_subtask_index.md:513`).

## 2. Background

ARI is **not** a green-field prompt-management project — a partial externalization
layer already exists (`docs/refactoring/011_prompt_management_plan.md:9-24`):

- `ari-core/ari/prompts/_loader.py` (49 LOC) defines a `PromptLoader` `Protocol`
  and a concrete `FilesystemPromptLoader`. `load(key)` reads `{base}/{key}.md`
  (base defaults to `package_prompts_root()`, `_loader.py:16-18`);
  `load_versioned(key)` returns `(text, sha256(text)[:12])` for reproducibility
  pinning (`_loader.py:45-49`). `__init__.py` (12 LOC) re-exports
  `FilesystemPromptLoader, PromptLoader, package_prompts_root`; it is also
  re-exported through `ari/protocols/__init__.py:20`.
- Templates are **Markdown filled by Python `str.format`** — single-brace
  `{name}` placeholders — **not** Jinja `.j2` (confirmed;
  `ari-core/ari/prompts/README.md:36`). 037 will formalize this as policy.
- Every core load site uses a **lazy in-function import**
  `from ari.prompts import FilesystemPromptLoader` (11 files, verified below).
- `ari-core/tests/test_prompt_extraction.py` (107 LOC) already pins every core
  template to a hardcoded sha256, and `report/scripts/check_prompt_snapshots.py`
  (Gate 10) byte-verifies `ari-core/ari/prompts/**/*.md`.

What is **missing** is (a) an inventory of the prompts that are *still inline*, and
(b) a decision record for the *mechanism inconsistency* where skills bypass the
core loader. That is exactly 036's job. The routed prompts finding (planning pack)
plus `011_prompt_management_plan.md` already identify the high-value inline targets;
036 turns those findings into a single authoritative, line-anchored artifact.

Phase 7 is small and linear-ish: **all** of 037–044 fan out from 036
(`007_subtask_index.md:294, 422-429`). 036 unblocks the policy doc (037), the
registry/loader extension (038), the three byte-identical extraction subtasks
(039/040/041), the snapshot tests (042), the `check_prompts.py` checker (043), and
run-metadata prompt-version tracking (044). If the inventory is wrong or
incomplete, every downstream subtask inherits the error, so accuracy is the whole
value.

## 3. Scope

In scope (read-only inventory production):

- **Enumerate the 11 core templates** under `ari-core/ari/prompts/`, each with its
  loader key, file, length, `str.format` placeholders, and the exact call site(s)
  that consume it (the 11 lazy-import sites listed in §5).
- **Enumerate the 5 skill-local externalized templates** under
  `ari-skill-replicate/src/prompts/` and `ari-skill-paper-re/src/prompts/`, and
  record that they are loaded via ad-hoc `Path.read_text()` (no version hash) —
  the **mechanism inconsistency** that 038 must resolve.
- **Enumerate the still-inline prompts** in the skill `server.py` files and core
  modules, at minimum the targets in §6, each with file+line, approximate length,
  interpolated inputs, and whether it embeds a JSON output schema.
- **Classify every entry** with the Phase-7 vocabulary (§7.2): KEEP_INLINE /
  EXTRACT_TEMPLATE / MERGE_DUPLICATE / MOVE_TO_CONFIGURABLE_PROMPT /
  REVIEW_REQUIRED — as a **recommendation for 037–044 only** (036 changes nothing).
- **Flag vendored prompts** (PaperBench templates in
  `ari-skill-paper-re/src/_paperbench_bridge.py`; VirSci `utils/prompt.py` path in
  `ari-skill-idea/src/server.py`) as KEEP_INLINE with an upstream-parity note.
- **Record duplication/overlap** between core templates and skill inline prompts
  (peer-review; metric-extraction) as MERGE_DUPLICATE / REVIEW_REQUIRED candidates.
- **Record the mechanism-inconsistency finding** (skills bypass
  `FilesystemPromptLoader`) as a REVIEW_REQUIRED design item for 038.

## 4. Non-Goals

- **Do not extract, move, rename, edit, or reformat any prompt** — not the `.md`
  templates, not the inline strings, not the loader. That is 039/040/041's job,
  guarded by 042's snapshot tests. 036 only *reads and records*.
- **Do not** add or modify `FilesystemPromptLoader`, a prompt registry, or any
  loader plumbing — that is **038**.
- **Do not** author the prompt-template **policy** (`.md` vs `.j2`, placeholder
  convention, key naming) — that is **037**; 036 only records the *current* facts
  the policy will codify.
- **Do not** create `scripts/docs/check_prompts.py` or any checker — that is
  **043**. (It does not exist today; `ls scripts/docs/check_prompts.py` →
  "does not exist".) Note the partial overlap with the existing
  `report/scripts/check_prompt_snapshots.py` (Gate 10) and record it; do not touch
  that file.
- **Do not** add snapshot tests (**042**) or wire prompt hashes into run metadata /
  checkpoint format (**044**).
- **Do not** "fix" the mechanism inconsistency (skills using `read_text()`), the
  peer-review duplication, or the metric-extract duplication found during
  inventory. Record them as REVIEW_REQUIRED / MERGE_DUPLICATE findings for 038/040.
- **Do not** touch `ari.public.*`, the CLI, MCP `ari-skill-*` tool contracts, the
  dashboard API, checkpoint/config file formats, README/docs usage, or workflow
  scripts. None are edited by an inventory.
- **Do not** fork or re-derive vendored upstream strings (PaperBench, VirSci) —
  they stay byte-for-byte with upstream; inventory only marks them.

## 5. Current Files / Directories to Inspect

### 5.1 Core loader + externalized templates (`ari-core/ari/prompts/`)

- `_loader.py` (49 LOC) — `package_prompts_root` (`:16`), `PromptLoader` Protocol
  (`:21-32`), `FilesystemPromptLoader.load` (`:41-43`), `load_versioned` (`:45-49`).
- `__init__.py` (12 LOC) — re-exports; also re-exported via
  `ari-core/ari/protocols/__init__.py:20`.
- `README.md` (top) + 5 per-directory `README.md` (`agent/`, `evaluator/`,
  `orchestrator/`, `pipeline/`, `viz/`).
- The 11 templates (loader key = path minus `.md`):
  - `agent/system.md` (13 L)
  - `evaluator/extract_metrics.md` (16 L), `evaluator/peer_review.md` (12 L)
  - `orchestrator/bfts_expand.md` (16 L), `orchestrator/bfts_expand_select.md`
    (8 L), `orchestrator/bfts_select.md` (15 L),
    `orchestrator/lineage_decision.md` (6 L), `orchestrator/root_idea_selector.md`
    (6 L)
  - `pipeline/keyword_librarian.md` (352 bytes; `wc -l` = 0 — no trailing
    newline, **not empty**)
  - `viz/wizard_chat_goal.md` (607 B), `viz/wizard_generate_config.md` (257 B) —
    both `wc -l` = 0 but populated.

### 5.2 Core call sites (11 lazy-import consumers — verified)

- `ari-core/ari/agent/loop.py:51` (1630 LOC file) — `agent/system`.
- `ari-core/ari/evaluator/llm_evaluator.py:254`, `:412` — `evaluator/extract_metrics`,
  `evaluator/peer_review`.
- `ari-core/ari/orchestrator/bfts.py:475`, `:553`, `:743` (845 LOC file) —
  `orchestrator/bfts_select`, `bfts_expand_select`, `bfts_expand`.
- `ari-core/ari/orchestrator/lineage_decision.py:292` — `orchestrator/lineage_decision`.
- `ari-core/ari/orchestrator/root_idea_selector.py:62` — `orchestrator/root_idea_selector`.
- `ari-core/ari/pipeline/context_builder.py:116` — `pipeline/keyword_librarian`.
- `ari-core/ari/viz/api_tools.py:54`, `:126` — `viz/wizard_chat_goal`,
  `viz/wizard_generate_config`.

### 5.3 Skill-local externalized templates (bypass the core loader)

- `ari-skill-replicate/src/prompts/`: `skeleton.md` (143 L), `subtree.md` (115 L),
  `adversarial_reviewer.md` (208 L), `rubric_audit.md` (28 L), `README.md`. Loaded
  via `PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"` and
  `(PROMPTS_DIR / "x.md").read_text()` at `generator.py:64, 77, 93` and
  `auditor.py:130` (`PROMPTS_DIR` defined `generator.py:26`, `auditor.py:17`).
- `ari-skill-paper-re/src/prompts/`: `replicator.md` (154 L) + `README.md` +
  `mpi_aggregate_skel.py` (**code skeleton, not a prompt**). `replicator.md` loaded
  via `server.py:66` (`return p.read_text()`).

### 5.4 Still-inline prompt hosts (largest LLM call-site files)

- `ari-skill-evaluator/src/server.py` (983 LOC) — `_METRIC_EXTRACT_SYS` (`:191`,
  consumed `:217`), `_SEMANTIC_SYSTEM_PROMPT` (`:790`, consumed `:903`); 31
  triple-quote blocks total (not all prompts — sampled, not fully line-verified).
- `ari-skill-paper/src/server.py` (2956 LOC — largest skill file) — 5 primary
  `"You are …"` prompts at `:542` (academic reviewer), `:1487` (fill-in writer),
  `:1638` (LaTeX figure inserter), `:1660` (paper writer), `:2544`
  (`_GLOBAL_COHERENCE` editor). Additional venue-parameterized `"You are …"`
  f-strings at `:353, :622, :631, :639` (title/abstract/section revisers).
- `ari-skill-paper/src/review_engine.py` (489 LOC) — `build_system_prompt` (`:58`,
  body `"You are a rigorous peer reviewer …"` at `:79-80`), Area Chair meta-review
  prompt at `:443`.
- `ari-skill-plot/src/server.py` (802 LOC) — `:90` (writing expert), `:560`
  (visualization expert), `:663` (matplotlib JSON emitter).
- `ari-skill-vlm/src/server.py` (355 LOC) — `:97` (figure reviewer), `:112` (table
  reviewer).
- `ari-skill-transform/src/server.py` (2465 LOC) — `:834`, `:867` (scientific-
  analyst summarizers).
- `ari-skill-web/src/server.py` (712 LOC) — `:465` (research librarian), `:483`
  (reference selector).
- `ari-skill-idea/src/server.py` (775 LOC) — fallback prompts only at `:253`,
  `:293`; primary path execs vendored VirSci `utils/prompt.py` via `_VirSciPrompts`
  (`:45-48`, used `:245-250`). KEEP_INLINE.
- `ari-skill-paper-re/src/_paperbench_bridge.py` (2376 LOC) — 59 triple-quote
  blocks, mostly **vendored** PaperBench templates (e.g. `:944`, reference to
  `solvers/basicagent/prompts/templates.py` at `:195`). KEEP_INLINE.

### 5.5 Rubric builders (parameterized prompt scaffolds, not prompt text)

- `ari-skill-paper/src/rubric.py` (344 LOC, 6 triple-quotes) and
  `ari-skill-replicate/src/rubric_template.py` (237 LOC, 9 triple-quotes) — rubric
  builders whose *static scaffolding* could later move to a template while dynamic
  rubric injection stays inline. Classify MOVE_TO_CONFIGURABLE_PROMPT (recommendation
  only).

### 5.6 Existing tooling + companion docs (cross-reference, do not edit)

- `ari-core/tests/test_prompt_extraction.py` (107 LOC) — sha256 pins for the 11
  core templates.
- `report/scripts/check_prompt_snapshots.py` (Gate 10) — byte-verifier for
  `ari-core/ari/prompts/**/*.md`.
- `docs/refactoring/011_prompt_management_plan.md` — the Phase-7 area plan;
  `docs/refactoring/007_subtask_index.md` (Phase 7 at `:292-315`, dependency edges
  `:422-429`).

Output location for the artifact: `docs/refactoring/reports/` (create the
directory if absent — it currently holds no `036` artifact). The inventory is a
**new reference file** (see §9), not a code change.

## 6. Current Problems

Findings to **record**, not to fix in 036:

1. **Prompt storage is split across three regimes with two mechanisms.** Core
   templates use `FilesystemPromptLoader` (versioned via `load_versioned`); skill
   templates use raw `Path.read_text()` (`generator.py:64/77/93`, `auditor.py:130`,
   `paper-re/server.py:66`) with **no** hash; and high-value prompts remain inline
   in Python. There is no single list, so 037–044 have no baseline to diff against
   unless 036 produces one.
2. **Mechanism inconsistency (REVIEW_REQUIRED for 038).** The five skill-local
   `.md` prompts get no version pin and are invisible to
   `report/scripts/check_prompt_snapshots.py` (which scans only
   `ari-core/ari/prompts/`). Any provenance/versioning story (044) is therefore
   incomplete for skill prompts until 038 decides how they route through a shared
   loader without breaking the ari-skill → ari-core boundary.
3. **High-value system prompts are still inline.** `_SEMANTIC_SYSTEM_PROMPT`
   (`evaluator/server.py:790`, ~18 L, judge rubric + JSON schema) and the five
   `ari-skill-paper/src/server.py` prompts (incl. `_GLOBAL_COHERENCE` at `:2544`
   with 5 hard-constraint rules + a JSON edit schema) cannot be A/B tested,
   version-pinned, or snapshot-guarded while embedded in 2956-/983-line files.
4. **Duplicated "peer reviewer" concept in two places (MERGE_DUPLICATE /
   REVIEW_REQUIRED).** `ari-skill-paper/src/review_engine.py:58` `build_system_prompt`
   and `:443` Area-Chair prompt overlap conceptually with core
   `evaluator/peer_review.md`, but are **not byte-identical** and have different
   scope (venue-rubric-parameterized vs. static core template). Consolidation is a
   judgment call for 040 — record, don't resolve.
5. **Duplicated "metric extraction" concept (REVIEW_REQUIRED).**
   `evaluator/server.py:191` `_METRIC_EXTRACT_SYS` vs. core
   `evaluator/extract_metrics.md` — both extract metrics, but distinct scope
   (optimize-target selection vs. artifact extraction). Related, not identical.
6. **Vendored strings must not be forked.** `_paperbench_bridge.py` (59
   triple-quotes) mirrors `vendor/paperbench/` templates, and
   `ari-skill-idea/src/server.py` primarily execs VirSci `utils/prompt.py`.
   Externalizing these would diverge from upstream — they are KEEP_INLINE, and the
   inventory must mark them so 039/040/041 skip them.
7. **`_paperbench_bridge.py` and `evaluator/server.py` triple-quote totals are
   counts, not audits.** 59 and 31 triple-quote blocks respectively were counted by
   grep; only the cited lines were inspected. The inventory must state that
   per-file totals are counts and mark unaudited blocks REVIEW_REQUIRED rather than
   asserting each is (or is not) a prompt.
8. **No inline-prompt checker exists.** `scripts/docs/check_prompts.py` does not
   exist; the only prompt tooling is the core-only
   `report/scripts/check_prompt_snapshots.py`. 043 will add the checker; 036 must
   define the ground truth it will enforce.

## 7. Proposed Design / Policy

036 produces **one inventory artifact** plus a short findings section. No runtime
classification changes anything; classifications are *recommendations* consumed by
037–044.

### 7.1 Inventory format

Emit a diff-friendly reference file (recommended:
`docs/refactoring/reports/hardcoded_prompt_inventory.md` with an embedded table,
and optionally a `.json` twin if 043's checker author prefers structured input).
Each prompt row:

| field | source of truth |
| --- | --- |
| `prompt_id` | stable key: existing loader key for core (`agent/system`), proposed key for inline (`skill.paper.global_coherence`) |
| `regime` | `core-loader` / `skill-read_text` / `inline` |
| `owner` | file + line (e.g. `ari-skill-paper/src/server.py:2544`) |
| `call_site(s)` | where the string is passed to an LLM (system/user role + line) |
| `format_inputs` | `str.format` placeholders or f-string interpolations / dynamic rubric fields |
| `embeds_json_schema` | yes/no (affects extraction risk — schema drift is silent) |
| `length` | line count or byte size |
| `vendored` | yes (PaperBench/VirSci) / no |
| `versioned_today` | yes (core `load_versioned`) / no (skill read_text / inline) |
| `classification` | KEEP_INLINE / EXTRACT_TEMPLATE / MERGE_DUPLICATE / MOVE_TO_CONFIGURABLE_PROMPT / REVIEW_REQUIRED |
| `target_subtask` | 038 / 039 / 040 / 041 (which extraction subtask should own it) |

### 7.2 Classification vocabulary (Phase-7 specific, from 011 / master prompt)

Use the Phase-7 prompt vocabulary as the primary axis, mapping onto the master
vocabulary where a reviewer needs it:

- **KEEP_INLINE** — leave as-is. Vendored (PaperBench `_paperbench_bridge.py`,
  VirSci `idea/server.py` primary path), trivial role strings, or fallbacks whose
  primary path is upstream. (master: KEEP.)
- **EXTRACT_TEMPLATE** — move byte-identically into a `.md` template loaded by the
  loader; guarded by 042 snapshot tests. High-value inline system prompts
  (`_SEMANTIC_SYSTEM_PROMPT`, the 5 paper prompts, plot/vlm/web/transform prompts).
  (master: ADAPT.)
- **MERGE_DUPLICATE** — consolidate overlapping prompts into one template with
  parameters (peer-review core vs. `review_engine`). Requires human sign-off
  because they are not byte-identical. (master: MERGE + REVIEW_REQUIRED.)
- **MOVE_TO_CONFIGURABLE_PROMPT** — the string is already data/rubric-parameterized
  (`review_engine.build_*_prompt`, `rubric.py`, `rubric_template.py`); externalize
  only the *static scaffold*, keep dynamic injection inline. (master: ADAPT.)
- **REVIEW_REQUIRED** — needs a human/design decision before any action: the
  skill-loader mechanism inconsistency, the unaudited `_paperbench_bridge.py` /
  `evaluator/server.py` triple-quote blocks, the metric-extract overlap.

Do **not** use "deprecated" for any of these — it is reserved for external
contracts (public API, CLI, MCP, dashboard API, documented import paths). No prompt
here is an external contract.

### 7.3 Extraction method (deterministic, no code change)

- Derive core entries directly from the 11 `.md` files and their 11 lazy-import
  call sites (§5.2). Confirm each `str.format` placeholder against the consuming
  `.format(...)` call.
- Derive skill-local entries from the 5 `.md` files + their `read_text()` call
  sites (§5.3).
- Derive inline entries by static reading of the cited lines in §5.4; for the two
  high-triple-quote files (`_paperbench_bridge.py` 59, `evaluator/server.py` 31),
  scan every triple-quote block and classify it, marking any block not individually
  read as REVIEW_REQUIRED (do not assert un-inspected blocks are prompts).
- Cross-reference against `011_prompt_management_plan.md §2` (which already
  enumerates core templates and the mechanism split) so the two documents agree.
- The inventory generation may be scripted (a throwaway grep/analysis script under
  the scratchpad, **not** committed). Do **not** add a checker to `scripts/` — that
  is subtask **043**.

## 8. Concrete Work Items

1. **Inventory the 11 core templates.** For each of the §5.1 files: loader key,
   length, `str.format` placeholders, and the exact §5.2 call site + LLM role.
   Record `versioned_today = yes` (all are pinned by
   `test_prompt_extraction.py`). Classification KEEP (already externalized).
2. **Inventory the 5 skill-local templates** (`replicate` × 4, `paper-re` × 1):
   file, length, `read_text()` call site (`generator.py:64/77/93`,
   `auditor.py:130`, `paper-re/server.py:66`). Record `versioned_today = no` and
   flag **REVIEW_REQUIRED** for the mechanism inconsistency (input to 038).
   Exclude `mpi_aggregate_skel.py` (code skeleton, not a prompt) with a one-line
   note.
3. **Inventory the evaluator inline prompts.** `_METRIC_EXTRACT_SYS`
   (`server.py:191`→`:217`) and `_SEMANTIC_SYSTEM_PROMPT` (`:790`→`:903`): length,
   whether each embeds a JSON schema, interpolated inputs. Classify
   `_SEMANTIC_SYSTEM_PROMPT` EXTRACT_TEMPLATE (target 040); classify
   `_METRIC_EXTRACT_SYS` REVIEW_REQUIRED (overlap with core
   `evaluator/extract_metrics.md`).
4. **Inventory the 5 paper `server.py` prompts** (`:542, :1487, :1638, :1660,
   :2544`) plus the 4 venue-parameterized revisers (`:353, :622, :631, :639`).
   Mark `_GLOBAL_COHERENCE` (`:2544`) as embedding a JSON edit schema + 5 hard
   rules → highest-value EXTRACT_TEMPLATE (target 041, largest file 2956 LOC).
5. **Inventory `review_engine.py`** — `build_system_prompt` (`:58`/`:79-80`) and
   Area-Chair (`:443`). Classify MERGE_DUPLICATE / MOVE_TO_CONFIGURABLE_PROMPT vs.
   core `evaluator/peer_review.md`; record the overlap explicitly (target 040,
   requires sign-off).
6. **Inventory plot / vlm / transform / web inline prompts** (`plot:90/560/663`,
   `vlm:97/112`, `transform:834/867`, `web:465/483`): length, JSON-schema-embed
   flag, inputs. Classify EXTRACT_TEMPLATE (targets 040/041).
7. **Inventory the KEEP_INLINE set with rationale.**
   `ari-skill-idea/src/server.py` fallbacks (`:253, :293`; primary path
   `_VirSciPrompts` `:45-48`/`:245-250`) and
   `ari-skill-paper-re/src/_paperbench_bridge.py` vendored blocks (59 triple-quotes;
   upstream ref `:195`). Explicitly mark "do not extract — upstream parity".
8. **Inventory the rubric builders** (`rubric.py` 344 LOC / 6 triple-quotes;
   `rubric_template.py` 237 LOC / 9 triple-quotes) as
   MOVE_TO_CONFIGURABLE_PROMPT (scaffold-only extraction, dynamic injection stays).
9. **Sweep the two high-triple-quote files** (`_paperbench_bridge.py` 59,
   `evaluator/server.py` 31): classify every block; mark any un-individually-read
   block REVIEW_REQUIRED. State per-file totals are counts, not full audits.
10. **Record the findings list** (§6 items 1–8): storage-regime split, mechanism
    inconsistency, peer-review duplication, metric-extract overlap, vendored-string
    parity, unaudited-block caveat, missing checker (partial overlap with
    `report/scripts/check_prompt_snapshots.py`).
11. **Propose a stable `prompt_id` namespace** for inline prompts that 038/043 can
    adopt (e.g. `skill.<name>.<role>` → `skill.paper.global_coherence`), without
    creating the templates — naming only, as a recommendation.
12. **Write the artifact** to
    `docs/refactoring/reports/hardcoded_prompt_inventory.md` (+ optional `.json`
    twin for 043). Cross-link from this subtask and from
    `011_prompt_management_plan.md` in prose only (do not edit 011).
13. **Self-check counts.** Confirm 11 core templates, 11 core call sites, 5
    skill-local templates, and that every §5.4 cited line resolves to a real prompt
    (or is reclassified with a note). Confirm `git status` shows only the docs.

## 9. Files Expected to Change

036 changes **no runtime code**. The only files it creates/edits:

- `docs/refactoring/subtasks/036_inventory_hardcoded_prompts.md` — this planning
  document.
- **New (produced when the subtask is executed):**
  `docs/refactoring/reports/hardcoded_prompt_inventory.md` — the inventory artifact
  (and optionally `docs/refactoring/reports/hardcoded_prompt_inventory.json` for
  043). Create `docs/refactoring/reports/` if it does not already exist.

Explicitly **not** changed (read-only inputs): everything under
`ari-core/ari/prompts/`, `ari-skill-replicate/src/prompts/`,
`ari-skill-paper-re/src/prompts/`, every `ari-skill-*/src/server.py`,
`ari-skill-paper/src/review_engine.py`, `ari-skill-paper/src/rubric.py`,
`ari-skill-replicate/src/rubric_template.py`, `ari-core/ari/agent/loop.py`,
`ari-core/ari/orchestrator/*.py`, `ari-core/ari/evaluator/llm_evaluator.py`,
`ari-core/ari/pipeline/context_builder.py`, `ari-core/ari/viz/api_tools.py`,
`ari-core/tests/test_prompt_extraction.py`,
`report/scripts/check_prompt_snapshots.py`,
`docs/refactoring/011_prompt_management_plan.md`,
`docs/refactoring/007_subtask_index.md`, `scripts/**`, `.github/workflows/**`.

## 10. Files / APIs That Must Not Be Broken

Because 036 is read-only, "must not be broken" means the inventory must faithfully
record — never alter — these:

- **Core prompt templates + loader**: the 11 `.md` files and their sha256 pins in
  `test_prompt_extraction.py` (and `check_prompt_snapshots.py`). The inventory
  must not touch a byte, or the pins/snapshots break.
- **The `FilesystemPromptLoader` API** (`load`, `load_versioned`,
  `package_prompts_root`) and its re-exports via `ari.prompts` and
  `ari.protocols` — a documented core import surface consumed by 11 call sites.
- **MCP `ari-skill-*` tool contracts** — the inline prompts live inside skill
  `server.py` files that also define MCP tools; 036 must not edit those files.
- **Vendored upstream parity** — `_paperbench_bridge.py` PaperBench strings and the
  VirSci `utils/prompt.py` path in `idea/server.py` must remain byte-identical to
  upstream.
- Out-of-band but must not be incidentally touched: **CLI `ari`**,
  **`ari.public.*`**, **dashboard API endpoints/schema**, **checkpoint/output/config
  file formats**, **README/docs usage**, **scripts called by `.github/workflows`**.
  036 reads none of these into a mutation.

## 11. Compatibility Constraints

- 036 is **inventory only** — there is nothing to make compatible, because no
  runtime behavior changes. The compatibility obligation is *forward*: the artifact
  must be accurate enough that 039/040/041 can prove **byte-for-byte** prompt
  preservation against it (guarded by 042 snapshot tests).
- Must stay compatible with **P2 (determinism)**: the inventory records only static
  facts; producing it must add **no** LLM calls. Any recommended `prompt_id`
  scheme (§8.11) must yield machine-stable identifiers (no timestamps, no host
  state), mirroring how `load_versioned` computes a machine-stable `sha256[:12]`.
- Record contracts **as they are**, including the mechanism inconsistency (skills
  bypass the loader) and the two duplications. Recording them is not endorsing
  them; do **not** normalize prompt text or "pre-merge" duplicates in the inventory
  — that would hide the baseline 040/043 must enforce.
- No `pyproject.toml`, `requirements*.txt`, workflow, or config file is touched.
  There is **no** top-level `pyproject.toml` (the core manifest is
  `ari-core/pyproject.toml`, not touched). The prompt's "sonfigs" directory does
  **not exist** in this repo (the confusable trio is `ari-core/ari/config/` [code]
  vs. `ari-core/ari/configs/` [packaged defaults] vs. top-level `ari-core/config/`
  [rubric data]) — irrelevant to the prompt inventory and not referenced by it.
- "Deprecated" is reserved for external contracts; inline prompts are classified
  with the Phase-7 vocabulary (§7.2), never "deprecated".

## 12. Tests to Run

036 produces documentation/data, so the test surface is a **sanity/lint gate**,
not a behavior gate. From repo root (`/home/t-kotama/workplace/ARI`):

- `python -m compileall .` — confirms the read-only inspection did not accidentally
  corrupt any source (should be a no-op; nothing was edited). At minimum run
  `python -m compileall ari-core ari-skill-evaluator ari-skill-paper ari-skill-plot
  ari-skill-vlm ari-skill-transform ari-skill-web ari-skill-idea ari-skill-replicate
  ari-skill-paper-re` if a full-tree compileall is slow.
- `pytest -q` — full suite must still pass unchanged. In particular
  `ari-core/tests/test_prompt_extraction.py` (the sha256 pins for the 11 core
  templates) must stay green — a red run there means a template byte was touched,
  which is out of scope for 036.
- `ruff check .` — ruff is available (radon is not); expect no lint regressions
  since no `.py` changed.
- `python report/scripts/check_prompt_snapshots.py` — the Gate-10 byte-verifier for
  `ari-core/ari/prompts/**/*.md`; must pass unchanged (evidence the core templates
  were not modified).
- No frontend build is required (036 touches no frontend file); `npm test` /
  `npm run build` are **not** applicable to this subtask.
- Docs guards for the new report file: `python scripts/docs/check_doc_links.py` and
  `python scripts/docs/check_doc_sources.py` (the inventory is a tracked doc; its
  links/source references must resolve). Confirm `git status` shows only the two
  docs under `docs/refactoring/`.

## 13. Acceptance Criteria

1. `docs/refactoring/reports/hardcoded_prompt_inventory.md` exists and enumerates
   **every** prompt in the three regimes: the 11 core templates (with keys +
   call sites), the 5 skill-local templates (marked unversioned), and the inline
   prompts of §5.4 — with the §7.1 fields populated per row.
2. Each entry carries a Phase-7 classification (KEEP_INLINE / EXTRACT_TEMPLATE /
   MERGE_DUPLICATE / MOVE_TO_CONFIGURABLE_PROMPT / REVIEW_REQUIRED) and a
   `target_subtask` (038/039/040/041) as a downstream recommendation.
3. The mechanism inconsistency (skills bypass `FilesystemPromptLoader`) is recorded
   as a REVIEW_REQUIRED finding routed to 038, listing the 5 affected files.
4. The two duplications are recorded: `review_engine.py:58/:443` vs.
   `evaluator/peer_review.md` (MERGE_DUPLICATE), and `evaluator/server.py:191`
   `_METRIC_EXTRACT_SYS` vs. `evaluator/extract_metrics.md` (REVIEW_REQUIRED).
5. Vendored prompts (`_paperbench_bridge.py`, VirSci `idea/server.py` primary path)
   are marked KEEP_INLINE with an explicit upstream-parity rationale.
6. The unaudited-block caveat is stated: `_paperbench_bridge.py` (59) and
   `evaluator/server.py` (31) triple-quote totals are counts; blocks not
   individually read are REVIEW_REQUIRED, not asserted as prompts.
7. A self-check confirms 11 core templates, 11 core call sites, 5 skill-local
   templates, and every §5.4 cited line accounted for.
8. `python -m compileall .`, `pytest -q` (incl. `test_prompt_extraction.py`),
   `ruff check .`, and `report/scripts/check_prompt_snapshots.py` are clean; no
   runtime file diff exists (`git status` shows only the two docs).

## 14. Rollback Plan

Trivial and risk-free: 036 adds documentation only. Rollback is `git rm` / `git
revert` of the two doc files:

1. Delete `docs/refactoring/reports/hardcoded_prompt_inventory.md` (and the
   optional `.json` twin).
2. Revert this planning document if it was committed.

No runtime code, prompt text, template, format, migration, or workflow is touched,
so there is nothing to un-migrate and no way for rollback to affect any running LLM
call site. Downstream subtasks (037–044) that consumed the inventory simply lose
their baseline reference until it is regenerated.

## 15. Dependencies

- **Predecessors: none.** 036 is a **root inventory subtask** in the dependency
  graph (no `X -> 036` edge). It can start immediately and is one of the nine
  inventory subtasks (001, 002, 020, 036, 045, 053, 059, 060, 067) that MUST
  precede any runtime code change (`docs/refactoring/007_subtask_index.md:513`).
- **Dependents (036 gates all of them): 037, 038, 039, 040, 041, 042, 043, 044** —
  the graph edges are `036 -> 037/038/039/040/041/042/043/044`
  (`007_subtask_index.md:422-429`). Concretely: 037 (`define_prompt_template_policy`)
  codifies the `.md`+`str.format` facts this inventory records; 038
  (`introduce_prompt_registry_and_loader`) resolves the skill-loader mechanism
  inconsistency (§6.2); 039/040/041 (`extract_*_prompts`) externalize the inline
  prompts byte-identically per the inventory's classification/target_subtask; 042
  (`add_prompt_snapshot_tests`) turns extracted prompts into sha-pinned snapshots;
  043 (`add_prompt_checker_script`) builds `scripts/docs/check_prompts.py` from this
  ground truth (overlapping the existing `report/scripts/check_prompt_snapshots.py`,
  Gate 10); 044 (`add_prompt_version_tracking_to_run_metadata`) persists
  `load_versioned` hashes into run metadata (checkpoint-format adjacency → ADAPT).
- **Companion (not a graph edge):** `docs/refactoring/011_prompt_management_plan.md`
  (Phase-7 area plan) — 036 supplies the concrete inventory that 011's three axes
  (finish extraction / unify mechanism / add registry+versioning) rely on. No
  ordering constraint between the two planning docs themselves.

## 16. Risk Level

**Low.** **Runtime code change: No.** 036 only reads prompt files, skill/core
`server.py` sources, and call sites, and writes a documentation artifact. The sole
risk is *inaccuracy* — an incomplete or mis-classified inventory would let a
downstream extraction (039/040/041) either miss a prompt or break byte-parity on a
vendored string. Mitigations: (a) enumerate directly from the cited files/lines
rather than from memory; (b) cross-validate against `011_prompt_management_plan.md
§2` and against `test_prompt_extraction.py`'s existing pins; (c) mark every
un-individually-read triple-quote block REVIEW_REQUIRED instead of guessing; (d)
require the count self-check (§8.13) and a green `pytest -q` + snapshot check
(§12) as evidence the tree was left unmodified. No data, format, prompt text, or
public API is touched, so there is no runtime-regression risk.

## 17. Notes for Implementer

- **Source of truth is the string plus its call site.** For core templates, read
  the `.md` file *and* the consuming `.format(...)` (the 11 sites in §5.2) — the
  placeholder set only makes sense when you see both. For inline prompts, read the
  literal *and* the `messages=[{"role": "system", "content": ...}]` line so you
  record the LLM role and any JSON schema the prompt promises.
- **Do not touch a byte of any prompt.** `ari-core/tests/test_prompt_extraction.py`
  and `report/scripts/check_prompt_snapshots.py` pin the 11 core templates by
  sha256; a single edited character turns 036's "read-only" claim into a failing
  test. If you find yourself editing any file under `ari-core/ari/prompts/` or any
  `server.py`, you have left 036's scope — stop.
- **Vendored means hands-off.** `_paperbench_bridge.py` mirrors
  `vendor/paperbench/` (see the `:195` reference to
  `solvers/basicagent/prompts/templates.py`); `ari-skill-idea/src/server.py`
  primary path execs VirSci `utils/prompt.py` (`_VirSciPrompts`, `:45-48`). Mark
  both KEEP_INLINE and do not propose extracting them — that would fork upstream.
- **`review_engine.build_*_prompt` is rubric-parameterized**, not a static string:
  it injects `rubric.venue`, `rubric.domain`, dim/text lines (`:58-104`, `:105+`).
  Classify MOVE_TO_CONFIGURABLE_PROMPT (extract scaffold, keep injection) and note
  it is a MERGE_DUPLICATE candidate vs. core `evaluator/peer_review.md` — but it is
  **not byte-identical**, so consolidation needs human sign-off (040).
- **Counts are not audits.** Report the 59 (`_paperbench_bridge.py`) and 31
  (`evaluator/server.py`) triple-quote totals as counts; individually classify only
  the blocks you actually read, and mark the rest REVIEW_REQUIRED. Do not assert an
  un-inspected block is or isn't a prompt.
- **Propose keys, don't create them.** Suggest a `prompt_id` namespace (e.g.
  `skill.paper.global_coherence`, `skill.evaluator.semantic_system`) so 038/043 can
  adopt it, but do **not** add any template file or loader key — that is 038/039/
  040/041.
- **Keep the artifact under `docs/refactoring/reports/`** and cross-link from prose
  only; never edit `011_prompt_management_plan.md` or `007_subtask_index.md`. A
  `.json` twin is optional and only useful if 043's checker author prefers
  structured input; the `.md` remains the canonical narrative.
- **Stay read-only.** The entire value of 036 is that the baseline it records was
  captured from an *unmodified* tree; verify with `git status` before finishing.

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **036** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
