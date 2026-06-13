"""Wiring tests for verified-context (handoff: 'secure the flow').

Proves the orchestrator generates verified_context.json ONLY when
ARI_MEMORY_CONSOLIDATE is set (default OFF => default behavior unchanged),
without touching the stage/tool resolution order.
"""
from __future__ import annotations

from unittest import mock

import ari.pipeline.verified_context as _vcmod
from ari.orchestrator.node import Node, NodeStatus
from ari.pipeline import run_pipeline


def _node():
    n = Node(id="n1", parent_id=None, depth=0)
    n.status = NodeStatus.SUCCESS
    n.has_real_data = True
    n.metrics = {"score": 1.0}
    return n


def _stages(tmp_path):
    return [{"stage": "s", "skill": "t-skill", "tool": "tool_x",
             "depends_on": [], "inputs": {}, "outputs": {"file": f"{tmp_path}/x.json"},
             "skip_if_exists": ""}]


def _run(tmp_path):
    def _fake_sub(tool, args, config_path, skill_name=""):
        return {"result": "ok"}
    with mock.patch("ari.pipeline._run_stage_subprocess", side_effect=_fake_sub):
        return run_pipeline(_stages(tmp_path), [_node()],
                            {"goal": "g", "topic": "t", "file": ""}, tmp_path, "")


def test_gate_explicit_off_does_not_build_verified_context(tmp_path, monkeypatch):
    monkeypatch.setenv("ARI_MEMORY_CONSOLIDATE", "0")  # explicit disable
    calls = []
    monkeypatch.setattr(_vcmod, "write_verified_context",
                        lambda ckpt, nodes, **kw: calls.append(str(ckpt)) or {"usable_for_claims": []})
    _run(tmp_path)
    assert calls == []  # explicitly OFF => not built


def test_default_unset_builds_verified_context(tmp_path, monkeypatch):
    monkeypatch.delenv("ARI_MEMORY_CONSOLIDATE", raising=False)  # default
    calls = []
    monkeypatch.setattr(_vcmod, "write_verified_context",
                        lambda ckpt, nodes, **kw: calls.append(str(ckpt)) or {"usable_for_claims": []})
    _run(tmp_path)
    assert len(calls) == 1  # default ON (v0.8.x) => built once


def test_gate_on_builds_verified_context(tmp_path, monkeypatch):
    monkeypatch.setenv("ARI_MEMORY_CONSOLIDATE", "1")
    calls = []
    monkeypatch.setattr(_vcmod, "write_verified_context",
                        lambda ckpt, nodes, **kw: calls.append(str(ckpt)) or {"usable_for_claims": []})
    _run(tmp_path)
    assert len(calls) == 1  # explicitly ON => built once


def test_gate_build_failure_does_not_break_pipeline(tmp_path, monkeypatch):
    monkeypatch.setenv("ARI_MEMORY_CONSOLIDATE", "true")

    def _boom(ckpt, nodes, **kw):
        raise RuntimeError("backend down")

    monkeypatch.setattr(_vcmod, "write_verified_context", _boom)
    # run_pipeline must complete despite the verified_context build raising
    result = _run(tmp_path)
    assert result.get("s") is not None  # the real stage still ran


# ── consolidation_enabled() default-ON semantics (v0.8.x flip) ──────────────

import pytest
from ari.config import consolidation_enabled


@pytest.mark.parametrize("val,expected", [
    (None, True),        # unset => default ON
    ("1", True), ("true", True), ("yes", True), ("on", True), ("TRUE", True),
    ("0", False), ("false", False), ("no", False), ("off", False), ("OFF", False),
    ("", True),          # empty (non-disable token) => ON
])
def test_consolidation_enabled(val, expected, monkeypatch):
    if val is None:
        monkeypatch.delenv("ARI_MEMORY_CONSOLIDATE", raising=False)
    else:
        monkeypatch.setenv("ARI_MEMORY_CONSOLIDATE", val)
    assert consolidation_enabled() is expected
