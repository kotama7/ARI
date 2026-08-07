#!/usr/bin/env python3
"""Promote the exact anonymous exclusive-node CUDA self-test Provider."""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PACKAGE_ROOT.parent
for dependency in (
    REPO_ROOT / "ari-core",
    REPO_ROOT / "ari-skill-hpc",
    PACKAGE_ROOT / "src",
):
    if str(dependency) not in sys.path:
        sys.path.insert(0, str(dependency))

from capability_pins import (  # noqa: E402
    capability_contract,
    capability_environment_requirements,
)
from ari.providers.registration import (  # noqa: E402
    PROVIDER_REGISTRATION_GATES,
    ProviderRegistrationGateV1,
    registration_report,
)
from ari_skill_hpc import (  # noqa: E402
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
from cuda_promotion import (  # noqa: E402
    CUDA_BUNDLE,
    CUDA_CAPABILITY_REF,
    CUDA_EVIDENCE_SCHEMA,
    CUDA_LOCK_SCHEMA,
    CUDA_MANIFEST_SCHEMA,
    CUDA_PROVIDER_ID,
    CUDA_PROVIDER_VERSION,
    verify_cuda_verified_lock,
)
from models import sha256_digest  # noqa: E402
from providers import ProviderProtocolError  # noqa: E402
from site_privacy import (  # noqa: E402
    assert_no_private_site_identity,
    assert_repository_site_anonymous,
    load_private_site_config,
    public_site_identity,
)


SOURCE = PACKAGE_ROOT / "src/cuda_validation_kernel.cu"
WORKER = PACKAGE_ROOT / "src/cuda_validation_worker.py"
INVENTORY_PROBE = PACKAGE_ROOT / "src/nvidia_smi_inventory_probe.py"
HPC_CONTRACT = REPO_ROOT / "ari-skill-hpc/ari_skill_hpc/contracts.py"
HPC_SCHEDULER = REPO_ROOT / "ari-skill-hpc/ari_skill_hpc/scheduler.py"
REMOTE_NVCC = "/usr/local/cuda-12.9/bin/nvcc"
REMOTE_NVIDIA_SMI = "/usr/bin/nvidia-smi"


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name("." + path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


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
                memory_mb=int(memory),
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


def _remote_tool_identity(site: dict[str, str]) -> dict[str, Any]:
    digest_output = _srun(
        site,
        ["/usr/bin/sha256sum", REMOTE_NVCC, REMOTE_NVIDIA_SMI],
    )
    digests: dict[str, str] = {}
    for line in digest_output.splitlines():
        digest, _, path = line.partition("  ")
        if path not in {REMOTE_NVCC, REMOTE_NVIDIA_SMI} or not re.fullmatch(
            r"[0-9a-f]{64}", digest
        ):
            raise ProviderProtocolError("remote CUDA tool digest output is invalid")
        digests[path] = "sha256:" + digest
    if set(digests) != {REMOTE_NVCC, REMOTE_NVIDIA_SMI}:
        raise ProviderProtocolError("remote CUDA tool identity is incomplete")
    version_output = _srun(site, [REMOTE_NVCC, "--version"])
    version = re.search(r"release\s+([^,\n]+),\s+V([^\s]+)", version_output)
    if not version or version.group(1) != "12.9":
        raise ProviderProtocolError("remote CUDA compiler release differs")
    return {
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


def _tests(test_python: str) -> dict[str, Any]:
    test_ids = (
        "ari-skill-hpc/tests/test_contracts.py",
        "ari-skill-hpc/tests/test_slurm_local.py",
        "ari-skill-tool-registry/tests/test_cuda_validation.py",
        "ari-skill-tool-registry/tests/test_site_privacy.py",
    )
    completed = subprocess.run(
        [test_python, "-m", "pytest", *test_ids, "-q"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        timeout=900,
        env={key: value for key, value in os.environ.items() if key != "GIT_INDEX_FILE"},
    )
    output = completed.stdout + completed.stderr
    if completed.returncode:
        raise RuntimeError(output.decode("utf-8", errors="replace")[-12_000:])
    return {
        "command": ["<test-python>", "-m", "pytest", *test_ids, "-q"],
        "exit_code": 0,
        "output_sha256": "sha256:" + hashlib.sha256(output).hexdigest(),
        "test_ids": list(test_ids),
    }


def _gate_evidence(
    *, manifest: dict[str, Any], observations: dict[str, Any], tests: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    scope = manifest["capability_scope"]
    common = {"test_output_sha256": tests["output_sha256"]}
    return {
        "manifest_schema": {"schema": manifest["schema_version"], **common},
        "source_package_digest_pin": {"artifact": manifest["artifact"]},
        "live_tools_list_parity": {
            "fixed_local_process_tool": scope["tool_names"],
            "input_schema_digest": scope["input_schema_digest"],
        },
        "schema_digest_pin": {
            "input": scope["input_schema_digest"],
            "output": scope["output_schema_digest"],
        },
        "capability_contract_conformance": {
            "capability_ref": CUDA_CAPABILITY_REF,
            "self_test": observations["cuda_self_test"],
        },
        "side_effect_declaration": {
            "side_effects": scope["side_effects"],
            "permissions": scope["permissions"],
        },
        "credential_scope": {"credential_scope_ids": []},
        "environment_allowlist": manifest["runtime_target"],
        "timeout_cancellation_process_group": {
            "timeout_seconds": 1_200,
            "terminal_evidence_policy": "fixed-wrapper-marker",
            **common,
        },
        "result_schema": observations["cuda_self_test"],
        "malicious_description_boundary": {
            "authority_source": "fixed typed request and verified lock",
            **common,
        },
        "workspace_isolation": observations["execution"],
        "revocation_behavior": {
            "rule": "non-verified status is ineligible for enforce binding"
        },
        "schema_drift_detection": {
            "remote_tool_identity": observations["remote_tool_identity"],
            "inventory_identity_digest": manifest["runtime_target"][
                "inventory_identity_digest"
            ],
        },
        "unbound_invocation_rejection": {
            "surface": "one fixed self-test leaf; no arbitrary command input"
        },
    }


def _bundle(
    *,
    output: Path,
    actor: str,
    captured_date: str,
    artifact: dict[str, Any],
    scope: dict[str, Any],
    runtime_target: dict[str, Any],
    observations: dict[str, Any],
    tests: dict[str, Any],
) -> dict[str, str]:
    adapter = {
        "kind": "ari-hpc-fixed-local-process",
        "revision": "ari.cuda-exclusive-node-provider/v1",
        "runtime_digest": sha256_digest(
            {
                "worker": artifact["worker_digest"],
                "scheduler": artifact["scheduler_digest"],
                "contract": artifact["job_contract_digest"],
            }
        ),
        "terminal_evidence_policy": "fixed-wrapper-marker",
    }
    manifest = {
        "schema_version": CUDA_MANIFEST_SCHEMA,
        "provider_id": CUDA_PROVIDER_ID,
        "provider_version": CUDA_PROVIDER_VERSION,
        "artifact": artifact,
        "adapter": adapter,
        "runtime_target": runtime_target,
        "environment_policy": {
            "network": "host-uncredentialed",
            "credential_scope_ids": [],
            "scheduler": "anonymous-exclusive-node",
            "gpu_gres": False,
        },
        "capability_scope": scope,
    }
    manifest_digest = sha256_digest(manifest)
    gate_evidence = _gate_evidence(
        manifest=manifest, observations=observations, tests=tests
    )
    if tuple(gate_evidence) != PROVIDER_REGISTRATION_GATES:
        raise ValueError("CUDA Provider registration gates are incomplete")
    evidence = {
        "schema_version": CUDA_EVIDENCE_SCHEMA,
        "provider_id": CUDA_PROVIDER_ID,
        "provider_version": CUDA_PROVIDER_VERSION,
        "captured_date": captured_date,
        "artifact": artifact,
        "capability_scope": scope,
        "observations": observations,
        "test_run": tests,
        "gate_evidence": gate_evidence,
    }
    evidence["bundle_digest"] = sha256_digest(evidence)
    gates = tuple(
        ProviderRegistrationGateV1(
            gate_id=gate_id,
            passed=True,
            evidence_digest=sha256_digest(gate_evidence[gate_id]),
            detail="closed anonymous exclusive-node CUDA self-test evidence passed",
        )
        for gate_id in PROVIDER_REGISTRATION_GATES
    )
    report = registration_report(
        provider_id=CUDA_PROVIDER_ID,
        manifest_sha256=manifest_digest,
        gates=gates,
    ).model_dump(mode="json")
    approval = {
        "schema_version": "ari.capability-provider-promotion-approval/v1",
        "provider_id": CUDA_PROVIDER_ID,
        "provider_version": CUDA_PROVIDER_VERSION,
        "from_status": "candidate",
        "to_status": "verified",
        "actor_kind": "human-maintainer",
        "actor_id": actor,
        "authorization_basis": "explicit-maintainer-approval",
        "approved_date": captured_date,
        "provider_manifest_digest": manifest_digest,
        "registration_report_digest": report["report_digest"],
        "evidence_bundle_digest": evidence["bundle_digest"],
        "capability_scope_digest": sha256_digest(scope),
    }
    approval["approval_digest"] = sha256_digest(approval)
    lock = {
        "schema_version": CUDA_LOCK_SCHEMA,
        "provider_id": CUDA_PROVIDER_ID,
        "provider_version": CUDA_PROVIDER_VERSION,
        "status": "verified",
        "artifact": artifact,
        "adapter": adapter,
        "runtime_target": runtime_target,
        "capability_scope": scope,
        "registration": {
            "provider_manifest_path": "provider-manifest-v1.json",
            "provider_manifest_digest": manifest_digest,
            "evidence_path": "registration-evidence-v1.json",
            "evidence_bundle_digest": evidence["bundle_digest"],
            "report_path": "registration-report-v1.json",
            "report_digest": report["report_digest"],
        },
        "promotion": {
            "approval_path": "promotion-approval-v1.json",
            "approval_digest": approval["approval_digest"],
        },
    }
    lock["lock_digest"] = sha256_digest(lock)
    for filename, document in (
        ("provider-manifest-v1.json", manifest),
        ("registration-evidence-v1.json", evidence),
        ("registration-report-v1.json", report),
        ("promotion-approval-v1.json", approval),
        ("verified-lock-v1.json", lock),
    ):
        _write_json(output / filename, document)
    verify_cuda_verified_lock(
        output / "verified-lock-v1.json", expected_lock_digest=lock["lock_digest"]
    )
    return {
        "lock_digest": lock["lock_digest"],
        "approval_digest": approval["approval_digest"],
        "report_digest": report["report_digest"],
    }


async def _run(args: argparse.Namespace) -> dict[str, str]:
    output = Path(args.output).resolve()
    if output != CUDA_BUNDLE.resolve():
        raise ValueError("CUDA Provider output must be its canonical bundle directory")
    output.mkdir(parents=True, exist_ok=True)
    site = load_private_site_config(args.site_config, repository=REPO_ROOT)
    assert_repository_site_anonymous(REPO_ROOT, site=site)
    work_root = Path(args.slurm_work_root).resolve(strict=True)
    if work_root.is_symlink() or not work_root.is_dir():
        raise ProviderProtocolError("CUDA SLURM work root is unsafe")
    tests = _tests(args.test_python)
    devices = _inventory(site)
    remote_tools = _remote_tool_identity(site)
    source = _pin(SOURCE, "cuda-self-test-source", "text/x-cuda")
    worker = _pin(WORKER, "cuda-self-test-worker", "text/x-python")
    probe = _pin(INVENTORY_PROBE, "nvidia-smi-inventory-probe", "text/x-python")
    worker_python = _pin(
        Path(args.worker_python), "cuda-self-test-python", "application/x-executable"
    )
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
            worker_python.path,
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
            "sm_70",
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
            path="/usr/local/cuda-12.9/bin:/usr/local/bin:/usr/bin:/bin"
        ),
        accelerator_allocation=allocation,
        inputs=(source, worker, probe, worker_python),
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
        metadata={"profile": "exclusive-node-sm70", "gpu_gres": False},
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
    public_result = _public_result(raw_result)
    device = devices[0]
    site_digest = sha256_digest(site)
    inventory_identity_digest = sha256_digest(
        {"site_nonce": site["site_nonce"], "devices": [item.model_dump(mode="json") for item in devices]}
    )
    runtime_target = {
        **public_site_identity(site, digest=site_digest),
        "inventory_identity_digest": inventory_identity_digest,
        "accelerator_count": len(devices),
        "accelerator_model": device.name,
        "memory_bytes_per_device": device.memory_mb * 1024 * 1024,
        "compute_capability": device.compute_capability,
        "driver_version": device.driver_version,
        "cuda_compiler_version": remote_tools["cuda_compiler_version"],
    }
    input_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["request_id"],
        "properties": {"request_id": {"type": "string", "minLength": 1}},
    }
    output_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["verdict", "device_count", "maximum_absolute_error"],
        "properties": {
            "verdict": {"const": "pass"},
            "device_count": {"type": "integer", "minimum": 1},
            "maximum_absolute_error": {"type": "number", "maximum": 1e-6},
        },
    }
    source_base_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    artifact = {
        "source_repository": "https://github.com/kotama7/ARI.git",
        "source_base_commit": source_base_commit,
        "source_overlay_digest": sha256_digest(
            {item.logical_name: item.digest for item in (source, worker, probe)}
        ),
        "source_digest": source.digest,
        "worker_digest": worker.digest,
        "inventory_probe_digest": probe.digest,
        "worker_python_digest": worker_python.digest,
        "remote_nvcc_digest": remote_tools["nvcc_digest"],
        "remote_nvidia_smi_digest": remote_tools["nvidia_smi_digest"],
        "job_contract_digest": file_digest(HPC_CONTRACT),
        "scheduler_digest": file_digest(HPC_SCHEDULER),
    }
    # The ontology's own digest, not a synthetic one. This used to hash
    # {capability_ref, semantic} locally, which produced a value that was never
    # ARI's contract digest and could therefore never match it -- so the lock
    # could not go stale when the contract moved, because it had never been
    # bound to the contract at all. The sibling ToolUniverse promotion has read
    # the ontology and verified against it all along; this one simply did not.
    contract = capability_contract(CUDA_CAPABILITY_REF)
    scope = {
        "capability_ref": CUDA_CAPABILITY_REF,
        "capability_contract_digest": contract.contract_digest,
        "tool_names": ["ari_cuda_validate__exclusive_node_sm70"],
        "input_schema_digest": sha256_digest(input_schema),
        "output_schema_digest": sha256_digest(output_schema),
        "side_effects": "scheduler-submit",
        "permissions": ["scheduler-submit", "workspace-read", "workspace-write"],
        "credential_scope_ids": [],
        # From the contract, not restated here. The hand-written list still
        # named `exclusive-node` and `slurm` after both were retired, and
        # nothing compared the two -- the same way this scope's contract digest
        # was built locally and could never match.
        "environment_requirements": capability_environment_requirements(
            CUDA_CAPABILITY_REF
        ),
        "resource_type": "gpu-slurm",
        "determinism": "conditional",
        "context_requirement": "run",
    }
    public_provenance = [
        {
            "logical_name": item.logical_name,
            "digest": item.digest,
            "size_bytes": item.size_bytes,
        }
        for item in result.provenance
        if item.logical_name != "observed-accelerator-inventory"
    ]
    observations = {
        "cuda_self_test": public_result,
        "remote_tool_identity": remote_tools,
        "execution": {
            "request_digest": result.request_digest,
            "result_digest": result.result_digest,
            "terminal_state": result.status.state,
            "terminal_reason": result.status.reason,
            "output_digests": {
                item.logical_name: item.digest for item in result.outputs
            },
            "provenance": public_provenance,
            "inventory_identity_digest": inventory_identity_digest,
            "site_identity_digest": site_digest,
        },
    }
    bundled = _bundle(
        output=output,
        actor=args.authorized_by,
        captured_date=args.captured_date,
        artifact=artifact,
        scope=scope,
        runtime_target=runtime_target,
        observations=observations,
        tests=tests,
    )
    _write_json(
        output / "workspace/materialized-private-allocation-v1.json",
        {
            "schema_version": "ari.cuda-private-allocation/v1",
            "site": site,
            "devices": [item.model_dump(mode="json") for item in devices],
            "request": request.model_dump(mode="json"),
            "result": result.model_dump(mode="json"),
        },
    )
    publishable = tuple(output.glob("*.json"))
    assert_no_private_site_identity(publishable, site=site)
    assert_repository_site_anonymous(REPO_ROOT, site=site)
    return bundled


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-config", required=True)
    parser.add_argument("--slurm-work-root", required=True)
    parser.add_argument("--worker-python", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--authorized-by", required=True)
    parser.add_argument("--captured-date", required=True)
    parser.add_argument("--test-python", default=sys.executable)
    args = parser.parse_args(argv)
    try:
        result = asyncio.run(_run(args))
    except Exception as exc:
        print(json.dumps({"ok": False, "error_type": type(exc).__name__}))
        return 1
    print(json.dumps({"ok": True, **result}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
