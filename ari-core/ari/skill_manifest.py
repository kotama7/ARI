"""Versioned contract for ARI MCP Skill packages.

``skill.yaml`` is the canonical source for package identity, process startup,
tool policy, and compatibility metadata.  This module intentionally has no MCP
runtime dependency, so manifests can be validated by packaging and CI jobs in a
clean interpreter.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)


MANIFEST_FILENAME = "skill.yaml"
LEGACY_MCP_RESULT_V1 = "ari.legacy-mcp-result/v1"
RESULT_ENVELOPE_V1 = "ari.result-envelope/v1"

_KEBAB_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_TOOL_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_REF_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_ENV_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")
_VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")


class SkillManifestError(ValueError):
    """Raised when a canonical Skill manifest cannot be loaded or validated."""


class SkillEntrypointV1(BaseModel):
    """How ari-core launches one Skill server."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    transport: Literal["stdio"] = "stdio"
    command_kind: Literal["python"] = "python"
    module: str = "src/server.py"

    @field_validator("module")
    @classmethod
    def _relative_module(cls, value: str) -> str:
        value = value.strip()
        path = PurePosixPath(value)
        if not value or "\\" in value or path.is_absolute() or ".." in path.parts:
            raise ValueError("entrypoint.module must be a safe POSIX-relative path")
        if path.suffix != ".py":
            raise ValueError("python entrypoint.module must end in .py")
        return value


class ToolPolicyV1(BaseModel):
    """Policy inherited by tools that do not declare an override."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    phases: list[str] = Field(default_factory=lambda: ["all"])
    side_effects: Literal["read-only", "workspace-write", "stateful", "destructive"] = (
        "read-only"
    )
    determinism: Literal["deterministic", "conditional", "stochastic", "live-data"] = (
        "conditional"
    )
    timeout_class: Literal["default", "bounded", "slow", "very-slow", "async"] = (
        "default"
    )
    permissions: list[str] = Field(default_factory=list)
    result_schema: str = RESULT_ENVELOPE_V1

    @field_validator("phases")
    @classmethod
    def _valid_phases(cls, values: list[str]) -> list[str]:
        if not values:
            raise ValueError("phases must contain at least one phase")
        return _validated_tokens(values, "phase")

    @field_validator("permissions")
    @classmethod
    def _valid_permissions(cls, values: list[str]) -> list[str]:
        return _validated_tokens(values, "permission")

    @field_validator("result_schema")
    @classmethod
    def _valid_result_schema(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("result_schema cannot be empty")
        return value


class ToolManifestV1(BaseModel):
    """One tool declaration; omitted policy fields inherit ``tool_defaults``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    capability_ref: str
    description: str = ""
    phases: list[str] | None = None
    side_effects: (
        Literal["read-only", "workspace-write", "stateful", "destructive"] | None
    ) = None
    determinism: (
        Literal["deterministic", "conditional", "stochastic", "live-data"] | None
    ) = None
    timeout_class: (
        Literal["default", "bounded", "slow", "very-slow", "async"] | None
    ) = None
    permissions: list[str] | None = None
    result_schema: str | None = None

    @field_validator("name")
    @classmethod
    def _valid_name(cls, value: str) -> str:
        if not _TOOL_RE.fullmatch(value):
            raise ValueError("tool name must be a Python-style identifier")
        return value

    @field_validator("capability_ref")
    @classmethod
    def _valid_capability(cls, value: str) -> str:
        value = value.strip()
        if not _REF_RE.fullmatch(value):
            raise ValueError("capability_ref must be a lowercase dotted identifier")
        return value

    @field_validator("phases")
    @classmethod
    def _valid_optional_phases(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        if not values:
            raise ValueError("phases override cannot be empty")
        return _validated_tokens(values, "phase")

    @field_validator("permissions")
    @classmethod
    def _valid_optional_permissions(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        return _validated_tokens(values, "permission")

    @field_validator("result_schema")
    @classmethod
    def _valid_optional_result_schema(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("result_schema override cannot be empty")
        return value.strip() if value is not None else None

    def resolve(self, defaults: ToolPolicyV1) -> "ResolvedToolManifestV1":
        """Return a fully populated tool policy."""

        policy = defaults.model_dump()
        for field_name in (
            "phases",
            "side_effects",
            "determinism",
            "timeout_class",
            "permissions",
            "result_schema",
        ):
            value = getattr(self, field_name)
            if value is not None:
                policy[field_name] = value
        return ResolvedToolManifestV1(
            name=self.name,
            capability_ref=self.capability_ref,
            description=self.description,
            **policy,
        )


class ResolvedToolManifestV1(ToolPolicyV1):
    """A tool declaration after package defaults have been applied."""

    name: str
    capability_ref: str
    description: str = ""


class SkillManifestV1(BaseModel):
    """Canonical ARI Skill package manifest, schema version 1."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    name: str
    package: str
    version: str
    display_name: str = ""
    description: str = ""
    enabled_by_default: bool = True
    environment_policy: Literal["audit-pending", "complete"] = "audit-pending"
    entrypoint: SkillEntrypointV1 = Field(default_factory=SkillEntrypointV1)
    required_env: list[str] = Field(default_factory=list)
    optional_env: list[str] = Field(default_factory=list)
    tool_defaults: ToolPolicyV1 = Field(default_factory=ToolPolicyV1)
    tools: list[ToolManifestV1]

    @field_validator("name", "package")
    @classmethod
    def _valid_kebab_identifier(cls, value: str) -> str:
        if not _KEBAB_RE.fullmatch(value):
            raise ValueError("name and package must be lowercase kebab-case")
        return value

    @field_validator("version")
    @classmethod
    def _valid_version(cls, value: str) -> str:
        value = value.strip()
        if not _VERSION_RE.fullmatch(value):
            raise ValueError("version must be SemVer-compatible (for example 1.2.3)")
        return value

    @field_validator("required_env", "optional_env")
    @classmethod
    def _valid_env_names(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("environment variable names must be unique")
        invalid = [value for value in values if not _ENV_RE.fullmatch(value)]
        if invalid:
            raise ValueError(f"invalid environment variable names: {invalid}")
        return values

    @model_validator(mode="after")
    def _unique_contract(self) -> "SkillManifestV1":
        names = [tool.name for tool in self.tools]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"duplicate tool declarations: {duplicates}")
        overlap = sorted(set(self.required_env) & set(self.optional_env))
        if overlap:
            raise ValueError(
                f"environment variables cannot be required and optional: {overlap}"
            )
        return self

    def resolved_tools(self) -> tuple[ResolvedToolManifestV1, ...]:
        """Return tools with package defaults applied, preserving manifest order."""

        return tuple(tool.resolve(self.tool_defaults) for tool in self.tools)

    def tool(self, name: str) -> ResolvedToolManifestV1 | None:
        """Return one resolved declaration by runtime tool name."""

        return next((tool for tool in self.resolved_tools() if tool.name == name), None)


def _validated_tokens(values: list[str], label: str) -> list[str]:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} values must be unique")
    invalid = [value for value in values if not _KEBAB_RE.fullmatch(value)]
    if invalid:
        raise ValueError(f"invalid {label} values: {invalid}")
    return values


def _legacy_to_v1(raw: dict, path: Path) -> dict:
    """Conservatively adapt a pre-v1 ``skill.yaml`` for transition-only use."""

    package = path.parent.name
    entrypoint = raw.get("entrypoint", "src/server.py")
    if isinstance(entrypoint, str):
        entrypoint = {
            "transport": "stdio",
            "command_kind": raw.get("runtime", "python"),
            "module": entrypoint,
        }
    tools = []
    capability_prefix = package.removeprefix("ari-skill-").replace("-", ".")
    for tool in raw.get("tools") or []:
        if isinstance(tool, str):
            tools.append(
                {
                    "name": tool,
                    "capability_ref": f"ari.legacy.{capability_prefix}.{tool}",
                }
            )
        elif isinstance(tool, dict):
            tools.append(tool)
    return {
        "schema_version": 1,
        "name": raw.get("name") or package,
        "package": package,
        "version": str(raw.get("version") or "0.0.0"),
        "display_name": raw.get("display_name", ""),
        "description": raw.get("description", ""),
        "entrypoint": entrypoint,
        "required_env": raw.get("required_env", raw.get("requires_env", [])) or [],
        "optional_env": raw.get("optional_env", []) or [],
        "tool_defaults": {
            "phases": ["all"],
            "side_effects": "stateful",
            "determinism": "conditional",
            "timeout_class": "default",
            "permissions": [],
            "result_schema": LEGACY_MCP_RESULT_V1,
        },
        "tools": tools,
    }


def load_skill_manifest(
    path: str | Path, *, allow_legacy: bool = False
) -> SkillManifestV1:
    """Load and validate one manifest.

    Legacy manifests are accepted only when a caller explicitly opts in.  CI and
    admission paths should leave ``allow_legacy`` false so an unversioned file
    cannot silently become a production contract.
    """

    manifest_path = Path(path)
    try:
        raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise SkillManifestError(f"cannot read {manifest_path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise SkillManifestError(f"{manifest_path}: manifest root must be a mapping")
    if "schema_version" not in raw:
        if not allow_legacy:
            raise SkillManifestError(
                f"{manifest_path}: schema_version is required for a canonical manifest"
            )
        raw = _legacy_to_v1(raw, manifest_path)
    try:
        return SkillManifestV1.model_validate(raw)
    except ValidationError as exc:
        raise SkillManifestError(f"{manifest_path}: {exc}") from exc


def resolve_skill_entrypoint(
    skill_dir: str | Path,
    manifest: SkillManifestV1,
    *,
    require_exists: bool = True,
) -> Path:
    """Resolve a manifest entrypoint while preventing package-root escape."""

    root = Path(skill_dir).resolve()
    target = (root / manifest.entrypoint.module).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise SkillManifestError(
            f"entrypoint {manifest.entrypoint.module!r} escapes package {root}"
        ) from exc
    if require_exists and not target.is_file():
        raise SkillManifestError(f"entrypoint does not exist: {target}")
    return target


def manifest_digest(manifest: SkillManifestV1) -> str:
    """Return a stable SHA-256 identity for the normalized manifest."""

    payload = json.dumps(
        manifest.model_dump(mode="json"),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def manifest_tool_ref(manifest: SkillManifestV1, tool_name: str) -> str:
    """Return the declared opaque identity for one manifest tool.

    The whole normalized manifest participates in the digest so package version,
    launcher, environment policy, and tool policy changes invalidate the
    identity. Runtime input/output-schema identity is layered on by the run
    registry after ``tools/list``.
    """

    if manifest.tool(tool_name) is None:
        raise SkillManifestError(
            f"tool {tool_name!r} is not declared by {manifest.package}"
        )
    return f"{manifest.package}/{tool_name}@sha256:{manifest_digest(manifest)}"


def legacy_mcp_document(manifest: SkillManifestV1) -> dict:
    """Render the read-only ``mcp.json`` compatibility view."""

    return {
        "schema_version": 1,
        "generated_from": MANIFEST_FILENAME,
        "name": manifest.name,
        "package": manifest.package,
        "version": manifest.version,
        "description": manifest.description,
        "tools": [tool.name for tool in manifest.tools],
        "runtime": manifest.entrypoint.command_kind,
        "entrypoint": manifest.entrypoint.module,
    }


__all__ = [
    "MANIFEST_FILENAME",
    "LEGACY_MCP_RESULT_V1",
    "RESULT_ENVELOPE_V1",
    "ResolvedToolManifestV1",
    "SkillEntrypointV1",
    "SkillManifestError",
    "SkillManifestV1",
    "ToolManifestV1",
    "ToolPolicyV1",
    "legacy_mcp_document",
    "load_skill_manifest",
    "manifest_digest",
    "manifest_tool_ref",
    "resolve_skill_entrypoint",
]
