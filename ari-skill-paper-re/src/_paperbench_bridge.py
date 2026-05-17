"""PaperBench SimpleJudge bridge.

This module re-exports the PaperBench upstream symbols used by
``grade_with_simplejudge`` and provides thin adapters for the calling
convention used inside ARI:

  - ``TaskNode``                 — paperbench.rubric.tasks.TaskNode
  - ``GradedTaskNode``           — paperbench.judge.graded_task_node.GradedTaskNode
  - ``SimpleJudge``              — paperbench.judge.simple.SimpleJudge
  - ``task_node_from_dict``      — dict → upstream TaskNode
  - ``aggregate_graded_tree``    — weighted tree score envelope
  - ``average_graded_runs``      — n-run mean over GradedTaskNode trees
  - ``judge_submission``         — async adapter that wires our (paper_md,
                                    submission_dir, reproduce_log, judge_model)
                                    inputs into a real upstream SimpleJudge run.

Resolution of the upstream package follows:
  1. ``ARI_PAPERBENCH_PATH`` (explicit override).
  2. The vendored git submodule at vendor/paperbench/project/paperbench.
     The submodule URL is github.com/openai/preparedness (a monorepo) but
     it is mounted at vendor/paperbench so the layout matches rubric.md §8.
  3. A pip-installed ``paperbench`` package on the standard sys.path.

The upstream depends on ``openai``, ``preparedness_turn_completer``,
``nanoeval``, ``alcatraz``, ``structlog``, ``tiktoken``, ``drain3``,
``blobfile``, etc. Run ``scripts/setup/install_paperbench.sh`` (invoked
automatically by ``setup.sh``) to install them. Without these packages
this module fails to import — there is **no local fallback**.
"""

from __future__ import annotations

import logging
import os
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


# ─── locate upstream PaperBench ───────────────────────────────────────────
# Path injection happens in :mod:`_vendor_path` so that the agent-mode
# Replicator and the SimpleJudge bridge load from the same vendor tree.

import _vendor_path  # noqa: F401  (side-effect: sys.path injection)


# ─── re-export upstream symbols (no fallback) ────────────────────────────

from paperbench.rubric.tasks import TaskNode  # noqa: E402  type: ignore
from paperbench.judge.graded_task_node import GradedTaskNode  # noqa: E402  type: ignore
from paperbench.judge.simple import SimpleJudge  # noqa: E402  type: ignore

log.info("paperbench upstream loaded (sys.path injected by _vendor_path)")


# ─── helpers ──────────────────────────────────────────────────────────────


def task_node_from_dict(d: dict) -> TaskNode:
    """Construct an upstream TaskNode from our PaperBench-format dict."""
    return TaskNode(
        id=str(d.get("id") or uuid.uuid4()),
        requirements=str(d.get("requirements", "")),
        weight=int(d.get("weight", 1)),
        sub_tasks=tuple(task_node_from_dict(c) for c in (d.get("sub_tasks") or [])),
        task_category=d.get("task_category"),
        finegrained_task_category=d.get("finegrained_task_category"),
    )


def aggregate_graded_tree(graded: GradedTaskNode) -> dict:
    """Reproduce PaperBench's weighted aggregation (and the unweighted score).

    weighted: sum(child.weight * child.score) / sum(child.weight) recursively.
    unweighted: mean of leaf 0/1 scores.
    """
    leaves: list[GradedTaskNode] = []

    def _walk(n: GradedTaskNode) -> None:
        children = list(n.sub_tasks) if n.sub_tasks else []
        if not children:
            leaves.append(n)
            return
        for c in children:
            _walk(c)

    _walk(graded)
    raw = (sum(1.0 if g.score >= 0.5 else 0.0 for g in leaves) / max(1, len(leaves)))

    return {
        "ors_score": float(graded.score),
        "raw_score": float(raw),
        "leaf_grades": [
            {
                "id": g.id,
                "requirements": g.requirements,
                "weight": int(g.weight),
                "task_category": g.task_category,
                "passed_runs": int(g.score >= 0.5),
                "n_runs": 1,
                "mean_score": float(g.score),
                "explanation": g.explanation,
            }
            for g in leaves
        ],
    }


def average_graded_runs(runs: list[GradedTaskNode]) -> dict:
    """Average leaf scores across multiple SimpleJudge runs."""
    if not runs:
        return {"ors_score": 0.0, "raw_score": 0.0, "leaf_grades": []}
    if len(runs) == 1:
        return aggregate_graded_tree(runs[0])

    leaf_runs: dict[str, list[GradedTaskNode]] = {}

    def _collect(n: GradedTaskNode) -> None:
        if not n.sub_tasks:
            leaf_runs.setdefault(n.id, []).append(n)
            return
        for c in n.sub_tasks:
            _collect(c)

    for r in runs:
        _collect(r)

    template = runs[0]
    n_runs = len(runs)

    def _rebuild(n: GradedTaskNode) -> GradedTaskNode:
        if not n.sub_tasks:
            scores = [g.score for g in leaf_runs.get(n.id, [n])]
            mean = sum(scores) / max(1, len(scores))
            kwargs = dict(
                id=n.id, requirements=n.requirements, weight=int(n.weight),
                sub_tasks=(), score=mean, explanation=n.explanation,
                task_category=n.task_category,
                valid_score=getattr(n, "valid_score", True),
                judge_metadata=getattr(n, "judge_metadata", None),
            )
            return GradedTaskNode(**kwargs)
        children = tuple(_rebuild(c) for c in n.sub_tasks)
        total_w = sum(c.weight for c in children) or 1
        score = sum(c.weight * c.score for c in children) / total_w
        kwargs = dict(
            id=n.id, requirements=n.requirements, weight=int(n.weight),
            sub_tasks=children, score=score, explanation=n.explanation,
            task_category=n.task_category,
            valid_score=getattr(n, "valid_score", True),
            judge_metadata=getattr(n, "judge_metadata", None),
        )
        return GradedTaskNode(**kwargs)

    averaged = _rebuild(template)
    agg = aggregate_graded_tree(averaged)
    for lg in agg["leaf_grades"]:
        runs_for = leaf_runs.get(lg["id"], [])
        passed = sum(1 for g in runs_for if g.score >= 0.5)
        lg["passed_runs"] = passed
        lg["n_runs"] = n_runs
    return agg


# ─── async adapter: our calling convention → upstream SimpleJudge ─────────


_PAPER_AUDIT_QUESTIONS = {
    "Code Development": (
        "Does the paper or its AD/AE Appendix describe this implementation "
        "detail with concrete, reconstructable specificity — concrete "
        "versions, parameters, configuration, file paths, or code "
        "fragments? Mere mentions or vague descriptions are NOT sufficient. "
        "Note: a submission may not exist; in paper_audit mode you are "
        "scoring the paper's self-description, not whether a submission "
        "reproduces it."
    ),
    "Code Execution": (
        "Does the paper or its AD/AE Appendix document the execution "
        "procedure for this (commands, scripts, sbatch parameters, "
        "environment variables, hardware setup) with enough detail that "
        "an HPC practitioner could reproduce it without consulting the "
        "authors? Note: a submission may not exist; in paper_audit mode "
        "you are scoring the paper's self-description, not whether a "
        "submission reproduces it."
    ),
    "Result Analysis": (
        "Is the paper's claim INTERNALLY CONSISTENT with the experimental "
        "evidence presented elsewhere in the paper (figures, tables, "
        "body text, AD/AE Appendix)? Cross-check the textual claim "
        "against the numerical or visual evidence — both the magnitude "
        "and the scaling trend must match within reasonable tolerance. "
        "Note: a submission may not exist; in paper_audit mode you are "
        "checking the paper's own internal consistency, not whether a "
        "submission reproduced the result."
    ),
    "Subtree": "What is the weighted score of all the criteria in the subtree?",
}


def _patch_task_category_questions(replacement: dict[str, str] | None = None):
    """Context manager: swap PaperBench's ``TASK_CATEGORY_QUESTIONS`` so
    SimpleJudge's grading prompt asks paper-audit-flavored questions
    instead of submission-flavored ones.

    The vendor ``simple.py`` imports the constant into its module
    namespace at module load time, so both
    ``paperbench.rubric.tasks.TASK_CATEGORY_QUESTIONS`` AND
    ``paperbench.judge.simple.TASK_CATEGORY_QUESTIONS`` must be patched
    to make the override take effect. Always restored on exit so the
    agent-benchmark code path is unaffected by a paper_audit call.
    """
    import contextlib
    import paperbench.judge.simple as ps_simple  # type: ignore
    import paperbench.rubric.tasks as ps_tasks   # type: ignore

    if replacement is None:
        replacement = _PAPER_AUDIT_QUESTIONS

    @contextlib.contextmanager
    def _patch():
        orig_simple = ps_simple.TASK_CATEGORY_QUESTIONS
        orig_tasks = ps_tasks.TASK_CATEGORY_QUESTIONS
        ps_simple.TASK_CATEGORY_QUESTIONS = replacement
        ps_tasks.TASK_CATEGORY_QUESTIONS = replacement
        try:
            yield
        finally:
            ps_simple.TASK_CATEGORY_QUESTIONS = orig_simple
            ps_tasks.TASK_CATEGORY_QUESTIONS = orig_tasks
    return _patch()


async def judge_submission(
    *,
    paper_md: str,
    rubric: TaskNode,
    submission_dir: Path,
    reproduce_log: str = "",
    judge_model: str,
    addendum: str | None = None,
    judge_addendum: str | None = None,
    paper_audit_mode: bool = False,
) -> GradedTaskNode:
    """Run upstream SimpleJudge against the given submission.

    The upstream constructor wants ``paper_path`` and ``paper_md`` as
    ``Path`` objects and reads ``reproduce.sh`` / ``reproduce.log`` from
    ``submission_dir``. This wrapper writes ``paper_md`` to a temp file and,
    if the caller provided an inline ``reproduce_log`` string, persists it
    into ``submission_dir/reproduce.log`` so the judge can find it.

    ``paper_audit_mode``: when True, the vendor's
    ``TASK_CATEGORY_QUESTIONS`` (which asks about a submission's code /
    reproduce.sh / produced evidence) is monkey-patched to paper-audit
    questions (about the paper's own self-description and internal
    consistency) for the duration of the call. This breaks the structural
    ceiling where ``Result Analysis`` leaves always score 0 with an empty
    submission. The override is scoped to this call only; agent-benchmark
    callers see the original vendor prompt.
    """
    # Main per-leaf grading completer routes through LiteLLM so any provider
    # works (OpenAI snapshots not in PaperBench's CONTEXT_WINDOW_LENGTHS,
    # Anthropic, Gemini, Ollama, …). The int/float structured completers
    # SimpleJudge constructs internally still default to gpt-4o-2024-08-06
    # via OpenAI direct — that is fine because that model IS in the registry
    # and the parse step is small.
    from _litellm_completer import LiteLLMTurnCompleter

    submission_dir = Path(submission_dir)
    submission_dir.mkdir(parents=True, exist_ok=True)
    if reproduce_log:
        log_path = submission_dir / "reproduce.log"
        if not log_path.is_file():
            log_path.write_text(reproduce_log)

    with tempfile.TemporaryDirectory() as tmp:
        paper_md_path = Path(tmp) / "paper.md"
        paper_md_path.write_text(paper_md or "")
        cfg = LiteLLMTurnCompleter.Config(model=judge_model)
        judge = SimpleJudge(
            paper_path=paper_md_path,
            rubric=rubric,
            addendum=addendum,
            judge_addendum=judge_addendum,
            submission_dir=submission_dir,
            paper_md=paper_md_path,
            completer_config=cfg,
        )
        if paper_audit_mode:
            with _patch_task_category_questions():
                await judge.before_grading()
                return await judge.grade(rubric, judge.grade_leaf)
        else:
            await judge.before_grading()
            return await judge.grade(rubric, judge.grade_leaf)
