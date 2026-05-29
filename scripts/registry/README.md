# scripts/registry

Deployment helpers for the ari-registry service (nginx ↔ uvicorn ↔ sqlite).

## Contents

- `README.md` — this file.
- `docker-compose.yml` — production stack (nginx + uvicorn + sqlite file volume).
- `start_local.sh` — uvicorn + sqlite single-process, for laptop/dev.
- `start_singularity.sh` — HPC fallback running the registry inside an Apptainer SIF.
