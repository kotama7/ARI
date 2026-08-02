# ari-skill-hpc/tests

Pytest suite for the HPC skill (SLURM + Singularity).

## Contents

- `test_execution_adapter.py` — common execution identity/input/environment
  handoff to SLURM, explicit unmapped-policy provenance, and pinned container
  parity.

- `README.md` — this file.
- `conftest.py` — shared fixtures.
- `test_contracts.py` — strict validation, stable digests, and public JSON Schema.
- `test_capability_probe.py` — deterministic platform-capability probe: `_parse_capability_output` parsing, `probe_platform_capabilities` cache short-circuit, and graceful skip paths (no partition / `srun` absent).
- `test_singularity.py` — digest-pinned build/run aliases and injection negatives.
- `test_slurm_local.py` — submit/idempotency/status/result/cancel/clean-env conformance.
- `test_slurm_remote.py` — strict host-key and explicit-credential SSH transport.
- `test_server.py` — runtime tool/schema and canonical MCP round-trip conformance.
