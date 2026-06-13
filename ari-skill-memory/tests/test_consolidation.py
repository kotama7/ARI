"""Phase 3 foundation — consolidation (node_report -> typed memory specs).

Pure logic tested with synthetic node_reports plus an opt-in check against a
real workspace node_report. Also verifies write_consolidated round-trips
through the in-memory backend (CoW node = nX).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ari_skill_memory import consolidation, retriever


def test_success_with_metrics_yields_experiment_result(tmp_path):
    report = {
        "node_id": "n7",
        "status": "success",
        "metrics": {"rows": 400000, "GFlops_per_s_T48": 6.04, "speedup_48T": 23.5},
        "self_assessment": {"headline": "banded SpMM hit 6.04 GFlops/s at 48 threads"},
        "files_changed": {"added": [{"path": "kernel.c", "sha256": "deadbeef"}]},
        "artifacts": [],
        "next_steps_hints": ["try wider K", "profile cache misses"],
    }
    specs = consolidation.consolidate_from_node_report(report, tmp_path, run_id="run1")
    kinds = [s["kind"] for s in specs]
    assert "experiment_result" in kinds and "reflection" in kinds
    er = next(s for s in specs if s["kind"] == "experiment_result")
    assert er["metric_ptr"]["name"] == "GFlops_per_s_T48"   # throughput hint wins over rows
    assert er["node_report_ref"] == {"run_id": "run1", "node_id": "n7"}
    assert er["artifact_refs"][0].path == "kernel.c"
    refl = next(s for s in specs if s["kind"] == "reflection")
    assert "try wider K" in refl["text"] and refl["_confidence"] == 0.4


def test_failure_status_yields_failure_case(tmp_path):
    report = {
        "node_id": "n12", "status": "failed", "metrics": {},
        "self_assessment": {"headline": "link error: cublasLt missing"},
        "files_changed": {}, "artifacts": [],
    }
    specs = consolidation.consolidate_from_node_report(report, tmp_path)
    assert [s["kind"] for s in specs] == ["failure_case"]
    assert "link error" in specs[0]["text"]


def test_success_without_metrics_emits_nothing_substantive(tmp_path):
    report = {"node_id": "n", "status": "success", "metrics": {}, "next_steps_hints": []}
    assert consolidation.consolidate_from_node_report(report, tmp_path) == []


def test_write_consolidated_roundtrips(backend, monkeypatch, tmp_path):
    monkeypatch.setenv("ARI_CURRENT_NODE_ID", "nX")
    report = {
        "node_id": "nX", "status": "success",
        "metrics": {"GB_per_s": 842.1},
        "self_assessment": {"headline": "tile=32 best throughput"},
        "files_changed": {}, "artifacts": [], "next_steps_hints": [],
    }
    specs = consolidation.consolidate_from_node_report(report, tmp_path, run_id="r")
    res = consolidation.write_consolidated(backend, "nX", specs)
    assert all(r["ok"] for r in res)
    got = retriever.ancestor_typed_memory(backend, ["nX"], kinds=["experiment_result"])
    assert any("tile=32" in g["text"] for g in got)
    md = got[0]["metadata"]
    assert md["metric_ptr"]["value"] == 842.1


# ── opt-in: real node_report ──────────────────────────────────────────────

_REAL_NODE = Path(
    "workspace/experiments/20260528180541_We_propose_an_implementation_of_CSR-form/node_b4affdab"
)


@pytest.mark.skipif(not (_REAL_NODE / "node_report.json").exists(),
                    reason="real node_report not present")
def test_consolidate_real_node_report():
    report = json.loads((_REAL_NODE / "node_report.json").read_text())
    specs = consolidation.consolidate_from_node_report(report, _REAL_NODE, run_id="real")
    assert specs, "expected specs from a real success node"
    er = next((s for s in specs if s["kind"] == "experiment_result"), None)
    assert er is not None
    assert er["metric_ptr"] is not None         # picked a numeric metric
    assert er["node_report_ref"]["node_id"] == "node_b4affdab"
