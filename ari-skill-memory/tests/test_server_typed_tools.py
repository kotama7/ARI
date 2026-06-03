"""Phase 1 — MCP server wiring for typed research-memory tools.

The server tools are thin delegators to writer/retriever/context_builder/audit;
this locks in that they are registered, callable, and round-trip through the
backend (in-memory via the ``ckpt_env`` fixture, CoW node = ``nX``).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

# Every skill ships a module literally named ``server``; bare-name import is
# ambiguous in the shared pytest process. Load THIS skill's server.py by path
# under a unique module name to avoid sys.modules collisions.
_SERVER_PY = Path(__file__).resolve().parent.parent / "src" / "server.py"
_spec = importlib.util.spec_from_file_location("ari_skill_memory_server", _SERVER_PY)
server = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(server)

_TYPED_TOOLS = [
    "add_experiment_result",
    "add_failure_case",
    "add_procedure_memory",
    "add_reflection",
    "add_reproducibility_event",
    "search_research_memory",
    "get_verified_context",
    "audit_memory",
]


def test_all_typed_tools_registered():
    for name in _TYPED_TOOLS:
        assert callable(getattr(server, name)), f"{name} not exposed"


def test_experiment_result_and_verified_context_roundtrip(ckpt_env):
    r = server.add_experiment_result(
        "nX", "grounded 842 GB/s",
        artifact_refs=[{"path": "out/bench.csv", "sha256": "a", "role": "data_output"}],
    )
    assert r["ok"]
    server.add_reproducibility_event("nX", r["id"], "rerun_passed")
    ctx = server.get_verified_context(["nX"])
    assert ctx["claims"][0]["repro_status"] == "rerun_passed"
    assert any("grounded 842" in c["text"] for c in ctx["usable_for_claims"])


def test_search_research_memory_kind_filter(ckpt_env):
    server.add_experiment_result("nX", "result on partA")
    server.add_failure_case("nX", "link failure on partA")
    res = server.search_research_memory("partA", ["nX"], kinds=["failure_case"])
    texts = [r["text"] for r in res["results"]]
    assert any("link failure" in t for t in texts)
    assert all("result on partA" not in t for t in texts)
