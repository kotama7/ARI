"""Immutable metric proposal/admission and mint-once evaluator tests."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import pytest

from ari.public.claim_gate import (
    MetricContractProposalV1,
    parse_metric_gate_contract,
)
from ari.public.research_contract import (
    IdeaCandidateV1,
    IdeaGenerationLockV1,
    IdeaGenerationProvenanceV1,
    IdeaSetV1,
    MetricContractV1,
    MetricFormulaProvenanceV1,
    MetricToleranceV1,
    RetrievalRecordV1,
    SurveySnapshotV1,
    canonical_digest,
    mint_research_contract,
)
from src import server


def _typed_contract_document(tmp_path):
    now = datetime(2026, 8, 2, tzinfo=timezone.utc)
    record = RetrievalRecordV1(
        canonical_id="s2:p1",
        provider="semantic-scholar",
        query="q",
        retrieved_at=now,
        title="Prior work",
        payload_digest=canonical_digest({"paper": 1}),
    )
    snapshot = SurveySnapshotV1.create(
        mode="record",
        provider="semantic-scholar",
        query="q",
        retrieved_at=now,
        byte_reproducible=False,
        records=(record,),
    )
    lock = IdeaGenerationLockV1.create(
        adapter="test",
        adapter_version="1",
        model="provider/fixed-model",
        prompt_digests=(canonical_digest("idea prompt"),),
        temperatures=(0.0,),
        seed=7,
        source_snapshot_digest=snapshot.snapshot_digest,
        topic_digest=canonical_digest("q"),
        experiment_context_digest=canonical_digest(""),
        model_revision="fixed-revision",
    )
    metric = MetricContractV1.create(
        name="accuracy",
        unit="fraction",
        direction="higher",
        comparison_scope="same-environment",
        rationale="Directly evaluates the selected hypothesis.",
        required_evidence=("accuracy", "baseline_accuracy"),
        correctness_required=False,
        normalization_ceiling="not-applicable",
        formula="value",
        operands={"value": "accuracy"},
        tolerance=MetricToleranceV1(absolute=0.0, relative=0.01),
        formula_provenance=MetricFormulaProvenanceV1(
            source="idea-generation-lock",
            source_digest=lock.generation_lock_digest,
            model=lock.model,
            prompt_digests=lock.prompt_digests,
        ),
        confidence=0.95,
        admission_status="admitted",
    )
    candidate = IdeaCandidateV1.create(
        title="T",
        hypothesis="Method improves accuracy.",
        description="D",
        experiment_plan="Run a controlled comparison.",
        falsification_conditions=("Reject if accuracy does not improve.",),
        metric_contract=metric,
        citations=(record.canonical_id,),
        limitations=("One frozen data set.",),
        source_snapshot_digest=snapshot.snapshot_digest,
        generation_lock_digest=lock.generation_lock_digest,
        generator_adapter="test",
    )
    provenance = IdeaGenerationProvenanceV1(
        lock=lock,
        generated_at=now,
        output_digest=canonical_digest({"candidate": 1}),
        requested_adapter="test",
        actual_adapter="test",
    )
    idea_set = IdeaSetV1.create(
        topic="q",
        source_snapshot_digest=snapshot.snapshot_digest,
        generation=provenance,
        candidates=(candidate,),
        selected_candidate_id=candidate.candidate_id,
    )
    contract = mint_research_contract(idea_set)
    document = {
        "typed_schema_version": "ari.research-contract/v1",
        "research_contract": contract.model_dump(mode="json"),
        "research_contract_digest": contract.contract_digest,
    }
    (tmp_path / "idea.json").write_text(json.dumps(document))
    return contract


def _proposal_payload() -> dict:
    return {
        "contract": {
            "name": "latency",
            "unit": "ms",
            "direction": "lower",
            "comparison_scope": "same-environment",
            "rationale": "Direct observation from a controlled run.",
            "required_evidence": ["latency"],
            "correctness_required": False,
            "normalization_ceiling": "not-applicable",
            "target_value": None,
            "formula": "value",
            "operands": {"value": "latency"},
            "tolerance": {"absolute": 0.01, "relative": 0.01},
            "required_measured": [],
            "invariants": ["value >= 0"],
            "correctness": None,
            "claims": [
                {
                    "claim": "The method changes latency.",
                    "required_evidence": ["latency"],
                }
            ],
        },
        "confidence": 0.55,
    }


class _Message:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.message = _Message(content)


class _Response:
    def __init__(self, content):
        self.choices = [_Choice(content)]


def test_untyped_make_is_deterministic_and_never_calls_llm(tmp_path, monkeypatch):
    async def forbidden(**_kwargs):
        raise AssertionError("make_metric_spec must not call an LLM")

    monkeypatch.setattr("litellm.acompletion", forbidden)
    result = asyncio.run(
        server._tool_make_metric_spec(
            {
                "experiment_text": "Metrics: latency\n",
                "checkpoint_dir": str(tmp_path),
            }
        )
    )
    assert result["expected_metrics"] == ["latency"]
    assert result["admission_status"] == "human-review-required"
    assert result["metric_contract"] is None
    assert not (tmp_path / "metric_contract.json").exists()


def test_typed_research_contract_is_consumed_and_frozen(tmp_path, monkeypatch):
    contract = _typed_contract_document(tmp_path)

    async def forbidden(**_kwargs):
        raise AssertionError("typed contract path must not call an LLM")

    monkeypatch.setattr("litellm.acompletion", forbidden)
    args = {
        "experiment_text": "Metrics: wrong_seed\n",
        "checkpoint_dir": str(tmp_path),
    }
    first = asyncio.run(server._tool_make_metric_spec(args))
    second = asyncio.run(server._tool_make_metric_spec(args))
    assert first == second
    assert first["metric_keyword"] == "accuracy"
    assert first["research_contract_digest"] == contract.contract_digest
    persisted = json.loads((tmp_path / "metric_contract.json").read_text())
    parsed = parse_metric_gate_contract(persisted)
    assert parsed.projection_digest == first["projection_digest"]
    assert parsed.metric_contract.contract_digest == first["metric_contract_digest"]


def test_explicit_proposal_records_model_prompt_and_evidence(tmp_path, monkeypatch):
    captured = {}

    async def fake(**kwargs):
        captured.update(kwargs)
        return _Response(json.dumps(_proposal_payload()))

    monkeypatch.setattr("litellm.acompletion", fake)
    result = asyncio.run(
        server._tool_propose_metric_contract(
            {
                "idea_json": {"title": "Measure latency", "plan": "controlled"},
                "checkpoint_dir": str(tmp_path),
                "model": "provider/proposal-model",
                "model_revision": "revision-1",
            }
        )
    )
    proposal = MetricContractProposalV1.model_validate(result)
    assert proposal.requires_human_review is True
    assert proposal.model == "provider/proposal-model"
    assert proposal.model_revision == "revision-1"
    assert proposal.prompt_digest.startswith("sha256:")
    assert proposal.evidence_digest.startswith("sha256:")
    assert captured["temperature"] == 0.0
    assert json.loads((tmp_path / "metric_contract_proposal.json").read_text()) == result
    assert not (tmp_path / "metric_contract.json").exists()


def test_proposal_without_reviewer_cannot_mint(tmp_path, monkeypatch):
    async def fake(**_kwargs):
        return _Response(json.dumps(_proposal_payload()))

    monkeypatch.setattr("litellm.acompletion", fake)
    proposal = asyncio.run(
        server._tool_propose_metric_contract(
            {"idea_json": "legacy idea", "checkpoint_dir": str(tmp_path)}
        )
    )
    result = asyncio.run(
        server._tool_make_metric_spec(
            {
                "experiment_text": "Metrics: latency\n",
                "checkpoint_dir": str(tmp_path),
                "proposal_json": proposal,
            }
        )
    )
    assert result["admission_status"] == "human-review-required"
    assert not (tmp_path / "metric_contract.json").exists()


def test_human_admission_is_digest_bound_and_idempotent(tmp_path, monkeypatch):
    async def fake(**_kwargs):
        return _Response(json.dumps(_proposal_payload()))

    monkeypatch.setattr("litellm.acompletion", fake)
    proposal = asyncio.run(
        server._tool_propose_metric_contract(
            {"idea_json": "legacy idea", "checkpoint_dir": str(tmp_path)}
        )
    )
    args = {
        "experiment_text": "Metrics: latency\n",
        "checkpoint_dir": str(tmp_path),
        "proposal_json": proposal,
        "reviewer": "reviewer@example.org",
    }
    first = asyncio.run(server._tool_make_metric_spec(args))
    second = asyncio.run(server._tool_make_metric_spec(args))
    assert first == second
    parsed = parse_metric_gate_contract(first["metric_contract"])
    assert parsed.source == "human-admitted"
    assert parsed.metric_contract.formula_provenance.source == "human-admission"
    assert parsed.metric_contract.confidence == 0.55
    assert first["admission_decision"]["reviewer"] == "reviewer@example.org"


def test_tampered_proposal_is_rejected(tmp_path, monkeypatch):
    async def fake(**_kwargs):
        return _Response(json.dumps(_proposal_payload()))

    monkeypatch.setattr("litellm.acompletion", fake)
    proposal = asyncio.run(
        server._tool_propose_metric_contract({"idea_json": "legacy idea"})
    )
    proposal["confidence"] = 0.99
    with pytest.raises(Exception, match="proposal_digest"):
        asyncio.run(
            server._tool_make_metric_spec(
                {
                    "experiment_text": "Metrics: latency\n",
                    "checkpoint_dir": str(tmp_path),
                    "proposal_json": proposal,
                    "reviewer": "human",
                }
            )
        )


def test_legacy_reader_is_conservative_and_does_not_overwrite(tmp_path):
    legacy = {
        "key": "latency",
        "unit": "ms",
        "direction": "lower",
        "formula": "value",
        "formula_operands": {"value": "latency"},
        "claims": [
            {"claim": "latency changes", "required_evidence": ["latency"]}
        ],
    }
    path = tmp_path / "metric_contract.json"
    original = json.dumps(legacy)
    path.write_text(original)
    result = asyncio.run(
        server._tool_make_metric_spec(
            {
                "experiment_text": "Metrics: latency\n",
                "checkpoint_dir": str(tmp_path),
            }
        )
    )
    assert result["contract_source"] == "legacy-migration-reader/v1"
    assert result["admission_status"] == "human-review-required"
    assert path.read_text() == original


def test_legacy_reader_does_not_guess_a_missing_unit(tmp_path):
    (tmp_path / "metric_contract.json").write_text(
        json.dumps({"key": "latency", "formula": "value"})
    )
    with pytest.raises(Exception, match="explicit metric name and unit"):
        asyncio.run(
            server._tool_make_metric_spec(
                {
                    "experiment_text": "Metrics: latency\n",
                    "checkpoint_dir": str(tmp_path),
                }
            )
        )


def test_removed_implicit_extractors_and_dead_helper_stay_absent():
    for name in (
        "_llm_extract_metric_spec",
        "_llm_extract_claims",
        "_llm_extract_contract_flags",
        "_resolve_falsifiable_claims",
        "_build_artifact_extractor_source",
    ):
        assert not hasattr(server, name)
