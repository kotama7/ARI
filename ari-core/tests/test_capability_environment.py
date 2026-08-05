from __future__ import annotations

from types import SimpleNamespace

import pytest

from ari.capability_binding import environment as environment_module
from ari.capability_binding.environment import build_environment_snapshot
from ari.protocols.integrity import canonical_digest
from ari.protocols.scientific_requirements import EnvironmentSnapshotV1


def _provider_lock():
    return SimpleNamespace(
        tools=(
            SimpleNamespace(policy={"permissions": ["scheduler-submit"]}),
        ),
        skills=(SimpleNamespace(entrypoint="ari-skill-hpc/src/server.py"),),
    )


def test_environment_snapshot_uses_observed_slurm_and_gpu_facts(monkeypatch):
    def probe(argv, *, timeout=5.0):
        del timeout
        if argv[0] == "sinfo":
            return {
                "status": "ready",
                "stdout": "gpuq|up|idle|2|64|512000|gpu:a100:4|a100\n",
                "stdout_digest": "sha256:" + "1" * 64,
                "stderr": "",
            }
        if argv[0] == "nvidia-smi":
            return {
                "status": "ready",
                "stdout": "GPU-1, NVIDIA A100, 8.0, 40960, 570.1\n",
                "stdout_digest": "sha256:" + "2" * 64,
                "stderr": "",
            }
        assert argv[0] == "nvcc"
        return {
            "status": "ready",
            "stdout": "Cuda compilation tools, release 12.4, V12.4.131\n",
            "stdout_digest": "sha256:" + "3" * 64,
            "stderr": "",
        }

    monkeypatch.setattr(environment_module, "_probe_command", probe)
    cfg = SimpleNamespace(resources={"gpus": 1, "hpc_enabled": True})
    first = build_environment_snapshot(cfg, _provider_lock())
    second = build_environment_snapshot(cfg, _provider_lock())

    assert first.model_dump_json() == second.model_dump_json()
    assert first.resource_types == ("cpu", "gpu", "process", "slurm")
    assert {"cuda-toolkit", "gpu-via-slurm", "nvidia-gpu", "slurm-controller"}.issubset(
        first.features
    )
    assert first.metadata["gpu"]["devices"][0]["uuid"] == "GPU-1"
    assert first.metadata["gpu"]["cuda_toolkit"]["compiler_version"] == "12.4.131"


def test_declared_gpu_does_not_fabricate_an_unobserved_resource(monkeypatch):
    def unavailable(argv, *, timeout=5.0):
        del timeout
        if argv[0] == "nvcc":
            return {"status": "unavailable"}
        return {
            "status": "failed" if argv[0] == "nvidia-smi" else "unavailable",
            "stderr": "no observed substrate",
        }

    monkeypatch.setattr(environment_module, "_probe_command", unavailable)
    cfg = SimpleNamespace(resources={"gpus": 8, "hpc_enabled": True})
    snapshot = build_environment_snapshot(cfg, _provider_lock())

    assert snapshot.resource_types == ("cpu", "process")
    assert snapshot.metadata["declared_resources"]["gpus"] == 8
    assert snapshot.metadata["gpu"]["status"] == "failed"
    assert snapshot.metadata["slurm"]["status"] == "unavailable"


def test_slurm_visible_gpu_without_gres_is_observed_but_not_schedulable(
    monkeypatch,
):
    def probe(argv, *, timeout=5.0):
        del timeout
        if argv[0] == "sinfo":
            return {
                "status": "ready",
                "stdout": "cpuq|up|idle|1|8|64000|(null)|(null)\n",
                "stdout_digest": "sha256:" + "1" * 64,
                "stderr": "",
            }
        if argv[0] == "nvidia-smi":
            return {"status": "unavailable"}
        if argv[0] == "nvcc":
            return {"status": "unavailable"}
        assert argv[0] == "srun"
        assert "--gres" not in argv
        assert "--exclusive" in argv
        return {
            "status": "ready",
            "stdout": "GPU-1, Tesla V100, 7.0, 16384, 570.1\n",
            "stdout_digest": "sha256:" + "4" * 64,
            "stderr": "",
        }

    monkeypatch.setattr(environment_module, "_probe_command", probe)
    monkeypatch.delenv("ARI_SLURM_ALLOW_NO_GRES", raising=False)

    snapshot = build_environment_snapshot(
        SimpleNamespace(resources={"gpus": 1, "partition": "cpuq"}),
        _provider_lock(),
    )

    assert snapshot.resource_types == ("cpu", "process", "slurm")
    assert "gpu-observed-on-slurm-node" in snapshot.features
    assert "gpu-via-slurm" not in snapshot.features
    assert snapshot.metadata["slurm_gpu"]["devices"][0]["name"] == "Tesla V100"
    assert snapshot.metadata["slurm_gpu"]["schedulable"] is False
    assert (
        snapshot.metadata["slurm_gpu"]["allocation_mode"]
        == "observation-only-no-gres"
    )


def test_explicit_exclusive_node_inventory_makes_no_gres_gpu_schedulable(
    monkeypatch,
):
    devices = [
        {
            "uuid": "GPU-1",
            "name": "Tesla V100",
            "compute_capability": "7.0",
            "memory_mb": 16384,
            "driver_version": "570.1",
        }
    ]

    def probe(argv, *, timeout=5.0):
        del timeout
        if argv[0] == "sinfo":
            return {
                "status": "ready",
                "stdout": "gpu-private|up|idle|1|8|64000|(null)|(null)\n",
                "stdout_digest": "sha256:" + "1" * 64,
                "stderr": "",
            }
        if argv[0] == "nvidia-smi":
            return {"status": "unavailable"}
        if argv[0] == "nvcc":
            return {"status": "unavailable"}
        assert argv[0] == "srun"
        assert "--gres" not in argv
        assert "--exclusive" in argv
        assert argv[argv.index("--nodelist") + 1] == "gpu-node-a"
        return {
            "status": "ready",
            "stdout": "GPU-1, Tesla V100, 7.0, 16384, 570.1\n",
            "stdout_digest": "sha256:" + "4" * 64,
            "stderr": "",
        }

    monkeypatch.setattr(environment_module, "_probe_command", probe)
    snapshot = build_environment_snapshot(
        SimpleNamespace(
            resources={
                "gpus": 1,
                "partition": "gpu-private",
                "gpu_allocation_mode": "exclusive-node-inventory",
                "gpu_node": "gpu-node-a",
                "gpu_inventory_digest": canonical_digest(devices),
                "exclusive": True,
            }
        ),
        _provider_lock(),
    )

    assert "gpu" in snapshot.resource_types
    assert "gpu-via-slurm" in snapshot.features
    assert snapshot.metadata["slurm_gpu"]["schedulable"] is True
    assert (
        snapshot.metadata["slurm_gpu"]["allocation_mode"]
        == "exclusive-node-inventory"
    )
    assert snapshot.metadata["slurm_gpu"]["observed_inventory_digest"] == (
        canonical_digest(devices)
    )


def test_persisted_environment_snapshot_rejects_fact_substitution(monkeypatch):
    monkeypatch.setattr(
        environment_module,
        "_probe_command",
        lambda argv, timeout=5.0: {"status": "unavailable"},
    )
    snapshot = build_environment_snapshot(
        SimpleNamespace(resources={}),
        _provider_lock(),
    )
    document = snapshot.model_dump(mode="json")
    document["resource_types"].append("gpu")
    with pytest.raises(ValueError, match="identity_digest"):
        EnvironmentSnapshotV1.model_validate(document)
