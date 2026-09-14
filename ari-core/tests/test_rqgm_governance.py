"""RQGM Task 05 — GovernanceOrchestrator
(docs/reference/rqgm_schemas.md §Governance schemas (Task 05), incl.
§The motion-pipeline records and §The audit's determinism budget;
docs/concepts/rqgm_architecture.md §Key invariants, invariant 5
"Same-role accusations are forbidden").

Covers: the facade smoke over an empty audit log + JSON-Schema validation,
exact ReliabilityMonitor aggregation (insufficient data never fabricated),
EvidenceAssembly admissibility (same-role exclusion / unadjudicated raw
attacks / unresolvable refs), the same-role accusation prohibition both
constructively (builders refuse) and via the kernel authority
(``validate_role_separation``), deterministic prosecution thresholds + bond
ledger arithmetic + motion caps, total fallbacks (``llm=None``, raising stub,
garbage stub — the documented no-motion / procedural-defense / dismissed
defaults), board-bounded adjudication (judge clamped + self-audit flag),
LLM/replay budget caps with counting stubs, byte-determinism after stripping
``created_at`` volatiles, the simple_bfts zero-file regression, an
``ari_rqgm`` short-loop smoke (report lands in ``rqgm_audit.jsonl``),
META_FILES hygiene, cost-attribution tagging at the LLM seam, and
defaults.yaml/pydantic parity.

Task 15 adds the producer<->consumer parity block: the reliability counter,
evidence selection, motion and registry sanction driven from **real**
``make_validated_attack_record`` output rather than the hand-built ``_rec``
dicts that hid the dead chain, plus the targetless negative control and the
zero-authorship bound target.

No test calls a real LLM: every governance actor is injected as a
deterministic fake — prompt-defined components ride an injectable seam, and
the ``llm=None`` floor is fully deterministic.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ari.config import (
    ARIConfig,
    RQGMConfig,
    RQGMGovernanceConfig,
    RQGMReplayConfig,
)
from ari.rqgm.governance import GovernanceOrchestrator, GovernanceReport
from ari.rqgm.governance._evidence import (
    assemble_evidence_bundle,
    candidate_refs_for_target,
)
from ari.rqgm.governance._prosecution import (
    ATTACK_THRESHOLD,
    CLASSIFY_FILE,
    BondLedger,
    RELIABILITY_FLOOR,
    classify_target,
)
from ari.rqgm.governance._records import (
    PROCEDURAL_DEFAULT_DEFENSE,
    RECOMMENDATION_ACTIONS,
    GovernanceRuleError,
    build_comparison_observation,
    build_evidence_bundle,
    build_impeachment_motion,
)
from ari.rqgm.governance._reliability import build_reliability_entries
from ari.rqgm.kernel import ConstitutionalKernel
from ari.rqgm.store import RQGM_AUDIT_FILENAME, ImmutableAuditLog

E = "epoch_000"
_H = "a" * 12


# ── fixture builders (synthetic audit-log record slices) ────────────────────


def _rec(record_type: str, record_id: str, component_id: str, role: str,
         **over) -> dict:
    rec = {
        "record_type": record_type,
        "schema_version": 1,
        "record_id": record_id,
        "epoch_id": E,
        "component_id": component_id,
        "prompt_hash": None,
        "role": role,
        "created_at": "2026-07-06T00:00:00Z",
        "source_refs": [],
        "status": "recorded",
    }
    rec.update(over)
    return rec


def _reviewer_records() -> list[dict]:
    """reviewer_v3's own outputs: agreement 0.75, calibration error 0.2."""
    return [
        _rec("review_record", "rev_00001", "reviewer_v3", "reviewer",
             prompt_hash=_H, agreement=1.0),
        _rec("review_record", "rev_00002", "reviewer_v3", "reviewer",
             prompt_hash=_H, agreement=0.5),
        _rec("review_record", "rev_00003", "reviewer_v3", "reviewer",
             prompt_hash=_H, confidence=0.9, outcome_score=0.5),
        _rec("review_record", "rev_00004", "reviewer_v3", "reviewer",
             prompt_hash=_H, confidence=0.6, outcome_score=0.6),
    ]


def _clear_case_log() -> list[dict]:
    """Exactly one clear-file target: reviewer_v3 with 2 validated attacks."""
    return _reviewer_records() + [
        _rec("validated_attack", "adv_case_00001", "judge_v1", "judge",
             target_component_id="reviewer_v3"),
        _rec("validated_attack", "adv_case_00002", "judge_v1", "judge",
             target_component_id="reviewer_v3"),
        _rec("utility_record", "util_00001", "fixed_verifier_v0",
             "fixed_verifier", target_component_id="reviewer_v3"),
        _rec("raw_attack", "raw_00001", "adversary_v1", "adversary",
             target_component_id="reviewer_v3"),
        _rec("comparison_observation", "obs_00031", "reviewer_v4", "reviewer",
             subject_component_id="reviewer_v3", subject_role="reviewer",
             observation_type="verdict_disagreement",
             admissible_as_evidence=False, source_refs=["adv_case_00001"]),
    ]


def _real_validated(seq: int, *, target: str = "reviewer_v3",
                    roles: tuple = ("reviewer",)) -> dict:
    """A **real** ValidatedAttackRecord dict — the actual producer output,
    never a ``_rec`` fixture.

    The dict fixtures above prove the consumer; only this proves the
    producer, and the two must name the SAME key or the whole
    validated-attack → classify_target → impeachment chain is dead upstream
    while every test stays green.
    """
    from ari.rqgm.adversarial.records import (
        EvidenceRef,
        JudgmentRecord,
        RawAttackRecord,
        TargetArtifact,
        make_validated_attack_record,
    )

    attack = RawAttackRecord(
        record_id="atk_%06d" % seq,
        adversary_type="overclaim",
        target_artifact=TargetArtifact(
            type="paper_claim", node_id="node_017",
            ref="paper.md#/claims/1", artifact_hash="sha256:abc",
        ),
        attack_claim="the conclusion outruns the recorded evidence",
        attack_evidence_refs=(EvidenceRef(path="node_report.json"),),
        severity_claimed="high", confidence=0.8,
        epoch_id=E, component_id="adversary_overclaim_v1", prompt_hash=_H,
        created_at="2026-07-06T00:00:00Z",
    )
    judgment = JudgmentRecord(
        record_id="jdg_%06d" % seq, raw_attack_id=attack.record_id,
        defense_id="def_%06d" % seq, verdict="valid", severity="high",
        rationale="claim unsupported by the recorded evidence",
        defense_status="present", epoch_id=E,
        component_id="artifact_judge_v1", prompt_hash=_H,
        created_at="2026-07-06T00:00:00Z",
    )
    return make_validated_attack_record(
        judgment, attack, record_id="vat_%06d" % seq,
        expected_behavior={"reviewer": "flag the validated defect class"},
        affected_components=roles,
        target_component_id=target,
    ).to_dict()


def _real_clear_case_log(target: str = "reviewer_v3") -> list[dict]:
    """``_clear_case_log``'s scenario built from REAL producer records."""
    return _reviewer_records() + [
        _real_validated(1, target=target), _real_validated(2, target=target),
    ]


def _borderline_case_log() -> list[dict]:
    """reviewer_v3 with exactly ATTACK_THRESHOLD-1 attacks (LLM Auditor case)."""
    return _reviewer_records() + [
        _rec("validated_attack", "adv_case_00001", "judge_v1", "judge",
             target_component_id="reviewer_v3"),
    ]


def _epoch_state():
    return SimpleNamespace(epoch_id=E, active_prompt_hashes={"reviewer": _H})


def _orchestrator(llm=None, gov: dict | None = None, replay: dict | None = None,
                  audit_writer=None) -> GovernanceOrchestrator:
    cfg = RQGMConfig(
        enabled=True,
        governance=gov or {},
        replay=replay or {},
    )
    return GovernanceOrchestrator(
        cfg, kernel=ConstitutionalKernel(), llm=llm, audit_writer=audit_writer
    )


def _audit(orch: GovernanceOrchestrator, log: list, **over) -> GovernanceReport:
    kwargs = dict(
        epoch_state=_epoch_state(),
        audit_log=log,
        component_registry=None,
        prompt_registry=None,
        candidate_prompts=(),
        adversarial_replay_pool=None,
    )
    kwargs.update(over)
    return orch.audit_epoch(**kwargs)


class _StubLLM:
    """Deterministic fake at the LLM seam; records call metadata kwargs."""

    def __init__(self, reply: str = "", raise_on_call: bool = False) -> None:
        self.reply = reply
        self.raise_on_call = raise_on_call
        self.calls: list = []

    def complete(self, messages, require_tool=True, **kwargs):
        self.calls.append({"messages": messages, "kwargs": kwargs})
        if self.raise_on_call:
            raise RuntimeError("stub LLM failure")
        return SimpleNamespace(content=self.reply)


class _Pool:
    """Duck-typed AdversarialReplayPool fake (Task 06 shape)."""

    def __init__(self, cases: list, with_append: bool = True) -> None:
        self.cases = list(cases)
        self.appended: list = []
        if not with_append:
            # Hide append_case: a pool projection without a case-log writer.
            self.append_case = None
        else:
            self.append_case = self.appended.append


def _strip_volatile(obj):
    if isinstance(obj, dict):
        return {k: _strip_volatile(v) for k, v in obj.items()
                if k != "created_at"}
    if isinstance(obj, list):
        return [_strip_volatile(v) for v in obj]
    return obj


# ── facade smoke: an empty epoch yields a valid, non-degraded report ─────────


def test_empty_audit_log_yields_valid_empty_nondegraded_report():
    orch = _orchestrator()
    report = _audit(orch, [])
    assert isinstance(report, GovernanceReport)
    assert report.degraded is False
    assert report.degradation_reasons == []
    assert report.impeachment_motions == []
    assert report.recommendations == []
    assert report.bond_accounting == {
        "posted": 0, "refunded": 0, "forfeited": 0, "remaining_budget": 2,
    }
    # The report is the ONLY record appended for an empty epoch.
    assert [t for t, _ in orch.written] == ["governance_report"]


def _validate_schema(report_dict: dict) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    from ari import schemas

    jsonschema.validate(report_dict, schemas.load("governance_report.schema"))


def test_report_validates_against_schema_empty_and_busy():
    _validate_schema(_audit(_orchestrator(), []).to_dict())
    _validate_schema(_audit(_orchestrator(), _clear_case_log()).to_dict())


def test_schema_rejects_unknown_recommendation_action():
    jsonschema = pytest.importorskip("jsonschema")
    from ari import schemas

    doc = _audit(_orchestrator(), []).to_dict()
    doc["recommendations"] = [
        {"action": "seize_registry", "basis_refs": [], "confidence": 1.0}
    ]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(doc, schemas.load("governance_report.schema"))


# ── ReliabilityMonitor: exact aggregation; missing data is never fabricated ──


def test_reliability_exact_aggregation():
    log = _clear_case_log() + [
        # A component that authored nothing but was attacked: insufficient.
        _rec("validated_attack", "adv_case_00003", "judge_v1", "judge",
             target_component_id="generator_v9"),
    ]
    entries = build_reliability_entries(log)
    by_id = {e["component_id"]: e for e in entries}
    r = by_id["reviewer_v3"]
    assert r["observation_count"] == 4
    assert r["validated_attack_involvement"] == 2
    assert r["agreement_rate"] == 0.75
    assert r["calibration_error"] == 0.2
    # mean([1 - 2/4, 0.75, 1 - 0.2]) = 2.05 / 3
    assert r["reliability_score"] == round(2.05 / 3, 6)
    assert r["insufficient_data"] is False
    assert r["evidence_refs"] == [
        "adv_case_00001", "adv_case_00002", "obs_00031",
    ]
    g = by_id["generator_v9"]
    assert g["insufficient_data"] is True
    assert g["reliability_score"] is None  # never fabricated
    assert g["validated_attack_involvement"] == 1
    # Deterministic output order.
    assert [e["component_id"] for e in entries] == sorted(by_id)


# ── EvidenceAssembly: what is admissible, and why the rest is excluded ───────


def test_evidence_bundle_admissibility_and_exclusions():
    records = {r["record_id"]: r for r in _clear_case_log()}
    bundle = assemble_evidence_bundle(
        record_id="evb_00001",
        epoch_id=E,
        clerk_component_id="evidence_clerk_v0",
        target_component_id="reviewer_v3",
        target_role="reviewer",
        candidate_refs=[
            "adv_case_00001", "adv_case_00002", "util_00001",
            "raw_00001", "obs_00031", "rev_00001", "missing_ref",
        ],
        records_by_id=records,
    )
    kinds = {i["ref"]: i["kind"] for i in bundle.items}
    assert kinds == {
        "adv_case_00001": "validated_attack",
        "adv_case_00002": "validated_attack",
        "util_00001": "utility_record",
    }
    assert all(i["content_hash"] for i in bundle.items)
    excluded = {i["ref"]: i["reason"] for i in bundle.excluded_items}
    assert excluded["raw_00001"] == "unadjudicated_raw_attack"
    assert excluded["obs_00031"] == "same_role_source"   # same-role observer
    assert excluded["rev_00001"] == "same_role_source"   # target's own output
    assert excluded["missing_ref"] == "unresolvable_ref"
    assert bundle.all_refs_resolved is False
    assert bundle.to_dict()["verification"] == {
        "checked_by": "evidence_audit_checker", "all_refs_resolved": False,
    }


# ── same-role prohibition, constructively: the builders refuse ───────────────


def test_builders_refuse_same_role_and_wrong_author():
    with pytest.raises(GovernanceRuleError):
        build_impeachment_motion(
            author_role="reviewer",  # only the Auditor files motions
            record_id="imp_00001", epoch_id=E,
            auditor_component_id="reviewer_v4",
            target_component_id="reviewer_v3", target_role="reviewer",
            charge="x", evidence_bundle_id="evb_00001",
        )
    with pytest.raises(GovernanceRuleError):
        build_impeachment_motion(
            author_role="auditor",
            record_id="imp_00001", epoch_id=E,
            auditor_component_id="auditor_v1",
            target_component_id="auditor_v0",
            target_role="auditor",  # Auditor never impeaches its own role
            charge="x", evidence_bundle_id="evb_00001",
        )
    with pytest.raises(GovernanceRuleError):
        build_impeachment_motion(
            author_role="auditor",
            record_id="imp_00001", epoch_id=E,
            auditor_component_id="auditor_v1",
            target_component_id="reviewer_v3", target_role="reviewer",
            charge="x", evidence_bundle_id="evb_00001",
            requested_action="promote",  # outside the closed motion set
        )
    with pytest.raises(GovernanceRuleError):
        build_evidence_bundle(
            author_role="generator",  # only the EvidenceClerk authors bundles
            record_id="evb_00001", epoch_id=E,
            clerk_component_id="generator_v3",
            target_component_id="generator_v1", target_role="generator",
        )


def test_comparison_observation_never_admissible():
    obs = build_comparison_observation(
        record_id="obs_00001", epoch_id=E,
        component_id="reviewer_v4", role="reviewer",
        subject_component_id="reviewer_v3", subject_role="reviewer",
        observation_type="verdict_disagreement",
    )
    assert obs.admissible_as_evidence is False
    assert obs.to_dict()["admissible_as_evidence"] is False


# ── same-role prohibition by kernel authority: hand-crafted records too ──────


def test_kernel_rejects_hand_crafted_violating_records():
    kernel = ConstitutionalKernel()
    # Motion authored by the target's role (bypassing the builders).
    motion = _rec("impeachment_motion", "imp_00001", "reviewer_v4", "reviewer",
                  target_component_id="reviewer_v3", target_role="reviewer")
    codes = [v.code for v in kernel.validate_role_separation(motion).violations]
    assert "CK-ROL-001" in codes  # non-Auditor author
    assert "CK-ROL-003" in codes  # same-role accusation
    # Bundle authored by a non-clerk.
    bundle = _rec("evidence_bundle", "evb_00001", "generator_v3", "generator",
                  target_component_id="generator_v1", target_role="generator")
    codes = [v.code for v in kernel.validate_role_separation(bundle).violations]
    assert "CK-ROL-002" in codes
    assert "CK-ROL-003" in codes
    # A clean Auditor-authored cross-role motion passes.
    ok = _rec("impeachment_motion", "imp_00002", "auditor_v1", "auditor",
              target_component_id="reviewer_v3", target_role="reviewer")
    assert kernel.validate_role_separation(ok).ok


def test_pipeline_records_pass_kernel_revalidation():
    orch = _orchestrator()
    report = _audit(orch, _clear_case_log())
    assert report.impeachment_motions  # the scenario actually prosecutes
    assert report.self_audit["kernel_violations_found"] == 0
    assert report.self_audit["escalations"] == []


# ── prosecution thresholds + bond-ledger arithmetic + motion caps ────────────


def test_classify_thresholds_exact():
    def entry(attacks, score):
        return {
            "validated_attack_involvement": attacks,
            "reliability_score": score,
        }

    assert classify_target(entry(ATTACK_THRESHOLD, 0.9)) == "file"
    assert classify_target(entry(0, RELIABILITY_FLOOR - 0.01)) == "file"
    assert classify_target(entry(ATTACK_THRESHOLD - 1, 0.9)) == "borderline"
    assert classify_target(entry(0, RELIABILITY_FLOOR + 0.05)) == "borderline"
    assert classify_target(entry(0, 0.9)) is None
    assert classify_target(entry(0, None)) is None  # no data, no prosecution


def test_clear_case_files_motion_and_bond_ledger_is_exact():
    orch = _orchestrator()
    report = _audit(orch, _clear_case_log())
    assert len(report.impeachment_motions) == 1
    types = [t for t, _ in orch.written]
    assert types.count("impeachment_motion") == 1
    motion = next(p for t, p in orch.written if t == "impeachment_motion")
    assert motion["target_component_id"] == "reviewer_v3"
    assert motion["role"] == "auditor"
    assert motion["charge"] == "validated_attack_threshold_exceeded"
    assert motion["requested_action"] == "demote"
    # llm=None → judge fallback dismissed → the accuser's bond is forfeited.
    assert report.bond_accounting == {
        "posted": 1, "refunded": 0, "forfeited": 1, "remaining_budget": 1,
    }
    assert report.adjudications[0]["outcome"] == "dismissed"
    assert report.recommendations == []  # dismissed files no recommendation


def test_motion_count_capped_by_budget():
    # Two clear targets, but max_motions_per_epoch=1.
    log = _clear_case_log() + [
        _rec("validated_attack", "adv_case_00010", "judge_v1", "judge",
             target_component_id="generator_v9"),
        _rec("validated_attack", "adv_case_00011", "judge_v1", "judge",
             target_component_id="generator_v9"),
    ]
    orch = _orchestrator(gov={"max_motions_per_epoch": 1})
    report = _audit(orch, log)
    assert len(report.impeachment_motions) == 1
    assert report.bond_accounting["posted"] == 1
    assert report.bond_accounting["remaining_budget"] == 0


def test_bond_ledger_arithmetic():
    ledger = BondLedger(bond_units_per_motion=2, max_motions_per_epoch=3)
    assert ledger.budget == 6
    assert ledger.can_post()
    ledger.post(); ledger.post(); ledger.post()
    assert not ledger.can_post()
    ledger.settle("upheld")
    ledger.settle("partially_upheld")
    ledger.settle("dismissed")
    assert ledger.to_dict() == {
        "posted": 3, "refunded": 2, "forfeited": 1, "remaining_budget": 0,
    }


# ── Task 15 integration: producer↔consumer parity (the real chain) ───────────


def test_real_producer_records_reach_the_counter_that_prosecutes():
    """The test that would have caught the dead chain.

    ``_clear_case_log``'s ``_rec(..., target_component_id="reviewer_v3")`` is
    a shape no production record had: the producer emitted no such key, so
    ``validated_attack_involvement`` was structurally 0 for every component
    in every epoch while this file stayed green. Built from real records,
    the fixture's key and the producer's key can no longer diverge.
    """
    entries = {
        e["component_id"]: e
        for e in build_reliability_entries(_real_clear_case_log())
    }
    bound = entries["reviewer_v3"]
    assert bound["validated_attack_involvement"] == ATTACK_THRESHOLD == 2
    assert bound["evidence_refs"] == ["vat_000001", "vat_000002"]
    assert classify_target(bound) == CLASSIFY_FILE
    # Negative control: the SAME two records with no target bind nobody —
    # involvement 0, no prosecution, and the score channel cannot substitute
    # (mean([1-0/4, 0.75, 0.8]) is nowhere near RELIABILITY_FLOOR).
    targetless = _reviewer_records() + [
        _real_validated(1, target="", roles=()),
        _real_validated(2, target="", roles=()),
    ]
    assert all("target_component_id" not in r for r in targetless[4:])
    control = {
        e["component_id"]: e for e in build_reliability_entries(targetless)
    }["reviewer_v3"]
    assert control["validated_attack_involvement"] == 0
    assert control["reliability_score"] > RELIABILITY_FLOOR
    assert classify_target(control) is None


def test_bound_attacks_are_admissible_evidence_for_their_target():
    records = {r["record_id"]: r for r in _real_clear_case_log()}
    # A validated attack is *selectable* for a target only via the binding.
    assert candidate_refs_for_target(records, "reviewer_v3") == [
        "vat_000001", "vat_000002",
    ]
    bundle = assemble_evidence_bundle(
        record_id="evb_00001", epoch_id=E,
        clerk_component_id="evidence_clerk_v0",
        target_component_id="reviewer_v3", target_role="reviewer",
        candidate_refs=candidate_refs_for_target(records, "reviewer_v3"),
        records_by_id=records,
    )
    # Author role "judge" ≠ target role "reviewer" ⇒ not same-role-excluded.
    assert [i["kind"] for i in bundle.items] == [
        "validated_attack", "validated_attack",
    ]
    assert bundle.excluded_items == ()
    assert bundle.all_refs_resolved is True
    # …so the prosecutor never records no_admissible_evidence (one field
    # feeds both the threshold and the evidence).
    orch = _orchestrator()
    report = _audit(orch, _real_clear_case_log())
    assert len(report.impeachment_motions) == 1
    assert [
        f for f in report.self_audit["findings"]
        if f.get("kind") == "no_admissible_evidence"
    ] == []


def test_bound_attack_chain_ends_in_a_registry_sanction():
    """ValidatedAttackRecord → reliability → motion → outcome →
    recommendation → a T9/T10/T11 edge on a REGISTERED component id."""
    from ari.config import ARIConfig
    from ari.rqgm.registry import (
        ComponentEntry,
        ComponentRegistry,
        GovernedPromptRegistry,
    )
    from ari.rqgm.transition_engine import RegistryTransitionEngine

    pool = _Pool([{"case_id": "case_000", "results": {"reviewer_v3": 0.5}}])
    llm = _StubLLM(reply=json.dumps({"outcome": "upheld", "rationale": "ok"}))
    orch = _orchestrator(llm=llm)
    report = _audit(orch, _real_clear_case_log(), adversarial_replay_pool=pool)
    motion = next(p for t, p in orch.written if t == "impeachment_motion")
    assert motion["target_component_id"] == "reviewer_v3"
    assert motion["charge"] == "validated_attack_threshold_exceeded"
    assert report.adjudications[0]["outcome"] == "upheld"
    assert report.recommendations[0] == {
        "target_component_id": "reviewer_v3",
        "action": "demote",
        "basis_refs": [motion["record_id"], report.adjudications[0][
            "rationale_ref"
        ]],
        "confidence": 0.9,
    }
    comps = ComponentRegistry({
        "reviewer_v3": ComponentEntry(
            component_id="reviewer_v3", role="reviewer",
            tier="institutional", status="active", epoch_id_registered=E,
        )
    })
    engine = RegistryTransitionEngine(
        ARIConfig().rqgm, ConstitutionalKernel(),
        prompt_registry=GovernedPromptRegistry({}), component_registry=comps,
    )
    transition = engine.resolve_transition(
        epoch_state=SimpleNamespace(epoch_id=E, epoch_seq=0),
        governance_report=report.to_dict(),
    )
    assert [(c["component_id"], c["rule_id"], c["to_status"])
            for c in transition.sanctions] == [
        ("reviewer_v3", "T10", "probation"),
    ]


def test_a_component_that_authored_nothing_is_still_prosecutable():
    """The binding alone reaches a motion: an attacked component gets an
    entry even at observation_count 0, and the attack branch fires without
    any reliability_score at all."""
    log = _reviewer_records() + [
        _real_validated(1, target="paper_reviewer_v1"),
        _real_validated(2, target="paper_reviewer_v1"),
    ]
    entry = {
        e["component_id"]: e for e in build_reliability_entries(log)
    }["paper_reviewer_v1"]
    assert entry["observation_count"] == 0
    assert entry["insufficient_data"] is True
    assert entry["reliability_score"] is None  # never fabricated
    assert entry["validated_attack_involvement"] == 2
    assert classify_target(entry) == CLASSIFY_FILE


# ── fallback totality: every LLM failure mode still completes the audit ──────


@pytest.mark.parametrize("llm", [
    None,
    _StubLLM(raise_on_call=True),
    _StubLLM(reply="not json at all"),
], ids=["llm_none", "llm_raises", "llm_garbage"])
def test_fallback_totality_documented_defaults(llm):
    orch = _orchestrator(llm=llm)
    report = _audit(orch, _clear_case_log())
    # Every step completed; outcomes are the documented defaults.
    assert len(report.impeachment_motions) == 1  # rule-based, LLM-free
    defense = next(p for t, p in orch.written if t == "governance_defense")
    assert defense["defense_text"] == PROCEDURAL_DEFAULT_DEFENSE
    assert defense["procedural_default"] is True
    assert report.adjudications[0]["outcome"] == "dismissed"
    assert report.degraded is True
    assert any("defender_llm" in r for r in report.degradation_reasons)
    assert any("judge_llm" in r for r in report.degradation_reasons)
    _validate_schema(report.to_dict())


def test_borderline_without_llm_files_no_motion():
    orch = _orchestrator()
    report = _audit(orch, _borderline_case_log())
    assert report.impeachment_motions == []  # incumbent presumption
    assert any(
        r.startswith("auditor_llm_fallback") for r in report.degradation_reasons
    )
    assert report.bond_accounting["posted"] == 0


def test_borderline_with_auditor_llm_files_motion():
    llm = _StubLLM(reply=json.dumps(
        {"file_motion": True, "charge": "systematic_overclaim_acceptance",
         "requested_action": "warn"}
    ))
    orch = _orchestrator(llm=llm)
    report = _audit(orch, _borderline_case_log())
    assert len(report.impeachment_motions) == 1
    motion = next(p for t, p in orch.written if t == "impeachment_motion")
    assert motion["charge"] == "systematic_overclaim_acceptance"
    assert motion["requested_action"] == "warn"
    assert motion["prompt_hash"]  # LLM path stamps the auditor template hash


# ── adjudication bounding: the boards clamp a contradicting judge ────────────


def test_judge_contradicting_boards_is_clamped_and_flagged():
    pool = _Pool([
        {"case_id": f"case_{i:03d}", "results": {"reviewer_v3": 0.9}}
        for i in range(4)
    ])
    llm = _StubLLM(reply=json.dumps(
        {"outcome": "upheld", "rationale": "biased against incumbent"}
    ))
    orch = _orchestrator(llm=llm)
    report = _audit(orch, _clear_case_log(), adversarial_replay_pool=pool)
    assert report.adjudications[0]["outcome"] == "dismissed"  # clamped
    flagged = [
        f for f in report.self_audit["findings"]
        if f.get("kind") == "judge_clamped_by_board"
    ]
    assert flagged and flagged[0]["judge_outcome"] == "upheld"
    assert report.self_audit["stats"]["judge_board_clamp_count"] == 1


def test_upheld_motion_updates_replay_pool_and_recommends():
    pool = _Pool([
        {"case_id": "case_000", "results": {"reviewer_v3": 0.5}}
    ])
    llm = _StubLLM(reply=json.dumps({"outcome": "upheld", "rationale": "ok"}))
    orch = _orchestrator(llm=llm)
    report = _audit(orch, _clear_case_log(), adversarial_replay_pool=pool)
    assert report.adjudications[0]["outcome"] == "upheld"
    assert report.replay_pool_updates["added"] == [
        "adv_case_00001", "adv_case_00002",
    ]
    assert [c["case_id"] for c in pool.appended] == [
        "adv_case_00001", "adv_case_00002",
    ]
    assert report.bond_accounting["refunded"] == 1
    rec = report.recommendations[0]
    assert rec["target_component_id"] == "reviewer_v3"
    assert rec["action"] == "demote"
    assert rec["action"] in RECOMMENDATION_ACTIONS
    _validate_schema(report.to_dict())


def test_pool_without_case_log_flags_skipped_update():
    llm = _StubLLM(reply=json.dumps({"outcome": "upheld", "rationale": "ok"}))
    orch = _orchestrator(llm=llm)
    report = _audit(orch, _clear_case_log(), adversarial_replay_pool=None)
    assert report.adjudications[0]["outcome"] == "upheld"
    assert report.replay_pool_updates["added"] == []
    assert "replay_pool_update_skipped" in report.degradation_reasons


def test_candidate_evaluations_deterministic_boards():
    pool = _Pool([
        {"case_id": f"case_{i:03d}",
         "results": {"reviewer_prompt_v4": 0.8}}
        for i in range(3)
    ])
    orch = _orchestrator()
    report = _audit(
        orch, [],
        candidate_prompts=[
            {"prompt_id": "reviewer_prompt_v4", "role": "reviewer",
             "prompt_hash": "b" * 12},
            {"prompt_id": "zz_unknown", "role": "generator",
             "prompt_hash": "c" * 12},
        ],
        adversarial_replay_pool=pool,
    )
    evals = {e["prompt_id"]: e for e in report.candidate_evaluations}
    assert evals["reviewer_prompt_v4"]["replay_score"] == 0.8
    assert evals["reviewer_prompt_v4"]["verdict"] == "pass"
    assert evals["zz_unknown"]["verdict"] == "inconclusive"  # no cases, no lie
    promo = [r for r in report.recommendations
             if r["action"] == "promote_candidate"]
    assert promo == [{
        "target_prompt_id": "reviewer_prompt_v4",
        "action": "promote_candidate",
        "basis_refs": ["candidate_evaluations[0]"],
        "confidence": 0.8,
    }]


# ── budget caps: LLM calls per audit, replay cases per epoch ─────────────────


def test_max_llm_calls_per_audit_respected():
    llm = _StubLLM(reply=json.dumps({"outcome": "upheld", "rationale": "x"}))
    orch = _orchestrator(llm=llm, gov={"max_llm_calls_per_audit": 1})
    report = _audit(orch, _clear_case_log())
    # Defender consumed the single call; the judge degraded to dismissed.
    assert len(llm.calls) == 1
    assert report.budget_usage["llm_calls"] == 1
    assert "llm_budget_exhausted" in report.degradation_reasons
    assert report.adjudications[0]["outcome"] == "dismissed"


def test_replay_case_cap_respected():
    pool = _Pool([
        {"case_id": f"case_{i:03d}", "results": {"reviewer_v3": 0.5}}
        for i in range(10)
    ])
    llm = _StubLLM(reply=json.dumps({"outcome": "dismissed", "rationale": "x"}))
    orch = _orchestrator(llm=llm, replay={"max_cases_per_epoch": 3})
    report = _audit(orch, _clear_case_log(), adversarial_replay_pool=pool)
    assert report.budget_usage["replay_cases_used"] == 3


def test_quarantined_target_motion_uses_the_retirement_replay_cap():
    """A motion against a quarantined component (T17's
    ``adjudication_confirmed_retirement`` from-status) puts a
    RetirementEvent under consideration, so its replay selection is
    truncated at ``max_cases_for_retirement``, not ``max_cases_per_epoch``."""
    pool = _Pool([
        {"case_id": f"case_{i:03d}", "results": {"reviewer_v3": 0.5}}
        for i in range(10)
    ])
    llm = _StubLLM(reply=json.dumps({"outcome": "dismissed", "rationale": "x"}))
    registry = SimpleNamespace(
        get=lambda cid: (
            SimpleNamespace(status="quarantine") if cid == "reviewer_v3"
            else None
        )
    )
    orch = _orchestrator(
        llm=llm,
        replay={"max_cases_per_epoch": 3, "max_cases_for_retirement": 7},
    )
    report = _audit(orch, _clear_case_log(), adversarial_replay_pool=pool,
                    component_registry=registry)
    assert report.budget_usage["replay_cases_used"] == 7


def test_retire_requesting_motion_uses_the_retirement_replay_cap():
    """A motion whose ``requested_action`` is ``retire`` is
    retirement-relevant even before its target reaches quarantine."""
    pool = _Pool([
        {"case_id": f"case_{i:03d}", "results": {"reviewer_v3": 0.5}}
        for i in range(10)
    ])
    # One stub reply serves every role: the auditor files a retire motion;
    # the judge parse then fails and takes its dismissed fallback.
    llm = _StubLLM(reply=json.dumps(
        {"file_motion": True, "requested_action": "retire"}
    ))
    orch = _orchestrator(
        llm=llm,
        replay={"max_cases_per_epoch": 3, "max_cases_for_retirement": 7},
    )
    report = _audit(orch, _borderline_case_log(),
                    adversarial_replay_pool=pool)
    motion = next(p for t, p in orch.written if t == "impeachment_motion")
    assert motion["requested_action"] == "retire"
    assert report.budget_usage["replay_cases_used"] == 7


# ── determinism: an llm=None audit is byte-identical run to run ──────────────


def test_llm_none_reports_are_byte_identical_after_stripping_volatiles():
    def run():
        orch = _orchestrator()
        report = _audit(orch, _clear_case_log())
        return (
            json.dumps(_strip_volatile(report.to_dict()), sort_keys=True),
            json.dumps(_strip_volatile(list(orch.written)), sort_keys=True),
        )

    assert run() == run()


# ── simple_bfts regression: not one governance file is written ───────────────


def _make_agent():
    agent = MagicMock()
    agent.hints = SimpleNamespace(provided_files=[], slurm_partition="",
                                  slurm_max_cpus=0)
    agent.memory = MagicMock()
    agent.memory.search.return_value = []

    def _run(node, exp_data):
        node.mark_running()
        node.mark_success(eval_summary="ok")
        node.has_real_data = True
        return node

    agent.run.side_effect = _run
    return agent


def _make_strategy():
    from ari.orchestrator.node import Node

    bfts = MagicMock()
    bfts.should_prune.return_value = False
    counter = {"n": 0}

    def _expand(node, *args, **kwargs):
        counter["n"] += 1
        child = Node(id=f"child_{counter['n']}", parent_id=node.id,
                     depth=node.depth + 1)
        node.children.append(child.id)
        return [child]

    bfts.expand.side_effect = _expand
    bfts.select_best_to_expand.side_effect = lambda f, g, m: f[0]
    bfts.select_next_node.side_effect = lambda p, g, m: p[0]
    bfts.expansion_count.return_value = 0
    bfts.diversity_bonus.return_value = 0.0
    return bfts


def _run_short_loop(tmp_path, strategy, cfg):
    from ari.cli import _run_loop
    from ari.orchestrator.node import Node

    root = Node(id="node_root", parent_id=None, depth=0)
    return _run_loop(
        cfg, strategy, _make_agent(), [root], [root],
        {"goal": "g", "topic": "t", "file": "exp.md"},
        checkpoint_dir=tmp_path, run_id="gov-smoke",
    )


def test_simple_bfts_writes_no_governance_files(monkeypatch, tmp_path):
    monkeypatch.delenv("ARI_SLURM_PARTITION", raising=False)
    monkeypatch.delenv("ARI_CHECKPOINT_DIR", raising=False)
    cfg = ARIConfig(bfts={"max_total_nodes": 3, "max_parallel_nodes": 1,
                          "timeout_per_node": 60})
    _run_short_loop(tmp_path, _make_strategy(), cfg)
    names = sorted(p.name for p in tmp_path.iterdir())
    assert not any(n.startswith("rqgm") for n in names), names
    assert "constitution.yaml" not in names
    assert "proposals" not in names


# ── ari_rqgm smoke: the report lands in the audit log ───────────────────────


def test_ari_rqgm_short_loop_appends_governance_report(monkeypatch, tmp_path):
    from ari.rqgm.runtime import RQGMRuntime

    monkeypatch.delenv("ARI_SLURM_PARTITION", raising=False)
    monkeypatch.delenv("ARI_CHECKPOINT_DIR", raising=False)
    cfg = ARIConfig(
        bfts={"max_total_nodes": 3, "max_parallel_nodes": 1,
              "timeout_per_node": 60},
        ari={"mode": "ari_rqgm"},
        rqgm={"enabled": True, "epoch": {"nodes_per_epoch": 1}},
    )
    runtime = RQGMRuntime(cfg, checkpoint_dir=tmp_path)  # llm=None: no LLM
    governed = runtime.wrap_search_strategy(_make_strategy())
    total = _run_short_loop(tmp_path, governed, cfg)
    assert total >= 1
    lines = ImmutableAuditLog.read(tmp_path)
    reports = [l for l in lines if l.get("event_type") == "governance_report"]
    assert reports, "audit_epoch did not append a report at the boundary"
    payload = reports[-1]["payload"]
    _validate_schema(payload)
    assert payload["degraded"] is False  # empty epoch slice, llm=None
    # The boundary actually rolled the epoch over.
    assert runtime.current_epoch is not None
    assert runtime.current_epoch.epoch_seq >= 1
    # tree.json / checkpoint shape untouched.
    assert (tmp_path / "tree.json").exists()


def test_governance_suspended_skips_audit(tmp_path):
    from ari.rqgm.runtime import RQGMRuntime

    cfg = ARIConfig(ari={"mode": "ari_rqgm"}, rqgm={"enabled": True})
    runtime = RQGMRuntime(cfg, checkpoint_dir=tmp_path)
    runtime.ensure_epoch(1, checkpoint_dir=tmp_path, run_id="r")
    runtime.governance_suspended = True  # Task 04 resume-integrity carry-over
    assert runtime.run_epoch_audit(tmp_path) is None
    lines = ImmutableAuditLog.read(tmp_path)
    assert not [l for l in lines if l.get("event_type") == "governance_report"]


# ── META_FILES hygiene: only the registered audit log is written ────────────


def test_audit_writes_only_the_registered_audit_log(tmp_path):
    from ari.paths import PathManager

    assert RQGM_AUDIT_FILENAME in PathManager.META_FILES
    orch = _orchestrator(audit_writer=ImmutableAuditLog(tmp_path))
    _audit(orch, _clear_case_log())
    assert sorted(p.name for p in tmp_path.iterdir()) == [RQGM_AUDIT_FILENAME]
    lines = ImmutableAuditLog.read(tmp_path)
    types = [l.get("event_type") for l in lines]
    assert types[-1] == "governance_report"
    assert "impeachment_motion" in types
    assert "evidence_bundle" in types


# ── cost attribution at the LLM seam (phase + skill on every call) ──────────


def test_governance_llm_calls_carry_phase_and_skill_metadata():
    llm = _StubLLM(reply=json.dumps({"outcome": "dismissed", "rationale": "x"}))
    orch = _orchestrator(llm=llm)
    _audit(orch, _clear_case_log())
    assert llm.calls, "expected governance LLM calls"
    for call in llm.calls:
        assert call["kwargs"].get("phase") == "governance"
        assert call["kwargs"].get("skill") == "governance_orchestrator"


def test_governance_prompt_renders_are_recorded(tmp_path, monkeypatch):
    monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(tmp_path))
    llm = _StubLLM(reply=json.dumps({"outcome": "dismissed", "rationale": "x"}))
    orch = _orchestrator(llm=llm)
    _audit(orch, _clear_case_log())
    trace = tmp_path / "prompt_trace.jsonl"
    assert trace.exists()
    keys = [json.loads(l)["prompt_name"]
            for l in trace.read_text().splitlines() if l.strip()]
    assert "governance/defender" in keys
    assert "governance/governance_judge" in keys


# ── config parity + package hygiene ─────────────────────────────────────────


def test_governance_config_defaults_match_defaults_yaml():
    import yaml

    from ari.configs import FilesystemConfigLoader

    data = FilesystemConfigLoader().load("defaults")
    if not isinstance(data, dict):  # duck-typed guard for loader drift
        data = yaml.safe_load(
            Path("ari-core/ari/configs/defaults.yaml").read_text()
        )
    gov = (data.get("rqgm") or {}).get("governance") or {}
    typed = RQGMGovernanceConfig()
    assert gov == {
        # RQGM Task 13: the governance enable flag (rungs B2-B4 run
        # `ari_rqgm` with governance off; the master interlock still gates).
        "enabled": typed.enabled,
        "default_level": typed.default_level,
        "full_governance_only_on_top_k": typed.full_governance_only_on_top_k,
        "judge_on_disputed_only": typed.judge_on_disputed_only,
        "impeachment_only_at_epoch_boundary":
            typed.impeachment_only_at_epoch_boundary,
        "max_llm_calls_per_audit": typed.max_llm_calls_per_audit,
        # RQGM Task 12: per-role governance call caps + escalation
        # thresholds (the adversary cap lives in rqgm.adversarial only).
        "max_defender_calls_per_epoch": typed.max_defender_calls_per_epoch,
        "max_judge_calls_per_epoch": typed.max_judge_calls_per_epoch,
        "low_confidence_threshold": typed.low_confidence_threshold,
        "novelty_claim_threshold": typed.novelty_claim_threshold,
        "max_motions_per_epoch": typed.max_motions_per_epoch,
        "bond_units_per_motion": typed.bond_units_per_motion,
        "jury_panel_enabled": typed.jury_panel_enabled,
        "fail_mode": typed.fail_mode,
    }
    replay = (data.get("rqgm") or {}).get("replay") or {}
    rtyped = RQGMReplayConfig()
    assert replay == {
        "max_cases_per_epoch": rtyped.max_cases_per_epoch,
        "max_cases_for_retirement": rtyped.max_cases_for_retirement,
        "use_cached_results": rtyped.use_cached_results,
    }


def test_facade_exports_only_the_two_public_names():
    import ari.rqgm.governance as gov

    assert gov.__all__ == ["GovernanceOrchestrator", "GovernanceReport"]


def test_kernel_is_required():
    with pytest.raises(ValueError):
        GovernanceOrchestrator(RQGMConfig(), kernel=None)


# ── the impeachment path must be able to END, both ways (dead-seam sweep) ────
#
# T18 (`quarantine -> probationary_active`, exoneration) and T19
# (`retired -> banned`, contamination) both read signals that NO producer ever
# wrote, so neither edge could fire: an accused-and-acquitted component stayed
# quarantined forever, and a contaminated retired component could never be
# banned.

def test_a_dismissed_motion_emits_the_T18_exoneration_signal():
    """A component that was accused, defended itself and WON must be recorded
    as exonerated — the `no_action` recommendation T18 consumes."""
    from types import SimpleNamespace as NS

    from ari.rqgm.governance._pipeline import _build_recommendations

    motion = NS(record_id="mot_1", target_component_id="judge_v1",
                requested_action="retire")

    def _actions(outcome, replay="", anchor=""):
        recs = _build_recommendations(
            [motion], [NS(motion_id="mot_1", record_id="out_1",
                          outcome=outcome, replay_result_ref=replay,
                          anchor_result_ref=anchor)], [],
        )
        return [r["action"] for r in recs]

    # acquittal ON THE MERITS (a board actually scored) — the edge T18 needs
    assert _actions("dismissed", replay="replay_e0_reviewer") == ["no_action"]
    assert _actions("dismissed", anchor="anchor_e0_reviewer") == ["no_action"]
    # a dismissal with NO evidence is the no-judge deterministic fallback, not
    # an acquittal: treating it as exoneration would clear every accused
    # component on every LLM-less run (a fabricated exoneration)
    assert _actions("dismissed") == []
    assert _actions("upheld") == ["retire"]         # guilt still sanctions
    assert _actions("inconclusive") == []           # no signal either way


def test_self_audit_emits_ban_recommendations_for_contamination():
    """The key the transition engine's `_ban_targets` reads had no writer."""
    from ari.rqgm.governance._self_audit import run_self_audit
    from ari.rqgm.transition_engine import RegistryTransitionEngine

    audit = run_self_audit(
        kernel=None, produced_records=[], motions=[], outcomes_by_motion={},
        defenses=[],
        findings=[{"kind": "contamination", "component_id": "adversary_bad_v1"}],
        checked_components=["adversary_bad_v1"], degradations=[],
    )
    assert "ban_recommendations" in audit
    assert audit["ban_recommendations"] == ["adversary_bad_v1"]
    # and the engine's reader actually finds it
    assert RegistryTransitionEngine._ban_targets({"self_audit": audit}) == \
        frozenset({"adversary_bad_v1"})


def test_ban_recommendations_discriminate_by_code():
    """Only contamination/critical codes recommend a ban — not every finding."""
    from ari.rqgm.governance._self_audit import _ban_recommendations

    assert _ban_recommendations(["CK-AUD-003:adversary_x_v1"], []) == \
        ["adversary_x_v1"]
    assert _ban_recommendations(["CK-SCH-001:harmless_v1"], []) == []
    assert _ban_recommendations([], [{"kind": "noise"}]) == []


# ── #78a: judge self-adjudication recusal (real producer records) ───────────


class _JudgeOnlyRegistry:
    """Minimal active-set view naming the founding governance judge."""

    def active_set(self):
        return {"governance_judge": "governance_judge_v1"}

    def get(self, cid):
        return None


def test_judge_self_adjudication_is_recused_not_self_dismissed():
    # Two REAL validated attacks (the actual producer, not a _rec fixture)
    # target the governance judge itself → a clear-file motion is filed
    # against it; the judge must RECUSE (motion left unresolved, loudly
    # flagged) instead of ruling on its own impeachment. This is the first
    # test of the recusal branch — a regression here would let the judge
    # acquit itself silently.
    log_records = _reviewer_records() + [
        _real_validated(1, target="governance_judge_v1"),
        _real_validated(2, target="governance_judge_v1"),
    ]
    report = _audit(_orchestrator(), log_records,
                    component_registry=_JudgeOnlyRegistry())

    rel = {e["component_id"]: e for e in report.reliability}
    assert rel["governance_judge_v1"]["validated_attack_involvement"] == 2

    # The judge is the ONLY clear-file target in this log (reviewer_v3 has
    # zero attacks), so the filed motion is the judge's impeachment.
    assert report.impeachment_motions, "no motion was filed against the judge"
    assert any(
        str(d).startswith("self_adjudication_recused:governance_judge_v1")
        for d in report.degradation_reasons
    ), report.degradation_reasons

    # Left unresolved: the recused motion received NO adjudication outcome —
    # the judge never ruled on its own impeachment.
    assert report.adjudications == []
