from __future__ import annotations

import errno
from types import SimpleNamespace

import pytest

from ari.capability_binding import environment as environment_module
from ari.capability_binding.environment import build_environment_snapshot
from ari.protocols.integrity import canonical_digest
from ari.protocols.scientific_requirements import EnvironmentSnapshotV1


_REAL_COUNTER_PROBE = environment_module._hardware_counter_probe


def _provider_lock():
    return SimpleNamespace(
        tools=(
            SimpleNamespace(policy={"permissions": ["scheduler-submit"]}),
        ),
        skills=(SimpleNamespace(entrypoint="ari-skill-hpc/src/server.py"),),
    )


@pytest.fixture(autouse=True)
def _counter_policy_is_not_inherited_from_the_test_host(monkeypatch):
    """Keep substrate-independent cases off the live counter policy.

    The counter probe reads the kernel policy of whatever machine runs the
    suite, so the cases that assert exact resource sets pin it here.  The
    counter cases below override this fixture with their own observation.
    """

    monkeypatch.setattr(
        environment_module,
        "_hardware_counter_probe",
        lambda: {
            "status": "denied",
            "events": ["cycles", "instructions"],
            "perf_event_paranoid": 3,
            "architecture": "x86_64",
            "errno": errno.EACCES,
        },
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


def _observe_counters(monkeypatch, *, opened, code=0, machine="x86_64", paranoid=0):
    """Drive the real probe over one synthetic kernel answer."""

    monkeypatch.setattr(
        environment_module, "_hardware_counter_probe", _REAL_COUNTER_PROBE
    )
    monkeypatch.setattr(environment_module.platform, "system", lambda: "Linux")
    monkeypatch.setattr(environment_module.platform, "machine", lambda: machine)
    monkeypatch.setattr(
        environment_module, "_perf_event_paranoid", lambda: paranoid
    )
    monkeypatch.setattr(
        environment_module,
        "_open_hardware_counter",
        lambda number, config: (opened, code),
    )
    monkeypatch.setattr(
        environment_module,
        "_probe_command",
        lambda argv, timeout=5.0: {"status": "unavailable"},
    )


def test_opened_hardware_counters_admit_the_profiling_substrate(monkeypatch):
    _observe_counters(monkeypatch, opened=True)
    snapshot = build_environment_snapshot(
        SimpleNamespace(resources={}), _provider_lock()
    )

    assert "hardware-counters" in snapshot.resource_types
    assert "hardware-counters" in snapshot.features
    assert snapshot.metadata["hardware_counters"]["status"] == "ready"
    assert snapshot.metadata["hardware_counters"]["perf_event_paranoid"] == 0
    assert snapshot.metadata["hardware_counters"]["events"] == [
        "cycles",
        "instructions",
    ]


def test_denied_hardware_counters_do_not_fabricate_the_substrate(monkeypatch):
    _observe_counters(monkeypatch, opened=False, code=errno.EACCES, paranoid=4)
    snapshot = build_environment_snapshot(
        SimpleNamespace(resources={}), _provider_lock()
    )

    assert snapshot.resource_types == ("cpu", "process")
    assert "hardware-counters" not in snapshot.features
    assert snapshot.metadata["hardware_counters"]["status"] == "denied"
    assert snapshot.metadata["hardware_counters"]["errno"] == errno.EACCES


def test_unknown_architecture_reports_unsupported_rather_than_guessing(monkeypatch):
    _observe_counters(monkeypatch, opened=True, machine="sparc64")
    snapshot = build_environment_snapshot(
        SimpleNamespace(resources={}), _provider_lock()
    )

    assert "hardware-counters" not in snapshot.features
    assert snapshot.metadata["hardware_counters"]["status"] == "unsupported"


def test_counter_substrate_is_decided_by_execution_not_by_a_profiler_binary(
    monkeypatch,
):
    """A present ``perf`` must not stand in for an actually openable counter."""

    _observe_counters(monkeypatch, opened=False, code=errno.EACCES)
    monkeypatch.setattr(
        environment_module.shutil, "which", lambda name: f"/usr/bin/{name}"
    )
    snapshot = build_environment_snapshot(
        SimpleNamespace(resources={}), _provider_lock()
    )

    assert "hardware-counters" not in snapshot.features


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
