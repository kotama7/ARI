"""gui_refresh Wave 5a (task 09) — RR-P0-6 / RR-P0-9 / MN-6: server-issued
confirmation challenges for dangerous operations.

Covers:

* ``POST /api/v1/challenges`` (``ari.viz.v1.challenges.issue_challenge`` via
  the v1 router): issuance shape (``chg-<12 hex>``, echoed action/target,
  ``expires_at``/``ttl_seconds``), body validation (unknown action, missing/
  empty target, unknown keys -> 400 envelope), deque cap 100 eviction;
* challenge consumption: single-use, monotonic expiry, action/target
  binding mismatch, unknown id;
* MN-6 enforcement on the legacy endpoints: ``POST /api/delete-checkpoint``
  and ``POST /api/stop`` and ``POST /api/gpu-monitor`` (action=stop) refuse
  with the frozen ``{"ok": False, "error": "confirmation challenge required
  or invalid"}`` + ``_status`` 428 payload and perform no destructive work;
* the happy path: issue -> delete a tmp checkpoint with the challenge;
* the ``ARI_GUI_CHALLENGES=0`` kill-switch restoring legacy direct calls;
* audit lines (``challenge_issued`` / ``challenge_consumed`` /
  ``challenge_refused``) appended to the active checkpoint's
  ``viz_access.jsonl``.

Register/announcement: risk_register.md rows RR-P0-6/RR-P0-9 (closed Wave
5a), migration_notes.md MN-6.
"""

from __future__ import annotations

import json
import re
import time
from unittest import mock

import pytest

from ari.viz import api_process
from ari.viz import state as _st
from ari.viz.checkpoint_lifecycle import _api_delete_checkpoint
from ari.viz.v1 import challenges as chg
from ari.viz.v1.router import dispatch


REFUSAL = {"ok": False, "error": "confirmation challenge required or invalid"}


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """Fresh challenge store per test; enforcement ON (env unset = default);
    no active checkpoint unless a test sets one."""
    monkeypatch.setattr(
        chg, "_challenges", type(chg._challenges)(maxlen=chg.CHALLENGE_STORE_CAP)
    )
    monkeypatch.delenv("ARI_GUI_CHALLENGES", raising=False)
    monkeypatch.setattr(_st, "_checkpoint_dir", None)
    monkeypatch.setattr(_st, "_last_proc", None, raising=False)
    monkeypatch.setattr(_st, "_gpu_monitor_proc", None, raising=False)


def _issue(action: str, target: str) -> dict:
    body = json.dumps({"action": action, "target": target}).encode()
    return dispatch("POST", "/api/v1/challenges", body=body)


# ──────────────────────────────────────────────────────────────────────
# Issuance (POST /api/v1/challenges)
# ──────────────────────────────────────────────────────────────────────

def test_issue_returns_bound_single_use_grant():
    r = _issue("delete-checkpoint", "/tmp/checkpoints/run1")
    assert re.fullmatch(r"chg-[0-9a-f]{12}", r["challenge_id"])
    assert r["action"] == "delete-checkpoint"
    assert r["target"] == "/tmp/checkpoints/run1"  # UI impact preview echo
    assert r["ttl_seconds"] == chg.CHALLENGE_TTL_SECONDS == 60
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", r["expires_at"])
    assert r["schema_version"] == 1
    assert r["request_id"].startswith("req-")


@pytest.mark.parametrize("action", ["stop-all", "gpu-monitor-stop"])
def test_issue_star_target_actions(action):
    r = _issue(action, "*")
    assert r["action"] == action and r["target"] == "*"


def test_issue_rejects_unknown_action():
    r = _issue("format-disk", "*")
    assert r["_status"] == 400
    assert r["error"]["code"] == "invalid_request"


def test_issue_rejects_missing_or_empty_target():
    for body in ({"action": "stop-all"}, {"action": "stop-all", "target": "  "}):
        r = dispatch("POST", "/api/v1/challenges", body=json.dumps(body).encode())
        assert r["_status"] == 400, body


def test_issue_rejects_unknown_body_keys():
    r = dispatch(
        "POST",
        "/api/v1/challenges",
        body=json.dumps({"action": "stop-all", "target": "*", "sudo": True}).encode(),
    )
    assert r["_status"] == 400


def test_store_cap_100_evicts_oldest():
    first = chg.issue_challenge({"action": "stop-all", "target": "*"})
    for _ in range(chg.CHALLENGE_STORE_CAP):
        chg.issue_challenge({"action": "stop-all", "target": "*"})
    assert len(chg._challenges) == chg.CHALLENGE_STORE_CAP
    assert (
        chg.consume_challenge(first["challenge_id"], "stop-all", "*")
        == "unknown challenge_id"
    )


# ──────────────────────────────────────────────────────────────────────
# Consumption: single-use / expiry / binding
# ──────────────────────────────────────────────────────────────────────

def test_consume_is_single_use():
    r = chg.issue_challenge({"action": "stop-all", "target": "*"})
    assert chg.consume_challenge(r["challenge_id"], "stop-all", "*") is None
    assert chg.consume_challenge(r["challenge_id"], "stop-all", "*") == "already used"


def test_consume_rejects_expired(monkeypatch):
    r = chg.issue_challenge({"action": "stop-all", "target": "*"})
    real = time.monotonic
    monkeypatch.setattr(
        chg.time, "monotonic", lambda: real() + chg.CHALLENGE_TTL_SECONDS + 1
    )
    assert chg.consume_challenge(r["challenge_id"], "stop-all", "*") == "expired"


def test_consume_rejects_action_and_target_mismatch():
    r = chg.issue_challenge(
        {"action": "delete-checkpoint", "target": "/tmp/checkpoints/a"}
    )
    cid = r["challenge_id"]
    assert chg.consume_challenge(cid, "stop-all", "/tmp/checkpoints/a") is not None
    assert (
        chg.consume_challenge(cid, "delete-checkpoint", "/tmp/checkpoints/b")
        is not None
    )
    # The failed attempts above never consumed it — the exact binding still works.
    assert chg.consume_challenge(cid, "delete-checkpoint", "/tmp/checkpoints/a") is None


def test_consume_rejects_unknown_id():
    assert chg.consume_challenge("chg-ffffffffffff", "stop-all", "*") is not None


# ──────────────────────────────────────────────────────────────────────
# MN-6 enforcement: legacy endpoints refuse without a valid challenge
# ──────────────────────────────────────────────────────────────────────

def _delete_body(path, **extra) -> bytes:
    return json.dumps({"path": str(path), **extra}).encode()


def test_delete_checkpoint_refuses_without_challenge(tmp_path):
    ckpt = tmp_path / "checkpoints" / "run1"
    ckpt.mkdir(parents=True)
    r = _api_delete_checkpoint(_delete_body(ckpt))
    assert r == {**REFUSAL, "_status": 428}
    assert ckpt.exists()  # nothing was deleted


def test_delete_checkpoint_refuses_wrong_target_challenge(tmp_path):
    ckpt = tmp_path / "checkpoints" / "run1"
    ckpt.mkdir(parents=True)
    other = chg.issue_challenge(
        {"action": "delete-checkpoint", "target": "/somewhere/else"}
    )
    r = _api_delete_checkpoint(
        _delete_body(ckpt, challenge_id=other["challenge_id"])
    )
    assert r["_status"] == 428
    assert ckpt.exists()


def test_delete_checkpoint_happy_path_with_challenge(tmp_path):
    ckpt = tmp_path / "checkpoints" / "20260101120000_run"
    ckpt.mkdir(parents=True)
    (ckpt / "tree.json").write_text("{}")
    grant = chg.issue_challenge(
        {"action": "delete-checkpoint", "target": str(ckpt)}
    )
    r = _api_delete_checkpoint(
        _delete_body(ckpt, challenge_id=grant["challenge_id"])
    )
    assert r.get("ok") is True
    assert not ckpt.exists()
    # Single-use: replaying the same grant is refused (nothing left to delete
    # anyway, but the challenge gate must trip first).
    ckpt.mkdir(parents=True)
    r2 = _api_delete_checkpoint(
        _delete_body(ckpt, challenge_id=grant["challenge_id"])
    )
    assert r2["_status"] == 428
    assert ckpt.exists()


def test_stop_refuses_without_challenge_and_touches_no_process(monkeypatch):
    proc = mock.MagicMock()
    proc.poll.return_value = None
    proc.pid = 4321
    monkeypatch.setattr(_st, "_last_proc", proc, raising=False)
    with mock.patch("os.killpg") as killpg, \
         mock.patch("subprocess.run") as run:
        r = api_process._api_stop(b"{}")
    assert r == {**REFUSAL, "_status": 428}
    killpg.assert_not_called()
    run.assert_not_called()
    proc.terminate.assert_not_called()


def test_stop_accepts_valid_challenge(monkeypatch):
    monkeypatch.setattr(_st, "_last_proc", None, raising=False)
    monkeypatch.setattr(_st, "_checkpoint_dir", None)
    grant = chg.issue_challenge({"action": "stop-all", "target": "*"})
    fake_done = mock.MagicMock(returncode=1, stdout="")
    with mock.patch("subprocess.run", return_value=fake_done), \
         mock.patch("time.sleep"):
        r = api_process._api_stop(
            json.dumps({"challenge_id": grant["challenge_id"]}).encode()
        )
    assert r["ok"] is True
    assert r["stopped"] is False  # nothing was running


def test_gpu_monitor_stop_refuses_without_challenge(monkeypatch):
    proc = mock.MagicMock()
    proc.poll.return_value = None
    monkeypatch.setattr(_st, "_gpu_monitor_proc", proc, raising=False)
    r = api_process._api_gpu_monitor_action(b'{"action": "stop"}')
    assert r == {**REFUSAL, "_status": 428}
    proc.terminate.assert_not_called()


def test_gpu_monitor_stop_accepts_valid_challenge(monkeypatch):
    monkeypatch.setattr(_st, "_gpu_monitor_proc", None, raising=False)
    grant = chg.issue_challenge({"action": "gpu-monitor-stop", "target": "*"})
    r = api_process._api_gpu_monitor_action(
        json.dumps({"action": "stop", "challenge_id": grant["challenge_id"]}).encode()
    )
    assert r == {"ok": True}


def test_gpu_monitor_start_unaffected_by_challenge_gate():
    """The start action keeps its legacy needs_confirm handshake."""
    r = api_process._api_gpu_monitor_action(b'{"action": "start"}')
    assert r["ok"] is False and r["needs_confirm"] is True


# ──────────────────────────────────────────────────────────────────────
# Kill-switch (ARI_GUI_CHALLENGES=0) restores legacy direct behavior
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value", ["0", "false", " False "])
def test_kill_switch_disables_enforcement(monkeypatch, tmp_path, value):
    monkeypatch.setenv("ARI_GUI_CHALLENGES", value)
    assert chg.challenges_enabled() is False
    ckpt = tmp_path / "checkpoints" / "legacy"
    ckpt.mkdir(parents=True)
    r = _api_delete_checkpoint(_delete_body(ckpt))  # no challenge_id at all
    assert r.get("ok") is True
    assert not ckpt.exists()


def test_kill_switch_default_and_other_values_keep_enforcement(monkeypatch):
    assert chg.challenges_enabled() is True  # unset (fixture) = on
    monkeypatch.setenv("ARI_GUI_CHALLENGES", "1")
    assert chg.challenges_enabled() is True


def test_issuance_still_works_under_kill_switch(monkeypatch):
    """A two-step client keeps working when enforcement is off."""
    monkeypatch.setenv("ARI_GUI_CHALLENGES", "0")
    r = _issue("stop-all", "*")
    assert r["challenge_id"].startswith("chg-")


# ──────────────────────────────────────────────────────────────────────
# Audit lines in viz_access.jsonl
# ──────────────────────────────────────────────────────────────────────

def _audit_events(ckpt) -> list[dict]:
    log = ckpt / "viz_access.jsonl"
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text().splitlines()]


def test_issue_and_consume_are_audit_logged(monkeypatch, tmp_path):
    active = tmp_path / "checkpoints" / "active_run"
    active.mkdir(parents=True)
    monkeypatch.setattr(_st, "_checkpoint_dir", active)

    grant = chg.issue_challenge({"action": "stop-all", "target": "*"})
    assert chg.require_challenge(
        "stop-all", "*", {"challenge_id": grant["challenge_id"]}
    ) is None
    refused = chg.require_challenge("stop-all", "*", {})
    assert refused is not None and refused["_status"] == 428

    events = _audit_events(active)
    kinds = [e["event"] for e in events]
    assert kinds == ["challenge_issued", "challenge_consumed", "challenge_refused"]
    assert events[0]["challenge_id"] == grant["challenge_id"]
    assert events[0]["action"] == "stop-all" and events[0]["target"] == "*"
    assert events[1]["challenge_id"] == grant["challenge_id"]
    assert events[2]["reason"] == "missing challenge_id"
    assert all("ts" in e for e in events)


def test_audit_is_best_effort_without_active_checkpoint():
    """No active checkpoint -> no crash, no file (same as log_request)."""
    grant = chg.issue_challenge({"action": "stop-all", "target": "*"})
    assert grant["challenge_id"].startswith("chg-")
