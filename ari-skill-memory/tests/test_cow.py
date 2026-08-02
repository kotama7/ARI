"""Signed NodeContext enforcement at the memory MCP boundary."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


_SERVER_PY = Path(__file__).resolve().parent.parent / "src" / "server.py"
_spec = importlib.util.spec_from_file_location("ari_memory_context_server", _SERVER_PY)
server = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(server)


def _child_capability(authorized_context, tool_name: str) -> dict:
    return authorized_context(
        tool_name,
        node_id="child",
        parent_node_id="ancestor",
        ancestor_node_ids=["ancestor"],
    )


def test_signed_child_cannot_write_ancestor(
    backend, authorized_context, monkeypatch
):
    backend.add_memory("ancestor", "original", {})
    # A spoofed legacy environment value has no authority.
    monkeypatch.setenv("ARI_CURRENT_NODE_ID", "ancestor")
    with pytest.raises(PermissionError, match="authorized self node"):
        server.add_memory(
            "ancestor",
            "mutation",
            ari_context=_child_capability(authorized_context, "add_memory"),
        )
    entries = backend.get_node_memory("ancestor")["entries"]
    assert [entry["text"] for entry in entries] == ["original"]


def test_signed_child_cannot_clear_ancestor(backend, authorized_context):
    backend.add_memory("ancestor", "A", {})
    with pytest.raises(PermissionError, match="authorized self node"):
        server.clear_node_memory(
            "ancestor",
            ari_context=_child_capability(
                authorized_context,
                "clear_node_memory",
            ),
        )
    assert backend.get_node_memory("ancestor")["entries"]


def test_missing_or_tampered_context_is_rejected(authorized_context):
    with pytest.raises(PermissionError, match="malformed"):
        server.add_memory("nX", "x")

    capability = authorized_context("add_memory")
    capability["context"]["node_id"] = "forged"
    with pytest.raises(PermissionError, match="malformed|signature"):
        server.add_memory("nX", "x", ari_context=capability)


def test_signed_lineage_rejects_sibling_read(authorized_context):
    with pytest.raises(PermissionError, match="crosses the authorized lineage"):
        server.get_node_memory(
            "sibling",
            ari_context=_child_capability(
                authorized_context,
                "get_node_memory",
            ),
        )
