% snapshot-from: ari-core/ari/prompts/orchestrator/bfts_select.md@38b1ea409ff58bc0b5342b7fc677b3c64c5374bf35b0d5c9b0594a401fd4b71b @ commit e780fa5626fc
% DO NOT EDIT — regenerate via `make snapshot-prompts`.
%
You are selecting the most promising node to explore next in a research tree.

Experiment goal: {experiment_goal}

Relevant past memories:
{memory_context}

Candidates:
{candidates}

Selection criteria:
- Nodes with has_real_data=True and strong metrics are high-value
- Consider all metrics holistically (multi-objective)
- Deeper nodes with excellent results are worth continuing
- A small diversity_bonus is awarded to underrepresented exploration types; treat it as a soft tiebreaker, not a primary signal
Reply with ONLY the index number (0-based) of the best node.