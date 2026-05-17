"""Tests for the venue-conditioned PaperBench rubric template loader."""

from __future__ import annotations

from pathlib import Path

import pytest

import generator as G
import rubric_template as RT


# ── load_paperbench_rubric ─────────────────────────────────────────────────


def test_load_generic_template_succeeds():
    t = RT.load_paperbench_rubric("generic")
    assert t.id == "generic"
    assert t.mode == "agent_benchmark"
    assert t.top_level_axes == []
    assert t.prompt_overrides.system_hint == ""
    assert t.prompt_overrides.leaf_style == ""


def test_load_neurips_template():
    t = RT.load_paperbench_rubric("neurips")
    assert t.mode == "paper_audit"
    assert {a.id for a in t.top_level_axes} >= {
        "claims_supported", "experimental_setup", "code_data_available",
        "statistical_rigor", "ethics_limitations",
    }
    # NeurIPS Reproducibility Checklist mandates ethics/limitations.
    assert any("ethics" in a.id or "limitation" in a.id for a in t.top_level_axes)


def test_load_nature_template():
    t = RT.load_paperbench_rubric("nature")
    assert t.mode == "paper_audit"
    # Wet-lab axes are very different from SC/NeurIPS — verify the
    # paper_audit machinery genuinely generalizes by checking they're
    # NOT a subset of the SC/NeurIPS axis names.
    nature_ids = {a.id for a in t.top_level_axes}
    sc_ids = {a.id for a in RT.load_paperbench_rubric("sc").top_level_axes}
    neurips_ids = {a.id for a in RT.load_paperbench_rubric("neurips").top_level_axes}
    assert nature_ids & sc_ids == set()
    assert nature_ids & neurips_ids == set()
    # Materials traceability is Nature's heaviest weight.
    by_id = {a.id: a for a in t.top_level_axes}
    assert by_id["materials_traceable"].weight == 3


def test_load_sc_template_has_six_audit_axes():
    t = RT.load_paperbench_rubric("sc")
    assert t.id == "sc"
    assert t.mode == "paper_audit"
    # Step 3 of HPC PaperBench audit research plan mandates these six axes.
    expected_ids = {
        "env_reconstructable",
        "data_available",
        "execution_specified",
        "figures_consistent",
        "scaling_consistent",
        "conclusion_supported",
    }
    assert {a.id for a in t.top_level_axes} == expected_ids
    # Weight calibration from the proposal example.
    by_id = {a.id: a for a in t.top_level_axes}
    assert by_id["scaling_consistent"].weight == 3  # SC's first-class concern
    assert by_id["conclusion_supported"].weight == 1
    # System hint must surface the framing change.
    assert "paper" in t.prompt_overrides.system_hint.lower()
    assert "submission" in t.prompt_overrides.system_hint.lower()


def test_unknown_template_id_raises_with_search_paths():
    with pytest.raises(FileNotFoundError) as exc:
        RT.load_paperbench_rubric("nope_doesnt_exist")
    msg = str(exc.value)
    assert "nope_doesnt_exist" in msg
    assert "Searched" in msg


def test_invalid_id_rejected():
    with pytest.raises(ValueError):
        RT.load_paperbench_rubric("../etc/passwd")


def test_paper_audit_without_axes_rejected(tmp_path: Path, monkeypatch):
    bad = tmp_path / "bad.yaml"
    bad.write_text("id: bad\nvenue: x\ndomain: y\nmode: paper_audit\n")
    monkeypatch.setenv("ARI_PAPERBENCH_RUBRIC_DIR", str(tmp_path))
    # Re-import path resolution: DEFAULT_DIRS is evaluated at import time, so
    # call _candidate_paths directly through a refresh.
    import importlib

    importlib.reload(RT)
    with pytest.raises(ValueError, match="top_level_axes"):
        RT.load_paperbench_rubric("bad")
    # Restore default search path so later tests aren't affected.
    monkeypatch.delenv("ARI_PAPERBENCH_RUBRIC_DIR", raising=False)
    importlib.reload(RT)


# ── build_skeleton_venue_hint ──────────────────────────────────────────────


def test_generic_template_emits_empty_hint():
    t = RT.load_paperbench_rubric("generic")
    assert RT.build_skeleton_venue_hint(t) == ""


def test_sc_template_emits_axes_in_hint():
    t = RT.load_paperbench_rubric("sc")
    hint = RT.build_skeleton_venue_hint(t)
    assert "paper_audit" in hint
    # All six axis IDs must appear so the LLM uses them verbatim.
    for axis_id in (
        "env_reconstructable",
        "data_available",
        "execution_specified",
        "figures_consistent",
        "scaling_consistent",
        "conclusion_supported",
    ):
        assert axis_id in hint
    # The override block must reject the default "STRUCTURAL AXIS" guidance.
    assert "OVERRIDDEN" in hint


# ── _render_skeleton_prompt with template ─────────────────────────────────


def test_skeleton_prompt_unchanged_when_template_none():
    prompt = G._render_skeleton_prompt("paper body", 100, template=None)
    # No leftover {VENUE_HINT} placeholder, and the original prompt body is
    # intact (must still contain the legacy "STRUCTURAL AXIS" guidance).
    assert "{VENUE_HINT}" not in prompt
    assert "STRUCTURAL AXIS" in prompt


def test_skeleton_prompt_injects_sc_hint():
    t = RT.load_paperbench_rubric("sc")
    prompt = G._render_skeleton_prompt("paper body", 100, template=t)
    assert "{VENUE_HINT}" not in prompt
    assert "VENUE OVERRIDE: ACM/IEEE Supercomputing" in prompt
    assert "env_reconstructable" in prompt
    assert "scaling_consistent" in prompt


# ── generate_rubric_async preconditions ────────────────────────────────────


def test_paper_audit_template_requires_two_stage():
    import asyncio

    out = asyncio.run(
        G.generate_rubric_async(
            paper_text="dummy paper text long enough to count",
            output_path="/tmp/should_not_be_written.json",
            paperbench_rubric_id="sc",
            two_stage=False,
        )
    )
    assert "error" in out
    assert "two_stage" in out["error"]
