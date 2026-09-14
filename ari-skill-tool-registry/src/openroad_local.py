"""Ephemeral local OpenROAD-MCP execution runtime."""

from __future__ import annotations

import asyncio
import json
import tempfile
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator

from models import sanitize_text
from openroad_contracts import OpenRoadExperimentV1
from openroad_identity import _file_sha256
from openroad_results import OpenRoadResultStore
from openroad_verification import verify_openroad_experiment_files
from providers import (
    ProviderAdapter,
    ProviderProtocolError,
    ProviderResponseV1,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _decode_wrapped(response: ProviderResponseV1, operation: str) -> dict[str, Any]:
    if response.is_error:
        raise ProviderProtocolError(
            f"OpenROAD MCP {operation} failed: {sanitize_text(response.text, limit=1_000)}"
        )
    value: Any = response.structured
    if not isinstance(value, dict):
        try:
            value = json.loads(response.text)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ProviderProtocolError(
                f"OpenROAD MCP {operation} returned non-JSON"
            ) from exc
    for _depth in range(3):
        if not isinstance(value, dict) or set(value) != {"result"}:
            break
        value = value["result"]
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                break
    if not isinstance(value, dict):
        raise ProviderProtocolError(
            f"OpenROAD MCP {operation} returned a non-object result"
        )
    if value.get("error"):
        raise ProviderProtocolError(
            f"OpenROAD MCP {operation} failed: "
            f"{sanitize_text(value['error'], limit=1_000)}"
        )
    return value


class OpenRoadLocalRuntime:
    """Run one immutable profile through a stateful local MCP session."""

    def __init__(
        self, transport: ProviderAdapter, results: OpenRoadResultStore
    ) -> None:
        self.transport = transport
        self.results = results

    @asynccontextmanager
    async def _connection(self) -> AsyncIterator[ProviderAdapter]:
        connection = getattr(self.transport, "connection", None)
        if connection is None:
            yield self.transport
            return
        async with connection() as connected:
            yield connected

    async def _call(
        self,
        transport: ProviderAdapter,
        operation: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        response = await transport.invoke(operation, arguments)
        return _decode_wrapped(response, operation)

    @staticmethod
    def _write_program(
        profile: OpenRoadExperimentV1, workspace: Path
    ) -> tuple[Path, str]:
        path = workspace / "ari-openroad-flow.tcl"
        path.write_text(
            "\n".join(command.text for command in profile.commands)
            + "\n# Runtime-owned normal shutdown; not profile authority.\nexit\n",
            encoding="utf-8",
        )
        path.chmod(0o600)
        return path, _file_sha256(path)

    async def _wait_for_session(
        self,
        transport: ProviderAdapter,
        *,
        session_id: str,
        profile: OpenRoadExperimentV1,
        initially_alive: bool,
    ) -> dict[str, Any]:
        started = asyncio.get_running_loop().time()
        final = {"state": "terminated", "is_alive": False}
        while initially_alive:
            elapsed = asyncio.get_running_loop().time() - started
            if elapsed >= profile.command_timeout_seconds:
                raise ProviderProtocolError(
                    "OpenROAD fixed Tcl program exceeded "
                    f"{profile.command_timeout_seconds}s"
                )
            inspected = await self._call(
                transport,
                "inspect_interactive_session",
                {"session_id": session_id},
            )
            metrics = inspected.get("metrics")
            if not isinstance(metrics, dict):
                raise ProviderProtocolError(
                    "OpenROAD MCP returned no typed session state"
                )
            final = {
                "state": str(metrics.get("state") or "unknown"),
                "is_alive": bool(metrics.get("is_alive")),
            }
            if not final["is_alive"] or final["state"] in {"terminated", "error"}:
                return final
            await asyncio.sleep(profile.poll_interval_seconds)
        return final

    async def run_job(self, job: Any) -> None:
        profile = job.experiment
        job.status = "running"
        job.stage = "initializing"
        job.started_at = _now()
        transcript: list[dict[str, Any]] = []
        session_id = "ari_" + job.handle_id.removeprefix("openroad-")[:24]
        try:
            verify_openroad_experiment_files(profile)
            with tempfile.TemporaryDirectory(prefix="ari-openroad-workspace-") as text:
                workspace = Path(text)
                self.results.copy_inputs(profile, workspace)
                for output in profile.output_artifacts:
                    (workspace / output.relative_path).parent.mkdir(
                        parents=True, exist_ok=True
                    )
                tcl_path, tcl_digest = self._write_program(profile, workspace)
                transcript.append(
                    {
                        "stage": "execution",
                        "operation": "runtime-generated-fixed-tcl",
                        "tcl_digest": tcl_digest,
                        "command_count": len(profile.commands),
                    }
                )
                async with self._connection() as transport:
                    created = False
                    try:
                        metric_outputs = [
                            item.relative_path
                            for item in profile.output_artifacts
                            if any(
                                metric.source_artifact == item.relative_path
                                for metric in profile.metrics
                            )
                        ]
                        metrics_path = sorted(set(metric_outputs))[0]
                        created_payload = await self._call(
                            transport,
                            "create_interactive_session",
                            {
                                "session_id": session_id,
                                "command": [
                                    profile.toolchain.executable_path,
                                    "-no_init",
                                    "-metrics",
                                    metrics_path,
                                    tcl_path.name,
                                ],
                                "env": {},
                                "cwd": str(workspace),
                            },
                        )
                        if created_payload.get("session_id") != session_id:
                            raise ProviderProtocolError(
                                "OpenROAD MCP did not create the bound session"
                            )
                        created = True
                        job.stage = "executing"
                        final_state = await self._wait_for_session(
                            transport,
                            session_id=session_id,
                            profile=profile,
                            initially_alive=bool(created_payload.get("is_alive")),
                        )
                        transcript.append(
                            {
                                "stage": "finalizing",
                                "operation": "fixed-tcl-process-exit",
                                "session_state": final_state,
                            }
                        )
                        metrics_file = workspace / metrics_path
                        flush_deadline = asyncio.get_running_loop().time() + 10.0
                        while not metrics_file.is_file():
                            if asyncio.get_running_loop().time() >= flush_deadline:
                                raise ProviderProtocolError(
                                    "OpenROAD normal exit did not flush the metrics artifact"
                                )
                            await asyncio.sleep(0.05)
                        job.stage = "collecting"
                        artifact_manifest, artifact_refs, artifact_digests = (
                            self.results.capture_artifacts(
                                profile,
                                workspace,
                                internal_paths=frozenset({tcl_path.name}),
                            )
                        )
                        metrics = self.results.normalize_metrics(
                            profile, workspace, artifact_digests
                        )
                    finally:
                        if created:
                            with suppress(Exception):
                                terminated = await self._call(
                                    transport,
                                    "terminate_interactive_session",
                                    {"session_id": session_id, "force": True},
                                )
                                transcript.append(
                                    {
                                        "stage": "cleanup",
                                        "operation": "terminate_interactive_session",
                                        "terminated": bool(
                                            terminated.get("terminated", True)
                                        ),
                                    }
                                )
                transcript_meta, transcript_ref = self.results.store_transcript(
                    job, transcript
                )
                if transcript_ref is not None:
                    artifact_refs.append(transcript_ref)
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
                    "_ari_result_artifacts": [
                        item.model_dump(mode="json") for item in artifact_refs
                    ],
                    "session_recovery": "fail-closed; local MCP sessions are ephemeral",
                }
                job.status = "completed"
                job.stage = "completed"
                job.completed_at = _now()
                job.response = self.results.terminal_response(structured)
        except asyncio.CancelledError:
            job.status = "cancelled"
            job.stage = "cancelled"
            job.completed_at = _now()
            transcript_meta, transcript_ref = (
                self.results.store_transcript_after_failure(job, transcript)
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
        except Exception as exc:
            job.status = "failed"
            job.stage = "failed"
            job.completed_at = _now()
            job.error = sanitize_text(f"{type(exc).__name__}: {exc}", limit=2_000)
            transcript_meta, transcript_ref = (
                self.results.store_transcript_after_failure(job, transcript)
            )
            structured: dict[str, Any] = {
                "handle_id": job.handle_id,
                "status": "failed",
                "error": job.error,
                "session_transcript": transcript_meta,
            }
            if transcript_ref is not None:
                structured["_ari_result_artifacts"] = [
                    transcript_ref.model_dump(mode="json")
                ]
            job.response = self.results.terminal_response(structured)


def openroad_local_runtime_digest() -> str:
    return _file_sha256(Path(__file__).resolve())


__all__ = ["OpenRoadLocalRuntime", "openroad_local_runtime_digest"]
