# Core / Skill Public Contract (requirement 09)

Task-control note from `09_core_skill_public_contract.md`. Captured 2026-05-30
from a 3-agent classification of every `ari-skill-*/src` import of `ari.*`
(builds on the req-01 dependency note). Goal: skills depend only on the stable
contract (`ari.public.*` / `ari.protocols.*` / `ari.mcp.*`); private-internal
edges are migrated or explicitly deferred — never broken.

## Stable surface (unchanged)

`ari.public` re-exports: `config_schema`, `container`, `cost_tracker`, `llm`,
`paths`, **and now `run_env`** (added this PR). `ari.protocols`: `evaluator`.
Each `ari.public.X` is a thin `from ari.X import *` re-export, so the internal
`ari.X` path keeps working (compatibility wrapper, per §7).

## Classification → action

| Private edge | Skills | Action (this PR) |
|--------------|--------|------------------|
| `from ari import cost_tracker` (top-level, not `ari.public`) | evaluator, idea, memory, paper-re, paper, replicate, transform, vlm, web (9) | **Migrated** to the dual pattern `try: from ari.public import cost_tracker except ImportError: from ari import cost_tracker` (the form `ari-skill-plot` already shipped). Zero behavior change — same module object; fallback keeps older cores working. |
| `from ari.container import …` | coding (`src` + test) | **Migrated** to `ari.public.container` (public-first, internal fallback). |
| `from ari.agent.run_env import …` | coding (`capture_env`), hpc (`shell_capture_snippet`) | **New re-export** `ari.public.run_env`; call sites migrated public-first. |
| `from ari.lineage import …` | idea | **Deferred** — virsci-specific (`format_ancestor_pool_for_virsci` is named for its consumer → unstable contract); already try/except-guarded. |
| `from ari.clone import …` | paper-re | **Deferred** — single adopter; verify `clone()` arg signature is stable before exposing. |
| `from ari.publish import …` | transform (prod), paper-re (test) | **Deferred** — confirm `publish()`/`promote()` dispatch contract is settled across backends (zenodo/gh/ari_registry/local_tarball) before a public shim. |
| `from ari.orchestrator import node_selection` | transform (×2) | **Deferred** — deepest break; reaches orchestrator-internal scheduling. Wants a *protocol* (narrow surface), not a whole-module re-export. |

The deferred set is the live to-do list (req 09 §12 follow-ups), enforced by the
guard test's allowlist — shrinking it is the next step.

## Critical nuance handled (coding container test)

`ari.public.container` does `from ari.container import *`, which **binds**
`run_shell_in_container` into the public module at import time. So
`monkeypatch.setattr(ari.container, "run_shell_in_container", fake)` does **not**
reach the public binding. When coding's production import moved to
`ari.public.container`, its test (`test_run_bash_uses_container_when_env_set`)
would have silently taken the host-fallback path. Fixed by patching **both**
modules in the test (verified empirically: patching `ari.container` alone leaves
`ari.public.container` pointing at the original). This is the kind of regression
a naive import-swap would introduce and `run_all_tests.sh` would catch.

## Guard test

`ari-core/tests/test_skill_public_contract.py` (2 tests) scans every
`ari-skill-*/src` for production `ari.*` imports and fails on a private-core path
that is neither public, in the deferred allowlist, nor an `except ImportError`
compatibility fallback. A second test fails if an allowlist entry goes stale
(import removed) so the allowlist can't rot. (Per req 09 §12.)

## Checks

`bash scripts/run_all_tests.sh` — **2843 passed / 0 failed / 26 skipped** across
all 13 suites (ari-core 2231 incl. the 2 new guards; coding 24 incl. the
repointed container test; every migrated skill green). No skill behavior, import
path, or `mcp.json` changed; internal paths still work via the public re-exports.

## Follow-up candidates (→ §12)

- Expose `ari.public.publish` (publish/promote/PublishError) once the backend
  dispatch contract is confirmed stable → migrate transform + paper-re.
- Expose `ari.public.clone` (clone/CloneError) once `clone()` signature is
  confirmed stable → migrate paper-re.
- Add a *protocol* for the narrow `node_selection` surface transform needs →
  migrate transform (deepest boundary break).
- Decide a public memory-backup boundary (idea/lineage `format_ancestor_pool_*`,
  `ari.memory_cli` test edge) — needs interface design, not a quick re-export.
- Each migration shrinks `test_skill_public_contract.py`'s allowlist.
