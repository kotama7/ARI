"""Versioned result contract and MCP compatibility normalization.

The MCP transport historically exposes ``{"result": "<text>"}`` and
``{"error": "..."}`` dictionaries to ARI callers.  ``ResultEnvelopeV1`` is the
provider-neutral contract used internally and by future catalog adapters.  The
normalizer keeps a lossless legacy conversion while bounding the serialized
envelope: large raw responses are stored content-addressably through the existing
``ArtifactStore`` seam.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ari.protocols.stores import ArtifactStore


RESULT_ENVELOPE_V1 = "ari.result-envelope/v1"
ARTIFACT_REF_V1 = "ari.artifact-ref/v1"
DEFAULT_INLINE_RESULT_LIMIT = 4_000
RAW_RESULT_ROLE = "mcp-raw-result"
SHA256_DIGEST_PATTERN = r"^sha256:[0-9a-f]{64}$"

ResultErrorKind = Literal[
    "tool",
    "transport",
    "protocol",
    "timeout",
    "cancelled",
    "admission",
    "artifact-integrity",
    "unknown",
]


class ResultArtifactIntegrityError(ValueError):
    """Raised when a content-addressed artifact does not match its digest."""


class ResultArtifactV1(BaseModel):
    """Content-addressed artifact descriptor stored relative to a run store."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["ari.artifact-ref/v1"] = ARTIFACT_REF_V1
    digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    media_type: str = Field(min_length=1)
    size: int = Field(ge=0)
    logical_role: str = Field(min_length=1)
    logical_name: str = Field(min_length=1)

    @field_validator("digest")
    @classmethod
    def _valid_digest(cls, value: str) -> str:
        prefix = "sha256:"
        digest = value.removeprefix(prefix)
        if not value.startswith(prefix) or len(digest) != 64:
            raise ValueError("digest must use sha256:<64 lowercase hex> format")
        try:
            int(digest, 16)
        except ValueError as exc:
            raise ValueError("digest contains non-hexadecimal characters") from exc
        if digest != digest.lower():
            raise ValueError("digest must use lowercase hexadecimal characters")
        return value

    @field_validator("logical_name")
    @classmethod
    def _safe_logical_name(cls, value: str) -> str:
        path = Path(value)
        if not value or path.is_absolute() or ".." in path.parts:
            raise ValueError("logical_name must be a safe relative artifact path")
        return value


class ResultErrorV1(BaseModel):
    """Typed failure information independent of provider-specific wording."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: ResultErrorKind
    message: str
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class ToolCallContextV1(BaseModel):
    """Explicit run/node context supplied at a tool-call boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str = ""
    node_id: str | None = None
    phase: str | None = None
    selection_reason: str = ""


class ResultProvenanceV1(BaseModel):
    """Identity and timing recorded for one normalized tool result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_ref: str = Field(min_length=1)
    run_id: str = ""
    node_id: str | None = None
    phase: str | None = None
    selection_reason: str = ""
    started_at: str = Field(min_length=1)
    completed_at: str | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    response_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)

    @field_validator("response_digest")
    @classmethod
    def _valid_response_digest(cls, value: str) -> str:
        ResultArtifactV1._valid_digest(value)
        return value


class ResultEnvelopeV1(BaseModel):
    """Bounded, provider-neutral result returned by ARI's typed dispatch API."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["ari.result-envelope/v1"] = RESULT_ENVELOPE_V1
    status: Literal["ok", "error", "submitted", "running", "cancelled"]
    content: str = ""
    content_truncated: bool = False
    structured_content: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[ResultArtifactV1] = Field(default_factory=list)
    error: ResultErrorV1 | None = None
    provenance: ResultProvenanceV1

    @model_validator(mode="after")
    def _consistent_status(self) -> "ResultEnvelopeV1":
        if self.status == "error" and self.error is None:
            raise ValueError("status=error requires error details")
        if self.status != "error" and self.error is not None:
            raise ValueError("error details require status=error")
        if self.content_truncated and not any(
            artifact.logical_role == RAW_RESULT_ROLE for artifact in self.artifacts
        ):
            raise ValueError("truncated content requires a raw-result artifact")
        return self

    def raw_result_artifact(self) -> ResultArtifactV1 | None:
        """Return the raw-result artifact descriptor, when externalized."""

        return next(
            (
                artifact
                for artifact in self.artifacts
                if artifact.logical_role == RAW_RESULT_ROLE
            ),
            None,
        )

    def materialize_content(self, store: ArtifactStore | None = None) -> str:
        """Recover the complete raw content and verify its content digest."""

        artifact = self.raw_result_artifact()
        if artifact is None:
            return self.content
        if store is None:
            raise ResultArtifactIntegrityError(
                "artifact store is required to materialize externalized content"
            )
        path = store.get(artifact.logical_name)
        try:
            payload = path.read_bytes()
        except OSError as exc:
            raise ResultArtifactIntegrityError(
                f"cannot read result artifact {artifact.logical_name}: {exc}"
            ) from exc
        actual = _sha256(payload)
        if actual != artifact.digest:
            raise ResultArtifactIntegrityError(
                f"result artifact digest mismatch: expected {artifact.digest}, got {actual}"
            )
        if len(payload) != artifact.size:
            raise ResultArtifactIntegrityError(
                f"result artifact size mismatch: expected {artifact.size}, got {len(payload)}"
            )
        try:
            return payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ResultArtifactIntegrityError(
                f"result artifact is not valid UTF-8: {artifact.logical_name}"
            ) from exc

    def to_legacy(self, store: ArtifactStore | None = None) -> dict[str, str]:
        """Losslessly project back to the historical MCPClient dictionary shape."""

        if self.error is not None and self.error.kind != "tool":
            return {"error": self.error.message}
        try:
            content = self.materialize_content(store)
        except ResultArtifactIntegrityError as exc:
            return {"error": str(exc)}
        if not content and self.structured_content:
            content = json.dumps(self.structured_content, ensure_ascii=False)
        return {"result": content}


class ResultEnvelopeNormalizer:
    """Normalize legacy/MCP responses and externalize large raw content."""

    def __init__(
        self,
        artifact_store: ArtifactStore | None = None,
        *,
        inline_limit: int = DEFAULT_INLINE_RESULT_LIMIT,
    ) -> None:
        if inline_limit <= 0:
            raise ValueError("inline_limit must be positive")
        self.artifact_store = artifact_store
        self.inline_limit = inline_limit

    def normalize_legacy(
        self,
        response: dict[str, Any],
        *,
        tool_ref: str,
        context: ToolCallContextV1 | None = None,
        started_at: str | None = None,
        completed_at: str | None = None,
    ) -> ResultEnvelopeV1:
        """Normalize one historical ``result``/``error`` response dictionary."""

        context = context or ToolCallContextV1()
        started_at = started_at or utc_now_iso()
        completed_at = completed_at or utc_now_iso()

        if not isinstance(response, dict) or not (
            {"result", "error"} & response.keys()
        ):
            return self.error(
                tool_ref=tool_ref,
                kind="protocol",
                message="MCP response must contain a result or error field",
                retryable=True,
                context=context,
                started_at=started_at,
                completed_at=completed_at,
            )

        if "error" in response and "result" not in response:
            message = str(response.get("error") or "unknown MCP transport error")
            raw_kind = str(response.get("_error_kind") or "transport")
            if raw_kind not in {
                "transport",
                "protocol",
                "timeout",
                "cancelled",
                "admission",
                "artifact-integrity",
                "unknown",
            }:
                raw_kind = "unknown"
            return self.error(
                tool_ref=tool_ref,
                kind=cast(ResultErrorKind, raw_kind),
                message=message,
                retryable=bool(response.get("_retryable", False)),
                context=context,
                started_at=started_at,
                completed_at=completed_at,
            )

        raw = response.get("result", "")
        if not isinstance(raw, str):
            raw = json.dumps(raw, ensure_ascii=False, default=str)
        structured = response.get("_structured_content")
        parsed = _parse_json(raw)
        if structured is None:
            structured = parsed
        structured_dict = _structured_dict(structured)

        is_tool_error = bool(response.get("_mcp_is_error", False)) or (
            isinstance(parsed, dict) and "error" in parsed
        )
        status = _result_status(structured_dict, is_tool_error)
        error = None
        if is_tool_error:
            error = ResultErrorV1(
                kind="tool",
                message=_tool_error_message(parsed, raw),
                retryable=False,
            )

        payload = raw.encode("utf-8")
        response_digest = _sha256(payload)
        content = raw
        content_truncated = False
        artifacts: list[ResultArtifactV1] = []
        if len(raw) > self.inline_limit and self.artifact_store is not None:
            artifact = self._put_raw_result(payload, parsed is not None)
            artifacts.append(artifact)
            content = _bounded_preview(raw, self.inline_limit)
            content_truncated = True
            # The complete structured value may be as large as the raw response;
            # the content-addressed artifact remains the lossless authority.
            structured_dict = {}

        provenance = _provenance(
            tool_ref=tool_ref,
            context=context,
            started_at=started_at,
            completed_at=completed_at,
            response_digest=response_digest,
        )
        return ResultEnvelopeV1(
            status=status,
            content=content,
            content_truncated=content_truncated,
            structured_content=structured_dict,
            artifacts=artifacts,
            error=error,
            provenance=provenance,
        )

    def error(
        self,
        *,
        tool_ref: str,
        kind: ResultErrorKind,
        message: str,
        retryable: bool,
        context: ToolCallContextV1 | None = None,
        started_at: str | None = None,
        completed_at: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> ResultEnvelopeV1:
        """Build a typed dispatch/transport failure envelope."""

        context = context or ToolCallContextV1()
        started_at = started_at or utc_now_iso()
        completed_at = completed_at or utc_now_iso()
        digest = _sha256(message.encode("utf-8"))
        return ResultEnvelopeV1(
            status="error",
            content="",
            error=ResultErrorV1(
                kind=kind,
                message=message,
                retryable=retryable,
                details=details or {},
            ),
            provenance=_provenance(
                tool_ref=tool_ref,
                context=context,
                started_at=started_at,
                completed_at=completed_at,
                response_digest=digest,
            ),
        )

    def _put_raw_result(self, payload: bytes, is_json: bool) -> ResultArtifactV1:
        assert self.artifact_store is not None
        digest = _sha256(payload)
        hex_digest = digest.removeprefix("sha256:")
        suffix = "json" if is_json else "txt"
        logical_name = (
            f"artifacts/mcp-results/sha256/{hex_digest[:2]}/{hex_digest}.{suffix}"
        )
        if self.artifact_store.exists(logical_name):
            existing = self.artifact_store.get(logical_name).read_bytes()
            if existing != payload:
                raise ResultArtifactIntegrityError(
                    f"content-address collision at {logical_name}"
                )
        else:
            self.artifact_store.put(logical_name, payload)
        return ResultArtifactV1(
            digest=digest,
            media_type="application/json" if is_json else "text/plain",
            size=len(payload),
            logical_role=RAW_RESULT_ROLE,
            logical_name=logical_name,
        )


def utc_now_iso() -> str:
    """Return an RFC 3339 UTC timestamp with an explicit ``Z`` suffix."""

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_json(raw: str) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def _structured_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    return {"value": value}


def _result_status(
    structured: dict[str, Any], is_tool_error: bool
) -> Literal["ok", "error", "submitted", "running", "cancelled"]:
    if is_tool_error:
        return "error"
    value = str(structured.get("status", "")).lower()
    if value in {"submitted", "running", "cancelled"}:
        return value  # type: ignore[return-value]
    return "ok"


def _tool_error_message(parsed: Any, raw: str) -> str:
    if isinstance(parsed, dict) and "error" in parsed:
        error = parsed["error"]
        return (
            error if isinstance(error, str) else json.dumps(error, ensure_ascii=False)
        )
    return raw or "MCP tool reported an error"


def _bounded_preview(raw: str, limit: int) -> str:
    suffix = "… [content externalized]"
    if len(suffix) >= limit:
        return suffix[:limit]
    suffix = "\n" + suffix
    head_length = max(0, limit - len(suffix))
    return raw[:head_length] + suffix


def _sha256(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _provenance(
    *,
    tool_ref: str,
    context: ToolCallContextV1,
    started_at: str,
    completed_at: str,
    response_digest: str,
) -> ResultProvenanceV1:
    duration_ms = None
    try:
        started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        completed = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
        duration_ms = max(0, int((completed - started).total_seconds() * 1_000))
    except (TypeError, ValueError):
        pass
    return ResultProvenanceV1(
        tool_ref=tool_ref,
        run_id=context.run_id,
        node_id=context.node_id,
        phase=context.phase,
        selection_reason=context.selection_reason,
        started_at=started_at,
        completed_at=completed_at,
        duration_ms=duration_ms,
        response_digest=response_digest,
    )


__all__ = [
    "ARTIFACT_REF_V1",
    "DEFAULT_INLINE_RESULT_LIMIT",
    "RAW_RESULT_ROLE",
    "RESULT_ENVELOPE_V1",
    "SHA256_DIGEST_PATTERN",
    "ResultArtifactIntegrityError",
    "ResultArtifactV1",
    "ResultEnvelopeNormalizer",
    "ResultEnvelopeV1",
    "ResultErrorKind",
    "ResultErrorV1",
    "ResultProvenanceV1",
    "ToolCallContextV1",
    "utc_now_iso",
]
