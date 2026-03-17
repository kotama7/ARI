"""Tests for ari/orchestrator/node.py - Node state transitions."""

import pytest

from ari.orchestrator.node import Node, NodeStatus


def test_node_creation():
    node = Node(id="node_001", parent_id=None, depth=0)
    assert node.id == "node_001"
    assert node.parent_id is None
    assert node.depth == 0
    assert node.status == NodeStatus.PENDING
    assert node.retry_count == 0
    assert node.created_at != ""


def test_node_with_parent():
    node = Node(id="node_002", parent_id="node_001", depth=1)
    assert node.parent_id == "node_001"
    assert node.depth == 1


def test_mark_running():
    node = Node(id="n1", parent_id=None, depth=0)
    node.mark_running()
    assert node.status == NodeStatus.RUNNING


def test_mark_success():
    node = Node(id="n1", parent_id=None, depth=0)
    node.mark_running()
    artifacts = [{"type": "paper", "path": "/tmp/paper.md"}]
    node.mark_success(artifacts=artifacts, eval_summary="Good results")
    assert node.status == NodeStatus.SUCCESS
    assert node.artifacts == artifacts
    assert node.eval_summary == "Good results"
    assert node.completed_at != ""


def test_mark_failed():
    node = Node(id="n1", parent_id=None, depth=0)
    node.mark_running()
    node.mark_failed(error_log="Timeout exceeded")
    assert node.status == NodeStatus.FAILED
    assert node.error_log == "Timeout exceeded"
    assert node.completed_at != ""


def test_mark_abandoned():
    node = Node(id="n1", parent_id=None, depth=0)
    node.mark_abandoned()
    assert node.status == NodeStatus.ABANDONED
    assert node.completed_at != ""


def test_to_dict():
    node = Node(id="n1", parent_id="n0", depth=1)
    node.mark_success(eval_summary="test")
    d = node.to_dict()
    assert d["id"] == "n1"
    assert d["parent_id"] == "n0"
    assert d["depth"] == 1
    assert d["status"] == "success"
    assert d["eval_summary"] == "test"


def test_node_children():
    node = Node(id="n1", parent_id=None, depth=0)
    node.children.append("n2")
    node.children.append("n3")
    assert len(node.children) == 2
    assert "n2" in node.children


def test_node_status_enum_values():
    assert NodeStatus.PENDING == "pending"
    assert NodeStatus.RUNNING == "running"
    assert NodeStatus.SUCCESS == "success"
    assert NodeStatus.FAILED == "failed"
    assert NodeStatus.ABANDONED == "abandoned"


def test_node_memory_snapshot():
    snapshot = [{"content": "previous experiment data"}]
    node = Node(id="n1", parent_id="n0", depth=1, memory_snapshot=snapshot)
    assert len(node.memory_snapshot) == 1
    assert node.memory_snapshot[0]["content"] == "previous experiment data"
