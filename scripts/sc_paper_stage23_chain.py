#!/usr/bin/env python3
"""Run Stage 2 (reproduce) + Stage 3 (judge) against an already-completed
Stage 1 rollout workspace.

Use when you cancel `sc_paper_dogfood.py --with-rollout` mid-way (e.g.,
the agent entered the DEFAULT_CONTINUE_MESSAGE loop after declaring
completion) but the `submission/submission/` tree is already populated
with a usable `reproduce.sh`. ``sc_paper_dogfood.py`` does not yet
expose a ``--skip-rollout`` flag, so this script bypasses Stage 1 and
goes straight to bridge.reproduce_submission + bridge.judge_submission
against the pre-existing submission tree.

Workspace layout assumed (matches what ``sc_paper_dogfood.py
--with-rollout`` writes):

    <workspace>/
      paper.md                   # Stage 0 output
      rubric.json                # Stage 0 output (wrapped envelope)
      submission/
        paper/
          paper.md
          addendum.md            # ARI bridge writes this
        submission/              # vendor convention
          reproduce.sh
          ... (agent's commits)

Usage:

    python scripts/sc_paper_stage23_chain.py \\
        --workspace workspace/checkpoints/<UTC>_<slug> \\
        --reproduce-sandbox local \\
        --reproduce-time-limit-sec 7200 \\
        --judge-model gpt-5-mini

Outputs `<workspace>/stage23_result.json` with the full envelope
(stage 2 reproduce log path + tarball + Stage 3 graded tree + ors_score).

To dispatch Stage 2 onto a SLURM compute node instead of running on
the login host, pass:

    --reproduce-sandbox slurm \\
    --reproduce-partition ai-l40s \\
    --reproduce-gpus-per-task 1 --reproduce-gpu-type L40S-44GB

Stage 3 always runs locally (LLM API call only — no GPU needed).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "ari-skill-paper-re" / "src"))


def _to_dict(n):
    """Walk GradedTaskNode → JSON-serialisable dict."""
    children = list(n.sub_tasks) if n.sub_tasks else []
    return {
        "id": getattr(n, "id", ""),
        "requirements": getattr(n, "requirements", ""),
        "weight": int(getattr(n, "weight", 1)),
        "score": float(getattr(n, "score", 0.0)),
        "valid_score": bool(getattr(n, "valid_score", True)),
        "task_category": getattr(n, "task_category", None),
        "finegrained_task_category": getattr(n, "finegrained_task_category", None),
        "explanation": getattr(n, "explanation", ""),
        "sub_tasks": [_to_dict(c) for c in children],
    }


async def chain(args: argparse.Namespace) -> int:
    from _paperbench_bridge import (  # type: ignore
        reproduce_submission,
        judge_submission,
        task_node_from_dict,
        aggregate_graded_tree,
    )

    workspace = Path(args.workspace).resolve()
    submission_dir = workspace / "submission" / "submission"
    paper_md_path = workspace / "paper.md"
    rubric_path = workspace / "rubric.json"
    result_path = workspace / "stage23_result.json"

    for p in (submission_dir, paper_md_path, rubric_path):
        assert p.exists(), f"missing workspace artifact: {p}"
    assert (submission_dir / "reproduce.sh").is_file(), (
        f"missing reproduce.sh under {submission_dir}; Stage 1 rollout "
        "may not have completed enough to produce one"
    )

    paper_md = paper_md_path.read_text()
    rubric_wrapper = json.loads(rubric_path.read_text())
    rubric_tree = rubric_wrapper.get("rubric") or rubric_wrapper
    rubric_node = task_node_from_dict(rubric_tree)

    t2 = time.time()
    print(f"[stage2] reproduce_submission(sandbox={args.reproduce_sandbox} "
          f"time_limit={args.reproduce_time_limit_sec}s) → {submission_dir}/")
    repro = await reproduce_submission(
        submission_dir=str(submission_dir),
        sandbox_kind=args.reproduce_sandbox,
        time_limit_sec=int(args.reproduce_time_limit_sec),
        partition=args.reproduce_partition or "",
        gpus_per_task=int(args.reproduce_gpus_per_task),
        gpu_type=args.reproduce_gpu_type or "",
        capture_tarball=True,
        tarball_dir=str(workspace),
    )
    elapsed2 = time.time() - t2
    print(f"[stage2] exit_code={repro.get('exit_code')} "
          f"elapsed_sec={elapsed2:.1f} "
          f"reproduce_log_path={repro.get('reproduce_log_path')}")

    reproduce_log = ""
    log_path = repro.get("reproduce_log_path")
    if log_path and Path(log_path).is_file():
        reproduce_log = Path(log_path).read_text()

    t3 = time.time()
    print(f"\n[stage3] judge_submission(model={args.judge_model}) "
          f"reproduce_log={'present' if reproduce_log else 'empty'} "
          f"({len(reproduce_log)} chars)")
    graded = await judge_submission(
        paper_md=paper_md,
        rubric=rubric_node,
        submission_dir=str(submission_dir),
        reproduce_log=reproduce_log,
        judge_model=args.judge_model,
    )
    elapsed3 = time.time() - t3
    agg = aggregate_graded_tree(graded)
    leaves = agg.get("leaf_grades") or []
    n_leaves = len(leaves)
    n_passed = sum(1 for lg in leaves if lg.get("passed_runs", 0) >= 1)
    print(f"[stage3] elapsed_sec={elapsed3:.1f} "
          f"ors_score={agg['ors_score']:.4f} "
          f"raw_score={agg['raw_score']:.4f} "
          f"leaves_passed={n_passed}/{n_leaves}")

    envelope = {
        "workspace": str(workspace),
        "submission_dir": str(submission_dir),
        "stage2": {
            "elapsed_sec": elapsed2,
            **{k: v for k, v in repro.items() if k != "reproduce_log"},
        },
        "stage3": {
            "elapsed_sec": elapsed3,
            "judge_model": args.judge_model,
            "ors_score": agg["ors_score"],
            "raw_score": agg["raw_score"],
            "leaves_passed": n_passed,
            "num_leaves": n_leaves,
            "leaf_grades": agg.get("leaf_grades") or [],
            "graded": _to_dict(graded),
        },
    }
    result_path.write_text(json.dumps(envelope, indent=2, default=str))
    print(f"\n[done] wrote {result_path}")
    return 0 if repro.get("exit_code") == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workspace", required=True,
                    help="Path to a checkpoint workspace already populated "
                         "by `sc_paper_dogfood.py --with-rollout` (must "
                         "contain paper.md, rubric.json, "
                         "submission/submission/reproduce.sh).")
    ap.add_argument("--reproduce-sandbox", default="local",
                    choices=("local", "slurm", "apptainer", "singularity"),
                    help="Where to run reproduce.sh (default: local — runs "
                         "on the calling host).")
    ap.add_argument("--reproduce-time-limit-sec", type=int, default=7200,
                    help="Wall-clock cap for Stage 2 reproduce.sh execution.")
    ap.add_argument("--reproduce-partition", default="",
                    help="SLURM partition (when --reproduce-sandbox=slurm).")
    ap.add_argument("--reproduce-gpus-per-task", type=int, default=0,
                    help="GPUs per task (when --reproduce-sandbox=slurm).")
    ap.add_argument("--reproduce-gpu-type", default="",
                    help="GRES gpu type (when --reproduce-sandbox=slurm), "
                         "e.g., L40S-44GB.")
    ap.add_argument("--judge-model", default="gpt-5-mini",
                    help="Model id for Stage 3 SimpleJudge.")
    args = ap.parse_args()
    return asyncio.run(chain(args))


if __name__ == "__main__":
    raise SystemExit(main())
