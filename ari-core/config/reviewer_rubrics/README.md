# ari-core/config/reviewer_rubrics

Reviewer rubric definitions, one YAML file per venue/journal (e.g. `iclr.yaml`, `neurips.yaml`, `nature.yaml`).

Each file declares fields like `id`, `version`, `venue`, `domain`, and review `params`.

## Contents

- `README.md` — this file.
- `acl.yaml` — ACL reviewer rubric.
- `aer.yaml` — AER reviewer rubric.
- `ahr.yaml` — AHR reviewer rubric.
- `apsr.yaml` — APSR reviewer rubric.
- `chi.yaml` — CHI reviewer rubric.
- `cvpr.yaml` — CVPR reviewer rubric.
- `econometrica.yaml` — Econometrica reviewer rubric.
- `generic_conference.yaml` — generic conference reviewer rubric.
- `iclr.yaml` — ICLR reviewer rubric.
- `icml.yaml` — ICML reviewer rubric.
- `icra.yaml` — ICRA reviewer rubric.
- `journal_generic.yaml` — generic journal reviewer rubric.
- `nature.yaml` — Nature reviewer rubric.
- `neurips.yaml` — NeurIPS reviewer rubric.
- `osdi.yaml` — OSDI reviewer rubric.
- `philreview.yaml` — Philosophical Review reviewer rubric.
- `pmla.yaml` — PMLA reviewer rubric.
- `qje.yaml` — QJE reviewer rubric.
- `sc.yaml` — SC reviewer rubric.
- `siggraph.yaml` — SIGGRAPH reviewer rubric.
- `stoc.yaml` — STOC reviewer rubric.
- `usenix_security.yaml` — USENIX Security reviewer rubric.
- `workshop.yaml` — generic workshop reviewer rubric.
- `fewshot_examples/` — few-shot review examples referenced by the rubrics.
  - `README.md` — fewshot_examples index.
  - `neurips/` — Few-shot review examples used when the `neurips` / `iclr` / `icml` rubric has
