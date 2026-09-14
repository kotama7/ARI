"""Golden legacy-checkpoint paper and replay compatibility contract."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from ari.checkpoint import load_nodes_tree
from ari.migrations.checkpoint import LegacyCheckpointError, load_legacy_checkpoint
from ari.viz import checkpoint_api


FIXTURE = (
    Path(__file__).parent / "fixtures" / "checkpoints" / "v0_7_golden"
).resolve()


def _tree_digest(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_golden_checkpoint_reader_preserves_paper_and_replay_inputs(monkeypatch):
    before = _tree_digest(FIXTURE)
    view = load_legacy_checkpoint(FIXTURE)

    assert view.schema_version == "ari.legacy-checkpoint-view/v1"
    assert view.run_id == "legacy-run-001"
    assert view.tree_layout == "node_*/tree.json"
    assert view.tree == load_nodes_tree(FIXTURE)
    assert view.tree["nodes"][0]["metrics"]["throughput_gflops"] == 125.0
    assert view.paper_relative_path == "full_paper.tex"
    assert "1.25x improvement" in view.paper_source
    assert "Golden legacy replay" in view.replay_inputs["experiment_md"]
    assert view.replay_inputs["launch_config"]["model"] == "fixture/model-v1"
    assert view.replay_inputs["workflow"]["pipeline"][0]["stage"] == "write_paper"
    assert all(digest.startswith("sha256:") for digest in view.source_digests.values())

    monkeypatch.setattr(checkpoint_api, "_resolve_checkpoint_dir", lambda _cid: FIXTURE)
    summary = checkpoint_api._api_checkpoint_summary(FIXTURE.name)
    assert summary["paper_tex"] == view.paper_source
    assert summary["nodes_tree"] == view.tree
    assert _tree_digest(FIXTURE) == before, "migration reader must be read-only"


def test_checkpoint_reader_rejects_symlink_escape(tmp_path: Path):
    outside = tmp_path / "outside.json"
    outside.write_text('{"nodes": []}', encoding="utf-8")
    checkpoint = tmp_path / "checkpoint"
    checkpoint.mkdir()
    (checkpoint / "tree.json").symlink_to(outside)

    with pytest.raises(LegacyCheckpointError, match="escapes root"):
        load_legacy_checkpoint(checkpoint)
