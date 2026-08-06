from __future__ import annotations

import errno
from types import SimpleNamespace

import pytest

from ari.capability_binding import environment as environment_module
from ari.capability_binding.environment import build_environment_snapshot
from ari.protocols.integrity import canonical_digest
from ari.protocols.scientific_requirements import EnvironmentSnapshotV1


_REAL_COUNTER_PROBE = environment_module._hardware_counter_probe
_REAL_CONTAINER_PROBE = environment_module._container_runtime_probe


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


@pytest.fixture(autouse=True)
def _container_runtime_is_not_inherited_from_the_test_host(monkeypatch):
    """Same reason as the counter fixture: a host that has Singularity would
    otherwise derive ``eda-cpu`` into every exact-resource assertion below."""

    monkeypatch.setattr(
        environment_module,
        "_container_runtime_probe",
        lambda: {"status": "unavailable", "runtime": None, "version": None},
    )


@pytest.fixture(autouse=True)
def _network_route_is_not_inherited_from_the_test_host(monkeypatch):
    """A host with a default route would otherwise derive the network resource
    into every exact-resource assertion below."""

    monkeypatch.setattr(
        environment_module,
        "_network_route_probe",
        lambda: {"status": "unavailable", "families": []},
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
    # gpu-slurm is derived, not observed: a capability wanting a GPU through the
    # scheduler needs both halves and the prober only ever emits them apart.
    assert first.resource_types == (
        "cpu",
        "gpu",
        "gpu-slurm",
        "process",
        "quantum-simulator",
        "slurm",
    )
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

    # quantum-simulator derives from cpu alone: a seeded two-qubit CPU
    # statevector pass needs nothing else. A substrate claim, not an
    # availability claim -- the pinned artifact still has to be registered.
    assert snapshot.resource_types == ("cpu", "process", "quantum-simulator")
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

    assert snapshot.resource_types == (
        "cpu",
        "process",
        "quantum-simulator",
        "slurm",
    )
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

    assert snapshot.resource_types == ("cpu", "process", "quantum-simulator")
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


# ------------------------------------------- container runtime and derivations


def _observe_runtime(monkeypatch, answers):
    """Restore the real probe and let ``answers`` decide what each binary says."""

    monkeypatch.setattr(
        environment_module, "_container_runtime_probe", _REAL_CONTAINER_PROBE
    )

    def probe(argv, *, timeout=5.0):
        del timeout
        return answers.get(argv[0], {"status": "unavailable"})

    monkeypatch.setattr(environment_module, "_probe_command", probe)


def _ready(stdout):
    return {
        "status": "ready",
        "stdout": stdout,
        "stdout_digest": canonical_digest(stdout),
        "stderr": "",
    }


def _derivations():
    from ari.capability_binding.ontology import load_resource_derivations
    from ari.config.finder import package_config_root

    return load_resource_derivations(
        package_config_root() / "capabilities" / "resource_derivations.yaml"
    )


def test_container_runtime_records_the_fork_that_actually_answered(monkeypatch):
    _observe_runtime(
        monkeypatch, {"singularity": _ready("singularity-ce version 4.5.0\n")}
    )
    snapshot = build_environment_snapshot(SimpleNamespace(), _provider_lock())
    assert "singularity" in snapshot.features
    assert "apptainer" not in snapshot.features
    assert snapshot.metadata["container_runtime"]["runtime"] == "singularity"
    # The path the binary was found at is site-dependent and binding needs none
    # of it, so it is not carried into the frozen identity.
    assert "executable" not in snapshot.metadata["container_runtime"]


def test_a_runtime_that_is_installed_but_broken_is_not_a_capability(monkeypatch):
    _observe_runtime(
        monkeypatch, {"apptainer": {"status": "failed", "exit_code": 1, "stdout": ""}}
    )
    snapshot = build_environment_snapshot(SimpleNamespace(), _provider_lock())
    assert "apptainer" not in snapshot.features
    assert "sif-container-runtime" not in snapshot.features
    assert "eda-cpu" not in snapshot.resource_types
    # Present-but-failing is a different fact from absent, and the operator
    # needs to see which one it was.
    assert snapshot.metadata["container_runtime"]["status"] == "failed"
    assert snapshot.metadata["container_runtime"]["runtime"] == "apptainer"


def test_either_fork_derives_the_reviewed_sif_capability(monkeypatch):
    for name in ("apptainer", "singularity"):
        _observe_runtime(monkeypatch, {name: _ready(f"{name} version 1.4.0\n")})
        snapshot = build_environment_snapshot(
            SimpleNamespace(), _provider_lock(), resource_derivations=_derivations()
        )
        assert "sif-container-runtime" in snapshot.features, name
        assert "eda-cpu" in snapshot.resource_types, name
        assert snapshot.metadata["derived_from_review"] == (
            "feature:sif-container-runtime",
            "resource_type:eda-cpu",
            "resource_type:quantum-simulator",
        )


def test_an_oci_only_runtime_does_not_derive_the_sif_capability(monkeypatch):
    _observe_runtime(monkeypatch, {"podman": _ready("podman version 5.8.2\n")})
    snapshot = build_environment_snapshot(
        SimpleNamespace(), _provider_lock(), resource_derivations=_derivations()
    )
    assert "sif-container-runtime" not in snapshot.features
    assert "eda-cpu" not in snapshot.resource_types


def test_derivations_cannot_invent_a_fact_the_prober_did_not_observe(monkeypatch):
    _observe_runtime(monkeypatch, {})
    snapshot = build_environment_snapshot(
        SimpleNamespace(), _provider_lock(), resource_derivations=_derivations()
    )
    assert "eda-cpu" not in snapshot.resource_types
    # Only the cpu-derived class fires: nothing here invented a container
    # runtime, a route, or a counter the prober did not see.
    assert snapshot.metadata["derived_from_review"] == (
        "resource_type:quantum-simulator",
    )


def test_a_derivation_without_a_reason_is_refused(tmp_path):
    from ari.capability_binding.ontology import (
        ResourceDerivationError,
        load_resource_derivations,
    )

    path = tmp_path / "derivations.yaml"
    path.write_text(
        "derivations:\n"
        "  - emits: eda-cpu\n"
        "    kind: resource_type\n"
        "    requires_resource_types: [cpu]\n",
        encoding="utf-8",
    )
    with pytest.raises(ResourceDerivationError, match="rationale"):
        load_resource_derivations(path)


def test_shipped_derivations_reach_a_fixpoint_through_a_chained_row():
    from ari.capability_binding.ontology import apply_resource_derivations

    # eda-cpu depends on a feature another row emits, so a single pass is not
    # enough; this is what the fixpoint loop is for.
    features, resources, fired = apply_resource_derivations(
        features={"singularity"},
        resource_types={"cpu", "process"},
        derivations=_derivations(),
    )
    assert "sif-container-runtime" in features
    assert "eda-cpu" in resources
    assert fired == (
        "feature:sif-container-runtime",
        "resource_type:eda-cpu",
        "resource_type:quantum-simulator",
    )


def _observe_route(monkeypatch, *, ipv4=False, ipv6=False):
    monkeypatch.setattr(
        environment_module,
        "_network_route_probe",
        lambda: {
            "status": "ready" if (ipv4 or ipv6) else "unavailable",
            "families": [n for n, on in (("ipv4", ipv4), ("ipv6", ipv6)) if on],
        },
    )


def test_a_default_route_derives_the_network_resource(monkeypatch):
    _observe_route(monkeypatch, ipv4=True)
    snapshot = build_environment_snapshot(
        SimpleNamespace(), _provider_lock(), resource_derivations=_derivations()
    )
    assert "network-route" in snapshot.features
    assert "network-read" in snapshot.features
    assert "network" in snapshot.resource_types


def test_an_air_gapped_node_supplies_no_network_resource(monkeypatch):
    """No route, nothing fires -- the retrieval capability stays unsupplied."""

    _observe_route(monkeypatch)
    snapshot = build_environment_snapshot(
        SimpleNamespace(), _provider_lock(), resource_derivations=_derivations()
    )
    assert "network-route" not in snapshot.features
    assert "network-read" not in snapshot.features
    assert "network" not in snapshot.resource_types


def test_the_quantum_class_derives_from_cpu_and_says_why_that_is_enough():
    """Withheld while nothing supplied it; accurate now that something does.

    A seeded two-qubit CPU statevector pass needs a CPU and nothing else. The
    row is weak because the capability is, and the rationale has to say so --
    what actually bounds it is the pinned artifact no derivation can see.
    """

    (row,) = [item for item in _derivations() if item.emits == "quantum-simulator"]
    assert row.requires_resource_types == frozenset({"cpu"})
    assert row.requires_features == frozenset()
    assert "no device" in row.rationale


# ------------------------------------------------------- observed GPU identity


def test_a_device_with_an_unreadable_memory_figure_is_still_a_device():
    """Grace-Blackwell reports memory.total as "[N/A]" -- unified memory.

    Dropping the row made ARI see no GPU at all on a node that has one, so
    every GPU capability was silently unbindable there. This is the exact line
    a real GB10 node returns for the prober's own query; it cannot be
    reproduced from a login node, which is why it survived.
    """

    row = "GPU-e24bed87-5853-1036-cbfc-b54eac6acda1, NVIDIA GB10, 12.1, [N/A], 580.159.03"
    (device,) = environment_module._parse_gpu_devices(row)
    assert device["name"] == "NVIDIA GB10"
    assert device["compute_capability"] == "12.1"
    assert device["memory_mb"] is None


def test_the_toolkit_version_and_device_generation_become_features(monkeypatch):
    """Both were observed and thrown away, so a contract naming either could
    never be satisfied by anything."""

    def probe(argv, *, timeout=5.0):
        del timeout
        if argv[0] == "nvidia-smi":
            return _ready("GPU-1, Tesla V100-SXM2-16GB, 7.0, 16384, 575.64.03\n")
        if argv[0] == "nvcc":
            return _ready(
                "Cuda compilation tools, release 12.9, V12.9.41\n"
                "Build cuda_12.9.r12.9/compiler.0_0\n"
            )
        return {"status": "unavailable"}

    monkeypatch.setattr(environment_module, "_probe_command", probe)
    snapshot = build_environment_snapshot(
        SimpleNamespace(resources={"gpus": 1}), _provider_lock()
    )
    assert "cuda-12.9" in snapshot.features
    assert "nvidia-sm70" in snapshot.features
    # Exactly what was observed, and nothing about what it is compatible with.
    assert "cuda-12.0" not in snapshot.features
    assert "nvidia-sm80" not in snapshot.features


def test_a_newer_device_does_not_claim_an_older_generation(monkeypatch):
    """Whether an sm70 build runs on Blackwell depends on how it was built."""

    def probe(argv, *, timeout=5.0):
        del timeout
        if argv[0] == "nvidia-smi":
            return _ready("GPU-1, NVIDIA GB10, 12.1, [N/A], 580.159.03\n")
        if argv[0] == "nvcc":
            return _ready("Cuda compilation tools, release 12.0, V12.0.140\n")
        return {"status": "unavailable"}

    monkeypatch.setattr(environment_module, "_probe_command", probe)
    snapshot = build_environment_snapshot(
        SimpleNamespace(resources={"gpus": 1}), _provider_lock()
    )
    assert "nvidia-sm121" in snapshot.features
    assert "nvidia-sm70" not in snapshot.features
    assert "cuda-12.0" in snapshot.features
    assert "cuda-12.9" not in snapshot.features
