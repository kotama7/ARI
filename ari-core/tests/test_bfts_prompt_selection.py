"""Verify BFTS reads prompt names from BFTSConfig."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ari.config import BFTSConfig
from ari.llm.client import LLMClient, LLMResponse
from ari.orchestrator.bfts import BFTS
from ari.orchestrator.node import Node, NodeLabel


def _node(nid: str, score: float = 0.5) -> Node:
    n = Node(id=nid, parent_id=None, depth=1, label=NodeLabel.DRAFT)
    n.has_real_data = True
    n.metrics = {"_scientific_score": score}
    n.eval_summary = "stub"
    return n


def _bfts(**overrides) -> BFTS:
    cfg = BFTSConfig(max_depth=3, max_total_nodes=10, **overrides)
    llm = MagicMock(spec=LLMClient)
    llm.complete.return_value = LLMResponse(content="0")
    return BFTS(cfg, llm)


def test_select_next_node_uses_configured_prompt_key():
    bfts = _bfts(select_prompt="orchestrator/bfts_select_variant")
    memory = MagicMock()
    memory.search.return_value = []
    captured: list[str] = []

    class _FakeLoader:
        def load(self, key):
            captured.append(key)
            # Echo the placeholders so .format() succeeds.
            return "goal={experiment_goal} mem={memory_context} cands={candidates}"

    with patch(
        "ari.prompts.FilesystemPromptLoader",
        new=_FakeLoader,
    ):
        bfts.select_next_node([_node("a"), _node("b")], "goal", memory)

    assert captured == ["orchestrator/bfts_select_variant"]


def test_select_best_to_expand_uses_configured_prompt_key():
    bfts = _bfts(expand_select_prompt="orchestrator/bfts_expand_select_variant")
    captured: list[str] = []

    class _FakeLoader:
        def load(self, key):
            captured.append(key)
            return "goal={experiment_goal} cands={candidates}"

    with patch(
        "ari.prompts.FilesystemPromptLoader",
        new=_FakeLoader,
    ):
        bfts.select_best_to_expand([_node("a"), _node("b")], "goal", MagicMock())

    assert captured == ["orchestrator/bfts_expand_select_variant"]


def test_defaults_match_legacy_prompt_keys():
    bfts = _bfts()
    assert bfts.config.select_prompt == "orchestrator/bfts_select"
    assert bfts.config.expand_select_prompt == "orchestrator/bfts_expand_select"
