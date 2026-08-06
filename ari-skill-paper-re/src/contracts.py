"""Immutable scientific contracts for reproduction execution and grading."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, model_validator


REPRODUCTION_PLAN_V1 = "ari.reproduction-plan/v1"
REPRODUCTION_ATTEMPT_V1 = "ari.reproduction-attempt/v1"
REPRODUCTION_RUN_V1 = "ari.reproduction-run/v1"
GRADE_REPORT_V1 = "ari.reproduction-grade-report/v1"
REPRODUCTION_ARTIFACT_V1 = "ari.reproduction-artifact/v1"
ZERO_DIGEST = "sha256:" + "0" * 64
_DIGEST_RE = re.compile(r"^sha256:[a-f0-9]{64}$")


class ReproductionContractError(ValueError):
    """A reproduction record is malformed, inconsistent, or tampered with."""


def canonical_digest(value: Any) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    try:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ReproductionContractError("contract payload must be finite JSON") from exc
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def bytes_digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def safe_relative_path(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("artifact path must be safe and relative")
    return path.as_posix()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DigestBoundModel(StrictModel):
    digest_field: ClassVar[str]

    @classmethod
    def create(cls, **values: Any):
        values = dict(values)
        values[cls.digest_field] = ZERO_DIGEST
        return cls.model_validate(values, context={"bind_digest": True})

    def digest_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={self.digest_field})

    @model_validator(mode="after")
    def _digest_matches(self, info: ValidationInfo):
        expected = canonical_digest(self.digest_payload())
        if info.context and info.context.get("bind_digest"):
            object.__setattr__(self, self.digest_field, expected)
        elif getattr(self, self.digest_field) != expected:
            raise ValueError(f"{self.digest_field} does not match canonical payload")
        return self


class ReproductionArtifactV1(StrictModel):
    schema_version: Literal["ari.reproduction-artifact/v1"] = REPRODUCTION_ARTIFACT_V1
    relative_path: str
    digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    size_bytes: int = Field(ge=0)
    media_type: str = Field(min_length=1, max_length=128)
    role: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def _safe_path(self) -> "ReproductionArtifactV1":
        safe_relative_path(self.relative_path)
        return self


class SandboxImageV1(StrictModel):
    runtime: Literal["docker", "apptainer", "singularity"]
    reference: str = Field(min_length=1, max_length=4096)
    digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")


class ReproductionPolicyV1(StrictModel):
    network: Literal["deny", "inherit"] = "deny"
    network_enforcement: Literal[
        "container-namespace", "administrator-attested", "unverified"
    ]
    credential_policy: Literal["none"] = "none"
    input_policy: Literal["content-addressed-read-only"] = "content-addressed-read-only"
    output_policy: Literal["private-attempt-diff"] = "private-attempt-diff"

    @model_validator(mode="after")
    def _network_claim_is_honest(self) -> "ReproductionPolicyV1":
        if self.network == "deny" and self.network_enforcement == "unverified":
            raise ValueError("network denial requires verified enforcement")
        if self.network == "inherit" and self.network_enforcement != "unverified":
            raise ValueError("inherited network cannot claim isolation")
        return self


class ReproductionPlanV1(DigestBoundModel):
    digest_field: ClassVar[str] = "plan_digest"
    schema_version: Literal["ari.reproduction-plan/v1"] = REPRODUCTION_PLAN_V1
    rubric_schema_version: str = Field(min_length=1, max_length=128)
    rubric_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    source_workspace: str = Field(min_length=1, max_length=4096)
    input_tree_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    script_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    argv: tuple[str, ...] = Field(min_length=1, max_length=64)
    sandbox: Literal["local", "docker", "apptainer", "singularity", "slurm"]
    image: SandboxImageV1 | None = None
    timeout_seconds: int = Field(ge=1, le=43_200)
    expected_artifacts: tuple[str, ...] = ()
    policy: ReproductionPolicyV1
    resources: dict[str, Any] = Field(default_factory=dict)
    plan_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")

    @model_validator(mode="after")
    def _coherent_plan(self) -> "ReproductionPlanV1":
        for path in self.expected_artifacts:
            safe_relative_path(path)
        if len(self.expected_artifacts) != len(set(self.expected_artifacts)):
            raise ValueError("expected artifacts must be unique")
        container_substrates = {"docker", "apptainer", "singularity"}
        if (self.sandbox in container_substrates) != (self.image is not None):
            raise ValueError("container sandbox and immutable image must be paired")
        if (
            self.policy.network == "deny"
            and self.sandbox in container_substrates
            and self.policy.network_enforcement != "container-namespace"
        ):
            raise ValueError("container network denial must use its namespace")
        return self


class FailureEvidenceV1(StrictModel):
    kind: Literal[
        "timeout",
        "cancelled",
        "oom",
        "missing-dependency",
        "gpu-mismatch",
        "filesystem-policy",
        "process-exit",
        "sandbox-unavailable",
        "network-policy",
        "scheduler-failure",
        "unknown",
    ]
    message: str = Field(min_length=1, max_length=4096)


class ReproductionAttemptV1(DigestBoundModel):
    digest_field: ClassVar[str] = "attempt_digest"
    schema_version: Literal["ari.reproduction-attempt/v1"] = REPRODUCTION_ATTEMPT_V1
    attempt_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    ordinal: int = Field(ge=1)
    parent_attempt_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    plan_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    status: Literal["succeeded", "failed", "timed_out", "cancelled"]
    started_at: str
    completed_at: str
    exit_code: int | None = None
    execution_identity: str | None = Field(
        default=None, pattern=r"^sha256:[a-f0-9]{64}$"
    )
    substrate_request_digest: str | None = Field(
        default=None, pattern=r"^sha256:[a-f0-9]{64}$"
    )
    environment: dict[str, Any]
    log_artifact: ReproductionArtifactV1
    output_manifest: ReproductionArtifactV1
    output_tree_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    expected_missing: tuple[str, ...] = ()
    failure: FailureEvidenceV1 | None = None
    attempt_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")

    @model_validator(mode="after")
    def _terminal_state_is_coherent(self) -> "ReproductionAttemptV1":
        for path in self.expected_missing:
            safe_relative_path(path)
        if self.status == "succeeded" and (self.exit_code != 0 or self.failure):
            raise ValueError("successful attempt cannot carry failure evidence")
        if self.status != "succeeded" and self.failure is None:
            raise ValueError("unsuccessful attempt requires failure evidence")
        return self


class ReproductionRunV1(DigestBoundModel):
    digest_field: ClassVar[str] = "run_digest"
    schema_version: Literal["ari.reproduction-run/v1"] = REPRODUCTION_RUN_V1
    plan: ReproductionPlanV1
    attempts: tuple[ReproductionAttemptV1, ...] = Field(min_length=1)
    status: Literal["succeeded", "failed", "timed_out", "cancelled"]
    selected_attempt_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    run_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")

    @model_validator(mode="after")
    def _lineage_is_coherent(self) -> "ReproductionRunV1":
        ordinals = [attempt.ordinal for attempt in self.attempts]
        if ordinals != list(range(1, len(ordinals) + 1)):
            raise ValueError("attempt ordinals must be contiguous")
        if any(
            attempt.plan_digest != self.plan.plan_digest for attempt in self.attempts
        ):
            raise ValueError("attempt is bound to another plan")
        if self.status == "succeeded":
            matches = [
                attempt
                for attempt in self.attempts
                if attempt.attempt_id == self.selected_attempt_id
            ]
            if len(matches) != 1 or matches[0].status != "succeeded":
                raise ValueError("successful run must select one successful attempt")
        elif self.selected_attempt_id is not None:
            raise ValueError("failed run cannot select a successful attempt")
        return self


class JudgeIdentityV1(StrictModel):
    model: str = Field(min_length=1, max_length=512)
    provider: str = Field(min_length=1, max_length=128)
    model_revision: str | None = Field(default=None, max_length=512)


class LeafGradeEvidenceV1(StrictModel):
    leaf_id: str = Field(min_length=1, max_length=128)
    requirements: str = Field(min_length=1)
    score: float = Field(ge=0.0, le=1.0)
    valid_score: bool
    explanation: str
    verification: dict[str, Any] | None = None
    run_scores: tuple[float, ...] = ()
    raw_response_artifacts: tuple[ReproductionArtifactV1, ...] = ()


class NegativeControlV1(StrictModel):
    status: Literal["passed", "failed", "unavailable"]
    empty_score: float | None = Field(default=None, ge=0.0, le=1.0)
    boilerplate_score: float | None = Field(default=None, ge=0.0, le=1.0)
    threshold: float = Field(default=0.05, ge=0.0, le=1.0)
    error: str | None = Field(default=None, max_length=4096)


class GradeReportV1(DigestBoundModel):
    digest_field: ClassVar[str] = "report_digest"
    schema_version: Literal["ari.reproduction-grade-report/v1"] = GRADE_REPORT_V1
    rubric_schema_version: str
    rubric_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    paper_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    reproduction_run_digest: str | None = Field(
        default=None, pattern=r"^sha256:[a-f0-9]{64}$"
    )
    reproduction_status: Literal[
        "succeeded", "failed", "timed_out", "cancelled", "unavailable"
    ]
    judge: JudgeIdentityV1
    independence_status: Literal["independent-model", "not-independent"]
    n_runs_requested: int = Field(ge=1, le=100)
    n_runs_completed: int = Field(ge=0, le=100)
    status: Literal["valid", "invalid-negative-control", "failed"]
    ors_score: float | None = Field(default=None, ge=0.0, le=1.0)
    raw_score: float | None = Field(default=None, ge=0.0, le=1.0)
    score_stddev: float | None = Field(default=None, ge=0.0)
    leaves: tuple[LeafGradeEvidenceV1, ...]
    negative_control: NegativeControlV1
    call_artifacts: tuple[ReproductionArtifactV1, ...]
    errors: tuple[str, ...] = ()
    report_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")

    @model_validator(mode="after")
    def _grade_state_is_coherent(self) -> "GradeReportV1":
        if self.status == "failed":
            if self.ors_score is not None or self.raw_score is not None:
                raise ValueError("failed grading cannot publish a scientific score")
            if not self.errors:
                raise ValueError("failed grading requires explicit errors")
        elif (
            self.ors_score is None
            or self.raw_score is None
            or self.n_runs_completed != self.n_runs_requested
        ):
            raise ValueError("published score requires every requested judge run")
        if self.status == "valid" and self.negative_control.status != "passed":
            raise ValueError("valid grade requires passing negative controls")
        return self


def artifact_from_path(
    path: Path,
    *,
    base: Path,
    role: str,
    media_type: str = "application/json",
) -> ReproductionArtifactV1:
    resolved_base = base.resolve()
    resolved = path.resolve(strict=True)
    try:
        relative = resolved.relative_to(resolved_base).as_posix()
    except ValueError as exc:
        raise ReproductionContractError("artifact escapes its declared base") from exc
    payload = resolved.read_bytes()
    return ReproductionArtifactV1(
        relative_path=relative,
        digest=bytes_digest(payload),
        size_bytes=len(payload),
        media_type=media_type,
        role=role,
    )


__all__ = [
    "GRADE_REPORT_V1",
    "REPRODUCTION_ATTEMPT_V1",
    "REPRODUCTION_PLAN_V1",
    "REPRODUCTION_RUN_V1",
    "FailureEvidenceV1",
    "GradeReportV1",
    "JudgeIdentityV1",
    "LeafGradeEvidenceV1",
    "NegativeControlV1",
    "ReproductionArtifactV1",
    "ReproductionAttemptV1",
    "ReproductionContractError",
    "ReproductionPlanV1",
    "ReproductionPolicyV1",
    "ReproductionRunV1",
    "SandboxImageV1",
    "artifact_from_path",
    "bytes_digest",
    "canonical_digest",
    "safe_relative_path",
]
