"""Pinned, restricted OpenROAD experiment adapter.

The upstream OpenROAD MCP server intentionally exposes an interactive shell.
ARI never publishes that shell.  One reviewed experiment profile becomes one
virtual asynchronous leaf whose command sequence, inputs, outputs, metrics,
toolchain, and technology are immutable catalog data.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import mimetypes
import platform
import re
import shutil
import tempfile
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from ari.public.result import ResultArtifactV1

from models import AdmissionEvidenceV1, sanitize_text, sha256_digest
from providers import (
    ProviderAdapter,
    ProviderProtocolError,
    ProviderResponseV1,
    ProviderToolV1,
    PythonStdioLauncherV1,
    StdioMCPAdapter,
    stdio_adapter_digest,
)
from storage import RegistryArtifactStore


OPENROAD_ADAPTER_ID = "ari.openroad-profile"
OPENROAD_ADAPTER_VERSION = "1.0.0"
OPENROAD_EXPERIMENT_V1 = "ari.openroad-experiment/v1"
_SUPPORT_MATRIX = (
    Path(__file__).resolve().parent.parent / "providers" / "openroad-support-v1.json"
)
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_SAFE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_REQUEST_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_SAFE_TCL_ATOM_RE = re.compile(r"^-?[A-Za-z0-9_./:+%=,@]+$")
_SAFE_TCL_LIST_RE = re.compile(r"^\{[-+A-Za-z0-9_./:,%=@ ]+\}$")
_FILE_SUFFIXES = frozenset(
    {
        ".db",
        ".def",
        ".gds",
        ".json",
        ".lef",
        ".lib",
        ".odb",
        ".rpt",
        ".sdc",
        ".spef",
        ".sv",
        ".upf",
        ".v",
    }
)
_STAGE_ORDER = {
    "setup": 0,
    "floorplan": 1,
    "placement": 2,
    "cts": 3,
    "routing": 4,
    "finishing": 5,
    "report": 6,
}
_UPSTREAM_TOOLS = frozenset(
    {
        "create_interactive_session",
        "get_session_history",
        "get_session_metrics",
        "inspect_interactive_session",
        "interactive_openroad_exec",
        "interactive_openroad_query",
        "list_interactive_sessions",
        "list_report_images",
        "read_report_image",
        "terminate_interactive_session",
    }
)
_PROVIDER_ARGUMENTS = ("--transport", "stdio", "--log-level", "ERROR")
_PROVIDER_ENV = {
    "FASTMCP_CHECK_FOR_UPDATES": "off",
    "FASTMCP_SHOW_SERVER_BANNER": "false",
    "OPENROAD_ALLOWED_COMMANDS": "openroad",
    "OPENROAD_ENABLE_COMMAND_VALIDATION": "true",
    "OPENROAD_MAX_SESSIONS": "8",
    "OPENROAD_WHITELIST_ENABLED": "true",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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
        document = json.loads(_SUPPORT_MATRIX.read_text(encoding="utf-8"))
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


def openroad_effective_launcher(
    launcher: PythonStdioLauncherV1,
) -> PythonStdioLauncherV1:
    """Apply the only admitted OpenROAD-MCP process policy."""

    return launcher.model_copy(
        update={
            "arguments": list(_PROVIDER_ARGUMENTS),
            "literal_env": dict(_PROVIDER_ENV),
        }
    )


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


OpenRoadStage = Literal[
    "setup",
    "floorplan",
    "placement",
    "cts",
    "routing",
    "finishing",
    "report",
]
OpenRoadVerb = Literal[
    "read_lef",
    "read_liberty",
    "read_verilog",
    "read_def",
    "read_db",
    "link_design",
    "read_sdc",
    "read_spef",
    "read_upf",
    "set_thread_count",
    "set_wire_rc",
    "set_routing_layers",
    "set_macro_extension",
    "set_global_routing_layer_adjustment",
    "set_placement_padding",
    "set_propagated_clock",
    "initialize_floorplan",
    "make_tracks",
    "tapcell",
    "pdngen",
    "place_pins",
    "macro_placement",
    "global_placement",
    "detailed_placement",
    "check_placement",
    "clock_tree_synthesis",
    "repair_clock_nets",
    "repair_design",
    "repair_timing",
    "global_route",
    "detailed_route",
    "check_antennas",
    "repair_antennas",
    "filler_placement",
    "estimate_parasitics",
    "write_db",
    "write_def",
    "write_gds",
    "write_verilog",
    "write_sdc",
    "write_spef",
    "write_guides",
    "report_design_area",
    "report_checks",
    "report_clock_skew",
    "report_congestion",
    "report_drc",
    "report_floating_nets",
    "report_wire_length",
    "report_worst_slack",
    "report_tns",
    "report_power",
]


class OpenRoadCommandV1(BaseModel):
    """One Tcl command represented as a closed verb plus inert atoms."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    stage: OpenRoadStage
    verb: OpenRoadVerb
    arguments: list[str] = Field(default_factory=list, max_length=64)

    @field_validator("arguments")
    @classmethod
    def _safe_atoms(cls, values: list[str]) -> list[str]:
        for value in values:
            if len(value) > 1_024 or not (
                _SAFE_TCL_ATOM_RE.fullmatch(value) or _SAFE_TCL_LIST_RE.fullmatch(value)
            ):
                raise ValueError(
                    "OpenROAD command arguments must be inert Tcl atoms or flat "
                    "brace-quoted lists"
                )
            if ".." in Path(value).parts:
                raise ValueError("OpenROAD command paths cannot traverse parents")
        return values

    @property
    def text(self) -> str:
        return " ".join((self.verb, *self.arguments))


class OpenRoadOutputArtifactV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    relative_path: str
    logical_role: str
    media_type: str
    required: bool = True
    capture: bool = True
    max_bytes: int = Field(default=100_000_000, ge=1, le=2_000_000_000)
    expected_digest: str | None = None

    @field_validator("relative_path")
    @classmethod
    def _path(cls, value: str) -> str:
        return _safe_relative(value)

    @field_validator("logical_role")
    @classmethod
    def _role(cls, value: str) -> str:
        if not _SAFE_ID_RE.fullmatch(value):
            raise ValueError("OpenROAD output logical_role is invalid")
        return value

    @field_validator("media_type")
    @classmethod
    def _media_type(cls, value: str) -> str:
        if not re.fullmatch(r"[a-z0-9.+-]+/[a-z0-9.+-]+", value):
            raise ValueError("OpenROAD artifact media_type is invalid")
        return value

    @field_validator("expected_digest")
    @classmethod
    def _optional_digest(cls, value: str | None) -> str | None:
        if value is not None and not _SHA256_RE.fullmatch(value):
            raise ValueError("expected output digest must use SHA-256")
        return value


class OpenRoadMetricV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    metric_id: str
    source_artifact: str
    json_pointer: str
    unit: Literal["ns", "ps", "um^2", "mm^2", "mW", "W", "count", "%", "ratio"]
    corner: str
    mode: str
    stage: OpenRoadStage
    expected_min: float | None = None
    expected_max: float | None = None

    @field_validator("metric_id")
    @classmethod
    def _id(cls, value: str) -> str:
        if not _SAFE_ID_RE.fullmatch(value):
            raise ValueError("OpenROAD metric_id is invalid")
        return value

    @field_validator("source_artifact")
    @classmethod
    def _source(cls, value: str) -> str:
        return _safe_relative(value)

    @field_validator("json_pointer")
    @classmethod
    def _pointer(cls, value: str) -> str:
        if not value.startswith("/") or len(value) > 1_000 or "\x00" in value:
            raise ValueError("OpenROAD metric json_pointer is invalid")
        return value

    @field_validator("corner", "mode")
    @classmethod
    def _context(cls, value: str) -> str:
        value = value.strip()
        if not value or len(value) > 200:
            raise ValueError("OpenROAD metric corner/mode is required")
        return value

    @model_validator(mode="after")
    def _range(self) -> "OpenRoadMetricV1":
        for value in (self.expected_min, self.expected_max):
            if value is not None and not math.isfinite(value):
                raise ValueError("OpenROAD expected metric ranges must be finite")
        if (
            self.expected_min is not None
            and self.expected_max is not None
            and self.expected_min > self.expected_max
        ):
            raise ValueError("OpenROAD expected metric range is reversed")
        return self


class OpenRoadExperimentV1(BaseModel):
    """Immutable scientific and execution contract for one EDA experiment."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["ari.openroad-experiment/v1"] = OPENROAD_EXPERIMENT_V1
    profile_id: str
    description: str
    toolchain: OpenRoadToolchainV1
    technology: OpenRoadTechnologyV1
    workspace: OpenRoadWorkspaceV1
    commands: list[OpenRoadCommandV1] = Field(min_length=1, max_length=2_000)
    output_artifacts: list[OpenRoadOutputArtifactV1] = Field(
        min_length=1, max_length=2_000
    )
    metrics: list[OpenRoadMetricV1] = Field(min_length=1, max_length=1_000)
    golden_fixture_digest: str | None = None
    golden_fixture_path: str | None = None
    replay_fixture_digest: str | None = None
    replay_fixture_path: str | None = None
    evidence: AdmissionEvidenceV1 = Field(default_factory=AdmissionEvidenceV1)
    limitations: list[str] = Field(min_length=1, max_length=100)
    command_timeout_seconds: float = Field(default=3_600.0, gt=0, le=172_800)
    poll_interval_seconds: float = Field(default=0.5, ge=0.05, le=10.0)

    @field_validator("profile_id")
    @classmethod
    def _profile_id(cls, value: str) -> str:
        if not _SAFE_ID_RE.fullmatch(value):
            raise ValueError("OpenROAD profile_id is invalid")
        return value

    @field_validator("description")
    @classmethod
    def _description(cls, value: str) -> str:
        value = sanitize_text(value, limit=1_000)
        if not value:
            raise ValueError("OpenROAD profile description is required")
        return value

    @field_validator("golden_fixture_digest", "replay_fixture_digest")
    @classmethod
    def _optional_digest(cls, value: str | None) -> str | None:
        if value is not None and not _SHA256_RE.fullmatch(value):
            raise ValueError("OpenROAD fixture digests must use SHA-256")
        return value

    @field_validator("golden_fixture_path", "replay_fixture_path")
    @classmethod
    def _optional_absolute_path(cls, value: str | None) -> str | None:
        if value is not None and not Path(value).is_absolute():
            raise ValueError("OpenROAD evidence fixture paths must be absolute")
        return str(Path(value)) if value is not None else None

    @field_validator("limitations")
    @classmethod
    def _limitations(cls, values: list[str]) -> list[str]:
        normalized = sorted({sanitize_text(item, limit=500) for item in values})
        if len(normalized) != len(values) or any(not item for item in normalized):
            raise ValueError("OpenROAD limitations must be unique and nonempty")
        return normalized

    @model_validator(mode="after")
    def _closed_experiment(self) -> "OpenRoadExperimentV1":
        output_paths = [item.relative_path for item in self.output_artifacts]
        if len(output_paths) != len(set(output_paths)):
            raise ValueError("OpenROAD output artifact paths must be unique")
        input_paths = {
            artifact.relative_path for artifact in self.workspace.input_artifacts
        }
        if input_paths & set(output_paths):
            raise ValueError("OpenROAD inputs and outputs may not share paths")

        metric_ids = [metric.metric_id for metric in self.metrics]
        if len(metric_ids) != len(set(metric_ids)):
            raise ValueError("OpenROAD metric_id values must be unique")
        for metric in self.metrics:
            if metric.source_artifact not in output_paths:
                raise ValueError(
                    f"metric {metric.metric_id} refers to an undeclared output"
                )
            if (
                metric.corner != self.technology.corner
                or metric.mode != self.technology.mode
            ):
                raise ValueError(
                    f"metric {metric.metric_id} corner/mode differs from technology"
                )

        previous = -1
        declared_paths = input_paths | set(output_paths)
        thread_commands = 0
        for command in self.commands:
            order = _STAGE_ORDER[command.stage]
            if order < previous:
                raise ValueError("OpenROAD command stages must be monotonic")
            previous = order
            if command.verb == "set_thread_count":
                thread_commands += 1
                if command.arguments != [str(self.toolchain.threads)]:
                    raise ValueError(
                        "set_thread_count must equal the pinned thread count"
                    )
            for argument in command.arguments:
                if Path(argument).suffix.casefold() in _FILE_SUFFIXES:
                    path = _safe_relative(argument)
                    if path not in declared_paths:
                        raise ValueError(
                            f"command refers to undeclared artifact path {path!r}"
                        )
        if thread_commands != 1:
            raise ValueError("OpenROAD profile requires exactly one set_thread_count")

        if self.evidence.replay_fixture_digest != self.replay_fixture_digest:
            raise ValueError(
                "OpenROAD replay evidence must equal the profile replay fixture"
            )
        if self.evidence.scientific_validation_digest != (self.golden_fixture_digest):
            raise ValueError(
                "OpenROAD scientific evidence must equal the golden fixture"
            )
        if (self.golden_fixture_digest is None) != (self.golden_fixture_path is None):
            raise ValueError("OpenROAD golden fixture path and digest must be paired")
        if (self.replay_fixture_digest is None) != (self.replay_fixture_path is None):
            raise ValueError("OpenROAD replay fixture path and digest must be paired")
        if self.golden_fixture_digest is not None and any(
            metric.expected_min is None or metric.expected_max is None
            for metric in self.metrics
        ):
            raise ValueError(
                "scientifically validated OpenROAD metrics require closed ranges"
            )
        required_outputs = {
            output.relative_path: output.required for output in self.output_artifacts
        }
        if any(not required_outputs[metric.source_artifact] for metric in self.metrics):
            raise ValueError(
                "OpenROAD metric source artifacts must be required outputs"
            )
        return self

    def execution_payload(self) -> dict[str, Any]:
        payload = self.model_dump(mode="json")
        for key in (
            "description",
            "evidence",
            "golden_fixture_digest",
            "golden_fixture_path",
            "replay_fixture_digest",
            "replay_fixture_path",
            "limitations",
        ):
            payload.pop(key, None)
        return payload

    @property
    def experiment_digest(self) -> str:
        return sha256_digest(self.execution_payload())

    @property
    def method_digest(self) -> str:
        return sha256_digest(
            {
                "toolchain": self.toolchain,
                "technology": self.technology,
                "commands": self.commands,
                "metrics": self.metrics,
            }
        )


def verify_openroad_provider_package(
    launcher: PythonStdioLauncherV1,
    pin: dict[str, Any],
) -> None:
    if Path(launcher.package_root).name != "openroad_mcp":
        raise ProviderProtocolError(
            "OpenROAD MCP package_root must be the exact openroad_mcp source package"
        )
    root, _executable, _entrypoint = launcher.resolve()
    if root.name != "openroad_mcp":
        raise ProviderProtocolError(
            "OpenROAD MCP package_root must be the exact openroad_mcp source package"
        )
    files: list[dict[str, Any]] = []
    total_bytes = 0
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if (
            not path.is_file()
            or "__pycache__" in path.parts
            or path.suffix in {".pyc", ".pyo"}
        ):
            continue
        size = path.stat().st_size
        total_bytes += size
        if len(files) >= 10_000 or total_bytes > 100_000_000:
            raise ProviderProtocolError("OpenROAD MCP package exceeds reviewed bounds")
        files.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size": size,
                "digest": _file_sha256(path),
            }
        )
    actual = sha256_digest(files)
    if actual != pin.get("package_tree_digest"):
        raise ProviderProtocolError(
            "OpenROAD MCP package tree drift: "
            f"expected {pin.get('package_tree_digest')}, got {actual}"
        )


def openroad_adapter_digest() -> str:
    return sha256_digest(
        {
            "adapter_source": _file_sha256(Path(__file__).resolve()),
            "generic_stdio_adapter": stdio_adapter_digest(),
            "support_matrix": _file_sha256(_SUPPORT_MATRIX),
        }
    )


def _load_evidence_fixture(path_text: str, digest: str) -> dict[str, Any]:
    path = Path(path_text)
    if path.is_symlink() or not path.is_file():
        raise ProviderProtocolError(
            "OpenROAD evidence fixture must be a regular non-symlink file"
        )
    if path.stat().st_size > 20_000_000:
        raise ProviderProtocolError("OpenROAD evidence fixture exceeds 20 MB")
    if _file_sha256(path) != digest:
        raise ProviderProtocolError("OpenROAD evidence fixture digest drifted")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderProtocolError(
            f"OpenROAD evidence fixture is invalid JSON: {exc}"
        ) from exc
    if not isinstance(document, dict):
        raise ProviderProtocolError("OpenROAD evidence fixture must be an object")
    return document


def _verify_openroad_evidence_fixtures(experiment: OpenRoadExperimentV1) -> None:
    if experiment.golden_fixture_path is not None:
        assert experiment.golden_fixture_digest is not None
        golden = _load_evidence_fixture(
            experiment.golden_fixture_path, experiment.golden_fixture_digest
        )
        expected = {
            "schema_version": "ari.openroad-golden/v1",
            "profile_id": experiment.profile_id,
            "metrics": [
                {
                    "metric_id": metric.metric_id,
                    "unit": metric.unit,
                    "corner": metric.corner,
                    "mode": metric.mode,
                    "stage": metric.stage,
                    "expected_min": metric.expected_min,
                    "expected_max": metric.expected_max,
                }
                for metric in experiment.metrics
            ],
        }
        if golden != expected:
            raise ProviderProtocolError(
                "OpenROAD golden fixture does not exactly match metric contracts"
            )

    if experiment.replay_fixture_path is not None:
        assert experiment.replay_fixture_digest is not None
        replay = _load_evidence_fixture(
            experiment.replay_fixture_path, experiment.replay_fixture_digest
        )
        if (
            set(replay)
            != {
                "schema_version",
                "profile_id",
                "experiment_digest",
                "arguments",
                "result",
            }
            or replay.get("schema_version") != "ari.openroad-replay-fixture/v1"
        ):
            raise ProviderProtocolError("OpenROAD replay fixture contract is invalid")
        if (
            replay.get("profile_id") != experiment.profile_id
            or replay.get("experiment_digest") != experiment.experiment_digest
        ):
            raise ProviderProtocolError(
                "OpenROAD replay fixture is bound to a different experiment"
            )
        arguments = replay.get("arguments")
        if (
            not isinstance(arguments, dict)
            or set(arguments) != {"request_id"}
            or not isinstance(arguments.get("request_id"), str)
            or not _REQUEST_ID_RE.fullmatch(arguments["request_id"])
        ):
            raise ProviderProtocolError("OpenROAD replay arguments are invalid")
        result = replay.get("result")
        if not isinstance(result, dict) or set(result) != {
            "status",
            "experiment_digest",
            "metrics",
        }:
            raise ProviderProtocolError("OpenROAD replay result contract is invalid")
        if (
            result.get("status") != "completed"
            or result.get("experiment_digest") != experiment.experiment_digest
            or not isinstance(result.get("metrics"), list)
        ):
            raise ProviderProtocolError("OpenROAD replay result identity is invalid")
        expected_metrics = {metric.metric_id: metric for metric in experiment.metrics}
        actual_metrics: dict[str, dict[str, Any]] = {}
        for item in result["metrics"]:
            if not isinstance(item, dict) or set(item) != {
                "metric_id",
                "value",
                "unit",
                "corner",
                "mode",
                "stage",
            }:
                raise ProviderProtocolError("OpenROAD replay metric is invalid")
            metric_id = item.get("metric_id")
            if not isinstance(metric_id, str) or metric_id in actual_metrics:
                raise ProviderProtocolError(
                    "OpenROAD replay metric identifiers are invalid"
                )
            actual_metrics[metric_id] = item
        if set(actual_metrics) != set(expected_metrics):
            raise ProviderProtocolError("OpenROAD replay metrics are incomplete")
        for metric_id, contract in expected_metrics.items():
            item = actual_metrics[metric_id]
            value = item["value"]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ProviderProtocolError("OpenROAD replay metric is not numeric")
            numeric = float(value)
            if not math.isfinite(numeric):
                raise ProviderProtocolError("OpenROAD replay metric is non-finite")
            if (
                item["unit"] != contract.unit
                or item["corner"] != contract.corner
                or item["mode"] != contract.mode
                or item["stage"] != contract.stage
                or (
                    contract.expected_min is not None
                    and numeric < contract.expected_min
                )
                or (
                    contract.expected_max is not None
                    and numeric > contract.expected_max
                )
            ):
                raise ProviderProtocolError(
                    f"OpenROAD replay metric {metric_id!r} violates its contract"
                )


def verify_openroad_experiment_files(experiment: OpenRoadExperimentV1) -> None:
    executable = Path(experiment.toolchain.executable_path)
    if executable.is_symlink() or not executable.is_file():
        raise ProviderProtocolError("OpenROAD executable must be a regular non-symlink")
    if _file_sha256(executable) != experiment.toolchain.executable_digest:
        raise ProviderProtocolError("OpenROAD executable digest drifted")
    if experiment.toolchain.architecture != platform.machine():
        raise ProviderProtocolError(
            "OpenROAD architecture mismatch: "
            f"expected {experiment.toolchain.architecture}, got {platform.machine()}"
        )

    root = Path(experiment.workspace.source_root)
    if root.is_symlink() or not root.is_dir():
        raise ProviderProtocolError(
            "OpenROAD source workspace must be a regular non-symlink directory"
        )
    declared = {
        artifact.relative_path: artifact
        for artifact in experiment.workspace.input_artifacts
    }
    actual_paths: set[str] = set()
    total_bytes = 0
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if path.is_symlink():
            raise ProviderProtocolError(
                f"OpenROAD source workspace contains a symlink: {path}"
            )
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        actual_paths.add(relative)
        artifact = declared.get(relative)
        if artifact is None:
            raise ProviderProtocolError(
                f"OpenROAD source workspace contains undeclared input {relative!r}"
            )
        total_bytes += path.stat().st_size
        if total_bytes > 2_000_000_000:
            raise ProviderProtocolError("OpenROAD source inputs exceed 2 GB")
        if _file_sha256(path) != artifact.digest:
            raise ProviderProtocolError(
                f"OpenROAD input artifact digest drifted: {relative}"
            )
    missing = sorted(set(declared) - actual_paths)
    if missing:
        raise ProviderProtocolError(f"OpenROAD input artifacts are missing: {missing}")
    _verify_openroad_evidence_fixtures(experiment)


def _decode_wrapped(response: ProviderResponseV1, operation: str) -> dict[str, Any]:
    if response.is_error:
        raise ProviderProtocolError(
            f"OpenROAD MCP {operation} failed: {sanitize_text(response.text, limit=1_000)}"
        )
    value: Any = response.structured
    if not isinstance(value, dict):
        try:
            value = json.loads(response.text)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ProviderProtocolError(
                f"OpenROAD MCP {operation} returned non-JSON"
            ) from exc
    for _depth in range(3):
        if not isinstance(value, dict) or set(value) != {"result"}:
            break
        value = value["result"]
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                break
    if not isinstance(value, dict):
        raise ProviderProtocolError(
            f"OpenROAD MCP {operation} returned a non-object result"
        )
    if value.get("error"):
        raise ProviderProtocolError(
            f"OpenROAD MCP {operation} failed: "
            f"{sanitize_text(value['error'], limit=1_000)}"
        )
    return value


def _json_pointer(document: Any, pointer: str) -> Any:
    value = document
    for raw in pointer.removeprefix("/").split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(value, dict) and token in value:
            value = value[token]
        elif isinstance(value, list) and token.isdigit() and int(token) < len(value):
            value = value[int(token)]
        else:
            raise ProviderProtocolError(
                f"OpenROAD metric JSON pointer {pointer!r} is absent"
            )
    return value


@dataclass
class _OpenRoadJob:
    handle_id: str
    experiment: OpenRoadExperimentV1
    request_id: str
    status: Literal["submitted", "running", "completed", "failed", "cancelled"] = (
        "submitted"
    )
    stage: str = "submitted"
    submitted_at: str = field(default_factory=_now)
    started_at: str | None = None
    completed_at: str | None = None
    task: asyncio.Task[None] | None = None
    response: ProviderResponseV1 | None = None
    error: str = ""


class OpenRoadExperimentAdapter:
    """Run only catalog-locked OpenROAD profiles through upstream MCP."""

    def __init__(
        self,
        launcher: PythonStdioLauncherV1,
        *,
        expected_provider_digest: str,
        pin: dict[str, Any],
        experiments: list[OpenRoadExperimentV1],
        artifact_store: RegistryArtifactStore | None = None,
        allowed_leaf_names: set[str] | None = None,
        timeout_seconds: float = 30.0,
        max_concurrent_jobs: int = 4,
        max_retained_jobs: int = 1_024,
        transport: ProviderAdapter | None = None,
        verify_package: bool = True,
        verify_contract: bool = True,
    ) -> None:
        verify_openroad_provider_pin(pin)
        if verify_package:
            verify_openroad_provider_package(launcher, pin)
        profile_ids = [item.profile_id for item in experiments]
        if len(profile_ids) != len(set(profile_ids)):
            raise ValueError("OpenROAD experiment profile_id values must be unique")
        if not 1 <= max_concurrent_jobs <= 32:
            raise ValueError("OpenROAD max_concurrent_jobs must be between 1 and 32")
        if not 32 <= max_retained_jobs <= 100_000:
            raise ValueError("OpenROAD max_retained_jobs must be between 32 and 100000")
        self.launcher = launcher
        self.expected_provider_digest = expected_provider_digest
        self.pin = dict(pin)
        self.experiments = {item.profile_id: item for item in experiments}
        self.artifact_store = artifact_store
        self.allowed_leaf_names = (
            frozenset(allowed_leaf_names) if allowed_leaf_names is not None else None
        )
        self.timeout_seconds = timeout_seconds
        self.max_concurrent_jobs = max_concurrent_jobs
        self.max_retained_jobs = max_retained_jobs
        self._job_slots = asyncio.Semaphore(max_concurrent_jobs)
        self.verify_contract = verify_contract
        self.transport = transport or StdioMCPAdapter(
            launcher,
            expected_provider_digest=expected_provider_digest,
            timeout_seconds=timeout_seconds,
            max_pages=8,
            max_tools=32,
        )
        self._jobs: dict[str, _OpenRoadJob] = {}

    @staticmethod
    def leaf_name(profile_id: str) -> str:
        return f"ari_openroad_run__{profile_id.replace('-', '_').replace('.', '_')}"

    def _virtual_tools(self) -> list[ProviderToolV1]:
        tools: list[ProviderToolV1] = []
        for profile in sorted(
            self.experiments.values(), key=lambda item: item.profile_id
        ):
            metadata = {
                "profile_id": profile.profile_id,
                "experiment_digest": profile.experiment_digest,
                "method_digest": profile.method_digest,
                "provider_release": self.pin["version"],
                "provider_commit": self.pin["repository_commit"],
                "toolchain": profile.toolchain.model_dump(mode="json"),
                "technology": profile.technology.model_dump(mode="json"),
                "workspace_input_digest": profile.workspace.input_digest,
                "metrics": [
                    {
                        "metric_id": metric.metric_id,
                        "unit": metric.unit,
                        "corner": metric.corner,
                        "mode": metric.mode,
                        "stage": metric.stage,
                        "source_artifact": metric.source_artifact,
                    }
                    for metric in profile.metrics
                ],
            }
            tools.append(
                ProviderToolV1(
                    name=self.leaf_name(profile.profile_id),
                    description=profile.description,
                    input_schema={
                        "type": "object",
                        "properties": {
                            "request_id": {
                                "type": "string",
                                "pattern": _REQUEST_ID_RE.pattern,
                                "description": (
                                    "Idempotency key for this immutable experiment"
                                ),
                            }
                        },
                        "required": ["request_id"],
                        "additionalProperties": False,
                    },
                    output_schema={
                        "type": "object",
                        "properties": {
                            "handle_id": {"type": "string"},
                            "status": {"type": "string"},
                            "experiment_digest": {"type": "string"},
                        },
                        "required": ["handle_id", "status", "experiment_digest"],
                        "additionalProperties": True,
                    },
                    annotations={"ari_openroad": metadata},
                )
            )
        return tools

    async def list_tools(self) -> list[ProviderToolV1]:
        if self.verify_contract:
            upstream = sorted(
                await self.transport.list_tools(), key=lambda item: item.name
            )
            names = {item.name for item in upstream}
            if names != _UPSTREAM_TOOLS:
                raise ProviderProtocolError(
                    "OpenROAD MCP tool surface drifted: "
                    f"expected {sorted(_UPSTREAM_TOOLS)}, got {sorted(names)}"
                )
            contract_digest = sha256_digest(
                [item.model_dump(mode="json") for item in upstream]
            )
            if contract_digest != self.pin["mcp_contract_digest"]:
                raise ProviderProtocolError(
                    "OpenROAD MCP schemas drifted from the reviewed contract"
                )
        return self._virtual_tools()

    def _profile_for_leaf(self, name: str) -> OpenRoadExperimentV1:
        if self.allowed_leaf_names is None or name not in self.allowed_leaf_names:
            raise ProviderProtocolError(
                "OpenROAD runtime accepts only a leaf from the active catalog lock"
            )
        matches = [
            profile
            for profile in self.experiments.values()
            if self.leaf_name(profile.profile_id) == name
        ]
        if len(matches) != 1:
            raise ProviderProtocolError("OpenROAD locked leaf has no unique profile")
        return matches[0]

    async def invoke(self, name: str, arguments: dict[str, Any]) -> ProviderResponseV1:
        profile = self._profile_for_leaf(name)
        if set(arguments) != {"request_id"} or not isinstance(
            arguments.get("request_id"), str
        ):
            raise ProviderProtocolError(
                "OpenROAD experiments accept only a string request_id"
            )
        request_id = arguments["request_id"]
        if not _REQUEST_ID_RE.fullmatch(request_id):
            raise ProviderProtocolError("OpenROAD request_id is invalid")
        handle_id = "openroad-" + sha256_digest(
            {
                "adapter": OPENROAD_ADAPTER_ID,
                "provider_digest": self.expected_provider_digest,
                "experiment_digest": profile.experiment_digest,
                "request_id": request_id,
            }
        ).removeprefix("sha256:")
        job = self._jobs.get(handle_id)
        if job is None:
            if len(self._jobs) >= self.max_retained_jobs:
                raise ProviderProtocolError(
                    "OpenROAD retained-job limit reached; restart or use durable "
                    "scheduler execution"
                )
            job = _OpenRoadJob(
                handle_id=handle_id,
                experiment=profile,
                request_id=request_id,
            )
            self._jobs[handle_id] = job
            job.task = asyncio.create_task(
                self._run_job(job),
                name=f"ari-openroad-{profile.profile_id}",
            )
        payload = self._status_payload(job)
        return ProviderResponseV1(
            text=json.dumps(payload, ensure_ascii=False, sort_keys=True),
            structured=payload,
        )

    @asynccontextmanager
    async def _connection(self) -> AsyncIterator[ProviderAdapter]:
        connection = getattr(self.transport, "connection", None)
        if connection is None:
            yield self.transport
            return
        async with connection() as connected:
            yield connected

    async def _call(
        self,
        transport: ProviderAdapter,
        operation: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        response = await transport.invoke(operation, arguments)
        return _decode_wrapped(response, operation)

    async def _run_command(
        self,
        transport: ProviderAdapter,
        *,
        session_id: str,
        command: OpenRoadCommandV1,
        profile: OpenRoadExperimentV1,
        transcript: list[dict[str, Any]],
        handle_id: str,
    ) -> None:
        started = asyncio.get_running_loop().time()
        initial = await self._call(
            transport,
            "interactive_openroad_exec",
            {"command": command.text, "session_id": session_id, "timeout_ms": 250},
        )
        chunks = [str(initial.get("output") or "")]
        if initial.get("error"):
            raise ProviderProtocolError(
                f"OpenROAD command {command.verb} failed: {initial['error']}"
            )
        sentinel = (
            "ARI_DONE_"
            + sha256_digest(
                {"handle_id": handle_id, "command": command.model_dump(mode="json")}
            ).removeprefix("sha256:")[:24]
        )
        while sentinel not in "\n".join(chunks):
            elapsed = asyncio.get_running_loop().time() - started
            command_timeout = profile.command_timeout_seconds
            if elapsed >= command_timeout:
                raise ProviderProtocolError(
                    f"OpenROAD command {command.verb} exceeded {command_timeout}s"
                )
            poll_ms = max(100, min(1_000, int((command_timeout - elapsed) * 1_000)))
            polled = await self._call(
                transport,
                "interactive_openroad_query",
                {
                    "command": f"puts {sentinel}",
                    "session_id": session_id,
                    "timeout_ms": poll_ms,
                },
            )
            chunks.append(str(polled.get("output") or ""))
            if polled.get("error"):
                raise ProviderProtocolError(
                    f"OpenROAD command {command.verb} failed: {polled['error']}"
                )
            if sentinel not in chunks[-1]:
                await asyncio.sleep(profile.poll_interval_seconds)
        output = "\n".join(chunks).replace(sentinel, "").strip()
        transcript.append(
            {
                "stage": command.stage,
                "verb": command.verb,
                "arguments": command.arguments,
                "output": sanitize_text(output, limit=100_000),
                "duration_seconds": round(
                    asyncio.get_running_loop().time() - started, 6
                ),
            }
        )

    @staticmethod
    def _copy_inputs(profile: OpenRoadExperimentV1, target: Path) -> None:
        source = Path(profile.workspace.source_root)
        for artifact in profile.workspace.input_artifacts:
            source_path = source / artifact.relative_path
            target_path = target / artifact.relative_path
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_path, target_path)
            if target_path.is_symlink() or _file_sha256(target_path) != artifact.digest:
                raise ProviderProtocolError(
                    "OpenROAD copied input failed digest verification: "
                    f"{artifact.relative_path}"
                )

    def _capture_artifacts(
        self,
        profile: OpenRoadExperimentV1,
        workspace: Path,
    ) -> tuple[list[dict[str, Any]], list[ResultArtifactV1], dict[str, str]]:
        input_paths = {
            artifact.relative_path for artifact in profile.workspace.input_artifacts
        }
        output_by_path = {
            artifact.relative_path: artifact for artifact in profile.output_artifacts
        }
        actual: set[str] = set()
        for path in sorted(workspace.rglob("*"), key=lambda item: item.as_posix()):
            if path.is_symlink():
                raise ProviderProtocolError(
                    f"OpenROAD run workspace contains a symlink: {path}"
                )
            if path.is_file():
                actual.add(path.relative_to(workspace).as_posix())
        unexpected = sorted(actual - input_paths - set(output_by_path))
        if unexpected:
            raise ProviderProtocolError(
                f"OpenROAD produced undeclared artifacts: {unexpected[:50]}"
            )

        manifest: list[dict[str, Any]] = []
        refs: list[ResultArtifactV1] = []
        digests: dict[str, str] = {}
        for relative, contract in sorted(output_by_path.items()):
            path = workspace / relative
            if not path.is_file():
                if contract.required:
                    raise ProviderProtocolError(
                        f"OpenROAD required artifact is missing: {relative}"
                    )
                continue
            size = path.stat().st_size
            if size > contract.max_bytes:
                raise ProviderProtocolError(
                    f"OpenROAD artifact exceeds its size limit: {relative}"
                )
            digest = _file_sha256(path)
            if contract.expected_digest is not None and digest != (
                contract.expected_digest
            ):
                raise ProviderProtocolError(
                    f"OpenROAD artifact digest is outside the golden policy: {relative}"
                )
            digests[relative] = digest
            item = {
                "relative_path": relative,
                "logical_role": contract.logical_role,
                "media_type": contract.media_type,
                "digest": digest,
                "size": size,
                "captured": bool(contract.capture and self.artifact_store is not None),
            }
            manifest.append(item)
            if contract.capture and self.artifact_store is not None:
                hexadecimal = digest.removeprefix("sha256:")
                suffix = (
                    Path(relative).suffix
                    or mimetypes.guess_extension(contract.media_type)
                    or ".bin"
                )
                logical_name = (
                    f"openroad/sha256/{hexadecimal[:2]}/{hexadecimal}{suffix}"
                )
                self.artifact_store.put(logical_name, path)
                refs.append(
                    ResultArtifactV1(
                        digest=digest,
                        media_type=contract.media_type,
                        size=size,
                        logical_role=contract.logical_role,
                        logical_name=logical_name,
                    )
                )
        return manifest, refs, digests

    @staticmethod
    def _normalize_metrics(
        profile: OpenRoadExperimentV1,
        workspace: Path,
        artifact_digests: dict[str, str],
    ) -> list[dict[str, Any]]:
        documents: dict[str, Any] = {}
        output: list[dict[str, Any]] = []
        for metric in profile.metrics:
            if metric.source_artifact not in documents:
                path = workspace / metric.source_artifact
                try:
                    documents[metric.source_artifact] = json.loads(
                        path.read_text(encoding="utf-8")
                    )
                except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
                    raise ProviderProtocolError(
                        f"OpenROAD metric artifact is invalid: {exc}"
                    ) from exc
            raw = _json_pointer(documents[metric.source_artifact], metric.json_pointer)
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                raise ProviderProtocolError(
                    f"OpenROAD metric {metric.metric_id!r} is not numeric"
                )
            value = float(raw)
            if not math.isfinite(value):
                raise ProviderProtocolError(
                    f"OpenROAD metric {metric.metric_id!r} is non-finite"
                )
            if metric.expected_min is not None and value < metric.expected_min:
                raise ProviderProtocolError(
                    f"OpenROAD metric {metric.metric_id!r} is below its golden range"
                )
            if metric.expected_max is not None and value > metric.expected_max:
                raise ProviderProtocolError(
                    f"OpenROAD metric {metric.metric_id!r} is above its golden range"
                )
            output.append(
                {
                    "metric_id": metric.metric_id,
                    "value": value,
                    "unit": metric.unit,
                    "corner": metric.corner,
                    "mode": metric.mode,
                    "stage": metric.stage,
                    "source_report": {
                        "relative_path": metric.source_artifact,
                        "digest": artifact_digests[metric.source_artifact],
                        "json_pointer": metric.json_pointer,
                    },
                    "golden_range": (
                        {
                            "min": metric.expected_min,
                            "max": metric.expected_max,
                        }
                        if metric.expected_min is not None
                        or metric.expected_max is not None
                        else None
                    ),
                }
            )
        return output

    def _store_transcript(
        self,
        job: _OpenRoadJob,
        transcript: list[dict[str, Any]],
    ) -> tuple[dict[str, Any], ResultArtifactV1 | None]:
        payload = (
            json.dumps(
                {
                    "schema_version": "ari.openroad-transcript/v1",
                    "handle_id": job.handle_id,
                    "experiment_digest": job.experiment.experiment_digest,
                    "request_id": job.request_id,
                    "commands": transcript,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        digest = f"sha256:{hashlib.sha256(payload).hexdigest()}"
        metadata = {"digest": digest, "size": len(payload), "captured": False}
        if self.artifact_store is None:
            return metadata, None
        hexadecimal = digest.removeprefix("sha256:")
        logical_name = f"openroad/sha256/{hexadecimal[:2]}/{hexadecimal}.json"
        self.artifact_store.put(logical_name, payload)
        metadata.update({"captured": True, "logical_name": logical_name})
        return metadata, ResultArtifactV1(
            digest=digest,
            media_type="application/json",
            size=len(payload),
            logical_role="openroad-session-transcript",
            logical_name=logical_name,
        )

    def _store_transcript_after_failure(
        self,
        job: _OpenRoadJob,
        transcript: list[dict[str, Any]],
    ) -> tuple[dict[str, Any], ResultArtifactV1 | None]:
        try:
            return self._store_transcript(job, transcript)
        except Exception as exc:
            return (
                {
                    "captured": False,
                    "capture_error": sanitize_text(
                        f"{type(exc).__name__}: {exc}", limit=1_000
                    ),
                },
                None,
            )

    @staticmethod
    def _terminal_response(structured: dict[str, Any]) -> ProviderResponseV1:
        structured = dict(structured)
        structured["result_digest"] = sha256_digest(structured)
        summary = {
            "handle_id": structured.get("handle_id"),
            "status": structured.get("status"),
            "experiment_digest": structured.get("experiment_digest"),
            "result_digest": structured["result_digest"],
            "metric_count": len(structured.get("metrics") or []),
            "artifact_count": len(structured.get("_ari_result_artifacts") or []),
        }
        if structured.get("error"):
            summary["error"] = sanitize_text(structured["error"], limit=2_000)
        return ProviderResponseV1(
            text=json.dumps(summary, ensure_ascii=False, sort_keys=True),
            structured=structured,
        )

    async def _run_job(self, job: _OpenRoadJob) -> None:
        try:
            async with self._job_slots:
                await self._run_job_active(job)
        except asyncio.CancelledError:
            job.status = "cancelled"
            job.stage = "cancelled"
            job.completed_at = _now()
            transcript_meta, transcript_ref = self._store_transcript_after_failure(
                job, []
            )
            structured: dict[str, Any] = {
                "handle_id": job.handle_id,
                "status": "cancelled",
                "session_transcript": transcript_meta,
            }
            if transcript_ref is not None:
                structured["_ari_result_artifacts"] = [
                    transcript_ref.model_dump(mode="json")
                ]
            job.response = self._terminal_response(structured)

    async def _run_job_active(self, job: _OpenRoadJob) -> None:
        profile = job.experiment
        job.status = "running"
        job.stage = "initializing"
        job.started_at = _now()
        transcript: list[dict[str, Any]] = []
        session_id = "ari_" + job.handle_id.removeprefix("openroad-")[:24]
        try:
            verify_openroad_experiment_files(profile)
            with tempfile.TemporaryDirectory(prefix="ari-openroad-workspace-") as text:
                workspace = Path(text)
                self._copy_inputs(profile, workspace)
                for output in profile.output_artifacts:
                    (workspace / output.relative_path).parent.mkdir(
                        parents=True, exist_ok=True
                    )
                async with self._connection() as transport:
                    created = False
                    try:
                        metric_outputs = [
                            item.relative_path
                            for item in profile.output_artifacts
                            if any(
                                metric.source_artifact == item.relative_path
                                for metric in profile.metrics
                            )
                        ]
                        metrics_path = sorted(set(metric_outputs))[0]
                        created_payload = await self._call(
                            transport,
                            "create_interactive_session",
                            {
                                "session_id": session_id,
                                "command": [
                                    profile.toolchain.executable_path,
                                    "-no_init",
                                    "-metrics",
                                    metrics_path,
                                ],
                                "env": {},
                                "cwd": str(workspace),
                            },
                        )
                        if not created_payload.get("is_alive") or (
                            created_payload.get("session_id") != session_id
                        ):
                            raise ProviderProtocolError(
                                "OpenROAD MCP did not create the bound session"
                            )
                        created = True
                        for command in profile.commands:
                            job.stage = command.stage
                            await self._run_command(
                                transport,
                                session_id=session_id,
                                command=command,
                                profile=profile,
                                transcript=transcript,
                                handle_id=job.handle_id,
                            )
                        job.stage = "collecting"
                        artifact_manifest, artifact_refs, artifact_digests = (
                            self._capture_artifacts(profile, workspace)
                        )
                        metrics = self._normalize_metrics(
                            profile, workspace, artifact_digests
                        )
                    finally:
                        if created:
                            with suppress(Exception):
                                terminated = await self._call(
                                    transport,
                                    "terminate_interactive_session",
                                    {"session_id": session_id, "force": True},
                                )
                                transcript.append(
                                    {
                                        "stage": "cleanup",
                                        "operation": "terminate_interactive_session",
                                        "terminated": bool(
                                            terminated.get("terminated", True)
                                        ),
                                    }
                                )
                transcript_meta, transcript_ref = self._store_transcript(
                    job, transcript
                )
                if transcript_ref is not None:
                    artifact_refs.append(transcript_ref)
                structured = {
                    "schema_version": "ari.openroad-result/v1",
                    "handle_id": job.handle_id,
                    "status": "completed",
                    "experiment_digest": profile.experiment_digest,
                    "method_digest": profile.method_digest,
                    "request_id": job.request_id,
                    "toolchain": profile.toolchain.model_dump(mode="json"),
                    "technology": profile.technology.model_dump(mode="json"),
                    "workspace_input_digest": profile.workspace.input_digest,
                    "metrics": metrics,
                    "artifact_manifest": artifact_manifest,
                    "session_transcript": transcript_meta,
                    "_ari_result_artifacts": [
                        item.model_dump(mode="json") for item in artifact_refs
                    ],
                    "session_recovery": "fail-closed; local MCP sessions are ephemeral",
                }
                job.status = "completed"
                job.stage = "completed"
                job.completed_at = _now()
                job.response = self._terminal_response(structured)
        except asyncio.CancelledError:
            job.status = "cancelled"
            job.stage = "cancelled"
            job.completed_at = _now()
            transcript_meta, transcript_ref = self._store_transcript_after_failure(
                job, transcript
            )
            structured: dict[str, Any] = {
                "handle_id": job.handle_id,
                "status": "cancelled",
                "session_transcript": transcript_meta,
            }
            if transcript_ref is not None:
                structured["_ari_result_artifacts"] = [
                    transcript_ref.model_dump(mode="json")
                ]
            job.response = self._terminal_response(structured)
        except Exception as exc:
            job.status = "failed"
            job.stage = "failed"
            job.completed_at = _now()
            job.error = sanitize_text(f"{type(exc).__name__}: {exc}", limit=2_000)
            transcript_meta, transcript_ref = self._store_transcript_after_failure(
                job, transcript
            )
            structured: dict[str, Any] = {
                "handle_id": job.handle_id,
                "status": "failed",
                "error": job.error,
                "session_transcript": transcript_meta,
            }
            if transcript_ref is not None:
                structured["_ari_result_artifacts"] = [
                    transcript_ref.model_dump(mode="json")
                ]
            job.response = self._terminal_response(structured)

    @staticmethod
    def _status_payload(job: _OpenRoadJob) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "handle_id": job.handle_id,
            "status": job.status,
            "stage": job.stage,
            "experiment_digest": job.experiment.experiment_digest,
            "request_id": job.request_id,
            "submitted_at": job.submitted_at,
            "started_at": job.started_at,
            "completed_at": job.completed_at,
        }
        if job.error:
            payload["error"] = job.error
        return payload

    def _job(self, provider_handle: str) -> _OpenRoadJob:
        job = self._jobs.get(provider_handle)
        if job is None:
            raise ProviderProtocolError(
                "OpenROAD session handle is unknown; recovery is fail-closed"
            )
        return job

    async def get_status(self, lifecycle, provider_handle: str) -> ProviderResponseV1:
        payload = self._status_payload(self._job(provider_handle))
        return ProviderResponseV1(
            text=json.dumps(payload, ensure_ascii=False, sort_keys=True),
            structured=payload,
        )

    async def get_result(self, lifecycle, provider_handle: str) -> ProviderResponseV1:
        job = self._job(provider_handle)
        if job.response is not None:
            return job.response
        return await self.get_status(lifecycle, provider_handle)

    async def cancel(self, lifecycle, provider_handle: str) -> ProviderResponseV1:
        job = self._job(provider_handle)
        if job.status in {"completed", "failed", "cancelled"}:
            if job.status != "cancelled":
                raise ProviderProtocolError(
                    f"OpenROAD job is already terminal: {job.status}"
                )
            assert job.response is not None
            return job.response
        assert job.task is not None
        job.task.cancel()
        with suppress(asyncio.CancelledError):
            await job.task
        assert job.response is not None
        return job.response


__all__ = [
    "OPENROAD_ADAPTER_ID",
    "OPENROAD_ADAPTER_VERSION",
    "OPENROAD_EXPERIMENT_V1",
    "OpenRoadArtifactPinV1",
    "OpenRoadCommandV1",
    "OpenRoadExperimentAdapter",
    "OpenRoadExperimentV1",
    "OpenRoadMetricV1",
    "OpenRoadOutputArtifactV1",
    "OpenRoadProviderPinV1",
    "OpenRoadTechnologyV1",
    "OpenRoadToolchainV1",
    "OpenRoadWorkspaceV1",
    "openroad_adapter_digest",
    "openroad_effective_launcher",
    "openroad_provider_release_pin",
    "openroad_toolchain_line",
    "openroad_workspace_digest",
    "verify_openroad_experiment_files",
    "verify_openroad_provider_package",
    "verify_openroad_provider_pin",
]
