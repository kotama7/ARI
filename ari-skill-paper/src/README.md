# ari-skill-paper/src

- `server.py` — narrow MCP transport and workflow-facing composition.
- `authoring.py` — native evidence loading, prompt/raw artifacts, revisions, and draft builds.
- `compiler.py` — fixed-command, shell-free, resource-bounded LaTeX compilation.
- `claim_links.py` — ScienceData/FigureBatch binding over `ari.public.latex_claims`.
- `review_engine.py` — explicit-rubric independent text review.
- `finalize.py` — fail-closed recomputation and `PaperBuildV1` final lock.
- `rubric.py` — versioned rubric loader.
- `rubric_migration.py` — offline conversion of old env/default rubric selection.
- `prompts/` — the three supported whole-document prompt templates.

Per-section author/reviewer APIs and the model-based figure inserter are not
runtime components.
