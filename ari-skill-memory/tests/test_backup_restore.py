"""Backup/restore round-trip for checkpoint-scoped Letta collections."""
from __future__ import annotations

import gzip
import json
import pytest


def test_backup_restore_roundtrip(ckpt_env, monkeypatch):
    # Import here so the env is already configured.
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ari-core"))
    from ari.memory_cli import (
        MemoryBackupIntegrityError, _backup_path, _do_backup, _do_migrate,
        _do_restore,
    )
    from ari_skill_memory.backends import get_backend
    from ari_skill_memory import writer

    b = get_backend(checkpoint_dir=ckpt_env)
    writer.add_observation(
        b,
        "root",
        "alpha",
        run_id="run-backup",
        ancestor_ids=[],
        created_by_tool_ref="memory-test:backup",
        attributes={"k": "v"},
    )
    writer.add_observation(
        b,
        "child",
        "beta",
        run_id="run-backup",
        ancestor_ids=["root"],
        created_by_tool_ref="memory-test:backup",
        attributes={"q": 1},
    )
    target = writer.add_experiment_result(
        b,
        "root",
        "reproduction target",
        run_id="run-backup",
        ancestor_ids=[],
        created_by_tool_ref="memory-test:backup",
    )
    writer.add_reproducibility_event(
        b,
        "root",
        target["record_id"],
        "rerun_failed",
        run_id="run-backup",
        ancestor_ids=[],
        created_by_tool_ref="memory-test:backup",
    )
    writer.add_reproducibility_event(
        b,
        "root",
        target["record_id"],
        "rerun_passed",
        run_id="run-backup",
        ancestor_ids=[],
        created_by_tool_ref="memory-test:backup",
    )
    b.react_add("ran kernel", {"node_id": "root"})

    result = _do_backup(ckpt_env)
    assert result["entries"] == 6
    assert result["records"] == 5
    assert result["backup_digest"].startswith("sha256:")
    assert _backup_path(ckpt_env).exists()
    first_bytes = _backup_path(ckpt_env).read_bytes()
    repeated = _do_backup(ckpt_env)
    assert repeated["artifact_digest"] == result["artifact_digest"]
    assert _backup_path(ckpt_env).read_bytes() == first_bytes

    # The snapshot is namespace-independent: it restores into a new, empty
    # checkpoint while preserving canonical record digests.
    clean = ckpt_env.parent / "clean-restore"
    clean.mkdir()
    (clean / ".ari-test-memory-backend").write_text("test-only\n")
    _backup_path(clean).write_bytes(first_bytes)
    clean_result = _do_restore(clean, on_conflict="merge")
    clean_backend = get_backend(checkpoint_dir=clean)
    clean_digests = {
        entry["metadata"]["record_digest"]
        for entries in clean_backend.list_all_nodes()["by_node"].values()
        for entry in entries
    }
    assert clean_digests == set(clean_result["record_digests"])
    from ari_skill_memory import retriever
    assert retriever.fold_reproducibility(clean_backend, ["root"])[
        target["record_id"]
    ]["status"] == "rerun_passed"

    # Purge and restore.
    b.purge_checkpoint()
    assert b.list_all_nodes().get("by_node") == {}
    res = _do_restore(ckpt_env, on_conflict="overwrite")
    assert res["restored"] >= 3
    # Entries back.
    all_nodes = b.list_all_nodes()["by_node"]
    assert "root" in all_nodes
    assert "child" in all_nodes
    assert len(b.react_get_all()) == 1

    # Repeating a merge is idempotent.
    repeated_restore = _do_restore(ckpt_env, on_conflict="merge")
    assert repeated_restore["restored"] == 0
    assert repeated_restore["skipped"] == 6

    # Any content mutation is rejected before backend writes occur.
    with gzip.open(_backup_path(ckpt_env), "rt", encoding="utf-8") as stream:
        tampered = json.load(stream)
    tampered["records"][0]["text"] = "forged result"
    with gzip.open(_backup_path(ckpt_env), "wt", encoding="utf-8") as stream:
        json.dump(tampered, stream)
    with pytest.raises(MemoryBackupIntegrityError, match="digest mismatch"):
        _do_restore(ckpt_env, on_conflict="merge")

    # Legacy conversion is explicit/offline, validates before mutation, and
    # produces canonical records plus a portable v1 backup.
    legacy = ckpt_env.parent / "legacy-migration"
    legacy.mkdir()
    (legacy / ".ari-test-memory-backend").write_text("test-only\n")
    old_entry = {
        "node_id": "legacy-node",
        "text": "legacy observation",
        "metadata": {"type": "result_summary", "run_id": "legacy-run"},
    }
    (legacy / "memory_store.jsonl").write_text(json.dumps(old_entry) + "\n")
    old_react = {
        "content": "legacy step",
        "metadata": {"node_id": "legacy-node"},
        "ts": 12.0,
    }
    (legacy / "memory.json").write_text(json.dumps([old_react]))
    dry_run = _do_migrate(legacy, include_react=True, dry_run=True)
    assert dry_run == {
        "records": 1,
        "react_entries": 1,
        "imported": 0,
        "archived_sources": [],
        "dry_run": True,
    }
    assert (legacy / "memory_store.jsonl").exists()

    migrated = _do_migrate(legacy, include_react=True)
    assert migrated["imported"] == 2
    assert migrated["backup"]["records"] == 1
    assert migrated["backup"]["react_entries"] == 1
    assert not (legacy / "memory_store.jsonl").exists()
    assert list(legacy.glob("memory_store.jsonl.migrated-*"))
    migrated_entry = get_backend(checkpoint_dir=legacy).get_node_memory(
        "legacy-node"
    )["entries"][0]
    record = migrated_entry["metadata"]["memory_record"]
    assert record["schema_version"] == "ari.memory-record/v1"
    assert record["kind"] == "observation"
    assert record["attributes"]["legacy_kind"] == "result_summary"

    # A retry after a crash/recreated source is content-idempotent for both
    # canonical node records and legacy ReAct entries.
    (legacy / "memory_store.jsonl").write_text(json.dumps(old_entry) + "\n")
    (legacy / "memory.json").write_text(json.dumps([old_react]))
    retried = _do_migrate(legacy, include_react=True)
    assert retried["imported"] == 0
    assert retried["skipped"] == 2
