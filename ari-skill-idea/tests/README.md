# ari-skill-idea/tests

Pytest suite for the idea skill (survey + idea generation).

## Contents

- `README.md` — this file.
- `test_server.py` — exercises `survey`, `make_metric_spec`, `generate_ideas`.
- `test_virsci.py` — covers the vendored VirSci discussion-flow integration.
- `test_virsci_live.py` — covers the VirSci-live (vendor-wrap) path: `ARI_IDEA_VIRSCI_*` env contract, auto-stubber import, `build_snapshot` (mocked S2), `LivePlatform.reference_paper`, `build_model_configs`, `_parse_idea`, and the `generate_ideas` real-path contract + degrade-to-reimpl fallback.
