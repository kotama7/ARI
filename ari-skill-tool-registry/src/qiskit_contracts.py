"""Closed scientific and execution contracts for Qiskit experiment profiles."""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from models import AdmissionEvidenceV1, sanitize_text, sha256_digest
from qiskit_identity import qiskit_software_stack_digest


QISKIT_EXPERIMENT_V1 = "ari.qiskit-experiment/v1"
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_SAFE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_GATE_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def _require_digest(value: str) -> str:
    if not _SHA256_RE.fullmatch(value):
        raise ValueError("Qiskit identities require SHA-256 digests")
    return value


class QiskitSoftwareV1(BaseModel):
    """Scientific packages whose algorithms affect the result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    qiskit_version: Literal["2.5.1"] = "2.5.1"
    qiskit_aer_version: Literal["0.17.2"] | None = None
    qiskit_ibm_runtime_version: Literal["0.48.0"] | None = None
    stack_digest: str

    @field_validator("stack_digest")
    @classmethod
    def _digest(cls, value: str) -> str:
        return _require_digest(value)

    @model_validator(mode="after")
    def _closed_stack(self) -> "QiskitSoftwareV1":
        names = {"qiskit": self.qiskit_version}
        if self.qiskit_aer_version is not None:
            names["qiskit-aer"] = self.qiskit_aer_version
        if self.qiskit_ibm_runtime_version is not None:
            names["qiskit-ibm-runtime"] = self.qiskit_ibm_runtime_version
        expected = qiskit_software_stack_digest(names)
        if self.stack_digest != expected:
            raise ValueError(f"Qiskit software stack digest mismatch: {expected}")
        return self

    @property
    def distributions(self) -> dict[str, str]:
        values = {"qiskit": self.qiskit_version}
        if self.qiskit_aer_version is not None:
            values["qiskit-aer"] = self.qiskit_aer_version
        if self.qiskit_ibm_runtime_version is not None:
            values["qiskit-ibm-runtime"] = self.qiskit_ibm_runtime_version
        return values


class QiskitCircuitV1(BaseModel):
    """One canonical, immutable QPY circuit plus closed parameter bindings."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    qpy_path: str
    qpy_digest: str
    qpy_version: int = Field(ge=1, le=255)
    num_qubits: int = Field(ge=1, le=100)
    num_clbits: int = Field(ge=1, le=100)
    parameter_bindings: dict[str, float] = Field(default_factory=dict, max_length=256)
    parameter_units: dict[str, Literal["rad", "1"]] = Field(
        default_factory=dict, max_length=256
    )

    @field_validator("qpy_path")
    @classmethod
    def _path(cls, value: str) -> str:
        path = Path(value)
        if not path.is_absolute() or path.suffix.casefold() != ".qpy":
            raise ValueError("Qiskit circuit must be an absolute QPY path")
        return str(path)

    @field_validator("qpy_digest")
    @classmethod
    def _digest(cls, value: str) -> str:
        return _require_digest(value)

    @field_validator("parameter_bindings")
    @classmethod
    def _bindings(cls, value: dict[str, float]) -> dict[str, float]:
        normalized: dict[str, float] = {}
        for name, raw in sorted(value.items()):
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", name):
                raise ValueError("Qiskit parameter name is invalid")
            number = float(raw)
            if not math.isfinite(number):
                raise ValueError("Qiskit parameter bindings must be finite")
            normalized[name] = number
        return normalized

    @field_validator("parameter_units")
    @classmethod
    def _parameter_units(
        cls, value: dict[str, Literal["rad", "1"]]
    ) -> dict[str, Literal["rad", "1"]]:
        if any(
            not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", name) for name in value
        ):
            raise ValueError("Qiskit parameter unit names are invalid")
        return dict(sorted(value.items()))

    @model_validator(mode="after")
    def _complete_parameter_units(self) -> "QiskitCircuitV1":
        if set(self.parameter_bindings) != set(self.parameter_units):
            raise ValueError(
                "Qiskit every parameter binding requires an explicit rad or 1 unit"
            )
        return self


class QiskitTargetV1(BaseModel):
    """Immutable compilation target; calibration remains per-run provenance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    num_qubits: int = Field(ge=1, le=10_000)
    basis_gates: list[str] = Field(min_length=1, max_length=256)
    coupling_map: list[list[int]] = Field(default_factory=list, max_length=100_000)
    target_digest: str

    @field_validator("basis_gates")
    @classmethod
    def _gates(cls, values: list[str]) -> list[str]:
        normalized = sorted(set(values))
        if len(normalized) != len(values) or any(
            not _GATE_RE.fullmatch(item) for item in normalized
        ):
            raise ValueError("Qiskit basis gates must be unique safe identifiers")
        return normalized

    @field_validator("coupling_map")
    @classmethod
    def _coupling(cls, values: list[list[int]]) -> list[list[int]]:
        edges: set[tuple[int, int]] = set()
        for edge in values:
            if len(edge) != 2 or min(edge) < 0 or edge[0] == edge[1]:
                raise ValueError("Qiskit coupling edges must be directed qubit pairs")
            edges.add((edge[0], edge[1]))
        if len(edges) != len(values):
            raise ValueError("Qiskit coupling edges must be unique")
        return [list(edge) for edge in sorted(edges)]

    @field_validator("target_digest")
    @classmethod
    def _digest(cls, value: str) -> str:
        return _require_digest(value)

    @model_validator(mode="after")
    def _closed_target(self) -> "QiskitTargetV1":
        if any(max(edge) >= self.num_qubits for edge in self.coupling_map):
            raise ValueError("Qiskit coupling map exceeds target qubit count")
        expected = sha256_digest(
            {
                "num_qubits": self.num_qubits,
                "basis_gates": self.basis_gates,
                "coupling_map": self.coupling_map,
            }
        )
        if self.target_digest != expected:
            raise ValueError(f"Qiskit target digest mismatch: expected {expected}")
        return self


class QiskitTranspilationV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    pass_manager: Literal["preset"] = "preset"
    optimization_level: int = Field(ge=0, le=3)
    seed_transpiler: int = Field(ge=0, le=2**31 - 1)
    initial_layout: list[int] | None = Field(default=None, max_length=100)

    @field_validator("initial_layout")
    @classmethod
    def _layout(cls, value: list[int] | None) -> list[int] | None:
        if value is not None and (
            len(value) != len(set(value)) or any(item < 0 for item in value)
        ):
            raise ValueError("Qiskit initial layout must use unique qubit indices")
        return value


class QiskitNoiseModelV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["depolarizing-readout"] = "depolarizing-readout"
    one_qubit_error: float = Field(ge=0, lt=1)
    two_qubit_error: float = Field(ge=0, lt=1)
    readout_p0_given_1: float = Field(ge=0, lt=1)
    readout_p1_given_0: float = Field(ge=0, lt=1)
    one_qubit_gates: list[str] = Field(min_length=1, max_length=100)
    two_qubit_gates: list[str] = Field(min_length=1, max_length=100)

    @field_validator("one_qubit_gates", "two_qubit_gates")
    @classmethod
    def _gates(cls, values: list[str]) -> list[str]:
        normalized = sorted(set(values))
        if len(normalized) != len(values) or any(
            not _GATE_RE.fullmatch(item) for item in normalized
        ):
            raise ValueError("Qiskit noise gates must be unique safe identifiers")
        return normalized


class QiskitLocalBackendV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["local-ideal", "local-noisy"]
    backend_name: Literal["aer_simulator"] = "aer_simulator"
    target: QiskitTargetV1
    simulator_method: Literal[
        "statevector", "density_matrix", "matrix_product_state", "stabilizer"
    ]
    precision: Literal["single", "double"] = "double"
    device: Literal["CPU"] = "CPU"
    max_parallel_threads: int = Field(default=1, ge=1, le=256)
    noise_model: QiskitNoiseModelV1 | None = None

    @model_validator(mode="after")
    def _noise_boundary(self) -> "QiskitLocalBackendV1":
        if (self.kind == "local-ideal") != (self.noise_model is None):
            raise ValueError(
                "ideal and noisy Aer profiles require distinct noise policy"
            )
        if self.noise_model is not None:
            gates = set(self.target.basis_gates)
            if (
                not set(self.noise_model.one_qubit_gates) <= gates
                or not set(self.noise_model.two_qubit_gates) <= gates
            ):
                raise ValueError("Qiskit noise gates must be target basis gates")
        return self


class QiskitRemoteBackendV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["remote-simulator", "ibm-hardware"]
    backend_name: str
    backend_version: str
    target: QiskitTargetV1
    channel: Literal["ibm_quantum_platform"] = "ibm_quantum_platform"
    instance_digest: str
    access_tier_id: str
    calibration_required: bool = True

    @field_validator("backend_name", "access_tier_id")
    @classmethod
    def _safe_id(cls, value: str) -> str:
        if not _SAFE_ID_RE.fullmatch(value):
            raise ValueError("Qiskit remote backend identifiers are invalid")
        return value

    @field_validator("backend_version")
    @classmethod
    def _version(cls, value: str) -> str:
        value = value.strip()
        if not value or len(value) > 100:
            raise ValueError("Qiskit backend version is required")
        return value

    @field_validator("instance_digest")
    @classmethod
    def _digest(cls, value: str) -> str:
        return _require_digest(value)

    @model_validator(mode="after")
    def _hardware_calibration(self) -> "QiskitRemoteBackendV1":
        if self.kind == "ibm-hardware" and not self.calibration_required:
            raise ValueError("IBM hardware profiles require calibration snapshots")
        return self


QiskitBackendV1 = Annotated[
    QiskitLocalBackendV1 | QiskitRemoteBackendV1, Field(discriminator="kind")
]


class QiskitMitigationV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dynamical_decoupling: bool = False
    dd_sequence: Literal["XX", "XpXm", "XY4"] = "XY4"
    gate_twirling: bool = False
    measure_twirling: bool = False


class QiskitOutcomeExpectationV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    bitstring: str
    probability_min: float = Field(ge=0, le=1)
    probability_max: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def _range(self) -> "QiskitOutcomeExpectationV1":
        if self.probability_min > self.probability_max:
            raise ValueError("Qiskit outcome probability range is reversed")
        if not re.fullmatch(r"[01]+", self.bitstring):
            raise ValueError("Qiskit outcome bitstring is invalid")
        return self


class QiskitExperimentV1(BaseModel):
    """One immutable simulator or IBM Runtime sampling experiment."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["ari.qiskit-experiment/v1"] = QISKIT_EXPERIMENT_V1
    profile_id: str
    description: str
    software: QiskitSoftwareV1
    circuit: QiskitCircuitV1
    transpilation: QiskitTranspilationV1
    backend: QiskitBackendV1
    shots: int = Field(ge=1, le=1_000_000)
    seed_simulator: int | None = Field(default=None, ge=0, le=2**31 - 1)
    mitigation: QiskitMitigationV1 = Field(default_factory=QiskitMitigationV1)
    expected_outcomes: list[QiskitOutcomeExpectationV1] = Field(
        min_length=1, max_length=1_024
    )
    max_unlisted_probability: float = Field(default=0.0, ge=0, le=1)
    golden_fixture_path: str | None = None
    golden_fixture_digest: str | None = None
    replay_fixture_path: str | None = None
    replay_fixture_digest: str | None = None
    evidence: AdmissionEvidenceV1 = Field(default_factory=AdmissionEvidenceV1)
    limitations: list[str] = Field(min_length=1, max_length=100)
    timeout_seconds: float = Field(default=3_600, gt=0, le=172_800)
    poll_interval_seconds: float = Field(default=2, ge=0.1, le=60)

    @field_validator("profile_id")
    @classmethod
    def _profile_id(cls, value: str) -> str:
        if not _SAFE_ID_RE.fullmatch(value):
            raise ValueError("Qiskit profile_id is invalid")
        return value

    @field_validator("description")
    @classmethod
    def _description(cls, value: str) -> str:
        value = sanitize_text(value, limit=1_000)
        if not value:
            raise ValueError("Qiskit profile description is required")
        return value

    @field_validator("golden_fixture_digest", "replay_fixture_digest")
    @classmethod
    def _optional_digest(cls, value: str | None) -> str | None:
        return _require_digest(value) if value is not None else None

    @field_validator("golden_fixture_path", "replay_fixture_path")
    @classmethod
    def _optional_path(cls, value: str | None) -> str | None:
        if value is not None and not Path(value).is_absolute():
            raise ValueError("Qiskit evidence fixture paths must be absolute")
        return str(Path(value)) if value is not None else None

    @field_validator("limitations")
    @classmethod
    def _limitations(cls, values: list[str]) -> list[str]:
        normalized = sorted({sanitize_text(item, limit=500) for item in values})
        if len(normalized) != len(values) or any(not item for item in normalized):
            raise ValueError("Qiskit limitations must be unique and nonempty")
        return normalized

    @model_validator(mode="after")
    def _closed_experiment(self) -> "QiskitExperimentV1":
        target = self.backend.target
        if self.circuit.num_qubits > target.num_qubits:
            raise ValueError("Qiskit circuit exceeds target qubit count")
        layout = self.transpilation.initial_layout
        if layout is not None and (
            len(layout) != self.circuit.num_qubits or max(layout) >= target.num_qubits
        ):
            raise ValueError("Qiskit initial layout does not match circuit and target")
        bitstrings = [item.bitstring for item in self.expected_outcomes]
        if len(bitstrings) != len(set(bitstrings)) or any(
            len(item) != self.circuit.num_clbits for item in bitstrings
        ):
            raise ValueError("Qiskit expected outcomes must be unique full bitstrings")
        if sum(item.probability_min for item in self.expected_outcomes) > 1:
            raise ValueError("Qiskit minimum outcome probabilities exceed one")
        if isinstance(self.backend, QiskitLocalBackendV1):
            if self.software.qiskit_aer_version is None or self.seed_simulator is None:
                raise ValueError(
                    "local Qiskit profiles require pinned Aer and simulator seed"
                )
            if self.software.qiskit_ibm_runtime_version is not None:
                raise ValueError(
                    "local Qiskit profiles cannot claim IBM Runtime software"
                )
            if self.mitigation != QiskitMitigationV1():
                raise ValueError("local Aer profiles cannot declare Runtime mitigation")
        else:
            if self.software.qiskit_ibm_runtime_version is None:
                raise ValueError("remote Qiskit profiles require pinned Runtime client")
            if self.seed_simulator is not None:
                raise ValueError(
                    "remote Runtime profiles cannot claim a simulator seed"
                )
            if self.circuit.parameter_bindings:
                raise ValueError(
                    "remote Runtime profiles cannot bind parameters through the "
                    "reviewed MCP release"
                )
        if self.evidence.replay_fixture_digest != self.replay_fixture_digest:
            raise ValueError("Qiskit replay evidence must equal the replay fixture")
        if self.evidence.scientific_validation_digest != self.golden_fixture_digest:
            raise ValueError("Qiskit scientific evidence must equal the golden fixture")
        for path, digest in (
            (self.golden_fixture_path, self.golden_fixture_digest),
            (self.replay_fixture_path, self.replay_fixture_digest),
        ):
            if (path is None) != (digest is None):
                raise ValueError("Qiskit fixture path and digest must be paired")
        return self

    @property
    def capability_ref(self) -> str:
        return {
            "local-ideal": "ari.quantum.sample.local-ideal",
            "local-noisy": "ari.quantum.sample.local-noisy",
            "remote-simulator": "ari.quantum.sample.remote-simulator",
            "ibm-hardware": "ari.quantum.sample.ibm-hardware",
        }[self.backend.kind]

    @property
    def determinism(self) -> Literal["seeded", "stochastic"]:
        return (
            "seeded" if isinstance(self.backend, QiskitLocalBackendV1) else "stochastic"
        )

    def execution_payload(self) -> dict[str, Any]:
        payload = self.model_dump(mode="json")
        for key in (
            "description",
            "evidence",
            "golden_fixture_path",
            "golden_fixture_digest",
            "replay_fixture_path",
            "replay_fixture_digest",
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
                "software": self.software,
                "transpilation": self.transpilation,
                "backend": self.backend,
                "shots": self.shots,
                "seed_simulator": self.seed_simulator,
                "mitigation": self.mitigation,
            }
        )


__all__ = [
    "QISKIT_EXPERIMENT_V1",
    "QiskitCircuitV1",
    "QiskitExperimentV1",
    "QiskitLocalBackendV1",
    "QiskitMitigationV1",
    "QiskitNoiseModelV1",
    "QiskitOutcomeExpectationV1",
    "QiskitRemoteBackendV1",
    "QiskitSoftwareV1",
    "QiskitTargetV1",
    "QiskitTranspilationV1",
]
