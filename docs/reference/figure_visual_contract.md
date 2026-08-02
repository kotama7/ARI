# Scientific figure and visual-review contract

ARI separates figure construction from visual judgement. `ari-skill-plot` is
the only owner of rendered figure bytes; `ari-skill-vlm` reads immutable
artifacts and reports findings without rewriting them. Stable Python imports
are exposed by `ari.public.figures` and `ari.public.visual_review`.

## Figure identity

`FigureSpecV1` is declarative. It binds the exact finite data slice and source
artifact digest to fields, units, scales, aggregation, uncertainty, caption,
and a fixed style profile. It accepts no Python, SVG, shell, path, or embedded
image payload. A model may propose admitted fields only; the fixed renderer
owns all numeric values and output bytes.

`FigureManifestV1` binds the specification to source-data/spec/PNG/PDF
artifacts and a `FigureEnvironmentV1` containing renderer, Python,
Matplotlib/backend, platform, font bytes, and optional container identity.
LLM-planned figures additionally retain the exact prompt and raw response.
`FigureBatchV1` requires every ID/path/LaTeX/kind map to match its manifests.

Rendering uses a closed workspace, a fixed `Agg` backend, bounded dimensions
and rows, and atomic writes. Legacy schema-less manifests are accepted only by
the explicit offline reader; new producers emit v1.

## Feedback lineage

`FigureFeedbackV1` binds one review digest to exactly one parent manifest and
one next revision. Revisions are capped at two, retain previous artifacts, and
cannot cross figure IDs. Re-rendering always creates a new manifest and batch
digest rather than overwriting scientific evidence in place.

## Visual review

Each `VisualReviewV1` binds:

- the exact target artifact bytes, figure/manifest identity, and context digest;
- a versioned criteria-profile ID and digest;
- structured issues with severity, evidence, suggestion, and optional region;
- provider/model/revision, prompt digest, sampling, token/cost status, and the
  content-addressed raw model response;
- either `completed` with a bounded score or an explicit typed artifact,
  limit, model, or schema error.

The server rereads target bytes and checks size/digest before a model call.
Unsupported, corrupt, oversized, missing, or changed artifacts are failures,
not empty successful reviews. Model JSON is validated strictly; malformed
responses become `schema-error` and preserve their raw bytes.

`VisualReviewBatchV1` uses `minimum-fail-closed`: every target remains present,
any failed target makes the batch score zero, and otherwise the score is the
minimum individual score. A publication consumer must compare that score with
the explicit `VisualCriteriaProfileV1.passing_score`; `PaperBuildV1` records
both the observed and required scores.

## Removed paths and rollback

The runtime no longer executes generated plotting code, infers raster siblings
from filenames, accepts inline base64 targets, treats invalid model output as a
successful review, or normalizes VLM results ad hoc in the paper Skill. The
benchmark plotting duplicate was replaced by the canonical renderer. Published
v1 contracts and the isolated legacy manifest reader remain available for
replay; removed producer paths are recoverable by reverting the pre-migration
component commits, not by silently enabling a compatibility fallback.

## Verification

```bash
PYTHONPATH=ari-core pytest -q ari-skill-plot/tests ari-skill-vlm/tests
python scripts/sync_skill_metadata.py
python scripts/snapshot_contracts.py --surface public --check
python scripts/snapshot_contracts.py --surface mcp --check
```
