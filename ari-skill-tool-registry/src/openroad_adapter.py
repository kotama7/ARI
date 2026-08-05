"""Pinned, restricted OpenROAD experiment adapter.

The upstream OpenROAD MCP server intentionally exposes an interactive shell.
ARI never publishes that shell.  One reviewed experiment profile becomes one
virtual asynchronous leaf whose command sequence, inputs, outputs, metrics,
toolchain, and technology are immutable catalog data.
"""

from __future__ import annotations

import asyncio
import json
import re
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from ari_skill_hpc import JobHandleV1

from models import sha256_digest
from openroad_contracts import (
    OPENROAD_EXPERIMENT_V1,
    OpenRoadArtifactPinV1,
    OpenRoadCommandV1,
    OpenRoadExecutionV1,
    OpenRoadExperimentV1,
    OpenRoadMetricV1,
    OpenRoadOutputArtifactV1,
    OpenRoadProviderPinV1,
    OpenRoadTechnologyV1,
    OpenRoadToolchainV1,
    OpenRoadWorkspaceV1,
    openroad_provider_release_pin,
    openroad_toolchain_line,
    openroad_workspace_digest,
    verify_openroad_provider_pin,
)
from openroad_hpc import (
    OpenRoadHpcRuntime,
    OpenRoadPortableRuntimeV1,
    OpenRoadSchedulerProtocol,
    hpc_runtime_digest,
)
from openroad_identity import _file_sha256
from openroad_local import OpenRoadLocalRuntime, openroad_local_runtime_digest
from openroad_results import OpenRoadResultStore, openroad_results_digest
from openroad_verification import (
    openroad_contracts_digest,
    verify_openroad_experiment_files,
    verify_openroad_provider_package,
)
from providers import (
    ProviderAdapter,
    ProviderProtocolError,
    ProviderResponseV1,
    ProviderToolV1,
    PythonStdioLauncherV1,
    StdioMCPAdapter,
    stdio_adapter_digest,
)
from storage import RegistryArtifactStore


OPENROAD_ADAPTER_ID = "ari.openroad-profile"
OPENROAD_ADAPTER_VERSION = "1.1.0"
_REQUEST_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_UPSTREAM_TOOLS = frozenset(
    {
        "create_interactive_session",
        "get_session_history",
        "get_session_metrics",
        "inspect_interactive_session",
        "interactive_openroad_exec",
        "interactive_openroad_query",
        "list_interactive_sessions",
        "list_report_images",
        "read_report_image",
        "terminate_interactive_session",
    }
)
_PROVIDER_ARGUMENTS = ("--transport", "stdio", "--log-level", "ERROR")
_PROVIDER_ENV = {
    "FASTMCP_CHECK_FOR_UPDATES": "off",
    "FASTMCP_SHOW_SERVER_BANNER": "false",
    "OPENROAD_ALLOWED_COMMANDS": "openroad",
    "OPENROAD_ENABLE_COMMAND_VALIDATION": "true",
    "OPENROAD_MAX_SESSIONS": "8",
    "OPENROAD_WHITELIST_ENABLED": "true",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def openroad_effective_launcher(
    launcher: PythonStdioLauncherV1,
) -> PythonStdioLauncherV1:
    """Apply the only admitted OpenROAD-MCP process policy."""

    return launcher.model_copy(
        update={
            "arguments": list(_PROVIDER_ARGUMENTS),
            "literal_env": dict(_PROVIDER_ENV),
        }
    )


def openroad_adapter_digest() -> str:
    return sha256_digest(
        {
            "adapter_source": _file_sha256(Path(__file__).resolve()),
            "contracts": openroad_contracts_digest(),
            "generic_stdio_adapter": stdio_adapter_digest(),
            "hpc_runtime": hpc_runtime_digest(),
            "local_runtime": openroad_local_runtime_digest(),
            "result_runtime": openroad_results_digest(),
        }
    )


def openroad_leaf_name(profile_id: str) -> str:
    return f"ari_openroad_run__{profile_id.replace('-', '_').replace('.', '_')}"


def openroad_virtual_tool(
    profile: OpenRoadExperimentV1,
    *,
    provider_version: str,
    provider_commit: str,
) -> ProviderToolV1:
    """Build the sole public operation for one immutable OpenROAD profile."""

    metadata = {
        "profile_id": profile.profile_id,
        "experiment_digest": profile.experiment_digest,
        "method_digest": profile.method_digest,
        "provider_release": provider_version,
        "provider_commit": provider_commit,
        "toolchain": profile.toolchain.model_dump(mode="json"),
        "technology": profile.technology.model_dump(mode="json"),
        "execution": profile.execution.model_dump(mode="json"),
        "workspace_input_digest": profile.workspace.input_digest,
        "metrics": [
            {
                "metric_id": metric.metric_id,
                "unit": metric.unit,
                "corner": metric.corner,
                "mode": metric.mode,
                "stage": metric.stage,
                "source_artifact": metric.source_artifact,
            }
            for metric in profile.metrics
        ],
    }
    return ProviderToolV1(
        name=openroad_leaf_name(profile.profile_id),
        description=profile.description,
        input_schema={
            "type": "object",
            "properties": {
                "request_id": {
                    "type": "string",
                    "pattern": _REQUEST_ID_RE.pattern,
                    "description": "Idempotency key for this immutable experiment",
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
        annotations={"ari_openroad": metadata},
    )

@dataclass
class _OpenRoadJob:
    handle_id: str
    experiment: OpenRoadExperimentV1
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
    scheduler: OpenRoadSchedulerProtocol | None = None
    scheduler_submission_started: bool = False
    scheduler_handle: JobHandleV1 | None = None
    scheduler_terminal: bool = False
    batch_workspace: Path | None = None


class OpenRoadExperimentAdapter:
    """Run only catalog-locked OpenROAD profiles through upstream MCP."""

    def __init__(
        self,
        launcher: PythonStdioLauncherV1,
        *,
        expected_provider_digest: str,
        pin: dict[str, Any],
        experiments: list[OpenRoadExperimentV1],
        artifact_store: RegistryArtifactStore | None = None,
        allowed_leaf_names: set[str] | None = None,
        timeout_seconds: float = 30.0,
        max_concurrent_jobs: int = 4,
        max_retained_jobs: int = 1_024,
        transport: ProviderAdapter | None = None,
        scheduler: OpenRoadSchedulerProtocol | None = None,
        verify_package: bool = True,
        verify_contract: bool = True,
    ) -> None:
        verify_openroad_provider_pin(pin)
        if verify_package:
            verify_openroad_provider_package(launcher, pin)
        profile_ids = [item.profile_id for item in experiments]
        if len(profile_ids) != len(set(profile_ids)):
            raise ValueError("OpenROAD experiment profile_id values must be unique")
        if not 1 <= max_concurrent_jobs <= 32:
            raise ValueError("OpenROAD max_concurrent_jobs must be between 1 and 32")
        if not 32 <= max_retained_jobs <= 100_000:
            raise ValueError("OpenROAD max_retained_jobs must be between 32 and 100000")
        self.launcher = launcher
        self.expected_provider_digest = expected_provider_digest
        self.pin = dict(pin)
        self.experiments = {item.profile_id: item for item in experiments}
        self.results = OpenRoadResultStore(artifact_store)
        self.allowed_leaf_names = (
            frozenset(allowed_leaf_names) if allowed_leaf_names is not None else None
        )
        self.timeout_seconds = timeout_seconds
        self.max_concurrent_jobs = max_concurrent_jobs
        self.max_retained_jobs = max_retained_jobs
        self._job_slots = asyncio.Semaphore(max_concurrent_jobs)
        self.verify_contract = verify_contract
        self.hpc_runtime = OpenRoadHpcRuntime(
            artifact_store=artifact_store,
            scheduler=scheduler,
            control_timeout_seconds=timeout_seconds,
        )
        self.transport = transport or StdioMCPAdapter(
            launcher,
            expected_provider_digest=expected_provider_digest,
            timeout_seconds=timeout_seconds,
            max_pages=8,
            max_tools=32,
        )
        self.local_runtime = OpenRoadLocalRuntime(self.transport, self.results)
        self._jobs: dict[str, _OpenRoadJob] = {}

    @staticmethod
    def leaf_name(profile_id: str) -> str:
        return openroad_leaf_name(profile_id)

    def _virtual_tools(self) -> list[ProviderToolV1]:
        tools: list[ProviderToolV1] = []
        for profile in sorted(
            self.experiments.values(), key=lambda item: item.profile_id
        ):
            tools.append(
                openroad_virtual_tool(
                    profile,
                    provider_version=self.pin["version"],
                    provider_commit=self.pin["repository_commit"],
                )
            )
        return tools

    async def list_tools(self) -> list[ProviderToolV1]:
        if self.verify_contract:
            upstream = sorted(
                await self.transport.list_tools(), key=lambda item: item.name
            )
            names = {item.name for item in upstream}
            if names != _UPSTREAM_TOOLS:
                raise ProviderProtocolError(
                    "OpenROAD MCP tool surface drifted: "
                    f"expected {sorted(_UPSTREAM_TOOLS)}, got {sorted(names)}"
                )
            contract_digest = sha256_digest(
                [item.model_dump(mode="json") for item in upstream]
            )
            if contract_digest != self.pin["mcp_contract_digest"]:
                raise ProviderProtocolError(
                    "OpenROAD MCP schemas drifted from the reviewed contract"
                )
        return self._virtual_tools()

    def _profile_for_leaf(self, name: str) -> OpenRoadExperimentV1:
        if self.allowed_leaf_names is None or name not in self.allowed_leaf_names:
            raise ProviderProtocolError(
                "OpenROAD runtime accepts only a leaf from the active catalog lock"
            )
        matches = [
            profile
            for profile in self.experiments.values()
            if self.leaf_name(profile.profile_id) == name
        ]
        if len(matches) != 1:
            raise ProviderProtocolError("OpenROAD locked leaf has no unique profile")
        return matches[0]

    async def invoke(self, name: str, arguments: dict[str, Any]) -> ProviderResponseV1:
        profile = self._profile_for_leaf(name)
        if set(arguments) != {"request_id"} or not isinstance(
            arguments.get("request_id"), str
        ):
            raise ProviderProtocolError(
                "OpenROAD experiments accept only a string request_id"
            )
        request_id = arguments["request_id"]
        if not _REQUEST_ID_RE.fullmatch(request_id):
            raise ProviderProtocolError("OpenROAD request_id is invalid")
        handle_id = "openroad-" + sha256_digest(
            {
                "adapter": OPENROAD_ADAPTER_ID,
                "provider_digest": self.expected_provider_digest,
                "experiment_digest": profile.experiment_digest,
                "request_id": request_id,
            }
        ).removeprefix("sha256:")
        job = self._jobs.get(handle_id)
        if job is None:
            if len(self._jobs) >= self.max_retained_jobs:
                raise ProviderProtocolError(
                    "OpenROAD retained-job limit reached; restart or use durable "
                    "scheduler execution"
                )
            job = _OpenRoadJob(
                handle_id=handle_id,
                experiment=profile,
                request_id=request_id,
            )
            self._jobs[handle_id] = job
            job.task = asyncio.create_task(
                self._run_job(job),
                name=f"ari-openroad-{profile.profile_id}",
            )
        payload = self._status_payload(job)
        return ProviderResponseV1(
            text=json.dumps(payload, ensure_ascii=False, sort_keys=True),
            structured=payload,
        )

    async def _run_job(self, job: _OpenRoadJob) -> None:
        try:
            async with self._job_slots:
                if job.experiment.execution.backend == "slurm":
                    await self.hpc_runtime.run_job(
                        self.results, job, verify_openroad_experiment_files
                    )
                else:
                    await self.local_runtime.run_job(job)
        except asyncio.CancelledError:
            job.status = "cancelled"
            job.stage = "cancelled"
            job.completed_at = _now()
            transcript_meta, transcript_ref = (
                self.results.store_transcript_after_failure(job, [])
            )
            structured: dict[str, Any] = {
                "handle_id": job.handle_id,
                "status": "cancelled",
                "session_transcript": transcript_meta,
            }
            if transcript_ref is not None:
                structured["_ari_result_artifacts"] = [
                    transcript_ref.model_dump(mode="json")
                ]
            job.response = self.results.terminal_response(structured)

    @staticmethod
    def _status_payload(job: _OpenRoadJob) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "handle_id": job.handle_id,
            "status": job.status,
            "stage": job.stage,
            "experiment_digest": job.experiment.experiment_digest,
            "request_id": job.request_id,
            "submitted_at": job.submitted_at,
            "started_at": job.started_at,
            "completed_at": job.completed_at,
        }
        if job.error:
            payload["error"] = job.error
        if job.scheduler_handle is not None:
            payload["hpc_handle"] = job.scheduler_handle.model_dump(mode="json")
        return payload

    def _job(self, provider_handle: str) -> _OpenRoadJob:
        job = self._jobs.get(provider_handle)
        if job is None:
            raise ProviderProtocolError(
                "OpenROAD session handle is unknown; recovery is fail-closed"
            )
        return job

    async def get_status(self, lifecycle, provider_handle: str) -> ProviderResponseV1:
        payload = self._status_payload(self._job(provider_handle))
        return ProviderResponseV1(
            text=json.dumps(payload, ensure_ascii=False, sort_keys=True),
            structured=payload,
        )

    async def get_result(self, lifecycle, provider_handle: str) -> ProviderResponseV1:
        job = self._job(provider_handle)
        if job.response is not None:
            return job.response
        return await self.get_status(lifecycle, provider_handle)

    async def cancel(self, lifecycle, provider_handle: str) -> ProviderResponseV1:
        job = self._job(provider_handle)
        if job.status in {"completed", "failed", "cancelled"}:
            if job.status != "cancelled":
                raise ProviderProtocolError(
                    f"OpenROAD job is already terminal: {job.status}"
                )
            assert job.response is not None
            return job.response
        assert job.task is not None
        await self.hpc_runtime.request_cancel(job)
        job.task.cancel()
        with suppress(asyncio.CancelledError):
            await job.task
        assert job.response is not None
        return job.response


__all__ = [
    "OPENROAD_ADAPTER_ID",
    "OPENROAD_ADAPTER_VERSION",
    "OPENROAD_EXPERIMENT_V1",
    "OpenRoadArtifactPinV1",
    "OpenRoadCommandV1",
    "OpenRoadExecutionV1",
    "OpenRoadExperimentAdapter",
    "OpenRoadExperimentV1",
    "OpenRoadMetricV1",
    "OpenRoadOutputArtifactV1",
    "OpenRoadPortableRuntimeV1",
    "OpenRoadProviderPinV1",
    "OpenRoadTechnologyV1",
    "OpenRoadToolchainV1",
    "OpenRoadWorkspaceV1",
    "openroad_adapter_digest",
    "openroad_leaf_name",
    "openroad_virtual_tool",
    "openroad_effective_launcher",
    "openroad_provider_release_pin",
    "openroad_toolchain_line",
    "openroad_workspace_digest",
    "verify_openroad_experiment_files",
    "verify_openroad_provider_package",
    "verify_openroad_provider_pin",
]
