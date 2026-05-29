# ari-skill-paper-re/src/prompts

Replicator-agent prompt plus an auto-injected source skeleton.

## Contents

- `README.md` — this file.
- `mpi_aggregate_skel.py` — not a prompt: an MPI result-aggregation source skeleton auto-injected into `reproduce.sh` when the rubric's `execution_profile.kind` is `mpi` / `mpi_gpu`.
- `replicator.md` — prompt template for the replicator agent (writes `reproduce.sh` + sources); single-brace `{name}` placeholders filled via Python `str.format`.
