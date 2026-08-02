"""Closed Aer worker security checks and optional exact scientific vectors."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from qiskit_fixtures import FIXTURE_ROOT, file_digest, write_json
from qiskit_worker import _load_circuit


WORKER = Path(__file__).resolve().parents[1] / "src" / "qiskit_worker.py"
QISKIT_TEST_PYTHON = os.environ.get("ARI_QISKIT_TEST_PYTHON", "")


def _worker_spec(
    root: Path,
    vector: dict,
    *,
    result_path: Path,
) -> dict:
    source = FIXTURE_ROOT / vector["transpiled_qpy"]
    qpy_path = root / "transpiled.qpy"
    shutil.copyfile(source, qpy_path)
    return {
        "schema_version": "ari.qiskit-aer-spec/v1",
        "experiment_digest": "sha256:" + "7" * 64,
        "qpy_path": str(qpy_path.resolve()),
        "qpy_digest": file_digest(qpy_path),
        "qpy_version": qpy_path.read_bytes()[6],
        "num_qubits": vector["num_qubits"],
        "num_clbits": vector["num_clbits"],
        "parameter_bindings": {},
        "qiskit_version": "2.5.1",
        "qiskit_aer_version": "0.17.2",
        "backend_name": "aer_simulator",
        "simulator_method": vector["simulator_method"],
        "precision": "double",
        "device": "CPU",
        "max_parallel_threads": 1,
        "noise_model": vector["noise_model"],
        "shots": vector["shots"],
        "seed_simulator": vector["seed_simulator"],
        "result_path": str(result_path.resolve()),
    }


def test_worker_rejects_qpy_header_identity_before_importing_qiskit(
    tmp_path: Path,
) -> None:
    document = json.loads(
        (FIXTURE_ROOT / "scientific-fixtures-v1.json").read_text(encoding="utf-8")
    )
    vector = document["vectors"][0]
    spec = _worker_spec(tmp_path, vector, result_path=tmp_path / "result.json")
    spec["qpy_version"] += 1
    with pytest.raises(ValueError, match="QPY header identity drifted"):
        _load_circuit(spec)


@pytest.mark.skipif(
    not QISKIT_TEST_PYTHON,
    reason="set ARI_QISKIT_TEST_PYTHON to an exact Qiskit/Aer environment",
)
def test_real_qiskit_aer_vectors_reproduce_exact_seeded_counts(
    tmp_path: Path,
) -> None:
    document = json.loads(
        (FIXTURE_ROOT / "scientific-fixtures-v1.json").read_text(encoding="utf-8")
    )
    for index, vector in enumerate(document["vectors"]):
        work = tmp_path / str(index)
        work.mkdir()
        result_path = work / "result.json"
        spec_path = work / "spec.json"
        spec = _worker_spec(work, vector, result_path=result_path)
        write_json(spec_path, spec)
        process = subprocess.run(
            [QISKIT_TEST_PYTHON, str(WORKER), str(spec_path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
            env={
                "LANG": "C.UTF-8",
                "OMP_NUM_THREADS": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONUNBUFFERED": "1",
            },
        )
        assert process.returncode == 0, process.stderr
        result = json.loads(result_path.read_text(encoding="utf-8"))
        assert result["counts"] == vector["counts"]
        assert result["shots"] == vector["shots"]
        assert result["seed_simulator"] == vector["seed_simulator"]
        assert result["qpy_digest"] == vector["transpiled_qpy_digest"]
        assert result["qiskit_version"] == document["software"]["qiskit"]
        assert result["qiskit_aer_version"] == document["software"]["qiskit-aer"]
