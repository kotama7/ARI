"""Tests for ari/orchestrator/bfts.py - BFTS pruning and node selection."""

from unittest.mock import MagicMock, patch

import pytest

from ari.config import BFTSConfig
from ari.llm.client import LLMClient, LLMResponse
from ari.orchestrator.bfts import BFTS
from ari.orchestrator.node import Node, NodeStatus


@pytest.fixture
def bfts_config():
    return BFTSConfig(max_depth=3, max_retries_per_node=2, max_total_nodes=10)


@pytest.fixture
def mock_llm():
    llm = MagicMock(spec=LLMClient)
    return llm


@pytest.fixture
def mock_memory():
    memory = MagicMock()
    memory.search.return_value = []
    return memory


@pytest.fixture
def bfts(bfts_config, mock_llm):
    return BFTS(bfts_config, mock_llm)


def test_should_not_prune_by_depth_alone(bfts):
    """depth is a soft constraint. Good nodes at deep levels are not pruned."""
    node = Node(id="n1", parent_id=None, depth=3, has_real_data=True)
    assert bfts.should_prune(node) is False


def test_should_not_prune_shallow(bfts):
    node = Node(id="n1", parent_id=None, depth=2)
    assert bfts.should_prune(node) is False


def test_should_not_prune_failed_node(bfts):
    """Failed nodes are not pruned — BFTS expands them with debug children."""
    node = Node(id="n1", parent_id=None, depth=0, retry_count=2)
    assert bfts.should_prune(node) is False


def test_select_next_node_single_candidate(bfts, mock_memory):
    node = Node(id="n1", parent_id=None, depth=0)
    result = bfts.select_next_node([node], "test goal", mock_memory)
    assert result is node


def test_select_next_node_empty_raises(bfts, mock_memory):
    with pytest.raises(ValueError, match="No candidate"):
        bfts.select_next_node([], "test goal", mock_memory)


def test_select_next_node_multiple(bfts, mock_llm, mock_memory):
    """The node at the index returned by LLM is selected."""
    mock_llm.complete.return_value = LLMResponse(content="1")
    nodes = [
        Node(id="n1", parent_id=None, depth=0),
        Node(id="n2", parent_id=None, depth=0),
    ]
    result = bfts.select_next_node(nodes, "test goal", mock_memory)
    assert result.id == "n2"  # LLM returned "1" so index=1 → n2


def test_select_next_node_invalid_llm_response(bfts, mock_llm, mock_memory):
    """If LLM returns an invalid response, prefer has_real_data=True nodes, otherwise pick the first."""
    mock_llm.complete.return_value = LLMResponse(content="invalid")
    nodes = [
        Node(id="n1", parent_id=None, depth=0),
        Node(id="n2", parent_id=None, depth=0),
    ]
    result = bfts.select_next_node(nodes, "test goal", mock_memory)
    assert result.id == "n1"  # fallback: pick first


def test_expand(bfts, mock_llm):
    # Even if the LLM returns multiple directions, expand() must hard-cap to 1
    # so that workers create exactly one new node per call.
    mock_llm.complete.return_value = LLMResponse(
        content='["direction A", "direction B"]'
    )

    node = Node(id="n1", parent_id=None, depth=0)
    children = bfts.expand(node)

    assert len(children) == 1
    assert children[0].parent_id == "n1"
    assert children[0].depth == 1
    assert len(node.children) == 1


def test_expand_non_json_response(bfts, mock_llm):
    mock_llm.complete.return_value = LLMResponse(content="just a text direction")

    node = Node(id="n1", parent_id=None, depth=0)
    children = bfts.expand(node)

    assert len(children) == 1
    assert children[0].eval_summary == "just a text direction"
