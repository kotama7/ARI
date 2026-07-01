# Subtask 041: Extract Pipeline And Paper Generation Prompts

> Phase 7: Prompt Management · Depends on 036 · Risk: Medium · Runtime code change: **Yes** (when implemented)
>
> This document is a **planning artifact only**. Writing it changes no runtime
> code, prompts, configs, workflows, or directory names. It describes the work a
> later implementation session will perform. Every path and line number below was
> verified by inspecting the repository on the planning date (2026-07-01).

## 1. Goal

Finish externalizing the prompt text that drives the two **paper-producing**
surfaces of ARI so that prompts are editable and version-pinnable without
touching Python:

1. **Pipeline-stage prompts** in `ari-core/ari/pipeline/` — audit and confirm
   completeness. The one core-loaded stage prompt
   (`ari/prompts/pipeline/keyword_librarian.md`) is **already externalized** and
   is the reference model for the rest of this subtask.
2. **Paper-generation prompts** in the `ari-skill-paper` package
   (`ari-skill-paper/src/server.py`, 2956 LOC — the largest Python file in the
   repo — and `ari-skill-paper/src/review_engine.py`, 489 LOC), which still carry
   ~10 hardcoded system prompts plus two module-level prompt constants.

The extraction is **behavior-preserving and byte-exact**: prompt text is moved
verbatim into `.md` templates, dynamic per-call injection (venue hints, cite-key
rules, language directive) stays in Python, and no LLM-visible bytes change. This
protects design principle **P2 (determinism)** — a prompt-text drift would silently
change model output and break reproducibility pins.

## 2. Background

Prompt externalization is **already partially done** (Phase "PC" /
`PROMPTS_AND_CONFIG.md`). The core loader lives in
`ari-core/ari/prompts/_loader.py` (49 LOC): `package_prompts_root()` returns the
bundled `ari-core/ari/prompts/` dir; `FilesystemPromptLoader.load(key)` reads
`{base}/{key}.md`; `load_versioned(key)` returns `(text, sha256[:12])` for
reproducibility pinning. `PromptLoader` is a `Protocol`, re-exported from
`ari/prompts/__init__.py` and again from `ari/protocols/__init__.py:20`. Templates
are `.md` (confirmed — not `.j2`), filled with Python `str.format(...)` at call
sites (single-brace `{name}` placeholders; literal braces are doubled `{{ }}`).

Eleven core call sites use the loader via a lazy in-function
`from ari.prompts import FilesystemPromptLoader`. The one relevant to this subtask
is the **pipeline** site:
`ari/pipeline/context_builder.py:116-117` loads
`pipeline/keyword_librarian` (`ari/prompts/pipeline/keyword_librarian.md`, a
single-line 352-byte research-librarian query prompt). That is the **only**
externalized pipeline prompt today, and the only hardcoded-prompt concern inside
`ari/pipeline/*.py` besides `stage_runner.py:129`, where the ReAct-stage
`system_prompt`/`user_prompt` are resolved **from YAML `react_cfg`** (already
config-driven, not Python-embedded) — and that ReAct path is dormant in the
shipped config (`grep -c 'react:' config/workflow.yaml` == 0, verified). So the
**pipeline side of this subtask is essentially an audit-and-confirm task**, not a
large extraction.

The **paper side** is where the real work is. `ari-skill-paper` is a standalone
MCP skill package and — verified — it does **not** import `ari-core` (no
`from ari` / `import ari.` statements in `src/*.py`), and it has **no
`src/prompts/` directory yet** (only `ari-skill-paper-re` and
`ari-skill-replicate` ship skill-local `src/prompts/`). Those two skills load
their externalized prompts via ad-hoc `Path(...).read_text()`
(`ari-skill-replicate/src/generator.py:26,64,77,93`;
`ari-skill-paper-re/src/server.py:66`) — i.e. they **bypass** the core
`FilesystemPromptLoader` and its `load_versioned` hashing. This mechanism
inconsistency (no version pin on skill prompts) is a REVIEW_REQUIRED item for
this subtask: paper prompts should be extracted, and the skill needs a loader —
but making the skill depend on `ari-core` just for `ari.prompts` would introduce
an unwanted skill→core coupling, so the practical options are (a) a tiny
skill-local loader mirroring `read_text` (parity with replicate/paper-re), or
(b) a shared loader delivered by the Phase 7 root subtask 036.

Subtask **036** is the Phase 7 root that all of `037-044` depend on (see
dependency graph). Its planning document **does not exist yet**
(`docs/refactoring/subtasks/036_*.md` is not present; the subtasks dir currently
holds 001-031 minus 028, 30 files total). 036 is expected to establish the shared
prompt-management policy/loader that 041 adopts; this doc is written so it can
proceed against the existing `ari.prompts` loader if 036 has not yet delivered a
new one.

## 3. Scope

In scope (implementation phase, not this doc):

- **Pipeline audit**: confirm that `ari-core/ari/pipeline/*.py` contains no
  Python-embedded LLM prompt text other than the already-externalized
  `keyword_librarian` load and the config-driven `stage_runner.py:129` ReAct
  block. Document the finding; no code change if the audit confirms completeness.
- **Paper prompt extraction** (`ari-skill-paper/src/server.py`, 2956 LOC): move
  the following **static** system-prompt text verbatim into skill-local `.md`
  templates, replacing the inline literals with a load-and-`str.format` call while
  keeping all **dynamic** per-call injection in Python:
  - Module-level `SECTION_PROMPTS` dict (`:66`) and `_FORBIDDEN_NOTICE` constant
    (`:126`).
  - Section writer assembly at `:302` (title), `:306` (abstract), `:362`
    (body sections). — EXTRACT_TEMPLATE for the static parts.
  - Academic-reviewer prompt `:541`. — EXTRACT_TEMPLATE.
  - Revise-title/abstract/section prompts `:621` / `:630` / `:638`.
    — EXTRACT_TEMPLATE.
  - Fill-in writer `_system_prompt_a` `:1486`. — EXTRACT_TEMPLATE.
  - LaTeX figure-inserter one-liner `:1638`. — EXTRACT_TEMPLATE.
  - Paper-writer `_system_prompt` `:1659`. — EXTRACT_TEMPLATE.
  - `_GLOBAL_COHERENCE` editor `:2543` (5 hard-constraint rules + JSON edit
    schema; appends `_paper_language_directive()` at runtime). — EXTRACT_TEMPLATE
    for the static skeleton; keep the `+ _paper_language_directive()` suffix in
    code.
- **Venue/rubric-parameterized paper prompts** (`ari-skill-paper/src/`): the
  author-hint block at `server.py:353` (sourced from
  `config/reviewer_rubrics/*.yaml` `prompt_overrides.author_hint`) and
  `review_engine.py:58 build_system_prompt` (`:80` rigorous peer reviewer, `:443`
  Area Chair) + `review_engine.py:105 build_user_prompt`. — MOVE_TO_CONFIGURABLE_PROMPT:
  externalize only the **static scaffolding** into templates; the dynamic
  `rubric.venue` / `rubric.domain` / `rubric.system_hint` / dimension-line
  injection stays in Python. `ari-skill-paper/src/rubric.py` (344 LOC) is a rubric
  **builder**, not prompt text — leave untouched.
- Provide a loader mechanism for `ari-skill-paper` (skill-local `read_text`
  helper mirroring `ari-skill-replicate`, or the 036-provided shared loader) and
  a `ari-skill-paper/src/prompts/README.md` index.

Out of scope but adjacent (belongs to sibling subtasks 037-040, 042-044): the
still-hardcoded prompts in `ari-skill-evaluator`, `ari-skill-plot`,
`ari-skill-vlm`, `ari-skill-transform`, `ari-skill-web`, `ari-skill-idea`, and
`ari-skill-paper-re`.

## 4. Non-Goals

- **No prompt-text edits.** Extraction is verbatim; not a wording/quality pass.
- **No merge of the two peer-reviewer prompts.** `review_engine.py:80/:443`
  overlaps conceptually with core `ari/prompts/evaluator/peer_review.md` but they
  are **not byte-identical** (confirmed). Consolidating them is REVIEW_REQUIRED
  and belongs to a dedicated dedup subtask, not here.
- **No change to `SECTION_PROMPTS`/`_FORBIDDEN_NOTICE` semantics**, only their
  storage location.
- **No modification of `ari/pipeline/orchestrator.py` or the stage/driver model**
  — that is subtask 012's territory; this subtask does not depend on it.
- **No change to `config/reviewer_rubrics/*.yaml`** schema or the
  `prompt_overrides.author_hint` field.
- **No conversion to Jinja/`.j2`.** Keep the `str.format` + `.md` convention.
- No new `ari-core → ari-skill-paper` dependency; no `ari-skill-paper → ari-core`
  dependency introduced merely to reach `ari.prompts`.

## 5. Current Files / Directories to Inspect

Core prompt infrastructure (reference model — do not modify):
- `ari-core/ari/prompts/_loader.py` (49 LOC) — `FilesystemPromptLoader`,
  `PromptLoader` Protocol, `load_versioned`.
- `ari-core/ari/prompts/__init__.py` (12 LOC) — re-exports.
- `ari-core/ari/prompts/README.md` — externalized-template index/format doc.
- `ari-core/ari/prompts/pipeline/keyword_librarian.md` (352 B) — the one
  externalized pipeline prompt.
- `ari-core/ari/prompts/pipeline/README.md`.

Pipeline (audit target):
- `ari-core/ari/pipeline/context_builder.py` (140 LOC) — loads
  `pipeline/keyword_librarian` at `:116-117`.
- `ari-core/ari/pipeline/stage_runner.py` (471 LOC) — ReAct `system_prompt`
  from YAML `react_cfg` at `:129` (config-driven; dormant path).
- `ari-core/ari/pipeline/orchestrator.py` (913 LOC), `yaml_loader.py` (103 LOC),
  `experiment_md.py`, `verified_context.py`, `stage_control.py`,
  `__init__.py` — confirm no other embedded prompt text.
- `ari-core/config/workflow.yaml` (629 LOC) — paper-generation stages that
  consume the paper skill: `generate_ear` (`:114`), `generate_figures`
  (tool `generate_figures_llm`, `:144`), `write_paper` (tool
  `write_paper_iterative`, `:178-180`), `review_paper` (`:261`), `paper_refine`
  (`:323-325`), `render_paper` (`:337`).

Paper skill (extraction target):
- `ari-skill-paper/src/server.py` (2956 LOC). Prompt sites (verified):
  `SECTION_PROMPTS` dict `:66`; `_FORBIDDEN_NOTICE` `:126`; section assembly
  `:302`, `:306`, `:353` (author-hint), `:362`; academic reviewer `:541`;
  revise `:621` / `:630` / `:638`; fill-in writer `:1486`; figure inserter
  `:1638`; paper writer `:1659`; `_GLOBAL_COHERENCE` `:2543`. MCP tool entry
  points near `:1053 write_paper_iterative`, `:2446 paper_refine`, and the other
  `@mcp.tool()` decorators at `:185,191,254,402,454,526,593,2083,2234,2371,2740,2849`.
- `ari-skill-paper/src/review_engine.py` (489 LOC): `:58 build_system_prompt`,
  `:80` rigorous peer reviewer, `:105 build_user_prompt`, `:443` Area Chair.
- `ari-skill-paper/src/rubric.py` (344 LOC) — rubric builder, **inspect only**.
- `ari-skill-paper/src/` layout: `claim_links.py`, `review_engine.py`,
  `rubric.py`, `server.py`, `README.md`, `__init__.py` — **no `prompts/` dir**.
- `config/reviewer_rubrics/*.yaml` (`prompt_overrides.author_hint` source for
  `server.py:353`).

Skill-local loader precedents (pattern to mirror):
- `ari-skill-replicate/src/generator.py:26,64,77,93` + `ari-skill-replicate/src/prompts/`
  (`skeleton.md`, `subtree.md`, `adversarial_reviewer.md`, `rubric_audit.md`).
- `ari-skill-paper-re/src/server.py:66` + `ari-skill-paper-re/src/prompts/replicator.md`.

## 6. Current Problems

1. **~10 hardcoded paper prompts** live inside the repo's largest Python file
   (`ari-skill-paper/src/server.py`, 2956 LOC), making prompt review and A/B
   iteration require Python edits and risking accidental logic changes.
2. **No version pinning for paper prompts.** Even the already-externalized
   skill prompts (`replicate`, `paper-re`) use bare `read_text()` and skip the
   `load_versioned` sha256 pin that core prompts get — so a paper-prompt change
   cannot be reproducibility-tracked the way core prompts can. (REVIEW_REQUIRED.)
3. **Mechanism split**: core uses `FilesystemPromptLoader`; skills use `read_text`.
   `ari-skill-paper` has neither and cannot cheaply reach the core loader (no
   existing `ari-core` dependency; adding one would couple a skill to core).
4. **Conceptual duplication** between `review_engine.py:80/:443` peer-reviewer
   prompts and core `ari/prompts/evaluator/peer_review.md` — two "peer reviewer"
   prompt homes, not byte-identical, easy to drift. (Flag only; do not merge here.)
5. **Mixed static/dynamic assembly**: several paper prompts concatenate a static
   skeleton with runtime injection (`_GLOBAL_COHERENCE` `:2543` +
   `_paper_language_directive()`; section writer `:362` + `author_hint_block` +
   `_cite_hint` + `_FORBIDDEN_NOTICE`). Extraction must split cleanly so only the
   static skeleton moves to `.md`.

## 7. Proposed Design / Policy

**Policy P-041-A (verbatim extraction).** Move only static prompt text; the moved
bytes must equal the current bytes exactly. Add a test that reconstructs each
prompt from `template.format(...)` and asserts equality against a captured golden
(see Section 12), so the extraction is provably byte-neutral.

**Policy P-041-B (static/dynamic boundary).** For each paper prompt, extract the
static skeleton to `ari-skill-paper/src/prompts/<key>.md` and keep dynamic
fragments as Python-side `str.format` arguments or trailing concatenations:
- `_GLOBAL_COHERENCE`: template holds rules 1-5 + JSON schema; code appends
  `_paper_language_directive()`.
- Section writer: template = `SECTION_PROMPTS[section]` body; code still appends
  `author_hint_block`, `_cite_hint`, `_FORBIDDEN_NOTICE`, and venue lines.
- `review_engine.build_system_prompt`: template holds the "You are a rigorous
  peer reviewer for {venue} ({domain})…" scaffold; `rubric.system_hint` and
  dimension lines are injected via placeholders.

**Policy P-041-C (loader for the paper skill).** Adopt the **skill-local
`read_text` pattern** already used by `ari-skill-replicate`
(`PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"`), i.e. introduce
`ari-skill-paper/src/prompts/` and a small module-level `PROMPTS_DIR` +
`_load_prompt(key)` helper. If subtask 036 delivers a shared versioned loader
usable without a skill→core coupling, prefer that instead and record the choice.
Either way, expose a `load_versioned`-equivalent (sha256[:12]) so paper prompts
gain the reproducibility pin core prompts have (closes Problem 2). — This loader
choice is REVIEW_REQUIRED and should be settled with 036.

**Policy P-041-D (pipeline = audit).** Treat the pipeline half as a
confirm-and-document task. `keyword_librarian.md` is already externalized;
`stage_runner.py:129` is config-driven. If the audit finds a stray embedded
prompt, extract it into `ari-core/ari/prompts/pipeline/<key>.md` via the existing
`FilesystemPromptLoader` (core already depends on it) and update the pipeline
`README.md`. Expected outcome: **no code change** on the pipeline side.

**Classification summary**

| Item | File:line | Class |
|---|---|---|
| `keyword_librarian.md` | `context_builder.py:117` | KEEP (already externalized; reference) |
| ReAct `system_prompt` | `stage_runner.py:129` | KEEP (config-driven via `react_cfg`) |
| `SECTION_PROMPTS`, `_FORBIDDEN_NOTICE` | `server.py:66,126` | EXTRACT_TEMPLATE |
| Section writer skeleton | `server.py:302,306,362` | EXTRACT_TEMPLATE |
| Academic reviewer | `server.py:541` | EXTRACT_TEMPLATE |
| Revise title/abstract/section | `server.py:621,630,638` | EXTRACT_TEMPLATE |
| Fill-in writer | `server.py:1486` | EXTRACT_TEMPLATE |
| LaTeX figure inserter | `server.py:1638` | EXTRACT_TEMPLATE |
| Paper writer | `server.py:1659` | EXTRACT_TEMPLATE |
| `_GLOBAL_COHERENCE` | `server.py:2543` | EXTRACT_TEMPLATE (static skeleton) |
| Author-hint block | `server.py:353` | MOVE_TO_CONFIGURABLE_PROMPT |
| `build_system_prompt`/`build_user_prompt` | `review_engine.py:58,80,105,443` | MOVE_TO_CONFIGURABLE_PROMPT |
| peer_review vs `evaluator/peer_review.md` | `review_engine.py:80` | MERGE_DUPLICATE / REVIEW_REQUIRED (defer) |
| Skill loader mechanism | new `prompts/` dir | REVIEW_REQUIRED (settle with 036) |
| `rubric.py` builders | `rubric.py` | KEEP (not prompt text) |

## 8. Concrete Work Items

1. **Pipeline audit.** `grep -rn "You are\|system_prompt\s*=\|SYSTEM_PROMPT"
   ari-core/ari/pipeline/*.py`; confirm only `stage_runner.py:129` (config) and
   the `keyword_librarian` load remain. Record the result in the PR description.
   Extract any stray prompt into `ari/prompts/pipeline/<key>.md` (expected: none).
2. **Create `ari-skill-paper/src/prompts/`** with a `README.md` index that
   mirrors `ari-core/ari/prompts/pipeline/README.md` style, plus a
   `PROMPTS_DIR` + `_load_prompt`/`_load_prompt_versioned` helper in the skill
   (or wire the 036 shared loader).
3. **Extract module constants**: move `SECTION_PROMPTS` (`:66`) section bodies to
   per-section templates (e.g. `prompts/section_introduction.md`,
   `section_related_work.md`, `section_method.md`, `section_experiment.md`, …) and
   `_FORBIDDEN_NOTICE` (`:126`) to `prompts/forbidden_notice.md`. Preserve
   brace-escaping (`str.format` doubling `{{ }}`) exactly.
4. **Extract inline server prompts** at `:302,306,362` (assembly),
   `:541` (`prompts/academic_reviewer.md`), `:621/630/638`
   (`prompts/revise_title.md` / `revise_abstract.md` / `revise_section.md`),
   `:1486` (`prompts/fill_in_writer.md`), `:1638`
   (`prompts/figure_inserter.md`), `:1659` (`prompts/paper_writer.md`), `:2543`
   (`prompts/global_coherence.md`). Replace each literal with a load call; keep
   the trailing dynamic concatenations (`_paper_language_directive()`,
   `author_hint_block`, `_cite_hint`) in code.
5. **Extract review-engine scaffolds** (`review_engine.py:80,443`) into
   `prompts/peer_reviewer.md` and `prompts/area_chair.md`, injecting
   `rubric.venue`, `rubric.domain`, `rubric.system_hint`, and dimension lines via
   placeholders; keep `build_user_prompt` dynamic assembly (`:105`) in code.
6. **Author-hint**: leave `config/reviewer_rubrics/*.yaml`
   `prompt_overrides.author_hint` as the source; extract only the static wrapper
   text at `server.py:353` (`══ VENUE-SPECIFIC AUTHOR GUIDANCE ══` frame) into a
   template.
7. **Version pin**: expose the sha256[:12] of each loaded paper prompt so it can
   flow into the run's reproducibility record the same way core prompts do
   (coordinate with 036 / verified-context wiring).
8. **Docs**: update `ari-skill-paper/src/README.md` (note new `prompts/` dir) and
   add `ari-skill-paper/src/prompts/README.md`. Keep the DELETE `evaluator/peer_review.md`
   duplication out of scope (defer to a dedup subtask), but add a one-line
   cross-reference note.
9. **Guard alignment**: ensure the new `.md` files satisfy any prompt lint that
   036 introduces (`check_prompts.py` is listed as MISSING / to-be-designed — do
   not implement it here).

## 9. Files Expected to Change

Created (implementation phase):
- `ari-skill-paper/src/prompts/` (new directory) with `.md` templates:
  `forbidden_notice.md`, `section_introduction.md`, `section_related_work.md`,
  `section_method.md`, `section_experiment.md` (and any remaining
  `SECTION_PROMPTS` keys), `academic_reviewer.md`, `revise_title.md`,
  `revise_abstract.md`, `revise_section.md`, `fill_in_writer.md`,
  `figure_inserter.md`, `paper_writer.md`, `global_coherence.md`,
  `author_hint_frame.md`, `peer_reviewer.md`, `area_chair.md`, and `README.md`.
  (Exact filename set finalized during implementation from the verified prompt
  sites in Section 5.)

Modified (implementation phase):
- `ari-skill-paper/src/server.py` (2956 LOC) — replace inline literals at the
  sites listed in Section 5 with loader calls; add `PROMPTS_DIR`/`_load_prompt`.
- `ari-skill-paper/src/review_engine.py` (489 LOC) — `build_system_prompt`
  (`:58/:80/:443`) load static scaffold from templates.
- `ari-skill-paper/src/README.md` — mention the new `prompts/` dir.

Possibly modified (only if the pipeline audit finds a stray prompt — expected
none):
- `ari-core/ari/prompts/pipeline/` (+ its `README.md`) and the corresponding
  `ari-core/ari/pipeline/*.py` load site.

New tests (implementation phase):
- A byte-equality golden test under `ari-skill-paper/tests/` (or the repo's skill
  test location) verifying each extracted prompt reconstructs identically.

Explicitly **not** changed: `ari-skill-paper/src/rubric.py`,
`ari/pipeline/orchestrator.py`, `config/reviewer_rubrics/*.yaml`,
`config/workflow.yaml`, `ari/prompts/_loader.py`.

## 10. Files / APIs That Must Not Be Broken

- **MCP tool contracts of `ari-skill-paper`** (`@mcp.tool()` entry points incl.
  `write_paper_iterative` `:1053`, `paper_refine` `:2446`, and those at
  `:185,191,254,402,454,526,593,2083,2234,2371,2740,2849`): names, signatures,
  and returned artifacts unchanged. Prompt extraction is internal.
- **Pipeline stage contract** (`config/workflow.yaml`): stages `generate_ear`,
  `generate_figures`, `write_paper`, `review_paper`, `paper_refine`,
  `render_paper` must produce identical outputs — enforced by the byte-exact
  prompt policy.
- **`ari.prompts` public loader** (`FilesystemPromptLoader`, `PromptLoader`
  re-exported via `ari/protocols/__init__.py:20`): do not change its signature;
  core call sites (incl. `context_builder.py:117`) stay valid.
- **`config/reviewer_rubrics/*.yaml` `prompt_overrides.author_hint`** field:
  format and consumption at `server.py:353` unchanged.
- **No skill↔core coupling regression**: `ari-skill-paper` must not gain an
  `ari-core` import (it has none today); `ari-core` must not import
  `ari-skill-paper`.
- **P2 determinism**: identical model input bytes for the same run inputs; the
  reproducibility pin (`load_versioned` sha) may be *added* but existing pins for
  core prompts must not shift.

## 11. Compatibility Constraints

- **Verbatim / byte-exact** extraction is the primary constraint; a golden test
  guards it. Preserve `str.format` brace-doubling and all whitespace/newlines
  (note `keyword_librarian.md` and the viz wizard prompts intentionally have no
  trailing newline — mirror that discipline for extracted files where the
  original literal had none).
- **`.md` + `str.format`** convention only; no Jinja, no `.j2`.
- **Loader choice deferred to 036**: if 036 has not landed a shared loader, use
  the skill-local `read_text` pattern (parity with `ari-skill-replicate`) and
  leave a TODO cross-referencing 036; do not block on 036 to complete 041's
  extraction.
- **Peer-reviewer dedup is a compatibility hazard**: do not "helpfully" collapse
  `review_engine.py:80` into `evaluator/peer_review.md` — they differ byte-wise
  and feed different consumers; changing either alters output. Leave both,
  cross-reference only.

## 12. Tests to Run

From repo root (`/home/t-kotama/workplace/ARI`):

- `python -m compileall ari-skill-paper ari-core/ari/pipeline ari-core/ari/prompts`
  (or `python -m compileall .`) — import/syntax check after edits.
- `pytest -q` — full suite. Targeted:
  - any `ari-skill-paper` prompt/golden test added by this subtask;
  - pipeline tests exercising paper stages (search `ari-core/tests/` for
    `write_paper` / `paper_refine` / `review_paper` references, e.g.
    `test_workflow_contract.py` 1606 LOC, `test_server.py` 1844 LOC).
- `ruff check .` — lint the changed Python and the new loader helper.
- **Byte-equality assertion** (new): for every extracted prompt, assert
  `loaded_template.format(**captured_args)` (or the template alone for static
  ones) equals the pre-extraction golden string captured at the corresponding
  `server.py`/`review_engine.py` line.

No frontend (`npm test` / `npm build`) is involved — this subtask touches no
`ari-core/ari/viz/frontend/` files.

## 13. Acceptance Criteria

1. **Pipeline audit documented**: PR states that `ari/pipeline/*.py` carries no
   embedded LLM prompt beyond the externalized `keyword_librarian` load and the
   config-driven `stage_runner.py:129` ReAct block (or lists and extracts any
   stray prompt found).
2. **All targeted paper prompts externalized**: every EXTRACT_TEMPLATE and
   MOVE_TO_CONFIGURABLE_PROMPT item in Section 7 lives in
   `ari-skill-paper/src/prompts/*.md`; `server.py`/`review_engine.py` load them.
3. **Byte-exact**: the golden reconstruction test passes for every extracted
   prompt; no LLM-visible bytes changed.
4. **Loader present** in `ari-skill-paper` (skill-local or 036-shared), with a
   version-pin (sha256[:12]) available for paper prompts.
5. **Contracts intact**: paper MCP tools, workflow stages, `ari.prompts` loader,
   and `reviewer_rubrics` `author_hint` all unchanged; `pytest -q`, `ruff check .`,
   `python -m compileall .` all green.
6. **Docs updated**: `ari-skill-paper/src/prompts/README.md` added;
   `ari-skill-paper/src/README.md` references the new dir; peer-reviewer dedup is
   cross-referenced (not performed).
7. **No new coupling**: `ari-skill-paper` still has zero `ari-core` imports.

## 14. Rollback Plan

The change is mechanical and self-contained (one skill package + optional
`ari.prompts/pipeline` docs). Rollback options, in order of preference:

1. **Git revert** the implementation commit(s); because the extraction is
   byte-exact, reverting restores identical behavior with zero data migration.
2. **Fallback-in-place**: if a prompt file is missing/misread at runtime, the
   loader helper can fall back to a Python constant kept for one release cycle
   (optional belt-and-suspenders; the golden test makes this unlikely to be
   needed). Remove the fallback in a follow-up once stable.
3. No checkpoint/output/config format changes are introduced, so there is nothing
   to migrate back; existing `workspace/checkpoints/*` remain valid.

## 15. Dependencies

Per the dependency graph, `036 -> 037, 038, 039, 040, 041, 042, 043, 044`:
- **Hard prerequisite: 036** (Phase 7 root, "prompt management" foundation). Its
  planning doc **does not exist yet** (`docs/refactoring/subtasks/036_*.md` is
  absent). 036 is expected to define the shared prompt loader/policy and any
  `check_prompts.py` guard that 041 aligns to. 041's extraction can proceed
  against the existing `ari.prompts` loader if 036's shared loader is not yet
  available (see Policy P-041-C), but 036 must precede per the graph.
- **Inventory prerequisites** (must precede any runtime code change, per the
  master list): **001** (measure complexity/dependencies) and **002** (inventory
  legacy/obsolete/duplicate code). These establish the baseline the extraction is
  measured against.
- **Sibling subtasks 037-044** are the other Phase 7 prompt-extraction children of
  036; they are **independent of 041** (each targets different skills) but should
  agree on the loader mechanism 036 sets. No ordering among siblings is implied.
- **Soft coordination (not a hard dep): 012** (refactor pipeline stage
  architecture) also touches `ari/pipeline/`. 041 does **not** modify
  `orchestrator.py`, so there is no hard dependency; if both land close together,
  rebase the trivial pipeline-audit note.

Nothing in this subtask depends on the `020` viz family, the `045`/`053`/`059`
chains, or `067`.

## 16. Risk Level

**Medium.**

- **Runtime code change: Yes** (when implemented) — modifies
  `ari-skill-paper/src/server.py` and `review_engine.py` and adds
  `ari-skill-paper/src/prompts/`. The pipeline half is expected to be
  audit-only (no code change).
- Why not Low: the extracted text is **LLM-facing and P2-determinism-sensitive**
  — any accidental byte drift silently changes paper/reviewer output. Mitigated
  by the byte-exact golden test (Section 12) and verbatim policy.
- Why not High: no public API, MCP tool signature, checkpoint/config format, or
  frontend surface changes; it is a localized, revertible, behavior-preserving
  move within a single skill package plus docs.

## 17. Notes for Implementer

- Start with the **pipeline audit** (cheap, likely a no-op) to close that half,
  then focus effort on `ari-skill-paper/src/server.py` (2956 LOC).
- Watch **brace escaping**: `SECTION_PROMPTS` bodies contain literal
  `\cite{authorYYYYkeyword}` (single-brace in the dict literal) while the
  assembly at `:302-378` uses `.format` with **doubled** `{{ }}` for LaTeX
  literals (e.g. `\begin{{document}}`). When moving text into a `.md` filled by
  `str.format`, replicate whichever escaping the original call site used, or the
  reconstruction test will catch a mismatch.
- Keep dynamic suffixes in code, not templates: `_GLOBAL_COHERENCE` ends with
  `+ _paper_language_directive()` (`server.py:2560`); the section writer appends
  `author_hint_block` + `_cite_hint` + `_FORBIDDEN_NOTICE` + venue lines. Extract
  only the static scaffold.
- The **author-hint** at `server.py:353` already reads its variable text from
  `config/reviewer_rubrics/*.yaml` (`prompt_overrides.author_hint`) via
  `load_rubric(venue)`; only the `══ VENUE-SPECIFIC AUTHOR GUIDANCE ══` wrapper
  is static. Venues without a rubric YAML (arxiv/icpp/acm/isc) fall through to
  no-op — preserve that fallback.
- **Do not** touch `ari-skill-paper/src/rubric.py` (344 LOC, a builder) or the
  vendored PaperBench templates elsewhere (`ari-skill-paper-re/src/_paperbench_bridge.py`
  is KEEP_INLINE for upstream parity — out of this subtask's scope).
- For the loader, the cleanest precedent is `ari-skill-replicate/src/generator.py:26`
  (`PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"`). Add a
  `load_versioned`-equivalent so paper prompts gain the sha256[:12] pin that
  `ari.prompts._loader.py:load_versioned` provides for core prompts.
- Reminder: there is **no `sonfigs/`** directory anywhere in the repo (a
  hypothesized typo); config data lives in `ari-core/ari/config/` (locator code),
  `ari-core/ari/configs/` (packaged defaults), and top-level `config/` (rubric
  data). None of these are prompt stores and none are touched here.
- Leave a single-line cross-reference noting the `review_engine.py:80/:443` vs
  `ari/prompts/evaluator/peer_review.md` overlap for the future dedup subtask;
  do **not** merge them here.

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **041** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
