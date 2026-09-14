# ari.llm.claude_code

Claude Code as an LLM-API-compatible ARI backend (`llm.backend: claude_code`).
Two modes: `strict_reproducibility` (fresh hermetic `claude -p` subprocess per
call) and `low_overhead` (resident Agent SDK worker, fresh `query()` per
request — sessions are never resumed). Conversation history stays ARI-side and
is fully re-serialized on every request; tools/MCP/memory/CLAUDE.md/hooks/
skills/session persistence are all suppressed and fail-loud enforced. Full
reference: `docs/reference/claude_code_provider.md`.

## Contents

- `README.md` — this file.
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

- **docs/reference/claude_code_provider.md** → full behavioural reference.
- **ari-core/ari/llm/client.py** → `LLMClient` dispatch
  (`_is_claude_code_target`) that routes this backend around litellm.
- **ari-core/ari/config/__init__.py** → `ClaudeCodeSettings` +
  `ARI_CLAUDE_CODE_*` env overrides.
- **ari-core/ari/cli/doctor.py** → `ari doctor claude-code` health check.
