"""Shared OpenROAD input, artifact, metric, and transcript normalization."""

from __future__ import annotations

import hashlib
import json
import math
import mimetypes
import shutil
from pathlib import Path
from typing import Any

from ari.public.result import ResultArtifactV1

from models import sanitize_text, sha256_digest
from openroad_contracts import OpenRoadExperimentV1
from openroad_identity import _file_sha256
from providers import ProviderProtocolError, ProviderResponseV1


def _json_pointer(document: Any, pointer: str) -> Any:
    value = document
    for raw in pointer.removeprefix("/").split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(value, dict) and token in value:
            value = value[token]
        elif isinstance(value, list) and token.isdigit() and int(token) < len(value):
            value = value[int(token)]
        else:
            raise ProviderProtocolError(
                f"OpenROAD metric JSON pointer {pointer!r} is absent"
            )
    return value




class OpenRoadResultStore:
    """Normalize scientific results identically across execution backends."""

    def __init__(self, artifact_store: Any | None) -> None:
        self.artifact_store = artifact_store

    @staticmethod
    def copy_inputs(profile: OpenRoadExperimentV1, target: Path) -> None:
        source = Path(profile.workspace.source_root)
        for artifact in profile.workspace.input_artifacts:
            source_path = source / artifact.relative_path
            target_path = target / artifact.relative_path
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_path, target_path)
            if target_path.is_symlink() or _file_sha256(target_path) != artifact.digest:
                raise ProviderProtocolError(
                    "OpenROAD copied input failed digest verification: "
                    f"{artifact.relative_path}"
                )

    def capture_artifacts(
        self,
        profile: OpenRoadExperimentV1,
        workspace: Path,
        *,
        internal_paths: frozenset[str] = frozenset(),
    ) -> tuple[list[dict[str, Any]], list[ResultArtifactV1], dict[str, str]]:
        input_paths = {
            artifact.relative_path for artifact in profile.workspace.input_artifacts
        }
        output_by_path = {
            artifact.relative_path: artifact for artifact in profile.output_artifacts
        }
        actual: set[str] = set()
        for path in sorted(workspace.rglob("*"), key=lambda item: item.as_posix()):
            if path.is_symlink():
                raise ProviderProtocolError(
                    f"OpenROAD run workspace contains a symlink: {path}"
                )
            if path.is_file():
                relative = path.relative_to(workspace).as_posix()
                if relative in internal_paths or relative.startswith(".ari-hpc/"):
                    continue
                actual.add(relative)
        unexpected = sorted(actual - input_paths - set(output_by_path))
        if unexpected:
            raise ProviderProtocolError(
                f"OpenROAD produced undeclared artifacts: {unexpected[:50]}"
            )

        manifest: list[dict[str, Any]] = []
        refs: list[ResultArtifactV1] = []
        digests: dict[str, str] = {}
        for relative, contract in sorted(output_by_path.items()):
            path = workspace / relative
            if not path.is_file():
                if contract.required:
                    raise ProviderProtocolError(
                        f"OpenROAD required artifact is missing: {relative}"
                    )
                continue
            size = path.stat().st_size
            if size > contract.max_bytes:
                raise ProviderProtocolError(
                    f"OpenROAD artifact exceeds its size limit: {relative}"
                )
            digest = _file_sha256(path)
            if contract.expected_digest is not None and digest != (
                contract.expected_digest
            ):
                raise ProviderProtocolError(
                    f"OpenROAD artifact digest is outside the golden policy: {relative}"
                )
            digests[relative] = digest
            item = {
                "relative_path": relative,
                "logical_role": contract.logical_role,
                "media_type": contract.media_type,
                "digest": digest,
                "size": size,
                "captured": bool(contract.capture and self.artifact_store is not None),
            }
            manifest.append(item)
            if contract.capture and self.artifact_store is not None:
                hexadecimal = digest.removeprefix("sha256:")
                suffix = (
                    Path(relative).suffix
                    or mimetypes.guess_extension(contract.media_type)
                    or ".bin"
                )
                logical_name = (
                    f"openroad/sha256/{hexadecimal[:2]}/{hexadecimal}{suffix}"
                )
                self.artifact_store.put(logical_name, path)
                refs.append(
                    ResultArtifactV1(
                        digest=digest,
                        media_type=contract.media_type,
                        size=size,
                        logical_role=contract.logical_role,
                        logical_name=logical_name,
                    )
                )
        return manifest, refs, digests

    @staticmethod
    def normalize_metrics(
        profile: OpenRoadExperimentV1,
        workspace: Path,
        artifact_digests: dict[str, str],
    ) -> list[dict[str, Any]]:
        documents: dict[str, Any] = {}
        output: list[dict[str, Any]] = []
        for metric in profile.metrics:
            if metric.source_artifact not in documents:
                path = workspace / metric.source_artifact
                try:
                    documents[metric.source_artifact] = json.loads(
                        path.read_text(encoding="utf-8")
                    )
                except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
                    raise ProviderProtocolError(
                        f"OpenROAD metric artifact is invalid: {exc}"
                    ) from exc
            raw = _json_pointer(documents[metric.source_artifact], metric.json_pointer)
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                raise ProviderProtocolError(
                    f"OpenROAD metric {metric.metric_id!r} is not numeric"
                )
            value = float(raw)
            if not math.isfinite(value):
                raise ProviderProtocolError(
                    f"OpenROAD metric {metric.metric_id!r} is non-finite"
                )
            if metric.expected_min is not None and value < metric.expected_min:
                raise ProviderProtocolError(
                    f"OpenROAD metric {metric.metric_id!r} is below its golden range"
                )
            if metric.expected_max is not None and value > metric.expected_max:
                raise ProviderProtocolError(
                    f"OpenROAD metric {metric.metric_id!r} is above its golden range"
                )
            output.append(
                {
                    "metric_id": metric.metric_id,
                    "value": value,
                    "unit": metric.unit,
                    "corner": metric.corner,
                    "mode": metric.mode,
                    "stage": metric.stage,
                    "source_report": {
                        "relative_path": metric.source_artifact,
                        "digest": artifact_digests[metric.source_artifact],
                        "json_pointer": metric.json_pointer,
                    },
                    "golden_range": (
                        {
                            "min": metric.expected_min,
                            "max": metric.expected_max,
                        }
                        if metric.expected_min is not None
                        or metric.expected_max is not None
                        else None
                    ),
                }
            )
        return output

    def store_transcript(
        self,
        job: Any,
        transcript: list[dict[str, Any]],
    ) -> tuple[dict[str, Any], ResultArtifactV1 | None]:
        payload = (
            json.dumps(
                {
                    "schema_version": "ari.openroad-transcript/v1",
                    "handle_id": job.handle_id,
                    "experiment_digest": job.experiment.experiment_digest,
                    "request_id": job.request_id,
                    "commands": transcript,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        digest = f"sha256:{hashlib.sha256(payload).hexdigest()}"
        metadata = {"digest": digest, "size": len(payload), "captured": False}
        if self.artifact_store is None:
            return metadata, None
        hexadecimal = digest.removeprefix("sha256:")
        logical_name = f"openroad/sha256/{hexadecimal[:2]}/{hexadecimal}.json"
        self.artifact_store.put(logical_name, payload)
        metadata.update({"captured": True, "logical_name": logical_name})
        return metadata, ResultArtifactV1(
            digest=digest,
            media_type="application/json",
            size=len(payload),
            logical_role="openroad-session-transcript",
            logical_name=logical_name,
        )

    def store_transcript_after_failure(
        self,
        job: Any,
        transcript: list[dict[str, Any]],
    ) -> tuple[dict[str, Any], ResultArtifactV1 | None]:
        try:
            return self.store_transcript(job, transcript)
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
    def terminal_response(structured: dict[str, Any]) -> ProviderResponseV1:
        structured = dict(structured)
        structured["result_digest"] = sha256_digest(structured)
        summary = {
            "handle_id": structured.get("handle_id"),
            "status": structured.get("status"),
            "experiment_digest": structured.get("experiment_digest"),
            "result_digest": structured["result_digest"],
            "metric_count": len(structured.get("metrics") or []),
            "artifact_count": len(structured.get("_ari_result_artifacts") or []),
        }
        if structured.get("error"):
            summary["error"] = sanitize_text(structured["error"], limit=2_000)
        return ProviderResponseV1(
            text=json.dumps(summary, ensure_ascii=False, sort_keys=True),
            structured=structured,
        )


def openroad_results_digest() -> str:
    return _file_sha256(Path(__file__).resolve())


__all__ = ["OpenRoadResultStore", "openroad_results_digest"]
