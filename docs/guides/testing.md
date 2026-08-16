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
last_verified: 2026-08-17
---

# How to Test ARI Code

This guide covers the testing conventions for `ari-core` and the
`ari-skill-*` packages: where tests live, what fixtures are
expected, and how to keep determinism guarantees intact.

## Repository layout

```
ari-core/tests/                    — core regression tests
ari-skill-<name>/tests/            — skill-local tests
ari-skill-<name>/tests/conftest.py — skill-level fixtures (13 of 17 skills;
                                     harness and knowledge ship no tests/ at
                                     all, idea and paper-re ship tests without
                                     one; benchmark and plot add a SECOND
                                     conftest at the package root)
pytest.ini                         — repo-wide config
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
pytest ari-core/tests/test_react_driver.py::TestRunReact  # one class
pytest ari-core/tests/test_gui_v1_api.py::test_projects_happy_path  # one case
pytest -k 'memory and not letta' -q              # by keyword
```

## ari-core conventions

### Always isolate writes

ARI used to write into `$HOME/.ari/`.  v0.5.0 removed that path, and two
guards keep it gone. `ari-core/tests/test_no_user_home_writes.py` holds a
single test, `test_module_imports_do_not_write_user_home`, which imports a
frozen list of eight core modules (`ari.config`, `ari.paths`,
`ari.cost_tracker`, `ari.lineage`, `ari.memory.client`,
`ari.memory.local_client`, `ari.publish.backends.ari_registry`,
`ari.clone.resolvers.ari`) under a fake `HOME` and asserts none of them
creates `$HOME/.ari/` at import time. The suite-wide guard is the
`refactor-guards` workflow, which runs all of `ari-core/tests` with `HOME`
redirected and fails the job if `$HOME/.ari/` exists afterwards — that is
what makes "no test ever creates files there" enforced rather than assumed.
When you write a new test that touches the filesystem:

- Use `monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(tmp_path))`.
- Use `tmp_path` for any auxiliary directories.
- Never call `Path.home()` directly in production code; if you must
  in a test, document why and add it to the audit list.

### Smoke tests for the agent loop

`ari-core/tests/test_react_driver.py` covers `ari.agent.react_driver` with
stubbed `LLMClient` and `MCPClient` dependencies, so the ReAct loop is
exercised without a live LLM or MCP server. It is a unit file, not a
node-to-node integration run: three helper classes pin the pure functions
(`TestValidatePaths` — 11 cases over `_validate_paths_in_args`, the
sandbox-escape and traversal rules; `TestBuildWindow` — conversation-window
truncation; `TestFinalToolDef`), and `TestRunReact` drives `run_react`
end-to-end four ways — completion when the final tool is called, a sandbox
violation blocking dispatch, the max-steps exit when the final tool never
fires, and log-file persistence.

Follow the same shape whenever you add an agent-level feature: stub the
clients, assert the loop's observable transitions, and keep the file free of
network and subprocess calls.

### Determinism guarantees (P2)

Nothing in this repository asserts a whole-run "same seed, same tree"
invariant end to end. What is pinned is narrower and worth knowing by name:
`ari-core/tests/test_gui_baseline_run_fixtures.py::test_same_seed_is_byte_identical`
generates two checkpoints from the same `(nodes, seed)` and compares the
files byte for byte (with `test_different_seed_changes_content` as its
negative), and the memory suite pins the isolation properties a
deterministic tree depends on —
`ari-skill-memory/tests/test_checkpoint_isolation.py` (two checkpoints never
see each other) and `ari-skill-memory/tests/test_ancestor_scope.py` (three
sibling branches, no cross-sibling contamination).

When a determinism regression sneaks in:

1. Write a regression test first that pins the expected tree shape.
2. Bisect the change set; the offender almost always introduces a
   `dict` ordering reliance or a hash that depends on `id(...)`.
3. Add the test to the per-domain suite (memory, BFTS, etc.).

### Synthetic checkpoint fixtures

The GUI and `/api/v1` reader tests do not ship checkpoints — they generate
them. `ari-core/tests/fixtures/gui_refresh/` holds two pure-Python factories:

- `run_fixture_factory.py` — `make_run_checkpoint(dest, nodes=N, seed=S)`
  writes a run checkpoint: `tree.json`, `nodes_tree.json` and `results.json`
  go through the real `ari.checkpoint.save_tree_json` /
  `save_nodes_tree_json` / `save_results_json`, so their formatting matches
  the production writers byte for byte; `experiment.md`, `idea.json`,
  `meta.json` and `cost_trace.jsonl` are written directly, since no
  `save_*_json` helper owns them. The optional `paper` / `review` / `ors` /
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

Ten of the seventeen `ari-skill-*` packages ship a `tests/test_server.py`
(benchmark, coding, evaluator, hpc, idea, paper, tool-registry, transform,
vlm, web); the rest name their surface file differently or do not have one —
`ari-skill-orchestrator/tests/test_mcp_surface.py` is the same kind of file
under another name. Nine of the ten import the server module in-process and
call the tool functions directly with fixture inputs, asserting the response
shape. Most reach it as `from src.server import …`; a packaged skill imports
its installed module instead (`ari_skill_hpc.server`), and `ari-skill-coding`
also loads it by path with `importlib.util.spec_from_file_location`.
`ari-skill-tool-registry` is the one exception, and deliberately: its surface
is a broker, so its `tests/test_server.py` launches `src/server.py` as a real
stdio child process (`PythonStdioLauncherV1` + `StdioMCPAdapter`, which reaches
`stdio_client` at `ari-skill-tool-registry/src/providers.py`:514) and drives it
over an MCP session. Outside the ten, the surface file under another name does
the same: `ari-skill-orchestrator/tests/test_mcp_surface.py` starts
`src/server.py` as a child process twice — once over `streamable-http`
(`subprocess.Popen`, :188) and once over stdio (`stdio_client`, :282). Those two
suites are the only places a subprocess appears.

Two things this layer mostly leaves to a workflow gate. Tool-list-versus-
`skill.yaml` parity and generated-`mcp.json` drift are the `contracts`
workflow's `scripts/check_skill_manifests.py`, described under "What gets
tested at PR time" below; exactly one suite also pins them for itself, so do
not read a green skill suite as covering them —
`ari-skill-orchestrator/tests/test_mcp_surface.py:38-43` asserts that the
runtime tool names, `skill.yaml`'s `tools:`, `mcp.json`'s `tools` and a literal
`EXPECTED` set of twelve are all one set. And
there is no shared MCP test harness: no `mcp.testing` module exists (the
`mcp` package ships `cli`, `client`, `os`, `server`, `shared` and `types`)
and nothing in the repo imports one. Each suite builds its own fixtures —
`ari-skill-memory/tests/conftest.py` is a readable reference for the pattern
(a `tmp_path`-scoped `ARI_CHECKPOINT_DIR`, a backend fixture, a signed
call-context issuer, and a fake Letta client).

Several suites do call `list_tools()`, and what each compares it against
differs. `ari-skill-coding` validates the declared `outputSchema` of the five
tools that carry one (`tests/test_server.py`:715-723); `ari-skill-hpc`
(`tests/test_server.py`:40-46) and `ari-skill-idea`
(`TestMcpToolRegistration`) assert that specific tool names are (and, for hpc,
are not) registered; `ari-skill-tool-registry` asserts the live broker surface
is exactly its six public operations (`tests/test_server.py`:48-50); and
`ari-skill-transform` reads the registered names
(`tests/test_metric_contract_seam.py`:22). In all of those the expected list is
a literal written in the test — `ari-skill-orchestrator` is the only suite that
compares it against the manifest.

### LLM mocks

Skills that call an LLM (`evaluator`, `paper`, `paper-re`, `idea`,
`replicate`, `transform`, `plot` — in `src/planning.py`, which is where its
`litellm.acompletion` call lives — and `vlm`) must mock the LLM in
unit tests.

The reference example is
`ari-skill-paper-re/tests/test_litellm_completer.py`, and its technique is
module injection rather than HTTP interception: `_install_fake_litellm`
builds a `types.ModuleType("litellm")` with a stub `acompletion` and
`monkeypatch.setitem(sys.modules, "litellm", fake)`, so nothing reaches the
network and the test can assert the exact kwargs the completer forwarded.
`respx` is available and used where a real HTTP client is the thing under
test (`ari-skill-memory/tests/test_letta_http_regression.py`); `pytest-mock`
is installed in CI for the same purpose.

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

**Tests** — the Python suites are split across two workflows, and neither
runs the other's paths.

- `refactor-guards` runs `pytest ari-core/tests/ -q` once, with `HOME`
  redirected to a scratch directory and four files excluded by `--ignore`
  (`test_letta_restart_live.py`, `test_letta_start_scripts.py`,
  `test_ollama_gpu.py`, `test_dashboard_html.py` — the last because it wants
  a Vite build no job produces). `test_no_user_home_writes.py` and
  `test_public_api_boundary.py` (Phase 4, ensures skills only import from
  `ari.public.*`) ride along inside that one invocation; they are not
  separate steps. The workflow then fails if `$HOME/.ari/` exists, and a
  second job diffs the PR for new `~/.ari` references outside an explicit
  allowlist. Five further jobs (import boundaries, directory policy,
  complexity, ruff lint, dead code) are all **advisory** — every one carries
  `continue-on-error: true`, and all but ruff lint (a bare `ruff check
  ari-core`) also pass `--warning-only`, so a finding never turns a PR red. It is one of the two workflows that also trigger on the
  `refactoring` branch (an in-file comment still claims it is the only one;
  `skill-tests` was added with the same trigger later).
- `skill-tests` runs seven skill suites, one pytest process per path
  (`paper`, `evaluator`, `web`, `plot`, `memory`, `transform`, `replicate`),
  with `-p no:randomly`. `ari-skill-coding` is **not** among them, and
  `ari-skill-paper-re` is deliberately excluded because it vendors PaperBench
  through a `git+chz` pull. The per-process split exists for the same reason
  `pytest.ini` keeps the skills out of `testpaths`.

**Dashboard frontend** — the `dashboard-frontend` workflow is a hard gate
(no `continue-on-error`) over `ari-core/ari/viz/frontend`: `npm ci`,
`npm run typecheck` (`tsc --noEmit`), then `npm test` (`vitest run`). It
deliberately does **not** run `npm run build` or the Playwright screenshot
capture. Because `npm test` is a whole-suite run, it also carries
`src/__tests__/v1TypesDrift.test.ts` — which regenerates
`src/services/api/v1types.gen.ts` in memory from `ari/viz/v1/openapi.json`
and asserts byte equality — so editing the OpenAPI document without
rerunning `npm run gen:v1types` fails here.

**Contracts** — the `contracts` workflow runs
`python scripts/check_skill_manifests.py` as a hard admission gate. It
validates every canonical manifest, declared environment access, live tool
surface, generated `mcp.json`, workflow reference, version, and default-on
name collision. Contract JSON snapshots cover the public API, MCP inventory,
CLI tree, and dashboard endpoints.

**Docs & structure** — three workflows keep the documentation set in sync:

- `readme-sync` — every directory's `## Contents` index lists the files
  beneath it (`scripts/readme_sync.py --check`).
- `docs-sync` — full-tree invariants. Six hard gates: declared `sources:`
  paths resolve (`check_doc_sources.py`), `docs/i18n/landing.{en,ja,zh}.js` share
  one key set (`check_i18n_js.py`), HTML-site i18n integrity and the public
  version pin (`check_site_i18n.py`), every `href`/`src` in the hand-written
  `docs/*.html` resolves (`check_doc_links.py --html-only`), the root
  `README.{md,ja,zh}` share one heading shape (`check_readme_parity.py`), and
  `report/{en,ja,zh}` are structurally parallel (`report/scripts/check_i18n.py`,
  Gate 6). Then three advisory, non-blocking steps: translation freshness
  (`check_translation_freshness.py`), Markdown link integrity
  (`check_doc_links.py` — it checks both halves of a link, so it reports a
  broken-file count and a broken-*anchor* count separately), and trunk-state
  staleness (`check_docs_source_sync.py --warning-only`), which covers the one
  dimension the others cannot see: a source whose newest commit already on
  `main` is more recent than the `last_verified` of a doc that declares it. Its
  frozen baseline is empty (`scripts/check_docs_source_sync.allow.yaml`:34,
  `known-offenders: []`), so every finding it reports is net-new. A second job
  checks the report PDFs are in sync (`sync_report_pdf.sh --check`) and builds
  the VitePress site.
- `docs-change-coupling` — diff-based: a `report/{en,ja,zh}` language-paired
  file (chapter, `strings.tex`, `main.tex`) edited in one language must be
  mirrored in the other two in the same PR (`check_report_cochange.py`, hard);
  and when a source listed in a doc's `sources:` changes, that doc's
  `last_verified` should be bumped (`check_ref_coupling.py`, advisory).

Run any doc gate locally from the repo root, e.g.
`python scripts/docs/check_i18n_js.py`.

**Dashboard translations** — the dashboard UI ships its own trilingual
dictionaries at `ari-core/ari/viz/frontend/src/i18n/{en,ja,zh}.ts`, and the docs
gates do not reach them: `check_i18n_js.py` reads only
`docs/i18n/landing.{en,ja,zh}.js` (its `SURFACES` tuple has one entry), and its
key pattern `^\s*'([^']+)'\s*:` matches single-quoted keys only, so it cannot
parse dictionaries whose keys are bare identifiers. The rule
is the same one the docs set follows — the three locales must declare an
**identical key set**, with no key repeated inside a file — so a new UI string
has to be added to all three in the same change. A key present in one locale but
missing from another falls back to the English string, or renders as the raw key
name when `en` lacks it too (`t()` in `src/i18n/index.ts`). Values are
deliberately not compared: a proper noun may legitimately read the same in all
three.

Two checks enforce this, and only one of them runs in CI:

- `python scripts/check_dashboard_ux.py --fail-on-regression` — key-set parity
  plus duplicate detection over the three `.ts` files, bundled with the same
  script's other dashboard-UX checks. **No workflow invokes it**, so run it
  yourself when you touch dashboard strings. It exits 1 on any finding not
  frozen in `scripts/quality/check_dashboard_ux.allow.yaml`, and that allowlist
  holds no i18n entries, so a parity break fails on its first run. Without the
  flag the script prints its report and exits 0.
- `npx vitest run src/i18n/__tests__/parity.test.tsx`, from
  `ari-core/ari/viz/frontend` — the same invariant asserted against the imported
  dictionaries, with a `KNOWN_DRIFT` allowlist that is currently empty. This one
  **is** gated: the `dashboard-frontend` workflow's `npm test` step runs the
  whole Vitest suite, this file included. Its duplicate-key assertion is weaker
  than the Python one, because a TypeScript object literal has already collapsed
  any repeated key by the time the test reads it.

Both pass on the current tree: the three dictionaries carry one identical key
set, with no duplicates.

**Dashboard accessibility** — the dashboard declares **no WCAG conformance
level**. No conformance target exists in this documentation set or in the
frontend suite, and nothing here should be read as one. What exists is a set of
frozen baselines in
`ari-core/ari/viz/frontend/src/__tests__/shellA11yBaseline.test.tsx`. It runs in
CI as part of the `dashboard-frontend` workflow's `npm test` step, and it is
also a row of the by-hand pre-cutover checklist
(`docs/guides/gui_cutover_runbook.md` §2). Run just this file from
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
rather than through a frontend adapter. Second, a ratchet needs a stored
baseline and something to compare against it. The `dashboard-frontend`
workflow now gives the frontend suite somewhere to run, but it runs
`npm test`, not `npm test -- --coverage`, and no baseline file is committed
on either side of the codebase — so the place exists and the measurement
still does not.

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
