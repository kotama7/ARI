"""Cross-section validation for canonical scientific-data documents."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from ari.pipeline.claim_gate.numeric import recompute

if TYPE_CHECKING:
    from ari.science_data_contract import (
        ScienceConfigurationV1,
        ScienceDataV1,
        ScienceNumericAssertionV1,
    )


def _environment_key(value: Any) -> tuple[str, str, str]:
    return (value.executor, value.cpu_model, value.arch)


def _measurement_value(config: "ScienceConfigurationV1", path: str) -> float:
    namespace, separator, metric = path.partition(".")
    if (
        namespace != "measurements"
        or not separator
        or metric not in config.measurements
    ):
        raise ValueError(
            f"claim pointer does not resolve to a typed measurement: {path}"
        )
    return float(config.measurements[metric])


def _validate_assertion(
    science: "ScienceDataV1",
    assertion: "ScienceNumericAssertionV1",
    by_node: dict[str, "ScienceConfigurationV1"],
) -> None:
    operand_values: dict[str, float] = {}
    environments: set[tuple[str, str, str]] = set()
    for role, operand in assertion.operands.items():
        if operand.run_id != science.run_id or operand.node_id not in by_node:
            raise ValueError("numeric assertion operand has an unknown run or node")
        config = by_node[operand.node_id]
        if not config.claim_eligible:
            raise ValueError("numeric assertion references non-claimable data")
        if _environment_key(operand.environment) != _environment_key(
            config.environment
        ):
            raise ValueError(
                "numeric assertion environment differs from raw provenance"
            )
        operand_values[role] = _measurement_value(config, operand.metric_path)
        environments.add(_environment_key(config.environment))
    if assertion.cross_environment != (len(environments) > 1):
        raise ValueError("numeric assertion cross-environment flag is incorrect")
    computed = recompute(assertion.formula, operand_values)
    if computed is None:
        raise ValueError("numeric assertion formula is undefined for its operands")
    absolute = float(assertion.tolerance.get("absolute", 0.0))
    relative = float(assertion.tolerance.get("relative", 0.0))
    allowed = max(absolute, relative * abs(float(computed)))
    if not math.isclose(
        float(assertion.value), float(computed), rel_tol=0, abs_tol=allowed
    ):
        raise ValueError("numeric assertion does not recompute from raw measurements")


def _validate_migration_status(science: "ScienceDataV1") -> bool:
    if science.migration_status != "legacy-explicit":
        if "legacy" in {
            science.raw.node_report_status,
            science.raw.measurement_status,
        }:
            raise ValueError("native science data cannot use legacy raw status")
        if science.interpretation.status == "legacy-migrated":
            raise ValueError("native science data cannot contain legacy interpretation")
        return False
    if (
        science.derived.claims
        or science.derived.numeric_assertions
        or any(config.claim_eligible for config in science.raw.configurations)
    ):
        raise ValueError("legacy migration cannot admit scientific claims")
    if science.interpretation.status != "legacy-migrated" or {
        science.raw.node_report_status,
        science.raw.measurement_status,
    } != {"legacy"}:
        raise ValueError("legacy migration status is inconsistent")
    return True


def _validate_native_raw_status(science: "ScienceDataV1") -> None:
    count = len(science.raw.configurations)
    report_count = sum(
        any(source.role == "node-report" for source in config.source_artifacts)
        for config in science.raw.configurations
    )
    typed_count = sum(config.claim_eligible for config in science.raw.configurations)
    expected_reports = (
        "complete"
        if report_count == count
        else "partial"
        if report_count
        else "missing"
    )
    expected_measurements = (
        "complete" if typed_count == count else "partial" if typed_count else "missing"
    )
    if science.raw.node_report_status != expected_reports:
        raise ValueError("node-report status differs from raw source artifacts")
    if science.raw.measurement_status != expected_measurements:
        raise ValueError("measurement status differs from claim eligibility")


def _validate_derived_links(
    science: "ScienceDataV1",
    by_node: dict[str, "ScienceConfigurationV1"],
    by_config: dict[str, "ScienceConfigurationV1"],
) -> None:
    for summary in science.derived.metric_summaries:
        for config_id in summary.source_config_ids:
            config = by_config.get(config_id)
            if config is None or not config.claim_eligible:
                raise ValueError(
                    "metric summary references non-claimable configuration"
                )
            _measurement_value(config, f"measurements.{summary.metric_id}")
    for claim in science.derived.claims:
        if any(
            node_id not in by_node or not by_node[node_id].claim_eligible
            for node_id in claim.supported_by.nodes
        ):
            raise ValueError("claim references an unknown or non-claimable node")
        for result in claim.supported_by.results:
            if result.run_id != science.run_id or result.node_id not in by_node:
                raise ValueError("claim result pointer has an unknown run or node")
            _measurement_value(by_node[result.node_id], result.metric_path)
    for assertion in science.derived.numeric_assertions:
        _validate_assertion(science, assertion, by_node)


def validate_science_data_links(science: "ScienceDataV1") -> None:
    """Reject cross-section pointers that cannot be replayed from raw facts."""

    by_node = {config.node_id: config for config in science.raw.configurations}
    by_config = {config.config_id: config for config in science.raw.configurations}
    provenance_inputs = {
        (artifact.relative_path, artifact.digest)
        for artifact in science.provenance.input_artifacts
    }
    required_sources = {
        (science.raw.tree_artifact.relative_path, science.raw.tree_artifact.digest),
        *(
            (artifact.relative_path, artifact.digest)
            for config in science.raw.configurations
            for artifact in config.source_artifacts
        ),
    }
    if not required_sources <= provenance_inputs:
        raise ValueError("raw source artifact is absent from science provenance")

    if _validate_migration_status(science):
        return
    _validate_native_raw_status(science)
    _validate_derived_links(science, by_node, by_config)


__all__ = ["validate_science_data_links"]
