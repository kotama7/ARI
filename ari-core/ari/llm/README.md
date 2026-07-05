# ari.llm

Thin wrappers around LiteLLM for the agent loop and skills: turn
ARI-internal calls into `completion(...)` and record cost. No prompt
templates here (those live under `ari/prompts/`).

## Contents

- `README.md` — this file.
- `__init__.py` — public `LLMClient` + contract.
- `cli_server.py` — OpenAI-compatible HTTP shim for agentic CLIs.
- `client.py` — `LLMClient`/`LLMMessage`: completion + tool calling + cost recording.
- `routing.py` — `resolve_litellm_model`: single source of truth for litellm provider-prefix rules so every caller routes a `(model, backend)` to the same id.
- `claude_code/` — Claude Code as an LLM-API-compatible backend (`backend: claude_code`; bypasses litellm).
  - `README.md` — claude_code index.
  - `__init__.py` — public re-exports (`ClaudeCodeProvider`, policy/serializer
  - `cli_runner.py` — strict_reproducibility runner: one fresh subprocess per
  - `command.py` — strict-mode `claude -p` argv builder (text vs native
  - `policy.py` — frozen `ClaudeCodePolicy` + `validate_policy()`: the fail-loud
  - `provenance.py` — per-call artifact sandbox under
  - `provider.py` — `ClaudeCodeProvider` orchestrating serialize → run →
  - `sdk_runner.py` — low_overhead runner: `claude_agent_sdk.query()` per
  - `serializer.py` — deterministic OpenAI-messages → single-prompt
  - `validation.py` — ARI-side JSON extraction + jsonschema (Draft 2020-12)

## See also

- **Public symbol (`LLMClient`) & contract** → the `__init__.py` module docstring (authoritative).
- **Claude Code backend** → `docs/reference/claude_code_provider.md`.
- **LLM env vars** → `docs/reference/configuration.md`.
- **Cost accounting** → `ari-core/ari/cost_tracker.py`.
