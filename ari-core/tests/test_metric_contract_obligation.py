"""Tests for the domain-general producer obligation (ari.agent.metric_contract).

Generality is the property under test: the obligation text must state the SAME
requirements (verify correctness, measure the ceiling, emit provenance, declare
the contract) for any domain, WITHOUT baking in roofline/HPC vocabulary. The
agent supplies the domain-specific fulfilment.
"""
from __future__ import annotations

from ari.agent.metric_contract import build_contract_obligation


def test_no_contract_no_obligation():
    assert build_contract_obligation(None) == ""
    assert build_contract_obligation({}) == ""
    assert build_contract_obligation("nope") == ""


def test_obligation_states_all_four_requirements():
    obl = build_contract_obligation(
        {"key": "primary_norm_metric", "concept": "normalized", "invariants": ["value <= 1"]}
    )
    assert obl
    # the four obligations are present
    for token in ("CORRECTNESS", "MEASURED CEILING", "PROVENANCE", "required_measured"):
        assert token in obl, token
    # the metric key and its invariant are surfaced
    assert "primary_norm_metric" in obl
    assert "value <= 1" in obl


def test_obligation_is_domain_neutral():
    # The FRAMEWORK text must not bake in HPC/roofline vocabulary — those would
    # leak domain knowledge into a system that also runs ML / theory experiments.
    obl = build_contract_obligation(
        {"key": "norm_efficiency", "concept": "normalized", "invariants": ["value <= 1"]}
    ).lower()
    for banned in ("roofline", "gflop", "flop/s", "bandwidth", "cache", "dram", "stream", "arithmetic intensity"):
        assert banned not in obl, banned


def test_obligation_works_for_ml_concept():
    # Same machinery, an ML-flavoured metric: still domain-neutral, still states
    # the obligations — the agent would fulfil with an ML baseline, not a STREAM.
    obl = build_contract_obligation(
        {"key": "val_accuracy_fraction", "concept": "probability", "invariants": ["0 <= value", "value <= 1"]}
    )
    assert "CORRECTNESS" in obl and "val_accuracy_fraction" in obl
    assert "roofline" not in obl.lower() and "gflop" not in obl.lower()


def test_obligation_surfaces_declared_claims():
    # When the idea declared falsifiable claims, the obligation lists each claim AND
    # the measurement names the agent must emit — so a claimed mechanism cannot ship
    # unmeasured (the names are surfaced top-down for the agent to emit).
    obl = build_contract_obligation({
        "key": "tput", "concept": "bounded",
        "claims": [{"claim": "page-shaping helps reach-limited regimes",
                    "required_evidence": ["thp_on_tput", "thp_off_tput"]}],
    })
    assert "5. CLAIMS" in obl
    assert "page-shaping helps reach-limited regimes" in obl
    assert "thp_on_tput" in obl and "thp_off_tput" in obl
    assert "BLOCKED" in obl


def test_claims_obligation_is_domain_neutral():
    obl = build_contract_obligation({
        "key": "val_acc",
        "claims": [{"claim": "method beats baseline", "required_evidence": ["ours_acc", "base_acc"]}],
    }).lower()
    for banned in ("roofline", "gflop", "bandwidth", "cache", "dram", "stream"):
        assert banned not in obl, banned


def test_no_claims_means_no_claims_section():
    obl = build_contract_obligation(
        {"key": "m", "concept": "normalized", "invariants": ["value <= 1"]}
    )
    assert "5. CLAIMS" not in obl


# ── build_emission_nudge: continuation after contract warnings ────────────────

def test_emission_nudge_contains_warnings_and_steps():
    from ari.agent.metric_contract import build_emission_nudge
    n = build_emission_nudge(["correctness_required: no measurement is tagged ..."], 66)
    assert "correctness_required" in n
    assert "66" in n
    assert "emit_results again" in n          # tells the agent it can re-emit
    assert "BLOCK" in n                       # and the consequence


def test_emission_nudge_noop_cases():
    from ari.agent.metric_contract import build_emission_nudge
    assert build_emission_nudge([], 50) == ""
    assert build_emission_nudge(["w"], 0) == ""


# ── run-level claim coverage: divide claims across the tree ─────────────────────

def test_coverage_status_partitions_and_prioritizes():
    from ari.agent.metric_contract import build_coverage_status
    mc = {"claims": [
        {"claim": "A helps", "required_evidence": ["a_on", "a_off"]},
        {"claim": "B scales", "required_evidence": ["b_curve"]},
        {"claim": "C robust", "required_evidence": ["c_x", "c_y"]},
    ]}
    s = build_coverage_status(mc, {"a_on", "unrelated"})   # claim A covered (R1)
    assert "1/3 covered" in s
    assert "STILL UNCOVERED" in s
    assert "B scales" in s and "b_curve" in s              # uncovered named with evidence
    assert "A helps" not in s.split("STILL UNCOVERED")[1]  # covered one not re-listed


def test_coverage_status_all_covered_and_noop():
    from ari.agent.metric_contract import build_coverage_status
    mc = {"claims": [{"claim": "A", "required_evidence": ["a"]}]}
    assert "1/1 covered" in build_coverage_status(mc, {"a"})
    assert build_coverage_status({"claims": []}, set()) == ""
    assert build_coverage_status(None, {"a"}) == ""


def test_collect_run_measurement_names_unions_nodes(tmp_path):
    import json
    from ari.agent.metric_contract import collect_run_measurement_names
    # layout: <ws>/checkpoints/<rid> + <ws>/experiments/<rid>/node_*/results*.json
    ws = tmp_path
    ck = ws / "checkpoints" / "run1"; ck.mkdir(parents=True)
    n1 = ws / "experiments" / "run1" / "node_a"; n1.mkdir(parents=True)
    n2 = ws / "experiments" / "run1" / "node_b"; n2.mkdir(parents=True)
    (n1 / "results.json").write_text(json.dumps({"measurements": {"a_on": 1.0}}))
    (n2 / "results_seed2.json").write_text(json.dumps({"measurements": {"b_curve": 2.0}}))
    names = collect_run_measurement_names(str(ck))
    assert names == {"a_on", "b_curve"}                    # union across nodes + variants
    assert collect_run_measurement_names(str(ws / "checkpoints" / "nope")) == set()


def test_collect_run_measurement_names_excludes_failed_nodes(tmp_path):
    # independence guard: a node the evaluator judged broken (has_real_data=False)
    # must NOT mark claims "covered" for its siblings — the gate will not count its
    # evidence either, and steering optimism would suppress the independent
    # re-measurement that branch fault-containment exists to preserve.
    import json
    from ari.agent.metric_contract import collect_run_measurement_names
    ws = tmp_path
    ck = ws / "checkpoints" / "run2"; ck.mkdir(parents=True)
    good = ws / "experiments" / "run2" / "node_good"; good.mkdir(parents=True)
    bad = ws / "experiments" / "run2" / "node_bad"; bad.mkdir(parents=True)
    (good / "results.json").write_text(json.dumps({"measurements": {"a_on": 1.0}}))
    (bad / "results.json").write_text(json.dumps({"measurements": {"b_curve": 9.9}}))
    (ck / "tree.json").write_text(json.dumps({"nodes": [
        {"id": "node_good", "has_real_data": True},
        {"id": "node_bad", "has_real_data": False},   # evaluated broken
    ]}))
    assert collect_run_measurement_names(str(ck)) == {"a_on"}   # bad node excluded


def test_obligation_matches_pinned_window_marker():
    # The react context window pins run-level invariant USER messages by marker;
    # if the obligation's first line is reworded without updating the marker, the
    # obligation silently vanishes mid-node again (the real-run failure mode).
    from ari.agent.loop import _PINNED_USER_MARKERS
    obl = build_contract_obligation({"key": "m", "concept": "normalized"})
    assert any(mk in obl[:120] for mk in _PINNED_USER_MARKERS)
