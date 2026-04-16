"""Tests for api_state._resolve_node_work_dir.

Guard against the regression where two runs with the same experiment name
share experiments/{slug}/ and return each other's node work directories.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ari.paths import PathManager
from ari.viz.api_state import _resolve_node_work_dir


def _make_workspace(tmp_path: Path, run_id: str) -> tuple[PathManager, Path]:
    pm = PathManager(tmp_path)
    ckpt = pm.ensure_checkpoint(run_id)
    return pm, ckpt


def test_resolves_run_id_bucket(tmp_path):
    """Primary (post-fix) layout: experiments/{run_id}/{node_id}/."""
    run_id = "20260415000000_same_topic"
    pm, ckpt = _make_workspace(tmp_path, run_id)
    node_id = "node_abcdef01"
    pm.ensure_node_work_dir(run_id, node_id)

    resolved = _resolve_node_work_dir(ckpt, node_id)
    assert resolved is not None
    assert resolved == pm.node_work_dir(run_id, node_id)


def test_same_topic_runs_return_distinct_dirs(tmp_path):
    """Two runs sharing an experiment name must not alias each other."""
    pm = PathManager(tmp_path)
    run_a = "20260415000000_shared_topic"
    run_b = "20260415010000_shared_topic"
    ckpt_a = pm.ensure_checkpoint(run_a)
    ckpt_b = pm.ensure_checkpoint(run_b)

    node_id = "node_abcdef01"  # simulate UUID collision worst case
    wd_a = pm.ensure_node_work_dir(run_a, node_id)
    wd_b = pm.ensure_node_work_dir(run_b, node_id)
    (wd_a / "mark_a.txt").write_text("A")
    (wd_b / "mark_b.txt").write_text("B")

    resolved_a = _resolve_node_work_dir(ckpt_a, node_id)
    resolved_b = _resolve_node_work_dir(ckpt_b, node_id)

    assert resolved_a == wd_a
    assert resolved_b == wd_b
    assert resolved_a != resolved_b
    assert (resolved_a / "mark_a.txt").exists()
    assert not (resolved_a / "mark_b.txt").exists()
    assert (resolved_b / "mark_b.txt").exists()
    assert not (resolved_b / "mark_a.txt").exists()


def test_legacy_slug_fallback(tmp_path):
    """Pre-fix layout (experiments/{topic_slug}/{node_id}/) still resolves."""
    pm = PathManager(tmp_path)
    run_id = "20260414191541_Investigate_whether_benchmark_performanc"
    legacy_slug = "Investigate_whether_benchmark_performanc"
    ckpt = pm.ensure_checkpoint(run_id)
    node_id = "node_14a3f12b"

    legacy_dir = pm.experiments_root / legacy_slug / node_id
    legacy_dir.mkdir(parents=True)

    resolved = _resolve_node_work_dir(ckpt, node_id)
    assert resolved == legacy_dir


def test_missing_node_returns_none(tmp_path):
    pm = PathManager(tmp_path)
    ckpt = pm.ensure_checkpoint("20260415000000_topic")
    assert _resolve_node_work_dir(ckpt, "node_nope") is None
