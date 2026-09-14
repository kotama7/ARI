"""The fixed CUDA validation operation, apart from the act of promoting it.

The promotion and the runtime have to submit the *same* job or the bundle's
evidence describes something the run does not do. Keeping the job in the script
that promotes it meant only a promotion could ever run it -- which is why the
capability had a verified Provider and no way to reach it.

Nothing here writes a bundle. It observes the node, builds the one fixed job,
submits it, and returns what the job saw.
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import os
import re
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any

from ari_skill_hpc import (
    AcceleratorDeviceIdentityV1,
    ArtifactPinV1,
    EnvironmentPolicyV1,
    ExclusiveNodeAcceleratorV1,
    JobRequestV1,
    LocalCommandRunner,
    OutputDeclarationV1,
    ResourceRequestV1,
    SlurmScheduler,
    SubmissionLedger,
    file_digest,
)
from cuda_promotion import cuda_architecture
from providers import ProviderProtocolError


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PACKAGE_ROOT.parent


SOURCE = PACKAGE_ROOT / "src/cuda_validation_kernel.cu"
WORKER = PACKAGE_ROOT / "src/cuda_validation_worker.py"
INVENTORY_PROBE = PACKAGE_ROOT / "src/nvidia_smi_inventory_probe.py"
HPC_CONTRACT = REPO_ROOT / "ari-skill-hpc/ari_skill_hpc/contracts.py"
HPC_SCHEDULER = REPO_ROOT / "ari-skill-hpc/ari_skill_hpc/scheduler.py"
REMOTE_NVIDIA_SMI = "/usr/bin/nvidia-smi"

def _pin(path: Path, logical_name: str, media_type: str) -> ArtifactPinV1:
    resolved = path.resolve(strict=True)
    if path.is_symlink() or not resolved.is_file():
        raise ProviderProtocolError("CUDA validation input is not a regular file")
    return ArtifactPinV1(
        logical_name=logical_name,
        path=str(resolved),
        digest=file_digest(resolved),
        size_bytes=resolved.stat().st_size,
        media_type=media_type,
    )


def _scheduler_environment() -> dict[str, str]:
    environment = {
        "HOME": "/nonexistent",
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "SLURM_EXPORT_ENV": "NONE",
    }
    for name in ("SLURM_CONF", "SLURM_CLUSTER_NAME"):
        if os.environ.get(name):
            environment[name] = os.environ[name]
    return environment


def _srun(site: dict[str, str], command: list[str], *, timeout: int = 180) -> str:
    completed = subprocess.run(
        [
            "srun",
            "--export=NONE",
            "--partition",
            site["partition"],
            "--nodes",
            "1",
            "--ntasks",
            "1",
            "--exclusive",
            "--nodelist",
            site["node_name"],
            "--time",
            "00:03:00",
            *command,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=_scheduler_environment(),
    )
    if completed.returncode:
        diagnostic = hashlib.sha256(
            (completed.stdout + completed.stderr).encode("utf-8")
        ).hexdigest()
        raise ProviderProtocolError(
            f"exclusive-node CUDA probe failed (diagnostic sha256:{diagnostic})"
        )
    return completed.stdout


def _inventory(site: dict[str, str]) -> tuple[AcceleratorDeviceIdentityV1, ...]:
    output = _srun(
        site,
        [
            REMOTE_NVIDIA_SMI,
            "--query-gpu=uuid,name,driver_version,memory.total,compute_cap",
            "--format=csv,noheader,nounits",
        ],
    )
    devices: list[AcceleratorDeviceIdentityV1] = []
    for row in csv.reader(io.StringIO(output)):
        if len(row) != 5:
            raise ProviderProtocolError("NVIDIA inventory row is malformed")
        uuid, name, driver, memory, compute = (item.strip() for item in row)
        devices.append(
            AcceleratorDeviceIdentityV1(
                uuid=uuid,
                name=name,
                driver_version=driver,
                # `[N/A]` on a unified-memory device. Refusing the row here
                # would make the whole node unpromotable over a figure the
                # self-test reads correctly from the CUDA API anyway.
                memory_mb=None if memory == "[N/A]" else int(memory),
                compute_capability=compute,
            )
        )
    devices.sort(key=lambda item: item.uuid)
    if not devices:
        raise ProviderProtocolError("exclusive-node CUDA inventory is empty")
    classes = {
        (item.name, item.driver_version, item.memory_mb, item.compute_capability)
        for item in devices
    }
    if len(classes) != 1:
        raise ProviderProtocolError("heterogeneous CUDA inventory requires another profile")
    return tuple(devices)


def _remote_tool_identity(
    site: dict[str, str], *, nvcc_path: str, worker_python: str
) -> dict[str, Any]:
    # Every one of these is digested on the node that will run them. The worker
    # interpreter used to be pinned from the submitting host instead, which is
    # only ever right when both machines run the same binaries -- on a compute
    # node of a different architecture the bundle would have recorded the
    # submitting host's interpreter for a run that never used it.
    REMOTE_NVCC = nvcc_path
    remote = [REMOTE_NVCC, REMOTE_NVIDIA_SMI, worker_python]
    digest_output = _srun(site, ["/usr/bin/sha256sum", *remote])
    digests: dict[str, str] = {}
    for line in digest_output.splitlines():
        digest, _, path = line.partition("  ")
        if path not in set(remote) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ProviderProtocolError("remote CUDA tool digest output is invalid")
        digests[path] = "sha256:" + digest
    if set(digests) != set(remote):
        raise ProviderProtocolError("remote CUDA tool identity is incomplete")
    version_output = _srun(site, [REMOTE_NVCC, "--version"])
    version = re.search(r"release\s+([^,\n]+),\s+V([^\s]+)", version_output)
    # The release is recorded, not required to be one particular value. Pinning
    # "12.9" here meant the promotion could only ever run again on the machine
    # it first ran on; the release it did find is bound into the identity below
    # and into the Provider version, which is where a version belongs.
    if not version:
        raise ProviderProtocolError("remote CUDA compiler release is unreadable")
    return {
        "worker_python_path": worker_python,
        "worker_python_digest": digests[worker_python],
        "nvcc_path": REMOTE_NVCC,
        "nvcc_digest": digests[REMOTE_NVCC],
        "cuda_release": version.group(1),
        "cuda_compiler_version": version.group(2),
        "nvidia_smi_path": REMOTE_NVIDIA_SMI,
        "nvidia_smi_digest": digests[REMOTE_NVIDIA_SMI],
    }


async def _wait(scheduler: SlurmScheduler, handle_id: str):
    async with asyncio.timeout(1_200):
        while True:
            status = await scheduler.status(handle_id)
            if status.state in {"succeeded", "failed", "cancelled"}:
                return status
            await asyncio.sleep(1)


def _public_result(value: dict[str, Any]) -> dict[str, Any]:
    devices = value.get("devices")
    if (
        value.get("schema_version") != "ari.cuda-self-test/v1"
        or value.get("verdict") != "pass"
        or not isinstance(devices, list)
        or value.get("device_count") != len(devices)
        or not devices
    ):
        raise ProviderProtocolError("CUDA self-test result did not pass")
    maximum = max(float(item["maximum_absolute_error"]) for item in devices)
    repeats = all(item.get("repeated_execution_equal") is True for item in devices)
    negatives = all(item.get("negative_control_detected") is True for item in devices)
    if maximum > 1e-6 or not repeats or not negatives:
        raise ProviderProtocolError("CUDA self-test assurance conditions failed")
    classes = sorted(
        {
            (
                str(item["name"]),
                str(item["compute_capability"]),
                int(item["memory_bytes"]),
            )
            for item in devices
        }
    )
    if len(classes) != 1:
        raise ProviderProtocolError("CUDA self-test result changed device class")
    return {
        "verdict": "pass",
        "device_count": len(devices),
        "device_classes": [
            {
                "name": name,
                "compute_capability": compute,
                "memory_bytes": memory,
            }
            for name, compute, memory in classes
        ],
        "case_count_per_device": sorted({int(item["case_count"]) for item in devices}),
        "maximum_absolute_error": maximum,
        "all_repeats_equal": repeats,
        "all_negative_controls_detected": negatives,
        "source_digest": value["source_digest"],
        "compiler_digest": value["compiler_digest"],
        "architecture": value["architecture"],
    }


async def _wait(scheduler: SlurmScheduler, handle_id: str, *, timeout: float = 1_800.0):
    """Poll until the job leaves the running states, or give up loudly."""

    waited = 0.0
    while True:
        status = await scheduler.status(handle_id)
        if status.state not in {"queued", "running", "submitted"}:
            return status
        if waited >= timeout:
            raise ProviderProtocolError("CUDA validation job did not reach a terminal state")
        await asyncio.sleep(5.0)
        waited += 5.0


async def run_cuda_validation(
    *,
    site: dict[str, str],
    work_root: Path,
    remote_nvcc: str,
    worker_python: str,
) -> dict[str, Any]:
    """Observe the node, run the fixed self-test on it, return what it saw.

    This is the operation the Provider promises. A promotion wraps evidence
    around it; a run calls it directly. Both build the identical job, because
    there is only one place that builds it.
    """

    work_root = Path(work_root).resolve(strict=True)
    if work_root.is_symlink() or not work_root.is_dir():
        raise ProviderProtocolError("CUDA SLURM work root is unsafe")
    devices = _inventory(site)
    remote_tools = _remote_tool_identity(
        site, nvcc_path=remote_nvcc, worker_python=worker_python
    )
    architecture = cuda_architecture(devices[0].compute_capability)
    source = _pin(SOURCE, "cuda-self-test-source", "text/x-cuda")
    worker = _pin(WORKER, "cuda-self-test-worker", "text/x-python")
    probe = _pin(INVENTORY_PROBE, "nvidia-smi-inventory-probe", "text/x-python")
    allocation = ExclusiveNodeAcceleratorV1(
        partition=site["partition"],
        node_name=site["node_name"],
        inventory_probe=probe,
        devices=devices,
    )
    work_dir = work_root / "cuda-exclusive-node-provider-v1"
    work_dir.mkdir(parents=True, exist_ok=True)
    result_path = work_dir / "cuda-self-test-result-v1.json"
    build_log_path = work_dir / "cuda-self-test-build.log"
    request = JobRequestV1(
        request_id="cuda-exclusive-node-provider-v1",
        job_name="ari-cuda-self-test",
        work_dir=str(work_dir),
        argv=(
            remote_tools["worker_python_path"],
            worker.path,
            "--source",
            source.path,
            "--source-digest",
            source.digest,
            "--nvcc",
            remote_tools["nvcc_path"],
            "--nvcc-digest",
            remote_tools["nvcc_digest"],
            "--architecture",
            architecture,
            "--work-dir",
            str(work_dir),
            "--result",
            str(result_path),
            "--build-log",
            str(build_log_path),
        ),
        resources=ResourceRequestV1(
            partition=site["partition"],
            nodes=1,
            tasks=1,
            tasks_per_node=1,
            cpus_per_task=2,
            walltime="00:15:00",
            nodelist=site["node_name"],
            exclusive=True,
        ),
        environment=EnvironmentPolicyV1(
            path=(
                f"{PurePosixPath(remote_tools['nvcc_path']).parent}"
                ":/usr/local/bin:/usr/bin:/bin"
            )
        ),
        accelerator_allocation=allocation,
        inputs=(source, worker, probe),
        outputs=(
            OutputDeclarationV1(
                logical_name="cuda-self-test-result",
                path=str(result_path),
                media_type="application/json",
                max_bytes=1_048_576,
            ),
            OutputDeclarationV1(
                logical_name="cuda-self-test-build-log",
                path=str(build_log_path),
                media_type="text/plain",
                max_bytes=262_144,
            ),
        ),
        metadata={
            # Named after the architecture actually validated. This said
            # "exclusive-node-sm70" on every run, whatever the device was.
            "profile": f"exclusive-node-{architecture.replace('_', '')}",
            "gpu_gres": False,
        },
    )
    scheduler = SlurmScheduler(
        runner=LocalCommandRunner(command_timeout=60),
        ledger=SubmissionLedger(work_root / "cuda-provider-jobs-v1.json"),
        shared_filesystem=True,
        terminal_evidence_policy="fixed-wrapper-marker",
    )
    handle = await scheduler.submit(request)
    status = await _wait(scheduler, handle.handle_id)
    result = await scheduler.result(handle.handle_id)
    if status.state != "succeeded" or result.error is not None:
        raise ProviderProtocolError("typed CUDA validation job did not succeed")
    raw_result = json.loads(result_path.read_text(encoding="utf-8"))
    return {
        "devices": devices,
        "remote_tools": remote_tools,
        "architecture": architecture,
        "request": request,
        "raw_result": raw_result,
        "public_result": _public_result(raw_result),
        "inputs": (source, worker, probe),
        "work_dir": work_dir,
    }
