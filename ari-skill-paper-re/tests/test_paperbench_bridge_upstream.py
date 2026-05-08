"""Bridge ↔ upstream PaperBench compatibility tests.

The bridge always uses the upstream PaperBench (no local fallback) — these
tests assert that the bridge's helper API agrees with the upstream
``TaskNode`` and ``GradedTaskNode`` shape. They skip if PaperBench upstream
is not importable (i.e., ``setup.sh`` / ``scripts/setup/install_paperbench.sh``
has not been run).

We do NOT exercise the LLM-driven ``SimpleJudge.judge()`` here: that requires
an OpenAI key and a real model call. ``test_run_reproduce_and_grade.py``
contains the live LLM tests guarded by ``OPENAI_API_KEY``.
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

_spec = importlib.util.spec_from_file_location("paper_re_bridge_upstream", SRC / "_paperbench_bridge.py")
B = importlib.util.module_from_spec(_spec)
sys.modules["paper_re_bridge_upstream"] = B
try:
    _spec.loader.exec_module(B)
    _UPSTREAM_OK = True
    _UPSTREAM_ERR = ""
except Exception as e:  # noqa: BLE001
    _UPSTREAM_OK = False
    _UPSTREAM_ERR = f"{type(e).__name__}: {e}"

pytestmark = pytest.mark.skipif(
    not _UPSTREAM_OK,
    reason=f"PaperBench upstream not importable ({_UPSTREAM_ERR}); run scripts/setup/install_paperbench.sh",
)


def _leaf_dict(text: str, weight: int = 1) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "requirements": text,
        "weight": weight,
        "sub_tasks": [],
        "task_category": "Code Development",
        "finegrained_task_category": "Method Implementation",
    }


def _root_dict(leaves: list[dict]) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "requirements": "Replicate the paper's main contribution.",
        "weight": 1,
        "sub_tasks": leaves,
    }


def test_bridge_loads_upstream_modules():
    """All re-exported symbols must come from the upstream paperbench.* package."""
    assert B.TaskNode.__module__.startswith("paperbench.")
    assert B.GradedTaskNode.__module__.startswith("paperbench.")
    assert B.SimpleJudge.__module__.startswith("paperbench.")


def test_task_node_from_dict_constructs_upstream_dataclass():
    """The dict → upstream TaskNode round-trip preserves shape and types."""
    pb = _root_dict([
        _leaf_dict("Implement the MaskNetwork outputs zero for critical states.", 2),
        _leaf_dict("Run Experiment II producing pre-refinement and post-refinement metrics.", 3),
    ])
    node = B.task_node_from_dict(pb)
    assert isinstance(node, B.TaskNode)
    assert node.weight == 1
    assert len(node.sub_tasks) == 2
    leaf0 = node.sub_tasks[0]
    assert isinstance(leaf0, B.TaskNode)
    assert leaf0.weight == 2
    assert leaf0.requirements.startswith("Implement the MaskNetwork")
    # PaperBench freezes the dataclass; mutating must raise.
    with pytest.raises(Exception):
        leaf0.requirements = "tampered"  # type: ignore[misc]


def test_aggregate_graded_tree_matches_paperbench_weighted_score():
    """Build a GradedTaskNode tree using the upstream class directly and verify
    that the bridge's aggregate function reproduces the weighted formula."""
    g_pass = B.GradedTaskNode(
        id="l1",
        requirements="x",
        weight=2,
        sub_tasks=(),
        score=1.0,
        valid_score=True,
        explanation="pass",
        task_category="Code Development",
        judge_metadata=None,
    )
    g_fail = B.GradedTaskNode(
        id="l2",
        requirements="y",
        weight=2,
        sub_tasks=(),
        score=0.0,
        valid_score=True,
        explanation="fail",
        task_category="Code Execution",
        judge_metadata=None,
    )
    expected_root_score = (2 * 1.0 + 2 * 0.0) / (2 + 2)
    g_root = B.GradedTaskNode(
        id="r",
        requirements="root",
        weight=1,
        sub_tasks=(g_pass, g_fail),
        score=expected_root_score,
        valid_score=True,
        explanation="",
        task_category=None,
        judge_metadata=None,
    )
    agg = B.aggregate_graded_tree(g_root)
    assert agg["ors_score"] == pytest.approx(0.5)
    assert agg["raw_score"] == pytest.approx(0.5)
    assert {lg["id"] for lg in agg["leaf_grades"]} == {"l1", "l2"}


def test_average_graded_runs_with_upstream_classes():
    """average_graded_runs must work over GradedTaskNode trees from upstream."""
    def _make_root(score: float) -> "B.GradedTaskNode":
        leaf = B.GradedTaskNode(
            id="l1",
            requirements="x",
            weight=1,
            sub_tasks=(),
            score=score,
            valid_score=True,
            explanation="",
            task_category="Code Development",
            judge_metadata=None,
        )
        return B.GradedTaskNode(
            id="r",
            requirements="root",
            weight=1,
            sub_tasks=(leaf,),
            score=score,
            valid_score=True,
            explanation="",
            task_category=None,
            judge_metadata=None,
        )

    runs = [_make_root(1.0), _make_root(0.0), _make_root(1.0)]
    agg = B.average_graded_runs(runs)
    assert agg["leaf_grades"][0]["passed_runs"] == 2
    assert agg["leaf_grades"][0]["n_runs"] == 3
    assert agg["leaf_grades"][0]["mean_score"] == pytest.approx(2 / 3)
