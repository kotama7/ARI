# Requirement: LLM Backend Boundary

## 1. Purpose

- Audit LLM provider usage across the codebase.
- Keep `ari-core/ari/llm/` as the primary LLM boundary.
- Avoid direct concrete provider calls outside the approved boundary.
- Preserve existing model behavior.

## 2. Current Problem

LLM usage may occur in multiple layers (evaluator, agent, orchestrator, viz)
and some may bypass `ari.llm`. The intended public surface is
`ari.public.llm`, backed by `ari/llm/` (`client.py`, `routing.py`,
`cli_server.py`). Direct provider calls outside this boundary make provider
changes risky and scatter credentials/config handling.

## 3. Scope

### In Scope

- Listing direct LLM/provider usages.
- Classifying acceptable vs. problematic usage.
- Proposing boundary consolidation.

### Out of Scope

- Changing provider behavior, model selection, or routing outcomes.
- Adding/removing providers.
- Changing the CLI shim backend behavior.

## 4. Files to Inspect First

```text
ari-core/ari/llm/
ari-core/ari/evaluator/
ari-core/ari/agent/
ari-core/ari/orchestrator/
ari-core/ari/viz/api_ollama.py
ari-core/ari/viz/api_settings.py
ari-skill-*/src/
```

Confirmed: `ari/llm/` has `client.py`, `routing.py`, `cli_server.py`;
`ari.public.llm` is the intended stable entry. There is a CLI-shim backend
(`claude -p` / `codex exec` made OpenAI-compatible) — treat the shim as an
existing, working boundary; do not alter its behavior here.

## 5. Expected Changes

- List direct LLM/provider usages.
- Classify acceptable and problematic usage.
- Propose boundary consolidation.
- Avoid changing provider behavior without tests.

## 6. Step-by-Step Execution Plan

1. Grep core and skills for provider SDK imports and HTTP calls to LLM
   endpoints (OpenAI-compatible, Ollama, Anthropic, etc.).
2. For each hit, determine whether it routes through `ari.llm` /
   `ari.public.llm` or calls a provider directly.
3. Classify: acceptable (inside `ari.llm`, or a justified server like
   `cli_server.py` / `api_ollama.py`) vs. problematic (domain logic calling a
   provider directly).
4. Propose moving problematic calls behind the boundary (do not implement
   behavior-changing moves without tests; small, behavior-neutral moves may be
   done in this PR).
5. Run section 8 checks.

## 7. Compatibility Requirements

- Model selection, routing, prompts, and provider responses are unchanged for
  the same inputs.
- `api_ollama.py` and settings-driven model/provider behavior unchanged.
- The CLI shim (`:8900` OpenAI-compatible) behavior unchanged.

## 8. Tests and Smoke Checks

```bash
pytest ari-core/tests -q
bash scripts/run_all_tests.sh
```

LLM behavior is environment-sensitive (real backends, credentials, GPU). Verify
representative calls on a real environment where possible; otherwise document
what could not be verified. Document unavailable dependencies.

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

- Routing/credential handling is subtle; moving a call behind the boundary can
  change which provider/model/key is used. Verify identical resolution.
- Some "direct" calls may be intentional infrastructure (shim server, ollama
  proxy) and must not be moved.

## 12. Follow-up Candidates

- Consolidating any problematic call left in place.
- A guard test asserting domain modules import only `ari.public.llm` /
  `ari.llm`.
