"""Tests for the configurable BFTSConfig.frontier_score strategies."""

from __future__ import annotations

import math
from unittest.mock import MagicMock

import pytest

from ari.config import BFTSConfig
from ari.llm.client import LLMClient
from ari.orchestrator.bfts import BFTS
from ari.orchestrator.node import Node, NodeLabel


def _node(node_id: str, score: float, depth: int = 0, label: NodeLabel = NodeLabel.DRAFT) -> Node:
    n = Node(id=node_id, parent_id=None, depth=depth, label=label)
    n.metrics = {"_scientific_score": score}
    return n


def _bfts(**cfg_overrides) -> BFTS:
    cfg = BFTSConfig(max_depth=3, max_total_nodes=10, **cfg_overrides)
    return BFTS(cfg, MagicMock(spec=LLMClient))


def test_scientific_only_returns_raw_score():
    bfts = _bfts(frontier_score="scientific_only")
    n = _node("a", 0.7)
    # Even if the label-history says this label is rare, no bonus is added.
    bfts._recent_label_history = ["other"] * 5
    assert bfts._fallback_score(n) == pytest.approx(0.7)


def test_scientific_plus_diversity_adds_bonus():
    bfts = _bfts(frontier_score="scientific_plus_diversity")
    n = _node("a", 0.7)
    bfts._recent_label_history = ["other"] * 5  # makes draft underrepresented
    assert bfts._fallback_score(n) == pytest.approx(0.75)


def test_depth_penalized_subtracts_lambda_times_depth():
    bfts = _bfts(frontier_score="depth_penalized", depth_penalty_lambda=0.1)
    n = _node("a", 0.7, depth=3)
    # Empty history → diversity_bonus = 0 → 0.7 - 0.1*3 = 0.4
    assert bfts._fallback_score(n) == pytest.approx(0.4)


def test_ucb_like_adds_exploration_term_for_unvisited_node():
    bfts = _bfts(frontier_score="ucb_like", ucb_c=1.0)
    n = _node("a", 0.5)
    # Empty history, unvisited node → score = 0.5 + 0 + 1.0 * sqrt(log(1)/1) = 0.5
    # (log(1)=0, so the exploration term is exactly zero in the empty case).
    assert bfts._fallback_score(n, frontier_size=1) == pytest.approx(0.5)


def test_ucb_like_explored_node_with_history_gets_bonus():
    bfts = _bfts(frontier_score="ucb_like", ucb_c=1.0)
    bfts._expansion_count = {"other": 3}  # total_visits=3, N=3+frontier_size
    n = _node("a", 0.5)
    expected = 0.5 + 1.0 * math.sqrt(math.log(3 + 2) / 1)
    assert bfts._fallback_score(n, frontier_size=2) == pytest.approx(expected)


def test_select_fallback_picks_highest_under_strategy():
    """When ucb_like is selected the lower-score node with zero visits
    should still win against a higher-score node that has been expanded
    many times, given a high enough ucb_c."""
    bfts = _bfts(frontier_score="ucb_like", ucb_c=2.0)
    bfts._expansion_count = {"hot": 5}  # "hot" already expanded a lot
    hot = _node("hot", 0.7)
    cold = _node("cold", 0.5)
    pick = bfts._select_fallback([hot, cold])
    assert pick.id == "cold"


def test_unknown_strategy_falls_back_to_diversity():
    """Hand-edited YAML with an unknown strategy must not crash; the
    default scientific_plus_diversity path takes over."""
    bfts = _bfts()
    bfts.config = bfts.config.model_copy(update={"frontier_score": "scientific_plus_diversity"})
    # Force-write an unexpected value via the underlying dict to simulate
    # a YAML typo that pydantic would normally reject.
    object.__setattr__(bfts.config, "frontier_score", "garbage")
    n = _node("a", 0.7)
    # Should fall back to scientific_plus_diversity (no crash).
    assert bfts._fallback_score(n) == pytest.approx(0.7)
