"""Unit tests for JsonlTraceStore (subtask 010).

Guards the node-report read/write seam subtask 011 consumes, plus the
append-only per-node trace, over the flat node-work-dir layout. Node reports
must be byte-identical to
``ari.orchestrator.node_report.write_node_report``'s write step.
"""

from __future__ import annotations

import json

from ari.paths import PathManager
from ari.protocols import TraceStore
from ari.trace_store import JsonlTraceStore


def _store(tmp_path, run_id="run1") -> JsonlTraceStore:
    return JsonlTraceStore(path_manager=PathManager(workspace_root=str(tmp_path)),
                           run_id=run_id)


def test_satisfies_protocol():
    assert isinstance(JsonlTraceStore(), TraceStore)


def test_node_report_write_is_byte_identical(tmp_path):
    store = _store(tmp_path)
    report = {"schema_version": 1, "node_id": "a", "metrics": {}, "u": "café"}
    p = store.write_node_report("a", report)

    assert p == tmp_path / "experiments" / "run1" / "a" / "node_report.json"
    # Byte-identical to builder.write_node_report's json.dumps(..., indent=2,
    # ensure_ascii=False) write step.
    assert p.read_text() == json.dumps(report, indent=2, ensure_ascii=False)
    assert store.read_node_report("a") == report


def test_read_node_report_missing_returns_none(tmp_path):
    store = _store(tmp_path)
    assert store.read_node_report("nope") is None


def test_read_node_report_corrupt_returns_none(tmp_path):
    store = _store(tmp_path)
    wd = tmp_path / "experiments" / "run1" / "bad"
    wd.mkdir(parents=True)
    (wd / "node_report.json").write_text("{not json")
    assert store.read_node_report("bad") is None


def test_read_sibling_reports_accepts_ids_and_objects(tmp_path):
    store = _store(tmp_path)
    store.write_node_report("a", {"node_id": "a"})
    store.write_node_report("b", {"node_id": "b"})

    by_id = store.read_sibling_reports(["a", "b", "missing"])
    assert set(by_id) == {"a", "b"}

    class _Node:
        def __init__(self, i):
            self.id = i

    by_obj = store.read_sibling_reports([_Node("a"), _Node("missing")])
    assert set(by_obj) == {"a"}


def test_trace_append_read_roundtrip(tmp_path):
    store = _store(tmp_path)
    store.append_trace("a", {"step": 1, "tool": "x"})
    store.append_trace("a", "→ plain string entry")

    assert store.read_trace("a") == [{"step": 1, "tool": "x"}, "→ plain string entry"]
    assert store.read_trace("never-written") == []


def test_env_pinned_resolution(tmp_path, monkeypatch):
    ckpt = tmp_path / "checkpoints" / "run1"
    ckpt.mkdir(parents=True)
    monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(ckpt))

    store = JsonlTraceStore()  # resolves via ARI_CHECKPOINT_DIR
    p = store.write_node_report("a", {"node_id": "a"})
    assert p == tmp_path / "experiments" / "run1" / "a" / "node_report.json"
