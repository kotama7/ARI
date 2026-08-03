# ari-skill-evaluator/src

- `server.py` exposes the four evaluator MCP tools and keeps transport logic
  thin; canonical scientific contracts live in `ari.public.evaluation`.
- `prompts/metric_contract_proposal_sys.md` is used only by the explicit,
  always-human-reviewed proposal step.
- `prompts/semantic_review_sys.md` is used only by the independent advisory
  semantic reviewer.

The removed metric/claim/flag extraction prompts must not be restored as an
implicit fallback inside `make_metric_spec`.
