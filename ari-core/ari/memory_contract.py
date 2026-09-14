"""Versioned, provider-neutral research-memory contracts."""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


MEMORY_RECORD_V1 = "ari.memory-record/v1"
MEMORY_RETRIEVAL_V1 = "ari.memory-retrieval/v1"
MEMORY_BACKUP_V1 = "ari.memory-backup/v1"
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+-]{0,255}$")

MemoryKindV1 = Literal[
    "observation",
    "experiment_result",
    "failure_case",
    "procedure",
    "reflection",
    "artifact_summary",
    "paper_claim",
    "reproducibility_event",
]
ReproStatusV1 = Literal[
    "unverified",
    "rerun_passed",
    "rerun_failed",
    "paper_only_reproduced",
]


def canonical_memory_digest(value: Any) -> str:
    value = _json_value(value)
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _json_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _json_value(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _digest(value: str, field: str) -> str:
    if not _DIGEST_RE.fullmatch(value):
        raise ValueError(f"{field} must use sha256:<64 lowercase hex> format")
    return value


def _identifier(value: str, field: str) -> str:
    if not _ID_RE.fullmatch(value):
        raise ValueError(f"{field} contains unsupported characters")
    return value


class MemoryArtifactRefV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    relative_path: str
    digest: str
    size_bytes: int = Field(ge=0)
    role: str = Field(min_length=1, max_length=128)
    integrity_status: Literal["verified", "unverified"]

    @field_validator("relative_path")
    @classmethod
    def _path(cls, value: str) -> str:
        pure = PurePosixPath(value)
        if (
            not value
            or pure.is_absolute()
            or any(part in {"", ".", ".."} for part in pure.parts)
        ):
            raise ValueError("memory artifact path must be safe and relative")
        return value

    @field_validator("digest")
    @classmethod
    def _sha256(cls, value: str) -> str:
        return _digest(value, "memory artifact digest")


class MemoryNodeReportRefV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    node_id: str
    digest: str

    @field_validator("run_id", "node_id")
    @classmethod
    def _ids(cls, value: str, info: Any) -> str:
        return _identifier(value, info.field_name)

    @field_validator("digest")
    @classmethod
    def _sha256(cls, value: str) -> str:
        return _digest(value, "node report digest")


class MemoryMetricPointerV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    name: str = Field(min_length=1, max_length=256)
    value: float
    unit: str = Field(min_length=1, max_length=128)

    @field_validator("value")
    @classmethod
    def _finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("memory metric value must be finite")
        return value

    @field_validator("unit")
    @classmethod
    def _unit(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("memory metric unit must be explicit")
        return value.strip()


class _MemoryRecordPayloadV1(BaseModel):
    """Validated canonical payload before its content address is assigned."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["ari.memory-record/v1"] = MEMORY_RECORD_V1
    kind: MemoryKindV1
    text: str = Field(min_length=1, max_length=100_000)
    source_run_id: str
    source_node_id: str
    ancestor_node_ids: list[str] = Field(default_factory=list, max_length=10_000)
    artifact_refs: list[MemoryArtifactRefV1] = Field(default_factory=list, max_length=1_024)
    node_report_ref: MemoryNodeReportRefV1 | None = None
    metric_ptr: MemoryMetricPointerV1 | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    repro_target_id: str | None = None
    repro_status: ReproStatusV1 | None = None
    created_by_tool_ref: str
    attributes: dict[str, Any] = Field(default_factory=dict, max_length=256)

    @field_validator("source_run_id", "source_node_id", "created_by_tool_ref")
    @classmethod
    def _ids(cls, value: str, info: Any) -> str:
        return _identifier(value, info.field_name)

    @field_validator("ancestor_node_ids")
    @classmethod
    def _ancestors(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("memory ancestor lineage contains duplicates")
        for node_id in value:
            _identifier(node_id, "ancestor_node_ids")
        return value

    @field_validator("repro_target_id")
    @classmethod
    def _target(cls, value: str | None) -> str | None:
        if value is not None:
            _digest(value, "repro_target_id")
        return value

    @field_validator("attributes")
    @classmethod
    def _json_attributes(cls, value: dict[str, Any]) -> dict[str, Any]:
        # Round-trip validation also rejects NaN and non-JSON runtime objects.
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        return value

    @model_validator(mode="after")
    def _consistent(self) -> "_MemoryRecordPayloadV1":
        if self.source_node_id in self.ancestor_node_ids:
            raise ValueError("memory source node cannot appear in its ancestor lineage")
        if self.node_report_ref is not None and (
            self.node_report_ref.run_id != self.source_run_id
            or self.node_report_ref.node_id != self.source_node_id
        ):
            raise ValueError(
                "memory node-report reference must match its source run and node"
            )
        if self.kind == "reproducibility_event":
            if self.repro_target_id is None or self.repro_status is None:
                raise ValueError(
                    "reproducibility_event requires target and status"
                )
        elif self.repro_target_id is not None or self.repro_status is not None:
            raise ValueError(
                "reproducibility status is only valid on reproducibility events"
            )
        return self


class MemoryRecordV1(_MemoryRecordPayloadV1):
    """Immutable index record; artifacts, not text, remain evidence."""

    record_id: str
    record_digest: str

    @field_validator("record_id", "record_digest")
    @classmethod
    def _digests(cls, value: str, info: Any) -> str:
        return _digest(value, info.field_name)

    @model_validator(mode="after")
    def _content_addressed(self) -> "MemoryRecordV1":
        payload = self.model_dump(mode="json", exclude={"record_id", "record_digest"})
        expected = canonical_memory_digest(payload)
        if self.record_id != expected or self.record_digest != expected:
            raise ValueError(f"memory record digest mismatch: expected {expected}")
        return self

    @property
    def artifact_grounded(self) -> bool:
        return bool(self.artifact_refs) and all(
            ref.integrity_status == "verified" for ref in self.artifact_refs
        )


def build_memory_record(**values: Any) -> MemoryRecordV1:
    values = dict(values)
    values.setdefault("schema_version", MEMORY_RECORD_V1)
    unsigned = {
        key: value
        for key, value in values.items()
        if key not in {"record_id", "record_digest"}
    }
    payload = _MemoryRecordPayloadV1.model_validate(unsigned).model_dump(mode="json")
    digest = canonical_memory_digest(payload)
    return MemoryRecordV1.model_validate(
        {**payload, "record_id": digest, "record_digest": digest}
    )


class MemoryRetrievalProvenanceV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    backend: str = Field(min_length=1, max_length=256)
    backend_version: str = Field(min_length=1, max_length=256)
    server_version: str = Field(min_length=1, max_length=256)
    model: str = Field(min_length=1, max_length=512)
    model_version: str = Field(min_length=1, max_length=256)
    ranking: str = Field(min_length=1, max_length=1_024)
    deterministic: bool
    query_digest: str
    candidate_count: int = Field(ge=0)
    returned_count: int = Field(ge=0)
    limit: int = Field(ge=1, le=1_000)
    filter_evidence: dict[str, Any]

    @field_validator("query_digest")
    @classmethod
    def _query_digest(cls, value: str) -> str:
        return _digest(value, "memory query digest")

    @field_validator("filter_evidence")
    @classmethod
    def _filter_json(cls, value: dict[str, Any]) -> dict[str, Any]:
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        return value

    @model_validator(mode="after")
    def _candidate_bound(self) -> "MemoryRetrievalProvenanceV1":
        if self.returned_count > self.candidate_count:
            raise ValueError("memory retrieval returned more rows than candidates")
        return self


class MemoryRetrievalV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["ari.memory-retrieval/v1"] = MEMORY_RETRIEVAL_V1
    results: list[dict[str, Any]] = Field(max_length=1_000)
    provenance: MemoryRetrievalProvenanceV1

    @model_validator(mode="after")
    def _count(self) -> "MemoryRetrievalV1":
        if len(self.results) != self.provenance.returned_count:
            raise ValueError("memory retrieval returned_count is inconsistent")
        return self


class _MemoryReactEntryPayloadV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    content: str = Field(max_length=1_000_000)
    metadata: dict[str, Any] = Field(default_factory=dict, max_length=256)
    ts: float

    @field_validator("metadata")
    @classmethod
    def _metadata_json(cls, value: dict[str, Any]) -> dict[str, Any]:
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        return value


class MemoryReactEntryV1(_MemoryReactEntryPayloadV1):
    entry_digest: str

    @field_validator("entry_digest")
    @classmethod
    def _entry_digest_format(cls, value: str) -> str:
        return _digest(value, "memory react entry digest")

    @model_validator(mode="after")
    def _content_addressed(self) -> "MemoryReactEntryV1":
        payload = self.model_dump(mode="json", exclude={"entry_digest"})
        expected = canonical_memory_digest(payload)
        if self.entry_digest != expected:
            raise ValueError(
                f"memory react entry digest mismatch: expected {expected}"
            )
        return self


def build_memory_react_entry(**values: Any) -> MemoryReactEntryV1:
    payload = _MemoryReactEntryPayloadV1.model_validate(values).model_dump(mode="json")
    return MemoryReactEntryV1.model_validate(
        {**payload, "entry_digest": canonical_memory_digest(payload)}
    )


class _MemoryBackupPayloadV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["ari.memory-backup/v1"] = MEMORY_BACKUP_V1
    records: list[MemoryRecordV1] = Field(max_length=1_000_000)
    react_entries: list[MemoryReactEntryV1] = Field(max_length=1_000_000)
    core_context: dict[str, Any] = Field(default_factory=dict, max_length=256)
    record_digests: list[str] = Field(max_length=1_000_000)
    record_order: list[str] = Field(max_length=1_000_000)

    @field_validator("record_digests", "record_order")
    @classmethod
    def _record_digest_formats(cls, value: list[str], info: Any) -> list[str]:
        for digest in value:
            _digest(digest, info.field_name)
        return value

    @field_validator("core_context")
    @classmethod
    def _context_json(cls, value: dict[str, Any]) -> dict[str, Any]:
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        return value

    @model_validator(mode="after")
    def _indexes(self) -> "_MemoryBackupPayloadV1":
        record_digests = [record.record_digest for record in self.records]
        if len(record_digests) != len(set(record_digests)):
            raise ValueError("memory backup contains duplicate records")
        if self.record_digests != sorted(record_digests):
            raise ValueError("memory backup record digest index is inconsistent")
        if (
            len(self.record_order) != len(set(self.record_order))
            or sorted(self.record_order) != self.record_digests
        ):
            raise ValueError("memory backup record order is inconsistent")
        react_digests = [entry.entry_digest for entry in self.react_entries]
        if react_digests != sorted(react_digests):
            raise ValueError("memory backup react entry order is not canonical")
        return self


class MemoryBackupV1(_MemoryBackupPayloadV1):
    backup_digest: str

    @field_validator("backup_digest")
    @classmethod
    def _backup_digest_format(cls, value: str) -> str:
        return _digest(value, "memory backup digest")

    @model_validator(mode="after")
    def _content_addressed(self) -> "MemoryBackupV1":
        payload = self.model_dump(mode="json", exclude={"backup_digest"})
        expected = canonical_memory_digest(payload)
        if self.backup_digest != expected:
            raise ValueError(f"memory backup digest mismatch: expected {expected}")
        return self


def build_memory_backup(**values: Any) -> MemoryBackupV1:
    values = dict(values)
    values.setdefault("schema_version", MEMORY_BACKUP_V1)
    unsigned = {key: value for key, value in values.items() if key != "backup_digest"}
    payload = _MemoryBackupPayloadV1.model_validate(unsigned).model_dump(mode="json")
    return MemoryBackupV1.model_validate(
        {**payload, "backup_digest": canonical_memory_digest(payload)}
    )


__all__ = [
    "MEMORY_RECORD_V1",
    "MEMORY_RETRIEVAL_V1",
    "MEMORY_BACKUP_V1",
    "MemoryBackupV1",
    "MemoryArtifactRefV1",
    "MemoryMetricPointerV1",
    "MemoryNodeReportRefV1",
    "MemoryRecordV1",
    "MemoryRetrievalProvenanceV1",
    "MemoryRetrievalV1",
    "MemoryReactEntryV1",
    "build_memory_backup",
    "build_memory_react_entry",
    "build_memory_record",
    "canonical_memory_digest",
]
