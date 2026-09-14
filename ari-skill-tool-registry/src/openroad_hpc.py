"""Typed C06 scheduler/container state machine for locked OpenROAD profiles."""

from __future__ import annotations

import asyncio
import os
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ari.public.result import ResultArtifactV1
from ari_skill_hpc import (
    ArtifactPinV1,
    ContainerRequestV1,
    EnvironmentPolicyV1,
    JobHandleV1,
    JobRequestV1,
    JobResultV1,
    JobStatusV1,
    LocalCommandRunner,
    ResourceRequestV1,
    SlurmScheduler,
    SubmissionLedger,
)

from models import sanitize_text, sha256_digest
from openroad_hpc_workspace import (
    OpenRoadHpcWorkspace,
    _digest_file,
    verify_openroad_hpc_files,
    workspace_runtime_digest,
)
from providers import ProviderProtocolError


_TERMINAL_STATES = frozenset({"succeeded", "failed", "cancelled"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def hpc_runtime_digest() -> str:
    return sha256_digest(
        {
            "runtime_source": _digest_file(Path(__file__).resolve()),
            "workspace_runtime": workspace_runtime_digest(),
            "hpc_job_contract": sha256_digest(JobRequestV1.model_json_schema()),
        }
    )


class OpenRoadSchedulerProtocol(Protocol):
    async def submit(self, request: JobRequestV1) -> JobHandleV1: ...

    async def status(self, handle_or_job_id: str) -> JobStatusV1: ...

    async def result(self, handle_or_job_id: str) -> JobResultV1: ...

    async def cancel(self, handle_or_job_id: str) -> dict[str, Any]: ...


class OpenRoadPortableRuntimeV1(BaseModel):
    """Digest-pinned SIF extraction and PRoot execution on a containerless node.

    This is not represented as a native container allocation.  The scheduler
    verifies the SIF, extractor, and PRoot bytes before launch; the fixed batch
    worker extracts that exact SIF into its private workspace and exposes only
    that workspace to the guest root.  Network namespaces are unavailable on
    the observed no-GRES node, so the policy records the residual host-network
    visibility instead of claiming `network: none`.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["ari.openroad-portable-runtime/v1"] = (
        "ari.openroad-portable-runtime/v1"
    )
    kind: Literal["proot-sif"] = "proot-sif"
    proot: ArtifactPinV1
    image: ArtifactPinV1
    unsquashfs: ArtifactPinV1
    squashfs_offset: int = Field(ge=0, le=2**63 - 1)
    network_policy: Literal["host-uncredentialed"] = "host-uncredentialed"

    @model_validator(mode="after")
    def _closed_identity(self) -> "OpenRoadPortableRuntimeV1":
        names = {self.proot.logical_name, self.image.logical_name, self.unsquashfs.logical_name}
        paths = {self.proot.path, self.image.path, self.unsquashfs.path}
        if len(names) != 3 or len(paths) != 3:
            raise ValueError("portable runtime artifacts must be distinct")
        if self.proot.logical_name != "openroad-proot-runtime":
            raise ValueError("portable runtime requires the fixed PRoot logical name")
        if self.image.logical_name != "openroad-sif-image":
            raise ValueError("portable runtime requires the fixed SIF logical name")
        if self.unsquashfs.logical_name != "openroad-unsquashfs-runtime":
            raise ValueError(
                "portable runtime requires the fixed unsquashfs logical name"
            )
        return self


class OpenRoadExecutionV1(BaseModel):
    """Closed local-MCP or scheduler/container execution policy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    backend: Literal["local-mcp", "slurm"] = "local-mcp"
    site_identity_digest: str | None = Field(
        default=None, pattern=r"^sha256:[0-9a-f]{64}$"
    )
    work_root: str | None = None
    resources: ResourceRequestV1 | None = None
    environment: EnvironmentPolicyV1 = Field(default_factory=EnvironmentPolicyV1)
    container: ContainerRequestV1 | None = None
    portable_runtime: OpenRoadPortableRuntimeV1 | None = None
    worker_python: str = "/usr/bin/python3"
    worker_python_pin: ArtifactPinV1 | None = None
    terminal_evidence_policy: Literal[
        "scheduler-accounting", "fixed-wrapper-marker"
    ] = "scheduler-accounting"

    @field_validator("work_root")
    @classmethod
    def _work_root(cls, value: str | None) -> str | None:
        if value is None:
            return None
        path = Path(value)
        if (
            not path.is_absolute()
            or ".." in path.parts
            or any(character.isspace() for character in value)
            or any(character in value for character in "\x00\n\r")
        ):
            raise ValueError("OpenROAD work_root must be an inert absolute path")
        return str(path)

    @field_validator("worker_python")
    @classmethod
    def _worker_python(cls, value: str) -> str:
        path = Path(value)
        if (
            not path.is_absolute()
            or ".." in path.parts
            or any(character.isspace() for character in value)
            or any(character in value for character in "\x00\n\r")
        ):
            raise ValueError("OpenROAD worker_python must be an inert absolute path")
        return str(path)

    @model_validator(mode="after")
    def _closed_backend(self) -> "OpenRoadExecutionV1":
        if self.backend == "local-mcp":
            if self.site_identity_digest is not None:
                raise ValueError("local-mcp execution cannot declare a site identity")
            if self.work_root is not None or self.resources is not None:
                raise ValueError(
                    "local-mcp execution cannot declare scheduler work or resources"
                )
            if self.container is not None or self.portable_runtime is not None:
                raise ValueError(
                    "local-mcp execution cannot declare a scheduler substrate"
                )
            if self.environment != EnvironmentPolicyV1():
                raise ValueError(
                    "local-mcp execution cannot declare a scheduler environment"
                )
            if self.worker_python != "/usr/bin/python3" or self.worker_python_pin is not None:
                raise ValueError(
                    "local-mcp execution cannot declare a batch worker interpreter"
                )
            if self.terminal_evidence_policy != "scheduler-accounting":
                raise ValueError(
                    "local-mcp execution cannot declare scheduler terminal evidence"
                )
            return self
        if (
            self.site_identity_digest is None
            or self.work_root is None
            or self.resources is None
        ):
            raise ValueError(
                "slurm execution requires site identity, work_root, and resources"
            )
        if (self.container is None) == (self.portable_runtime is None):
            raise ValueError(
                "slurm execution requires exactly one pinned execution substrate"
            )
        if self.resources.nodes != 1 or self.resources.tasks != 1:
            raise ValueError(
                "OpenROAD batch profiles currently require one node and one task"
            )
        if self.resources.tasks_per_node not in {None, 1}:
            raise ValueError("OpenROAD batch tasks_per_node must be omitted or one")
        if self.resources.gpus_per_node or self.resources.gpus_per_task:
            raise ValueError("OpenROAD batch profiles do not declare GPU resources")
        if self.container is not None:
            if self.worker_python_pin is not None:
                raise ValueError(
                    "container execution cannot pin a host worker interpreter"
                )
            if not self.container.contain_all or not self.container.clean_environment:
                raise ValueError(
                    "OpenROAD batch containers require contain_all and clean_environment"
                )
            if self.container.gpu:
                raise ValueError(
                    "OpenROAD batch containers must not enable GPU passthrough"
                )
            if self.container.network != "none":
                raise ValueError("OpenROAD batch containers require network isolation")
        else:
            if self.worker_python_pin is None:
                raise ValueError(
                    "portable execution requires a pinned worker interpreter"
                )
            if (
                self.worker_python_pin.logical_name != "openroad-worker-python"
                or self.worker_python_pin.path != self.worker_python
            ):
                raise ValueError(
                    "portable worker interpreter path and pin must be identical"
                )
        return self


class OpenRoadHpcRuntime:
    """Prepare, submit, normalize, cancel, and clean one locked batch run."""

    def __init__(
        self,
        *,
        artifact_store: Any | None,
        scheduler: OpenRoadSchedulerProtocol | None,
        control_timeout_seconds: float,
    ) -> None:
        self.workspace = OpenRoadHpcWorkspace(artifact_store)
        self.scheduler = scheduler
        self.control_timeout_seconds = control_timeout_seconds
        self._schedulers: dict[str, OpenRoadSchedulerProtocol] = {}

    def _scheduler_for(self, profile: Any) -> OpenRoadSchedulerProtocol:
        if self.scheduler is not None:
            return self.scheduler
        execution = profile.execution
        if execution.backend != "slurm" or execution.work_root is None:
            raise ProviderProtocolError("OpenROAD profile has no scheduler execution")
        cached = self._schedulers.get(execution.work_root)
        if cached is not None:
            return cached
        scheduler_path = os.environ.get(
            "ARI_SCHEDULER_PATH", "/usr/local/bin:/usr/bin:/bin"
        )
        EnvironmentPolicyV1(path=scheduler_path)
        ledger_value = os.environ.get("ARI_HPC_LEDGER_PATH", "").strip()
        ledger_path = (
            Path(ledger_value)
            if ledger_value
            else Path(execution.work_root)
            / ".ari-openroad"
            / "hpc-jobs-v1.json"
        )
        scheduler = SlurmScheduler(
            runner=LocalCommandRunner(scheduler_path=scheduler_path),
            ledger=SubmissionLedger(ledger_path),
            shared_filesystem=True,
            terminal_evidence_policy=execution.terminal_evidence_policy,
        )
        self._schedulers[execution.work_root] = scheduler
        return scheduler

    async def _wait_terminal(
        self, job: Any, transcript: list[dict[str, Any]]
    ) -> JobStatusV1:
        assert job.scheduler is not None
        assert job.scheduler_handle is not None
        profile = job.experiment
        deadline = asyncio.get_running_loop().time() + profile.command_timeout_seconds
        while True:
            status = await job.scheduler.status(job.scheduler_handle.handle_id)
            job.stage = f"scheduler-{status.state}"
            if status.state in _TERMINAL_STATES:
                job.scheduler_terminal = True
                return status
            if asyncio.get_running_loop().time() >= deadline:
                await job.scheduler.cancel(job.scheduler_handle.handle_id)
                transcript.append(
                    {
                        "stage": "scheduler",
                        "operation": "cancel-on-timeout",
                        "job_id": job.scheduler_handle.job_id,
                    }
                )
                cancel_deadline = asyncio.get_running_loop().time() + min(
                    30.0, self.control_timeout_seconds
                )
                while asyncio.get_running_loop().time() < cancel_deadline:
                    status = await job.scheduler.status(job.scheduler_handle.handle_id)
                    if status.state in _TERMINAL_STATES:
                        job.scheduler_terminal = True
                        break
                    await asyncio.sleep(0.25)
                raise ProviderProtocolError(
                    "OpenROAD scheduler job exceeded command_timeout_seconds"
                )
            await asyncio.sleep(profile.poll_interval_seconds)

    async def _terminal_artifacts(
        self, job: Any, transcript: list[dict[str, Any]]
    ) -> tuple[JobResultV1, list[ResultArtifactV1]]:
        assert job.scheduler is not None
        assert job.scheduler_handle is not None
        result = await job.scheduler.result(job.scheduler_handle.handle_id)
        hpc_artifacts, refs = self.workspace.store_hpc_artifacts(result)
        transcript.append(
            {
                "stage": "scheduler",
                "operation": "result",
                "status": result.status.model_dump(mode="json"),
                "request_digest": result.request_digest,
                "result_digest": result.result_digest,
                "environment_digest": result.environment_digest,
                "module_digest": result.module_digest,
                "module_snapshot_digest": result.module_snapshot_digest,
                "container_digest": result.container_digest,
                "artifacts": hpc_artifacts,
                "error": result.error.model_dump(mode="json")
                if result.error is not None
                else None,
            }
        )
        return result, refs

    async def _complete(
        self,
        results: Any,
        job: Any,
        status: JobStatusV1,
        result: JobResultV1,
        internal_paths: frozenset[str],
        transcript: list[dict[str, Any]],
        artifact_refs: list[ResultArtifactV1],
    ) -> None:
        profile = job.experiment
        if result.error is not None or status.state != "succeeded":
            message = (
                result.error.message
                if result.error is not None
                else f"scheduler ended in {status.scheduler_state}"
            )
            raise ProviderProtocolError(f"OpenROAD scheduler execution failed: {message}")
        assert job.batch_workspace is not None
        worker_result = self.workspace.batch_result(
            job.batch_workspace / "ari-openroad-batch-result.json", profile
        )
        transcript.append(
            {"stage": "scheduler", "operation": "batch-worker", **worker_result}
        )
        job.stage = "collecting"
        artifact_manifest, output_refs, artifact_digests = results.capture_artifacts(
            profile, job.batch_workspace, internal_paths=internal_paths
        )
        artifact_refs.extend(output_refs)
        metrics = results.normalize_metrics(
            profile, job.batch_workspace, artifact_digests
        )
        transcript_meta, transcript_ref = results.store_transcript(job, transcript)
        if transcript_ref is not None:
            artifact_refs.append(transcript_ref)
        handle = job.scheduler_handle
        assert handle is not None
        structured = {
            "schema_version": "ari.openroad-result/v1",
            "handle_id": job.handle_id,
            "status": "completed",
            "experiment_digest": profile.experiment_digest,
            "method_digest": profile.method_digest,
            "request_id": job.request_id,
            "toolchain": profile.toolchain.model_dump(mode="json"),
            "technology": profile.technology.model_dump(mode="json"),
            "execution": profile.execution.model_dump(mode="json"),
            "workspace_input_digest": profile.workspace.input_digest,
            "metrics": metrics,
            "artifact_manifest": artifact_manifest,
            "session_transcript": transcript_meta,
            "hpc_job": {
                "handle": handle.model_dump(mode="json"),
                "status": result.status.model_dump(mode="json"),
                "request_digest": result.request_digest,
                "result_digest": result.result_digest,
                "environment_digest": result.environment_digest,
                "module_digest": result.module_digest,
                "module_snapshot_digest": result.module_snapshot_digest,
                "container_digest": result.container_digest,
            },
            "_ari_result_artifacts": [
                item.model_dump(mode="json") for item in artifact_refs
            ],
            "session_recovery": (
                "durable C06 scheduler handle; restart requires locked catalog "
                "and ledger reconciliation"
            ),
        }
        job.status = "completed"
        job.stage = "completed"
        job.completed_at = _now()
        job.response = results.terminal_response(structured)

    async def _cancelled(
        self,
        results: Any,
        job: Any,
        transcript: list[dict[str, Any]],
        artifact_refs: list[ResultArtifactV1],
    ) -> None:
        job.status = "cancelled"
        job.stage = "cancelled"
        job.completed_at = _now()
        transcript.append(
            {
                "stage": "scheduler",
                "operation": "cancelled",
                "scheduler_terminal": job.scheduler_terminal,
            }
        )
        if job.scheduler_terminal and job.scheduler is not None and job.scheduler_handle:
            with suppress(Exception):
                result, captured = await self._terminal_artifacts(job, transcript)
                artifact_refs.extend(captured)
                transcript[-1]["cancel_result_digest"] = result.result_digest
        transcript_meta, transcript_ref = results.store_transcript_after_failure(
            job, transcript
        )
        if transcript_ref is not None:
            artifact_refs.append(transcript_ref)
        structured: dict[str, Any] = {
            "handle_id": job.handle_id,
            "status": "cancelled",
            "session_transcript": transcript_meta,
            "cleanup_deferred": not job.scheduler_terminal,
        }
        if job.scheduler_handle is not None:
            structured["hpc_handle"] = job.scheduler_handle.model_dump(mode="json")
        if artifact_refs:
            structured["_ari_result_artifacts"] = [
                item.model_dump(mode="json") for item in artifact_refs
            ]
        job.response = results.terminal_response(structured)

    def _failed(
        self,
        results: Any,
        job: Any,
        exc: Exception,
        transcript: list[dict[str, Any]],
        artifact_refs: list[ResultArtifactV1],
    ) -> None:
        job.status = "failed"
        job.stage = "failed"
        job.completed_at = _now()
        job.error = sanitize_text(f"{type(exc).__name__}: {exc}", limit=2_000)
        transcript.append(
            {
                "stage": "scheduler",
                "operation": "failed",
                "error": job.error,
                "scheduler_terminal": job.scheduler_terminal,
            }
        )
        transcript_meta, transcript_ref = results.store_transcript_after_failure(
            job, transcript
        )
        if transcript_ref is not None:
            artifact_refs.append(transcript_ref)
        structured: dict[str, Any] = {
            "handle_id": job.handle_id,
            "status": "failed",
            "error": job.error,
            "session_transcript": transcript_meta,
            "cleanup_deferred": (
                job.scheduler_handle is not None and not job.scheduler_terminal
            ),
        }
        if job.scheduler_handle is not None:
            structured["hpc_handle"] = job.scheduler_handle.model_dump(mode="json")
        if artifact_refs:
            structured["_ari_result_artifacts"] = [
                item.model_dump(mode="json") for item in artifact_refs
            ]
        job.response = results.terminal_response(structured)

    async def run_job(
        self,
        results: Any,
        job: Any,
        verify_profile: Callable[[Any], None],
    ) -> None:
        profile = job.experiment
        job.status = "running"
        job.stage = "preparing-scheduler-job"
        job.started_at = _now()
        transcript: list[dict[str, Any]] = []
        artifact_refs: list[ResultArtifactV1] = []
        try:
            verify_profile(profile)
            request, internal_paths = self.workspace.prepare_request(results, job)
            job.scheduler = self._scheduler_for(profile)
            job.scheduler_submission_started = True
            job.scheduler_handle = await job.scheduler.submit(request)
            job.stage = "scheduler-submitted"
            transcript.append(
                {
                    "stage": "scheduler",
                    "operation": "submit",
                    "handle": job.scheduler_handle.model_dump(mode="json"),
                    "resources": profile.execution.resources.model_dump(mode="json"),
                    "container_digest": profile.toolchain.execution_image_digest,
                }
            )
            status = await self._wait_terminal(job, transcript)
            result, captured = await self._terminal_artifacts(job, transcript)
            artifact_refs.extend(captured)
            await self._complete(
                results,
                job,
                status,
                result,
                internal_paths,
                transcript,
                artifact_refs,
            )
        except asyncio.CancelledError:
            await self._cancelled(results, job, transcript, artifact_refs)
        except Exception as exc:
            self._failed(results, job, exc, transcript, artifact_refs)
        finally:
            if not job.scheduler_submission_started or job.scheduler_terminal:
                with suppress(Exception):
                    self.workspace.cleanup_workspace(job)

    async def request_cancel(self, job: Any) -> None:
        if job.scheduler is None or job.scheduler_handle is None:
            return
        await job.scheduler.cancel(job.scheduler_handle.handle_id)
        deadline = asyncio.get_running_loop().time() + min(
            30.0, self.control_timeout_seconds
        )
        while asyncio.get_running_loop().time() < deadline:
            status = await job.scheduler.status(job.scheduler_handle.handle_id)
            if status.state in _TERMINAL_STATES:
                job.scheduler_terminal = True
                return
            await asyncio.sleep(0.25)


__all__ = [
    "OpenRoadExecutionV1",
    "OpenRoadHpcRuntime",
    "OpenRoadPortableRuntimeV1",
    "OpenRoadSchedulerProtocol",
    "hpc_runtime_digest",
    "verify_openroad_hpc_files",
]
