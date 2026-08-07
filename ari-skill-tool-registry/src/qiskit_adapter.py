"""Immutable Qiskit MCP/Aer experiment adapter with typed async lifecycle."""

from __future__ import annotations

import asyncio
import json
import os
import re
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from ari.public.result import ResultArtifactV1

from models import sha256_digest
from providers import (
    ProviderAdapter,
    ProviderProtocolError,
    ProviderResponseV1,
    ProviderToolV1,
    PythonStdioLauncherV1,
    StdioMCPAdapter,
    stdio_adapter_digest,
)
from qiskit_contracts import (
    QISKIT_EXPERIMENT_V1,
    QiskitCircuitV1,
    QiskitExperimentV1,
    QiskitLocalBackendV1,
    QiskitMitigationV1,
    QiskitNoiseModelV1,
    QiskitOutcomeExpectationV1,
    QiskitRemoteBackendV1,
    QiskitSoftwareV1,
    QiskitTargetV1,
    QiskitTranspilationV1,
)
from qiskit_core import QiskitCoreRuntime, qiskit_core_runtime_digest
from qiskit_identity import (
    QiskitProviderPinV1,
    _file_sha256,
    qiskit_effective_launcher,
    qiskit_identity_digest,
    qiskit_provider_release_pin,
    qiskit_software_stack_digest,
    verify_qiskit_provider_package,
)
from qiskit_local import QiskitLocalRuntime, qiskit_local_runtime_digest
from qiskit_remote import QiskitRemoteRuntime, qiskit_remote_runtime_digest
from qiskit_results import QiskitResultStore, qiskit_results_digest
from qiskit_verification import (
    qiskit_contracts_digest,
    verify_qiskit_experiment_files,
)
from storage import RegistryArtifactStore


QISKIT_ADAPTER_ID = "ari.qiskit-profile"
QISKIT_ADAPTER_VERSION = "1.0.0"
_REQUEST_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_CORE_TOOLS = frozenset(
    {
        "analyze_circuit_tool",
        "compare_optimization_levels_tool",
        "convert_qasm3_to_qpy_tool",
        "convert_qpy_to_qasm3_tool",
        "export_circuit_to_qasm_tool",
        "load_circuit_from_qasm_tool",
        "transpile_circuit_tool",
    }
)
_RUNTIME_TOOLS = frozenset(
    {
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
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def qiskit_adapter_digest() -> str:
    return sha256_digest(
        {
            "adapter_source": _file_sha256(Path(__file__).resolve()),
            "contracts": qiskit_contracts_digest(),
            "identity": qiskit_identity_digest(),
            "stdio_adapter": stdio_adapter_digest(),
            "core_runtime": qiskit_core_runtime_digest(),
            "local_runtime": qiskit_local_runtime_digest(),
            "remote_runtime": qiskit_remote_runtime_digest(),
            "results": qiskit_results_digest(),
        }
    )


@dataclass
class _QiskitJob:
    handle_id: str
    experiment: QiskitExperimentV1
    request_id: str
    status: Literal["submitted", "running", "completed", "failed", "cancelled"] = (
        "submitted"
    )
    stage: str = "submitted"
    submitted_at: str = field(default_factory=_now)
    started_at: str | None = None
    completed_at: str | None = None
    task: asyncio.Task[None] | None = None
    response: ProviderResponseV1 | None = None
    error: str = ""
    local_process: asyncio.subprocess.Process | None = None
    local_workspace: Path | None = None
    remote_job_id: str | None = None
    remote_state: str | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    artifact_refs: list[ResultArtifactV1] = field(default_factory=list)
    backend_snapshot: dict[str, Any] | None = None
    backend_snapshot_digest: str | None = None
    transpiled_qpy_digest: str | None = None
    transpile_metadata: dict[str, Any] | None = None
    cancel_requested: bool = False
    remote_deadline_monotonic: float | None = None


class QiskitExperimentAdapter:
    """Expose one virtual leaf per reviewed Qiskit experiment profile."""

    def __init__(
        self,
        core_launcher: PythonStdioLauncherV1,
        *,
        core_provider_digest: str,
        core_pin: QiskitProviderPinV1,
        experiments: list[QiskitExperimentV1],
        runtime_launcher: PythonStdioLauncherV1 | None = None,
        runtime_provider_digest: str | None = None,
        runtime_pin: QiskitProviderPinV1 | None = None,
        artifact_store: RegistryArtifactStore | None = None,
        allowed_leaf_names: set[str] | None = None,
        timeout_seconds: float = 60,
        max_concurrent_jobs: int = 4,
        max_retained_jobs: int = 1_024,
        core_transport: ProviderAdapter | None = None,
        runtime_transport: ProviderAdapter | None = None,
        verify_packages: bool = True,
        verify_contract: bool = True,
    ) -> None:
        core_pin.verify()
        if verify_packages:
            verify_qiskit_provider_package(core_launcher, core_pin)
        remote_required = any(
            isinstance(item.backend, QiskitRemoteBackendV1) for item in experiments
        )
        if remote_required and (
            runtime_launcher is None
            or runtime_provider_digest is None
            or runtime_pin is None
        ):
            raise ValueError("remote Qiskit profiles require the Runtime MCP provider")
        if runtime_pin is not None:
            runtime_pin.verify()
            if verify_packages:
                assert runtime_launcher is not None
                verify_qiskit_provider_package(runtime_launcher, runtime_pin)
        profile_ids = [item.profile_id for item in experiments]
        if len(profile_ids) != len(set(profile_ids)):
            raise ValueError("Qiskit experiment profile_id values must be unique")
        if not 1 <= max_concurrent_jobs <= 32:
            raise ValueError("Qiskit max_concurrent_jobs must be between 1 and 32")
        if not 32 <= max_retained_jobs <= 100_000:
            raise ValueError("Qiskit max_retained_jobs must be between 32 and 100000")
        self.core_pin = core_pin
        self.runtime_pin = runtime_pin
        self.core_provider_digest = core_provider_digest
        self.runtime_provider_digest = runtime_provider_digest
        self.experiments = {item.profile_id: item for item in experiments}
        self.allowed_leaf_names = (
            frozenset(allowed_leaf_names) if allowed_leaf_names is not None else None
        )
        self.max_retained_jobs = max_retained_jobs
        self.verify_contract = verify_contract
        self._job_slots = asyncio.Semaphore(max_concurrent_jobs)
        self.results = QiskitResultStore(artifact_store)
        self.core_transport = core_transport or StdioMCPAdapter(
            qiskit_effective_launcher(core_launcher, "circuit"),
            expected_provider_digest=core_provider_digest,
            timeout_seconds=timeout_seconds,
            max_pages=8,
            max_tools=32,
        )
        self.core = QiskitCoreRuntime(self.core_transport)
        self.local = QiskitLocalRuntime(
            core=self.core,
            results=self.results,
            worker_python=core_launcher.python_executable,
        )
        self.runtime_transport = runtime_transport
        self.remote: QiskitRemoteRuntime | None = None
        if runtime_launcher is not None and runtime_provider_digest is not None:
            runtime_token = os.environ.get("QISKIT_IBM_TOKEN")
            self.runtime_transport = runtime_transport or StdioMCPAdapter(
                qiskit_effective_launcher(runtime_launcher, "runtime"),
                expected_provider_digest=runtime_provider_digest,
                credential_env_values=(
                    {"QISKIT_IBM_TOKEN": runtime_token} if runtime_token else {}
                ),
                timeout_seconds=timeout_seconds,
                max_pages=8,
                max_tools=64,
            )
            self.remote = QiskitRemoteRuntime(
                core=self.core,
                transport=self.runtime_transport,
                results=self.results,
            )
        self._jobs: dict[str, _QiskitJob] = {}

    @staticmethod
    def leaf_name(profile_id: str) -> str:
        return qiskit_leaf_name(profile_id)

    def _virtual_tools(self) -> list[ProviderToolV1]:
        tools: list[ProviderToolV1] = []
        for profile in sorted(
            self.experiments.values(), key=lambda item: item.profile_id
        ):
            if (
                self.allowed_leaf_names is not None
                and self.leaf_name(profile.profile_id) not in self.allowed_leaf_names
            ):
                continue
            tools.append(qiskit_virtual_tool(profile))
        return tools

    async def list_tools(self) -> list[ProviderToolV1]:
        if self.verify_contract:
            core_names = {item.name for item in await self.core_transport.list_tools()}
            if core_names != _CORE_TOOLS:
                raise ProviderProtocolError("Qiskit core MCP tool surface drifted")
            if self.remote is not None:
                assert self.runtime_transport is not None
                runtime_names = {
                    item.name for item in await self.runtime_transport.list_tools()
                }
                if runtime_names != _RUNTIME_TOOLS:
                    raise ProviderProtocolError(
                        "Qiskit Runtime MCP tool surface drifted"
                    )
        return self._virtual_tools()

    def _profile(self, name: str) -> QiskitExperimentV1:
        if self.allowed_leaf_names is None or name not in self.allowed_leaf_names:
            raise ProviderProtocolError(
                "Qiskit runtime accepts only a leaf from the active catalog lock"
            )
        matches = [
            item
            for item in self.experiments.values()
            if self.leaf_name(item.profile_id) == name
        ]
        if len(matches) != 1:
            raise ProviderProtocolError("Qiskit locked leaf has no unique profile")
        return matches[0]

    async def invoke(self, name: str, arguments: dict[str, Any]) -> ProviderResponseV1:
        profile = self._profile(name)
        if set(arguments) != {"request_id"} or not isinstance(
            arguments.get("request_id"), str
        ):
            raise ProviderProtocolError("Qiskit profiles accept only a request_id")
        request_id = arguments["request_id"]
        if not _REQUEST_ID_RE.fullmatch(request_id):
            raise ProviderProtocolError("Qiskit request_id is invalid")
        handle_id = "qiskit-" + sha256_digest(
            {
                "adapter": QISKIT_ADAPTER_ID,
                "core_provider_digest": self.core_provider_digest,
                "runtime_provider_digest": self.runtime_provider_digest,
                "experiment_digest": profile.experiment_digest,
                "request_id": request_id,
            }
        ).removeprefix("sha256:")
        job = self._jobs.get(handle_id)
        if job is None:
            if len(self._jobs) >= self.max_retained_jobs:
                raise ProviderProtocolError("Qiskit retained-job limit reached")
            job = _QiskitJob(handle_id, profile, request_id)
            self._jobs[handle_id] = job
            job.task = asyncio.create_task(
                self._run_job(job), name=f"ari-qiskit-{profile.profile_id}"
            )
        return self._response(self._status_payload(job))

    async def _run_job(self, job: _QiskitJob) -> None:
        try:
            async with self._job_slots:
                if isinstance(job.experiment.backend, QiskitLocalBackendV1):
                    await self.local.run_job(job)
                else:
                    if self.remote is None:
                        raise ProviderProtocolError("Qiskit Runtime MCP is unavailable")
                    await self.remote.submit(job)
        except asyncio.CancelledError:
            job.status = "cancelled"
            job.stage = "cancelled"
            job.completed_at = _now()
            transcript, ref = self.results.store_transcript_after_failure(
                job, job.events
            )
            refs = [ref] if ref is not None else []
            job.response = self.results.terminal_response(
                {
                    "handle_id": job.handle_id,
                    "status": "cancelled",
                    "execution_transcript": transcript,
                    "_ari_result_artifacts": [
                        item.model_dump(mode="json") for item in refs
                    ],
                }
            )
        except Exception as exc:
            self._fail(job, exc)

    def _fail(self, job: _QiskitJob, exc: Exception) -> None:
        if self.remote is not None:
            self.remote.fail(job, exc)
            return
        job.status = "failed"
        job.stage = "failed"
        job.completed_at = _now()
        job.error = f"{type(exc).__name__}: {exc}"[:2_000]
        job.events.append({"stage": "failed", "error": job.error})
        transcript, ref = self.results.store_transcript_after_failure(job, job.events)
        refs = [ref] if ref is not None else []
        job.response = self.results.terminal_response(
            {
                "handle_id": job.handle_id,
                "status": "failed",
                "error": job.error,
                "execution_transcript": transcript,
                "_ari_result_artifacts": [
                    item.model_dump(mode="json") for item in refs
                ],
            }
        )

    @staticmethod
    def _response(value: dict[str, Any]) -> ProviderResponseV1:
        return ProviderResponseV1(
            text=json.dumps(value, ensure_ascii=False, sort_keys=True), structured=value
        )

    @staticmethod
    def _status_payload(job: _QiskitJob) -> dict[str, Any]:
        value: dict[str, Any] = {
            "handle_id": job.handle_id,
            "status": job.status,
            "stage": job.stage,
            "experiment_digest": job.experiment.experiment_digest,
            "request_id": job.request_id,
            "submitted_at": job.submitted_at,
            "started_at": job.started_at,
            "completed_at": job.completed_at,
        }
        if job.remote_job_id is not None:
            value["remote_job_id"] = job.remote_job_id
            value["remote_state"] = job.remote_state
        if job.error:
            value["error"] = job.error
        return value

    def _job(self, handle: str) -> _QiskitJob:
        job = self._jobs.get(handle)
        if job is None:
            raise ProviderProtocolError(
                "Qiskit handle is unknown; recovery fails closed"
            )
        return job

    async def get_status(self, lifecycle, provider_handle: str) -> ProviderResponseV1:
        job = self._job(provider_handle)
        if job.response is not None and job.status in {
            "completed",
            "failed",
            "cancelled",
        }:
            return job.response
        if (
            isinstance(job.experiment.backend, QiskitRemoteBackendV1)
            and job.remote_job_id is not None
            and job.status not in {"failed", "cancelled"}
        ):
            assert self.remote is not None
            try:
                await self.remote.refresh_status(job)
            except Exception as exc:
                self.remote.fail(job, exc)
        return self._response(self._status_payload(job))

    async def get_result(self, lifecycle, provider_handle: str) -> ProviderResponseV1:
        job = self._job(provider_handle)
        if job.response is not None:
            return job.response
        if isinstance(job.experiment.backend, QiskitRemoteBackendV1):
            assert self.remote is not None
            try:
                response = await self.remote.collect_result(job)
                if response is not None:
                    return response
            except Exception as exc:
                self.remote.fail(job, exc)
                assert job.response is not None
                return job.response
        return self._response(self._status_payload(job))

    async def cancel(self, lifecycle, provider_handle: str) -> ProviderResponseV1:
        job = self._job(provider_handle)
        if job.status in {"completed", "failed", "cancelled"}:
            if job.status != "cancelled":
                raise ProviderProtocolError(f"Qiskit job is already {job.status}")
            assert job.response is not None
            return job.response
        if job.remote_job_id is not None:
            assert self.remote is not None
            await self.remote.cancel(job)
        else:
            assert job.task is not None
            if isinstance(job.experiment.backend, QiskitRemoteBackendV1):
                job.cancel_requested = True
                with suppress(asyncio.CancelledError):
                    await job.task
                if job.remote_job_id is not None and job.status not in {
                    "failed",
                    "cancelled",
                }:
                    assert self.remote is not None
                    await self.remote.cancel(job)
            else:
                job.task.cancel()
                with suppress(asyncio.CancelledError):
                    await job.task
        if job.status == "failed":
            raise ProviderProtocolError(job.error or "Qiskit cancellation failed")
        assert job.response is not None
        return job.response


__all__ = [
    "QISKIT_ADAPTER_ID",
    "QISKIT_ADAPTER_VERSION",
    "QISKIT_EXPERIMENT_V1",
    "QiskitCircuitV1",
    "QiskitExperimentAdapter",
    "QiskitExperimentV1",
    "QiskitLocalBackendV1",
    "QiskitMitigationV1",
    "QiskitNoiseModelV1",
    "QiskitOutcomeExpectationV1",
    "QiskitProviderPinV1",
    "QiskitRemoteBackendV1",
    "QiskitSoftwareV1",
    "QiskitTargetV1",
    "QiskitTranspilationV1",
    "qiskit_adapter_digest",
    "qiskit_effective_launcher",
    "qiskit_leaf_name",
    "qiskit_provider_release_pin",
    "qiskit_software_stack_digest",
    "qiskit_virtual_tool",
    "verify_qiskit_experiment_files",
    "verify_qiskit_provider_package",
]
def qiskit_leaf_name(profile_id: str) -> str:
    safe = profile_id.replace("-", "_").replace(".", "_")
    return f"ari_qiskit_sample__{safe}"


def qiskit_virtual_tool(profile: QiskitExperimentV1) -> ProviderToolV1:
    """Build the sole public operation for one immutable Qiskit profile."""

    metadata = {
        "profile_id": profile.profile_id,
        "experiment_digest": profile.experiment_digest,
        "method_digest": profile.method_digest,
        "capability_ref": profile.capability_ref,
        "backend_kind": profile.backend.kind,
        "target_digest": profile.backend.target.target_digest,
        "circuit_digest": profile.circuit.qpy_digest,
        "shots": profile.shots,
        "seed_simulator": profile.seed_simulator,
    }
    return ProviderToolV1(
        name=qiskit_leaf_name(profile.profile_id),
        description=profile.description,
        input_schema={
            "type": "object",
            "properties": {
                "request_id": {
                    "type": "string",
                    "pattern": _REQUEST_ID_RE.pattern,
                }
            },
            "required": ["request_id"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "handle_id": {"type": "string"},
                "status": {"type": "string"},
                "experiment_digest": {"type": "string"},
            },
            "required": ["handle_id", "status", "experiment_digest"],
            "additionalProperties": True,
        },
        annotations={"ari_qiskit": metadata},
    )
