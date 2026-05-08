"""Phase 4 — graceful degradation when VirSci is OFF or partially missing.

Validates that Phase 1-3 features keep working when ``idea.json`` is absent
or when a parent checkpoint cannot be located. The system must:

  - Not crash on missing ``idea.json``
  - Leave the user's ``experiment.md`` unchanged
  - Produce a usable BFTS expand idea_ctx (empty string OK; not raise)
  - Reject ``inherit_idea_index`` cleanly when the prerequisite is absent
  - Walk a lineage chain that contains some checkpoints without idea.json
  - Build dynamic axes that fall back to the generic floor only
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ari.cli import _build_idea_ctx_for_expand
from ari.evaluator.dynamic_axes import (
    GENERIC_AXIS_NAMES,
    build_axes_for_run,
)
from ari.lineage import (
    format_ancestor_pool_for_virsci,
    get_idea_pool_for_ckpt,
)
from ari.pipeline import _promote_plan_to_experiment_md


# ---------------------------------------------------------------------------
# Plan-promote when VirSci is off (no idea.json)
# ---------------------------------------------------------------------------


def test_promote_with_empty_idea_data_is_noop(tmp_path: Path):
    user_md = tmp_path / "experiment.md"
    user_md.write_text("user task\n")
    # Mimic the workflow when VirSci was off and idea.json never existed.
    changed = _promote_plan_to_experiment_md(tmp_path, {"ideas": []})
    assert changed is False
    assert user_md.read_text() == "user task\n"


def test_promote_off_mode_does_not_modify_file(tmp_path: Path):
    user_md = tmp_path / "experiment.md"
    user_md.write_text("user task\n")
    sample = {"ideas": [{"title": "x", "experiment_plan": "1) base", "overall_score": 0.5}]}
    changed = _promote_plan_to_experiment_md(tmp_path, sample, mode="off")
    assert changed is False
    assert user_md.read_text() == "user task\n"


# ---------------------------------------------------------------------------
# BFTS expand idea_ctx with no ideas
# ---------------------------------------------------------------------------


def test_idea_ctx_for_expand_empty_when_no_ideas():
    # Mirror the shape pipeline.py would produce on a VirSci-off run.
    ctx = _build_idea_ctx_for_expand({"ideas": []})
    assert ctx == ""


def test_idea_ctx_for_expand_empty_when_completely_empty_dict():
    assert _build_idea_ctx_for_expand({}) == ""


def test_idea_ctx_for_expand_handles_missing_plan():
    idea_data = {
        "ideas": [{"title": "T", "description": "D", "experiment_plan": ""}]
    }
    ctx = _build_idea_ctx_for_expand(idea_data)
    # Title and description still surface; no plan section, no exception.
    assert "T" in ctx
    assert "D" in ctx
    assert "Plan sections" not in ctx


# ---------------------------------------------------------------------------
# Lineage walk with mixed VirSci on/off ancestry
# ---------------------------------------------------------------------------


def _make_ckpt(base: Path, run_id: str, *, parent: str | None = None, ideas=None) -> Path:
    d = base / run_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "meta.json").write_text(json.dumps({"run_id": run_id, "parent_run_id": parent}))
    if ideas is not None:
        (d / "idea.json").write_text(json.dumps({"ideas": ideas}))
    return d


def test_lineage_walk_skips_missing_idea_json(tmp_path: Path, monkeypatch):
    """Ancestor without idea.json (VirSci off there) must not break the walk."""
    root = tmp_path / "checkpoints"
    root.mkdir()
    monkeypatch.setenv("ARI_ORCHESTRATOR_LOGS", str(root))
    # gp has VirSci output, parent ran with VirSci off, child has its own.
    _make_ckpt(root, "gp", ideas=[{"title": "GpTitle", "overall_score": 0.5}])
    _make_ckpt(root, "p", parent="gp", ideas=None)            # VirSci off
    c = _make_ckpt(root, "c", parent="p", ideas=[{"title": "CTitle", "overall_score": 0.7}])
    pool = get_idea_pool_for_ckpt(c)
    # Pool contains self + gp; the parent (no idea.json) is silently skipped.
    run_ids = [e["run_id"] for e in pool]
    assert run_ids == ["c", "gp"]


def test_format_ancestor_block_quiet_when_only_self(tmp_path: Path, monkeypatch):
    root = tmp_path / "checkpoints"
    root.mkdir()
    monkeypatch.setenv("ARI_ORCHESTRATOR_LOGS", str(root))
    c = _make_ckpt(root, "solo", ideas=[{"title": "OnlySelf", "overall_score": 0.6}])
    pool = get_idea_pool_for_ckpt(c)
    # Self-only pool produces no ancestor block (nothing to inject).
    assert format_ancestor_pool_for_virsci(pool) == ""


# ---------------------------------------------------------------------------
# inherit_idea_index error paths when VirSci off / parent missing
# ---------------------------------------------------------------------------


def _launch(body: dict) -> dict:
    from ari.viz.api_orchestrator import _api_launch_sub_experiment
    return _api_launch_sub_experiment(json.dumps(body).encode())


def test_inherit_rejects_missing_parent_idea_json(tmp_path: Path, monkeypatch):
    root = tmp_path / "checkpoints"
    root.mkdir()
    monkeypatch.setenv("ARI_ORCHESTRATOR_LOGS", str(root))
    _make_ckpt(root, "parent_no_virsci", ideas=None)  # VirSci off at parent
    res = _launch({
        "experiment_md": "child task",
        "parent_run_id": "parent_no_virsci",
        "inherit_idea_index": 0,
        "dry_run": True,
    })
    assert res["ok"] is False
    assert "idea.json missing" in res["error"]


def test_inherit_rejects_unknown_parent(tmp_path: Path, monkeypatch):
    root = tmp_path / "checkpoints"
    root.mkdir()
    monkeypatch.setenv("ARI_ORCHESTRATOR_LOGS", str(root))
    res = _launch({
        "experiment_md": "child task",
        "parent_run_id": "ghost",
        "inherit_idea_index": 0,
        "dry_run": True,
    })
    assert res["ok"] is False
    assert "not found" in res["error"]


def test_default_launch_works_without_any_virsci(tmp_path: Path, monkeypatch):
    """Top-level launch with no parent and no inherit must still succeed."""
    root = tmp_path / "checkpoints"
    root.mkdir()
    monkeypatch.setenv("ARI_ORCHESTRATOR_LOGS", str(root))
    res = _launch({
        "experiment_md": "fresh top-level task",
        "dry_run": True,
    })
    assert res["ok"] is True
    child_md = (Path(res["checkpoint_dir"]) / "experiment.md").read_text()
    assert child_md == "fresh top-level task"
    assert "AUTO-APPENDED" not in child_md


# ---------------------------------------------------------------------------
# Dynamic axes with no rubric / no idea.json
# ---------------------------------------------------------------------------


def test_dynamic_axes_falls_back_to_generic_floor():
    """build_axes_for_run() with no inputs returns just the 5 generic axes."""
    axes = build_axes_for_run()
    names = {a.name for a in axes}
    assert names == set(GENERIC_AXIS_NAMES)


def test_dynamic_axes_with_rubric_no_idea():
    rubric = {
        "id": "sc",
        "score_dimensions": [{"name": "scalability_evaluation", "description": "scaling"}],
    }
    axes = build_axes_for_run(rubric=rubric)
    names = {a.name for a in axes}
    # Generic floor + rubric-derived; no plan-derived (no idea.json).
    assert "scalability_evaluation" in names
    for k in GENERIC_AXIS_NAMES:
        assert k in names


def test_dynamic_axes_with_idea_no_rubric():
    """Without a rubric, the core (cross-domain) plan vocabulary still
    fires — but the HPC-specific Pmax/STREAM keywords stay dormant
    (lineage decisions domain-gating). The plan must mention something from
    the core vocabulary for any plan-derived axis to appear."""
    idea_data = {"ideas": [{
        "experiment_plan": (
            "Run with multiple seeds, baseline against prior work, "
            "report mean ± std confidence intervals."
        )
    }]}
    axes = build_axes_for_run(idea_data=idea_data)
    names = {a.name for a in axes}
    # Core vocabulary fires regardless of rubric.
    assert "baseline_comparison_present" in names
    assert "statistical_test_present" in names
    # HPC-specific axes do NOT fire without HPC rubric.
    assert "model_calibration_present" not in names
    for k in GENERIC_AXIS_NAMES:
        assert k in names
