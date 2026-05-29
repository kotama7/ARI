"""Tests for ari/orchestrator/bfts.py - BFTS pruning and node selection."""

from unittest.mock import MagicMock, patch

import pytest

from ari.config import BFTSConfig
from ari.llm.client import LLMClient, LLMResponse
from ari.orchestrator import bfts as bfts_mod
from ari.orchestrator.bfts import BFTS, _extract_directions_json, _infer_label_from_text
from ari.orchestrator.node import Node, NodeLabel, NodeStatus


@pytest.fixture
def bfts_config():
    return BFTSConfig(max_depth=3, max_total_nodes=10)


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


# ── B-1 / B-2 / B-4: should_prune semantics ──────────────────────────


def test_should_prune_when_total_at_max(bfts):
    """current_total at the configured cap triggers pruning (B-1)."""
    node = Node(id="n1", parent_id=None, depth=0, has_real_data=True)
    assert bfts.should_prune(node, current_total=10) is True


def test_should_prune_under_budget(bfts):
    """current_total below the cap with shallow depth must not prune."""
    node = Node(id="n1", parent_id=None, depth=1)
    assert bfts.should_prune(node, current_total=0) is False


def test_should_prune_at_max_depth(bfts):
    """depth >= max_depth activates the previously-dead config (B-2)."""
    node = Node(id="n1", parent_id=None, depth=3, has_real_data=True)
    assert bfts.should_prune(node, current_total=0) is True


def test_should_prune_below_max_depth(bfts):
    node = Node(id="n1", parent_id=None, depth=2, has_real_data=True)
    assert bfts.should_prune(node, current_total=0) is False


def test_should_prune_when_sterile(bfts):
    """metrics._sterile=True retires the node from frontier (B-4)."""
    node = Node(id="n1", parent_id=None, depth=0, has_real_data=False,
                metrics={"_sterile": True})
    assert bfts.should_prune(node, current_total=0) is True


def test_should_not_prune_normal_node(bfts):
    node = Node(id="n1", parent_id=None, depth=1, has_real_data=True,
                metrics={"_scientific_score": 0.7})
    assert bfts.should_prune(node, current_total=0) is False


def test_expand_does_not_set_bfts_counter(bfts, mock_llm):
    """B-1: BFTS no longer carries a ``total_nodes`` integer."""
    assert not hasattr(bfts, "total_nodes")


def test_expansion_count_tracks_expand_calls(bfts, mock_llm):
    """B-6: expansion_count(node_id) grows with each expand() call."""
    mock_llm.complete.return_value = LLMResponse(
        content='[{"label": "improve", "direction": "x"}]'
    )
    parent = Node(id="p1", parent_id=None, depth=0, has_real_data=True)
    assert bfts.expansion_count(parent.id) == 0
    bfts.expand(parent)
    bfts.expand(parent)
    bfts.expand(parent)
    assert bfts.expansion_count(parent.id) == 3


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


# ── B-2: expand prompt carries depth + max_depth ─────────────────────


def test_expand_prompt_contains_depth_note(bfts, mock_llm):
    mock_llm.complete.return_value = LLMResponse(
        content='[{"label": "improve", "direction": "x"}]'
    )
    parent = Node(id="p", parent_id=None, depth=1, has_real_data=True)
    bfts.expand(parent)
    prompt = mock_llm.complete.call_args[0][0][0].content
    assert "max_depth" in prompt
    assert "Current depth: 1" in prompt


# ── I-4: budget_remaining surfaces when caller provides it ───────────


def test_expand_prompt_contains_budget_when_provided(bfts, mock_llm):
    mock_llm.complete.return_value = LLMResponse(
        content='[{"label": "improve", "direction": "x"}]'
    )
    parent = Node(id="p", parent_id=None, depth=0, has_real_data=True)
    bfts.expand(parent, budget_remaining=12)
    prompt = mock_llm.complete.call_args[0][0][0].content
    assert "Remaining node budget: 12" in prompt


def test_expand_prompt_omits_budget_when_not_provided(bfts, mock_llm):
    mock_llm.complete.return_value = LLMResponse(
        content='[{"label": "improve", "direction": "x"}]'
    )
    parent = Node(id="p", parent_id=None, depth=0, has_real_data=True)
    bfts.expand(parent, budget_remaining=None)
    prompt = mock_llm.complete.call_args[0][0][0].content
    assert "Remaining node budget:" not in prompt


# ── B-3 / B-8: candidate description format ─────────────────────────


def test_select_next_node_prompt_omits_retry_and_includes_label(bfts, mock_llm, mock_memory):
    mock_llm.complete.return_value = LLMResponse(content="0")
    nodes = [
        Node(id="aaa", parent_id=None, depth=0, label=NodeLabel.IMPROVE),
        Node(id="bbb", parent_id=None, depth=0, label=NodeLabel.ABLATION),
    ]
    bfts.select_next_node(nodes, "goal", mock_memory)
    prompt = mock_llm.complete.call_args[0][0][0].content
    assert "retry=" not in prompt
    assert "label=improve" in prompt
    assert "label=ablation" in prompt


# ── B-7: fallback child inherits attrs ──────────────────────────────


def test_expand_fallback_inherits_memory_and_direction(bfts, mock_llm):
    mock_llm.complete.return_value = LLMResponse(content="")
    parent = Node(
        id="p", parent_id=None, depth=0, has_real_data=True,
        memory_snapshot=[{"k": "v"}],
    )
    children = bfts.expand(parent)
    assert len(children) == 1
    fb = children[0]
    assert fb.memory_snapshot == [{"k": "v"}]
    assert fb.eval_summary
    assert fb.original_direction
    assert fb.raw_label == ""
    # memory_snapshot is a defensive copy.
    parent.memory_snapshot.append({"k2": "v2"})
    assert {"k2": "v2"} not in fb.memory_snapshot


# ── B-9: JSON extraction robust against <think> wrapping ─────────────


def test_extract_directions_strips_think_block():
    raw = '<think>chatter</think>[{"label":"improve","direction":"x"}]'
    assert _extract_directions_json(raw) == [{"label": "improve", "direction": "x"}]


def test_extract_directions_handles_multiple_brackets():
    raw = 'options [a, b] and [c]: [{"label":"draft","direction":"y"}]'
    result = _extract_directions_json(raw)
    assert isinstance(result, list)
    assert result[0] == {"label": "draft", "direction": "y"}


def test_extract_directions_falls_back_to_plain_text():
    assert _extract_directions_json("Try ablation of cache") == ["Try ablation of cache"]


def test_expand_with_thinking_response_assigns_label(bfts, mock_llm):
    mock_llm.complete.return_value = LLMResponse(
        content='<think>I will choose validation</think>'
                '[{"label":"validation","direction":"verify seed=42"}]'
    )
    parent = Node(id="p", parent_id=None, depth=0, has_real_data=True)
    children = bfts.expand(parent)
    assert children[0].label == NodeLabel.VALIDATION


# ── I-6: regex-based label inference (no false positives on "invalid") ─


def test_infer_label_debug_when_no_real_data():
    assert _infer_label_from_text("anything", parent_has_real_data=False) == NodeLabel.DEBUG


def test_infer_label_ablation():
    assert _infer_label_from_text("Ablate warmup", parent_has_real_data=True) == NodeLabel.ABLATION


def test_infer_label_validation():
    assert (
        _infer_label_from_text("Reproduce with seed=42", parent_has_real_data=True)
        == NodeLabel.VALIDATION
    )


def test_infer_label_improve():
    assert (
        _infer_label_from_text("Tune the TILE for higher throughput", parent_has_real_data=True)
        == NodeLabel.IMPROVE
    )


def test_infer_label_default_draft():
    assert (
        _infer_label_from_text("Investigate a fresh architecture", parent_has_real_data=True)
        == NodeLabel.DRAFT
    )


def test_infer_label_no_false_positive_on_invalid():
    """Word boundaries: 'invalid' must NOT trigger VALIDATION."""
    assert (
        _infer_label_from_text("Skip invalid memory access", parent_has_real_data=True)
        == NodeLabel.DRAFT
    )


# ── L-1: _make_node_name normalisation ──────────────────────────────


def test_make_node_name_normalizes_fullwidth():
    name = bfts_mod._make_node_name("improve", "ＴＩＬＥ tuning", 1)
    assert "TILE tuning" in name


def test_make_node_name_collapses_whitespace():
    name = bfts_mod._make_node_name("improve", "x    with   gaps", 1)
    assert "x with gaps" in name


# ── L-2: prompt budget defaults match legacy magic numbers ──────────


def test_prompt_budget_defaults_match_legacy_values():
    b = bfts_mod._BUDGET
    assert b.parent_delta_chars == 240
    assert b.parent_concern_chars == 200
    assert b.parent_hint_chars == 200
    assert b.candidate_summary_select_chars == 120
    assert b.candidate_summary_expand_chars == 150
    assert b.sibling_direction_chars == 160
    assert b.list_top_n == 5


# ── L-6: saturation threshold is configurable ───────────────────────


def test_label_saturation_threshold_default():
    assert BFTSConfig().label_saturation_threshold == 2


def test_expand_uses_saturation_threshold_from_config(mock_llm):
    cfg = BFTSConfig(max_depth=3, max_total_nodes=10, label_saturation_threshold=3)
    bfts = BFTS(cfg, mock_llm)
    mock_llm.complete.return_value = LLMResponse(
        content='[{"label":"ablation","direction":"x"}]'
    )
    parent = Node(id="p", parent_id=None, depth=0, has_real_data=True)
    children_existing = [
        Node(id=f"c{i}", parent_id="p", depth=1, label=NodeLabel.IMPROVE,
             status=NodeStatus.PENDING)
        for i in range(2)
    ]
    bfts.expand(parent, existing_children=children_existing)
    prompt = mock_llm.complete.call_args[0][0][0].content
    # cnt=2 must NOT trip saturation when threshold=3
    assert "saturated" not in prompt


# ── I-1: prompt prefers canonical labels but no longer forbids inventions ─


def test_expand_prompt_no_longer_forbids_inventions(bfts, mock_llm):
    mock_llm.complete.return_value = LLMResponse(
        content='[{"label":"improve","direction":"x"}]'
    )
    parent = Node(id="p", parent_id=None, depth=0, has_real_data=True)
    bfts.expand(parent)
    prompt = mock_llm.complete.call_args[0][0][0].content
    assert "no inventions" not in prompt
    assert "no other strings allowed" not in prompt
    assert "strongly prefer" in prompt.lower()


# ── I-3 / L-3: shared fallback uses diversity bonus ─────────────────


def test_select_best_to_expand_fallback_uses_diversity_bonus(bfts, mock_llm, mock_memory):
    for _ in range(6):
        bfts.record_run(Node(id="h", parent_id=None, depth=0, label=NodeLabel.IMPROVE))
    a = Node(id="a", parent_id=None, depth=1, label=NodeLabel.IMPROVE,
             has_real_data=True, metrics={"_scientific_score": 0.5})
    b = Node(id="b", parent_id=None, depth=1, label=NodeLabel.VALIDATION,
             has_real_data=True, metrics={"_scientific_score": 0.5})
    mock_llm.complete.return_value = LLMResponse(content="not a number")
    chosen = bfts.select_best_to_expand([a, b], "goal", mock_memory)
    assert chosen.id == "b"


# ── I-5: _resolve_pm_and_run_id boundary cases ──────────────────────


def test_resolve_pm_and_run_id_returns_none_when_env_unset(monkeypatch):
    monkeypatch.delenv("ARI_CHECKPOINT_DIR", raising=False)
    assert bfts_mod._resolve_pm_and_run_id() is None


# ── I-8: report cache honours mtime ─────────────────────────────────


def test_get_node_report_caches_when_mtime_unchanged(bfts, tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
    run_id = "run0"
    ckpt = workspace / "checkpoints" / run_id
    ckpt.mkdir(parents=True)
    node_id = "node_abc12345"
    wd = workspace / "experiments" / run_id / node_id
    wd.mkdir(parents=True)
    rp = wd / "node_report.json"
    import json as _json
    rp.write_text(_json.dumps({"v": 1}))
    monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(ckpt))
    a = bfts._get_node_report(node_id)
    assert a == {"v": 1}
    # Second hit comes from cache — verify by mutating the file without
    # touching mtime; we should still see v=1.
    rp.write_text(_json.dumps({"v": 2}))
    # Force mtime back so the cache key matches.
    import os as _os
    stat = rp.stat()
    _os.utime(str(rp), ns=(stat.st_atime_ns, list(bfts._report_cache.values())[0][0]))
    b = bfts._get_node_report(node_id)
    assert b == {"v": 1}


def test_get_node_report_invalidates_on_mtime_advance(bfts, tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
    run_id = "run0"
    ckpt = workspace / "checkpoints" / run_id
    ckpt.mkdir(parents=True)
    node_id = "node_xyz67890"
    wd = workspace / "experiments" / run_id / node_id
    wd.mkdir(parents=True)
    rp = wd / "node_report.json"
    import json as _json
    rp.write_text(_json.dumps({"v": 1}))
    monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(ckpt))
    assert bfts._get_node_report(node_id) == {"v": 1}
    import time as _t
    _t.sleep(0.01)
    rp.write_text(_json.dumps({"v": 2}))
    assert bfts._get_node_report(node_id) == {"v": 2}


# ── I-9: concurrent record_run leaves history bounded ───────────────


def test_record_run_concurrent_appends_bounded(bfts):
    from concurrent.futures import ThreadPoolExecutor

    labels = [NodeLabel.DRAFT, NodeLabel.IMPROVE, NodeLabel.VALIDATION]

    def go(i):
        n = Node(id=f"n{i}", parent_id=None, depth=0, label=labels[i % 3])
        bfts.record_run(n)

    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(go, range(200)))
    assert len(bfts._recent_label_history) == bfts._max_recent_labels
