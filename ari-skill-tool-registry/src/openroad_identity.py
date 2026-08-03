"""Pinned OpenROAD provider, workspace, toolchain, and technology identities."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from models import sanitize_text, sha256_digest
from providers import ProviderProtocolError


OPENROAD_SUPPORT_MATRIX = (
    Path(__file__).resolve().parent.parent / "providers" / "openroad-support-v1.json"
)
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_SAFE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


def _file_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                hasher.update(chunk)
    except OSError as exc:
        raise ProviderProtocolError(
            f"cannot read OpenROAD identity file: {exc}"
        ) from exc
    return f"sha256:{hasher.hexdigest()}"


def _safe_relative(value: str) -> str:
    path = Path(value)
    if (
        not value
        or path.is_absolute()
        or ".." in path.parts
        or any(part in {"", "."} for part in path.parts)
    ):
        raise ValueError("artifact paths must be safe workspace-relative paths")
    return path.as_posix()


def _support_document() -> dict[str, Any]:
    try:
        document = json.loads(OPENROAD_SUPPORT_MATRIX.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        raise ProviderProtocolError(
            f"OpenROAD support matrix is unavailable or invalid: {exc}"
        ) from exc
    if not isinstance(document, dict) or document.get("schema_version") != (
        "ari.openroad-support/v1"
    ):
        raise ProviderProtocolError("OpenROAD support matrix version is invalid")
    if not isinstance(document.get("provider_releases"), list):
        raise ProviderProtocolError("OpenROAD support matrix has no provider releases")
    if not isinstance(document.get("toolchain_lines"), list):
        raise ProviderProtocolError("OpenROAD support matrix has no toolchain lines")
    return document


def openroad_provider_release_pin(version: str) -> dict[str, Any]:
    matches = [
        item
        for item in _support_document()["provider_releases"]
        if item.get("version") == version
    ]
    if len(matches) != 1:
        raise ProviderProtocolError(
            f"OpenROAD MCP release {sanitize_text(version, limit=100)!r} is unsupported"
        )
    return dict(matches[0])


def verify_openroad_provider_pin(pin: dict[str, Any]) -> None:
    if pin not in _support_document()["provider_releases"]:
        raise ProviderProtocolError("OpenROAD MCP pin is not an exact reviewed release")


def openroad_toolchain_line(line_id: str) -> dict[str, Any]:
    matches = [
        item
        for item in _support_document()["toolchain_lines"]
        if item.get("line_id") == line_id
    ]
    if len(matches) != 1:
        raise ProviderProtocolError(
            f"OpenROAD toolchain line {sanitize_text(line_id, limit=100)!r} is unsupported"
        )
    return dict(matches[0])


class OpenRoadProviderPinV1(BaseModel):
    """Exact upstream OpenROAD-MCP Python release."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    distribution_name: Literal["openroad-mcp"] = "openroad-mcp"
    version: str
    repository_url: Literal["https://github.com/The-OpenROAD-Project/OpenROAD-MCP"]
    repository_commit: str
    repository_tag: str
    source_archive_digest: str
    license_id: Literal["BSD-3-Clause"]
    license_digest: str
    package_tree_digest: str
    dependency_lock_digest: str
    direct_dependencies: list[str] = Field(min_length=1)
    mcp_contract_digest: str
    python_requires: str
    distribution_status: Literal["deprecated-final"]
    maintained_distribution: Literal["npm"]

    @field_validator(
        "source_archive_digest",
        "license_digest",
        "package_tree_digest",
        "dependency_lock_digest",
        "mcp_contract_digest",
    )
    @classmethod
    def _digest(cls, value: str) -> str:
        if not _SHA256_RE.fullmatch(value):
            raise ValueError("OpenROAD provider pins require SHA-256 digests")
        return value

    @field_validator("repository_commit")
    @classmethod
    def _commit(cls, value: str) -> str:
        if not re.fullmatch(r"[0-9a-f]{40}", value):
            raise ValueError("OpenROAD provider commit must be a full Git SHA-1")
        return value

    @field_validator("direct_dependencies")
    @classmethod
    def _dependencies(cls, values: list[str]) -> list[str]:
        normalized = sorted({str(item).strip() for item in values})
        if len(normalized) != len(values) or any(not item for item in normalized):
            raise ValueError("OpenROAD provider dependency inventory is invalid")
        return normalized

    def verify(self) -> None:
        verify_openroad_provider_pin(self.model_dump(mode="json"))


class OpenRoadArtifactPinV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    relative_path: str
    digest: str
    role: Literal[
        "rtl",
        "netlist",
        "constraint",
        "technology-lef",
        "library-lef",
        "liberty",
        "def",
        "database",
        "gds",
        "spef",
        "upf",
        "flow-config",
        "other",
    ]
    media_type: str = "application/octet-stream"

    @field_validator("relative_path")
    @classmethod
    def _path(cls, value: str) -> str:
        return _safe_relative(value)

    @field_validator("digest")
    @classmethod
    def _digest(cls, value: str) -> str:
        if not _SHA256_RE.fullmatch(value):
            raise ValueError("input artifact digest must use SHA-256")
        return value


def openroad_workspace_digest(artifacts: list[OpenRoadArtifactPinV1]) -> str:
    return sha256_digest(
        [
            artifact.model_dump(mode="json")
            for artifact in sorted(artifacts, key=lambda item: item.relative_path)
        ]
    )


class OpenRoadWorkspaceV1(BaseModel):
    """Read-only source workspace copied into a fresh run directory."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_root: str
    input_artifacts: list[OpenRoadArtifactPinV1] = Field(min_length=1, max_length=2_000)
    input_digest: str

    @field_validator("source_root")
    @classmethod
    def _absolute_root(cls, value: str) -> str:
        if not Path(value).is_absolute():
            raise ValueError("OpenROAD source_root must be absolute")
        return str(Path(value))

    @field_validator("input_digest")
    @classmethod
    def _digest(cls, value: str) -> str:
        if not _SHA256_RE.fullmatch(value):
            raise ValueError("workspace input_digest must use SHA-256")
        return value

    @model_validator(mode="after")
    def _closed_inputs(self) -> "OpenRoadWorkspaceV1":
        paths = [item.relative_path for item in self.input_artifacts]
        if len(paths) != len(set(paths)):
            raise ValueError("OpenROAD input artifact paths must be unique")
        expected = openroad_workspace_digest(self.input_artifacts)
        if self.input_digest != expected:
            raise ValueError(f"workspace input_digest mismatch: expected {expected}")
        roles = {item.role for item in self.input_artifacts}
        if not roles & {"rtl", "netlist", "def", "database"}:
            raise ValueError("OpenROAD workspace requires a design input")
        if "constraint" not in roles:
            raise ValueError("OpenROAD workspace requires a constraint input")
        if not roles & {"technology-lef", "library-lef"}:
            raise ValueError("OpenROAD workspace requires LEF technology data")
        if "liberty" not in roles:
            raise ValueError("OpenROAD workspace requires a Liberty library")
        return self


class OpenRoadToolchainV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    support_line: str
    orfs_commit: str
    openroad_commit: str
    openroad_version: str
    executable_path: str
    executable_digest: str
    execution_image_digest: str
    architecture: str
    threads: int = Field(ge=1, le=256)
    seed: int = Field(ge=0, le=2**31 - 1)

    @field_validator("orfs_commit", "openroad_commit")
    @classmethod
    def _commit(cls, value: str) -> str:
        if not re.fullmatch(r"[0-9a-f]{40}", value):
            raise ValueError("OpenROAD/ORFS commits must be full Git SHA-1 values")
        return value

    @field_validator("executable_digest", "execution_image_digest")
    @classmethod
    def _digest(cls, value: str) -> str:
        if not _SHA256_RE.fullmatch(value):
            raise ValueError("OpenROAD toolchain digests must use SHA-256")
        return value

    @field_validator("executable_path")
    @classmethod
    def _absolute_executable(cls, value: str) -> str:
        if not Path(value).is_absolute():
            raise ValueError("OpenROAD executable_path must be absolute")
        return str(Path(value))

    @model_validator(mode="after")
    def _reviewed_line(self) -> "OpenRoadToolchainV1":
        line = openroad_toolchain_line(self.support_line)
        expected = {
            "orfs_commit": self.orfs_commit,
            "openroad_commit": self.openroad_commit,
        }
        if any(line.get(key) != value for key, value in expected.items()):
            raise ValueError(
                "OpenROAD and ORFS commits do not match the reviewed support line"
            )
        if not self.architecture or len(self.architecture) > 100:
            raise ValueError("OpenROAD architecture is required")
        return self


class OpenRoadTechnologyV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    pdk_id: str
    pdk_version: str
    pdk_digest: str
    pdk_license_scope: Literal["redistributable", "local-only", "restricted"]
    standard_cell_library_id: str
    standard_cell_library_version: str
    standard_cell_library_digest: str
    corner: str
    mode: str

    @field_validator("pdk_id", "standard_cell_library_id")
    @classmethod
    def _id(cls, value: str) -> str:
        if not _SAFE_ID_RE.fullmatch(value):
            raise ValueError("OpenROAD technology identifiers are invalid")
        return value

    @field_validator("pdk_digest", "standard_cell_library_digest")
    @classmethod
    def _digest(cls, value: str) -> str:
        if not _SHA256_RE.fullmatch(value):
            raise ValueError("OpenROAD technology digests must use SHA-256")
        return value

    @field_validator(
        "pdk_version",
        "standard_cell_library_version",
        "corner",
        "mode",
    )
    @classmethod
    def _nonempty(cls, value: str) -> str:
        value = value.strip()
        if not value or len(value) > 200:
            raise ValueError("OpenROAD technology metadata is required and bounded")
        return value
