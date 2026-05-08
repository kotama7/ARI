"""Tests for lineage decision — root_idea_selector.

Covers:
- _parse_choice: valid index, out-of-range, malformed JSON
- apply_root_choice: swap behaviour, idempotency, _root_choice provenance
- select_root_idea: LLM-mocked happy path + fallback paths
- Single-idea pool short-circuits
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ari.orchestrator.root_idea_selector import (
    RootChoice,
    _parse_choice,
    apply_root_choice,
    select_root_idea,
)


# ---------------------------------------------------------------------------
# _parse_choice
# ---------------------------------------------------------------------------


def test_parse_valid_choice():
    raw = '{"chosen_index": 1, "rationale": "alt 1 better fits SC criteria"}'
    c = _parse_choice(raw, n_ideas=3)
    assert c.chosen_index == 1
    assert "SC" in c.rationale


def test_parse_zero_choice():
    raw = '{"chosen_index": 0, "rationale": "VirSci default holds"}'
    c = _parse_choice(raw, n_ideas=3)
    assert c.chosen_index == 0


def test_parse_out_of_range_falls_back_to_zero():
    raw = '{"chosen_index": 7, "rationale": "x"}'
    c = _parse_choice(raw, n_ideas=3)
    assert c.chosen_index == 0
    assert "out of range" in c.rationale


def test_parse_negative_index_falls_back():
    raw = '{"chosen_index": -1, "rationale": "x"}'
    c = _parse_choice(raw, n_ideas=3)
    assert c.chosen_index == 0


def test_parse_no_json_falls_back():
    c = _parse_choice("freeform text only", n_ideas=3)
    assert c.chosen_index == 0
    assert "no JSON" in c.rationale


def test_parse_malformed_json_falls_back():
    c = _parse_choice('{"chosen_index": 1', n_ideas=3)
    assert c.chosen_index == 0


def test_parse_empty_input():
    c = _parse_choice("", n_ideas=3)
    assert c.chosen_index == 0


def test_parse_strips_thinking_blocks():
    raw = ('<think>Let me consider</think>\n'
           '{"chosen_index": 2, "rationale": "scaling fits"}')
    c = _parse_choice(raw, n_ideas=3)
    assert c.chosen_index == 2


# ---------------------------------------------------------------------------
# apply_root_choice
# ---------------------------------------------------------------------------


def test_apply_swaps_ideas_and_records_provenance(tmp_path: Path):
    idea_path = tmp_path / "idea.json"
    idea_path.write_text(json.dumps({
        "ideas": [
            {"title": "A"},
            {"title": "B"},
            {"title": "C"},
        ]
    }))
    changed = apply_root_choice(idea_path, chosen_index=2, rationale="C wins")
    assert changed is True
    data = json.loads(idea_path.read_text())
    assert data["ideas"][0]["title"] == "C"
    assert data["ideas"][2]["title"] == "A"  # original ideas[0] now at 2
    # B (originally at 1) untouched.
    assert data["ideas"][1]["title"] == "B"
    assert data["_root_choice"]["chosen_index"] == 2
    assert "C wins" in data["_root_choice"]["rationale"]


def test_apply_zero_index_is_noop(tmp_path: Path):
    idea_path = tmp_path / "idea.json"
    idea_path.write_text(json.dumps({"ideas": [{"title": "A"}, {"title": "B"}]}))
    changed = apply_root_choice(idea_path, chosen_index=0)
    assert changed is False
    data = json.loads(idea_path.read_text())
    # No swap, no provenance written.
    assert "_root_choice" not in data
    assert data["ideas"][0]["title"] == "A"


def test_apply_out_of_range_is_noop(tmp_path: Path):
    idea_path = tmp_path / "idea.json"
    idea_path.write_text(json.dumps({"ideas": [{"title": "A"}, {"title": "B"}]}))
    assert apply_root_choice(idea_path, chosen_index=99) is False


def test_apply_missing_file_is_noop(tmp_path: Path):
    idea_path = tmp_path / "missing.json"
    assert apply_root_choice(idea_path, chosen_index=1) is False


def test_apply_malformed_file_is_noop(tmp_path: Path):
    idea_path = tmp_path / "bad.json"
    idea_path.write_text("not json {{")
    assert apply_root_choice(idea_path, chosen_index=1) is False


# ---------------------------------------------------------------------------
# select_root_idea — LLM mocked
# ---------------------------------------------------------------------------


def _run(coro):
    return asyncio.run(coro)


def _mock_response(content: str):
    msg = MagicMock(); msg.content = content
    choice = MagicMock(); choice.message = msg
    resp = MagicMock(); resp.choices = [choice]
    return resp


def test_select_returns_llm_choice():
    pool = {"ideas": [
        {"title": "T0", "overall_score": 0.7},
        {"title": "T1", "overall_score": 0.65},
        {"title": "T2", "overall_score": 0.6},
    ]}
    raw = '{"chosen_index": 2, "rationale": "T2 fits SC scaling demand"}'
    with patch(
        "ari.orchestrator.root_idea_selector.litellm.acompletion",
        new=AsyncMock(return_value=_mock_response(raw)),
    ):
        choice = _run(select_root_idea(pool, venue_constraints="SC scaling"))
    assert choice.chosen_index == 2
    assert "scaling" in choice.rationale.lower()


def test_select_falls_back_on_llm_error():
    pool = {"ideas": [{"title": "T0"}, {"title": "T1"}]}
    with patch(
        "ari.orchestrator.root_idea_selector.litellm.acompletion",
        new=AsyncMock(side_effect=RuntimeError("network")),
    ):
        choice = _run(select_root_idea(pool))
    assert choice.chosen_index == 0
    assert "LLM error" in choice.rationale


def test_select_falls_back_on_garbage_output():
    pool = {"ideas": [{"title": "T0"}, {"title": "T1"}]}
    with patch(
        "ari.orchestrator.root_idea_selector.litellm.acompletion",
        new=AsyncMock(return_value=_mock_response("absolutely no JSON here")),
    ):
        choice = _run(select_root_idea(pool))
    assert choice.chosen_index == 0


def test_select_short_circuits_single_idea_pool():
    pool = {"ideas": [{"title": "Only", "overall_score": 0.9}]}
    # No LLM call should happen for a 1-idea pool — patch to assert.
    mock = AsyncMock()
    with patch(
        "ari.orchestrator.root_idea_selector.litellm.acompletion", new=mock,
    ):
        choice = _run(select_root_idea(pool))
    assert choice.chosen_index == 0
    mock.assert_not_called()


def test_select_short_circuits_empty_pool():
    with patch(
        "ari.orchestrator.root_idea_selector.litellm.acompletion",
        new=AsyncMock(),
    ) as mock:
        choice = _run(select_root_idea({"ideas": []}))
    assert choice.chosen_index == 0
    mock.assert_not_called()


def test_select_passes_venue_and_ancestor_to_prompt():
    pool = {"ideas": [{"title": "T0"}, {"title": "T1"}]}
    captured: dict = {}

    async def _capturing_acompletion(**kwargs):
        captured.update(kwargs)
        return _mock_response('{"chosen_index": 0, "rationale": "default"}')

    with patch(
        "ari.orchestrator.root_idea_selector.litellm.acompletion",
        new=_capturing_acompletion,
    ):
        _run(select_root_idea(
            pool,
            venue_constraints="SC requires AD/AE",
            ancestor_thread="prior run tried envelope",
        ))
    user_msg = captured["messages"][1]["content"]
    assert "SC requires AD/AE" in user_msg
    assert "envelope" in user_msg


# ---------------------------------------------------------------------------
# RootChoice contract
# ---------------------------------------------------------------------------


def test_root_choice_dataclass():
    c = RootChoice(chosen_index=1, rationale="r", raw={})
    assert c.chosen_index == 1
    assert c.rationale == "r"
