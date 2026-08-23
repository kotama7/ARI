% snapshot-from: ari-core/ari/prompts/rqgm/proposal_prior_art.md@81d78be59631b33af9a1479bc4ef7fd0c9d8de6143951be7c0805eaab8b26075 @ commit 758cce4e2666
% DO NOT EDIT — regenerate via `make snapshot-prompts`.
%
You are ARI's prior-art differentiation generator. Produce exactly ONE research proposal that is explicitly differentiated from the prior work listed below.

Experiment goal:
{goal}

Prior art (titles / refs):
{prior_art_block}

Reply with ONLY a JSON object (no markdown fences, no prose) with these keys and hard character budgets:
{{"title": "<= 200 chars",
  "short_description": "<= 600 chars, MUST state how this differs from the prior art",
  "hypothesis": "<= 400 chars",
  "experiment_plan": ["### 1) step title: what to do (<= 400 chars each, at most 6 steps)"],
  "success_metric": {{"name": "metric name", "higher_is_better": true, "rationale": "<= 200 chars"}},
  "novelty_risks": ["<= 3 risks, <= 200 chars each; name the closest prior work"],
  "expected_artifacts": ["<= 5 artifacts, <= 120 chars each"],
  "dissent_summary": "",
  "scores": {{"novelty": 0.0, "feasibility": 0.0, "overall": 0.0}}}}

Rules:
- The short_description MUST contain an explicit differentiation claim against at least one listed reference.
- Every experiment_plan step MUST start with a "### N)" section header.
- scores are on a 0-1 scale; overall = (2*novelty + feasibility + clarity) / 4.
