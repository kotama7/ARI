"""Shared primitives for versioned scientific-data contracts."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import PurePosixPath
from typing import Any, ClassVar, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)


SCIENCE_DATA_V1 = "ari.science-data/v1"
SCIENCE_RAW_V1 = "ari.science-raw/v1"
SCIENCE_DERIVED_V1 = "ari.science-derived/v1"
SCIENCE_INTERPRETATION_V1 = "ari.science-interpretation/v1"
SCIENCE_PROVENANCE_V1 = "ari.science-provenance/v1"
SCIENCE_ARTIFACT_REF_V1 = "ari.science-artifact-ref/v1"

SHA256_DIGEST_PATTERN = r"^sha256:[0-9a-f]{64}$"
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,255}$")
ZERO_DIGEST = "sha256:" + "0" * 64


class ScienceDataError(ValueError):
    """The scientific-data record is malformed, unbound, or tampered with."""


def canonical_science_digest(value: Any) -> str:
    """Return a stable SHA-256 identity for finite JSON-compatible data."""

    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def finite_json(value: Any, field: str) -> Any:
    try:
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be finite JSON") from exc
    return value


def safe_id(value: str, field: str) -> str:
    if not _SAFE_ID_RE.fullmatch(value):
        raise ValueError(f"{field} contains unsupported characters")
    return value


class StrictScienceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DigestBoundScienceModel(StrictScienceModel):
    digest_field: ClassVar[str]

    @classmethod
    def create(cls, **values: Any):
        values = dict(values)
        values[cls.digest_field] = ZERO_DIGEST
        return cls.model_validate(values, context={"bind_science_digest": True})

    def digest_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={self.digest_field})

    @model_validator(mode="after")
    def _digest_matches(self, info: ValidationInfo):
        expected = canonical_science_digest(self.digest_payload())
        if info.context and info.context.get("bind_science_digest"):
            object.__setattr__(self, self.digest_field, expected)
        elif getattr(self, self.digest_field) != expected:
            raise ValueError(
                f"{self.digest_field} does not match the canonical payload"
            )
        return self


class ScienceArtifactRefV1(StrictScienceModel):
    """A content-addressed input or output under the run checkpoint."""

    schema_version: Literal["ari.science-artifact-ref/v1"] = SCIENCE_ARTIFACT_REF_V1
    relative_path: str
    digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    media_type: str = Field(min_length=1, max_length=128)
    role: str = Field(min_length=1, max_length=128)
    size_bytes: int = Field(ge=0)

    @field_validator("relative_path")
    @classmethod
    def _relative_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if (
            not value
            or path.is_absolute()
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise ValueError("science artifact path must be safe and relative")
        return path.as_posix()


class ScienceEnvironmentV1(StrictScienceModel):
    executor: str = Field(default="", max_length=256)
    hostname: str = Field(default="", max_length=256)
    cpu_model: str = Field(default="", max_length=1024)
    arch: str = Field(default="", max_length=256)
    scheduler_job_id: str = Field(default="", max_length=256)
    scheduler_partition: str = Field(default="", max_length=256)
    environment_digest: str | None = Field(default=None, pattern=SHA256_DIGEST_PATTERN)


__all__ = [
    "DigestBoundScienceModel",
    "SCIENCE_ARTIFACT_REF_V1",
    "SCIENCE_DATA_V1",
    "SCIENCE_DERIVED_V1",
    "SCIENCE_INTERPRETATION_V1",
    "SCIENCE_PROVENANCE_V1",
    "SCIENCE_RAW_V1",
    "SHA256_DIGEST_PATTERN",
    "ZERO_DIGEST",
    "ScienceArtifactRefV1",
    "ScienceDataError",
    "ScienceEnvironmentV1",
    "StrictScienceModel",
    "canonical_science_digest",
    "finite_json",
    "safe_id",
]
