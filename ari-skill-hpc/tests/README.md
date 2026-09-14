# ari-skill-hpc/tests

Pytest suite for the HPC skill (SLURM + Singularity).

## Contents

- `README.md` — this file.
- `conftest.py` — shared fixtures.
- `test_allowed_nodes.py` — environment-configured node-confinement policy (hostlist expansion, fail-closed refusals that do not name nodes) plus the allocation shape and the `launcher` mode (`auto` / `srun` / `none`), both of which change the request digest.
- `test_capability_probe.py` — deterministic platform-capability probe: `_parse_capability_output` parsing, `probe_platform_capabilities` cache short-circuit, and graceful skip paths (no partition / `srun` absent).
- `test_contracts.py` — strict validation, stable digests, and public JSON Schema.
- `test_execution_adapter.py` — common execution identity/input/environment
- `test_server.py` — runtime tool/schema and canonical MCP round-trip conformance.
- `test_slurm_local.py` — submit/idempotency/status/result/cancel/clean-env conformance.
- `test_slurm_remote.py` — strict host-key and explicit-credential SSH transport.
- `test_submit_work_dir.py` — a submitted job must run where the evaluator reads, or fail saying so. The regression: `slurm_submit` accepted the virtual container root `/workspace`, passed it straight through, and the job ran in the submitting process's cwd — so every node wrote into the repository root and was then scored on the untouched seed it had inherited.
