#!/usr/bin/env python3
"""Pilot + sweep driver for the handoff study (Stage 4).

RUN ON A COMPUTE NODE with a GPU-served Ollama. This driver only sets the
per-arm env and shells out to the proven ``ari run``; it bakes in NO host /
partition / port (those come from your environment: OLLAMA_HOST, ARI_BACKEND,
SLURM allocation). See ari-core/PREREG_handoff_study.md and
ari-core/MASTER_PLAN_handoff_impl.md.

Examples (on a compute node, after starting Ollama and exporting OLLAMA_HOST):
    # 1) qwen3:8b validity-floor pilot (PREREG gate)
    python scripts/run_handoff_ablation.py --mode pilot --model qwen3:8b
    # 2) MVP 3-arm sweep on the large model, n seeds
    python scripts/run_handoff_ablation.py --mode mvp --large-model qwen3:32b --seeds 10
    # inspect the exact env+commands without running:
    python scripts/run_handoff_ablation.py --mode mvp --dry-run
"""
from __future__ import annotations

import argparse
import datetime as _dt
import glob
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
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
# 2x2 FACTORIAL over {summary on/off} x {full_log on/off}:
#   code_only          (–summary, –log)   code_plus_summary           (+summary, –log)
#   code_plus_full_log (–summary, +log)    code_plus_summary_plus_full_log (+summary, +log)
# The nested chain code ⊂ code+summary ⊂ code+summary+full_log is still present (it
# is 3 of the 4 cells); adding code_plus_full_log isolates the full_log main effect
# WITHOUT summary, so the analyzer can attribute the rewrite→refine shift to the log
# per se (not just "log on top of summary") and estimate the summary×log interaction.
# The PRIMARY (nested) contrast remains code_plus_summary vs code_plus_summary_plus_full_log.
# Override with ARI_HANDOFF_ARMS (comma-separated) to run a subset.
ARMS = os.environ.get(
    "ARI_HANDOFF_ARMS",
    "code_only,code_plus_summary,code_plus_full_log,code_plus_summary_plus_full_log",
).split(",")
# Per-arm env that pins the study controls (PREREG): frozen contract, deterministic
# evaluator + selector. memory_off is implied by each handoff mode's resolution.
_FIXED = {
    "ARI_FREEZE_CONTRACT": "1",
    "ARI_EVALUATOR": "deterministic",
    "ARI_BFTS_DETERMINISTIC": "1",
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
    # Prefer the project venv's ari entry point over any global `ari` on PATH:
    # a stale ~/.local/bin/ari can resolve to a different (broken) interpreter
    # (e.g. a pydantic-core/pydantic version mismatch in user site-packages).
    venv_ari = REPO / ".venv" / "bin" / "ari"
    if venv_ari.is_file():
        return [str(venv_ari), "run", exp]
    if shutil.which("ari"):
        return ["ari", "run", exp]
    return [sys.executable, "-m", "ari.cli", "run", exp]


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


def run_one(arm: str, model: str, seed: int, max_nodes: int, dry: bool,
            task: str = "spmm", scorer: str = "deterministic") -> tuple[int, str | None]:
    """Run one (arm, seed). Returns (returncode, run experiment dir or None).

    ``scorer`` selects what drives BFTS node selection: ``deterministic`` (the
    fixed non-LLM evaluator that owns the task metric) or ``judge`` (the system's
    LLM-as-a-judge). The scorer is orthogonal to the handoff channel under test;
    comparing the two is the scorer ablation.
    """
    overrides = dict(_FIXED)
    overrides.update({
        "ARI_TASK": task,
        "ARI_HANDOFF_MODE": arm,
        "ARI_SEED": str(seed),
        "ARI_MODEL": model,
        "ARI_MAX_NODES": str(max_nodes),
    })
    # Scorer ablation: deterministic evaluator vs LLM-as-a-judge. Task scaffolding
    # is seeded on ARI_TASK regardless, so the agent still solves meshpart either way.
    if scorer == "judge":
        overrides["ARI_EVALUATOR"] = "llm"   # any non-"deterministic" → LLMEvaluator
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
    env.update(overrides)
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
    return rc, run_dir


def _record(manifest: Path | None, **row) -> None:
    if manifest is None:
        return
    with open(manifest, "a") as fh:
        fh.write(json.dumps(row) + "\n")


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

    rc = 0
    if a.mode == "pilot":
        # validity-floor pilot: one clean arm, small N (PREREG gate (a)).
        r, run_dir = run_one("code_plus_summary", a.model, 0, a.max_nodes, a.dry_run, task, a.scorer)
        rc |= r
        _record(manifest, task=task, arm="code_plus_summary", model=a.model, seed=0,
                max_nodes=a.max_nodes, run_dir=run_dir, rc=r, scorer=a.scorer)
        print(f"\n[{task}] Pilot done. Gate: confirm >0 valid nodes; also read off the "
              f"run-level SD + invalid-run rate to size the confirmatory sweep "
              f"(power analysis targets n=50/arm — see below).")
    else:
        for seed in range(a.seed_base, a.seed_base + a.seeds):
            for arm in ARMS:
                r, run_dir = run_one(arm, a.large_model, seed, a.max_nodes, a.dry_run, task, a.scorer)
                rc |= r
                _record(manifest, task=task, arm=arm, model=a.large_model, seed=seed,
                        max_nodes=a.max_nodes, run_dir=run_dir, rc=r, scorer=a.scorer)
        if manifest:
            print(f"\n[{task}] MVP sweep done. Analyze with:\n"
                  f"  python scripts/analyze_handoff_ablation.py {manifest.parent}")
    return rc


def main() -> int:
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
    ap.add_argument("--out-dir", default=None,
                    help="manifest output dir (default workspace/checkpoints/<ts>_handoff_<task>_<mode>). "
                         "With multiple tasks, each task gets a <out-dir>/<task> subdir.")
    ap.add_argument("--scorer", choices=["deterministic", "judge"], default="deterministic",
                    help="what drives BFTS node selection: the fixed deterministic "
                         "evaluator (default) or the LLM-as-a-judge (scorer ablation)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    tasks = _resolve_tasks(a.task)

    if a.mode == "mvp" and a.seeds < 5:
        print(f"[preflight] WARNING: --seeds {a.seeds} gives n={a.seeds}/arm. The power "
              f"analysis targets n=50/arm for the primary Jonckheere-Terpstra trend "
              f"(nested chain: ~1.0 power at 1.2x/step; >=0.8 for >=1.15x at run-SD<=0.4, "
              f"incl. 5-task Bonferroni). Confirm this is a pilot, not the confirmatory sweep.",
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
