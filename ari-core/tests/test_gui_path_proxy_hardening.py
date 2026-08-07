"""gui_refresh Wave 5a (task 09) — RR-P0-5 / RR-P0-7 / MN-5: /codefile path
boundary + Ollama reverse-proxy gate.

Covers:

* ``ari.viz.routes._codefile_resolve`` — the pure canonical boundary check
  for ``GET /codefile?path=``: allowed only under the active checkpoint dir
  or a checkpoint search base (``checkpoint_finder``); explicit rejection of
  ``..`` traversal, symlink escapes, ``/etc/passwd``, crafted
  ``.../checkpoints/...`` paths outside every base (the pre-MN-5 loophole),
  directories, and missing files.
* ``GET /codefile`` end-to-end through a socketless ``_Handler`` against a
  ``run_fixture_factory`` checkpoint (the legitimate frontend use: Results /
  EarSection / PaperWorkspace serve artifacts under real checkpoint dirs).
* ``ari.viz.api_ollama`` — MN-5 proxy gate: 403 when no ollama_host is
  configured and the effective llm backend is not ollama (no implicit
  localhost relay), explicit settings/`OLLAMA_HOST` opt-in (covers
  cli-shim-with-ollama), backend-is-ollama localhost dev default preserved,
  and the exact five-path allowlist (tags/show/generate/chat/ps).

Register/announcement: risk_register.md rows RR-P0-5/RR-P0-7 (closed Wave
5a), migration_notes.md MN-5.
"""

from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
from unittest import mock

import pytest

from ari.viz import api_state
from ari.viz import state as _st
from ari.viz.api_ollama import (
    OLLAMA_PROXY_ALLOWED_PATHS,
    _explicit_ollama_host,
    _ollama_proxy,
    _ollama_proxy_refusal,
)
from ari.viz.routes import _Handler, _codefile_resolve

_FACTORY_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "gui_refresh"
    / "run_fixture_factory.py"
)


def _load_factory():
    spec = importlib.util.spec_from_file_location(
        "gui_refresh_run_fixture_factory", _FACTORY_PATH
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


make_run_checkpoint = _load_factory().make_run_checkpoint


@pytest.fixture(autouse=True)
def _isolate_state(monkeypatch, tmp_path):
    """Never read/write the real project settings or checkpoint state."""
    settings = tmp_path / "settings.json"
    settings.write_text("{}")
    monkeypatch.setattr(_st, "_settings_path", settings)
    monkeypatch.setattr(_st, "_checkpoint_dir", None)
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.delenv("ARI_BACKEND", raising=False)


# ──────────────────────────────────────────────────────────────────────
# _codefile_resolve (pure — RR-P0-5 boundary)
# ──────────────────────────────────────────────────────────────────────

def _base_with_file(tmp_path: Path) -> tuple[Path, Path]:
    base = tmp_path / "bases" / "checkpoints"
    ckpt = base / "run1"
    ckpt.mkdir(parents=True)
    f = ckpt / "figure.png"
    f.write_bytes(b"\x89PNG fake")
    return base, f


def test_allows_file_under_search_base(tmp_path):
    base, f = _base_with_file(tmp_path)
    assert _codefile_resolve(str(f), None, [base]) == f.resolve()


def test_allows_file_under_active_checkpoint_outside_bases(tmp_path):
    """Active checkpoint dirs may live outside the search bases (custom
    locations selected via set_active_checkpoint) and must keep serving."""
    active = tmp_path / "elsewhere" / "run9"
    active.mkdir(parents=True)
    f = active / "plot.pdf"
    f.write_bytes(b"%PDF fake")
    assert _codefile_resolve(str(f), active, []) == f.resolve()


def test_rejects_dot_dot_traversal(tmp_path):
    base, f = _base_with_file(tmp_path)
    outside = tmp_path / "secret.txt"
    outside.write_text("secret")
    raw = str(base / "run1" / ".." / ".." / ".." / "secret.txt")
    assert _codefile_resolve(raw, None, [base]) is None


def test_rejects_dot_dot_even_when_target_would_stay_inside(tmp_path):
    """`..` segments are rejected outright, before any resolution."""
    base, f = _base_with_file(tmp_path)
    raw = str(base / "run1" / ".." / "run1" / "figure.png")
    assert _codefile_resolve(raw, None, [base]) is None


def test_rejects_symlink_escape(tmp_path):
    base, _ = _base_with_file(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("leaked")
    link = base / "run1" / "innocent.txt"
    link.symlink_to(outside)
    # The raw path looks in-tree; the resolved realpath is not.
    assert _codefile_resolve(str(link), None, [base]) is None


def test_rejects_etc_passwd(tmp_path):
    base, _ = _base_with_file(tmp_path)
    assert _codefile_resolve("/etc/passwd", None, [base]) is None
    assert _codefile_resolve("/etc/passwd", base / "run1", [base]) is None


def test_rejects_crafted_checkpoints_path_outside_bases(tmp_path):
    """The exact pre-MN-5 bypass: any path containing a `checkpoints`
    component used to be allowed regardless of where it lived."""
    fake = tmp_path / "fake" / "checkpoints" / "x"
    fake.mkdir(parents=True)
    f = fake / "payload.txt"
    f.write_text("outside the real bases")
    base, _ = _base_with_file(tmp_path)
    assert _codefile_resolve(str(f), None, [base]) is None


def test_rejects_directory_target(tmp_path):
    base, f = _base_with_file(tmp_path)
    assert _codefile_resolve(str(f.parent), None, [base]) is None


def test_rejects_missing_file_and_empty_path(tmp_path):
    base, _ = _base_with_file(tmp_path)
    assert _codefile_resolve(str(base / "run1" / "nope.txt"), None, [base]) is None
    assert _codefile_resolve("", base / "run1", [base]) is None


def test_unreadable_base_is_skipped_not_fatal(tmp_path):
    base, f = _base_with_file(tmp_path)
    ghost = tmp_path / "does-not-exist" / "checkpoints"
    assert _codefile_resolve(str(f), None, [ghost, base]) == f.resolve()


# ──────────────────────────────────────────────────────────────────────
# GET /codefile end-to-end (socketless _Handler + run fixture factory)
# ──────────────────────────────────────────────────────────────────────

def _make_get_handler(path: str):
    h = _Handler.__new__(_Handler)
    h.path = path
    h.headers = {}
    h.wfile = io.BytesIO()
    h.sent = []
    h.send_response = lambda code: h.sent.append(("status", code))
    h.send_header = lambda k, v: h.sent.append((k, v))
    h.end_headers = lambda: h.sent.append(("end", None))
    return h


def _status_of(h) -> int:
    return next(code for kind, code in h.sent if kind == "status")


def test_codefile_serves_fixture_checkpoint_artifact(tmp_path, monkeypatch):
    """Legitimate frontend use keeps working: an artifact under a real
    checkpoint dir (fixture factory) is served with its content-type."""
    base = tmp_path / "checkpoints"
    ckpt = base / "run_fixture"
    make_run_checkpoint(ckpt, nodes=3, seed=1, paper=True)
    monkeypatch.setattr(api_state, "_checkpoint_search_bases", lambda: [base])
    pdf = ckpt / "full_paper.pdf"
    assert pdf.is_file()

    h = _make_get_handler(f"/codefile?path={pdf}")
    h.do_GET()
    assert _status_of(h) == 200
    headers = {k: v for k, v in h.sent if k not in ("status", "end")}
    assert headers["Content-Type"] == "application/pdf"
    assert h.wfile.getvalue() == pdf.read_bytes()


def test_codefile_active_checkpoint_still_served(tmp_path, monkeypatch):
    monkeypatch.setattr(api_state, "_checkpoint_search_bases", lambda: [])
    active = tmp_path / "custom" / "run2"
    make_run_checkpoint(active, nodes=2, seed=2)
    monkeypatch.setattr(_st, "_checkpoint_dir", active)

    target = active / "experiment.md"
    h = _make_get_handler(f"/codefile?path={target}")
    h.do_GET()
    assert _status_of(h) == 200


def test_codefile_404_for_outside_paths(tmp_path, monkeypatch):
    base = tmp_path / "checkpoints"
    (base / "run1").mkdir(parents=True)
    monkeypatch.setattr(api_state, "_checkpoint_search_bases", lambda: [base])

    fake = tmp_path / "tmpfake" / "checkpoints" / "x"
    fake.mkdir(parents=True)
    (fake / "evil.txt").write_text("x")

    for raw in ("/etc/passwd", str(fake / "evil.txt"),
                str(base / "run1" / ".." / ".." / "settings.json")):
        h = _make_get_handler(f"/codefile?path={raw}")
        h.do_GET()
        assert _status_of(h) == 404, raw


# ──────────────────────────────────────────────────────────────────────
# Ollama proxy gate (RR-P0-7) — pure refusal logic
# ──────────────────────────────────────────────────────────────────────

def test_allowlist_is_exactly_the_five_documented_paths():
    assert OLLAMA_PROXY_ALLOWED_PATHS == frozenset({
        "/api/tags", "/api/show", "/api/generate", "/api/chat", "/api/ps",
    })


def test_refusal_when_no_host_and_backend_not_ollama():
    # settings {} → workflow.yaml default backend (openai) → refuse.
    reason = _ollama_proxy_refusal("/api/tags")
    assert reason is not None and "not ollama" in reason


def test_no_refusal_when_backend_is_ollama():
    _st._settings_path.write_text(json.dumps({"llm_provider": "ollama"}))
    assert _ollama_proxy_refusal("/api/tags") is None


def test_no_refusal_with_settings_host_any_backend():
    _st._settings_path.write_text(json.dumps({
        "llm_provider": "openai", "ollama_host": "http://gpu-node:11435",
    }))
    assert _ollama_proxy_refusal("/api/generate") is None


def test_no_refusal_with_env_host_cli_shim(monkeypatch):
    """cli-shim-with-ollama: OLLAMA_HOST env is the explicit opt-in."""
    _st._settings_path.write_text(json.dumps({"llm_provider": "cli-shim"}))
    monkeypatch.setenv("OLLAMA_HOST", "http://localhost:11434")
    assert _ollama_proxy_refusal("/api/chat") is None


@pytest.mark.parametrize("bad_path", [
    "/api/pull", "/api/push", "/api/create", "/api/copy", "/api/delete",
    "/api/embeddings", "/", "/api/tags/../delete", "/version",
])
def test_refusal_for_non_allowlisted_paths(bad_path, monkeypatch):
    """Even a fully configured target only relays the allowlist."""
    monkeypatch.setenv("OLLAMA_HOST", "http://localhost:11434")
    reason = _ollama_proxy_refusal(bad_path)
    assert reason is not None and "not allowed" in reason


@pytest.mark.parametrize("good_path", sorted(OLLAMA_PROXY_ALLOWED_PATHS))
def test_allowlisted_paths_pass_with_query_string(good_path, monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "http://localhost:11434")
    assert _ollama_proxy_refusal(good_path) is None
    assert _ollama_proxy_refusal(good_path + "?x=1") is None


def test_explicit_host_ignores_merged_default(monkeypatch):
    """_explicit_ollama_host must not see _api_get_settings' implicit
    localhost default — only raw settings or the env var."""
    assert _explicit_ollama_host() == ""
    monkeypatch.setenv("OLLAMA_HOST", "http://h:1")
    assert _explicit_ollama_host() == "http://h:1"
    monkeypatch.delenv("OLLAMA_HOST")
    _st._settings_path.write_text(json.dumps({"ollama_host": " http://s:2 "}))
    assert _explicit_ollama_host() == "http://s:2"


# ──────────────────────────────────────────────────────────────────────
# Ollama proxy gate — handler-level (mocked upstream)
# ──────────────────────────────────────────────────────────────────────

def _make_proxy_handler(path="/api/ollama/api/tags", method="GET", body=b""):
    handler = mock.MagicMock()
    handler.path = path
    handler.command = method
    handler.headers = {"Content-Type": "application/json",
                       "Content-Length": str(len(body))}
    handler.rfile = io.BytesIO(body)
    handler.wfile = io.BytesIO()
    handler.wfile.flush = mock.MagicMock()
    return handler


def test_proxy_403_no_upstream_connection_when_unconfigured():
    """No configured host + non-ollama backend → 403, and no socket is
    ever opened toward the implicit localhost default."""
    handler = _make_proxy_handler()
    with mock.patch("http.client.HTTPConnection",
                    side_effect=AssertionError("must not connect")) as mock_http:
        _ollama_proxy(handler)
    mock_http.assert_not_called()
    handler.send_response.assert_called_once_with(403)
    assert b"ollama proxy refused" in handler.wfile.getvalue()


def test_proxy_403_for_non_allowlisted_path_even_when_configured(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "http://gpu-node:11435")
    handler = _make_proxy_handler(path="/api/ollama/api/pull", method="POST",
                                  body=b'{"name": "evil"}')
    with mock.patch("http.client.HTTPConnection") as mock_http:
        _ollama_proxy(handler)
    mock_http.assert_not_called()
    handler.send_response.assert_called_once_with(403)
    assert b"not allowed" in handler.wfile.getvalue()


def test_proxy_forwards_allowlisted_path_with_env_host(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "http://gpu-node:11435")
    mock_resp = mock.MagicMock()
    mock_resp.status = 200
    mock_resp.getheader.return_value = "application/json"
    mock_resp.read = mock.MagicMock(side_effect=[b"{}", b""])
    mock_conn = mock.MagicMock()
    mock_conn.getresponse.return_value = mock_resp

    handler = _make_proxy_handler(path="/api/ollama/api/tags")
    with mock.patch("http.client.HTTPConnection", return_value=mock_conn) as mock_http:
        _ollama_proxy(handler)
    mock_http.assert_called_with("gpu-node", 11435, timeout=600)
