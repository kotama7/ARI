"""In-process realtime event bus for ``GET /api/v1/events/stream``
(gui_refresh Wave 2b, ADR-03 + plan 04 §Realtime event contract).

Events are notifications/invalidations, never a source of truth: on
reconnect a client replays via ``Last-Event-ID`` **and** refetches the
snapshot resource. Each event carries the frozen plan-04 contract shape::

    {"event_id": "<monotonic int as str>", "run_id": ..., "topic": "run"|"tree",
     "revision": <per-(topic, run_id) counter>, "occurred_at": "<UTC ISO>",
     "kind": "resource.changed", "resource": "/api/v1/runs/{run_id}/...",
     "payload": {}}

Storage is an append-only ring buffer (``deque(maxlen=1000)``) guarded by a
single :class:`threading.Condition`; :func:`publish` is thread-safe and
notifies blocked subscribers. :func:`subscribe` yields matching events (and
``None`` heartbeat ticks on wait timeout); :func:`stream_events` frames them
as SSE onto a ``wfile``, copying the working chunked-response pattern of
``GET /api/logs`` / ``GET /api/paperbench/run/{job_id}/logs`` (heartbeat
comments, bounded stream window, ``BrokenPipeError`` swallowed on client
disconnect).

Publication hooks live in ``state_sync._watcher_thread`` (topic ``tree``,
mirroring the legacy WebSocket broadcast — ADR-03 dual-running parity) and
``checkpoint_lifecycle._api_switch_checkpoint`` (topic ``run``); both import
this module lazily so simple_bfts / no-GUI paths never load ``viz.v1``.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Iterator

log = logging.getLogger(__name__)

# Frozen Wave 2b topic vocabulary (plan 04 lists run/tree/logs/artifacts/
# config/rqgm as the full starting set; this wave publishes the first two).
TOPICS = ("run", "tree")

# Default invalidated resource per topic (plan 04: `resource` names the
# /api/v1 snapshot the client should refetch).
_DEFAULT_RESOURCES = {
    "tree": "/api/v1/runs/{run_id}/tree",
    "run": "/api/v1/runs/{run_id}/summary",
}

BUFFER_MAXLEN = 1000

# SSE stream policy — mirrors the /api/paperbench logs stream: 15 s heartbeat
# comments keep proxies from dropping the idle connection, and a bounded
# window stops a stuck client from pinning a ThreadingHTTPServer worker
# forever (the browser reconnects with Last-Event-ID).
HEARTBEAT_S = 15.0
MAX_STREAM_S = 300.0

_cond = threading.Condition()
_buffer: deque = deque(maxlen=BUFFER_MAXLEN)
_next_id = 1
_revisions: dict = {}  # (topic, run_id) -> last published revision
# MN-9 (task 09 Wave 5b): live stream_events consumers, for the bounded
# GET /api/v1/diagnostics sse.subscribers scalar (ari/viz/health.py).
_subscribers = 0


def bus_stats() -> dict:
    """Bounded bus scalars for ``GET /api/v1/diagnostics`` (MN-9): live SSE
    subscriber count, ring-buffer length, and the last published event id
    (0 when nothing has been published in this process). Counts only —
    never event payloads."""
    with _cond:
        return {
            "subscribers": _subscribers,
            "buffer_len": len(_buffer),
            "last_event_id": _next_id - 1,
        }


def _parse_event_id(value) -> int:
    """``Last-Event-ID`` header value → int cursor (0 when absent/garbage)."""
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0


def _matches(event: dict, run_id, topics) -> bool:
    if run_id and event["run_id"] != run_id:
        return False
    if topics and event["topic"] not in topics:
        return False
    return True


def publish(topic: str, run_id: str, *, resource: str | None = None,
            payload: dict | None = None) -> dict:
    """Append one ``resource.changed`` event to the ring buffer (thread-safe).

    Returns the published event dict. ``event_id`` is a process-lifetime
    monotonic integer serialized as a string (the SSE ``id:`` field);
    ``revision`` counts per ``(topic, run_id)`` so a client can detect
    missed invalidations for one resource.
    """
    global _next_id
    if topic not in TOPICS:
        raise ValueError(f"unknown event topic: {topic!r} (choose from {TOPICS})")
    with _cond:
        event_id = _next_id
        _next_id += 1
        key = (topic, run_id)
        revision = _revisions.get(key, 0) + 1
        _revisions[key] = revision
        event = {
            "event_id": str(event_id),
            "run_id": run_id,
            "topic": topic,
            "revision": revision,
            "occurred_at": datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "kind": "resource.changed",
            "resource": resource
            or _DEFAULT_RESOURCES[topic].format(run_id=run_id),
            "payload": dict(payload or {}),
        }
        _buffer.append(event)
        _cond.notify_all()
    return event


def replay_since(last_event_id=None, *, run_id: str | None = None,
                 topics=None) -> list:
    """Buffered events with id > ``last_event_id``, oldest first, filtered.

    Events already evicted from the ring are silently gone — the client's
    snapshot refetch covers the gap (plan 04: events are invalidations,
    not a source of truth).
    """
    cursor = _parse_event_id(last_event_id)
    with _cond:
        return [
            e for e in _buffer
            if int(e["event_id"]) > cursor and _matches(e, run_id, topics)
        ]


def subscribe(*, last_event_id=None, run_id: str | None = None,
              topics=None, heartbeat_s: float = HEARTBEAT_S) -> Iterator:
    """Yield matching events forever; ``None`` marks a heartbeat tick.

    First replays the ring buffer past ``last_event_id`` (SSE resume), then
    blocks on the bus Condition. A wait that times out after *heartbeat_s*
    (or wakes to only filtered-out events) yields ``None`` so the consumer
    can emit a keep-alive comment and check its stream deadline.
    """
    cursor = _parse_event_id(last_event_id)
    while True:
        with _cond:
            pending = [e for e in _buffer if int(e["event_id"]) > cursor]
            if not pending:
                _cond.wait(timeout=heartbeat_s)
                pending = [e for e in _buffer if int(e["event_id"]) > cursor]
            if pending:
                cursor = int(pending[-1]["event_id"])
        matched = [e for e in pending if _matches(e, run_id, topics)]
        if matched:
            for e in matched:
                yield e
        else:
            yield None


def stream_events(wfile, *, run_id: str | None = None, topics=None,
                  last_event_id=None, heartbeat_s: float = HEARTBEAT_S,
                  max_stream_s: float = MAX_STREAM_S) -> None:
    """Write the ``/api/v1/events/stream`` SSE body onto *wfile*.

    Frame order: ``: connected`` comment + ``retry: 5000``, then the
    Last-Event-ID replay, then live events as
    ``id:/event: resource.changed/data:`` frames with ``: heartbeat``
    comments on idle ticks. The bounded window ends with a
    ``: stream-timeout`` comment (client reconnects with Last-Event-ID);
    client disconnect (``BrokenPipeError``/``ConnectionResetError``) ends
    the stream cleanly, exactly like ``/api/logs``.
    """
    global _subscribers
    with _cond:
        _subscribers += 1  # MN-9: diagnostics sse.subscribers scalar
    try:
        wfile.write(b": connected\n\n")
        wfile.write(b"retry: 5000\n\n")
        wfile.flush()
        deadline = time.time() + max_stream_s
        for event in subscribe(
            last_event_id=last_event_id,
            run_id=run_id,
            topics=topics,
            heartbeat_s=heartbeat_s,
        ):
            if event is None:
                # Deadline is checked on idle ticks only (the paperbench
                # stream likewise checks once per poll loop): an active
                # stream is never cut mid-replay.
                if time.time() > deadline:
                    wfile.write(b": stream-timeout - reconnect\n\n")
                    wfile.flush()
                    break
                wfile.write(b": heartbeat\n\n")
            else:
                data = json.dumps(event, ensure_ascii=False)
                wfile.write(
                    f"id: {event['event_id']}\nevent: {event['kind']}\n"
                    f"data: {data}\n\n".encode("utf-8")
                )
            wfile.flush()
    except (BrokenPipeError, ConnectionResetError):
        pass
    finally:
        with _cond:
            _subscribers -= 1


def _reset_for_tests() -> None:
    """Clear the bus (buffer, id counter, revisions) — test isolation only."""
    global _next_id
    with _cond:
        _buffer.clear()
        _revisions.clear()
        _next_id = 1
        _cond.notify_all()
