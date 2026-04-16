"""Regression tests for deleting a project and its experiments directory.

User report: after deleting a project from the GUI's Project Management
section, the sibling ``workspace/experiments/{run_id}/`` directory — which
holds per-node work_dirs with compiled artifacts, SIF files, and uploads —
was left behind.

Root cause: the CLI historically minted its own ``run_id`` (LLM-generated
title + fresh timestamp) that drifted from the GUI-prepared checkpoint
directory name. The delete handler joined ``experiments_root`` with the
checkpoint's name and missed the real (differently-named) experiments dir.

Fix 1: ``ari.cli.run`` now adopts ``ARI_CHECKPOINT_DIR``'s basename as the
``run_id`` so the two directories share a name.

Fix 2: ``_api_delete_checkpoint`` additionally searches for siblings that
share the 14-digit timestamp prefix or that contain ``node_{ckpt}_*``
sub-directories — covering pre-existing orphans and belt-and-braces.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """Build a fake workspace with checkpoints/ and experiments/ siblings."""
    ws = tmp_path / "workspace"
    (ws / "checkpoints").mkdir(parents=True)
    (ws / "experiments").mkdir()
    # Point viz state at this workspace.
    from ari.viz import state as _st
    monkeypatch.setattr(_st, "_ari_root", ws.parent)
    return ws


def _touch_file(p: Path, content: str = "x") -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


# ── Case A: aligned names — basic cleanup ───────────────────────────


def test_delete_removes_aligned_experiments_dir(workspace, monkeypatch):
    """When checkpoint and experiments share a run_id, both are removed."""
    from ari.viz.api_state import _api_delete_checkpoint

    run_id = "20260416120000_aligned_run"
    ckpt = workspace / "checkpoints" / run_id
    exp = workspace / "experiments" / run_id
    ckpt.mkdir()
    (ckpt / "experiment.md").write_text("goal")
    _touch_file(exp / f"node_{run_id}_root" / "artifact.txt")

    body = json.dumps({"path": str(ckpt)}).encode()
    result = _api_delete_checkpoint(body)

    assert result.get("ok") is True
    assert not ckpt.exists()
    assert not exp.exists(), "aligned experiments dir must be deleted"


# ── Case B: legacy orphan — timestamp-prefix fallback ────────────────


def test_delete_leaves_unrelated_timestamp_sibling_alone(workspace):
    """Timestamp-prefix alone is too coarse a signal — two projects started
    within the same second must not be entangled. Only aligned-name or
    node-subdir matches should trigger cleanup.
    """
    from ari.viz.api_state import _api_delete_checkpoint

    ts = "20260416120000"
    ckpt_name = f"{ts}_project_a"
    other_name = f"{ts}_project_b"
    ckpt = workspace / "checkpoints" / ckpt_name
    ckpt.mkdir()
    other_exp = workspace / "experiments" / other_name
    _touch_file(other_exp / "node_unrelated_root" / "file.txt")

    body = json.dumps({"path": str(ckpt)}).encode()
    _api_delete_checkpoint(body)

    assert other_exp.exists(), (
        "matching timestamp alone must not cause deletion of an unrelated "
        "project's experiments dir"
    )


# ── Case C: node-dir fallback ────────────────────────────────────────


def test_delete_removes_orphan_via_node_subdir_match(workspace):
    """When the experiments dir name drifts entirely but contains a node
    directory whose name embeds the checkpoint's run_id, we still find it.
    """
    from ari.viz.api_state import _api_delete_checkpoint

    ckpt_name = "20260416120000_ckpt_name"
    exp_name = "20260416131515_completely_different"  # different timestamp
    ckpt = workspace / "checkpoints" / ckpt_name
    exp = workspace / "experiments" / exp_name
    ckpt.mkdir()
    _touch_file(exp / f"node_{ckpt_name}_root" / "out.log")

    body = json.dumps({"path": str(ckpt)}).encode()
    result = _api_delete_checkpoint(body)

    assert result.get("ok") is True
    assert not exp.exists(), (
        "experiments dir containing node_{ckpt_name}_* must be deleted "
        "even when the dir name itself does not match"
    )


# ── Case D: unrelated dirs preserved ─────────────────────────────────


def test_delete_preserves_unrelated_experiments(workspace):
    """Deleting project A must not touch project B's experiments dir."""
    from ari.viz.api_state import _api_delete_checkpoint

    a = "20260416120000_project_a"
    b = "20260501090000_project_b"
    (workspace / "checkpoints" / a).mkdir()
    _touch_file(workspace / "experiments" / a / "file.txt")
    _touch_file(workspace / "experiments" / b / "file.txt")

    body = json.dumps({"path": str(workspace / "checkpoints" / a)}).encode()
    _api_delete_checkpoint(body)

    assert not (workspace / "experiments" / a).exists()
    assert (workspace / "experiments" / b).exists(), (
        "unrelated project's experiments must not be deleted"
    )


# ── Case E: cli run_id adoption ──────────────────────────────────────


def test_cli_adopts_checkpoint_dir_name_as_run_id(tmp_path, monkeypatch):
    """When ARI_CHECKPOINT_DIR is set (GUI path), the CLI must not mint a
    fresh run_id — it must reuse the checkpoint directory's basename so
    experiments/{run_id}/ aligns with checkpoints/{run_id}/.
    """
    import ari.cli as cli_mod
    source = Path(cli_mod.__file__).read_text()
    # The key mechanism: adopting ARI_CHECKPOINT_DIR's name before the
    # timestamp/LLM title path. If this block is ever removed, the delete
    # alignment breaks again and the user's bug returns.
    assert 'ARI_CHECKPOINT_DIR' in source
    assert '_adopted_run_id' in source, (
        "cli.run must derive run_id from the GUI-prepared checkpoint dir "
        "so experiments/{run_id}/ is cleaned when the checkpoint is deleted"
    )


def test_cli_run_with_adopted_run_id_does_not_crash(tmp_path, monkeypatch):
    """Regression: the adoption branch must define every local the else
    branch defines (``_slug`` in particular), or downstream references
    raise ``UnboundLocalError: cannot access local variable '_slug'``.
    """
    from unittest import mock
    from typer.testing import CliRunner

    from ari.cli import app

    exp = tmp_path / "experiment.md"
    exp.write_text("Any goal text\n")
    pre_ckpt = tmp_path / "20260416044720_Investigate_whether_benchmark_performanc"
    pre_ckpt.mkdir()
    cfg = tmp_path / "cfg.yaml"
    cfg.write_text(
        "llm:\n  model: fake\n"
        f"checkpoint:\n  dir: {pre_ckpt}\n"
        f"logging:\n  dir: {pre_ckpt}\n"
    )

    monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(pre_ckpt))

    captured = {}

    def _capture(cfg_, bfts, agent, pending, nodes, experiment_data, ckpt_dir, run_id):
        captured["run_id"] = run_id
        captured["topic"] = experiment_data.get("topic", "")
        return 0

    with mock.patch("ari.cli.build_runtime") as mock_rt, \
         mock.patch("ari.cli._run_loop", side_effect=_capture), \
         mock.patch("ari.cli.generate_paper_section"):
        mock_rt.return_value = (
            None, None, None, mock.MagicMock(), mock.MagicMock(), None, None,
        )
        result = CliRunner().invoke(app, ["run", str(exp), "--config", str(cfg)])

    # The key assertion: we must not get UnboundLocalError before _run_loop.
    assert result.exit_code == 0, (
        f"cli.run crashed with adopted run_id: exit={result.exit_code}\n"
        f"output:\n{result.output}\n"
        f"exc: {result.exception!r}"
    )
    assert captured.get("run_id") == pre_ckpt.name
    # experiment_data['topic'] must have a non-empty string value;
    # the original bug left _slug unbound so this line would never run.
    assert isinstance(captured.get("topic"), str)
    assert captured["topic"], "topic (derived from _slug) must be non-empty"
