"""Parallel memory calls use signed NodeContext, never shared mutable state."""

from __future__ import annotations

import json
import threading
from pathlib import Path

from ari.call_context import ToolCallContextV1
from ari.config import SkillConfig
from ari.config.skill_runtime import manifest_runtime_metadata
from ari.mcp.client import MCPClient
from ari.skill_manifest import load_skill_manifest


def _memory_skill() -> SkillConfig:
    root = Path(__file__).parents[2] / "ari-skill-memory"
    manifest = load_skill_manifest(root / "skill.yaml")
    return SkillConfig(
        name=manifest.name,
        path=str(root),
        package=manifest.package,
        version=manifest.version,
        entrypoint=manifest.entrypoint.module,
        environment_policy=manifest.environment_policy,
        required_env=list(manifest.required_env),
        optional_env=list(manifest.optional_env),
        **manifest_runtime_metadata(manifest),
    )


def _context(node_id: str) -> ToolCallContextV1:
    return ToolCallContextV1.for_node(
        run_id="parallel-run",
        node_id=node_id,
        parent_node_id="root",
        ancestor_node_ids=["root"],
        phase="bfts",
    )


def _payload(result: dict) -> dict:
    return json.loads(result["result"])


def test_parallel_node_contexts_never_cross(tmp_path, monkeypatch):
    (tmp_path / ".ari-test-memory-backend").write_text("test-only\n")
    monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(tmp_path))
    monkeypatch.setenv("ARI_MEMORY_BACKEND", "in_memory")
    # The removed compatibility variable cannot grant or redirect authority.
    monkeypatch.setenv("ARI_CURRENT_NODE_ID", "spoofed-node")
    client = MCPClient([_memory_skill()], strict_provider_loading=True)
    client.list_tools(phase="bfts")
    nodes = [f"node_{index}" for index in range(4)]
    writes_per_node = 10
    failures: list[object] = []

    def writer(node_id: str) -> None:
        context = _context(node_id)
        for index in range(writes_per_node):
            result = client.call_tool(
                "add_memory",
                {"node_id": node_id, "text": f"{node_id}:{index}"},
                context=context,
            )
            if "error" in result or not _payload(result).get("ok"):
                failures.append(result)

    threads = [threading.Thread(target=writer, args=(node,)) for node in nodes]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert failures == []
    for node_id in nodes:
        entries = _payload(
            client.call_tool(
                "get_node_memory",
                {"node_id": node_id},
                context=_context(node_id),
            )
        )["entries"]
        assert len(entries) == writes_per_node
        assert all(entry["text"].startswith(f"{node_id}:") for entry in entries)
    client.close_all()


def test_context_policy_fails_closed_and_rejects_sibling(tmp_path, monkeypatch):
    (tmp_path / ".ari-test-memory-backend").write_text("test-only\n")
    monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(tmp_path))
    monkeypatch.setenv("ARI_MEMORY_BACKEND", "in_memory")
    client = MCPClient([_memory_skill()], strict_provider_loading=True)

    missing = client.call_tool("add_memory", {"node_id": "node_a", "text": "x"})
    assert "requires explicit node context" in missing["error"]

    forged_target = client.call_tool(
        "add_memory",
        {"node_id": "node_b", "text": "x"},
        context=_context("node_a"),
    )
    assert "authorized self node" in forged_target["result"]

    sibling_read = client.call_tool(
        "get_node_memory",
        {"node_id": "node_b"},
        context=_context("node_a"),
    )
    assert "crosses the authorized lineage" in sibling_read["result"]
    client.close_all()


def test_claude_proxy_config_carries_context_but_not_authority_key(
    tmp_path, monkeypatch
):
    (tmp_path / ".ari-test-memory-backend").write_text("test-only\n")
    monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(tmp_path))
    monkeypatch.setenv("ARI_MEMORY_BACKEND", "in_memory")
    client = MCPClient([_memory_skill()], strict_provider_loading=True)
    context = _context("node_a")
    config, allowed = client.to_claude_mcp_config(
        phase="bfts",
        context=context,
    )
    server = config["mcpServers"]["memory-skill"]
    proxy_spec = json.loads(server["args"][3])
    serialized = json.dumps(config, sort_keys=True)

    assert proxy_spec["call_context"]["node_context"]["node_id"] == "node_a"
    assert proxy_spec["context_requirements"]["add_memory"] == "node"
    assert "ARI_CONTEXT_AUTHORITY_KEY" not in proxy_spec["env_names"]
    assert "ARI_CONTEXT_AUTHORITY_KEY" not in server["env"]
    assert client._context_authority_keys["memory-skill"] not in serialized
    assert "mcp__memory-skill__add_memory" in allowed
    assert all("_set_current_node" not in name for name in allowed)
    client.close_all()
