"""Tests for the handoff-study deterministic selector (G9a).

With BFTSConfig.deterministic_selector set, both BFTS selectors must bypass the
stochastic LLM and rank by the deterministic frontier scorer — so node selection
is reproducible (PREREG §7.1) and never calls the LLM.
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock

from ari.config import BFTSConfig, ARIConfig, apply_bfts_env_overrides
from ari.llm.client import LLMClient
from ari.orchestrator.bfts import BFTS
from ari.orchestrator.node import Node, NodeLabel


def _node(node_id: str, score: float) -> Node:
    n = Node(id=node_id, parent_id=None, depth=1, label=NodeLabel.DRAFT)
    n.metrics = {"_scientific_score": score}
    return n


def _bfts() -> BFTS:
    cfg = BFTSConfig(deterministic_selector=True, frontier_score="scientific_only")
    return BFTS(cfg, MagicMock(spec=LLMClient))


def test_select_next_node_deterministic_picks_top_score_without_llm():
    bfts = _bfts()
    chosen = bfts.select_next_node(
        [_node("a", 0.1), _node("b", 0.9), _node("c", 0.5)], "goal", MagicMock())
    assert chosen.id == "b"
    bfts.llm.complete.assert_not_called()


def test_select_best_to_expand_deterministic_picks_top_score_without_llm():
    bfts = _bfts()
    chosen = bfts.select_best_to_expand(
        [_node("x", 0.2), _node("y", 0.8)], "goal", MagicMock())
    assert chosen.id == "y"
    bfts.llm.complete.assert_not_called()


def test_default_is_off():
    assert BFTSConfig().deterministic_selector is False


def test_env_override_sets_flag():
    cfg = ARIConfig()
    os.environ["ARI_BFTS_DETERMINISTIC"] = "1"
    try:
        apply_bfts_env_overrides(cfg)
        assert cfg.bfts.deterministic_selector is True
    finally:
        os.environ.pop("ARI_BFTS_DETERMINISTIC", None)
