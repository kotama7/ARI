"""Credential-free Qiskit artifact, transcript, and result normalization."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import re
from pathlib import Path
from typing import Any

from ari.public.result import ResultArtifactV1

from models import credential_field_paths, sanitize_text, sha256_digest
from providers import ProviderProtocolError, ProviderResponseV1
from qiskit_contracts import QiskitExperimentV1
from qiskit_identity import _file_sha256
from qiskit_verification import validate_qiskit_counts


class QiskitResultStore:
    """Store raw evidence while exposing one stable normalized count schema."""

    def __init__(self, artifact_store: Any | None) -> None:
        self.artifact_store = artifact_store

    def _put_bytes(
        self,
        payload: bytes,
        *,
        media_type: str,
        logical_role: str,
        suffix: str,
    ) -> tuple[dict[str, Any], ResultArtifactV1 | None]:
        digest = "sha256:" + hashlib.sha256(payload).hexdigest()
        metadata: dict[str, Any] = {
            "digest": digest,
            "media_type": media_type,
            "size": len(payload),
            "logical_role": logical_role,
            "captured": False,
        }
        if self.artifact_store is None:
            return metadata, None
        hexadecimal = digest.removeprefix("sha256:")
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,127}", logical_role):
            raise ProviderProtocolError("Qiskit artifact logical role is invalid")
        logical_name = (
            f"qiskit/sha256/{hexadecimal[:2]}/{hexadecimal}--{logical_role}{suffix}"
        )
        self.artifact_store.put(logical_name, payload)
        metadata.update({"captured": True, "logical_name": logical_name})
        return metadata, ResultArtifactV1(
            digest=digest,
            media_type=media_type,
            size=len(payload),
            logical_role=logical_role,
            logical_name=logical_name,
        )

    def store_json(
        self, value: dict[str, Any], *, logical_role: str
    ) -> tuple[dict[str, Any], ResultArtifactV1 | None]:
        paths = credential_field_paths(value, logical_role)
        if paths:
            raise ProviderProtocolError(
                f"Qiskit artifact contains credential-shaped fields: {paths}"
            )
        payload = (
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        return self._put_bytes(
            payload,
            media_type="application/json",
            logical_role=logical_role,
            suffix=".json",
        )

    def store_file(
        self,
        path: Path,
        *,
        logical_role: str,
        media_type: str | None = None,
        max_bytes: int = 100_000_000,
    ) -> tuple[dict[str, Any], ResultArtifactV1 | None]:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > max_bytes:
            raise ProviderProtocolError("Qiskit artifact path is missing or unsafe")
        payload = path.read_bytes()
        guessed = (
            media_type
            or mimetypes.guess_type(path.name)[0]
            or ("application/octet-stream")
        )
        suffix = path.suffix or ".bin"
        metadata, ref = self._put_bytes(
            payload,
            media_type=guessed,
            logical_role=logical_role,
            suffix=suffix,
        )
        if metadata["digest"] != _file_sha256(path):
            raise ProviderProtocolError("Qiskit artifact changed while being captured")
        return metadata, ref

    @staticmethod
    def normalized_counts(
        profile: QiskitExperimentV1, counts: dict[str, Any]
    ) -> tuple[dict[str, int], list[dict[str, Any]]]:
        normalized = validate_qiskit_counts(profile, counts)
        probabilities = [
            {
                "bitstring": bitstring,
                "count": count,
                "probability": count / profile.shots,
            }
            for bitstring, count in normalized.items()
        ]
        return normalized, probabilities

    def store_transcript(
        self, job: Any, events: list[dict[str, Any]]
    ) -> tuple[dict[str, Any], ResultArtifactV1 | None]:
        return self.store_json(
            {
                "schema_version": "ari.qiskit-transcript/v1",
                "handle_id": job.handle_id,
                "experiment_digest": job.experiment.experiment_digest,
                "request_id": job.request_id,
                "events": events,
            },
            logical_role="qiskit-execution-transcript",
        )

    def store_transcript_after_failure(
        self, job: Any, events: list[dict[str, Any]]
    ) -> tuple[dict[str, Any], ResultArtifactV1 | None]:
        try:
            return self.store_transcript(job, events)
        except Exception as exc:
            return (
                {
                    "captured": False,
                    "capture_error": sanitize_text(
                        f"{type(exc).__name__}: {exc}", limit=1_000
                    ),
                },
                None,
            )

    @staticmethod
    def terminal_response(value: dict[str, Any]) -> ProviderResponseV1:
        structured = dict(value)
        structured["result_digest"] = sha256_digest(structured)
        summary = {
            "handle_id": structured.get("handle_id"),
            "status": structured.get("status"),
            "experiment_digest": structured.get("experiment_digest"),
            "result_digest": structured["result_digest"],
            "shots": structured.get("shots"),
            "outcome_count": len(structured.get("counts") or {}),
            "artifact_count": len(structured.get("_ari_result_artifacts") or []),
        }
        if structured.get("error"):
            summary["error"] = sanitize_text(str(structured["error"]), limit=2_000)
        return ProviderResponseV1(
            text=json.dumps(summary, ensure_ascii=False, sort_keys=True),
            structured=structured,
        )


def qiskit_results_digest() -> str:
    return _file_sha256(Path(__file__).resolve())


__all__ = ["QiskitResultStore", "qiskit_results_digest"]
