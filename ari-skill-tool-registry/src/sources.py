"""Catalog-source declarations and candidate generation."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Protocol

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from models import (
    AdmissionEvidenceV1,
    CanonicalToolDescriptorV1,
    LockedSourceV1,
    OriginHopV1,
    ProviderAsyncLifecycleV1,
    sanitize_text,
    sha256_digest,
)
from providers import (
    STDIO_ADAPTER_ID,
    STDIO_ADAPTER_VERSION,
    ProviderAdapter,
    ProviderToolV1,
    PythonStdioLauncherV1,
    StdioMCPAdapter,
    provider_digest,
    stdio_adapter_digest,
)


SOURCES_V1 = "ari.catalog-sources/v1"
_REF_SAFE_RE = re.compile(r"[^a-z0-9._-]+")


class CatalogSourceError(RuntimeError):
    pass


class CatalogCandidateV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    descriptor: CanonicalToolDescriptorV1
    evidence: AdmissionEvidenceV1 = Field(default_factory=AdmissionEvidenceV1)


class CatalogSource(Protocol):
    @property
    def locked_source(self) -> LockedSourceV1: ...

    async def sync(self) -> list[CatalogCandidateV1]: ...


class StdioSourceSpecV1(BaseModel):
    """Reviewed declaration for one direct stdio MCP provider."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str
    kind: str = "stdio-mcp"
    provider_id: str
    provider_version: str
    provider_digest: str
    launcher: PythonStdioLauncherV1
    capability_prefix: str = "ari.federated"
    default_permissions: list[str] = Field(default_factory=lambda: ["process"])
    origin_prefix: list[OriginHopV1] = Field(default_factory=list)
    evidence: AdmissionEvidenceV1 = Field(default_factory=AdmissionEvidenceV1)
    timeout_seconds: float = Field(default=30.0, gt=0, le=3_600)
    max_pages: int = Field(default=1_000, ge=1, le=10_000)
    max_tools: int = Field(default=100_000, ge=1, le=1_000_000)

    @field_validator("kind")
    @classmethod
    def _stdio_only(cls, value: str) -> str:
        if value != "stdio-mcp":
            raise ValueError("only stdio-mcp is a production generic source kind")
        return value

    @field_validator("source_id", "provider_id", "capability_prefix")
    @classmethod
    def _valid_ref(cls, value: str) -> str:
        if not value or _REF_SAFE_RE.search(value):
            raise ValueError("source identifiers must be lowercase dotted/kebab text")
        return value

    @field_validator("provider_digest")
    @classmethod
    def _valid_digest(cls, value: str) -> str:
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
            raise ValueError("provider_digest must be a SHA-256 digest")
        return value

    def verify(self) -> None:
        actual = provider_digest(self.launcher)
        if actual != self.provider_digest:
            raise CatalogSourceError(
                f"source {self.source_id} provider digest drift: "
                f"expected {self.provider_digest}, got {actual}"
            )

    @property
    def adapter_digest(self) -> str:
        return stdio_adapter_digest()

    @property
    def source_digest(self) -> str:
        return sha256_digest(self.model_dump(mode="json"))

    def to_locked_source(self) -> LockedSourceV1:
        self.verify()
        return LockedSourceV1(
            source_id=self.source_id,
            kind="stdio-mcp",
            source_digest=self.source_digest,
            provider_id=self.provider_id,
            provider_version=self.provider_version,
            provider_digest=self.provider_digest,
            adapter_id=STDIO_ADAPTER_ID,
            adapter_version=STDIO_ADAPTER_VERSION,
            adapter_digest=self.adapter_digest,
            runtime={
                "launcher": self.launcher.model_dump(mode="json"),
                "timeout_seconds": self.timeout_seconds,
                "max_pages": self.max_pages,
                "max_tools": self.max_tools,
            },
        )


class SourcesDocumentV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = SOURCES_V1
    sources: list[StdioSourceSpecV1] = Field(default_factory=list)

    @field_validator("schema_version")
    @classmethod
    def _version(cls, value: str) -> str:
        if value != SOURCES_V1:
            raise ValueError(f"schema_version must be {SOURCES_V1}")
        return value


def _safe_capability_segment(value: str) -> str:
    normalized = _REF_SAFE_RE.sub("-", value.casefold()).strip("-.")
    return normalized or "unnamed"


def _schema_defaults(schema: dict[str, Any]) -> dict[str, Any]:
    defaults: dict[str, Any] = {}
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return defaults
    for name, definition in sorted(properties.items()):
        if isinstance(definition, dict) and "default" in definition:
            defaults[str(name)] = definition["default"]
    return defaults


def _annotation_dict(tool: ProviderToolV1) -> dict[str, Any]:
    return dict(tool.annotations or {})


def _descriptor_from_tool(
    spec: StdioSourceSpecV1,
    tool: ProviderToolV1,
) -> CanonicalToolDescriptorV1:
    annotations = _annotation_dict(tool)
    leaf_identity = sanitize_text(
        annotations.get("ari_leaf_identity") or f"{spec.provider_id}:{tool.name}",
        limit=1_024,
    )
    origin_chain = [
        *spec.origin_prefix,
        OriginHopV1(kind="source", id=spec.source_id, digest=spec.source_digest),
        OriginHopV1(kind="provider", id=spec.provider_id, digest=spec.provider_digest),
        OriginHopV1(kind="tool", id=leaf_identity),
    ]
    raw_capability = annotations.get("ari_capability_ref")
    capability = (
        str(raw_capability)
        if isinstance(raw_capability, str) and raw_capability
        else ".".join(
            (
                spec.capability_prefix,
                _safe_capability_segment(spec.provider_id),
                _safe_capability_segment(tool.name),
            )
        )
    )
    read_only = bool(annotations.get("readOnlyHint", False))
    destructive = bool(annotations.get("destructiveHint", False))
    side_effects = (
        "destructive" if destructive else "read-only" if read_only else "stateful"
    )
    determinism = str(annotations.get("ari_determinism") or "conditional")
    if determinism not in {
        "deterministic",
        "seeded",
        "conditional",
        "stochastic",
        "live-data",
    }:
        determinism = "conditional"
    permissions = annotations.get("ari_permissions")
    if not isinstance(permissions, list) or not all(
        isinstance(item, str) for item in permissions
    ):
        permissions = spec.default_permissions
    lifecycle_raw = annotations.get("ari_async_lifecycle")
    lifecycle = (
        ProviderAsyncLifecycleV1.model_validate(lifecycle_raw)
        if isinstance(lifecycle_raw, dict)
        else None
    )
    semantics = annotations.get("ari_semantics")
    units = annotations.get("ari_units")
    limitations = annotations.get("ari_limitations")
    backend_lineage = annotations.get("ari_backend_lineage")
    data_lineage = annotations.get("ari_data_lineage")
    return CanonicalToolDescriptorV1.create(
        source_ids=[spec.source_id],
        provider_id=spec.provider_id,
        provider_version=spec.provider_version,
        provider_digest=spec.provider_digest,
        adapter_id=STDIO_ADAPTER_ID,
        adapter_version=STDIO_ADAPTER_VERSION,
        adapter_digest=spec.adapter_digest,
        name=tool.name,
        provider_tool_name=tool.name,
        capability_ref=capability,
        description=tool.description,
        input_schema=tool.input_schema,
        output_schema=tool.output_schema,
        defaults=_schema_defaults(tool.input_schema),
        annotations=annotations,
        side_effects=side_effects,
        determinism=determinism,
        permissions=permissions,
        semantics=semantics if isinstance(semantics, dict) else {},
        units=units if isinstance(units, dict) else {},
        limitations=limitations if isinstance(limitations, list) else [],
        backend_lineage=(backend_lineage if isinstance(backend_lineage, list) else []),
        data_lineage=data_lineage if isinstance(data_lineage, list) else [],
        leaf_identity=leaf_identity,
        origin_chains=[origin_chain],
        equivalence_key=(
            str(annotations["ari_equivalence_key"])
            if annotations.get("ari_equivalence_key")
            else None
        ),
        independence_group=str(
            annotations.get("ari_independence_group") or spec.provider_id
        ),
        async_lifecycle=lifecycle,
    )


class StdioCatalogSource:
    def __init__(
        self,
        spec: StdioSourceSpecV1,
        adapter: ProviderAdapter | None = None,
    ) -> None:
        self.spec = spec
        self._locked_source = spec.to_locked_source()
        self.adapter = adapter or StdioMCPAdapter(
            spec.launcher,
            expected_provider_digest=spec.provider_digest,
            timeout_seconds=spec.timeout_seconds,
            max_pages=spec.max_pages,
            max_tools=spec.max_tools,
        )

    @property
    def locked_source(self) -> LockedSourceV1:
        return self._locked_source

    async def sync(self) -> list[CatalogCandidateV1]:
        tools = await self.adapter.list_tools()
        return [
            CatalogCandidateV1(
                descriptor=_descriptor_from_tool(self.spec, tool),
                evidence=self.spec.evidence,
            )
            for tool in tools
        ]


class StaticCatalogSource:
    """Directly injected fixture source; absent from config deserialization."""

    def __init__(
        self,
        locked_source: LockedSourceV1,
        candidates: list[CatalogCandidateV1],
    ) -> None:
        if locked_source.kind != "fixture":
            raise ValueError("StaticCatalogSource requires kind=fixture")
        self._locked_source = locked_source
        self._candidates = list(candidates)

    @property
    def locked_source(self) -> LockedSourceV1:
        return self._locked_source

    async def sync(self) -> list[CatalogCandidateV1]:
        return list(self._candidates)


def load_source_specs(path: str | Path) -> list[StdioSourceSpecV1]:
    """Load production source declarations; fixture/static kinds are rejected."""

    source_path = Path(path)
    try:
        raw = yaml.safe_load(source_path.read_text(encoding="utf-8")) or {}
        document = SourcesDocumentV1.model_validate(raw)
    except (OSError, yaml.YAMLError, ValidationError, ValueError) as exc:
        raise CatalogSourceError(
            f"invalid sources document {source_path}: {exc}"
        ) from exc
    ids = [source.source_id for source in document.sources]
    if len(ids) != len(set(ids)):
        raise CatalogSourceError("sources document contains duplicate source_id values")
    return sorted(document.sources, key=lambda source: source.source_id)


def source_document_digest(path: str | Path) -> str:
    specs = load_source_specs(path)
    return sha256_digest([spec.model_dump(mode="json") for spec in specs])


__all__ = [
    "CatalogCandidateV1",
    "CatalogSource",
    "CatalogSourceError",
    "SOURCES_V1",
    "SourcesDocumentV1",
    "StaticCatalogSource",
    "StdioCatalogSource",
    "StdioSourceSpecV1",
    "load_source_specs",
    "source_document_digest",
]
