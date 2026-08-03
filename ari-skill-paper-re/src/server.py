"""ari-skill-paper-re: Reproducibility grading via PaperBench SimpleJudge.

This skill exposes:

- ``run_reproduce``          — Phase 1 sandbox runner for ``reproduce.sh``.
- ``grade_with_simplejudge`` — Phase 2 grader, a thin wrapper around the
  upstream PaperBench ``SimpleJudge`` (see ``_paperbench_bridge.py``).
- ``fetch_code_bundle``      — pre-populates the sandbox with the curated
  EAR bundle (deterministic, no LLM).
- ``build_reproduce_sh``     — LLM-driven replicator; reads the paper and
  writes ``reproduce.sh`` + supporting source files into the sandbox. Used
  when no curated bundle / EAR is available. Skips when reproduce.sh is
  already present, so it composes cleanly after fetch_code_bundle / EAR.

The legacy LLM-driven metric-verdict tools (``extract_repro_config``,
``extract_metric_from_output``, ``build_repro_report``) were removed in the
§4.1 rewrite; the rubric now carries claims and PaperBench
``SimpleJudge`` reads the reproduce.log directly.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import statistics
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from ari.public import cost_tracker as _ari_cost_tracker
from ari.public.clone import CloneError, clone
from ari_skill_hpc import (
    EnvironmentPolicyV1,
    LocalCommandRunner,
    ResourceRequestV1,
    SchedulerError,
    SlurmScheduler,
    SubmissionLedger,
    handoff_execution_to_slurm,
)
from rubric_contract import (
    RubricContractError,
    load_rubric,
    to_paperbench_format,
)
from contracts import (
    FailureEvidenceV1,
    GradeReportV1,
    JudgeIdentityV1,
    LeafGradeEvidenceV1,
    NegativeControlV1,
    ReproductionContractError,
    artifact_from_path,
    bytes_digest,
    canonical_digest,
)
from sandbox import (
    begin_attempt,
    execute_container_attempt,
    execute_local_attempt,
    execution_request,
    finalize_attempt,
    load_run,
    prepare_reproduction,
    publish_latest_pointer,
    resolve_latest_run,
    tree_manifest,
)

log = logging.getLogger(__name__)

mcp = FastMCP("paper-reproducibility-skill")

try:
    _ari_cost_tracker.bootstrap_skill("paper-re")
except Exception:
    pass


def _load_paper_text(paper_path: str, paper_text: str) -> str:
    """Resolve paper content from either an inline string or a path."""
    if paper_text:
        return paper_text
    if not paper_path:
        return ""
    p = Path(paper_path)
    if p.suffix == ".pdf":
        try:
            r = subprocess.run(
                ["pdftotext", str(p), "-"],
                capture_output=True, text=True, timeout=30,
            )
            if r.stdout:
                return r.stdout
        except Exception:
            pass
    try:
        return p.read_text()
    except Exception as e:
        log.warning("Cannot read paper at %s: %s", paper_path, e)
        return ""


# ─── fetch_code_bundle MCP tool ───────────────────────────────────────
#
# Used by the reproducibility pipeline as a `pre_tool` to populate the
# sandbox before Phase 1 runs. The agent never has to clone — the working
# tree is already there. This is defense-in-depth on top of the git shim.


def _safe_bundle_destination(dest: str, checkpoint_dir: str) -> Path:
    """Resolve a bundle destination and reject broad/symlinked targets."""

    raw = Path(dest).expanduser()
    absolute = raw if raw.is_absolute() else Path.cwd() / raw
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"bundle destination crosses a symlink: {current}")
    resolved = absolute.resolve(strict=False)
    repository_root = Path(__file__).resolve().parents[2]
    protected = {
        Path(absolute.anchor).resolve(),
        Path.home().resolve(),
        Path.cwd().resolve(),
        repository_root,
        Path(__file__).resolve().parents[1],
    }
    if checkpoint_dir:
        protected.add(Path(checkpoint_dir).expanduser().resolve(strict=False))
    if resolved in protected or len(resolved.parts) < 3:
        raise ValueError(f"refusing broad bundle destination: {resolved}")
    return resolved


@mcp.tool()
async def fetch_code_bundle(
    ref: str = "",
    sha256: str = "",
    dest: str = "",
    checkpoint_dir: str = "",
    overwrite: bool = False,
) -> dict:
    """Pre-populate the sandbox with the curated EAR bundle (no LLM call).

    Args:
        ref: bundle reference (file://, https://, ari://, gh:, doi:). When
            empty AND ``checkpoint_dir`` is given, ref + sha256 are loaded
            from ``{checkpoint_dir}/publish_record.json`` (the file ``ari
            ear publish`` writes).
        sha256: required 64-hex bundle digest. Hard fail on mismatch.
        dest: target directory.
        checkpoint_dir: when non-empty, this enables auto-loading ref +
            sha256 from publish_record.json. Mirrors the convention used by
            ``inject_code_availability``.
        overwrite: when False (default) and ``dest/reproduce.sh`` exists,
            no work is done — composes with build_reproduce_sh / EAR
            pre-populate.

    Returns:
        ``{"populated": bool, "dest": str, "bundle_sha256": str, "files": int}``
        or ``{"populated": False, "skipped_reason": str}`` on the no-op path.
    """
    # Auto-load ref + sha256 from publish_record.json when not given.
    if not ref and checkpoint_dir:
        rec_path = Path(checkpoint_dir) / "publish_record.json"
        if rec_path.is_file():
            try:
                rec = json.loads(rec_path.read_text())
                ref = ref or str(rec.get("ref") or "")
                sha256 = sha256 or str(rec.get("bundle_sha256") or "")
            except Exception as e:
                log.warning("fetch_code_bundle: cannot read %s: %s", rec_path, e)

    if not ref:
        return {"populated": False, "skipped_reason": "no code_availability_ref"}
    if not dest:
        return {"populated": False, "skipped_reason": "no dest"}

    try:
        dest_path = _safe_bundle_destination(dest, checkpoint_dir)
    except (OSError, ValueError) as exc:
        return {"populated": False, "error": str(exc)}
    if (dest_path / "reproduce.sh").is_file() and not overwrite:
        return {
            "populated": False,
            "skipped_reason": f"reproduce.sh already present at {dest_path}/reproduce.sh; "
                              f"pass overwrite=True to re-fetch",
            "dest": str(dest_path),
        }

    # ari.clone refuses non-empty destinations. When overwrite=True, clear
    # the target so subsequent stages get a clean slate.
    if dest_path.exists() and any(dest_path.iterdir()):
        if overwrite:
            shutil.rmtree(dest_path)
        else:
            return {
                "populated": False,
                "skipped_reason": f"dest non-empty (no reproduce.sh, but other files): "
                                  f"{dest_path}; pass overwrite=True to clear",
                "dest": str(dest_path),
            }

    try:
        result = clone(ref, dest=dest_path, expect_sha256=sha256 or None)
    except CloneError as e:
        return {"populated": False, "error": str(e)}
    return {
        "populated": True,
        "dest": str(result.dest),
        "bundle_sha256": result.bundle_sha256,
        "files": result.file_count,
    }


# ─── build_reproduce_sh MCP tool (agent-driven replicator) ────────────
#
# v0.7+: this tool wraps PaperBench's BasicAgent / IterativeAgent solver
# (vendored under ``vendor/paperbench``), driven against ari's HPC sandbox
# via :class:`_compute.LocalComputer` / :class:`_compute.ApptainerComputer`.
# The pre-v0.7 single-shot LLM replicator has been deleted — see CHANGELOG.
#
# Composition contract: this tool is the agentic sibling of
# ``fetch_code_bundle``. Both target the same destination (typically
# ``{checkpoint_dir}/repro_sandbox``). The replicator skips with
# ``skipped_reason`` when reproduce.sh is already present unless the caller
# passes ``overwrite=True``, so a workflow that runs fetch_code_bundle (or
# a stage that copies EAR) before this tool will not regenerate the sandbox
# unnecessarily.


@mcp.tool()
async def build_reproduce_sh(
    paper_path: str = "",
    paper_text: str = "",
    rubric_path: str = "",
    output_dir: str = "",
    model: str = "",
    time_limit_sec: int = 12 * 3600,
    iterative_agent: bool = False,
    max_steps: int = 0,
    sandbox_kind: str = "auto",
    container_image: str = "",
    overwrite: bool = False,
) -> dict:
    """Replicator: drive a PaperBench-style ReAct agent against the workspace.

    Args:
        paper_path: path to .tex / .pdf / .txt; used when ``paper_text`` is empty.
        paper_text: inline paper content (overrides ``paper_path``).
        rubric_path: optional path to the frozen rubric envelope. When given,
            the rubric's ``reproduce_contract.expected_artifacts`` is fed to
            the agent prompt so its output aligns with the grader's
            expectations.
        output_dir: target sandbox directory (typically ``repro_sandbox/``).
            Becomes the agent's workspace; reproduce.sh ends up at its root.
        model: LiteLLM / OpenAI model id; overrides ``ARI_MODEL_REPLICATOR``.
        time_limit_sec: hard wall-clock budget for the agent rollout.
            PaperBench paper §5.2 uses 12 h by default; ``IterativeAgent``
            extended runs use up to 36 h.
        iterative_agent: when True, switches the agent to PaperBench's
            IterativeAgent variant (no submit-tool early termination,
            step-by-step prompting; see paper §5.3).
        max_steps: optional hard cap on agent steps; 0 = unlimited (only
            ``time_limit_sec`` constrains).
        sandbox_kind: ``auto`` | ``local`` | ``apptainer`` | ``slurm``;
            see :func:`_compute.make_computer`.
        container_image: container image used by the agent rollout. For
            ``sandbox_kind=apptainer`` this is an immutable local SIF or a
            digest-pinned remote URI. For ``local`` / ``slurm`` the value is
            ignored. When empty, ``ARI_PHASE1_APPTAINER_IMAGE`` is consulted.
        overwrite: when False (default) and ``output_dir/reproduce.sh`` is
            already present, no rollout is performed — returns
            ``populated=False, skipped_reason=...``.

    Returns the populated flag, written file list, expected_artifacts seen,
    max_runtime_sec, model id, and warnings (or ``error`` on failure).
    """
    if not output_dir:
        return {"populated": False, "error": "output_dir is required"}

    out = Path(output_dir)
    text = _load_paper_text(paper_path, paper_text)
    if not text:
        return {"populated": False, "error": "No paper text provided"}

    expected_artifacts: list[str] = []
    execution_profile: dict = {}
    rubric_schema_version = ""
    rubric_migration_required = False
    if rubric_path:
        try:
            loaded_rubric = load_rubric(rubric_path, paper_text=text)
            rubric = loaded_rubric.document
            rc = rubric.get("reproduce_contract") or {}
            expected_artifacts = list(rc.get("expected_artifacts") or [])
            execution_profile = dict(rc.get("execution_profile") or {})
            rubric_schema_version = loaded_rubric.schema_version
            rubric_migration_required = loaded_rubric.migration_required
        except RubricContractError as exc:
            return {
                "populated": False,
                "error": f"rubric contract rejected: {exc}",
            }

    if (out / "reproduce.sh").is_file() and not overwrite:
        return {
            "populated": False,
            "skipped_reason": (
                f"reproduce.sh already present at {out / 'reproduce.sh'}; "
                f"pass overwrite=True to regenerate"
            ),
            "output_dir": str(out),
            "rubric_schema_version": rubric_schema_version or None,
            "rubric_migration_required": rubric_migration_required,
        }

    out.mkdir(parents=True, exist_ok=True)
    paper_md = out / "_input_paper.md"
    paper_md.write_text(text, encoding="utf-8")

    from _replicator_agent import run_replicator_agent

    # Defaults come from env (set by api_experiment.py) when the workflow.yaml
    # passed sentinel values (0 / empty string). These are applied here, not
    # in workflow.yaml templating, because pipeline._resolve_templates is a
    # regex substitution (no Jinja2 ``| default(...)`` filter).
    chosen_model = (
        model
        or os.environ.get("ARI_MODEL_REPLICATOR")
        or os.environ.get("ARI_LLM_MODEL")
        or "gpt-5-mini"
    )
    if not int(time_limit_sec):
        time_limit_sec = int(os.environ.get("ARI_REPLICATOR_TIME_LIMIT_SEC") or 12 * 3600)
    if not iterative_agent:
        iterative_agent = os.environ.get("ARI_REPLICATOR_ITERATIVE", "0") == "1"
    if not int(max_steps):
        max_steps = int(os.environ.get("ARI_REPLICATOR_MAX_STEPS") or 0)
    if sandbox_kind in (None, "", "auto"):
        sandbox_kind = os.environ.get("ARI_PHASE1_SANDBOX") or "auto"

    # Pick the completer flavour based on the model id. PaperBench upstream's
    # OpenAIResponsesTurnCompleter only accepts OpenAI Responses API models;
    # for Anthropic / Gemini / Ollama / etc. we route through LiteLLM via
    # our LiteLLMBasicAgentCompleterConfig.
    is_openai_responses = (
        chosen_model.startswith(("gpt-", "o1-", "o3-", "o4-", "o5-"))
        and "/" not in chosen_model
    )
    if is_openai_responses:
        from paperbench.solvers.basicagent.completer import (
            OpenAIResponsesTurnCompleterConfig,
        )
        from openai.types.responses.web_search_tool_param import (
            WebSearchToolParam,
        )
        # Preserve the vendor BasicAgentSolver default_factory's
        # ``tools=[WebSearchToolParam(type="web_search_preview")]`` — we
        # construct a fresh completer_config to thread chosen_model, so
        # the vendor's web search tool would otherwise be lost. Without
        # this, the agent cannot look up library versions, baselines,
        # or recent commits during rollout.
        completer_config = OpenAIResponsesTurnCompleterConfig(
            model=chosen_model,
            tools=[WebSearchToolParam(type="web_search_preview")],
        )
    else:
        from _litellm_completer import get_litellm_basicagent_completer_config
        completer_config = get_litellm_basicagent_completer_config()(
            model=chosen_model,
        )

    resolved_image = container_image or os.environ.get(
        "ARI_PHASE1_APPTAINER_IMAGE", ""
    )

    result = await run_replicator_agent(
        paper_md_path=str(paper_md),
        output_dir=str(out),
        expected_artifacts=expected_artifacts,
        execution_profile=execution_profile,
        time_limit_sec=int(time_limit_sec),
        iterative_agent=bool(iterative_agent),
        max_steps=int(max_steps) or None,
        completer_config=completer_config,
        sandbox_kind=sandbox_kind,
        container_image=resolved_image or None,
    )
    result["rubric_schema_version"] = rubric_schema_version or None
    result["rubric_migration_required"] = rubric_migration_required
    return result


# ─── Phase 1 / Phase 2 (PaperBench-format) ─────────────────────────────


def _has_bin(name: str) -> bool:
    return shutil.which(name) is not None


def _docker_works() -> bool:
    if not _has_bin("docker"):
        return False
    return subprocess.run(["docker", "info"], capture_output=True).returncode == 0


def _on_hpc() -> bool:
    return any(os.environ.get(k) for k in ("SLURM_CLUSTER_NAME", "SLURM_JOB_ID"))


def _slurm_available() -> bool:
    """We can submit to SLURM iff sbatch is on PATH AND we know which
    partition to target (either via ARI_SLURM_PARTITION env, set by
    api_experiment.py from the wizard / launch_config.json, or via an
    explicit caller-supplied partition arg)."""
    if not _has_bin("sbatch"):
        return False
    return bool(os.environ.get("ARI_SLURM_PARTITION"))


def _phase1_sandbox_kind(default: str = "auto") -> str:
    """Resolve sandbox kind.

    ``auto`` priority:
        1. ``slurm`` — when sbatch is available AND ARI_SLURM_PARTITION is
           set. The reproduce.sh from BFTS was almost certainly compiled with
           ``-march=native`` on a partition CPU (e.g. AVX-512 on sx40), so
           re-running on the login node usually fails. Submit back to the
           same partition.
        2. ``docker`` — when daemon is usable AND we're not inside SLURM.
        3. ``apptainer`` → ``singularity`` → ``local``.

    Explicit ``ARI_PHASE1_SANDBOX`` always wins. Accepted explicit values:
    ``docker | apptainer | singularity | slurm | local | auto``.

    SLURM support was present in v0.5.0 (pre-§4.1 rewrite) and lost in the
    v0.6.0 paper-re rewrite alongside the legacy metric-verdict tools.
    """
    val = os.environ.get("ARI_PHASE1_SANDBOX") or default
    if val == "auto":
        if _slurm_available():
            return "slurm"
        if _docker_works() and not _on_hpc():
            return "docker"
        if _has_bin("apptainer"):
            return "apptainer"
        if _has_bin("singularity"):
            return "singularity"
        return "local"
    return val


def _judge_model() -> str:
    # Routed through LiteLLM via _litellm_completer, so any provider/model
    # litellm understands works (e.g. ``gpt-5-mini``, ``anthropic/claude-...``,
    # ``gemini/gemini-2.5-flash``). Falls back to the global ARI model env
    # so the same default applies repo-wide.
    return (
        os.environ.get("ARI_MODEL_JUDGE")
        or os.environ.get("ARI_LLM_MODEL")
        or "gpt-5-mini"
    )


def _read_log_tail(p: Path, max_bytes: int = 200_000) -> str:
    try:
        data = p.read_bytes()
    except Exception:
        return ""
    if len(data) <= max_bytes:
        return data.decode("utf-8", errors="replace")
    return data[-max_bytes:].decode("utf-8", errors="replace")


def _resolve_partition(partition: str = "") -> str:
    """Resolve target SLURM partition. Priority: explicit arg → env →
    launch_config.json (sibling of repo_dir's checkpoint dir, looked up by
    walking up from repo_dir at the call site)."""
    return (
        partition
        or os.environ.get("ARI_SLURM_PARTITION", "")
        or os.environ.get("SLURM_PARTITION", "")
    )


def _resolve_partition_for_repo(repo_dir: Path, partition: str = "") -> str:
    """Same as ``_resolve_partition`` but additionally consults
    ``{checkpoint_dir}/launch_config.json`` when the env is unset.
    ``repo_dir`` is typically ``{checkpoint_dir}/repro_sandbox`` so we look
    one level up."""
    p = _resolve_partition(partition)
    if p:
        return p
    for candidate in (repo_dir.parent / "launch_config.json", repo_dir / "launch_config.json"):
        if candidate.is_file():
            try:
                cfg = json.loads(candidate.read_text())
                p = str(cfg.get("partition") or "")
                if p:
                    return p
            except Exception:
                pass
    return ""


def _walltime_str(timeout_sec: int) -> str:
    """SLURM ``--time`` HH:MM:SS string, capped to a reasonable upper bound."""
    secs = max(60, int(timeout_sec))
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


_TERMINAL_JOB_STATES = {"succeeded", "failed", "cancelled"}
_DEPRECATED_SBATCH_FIELDS = {
    "--account=": "account",
    "--qos=": "qos",
    "--reservation=": "reservation",
    "--hint=": "hint",
}


def _parse_deprecated_sbatch_args(arguments: list[str] | None) -> dict[str, str]:
    """Translate the former arbitrary flag escape hatch into typed fields."""
    translated: dict[str, str] = {}
    for argument in arguments or ():
        if not isinstance(argument, str):
            raise ValueError("extra_sbatch_args entries must be strings")
        for prefix, field in _DEPRECATED_SBATCH_FIELDS.items():
            if argument.startswith(prefix):
                value = argument.removeprefix(prefix)
                if not value or field in translated:
                    raise ValueError(f"invalid or duplicate deprecated {prefix} value")
                translated[field] = value
                break
        else:
            raise ValueError(
                f"unsupported extra_sbatch_args entry {argument!r}; use a typed "
                "scheduler resource field"
            )
    return translated


def _paper_re_scheduler(repo_dir: Path) -> SlurmScheduler:
    """Construct the local canonical scheduler used by paper reproduction."""
    scheduler_path = os.environ.get(
        "ARI_SCHEDULER_PATH", "/usr/local/bin:/usr/bin:/bin"
    )
    EnvironmentPolicyV1(path=scheduler_path)
    return SlurmScheduler(
        runner=LocalCommandRunner(scheduler_path=scheduler_path),
        ledger=SubmissionLedger(
            repo_dir.parent / ".ari-hpc" / "paper-re-jobs-v1.json"
        ),
    )


def _materialize_scheduler_log(log_path: Path, job_logs: tuple) -> None:
    """Atomically publish verified scheduler stdout/stderr for judging."""
    text = "".join(
        item.text or ""
        for item in job_logs
        if item.stream in {"stdout", "stderr"}
    )
    temporary = log_path.parent / f".{log_path.name}.tmp"
    temporary.write_text(text, encoding="utf-8")
    temporary.chmod(0o600)
    os.replace(temporary, log_path)


async def _execute_reproduction_slurm(
    common_request,
    log_path: Path,
    *,
    partition: str = "",
    cpus: int = 0,
    walltime: str = "",
    nodes: int = 0,
    ntasks: int = 0,
    ntasks_per_node: int = 0,
    nodelist: str = "",
    exclude_nodes: str = "",
    exclusive: bool = False,
    gpus_per_task: int = 0,
    gpus_per_node: int = 0,
    gpu_type: str = "",
    memory_gb_per_node: int = 0,
    memory_gb_per_cpu: int = 0,
    constraint: str = "",
    cpu_bind: str = "",
    mem_bind: str = "",
    hint: str = "",
    account: str = "",
    qos: str = "",
    reservation: str = "",
    module_loads: tuple[str, ...] = (),
    extra_sbatch_args: list[str] | None = None,
    network_isolation_attested: bool = False,
) -> dict:
    """Handoff a common execution request to the typed SLURM lifecycle."""
    repo_dir = Path(common_request.workspace.root)
    timeout = int(common_request.timeout_seconds)
    if not _has_bin("sbatch"):
        raise RuntimeError(
            "sandbox_kind=slurm requested but sbatch is not on PATH. "
            "Refusing to silently fall back to local execution."
        )

    resolved_partition = _resolve_partition_for_repo(repo_dir, partition)
    if not resolved_partition:
        raise RuntimeError(
            "sandbox_kind=slurm requested but no partition could be resolved"
        )

    script = repo_dir / "reproduce.sh"
    if not script.is_file():
        return {"executed": False, "exit_code": None, "error": "reproduce.sh missing"}
    if cpu_bind or mem_bind:
        raise ValueError(
            "cpu_bind and mem_bind are srun job-step settings; place them "
            "explicitly in reproduce.sh"
        )

    started = time.monotonic()
    try:
        deprecated = _parse_deprecated_sbatch_args(extra_sbatch_args)
        account = account or deprecated.get("account", "")
        qos = qos or deprecated.get("qos", "")
        reservation = reservation or deprecated.get("reservation", "")
        hint = hint or deprecated.get("hint", "")
        n_cpus = (
            int(cpus)
            if cpus and int(cpus) > 0
            else int(os.environ.get("ARI_SLURM_CPUS", "8"))
        )
        resolved_walltime = (
            walltime
            or os.environ.get("ARI_SLURM_WALLTIME", "")
            or _walltime_str(timeout)
        )
        effective_gpus_per_task = int(gpus_per_task or 0)
        effective_gpus_per_node = int(gpus_per_node or 0)
        if gpu_type and not (effective_gpus_per_task or effective_gpus_per_node):
            effective_gpus_per_node = 1

        resolved_tasks = int(
            ntasks
            or (int(ntasks_per_node) * int(nodes or 1) if ntasks_per_node else 1)
        )
        resources = ResourceRequestV1(
            partition=resolved_partition,
            nodes=int(nodes or 1),
            tasks=resolved_tasks,
            tasks_per_node=int(ntasks_per_node) if ntasks_per_node else None,
            cpus_per_task=n_cpus,
            memory_mb_per_node=(
                int(memory_gb_per_node) * 1024 if memory_gb_per_node else None
            ),
            memory_mb_per_cpu=(
                int(memory_gb_per_cpu) * 1024 if memory_gb_per_cpu else None
            ),
            gpus_per_task=effective_gpus_per_task,
            gpus_per_node=effective_gpus_per_node,
            gpu_type=gpu_type or None,
            walltime=resolved_walltime,
            nodelist=nodelist or None,
            exclude_nodes=exclude_nodes or None,
            exclusive=exclusive,
            constraint=constraint or None,
            hint=hint or None,
            account=account or None,
            qos=qos or None,
            reservation=reservation or None,
        )
        handoff = handoff_execution_to_slurm(
            common_request,
            request_id=(
                "paper-re-"
                + common_request.execution_identity.removeprefix("sha256:")[:24]
            ),
            job_name="ari-ors",
            resources=resources,
            modules=module_loads,
            network_isolation_attested=network_isolation_attested,
        )
        scheduler = _paper_re_scheduler(repo_dir)
        handle = await scheduler.submit(handoff.job_request)
        deadline = time.monotonic() + timeout + 60
        while True:
            status = await scheduler.status(handle.handle_id)
            if status.state in _TERMINAL_JOB_STATES:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                try:
                    await scheduler.cancel(handle.handle_id)
                except SchedulerError as exc:
                    log.warning("failed to cancel timed-out job %s: %s", handle.job_id, exc)
                job_logs = await scheduler.logs(handle.handle_id)
                _materialize_scheduler_log(log_path, job_logs)
                return {
                    "executed": True,
                    "exit_code": None,
                    "timed_out": True,
                    "elapsed_sec": round(time.monotonic() - started, 2),
                    "partition": resolved_partition,
                    "handle_id": handle.handle_id,
                    "job_id": handle.job_id,
                    "request_digest": handle.request_digest,
                    "handoff_digest": handoff.handoff_digest,
                    "execution_identity": handoff.execution_identity,
                    "unmapped_policies": list(handoff.unmapped_policies),
                }
            await asyncio.sleep(min(5.0, remaining))
        job_logs = await scheduler.logs(handle.handle_id)
        _materialize_scheduler_log(log_path, job_logs)
        scheduler_result = (
            await scheduler.result(handle.handle_id)
            if hasattr(scheduler, "result")
            else None
        )
    except (SchedulerError, ValueError, OSError) as exc:
        return {
            "executed": False,
            "exit_code": None,
            "error": str(exc)[:1000],
            "elapsed_sec": round(time.monotonic() - started, 2),
            "partition": resolved_partition,
        }

    out: dict = {
        "executed": True,
        "exit_code": status.exit_code if status.exit_code is not None else (
            0 if status.state == "succeeded" else None
        ),
        "elapsed_sec": round(time.monotonic() - started, 2),
        "partition": resolved_partition,
        "cpus": n_cpus,
        "walltime": resolved_walltime,
        "handle_id": handle.handle_id,
        "job_id": handle.job_id,
        "request_digest": handle.request_digest,
        "handoff_digest": handoff.handoff_digest,
        "execution_identity": handoff.execution_identity,
        "unmapped_policies": list(handoff.unmapped_policies),
        "policy_equivalent": handoff.policy_equivalent,
    }
    if scheduler_result is not None:
        out["scheduler_result_digest"] = scheduler_result.result_digest
        out["environment_digest"] = scheduler_result.environment_digest
        out["module_snapshot_digest"] = scheduler_result.module_snapshot_digest
        out["provenance"] = [
            artifact.model_dump(mode="json")
            for artifact in scheduler_result.provenance
        ]
    if nodes:
        out["nodes"] = int(nodes)
    if ntasks:
        out["ntasks"] = int(ntasks)
    if exclusive:
        out["exclusive"] = True
    if effective_gpus_per_task or effective_gpus_per_node or gpu_type:
        out["gpu"] = {
            "per_task": effective_gpus_per_task,
            "per_node": effective_gpus_per_node,
            "type": gpu_type,
        }
    if status.state != "succeeded":
        out["error"] = f"scheduler job ended in {status.scheduler_state}"
    return out


def _reproduction_response(
    *,
    prepared,
    run,
    attempt_id: str,
    work_dir: Path,
    rubric_schema_version: str,
    rubric_migration_required: bool,
    idempotent_replay: bool,
) -> dict:
    """Project the immutable run record into the stable MCP response shape."""

    attempt = next(item for item in run.attempts if item.attempt_id == attempt_id)
    artifacts = [
        path.relative_to(work_dir).as_posix()
        for path in sorted(work_dir.rglob("*"))
        if path.is_file()
        and path.relative_to(work_dir).parts[0] not in {".ari-execution", ".ari-hpc"}
    ]
    environment = dict(attempt.environment)
    out = {
        "executed": bool(environment.get("launched", True)),
        "exit_code": attempt.exit_code,
        "log_path": str(prepared.source / attempt.log_artifact.relative_path),
        "artifacts": artifacts,
        "missing": list(attempt.expected_missing),
        "elapsed_sec": float(environment.get("elapsed_sec", 0.0)),
        "sandbox_kind": prepared.plan.sandbox,
        "rubric_schema_version": rubric_schema_version,
        "rubric_migration_required": rubric_migration_required,
        "plan_path": str(prepared.plan_path),
        "plan_digest": prepared.plan.plan_digest,
        "run_record_path": str(prepared.run_path),
        "run_digest": run.run_digest,
        "attempt_id": attempt.attempt_id,
        "attempt_status": attempt.status,
        "executed_repo_dir": str(work_dir),
        "idempotent_replay": idempotent_replay,
    }
    scheduler = environment.get("scheduler")
    if isinstance(scheduler, dict):
        for key in (
            "partition",
            "cpus",
            "walltime",
            "nodes",
            "ntasks",
            "exclusive",
            "gpu",
            "handle_id",
            "job_id",
            "request_digest",
            "timed_out",
        ):
            if key in scheduler:
                out[key] = scheduler[key]
    if attempt.status == "timed_out":
        out["timed_out"] = True
    if attempt.failure is not None:
        out["error"] = attempt.failure.message
        out["failure_kind"] = attempt.failure.kind
    return out


def _failed_execution(
    prepared,
    attempt,
    *,
    substrate: str,
    message: str,
    failure_kind: str,
    launched: bool,
    status: str = "failed",
) -> dict:
    message = message[:4096] or "reproduction failed without a diagnostic"
    return {
        "status": status,
        "exit_code": None,
        "stdout": b"",
        "stderr": message.encode("utf-8", errors="replace"),
        "execution_identity": execution_request(prepared, attempt).execution_identity,
        "substrate_request_digest": None,
        "environment": {"launched": launched, "substrate": substrate},
        "failure": FailureEvidenceV1(kind=failure_kind, message=message),
    }


@mcp.tool()
async def run_reproduce(
    rubric_path: str,
    repo_dir: str,
    sandbox_kind: str = "",
    container_image: str = "",
    timeout_global_sec: int = 0,
    network_policy: str = "deny",
    network_isolation_attested: bool = False,
    partition: str = "",
    cpus: int = 0,
    walltime: str = "",
    nodes: int = 0,
    ntasks: int = 0,
    ntasks_per_node: int = 0,
    nodelist: str = "",
    exclude_nodes: str = "",
    exclusive: bool = False,
    gpus_per_task: int = 0,
    gpus_per_node: int = 0,
    gpu_type: str = "",
    memory_gb_per_node: int = 0,
    memory_gb_per_cpu: int = 0,
    constraint: str = "",
    cpu_bind: str = "",
    mem_bind: str = "",
    hint: str = "",
    account: str = "",
    qos: str = "",
    reservation: str = "",
    module_loads: list[str] | None = None,
    extra_sbatch_args: list[str] | None = None,
) -> dict:
    """Execute a content-bound reproduction attempt and retain its evidence.

    The source tree is snapshotted read-only and execution happens in a private
    attempt tree. Network access is denied by default; an unisolated substrate
    must be explicitly admitted with ``network_policy=inherit``. Successful
    identical plans are replayed idempotently and failed plans gain a linked
    retry attempt.
    """

    rubric: dict = {}
    rubric_schema_version = "ari.replication-rubric/explicit-input-v1"
    rubric_migration_required = False
    if rubric_path:
        try:
            loaded_rubric = load_rubric(rubric_path)
            rubric = loaded_rubric.document
            rubric_schema_version = loaded_rubric.schema_version
            rubric_migration_required = loaded_rubric.migration_required
        except RubricContractError as exc:
            return {"executed": False, "error": f"rubric contract rejected: {exc}"}

    repo = Path(repo_dir)
    if not repo.is_dir():
        return {
            "executed": False,
            "skipped_reason": f"repo_dir not present: {repo_dir}",
            "exit_code": None,
            "log_path": "",
            "artifacts": [],
            "missing": [],
            "elapsed_sec": 0.0,
            "sandbox_kind": "",
            "rubric_schema_version": rubric_schema_version,
            "rubric_migration_required": rubric_migration_required,
        }

    rc = rubric.get("reproduce_contract") or {}
    max_runtime = int(timeout_global_sec or rc.get("max_runtime_sec") or 21600)
    expected = list(rc.get("expected_artifacts") or [])
    exec_profile: dict = dict(rc.get("execution_profile") or {})
    requested = (sandbox_kind or _phase1_sandbox_kind()).lower()
    kind = _phase1_sandbox_kind() if requested == "auto" else requested
    if kind not in {"local", "docker", "apptainer", "singularity", "slurm"}:
        return {"executed": False, "error": f"unknown sandbox_kind: {kind}"}

    if not container_image:
        if kind == "docker":
            container_image = os.environ.get("ARI_PHASE1_DOCKER_IMAGE", "")
        elif kind in {"apptainer", "singularity"}:
            container_image = os.environ.get("ARI_PHASE1_APPTAINER_IMAGE", "")

    resolved_nodes = int(nodes) or int(exec_profile.get("requested_nodes", 0) or 0)
    resolved_ntasks = int(ntasks) or int(exec_profile.get("min_ranks", 0) or 0)
    resolved_ntasks_per_node = int(ntasks_per_node) or int(
        exec_profile.get("ntasks_per_node", 0) or 0
    )
    resolved_nodelist = nodelist or (exec_profile.get("requested_nodelist") or "")
    resolved_exclude_nodes = exclude_nodes or (exec_profile.get("exclude_nodes") or "")
    resolved_exclusive = bool(exclusive) or bool(exec_profile.get("exclusive", False))
    resolved_gpus_per_task = int(gpus_per_task) or int(
        exec_profile.get("requested_gpus_per_task", 0) or 0
    )
    resolved_gpus_per_node = int(gpus_per_node) or int(
        exec_profile.get("requested_gpus_per_node", 0) or 0
    )
    resolved_gpu_type = gpu_type or (exec_profile.get("gpu_type") or "")
    resolved_mem_gb_node = int(memory_gb_per_node) or int(
        exec_profile.get("memory_gb_per_node", 0) or 0
    )
    resolved_mem_gb_cpu = int(memory_gb_per_cpu) or int(
        exec_profile.get("memory_gb_per_cpu", 0) or 0
    )
    resolved_constraint = constraint or (exec_profile.get("constraint") or "")
    resolved_hint = hint or (exec_profile.get("hint") or "")
    resolved_account = account or (exec_profile.get("account") or "")
    resolved_qos = qos or (exec_profile.get("qos") or "")
    resolved_reservation = reservation or (exec_profile.get("reservation") or "")
    resolved_modules = tuple(module_loads or exec_profile.get("module_loads") or ())
    resolved_extra = list(
        extra_sbatch_args or exec_profile.get("extra_sbatch_args") or []
    )
    try:
        deprecated = _parse_deprecated_sbatch_args(resolved_extra)
    except ValueError as exc:
        return {"executed": False, "error": str(exc)}
    resolved_account = resolved_account or deprecated.get("account", "")
    resolved_qos = resolved_qos or deprecated.get("qos", "")
    resolved_reservation = resolved_reservation or deprecated.get("reservation", "")
    resolved_hint = resolved_hint or deprecated.get("hint", "")
    resolved_partition = (
        _resolve_partition_for_repo(repo, partition) if kind == "slurm" else ""
    )
    resolved_cpus = 0
    resolved_walltime = ""
    if kind == "slurm":
        resolved_cpus = int(cpus or os.environ.get("ARI_SLURM_CPUS", "8"))
        resolved_walltime = (
            walltime
            or os.environ.get("ARI_SLURM_WALLTIME", "")
            or _walltime_str(max_runtime)
        )
    resources = {
        "partition": resolved_partition,
        "cpus_per_task": resolved_cpus,
        "walltime": resolved_walltime,
        "nodes": resolved_nodes,
        "ntasks": resolved_ntasks,
        "ntasks_per_node": resolved_ntasks_per_node,
        "nodelist": resolved_nodelist,
        "exclude_nodes": resolved_exclude_nodes,
        "exclusive": resolved_exclusive,
        "gpus_per_task": resolved_gpus_per_task,
        "gpus_per_node": resolved_gpus_per_node,
        "gpu_type": resolved_gpu_type,
        "memory_gb_per_node": resolved_mem_gb_node,
        "memory_gb_per_cpu": resolved_mem_gb_cpu,
        "constraint": resolved_constraint,
        "cpu_bind": cpu_bind,
        "mem_bind": mem_bind,
        "hint": resolved_hint,
        "account": resolved_account,
        "qos": resolved_qos,
        "reservation": resolved_reservation,
        "module_loads": list(resolved_modules),
    }
    rubric_sha256 = str(
        rubric.get("rubric_sha256") or bytes_digest(b"").removeprefix("sha256:")
    )
    try:
        prepared = prepare_reproduction(
            source_workspace=str(repo),
            rubric_schema_version=rubric_schema_version,
            rubric_sha256=rubric_sha256,
            sandbox_kind=kind,
            container_image=container_image,
            timeout_seconds=max_runtime,
            expected_artifacts=expected,
            network_policy=network_policy,
            network_isolation_attested=network_isolation_attested,
            resources=resources,
        )
        previous = load_run(prepared)
    except (ReproductionContractError, ValueError, OSError) as exc:
        return {
            "executed": False,
            "error": f"reproduction plan rejected: {exc}",
            "sandbox_kind": kind,
            "rubric_schema_version": rubric_schema_version,
            "rubric_migration_required": rubric_migration_required,
        }

    if previous is not None and previous.status == "succeeded":
        selected_id = previous.selected_attempt_id
        assert selected_id is not None
        selected = next(
            item for item in previous.attempts if item.attempt_id == selected_id
        )
        work_dir = (prepared.source / selected.log_artifact.relative_path).parent
        try:
            publish_latest_pointer(
                prepared, previous, attempt_id=selected_id, work_dir=work_dir
            )
        except ReproductionContractError as exc:
            return {"executed": False, "error": f"stored run rejected: {exc}"}
        return _reproduction_response(
            prepared=prepared,
            run=previous,
            attempt_id=selected_id,
            work_dir=work_dir,
            rubric_schema_version=rubric_schema_version,
            rubric_migration_required=rubric_migration_required,
            idempotent_replay=True,
        )

    try:
        attempt = begin_attempt(prepared, previous)
    except (ReproductionContractError, OSError) as exc:
        return {"executed": False, "error": f"cannot create attempt: {exc}"}

    started = time.monotonic()
    try:
        if kind == "local":
            execution = await execute_local_attempt(prepared, attempt)
        elif kind in {"docker", "apptainer", "singularity"}:
            execution = await execute_container_attempt(prepared, attempt)
        else:
            common_request = execution_request(prepared, attempt)
            slurm_result = await _execute_reproduction_slurm(
                common_request,
                attempt.work_dir / "reproduce.log",
                partition=resolved_partition,
                cpus=resolved_cpus,
                walltime=resolved_walltime,
                nodes=resolved_nodes,
                ntasks=resolved_ntasks,
                ntasks_per_node=resolved_ntasks_per_node,
                nodelist=resolved_nodelist,
                exclude_nodes=resolved_exclude_nodes,
                exclusive=resolved_exclusive,
                gpus_per_task=resolved_gpus_per_task,
                gpus_per_node=resolved_gpus_per_node,
                gpu_type=resolved_gpu_type,
                memory_gb_per_node=resolved_mem_gb_node,
                memory_gb_per_cpu=resolved_mem_gb_cpu,
                constraint=resolved_constraint,
                cpu_bind=cpu_bind,
                mem_bind=mem_bind,
                hint=resolved_hint,
                account=resolved_account,
                qos=resolved_qos,
                reservation=resolved_reservation,
                module_loads=resolved_modules,
                extra_sbatch_args=[],
                network_isolation_attested=network_isolation_attested,
            )
            scheduler_log = attempt.work_dir / "reproduce.log"
            combined = scheduler_log.read_bytes() if scheduler_log.is_file() else b""
            status = (
                "timed_out"
                if slurm_result.get("timed_out")
                else "succeeded"
                if slurm_result.get("executed")
                and slurm_result.get("exit_code") == 0
                and "error" not in slurm_result
                else "failed"
            )
            execution = {
                "status": status,
                "exit_code": slurm_result.get("exit_code"),
                "stdout": combined,
                "stderr": b"",
                "execution_identity": slurm_result.get("execution_identity")
                or common_request.execution_identity,
                "substrate_request_digest": slurm_result.get("request_digest"),
                "environment": {
                    "launched": bool(slurm_result.get("executed")),
                    "substrate": "slurm",
                    "modules": list(resolved_modules),
                    "network": prepared.plan.policy.network_enforcement,
                    "scheduler": dict(slurm_result),
                },
            }
            if status == "failed" and slurm_result.get("error"):
                execution["failure"] = FailureEvidenceV1(
                    kind="scheduler-failure",
                    message=str(slurm_result["error"])[:4096],
                )
    except asyncio.CancelledError:
        execution = _failed_execution(
            prepared,
            attempt,
            substrate=kind,
            message="reproduction request cancelled",
            failure_kind="cancelled",
            launched=True,
            status="cancelled",
        )
    except Exception as exc:
        message = str(exc) or exc.__class__.__name__
        lowered = message.casefold()
        failure_kind = (
            "network-policy"
            if "network" in lowered
            else "scheduler-failure"
            if kind == "slurm"
            else "sandbox-unavailable"
        )
        execution = _failed_execution(
            prepared,
            attempt,
            substrate=kind,
            message=message,
            failure_kind=failure_kind,
            launched=False,
        )
    execution.setdefault("environment", {})["elapsed_sec"] = round(
        time.monotonic() - started, 3
    )
    try:
        run, _pointer = finalize_attempt(prepared, attempt, execution, previous)
    except (ReproductionContractError, ValueError, OSError) as exc:
        return {"executed": False, "error": f"cannot finalize attempt: {exc}"}
    return _reproduction_response(
        prepared=prepared,
        run=run,
        attempt_id=attempt.attempt_id,
        work_dir=attempt.work_dir,
        rubric_schema_version=rubric_schema_version,
        rubric_migration_required=rubric_migration_required,
        idempotent_replay=False,
    )


async def _grade_once(
    pb_taskroot,
    paper_md: str,
    repo_dir: Path,
    reproduce_log: str,
    judge_model: str,
    code_only: bool = False,
    trace_dir: Path | None = None,
):
    from _paperbench_bridge import judge_submission

    return await judge_submission(
        paper_md=paper_md,
        rubric=pb_taskroot,
        submission_dir=repo_dir,
        reproduce_log=reproduce_log,
        judge_model=judge_model,
        code_only=code_only,
        trace_dir=trace_dir,
    )


async def _negative_control_check(
    pb_taskroot,
    paper_md: str,
    judge_model: str,
    code_only: bool = False,
    trace_dir: Path | None = None,
) -> dict:
    """Apply rubric to (a) empty repo and (b) trivial-reproduce.sh repo.

    Both should score below 5%. ``passed=True`` only if both fall under 0.05.

    ``code_only`` is threaded so the negative-control grading uses the
    same rubric scope as the main grading call. Without this, a code_only
    main run would be compared against a full-rubric control, which
    sometimes inverts the pass/fail decision.
    """
    from _paperbench_bridge import aggregate_graded_tree

    results: dict = {}
    with tempfile.TemporaryDirectory() as empty:
        graded = await _grade_once(
            pb_taskroot, paper_md, Path(empty), "", judge_model,
            code_only=code_only,
            trace_dir=trace_dir / "empty" if trace_dir else None,
        )
        results["empty"] = aggregate_graded_tree(graded)["ors_score"]
    with tempfile.TemporaryDirectory() as bp:
        bp_path = Path(bp)
        sh = bp_path / "reproduce.sh"
        sh.write_text("#!/bin/bash\necho 'no-op'\nexit 0\n")
        sh.chmod(0o755)
        graded = await _grade_once(
            pb_taskroot, paper_md, bp_path, "", judge_model,
            code_only=code_only,
            trace_dir=trace_dir / "boilerplate" if trace_dir else None,
        )
        results["boilerplate"] = aggregate_graded_tree(graded)["ors_score"]
    results["passed"] = (results["empty"] < 0.05 and results["boilerplate"] < 0.05)
    return results


def _atomic_grade_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        allow_nan=False,
    ).encode("utf-8")
    temporary = path.parent / f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp"
    temporary.write_bytes(encoded)
    temporary.chmod(0o600)
    os.replace(temporary, path)


def _allocate_grade_root(base: Path, *, reproduction_source: bool) -> Path:
    parent = (
        base / ".ari-reproduction" / "grades"
        if reproduction_source
        else base / ".ari-grades"
    )
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    identity = canonical_digest(
        {"pid": os.getpid(), "time_ns": time.time_ns(), "base": str(base)}
    ).removeprefix("sha256:")[:32]
    root = parent / identity
    root.mkdir(mode=0o700)
    return root


def _resolve_grade_reproduction(repo: Path):
    resolved_repo = repo.resolve(strict=True)
    candidates = [resolved_repo, *list(resolved_repo.parents)[:12]]
    for candidate in candidates:
        if not (candidate / ".ari-reproduction" / "latest.json").is_file():
            continue
        resolved = resolve_latest_run(candidate)
        if resolved is None:
            continue
        run, work_dir = resolved
        if candidate != resolved_repo and not (
            resolved_repo == work_dir or resolved_repo.is_relative_to(work_dir)
        ):
            continue
        return candidate, run, work_dir
    return None


def _judge_identity(model: str) -> JudgeIdentityV1:
    if "/" in model:
        provider = model.split("/", 1)[0]
    elif model.startswith(("gpt-", "o1", "o3", "o4", "o5")):
        provider = "openai"
    else:
        provider = "litellm"
    return JudgeIdentityV1(model=model, provider=provider)


def _models_are_independent(rubric: dict, judge_model: str) -> bool:
    generator = rubric.get("generator") or {}
    generator_model = str(generator.get("model") or "").strip().casefold()
    return bool(generator_model) and generator_model != judge_model.strip().casefold()


def _walk_graded_leaves(root) -> list:
    leaves: list = []

    def visit(node) -> None:
        children = list(node.sub_tasks) if node.sub_tasks else []
        if not children:
            leaves.append(node)
            return
        for child in children:
            visit(child)

    visit(root)
    return leaves


def _rubric_verification_map(rubric: dict) -> dict[str, dict[str, Any]]:
    values: dict[str, dict[str, Any]] = {}

    def visit(node: dict) -> None:
        children = node.get("sub_tasks") or []
        if not children and isinstance(node.get("verification"), dict):
            values[str(node.get("id"))] = dict(node["verification"])
        for child in children:
            if isinstance(child, dict):
                visit(child)

    root = rubric.get("rubric")
    if isinstance(root, dict):
        visit(root)
    return values


def _persist_leaf_evidence(
    *,
    runs: list,
    grade_root: Path,
    artifact_base: Path,
    verification: dict[str, dict[str, Any]],
) -> tuple[LeafGradeEvidenceV1, ...]:
    by_leaf: dict[str, list[tuple[int, Any, Any]]] = {}
    for run_index, run in enumerate(runs, start=1):
        run_dir = grade_root / "leaf-responses" / f"run-{run_index:04d}"
        for leaf in _walk_graded_leaves(run):
            leaf_id = str(leaf.id)
            metadata = getattr(leaf, "judge_metadata", None)
            payload = {
                "schema_version": "ari.leaf-judge-evidence/v1",
                "run_index": run_index,
                "leaf_id": leaf_id,
                "requirements": str(leaf.requirements),
                "score": float(leaf.score),
                "valid_score": bool(getattr(leaf, "valid_score", False)),
                "explanation": str(getattr(leaf, "explanation", "")),
                "full_judge_response": (
                    metadata.get("full_judge_response")
                    if isinstance(metadata, dict)
                    else None
                ),
                "judge_metadata": metadata,
            }
            name = bytes_digest(leaf_id.encode("utf-8")).removeprefix("sha256:")
            evidence_path = run_dir / f"{name}.json"
            _atomic_grade_json(evidence_path, payload)
            artifact = artifact_from_path(
                evidence_path,
                base=artifact_base,
                role="leaf-judge-raw-response",
            )
            by_leaf.setdefault(leaf_id, []).append((run_index, leaf, artifact))

    leaves: list[LeafGradeEvidenceV1] = []
    for leaf_id, observations in sorted(by_leaf.items()):
        scores = tuple(float(item[1].score) for item in observations)
        first = observations[0][1]
        leaves.append(
            LeafGradeEvidenceV1(
                leaf_id=leaf_id,
                requirements=str(first.requirements),
                score=sum(scores) / len(scores),
                valid_score=all(
                    bool(getattr(item[1], "valid_score", False))
                    for item in observations
                ),
                explanation=str(getattr(first, "explanation", "")),
                verification=verification.get(leaf_id),
                run_scores=scores,
                raw_response_artifacts=tuple(item[2] for item in observations),
            )
        )
    return tuple(leaves)


def _collect_call_artifacts(
    calls_root: Path,
    *,
    artifact_base: Path,
) -> tuple:
    if not calls_root.is_dir():
        return ()
    return tuple(
        artifact_from_path(
            path,
            base=artifact_base,
            role="model-call-trace",
        )
        for path in sorted(calls_root.rglob("*.json"))
        if path.is_file() and not path.is_symlink()
    )


def _save_grade_report(grade_root: Path, report: GradeReportV1) -> Path:
    report_path = grade_root / "grade-report.json"
    _atomic_grade_json(report_path, report.model_dump(mode="json"))
    validated = GradeReportV1.model_validate_json(report_path.read_text())
    if validated != report:
        raise ReproductionContractError("stored grade report differs")
    return report_path


def _grade_response(
    report: GradeReportV1,
    report_path: Path,
    *,
    elapsed_sec: float,
    code_only: bool,
) -> dict:
    out = {
        "grade_status": report.status,
        "grade_report_path": str(report_path),
        "grade_report_digest": report.report_digest,
        "rubric_sha256": report.rubric_digest.removeprefix("sha256:"),
        "rubric_schema_version": report.rubric_schema_version,
        "reproduction_run_digest": report.reproduction_run_digest,
        "reproduction_status": report.reproduction_status,
        "judge_model": report.judge.model,
        "judge_provider": report.judge.provider,
        "independence_status": report.independence_status,
        "n_runs": report.n_runs_requested,
        "n_runs_completed": report.n_runs_completed,
        "code_only": code_only,
        "elapsed_sec": elapsed_sec,
        "leaf_grades": [
            {
                "id": leaf.leaf_id,
                "requirements": leaf.requirements,
                "mean_score": leaf.score,
                "valid_score": leaf.valid_score,
                "explanation": leaf.explanation,
                "n_runs": len(leaf.run_scores),
                "run_scores": list(leaf.run_scores),
                "raw_response_artifacts": [
                    artifact.model_dump(mode="json")
                    for artifact in leaf.raw_response_artifacts
                ],
            }
            for leaf in report.leaves
        ],
        "negative_control_check": {
            "empty": report.negative_control.empty_score,
            "boilerplate": report.negative_control.boilerplate_score,
            "passed": report.negative_control.status == "passed",
            "status": report.negative_control.status,
            "error": report.negative_control.error,
        },
        "call_artifacts": [
            artifact.model_dump(mode="json") for artifact in report.call_artifacts
        ],
    }
    if report.status == "failed":
        out["error"] = "; ".join(report.errors)
        out["errors"] = list(report.errors)
    else:
        out["ors_score"] = report.ors_score
        out["raw_score"] = report.raw_score
        out["score_stddev"] = report.score_stddev
    return out


@mcp.tool()
async def grade_with_simplejudge(
    rubric_path: str,
    repo_dir: str,
    paper_path: str = "",
    paper_text: str = "",
    judge_model: str = "",
    n_runs: int = 0,
    skip_negative_control: bool = False,
    code_only: bool = False,
) -> dict:
    """Grade one verified reproduction and persist all scientific evidence."""

    started = time.monotonic()
    if not judge_model:
        judge_model = _judge_model()
    if not n_runs:
        n_runs = int(os.environ.get("ARI_JUDGE_N_RUNS") or 1)
    n_runs = int(n_runs)
    paper_md = _load_paper_text(paper_path, paper_text)
    try:
        loaded_rubric = load_rubric(rubric_path, paper_text=paper_md)
    except RubricContractError as exc:
        return {"error": f"rubric contract rejected: {exc}"}
    rubric = loaded_rubric.document
    rubric_digest = "sha256:" + str(rubric["rubric_sha256"])
    paper_digest = bytes_digest(paper_md.encode("utf-8"))
    judge = _judge_identity(judge_model)
    independence = (
        "independent-model"
        if _models_are_independent(rubric, judge_model)
        else "not-independent"
    )
    fallback_base = Path(rubric_path).resolve(strict=True).parent
    reproduction_source = False
    run = None
    executed_work = None
    resolution_error = ""
    repo = Path(repo_dir)
    if not repo.is_dir():
        resolution_error = f"repo_dir not present: {repo_dir}"
    else:
        try:
            resolved = _resolve_grade_reproduction(repo)
            if resolved is None:
                resolution_error = "no verified ReproductionRunV1 is available"
            else:
                fallback_base, run, executed_work = resolved
                reproduction_source = True
        except (ReproductionContractError, ValueError, OSError) as exc:
            resolution_error = f"reproduction record rejected: {exc}"
    grade_root = _allocate_grade_root(
        fallback_base, reproduction_source=reproduction_source
    )
    calls_root = grade_root / "calls"
    calls_root.mkdir(mode=0o700)

    def failed_report(
        errors: list[str],
        *,
        completed_runs: list | None = None,
        negative_control: NegativeControlV1 | None = None,
    ) -> dict:
        completed_runs = completed_runs or []
        leaves = _persist_leaf_evidence(
            runs=completed_runs,
            grade_root=grade_root,
            artifact_base=fallback_base,
            verification=_rubric_verification_map(rubric),
        )
        report = GradeReportV1.create(
            rubric_schema_version=loaded_rubric.schema_version,
            rubric_digest=rubric_digest,
            paper_digest=paper_digest,
            reproduction_run_digest=run.run_digest if run is not None else None,
            reproduction_status=run.status if run is not None else "unavailable",
            judge=judge,
            independence_status=independence,
            n_runs_requested=max(1, min(100, n_runs)),
            n_runs_completed=len(completed_runs),
            status="failed",
            ors_score=None,
            raw_score=None,
            score_stddev=None,
            leaves=leaves,
            negative_control=negative_control
            or NegativeControlV1(
                status="unavailable", error="grading did not reach controls"
            ),
            call_artifacts=_collect_call_artifacts(
                calls_root, artifact_base=fallback_base
            ),
            errors=tuple(error[:4096] for error in errors),
        )
        report_path = _save_grade_report(grade_root, report)
        return _grade_response(
            report,
            report_path,
            elapsed_sec=round(time.monotonic() - started, 3),
            code_only=code_only,
        )

    expected_paper_digest = "sha256:" + str(rubric["paper_sha256"])
    if not paper_md or paper_digest != expected_paper_digest:
        return failed_report(
            ["paper text is required and must match the rubric paper digest"]
        )
    if n_runs < 1 or n_runs > 100:
        return failed_report(["n_runs must be between 1 and 100"])
    if resolution_error:
        return failed_report([resolution_error])
    assert run is not None and executed_work is not None
    if run.status != "succeeded":
        return failed_report(
            [f"reproduction status is {run.status}; only succeeded runs are gradable"]
        )

    submission = grade_root / "submission"
    try:
        source_manifest = tree_manifest(executed_work)
        if canonical_digest(source_manifest) != run.attempts[-1].output_tree_digest:
            selected = next(
                attempt
                for attempt in run.attempts
                if attempt.attempt_id == run.selected_attempt_id
            )
            if canonical_digest(source_manifest) != selected.output_tree_digest:
                raise ReproductionContractError(
                    "selected reproduction output digest differs"
                )
        shutil.copytree(executed_work, submission, symlinks=False)
        copied_manifest = tree_manifest(submission)
        if canonical_digest(copied_manifest) != canonical_digest(source_manifest):
            raise ReproductionContractError("grading snapshot differs from execution")
        _atomic_grade_json(
            grade_root / "submission-manifest.json",
            {
                "schema_version": "ari.grading-submission-manifest/v1",
                "reproduction_run_digest": run.run_digest,
                "tree_digest": canonical_digest(copied_manifest),
                "files": copied_manifest,
            },
        )
    except (ReproductionContractError, OSError, ValueError) as exc:
        return failed_report([f"cannot create grading snapshot: {exc}"])

    from _paperbench_bridge import (
        aggregate_graded_tree,
        average_graded_runs,
        task_node_from_dict,
    )

    pb_taskroot = task_node_from_dict(_strip_to_paperbench_format(rubric))
    reproduce_log_path = submission / "reproduce.log"
    reproduce_log = (
        _read_log_tail(reproduce_log_path) if reproduce_log_path.is_file() else ""
    )
    runs: list = []
    try:
        for index in range(1, n_runs + 1):
            runs.append(
                await _grade_once(
                    pb_taskroot,
                    paper_md,
                    submission,
                    reproduce_log,
                    judge_model,
                    code_only=code_only,
                    trace_dir=calls_root / f"main-run-{index:04d}",
                )
            )
    except Exception as exc:
        return failed_report(
            [f"judge run {len(runs) + 1} failed: {exc}"], completed_runs=runs
        )

    invalid_leaves = [
        str(leaf.id)
        for graded in runs
        for leaf in _walk_graded_leaves(graded)
        if not bool(getattr(leaf, "valid_score", False))
    ]
    if invalid_leaves:
        return failed_report(
            ["judge returned invalid scores for leaves: " + ", ".join(invalid_leaves)],
            completed_runs=runs,
        )

    aggregate = (
        aggregate_graded_tree(runs[0])
        if n_runs == 1
        else average_graded_runs(runs)
    )
    root_scores = [float(aggregate_graded_tree(item)["ors_score"]) for item in runs]
    negative_control: NegativeControlV1
    if skip_negative_control:
        negative_control = NegativeControlV1(
            status="unavailable",
            error="negative controls were explicitly skipped",
        )
    else:
        try:
            control = await _negative_control_check(
                pb_taskroot,
                paper_md,
                judge_model,
                code_only=code_only,
                trace_dir=calls_root / "negative-controls",
            )
            negative_control = NegativeControlV1(
                status="passed" if control["passed"] else "failed",
                empty_score=float(control["empty"]),
                boilerplate_score=float(control["boilerplate"]),
            )
        except Exception as exc:
            negative_control = NegativeControlV1(
                status="unavailable", error=str(exc)[:4096]
            )
            return failed_report(
                [f"negative-control grading failed: {exc}"],
                completed_runs=runs,
                negative_control=negative_control,
            )

    leaves = _persist_leaf_evidence(
        runs=runs,
        grade_root=grade_root,
        artifact_base=fallback_base,
        verification=_rubric_verification_map(rubric),
    )
    report_status = (
        "valid" if negative_control.status == "passed" else "invalid-negative-control"
    )
    report = GradeReportV1.create(
        rubric_schema_version=loaded_rubric.schema_version,
        rubric_digest=rubric_digest,
        paper_digest=paper_digest,
        reproduction_run_digest=run.run_digest,
        reproduction_status=run.status,
        judge=judge,
        independence_status=independence,
        n_runs_requested=n_runs,
        n_runs_completed=len(runs),
        status=report_status,
        ors_score=float(aggregate["ors_score"]),
        raw_score=float(aggregate["raw_score"]),
        score_stddev=statistics.pstdev(root_scores) if len(root_scores) > 1 else 0.0,
        leaves=leaves,
        negative_control=negative_control,
        call_artifacts=_collect_call_artifacts(
            calls_root, artifact_base=fallback_base
        ),
        errors=(),
    )
    report_path = _save_grade_report(grade_root, report)
    return _grade_response(
        report,
        report_path,
        elapsed_sec=round(time.monotonic() - started, 3),
        code_only=code_only,
    )


def _strip_to_paperbench_format(rubric: dict) -> dict:
    """Compatibility wrapper around the shared consumer-side conversion."""

    return to_paperbench_format(rubric)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
