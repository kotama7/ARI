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

# ── plan-fidelity: claim_evidence_missing (F) ────────────────────────────────

def test_claim_wholly_unsupported_is_flagged():
    # The idea declares a falsifiable claim but the run emitted NONE of its
    # required_evidence -> the mechanism is claimed but never measured (the D5
    # claim_implementation骨抜き). Run-level: union over all configs.
    sd = _sd(
        {"key": "tput", "claims": [
            {"claim": "page-shaping controller helps reach-limited regimes",
             "required_evidence": ["thp_on_tput", "thp_off_tput"]}]},
        [{"config_id": "c1", "measurements": {"tput": 100.0, "k": 4.0}},
         {"config_id": "c2", "measurements": {"tput": 120.0, "k": 8.0}}],
    )
    fs = contract.check_contract(sd)
    assert [f["type"] for f in fs] == ["claim_evidence_missing"]
    assert fs[0]["missing"] == ["thp_on_tput", "thp_off_tput"]


def test_claim_with_any_evidence_present_is_not_blocked():
    # High precision: if ANY of the claim's evidence is present, the blocking check
    # stays silent — partial/weak support is the advisory review layer's job, not a
    # hard block (avoids pipeline-wide over-blocking on cross-party naming mismatch).
    sd = _sd(
        {"key": "tput", "claims": [
            {"claim": "huge pages help reach-limited regimes",
             "required_evidence": ["thp_on_tput", "thp_off_tput"]}]},
        [{"config_id": "c1", "measurements": {"thp_on_tput": 100.0}}],  # only one present
    )
    assert contract.check_contract(sd) == []


def test_claim_negative_result_is_allowed():
    # Both measurements present, outcome unfavourable (on < off): NOT blocked — the
    # gate requires the evidence to judge the claim, not that the claim be confirmed.
    sd = _sd(
        {"key": "tput", "claims": [
            {"claim": "X improves throughput", "required_evidence": ["x_on", "x_off"]}]},
        [{"config_id": "c", "measurements": {"x_on": 90.0, "x_off": 100.0}}],
    )
    assert contract.check_contract(sd) == []


def test_claim_coverage_is_domain_neutral_ml():
    # Same machinery, an ML claim with NO supporting run at all — domain-neutral.
    sd = _sd(
        {"key": "val_acc", "claims": [
            {"claim": "method M raises validation accuracy",
             "required_evidence": ["m_on_val_acc", "m_off_val_acc"]}]},
        [{"config_id": "c", "measurements": {"throughput": 1000.0}}],  # unrelated metric only
    )
    assert [f["type"] for f in contract.check_contract(sd)] == ["claim_evidence_missing"]


def test_claim_without_required_evidence_is_noop():
    sd = _sd({"key": "t", "claims": [{"claim": "vague", "required_evidence": []}]},
             [{"config_id": "c", "measurements": {"t": 1.0}}])
    assert contract.check_contract(sd) == []


def test_no_claims_is_noop():
    sd = _sd({"key": "t"}, [{"config_id": "c", "measurements": {"t": 1.0}}])
    assert contract.check_contract(sd) == []


def test_gate_blocks_claim_evidence_missing_in_warn_at_final(tmp_path):
    ckpt = tmp_path / "checkpoints" / "run2"
    ckpt.mkdir(parents=True)
    (ckpt / "tree.json").write_text(json.dumps({"nodes": []}))
    sd = _sd(
        {"key": "tput", "claims": [
            {"claim": "page-shaping controller improves width robustness",
             "required_evidence": ["psc_on_tput", "psc_off_tput"]}]},
        [{"config_id": "c", "measurements": {"tput": 100.0}}],
    )
    rep = run_hard_gate(ckpt, paper_tex="", science_data=sd, policy={"mode": "warn"},
                        phase="final", write=False)
    assert rep["should_block"] is True
    assert any(e["type"] == "claim_evidence_missing" for e in rep["errors"])


# ── check_emission: point-of-emission producer feedback ─────────────────────────
# Mirrors the gate's presence checks at emit_results time so an agent that did the
# work but DROPPED the evidence in its final emit (a real run verified its
# kernel yet emitted only throughput) is told immediately, while it can re-emit.

def test_check_emission_warns_on_dropped_correctness():
    mc = {"key": "GFLOP_per_s", "correctness_required": True,
          "claims": [{"claim": "X improves Y", "required_evidence": ["x_on", "x_off"]}]}
    warns = contract.check_emission(
        mc, {"GFlops_per_s": 40.5, "GB_per_s": 92.5}, {"GFlops_per_s": "benchmark"})
    joined = " ".join(warns)
    assert any("correctness_required" in w for w in warns)
    assert any("claims:" in w for w in warns)
    assert "x_on" in joined                              # tells the agent the names
    assert "BLOCKED" in joined                           # and the consequence


def test_check_emission_quiet_when_compliant():
    mc = {"key": "m", "correctness_required": True, "ceiling_must_be_measured": True,
          "claims": [{"claim": "c", "required_evidence": ["x_on", "x_off"]}]}
    warns = contract.check_emission(
        mc,
        {"m": 0.5, "max_abs_err": 0.0, "peak": 400.0, "x_on": 1.0},
        {"max_abs_err": "correctness", "peak": "microbench"})
    assert warns == []                                   # R1: any claim evidence suffices


def test_check_emission_noop_without_contract():
    assert contract.check_emission({}, {"m": 1.0}, {}) == []
    assert contract.check_emission(None, {"m": 1.0}, {}) == []


# ── idea-owned requirement flags (G): provenance-presence enforcement ──────────
# The idea owns the REQUIREMENT; the agent satisfies it by emitting TAGGED evidence
# (a measured ceiling, a correctness residual). Presence-only & run-level: an honest
# run is never blocked, only a placeholder / no-check 骨抜き is. No agent-declared
# name is involved, so there is no cross-party naming over-block.

def test_ceiling_must_be_measured_blocks_with_no_measured_evidence():
    sd = _sd({"key": "rnorm", "ceiling_must_be_measured": True},
             [{"config_id": "c", "measurements": {"rnorm": 0.5},
               "_provenance": {"rnorm": "declared"}}])  # nothing microbench/benchmark
    assert [f["type"] for f in contract.check_contract(sd)] == ["ceiling_unmeasured"]


def test_ceiling_must_be_measured_satisfied_by_measured_evidence():
    # honest run: a measured (microbench) ceiling operand exists -> NOT blocked.
    sd = _sd({"key": "rnorm", "ceiling_must_be_measured": True},
             [{"config_id": "c", "measurements": {"rnorm": 0.5, "peak_bw": 400.0},
               "_provenance": {"peak_bw": "microbench"}}])
    assert contract.check_contract(sd) == []


def test_correctness_required_blocks_with_no_correctness_evidence():
    sd = _sd({"key": "m", "correctness_required": True},
             [{"config_id": "c", "measurements": {"m": 0.5, "gflops": 1000.0},
               "_provenance": {"gflops": "microbench"}}])  # measured, but no correctness tag
    fs = contract.check_contract(sd)
    assert [f["type"] for f in fs] == ["correctness_uncovered"]
    assert fs[0]["config_id"] == "*"


def test_correctness_required_satisfied_by_correctness_tag():
    sd = _sd({"key": "m", "correctness_required": True},
             [{"config_id": "c", "measurements": {"m": 0.5, "max_abs_err": 1e-7},
               "_provenance": {"max_abs_err": "correctness"}}])
    assert contract.check_contract(sd) == []


def test_requirement_flags_absent_is_noop():
    sd = _sd({"key": "m"}, [{"config_id": "c", "measurements": {"m": 0.5}}])
    assert contract.check_contract(sd) == []


def test_requirement_flags_run_level_evidence_in_any_config():
    # evidence in ANY config satisfies the run-level requirement (no per-config block).
    sd = _sd({"key": "rnorm", "ceiling_must_be_measured": True, "correctness_required": True},
             [{"config_id": "c1", "measurements": {"rnorm": 0.5, "peak": 400.0},
               "_provenance": {"peak": "benchmark"}},
              {"config_id": "c2", "measurements": {"err": 1e-8},
               "_provenance": {"err": "reference"}}])
    assert contract.check_contract(sd) == []


def test_requirement_flags_domain_neutral_ml():
    # ML: idea requires correctness, the run emitted no correctness residual at all.
    sd = _sd({"key": "val_acc", "correctness_required": True},
             [{"config_id": "c", "measurements": {"val_acc": 0.9}}])  # no _provenance
    assert [f["type"] for f in contract.check_contract(sd)] == ["correctness_uncovered"]


def test_requirement_flags_tolerate_provenance_synonyms():
    # an honest run that PARAPHRASES the tag (STREAM benchmark / verified vs reference)
    # must NOT be over-blocked — recognition is root-token, not exact-set membership.
    sd = _sd({"key": "rnorm", "ceiling_must_be_measured": True, "correctness_required": True},
             [{"config_id": "c", "measurements": {"rnorm": 0.8, "peak": 400.0, "err": 1e-8},
               "_provenance": {"peak": "STREAM benchmark", "err": "verified vs reference"}}])
    assert contract.check_contract(sd) == []


def test_requirement_flags_block_unrelated_provenance():
    # a tag that is clearly NOT a measured/verification source still blocks.
    sd = _sd({"key": "rnorm", "ceiling_must_be_measured": True},
             [{"config_id": "c", "measurements": {"rnorm": 0.8, "x": 1.0},
               "_provenance": {"x": "hardcoded constant"}}])
    assert [f["type"] for f in contract.check_contract(sd)] == ["ceiling_unmeasured"]


def test_baseline_tag_is_ceiling_not_correctness():
    # "baseline" is a measured-ceiling method, NOT a correctness tag: a perf-only run
    # tagging "baseline" SATISFIES the ceiling but must STILL be correctness_uncovered.
    sd = _sd({"key": "rnorm", "ceiling_must_be_measured": True, "correctness_required": True},
             [{"config_id": "c", "measurements": {"rnorm": 0.8, "base_peak": 400.0},
               "_provenance": {"base_peak": "baseline run"}}])
    assert [f["type"] for f in contract.check_contract(sd)] == ["correctness_uncovered"]


def test_integrity_tags_do_not_discharge_correctness():
    # checkpoint / checksum / sanity_check must NOT satisfy correctness_required
    # (the bare "check" root was removed to stop the substring collision).
    for tag in ("checkpoint", "checksum", "sanity_check", "model_checkpoint", "estimated"):
        sd = _sd({"key": "m", "correctness_required": True},
                 [{"config_id": "c", "measurements": {"m": 0.5, "x": 1.0},
                   "_provenance": {"x": tag}}])
        assert [f["type"] for f in contract.check_contract(sd)] == ["correctness_uncovered"], tag


def test_gate_blocks_ceiling_unmeasured_in_warn_at_final(tmp_path):
    ckpt = tmp_path / "checkpoints" / "run3"
    ckpt.mkdir(parents=True)
    (ckpt / "tree.json").write_text(json.dumps({"nodes": []}))
    sd = _sd({"key": "rnorm", "ceiling_must_be_measured": True},
             [{"config_id": "c", "measurements": {"rnorm": 0.5}}])
    rep = run_hard_gate(ckpt, paper_tex="", science_data=sd, policy={"mode": "warn"},
                        phase="final", write=False)
    assert rep["should_block"] is True
    assert any(e["type"] == "ceiling_unmeasured" for e in rep["errors"])


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
