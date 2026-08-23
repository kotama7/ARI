"""Shared canonical-JSON and immutable digest-bound contract primitives.

The Knowledge, Provider/Capability, and Assurance layers all use this module
as their sole trust-anchor implementation.  Keeping the primitive in
``ari.protocols`` prevents those product layers from depending on RQGM and
also avoids creating subtly different JSON canonicalisation rules.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Annotated, Any, ClassVar

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    model_validator,
)


SHA256_DIGEST_PATTERN = r"^sha256:[0-9a-f]{64}$"
FULL_GIT_COMMIT_PATTERN = r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$"
ZERO_SHA256 = "sha256:" + ("0" * 64)

#: A single full trust anchor. Scalar anchor fields already carry
#: ``Field(pattern=SHA256_DIGEST_PATTERN)``; this alias is what gives the SAME
#: constraint to an anchor that lives *inside* a collection, where a bare
#: ``tuple[str, ...]`` or ``dict[str, str]`` annotation accepts a truncated
#: ``hash12`` element and silently demotes the anchor.
Sha256Digest = Annotated[str, Field(pattern=SHA256_DIGEST_PATTERN)]


class ContractIntegrityError(ValueError):
    """A canonical contract is malformed, mutable, or digest-inconsistent."""


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize *value* using ARI's stable canonical JSON representation."""

    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_digest(value: Any) -> str:
    """Return a full, algorithm-qualified SHA-256 over canonical JSON."""

    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def bytes_digest(value: bytes) -> str:
    """Return a full, algorithm-qualified SHA-256 over exact bytes."""

    return "sha256:" + hashlib.sha256(value).hexdigest()


def normalize_sha256(value: str) -> str:
    """Normalize legacy 64-hex digests without altering their source object."""

    normalized = value.strip().lower()
    if normalized.startswith("sha256:"):
        if len(normalized) != 71:
            raise ContractIntegrityError("SHA-256 digest must contain 64 hex digits")
        try:
            int(normalized[7:], 16)
        except ValueError as exc:
            raise ContractIntegrityError("SHA-256 digest contains non-hex data") from exc
        return normalized
    if len(normalized) == 64:
        try:
            int(normalized, 16)
        except ValueError as exc:
            raise ContractIntegrityError("SHA-256 digest contains non-hex data") from exc
        return "sha256:" + normalized
    raise ContractIntegrityError("expected full SHA-256 digest")


def is_full_sha256(value: str) -> bool:
    """Return whether *value* is an algorithm-qualified full SHA-256."""

    return re.fullmatch(SHA256_DIGEST_PATTERN, str(value)) is not None


class StrictModel(BaseModel):
    """Frozen, closed-schema base used by all new public contracts."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class DigestBoundModel(StrictModel):
    """Mint-once model whose declared digest covers every other field."""

    _digest_field: ClassVar[str]

    @classmethod
    def create(cls, **values: Any):
        values[cls._digest_field] = ZERO_SHA256
        return cls.model_validate(values, context={"bind_canonical_digest": True})

    def digest_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={self._digest_field})

    @model_validator(mode="after")
    def _canonical_digest_matches(self, info: ValidationInfo):
        expected = canonical_digest(self.digest_payload())
        if info.context and info.context.get("bind_canonical_digest"):
            object.__setattr__(self, self._digest_field, expected)
        elif getattr(self, self._digest_field) != expected:
            raise ValueError(
                f"{self._digest_field} does not match the canonical payload"
            )
        return self


__all__ = [
    "ContractIntegrityError",
    "DigestBoundModel",
    "FULL_GIT_COMMIT_PATTERN",
    "SHA256_DIGEST_PATTERN",
    "Sha256Digest",
    "StrictModel",
    "ZERO_SHA256",
    "bytes_digest",
    "canonical_digest",
    "canonical_json_bytes",
    "is_full_sha256",
    "normalize_sha256",
]
