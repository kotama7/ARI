"""Typed survey/idea contract, replay, and deterministic preflight tests."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import contracts  # noqa: E402
import server  # noqa: E402
from ari.public.research_contract import (  # noqa: E402
    IdeaGenerationProvenanceV1,
    IdeaSetV1,
    ResearchContractError,
    canonical_digest,
    parse_survey_snapshot,
)


PAPERS = [
    {
        "title": "Grounding Paper",
        "abstract": "A prior controlled result.",
        "year": 2025,
        "citationCount": 4,
        "paperId": "p1",
        "authors": [{"name": "A. Author"}],
    }
]


def _metric_data(unit: str = "fraction", citation: str = "s2:p1") -> dict:
    return {
        "metric_contract": {
            "name": "error_rate",
            "unit": unit,
            "direction": "lower",
            "comparison_scope": "same-environment",
            "rationale": "Tests the claimed reduction directly.",
            "required_evidence": ["error_rate", "baseline_error_rate"],
            "correctness_required": True,
            "normalization_ceiling": "not-applicable",
            "target_value": None,
        },
        "idea_contracts": [
            {
                "title": "Method X",
                "hypothesis": "Method X reduces error_rate against the baseline.",
                "falsification_conditions": [
                    "Reject when error_rate is not lower than baseline_error_rate."
                ],
                "citations": [citation],
                "artifact_references": [],
                "limitations": ["The claim is limited to the frozen input set."],
            }
        ],
    }


def _raw_idea() -> dict:
    return {
        "title": "Method X",
        "description": "Compare X with a fixed baseline.",
        "novelty": "Controlled mechanism",
        "feasibility": "Uses available tools",
        "experiment_plan": "Run X and baseline on identical inputs.",
        "novelty_score": 0.7,
        "feasibility_score": 0.9,
        "clarity_score": 0.8,
        "overall_score": 0.78,
    }


def _snapshot(tmp_path: Path):
    return contracts.build_survey_snapshot(
        PAPERS,
        query="topic",
        mode="record",
        provider="semantic-scholar",
        provider_version="graph-v1",
        retrieved_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        byte_reproducible=False,
        checkpoint_dir=tmp_path,
    )


def _lock(snapshot, adapter="default-discussion"):
    return contracts.build_generation_lock(
        adapter=adapter,
        model="fixed/model",
        api_base="https://user:secret@example.test/v1?token=secret",
        prompt_texts=("prompt-v1",),
        temperatures=(0.1,),
        seed=11,
        snapshot=snapshot,
        topic="topic",
        experiment_context="",
        generation_parameters={"n_ideas": 1},
        model_revision="fixed-revision",
    )


def test_record_then_offline_replay_is_exact(tmp_path, monkeypatch):
    monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(tmp_path))
    with patch("server._s2_search", return_value=PAPERS), patch(
        "server._s2_citations", return_value=[]
    ):
        recorded = server.survey("topic", max_papers=3, mode="record")

    with patch("server._s2_search", side_effect=AssertionError("network called")):
        replayed = server.survey("topic", max_papers=3, mode="replay")
    assert replayed["survey_snapshot"] == recorded["survey_snapshot"]
    assert replayed["survey_snapshot_digest"] == recorded["survey_snapshot_digest"]
    assert replayed["execution_mode"] == "replay"


def test_replay_rejects_snapshot_tampering(tmp_path, monkeypatch):
    monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(tmp_path))
    snapshot = _snapshot(tmp_path)
    path = tmp_path / "survey_snapshot_v1.json"
    document = json.loads(path.read_text())
    document["query"] = "tampered"
    path.write_text(json.dumps(document))
    with pytest.raises(ResearchContractError, match="snapshot_digest"):
        server.survey("topic", mode="replay")
    assert snapshot.snapshot_digest != canonical_digest(
        {k: v for k, v in document.items() if k != "snapshot_digest"}
    )


def test_complete_candidate_mints_one_contract_for_both_adapters(tmp_path):
    snapshot = _snapshot(tmp_path)
    results = []
    for adapter in ("default-discussion", "virsci-real"):
        lock = _lock(snapshot, adapter=adapter)
        idea_set, contract = contracts.build_idea_handoff(
            topic="topic",
            snapshot=snapshot,
            raw_ideas=[_raw_idea()],
            metric_data=_metric_data(),
            generation_lock=lock,
            generated_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
            requested_adapter=adapter,
            actual_adapter=adapter,
            fallback_reason=None,
        )
        assert isinstance(idea_set, IdeaSetV1)
        assert isinstance(idea_set.generation, IdeaGenerationProvenanceV1)
        assert len(idea_set.candidates) == 1
        assert not idea_set.rejections
        assert contract is not None
        assert contract.metric_contract.unit == "fraction"
        results.append((idea_set, contract))
    assert set(results[0][0].model_dump()) == set(results[1][0].model_dump())
    assert set(results[0][1].model_dump()) == set(results[1][1].model_dump())


@pytest.mark.parametrize(
    ("metric_data", "reason"),
    [
        (_metric_data(unit="unknown"), "unknown_unit"),
        (_metric_data(citation="s2:missing"), "unknown_citation"),
    ],
)
def test_preflight_rejects_unknown_scientific_identity(
    tmp_path, metric_data, reason
):
    snapshot = _snapshot(tmp_path)
    idea_set, contract = contracts.build_idea_handoff(
        topic="topic",
        snapshot=snapshot,
        raw_ideas=[_raw_idea()],
        metric_data=metric_data,
        generation_lock=_lock(snapshot),
        generated_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        requested_adapter="default-discussion",
        actual_adapter="default-discussion",
        fallback_reason=None,
    )
    assert contract is None
    assert not idea_set.candidates
    assert any(
        item == reason or item.startswith(reason + ":")
        for item in idea_set.rejections[0].reasons
    )


def test_generation_lock_is_stable_and_redacts_api_credentials(tmp_path):
    snapshot = _snapshot(tmp_path)
    lock_a = _lock(snapshot)
    lock_b = _lock(parse_survey_snapshot(snapshot.model_dump(mode="json")))
    assert lock_a.generation_lock_digest == lock_b.generation_lock_digest
    assert lock_a.api_base_identity == "https://example.test"
    assert "secret" not in json.dumps(lock_a.model_dump(mode="json"))
