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
