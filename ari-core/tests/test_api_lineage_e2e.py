"""E2E smoke test: start the actual ARI HTTP server and verify
/api/lineage-decisions/<run_id> answers as expected for the GUI.

This complements the unit-level tests in test_api_lineage_decisions.py
by exercising the full HTTP path (do_GET dispatch + JSON serialisation).
"""

from __future__ import annotations

import json
import socket
import threading
import time
import urllib.request
from http.server import HTTPServer
from pathlib import Path
from unittest.mock import patch

import pytest


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def http_server(tmp_path: Path):
    """Start ari.viz.server.Handler on a random port, scoped to a temp
    workspace. Yields (port, ckpt_path)."""
    from ari.viz import server as srv
    from ari.viz import api_state

    # Build a fake checkpoint with one lineage_decision record.
    ckpt = tmp_path / "ckpt_e2e"
    ckpt.mkdir()
    (ckpt / "lineage_decisions.jsonl").write_text(
        json.dumps(
            {
                "ts": 1715000000.0,
                "ts_iso": "2026-05-04T08:00:00Z",
                "trigger": "stagnation_rule",
                "executed": False,
                "state": {
                    "active_idea_title": "ENVELOPE",
                    "nodes_explored": 5,
                    "budget_remaining": 10,
                },
                "decision": {
                    "action": "continue",
                    "target_idea_index": None,
                    "disable_generate_ideas": False,
                    "rationale": "still productive",
                },
            }
        )
        + "\n",
    )

    # Patch _resolve_checkpoint_dir to point at our tmp ckpt for this id.
    orig_resolver = api_state._resolve_checkpoint_dir
    def _resolver(ckpt_id: str):
        if ckpt_id == "ckpt_e2e":
            return ckpt
        return orig_resolver(ckpt_id)
    patcher = patch.object(api_state, "_resolve_checkpoint_dir", side_effect=_resolver)
    patcher.start()

    port = _free_port()
    handler = srv._Handler
    httpd = HTTPServer(("127.0.0.1", port), handler)
    th = threading.Thread(target=httpd.serve_forever, daemon=True)
    th.start()
    # Tiny wait for server to settle.
    time.sleep(0.05)
    try:
        yield port, ckpt
    finally:
        httpd.shutdown()
        httpd.server_close()
        patcher.stop()


def test_get_lineage_decisions_returns_jsonl(http_server):
    port, _ckpt = http_server
    url = f"http://127.0.0.1:{port}/api/lineage-decisions/ckpt_e2e"
    with urllib.request.urlopen(url, timeout=5) as resp:
        assert resp.status == 200
        body = resp.read().decode("utf-8")
    data = json.loads(body)
    assert data["n"] == 1
    rec = data["records"][0]
    assert rec["trigger"] == "stagnation_rule"
    assert rec["decision"]["action"] == "continue"
    assert rec["state"]["active_idea_title"] == "ENVELOPE"


def test_get_lineage_decisions_unknown_ckpt(http_server):
    port, _ckpt = http_server
    url = f"http://127.0.0.1:{port}/api/lineage-decisions/no_such_ckpt"
    with urllib.request.urlopen(url, timeout=5) as resp:
        body = resp.read().decode("utf-8")
    data = json.loads(body)
    assert data["n"] == 0
    assert "error" in data


def test_get_lineage_decisions_url_encoded(http_server):
    """Run IDs are URL-encoded by the frontend; the server must decode."""
    port, ckpt = http_server
    # Re-create the ckpt under a name that contains characters needing
    # encoding, then point to it via URL-encoded path.
    encoded_name = "ckpt with space"
    new_ckpt = ckpt.parent / encoded_name
    new_ckpt.mkdir()
    (new_ckpt / "lineage_decisions.jsonl").write_text(
        json.dumps({
            "ts": 1, "trigger": "stagnation_rule", "executed": False,
            "decision": {"action": "continue", "rationale": "ok"},
        }) + "\n",
    )
    from ari.viz import api_state
    orig_resolver = api_state._resolve_checkpoint_dir
    def _resolver(ckpt_id: str):
        if ckpt_id == encoded_name:
            return new_ckpt
        return orig_resolver(ckpt_id)
    with patch.object(api_state, "_resolve_checkpoint_dir", side_effect=_resolver):
        import urllib.parse
        url = (
            f"http://127.0.0.1:{port}/api/lineage-decisions/"
            + urllib.parse.quote(encoded_name)
        )
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    assert data["n"] == 1


def test_get_lineage_decisions_content_type_json(http_server):
    """The response must be application/json so the frontend's JSON
    parser does not need defensive content-sniffing."""
    port, _ = http_server
    url = f"http://127.0.0.1:{port}/api/lineage-decisions/ckpt_e2e"
    with urllib.request.urlopen(url, timeout=5) as resp:
        ct = resp.headers.get("Content-Type", "")
    assert "json" in ct.lower()
