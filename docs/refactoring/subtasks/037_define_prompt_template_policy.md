# Subtask 037: Define Prompt Template Policy

- **Phase:** Phase 7 — Prompt Management
- **Subtask ID:** 037
- **Title (index):** `define_prompt_template_policy`
- **Status:** PLANNING ONLY (this subtask produces a policy document; it does **not** modify runtime code, prompt text, templates, configs, workflows, or directory names)
- **Planning date:** 2026-07-01
- **Repo:** `/home/t-kotama/workplace/ARI` (git branch `main`; `ari-core` version `0.9.0`, from `ari-core/pyproject.toml`)
- **Author role:** senior software architect
- **Runtime code change:** **No** (see Section 16)
- **Depends on:** subtask **036** (`inventory_hardcoded_prompts`)
- **Hands off to:** subtasks **038** (`introduce_prompt_registry_and_loader`), **039/040/041** (`extract_*_prompts`), **042** (`add_prompt_snapshot_tests`), **043** (`add_prompt_checker_script`), **044** (`add_prompt_version_tracking_to_run_metadata`)
- **Classification vocabulary:** `KEEP` / `ADAPT` / `MERGE` / `MOVE_TO_LEGACY` / `DELETE_CANDIDATE` / `REVIEW_REQUIRED`. For prompts specifically, the specialized verdicts `KEEP_INLINE` / `EXTRACT_TEMPLATE` / `MERGE_DUPLICATE` / `MOVE_TO_CONFIGURABLE_PROMPT` / `REVIEW_REQUIRED` are used. The word "deprecated" is reserved for external contracts only (public API, CLI, MCP, dashboard API, documented import paths, `ari-skill-*` stable interfaces).

> **Hard scope note.** This document defines *policy* — the canonical, normative rules that govern how ARI prompt templates are formatted, located, named, loaded, versioned, tested, and secured. It proposes **nothing** that changes any `.md` template, `.py` call site, config, workflow, or directory *today*. Every "canonical rule" named here is a constraint that the later implementation subtasks (038–044) must satisfy; it is **not** an instruction to edit or move any file now. The only artifact produced by subtask 037 is this `.md` file.

---

## 1. Goal

Produce a single, authoritative **Prompt Template Policy** that the downstream prompt-management subtasks (038–044) implement against without re-litigating design questions. The policy must fix, as normative rules:

1. **Template format.** Ratify that ARI prompt templates are `.md` files filled with Python `str.format(...)` using single-brace `{name}` placeholders — **not** Jinja2 (`.md.j2`) — and state precisely the narrow condition under which `.md.j2` may be introduced later.
2. **Location / directory convention.** Fix the two-tier layout: core prompts under `ari-core/ari/prompts/<category>/<name>.md`; skill prompts under `ari-skill-*/src/prompts/<name>.md`. Forbid centralizing skill prompts into core (would invert the `ari-skill-* → ari-core` dependency direction).
3. **Key / naming convention.** Fix the registry-key grammar (`<category>/<name>`, lowercase, `^[a-z0-9_]+(/[a-z0-9_]+)*$`) so keys are safe to join into a filesystem path.
4. **Loading-mechanism convention.** Declare the `PromptLoader` Protocol (`load` / `load_versioned`) the single loading contract that both core and skills must conform to, closing the current split where skills bypass the loader with ad-hoc `Path.read_text()`.
5. **Ownership.** Fix who may edit which prompt, keyed to the contract surface it touches, and mark vendored prompts `KEEP_INLINE`.
6. **Versioning / provenance.** Fix the field set and hashing scheme (`sha256[:12]`, machine-stable, no timestamps) so a run can be traced to an exact template revision, and fix the manual `prompt_version`-bump discipline.
7. **Snapshot testing.** Fix that every ARI-authored managed template must be byte-pinned, and reconcile the **two** snapshot mechanisms that already exist (`ari-core/tests/test_prompt_extraction.py` and Gate 10 `report/scripts/check_prompt_snapshots.py`).
8. **Security boundary.** Fix the key-sanitization rule and the user-free-text isolation rule.

Success = a fresh coding session opening subtask 038 (or 039/040/041/042/043/044) can read this one document and know, without further design work, the exact conventions every extracted or newly-created prompt must satisfy.

## 2. Background

ARI is **not** a green-field prompt-management project. A partial externalization layer already exists and is the foundation this policy ratifies and extends:

- **Loader.** `ari-core/ari/prompts/_loader.py` (~49 lines) defines a `PromptLoader` `Protocol` and a default `FilesystemPromptLoader`. `load(key)` resolves `{base}/{key}.md` (base defaults to `package_prompts_root()`); `load_versioned(key)` returns `(text, sha256(text)[:12])`. `ari-core/ari/prompts/__init__.py` (335 B) re-exports `FilesystemPromptLoader, PromptLoader, package_prompts_root`, and `PromptLoader` is additionally re-exported at `ari-core/ari/protocols/__init__.py:20` (`__all__` includes it).
- **11 externalized core templates** under `ari-core/ari/prompts/` plus 5 per-directory `README.md` files, spanning `agent/`, `evaluator/`, `orchestrator/`, `pipeline/`, `viz/`.
- **A snapshot regression test** already pins every one of those 11 templates: `ari-core/tests/test_prompt_extraction.py` (107 lines) hardcodes the full `sha256` of each template body in `_EXPECTED_HASHES` (11 rows), plus a `.format(...)` round-trip test and a `load_versioned` determinism test.
- **A second, report-side snapshot gate** exists: Gate 10 (`report/scripts/check_prompt_snapshots.py`) verifies that `report/shared/appendix/prompts/**/*.md` snapshots equal the bytes of the corresponding `ari-core/ari/prompts/**` source (regenerated by `report/scripts/snapshot_prompts.py`).
- **A config-swappable seed** already exists: `BFTSConfig.select_prompt` (`ari-core/ari/config/__init__.py:133`) and `BFTSConfig.expand_select_prompt` (`:140`) let a config file point the loader at an alternative `.md` key, provided it accepts the same documented placeholders.

The prior analysis document `docs/refactoring/011_prompt_management_plan.md` (~33 KB) already surveyed the landscape and drafted candidate policy text (its §6 template-location, §8 versioning, §9 rendering/validation, §10 snapshot, §11 security). **Subtask 037's job is to distill that analysis into a normative, decision-only policy** the implementer subtasks cite as the single source of truth. Subtask 036 supplies the exhaustive inline-prompt census that feeds the per-prompt classification in Section 7.5.

> **Numbering caveat for the implementer.** `docs/refactoring/011_prompt_management_plan.md` uses an *internal* subtask numbering in its §13 table (there, `037` = "PromptRegistry scaffold", `038` = "provenance record", etc.). The **canonical** mapping is `docs/refactoring/007_subtask_index.md` (Phase 7 section, lines ~296–314) and the master dependency graph, which is what this document and the DEPENDENCY GRAPH follow: `037 = define_prompt_template_policy` (policy doc, no runtime code), `038 = introduce_prompt_registry_and_loader`, `039/040/041 = extract_*_prompts`, `042 = add_prompt_snapshot_tests`, `043 = add_prompt_checker_script`, `044 = add_prompt_version_tracking_to_run_metadata`. Where 011 and 007 disagree on numbers, **007 wins.**

## 3. Scope

**In scope (this subtask writes only this `.md`):**

- Ratify the template **format** decision (`.md` + `str.format`; not `.j2`) with the narrow `.j2` escape hatch defined.
- Fix the **location**, **key/naming**, **loading**, **ownership**, **versioning/provenance**, **snapshot-test**, and **security** rules.
- Provide the per-category **classification policy** (how to apply `KEEP_INLINE` / `EXTRACT_TEMPLATE` / `MERGE_DUPLICATE` / `MOVE_TO_CONFIGURABLE_PROMPT` / `REVIEW_REQUIRED`), and enumerate the concrete prompt sites the policy governs (drawn from the verified inventory) so downstream subtasks have an actionable target list.
- Enumerate the contracts the policy must preserve (Section 10/11).

**Out of scope (belongs to downstream subtasks):**

- The exhaustive line-level census of every triple-quoted string in the large skill files → **036**.
- Writing `_registry.py` / a manifest / the `PromptRecord` dataclass and wiring a unified loader → **038**.
- Moving any inline prompt into a `.md` file → **039 / 040 / 041**.
- Adding snapshot-test rows or a rendered-prompt fixture test → **042**.
- Writing `scripts/docs/check_prompts.py` → **043**.
- Persisting prompt hash/version into run metadata / checkpoint → **044**.

## 4. Non-Goals

- **No network prompt service, no prompt DSL, no per-user prompt overrides.** The policy stays filesystem-local and deterministic (Design principle **P2**: no added LLM calls, identical hashes across machines).
- **No migration to Jinja2 in this phase** (see Section 7.1). The 11 existing `.md` templates and their pinned hashes stay byte-identical.
- **No touching any `config*` directory.** The prompt layer (`ari-core/ari/prompts/`) is governed separately from the confusable trio `ari-core/ari/config/` (code), `ari-core/ari/configs/` (packaged data), and top-level `ari-core/config/` (rubric YAML). There is **no `sonfigs/`** directory anywhere in the repo (confirmed absent; the term is a hypothesized typo — state this where the trio is discussed).
- **No hardening of vendored prompt text.** PaperBench-bridge and VirSci prompts stay verbatim to preserve upstream parity.
- **No change to any prompt wording.** Even for prompts later marked `EXTRACT_TEMPLATE`, the extraction (in 039–041) must be byte-identical; 037 only sets the rule.

## 5. Current Files / Directories to Inspect

All paths verified present on 2026-07-01. Line/byte counts as noted.

**Core prompt layer (`ari-core/ari/prompts/`):**

| Path | Role | Size |
| --- | --- | --- |
| `ari-core/ari/prompts/_loader.py` | `PromptLoader` Protocol + `FilesystemPromptLoader` + `package_prompts_root()` | ~49 L |
| `ari-core/ari/prompts/__init__.py` | re-exports loader symbols | 335 B |
| `ari-core/ari/prompts/README.md` | layer overview; documents `str.format` single-brace convention | ~38 L |
| `ari-core/ari/prompts/agent/system.md` | agent ReAct system prompt (`agent/system`) | 13 L |
| `ari-core/ari/prompts/evaluator/extract_metrics.md` | metric extraction (`evaluator/extract_metrics`) | 16 L |
| `ari-core/ari/prompts/evaluator/peer_review.md` | rubric peer review (`evaluator/peer_review`) | 11 L |
| `ari-core/ari/prompts/orchestrator/bfts_expand.md` | leaf-expansion | 16 L |
| `ari-core/ari/prompts/orchestrator/bfts_expand_select.md` | combined expand+select | 8 L |
| `ari-core/ari/prompts/orchestrator/bfts_select.md` | next-node selection | 15 L |
| `ari-core/ari/prompts/orchestrator/lineage_decision.md` | continue/switch/fanout/terminate | 6 L |
| `ari-core/ari/prompts/orchestrator/root_idea_selector.md` | run-start root pick | 6 L |
| `ari-core/ari/prompts/pipeline/keyword_librarian.md` | keyword extraction | 352 B (no trailing newline — populated, not empty) |
| `ari-core/ari/prompts/viz/wizard_chat_goal.md` | wizard goal chat | 607 B |
| `ari-core/ari/prompts/viz/wizard_generate_config.md` | wizard config generation (`{goal}` placeholder) | 257 B |
| `.../agent/README.md`, `.../evaluator/README.md`, `.../orchestrator/README.md`, `.../pipeline/README.md`, `.../viz/README.md` | 5 per-directory indexes | — |

**Core load sites (11 files, all lazy in-function `from ari.prompts import FilesystemPromptLoader`):**
`ari-core/ari/agent/loop.py:51`, `ari-core/ari/evaluator/llm_evaluator.py:255,413`, `ari-core/ari/orchestrator/bfts.py:475,553,743`, `ari-core/ari/orchestrator/lineage_decision.py:293`, `ari-core/ari/orchestrator/root_idea_selector.py:63`, `ari-core/ari/pipeline/context_builder.py:117`, `ari-core/ari/viz/api_tools.py:55,127`.

**Config-swappable keys:** `ari-core/ari/config/__init__.py:133` (`select_prompt`, accepts `{experiment_goal}`, `{memory_context}`, `{candidates}`), `:140` (`expand_select_prompt`, accepts `{experiment_goal}`, `{candidates}`).

**Protocol re-export:** `ari-core/ari/protocols/__init__.py:20` (`from ari.prompts._loader import PromptLoader`).

**Snapshot / test surfaces:**
- `ari-core/tests/test_prompt_extraction.py` (107 L) — `_EXPECTED_HASHES` (11 rows, full sha256); `load_versioned` sole caller at `:103`.
- `report/scripts/check_prompt_snapshots.py` (Gate 10) + `report/scripts/snapshot_prompts.py` — appendix snapshots of `ari-core/ari/prompts/**` into `report/shared/appendix/prompts/{agent,evaluator,orchestrator,pipeline,viz}/`.

**Skill-local externalized templates (bypass the core loader — REVIEW_REQUIRED for mechanism):**
- `ari-skill-replicate/src/prompts/skeleton.md` (143 L), `subtree.md` (115 L), `adversarial_reviewer.md` (208 L), `rubric_audit.md` (28 L) — loaded via `Path.read_text()` in `ari-skill-replicate/src/generator.py:26,64,77,93` and `ari-skill-replicate/src/auditor.py:17,130`.
- `ari-skill-paper-re/src/prompts/replicator.md` (154 L) — loaded via `ari-skill-paper-re/src/server.py:66`. (Sibling `ari-skill-paper-re/src/prompts/mpi_aggregate_skel.py` is a **code skeleton, not a prompt** — must not enter the registry.)

**Still-inline prompt sites (governed target list; census completed by 036):**
- `ari-skill-evaluator/src/server.py:191` (`_METRIC_EXTRACT_SYS`), `:790` (`_SEMANTIC_SYSTEM_PROMPT`).
- `ari-skill-paper/src/server.py:542, 1487, 1638, 1660, 2544`; `ari-skill-paper/src/review_engine.py:58, 105, 443`.
- `ari-skill-plot/src/server.py:90, 560, 663`; `ari-skill-vlm/src/server.py:97, 112`; `ari-skill-transform/src/server.py:834, 867`; `ari-skill-web/src/server.py:465, 483`.
- `ari-skill-idea/src/server.py:245-266` (inline fallback; primary path execs vendored VirSci `utils/prompt.py`, `server.py:42-48`).
- `ari-skill-paper-re/src/_paperbench_bridge.py` (2376 L, 59 triple-quotes — **vendored**, `KEEP_INLINE`).

**Prior planning docs to reconcile (read, do not edit):** `docs/refactoring/011_prompt_management_plan.md`, `docs/refactoring/007_subtask_index.md` (Phase 7 section).

## 6. Current Problems

Repository-specific problems the policy must resolve (grounded; all verified 2026-07-01):

1. **No provenance on the majority of LLM calls.** `load_versioned()` computes an `sha256[:12]` but its **only** caller is `test_prompt_extraction.py:103`. In production, `bfts.py`, `loop.py`, `llm_evaluator.py`, and every skill call `load()` (or `read_text()`), so **no prompt hash is recorded in any checkpoint or run record**. `grep` across `ari-core` for `template_hash`, `prompt_version`, `rendered_prompt`, `prompt_registry` returns **zero** hits — none of the provenance vocabulary exists yet.

2. **Two divergent loading mechanisms.** Core uses `FilesystemPromptLoader` (hash-capable). `ari-skill-replicate` and `ari-skill-paper-re` use `Path.read_text()` — no hashing, no config-swap, no snapshot coverage. Edits to `skeleton.md` (143 L) or `replicator.md` (154 L) are invisible to the regression harness. `REVIEW_REQUIRED`.

3. **High-value prompts buried in the largest files.** The biggest system prompts live in `ari-skill-paper/src/server.py` (2956 L, 5 inline "You are …" prompts) and `ari-skill-evaluator/src/server.py` (983 L). A wording change is indistinguishable from a code change in the diff.

4. **Conceptual duplication across core and skills.** `ari-skill-paper/src/review_engine.py:58` (venue peer-reviewer) overlaps `evaluator/peer_review.md`; `ari-skill-evaluator/src/server.py:191` (`_METRIC_EXTRACT_SYS`) overlaps `evaluator/extract_metrics.md`. Related but not byte-identical → silent drift. `MERGE_DUPLICATE` / `REVIEW_REQUIRED`.

5. **Unguarded key resolution + user-driven rendering.** `FilesystemPromptLoader.load` (`_loader.py:42`) does `self._base / f"{key}.md"` with **no key sanitization**. Because keys can come from config (`BFTSConfig.select_prompt`), a crafted key could traverse outside the prompts root. Separately, wizard prompts render free-text user goals via `str.format`. Neither is a Python format-string vulnerability today (templates are trusted; user text is a *value*), but both are validation gaps.

6. **No versioning scheme.** Templates carry no `prompt_version`. The snapshot tests detect *any* byte change (hash mismatch → fail) but there is no notion of an *intentional* bump, no per-prompt changelog, and no way to say "this run used `peer_review` v2".

7. **Two snapshot mechanisms, no stated relationship.** `test_prompt_extraction.py` (pytest, full sha256) and Gate 10 (`report/scripts/check_prompt_snapshots.py`, appendix parity) both hash the same `ari-core/ari/prompts/**` files but are unaware of each other, and neither covers the skill-local templates. The policy must state which is authoritative for which purpose.

## 7. Proposed Design / Policy

The following are **normative rules** (RULE-*). Downstream subtasks 038–044 must satisfy every applicable rule.

### 7.1 Template format — `.md` + `str.format`

- **RULE-FMT-1.** ARI prompt templates are **`.md` files rendered with Python `str.format(**vars)`**, using **single-brace `{name}`** placeholders. This is ratified as the standing convention, matching every current core call site (e.g. `bfts.py:479`, `llm_evaluator.py:413`) and the documented convention in `ari-core/ari/prompts/README.md`.
- **RULE-FMT-2.** Do **not** migrate any existing `.md` template to Jinja2 (`.md.j2`) in Phase 7. Migrating would require rewriting all 11 templates and every `.format(...)` call site simultaneously and would break the 11 pinned hashes in `test_prompt_extraction.py`. `str.format` covers all present needs (named substitution); no template in the inventory needs loops/conditionals/includes/filters.
- **RULE-FMT-3 (`.j2` escape hatch).** `.md.j2` may be introduced **only** for a template that genuinely needs control flow, and **only** the `MOVE_TO_CONFIGURABLE_PROMPT` rubric builders (`ari-skill-paper/src/review_engine.py` — per-dimension lines, optional `system_hint`) are candidates. If adopted (deferred to subtask 042's follow-on, not 037), the loader selects the render engine by suffix (`.md` → `str.format`, `.md.j2` → Jinja2 with `StrictUndefined`), the 11 existing `.md` files stay untouched, and the provenance record (7.5) must record which engine was used.

### 7.2 Location / directory convention

- **RULE-LOC-1.** Core prompts live at `ari-core/ari/prompts/<category>/<name>.md`, where `<category>` mirrors the consuming module (`agent`, `evaluator`, `orchestrator`, `pipeline`, `viz`). New extracted core prompts follow the same scheme.
- **RULE-LOC-2.** Skill prompts live at `ari-skill-<skill>/src/prompts/<name>.md`. This directory already exists for `replicate` and `paper-re`; extend it (not core) for skills that gain extracted templates (`evaluator`, `paper`, `plot`, `vlm`, `transform`, `web`).
- **RULE-LOC-3.** A skill must **never** read from `ari-core/ari/prompts/` and core must **never** read from a skill's `src/prompts/`. Centralizing skill prompts into core would create an `ari-core → ari-skill` coupling in the wrong direction and break MCP-package self-containment. If a skill needs a core prompt, it receives the **rendered string** across the MCP boundary, never the template path.
- **RULE-LOC-4.** Each prompt directory keeps its `README.md` index (the existing 5 core indexes + skill indexes) as the co-located per-prompt documentation.

### 7.3 Key / naming convention

- **RULE-KEY-1.** A prompt key is `<category>/<name>` (may nest: `a/b/c`), lowercase, matching `^[a-z0-9_]+(/[a-z0-9_]+)*$`. The `.md` (or `.md.j2`) suffix is **not** part of the key.
- **RULE-KEY-2.** Keys are code/config identifiers, never user input. Config-supplied keys (`BFTSConfig.select_prompt`, `expand_select_prompt`) must match RULE-KEY-1 and resolve to a path **inside** `package_prompts_root()`. Before enforcing the regex, subtask 038 must confirm no legitimate existing key uses characters outside the grammar (`REVIEW_REQUIRED`).

### 7.4 Loading-mechanism convention

- **RULE-LOAD-1.** The `PromptLoader` Protocol (`load(key) -> str`, `load_versioned(key, version=None) -> (text, version_id)`) in `ari-core/ari/prompts/_loader.py` is the single loading contract. `FilesystemPromptLoader` is the default, filesystem-local implementation; it stays test-swappable (the Protocol exists precisely so tests can inject a loader).
- **RULE-LOAD-2.** Skills must **not** import a core loader/registry object (would invert the dependency). Instead each skill adopts the **same** `load_versioned` return contract — `(text, sha256(text)[:12])` — via a small per-skill helper or a shared MCP-surfaced utility. The exact sharing mechanism is `REVIEW_REQUIRED`, decided in subtask **040** (unify skill loading), not here. This closes Problem 2 without a new import edge.
- **RULE-LOAD-3.** The rendered-prompt hash a skill computes is returned to `ari-core` **through the existing MCP tool-result payload as an additive field**, so `ari-core` records it in run provenance without importing skill code. Additive only — no breaking change to any MCP tool contract.

### 7.5 Versioning / provenance

- **RULE-VER-1 (field set).** A managed prompt call should be able to emit a provenance record with these fields. **None of these symbols exist in the codebase today** (confirmed by `grep`); they are introduced by subtasks 038/044:

  | Field | Meaning | Source |
  | --- | --- | --- |
  | `prompt_name` | registry key, e.g. `orchestrator/bfts_select` | registry |
  | `prompt_version` | human-assigned semantic version of the template | registry manifest |
  | `template_hash` | `sha256[:12]` of the raw template body | `load_versioned()` (exists) |
  | `rendered_prompt_hash` | `sha256[:12]` of the post-`format` string actually sent | registry `render()` (new, 038) |
  | `prompt_registry_version` | version of the manifest as a whole | registry manifest |
  | `render_engine` | `str.format` or `jinja2` (per RULE-FMT-3) | registry manifest |
  | `model_name` | model the rendered prompt was sent to | LLM call site (`ari.public.llm`) |
  | `run_id` | the run this call belongs to | run/checkpoint context |
  | `node_id` | BFTS node / pipeline node served | orchestrator/pipeline context |

- **RULE-VER-2 (hashing).** Hashing is `hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]` — the exact scheme already in `_loader.py:48`. It is machine-stable (unlike a git SHA). No timestamps or host info may enter any hashed content (P2 determinism).
- **RULE-VER-3 (bump discipline).** `template_hash` changes **automatically** on any byte change (caught by the snapshot test). `prompt_version` is bumped **manually** to signal an *intentional* behavioral change; the snapshot test's expected hash is updated in the **same commit** (mirroring the existing `v0.7.2` annotations in `test_prompt_extraction.py:40,50`). A one-line per-prompt changelog lives in the registry manifest or the category `README.md`, co-located with the prompt.

### 7.6 Snapshot testing

- **RULE-SNAP-1.** Every ARI-authored managed template (core **and** extracted skill templates) must be byte-pinned. `ari-core/tests/test_prompt_extraction.py` is the **authoritative** byte-identity gate for core templates; skill templates are pinned in **each skill's own** test suite (keeps packages self-contained). This is the safety net that makes every extraction PR (039–041) byte-verifiable.
- **RULE-SNAP-2 (relationship to Gate 10).** `report/scripts/check_prompt_snapshots.py` (Gate 10) is a **report-build** gate that verifies the LaTeX/HTML appendix (`report/shared/appendix/prompts/**`) still mirrors `ari-core/ari/prompts/**`. It is complementary, not a substitute: Gate 10 protects the *published* copy; `test_prompt_extraction.py` protects the *shipped* template. When a template body changes intentionally, **both** must be regenerated/updated (Gate 10 via `report/scripts/snapshot_prompts.py`). Gate 10 is invoked from the report build tooling, **not** from any of the 5 `.github/workflows/*.yml` (confirmed: `grep` of `.github/workflows/` for `check_prompt_snapshots` returns no hits).
- **RULE-SNAP-3 (rendered fixture, deferred to 042).** In addition to the raw-template hash, a rendered-prompt fixture test (render each template with a canned variable set, assert `rendered_prompt_hash`) should be added so a change to a `.format(...)` call site — not just the template — is also caught.

### 7.7 Security boundary

- **RULE-SEC-1 (key sanitization).** The registry/loader boundary must validate that a resolved key matches RULE-KEY-1 and that the resolved path stays within `package_prompts_root()` (closes the `_loader.py:42` traversal gap, reachable via config-swappable keys).
- **RULE-SEC-2 (user-text isolation).** User free-text (wizard goals rendered at `api_tools.py:55,127`; `{experiment_goal}` in BFTS templates) is confined to clearly named placeholders and passed **only** as `str.format` *arguments*. Never build a template string from user input; never `str.format` a user-provided template; never let user text choose a `prompt_name`. This is a prompt-injection surface at the LLM level, not a Python format-string vulnerability — but the isolation rule keeps it that way.
- **RULE-SEC-3 (vendored).** Vendored prompt text (`_paperbench_bridge.py`, VirSci) keeps its upstream browsing/tool instructions verbatim; its injection boundary is governed by the vendored solver. Do **not** "harden" vendored text — that forks upstream.

### 7.8 Ownership + classification policy

- **RULE-OWN-1 (ownership).**

  | Category | Owner boundary | Storage |
  | --- | --- | --- |
  | Agent / orchestration / pipeline / evaluator **core** prompts | ari-core maintainers | `ari-core/ari/prompts/**` |
  | Wizard / dashboard prompts (user-input-facing, review under 7.7) | ari-core maintainers (viz) | `ari-core/ari/prompts/viz/**` |
  | Skill-authored generation prompts (non-vendored) | owning `ari-skill-*` package | `ari-skill-*/src/prompts/**` |
  | Vendored prompts (PaperBench bridge, VirSci) | **upstream** — mirror only | in place, `KEEP_INLINE` |

- **RULE-CLS-1 (classification verdicts).** Apply these verdicts (the census in 036 supplies the exhaustive per-string list; the target sites in Section 5 are the confirmed starting set):
  - **`EXTRACT_TEMPLATE`** (substantial, static, ARI-authored → move to `.md` under the owning package): `ari-skill-evaluator/src/server.py:790` (`_SEMANTIC_SYSTEM_PROMPT`, ~18 L judge rubric + JSON schema — strongest single target), `:191` (`_METRIC_EXTRACT_SYS`, ~11 L); `ari-skill-paper/src/server.py:1487, 1638, 1660, 2544`; `ari-skill-plot/src/server.py:90, 560, 663`; `ari-skill-vlm/src/server.py:97, 112`; `ari-skill-transform/src/server.py:834, 867`; `ari-skill-web/src/server.py:465, 483`.
  - **`MOVE_TO_CONFIGURABLE_PROMPT`** (rubric/venue-parameterized — extract static scaffold to a template, keep dynamic injection as a Python builder): `ari-skill-paper/src/review_engine.py:58` (`build_system_prompt`), `:105` (`build_user_prompt`). `ari-skill-paper/src/rubric.py` (344 L) and `ari-skill-replicate/src/rubric_template.py` (237 L) are **rubric builders, not prompt text** — leave in place. Precedent: `BFTSConfig.select_prompt` / `expand_select_prompt`.
  - **`MERGE_DUPLICATE` / `REVIEW_REQUIRED`** (overlapping concepts, not byte-identical — human adjudication in 043 before any consolidation): `review_engine.py:58/:443` vs `evaluator/peer_review.md`; `ari-skill-evaluator/src/server.py:191` vs `evaluator/extract_metrics.md`.
  - **`KEEP_INLINE`** (vendored or fallback-only — extraction harms upstream parity or is not worth the churn): `ari-skill-idea/src/server.py:245-266` (fallback; primary path uses vendored VirSci `utils/prompt.py`); `ari-skill-paper-re/src/_paperbench_bridge.py` (2376 L vendored PaperBench); short f-string one-liners such as `ari-skill-paper/src/server.py:353, 622, 631, 639` (extraction cost > benefit).
  - **`REVIEW_REQUIRED` (mechanism)**: the already-externalized skill-local `.md` prompts (`ari-skill-replicate/src/prompts/*`, `ari-skill-paper-re/src/prompts/*`) — externalized but bypass the loader; decision to route through a shared `load_versioned` contract belongs to subtask 040 (RULE-LOAD-2).

## 8. Concrete Work Items

This subtask writes **one** document. The work items are the sections of that document.

1. Write the policy `.md` at the target path (Section 9) using the standard 17-section subtask template — this file.
2. Ratify RULE-FMT-1/2/3 (Section 7.1) with the grounded rationale and the `.j2` escape-hatch condition.
3. Fix RULE-LOC-1..4, RULE-KEY-1..2, RULE-LOAD-1..3 (Sections 7.2–7.4) with the exact directory/key grammar.
4. Fix the provenance field set + hashing + bump discipline (RULE-VER-1..3, Section 7.5), including the note that all provenance symbols are net-new (`grep` = 0 hits).
5. Fix the snapshot policy and reconcile the two existing snapshot mechanisms (RULE-SNAP-1..3, Section 7.6).
6. Fix the security boundary rules (RULE-SEC-1..3, Section 7.7).
7. Fix ownership + the per-site classification target list (RULE-OWN-1, RULE-CLS-1, Section 7.8).
8. Record the numbering caveat vs `011_prompt_management_plan.md` (Section 2) and the `sonfigs`/`config`/`configs` clarification (Section 4).
9. State the contracts that must not break (Sections 10/11) and the acceptance criteria (Section 13) so 038–044 can self-check.

## 9. Files Expected to Change

**In this subtask (037):**

| Path | Change |
| --- | --- |
| `docs/refactoring/subtasks/037_define_prompt_template_policy.md` | **Created** — this policy document (the only file written) |

No other file — no `.py`, `.md` template, `.yaml`, `.ts`, workflow, or config — is created or modified in subtask 037.

**Files the policy will GOVERN in downstream subtasks (informational; NOT changed here):**

| Path | Governed by | Subtask that edits it |
| --- | --- | --- |
| `ari-core/ari/prompts/_loader.py` | RULE-LOAD-1, RULE-SEC-1 (key sanitization); new `_registry.py` sibling | 038 |
| `ari-core/ari/prompts/` (new manifest data file) | RULE-VER-1..3 (packaged manifest, like `ari/configs/defaults.yaml`) | 038 |
| Core load sites (`agent/loop.py:51`, `evaluator/llm_evaluator.py:255,413`, `orchestrator/bfts.py:475,553,743`, `orchestrator/lineage_decision.py:293`, `orchestrator/root_idea_selector.py:63`, `pipeline/context_builder.py:117`, `viz/api_tools.py:55,127`) | RULE-VER-1 (`rendered_prompt_hash` plumbing, additive) | 038 / 044 |
| Inline prompt sites in `ari-skill-evaluator/src/server.py`, `ari-skill-paper/src/server.py` (+ `review_engine.py`), `-plot/-vlm/-transform/-web/src/server.py` | RULE-CLS-1 (`EXTRACT_TEMPLATE` / `MOVE_TO_CONFIGURABLE_PROMPT`) | 039 / 040 / 041 |
| `ari-skill-replicate/src/{generator.py,auditor.py}`, `ari-skill-paper-re/src/server.py` | RULE-LOAD-2/3 (unified `load_versioned`) | 040 |
| `ari-core/tests/test_prompt_extraction.py` + per-skill test suites | RULE-SNAP-1/3 (new rows, rendered fixture) | 042 |
| `report/scripts/check_prompt_snapshots.py` / `snapshot_prompts.py` + `report/shared/appendix/prompts/**` | RULE-SNAP-2 (regenerate on intentional change) | 042 (as needed) |
| `scripts/docs/check_prompts.py` (net-new) | RULE-KEY-1, RULE-SNAP-1 (lint: manifest ↔ files, placeholder-declaration scan) | 043 |
| Run-metadata / checkpoint writer (`ari-core/ari/checkpoint.py` and run-record path) | RULE-VER-1 (persist provenance, additive keys) | 044 |

## 10. Files / APIs That Must Not Be Broken

The policy must be expressible **without** breaking any of these; any later phase touching them requires a compatibility-adapter note:

- **`PromptLoader` Protocol + `FilesystemPromptLoader`** (`ari-core/ari/prompts/_loader.py`, re-exported at `ari-core/ari/prompts/__init__.py` and `ari-core/ari/protocols/__init__.py:20`). The `load` / `load_versioned` method surface and return shapes stay stable; the registry (038) **composes** the loader, it does not replace it.
- **Public Python API** `ari.public.*` (`claim_gate, config_schema, container, cost_tracker, llm, paths, run_env, verified_context`). Provenance recording hooks into `ari.public.llm` call sites additively.
- **CLI** `ari = ari.cli:app` (typer; subcommands in `cli/{commands,run,bfts_loop,lineage,migrate,projects}.py`).
- **MCP tool contracts** — the 14 `ari-skill-*` `src/server.py` servers and `ari-core/ari/mcp/client.py`. RULE-LOAD-3's `rendered_prompt_hash` is an **additive** field on the tool result.
- **Dashboard API** — `ari-core/ari/viz/routes.py` + `api_*.py` endpoints (incl. `api_tools.py` wizard endpoints) consumed by the React frontend (`services/api.ts`) and `websocket.py`. No endpoint/schema change (Section 7.7 touches wizard prompts conceptually only).
- **Config file formats** — `BFTSConfig.select_prompt` / `expand_select_prompt` (`ari-core/ari/config/__init__.py:133,140`) keep their documented placeholder contract so existing configs continue to load.
- **Checkpoint format** — `ari-core/ari/checkpoint.py`; any prompt-provenance persistence (044) is **additive keys only**, keeping existing readers working.
- **The 11 pinned template hashes** in `ari-core/tests/test_prompt_extraction.py` and the Gate 10 appendix snapshots — byte-identity is the migration's contract.
- **Vendored prompts** — `ari-skill-paper-re/src/_paperbench_bridge.py`, VirSci `utils/prompt.py` — mirror-only, never re-authored.

## 11. Compatibility Constraints

- **Additive-only across boundaries.** Every provenance field (7.5), every MCP result field (RULE-LOAD-3), and every checkpoint/run-metadata key (044) is additive. No existing key is removed or renamed.
- **Byte-identical extraction.** Prompts marked `EXTRACT_TEMPLATE` move to `.md` verbatim; the extracting PR pins the new hash in the same commit (the discipline already used for `agent/system` — see `test_prompt_extraction.py:19-24`).
- **Determinism (P2).** No policy element adds an LLM call, a network fetch, or nondeterministic content. Hashing stays `sha256[:12]` and machine-stable; the registry manifest is packaged git-versioned data, not a service.
- **No dependency inversion.** Skills never import core prompt objects; core never reads skill prompt directories (RULE-LOC-3, RULE-LOAD-2).
- **`.md` default preserved.** The 11 existing `.md` templates keep the `.md` extension and `str.format` rendering; `.j2` is opt-in per-file only (RULE-FMT-3).
- **No `config*` / `sonfigs` involvement.** The policy touches only the `ari-core/ari/prompts/` layer and skill `src/prompts/` layers; it does not touch `ari-core/ari/config/`, `ari-core/ari/configs/`, or `ari-core/config/`, and there is no `sonfigs/` directory to touch.

## 12. Tests to Run

This subtask changes **no runtime code**, so its own verification is limited to confirming the repository is unperturbed and the doc is valid Markdown. Run from the repo root `/home/t-kotama/workplace/ARI`:

- `python -m compileall .` — must pass unchanged (no `.py` touched).
- `pytest -q` — full suite unchanged; in particular `ari-core/tests/test_prompt_extraction.py` must stay green (11 pinned hashes untouched).
- `ruff check .` — clean (no `.py` touched).
- Frontend (`ari-core/ari/viz/frontend/`): **not applicable** — this subtask touches no React/TS; `npm test` / `npm run build` are **not required** for 037.
- Sanity: `git status --porcelain` shows only `docs/refactoring/subtasks/037_define_prompt_template_policy.md` added; `git diff --stat` touches no code, prompt, config, or workflow.

(The commands above are the standard gate; because 037 is a doc-only planning subtask, they serve as a no-regression check rather than a test of new behavior.)

## 13. Acceptance Criteria

1. `docs/refactoring/subtasks/037_define_prompt_template_policy.md` exists, is valid GitHub-flavored Markdown, and uses exactly the 17 standard H2 sections.
2. The document states, as normative rules, the format decision (`.md` + `str.format`, not `.j2`, with the `.j2` escape hatch), the location/key/naming/loading conventions, the ownership table, the provenance field set + hashing + bump discipline, the snapshot policy (reconciling both existing mechanisms), and the security boundary rules.
3. Every path, line number, and count cited resolves in the current repo (spot-checkable against Section 5); no invented paths; anything absent is written as "does not exist".
4. The per-site classification target list (RULE-CLS-1) is consistent with the verified inventory and with subtask 036's remit (037 sets policy; 036 does the exhaustive census).
5. The numbering caveat vs `011_prompt_management_plan.md` and the `config`/`configs`/`sonfigs` clarification are both present.
6. `git status` after the subtask shows **only** this one file added; `pytest -q`, `python -m compileall .`, and `ruff check .` all pass unchanged.
7. Contracts in Sections 10/11 are complete enough that subtasks 038–044 can self-check against them before merging.

## 14. Rollback Plan

Trivial and total: the subtask adds exactly one Markdown file and touches no runtime code, prompt, config, workflow, or test. To roll back, delete `docs/refactoring/subtasks/037_define_prompt_template_policy.md` (or `git revert` the single doc-only commit). No migration, no data change, no downstream code depends on the file existing at runtime — only the *authors* of subtasks 038–044 consult it. There is no compatibility surface to unwind.

## 15. Dependencies

Per the master DEPENDENCY GRAPH (`036 -> 037, 038, 039, 040, 041, 042, 043, 044`):

- **Upstream (must precede 037):** **036** (`inventory_hardcoded_prompts`) — supplies the exhaustive inline-prompt census that grounds the per-site classification in Section 7.8. 036 is one of the nine inventory subtasks (`001, 002, 020, 036, 045, 053, 059, 060, 067`) that **must precede any runtime code change** in their phase.
- **Downstream (consume this policy):** **038** (`introduce_prompt_registry_and_loader`), **039 / 040 / 041** (`extract_*_prompts`), **042** (`add_prompt_snapshot_tests`), **043** (`add_prompt_checker_script`), **044** (`add_prompt_version_tracking_to_run_metadata`). In the raw graph these fan out from 036; **037 should land before the extraction subtasks (039–041) and the registry subtask (038)** so they build against the ratified conventions rather than re-deriving them.
- **Cross-phase notes (informational, no hard edge):** subtask **051** (`add_prompt_change_review_workflow`, Phase 9) will operationalize RULE-VER-3 / RULE-SNAP-1 as a review gate; the quality-scripts phase's `check_prompts.py` (subtask 043) implements RULE-KEY-1 / RULE-SNAP-1 as a lint. Neither blocks 037.

This subtask is itself pure planning and introduces **no** new runtime dependency edges.

## 16. Risk Level

- **Risk: Low.**
- **Runtime code change: No.** This subtask produces a single planning/policy Markdown file. It modifies no Python, no prompt template, no config, no workflow, no frontend, and no directory name. It cannot alter runtime behavior, break a contract, or shift any prompt hash.
- The only *downstream* risk the policy must pre-empt (and does, via the additive-only and byte-identical rules) is that a later implementation subtask breaks the 11 pinned template hashes or an MCP/dashboard/checkpoint contract — those risks live in 038–044, gated by the rules fixed here.

## 17. Notes for Implementer

- **This is a decision document, not a survey.** The survey already exists (`docs/refactoring/011_prompt_management_plan.md`, ~33 KB, and subtask 036's census). Keep 037 tight and normative: state the rule, cite the one grounding fact, move on. Do not re-inventory.
- **Follow the canonical numbering (`007_subtask_index.md`), not 011's internal numbering.** Where they conflict, 007 wins (see the Section 2 caveat). Double-check any cross-reference to 038–044 against `docs/refactoring/007_subtask_index.md` Phase 7 section before citing it.
- **Two snapshot mechanisms exist — do not conflate them.** `ari-core/tests/test_prompt_extraction.py` uses **full** sha256 (64 hex) for pinning and lives in the test suite; `report/scripts/check_prompt_snapshots.py` (Gate 10) also uses full sha256 but protects the report appendix and is *not* wired into the 5 `.github/workflows/*.yml`. The loader's `load_versioned` uses **truncated** `sha256[:12]`. State each precisely.
- **The trailing-newline subtlety is real** (`evaluator/extract_metrics.md` ends with `\n`, the former in-class constant did not; the call site strips one — see the comment at `test_prompt_extraction.py:55-57`). Any policy on newline normalization (RULE-SNAP / 7.6) must account for it; do not "fix" it here.
- **`pipeline/keyword_librarian.md` is populated despite `wc -l` = 0** (352 B, no trailing newline). Do not classify it as empty.
- **`ari-skill-paper-re/src/prompts/mpi_aggregate_skel.py` is code, not a prompt** — it must never be swept into the registry or snapshot set (RULE loc/snap).
- **Vendored ≠ owned.** `_paperbench_bridge.py` (2376 L, 59 triple-quotes) and VirSci `utils/prompt.py` are mirror-only `KEEP_INLINE`; the per-file triple-quote counts are *counts, not exhaustive audits* (036 finishes the line-level verification). Do not propose extracting or hardening vendored text.
- **Keep the doc self-contained.** A fresh coding session opening subtask 038 must not need to open 011 to know the rules — restate the rules here, cite 011 only as the analysis provenance.

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **037** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
