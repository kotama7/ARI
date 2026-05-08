"""Tests for ``categories`` normalizer.

Mirrors PaperBench's closed vocabulary in
``vendor/paperbench/.../rubric/tasks.py`` — any value outside
``VALID_FINEGRAINED_TASK_CATEGORIES`` makes ``TaskNode.__post_init__`` raise
and crashes ``grade_with_simplejudge``. The normalizer is the only thing
between LLM output and that explosion.
"""

from __future__ import annotations

import categories as C


# ── normalize_task_category ─────────────────────────────────────

def test_task_category_passthrough():
    for ok in C.VALID_TASK_CATEGORIES:
        v, why = C.normalize_task_category(ok)
        assert v == ok
        assert why is None


def test_task_category_none_passthrough():
    v, why = C.normalize_task_category(None)
    assert v is None and why is None


def test_task_category_case_fix():
    v, why = C.normalize_task_category("code development")
    assert v == "Code Development"
    assert why and "case-fix" in why


def test_task_category_unknown_falls_back():
    v, why = C.normalize_task_category("Whatever")
    assert v == "Code Development"
    assert why and "not in allow-list" in why


# ── normalize_finegrained ───────────────────────────────────────

def test_finegrained_passthrough():
    for ok in C.VALID_FINEGRAINED_TASK_CATEGORIES:
        v, why = C.normalize_finegrained(ok, "Code Development")
        assert v == ok
        assert why is None


def test_finegrained_none_passthrough():
    v, why = C.normalize_finegrained(None, "Code Development")
    assert v is None and why is None


def test_finegrained_case_fix():
    v, why = C.normalize_finegrained("method implementation", "Code Development")
    assert v == "Method Implementation"
    assert why and "case-fix" in why


def test_finegrained_known_synonyms():
    # The two captured-in-the-wild variants:
    v, why = C.normalize_finegrained("Result Visualization", "Result Analysis")
    assert v == "Logging, Analysis & Presentation"
    assert why and "synonym" in why

    v, why = C.normalize_finegrained("Result Analysis Implementation", "Result Analysis")
    assert v == "Method Implementation"
    assert why and "synonym" in why


def test_finegrained_fuzzy_substring():
    # An unseen variant that contains a known synonym key.
    v, why = C.normalize_finegrained("Plotting helpers", "Code Development")
    assert v == "Logging, Analysis & Presentation"
    assert why and ("fuzzy" in why or "synonym" in why)


def test_finegrained_unknown_uses_category_default():
    # Truly novel string with no synonym overlap → category-conditioned default.
    for tc, expected in [
        ("Code Development", "Method Implementation"),
        ("Code Execution", "Experimental Setup"),
        ("Result Analysis", "Evaluation, Metrics & Benchmarking"),
    ]:
        v, why = C.normalize_finegrained("Quantum Foo Bar Baz", tc)
        assert v == expected, f"tc={tc} expected {expected}, got {v}"
        assert why and "unrecognized" in why


def test_finegrained_unknown_no_task_category():
    v, why = C.normalize_finegrained("Quantum Foo Bar Baz", None)
    assert v == "Method Implementation"
    assert why and "unrecognized" in why


# ── normalize_rubric_node (envelope walk) ───────────────────────

def _node(tc, fg, sub=None):
    return {
        "id": "n",
        "requirements": "x",
        "weight": 1,
        "sub_tasks": sub or [],
        "task_category": tc,
        "finegrained_task_category": fg,
    }


def test_walk_replaces_known_invalid_in_tree():
    bad = _node("Result Analysis", "Result Visualization", sub=[
        _node("Code Development", "Result Analysis Implementation"),
        _node("Code Development", "Method Implementation"),  # already valid
    ])
    warns = C.normalize_rubric_node(bad)
    # Top-level got clamped
    assert bad["finegrained_task_category"] == "Logging, Analysis & Presentation"
    # First child got clamped
    assert bad["sub_tasks"][0]["finegrained_task_category"] == "Method Implementation"
    # Already-valid child untouched
    assert bad["sub_tasks"][1]["finegrained_task_category"] == "Method Implementation"
    # Two changes → two warnings
    assert len(warns) == 2


def test_walk_passthrough_when_all_valid():
    good = _node("Code Development", "Method Implementation", sub=[
        _node("Code Execution", "Experimental Setup"),
    ])
    warns = C.normalize_rubric_node(good)
    assert warns == []
    assert good["finegrained_task_category"] == "Method Implementation"


def test_walk_handles_missing_categories():
    # Internal nodes commonly lack task_category / finegrained_task_category.
    internal = {
        "id": "root",
        "requirements": "root",
        "weight": 1,
        "sub_tasks": [_node("Code Development", "Method Implementation")],
    }
    warns = C.normalize_rubric_node(internal)
    assert warns == []
    assert "task_category" not in internal
    assert "finegrained_task_category" not in internal


# ── parity with PaperBench upstream ─────────────────────────────

def test_allow_list_matches_paperbench_upstream():
    """Guard against drift if the vendored PaperBench bumps its vocab."""
    from pathlib import Path
    # PaperBench is vendored under the sibling skill (ari-skill-paper-re).
    repo_root = Path(__file__).resolve().parents[2]
    pb = (
        repo_root
        / "ari-skill-paper-re"
        / "vendor"
        / "paperbench"
        / "project"
        / "paperbench"
        / "paperbench"
        / "rubric"
        / "tasks.py"
    )
    if not pb.exists():
        import pytest
        pytest.skip(f"vendored PaperBench not present at {pb}")
    src = pb.read_text()
    for cat in C.VALID_FINEGRAINED_TASK_CATEGORIES:
        assert f'"{cat}"' in src, f"finegrained category {cat!r} drifted from PaperBench upstream"
    for cat in C.VALID_TASK_CATEGORIES:
        assert f'"{cat}"' in src, f"task_category {cat!r} drifted from PaperBench upstream"
