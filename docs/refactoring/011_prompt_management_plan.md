# Prompt Management Refactoring Plan

> Planning document — 2026-07-01. `ari-core` version 0.9.0, git branch `main`.
> This is **planning only**. No runtime code, prompt text, template, config,
> workflow, or directory is modified by this document. The only artifact
> produced here is this `.md` file.

## 1. Purpose

ARI already has a partial prompt-externalization layer:
`ari-core/ari/prompts/` ships a `PromptLoader` Protocol plus a
`FilesystemPromptLoader` (`_loader.py`, 49 lines) and 11 `.md` templates under
`agent/`, `evaluator/`, `orchestrator/`, `pipeline/`, and `viz/`. A regression
test (`ari-core/tests/test_prompt_extraction.py`, 107 lines) already pins every
externalized template to a hardcoded sha256. So this is **not** a
green-field prompt-management project.

The purpose of this plan is to **extend the existing system**, not replace it,
along three axes:

1. **Finish the extraction.** Substantial "You are …" system prompts still live
   inline in the largest skill `server.py` files (e.g.
   `ari-skill-paper/src/server.py`, 2956 lines;
   `ari-skill-evaluator/src/server.py`, 983 lines). Inventory them and
   classify each as KEEP_INLINE / EXTRACT_TEMPLATE / MERGE_DUPLICATE /
   MOVE_TO_CONFIGURABLE_PROMPT / REVIEW_REQUIRED.
2. **Unify the loading mechanism.** Skill-local prompts under
   `ari-skill-replicate/src/prompts/` and `ari-skill-paper-re/src/prompts/`
   bypass `FilesystemPromptLoader` entirely (they use ad-hoc `Path.read_text()`),
   so they get no version hashing. Decide whether/how to route them through a
   shared loader without breaking the ari-skill → ari-core boundary.
3. **Add a registry + versioning layer.** `load_versioned()` computes a
   `sha256[:12]` today, but that value is **only** consumed by
   `test_prompt_extraction.py:103` — it is never persisted into a run record or
   checkpoint. Design a lightweight prompt registry and a provenance record so
   every LLM call can be traced back to a specific template revision and
   rendered-prompt hash.

Non-goals for this plan: introducing a network prompt service, a prompt DSL, or
per-user prompt overrides. The design must stay compatible with **P2
(determinism)** — the registry and versioning machinery must not add
LLM calls and must produce identical hashes across machines.

## 2. Current Prompt Locations

Verified by inspection on 2026-07-01. Prompts currently live in four distinct
places with two different loading mechanisms.

### 2.1 Core externalized templates (via `FilesystemPromptLoader`)

`ari-core/ari/prompts/` — 11 `.md` templates + 5 per-directory `README.md`:

| Key | File | Lines / size |
| --- | --- | --- |
| `agent/system` | `agent/system.md` | 13 L |
| `evaluator/extract_metrics` | `evaluator/extract_metrics.md` | 16 L |
| `evaluator/peer_review` | `evaluator/peer_review.md` | 11 L |
| `orchestrator/bfts_expand` | `orchestrator/bfts_expand.md` | 16 L |
| `orchestrator/bfts_expand_select` | `orchestrator/bfts_expand_select.md` | 8 L |
| `orchestrator/bfts_select` | `orchestrator/bfts_select.md` | 15 L |
| `orchestrator/lineage_decision` | `orchestrator/lineage_decision.md` | 6 L |
| `orchestrator/root_idea_selector` | `orchestrator/root_idea_selector.md` | 6 L |
| `pipeline/keyword_librarian` | `pipeline/keyword_librarian.md` | 352 B (0 trailing newline — populated, not empty) |
| `viz/wizard_chat_goal` | `viz/wizard_chat_goal.md` | 607 B |
| `viz/wizard_generate_config` | `viz/wizard_generate_config.md` | 257 B |

The loader (`_loader.py`) resolves `{base}/{key}.md`, defaulting `base` to
`package_prompts_root()` (the `prompts/` directory). Templates are filled with
Python `str.format(...)` at the call site (single-brace `{name}` placeholders).

### 2.2 Core load sites (11 files, all lazy in-function imports)

Every core consumer imports the loader lazily inside the function that needs it:

- `ari/agent/loop.py:51-52` — loads `agent/system`.
- `ari/evaluator/llm_evaluator.py:255` (`evaluator/extract_metrics`),
  `:412-413` (`evaluator/peer_review`, then `.format(...)`).
- `ari/orchestrator/bfts.py:475-479` (`select_prompt`, default
  `orchestrator/bfts_select`), `:553-559` (`expand_select_prompt`, default
  `orchestrator/bfts_expand_select`), `:743-744`
  (`orchestrator/bfts_expand`).
- `ari/orchestrator/lineage_decision.py:292-293`
  (`orchestrator/lineage_decision`).
- `ari/orchestrator/root_idea_selector.py:62-63`
  (`orchestrator/root_idea_selector`).
- `ari/pipeline/context_builder.py:116-117`
  (`pipeline/keyword_librarian`).
- `ari/viz/api_tools.py:54-55` (`viz/wizard_chat_goal`), `:126-127`
  (`viz/wizard_generate_config`).

Two of these keys are already **config-swappable**: `BFTSConfig.select_prompt`
(`ari/config/__init__.py:133`) and `BFTSConfig.expand_select_prompt`
(`ari/config/__init__.py:140`) let a config file point the loader at an
alternative `.md` key as long as it accepts the same placeholders. This is the
seed of the "configurable prompt" pattern (see §6, §7).

### 2.3 Skill-local externalized templates (bypass the core loader)

These are `.md` files, but loaded with plain `Path.read_text()`, so they are
**not** hash-pinned and carry no version metadata:

- `ari-skill-replicate/src/prompts/`: `skeleton.md` (143 L), `subtree.md`
  (115 L), `adversarial_reviewer.md` (208 L), `rubric_audit.md` (28 L). Loaded
  via `PROMPTS_DIR / "x.md").read_text()` in `generator.py:64,77,93` and
  `auditor.py:130` (`PROMPTS_DIR` defined at `generator.py:26`,
  `auditor.py:17`).
- `ari-skill-paper-re/src/prompts/`: `replicator.md` (154 L) loaded via
  `server.py:66`. (`prompts/mpi_aggregate_skel.py` in the same directory is a
  **code skeleton, not a prompt** — it must not be swept into the registry.)

### 2.4 Still-inline prompts in Python

Substantial system prompts remain embedded as string literals in skill
`server.py` files and helper modules — inventoried in §3 and classified in §5.
The highest-value targets are the evaluator judge prompts
(`ari-skill-evaluator/src/server.py:191, 790`) and the five paper prompts in
`ari-skill-paper/src/server.py` (see §3.3).

> Note on the "config/configs/sonfigs" concern: there is **no `sonfigs/`**
> directory anywhere in the repo (confirmed absent; the term is a hypothesized
> typo). The confusable trio is `ari-core/ari/config/` (Python *code* that
> locates config files), `ari-core/ari/configs/` (packaged *data*:
> `defaults.yaml`, `model_prices.yaml`, plus `_loader.py`), and top-level
> `ari-core/config/` (rubric/profile YAML data). Prompts are governed
> separately by `ari-core/ari/prompts/`. This plan keeps the prompt layer
> parallel to `configs/` (both have a `_loader.py` + Protocol) and does **not**
> touch any `config*` directory.

## 3. Prompt Categories

Prompts in ARI fall into six functional categories. Category drives ownership
(§5) and the KEEP/EXTRACT decision (§5.x).

### 3.1 Agent / ReAct loop prompts
The single agent system prompt (`agent/system.md`, consumed by
`ari/agent/loop.py`, 1630 lines). Stable, already externalized.

### 3.2 Orchestration / search prompts
BFTS expand/select, lineage decision, root-idea selection — five templates
under `orchestrator/`, consumed by `ari/orchestrator/bfts.py` (845 lines),
`lineage_decision.py`, and `root_idea_selector.py`. All externalized; two are
config-swappable.

### 3.3 Evaluation / judge prompts (LLM-as-judge)
- **Externalized (core):** `evaluator/extract_metrics.md`,
  `evaluator/peer_review.md`.
- **Still inline (skill):** `ari-skill-evaluator/src/server.py`
  `_METRIC_EXTRACT_SYS` (`:191`, ~11 L, used at `:217`) and
  `_SEMANTIC_SYSTEM_PROMPT` (`:790`, ~18 L rigorous-reviewer judge + JSON
  schema, used at `:903`).
- **Still inline (paper skill):** `ari-skill-paper/src/server.py` inline
  reviewer/writer/editor prompts at `:542` (academic reviewer), `:1487`
  (fill-in writer), `:1638` (LaTeX figure inserter), `:1660` (paper writer),
  `:2544` (global-coherence editor with hard-constraint rules + JSON edit
  schema). `review_engine.py` builds venue peer-reviewer prompts at `:58`
  (`build_system_prompt`) and an Area-Chair meta-review prompt at `:443`.

### 3.4 Pipeline / context-building prompts
`pipeline/keyword_librarian.md` (keyword extraction for BFTS context). Small,
externalized.

### 3.5 Wizard / dashboard prompts
`viz/wizard_chat_goal.md`, `viz/wizard_generate_config.md` — consumed by
`ari/viz/api_tools.py`. These are the only prompts whose rendered output is
driven by **free-text user input** from the dashboard (see §11).

### 3.6 Generation / replication / plotting prompts (skill-local + inline)
- Externalized skill-local: `ari-skill-replicate/src/prompts/*.md`,
  `ari-skill-paper-re/src/prompts/replicator.md`.
- Inline skill prompts: `ari-skill-plot/src/server.py:90,560,663`
  (writing/visualization expert, matplotlib JSON emitter);
  `ari-skill-vlm/src/server.py:97,112` (figure/table reviewer);
  `ari-skill-transform/src/server.py:834,867` (scientific-analyst
  summarizers); `ari-skill-web/src/server.py:465,483` (research librarian /
  reference selector); `ari-skill-idea/src/server.py:245-266` (VirSci-backed
  discussion, inline fallback).
- **Vendored (do not touch):** `ari-skill-paper-re/src/_paperbench_bridge.py`
  (2376 lines, 59 triple-quoted strings) mostly mirrors upstream PaperBench
  templates; `ari-skill-idea` primary path execs vendored VirSci
  `utils/prompt.py` (`server.py:42-48`).

## 4. Problems with Hardcoded Prompts

Concrete, repository-specific problems that this plan addresses.

1. **No provenance on the majority of LLM calls.** `load_versioned()` produces
   a `sha256[:12]`, but the only caller is `test_prompt_extraction.py:103`. In
   production, `bfts.py`, `loop.py`, `llm_evaluator.py`, and every skill call
   `load()` (not `load_versioned()`) or `read_text()`, so **no prompt hash is
   recorded in any checkpoint or run record**. A run's outputs cannot be tied
   back to the exact prompt text that produced them. `grep` for
   `template_hash`, `prompt_version`, `rendered_prompt`, or `prompt_registry`
   across `ari-core` returns **zero** hits — none of the provenance vocabulary
   exists yet.

2. **Two divergent loading mechanisms.** Core uses `FilesystemPromptLoader`
   (hash-capable); `ari-skill-replicate` and `ari-skill-paper-re` use
   `Path.read_text()` (no hashing, no config-swap, no snapshot coverage). Edits
   to `skeleton.md` (143 L) or `replicator.md` (154 L) are invisible to the
   regression harness. REVIEW_REQUIRED.

3. **Large files hide high-value prompts.** The biggest system prompts are
   buried in the biggest files: `ari-skill-paper/src/server.py` (2956 L, 5
   inline "You are …" prompts) and `ari-skill-evaluator/src/server.py`
   (983 L). Reviewers editing prompt wording must scroll past MCP wiring and
   business logic; a wording change is indistinguishable from a code change in
   the diff.

4. **Conceptual duplication across core and skills.** `review_engine.py:58`
   (venue peer-reviewer) overlaps `evaluator/peer_review.md`;
   `ari-skill-evaluator/src/server.py:191` (`_METRIC_EXTRACT_SYS`) overlaps
   `evaluator/extract_metrics.md`. They are related but not byte-identical, so
   fixes to one silently drift from the other. MERGE_DUPLICATE /
   REVIEW_REQUIRED.

5. **Unguarded key resolution + user-driven rendering.**
   `FilesystemPromptLoader.load` (`_loader.py:42`) does
   `self._base / f"{key}.md"` with **no key sanitization**. Combined with
   config-swappable keys (`BFTSConfig.select_prompt`), a crafted key could
   traverse outside the prompts root. Separately, the wizard prompts render
   free-text user goals via `str.format`. Neither concern is a format-string
   vulnerability today (templates are trusted; user text is a *value*, not part
   of the format string), but both are validation gaps (see §9, §11).

6. **No versioning scheme.** Templates carry no `prompt_version`. The snapshot
   test tracks change *detection* (hash mismatch → fail) but there is no
   notion of an intentional bump, no changelog per prompt, and no way to say
   "this run used peer_review v2".

## 5. Prompt Ownership Policy

Ownership defines **who** may edit a prompt and **where** it lives, keyed to the
contract surface it touches.

| Category | Owner boundary | Storage location |
| --- | --- | --- |
| Agent / orchestration / pipeline / evaluator core prompts (§3.1–3.4 core) | ari-core maintainers | `ari-core/ari/prompts/**` |
| Wizard / dashboard prompts (§3.5) | ari-core maintainers (viz) — but user-input-facing, review under §11 | `ari-core/ari/prompts/viz/**` |
| Skill-authored generation prompts (§3.6, non-vendored) | owning `ari-skill-*` package | `ari-skill-*/src/prompts/**` |
| Vendored prompts (PaperBench bridge, VirSci) | **upstream** — mirror only | in place, `KEEP_INLINE` |

Rules:

- **Core prompts stay in core.** A skill must not reach into
  `ari-core/ari/prompts/` — that would invert the ari-skill → ari-core
  dependency direction. If a skill needs a core prompt, it is passed the
  rendered string across the MCP boundary, not the template path.
- **Skills own their own prompts.** `ari-skill-replicate` and
  `ari-skill-paper-re` keep their `src/prompts/` directories. The plan changes
  *how* they load (unified loader) not *where* they live.
- **Vendored prompts are never "owned" by ARI.** They are classified
  `KEEP_INLINE` to preserve upstream parity; editing them forks the vendor.

### 5.x Per-prompt classification (inventory outcome)

Using the master vocabulary specialized for prompts —
**KEEP_INLINE / EXTRACT_TEMPLATE / MERGE_DUPLICATE /
MOVE_TO_CONFIGURABLE_PROMPT / REVIEW_REQUIRED**:

**EXTRACT_TEMPLATE** (substantial, static, ARI-authored — move to `.md` under
the owning package):
- `ari-skill-evaluator/src/server.py:790` `_SEMANTIC_SYSTEM_PROMPT` (~18 L judge
  rubric + JSON schema) — strongest single target.
- `ari-skill-evaluator/src/server.py:191` `_METRIC_EXTRACT_SYS` (~11 L).
- `ari-skill-paper/src/server.py:1487, 1638, 1660, 2544` (fill-in writer, LaTeX
  figure inserter, paper writer, global-coherence editor).
- `ari-skill-plot/src/server.py:90, 560, 663`;
  `ari-skill-vlm/src/server.py:97, 112`;
  `ari-skill-transform/src/server.py:834, 867`;
  `ari-skill-web/src/server.py:465, 483`.

**MOVE_TO_CONFIGURABLE_PROMPT** (rubric/venue-parameterized — extract the static
scaffold to a template, keep dynamic injection as a builder):
- `ari-skill-paper/src/review_engine.py:58` `build_system_prompt` and `:105`
  `build_user_prompt` (parameterized by `rubric.venue`, `rubric.system_hint`,
  dimension lines). The static scaffold moves to a template; rubric injection
  stays in Python. `ari-skill-paper/src/rubric.py` (344 L) and
  `ari-skill-replicate/src/rubric_template.py` (237 L) are **rubric builders,
  not prompt text** — leave in place.
- Precedent already exists: `BFTSConfig.select_prompt` /
  `expand_select_prompt` (`ari/config/__init__.py:133,140`) demonstrate the
  configurable-key pattern for the orchestrator templates.

**MERGE_DUPLICATE / REVIEW_REQUIRED** (overlapping concepts, not byte-identical
— needs human adjudication before consolidation):
- `review_engine.py:58` / `:443` vs core `evaluator/peer_review.md`.
- `ari-skill-evaluator/src/server.py:191` vs core
  `evaluator/extract_metrics.md`.

**KEEP_INLINE** (vendored or fallback-only — externalizing harms upstream
parity or is not worth the churn):
- `ari-skill-idea/src/server.py:245-266` inline fallback (primary path uses
  vendored VirSci `utils/prompt.py`).
- `ari-skill-paper-re/src/_paperbench_bridge.py` (2376 L) — vendored PaperBench
  templates; trivial role strings (e.g. `:1097`) not worth extracting.
- `ari-skill-paper/src/server.py:353, 622, 631, 639` — short, heavily
  f-string-interpolated one-liners; extraction cost > benefit (REVIEW_REQUIRED
  if bundled with the larger paper-server extraction).

**REVIEW_REQUIRED (mechanism)**: skill-local `.md` prompts that already exist
(`ari-skill-replicate/src/prompts/*`, `ari-skill-paper-re/src/prompts/*`) —
they are externalized but bypass the loader (§2.3). The decision is whether to
route them through a shared loader (§6).

> The above per-file line numbers were confirmed by `grep` on 2026-07-01. The
> full triple-quote census of `_paperbench_bridge.py` (59) and
> `ari-skill-evaluator/src/server.py` (31) was **sampled, not exhaustively
> line-verified** — treat per-file counts as counts, not complete audits.
> Subtask 036 (§13) performs the exhaustive line-level inventory.

## 6. Prompt Template Location Policy

### 6.1 Directory convention (extend, don't relocate)

Keep the existing two-tier layout:

- **Core prompts:** `ari-core/ari/prompts/<category>/<name>.md`, where
  `<category>` mirrors the consuming module (`agent`, `evaluator`,
  `orchestrator`, `pipeline`, `viz`). New extracted core prompts follow the
  same key scheme.
- **Skill prompts:** `ari-skill-<name>/src/prompts/<name>.md`. This directory
  already exists for `replicate` and `paper-re`; extend it to the other skills
  that gain extracted templates (`evaluator`, `paper`, `plot`, `vlm`,
  `transform`, `web`) rather than centralizing skill prompts into core.

Rationale: centralizing skill prompts into `ari-core` would create a new
ari-core → ari-skill coupling in the wrong direction and break MCP-package
self-containment. Each skill remains installable on its own.

### 6.2 `.md` vs `.md.j2` — recommendation

**Recommendation: keep `.md` extension; do NOT migrate to `.md.j2` in this
phase.** Reasons grounded in the current code:

- Every core call site fills templates with `str.format(...)` using
  single-brace `{name}` placeholders (e.g. `bfts.py:479`,
  `llm_evaluator.py:413`). Migrating to Jinja2 (`{{ name }}`) would require
  rewriting all 11 templates **and** every `.format(...)` call site
  simultaneously, and would break the byte-for-byte hashes in
  `test_prompt_extraction.py`.
- `str.format` covers all present needs (named substitution). No template in
  the inventory requires loops, conditionals, includes, or filters.
- Jinja2 introduces autoescaping/undefined-variable semantics and a runtime
  dependency that the deterministic core currently avoids.

**Where `.md.j2` becomes justified (defer to a follow-up subtask):** only the
MOVE_TO_CONFIGURABLE_PROMPT prompts (`review_engine.py` rubric builders) have
genuine conditional/loop structure (per-dimension lines, optional
`system_hint`). If any single template needs control flow, adopt `.j2` **for
that template only**, keyed by extension, with the loader selecting the render
engine by suffix (`.md` → `str.format`, `.md.j2` → Jinja2). This keeps the 11
existing `.md` files untouched and their hashes stable. The registry (§7) must
record which render engine was used.

## 7. Prompt Registry Design

The registry is a thin, deterministic index over templates — **not** a service
and **not** a new storage backend. It builds on the existing `PromptLoader`
Protocol rather than replacing it.

### 7.1 Shape

A `PromptRegistry` (proposed home: `ari-core/ari/prompts/_registry.py`,
alongside the existing `_loader.py`) that:

- Enumerates known prompt keys and their declared metadata (owner category,
  `prompt_version`, render engine, expected placeholders).
- Wraps a `PromptLoader` (default `FilesystemPromptLoader`) so it stays
  test-swappable, consistent with the existing Protocol design.
- Exposes `resolve(key) -> PromptRecord` returning
  `(text, template_hash, prompt_version, render_engine, placeholders)` and
  `render(key, **vars) -> RenderedPrompt` returning the filled string plus
  `rendered_prompt_hash`.

The registry manifest itself is packaged **data** (a YAML/JSON file under
`ari-core/ari/prompts/`, mirroring how `ari/configs/` ships `defaults.yaml`),
so it is versioned in git and adds no LLM calls (P2-safe).

### 7.2 Cross-package strategy (skill prompts)

Skills must **not** import a core registry object (would invert the
dependency). Instead:

- Each skill keeps its own tiny loader but adopts the **same** `load_versioned`
  contract (return `(text, sha256[:12])`), so hashes are produced uniformly.
  This can be a copied 15-line helper per skill or a shared utility exposed via
  the MCP tool result — decision is REVIEW_REQUIRED (subtask 040).
- The rendered-prompt hash a skill computes is returned to ari-core **through
  the existing MCP tool result payload** (an additive field), so ari-core can
  record it in the run provenance without a new import edge. This preserves the
  ari-skill-* → ari-core stable interface and the MCP tool contract (additive
  field only; no breaking change).

### 7.3 What the registry is NOT

- Not a runtime prompt *editor* or override mechanism (no per-user prompts).
- Not a network fetch. `package_prompts_root()` stays filesystem-local.
- Not a replacement for `FilesystemPromptLoader` — it composes it.

## 8. Prompt Versioning Policy

### 8.1 Fields (provenance record)

Every LLM call that uses a managed prompt should be able to emit a provenance
record with these fields. **None of these symbols exist in the codebase today**
(confirmed by `grep`); they are introduced by this plan:

| Field | Meaning | Source |
| --- | --- | --- |
| `prompt_name` | registry key, e.g. `orchestrator/bfts_select` | registry |
| `prompt_version` | human-assigned semantic version of the template | registry manifest |
| `template_hash` | `sha256[:12]` of the raw template body | `load_versioned()` (exists) |
| `rendered_prompt_hash` | `sha256[:12]` of the post-`format` string actually sent | registry `render()` (new) |
| `prompt_registry_version` | version of the manifest as a whole | registry manifest |
| `model_name` | model the rendered prompt was sent to | LLM call site (`ari.public.llm`) |
| `run_id` | the run this call belongs to | run/checkpoint context |
| `node_id` | BFTS node / pipeline node the call served | orchestrator/pipeline context |

`template_hash` is already computable via `load_versioned()`; the new work is
(a) computing `rendered_prompt_hash` after `.format(...)`, and (b) plumbing the
record into the run/checkpoint provenance rather than discarding it.

### 8.2 Version-bump discipline

- `template_hash` changes **automatically** on any byte change (detected by the
  snapshot test, §10). `prompt_version` is bumped **manually** to signal an
  *intentional* behavioral change, and the snapshot test's expected hash is
  updated in the same commit (this mirrors the existing pattern — see the
  `v0.7.2` annotations already present in `test_prompt_extraction.py`).
- A per-prompt changelog line lives in the registry manifest (or the prompt's
  category `README.md`), not in a separate file, to keep prompt + history
  co-located.

### 8.3 Determinism constraint

Hashing uses `hashlib.sha256(text.encode("utf-8"))` truncated to 12 hex chars —
the exact scheme already in `_loader.py:48`. It is machine-stable (unlike a git
SHA) and adds no nondeterminism. The registry must not embed timestamps or host
info in any hashed content.

## 9. Prompt Rendering and Validation Policy

### 9.1 Render path

- `.md` templates render via `str.format(**vars)` (unchanged from today).
- Optional `.md.j2` templates (only if adopted per §6.2) render via Jinja2 with
  `StrictUndefined` so a missing variable fails loudly rather than silently
  emitting an empty string.

### 9.2 Validation gaps to close (grounded)

1. **Key sanitization.** `FilesystemPromptLoader.load` (`_loader.py:42`) joins
   an arbitrary `key` into a path with no traversal guard. Because keys can come
   from config (`BFTSConfig.select_prompt`), the registry must validate that the
   resolved path stays within `package_prompts_root()` and that the key matches
   `^[a-z0-9_]+(/[a-z0-9_]+)*$`. REVIEW_REQUIRED — verify no legitimate key
   contains other characters before enforcing.
2. **Placeholder contract.** Each registry entry declares its expected
   placeholders; `render()` should assert the supplied `vars` match (catches the
   `bfts_select` "must accept `{experiment_goal}`, `{memory_context}`,
   `{candidates}`" contract already documented at
   `ari/config/__init__.py:135-139`). A config that swaps in a template missing
   a placeholder currently fails only at `str.format` time with a raw
   `KeyError`; the registry should surface a clear error.
3. **Trailing-newline sensitivity.** `evaluator/extract_metrics.md` ends with a
   newline that the in-class constant did not, and the call site strips one (see
   the note at `test_prompt_extraction.py`). The registry should make
   newline-normalization explicit rather than leaving it to per-call-site
   `.strip()`.

## 10. Prompt Snapshot Test Policy

**A snapshot test already exists** and is the foundation to extend, not
duplicate: `ari-core/tests/test_prompt_extraction.py` (107 lines) hardcodes the
expected `sha256` of every externalized core template and asserts it matches the
on-disk body (`_EXPECTED_HASHES` list). Provenance annotations (PC2–PC6,
`v0.7.2`) are already threaded through it.

Extensions this plan proposes:

1. **Cover the gaps.** Add rows for every newly EXTRACT_TEMPLATE'd prompt (§5.x)
   and for the skill-local templates that currently have **no** snapshot
   coverage (`ari-skill-replicate/src/prompts/*`,
   `ari-skill-paper-re/src/prompts/replicator.md`). Skill tests live in each
   skill's own test suite to keep packages self-contained.
2. **Snapshot the *rendered* prompt for a fixed fixture.** In addition to the
   raw-template hash, add a test that renders each template with a canned
   variable set and asserts `rendered_prompt_hash`, so a change to a
   `.format(...)` call site (not just the template) is also caught.
3. **Registry-manifest consistency.** A test that every registry key resolves to
   an existing file and every `.md` file under a managed directory has a
   registry entry (no orphans, no dangling keys).
4. **CI wiring.** These are ordinary `pytest` tests; they run under the existing
   suites invoked by `.github/workflows/refactor-guards.yml` and
   `scripts/run_all_tests.sh`. No new workflow is required. A dedicated
   `scripts/docs/check_prompts.py` (listed as MISSING in the tooling survey) may
   later add a lint pass (placeholder-declaration vs template scan), designed as
   subtask 044 — **not implemented now**.

## 11. Prompt Security / Injection Boundary

### 11.1 The actual boundary

Managed templates are **trusted** (shipped, hash-pinned). The untrusted input is
the *data* interpolated into them. The two real boundaries:

- **User free-text → prompt (semantic injection).** The wizard prompts
  (`viz/wizard_chat_goal.md`, `viz/wizard_generate_config.md`, rendered in
  `ari/viz/api_tools.py:55,127`) and the BFTS templates
  (`{experiment_goal}`) interpolate free text the user supplied through the
  dashboard. This is a **prompt-injection** surface at the LLM level (a goal
  containing "ignore prior instructions and …"), not a Python format-string
  vulnerability — the user text is a *value*, not part of the format string, so
  `str.format` does not expose attribute/index access to it.
- **Config-controlled template key → filesystem (path traversal).** As in
  §9.2(1), `select_prompt`/`expand_select_prompt` let config choose which file
  is read; without sanitization this can escape the prompts root.

### 11.2 Policy

- **Isolate untrusted values.** Keep user-supplied text confined to clearly
  named placeholders (`{experiment_goal}`, wizard user turns). Never let user
  text choose a `prompt_name` / registry key.
- **Sanitize keys** at the registry boundary (§9.2). Keys are code/config
  identifiers, never user input.
- **No format-string reflection.** Continue passing user text only as
  `str.format` *arguments*; never build a template string from user input and
  never `str.format` a user-provided template.
- **Record the rendered hash** (§8) so an injected/anomalous rendered prompt is
  auditable after the fact.
- **Vendored prompts** (`_paperbench_bridge.py`) keep their upstream browsing/
  tool instructions verbatim; the injection boundary there is governed by the
  vendored solver, not this plan. Do not "harden" vendored text (forks upstream).

This section touches the dashboard API only conceptually; no endpoint schema in
`ari/viz/routes.py` or `api_*.py` is changed by this plan.

## 12. Migration Strategy

Incremental, contract-preserving, one prompt-family per PR. Ordered by
risk/value:

1. **Inventory (no code change).** Produce the exhaustive line-level census of
   inline prompts (extends §5.x beyond the sampled counts). Output: a checklist
   with a KEEP_INLINE/EXTRACT/MERGE/MOVE/REVIEW verdict per string. (Subtask
   036.)
2. **Registry scaffold + provenance fields (additive).** Add
   `ari/prompts/_registry.py` + manifest and the `PromptRecord`/provenance
   dataclass. Wire `rendered_prompt_hash` computation at the existing core call
   sites **without changing prompt text** (hashes in
   `test_prompt_extraction.py` stay green). Persist the provenance record into
   the run/checkpoint context. (Subtasks 037–038.)
3. **Extract the high-value skill prompts.** Move `_SEMANTIC_SYSTEM_PROMPT` and
   `_METRIC_EXTRACT_SYS` (`ari-skill-evaluator`), then the four paper prompts,
   each PR pairing the extraction with a new snapshot-hash row. Verified
   byte-identical extraction (hash captured against the original literal, the
   same discipline used for `agent/system` in PC3). (Subtasks 039, 041.)
4. **Unify skill loading.** Give `ari-skill-replicate` / `ari-skill-paper-re`
   the `load_versioned` contract and surface the hash across the MCP result
   (additive field). (Subtask 040.)
5. **Configurable rubric prompts.** Extract the static scaffold from
   `review_engine.py` builders; adopt `.md.j2` only if control flow is
   genuinely needed (§6.2). (Subtask 042.)
6. **Merge-duplicate adjudication.** Human review of the peer_review /
   extract_metrics overlaps; consolidate or explicitly document the divergence.
   (Subtask 043.)
7. **Lint + snapshot completeness gate.** Add `check_prompts.py`, wire into the
   existing test scripts. (Subtask 044.)

Compatibility notes (contracts preserved throughout):
- CLI `ari`, `ari.public.*`, MCP tool contracts, dashboard API endpoints/schema,
  and checkpoint/config file formats are **not** broken. New provenance fields
  are **additive** (new keys in existing records / new MCP result fields).
- Every extraction PR must keep `test_prompt_extraction.py` green by adding the
  new expected hash in the same commit — the byte-identical guarantee is the
  migration's safety net.
- `BFTSConfig.select_prompt` / `expand_select_prompt` config keys keep their
  documented placeholder contract, so existing configs continue to load.

## 13. Related Subtasks

These subtasks will be authored under `docs/refactoring/subtasks/` (currently
empty — this is the first refactoring plan in the tree). They are **planning
placeholders**; none is implemented by this document.

| ID | Title | Scope |
| --- | --- | --- |
| 036 | Exhaustive inline-prompt inventory | Line-level census of every triple-quote / "You are …" across all `ari-skill-*/src/server.py` and helpers; verdict per string. Closes the "sampled, not exhaustive" gap in §5.x. |
| 037 | PromptRegistry scaffold + manifest | `ari/prompts/_registry.py`, packaged manifest, `PromptRecord`; no prompt-text change. |
| 038 | Prompt provenance record + persistence | Compute `rendered_prompt_hash`, assemble the §8.1 field set, persist into run/checkpoint context (additive). |
| 039 | Extract evaluator judge prompts | `_SEMANTIC_SYSTEM_PROMPT`, `_METRIC_EXTRACT_SYS` → `ari-skill-evaluator/src/prompts/*.md` + snapshot rows. |
| 040 | Unify skill prompt loading | Give `replicate` / `paper-re` the `load_versioned` contract; surface hash via MCP result (additive). |
| 041 | Extract paper-skill prompts | Four paper `server.py` prompts (`:1487, 1638, 1660, 2544`) → templates + snapshot rows. |
| 042 | Configurable rubric prompts | Extract static scaffold from `review_engine.py` builders; `.md.j2` decision (§6.2). |
| 043 | Merge-duplicate adjudication | peer_review / extract_metrics core-vs-skill overlap; consolidate or document divergence. |
| 044 | `check_prompts.py` lint + snapshot-completeness gate | New checker under `scripts/docs/`; wire into `scripts/run_all_tests.sh` / refactor-guards. |

---

### Appendix A — grounding index

Facts in this document verified by direct inspection on 2026-07-01:

- Loader: `ari-core/ari/prompts/_loader.py` (49 L), `__init__.py` (12 L),
  re-exported at `ari/protocols/__init__.py`.
- Templates + line/byte counts: §2.1 table (measured via `wc`).
- Core call sites: `agent/loop.py:51`, `evaluator/llm_evaluator.py:255,412`,
  `orchestrator/bfts.py:475,553,743`, `orchestrator/lineage_decision.py:292`,
  `orchestrator/root_idea_selector.py:62`, `pipeline/context_builder.py:116`,
  `viz/api_tools.py:54,126`.
- Config-swappable keys: `ari/config/__init__.py:133` (`select_prompt`),
  `:140` (`expand_select_prompt`).
- Skill-local loaders: `ari-skill-replicate/src/generator.py:26,64,77,93`,
  `auditor.py:17,130`; `ari-skill-paper-re/src/server.py:66`.
- Inline prompts: `ari-skill-evaluator/src/server.py:191,790`;
  `ari-skill-paper/src/server.py:542,1487,1638,1660,2544`;
  `ari-skill-paper/src/review_engine.py:58,105,443`; plot/vlm/transform/web
  per §3.6; idea fallback `ari-skill-idea/src/server.py:42-48,245-266`.
- Existing snapshot test: `ari-core/tests/test_prompt_extraction.py` (107 L);
  `load_versioned` sole caller at `:103`.
- Absence checks (grep, zero hits in `ari-core`): `template_hash`,
  `prompt_version`, `rendered_prompt`, `prompt_registry`. No `sonfigs/`
  directory anywhere.

## Retirement Condition

This is a **program-level planning document**, not a per-subtask artifact. It
stays live for the duration of the refactoring program and may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources — never on assumption:

1. Every subtask this document governs is marked **DONE** in
   `docs/refactoring/007_subtask_index.md`, **or** this document has been
   explicitly **superseded** by a named replacement (the superseding document
   must reference this file by name).
2. Any conclusions worth keeping have been folded into the permanent
   documentation / architecture.

Before any `git rm`, re-read this document's own conditions and check each one
against the current repository. See the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
