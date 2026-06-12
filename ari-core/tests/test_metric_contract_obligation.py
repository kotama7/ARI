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


def test_coverage_status_majority_rule_for_steering():
    # P2b: steering "covered" needs >= half the names (the gate's R1 any-name rule
    # is unchanged). One accidental shared name out of four must NOT stop every
    # node from ever running the claim's experiment.
    from ari.agent.metric_contract import build_coverage_status
    mc = {"claims": [
        {"claim": "M2 lowers translation misses",
         "required_evidence": ["tlb_misses_m2", "tlb_misses_m0", "tput_m2", "tput_m0"]}]}
    assert "0/1 covered" in build_coverage_status(mc, {"tput_m0"})            # 1/4 -> uncovered
    assert "1/1 covered" in build_coverage_status(mc, {"tput_m0", "tput_m2"})  # 2/4 -> covered


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


def test_expand_coverage_hint_lists_uncovered_for_scheduler(tmp_path):
    # P3: the expansion-selection goal gains the run-level coverage block so the
    # scheduler can prefer nodes that evidence STILL-UNCOVERED claims.
    import json
    from ari.agent.metric_contract import build_expand_coverage_hint
    ws = tmp_path
    ck = ws / "checkpoints" / "run3"; ck.mkdir(parents=True)
    (ck / "metric_contract.json").write_text(json.dumps({"key": "t", "claims": [
        {"claim": "A helps", "required_evidence": ["a_with_mech", "a_without_mech"]}]}))
    h = build_expand_coverage_hint(str(ck))
    assert "claim coverage" in h and "STILL UNCOVERED" in h
    assert "a_with_mech" in h
    # no contract / no claims -> empty (legacy behaviour untouched)
    ck2 = ws / "checkpoints" / "run4"; ck2.mkdir(parents=True)
    assert build_expand_coverage_hint(str(ck2)) == ""
    (ck2 / "metric_contract.json").write_text(json.dumps({"key": "t", "claims": []}))
    assert build_expand_coverage_hint(str(ck2)) == ""


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


# --- lineage chaining (parent-selection hint + child inherited-data note) ---

def _lineage_ckpt(tmp_path, per_node, claims, has_real=None):
    """Build checkpoint + experiments layout: per_node = {node: {name: val}}."""
    import json
    ws = tmp_path / "ws"
    ckpt = ws / "checkpoints" / "run1"
    exp = ws / "experiments" / "run1"
    ckpt.mkdir(parents=True)
    (ckpt / "metric_contract.json").write_text(json.dumps({"key": "m", "claims": claims}))
    nodes = []
    for nid, meas in per_node.items():
        d = exp / nid
        d.mkdir(parents=True)
        (d / "results.json").write_text(json.dumps({"measurements": meas}))
        nodes.append({"id": nid,
                      "has_real_data": True if has_real is None else has_real.get(nid, True)})
    (ckpt / "tree.json").write_text(json.dumps({"nodes": nodes}))
    return ckpt


def test_collect_node_measurement_names_attributes_per_node(tmp_path):
    from ari.agent.metric_contract import (collect_node_measurement_names,
                                           collect_run_measurement_names)
    ckpt = _lineage_ckpt(tmp_path,
                         {"node_a": {"alpha_t": 1, "beta_t": 2}, "node_b": {"gamma_t": 3}},
                         claims=[{"claim": "x", "required_evidence": ["alpha_t"]}])
    per = collect_node_measurement_names(str(ckpt))
    assert per["node_a"] == {"alpha_t", "beta_t"} and per["node_b"] == {"gamma_t"}
    # run-level union unchanged (regression guard for the refactor)
    assert collect_run_measurement_names(str(ckpt)) == {"alpha_t", "beta_t", "gamma_t"}


def test_expand_hint_names_data_richest_node_for_uncovered_claims(tmp_path):
    from ari.agent.metric_contract import build_expand_coverage_hint
    claims = [
        {"claim": "probe basics", "required_evidence": ["alpha_t", "beta_t"]},
        {"claim": "fit parameters from existing probes",
         "required_evidence": ["theta_fit_value", "theta_fit_residual"]},
    ]
    ckpt = _lineage_ckpt(tmp_path,
                         {"node_rich": {"alpha_t": 1, "beta_t": 2},
                          "node_poor": {"unrelated": 9}}, claims)
    hint = build_expand_coverage_hint(str(ckpt))
    assert "STILL UNCOVERED" in hint                  # fit claim lacks evidence
    assert "LINEAGE" in hint and "node_rich" in hint  # parent-selection signal
    assert "INHERIT" in hint


def test_expand_hint_no_lineage_when_all_covered_or_no_holdings(tmp_path):
    from ari.agent.metric_contract import build_expand_coverage_hint
    claims = [{"claim": "probe", "required_evidence": ["alpha_t", "beta_t"]}]
    ckpt = _lineage_ckpt(tmp_path, {"node_a": {"alpha_t": 1, "beta_t": 2}}, claims)
    hint = build_expand_coverage_hint(str(ckpt))
    assert "LINEAGE" not in hint                      # nothing uncovered -> no signal


def test_inherited_data_note_lists_files_and_contract_names(tmp_path):
    import json
    from ari.agent.metric_contract import build_inherited_data_note
    wd = tmp_path / "wd"; wd.mkdir()
    (wd / "results.json").write_text(json.dumps(
        {"measurements": {"alpha_t": 1.0, "beta_t": 2.0, "own_extra": 3.0}}))
    contract = {"claims": [{"claim": "c", "required_evidence": ["alpha_t", "theta_fit_value"]}]}
    note = build_inherited_data_note(contract, str(wd))
    assert "INHERITED DATA" in note and "results.json" in note
    assert "alpha_t" in note                          # contract hit listed
    assert "do NOT re-run" in note


def test_inherited_data_note_silent_without_data_or_claims(tmp_path):
    from ari.agent.metric_contract import build_inherited_data_note
    wd = tmp_path / "empty"; wd.mkdir()
    assert build_inherited_data_note({"claims": [{"claim": "c"}]}, str(wd)) == ""
    assert build_inherited_data_note({}, str(wd)) == ""
    assert build_inherited_data_note({"claims": [{"claim": "c"}]}, str(tmp_path / "nope")) == ""
