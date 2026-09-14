"""Verified-context artifact for paper generation (本命).

Covers ari.pipeline.verified_context: best-node selection, scoping to the
root->best lineage, graceful empty output, and the prompt-block renderer.
Uses a fake memory backend so no Letta is required.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

from ari.pipeline import verified_context as vc


def _node(nid, *, ancestors=(), score=None, has_real=True, metric=None, erased=False):
    metrics = {}
    if score is not None:
        metrics["_scientific_score"] = score
    if metric is not None:
        metrics["GB_per_s"] = metric
    if erased:
        # RQGM selective-erasure sentinels as written by FrontierRepairEngine
        # (_flag_node): the score is deliberately retained alongside the flag.
        metrics["_stale"] = True
        metrics["_valid_for_frontier"] = False
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


def test_select_best_excludes_erased_nodes():
    # An erased node keeps its (stale, possibly higher) score but must never
    # win selection — the score was produced under a retired policy/prompt.
    nodes = [_node("stale", score=0.9, erased=True), _node("valid", score=0.3)]
    assert vc.select_best_node(nodes).id == "valid"


def test_select_best_none_when_all_erased():
    # Hard-exclude semantics: contaminated evidence does not become clean by
    # being the only evidence left.
    nodes = [_node("a", score=0.9, erased=True), _node("b", score=0.1, erased=True)]
    assert vc.select_best_node(nodes) is None


def test_select_best_erasure_precedes_real_data_preference():
    nodes = [
        _node("stale", score=0.9, has_real=True, erased=True),
        _node("valid", score=0.2, has_real=False),
    ]
    assert vc.select_best_node(nodes).id == "valid"   # never falls back to erased


def test_build_verified_context_empty_when_all_erased():
    nodes = [_node("stale", ancestors=["root"], score=0.9, erased=True)]
    out = vc.build_verified_context("/tmp/ck", nodes, backend=object())
    assert out["best_node_id"] is None and out["lineage"] == []


def test_build_lineage_excludes_erased_ancestors(monkeypatch):
    # A VALID winner can carry an ERASED ancestor (erasure never propagates
    # to descendants automatically); that ancestor's memory entries must not
    # ground the paper's claims. Unknown ancestor ids are kept.
    root = _node("root", score=0.1)
    erased_parent = _node("p1", score=0.4, erased=True)
    best = _node("leaf", ancestors=["root", "p1"], score=0.8)
    captured = {}

    def fake_build(backend, ancestor_ids, purpose="paper"):
        captured["lineage"] = list(ancestor_ids)
        return {"claims": [], "limitations": [], "usable_for_claims": []}

    monkeypatch.setattr(
        "ari_skill_memory.context_builder.build_verified_context", fake_build)
    out = vc.build_verified_context(
        "/tmp/ck", [root, erased_parent, best], backend=object())
    assert out["best_node_id"] == "leaf"
    assert captured["lineage"] == ["root", "leaf"]   # p1 dropped
    assert out["lineage"] == ["root", "leaf"]

    ghost_best = _node("leaf2", ancestors=["ghost"], score=0.9)
    out2 = vc.build_verified_context("/tmp/ck", [ghost_best], backend=object())
    assert out2["lineage"] == ["ghost", "leaf2"]     # unknown id kept


def test_write_verified_context_removes_stale_artifact_on_winner_change(tmp_path):
    # Invocation A wrote the artifact for winner X; X was later erased and the
    # fresh build has no winner. Left in place, the stale artifact would keep
    # grounding the paper on the erased lineage across re-invocations.
    (tmp_path / "verified_context.json").write_text(json.dumps(
        {"best_node_id": "X", "lineage": ["root", "X"],
         "usable_for_claims": [{"text": "stale 842 GB/s"}]}
    ))
    erased = _node("X", ancestors=["root"], score=0.9, erased=True)
    out = vc.write_verified_context(tmp_path, [erased], backend=object())
    assert out["best_node_id"] is None
    assert not (tmp_path / "verified_context.json").exists()


def test_write_verified_context_removes_stale_artifact_on_lineage_change(tmp_path):
    # The winner is UNCHANGED but a mid-lineage ancestor was erased and its
    # claims were the only grounded ones. The paper reads the FILE, not the
    # fresh build — the stale artifact (pre-erasure lineage + the erased
    # ancestor's claims) must not survive.
    (tmp_path / "verified_context.json").write_text(json.dumps(
        {"best_node_id": "leaf", "lineage": ["root", "p1", "leaf"],
         "usable_for_claims": [{"text": "from p1: 842 GB/s"}]}
    ))
    root = _node("root", score=0.1)
    erased_parent = _node("p1", score=0.4, erased=True)
    best = _node("leaf", ancestors=["root", "p1"], score=0.8)
    out = vc.write_verified_context(
        tmp_path, [root, erased_parent, best], backend=object())
    assert out["best_node_id"] == "leaf"
    assert out["lineage"] == ["root", "leaf"]
    assert not (tmp_path / "verified_context.json").exists()


def test_write_verified_context_keeps_artifact_when_winner_unchanged(tmp_path, monkeypatch):
    # A transient backend failure (empty fresh build, same winner) must not
    # discard a still-valid artifact.
    (tmp_path / "verified_context.json").write_text(json.dumps(
        {"best_node_id": "leaf", "lineage": ["root", "leaf"],
         "usable_for_claims": [{"text": "x 842 GB/s"}]}
    ))
    nodes = [_node("leaf", ancestors=["root"], score=0.8)]

    def boom(*a, **k):
        raise RuntimeError("letta down")

    monkeypatch.setattr("ari_skill_memory.context_builder.build_verified_context", boom)
    vc.write_verified_context(tmp_path, nodes, backend=object())
    assert (tmp_path / "verified_context.json").exists()


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
