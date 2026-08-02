"""Ephemeral local OpenROAD-MCP execution runtime."""

from __future__ import annotations

import asyncio
import json
import tempfile
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator

from models import sanitize_text, sha256_digest
from openroad_contracts import OpenRoadCommandV1, OpenRoadExperimentV1
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

    async def _run_command(
        self,
        transport: ProviderAdapter,
        *,
        session_id: str,
        command: OpenRoadCommandV1,
        profile: OpenRoadExperimentV1,
        transcript: list[dict[str, Any]],
        handle_id: str,
    ) -> None:
        started = asyncio.get_running_loop().time()
        initial = await self._call(
            transport,
            "interactive_openroad_exec",
            {"command": command.text, "session_id": session_id, "timeout_ms": 250},
        )
        chunks = [str(initial.get("output") or "")]
        if initial.get("error"):
            raise ProviderProtocolError(
                f"OpenROAD command {command.verb} failed: {initial['error']}"
            )
        sentinel = (
            "ARI_DONE_"
            + sha256_digest(
                {"handle_id": handle_id, "command": command.model_dump(mode="json")}
            ).removeprefix("sha256:")[:24]
        )
        while sentinel not in "\n".join(chunks):
            elapsed = asyncio.get_running_loop().time() - started
            command_timeout = profile.command_timeout_seconds
            if elapsed >= command_timeout:
                raise ProviderProtocolError(
                    f"OpenROAD command {command.verb} exceeded {command_timeout}s"
                )
            poll_ms = max(100, min(1_000, int((command_timeout - elapsed) * 1_000)))
            polled = await self._call(
                transport,
                "interactive_openroad_query",
                {
                    "command": f"puts {sentinel}",
                    "session_id": session_id,
                    "timeout_ms": poll_ms,
                },
            )
            chunks.append(str(polled.get("output") or ""))
            if polled.get("error"):
                raise ProviderProtocolError(
                    f"OpenROAD command {command.verb} failed: {polled['error']}"
                )
            if sentinel not in chunks[-1]:
                await asyncio.sleep(profile.poll_interval_seconds)
        output = "\n".join(chunks).replace(sentinel, "").strip()
        transcript.append(
            {
                "stage": command.stage,
                "verb": command.verb,
                "arguments": command.arguments,
                "output": sanitize_text(output, limit=100_000),
                "duration_seconds": round(
                    asyncio.get_running_loop().time() - started, 6
                ),
            }
        )
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
                                ],
                                "env": {},
                                "cwd": str(workspace),
                            },
                        )
                        if not created_payload.get("is_alive") or (
                            created_payload.get("session_id") != session_id
                        ):
                            raise ProviderProtocolError(
                                "OpenROAD MCP did not create the bound session"
                            )
                        created = True
                        for command in profile.commands:
                            job.stage = command.stage
                            await self._run_command(
                                transport,
                                session_id=session_id,
                                command=command,
                                profile=profile,
                                transcript=transcript,
                                handle_id=job.handle_id,
                            )
                        job.stage = "collecting"
                        artifact_manifest, artifact_refs, artifact_digests = (
                            self.results.capture_artifacts(profile, workspace)
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
            transcript_meta, transcript_ref = self.results.store_transcript_after_failure(
                job, transcript
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
            transcript_meta, transcript_ref = self.results.store_transcript_after_failure(
                job, transcript
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
