"""A promotion gate has to be computed, or it is a sentence in a signed record.

WHAT THIS FILE PINS. Every gate in every shipped registration report carries the
identical string "passed by immutable native promotion evidence", and nothing
computed any of them: ``registration_report`` took the answers and checked only
that the ids were in order. ``parity_probe`` -- the one piece of code that
establishes an instrument can tell a wrong answer from a slow one -- had no
caller outside tests. Three harnesses carry human-maintainer approvals over that
arrangement. The signatures are real; what they attest to was never measured.

The invariant is therefore not "the gates pass". It is that a gate cannot pass
without having looked, and that no gate is missing an evaluator.
"""

from __future__ import annotations

import pytest

from ari.assurance.registration import HARNESS_REGISTRATION_GATES, registration_report
from ari.assurance.registration_gates import (
    GateEvidence, REQUIRES_HUMAN, evaluate_gates, unevaluated_gates)


class _StubManifest:
    """Only the fields the gates read. A real manifest is a 46-field frozen
    contract; these tests are about whether the gates LOOK, not about it."""

    scorer_determinism = "deterministic"
    nondeterminism_declaration = "none"
    timeout_seconds = 600
    hidden_test_policy = "verifier-only"
    network_policy = "deny"
    credential_policy = "none"
    source_full_commit_sha = "b" * 40

    class _Asset:
        sha256 = "sha256:" + "a" * 64
        license = "MIT"

    dataset = oracle = driver = model = _Asset()


def _passing(manifest=None):
    manifest = manifest if manifest is not None else _StubManifest()
    probe = {
        "driver_digest": "sha256:" + "a" * 64,
        "passed": True,
        "controls": {
            "clean": {"verdict": "pass", "relative_spread": 0.01, "resolved": True},
            "negatives": [
                {"name": "slow-but-correct", "verdict": "fail", "detail": "threshold"},
                {"name": "fast-but-wrong", "verdict": "fail", "detail": "residual bound"},
            ],
        },
        "results": {
            "clean_control": {"verdict": "pass", "relative_spread": 0.01,
                              "resolved": True},
            "negative_control_slow": {"verdict": "fail", "detail": "threshold"},
            "negative_control_wrong": {"verdict": "fail", "detail": "residual bound"},
        },
    }
    return GateEvidence(manifest=manifest, parity=probe,
                        driver_digest="sha256:" + "a" * 64,
                        report_schema={"$id": "t", "properties": {"verdict": {}}},
                        stability={"runs": 3, "relative_spread": 0.02},
                        repo_commit="b" * 40)


def test_every_canonical_gate_has_an_evaluator():
    """A gate nothing computes must not be reportable at all. Fifteen of them
    were, which is how one string came to stand for fifteen checks."""
    assert unevaluated_gates() == ()


def test_no_gate_passes_on_no_evidence():
    """The failure being fixed is a gate that answers True without looking.

    One gate legitimately passes here -- infrastructure_failure_separation
    checks the evaluator's actual behaviour and needs nothing supplied. Every
    other gate must fail when handed nothing.
    """
    gates = {g.gate_id: g for g in evaluate_gates(GateEvidence())}
    passed = {gate_id for gate_id, g in gates.items() if g.passed}
    assert passed == {"infrastructure_failure_separation"}, passed


def test_a_report_minted_from_nothing_is_rejected():
    report = registration_report(
        harness_id="x", manifest_digest="sha256:" + "0" * 64,
        evidence=GateEvidence())
    assert report.decision == "rejected"


def test_registration_cannot_be_handed_pre_decided_gates():
    """There is deliberately no parameter for them."""
    with pytest.raises(TypeError):
        registration_report(harness_id="x", manifest_digest="sha256:" + "0" * 64,
                            gates=())


def test_each_gate_reports_its_own_finding():
    """One string for fifteen gates is what made the record unreadable."""
    gates = evaluate_gates(GateEvidence())
    assert len({g.detail for g in gates}) > 8
    # And the evidence digest is over WHAT WAS READ, so two gates that read
    # different things cannot share one.
    assert len({g.evidence_digest for g in gates}) == len(gates)


def test_the_probe_gates_read_the_probe():
    """The four gates the parity probe settles must actually consult it."""
    evidence = _passing()
    ok = {g.gate_id: g.passed for g in evaluate_gates(evidence)}
    for gate_id in ("reference_oracle_pass", "negative_control_fail",
                    "clean_control_pass", "official_runner_parity"):
        assert ok[gate_id], gate_id

    # Both negatives failing the SAME way is a stopwatch, not a harness.
    same = _passing()
    same.parity["controls"]["negatives"][1]["detail"] = "threshold"
    fails = {g.gate_id: g for g in evaluate_gates(same)}
    assert not fails["negative_control_fail"].passed
    assert "same reason" in fails["negative_control_fail"].detail

    # A clean control that passed without resolving certifies noise.
    noisy = _passing()
    noisy.parity["controls"]["clean"].update(resolved=False,
                                            relative_spread=1.16)
    assert not {g.gate_id: g for g in evaluate_gates(noisy)}["clean_control_pass"].passed

    # A probe run against a different driver says nothing about this one.
    other = _passing()
    other.driver_digest = "sha256:" + "c" * 64
    assert not {g.gate_id: g
                for g in evaluate_gates(other)}["official_runner_parity"].passed


def test_stability_fails_without_repeated_runs():
    """A stability gate that passes without repeating anything is the defect."""
    evidence = _passing()
    evidence.stability = {}
    gate = {g.gate_id: g for g in evaluate_gates(evidence)}["multiple_run_stability"]
    assert not gate.passed and "no repeated-run evidence" in gate.detail

    evidence.stability = {"runs": 1, "relative_spread": 0.0}
    gate = {g.gate_id: g for g in evaluate_gates(evidence)}["multiple_run_stability"]
    assert not gate.passed and "cannot show stability" in gate.detail


def test_the_human_gates_say_they_are_structural():
    """They were indistinguishable from the twelve a machine can settle."""
    gates = {g.gate_id: g for g in evaluate_gates(_passing())}
    for gate_id in REQUIRES_HUMAN:
        assert gate_id in HARNESS_REGISTRATION_GATES
        assert "the answer is the approval" in gates[gate_id].detail


def test_the_source_pin_is_compared_against_something():
    """The shipped reports pin a commit that is not HEAD and is regex-checked
    only, so the pin recorded which commit someone typed."""
    evidence = _passing()
    evidence.repo_commit = None
    gate = {g.gate_id: g
            for g in evaluate_gates(evidence)}["source_revision_digest_pin"]
    assert not gate.passed and "nothing compares" in gate.detail
