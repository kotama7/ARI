"""Tests for Phase 1 plan-promote helpers in ari.pipeline.

Covers:
- _extract_plan_sections recognises numeric and §-prefixed headings
- _build_auto_append_block emits the expected mode-specific structure
- _promote_plan_to_experiment_md is idempotent across repeat invocations
- _promote_plan_to_experiment_md is a no-op for mode="off" or empty ideas
- The user-supplied experiment.md prefix is preserved verbatim
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ari.pipeline import (
    _AUTO_APPEND_BEGIN,
    _AUTO_APPEND_END,
    _build_auto_append_block,
    _extract_plan_sections,
    _promote_plan_to_experiment_md,
)


_SAMPLE_PLAN = """1) Baseline and harness
- Implement an optimized CSR SpMM baseline.
- Add a k-sweep driver.

2) Implement preprocessing
- preprocessing details.

4) CTCE model construction
- Microbenchmark to measure bandwidth ceilings (Pmax/Bmax).

6) Comparisons
- Baselines: MKL, BOUND-SpMM.
- Ablations: CTCE off/on.
"""


_SAMPLE_IDEAS = {
    "ideas": [
        {
            "title": "ENVELOPE-SpMM (CTCE)",
            "description": "Conflict-Envelope Scheduling for cliff-free SpMM.",
            "experiment_plan": _SAMPLE_PLAN,
            "overall_score": 0.77,
        },
        {
            "title": "TALON-SpMM",
            "description": "Translation-Aware Loopline.",
            "experiment_plan": "stub",
            "overall_score": 0.75,
        },
        {
            "title": "STABLELINE-SpMM",
            "description": "MLP-Controlled Gather Buffering.",
            "experiment_plan": "stub",
            "overall_score": 0.75,
        },
    ],
}


# ---------------------------------------------------------------------------
# _extract_plan_sections
# ---------------------------------------------------------------------------


def test_extract_plan_sections_numeric_prefix():
    sections = _extract_plan_sections(_SAMPLE_PLAN)
    assert len(sections) == 4
    tags = [t for t, _, _ in sections]
    titles = [title for _, title, _ in sections]
    assert tags == ["§1", "§2", "§4", "§6"]
    assert titles[0].startswith("Baseline")
    assert titles[2].startswith("CTCE")
    assert titles[3].startswith("Comparisons")


def test_extract_plan_sections_section_marker_prefix():
    text = "§1) First\nbody1\n§3) Third\nbody3\n"
    sections = _extract_plan_sections(text)
    assert [t for t, _, _ in sections] == ["§1", "§3"]
    assert sections[0][2].strip() == "body1"
    assert sections[1][2].strip() == "body3"


def test_extract_plan_sections_empty():
    assert _extract_plan_sections("") == []
    assert _extract_plan_sections("   ") == []


def test_extract_plan_sections_no_headings_fallback():
    sections = _extract_plan_sections("just a paragraph without numbering")
    # Falls back to one synthetic §1 wrapping the whole text.
    assert len(sections) == 1
    assert sections[0][0] == "§1"


# Phase 6: regression for the multi-level Markdown header bug. When a plan
# uses ``### N) Title`` for the top level AND nested ``N. ...`` lists for
# sub-steps, the old regex grabbed only the inner sub-steps and silently
# dropped the actual top-level structure — so the BFTS expand prompt and
# the experiment.md auto-append both ended up showing five "ablation
# step" entries instead of the real five plan sections.
_MULTILEVEL_PLAN = """### 1) Implementation plan

**1. Baseline kernel skeleton**
- thread parallelism over rows.

**2. Persistent structural plan**
- precomputed page/set indices.

### 2) Modeling implementation
- tri-roofline calibration.

### 3) Validation plan
**Workloads**
- synthetic + SuiteSparse sample.

### 4) Key ablations to validate claims
1) Disable T_xlate while keeping read/write modeling.
2) Force a single store policy (always temporal vs always NT).
3) Disable WC contract.

### 5) Reproducibility
- seeds, build scripts, run scripts captured.
"""


def test_extract_plan_sections_prefers_markdown_headers():
    sections = _extract_plan_sections(_MULTILEVEL_PLAN)
    titles = [t for _tag, t, _body in sections]
    # Top-level Markdown headers (### N)) wins; sub-numbered lines inside
    # the ablation section are NOT promoted to top-level.
    assert "Implementation plan" in titles
    assert "Modeling implementation" in titles
    assert "Validation plan" in titles
    assert "Key ablations to validate claims" in titles
    assert "Reproducibility" in titles
    # The inner "Disable T_xlate" enumeration must NOT have replaced the
    # outer structure.
    assert all("Disable T_xlate" not in t for t in titles)
    # Five top-level sections, in order.
    assert len(sections) == 5
    tags = [t for t, _, _ in sections]
    assert tags == ["§1", "§2", "§3", "§4", "§5"]


def test_extract_plan_sections_falls_back_to_bare_numbering():
    """When a plan uses bare ``N) ...`` numbering only (no Markdown
    headers), the fallback path still works."""
    plan = (
        "1) First section.\n"
        "Some body.\n"
        "\n"
        "2) Second section.\n"
        "More body.\n"
    )
    sections = _extract_plan_sections(plan)
    titles = [t for _tag, t, _body in sections]
    assert titles == ["First section.", "Second section."]


def test_extract_plan_sections_markdown_h2_h1_also_recognised():
    plan = "## 1) From H2\n\n# 2) From H1\n"
    sections = _extract_plan_sections(plan)
    assert [t for _tag, t, _ in sections] == ["From H2", "From H1"]


# ---------------------------------------------------------------------------
# _build_auto_append_block
# ---------------------------------------------------------------------------


def test_build_block_index_only_includes_section_titles_only():
    block = _build_auto_append_block(_SAMPLE_IDEAS, mode="index_only")
    assert _AUTO_APPEND_BEGIN in block
    assert _AUTO_APPEND_END in block
    assert "ENVELOPE-SpMM (CTCE)" in block
    assert "Plan sections" in block
    # In index_only mode the section bodies must NOT appear.
    assert "Microbenchmark to measure bandwidth ceilings" not in block
    assert "MKL, BOUND-SpMM" not in block
    # But the §4 / §6 titles MUST appear (these are the bits that were
    # silently dropped before this fix).
    assert "§4" in block
    assert "§6" in block
    assert "CTCE" in block
    assert "Comparisons" in block
    # Alternatives listed.
    assert "TALON-SpMM" in block
    assert "STABLELINE-SpMM" in block


def test_build_block_full_mode_includes_bodies():
    block = _build_auto_append_block(_SAMPLE_IDEAS, mode="full")
    assert "Microbenchmark to measure bandwidth ceilings" in block
    assert "MKL, BOUND-SpMM" in block


def test_build_block_off_returns_empty():
    assert _build_auto_append_block(_SAMPLE_IDEAS, mode="off") == ""


def test_build_block_no_ideas_returns_empty():
    assert _build_auto_append_block({"ideas": []}) == ""
    assert _build_auto_append_block({}) == ""


# ---------------------------------------------------------------------------
# _promote_plan_to_experiment_md
# ---------------------------------------------------------------------------


def test_promote_appends_when_no_marker(tmp_path: Path):
    user_md = tmp_path / "experiment.md"
    user_md.write_text("Original user task statement.\nMetrics: GB/s\n")

    changed = _promote_plan_to_experiment_md(tmp_path, _SAMPLE_IDEAS)
    assert changed is True
    text = user_md.read_text()
    # User content survives at the top, verbatim.
    assert text.startswith("Original user task statement.")
    assert "Metrics: GB/s" in text
    # Auto-append marker present.
    assert _AUTO_APPEND_BEGIN in text
    assert _AUTO_APPEND_END in text
    # §4 and §6 visible in index_only mode.
    assert "§4" in text and "§6" in text


def test_promote_idempotent_when_marker_present(tmp_path: Path):
    user_md = tmp_path / "experiment.md"
    user_md.write_text("user text\n")

    assert _promote_plan_to_experiment_md(tmp_path, _SAMPLE_IDEAS) is True
    once = user_md.read_text()
    # Second call is a no-op.
    assert _promote_plan_to_experiment_md(tmp_path, _SAMPLE_IDEAS) is False
    twice = user_md.read_text()
    assert once == twice
    # Marker appears exactly once.
    assert twice.count(_AUTO_APPEND_BEGIN) == 1


def test_promote_off_mode_is_noop(tmp_path: Path):
    user_md = tmp_path / "experiment.md"
    user_md.write_text("user text\n")
    assert _promote_plan_to_experiment_md(tmp_path, _SAMPLE_IDEAS, mode="off") is False
    assert user_md.read_text() == "user text\n"


def test_promote_handles_missing_experiment_md(tmp_path: Path):
    # No prior file — function should still write the auto-append block.
    assert not (tmp_path / "experiment.md").exists()
    changed = _promote_plan_to_experiment_md(tmp_path, _SAMPLE_IDEAS)
    assert changed is True
    text = (tmp_path / "experiment.md").read_text()
    assert _AUTO_APPEND_BEGIN in text


def test_promote_handles_empty_ideas(tmp_path: Path):
    user_md = tmp_path / "experiment.md"
    user_md.write_text("user text\n")
    changed = _promote_plan_to_experiment_md(tmp_path, {"ideas": []})
    assert changed is False
    assert user_md.read_text() == "user text\n"
