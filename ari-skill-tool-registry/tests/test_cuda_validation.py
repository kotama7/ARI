"""CUDA self-test Provider contract tests that do not require a GPU."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from cuda_promotion import CUDA_CAPABILITY_REF
from cuda_validation_worker import _validate_result


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
PROBE = PACKAGE_ROOT / "src/nvidia_smi_inventory_probe.py"
SOURCE = PACKAGE_ROOT / "src/cuda_validation_kernel.cu"


def _result() -> dict:
    return {
        "schema_version": "ari.cuda-self-test/v1",
        "verdict": "pass",
        "device_count": 1,
        "devices": [
            {
                "device_index": 0,
                "name": "fixture-device",
                "compute_capability": "7.0",
                "memory_bytes": 1024,
                "case_count": 4,
                "maximum_absolute_error": 0.0,
                "checksum": 1.0,
                "repeated_execution_equal": True,
                "negative_control_detected": True,
            }
        ],
    }


def test_cuda_result_requires_real_negative_control_and_repeat_equality():
    assert _validate_result(_result())["verdict"] == "pass"

    missing_negative = _result()
    missing_negative["devices"][0]["negative_control_detected"] = False
    with pytest.raises(ValueError, match="device validation"):
        _validate_result(missing_negative)

    changed_repeat = _result()
    changed_repeat["devices"][0]["repeated_execution_equal"] = False
    with pytest.raises(ValueError, match="device validation"):
        _validate_result(changed_repeat)


def test_inventory_probe_rejects_every_noncanonical_query():
    completed = subprocess.run(
        [sys.executable, str(PROBE), "--query-gpu=name"],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 64
    assert "unsupported" in completed.stderr


def test_cuda_source_covers_all_devices_multiple_shapes_and_negative_control():
    source = SOURCE.read_text(encoding="utf-8")
    assert "cudaGetDeviceCount" in source
    assert "for (int device = 0; device < device_count; ++device)" in source
    assert "1, 257, 65537, 1048576" in source
    assert "for (int repeat = 0; repeat < 2; ++repeat)" in source
    assert "corrupted[count / 2] += 1.0F" in source
    assert CUDA_CAPABILITY_REF == "ari.environment.cuda.validate/v1"
