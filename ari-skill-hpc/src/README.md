# ari-skill-hpc/src

MCP server package for typed SLURM and digest-pinned container jobs, in local
or strict SSH remote-cluster mode.
`__init__.py` is empty; the package is imported as `src`.

## Contents

- `README.md` — this file.
- `__init__.py` — empty package marker.
- `contracts.py` — immutable v1 job, handle, status, result, artifact, resource,
  environment, and container models.
- `scheduler.py` — shell-free local transport, strict SSH transport, durable
  idempotency ledger, SLURM backend, result and provenance collection.
- `server.py` — canonical MCP lifecycle plus deprecated compatibility aliases.
- `singularity.py` — compatibility aliases compiled into typed scheduler jobs.
- `slurm.py` — legacy client facade and bounded platform capability probe.

## See also

- The skill root `README.md` and the `server.py` module docstring for the tools & outward interface.
