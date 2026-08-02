"""Closed scientific and execution contracts for OpenROAD profiles."""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from models import AdmissionEvidenceV1, sanitize_text, sha256_digest
from openroad_hpc import OpenRoadExecutionV1
from openroad_identity import (
    OpenRoadArtifactPinV1,
    OpenRoadProviderPinV1,
    OpenRoadTechnologyV1,
    OpenRoadToolchainV1,
    OpenRoadWorkspaceV1,
    _SAFE_ID_RE,
    _SHA256_RE,
    _safe_relative,
    openroad_provider_release_pin,
    openroad_toolchain_line,
    openroad_workspace_digest,
    verify_openroad_provider_pin,
)


OPENROAD_EXPERIMENT_V1 = "ari.openroad-experiment/v1"
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


def _walltime_seconds(value: str) -> int:
    day_text, separator, clock = value.rpartition("-")
    days = int(day_text) if separator else 0
    if not separator:
        clock = value
    hours, minutes, seconds = (int(part) for part in clock.split(":"))
    return days * 86_400 + hours * 3_600 + minutes * 60 + seconds


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
    execution: OpenRoadExecutionV1 = Field(default_factory=OpenRoadExecutionV1)
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
        self._validate_execution()
        input_paths, output_paths = self._validate_artifact_graph()
        self._validate_metrics(output_paths)
        self._validate_commands(input_paths | output_paths)
        self._validate_evidence()
        return self

    def _validate_execution(self) -> None:
        if self.execution.backend == "slurm":
            assert self.execution.resources is not None
            assert self.execution.container is not None
            if self.execution.resources.cpus_per_task != self.toolchain.threads:
                raise ValueError(
                    "OpenROAD SLURM CPUs per task must equal the pinned thread count"
                )
            if self.execution.container.image.digest != (
                self.toolchain.execution_image_digest
            ):
                raise ValueError(
                    "OpenROAD container digest must equal the toolchain image digest"
                )
            if _walltime_seconds(self.execution.resources.walltime) < int(
                math.ceil(self.command_timeout_seconds)
            ):
                raise ValueError(
                    "OpenROAD scheduler walltime must cover command_timeout_seconds"
                )

    def _validate_artifact_graph(self) -> tuple[set[str], set[str]]:
        output_list = [item.relative_path for item in self.output_artifacts]
        output_paths = set(output_list)
        if len(output_list) != len(output_paths):
            raise ValueError("OpenROAD output artifact paths must be unique")
        input_paths = {
            artifact.relative_path for artifact in self.workspace.input_artifacts
        }
        if input_paths & output_paths:
            raise ValueError("OpenROAD inputs and outputs may not share paths")
        return input_paths, output_paths

    def _validate_metrics(self, output_paths: set[str]) -> None:
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
        required_outputs = {
            output.relative_path: output.required for output in self.output_artifacts
        }
        if any(not required_outputs[metric.source_artifact] for metric in self.metrics):
            raise ValueError(
                "OpenROAD metric source artifacts must be required outputs"
            )

    def _validate_commands(self, declared_paths: set[str]) -> None:
        previous = -1
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

    def _validate_evidence(self) -> None:
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
                "execution": self.execution,
                "commands": self.commands,
                "metrics": self.metrics,
            }
        )


__all__ = [
    "OPENROAD_EXPERIMENT_V1",
    "OpenRoadArtifactPinV1",
    "OpenRoadCommandV1",
    "OpenRoadExecutionV1",
    "OpenRoadExperimentV1",
    "OpenRoadMetricV1",
    "OpenRoadOutputArtifactV1",
    "OpenRoadProviderPinV1",
    "OpenRoadTechnologyV1",
    "OpenRoadToolchainV1",
    "OpenRoadWorkspaceV1",
    "openroad_provider_release_pin",
    "openroad_toolchain_line",
    "openroad_workspace_digest",
    "verify_openroad_provider_pin",
]
