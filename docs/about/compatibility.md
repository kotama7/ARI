---
sources:
  - path: ari-core/pyproject.toml
    role: config
  - path: setup.sh
    role: doc
  - path: ari-core/ari/memory/letta_client.py
    role: implementation
last_verified: 2026-05-26
---

# Compatibility & Support

What ARI runs on. For the *policy* around versions (SemVer, support windows,
deprecation), see [Release & versioning policy](release_policy.md).

## Python

| | Version |
|---|---|
| Hard requirement | **Python ≥ 3.9** (`requires-python` in `ari-core/pyproject.toml`) |
| Recommended | **3.10+** (the [Quickstart](../getting-started/quickstart.md) targets 3.10 or later) |

`setup.sh` checks the interpreter and installs the rest. Run it as your normal
user — never with `sudo`.

## Operating systems

| OS | Status |
|---|---|
| Linux | Supported |
| macOS | Supported |
| Windows | Via WSL2 |

## Memory backend (Letta)

ARI's memory is backed by [Letta](https://docs.letta.com) (formerly MemGPT)
since v0.6.0. `setup.sh` bootstraps it, auto-detecting the best deployment:
Docker → Singularity/Apptainer → pip (skip with `SKIP_LETTA_SETUP=1`).

The live behaviour is verified against **Letta 0.16.7** (see the implementation
note in [Memory architecture](../concepts/memory.md)). Check a running backend
with `ari memory health`. Each checkpoint also carries a
`memory_backup.jsonl.gz` snapshot, so a run stays portable even across Letta
versions.

## LLM backends

Model routing goes through LiteLLM, so any OpenAI-compatible provider works.
Select with `ARI_BACKEND` / `ARI_MODEL` (always use the provider prefix, e.g.
`openai/gpt-4o`).

| Backend | `ARI_BACKEND` | Notes |
|---|---|---|
| Ollama | `ollama` | Local, free, no API key (default for getting started) |
| OpenAI | `openai` | Cloud, paid; `OPENAI_API_KEY` |
| Anthropic | `claude` | Cloud, paid; `ANTHROPIC_API_KEY` |
| Any OpenAI-compatible | (custom) | Routed via LiteLLM |

Per-phase model overrides are available (e.g. a cheaper model for idea
generation, a stronger one for paper writing) — see
[Configuration](../reference/configuration.md) and
[Environment variables](../reference/environment_variables.md).

## Skills vs core

Skills are versioned independently of `ari-core`. A skill at `0.7.x` works with
any `ari-core` `0.7.y` (compatibility within a minor); across minors, expect a
coordinated release. See [Release policy → Compatibility windows](release_policy.md#compatibility-windows).

---

See also: [Release policy](release_policy.md) · [About](index.md) ·
[Quickstart](../getting-started/quickstart.md) ·
[Environment variables](../reference/environment_variables.md)
