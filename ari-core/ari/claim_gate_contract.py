"""Canonical contracts for metric admission and claim/evidence evaluation.

The evaluator Skill is a transport boundary.  Scientific identity, report
shape, and digest verification live here so idea, transform, evaluator, paper,
and offline readers all consume the same models.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from ari.research_contract import (
    SHA256_DIGEST_PATTERN,
    MetricContractV1,
    MetricCorrectnessV1,
    MetricFormulaProvenanceV1,
    MetricToleranceV1,
    canonical_digest,
)


METRIC_GATE_CONTRACT_V1 = "ari.metric-gate-contract/v1"
METRIC_CONTRACT_PROPOSAL_V1 = "ari.metric-contract-proposal/v1"
METRIC_ADMISSION_DECISION_V1 = "ari.metric-admission-decision/v1"
GATE_FINDING_V1 = "ari.gate-finding/v1"
GATE_REPORT_V1 = "ari.gate-report/v1"
SEMANTIC_REVIEW_V1 = "ari.semantic-review/v1"

_ZERO_DIGEST = "sha256:" + ("0" * 64)
_SAFE_CODE = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")


class ClaimGateContractError(ValueError):
    """A gate, proposal, or review document is malformed or was changed."""


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _DigestBoundModel(_StrictModel):
    _digest_field: ClassVar[str]

    @classmethod
    def create(cls, **values: Any):
        values[cls._digest_field] = _ZERO_DIGEST
        return cls.model_validate(values, context={"bind_claim_gate_digest": True})

    def digest_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={self._digest_field})

    @model_validator(mode="after")
    def _digest_matches(self, info: ValidationInfo):
        expected = canonical_digest(self.digest_payload())
        if info.context and info.context.get("bind_claim_gate_digest"):
            object.__setattr__(self, self._digest_field, expected)
        elif getattr(self, self._digest_field) != expected:
            raise ValueError(
                f"{self._digest_field} does not match the canonical payload"
            )
        return self


class MetricClaimV1(_StrictModel):
    claim: str = Field(min_length=1, max_length=10_000)
    required_evidence: tuple[str, ...] = Field(min_length=1, max_length=128)

    @field_validator("required_evidence")
    @classmethod
    def _unique_evidence(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(item.strip() for item in value if item.strip())
        if not normalized or len(normalized) != len(set(normalized)):
            raise ValueError("claim evidence must be non-empty and unique")
        return normalized


class MetricGateContractV1(_DigestBoundModel):
    """Evaluator projection of one immutable idea-owned metric contract."""

    _digest_field = "projection_digest"

    schema_version: Literal["ari.metric-gate-contract/v1"] = (
        METRIC_GATE_CONTRACT_V1
    )
    projection_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    source: Literal["research-contract", "human-admitted", "legacy-migrated"]
    source_idea_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    research_contract_digest: str | None = Field(
        default=None, pattern=SHA256_DIGEST_PATTERN
    )
    metric_contract: MetricContractV1
    claims: tuple[MetricClaimV1, ...] = Field(default_factory=tuple, max_length=128)

    @model_validator(mode="after")
    def _source_binding(self):
        if self.source == "research-contract" and self.research_contract_digest is None:
            raise ValueError("research-contract projection requires its digest")
        if self.source != "research-contract" and self.research_contract_digest is not None:
            raise ValueError("only research-contract projections carry its digest")
        return self

    def gate_projection(self) -> dict[str, Any]:
        """Return the single compatibility view consumed by gate mathematics."""

        metric = self.metric_contract
        return {
            "schema_version": self.schema_version,
            "projection_digest": self.projection_digest,
            "research_contract_digest": self.research_contract_digest,
            "metric_contract_digest": metric.contract_digest,
            "key": metric.name,
            "unit": metric.unit,
            "direction": metric.direction,
            "comparison_scope": metric.comparison_scope,
            "formula": metric.formula,
            "formula_operands": dict(metric.operands),
            "formula_provenance": metric.formula_provenance.model_dump(mode="json"),
            "tolerance": metric.tolerance.model_dump(mode="json"),
            "claims": [item.model_dump(mode="json") for item in self.claims],
            "correctness_required": metric.correctness_required,
            "ceiling_must_be_measured": metric.normalization_ceiling == "measured",
            "required_measured": list(metric.required_measured),
            "invariants": list(metric.invariants),
            "correctness": (
                metric.correctness.model_dump(mode="json")
                if metric.correctness is not None
                else {}
            ),
        }


class MetricContractProposalV1(_DigestBoundModel):
    """Untrusted LLM suggestion; never an admitted scientific contract."""

    _digest_field = "proposal_digest"

    schema_version: Literal["ari.metric-contract-proposal/v1"] = (
        METRIC_CONTRACT_PROPOSAL_V1
    )
    proposal_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    source_idea_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    evidence_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    model: str = Field(min_length=1, max_length=512)
    model_revision: str | None = Field(default=None, max_length=512)
    prompt_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    proposed_contract: dict[str, Any]
    confidence: float = Field(ge=0, le=1)
    requires_human_review: Literal[True] = True

    @field_validator("proposed_contract")
    @classmethod
    def _finite_proposal(cls, value: dict[str, Any]) -> dict[str, Any]:
        try:
            json.dumps(value, sort_keys=True, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("proposal must be finite JSON") from exc
        return value


class MetricAdmissionDecisionV1(_DigestBoundModel):
    _digest_field = "decision_digest"

    schema_version: Literal["ari.metric-admission-decision/v1"] = (
        METRIC_ADMISSION_DECISION_V1
    )
    decision_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    proposal_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    decision: Literal["admitted", "review-required", "rejected"]
    reviewer: str | None = Field(default=None, max_length=512)
    reasons: tuple[str, ...] = Field(min_length=1, max_length=64)
    admitted_contract_digest: str | None = Field(
        default=None, pattern=SHA256_DIGEST_PATTERN
    )

    @model_validator(mode="after")
    def _admission_is_explicit(self):
        if self.decision == "admitted":
            if not self.reviewer or not self.admitted_contract_digest:
                raise ValueError("admission requires reviewer and contract digest")
        elif self.admitted_contract_digest is not None:
            raise ValueError("non-admission cannot carry an admitted contract")
        return self


class GateFindingV1(_StrictModel):
    schema_version: Literal["ari.gate-finding/v1"] = GATE_FINDING_V1
    severity: Literal["blocking", "advisory"]
    type: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=20_000)
    claim_id: str | None = Field(default=None, max_length=512)
    numeric_id: str | None = Field(default=None, max_length=512)
    node_id: str | None = Field(default=None, max_length=512)
    artifact_path: str | None = Field(default=None, max_length=4096)
    details: dict[str, Any] = Field(default_factory=dict)

    @field_validator("type")
    @classmethod
    def _finding_code(cls, value: str) -> str:
        if not _SAFE_CODE.fullmatch(value):
            raise ValueError("finding type must be a stable lowercase code")
        return value

    @field_validator("details")
    @classmethod
    def _finite_details(cls, value: dict[str, Any]) -> dict[str, Any]:
        try:
            json.dumps(value, sort_keys=True, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("finding details must be finite JSON") from exc
        return value


class GateFormulaProvenanceV1(_StrictModel):
    registry_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    formulas_used: tuple[str, ...] = Field(default_factory=tuple, max_length=1_000)
    metric_contract_digest: str | None = Field(
        default=None, pattern=SHA256_DIGEST_PATTERN
    )
    unit_conversions: tuple[str, ...] = Field(default_factory=tuple, max_length=128)


class GateReportV1(_DigestBoundModel):
    """Deterministic hard-gate result with typed finding separation."""

    _digest_field = "report_digest"

    schema_version: Literal["ari.gate-report/v1"] = GATE_REPORT_V1
    report_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    gate: Literal["claim_evidence_hard_gate"] = "claim_evidence_hard_gate"
    source_run_id: str = Field(min_length=1, max_length=512)
    phase: Literal["draft", "final"]
    policy_mode: Literal["off", "warn", "strict"]
    comparison_scope: Literal["any", "same_environment"]
    status: Literal["passed", "warn", "failed"]
    should_block: bool
    policy_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    evidence_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    formula_provenance: GateFormulaProvenanceV1
    blocking_findings: tuple[GateFindingV1, ...] = Field(default_factory=tuple)
    advisory_findings: tuple[GateFindingV1, ...] = Field(default_factory=tuple)
    metrics: dict[str, int | float]

    @field_validator("metrics")
    @classmethod
    def _finite_metrics(cls, value: dict[str, int | float]):
        if any(
            isinstance(item, bool) or not math.isfinite(float(item))
            for item in value.values()
        ):
            raise ValueError("gate metrics must be finite numbers")
        return value

    @model_validator(mode="after")
    def _outcome_consistency(self):
        if any(item.severity != "blocking" for item in self.blocking_findings):
            raise ValueError("blocking_findings contains a non-blocking finding")
        if any(item.severity != "advisory" for item in self.advisory_findings):
            raise ValueError("advisory_findings contains a non-advisory finding")
        if self.should_block and (
            self.phase != "final"
            or self.policy_mode == "off"
            or not self.blocking_findings
        ):
            raise ValueError("gate cannot block in this phase/policy/outcome")
        if self.status == "passed" and (
            self.blocking_findings or self.advisory_findings
        ):
            raise ValueError("passed gate cannot contain findings")
        if self.status == "failed" and not self.blocking_findings:
            raise ValueError("failed gate requires a blocking finding")
        return self


class SemanticFindingV1(_StrictModel):
    type: Literal[
        "overclaim",
        "overgeneralization",
        "unsupported_claim",
        "interpretation",
        "visual_semantics",
    ]
    section: str = Field(min_length=1, max_length=256)
    message: str = Field(min_length=1, max_length=20_000)


class SemanticRevisionV1(_StrictModel):
    section: str = Field(min_length=1, max_length=256)
    instruction: str = Field(min_length=1, max_length=20_000)


class SemanticReviewV1(_DigestBoundModel):
    """Advisory review whose provenance cannot mutate the hard-gate result."""

    _digest_field = "review_digest"

    schema_version: Literal["ari.semantic-review/v1"] = SEMANTIC_REVIEW_V1
    review_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    stage: Literal["evidence_grounded_semantic_review"] = (
        "evidence_grounded_semantic_review"
    )
    phase: str = Field(min_length=1, max_length=128)
    status: Literal["ok", "revise", "unavailable"]
    model: str = Field(min_length=1, max_length=512)
    model_revision: str | None = Field(default=None, max_length=512)
    prompt_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    evidence_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    hard_gate_report_digest: str | None = Field(
        default=None, pattern=SHA256_DIGEST_PATTERN
    )
    scores: dict[str, float] = Field(default_factory=dict)
    findings: tuple[SemanticFindingV1, ...] = Field(default_factory=tuple)
    suggested_revisions: tuple[SemanticRevisionV1, ...] = Field(default_factory=tuple)
    detected_overclaim_count: int = Field(ge=0)
    previous_review_digest: str | None = Field(
        default=None, pattern=SHA256_DIGEST_PATTERN
    )
    score_delta: float | None = None
    resolved_overclaim_count: int = 0
    human_verified_overclaim_precision: float | None = Field(
        default=None, ge=0, le=1
    )
    note: str | None = Field(default=None, max_length=20_000)

    @field_validator("scores")
    @classmethod
    def _bounded_scores(cls, value: dict[str, float]) -> dict[str, float]:
        if any(not math.isfinite(float(item)) or not 0 <= float(item) <= 1 for item in value.values()):
            raise ValueError("semantic-review scores must be finite values in [0, 1]")
        return value


def parse_metric_gate_contract(document: dict[str, Any]) -> MetricGateContractV1:
    try:
        return MetricGateContractV1.model_validate(document)
    except Exception as exc:
        raise ClaimGateContractError(f"invalid metric gate contract: {exc}") from exc


def parse_gate_report(document: dict[str, Any]) -> GateReportV1:
    try:
        return GateReportV1.model_validate(document)
    except Exception as exc:
        raise ClaimGateContractError(f"invalid gate report: {exc}") from exc


_LEGACY_FINDING_FIELDS = {
    "type",
    "message",
    "claim_id",
    "numeric_id",
    "node_id",
    "artifact_path",
}


def _legacy_gate_findings(
    document: dict[str, Any], key: str, severity: str
) -> tuple[GateFindingV1, ...]:
    raw_items = document.get(key) or ()
    if not isinstance(raw_items, (list, tuple)):
        raise ClaimGateContractError(f"legacy {key} must be a list")
    migrated: list[GateFindingV1] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            raise ClaimGateContractError(f"legacy {key} contains a non-object")
        finding_type = str(raw.get("type") or "legacy_untyped_finding")
        optional = {
            name: (str(raw[name]) if raw.get(name) is not None else None)
            for name in ("claim_id", "numeric_id", "node_id", "artifact_path")
        }
        try:
            migrated.append(
                GateFindingV1(
                    severity=severity,
                    type=finding_type,
                    message=str(raw.get("message") or finding_type),
                    **optional,
                    details={
                        name: value
                        for name, value in raw.items()
                        if name not in _LEGACY_FINDING_FIELDS
                    },
                )
            )
        except Exception as exc:
            raise ClaimGateContractError(
                f"invalid legacy {key} finding: {exc}"
            ) from exc
    return tuple(migrated)


def migrate_legacy_gate_report(
    document: dict[str, Any], *, source_run_id: str
) -> GateReportV1:
    """Read a pre-v1 gate report without pretending it was fully replayable.

    Old reports did not record policy, evidence, or formula implementation
    digests.  The migration therefore binds each unknown provenance field to a
    digest of an explicit legacy marker plus the exact old document.  It never
    rewrites the published report on disk and never upgrades its findings.
    """

    if not isinstance(document, dict) or not document:
        raise ClaimGateContractError("legacy gate report must be an object")
    if document.get("schema_version") == GATE_REPORT_V1:
        return parse_gate_report(document)
    if document.get("gate") != "claim_evidence_hard_gate":
        raise ClaimGateContractError("unrecognized legacy gate report")
    source_run_id = source_run_id.strip()
    if not source_run_id:
        raise ClaimGateContractError("legacy gate report needs its source run id")

    phase = document.get("phase")
    policy_mode = document.get("policy_mode", document.get("policy"))
    if phase not in {"draft", "final"}:
        raise ClaimGateContractError("legacy gate report has an invalid phase")
    if policy_mode not in {"off", "warn", "strict"}:
        raise ClaimGateContractError("legacy gate report has an invalid policy mode")

    blocking = _legacy_gate_findings(document, "errors", "blocking")
    advisory = _legacy_gate_findings(document, "warnings", "advisory")
    status = "failed" if blocking else ("warn" if advisory else "passed")
    should_block = bool(document.get("should_block"))
    if should_block and (phase != "final" or policy_mode == "off" or not blocking):
        raise ClaimGateContractError("legacy gate report has an impossible block state")
    comparison_scope = document.get("comparison_scope", "any")
    if comparison_scope not in {"any", "same_environment"}:
        raise ClaimGateContractError("legacy gate report has an invalid comparison scope")
    raw_metrics = document.get("metrics") or {}
    if not isinstance(raw_metrics, dict):
        raise ClaimGateContractError("legacy gate report metrics must be an object")

    legacy_digest = canonical_digest(document)
    marker = {"format": "pre-ari.gate-report/v1", "document": legacy_digest}
    try:
        return GateReportV1.create(
            source_run_id=source_run_id,
            phase=phase,
            policy_mode=policy_mode,
            comparison_scope=comparison_scope,
            status=status,
            should_block=should_block,
            policy_digest=canonical_digest({**marker, "unknown": "policy"}),
            evidence_digest=canonical_digest({**marker, "unknown": "evidence"}),
            formula_provenance=GateFormulaProvenanceV1(
                registry_digest=canonical_digest(
                    {**marker, "unknown": "formula-registry"}
                ),
                formulas_used=("legacy-unrecorded",),
            ),
            blocking_findings=blocking,
            advisory_findings=advisory,
            metrics=raw_metrics,
        )
    except Exception as exc:
        raise ClaimGateContractError(f"invalid legacy gate report: {exc}") from exc


def parse_semantic_review(document: dict[str, Any]) -> SemanticReviewV1:
    try:
        return SemanticReviewV1.model_validate(document)
    except Exception as exc:
        raise ClaimGateContractError(f"invalid semantic review: {exc}") from exc


def migrate_legacy_metric_gate_contract(
    document: dict[str, Any], *, source_idea_digest: str | None = None
) -> MetricGateContractV1:
    """Conservatively read one pre-v1 metric-gate document.

    This is a read/migration boundary, never an admission shortcut.  A missing
    metric name or unit is rejected instead of guessed, and the resulting
    contract remains ``human-review-required`` with legacy provenance.
    """

    if not isinstance(document, dict) or not document:
        raise ClaimGateContractError("legacy metric contract must be an object")
    if document.get("schema_version") == METRIC_GATE_CONTRACT_V1:
        return parse_metric_gate_contract(document)
    key = str(document.get("key") or document.get("name") or "").strip()
    unit = str(document.get("unit") or "").strip()
    if not key or not unit:
        raise ClaimGateContractError(
            "legacy metric contract needs an explicit metric name and unit"
        )
    raw_claims = document.get("claims") or []
    claims: list[MetricClaimV1] = []
    evidence: list[str] = [key]
    for raw in raw_claims:
        if not isinstance(raw, dict):
            continue
        required = tuple(
            str(item).strip()
            for item in raw.get("required_evidence") or ()
            if str(item).strip()
        )
        claim = str(raw.get("claim") or "").strip()
        if claim and required:
            claims.append(MetricClaimV1(claim=claim, required_evidence=required))
            evidence.extend(required)
    evidence = list(dict.fromkeys(evidence))
    formula = str(document.get("formula") or "value").strip()
    operands = document.get("formula_operands") or document.get("operands")
    if not isinstance(operands, dict):
        operands = {"value": key}
    tolerance_raw = document.get("tolerance") or {
        "absolute": 0.0,
        "relative": 0.02,
    }
    if not isinstance(tolerance_raw, dict):
        raise ClaimGateContractError("legacy tolerance must be an object")
    correctness_raw = document.get("correctness") or None
    correctness = None
    if isinstance(correctness_raw, dict) and correctness_raw:
        correctness = MetricCorrectnessV1(
            expr=str(correctness_raw.get("expr") or "").strip(),
            requires=tuple(correctness_raw.get("requires") or ()),
        )
    source_digest = canonical_digest(document)
    metric = MetricContractV1.create(
        name=key,
        unit=unit,
        direction=document.get("direction") or "none",
        comparison_scope=document.get("comparison_scope") or "not-applicable",
        rationale=str(document.get("rationale") or "Legacy contract; human review required."),
        required_evidence=tuple(evidence),
        correctness_required=bool(document.get("correctness_required")),
        normalization_ceiling=(
            "measured" if document.get("ceiling_must_be_measured") else "not-applicable"
        ),
        target_value=document.get("target_value"),
        formula=formula,
        operands={str(role): str(name) for role, name in operands.items()},
        tolerance=MetricToleranceV1(
            absolute=tolerance_raw.get("absolute", 0.0),
            relative=tolerance_raw.get("relative", 0.02),
        ),
        formula_provenance=MetricFormulaProvenanceV1(
            source="legacy-migration",
            source_digest=source_digest,
        ),
        required_measured=tuple(document.get("required_measured") or ()),
        invariants=tuple(document.get("invariants") or ()),
        correctness=correctness,
        confidence=0.0,
        admission_status="human-review-required",
    )
    return MetricGateContractV1.create(
        source="legacy-migrated",
        source_idea_digest=source_idea_digest or source_digest,
        metric_contract=metric,
        claims=tuple(claims),
    )


def admit_metric_contract_proposal(
    proposal: MetricContractProposalV1, *, reviewer: str
) -> tuple[MetricGateContractV1, MetricAdmissionDecisionV1]:
    """Human-admit an exact proposal; all scientific fields remain unchanged."""

    reviewer = reviewer.strip()
    if not reviewer:
        raise ClaimGateContractError("metric admission requires a reviewer identity")
    raw = dict(proposal.proposed_contract)
    raw.pop("contract_digest", None)
    raw.pop("schema_version", None)
    raw_claims = raw.pop("claims", ())
    raw["formula_provenance"] = MetricFormulaProvenanceV1(
        source="human-admission",
        source_digest=proposal.proposal_digest,
        model=proposal.model,
        prompt_digests=(proposal.prompt_digest,),
    )
    raw["confidence"] = proposal.confidence
    raw["admission_status"] = "admitted"
    try:
        metric = MetricContractV1.create(**raw)
    except Exception as exc:
        raise ClaimGateContractError(f"proposal cannot be admitted: {exc}") from exc
    claims = tuple(MetricClaimV1.model_validate(item) for item in raw_claims)
    projection = MetricGateContractV1.create(
        source="human-admitted",
        source_idea_digest=proposal.source_idea_digest,
        metric_contract=metric,
        claims=claims,
    )
    decision = MetricAdmissionDecisionV1.create(
        proposal_digest=proposal.proposal_digest,
        decision="admitted",
        reviewer=reviewer,
        reasons=("explicit-human-confirmation",),
        admitted_contract_digest=metric.contract_digest,
    )
    return projection, decision


__all__ = [
    "GATE_FINDING_V1",
    "GATE_REPORT_V1",
    "METRIC_ADMISSION_DECISION_V1",
    "METRIC_CONTRACT_PROPOSAL_V1",
    "METRIC_GATE_CONTRACT_V1",
    "SEMANTIC_REVIEW_V1",
    "ClaimGateContractError",
    "GateFindingV1",
    "GateFormulaProvenanceV1",
    "GateReportV1",
    "MetricAdmissionDecisionV1",
    "MetricClaimV1",
    "MetricContractProposalV1",
    "MetricGateContractV1",
    "SemanticFindingV1",
    "SemanticReviewV1",
    "SemanticRevisionV1",
    "parse_gate_report",
    "parse_metric_gate_contract",
    "parse_semantic_review",
    "admit_metric_contract_proposal",
    "migrate_legacy_gate_report",
    "migrate_legacy_metric_gate_contract",
]
