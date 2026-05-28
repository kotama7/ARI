# ari-skill-paper-re/tests

Pytest suite for the paper-re skill (PaperBench-format reproducibility).

## Contents

- `README.md` — this file.
- `test_compute_interface.py` — `_compute` `ComputerInterface` implementations.
- `test_fetch_code_bundle.py` — `fetch_code_bundle`.
- `test_litellm_basicagent_completer.py` — LiteLLM completer against BasicAgent.
- `test_litellm_completer.py` — LiteLLM `TurnCompleter`.
- `test_local_pbtask.py` — local PaperBench task wiring.
- `test_mpi_aggregate_skel.py` — MPI aggregation skeleton injection.
- `test_paperbench_bridge.py` — `SimpleJudge` bridge.
- `test_paperbench_bridge_upstream.py` — `SimpleJudge` bridge against the vendored upstream.
- `test_replicator_agent.py` — replicator agent driver.
- `test_run_reproduce_and_grade.py` — Phase 1 sandbox run + Phase 2 grading.
- `test_run_reproduce_slurm.py` — Phase 1 Slurm run + Phase 2 grading.
