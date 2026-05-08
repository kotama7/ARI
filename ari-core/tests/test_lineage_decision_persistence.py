"""Tests for lineage decisions decision persistence + cost-tracker metadata wiring (B).

Covers:
- append_decision_log writes one JSON-per-line record with state + decision
- read_decision_log round-trips multiple appends
- Malformed lines are skipped silently by the reader
- append_root_selection_log shares the same file with disambiguating trigger
- decide_lineage_action passes metadata.phase="lineage_decision" so
  ari.cost_tracker can attribute the call
- select_root_idea passes metadata.phase="root_idea_selection" similarly
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ari.orchestrator.lineage_decision import (
    LineageDecision,
    LineageState,
    append_decision_log,
    decide_lineage_action,
    read_decision_log,
)
from ari.orchestrator.root_idea_selector import (
    RootChoice,
    append_root_selection_log,
    select_root_idea,
)


def _state(**overrides) -> LineageState:
    base = dict(
        active_idea_title="T0",
        active_idea_index=0,
        nodes_explored=5,
        best_axis_scores={"measurement_validity": 0.7},
        recent_composite_scores=[0.4, 0.5, 0.55, 0.55, 0.55],
        budget_remaining=5,
        alternatives=[
            {"index": 1, "title": "Alt-1", "summary": "", "overall_score": 0.7},
        ],
    )
    base.update(overrides)
    return LineageState(**base)


def _mock_llm_response(content: str):
    msg = MagicMock(); msg.content = content
    choice = MagicMock(); choice.message = msg
    resp = MagicMock(); resp.choices = [choice]
    return resp


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# append_decision_log + read_decision_log
# ---------------------------------------------------------------------------


def test_append_decision_log_writes_one_record(tmp_path: Path):
    state = _state()
    decision = LineageDecision(
        action="continue",
        target_idea_index=None,
        disable_generate_ideas=False,
        rationale="still productive",
    )
    ok = append_decision_log(
        tmp_path, state=state, decision=decision, trigger="stagnation_rule"
    )
    assert ok is True
    log_file = tmp_path / "lineage_decisions.jsonl"
    assert log_file.exists()
    records = read_decision_log(tmp_path)
    assert len(records) == 1
    rec = records[0]
    assert rec["trigger"] == "stagnation_rule"
    assert rec["decision"]["action"] == "continue"
    assert rec["state"]["active_idea_title"] == "T0"
    assert "ts" in rec and "ts_iso" in rec


def test_append_decision_log_appends_multiple(tmp_path: Path):
    for i in range(3):
        append_decision_log(
            tmp_path,
            state=_state(nodes_explored=i),
            decision=LineageDecision.fallback_continue(f"call {i}"),
            trigger="every_node",
        )
    records = read_decision_log(tmp_path)
    assert len(records) == 3
    assert [r["state"]["nodes_explored"] for r in records] == [0, 1, 2]


def test_append_decision_log_records_executed_flag(tmp_path: Path):
    state = _state()
    switch = LineageDecision(
        action="switch_to_idea",
        target_idea_index=1,
        disable_generate_ideas=True,
        rationale="stagnation",
    )
    append_decision_log(
        tmp_path, state=state, decision=switch, trigger="stagnation_rule",
        executed=True, extra={"stop_requested": False},
    )
    rec = read_decision_log(tmp_path)[0]
    assert rec["executed"] is True
    assert rec["extra"]["stop_requested"] is False
    assert rec["decision"]["target_idea_index"] == 1
    assert rec["decision"]["disable_generate_ideas"] is True


def test_read_decision_log_skips_malformed_lines(tmp_path: Path):
    log_file = tmp_path / "lineage_decisions.jsonl"
    log_file.write_text(
        '{"ts": 1, "trigger": "x", "decision": {"action":"continue"}, "state": {}}\n'
        'NOT JSON HERE\n'
        '\n'  # blank line
        '{"ts": 2, "trigger": "y", "decision": {"action":"terminate"}, "state": {}}\n'
    )
    records = read_decision_log(tmp_path)
    assert len(records) == 2
    assert records[0]["trigger"] == "x"
    assert records[1]["trigger"] == "y"


def test_read_decision_log_missing_file_returns_empty(tmp_path: Path):
    assert read_decision_log(tmp_path) == []


# ---------------------------------------------------------------------------
# append_root_selection_log shares the file
# ---------------------------------------------------------------------------


def test_root_selection_log_shares_jsonl_with_lineage(tmp_path: Path):
    state = _state()
    append_decision_log(
        tmp_path, state=state,
        decision=LineageDecision.fallback_continue("ok"),
        trigger="stagnation_rule",
    )
    append_root_selection_log(
        tmp_path,
        pool_size=3,
        choice=RootChoice(chosen_index=2, rationale="alt 2 fits SC", raw={}),
        swapped=True,
    )
    records = read_decision_log(tmp_path)
    triggers = [r["trigger"] for r in records]
    # Same file holds both record types — the trigger field disambiguates.
    assert "stagnation_rule" in triggers
    assert "root_idea_selection" in triggers
    root_rec = next(r for r in records if r["trigger"] == "root_idea_selection")
    assert root_rec["decision"]["action"] == "root_swap"
    assert root_rec["decision"]["chosen_index"] == 2
    assert root_rec["extra"]["pool_size"] == 3


def test_root_selection_log_records_no_swap(tmp_path: Path):
    append_root_selection_log(
        tmp_path,
        pool_size=3,
        choice=RootChoice(chosen_index=0, rationale="VirSci default", raw={}),
        swapped=False,
    )
    rec = read_decision_log(tmp_path)[0]
    assert rec["decision"]["action"] == "root_keep"
    assert rec["executed"] is False


# ---------------------------------------------------------------------------
# Cost-tracker metadata wiring (verifies phase identifier on litellm call)
# ---------------------------------------------------------------------------


def test_decide_lineage_action_passes_phase_metadata():
    """Captured kwargs to litellm.acompletion must carry metadata.phase
    so the global cost_tracker callback can attribute the call.
    """
    captured: dict = {}

    async def _capturing(**kwargs):
        captured.update(kwargs)
        return _mock_llm_response('{"action":"continue","rationale":"ok"}')

    with patch(
        "ari.orchestrator.lineage_decision.litellm.acompletion",
        new=_capturing,
    ):
        _run(decide_lineage_action(_state()))
    assert "metadata" in captured
    md = captured["metadata"]
    assert md.get("phase") == "lineage_decision"
    assert md.get("skill") == "lineage_decision"


def test_select_root_idea_passes_phase_metadata():
    captured: dict = {}

    async def _capturing(**kwargs):
        captured.update(kwargs)
        return _mock_llm_response('{"chosen_index":0,"rationale":"default"}')

    pool = {"ideas": [{"title": "A"}, {"title": "B"}]}
    with patch(
        "ari.orchestrator.root_idea_selector.litellm.acompletion",
        new=_capturing,
    ):
        _run(select_root_idea(pool))
    md = captured["metadata"]
    assert md.get("phase") == "root_idea_selection"
    assert md.get("skill") == "root_idea_selector"


# ---------------------------------------------------------------------------
# State serialiser strips heavy fields
# ---------------------------------------------------------------------------


def test_state_for_log_drops_long_context(tmp_path: Path):
    state = _state(
        venue_constraints="x" * 500,
        ancestor_thread="y" * 5000,
    )
    append_decision_log(
        tmp_path, state=state,
        decision=LineageDecision.fallback_continue("x"),
        trigger="every_node",
    )
    rec = read_decision_log(tmp_path)[0]
    # Context blocks not duplicated into the log; presence flags only.
    assert rec["state"]["venue_constraints_present"] is True
    assert rec["state"]["ancestor_thread_present"] is True
    assert "venue_constraints" not in rec["state"]
    assert "ancestor_thread" not in rec["state"]
