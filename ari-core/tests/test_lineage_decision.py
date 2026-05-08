"""Tests for lineage decision5b — lineage_decision module.

Covers:
- _parse_decision: valid actions, invalid action / index, missing fields
- detect_stagnation: window thresholds, edge cases
- build_lineage_state: composes from BFTS-shaped nodes
- decide_lineage_action: LLM mocked, returns LineageDecision; failures
  degrade to fallback "continue"
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ari.orchestrator.lineage_decision import (
    LineageDecision,
    LineageState,
    VALID_ACTIONS,
    _parse_decision,
    build_lineage_state,
    decide_lineage_action,
    detect_stagnation,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _state(**overrides) -> LineageState:
    base = dict(
        active_idea_title="T0",
        active_idea_index=0,
        nodes_explored=5,
        best_axis_scores={"measurement_validity": 0.7},
        recent_composite_scores=[0.4, 0.5, 0.55, 0.55, 0.55],
        budget_remaining=5,
        alternatives=[
            {"index": 1, "title": "Alt-1", "summary": "alt", "overall_score": 0.7},
            {"index": 2, "title": "Alt-2", "summary": "alt2", "overall_score": 0.65},
        ],
    )
    base.update(overrides)
    return LineageState(**base)


# ---------------------------------------------------------------------------
# _parse_decision
# ---------------------------------------------------------------------------


def test_parse_continue():
    raw = '{"action": "continue", "rationale": "still productive"}'
    d = _parse_decision(raw, _state())
    assert d.action == "continue"
    assert d.target_idea_index is None
    assert "still productive" in d.rationale


def test_parse_switch_to_idea_with_valid_index():
    raw = ('{"action":"switch_to_idea","target_idea_index":1,'
           '"disable_generate_ideas":true,"rationale":"stagnation"}')
    d = _parse_decision(raw, _state())
    assert d.action == "switch_to_idea"
    assert d.target_idea_index == 1
    assert d.disable_generate_ideas is True


def test_parse_switch_with_invalid_index_falls_back():
    raw = '{"action":"switch_to_idea","target_idea_index":99,"rationale":"x"}'
    d = _parse_decision(raw, _state())
    assert d.action == "continue"
    assert "fallback" in d.rationale.lower()


def test_parse_switch_with_missing_index_falls_back():
    raw = '{"action":"switch_to_idea","rationale":"x"}'
    d = _parse_decision(raw, _state())
    assert d.action == "continue"
    assert "target_idea_index" in d.rationale


def test_parse_unknown_action_falls_back():
    raw = '{"action":"frobnicate","rationale":"x"}'
    d = _parse_decision(raw, _state())
    assert d.action == "continue"
    assert "unknown action" in d.rationale.lower()


def test_parse_terminate_does_not_require_index():
    raw = '{"action":"terminate","rationale":"all explored"}'
    d = _parse_decision(raw, _state())
    assert d.action == "terminate"
    assert d.target_idea_index is None


def test_parse_fanout_validates_index_against_pool():
    raw = '{"action":"fanout","target_idea_index":2,"rationale":"explore"}'
    d = _parse_decision(raw, _state())
    assert d.action == "fanout"
    assert d.target_idea_index == 2


def test_parse_empty_input_returns_continue():
    d = _parse_decision("", _state())
    assert d.action == "continue"


def test_parse_no_json_returns_continue():
    d = _parse_decision("just freeform text without JSON", _state())
    assert d.action == "continue"


def test_parse_malformed_json_returns_continue():
    d = _parse_decision('{"action":"switch_to_idea",', _state())
    assert d.action == "continue"


def test_parse_strips_thinking_blocks():
    raw = ('<think>I should check progress</think>\n'
           '{"action":"continue","rationale":"good progress"}')
    d = _parse_decision(raw, _state())
    assert d.action == "continue"


# ---------------------------------------------------------------------------
# detect_stagnation
# ---------------------------------------------------------------------------


def test_stagnation_true_when_flat():
    assert detect_stagnation([0.5, 0.5, 0.5, 0.5, 0.5]) is True


def test_stagnation_false_when_recent_improvement():
    # Last 5 values span 0.3 → 0.7 — not stagnant.
    assert detect_stagnation([0.3, 0.4, 0.5, 0.6, 0.7]) is False


def test_stagnation_false_when_window_too_short():
    assert detect_stagnation([0.5, 0.5, 0.5]) is False


def test_stagnation_threshold_respected():
    # Range = 0.025 — below threshold=0.03 → stagnant.
    assert detect_stagnation([0.50, 0.51, 0.52, 0.51, 0.525], threshold=0.03) is True
    # Same data, tighter threshold=0.01 → not stagnant.
    assert detect_stagnation([0.50, 0.51, 0.52, 0.51, 0.525], threshold=0.01) is False


def test_stagnation_empty_input():
    assert detect_stagnation([]) is False


# ---------------------------------------------------------------------------
# build_lineage_state
# ---------------------------------------------------------------------------


def test_build_state_composes_from_bfts_nodes():
    nodes = [
        SimpleNamespace(
            metrics={
                "_scientific_score": 0.6,
                "_axis_scores": {"measurement_validity": 0.7, "novelty": 0.5},
            }
        ),
        SimpleNamespace(
            metrics={
                "_scientific_score": 0.65,
                "_axis_scores": {"measurement_validity": 0.8, "novelty": 0.4},
            }
        ),
    ]
    idea_data = {
        "ideas": [
            {"title": "Active", "experiment_plan": ""},
            {"title": "Alt-1", "description": "alt1 desc", "overall_score": 0.7},
        ]
    }
    state = build_lineage_state(
        all_nodes=nodes, idea_data=idea_data, budget_remaining=10,
    )
    assert state.active_idea_title == "Active"
    assert state.nodes_explored == 2
    assert state.recent_composite_scores == [0.6, 0.65]
    # Best per-axis = max across nodes.
    assert state.best_axis_scores["measurement_validity"] == pytest.approx(0.8)
    assert state.best_axis_scores["novelty"] == pytest.approx(0.5)
    assert len(state.alternatives) == 1
    assert state.alternatives[0]["index"] == 1
    assert state.alternatives[0]["title"] == "Alt-1"


def test_build_state_handles_empty_pool():
    state = build_lineage_state(all_nodes=[], idea_data={}, budget_remaining=0)
    assert state.active_idea_title == ""
    assert state.alternatives == []
    assert state.recent_composite_scores == []


def test_state_to_prompt_includes_alternatives():
    state = _state()
    prompt = state.to_prompt()
    assert "Alt-1" in prompt
    assert "ideas[1]" in prompt
    assert "Active idea: ideas[0]" in prompt


# ---------------------------------------------------------------------------
# decide_lineage_action — LLM mocked
# ---------------------------------------------------------------------------


def _run(coro):
    return asyncio.run(coro)


def _mock_litellm_response(content: str):
    """Build the litellm response shape: resp.choices[0].message.content"""
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def test_decide_returns_continue_on_llm_continue():
    raw = '{"action":"continue","rationale":"ok"}'
    with patch(
        "ari.orchestrator.lineage_decision.litellm.acompletion",
        new=AsyncMock(return_value=_mock_litellm_response(raw)),
    ):
        decision = _run(decide_lineage_action(_state()))
    assert decision.action == "continue"


def test_decide_returns_switch_with_pinned_disable():
    raw = ('{"action":"switch_to_idea","target_idea_index":1,'
           '"disable_generate_ideas":true,"rationale":"stagnation"}')
    with patch(
        "ari.orchestrator.lineage_decision.litellm.acompletion",
        new=AsyncMock(return_value=_mock_litellm_response(raw)),
    ):
        decision = _run(decide_lineage_action(_state()))
    assert decision.action == "switch_to_idea"
    assert decision.target_idea_index == 1
    assert decision.disable_generate_ideas is True


def test_decide_falls_back_to_continue_on_llm_error():
    with patch(
        "ari.orchestrator.lineage_decision.litellm.acompletion",
        new=AsyncMock(side_effect=RuntimeError("network down")),
    ):
        decision = _run(decide_lineage_action(_state()))
    assert decision.action == "continue"
    assert "LLM error" in decision.rationale


def test_decide_falls_back_on_invalid_target_index():
    raw = '{"action":"switch_to_idea","target_idea_index":99,"rationale":"x"}'
    with patch(
        "ari.orchestrator.lineage_decision.litellm.acompletion",
        new=AsyncMock(return_value=_mock_litellm_response(raw)),
    ):
        decision = _run(decide_lineage_action(_state()))
    assert decision.action == "continue"


def test_decide_terminate_path():
    raw = '{"action":"terminate","rationale":"exhausted"}'
    with patch(
        "ari.orchestrator.lineage_decision.litellm.acompletion",
        new=AsyncMock(return_value=_mock_litellm_response(raw)),
    ):
        decision = _run(decide_lineage_action(_state()))
    assert decision.action == "terminate"


def test_fallback_continue_factory():
    d = LineageDecision.fallback_continue("test reason")
    assert d.action == "continue"
    assert "test reason" in d.rationale


def test_valid_actions_contract():
    # Documents the contract: 4 specific actions only.
    assert VALID_ACTIONS == {"continue", "switch_to_idea", "fanout", "terminate"}


# ---------------------------------------------------------------------------
# lineage decisions: adversarial / pathological LLM response tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("payload", [
    "",                                       # empty body
    "<think>only thinking</think>",            # nothing after </think>
    "<<<>>>",                                  # noise
    '"action":"continue"',                     # no JSON braces
    '{}',                                      # empty object
    '{"action":null}',                         # null action
    '{"action":42}',                           # non-string action
    '{"action":"continue","rationale":[1,2]}', # rationale not a string (still valid)
    '[1,2,3]',                                 # JSON array
    '"just a string"',                         # JSON scalar
    '{"action":"DROP TABLE users"}',           # injection-flavoured noise
    "{" * 5000,                                # incomplete JSON, large
    '{"action":"continue","rationale":"' + "x" * 5000 + '"}',  # very long rationale
])
def test_decide_handles_adversarial_llm_output_with_continue_fallback(payload):
    """Every malformed / hostile LLM response must downgrade to ``continue``
    so the BFTS loop keeps making progress."""
    with patch(
        "ari.orchestrator.lineage_decision.litellm.acompletion",
        new=AsyncMock(return_value=_mock_litellm_response(payload)),
    ):
        decision = _run(decide_lineage_action(_state()))
    assert decision.action == "continue"


def test_decide_truncates_oversized_rationale():
    """Very long rationales must be capped at the parser boundary so the
    persistence log doesn't accumulate runaway strings."""
    raw = '{"action":"continue","rationale":"' + ("x" * 1000) + '"}'
    with patch(
        "ari.orchestrator.lineage_decision.litellm.acompletion",
        new=AsyncMock(return_value=_mock_litellm_response(raw)),
    ):
        decision = _run(decide_lineage_action(_state()))
    assert len(decision.rationale) <= 500


def test_decide_rejects_unicode_action_variants():
    """Non-ASCII action strings (homoglyphs etc.) must not bypass
    the action whitelist."""
    raw = '{"action":"contіnue","rationale":"x"}'   # cyrillic 'i' homoglyph
    with patch(
        "ari.orchestrator.lineage_decision.litellm.acompletion",
        new=AsyncMock(return_value=_mock_litellm_response(raw)),
    ):
        decision = _run(decide_lineage_action(_state()))
    assert decision.action == "continue"
    assert "fallback" in decision.rationale.lower()


def test_decide_handles_recursion_depth_at_limit():
    """When state shows recursion_depth == max, the LLM is told to
    avoid switch/fanout. The fallback path still works regardless."""
    state_at_limit = _state(recursion_depth=3, max_recursion_depth=3)
    raw = '{"action":"continue","rationale":"already at limit"}'
    with patch(
        "ari.orchestrator.lineage_decision.litellm.acompletion",
        new=AsyncMock(return_value=_mock_litellm_response(raw)),
    ):
        decision = _run(decide_lineage_action(state_at_limit))
    assert decision.action == "continue"
    # The prompt block must include the recursion warning — check via
    # to_prompt output to assure I-level wiring is present.
    prompt = state_at_limit.to_prompt()
    assert "recursion" in prompt.lower()
    assert "limit" in prompt.lower() or "switch_to_idea" in prompt.lower()
