"""Phase 1 — schemas / provenance / audit (verifiability core).

These are Letta-free: schema validation, sha256 provenance derived from
node_report.json, and artifact audit against disk. Uses synthetic work_dirs
for determinism plus an opt-in check against the real workspace checkpoint.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ari_skill_memory.audit import audit_node_report, summarize
from ari_skill_memory.provenance import (
    normalize_artifact_path,
    refs_from_node_report,
    sha256_of,
)
from ari_skill_memory.schemas import ArtifactRef, ResearchMemory


# ── schemas ──────────────────────────────────────────────────────────────

def test_research_memory_rejects_unknown_kind():
    with pytest.raises(ValueError):
        ResearchMemory(id="m1", checkpoint_id="c", node_id="n", kind="bogus", text="x")


def test_research_memory_rejects_bad_repro_status():
    with pytest.raises(ValueError):
        ResearchMemory(
            id="m1", checkpoint_id="c", node_id="n", kind="experiment_result",
            text="x", repro_status="maybe",
        )


def test_reproducibility_event_requires_target():
    with pytest.raises(ValueError):
        ResearchMemory(id="m1", checkpoint_id="c", node_id="n",
                       kind="reproducibility_event", text="x")
    # valid when target supplied
    ev = ResearchMemory(id="m1", checkpoint_id="c", node_id="n",
                        kind="reproducibility_event", text="x",
                        repro_target_id="m0", repro_status="rerun_passed")
    assert ev.repro_target_id == "m0"


def test_to_metadata_promotes_mem_kind_top_level():
    m = ResearchMemory(
        id="m1", checkpoint_id="c", node_id="n", kind="experiment_result",
        text="tile=32 -> 842 GB/s",
        artifact_refs=[ArtifactRef(path="out/bench.csv", sha256="ab", role="data_output")],
        metric_ptr={"name": "GB/s", "value": 842.1},
    )
    md = m.to_metadata()
    assert md["mem_kind"] == "experiment_result"            # filterable top-level facet
    assert md["artifact_refs"][0]["path"] == "out/bench.csv"
    assert md["metric_ptr"]["value"] == 842.1


# ── provenance ───────────────────────────────────────────────────────────

def _write(p: Path, content: bytes) -> str:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)
    return hashlib.sha256(content).hexdigest()


def test_sha256_of_and_missing(tmp_path):
    h = _write(tmp_path / "a.txt", b"hello")
    assert sha256_of(tmp_path / "a.txt") == h
    assert sha256_of(tmp_path / "nope.txt") is None


def test_normalize_artifact_path_relative_and_abs(tmp_path):
    assert normalize_artifact_path("out/x.csv", tmp_path) == "out/x.csv"
    assert normalize_artifact_path(str(tmp_path / "out/x.csv"), tmp_path) == "out/x.csv"
    # outside base -> basename fallback
    assert normalize_artifact_path("/elsewhere/y.csv", tmp_path) == "y.csv"


def test_refs_reuse_files_changed_hash_and_hash_artifacts(tmp_path):
    # one changed file (hash recorded), one output artifact (hash computed now)
    recorded = _write(tmp_path / "kernel.c", b"int main(){}")
    out_hash = _write(tmp_path / "results.csv", b"k,v\n32,842\n")
    report = {
        "node_id": "n7",
        "files_changed": {"added": [{"path": "kernel.c", "sha256": recorded}]},
        "artifacts": [{"filename": "results.csv", "role": "data_output"}],
    }
    refs = {r.path: r for r in refs_from_node_report(report, tmp_path)}
    assert refs["kernel.c"].sha256 == recorded          # reused, not recomputed
    assert refs["results.csv"].sha256 == out_hash        # computed from disk
    assert refs["results.csv"].role == "data_output"


# ── audit ────────────────────────────────────────────────────────────────

def test_audit_verified_missing_and_mismatch(tmp_path):
    good = _write(tmp_path / "good.csv", b"correct")
    _write(tmp_path / "tampered.csv", b"v1")
    report = {
        "node_id": "n",
        "files_changed": {
            "added": [
                {"path": "good.csv", "sha256": good},
                {"path": "tampered.csv", "sha256": "deadbeef" * 8},  # wrong hash
                {"path": "gone.csv", "sha256": "00" * 32},           # missing file
            ]
        },
        "artifacts": [],
    }
    by_path = {r["path"]: r for r in audit_node_report(report, tmp_path)}
    assert by_path["good.csv"]["status"] == "verified"
    assert by_path["tampered.csv"]["status"] == "mismatch"
    assert by_path["gone.csv"]["status"] == "missing"


def test_audit_unhashed_when_no_recorded_hash(tmp_path):
    _write(tmp_path / "fig.png", b"PNG")
    report = {"node_id": "n", "files_changed": {}, "artifacts": [{"filename": "fig.png", "role": "figure"}]}
    res = audit_node_report(report, tmp_path)
    assert res[0]["status"] == "unhashed"  # exists, but nothing to compare


# ── opt-in: real checkpoint ──────────────────────────────────────────────

_REAL = Path("workspace/experiments/20260528180541_We_propose_an_implementation_of_CSR-form")


@pytest.mark.skipif(not _REAL.exists(), reason="real checkpoint not present")
def test_audit_real_checkpoint_node():
    node_dir = next(p for p in _REAL.iterdir() if (p / "node_report.json").exists())
    report = json.loads((node_dir / "node_report.json").read_text())
    results = audit_node_report(report, node_dir)
    counts = summarize(results)
    # real node has files_changed with sha256 → at least some verified/mismatch,
    # and the audit must run without error and classify every ref.
    assert results, "expected at least one artifact ref"
    assert set(counts) <= {"verified", "missing", "mismatch", "unhashed"}
