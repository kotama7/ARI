# ari.prompts

External prompt templates for ARI core (Phase PC), lifted out of code so
prompts are editable without touching Python. Loaded via the package's
`PromptLoader` (see `ari.protocols.PromptLoader`).

## Contents

- `README.md` — this file.
- `__init__.py` — exports + `PromptLoader` plumbing.
- `_loader.py` — `PromptLoader` Protocol + `FilesystemPromptLoader`.
- `_provenance.py` — append-only `prompt_trace.jsonl` recorder + `prompt_versions.json` rollup (`record_prompt_use`, `hash12`); stdlib-only, no LLM calls.
- `registry.py` — `PromptRegistry` — key enumeration, `str.format` placeholder introspection and `PromptEntry` describe, layered over the loader.
- `agent/` — agent ReAct system prompt.
  - `README.md` — agent index.
  - `system.md` — the agent system prompt.
- `evaluator/` — metric extraction & peer review.
  - `README.md` — evaluator index.
  - `extract_metrics.md` — numeric metric extraction.
  - `peer_review.md` — rubric-driven paper review.
- `governance/` — Committed governance-actor prompt templates for the ARI-RQGM
- `llm/` — prompt fragments for the LLM shim layer.
  - `mcp_name_resolution.md` — bare → namespaced MCP tool-name translation note (`{rows}`) injected into CLI-shim system prompts.
- `orchestrator/` — BFTS expand/select, lineage & root-idea decisions.
  - `README.md` — orchestrator index.
  - `bfts_expand.md` — leaf-expansion prompt.
  - `bfts_expand_select.md` — combined expand + select prompt.
  - `bfts_select.md` — next-node selection prompt.
  - `lineage_decision.md` — continue / switch_to_idea / fanout / terminate.
  - `root_idea_selector.md` — run-start root-idea pick.
- `pipeline/` — pipeline-stage prompts.
  - `README.md` — pipeline index.
  - `keyword_librarian.md` — keyword extraction for BFTS-context building.
- `rqgm/` — Committed prompt templates for the ARI-RQGM prompt-defined actors (Tasks 03/06/07)
- `viz/` — wizard chat prompts.
  - `README.md` — viz index.
  - `wizard_chat_goal.md` — chat that elicits the experiment goal.
  - `wizard_generate_config.md` — turns the goal into a launch config.

## See also

- **Format:** Markdown filled with Python `str.format` — placeholders are single-brace `{name}`.
- **Loading & history** → the `__init__.py` module docstring.
