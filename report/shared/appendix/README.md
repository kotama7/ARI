# report/shared/appendix

Verbatim appendix material shared across the en/ja/zh report builds.

## Contents

- `README.md` — this file.
- `prompts/` — runtime LLM prompt snapshots, grouped by subsystem.
  - `README.md` — prompts index.
  - `agent/` — agent prompt snapshots (auto-generated): `system.md`.
    - `system.md` — agent system prompt.
  - `evaluator/` — evaluator prompt snapshots (auto-generated): `extract_metrics.md`, `peer_review.md`.
    - `extract_metrics.md` — metric-extraction prompt.
    - `peer_review.md` — peer-review prompt.
  - `orchestrator/` — orchestrator prompt snapshots (auto-generated): `bfts_expand.md`, `bfts_expand_select.md`, `bfts_select.md`, `lineage_decision.md`, `root_idea_selector.md`.
    - `bfts_expand.md` — BFTS expand prompt.
    - `bfts_expand_select.md` — BFTS combined expand+select prompt.
    - `bfts_select.md` — BFTS select prompt.
    - `lineage_decision.md` — lineage-decision prompt.
    - `root_idea_selector.md` — root-idea selection prompt.
  - `pipeline/` — pipeline prompt snapshots (auto-generated): `keyword_librarian.md`.
    - `keyword_librarian.md` — keyword-librarian prompt.
  - `viz/` — viz prompt snapshots (auto-generated): `wizard_chat_goal.md`, `wizard_generate_config.md`.
    - `wizard_chat_goal.md` — wizard chat goal prompt.
    - `wizard_generate_config.md` — wizard config-generation prompt.
