# ari-skill-paper-re/src

MCP server package for the paper-re skill — PaperBench-format reproducibility
evaluation: Phase 1 sandbox execution of `reproduce.sh`, Phase 2 grading via
PaperBench `SimpleJudge`. No top-level `__init__.py`; `server.py` is the entry point.

## Contents

- `README.md` — this file.
- `_litellm_completer.py` — provider-neutral LiteLLM `TurnCompleter`.
- `_paperbench_bridge.py` — `SimpleJudge` bridge.
- `_replicator_agent.py` — drives PaperBench's BasicAgent/IterativeAgent solver.
- `_vendor_path.py` — injects vendored PaperBench onto `sys.path`.
- `server.py` — exposes `run_reproduce`, `grade_with_simplejudge`, `fetch_code_bundle`, `build_reproduce_sh`.
- `_compute/` — `ComputerInterface` implementations (local / Apptainer).
  - `README.md` — _compute index.
  - `__init__.py` — public surface (`LocalComputer`, `ApptainerComputer`, `make_computer`); module docstring is authoritative.
  - `computer.py` — the computer implementations.
  - `local_pbtask.py` — local PaperBench task wiring.
- `prompts/` — replicator prompt + MPI aggregation skeleton.
  - `README.md` — prompts index.
  - `mpi_aggregate_skel.py` — not a prompt: an MPI result-aggregation source skeleton auto-injected into `reproduce.sh` when the rubric's `execution_profile.kind` is `mpi` / `mpi_gpu`.
  - `replicator.md` — prompt template for the replicator agent (writes `reproduce.sh` + sources); single-brace `{name}` placeholders filled via Python `str.format`.

## See also

- The skill root `README.md` and the `server.py` module docstring for the tools, phases & removed legacy tools.
