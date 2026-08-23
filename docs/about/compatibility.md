---
sources:
  - path: ari-core/pyproject.toml
    role: config
  - path: setup.sh
    role: doc
  - path: scripts/setup/detect_env.sh
    role: config
  - path: scripts/setup/install_letta.sh
    role: config
  - path: ari-core/ari/memory/letta_client.py
    role: implementation
  - path: ari-core/ari/llm/routing.py
    role: implementation
  - path: ari-core/ari/llm/client.py
    role: implementation
  - path: ari-core/ari/memory_cli.py
    role: implementation
last_verified: 2026-08-16
---

# Compatibility & Support

What ARI runs on. For the *policy* around versions (SemVer, support windows,
deprecation), see [Release & versioning policy](release_policy.md).

## Python

| | Version |
|---|---|
| Package metadata | **Python ≥ 3.9** (`requires-python` in `ari-core/pyproject.toml`) |
| What `setup.sh` accepts | **Python ≥ 3.10** — `scripts/setup/detect_env.sh` warns on anything older and `exit 1`s when no interpreter reaches 3.10 |

The two disagree: `pip install` will accept 3.9, the installer will not. Treat
**3.10** as the real floor — several dependencies (`mcp>=1.1`) require it.

`setup.sh` checks the interpreter, creates `.venv` at the repo root, and
installs the rest. Run it as your normal user — never with `sudo`.

## Operating systems

| OS | Status |
|---|---|
| Linux | Supported |
| macOS | Supported |
| Windows | Via WSL2 |

## Memory backend (Letta)

ARI's memory is backed by [Letta](https://docs.letta.com) (formerly MemGPT)
since v0.6.0. `setup.sh` bootstraps it, auto-detecting the best deployment:
Docker → Singularity/Apptainer → pip (skip with `SKIP_LETTA_SETUP=1`). Docker
is skipped outright when `SLURM_CLUSTER_NAME` or `SLURM_JOB_ID` is set, even if
the daemon is usable, so a setup run from inside a job allocation lands on
Singularity/Apptainer.

The live behaviour is verified against **Letta 0.16.7** (see the implementation
note in [Memory architecture](../concepts/memory.md)). Check a running backend
with `ari memory health`. Each checkpoint also carries a
`memory_backup.v1.json.gz` snapshot, so a run stays portable even across Letta
versions.

## LLM backends

Model routing goes through LiteLLM, so any OpenAI-compatible provider works.
Select with `ARI_BACKEND` / `ARI_MODEL`. You do not have to write the provider
prefix yourself: `resolve_litellm_model` derives it from `ARI_BACKEND`
(`ollama` → `ollama_chat/…`, `claude`/`anthropic` → `anthropic/…`, `cli-shim`
→ `openai/…`, `openai` and anything unknown → unchanged), and a model id that
already carries a known prefix is passed through untouched.

| Backend | `ARI_BACKEND` | Notes |
|---|---|---|
| Ollama | `ollama` | Local, free, no API key (default for getting started) |
| OpenAI | `openai` | Cloud, paid; `OPENAI_API_KEY` |
| Anthropic | `claude` | Cloud, paid; `ANTHROPIC_API_KEY` |
| Claude Code CLI | `claude_code` | **Not** LiteLLM-routed for the agent loop — `LLMClient` dispatches to `ari/llm/claude_code/`, and tool calling is unsupported there (fails loud). MCP skills resolving `ARI_BACKEND` directly still go to the plain Anthropic API and need `ANTHROPIC_API_KEY`. |
| Any OpenAI-compatible | (custom) | Routed via LiteLLM |

Per-phase model overrides are available (e.g. a cheaper model for idea
generation, a stronger one for paper writing) — see
[Configuration](../reference/configuration.md) and
[Environment variables](../reference/environment_variables.md).

## Skills vs core

Skills are versioned independently of `ari-core`, and their numbers do not track
it: `ari-core` is at `0.9.1` while the shipped skills range from `0.1.0` to
`2.0.0`. No code enforces a skill↔core version pair, so pair them by the
coordinated release rather than by matching numbers.
See [Release policy → Compatibility windows](release_policy.md#compatibility-windows).

---

See also: [Release policy](release_policy.md) · [About](index.md) ·
[Quickstart](../getting-started/quickstart.md) ·
[Environment variables](../reference/environment_variables.md)
