"""Canonical GateReportV1 evidence, unit, and policy calibration tests."""

from __future__ import annotations

import hashlib
import json

import pytest

from ari.calibration import load_evaluator_calibration_v1
from ari.execution import MeasurementRecordV1, MeasurementSetV1
from ari.pipeline.claim_gate.gate import run_hard_gate
from ari.pipeline.claim_gate.numeric import formula_registry_digest
from ari.public.claim_gate import (
    ClaimGateContractError,
    MetricClaimV1,
    MetricGateContractV1,
    migrate_legacy_gate_report,
    parse_gate_report,
)
from ari.research_contract import (
    MetricContractV1,
    MetricFormulaProvenanceV1,
    MetricToleranceV1,
    canonical_digest,
)


def _measurement_document(measurement_set: MeasurementSetV1) -> dict:
    return {
        "schema_version": "1.0",
        "typed_schema_version": measurement_set.schema_version,
        "measurement_set": measurement_set.model_dump(mode="json"),
        "params": measurement_set.parameters,
        "measurements": {
            item.metric_id: item.value for item in measurement_set.measurements
        },
        "measurement_records": [
            item.model_dump(mode="json") for item in measurement_set.measurements
        ],
        "predictions": measurement_set.predictions,
        "scores": measurement_set.scores,
        "_provenance": {
            item.metric_id: item.provenance
            for item in measurement_set.measurements
            if item.provenance is not None
        },
    }


def _fixture(tmp_path, *, artifact: bool = False):
    workspace = tmp_path
    checkpoint = workspace / "checkpoints" / "run1"
    checkpoint.mkdir(parents=True)
    (checkpoint / "tree.json").write_text(
        json.dumps(
            {
                "nodes": [
                    {
                        "id": "n1",
                        "has_real_data": True,
                        "metrics": {"latency": 100.0},
                    }
                ]
            }
        )
    )
    node_dir = workspace / "experiments" / "run1" / "n1"
    node_dir.mkdir(parents=True)
    artifact_digests = []
    report_artifacts = []
    if artifact:
        payload = b"raw evidence\n"
        path = node_dir / "evidence.bin"
        path.write_bytes(payload)
        digest = "sha256:" + hashlib.sha256(payload).hexdigest()
        artifact_digests.append(digest)
        report_artifacts.append(
            {
                "filename": path.name,
                "role": "data_output",
                "size": len(payload),
                "sha256": digest,
            }
        )
    record = MeasurementRecordV1(
        metric_id="latency",
        value=100.0,
        unit="ms",
        unit_status="declared",
        provenance="measurement",
        artifact_digests=artifact_digests,
    )
    measurement_set = MeasurementSetV1(
        measurements=[record], artifact_digests=artifact_digests
    )
    (node_dir / "results.json").write_text(
        json.dumps(_measurement_document(measurement_set))
    )
    (node_dir / "node_report.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "node_id": "n1",
                "executor": "local",
                "cpu_info": {"model": "fixture", "arch": "x86_64"},
                "artifacts": report_artifacts,
            }
        )
    )
    source_digest = canonical_digest({"human": "fixture"})
    metric = MetricContractV1.create(
        name="latency",
        unit="ms",
        direction="lower",
        comparison_scope="same-environment",
        rationale="A direct latency observation.",
        required_evidence=("latency",),
        correctness_required=False,
        normalization_ceiling="not-applicable",
        formula="value",
        operands={"value": "latency"},
        tolerance=MetricToleranceV1(absolute=0.0, relative=0.01),
        formula_provenance=MetricFormulaProvenanceV1(
            source="human-admission", source_digest=source_digest
        ),
        confidence=1.0,
        admission_status="admitted",
        invariants=("value >= 0",),
    )
    projection = MetricGateContractV1.create(
        source="human-admitted",
        source_idea_digest=source_digest,
        metric_contract=metric,
        claims=(
            MetricClaimV1(
                claim="Latency is measured.", required_evidence=("latency",)
            ),
        ),
    )
    result_ref = {
        "run_id": "run1",
        "node_id": "n1",
        "metric_path": "measurements.latency",
    }
    assertion = {
        "id": "NC1",
        "claim_id": "C1",
        "metric": "latency",
        "value": 100.0,
        "unit": "ms",
        "formula": "identity",
        "operands": {"value": dict(result_ref)},
        "tolerance": {"absolute": 0.0, "relative": 0.01},
    }
    science_data = {
        "metric_contract": projection.model_dump(mode="json"),
        "configurations": [
            {
                "config_id": "cfg1",
                "measurements": {"latency": 100.0},
                "_provenance": {"latency": "measurement"},
            }
        ],
        "claims": [
            {
                "id": "C1",
                "text": "Latency is 100 ms.",
                "status": "supported",
                "supported_by": {
                    "nodes": ["n1"],
                    "results": [dict(result_ref)],
                    "artifacts": [],
                },
            }
        ],
        "numeric_assertions": [assertion],
    }
    links = {
        "paper_claim_links": [
            {
                "claim_id": "C1",
                "numeric_id": "NC1",
                "line_range": [4, 4],
                "resolved": True,
                "figures": [],
            }
        ],
        "numeric_mentions": [
            {
                "value": 0.1,
                "unit": "s",
                "type": "result_claim",
                "requires_assertion": True,
                "section": "results",
                "line": 4,
            }
        ],
    }
    return checkpoint, node_dir, science_data, links


def _codes(report):
    return {item["type"] for item in report["blocking_findings"]}


def test_canonical_gate_is_typed_deterministic_and_records_conversion(tmp_path):
    checkpoint, _, science_data, links = _fixture(tmp_path)
    first = run_hard_gate(
        checkpoint,
        paper_tex="0.1 s",
        science_data=science_data,
        paper_claim_links=links,
        policy={"mode": "strict"},
        phase="final",
        write=False,
    )
    second = run_hard_gate(
        checkpoint,
        paper_tex="0.1 s",
        science_data=science_data,
        paper_claim_links=links,
        policy={"mode": "strict"},
        phase="final",
        write=False,
    )
    parsed = parse_gate_report(first)
    assert first == second
    assert parsed.status == "passed"
    assert parsed.report_digest == second["report_digest"]
    assert parsed.formula_provenance.unit_conversions
    assert parsed.policy_digest.startswith("sha256:")
    assert parsed.evidence_digest.startswith("sha256:")

    changed = json.loads(json.dumps(first))
    changed["metrics"]["numeric_reproducible"] = 99
    with pytest.raises(ClaimGateContractError, match="report_digest"):
        parse_gate_report(changed)


def test_cross_run_operand_is_blocking(tmp_path):
    checkpoint, _, science_data, links = _fixture(tmp_path)
    science_data["numeric_assertions"][0]["operands"]["value"]["run_id"] = "run2"
    report = run_hard_gate(
        checkpoint,
        paper_tex="",
        science_data=science_data,
        paper_claim_links=links,
        policy={"mode": "strict"},
        phase="final",
        write=False,
    )
    assert "cross_run_evidence" in _codes(report)
    assert report["should_block"] is True


def test_unknown_node_is_blocking(tmp_path):
    checkpoint, _, science_data, links = _fixture(tmp_path)
    science_data["numeric_assertions"][0]["operands"]["value"]["node_id"] = "ghost"
    report = run_hard_gate(
        checkpoint,
        paper_tex="",
        science_data=science_data,
        paper_claim_links=links,
        policy={"mode": "strict"},
        phase="final",
        write=False,
    )
    assert "cross_run_or_unknown_node" in _codes(report)


def test_artifact_digest_tampering_is_objectively_blocking(tmp_path):
    checkpoint, node_dir, science_data, links = _fixture(tmp_path, artifact=True)
    (node_dir / "evidence.bin").write_bytes(b"tampered\n")
    report = run_hard_gate(
        checkpoint,
        paper_tex="",
        science_data=science_data,
        paper_claim_links=links,
        policy={"mode": "warn"},
        phase="final",
        write=False,
    )
    assert "artifact_digest_mismatch" in _codes(report)
    assert report["should_block"] is True


def test_untyped_artifact_reference_is_rejected_for_canonical_run(tmp_path):
    checkpoint, _, science_data, links = _fixture(tmp_path)
    science_data["claims"][0]["supported_by"]["artifacts"] = ["evidence.bin"]
    report = run_hard_gate(
        checkpoint,
        paper_tex="",
        science_data=science_data,
        paper_claim_links=links,
        policy={"mode": "strict"},
        phase="final",
        write=False,
    )
    assert "artifact_reference_untyped" in _codes(report)


def test_unknown_unit_is_not_guessed(tmp_path):
    checkpoint, _, science_data, links = _fixture(tmp_path)
    links["numeric_mentions"][0]["unit"] = "ticks"
    report = run_hard_gate(
        checkpoint,
        paper_tex="",
        science_data=science_data,
        paper_claim_links=links,
        policy={"mode": "strict"},
        phase="final",
        write=False,
    )
    assert "unit_mismatch" in _codes(report)


def test_off_policy_never_blocks_even_objective_finding(tmp_path):
    checkpoint, node_dir, science_data, links = _fixture(tmp_path, artifact=True)
    (node_dir / "evidence.bin").write_bytes(b"tampered\n")
    report = run_hard_gate(
        checkpoint,
        paper_tex="",
        science_data=science_data,
        paper_claim_links=links,
        policy={"mode": "off"},
        phase="final",
        write=False,
    )
    assert "artifact_digest_mismatch" in _codes(report)
    assert report["should_block"] is False


def test_formula_registry_digest_tracks_implementation(monkeypatch):
    original = formula_registry_digest()
    from ari.pipeline.claim_gate import numeric

    monkeypatch.setitem(
        numeric.FORMULAS,
        "identity",
        (("value",), lambda operands: operands["value"] + 1),
    )
    assert formula_registry_digest() != original


def test_legacy_gate_report_reader_is_typed_and_does_not_rewrite_source():
    legacy = {
        "gate": "claim_evidence_hard_gate",
        "phase": "final",
        "policy": "strict",
        "comparison_scope": "any",
        "status": "failed",
        "should_block": True,
        "errors": [
            {
                "type": "numeric_mismatch",
                "message": "legacy mismatch",
                "reported": 3.0,
            }
        ],
        "warnings": [],
        "metrics": {"numeric_claim_mismatch_count": 1},
    }
    before = json.dumps(legacy, sort_keys=True)
    migrated = migrate_legacy_gate_report(legacy, source_run_id="published-run")

    assert migrated.schema_version == "ari.gate-report/v1"
    assert migrated.source_run_id == "published-run"
    assert migrated.blocking_findings[0].details["reported"] == 3.0
    assert migrated.formula_provenance.formulas_used == ("legacy-unrecorded",)
    assert json.dumps(legacy, sort_keys=True) == before


def test_versioned_hard_gate_calibration_corpus(tmp_path):
    corpus = load_evaluator_calibration_v1()
    assert corpus["schema_version"] == "ari.evaluator-calibration/v1"
    cases = corpus["hard_gate_cases"]
    assert len({case["id"] for case in cases}) == len(cases)
    assert {case["category"] for case in cases} >= {
        "numeric",
        "unit",
        "formula",
        "evidence",
        "policy",
    }

    for case in cases:
        checkpoint, node_dir, science_data, links = _fixture(
            tmp_path / case["id"], artifact=case["artifact_fixture"]
        )
        mutation = case["mutation"]
        if mutation == "reported-value-mismatch":
            links["numeric_mentions"][0]["value"] = 0.2
        elif mutation == "unknown-formula":
            science_data["numeric_assertions"][0]["formula"] = "unknown"
        elif mutation == "unknown-unit":
            links["numeric_mentions"][0]["unit"] = "ticks"
        elif mutation == "cross-run-operand":
            science_data["numeric_assertions"][0]["operands"]["value"][
                "run_id"
            ] = "other-run"
        elif mutation == "unknown-node":
            science_data["numeric_assertions"][0]["operands"]["value"][
                "node_id"
            ] = "ghost"
        elif mutation == "missing-evidence":
            science_data["claims"][0]["supported_by"] = {
                "nodes": [],
                "results": [],
                "artifacts": [],
            }
        elif mutation == "untyped-artifact":
            science_data["claims"][0]["supported_by"]["artifacts"] = [
                "evidence.bin"
            ]
        elif mutation == "tamper-artifact":
            (node_dir / "evidence.bin").write_bytes(b"tampered\n")
        elif mutation != "none":
            raise AssertionError(f"unknown calibration mutation: {mutation}")

        report = run_hard_gate(
            checkpoint,
            paper_tex="0.1 s",
            science_data=science_data,
            paper_claim_links=links,
            policy={"mode": case["policy_mode"]},
            phase="final",
            write=False,
        )
        assert report["status"] == case["expected_status"], case["id"]
        assert report["should_block"] is case["expected_should_block"], case["id"]
        assert set(case["expected_finding_types"]) <= _codes(report), case["id"]


def test_semantic_calibration_labels_include_positive_and_negative_controls():
    cases = load_evaluator_calibration_v1()["semantic_cases"]
    assert len({case["id"] for case in cases}) == len(cases)
    assert any(case["negative_control"] for case in cases)
    assert any(not case["negative_control"] for case in cases)
    for case in cases:
        assert case["evidence_summary"] and case["paper_text"]
        if case["negative_control"]:
            assert case["expected_finding_types"] == []
        else:
            assert set(case["expected_finding_types"]) <= {
                "overclaim",
                "overgeneralization",
                "unsupported_claim",
                "interpretation",
                "visual_semantics",
            }
