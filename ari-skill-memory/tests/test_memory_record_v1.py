"""Versioned record integrity, idempotency, and production-boundary tests."""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from ari_skill_memory import retriever, writer


def _write(backend, *, node_id: str = "node-a", text: str = "stable result") -> dict:
    return writer.add_experiment_result(
        backend,
        node_id,
        text,
        run_id="run-concurrent",
        ancestor_ids=["root"],
        created_by_tool_ref="memory-test:idempotency",
    )


def test_parallel_identical_writes_are_one_append_only_record(backend, ckpt_env):
    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(lambda _: _write(backend), range(32)))

    assert len({result["record_digest"] for result in results}) == 1
    assert len({result["id"] for result in results}) == 1
    assert sum(bool(result["deduplicated"]) for result in results) == 31
    entries = backend.get_node_memory("node-a")["entries"]
    assert len(entries) == 1

    events = [
        json.loads(line)
        for line in (ckpt_env / "memory_events.jsonl").read_text().splitlines()
    ]
    assert len(events) == 1
    assert events[0]["record_digest"] == results[0]["record_digest"]
    assert events[0]["event_digest"].startswith("sha256:")


def test_event_ledger_does_not_mask_record_after_admin_purge(backend, ckpt_env):
    first = _write(backend)
    backend.purge_checkpoint()
    second = _write(backend)

    assert second["record_digest"] == first["record_digest"]
    assert len(backend.get_node_memory("node-a")["entries"]) == 1
    assert len((ckpt_env / "memory_events.jsonl").read_text().splitlines()) == 1


def test_corrupt_event_ledger_fails_closed(backend, ckpt_env):
    _write(backend)
    event_path = ckpt_env / "memory_events.jsonl"
    event = json.loads(event_path.read_text())
    event["source_node_id"] = "forged-node"
    event_path.write_text(json.dumps(event) + "\n")

    with pytest.raises(ValueError, match="ledger digest mismatch"):
        _write(backend)
    assert len(backend.get_node_memory("node-a")["entries"]) == 1


def test_artifact_digest_is_verified_before_write(backend, ckpt_env):
    artifact = ckpt_env / "evidence.csv"
    artifact.write_text("measured,42\n")
    actual = hashlib.sha256(artifact.read_bytes()).hexdigest()

    with pytest.raises(ValueError, match="digest mismatch"):
        writer.add_experiment_result(
            backend,
            "node-a",
            "tampered evidence",
            run_id="run-integrity",
            ancestor_ids=[],
            created_by_tool_ref="memory-test:integrity",
            artifact_refs=[{
                "path": "evidence.csv",
                "sha256": "0" * 64,
                "role": "data_output",
            }],
            artifact_root=ckpt_env,
        )

    accepted = writer.add_experiment_result(
        backend,
        "node-a",
        "verified evidence",
        run_id="run-integrity",
        ancestor_ids=[],
        created_by_tool_ref="memory-test:integrity",
        artifact_refs=[{
            "path": "evidence.csv",
            "sha256": actual,
            "role": "data_output",
        }],
        artifact_root=ckpt_env,
    )
    assert accepted["ok"]
    record = backend.get_node_memory("node-a")["entries"][0]["metadata"][
        "memory_record"
    ]
    assert record["artifact_refs"][0]["integrity_status"] == "verified"


def test_artifact_verification_rejects_symlink_components(
    backend, ckpt_env, tmp_path
):
    outside = tmp_path / "outside"
    outside.mkdir()
    artifact = outside / "evidence.csv"
    artifact.write_text("outside\n")
    (ckpt_env / "linked").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="missing or unsafe"):
        writer.add_experiment_result(
            backend,
            "node-a",
            "symlinked evidence",
            run_id="run-integrity",
            ancestor_ids=[],
            created_by_tool_ref="memory-test:integrity",
            artifact_refs=[{
                "path": "linked/evidence.csv",
                "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                "role": "data_output",
            }],
            artifact_root=ckpt_env,
        )


def test_retrieval_uses_canonical_record_not_mutable_projections(backend):
    _write(backend, text="canonical experiment")
    entry = backend.get_node_memory("node-a")["entries"][0]
    entry["metadata"]["mem_kind"] = "failure_case"
    entry["metadata"]["artifact_refs"] = []

    result = retriever.search_research_memory(
        backend,
        "canonical",
        ["node-a"],
        kinds=["experiment_result"],
    )
    assert len(result["results"]) == 1
    assert result["results"][0]["record"]["kind"] == "experiment_result"

    differently_filtered = retriever.search_research_memory(
        backend,
        "canonical",
        ["node-a"],
        kinds=None,
    )
    assert (
        differently_filtered["provenance"]["query_digest"]
        != result["provenance"]["query_digest"]
    )


def test_retrieval_rejects_tampered_canonical_record(backend):
    _write(backend)
    entry = backend.get_node_memory("node-a")["entries"][0]
    entry["metadata"]["memory_record"]["text"] = "changed after digest"
    with pytest.raises(ValueError, match="digest mismatch"):
        retriever.ancestor_typed_memory(backend, ["node-a"])


def test_in_memory_backend_requires_explicit_test_namespace(tmp_path, monkeypatch):
    from ari_skill_memory.config import load_config

    monkeypatch.setenv("ARI_MEMORY_BACKEND", "in_memory")
    with pytest.raises(RuntimeError, match="test-only"):
        load_config(tmp_path)

    (tmp_path / ".ari-test-memory-backend").write_text("test-only\n")
    assert load_config(tmp_path).backend_name == "in_memory"
