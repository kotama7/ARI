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
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXPERIMENT = REPO / "ari-core" / "ari" / "evaluator" / "spmm_kernels" / "experiment.md"
# MVP 3-arm contrast (PREREG primary = code_plus_summary vs code_plus_full_log).
ARMS = ["code_only", "code_plus_summary", "code_plus_full_log"]
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
}


def _ari_cmd() -> list[str]:
    if shutil.which("ari"):
        return ["ari", "run", str(EXPERIMENT)]
    return [sys.executable, "-m", "ari.cli", "run", str(EXPERIMENT)]


def run_one(mode: str, model: str, seed: int, max_nodes: int, dry: bool) -> int:
    overrides = dict(_FIXED)
    overrides.update({
        "ARI_HANDOFF_MODE": mode,
        "ARI_SEED": str(seed),
        "ARI_MODEL": model,
        "ARI_MAX_NODES": str(max_nodes),
    })
    label = f"{mode} | {model} | seed={seed} | N={max_nodes}"
    cmd = _ari_cmd()
    if dry:
        print(f"[dry-run] {label}")
        print("  env:", " ".join(f"{k}={v}" for k, v in overrides.items()))
        print("  cmd:", " ".join(cmd), f"(cwd={REPO})")
        return 0
    env = dict(os.environ)
    env.update(overrides)
    print(f"[run] {label}", flush=True)
    return subprocess.run(cmd, env=env, cwd=str(REPO)).returncode


def main() -> int:
    ap = argparse.ArgumentParser(description="Handoff-study pilot/sweep driver")
    ap.add_argument("--mode", choices=["pilot", "mvp"], default="pilot")
    ap.add_argument("--model", default="qwen3:8b", help="pilot model (validity floor)")
    ap.add_argument("--large-model", default="qwen3:32b", help="MVP model")
    ap.add_argument("--seeds", type=int, default=1, help="MVP: independent runs per arm")
    ap.add_argument("--max-nodes", type=int, default=10, help="best valid @ N nodes (PREREG N=10)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    if not EXPERIMENT.is_file():
        print(f"experiment not found: {EXPERIMENT}", file=sys.stderr)
        return 2

    rc = 0
    if a.mode == "pilot":
        # qwen3:8b validity-floor pilot: one clean arm, small N (PREREG gate (a)).
        rc |= run_one("code_plus_summary", a.model, 0, a.max_nodes, a.dry_run)
        print("\nPilot done. Gate: confirm >0 valid nodes in the checkpoint "
              "(workspace/checkpoints/<ts>_*); if the model floors at 0, raise "
              "the small model (e.g. qwen3:14b) per PREREG before the MVP sweep.")
    else:
        for seed in range(a.seeds):
            for arm in ARMS:
                rc |= run_one(arm, a.large_model, seed, a.max_nodes, a.dry_run)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
