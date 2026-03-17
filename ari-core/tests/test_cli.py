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
