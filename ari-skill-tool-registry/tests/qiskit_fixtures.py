"""Deterministic Qiskit profile and provider fixtures shared by registry tests."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import platform
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from models import AdmissionEvidenceV1, sha256_digest
from providers import ProviderResponseV1, ProviderToolV1, PythonStdioLauncherV1
from qiskit_adapter import (
    QiskitCircuitV1,
    QiskitExperimentAdapter,
    QiskitExperimentV1,
    QiskitLocalBackendV1,
    QiskitMitigationV1,
    QiskitNoiseModelV1,
    QiskitOutcomeExpectationV1,
    QiskitProviderPinV1,
    QiskitRemoteBackendV1,
    QiskitSoftwareV1,
    QiskitTargetV1,
    QiskitTranspilationV1,
    qiskit_provider_release_pin,
    qiskit_software_stack_digest,
)
from sources import QiskitSourceSpecV1
from storage import RegistryArtifactStore


FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "qiskit"
CORE_TOOL_NAMES = {
    "analyze_circuit_tool",
    "compare_optimization_levels_tool",
    "convert_qasm3_to_qpy_tool",
    "convert_qpy_to_qasm3_tool",
    "export_circuit_to_qasm_tool",
    "load_circuit_from_qasm_tool",
    "transpile_circuit_tool",
}
RUNTIME_TOOL_NAMES = {
    "active_account_info_tool",
    "active_instance_info_tool",
    "available_instances_tool",
    "cancel_job_tool",
    "delete_saved_account_tool",
    "find_optimal_qubit_chains_tool",
    "find_optimal_qv_qubits_tool",
    "get_backend_calibration_tool",
    "get_backend_properties_tool",
    "get_coupling_map_tool",
    "get_job_results_tool",
    "get_job_status_tool",
    "least_busy_backend_tool",
    "list_backends_tool",
    "list_my_jobs_tool",
    "list_saved_accounts_tool",
    "run_estimator_tool",
    "run_sampler_tool",
    "setup_ibm_quantum_account_tool",
    "usage_info_tool",
}


def file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def provider_pin(role: str) -> QiskitProviderPinV1:
    version = "0.3.1" if role == "circuit" else "0.6.1"
    return QiskitProviderPinV1.model_validate(
        qiskit_provider_release_pin(role, version)
    )


def launcher(root: Path, role: str) -> PythonStdioLauncherV1:
    package_name = (
        "qiskit_mcp_server" if role == "circuit" else "qiskit_ibm_runtime_mcp_server"
    )
    package = root / role / package_name
    package.mkdir(parents=True, exist_ok=True)
    (package / "__init__.py").write_text(
        "def main():\n    return None\n", encoding="utf-8"
    )
    return PythonStdioLauncherV1(
        python_executable=str(Path(sys.executable).absolute()),
        package_root=str(package.resolve()),
        python_module=package_name,
        python_callable="main",
        expected_architecture=platform.machine(),
        identity_globs=[
            "**/*",
            "**/*.py",
            "*.lock",
            "pyproject.toml",
            "requirements*.txt",
        ],
    )


def _copy_circuit(root: Path, name: str) -> Path:
    source = FIXTURE_ROOT / name
    destination = root / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(source.read_bytes())
    return destination.resolve()


def _target(num_qubits: int) -> QiskitTargetV1:
    edges = [[index, index + 1] for index in range(num_qubits - 1)]
    edges += [[right, left] for left, right in edges]
    material = {
        "num_qubits": num_qubits,
        "basis_gates": ["cx", "id", "rz", "sx", "x"],
        "coupling_map": sorted(edges),
    }
    return QiskitTargetV1(**material, target_digest=sha256_digest(material))


def experiment_profile(
    root: Path,
    *,
    kind: str = "local-ideal",
    profile_id: str | None = None,
    circuit_name: str = "bell-phi-plus.qpy",
    scientific: bool = True,
) -> QiskitExperimentV1:
    circuit_path = _copy_circuit(root, circuit_name)
    num_qubits = 3 if circuit_name == "ghz3.qpy" else 2
    target = _target(num_qubits)
    if kind.startswith("local"):
        software_names = {"qiskit": "2.5.1", "qiskit-aer": "0.17.2"}
        software = QiskitSoftwareV1(
            qiskit_aer_version="0.17.2",
            stack_digest=qiskit_software_stack_digest(software_names),
        )
        noise = (
            QiskitNoiseModelV1(
                one_qubit_error=0.01,
                two_qubit_error=0.02,
                readout_p0_given_1=0.03,
                readout_p1_given_0=0.04,
                one_qubit_gates=["sx", "x"],
                two_qubit_gates=["cx"],
            )
            if kind == "local-noisy"
            else None
        )
        backend: QiskitLocalBackendV1 | QiskitRemoteBackendV1 = QiskitLocalBackendV1(
            kind=kind,
            target=target,
            simulator_method=(
                "density_matrix" if kind == "local-noisy" else "statevector"
            ),
            max_parallel_threads=1,
            noise_model=noise,
        )
        seed_simulator = 20260802
        mitigation = QiskitMitigationV1()
    else:
        software_names = {"qiskit": "2.5.1", "qiskit-ibm-runtime": "0.48.0"}
        software = QiskitSoftwareV1(
            qiskit_ibm_runtime_version="0.48.0",
            stack_digest=qiskit_software_stack_digest(software_names),
        )
        backend = QiskitRemoteBackendV1(
            kind=kind,
            backend_name=(
                "ibm_fixture_simulator"
                if kind == "remote-simulator"
                else "ibm_fixture_hardware"
            ),
            backend_version="1.2.3",
            target=target,
            instance_digest=sha256_digest("crn:v1:ari:fixture-instance"),
            access_tier_id="fixture-tier",
            calibration_required=kind == "ibm-hardware",
        )
        seed_simulator = None
        mitigation = QiskitMitigationV1(
            dynamical_decoupling=kind == "ibm-hardware",
            gate_twirling=kind == "ibm-hardware",
            measure_twirling=kind == "ibm-hardware",
        )

    bit0 = "0" * num_qubits
    bit1 = "1" * num_qubits
    if kind == "local-noisy":
        expected = [
            QiskitOutcomeExpectationV1(
                bitstring=bit0, probability_min=0.40, probability_max=0.55
            ),
            QiskitOutcomeExpectationV1(
                bitstring=bit1, probability_min=0.40, probability_max=0.55
            ),
        ]
        max_unlisted = 0.15
        counts = {bit0: 1859, bit1: 1917, "01": 162, "10": 158}
    elif kind == "ibm-hardware":
        expected = [
            QiskitOutcomeExpectationV1(
                bitstring=bit0, probability_min=0.35, probability_max=0.60
            ),
            QiskitOutcomeExpectationV1(
                bitstring=bit1, probability_min=0.35, probability_max=0.60
            ),
        ]
        max_unlisted = 0.30
        counts = {bit0: 1800, bit1: 1800, "01": 248, "10": 248}
    else:
        expected = [
            QiskitOutcomeExpectationV1(
                bitstring=bit0, probability_min=0.45, probability_max=0.55
            ),
            QiskitOutcomeExpectationV1(
                bitstring=bit1, probability_min=0.45, probability_max=0.55
            ),
        ]
        max_unlisted = 0.0
        counts = {bit0: 2046, bit1: 2050}

    values: dict[str, Any] = {
        "profile_id": profile_id or kind,
        "description": f"Pinned {kind} Bell/GHZ sampling fixture",
        "software": software,
        "circuit": QiskitCircuitV1(
            qpy_path=str(circuit_path),
            qpy_digest=file_digest(circuit_path),
            qpy_version=circuit_path.read_bytes()[6],
            num_qubits=num_qubits,
            num_clbits=num_qubits,
            parameter_bindings={},
            parameter_units={},
        ),
        "transpilation": QiskitTranspilationV1(
            optimization_level=1,
            seed_transpiler=731,
            initial_layout=list(range(num_qubits)),
        ),
        "backend": backend,
        "shots": 4096,
        "seed_simulator": seed_simulator,
        "mitigation": mitigation,
        "expected_outcomes": expected,
        "max_unlisted_probability": max_unlisted,
        "limitations": ["Deterministic registry test profile."],
        "timeout_seconds": 5,
        "poll_interval_seconds": 0.1,
    }
    provisional = QiskitExperimentV1.model_validate(values)
    if not scientific:
        return provisional
    golden_path = root / f"{provisional.profile_id}.golden.json"
    replay_path = root / f"{provisional.profile_id}.replay.json"
    write_json(
        golden_path,
        {
            "schema_version": "ari.qiskit-golden/v1",
            "profile_id": provisional.profile_id,
            "experiment_digest": provisional.experiment_digest,
            "counts": counts,
        },
    )
    write_json(
        replay_path,
        {
            "schema_version": "ari.qiskit-replay-fixture/v1",
            "profile_id": provisional.profile_id,
            "arguments": {"request_id": "offline-fixture"},
            "result": {
                "status": "completed",
                "experiment_digest": provisional.experiment_digest,
                "method_digest": provisional.method_digest,
                "counts": counts,
                "shots": provisional.shots,
            },
        },
    )
    golden_digest = file_digest(golden_path)
    replay_digest = file_digest(replay_path)
    values.update(
        {
            "golden_fixture_path": str(golden_path.resolve()),
            "golden_fixture_digest": golden_digest,
            "replay_fixture_path": str(replay_path.resolve()),
            "replay_fixture_digest": replay_digest,
            "evidence": AdmissionEvidenceV1(
                protocol_conformance=True,
                provider_pinned=True,
                launcher_verified=True,
                dependencies_pinned=True,
                replay_fixture_digest=replay_digest,
                scientific_validation_digest=golden_digest,
                limitations_documented=True,
                semantics_documented=True,
                units_documented=True,
                method_identity_documented=True,
                architecture=platform.machine(),
                notes=["Exact official Qiskit/Aer fixture versions are pinned."],
            ),
        }
    )
    return QiskitExperimentV1.model_validate(values)


def source_spec(
    root: Path, experiments: list[QiskitExperimentV1]
) -> QiskitSourceSpecV1:
    remote = any(
        isinstance(item.backend, QiskitRemoteBackendV1) for item in experiments
    )
    return QiskitSourceSpecV1(
        source_id="qiskit.fixture",
        core_provider_digest="sha256:" + "4" * 64,
        core_launcher=launcher(root, "circuit"),
        runtime_provider_digest="sha256:" + "5" * 64 if remote else None,
        runtime_launcher=launcher(root, "runtime") if remote else None,
        experiments=experiments,
    )


class FakeQiskitCore:
    def __init__(self, *, num_qubits: int = 2, num_clbits: int = 2) -> None:
        self.num_qubits = num_qubits
        self.num_clbits = num_clbits
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def list_tools(self) -> list[ProviderToolV1]:
        return [ProviderToolV1(name=name) for name in sorted(CORE_TOOL_NAMES)]

    async def invoke(self, name: str, arguments: dict[str, Any]) -> ProviderResponseV1:
        if name != "transpile_circuit_tool":
            raise AssertionError(name)
        self.calls.append((name, dict(arguments)))
        payload = base64.b64decode(arguments["circuit"], validate=True)
        value = {
            "status": "success",
            "optimization_level": arguments["optimization_level"],
            "basis_gates": arguments["basis_gates"],
            "coupling_map_type": "custom",
            "transpiled_circuit": {
                "circuit_qpy": base64.b64encode(payload).decode("ascii"),
                "num_qubits": self.num_qubits,
                "num_clbits": self.num_clbits,
                "depth": 3,
                "size": 4,
                "operation_counts": {"cx": 1, "measure": self.num_clbits},
                "total_operations": 4,
                "width": self.num_qubits + self.num_clbits,
            },
            "improvements": {"depth_reduction": 0},
        }
        return ProviderResponseV1(text=json.dumps(value), structured=value)

    async def get_status(self, lifecycle, provider_handle):
        raise AssertionError("virtual adapter owns lifecycle")

    async def get_result(self, lifecycle, provider_handle):
        raise AssertionError("virtual adapter owns lifecycle")

    async def cancel(self, lifecycle, provider_handle):
        raise AssertionError("virtual adapter owns lifecycle")


class FakeQiskitRuntime:
    def __init__(
        self,
        profile: QiskitExperimentV1,
        *,
        states: list[str] | None = None,
        backend_mismatch: bool = False,
        block_submission: bool = False,
    ) -> None:
        assert isinstance(profile.backend, QiskitRemoteBackendV1)
        self.profile = profile
        self.states = list(states or ["DONE"])
        self.backend_mismatch = backend_mismatch
        self.block_submission = block_submission
        self.submission_entered = asyncio.Event()
        self.release_submission = asyncio.Event()
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.cancelled = False

    @asynccontextmanager
    async def connection(self):
        yield self

    async def list_tools(self) -> list[ProviderToolV1]:
        return [ProviderToolV1(name=name) for name in sorted(RUNTIME_TOOL_NAMES)]

    def _response(self, value: dict[str, Any]) -> ProviderResponseV1:
        return ProviderResponseV1(text=json.dumps(value), structured=value)

    async def invoke(self, name: str, arguments: dict[str, Any]) -> ProviderResponseV1:
        self.calls.append((name, dict(arguments)))
        backend = self.profile.backend
        assert isinstance(backend, QiskitRemoteBackendV1)
        if name == "setup_ibm_quantum_account_tool":
            value = {"status": "success", "channel": backend.channel}
        elif name == "active_instance_info_tool":
            value = {
                "status": "success",
                "instance_crn": "crn:v1:ari:fixture-instance",
            }
        elif name == "get_backend_properties_tool":
            value = {
                "status": "success",
                "backend_name": (
                    "wrong_backend" if self.backend_mismatch else backend.backend_name
                ),
                "backend_version": backend.backend_version,
                "num_qubits": backend.target.num_qubits,
                "simulator": backend.kind == "remote-simulator",
                "operational": True,
                "pending_jobs": 2,
                "status_msg": "active",
                "processor_type": "fixture-r1",
                "basis_gates": backend.target.basis_gates,
                "coupling_map": backend.target.coupling_map,
                "max_shots": 100_000,
                "max_experiments": 1,
            }
        elif name == "get_coupling_map_tool":
            value = {
                "status": "success",
                "backend_name": backend.backend_name,
                "num_qubits": backend.target.num_qubits,
                "num_edges": len(backend.target.coupling_map),
                "edges": backend.target.coupling_map,
                "bidirectional": True,
                "adjacency_list": {
                    str(index): sorted(
                        edge[1]
                        for edge in backend.target.coupling_map
                        if edge[0] == index
                    )
                    for index in range(backend.target.num_qubits)
                },
            }
        elif name == "get_backend_calibration_tool":
            value = {
                "status": "success",
                "backend_name": backend.backend_name,
                "num_qubits": backend.target.num_qubits,
                "last_calibration": "2026-08-02T00:00:00Z",
                "faulty_qubits": [],
                "faulty_gates": [],
                "qubit_calibration": [],
                "gate_errors": [],
                "note": "fixture calibration",
            }
        elif name == "run_sampler_tool":
            self.submission_entered.set()
            if self.block_submission:
                await self.release_submission.wait()
            value = {
                "status": "success",
                "job_id": "runtime-job-fixture",
                "backend": backend.backend_name,
                "shots": self.profile.shots,
            }
        elif name == "get_job_status_tool":
            state = self.states.pop(0) if len(self.states) > 1 else self.states[0]
            value = {
                "status": "success",
                "job_id": "runtime-job-fixture",
                "job_status": state,
                "backend": backend.backend_name,
                "error_message": "fixture remote failure" if state == "ERROR" else None,
            }
        elif name == "get_job_results_tool":
            bit0 = "0" * self.profile.circuit.num_clbits
            bit1 = "1" * self.profile.circuit.num_clbits
            value = {
                "status": "success",
                "job_id": "runtime-job-fixture",
                "job_status": "DONE",
                "backend": backend.backend_name,
                "counts": {bit0: 2046, bit1: 2050},
                "shots": self.profile.shots,
                "execution_time": 1.25,
            }
        elif name == "cancel_job_tool":
            self.cancelled = True
            value = {"status": "success", "job_id": "runtime-job-fixture"}
        else:
            raise AssertionError(name)
        return self._response(value)

    async def get_status(self, lifecycle, provider_handle):
        raise AssertionError("virtual adapter owns lifecycle")

    async def get_result(self, lifecycle, provider_handle):
        raise AssertionError("virtual adapter owns lifecycle")

    async def cancel(self, lifecycle, provider_handle):
        raise AssertionError("virtual adapter owns lifecycle")


def adapter(
    spec: QiskitSourceSpecV1,
    *,
    core: FakeQiskitCore,
    runtime: FakeQiskitRuntime | None = None,
    artifact_store: RegistryArtifactStore | None = None,
    verify_contract: bool = True,
) -> QiskitExperimentAdapter:
    return QiskitExperimentAdapter(
        spec.core_effective_launcher,
        core_provider_digest=spec.core_provider_digest,
        core_pin=spec.core_pin,
        runtime_launcher=spec.runtime_effective_launcher,
        runtime_provider_digest=spec.runtime_provider_digest,
        runtime_pin=spec.runtime_pin if spec.runtime_launcher is not None else None,
        experiments=spec.experiments,
        artifact_store=artifact_store,
        allowed_leaf_names={
            QiskitExperimentAdapter.leaf_name(item.profile_id)
            for item in spec.experiments
        },
        core_transport=core,
        runtime_transport=runtime,
        verify_packages=False,
        verify_contract=verify_contract,
    )


def write_fake_worker(path: Path) -> None:
    path.write_text(
        """import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

spec = json.loads(Path(sys.argv[1]).read_text())
n = spec["num_clbits"]
zero = "0" * n
one = "1" * n
counts = {zero: 2046, one: 2050}
if spec["noise_model"] is not None:
    counts = {"00": 1859, "01": 162, "10": 158, "11": 1917}
now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
value = {
    "schema_version": "ari.qiskit-aer-result/v1",
    "experiment_digest": spec["experiment_digest"],
    "started_at": now,
    "completed_at": now,
    "architecture": platform.machine(),
    "qiskit_version": spec["qiskit_version"],
    "qiskit_aer_version": spec["qiskit_aer_version"],
    "qpy_digest": spec["qpy_digest"],
    "backend_name": spec["backend_name"],
    "simulator_method": spec["simulator_method"],
    "precision": spec["precision"],
    "device": spec["device"],
    "max_parallel_threads": spec["max_parallel_threads"],
    "shots": spec["shots"],
    "seed_simulator": spec["seed_simulator"],
    "counts": counts,
    "return_code": 0,
    "error": None,
}
Path(spec["result_path"]).write_text(json.dumps(value))
""",
        encoding="utf-8",
    )


__all__ = [
    "CORE_TOOL_NAMES",
    "FIXTURE_ROOT",
    "RUNTIME_TOOL_NAMES",
    "FakeQiskitCore",
    "FakeQiskitRuntime",
    "adapter",
    "experiment_profile",
    "file_digest",
    "launcher",
    "provider_pin",
    "source_spec",
    "write_fake_worker",
]
