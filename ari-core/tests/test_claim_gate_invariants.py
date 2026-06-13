"""Tests for the concept->invariant registry (Phase 1 of the metric-correctness
contract) and its blocking integration in claim_evidence_hard_gate.

Generality is the property under test: the registry encodes ONLY universal math
(normalized<=1, probability in [0,1]) and must fire identically for HPC, ML and
theory metric names while never false-blocking legitimately-unbounded metrics
(raw throughput, speedup, percent>100, vector norms).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ari.pipeline.claim_gate import invariants as inv
from ari.pipeline.claim_gate.gate import run_hard_gate


# ── classify_concept: domain-general + conservative ──────────────────────────

@pytest.mark.parametrize("name,expected", [
    # HPC (the CSR-SpMM motivating case) — classified via the general "norm" token
    ("geo_mean_norm_roofline_throughput", "normalized"),
    ("ablated_geo_mean_norm_roofline_throughput", "normalized"),
    ("roofline_norm_throughput_gmean", "normalized"),
    # General normalization concepts (any domain)
    ("efficiency", "normalized"),
    ("hardware_utilization", "normalized"),
    ("fraction_of_peak", "normalized"),
    ("success_probability", "probability"),
    ("prob", "probability"),
    # NOT auto-bounded: ambiguous or legitimately-unbounded -> None (no false block)
    ("val_accuracy", None),          # accuracy may be reported as % -> don't assume <=1
    ("improvement_percent", None),   # percent can exceed 100
    ("ratio_pct", None),
    ("speedup", None),               # > 1 is the whole point
    ("GFLOP_per_s", None),           # raw throughput
    ("runtime_sec", None),
    ("grad_norm", None),             # ML vector norm can exceed 1
    ("l2_norm", None),
    ("weight_norm", None),
    ("spectral_norm", None),
])
def test_classify_concept_generality(name, expected):
    assert inv.classify_concept(name) == expected


def test_concept_invariants_are_pure_math():
    # normalized has an upper bound of exactly 1; probability is the unit interval.
    assert ("<=", 1.0) in inv.CONCEPT_INVARIANTS["normalized"]
    assert ("<=", 1.0) in inv.CONCEPT_INVARIANTS["probability"]
    assert (">=", 0.0) in inv.CONCEPT_INVARIANTS["probability"]


# ── scan_science_data: catch the impossible, leave the legitimate alone ──────

def _cfg(measurements):
    return {"config_id": "cfg", "measurements": measurements}


def test_scan_flags_normalized_above_one():
    sd = {"configurations": [_cfg({"roofline_norm_throughput": 3.15})]}
    v = inv.scan_science_data(sd)
    assert len(v) == 1
    assert v[0]["type"] == "invariant_violation"
    assert v[0]["concept"] == "normalized"
    assert v[0]["metric"] == "roofline_norm_throughput"


def test_scan_flags_probability_out_of_range():
    sd = {"configurations": [_cfg({"success_probability": 1.4, "failure_prob": -0.1})]}
    types = {(f["metric"]) for f in inv.scan_science_data(sd)}
    assert "success_probability" in types and "failure_prob" in types


def test_scan_passes_legitimate_metrics():
    sd = {"configurations": [_cfg({
        "GFLOP_per_s": 1498.0, "speedup": 7.6, "improvement_percent": 140.0,
        "val_accuracy": 0.93, "grad_norm": 12.0, "roofline_norm_throughput": 0.82,
    })]}
    assert inv.scan_science_data(sd) == []


def test_scan_skips_params_and_internal_keys():
    # parameters/_-prefixed must never be scanned (they are inputs / internals).
    sd = {"configurations": [{
        "config_id": "c", "parameters": {"normalized_seed": 5.0},
        "_axis_scores": {"efficiency": 9.9},
        "measurements": {"roofline_norm_throughput": 0.5},
    }]}
    assert inv.scan_science_data(sd) == []


def test_declared_bound_invariant_enforced():
    # A metric_contract may declare an explicit bound for a name the registry
    # would not classify; that bound is enforced verbatim.
    sd = {
        "metric_contract": {"invariants": [
            {"type": "bound", "expr": "custom_score", "op": "<=", "rhs": 10.0},
        ]},
        "configurations": [_cfg({"custom_score": 12.0})],
    }
    v = inv.scan_science_data(sd)
    assert len(v) == 1 and v[0]["metric"] == "custom_score"


# ── gate integration: blocks at FINAL regardless of warn/strict ──────────────

def _ckpt_with_tree(tmp_path: Path) -> Path:
    ckpt = tmp_path / "checkpoints" / "run1"
    ckpt.mkdir(parents=True)
    (ckpt / "tree.json").write_text(json.dumps({"nodes": []}))
    return ckpt


def test_gate_blocks_normalized_violation_in_warn_mode_at_final(tmp_path):
    ckpt = _ckpt_with_tree(tmp_path)
    sd = {"configurations": [_cfg({"roofline_norm_throughput_gmean": 3.15})]}
    rep = run_hard_gate(ckpt, paper_tex="", science_data=sd,
                        policy={"mode": "warn"}, phase="final", write=False)
    assert rep["metrics"]["invariant_violation_count"] == 1
    assert rep["status"] == "failed"
    # The key property: objective falsehood blocks even in warn mode.
    assert rep["should_block"] is True


def test_gate_does_not_block_violation_in_draft(tmp_path):
    ckpt = _ckpt_with_tree(tmp_path)
    sd = {"configurations": [_cfg({"roofline_norm_throughput_gmean": 3.15})]}
    rep = run_hard_gate(ckpt, paper_tex="", science_data=sd,
                        policy={"mode": "warn"}, phase="draft", write=False)
    assert rep["metrics"]["invariant_violation_count"] == 1
    assert rep["should_block"] is False  # drafts stay iterable


def test_gate_clean_configs_no_invariant_block(tmp_path):
    ckpt = _ckpt_with_tree(tmp_path)
    sd = {"configurations": [_cfg({"GFLOP_per_s": 1498.0, "roofline_norm_throughput": 0.82})]}
    rep = run_hard_gate(ckpt, paper_tex="", science_data=sd,
                        policy={"mode": "warn"}, phase="final", write=False)
    assert rep["metrics"]["invariant_violation_count"] == 0
    assert rep["should_block"] is False
