"""Integration tests for the configurable BFTS evaluation layers.

Covers:
  - YAML round-trip: load_config() picks up new evaluator/bfts keys.
  - Default behaviour: empty YAML yields back-compat values.
  - End-to-end: LLMEvaluator.evaluate() emits different _scientific_score
    values for the same axis_scores depending on `composite`.
  - Edge cases: depth_penalized with λ=0, custom axis_mode with empty list,
  - core.py axis_mode dispatch shape (light: covers branching, not full run).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from ari.config import ARIConfig, BFTSConfig, EvaluatorConfig, load_config
from ari.evaluator.dynamic_axes import AxisDef
from ari.evaluator.llm_evaluator import (
    AXIS_NAMES,
    LLMEvaluator,
    MetricSpec,
    _COMPOSITES,
)
from ari.llm.client import LLMClient
from ari.orchestrator.bfts import BFTS
from ari.orchestrator.node import Node, NodeLabel


# ── YAML round-trip ──────────────────────────────────────────────────


def test_default_config_has_back_compat_defaults():
    """Pydantic defaults match the legacy hard-coded behaviour."""
    cfg = ARIConfig()
    assert cfg.evaluator.composite == "harmonic_mean"
    assert cfg.evaluator.axis_mode == "dynamic"
    assert cfg.evaluator.custom_axes == []
    assert cfg.bfts.frontier_score == "scientific_plus_diversity"
    assert cfg.bfts.depth_penalty_lambda == pytest.approx(0.05)
    assert cfg.bfts.ucb_c == pytest.approx(0.5)
    assert cfg.bfts.select_prompt == "orchestrator/bfts_select"
    assert cfg.bfts.expand_select_prompt == "orchestrator/bfts_expand_select"


def test_default_yaml_file_loads_new_keys(tmp_path):
    """The shipped default.yaml must parse cleanly and expose the new keys.

    We copy the file into ``tmp_path`` so ``load_config`` runs through its
    full pipeline, then manually clean up the env vars that
    ``_apply_memory_section`` populates via ``os.environ.setdefault`` —
    pytest's ``monkeypatch.delenv(raising=False)`` would *not* record the
    state of an absent key (see pytest's MonkeyPatch.delitem), so we
    cannot rely on its teardown for this case.
    """
    import os

    src = Path(__file__).resolve().parents[1] / "config" / "default.yaml"
    target = tmp_path / "default.yaml"
    target.write_text(src.read_text())
    leaked_keys = ("ARI_MEMORY_BACKEND", "LETTA_BASE_URL", "LETTA_EMBEDDING_CONFIG")
    snapshot = {k: os.environ.get(k) for k in leaked_keys}
    try:
        cfg = load_config(str(target))
        assert cfg.evaluator.composite == "harmonic_mean"
        assert cfg.evaluator.axis_mode == "dynamic"
        assert cfg.bfts.frontier_score == "scientific_plus_diversity"
        assert cfg.bfts.select_prompt == "orchestrator/bfts_select"
    finally:
        for k, v in snapshot.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_yaml_override_propagates(tmp_path):
    """A minimal user YAML overrides the new fields and Pydantic accepts."""
    raw = {
        "evaluator": {
            "composite": "weighted_min",
            "axis_mode": "custom",
            "custom_axes": [
                {"name": "speedup", "description": "x faster", "weight": 0.5},
                {"name": "accuracy", "description": "% correct", "weight": 0.5},
            ],
        },
        "bfts": {
            "frontier_score": "ucb_like",
            "ucb_c": 1.5,
            "depth_penalty_lambda": 0.2,
            "select_prompt": "orchestrator/my_select",
            "expand_select_prompt": "orchestrator/my_expand_select",
        },
    }
    path = tmp_path / "user.yaml"
    path.write_text(yaml.safe_dump(raw))
    cfg = load_config(str(path))
    assert cfg.evaluator.composite == "weighted_min"
    assert cfg.evaluator.axis_mode == "custom"
    assert [(a.name, a.weight) for a in cfg.evaluator.custom_axes] == [
        ("speedup", 0.5),
        ("accuracy", 0.5),
    ]
    assert cfg.bfts.frontier_score == "ucb_like"
    assert cfg.bfts.ucb_c == pytest.approx(1.5)
    assert cfg.bfts.depth_penalty_lambda == pytest.approx(0.2)
    assert cfg.bfts.select_prompt == "orchestrator/my_select"
    assert cfg.bfts.expand_select_prompt == "orchestrator/my_expand_select"


def test_yaml_rejects_unknown_composite(tmp_path):
    """Pydantic Literal must reject an unsupported composite formula."""
    raw = {"evaluator": {"composite": "nonexistent"}}
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(raw))
    with pytest.raises(Exception):  # pydantic.ValidationError
        load_config(str(path))


def test_yaml_rejects_unknown_frontier_score(tmp_path):
    raw = {"bfts": {"frontier_score": "bogus"}}
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(raw))
    with pytest.raises(Exception):
        load_config(str(path))


# ── End-to-end: composite changes the _scientific_score ───────────────


class _StubLLMResponse:
    def __init__(self, content):
        self.content = content


def _stub_judge_response() -> _StubLLMResponse:
    """Force the LLM to return a fixed uneven axis_scores payload."""
    payload = {
        "reason": "stub",
        "has_real_data": True,
        "axis_scores": {
            "measurement_validity": 0.1,
            "comparative_rigor": 0.9,
            "novelty": 0.9,
            "reproducibility": 0.9,
            "clarity_of_contribution": 0.9,
        },
        "axis_rationales": {},
    }
    return _StubLLMResponse(json.dumps(payload))


def _run_with_composite(composite: str) -> float:
    """Invoke evaluate_sync() with a stubbed judge and return _scientific_score."""
    ev = LLMEvaluator(
        model="stub",
        metric_spec=MetricSpec(),
        composite=composite,
    )

    # litellm.acompletion is awaited inside evaluate(); patch it with an
    # async stub that returns the fixed JSON payload.
    fake_msg = MagicMock()
    fake_msg.content = _stub_judge_response().content
    fake_choice = MagicMock()
    fake_choice.message = fake_msg
    fake_response = MagicMock()
    fake_response.choices = [fake_choice]

    async def _fake_acompletion(**_kwargs):
        return fake_response

    import litellm

    with patch.object(litellm, "acompletion", new=_fake_acompletion):
        result = ev.evaluate_sync(
            goal="goal",
            artifacts=[],
            summary="stub",
            node_id="n0",
            node_label="draft",
        )
    return result["scientific_score"]


def test_composites_yield_different_scores_end_to_end():
    """Same axis_scores must collapse to ordered different scalars."""
    scores = {name: _run_with_composite(name) for name in _COMPOSITES}
    assert scores["weighted_min"] == pytest.approx(0.1, abs=1e-6)
    # HM ≤ GM ≤ AM, all strictly above the bottleneck.
    assert scores["harmonic_mean"] <= scores["geometric_mean"]
    assert scores["geometric_mean"] <= scores["arithmetic_mean"]
    assert scores["weighted_min"] < scores["harmonic_mean"]


# ── Edge cases for BFTS frontier strategies ───────────────────────────


def _node(nid: str, score: float, depth: int = 0) -> Node:
    n = Node(id=nid, parent_id=None, depth=depth, label=NodeLabel.DRAFT)
    n.metrics = {"_scientific_score": score}
    return n


def _bfts(**cfg_overrides) -> BFTS:
    cfg = BFTSConfig(max_depth=5, max_total_nodes=20, **cfg_overrides)
    return BFTS(cfg, MagicMock(spec=LLMClient))


def test_depth_penalty_lambda_zero_degrades_to_plus_diversity():
    """λ=0 means depth_penalized is numerically identical to the default."""
    bfts_a = _bfts(frontier_score="depth_penalized", depth_penalty_lambda=0.0)
    bfts_b = _bfts(frontier_score="scientific_plus_diversity")
    n = _node("a", 0.8, depth=4)
    assert bfts_a._fallback_score(n) == pytest.approx(bfts_b._fallback_score(n))


def test_ucb_c_zero_degrades_to_plus_diversity():
    """c=0 strips the exploration term."""
    bfts_a = _bfts(frontier_score="ucb_like", ucb_c=0.0)
    bfts_b = _bfts(frontier_score="scientific_plus_diversity")
    n = _node("a", 0.6, depth=2)
    assert bfts_a._fallback_score(n, frontier_size=4) == pytest.approx(
        bfts_b._fallback_score(n)
    )


def test_node_with_missing_scientific_score_yields_zero():
    """Frontier score must remain finite when _scientific_score is absent."""
    bfts = _bfts(frontier_score="depth_penalized", depth_penalty_lambda=0.1)
    n = Node(id="x", parent_id=None, depth=2, label=NodeLabel.DRAFT)
    n.metrics = {}  # no _scientific_score
    score = bfts._fallback_score(n)
    # 0 (sci) + 0 (diversity, empty history) - 0.1*2 = -0.2
    assert score == pytest.approx(-0.2)


# ── Custom axis_mode round-trip ───────────────────────────────────────


def test_custom_axes_with_empty_list_falls_through_to_legacy():
    """axis_mode=custom with no axes should still construct (degenerate)."""
    ev = LLMEvaluator(model="stub", axes=[])
    # When axes is falsy, the constructor falls through to the legacy path.
    assert ev._axis_names == AXIS_NAMES


def test_custom_axis_def_weights_used_in_resolved_weights():
    custom = [
        AxisDef(name="a", description="", source="custom", weight=0.3),
        AxisDef(name="b", description="", source="custom", weight=0.7),
    ]
    ev = LLMEvaluator(model="stub", axes=custom)
    resolved = ev._resolve_axis_weights()
    assert resolved == {"a": 0.3, "b": 0.7}
