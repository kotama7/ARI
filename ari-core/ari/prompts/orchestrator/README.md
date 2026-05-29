# ari.prompts.orchestrator

Prompt templates for `ari.orchestrator` (BFTS + lineage decisions).

## Contents

- `README.md` — this file.
- `bfts_expand.md` — leaf-expansion prompt.
- `bfts_expand_select.md` — combined expand + select prompt.
- `bfts_select.md` — next-node selection prompt.
- `lineage_decision.md` — continue / switch_to_idea / fanout / terminate.
- `root_idea_selector.md` — run-start root-idea pick.

## See also

- **Format:** Markdown + single-brace `{name}` placeholders filled via `str.format` (e.g. `{parent_metrics_json}`, `{ancestors_block}`). See `ari/prompts/README.md`.
