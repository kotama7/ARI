"""Tests for the v0.7.0 GUI endpoint that surfaces lineage decisions.

Covers:
- _api_lineage_decisions reads {checkpoint}/lineage_decisions.jsonl
- Records are returned in chronological order
- Missing file produces empty result without error
- Malformed lines are skipped
- Unknown checkpoint returns an error key
- HTTP route /api/lineage-decisions/<run_id> dispatches to the helper
- The helper wires correctly with append_decision_log/append_root_selection_log
  so what the writer persists is exactly what the reader returns.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ari.viz.api_state import _api_lineage_decisions
from ari.orchestrator.lineage_decision import (
    LineageDecision,
    LineageState,
    append_decision_log,
)
from ari.orchestrator.root_idea_selector import (
    RootChoice,
    append_root_selection_log,
)


def _state(**overrides) -> LineageState:
    base = dict(
        active_idea_title="ENVELOPE",
        active_idea_index=0,
        nodes_explored=5,
        best_axis_scores={"measurement_validity": 0.9},
        recent_composite_scores=[0.6, 0.62, 0.63],
        budget_remaining=10,
        alternatives=[
            {"index": 1, "title": "TALON", "summary": "", "overall_score": 0.7},
        ],
    )
    base.update(overrides)
    return LineageState(**base)


def _resolve(ckpt_id, ckpt_path):
    """Patcher: make _resolve_checkpoint_dir return the test path for ckpt_id."""
    def _impl(_x):
        return ckpt_path if str(_x) == ckpt_id else None
    return _impl


def _viz_server_concat(viz_dir: Path) -> str:
    """Phase 3B PR-3B-1: ``server.py`` was split into sibling modules
    (``websocket.py``, ``ui_helpers.py``, ``routes.py``); concatenate
    them so existing source-text checks still find the moved literals.
    """
    parts = []
    for name in ("ui_helpers.py", "websocket.py", "routes.py", "server.py"):
        p = viz_dir / name
        if p.exists():
            parts.append(p.read_text())
    return "\n".join(parts)


def test_lineage_decisions_endpoint_reads_jsonl(tmp_path: Path):
    ckpt = tmp_path / "ckpt_a"
    ckpt.mkdir()

    # Write three records via the public API.
    state = _state()
    append_decision_log(
        ckpt, state=state,
        decision=LineageDecision.fallback_continue("ok"),
        trigger="stagnation_rule",
    )
    switch = LineageDecision(
        action="switch_to_idea",
        target_idea_index=1,
        disable_generate_ideas=True,
        rationale="stagnation",
    )
    append_decision_log(
        ckpt, state=state, decision=switch, trigger="stagnation_rule",
        executed=True,
    )
    append_root_selection_log(
        ckpt,
        pool_size=3,
        choice=RootChoice(chosen_index=2, rationale="alt 2 fits SC", raw={}),
        swapped=True,
    )

    with patch(
        "ari.viz.api_state._resolve_checkpoint_dir",
        side_effect=_resolve("ckpt_a", ckpt),
    ):
        out = _api_lineage_decisions("ckpt_a")
    assert out["n"] == 3
    triggers = [r["trigger"] for r in out["records"]]
    assert triggers == ["stagnation_rule", "stagnation_rule", "root_idea_selection"]
    # Switch record carries action + target.
    sw = out["records"][1]
    assert sw["decision"]["action"] == "switch_to_idea"
    assert sw["decision"]["target_idea_index"] == 1
    # Root record uses the disambiguating action label.
    root = out["records"][2]
    assert root["decision"]["action"] == "root_swap"
    assert root["extra"]["pool_size"] == 3


def test_lineage_decisions_missing_file_returns_empty(tmp_path: Path):
    ckpt = tmp_path / "empty"
    ckpt.mkdir()
    with patch(
        "ari.viz.api_state._resolve_checkpoint_dir",
        side_effect=_resolve("empty", ckpt),
    ):
        out = _api_lineage_decisions("empty")
    assert out == {"records": [], "n": 0}


def test_lineage_decisions_unknown_checkpoint_errors(tmp_path: Path):
    with patch(
        "ari.viz.api_state._resolve_checkpoint_dir",
        return_value=None,
    ):
        out = _api_lineage_decisions("does_not_exist")
    assert out["n"] == 0
    assert "error" in out
    assert "unknown" in out["error"]


def test_lineage_decisions_skips_malformed_lines(tmp_path: Path):
    ckpt = tmp_path / "broken"
    ckpt.mkdir()
    log = ckpt / "lineage_decisions.jsonl"
    log.write_text(
        '{"ts": 1, "trigger": "stagnation_rule", "decision": {"action":"continue"}}\n'
        'not json at all\n'
        '\n'
        '{"ts": 2, "trigger": "stagnation_rule", "decision": {"action":"terminate"}}\n'
    )
    with patch(
        "ari.viz.api_state._resolve_checkpoint_dir",
        side_effect=_resolve("broken", ckpt),
    ):
        out = _api_lineage_decisions("broken")
    assert out["n"] == 2
    assert [r["decision"]["action"] for r in out["records"]] == [
        "continue", "terminate",
    ]


def test_lineage_decisions_chronological_order(tmp_path: Path):
    """Records must be returned in the order they were written so the
    GUI can render a faithful timeline."""
    ckpt = tmp_path / "chrono"
    ckpt.mkdir()
    state = _state()
    for i in range(5):
        append_decision_log(
            ckpt,
            state=_state(nodes_explored=i),
            decision=LineageDecision.fallback_continue(f"call {i}"),
            trigger="every_node",
        )
    with patch(
        "ari.viz.api_state._resolve_checkpoint_dir",
        side_effect=_resolve("chrono", ckpt),
    ):
        out = _api_lineage_decisions("chrono")
    assert out["n"] == 5
    nodes = [r["state"]["nodes_explored"] for r in out["records"]]
    assert nodes == [0, 1, 2, 3, 4]


def test_lineage_decisions_route_dispatches_in_http_layer():
    """The HTTP do_GET handler in ari.viz routes the path to the
    helper. Phase 3B PR-3B-1 split the dispatch table out into
    ``ari/viz/routes.py``; concat the viz package so this check finds
    the literal regardless of which sub-module owns it now."""
    import ari.viz.server as srv
    src = _viz_server_concat(Path(srv.__file__).resolve().parent)
    assert "/api/lineage-decisions/" in src
    assert "_api_lineage_decisions(" in src
