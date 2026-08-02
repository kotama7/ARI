"""Versioned, immutable contracts for the ARI orchestration control plane."""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from typing import Any, ClassVar, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)


RUN_REQUEST_V1 = "ari.orchestrator-run-request/v1"
RUN_HANDLE_V1 = "ari.orchestrator-run-handle/v1"
RUN_STATUS_V1 = "ari.orchestrator-run-status/v1"
RUN_RESULT_V1 = "ari.orchestrator-run-result/v1"
ARTIFACT_REF_V1 = "ari.orchestrator-artifact-ref/v1"
PRINCIPAL_V1 = "ari.orchestrator-principal/v1"
ZERO_DIGEST = "sha256:" + "0" * 64
DIGEST_PATTERN = r"^sha256:[a-f0-9]{64}$"
RUN_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}$")

RunState = Literal[
    "submitted",
    "running",
    "cancelling",
    "succeeded",
    "failed",
    "cancelled",
]


class OrchestratorContractError(ValueError):
    """A public orchestration record is malformed or fails its digest binding."""


def canonical_digest(value: Any) -> str:
    """Return a deterministic SHA-256 identifier for a finite JSON value."""

    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise OrchestratorContractError("contract payload must be finite JSON") from exc
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def bytes_digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


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


class PrincipalV1(StrictModel):
    schema_version: Literal["ari.orchestrator-principal/v1"] = PRINCIPAL_V1
    principal_id: str = Field(min_length=1, max_length=128)
    roles: tuple[str, ...] = ()
    authentication: Literal["local-stdio", "bearer", "test"] = "local-stdio"

    @field_validator("principal_id")
    @classmethod
    def _safe_principal_id(cls, value: str) -> str:
        if not _SAFE_ID_RE.fullmatch(value):
            raise ValueError("principal_id contains unsupported characters")
        return value

    @field_validator("roles")
    @classmethod
    def _safe_roles(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(sorted(set(value)))
        if any(not _SAFE_ID_RE.fullmatch(item) for item in normalized):
            raise ValueError("role contains unsupported characters")
        return normalized

    @property
    def is_admin(self) -> bool:
        return "admin" in self.roles


class RunRequestV1(DigestBoundModel):
    """A complete, idempotent request whose scientific input is digest-bound."""

    digest_field: ClassVar[str] = "request_digest"
    schema_version: Literal["ari.orchestrator-run-request/v1"] = RUN_REQUEST_V1
    idempotency_key: str = Field(min_length=1, max_length=128)
    experiment_md: str = Field(min_length=1, max_length=1_048_576)
    experiment_digest: str = Field(pattern=DIGEST_PATTERN)
    parent_run_id: str | None = Field(default=None, pattern=RUN_ID_PATTERN)
    max_recursion_depth: int = Field(default=3, ge=0, le=32)
    max_nodes: int = Field(default=10, ge=1, le=10_000)
    max_total_nodes: int = Field(default=100, ge=1, le=100_000)
    max_descendant_runs: int = Field(default=32, ge=0, le=10_000)
    estimated_cost_usd: float = Field(default=0.0, ge=0.0, le=1_000_000.0)
    max_cost_usd: float = Field(default=100.0, ge=0.0, le=1_000_000.0)
    cpus: int = Field(default=1, ge=1, le=1024)
    timeout_minutes: int = Field(default=60, ge=1, le=10_080)
    model: str = Field(default="", max_length=256)
    llm_backend: str = Field(default="", max_length=128)
    executor: str = Field(default="", max_length=128)
    retrieval_backend: str = Field(default="", max_length=128)
    request_digest: str = Field(pattern=DIGEST_PATTERN)

    @classmethod
    def from_parameters(cls, **values: Any) -> "RunRequestV1":
        experiment_md = str(values.get("experiment_md") or "")
        values = dict(values)
        values["experiment_md"] = experiment_md
        values["experiment_digest"] = bytes_digest(experiment_md.encode("utf-8"))
        return cls.create(**values)

    @field_validator("idempotency_key")
    @classmethod
    def _safe_idempotency_key(cls, value: str) -> str:
        if not _SAFE_ID_RE.fullmatch(value):
            raise ValueError("idempotency_key contains unsupported characters")
        return value

    @field_validator("estimated_cost_usd", "max_cost_usd")
    @classmethod
    def _finite_cost(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("cost values must be finite")
        return value

    @model_validator(mode="after")
    def _coherent_request(self) -> "RunRequestV1":
        if self.experiment_digest != bytes_digest(self.experiment_md.encode("utf-8")):
            raise ValueError("experiment_digest does not match experiment_md")
        if self.max_nodes > self.max_total_nodes:
            raise ValueError("max_nodes cannot exceed max_total_nodes")
        if self.estimated_cost_usd > self.max_cost_usd:
            raise ValueError("estimated_cost_usd cannot exceed max_cost_usd")
        for field_name in ("model", "llm_backend", "executor", "retrieval_backend"):
            value = getattr(self, field_name)
            if value and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]*", value):
                raise ValueError(f"{field_name} is not a safe profile identifier")
        return self


class RunHandleV1(StrictModel):
    schema_version: Literal["ari.orchestrator-run-handle/v1"] = RUN_HANDLE_V1
    run_id: str = Field(pattern=RUN_ID_PATTERN)
    request_digest: str = Field(pattern=DIGEST_PATTERN)
    principal_id: str
    parent_run_id: str | None = Field(default=None, pattern=RUN_ID_PATTERN)
    root_run_id: str = Field(pattern=RUN_ID_PATTERN)
    recursion_depth: int = Field(ge=0, le=32)
    max_recursion_depth: int = Field(ge=0, le=32)
    state: RunState
    created_at: str
    reused: bool = False


class ArtifactRefV1(StrictModel):
    schema_version: Literal["ari.orchestrator-artifact-ref/v1"] = ARTIFACT_REF_V1
    run_id: str = Field(pattern=RUN_ID_PATTERN)
    artifact_id: str = Field(pattern=DIGEST_PATTERN)
    digest: str = Field(pattern=DIGEST_PATTERN)
    role: str = Field(min_length=1, max_length=128)
    media_type: str = Field(min_length=1, max_length=128)
    size_bytes: int = Field(ge=0)

    @model_validator(mode="after")
    def _content_addressed(self) -> "ArtifactRefV1":
        if self.artifact_id != self.digest:
            raise ValueError("artifact_id must equal the content digest")
        return self


class RunStatusV1(StrictModel):
    schema_version: Literal["ari.orchestrator-run-status/v1"] = RUN_STATUS_V1
    run_id: str = Field(pattern=RUN_ID_PATTERN)
    request_digest: str = Field(pattern=DIGEST_PATTERN)
    principal_id: str
    parent_run_id: str | None = Field(default=None, pattern=RUN_ID_PATTERN)
    root_run_id: str = Field(pattern=RUN_ID_PATTERN)
    recursion_depth: int = Field(ge=0, le=32)
    max_recursion_depth: int = Field(ge=0, le=32)
    state: RunState
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
    exit_code: int | None = None
    error: str | None = Field(default=None, max_length=4096)
    cancel_requested: bool = False
    total_nodes: int = Field(default=0, ge=0)
    successful_nodes: int = Field(default=0, ge=0)
    best_node_id: str | None = None
    best_score: float | None = None
    budget: dict[str, int | float] = Field(default_factory=dict)


class RunResultV1(StrictModel):
    schema_version: Literal["ari.orchestrator-run-result/v1"] = RUN_RESULT_V1
    run_id: str = Field(pattern=RUN_ID_PATTERN)
    request_digest: str = Field(pattern=DIGEST_PATTERN)
    state: RunState
    exit_code: int | None = None
    error: str | None = Field(default=None, max_length=4096)
    artifacts: tuple[ArtifactRefV1, ...] = ()


__all__ = [
    "ARTIFACT_REF_V1",
    "DIGEST_PATTERN",
    "PRINCIPAL_V1",
    "RUN_HANDLE_V1",
    "RUN_ID_PATTERN",
    "RUN_REQUEST_V1",
    "RUN_RESULT_V1",
    "RUN_STATUS_V1",
    "ArtifactRefV1",
    "OrchestratorContractError",
    "PrincipalV1",
    "RunHandleV1",
    "RunRequestV1",
    "RunResultV1",
    "RunState",
    "RunStatusV1",
    "bytes_digest",
    "canonical_digest",
    "utc_now",
]
