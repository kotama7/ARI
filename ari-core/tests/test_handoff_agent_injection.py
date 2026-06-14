"""Tests for the handoff-study agent-face injection (G4): build_handoff_agent_messages
and the parent-report / parent-log loaders (derived from the child work_dir).
"""
import json
import types

from ari.agent.loop import (
    build_handoff_agent_messages,
    _load_parent_node_report,
    _load_parent_log,
)
from ari.config import HandoffConfig

REP = {
    "node_id": "p123", "label": "perf", "status": "success",
    "delta_vs_parent": "used blocking", "files_changed": {"added": [{"path": "spmm.c"}]},
    "self_assessment": {"concerns": []}, "next_steps_hints": ["try tiling"],
    "metrics": {"valid_geomean_speedup": 2.0, "_scientific_score": 0.5},
    "build_command": "make", "run_command": "./bench",
}


def test_none_and_no_op_arms_inject_nothing():
    assert build_handoff_agent_messages(None, REP, "log") == []
    assert build_handoff_agent_messages(HandoffConfig(mode="disabled"), REP, "log") == []
    # code_only: agent block off + log none
    assert build_handoff_agent_messages(HandoffConfig(mode="code_only"), REP, "log") == []


def test_summary_arm_injects_operational_summary():
    m = build_handoff_agent_messages(HandoffConfig(mode="code_plus_summary"), REP, "")
    assert len(m) == 1
    assert "operational summary" in m[0]["content"]
    assert "delta_vs_parent" in m[0]["content"]


def test_full_log_arm_injects_full_log():
    m = build_handoff_agent_messages(HandoffConfig(mode="code_plus_full_log"), None, "FULLLOGDATA")
    assert len(m) == 1 and "execution log" in m[0]["content"] and "FULLLOGDATA" in m[0]["content"]


def test_truncated_log_keeps_tail():
    h = HandoffConfig(mode="code_plus_truncated_log")
    h.log_truncate_chars = 6
    m = build_handoff_agent_messages(h, None, "0123456789ABCDEF")
    assert "ABCDEF" in m[0]["content"] and "0123456" not in m[0]["content"]


def test_loaders_resolve_parent_from_child_workdir(tmp_path):
    run = tmp_path / "run1"
    (run / "parent").mkdir(parents=True)
    (run / "child").mkdir()
    (run / "parent" / "node_report.json").write_text(json.dumps(REP))
    (run / "parent" / "run.log").write_text("PARENTRUNLOG")
    node = types.SimpleNamespace(parent_id="parent", id="child")
    rep = _load_parent_node_report(node, str(run / "child"))
    assert rep and rep["node_id"] == "p123"
    log = _load_parent_log(node, str(run / "child"))
    assert "PARENTRUNLOG" in log and "run.log" in log


def test_loaders_graceful_without_parent():
    import types as _t
    assert _load_parent_node_report(_t.SimpleNamespace(parent_id=None, id="x"), "/nope") is None
    assert _load_parent_log(_t.SimpleNamespace(parent_id=None, id="x"), "/nope") == ""
