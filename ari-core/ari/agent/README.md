# ari.agent

ReAct loop, environment capture, and per-stage workflow guidance — the
conversational driver that runs an LLM in a tool-calling loop against the
MCP skills.

## Contents

- `README.md` — this file.
- `__init__.py` — package module-map docstring.
- `guidance.py` — per-stage step-guidance + metrics-validation helpers.
- `loop.py` — `AgentLoop` driver + per-node prompt builder.
- `message_utils.py` — ReAct-message helpers (`_extract_job_ids`, `_tool_was_called`).
- `metric_contract.py` — producer/agent half of the metric-correctness contract (mirrors `pipeline.claim_gate`): domain-neutral obligation text (`build_contract_obligation`), run-level claim-coverage + lineage-chaining steering (`build_coverage_status`, `build_expand_coverage_hint`, `build_inherited_data_note`, `collect_node_measurement_names`), and the post-emit continuation nudge (`build_emission_nudge`).
- `react_driver.py` — generic ReAct driver for pipeline `react:` stages, with sandbox enforcement.
- `run_env.py` — capture/read helper for `_run_env.json`.
- `tool_manager.py` — OpenAI tool conversion, dispatch, phase-aware filtering.
- `workflow.py` — `WorkflowHints` dataclass injected into `AgentLoop`.
- `shims/` — executable `PATH` shims for the reproducibility sandbox.
  - `README.md` — shims index.
  - `git.sh` — intercepts only `git clone` of the paper's ref; other git passes through.

## See also

- **Module map & outward interface** → the `__init__.py` module docstring (authoritative).
- **Per-node prompt composition / pipeline-driven ReAct** → `docs/concepts/architecture.md`.
- **Split history** → `git log -- ari-core/ari/agent/`.
