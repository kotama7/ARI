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

from ari.public.memory import MemoryRecordV1, build_memory_record
from ari_skill_memory.audit import audit_node_report, summarize
from ari_skill_memory.provenance import (
    normalize_artifact_path,
    refs_from_node_report,
    sha256_of,
)
# ── schemas ──────────────────────────────────────────────────────────────

def _record(**overrides):
    values = {
        "kind": "experiment_result",
        "text": "tile=32 -> 842 GB/s",
        "source_run_id": "run-test",
        "source_node_id": "node-test",
        "ancestor_node_ids": [],
        "artifact_refs": [],
        "created_by_tool_ref": "memory-test:schema",
    }
    values.update(overrides)
    return build_memory_record(**values)


def test_memory_record_rejects_unknown_kind():
    with pytest.raises(ValueError):
        _record(kind="bogus")


def test_memory_record_rejects_bad_repro_status():
    with pytest.raises(ValueError):
        _record(kind="reproducibility_event", repro_status="maybe")


def test_memory_record_binds_lineage_and_node_report_source():
    with pytest.raises(ValueError, match="source node"):
        _record(ancestor_node_ids=["node-test"])
    with pytest.raises(ValueError, match="must match"):
        _record(
            node_report_ref={
                "run_id": "another-run",
                "node_id": "node-test",
                "digest": "sha256:" + "a" * 64,
            }
        )


def test_reproducibility_event_requires_target():
    with pytest.raises(ValueError):
        _record(kind="reproducibility_event")
    # valid when target supplied
    target = "sha256:" + "0" * 64
    ev = _record(
        kind="reproducibility_event",
        repro_target_id=target,
        repro_status="rerun_passed",
    )
    assert ev.repro_target_id == target


def test_memory_record_is_content_addressed_and_rejects_tampering():
    record = _record(
        artifact_refs=[{
            "relative_path": "out/bench.csv",
            "digest": "sha256:" + "a" * 64,
            "size_bytes": 12,
            "role": "data_output",
            "integrity_status": "verified",
        }],
        metric_ptr={"name": "throughput", "value": 842.1, "unit": "GB/s"},
    )
    assert record.record_id == record.record_digest
    raw = record.model_dump(mode="json")
    raw["text"] = "tampered"
    with pytest.raises(ValueError, match="digest mismatch"):
        MemoryRecordV1.model_validate(raw)


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


def test_inline_blob_is_not_a_phantom_missing(tmp_path):
    """agent/loop.py substitutes captured stdout for fake artifacts as an
    inline blob; node_report's builder marks it ``inline`` with a display-only
    ``filename`` (the type, e.g. "result"). It has no file on disk, so the
    audit must SKIP it — otherwise every such node reports a `missing`
    artifact for a file that was never meant to exist, training a reader to
    ignore `missing` entirely."""
    _write(tmp_path / "real.csv", b"data")
    good = sha256_of(tmp_path / "real.csv")
    report = {
        "node_id": "n",
        "files_changed": {"added": [{"path": "real.csv", "sha256": good}]},
        "artifacts": [
            {"filename": "result", "role": "unknown", "inline": True},
        ],
    }
    res = audit_node_report(report, tmp_path)
    statuses = {r["path"]: r["status"] for r in res}
    assert statuses == {"real.csv": "verified"}, statuses
    assert "result" not in statuses  # the inline blob produced no ref at all


def test_a_deleted_file_is_still_missing_without_the_inline_marker(tmp_path):
    """The inline skip must not blind the audit to genuine deletions: an
    artifacts entry WITHOUT ``inline`` whose file is gone is still `missing`."""
    report = {
        "node_id": "n",
        "files_changed": {"added": [{"path": "gone.py", "sha256": "ab" * 32}]},
        "artifacts": [],
    }
    res = audit_node_report(report, tmp_path)
    assert [r["status"] for r in res] == ["missing"]


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
