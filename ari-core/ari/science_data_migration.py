"""Offline-only migration for pre-v1 scientific-data checkpoints.

The native runtime parser deliberately does not import old flat formats.  This
module is reached only through the explicit migration entrypoint retained by
``ari.science_data_contract``.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from ari.claim_gate_contract import (
    migrate_legacy_metric_gate_contract,
    parse_metric_gate_contract,
)
from ari.science_data_contract import (
    SCIENCE_DATA_V1,
    ScienceArtifactRefV1,
    ScienceConfigurationV1,
    ScienceDataError,
    ScienceDataV1,
    ScienceDerivedV1,
    ScienceInterpretationV1,
    ScienceMetricSummaryV1,
    ScienceProvenanceV1,
    ScienceRawV1,
    formula_registry_digest,
    parse_science_data,
)


def _finite_metrics(value: Any) -> dict[str, int | float]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key): number
        for key, number in value.items()
        if isinstance(number, (int, float))
        and not isinstance(number, bool)
        and math.isfinite(float(number))
        and not str(key).startswith("_")
    }


def _migrate_metric_contract(value: Any) -> tuple[dict[str, Any] | None, bool]:
    if not isinstance(value, dict):
        return None, False
    try:
        if value.get("schema_version") == "ari.metric-gate-contract/v1":
            contract = parse_metric_gate_contract(value)
        else:
            contract = migrate_legacy_metric_gate_contract(value)
    except ValueError:
        return None, True
    return contract.model_dump(mode="json"), False


def migrate_legacy_document(
    value: dict[str, Any] | str,
    *,
    run_id: str,
    logical_name: str,
) -> ScienceDataV1:
    """Conservatively bind a legacy flat document without admitting claims."""

    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ScienceDataError("legacy science data is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ScienceDataError("legacy science data must be an object")
    if value.get("schema_version") == SCIENCE_DATA_V1:
        return parse_science_data(value)
    source_payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    source = ScienceArtifactRefV1(
        relative_path=logical_name,
        digest="sha256:" + hashlib.sha256(source_payload).hexdigest(),
        media_type="application/json",
        role="legacy-science-data",
        size_bytes=len(source_payload),
    )
    config_nodes = value.get("_config_nodes") or {}
    configs: list[ScienceConfigurationV1] = []
    for index, raw_config in enumerate(value.get("configurations") or []):
        if not isinstance(raw_config, dict):
            continue
        config_id = str(raw_config.get("config_id") or f"cfg{index + 1}")
        node_info = (
            config_nodes.get(config_id) if isinstance(config_nodes, dict) else {}
        )
        node_info = node_info if isinstance(node_info, dict) else {}
        configs.append(
            ScienceConfigurationV1(
                config_id=config_id,
                run_id=run_id,
                node_id=str(node_info.get("node_id") or f"legacy-node-{index + 1}"),
                rank=int(raw_config.get("rank") or index + 1),
                label=str(raw_config.get("label") or "legacy")[:256],
                source_kind="legacy-untyped",
                claim_eligible=False,
                parameters=dict(raw_config.get("parameters") or {}),
                measurements={},
                measurement_records=(),
                predictions=dict(raw_config.get("predictions") or {}),
                scores=dict(raw_config.get("scores") or {}),
                legacy_metrics={
                    **_finite_metrics(raw_config.get("metrics")),
                    **_finite_metrics(raw_config.get("measurements")),
                },
                source_artifacts=(source,),
            )
        )
    if not configs:
        raise ScienceDataError("legacy science data contains no configurations")
    raw = ScienceRawV1.create(
        tree_artifact=source,
        configurations=tuple(configs),
        node_report_status="legacy",
        measurement_status="legacy",
    )
    summaries: list[ScienceMetricSummaryV1] = []
    summary_source = value.get("per_key_summary") or {}
    if not isinstance(summary_source, dict):
        summary_source = {}
    for metric, record in summary_source.items():
        if not isinstance(record, dict):
            continue
        numbers = [
            (config.config_id, config.legacy_metrics.get(metric)) for config in configs
        ]
        numbers = [
            (config_id, number) for config_id, number in numbers if number is not None
        ]
        if not numbers:
            continue
        numeric_values = [float(number) for _, number in numbers]
        summaries.append(
            ScienceMetricSummaryV1(
                metric_id=str(metric),
                unit=str(record.get("unit") or "unknown"),
                minimum=min(numeric_values),
                maximum=max(numeric_values),
                best_value=float(record.get("best_value", max(numeric_values))),
                count=len(numeric_values),
                direction="unspecified",
                source_config_ids=tuple(config_id for config_id, _ in numbers),
            )
        )
    derived = ScienceDerivedV1.create(
        formula_registry_digest=formula_registry_digest(),
        metric_summaries=tuple(summaries),
        summary_stats=dict(value.get("summary_stats") or {}),
        claims=(),
        numeric_assertions=(),
        anomalies=tuple(value.get("_anomalies") or ()),
    )
    interpretation = ScienceInterpretationV1.create(
        status="legacy-migrated",
        input_raw_digest=raw.raw_digest,
        evaluation_protocol={},
        experiment_context=dict(value.get("experiment_context") or {}),
        implementation_overview=(
            dict(value["implementation_overview"])
            if isinstance(value.get("implementation_overview"), dict)
            else None
        ),
        error_kind="legacy-unverified",
        error_message="Imported explicitly from a pre-v1 science_data artifact.",
    )
    provenance = ScienceProvenanceV1(
        producer_tool_ref="transform-skill/migrate-science-data@v1",
        producer_version="1",
        input_artifacts=(source,),
    )
    metric_contract, contract_dropped = _migrate_metric_contract(
        value.get("metric_contract")
    )
    limitations = [
        "Legacy metrics are untyped and are not eligible as paper evidence.",
        "Legacy claims were not carried forward without exact artifact binding.",
    ]
    if contract_dropped:
        limitations.append(
            "The legacy metric contract was invalid and was not carried forward."
        )
    return ScienceDataV1.create(
        run_id=run_id,
        raw=raw,
        derived=derived,
        interpretation=interpretation,
        metric_contract=metric_contract,
        limitations=tuple(limitations),
        provenance=provenance,
        migration_status="legacy-explicit",
    )


__all__ = ["migrate_legacy_document"]
