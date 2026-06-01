# HPC / Container / Subprocess Boundary (requirement 12)

Task-control note from `12_hpc_container_subprocess_boundary.md`. Captured
2026-05-30 from a 3-agent audit (core / viz / skills+scripts) of every
subprocess / SLURM / container / SSH side effect. **Audit/documentation-only**
(§5: document + propose; out of scope: changing HPC/container behavior, `scripts/`,
or expanding `ari.viz.state`). No production code changed.

## 1. The sanctioned execution boundary

- **`ari/container.py`** is the dedicated container exec module and is the
  *correct* boundary: `detect_runtime`, `build_run_cmd`, `run_in_container`
  (Popen + `_sandbox_preexec` = `os.setsid` new process group + optional
  `RLIMIT_NPROC` via `ARI_MAX_CHILD_PROCS`), `_run_with_timeout` (group
  SIGTERM→SIGKILL), `pull_image`, `exec_in_container`. `ari.public.container`
  re-exports it (the req-09 surface). All container launches here are
  **acceptable**.
- **`ari/env_detect.py`** owns scheduler/runtime probes (`sinfo`, `qstat`,
  `docker info`, `lscpu`…) — read-only, best-effort, **infra-sanctioned** (no
  hardcoded cluster knowledge).
- **`ari/mcp/client.py`** spawns skill stdio servers via the MCP SDK
  `stdio_client` — a sanctioned wrapper, not a raw spawn.
- **`ari-skill-hpc/src/slurm.py`** (`SlurmClient`: `_run_local` =
  asyncio subprocess, `_run_remote` = paramiko) is the canonical SLURM
  submit/status/cancel — **acceptable** (that is the skill's job).
- **`scripts/` and `containers/`** — out of scope to change (§3).

## 2. Problematic sites (subprocess in domain logic / route layer, or duplication)

Ranked by the seam value they motivate (all fixes are PROPOSE-ONLY here):

| Site | Issue |
|------|-------|
| `viz/api_memory.py:102,121` (start/stop-local) | Re-derives docker/singularity/apptainer dispatch that `ari.container.detect_runtime` already owns — duplication, drift risk. Route-handler-adjacent (POST /api/memory/start-local/stop-local). **Highest-value / lowest-risk** adopter of a container facet. |
| `ari-skill-paper-re/src/server.py:426,496,795` | Re-implements SLURM submission (`sbatch --wait`, 15+ flags) and container-exec (`apptainer exec --bind/--pwd/--no-home`) that `ari-skill-hpc.SlurmClient` + `ari.public.container` already own — and **already diverges** (paper-re hardcodes `--export ALL`; slurm.py has `ARI_SBATCH_EXPORT_MODE` clean-env logic). The local fallback (`:426`) lacks setsid/killpg, so a hung reproduce can orphan. |
| `ari-skill-orchestrator/src/server.py:324` | Detached child `ari` CLI run via `Popen`, pid returned but not process-group-reaped (no setsid) — orphan risk on recursive sub-runs. |
| `ari/clone/resolvers/gh.py:54`, `ari/publish/backends/gh.py:27` | `git`/`gh` shelled from clone/publish domain logic (each has its own `_run` with cwd) — acceptable-ish (fallback / backend), noted as seam candidates. |
| `ari/viz/state.py:21-29` | Global mutable process-handle store (see §3). |

No site was found that changes scheduler/runtime *behavior* improperly — the
duplication is the risk, not incorrect execution.

## 3. The `ari.viz.state` process-handle coupling (§11 / §12 follow-up)

`ari.viz.state` holds three live OS handles as module globals (imported
everywhere as `_st`):
- **`_last_proc`** (Popen) — most-recent experiment proc. Written by
  `api_experiment._api_launch`/`_api_run_stage`; read for status badges in
  `routes.py`; torn down by `api_process._api_stop` (SIGTERM→SIGKILL via
  `os.killpg(os.getpgid(pid))`).
- **`_running_procs`** (dict checkpoint-path→Popen) — written only in the two
  launch paths; the durable checkpoint→proc map. §7 requires its lifecycle stay
  identical. (Latent gap: `_api_stop` works off `_last_proc`/`.ari_pid`, not this
  dict — a runner could unify.)
- **`_gpu_monitor_proc`** — after **req-05**, all its logic lives in
  `api_process.py` (`_api_gpu_monitor_action`/`_status`/`_api_stop` step 2);
  `server._http_thread` reaps a stale monitor across restarts.

This global-handle coupling is the GLOBAL_RULES "avoid hidden coupling through
global mutable state" item and the explicit req-12 §12 follow-up. **Not touched**
— §11 flags it as the orphan/status/shutdown nexus; high-risk, must be behind
tests and verified on a real node.

## 4. Seam proposals (ALL PROPOSE-ONLY — implementation is a separate requirement)

1. **[HIGH value / LOW risk] `CommandRunner.probe(cmd, timeout) -> stdout|None`**
   — unify the duplicated read-only capability probes (`container._cmd_ok`,
   `env_detect._run`, version/shell probes). ~4 copies, no long-lived procs, no
   signal/cgroup. Must preserve per-call `timeout` + swallow-all (probes must
   never raise into detection).
2. **[HIGH value / LOW risk] Route `viz/api_memory` start/stop-local through a
   container facet that delegates to `ari.container.detect_runtime`** — removes
   the runtime-dispatch duplication; short-lived `run`, no handle/signal logic.
   Best first real adopter.
3. **[HIGH value / MED risk] Unify `paper-re`'s reproduce SLURM/container paths
   onto `ari-skill-hpc.SlurmClient` + `ari.public.container`** — collapses two
   diverging `sbatch`-builders (the `--export ALL` vs clean-env divergence is a
   real latent bug). Must preserve cwd (`--chdir`/`--pwd`), env-export semantics,
   and add the missing setsid/killpg to the local fallback. **Do NOT touch** the
   vendored `_compute` rollout path (it implements the upstream PaperBench
   `ComputerInterface`).
4. **[HIGH value / HIGH risk — do LAST] A managed-process Runner owning the
   handle registry** (`spawn_managed`/`stop_managed`/`run_probe`), replacing
   `_last_proc`/`_running_procs`/`_gpu_monitor_proc` in `ari.viz.state`. Kills the
   global-handle coupling but is the orphan/status/shutdown nexus — only behind
   tests + real-node verification.

§11 hazards any runner MUST preserve (called out for each proposal): **cwd**
(cli_server per-request, gh.py `cwd=repo_dir`, slurm `--chdir`, apptainer
`--pwd`); **env** (stage_runner's allow-list + `~/.env` load; react_driver
PATH-shim injection that MUST happen *pre-fork* because MCP servers snapshot env;
sbatch `--export` mode); **signal/cgroup/orphans** (the `setsid` + process-group
SIGTERM→SIGKILL teardown in `container._sandbox_preexec`, `coding._run_sandboxed`,
`api_process._api_stop` — a naive wrapper that drops `preexec_fn` breaks
group-kill/orphan cleanup); **`start.sh`/`shutdown.sh`/`status`** semantics
(`api_memory` and `_api_stop` mirror the best-effort multi-form teardown
convention).

## 5. Checks

No production code changed (only this note). `pytest ari-core/tests` =
2231 passed / 0 failed; `bash scripts/run_all_tests.sh` = 2843 passed / 0 failed
(unchanged from req 09–11). **Environment caveat (§8/§11):** the real validation —
`./start.sh` / `./start.sh gui` / `./start.sh status` / `./shutdown.sh` and an
actual container/SLURM operation — is **compute-node-gated** and was NOT run on
this login node. Per §8 ("do not treat green unit tests on a login/fake node as
completion"), this requirement makes **no code change**, so the green unit tests
are sufficient evidence for *this* (documentation) deliverable; any future seam
implementation MUST be verified on a real compute node before merge.

## 6. Follow-up candidates (→ §12)

- Implement seam #2 (`api_memory` → container facet) — smallest real win.
- Implement seam #3 (paper-re reproduce → `SlurmClient`/`ari.public.container`) —
  fixes the `--export` divergence; a dedicated requirement with real-node verify.
- Implement seam #1 (`CommandRunner.probe`) — cosmetic dedup.
- Move process-handle management out of `ari.viz.state` (seam #4) — the §12
  headline follow-up; highest risk, real-node verification mandatory; coordinates
  with the req-07 active-checkpoint-global follow-up.
- Add setsid/killpg to `paper-re` local reproduce + `orchestrator` detached child
  (orphan-reaping fix) — behavior change, needs its own justification + test.
