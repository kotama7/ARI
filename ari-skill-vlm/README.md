# ari-skill-vlm

Artifact-bound multimodal review for scientific figures and tables. The skill
does not generate or rewrite content. It verifies the target bytes against a
canonical manifest, applies a versioned criterion profile, stores the raw model
response, and returns `VisualReviewV1` or `VisualReviewBatchV1`.

## MCP tools

- `review_figure(figures_manifest_path, figure_id, ...)` selects one figure
  from a verified `FigureBatchV1`; arbitrary image paths are not accepted.
- `review_figures_all(figures_manifest_path, ...)` reviews every manifest
  entry with bounded bytes, calls, output tokens, and concurrency. Individual
  failures remain in `reviews`; aggregate score is minimum/fail-closed.
- `review_table(request)` reviews a digest-bound image or UTF-8 LaTeX/Markdown
  artifact under a closed `WorkspaceRefV1`.

## Contract

`VisualReviewV1` records target/manifest/context/profile digests, stable figure
ID and revision, issues with severity and optional normalized region, exact
model/provider/revision, sampling, token/cost status, prompt digest, and a raw
response artifact. Invalid JSON/schema is `status=schema-error`; it is never
repaired or converted into an empty success.

Built-in profiles are immutable:

- `figure-publication/v1`
- `figure-domain-integrity/v1`
- `table-publication/v1`

PNG, JPEG, and WebP targets are limited to 20 MiB, 8192 pixels per dimension,
40 million pixels, and 64 KiB metadata. Corrupt, unsupported, oversized,
missing, or digest-mismatched targets return typed failures. Base64 image data
is sent only in the model request and is never returned or written to logs.

## Environment

| Variable | Purpose |
|---|---|
| `ARI_VLM_MODEL` | Explicit LiteLLM visual-review model |
| `ARI_MODEL_VLM_REVISION` | Provider/model revision recorded in reviews |
| `ARI_MODEL_VLM_PROVIDER` | Optional provider identity override |
| `ARI_LLM_API_BASE` / `LLM_API_BASE` | Optional provider endpoint |

The prompts live in `src/prompts/`. Review artifacts are content-addressed
under `.ari-vlm/reviews/` inside the batch/table workspace.

## Verification

```bash
PYTHONPATH=../ari-core pytest -q tests
```
