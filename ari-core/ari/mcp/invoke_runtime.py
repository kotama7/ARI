"""Retry, cancellation, and typed normalization for one admitted tool call."""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import time
from typing import Callable, Protocol

from ari.mcp.child_environment import ChildEnvironmentError
from ari.mcp.dispatch_support import MAX_RETRIES, RETRY_DELAY
from ari.result import (
    ResultArtifactIntegrityError,
    ResultEnvelopeNormalizer,
    ResultEnvelopeV1,
    ResultErrorKind,
    ToolCallContextV1,
    utc_now_iso,
)


class ToolCallConnection(Protocol):
    def call_tool(self, tool_name: str, args: dict, timeout: int) -> dict: ...

    def redact_text(self, value: str) -> str: ...


def _redact(connection: ToolCallConnection, message: str) -> str:
    redact = getattr(connection, "redact_text", None)
    return redact(message) if callable(redact) else message


def invoke_with_retries(
    *,
    connection: ToolCallConnection,
    reconnect: Callable[[ToolCallConnection], ToolCallConnection],
    tool_name: str,
    tool_ref: str,
    args: dict,
    timeout: int,
    context: ToolCallContextV1,
    normalizer: ResultEnvelopeNormalizer,
    started_at: str,
    logger: logging.Logger,
) -> ResultEnvelopeV1:
    """Invoke a provider and convert every transport outcome to one envelope."""

    last_error = ""
    last_kind: ResultErrorKind = "transport"
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = connection.call_tool(tool_name, args, timeout=timeout)
        except ChildEnvironmentError as exc:
            detail = _redact(connection, f"{type(exc).__name__}: {exc}".rstrip())
            return normalizer.error(
                tool_ref=tool_ref,
                kind="admission",
                message=f"Tool '{tool_name}' provider environment was refused. {detail}",
                retryable=False,
                context=context,
                started_at=started_at,
                completed_at=utc_now_iso(),
            )
        except (asyncio.CancelledError, concurrent.futures.CancelledError) as exc:
            detail = _redact(connection, f"{type(exc).__name__}: {exc}".rstrip())
            return normalizer.error(
                tool_ref=tool_ref,
                kind="cancelled",
                message=f"Tool '{tool_name}' was cancelled. {detail}",
                retryable=False,
                context=context,
                started_at=started_at,
                completed_at=utc_now_iso(),
            )
        except TimeoutError as exc:
            last_error = _redact(
                connection, f"{type(exc).__name__}: {exc}".rstrip()
            )
            last_kind = "timeout"
        except Exception as exc:
            last_error = _redact(
                connection, f"{type(exc).__name__}: {exc}".rstrip()
            )
            last_kind = "transport"
        else:
            try:
                return normalizer.normalize_legacy(
                    response,
                    tool_ref=tool_ref,
                    context=context,
                    started_at=started_at,
                    completed_at=utc_now_iso(),
                )
            except (ResultArtifactIntegrityError, OSError) as exc:
                return normalizer.error(
                    tool_ref=tool_ref,
                    kind="artifact-integrity",
                    message=str(exc),
                    retryable=False,
                    context=context,
                    started_at=started_at,
                    completed_at=utc_now_iso(),
                )

        logger.warning(
            "Tool '%s' attempt %d/%d failed: %s",
            tool_name,
            attempt,
            MAX_RETRIES,
            last_error,
        )
        try:
            connection = reconnect(connection)
        except Exception:
            pass
        if attempt < MAX_RETRIES:
            time.sleep(RETRY_DELAY * attempt)

    return normalizer.error(
        tool_ref=tool_ref,
        kind=last_kind,
        message=(
            f"Tool '{tool_name}' failed after {MAX_RETRIES} attempts. "
            f"Last: {last_error}"
        ),
        retryable=True,
        context=context,
        started_at=started_at,
        completed_at=utc_now_iso(),
    )


__all__ = ["ToolCallConnection", "invoke_with_retries"]
