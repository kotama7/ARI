<!--
  Thanks for contributing to ARI. Fill in the sections below and DELETE any that
  do not apply. This checklist is your self-attestation, NOT the only line of
  defense: the machine-checkable items are ALSO enforced by CI (existing
  refactor-guards.yml / docs-sync.yml / readme-sync.yml, plus the contract-check
  workflows as they land). A PR template cannot fail CI — only workflows can.

  See CONTRIBUTING.md and docs/refactoring/012_github_workflow_integration_plan.md §9
  ("Pull Request Review Checklist Policy") for the rationale behind each item.
-->

## Summary

<!-- What does this PR do, and why? One or two sentences. -->

## Refactoring context

<!-- Delete this whole section if the PR is not part of the refactoring program. -->

- Subtask: <!-- e.g. 047; see docs/refactoring/subtasks/ -->
- Classification: <!-- KEEP / ADAPT / MERGE / MOVE_TO_LEGACY / DELETE_CANDIDATE / REVIEW_REQUIRED -->

## Type of change

- [ ] Bug fix
- [ ] Feature
- [ ] Refactor (behaviour-preserving)
- [ ] Docs
- [ ] CI / tooling

## Contract-preservation checklist

<!--
  Tick each box. "unchanged" is the happy path; otherwise confirm the documented
  fallback. Items backed by CI are noted; the parenthesised checker scripts are
  referenced "when available" — several are planned Phase-8 deliverables and may
  not exist yet, so treat them as self-attestation, not a hard precondition.
-->

- [ ] **CLI** surface unchanged, or the change is documented in `docs/reference/cli_reference.md` and the root README CLI table.
- [ ] **`ari.public.*`** unchanged, or the public-API snapshot is updated with justification (`scripts/check_public_api_contracts.py`, when available). CI: `ari-core/tests/test_public_api_boundary.py`.
- [ ] **MCP tool contracts** (`ari-skill-*/src/server.py`) unchanged, or the tool-schema change is documented in `docs/reference/mcp_tools.md`.
- [ ] **Dashboard API** (`ari-core/ari/viz/routes.py` + `api_*.py`) unchanged, or `ari-core/ari/viz/frontend/src/services/api.ts` and `docs/reference/rest_api.md` are updated in the same PR.
- [ ] **Checkpoint / config file formats** unchanged, or a migration under `ari-core/ari/migrations/` is included.
- [ ] **Prompts**: any inline LLM prompt moved to `ari-core/ari/prompts/<area>/<purpose>.md` with the sha256 snapshot updated (`ari-core/tests/test_prompt_extraction.py`; see `CONTRIBUTING.md`).
- [ ] **Docs `sources:` front-matter and per-directory README `## Contents`** updated. CI-enforced: `docs-sync.yml` / `readme-sync.yml`.
- [ ] **No new `~/.ari/` references** outside the sanctioned allow-list. CI-enforced: `refactor-guards.yml` job `no-new-home-ari-refs`.

## Test evidence

<!-- Paste the relevant results. For a docs- or markdown-only PR these are no-ops; run them to prove no regression. -->

- [ ] `python -m compileall .`
- [ ] `pytest -q` (or the per-package command from `CONTRIBUTING.md`)
- [ ] `ruff check .`
- [ ] Frontend only: `npm test` + `npm run build` under `ari-core/ari/viz/frontend/`

<!-- See also: CONTRIBUTING.md (engineering discipline) and
     docs/refactoring/012_github_workflow_integration_plan.md §9. -->
