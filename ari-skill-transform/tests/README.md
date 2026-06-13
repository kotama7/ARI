# ari-skill-transform/tests

Pytest suite for the transform skill (tree-walk + EAR lifecycle).

## Contents

- `README.md` — this file.
- `conftest.py` — shared fixtures.
- `test_claims.py` — unit-tests the deterministic claim layer (`build_science_claims`, `recompute`, `FORMULAS`, metric resolution/autodetect), covering formula semantics, operand provenance, and comparison-scope cross-env gating.
- `test_metric_contract_seam.py` — covers the `make_metric_spec`→`_load_run_metric_contract`→`nodes_to_science_data` seam that carries the persisted `metric_contract.json` onto `science_data` and into the hard gate (`check_contract` flags `claim_evidence_missing`).
- `test_server.py` — exercises `nodes_to_science_data` (config extraction, JSON parsing via `_robust_extract_json`, typed param/measurement split, `_default_llm_model` backend-aware selection); does not test the EAR curate/publish/promote tools.
