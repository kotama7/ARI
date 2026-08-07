"""Where a registration's evidence comes from, now that something produces it.

``registration_gates`` could compute every gate and nothing in production
produced anything for it to read -- in particular ``parity_probe``, the only
code that establishes an instrument can tell a wrong answer from a slow one,
had no caller outside tests. A gate that could be computed and never is sits a
short distance from a gate that is decorative.

What this file pins is that the evidence is PRODUCED and not accepted: the probe
runs against the driver being registered, stability comes from repeated runs,
the commit is read out of the repository, and each of those refuses rather than
substituting something weaker.
"""

from __future__ import annotations

import pytest

from ari.assurance.registration_gates import evaluate_gates
from ari.assurance.registration_run import (
    RegistrationEvidenceError, gather_evidence, probe_repeatedly,
    repository_commit, result_schema_for)


class _Manifest:
    id = "x/y"
    manifest_digest = "sha256:" + "0" * 64
    scorer_determinism = "seeded"
    nondeterminism_declaration = "timing"
    timeout_seconds = 600
    hidden_test_policy = "verifier-only"
    network_policy = "deny"
    credential_policy = "none"
    source_full_commit_sha = "b" * 40

    class _Asset:
        sha256 = "sha256:" + "a" * 64
        license = "MIT"

    dataset = oracle = driver = model = _Asset()


class _Driver:
    """Answers a probe from a script, so a test costs no compiles."""

    report_schema_version = "ari.native-perf-report/v1"

    def __init__(self, speedups, digest="sha256:" + "d" * 64):
        self.speedups, self.digest, self.calls = list(speedups), digest, 0

    def identity(self):
        return {"driver_digest": self.digest}

    def parity_probe(self, manifest):
        speedup = self.speedups[min(self.calls, len(self.speedups) - 1)]
        self.calls += 1
        return {
            "driver_digest": self.digest,
            "passed": True,
            "results": {
                "clean_control": {"verdict": "pass", "median_speedup": speedup,
                                  "relative_spread": 0.01, "resolved": True},
                "negative_control_slow": {"verdict": "fail", "detail": "threshold"},
                "negative_control_wrong": {"verdict": "fail",
                                           "detail": "residual bound"},
            },
        }


def test_a_dirty_tree_cannot_be_registered_from():
    """A pin taken while files are modified names a commit whose bytes are not
    the bytes that were measured. One shipped report pins a commit that is not
    the one it describes, and it is regex-checked only."""
    import subprocess

    from ari.assurance.registration_run import repository_root

    dirty = subprocess.run(
        ["git", "-C", str(repository_root()), "status", "--porcelain"],
        capture_output=True, text=True, timeout=60).stdout.strip()
    if not dirty:
        assert len(repository_commit()) == 40
        return
    with pytest.raises(RegistrationEvidenceError, match="modified path"):
        repository_commit()
    # And the escape hatch is explicit, so a dry run cannot be mistaken for one.
    assert len(repository_commit(allow_dirty=True)) == 40


def test_stability_needs_more_than_one_run():
    driver = _Driver([1.0])
    with pytest.raises(RegistrationEvidenceError, match="cannot show stability"):
        probe_repeatedly(driver, _Manifest(), runs=1)


def test_stability_is_measured_from_the_repeated_probes():
    """The clean control is the frozen reference scored as a candidate: it
    should read the same every run, so its spread across runs IS the answer to
    'does this instrument repeat'."""
    driver = _Driver([1.00, 1.10, 1.05])
    _probe, stability = probe_repeatedly(driver, _Manifest(), runs=3)
    assert driver.calls == 3
    assert stability["runs"] == 3
    assert stability["relative_spread"] == pytest.approx(0.10 / 1.05, rel=1e-3)


def test_the_last_probe_is_reported_not_the_best():
    """Choosing the run that passed would make the record describe a run picked
    for its answer."""
    driver = _Driver([9.0, 9.0, 2.5])
    probe, _ = probe_repeatedly(driver, _Manifest(), runs=3)
    assert probe["results"]["clean_control"]["median_speedup"] == 2.5


def test_a_driver_with_no_digest_cannot_be_registered():
    class _Anonymous(_Driver):
        def identity(self):
            return {}

    with pytest.raises(RegistrationEvidenceError, match="reports no digest"):
        gather_evidence(_Manifest(), _Anonymous([1.0]), runs=2, allow_dirty=True)


def test_the_gates_read_the_probe_this_call_produced():
    evidence = gather_evidence(_Manifest(), _Driver([1.0, 1.0]), runs=2,
                               allow_dirty=True)
    gates = {g.gate_id: g for g in evaluate_gates(evidence)}
    for gate_id in ("reference_oracle_pass", "negative_control_fail",
                    "clean_control_pass", "official_runner_parity",
                    "multiple_run_stability", "result_schema_conformance"):
        assert gates[gate_id].passed, (gate_id, gates[gate_id].detail)


def test_a_probe_that_does_not_repeat_fails_the_stability_gate():
    """On a shared node the real probe measured a clean-control spread of 0.21
    across two runs. Evidence produced there certifies noise, and says so."""
    evidence = gather_evidence(_Manifest(), _Driver([0.83, 1.04]), runs=2,
                               allow_dirty=True)
    gate = {g.gate_id: g for g in evaluate_gates(evidence)}["multiple_run_stability"]
    assert not gate.passed and "exceeds" in gate.detail


def test_both_shipped_report_types_have_a_schema():
    """There was no schema for the performance report at all, so its
    conformance gate could never have passed."""
    for version in ("ari.native-perf-report/v1",
                    "ari.native-hpc-verification-report/v1"):
        schema = result_schema_for(version)
        assert schema and schema.get("properties"), version


def test_an_unknown_report_type_is_a_finding_not_a_crash():
    assert result_schema_for("ari.invented-report/v9") is None
