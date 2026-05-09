# ari-skill-plot

Scientific figure generation MCP skill — produces PNG / PDF figures
either deterministically from a fixed schema or by letting an LLM
write matplotlib code from data shape and a natural-language intent.

## MCP tools

### `generate_figures` (deterministic, P2-safe)

Take a list of BFTS nodes, render canonical comparison figures
(metric-vs-config, metric-vs-time, learning curves, etc.), and write
them into a target directory together with a manifest.

Arguments (key fields):

| Field | Meaning |
|---|---|
| `nodes_json_path` | Path to `nodes_tree.json` (or compatible list) |
| `output_dir` | Where PNG / PDF files are written |
| `figure_spec` | What to plot (axes, group-by, fill/aggregation) |

Returns a JSON manifest enumerating every emitted figure with its
caption and source node ids.

### `generate_figures_llm` (P2 exception)

LLM examines the data shape and intent, writes matplotlib code, and
the skill executes it under the same `_run_plot_code` sandbox used by
the deterministic path.  Optional VLM caption pass after rendering.

Arguments (key fields):

| Field | Meaning |
|---|---|
| `nodes_json_path` | Source data |
| `intent` | Natural-language description of what to visualise |
| `output_dir` | Output directory |

Returns the same manifest format plus the generated matplotlib code
for audit.

## Determinism

`generate_figures` is byte-deterministic for a given matplotlib
version — same nodes in, same PNG out.  `generate_figures_llm` is a
P2 exception: the matplotlib code is LLM-generated and may differ
from run to run.  Always prefer the deterministic tool when the
figure shape is known up front.

## Environment variables

| Variable | Purpose | Default |
|---|---|---|
| `VLM_MODEL` | Vision LLM for caption generation (optional pass after rendering) | `openai/gpt-4o` |
| `ARI_LLM_MODEL` | LLM that writes the matplotlib code in `_llm` mode | (none — required for `_llm`) |
| `LLM_MODEL` | Cross-skill fallback when `ARI_LLM_MODEL` is unset | (none) |
| `ARI_LLM_API_BASE` | LiteLLM API base override | LiteLLM default |
| `OPENAI_API_KEY` | Needed when the VLM or LLM is OpenAI-hosted | (none) |

## ari-core boundary

`src/server.py` imports `from ari import cost_tracker` to send LLM
spend back to the central tracker.  Phase 4 of the master refactor
moves this to `ari.public.cost_tracker`; see
`ari-skill-plot/REFACTORING.md`.

## Test gap

No tests are checked in yet.  A smoke test that mocks the LLM and
calls `generate_figures` against a fixture `nodes_tree.json` is the
recommended starting point.

## Development

```bash
python -m ari_skill_plot.server
```

There are no automated tests yet — see "Test gap" above.

## See also

- `docs/skills.md` — high-level summary in the master skill index.
- `ari-skill-vlm/README.md` — VLM-side figure review (different concern).
- `ari-core/ari/cost_tracker.py` — cost accounting hook.
