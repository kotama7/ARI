from __future__ import annotations

import copy

import pytest

from ari.public.execution import MeasurementRecordV1
from ari.public.science_data import (
    ScienceArtifactRefV1,
    ScienceConfigurationV1,
    ScienceDataError,
    ScienceDataV1,
    ScienceDerivedV1,
    ScienceInterpretationV1,
    ScienceProvenanceV1,
    ScienceRawV1,
    formula_registry_digest,
    migrate_legacy_science_data,
    parse_science_data,
    science_data_projection,
)


SHA_A = "sha256:" + "a" * 64
SHA_C = "sha256:" + "c" * 64


def _native(*, context: dict | None = None) -> ScienceDataV1:
    artifact = ScienceArtifactRefV1(
        relative_path="checkpoints/run/tree.json",
        digest=SHA_A,
        media_type="application/json",
        role="experiment-tree",
        size_bytes=12,
    )
    result_artifact = ScienceArtifactRefV1(
        relative_path="experiments/run/node-1/results.json",
        digest=SHA_C,
        media_type="application/json",
        role="measurement-set",
        size_bytes=48,
    )
    record = MeasurementRecordV1(
        metric_id="latency",
        value=1.25,
        unit="ms",
        unit_status="declared",
        execution_identity="sha256:" + "b" * 64,
        execution_attempt_id="attempt-1",
        execution_status="completed",
        exit_code=0,
    )
    config = ScienceConfigurationV1(
        config_id="cfg1",
        run_id="run",
        node_id="node-1",
        rank=1,
        source_kind="typed-measurement",
        claim_eligible=True,
        measurements={"latency": 1.25},
        measurement_records=(record,),
        source_artifacts=(artifact, result_artifact),
    )
    raw = ScienceRawV1.create(
        tree_artifact=artifact,
        configurations=(config,),
        node_report_status="missing",
        measurement_status="complete",
    )
    derived = ScienceDerivedV1.create(
        formula_registry_digest=formula_registry_digest(),
        summary_stats={"count": 1},
    )
    interpretation = ScienceInterpretationV1.create(
        status="unavailable",
        input_raw_digest=raw.raw_digest,
        experiment_context=context or {},
        error_kind="test-annotation",
        error_message="non-authoritative test annotation",
    )
    provenance = ScienceProvenanceV1(
        producer_tool_ref="transform-skill/nodes-to-science-data@v1",
        producer_version="1",
        input_artifacts=(artifact, result_artifact),
    )
    return ScienceDataV1.create(
        run_id="run",
        raw=raw,
        derived=derived,
        interpretation=interpretation,
        provenance=provenance,
    )


def test_native_round_trip_and_flat_projection():
    science = _native()
    parsed = parse_science_data(science.model_dump(mode="json"))
    projection = science_data_projection(parsed)
    assert projection["configurations"][0]["measurements"] == {"latency": 1.25}
    assert projection["configurations"][0]["_claim_eligible"] is True


def test_interpretation_cannot_change_deterministic_identity():
    first = _native(context={"claimed_latency": 999999})
    second = _native(context={"claimed_latency": -100})
    assert first.raw.raw_digest == second.raw.raw_digest
    assert first.derived.derived_digest == second.derived.derived_digest
    assert first.deterministic_digest == second.deterministic_digest
    assert first.science_data_digest != second.science_data_digest
    assert science_data_projection(first)["configurations"][0]["measurements"] == {
        "latency": 1.25
    }


def test_tampering_any_section_is_rejected():
    value = _native().model_dump(mode="json")
    value["raw"]["configurations"][0]["measurements"]["latency"] = 9.0
    with pytest.raises(ScienceDataError, match="measurement projection|digest"):
        parse_science_data(value)


def test_native_parser_does_not_implicitly_accept_legacy():
    with pytest.raises(ScienceDataError, match="explicit legacy reader"):
        parse_science_data({"configurations": []})


def test_explicit_legacy_migration_never_admits_old_claims():
    old = {
        "configurations": [
            {
                "config_id": "cfg1",
                "rank": 1,
                "metrics": {"latency": 1.25},
                "measurements": {"latency": 1.25},
            }
        ],
        "claims": [{"id": "C1", "text": "unbound old claim"}],
        "numeric_assertions": [{"id": "NC1", "value": 1.25}],
        "experiment_context": {"latency": 1.25},
    }
    migrated = migrate_legacy_science_data(old, run_id="legacy-run")
    assert migrated.migration_status == "legacy-explicit"
    assert migrated.raw.configurations[0].claim_eligible is False
    assert migrated.derived.claims == ()
    assert migrated.derived.numeric_assertions == ()
    assert migrated.interpretation.claim_eligible is False


def test_digest_fields_are_not_cosmetic():
    value = _native().model_dump(mode="json")
    altered = copy.deepcopy(value)
    altered["deterministic_digest"] = "sha256:" + "f" * 64
    with pytest.raises(ScienceDataError, match="deterministic science-data digest"):
        parse_science_data(altered)


def test_native_science_data_rejects_untyped_metric_contract():
    native = _native()
    with pytest.raises(ValueError, match="canonical digest-bound contract"):
        ScienceDataV1.create(
            run_id=native.run_id,
            raw=native.raw,
            derived=native.derived,
            interpretation=native.interpretation,
            metric_contract={"metric": "latency"},
            provenance=native.provenance,
        )
