---
sources:
  - path: ari-core/tests
    role: test
  - path: ari-core/tests/fixtures/gui_refresh
    role: test
  - path: pytest.ini
    role: config
  - path: scripts/docs
    role: test
  - path: scripts/check_dashboard_ux.py
    role: test
  - path: scripts/check_bundle_budget.py
    role: test
  - path: scripts/quality/check_bundle_budget.yaml
    role: config
  - path: ari-core/ari/viz/frontend/src/i18n
    role: test
  - path: ari-core/ari/viz/frontend/src/__tests__
    role: test
  - path: ari-core/ari/viz/frontend/vitest.config.ts
    role: config
  - path: ari-core/ari/viz/frontend/package.json
    role: config
  - path: .github/workflows
    role: config
last_verified: 2026-08-13
---

# How to Test ARI Code

This guide covers the testing conventions for `ari-core` and the
`ari-skill-*` packages: where tests live, what fixtures are
expected, and how to keep determinism guarantees intact.

## Repository layout

```
ari-core/tests/                 — core regression tests
ari-skill-<name>/tests/         — skill-local tests
ari-skill-<name>/conftest.py    — skill-level fixtures
pytest.ini                      — repo-wide config
```

`pytest.ini` at the repo root sets the `testpaths` a bare `pytest` walks:
`ari-core/tests` and `workspace/harnesses` (the second is absent on a
checkout without a workspace, which pytest tolerates). The `ari-skill-*`
suites are deliberately **not** in `testpaths` — each ships its own
`src/server.py`, so importing two of them in one process is ambiguous. Run
them per-package, or run `bash scripts/run_all_tests.sh` for the full suite
(one pytest process per path).

## Running the suite

```bash
pytest -q                                        # the default testpaths only
bash scripts/run_all_tests.sh                    # full suite, process per path
pytest ari-skill-memory/tests -q                 # one skill
pytest ari-core/tests/test_react_driver.py -q    # one file
pytest ari-core/tests/test_react_driver.py::test_runs_for_two_nodes  # one case
pytest -k 'memory and not letta' -q              # by keyword
```

## ari-core conventions

### Always isolate writes

ARI used to write into `$HOME/.ari/`.  v0.5.0 removed that path; the
guardrail test `ari-core/tests/test_no_user_home_writes.py` asserts
that no test ever creates files there again.  When you write a new
test that touches the filesystem:

- Use `monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(tmp_path))`.
- Use `tmp_path` for any auxiliary directories.
- Never call `Path.home()` directly in production code; if you must
  in a test, document why and add it to the audit list.

### Smoke tests for the agent loop

`ari-core/tests/test_react_driver.py` runs three deterministic
"agent runs through two nodes" tests:

1. **Happy path** — two nodes, real LLM stub, asserts BFTS state at
   each transition.
2. **Tool failure recovery** — the coding skill returns an error;
   the agent retries with a fixed seed.
3. **Memory write isolation** — sibling nodes see disjoint memory
   stores.

Mirror this triplet whenever you add a new agent-level feature.

### Determinism guarantees (P2)

The "same seed, same tree" invariant is verified by
`ari-core/tests/test_no_user_home_writes.py` indirectly (it asserts
no global state mutates between runs) and by the per-skill suites
(`ari-skill-memory/tests/test_isolation.py`,
`ari-skill-memory/tests/test_cow.py`).

When a determinism regression sneaks in:

1. Write a regression test first that pins the expected tree shape.
2. Bisect the change set; the offender almost always introduces a
   `dict` ordering reliance or a hash that depends on `id(...)`.
3. Add the test to the per-domain suite (memory, BFTS, etc.).

### Synthetic checkpoint fixtures

The GUI and `/api/v1` reader tests do not ship checkpoints — they generate
them. `ari-core/tests/fixtures/gui_refresh/` holds two pure-Python factories:

- `run_fixture_factory.py` — `make_run_checkpoint(dest, nodes=N, seed=S)`
  writes a run checkpoint (`tree.json`, `nodes_tree.json`, `results.json`,
  `experiment.md`, `idea.json`, `meta.json`, `cost_trace.jsonl`) through the
  real `ari.checkpoint.save_*_json` helpers, so the JSON formatting matches the
  production writers byte for byte. The optional `paper` / `review` / `ors` /
  `ear` result layers all default off.
- `rqgm_fixture_factory.py` — `make_rqgm_checkpoint(dest, nodes=10, epochs=2,
  ...)` calls the base factory first, then layers a deterministic RQGM
  governance surface on top (hash-chained transition and audit logs, the
  registry rollup, prompt bodies, node-metric sentinels), importing the real
  `ari.rqgm` hash and state helpers rather than reimplementing them.

Three properties matter when you use them.

**Nothing is committed.** Both factories generate into a caller-supplied
directory — `tmp_path` in every consumer — so no fixture data sits in the
repository going stale.

**Determinism (P2).** Every value is a fixed literal or derived from the seed
via `hashlib`; `random` is never imported, and timestamps are fixed arithmetic
on the literal `2026-07-23T00:00:00Z`, never `datetime.now()`. The same
`(nodes, seed)` yields byte-identical files, which
`ari-core/tests/test_gui_baseline_run_fixtures.py` asserts directly.

**Corrupt modes are the robustness inputs.** `corrupt=` writes a fully valid
checkpoint first and then damages exactly one thing, so a test isolates one
failure shape at a time: `"truncated_jsonl"` tears the last line of
`cost_trace.jsonl`, `"invalid_json"` chops the tail off `tree.json`, and
`"partial_write"` deletes `tree.json` while leaving `nodes_tree.json` valid.
The RQGM factory has its own trio — `"broken_chain"`,
`"truncated_transitions"`, `"registry_mismatch"`. Both reject an unrecognised
mode with `ValueError`.

The size tiers are a naming convention, not a contract. The factory docstring
and `ari-core/tests/fixtures/gui_refresh/README.md` describe `nodes=10` /
`1000` / `10000` as small / medium / large and call the small tier the one
"every reader must load" — but nothing enforces any of that. `nodes` is a plain
integer parameter carrying a single `nodes >= 1` check; only
`test_gui_baseline_run_fixtures.py` exercises the three tiers (and it also uses
`nodes=50` for the determinism cases); and the reader suites pass whatever
count their assertion needs, `nodes=2` through `nodes=10` across the other
`test_gui_*` files. Read the tier names as shorthand when following those
tests, not as a rule to obey. In `test_gui_baseline_run_fixtures.py` the large
tier is generated but never reloaded, because the repo defines no `slow` marker
to hang a skip on.

Consumers load the factories by file path with
`importlib.util.spec_from_file_location` instead of importing the package, so a
small loader helper is repeated at the top of every consumer file.

## Skill-level conventions

### MCP server tests

Each skill ships a `test_server.py` that:

1. Starts the MCP server in-process (no subprocess).
2. Calls `list_tools()` and asserts the tool list matches canonical
   `skill.yaml`; generated `mcp.json` must match the same projection.
3. Calls each tool with a fixture input and asserts the response
   shape.

Use `mcp.testing` helpers (the harness varies by skill — see
`ari-skill-memory/tests/conftest.py` for a reference).

### LLM mocks

Skills that call an LLM (`evaluator`, `paper`, `paper-re`, `idea`,
`replicate`, `transform`, `plot/_llm`, `vlm`) must mock the LLM in
unit tests.  Use the LiteLLM `respx` adapter or `pytest-mock` to
replace `litellm.completion` with a canned response.

`ari-skill-paper-re/tests/test_litellm_completer.py` is the
reference example.

### Dependent-state fixtures

When a skill needs an `ARI_CHECKPOINT_DIR`-style environment, set it
in a fixture:

```python
@pytest.fixture
def ckpt(tmp_path, monkeypatch):
    monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(tmp_path))
    return tmp_path
```

Never set `ARI_CHECKPOINT_DIR` at module import time — the value
must scope to the test.

## What gets tested at PR time

Several GitHub Actions workflows gate every PR to `main`.

**Tests** — the `refactor-guards` workflow runs:

- `pytest ari-core/tests -q`
- `pytest ari-skill-coding/tests -q`
- `pytest ari-skill-memory/tests -q`
- ... per-skill suites

It also runs `tests/test_no_user_home_writes.py` and
`tests/test_public_api_boundary.py` (Phase 4, ensures skills only
import from `ari.public.*`).

**Contracts** — the `contracts` workflow runs
`python scripts/check_skill_manifests.py` as a hard admission gate. It
validates every canonical manifest, declared environment access, live tool
surface, generated `mcp.json`, workflow reference, version, and default-on
name collision. Contract JSON snapshots cover the public API, MCP inventory,
CLI tree, and dashboard endpoints.

**Docs & structure** — three workflows keep the documentation set in sync:

- `readme-sync` — every directory's `## Contents` index lists the files
  beneath it (`scripts/readme_sync.py --check`).
- `docs-sync` — full-tree invariants, all hard gates: declared `sources:`
  paths resolve (`check_doc_sources.py`), `docs/i18n/landing.{en,ja,zh}.js` share
  one key set (`check_i18n_js.py`), the root `README.{md,ja,zh}` share one heading
  shape (`check_readme_parity.py`), and `report/{en,ja,zh}` are structurally
  parallel (`report/scripts/check_i18n.py`, Gate 6). Translation freshness
  (`check_translation_freshness.py`) and intra-doc links (`check_doc_links.py`)
  run as advisory, non-blocking steps.
- `docs-change-coupling` — diff-based: a `report/{en,ja,zh}` language-paired
  file (chapter, `strings.tex`, `main.tex`) edited in one language must be
  mirrored in the other two in the same PR (`check_report_cochange.py`, hard);
  and when a source listed in a doc's `sources:` changes, that doc's
  `last_verified` should be bumped (`check_ref_coupling.py`, advisory).

Run any doc gate locally from the repo root, e.g.
`python scripts/docs/check_i18n_js.py`.

**Dashboard translations** — the dashboard UI ships its own trilingual
dictionaries at `ari-core/ari/viz/frontend/src/i18n/{en,ja,zh}.ts`, and none of
the workflows above cover them: `check_i18n_js.py` reads only
`docs/i18n/landing.{en,ja,zh}.js`, and its key pattern matches single-quoted keys
only, so it cannot parse dictionaries whose keys are bare identifiers. The rule
is the same one the docs set follows — the three locales must declare an
**identical key set**, with no key repeated inside a file — so a new UI string
has to be added to all three in the same change. A key present in one locale but
missing from another falls back to the English string, or renders as the raw key
name when `en` lacks it too (`t()` in `src/i18n/index.ts`). Values are
deliberately not compared: a proper noun may legitimately read the same in all
three.

Two checks enforce this, and **neither is wired into a workflow** — run them
yourself when you touch dashboard strings:

- `python scripts/check_dashboard_ux.py --fail-on-regression` — key-set parity
  plus duplicate detection over the three `.ts` files, bundled with the same
  script's other dashboard-UX checks. It exits 1 on any finding not frozen in
  `scripts/quality/check_dashboard_ux.allow.yaml`, and that allowlist holds no
  i18n entries, so a parity break fails on its first run. Without the flag the
  script prints its report and exits 0.
- `npx vitest run src/i18n/__tests__/parity.test.tsx`, from
  `ari-core/ari/viz/frontend` — the same invariant asserted against the imported
  dictionaries, with a `KNOWN_DRIFT` allowlist that is currently empty. Its
  duplicate-key assertion is weaker than the Python one, because a TypeScript
  object literal has already collapsed any repeated key by the time the test
  reads it.

Both pass on the current tree: the three dictionaries carry one identical key
set, with no duplicates.

**Dashboard accessibility** — the dashboard declares **no WCAG conformance
level**. No conformance target exists in this documentation set or in the
frontend suite, and nothing here should be read as one. What exists is a set of
frozen baselines in
`ari-core/ari/viz/frontend/src/__tests__/shellA11yBaseline.test.tsx`. Like the
i18n checks above it is **not wired into any workflow** — no workflow runs the
frontend suite at all (the only Node steps in CI build the VitePress docs site),
so it is a hard row of the by-hand pre-cutover checklist instead (`npm test`,
`docs/guides/gui_cutover_runbook.md` §2). Run just this file from
`ari-core/ari/viz/frontend`:

```bash
npx vitest run src/__tests__/shellA11yBaseline.test.tsx
```

It pins three things:

- **Positive invariants that already hold.** Exactly one `navigation` landmark;
  every sidebar entry (15 of them with `gui_v2` on) is a native button carrying
  `tabindex="0"`; the four nav groups are named through `aria-labelledby`; the
  mobile hamburger carries `aria-label`/`aria-controls`/`aria-expanded`; the
  active-project `combobox` has an accessible name.
- **An axe-core violation-id baseline** for the shell rendered at `#/home`,
  currently the empty list. The assertion is exact equality, so a new violation
  fails *and* so does an id left in the baseline after the underlying problem is
  fixed. The `color-contrast` rule is **disabled** there because jsdom does not
  paint — no automated check in this repo computes colour contrast.
- **An `<h1>`-count baseline over the 18 routes** in the test's `ROUTE_MARKERS`.
  Four are knowingly non-compliant and pinned as such: `#/paperbench`,
  `#/workflow` and `#/settings` title the page with an `<h2>` and no `<h1>`, and
  `#/idea` renders no heading element at all. The other 14 render exactly one
  `<h1>`. Exact equality again, so fixing a route means shrinking the frozen
  literal in the same change.

What nothing covers: there is no end-to-end assertion that a primary journey can
be completed without a mouse, and no screen-reader check. Keyboard *reachability*
is asserted for the sidebar (focusable native buttons, above); actually *driving*
a surface from the keyboard is asserted only for the `#/tree2` table
(`src/components/TreeV2/__tests__/TreeV2LargeTree.test.tsx` walks
<kbd>↓</kbd>/<kbd>→</kbd>/<kbd>Enter</kbd> across the roving tabindex; the key map
is in `docs/guides/dashboard.md`). Reduced motion is honoured globally —
`src/styles/motion.css` zeroes the motion tokens under
`prefers-reduced-motion: reduce` — but that is a property of the stylesheet, not
of a test.

A WCAG 2.2 AA gate, automated or manual, is a goal of the dashboard refresh, not
a property this suite establishes. Do not read a green run as evidence of AA
conformance.

**SPA bundle weight** — `scripts/check_bundle_budget.py` holds the dashboard
build to a set of gzip budgets, and it is **not wired into any workflow**
either. Here the reason is structural: no workflow builds the frontend, and
`ari-core/ari/viz/static/dist/` is generated rather than committed, so the
directory the checker measures never exists on a runner. It *is* registered in
`scripts/quality/generate_quality_report.yaml`, but the aggregator that reads
that file runs in `contracts.yml` in `--target` mode — it merges the JSON
artifacts other jobs uploaded and executes no checker — so the bundle budget
surfaces there as `unavailable`. Run it yourself after a build; it is a row of
the by-hand pre-cutover checklist (`docs/guides/gui_cutover_runbook.md` §2):

```bash
cd ari-core/ari/viz/frontend && npm run build   # the checker never builds
python scripts/check_bundle_budget.py --fail-on-regression
```

It gzips every `ari-core/ari/viz/static/dist/assets/*.js` in-process (level 6,
`mtime=0`, so a rerun over the same build reports identical numbers) and
compares each chunk against its class budget, in KiB of gzip:

| Class | What it matches | Budget |
|---|---|---|
| `entry` | the `<script type="module">` chunk(s) `dist/index.html` references | 100 |
| `route` | lazy route chunks, matched as `<Name>Page-<hash>.js` | 150, with `SettingsPage` and `WizardPage` tightened to 50 |
| `shared` | every other `.js` chunk — vendor splits, locale dictionaries, shared components | 150 |
| `total` | the sum of every `.js` chunk's gzip size | 600 |

The `shared` cap is a deliberate conservative superset: only route chunks were
ever budgeted individually, and extending the same number to everything else
stops a mis-split vendor bundle from hiding outside the route class. The
`total` is a ratchet ceiling, not a target — it exists for the one failure mode
per-chunk budgets are blind to, a dependency duplicated across many chunks or a
fleet of new sub-budget chunks.

Browser metrics (LCP, INP, CLS) are deliberately **not** gated: jsdom paints
nothing, and a shared runner is too noisy for a pass/fail budget. A green bundle
run therefore says nothing about perceived performance; that half is a manual
profile on a fixed machine, recorded in the release evidence.

The exit convention matches the rest of the `scripts/quality` family. A plain
invocation reports and exits 0. `--fail-on-regression` exits 1 on any finding
not frozen in `scripts/quality/check_bundle_budget.allow.yaml`, and that file
does not exist — no budget has ever needed freezing, and a missing allow file
means an empty allowlist, so an over-budget chunk fails on its first run. A
missing `dist/assets` exits 2,
because an absent build is an environment problem rather than a budget
regression.

The budgets themselves live in `scripts/quality/check_bundle_budget.yaml` —
dist path, the route-chunk regex, the four class budgets, and the per-route
overrides. Every key is optional and the checker carries the same values as
in-code defaults, so the YAML earns its place purely by making a budget change
a one-line reviewable diff instead of a code edit. Retune it there, not in the
script.

**Test coverage — a known gap.** Nothing in this repository measures how much of
either half of the codebase a suite actually executes.
`ari-core/ari/viz/frontend/vitest.config.ts` declares no `coverage` block;
`package.json` defines `test` as a bare `vitest run`, adds no coverage script,
and lists no coverage provider among its devDependencies — `@vitest/coverage-v8`
appears in `package-lock.json` only as one of vitest's own optional peer
dependencies, so `vitest run --coverage` would have to install it first. The
Python half is unmeasured in the same way: `pytest.ini` sets no `--cov`, and no
ARI package depends on `pytest-cov`. No coverage baseline has ever been recorded
for either.

Two numbers were set as targets during the dashboard refresh and never
implemented. They are recorded here as a **known gap** rather than as policy,
and a green suite is evidence for neither: line and branch coverage of 90% for
the pure-logic frontend layers, and an overall figure baselined on first
measurement and then ratcheted upward toward 80%, with any drop treated as a
regression.

Two things would have to be settled before either number could mean anything.
First, the layers the 90% target named — reducers, serializers, API wrappers and
the config-resolver adapter — map onto this code only in part.
`src/services/api/` is the API wrapper layer and does exist. But the frontend
holds no reducers at all (a case-insensitive search for `reducer` under `src/`
returns nothing), it has no serializer module (the only two matches for
`serializ` under `src/` are comments, in `services/api/client.ts` and
`hooks/useRunEvents.ts`), and the config resolver is Python —
`ari-core/ari/config/resolver.py`, reached over HTTP
rather than through a frontend adapter. Second, a ratchet needs somewhere to
run, and no workflow runs the frontend suite — the same reason the shell
accessibility baseline and the bundle budget above are hand-run rows of the
pre-cutover checklist rather than CI gates.

## Writing a regression test

Pattern:

1. Capture the bug as a test that fails with `assert <observed> ==
   <expected>`.
2. Land the test alone first (red commit).
3. Land the fix on top.

This separates "what we expected" from "how we fixed it" in `git
log` and survives subsequent rewrites of the fix.

## See also

- `pytest.ini` — repo-wide config.
- `docs/concepts/architecture.md` — runtime architecture (helps when picking
  the right test layer).
- `docs/reference/public_api.md` — boundary tests check imports
  against this surface.
