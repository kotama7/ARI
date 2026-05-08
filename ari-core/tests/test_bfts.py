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


def test_expand_enriches_prompt_with_parent_node_report(bfts, mock_llm, tmp_path, monkeypatch):
    """When the parent's `node_report.json` exists, expand() should fold its
    delta_vs_parent / concerns / next_steps_hints into the LLM prompt so the
    planner can target weaknesses concretely."""
    workspace = tmp_path / "ws"
    run_id = "myexp"
    ckpt = workspace / "checkpoints" / run_id
    ckpt.mkdir(parents=True)
    parent = Node(id="parent_x", parent_id=None, depth=0)
    parent_wd = workspace / "experiments" / run_id / parent.id
    parent_wd.mkdir(parents=True)
    import json as _j
    (parent_wd / "node_report.json").write_text(_j.dumps({
        "schema_version": 1,
        "node_id": parent.id,
        "depth": 0,
        "label": "improve",
        "status": "success",
        "files_changed": {
            "added": [{"path": "tiling.h", "sha256": "x"}],
            "modified": [{"path": "main.cpp", "sha256_before": "a", "sha256_after": "b"}],
            "deleted": [], "inherited_unchanged": [],
        },
        "delta_vs_parent": "Introduced tile-blocking with TILE=32",
        "self_assessment": {
            "succeeded": True, "headline": "+75% throughput",
            "concerns": ["comparative_rigor: no MKL baseline"],
        },
        "next_steps_hints": ["Try TILE=64 + AVX-512 prefetch"],
        "metrics": {}, "artifacts": [],
    }))
    monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(ckpt))
    captured: dict = {}

    def _capture(messages, **kw):
        captured["prompt"] = messages[0].content
        return LLMResponse(content='[{"label": "ablation", "direction": "ablate TILE"}]')

    mock_llm.complete.side_effect = _capture
    bfts.expand(parent)
    text = captured["prompt"]
    assert "Parent node_report" in text
    assert "Introduced tile-blocking with TILE=32" in text
    assert "no MKL baseline" in text
    assert "TILE=64 + AVX-512 prefetch" in text
    assert "tiling.h" in text  # files added surfaced
    assert "main.cpp" in text  # files modified surfaced


def test_expand_sibling_dedup_uses_files_changed(bfts, mock_llm, tmp_path, monkeypatch):
    """T-B5: when sibling node_reports exist, the prompt must list each
    sibling's files_changed.added so the LLM can physically avoid
    proposing a direction that writes the same files."""
    workspace = tmp_path / "ws"
    run_id = "myexp"
    ckpt = workspace / "checkpoints" / run_id
    ckpt.mkdir(parents=True)
    parent = Node(id="parent_x", parent_id=None, depth=0)
    sibling_a = Node(id="sib_a", parent_id="parent_x", depth=1)
    sibling_b = Node(id="sib_b", parent_id="parent_x", depth=1)
    # sibling A writes tile.py; sibling B writes prefetch.py.
    import json as _j
    for nid, fname in (("sib_a", "tile.py"), ("sib_b", "prefetch.py")):
        wd = workspace / "experiments" / run_id / nid
        wd.mkdir(parents=True)
        (wd / "node_report.json").write_text(_j.dumps({
            "schema_version": 1, "node_id": nid,
            "depth": 1, "label": "improve", "status": "success",
            "files_changed": {
                "added": [{"path": fname, "sha256": "x"}],
                "modified": [], "deleted": [], "inherited_unchanged": [],
            },
            "self_assessment": {"succeeded": True, "headline": "ok",
                                "concerns": []},
            "metrics": {"x": 1.0},
            "artifacts": [],
        }))
    monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(ckpt))
    captured: dict = {}

    def _capture(messages, **kw):
        captured["prompt"] = messages[0].content
        return LLMResponse(content='[{"label": "ablation", "direction": "x"}]')

    mock_llm.complete.side_effect = _capture
    sibling_a.has_real_data = True
    sibling_a.metrics = {"x": 1.0}
    sibling_b.has_real_data = True
    sibling_b.metrics = {"x": 1.0}
    bfts.expand(parent, existing_children=[sibling_a, sibling_b])
    text = captured["prompt"]
    assert "files_added=['tile.py']" in text
    assert "files_added=['prefetch.py']" in text


def test_expand_sets_original_direction(bfts, mock_llm):
    """The direction text the LLM chose must be preserved verbatim on the
    child as `original_direction`, even after the evaluator later overwrites
    `eval_summary`."""
    mock_llm.complete.return_value = LLMResponse(
        content='[{"label": "improve", "direction": "Sweep k=1..930 fp32/fp64"}]'
    )
    node = Node(id="n1", parent_id=None, depth=0)
    children = bfts.expand(node)
    assert len(children) == 1
    child = children[0]
    assert child.original_direction == "Sweep k=1..930 fp32/fp64"
    # Simulate evaluator overwriting eval_summary on completion.
    child.eval_summary = "evaluator reason [scientific_score=0.4]"
    assert child.original_direction == "Sweep k=1..930 fp32/fp64"
