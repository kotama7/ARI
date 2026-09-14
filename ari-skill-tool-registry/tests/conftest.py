"""Shared deterministic federation fixtures."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "ari-skill-tool-registry" / "src"
CORE = REPO_ROOT / "ari-core"
TESTS = Path(__file__).resolve().parent
for path in (str(TESTS), str(SRC), str(CORE)):
    if path not in sys.path:
        sys.path.insert(0, path)

from models import (  # noqa: E402
    AdmissionEvidenceV1,
    CanonicalToolDescriptorV1,
    LockedSourceV1,
    OriginHopV1,
    sha256_digest,
)
from sources import CatalogCandidateV1, StaticCatalogSource  # noqa: E402


def fixture_source(
    source_id: str = "fixture.source",
    *,
    provider_id: str = "fixture.provider",
) -> LockedSourceV1:
    provider_identity = {"provider": provider_id, "version": "1.0.0"}
    adapter_identity = {"adapter": "fixture", "version": "1.0.0"}
    return LockedSourceV1(
        source_id=source_id,
        kind="fixture",
        source_digest=sha256_digest({"source": source_id}),
        provider_id=provider_id,
        provider_version="1.0.0",
        provider_digest=sha256_digest(provider_identity),
        adapter_id="ari.fixture-adapter",
        adapter_version="1.0.0",
        adapter_digest=sha256_digest(adapter_identity),
        runtime={},
    )


def fixture_descriptor(
    name: str = "measure",
    *,
    source: LockedSourceV1 | None = None,
    capability_ref: str = "ari.fixture.measure",
    input_schema: dict[str, Any] | None = None,
    output_schema: dict[str, Any] | None = None,
    defaults: dict[str, Any] | None = None,
    origin_chains: list[list[OriginHopV1]] | None = None,
    leaf_identity: str | None = None,
    independence_group: str | None = None,
    equivalence_key: str | None = None,
    **overrides: Any,
) -> CanonicalToolDescriptorV1:
    source = source or fixture_source()
    leaf_identity = leaf_identity or f"{source.provider_id}:{name}"
    chain = origin_chains or [
        [
            OriginHopV1(
                kind="source", id=source.source_id, digest=source.source_digest
            ),
            OriginHopV1(
                kind="provider", id=source.provider_id, digest=source.provider_digest
            ),
            OriginHopV1(kind="tool", id=leaf_identity),
        ]
    ]
    values: dict[str, Any] = {
        "source_ids": [source.source_id],
        "provider_id": source.provider_id,
        "provider_version": source.provider_version,
        "provider_digest": source.provider_digest,
        "adapter_id": source.adapter_id,
        "adapter_version": source.adapter_version,
        "adapter_digest": source.adapter_digest,
        "name": name,
        "provider_tool_name": name,
        "capability_ref": capability_ref,
        "description": f"Measure {name} for a fixture experiment",
        "input_schema": input_schema
        or {
            "type": "object",
            "properties": {
                "value": {"type": "number"},
                "scale": {"type": "number", "default": 1.0},
            },
            "required": ["value"],
        },
        "output_schema": output_schema or {"type": "object"},
        "defaults": defaults if defaults is not None else {"scale": 1.0},
        "annotations": {},
        "side_effects": "read-only",
        "determinism": "deterministic",
        "permissions": ["process"],
        "semantics": {"quantity": "fixture measurement"},
        "units": {"value": "fixture-unit"},
        "limitations": ["fixture only"],
        "backend_lineage": [source.provider_id],
        "data_lineage": ["fixture:data"],
        "leaf_identity": leaf_identity,
        "origin_chains": chain,
        "equivalence_key": equivalence_key,
        "independence_group": independence_group or source.provider_id,
        "async_lifecycle": None,
    }
    values.update(overrides)
    return CanonicalToolDescriptorV1.create(**values)


def callable_evidence(**updates: Any) -> AdmissionEvidenceV1:
    values = {
        "protocol_conformance": True,
        "provider_pinned": True,
        "launcher_verified": True,
    }
    values.update(updates)
    return AdmissionEvidenceV1(**values)


def static_source(
    descriptors: list[CanonicalToolDescriptorV1],
    *,
    source: LockedSourceV1 | None = None,
    evidence: AdmissionEvidenceV1 | None = None,
) -> StaticCatalogSource:
    source = source or fixture_source()
    return StaticCatalogSource(
        source,
        [
            CatalogCandidateV1(
                descriptor=descriptor,
                evidence=evidence or callable_evidence(),
            )
            for descriptor in descriptors
        ],
    )


@pytest.fixture
def fixture_helpers():
    return {
        "source": fixture_source,
        "descriptor": fixture_descriptor,
        "evidence": callable_evidence,
        "static_source": static_source,
    }
