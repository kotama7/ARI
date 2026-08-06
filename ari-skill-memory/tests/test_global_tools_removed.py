"""Confirm that the v0.5.x global-memory tools are gone in v0.6.0."""
from __future__ import annotations

import importlib.util
from pathlib import Path


_SERVER_PY = Path(__file__).resolve().parent.parent / "src" / "server.py"
_SPEC = importlib.util.spec_from_file_location(
    "ari_skill_memory_global_tools_server",
    _SERVER_PY,
)
assert _SPEC is not None
assert _SPEC.loader is not None
SERVER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(SERVER)


def test_server_does_not_expose_global_tools():
    for name in ("add_global_memory", "search_global_memory", "list_global_memory"):
        assert not hasattr(SERVER, name), (
            f"{name!r} should have been removed from server.py"
        )


def test_backend_has_no_global_methods(backend):
    for name in ("add_global_memory", "search_global_memory", "list_global_memory"):
        assert not hasattr(backend, name)
