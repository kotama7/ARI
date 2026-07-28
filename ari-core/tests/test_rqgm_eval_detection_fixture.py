"""RQGM Task 13 — Tier-1 fixture detection (docs/plans/ari_rqgm/13 §5.3/§9).

The fixture-mechanism injections are caught by the EXISTING deterministic
detectors, run directly against the committed checkpoint fragments:

- injections 1/2 (metric gaming, overclaim) by the claim gate via
  ``gate_detection_report`` (``run_hard_gate(write=False)``);
- injection 7 (contaminated prompt) by Task 07's static + constitutional
  candidate validation;
- injection 9 (clean-room violation) by Task 08's request schema mirror and
  the kernel's ``validate_clean_room_bundle`` (CK-CLN-001, invariant 14);
- injection 10 (stale record leakage) by the kernel's
  ``validate_selective_erasure`` (CK-ERA-003/004) and metric 9;
- the control fixture passes the gate with zero errors (false-reject floor).

No LLM, no network; detectors are the same code paths production hits (P2).
"""

from __future__ import annotations

import json

import pytest

from ari.rqgm.evaluation.injection import (
    fixtures_root,
    gate_detection_report,
)
from ari.rqgm.evaluation.metrics import frontier_contamination
from ari.rqgm.kernel import ConstitutionalKernel

FIXTURES = fixtures_root()


@pytest.fixture(autouse=True)
def _no_env_overrides(monkeypatch):
    # The gate honors ARI_CLAIM_GATE_MODE / ARI_COMPARISON_SCOPE; the
    # fixtures pin policy via claim_gate_policy.json instead.
    monkeypatch.delenv("ARI_CLAIM_GATE_MODE", raising=False)
    monkeypatch.delenv("ARI_COMPARISON_SCOPE", raising=False)
    monkeypatch.delenv("ARI_CHECKPOINT_DIR", raising=False)


# ── injection 1: metric gaming ───────────────────────────────────────────────


def test_injection1_metric_gaming_flagged_by_gate():
    report = gate_detection_report(FIXTURES / "metric_gaming")
    types = {e["type"] for e in report["errors"]}
    # The gamed speedup does not reproduce from executed data ...
    assert "numeric_mismatch" in types
    # ... and baseline/proposed ran on different machines.
    assert "environment_mismatch" in types
    assert report["should_block"] is True
    mismatch = next(e for e in report["errors"]
                    if e["type"] == "numeric_mismatch")
    assert mismatch["numeric_id"] == "NCG1"
    assert mismatch["reported"] == 120.0
    assert mismatch["recomputed"] == 50.0     # the honest recompute


# ── injection 2: overclaim ───────────────────────────────────────────────────


def test_injection2_overclaim_flagged_by_gate():
    report = gate_detection_report(FIXTURES / "overclaim")
    types = {e["type"] for e in report["errors"]}
    assert "missing_evidence" in types        # supported claim, no evidence
    assert "uncovered_numeric" in types       # 3.7x with no % CLAIM anchor
    assert report["should_block"] is True
    claim_ids = {e.get("claim_id") for e in report["errors"]}
    assert {"C_OVER", "C_GHOST"} <= claim_ids


# ── injection 7: contaminated prompt candidate ───────────────────────────────


def test_injection7_candidate_rejected_by_task07_validation():
    from ari.rqgm.prompt_evolution import (
        constitutional_validation_failures,
        static_validation_failures,
    )
    from ari.rqgm.prompt_records import candidate_from_dict

    payload_dir = FIXTURES / "contaminated_prompt"
    candidate = candidate_from_dict(
        json.loads((payload_dir / "prompt_candidate.json").read_text())
    )
    template = (payload_dir / "candidate_template.txt").read_text()

    static = static_validation_failures(candidate, template)
    assert any("forbidden placeholders" in f for f in static)
    assert any("retired_prompt_text" in f for f in static)

    constitutional = constitutional_validation_failures(candidate)
    assert any("missing mandatory constraint" in f for f in constitutional)
    assert any("Do not override fixed verifier failures" in f
               for f in constitutional)


# ── injection 9: clean-room violation ────────────────────────────────────────


def test_injection9_request_blocked_before_assembly():
    from ari.rqgm.clean_room import request_from_dict, \
        request_schema_failures

    payload_dir = FIXTURES / "clean_room_violation"
    request_dict = json.loads(
        (payload_dir / "clean_room_request.json").read_text()
    )
    request = request_from_dict(request_dict)
    failures = request_schema_failures(request)
    assert any("retired_prompt_text" in f and "const-false" in f
               for f in failures)


def test_injection9_kernel_blocks_the_bundle():
    payload_dir = FIXTURES / "clean_room_violation"
    request = json.loads(
        (payload_dir / "clean_room_request.json").read_text()
    )
    bundle = json.loads(
        (payload_dir / "clean_room_bundle.json").read_text()
    )
    report = ConstitutionalKernel().validate_clean_room_bundle(
        bundle, request, None
    )
    assert report.blocking
    codes = {v.code for v in report.violations}
    assert codes == {"CK-CLN-001"}
    assert any("retired_prompt_text" in v.detail for v in report.violations)


# ── injection 10: stale record leakage ───────────────────────────────────────


def _stale_leak_inputs():
    payload_dir = FIXTURES / "stale_record_leakage"
    registry = json.loads((payload_dir / "rqgm_registry.json").read_text())
    records = [
        json.loads(line)
        for line in (
            payload_dir / "proposals" / "proposal_records.jsonl"
        ).read_text().splitlines()
        if line.strip()
    ]
    retired = {
        e["prompt_hash"]
        for e in registry["prompts"]
        if e["status"] in ("retired", "banned")
    }
    return records, retired


def test_injection10_kernel_flags_the_leak():
    records, retired = _stale_leak_inputs()
    report = ConstitutionalKernel().validate_selective_erasure(
        records, records, retired
    )
    assert report.blocking
    codes = {v.code for v in report.violations}
    # In the frontier with a retired hash AND not staled by the closure.
    assert {"CK-ERA-003", "CK-ERA-004"} <= codes
    assert all(v.subject_ref == "eval_rec_stale_leak"
               for v in report.violations)


def test_injection10_metric9_sees_full_contamination():
    records, retired = _stale_leak_inputs()
    out = frontier_contamination(records, retired)
    assert out["value"] == 1.0
    assert out["evidence_refs"] == ["eval_rec_stale_leak"]


def test_injection10_repaired_frontier_passes():
    records, retired = _stale_leak_inputs()
    repaired = [dict(records[0], stale=True, valid_for_frontier=False)]
    # A repaired frontier excludes the record entirely ...
    report = ConstitutionalKernel().validate_selective_erasure(
        [], repaired, retired
    )
    assert report.ok
    # ... and metric 9 over the empty frontier degrades, never crashes.
    assert frontier_contamination([], retired)["applicable"] is False


# ── injection 3: payload sanity (detection channel is B4-adversarial) ────────


def test_injection3_fixture_cites_ids_absent_from_snapshot():
    payload_dir = FIXTURES / "hallucinated_prior_art"
    record = json.loads(
        (payload_dir / "proposals" / "proposal_records.jsonl")
        .read_text().splitlines()[0]
    )
    known = {
        ref["id"]
        for ref in json.loads(
            (payload_dir / "related_refs.json").read_text()
        )["references"]
    }
    cited = {
        token
        for risk in record["summary"]["novelty_risks"]
        for token in risk.split()
        if token.startswith("S2:")
    }
    assert cited and cited.isdisjoint(known)   # fabricated by construction


# ── control: clean artifacts stay clean ──────────────────────────────────────


def test_control_fixture_passes_the_gate():
    report = gate_detection_report(FIXTURES / "control_clean")
    assert report["errors"] == []
    assert report["should_block"] is False
    assert report["metrics"]["numeric_claim_reproducible_rate"] == 1.0
