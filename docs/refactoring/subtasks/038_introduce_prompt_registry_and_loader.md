# Subtask 038: Introduce Prompt Registry And Loader

> Phase 7: Prompt Management · Risk: Medium · Runtime code change: **Yes (additive, non-breaking)**
> Layers a discoverable, validated **prompt registry** on top of the already-shipped
> `FilesystemPromptLoader`, giving the rest of Phase 7 (037, 039–044) a single canonical
> accessor to migrate the still-hardcoded and skill-local prompts into.

---

## 1. Goal

Introduce a **prompt registry** — a central, discoverable, self-validating catalogue of
prompt-template keys — in `ari-core/ari/prompts/`, wrapping (not replacing) the existing
`FilesystemPromptLoader`. The registry gives ARI:

- one canonical way to enumerate every externalized prompt key (`agent/system`,
  `evaluator/peer_review`, `orchestrator/bfts_expand`, …) with its on-disk path, content
  hash (via `load_versioned`), and — optionally — its expected `str.format` placeholders;
- a single entry point that later Phase 7 subtasks route both **core** call sites (the 11
  lazy `from ari.prompts import FilesystemPromptLoader` sites) and **skill-local** ad-hoc
  loaders (`ari-skill-replicate`, `ari-skill-paper-re`, which today call
  `Path(...).read_text()` and bypass versioning) through;
- a machine-readable surface a future `check_prompts.py` gate (a currently-MISSING checker,
  to be designed as separate tooling — do **not** implement it here) can consume to detect
  prompt drift / orphaned keys / placeholder mismatches.

Classification of this subtask's deliverable: **KEEP (net-new registry) + ADAPT (loader
re-exports)**. The `FilesystemPromptLoader` / `PromptLoader` Protocol / `load_versioned`
mechanism is KEEP — it is correct and already used at 11 sites; this subtask does **not**
rewrite it, only adds a registry layer above it.

This subtask is the **mechanism-only** foundation of Phase 7. It does **not** move any
prompt text, does **not** touch skill code, and does **not** consolidate duplicate prompts.
Those are downstream siblings (039–044).

---

## 2. Background

Prompts in ARI are **partially externalized** already (verified 2026-07-01):

- **Core loader (exists, KEEP).** `ari-core/ari/prompts/_loader.py` (49 lines) defines
  `package_prompts_root()`, a `PromptLoader` `Protocol`, and a concrete
  `FilesystemPromptLoader`. `load(key)` reads `{base}/{key}.md`; `load_versioned(key)`
  returns `(text, sha256(text)[:12])` for reproducibility pinning. Templates are `.md`
  (confirmed — **not** `.j2`), filled with Python `str.format(...)` single-brace `{name}`
  placeholders at the call site.
- **Re-export chain (documented import paths — MUST NOT break).**
  `ari-core/ari/prompts/__init__.py` (12 lines) re-exports `FilesystemPromptLoader`,
  `PromptLoader`, `package_prompts_root`. `ari-core/ari/protocols/__init__.py:20`
  additionally re-exports `PromptLoader` (`from ari.prompts._loader import PromptLoader`).
- **Externalized core templates (11 `.md` + 5 per-dir READMEs)** under
  `ari-core/ari/prompts/`: `agent/system.md`; `evaluator/{extract_metrics,peer_review}.md`;
  `orchestrator/{bfts_expand,bfts_expand_select,bfts_select,lineage_decision,root_idea_selector}.md`;
  `pipeline/keyword_librarian.md`; `viz/{wizard_chat_goal,wizard_generate_config}.md`.
  (Note: `pipeline/keyword_librarian.md`, `viz/wizard_chat_goal.md`,
  `viz/wizard_generate_config.md` report `wc -l` = 0 because they have no trailing newline —
  they are **populated, not empty**.)
- **Core load sites (11 files, all lazy in-function imports).** Verified via grep:
  `agent/loop.py:51`, `evaluator/llm_evaluator.py:255,413`,
  `orchestrator/bfts.py:475,553,743`, `orchestrator/lineage_decision.py:293`,
  `orchestrator/root_idea_selector.py:63`, `pipeline/context_builder.py:116`,
  `viz/api_tools.py:54,126`. Each constructs `FilesystemPromptLoader()` inline and calls
  `.load(key).format(...)`.
- **Config-injected keys (important edge case).** Two BFTS prompt keys are **not**
  hardcoded at the call site — they are Pydantic config fields:
  `ari-core/ari/config/__init__.py:133` `select_prompt` (default `"orchestrator/bfts_select"`)
  and `:142` `expand_select_prompt` (default `"orchestrator/bfts_expand_select"`), each
  described in-code as a "FilesystemPromptLoader key". `orchestrator/bfts.py:475,553` load
  whatever key the config supplies. The registry must therefore treat config-supplied keys
  as first-class and must **not** hard-fail a run when a key it did not statically discover
  is requested.
- **Skill-local loaders (inconsistent — REVIEW_REQUIRED, migrated later).** Some skills
  externalize prompts but bypass the core loader (no versioning/hash):
  `ari-skill-replicate/src/prompts/` (`skeleton.md`, `subtree.md`, `adversarial_reviewer.md`,
  `rubric_audit.md`) loaded via `PROMPTS_DIR / "x.md").read_text()` at `generator.py:64,77,93`
  and `auditor.py:130`; `ari-skill-paper-re/src/prompts/replicator.md` loaded at
  `server.py:66`. This mechanism inconsistency is the primary motivation for a shared
  registry, but **migrating these skills is out of scope for 038** (see Non-Goals).
- **Still-hardcoded prompts (extract targets for 039–044, NOT 038).** e.g.
  `ari-skill-evaluator/src/server.py:191` `_METRIC_EXTRACT_SYS`, `:790`
  `_SEMANTIC_SYSTEM_PROMPT`; five inline `You are …` prompts in
  `ari-skill-paper/src/server.py` (`:542,1487,1638,1660,2544`). 038 provides the *destination
  mechanism*; it does not perform the extraction.

**Why a registry, given the loader already exists?** The loader answers "given a key, read
its file." It cannot answer "what keys exist?", "which module owns this key?", "does this
template's placeholder set match what the caller passes?", or "is a shipped `.md` orphaned
(no code loads it)?". Those questions are what unblock the rest of Phase 7 and a future
`check_prompts.py` gate. A registry is the smallest addition that answers them.

There is **no `sonfigs/`** anywhere in the repo (the master prompt's "sonfigs" is a
hypothesized typo, confirmed absent) — irrelevant to this subtask beyond noting it so the
implementer does not go looking for a prompts equivalent.

---

## 3. Scope

In scope (all **additive**):

1. Add `ari-core/ari/prompts/registry.py` — a `PromptRegistry` class that:
   - discovers every `*.md` under `package_prompts_root()` (excluding `README.md`),
     deriving the logical key from the path relative to the root minus the `.md` suffix
     (e.g. `orchestrator/bfts_expand.md` → key `orchestrator/bfts_expand`);
   - wraps a `PromptLoader` (default `FilesystemPromptLoader`) via dependency injection, so
     tests can substitute a stub loader (mirroring the existing loader's test-swap design);
   - exposes: `keys() -> list[str]` (sorted), `has(key) -> bool`, `get(key) -> str`
     (delegates to the wrapped loader), `get_versioned(key) -> tuple[str, str]`,
     `describe(key) -> PromptEntry` (path, discovered-or-not flag, content hash, extracted
     placeholder set), and `placeholders(key) -> set[str]` (parsed from the template with
     `string.Formatter().parse`, tolerant of `{{`/`}}` escapes);
   - is **tolerant of config-injected keys**: `get`/`get_versioned` on a key not in the
     discovered set falls back to the wrapped loader (which raises `FileNotFoundError` only
     if the `.md` truly does not exist), so `bfts.py` config-driven loads keep working.
2. Re-export `PromptRegistry` (and any small `PromptEntry` dataclass) from
   `ari-core/ari/prompts/__init__.py`, additively, without removing existing exports.
3. Update `ari-core/ari/prompts/README.md` `## Contents` to list `registry.py`
   (**required** — the `readme_sync` pre-commit hook + `readme-sync.yml` CI gate check this;
   see §11).
4. Add unit tests `ari-core/tests/test_prompt_registry.py`.
5. Optionally re-export `PromptRegistry` from `ari-core/ari/protocols/__init__.py` **only if**
   a structural Protocol is warranted; default is to keep the registry a concrete class and
   leave `ari.protocols` exposing only the `PromptLoader` Protocol (avoid over-abstraction).

Out of scope: everything in §4.

---

## 4. Non-Goals

- **Not** moving/extracting any still-hardcoded prompt (`_SEMANTIC_SYSTEM_PROMPT`,
  `ari-skill-paper` `You are …` blocks, etc.) — those are siblings 039–044.
- **Not** migrating skill-local loaders (`ari-skill-replicate`, `ari-skill-paper-re`) off
  `read_text()` onto the registry — that is a later Phase 7 subtask; 038 only makes the
  destination mechanism available.
- **Not** consolidating duplicate/overlapping prompts (e.g. `review_engine.py`
  `build_system_prompt` vs core `evaluator/peer_review.md`; `_METRIC_EXTRACT_SYS` vs
  `evaluator/extract_metrics.md`) — REVIEW_REQUIRED, handled separately.
- **Not** changing any prompt **text**, key name, placeholder name, or `.md` file.
- **Not** rewriting `FilesystemPromptLoader` or `load_versioned` semantics, and **not**
  changing the existing lazy import call pattern at the 11 core sites (they keep working
  unchanged; rewiring them to the registry, if desired at all, is a downstream task).
- **Not** building the `check_prompts.py` quality gate or wiring any new CI workflow (Phase 8
  / separate tooling subtask). 038 only produces the machine-readable surface it will consume.
- **Not** introducing Jinja2 / `.j2` templating or any new templating dependency — the
  format stays `.md` + `str.format`.
- **Not** touching the vendored `KEEP_INLINE` prompts (`ari-skill-idea` VirSci fallbacks,
  `ari-skill-paper-re/_paperbench_bridge.py` upstream PaperBench templates).

---

## 5. Current Files / Directories to Inspect

Read these before starting (all paths absolute-from-repo-root, verified 2026-07-01):

Core prompts package:
- `ari-core/ari/prompts/_loader.py` (49 L) — `package_prompts_root`, `PromptLoader`
  Protocol, `FilesystemPromptLoader` (`load`, `load_versioned`). **The thing the registry
  wraps.**
- `ari-core/ari/prompts/__init__.py` (12 L) — existing re-exports to extend additively.
- `ari-core/ari/prompts/README.md` (37 L) — `## Contents` index to update.
- `ari-core/ari/protocols/__init__.py` — re-exports `PromptLoader` at line 20; note the
  "More Protocols … land in subsequent phases" docstring.

Externalized templates (the discovery target — do not modify):
- `ari-core/ari/prompts/agent/system.md` (13 L) + `agent/README.md`
- `ari-core/ari/prompts/evaluator/{extract_metrics.md (16 L), peer_review.md (11 L)}` + `evaluator/README.md`
- `ari-core/ari/prompts/orchestrator/{bfts_expand.md (16 L), bfts_expand_select.md (8 L), bfts_select.md (15 L), lineage_decision.md (6 L), root_idea_selector.md (6 L)}` + `orchestrator/README.md`
- `ari-core/ari/prompts/pipeline/keyword_librarian.md` (populated, no trailing newline) + `pipeline/README.md`
- `ari-core/ari/prompts/viz/{wizard_chat_goal.md, wizard_generate_config.md}` (populated, no trailing newline) + `viz/README.md`

Core load sites (understand the call pattern; do NOT rewire in 038):
- `ari-core/ari/agent/loop.py:51` (`_SYSTEM_PROMPT_KEY`)
- `ari-core/ari/evaluator/llm_evaluator.py:255` (`evaluator/extract_metrics`), `:413`
  (`evaluator/peer_review`, `.format(axes_block=…)`)
- `ari-core/ari/orchestrator/bfts.py:475,553,743`
- `ari-core/ari/orchestrator/lineage_decision.py:293`
- `ari-core/ari/orchestrator/root_idea_selector.py:63`
- `ari-core/ari/pipeline/context_builder.py:116`
- `ari-core/ari/viz/api_tools.py:54,126`

Config-injected keys (the tolerance requirement):
- `ari-core/ari/config/__init__.py:133` (`select_prompt`), `:142` (`expand_select_prompt`).

Skill-local loaders (context only; migration is out of scope):
- `ari-skill-replicate/src/generator.py:26,64,77,93` and `auditor.py:17,130` (`PROMPTS_DIR`).
- `ari-skill-paper-re/src/server.py:66` and `src/prompts/replicator.md`.

House conventions to match:
- `scripts/readme_sync.py` — per-directory `## Contents` drift gate (stdlib-only).
- An existing sibling test for structure, e.g. anything under `ari-core/tests/`.

---

## 6. Current Problems

1. **No enumeration surface.** Nothing can answer "what prompt keys exist?" There is no way
   to list the 11 core templates programmatically, so a drift/orphan checker cannot be built
   and Phase 7 migration has no authoritative catalogue to grow into.
2. **Two divergent loading mechanisms.** Core uses `FilesystemPromptLoader` (versioned,
   hashable); skills use raw `Path.read_text()` (unversioned). There is no shared object
   through which both can flow, so reproducibility pinning is inconsistent across
   core-vs-skill boundaries. (Registry is the enabling mechanism; actual skill migration is
   later.)
3. **Repetitive, un-abstracted call pattern.** 11 core sites each re-instantiate
   `FilesystemPromptLoader()` inline and call `.load(key).format(...)`. There is no shared
   accessor, so cross-cutting concerns (validation, placeholder checking, hashing for a run
   manifest) cannot be added in one place.
4. **No placeholder validation.** Templates are filled with `str.format`; a missing/renamed
   `{placeholder}` surfaces only as a `KeyError`/`IndexError` at runtime deep inside an agent
   loop. Nothing compares a template's declared placeholders against what callers pass.
5. **Orphan risk.** A `.md` can be added or a key renamed with no automated check that a
   loader actually references it (or vice-versa). The config-injected keys
   (`select_prompt`/`expand_select_prompt`) make this worse: a key can be "used" only via a
   config string, invisible to a naive grep.

---

## 7. Proposed Design / Policy

### 7.1 Layering (do not break the loader)

```
callers (core sites, later: skills)
        │  get(key) / get_versioned(key) / placeholders(key) / keys()
        ▼
  PromptRegistry            ← NEW (038): discovery + validation + catalogue
        │  load(key) / load_versioned(key)
        ▼
  PromptLoader Protocol     ← KEEP: FilesystemPromptLoader (unchanged)
        ▼
  ari-core/ari/prompts/**/*.md
```

The registry **delegates all file reads** to an injected `PromptLoader`. It adds no new I/O
semantics — `get` == `loader.load`, `get_versioned` == `loader.load_versioned`. This keeps
the KEEP contract intact and makes the registry test-swappable exactly like the loader.

### 7.2 `PromptRegistry` shape (illustrative; final names at implementer discretion)

- Construction: `PromptRegistry(loader: PromptLoader | None = None, root: Path | None = None)`.
  Defaults: `loader = FilesystemPromptLoader(root)`, `root = package_prompts_root()`.
- Discovery: on first access (lazy) or in `__init__`, walk `root.rglob("*.md")`, skip any
  file named `README.md`, and register key = `path.relative_to(root).with_suffix("").as_posix()`.
- API:
  - `keys() -> list[str]` — sorted discovered keys.
  - `has(key) -> bool` — key in discovered set.
  - `get(key) -> str` — `self._loader.load(key)`.
  - `get_versioned(key) -> tuple[str, str]` — `self._loader.load_versioned(key)`.
  - `placeholders(key) -> set[str]` — parse the template via
    `string.Formatter().parse(text)`, collect non-`None` field names, ignore `{{`/`}}`.
  - `describe(key) -> PromptEntry` — small frozen dataclass: `key`, `path`, `discovered:
    bool`, `version_id: str`, `placeholders: frozenset[str]`.
- **Tolerance policy (critical):** `get`/`get_versioned`/`placeholders` do **not** require
  `has(key)`. If a caller (e.g. `bfts.py` via config-injected `select_prompt`) requests a
  key the registry did not statically discover, it still delegates to the loader. Only the
  loader's own `FileNotFoundError` (missing `.md`) propagates. This preserves the config
  contract at `ari/config/__init__.py:133,142`.
- **No LLM calls, no network, pure stdlib** (aligns with design principle P2 determinism;
  `string.Formatter`, `pathlib`, `hashlib` are all stdlib — `hashlib` is already used by
  `_loader.py`).

### 7.3 Placeholder metadata: discovery-first, no manifest file

Do **not** introduce a hand-maintained `registry.yaml` manifest in 038 — a second source of
truth invites drift (the exact problem Phase 7 is solving). Derive placeholders **from the
templates themselves** via `string.Formatter().parse`. If a downstream subtask later wants
an owner→key map or an expected-placeholder allowlist for a stricter gate, it can add that as
a separate, explicitly-justified artifact. Keep 038 single-source-of-truth.

### 7.4 What 038 deliberately leaves for later Phase 7 siblings

- Rewiring the 11 core call sites to `PromptRegistry` (optional ergonomics; not required for
  the mechanism to be usable).
- Migrating skill `read_text()` loaders onto a registry (needs the registry to accept
  additional roots; that extension can land when a skill is actually migrated).
- Building `check_prompts.py` (consumes `keys()` / `placeholders()` — Phase 8 / tooling).

---

## 8. Concrete Work Items

1. **Create `ari-core/ari/prompts/registry.py`.** Implement `PromptRegistry` and a frozen
   `PromptEntry` dataclass per §7.2. Reuse `package_prompts_root` and `FilesystemPromptLoader`
   from `._loader`. Module docstring should cite Phase 7 / this subtask ID and state
   "wraps, does not replace, FilesystemPromptLoader". Pure stdlib only.
2. **Extend `ari-core/ari/prompts/__init__.py`** to additively re-export `PromptRegistry`
   (and `PromptEntry` if public). Keep the three existing exports
   (`FilesystemPromptLoader`, `PromptLoader`, `package_prompts_root`) verbatim. Preserve the
   `# noqa: F401` pattern.
3. **Update `ari-core/ari/prompts/README.md` `## Contents`** to add a line for `registry.py`
   (e.g. "`registry.py` — `PromptRegistry`: discovery + placeholder validation over the
   loader."). Run `python scripts/readme_sync.py --check` (or `--write`) to confirm parity.
4. **Add `ari-core/tests/test_prompt_registry.py`** (see §12 for cases).
5. **(Optional, only if justified) re-export `PromptRegistry` from
   `ari-core/ari/protocols/__init__.py`** and add it to that module's docstring "Currently
   exposed" list. Default: skip — the registry is a concrete class, not a structural
   Protocol; over-exposing it adds a documented import path we would then have to keep stable.
6. **Sanity-check discovery against reality:** the registry's `keys()` must return exactly
   the 11 known core keys (`agent/system`, `evaluator/extract_metrics`,
   `evaluator/peer_review`, `orchestrator/bfts_expand`, `orchestrator/bfts_expand_select`,
   `orchestrator/bfts_select`, `orchestrator/lineage_decision`,
   `orchestrator/root_idea_selector`, `pipeline/keyword_librarian`, `viz/wizard_chat_goal`,
   `viz/wizard_generate_config`) and must exclude the 5 `README.md` files. Assert this in a
   test so future template additions are noticed.

---

## 9. Files Expected to Change

Net-new:
- `ari-core/ari/prompts/registry.py` — `PromptRegistry` + `PromptEntry`.
- `ari-core/tests/test_prompt_registry.py` — unit tests.

Modified (small, additive):
- `ari-core/ari/prompts/__init__.py` (12 L) — add `PromptRegistry`/`PromptEntry` re-export.
- `ari-core/ari/prompts/README.md` (37 L) — add `registry.py` to `## Contents` (gate-required).

Modified (optional, only if §8.5 taken):
- `ari-core/ari/protocols/__init__.py` — re-export + docstring line for `PromptRegistry`.

Explicitly **NOT** changed by 038:
- `ari-core/ari/prompts/_loader.py` — KEEP unchanged.
- The 11 `.md` templates — unchanged.
- All 11 core load sites — unchanged.
- Any `ari-skill-*` file — unchanged.
- `ari-core/ari/config/__init__.py` — unchanged (registry is tolerant of its keys).

---

## 10. Files / APIs That Must Not Be Broken

- **Documented import paths (external-facing contract):**
  `from ari.prompts import FilesystemPromptLoader, PromptLoader, package_prompts_root` and
  `from ari.protocols import PromptLoader` must continue to resolve unchanged. Registry
  additions are purely additive to these namespaces.
- **`ari.public.*` STABLE PUBLIC API** — the registry lives in `ari.prompts` (internal), not
  `ari.public`; do not add it to `ari.public`. No `ari.public` surface changes.
- **`FilesystemPromptLoader.load` / `.load_versioned` signatures and return types** — KEEP
  exactly (`load_versioned` returns `(text, sha256[:12])`); reproducibility tooling depends
  on the 12-char hash form.
- **Config contract** `ari/config/__init__.py:133` `select_prompt` / `:142`
  `expand_select_prompt` — a run that sets these to any valid key must still load via
  `orchestrator/bfts.py:475,553`. The registry's tolerance policy (§7.2) preserves this.
- **CLI `ari`**, **MCP tool contracts** (14 `ari-skill-*` `src/server.py`), **dashboard API
  endpoints/schema** (`ari/viz/routes.py` + `api_*.py`, `services/api.ts`), **checkpoint /
  output / config file formats** — none are touched by this subtask; keep it that way.
- **`ari-core -> ari_skill_memory`** and other core↔skill stable interfaces — untouched.

---

## 11. Compatibility Constraints

- **Additive only.** No existing symbol renamed, moved, or removed. Both the `ari.prompts`
  and `ari.protocols` `__init__` changes strictly grow the export list.
- **`readme_sync` gate is blocking.** Adding `registry.py` to `ari-core/ari/prompts/` makes
  the directory's `README.md ## Contents` stale. `scripts/git-hooks/pre-commit` runs
  `scripts/readme_sync.py --write` and `.github/workflows/readme-sync.yml` runs
  `readme_sync.py --check` as a hard gate — the README **must** be updated in the same commit
  or CI fails. Update it (§8.3).
- **No new dependency.** Stdlib only (`pathlib`, `string`, `hashlib`, `dataclasses`,
  `typing`). Do not add Jinja2/`.j2`. `ruff` is available and enforced; `radon` is NOT
  installed (irrelevant here).
- **Determinism (design principle P2).** No LLM calls, no network, no wall-clock/randomness
  in discovery or hashing. `load_versioned`'s content hash must stay machine-independent
  (it already is — `sha256` of file text, not a git SHA).
- **`ari-core/pyproject.toml` packaging.** The `.md` templates are already packaged; a new
  `.py` module needs no packaging change (it is inside the `ari` package). Confirm no
  `MANIFEST`/`package_data` edit is required (it is not — `registry.py` is a normal module).

---

## 12. Tests to Run

Repo-wide gates (run from repo root):
- `python -m compileall .` — byte-compile everything, confirm the new module imports.
- `ruff check .` — lint the new module and edited `__init__`.
- `pytest -q` (or the scoped `pytest ari-core/tests/ -q` used by `refactor-guards.yml`) —
  full suite must stay green; in particular no regression in prompt-loading paths.
- `python scripts/readme_sync.py --check` — confirm the `ari-core/ari/prompts/README.md`
  `## Contents` update matches the tree (mirrors the `readme-sync.yml` CI gate).

New unit tests (`ari-core/tests/test_prompt_registry.py`) — at minimum:
1. `keys()` returns exactly the 11 known core keys and excludes every `README.md` (§8.6).
2. `get("agent/system")` equals `FilesystemPromptLoader().load("agent/system")` (delegation
   parity).
3. `get_versioned("evaluator/peer_review")` returns a 12-char hex hash equal to the loader's.
4. `placeholders("evaluator/peer_review")` includes `axes_block` (matches the
   `.format(axes_block=…)` call at `llm_evaluator.py:413`); `placeholders("bfts_select")`
   includes `experiment_goal`, `memory_context`, `candidates` (per the config field
   description at `config/__init__.py:135`).
5. **Tolerance:** `get("orchestrator/bfts_select")` works even though the key can arrive via
   config; a genuinely-missing key raises `FileNotFoundError` (loader behavior), not a
   registry-specific error that would break config-driven loads.
6. Test-swap: a stub `PromptLoader` injected into `PromptRegistry` is actually used by
   `get`/`get_versioned` (confirms DI, mirrors the loader's own swap design).

(No frontend involved — `npm test` / `npm run build` not applicable to this subtask.)

---

## 13. Acceptance Criteria

- `ari-core/ari/prompts/registry.py` exists; `from ari.prompts import PromptRegistry`
  succeeds.
- `PromptRegistry().keys()` returns exactly the 11 core keys listed in §8.6, README files
  excluded.
- `PromptRegistry().get(k)` / `.get_versioned(k)` are byte-for-byte / hash-for-hash identical
  to `FilesystemPromptLoader()` for every discovered key.
- Config-injected keys (`select_prompt`, `expand_select_prompt`) still load; the tolerance
  test (§12.5) passes.
- The three existing `ari.prompts` exports and the `ari.protocols.PromptLoader` re-export are
  unchanged and still import.
- `python -m compileall .`, `ruff check .`, `pytest -q`, and
  `python scripts/readme_sync.py --check` all pass.
- No `.md` template, no core load site, no skill file, and no `ari.public`/CLI/MCP/dashboard
  surface was modified.
- The word "deprecated" is not applied to any internal code introduced or touched here.

---

## 14. Rollback Plan

Because the change is purely additive and behind a new, not-yet-adopted class, rollback is
low-risk:
1. Delete `ari-core/ari/prompts/registry.py` and `ari-core/tests/test_prompt_registry.py`.
2. Revert the additive export line(s) in `ari-core/ari/prompts/__init__.py` (and
   `ari/protocols/__init__.py` if §8.5 was taken).
3. Revert the `ari-core/ari/prompts/README.md ## Contents` line (or re-run
   `scripts/readme_sync.py --write`).
Since no existing call site was rewired and the loader is untouched, reverting cannot affect
any runtime prompt-loading path. `git revert` of the single feature commit is sufficient; no
data/format migration is involved.

---

## 15. Dependencies

Per the Phase 7 dependency graph (`036 -> 037, 038, 039, 040, 041, 042, 043, 044`):

- **Requires (must precede 038):** **036** — the Phase 7 root/inventory subtask
  (`036 -> 038`). 036 is one of the inventory subtasks that MUST precede any runtime code
  change (listed alongside 001, 002, 020, 045, 053, 059, 060, 067); 038 is the first
  *implementation* subtask of Phase 7 and therefore gated on 036 completing the prompt
  inventory. Note: the file `docs/refactoring/subtasks/036_*.md` **does not exist** in the
  subtasks directory at planning time — confirm 036 is authored/completed before starting.
- **Informed by (upstream inventory, not hard blockers):** **002** (legacy/obsolete/duplicate
  inventory — supplies the MERGE_DUPLICATE/REVIEW_REQUIRED prompt overlaps 038 must leave
  alone) and **001** (complexity/dependency measurement).
- **Enables (downstream siblings that build on this mechanism):** **037, 039, 040, 041, 042,
  043, 044** — the prompt-extraction / skill-migration / duplicate-consolidation subtasks that
  will migrate hardcoded and skill-local prompts into the registry established here. 038 is a
  sibling of these under 036, not their strict predecessor in the graph, but it is the
  natural first step (it provides their destination); sequence 038 ahead of the
  text-moving siblings.
- **No cross-phase dependency** on the config-consolidation (003/027/028), path (004–006),
  or viz (020–024) chains, and no dependency on the quality-tooling phase — a future
  `check_prompts.py` depends on 038, not the reverse.

---

## 16. Risk Level

**Medium.** Rationale:

- **Runtime code change: Yes**, but strictly **additive and non-adopted** — the new
  `PromptRegistry` is not yet on any hot path (the 11 core sites keep their existing loader
  calls), so the blast radius on runtime behavior is near-zero at merge time.
- The two genuine risk vectors are (a) the **`readme_sync` blocking gate** — easy to trip,
  easy to fix, must not be forgotten; and (b) the **config-injected key tolerance** — if the
  registry were written to hard-fail on undiscovered keys, it could later break
  config-driven BFTS prompt selection. §7.2 mandates tolerance and §12.5 tests it, keeping
  this contained.
- Not Low, because it is the first Phase 7 code change and establishes a mechanism many
  downstream subtasks will build on — a wrong abstraction here (e.g. a second manifest source
  of truth, or breaking the loader's KEEP contract) would propagate. Not High, because it
  touches no public/CLI/MCP/dashboard surface and is trivially reversible (§14).

---

## 17. Notes for Implementer

- **Wrap, do not fork.** The registry must delegate every read to a `PromptLoader`; do not
  reimplement `read_text`/hashing. If you find yourself copying `_loader.py` logic, stop.
- **Single source of truth.** Resist adding a `registry.yaml`. Placeholders come from parsing
  the `.md` via `string.Formatter().parse`; keys come from filesystem discovery. Two lists to
  keep in sync is the anti-pattern Phase 7 exists to remove.
- **The `wc -l == 0` templates are populated,** not empty (`pipeline/keyword_librarian.md`,
  both `viz/wizard_*.md` lack a trailing newline). Do not "fix" them and do not treat them as
  missing — that would be a prompt-text change, which is out of scope.
- **Placeholder parsing gotchas:** templates use single-brace `{name}` `str.format`
  placeholders and may contain literal JSON braces escaped as `{{`/`}}` (e.g. the
  evaluator/orchestrator prompts that request JSON output). `string.Formatter().parse` yields
  `field_name = None` for literal text and correctly skips `{{`/`}}`; filter out `None` and
  empty field names. Do a manual spot-check against `evaluator/extract_metrics.md` and
  `orchestrator/bfts_expand.md` (both request structured output) to confirm no spurious
  placeholders.
- **Config keys are real usages.** When reasoning about "is a key used?", remember
  `select_prompt`/`expand_select_prompt` are referenced only as **config strings**
  (`config/__init__.py:133,142`), not as literal `.load("…")` arguments. A future orphan
  checker (not this subtask) must account for that; 038's registry must at least not break it.
- **Leave the skills alone.** `ari-skill-replicate` and `ari-skill-paper-re` load prompts via
  `read_text()` and are the motivation for this work, but migrating them is a *later* subtask.
  Do not add skill imports or a multi-root registry in 038 unless a downstream subtask
  explicitly requires it — keep the surface minimal.
- **Match house test/module conventions** already present under `ari-core/tests/` and in
  `_loader.py` (module docstring citing the phase/design doc, `from __future__ import
  annotations`, `Protocol`-friendly typing). Keep it stdlib and deterministic (P2).
- **Do not touch `ari.public`.** The registry is internal (`ari.prompts`). Adding it to the
  stable public API would create a maintenance obligation this subtask does not intend.

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **038** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
