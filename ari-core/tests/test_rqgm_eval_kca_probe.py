"""Task-20 mutations traverse production validators, with clean controls."""

from __future__ import annotations

import json

from ari.rqgm.evaluation.injection import load_injection_specs
from ari.rqgm.evaluation.kca_probe import (
    run_and_persist_kca_probes,
    run_kca_probe,
)
from ari.rqgm.evaluation.smoke import run_condition_smoke


SPECS = load_injection_specs()
FAULTS = SPECS["kca_injections"]
CONTROLS = SPECS["kca_controls"]


def test_all_kca_faults_hit_their_declared_production_detection_channel():
    for spec in FAULTS:
        first = run_kca_probe(spec)
        second = run_kca_probe(spec)
        assert first == second
        assert first["expected_met"], (
            spec["injection_id"],
            first["expected_channels"],
            first["observed_channels"],
        )
        assert first["record_types"] == sorted(
            spec["expected_detection"]["record_types"]
        )
        assert first["production_entrypoint"].startswith(
            ("ari.", "ConstitutionalKernel.")
        )


def test_all_same_shape_controls_traverse_cleanly():
    faults = {item["injection_id"]: item for item in FAULTS}
    for spec in CONTROLS:
        source = faults[spec["control_for"]]
        result = run_kca_probe(spec, source_mutation=source["mutation"])
        assert result["expected_met"]
        assert result["observed_channels"] == []
        assert result["record_types"] == []


def test_probe_campaign_persists_audit_records_and_matched_panels(tmp_path):
    summary = run_and_persist_kca_probes(tmp_path, FAULTS + CONTROLS)
    assert summary["kca_probes"] == summary["kca_expected_met"] == 76
    records = [
        json.loads(line)
        for line in (
            tmp_path / "rqgm/kca/evaluation/kca_probe_records.jsonl"
        ).read_text(encoding="utf-8").splitlines()
    ]
    assert len(records) == 76
    assert all(item["deterministic"] for item in records)
    audit = (
        tmp_path / "rqgm_audit.jsonl"
    ).read_text(encoding="utf-8").splitlines()
    assert len(audit) == 76

    knowledge = json.loads(
        (tmp_path / "rqgm/kca/evaluation/knowledge_capability_panel.json")
        .read_text(encoding="utf-8")
    )
    assurance = json.loads(
        (tmp_path / "rqgm/kca/evaluation/assurance_panel.json")
        .read_text(encoding="utf-8")
    )
    assert knowledge["binding_determinism_rate"]["value"] == 1.0
    assert knowledge["skill_prompt_injection_success_rate"]["value"] == 0.0
    assert assurance["harness_false_accept_rate"]["value"] == 0.0
    assert assurance["harness_false_reject_rate"]["value"] == 0.0
    assert assurance["attestation_integrity_detection_rate"]["value"] == 1.0


def test_factorial_smoke_runs_kca_probe_before_metric_collection(tmp_path):
    report = run_condition_smoke(
        tmp_path,
        "B8__H3_assurance_full_certification__K3_capability_binding_enforced",
        injections=(FAULTS[0], CONTROLS[0]),
    )
    assert report["smoke_summary"]["kca_probes"] == 2
    assert report["smoke_summary"]["kca_expected_met"] == 2
    assert report["knowledge_capability"][
        "skill_prompt_injection_success_rate"
    ]["value"] == 0.0
