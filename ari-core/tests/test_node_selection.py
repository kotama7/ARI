"""PR #A — tests T-A9..T-A15 for ari/orchestrator/node_selection.py.

Covers:
- T-A9:  is_relevant_for_synthesis 4 scenarios
- T-A10: contributes_code branches on files_changed
- T-A11: is_narrative_step branches on status
- T-A12: filter_nodes(always_include={best_id}) keeps best
- T-A13: migration_source="auto" -> contributes_code keeps node (conservative)
- T-A14: select_source_files_for_publication is deterministic and file-I/O-free
- T-A15: load_selected_sources(size_budget=N) skips when budget would overflow
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from ari.orchestrator.node_selection import (
    SourceSelection,
    build_parent_chain,
    collect_excluded,
    contributes_code,
    filter_nodes,
    is_narrative_step,
    is_relevant_for_synthesis,
    load_selected_sources,
    select_source_files_for_publication,
)


# ── builders ────────────────────────────────────────────────────────────

def _node(id_: str, *, parent: str | None = None, depth: int = 0,
          status: str = "success", has_real_data: bool = True,
          metrics: dict | None = None) -> dict:
    return {
        "id": id_,
        "parent_id": parent,
        "depth": depth,
        "status": status,
        "has_real_data": has_real_data,
        "metrics": dict(metrics or {"x": 1.0}),
    }


def _report(*, files_added: list[str] | None = None,
            files_modified: list[str] | None = None,
            succeeded: bool = True,
            migration_source: str = "fresh") -> dict:
    return {
        "schema_version": 1,
        "files_changed": {
            "added": [{"path": p, "sha256": "x"} for p in (files_added or [])],
            "modified": [{"path": p, "sha256_before": "a",
                          "sha256_after": "b"} for p in (files_modified or [])],
            "deleted": [],
            "inherited_unchanged": [],
        },
        "self_assessment": {"succeeded": succeeded, "headline": "", "concerns": []},
        "migration_source": migration_source,
    }


# ── T-A9 ────────────────────────────────────────────────────────────────

def test_is_relevant_for_synthesis_four_scenarios() -> None:
    # success + metrics — included.
    assert is_relevant_for_synthesis(
        _node("a"), _report(files_added=["x.py"])) is True
    # success - metrics, but report says succeeded=true — included.
    n_ok_no_metrics = _node("b", has_real_data=False, metrics={})
    assert is_relevant_for_synthesis(n_ok_no_metrics, _report(succeeded=True)) is True
    # report exists, no files changed, succeeded=false, no metrics — excluded.
    n_no_data = _node("c", has_real_data=False, metrics={})
    assert is_relevant_for_synthesis(n_no_data, _report(succeeded=False)) is False
    # No report, no data — excluded.
    assert is_relevant_for_synthesis(n_no_data, None) is False


# ── T-A10 ───────────────────────────────────────────────────────────────

def test_contributes_code_branches() -> None:
    assert contributes_code(_node("a"),
                            _report(files_added=["x.py"])) is True
    assert contributes_code(_node("a"),
                            _report(files_modified=["x.py"])) is True
    # Empty files_changed -> excluded (validation-style node).
    assert contributes_code(_node("a"), _report()) is False


def test_contributes_code_no_report_is_conservative() -> None:
    # Legacy fallback: no report -> include.
    assert contributes_code(_node("a"), None) is True


# ── T-A11 ───────────────────────────────────────────────────────────────

def test_is_narrative_step_status() -> None:
    assert is_narrative_step(_node("a", status="success"),
                             _report(files_added=["x.py"])) is True
    assert is_narrative_step(_node("a", status="failed"),
                             _report(files_added=["x.py"])) is False
    assert is_narrative_step(_node("a", status="abandoned"), None) is False
    # No report + success status -> include (legacy fallback).
    assert is_narrative_step(_node("a", status="success"), None) is True


# ── T-A12 ───────────────────────────────────────────────────────────────

def test_filter_nodes_always_include_keeps_best() -> None:
    # validation node has no contributing files but is the best — must survive.
    nodes = [
        _node("draft", depth=0),
        _node("improve", parent="draft", depth=1),
        _node("validation", parent="improve", depth=2),
    ]
    reports = {
        "draft":      _report(files_added=["a.py"]),
        "improve":    _report(files_modified=["a.py"]),
        "validation": _report(),  # no files_changed at all
    }
    kept = filter_nodes(nodes, reports, "for_code",
                        always_include_node_ids={"validation"})
    kept_ids = [n["id"] for n in kept]
    assert kept_ids == ["draft", "improve", "validation"]
    # And without always_include, validation is dropped:
    kept2 = filter_nodes(nodes, reports, "for_code")
    assert "validation" not in {n["id"] for n in kept2}


def test_collect_excluded_records_reason() -> None:
    nodes = [
        _node("draft", depth=0),
        _node("validation", parent="draft", depth=1),
    ]
    reports = {
        "draft":      _report(files_added=["a.py"]),
        "validation": _report(),
    }
    excluded = collect_excluded(nodes, reports, "for_code")
    assert {e["node_id"] for e in excluded} == {"validation"}
    assert excluded[0]["criterion"] == "for_code"
    assert "files_changed" in excluded[0]["reason"]


# ── T-A13 ───────────────────────────────────────────────────────────────

def test_migration_source_auto_keeps_for_code() -> None:
    """`migration_source=auto` reports must not exclude nodes for `for_code`
    even if files_changed is empty (the diff couldn't be reconstructed)."""
    auto_rep = _report(migration_source="auto")
    # Empty files_changed but still included due to conservative fallback.
    assert contributes_code(_node("a"), auto_rep) is True


# ── T-A14 ───────────────────────────────────────────────────────────────

def test_select_source_files_for_publication_is_deterministic_and_io_free(
    tmp_path: Path,
) -> None:
    nodes = [
        _node("draft",      depth=0),
        _node("improve",    parent="draft",   depth=1),
        _node("validation", parent="improve", depth=2),
    ]
    reports = {
        "draft":      _report(files_added=["main.cpp", "run_job.sh"]),
        "improve":    _report(files_modified=["main.cpp"], files_added=["util.h"]),
        "validation": _report(),  # contributes nothing
    }
    sel = select_source_files_for_publication(nodes, reports, "validation")
    assert isinstance(sel, SourceSelection)
    # Sorted by rel_path.
    rel_paths = [rel for _, rel in sel.files]
    assert rel_paths == sorted(rel_paths)
    # main.cpp deepest = improve (modified there). run_job.sh only in draft.
    sel_map = dict((rel, nid) for nid, rel in sel.files)
    assert sel_map["main.cpp"] == "improve"
    assert sel_map["run_job.sh"] == "draft"
    assert sel_map["util.h"] == "improve"
    # excluded_nodes captures validation (best) — but always_include was set,
    # so validation is NOT excluded.
    assert "validation" not in {e["node_id"] for e in sel.excluded_nodes}

    # Determinism: re-call with the same inputs yields identical SourceSelection.
    sel2 = select_source_files_for_publication(nodes, reports, "validation")
    assert sel == sel2

    # And no side-effect file was written.
    assert list(tmp_path.iterdir()) == []


def test_select_source_files_handles_missing_best() -> None:
    """If the alleged best isn't in the node list, return an empty selection."""
    nodes = [_node("draft", depth=0)]
    reports = {"draft": _report(files_added=["x.py"])}
    sel = select_source_files_for_publication(nodes, reports, "missing_id")
    assert sel.files == ()


# ── build_parent_chain ──────────────────────────────────────────────────

def test_build_parent_chain_root_to_best() -> None:
    nodes = [
        _node("a", depth=0),
        _node("b", parent="a", depth=1),
        _node("c", parent="b", depth=2),
        _node("d", parent="b", depth=2),  # sibling — not in chain.
    ]
    chain = build_parent_chain("c", nodes)
    assert [n["id"] for n in chain] == ["a", "b", "c"]


# ── T-A15 ───────────────────────────────────────────────────────────────

def test_load_selected_sources_respects_size_budget(tmp_path: Path) -> None:
    # Two nodes' work_dirs.
    work_a = tmp_path / "a"
    work_b = tmp_path / "b"
    work_a.mkdir()
    work_b.mkdir()
    (work_a / "small.txt").write_bytes(b"x" * 100)
    (work_b / "big.txt").write_bytes(b"y" * 10_000)

    selection = SourceSelection(files=(
        ("a", "small.txt"),
        ("b", "big.txt"),
    ))

    work_for = {"a": work_a, "b": work_b}
    out_full = load_selected_sources(
        selection, work_dir_for=lambda nid: work_for[nid], size_budget=None)
    assert set(out_full.keys()) == {"small.txt", "big.txt"}
    assert out_full["big.txt"]["size"] == 10_000
    assert out_full["small.txt"]["sha256"] == hashlib.sha256(b"x" * 100).hexdigest()

    # Tight budget — only the small file fits.
    out_tight = load_selected_sources(
        selection, work_dir_for=lambda nid: work_for[nid], size_budget=200)
    assert set(out_tight.keys()) == {"small.txt"}


def test_filter_nodes_warns_when_skip_rate_over_50pct(caplog) -> None:
    """FR-NS-FALLBACK-5: dropping >50% of successful nodes triggers a warning."""
    import logging
    nodes = [
        _node("a", status="success"),  # contributes nothing -> dropped (for_code)
        _node("b", status="success"),
        _node("c", status="success"),
        _node("d", status="success"),
    ]
    reports = {nid: _report() for nid in ("a", "b", "c", "d")}  # all empty files_changed
    with caplog.at_level(logging.WARNING, logger="ari.orchestrator.node_selection"):
        filter_nodes(nodes, reports, "for_code")
    assert any(">50%" in m for m in caplog.messages), caplog.messages


def test_filter_nodes_no_warn_when_skip_under_threshold(caplog) -> None:
    import logging
    nodes = [
        _node("a", status="success"),
        _node("b", status="success"),
    ]
    reports = {
        "a": _report(files_added=["x.py"]),
        "b": _report(),  # 1 of 2 dropped == 50% (not strictly >50%)
    }
    with caplog.at_level(logging.WARNING, logger="ari.orchestrator.node_selection"):
        filter_nodes(nodes, reports, "for_code")
    assert not any(">50%" in m for m in caplog.messages)


def test_load_selected_sources_skips_missing_files(tmp_path: Path) -> None:
    work_a = tmp_path / "a"
    work_a.mkdir()
    selection = SourceSelection(files=(("a", "ghost.py"),))
    out = load_selected_sources(
        selection, work_dir_for=lambda nid: work_a, size_budget=None)
    assert out == {}
