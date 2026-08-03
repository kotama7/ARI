"""Artifact-backed model-call and repair provenance for rubric generation."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Awaitable, Callable


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def bytes_sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _safe_label(value: str) -> str:
    label = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.")
    return (label or "call")[:128]


class ModelCallBudgetExceeded(RuntimeError):
    """The declared rubric-generation model-call budget was exhausted."""


class ProvenanceRecorder:
    """Persist exact prompts/responses and expose deterministic call records."""

    def __init__(
        self,
        *,
        output_path: str,
        model: str,
        provider: str,
        model_revision: str | None,
        max_model_calls: int,
    ) -> None:
        self.output_path = Path(output_path).resolve()
        self.base = self.output_path.parent / ".ari-rubric" / self.output_path.stem
        self.calls_dir = self.base / "calls"
        self.inputs_dir = self.base / "inputs"
        self.repairs_dir = self.base / "repairs"
        self.calls_dir.mkdir(parents=True, exist_ok=True)
        self.inputs_dir.mkdir(parents=True, exist_ok=True)
        self.repairs_dir.mkdir(parents=True, exist_ok=True)
        self.model = model
        self.provider = provider
        self.model_revision = model_revision
        self.max_model_calls = max_model_calls
        self._reserved = 0
        self._lock = asyncio.Lock()
        self._calls: dict[str, dict[str, Any]] = {}

    def _artifact(self, path: Path, payload: bytes, media_type: str) -> dict[str, Any]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        try:
            relative = path.relative_to(self.output_path.parent).as_posix()
        except ValueError as exc:  # pragma: no cover - constructor guarantees this
            raise ValueError("rubric provenance escaped the output workspace") from exc
        return {
            "relative_path": relative,
            "sha256": bytes_sha256(payload),
            "size_bytes": len(payload),
            "media_type": media_type,
        }

    async def invoke(
        self,
        *,
        label: str,
        prompt: str,
        call: Callable[[str], Awaitable[str]],
    ) -> str:
        safe = _safe_label(label)
        async with self._lock:
            if safe in self._calls:
                raise ValueError(f"duplicate rubric model-call label: {safe}")
            self._reserved += 1
            ordinal = self._reserved
            if ordinal > self.max_model_calls:
                self._reserved -= 1
                raise ModelCallBudgetExceeded(
                    f"rubric model-call budget {self.max_model_calls} exhausted"
                )

        prompt_artifact = self._artifact(
            self.calls_dir / f"{safe}.prompt.txt",
            prompt.encode("utf-8"),
            "text/plain; charset=utf-8",
        )
        record: dict[str, Any] = {
            "label": safe,
            "status": "failed",
            "model": self.model,
            "model_revision": self.model_revision,
            "provider": self.provider,
            "prompt": prompt_artifact,
            "error": None,
        }
        try:
            raw = await call(prompt)
            if not isinstance(raw, str):
                raise TypeError("rubric model call did not return text")
            record["status"] = "completed"
            record["raw_response"] = self._artifact(
                self.calls_dir / f"{safe}.response.txt",
                raw.encode("utf-8"),
                "text/plain; charset=utf-8",
            )
            record["call_sha256"] = canonical_sha256(record)
            self._calls[safe] = record
            return raw
        except ModelCallBudgetExceeded:
            raise
        except Exception as exc:
            record["error"] = f"{type(exc).__name__}: {exc}"[:4096]
            record["call_sha256"] = canonical_sha256(record)
            self._calls[safe] = record
            raise

    def calls(self) -> list[dict[str, Any]]:
        return [self._calls[key] for key in sorted(self._calls)]

    def write_input(
        self, label: str, payload: bytes, media_type: str = "application/json"
    ) -> dict[str, Any]:
        """Persist an immutable migration/input artifact beside the rubric."""

        return self._artifact(
            self.inputs_dir / f"{_safe_label(label)}.json",
            payload,
            media_type,
        )

    def write_dropped(self, sequence: int, target: str, dropped: Any) -> dict[str, Any]:
        payload = json.dumps(
            dropped,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        ).encode("utf-8")
        return self._artifact(
            self.repairs_dir / f"{sequence:03d}-{_safe_label(target)}.dropped.json",
            payload,
            "application/json",
        )


class RepairLedger:
    """Record every meaning-affecting normalization and removed payload."""

    def __init__(self, recorder: ProvenanceRecorder) -> None:
        self.recorder = recorder
        self.actions: list[dict[str, Any]] = []
        self.dropped_artifacts: list[dict[str, Any]] = []

    def record(
        self,
        *,
        action: str,
        target: str,
        before: Any,
        after: Any,
        reason: str,
        dropped: Any | None = None,
    ) -> None:
        before_sha = canonical_sha256(before)
        after_sha = canonical_sha256(after)
        if before_sha == after_sha and dropped is None:
            return
        sequence = len(self.actions)
        item: dict[str, Any] = {
            "sequence": sequence,
            "action": action,
            "target": target,
            "before_sha256": before_sha,
            "after_sha256": after_sha,
            "reason": reason,
        }
        if dropped is not None:
            artifact = self.recorder.write_dropped(sequence, target, dropped)
            item["dropped_artifact"] = artifact
            self.dropped_artifacts.append(artifact)
        self.actions.append(item)

    def document(self) -> dict[str, Any]:
        return {
            "actions": list(self.actions),
            "dropped_artifacts": list(self.dropped_artifacts),
        }


__all__ = [
    "ModelCallBudgetExceeded",
    "ProvenanceRecorder",
    "RepairLedger",
    "bytes_sha256",
    "canonical_sha256",
]
