"""Background worker for the PaperBench Wizard.

v0.7.4 wiring: when the Wizard POSTs to ``/api/paperbench/run``,
:func:`start_paperbench_job` spawns a daemon thread per (paper_id, job_id)
that drives the four PaperBench skill tools in sequence:

    1. ``generate_rubric``        (ari-skill-replicate)
    2. ``build_reproduce_sh``     (ari-skill-paper-re)
    3. ``run_reproduce``          (ari-skill-paper-re)
    4. ``grade_with_simplejudge`` (ari-skill-paper-re)

The thread owns a process-wide :class:`MCPClient` singleton that pools
stdio connections to the two skill servers, so the first launch pays the
subprocess start-up cost (~seconds) once and subsequent jobs reuse it.

Each stage's args are derived from the three Wizard config dicts. Sentinel
values (``0`` / ``""``) pass through to the skill tools, which resolve
them to environment-variable defaults — matching the ``workflow.yaml``
contract so we stay consistent with the CLI execution path.

Status / progress / per-stage logs flow back to the in-memory ``_JOBS``
entry via the same helpers the rest of ``api_paperbench`` uses
(``_set_job_field`` and ``append_job_log``); the SSE log endpoint and the
``/api/paperbench/run/<job_id>`` polling endpoint therefore see updates
without any further wiring.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_CLIENT_LOCK = threading.Lock()
_CLIENT: Any = None  # MCPClient — typed lazily so test envs without skills can still import


def _get_client() -> Any:
    """Lazily build a process-wide MCPClient bound to the two PaperBench skills.

    Auto-discovery is via ``ari.config._discover_skills`` (same mechanism the
    workflow runner uses); we filter to ``ari-skill-replicate`` and
    ``ari-skill-paper-re``. If either skill is missing from disk, raise so
    the caller can mark the job as failed rather than silently hanging.
    """
    global _CLIENT
    with _CLIENT_LOCK:
        if _CLIENT is not None:
            return _CLIENT
        from ari.config import _discover_skills
        from ari.mcp.client import MCPClient

        wanted = {"ari-skill-replicate", "ari-skill-paper-re"}
        skills = [s for s in _discover_skills() if s.name in wanted]
        missing = wanted - {s.name for s in skills}
        if missing:
            raise RuntimeError(
                f"PaperBench worker requires skills {sorted(wanted)}; "
                f"missing on disk: {sorted(missing)}"
            )
        _CLIENT = MCPClient(skills)
        return _CLIENT


def _parse_result(raw: dict) -> dict:
    """Decode MCPClient's ``{"result": "<json>"}`` envelope into the tool's dict.

    The MCPClient returns either ``{"error": "..."}`` (transport / not-found /
    retries exhausted) or ``{"result": "<text>"}`` where text is the JSON
    serialization of the skill tool's return dict. We unify the two so
    downstream code can treat ``error`` consistently regardless of layer.
    """
    if "error" in raw:
        return {"error": raw["error"]}
    text = raw.get("result")
    if not isinstance(text, str) or not text:
        return {"error": "skill tool returned empty body"}
    try:
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            return {"error": f"skill tool returned non-object: {type(parsed).__name__}"}
        return parsed
    except json.JSONDecodeError as e:
        return {"error": f"could not decode skill response: {e}"}


def _generate_rubric_args(paper_pdf: Path, rubric_path: Path, cfg: dict) -> dict:
    return {
        "paper_path": str(paper_pdf),
        "output_path": str(rubric_path),
        "model": cfg.get("model") or "",
        "two_stage": bool(cfg.get("two_stage", True)),
        "target_leaf_count": int(cfg.get("target_leaf_count") or 0),
        "temperature": float(cfg.get("temperature") or 0.0),
    }


def _build_reproduce_args(paper_pdf: Path, rubric_path: Path, repro_dir: Path, cfg: dict) -> dict:
    # ``container_image`` is the wizard's unified field; ``apptainer_image`` is
    # the legacy Stage 1-only alias still accepted for back-compat.
    img = str(cfg.get("container_image") or cfg.get("apptainer_image") or "")
    return {
        "paper_path": str(paper_pdf),
        "rubric_path": str(rubric_path),
        "output_dir": str(repro_dir),
        "model": cfg.get("model") or "",
        "time_limit_sec": int(cfg.get("time_limit_sec") or 0),
        "iterative_agent": bool(cfg.get("iterative_agent", False)),
        "sandbox_kind": str(cfg.get("sandbox_kind") or "auto"),
        "container_image": img,
        "apptainer_image": img,  # back-compat for callers still reading this key
        "max_steps": int(cfg.get("max_steps") or 0),
    }


def _run_reproduce_args(rubric_path: Path, repro_dir: Path, cfg: dict) -> dict:
    return {
        "rubric_path": str(rubric_path),
        "repo_dir": str(repro_dir),
        "sandbox_kind": str(cfg.get("sandbox_kind") or ""),
        "container_image": str(cfg.get("container_image") or ""),
        "partition": str(cfg.get("partition") or ""),
        "nodes": int(cfg.get("nodes") or 0),
        "ntasks": int(cfg.get("ntasks") or 0),
        "ntasks_per_node": int(cfg.get("ntasks_per_node") or 0),
        "exclusive": bool(cfg.get("exclusive", False)),
        "gpus_per_task": int(cfg.get("gpus_per_task") or 0),
        "gpu_type": str(cfg.get("gpu_type") or ""),
        "memory_gb_per_node": int(cfg.get("memory_gb_per_node") or 0),
        "constraint": str(cfg.get("constraint") or ""),
        "cpu_bind": str(cfg.get("cpu_bind") or ""),
        "mem_bind": str(cfg.get("mem_bind") or ""),
        "hint": str(cfg.get("hint") or ""),
        "nodelist": str(cfg.get("nodelist") or ""),
        "extra_sbatch_args": list(cfg.get("extra_sbatch_args") or []),
    }


def _grade_args(paper_pdf: Path, rubric_path: Path, repro_dir: Path, cfg: dict) -> dict:
    # Wizard stores the judge model under ``model``; the skill tool expects
    # ``judge_model``. Translate at this boundary.
    # ``code_only`` is wizard-overridable but the MCP tool auto-enables it
    # when no reproduce.log is present, so leaving it unset is usually fine.
    return {
        "rubric_path": str(rubric_path),
        "repo_dir": str(repro_dir),
        "paper_path": str(paper_pdf),
        "judge_model": str(cfg.get("model") or ""),
        "n_runs": int(cfg.get("n_runs") or 0),
        "skip_negative_control": bool(cfg.get("skip_negative_control", False)),
        "code_only": bool(cfg.get("code_only", False)),
    }


_STAGE_PROGRESS = {
    "rubric": 0.05,
    "reproduce_build": 0.25,
    "reproduce_run": 0.55,
    "grade": 0.85,
}


def _run_pipeline(job_id: str, paper_dir: Path, configs: dict, client_factory: Any) -> None:
    """Drive the four-stage pipeline; updates _JOBS[job_id] as it goes.

    ``client_factory`` is the callable returning the MCPClient. Tests inject a
    fake to avoid spawning real skill subprocesses.
    """
    # Imported lazily so the module is importable without the rest of ari.viz
    # (helps when running unit tests that monkey-patch these helpers).
    from .api_paperbench import _set_job_field, append_job_log

    rubric_cfg = dict(configs.get("rubric") or {})
    reproduce_cfg = dict(configs.get("reproduce") or {})
    judge_cfg = dict(configs.get("judge") or {})

    paper_pdf = paper_dir / "paper.pdf"
    if not paper_pdf.is_file():
        msg = f"paper.pdf missing under {paper_dir}; cannot launch PaperBench"
        _set_job_field(job_id, status="failed", error=msg)
        append_job_log(job_id, msg, level="error")
        return

    run_dir = paper_dir / "runs" / job_id
    run_dir.mkdir(parents=True, exist_ok=True)
    rubric_path = run_dir / "rubric.json"
    repro_dir = run_dir / "repro_sandbox"
    repro_dir.mkdir(parents=True, exist_ok=True)

    try:
        client = client_factory()
    except Exception as e:
        _set_job_field(job_id, status="failed", error=f"skill bootstrap failed: {e}")
        append_job_log(job_id, f"skill bootstrap failed: {e}", level="error")
        return

    def _stage(name: str, tool: str, args: dict, *, fatal: bool = True) -> dict | None:
        """Run one stage; on error mark job failed and return None when fatal."""
        _set_job_field(job_id, status="running", current_stage=name,
                       progress=_STAGE_PROGRESS[name])
        append_job_log(job_id, f"stage {name}: {tool} starting", level="info")
        try:
            raw = client.call_tool(tool, args)
        except Exception as e:
            msg = f"{tool} raised {type(e).__name__}: {e}"
            log.exception("PaperBench worker: %s", msg)
            if fatal:
                _set_job_field(job_id, status="failed", current_stage=name, error=msg)
                append_job_log(job_id, msg, level="error")
                return None
            append_job_log(job_id, msg, level="warning")
            return {"error": msg}
        result = _parse_result(raw)
        if "error" in result:
            msg = f"{tool}: {result['error']}"
            if fatal:
                _set_job_field(job_id, status="failed", current_stage=name, error=msg)
                append_job_log(job_id, msg, level="error")
                return None
            append_job_log(job_id, msg, level="warning")
        else:
            append_job_log(job_id, f"stage {name}: {tool} ok", level="success")
        return result

    rubric_res = _stage("rubric", "generate_rubric",
                        _generate_rubric_args(paper_pdf, rubric_path, rubric_cfg))
    if rubric_res is None or "error" in rubric_res:
        return

    build_res = _stage("reproduce_build", "build_reproduce_sh",
                       _build_reproduce_args(paper_pdf, rubric_path, repro_dir, reproduce_cfg))
    if build_res is None or "error" in build_res:
        return

    # Phase 1 (run_reproduce) failures degrade rather than abort — Phase 2
    # SimpleJudge is designed to score against an empty/partial sandbox and
    # report the negative-control delta, which is itself useful signal.
    run_res = _stage("reproduce_run", "run_reproduce",
                     _run_reproduce_args(rubric_path, repro_dir, reproduce_cfg),
                     fatal=False) or {}

    grade_res = _stage("grade", "grade_with_simplejudge",
                       _grade_args(paper_pdf, rubric_path, repro_dir, judge_cfg))
    if grade_res is None or "error" in grade_res:
        return

    # Read the rubric envelope back so ResultsView can render the tree
    # (the on-disk file is the authoritative copy; rubric_res is the
    # generator's manifest with sha256 / leaves_count metadata).
    rubric_envelope: dict | None = None
    try:
        rubric_envelope = json.loads(rubric_path.read_text())
    except Exception as e:  # pragma: no cover — best-effort
        log.warning("PaperBench worker: cannot reload rubric envelope: %s", e)

    _set_job_field(
        job_id,
        status="completed",
        current_stage="grade",
        progress=1.0,
        results={
            "rubric_manifest": rubric_res,
            "reproduce_build": build_res,
            "reproduce_run": run_res,
            "grade": grade_res,
            "rubric_path": str(rubric_path),
            "repo_dir": str(repro_dir),
            # Top-level keys ResultsView (frontend) consumes — keep names
            # aligned with results/ResultsView.tsx, not with the skill tool
            # response shape.
            "ors_score": grade_res.get("ors_score"),
            "leaves": grade_res.get("leaf_grades"),
            "rubric": (rubric_envelope or {}).get("rubric"),
            "negative_control": grade_res.get("negative_control_check"),
        },
    )
    append_job_log(
        job_id,
        f"pipeline complete (ors_score={grade_res.get('ors_score')})",
        level="success",
    )


def start_paperbench_job(
    job_id: str,
    paper_dir: Path,
    configs: dict,
    *,
    client_factory: Any = None,
) -> threading.Thread | None:
    """Launch a daemon thread that runs the four-stage pipeline.

    ``client_factory`` defaults to the singleton MCPClient builder; tests pass
    a fake. Returns the thread so tests can ``join()`` deterministically.

    The ``ARI_PAPERBENCH_WORKER_DISABLED=1`` env var is the opt-out tests use
    to preserve the pre-wiring "stay in queued" behaviour while still
    exercising _api_launch_run paths. It only gates the default-factory
    case; passing an explicit ``client_factory`` always runs (so the
    worker-specific tests can drive a stubbed pipeline even with the env
    var set globally).
    """
    if client_factory is None and os.environ.get("ARI_PAPERBENCH_WORKER_DISABLED") == "1":
        log.info("PaperBench worker disabled via env (job_id=%s)", job_id)
        return None
    factory = client_factory or _get_client
    t = threading.Thread(
        target=_run_pipeline,
        args=(job_id, paper_dir, configs, factory),
        daemon=True,
        name=f"paperbench-{job_id[:8]}",
    )
    t.start()
    return t
