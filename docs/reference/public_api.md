---
sources:
  - path: ari-core/ari/public
    role: implementation
  - path: ari-core/tests/test_public_api_boundary.py
    role: test
last_verified: 2026-06-10
---

# `ari.public` — Stable API for skills

`ari.public` is the **only** module surface that `ari-skill-*`
packages may depend on.  Everything outside it is internal and may
change without notice.  The package is a thin re-export layer over
the corresponding `ari.<module>` private implementations so core can
refactor freely while the skill-facing contract stays put.  It was
introduced in v0.7.1 (Phase 4 of the v0.7+ refactor) and is enforced
by `ari-core/tests/test_public_api_boundary.py`.

## Sub-modules

| Sub-module | What it re-exports | Skills that use it |
|---|---|---|
| `ari.public.config_schema` | Pydantic config models (`ARIConfig`, `LLMConfig`, ...) | callers needing typed settings |
| `ari.public.container` | Container runtime helpers (`ContainerConfig`, `run_in_container`, ...) | `ari-skill-coding` (tests) |
| `ari.public.cost_tracker` | LLM cost recording (`bootstrap_skill`, `record`, ...) | `ari-skill-plot` (LLM call cost) |
| `ari.public.llm` | `LLMClient` (LiteLLM wrapper with cost integration) | callers that prefer ARI's wrapper |
| `ari.public.paths` | `PathManager` (checkpoint path resolver) | callers that need scoped paths |
| `ari.public.claim_gate` | Deterministic claim-evidence hard gate (`run_hard_gate`) + concept→invariant registry (`classify_concept`, `scan_science_data`, `CONCEPT_INVARIANTS`) | `ari-skill-evaluator`, `ari-skill-transform` |
| `ari.public.verified_context` | Verified-context helpers (`render_grounded_block`, `write_verified_context`, `build_verified_context`) | `ari-skill-paper` |

## `ari.public.config_schema`

Re-exports the Pydantic models from `ari.config`:

```python
from ari.public.config_schema import (
    ARIConfig,
    BFTSConfig,
    CheckpointConfig,
    EvaluatorConfig,
    LLMConfig,
    LoggingConfig,
    SkillConfig,
)

cfg = ARIConfig.model_validate(yaml.safe_load(open("ari.yaml")))
```

The exported names track `ari/config/__init__.py` symbol-for-symbol; consult
that file for current field shapes.  Source:
`ari-core/ari/public/config_schema.py`.

## `ari.public.container`

Re-exports the container runtime from `ari.container`:

| Symbol | Purpose |
|---|---|
| `ContainerConfig` | Dataclass: `mode`, `image`, `bind_paths`, `gpu`, ... |
| `detect_runtime()` | Returns `"singularity"` / `"apptainer"` / `"docker"` / `"none"` based on `which` lookups |
| `config_from_env()` | Builds a `ContainerConfig` from `ARI_CONTAINER_*` env vars (returns `None` when unset) |
| `pull_image(cfg)` | Pulls / builds the image referenced by `cfg` |
| `run_in_container(cfg, cmd, ...)` | Runs a process inside the container, returning exit code + captured streams |
| `run_shell_in_container(cfg, script, ...)` | Same, but takes a bash script string |
| `list_images()` | Inventory of available images in the active runtime |
| `get_container_info()` | Diagnostic dict with runtime + image health |

Source: `ari-core/ari/container.py` → `ari-core/ari/public/container.py`.

## `ari.public.cost_tracker`

Re-exports the LLM cost tracker from `ari.cost_tracker`:

| Symbol | Purpose |
|---|---|
| `CostTracker` | Aggregator instance written to `cost_log.jsonl` |
| `CallRecord` | Per-call dataclass (`model`, `prompt_tokens`, `completion_tokens`, `cost_usd`, `metadata`) |
| `init(log_dir)` | Initialise the global tracker rooted at `log_dir` |
| `init_from_env()` | Initialise using `ARI_CHECKPOINT_DIR` automatically (most callers want this) |
| `bootstrap_skill(skill_name, phase=None)` | Convenience wrapper for skills — initialises + tags every record |
| `record(**kwargs)` | Append a manual `CallRecord` (used when not going through LiteLLM callback) |
| `set_default_metadata(**kwargs)` | Tag every subsequent record with extra metadata |
| `get()` | Get the current tracker (or `None`) |

Skills typically only need `bootstrap_skill` at startup; the LiteLLM
callback handles the rest.  Source:
`ari-core/ari/cost_tracker.py` → `ari-core/ari/public/cost_tracker.py`.

## `ari.public.llm`

Re-exports `LLMClient` from `ari.llm.client`:

```python
from ari.public.llm import LLMClient

client = LLMClient(model="ollama/qwen3:32b")
resp = await client.complete([{"role": "user", "content": "..."}])
```

Use this in preference to calling LiteLLM directly — `LLMClient`
threads through ARI's cost tracker and metadata tagging.  Source:
`ari-core/ari/llm/client.py` → `ari-core/ari/public/llm.py`.

## `ari.public.paths`

Re-exports `PathManager` from `ari.paths`:

```python
from ari.public.paths import PathManager

paths = PathManager.from_env()        # honours ARI_CHECKPOINT_DIR
nodes_json = paths.checkpoint / "nodes_tree.json"
```

`PathManager` is the central resolver — never read `ARI_CHECKPOINT_DIR`
directly from a skill.  Source: `ari-core/ari/paths.py` →
`ari-core/ari/public/paths.py`.

## `ari.public.claim_gate`

Re-exports the deterministic claim-evidence hard gate and its
concept→invariant registry from `ari.pipeline.claim_gate`:

| Symbol | Purpose |
|---|---|
| `run_hard_gate` | The gate entry point — blocks claims whose evidence fails the deterministic checks |
| `classify_concept` | Maps a concept to its universal-invariant family |
| `scan_science_data` | Scans science data against the registered invariants |
| `CONCEPT_INVARIANTS` | The domain-general concept→invariant registry (single source of truth) |

```python
from ari.public.claim_gate import run_hard_gate
```

`ari-skill-evaluator` and `ari-skill-transform` reach the gate through
this stable public surface rather than the private
`ari.pipeline.claim_gate` path, so both skills reuse the *same*
universal-invariant logic the gate blocks on — no duplicated domain
math.  Source: `ari-core/ari/pipeline/claim_gate/` →
`ari-core/ari/public/claim_gate.py`.

## `ari.public.verified_context`

Re-exports the verified-context helpers from
`ari.pipeline.verified_context`:

| Symbol | Purpose |
|---|---|
| `render_grounded_block` | Renders a grounded (citation-backed) block of context |
| `write_verified_context` | Writes the verified-context artifact for callers that build it |
| `build_verified_context` | Builds the verified-context structure |

```python
from ari.public.verified_context import render_grounded_block
```

`ari-skill-paper` reaches these helpers through the stable public
surface rather than the private `ari.pipeline.verified_context` path.
Source: `ari-core/ari/pipeline/verified_context.py` →
`ari-core/ari/public/verified_context.py`.

## Putting it together — a minimal skill

A skill that uses only `ari.public.*`: bootstrap cost tracking, resolve a
checkpoint-scoped path, and make a cost-tracked LLM call.

```python
from ari.public import cost_tracker
from ari.public.paths import PathManager
from ari.public.llm import LLMClient

# 1. Tag every LLM call this skill makes (reads ARI_CHECKPOINT_DIR).
cost_tracker.bootstrap_skill("ari-skill-example", phase="bfts")

# 2. Resolve paths through PathManager — never read ARI_CHECKPOINT_DIR directly.
paths = PathManager.from_env()
nodes_json = paths.checkpoint / "nodes_tree.json"

# 3. LLM call goes through ARI's wrapper, so the cost is recorded automatically.
client = LLMClient(model="ollama/qwen3:32b")
resp = await client.complete([{"role": "user", "content": "Summarise: ..."}])
```

The call's tokens and USD cost land in the checkpoint's `cost_trace.jsonl`
tagged with the skill name and phase — no manual `record()` needed.

## Stability guarantees

- **MAJOR (SemVer)** — symbols, signatures, and behaviour can break.
- **MINOR** — new symbols added; existing ones extended in
  backwards-compatible ways (new optional kwargs allowed).
- **PATCH** — bug fixes only.

Anything imported via `from ari import <X>` directly (rather than
`from ari.public import <X>`) bypasses this contract — skill authors
should grep their imports against `ari/public/__init__.py` and move
internal-import boundaries through the public layer.

## See also

- `ari-core/ari/public/__init__.py` — module-level docstring with
  the canonical sub-module list.
- `docs/guides/extension_guide.md` — how to write a new skill that depends
  only on `ari.public`.
- `CONTRIBUTING.md::Software-engineering discipline §3` — public-API
  rule (skills only see `ari.public.*`).
- `docs/_archive/refactor_audit.md` (§4) — historical Phase 4 inventory.
