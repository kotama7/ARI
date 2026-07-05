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
# The deterministic task: spmm (default) or gemm (task A — wide optimization
# gradient). Each maps to its experiment fixture; the env var ARI_TASK selects
# the evaluator's measurement + scaffolding + scoring scale.
_EVAL = REPO / "ari-core" / "ari" / "evaluator"
EXPERIMENTS = {
    "spmm": _EVAL / "spmm_kernels" / "experiment.md",
    "gemm": _EVAL / "gemm_kernels" / "experiment.md",
    "erfc": _EVAL / "erfc_kernels" / "experiment.md",
    "meshpart": _EVAL / "meshpart_kernels" / "experiment.md",
    "stencil": _EVAL / "stencil_kernels" / "experiment.md",
}
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
    # The study analyses BFTS node speedups, not papers — skip the 24-stage
    # paper pipeline that otherwise dominates per-run wall-clock.
    "ARI_SKIP_PAPER": "1",
}


def _ari_cmd(task: str) -> list[str]:
    exp = str(EXPERIMENTS[task])
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
    label = f"{task} | {arm} | {model} | seed={seed} | N={max_nodes} | scorer={scorer}"
    cmd = _ari_cmd(task)
    if dry:
        print(f"[dry-run] {label}")
        print("  env:", " ".join(f"{k}={v}" for k, v in overrides.items()))
        print("  cmd:", " ".join(cmd), f"(cwd={REPO})")
        return 0, None
    env = dict(os.environ)
    env.update(overrides)
    print(f"[run] {label}", flush=True)
    before = _experiment_dirs()
    # DETERMINISTIC run-dir attribution: capture ARI's output and parse the
    # experiments/<run_id>/ path it logs for its own node work dirs. The previous
    # before/after diff of experiments/ is NOT concurrency-safe — with several
    # shards running at once it mis-attributes a run to a sibling shard's dir
    # (and the *_int_part name variants compounded it), corrupting the analyzer's
    # per-run scoring. Parsing this process's own stdout is race-free.
    proc = subprocess.run(cmd, env=env, cwd=str(REPO), capture_output=True, text=True)
    rc = proc.returncode
    out = (proc.stdout or "") + "\n" + (proc.stderr or "")
    print(out, flush=True)  # keep the run log (no longer live-streamed)
    run_dir = None
    hits = re.findall(r'experiments/([0-9]{8,}_[^/\s"\']+)/node_', out)
    if hits:
        run_id = Counter(hits).most_common(1)[0][0]
        cand = str(REPO / "experiments" / run_id)
        if os.path.isdir(cand):
            run_dir = cand
    if run_dir is None:  # fallback (single-run / non-concurrent): before/after diff
        new = sorted(_experiment_dirs() - before)
        node_bearing = [d for d in new if glob.glob(d + "/node_*")]
        run_dir = (node_bearing or new)[-1] if new else None
    return rc, run_dir


def _record(manifest: Path | None, **row) -> None:
    if manifest is None:
        return
    with open(manifest, "a") as fh:
        fh.write(json.dumps(row) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description="Handoff-study pilot/sweep driver")
    ap.add_argument("--mode", choices=["pilot", "mvp"], default="pilot")
    ap.add_argument("--task", choices=["spmm", "gemm", "erfc", "meshpart", "stencil"], default="spmm",
                    help="deterministic task (gemm = compute-bound perf kernel; spmm = bandwidth-bound perf kernel; "
                         "stencil = 3-D Jacobi perf kernel with temporal-blocking headroom; "
                         "erfc = numerical accuracy-coverage; meshpart = combinatorial balanced k-way partitioning)")
    ap.add_argument("--model", default="qwen3:8b", help="pilot model (validity floor)")
    ap.add_argument("--large-model", default="qwen3:32b", help="MVP model")
    ap.add_argument("--seeds", type=int, default=1, help="MVP: independent runs per arm")
    ap.add_argument("--seed-base", type=int, default=0,
                    help="MVP: first seed (for sharding a sweep across jobs: each "
                         "shard runs seeds [seed_base, seed_base+seeds))")
    ap.add_argument("--max-nodes", type=int, default=10, help="best valid @ N nodes (PREREG N=10)")
    ap.add_argument("--out-dir", default=None,
                    help="manifest output dir (default workspace/checkpoints/<ts>_handoff_<mode>)")
    ap.add_argument("--scorer", choices=["deterministic", "judge"], default="deterministic",
                    help="what drives BFTS node selection: the fixed deterministic "
                         "evaluator (default) or the LLM-as-a-judge (scorer ablation)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    exp = EXPERIMENTS[a.task]
    if not exp.is_file():
        print(f"experiment not found: {exp}", file=sys.stderr)
        return 2

    manifest = None
    if not a.dry_run:
        ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = Path(a.out_dir) if a.out_dir else REPO / "workspace" / "checkpoints" / f"{ts}_handoff_{a.task}_{a.mode}"
        out_dir.mkdir(parents=True, exist_ok=True)
        manifest = out_dir / "manifest.jsonl"
        print(f"[driver] task={a.task} manifest -> {manifest}")

    rc = 0
    if a.mode == "pilot":
        # validity-floor pilot: one clean arm, small N (PREREG gate (a)).
        r, run_dir = run_one("code_plus_summary", a.model, 0, a.max_nodes, a.dry_run, a.task, a.scorer)
        rc |= r
        _record(manifest, task=a.task, arm="code_plus_summary", model=a.model, seed=0,
                max_nodes=a.max_nodes, run_dir=run_dir, rc=r, scorer=a.scorer)
        print("\nPilot done. Gate: confirm >0 valid nodes in the run dir; if the "
              "model floors at 0, raise the small model (e.g. qwen3:14b) per "
              "PREREG before the MVP sweep.")
    else:
        for seed in range(a.seed_base, a.seed_base + a.seeds):
            for arm in ARMS:
                r, run_dir = run_one(arm, a.large_model, seed, a.max_nodes, a.dry_run, a.task, a.scorer)
                rc |= r
                _record(manifest, task=a.task, arm=arm, model=a.large_model, seed=seed,
                        max_nodes=a.max_nodes, run_dir=run_dir, rc=r, scorer=a.scorer)
        if manifest:
            print(f"\nMVP sweep done. Analyze with:\n"
                  f"  python scripts/analyze_handoff_ablation.py {manifest.parent}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
