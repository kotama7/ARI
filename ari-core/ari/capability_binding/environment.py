"""Value-free, digest-bound-at-admission execution environment facts."""

from __future__ import annotations

import csv
import io
import os
import platform
import re
import shutil
import subprocess

from ari.protocols.integrity import bytes_digest, canonical_digest, is_full_sha256
from ari.protocols.scientific_requirements import EnvironmentSnapshotV1


def _probe_command(argv: tuple[str, ...], *, timeout: float = 5.0) -> dict:
    """Run one allowlisted, read-only substrate probe without a shell."""

    executable = shutil.which(argv[0])
    if executable is None:
        return {"status": "unavailable", "argv": list(argv)}
    environment = {
        "HOME": "/nonexistent",
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": os.defpath,
    }
    for name in ("SLURM_CONF", "SLURM_CLUSTER_NAME"):
        value = os.environ.get(name)
        if value:
            environment[name] = value
    try:
        completed = subprocess.run(
            (executable, *argv[1:]),
            check=False,
            capture_output=True,
            text=False,
            timeout=timeout,
            env=environment,
        )
    except subprocess.TimeoutExpired:
        return {
            "status": "timed_out",
            "argv": list(argv),
            "executable": executable,
        }
    except OSError as exc:
        return {
            "status": "failed",
            "argv": list(argv),
            "executable": executable,
            "error_type": type(exc).__name__,
        }
    stdout = completed.stdout[:128 * 1024]
    stderr = completed.stderr[:16 * 1024]
    return {
        "status": "ready" if completed.returncode == 0 else "failed",
        "argv": list(argv),
        "executable": executable,
        "exit_code": completed.returncode,
        "stdout": stdout.decode("utf-8", errors="replace"),
        "stdout_digest": bytes_digest(stdout),
        "stderr": stderr.decode("utf-8", errors="replace")[:1_000],
        "stderr_digest": bytes_digest(stderr),
        "output_truncated": (
            len(completed.stdout) > len(stdout) or len(completed.stderr) > len(stderr)
        ),
    }


def _slurm_probe() -> dict:
    observed = _probe_command(
        ("sinfo", "--noheader", "--format=%P|%a|%t|%D|%c|%m|%G|%f")
    )
    partitions = []
    if observed.get("status") == "ready":
        for raw in str(observed.get("stdout", "")).splitlines():
            fields = raw.split("|", 7)
            if len(fields) != 8:
                continue
            partition, availability, state, nodes, cpus, memory, gres, features = fields
            try:
                node_count = int(nodes)
                cpu_count = int(cpus)
                memory_mb = int(memory)
            except ValueError:
                continue
            partitions.append(
                {
                    "partition": partition.rstrip("*"),
                    "availability": availability,
                    "state": state,
                    "nodes": node_count,
                    "cpus_per_node": cpu_count,
                    "memory_mb_per_node": memory_mb,
                    "gres": gres,
                    "features": features,
                }
            )
    partitions.sort(key=lambda item: (item["partition"], item["state"], item["gres"]))
    usable = any(
        item["availability"] == "up"
        and item["nodes"] > 0
        and not item["state"].casefold().startswith(("down", "drain"))
        for item in partitions
    )
    gpu_gres = any(
        re.search(r"(?:^|,)gpu(?::|=)", item["gres"], flags=re.IGNORECASE)
        for item in partitions
    )
    return {
        "status": "ready" if usable else observed.get("status", "unavailable"),
        "probe_output_digest": observed.get("stdout_digest"),
        "diagnostic": str(observed.get("stderr", ""))[:500],
        "partitions": partitions,
        "gpu_gres_available": gpu_gres,
    }


def _gpu_probe() -> dict:
    observed = _probe_command(
        (
            "nvidia-smi",
            "--query-gpu=uuid,name,compute_cap,memory.total,driver_version",
            "--format=csv,noheader,nounits",
        )
    )
    devices = _parse_gpu_devices(str(observed.get("stdout", "")))
    toolkit = _probe_command(("nvcc", "--version"))
    version_match = re.search(
        r"release\s+([^,\n]+),\s+V([^\s]+)",
        str(toolkit.get("stdout", "")),
    )
    return {
        "status": "ready" if devices else observed.get("status", "unavailable"),
        "probe_output_digest": observed.get("stdout_digest"),
        "diagnostic": str(observed.get("stderr", ""))[:500],
        "devices": devices,
        "cuda_toolkit": {
            "status": toolkit.get("status", "unavailable"),
            "release": version_match.group(1) if version_match else None,
            "compiler_version": version_match.group(2) if version_match else None,
            "probe_output_digest": toolkit.get("stdout_digest"),
        },
    }


def _parse_gpu_devices(stdout: str) -> list[dict]:
    devices = []
    for row in csv.reader(io.StringIO(stdout)):
        if len(row) != 5:
            continue
        uuid, name, compute_capability, memory_mb, driver = (
            value.strip() for value in row
        )
        try:
            memory = int(memory_mb)
        except ValueError:
            continue
        devices.append(
            {
                "uuid": uuid,
                "name": name,
                "compute_capability": compute_capability,
                "memory_mb": memory,
                "driver_version": driver,
            }
        )
    devices.sort(key=lambda item: item["uuid"])
    return devices


def _requested_gpu_count(resources: dict) -> int:
    value = resources.get("gpus", 0)
    if isinstance(value, bool):
        return int(value)
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _slurm_gpu_probe(slurm: dict, resources: dict) -> dict:
    """Observe a requested GPU on a compute node without granting authority.

    A cluster can expose devices while omitting GPU GRES accounting.  Such a
    device is recorded, but it is not a schedulable ``gpu`` resource unless
    GRES was observed or the existing explicit no-GRES operator override is
    active.
    """

    if slurm.get("status") != "ready" or _requested_gpu_count(resources) < 1:
        return {
            "status": "not_requested",
            "partition": None,
            "devices": [],
            "schedulable": False,
            "allocation_mode": "not-requested",
        }
    requested_partition = str(resources.get("partition") or "").strip()
    usable = [
        item
        for item in slurm.get("partitions", ())
        if item.get("availability") == "up"
        and item.get("nodes", 0) > 0
        and not str(item.get("state", "")).casefold().startswith(("down", "drain"))
    ]
    if requested_partition:
        usable = [
            item for item in usable if item.get("partition") == requested_partition
        ]
    if not usable:
        return {
            "status": "unavailable",
            "partition": requested_partition or None,
            "devices": [],
            "schedulable": False,
            "allocation_mode": "no-usable-partition",
        }
    partition = sorted(usable, key=lambda item: item["partition"])[0]["partition"]
    gres_available = bool(slurm.get("gpu_gres_available"))
    argv = [
        "srun",
        "--partition",
        partition,
        "--nodes",
        "1",
        "--ntasks",
        "1",
        "--time",
        "00:01:00",
    ]
    if gres_available:
        argv.extend(["--gres", "gpu:1"])
    else:
        argv.append("--exclusive")
        node_name = str(resources.get("gpu_node") or "").strip()
        if node_name and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:@+-]{0,127}", node_name):
            argv.extend(["--nodelist", node_name])
    argv.extend(
        [
            "nvidia-smi",
            "--query-gpu=uuid,name,compute_cap,memory.total,driver_version",
            "--format=csv,noheader,nounits",
        ]
    )
    observed = _probe_command(tuple(argv), timeout=75.0)
    devices = (
        _parse_gpu_devices(str(observed.get("stdout", "")))
        if observed.get("status") == "ready"
        else []
    )
    observed_inventory_digest = canonical_digest(devices)
    expected_inventory_digest = str(
        resources.get("gpu_inventory_digest") or ""
    ).strip()
    explicit_exclusive = (
        resources.get("gpu_allocation_mode") == "exclusive-node-inventory"
        and resources.get("exclusive") is True
        and bool(str(resources.get("gpu_node") or "").strip())
        and is_full_sha256(expected_inventory_digest)
    )
    inventory_matches = (
        explicit_exclusive
        and expected_inventory_digest == observed_inventory_digest
        and _requested_gpu_count(resources) <= len(devices)
    )
    schedulable = bool(devices) and (gres_available or inventory_matches)
    if gres_available:
        allocation_mode = "gres"
    elif inventory_matches:
        allocation_mode = "exclusive-node-inventory"
    elif explicit_exclusive:
        allocation_mode = "exclusive-node-inventory-mismatch"
    else:
        allocation_mode = "observation-only-no-gres"
    return {
        "status": "ready" if devices else observed.get("status", "unavailable"),
        "partition": partition,
        "probe_output_digest": observed.get("stdout_digest"),
        "diagnostic": str(observed.get("stderr", ""))[:500],
        "devices": devices,
        "observed_inventory_digest": observed_inventory_digest,
        "expected_inventory_digest": expected_inventory_digest or None,
        "schedulable": schedulable,
        "allocation_mode": allocation_mode,
    }


def build_environment_snapshot(cfg, provider_lock) -> EnvironmentSnapshotV1:
    resources = dict(getattr(cfg, "resources", None) or {})
    tool_policies = [dict(item.policy) for item in provider_lock.tools]
    permissions = {
        str(permission)
        for policy in tool_policies
        for permission in policy.get("permissions", ())
    }
    slurm = _slurm_probe()
    gpu = _gpu_probe()
    slurm_gpu = (
        _slurm_gpu_probe(slurm, resources)
        if not gpu["devices"]
        else {
            "status": "not_needed_local_gpu_ready",
            "partition": None,
            "devices": [],
            "schedulable": False,
            "allocation_mode": "local-device",
        }
    )
    resource_types = {"process", "cpu"}
    if slurm["status"] == "ready":
        resource_types.add("slurm")
    if (
        gpu["status"] == "ready"
        or slurm["gpu_gres_available"]
        or slurm_gpu["schedulable"]
    ):
        resource_types.add("gpu")
    features = {
        value.strip()
        for value in os.environ.get("ARI_KCA_ENV_FEATURES", "").split(",")
        if value.strip()
    }
    if slurm["status"] == "ready":
        features.add("slurm-controller")
    if slurm["gpu_gres_available"]:
        features.add("gpu-via-slurm")
    if gpu["devices"]:
        features.add("nvidia-gpu")
    if slurm_gpu["devices"]:
        features.add("gpu-observed-on-slurm-node")
    if slurm_gpu["schedulable"]:
        features.add("gpu-via-slurm")
    if gpu["cuda_toolkit"]["status"] == "ready":
        features.add("cuda-toolkit")
    transports = {
        "mcp-stdio" if str(item.entrypoint).endswith(".py") else "mcp-external"
        for item in provider_lock.skills
    }
    network_classes = {"none"}
    if "network" in permissions or "network-read" in permissions:
        network_classes.add("external")
    body = {
        "resource_types": tuple(sorted(resource_types)),
        "features": tuple(sorted(features)),
        "transports": tuple(sorted(transports)),
        "network_classes": tuple(sorted(network_classes)),
        "metadata": {
            "architecture": platform.machine() or "unknown",
            "platform": platform.system().lower() or "unknown",
            "python": platform.python_version(),
            "declared_resources": resources,
            "declared_scheduler_permission": (
                "scheduler" in permissions or "scheduler-submit" in permissions
            ),
            "slurm": slurm,
            "gpu": gpu,
            "slurm_gpu": slurm_gpu,
        },
    }
    return EnvironmentSnapshotV1.create(**body)


__all__ = ["build_environment_snapshot"]
