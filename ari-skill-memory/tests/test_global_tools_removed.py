"""Confirm that the v0.5.x global-memory tools are gone in v0.6.0."""
from __future__ import annotations


def test_server_does_not_expose_global_tools():
    from src import server as srv  # type: ignore[import]
    for name in ("add_global_memory", "search_global_memory", "list_global_memory"):
        assert not hasattr(srv, name), (
            f"{name!r} should have been removed from server.py"
        )


def test_backend_has_no_global_methods(backend):
    for name in ("add_global_memory", "search_global_memory", "list_global_memory"):
        assert not hasattr(backend, name)
