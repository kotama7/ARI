#!/usr/bin/env python3
"""Pilot + sweep driver for the handoff study (Stage 4).

RUN ON A COMPUTE NODE with a GPU-served Ollama. This driver only sets the
per-arm env and shells out to the proven ``ari run``; it bakes in NO host /
partition / port (those come from your environment: OLLAMA_HOST, ARI_BACKEND,
SLURM allocation). See ari-core/PREREG_handoff_study.md and
ari-core/MASTER_PLAN_handoff_impl.md.

Examples (on a compute node, after starting Ollama and exporting OLLAMA_HOST):
    # 1) qwen3:8b validity-floor pilot (PREREG gate)
    python workspace/run_handoff_ablation.py --mode pilot --model qwen3:8b
    # 2) MVP 3-arm sweep on the large model, n independent runs per arm
    python workspace/run_handoff_ablation.py --mode mvp --large-model qwen3:32b --seeds 10
    # inspect the exact env+commands without running:
    python workspace/run_handoff_ablation.py --mode mvp --dry-run

For fx700 batch submission, use the matrix launcher. It submits one independent
Slurm array element per task, arm, and seed:
    bash workspace/submit_handoff_ablation_array.sh --smoke
    bash workspace/submit_handoff_ablation_array.sh --full
"""
from __future__ import annotations

import argparse
import datetime as _dt
import glob
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
# Make ``ari`` importable without relying on a site-packages install. On the login
# node the x86 .venv has ari installed, but a per-arch compute-node venv (e.g. the
# aarch64 fx700 venv) does not, so `import ari` died with ModuleNotFoundError before
# the driver could even list tasks. Same one-liner the analyzer uses.
sys.path.insert(0, str(REPO / "ari-core"))
# The deterministic task selects the harness: its measurement, its frozen
# scaffolding, its scoring scale and its goal statement. ARI ships none of these
# — every task is registered under $ARI_WORKSPACE/harnesses/<task>/ — so this
# driver asks the registry instead of naming tasks.


def _task_choices() -> list[str]:
    """The registered harnesses. A hardcoded ``choices=`` rejected a newly
    registered task before any of the wiring below could run."""
    from ari.harness_registry import available_tasks
    tasks = available_tasks()
    if not tasks:
        raise SystemExit(
            "no task harnesses are registered. Register one under "
            "$ARI_WORKSPACE/harnesses/<task>/ (see ari/harness_registry.py)."
        )
    return tasks


def _experiment_for(task: str) -> Path:
    """The goal statement the task is scored against — it ships with the harness,
    so the workspace carries the experiment and ARI carries only the framework."""
    from ari.harness_registry import workspace_harness_root
    exp = workspace_harness_root() / task / "experiment.md"
    if not exp.is_file():
        raise SystemExit(f"task {task!r}: harness ships no experiment.md at {exp}")
    return exp
# EVIDENCE / REFLECTION HANDOFF (3 arms):
#   code_only                    parent code/workspace only
#   evidence_only                + objective evaluator/harness evidence
#   evidence_plus_reflection     + the same evidence plus LLM self-reflection
# Full tool logs are deliberately OUT of the main experiment. They remain useful
# as prior pilot evidence that more text / more process trace is not necessarily
# better, but the new question is about information provenance, not log length.
# The confirmatory arm set. Prefer the explicit --arms CLI flag (resolved in
# main); ARI_HANDOFF_ARMS only overrides when --arms is absent, and main() warns
# LOUDLY if the effective set differs from this registered default — so a stale
# ambient ARI_HANDOFF_ARMS cannot silently change the DESIGN without a visible
# preflight warning. The arm set is the study's design, not a nuisance control.
_DEFAULT_ARMS = "code_only,evidence_only,evidence_plus_reflection"
# The single arm the validity-floor pilot runs (it is a floor check, not an
# ablation). Named once so the preflight message and the run agree.
_PILOT_ARM = "evidence_only"
ARMS = os.environ.get("ARI_HANDOFF_ARMS", _DEFAULT_ARMS).split(",")

# Files whose bytes define the registered experiment.  The launcher records one
# aggregate digest and every array worker verifies it before and after its run.
# Tracked runtime files are discovered from git; ignored experiment assets are
# named explicitly below.
_STUDY_EXTRA_FILES = (
    "workspace/run_handoff_ablation.py",
    "workspace/analyze_handoff_ablation.py",
    "workspace/submit_handoff_ablation_array.sh",
    "workspace/submit_handoff_ablation_sbatch.sh",
    "workspace/staging/fx700_smoke_config.yaml",
    "report_temp/paper_ja.tex",
)
_STUDY_TRACKED_PREFIXES = (
    "ari-core/ari/",
    "ari-core/config/",
    "ari-skill-coding/",
    "ari-skill-memory/",
)


def study_source_manifest() -> dict[str, str]:
    """Return content hashes for every file that can define this study.

    The repository is intentionally allowed to be dirty, but it must be
    byte-identical for all 270 workers.  Hashing only git's dirty patch is not
    enough because the ignored workspace harnesses and study scripts are part of
    the instrument.
    """
    paths: set[Path] = set()
    try:
        cp = subprocess.run(
            ["git", "-C", str(REPO), "ls-files", "-z"],
            capture_output=True,
            check=True,
        )
        for raw in cp.stdout.split(b"\0"):
            if not raw:
                continue
            relative = os.fsdecode(raw)
            if relative.startswith(_STUDY_TRACKED_PREFIXES):
                paths.add(REPO / relative)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"cannot enumerate tracked study sources: {exc}") from exc

    for relative in _STUDY_EXTRA_FILES:
        paths.add(REPO / relative)

    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover - Python <3.11 compatibility
        import tomli as tomllib  # type: ignore
    for task in ("gemm", "spmm", "stencil"):
        harness_dir = REPO / "workspace" / "harnesses" / task
        manifest_path = harness_dir / "harness.toml"
        paths.add(manifest_path)
        with manifest_path.open("rb") as fh:
            manifest = tomllib.load(fh)
        for relative in (manifest.get("files") or {}):
            paths.add(harness_dir / relative)

    result: dict[str, str] = {}
    for path in sorted(paths):
        try:
            relative = path.relative_to(REPO).as_posix()
        except ValueError as exc:
            raise RuntimeError(f"study source is outside repository: {path}") from exc
        if path.is_symlink():
            payload = ("symlink:" + os.readlink(path)).encode()
            result[relative] = hashlib.sha256(payload).hexdigest()
        elif path.is_file():
            result[relative] = _sha256_file(path)
        else:
            raise RuntimeError(f"study source is missing: {relative}")
    return result


def study_source_fingerprint() -> str:
    """Stable aggregate digest of :func:`study_source_manifest`."""
    payload = json.dumps(
        study_source_manifest(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode()
    return hashlib.sha256(payload).hexdigest()


_HANDOFF_CHANNEL_ENV = {
    "ARI_HANDOFF_COPY_WORKDIR",
    "ARI_HANDOFF_AGENT_BLOCK",
    "ARI_HANDOFF_PLANNER_BLOCK",
    "ARI_HANDOFF_MEMORY_OFF",
    "ARI_HANDOFF_LOG_MODE",
    "ARI_HANDOFF_SUMMARY_FORM",
    "ARI_HANDOFF_SUMMARY_FIELDS",
    "ARI_HANDOFF_PAIRED_MODES",
    "ARI_HANDOFF_LOG_LIMIT",
    "ARI_HANDOFF_LOG_SCRUB_EMIT",
}
_ARM_CHANNELS = {
    "code_only": {
        "ARI_HANDOFF_COPY_WORKDIR": "1",
        "ARI_HANDOFF_AGENT_BLOCK": "0",
        "ARI_HANDOFF_LOG_MODE": "none",
        "ARI_HANDOFF_SUMMARY_FORM": "extractive",
    },
    "evidence_only": {
        "ARI_HANDOFF_COPY_WORKDIR": "1",
        "ARI_HANDOFF_AGENT_BLOCK": "1",
        "ARI_HANDOFF_LOG_MODE": "none",
        "ARI_HANDOFF_SUMMARY_FORM": "evidence",
    },
    "evidence_plus_reflection": {
        "ARI_HANDOFF_COPY_WORKDIR": "1",
        "ARI_HANDOFF_AGENT_BLOCK": "1",
        "ARI_HANDOFF_LOG_MODE": "none",
        "ARI_HANDOFF_SUMMARY_FORM": "evidence_reflection",
    },
}
# Measurement isolation is part of the treatment-independent study contract.
# NumPy's GEMM reference otherwise leaves a many-threaded BLAS pool active just
# before the timed OpenMP candidate. On fx700 this made candidate-first pairs
# 6-15x slower than baseline-first pairs. The kernel subprocess still receives
# the task-specific 48-thread budget through ARI_{TASK}_THREADS; these variables
# only serialize controller-side numerical libraries and pin kernel placement.
_MEASUREMENT_ENV = {
    "OPENBLAS_NUM_THREADS": "1",
    "GOTO_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "BLIS_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
    "OMP_PROC_BIND": "spread",
    "OMP_PLACES": "cores",
    "OMP_DYNAMIC": "FALSE",
    # A candidate that cannot complete one frozen case within two minutes is a
    # scientific candidate failure, not permission to consume the six-hour
    # allocation until Slurm reclassifies it as infrastructure loss.
    "ARI_HARNESS_RUN_TIMEOUT_S": "120",
}
# Per-arm env that pins the study controls (PREREG): frozen contract, deterministic
# evaluator + selector. memory_off is implied by each handoff mode's resolution.
_FIXED = {
    **_MEASUREMENT_ENV,
    "ARI_FREEZE_CONTRACT": "1",
    "ARI_EVALUATOR": "deterministic",
    "ARI_BFTS_DETERMINISTIC": "1",
    # Registered per-node action budget requested for both smoke and study runs.
    "ARI_MAX_REACT": "25",
    # The node budget is exact for the registered study. The default depth cap
    # of 5 can exhaust a path-shaped frontier at 6--9 nodes, differentially by
    # treatment. A depth cap of 10 permits root + 9 descendants for N=10.
    "ARI_MAX_DEPTH": "10",
    # Self-contained, deterministic memory: the study controls memory via the
    # handoff mode (arms set memory_off); the backend must not depend on an
    # external Letta service, so pin the process-local in_memory backend.
    "ARI_MEMORY_BACKEND": "in_memory",
    # Belt-and-suspenders: force the handoff memory gate OFF explicitly, so the
    # de-facto memory channel (working-context Tier-1a/1b/1c/2 + global-memory
    # search in agent/loop.py) is never injected regardless of mode resolution.
    # The canonical handoff modes already set memory_off=True, but pinning the
    # env makes cross-node memory a non-confound even if a merge shifts defaults.
    "ARI_HANDOFF_MEMORY_OFF": "1",
    # PLANNER-SIDE PARENT REPORT OFF. The BFTS expand prompt injects the parent's
    # structured node_report ("Parent node_report (structured self-report): ...").
    # That is a SUMMARY channel living outside the arm definition: with it on,
    # even code_only children read the parent's self-report, so every arm shares
    # an un-ablated summary and the between-arm difference is pushed toward zero.
    # HandoffConfig resolves inject_planner_block=False for every mode, but the
    # flag was never consulted until it was wired to this env var — pin it here so
    # the control is explicit in the run record rather than implied by a default.
    "ARI_HANDOFF_PLANNER_BLOCK": "0",
    # LABEL FEATURE OFF (the real one). The exploration label steers the search in
    # THREE places and only the third is reporting:
    #   1. the system prompt's NODE ROLE (per-label orders: ABLATION="remove or
    #      disable one component", DEBUG="the parent failed, diagnose it",
    #      DRAFT="implement from scratch");
    #   2. the child's `Task:` line (same, restated);
    #   3. node SELECTION — the default frontier score is scientific_plus_diversity,
    #      whose diversity_bonus gives +0.05 to under-represented labels.
    # This makes every child get the same neutral role/task and makes selection
    # ignore labels entirely.
    #
    # WHY IT MATTERS (measured, 4-arm x 10-node run): the ABLATION share of children
    # was 0 / 1 / 3 / 4 — MONOTONE in handoff richness — while ARI_REPORT_MINIMAL
    # stripped labels from node_report/tree.json. So the planner was handing richer
    # arms an explicit "edit the parent's code" order, the central rewrite->refine
    # result could not be separated from it, and the confound was INVISIBLE in the
    # deliverable. See paper §limits (vi).
    "ARI_BFTS_NO_LABEL": "1",
    # ARI_REPORT_MINIMAL and ARI_BFTS_DETERMINISTIC_LABEL are DELIBERATELY NOT SET.
    # Both only strip label/raw_label/original_direction from node_report+tree.json
    # while the label kept driving the search — a record-only suppression, which is
    # precisely how this study's label confound stayed invisible for a whole 4-arm
    # run (ABLATION share 0/1/3/4 across arms, undetectable from the deliverable).
    # A flag that hides a live variable from the record does not make the variable
    # inert; it only removes the evidence. The record must show whatever actually
    # drove the search. With ARI_BFTS_NO_LABEL above, the label is genuinely inert,
    # so recording it costs nothing and lets a reader VERIFY it was inert.
    # Disable the per-node re-expansion cap (default 4) so the BFTS tree can grow
    # toward the run-level budget (N) instead of stopping at root + 4 children.
    "ARI_BFTS_MAX_EXPANSIONS": "999",
    # The study analyses BFTS node speedups, not papers — skip the 24-stage
    # paper pipeline that otherwise dominates per-run wall-clock.
    "ARI_SKIP_PAPER": "1",
    # No ideation/survey/paper phase: the work_dir is pre-seeded and scoring is a
    # fixed deterministic evaluator. Root nodes get a DIRECT experiment prompt
    # (edit candidate -> build -> run selftest), NOT the research-pipeline
    # boilerplate ("call generate_ideas()/make_metric_spec()/survey() ...").
    "ARI_SKIP_IDEATION": "1",
    # Strict tool allowlist: pin the agent to the minimal HPC-coding toolset so the
    # deterministic task is not confounded — and weak models are not drowned — by
    # the ~30 irrelevant memory / VirSci / singularity / make_metric_spec / slurm /
    # plot tools that loaded skills otherwise expose. memory_off only gated
    # INJECTION; this also removes the memory TOOLS the agent could still call.
    "ARI_ALLOWED_TOOLS": "write_code,run_code,run_bash,read_file,emit_results,describe_environment",
    # NEVER truncate the task description. The old 1500-char goal cap cut every
    # task's experiment.md mid-way (all are 2296-4324 chars), hiding the scoring
    # rubric / data layout / workflow from the agent. 0 = no cap.
    "ARI_GOAL_MAX_CHARS": "0",
    # LLM context = 32768, the qwen2.5-coder HARD limit (n_ctx_train=32768; it
    # CANNOT be raised — ollama caps a larger num_ctx with a "too large for model"
    # warning). Overflow (~0.69% of requests at 32768) is instead prevented by the
    # budget-aware ReAct window (loop.py _build_safe_window), which trims the oldest
    # tail so head(goal)+pinned(handoff) always fit under this limit.
    "ARI_LLM_NUM_CTX": "32768",
    # SERIAL BFTS (no parallel nodes). The deterministic evaluator locates the
    # candidate via the PROCESS-GLOBAL os.environ["ARI_WORK_DIR"]
    # (deterministic_evaluator.py) which each node overwrites at run() start
    # (loop.py) with no save/restore. BFTS otherwise runs up to 4 nodes as
    # concurrent THREADS in one process (bfts_loop.py ThreadPoolExecutor,
    # default ARI_PARALLEL=4), so ARI_WORK_DIR is raced across siblings and a
    # node can be SCORED ON A SIBLING's candidate while its own dir keeps its
    # own file (eval≠saved). Parallelism also oversubscribes cores, making the
    # (racy) kernels' correctness/timing non-deterministic. Pinning =1 makes
    # every node score its own candidate under a stable load. (The packed
    # sbatch already set this; direct runs must too.) The proper fix is to pass
    # work_dir to the evaluator explicitly instead of via a global.
    "ARI_PARALLEL": "1",
}


def _ari_cmd(task: str) -> list[str]:
    exp = str(_experiment_for(task))
    # Run the ari CLI with the INTERPRETER WE ARE ALREADY USING, via ``-m ari.cli``.
    # The project .venv/bin/ari is an x86 console script; on an aarch64 compute node
    # it cannot execute, and preferring it launched a wrong-arch binary that failed
    # every run. `python -m ari.cli` uses sys.executable (this run's arch-correct
    # venv) and the ari-core path we inserted at import, so it works on either arch.
    # (A global `ari` on PATH is deliberately NOT preferred: a stale ~/.local/bin/ari
    # can resolve to a broken interpreter — the reason this used to pin the venv one.)
    cmd = [sys.executable, "-m", "ari.cli", "run", exp]
    cfg = os.environ.get("ARI_RUN_CONFIG", "").strip()
    if cfg:
        cmd.extend(["--config", cfg])
    return cmd


def _experiment_dirs() -> set[str]:
    """Run dirs that hold per-node work_dirs (excludes the ``*_root`` siblings)."""
    out = set()
    for p in glob.glob(str(REPO / "experiments" / "*")):
        if os.path.isdir(p) and not p.endswith("_root"):
            out.add(p)
    return out


# Remote (non-Ollama) providers litellm routes by a leading "<provider>/".
_REMOTE_PREFIXES = ("openai/", "cerebras/", "anthropic/", "claude/", "groq/",
                    "together_ai/", "azure/", "mistral/", "deepseek/")
# provider prefix -> the env var litellm reads the key from. config.llm.api_key is
# NOT populated from env by ARI's apply_env_overrides, so authentication comes from
# these; keeping the key out of `overrides` means no secret reaches the dry-run
# print or the recorded command.
_PROVIDER_KEY_ENV = {
    "cerebras/": "CEREBRAS_API_KEY", "openai/": "OPENAI_API_KEY",
    "anthropic/": "ANTHROPIC_API_KEY", "claude/": "ANTHROPIC_API_KEY",
    "groq/": "GROQ_API_KEY", "deepseek/": "DEEPSEEK_API_KEY",
    "mistral/": "MISTRAL_API_KEY",
}


def _autoconfig_and_guard(overrides: dict, model: str) -> None:
    """Make a remote model 'just work', and fail LOUD on the silent-misroute trap.

    Verified end-to-end (real completion through ARI's LLMClient): the default
    ``ARI_BACKEND=ollama`` both prepends ``ollama_chat/`` AND injects Ollama-only
    ``num_ctx`` (from ``ARI_LLM_NUM_CTX`` in ``_FIXED``). An OpenAI-compatible
    endpoint (Cerebras) 400s on ``num_ctx``, so EVERY (arm, seed) run dies at the
    root node's first LLM call with zero data — and nothing in ARI validates it,
    so a remote id detonates silently. This converts that into a startup error and
    auto-sets the backend so the operator need not remember it.

    Keys are deliberately NOT set here (see ``_PROVIDER_KEY_ENV``): litellm reads
    the provider key env var itself, so no secret enters ``overrides``.
    """
    api_base = os.environ.get("ARI_LLM_API_BASE", "").strip()
    prefix = next((p for p in _REMOTE_PREFIXES if model.startswith(p)), None)
    remote = bool(prefix) or bool(api_base)
    backend = (overrides.get("ARI_BACKEND")
               or os.environ.get("ARI_BACKEND", "")).strip().lower()

    if not remote:
        # A bare id needs an auto-prefixing backend (ollama -> ollama_chat/,
        # cli-shim -> openai/). On a plain remote backend litellm can't infer it.
        if backend not in ("", "ollama", "cli-shim", "cli_shim"):
            raise SystemExit(
                f"[preflight] model {model!r} on ARI_BACKEND={backend!r} has no "
                f"'<provider>/' prefix; litellm cannot route it (provider NOT provided). "
                f"Use e.g. cerebras/{model} or openai/{model}.")
        # A bare id on the ollama/unset backend routes to LOCAL Ollama — legit for a
        # local model, but if a remote provider key is set the operator probably
        # meant that provider and dropped the '<provider>/' prefix, which would
        # silently reach a (likely absent) local Ollama and abort every run. Warn,
        # not fatal: local-Ollama use with a stray key in the env is possible.
        if backend in ("", "ollama") and "/" not in model:
            for pfx, kenv in _PROVIDER_KEY_ENV.items():
                if os.environ.get(kenv):
                    print(f"[preflight] WARNING: bare model {model!r} routes to LOCAL "
                          f"Ollama, but {kenv} is set in the environment. Did you mean "
                          f"{pfx}{model}? A bare id will NOT reach {pfx.rstrip('/')}.",
                          file=sys.stderr)
                    break
        return

    if backend == "ollama":
        raise SystemExit(
            f"[preflight] ARI_BACKEND=ollama with the remote model {model!r} injects "
            f"Ollama-only num_ctx that an OpenAI-compatible endpoint rejects — verified "
            f"to abort every run at the root node with zero data. Set ARI_BACKEND=openai.")
    if not backend:
        # openai backend: resolve() leaves an already-prefixed id alone and skips
        # the ollama-only num_ctx injection. Recorded (non-secret) so it is visible.
        overrides["ARI_BACKEND"] = "openai"
    key_env = _PROVIDER_KEY_ENV.get(prefix or "openai/")
    if key_env and not os.environ.get(key_env):
        print(f"[preflight] WARNING: {key_env} is not set; litellm needs it to "
              f"authenticate {model!r}. `source .env` (or export it) first.",
              file=sys.stderr)


def _redact_env(k: str, v: str) -> str:
    """Never print a secret value in the dry-run env dump."""
    return "<redacted>" if re.search(r"KEY|TOKEN|SECRET|PASSWORD|CRED", k, re.I) else v


def _node_reports(run_dir: str | None) -> list[tuple[Path, dict]]:
    if not run_dir or not os.path.isdir(run_dir):
        return []
    out: list[tuple[Path, dict]] = []
    for path in sorted(Path(run_dir).glob("node_*/node_report.json")):
        try:
            out.append((path, json.loads(path.read_text())))
        except Exception:
            continue
    return out


def _run_has_infrastructure_error(run_dir: str | None) -> bool:
    return any(
        report.get("evaluation_status") == "infrastructure_error"
        for _, report in _node_reports(run_dir)
    )


def _scored_any(run_dir: str | None) -> bool:
    """True iff the evaluator scored >=1 node — i.e. a MEASUREMENT happened.
    A run where no node was ever scored (all failed at the root with a null score)
    is an LLM/provider outage, not a measurement. Mirrors the analyzer's guard."""
    import math as _mm
    reports = _node_reports(run_dir)
    if not reports or _run_has_infrastructure_error(run_dir):
        return False
    for _, report in reports:
        status = report.get("evaluation_status")
        if status in {"valid", "candidate_invalid", "measurement_invalid"}:
            return True
        m = report.get("metrics") or {}
        for k in ("_scientific_score", "valid_geomean_speedup"):
            v = m.get(k)
            if isinstance(v, (int, float)) and _mm.isfinite(v):
                return True
    return False


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _best_valid_node(run_dir: str | None) -> tuple[Path | None, dict | None, float]:
    best_path: Path | None = None
    best_report: dict | None = None
    best_score = 0.0
    for report_path, report in _node_reports(run_dir):
        valid = report.get("measurement_valid")
        metrics = report.get("metrics") or {}
        if metrics.get("_sterile") is True:
            continue
        score = metrics.get("valid_geomean_speedup")
        if valid is not True or not isinstance(score, (int, float)):
            continue
        if math.isfinite(float(score)) and float(score) > best_score:
            best_path = report_path.parent
            best_report = report
            best_score = float(score)
    return best_path, best_report, best_score


def _write_final_measurement(
    run_dir: str | None,
    *,
    task: str,
    seed: int,
    reps: int,
    expected_nodes: int | None = None,
) -> dict:
    """Independently remeasure the search winner and persist the primary outcome."""
    if not run_dir:
        return {
            "status": "infrastructure_error",
            "score": None,
            "reason": "run directory missing",
            "path": None,
        }
    out_path = Path(run_dir) / "final_measurement.json"
    started = _dt.datetime.now(_dt.timezone.utc).isoformat()
    reports = _node_reports(run_dir)
    observed_nodes = len(reports)
    node_dir, report, search_score = _best_valid_node(run_dir)
    base = {
        "schema_version": 1,
        "task": task,
        "seed": seed,
        "remeasure_seed": seed + 1_000_000,
        "requested_repetitions": int(reps),
        "started_at": started,
        "selected_node_id": (report or {}).get("node_id"),
        "search_score": search_score,
        "expected_search_nodes": expected_nodes,
        "observed_search_nodes": observed_nodes,
    }
    if _run_has_infrastructure_error(run_dir):
        payload = {
            **base,
            "evaluation_status": "infrastructure_error",
            "measurement_valid": False,
            "scientific_score": None,
            "reason": "node evaluation reported infrastructure_error",
        }
    elif expected_nodes is not None and observed_nodes != int(expected_nodes):
        payload = {
            **base,
            "evaluation_status": "infrastructure_error",
            "measurement_valid": False,
            "scientific_score": None,
            "reason": (
                "search node budget was not completed: "
                f"{observed_nodes}/{int(expected_nodes)} readable node reports"
            ),
        }
    elif not _scored_any(run_dir):
        payload = {
            **base,
            "evaluation_status": "infrastructure_error",
            "measurement_valid": False,
            "scientific_score": None,
            "reason": (
                "no node received an objective evaluator verdict; probable "
                "LLM/provider or orchestration failure"
            ),
        }
    elif node_dir is None:
        payload = {
            **base,
            "evaluation_status": "candidate_invalid",
            "measurement_valid": False,
            "scientific_score": 0.0,
            "reason": "search produced no valid candidate",
            "evaluation_cases": {},
            "measurement_audit": {
                "effective_candidate_compile_flags": [],
                "rejected_candidate_compile_flags": [],
                "cases": {},
            },
        }
    else:
        candidate_files = sorted(
            p for p in node_dir.iterdir()
            if p.is_file() and (p.name.startswith("candidate_")
                                or p.name == "candidate_flags.txt")
        )
        base["candidate_files"] = {
            p.name: _sha256_file(p) for p in candidate_files
        }
        try:
            from ari.evaluator.deterministic_evaluator import DeterministicEvaluator
            from ari.harness_registry import load
            raw = load(task).measure(
                str(node_dir), reps=int(reps), seed=seed + 1_000_000)
            scored = DeterministicEvaluator(
                task=task,
                target_speedup=1.0, scale="linear").score_result(raw)
            payload = {
                **base,
                "evaluation_status": scored["evaluation_status"],
                "measurement_valid": bool(scored["valid"]),
                "scientific_score": float(scored["scientific_score"]),
                "reason": scored["reason"],
                "evaluation_cases": scored.get("evaluation_cases") or {},
                "measurement_audit": scored.get("measurement_audit") or {},
            }
        except Exception as exc:
            payload = {
                **base,
                "evaluation_status": "infrastructure_error",
                "measurement_valid": False,
                "scientific_score": None,
                "reason": f"final remeasurement infrastructure error: {exc}",
            }
    payload["completed_at"] = _dt.datetime.now(_dt.timezone.utc).isoformat()
    tmp = out_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    tmp.replace(out_path)
    return {
        "status": payload["evaluation_status"],
        "score": payload.get("scientific_score"),
        "reason": payload.get("reason"),
        "path": str(out_path),
    }


def _api_health_check(model: str) -> tuple[bool, str]:
    """Cheap preflight: one minimal completion to confirm the LLM provider ANSWERS,
    BEFORE launching a full sweep. Catches an already-down / out-of-credit API up
    front (the 2026-07-27 Cerebras payment outage burned a 150-run sweep because
    nothing checked). Skips for local/non-remote models or if litellm is absent."""
    prefix = next((p for p in _REMOTE_PREFIXES if model.startswith(p)), None)
    if not prefix:
        return True, "non-remote model; API health check skipped"
    try:
        import litellm
        litellm.completion(model=model,
                           messages=[{"role": "user", "content": "ping"}],
                           max_tokens=1, temperature=0)
        return True, "ok"
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:200]}"


def run_one(arm: str, model: str, seed: int, max_nodes: int, dry: bool,
            task: str = "spmm", scorer: str = "deterministic",
            paired_modes: list[str] | None = None) -> tuple[int, str | None]:
    """Run one (arm, seed). Returns (returncode, run experiment dir or None).

    The study fixes ``scorer`` to the registered non-LLM evaluator; it is retained
    as a manifest field so the resolved configuration remains auditable.
    """
    if scorer != "deterministic":
        raise SystemExit(
            f"[preflight] scorer {scorer!r} is outside the registered handoff study")
    overrides = dict(_FIXED)
    overrides.update({
        "ARI_TASK": task,
        "ARI_HANDOFF_MODE": arm,
        "ARI_SEED": str(seed),
        "ARI_MODEL": model,
        "ARI_MAX_NODES": str(max_nodes),
    })
    if arm not in _ARM_CHANNELS:
        raise SystemExit(
            f"[preflight] arm {arm!r} has no pinned handoff-channel definition")
    overrides.update(_ARM_CHANNELS[arm])
    if paired_modes:
        overrides["ARI_HANDOFF_PAIRED_MODES"] = ",".join(paired_modes)
        # Diagnostic paired mode: one BFTS tree contains sibling handoff arms.
        # This is useful for checking prompt injection and parent-workspace
        # cloning, but it is not the confirmatory design for a deep BFTS sweep.
        # Per-child handoff_mode controls the actual child prompt.
        overrides["ARI_HANDOFF_MODE"] = "code_only"
    # Fail loud (or auto-set the backend) BEFORE launching — a remote model on the
    # default ollama backend aborts every run at the root node with zero data.
    _autoconfig_and_guard(overrides, model)
    label = f"{task} | {arm} | {model} | seed={seed} | N={max_nodes} | scorer={scorer}"
    cmd = _ari_cmd(task)
    if dry:
        print(f"[dry-run] {label}")
        print("  env:", " ".join(f"{k}={_redact_env(k, v)}" for k, v in overrides.items()))
        print("  cmd:", " ".join(cmd), f"(cwd={REPO})")
        return 0, None
    env = dict(os.environ)
    # Remove every ambient per-channel override before applying the registered
    # arm. Otherwise a stale shell variable can silently collapse two treatments.
    for key in _HANDOFF_CHANNEL_ENV:
        env.pop(key, None)
    env.update(overrides)
    # ``python -m ari.cli`` is a FRESH process; give it ari-core on PYTHONPATH so it
    # can import ari without a site-packages install (needed on the aarch64 venv).
    _ari_core = str(REPO / "ari-core")
    env["PYTHONPATH"] = _ari_core + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    print(f"[run] {label}", flush=True)
    proc = subprocess.run(cmd, env=env, cwd=str(REPO), capture_output=True, text=True)
    rc = proc.returncode
    out = (proc.stdout or "") + "\n" + (proc.stderr or "")
    print(out, flush=True)  # keep the run log (no longer live-streamed)
    # RACE-FREE run-dir attribution. The origin/main refactor pins the experiments
    # dir to {repo}/workspace/experiments/ (from the package location — ARI_ROOT /
    # ARI_CHECKPOINT_DIR do NOT relocate it), and node work_dirs land at
    # {repo}/workspace/experiments/<run_id>/node_*. ARI logs THIS run's own run_id
    # (a 14-digit timestamp + goal slug) as ``checkpoints/<run_id>`` in its stdout,
    # so we parse it from this process's captured output — concurrent shards never
    # collide because each parses only its own run's stdout. (The old repo-root
    # before/after diff + ``experiments/<id>/node_`` regex both failed silently
    # after the move, giving run_dir=None and empty results.)
    run_dir = None
    hits = re.findall(r'(?:checkpoints|experiments)/(\d{14}_[A-Za-z0-9_]+)', out)
    bases = [REPO / "workspace" / "experiments", REPO / "experiments"]
    if hits:
        rid = Counter(hits).most_common(1)[0][0]
        for base in bases:  # exact run_id first
            c = base / rid
            if c.is_dir() and glob.glob(str(c / "node_*")):
                run_dir = str(c); break
        if run_dir is None:  # stdout may truncate the slug — match the unique timestamp
            ts = rid[:14]
            for base in bases:
                m = [d for d in glob.glob(str(base / (ts + "_*"))) if glob.glob(d + "/node_*")]
                if m:
                    run_dir = sorted(m)[-1]; break
    if _run_has_infrastructure_error(run_dir):
        print(
            f"[run] FATAL: {label} contains evaluator infrastructure_error; "
            "marking the run non-zero so it cannot enter the scientific sample.",
            file=sys.stderr,
        )
        rc = rc or 4
    return rc, run_dir


def _record(manifest: Path | None, **row) -> None:
    if manifest is None:
        return
    row["allocation"] = {
        "hostname": os.uname().nodename,
        "slurm_job_id": os.environ.get("SLURM_JOB_ID"),
        "slurm_array_job_id": os.environ.get("SLURM_ARRAY_JOB_ID"),
        "slurm_array_task_id": os.environ.get("SLURM_ARRAY_TASK_ID"),
        "slurm_partition": os.environ.get("SLURM_JOB_PARTITION"),
        "slurm_nodelist": os.environ.get("SLURM_JOB_NODELIST"),
        "slurm_cpus_per_task": os.environ.get("SLURM_CPUS_PER_TASK"),
    }
    row["study_source_fingerprint"] = os.environ.get(
        "ARI_STUDY_SOURCE_FINGERPRINT"
    )
    with open(manifest, "a") as fh:
        fh.write(json.dumps(row) + "\n")


def _write_study_bundle(out_dir: Path, *, task: str, args) -> str:
    """Snapshot the exact study controls, task harness, and tracked dirty diff."""
    bundle = out_dir / "study_bundle"
    bundle.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []

    def _copy(src: Path, relative: Path) -> None:
        if not src.is_file():
            return
        dst = bundle / relative
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied.append(dst)

    # These files define the treatment, evaluator, report schema, driver, and
    # analysis. They are copied even when tracked because a dirty patch alone
    # requires the exact base checkout to reconstruct the executed bytes.
    control_sources = [
        "workspace/run_handoff_ablation.py",
        "workspace/analyze_handoff_ablation.py",
        "workspace/submit_handoff_ablation_array.sh",
        "workspace/submit_handoff_ablation_sbatch.sh",
        "report_temp/paper_ja.tex",
        "ari-core/ari/agent/loop.py",
        "ari-core/ari/cli/bfts_loop.py",
        "ari-core/ari/config/__init__.py",
        "ari-core/ari/evaluator/deterministic_evaluator.py",
        "ari-core/ari/evaluator/handoff_stats.py",
        "ari-core/ari/harness_registry.py",
        "ari-core/ari/orchestrator/bfts.py",
        "ari-core/ari/orchestrator/node.py",
        "ari-core/ari/orchestrator/node_summary_view.py",
        "ari-core/ari/orchestrator/node_report/builder.py",
        "ari-core/ari/schemas/node_report.schema.json",
    ]
    for relative in control_sources:
        _copy(REPO / relative, Path("source") / relative)

    config = os.environ.get("ARI_RUN_CONFIG", "").strip()
    if config:
        _copy(Path(config), Path("config") / Path(config).name)

    # Harnesses live under the gitignored workspace. Copy the self-hashed
    # manifest and every content-addressed file so the recorded digests name
    # bytes that are actually present in the study artifact.
    from ari.harness_registry import load as _load_harness
    harness = _load_harness(task)
    harness_dir = Path(harness.origin)
    _copy(
        harness_dir / "harness.toml",
        Path("harness") / task / "harness.toml",
    )
    for relative in sorted(harness.pinned):
        _copy(
            harness_dir / relative,
            Path("harness") / task / relative,
        )

    def _git(*git_args: str) -> str:
        cp = subprocess.run(
            ["git", "-C", str(REPO), *git_args],
            capture_output=True,
            text=True,
            timeout=60,
        )
        return cp.stdout if cp.returncode == 0 else ""

    (bundle / "git_status.txt").write_text(
        _git("status", "--porcelain=v1", "--untracked-files=all"))
    (bundle / "ari_dirty.patch").write_text(_git("diff", "--binary", "HEAD"))
    copied.extend([bundle / "git_status.txt", bundle / "ari_dirty.patch"])
    config_payload = {
        "schema_version": 1,
        "task": task,
        "argv": list(sys.argv),
        "mode": args.mode,
        "arms": list(args.arms),
        "shard_arm": getattr(args, "shard_arm", None),
        "seed_base": args.seed_base,
        "seeds": args.seeds,
        "max_nodes": args.max_nodes,
        "max_react": _FIXED["ARI_MAX_REACT"],
        "remeasure_reps": args.remeasure_reps,
        "model": args.model if args.mode == "pilot" else args.large_model,
        "scorer": args.scorer,
        "study_source_fingerprint": os.environ.get(
            "ARI_STUDY_SOURCE_FINGERPRINT"
        ),
        "fixed_env": dict(_FIXED),
        "arm_channels": _ARM_CHANNELS,
        "measurement_environment": {
            key: os.environ.get(key)
            for key in (
                "OMP_NUM_THREADS",
                "OMP_PROC_BIND",
                "OMP_PLACES",
                "OMP_DYNAMIC",
                "ARI_HARNESS_RUN_TIMEOUT_S",
                "OPENBLAS_NUM_THREADS",
                "GOTO_NUM_THREADS",
                "MKL_NUM_THREADS",
                "BLIS_NUM_THREADS",
                "VECLIB_MAXIMUM_THREADS",
                "NUMEXPR_NUM_THREADS",
                "ARI_GEMM_THREADS",
                "ARI_GEMM_CC",
                "ARI_GEMM_CFLAGS",
                "ARI_SPMM_THREADS",
                "ARI_SPMM_CC",
                "ARI_SPMM_CFLAGS",
                "ARI_STENCIL_THREADS",
                "ARI_STENCIL_CC",
                "ARI_STENCIL_CFLAGS",
                "ARI_SPMM_N",
                "ARI_SPMM_K",
                "ARI_STENCIL_SHAPES",
            )
        },
        "allocation": {
            "hostname": os.uname().nodename,
            "slurm_job_id": os.environ.get("SLURM_JOB_ID"),
            "slurm_array_job_id": os.environ.get("SLURM_ARRAY_JOB_ID"),
            "slurm_array_task_id": os.environ.get("SLURM_ARRAY_TASK_ID"),
            "slurm_partition": os.environ.get("SLURM_JOB_PARTITION"),
            "slurm_nodelist": os.environ.get("SLURM_JOB_NODELIST"),
            "slurm_cpus_per_task": os.environ.get("SLURM_CPUS_PER_TASK"),
        },
        "harness": harness.provenance(),
        "git_sha": _git("rev-parse", "HEAD").strip(),
    }
    config_path = bundle / "study_configuration.json"
    config_path.write_text(json.dumps(config_payload, indent=2, sort_keys=True) + "\n")
    copied.append(config_path)
    manifest_payload = {
        "schema_version": 1,
        "files": {
            str(path.relative_to(bundle)): _sha256_file(path)
            for path in sorted(copied)
        },
    }
    manifest_path = bundle / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest_payload, indent=2, sort_keys=True) + "\n")
    return _sha256_file(manifest_path)


def _resolve_tasks(spec: str) -> list[str]:
    """Resolve a ``--task`` spec to a list of registered tasks.

    Accepts a single name (``gemm`` runs gemm ONLY), a comma-separated subset
    (``gemm,spmm``), or ``all`` (every registered harness). Scores are
    non-commensurable across tasks, so each selected task is swept and analyzed
    on its OWN manifest — never pooled."""
    registered = _task_choices()
    s = (spec or "").strip()
    if s.lower() == "all":
        return registered
    sel = [t.strip() for t in s.split(",") if t.strip()]
    bad = [t for t in sel if t not in registered]
    if bad:
        raise SystemExit(f"unknown task(s) {bad}; registered: {registered} "
                         f"(use a single name, a comma list, or 'all').")
    if not sel:
        raise SystemExit("no task selected (--task)")
    return sel


def _counterbalanced_arms(arms: list[str], seed: int) -> list[str]:
    """Cyclic order: each arm occupies each position once per complete block."""
    if not arms:
        return []
    offset = int(seed) % len(arms)
    return list(arms[offset:] + arms[:offset])


def _run_task_sweep(task: str, a, out_dir: "Path | None") -> int:
    """Run the pilot/MVP sweep for ONE task, writing its own manifest."""
    exp = _experiment_for(task)
    if not exp.is_file():
        print(f"experiment not found: {exp}", file=sys.stderr)
        return 2
    manifest = None
    if not a.dry_run and out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        manifest = out_dir / "manifest.jsonl"
        print(f"[driver] task={task} manifest -> {manifest}")
        bundle_hash = _write_study_bundle(out_dir, task=task, args=a)
        print(f"[driver] study bundle sha256={bundle_hash}")
    else:
        bundle_hash = None

    if not a.dry_run:
        _hm = a.model if a.mode == "pilot" else a.large_model
        _ok, _detail = _api_health_check(_hm)
        if not _ok:
            print(f"[preflight] FATAL: LLM API health check FAILED before running "
                  f"({_hm}) — aborting so a dead/out-of-credit provider does not burn a "
                  f"full sweep. Detail: {_detail}", file=sys.stderr)
            return 3
        print(f"[preflight] API health check: {_detail}", flush=True)

    rc = 0
    if a.mode == "pilot":
        # validity-floor pilot: one clean arm, small N (PREREG gate (a)).
        r, run_dir = run_one(_PILOT_ARM, a.model, 0, a.max_nodes, a.dry_run, task, a.scorer)
        final = (
            {"status": "dry_run", "score": None, "reason": "", "path": None}
            if a.dry_run
            else _write_final_measurement(
                run_dir, task=task, seed=0, reps=a.remeasure_reps,
                expected_nodes=a.max_nodes)
        )
        if final["status"] == "infrastructure_error":
            r = r or 4
        rc |= r
        _record(manifest, task=task, arm=_PILOT_ARM, model=a.model, seed=0,
                max_nodes=a.max_nodes, run_dir=run_dir, rc=r, scorer=a.scorer,
                remeasure_reps=a.remeasure_reps,
                final_measurement=final,
                resolved_handoff=dict(_ARM_CHANNELS[_PILOT_ARM]),
                study_bundle_manifest_sha256=bundle_hash)
        print(f"\n[{task}] Pilot done. Gate: confirm >0 valid nodes; also read off the "
              f"run-level SD + invalid-run rate to size the confirmatory sweep "
              f"before freezing n=30/arm.")
    else:
        _consec_unscored = 0
        for seed in range(a.seed_base, a.seed_base + a.seeds):
            if a.paired:
                arms_this_seed = ["paired"]
                design_order = ["paired"]
            elif a.shard_arm:
                # An array shard executes one arm, but records that arm's position
                # in the full three-arm cyclic schedule. Slurm may preferentially
                # start lower array indices, so rotating positions across seeds
                # prevents one arm from always receiving the first allocations.
                design_order = _counterbalanced_arms(
                    _DEFAULT_ARMS.split(","), seed)
                arms_this_seed = [a.shard_arm]
            else:
                # Exact cyclic counterbalancing: over each block of three seeds,
                # every arm occupies every execution position once.
                arms_this_seed = _counterbalanced_arms(a.arms, seed)
                design_order = arms_this_seed
            for arm_index, arm in enumerate(arms_this_seed):
                design_arm_index = (
                    design_order.index(arm) if arm in design_order else arm_index
                )
                paired_modes = list(a.arms) if a.paired else None
                run_arm = "code_only" if a.paired else arm
                r, run_dir = run_one(run_arm, a.large_model, seed, a.max_nodes,
                                     a.dry_run, task, a.scorer,
                                     paired_modes=paired_modes)
                final = (
                    {"status": "dry_run", "score": None, "reason": "", "path": None}
                    if a.dry_run or a.paired
                    else _write_final_measurement(
                        run_dir, task=task, seed=seed, reps=a.remeasure_reps,
                        expected_nodes=a.max_nodes)
                )
                if final["status"] == "infrastructure_error":
                    r = r or 4
                rc |= r
                _record(manifest, task=task, arm=arm, model=a.large_model, seed=seed,
                        max_nodes=a.max_nodes, run_dir=run_dir, rc=r,
                        scorer=a.scorer, paired_modes=paired_modes,
                        arm_order=design_order,
                        arm_order_index=design_arm_index,
                        remeasure_reps=a.remeasure_reps,
                        final_measurement=final,
                        study_bundle_manifest_sha256=bundle_hash,
                        resolved_handoff=(
                            dict(_ARM_CHANNELS[run_arm]) if not a.paired else None
                        ))
                # Fail fast on a mid-sweep provider outage: if several runs in a row
                # produce NO scored node, the LLM API is almost certainly down —
                # abort loudly instead of burning the rest of the sweep on failures
                # that would silently enter analysis as 0 (see 2026-07-27 outage).
                if not a.dry_run:
                    _consec_unscored = 0 if _scored_any(run_dir) else _consec_unscored + 1
                    if _consec_unscored >= 3:
                        print(f"[driver] FATAL: {_consec_unscored} consecutive runs scored "
                              f"NO node — almost certainly an LLM/provider outage. Aborting "
                              f"the sweep (investigate the API; do NOT trust partial data).",
                              file=sys.stderr)
                        return rc | 3
        if manifest:
            print(f"\n[{task}] MVP sweep done. Analyze with:\n"
                  f"  python workspace/analyze_handoff_ablation.py {manifest.parent}")
    return rc


def main() -> int:
    # The driver performs the independent final remeasurement in this process,
    # so pin controller BLAS before the registry imports NumPy/SciPy harnesses.
    # Child ARI processes receive the same values through _FIXED.
    os.environ.update(_MEASUREMENT_ENV)

    ap = argparse.ArgumentParser(description="Handoff-study pilot/sweep driver")
    ap.add_argument("--mode", choices=["pilot", "mvp"], default="pilot")
    ap.add_argument("--task", default="spmm",
                    help="deterministic task(s): a SINGLE name (e.g. 'gemm' to run "
                         "gemm ONLY), a comma-separated subset ('gemm,spmm'), or 'all' "
                         "(every registered harness). Each task writes its OWN manifest "
                         "(scores are non-commensurable across tasks). Registered: "
                         + ", ".join(_task_choices()))
    ap.add_argument("--model", default="qwen3:8b", help="pilot model (validity floor)")
    ap.add_argument("--large-model", default="qwen3:32b", help="MVP model")
    ap.add_argument("--seeds", type=int, default=1, help="MVP: independent runs per arm")
    ap.add_argument("--seed-base", type=int, default=0,
                    help="MVP: first seed (for sharding a sweep across jobs: each "
                         "shard runs seeds [seed_base, seed_base+seeds))")
    ap.add_argument("--max-nodes", type=int, default=10, help="best valid @ N nodes (PREREG N=10)")
    ap.add_argument(
        "--remeasure-reps",
        type=int,
        default=15,
        help="independent repetitions per case for the selected run winner "
             "(primary outcome; default 15)",
    )
    ap.add_argument("--out-dir", default=None,
                    help="manifest output dir (default workspace/checkpoints/<ts>_handoff_<task>_<mode>). "
                         "With multiple tasks, each task gets a <out-dir>/<task> subdir.")
    ap.add_argument(
        "--scorer",
        choices=["deterministic"],
        default="deterministic",
        help="fixed registered non-LLM evaluator (recorded in the manifest)",
    )
    ap.add_argument("--arms", default=None,
                    help="comma-separated arm set (default: code_only,evidence_only,"
                         "evidence_plus_reflection). Explicit --arms beats ARI_HANDOFF_ARMS; if the effective "
                         "set differs from the registered design, a LOUD preflight warning "
                         "fires so a stale ambient value cannot silently change the design.")
    ap.add_argument(
        "--shard-arm",
        choices=list(_ARM_CHANNELS),
        default=None,
        help="registered matrix sharding: execute exactly one arm while retaining "
             "the full three-arm design metadata. Intended for one "
             "task x arm x seed Slurm allocation; unlike --arms, this is not a "
             "non-registered diagnostic design.",
    )
    ap.add_argument("--paired", action="store_true",
                    help="diagnostic only: run one BFTS tree per seed and create "
                         "sibling children for all arms from the same selected "
                         "parent workspace. Confirmatory sweeps should omit this "
                         "flag so each handoff policy gets an independent BFTS run.")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if a.remeasure_reps < 3:
        raise SystemExit("--remeasure-reps must be >=3")

    if a.shard_arm and a.arms is not None:
        raise SystemExit("--shard-arm and --arms are mutually exclusive")
    if a.shard_arm and a.mode != "mvp":
        raise SystemExit("--shard-arm is only valid with --mode mvp")
    if a.shard_arm and a.paired:
        raise SystemExit("--shard-arm and --paired are mutually exclusive")

    # Resolve the arm set: the registered shard selects one member of the frozen
    # design; otherwise --arms wins, then ARI_HANDOFF_ARMS, then the default.
    _arms_explicit = a.arms is not None
    if a.shard_arm:
        a.arms = [a.shard_arm]
    else:
        a.arms = (
            [x.strip() for x in a.arms.split(",") if x.strip()]
            if a.arms else list(ARMS)
        )
    if a.mode == "pilot":
        # The pilot is a validity FLOOR check, not an ablation: it runs the single
        # fixed arm below, whatever --arms/ARI_HANDOFF_ARMS say. Say so, instead of
        # printing an arm-set warning that implies a set the pilot will not run —
        # reporting one design and executing another is the exact failure this
        # preflight exists to prevent.
        print(f"[preflight] pilot mode runs ONE fixed arm ({_PILOT_ARM}), not an arm set."
              + (f" --arms {a.arms} is IGNORED in pilot mode; use --mode mvp to run an "
                 f"arm set." if _arms_explicit else ""),
              file=sys.stderr)
    elif not a.shard_arm and a.arms != _DEFAULT_ARMS.split(","):
        if os.environ.get("ARI_ALLOW_NONREGISTERED_ARMS", "0") != "1":
            raise SystemExit(
                f"[preflight] arm set {a.arms} differs from the registered design "
                f"{_DEFAULT_ARMS.split(',')}. Refusing to change the experiment from "
                "ambient/CLI state. Set ARI_ALLOW_NONREGISTERED_ARMS=1 only for an "
                "explicit diagnostic run."
            )
        print(
            f"[preflight] DIAGNOSTIC OVERRIDE: non-registered arm set {a.arms}",
            file=sys.stderr,
        )
    if len(a.arms) != len(set(a.arms)):
        raise SystemExit(f"[preflight] duplicate arm in {a.arms}")
    unknown_arms = [arm for arm in a.arms if arm not in _ARM_CHANNELS]
    if unknown_arms:
        raise SystemExit(f"[preflight] no pinned channel definition for {unknown_arms}")

    tasks = _resolve_tasks(a.task)
    if a.shard_arm and len(tasks) != 1:
        raise SystemExit(
            "--shard-arm requires exactly one --task so one allocation contains "
            "one task x arm x seed run"
        )
    if a.shard_arm and a.seeds != 1:
        raise SystemExit(
            "--shard-arm requires --seeds 1; shard independent seeds into "
            "separate Slurm allocations"
        )

    if a.paired:
        paired_cap = 1 + len(a.arms)
        if a.max_nodes > paired_cap and os.environ.get("ARI_ALLOW_PAIRED_DEEP", "0") != "1":
            raise SystemExit(
                f"[preflight] --paired is a diagnostic parent-block mode and is only "
                f"allowed up to root+one child per arm (max_nodes <= {paired_cap}). "
                f"For the current study, run separate BFTS runs per arm by omitting "
                f"--paired. Set ARI_ALLOW_PAIRED_DEEP=1 only for exploratory debugging."
            )
        print("[preflight] WARNING: --paired is diagnostic, not the confirmatory "
              "separate-run design. Omit --paired for the handoff-policy sweep.",
              file=sys.stderr)

    if a.mode == "mvp" and a.seeds < 5 and not a.shard_arm:
        print(f"[preflight] WARNING: --seeds {a.seeds} gives n={a.seeds}/arm. The power "
              f"analysis target should be set before the confirmatory evidence/reflection "
              f"sweep. Confirm this is a pilot, not the confirmatory sweep.",
              file=sys.stderr)

    ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    base = Path(a.out_dir) if a.out_dir else None
    rc = 0
    for task in tasks:
        if a.dry_run:
            out_dir = None
        elif base is not None:
            out_dir = base if len(tasks) == 1 else base / task
        else:
            out_dir = REPO / "workspace" / "checkpoints" / f"{ts}_handoff_{task}_{a.mode}"
        rc |= _run_task_sweep(task, a, out_dir)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
