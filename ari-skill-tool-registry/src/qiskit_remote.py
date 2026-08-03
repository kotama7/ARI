"""Credential-scoped IBM Quantum Runtime submission and job lifecycle."""

from __future__ import annotations

import base64
import re
import tempfile
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator

from models import sanitize_text, sha256_digest
from providers import ProviderAdapter, ProviderProtocolError
from qiskit_contracts import QiskitRemoteBackendV1
from qiskit_core import QiskitCoreRuntime, decode_qiskit_response
from qiskit_identity import _file_sha256
from qiskit_results import QiskitResultStore
from qiskit_verification import verify_qiskit_experiment_files


_REMOTE_JOB_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_RUNNING = frozenset({"INITIALIZING", "QUEUED", "RUNNING"})
_TERMINAL = frozenset({"DONE", "CANCELLED", "ERROR"})
_SCIENTIFIC_PROPERTY_KEYS = frozenset(
    {
        "backend_name",
        "backend_version",
        "basis_gates",
        "coupling_map",
        "max_experiments",
        "max_shots",
        "num_qubits",
        "processor_type",
        "simulator",
    }
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class QiskitRemoteRuntime:
    """Use only setup, snapshot, sampler, status, result, and cancel MCP leaves."""

    def __init__(
        self,
        *,
        core: QiskitCoreRuntime,
        transport: ProviderAdapter,
        results: QiskitResultStore,
    ) -> None:
        self.core = core
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

    @staticmethod
    async def _call(
        transport: ProviderAdapter, operation: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        response = await transport.invoke(operation, arguments)
        return decode_qiskit_response(response, operation)

    @asynccontextmanager
    async def _authenticated(
        self, profile: Any, events: list[dict[str, Any]]
    ) -> AsyncIterator[ProviderAdapter]:
        backend = profile.backend
        assert isinstance(backend, QiskitRemoteBackendV1)
        async with self._connection() as transport:
            setup = await self._call(
                transport,
                "setup_ibm_quantum_account_tool",
                {"channel": backend.channel},
            )
            if setup.get("status") != "success":
                raise ProviderProtocolError("IBM Quantum account setup failed")
            instance = await self._call(transport, "active_instance_info_tool", {})
            instance_crn = instance.get("instance_crn")
            if not isinstance(instance_crn, str) or sha256_digest(instance_crn) != (
                backend.instance_digest
            ):
                raise ProviderProtocolError(
                    "IBM Quantum active instance differs from the locked scope"
                )
            credential_event = {
                "stage": "credential-scope",
                "channel": backend.channel,
                "instance_digest": backend.instance_digest,
                "access_tier_id": backend.access_tier_id,
            }
            if credential_event not in events:
                events.append(credential_event)
            yield transport

    @staticmethod
    def _validate_backend_properties(
        backend: QiskitRemoteBackendV1,
        properties: dict[str, Any],
        coupling: dict[str, Any],
    ) -> None:
        expected_simulator = backend.kind == "remote-simulator"
        if (
            properties.get("status") != "success"
            or properties.get("backend_name") != backend.backend_name
            or properties.get("backend_version") != backend.backend_version
            or properties.get("num_qubits") != backend.target.num_qubits
            or bool(properties.get("simulator")) != expected_simulator
            or sorted(properties.get("basis_gates") or []) != backend.target.basis_gates
            or sorted(properties.get("coupling_map") or [])
            != backend.target.coupling_map
        ):
            raise ProviderProtocolError("IBM backend properties differ from profile")
        edges = coupling.get("edges")
        if (
            coupling.get("status") != "success"
            or coupling.get("backend_name") != backend.backend_name
            or coupling.get("num_qubits") != backend.target.num_qubits
            or not isinstance(edges, list)
            or sorted(edges) != backend.target.coupling_map
        ):
            raise ProviderProtocolError("IBM backend coupling map differs from profile")

    async def _snapshot(
        self,
        transport: ProviderAdapter,
        profile: Any,
    ) -> dict[str, Any]:
        backend = profile.backend
        assert isinstance(backend, QiskitRemoteBackendV1)
        properties = await self._call(
            transport,
            "get_backend_properties_tool",
            {"backend_name": backend.backend_name},
        )
        coupling = await self._call(
            transport,
            "get_coupling_map_tool",
            {"backend_name": backend.backend_name},
        )
        self._validate_backend_properties(backend, properties, coupling)
        calibration: dict[str, Any] | None = None
        if backend.calibration_required:
            calibration = await self._call(
                transport,
                "get_backend_calibration_tool",
                {
                    "backend_name": backend.backend_name,
                    "qubit_indices": list(range(backend.target.num_qubits)),
                },
            )
            if (
                calibration.get("status") != "success"
                or calibration.get("backend_name") != backend.backend_name
                or calibration.get("num_qubits") != backend.target.num_qubits
                or not calibration.get("last_calibration")
            ):
                raise ProviderProtocolError("IBM backend calibration is incomplete")
        scientific_material = {
            "target_digest": backend.target.target_digest,
            "properties": {
                key: properties.get(key) for key in sorted(_SCIENTIFIC_PROPERTY_KEYS)
            },
            "coupling": {
                key: coupling.get(key)
                for key in (
                    "adjacency_list",
                    "backend_name",
                    "bidirectional",
                    "edges",
                    "num_edges",
                    "num_qubits",
                )
            },
            "calibration": calibration,
        }
        return {
            "schema_version": "ari.qiskit-backend-snapshot/v1",
            "captured_at": _now(),
            "snapshot_digest": sha256_digest(scientific_material),
            **scientific_material,
        }

    def _terminal_cancelled(self, job: Any, *, before_submit: bool) -> None:
        if job.response is not None and job.status == "cancelled":
            return
        job.status = "cancelled"
        job.stage = "cancelled"
        job.completed_at = _now()
        event: dict[str, Any] = {
            "stage": "cancelled-before-submit" if before_submit else "remote-cancelled"
        }
        if job.remote_job_id is not None:
            event["remote_job_id"] = job.remote_job_id
        job.events.append(event)
        transcript, ref = self.results.store_transcript_after_failure(job, job.events)
        if ref is not None:
            job.artifact_refs.append(ref)
        job.response = self.results.terminal_response(
            {
                "handle_id": job.handle_id,
                "status": "cancelled",
                "execution_transcript": transcript,
                "_ari_result_artifacts": [
                    item.model_dump(mode="json") for item in job.artifact_refs
                ],
            }
        )

    async def submit(self, job: Any) -> None:
        profile = job.experiment
        backend = profile.backend
        assert isinstance(backend, QiskitRemoteBackendV1)
        job.status = "running"
        job.stage = "verifying-circuit"
        job.started_at = _now()
        job.remote_deadline_monotonic = time.monotonic() + profile.timeout_seconds
        events = job.events
        try:
            verify_qiskit_experiment_files(profile)
            with tempfile.TemporaryDirectory(prefix="ari-qiskit-runtime-") as text:
                workspace = Path(text)
                job.stage = "transpiling"
                qpy_path, qpy_digest, transpile_metadata = await self.core.transpile(
                    profile, workspace, events
                )
                if job.cancel_requested:
                    self._terminal_cancelled(job, before_submit=True)
                    return
                for path, role in (
                    (Path(profile.circuit.qpy_path), "qiskit-input-circuit-qpy"),
                    (qpy_path, "qiskit-transpiled-circuit-qpy"),
                ):
                    _metadata, ref = self.results.store_file(
                        path,
                        logical_role=role,
                        media_type="application/x-qiskit-qpy",
                    )
                    if ref is not None:
                        job.artifact_refs.append(ref)
                job.stage = "capturing-backend-snapshot"
                async with self._authenticated(profile, events) as transport:
                    snapshot = await self._snapshot(transport, profile)
                    snapshot_meta, snapshot_ref = self.results.store_json(
                        snapshot, logical_role="qiskit-backend-snapshot"
                    )
                    if snapshot_ref is not None:
                        job.artifact_refs.append(snapshot_ref)
                    job.backend_snapshot = {
                        **snapshot_meta,
                        "snapshot_digest": snapshot["snapshot_digest"],
                        "captured_at": snapshot["captured_at"],
                        "target_digest": snapshot["target_digest"],
                        "last_calibration": (
                            snapshot["calibration"].get("last_calibration")
                            if isinstance(snapshot["calibration"], dict)
                            else None
                        ),
                    }
                    job.backend_snapshot_digest = snapshot["snapshot_digest"]
                    if job.cancel_requested:
                        self._terminal_cancelled(job, before_submit=True)
                        return
                    encoded = base64.b64encode(qpy_path.read_bytes()).decode("ascii")
                    job.stage = "submitting-runtime-job"
                    submitted = await self._call(
                        transport,
                        "run_sampler_tool",
                        {
                            "circuit": encoded,
                            "backend_name": backend.backend_name,
                            "shots": profile.shots,
                            "circuit_format": "qpy",
                            "dynamical_decoupling": (
                                profile.mitigation.dynamical_decoupling
                            ),
                            "dd_sequence": profile.mitigation.dd_sequence,
                            "twirling": profile.mitigation.gate_twirling,
                            "measure_twirling": profile.mitigation.measure_twirling,
                        },
                    )
                remote_id = submitted.get("job_id")
                if (
                    submitted.get("status") != "success"
                    or not isinstance(remote_id, str)
                    or not _REMOTE_JOB_RE.fullmatch(remote_id)
                    or submitted.get("backend") != backend.backend_name
                    or submitted.get("shots") != profile.shots
                ):
                    raise ProviderProtocolError(
                        "IBM Runtime submission identity drifted"
                    )
                job.remote_job_id = remote_id
                job.transpiled_qpy_digest = qpy_digest
                job.transpile_metadata = transpile_metadata
                events.append(
                    {
                        "stage": "submit",
                        "remote_job_id": remote_id,
                        "backend": backend.backend_name,
                        "shots": profile.shots,
                        "backend_snapshot_digest": job.backend_snapshot_digest,
                        "mitigation": profile.mitigation.model_dump(mode="json"),
                    }
                )
                job.stage = "runtime-submitted"
                if job.cancel_requested:
                    await self.cancel(job)
        except Exception as exc:
            self.fail(job, exc)

    async def refresh_status(self, job: Any) -> dict[str, Any]:
        if job.remote_job_id is None:
            return self._status_payload(job)
        profile = job.experiment
        timed_out = False
        async with self._authenticated(profile, job.events) as transport:
            value = await self._call(
                transport,
                "get_job_status_tool",
                {"job_id": job.remote_job_id},
            )
            remote_state = value.get("job_status")
            if (
                value.get("status") != "success"
                or value.get("job_id") != job.remote_job_id
                or value.get("backend") != profile.backend.backend_name
                or remote_state not in _RUNNING | _TERMINAL
            ):
                raise ProviderProtocolError("IBM Runtime job status is invalid")
            deadline = job.remote_deadline_monotonic
            if (
                remote_state in _RUNNING
                and deadline is not None
                and time.monotonic() > deadline
            ):
                cancelled = await self._call(
                    transport,
                    "cancel_job_tool",
                    {"job_id": job.remote_job_id},
                )
                if (
                    cancelled.get("status") != "success"
                    or cancelled.get("job_id") != job.remote_job_id
                ):
                    raise ProviderProtocolError(
                        "IBM Runtime timed out and cancellation was not acknowledged"
                    )
                timed_out = True
        if timed_out:
            job.events.append(
                {"stage": "timeout-cancel", "remote_job_id": job.remote_job_id}
            )
            raise ProviderProtocolError(
                "IBM Runtime job timed out and cancellation was requested"
            )
        previous_state = job.remote_state
        job.remote_state = remote_state
        job.stage = f"runtime-{str(remote_state).casefold()}"
        if previous_state != remote_state:
            job.events.append(
                {
                    "stage": "remote-status",
                    "remote_job_id": job.remote_job_id,
                    "remote_state": remote_state,
                }
            )
        if remote_state == "DONE":
            job.status = "completed"
        elif remote_state == "CANCELLED":
            self._terminal_cancelled(job, before_submit=False)
        elif remote_state == "ERROR":
            self.fail(
                job,
                ProviderProtocolError(
                    sanitize_text(str(value.get("error_message") or "remote error"))
                ),
            )
        else:
            job.status = "running"
        return self._status_payload(job)

    @staticmethod
    def _status_payload(job: Any) -> dict[str, Any]:
        value = {
            "handle_id": job.handle_id,
            "status": job.status,
            "stage": job.stage,
            "experiment_digest": job.experiment.experiment_digest,
            "request_id": job.request_id,
            "remote_job_id": job.remote_job_id,
            "remote_state": job.remote_state,
        }
        if job.error:
            value["error"] = job.error
        return value

    async def collect_result(self, job: Any) -> Any:
        await self.refresh_status(job)
        if job.remote_state != "DONE":
            return job.response
        profile = job.experiment
        backend = profile.backend
        assert isinstance(backend, QiskitRemoteBackendV1)
        async with self._authenticated(profile, job.events) as transport:
            raw = await self._call(
                transport,
                "get_job_results_tool",
                {"job_id": job.remote_job_id},
            )
        if (
            raw.get("status") != "success"
            or raw.get("job_id") != job.remote_job_id
            or raw.get("job_status") != "DONE"
            or raw.get("backend") != backend.backend_name
            or raw.get("shots") != profile.shots
            or not isinstance(raw.get("counts"), dict)
        ):
            raise ProviderProtocolError("IBM Runtime result identity is invalid")
        counts, probabilities = self.results.normalized_counts(profile, raw["counts"])
        job.events.append(
            {
                "stage": "collect-result",
                "remote_job_id": job.remote_job_id,
                "shots": profile.shots,
            }
        )
        raw_meta, raw_ref = self.results.store_json(
            raw, logical_role="qiskit-raw-runtime-result"
        )
        if raw_ref is not None:
            job.artifact_refs.append(raw_ref)
        transcript, transcript_ref = self.results.store_transcript(job, job.events)
        if transcript_ref is not None:
            job.artifact_refs.append(transcript_ref)
        effective_method_digest = sha256_digest(
            {
                "method_digest": profile.method_digest,
                "backend_snapshot_digest": job.backend_snapshot_digest,
                "transpiled_qpy_digest": job.transpiled_qpy_digest,
            }
        )
        structured = {
            "schema_version": "ari.qiskit-result/v1",
            "handle_id": job.handle_id,
            "status": "completed",
            "experiment_digest": profile.experiment_digest,
            "method_digest": profile.method_digest,
            "effective_method_digest": effective_method_digest,
            "request_id": job.request_id,
            "capability_ref": profile.capability_ref,
            "software": profile.software.model_dump(mode="json"),
            "circuit_digest": profile.circuit.qpy_digest,
            "transpiled_qpy_digest": job.transpiled_qpy_digest,
            "transpilation": {
                **profile.transpilation.model_dump(mode="json"),
                "output": job.transpile_metadata,
            },
            "backend": backend.model_dump(mode="json"),
            "backend_snapshot": job.backend_snapshot,
            "remote_job_id": job.remote_job_id,
            "shots": profile.shots,
            "seed_simulator": None,
            "counts": counts,
            "probabilities": probabilities,
            "raw_result": raw_meta,
            "execution_transcript": transcript,
            "_ari_result_artifacts": [
                item.model_dump(mode="json") for item in job.artifact_refs
            ],
        }
        job.completed_at = _now()
        job.response = self.results.terminal_response(structured)
        return job.response

    async def cancel(self, job: Any) -> None:
        if job.remote_job_id is None:
            return
        profile = job.experiment
        async with self._authenticated(profile, job.events) as transport:
            value = await self._call(
                transport, "cancel_job_tool", {"job_id": job.remote_job_id}
            )
        if value.get("status") != "success" or value.get("job_id") != job.remote_job_id:
            raise ProviderProtocolError("IBM Runtime cancellation was not acknowledged")
        job.status = "cancelled"
        job.stage = "cancelled"
        job.remote_state = "CANCELLED"
        job.completed_at = _now()
        job.events.append({"stage": "cancelled", "remote_job_id": job.remote_job_id})
        transcript, ref = self.results.store_transcript_after_failure(job, job.events)
        if ref is not None:
            job.artifact_refs.append(ref)
        job.response = self.results.terminal_response(
            {
                "handle_id": job.handle_id,
                "status": "cancelled",
                "remote_job_id": job.remote_job_id,
                "execution_transcript": transcript,
                "_ari_result_artifacts": [
                    item.model_dump(mode="json") for item in job.artifact_refs
                ],
            }
        )

    def fail(self, job: Any, exc: Exception) -> None:
        if job.response is not None and job.status in {"failed", "cancelled"}:
            return
        job.status = "failed"
        job.stage = "failed"
        job.completed_at = _now()
        job.error = sanitize_text(f"{type(exc).__name__}: {exc}", limit=2_000)
        job.events.append({"stage": "failed", "error": job.error})
        transcript, ref = self.results.store_transcript_after_failure(job, job.events)
        if ref is not None:
            job.artifact_refs.append(ref)
        job.response = self.results.terminal_response(
            {
                "handle_id": job.handle_id,
                "status": "failed",
                "error": job.error,
                "execution_transcript": transcript,
                "_ari_result_artifacts": [
                    item.model_dump(mode="json") for item in job.artifact_refs
                ],
            }
        )


def qiskit_remote_runtime_digest() -> str:
    return _file_sha256(Path(__file__).resolve())


__all__ = ["QiskitRemoteRuntime", "qiskit_remote_runtime_digest"]
