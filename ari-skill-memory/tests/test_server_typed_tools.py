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
    "consolidate_node_memory",
]


def test_all_typed_tools_registered():
    for name in _TYPED_TOOLS:
        assert callable(getattr(server, name)), f"{name} not exposed"


def test_experiment_result_and_verified_context_roundtrip(
    ckpt_env, authorized_context
):
    r = server.add_experiment_result(
        "nX", "grounded 842 GB/s",
        artifact_refs=[{"path": "out/bench.csv", "sha256": "a", "role": "data_output"}],
        ari_context=authorized_context("add_experiment_result"),
    )
    assert r["ok"]
    server.add_reproducibility_event(
        "nX",
        r["id"],
        "rerun_passed",
        ari_context=authorized_context("add_reproducibility_event"),
    )
    ctx = server.get_verified_context(
        ["nX"],
        ari_context=authorized_context("get_verified_context"),
    )
    assert ctx["claims"][0]["repro_status"] == "rerun_passed"
    assert any("grounded 842" in c["text"] for c in ctx["usable_for_claims"])


def test_search_research_memory_kind_filter(ckpt_env, authorized_context):
    server.add_experiment_result(
        "nX",
        "result on partA",
        ari_context=authorized_context("add_experiment_result"),
    )
    server.add_failure_case(
        "nX",
        "link failure on partA",
        ari_context=authorized_context("add_failure_case"),
    )
    res = server.search_research_memory(
        "partA",
        ["nX"],
        kinds=["failure_case"],
        ari_context=authorized_context("search_research_memory"),
    )
    texts = [r["text"] for r in res["results"]]
    assert any("link failure" in t for t in texts)
    assert all("result on partA" not in t for t in texts)


def test_consolidate_node_memory_writes_typed(ckpt_env, authorized_context):
    report = {
        "node_id": "nX", "status": "success",
        "metrics": {"GB_per_s": 842.1},
        "self_assessment": {"headline": "tile=32 best throughput"},
        "files_changed": {}, "artifacts": [], "next_steps_hints": ["try K=64"],
    }
    out = server.consolidate_node_memory(
        "nX",
        report,
        str(ckpt_env),
        run_id="r",
        ari_context=authorized_context("consolidate_node_memory"),
    )
    kinds = {w["kind"] for w in out["written"]}
    assert "experiment_result" in kinds and "reflection" in kinds
    assert all(w["ok"] for w in out["written"])
    got = server.get_verified_context(
        ["nX"],
        ari_context=authorized_context("get_verified_context"),
    )
    assert any("tile=32" in c["text"] for c in got["usable_for_claims"] + got["claims"])


def test_audit_defaults_to_authorized_run_and_rejects_other_run(
    ckpt_env, authorized_context, monkeypatch
):
    captured: dict[str, object] = {}

    def fake_audit(experiments_root, run_id):
        captured.update(experiments_root=experiments_root, run_id=run_id)
        return []

    monkeypatch.setattr(server._audit, "audit_checkpoint", fake_audit)
    out = server.audit_memory(
        str(ckpt_env.parent),
        ari_context=authorized_context("audit_memory", run_id="run-authorized"),
    )
    assert out["results"] == []
    assert captured["run_id"] == "run-authorized"

    with pytest.raises(PermissionError, match="does not match"):
        server.audit_memory(
            str(ckpt_env.parent),
            run_id="run-other",
            ari_context=authorized_context("audit_memory", run_id="run-authorized"),
        )


def test_consolidation_defaults_to_authorized_run(
    ckpt_env, authorized_context, monkeypatch
):
    captured: dict[str, object] = {}

    def fake_consolidate(node_report, work_dir, *, run_id):
        captured.update(node_report=node_report, work_dir=work_dir, run_id=run_id)
        return []

    monkeypatch.setattr(
        server.consolidation,
        "consolidate_from_node_report",
        fake_consolidate,
    )
    monkeypatch.setattr(
        server.consolidation,
        "write_consolidated",
        lambda backend, node_id, specs: [],
    )
    out = server.consolidate_node_memory(
        "nX",
        {"node_id": "nX", "status": "success"},
        str(ckpt_env),
        ari_context=authorized_context(
            "consolidate_node_memory",
            run_id="run-authorized",
        ),
    )
    assert out == {"written": []}
    assert captured["run_id"] == "run-authorized"
