# ari-skill-plot

Source-bound scientific figure planning and deterministic rendering. Every
native result is an `ari.figure-manifest/v1` or `ari.figure-batch/v1` document
that binds the exact ScienceData slice, units, declarative specification,
renderer environment, revision lineage, and PNG/PDF bytes.

## MCP tools

- `render_figure(request)` validates a canonical `FigureSpecV1` and renders it
  through the fixed matplotlib implementation.
- `generate_figures(science_data_path, output_dir, n_figures=3)` chooses stable
  default specs from claim-eligible typed measurements. It has no model call.
- `generate_figures_llm(...)` lets a model choose only an admitted metric ID,
  fixed chart type, and x-axis mode. The model cannot emit values, units,
  captions, paths, Python, SVG, or image bytes.

All input and output paths must remain below `output_dir`, which is treated as a
closed `WorkspaceRefV1`. Native generation rejects pre-v1 ScienceData. The
unversioned figure map is available only through the offline
`read_legacy_figure_batch` reader and is never admitted as native evidence.

## Scientific and security properties

- Numeric vectors and units come only from claim-eligible `ScienceDataV1`
  measurement records.
- Axis units are mandatory and bound by `spec_digest`.
- The renderer executes no caller or model code and launches no subprocess.
- The old directory-scan fallback, implicit VLM caption call, generated Python,
  SVG rasterizer, and private `_run_plot_code` sandbox were removed in v0.2.
- Each revision is written under `figures/revisions/NN/`; a review must bind the
  exact parent manifest and the configured two-iteration cap is enforced.
- Replay identity includes Python, matplotlib, backend, font bytes, platform,
  and optional container digest. Byte identity is claimed only inside the same
  environment digest.

The planner prompt is stored in `src/prompts/figure_planner.md`. Raw planner
response and exact prompt bytes are content-addressed artifacts. Visual quality
and captions belong to the explicit `ari-skill-vlm` review stage.

## Environment

| Variable | Purpose |
|---|---|
| `ARI_MODEL_PLOT` | Preferred declarative planner model |
| `ARI_MODEL_PLOT_REVISION` | Provider/model revision recorded in the manifest |
| `ARI_LLM_MODEL` / `LLM_MODEL` | Cross-skill model fallback |
| `ARI_LLM_API_BASE` / `LLM_API_BASE` | Optional LiteLLM endpoint |
| `ARI_CONTAINER_DIGEST` | Optional immutable rendering environment identity |

## Verification

```bash
PYTHONPATH=../ari-core pytest -q tests
```

The corpus covers six chart types, deterministic replay, content digests,
invalid values/units, closed paths, malicious planner fields, revision lineage,
and the explicit legacy reader.
