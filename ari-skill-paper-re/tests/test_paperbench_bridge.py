"""Tests for the PaperBench bridge (Step 3 / 5.1 DoD).

These tests exercise the bridge's structural surface — TaskNode construction
from dicts, weighted aggregation, and run averaging. They use the upstream
GradedTaskNode/TaskNode (no local fallback exists). The LLM-driven
SimpleJudge.judge() path is exercised separately in
test_paperbench_bridge_upstream.py — those tests need a real OpenAI key and
are skipped on CI by default.
"""

from __future__ import annotations

import importlib.util
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for p in (str(ROOT), str(SRC)):
    if p not in sys.path:
        sys.path.insert(0, p)

_spec = importlib.util.spec_from_file_location("paper_re_bridge", SRC / "_paperbench_bridge.py")
B = importlib.util.module_from_spec(_spec)
sys.modules["paper_re_bridge"] = B
_spec.loader.exec_module(B)


def _leaf(text: str, weight: int = 1) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "requirements": text,
        "weight": weight,
        "sub_tasks": [],
        "task_category": "Code Development",
        "finegrained_task_category": "Method Implementation",
    }


def _root_pb_dict(leaves: list[dict]) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "requirements": "Replicate the paper's main contribution.",
        "weight": 1,
        "sub_tasks": leaves,
        "task_category": None,
    }


def _graded_leaf(id_: str, *, score: float, weight: int = 1, category: str = "Code Development") -> "B.GradedTaskNode":
    return B.GradedTaskNode(
        id=id_, requirements="x", weight=weight, sub_tasks=(), score=score,
        valid_score=True, explanation="", task_category=category,
        judge_metadata=None,
    )


def _graded_internal(id_: str, children, *, score: float, weight: int = 1) -> "B.GradedTaskNode":
    return B.GradedTaskNode(
        id=id_, requirements="root", weight=weight, sub_tasks=tuple(children),
        score=score, valid_score=True, explanation="", task_category=None,
        judge_metadata=None,
    )


def test_task_node_from_dict_round_trip():
    pb = _root_pb_dict([_leaf("Implement MaskNetwork outputs zero for critical states.")])
    node = B.task_node_from_dict(pb)
    assert node.requirements.startswith("Replicate the paper")
    assert len(node.sub_tasks) == 1
    leaf = node.sub_tasks[0]
    assert leaf.weight == 1
    assert leaf.task_category == "Code Development"


def test_aggregate_graded_tree_unweighted_and_weighted():
    g_pass = _graded_leaf("l1", score=1.0, weight=2)
    g_fail = _graded_leaf("l2", score=0.0, weight=2, category="Code Execution")
    expected = (2 * 1.0 + 2 * 0.0) / (2 + 2)
    g_root = _graded_internal("r", [g_pass, g_fail], score=expected)
    agg = B.aggregate_graded_tree(g_root)
    assert agg["ors_score"] == pytest.approx(0.5)
    assert agg["raw_score"] == pytest.approx(0.5)
    assert len(agg["leaf_grades"]) == 2


def test_average_graded_runs_passed_runs_count():
    g_root_pass = _graded_internal("r", [_graded_leaf("l1", score=1.0)], score=1.0)
    g_root_fail = _graded_internal("r", [_graded_leaf("l1", score=0.0)], score=0.0)
    agg = B.average_graded_runs([g_root_pass, g_root_fail, g_root_pass])
    assert agg["leaf_grades"][0]["passed_runs"] == 2
    assert agg["leaf_grades"][0]["n_runs"] == 3
    assert agg["leaf_grades"][0]["mean_score"] == pytest.approx(2 / 3)


def test_average_graded_runs_single_run_is_aggregate():
    """Single-run case is equivalent to aggregate_graded_tree for scoring."""
    g = _graded_internal("r", [_graded_leaf("l1", score=1.0), _graded_leaf("l2", score=0.0)], score=0.5)
    agg = B.average_graded_runs([g])
    assert agg["ors_score"] == pytest.approx(0.5)


def test_average_graded_runs_empty_list_is_zero():
    agg = B.average_graded_runs([])
    assert agg["ors_score"] == 0.0
    assert agg["leaf_grades"] == []


def test_judge_submission_is_async_callable():
    """The async LLM-driven adapter exists. Real LLM calls are exercised in
    test_paperbench_bridge_upstream.py (skipped without OPENAI_API_KEY)."""
    import inspect
    assert inspect.iscoroutinefunction(B.judge_submission)


def test_three_stage_adapters_share_calling_style():
    """Stage 1 (rollout_submission), Stage 2 (reproduce_submission), and
    Stage 3 (judge_submission) are exposed as keyword-only async callables
    so a caller can sequence them with explicit field names. This is the
    public surface the dogfood script and the viz worker consume.
    """
    import inspect
    for fn_name in ("rollout_submission", "reproduce_submission", "judge_submission"):
        fn = getattr(B, fn_name)
        assert inspect.iscoroutinefunction(fn), f"{fn_name} must be async"
        sig = inspect.signature(fn)
        # All params keyword-only (no positional surprises).
        kinds = {p.kind for p in sig.parameters.values()}
        assert kinds == {inspect.Parameter.KEYWORD_ONLY}, (
            f"{fn_name} parameters must all be keyword-only; got kinds={kinds}"
        )


def test_rollout_submission_signature_includes_container_image_and_sandbox():
    """Regression for the container_image / sandbox_kind pipeline: the
    Stage 1 adapter must expose both so a caller can opt into Apptainer
    isolation (the only Stage 1 sandbox with real container isolation).
    """
    import inspect
    sig = inspect.signature(B.rollout_submission)
    params = set(sig.parameters)
    for required in (
        "paper_md", "work_dir", "agent_model",
        "container_image", "sandbox_kind",
        "iterative_agent", "time_limit_sec",
    ):
        assert required in params, f"rollout_submission missing {required!r}"


def test_reproduce_submission_signature_honors_sandbox_and_slurm_flags():
    """Regression for the Stage 2 wiring: the adapter must expose
    container_image plus the SLURM resource flags so a wizard request
    flows through verbatim.
    """
    import inspect
    sig = inspect.signature(B.reproduce_submission)
    params = set(sig.parameters)
    for required in (
        "submission_dir", "sandbox_kind", "container_image",
        "time_limit_sec", "partition",
        "gpus_per_task", "gpu_type", "memory_gb_per_node",
        "exclusive", "extra_sbatch_args",
    ):
        assert required in params, f"reproduce_submission missing {required!r}"


def test_judge_submission_code_only_prunes_rubric_tree():
    """Mirror of vendor ``paperbench/grade.py:109-112``: when
    ``code_only=True`` is passed, the rubric tree is reduced to
    Code Development leaves only (per ``TaskNode.code_only`` in
    ``rubric/tasks.py:338-344``) BEFORE SimpleJudge is constructed.

    This is the structural test (the reducer call is what matters; the
    actual LLM-driven grade_leaf is exercised in the upstream test).
    We exercise reduce-then-aggregate which gives an apples-to-apples
    comparison: graded.score over a pruned tree counts only Code Dev.
    """
    import uuid
    rubric_dict = {
        "id": str(uuid.uuid4()),
        "requirements": "root",
        "weight": 1,
        "sub_tasks": [
            {"id": str(uuid.uuid4()), "requirements": "implement X",
             "weight": 1, "task_category": "Code Development"},
            {"id": str(uuid.uuid4()), "requirements": "run Y",
             "weight": 1, "task_category": "Code Execution"},
            {"id": str(uuid.uuid4()), "requirements": "analyze Z",
             "weight": 1, "task_category": "Result Analysis"},
        ],
    }
    root = B.task_node_from_dict(rubric_dict)

    # Pre-reduction: 3 leaves spanning all three categories.
    leaves_before = []
    def _walk(n):
        if not n.sub_tasks:
            leaves_before.append(n)
        for c in n.sub_tasks:
            _walk(c)
    _walk(root)
    assert len(leaves_before) == 3
    assert {l.task_category for l in leaves_before} == {
        "Code Development", "Code Execution", "Result Analysis"
    }

    # Post-reduction (the vendor method used inside judge_submission).
    pruned = root.code_only()
    assert pruned is not None
    leaves_after = []
    def _walk2(n):
        if not n.sub_tasks:
            leaves_after.append(n)
        for c in n.sub_tasks:
            _walk2(c)
    _walk2(pruned)
    assert len(leaves_after) == 1
    assert leaves_after[0].task_category == "Code Development"
    assert leaves_after[0].requirements == "implement X"


def test_judge_submission_rejects_code_only_with_paper_audit_mode():
    """code_only (grade a Stage 1 submission against Code Dev subtree)
    and paper_audit_mode (grade the paper itself for describability)
    are conceptually orthogonal targets. Combining them would feed an
    executed-or-not submission to a judge asking 'is the paper specific
    enough?' — meaningless. The bridge MUST refuse loudly.
    """
    import asyncio, uuid
    rubric_dict = {
        "id": str(uuid.uuid4()),
        "requirements": "root",
        "weight": 1,
        "task_category": "Code Development",
    }
    root = B.task_node_from_dict(rubric_dict)
    with pytest.raises(ValueError, match="mutually exclusive"):
        asyncio.run(B.judge_submission(
            paper_md="x", rubric=root, submission_dir=Path("/tmp"),
            judge_model="test/m",
            paper_audit_mode=True, code_only=True,
        ))
