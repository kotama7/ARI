# Requirement: HPC / Container / Subprocess Boundary

## 1. Purpose

- Audit subprocess, SLURM, Docker, Singularity, Apptainer, SSH, filesystem, and
  remote execution side effects.
- Isolate infrastructure operations behind explicit boundaries.
- Preserve existing HPC/container behavior.

## 2. Current Problem

Execution side effects (subprocess, SLURM, container runtimes, SSH) may be
invoked directly from domain logic and route handlers rather than behind an
execution boundary. `ari.viz.state` even holds live process handles
(`_running_procs`, `_last_proc`, `_gpu_monitor_proc`), tying subprocess
lifecycle to global mutable state.

## 3. Scope

### In Scope

- Documenting current execution side effects and where they originate.
- Identifying subprocess/container/SLURM/SSH calls embedded in domain logic.
- Proposing execution-backend interfaces or wrappers.

### Out of Scope

- Changing HPC/container behavior or scheduler interaction.
- Changing scripts under `scripts/` or `containers/`.
- Expanding `ari.viz.state` process handling.

## 4. Files to Inspect First

```text
ari-core/ari/container.py
ari-core/ari/env_detect.py
ari-core/ari/agent/react_driver.py
ari-core/ari/viz/api_tools.py
ari-core/ari/viz/api_ollama.py
ari-skill-hpc/src/
ari-skill-coding/src/
scripts/run_ollama_gpu.sh
scripts/build_pb_images.sh
scripts/registry/
scripts/letta/
containers/
```

Confirmed: `ari.public.container` is the intended stable container surface
(backed by `ari/container.py`). The R-CCS environment uses Tcl Env Modules
(two-stage, `module` only) — environment detection (`env_detect.py`) and any
module/SLURM interaction is environment-sensitive and must be verified on a
real compute node, not a login/fake node.

## 5. Expected Changes

- Document current execution side effects.
- Identify subprocess calls in domain logic.
- Propose execution-backend interfaces or wrappers.
- Preserve existing scripts and HPC behavior.

## 6. Step-by-Step Execution Plan

1. Grep core, viz, and skills for `subprocess`, `Popen`, `os.system`, `ssh`,
   `srun`/`sbatch`, `docker`/`singularity`/`apptainer`.
2. For each, record: caller layer, what it executes, and whether it goes
   through `ari.container` / a wrapper or is raw.
3. Classify: acceptable (inside `container.py` / a dedicated execution module /
   a script) vs. problematic (subprocess inside a route handler or domain
   logic — see prohibited edges in `GLOBAL_RULES.md`).
4. Propose an execution-backend interface (e.g. a runner abstraction) that the
   problematic call sites could use, without changing behavior yet.
5. Run section 8 checks.

## 7. Compatibility Requirements

- HPC/SLURM/container/SSH behavior is identical for the same inputs and
  environment.
- `scripts/` and `containers/` are unchanged.
- Process-handle lifecycle (start/stop via `start.sh` / `shutdown.sh`,
  `_running_procs`) behaves the same.

## 8. Tests and Smoke Checks

```bash
pytest ari-core/tests -q
bash scripts/run_all_tests.sh
```

Plus, on a **real compute node**: confirm `./start.sh`, `./start.sh gui`,
`./start.sh status`, and `./shutdown.sh` behave as before, and that an actual
container/HPC operation still runs. Do not treat green unit tests on a login/
fake node as completion. Document unavailable dependencies.

## 9. Completion Criteria

The requirement is complete only when:

- all scoped changes are implemented
- existing behavior is preserved
- tests or smoke checks pass
- risks are documented
- follow-up work is moved to another requirement file
- completion is recorded in `refactoring/COMPLETED.md`
- this requirement file is deleted in the same PR

## 10. Deletion Rule

This file must remain in `refactoring/requirements/` while the requirement is
incomplete.

When all completion criteria are satisfied, record the completion in
`refactoring/COMPLETED.md`, then delete this file in the same PR.

Do not delete this file for partial completion.

## 11. Risks

- Execution side effects are the hardest to test and the most environment-
  dependent; a wrapper can change cwd, env, or signal handling subtly.
- Global process handles in `ari.viz.state` couple subprocess lifecycle to the
  server; touching this risks orphaned processes or broken `status`/`shutdown`.

## 12. Follow-up Candidates

- Implementing the proposed execution-backend interface (separate requirement).
- Moving process-handle management out of `ari.viz.state`.
