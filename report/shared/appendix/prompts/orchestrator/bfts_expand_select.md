% snapshot-from: ari-core/ari/prompts/orchestrator/bfts_expand_select.md@cff71dfe47770d9fdc23c704ca01717030f73b7ecb36f95cb9f1a49624709465 @ commit e780fa5626fc
% DO NOT EDIT — regenerate via `make snapshot-prompts`.
%
You are selecting which completed research node to expand next in a BFTS tree.

Experiment goal: {experiment_goal}

Completed nodes awaiting expansion:
{candidates}

Select the single most promising node to expand. Prefer nodes with high scientific_score, strong metrics, and unexplored directions. Avoid nodes that have already been retried many times or are at excessive depth.
Reply with ONLY the index number (0-based).