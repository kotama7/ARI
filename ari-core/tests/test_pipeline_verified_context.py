"""Verified-context artifact for paper generation (本命).

Covers ari.pipeline.verified_context: best-node selection, scoping to the
root->best lineage, graceful empty output, and the prompt-block renderer.
Uses a fake memory backend so no Letta is required.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

from ari.pipeline import verified_context as vc


def _node(nid, *, ancestors=(), score=None, has_real=True, metric=None):
    metrics = {}
    if score is not None:
        metrics["_scientific_score"] = score
    if metric is not None:
        metrics["GB_per_s"] = metric
    return SimpleNamespace(
        id=nid, ancestor_ids=list(ancestors), metrics=metrics, has_real_data=has_real,
    )


class _FakeBackend:
    """Returns a fixed verified-context-shaped result for a known lineage."""

    def __init__(self, by_lineage):
        self.by_lineage = by_lineage
        self.calls = []

    # context_builder.build_verified_context will be monkeypatched to call this
    def build(self, ancestor_ids):
        self.calls.append(list(ancestor_ids))
        return self.by_lineage


# ── best-node selection ───────────────────────────────────────────────────

def test_select_best_node_by_scientific_score():
    nodes = [_node("a", score=0.2), _node("b", score=0.9), _node("c", score=0.5)]
    assert vc.select_best_node(nodes).id == "b"


def test_select_best_prefers_real_data():
    nodes = [_node("a", score=0.9, has_real=False), _node("b", score=0.3, has_real=True)]
    assert vc.select_best_node(nodes).id == "b"   # real-data wins over higher score


def test_select_best_none_when_empty():
    assert vc.select_best_node([]) is None


# ── build_verified_context: scoping + graceful ────────────────────────────

def test_build_scopes_to_root_to_best_lineage(monkeypatch):
    best = _node("leaf", ancestors=["root", "p1"], score=0.8)
    nodes = [_node("root", score=0.1), _node("p1", score=0.4), best]
    captured = {}

    def fake_build(backend, ancestor_ids, purpose="paper"):
        captured["lineage"] = list(ancestor_ids)
        return {"claims": [], "limitations": [], "usable_for_claims": []}

    monkeypatch.setattr("ari_skill_memory.context_builder.build_verified_context", fake_build)
    out = vc.build_verified_context("/tmp/ck", nodes, backend=object())
    assert out["best_node_id"] == "leaf"
    assert captured["lineage"] == ["root", "p1", "leaf"]   # root -> best, inclusive


def test_build_graceful_on_backend_error(monkeypatch):
    nodes = [_node("leaf", ancestors=["root"], score=0.8)]

    def boom(*a, **k):
        raise RuntimeError("letta down")

    monkeypatch.setattr("ari_skill_memory.context_builder.build_verified_context", boom)
    out = vc.build_verified_context("/tmp/ck", nodes, backend=object())
    assert out["usable_for_claims"] == [] and out["best_node_id"] == "leaf"


def test_write_verified_context_writes_file(tmp_path, monkeypatch):
    nodes = [_node("leaf", ancestors=["root"], score=0.8)]
    monkeypatch.setattr(
        "ari_skill_memory.context_builder.build_verified_context",
        lambda b, a, purpose="paper": {
            "claims": [], "limitations": [],
            "usable_for_claims": [{"text": "x 842 GB/s", "repro_status": "rerun_passed",
                                    "artifact_refs": [{"path": "out/b.csv"}]}],
        },
    )
    vc.write_verified_context(tmp_path, nodes, backend=object())
    data = json.loads((tmp_path / "verified_context.json").read_text())
    assert data["best_node_id"] == "leaf"
    assert len(data["usable_for_claims"]) == 1


# ── render_grounded_block ─────────────────────────────────────────────────

def test_render_block_empty_when_no_usable():
    assert vc.render_grounded_block({"usable_for_claims": []}) == ""
    assert vc.render_grounded_block({}) == ""


def test_render_block_lists_grounded_claims():
    ctx = {"usable_for_claims": [
        {"text": "tile=32 -> 842 GB/s", "repro_status": "rerun_passed",
         "artifact_refs": [{"path": "out/bench.csv"}]},
        {"text": "baseline 100 GB/s", "repro_status": "unverified", "artifact_refs": []},
    ]}
    block = vc.render_grounded_block(ctx)
    assert "GROUNDED CLAIMS" in block
    assert "[rerun_passed] tile=32 -> 842 GB/s" in block
    assert "out/bench.csv" in block
    assert "Do NOT invent numbers" in block
