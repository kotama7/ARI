---
sources:
  - path: ari-core/ari/llm/claude_code
    role: implementation
  - path: ari-core/ari/config/__init__.py
    role: implementation
  - path: ari-core/ari/llm/client.py
    role: implementation
last_verified: 2026-07-03
---

# Claude Code LLM Provider (`backend: claude_code`)

The `claude_code` backend drives a local **Claude Code** installation as a
plain, stateless LLM API behind ARI's existing provider abstraction: ARI code
calls the same `LLMClient.complete()` it uses for Ollama/OpenAI/Anthropic,
and the provider additionally exposes `structured_complete()` for
schema-validated JSON. Claude Code is **not** used as an agent executor
here — no tools, no MCP, no memory, no CLAUDE.md, no hooks/plugins/skills,
no session reuse. ARI's BFTS control, `claim_evidence_hard_gate`, metric
recomputation, EAR generation and reproducibility checks remain entirely on
the ARI side.

Implementation: `ari-core/ari/llm/claude_code/` (policy, serializer, command
builder, CLI/SDK runners, provenance, provider). Verified against Claude
Code 2.1.198.

## Modes

### `strict_reproducibility` (default)

For experiments, papers and baselines. Every request:

1. serializes the full ARI-side message history into one deterministic
   prompt (`serializer.py`; ARI is the source of truth for conversation
   state — Claude Code's transcript is never canonical),
2. spawns a **fresh** `claude -p` subprocess with a hermetic profile:

   ```
   claude -p --output-format json --max-turns 1 --model <model>
          [--system-prompt-file system.txt] [--bare] --safe-mode
          --strict-mcp-config --disable-slash-commands --no-chrome
          --no-session-persistence --setting-sources "" --tools ""
          --disallowedTools "*" --permission-mode plan
   ```

   `--setting-sources ""` is always explicit: with the flag omitted the CLI
   loads user/project/local settings by default, and `--safe-mode` does not
   stop settings `env`/auth overrides from applying (verified by A/B test
   on 2.1.198).

   with the prompt on stdin, a throwaway per-call `cwd/`, an environment
   **allowlist** (auth/proxy/locale only; parent `CLAUDE_CODE_*` session
   variables are dropped) plus forced
   `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`,
   `CLAUDE_CODE_SKIP_PROMPT_HISTORY=1`,
   `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`,
3. parses the single JSON result envelope, validates any response schema
   ARI-side, records full provenance and cost, and returns an
   `LLMResponse`.

`--bare` restricts auth to `ANTHROPIC_API_KEY`/apiKeyHelper (OAuth
credentials are never read). The default `bare: null` therefore
auto-resolves: `--bare` is used only when `ANTHROPIC_API_KEY` or
`ANTHROPIC_AUTH_TOKEN` is present; otherwise the flag is dropped (all other
isolation flags stay) and the decision is recorded in provenance
(`bare_auto_resolved`). An explicit `bare: true` without a key is honoured
and fails loudly ("Not logged in") rather than silently weakening isolation.
`home_mode: sandbox` gives each call a temp `$HOME` (requires key auth,
since OAuth credentials live under the real `$HOME`).

### `low_overhead`

For implementation-speed work. The Python provider object (and the Agent SDK
worker) stays resident, but **each request is a fresh
`claude_agent_sdk.query()`** with `max_turns=1`, empty tools, empty MCP
servers, empty setting sources, the forced memory-suppression env vars, and
`--no-session-persistence` passed through the SDK's `extra_args` escape
hatch (an SDK without `extra_args` fails loudly — transcripts would
otherwise persist under `~/.claude/projects/`). A resolved sandbox HOME is
applied via `options.env["HOME"]`.
`resume` / `continue_conversation` / session-id reuse are never passed — the
runner has no API that could accept them. The SDK event stream is saved to
`trace.jsonl`. If `claude-agent-sdk` is not installed the provider raises a
clear error; falling back to the strict CLI runner happens only with the
explicit `sdk_fallback_to_cli: true` (and is recorded in provenance).

Known difference: the SDK's subprocess transport inherits the parent
environment (options.env only adds vars), so the strict env allowlist cannot
be enforced in this mode — recorded in provenance as `hermetic_env: false`.
The SDK is pointed at the same CLI binary strict mode uses (`cli_path` =
resolved `claude_bin`; falls back to the SDK's bundled CLI when not on
PATH); provenance records `sdk_version` plus the full options snapshot.
Verified live against claude-agent-sdk 0.2.110 (install via
`pip install 'ari-core[claude-code]'` or `pip install claude-agent-sdk`).

## Configuration

```yaml
llm:
  backend: claude_code
  model: claude-sonnet-5
  claude_code:
    mode: strict_reproducibility  # strict_reproducibility | low_overhead
    max_turns: 1
    timeout_sec: 300
    output_format: json
    hermetic: true
    tools: []
    disallowed_tools: ["*"]
    disable_auto_memory: true
    disable_prompt_history: true
    bare: null                    # auto by ANTHROPIC_API_KEY presence
    safe_mode: true
    strict_mcp_config: true
    disable_slash_commands: true
    no_chrome: true
    no_session_persistence: true
    permission_mode: plan
    setting_sources: []
    record_provenance: true
    structured_output_transport: prompt   # prompt | native
    schema_repair_retries: 1
    home_mode: auto               # auto | real | sandbox
    claude_bin: claude
    sdk_fallback_to_cli: false
```

Env overrides: `ARI_BACKEND=claude_code`, `ARI_CLAUDE_CODE_MODE`,
`ARI_CLAUDE_CODE_MODEL`, `ARI_CLAUDE_CODE_MAX_TURNS`,
`ARI_CLAUDE_CODE_TIMEOUT_SEC`, `ARI_CLAUDE_CODE_RECORD_PROVENANCE`,
`ARI_CLAUDE_CODE_BIN` (see
[environment_variables.md](./environment_variables.md)).

GUI: the New Experiment wizard and the Settings page offer **Claude Code**
as a provider; the launcher exports `ARI_BACKEND=claude_code` (default model
`claude-sonnet-5` when none is chosen). The API-key field is optional — an
existing Claude Code OAuth login works; a key enables the `--bare` profile.

## Policy enforcement (fail-loud)

`ClaudeCodePolicy` (`policy.py`) freezes the hermetic contract;
`validate_policy()` rejects — listing every violation at once — any config
with non-empty `tools`, a deny list missing `"*"`, MCP enabled, session
resume, memory/history suppression off, `safe_mode`/`no_session_persistence`
off, or `max_turns > 1` without the explicit `allow_multi_turn` opt-in.
Session-reuse CLI flags (`--resume`, `--continue`, `--session-id`,
`--fork-session`) are additionally asserted absent from every built command.

If the installed Claude Code rejects a flag (version drift), the call fails
with `ClaudeCodeUnsupportedFlagError`. Listing the flag under
`compat_drop_flags` drops it explicitly and records it in provenance as
`unsupported_flags` — isolation is never weakened silently.

## Structured output

`response_schema` is always saved to `schema.json` and the final output is
**always validated ARI-side** (jsonschema, Draft 2020-12). Two transports:

- `prompt` (default): the canonical schema JSON is embedded in the prompt's
  `<response_contract>` block; the strictest flag profile is kept
  (`--permission-mode plan`, `--max-turns 1`, `--disallowedTools "*"`).
- `native`: the schema is passed via `--json-schema`. Verified on 2.1.198:
  Claude Code implements this through a `StructuredOutput` **tool** call,
  which plan mode denies and which costs one extra turn — so this transport
  runs with `--allowedTools StructuredOutput --permission-mode default
  --max-turns 2` (while `--tools ""` keeps every other tool disabled), and
  the validated object is read from the envelope's `structured_output`.

On validation failure the provider makes at most **one** repair retry (same
hermetic policy, prompt = original + invalid output + validation errors,
recorded under `attempt_2/`), then raises `ClaudeCodeSchemaError`.

## Provenance

With `record_provenance: true` (default) every call writes
`<checkpoint>/claude_code/<call_id>/` (temp dir when no checkpoint is
pinned; the path is returned as `LLMResponse.provenance_path`):

```
input/messages.json  prompt.txt  system.txt  schema.json
command.json  env_allowlist.json  claude_version.txt
stdout.json  stderr.log  result.json  validation.json
input_hashes.json  output_hashes.json  provenance.json
trace.jsonl (low_overhead)  cwd/  attempt_2/ (repair retry)
```

`provenance.json` captures provider/mode/model, `claude --version` or SDK
version, the exact argv/options, cwd, env allowlist markers (names only —
secret values are never written), the full policy including
`resume_used: false`, `session_id` (recorded, never reused),
`unsupported_params` (e.g. `temperature`/`max_tokens`, which have no CLI
equivalent), return code, attempts, and the validation outcome. Cost is
booked to `cost_trace.jsonl` via `ari.cost_tracker` with Claude's
authoritative `total_cost_usd` (this backend bypasses litellm, so the global
litellm callback never sees it).

## Why not an interactive session + `/clear`

A resident interactive Claude Code with `/clear` between requests would keep
one long-lived process whose state (loaded settings, memory directives,
compaction, skill/hook surface, working directory) is only *approximately*
reset by `/clear` — none of it is observable or hash-verifiable per call.
Fresh processes (or fresh SDK queries) make the unit of execution equal the
unit of provenance: every call has exactly one command, one env, one input
hash set and one output.

## Why not resume / session transcripts

Replaying or hand-writing Claude Code session transcripts to `--resume` them
would make Claude Code's on-disk session format the canonical conversation
state — an undocumented, version-drifting format ARI cannot validate.
ARI instead keeps the message history itself and serializes it fully on
every request; `--no-session-persistence` guarantees there is nothing on
disk to resume. `session_id`s appearing in result envelopes are recorded in
provenance for audit and never passed back.

## Recommended settings

- **paper / idea / eval completion calls** (BFTS selectors, judges,
  summarizers): the defaults (`strict_reproducibility`, `max_turns: 1`,
  `structured_output_transport: prompt`, `record_provenance: true`).
- **iterating on prompts / plumbing**: `mode: low_overhead`
  (`pip install claude-agent-sdk`), optionally
  `record_provenance: false` outside real runs.
- **ReAct agent phases and MCP skills do not run through this backend.**
  The agent loop's tool-calling calls fail loudly
  (`ClaudeCodeToolsUnsupportedError`) — point them at a tool-calling backend
  (e.g. `cli-shim`, `ollama`, `openai`). MCP skills' direct litellm calls
  route deterministically to the plain Anthropic API
  (`anthropic/<model>`, requires `ANTHROPIC_API_KEY`).
- A future agent-executor use of Claude Code must be a **separate backend**
  (e.g. `claude_code_agent_executor`) with its own policy surface, not a
  relaxation of this one.

## Reproducibility limits

Identical prompts do **not** guarantee bit-identical LLM output (sampling,
server-side changes). What this provider guarantees is *verifiability*:
every input, the full policy, model id, Claude Code/SDK version, command,
environment allowlist, output and their SHA-256 hashes are persisted per
call, so any result can be audited and re-run under the same recorded
conditions.

## Health check

```bash
ari doctor claude-code          # binary, version, policy, command, flag report
ari doctor claude-code --live   # + one real hermetic call with schema validation
```
