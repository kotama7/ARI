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
import subprocess
import tempfile
import time
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from ari.public import cost_tracker as _ari_cost_tracker
from ari.public.clone import CloneError, clone
from ari_skill_hpc import (
    ArtifactPinV1,
    EnvironmentPolicyV1,
    JobRequestV1,
    LocalCommandRunner,
    ResourceRequestV1,
    SchedulerError,
    SlurmScheduler,
    SubmissionLedger,
    file_digest,
    sha256_digest,
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

    dest_path = Path(dest)
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
    apptainer_image: str = "",
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
            ``sandbox_kind=apptainer`` this is the SIF path or
            ``docker://...`` URI. For ``local`` / ``slurm`` the value is
            ignored (the agent runs on the host filesystem). When empty,
            the legacy ``apptainer_image`` arg is consulted, then
            env ``ARI_PHASE1_APPTAINER_IMAGE`` /
            ``ARI_PHASE1_SINGULARITY_IMAGE``.
        apptainer_image: deprecated alias of ``container_image``; kept for
            back-compat with workflow YAMLs that still set it.
        overwrite: when False (default) and ``output_dir/reproduce.sh`` is
            already present, no rollout is performed — returns
            ``populated=False, skipped_reason=...``.

    Returns the populated flag, written file list, expected_artifacts seen,
    max_runtime_sec, model id, and warnings (or ``error`` on failure).
    """
    if not output_dir:
        return {"populated": False, "error": "output_dir is required"}

    out = Path(output_dir)
    if (out / "reproduce.sh").is_file() and not overwrite:
        return {
            "populated": False,
            "skipped_reason": (
                f"reproduce.sh already present at {out / 'reproduce.sh'}; "
                f"pass overwrite=True to regenerate"
            ),
            "output_dir": str(out),
        }

    text = _load_paper_text(paper_path, paper_text)
    if not text:
        return {"populated": False, "error": "No paper text provided"}

    expected_artifacts: list[str] = []
    execution_profile: dict = {}
    if rubric_path:
        try:
            rubric = json.loads(Path(rubric_path).read_text())
            rc = rubric.get("reproduce_contract") or {}
            expected_artifacts = list(rc.get("expected_artifacts") or [])
            execution_profile = dict(rc.get("execution_profile") or {})
        except Exception as e:
            log.warning("build_reproduce_sh: cannot read rubric %s: %s", rubric_path, e)

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

    # container_image (wizard) takes precedence over the deprecated
    # apptainer_image alias.
    resolved_image = container_image or apptainer_image or ""

    return await run_replicator_agent(
        paper_md_path=str(paper_md),
        output_dir=str(out),
        expected_artifacts=expected_artifacts,
        execution_profile=execution_profile,
        time_limit_sec=int(time_limit_sec),
        iterative_agent=bool(iterative_agent),
        max_steps=int(max_steps) or None,
        completer_config=completer_config,
        sandbox_kind=sandbox_kind,
        apptainer_image=resolved_image or None,
    )


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


def _run_reproduce_local(repo_dir: Path, log_path: Path, timeout: int) -> dict:
    """Execute reproduce.sh in-place (no sandbox). Used as a fallback."""
    script = repo_dir / "reproduce.sh"
    if not script.is_file():
        return {"executed": False, "exit_code": None, "error": "reproduce.sh missing"}
    try:
        script.chmod(script.stat().st_mode | 0o111)
    except Exception:
        pass
    start = time.time()
    with log_path.open("wb") as logf:
        try:
            proc = subprocess.run(
                ["bash", str(script)],
                cwd=str(repo_dir),
                stdout=logf,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                check=False,
            )
            return {
                "executed": True,
                "exit_code": int(proc.returncode),
                "elapsed_sec": round(time.time() - start, 2),
            }
        except subprocess.TimeoutExpired:
            return {
                "executed": True,
                "exit_code": None,
                "timed_out": True,
                "elapsed_sec": round(time.time() - start, 2),
            }


def _run_reproduce_apptainer(
    repo_dir: Path, log_path: Path, timeout: int, *,
    runner: str = "apptainer", image: str = "",
) -> dict:
    """Execute reproduce.sh in an Apptainer/Singularity container.

    Image resolution (priority order):
      1. Explicit ``image`` arg (wizard ``container_image`` field).
      2. ``ARI_PHASE1_APPTAINER_IMAGE`` / ``ARI_PHASE1_SINGULARITY_IMAGE``
         (file:// path or library://, docker://, shub:// URI accepted by
         ``apptainer exec``).
      3. Default: ``docker://ubuntu:24.04`` — Apptainer/Singularity can pull
         and execute a docker image directly without a Docker daemon.

    Falls back to local if the binary is missing.
    """
    if not _has_bin(runner):
        if os.environ.get("ARI_PHASE1_ALLOW_FALLBACK", "") == "1":
            log.warning(
                "%s not on PATH; ARI_PHASE1_ALLOW_FALLBACK=1 → falling back "
                "to local reproduce",
                runner,
            )
            return _run_reproduce_local(repo_dir, log_path, timeout)
        raise RuntimeError(
            f"sandbox_kind={runner!r} requested but {runner!r} is not on "
            f"PATH. Refusing to silently fall back to local host execution. "
            f"Either install {runner}, pick a different sandbox_kind, or "
            f"set ARI_PHASE1_ALLOW_FALLBACK=1 to opt in to the legacy "
            f"silent-fallback behaviour."
        )
    image = (
        image
        or os.environ.get("ARI_PHASE1_APPTAINER_IMAGE")
        or os.environ.get("ARI_PHASE1_SINGULARITY_IMAGE")
        or "docker://ubuntu:24.04"
    )
    cmd = [
        runner, "exec",
        "--bind", f"{repo_dir}:{repo_dir}",
        "--pwd", str(repo_dir),
        "--no-home",
        image,
        "bash", "-c", "chmod +x reproduce.sh && ./reproduce.sh",
    ]
    start = time.time()
    with log_path.open("wb") as logf:
        try:
            proc = subprocess.run(
                cmd, stdout=logf, stderr=subprocess.STDOUT,
                timeout=timeout, check=False,
            )
            return {
                "executed": True,
                "exit_code": int(proc.returncode),
                "elapsed_sec": round(time.time() - start, 2),
            }
        except subprocess.TimeoutExpired:
            return {
                "executed": True,
                "exit_code": None,
                "timed_out": True,
                "elapsed_sec": round(time.time() - start, 2),
            }


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


async def _run_reproduce_slurm(
    repo_dir: Path,
    log_path: Path,
    timeout: int,
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
) -> dict:
    """Run reproduce.sh through the canonical typed SLURM lifecycle."""
    if not _has_bin("sbatch"):
        if os.environ.get("ARI_PHASE1_ALLOW_FALLBACK", "") == "1":
            log.warning(
                "sbatch not on PATH; ARI_PHASE1_ALLOW_FALLBACK=1 -> local fallback"
            )
            return _run_reproduce_local(repo_dir, log_path, timeout)
        raise RuntimeError(
            "sandbox_kind=slurm requested but sbatch is not on PATH. "
            "Refusing to silently fall back to local execution."
        )

    resolved_partition = _resolve_partition_for_repo(repo_dir, partition)
    if not resolved_partition:
        if os.environ.get("ARI_PHASE1_ALLOW_FALLBACK", "") == "1":
            log.warning(
                "no SLURM partition resolved; ARI_PHASE1_ALLOW_FALLBACK=1 "
                "-> local fallback"
            )
            return _run_reproduce_local(repo_dir, log_path, timeout)
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
        resolved_script = script.resolve(strict=True)
        input_pin = ArtifactPinV1(
            logical_name="reproduce-script",
            path=str(resolved_script),
            digest=file_digest(resolved_script),
            size_bytes=resolved_script.stat().st_size,
            media_type="text/x-shellscript",
        )
        identity = sha256_digest(
            {
                "script": input_pin.digest,
                "resources": resources.model_dump(mode="json"),
                "modules": list(module_loads),
            }
        )
        request = JobRequestV1(
            request_id="paper-re-" + identity.removeprefix("sha256:")[:24],
            job_name="ari-ors",
            work_dir=str(repo_dir.resolve(strict=True)),
            argv=("/bin/bash", str(resolved_script)),
            resources=resources,
            environment=EnvironmentPolicyV1(modules=module_loads),
            inputs=(input_pin,),
            metadata={"domain": "paper-re", "timeout_sec": timeout},
        )
        scheduler = _paper_re_scheduler(repo_dir)
        handle = await scheduler.submit(request)
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
                }
            await asyncio.sleep(min(5.0, remaining))
        job_logs = await scheduler.logs(handle.handle_id)
        _materialize_scheduler_log(log_path, job_logs)
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
    }
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


def _run_reproduce_docker(
    repo_dir: Path, log_path: Path, timeout: int, *, image: str = "",
) -> dict:
    """Execute reproduce.sh in a docker sandbox.

    Image priority: explicit ``image`` arg (from wizard ``container_image``) →
    env ``ARI_PHASE1_DOCKER_IMAGE`` → hardcoded ``ubuntu:24.04``.

    When the docker daemon is unreachable, raises ``RuntimeError`` (the user
    explicitly picked ``sandbox_kind=docker`` and a silent fallback to local
    would defeat the isolation intent). Set ``ARI_PHASE1_ALLOW_FALLBACK=1``
    to opt back into the legacy silent-fallback-to-local behaviour.
    """
    if not _docker_works():
        if os.environ.get("ARI_PHASE1_ALLOW_FALLBACK", "") == "1":
            log.warning(
                "docker daemon not usable; ARI_PHASE1_ALLOW_FALLBACK=1 → "
                "falling back to local reproduce"
            )
            return _run_reproduce_local(repo_dir, log_path, timeout)
        raise RuntimeError(
            "sandbox_kind=docker requested but docker daemon is not "
            "reachable (`docker info` failed). Refusing to silently fall "
            "back to local host execution. Either start the docker daemon, "
            "pick a different sandbox_kind, or set "
            "ARI_PHASE1_ALLOW_FALLBACK=1 to opt in to the legacy "
            "silent-fallback behaviour."
        )
    image = image or os.environ.get("ARI_PHASE1_DOCKER_IMAGE", "ubuntu:24.04")
    cmd = [
        "docker", "run", "--rm",
        "-v", f"{repo_dir}:/work",
        "-w", "/work",
        image,
        "bash", "-c", "chmod +x reproduce.sh && ./reproduce.sh",
    ]
    start = time.time()
    with log_path.open("wb") as logf:
        try:
            proc = subprocess.run(
                cmd, stdout=logf, stderr=subprocess.STDOUT,
                timeout=timeout, check=False,
            )
            return {
                "executed": True,
                "exit_code": int(proc.returncode),
                "elapsed_sec": round(time.time() - start, 2),
            }
        except subprocess.TimeoutExpired:
            return {
                "executed": True,
                "exit_code": None,
                "timed_out": True,
                "elapsed_sec": round(time.time() - start, 2),
            }


@mcp.tool()
async def run_reproduce(
    rubric_path: str,
    repo_dir: str,
    sandbox_kind: str = "",
    container_image: str = "",
    timeout_global_sec: int = 0,
    partition: str = "",
    cpus: int = 0,
    walltime: str = "",
    # ── 配置・並列度 (v0.7.2) ──
    nodes: int = 0,
    ntasks: int = 0,
    ntasks_per_node: int = 0,
    nodelist: str = "",
    exclude_nodes: str = "",
    # ── 排他性 ──
    exclusive: bool = False,
    # ── GPU ──
    gpus_per_task: int = 0,
    gpus_per_node: int = 0,
    gpu_type: str = "",
    # ── メモリ ──
    memory_gb_per_node: int = 0,
    memory_gb_per_cpu: int = 0,
    # ── HW / NUMA ──
    constraint: str = "",
    cpu_bind: str = "",
    mem_bind: str = "",
    hint: str = "",
    account: str = "",
    qos: str = "",
    reservation: str = "",
    module_loads: list[str] | None = None,
    # Deprecated typed-translation shim; arbitrary flags are rejected.
    extra_sbatch_args: list[str] | None = None,
) -> dict:
    """Phase 1: execute reproduce.sh in a sandbox; capture log + artifact list.

    SLURM execution is submitted as a versioned JobRequestV1 and observed via
    submit/status/logs/cancel handles. The rubric's execution_profile fills
    caller fields left at their defaults; explicit caller values win.

    Args:
        rubric_path: path to the frozen rubric JSON envelope (provides
            ``reproduce_contract.max_runtime_sec``,
            ``reproduce_contract.expected_artifacts``, and the optional
            ``reproduce_contract.execution_profile``).
        repo_dir: candidate submission directory (must contain ``reproduce.sh``).
        sandbox_kind: ``docker`` | ``apptainer`` | ``singularity`` | ``slurm``
            | ``local`` | ``auto``. Default reads ``ARI_PHASE1_SANDBOX``
            (then ``auto``). ``auto`` priority: slurm (when sbatch + partition
            present) → docker (when daemon usable and not on HPC) → apptainer
            → singularity → local.
        timeout_global_sec: 0 → use the rubric's ``max_runtime_sec``.
        partition: SLURM ``--partition``. Defaults to ``ARI_SLURM_PARTITION``
            env then to ``{checkpoint_dir}/launch_config.json::partition``.
        cpus: SLURM ``--cpus-per-task``. Defaults to ``ARI_SLURM_CPUS=8``.
        walltime: SLURM ``--time`` (HH:MM:SS). Defaults to
            ``ARI_SLURM_WALLTIME`` then to a value derived from
            ``timeout_global_sec``.
        nodes / ntasks / ntasks_per_node: ``--nodes`` / ``--ntasks`` /
            ``--ntasks-per-node``. 0 = leave to SLURM.
        nodelist / exclude_nodes: ``--nodelist=...`` / ``--exclude=...``.
        exclusive: ``--exclusive`` (no other jobs share the allocated
            nodes — essential for faithful performance reproduction).
        gpus_per_task / gpus_per_node: ``--gpus-per-task=N`` /
            ``--gpus-per-node=N``.
        gpu_type: typed GPU request. The requested count and type are never
            silently dropped or downgraded.
        memory_gb_per_node / memory_gb_per_cpu: ``--mem=NG`` /
            ``--mem-per-cpu=NG``.
        constraint: ``--constraint=...`` (e.g. ``"skylake"``,
            ``"haswell|broadwell"``).
        cpu_bind / mem_bind: rejected at this boundary because they are srun
            job-step settings; put them explicitly in reproduce.sh.
        hint / account / qos / reservation: typed SLURM resource selectors.
        module_loads: reviewed module names loaded by the generated job script.
        extra_sbatch_args: deprecated compatibility input. Only account, qos,
            reservation, and hint assignments are translated; all others fail.

    Returns the executed flag, exit code, log path, produced artifact list,
    missing expected artifacts, elapsed time, and (when SLURM-dispatched)
    a snapshot of the chosen partition / nodes / ntasks / gpu spec.
    """
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
        }
    # rubric_path is the canonical source for ``max_runtime_sec`` /
    # ``expected_artifacts`` / ``execution_profile``, but the public
    # :func:`_paperbench_bridge.reproduce_submission` wrapper drives this
    # tool without a rubric — explicit caller args supply the same info.
    # Treat empty / missing rubric_path as "no hint dict; use caller args".
    rubric: dict = {}
    if rubric_path:
        try:
            rubric = json.loads(Path(rubric_path).read_text())
        except Exception as e:
            return {"executed": False, "error": f"cannot read rubric: {e}"}

    rc = rubric.get("reproduce_contract") or {}
    max_runtime = int(timeout_global_sec or rc.get("max_runtime_sec") or 21600)
    expected = list(rc.get("expected_artifacts") or [])
    exec_profile: dict = dict(rc.get("execution_profile") or {})
    requested = (sandbox_kind or _phase1_sandbox_kind()).lower()
    if requested == "auto":
        requested = _phase1_sandbox_kind()
    kind = requested

    # ── Auto-resolve SLURM args from execution_profile (rubric hint).
    # Explicit caller args always win — these only fill in fields the
    # caller left at the default zero/empty/False sentinel.
    resolved_nodes              = int(nodes)            or int(exec_profile.get("requested_nodes", 0) or 0)
    resolved_ntasks             = int(ntasks)           or int(exec_profile.get("min_ranks", 0) or 0)
    resolved_ntasks_per_node    = int(ntasks_per_node)  or int(exec_profile.get("ntasks_per_node", 0) or 0)
    resolved_nodelist           = nodelist              or (exec_profile.get("requested_nodelist") or "")
    resolved_exclude_nodes      = exclude_nodes         or (exec_profile.get("exclude_nodes") or "")
    resolved_exclusive          = bool(exclusive)       or bool(exec_profile.get("exclusive", False))
    resolved_gpus_per_task      = int(gpus_per_task)    or int(exec_profile.get("requested_gpus_per_task", 0) or 0)
    resolved_gpus_per_node      = int(gpus_per_node)    or int(exec_profile.get("requested_gpus_per_node", 0) or 0)
    resolved_gpu_type           = gpu_type              or (exec_profile.get("gpu_type") or "")
    resolved_mem_gb_node        = int(memory_gb_per_node) or int(exec_profile.get("memory_gb_per_node", 0) or 0)
    resolved_mem_gb_cpu         = int(memory_gb_per_cpu)  or int(exec_profile.get("memory_gb_per_cpu", 0) or 0)
    resolved_constraint         = constraint            or (exec_profile.get("constraint") or "")
    # Profile bindings are consumed by the replicator when it writes srun
    # steps inside reproduce.sh; they are not portable sbatch directives.
    resolved_cpu_bind           = cpu_bind
    resolved_mem_bind           = mem_bind
    resolved_hint               = hint                  or (exec_profile.get("hint") or "")
    resolved_account            = account               or (exec_profile.get("account") or "")
    resolved_qos                = qos                   or (exec_profile.get("qos") or "")
    resolved_reservation        = reservation           or (exec_profile.get("reservation") or "")
    resolved_modules            = tuple(module_loads or exec_profile.get("module_loads") or ())
    resolved_extra              = list(extra_sbatch_args or exec_profile.get("extra_sbatch_args") or [])

    log_path = repo / "reproduce.log"
    if kind == "docker":
        exec_res = _run_reproduce_docker(
            repo, log_path, max_runtime, image=container_image,
        )
    elif kind in ("local", ""):
        exec_res = _run_reproduce_local(repo, log_path, max_runtime)
    elif kind == "apptainer":
        exec_res = _run_reproduce_apptainer(
            repo, log_path, max_runtime, runner="apptainer", image=container_image,
        )
    elif kind == "singularity":
        exec_res = _run_reproduce_apptainer(
            repo, log_path, max_runtime, runner="singularity", image=container_image,
        )
    elif kind == "slurm":
        exec_res = await _run_reproduce_slurm(
            repo, log_path, max_runtime,
            partition=partition, cpus=int(cpus or 0), walltime=walltime,
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
            cpu_bind=resolved_cpu_bind,
            mem_bind=resolved_mem_bind,
            hint=resolved_hint,
            account=resolved_account,
            qos=resolved_qos,
            reservation=resolved_reservation,
            module_loads=resolved_modules,
            extra_sbatch_args=resolved_extra,
        )
    else:
        return {"executed": False, "error": f"unknown sandbox_kind: {kind}"}

    artifacts = []
    for f in repo.rglob("*"):
        if f.is_file():
            relative = f.relative_to(repo)
            if relative.parts and relative.parts[0] == ".ari-hpc":
                continue
            artifacts.append(str(relative))
    missing = [e for e in expected if e not in artifacts]

    out = {
        "executed": exec_res.get("executed", False),
        "exit_code": exec_res.get("exit_code"),
        "log_path": str(log_path),
        "artifacts": artifacts,
        "missing": missing,
        "elapsed_sec": exec_res.get("elapsed_sec", 0.0),
        "sandbox_kind": kind,
    }
    # SLURM-only metadata: partition / cpus / walltime / nodes / ntasks /
    # exclusive / gpu spec actually used. Everything is optional — keys
    # only present when the corresponding flag was emitted, which keeps the
    # legacy single-node response shape unchanged.
    for k in (
        "partition", "cpus", "walltime",
        "nodes", "ntasks", "exclusive", "gpu", "handle_id", "job_id",
        "request_digest", "timed_out",
    ):
        if k in exec_res:
            out[k] = exec_res[k]
    if "error" in exec_res:
        out["error"] = exec_res["error"]
    return out


async def _grade_once(
    pb_taskroot,
    paper_md: str,
    repo_dir: Path,
    reproduce_log: str,
    judge_model: str,
    code_only: bool = False,
):
    from _paperbench_bridge import judge_submission

    return await judge_submission(
        paper_md=paper_md,
        rubric=pb_taskroot,
        submission_dir=repo_dir,
        reproduce_log=reproduce_log,
        judge_model=judge_model,
        code_only=code_only,
    )


async def _negative_control_check(
    pb_taskroot,
    paper_md: str,
    judge_model: str,
    code_only: bool = False,
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
        )
        results["boilerplate"] = aggregate_graded_tree(graded)["ors_score"]
    results["passed"] = (results["empty"] < 0.05 and results["boilerplate"] < 0.05)
    return results


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
    """Phase 2: run PaperBench SimpleJudge against the (post-Phase-1) repo.

    ``n_runs=0`` (the workflow.yaml sentinel) resolves to
    ``ARI_JUDGE_N_RUNS`` env var, defaulting to 1 (PaperBench paper §4.1
    single-pass).
    ``judge_model=""`` resolves to ``ARI_MODEL_JUDGE`` env or
    :func:`_judge_model`.

    Workflow:
      1. Load rubric envelope, strip our metadata via ``to_paperbench_format``.
      2. Construct ``TaskNode`` tree.
      3. Run ``SimpleJudge.judge()`` for ``n_runs`` iterations.
      4. Average per-leaf scores (PaperBench weighted aggregation).
      5. Run a one-off negative control (empty + trivial reproduce.sh repo).
      6. Return result envelope.
    """
    if not n_runs:
        n_runs = int(os.environ.get("ARI_JUDGE_N_RUNS") or 1)
    if not judge_model:
        judge_model = _judge_model()
    from _paperbench_bridge import (
        aggregate_graded_tree,
        average_graded_runs,
        task_node_from_dict,
    )

    try:
        rubric = json.loads(Path(rubric_path).read_text())
    except Exception as e:
        return {"error": f"cannot read rubric: {e}"}

    pb_dict = _strip_to_paperbench_format(rubric)
    pb_taskroot = task_node_from_dict(pb_dict)

    paper_md = _load_paper_text(paper_path, paper_text)

    # If repo_dir is missing, degrade to scoring against an effectively empty
    # submission per workflow.yaml §"ORS auto-rubric reproducibility".
    repo = Path(repo_dir)
    _empty_submission_dir: tempfile.TemporaryDirectory | None = None
    degraded_reason = ""
    if not repo.is_dir():
        _empty_submission_dir = tempfile.TemporaryDirectory()
        repo = Path(_empty_submission_dir.name)
        degraded_reason = f"repo_dir not present: {repo_dir}"
    log_path = repo / "reproduce.log"
    reproduce_log = _read_log_tail(log_path) if log_path.is_file() else ""

    chosen_model = judge_model or _judge_model()
    n_runs = max(1, int(n_runs))

    # Auto-enable code_only when there is no reproduce.log to grade against
    # — Stage 1 instruction defaults to code_only=True
    # (`_compute/local_pbtask.py:166-175`), so the Stage 3 grader should
    # match that scope rather than penalising the agent for Code Execution
    # / Result Analysis leaves it was never asked to satisfy. Explicit
    # caller-supplied code_only=True always wins.
    if not code_only and not log_path.is_file():
        code_only = True

    try:
        start = time.time()
        runs = []
        for _ in range(n_runs):
            runs.append(await _grade_once(
                pb_taskroot, paper_md, repo, reproduce_log, chosen_model,
                code_only=code_only,
            ))
        if n_runs == 1:
            agg = aggregate_graded_tree(runs[0])
        else:
            agg = average_graded_runs(runs)

        out = {
            "rubric_sha256": rubric.get("rubric_sha256"),
            "ors_score": agg["ors_score"],
            "raw_score": agg["raw_score"],
            "leaf_grades": agg["leaf_grades"],
            "judge_model": chosen_model,
            "n_runs": n_runs,
            "code_only": code_only,
            "elapsed_sec": round(time.time() - start, 2),
        }
        if degraded_reason:
            out["degraded"] = True
            out["degraded_reason"] = degraded_reason
        if not skip_negative_control:
            out["negative_control_check"] = await _negative_control_check(
                pb_taskroot, paper_md, chosen_model,
                code_only=code_only,
            )
        return out
    finally:
        if _empty_submission_dir is not None:
            _empty_submission_dir.cleanup()


def _strip_to_paperbench_format(rubric: dict) -> dict:
    """Local copy of ari-skill-replicate.manifest.to_paperbench_format.

    Avoids a hard import from ari-skill-paper-re into ari-skill-replicate
    (each skill ships independently). The two implementations MUST stay in sync.
    """
    KEEP = {"id", "requirements", "weight", "sub_tasks",
            "task_category", "finegrained_task_category"}

    def strip(node: dict) -> dict:
        out: dict = {k: v for k, v in node.items() if k in KEEP}
        out["weight"] = int(node.get("weight", 1))
        out["sub_tasks"] = [strip(c) for c in (node.get("sub_tasks") or [])]
        return out

    root = rubric.get("rubric")
    if not isinstance(root, dict):
        raise ValueError("Rubric envelope missing 'rubric' root TaskNode")
    return strip(root)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
