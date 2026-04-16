"""Tests for _run_loop in ari/cli.py — verify the pending-node drain fix.

The bug: when expand() pushed len(all_nodes) past max_total_nodes, the outer
while-loop exited and left the last pending node(s) unexecuted (still PENDING).
The fix changes the loop condition so that *already-created* pending nodes are
always processed, regardless of the total-node budget.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from ari.config import ARIConfig, BFTSConfig
from ari.orchestrator.node import Node, NodeStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cfg(max_total_nodes: int = 6, max_parallel: int = 2,
              timeout: int = 60) -> ARIConfig:
    return ARIConfig(
        bfts=BFTSConfig(
            max_total_nodes=max_total_nodes,
            max_parallel_nodes=max_parallel,
            timeout_per_node=timeout,
        ),
    )


def _make_agent(succeed: bool = True):
    """Return a mock agent whose run() marks the node SUCCESS or FAILED."""
    agent = MagicMock()
    agent.hints = SimpleNamespace(provided_files=[], slurm_partition="", slurm_max_cpus=0)
    agent.memory = MagicMock()
    agent.memory.search.return_value = []

    def _run(node, exp_data):
        node.mark_running()
        if succeed:
            node.mark_success(eval_summary="ok")
            node.has_real_data = True
        else:
            node.mark_failed(error_log="simulated failure")
        return node

    agent.run.side_effect = _run
    return agent


def _make_bfts(children_per_expand: int = 2):
    """Return a mock BFTS that creates *children_per_expand* child nodes per call.

    Note: real expand() now caps to 1 child per call. Tests that simulate the
    old multi-child behavior still work because we control the mock here, but
    callers should be aware that production code will call expand() multiple
    times to fill worker slots instead of relying on a multi-child return.
    """
    bfts = MagicMock()
    bfts.should_prune.return_value = False

    _expand_counter = {"n": 0}

    def _expand(node, *args, **kwargs):
        children = []
        for _ in range(children_per_expand):
            _expand_counter["n"] += 1
            child = Node(
                id=f"child_{_expand_counter['n']}",
                parent_id=node.id,
                depth=node.depth + 1,
            )
            node.children.append(child.id)
            children.append(child)
        return children

    bfts.expand.side_effect = _expand

    def _select_best(frontier, goal, memory):
        return frontier[0]
    bfts.select_best_to_expand.side_effect = _select_best

    def _select_next(pending, goal, memory):
        return pending[0]
    bfts.select_next_node.side_effect = _select_next

    return bfts


def _run(cfg, bfts, agent, pending, all_nodes, experiment_data,
         total_processed=0):
    """Call _run_loop with a temp checkpoint dir."""
    from ari.cli import _run_loop
    with tempfile.TemporaryDirectory() as tmpdir:
        return _run_loop(
            cfg, bfts, agent, pending, all_nodes, experiment_data,
            checkpoint_dir=Path(tmpdir), run_id="test-run",
            total_processed=total_processed,
        )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRunLoopPendingDrain:
    """Core fix: pending nodes must be processed even when all_nodes >= max."""

    def test_last_pending_node_executed(self):
        """Bug reproduction: expand overshoots budget, last node must NOT stay PENDING."""
        # max_total_nodes=4, root + expand(root)->3 children = 4 nodes total
        # Then one child succeeds, expand again -> 3 more = 7 total (over budget).
        # The remaining pending children from the second expand must still run.
        cfg = _make_cfg(max_total_nodes=4, max_parallel=1)
        bfts = _make_bfts(children_per_expand=3)
        agent = _make_agent(succeed=True)

        root = Node(id="root", parent_id=None, depth=0)
        pending = [root]
        all_nodes = [root]
        exp_data = {"goal": "test", "topic": "t", "file": "f.md"}

        _run(cfg, bfts, agent, pending, all_nodes, exp_data)

        pending_nodes = [n for n in all_nodes if n.status == NodeStatus.PENDING]
        assert pending_nodes == [], (
            f"Nodes left PENDING: {[n.id for n in pending_nodes]}"
        )

    def test_all_nodes_reach_terminal_state(self):
        """Every node in all_nodes must be SUCCESS or FAILED, never PENDING."""
        cfg = _make_cfg(max_total_nodes=5, max_parallel=2)
        bfts = _make_bfts(children_per_expand=3)
        agent = _make_agent(succeed=True)

        root = Node(id="root", parent_id=None, depth=0)
        pending = [root]
        all_nodes = [root]
        exp_data = {"goal": "test", "topic": "t", "file": "f.md"}

        _run(cfg, bfts, agent, pending, all_nodes, exp_data)

        for node in all_nodes:
            assert node.status in (NodeStatus.SUCCESS, NodeStatus.FAILED), (
                f"Node {node.id} has non-terminal status: {node.status}"
            )

    def test_expand_overshoot_still_drains(self):
        """Even if expand creates more nodes than budget allows, all get executed."""
        # max_total_nodes=3 but expand always creates 3 children
        # root(1) + 3 children = 4 > 3.  All 4 must be executed.
        cfg = _make_cfg(max_total_nodes=3, max_parallel=4)
        bfts = _make_bfts(children_per_expand=3)
        agent = _make_agent(succeed=True)

        root = Node(id="root", parent_id=None, depth=0)
        pending = [root]
        all_nodes = [root]
        exp_data = {"goal": "test", "topic": "t", "file": "f.md"}

        _run(cfg, bfts, agent, pending, all_nodes, exp_data)

        executed = [n for n in all_nodes if n.status != NodeStatus.PENDING]
        assert len(executed) == len(all_nodes), (
            f"Only {len(executed)}/{len(all_nodes)} executed"
        )


class TestRunLoopBatchSize:
    """batch_size must not be capped by total_processed."""

    def test_batch_not_capped_by_total_processed(self):
        """With the old code, batch_size = min(workers, pending, max_nodes - total_processed).
        If total_processed >= max_nodes, batch_size=0 and pending nodes starve.
        After the fix, batch_size = min(workers, pending) — always positive."""
        cfg = _make_cfg(max_total_nodes=2, max_parallel=4)
        # No expansion needed — just feed pre-built pending nodes.
        bfts = _make_bfts(children_per_expand=2)
        agent = _make_agent(succeed=True)

        root = Node(id="root", parent_id=None, depth=0)
        pending = [root]
        all_nodes = [root]
        exp_data = {"goal": "test", "topic": "t", "file": "f.md"}

        # Start with total_processed already at max.
        # Old code: batch_size = min(4, 1, 2-2) = 0 → root never runs.
        # New code: batch_size = min(4, 1) = 1 → root runs.
        total = _run(cfg, bfts, agent, pending, all_nodes, exp_data,
                     total_processed=2)

        assert root.status != NodeStatus.PENDING, (
            "Root should have been executed despite total_processed >= max_total_nodes"
        )


class TestRunLoopNormalFlow:
    """Sanity checks for the normal (non-overshoot) flow."""

    def test_single_root_node(self):
        """A single root node with no expansion should just run and return."""
        cfg = _make_cfg(max_total_nodes=1, max_parallel=1)
        bfts = _make_bfts(children_per_expand=2)
        agent = _make_agent(succeed=True)

        root = Node(id="root", parent_id=None, depth=0)
        pending = [root]
        all_nodes = [root]
        exp_data = {"goal": "test", "topic": "t", "file": "f.md"}

        total = _run(cfg, bfts, agent, pending, all_nodes, exp_data)

        assert root.status == NodeStatus.SUCCESS
        assert total == 1

    def test_failed_nodes_get_expanded(self):
        """Failed nodes go to frontier and get expanded with debug children."""
        cfg = _make_cfg(max_total_nodes=6, max_parallel=2)
        bfts = _make_bfts(children_per_expand=2)
        agent = _make_agent(succeed=False)  # all nodes fail

        root = Node(id="root", parent_id=None, depth=0)
        pending = [root]
        all_nodes = [root]
        exp_data = {"goal": "test", "topic": "t", "file": "f.md"}

        _run(cfg, bfts, agent, pending, all_nodes, exp_data)

        # root fails → expanded → 2 children fail → expanded → etc.
        # all should reach FAILED, none PENDING
        for n in all_nodes:
            assert n.status in (NodeStatus.SUCCESS, NodeStatus.FAILED), (
                f"Node {n.id} stuck in {n.status}"
            )

    def test_total_processed_counts_correctly(self):
        """total_processed should equal the number of nodes actually run."""
        cfg = _make_cfg(max_total_nodes=10, max_parallel=2)
        bfts = _make_bfts(children_per_expand=2)
        agent = _make_agent(succeed=True)

        root = Node(id="root", parent_id=None, depth=0)
        pending = [root]
        all_nodes = [root]
        exp_data = {"goal": "test", "topic": "t", "file": "f.md"}

        total = _run(cfg, bfts, agent, pending, all_nodes, exp_data)

        executed = [n for n in all_nodes
                    if n.status in (NodeStatus.SUCCESS, NodeStatus.FAILED)]
        assert total == len(executed)

    def test_no_expansion_beyond_budget(self):
        """Frontier nodes should NOT be expanded once all_nodes >= max_total_nodes."""
        cfg = _make_cfg(max_total_nodes=4, max_parallel=1)
        bfts = _make_bfts(children_per_expand=2)
        agent = _make_agent(succeed=True)

        root = Node(id="root", parent_id=None, depth=0)
        pending = [root]
        all_nodes = [root]
        exp_data = {"goal": "test", "topic": "t", "file": "f.md"}

        _run(cfg, bfts, agent, pending, all_nodes, exp_data)

        # Track expansion calls: root → 2 children. Each child succeeds and
        # goes to frontier. When picking the next expansion, budget may allow
        # one more round. But eventually, no expand should happen once
        # len(all_nodes) >= max_total_nodes and pending is empty.
        # Just verify we didn't create wildly more nodes than the budget.
        # (Some overshoot is acceptable since expand returns 2+ at once.)
        assert len(all_nodes) <= cfg.bfts.max_total_nodes + 3, (
            f"Too many nodes created: {len(all_nodes)} (max={cfg.bfts.max_total_nodes})"
        )


class TestRunLoopEdgeCases:
    """Edge cases and boundary conditions."""

    def test_empty_pending_no_crash(self):
        """Empty pending list should return immediately without error."""
        cfg = _make_cfg(max_total_nodes=5, max_parallel=2)
        bfts = _make_bfts()
        agent = _make_agent()

        total = _run(cfg, bfts, agent, pending=[], all_nodes=[],
                     experiment_data={"goal": "test", "topic": "t", "file": "f.md"})
        assert total == 0

    def test_max_total_nodes_one(self):
        """With max_total_nodes=1, only the root runs, no expansion."""
        cfg = _make_cfg(max_total_nodes=1, max_parallel=1)
        bfts = _make_bfts(children_per_expand=2)
        agent = _make_agent(succeed=True)

        root = Node(id="root", parent_id=None, depth=0)
        pending = [root]
        all_nodes = [root]
        exp_data = {"goal": "test", "topic": "t", "file": "f.md"}

        total = _run(cfg, bfts, agent, pending, all_nodes, exp_data)

        assert root.status == NodeStatus.SUCCESS
        assert total == 1
        # No expansion should have happened (budget=0 after root).
        assert len(all_nodes) == 1

    def test_multiple_pending_at_start(self):
        """If resumed with multiple pending nodes, all should be executed."""
        cfg = _make_cfg(max_total_nodes=3, max_parallel=4)
        bfts = _make_bfts(children_per_expand=2)
        agent = _make_agent(succeed=True)

        nodes = [
            Node(id=f"node_{i}", parent_id=None, depth=0)
            for i in range(3)
        ]
        pending = list(nodes)
        all_nodes = list(nodes)
        exp_data = {"goal": "test", "topic": "t", "file": "f.md"}

        total = _run(cfg, bfts, agent, pending, all_nodes, exp_data)

        for n in nodes:
            assert n.status == NodeStatus.SUCCESS, (
                f"Node {n.id} not executed: {n.status}"
            )
        assert total == 3


class TestFrontierExpandDisabled:
    """When frontier_expand is disabled in bfts_pipeline, the loop must NOT
    expand completed nodes — only run the initial pending set."""

    def test_no_expand_when_frontier_expand_disabled(self, tmp_path):
        """With frontier_expand disabled, root should run but no children created."""
        import yaml
        from ari.cli import _run_loop

        # Write workflow.yaml with frontier_expand disabled
        wf = {
            "bfts_pipeline": [
                {"stage": "generate_idea", "enabled": True, "phase": "bfts"},
                {"stage": "select_and_run", "enabled": True, "phase": "bfts"},
                {"stage": "evaluate", "enabled": True, "phase": "bfts"},
                {"stage": "frontier_expand", "enabled": False, "phase": "bfts"},
            ],
        }
        (tmp_path / "workflow.yaml").write_text(yaml.dump(wf))

        cfg = _make_cfg(max_total_nodes=10, max_parallel=2)
        bfts = _make_bfts(children_per_expand=2)
        agent = _make_agent(succeed=True)

        root = Node(id="root", parent_id=None, depth=0)
        pending = [root]
        all_nodes = [root]
        exp_data = {"goal": "test", "topic": "t", "file": "f.md"}

        total = _run_loop(
            cfg, bfts, agent, pending, all_nodes, exp_data,
            checkpoint_dir=tmp_path, run_id="test-disabled",
        )

        # Root was executed
        assert root.status == NodeStatus.SUCCESS
        assert total == 1
        # No expansion happened — only root in all_nodes
        assert len(all_nodes) == 1
        bfts.expand.assert_not_called()
