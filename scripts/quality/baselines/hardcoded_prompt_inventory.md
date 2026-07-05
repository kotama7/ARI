# Hardcoded-Prompt Inventory (Subtask 036)

> **Read-only inventory.** Produced by subtask
> `docs/refactoring/subtasks/036_inventory_hardcoded_prompts.md`. This document
> changes **no runtime code and no prompt bytes**. Every `classification` and
> `target_subtask` below is a **recommendation** for the downstream Phase-7
> extraction subtasks (037–044) — 036 resolves nothing.
>
> Repo root `/home/t-kotama/workplace/ARI`, branch `whole_refactoring`, planning
> date 2026-07-01. All rows grounded in `Read`/`grep` against the working tree.
> A machine-readable twin lives at
> `docs/refactoring/reports/hardcoded_prompt_inventory.json` (structured input
> for subtask 043's `check_prompts.py`).

## 0. How to read this

Prompts live in **three storage regimes** with **two loading mechanisms**:

1. **`core-loader`** — 11 `.md` templates under `ari-core/ari/prompts/`, loaded
   through `FilesystemPromptLoader` (`ari-core/ari/prompts/_loader.py`), each
   version-pinned by `ari-core/tests/test_prompt_extraction.py` and byte-verified
   by `report/scripts/check_prompt_snapshots.py` (Gate 10). **Already
   externalized** — classification `KEEP` (master vocabulary; not an inline
   verdict). These are the frozen baseline 039/040/041 must preserve
   byte-for-byte.
2. **`skill-read_text`** — 5 skill-local `.md` files loaded with ad-hoc
   `Path.read_text()`, so they carry **no** version hash and are invisible to
   Gate 10. Classification `REVIEW_REQUIRED` (mechanism inconsistency → 038).
3. **`inline`** — `"You are …"` system prompts and JSON-schema instruction blocks
   embedded directly in skill `server.py` files and helpers. Classified with the
   Phase-7 vocabulary below.

**Phase-7 classification vocabulary (§7.2 of the subtask):** `KEEP_INLINE`,
`EXTRACT_TEMPLATE`, `MERGE_DUPLICATE`, `MOVE_TO_CONFIGURABLE_PROMPT`,
`REVIEW_REQUIRED`. The already-externalized core templates carry the
master-vocabulary `KEEP` (they are *not* inline, so no inline verdict applies);
this is exactly what subtask §8.1 prescribes ("Classification KEEP (already
externalized)"). "Deprecated" is **not** used — no prompt here is an external
contract.

**`prompt_id` namespace (proposal only; §8.11).** Core keeps its existing loader
key (`agent/system`). Skill-local `.md` → `skill.<pkg>.<name>`. Inline →
`skill.<pkg>.<role>` (e.g. `skill.paper.global_coherence`). IDs are lowercase,
machine-stable, and carry no timestamp/host state, mirroring `load_versioned`'s
`sha256[:12]`. **036 proposes these names; it creates no template or loader key.**

---

## 1. Core externalized templates (`core-loader`, 11) — `KEEP`

Loader: `ari-core/ari/prompts/_loader.py` (`package_prompts_root` :16,
`FilesystemPromptLoader.load` :41-43, `load_versioned` :45-49). Re-exported via
`ari.prompts.__init__` and `ari.protocols.__init__:20`. All 11 keys are pinned by
sha256 in `test_prompt_extraction.py` → `versioned_today = yes`.

| prompt_id (loader key) | length | placeholders | call site (file:line, LLM role) | JSON schema |
| --- | --- | --- | --- | --- |
| `agent/system` | 13 L / 1321 B | `{extra}` `{memory_rules}` `{tool_desc}` | `ari/agent/loop.py:51-52` — system (`_SYSTEM_PROMPT_KEY` :46) | no |
| `evaluator/extract_metrics` | 16 L / 1992 B | none | `ari/evaluator/llm_evaluator.py:254-255` (`_load_base_system`, strips 1 trailing `\n`) — system | yes |
| `evaluator/peer_review` | **11 L** / 1049 B | `{axes_block}` | `ari/evaluator/llm_evaluator.py:412-413` (`.format(axes_block=…)`, trims 1 `\n`) — system | no |
| `orchestrator/bfts_expand` | 16 L / 1724 B | 15 (`{goal_line}` `{parent_*}` `{ancestors_block}` `{siblings_block}` `{idea_block}` `{diversity_block}` `{existing_block}` `{sci_note}` `{budget_note}` `{depth_note}` …) | `ari/orchestrator/bfts.py:743-744` (`.format(…)`) — expand | no |
| `orchestrator/bfts_expand_select` | 8 L / 423 B | `{candidates}` `{experiment_goal}` | `ari/orchestrator/bfts.py:553-559` — select; **config-swappable** via `BFTSConfig.expand_select_prompt` (`config/__init__.py:140`) | no |
| `orchestrator/bfts_select` | 15 L / 570 B | `{candidates}` `{experiment_goal}` `{memory_context}` | `ari/orchestrator/bfts.py:475-479` — select; **config-swappable** via `BFTSConfig.select_prompt` (`config/__init__.py:133`) | no |
| `orchestrator/lineage_decision` | 6 L / 1005 B | none | `ari/orchestrator/lineage_decision.py:291-293` — system | no |
| `orchestrator/root_idea_selector` | 6 L / 671 B | none | `ari/orchestrator/root_idea_selector.py:61-63` — system | no |
| `pipeline/keyword_librarian` | 0 L / 352 B (no trailing `\n`; populated) | none | `ari/pipeline/context_builder.py:116-117` — system | no |
| `viz/wizard_chat_goal` | 0 L / 607 B (no trailing `\n`; populated) | none | `ari/viz/api_tools.py:54-55` (strips 1 `\n`) — system | no |
| `viz/wizard_generate_config` | 0 L / 257 B (no trailing `\n`; populated) | `{goal}` | `ari/viz/api_tools.py:126-127` (`.format(goal=goal)`, strips 1 `\n`) — system | no |

**Count self-check:** 11 templates, 11 distinct lazy-import call sites — matches
the 11 keys pinned in `test_prompt_extraction.py` (`agent/system`,
`orchestrator/{lineage_decision,root_idea_selector,bfts_select,bfts_expand_select,bfts_expand}`,
`pipeline/keyword_librarian`, `evaluator/{extract_metrics,peer_review}`,
`viz/{wizard_chat_goal,wizard_generate_config}`). ✔

> Minor correction: subtask §5.1 lists `peer_review.md` as 12 L; actual `wc -l` =
> **11** (plan 011 §2.1 already says 11). Recorded as 11; do **not** touch the
> file — the sha256 pin depends on its exact bytes.

---

## 2. Skill-local externalized templates (`skill-read_text`, 5) — `REVIEW_REQUIRED` → 038

`versioned_today = no` for all five. Mechanism inconsistency (Finding 2): they
bypass `FilesystemPromptLoader`, so no hash and no Gate-10 coverage.

| prompt_id | length | placeholders | load site | classification / target |
| --- | --- | --- | --- | --- |
| `skill.replicate.skeleton` | 143 L / 7423 B | `{PAPER_TEXT}` `{TARGET_LEAVES}` `{VENUE_HINT}` | `ari-skill-replicate/src/generator.py:77` (`read_text()`; `PROMPTS_DIR` :26) | REVIEW_REQUIRED / 038 |
| `skill.replicate.subtree` | 115 L / 5083 B | `{PAPER_TEXT}` `{PARENT_REQUIREMENTS}` `{TARGET_LEAVES}` `{VENUE_HINT}` `{X}` | `generator.py:93` | REVIEW_REQUIRED / 038 |
| `skill.replicate.adversarial_reviewer` | 208 L / 11211 B | `{PAPER_TEXT}` `{TARGET_LEAVES}` `{X}` | `generator.py:64` | REVIEW_REQUIRED / 038 |
| `skill.replicate.rubric_audit` | 28 L / 1226 B | `{LEAF_JSON}` | `ari-skill-replicate/src/auditor.py:130` (`PROMPTS_DIR` :17) | REVIEW_REQUIRED / 038 |
| `skill.paper_re.replicator` | 154 L / 7258 B | `{PAPER_TEXT}` `{EXECUTION_PROFILE}` `{EXPECTED_ARTIFACTS}` `{GPU_LIST}` `{SLURM_JOB_NUM_NODES}` `{SLURM_NTASKS}` | **see correction below** | REVIEW_REQUIRED / 038 |

**CORRECTION — `replicator.md` load site (Finding 9).** Subtask §5.3 and plan 011
§2.3 state `replicator.md` is "loaded via `server.py:66` (`return p.read_text()`)".
Verified false: `ari-skill-paper-re/src/server.py:66` is `return p.read_text()`
inside the **paper-text extraction fallback** (`p` is the paper file), not a
prompt load. `grep -rn 'replicator\.md'` across `ari-skill-paper-re/src` +
`tests` finds **no** runtime `read_text()` of the template — only a docstring
reference (`_replicator_agent.py:10`, "mirroring `prompts/replicator.md`"). The
live replicator agent prompt comes from the **vendored** PaperBench templates
(`_replicator_agent.py:74` imports
`paperbench.solvers.basicagent.prompts.templates`). So `replicator.md` currently
appears **orphaned / documentation-mirror only**. This makes it a *two-part*
`REVIEW_REQUIRED` for 038: (a) the shared mechanism inconsistency, and (b) a human
decision — wire it through the unified loader, keep it as an explicit vendored
mirror, or retire it. **Do not** silently rewire or delete it in an inventory.

`ari-skill-paper-re/src/prompts/mpi_aggregate_skel.py` is a **code skeleton, not a
prompt** (copied to the sandbox at `_replicator_agent.py:607`) — excluded from the
registry.

**Count self-check:** 5 skill-local `.md` files (4 replicate + 1 paper-re); 4 are
wired via `read_text()`, 1 (`replicator.md`) is present but unwired. ✔

---

## 3. Still-inline prompts (`inline`)

### 3.1 Evaluator judge prompts (`ari-skill-evaluator/src/server.py`, 983 LOC)

| prompt_id | symbol | owner:line | consumed | length | JSON schema | classification / target |
| --- | --- | --- | --- | --- | --- | --- |
| `skill.evaluator.metric_extract` | `_METRIC_EXTRACT_SYS` | `:191` | `:217` (system) | ~13 L | yes (`metric_keyword`/`higher_is_better`/`expected_metrics`/`expected_params`) | **REVIEW_REQUIRED** / 040 — overlaps core `evaluator/extract_metrics.md` (Finding 5) |
| `skill.evaluator.semantic_system` | `_SEMANTIC_SYSTEM_PROMPT` | `:790` | `:903` (system) | ~18 L | yes (`scores`/`warnings`/`suggested_revisions`) | **EXTRACT_TEMPLATE** / 040 — highest-value evaluator target |

Neither uses `str.format`; the description / `user_prompt` is a separate user
message.

### 3.2 Paper skill prompts (`ari-skill-paper/src/server.py`, 2956 LOC — largest file)

| prompt_id | symbol / host | owner:line | length | JSON schema | classification / target |
| --- | --- | --- | --- | --- | --- |
| `skill.paper.academic_reviewer` | `system_prompt` (local) | `:542` | ~14 L | yes | EXTRACT_TEMPLATE / 041 (reviewer-family; flag vs peer-review consolidation) |
| `skill.paper.fill_in_writer` | `_system_prompt_a` (local) | `:1487` | ~41 L | no | EXTRACT_TEMPLATE / 041 |
| `skill.paper.latex_figure_inserter` | inline literal in `messages[]` | `:1638` | 1 L (role string) | no | EXTRACT_TEMPLATE / 041 — **trivial role string**; substantive text is the `_fig_inject_prompt` **user** message |
| `skill.paper.paper_writer` | `_system_prompt` (local) | `:1660` | ~6 L | no | EXTRACT_TEMPLATE / 041 |
| `skill.paper.global_coherence` | `system_prompt` (local) | `:2544` | ~17 L | yes (find/replace edit array) | **EXTRACT_TEMPLATE** / 041 — highest-value paper target: **5 hard-constraint rules** + JSON edit schema + `_paper_language_directive()` |
| `skill.paper.venue_drafting` | f-string (local) | `:353` | 1 L | no | REVIEW_REQUIRED / 041 (short f-string; cost > benefit) |
| `skill.paper.title_reviser` | f-string (local) | `:622` | 1 L | no | REVIEW_REQUIRED / 041 |
| `skill.paper.abstract_reviser` | f-string (local) | `:631` | 1 L | no | REVIEW_REQUIRED / 041 |
| `skill.paper.section_reviser` | f-string (local) | `:639` | 1 L | no | REVIEW_REQUIRED / 041 |

> Correction (Finding 10b): there is **no** module constant `_GLOBAL_COHERENCE`;
> `:2544` assigns a local `system_prompt`. The subtask's `_GLOBAL_COHERENCE` is a
> conceptual shorthand → proposed `prompt_id = skill.paper.global_coherence`.

### 3.3 `ari-skill-paper/src/review_engine.py` (489 LOC) — duplication (Finding 4)

| prompt_id | host | owner:line | length | JSON schema | classification / target |
| --- | --- | --- | --- | --- | --- |
| `skill.paper.review_system` | `build_system_prompt(rubric)` | `:58` (body `"You are a rigorous peer reviewer …"` `:79-80`) | builder (~35 L incl injected dim/text/decision lines) | yes | **MOVE_TO_CONFIGURABLE_PROMPT** + MERGE_DUPLICATE candidate / 040 |
| `skill.paper.area_chair` | `system` (local, meta-review) | `:443` | ~6 L | yes | **MERGE_DUPLICATE** / 040 |

Both overlap core `evaluator/peer_review.md` conceptually but are **not
byte-identical** (venue/rubric-parameterized: injects `rubric.venue`,
`rubric.domain`, `rubric.system_hint`, per-dimension/text/decision lines).
Consolidation needs human sign-off — record, do not resolve.

### 3.4 plot / vlm / transform / web inline prompts

| prompt_id | owner:line | length | JSON schema | classification / target |
| --- | --- | --- | --- | --- |
| `skill.plot.caption_writer` | `ari-skill-plot/src/server.py:90` (vision text block) | few L | no | EXTRACT_TEMPLATE / 041 |
| `skill.plot.viz_expert` | `plot/server.py:560` (`system_prompt`) | ~33 L | no | EXTRACT_TEMPLATE / 041 |
| `skill.plot.matplotlib_emitter` | `plot/server.py:663` (`simple_system`) | few L | yes (`{name,kind,code,caption}` array) | EXTRACT_TEMPLATE / 041 |
| `skill.vlm.figure_reviewer` | `ari-skill-vlm/src/server.py:97` | few L | no | EXTRACT_TEMPLATE / 040 |
| `skill.vlm.table_reviewer` | `vlm/server.py:112` (interps `context`, `source_type`) | few L | no | EXTRACT_TEMPLATE / 040 |
| `skill.transform.node_report_analyst` | `ari-skill-transform/src/server.py:834` (`analysis_prompt`) | medium | no | EXTRACT_TEMPLATE / 041 |
| `skill.transform.tree_analyst` | `transform/server.py:867` (`analysis_prompt`) | medium | no | EXTRACT_TEMPLATE / 041 |
| `skill.web.query_librarian` | `ari-skill-web/src/server.py:465` (`_QUERY_SYSTEM`) | ~15 L | no | EXTRACT_TEMPLATE / 040 |
| `skill.web.reference_selector` | `web/server.py:483` (`_SELECT_SYSTEM`) | ~7 L | no | EXTRACT_TEMPLATE / 040 |

> `target_subtask` splits are recommendations keyed to the phase-7 titles
> (040 = evaluator/LLM-judge family; 041 = pipeline/paper/generation family). 037
> may refine them. No inline prompt maps to 039 — the agent/BFTS prompts are all
> already externalized (§1).

### 3.5 KEEP_INLINE — vendored / fallback / trivial personas

| prompt_id | owner | vendored | rationale |
| --- | --- | --- | --- |
| `skill.idea.virsci_primary_path` | `ari-skill-idea/src/server.py:45-48` (`_VirSciPrompts` via `exec` of vendored `utils/prompt.py`), used `:245-250` | yes | Primary path execs vendored VirSci — externalizing forks upstream |
| `skill.idea.fallback_task` | `idea/server.py:252-266` (else branch; `prompt_task` `:253`, `prompt_response` embeds JSON) | no | Fallback only (primary is vendored); not worth churn |
| `skill.idea.agent_persona` | `idea/server.py:293` (`f"You are {role_desc} in a multi-agent scientific research team."`) | no | Trivial role string |
| `skill.idea.scientist_persona.virsci_runtime` | `idea/virsci_runtime.py:366` | yes | **Completeness sweep** (not in §5.4): VirSci-mirroring trivial persona |
| `skill.idea.author_persona.snapshot` | `idea/snapshot.py:367` | yes | **Completeness sweep** (not in §5.4): VirSci SciAgent persona builder |
| `skill.paper_re.paperbench_bridge_vendored` | `ari-skill-paper-re/src/_paperbench_bridge.py` (2376 LOC) | yes | Mirrors upstream PaperBench templates — **do not extract** |

### 3.6 Rubric builders — `MOVE_TO_CONFIGURABLE_PROMPT` (scaffold-only)

| prompt_id | owner | triple-quote lines | classification / target |
| --- | --- | --- | --- |
| `skill.paper.rubric_builders` | `ari-skill-paper/src/rubric.py` (344 LOC) | 6 | MOVE_TO_CONFIGURABLE_PROMPT / 041 |
| `skill.replicate.rubric_template_builders` | `ari-skill-replicate/src/rubric_template.py` (237 LOC) | 9 | MOVE_TO_CONFIGURABLE_PROMPT / 041 |

> **011-vs-036 divergence (Finding 11).** Plan 011 §5.x says these are "rubric
> builders, not prompt text — leave in place"; subtask 036 §8.8 says classify
> `MOVE_TO_CONFIGURABLE_PROMPT` (extract *static scaffold*, keep dynamic rubric
> injection inline). Both are recorded; 037/041 must reconcile before any move.

---

## 4. Two high-triple-quote files — counts, **not** audits (Finding 7)

Per-file totals are grep line-counts of `"""` occurrences, not per-block prompt
audits. Only the individually-cited lines below were read; **every block not
individually read is `REVIEW_REQUIRED`, not asserted to be (or not be) a prompt.**

- `ari-skill-paper-re/src/_paperbench_bridge.py` (2376 LOC): **59** lines contain
  `"""`. Individually read: upstream ref comment `:195`
  (`solvers/basicagent/prompts/templates.py`), `_VENDOR_BLACKLIST_LINE` browsing
  instruction `:944`. **KEEP_INLINE** (vendored parity). Remaining blocks
  `REVIEW_REQUIRED`.
- `ari-skill-evaluator/src/server.py` (983 LOC): **31** lines contain `"""`. Of
  these, the two prompts in §3.1 were read; the rest are function docstrings /
  helper strings not individually classified → `REVIEW_REQUIRED`.

---

## 5. Findings (subtask §6 items 1–8, plus corrections)

1. **Three storage regimes, two mechanisms** — core-loader (11, versioned) vs
   skill `read_text()` (5, unversioned) vs inline Python. This inventory is the
   first single baseline.
2. **Mechanism inconsistency → `REVIEW_REQUIRED` for 038.** The 5 skill-local
   `.md` prompts get no hash and are invisible to Gate 10
   (`report/scripts/check_prompt_snapshots.py` scans only
   `ari-core/ari/prompts/`). Affected files: the four `ari-skill-replicate/src/prompts/*.md`
   plus `ari-skill-paper-re/src/prompts/replicator.md`.
3. **High-value inline system prompts** — `_SEMANTIC_SYSTEM_PROMPT` (evaluator
   :790) and `skill.paper.global_coherence` (paper :2544, 5 hard rules + JSON edit
   schema) cannot be version-pinned/snapshot-guarded while inline.
4. **Peer-reviewer duplication** — `review_engine.py:58/:443` vs core
   `evaluator/peer_review.md` (MERGE_DUPLICATE, not byte-identical → 040 sign-off).
5. **Metric-extract overlap** — `evaluator/server.py:191` `_METRIC_EXTRACT_SYS` vs
   core `evaluator/extract_metrics.md` (REVIEW_REQUIRED; related, distinct scope).
6. **Vendored strings must not be forked** — `_paperbench_bridge.py` (PaperBench)
   and the idea VirSci primary path stay byte-identical to upstream (KEEP_INLINE).
7. **Counts are not audits** — the 59 / 31 triple-quote totals are counts;
   un-read blocks are REVIEW_REQUIRED (see §4).
8. **No inline-prompt checker** — `scripts/docs/check_prompts.py` **does not
   exist** (verified). Only `report/scripts/check_prompt_snapshots.py` (Gate 10,
   core-only). Subtask 043 builds the checker from this inventory; note the
   partial overlap with Gate 10 (do not duplicate its core-snapshot slice).
9. **CORRECTION — `replicator.md` is unwired** (see §2): the cited `server.py:66`
   reads the paper file, not the prompt; the template appears orphaned /
   mirror-only vs the vendored PaperBench templates that actually run.
10. **Minor corrections** — `peer_review.md` is 11 L (not 12); no `_GLOBAL_COHERENCE`
    constant exists (local `system_prompt` at :2544); `paper:1638` is a 1-line role
    string, not a full prompt.
11. **011-vs-036 rubric-builder divergence** — "leave in place" (011) vs
    `MOVE_TO_CONFIGURABLE_PROMPT` (036 §8.8); needs 037/041 reconciliation.

---

## 6. Self-check (subtask §8.13 / §13.7)

- **11 core templates** enumerated (§1) — matches the 11 sha256 pins in
  `test_prompt_extraction.py`. ✔
- **11 core call sites** — one per template, all lazy `from ari.prompts import
  FilesystemPromptLoader` (§1). ✔
- **5 skill-local templates** — 4 replicate (wired) + 1 paper-re (unwired
  correction). ✔
- **Every §5.4 cited line resolved** — evaluator `191/790`; paper
  `542/1487/1638/1660/2544` + revisers `353/622/631/639`; `review_engine`
  `58/443`; plot `90/560/663`; vlm `97/112`; transform `834/867`; web `465/483`;
  idea `253/293` (+ vendored primary `45-48/245-250`); `_paperbench_bridge.py`
  (59 counted, `195/944` read); rubric builders `rubric.py`/`rubric_template.py`.
  Two completeness extras beyond §5.4 (`idea/virsci_runtime.py:366`,
  `idea/snapshot.py:367`) are recorded KEEP_INLINE. ✔
- **`git status`** shows only the two new files under
  `docs/refactoring/reports/`; no runtime file diff. ✔ (verified at completion)

---

## 7. Downstream routing summary (recommendations only)

| target | consumes |
| --- | --- |
| **037** define_prompt_template_policy | the `.md` + `str.format` facts in §1; the 011-vs-036 rubric divergence (Finding 11) |
| **038** introduce_prompt_registry_and_loader | the mechanism inconsistency (§2, Finding 2) incl. the unwired `replicator.md` (Finding 9) |
| **039** extract_agent_and_bfts_prompts | nothing inline remains — agent/BFTS already externalized (§1) |
| **040** extract_evaluator_and_llm_judge_prompts | `skill.evaluator.*`, `skill.paper.review_system`, `skill.paper.area_chair`, `skill.vlm.*`, `skill.web.*` |
| **041** extract_pipeline_and_paper_generation_prompts | `skill.paper.*` (server), `skill.plot.*`, `skill.transform.*`, rubric builders |
| **042** add_prompt_snapshot_tests | every EXTRACT_TEMPLATE row (byte-identical guard) |
| **043** add_prompt_checker_script | the JSON twin as ground truth; overlaps Gate 10 core slice |
| **044** add_prompt_version_tracking_to_run_metadata | `load_versioned` hashes for all managed prompts |
