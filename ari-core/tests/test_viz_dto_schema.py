"""Schema-DTO conformance tests for the viz dashboard wire contract (subtask 022).

Extends the subset-assertion guards in ``test_api_schema_contract.py`` by
validating the SAME real handler payloads against committed draft-07 JSON
Schemas under ``ari-core/ari/schemas/`` (the ``viz_*.schema.json`` files), and by
cross-checking that each schema's ``required`` keys still exist as fields in the
frontend TypeScript source of truth
(``ari/viz/frontend/src/types/index.ts``). Validation is **dependency-free** (no
``jsonschema``): it copies the ``_load_schema``/``_check_required`` idiom from
``test_node_report.py`` and only asserts required-key presence plus a few
explicit value checks (a false-negative schema is safe; an over-strict one would
break the suite).

Documented (not changed) live response conventions the dashboard uses today:

- ``{"ok": bool, ...}`` — launch/run-stage/workflow-save endpoints.
- ``{"error": str}`` — file/checkpoint/PaperBench endpoints; the PaperBench
  handlers also return e.g. ``{"deleted": bool, "paper_id": ...}``
  (``api_paperbench.py``).
- The checkpoint-summary not-found path is the exact sentinel
  ``{"error": "not found"}`` (``checkpoint_api.py:199``), asserted by equality.
- HTTP status codes are smuggled via ``routes.py`` ``r.pop("_status", 200)``
  (``routes.py:1047-1057,1088-1089``).

These remain the current contract; 022 only pins them (015/021 may later unify
the ``{"ok"}``/``{"error"}`` split — that is a runtime change out of scope here).

Verified against the implementation on 2026-07-02.
"""
from __future__ import annotations

import json
import re
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from ari import schemas
from ari.viz import api_settings
from ari.viz import checkpoint_api
from ari.viz import state as _st


# ── dependency-free validator (mirrors test_node_report.py:29-61) ──────────

def _check_required(payload, schema, *, where: str = "$") -> None:
    """Assert ``payload`` is an object carrying every ``schema['required']`` key.

    Deliberately does NOT type-check every property (that would duplicate a full
    jsonschema engine, which is not a dependency); explicit value asserts live in
    the individual tests. Required-key presence is the drift tripwire.
    """
    assert isinstance(payload, dict), f"{where}: payload is not an object"
    missing = [k for k in schema.get("required", []) if k not in payload]
    assert not missing, (
        f"{where}: missing required key(s) {missing} for schema "
        f"{schema.get('$id')}"
    )


def _load(basename: str) -> dict:
    """Load a ``viz_*.schema.json`` via ``ari.schemas.load``.

    The files follow the repo's ``<name>.schema.json`` convention (like
    ``node_report.schema.json``); the generic loader only appends ``.json``, so
    the ``.schema`` suffix is passed explicitly.
    """
    return schemas.load(f"{basename}.schema")


# ── fixtures / helpers (mirror test_api_schema_contract.py:25-40) ──────────

@pytest.fixture
def isolated_state(monkeypatch, tmp_path):
    monkeypatch.setattr(_st, "_checkpoint_dir", None, raising=False)
    monkeypatch.setattr(_st, "_last_proc", None, raising=False)
    monkeypatch.setattr(_st, "_running_procs", {}, raising=False)
    monkeypatch.setattr(_st, "_settings_path", None, raising=False)
    yield tmp_path


def _make_checkpoint(root: Path, name: str = "20260101_dto") -> Path:
    d = root / name
    d.mkdir(parents=True)
    (d / "tree.json").write_text(json.dumps({"nodes": [
        {"id": "n0", "status": "completed", "metrics": {"_scientific_score": 0.5}},
    ]}))
    return d


_TYPES_TS = (
    Path(__file__).resolve().parent.parent
    / "ari" / "viz" / "frontend" / "src" / "types" / "index.ts"
)

# schema basename -> mirrored frontend TS interface name.
_SCHEMA_TO_INTERFACE = {
    "viz_tree_node": "TreeNode",
    "viz_state": "AppState",
    "viz_settings": "Settings",
    "viz_checkpoint": "Checkpoint",
    "viz_checkpoint_summary": "CheckpointSummary",
}


def _interface_fields(ts_src: str, name: str) -> set:
    """Return the field-name set of a TS ``export interface`` block.

    Name-level extraction only (no TS toolchain): find the interface, walk its
    balanced braces, and match ``^\\s*fieldName?:`` per line. Optional ``?`` and
    nested type braces are tolerated.
    """
    m = re.search(r"export interface " + re.escape(name) + r"\s*\{", ts_src)
    assert m, f"interface {name} not found in {_TYPES_TS}"
    depth = 1
    i = m.end()
    while i < len(ts_src) and depth > 0:
        c = ts_src[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        i += 1
    body = ts_src[m.end():i - 1]
    fields = set()
    for line in body.splitlines():
        fm = re.match(r"\s*([A-Za-z_]\w*)\??\s*:", line)
        if fm:
            fields.add(fm.group(1))
    return fields


# ── schema files load and are valid draft-07 objects ───────────────────────

@pytest.mark.parametrize("name", list(_SCHEMA_TO_INTERFACE))
def test_viz_schema_loads_and_is_draft07(name):
    s = _load(name)
    assert isinstance(s, dict), f"{name}: not an object"
    assert s.get("$schema") == "http://json-schema.org/draft-07/schema#"
    assert s.get("type") == "object"
    assert isinstance(s.get("required", []), list)
    assert isinstance(s.get("properties", {}), dict)
    # Additive-subset policy: extra/optional keys must never fail validation.
    assert s.get("additionalProperties", True) is True


# ── TS <-> schema sync guard (Section 7.3) ─────────────────────────────────

def test_schema_required_keys_exist_in_ts_interface():
    ts_src = _TYPES_TS.read_text(encoding="utf-8")
    for name, iface in _SCHEMA_TO_INTERFACE.items():
        schema = _load(name)
        fields = _interface_fields(ts_src, iface)
        for key in schema.get("required", []):
            assert key in fields, (
                f"drift: schema {name}.schema.json requires '{key}' but interface "
                f"{iface} in {_TYPES_TS} has no such field — fix the schema or the "
                f"TS type."
            )


# ── /api/checkpoints item  ->  viz_checkpoint ──────────────────────────────

def test_checkpoints_item_conforms(isolated_state, monkeypatch):
    root = isolated_state / "checkpoints"
    _make_checkpoint(root)
    monkeypatch.setattr(checkpoint_api, "_checkpoint_search_bases", lambda: [root])
    items = checkpoint_api._api_checkpoints()
    assert isinstance(items, list) and items, "expected at least one checkpoint"
    schema = _load("viz_checkpoint")
    for item in items:
        _check_required(item, schema, where="/api/checkpoints[]")
    assert isinstance(items[0]["id"], str)
    assert isinstance(items[0]["node_count"], int)
    assert items[0]["best_metric"] is None  # documented always-null init


# ── /api/checkpoint/<id>/summary  ->  viz_checkpoint_summary + viz_tree_node ─

def test_checkpoint_summary_found_conforms(isolated_state, monkeypatch):
    root = isolated_state / "checkpoints"
    d = _make_checkpoint(root, name="20260101_summary")
    monkeypatch.setattr(checkpoint_api, "_resolve_checkpoint_dir", lambda cid: d)
    summary = checkpoint_api._api_checkpoint_summary("20260101_summary")
    schema = _load("viz_checkpoint_summary")
    _check_required(summary, schema, where="/api/checkpoint/<id>/summary")
    assert summary["id"] == "20260101_summary"
    # nodes_tree is present for this fixture; each node validates against the
    # shared viz_tree_node schema (id is the only guaranteed key).
    assert "nodes_tree" in summary and "nodes" in summary["nodes_tree"]
    tree_node = _load("viz_tree_node")
    for node in summary["nodes_tree"]["nodes"]:
        _check_required(node, tree_node, where="nodes_tree.nodes[]")


def test_checkpoint_summary_not_found_sentinel(isolated_state, monkeypatch):
    monkeypatch.setattr(checkpoint_api, "_resolve_checkpoint_dir", lambda cid: None)
    summary = checkpoint_api._api_checkpoint_summary("nope")
    # Exact sentinel — NOT an additive payload (documented in the schema desc).
    assert summary == {"error": "not found"}


# ── /api/settings  ->  viz_settings ────────────────────────────────────────

def test_settings_conforms(isolated_state, monkeypatch):
    monkeypatch.setattr(_st, "_settings_path", None, raising=False)
    s = api_settings._api_get_settings()
    schema = _load("viz_settings")
    _check_required(s, schema, where="/api/settings")
    # `ors` is emitted by the backend but absent from the Settings TS interface;
    # it lives in the schema properties (not `required`) and is pinned here.
    assert isinstance(s.get("ors"), dict) and "judge_model" in s["ors"]


def test_settings_merge_still_conforms(isolated_state, monkeypatch):
    sp = isolated_state / "settings.json"
    sp.write_text(json.dumps({"llm_model": "custom/model", "extra_saved": 7}))
    monkeypatch.setattr(_st, "_settings_path", sp, raising=False)
    s = api_settings._api_get_settings()
    schema = _load("viz_settings")
    _check_required(s, schema, where="/api/settings (merged)")
    assert s["llm_model"] == "custom/model"  # saved overrides default
    assert s["extra_saved"] == 7             # additionalProperties: true


# ── GET /state  ->  viz_state (+ viz_tree_node)  via a real HTTP round-trip ──

def test_state_payload_conforms(monkeypatch, tmp_path):
    """The /state builder is inline in ``routes.py`` do_GET (no standalone
    function exists yet), so it is exercised through an in-process HTTP request
    exactly as ``test_server.py`` does — this validates *current* behaviour, not
    a future extraction."""
    ckpt = tmp_path / "checkpoints" / "20260101_state"
    ckpt.mkdir(parents=True)
    (ckpt / "nodes_tree.json").write_text(json.dumps({"nodes": [
        {"id": "n0", "status": "completed", "metrics": {"_scientific_score": 0.5}},
    ]}))
    monkeypatch.setattr(_st, "_checkpoint_dir", ckpt, raising=False)
    monkeypatch.setattr(_st, "_last_proc", None, raising=False)
    monkeypatch.setattr(_st, "_running_procs", {}, raising=False)
    monkeypatch.setattr(_st, "_launch_llm_model", "openai/gpt-4o", raising=False)
    monkeypatch.setattr(_st, "_launch_llm_provider", "openai", raising=False)
    monkeypatch.setattr(_st, "_settings_path", None, raising=False)

    from ari.viz.server import _Handler
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        conn = HTTPConnection("127.0.0.1", port, timeout=10)
        conn.request("GET", "/state")
        resp = conn.getresponse()
        assert resp.status == 200, f"expected 200, got {resp.status}"
        payload = json.loads(resp.read())
        conn.close()
    finally:
        srv.shutdown()

    schema = _load("viz_state")
    _check_required(payload, schema, where="/state")
    # Unconditional tail keys (routes.py:564-575) + JS-compat aliases.
    assert isinstance(payload["is_running"], bool)
    assert isinstance(payload["running"], bool)
    assert payload["running"] == payload["is_running"]
    assert payload["pid"] == payload["running_pid"]
    assert isinstance(payload["status_label"], str)
    assert isinstance(payload["llm_model"], str)
    # nodes come from nodes_tree.json; each raw node validates against tree_node.
    if isinstance(payload.get("nodes"), list) and payload["nodes"]:
        tree_node = _load("viz_tree_node")
        for node in payload["nodes"]:
            _check_required(node, tree_node, where="/state nodes[]")
