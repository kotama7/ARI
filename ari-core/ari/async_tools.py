"""Provider-neutral contracts for asynchronous Skill execution.

The manifest-side lifecycle names semantic capabilities.  At admission time the
MCP control plane resolves those capabilities to immutable tool references and
places them in :class:`AsyncToolHandleV1`.  A serialized handle therefore never
depends on a provider's bare tool names or on a mutable catalog lookup.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ASYNC_TOOL_HANDLE_V1 = "ari.async-tool-handle/v1"

_FIELD_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_CAPABILITY_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")

AsyncStateV1 = Literal[
    "submitted",
    "running",
    "succeeded",
    "failed",
    "cancelled",
    "unknown",
]


class TimeoutBudgetV1(BaseModel):
    """A caller-controlled timeout argument explicitly admitted by a manifest."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    argument: str
    unit: Literal["seconds", "minutes", "hours"] = "seconds"
    overhead_seconds: int = Field(default=0, ge=0, le=2_678_400)
    maximum_seconds: int = Field(gt=0, le=2_678_400)

    @field_validator("argument")
    @classmethod
    def _valid_argument(cls, value: str) -> str:
        if not _FIELD_RE.fullmatch(value):
            raise ValueError("timeout budget argument must be an identifier")
        return value

    @model_validator(mode="after")
    def _valid_limit(self) -> "TimeoutBudgetV1":
        if self.maximum_seconds <= self.overhead_seconds:
            raise ValueError("maximum_seconds must exceed overhead_seconds")
        return self

    def requested_seconds(self, arguments: dict[str, Any]) -> int | None:
        """Return the bounded outer timeout requested by one call, if present."""

        raw = arguments.get(self.argument)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)) or raw <= 0:
            return None
        multiplier = {"seconds": 1, "minutes": 60, "hours": 3_600}[self.unit]
        requested = int(raw * multiplier) + self.overhead_seconds
        return min(requested, self.maximum_seconds)


class AsyncOperationV1(BaseModel):
    """Manifest reference to one operation in an async lifecycle."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    capability_ref: str
    handle_argument: str = "handle_id"

    @field_validator("capability_ref")
    @classmethod
    def _valid_capability_ref(cls, value: str) -> str:
        value = value.strip()
        if not _CAPABILITY_RE.fullmatch(value):
            raise ValueError("capability_ref must be a lowercase dotted identifier")
        return value

    @field_validator("handle_argument")
    @classmethod
    def _valid_handle_argument(cls, value: str) -> str:
        if not _FIELD_RE.fullmatch(value):
            raise ValueError("handle_argument must be an identifier")
        return value


class AsyncStateMapV1(BaseModel):
    """Case-insensitive provider state mapping used while polling a handle."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    submitted_states: list[str] = Field(
        default_factory=lambda: ["submitted", "queued", "pending", "started"]
    )
    running_states: list[str] = Field(default_factory=lambda: ["running", "active"])
    succeeded_states: list[str] = Field(
        default_factory=lambda: ["succeeded", "success", "completed", "complete", "done", "ok"]
    )
    failed_states: list[str] = Field(
        default_factory=lambda: ["failed", "error", "timed_out", "timeout"]
    )
    cancelled_states: list[str] = Field(
        default_factory=lambda: ["cancelled", "canceled"]
    )

    @field_validator(
        "submitted_states",
        "running_states",
        "succeeded_states",
        "failed_states",
        "cancelled_states",
    )
    @classmethod
    def _valid_states(cls, values: list[str]) -> list[str]:
        normalized = [str(value).strip() for value in values]
        if any(not value for value in normalized):
            raise ValueError("async state names cannot be empty")
        folded = [value.casefold() for value in normalized]
        if len(folded) != len(set(folded)):
            raise ValueError("async state names must be unique")
        return normalized

    @model_validator(mode="after")
    def _disjoint_states(self) -> "AsyncStateMapV1":
        owners: dict[str, str] = {}
        for field_name in (
            "submitted_states",
            "running_states",
            "succeeded_states",
            "failed_states",
            "cancelled_states",
        ):
            for state in getattr(self, field_name):
                key = state.casefold()
                if key in owners:
                    raise ValueError(
                        f"async state {state!r} occurs in {owners[key]} and {field_name}"
                    )
                owners[key] = field_name
        return self

    def classify(self, value: Any) -> AsyncStateV1:
        """Map one provider value to ARI's state machine without guessing."""

        key = str(value).strip().casefold()
        for result, field_name in (
            ("submitted", "submitted_states"),
            ("running", "running_states"),
            ("succeeded", "succeeded_states"),
            ("failed", "failed_states"),
            ("cancelled", "cancelled_states"),
        ):
            if key in {state.casefold() for state in getattr(self, field_name)}:
                return result  # type: ignore[return-value]
        return "unknown"


class AsyncLifecycleV1(BaseModel):
    """Manifest-declared submit/status/result/cancel protocol."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    handle_field: str = "handle_id"
    state_field: str = "status"
    status: AsyncOperationV1
    result: AsyncOperationV1 | None = None
    cancel: AsyncOperationV1 | None = None
    states: AsyncStateMapV1 = Field(default_factory=AsyncStateMapV1)
    poll_interval_seconds: float = Field(default=5.0, ge=0.01, le=3_600)
    max_wait_seconds: int = Field(default=86_400, ge=1, le=2_678_400)

    @field_validator("handle_field", "state_field")
    @classmethod
    def _valid_field(cls, value: str) -> str:
        if not _FIELD_RE.fullmatch(value):
            raise ValueError("async handle/state fields must be identifiers")
        return value


class AsyncToolEndpointV1(BaseModel):
    """One immutable endpoint embedded in a runtime async handle."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_ref: str = Field(min_length=1)
    handle_argument: str

    @field_validator("handle_argument")
    @classmethod
    def _valid_handle_argument(cls, value: str) -> str:
        if not _FIELD_RE.fullmatch(value):
            raise ValueError("handle_argument must be an identifier")
        return value


class AsyncToolHandleV1(BaseModel):
    """Portable handle bound to immutable lifecycle tool references."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["ari.async-tool-handle/v1"] = ASYNC_TOOL_HANDLE_V1
    handle_id: str = Field(min_length=1, max_length=1_024)
    submission_tool_ref: str = Field(min_length=1)
    status: AsyncToolEndpointV1
    result: AsyncToolEndpointV1 | None = None
    cancel: AsyncToolEndpointV1 | None = None
    state_field: str
    states: AsyncStateMapV1
    poll_interval_seconds: float = Field(ge=0.01, le=3_600)
    max_wait_seconds: int = Field(ge=1, le=2_678_400)
    submitted_at: str = Field(min_length=1)

    @field_validator("state_field")
    @classmethod
    def _valid_state_field(cls, value: str) -> str:
        if not _FIELD_RE.fullmatch(value):
            raise ValueError("state_field must be an identifier")
        return value


__all__ = [
    "ASYNC_TOOL_HANDLE_V1",
    "AsyncLifecycleV1",
    "AsyncOperationV1",
    "AsyncStateMapV1",
    "AsyncStateV1",
    "AsyncToolEndpointV1",
    "AsyncToolHandleV1",
    "TimeoutBudgetV1",
]
