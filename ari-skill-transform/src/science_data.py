"""Deterministic ``ScienceDataV1`` materialization for transform-skill.

This module is intentionally model-free.  It accepts the validated measurement
projection and node reports assembled by the MCP adapter, binds every input to a
content digest, and returns the raw/derived/provenance sections.  Stochastic
annotation is attached later by :mod:`annotations`.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ari.public.execution import MeasurementRecordV1
from ari.public.science_data import (
    ScienceArtifactRefV1,
    ScienceClaimEvidenceV1,
    ScienceClaimV1,
    ScienceConfigurationV1,
    ScienceDataV1,
    ScienceDerivedV1,
    ScienceEnvironmentV1,
    ScienceEvidenceResultV1,
    ScienceInterpretationV1,
    ScienceMetricSummaryV1,
    ScienceNumericAssertionV1,
    ScienceOperandV1,
    ScienceProvenanceV1,
    ScienceRawV1,
    formula_registry_digest,
)


PRODUCER_TOOL_REF = "transform-skill/nodes-to-science-data@v1"
PRODUCER_VERSION = "1"


@dataclass(frozen=True)
class DeterministicScienceSections:
    run_id: str
    raw: ScienceRawV1
    derived: ScienceDerivedV1
    metric_contract: dict[str, Any] | None
    limitations: tuple[str, ...]
    provenance: ScienceProvenanceV1


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _workspace_layout(nodes_json_path: str) -> tuple[Path, Path, str]:
    tree = Path(nodes_json_path).expanduser().resolve(strict=True)
    checkpoint = tree.parent
    workspace = (
        checkpoint.parent.parent
        if checkpoint.parent.name == "checkpoints"
        else checkpoint.parent
    )
    return workspace, checkpoint, checkpoint.name


def _relative_to_workspace(path: Path, workspace: Path) -> str:
    resolved = path.resolve(strict=True)
    try:
        return resolved.relative_to(workspace.resolve(strict=True)).as_posix()
    except ValueError:
        # Ad-hoc callers may pass a temporary tree outside an ARI workspace.
        # Its basename is still safe and its digest remains authoritative.
        return f"external/{resolved.name}"


def artifact_ref(path: Path, workspace: Path, *, role: str) -> ScienceArtifactRefV1:
    payload_size = path.stat().st_size
    return ScienceArtifactRefV1(
        relative_path=_relative_to_workspace(path, workspace),
        digest=_sha256_file(path),
        media_type="application/json"
        if path.suffix in {".json", ".lock"}
        else "application/octet-stream",
        role=role,
        size_bytes=payload_size,
    )


def _result_path(workspace: Path, run_id: str, node_id: str) -> Path | None:
    for candidate in (
        workspace / "experiments" / run_id / node_id / "results.json",
        workspace / "experiments" / node_id / "results.json",
    ):
        if candidate.is_file() and not candidate.is_symlink():
            return candidate
    return None


def _report_path(
    workspace: Path, checkpoint: Path, run_id: str, node_id: str
) -> Path | None:
    for candidate in (
        workspace / "experiments" / run_id / node_id / "node_report.json",
        workspace / "experiments" / node_id / "node_report.json",
        checkpoint / "experiments" / node_id / "node_report.json",
    ):
        if candidate.is_file() and not candidate.is_symlink():
            return candidate
    return None


def _environment(report: dict[str, Any] | None) -> ScienceEnvironmentV1:
    report = report or {}
    cpu = report.get("cpu_info") if isinstance(report.get("cpu_info"), dict) else {}
    identity = {
        "executor": str(report.get("executor") or ""),
        "hostname": str(report.get("hostname") or ""),
        "cpu_model": str(cpu.get("model") or ""),
        "arch": str(cpu.get("arch") or ""),
        "scheduler_job_id": str(report.get("slurm_job_id") or ""),
        "scheduler_partition": str(report.get("slurm_partition") or ""),
    }
    if any(identity.values()):
        encoded = json.dumps(
            identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        identity["environment_digest"] = "sha256:" + hashlib.sha256(encoded).hexdigest()
    return ScienceEnvironmentV1(**identity)


def _finite_metrics(value: Any) -> dict[str, int | float]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key): number
        for key, number in value.items()
        if isinstance(key, str)
        and key
        and not key.startswith("_")
        and isinstance(number, (int, float))
        and not isinstance(number, bool)
        and math.isfinite(float(number))
    }


def _build_configurations(
    *,
    nodes: list[dict[str, Any]],
    typed_results: dict[str, dict[str, Any]],
    reports: dict[str, dict[str, Any]],
    workspace: Path,
    checkpoint: Path,
    run_id: str,
    tree_ref: ScienceArtifactRefV1,
) -> tuple[ScienceConfigurationV1, ...]:
    configurations: list[ScienceConfigurationV1] = []
    successful = [
        node for node in nodes if node.get("has_real_data") and node.get("metrics")
    ]
    for index, node in enumerate(successful):
        node_id = str(node.get("id") or node.get("node_id") or "")
        if not node_id:
            continue
        typed = typed_results.get(node_id) or {}
        result_path = _result_path(workspace, run_id, node_id)
        report_path = _report_path(workspace, checkpoint, run_id, node_id)
        sources: list[ScienceArtifactRefV1] = [tree_ref]
        if result_path is not None:
            sources.append(artifact_ref(result_path, workspace, role="measurement-set"))
        if report_path is not None and node_id in reports:
            sources.append(artifact_ref(report_path, workspace, role="node-report"))
        records: tuple[MeasurementRecordV1, ...] = ()
        measurements: dict[str, int | float] = {}
        source_kind = "legacy-untyped"
        claim_eligible = False
        if typed and result_path is not None:
            records = tuple(
                MeasurementRecordV1.model_validate(record)
                for record in typed.get("measurement_records") or ()
            )
            measurements = _finite_metrics(typed.get("measurements"))
            if (
                records
                and typed.get("source_schema") == "canonical"
                and all(record.execution_status == "completed" for record in records)
            ):
                source_kind = "typed-measurement"
                claim_eligible = True
            else:
                # Compatibility measurements remain inspectable but cannot be
                # laundered into evidence by merely passing through v1.
                records = ()
                measurements = {}
        configurations.append(
            ScienceConfigurationV1(
                config_id=f"cfg{len(configurations) + 1}",
                run_id=run_id,
                node_id=node_id,
                rank=len(configurations) + 1,
                label=str(node.get("label") or "")[:256],
                source_kind=source_kind,
                claim_eligible=claim_eligible,
                parameters=dict(typed.get("params") or {}) if typed else {},
                measurements=measurements,
                measurement_records=records,
                predictions=dict(typed.get("predictions") or {}) if typed else {},
                scores=dict(typed.get("scores") or {}) if typed else {},
                legacy_metrics=(
                    {} if claim_eligible else _finite_metrics(node.get("metrics"))
                ),
                environment=_environment(reports.get(node_id)),
                source_artifacts=tuple(sources),
                provenance_labels={
                    str(key): str(label)
                    for key, label in (typed.get("_provenance") or {}).items()
                    if key and label
                },
            )
        )
    return tuple(configurations)


def _summary_direction(metric: str, primary_metric: str, higher_is_better: bool) -> str:
    if metric != primary_metric:
        return "unspecified"
    return "higher" if higher_is_better else "lower"


def _metric_unit(
    configurations: tuple[ScienceConfigurationV1, ...], metric: str
) -> str:
    units = {
        record.unit
        for config in configurations
        for record in config.measurement_records
        if record.metric_id == metric and record.unit
    }
    return next(iter(units)) if len(units) == 1 else "unknown"


def _metric_summaries(
    configurations: tuple[ScienceConfigurationV1, ...],
    *,
    primary_metric: str,
    higher_is_better: bool,
) -> tuple[ScienceMetricSummaryV1, ...]:
    keys = sorted(
        {
            metric
            for config in configurations
            if config.claim_eligible
            for metric in config.measurements
        }
    )
    summaries: list[ScienceMetricSummaryV1] = []
    for metric in keys:
        values = [
            (config.config_id, float(config.measurements[metric]))
            for config in configurations
            if config.claim_eligible and metric in config.measurements
        ]
        if not values:
            continue
        numbers = [number for _, number in values]
        direction = _summary_direction(metric, primary_metric, higher_is_better)
        best = min(numbers) if direction == "lower" else max(numbers)
        summaries.append(
            ScienceMetricSummaryV1(
                metric_id=metric,
                unit=_metric_unit(configurations, metric),
                minimum=min(numbers),
                maximum=max(numbers),
                best_value=best,
                count=len(numbers),
                direction=direction,
                source_config_ids=tuple(config_id for config_id, _ in values),
            )
        )
    return tuple(summaries)


def _operand(value: dict[str, Any], run_id: str) -> ScienceOperandV1:
    environment = (
        value.get("environment") if isinstance(value.get("environment"), dict) else {}
    )
    return ScienceOperandV1(
        run_id=str(value.get("run_id") or run_id),
        node_id=str(value.get("node_id") or ""),
        metric_path=str(value.get("metric_path") or ""),
        environment=ScienceEnvironmentV1(
            executor=str(environment.get("executor") or ""),
            cpu_model=str(environment.get("cpu_model") or ""),
            arch=str(environment.get("arch") or ""),
        ),
    )


def _assertion(
    value: dict[str, Any], *, run_id: str, claim_id: str | None
) -> ScienceNumericAssertionV1:
    operands = {
        str(role): _operand(pointer, run_id)
        for role, pointer in (value.get("operands") or {}).items()
        if isinstance(pointer, dict)
    }
    number = value.get("value")
    if isinstance(number, bool) or not isinstance(number, (int, float)):
        raise ValueError("numeric assertion lacks a finite deterministic value")
    return ScienceNumericAssertionV1(
        id=str(value.get("id") or ""),
        claim_id=claim_id,
        text_span=str(value.get("text_span") or "")[:4096],
        metric=str(value.get("metric") or ""),
        value=float(number),
        unit=str(value.get("unit") or "unknown"),
        formula=str(value.get("formula") or ""),
        operands=operands,
        cross_environment=bool(value.get("cross_environment", False)),
        aggregation=dict(value.get("aggregation") or {}),
        tolerance={
            key: float(item)
            for key, item in (value.get("tolerance") or {}).items()
            if key in {"absolute", "relative"}
        },
    )


def _claims(
    projection: dict[str, Any], *, run_id: str
) -> tuple[tuple[ScienceClaimV1, ...], tuple[ScienceNumericAssertionV1, ...]]:
    claims: list[ScienceClaimV1] = []
    flat: list[ScienceNumericAssertionV1] = []
    for value in projection.get("claims") or ():
        if not isinstance(value, dict):
            continue
        claim_id = str(value.get("id") or "")
        evidence = (
            value.get("supported_by")
            if isinstance(value.get("supported_by"), dict)
            else {}
        )
        assertions = tuple(
            _assertion(item, run_id=run_id, claim_id=None)
            for item in value.get("numeric_assertions") or ()
            if isinstance(item, dict)
        )
        results = tuple(
            ScienceEvidenceResultV1(
                run_id=str(item.get("run_id") or run_id),
                node_id=str(item.get("node_id") or ""),
                metric_path=str(item.get("metric_path") or ""),
            )
            for item in evidence.get("results") or ()
            if isinstance(item, dict)
        )
        claims.append(
            ScienceClaimV1(
                id=claim_id,
                text=str(value.get("text") or ""),
                section=str(value.get("section") or "results"),
                status=str(value.get("status") or "draft"),
                supported_by=ScienceClaimEvidenceV1(
                    nodes=tuple(str(node) for node in evidence.get("nodes") or ()),
                    results=results,
                    figures=tuple(
                        str(figure) for figure in evidence.get("figures") or ()
                    ),
                    artifacts=(),
                ),
                numeric_assertions=assertions,
                risk=str(value.get("risk") or ""),
            )
        )
        flat.extend(
            item.model_copy(update={"claim_id": claim_id}) for item in assertions
        )
    return tuple(claims), tuple(flat)


def _optional_known_artifact(
    path: Path, workspace: Path, *, role: str
) -> ScienceArtifactRefV1 | None:
    if not path.is_file() or path.is_symlink():
        return None
    return artifact_ref(path, workspace, role=role)


def build_deterministic_sections(
    *,
    nodes_json_path: str,
    nodes: list[dict[str, Any]],
    reports: dict[str, dict[str, Any]],
    typed_results: dict[str, dict[str, Any]],
    deterministic_projection: dict[str, Any],
    metric_contract: dict[str, Any] | None,
    primary_metric: str,
    higher_is_better: bool,
) -> DeterministicScienceSections:
    workspace, checkpoint, run_id = _workspace_layout(nodes_json_path)
    tree_path = Path(nodes_json_path).expanduser().resolve(strict=True)
    tree_ref = artifact_ref(tree_path, workspace, role="experiment-tree")
    configurations = _build_configurations(
        nodes=nodes,
        typed_results=typed_results,
        reports=reports,
        workspace=workspace,
        checkpoint=checkpoint,
        run_id=run_id,
        tree_ref=tree_ref,
    )
    if not configurations:
        raise ValueError("no successful configuration can be materialized")
    report_count = sum(1 for config in configurations if config.node_id in reports)
    typed_count = sum(1 for config in configurations if config.claim_eligible)
    raw = ScienceRawV1.create(
        tree_artifact=tree_ref,
        configurations=configurations,
        node_report_status=(
            "complete"
            if report_count == len(configurations)
            else "partial"
            if report_count
            else "missing"
        ),
        measurement_status=(
            "complete"
            if typed_count == len(configurations)
            else "partial"
            if typed_count
            else "missing"
        ),
    )
    claims, assertions = _claims(deterministic_projection, run_id=run_id)
    summaries = _metric_summaries(
        configurations,
        primary_metric=primary_metric,
        higher_is_better=higher_is_better,
    )
    summary_stats = dict(deterministic_projection.get("summary_stats") or {})
    # A best value can only be claimable when it came from typed measurements.
    primary_summary = next(
        (summary for summary in summaries if summary.metric_id == primary_metric), None
    )
    if primary_summary is None:
        summary_stats.pop("primary_metric_best", None)
        summary_stats.pop("primary_metric_n", None)
    else:
        summary_stats["primary_metric_best"] = primary_summary.best_value
        summary_stats["primary_metric_n"] = primary_summary.count
    derived = ScienceDerivedV1.create(
        formula_registry_digest=formula_registry_digest(),
        metric_summaries=summaries,
        summary_stats=summary_stats,
        claims=claims,
        numeric_assertions=assertions,
        anomalies=tuple(deterministic_projection.get("_anomalies") or ()),
    )
    skills_lock = _optional_known_artifact(
        checkpoint / "SKILLS.lock", workspace, role="skills-lock"
    )
    catalog_lock = _optional_known_artifact(
        checkpoint / "CATALOG.lock", workspace, role="catalog-lock"
    ) or _optional_known_artifact(
        checkpoint / "catalog" / "CATALOG.lock", workspace, role="catalog-lock"
    )
    admission: list[ScienceArtifactRefV1] = []
    cassettes: list[ScienceArtifactRefV1] = []
    for relative, role, destination in (
        ("catalog/catalog-provenance.json", "catalog-admission", admission),
        ("openroad/admission.json", "domain-admission", admission),
        ("qiskit/admission.json", "domain-admission", admission),
        ("catalog/cassette-index.json", "cassette-index", cassettes),
    ):
        item = _optional_known_artifact(checkpoint / relative, workspace, role=role)
        if item is not None:
            destination.append(item)
    all_inputs = {tree_ref.digest: tree_ref}
    for config in configurations:
        for source in config.source_artifacts:
            all_inputs[source.digest] = source
    provenance = ScienceProvenanceV1(
        producer_tool_ref=PRODUCER_TOOL_REF,
        producer_version=PRODUCER_VERSION,
        input_artifacts=tuple(
            sorted(all_inputs.values(), key=lambda item: item.relative_path)
        ),
        skills_lock=skills_lock,
        catalog_lock=catalog_lock,
        admission_artifacts=tuple(admission),
        cassette_artifacts=tuple(cassettes),
    )
    limitations: list[str] = []
    if report_count != len(configurations):
        limitations.append(
            "One or more node reports are missing; no trace/source scan was used as a substitute."
        )
    if typed_count != len(configurations):
        limitations.append(
            "Untyped node metrics are retained for inspection but are not claim eligible."
        )
    return DeterministicScienceSections(
        run_id=run_id,
        raw=raw,
        derived=derived,
        metric_contract=metric_contract,
        limitations=tuple(limitations),
        provenance=provenance,
    )


def assemble_science_data(
    sections: DeterministicScienceSections,
    interpretation: ScienceInterpretationV1,
) -> ScienceDataV1:
    return ScienceDataV1.create(
        run_id=sections.run_id,
        raw=sections.raw,
        derived=sections.derived,
        interpretation=interpretation,
        metric_contract=sections.metric_contract,
        limitations=sections.limitations,
        provenance=sections.provenance,
        migration_status="native-v1",
    )


__all__ = [
    "DeterministicScienceSections",
    "artifact_ref",
    "assemble_science_data",
    "build_deterministic_sections",
]
