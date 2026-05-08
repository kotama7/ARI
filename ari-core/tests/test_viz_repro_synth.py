"""Tests for ``api_state._synth_repro_report_from_ors``.

The GUI's renderRepro() (ResultsPage.tsx) only knows the legacy
``reproducibility_report`` shape. This synthesizer projects the new
PaperBench-format ``ors_grade.json`` (+ companions) into that shape so users
who run the new ORS pipeline don't see a blank reproducibility section.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ari.viz.api_state import _synth_repro_report_from_ors


def _write(d: Path, name: str, payload: dict) -> None:
    (d / name).write_text(json.dumps(payload))


# ── empty / absent cases ────────────────────────────────────────────────

def test_returns_none_when_nothing_present(tmp_path):
    assert _synth_repro_report_from_ors(tmp_path) is None


def test_returns_none_when_grade_has_no_score_and_no_phase1(tmp_path):
    _write(tmp_path, "ors_grade.json", {"some": "thing"})
    # No phase1, no replicator, no ors_score → not enough to synthesize.
    assert _synth_repro_report_from_ors(tmp_path) is None


# ── MCP error envelope: ``{"result": "Error executing tool ..."}`` ──────

def test_mcp_error_envelope_becomes_failed_verdict(tmp_path):
    _write(
        tmp_path, "ors_grade.json",
        {"result": "Error executing tool grade_with_simplejudge: bad category"},
    )
    out = _synth_repro_report_from_ors(tmp_path)
    assert out is not None
    assert out["verdict"] == "FAILED"
    assert "bad category" in out["error"]


# ── verdict thresholds ─────────────────────────────────────────────────

def _grade(score: float, n_runs: int = 1, leaves: int = 10, passed: int = 0) -> dict:
    return {
        "ors_score": score,
        "raw_score": score,
        "judge_model": "gpt-5-mini",
        "n_runs": n_runs,
        "elapsed_sec": 12.3,
        "leaf_grades": [
            {"id": f"L{i}", "passed_runs": 1 if i < passed else 0, "n_runs": n_runs}
            for i in range(leaves)
        ],
    }


def test_high_score_is_reproduced(tmp_path):
    _write(tmp_path, "ors_grade.json", _grade(0.85, leaves=20, passed=18))
    out = _synth_repro_report_from_ors(tmp_path)
    assert out["verdict"] == "REPRODUCED"
    assert out["passed_leaves"] == 18
    assert out["total_leaves"] == 20
    assert out["ors_score"] == 0.85
    assert "18/20" in out["summary"]


def test_mid_score_is_partial(tmp_path):
    _write(tmp_path, "ors_grade.json", _grade(0.4, leaves=29, passed=9))
    out = _synth_repro_report_from_ors(tmp_path)
    assert out["verdict"] == "PARTIAL"
    assert out["passed_leaves"] == 9


def test_low_score_is_not_reproduced(tmp_path):
    _write(tmp_path, "ors_grade.json", _grade(0.05, leaves=10, passed=0))
    out = _synth_repro_report_from_ors(tmp_path)
    assert out["verdict"] == "NOT_REPRODUCED"


# ── degraded path ──────────────────────────────────────────────────────

def test_degraded_grade_shows_environment_mismatch(tmp_path):
    g = _grade(0.0, leaves=5, passed=0)
    g["degraded"] = True
    g["degraded_reason"] = "repo_dir not present: /foo"
    _write(tmp_path, "ors_grade.json", g)
    out = _synth_repro_report_from_ors(tmp_path)
    assert out["verdict"] == "ENVIRONMENT_MISMATCH"
    assert "repo_dir not present" in out["summary"]


# ── intermediate (no grade yet) ─────────────────────────────────────────

def test_phase1_skipped_no_grade_yields_pending(tmp_path):
    _write(
        tmp_path, "ors_phase1.json",
        {"executed": False, "skipped_reason": "reproduce.sh missing"},
    )
    out = _synth_repro_report_from_ors(tmp_path)
    assert out is not None
    assert out["verdict"] == "PENDING"
    assert "reproduce.sh missing" in out["summary"]


def test_replicator_only_yields_pending(tmp_path):
    _write(
        tmp_path, "ors_replicator.json",
        {"populated": True, "files": ["reproduce.sh", "main.py"], "model": "gpt-5-mini"},
    )
    out = _synth_repro_report_from_ors(tmp_path)
    assert out is not None
    assert out["verdict"] == "PENDING"
    assert "reproduce.sh" in out["summary"]


# ── companion files surface as fields ───────────────────────────────────

def test_replicator_model_and_phase1_fields_attach(tmp_path):
    _write(tmp_path, "ors_grade.json", _grade(0.4, leaves=29, passed=9))
    _write(tmp_path, "ors_phase1.json", {
        "executed": True, "exit_code": 0, "missing": ["fig_3.pdf"],
    })
    _write(tmp_path, "ors_replicator.json", {
        "populated": True, "model": "anthropic/claude-opus-4-7", "files": ["reproduce.sh"],
    })
    out = _synth_repro_report_from_ors(tmp_path)
    assert out["replicator_model"] == "anthropic/claude-opus-4-7"
    assert out["phase1_executed"] is True
    assert out["phase1_missing_artifacts"] == ["fig_3.pdf"]


# ── checkpoint summary surfaces raw ORS payloads for the rich GUI ───────

def test_checkpoint_summary_surfaces_raw_ors_payloads(tmp_path, monkeypatch):
    """The rich PaperBench-aware GUI section reads ors_grade / ors_phase1 /
    ors_replicator / ors_seed / ors_rubric_meta as raw payloads alongside
    the synthesized reproducibility_report."""
    from ari.viz import api_state
    from ari.viz import state as _st

    ckpt = tmp_path / "ckpt_xyz"
    ckpt.mkdir()
    grade = _grade(0.5, leaves=10, passed=5)
    _write(ckpt, "ors_grade.json", grade)
    _write(ckpt, "ors_phase1.json", {
        "executed": True, "exit_code": 0, "sandbox_kind": "slurm",
        "partition": "sx40", "missing": [],
    })
    _write(ckpt, "ors_replicator.json", {"populated": True, "model": "gpt-5-mini"})
    _write(ckpt, "ors_seed.json", {"populated": False, "skipped_reason": "no ref"})
    _write(ckpt, "ors_rubric.meta.json", {
        "leaves_count": 27, "model": "gpt-5-mini", "expected_artifacts": ["results.csv"],
    })
    _write(ckpt, "ors_rubric.json", {
        "version": "3",
        "reproduce_contract": {
            "script_path": "reproduce.sh", "max_runtime_sec": 600,
            "expected_artifacts": ["results.csv"],
        },
        "rubric": {
            "id": "root", "requirements": "Replicate the paper", "weight": 1,
            "sub_tasks": [
                {"id": "L1", "requirements": "leaf 1", "weight": 1, "sub_tasks": [],
                 "task_category": "Code Development"},
                {"id": "L2", "requirements": "leaf 2", "weight": 2, "sub_tasks": [],
                 "task_category": "Code Execution"},
            ],
        },
    })

    # _resolve_checkpoint_dir uses the search-base list; point one entry at
    # tmp_path so our synthetic checkpoint is discoverable.
    monkeypatch.setattr(
        api_state, "_checkpoint_search_bases", lambda: [tmp_path],
    )

    out = api_state._api_checkpoint_summary("ckpt_xyz")
    assert out["id"] == "ckpt_xyz"
    # Synthesized verdict still present (legacy GUI compat).
    assert out["reproducibility_report"]["verdict"] == "PARTIAL"
    # Raw ORS payloads surfaced for the rich GUI.
    assert out["ors_grade"]["ors_score"] == 0.5
    assert out["ors_phase1"]["partition"] == "sx40"
    assert out["ors_replicator"]["populated"] is True
    assert out["ors_seed"]["populated"] is False
    assert out["ors_rubric_meta"]["leaves_count"] == 27
    # The full TaskNode tree is surfaced so the GUI can render the grading
    # tree mirroring PaperBench's hierarchy.
    assert out["ors_rubric"]["rubric"]["id"] == "root"
    assert len(out["ors_rubric"]["rubric"]["sub_tasks"]) == 2
    assert out["ors_rubric"]["reproduce_contract"]["expected_artifacts"] == ["results.csv"]
