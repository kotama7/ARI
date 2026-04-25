"""Live Letta integration test (opt-in).

Hits a real Letta server end-to-end with non-ASCII payloads — the original
``add_memory`` 400 was discovered against the live server, not the SDK.
The respx-based regression tests in ``test_letta_http_regression.py``
cover the SDK serialization path; this file covers the *deployment* path
(server schema mismatches, embedding config issues, agent creation, etc.)
that the mock can never see.

Skipped by default. Run explicitly with::

    ARI_TEST_LETTA=1 LETTA_BASE_URL=http://localhost:8283 pytest \\
        tests/test_letta_live_integration.py -v

Optional env:

  - ``ARI_TEST_LETTA``           — must be "1" to run (otherwise skipped).
  - ``LETTA_BASE_URL``           — defaults to ``http://localhost:8283``.
  - ``LETTA_API_KEY``            — passed through if Letta requires auth.
  - ``LETTA_EMBEDDING_CONFIG``   — embedding handle (default ``letta-default``;
                                   per project notes, set to
                                   ``openai/text-embedding-3-small`` for
                                   the local 0.9.1 deployment).

The test creates a uniquely-named ari_agent_<random>, exercises the
non-ASCII insert path, asserts no 400, and tears the agent down.
"""
from __future__ import annotations

import os
import time
import uuid

import pytest


pytestmark = pytest.mark.skipif(
    os.environ.get("ARI_TEST_LETTA") != "1",
    reason="opt-in: set ARI_TEST_LETTA=1 (and start a Letta server) to run",
)


def _server_reachable(base_url: str, api_key: str = "") -> bool:
    """Cheap pre-flight so we fail fast with a useful skip reason."""
    try:
        import httpx
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        with httpx.Client(timeout=2.0) as c:
            r = c.get(f"{base_url}/v1/health/", headers=headers)
            return r.status_code < 500
    except Exception:
        return False


@pytest.fixture
def live_backend(tmp_path, monkeypatch):
    """Construct a real LettaBackend pointed at the configured server.

    Yields ``(backend, agent_id_holder)`` where ``agent_id_holder`` is a
    list mutated by the backend on first ensure_agent — used by the
    fixture's teardown to delete the agent.
    """
    base_url = os.environ.get("LETTA_BASE_URL", "http://localhost:8283")
    api_key = os.environ.get("LETTA_API_KEY", "")
    if not _server_reachable(base_url, api_key):
        pytest.skip(f"Letta server not reachable at {base_url}")

    # Make every test run hit a fresh agent so we don't pollute other state
    # and so cleanup is unambiguous. We hash a per-run uuid as the
    # checkpoint so ari_agent_<hash> is unique.
    ckpt = tmp_path / f"ckpt-{uuid.uuid4().hex[:8]}"
    ckpt.mkdir()
    monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(ckpt))
    monkeypatch.setenv("ARI_MEMORY_BACKEND", "letta")
    monkeypatch.setenv("ARI_CURRENT_NODE_ID", "live-root")
    monkeypatch.setenv("LETTA_BASE_URL", base_url)
    if api_key:
        monkeypatch.setenv("LETTA_API_KEY", api_key)
    monkeypatch.setenv("ARI_MEMORY_ACCESS_LOG", "off")

    from ari_skill_memory.backends import clear_backend_cache, get_backend
    clear_backend_cache()
    backend = get_backend(checkpoint_dir=ckpt)
    try:
        yield backend
    finally:
        # Best-effort cleanup. purge_checkpoint deletes the agent it
        # created (line 356 of letta_backend.py).
        try:
            backend.purge_checkpoint()
        except Exception as e:
            print(f"[live integration] cleanup warn: {e}")
        clear_backend_cache()


def test_live_add_memory_with_non_ascii(live_backend):
    """The exact failure mode from the original bug report.

    Non-ASCII text + metadata against the real Letta server. If this
    raises ``Error code: 400 - {'detail': 'Expecting value...'}``, the
    bug has regressed.
    """
    text = (
        "Ran CSR SpMM two-path microbenchmark (gather vs global-packed B). "
        "結果: gather max 23.870 GFlops/s @ N=16, packed max 20.790 @ N=32. "
        "総合 GB_per_s mean 36.511, max 59.674. 検証コード: α/β τ=0.7."
    )
    metadata = {
        "node_id_label": "node_20260424073618_We_propose_an_implementation_of_CSR-form_root",
        "tags": ["性能", "ベンチマーク"],
    }
    r = live_backend.add_memory("live-root", text, metadata)
    assert r["ok"] is True
    assert isinstance(r.get("id"), str) and r["id"]


def test_live_add_then_search_roundtrip(live_backend):
    """Insert + search end-to-end against a real server.

    Adds two passages on the ancestor path, then searches; verifies
    the inserted text comes back. This catches not just the JSON
    encoding regression but also embedding/index path issues that
    only manifest server-side.
    """
    live_backend.add_memory(
        "live-root",
        "実験ベースライン GFlops_per_s mean=12.502",
        {"tag": "baseline"},
    )
    live_backend.add_memory(
        "live-root",
        "改善版 packed N=64 で 17.094 GFlops/s 達成",
        {"tag": "improved"},
    )
    # Letta's archival index is not strictly synchronous — give it a
    # moment if needed. Two seconds is generous for a local server.
    deadline = time.time() + 5.0
    found_texts: list[str] = []
    while time.time() < deadline:
        r = live_backend.search_memory(
            "GFlops", ancestor_ids=["live-root"], limit=10
        )
        found_texts = [x["text"] for x in r["results"]]
        if any("ベースライン" in t for t in found_texts):
            break
        time.sleep(0.25)
    assert any("ベースライン" in t for t in found_texts), (
        f"non-ASCII passage not retrievable after roundtrip: got {found_texts!r}"
    )


def test_live_health(live_backend):
    """The health endpoint should be 200 — a useful canary if the
    other tests start failing. If health itself is degraded we want
    to surface that rather than blame the insert path."""
    h = live_backend.health()
    assert h.get("ok") is True


# ──────────────────────────────────────────────────────────────────────
# Deployment-health canaries (added 2026-04-25 after a multi-hour
# debug session where add_memory returned opaque 500s for two distinct
# reasons that the existing roundtrip tests caught only as "500 from
# /v1/agents/.../archival-memory" with no signal as to *why*).
# ──────────────────────────────────────────────────────────────────────


def test_embedding_config_is_set_to_a_reachable_handle():
    """``LETTA_EMBEDDING_CONFIG`` defaulting to ``letta-default`` (or
    being unset) silently routes embeddings to a Letta-Cloud-only
    endpoint that local deployments cannot reach. Every ``add_memory``
    then surfaces as ``500 Internal Server Error`` whose root cause
    (``openai.NotFoundError: 404 Not Found``) is buried in the Letta
    server log, not the client traceback. Fail fast at the env layer.

    Why this isn't subsumed by the roundtrip tests: those produce a
    500 too, but with a generic ``InternalServerError`` and no hint
    that the fix is one ``.env`` line. This test names the cause.
    """
    val = os.environ.get("LETTA_EMBEDDING_CONFIG", "")
    assert val and val != "letta-default", (
        "LETTA_EMBEDDING_CONFIG is unset or 'letta-default' — that handle "
        "is unreachable from local Letta deployments. Set it to e.g. "
        "'openai/text-embedding-3-small' in .env. Symptom otherwise: every "
        "add_memory returns 500, with openai.NotFoundError: 404 in the "
        "Letta server log."
    )


def test_no_orphan_internal_daemons_under_apptainer():
    """Apptainer shares the host PID and network namespaces, so the
    Postgres and Redis processes spawned with ``&`` inside the SIF's
    ``startup.sh`` outlive the apptainer parent on a hard kill. Such
    orphans keep their ports (5432 / 6379) and an open handle to the
    SIF's filesystem — but the squashfuse_ll mount that backed that
    filesystem dies with its parent. The next ``dlopen('vector.so')``
    inside the orphan Postgres then fails with
    ``Transport endpoint is not connected``, and every pgvector-using
    archival_insert returns 500.

    Detection: any 5432/6379 listener owned by the current user
    whose process start time predates the apptainer parent recorded
    in the PIDFILE. Start-time comparison is more robust than
    ancestor-chain walking because Redis daemonizes (double-forks),
    losing its link back to the apptainer parent even in the healthy
    case.

    Skipped when no PIDFILE is present (i.e. the deployment isn't
    Apptainer-managed via start_singularity.sh).
    """
    import re
    import subprocess
    from pathlib import Path

    pidfile = Path(os.environ.get(
        "ARI_LETTA_PIDFILE", os.path.expanduser("~/.ari/letta.pid"),
    ))
    if not pidfile.is_file():
        pytest.skip(
            f"no PIDFILE at {pidfile}; apptainer-orphan check only "
            "applies to start_singularity.sh-managed deployments"
        )
    apptainer_pid = int(pidfile.read_text().strip())

    def _start_epoch(pid: int) -> float | None:
        # `ps -o lstart=` prints the absolute start time in a form
        # `date -d` understands. Convert to epoch for comparison.
        try:
            lstart = subprocess.check_output(
                ["ps", "-o", "lstart=", "-p", str(pid)], text=True,
            ).strip()
            if not lstart:
                return None
            return float(subprocess.check_output(
                ["date", "-d", lstart, "+%s"], text=True,
            ).strip())
        except (subprocess.CalledProcessError, ValueError):
            return None

    apptainer_start = _start_epoch(apptainer_pid)
    if apptainer_start is None:
        pytest.skip(
            f"could not read start time of apptainer pid={apptainer_pid}; "
            "the recorded PID is gone or unreadable"
        )

    out = subprocess.check_output(
        ["ss", "-ltnp"], text=True, stderr=subprocess.DEVNULL,
    )

    user = os.environ.get("USER", "")
    orphans: list[tuple[int, int, float, float]] = []
    for line in out.splitlines():
        for port in (5432, 6379):
            if f":{port} " not in line:
                continue
            m = re.search(r"pid=(\d+)", line)
            if not m:
                continue
            pid = int(m.group(1))
            try:
                owner = subprocess.check_output(
                    ["ps", "-o", "user=", "-p", str(pid)], text=True,
                ).strip()
            except subprocess.CalledProcessError:
                continue
            if owner != user:
                continue
            ts = _start_epoch(pid)
            if ts is None:
                continue
            # 2 s of slack for clock granularity. A daemon born from the
            # current apptainer is born strictly after the parent; one
            # leaked from a prior apptainer was born strictly before.
            if ts + 2.0 < apptainer_start:
                orphans.append((port, pid, ts, apptainer_start))

    assert not orphans, (
        f"Found internal Letta daemons whose start time predates the "
        f"current apptainer parent (pid={apptainer_pid}, "
        f"start={apptainer_start}): {orphans!r}. "
        "These are leaked processes from an earlier Letta restart that "
        "killed the apptainer parent without taking the daemon-mode "
        "Postgres/Redis with it. Symptom: archival_insert returns 500 "
        "with 'Transport endpoint is not connected'. Fix: kill the "
        "orphan PIDs, then re-run start_singularity.sh."
    )


def test_purge_checkpoint_actually_deletes_agent(live_backend):
    """``_api_delete_checkpoint`` calls ``backend.purge_checkpoint()``
    immediately before ``shutil.rmtree(checkpoint_dir)`` so that
    deleting a project from the GUI also removes its Letta data.

    This test asserts the contract that ari-core relies on: after a
    purge, the named agent is gone from Letta's REST surface. A
    regression here would manifest as ever-accumulating orphan agents
    in the Letta DB invisible from the GUI.
    """
    import json
    import urllib.request

    # Force agent creation by performing a write first.
    r = live_backend.add_memory("live-root", "to-be-purged")
    assert r.get("ok") is True, f"setup write failed: {r!r}"
    ckpt_hash = live_backend.ckpt_hash

    out = live_backend.purge_checkpoint()
    assert out["removed_node"] >= 1, (
        f"purge_checkpoint reported no removals: {out!r}"
    )

    base = os.environ.get("LETTA_BASE_URL", "http://localhost:8283")
    with urllib.request.urlopen(f"{base}/v1/agents", timeout=5) as resp:
        agents = json.loads(resp.read())
    matching = [a for a in agents if ckpt_hash in (a.get("name") or "")]
    assert not matching, (
        f"agent for ckpt_hash={ckpt_hash!r} still exists after purge: "
        f"{[a.get('name') for a in matching]}"
    )
