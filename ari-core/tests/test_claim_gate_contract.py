"""Tests for the declared metric_contract enforcement (Phases 2-4 harness) and
its safe expression evaluator.

Generality is the property under test: contract.py evaluates only DECLARED
expressions over measured metrics; it knows nothing about roofline/GFLOP. The
same machinery enforces an HPC roofline bound, an ML accuracy bound, or a theory
runtime ordering — only the declaration differs.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ari.pipeline.claim_gate import contract
from ari.pipeline.claim_gate.formula_eval import safe_eval
from ari.pipeline.claim_gate.gate import run_hard_gate


# ── formula_eval: general + safe ─────────────────────────────────────────────

def test_eval_arithmetic_and_lists():
    v = {"a": [100.0, 200.0, 400.0], "b": [400.0, 400.0, 400.0], "x": 6.0, "y": 2.0}
    assert safe_eval("x / y", v) == 3.0
    assert safe_eval("a / b", v) == [0.25, 0.5, 1.0]
    assert abs(safe_eval("geomean(a / b)", v) - (0.25 * 0.5 * 1.0) ** (1 / 3)) < 1e-9
    assert safe_eval("max(a)", v) == 400.0


def test_eval_compare_and_conditional():
    v = {"value": 3.15, "model_sec": 0.0265, "sec": 0.0034,
         "ebw": 3102.0, "dram": 460.0, "cache": 3500.0,
         "g": [100.0, 200.0], "c": [400.0, 400.0]}
    assert safe_eval("value <= 1", v) is False
    assert safe_eval("model_sec <= sec", v) is False        # roofline lower-bound violated
    assert safe_eval("g <= c", v) is True                   # elementwise all
    assert safe_eval("cache if ebw > dram else dram", v) == 3500.0
    assert safe_eval("0 <= value <= 1", v) is False          # chained


def test_eval_safety_and_badexpr():
    assert safe_eval("__import__('os').system('x')", {}) is None
    assert safe_eval("open('/etc/passwd')", {}) is None
    assert safe_eval("a.b", {"a": 1.0}) is None              # attribute access blocked
    assert safe_eval("unknown_name + 1", {}) is None
    assert safe_eval("1 +", {}) is None                      # syntax error -> None
    assert safe_eval("1/0", {}) is None                      # undefined -> None


# ── contract.check_contract ──────────────────────────────────────────────────

def _sd(metric_contract, configs):
    return {"metric_contract": metric_contract, "configurations": configs}


def test_no_contract_is_noop():
    assert contract.check_contract({"configurations": [{"measurements": {"x": 5.0}}]}) == []


def test_declared_invariants_flag_violation():
    sd = _sd(
        {"key": "rnorm", "invariants": ["value <= 1", "model_sec <= sec"]},
        [{"config_id": "c", "measurements": {"rnorm": 3.15, "model_sec": 0.0265, "sec": 0.0034}}],
    )
    types = [f["type"] for f in contract.check_contract(sd)]
    assert types.count("invariant_violation") == 2  # both 'value<=1' and 'model_sec<=sec'


def test_declared_invariant_passes_when_true():
    sd = _sd(
        {"key": "rnorm", "invariants": ["value <= 1", "model_sec <= sec"]},
        [{"config_id": "c", "measurements": {"rnorm": 0.82, "model_sec": 0.002, "sec": 0.0034}}],
    )
    assert contract.check_contract(sd) == []


def test_correctness_uncovered_and_failed():
    # missing residual -> uncovered
    sd1 = _sd(
        {"key": "m", "correctness": {"expr": "max_abs_err < 1e-4", "requires": ["max_abs_err"]}},
        [{"config_id": "c", "measurements": {"m": 0.5}}],
    )
    assert [f["type"] for f in contract.check_contract(sd1)] == ["correctness_uncovered"]
    # present but failing -> failed
    sd2 = _sd(
        {"key": "m", "correctness": {"expr": "max_abs_err < 1e-4", "requires": ["max_abs_err"]}},
        [{"config_id": "c", "measurements": {"m": 0.5, "max_abs_err": 0.3}}],
    )
    assert [f["type"] for f in contract.check_contract(sd2)] == ["correctness_failed"]
    # present and passing -> clean
    sd3 = _sd(
        {"key": "m", "correctness": {"expr": "max_abs_err < 1e-4", "requires": ["max_abs_err"]}},
        [{"config_id": "c", "measurements": {"m": 0.5, "max_abs_err": 2e-5}}],
    )
    assert contract.check_contract(sd3) == []


def test_provenance_placeholder_denominator():
    base = {"key": "rnorm", "required_measured": ["ceiling_bw"]}
    # placeholder/declared provenance -> blocked
    sd_bad = _sd(base, [{"config_id": "c", "measurements": {"rnorm": 0.5, "ceiling_bw": 400.0},
                         "_provenance": {"ceiling_bw": "declared"}}])
    assert [f["type"] for f in contract.check_contract(sd_bad)] == ["placeholder_denominator"]
    # measured provenance -> clean
    sd_ok = _sd(base, [{"config_id": "c", "measurements": {"rnorm": 0.5, "ceiling_bw": 460.0},
                        "_provenance": {"ceiling_bw": "microbench"}}])
    assert contract.check_contract(sd_ok) == []
    # absent provenance -> blocked
    sd_absent = _sd(base, [{"config_id": "c", "measurements": {"rnorm": 0.5, "ceiling_bw": 400.0}}])
    assert [f["type"] for f in contract.check_contract(sd_absent)] == ["placeholder_denominator"]


def test_owned_recompute_mismatch():
    # reported value must be reproducible from the declared formula
    mc = {"key": "rnorm", "formula": "geomean(gflops_byK / ceiling_byK)",
          "tolerance": {"absolute": 0.0, "relative": 0.02}}
    bad = _sd(mc, [{"config_id": "c", "measurements": {
        "rnorm": 3.15, "gflops_byK": [100.0, 200.0, 400.0], "ceiling_byK": [400.0, 400.0, 400.0]}}])
    assert [f["type"] for f in contract.check_contract(bad)] == ["recompute_mismatch"]
    ok = _sd(mc, [{"config_id": "c", "measurements": {
        "rnorm": 0.5, "gflops_byK": [100.0, 200.0, 400.0], "ceiling_byK": [400.0, 400.0, 400.0]}}])
    assert contract.check_contract(ok) == []


def test_regime_select_binds_ceiling_for_invariant():
    # the declared conditional picks WHICH ceiling 'value' is normalized against;
    # the harness only evaluates the declared conditional (no cache/DRAM inference).
    mc = {"key": "ach", "ceiling_select": "cache_bw if effective_bw > dram_peak_bw else dram_peak_bw",
          "invariants": ["ach <= ceiling"]}
    # cache-resident: effective_bw>dram -> ceiling=cache_bw=3500 -> 3102<=3500 OK
    ok = _sd(mc, [{"config_id": "c", "measurements": {
        "ach": 3102.0, "effective_bw": 3102.0, "dram_peak_bw": 460.0, "cache_bw": 3500.0}}])
    assert contract.check_contract(ok) == []
    # if regime forced DRAM ceiling, 3102<=460 would fail (proves the conditional matters)
    dram = _sd({"key": "ach", "ceiling_select": "dram_peak_bw", "invariants": ["ach <= ceiling"]},
               [{"config_id": "c", "measurements": {"ach": 3102.0, "dram_peak_bw": 460.0}}])
    assert [f["type"] for f in contract.check_contract(dram)] == ["invariant_violation"]


# ── gate integration: contract violations block at final regardless of mode ──

def test_gate_blocks_contract_violation_in_warn_at_final(tmp_path):
    ckpt = tmp_path / "checkpoints" / "run1"
    ckpt.mkdir(parents=True)
    (ckpt / "tree.json").write_text(json.dumps({"nodes": []}))
    sd = _sd(
        {"key": "rnorm", "required_measured": ["ceiling_bw"],
         "correctness": {"expr": "max_abs_err < 1e-4", "requires": ["max_abs_err"]}},
        [{"config_id": "c", "measurements": {"rnorm": 0.5, "ceiling_bw": 400.0},
          "_provenance": {"ceiling_bw": "declared"}}],
    )
    rep = run_hard_gate(ckpt, paper_tex="", science_data=sd, policy={"mode": "warn"},
                        phase="final", write=False)
    assert rep["metrics"]["contract_violation_count"] >= 2  # placeholder + correctness_uncovered
    assert rep["should_block"] is True
