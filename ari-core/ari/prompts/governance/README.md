# ari/prompts/governance

Committed governance-actor prompt templates for the ARI-RQGM
GovernanceOrchestrator (docs/plans/ari_rqgm Task 05 §5.3 / §7). Loaded via
`FilesystemPromptLoader.load_versioned("governance/<name>")`; the returned
`sha256[:12]` is stamped as the governance record `prompt_hash` and recorded
via `record_prompt_use` (→ `prompt_trace.jsonl`, `phase="governance"`).

- `auditor.md` — Auditor: decide borderline prosecution cases (rule-first,
  LLM-second; clear threshold cases never reach the LLM). Placeholders:
  `{target_component_id}`, `{target_role}`, `{reliability_block}`,
  `{evidence_block}`.
- `defender.md` — Defender: rebuttal per filed motion. Placeholders:
  `{motion_block}`, `{evidence_block}`, `{target_outputs_block}`.
- `governance_judge.md` — GovernanceJudge: rule each motion, bounded by the
  deterministic board scores. Placeholders: `{motion_block}`,
  `{defense_block}`, `{board_scores_block}`.

Every LLM decision has a total deterministic fallback (no motion /
procedural default defense / dismissed), so `llm=None` runs a fully
deterministic audit. Prompt *evolution* is Task 07/11 scope; these files
change only through the existing prompt-snapshot blessing flow
(`test_prompt_snapshots.py`, `test_prompt_extraction.py`).
