"""Closed Qiskit Aer batch worker used by immutable local profiles."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_SPEC_KEYS = {
    "schema_version",
    "experiment_digest",
    "qpy_path",
    "qpy_digest",
    "qpy_version",
    "num_qubits",
    "num_clbits",
    "parameter_bindings",
    "qiskit_version",
    "qiskit_aer_version",
    "backend_name",
    "simulator_method",
    "precision",
    "device",
    "max_parallel_threads",
    "noise_model",
    "shots",
    "seed_simulator",
    "result_path",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return "sha256:" + value.hexdigest()


def _load_spec(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 2_000_000:
        raise ValueError("Qiskit worker spec is missing or unsafe")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or set(value) != _SPEC_KEYS:
        raise ValueError("Qiskit worker spec shape is invalid")
    if value["schema_version"] != "ari.qiskit-aer-spec/v1":
        raise ValueError("Qiskit worker spec version is invalid")
    result_path = Path(value["result_path"])
    qpy_path = Path(value["qpy_path"])
    if (
        not qpy_path.is_absolute()
        or not result_path.is_absolute()
        or qpy_path.parent != path.parent
        or result_path.parent != path.parent
    ):
        raise ValueError("Qiskit worker paths must stay in one private workspace")
    return value


def _noise_model(value: dict[str, Any] | None) -> Any | None:
    if value is None:
        return None
    expected = {
        "kind",
        "one_qubit_error",
        "two_qubit_error",
        "readout_p0_given_1",
        "readout_p1_given_0",
        "one_qubit_gates",
        "two_qubit_gates",
    }
    if set(value) != expected or value["kind"] != "depolarizing-readout":
        raise ValueError("Qiskit Aer noise contract is invalid")
    from qiskit_aer.noise import NoiseModel, ReadoutError, depolarizing_error

    model = NoiseModel()
    one_error = depolarizing_error(float(value["one_qubit_error"]), 1)
    two_error = depolarizing_error(float(value["two_qubit_error"]), 2)
    model.add_all_qubit_quantum_error(one_error, value["one_qubit_gates"])
    model.add_all_qubit_quantum_error(two_error, value["two_qubit_gates"])
    p01 = float(value["readout_p1_given_0"])
    p10 = float(value["readout_p0_given_1"])
    model.add_all_qubit_readout_error(ReadoutError([[1 - p01, p01], [p10, 1 - p10]]))
    return model


def _load_circuit(spec: dict[str, Any]) -> Any:
    path = Path(spec["qpy_path"])
    if path.is_symlink() or not path.is_file() or _digest(path) != spec["qpy_digest"]:
        raise ValueError("Qiskit worker QPY identity drifted")
    header = path.read_bytes()[:10]
    expected_producer = tuple(
        int(item) for item in str(spec["qiskit_version"]).split(".")
    )
    if (
        len(header) != 10
        or header[:6] != b"QISKIT"
        or header[6] != spec["qpy_version"]
        or tuple(header[7:10]) != expected_producer
    ):
        raise ValueError("Qiskit worker QPY header identity drifted")
    from qiskit import qpy

    with path.open("rb") as stream:
        circuits = qpy.load(stream)
    if len(circuits) != 1:
        raise ValueError("Qiskit profile QPY must contain exactly one circuit")
    circuit = circuits[0]
    if (
        circuit.num_qubits != spec["num_qubits"]
        or circuit.num_clbits != spec["num_clbits"]
    ):
        raise ValueError("Qiskit circuit dimensions differ from the profile")
    bindings = spec["parameter_bindings"]
    parameters = {parameter.name: parameter for parameter in circuit.parameters}
    if set(parameters) != set(bindings):
        raise ValueError("Qiskit circuit parameter set differs from bindings")
    if bindings:
        circuit = circuit.assign_parameters(
            {parameters[name]: value for name, value in bindings.items()},
            inplace=False,
            strict=True,
        )
    return circuit


def _execute(spec: dict[str, Any]) -> dict[str, int]:
    from qiskit_aer import AerSimulator

    expected_versions = {
        "qiskit": spec["qiskit_version"],
        "qiskit-aer": spec["qiskit_aer_version"],
    }
    actual_versions = {
        name: importlib.metadata.version(name) for name in expected_versions
    }
    if actual_versions != expected_versions:
        raise ValueError("Qiskit Aer worker distribution versions drifted")
    circuit = _load_circuit(spec)
    simulator = AerSimulator(
        method=spec["simulator_method"],
        precision=spec["precision"],
        device=spec["device"],
        max_parallel_threads=spec["max_parallel_threads"],
        max_parallel_experiments=1,
        max_parallel_shots=1,
        noise_model=_noise_model(spec["noise_model"]),
    )
    job = simulator.run(
        circuit,
        shots=spec["shots"],
        seed_simulator=spec["seed_simulator"],
    )
    result = job.result()
    if not result.success:
        raise RuntimeError("Qiskit Aer reported an unsuccessful result")
    counts = result.get_counts(circuit)
    return dict(
        sorted((str(key).replace(" ", ""), int(value)) for key, value in counts.items())
    )


def _write_result(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.chmod(0o600)
    os.replace(temporary, path)


def run(spec_path: Path) -> int:
    started_at = _now()
    try:
        spec = _load_spec(spec_path)
        counts = _execute(spec)
        error = None
        return_code = 0
    except Exception as exc:
        spec = locals().get("spec", {})
        counts = {}
        error = f"{type(exc).__name__}: {exc}"
        return_code = 1
    result_path_text = spec.get("result_path") if isinstance(spec, dict) else None
    if not isinstance(result_path_text, str):
        return 2
    _write_result(
        Path(result_path_text),
        {
            "schema_version": "ari.qiskit-aer-result/v1",
            "experiment_digest": spec["experiment_digest"],
            "started_at": started_at,
            "completed_at": _now(),
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
            "return_code": return_code,
            "error": error,
        },
    )
    return return_code


def main() -> int:
    if len(sys.argv) != 2:
        return 2
    return run(Path(sys.argv[1]).resolve())


if __name__ == "__main__":
    raise SystemExit(main())
