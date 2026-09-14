"""Typed error envelope for ``/api/v1`` (gui_refresh Wave 2a, ADR-02).

Every v1 error is the same JSON shape::

    {"error": {"code": ..., "message": ..., "details": ...,
               "request_id": ..., "retryable": ...}}

plus a transport-only ``"_status"`` key consumed (and popped) by the
``routes.py`` convention ``self._json(r, status=r.pop("_status", 200))`` —
the exact mechanism the legacy launch/run-stage handlers already use, so the
envelope travels through the stdlib server without new HTTP plumbing.

``request_id`` correlation is owned by :mod:`ari.viz.v1.router`: builders
below may pass a placeholder (``""``) and the router overwrites it with the
per-request ``req-<12 hex>`` id before the response is serialized.
"""

from __future__ import annotations

from typing import Any

# Frozen v1 error code vocabulary: additive only — a code is never removed
# or repurposed, so a client can switch on one forever.
# Wave 3b (task 05 config CRUD) added the two optimistic-concurrency codes:
# 'revision_conflict' (409, If-Match mismatch) and 'already_exists' (409,
# create-only POST hit an existing document).
ERROR_CODES = (
    "not_found",
    "invalid_request",
    "internal",
    "revision_conflict",
    "already_exists",
)


def error_response(
    code: str,
    message: str,
    *,
    details: Any = None,
    request_id: str,
    retryable: bool = False,
    status: int,
) -> dict:
    """Build the typed v1 error envelope carrying its HTTP status.

    ``status`` rides in ``"_status"`` so ``routes.py`` can pop it into the
    real HTTP status line; the wire payload is the ``{"error": {...}}`` dict.
    """
    if code not in ERROR_CODES:
        raise ValueError(f"unknown v1 error code: {code!r} (choose from {ERROR_CODES})")
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details,
            "request_id": request_id,
            "retryable": retryable,
        },
        "_status": status,
    }
