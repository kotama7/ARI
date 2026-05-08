"""Tests for ari/cli.py - CLI command tests."""

import json
import tempfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ari.cli import app

runner = CliRunner()


def test_status_missing_checkpoint():
    result = runner.invoke(app, ["status", "/nonexistent/checkpoint"])
    assert result.exit_code != 0


def test_resume_missing_checkpoint():
    result = runner.invoke(app, ["resume", "/nonexistent/checkpoint"])
    assert result.exit_code != 0


def test_status_with_checkpoint():
    with tempfile.TemporaryDirectory() as tmpdir:
        tree = {
            "run_id": "test123",
            "experiment_file": "exp.md",
            "created_at": "2025-01-01T00:00:00",
            "nodes": [
                {
                    "id": "node_root",
                    "parent_id": None,
                    "depth": 0,
                    "status": "success",
                    "retry_count": 0,
                    "children": [],
                    "created_at": "2025-01-01T00:00:00",
                    "completed_at": "2025-01-01T00:01:00",
                }
            ],
        }
        tree_path = Path(tmpdir) / "tree.json"
        tree_path.write_text(json.dumps(tree))

        result = runner.invoke(app, ["status", tmpdir])
        assert result.exit_code == 0
        assert "test123" in result.output


def test_resume_with_checkpoint():
    """resume command exits normally when all nodes are already complete."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tree = {
            "run_id": "test456",
            "experiment_file": "exp.md",
            "created_at": "2025-01-01T00:00:00",
            "nodes": [
                {
                    "id": "node_root",
                    "parent_id": None,
                    "depth": 0,
                    "status": "success",  # already complete → pending=0 → immediate exit
                    "retry_count": 0,
                    "children": [],
                    "created_at": "2025-01-01T00:00:00",
                    "completed_at": "2025-01-01T00:01:00",
                }
            ],
        }
        tree_path = Path(tmpdir) / "tree.json"
        tree_path.write_text(json.dumps(tree))

        result = runner.invoke(app, ["resume", tmpdir])
        assert result.exit_code == 0
        assert "test456" in result.output


def test_skills_list_empty():
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "config.yaml"
        config_path.write_text("skills: []\n")

        result = runner.invoke(app, ["skills-list", "--config", str(config_path)])
        assert result.exit_code == 0
        assert "No skills" in result.output


def test_migrate_node_reports_legacy_checkpoint(tmp_path: Path):
    """`ari migrate node-reports <checkpoint>` writes a node_report.json
    next to each node's work_dir, with migration_source=auto."""
    workspace = tmp_path / "workspace"
    checkpoint = workspace / "checkpoints" / "exp123"
    checkpoint.mkdir(parents=True)
    # Build a 2-node legacy tree.
    tree = {
        "run_id": "exp123",
        "experiment_file": "exp.md",
        "created_at": "2025-01-01T00:00:00",
        "nodes": [
            {
                "id": "node_root",
                "parent_id": None,
                "depth": 0,
                "status": "success",
                "retry_count": 0,
                "children": ["node_b"],
                "created_at": "2025-01-01T00:00:00",
                "completed_at": "2025-01-01T00:01:00",
                "label": "draft",
                "metrics": {"x": 1.0},
                "has_real_data": True,
                "eval_summary": "ok [scientific_score=0.5]",
                "artifacts": [],
            },
            {
                "id": "node_b",
                "parent_id": "node_root",
                "depth": 1,
                "status": "success",
                "retry_count": 0,
                "children": [],
                "created_at": "2025-01-01T00:02:00",
                "completed_at": "2025-01-01T00:03:00",
                "label": "improve",
                "metrics": {"x": 2.0},
                "has_real_data": True,
                "eval_summary": "better [scientific_score=0.7]",
                "artifacts": [],
                "ancestor_ids": ["node_root"],
            },
        ],
    }
    (checkpoint / "tree.json").write_text(json.dumps(tree))
    # Make work_dirs so files_changed reconstruction has something to look at.
    exp_root = workspace / "experiments" / "exp123"
    (exp_root / "node_root").mkdir(parents=True)
    (exp_root / "node_b").mkdir(parents=True)
    (exp_root / "node_root" / "x.py").write_text("v1\n")
    (exp_root / "node_b" / "x.py").write_text("v2\n")

    result = runner.invoke(app, ["migrate", "node-reports", str(checkpoint)])
    assert result.exit_code == 0, result.output
    assert "migrated" in result.output

    rep_a = json.loads((exp_root / "node_root" / "node_report.json").read_text())
    rep_b = json.loads((exp_root / "node_b" / "node_report.json").read_text())
    assert rep_a["migration_source"] == "auto"
    assert rep_b["migration_source"] == "auto"
    # node_b should show x.py as modified vs node_root.
    modified = {m["path"] for m in rep_b["files_changed"]["modified"]}
    assert "x.py" in modified


def test_migrate_node_reports_skips_existing(tmp_path: Path):
    """An existing node_report.json must not be overwritten unless
    --overwrite is passed."""
    workspace = tmp_path / "workspace"
    checkpoint = workspace / "checkpoints" / "exp"
    checkpoint.mkdir(parents=True)
    tree = {
        "run_id": "exp",
        "nodes": [{
            "id": "node_a", "parent_id": None, "depth": 0,
            "status": "success", "retry_count": 0, "children": [],
            "created_at": "x", "completed_at": "y",
            "label": "draft", "metrics": {}, "has_real_data": True,
            "eval_summary": "", "artifacts": [],
        }],
    }
    (checkpoint / "tree.json").write_text(json.dumps(tree))
    work = workspace / "experiments" / "exp" / "node_a"
    work.mkdir(parents=True)
    existing = work / "node_report.json"
    existing.write_text('{"schema_version": 1, "preserved": true}')

    result = runner.invoke(app, ["migrate", "node-reports", str(checkpoint)])
    assert result.exit_code == 0
    # Untouched.
    rep = json.loads(existing.read_text())
    assert rep.get("preserved") is True

    # With --overwrite, it gets replaced.
    result2 = runner.invoke(
        app, ["migrate", "node-reports", str(checkpoint), "--overwrite"])
    assert result2.exit_code == 0
    rep2 = json.loads(existing.read_text())
    assert rep2.get("preserved") is None
    assert rep2.get("migration_source") == "auto"
