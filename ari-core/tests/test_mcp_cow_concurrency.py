"""Regression: MCPClient must atomically pair `_set_current_node` with
the following memory write across concurrent BFTS nodes.

The CoW guard in ari-skill-memory's LettaBackend rejects writes whose
``node_id`` doesn't match ``$ARI_CURRENT_NODE_ID``. That env lives in
the *shared* memory-skill MCP server process, so when multiple BFTS
nodes run in parallel (default ``max_parallel_nodes=4``), naive code
of the form

    self.mcp.call_tool("_set_current_node", {"node_id": node.id})  # T0
    ...                                                            # T1
    self.mcp.call_tool("add_memory", {"node_id": node.id, ...})    # T2

races: between T0 and T2 a sibling node can call _set_current_node with
its own id and the CoW guard rejects T2's write.

The fix is ``MCPClient.call_tool(..., cow_node_id=node.id)``, which
serialises the (set, write) pair under a process-wide RLock. This test
asserts the serialisation contract by recording the order of the two
inner calls and verifying every write sees its own node's set as the
most recent one.
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

_ARI_SRC = Path(__file__).resolve().parent.parent / "ari"
if str(_ARI_SRC.parent) not in sys.path:
    sys.path.insert(0, str(_ARI_SRC.parent))

from ari.mcp.client import MCPClient


class _FakeMCPClient(MCPClient):
    """Drop-in MCPClient that bypasses real stdio dispatch.

    Records every (tool_name, args) call in the order they actually
    enter the inner dispatch — i.e. *under* whatever lock the public
    ``call_tool`` holds — so the test can assert that for each
    ``add_memory`` entry, the immediately preceding entry was a
    ``_set_current_node`` for the same node_id.
    """
    def __init__(self) -> None:
        # Skip parent __init__: no skills / connections needed.
        import threading as _t
        self._cow_lock = _t.RLock()
        self.calls: list[tuple[str, dict]] = []
        self._calls_lock = _t.Lock()

    def _call_tool_unlocked(self, tool_name: str, args: dict) -> dict:
        # Tiny sleep simulates real MCP latency so threads actually
        # interleave at the unlocked layer if the caller forgot to lock.
        time.sleep(0.005)
        with self._calls_lock:
            self.calls.append((tool_name, dict(args)))
        return {"ok": True}


def _writer(client: _FakeMCPClient, node_id: str, n: int) -> None:
    for _ in range(n):
        client.call_tool(
            "add_memory",
            {"node_id": node_id, "text": f"from {node_id}"},
            cow_node_id=node_id,
        )


def test_concurrent_add_memory_pairs_with_set_current_node():
    """Across many concurrent writers, every add_memory entry in the
    serialized call log must be immediately preceded by a
    _set_current_node for the same node_id."""
    client = _FakeMCPClient()
    nodes = [f"node_{i:03d}" for i in range(8)]
    writes_per_node = 25

    threads = [
        threading.Thread(target=_writer, args=(client, nid, writes_per_node))
        for nid in nodes
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    calls = client.calls
    expected_total = len(nodes) * writes_per_node * 2  # set + write each
    assert len(calls) == expected_total, (
        f"expected {expected_total} calls, got {len(calls)}"
    )

    add_count = 0
    for i, (name, args) in enumerate(calls):
        if name != "add_memory":
            continue
        add_count += 1
        # Without the CoW lock, an interleaved sibling's _set_current_node
        # would land between this add_memory and its own set — i.e.
        # calls[i-1] would be a _set_current_node for a *different* node.
        prev_name, prev_args = calls[i - 1]
        assert prev_name == "_set_current_node", (
            f"add_memory at idx {i} not preceded by _set_current_node; "
            f"prev was {prev_name!r}"
        )
        assert prev_args["node_id"] == args["node_id"], (
            f"add_memory at idx {i} for {args['node_id']!r} preceded by "
            f"_set_current_node for {prev_args['node_id']!r} — CoW lock "
            "did not serialise the (set, write) pair"
        )
    assert add_count == len(nodes) * writes_per_node


def test_non_cow_tools_bypass_lock():
    """The CoW lock should only engage for memory tools. Other tool
    calls must be reentrant from inside the lock (e.g. nested helpers)
    and must not be serialised by it.

    We assert this by calling a non-CoW tool while holding _cow_lock
    in the same thread — the RLock handles same-thread reentry, and
    non-CoW tools should not even try to take the lock.
    """
    client = _FakeMCPClient()
    with client._cow_lock:
        # search_memory is not in _COW_TOOLS, so call_tool should not
        # try to re-acquire the lock under cow_node_id semantics.
        r = client.call_tool("search_memory", {"query": "x"})
        assert r == {"ok": True}
    # Single passthrough call recorded.
    assert client.calls == [("search_memory", {"query": "x"})]


def test_call_tool_without_cow_node_id_is_passthrough():
    """When cow_node_id is omitted, even add_memory should pass through
    without invoking _set_current_node (preserves the legacy behaviour
    for non-BFTS callers like CLI tools and tests)."""
    client = _FakeMCPClient()
    client.call_tool("add_memory", {"node_id": "n1", "text": "x"})
    assert client.calls == [("add_memory", {"node_id": "n1", "text": "x"})]
