"""Tests for Phase 2: lineage walk + inherit_idea_index sub-experiment API.

Covers:
- walk_ancestor_ckpts traverses parent_run_id chain
- get_idea_pool_for_ckpt aggregates self + ancestors
- format_ancestor_pool_for_virsci emits a usable context block
- _api_launch_sub_experiment with inherit_idea_index materialises the
  chosen alternative into the child's experiment.md
- Error paths: missing parent, missing idea.json, out-of-range index
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from ari.lineage import (
    _resolve_ckpt_by_run_id,
    format_ancestor_pool_for_virsci,
    get_idea_pool_for_ckpt,
    walk_ancestor_ckpts,
)


def _make_ckpt(
    base: Path,
    run_id: str,
    *,
    parent_run_id: str | None = None,
    ideas: list | None = None,
) -> Path:
    """Materialise a fake checkpoint with meta.json (and optional idea.json)."""
    d = base / run_id
    d.mkdir(parents=True, exist_ok=True)
    meta = {
        "run_id": run_id,
        "parent_run_id": parent_run_id,
        "recursion_depth": 0 if parent_run_id is None else 1,
    }
    (d / "meta.json").write_text(json.dumps(meta))
    if ideas is not None:
        (d / "idea.json").write_text(json.dumps({"ideas": ideas}))
    return d


@pytest.fixture
def lineage_tree(tmp_path, monkeypatch):
    """Build grandparent → parent → child checkpoints under a temp root."""
    root = tmp_path / "checkpoints"
    root.mkdir()
    monkeypatch.setenv("ARI_ORCHESTRATOR_LOGS", str(root))

    gp = _make_ckpt(
        root,
        "gp_001",
        ideas=[{"title": "GrandparentIdea", "overall_score": 0.6}],
    )
    p = _make_ckpt(
        root,
        "p_002",
        parent_run_id="gp_001",
        ideas=[
            {"title": "ParentSelected", "overall_score": 0.77, "experiment_plan": "1) base\n2) more"},
            {"title": "ParentAlt1", "overall_score": 0.75},
            {"title": "ParentAlt2", "overall_score": 0.74},
        ],
    )
    c = _make_ckpt(
        root,
        "c_003",
        parent_run_id="p_002",
        ideas=[{"title": "ChildOwn", "overall_score": 0.8}],
    )
    return {"root": root, "gp": gp, "p": p, "c": c}


# ---------------------------------------------------------------------------
# walk_ancestor_ckpts
# ---------------------------------------------------------------------------


def test_walk_yields_parent_then_grandparent(lineage_tree):
    chain = list(walk_ancestor_ckpts(lineage_tree["c"]))
    names = [p.name for p in chain]
    assert names == ["p_002", "gp_001"]


def test_walk_terminates_at_root(lineage_tree):
    chain = list(walk_ancestor_ckpts(lineage_tree["gp"]))
    assert chain == []


def test_walk_includes_self_when_asked(lineage_tree):
    chain = list(walk_ancestor_ckpts(lineage_tree["c"], include_self=True))
    assert [p.name for p in chain] == ["c_003", "p_002", "gp_001"]


def test_walk_handles_dangling_parent(tmp_path, monkeypatch):
    root = tmp_path / "checkpoints"
    root.mkdir()
    monkeypatch.setenv("ARI_ORCHESTRATOR_LOGS", str(root))
    # parent_run_id refers to a run that doesn't exist on disk.
    orphan = _make_ckpt(root, "orphan", parent_run_id="ghost", ideas=[])
    assert list(walk_ancestor_ckpts(orphan)) == []


# ---------------------------------------------------------------------------
# get_idea_pool_for_ckpt
# ---------------------------------------------------------------------------


def test_pool_aggregates_self_and_ancestors(lineage_tree):
    pool = get_idea_pool_for_ckpt(lineage_tree["c"])
    # Self entry (depth 0) + parent (1) + grandparent (2) = 3 entries.
    assert len(pool) == 3
    assert pool[0]["depth"] == 0
    assert pool[0]["run_id"] == "c_003"
    assert pool[1]["depth"] == 1
    assert pool[1]["run_id"] == "p_002"
    assert pool[2]["depth"] == 2
    assert pool[2]["run_id"] == "gp_001"


def test_pool_exclude_self(lineage_tree):
    pool = get_idea_pool_for_ckpt(lineage_tree["c"], exclude_self=True)
    # Only ancestors remain.
    assert [e["run_id"] for e in pool] == ["p_002", "gp_001"]


def test_pool_skip_walk(lineage_tree):
    pool = get_idea_pool_for_ckpt(lineage_tree["c"], walk_ancestors=False)
    assert len(pool) == 1
    assert pool[0]["run_id"] == "c_003"


def test_pool_skips_ckpts_without_idea_json(tmp_path, monkeypatch):
    root = tmp_path / "checkpoints"
    root.mkdir()
    monkeypatch.setenv("ARI_ORCHESTRATOR_LOGS", str(root))
    # Parent has no idea.json; child has.
    _make_ckpt(root, "p", ideas=None)
    c = _make_ckpt(root, "c", parent_run_id="p", ideas=[{"title": "x", "overall_score": 0.5}])
    pool = get_idea_pool_for_ckpt(c)
    assert [e["run_id"] for e in pool] == ["c"]


# ---------------------------------------------------------------------------
# format_ancestor_pool_for_virsci
# ---------------------------------------------------------------------------


def test_format_ancestor_block_excludes_self_entries(lineage_tree):
    pool = get_idea_pool_for_ckpt(lineage_tree["c"])
    block = format_ancestor_pool_for_virsci(pool)
    # ChildOwn is depth 0 (self) — must NOT appear.
    assert "ChildOwn" not in block
    # Ancestor titles MUST appear.
    assert "ParentSelected" in block
    assert "GrandparentIdea" in block
    # Treat-as-context guidance present so VirSci agents understand the role.
    assert "context" in block.lower()


def test_format_ancestor_block_empty_when_no_ancestors(lineage_tree):
    pool = get_idea_pool_for_ckpt(lineage_tree["gp"])  # no ancestors
    assert format_ancestor_pool_for_virsci(pool) == ""


def test_format_ancestor_block_empty_when_only_self(lineage_tree):
    pool = get_idea_pool_for_ckpt(lineage_tree["c"], walk_ancestors=False)
    assert format_ancestor_pool_for_virsci(pool) == ""


# ---------------------------------------------------------------------------
# _resolve_ckpt_by_run_id
# ---------------------------------------------------------------------------


def test_resolve_ckpt_by_run_id_via_dir_name(lineage_tree):
    found = _resolve_ckpt_by_run_id("p_002")
    assert found is not None
    assert found.name == "p_002"


def test_resolve_ckpt_by_run_id_unknown(lineage_tree):
    assert _resolve_ckpt_by_run_id("does_not_exist") is None


# ---------------------------------------------------------------------------
# _api_launch_sub_experiment with inherit_idea_index
# ---------------------------------------------------------------------------


def _launch(body: dict) -> dict:
    """Invoke the sub-experiment launcher synchronously with dry_run."""
    from ari.viz.api_orchestrator import _api_launch_sub_experiment
    return _api_launch_sub_experiment(json.dumps(body).encode())


def test_inherit_idea_index_materialises_alternative(lineage_tree, monkeypatch):
    monkeypatch.setenv("ARI_ORCHESTRATOR_LOGS", str(lineage_tree["root"]))
    # ari_root must exist for subprocess.cwd; dry_run avoids that path entirely.
    res = _launch({
        "experiment_md": "Original child task.\n",
        "parent_run_id": "p_002",
        "inherit_idea_index": 1,    # ParentAlt1
        "dry_run": True,
    })
    assert res["ok"] is True, res
    child_ckpt = Path(res["checkpoint_dir"])
    exp_md = (child_ckpt / "experiment.md").read_text()
    # The child's experiment.md retains the caller's text.
    assert "Original child task." in exp_md
    # …and gains a Selected block populated from parent's ideas[1].
    assert "ParentAlt1" in exp_md
    # ParentSelected (ideas[0]) must NOT have been picked.
    assert "ParentSelected" not in exp_md
    # Provenance: meta.json records the index used.
    meta = json.loads((child_ckpt / "meta.json").read_text())
    assert meta["parent_run_id"] == "p_002"
    assert meta["inherit_idea_index"] == 1


def test_inherit_idea_index_seeds_child_idea_json(lineage_tree, monkeypatch):
    """Phase 2.5: child idea.json is seeded with the pinned parent idea.

    Without this seed, the child's generate_ideas would overwrite the
    inheritance and BFTS would silently drift — see test_dynamic_axes for
    the related dynamic-axes contract.
    """
    monkeypatch.setenv("ARI_ORCHESTRATOR_LOGS", str(lineage_tree["root"]))
    res = _launch({
        "experiment_md": "child.\n",
        "parent_run_id": "p_002",
        "inherit_idea_index": 1,    # ParentAlt1
        "dry_run": True,
    })
    assert res["ok"] is True
    child_ckpt = Path(res["checkpoint_dir"])
    seed = json.loads((child_ckpt / "idea.json").read_text())
    assert len(seed["ideas"]) == 1
    pinned = seed["ideas"][0]
    assert pinned["title"] == "ParentAlt1"
    assert pinned["_pinned"] is True
    assert pinned["_inherited_from"] == {"parent_run_id": "p_002", "index": 1}
    # Top-level provenance also recorded so downstream tools can detect the
    # inherit relationship without parsing every idea.
    assert seed["_inherited_from"]["parent_run_id"] == "p_002"


def test_default_launch_does_not_seed_idea_json(lineage_tree, monkeypatch):
    """Without inherit_idea_index, no synthetic idea.json is written —
    child generate_ideas runs from scratch (current default behaviour)."""
    monkeypatch.setenv("ARI_ORCHESTRATOR_LOGS", str(lineage_tree["root"]))
    res = _launch({
        "experiment_md": "Pristine.\n",
        "parent_run_id": "p_002",
        "dry_run": True,
    })
    assert res["ok"] is True
    child_ckpt = Path(res["checkpoint_dir"])
    assert not (child_ckpt / "idea.json").exists()


# ---------------------------------------------------------------------------
# lineage decisions: nested inherit (grandparent → parent → child)
# ---------------------------------------------------------------------------


def test_inherit_idea_index_works_when_parent_idea_was_itself_inherited(
    tmp_path: Path, monkeypatch
):
    """The grandchild can inherit a parent idea even if that parent's
    idea.json was itself seeded via a previous inherit_idea_index launch
    (i.e. the parent's ideas[0] already has _pinned and _inherited_from)."""
    root = tmp_path / "checkpoints"
    root.mkdir()
    monkeypatch.setenv("ARI_ORCHESTRATOR_LOGS", str(root))

    # Grandparent has 3 ideas; parent's idea.json is a synthetic seed
    # containing the grandparent's ideas[1] as a pinned ideas[0].
    _make_ckpt(
        root, "gp",
        ideas=[
            {"title": "GP-First", "overall_score": 0.8},
            {"title": "GP-Alt", "overall_score": 0.7},
        ],
    )
    parent_pinned = {
        "title": "GP-Alt",
        "overall_score": 0.7,
        "_pinned": True,
        "_inherited_from": {"parent_run_id": "gp", "index": 1},
    }
    parent = _make_ckpt(
        root, "parent_inherited",
        parent_run_id="gp",
        ideas=[parent_pinned, {"title": "PNew", "overall_score": 0.6}],
    )
    # Drop a top-level _inherited_from so child launcher can also inspect.
    (parent / "idea.json").write_text(json.dumps({
        "ideas": [parent_pinned, {"title": "PNew", "overall_score": 0.6}],
        "_inherited_from": {"parent_run_id": "gp", "index": 1},
    }))

    # Grandchild launches with inherit_idea_index=0 — that picks up
    # GP-Alt (the already-inherited pinned idea).
    res = _launch({
        "experiment_md": "grandchild.\n",
        "parent_run_id": "parent_inherited",
        "inherit_idea_index": 0,
        "dry_run": True,
    })
    assert res["ok"] is True, res
    child_ckpt = Path(res["checkpoint_dir"])
    seed = json.loads((child_ckpt / "idea.json").read_text())
    pinned = seed["ideas"][0]
    # The seed's title is GP-Alt (from grandparent, via parent).
    assert pinned["title"] == "GP-Alt"
    # _pinned is set because the launcher always pins the chosen idea.
    assert pinned["_pinned"] is True
    # _inherited_from points to *parent* (the immediate launch source),
    # not grandparent — provenance is one hop, callers can walk lineage
    # if they need the full chain.
    assert pinned["_inherited_from"] == {
        "parent_run_id": "parent_inherited", "index": 0
    }


def test_inherit_idea_index_requires_parent(lineage_tree, monkeypatch):
    monkeypatch.setenv("ARI_ORCHESTRATOR_LOGS", str(lineage_tree["root"]))
    res = _launch({
        "experiment_md": "x",
        "inherit_idea_index": 0,
        "dry_run": True,
    })
    assert res["ok"] is False
    assert "parent_run_id" in res["error"]


def test_inherit_idea_index_unknown_parent(lineage_tree, monkeypatch):
    monkeypatch.setenv("ARI_ORCHESTRATOR_LOGS", str(lineage_tree["root"]))
    res = _launch({
        "experiment_md": "x",
        "parent_run_id": "no_such_run",
        "inherit_idea_index": 0,
        "dry_run": True,
    })
    assert res["ok"] is False
    assert "not found" in res["error"]


def test_inherit_idea_index_out_of_range(lineage_tree, monkeypatch):
    monkeypatch.setenv("ARI_ORCHESTRATOR_LOGS", str(lineage_tree["root"]))
    res = _launch({
        "experiment_md": "x",
        "parent_run_id": "p_002",
        "inherit_idea_index": 99,
        "dry_run": True,
    })
    assert res["ok"] is False
    assert "out of range" in res["error"]


def test_inherit_idea_index_missing_parent_idea_json(tmp_path, monkeypatch):
    root = tmp_path / "checkpoints"
    root.mkdir()
    monkeypatch.setenv("ARI_ORCHESTRATOR_LOGS", str(root))
    # Parent ckpt without idea.json.
    _make_ckpt(root, "barren", ideas=None)
    res = _launch({
        "experiment_md": "x",
        "parent_run_id": "barren",
        "inherit_idea_index": 0,
        "dry_run": True,
    })
    assert res["ok"] is False
    assert "idea.json missing" in res["error"]


def test_default_launch_does_not_inherit(lineage_tree, monkeypatch):
    """Without inherit_idea_index the child must NOT see parent's plan."""
    monkeypatch.setenv("ARI_ORCHESTRATOR_LOGS", str(lineage_tree["root"]))
    res = _launch({
        "experiment_md": "Pristine child task.\n",
        "parent_run_id": "p_002",
        "dry_run": True,
    })
    assert res["ok"] is True
    child_ckpt = Path(res["checkpoint_dir"])
    exp_md = (child_ckpt / "experiment.md").read_text()
    # Default fresh: no parent idea materialised.
    assert "ParentSelected" not in exp_md
    assert "ParentAlt1" not in exp_md
    assert "AUTO-APPENDED" not in exp_md
