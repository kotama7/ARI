"""Canonical, provider-neutral federation contracts.

Execution identity and admission identity are deliberately separate. A tool
reference changes when provider, adapter, schema, defaults, or semantic
execution metadata changes. Re-running a policy only changes the admission
decision and policy digest.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any, Literal
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


CATALOG_LOCK_V1 = "ari.catalog-lock/v1"
CATALOG_INDEX_V1 = "ari.catalog-index/v1"
TOOL_DESCRIPTOR_V1 = "ari.tool-descriptor/v1"
ADMISSION_DECISION_V1 = "ari.admission-decision/v1"
REGISTRY_HANDLE_V1 = "ari.registry-handle/v1"
CASSETTE_V1 = "ari.tool-cassette/v1"

SHA256_PATTERN = r"^sha256:[0-9a-f]{64}$"
_REF_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_CAPABILITY_REF_RE = re.compile(
    r"^[a-z0-9][a-z0-9._-]*(?:/v[1-9][0-9]*)?$"
)
_TOOL_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.:/-]*$")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SENSITIVE_KEY_RE = re.compile(
    r"(?:secret|token|password|passwd|api[_-]?key|private[_-]?key|credential)",
    re.IGNORECASE,
)
_CREDENTIAL_FIELD_RE = re.compile(
    r"^(?:api[_-]?key|apikey|secret|client[_-]?secret|password|passwd|"
    r"credential|credentials|access[_-]?token|refresh[_-]?token|token|"
    r"authorization|authentication|bearer|private[_-]?key|privatekey)$",
    re.IGNORECASE,
)
_SET_LIKE_SCHEMA_KEYS = frozenset({"required", "enum", "type"})

AdmissionLevel = Literal[
    "discovered", "callable", "reproducible", "scientifically_admitted"
]
InvocationMode = Literal["live", "record", "replay"]

ADMISSION_LEVELS: tuple[AdmissionLevel, ...] = (
    "discovered",
    "callable",
    "reproducible",
    "scientifically_admitted",
)


def canonical_value(value: Any, *, parent_key: str = "") -> Any:
    """Normalize JSON-compatible data for stable semantic hashing."""

    if isinstance(value, BaseModel):
        return canonical_value(value.model_dump(mode="json"), parent_key=parent_key)
    if isinstance(value, dict):
        return {
            str(key): canonical_value(item, parent_key=str(key))
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, list):
        items = [canonical_value(item) for item in value]
        if parent_key in _SET_LIKE_SCHEMA_KEYS:
            return sorted(items, key=canonical_json)
        return items
    if isinstance(value, tuple):
        return [canonical_value(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("non-finite numbers are not canonical JSON")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"value is not JSON-compatible: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    return json.dumps(
        canonical_value(value),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def sha256_digest(value: Any) -> str:
    return f"sha256:{hashlib.sha256(canonical_json(value).encode('utf-8')).hexdigest()}"


def sanitize_text(value: Any, *, limit: int = 2_000) -> str:
    """Bound and remove non-printing controls from untrusted provider text."""

    text = _CONTROL_RE.sub("", str(value or "")).replace("\r\n", "\n")
    return text[:limit]


def admission_rank(level: AdmissionLevel) -> int:
    return ADMISSION_LEVELS.index(level)


def meets_admission(actual: AdmissionLevel, required: AdmissionLevel) -> bool:
    return admission_rank(actual) >= admission_rank(required)


def _valid_digest(value: str) -> str:
    if not re.fullmatch(SHA256_PATTERN, value):
        raise ValueError("digest must use sha256:<64 lowercase hex>")
    return value


def _reject_sensitive_mapping(value: Any, path: str = "runtime") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key)
            if _SENSITIVE_KEY_RE.search(key_text):
                raise ValueError(f"{path}.{key_text} may not contain credentials")
            _reject_sensitive_mapping(item, f"{path}.{key_text}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_sensitive_mapping(item, f"{path}[{index}]")


def credential_field_paths(value: Any, path: str = "value") -> list[str]:
    """Find fields that would serialize credential material into evidence.

    The match is deliberately field-based rather than a substring search, so
    scientific metrics such as ``token_count`` remain valid while direct secret,
    API-key, password, and access-token arguments fail closed.
    """

    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key)
            if _CREDENTIAL_FIELD_RE.fullmatch(key_text):
                found.append(f"{path}.{key_text}")
            found.extend(credential_field_paths(item, f"{path}.{key_text}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(credential_field_paths(item, f"{path}[{index}]"))
    return found


class OriginHopV1(BaseModel):
    """One visible step in the collection-to-leaf supply chain."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["source", "collection", "provider", "tool"]
    id: str = Field(min_length=1, max_length=512)
    digest: str | None = Field(default=None, pattern=SHA256_PATTERN)


class ProviderAsyncLifecycleV1(BaseModel):
    """Provider-native asynchronous operations bound into a descriptor."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    handle_field: str = "handle_id"
    state_field: str = "status"
    status_tool: str
    result_tool: str | None = None
    cancel_tool: str | None = None
    handle_argument: str = "handle_id"
    submitted_states: list[str] = Field(
        default_factory=lambda: ["submitted", "queued", "pending"]
    )
    running_states: list[str] = Field(default_factory=lambda: ["running"])
    succeeded_states: list[str] = Field(
        default_factory=lambda: ["succeeded", "completed", "done", "ok"]
    )
    failed_states: list[str] = Field(default_factory=lambda: ["failed", "error"])
    cancelled_states: list[str] = Field(
        default_factory=lambda: ["cancelled", "canceled"]
    )

    @field_validator("handle_field", "state_field", "handle_argument", "status_tool")
    @classmethod
    def _valid_required_name(cls, value: str) -> str:
        if not _TOOL_RE.fullmatch(value):
            raise ValueError("async lifecycle names must be safe identifiers")
        return value

    @field_validator("result_tool", "cancel_tool")
    @classmethod
    def _valid_optional_name(cls, value: str | None) -> str | None:
        if value is not None and not _TOOL_RE.fullmatch(value):
            raise ValueError("async lifecycle names must be safe identifiers")
        return value

    @model_validator(mode="after")
    def _disjoint_states(self) -> "ProviderAsyncLifecycleV1":
        owners: dict[str, str] = {}
        for field_name in (
            "submitted_states",
            "running_states",
            "succeeded_states",
            "failed_states",
            "cancelled_states",
        ):
            values = [str(item).strip() for item in getattr(self, field_name)]
            if any(not item for item in values):
                raise ValueError("async lifecycle states cannot be empty")
            for item in values:
                folded = item.casefold()
                if folded in owners:
                    raise ValueError(
                        f"async state {item!r} occurs in {owners[folded]} and {field_name}"
                    )
                owners[folded] = field_name
        return self

    def classify(
        self, raw: Any
    ) -> Literal["submitted", "running", "succeeded", "failed", "cancelled", "unknown"]:
        value = str(raw).strip().casefold()
        for state, field_name in (
            ("submitted", "submitted_states"),
            ("running", "running_states"),
            ("succeeded", "succeeded_states"),
            ("failed", "failed_states"),
            ("cancelled", "cancelled_states"),
        ):
            if value in {item.casefold() for item in getattr(self, field_name)}:
                return state  # type: ignore[return-value]
        return "unknown"


class CanonicalToolDescriptorV1(BaseModel):
    """One leaf tool with immutable execution identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["ari.tool-descriptor/v1"] = TOOL_DESCRIPTOR_V1
    tool_ref: str = Field(min_length=1)
    source_ids: list[str] = Field(min_length=1)
    provider_id: str
    provider_version: str = Field(min_length=1)
    provider_digest: str = Field(pattern=SHA256_PATTERN)
    adapter_id: str
    adapter_version: str = Field(min_length=1)
    adapter_digest: str = Field(pattern=SHA256_PATTERN)
    name: str
    provider_tool_name: str
    capability_ref: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    defaults: dict[str, Any] = Field(default_factory=dict)
    annotations: dict[str, Any] = Field(default_factory=dict)
    side_effects: Literal["read-only", "workspace-write", "stateful", "destructive"] = (
        "stateful"
    )
    determinism: Literal[
        "deterministic", "seeded", "conditional", "stochastic", "live-data"
    ] = "conditional"
    permissions: list[str] = Field(default_factory=list)
    semantics: dict[str, Any] = Field(default_factory=dict)
    units: dict[str, str] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)
    backend_lineage: list[str] = Field(default_factory=list)
    data_lineage: list[str] = Field(default_factory=list)
    leaf_identity: str = Field(min_length=1, max_length=1_024)
    origin_chains: list[list[OriginHopV1]] = Field(min_length=1)
    equivalence_key: str | None = None
    independence_group: str = Field(min_length=1)
    async_lifecycle: ProviderAsyncLifecycleV1 | None = None

    @field_validator("provider_id", "adapter_id")
    @classmethod
    def _valid_ref(cls, value: str) -> str:
        if not _REF_RE.fullmatch(value):
            raise ValueError("identifier must be lowercase dotted/kebab text")
        return value

    @field_validator("capability_ref")
    @classmethod
    def _valid_capability_ref(cls, value: str) -> str:
        if not _CAPABILITY_REF_RE.fullmatch(value):
            raise ValueError(
                "capability_ref must be lowercase dotted text with an optional /vN suffix"
            )
        return value

    @field_validator("name", "provider_tool_name")
    @classmethod
    def _valid_tool_name(cls, value: str) -> str:
        if not _TOOL_RE.fullmatch(value):
            raise ValueError("tool name contains unsafe characters")
        return value

    @field_validator("description")
    @classmethod
    def _clean_description(cls, value: str) -> str:
        return sanitize_text(value)

    @field_validator("limitations")
    @classmethod
    def _clean_limitations(cls, values: list[str]) -> list[str]:
        return [sanitize_text(value, limit=500) for value in values]

    @field_validator("source_ids", "permissions")
    @classmethod
    def _unique_sorted(cls, values: list[str]) -> list[str]:
        normalized = sorted({str(value).strip() for value in values})
        if any(not value for value in normalized):
            raise ValueError("list values cannot be empty")
        return normalized

    @model_validator(mode="after")
    def _identity_matches(self) -> "CanonicalToolDescriptorV1":
        expected = tool_ref_for(self.execution_identity_payload())
        if self.tool_ref != expected:
            raise ValueError(f"tool_ref mismatch: expected {expected}")
        if len(canonical_json(self.input_schema).encode("utf-8")) > 262_144:
            raise ValueError("input schema exceeds 256 KiB")
        if len(canonical_json(self.output_schema).encode("utf-8")) > 262_144:
            raise ValueError("output schema exceeds 256 KiB")
        return self

    def execution_identity_payload(self) -> dict[str, Any]:
        """Return fields that define execution, excluding policy and aliases."""

        return {
            "provider_id": self.provider_id,
            "provider_version": self.provider_version,
            "provider_digest": self.provider_digest,
            "adapter_id": self.adapter_id,
            "adapter_version": self.adapter_version,
            "adapter_digest": self.adapter_digest,
            "provider_tool_name": self.provider_tool_name,
            "capability_ref": self.capability_ref,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "defaults": self.defaults,
            "side_effects": self.side_effects,
            "determinism": self.determinism,
            "permissions": self.permissions,
            "semantics": self.semantics,
            "units": self.units,
            "leaf_identity": self.leaf_identity,
            "equivalence_key": self.equivalence_key,
            "independence_group": self.independence_group,
            "async_lifecycle": (
                self.async_lifecycle.model_dump(mode="json")
                if self.async_lifecycle is not None
                else None
            ),
        }

    @classmethod
    def create(cls, **values: Any) -> "CanonicalToolDescriptorV1":
        provisional = dict(values)
        provisional.setdefault("schema_version", TOOL_DESCRIPTOR_V1)
        provisional["description"] = sanitize_text(provisional.get("description", ""))
        provisional["source_ids"] = sorted(set(provisional.get("source_ids") or []))
        provisional["permissions"] = sorted(set(provisional.get("permissions") or []))
        identity_fields = {
            key: value
            for key, value in provisional.items()
            if key
            in {
                "provider_id",
                "provider_version",
                "provider_digest",
                "adapter_id",
                "adapter_version",
                "adapter_digest",
                "provider_tool_name",
                "capability_ref",
                "input_schema",
                "output_schema",
                "defaults",
                "side_effects",
                "determinism",
                "permissions",
                "semantics",
                "units",
                "leaf_identity",
                "equivalence_key",
                "independence_group",
                "async_lifecycle",
            }
        }
        identity_fields.setdefault("input_schema", {})
        identity_fields.setdefault("output_schema", {})
        identity_fields.setdefault("defaults", {})
        identity_fields.setdefault("side_effects", "stateful")
        identity_fields.setdefault("determinism", "conditional")
        identity_fields.setdefault("permissions", [])
        identity_fields.setdefault("semantics", {})
        identity_fields.setdefault("units", {})
        identity_fields.setdefault("equivalence_key", None)
        identity_fields.setdefault("async_lifecycle", None)
        if isinstance(identity_fields.get("async_lifecycle"), BaseModel):
            identity_fields["async_lifecycle"] = identity_fields[
                "async_lifecycle"
            ].model_dump(mode="json")
        provisional["tool_ref"] = tool_ref_for(identity_fields)
        return cls.model_validate(provisional)


def tool_ref_for(identity_payload: dict[str, Any]) -> str:
    provider_id = str(identity_payload["provider_id"])
    leaf = str(identity_payload["leaf_identity"])
    digest = sha256_digest(identity_payload)
    return f"ari-tool://{quote(provider_id, safe='._-')}/{quote(leaf, safe='._-')}@{digest}"


class AdmissionEvidenceV1(BaseModel):
    """Value-free evidence used to compute an admission level."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    protocol_conformance: bool = False
    provider_pinned: bool = False
    launcher_verified: bool = False
    dependencies_pinned: bool = False
    replay_fixture_digest: str | None = Field(default=None, pattern=SHA256_PATTERN)
    scientific_validation_digest: str | None = Field(
        default=None, pattern=SHA256_PATTERN
    )
    limitations_documented: bool = False
    semantics_documented: bool = False
    units_documented: bool = False
    method_identity_documented: bool = False
    architecture: str = ""
    notes: list[str] = Field(default_factory=list)


class AdmissionDecisionV1(BaseModel):
    """Policy result kept separate from a descriptor's execution identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["ari.admission-decision/v1"] = ADMISSION_DECISION_V1
    tool_ref: str
    level: AdmissionLevel
    required_level: AdmissionLevel = "callable"
    policy_digest: str = Field(pattern=SHA256_PATTERN)
    evidence_digest: str = Field(pattern=SHA256_PATTERN)
    reasons: list[str] = Field(default_factory=list)

    @property
    def invokable(self) -> bool:
        return meets_admission(self.level, self.required_level)


class QuarantinedCandidateV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str
    candidate_name: str
    reason_code: Literal[
        "cycle",
        "depth-exceeded",
        "hidden-leaf",
        "descriptor-invalid",
        "provider-drift",
        "source-failure",
        "policy-excluded",
        "unsupported-profile",
        "schema-drift",
    ]
    detail: str
    candidate_digest: str = Field(pattern=SHA256_PATTERN)


class OverlapDecisionV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    capability_ref: str
    tool_refs: list[str]
    relationship: Literal[
        "exact-duplicate", "same-backend", "semantic-near-match", "independent-method"
    ]
    explanation: str


class LockedSourceV1(BaseModel):
    """Reviewed source definition embedded in the immutable catalog lock."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str
    kind: Literal["stdio-mcp", "fixture", "tooluniverse", "openroad", "qiskit"]
    source_digest: str = Field(pattern=SHA256_PATTERN)
    provider_id: str
    provider_version: str
    provider_digest: str = Field(pattern=SHA256_PATTERN)
    adapter_id: str
    adapter_version: str
    adapter_digest: str = Field(pattern=SHA256_PATTERN)
    runtime: dict[str, Any] = Field(default_factory=dict)

    @field_validator("source_id", "provider_id", "adapter_id")
    @classmethod
    def _safe_id(cls, value: str) -> str:
        if not _REF_RE.fullmatch(value):
            raise ValueError("source/provider/adapter id is invalid")
        return value

    @field_validator("runtime")
    @classmethod
    def _safe_runtime(cls, value: dict[str, Any]) -> dict[str, Any]:
        _reject_sensitive_mapping(value)
        if len(canonical_json(value).encode("utf-8")) > 65_536:
            raise ValueError("source runtime definition exceeds 64 KiB")
        return value


class CatalogLockV1(BaseModel):
    """Self-authenticating, deterministic federation snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["ari.catalog-lock/v1"] = CATALOG_LOCK_V1
    catalog_digest: str = Field(pattern=SHA256_PATTERN)
    policy_digest: str = Field(pattern=SHA256_PATTERN)
    sources: list[LockedSourceV1]
    tools: list[CanonicalToolDescriptorV1]
    admissions: list[AdmissionDecisionV1]
    quarantined: list[QuarantinedCandidateV1] = Field(default_factory=list)
    overlaps: list[OverlapDecisionV1] = Field(default_factory=list)

    @model_validator(mode="after")
    def _consistent(self) -> "CatalogLockV1":
        source_ids = [source.source_id for source in self.sources]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("catalog contains duplicate source_id values")
        tool_refs = [tool.tool_ref for tool in self.tools]
        if len(tool_refs) != len(set(tool_refs)):
            raise ValueError("catalog contains duplicate tool_ref values")
        admission_refs = [decision.tool_ref for decision in self.admissions]
        if sorted(admission_refs) != sorted(tool_refs):
            raise ValueError("catalog must contain exactly one admission per tool")
        if any(
            decision.policy_digest != self.policy_digest for decision in self.admissions
        ):
            raise ValueError(
                "every admission decision must use the catalog policy_digest"
            )
        known_sources = set(source_ids)
        for tool in self.tools:
            unknown = sorted(set(tool.source_ids) - known_sources)
            if unknown:
                raise ValueError(
                    f"tool {tool.tool_ref} refers to unknown sources: {unknown}"
                )
        expected = catalog_lock_digest(self)
        if self.catalog_digest != expected:
            raise ValueError(
                f"catalog_digest mismatch: expected {expected}, got {self.catalog_digest}"
            )
        return self


def _lock_payload(lock: CatalogLockV1 | dict[str, Any]) -> dict[str, Any]:
    payload = (
        lock.model_dump(mode="json") if isinstance(lock, CatalogLockV1) else dict(lock)
    )
    payload.pop("catalog_digest", None)
    return payload


def catalog_lock_digest(lock: CatalogLockV1 | dict[str, Any]) -> str:
    return sha256_digest(_lock_payload(lock))


class CatalogIndexEntryV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_ref: str
    name: str
    capability_ref: str
    admission_level: AdmissionLevel
    source_ids: list[str]
    terms: list[str]
    description: str


class CatalogIndexV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["ari.catalog-index/v1"] = CATALOG_INDEX_V1
    catalog_digest: str = Field(pattern=SHA256_PATTERN)
    entries: list[CatalogIndexEntryV1]


class RegistryHandleV1(BaseModel):
    """Portable provider handle bound to one immutable descriptor and source."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["ari.registry-handle/v1"] = REGISTRY_HANDLE_V1
    handle_ref: str = Field(pattern=SHA256_PATTERN)
    tool_ref: str
    source_id: str
    provider_handle: str = Field(min_length=1, max_length=1_024)
    lifecycle: ProviderAsyncLifecycleV1
    cassette_key: str | None = Field(default=None, pattern=SHA256_PATTERN)
    mode: InvocationMode

    @model_validator(mode="after")
    def _handle_matches(self) -> "RegistryHandleV1":
        expected = registry_handle_digest(self)
        if self.handle_ref != expected:
            raise ValueError("registry handle digest does not match its contents")
        return self

    @classmethod
    def create(cls, **values: Any) -> "RegistryHandleV1":
        payload = dict(values)
        payload.setdefault("schema_version", REGISTRY_HANDLE_V1)
        payload["handle_ref"] = registry_handle_digest(payload)
        return cls.model_validate(payload)


def registry_handle_digest(handle: RegistryHandleV1 | dict[str, Any]) -> str:
    payload = (
        handle.model_dump(mode="json")
        if isinstance(handle, RegistryHandleV1)
        else dict(handle)
    )
    payload.pop("handle_ref", None)
    return sha256_digest(payload)


class InvocationCassetteV1(BaseModel):
    """Self-authenticating record sufficient for credential-free replay."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["ari.tool-cassette/v1"] = CASSETTE_V1
    cassette_key: str = Field(pattern=SHA256_PATTERN)
    tool_ref: str
    arguments: dict[str, Any]
    arguments_digest: str = Field(pattern=SHA256_PATTERN)
    catalog_digest: str = Field(pattern=SHA256_PATTERN)
    policy_digest: str = Field(pattern=SHA256_PATTERN)
    selection_reason: str
    rejected_candidates: list[dict[str, Any]] = Field(default_factory=list)
    raw_response: dict[str, Any]
    result_envelope: dict[str, Any]

    @model_validator(mode="after")
    def _key_matches(self) -> "InvocationCassetteV1":
        if self.arguments_digest != sha256_digest(self.arguments):
            raise ValueError("cassette arguments_digest is invalid")
        expected = cassette_key(self.tool_ref, self.arguments)
        if self.cassette_key != expected:
            raise ValueError("cassette key is invalid")
        return self


def cassette_key(tool_ref: str, arguments: dict[str, Any]) -> str:
    return sha256_digest({"tool_ref": tool_ref, "arguments": arguments})


__all__ = [
    "ADMISSION_DECISION_V1",
    "ADMISSION_LEVELS",
    "AdmissionDecisionV1",
    "AdmissionEvidenceV1",
    "AdmissionLevel",
    "CASSETTE_V1",
    "CATALOG_INDEX_V1",
    "CATALOG_LOCK_V1",
    "CanonicalToolDescriptorV1",
    "CatalogIndexEntryV1",
    "CatalogIndexV1",
    "CatalogLockV1",
    "InvocationCassetteV1",
    "InvocationMode",
    "LockedSourceV1",
    "OriginHopV1",
    "OverlapDecisionV1",
    "ProviderAsyncLifecycleV1",
    "QuarantinedCandidateV1",
    "REGISTRY_HANDLE_V1",
    "RegistryHandleV1",
    "TOOL_DESCRIPTOR_V1",
    "admission_rank",
    "canonical_json",
    "canonical_value",
    "cassette_key",
    "catalog_lock_digest",
    "credential_field_paths",
    "meets_admission",
    "registry_handle_digest",
    "sanitize_text",
    "sha256_digest",
    "tool_ref_for",
]
