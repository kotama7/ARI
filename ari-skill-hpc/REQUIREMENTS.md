# ari-skill-hpc requirements

## Required behavior

1. A submit operation accepts a strict `JobRequestV1`, returns `JobHandleV1`
   after scheduler acceptance, and never waits for the compute job to finish.
2. The request digest binds command argv, resource request, clean environment,
   module list, container/image/binds, input pins, output declarations, and
   scientific metadata.
3. A durable claim is committed before the external submit. Identical committed
   requests return the existing handle; uncertain claims fail closed rather
   than submitting twice.
4. Status, result, logs, and cancellation use one validated handle/SLURM-ID
   parser and one provider-neutral state map.
5. Terminal results revalidate every input and collect only declared regular,
   non-symlink outputs within the workspace. Logs and provenance are bounded and
   SHA-256 bound.
6. Scheduler transport accepts argv and optional stdin, not shell command
   strings. Batch content may execute a caller-authorized workload only after
   allocation on the compute node.
7. The generated job environment uses SLURM `NIL`, a fixed PATH and locale,
   explicit non-secret variables, and explicit modules. Parent environment,
   credential files, shell rc files, virtualenv paths, and Python path state are
   not inherited.
8. SSH mode requires a reviewed known-hosts file and explicit credential scope;
   unknown/mismatched host keys, implicit user keys, and SSH agents are rejected.
9. Container jobs verify image digest and size, declare every bind mode and GPU
   request, and run with a clean contained environment.
10. Local, remote, A64FX-like, GPU, no-SLURM, cancellation, timeout, input drift,
    and shared-filesystem behavior must be covered by deterministic fixtures.

## Compatibility and deletion

- `slurm_submit` is an opaque compute-node batch-body adapter. Generated
  directives occur before its body, so caller `#SBATCH` lines cannot override
  the reviewed scheduler policy.
- `singularity_build`, `singularity_build_fakeroot`, `singularity_pull`,
  `singularity_run`, and `singularity_run_gpu` compile into canonical typed job
  requests.
- These aliases remain only through the documented deprecation release. Remove
  them when workflow/tool caller count is zero and container parity fixtures
  pass. Restore from the pre-deletion commit if rollback is required.
- `run_bash`, parent-environment export, `.env` sourcing, automatic SSH host-key
  acceptance, shell-based scheduler commands, and predictable remote temporary
  scripts are prohibited and have no compatibility path.

## Verification commands

```bash
pytest -q
ruff check src tests scripts
python scripts/sync_contracts.py
python ../scripts/check_skill_manifests.py
```
