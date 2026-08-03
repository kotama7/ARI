"""Phase 1 — verified context for paper generation.

build_verified_context must (PLAN §4.5/§8.4):
  - rank rerun_passed > artifact-grounded > ungrounded;
  - expose only grounded, not-rerun_failed memory as usable_for_claims;
  - keep failure_case out of claims (as limitations);
  - respect ancestor scope (no sibling leakage).
"""
from __future__ import annotations

import hashlib

from ari_skill_memory import context_builder, writer
from ari_skill_memory.schemas import ArtifactRef


def _w(backend, monkeypatch, node_id, fn, *a, **k):
    k.setdefault("run_id", "run-test")
    k.setdefault("ancestor_ids", [])
    k.setdefault("created_by_tool_ref", "memory-test:verified-context")
    if k.get("artifact_refs"):
        k.setdefault("artifact_root", backend.cfg.checkpoint_dir)
    return fn(backend, node_id, *a, **k)


def _artifact(backend, path: str, content: str) -> ArtifactRef:
    target = backend.cfg.checkpoint_dir / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    return ArtifactRef(
        path=path,
        sha256=hashlib.sha256(content.encode()).hexdigest(),
        role="data_output",
    )


def test_usable_for_claims_requires_artifacts(backend, monkeypatch):
    _w(backend, monkeypatch, "root", writer.add_experiment_result,
       "grounded result 842 GB/s",
       artifact_refs=[_artifact(backend, "root/bench.csv", "842\n")])
    _w(backend, monkeypatch, "root", writer.add_experiment_result,
       "ungrounded claim no file")  # no artifacts
    _w(backend, monkeypatch, "root", writer.add_failure_case, "link error")

    ctx = context_builder.build_verified_context(backend, ["root"])
    usable = [c["text"] for c in ctx["usable_for_claims"]]
    assert any("grounded result" in t for t in usable)
    assert all("ungrounded" not in t for t in usable)        # not usable as claim
    assert any("link error" in lim["text"] for lim in ctx["limitations"])
    assert all("link error" not in c["text"] for c in ctx["claims"])  # failure ≠ claim


def test_rerun_passed_ranks_first_and_failed_is_not_usable(backend, monkeypatch):
    r1 = _w(backend, monkeypatch, "root", writer.add_experiment_result,
            "result G grounded",
            artifact_refs=[_artifact(backend, "g.csv", "grounded\n")])
    r2 = _w(backend, monkeypatch, "root", writer.add_experiment_result,
            "result P reproduced",
            artifact_refs=[_artifact(backend, "p.csv", "reproduced\n")])
    # P reproduced-passed (should rank first); G grounded but later marked failed
    _w(backend, monkeypatch, "root", writer.add_reproducibility_event,
       r2["record_id"], "rerun_passed")
    _w(backend, monkeypatch, "root", writer.add_reproducibility_event,
       r1["record_id"], "rerun_failed")

    ctx = context_builder.build_verified_context(backend, ["root"])
    assert ctx["claims"][0]["text"] == "result P reproduced"     # rerun_passed first
    assert ctx["claims"][0]["repro_status"] == "rerun_passed"
    usable_texts = [c["text"] for c in ctx["usable_for_claims"]]
    assert "result P reproduced" in usable_texts
    assert "result G grounded" not in usable_texts              # rerun_failed excluded


def test_verified_context_ancestor_scope(backend, monkeypatch):
    _w(backend, monkeypatch, "root", writer.add_experiment_result, "root claim",
       artifact_refs=[_artifact(backend, "r.csv", "root\n")])
    _w(backend, monkeypatch, "sib", writer.add_experiment_result, "sibling claim",
       artifact_refs=[_artifact(backend, "s.csv", "sibling\n")])
    ctx = context_builder.build_verified_context(backend, ["root"])
    texts = [c["text"] for c in ctx["claims"]]
    assert "root claim" in texts and "sibling claim" not in texts
