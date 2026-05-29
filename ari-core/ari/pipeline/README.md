# ari.pipeline

Generic workflow execution engine driven entirely by `workflow.yaml` (no
hardcoded tool names). Adding a skill or stage is a YAML change, not a
code change. Public surface (`run_pipeline`, `load_workflow`, …) is
re-exported from the package root.

## Contents

- `README.md` — this file.
- `__init__.py` — sub-module map + public re-exports.
- `context_builder.py` — best-nodes context + keyword extraction.
- `experiment_md.py` — `experiment.md` helpers.
- `orchestrator.py` — top-level entry points (`build_scientific_data`, `run_pipeline`).
- `stage_control.py` — loop_back / VLM-feedback control.
- `stage_runner.py` — stage execution helpers (retry, ReAct, subprocess).
- `yaml_loader.py` — workflow/pipeline loaders + `{{var}}` resolution.

## See also

- **Sub-module map & re-exports** → the `__init__.py` module docstring (authoritative).
- **Workflow file & stages** → `docs/concepts/architecture.md`, `docs/guides/experiment_file.md`.
- **Split history** → `git log -- ari-core/ari/pipeline/`.
