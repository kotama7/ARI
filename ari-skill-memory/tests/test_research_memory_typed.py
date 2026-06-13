"""Phase 1 — typed writer/retriever over the existing backend (no backend mod).

Uses the in-memory ``backend`` fixture (conftest). CoW requires writes to use
the current node id, so we monkeypatch ARI_CURRENT_NODE_ID per write.
"""
from __future__ import annotations

import pytest

from ari_skill_memory import writer, retriever
from ari_skill_memory.schemas import ArtifactRef


def _write_as(backend, monkeypatch, node_id, fn, *args, **kw):
    monkeypatch.setenv("ARI_CURRENT_NODE_ID", node_id)
    return fn(backend, node_id, *args, **kw)


# ── writer stamps kind + refs ────────────────────────────────────────────

def test_add_experiment_result_stamps_kind_and_refs(backend, monkeypatch):
    res = _write_as(
        backend, monkeypatch, "nX", writer.add_experiment_result,
        "tile=32 -> 842 GB/s",
        metric_ptr={"name": "GB/s", "value": 842.1},
        artifact_refs=[ArtifactRef(path="out/bench.csv", sha256="ab", role="data_output")],
    )
    assert res["ok"]
    entry = backend.get_node_memory("nX")["entries"][0]
    md = entry["metadata"]
    assert md["type"] == "experiment_result" and md["mem_kind"] == "experiment_result"
    assert md["artifact_refs"][0]["path"] == "out/bench.csv"
    assert md["metric_ptr"]["value"] == 842.1


def test_writer_rejects_unknown_kind(backend, monkeypatch):
    monkeypatch.setenv("ARI_CURRENT_NODE_ID", "nX")
    with pytest.raises(ValueError):
        writer.add_typed_memory(backend, "nX", "bogus", "x")


# ── retriever: kind filter + ancestor scope + require_artifacts ──────────

def _seed_tree(backend, monkeypatch):
    # root: experiment_result (with artifact) ; p1: failure_case ; sibling sX: experiment_result
    _write_as(backend, monkeypatch, "root", writer.add_experiment_result,
              "root baseline 100 GB/s on partA",
              artifact_refs=[ArtifactRef(path="root/results.csv", sha256="r1", role="data_output")])
    _write_as(backend, monkeypatch, "p1", writer.add_failure_case,
              "link failed on partA cublasLt missing")
    _write_as(backend, monkeypatch, "p1", writer.add_experiment_result,
              "p1 tiling 140 GB/s on partA")  # no artifact
    _write_as(backend, monkeypatch, "sib", writer.add_experiment_result,
              "sibling 999 GB/s on partA")


def test_search_filters_by_kind_and_scope(backend, monkeypatch):
    _seed_tree(backend, monkeypatch)
    # query matches "partA"; ancestors = root, p1 (sibling excluded)
    res = retriever.search_research_memory(
        backend, "partA", ["root", "p1"], kinds=["failure_case"], limit=5,
    )
    texts = [r["text"] for r in res["results"]]
    assert any("link failed" in t for t in texts)
    assert all("sibling" not in t for t in texts)        # sibling scoped out
    assert all("baseline" not in t for t in texts)       # experiment_result filtered out


def test_search_require_artifacts(backend, monkeypatch):
    _seed_tree(backend, monkeypatch)
    res = retriever.search_research_memory(
        backend, "partA", ["root", "p1"], kinds=["experiment_result"],
        require_artifacts=True, limit=5,
    )
    texts = [r["text"] for r in res["results"]]
    assert any("baseline" in t for t in texts)           # root has artifact
    assert all("tiling" not in t for t in texts)         # p1 result has no artifact


def test_ancestor_typed_memory_deterministic_full_in_order(backend, monkeypatch):
    _seed_tree(backend, monkeypatch)
    out = retriever.ancestor_typed_memory(
        backend, ["root", "p1"], kinds=["experiment_result"],
    )
    texts = [o["text"] for o in out]
    assert any("baseline" in t for t in texts) and any("tiling" in t for t in texts)
    assert all("sibling" not in t for t in texts)
    # ancestor order: root before p1
    assert next(i for i, t in enumerate(texts) if "baseline" in t) < \
           next(i for i, t in enumerate(texts) if "tiling" in t)


# ── reproducibility events: append-only + fold ──────────────────────────

def test_reproducibility_events_fold_latest(backend, monkeypatch):
    r = _write_as(backend, monkeypatch, "n1", writer.add_experiment_result, "result A")
    target = r["id"]
    # two append-only events for the same target; latest wins
    _write_as(backend, monkeypatch, "n1", writer.add_reproducibility_event,
              target, "rerun_failed")
    _write_as(backend, monkeypatch, "n1", writer.add_reproducibility_event,
              target, "rerun_passed")
    folded = retriever.fold_reproducibility(backend, ["n1"])
    assert folded[target]["status"] == "rerun_passed"
    # original result memory is untouched (byte-stable / CoW)
    assert any(e["text"] == "result A" for e in backend.get_node_memory("n1")["entries"])


def test_reproducibility_event_rejects_bad_status(backend, monkeypatch):
    monkeypatch.setenv("ARI_CURRENT_NODE_ID", "n1")
    with pytest.raises(ValueError):
        writer.add_reproducibility_event(backend, "n1", "mem0", "totally_passed")
