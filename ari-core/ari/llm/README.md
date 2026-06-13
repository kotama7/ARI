# ari.llm

Thin wrappers around LiteLLM for the agent loop and skills: turn
ARI-internal calls into `completion(...)` and record cost. No prompt
templates here (those live under `ari/prompts/`).

## Contents

- `README.md` — this file.
- `__init__.py` — public `LLMClient` + contract.
- `cli_server.py` — OpenAI-compatible HTTP shim for agentic CLIs.
- `client.py` — `LLMClient`/`LLMMessage`: completion + tool calling + cost recording.
- `Plan.md` — ローカルモデル決定性（seed/digest/thinking）の実装計画（handoff study）.
- `routing.py` — TODO

## See also

- **Public symbol (`LLMClient`) & contract** → the `__init__.py` module docstring (authoritative).
- **LLM env vars** → `docs/reference/configuration.md`.
- **Cost accounting** → `ari-core/ari/cost_tracker.py`.
