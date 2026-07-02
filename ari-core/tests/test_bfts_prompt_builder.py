"""Golden-string tests for ari/orchestrator/bfts_prompt_builder.py (subtask 011).

These pin the *byte-exact* output of the pure prompt-context builders that were
extracted out of ``BFTS`` so that the extraction is (and stays) behaviour /
byte-identical (design principle P2 determinism). They complement the prompt
assertions already in ``test_bfts.py`` / ``test_bfts_diversity.py`` (which
capture the assembled prompt end-to-end).
"""
from __future__ import annotations

from ari.config import BFTSConfig
from ari.orchestrator.bfts_prompt_builder import (
    _BUDGET,
    build_expand_context,
    build_expand_select_candidate_descriptions,
    build_select_candidate_descriptions,
)
from ari.orchestrator.node import Node, NodeLabel, NodeStatus


def _cand() -> Node:
    n = Node(
        id="node_aaaaaaaa", parent_id=None, depth=1, label=NodeLabel.IMPROVE,
        has_real_data=True, metrics={"_scientific_score": 0.5},
    )
    n.eval_summary = "did stuff"
    return n


def test_budget_reexport_from_bfts_module():
    """``ari.orchestrator.bfts._BUDGET`` must keep resolving after the move."""
    from ari.orchestrator import bfts as bfts_mod

    assert bfts_mod._BUDGET is _BUDGET
    assert bfts_mod._BUDGET.list_top_n == 5
    assert bfts_mod._BUDGET.candidate_summary_select_chars == 120
    assert bfts_mod._BUDGET.candidate_summary_expand_chars == 150


def test_build_select_candidate_descriptions_golden():
    out = build_select_candidate_descriptions([_cand()], [0.05])
    assert out == [
        '[0] id=aaaaaaaa, depth=1, label=improve, has_real_data=True, '
        'metrics={"_scientific_score": 0.5}, summary=\'did stuff\', '
        'diversity_bonus=+0.05'
    ]


def test_build_select_candidate_descriptions_no_bonus_when_zero():
    out = build_select_candidate_descriptions([_cand()], [0.0])
    assert "diversity_bonus" not in out[0]


def test_build_expand_select_candidate_descriptions_golden():
    out = build_expand_select_candidate_descriptions([_cand()])
    assert out == [
        '[0] id=aaaaaaaa, depth=1, label=improve, has_real_data=True, '
        'metrics={"_scientific_score": 0.5}, summary=\'did stuff\''
    ]


def test_build_expand_context_golden_blocks():
    parent = Node(
        id="node_par0000c", parent_id=None, depth=0, has_real_data=True,
        metrics={"_scientific_score": 0.6},
    )
    parent.eval_summary = "baseline"
    ctx = build_expand_context(
        parent, BFTSConfig(max_depth=3, max_total_nodes=10),
        experiment_goal="goal", budget_remaining=7,
    )
    assert ctx["goal_line"] == "Experiment goal: goal\n"
    assert ctx["parent_status"] == "succeeded"
    assert ctx["parent_id_short"] == "par0000c"
    assert ctx["parent_depth"] == 0
    assert ctx["depth_note"] == "Current depth: 0 / max_depth 3 (child will be at depth 1)\n"
    assert ctx["budget_note"] == "Remaining node budget: 7 / 10\n"
    assert ctx["sci_note"] == "Parent scientific score: 0.60/1.0\n"
    assert ctx["siblings_block"] == "Sibling scores at same depth: (none)\n\n"
    assert ctx["ancestors_block"] == "Ancestor scores: (none)\n\n"
    assert ctx["existing_block"] == (
        "Already-spawned children of THIS parent: "
        "(none — this is the first child)\n\n"
    )
    assert ctx["diversity_block"] == (
        "Tree diversity so far:\n"
        "  unique labels observed: (none)\n"
        "  depth distribution: (empty)\n\n"
    )
    assert ctx["parent_metrics_json"] == '{"_scientific_score": 0.6}'
    assert ctx["parent_summary"] == "baseline"


def test_build_expand_context_saturation_and_diversity():
    parent = Node(id="node_par00000", parent_id=None, depth=0, has_real_data=True)
    children = [
        Node(id=f"node_c{i:07d}", parent_id="node_par00000", depth=1,
             label=NodeLabel.IMPROVE, status=NodeStatus.PENDING)
        for i in range(3)
    ]
    ctx = build_expand_context(
        parent, BFTSConfig(max_depth=3, max_total_nodes=10),
        existing_children=children, all_run_nodes=[parent] + children,
    )
    assert "improve=3" in ctx["existing_block"]
    assert "saturated" in ctx["existing_block"]
    assert "propose a DIFFERENT label" in ctx["existing_block"]
    # budget omitted -> empty note
    assert ctx["budget_note"] == ""


def test_build_expand_context_keys_match_template():
    """The builder's dict keys must be exactly the placeholders the shipped
    ``orchestrator/bfts_expand.md`` template expects, so ``.format(**ctx)``
    neither raises KeyError nor leaves unfilled fields."""
    from ari.prompts import FilesystemPromptLoader

    parent = Node(id="node_par0000c", parent_id=None, depth=0, has_real_data=True)
    ctx = build_expand_context(parent, BFTSConfig(max_depth=3, max_total_nodes=10))
    tmpl, _ = FilesystemPromptLoader().load_versioned("orchestrator/bfts_expand")
    # Should not raise (KeyError = missing key; IndexError = positional field).
    rendered = tmpl.format(**ctx)
    assert isinstance(rendered, str) and rendered
