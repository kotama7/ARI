"""RQGM-independent semantic requirements shared across K/C/A layers."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, field_validator

from ari.protocols.integrity import (
    DigestBoundModel,
    SHA256_DIGEST_PATTERN,
    StrictModel,
)


AssuranceTier = Literal["screen", "validate", "certify"]


class EvaluationObligationV1(StrictModel):
    """A Knowledge Skill's non-authoritative request for scientific checks."""

    schema_version: Literal["ari.evaluation-obligation/v1"] = (
        "ari.evaluation-obligation/v1"
    )
    property_id: str = Field(min_length=1, max_length=256)
    required_methods: tuple[str, ...] = Field(default_factory=tuple, max_length=64)
    required_tier: AssuranceTier = "screen"
    scope: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    source_skill_digest: str | None = Field(
        default=None, pattern=SHA256_DIGEST_PATTERN
    )

    @field_validator("required_methods")
    @classmethod
    def _unique_methods(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(sorted({value.strip() for value in values if value.strip()}))
        if len(normalized) != len(values):
            raise ValueError("required_methods must be non-empty and unique")
        return normalized

    @field_validator("scope")
    @classmethod
    def _canonical_scope(
        cls, value: dict[str, tuple[str, ...]]
    ) -> dict[str, tuple[str, ...]]:
        normalized: dict[str, tuple[str, ...]] = {}
        for key, items in sorted(value.items()):
            name = str(key).strip()
            vals = tuple(sorted({str(item).strip() for item in items if str(item).strip()}))
            if not name or len(vals) != len(items):
                raise ValueError("scope keys and values must be non-empty and unique")
            normalized[name] = vals
        return normalized


class EnvironmentSnapshotV1(DigestBoundModel):
    """Value-free environment facts used by deterministic resolvers."""

    _digest_field = "identity_digest"

    schema_version: Literal["ari.environment-snapshot/v1"] = (
        "ari.environment-snapshot/v1"
    )
    identity_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    resource_types: tuple[str, ...] = Field(default_factory=tuple)
    features: tuple[str, ...] = Field(default_factory=tuple)
    transports: tuple[str, ...] = Field(default_factory=tuple)
    network_classes: tuple[str, ...] = Field(default_factory=tuple)
    metadata: dict[str, Any] = Field(default_factory=dict)


__all__ = ["AssuranceTier", "EnvironmentSnapshotV1", "EvaluationObligationV1"]
