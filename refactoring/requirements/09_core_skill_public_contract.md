# Requirement: Core / Skill Public Contract

## 1. Purpose

- Ensure skills depend on stable ARI contracts.
- Prefer `ari-core/ari/public/` and `ari-core/ari/protocols/`.
- Reduce direct dependency on private core internals.
- Preserve all existing skill behavior.

## 2. Current Problem

The 14 `ari-skill-*` packages are separate from core but import from `ari`.
Some imports may reach into private internals rather than the stable surface
(`ari.public`, `ari.protocols`). This makes core refactors risky because they
can break skills that depend on internals.

## 3. Scope

### In Scope

- Listing current skill imports from `ari`.
- Classifying each as public/stable vs. private/internal.
- Proposing re-exports or protocol additions where a skill needs something not
  yet exposed publicly.

### Out of Scope

- Breaking or restructuring skill packages.
- Changing skill behavior.
- Renaming public modules.

## 4. Files to Inspect First

```text
ari-core/ari/public/
ari-core/ari/protocols/
ari-core/ari/mcp/
ari-skill-*/src/
ari-skill-*/mcp.json
ari-skill-*/pyproject.toml
```

Confirmed stable surface today: `ari.public` exposes `config_schema.py`,
`container.py`, `cost_tracker.py`, `llm.py`, `paths.py`; `ari.protocols`
exposes `evaluator.py`. Skills are: benchmark, coding, evaluator, hpc, idea,
memory, orchestrator, paper, paper-re, plot, replicate, transform, vlm, web.

## 5. Expected Changes

- List current skill imports from `ari`.
- Classify them as public/stable or private/internal.
- Propose re-exports or protocol additions where needed.
- Avoid breaking existing skill packages.

## 6. Step-by-Step Execution Plan

1. For each `ari-skill-*/src/`, grep for `import ari` / `from ari` and record
   every imported symbol.
2. Classify each import: public (`ari.public`, `ari.protocols`), MCP boundary
   (`ari.mcp`), or private internal.
3. For private-internal imports, decide: (a) the symbol should be re-exported
   from `ari.public`, (b) a protocol should be added to `ari.protocols`, or
   (c) the skill should use an existing public equivalent.
4. Where a re-export is safe, add it to `ari.public` (keeping the internal path
   working as a compatibility wrapper) — only if this requirement's PR stays
   small; otherwise list as follow-up.
5. Run section 8 checks across skills.

## 7. Compatibility Requirements

- Every skill imports and runs exactly as before; existing import paths keep
  working (use re-export wrappers, do not remove internal paths).
- `mcp.json` contracts and skill entrypoints unchanged.
- No change to core public module names.

## 8. Tests and Smoke Checks

```bash
bash scripts/run_all_tests.sh
```

`run_all_tests.sh` runs each skill's tests in its own pytest process to avoid
the cross-skill `sys.modules['src.server']` collision — use it rather than a
single pytest invocation across skills. Document unavailable dependencies.

## 9. Completion Criteria

The requirement is complete only when:

- all scoped changes are implemented
- existing behavior is preserved
- tests or smoke checks pass
- risks are documented
- follow-up work is moved to another requirement file
- completion is recorded in `refactoring/COMPLETED.md`
- this requirement file is deleted in the same PR

## 10. Deletion Rule

This file must remain in `refactoring/requirements/` while the requirement is
incomplete.

When all completion criteria are satisfied, record the completion in
`refactoring/COMPLETED.md`, then delete this file in the same PR.

Do not delete this file for partial completion.

## 11. Risks

- Skills may import internals dynamically or via re-exports; static grep can
  miss edges. Cross-check with `01`.
- Adding to `ari.public` is a contract commitment; keep additions minimal and
  intentional.

## 12. Follow-up Candidates

- Each proposed re-export/protocol addition not done in this PR becomes a
  follow-up.
- A guard test that fails when a skill imports a non-public `ari` path.
