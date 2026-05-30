# Requirement: Config / Settings / Workflow Unification

## 1. Purpose

- Clarify the relationship between environment variables, CLI options, GUI
  settings, workflow YAML, profiles, and config models.
- Define a single, documented precedence order.
- Preserve existing behavior.

## 2. Current Problem

Configuration enters from many sources: env vars (`.env`, `ARI_*`), CLI
options, GUI settings (`api_settings.py`, which writes a project-scoped settings
file and `.env`), workflow YAML (`pipeline/yaml_loader.py`), profiles
(`ari-core/config/profiles/`), and config models (`ari.config`,
`ari.configs`, `ari.public.config_schema`). The precedence among these is not
documented in one place, and settings logic may be duplicated.

## 3. Scope

### In Scope

- Documenting the current precedence order (as implemented today).
- Identifying duplicated settings logic.
- Proposing central config-loading helpers.

### Out of Scope

- Changing behavior or precedence until the current order is locked down and
  documented.
- Changing `.env` handling, `start.sh`, or `setup_env.sh` behavior.
- GUI redesign.

## 4. Files to Inspect First

```text
ari-core/ari/config/
ari-core/ari/configs/
ari-core/ari/viz/api_settings.py
ari-core/ari/viz/api_workflow.py
ari-core/ari/pipeline/yaml_loader.py
ari-core/config/
scripts/setup/setup_env.sh
start.sh
```

Confirmed present: `ari-core/ari/config/` (`finder.py`, `__init__.py`),
`ari-core/config/` (`default.yaml`, `workflow.yaml`, `profiles/`,
`paperbench_rubrics/`, `reviewer_rubrics/`), and
`scripts/setup/setup_env.sh`. Also relevant: `ari.public.config_schema` (the
intended stable config contract) and `ari.viz.state` which holds
`_launch_config`, `_launch_llm_model`, `_launch_llm_provider`, `_env_write_path`.

## 5. Expected Changes

- Document the current precedence order.
- Identify duplicated settings logic.
- Propose central config-loading helpers.
- Avoid behavior changes until current precedence is locked down.

## 6. Step-by-Step Execution Plan

1. Enumerate every configuration source and where it is read/written.
2. Trace, for representative settings (e.g. LLM model/provider, ports, language,
   paths), exactly which source wins today.
3. Write the precedence order as observed (env vs. CLI vs. GUI vs. YAML vs.
   profile vs. defaults).
4. List duplicated parsing/merging logic across the modules above.
5. Propose (do not yet implement, unless trivial and behavior-neutral) a central
   loader that reproduces the documented precedence.
6. Run section 8 checks; on a real environment, verify a known setting resolves
   the same before/after any helper extraction.

## 7. Compatibility Requirements

- Resolved configuration values are identical to today for the same inputs.
- `.env` read/write semantics (including `ari.viz.state._env_write_path`)
  unchanged.
- `start.sh`, `setup_env.sh`, and GUI settings save/load behavior unchanged.
- Per the user's standing rule: do **not** rewrite user config files
  (e.g. `~/.ari/settings.json`, `.env`) as a workaround — fix the code path.

## 8. Tests and Smoke Checks

```bash
pytest ari-core/tests -q
```

Add/extend precedence tests (env vs. YAML vs. defaults) before any helper
extraction. Verify on a real compute node, not only with fakes, since some
resolution is environment-dependent. Document unavailable dependencies.

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

- Precedence is easy to get subtly wrong; a "cleanup" can flip which source
  wins. Lock behavior with tests **before** touching code.
- Environment-dependent resolution means green tests on a login/fake node are
  not sufficient evidence of correctness.

## 12. Follow-up Candidates

- Implementing the proposed central loader (separate requirement once
  precedence is locked).
- Reducing config-related fields in `ari.viz.state`.
