# Subtask 042: Add Prompt Snapshot Tests

> **Phase:** 7 — Prompt Management.
> **Repo:** `/home/t-kotama/workplace/ARI` (branch `main`, `ari-core` version `0.9.0`).
> **Planning date:** 2026-07-01. **Author role:** senior software architect.
> **Runtime code change:** **No** (adds `pytest` snapshot modules, committed golden fixtures, and a
> `tests/README.md` subsection only — no runtime code, prompts, configs, or contracts are touched).
> **Companion facts:** the core prompt loader is `ari-core/ari/prompts/_loader.py` (49 lines); an
> existing byte-pin regression already lives at `ari-core/tests/test_prompt_extraction.py`
> (108 lines). This subtask is the *snapshot* counterpart to that hand-maintained hash list, and the
> in-process `pytest` counterpart to the not-yet-existing `scripts/check_prompts.py` (a separate
> Phase-7 / tooling subtask — **do not implement it here**).

---

## 1. Goal

Add **prompt snapshot tests** so that any change to an externalised prompt — whether a stray `\n`,
a renamed `{placeholder}`, a reworded system instruction, or an accidentally deleted/added template
file — fails `pytest -q` on the PR that introduces it, and is easy to re-bless when intentional.

Concretely, deliver three guarantees that the current tooling does **not** fully provide:

1. **Completeness / drift by auto-discovery.** Every `ari-core/ari/prompts/**/*.md` template has a
   committed snapshot, and every committed snapshot has a live template. Adding or removing a prompt
   file without updating snapshots fails the suite. (The existing hash list in
   `test_prompt_extraction.py` is hand-maintained and silently goes stale when a new prompt lands —
   see its own docstring: *"Add a row here for each new `ari/prompts/<key>.md` that lands."*)
2. **Rendered-output stability.** For each prompt, snapshot the string produced by
   `str.format(**fixture_kwargs)` using the kwargs its real call site passes. This catches
   placeholder-contract breakage (a renamed/added/removed `{var}`) that a raw byte hash of the
   *template* would flag only indirectly, and that a rendered snapshot pins explicitly.
3. **Coverage of skill-local externalised prompts.** The skill prompts under
   `ari-skill-replicate/src/prompts/` (4 files) and `ari-skill-paper-re/src/prompts/replicator.md`
   are loaded via ad-hoc `Path.read_text()` (not the core loader) and currently have **no** snapshot
   or hash guard. Add snapshot coverage for them inside each skill's own `tests/` directory.

Provide a low-friction, dependency-free **update mechanism** (`ARI_UPDATE_PROMPT_SNAPSHOTS=1`) so an
intentional prompt edit is re-blessed by re-running `pytest` once, instead of hand-computing a
`sha256` and pasting it into a source list.

## 2. Background

Prompts in ARI are **already partially externalised** (Phase "PROMPTS_AND_CONFIG" / PC):

- `ari-core/ari/prompts/_loader.py` defines `FilesystemPromptLoader` and a `PromptLoader` `Protocol`.
  `load(key)` reads `{base}/{key}.md`; `load_versioned(key)` returns `(text, sha256[:12])` for
  reproducibility pinning. `package_prompts_root()` returns the bundled prompts dir. These names are
  re-exported by `ari/prompts/__init__.py` and again via `ari/protocols/__init__.py`.
- **11 core templates** live under `ari-core/ari/prompts/` (all `.md`, filled with `str.format(...)`
  at the call site): `agent/system.md`; `evaluator/extract_metrics.md`, `evaluator/peer_review.md`;
  `orchestrator/{bfts_expand,bfts_expand_select,bfts_select,lineage_decision,root_idea_selector}.md`;
  `pipeline/keyword_librarian.md`; `viz/{wizard_chat_goal,wizard_generate_config}.md`.
- Load sites are lazy in-function imports (`from ari.prompts import FilesystemPromptLoader`):
  `agent/loop.py:51-52`, `evaluator/llm_evaluator.py:254-255,412`,
  `orchestrator/bfts.py:475-479,553-559,743-744`, `orchestrator/lineage_decision.py:292-293`,
  `orchestrator/root_idea_selector.py:62-63`, `pipeline/context_builder.py:116-117`,
  `viz/api_tools.py:54,126`.
- **Skill-local externalised prompts** bypass the core loader (mechanism inconsistency, already flagged
  `REVIEW_REQUIRED` in the prompts inventory): `ari-skill-replicate/src/prompts/`
  (`skeleton.md` 143L, `subtree.md` 115L, `adversarial_reviewer.md` 208L, `rubric_audit.md` 28L —
  loaded at `generator.py:64,77,93` and `auditor.py:130`) and `ari-skill-paper-re/src/prompts/`
  (`replicator.md` 154L — loaded at `server.py:66`; note `mpi_aggregate_skel.py` there is a **code
  skeleton, not a prompt** and is out of scope).

The **existing** guard is `ari-core/tests/test_prompt_extraction.py`: a `pytest.mark.parametrize`
table of `(key, expected_sha256)` for the 11 core prompts, plus a `.format()` smoke test and a
`load_versioned` determinism test. It is green today and is a legitimate byte-pin — but it is (a)
hand-maintained (goes stale on new prompts), (b) core-only (no skill prompts), and (c) template-only
(does not pin the *rendered* output nor the placeholder set). This subtask complements it; it does
**not** delete or rewrite it.

Still-hardcoded prompts in the large skill `server.py` files (e.g.
`ari-skill-paper/src/server.py` 5 inline "You are…" prompts; `ari-skill-evaluator/src/server.py`
`_SEMANTIC_SYSTEM_PROMPT`/`_METRIC_EXTRACT_SYS`; plot/vlm/transform/web servers) are **out of scope
here** — their extraction is the job of sibling Phase-7 subtasks 037–041. This subtask snapshots
what is *already externalised*, so it can immediately protect the extracted files those subtasks
will keep producing.

No prompt snapshot library is installed today: `requirements.txt`, `requirements.lock`, and
`ari-core/pyproject.toml` contain no `syrupy` / `pytest-regtest` / `inline-snapshot` entry. `ruff`,
`python -m compileall`, and `pytest` (with `pytest-asyncio`, `pytest-mock`) are available. The plan
below is therefore **stdlib-only** and adds **no new dependency** (P2 determinism, minimal footprint).

## 3. Scope

**In scope**

- New `pytest` module `ari-core/tests/test_prompt_snapshots.py` covering the 11 core templates:
  auto-discovery completeness, raw-byte snapshots, rendered-output snapshots, and per-key placeholder
  sets.
- Committed golden fixtures under a new `ari-core/tests/snapshots/prompts/` tree.
- New `pytest` modules `ari-skill-replicate/tests/test_prompt_snapshots.py` and
  `ari-skill-paper-re/tests/test_prompt_snapshots.py` covering their `src/prompts/*.md`, with goldens
  under each skill's `tests/snapshots/prompts/`.
- A shared, stdlib-only update mechanism gated on `ARI_UPDATE_PROMPT_SNAPSHOTS=1`.
- A short "Prompt snapshot tests" subsection appended to `ari-core/tests/README.md`.

**Out of scope**

- Extracting still-hardcoded prompts (subtasks 037–041).
- Consolidating the loader-vs-`read_text` mechanism inconsistency (`REVIEW_REQUIRED`, a separate
  Phase-7 item) — snapshot the skill prompts *as they are read today*.
- Implementing `scripts/check_prompts.py` (separate tooling subtask).
- Adding a snapshot dependency such as `syrupy` (`REVIEW_REQUIRED`; see §4).

## 4. Non-Goals

- **Do not** edit any `.md` prompt template, `_loader.py`, or any call site. Snapshots must be
  captured against the current on-disk bytes; a red snapshot on first run means a fixture/golden bug,
  not a prompt bug.
- **Do not** delete, rename, or rewrite `ari-core/tests/test_prompt_extraction.py` — it stays as an
  independent byte-pin (`KEEP`). Overlap on raw bytes is intentional belt-and-suspenders.
- **Do not** add a third-party snapshot framework. `syrupy`/`inline-snapshot` are `REVIEW_REQUIRED`
  and explicitly deferred: they add a runtime/test dependency and their `--snapshot-update` semantics
  are unnecessary given the tiny, static prompt corpus.
- **Do not** move skill prompt tests into `ari-core/tests/` — `pytest.ini` `testpaths` is
  `ari-core/tests` only, and importing two skills' `src/server.py` in one process is ambiguous by
  design (see `pytest.ini` comment). Skill snapshots live in the skill's own `tests/`.
- **Do not** touch MCP tool contracts, dashboard API, CLI, or `ari.public.*`.

## 5. Current Files / Directories to Inspect

Loader and templates (core):

- `ari-core/ari/prompts/_loader.py` (49L) — `FilesystemPromptLoader.load` / `load_versioned` /
  `package_prompts_root`.
- `ari-core/ari/prompts/__init__.py` (12L) — public re-exports (also surfaced via
  `ari-core/ari/protocols/__init__.py`).
- `ari-core/ari/prompts/agent/system.md` (1321B), `evaluator/extract_metrics.md` (1992B),
  `evaluator/peer_review.md` (1049B), `orchestrator/bfts_expand.md` (1724B),
  `orchestrator/bfts_expand_select.md` (423B), `orchestrator/bfts_select.md` (570B),
  `orchestrator/lineage_decision.md` (1005B), `orchestrator/root_idea_selector.md` (671B),
  `pipeline/keyword_librarian.md` (352B, **no trailing newline**), `viz/wizard_chat_goal.md` (607B),
  `viz/wizard_generate_config.md` (257B, template retains an unsubstituted `{goal}`).
- Per-directory `README.md` files exist under `ari/prompts/{agent,evaluator,orchestrator,pipeline,viz}/`
  and `ari/prompts/README.md` — these are docs, **not** prompts; the discovery glob must exclude
  `README.md`.

Existing tests and conventions:

- `ari-core/tests/test_prompt_extraction.py` (108L) — the sha256 byte-pin to complement.
- `ari-core/tests/test_bfts_prompt_selection.py` — shows a `_FakeLoader` and the exact `bfts_select`
  placeholders (`experiment_goal`, `memory_context`, `candidates`).
- `ari-core/tests/test_system_prompt_memory.py` — shows `agent/system` render kwargs
  (`tool_desc`, `memory_rules`, `extra`).
- `ari-core/tests/README.md` — where the new subsection goes.
- `pytest.ini` — `--import-mode=importlib`, `testpaths = ari-core/tests`, `asyncio_mode = auto`.
- `scripts/run_all_tests.sh` — full multi-package runner; already lists `ari-skill-replicate/tests`
  and `ari-skill-paper-re/tests`, so **no runner change is needed** for skill snapshots to execute.

Call sites (to read for the exact render kwargs of each key):

- `ari-core/ari/agent/loop.py:51-52`; `ari-core/ari/orchestrator/bfts.py:475-479,553-559,743-744`;
  `ari-core/ari/orchestrator/lineage_decision.py:292-293`;
  `ari-core/ari/orchestrator/root_idea_selector.py:62-63`;
  `ari-core/ari/evaluator/llm_evaluator.py:254-255,412`;
  `ari-core/ari/pipeline/context_builder.py:116-117`; `ari-core/ari/viz/api_tools.py:54,126`.

Skill prompts and their read sites:

- `ari-skill-replicate/src/prompts/{skeleton,subtree,adversarial_reviewer,rubric_audit}.md`; read at
  `ari-skill-replicate/src/generator.py:64,77,93` and `ari-skill-replicate/src/auditor.py:130`
  (`PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"`).
- `ari-skill-paper-re/src/prompts/replicator.md`; read at `ari-skill-paper-re/src/server.py:66`.
  (`ari-skill-paper-re/src/prompts/mpi_aggregate_skel.py` is a code skeleton — exclude.)
- Existing skill test dirs to extend: `ari-skill-replicate/tests/` (has `conftest.py`, `fixtures/`),
  `ari-skill-paper-re/tests/`.

Parallel prior art (for the update-flag ergonomics, not to modify):

- `ari-core/ari/configs/_loader.py` — the config analogue the prompt loader docstring references.

## 6. Current Problems

1. **The byte-pin list goes stale silently.** `test_prompt_extraction.py` only checks the 11 keys
   hand-listed in `_EXPECTED_HASHES`. A newly extracted prompt (which subtasks 037–041 will add) is
   unprotected until someone remembers to append a row; there is no test that *fails* on an
   un-snapshotted prompt file.
2. **No rendered / placeholder-contract coverage.** The current tests pin the raw template bytes and
   run one `.format()` smoke assertion for `agent/system` only. A prompt whose `{placeholder}` set
   diverges from what the call site passes (e.g. a template gains `{budget}` but `bfts.py` never
   supplies it) would raise `KeyError`/`IndexError` only at runtime, not in CI.
3. **Skill-local prompts have zero drift protection.** `ari-skill-replicate` (4 prompts, up to 208L)
   and `ari-skill-paper-re` (`replicator.md`, 154L) are read via bare `read_text()` with no hash and
   no snapshot — the highest-line externalised prompts in the repo are the least guarded.
4. **Re-blessing is manual and error-prone.** Updating an intentional prompt change today means
   running the code, copying a `sha256`, and pasting it into a Python list — no `--update` path.
5. **Newline/encoding subtlety is undocumented as a test concern.** `test_prompt_extraction.py:55-60`
   already notes that `evaluator/extract_metrics.md` ends with a trailing newline while the legacy
   constant did not, and `pipeline/keyword_librarian.md` has **no** trailing newline. Snapshots that
   read text with platform newline translation, or that a formatter "fixes", would produce spurious
   diffs.

## 7. Proposed Design / Policy

**Policy P042-A — Auto-discovery, not a hand list.** The core snapshot module discovers prompts by
globbing `package_prompts_root()` for `**/*.md`, excluding any file named `README.md`. The set of
discovered keys is asserted against the set of committed golden files, so *adding* a prompt without a
golden, or *removing* a prompt while leaving a golden, both fail.

**Policy P042-B — Two snapshots per prompt.**
- *Raw snapshot*: exact template bytes (read/compared as bytes to avoid newline translation),
  stored at `ari-core/tests/snapshots/prompts/<key>.md`.
- *Rendered snapshot*: `template.format(**FIXTURE_KWARGS[key])` output, stored at
  `ari-core/tests/snapshots/prompts/<key>.rendered.txt`. `FIXTURE_KWARGS` is a small dict in the test
  module mapping each key to representative kwargs taken from its real call site (see §5). Keys with
  intentionally-unfilled placeholders (e.g. `viz/wizard_generate_config`'s `{goal}`) supply a
  sentinel fixture value so the rendered form is deterministic.

**Policy P042-C — Placeholder-set assertion.** For each key, extract the field names via
`string.Formatter().parse(template)` and assert they equal an expected frozenset declared next to
`FIXTURE_KWARGS`. This is the explicit *contract* the call sites depend on and the cheapest way to
catch a renamed/added/removed `{var}`.

**Policy P042-D — Skill snapshots live with their skill.** Mirror P042-A/B (raw snapshot only; skills
render via their own agents, so a rendered snapshot is not attempted here) inside
`ari-skill-replicate/tests/test_prompt_snapshots.py` and
`ari-skill-paper-re/tests/test_prompt_snapshots.py`, discovering `src/prompts/*.md` (excluding
`README.md` and non-`.md` files like `mpi_aggregate_skel.py`). These run only under
`scripts/run_all_tests.sh` / `pytest ari-skill-<name>/tests`, never in the `ari-core` in-process set.

**Policy P042-E — One-command re-bless, stdlib only.** When `ARI_UPDATE_PROMPT_SNAPSHOTS=1` is set,
each snapshot test **writes** the current value to its golden path (creating parent dirs) and passes;
otherwise it **reads** the golden and asserts equality with a message that names the env var. No
third-party framework, no network, deterministic output (P2). Absence of a golden under a normal run
is a hard failure ("run with ARI_UPDATE_PROMPT_SNAPSHOTS=1 to create it").

**Policy P042-F — Keep the existing byte-pin.** `test_prompt_extraction.py` stays as an independent
`sha256` cross-check (`KEEP`). The new module is additive; overlap on raw bytes is deliberate
redundancy. (A follow-up may fold the hand list into the auto-discovered snapshot; that consolidation
is *not* part of 042.)

Golden files are **test fixtures**, not shipped artefacts: they live under `tests/`, are not packaged,
and must be excluded from any prompt-linting/formatting so no autoformatter rewrites their bytes.

## 8. Concrete Work Items

1. **Create `ari-core/tests/test_prompt_snapshots.py`** with a stdlib-only helper
   `_assert_snapshot(path, value_bytes)` implementing the read/compare vs write behaviour gated on
   `ARI_UPDATE_PROMPT_SNAPSHOTS` (Policy P042-E). Compare as `bytes`; write with `Path.write_bytes`.
2. **Add `test_all_prompts_have_snapshots`** — glob `package_prompts_root()/**/*.md`, drop
   `README.md`, derive keys, and assert the discovered key set equals the set derived from
   `tests/snapshots/prompts/*.md`. (Policy P042-A.)
3. **Add `test_prompt_raw_snapshot[key]`** — parametrized over discovered keys; snapshot the template
   bytes via `FilesystemPromptLoader().load(key).encode("utf-8")` **or** `Path.read_bytes()` (pick
   `read_bytes` to be encoding-neutral) against `<key>.md` goldens. (Policy P042-B raw.)
4. **Add `FIXTURE_KWARGS` and `EXPECTED_FIELDS`** dicts, populated from the call sites in §5
   (`agent/system` → `tool_desc,memory_rules,extra`; `orchestrator/bfts_select` →
   `experiment_goal,memory_context,candidates`; etc. — read each cited call site to copy the exact
   kwarg names).
5. **Add `test_prompt_placeholders[key]`** — assert `string.Formatter().parse` field set ==
   `EXPECTED_FIELDS[key]`. (Policy P042-C.)
6. **Add `test_prompt_rendered_snapshot[key]`** — `template.format(**FIXTURE_KWARGS[key])` compared to
   `<key>.rendered.txt`. (Policy P042-B rendered.)
7. **Generate the core goldens once**: run
   `ARI_UPDATE_PROMPT_SNAPSHOTS=1 pytest ari-core/tests/test_prompt_snapshots.py -q`, then run the
   same command **without** the env var to confirm green. Inspect the generated goldens (esp. the
   no-trailing-newline `pipeline/keyword_librarian.md` and the trailing-newline
   `evaluator/extract_metrics.md`) to confirm bytes match the live files exactly.
8. **Create `ari-skill-replicate/tests/test_prompt_snapshots.py`** (Policy P042-D) — discover
   `src/prompts/*.md`, raw-snapshot to `ari-skill-replicate/tests/snapshots/prompts/`. Reuse a local
   copy of the tiny `_assert_snapshot` helper (skills cannot import `ari-core` test modules; keep it
   ~15 lines and self-contained).
9. **Create `ari-skill-paper-re/tests/test_prompt_snapshots.py`** — same, for
   `src/prompts/replicator.md`; explicitly exclude `mpi_aggregate_skel.py` and `README.md`.
10. **Generate skill goldens** via `ARI_UPDATE_PROMPT_SNAPSHOTS=1 pytest ari-skill-replicate/tests
    ari-skill-paper-re/tests -q` (run each path in its own process per `pytest.ini` guidance), then
    confirm green without the env var.
11. **Append a "Prompt snapshot tests" subsection to `ari-core/tests/README.md`** documenting: what
    is snapshotted, the golden locations, the `ARI_UPDATE_PROMPT_SNAPSHOTS=1` re-bless flow, and the
    note that skill prompt snapshots run only via `scripts/run_all_tests.sh`.
12. **Verify quality gates**: `python -m compileall .`, `ruff check .`, `pytest -q`, and
    `bash scripts/run_all_tests.sh` (or the two skill paths) all pass. Confirm `ruff` does not flag
    the new modules and that golden text files are not picked up by any Python lint.

## 9. Files Expected to Change

**New (test code):**

- `ari-core/tests/test_prompt_snapshots.py`
- `ari-skill-replicate/tests/test_prompt_snapshots.py`
- `ari-skill-paper-re/tests/test_prompt_snapshots.py`

**New (committed golden fixtures):**

- `ari-core/tests/snapshots/prompts/*.md` (11 raw goldens, mirroring the key tree) and
  `ari-core/tests/snapshots/prompts/*.rendered.txt` (11 rendered goldens).
- `ari-skill-replicate/tests/snapshots/prompts/{skeleton,subtree,adversarial_reviewer,rubric_audit}.md`.
- `ari-skill-paper-re/tests/snapshots/prompts/replicator.md`.

**Modified (docs only):**

- `ari-core/tests/README.md` (add the "Prompt snapshot tests" subsection).

**Explicitly NOT changed:** `ari-core/tests/test_prompt_extraction.py` (kept as-is);
`scripts/run_all_tests.sh` (already lists both skill test paths — no edit needed); any `.md` prompt
template; `ari/prompts/_loader.py`; any call site; `requirements*.txt` / `pyproject.toml` (no new
dependency); `.github/workflows/*` (existing `refactor-guards.yml` already runs `ari-core/tests`,
which picks up the new core module automatically).

## 10. Files / APIs That Must Not Be Broken

- **`ari-core/tests/test_prompt_extraction.py`** — must still pass unchanged (both suites cover the
  same raw bytes; a red here means a golden was captured against wrong bytes).
- **`ari.prompts` public surface** — `FilesystemPromptLoader`, `PromptLoader`, `package_prompts_root`
  (re-exported via `ari.prompts` and `ari.protocols`): consumed read-only by the tests; do not alter.
- **Prompt `.md` bytes and their `{placeholder}` contracts** — the 11 core templates plus the 5 skill
  templates. The call sites in §5 depend on exact placeholder names; the tests *lock* these, they must
  not change them.
- **`pytest.ini`** contract — `testpaths = ari-core/tests`, `--import-mode=importlib`,
  `asyncio_mode = auto`. New core tests live under `ari-core/tests`; skill tests must not leak into it.
- **`scripts/run_all_tests.sh`** interface — the per-skill process isolation must keep working; do not
  add a skill snapshot module that imports another skill's `src.server`.
- **MCP tool contracts, dashboard API, CLI `ari`, `ari.public.*`, checkpoint/config formats** — wholly
  untouched by this test-only subtask.

## 11. Compatibility Constraints

- **No prompt bytes change** ⇒ no behavioural change to any agent, orchestrator, evaluator, pipeline,
  viz wizard, or skill. Snapshots are captured *from* the current files.
- **No new dependency.** Stdlib only (`hashlib` is not even required; `pathlib`, `string`, `os` are).
  Preserves reproducibility (P2) and the lean `ari-core/pyproject.toml` (which deliberately excludes
  runtime deps).
- **Golden files are fixtures, not contracts.** They are not packaged, not imported at runtime, and
  carry no external-contract status; they may be re-blessed freely via the update flag.
- **Deterministic.** Discovery is sorted; rendered output uses fixed fixture kwargs; byte comparison
  avoids newline translation — identical results across machines/OSes.
- **Additive to CI.** `refactor-guards.yml` already runs `ari-core/tests/`; the new core module is
  exercised without any workflow edit. Skill snapshots ride the existing `run_all_tests.sh` paths.

## 12. Tests to Run

From the repo root `/home/t-kotama/workplace/ARI`:

```bash
# 0. (one-time) bless goldens, then run WITHOUT the flag to confirm green.
ARI_UPDATE_PROMPT_SNAPSHOTS=1 pytest ari-core/tests/test_prompt_snapshots.py -q

# 1. syntax / import sanity across the tree
python -m compileall .

# 2. core in-process suite (includes the new snapshot module + the kept byte-pin)
pytest -q
pytest -q ari-core/tests/test_prompt_snapshots.py ari-core/tests/test_prompt_extraction.py

# 3. lint
ruff check .

# 4. skill snapshot modules (each in its own process, per pytest.ini rationale)
pytest -q ari-skill-replicate/tests/test_prompt_snapshots.py
pytest -q ari-skill-paper-re/tests/test_prompt_snapshots.py
# …or the full multi-package runner:
bash scripts/run_all_tests.sh
```

No frontend build is involved (this is not a frontend subtask), so `npm test` / `npm run build` are
not required.

## 13. Acceptance Criteria

1. `pytest -q` (core) is green **and** includes the new `test_prompt_snapshots.py` cases; the kept
   `test_prompt_extraction.py` remains green.
2. Deleting or renaming any `ari/prompts/**/*.md` (without re-blessing) makes
   `test_all_prompts_have_snapshots` fail; adding a new template without a golden fails the same test.
3. Editing a single byte in any template (without re-blessing) fails the corresponding
   `test_prompt_raw_snapshot[key]`; changing a `{placeholder}` name fails
   `test_prompt_placeholders[key]` and/or `test_prompt_rendered_snapshot[key]`.
4. Rendered goldens exist for all 11 core keys and match `template.format(**FIXTURE_KWARGS[key])`.
5. Raw goldens exist for the 4 `ari-skill-replicate` prompts and the 1 `ari-skill-paper-re` prompt;
   `pytest ari-skill-replicate/tests` and `pytest ari-skill-paper-re/tests` are green.
6. `ARI_UPDATE_PROMPT_SNAPSHOTS=1 pytest …` regenerates goldens and passes; a subsequent plain run is
   green with a clean `git diff` on the golden files.
7. `python -m compileall .` and `ruff check .` are clean.
8. `ari-core/tests/README.md` documents the suite and the update flag.
9. `git status` shows only the files listed in §9 as added/modified — no prompt template, loader, or
   config file is touched.

## 14. Rollback Plan

Pure additive, test-only change with a trivial rollback:

1. `git rm` the three new `test_prompt_snapshots.py` modules and their `snapshots/prompts/` golden
   directories under `ari-core/tests/`, `ari-skill-replicate/tests/`, `ari-skill-paper-re/tests/`.
2. Revert the `ari-core/tests/README.md` subsection.

No runtime code, prompt, config, workflow, or contract is affected, so rollback cannot regress
behaviour. If only the *skill* snapshots prove flaky (e.g. a vendored prompt update churns
`replicator.md`), they can be removed independently of the core module.

## 15. Dependencies

- **Depends on 036** (Phase 7 prompt inventory) — per the dependency graph `036 -> 037…044`, subtask
  036 is the authoritative enumeration of prompt keys / locations this test snapshots. 036 is one of
  the inventory subtasks that **must precede any runtime code change**; 042 is test-only but should
  land after 036 so the snapshot set matches the inventory of record.
- **Sibling extraction subtasks 037–041** (also children of 036): these will *add* new externalised
  prompt files. 042 does not block on them, but because it auto-discovers prompts (Policy P042-A), its
  goldens should be re-blessed (`ARI_UPDATE_PROMPT_SNAPSHOTS=1`) whenever an extraction subtask lands a
  new template. Note this ordering in the PR description.
- **Pattern sibling 018** (Add Tests For Architecture Boundaries) — same "pytest guard in-process,
  static checker in CI" split; reuse its conventions (parametrized guards, README subsection).
- **Downstream, out of scope:** the not-yet-existing `scripts/check_prompts.py` is the CI static
  counterpart of these tests (a separate tooling subtask; the prompts inventory notes `check_prompts.py`
  is `MISSING` — do not implement it here).
- **No dependency** on any frontend, viz-API, or path-policy subtask.

## 16. Risk Level

**Low.** Runtime code change: **No** — this subtask adds `pytest` modules, committed golden text
fixtures, and one README subsection, using only the standard library. It imports no skill server into
the core process, changes no prompt/loader/contract, and adds no dependency. The only residual risks
are (a) a golden captured against wrong bytes — mitigated by the mandatory "bless then run clean"
step (§8.7, §8.10) and the redundant `test_prompt_extraction.py` cross-check; and (b) newline/encoding
churn — mitigated by byte-level comparison and the explicit notes in §17. Consistent with the
non-runtime, Low-risk profile of sibling test subtask 018.

## 17. Notes for Implementer

- **Read as bytes, compare as bytes.** Use `Path.read_bytes()` for both live templates and goldens.
  Do **not** normalise newlines. `pipeline/keyword_librarian.md` has **no** trailing newline
  (`wc -l` = 0 but 352 bytes) while `evaluator/extract_metrics.md` ends with one — the snapshot must
  preserve each exactly. `viz/wizard_chat_goal.md` (607B) and `viz/wizard_generate_config.md` (257B)
  also report `wc -l` = 0 yet are populated; trust the byte length, not the line count.
- **`{goal}` stays unsubstituted in the template.** `viz/wizard_generate_config.md` carries a literal
  `{goal}` that the call site (`api_tools.py:126`) fills at runtime; the *raw* snapshot keeps it, and
  the *rendered* snapshot supplies a sentinel `goal=` fixture value. Confirm no other template has an
  intentionally-unfilled placeholder before choosing `EXPECTED_FIELDS`.
- **Copy render kwargs from the real call sites**, do not guess. Confirmed pairs to seed
  `FIXTURE_KWARGS`: `agent/system` → `tool_desc, memory_rules, extra` (see
  `test_system_prompt_memory.py`); `orchestrator/bfts_select` → `experiment_goal, memory_context,
  candidates` (see `test_bfts_prompt_selection.py`'s `_FakeLoader`). Derive the rest by reading
  `bfts.py:479/559/744`, `llm_evaluator.py:255/412`, `context_builder.py:117`, `api_tools.py:55/127`.
- **`README.md` files under `ari/prompts/**` are not prompts** — the discovery glob must exclude any
  basename `README.md`, or `test_all_prompts_have_snapshots` will demand goldens for docs.
- **Skills cannot import core test helpers.** Duplicate the ~15-line `_assert_snapshot` helper into
  each skill test module; do not attempt a shared import (cross-package + separate-process execution
  make it brittle).
- **Keep goldens out of formatters.** Golden text files must not be rewritten by `ruff`/prettier/EOL
  fixers. If a repo-wide autoformat hook exists, exclude `**/tests/snapshots/**`; otherwise just avoid
  running formatters over them.
- **`sonfigs/` does not exist** — ignore any reference to it (it is a hypothesised typo, absent from
  the repo). The prompt loader lives at `ari-core/ari/prompts/`; the confusable config trio
  (`ari/config/`, `ari/configs/`, top-level `config/`) is unrelated to this subtask.
- **The hand-maintained hash list is intentionally kept.** Do not "helpfully" delete
  `test_prompt_extraction.py`; folding it into the auto-discovered snapshot is a possible *future*
  cleanup, explicitly outside 042's scope.

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **042** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
