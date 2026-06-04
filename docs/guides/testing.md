---
sources:
  - path: ari-core/tests
    role: test
  - path: pytest.ini
    role: config
  - path: scripts/docs
    role: test
  - path: .github/workflows
    role: config
last_verified: 2026-06-04
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

`pytest.ini` at the repo root makes `pytest` from anywhere walk every
test directory.

## Running the suite

```bash
pytest -q                                        # everything
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

## Skill-level conventions

### MCP server tests

Each skill ships a `test_server.py` that:

1. Starts the MCP server in-process (no subprocess).
2. Calls `list_tools()` and asserts the tool list matches `mcp.json`.
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

**Docs & structure** — three workflows keep the documentation set in sync:

- `readme-sync` — every directory's `## Contents` index lists the files
  beneath it (`scripts/readme_sync.py --check`).
- `docs-sync` — full-tree invariants, all hard gates: declared `sources:`
  paths resolve (`check_doc_sources.py`), `docs/i18n/{en,ja,zh}.js` share one
  key set (`check_i18n_js.py`), the root `README.{md,ja,zh}` share one heading
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
