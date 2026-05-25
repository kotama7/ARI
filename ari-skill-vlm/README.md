# ari-skill-vlm

Vision LLM (VLM) review of figures and tables in generated papers.
Does **not** generate figures (`ari-skill-plot` does that) — it
reads the rendered output and returns critique that the paper
revision loop can act on.

## Responsibilities

- **Figure review**: load a PNG, base64-encode it, send it through
  the VLM with the paper context, and return a structured critique
  (axis labels, units, legend, readability, alignment with the
  caption text).
- **Table review**: send the rendered LaTeX / Markdown table to the
  VLM as text and apply the same critique pass.
- **Batch review**: walk a paper directory, find every figure /
  table, run both passes, and return one consolidated report.

## Internal API

`mcp.json` does not list public tools yet — the skill is invoked
from `ari-skill-paper.review_compiled_paper` and via the internal
ARI loop.  The relevant entry points in `src/server.py`:

| Function | Purpose |
|---|---|
| `review_figure(image_path, context)` | Single-figure critique |
| `review_table(table_text, context)` | Single-table critique |
| `review_paper_figures(paper_dir)` | Batch over a paper directory |

When external exposure is added, both `mcp.json` and this README
should be updated together.

## VLM prompt strategy

- **Figures**: image base64-encoded into the VLM message; prompt
  asks for axis labels, units, legend completeness, readability of
  small text, and consistency with the caption.
- **Tables**: LaTeX / Markdown source sent as text; prompt focuses
  on column alignment, missing units, decimal precision, and
  agreement with the body text.
- **Output**: structured JSON with `issues: [{kind, severity,
  rationale, suggestion}]`.

## Environment variables

| Variable | Purpose | Default |
|---|---|---|
| `VLM_MODEL` | Vision LLM identifier (LiteLLM format) | `openai/gpt-4o` |
| `OPENAI_API_KEY` | Required when the VLM is OpenAI-hosted | (none) |

## Dependencies

- `mcp >= 1.0`
- `litellm >= 1.0` (VLM dispatch)
- `pillow >= 10.0` (image encoding)

## P2 exception

The skill is a P2 exception — VLM output is non-deterministic, so
the same image can produce different critiques on different runs.
Down-stream consumers (`review_compiled_paper`) merge the VLM
output with the rubric review to dampen the variance.

## Development

```bash
pytest tests/ -q
```

## Related skills

- `ari-skill-paper.review_compiled_paper` — primary caller, merges
  VLM output with rubric review (`merge_reviews` tool).
- `ari-skill-plot` — generates the figures this skill reviews.
- `ari-core/ari/pipeline/...` — `_format_vlm_feedback` integrates
  VLM findings into the paper revision loop.

## See also

- `docs/reference/skills.md#ari-skill-vlm` — high-level summary.
- `docs/reference/mcp_tools.md` — argument signatures.
