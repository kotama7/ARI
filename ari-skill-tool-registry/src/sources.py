"""Catalog-source declarations and candidate generation."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated, Any, Literal, Protocol, TypeAlias

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from models import (
    AdmissionEvidenceV1,
    CanonicalToolDescriptorV1,
    LockedSourceV1,
    OriginHopV1,
    ProviderAsyncLifecycleV1,
    sanitize_text,
    sha256_digest,
)
from openroad_adapter import (
    OPENROAD_ADAPTER_ID,
    OPENROAD_ADAPTER_VERSION,
    OpenRoadExperimentAdapter,
    OpenRoadExperimentV1,
    OpenRoadProviderPinV1,
    openroad_adapter_digest,
    openroad_effective_launcher,
    openroad_provider_release_pin,
    verify_openroad_experiment_files,
    verify_openroad_provider_package,
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
from qiskit_adapter import (
    QISKIT_ADAPTER_ID,
    QISKIT_ADAPTER_VERSION,
    QiskitExperimentAdapter,
    QiskitExperimentV1,
    QiskitLocalBackendV1,
    QiskitProviderPinV1,
    QiskitRemoteBackendV1,
    qiskit_adapter_digest,
    qiskit_effective_launcher,
    qiskit_provider_release_pin,
    verify_qiskit_experiment_files,
    verify_qiskit_provider_package,
)
from qiskit_identity import verify_qiskit_python_distributions
from tooluniverse_adapter import (
    TOOLUNIVERSE_ADAPTER_ID,
    TOOLUNIVERSE_ADAPTER_VERSION,
    ToolUniverseCompactAdapter,
    dangerous_leaf,
    tooluniverse_adapter_digest,
    tooluniverse_release_pin,
    verify_tooluniverse_package,
    verify_tooluniverse_pin,
)


SOURCES_V1 = "ari.catalog-sources/v1"
_REF_SAFE_RE = re.compile(r"[^a-z0-9._-]+")


class CatalogSourceError(RuntimeError):
    pass


class CatalogCandidateV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    descriptor: CanonicalToolDescriptorV1
    evidence: AdmissionEvidenceV1 = Field(default_factory=AdmissionEvidenceV1)
    quarantine_reason_code: (
        Literal["policy-excluded", "unsupported-profile", "schema-drift"] | None
    ) = None
    quarantine_detail: str = ""

    @model_validator(mode="after")
    def _complete_quarantine(self) -> "CatalogCandidateV1":
        if bool(self.quarantine_reason_code) != bool(self.quarantine_detail):
            raise ValueError(
                "quarantine_reason_code and quarantine_detail must be set together"
            )
        return self


class CatalogSource(Protocol):
    @property
    def locked_source(self) -> LockedSourceV1: ...

    async def sync(self) -> list[CatalogCandidateV1]: ...


class StdioSourceSpecV1(BaseModel):
    """Reviewed declaration for one direct stdio MCP provider."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str
    kind: Literal["stdio-mcp"] = "stdio-mcp"
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


class ToolUniversePinV1(BaseModel):
    """One exact upstream release reviewed in the support matrix."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    distribution_name: Literal["tooluniverse"] = "tooluniverse"
    version: str
    wheel_digest: str
    sdist_digest: str
    repository_url: Literal["https://github.com/mims-harvard/ToolUniverse"]
    repository_commit: str
    repository_tag: str
    license_id: Literal["Apache-2.0"]
    license_digest: str
    package_tree_digest: str
    dependency_lock_digest: str
    direct_dependencies: list[str] = Field(min_length=1)
    compact_contract_digest: str
    python_requires: str

    @field_validator(
        "wheel_digest",
        "sdist_digest",
        "license_digest",
        "package_tree_digest",
        "dependency_lock_digest",
        "compact_contract_digest",
    )
    @classmethod
    def _digest(cls, value: str) -> str:
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
            raise ValueError("ToolUniverse pin digests must be SHA-256 values")
        return value

    @field_validator("repository_commit")
    @classmethod
    def _commit(cls, value: str) -> str:
        if not re.fullmatch(r"[0-9a-f]{40}", value):
            raise ValueError("ToolUniverse repository_commit must be a full SHA-1")
        return value

    @field_validator("direct_dependencies")
    @classmethod
    def _dependencies(cls, values: list[str]) -> list[str]:
        normalized = sorted({str(value).strip() for value in values})
        if len(normalized) != len(values) or any(not value for value in normalized):
            raise ValueError("ToolUniverse direct dependency inventory is invalid")
        return normalized

    def verify(self) -> None:
        verify_tooluniverse_pin(self.model_dump(mode="json"))


class ToolUniverseCategoryProfileV1(BaseModel):
    """Reviewed category/type policy shared by many collection leaves."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    profile_id: str
    categories: list[str] = Field(default_factory=list)
    tool_types: list[str] = Field(default_factory=list)
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
    independence_group: str = ""

    @field_validator("profile_id")
    @classmethod
    def _profile_id(cls, value: str) -> str:
        if not value or _REF_SAFE_RE.search(value):
            raise ValueError("profile_id must be lowercase dotted/kebab text")
        return value

    @field_validator(
        "categories",
        "tool_types",
        "permissions",
        "limitations",
        "backend_lineage",
        "data_lineage",
    )
    @classmethod
    def _unique_values(cls, values: list[str]) -> list[str]:
        normalized = sorted({str(value).strip() for value in values})
        if any(not value for value in normalized):
            raise ValueError("profile list values cannot be empty")
        return normalized

    @model_validator(mode="after")
    def _selector(self) -> "ToolUniverseCategoryProfileV1":
        if not self.categories and not self.tool_types:
            raise ValueError("ToolUniverse profiles require a category or tool type")
        if self.profile_id == "discovered-only" and (
            self.permissions
            or self.semantics
            or self.units
            or self.backend_lineage
            or self.data_lineage
        ):
            raise ValueError(
                "discovered-only profiles cannot assert scientific metadata"
            )
        return self

    def matches(self, *, category: str, tool_type: str) -> bool:
        return (
            "*" in self.categories
            or category in self.categories
            or "*" in self.tool_types
            or tool_type in self.tool_types
        )


class ToolUniverseSourceSpecV1(BaseModel):
    """One pinned ToolUniverse collection imported through compact MCP."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str
    kind: Literal["tooluniverse"] = "tooluniverse"
    provider_id: str = "tooluniverse"
    provider_digest: str
    launcher: PythonStdioLauncherV1
    support_release: str = "1.3.1"
    profiles: list[ToolUniverseCategoryProfileV1] = Field(min_length=1)
    include_categories: list[str] = Field(default_factory=list)
    exclude_categories: list[str] = Field(default_factory=list)
    capability_prefix: str = "ari.tooluniverse"
    evidence: AdmissionEvidenceV1 = Field(default_factory=AdmissionEvidenceV1)
    timeout_seconds: float = Field(default=60.0, gt=0, le=3_600)
    page_size: int = Field(default=250, ge=1, le=1_000)
    info_batch_size: int = Field(default=20, ge=1, le=100)
    max_pages: int = Field(default=1_000, ge=1, le=10_000)
    max_tools: int = Field(default=100_000, ge=1, le=1_000_000)

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

    @field_validator("include_categories", "exclude_categories")
    @classmethod
    def _categories(cls, values: list[str]) -> list[str]:
        normalized = sorted({str(value).strip() for value in values})
        if any(not value or value.startswith("-") for value in normalized):
            raise ValueError("ToolUniverse category names are invalid")
        return normalized

    @model_validator(mode="after")
    def _safe_collection_boundary(self) -> "ToolUniverseSourceSpecV1":
        self.pin.verify()
        profile_ids = [profile.profile_id for profile in self.profiles]
        if len(profile_ids) != len(set(profile_ids)):
            raise ValueError("ToolUniverse profile_id values must be unique")
        overlap = sorted(set(self.include_categories) & set(self.exclude_categories))
        if overlap:
            raise ValueError(
                f"ToolUniverse categories both included and excluded: {overlap}"
            )
        if (
            self.launcher.entrypoint is not None
            or (self.launcher.python_module != "tooluniverse.smcp_server")
            or self.launcher.python_callable != "run_stdio_server"
        ):
            raise ValueError(
                "ToolUniverse must launch the reviewed "
                "tooluniverse.smcp_server:run_stdio_server entry point"
            )
        if self.launcher.arguments:
            raise ValueError(
                "ToolUniverse base launcher arguments must be empty; the adapter "
                "constructs the bounded compact arguments"
            )
        if self.launcher.literal_env:
            raise ValueError(
                "ToolUniverse literal environment is fixed by the isolated adapter"
            )
        if "**/*" not in self.launcher.identity_globs:
            raise ValueError(
                "ToolUniverse identity_globs must include **/* to cover data/spec files"
            )
        if self.evidence.replay_fixture_digest is not None or (
            self.evidence.scientific_validation_digest is not None
        ):
            raise ValueError(
                "collection-level evidence cannot be promoted to leaf replay or "
                "scientific validation evidence"
            )
        return self

    @property
    def pin(self) -> ToolUniversePinV1:
        return ToolUniversePinV1.model_validate(
            tooluniverse_release_pin(self.support_release)
        )

    @property
    def provider_version(self) -> str:
        return self.pin.version

    @property
    def effective_launcher(self) -> PythonStdioLauncherV1:
        arguments = ["--compact-mode", "--no-search", "--max-workers", "1"]
        if self.include_categories:
            arguments.extend(["--categories", *self.include_categories])
        if self.exclude_categories:
            arguments.extend(["--exclude-categories", *self.exclude_categories])
        return self.launcher.model_copy(update={"arguments": arguments})

    def verify(self) -> None:
        self.pin.verify()
        verify_tooluniverse_package(self.launcher, self.pin.model_dump(mode="json"))
        actual = provider_digest(self.effective_launcher)
        if actual != self.provider_digest:
            raise CatalogSourceError(
                f"source {self.source_id} provider digest drift: "
                f"expected {self.provider_digest}, got {actual}"
            )

    @property
    def adapter_digest(self) -> str:
        return tooluniverse_adapter_digest()

    @property
    def source_digest(self) -> str:
        return sha256_digest(self.model_dump(mode="json"))

    def matching_profiles(
        self, *, category: str, tool_type: str
    ) -> list[ToolUniverseCategoryProfileV1]:
        return [
            profile
            for profile in self.profiles
            if profile.matches(category=category, tool_type=tool_type)
        ]

    def to_locked_source(self, *, verify: bool = True) -> LockedSourceV1:
        if verify:
            self.verify()
        return LockedSourceV1(
            source_id=self.source_id,
            kind="tooluniverse",
            source_digest=self.source_digest,
            provider_id=self.provider_id,
            provider_version=self.provider_version,
            provider_digest=self.provider_digest,
            adapter_id=TOOLUNIVERSE_ADAPTER_ID,
            adapter_version=TOOLUNIVERSE_ADAPTER_VERSION,
            adapter_digest=self.adapter_digest,
            runtime={
                "launcher": self.effective_launcher.model_dump(mode="json"),
                "pin": self.pin.model_dump(mode="json"),
                "timeout_seconds": self.timeout_seconds,
                "page_size": self.page_size,
                "info_batch_size": self.info_batch_size,
                "max_pages": self.max_pages,
                "max_tools": self.max_tools,
            },
        )


class OpenRoadSourceSpecV1(BaseModel):
    """Pinned OpenROAD MCP exposed only as immutable experiment leaves."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str
    kind: Literal["openroad"] = "openroad"
    provider_id: Literal["openroad-mcp"] = "openroad-mcp"
    provider_digest: str
    launcher: PythonStdioLauncherV1
    support_release: Literal["0.6.1"] = "0.6.1"
    experiments: list[OpenRoadExperimentV1] = Field(min_length=1, max_length=100)
    capability_ref: str = "ari.eda.openroad.place-route"
    timeout_seconds: float = Field(default=60.0, gt=0, le=3_600)
    max_concurrent_jobs: int = Field(default=4, ge=1, le=32)
    max_retained_jobs: int = Field(default=1_024, ge=32, le=100_000)

    @field_validator("source_id", "capability_ref")
    @classmethod
    def _valid_ref(cls, value: str) -> str:
        if not value or _REF_SAFE_RE.search(value):
            raise ValueError("OpenROAD source identifiers are invalid")
        return value

    @field_validator("provider_digest")
    @classmethod
    def _valid_digest(cls, value: str) -> str:
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
            raise ValueError("OpenROAD provider_digest must be a SHA-256 digest")
        return value

    @model_validator(mode="after")
    def _closed_provider_boundary(self) -> "OpenRoadSourceSpecV1":
        self.pin.verify()
        profile_ids = [profile.profile_id for profile in self.experiments]
        if len(profile_ids) != len(set(profile_ids)):
            raise ValueError("OpenROAD experiment profile_id values must be unique")
        if (
            self.launcher.entrypoint is not None
            or self.launcher.python_module != "openroad_mcp.main"
            or self.launcher.python_callable != "main"
        ):
            raise ValueError(
                "OpenROAD must launch the reviewed openroad_mcp.main:main entry point"
            )
        if self.launcher.arguments:
            raise ValueError(
                "OpenROAD base launcher arguments must be empty; ARI fixes stdio mode"
            )
        if self.launcher.literal_env:
            raise ValueError(
                "OpenROAD base launcher environment must be empty; ARI fixes its policy"
            )
        if "**/*" not in self.launcher.identity_globs:
            raise ValueError(
                "OpenROAD identity_globs must include **/* to cover the package tree"
            )
        for experiment in self.experiments:
            if Path(experiment.toolchain.executable_path).name != "openroad":
                raise ValueError(
                    "OpenROAD experiments require an executable named exactly openroad"
                )
        return self

    @property
    def pin(self) -> OpenRoadProviderPinV1:
        return OpenRoadProviderPinV1.model_validate(
            openroad_provider_release_pin(self.support_release)
        )

    @property
    def provider_version(self) -> str:
        return self.pin.version

    @property
    def effective_launcher(self) -> PythonStdioLauncherV1:
        return openroad_effective_launcher(self.launcher)

    def verify(self) -> None:
        self.pin.verify()
        verify_openroad_provider_package(
            self.launcher, self.pin.model_dump(mode="json")
        )
        actual = provider_digest(self.effective_launcher)
        if actual != self.provider_digest:
            raise CatalogSourceError(
                f"source {self.source_id} provider digest drift: "
                f"expected {self.provider_digest}, got {actual}"
            )
        for experiment in self.experiments:
            verify_openroad_experiment_files(experiment)

    @property
    def adapter_digest(self) -> str:
        return openroad_adapter_digest()

    @property
    def source_digest(self) -> str:
        return sha256_digest(self.model_dump(mode="json"))

    def to_locked_source(self, *, verify: bool = True) -> LockedSourceV1:
        if verify:
            self.verify()
        return LockedSourceV1(
            source_id=self.source_id,
            kind="openroad",
            source_digest=self.source_digest,
            provider_id=self.provider_id,
            provider_version=self.provider_version,
            provider_digest=self.provider_digest,
            adapter_id=OPENROAD_ADAPTER_ID,
            adapter_version=OPENROAD_ADAPTER_VERSION,
            adapter_digest=self.adapter_digest,
            runtime={
                "launcher": self.effective_launcher.model_dump(mode="json"),
                "pin": self.pin.model_dump(mode="json"),
                "experiments": [
                    experiment.model_dump(mode="json")
                    for experiment in self.experiments
                ],
                "timeout_seconds": self.timeout_seconds,
                "max_concurrent_jobs": self.max_concurrent_jobs,
                "max_retained_jobs": self.max_retained_jobs,
            },
        )


class QiskitSourceSpecV1(BaseModel):
    """Official Qiskit MCP providers exposed as reviewed sampling profiles."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str
    kind: Literal["qiskit"] = "qiskit"
    provider_id: Literal["qiskit-mcp-servers"] = "qiskit-mcp-servers"
    core_provider_digest: str
    core_launcher: PythonStdioLauncherV1
    core_support_release: Literal["0.3.1"] = "0.3.1"
    runtime_provider_digest: str | None = None
    runtime_launcher: PythonStdioLauncherV1 | None = None
    runtime_support_release: Literal["0.6.1"] = "0.6.1"
    experiments: list[QiskitExperimentV1] = Field(min_length=1, max_length=64)
    timeout_seconds: float = Field(default=60.0, gt=0, le=3_600)
    max_concurrent_jobs: int = Field(default=4, ge=1, le=32)
    max_retained_jobs: int = Field(default=1_024, ge=32, le=100_000)

    @field_validator("source_id")
    @classmethod
    def _valid_ref(cls, value: str) -> str:
        if not value or _REF_SAFE_RE.search(value):
            raise ValueError("Qiskit source_id is invalid")
        return value

    @field_validator("core_provider_digest", "runtime_provider_digest")
    @classmethod
    def _valid_digest(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
            raise ValueError("Qiskit provider digests must be SHA-256 values")
        return value

    @staticmethod
    def _validate_launcher(
        launcher: PythonStdioLauncherV1,
        *,
        package_name: str,
        module_name: str,
    ) -> None:
        if (
            launcher.entrypoint is not None
            or launcher.python_module != module_name
            or launcher.python_callable != "main"
            or Path(launcher.package_root).name != package_name
        ):
            raise ValueError(
                f"Qiskit must launch the reviewed {module_name}:main entry point"
            )
        if launcher.arguments:
            raise ValueError("Qiskit base launcher arguments must be empty")
        if launcher.literal_env:
            raise ValueError(
                "Qiskit base launcher environment must be empty; ARI fixes policy"
            )
        if not launcher.expected_architecture:
            raise ValueError("Qiskit launcher requires an architecture identity")
        if "**/*" not in launcher.identity_globs:
            raise ValueError(
                "Qiskit identity_globs must include **/* to cover the package tree"
            )

    @model_validator(mode="after")
    def _closed_provider_boundary(self) -> "QiskitSourceSpecV1":
        self.core_pin.verify()
        self._validate_launcher(
            self.core_launcher,
            package_name="qiskit_mcp_server",
            module_name="qiskit_mcp_server",
        )
        profile_ids = [profile.profile_id for profile in self.experiments]
        if len(profile_ids) != len(set(profile_ids)):
            raise ValueError("Qiskit experiment profile_id values must be unique")
        remote_required = any(
            isinstance(profile.backend, QiskitRemoteBackendV1)
            for profile in self.experiments
        )
        runtime_fields = (
            self.runtime_launcher is not None,
            self.runtime_provider_digest is not None,
        )
        if len(set(runtime_fields)) != 1:
            raise ValueError(
                "Qiskit Runtime launcher and provider digest must be set together"
            )
        if remote_required and not all(runtime_fields):
            raise ValueError("remote Qiskit profiles require the Runtime MCP provider")
        if self.runtime_launcher is not None:
            self.runtime_pin.verify()
            self._validate_launcher(
                self.runtime_launcher,
                package_name="qiskit_ibm_runtime_mcp_server",
                module_name="qiskit_ibm_runtime_mcp_server",
            )
        return self

    @property
    def core_pin(self) -> QiskitProviderPinV1:
        return QiskitProviderPinV1.model_validate(
            qiskit_provider_release_pin("circuit", self.core_support_release)
        )

    @property
    def runtime_pin(self) -> QiskitProviderPinV1:
        return QiskitProviderPinV1.model_validate(
            qiskit_provider_release_pin("runtime", self.runtime_support_release)
        )

    @property
    def core_effective_launcher(self) -> PythonStdioLauncherV1:
        return qiskit_effective_launcher(self.core_launcher, "circuit")

    @property
    def runtime_effective_launcher(self) -> PythonStdioLauncherV1 | None:
        if self.runtime_launcher is None:
            return None
        return qiskit_effective_launcher(self.runtime_launcher, "runtime")

    @property
    def provider_version(self) -> str:
        value = f"core-{self.core_pin.version}"
        if self.runtime_launcher is not None:
            value += f"+runtime-{self.runtime_pin.version}"
        return value

    @property
    def provider_digest(self) -> str:
        return sha256_digest(
            {
                "core_provider_digest": self.core_provider_digest,
                "runtime_provider_digest": self.runtime_provider_digest,
            }
        )

    def verify(self) -> None:
        verify_qiskit_provider_package(self.core_launcher, self.core_pin)
        actual_core = provider_digest(self.core_effective_launcher)
        if actual_core != self.core_provider_digest:
            raise CatalogSourceError(
                f"source {self.source_id} core provider digest drift: "
                f"expected {self.core_provider_digest}, got {actual_core}"
            )
        core_distributions = {
            "qiskit-mcp-server": self.core_pin.version,
            "qiskit": "2.5.1",
        }
        if any(
            isinstance(profile.backend, QiskitLocalBackendV1)
            for profile in self.experiments
        ):
            core_distributions["qiskit-aer"] = "0.17.2"
        verify_qiskit_python_distributions(self.core_launcher, core_distributions)
        if self.runtime_launcher is not None:
            assert self.runtime_provider_digest is not None
            verify_qiskit_provider_package(self.runtime_launcher, self.runtime_pin)
            effective = self.runtime_effective_launcher
            assert effective is not None
            actual_runtime = provider_digest(effective)
            if actual_runtime != self.runtime_provider_digest:
                raise CatalogSourceError(
                    f"source {self.source_id} runtime provider digest drift: "
                    f"expected {self.runtime_provider_digest}, got {actual_runtime}"
                )
            verify_qiskit_python_distributions(
                self.runtime_launcher,
                {
                    "qiskit-ibm-runtime-mcp-server": self.runtime_pin.version,
                    "qiskit-mcp-server": self.core_pin.version,
                    "qiskit": "2.5.1",
                    "qiskit-ibm-runtime": "0.48.0",
                },
            )
        for experiment in self.experiments:
            verify_qiskit_experiment_files(experiment)

    @property
    def adapter_digest(self) -> str:
        return qiskit_adapter_digest()

    @property
    def source_digest(self) -> str:
        return sha256_digest(self.model_dump(mode="json"))

    def to_locked_source(self, *, verify: bool = True) -> LockedSourceV1:
        if verify:
            self.verify()
        runtime_launcher = self.runtime_effective_launcher
        return LockedSourceV1(
            source_id=self.source_id,
            kind="qiskit",
            source_digest=self.source_digest,
            provider_id=self.provider_id,
            provider_version=self.provider_version,
            provider_digest=self.provider_digest,
            adapter_id=QISKIT_ADAPTER_ID,
            adapter_version=QISKIT_ADAPTER_VERSION,
            adapter_digest=self.adapter_digest,
            runtime={
                "core_launcher": self.core_effective_launcher.model_dump(mode="json"),
                "core_provider_digest": self.core_provider_digest,
                "core_pin": self.core_pin.model_dump(mode="json"),
                "runtime_launcher": (
                    runtime_launcher.model_dump(mode="json")
                    if runtime_launcher is not None
                    else None
                ),
                "runtime_provider_digest": self.runtime_provider_digest,
                "runtime_pin": (
                    self.runtime_pin.model_dump(mode="json")
                    if runtime_launcher is not None
                    else None
                ),
                "experiments": [
                    experiment.model_dump(mode="json")
                    for experiment in self.experiments
                ],
                "timeout_seconds": self.timeout_seconds,
                "max_concurrent_jobs": self.max_concurrent_jobs,
                "max_retained_jobs": self.max_retained_jobs,
            },
        )


SourceSpecV1: TypeAlias = Annotated[
    StdioSourceSpecV1
    | ToolUniverseSourceSpecV1
    | OpenRoadSourceSpecV1
    | QiskitSourceSpecV1,
    Field(discriminator="kind"),
]


class SourcesDocumentV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = SOURCES_V1
    sources: list[SourceSpecV1] = Field(default_factory=list)

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


def _tooluniverse_candidate(
    spec: ToolUniverseSourceSpecV1,
    tool: ProviderToolV1,
) -> CatalogCandidateV1:
    metadata = tool.annotations.get("ari_tooluniverse")
    if not isinstance(metadata, dict):
        raise CatalogSourceError(
            f"ToolUniverse leaf {tool.name!r} omitted collection metadata"
        )
    category = str(metadata.get("category") or "unknown")
    tool_type = str(metadata.get("type") or "Unknown")
    spec_digest = str(metadata.get("tool_spec_digest") or "")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", spec_digest):
        raise CatalogSourceError(
            f"ToolUniverse leaf {tool.name!r} omitted its specification digest"
        )

    quarantine_reason: (
        Literal["policy-excluded", "unsupported-profile", "schema-drift"] | None
    ) = None
    quarantine_detail = ""
    danger = dangerous_leaf(category, tool_type)
    matching = spec.matching_profiles(category=category, tool_type=tool_type)
    profile = matching[0] if len(matching) == 1 else None
    required_api_keys = metadata.get("required_api_keys")
    schema_errors = metadata.get("schema_errors")
    if isinstance(schema_errors, list) and schema_errors:
        quarantine_reason = "schema-drift"
        quarantine_detail = (
            "upstream leaf schema is not valid JSON Schema Draft 2020-12: "
            + "; ".join(sanitize_text(item, limit=500) for item in schema_errors)
        )
    elif danger:
        quarantine_reason = "policy-excluded"
        quarantine_detail = danger
    elif len(matching) != 1:
        quarantine_reason = "unsupported-profile"
        quarantine_detail = (
            f"leaf must match exactly one reviewed category profile; matched "
            f"{[item.profile_id for item in matching]}"
        )
    elif isinstance(required_api_keys, list) and required_api_keys:
        quarantine_reason = "policy-excluded"
        quarantine_detail = (
            "leaf requires provider credentials, but no value-free credential "
            "scope bridge is admitted"
        )

    profile_id = profile.profile_id if profile is not None else "unclassified"
    side_effects = profile.side_effects if profile is not None else "stateful"
    determinism = profile.determinism if profile is not None else "conditional"
    permissions = profile.permissions if profile is not None else []
    semantics = dict(profile.semantics) if profile is not None else {}
    semantics.update(
        {
            "collection_profile": profile_id,
            "tooluniverse_category": category,
            "tooluniverse_type": tool_type,
        }
    )
    units = dict(profile.units) if profile is not None else {}
    limitations = list(profile.limitations) if profile is not None else []
    limitations.extend(
        [
            "ToolUniverse collection review is not leaf scientific validation.",
            "ToolUniverse result caching is disabled; ARI cassette/EAR is the replay authority.",
        ]
    )
    source_file = metadata.get("source_file")
    if not source_file:
        limitations.append(
            "Upstream compact metadata does not identify a leaf implementation source file."
        )
    if quarantine_detail:
        limitations.append(quarantine_detail)

    leaf_identity = f"tooluniverse:{tool.name}"
    collection_id = f"tooluniverse@{spec.pin.version}"
    origin_chain = [
        OriginHopV1(kind="source", id=spec.source_id, digest=spec.source_digest),
        OriginHopV1(kind="collection", id=collection_id, digest=spec.pin.wheel_digest),
        OriginHopV1(
            kind="provider",
            id=f"tooluniverse-type:{tool_type}",
            digest=spec.provider_digest,
        ),
        OriginHopV1(kind="tool", id=leaf_identity, digest=spec_digest),
    ]
    capability = ".".join(
        (
            spec.capability_prefix,
            _safe_capability_segment(category),
            _safe_capability_segment(tool.name),
        )
    )
    backend_lineage = list(profile.backend_lineage) if profile is not None else []
    backend_lineage.extend([collection_id, f"tooluniverse-type:{tool_type}"])
    data_lineage = list(profile.data_lineage) if profile is not None else []
    data_lineage.append(f"tooluniverse-category:{category}")
    for key in ("endpoint", "tool_url", "package_name", "source_file"):
        value = metadata.get(key)
        if isinstance(value, (str, int, float, bool)) and str(value):
            data_lineage.append(f"{key}:{sanitize_text(value, limit=500)}")
    annotations = dict(tool.annotations)
    annotations["ari_tooluniverse_profile"] = profile_id

    descriptor = CanonicalToolDescriptorV1.create(
        source_ids=[spec.source_id],
        provider_id=spec.provider_id,
        provider_version=spec.provider_version,
        provider_digest=spec.provider_digest,
        adapter_id=TOOLUNIVERSE_ADAPTER_ID,
        adapter_version=TOOLUNIVERSE_ADAPTER_VERSION,
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
        semantics=semantics,
        units=units,
        limitations=sorted(set(limitations)),
        backend_lineage=sorted(set(backend_lineage)),
        data_lineage=sorted(set(data_lineage)),
        leaf_identity=leaf_identity,
        origin_chains=[origin_chain],
        equivalence_key=None,
        independence_group=(
            profile.independence_group
            if profile is not None and profile.independence_group
            else f"tooluniverse:{category}"
        ),
        async_lifecycle=None,
    )
    evidence = (
        AdmissionEvidenceV1()
        if quarantine_reason is not None or profile_id == "discovered-only"
        else spec.evidence
    )
    return CatalogCandidateV1(
        descriptor=descriptor,
        evidence=evidence,
        quarantine_reason_code=quarantine_reason,
        quarantine_detail=quarantine_detail,
    )


class ToolUniverseCatalogSource:
    def __init__(
        self,
        spec: ToolUniverseSourceSpecV1,
        adapter: ProviderAdapter | None = None,
        *,
        verify_source: bool = True,
    ) -> None:
        self.spec = spec
        self._locked_source = spec.to_locked_source(verify=verify_source)
        self.adapter = adapter or ToolUniverseCompactAdapter(
            spec.effective_launcher,
            expected_provider_digest=spec.provider_digest,
            pin=spec.pin.model_dump(mode="json"),
            include_categories=spec.include_categories,
            exclude_categories=spec.exclude_categories,
            timeout_seconds=spec.timeout_seconds,
            page_size=spec.page_size,
            info_batch_size=spec.info_batch_size,
            max_pages=spec.max_pages,
            max_tools=spec.max_tools,
            verify_package=verify_source,
        )

    @property
    def locked_source(self) -> LockedSourceV1:
        return self._locked_source

    async def sync(self) -> list[CatalogCandidateV1]:
        tools = await self.adapter.list_tools()
        return [_tooluniverse_candidate(self.spec, tool) for tool in tools]


def _openroad_candidate(
    spec: OpenRoadSourceSpecV1,
    tool: ProviderToolV1,
) -> CatalogCandidateV1:
    metadata = tool.annotations.get("ari_openroad")
    if not isinstance(metadata, dict):
        raise CatalogSourceError(
            f"OpenROAD leaf {tool.name!r} omitted immutable experiment metadata"
        )
    profile_id = metadata.get("profile_id")
    matches = [
        profile for profile in spec.experiments if profile.profile_id == profile_id
    ]
    if len(matches) != 1:
        raise CatalogSourceError(
            f"OpenROAD leaf {tool.name!r} does not map to one reviewed profile"
        )
    profile = matches[0]
    if (
        tool.name != OpenRoadExperimentAdapter.leaf_name(profile.profile_id)
        or metadata.get("experiment_digest") != profile.experiment_digest
        or metadata.get("method_digest") != profile.method_digest
    ):
        raise CatalogSourceError(
            f"OpenROAD leaf {tool.name!r} drifted from its experiment profile"
        )

    lifecycle = ProviderAsyncLifecycleV1(
        handle_field="handle_id",
        state_field="status",
        status_tool="ari_openroad_status",
        result_tool="ari_openroad_result",
        cancel_tool="ari_openroad_cancel",
        handle_argument="handle_id",
        submitted_states=["submitted"],
        running_states=["running"],
        succeeded_states=["completed"],
        failed_states=["failed"],
        cancelled_states=["cancelled"],
    )
    collection_id = f"openroad-mcp@{spec.pin.version}"
    leaf_identity = f"openroad-profile:{profile.profile_id}:{profile.experiment_digest}"
    origin_chain = [
        OriginHopV1(kind="source", id=spec.source_id, digest=spec.source_digest),
        OriginHopV1(
            kind="collection", id=collection_id, digest=spec.pin.source_archive_digest
        ),
        OriginHopV1(
            kind="provider",
            id=f"openroad@{profile.toolchain.openroad_commit}",
            digest=profile.toolchain.executable_digest,
        ),
        OriginHopV1(kind="tool", id=leaf_identity, digest=profile.experiment_digest),
    ]
    semantics = {
        "experiment_digest": profile.experiment_digest,
        "method_digest": profile.method_digest,
        "execution_model": (
            "typed-slurm-container"
            if profile.execution.backend == "slurm"
            else "immutable-profile"
        ),
        "idempotency_key": "request_id",
        "session_recovery": "fail-closed",
        "toolchain": profile.toolchain.model_dump(mode="json"),
        "technology": profile.technology.model_dump(mode="json"),
        "execution": profile.execution.model_dump(mode="json"),
        "workspace_input_digest": profile.workspace.input_digest,
        "metrics": [metric.model_dump(mode="json") for metric in profile.metrics],
    }
    units = {metric.metric_id: metric.unit for metric in profile.metrics}
    limitations = [
        *profile.limitations,
        (
            "The pinned Python OpenROAD-MCP 0.6.1 release is its deprecated final "
            "Python release; npm migration requires a separately reviewed launcher."
        ),
        "ARI exposes no arbitrary Tcl, command, environment, cwd, or path argument.",
        (
            "An interrupted local MCP session cannot be resumed and fails closed."
            if profile.execution.backend == "local-mcp"
            else "Scheduler recovery requires the locked catalog and durable C06 ledger."
        ),
    ]
    backend_lineage = [
        collection_id,
        f"openroad:{profile.toolchain.openroad_commit}",
        f"orfs:{profile.toolchain.orfs_commit}",
        f"execution-image:{profile.toolchain.execution_image_digest}",
        f"architecture:{profile.toolchain.architecture}",
        f"execution-backend:{profile.execution.backend}",
    ]
    data_lineage = [
        f"workspace:{profile.workspace.input_digest}",
        f"pdk:{profile.technology.pdk_id}@{profile.technology.pdk_version}:{profile.technology.pdk_digest}",
        (
            "library:"
            f"{profile.technology.standard_cell_library_id}@"
            f"{profile.technology.standard_cell_library_version}:"
            f"{profile.technology.standard_cell_library_digest}"
        ),
        *[
            f"input:{artifact.role}:{artifact.digest}"
            for artifact in profile.workspace.input_artifacts
        ],
    ]
    descriptor = CanonicalToolDescriptorV1.create(
        source_ids=[spec.source_id],
        provider_id=spec.provider_id,
        provider_version=spec.provider_version,
        provider_digest=spec.provider_digest,
        adapter_id=OPENROAD_ADAPTER_ID,
        adapter_version=OPENROAD_ADAPTER_VERSION,
        adapter_digest=spec.adapter_digest,
        name=tool.name,
        provider_tool_name=tool.name,
        capability_ref=spec.capability_ref,
        description=tool.description,
        input_schema=tool.input_schema,
        output_schema=tool.output_schema,
        defaults=_schema_defaults(tool.input_schema),
        annotations=tool.annotations,
        side_effects="workspace-write",
        determinism="seeded",
        permissions=["process", "workspace-read", "workspace-write"],
        semantics=semantics,
        units=units,
        limitations=sorted(set(limitations)),
        backend_lineage=sorted(set(backend_lineage)),
        data_lineage=sorted(set(data_lineage)),
        leaf_identity=leaf_identity,
        origin_chains=[origin_chain],
        equivalence_key=None,
        independence_group=(
            "openroad:"
            f"{profile.technology.pdk_id}:"
            f"{profile.technology.standard_cell_library_id}:"
            f"{profile.workspace.input_digest}"
        ),
        async_lifecycle=lifecycle,
    )
    return CatalogCandidateV1(descriptor=descriptor, evidence=profile.evidence)


class OpenRoadCatalogSource:
    def __init__(
        self,
        spec: OpenRoadSourceSpecV1,
        adapter: ProviderAdapter | None = None,
        *,
        verify_source: bool = True,
    ) -> None:
        self.spec = spec
        self._locked_source = spec.to_locked_source(verify=verify_source)
        locked_names = {
            OpenRoadExperimentAdapter.leaf_name(profile.profile_id)
            for profile in spec.experiments
        }
        self.adapter = adapter or OpenRoadExperimentAdapter(
            spec.effective_launcher,
            expected_provider_digest=spec.provider_digest,
            pin=spec.pin.model_dump(mode="json"),
            experiments=spec.experiments,
            allowed_leaf_names=locked_names,
            timeout_seconds=spec.timeout_seconds,
            max_concurrent_jobs=spec.max_concurrent_jobs,
            max_retained_jobs=spec.max_retained_jobs,
            verify_package=verify_source,
        )

    @property
    def locked_source(self) -> LockedSourceV1:
        return self._locked_source

    async def sync(self) -> list[CatalogCandidateV1]:
        tools = await self.adapter.list_tools()
        return [_openroad_candidate(self.spec, tool) for tool in tools]


def _qiskit_candidate(
    spec: QiskitSourceSpecV1,
    tool: ProviderToolV1,
) -> CatalogCandidateV1:
    metadata = tool.annotations.get("ari_qiskit")
    if not isinstance(metadata, dict):
        raise CatalogSourceError(
            f"Qiskit leaf {tool.name!r} omitted immutable experiment metadata"
        )
    profile_id = metadata.get("profile_id")
    matches = [
        profile for profile in spec.experiments if profile.profile_id == profile_id
    ]
    if len(matches) != 1:
        raise CatalogSourceError(
            f"Qiskit leaf {tool.name!r} does not map to one reviewed profile"
        )
    profile = matches[0]
    backend = profile.backend
    expected_metadata = {
        "experiment_digest": profile.experiment_digest,
        "method_digest": profile.method_digest,
        "capability_ref": profile.capability_ref,
        "backend_kind": backend.kind,
        "target_digest": backend.target.target_digest,
        "circuit_digest": profile.circuit.qpy_digest,
        "shots": profile.shots,
        "seed_simulator": profile.seed_simulator,
    }
    if tool.name != QiskitExperimentAdapter.leaf_name(profile.profile_id) or any(
        metadata.get(key) != value for key, value in expected_metadata.items()
    ):
        raise CatalogSourceError(
            f"Qiskit leaf {tool.name!r} drifted from its experiment profile"
        )

    lifecycle = ProviderAsyncLifecycleV1(
        handle_field="handle_id",
        state_field="status",
        status_tool="ari_qiskit_status",
        result_tool="ari_qiskit_result",
        cancel_tool="ari_qiskit_cancel",
        handle_argument="handle_id",
        submitted_states=["submitted"],
        running_states=["running"],
        succeeded_states=["completed"],
        failed_states=["failed"],
        cancelled_states=["cancelled"],
    )
    core_collection = f"qiskit-mcp-server@{spec.core_pin.version}"
    leaf_identity = (
        f"qiskit-profile:{profile.profile_id}:{profile.experiment_digest}"
    )
    origin_chains = [
        [
            OriginHopV1(kind="source", id=spec.source_id, digest=spec.source_digest),
            OriginHopV1(
                kind="collection",
                id=core_collection,
                digest=spec.core_pin.source_archive_digest,
            ),
            OriginHopV1(
                kind="provider",
                id=f"qiskit@{profile.software.qiskit_version}",
                digest=profile.software.stack_digest,
            ),
            OriginHopV1(
                kind="tool", id=leaf_identity, digest=profile.experiment_digest
            ),
        ]
    ]
    if isinstance(backend, QiskitRemoteBackendV1):
        origin_chains.append(
            [
                OriginHopV1(
                    kind="source", id=spec.source_id, digest=spec.source_digest
                ),
                OriginHopV1(
                    kind="collection",
                    id=f"qiskit-ibm-runtime-mcp-server@{spec.runtime_pin.version}",
                    digest=spec.runtime_pin.source_archive_digest,
                ),
                OriginHopV1(
                    kind="provider",
                    id=f"ibm-quantum:{backend.backend_name}",
                    digest=backend.target.target_digest,
                ),
                OriginHopV1(
                    kind="tool", id=leaf_identity, digest=profile.experiment_digest
                ),
            ]
        )

    semantics = {
        "semantic_family": "ari.quantum.sample",
        "experiment_digest": profile.experiment_digest,
        "method_digest": profile.method_digest,
        "idempotency_key": "request_id",
        "session_recovery": "fail-closed",
        "result_schema": "ari.qiskit-result/v1",
        "result_type": "measurement-counts",
        "bitstring_order": "qiskit-classical-display-msb-left",
        "circuit": profile.circuit.model_dump(mode="json"),
        "transpilation": profile.transpilation.model_dump(mode="json"),
        "backend": backend.model_dump(mode="json"),
        "software": profile.software.model_dump(mode="json"),
        "shots": profile.shots,
        "seed_simulator": profile.seed_simulator,
        "mitigation": profile.mitigation.model_dump(mode="json"),
        "expected_outcomes": [
            item.model_dump(mode="json") for item in profile.expected_outcomes
        ],
        "max_unlisted_probability": profile.max_unlisted_probability,
    }
    units = {"counts": "shot", "probabilities": "1"}
    units.update(
        {
            f"parameter.{name}": unit
            for name, unit in profile.circuit.parameter_units.items()
        }
    )
    if isinstance(backend, QiskitLocalBackendV1) and backend.noise_model is not None:
        units.update(
            {
                "noise.one_qubit_error": "1",
                "noise.two_qubit_error": "1",
                "noise.readout_p0_given_1": "1",
                "noise.readout_p1_given_0": "1",
            }
        )
    if isinstance(backend, QiskitRemoteBackendV1):
        units.update(
            {
                "calibration.frequency": "GHz",
                "calibration.gate_error": "1",
                "calibration.readout_error": "1",
                "calibration.t1": "us",
                "calibration.t2": "us",
                "execution_time": "s",
            }
        )

    limitations = [
        *profile.limitations,
        "Shot-based sampling is statistical and does not expose an exact statevector.",
        "ARI exposes no arbitrary Python, QASM, backend, path, or provider account operation.",
        (
            "The official core MCP performs transpilation; local execution uses the "
            "separately pinned Qiskit Aer worker."
        ),
    ]
    if isinstance(backend, QiskitLocalBackendV1):
        limitations.append(
            "Qiskit Aer 0.17.2 is in reduced maintenance and requires a new "
            "support review before any version change."
        )
    else:
        limitations.extend(
            [
                "IBM backend availability, queue state, and calibration are live data.",
                "The credential is injected only into an isolated Runtime MCP process; "
                "account-management leaves are not exposed.",
                "Remote Runtime profiles do not accept parameter bindings in the "
                "reviewed MCP release.",
            ]
        )

    backend_lineage = [
        core_collection,
        f"qiskit:{profile.software.qiskit_version}",
        f"software-stack:{profile.software.stack_digest}",
        f"backend-kind:{backend.kind}",
        f"backend:{backend.backend_name}",
        f"target:{backend.target.target_digest}",
    ]
    if isinstance(backend, QiskitLocalBackendV1):
        backend_lineage.extend(
            [
                f"qiskit-aer:{profile.software.qiskit_aer_version}",
                f"simulator-method:{backend.simulator_method}",
                f"noise-model:{sha256_digest(backend.noise_model)}"
                if backend.noise_model is not None
                else "noise-model:none",
            ]
        )
        side_effects = "workspace-write"
        permissions = ["process", "workspace-read", "workspace-write"]
    else:
        backend_lineage.extend(
            [
                f"qiskit-ibm-runtime-mcp-server:{spec.runtime_pin.version}",
                f"qiskit-ibm-runtime:{profile.software.qiskit_ibm_runtime_version}",
                f"instance:{backend.instance_digest}",
                f"access-tier:{backend.access_tier_id}",
            ]
        )
        side_effects = "stateful"
        permissions = ["network", "process", "workspace-read", "workspace-write"]
    data_lineage = [
        f"qpy:{profile.circuit.qpy_digest}",
        f"target:{backend.target.target_digest}",
    ]
    if profile.golden_fixture_digest is not None:
        data_lineage.append(f"golden:{profile.golden_fixture_digest}")
    if profile.replay_fixture_digest is not None:
        data_lineage.append(f"replay:{profile.replay_fixture_digest}")

    descriptor = CanonicalToolDescriptorV1.create(
        source_ids=[spec.source_id],
        provider_id=spec.provider_id,
        provider_version=spec.provider_version,
        provider_digest=spec.provider_digest,
        adapter_id=QISKIT_ADAPTER_ID,
        adapter_version=QISKIT_ADAPTER_VERSION,
        adapter_digest=spec.adapter_digest,
        name=tool.name,
        provider_tool_name=tool.name,
        capability_ref=profile.capability_ref,
        description=tool.description,
        input_schema=tool.input_schema,
        output_schema=tool.output_schema,
        defaults=_schema_defaults(tool.input_schema),
        annotations=tool.annotations,
        side_effects=side_effects,
        determinism=profile.determinism,
        permissions=permissions,
        semantics=semantics,
        units=units,
        limitations=sorted(set(limitations)),
        backend_lineage=sorted(set(backend_lineage)),
        data_lineage=sorted(set(data_lineage)),
        leaf_identity=leaf_identity,
        origin_chains=origin_chains,
        equivalence_key=None,
        independence_group=(
            f"qiskit:{backend.kind}:{backend.backend_name}:"
            f"{profile.software.stack_digest}:{backend.target.target_digest}"
        ),
        async_lifecycle=lifecycle,
    )
    return CatalogCandidateV1(descriptor=descriptor, evidence=profile.evidence)


class QiskitCatalogSource:
    def __init__(
        self,
        spec: QiskitSourceSpecV1,
        adapter: ProviderAdapter | None = None,
        *,
        verify_source: bool = True,
    ) -> None:
        self.spec = spec
        self._locked_source = spec.to_locked_source(verify=verify_source)
        locked_names = {
            QiskitExperimentAdapter.leaf_name(profile.profile_id)
            for profile in spec.experiments
        }
        self.adapter = adapter or QiskitExperimentAdapter(
            spec.core_effective_launcher,
            core_provider_digest=spec.core_provider_digest,
            core_pin=spec.core_pin,
            runtime_launcher=spec.runtime_effective_launcher,
            runtime_provider_digest=spec.runtime_provider_digest,
            runtime_pin=(
                spec.runtime_pin if spec.runtime_launcher is not None else None
            ),
            experiments=spec.experiments,
            allowed_leaf_names=locked_names,
            timeout_seconds=spec.timeout_seconds,
            max_concurrent_jobs=spec.max_concurrent_jobs,
            max_retained_jobs=spec.max_retained_jobs,
            verify_packages=verify_source,
        )

    @property
    def locked_source(self) -> LockedSourceV1:
        return self._locked_source

    async def sync(self) -> list[CatalogCandidateV1]:
        tools = await self.adapter.list_tools()
        return [_qiskit_candidate(self.spec, tool) for tool in tools]


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


def load_source_specs(path: str | Path) -> list[SourceSpecV1]:
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


def catalog_source_from_spec(spec: SourceSpecV1) -> CatalogSource:
    if isinstance(spec, StdioSourceSpecV1):
        return StdioCatalogSource(spec)
    if isinstance(spec, ToolUniverseSourceSpecV1):
        return ToolUniverseCatalogSource(spec)
    if isinstance(spec, OpenRoadSourceSpecV1):
        return OpenRoadCatalogSource(spec)
    if isinstance(spec, QiskitSourceSpecV1):
        return QiskitCatalogSource(spec)
    raise CatalogSourceError(
        f"unsupported production source spec: {type(spec).__name__}"
    )


def source_document_digest(path: str | Path) -> str:
    specs = load_source_specs(path)
    return sha256_digest([spec.model_dump(mode="json") for spec in specs])


__all__ = [
    "CatalogCandidateV1",
    "CatalogSource",
    "CatalogSourceError",
    "SOURCES_V1",
    "OpenRoadCatalogSource",
    "OpenRoadSourceSpecV1",
    "QiskitCatalogSource",
    "QiskitSourceSpecV1",
    "SourcesDocumentV1",
    "SourceSpecV1",
    "StaticCatalogSource",
    "StdioCatalogSource",
    "StdioSourceSpecV1",
    "ToolUniverseCatalogSource",
    "ToolUniverseCategoryProfileV1",
    "ToolUniversePinV1",
    "ToolUniverseSourceSpecV1",
    "catalog_source_from_spec",
    "load_source_specs",
    "source_document_digest",
]
