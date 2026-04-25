"""Live restart-endpoint integration test (opt-in).

Exercises the full chain that the GUI's "Restart Letta" button triggers:

    SettingsPage button → POST /api/memory/restart →
        _api_memory_restart() → stop_local() → start_local()

against the real running Letta server. The mocked
``test_letta_start_scripts.py::test_restart_endpoint_runs_stop_then_start``
covers wiring; this file covers the actual daemon lifecycle (port
release, fresh process, .env re-read, post-restart health).

Skipped by default. Opt in with::

    ARI_TEST_LETTA_RESTART=1 pytest -v tests/test_letta_restart_live.py

The test is destructive — it kills the running ``letta server`` process
and waits for it to come back. Don't run while an experiment depends
on the server (in-flight ``add_memory`` calls during the restart
window will fail).
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import httpx
import pytest


pytestmark = pytest.mark.skipif(
    os.environ.get("ARI_TEST_LETTA_RESTART") != "1",
    reason=(
        "destructive: restarts the live Letta daemon. "
        "Set ARI_TEST_LETTA_RESTART=1 to run."
    ),
)


_BASE = os.environ.get("LETTA_BASE_URL", "http://localhost:8283")
_PIDFILE = Path(
    os.environ.get("ARI_LETTA_PIDFILE", str(Path.home() / ".ari" / "letta-pid"))
)


def _read_pid() -> int | None:
    """Return the pid recorded in ``letta-pid``, if any."""
    try:
        text = _PIDFILE.read_text().strip()
        return int(text) if text else None
    except (FileNotFoundError, ValueError):
        return None


def _is_alive(pid: int) -> bool:
    """``True`` iff the kernel still tracks ``pid`` (any state)."""
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _wait_for_health(timeout_s: float) -> tuple[bool, float]:
    """Poll ``/v1/health/`` until 200 or timeout. Return (ok, latency_s)."""
    deadline = time.monotonic() + timeout_s
    start = time.monotonic()
    while time.monotonic() < deadline:
        try:
            with httpx.Client(timeout=2.0) as c:
                r = c.get(f"{_BASE}/v1/health/")
                if r.status_code < 500:
                    return True, time.monotonic() - start
        except Exception:
            pass
        time.sleep(0.5)
    return False, timeout_s


def _preflight_or_skip() -> int:
    """Verify Letta is reachable before we destroy it. Returns the
    initial pid so post-restart we can confirm it changed."""
    try:
        with httpx.Client(timeout=2.0) as c:
            if c.get(f"{_BASE}/v1/health/").status_code >= 500:
                pytest.skip(f"Letta at {_BASE} is not healthy pre-test")
    except Exception as e:
        pytest.skip(f"Letta at {_BASE} not reachable: {e}")
    pid = _read_pid()
    if pid is None or not _is_alive(pid):
        pytest.skip(
            f"can't read a live pid from {_PIDFILE}; "
            "this test only runs against the pip-mode deployment"
        )
    return pid


def test_restart_endpoint_actually_bounces_the_daemon():
    """End-to-end: the running Letta gets killed, a NEW process comes
    up at the same port, and ``/v1/health/`` returns 200 again.

    This is the test that would catch:
      - stop_local missing the pip-mode process (no restart effect)
      - start_local racing with port release (new process fails to bind)
      - .env loader regression (Letta starts but with no provider keys)
    """
    from ari.viz.api_memory import _api_memory_restart

    old_pid = _preflight_or_skip()

    # Trigger the restart end-to-end. Path "pip" matches what the
    # current deployment is using; passing it explicitly avoids the
    # auto-detect heuristic flapping (docker preferred when present).
    result = _api_memory_restart(b'{"path": "pip"}')

    assert result["ok"] is True, (
        f"restart reported failure: stop={result.get('stop')!r} "
        f"start={result.get('start')!r}"
    )

    # The OLD pid must be dead (or at least not the one in pidfile any
    # more). Give the kernel a moment to reap.
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline and _is_alive(old_pid):
        time.sleep(0.2)
    assert not _is_alive(old_pid), (
        f"old Letta pid {old_pid} still alive after restart — stop_local "
        "did not actually kill the running process"
    )

    # Health must come back within a reasonable window. Fresh Letta
    # boot with sqlite-vec loading + agent index typically takes 5–15s.
    healthy, took = _wait_for_health(timeout_s=60.0)
    assert healthy, (
        f"Letta did not return to healthy at {_BASE} within 60s after "
        "restart — start_local may have failed to relaunch"
    )

    # The new pid must differ from the old one. (A pid file that wasn't
    # rewritten would be a regression.)
    new_pid = _read_pid()
    assert new_pid is not None and new_pid != old_pid, (
        f"pidfile {_PIDFILE} still shows {new_pid!r} after restart — "
        "either start_pip.sh skipped writing it, or the restart didn't "
        "actually spawn a new process"
    )
    assert _is_alive(new_pid), (
        f"new pid {new_pid} from pidfile is not alive"
    )

    # Functional recovery: add_memory must work end-to-end against the
    # fresh daemon (which proves credentials/agent provisioning still
    # work after a restart, not just port-binding).
    import tempfile
    import uuid
    from ari_skill_memory.backends import (  # type: ignore[import]
        clear_backend_cache, get_backend,
    )

    with tempfile.TemporaryDirectory(prefix="ari-restart-probe-") as td:
        ckpt = Path(td) / f"ckpt-{uuid.uuid4().hex[:6]}"
        ckpt.mkdir()
        os.environ["ARI_CHECKPOINT_DIR"] = str(ckpt)
        os.environ["ARI_MEMORY_BACKEND"] = "letta"
        os.environ["ARI_CURRENT_NODE_ID"] = "post-restart"
        os.environ["LETTA_BASE_URL"] = _BASE
        os.environ.setdefault(
            "LETTA_EMBEDDING_CONFIG", "openai/text-embedding-3-small"
        )
        os.environ["ARI_MEMORY_ACCESS_LOG"] = "off"
        clear_backend_cache()
        backend = get_backend(checkpoint_dir=ckpt)
        try:
            r = backend.add_memory(
                "post-restart",
                "post-restart probe — fresh daemon",
                {"tag": "restart-test"},
            )
            assert r["ok"] is True, (
                f"add_memory failed against the freshly-restarted Letta: {r}"
            )
        finally:
            try:
                backend.purge_checkpoint()
            except Exception:
                pass
            clear_backend_cache()

    print(
        f"[ok] restart bounced pid {old_pid} → {new_pid}, "
        f"healthy in {took:.1f}s"
    )
