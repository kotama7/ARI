"""Server-issued confirmation challenges for dangerous operations
(gui_refresh task 09 Wave 5a — RR-P0-6 / RR-P0-9 / MN-6).

Plan 09 §Dangerous operations: destructive endpoints must not fire on a
client-side ``window.confirm`` (or a hardcoded ``confirmed: true``) alone.
The server issues a short-lived challenge **bound to one action + target**;
the destructive endpoint then requires that unexpired, unused challenge id
back in its body. This turns "the client said it was sure" into "the server
recently told THIS client what exactly would be destroyed, and the client
echoed that specific grant back".

Protocol
--------

``POST /api/v1/challenges`` with ``{"action": ..., "target": ...}`` where
``action`` is one of :data:`CHALLENGE_ACTIONS` and ``target`` names what
will be destroyed (the checkpoint path for ``delete-checkpoint``; the
literal ``"*"`` for the process-wide ``stop-all`` / ``gpu-monitor-stop``).
The response is :class:`ari.viz.v1.dto.ChallengeV1`: ``challenge_id``
(``chg-<12 hex>``), the echoed ``action``/``target`` (the UI's impact
preview), ``expires_at`` (display-only wall clock) and ``ttl_seconds``.

Enforcement (the legacy endpoints changed by MN-6):

* ``POST /api/delete-checkpoint`` — challenge ``(delete-checkpoint, <path>)``;
* ``POST /api/stop``             — challenge ``(stop-all, "*")``;
* ``POST /api/gpu-monitor`` ``action=stop`` — challenge
  ``(gpu-monitor-stop, "*")``.

Each requires body key ``challenge_id``; anything else answers the frozen
refusal ``{"ok": false, "error": "confirmation challenge required or
invalid"}`` with HTTP **428** (Precondition Required) and performs no
destructive work. Challenges are single-use, expire after
:data:`CHALLENGE_TTL_SECONDS` (enforced on ``time.monotonic()`` so wall
clock jumps cannot extend a grant), and live in a bounded in-memory deque
(cap :data:`CHALLENGE_STORE_CAP`; oldest evicted first — a GUI restart
clears them all, which is safe: the client just asks for a fresh one).

Issuance and consumption are audit-logged to the active checkpoint's
``viz_access.jsonl`` (same file the HTTP access log uses) as additive
``{"event": "challenge_*"}`` lines.

``ARI_GUI_CHALLENGES`` (env kill-switch, ADR-07 register):

* owner: gui_refresh task 09 (security, performance, and operations);
* default: unset/on — the three endpoints above REQUIRE a challenge;
* rollback: ``ARI_GUI_CHALLENGES=0`` restores the legacy direct behavior
  (no challenge needed; issuance stays available so a two-step client
  keeps working either way);
* removal gate: G5 — reviewed with the deployment trust-mode decision
  (ADR-05); until then it is the documented escape hatch for automation
  that scripted the legacy single-shot endpoints.
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timedelta, timezone

from .dto import ChallengeV1
from .errors import error_response

# The only actions a challenge can ever be minted for (plan 09 §Dangerous
# operations: delete / stop are the risk-bearing legacy operations).
CHALLENGE_ACTIONS: tuple[str, ...] = (
    "delete-checkpoint",
    "stop-all",
    "gpu-monitor-stop",
)

CHALLENGE_TTL_SECONDS = 60
CHALLENGE_STORE_CAP = 100

# Frozen refusal payload (MN-6) — the legacy endpoints return exactly this
# (plus HTTP 428 via the _status pop convention) when the challenge is
# missing, unknown, expired, already used, or bound to another action/target.
REFUSAL_ERROR = "confirmation challenge required or invalid"

# Bounded in-memory store: records are dicts {challenge_id, action, target,
# deadline (monotonic), used (bool)}. A deque(maxlen) gives the cap-100
# oldest-first eviction for free; lookups scan at most 100 entries.
_challenges: deque = deque(maxlen=CHALLENGE_STORE_CAP)
_lock = threading.Lock()


def challenges_enabled() -> bool:
    """MN-6 kill-switch: False only when ``ARI_GUI_CHALLENGES`` is 0/false."""
    return os.environ.get("ARI_GUI_CHALLENGES", "").strip().lower() not in (
        "0",
        "false",
    )


def _audit(event: str, **fields) -> None:
    """Best-effort audit line into the active checkpoint's viz_access.jsonl.

    Reuses ``routes._write_access_log`` (same file + lock as the HTTP access
    log) so challenge grants/consumptions interleave with the request lines
    they authorize. No active checkpoint -> nothing to write (same posture
    as ``_Handler.log_request``). Never raises.
    """
    try:
        from pathlib import Path

        from .. import state as _st
        from ..routes import _write_access_log

        ckpt = _st._checkpoint_dir
        if ckpt is None:
            return
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "event": event,
            **fields,
        }
        _write_access_log(Path(ckpt), entry)
    except Exception:
        pass


def _bad(message: str) -> dict:
    return error_response("invalid_request", message, request_id="", status=400)


def issue_challenge(body: dict) -> dict:
    """POST /api/v1/challenges — mint a single-use confirmation challenge.

    Issuance itself is harmless (a challenge grants nothing on its own), so
    it stays available even under the kill-switch — a two-step client works
    identically whether enforcement is on or off.
    """
    unknown = sorted(set(body) - {"action", "target"})
    if unknown:
        return _bad(f"unknown request body keys: {unknown}")
    action = body.get("action")
    if action not in CHALLENGE_ACTIONS:
        return _bad(
            f'"action" must be one of {list(CHALLENGE_ACTIONS)} (got {action!r})'
        )
    target = body.get("target")
    if not isinstance(target, str) or not target.strip():
        return _bad('"target" must be a non-empty string')
    target = target.strip()

    challenge_id = "chg-" + uuid.uuid4().hex[:12]
    record = {
        "challenge_id": challenge_id,
        "action": action,
        "target": target,
        "deadline": time.monotonic() + CHALLENGE_TTL_SECONDS,
        "used": False,
    }
    with _lock:
        _challenges.append(record)
    expires_at = (
        datetime.now(timezone.utc) + timedelta(seconds=CHALLENGE_TTL_SECONDS)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    _audit(
        "challenge_issued",
        challenge_id=challenge_id,
        action=action,
        target=target,
        ttl_seconds=CHALLENGE_TTL_SECONDS,
    )
    return ChallengeV1(
        challenge_id=challenge_id,
        action=action,
        target=target,
        expires_at=expires_at,
        ttl_seconds=CHALLENGE_TTL_SECONDS,
    ).model_dump()


def consume_challenge(challenge_id: str, action: str, target: str) -> str | None:
    """Atomically consume one challenge; ``None`` on success, else a reason.

    The reason string is for the audit log only — the wire refusal is always
    the frozen :data:`REFUSAL_ERROR` (no oracle for probing which part of a
    guessed id/binding was wrong).
    """
    with _lock:
        for record in _challenges:
            if record["challenge_id"] != challenge_id:
                continue
            if record["used"]:
                return "already used"
            if time.monotonic() > record["deadline"]:
                return "expired"
            if record["action"] != action or record["target"] != target:
                return "action/target mismatch"
            record["used"] = True
            return None
    return "unknown challenge_id"


def require_challenge(action: str, target: str, data: dict) -> dict | None:
    """Gate a legacy destructive handler (MN-6).

    Returns ``None`` when the operation may proceed (valid single-use
    challenge consumed, or the kill-switch disabled enforcement); otherwise
    the frozen 428 refusal dict for the caller to return as-is.
    """
    if not challenges_enabled():
        return None
    challenge_id = data.get("challenge_id") if isinstance(data, dict) else None
    if not isinstance(challenge_id, str) or not challenge_id:
        _audit("challenge_refused", action=action, target=target,
               reason="missing challenge_id")
        return {"ok": False, "error": REFUSAL_ERROR, "_status": 428}
    reason = consume_challenge(challenge_id, action, target)
    if reason is not None:
        _audit("challenge_refused", challenge_id=challenge_id, action=action,
               target=target, reason=reason)
        return {"ok": False, "error": REFUSAL_ERROR, "_status": 428}
    _audit("challenge_consumed", challenge_id=challenge_id, action=action,
           target=target)
    return None
