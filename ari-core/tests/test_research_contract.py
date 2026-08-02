"""Scientific hand-off contract integrity and deterministic identity tests."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from ari.public.research_contract import (
    IdeaCandidateV1,
    IdeaGenerationLockV1,
    IdeaGenerationProvenanceV1,
    IdeaSetV1,
    MetricContractV1,
    ResearchContractError,
    RetrievalRecordV1,
    SurveySnapshotV1,
    canonical_digest,
    metric_gate_projection,
    mint_research_contract,
    parse_research_contract,
    parse_research_contract_document,
    validate_research_handoff,
)


def _handoff():
    now = datetime(2026, 8, 2, tzinfo=timezone.utc)
    record = RetrievalRecordV1(
        canonical_id="s2:paper-1",
        provider="semantic-scholar",
        provider_record_id="paper-1",
        provider_version="graph-v1",
        query="test topic",
        retrieved_at=now,
        title="Prior result",
        payload_digest=canonical_digest({"paperId": "paper-1"}),
    )
    snapshot = SurveySnapshotV1.create(
        mode="record",
        provider="semantic-scholar",
        provider_version="graph-v1",
        query="test topic",
        retrieved_at=now,
        byte_reproducible=False,
        records=(record,),
    )
    lock = IdeaGenerationLockV1.create(
        adapter="default-discussion",
        adapter_version="ari-skill-idea/0.2.0",
        model="provider/model-2026-08",
        prompt_digests=(canonical_digest("prompt-v1"),),
        temperatures=(0.1,),
        seed=7,
        source_snapshot_digest=snapshot.snapshot_digest,
        topic_digest=canonical_digest("test topic"),
        experiment_context_digest=canonical_digest(""),
        model_revision="model-2026-08",
    )
    metric = MetricContractV1(
        name="error_rate",
        unit="fraction",
        direction="lower",
        comparison_scope="same-environment",
        rationale="Directly tests the proposed reduction in errors.",
        required_evidence=("error_rate", "baseline_error_rate"),
        correctness_required=True,
        normalization_ceiling="not-applicable",
    )
    candidate = IdeaCandidateV1.create(
        title="Reduce errors with method X",
        hypothesis="Method X reduces error rate relative to the fixed baseline.",
        description="A controlled comparison of X and the baseline.",
        experiment_plan="Run both methods on the same frozen inputs.",
        falsification_conditions=(
            "Reject the hypothesis when X does not reduce error_rate.",
        ),
        metric_contract=metric,
        citations=(record.canonical_id,),
        limitations=("The conclusion is limited to the frozen input set.",),
        source_snapshot_digest=snapshot.snapshot_digest,
        generation_lock_digest=lock.generation_lock_digest,
        generator_adapter="default-discussion",
        novelty_score=0.7,
        feasibility_score=0.9,
        overall_score=0.8,
    )
    provenance = IdeaGenerationProvenanceV1(
        lock=lock,
        generated_at=now,
        output_digest=canonical_digest({"candidate": "x"}),
        requested_adapter="default-discussion",
        actual_adapter="default-discussion",
    )
    idea_set = IdeaSetV1.create(
        topic="test topic",
        source_snapshot_digest=snapshot.snapshot_digest,
        generation=provenance,
        candidates=(candidate,),
        selected_candidate_id=candidate.candidate_id,
    )
    contract = mint_research_contract(idea_set)
    return snapshot, lock, candidate, idea_set, contract


def test_digest_bound_handoff_round_trip_and_gate_projection():
    snapshot, _, _, idea_set, contract = _handoff()
    validate_research_handoff(
        snapshot=snapshot, idea_set=idea_set, contract=contract
    )
    parsed = parse_research_contract(contract.model_dump(mode="json"))
    assert parsed == contract
    projection = metric_gate_projection(contract)
    assert projection["research_contract_digest"] == contract.contract_digest
    assert projection["unit"] == "fraction"
    assert projection["claims"][0]["required_evidence"] == [
        "error_rate",
        "baseline_error_rate",
    ]


def test_same_frozen_inputs_produce_same_lock_and_candidate_identity():
    _, lock_a, candidate_a, _, _ = _handoff()
    _, lock_b, candidate_b, _, _ = _handoff()
    assert lock_a.generation_lock_digest == lock_b.generation_lock_digest
    assert candidate_a.candidate_id == candidate_b.candidate_id


def test_tampered_contract_is_rejected():
    *_, contract = _handoff()
    document = contract.model_dump(mode="json")
    document["title"] = "tampered"
    with pytest.raises(ResearchContractError, match="contract_digest"):
        parse_research_contract(document)


def test_new_format_document_cannot_downgrade_to_legacy_inference():
    with pytest.raises(ResearchContractError, match="no admitted"):
        parse_research_contract_document(
            {
                "typed_schema_version": "ari.research-contract/v1",
                "research_contract": None,
            }
        )


def test_unknown_citation_is_rejected_at_handoff():
    snapshot, _, candidate, idea_set, _ = _handoff()
    bad_candidate = IdeaCandidateV1.create(
        **{
            **candidate.model_dump(mode="python", exclude={"candidate_id"}),
            "citations": ("s2:not-in-snapshot",),
        }
    )
    bad_set = IdeaSetV1.create(
        **{
            **idea_set.model_dump(
                mode="python",
                exclude={"idea_set_digest", "candidates", "selected_candidate_id"},
            ),
            "candidates": (bad_candidate,),
            "selected_candidate_id": bad_candidate.candidate_id,
        }
    )
    with pytest.raises(ResearchContractError, match="unknown citations"):
        validate_research_handoff(
            snapshot=snapshot,
            idea_set=bad_set,
            contract=mint_research_contract(bad_set),
        )
