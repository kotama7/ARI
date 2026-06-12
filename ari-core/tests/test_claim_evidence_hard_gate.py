"""Tests for claim_evidence_hard_gate (Story2Proposal Phase B).

Builds a synthetic checkpoint (tree.json + per-node results.json) and exercises
recompute, mismatch, operand resolution, coverage, and blocking semantics.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ari.pipeline.claim_gate import numeric
from ari.pipeline.claim_gate.gate import run_hard_gate
from ari.pipeline.claim_gate.policy import load_policy


def _make_ckpt(tmp_path: Path) -> Path:
    ws = tmp_path
    ckpt = ws / "checkpoints" / "run1"
    ckpt.mkdir(parents=True)
    tree = {"nodes": [
        {"id": "n_base", "has_real_data": True, "metrics": {"GFlops": 100.0}},
        {"id": "n_prop", "has_real_data": True, "metrics": {"GFlops": 150.0}},
    ]}
    (ckpt / "tree.json").write_text(json.dumps(tree))
    for nid, val in (("n_base", 100.0), ("n_prop", 150.0)):
        d = ws / "experiments" / "run1" / nid
        d.mkdir(parents=True)
        (d / "results.json").write_text(json.dumps({"measurements": {"GFlops": val}}))
    return ckpt


SCIENCE = {
    "claims": [
        {"id": "C1", "text": "absolute", "section": "results", "status": "draft",
         "supported_by": {"nodes": ["n_prop"], "results": [{"node_id": "n_prop", "metric_path": "measurements.GFlops"}], "figures": [], "artifacts": []},
         "numeric_assertions": [{"id": "NC1", "metric": "GFlops", "value": 150.0, "unit": "",
                                 "formula": "identity", "operands": {"value": {"node_id": "n_prop", "metric_path": "measurements.GFlops"}},
                                 "tolerance": {"absolute": 0.0, "relative": 0.02}}]},
        {"id": "C2", "text": "comparison", "section": "results", "status": "draft",
         "supported_by": {"nodes": ["n_prop", "n_base"], "results": [], "figures": [], "artifacts": []},
         "numeric_assertions": [{"id": "NC2", "metric": "GFlops", "value": 50.0, "unit": "%",
                                 "formula": "relative_increase_percent",
                                 "operands": {"baseline": {"node_id": "n_base", "metric_path": "measurements.GFlops"},
                                              "proposed": {"node_id": "n_prop", "metric_path": "measurements.GFlops"}},
                                 "tolerance": {"absolute": 0.0, "relative": 0.02}}]},
    ],
    "numeric_assertions": [
        {"id": "NC1", "claim_id": "C1", "metric": "GFlops", "value": 150.0, "formula": "identity",
         "operands": {"value": {"node_id": "n_prop", "metric_path": "measurements.GFlops"}},
         "tolerance": {"absolute": 0.0, "relative": 0.02}},
        {"id": "NC2", "claim_id": "C2", "metric": "GFlops", "value": 50.0, "formula": "relative_increase_percent",
         "operands": {"baseline": {"node_id": "n_base", "metric_path": "measurements.GFlops"},
                      "proposed": {"node_id": "n_prop", "metric_path": "measurements.GFlops"}},
         "tolerance": {"absolute": 0.0, "relative": 0.02}},
    ],
}


def _links(nc1_value: float, nc2_value: float) -> dict:
    return {
        "paper_claim_links": [
            {"claim_id": "C1", "numeric_id": "NC1", "section": "results", "anchor": "CLAIM:C1:NC1",
             "span_hash": "h", "line_range": [10, 10], "figures": [], "resolved": True},
            {"claim_id": "C2", "numeric_id": "NC2", "section": "results", "anchor": "CLAIM:C2:NC2",
             "span_hash": "h", "line_range": [12, 12], "figures": [], "resolved": True},
        ],
        "numeric_mentions": [
            {"value": nc1_value, "unit": "", "type": "result_claim", "requires_assertion": True, "section": "results", "line": 10},
            {"value": nc2_value, "unit": "%", "type": "result_claim", "requires_assertion": True, "section": "results", "line": 12},
        ],
        "figure_refs": [], "unresolved_anchors": [], "uncovered_numeric_candidates": [],
    }


def test_passing_gate(tmp_path):
    ckpt = _make_ckpt(tmp_path)
    rep = run_hard_gate(ckpt, paper_tex="", science_data=SCIENCE,
                        paper_claim_links=_links(150.0, 50.0),
                        policy={"mode": "strict"}, phase="final")
    assert rep["errors"] == []
    assert rep["status"] in ("passed", "warn")
    assert rep["should_block"] is False
    assert rep["metrics"]["numeric_claim_reproducible_rate"] == 1.0
    assert rep["metrics"]["execution_grounded_claim_rate"] == 1.0


def test_numeric_mismatch_blocks_in_strict_final(tmp_path):
    ckpt = _make_ckpt(tmp_path)
    rep = run_hard_gate(ckpt, paper_tex="", science_data=SCIENCE,
                        paper_claim_links=_links(150.0, 99.0),  # NC2 paper says 99, recompute 50
                        policy={"mode": "strict"}, phase="final")
    types = [e["type"] for e in rep["errors"]]
    assert "numeric_mismatch" in types
    assert rep["should_block"] is True
    assert rep["metrics"]["numeric_claim_mismatch_count"] == 1


def test_numeric_mismatch_warn_does_not_block(tmp_path):
    ckpt = _make_ckpt(tmp_path)
    rep = run_hard_gate(ckpt, paper_tex="", science_data=SCIENCE,
                        paper_claim_links=_links(150.0, 99.0),
                        policy={"mode": "warn"}, phase="final")
    assert any(e["type"] == "numeric_mismatch" for e in rep["errors"])
    assert rep["should_block"] is False  # warn mode never blocks


def test_draft_phase_never_blocks(tmp_path):
    ckpt = _make_ckpt(tmp_path)
    rep = run_hard_gate(ckpt, paper_tex="", science_data=SCIENCE,
                        paper_claim_links=_links(150.0, 99.0),
                        policy={"mode": "strict"}, phase="draft")
    assert any(e["type"] == "numeric_mismatch" for e in rep["errors"])
    assert rep["should_block"] is False  # draft is informational


def test_operand_unresolved(tmp_path):
    ckpt = _make_ckpt(tmp_path)
    sd = json.loads(json.dumps(SCIENCE))
    sd["numeric_assertions"][0]["operands"]["value"]["node_id"] = "ghost"
    rep = run_hard_gate(ckpt, paper_tex="", science_data=sd,
                        paper_claim_links=_links(150.0, 50.0),
                        policy={"mode": "strict"}, phase="final")
    assert any(e["type"] == "operand_unresolved" for e in rep["errors"])
    assert rep["should_block"] is True


def test_missing_evidence_unknown_node(tmp_path):
    ckpt = _make_ckpt(tmp_path)
    sd = json.loads(json.dumps(SCIENCE))
    sd["claims"][0]["supported_by"]["nodes"] = ["ghost_node"]
    rep = run_hard_gate(ckpt, paper_tex="", science_data=sd,
                        paper_claim_links=_links(150.0, 50.0),
                        policy={"mode": "strict"}, phase="final")
    assert any(e["type"] == "missing_evidence" for e in rep["errors"])


def test_uncovered_numeric_strict_blocks_warn_warns(tmp_path):
    ckpt = _make_ckpt(tmp_path)
    # An unanchored result_claim number in the abstract.
    tex = "\\begin{abstract}\nWe report a speedup of 31\\%.\n\\end{abstract}\n"
    empty_links = {"paper_claim_links": [], "numeric_mentions": None, "figure_refs": [],
                   "unresolved_anchors": [], "uncovered_numeric_candidates": []}
    strict = run_hard_gate(ckpt, paper_tex=tex, science_data={"claims": [], "numeric_assertions": []},
                           paper_claim_links=empty_links, policy={"mode": "strict"}, phase="final")
    assert any(e["type"] == "uncovered_numeric" for e in strict["errors"])
    assert strict["should_block"] is True

    warn = run_hard_gate(ckpt, paper_tex=tex, science_data={"claims": [], "numeric_assertions": []},
                         paper_claim_links=empty_links, policy={"mode": "warn"}, phase="final")
    assert any(w["type"] == "uncovered_numeric" for w in warn["warnings"])
    assert warn["should_block"] is False


def test_report_written_to_evaluation_dir(tmp_path):
    ckpt = _make_ckpt(tmp_path)
    run_hard_gate(ckpt, paper_tex="", science_data=SCIENCE, paper_claim_links=_links(150.0, 50.0),
                  policy={"mode": "warn"}, phase="draft")
    assert (ckpt / "evaluation" / "claim_evidence_hard_gate_draft.json").is_file()


def test_env_mismatch_warning(tmp_path):
    ckpt = _make_ckpt(tmp_path)
    # give the two nodes different cpu models via node_report.json
    for nid, model in (("n_base", "cpuX"), ("n_prop", "cpuY")):
        d = ckpt.parent.parent / "experiments" / "run1" / nid
        (d / "node_report.json").write_text(json.dumps({"executor": "slurm", "cpu_info": {"model": model}}))
    rep = run_hard_gate(ckpt, paper_tex="", science_data=SCIENCE, paper_claim_links=_links(150.0, 50.0),
                        policy={"mode": "warn"}, phase="final")
    assert any(w["type"] == "environment_mismatch" for w in rep["warnings"])


def test_env_mismatch_severity_is_intent_driven(tmp_path, monkeypatch):
    """environment_mismatch is a WARNING under scope=any (cross-arch studies) and
    a BLOCKING error only under scope=same_environment (single-arch studies)."""
    monkeypatch.delenv("ARI_COMPARISON_SCOPE", raising=False)
    monkeypatch.delenv("ARI_CLAIM_GATE_MODE", raising=False)
    ckpt = _make_ckpt(tmp_path)
    for nid, model in (("n_base", "cpuX"), ("n_prop", "cpuY")):
        d = ckpt.parent.parent / "experiments" / "run1" / nid
        (d / "node_report.json").write_text(json.dumps({"executor": "slurm", "cpu_info": {"model": model}}))

    # same_environment intent => blocking error
    strict = run_hard_gate(ckpt, paper_tex="", science_data=SCIENCE, paper_claim_links=_links(150.0, 50.0),
                           policy={"mode": "strict", "comparison_scope": "same_environment"}, phase="final")
    assert strict["comparison_scope"] == "same_environment"
    assert any(e["type"] == "environment_mismatch" for e in strict["errors"])
    assert strict["should_block"] is True

    # any intent (default) => warning, never blocks on env mismatch
    anyscope = run_hard_gate(ckpt, paper_tex="", science_data=SCIENCE, paper_claim_links=_links(150.0, 50.0),
                             policy={"mode": "strict", "comparison_scope": "any"}, phase="final")
    assert any(w["type"] == "environment_mismatch" for w in anyscope["warnings"])
    assert not any(e["type"] == "environment_mismatch" for e in anyscope["errors"])
    assert anyscope["should_block"] is False


def test_policy_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("ARI_CLAIM_GATE_MODE", "strict")
    pol = load_policy(tmp_path, None)
    assert pol["mode"] == "strict"
    monkeypatch.setenv("ARI_CLAIM_GATE_MODE", "off")
    assert load_policy(tmp_path, None)["mode"] == "off"


def _links_with_writer_assertion(reported: float):
    """paper_claim_links carrying a writer-declared NC9 (comparison) + its reported value."""
    return {
        "paper_claim_links": [
            {"claim_id": "C9", "numeric_id": "NC9", "section": "results", "anchor": "CLAIM:C9:NC9",
             "span_hash": "h", "line_range": [10, 10], "figures": [], "resolved": True},
        ],
        "numeric_mentions": [
            {"value": reported, "unit": "%", "type": "result_claim", "requires_assertion": True,
             "section": "results", "line": 10},
        ],
        "writer_assertions": [
            {"id": "NC9", "claim_id": "C9", "metric": "GFlops", "formula": "relative_increase_percent",
             "operands": {"baseline": {"node_id": "n_base", "metric_path": "GFlops"},
                          "proposed": {"node_id": "n_prop", "metric_path": "GFlops"}},
             "line": 10, "source": "writer_declared"},
        ],
        "figure_refs": [], "unresolved_anchors": [], "uncovered_numeric_candidates": [],
    }


def test_writer_declared_assertion_verified_forward(tmp_path):
    """A correct writer-declared assertion (no science_data claim) is verified forward."""
    ckpt = _make_ckpt(tmp_path)  # n_base GFlops=100, n_prop GFlops=150 -> +50%
    rep = run_hard_gate(ckpt, paper_tex="", science_data={"claims": [], "numeric_assertions": []},
                        paper_claim_links=_links_with_writer_assertion(50.0),
                        policy={"mode": "strict"}, phase="final")
    assert rep["metrics"]["writer_declared_assertions"] == 1
    assert rep["metrics"]["numeric_reproducible"] == 1
    assert not any(e["type"] == "numeric_mismatch" for e in rep["errors"])


def test_writer_declared_assertion_wrong_is_mismatch(tmp_path):
    """A wrong writer-declared number is caught forward (no laundering)."""
    ckpt = _make_ckpt(tmp_path)
    rep = run_hard_gate(ckpt, paper_tex="", science_data={"claims": [], "numeric_assertions": []},
                        paper_claim_links=_links_with_writer_assertion(99.0),  # recompute=50, reported=99
                        policy={"mode": "strict"}, phase="final")
    assert any(e["type"] == "numeric_mismatch" for e in rep["errors"])
    assert rep["should_block"] is True


def test_coverage_by_value_restatement(tmp_path):
    """A verified value (150 GFlops in results) restated in the abstract is covered
    without re-anchoring; an ungrounded number and a unit-mismatched value are not."""
    ckpt = _make_ckpt(tmp_path)
    na = {"id": "NC1", "claim_id": "C1", "metric": "GFlops", "unit": "", "formula": "identity",
          "operands": {"value": {"node_id": "n_prop", "metric_path": "measurements.GFlops"}}}
    sd = {"claims": [{"id": "C1", "text": "x", "section": "results", "numeric_assertions": [na]}],
          "numeric_assertions": [na]}
    pcl = {
        "paper_claim_links": [{"claim_id": "C1", "numeric_id": "NC1", "section": "results",
                               "anchor": "CLAIM:C1:NC1", "span_hash": "h", "line_range": [5, 5],
                               "figures": [], "resolved": True}],
        "numeric_mentions": [
            {"value": 150.0, "unit": "", "type": "result_claim", "requires_assertion": True, "section": "results", "line": 5},
            {"value": 150.0, "unit": "", "type": "result_claim", "requires_assertion": True, "section": "abstract", "line": 1},  # restatement
            {"value": 99.0, "unit": "", "type": "result_claim", "requires_assertion": True, "section": "abstract", "line": 2},   # ungrounded
            {"value": 150.0, "unit": "%", "type": "result_claim", "requires_assertion": True, "section": "abstract", "line": 3}, # unit mismatch
        ],
        "writer_assertions": [], "figure_refs": [], "unresolved_anchors": [], "uncovered_numeric_candidates": [],
    }
    rep = run_hard_gate(ckpt, paper_tex="", science_data=sd, paper_claim_links=pcl,
                        policy={"mode": "strict"}, phase="final", write=False)
    err_lines = {e.get("line") for e in rep["errors"] if e["type"] == "uncovered_numeric"}
    assert 1 not in err_lines   # restatement of a verified value -> covered (no laundering: exact value+unit)
    assert 2 in err_lines       # genuinely ungrounded number -> still flagged
    assert 3 in err_lines       # value matches but unit differs (% vs absolute) -> not covered


def test_coverage_credits_resolved_operand_value(tmp_path):
    """A baseline value cited in prose (used only as a comparison operand) is covered
    by its resolved operand value (from executed data) without its own anchor."""
    ckpt = _make_ckpt(tmp_path)
    na = {"id": "NC2", "claim_id": "C2", "metric": "GFlops", "unit": "%", "formula": "relative_increase_percent",
          "operands": {"baseline": {"node_id": "n_base", "metric_path": "measurements.GFlops"},
                       "proposed": {"node_id": "n_prop", "metric_path": "measurements.GFlops"}}}
    sd = {"claims": [{"id": "C2", "text": "x", "section": "results", "numeric_assertions": [na]}],
          "numeric_assertions": [na]}
    pcl = {
        "paper_claim_links": [{"claim_id": "C2", "numeric_id": "NC2", "section": "results",
                               "anchor": "CLAIM:C2:NC2", "span_hash": "h", "line_range": [5, 5],
                               "figures": [], "resolved": True}],
        "numeric_mentions": [
            {"value": 50.0, "unit": "%", "type": "result_claim", "requires_assertion": True, "section": "results", "line": 5},
            {"value": 100.0, "unit": "", "type": "result_claim", "requires_assertion": True, "section": "results", "line": 6},  # baseline operand cited in prose
        ],
        "writer_assertions": [], "figure_refs": [], "unresolved_anchors": [], "uncovered_numeric_candidates": [],
    }
    rep = run_hard_gate(ckpt, paper_tex="", science_data=sd, paper_claim_links=pcl,
                        policy={"mode": "strict"}, phase="final", write=False)
    err_lines = {e.get("line") for e in rep["errors"] if e["type"] == "uncovered_numeric"}
    assert 6 not in err_lines   # baseline (100) = resolved operand of a verified claim -> covered


def test_numeric_within_tolerance():
    assert numeric.within_tolerance(50.4, 50.0, {"absolute": 0.0, "relative": 0.02}) is True
    assert numeric.within_tolerance(99.0, 50.0, {"absolute": 0.0, "relative": 0.02}) is False


# --- scientific-notation extraction (mirrors claim_links; false-mismatch fix) ---

def test_latex_mentions_scientific_notation():
    from ari.pipeline.claim_gate.latex import extract_numeric_mentions
    tex = r"The FP64 maximum absolute error is \(4.440892098500626\times 10^{-16}\)."
    ms = extract_numeric_mentions(tex)
    sci = [m for m in ms if m["value"] < 1e-10]
    assert len(sci) == 1 and abs(sci[0]["value"] - 4.440892098500626e-16) < 1e-22
    assert sorted(m["value"] for m in ms) == [sci[0]["value"]]   # no junk 10/16 split
    assert sci[0]["type"] == "result_claim"


def test_latex_mentions_e_notation_and_speedup_x():
    from ari.pipeline.claim_gate.latex import extract_numeric_mentions
    ms = extract_numeric_mentions("tolerance 1.2e-6 holds")
    assert any(abs(m["value"] - 1.2e-6) < 1e-12 for m in ms)
    ms2 = extract_numeric_mentions(r"a \(4.18\times\) speedup over 10 runs")
    assert sorted(m["value"] for m in ms2) == [4.18, 10.0]
