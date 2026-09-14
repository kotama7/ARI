"""Task-20 metrics use persisted K/C/A evidence without fabricating panels."""

from __future__ import annotations

import json
from pathlib import Path

from ari.rqgm.evaluation.metrics import (
    ASSURANCE_METRIC_KEYS,
    KNOWLEDGE_CAPABILITY_METRIC_KEYS,
    METRIC_KEYS,
    compute_metric_report,
)


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, values) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(value) + "\n" for value in values),
        encoding="utf-8",
    )


def test_empty_checkpoint_has_complete_absence_tolerant_kca_blocks(tmp_path):
    report = compute_metric_report(tmp_path, condition_id="B0", seed=11)
    assert tuple(report["metrics"]) == METRIC_KEYS
    assert tuple(report["knowledge_capability"]) == KNOWLEDGE_CAPABILITY_METRIC_KEYS
    assert tuple(report["assurance"]) == ASSURANCE_METRIC_KEYS
    assert all(not entry["applicable"] for entry in report["knowledge_capability"].values())
    assert all(not entry["applicable"] for entry in report["assurance"].values())


def test_direct_kca_metrics_are_computed_from_locks_records_and_nodes(tmp_path):
    admission = tmp_path / "rqgm" / "kca" / "admission-v1"
    _write_json(admission / "capability_binding_lock.json", {
        "requirements": [
            {"requirement_digest": "r1", "required": True},
            {"requirement_digest": "r2", "required": True},
        ],
        "bindings": [{"requirement_digest": "r1"}],
        "unsatisfied": [{"requirement_digest": "r2", "required": True}],
    })
    _write_json(admission / "baseline_harness_lock.json", {
        "requirements": [{"atom_digest": "a1"}, {"atom_digest": "a2"}],
        "harnesses": [{"covered_atom_digests": ["a1"]}],
    })
    _write_json(tmp_path / "tree.json", {"nodes": [{
        "id": "node-1",
        "status": "SUCCESS",
        "knowledge_skill_refs": ["knowledge:test"],
        "knowledge_skill_use_digest": "k-use",
        "capability_binding_lock_digest": "binding",
        "bound_tool_refs": ["provider::tool"],
        "attestation_refs": ["att-1"],
        "assurance_status": "pass",
        "frontier_class": "scientific_frontier",
        "metrics": {},
    }]})
    _write_jsonl(tmp_path / "rqgm_audit.jsonl", [
        {"event_type": "capability_binding", "payload": {
            "record_type": "capability_binding",
            "record_id": "cap-1",
            "invocation_decisions": [
                {"reason_code": "bound"},
                {"reason_code": "unknown_tool"},
            ],
        }},
        {"event_type": "harness_attestation", "payload": {
            "record_type": "harness_attestation",
            "record_id": "att-1",
            "verdict": "infrastructure_error",
        }},
    ])
    _write_jsonl(tmp_path / "cost_trace.jsonl", [
        {"phase": "provider", "cost_usd": 2.0},
        {"phase": "screen", "cost_usd": 3.0},
    ])

    report = compute_metric_report(tmp_path, condition_id="B8", seed=11)
    kc = report["knowledge_capability"]
    assurance = report["assurance"]
    assert kc["capability_coverage_rate"]["value"] == 0.5
    assert kc["unsupported_capability_rate"]["value"] == 0.5
    assert kc["unbound_invocation_rate"]["value"] == 0.5
    assert kc["tool_hallucination_rate"]["value"] == 0.5
    assert kc["provenance_completeness"]["value"] == 1.0
    assert kc["cost_per_successful_bound_node"]["value"] == 2.0
    assert assurance["required_property_coverage_rate"]["value"] == 0.5
    assert assurance["infrastructure_error_rate"]["value"] == 1.0
    assert assurance["scientific_frontier_contamination_rate"]["value"] == 0.0
    assert assurance["verification_cost_per_valid_node"]["value"] == 3.0
    assert assurance["tier_cost_breakdown"]["detail"]["cost_usd"] == {
        "screen": 3.0, "validate": 0, "certify": 0
    }
    assert assurance["tier_cost_breakdown"]["detail"]["cost_status"] == "complete"
    # Cross-run quantities require their explicit matched-panel artifact.
    assert not kc["skill_portability_across_providers"]["applicable"]
    assert not assurance["harness_false_accept_rate"]["applicable"]


def test_task20_blocks_do_not_change_existing_thirteen_metrics(tmp_path):
    before = compute_metric_report(tmp_path, condition_id="B0", seed=7)["metrics"]
    panel = tmp_path / "rqgm" / "kca" / "evaluation"
    _write_json(panel / "knowledge_capability_panel.json", {
        "binding_determinism_rate": 1.0,
    })
    _write_json(panel / "assurance_panel.json", {
        "harness_lock_determinism_rate": 1.0,
    })
    after = compute_metric_report(tmp_path, condition_id="B0", seed=7)
    assert after["metrics"] == before
    assert after["knowledge_capability"]["binding_determinism_rate"]["value"] == 1.0
    assert after["assurance"]["harness_lock_determinism_rate"]["value"] == 1.0


def test_canonical_cost_field_and_verifier_resources_are_aggregated(tmp_path):
    _write_json(tmp_path / "tree.json", {"nodes": [{
        "id": "node-1",
        "status": "SUCCESS",
        "assurance_status": "pass",
        "frontier_class": "scientific_frontier",
        "metrics": {},
    }]})
    _write_jsonl(tmp_path / "cost_trace.jsonl", [
        {
            "phase": "provider",
            "estimated_cost_usd": 2.5,
        },
        {
            "phase": "screen",
            "component": "assurance",
            "estimated_cost_usd": 1.25,
            "cost_status": "measured",
            "wall_time_ms": 2000,
            "cpu_core_seconds": 4,
            "accelerator_seconds": 2,
            "memory_byte_seconds": 8192,
        },
    ])

    report = compute_metric_report(tmp_path, condition_id="K4", seed=7)
    assert report["knowledge_capability"]["cost_per_successful_bound_node"][
        "applicable"
    ] is False
    cost = report["assurance"]["verification_cost_per_valid_node"]
    assert cost["value"] == 1.25
    assert cost["detail"]["resources_per_valid_node"] == {
        "wall_time_seconds": 2.0,
        "cpu_core_seconds": 4.0,
        "accelerator_seconds": 2.0,
        "memory_byte_seconds": 8192.0,
    }


def test_unpriced_verifier_execution_is_not_reported_as_free(tmp_path):
    _write_json(tmp_path / "tree.json", {"nodes": [{
        "id": "node-1",
        "status": "SUCCESS",
        "assurance_status": "pass",
        "frontier_class": "scientific_frontier",
        "metrics": {},
    }]})
    _write_jsonl(tmp_path / "cost_trace.jsonl", [{
        "phase": "screen",
        "component": "assurance",
        "estimated_cost_usd": 0.0,
        "cost_status": "unpriced",
        "wall_time_ms": 500,
        "cpu_core_seconds": 1.0,
        "accelerator_seconds": 0.0,
        "memory_byte_seconds": 2048.0,
    }])

    report = compute_metric_report(tmp_path, condition_id="H2", seed=7)
    cost = report["assurance"]["verification_cost_per_valid_node"]
    assert cost["applicable"] is True
    assert cost["value"] is None
    assert cost["detail"]["cost_status"] == "unpriced"
    tiers = report["assurance"]["tier_cost_breakdown"]
    assert tiers["applicable"] is True
    assert tiers["value"] is None
    assert tiers["detail"]["tiers"]["screen"]["wall_time_seconds"] == 0.5
