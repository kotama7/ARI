"""Credential-free local Qiskit Aer execution runtime."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ari.public.result import ResultArtifactV1

from models import sanitize_text, sha256_digest
from providers import ProviderProtocolError
from qiskit_contracts import QiskitLocalBackendV1
from qiskit_core import QiskitCoreRuntime
from qiskit_identity import _file_sha256
from qiskit_results import QiskitResultStore
from qiskit_verification import verify_qiskit_experiment_files


_WORKER = Path(__file__).resolve().with_name("qiskit_worker.py")
_RESULT_KEYS = {
    "schema_version",
    "experiment_digest",
    "started_at",
    "completed_at",
    "architecture",
    "qiskit_version",
    "qiskit_aer_version",
    "qpy_digest",
    "backend_name",
    "simulator_method",
    "precision",
    "device",
    "max_parallel_threads",
    "shots",
    "seed_simulator",
    "counts",
    "return_code",
    "error",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class QiskitLocalRuntime:
    """Transpile through the official MCP, then run one fixed Aer worker."""

    def __init__(
        self,
        *,
        core: QiskitCoreRuntime,
        results: QiskitResultStore,
        worker_python: str,
    ) -> None:
        self.core = core
        self.results = results
        self.worker_python = worker_python

    @staticmethod
    def _write_json(path: Path, value: dict[str, Any]) -> None:
        path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        path.chmod(0o600)

    @staticmethod
    async def _reap(process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        process.terminate()
        try:
            async with asyncio.timeout(5):
                await process.wait()
        except TimeoutError:
            process.kill()
            await process.wait()

    @staticmethod
    def _load_worker_result(path: Path, job: Any, qpy_digest: str) -> dict[str, Any]:
        profile = job.experiment
        backend = profile.backend
        assert isinstance(backend, QiskitLocalBackendV1)
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 20_000_000:
            raise ProviderProtocolError("Qiskit Aer result is missing or unsafe")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderProtocolError(f"Qiskit Aer result is invalid: {exc}") from exc
        if not isinstance(value, dict) or set(value) != _RESULT_KEYS:
            raise ProviderProtocolError("Qiskit Aer result shape drifted")
        identity_matches = (
            value["schema_version"] == "ari.qiskit-aer-result/v1"
            and value["experiment_digest"] == profile.experiment_digest
            and value["qiskit_version"] == profile.software.qiskit_version
            and value["qiskit_aer_version"] == profile.software.qiskit_aer_version
            and value["qpy_digest"] == qpy_digest
            and value["backend_name"] == backend.backend_name
            and value["simulator_method"] == backend.simulator_method
            and value["precision"] == backend.precision
            and value["device"] == backend.device
            and value["max_parallel_threads"] == backend.max_parallel_threads
            and value["shots"] == profile.shots
            and value["seed_simulator"] == profile.seed_simulator
        )
        if (
            not identity_matches
            or value["return_code"] != 0
            or value["error"] is not None
            or not isinstance(value["counts"], dict)
        ):
            raise ProviderProtocolError(
                "Qiskit Aer worker identity or execution failed"
            )
        return value

    async def run_job(self, job: Any) -> None:
        profile = job.experiment
        backend = profile.backend
        assert isinstance(backend, QiskitLocalBackendV1)
        job.status = "running"
        job.stage = "verifying-circuit"
        job.started_at = _now()
        events: list[dict[str, Any]] = []
        artifact_refs: list[ResultArtifactV1] = []
        try:
            verify_qiskit_experiment_files(profile)
            with tempfile.TemporaryDirectory(prefix="ari-qiskit-aer-") as text:
                workspace = Path(text)
                job.local_workspace = workspace
                job.stage = "transpiling"
                qpy_path, qpy_digest, transpile_metadata = await self.core.transpile(
                    profile, workspace, events
                )
                for path, role, media_type in (
                    (
                        Path(profile.circuit.qpy_path),
                        "qiskit-input-circuit-qpy",
                        "application/x-qiskit-qpy",
                    ),
                    (
                        qpy_path,
                        "qiskit-transpiled-circuit-qpy",
                        "application/x-qiskit-qpy",
                    ),
                ):
                    _metadata, ref = self.results.store_file(
                        path, logical_role=role, media_type=media_type
                    )
                    if ref is not None:
                        artifact_refs.append(ref)
                worker_path = workspace / "qiskit-worker.py"
                shutil.copyfile(_WORKER, worker_path)
                worker_path.chmod(0o600)
                result_path = workspace / "aer-result.json"
                spec_path = workspace / "aer-spec.json"
                noise = (
                    backend.noise_model.model_dump(mode="json")
                    if backend.noise_model is not None
                    else None
                )
                self._write_json(
                    spec_path,
                    {
                        "schema_version": "ari.qiskit-aer-spec/v1",
                        "experiment_digest": profile.experiment_digest,
                        "qpy_path": str(qpy_path),
                        "qpy_digest": qpy_digest,
                        "qpy_version": qpy_path.read_bytes()[6],
                        "num_qubits": transpile_metadata["num_qubits"],
                        "num_clbits": profile.circuit.num_clbits,
                        "parameter_bindings": profile.circuit.parameter_bindings,
                        "qiskit_version": profile.software.qiskit_version,
                        "qiskit_aer_version": profile.software.qiskit_aer_version,
                        "backend_name": backend.backend_name,
                        "simulator_method": backend.simulator_method,
                        "precision": backend.precision,
                        "device": backend.device,
                        "max_parallel_threads": backend.max_parallel_threads,
                        "noise_model": noise,
                        "shots": profile.shots,
                        "seed_simulator": profile.seed_simulator,
                        "result_path": str(result_path),
                    },
                )
                job.stage = "simulating"
                home = workspace / "home"
                home.mkdir(mode=0o700)
                environment = {
                    "HOME": str(home),
                    "LANG": os.environ.get("LANG", "C.UTF-8"),
                    "OMP_NUM_THREADS": str(backend.max_parallel_threads),
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "PYTHONUNBUFFERED": "1",
                }
                process = await asyncio.create_subprocess_exec(
                    self.worker_python,
                    str(worker_path),
                    str(spec_path),
                    cwd=str(workspace),
                    env=environment,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                job.local_process = process
                try:
                    async with asyncio.timeout(profile.timeout_seconds):
                        stdout, stderr = await process.communicate()
                except TimeoutError as exc:
                    await self._reap(process)
                    raise ProviderProtocolError("Qiskit Aer worker timed out") from exc
                finally:
                    job.local_process = None
                if len(stdout) > 100_000 or len(stderr) > 100_000:
                    raise ProviderProtocolError(
                        "Qiskit Aer worker diagnostics are too large"
                    )
                events.append(
                    {
                        "stage": "simulate",
                        "worker_digest": _file_sha256(worker_path),
                        "spec_digest": _file_sha256(spec_path),
                        "return_code": process.returncode,
                        "stdout": sanitize_text(
                            stdout.decode(errors="replace"), limit=10_000
                        ),
                        "stderr": sanitize_text(
                            stderr.decode(errors="replace"), limit=10_000
                        ),
                    }
                )
                worker_result = self._load_worker_result(result_path, job, qpy_digest)
                counts, probabilities = self.results.normalized_counts(
                    profile, worker_result["counts"]
                )
                raw_meta, raw_ref = self.results.store_file(
                    result_path,
                    logical_role="qiskit-raw-aer-result",
                    media_type="application/json",
                    max_bytes=20_000_000,
                )
                if raw_ref is not None:
                    artifact_refs.append(raw_ref)
                transcript_meta, transcript_ref = self.results.store_transcript(
                    job, events
                )
                if transcript_ref is not None:
                    artifact_refs.append(transcript_ref)
                structured = {
                    "schema_version": "ari.qiskit-result/v1",
                    "handle_id": job.handle_id,
                    "status": "completed",
                    "experiment_digest": profile.experiment_digest,
                    "method_digest": profile.method_digest,
                    "effective_method_digest": sha256_digest(
                        {
                            "method_digest": profile.method_digest,
                            "qpy_digest": qpy_digest,
                        }
                    ),
                    "request_id": job.request_id,
                    "capability_ref": profile.capability_ref,
                    "software": profile.software.model_dump(mode="json"),
                    "circuit_digest": profile.circuit.qpy_digest,
                    "transpiled_qpy_digest": qpy_digest,
                    "transpilation": {
                        **profile.transpilation.model_dump(mode="json"),
                        "output": transpile_metadata,
                    },
                    "backend": backend.model_dump(mode="json"),
                    "shots": profile.shots,
                    "seed_simulator": profile.seed_simulator,
                    "counts": counts,
                    "probabilities": probabilities,
                    "raw_result": raw_meta,
                    "execution_transcript": transcript_meta,
                    "_ari_result_artifacts": [
                        item.model_dump(mode="json") for item in artifact_refs
                    ],
                }
                job.status = "completed"
                job.stage = "completed"
                job.completed_at = _now()
                job.response = self.results.terminal_response(structured)
        except asyncio.CancelledError:
            if job.local_process is not None:
                await self._reap(job.local_process)
                job.local_process = None
            self._cancelled(job, events, artifact_refs)
        except Exception as exc:
            self._failed(job, exc, events, artifact_refs)
        finally:
            job.local_workspace = None

    def _cancelled(
        self, job: Any, events: list[dict[str, Any]], refs: list[ResultArtifactV1]
    ) -> None:
        job.status = "cancelled"
        job.stage = "cancelled"
        job.completed_at = _now()
        events.append({"stage": "cancelled"})
        transcript, ref = self.results.store_transcript_after_failure(job, events)
        if ref is not None:
            refs.append(ref)
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

    def _failed(
        self,
        job: Any,
        exc: Exception,
        events: list[dict[str, Any]],
        refs: list[ResultArtifactV1],
    ) -> None:
        job.status = "failed"
        job.stage = "failed"
        job.completed_at = _now()
        job.error = sanitize_text(f"{type(exc).__name__}: {exc}", limit=2_000)
        events.append({"stage": "failed", "error": job.error})
        transcript, ref = self.results.store_transcript_after_failure(job, events)
        if ref is not None:
            refs.append(ref)
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


def qiskit_local_runtime_digest() -> str:
    return sha256_digest(
        {
            "runtime_source": _file_sha256(Path(__file__).resolve()),
            "worker_source": _file_sha256(_WORKER),
        }
    )


__all__ = ["QiskitLocalRuntime", "qiskit_local_runtime_digest"]
