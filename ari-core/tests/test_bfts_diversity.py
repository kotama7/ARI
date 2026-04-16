"""Tests for BFTS diversity / score-collapse fixes (issue #19).

Covers:
- LLMEvaluator injects sibling-score calibration context into the prompt
- BFTS.expand() prompt no longer contains a hardcoded label list
- BFTS.diversity_bonus() rewards underrepresented exploration labels
"""
from __future__ import annotations

import re
from unittest.mock import MagicMock, patch

import pytest

from ari.config import BFTSConfig
from ari.evaluator.llm_evaluator import LLMEvaluator
from ari.llm.client import LLMClient, LLMResponse
from ari.orchestrator.bfts import BFTS
from ari.orchestrator.node import Node, NodeLabel


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_llm():
    return MagicMock(spec=LLMClient)


@pytest.fixture
def mock_memory():
    m = MagicMock()
    m.search.return_value = []
    return m


@pytest.fixture
def bfts(mock_llm):
    cfg = BFTSConfig(max_depth=4, max_retries_per_node=2, max_total_nodes=20)
    return BFTS(cfg, mock_llm)


# ──────────────────────────────────────────────────────────────────────────────
# Fix 1: LLMEvaluator score calibration context
# ──────────────────────────────────────────────────────────────────────────────


def _fake_completion_response(payload_json: str):
    """Build a litellm-style response object with a single message."""
    msg = MagicMock()
    msg.content = payload_json
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def test_evaluator_injects_score_distribution_context():
    """After several evaluations, the next prompt must include the calibration block."""
    ev = LLMEvaluator(model="dummy")
    # Pre-populate score history (simulating prior evaluations)
    ev._record_score("node_aaaaaaaa", 0.20, "draft")
    ev._record_score("node_bbbbbbbb", 0.55, "improve")
    ev._record_score("node_cccccccc", 0.85, "validation")

    captured: dict = {}

    async def _fake_acompletion(**kwargs):
        captured["messages"] = kwargs.get("messages", [])
        return _fake_completion_response(
            '{"has_real_data": true, "metrics": {"x": 1.0}, "reason": "ok", '
            '"scientific_score": 0.7, "comparison_found": false}'
        )

    with patch("ari.evaluator.llm_evaluator.litellm.acompletion", side_effect=_fake_acompletion):
        result = ev.evaluate_sync(
            goal="test goal",
            artifacts=[{"stdout": "x=1.0"}],
            summary="ran experiment",
            node_id="node_dddddddd",
            node_label="ablation",
        )

    # Result must be returned successfully
    assert result["has_real_data"] is True
    assert result["scientific_score"] == 0.7

    # User prompt must contain the calibration block
    user_msg = next(m for m in captured["messages"] if m["role"] == "user")
    user_content = user_msg["content"]
    assert "Score distribution context" in user_content
    assert "0.20" in user_content
    assert "0.85" in user_content
    assert "Use the full 0.0–1.0 range" in user_content


def test_evaluator_score_history_capped_at_15_in_prompt():
    """The calibration block must show at most 15 entries even with more history."""
    ev = LLMEvaluator(model="dummy")
    for i in range(25):
        ev._record_score(f"node_{i:08d}", 0.01 * i, "improve")

    block = ev._build_score_context()
    # Count score lines (each starts with two spaces and a dash)
    lines = [ln for ln in block.split("\n") if ln.strip().startswith("- node_")]
    assert len(lines) <= 15


def test_evaluator_no_context_when_history_empty():
    """First evaluation in a run has no calibration block (nothing to calibrate against)."""
    ev = LLMEvaluator(model="dummy")
    assert ev._build_score_context() == ""


def test_evaluator_records_score_after_evaluation():
    """A successful evaluation must append to the score history."""
    ev = LLMEvaluator(model="dummy")

    async def _fake_acompletion(**kwargs):
        return _fake_completion_response(
            '{"has_real_data": true, "metrics": {}, "reason": "ok", '
            '"scientific_score": 0.42, "comparison_found": false}'
        )

    with patch("ari.evaluator.llm_evaluator.litellm.acompletion", side_effect=_fake_acompletion):
        ev.evaluate_sync(
            goal="g",
            artifacts=[],
            summary="s",
            node_id="node_xxxxxxxx",
            node_label="improve",
        )

    assert len(ev._score_history) == 1
    assert ev._score_history[0]["score"] == pytest.approx(0.42)
    assert ev._score_history[0]["label"] == "improve"


# ──────────────────────────────────────────────────────────────────────────────
# Fix 2: expand() prompt has no hardcoded label list
# ──────────────────────────────────────────────────────────────────────────────


def test_expand_prompt_has_no_hardcoded_label_template(bfts, mock_llm):
    """The expansion prompt must NOT enumerate a fixed label vocabulary."""
    mock_llm.complete.return_value = LLMResponse(
        content='[{"label":"replication","direction":"re-run on a 2x larger dataset"}]'
    )
    parent = Node(
        id="node_parent00",
        parent_id=None,
        depth=1,
        has_real_data=True,
        metrics={"_scientific_score": 0.6, "throughput": 100.0},
        label=NodeLabel.IMPROVE,
    )
    parent.eval_summary = "improved baseline by 20%"

    bfts.expand(
        parent,
        experiment_goal="some goal",
        siblings=[],
        ancestors=[],
        all_run_nodes=[parent],
    )

    prompt_arg = mock_llm.complete.call_args[0][0][0].content

    # Must NOT contain the old hardcoded label menu
    forbidden_phrases = [
        "draft      - new implementation from scratch",
        "improve    - improve parent results",
        "debug      - fix parent failure/error",
        "ablation   - remove ONE component",
        "validation - re-run parent with different seeds",
    ]
    for phrase in forbidden_phrases:
        assert phrase not in prompt_arg, f"prompt still contains hardcoded hint: {phrase!r}"

    # Must contain the new context-driven instruction
    assert "Tree diversity so far" in prompt_arg
    assert "Sibling scores at same depth" in prompt_arg
    assert "Ancestor scores" in prompt_arg
    assert "Parent scientific score" in prompt_arg
    # Label vocabulary is now constrained to the canonical 5 (no inventions).
    assert "draft, improve, debug, ablation, validation" in prompt_arg
    assert "no inventions" in prompt_arg


def test_expand_accepts_invented_label(bfts, mock_llm):
    """An LLM-invented label like 'replication' is preserved on the child node."""
    mock_llm.complete.return_value = LLMResponse(
        content='[{"label":"replication","direction":"reproduce on dataset B"}]'
    )
    parent = Node(id="node_p00000aa", parent_id=None, depth=0, has_real_data=True)
    children = bfts.expand(parent, all_run_nodes=[parent])
    assert len(children) == 1
    # Internal enum must coerce to OTHER
    assert children[0].label == NodeLabel.OTHER
    # Original LLM string must be preserved
    assert children[0].raw_label == "replication"


def test_expand_passes_sibling_and_ancestor_scores(bfts, mock_llm):
    """Sibling and ancestor scores must appear inside the prompt."""
    mock_llm.complete.return_value = LLMResponse(
        content='[{"label":"improve","direction":"tune knobs"}]'
    )
    root = Node(
        id="node_root0000",
        parent_id=None,
        depth=0,
        has_real_data=True,
        metrics={"_scientific_score": 0.30},
        label=NodeLabel.DRAFT,
    )
    sibling_a = Node(
        id="node_sib0000a",
        parent_id="node_root0000",
        depth=1,
        has_real_data=True,
        metrics={"_scientific_score": 0.71},
        label=NodeLabel.IMPROVE,
    )
    parent = Node(
        id="node_par0000c",
        parent_id="node_root0000",
        depth=1,
        has_real_data=True,
        metrics={"_scientific_score": 0.55},
        label=NodeLabel.ABLATION,
    )
    bfts.expand(
        parent,
        siblings=[sibling_a],
        ancestors=[root],
        all_run_nodes=[root, sibling_a, parent],
    )
    prompt = mock_llm.complete.call_args[0][0][0].content
    # Sibling score appears
    assert "0.71" in prompt
    # Ancestor score appears
    assert "0.30" in prompt
    # Diversity metrics include all three labels we created
    assert "improve" in prompt
    assert "ablation" in prompt
    assert "draft" in prompt


# ──────────────────────────────────────────────────────────────────────────────
# Fix 3: diversity bonus
# ──────────────────────────────────────────────────────────────────────────────


def test_diversity_bonus_zero_with_no_history(bfts):
    n = Node(id="n", parent_id=None, depth=0, label=NodeLabel.IMPROVE)
    assert bfts.diversity_bonus(n) == 0.0


def test_diversity_bonus_rewards_underrepresented(bfts):
    """A label that has been run far less than the dominant one gets +0.05."""
    # Recent history: lots of "improve", just one "ablation"
    for _ in range(8):
        bfts.record_run(Node(id="x", parent_id=None, depth=0, label=NodeLabel.IMPROVE))
    bfts.record_run(Node(id="y", parent_id=None, depth=0, label=NodeLabel.ABLATION))

    candidate_under = Node(id="c1", parent_id=None, depth=0, label=NodeLabel.VALIDATION)
    candidate_over = Node(id="c2", parent_id=None, depth=0, label=NodeLabel.IMPROVE)

    # Validation is unseen → underrepresented → +0.05
    assert bfts.diversity_bonus(candidate_under) == pytest.approx(0.05)
    # Improve is the dominant label → no bonus
    assert bfts.diversity_bonus(candidate_over) == 0.0


def test_diversity_bonus_balanced_history(bfts):
    """When labels are roughly balanced, no bonus is awarded."""
    bfts.record_run(Node(id="a", parent_id=None, depth=0, label=NodeLabel.IMPROVE))
    bfts.record_run(Node(id="b", parent_id=None, depth=0, label=NodeLabel.ABLATION))
    bfts.record_run(Node(id="c", parent_id=None, depth=0, label=NodeLabel.VALIDATION))

    cand = Node(id="x", parent_id=None, depth=0, label=NodeLabel.IMPROVE)
    assert bfts.diversity_bonus(cand) == 0.0


def test_diversity_bonus_appears_in_select_prompt(bfts, mock_llm, mock_memory):
    """select_next_node should annotate the candidate with its bonus."""
    # Recent history dominated by improve
    for _ in range(6):
        bfts.record_run(Node(id="h", parent_id=None, depth=0, label=NodeLabel.IMPROVE))

    cand_a = Node(
        id="cand_aaaaaa", parent_id=None, depth=1,
        label=NodeLabel.IMPROVE, has_real_data=True,
        metrics={"_scientific_score": 0.5},
    )
    cand_b = Node(
        id="cand_bbbbbb", parent_id=None, depth=1,
        label=NodeLabel.VALIDATION, has_real_data=True,
        metrics={"_scientific_score": 0.5},
    )
    mock_llm.complete.return_value = LLMResponse(content="1")
    bfts.select_next_node([cand_a, cand_b], "goal", mock_memory)

    prompt = mock_llm.complete.call_args[0][0][0].content
    # cand_b's underrepresented validation label should show a diversity_bonus marker
    assert "diversity_bonus=+0.05" in prompt


def test_select_fallback_uses_diversity_bonus(bfts, mock_llm, mock_memory):
    """When LLM returns garbage and scientific scores tie, the bonus should break the tie."""
    for _ in range(6):
        bfts.record_run(Node(id="h", parent_id=None, depth=0, label=NodeLabel.IMPROVE))

    cand_a = Node(
        id="cand_aaaaaa", parent_id=None, depth=1,
        label=NodeLabel.IMPROVE, has_real_data=True,
        metrics={"_scientific_score": 0.5},
    )
    cand_b = Node(
        id="cand_bbbbbb", parent_id=None, depth=1,
        label=NodeLabel.VALIDATION, has_real_data=True,
        metrics={"_scientific_score": 0.5},
    )
    mock_llm.complete.return_value = LLMResponse(content="not a number")
    chosen = bfts.select_next_node([cand_a, cand_b], "goal", mock_memory)
    # cand_b wins because of the diversity bonus on validation
    assert chosen.id == "cand_bbbbbb"
