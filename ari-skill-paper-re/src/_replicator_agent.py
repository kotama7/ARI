"""Agent-mode Replicator: drive PaperBench's BasicAgent / IterativeAgent
solver against ari's checkpoint workspace.

v0.7.2 additions (PLAN_MPI_EXIT):

* ``run_replicator_agent`` accepts an ``execution_profile`` dict (rubric's
  ``reproduce_contract.execution_profile``) and forwards it via
  :class:`LocalPBTask` so the agent's user message gets the EXECUTION
  PROFILE / CLUSTER SHAPE / COMPUTE-NODE EXECUTION CONVENTIONS blocks
  (mirroring ``prompts/replicator.md``).
* Cluster shape is captured at call-site from SLURM env vars
  (``SLURM_JOB_NUM_NODES``, ``SLURM_NTASKS``) plus a best-effort GPU list
  via ``nvidia-smi``.
* The MPI aggregation skeleton (``prompts/mpi_aggregate_skel.py``) is
  auto-copied into ``submission/`` when ``execution_profile.kind`` ∈
  {``"mpi"``, ``"mpi_gpu"``}.

This is the v0.7+ replacement for the v0.6 single-shot Replicator
(``_replicator.py``). The single-shot version is *deleted* — see release
notes; if you want it back, ``git revert`` the deletion commit. Agent mode
is now the only path through ``ors_build_reproduce``.

Key differences from a vanilla ``BasicAgentSolver`` invocation:

1. Runs against :class:`LocalComputer` / :class:`ApptainerComputer` —
   ari's HPC sandbox stack — not alcatraz / Docker.

2. ``sanity_check_docker`` is bypassed (the upstream helper assumes
   Docker is present *inside* the agent's container; the PaperBench paper
   itself does not require DinD — see paper §2.2).

3. Instructions / system message are constructed inline instead of read
   from upstream's ICML-replication-specific instruction templates. The
   template references the workspace root (relative paths) instead of
   ``/home/submission`` so the agent operates in ari's
   ``repro_sandbox/`` layout without needing a fake chroot.

4. After the agent finishes (submit / time-limit), the workspace is
   inspected: if ``reproduce.sh`` ended up under ``submission/``, it is
   promoted to the workspace root so ari's downstream
   ``ors_run_reproduce`` finds it where it expects.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import _vendor_path  # noqa: F401

import chz

from nanoeval.solvers.computer_tasks.code_execution_interface import ComputerInterface
import paperbench.solvers.utils as _pb_solver_utils
from paperbench.nano.structs import AgentOutput
from paperbench.nano.task import PBTask
from paperbench.solvers.basicagent.solver import BasicAgentSolver
from paperbench.solvers.basicagent.completer import (
    BasicAgentTurnCompleterConfig,
    OpenAIResponsesTurnCompleterConfig,
)
from paperbench.solvers.basicagent.utils import (
    get_instructions as _vendor_get_instructions,
)
from paperbench.solvers.basicagent.prompts.templates import (
    get_system_message as _vendor_get_system_message,
)
from paperbench.solvers.utils import check_for_existing_run

from _compute import LocalComputer, ApptainerComputer, make_computer
from _compute.local_pbtask import LocalPBTask, make_local_pbtask

log = logging.getLogger(__name__)


# ─── cluster shape + HPC prompt appendix ─────────────────────────────────


def _detect_gpu_list() -> str:
    """Best-effort GPU enumeration for the prompt's CLUSTER SHAPE block.

    Returns a comma-joined string of GPU model names (e.g.
    "Tesla V100-SXM2-16GB ×4") or "none visible" when nvidia-smi is absent
    or reports no devices. Never raises — this is purely informational.
    """
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return "none visible"
    if r.returncode != 0:
        return "none visible"
    names = [n.strip() for n in (r.stdout or "").splitlines() if n.strip()]
    if not names:
        return "none visible"
    counts: dict[str, int] = {}
    for n in names:
        counts[n] = counts.get(n, 0) + 1
    return ", ".join(f"{name} ×{c}" for name, c in counts.items())


def detect_cluster_shape() -> dict[str, str]:
    """Snapshot the current allocation's shape from SLURM env + nvidia-smi.

    Used by ``run_replicator_agent`` to seed the agent's CLUSTER SHAPE
    prompt block. Outside SLURM, both rank/node counts fall back to "1"
    (the legacy single-node behaviour).
    """
    return {
        "SLURM_JOB_NUM_NODES": os.environ.get("SLURM_JOB_NUM_NODES", "1"),
        "SLURM_NTASKS": os.environ.get("SLURM_NTASKS", "1"),
        "GPU_LIST": _detect_gpu_list(),
    }


_MPI_KINDS = ("mpi", "mpi_gpu")


def _format_hpc_appendix(
    *,
    expected_artifacts: list[str],
    execution_profile: dict,
    cluster_shape: dict,
) -> str:
    """Build the ari-side prompt appendix appended to the vendor instructions.

    Domain isolation: HPC-specific content (CLUSTER SHAPE, MPI / srun /
    sbatch / multi-node fan-out conventions) is emitted ONLY when the
    rubric's ``execution_profile`` is non-empty (the explicit HPC opt-in
    signal). When only ``expected_artifacts`` is present (legacy non-HPC
    paper), the appendix degrades to the same EXPECTED_ARTIFACTS-only
    block emitted by v0.7.1 — byte-identical agent prompts for non-HPC
    papers.

    Returns an empty string when none of the three inputs has content,
    preserving the pre-v0.7.2 zero-overhead behaviour.
    """
    has_artifacts = bool(expected_artifacts)
    has_profile = bool(execution_profile)
    # ``has_shape`` only counts as a signal when execution_profile is also
    # set. A non-HPC paper running inside an unrelated SLURM allocation
    # should NOT pull in CLUSTER SHAPE / COMPUTE-NODE conventions just
    # because $SLURM_NTASKS happens to be set.
    has_shape = has_profile and any(
        cluster_shape.get(k) and cluster_shape.get(k) not in ("1", "none visible", "")
        for k in ("SLURM_JOB_NUM_NODES", "SLURM_NTASKS", "GPU_LIST")
    )
    if not (has_artifacts or has_profile):
        return ""

    parts: list[str] = []

    if has_artifacts:
        parts.append(
            "EXPECTED_ARTIFACTS (rubric-driven; ``reproduce.sh`` MUST produce "
            "these at the workspace root):\n"
            + "\n".join(f"  - {a}" for a in expected_artifacts)
        )

    # Below this point: HPC-specific blocks. Gated on ``has_profile`` so
    # they never leak into non-HPC paper runs.
    if not has_profile:
        return "\n\n" + "\n\n".join(parts)

    parts.append(
        "EXECUTION PROFILE (from the rubric):\n"
        + json.dumps(execution_profile, indent=2, ensure_ascii=False)
    )

    if has_shape:
        parts.append(
            "CLUSTER SHAPE (current allocation):\n"
            f"  - SLURM_JOB_NUM_NODES = {cluster_shape.get('SLURM_JOB_NUM_NODES', '1')}\n"
            f"  - SLURM_NTASKS        = {cluster_shape.get('SLURM_NTASKS', '1')}\n"
            f"  - GPU devices visible = {cluster_shape.get('GPU_LIST', 'none visible')}"
        )

    kind = (execution_profile or {}).get("kind", "")
    conventions: list[str] = []
    if kind in _MPI_KINDS:
        metric_cols = (execution_profile or {}).get("metric_columns") or []
        cols_repr = (
            ", ".join(repr(c) for c in metric_cols) if metric_cols else "<rubric.metric_columns>"
        )
        conventions.append(
            "  - reproduce.sh MUST launch via ``srun -n $SLURM_NTASKS`` or\n"
            "    ``mpirun -np $SLURM_NTASKS``. Rank 0 collects metrics via\n"
            "    MPI_Reduce/Gather (or mpi4py ``comm.gather``) and writes\n"
            "    ``submission/results/<file>.csv`` with header EXACTLY:\n"
            f"        [{cols_repr}]\n"
            "    A helper skeleton (``submission/mpi_aggregate.py``) has\n"
            "    been auto-injected — copy it into your CSV-emit step."
        )
    if kind in ("gpu_single", "gpu_multi") or kind in _MPI_KINDS:
        conventions.append(
            "  - kind is GPU-bearing: reproduce.sh MUST use CUDA (nvcc) OR\n"
            "    PyTorch CUDA / cupy. Do NOT fall back to NumPy unless\n"
            "    EXECUTION_PROFILE is empty."
        )
    if (execution_profile or {}).get("accepts_reduced_scale"):
        conventions.append(
            "  - accepts_reduced_scale=true: if you cannot reach\n"
            "    paper_max_ranks/nodes in this allocation, run as many\n"
            "    scale points as fit and add a ``paper_paper_scale_point``\n"
            "    boolean column to the CSV (false for reduced points)."
        )
    module_loads = (execution_profile or {}).get("module_loads") or []
    if module_loads:
        conventions.append(
            "  - module_loads is non-empty. PREPEND to reproduce.sh:\n"
            f"        module load {' '.join(module_loads)}"
        )
    if conventions:
        parts.append("CONVENTIONS:\n" + "\n".join(conventions))

    # COMPUTE-NODE conventions are HPC-flavoured; only emit when the
    # rubric explicitly opted into the HPC pathway via execution_profile.
    parts.append(
        "COMPUTE-NODE EXECUTION CONVENTIONS:\n"
        "  Shared filesystem:\n"
        "    - All paths in reproduce.sh must resolve on EVERY allocated node.\n"
        "    - $HOME-based or /work/-based paths only. NEVER /tmp or /var/tmp.\n"
        "  MPI invocation (PREFER srun over mpirun):\n"
        "    - ``srun -n $SLURM_NTASKS <cmd>`` uses SLURM's PMI/PMIx and works\n"
        "      without a separately-installed OpenMPI/MPICH.\n"
        "    - Test ``which mpirun`` before assuming it is on PATH.\n"
        "  Python env:\n"
        "    - bash shebang does NOT activate conda. Prepend\n"
        "      ``source ~/.bashrc`` or\n"
        "      ``source ~/miniconda3/etc/profile.d/conda.sh && conda activate <env>``\n"
        "      when needed.\n"
        "  Multi-node fan-out:\n"
        "    - reproduce.sh starts as 1 rank. Use\n"
        "      ``srun -N $SLURM_JOB_NUM_NODES -n $SLURM_NTASKS <cmd>``\n"
        "      to spread across all allocated nodes.\n"
        "  Timeout wrapping:\n"
        "    - Wrap long stages with ``timeout 1800 <cmd>`` so one slow step\n"
        "      does not eat the whole SLURM walltime."
    )

    return "\n\n" + "\n\n".join(parts)


# ─── docker sanity bypass ─────────────────────────────────────────────────


@contextlib.asynccontextmanager
async def _bypass_docker_sanity_check():
    """Temporarily neuter the upstream helpers that assume an alcatraz-style
    container (``/home/submission``, ``/home/logs`` directories, host
    Docker socket, blob-storage tarball uploads).

    Replaced helpers — all reverted on context exit:

    * :func:`paperbench.solvers.utils.sanity_check_docker` — runs
      ``docker --version`` / ``docker run hello-world`` *inside* the agent's
      container. ari's :class:`LocalComputer` is on the host (no Docker
      socket exposed) and the PaperBench paper §2.2 does not actually
      require Docker-in-Docker.

    * :func:`paperbench.solvers.upload.upload_heavy_logs` and
      :func:`paperbench.solvers.utils.optionally_upload_heavy_logs` — call
      ``upload_sources`` which tries to ``cp -rp /home/submission /tmp/...``
      on the agent's filesystem. Under :class:`LocalComputer` that is the
      host filesystem; running it would either fail (no write perm to
      ``/home``) or pollute the host's actual ``/home/submission``. ari's
      reproduce.sh + sources end up in the workspace directly via the
      agent's tools, so the alcatraz-style tarball upload is redundant.

    All three replacements log INFO once on activation so production runs
    leave a breadcrumb if someone later wonders why no
    ``submission-<ts>.tar.gz`` artifacts appeared.
    """
    import paperbench.solvers.upload as _pb_upload
    import paperbench.solvers.basicagent.utils as _pb_ba_utils
    # solver.py captures these names at module load via ``from X import Y``,
    # so the local references inside ``_run_agent_loop`` /
    # ``_execute_agent_and_periodically_upload_logs`` survive a patch on
    # the source modules. Patch the solver module's namespace too —
    # otherwise post-rollout `upload_heavy_logs(...)` runs the upstream
    # version which calls ``mkdir -p /home/submission`` on the host fs.
    import paperbench.solvers.basicagent.solver as _pb_ba_solver

    orig_sanity = _pb_solver_utils.sanity_check_docker
    orig_heavy = _pb_upload.upload_heavy_logs
    orig_optional = _pb_ba_utils.optionally_upload_heavy_logs
    orig_solver_sanity = getattr(_pb_ba_solver, "sanity_check_docker", None)
    orig_solver_heavy = getattr(_pb_ba_solver, "upload_heavy_logs", None)
    orig_solver_optional = getattr(_pb_ba_solver, "optionally_upload_heavy_logs", None)

    async def _noop_sanity(computer: ComputerInterface) -> None:
        log.info("sanity_check_docker bypassed (HPC substrate; no DinD needed)")

    async def _noop_upload(*args, **kwargs) -> None:
        # Returning None matches upstream signature; the ContextLogger info
        # log is safe to emit silently per call.
        pass

    async def _noop_optional(*args, **kwargs):
        # ``optionally_upload_heavy_logs`` returns a small dataclass; mirror
        # its shape lazily by importing only on first call.
        from paperbench.solvers.basicagent.utils import _OptionalUploadOutcome  # type: ignore[attr-defined]
        return _OptionalUploadOutcome(last_time_uploaded=0.0, upload_task=None)

    # Some upstream versions name the dataclass differently or inline it.
    # Probe and fall back to a duck-typed namedtuple if the import fails.
    try:
        from paperbench.solvers.basicagent.utils import _OptionalUploadOutcome  # noqa: F401
    except Exception:
        from collections import namedtuple
        _Outcome = namedtuple("_OptUpOutcome", ["last_time_uploaded", "upload_task"])

        async def _noop_optional(*args, **kwargs):  # type: ignore[no-redef]
            return _Outcome(last_time_uploaded=0.0, upload_task=None)

    _pb_solver_utils.sanity_check_docker = _noop_sanity  # type: ignore[assignment]
    _pb_upload.upload_heavy_logs = _noop_upload  # type: ignore[assignment]
    _pb_ba_utils.optionally_upload_heavy_logs = _noop_optional  # type: ignore[assignment]
    # Same patch on the solver module's local names (early-bound via
    # ``from X import Y``); without these the post-rollout
    # ``upload_heavy_logs(...)`` call in solver.py still hits upstream.
    _pb_ba_solver.sanity_check_docker = _noop_sanity  # type: ignore[assignment]
    _pb_ba_solver.upload_heavy_logs = _noop_upload  # type: ignore[assignment]
    _pb_ba_solver.optionally_upload_heavy_logs = _noop_optional  # type: ignore[assignment]
    log.info(
        "alcatraz-style upload helpers bypassed: sanity_check_docker, "
        "upload_heavy_logs, optionally_upload_heavy_logs"
    )
    try:
        yield
    finally:
        _pb_solver_utils.sanity_check_docker = orig_sanity  # type: ignore[assignment]
        _pb_upload.upload_heavy_logs = orig_heavy  # type: ignore[assignment]
        _pb_ba_utils.optionally_upload_heavy_logs = orig_optional  # type: ignore[assignment]
        if orig_solver_sanity is not None:
            _pb_ba_solver.sanity_check_docker = orig_solver_sanity  # type: ignore[assignment]
        if orig_solver_heavy is not None:
            _pb_ba_solver.upload_heavy_logs = orig_solver_heavy  # type: ignore[assignment]
        if orig_solver_optional is not None:
            _pb_ba_solver.optionally_upload_heavy_logs = orig_solver_optional  # type: ignore[assignment]


# ─── ari-flavoured solver ─────────────────────────────────────────────────


# Brief stub written to ``instructions.txt`` in the workspace. The agent's
# canonical task description comes from the conversation prompt (vendor's
# ``get_instructions`` + ``get_system_message``); this file only exists so
# tools that read ``instructions.txt`` see something non-empty.
_INSTRUCTIONS_TXT_STUB = (
    "See the conversation system + user messages for the full task brief. "
    "This file is a workspace artifact, not the canonical instruction source."
)


def _adapt_vendor_paths(text: str) -> str:
    """Map upstream's alcatraz hardcoded paths to ari's workspace-flat layout.

    PaperBench upstream's prompt files (``code_only_instructions.txt`` etc.)
    reference ``/home/submission``, ``/home/paper``, ``/home/agent.env`` —
    the alcatraz container's filesystem layout. ari's :class:`LocalComputer`
    instead operates on the host directly with the workspace
    (``repro_sandbox/``) as cwd, and :class:`LocalPBTask._setup` uploads
    paper materials to the workspace's ``paper/`` subdir while creating
    ``submission/`` as a sibling.

    We rewrite the absolute paths so the agent's bash / python tool calls
    land where ari expects them, while keeping the prompt wording verbatim
    from upstream. ``run_replicator_agent``'s post-rollout promote step
    (``submission/reproduce.sh`` → workspace-root ``reproduce.sh``) covers
    the "reproduce.sh placed inside submission/" case the upstream prompts
    encourage.
    """
    text = text.replace("/home/submission/", "submission/")
    text = text.replace("/home/submission", "submission")
    text = text.replace("/home/paper/", "paper/")
    text = text.replace("/home/paper", "paper")
    text = text.replace("/home/agent.env", "./agent.env")
    text = text.replace("/home/logs", "./logs")
    return text


# ─── tool-output truncation ──────────────────────────────────────────────


# OpenAI's Responses API rejects any single ``input[N].output`` string
# longer than 10 MB with a 400 ``string_above_max_length``. The agent
# occasionally prints whole NumPy arrays / huge directory listings whose
# stdout is multi-megabytes; cap each tool result well below the API
# ceiling so the next turn's API call doesn't abort the rollout.
_MAX_TOOL_OUTPUT_BYTES = 200 * 1024  # 200 KB; leaves >9 MB headroom for the
# rest of the conversation context.


def _truncate_tool_output(text: str, max_bytes: int = _MAX_TOOL_OUTPUT_BYTES) -> str:
    """Cap a tool stdout/stderr blob to ``max_bytes`` with a clear marker.

    Truncation is byte-based (not char-based) because OpenAI's limit is
    measured in bytes of the JSON-encoded UTF-8 string. The marker tells
    the agent why the output was cut and suggests follow-up strategies
    (head/tail/grep, or redirect to a file + ReadFileChunk).
    """
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= max_bytes:
        return text
    head_bytes = max_bytes - 256  # leave room for the trailing marker
    truncated = encoded[:head_bytes].decode("utf-8", errors="replace")
    return (
        truncated
        + f"\n\n[... TOOL OUTPUT TRUNCATED at {head_bytes:,} bytes; "
        f"original length {len(encoded):,} bytes. Re-run with head/tail/grep "
        f"or redirect to a file and use the file-read tool to inspect parts.]"
    )


from typing import Any as _Any
from paperbench.solvers.basicagent.tools.base import Tool as _Tool


class _BoundedOutputTool(_Tool):
    """:class:`Tool` wrapper capping ``execute()`` output bytes.

    Submit is detected by tool *name* in upstream's ``handle_tool_call``
    (its ``execute()`` is never called), so wrapping every non-submit tool
    is safe and keeps the dispatch contract intact.
    """
    inner: _Any
    max_bytes: int = _MAX_TOOL_OUTPUT_BYTES

    model_config = {"arbitrary_types_allowed": True}

    def name(self) -> str:
        return self.inner.name()

    async def execute(self, *args: _Any, **kwargs: _Any) -> str:
        out = await self.inner.execute(*args, **kwargs)
        if isinstance(out, str):
            return _truncate_tool_output(out, self.max_bytes)
        return out

    def get_oai_tool_call(self):  # type: ignore[override]
        return self.inner.get_oai_tool_call()


@chz.chz
class AriPBSolver(BasicAgentSolver):
    """:class:`BasicAgentSolver` with ari-specific ``_run_agent`` semantics.

    chz subclassing requires the decorator on the subclass too even when
    no new fields are added (chz immutable-config rule).
    """

    def _get_tools(self):  # type: ignore[override]
        """Wrap every non-submit tool with output-size capping.

        Submit is dispatched by name in ``handle_tool_call`` (its
        ``execute()`` is never invoked), so we only need to cap the
        bash / python / file-read / search tools whose output flows
        straight into the next API call.
        """
        base = super()._get_tools()
        return [
            t if t.name() == "submit" else _BoundedOutputTool(inner=t)
            for t in base
        ]

    async def _run_agent(  # type: ignore[override]
        self,
        computer: ComputerInterface,
        task: PBTask,
    ) -> AgentOutput:
        """Override of :meth:`BasicAgentSolver._run_agent`.

        Differences vs upstream:
          - bypasses :func:`paperbench.solvers.utils.sanity_check_docker`;
          - rewrites upstream's hardcoded ``/home/{submission,paper}`` paths
            to ari's workspace-relative layout (``LocalComputer`` cwd =
            ``repro_sandbox/``, ``LocalPBTask._setup`` uploads paper to
            ``paper/`` and creates ``submission/`` as a sibling).

        Prompt content otherwise comes verbatim from PaperBench upstream
        (``get_instructions`` / ``get_system_message``) — this keeps ari
        aligned with the upstream replication task definition (7-day budget
        framing, "use all available time", "do not stop until you have
        replicated all results", etc.) rather than encouraging early
        submission.

        We retain ``check_for_existing_run`` for idempotency (resume support).
        """
        existing = await check_for_existing_run(task)
        if existing:
            return existing

        # Step (3): bypass docker sanity check — see module docstring.
        async with _bypass_docker_sanity_check():
            start_time = time.time()
            instructions = await _vendor_get_instructions(
                computer, task, self.iterative_agent, self.time_limit
            )
            system_msg = _vendor_get_system_message(
                self.iterative_agent, task.judge.code_only
            )
            instructions = _adapt_vendor_paths(instructions)
            system_msg = _adapt_vendor_paths(system_msg)
            # ari-side addition: rubric-driven expected_artifacts +
            # (v0.7.2) execution_profile + cluster shape + HPC compute-node
            # conventions. Vendor's prompts don't know about ari's rubric
            # tree or the surrounding SLURM allocation, so the agent would
            # otherwise generate a single-node CPU implementation regardless
            # of the rubric's HPC requirements.
            artifacts: list[str] = []
            exec_profile: dict = {}
            cluster_shape: dict = {}
            if isinstance(task, LocalPBTask):
                artifacts = task.rubric_expected_artifacts
                exec_profile = task.rubric_execution_profile
                cluster_shape = task.cluster_shape
            appendix = _format_hpc_appendix(
                expected_artifacts=artifacts,
                execution_profile=exec_profile,
                cluster_shape=cluster_shape,
            )
            if appendix:
                instructions += appendix
            await self._execute_agent_and_periodically_upload_logs(
                computer=computer,
                task=task,
                prompt=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": instructions},
                ],
            )

        return AgentOutput(
            run_id=task.run_id,
            time_start=start_time,
            time_end=time.time(),
            error_msg=None,
            runtime_in_seconds=time.time() - start_time,
            # status.json is upstream-specific; we don't write one. Leaving
            # this False is honest about the absence.
            status_exists=False,
        )


# ─── high-level entry ─────────────────────────────────────────────────────


async def run_replicator_agent(
    *,
    paper_md_path: str,
    output_dir: str,
    expected_artifacts: list[str],
    execution_profile: dict | None = None,
    time_limit_sec: int = 12 * 3600,
    iterative_agent: bool = False,
    max_steps: int | None = None,
    completer_config: BasicAgentTurnCompleterConfig | None = None,
    sandbox_kind: str = "auto",
    apptainer_image: str | None = None,
    env: dict[str, str] | None = None,
    paper_id: str = "ari-local",
    run_id: str | None = None,
    paper_addendum_md_path: str = "",
    run_group_id: str = "ari-local",
) -> dict[str, Any]:
    """Run BasicAgent / IterativeAgent against the workspace ``output_dir``.

    Returns the standard ``build_reproduce_sh`` envelope:
    ``{populated, output_dir, files, expected_artifacts, max_runtime_sec,
    model, prompt_sha256, notes, warnings}``.

    Notes
    -----
    * ``output_dir`` is *both* the agent's workspace and where ari expects
      to find ``reproduce.sh`` after the rollout.
    * ``completer_config`` defaults to PaperBench upstream's
      :class:`OpenAIResponsesTurnCompleterConfig` with model ``gpt-5-mini``;
      see :mod:`_litellm_completer` for litellm-routed alternatives.
    * The vendor solver writes lots of bookkeeping (``agent.log`` etc.) to
      ``run_dir``; we point that at the workspace itself so the artifacts
      live alongside ``reproduce.sh``.
    """
    work = Path(output_dir).resolve()
    work.mkdir(parents=True, exist_ok=True)
    run_id = run_id or f"ari-{int(time.time())}"

    exec_profile = dict(execution_profile or {})
    cluster_shape = detect_cluster_shape()

    # Auto-inject the MPI aggregation skeleton when the rubric declares an
    # MPI-bearing kind. Placed at ``submission/mpi_aggregate.py`` so the
    # agent can simply copy or import from it; absent execution_profile
    # short-circuits silently.
    if exec_profile.get("kind") in _MPI_KINDS:
        skel_src = Path(__file__).resolve().parent / "prompts" / "mpi_aggregate_skel.py"
        if skel_src.is_file():
            sub = work / "submission"
            sub.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(skel_src, sub / "mpi_aggregate.py")
                log.info("injected MPI aggregate skeleton → %s", sub / "mpi_aggregate.py")
            except OSError as e:
                log.warning("could not inject MPI aggregate skeleton: %s", e)

    computer = make_computer(
        work_dir=work,
        kind=sandbox_kind,
        image=apptainer_image,
        env=env,
        timeout_sec=min(time_limit_sec, 30 * 60),
    )

    # The agent's canonical prompt is built in ``AriPBSolver._run_agent``
    # via PaperBench upstream's ``get_instructions`` + ``get_system_message``.
    # ``LocalPBTask._setup`` writes ``instructions.txt`` to the workspace as
    # a side artifact (its content must be a non-empty str); we pass a brief
    # stub since the conversation prompt is the source of truth.
    task = make_local_pbtask(
        paper_md_path=paper_md_path,
        paper_addendum_md_path=paper_addendum_md_path,
        work_dir=str(work),
        instructions=_INSTRUCTIONS_TXT_STUB,
        rubric_expected_artifacts=expected_artifacts,
        rubric_execution_profile=exec_profile,
        cluster_shape=cluster_shape,
        paper_id=paper_id,
        run_id=run_id,
        run_group_id=run_group_id,
        run_dir=str(work),
        runs_dir=str(work.parent),
        # code_only inherits make_local_pbtask's default (False since
        # v0.7.4) so the vendor full instructions.txt — which
        # explicitly requires reproduce.sh — reaches the agent.
        target_duration_hr=int(round(time_limit_sec / 3600)) or None,
    )

    if completer_config is None:
        # Default to upstream OpenAI Responses; users wire LiteLLM via the
        # litellm-backed BasicAgent completer config (Phase 4).
        completer_config = OpenAIResponsesTurnCompleterConfig(
            model=os.environ.get("ARI_MODEL_REPLICATOR") or "gpt-5-mini",
        )

    solver = AriPBSolver(
        completer_config=completer_config,
        max_steps=max_steps,
        time_limit=time_limit_sec,
        use_submit_tool=True,
        use_real_time_limit=True,
        iterative_agent=iterative_agent,
    )

    try:
        await task.setup(computer, runtime_config=solver.runtime_config_for_task(task))
        agent_output = await solver._run_agent(computer, task)
    finally:
        await computer.stop()

    # Promote submission/reproduce.sh → workspace root if the agent put it there.
    sub = work / "submission" / "reproduce.sh"
    root = work / "reproduce.sh"
    if sub.is_file() and not root.is_file():
        root.write_bytes(sub.read_bytes())
        try:
            root.chmod(0o755)
        except OSError:
            pass
        log.info("promoted submission/reproduce.sh → reproduce.sh")

    populated = root.is_file()
    files = sorted(p.name for p in work.iterdir() if p.is_file())
    return {
        "populated": populated,
        "output_dir": str(work),
        "files": files,
        "expected_artifacts": expected_artifacts,
        "max_runtime_sec": int(time_limit_sec),
        "language": "agent-driven",
        "model": getattr(completer_config, "model", "unknown"),
        "iterative_agent": bool(iterative_agent),
        "agent_runtime_sec": int(agent_output.runtime_in_seconds),
        "notes": (
            "Agent-driven replicator (BasicAgent/IterativeAgent). "
            "reproduce.sh promoted from submission/ if needed."
        ),
        "warnings": [] if populated else ["agent finished without writing reproduce.sh"],
    }


def runtime_config_for_task(self, task: PBTask):  # noqa: N802
    """Hook used by solver in some upstream paths; we just return the task's
    own runtime_config (which is already set inside ReproductionConfig
    defaults)."""
    return task.reproduction.runtime_config


# Patch the BasicAgentSolver class so the solver instance has access to a
# runtime_config_for_task accessor (upstream's PythonCodingSolver hierarchy
# defines this; chz config classes vary). Defensive: only patch if missing.
if not hasattr(BasicAgentSolver, "runtime_config_for_task"):
    BasicAgentSolver.runtime_config_for_task = runtime_config_for_task  # type: ignore[attr-defined]


__all__ = ["AriPBSolver", "run_replicator_agent"]
