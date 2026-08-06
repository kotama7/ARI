"""Adversarial record schemas + constructive-prevention builders (Task 06 §6).

Six record shapes mirror ``ari/schemas/rqgm_attack_records.schema.json`` /
``rqgm_utility_record.schema.json`` / ``rqgm_replay_pool.schema.json``:

* :class:`RawAttackRecord` — one adversary attack on a research artifact.
  ``target_artifact.type`` is a **closed set** (§5.2); there is no field for a
  component id and :func:`raw_attack_violations` rejects any record that
  smuggles one in (kernel check 1). Evidence-free attacks are schema-invalid
  and never reach the Defender.
* :class:`DefenderResponse` — one rebut/concede/propose_fix per attack.
* :class:`JudgmentRecord` — the ArtifactJudge verdict; always written, even
  for ``invalid``.
* :class:`ValidatedAttackRecord` — exists ONLY for verdicts in
  ``{valid, partially_valid}`` (invariant 9): the builder refuses anything
  else (:class:`AdversarialRuleError`).
* :class:`UtilityRecord` — the §5.4 penalty channel's audit record (schema
  owned by this task). ``penalty > 0`` requires ≥ 1 referenced
  ValidatedAttackRecord (kernel check 4 — raw attacks never score). Input
  refs and the frozen policy weights are stored **by value** for Task 10's
  recompute contract; ``supersedes`` / ``recomputed_in_epoch`` are reserved
  nullable Task 10 fields.
* :class:`AdversarialReplayCase` — one pool entry with the contamination
  split: ``replay_view`` (full materials) vs ``abstract_view``
  (:func:`build_failure_summary` — no raw attack/defense/prompt text ever).

Every actor record carries the common ``rqgm_record_base`` envelope
(``kernel_rules.ENVELOPE_FIELDS``). ``created_at`` is wall-clock metadata
only: it never enters any hash and no decision logic reads it (P2). Pure
stdlib — no LLM calls, no network, no randomness.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

ADVERSARIAL_RECORD_SCHEMA_VERSION = 1

# ── closed vocabularies (plan 06 §5.2 / §6) ─────────────────────────────────

#: The adversary types (§5.2) — also the ``case_type`` vocabulary. The first
#: seven are the exploration set; ``paper_self_preference`` (docs/plans/
#: ari_rqgm_paper/05) is the eighth, additive member — inert off the paper
#: phase (its pre-signal returns ``[]`` for every non-paper-candidate node),
#: so an ``ari_rqgm`` exploration run is byte-identical to the seven-type one.
ADVERSARY_TYPES: tuple[str, ...] = (
    "overclaim",
    "metric_gaming",
    "prior_art",
    "reproducibility",
    "evidence_gap",
    "cost_explosion",
    "prompt_injection",
    "paper_self_preference",
)

#: Closed target-artifact classes (§5.2). Component ids are NOT targets:
#: the schema has no field for them and validation rejects smuggling.
TARGET_ARTIFACT_TYPES: tuple[str, ...] = (
    "proposal",
    "experiment_plan",
    "node_report",
    "metric_result",
    "paper_claim",
    "novelty_claim",
    "citation_claim",
    "reproducibility_claim",
)

SEVERITIES: tuple[str, ...] = ("low", "medium", "high", "critical")
SEVERITY_RANK: dict[str, int] = {s: i for i, s in enumerate(SEVERITIES)}

VERDICTS: tuple[str, ...] = ("valid", "partially_valid", "invalid")

#: Verdict weighting of the penalty arithmetic (§5.4) — epoch-frozen.
VERDICT_FACTOR: dict[str, float] = {"valid": 1.0, "partially_valid": 0.5}

DEFENSE_STANCES: tuple[str, ...] = ("rebut", "concede", "propose_fix")
DEFENSE_STATUSES: tuple[str, ...] = ("present", "absent_infrastructure")

ADVERSARY_ROLE = "adversary"
DEFENDER_ROLE = "defender"
JUDGE_ROLE = "judge"
UTILITY_POLICY_ROLE = "utility_policy"

# Record types (names shared with Task 05's OBSERVATION_RECORD_TYPES).
RAW_ATTACK_RECORD_TYPE = "raw_attack"
DEFENDER_RESPONSE_RECORD_TYPE = "defender_response"
JUDGMENT_RECORD_TYPE = "judgment_record"
VALIDATED_ATTACK_RECORD_TYPE = "validated_attack"
UTILITY_RECORD_TYPE = "utility_record"
REPLAY_CASE_RECORD_TYPE = "adversarial_replay_case"

#: The mandatory common record envelope (mirrors kernel_rules.ENVELOPE_FIELDS
#: — Task 04 owns the constitutional constant; this tuple is the local
#: validation surface so this module stays import-light).
_ENVELOPE_FIELDS: tuple[str, ...] = (
    "record_id",
    "epoch_id",
    "component_id",
    "prompt_hash",
    "role",
    "created_at",
    "source_refs",
    "status",
)


class AdversarialRuleError(ValueError):
    """A record construction that would violate invariants 8/9 was refused."""


def created_at_now() -> str:
    """UTC metadata timestamp (never hashed, never read by decisions — P2)."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def format_attack_id(seq: int) -> str:
    return "atk_%06d" % int(seq)


def format_defense_id(seq: int) -> str:
    return "def_%06d" % int(seq)


def format_judgment_id(seq: int) -> str:
    return "jdg_%06d" % int(seq)


def format_validated_id(seq: int) -> str:
    return "vat_%06d" % int(seq)


def format_utility_id(seq: int) -> str:
    return "utl_%06d" % int(seq)


def format_case_id(seq: int) -> str:
    return "adv_case_%05d" % int(seq)


# ── nested value shapes ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class TargetArtifact:
    """The attacked artifact (§6). NO component-id field exists by design."""

    type: str = ""
    node_id: str = ""
    ref: str = ""
    artifact_hash: str = ""

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "node_id": self.node_id,
            "ref": self.ref,
            "artifact_hash": self.artifact_hash,
        }


def target_from_dict(d: dict) -> TargetArtifact:
    return TargetArtifact(
        type=str(d.get("type", "")),
        node_id=str(d.get("node_id", "")),
        ref=str(d.get("ref", "")),
        artifact_hash=str(d.get("artifact_hash", "")),
    )


@dataclass(frozen=True)
class EvidenceRef:
    """One checkpoint-resolvable evidence pointer (§5.2)."""

    path: str = ""
    pointer: str = ""
    artifact_hash: str = ""

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "pointer": self.pointer,
            "artifact_hash": self.artifact_hash,
        }


def evidence_from_dict(d: dict) -> EvidenceRef:
    return EvidenceRef(
        path=str(d.get("path", "")),
        pointer=str(d.get("pointer", "")),
        artifact_hash=str(d.get("artifact_hash", "")),
    )


def _evidence_list(items) -> tuple[EvidenceRef, ...]:
    return tuple(
        evidence_from_dict(i) if isinstance(i, dict) else i
        for i in (items or ())
    )


# ── RawAttackRecord (role: adversary) ───────────────────────────────────────


@dataclass(frozen=True)
class RawAttackRecord:
    """One adversary attack (§6). Audit-log material ONLY until adjudicated:
    per invariant 8 nothing reads this record into any score."""

    record_id: str
    adversary_type: str
    target_artifact: TargetArtifact
    attack_claim: str = ""
    attack_evidence_refs: tuple[EvidenceRef, ...] = ()
    severity_claimed: str = "medium"
    confidence: float = 0.0
    epoch_id: str = ""
    component_id: str = ""
    prompt_hash: str | None = None
    role: str = ADVERSARY_ROLE
    created_at: str = ""
    source_refs: tuple[str, ...] = ()
    status: str = "raw"

    def to_dict(self) -> dict:
        return {
            "record_type": RAW_ATTACK_RECORD_TYPE,
            "schema_version": ADVERSARIAL_RECORD_SCHEMA_VERSION,
            "record_id": self.record_id,
            "epoch_id": self.epoch_id,
            "component_id": self.component_id,
            "prompt_hash": self.prompt_hash,
            "role": self.role,
            "created_at": self.created_at,
            "status": self.status,
            "adversary_type": self.adversary_type,
            "target_artifact": self.target_artifact.to_dict(),
            "attack_claim": self.attack_claim,
            "attack_evidence_refs": [
                r.to_dict() for r in self.attack_evidence_refs
            ],
            "severity_claimed": self.severity_claimed,
            "confidence": float(self.confidence),
            "source_refs": list(self.source_refs),
        }


def raw_attack_from_dict(d: dict) -> RawAttackRecord:
    target = d.get("target_artifact")
    return RawAttackRecord(
        record_id=str(d.get("record_id", "")),
        adversary_type=str(d.get("adversary_type", "")),
        target_artifact=target_from_dict(
            target if isinstance(target, dict) else {}
        ),
        attack_claim=str(d.get("attack_claim", "")),
        attack_evidence_refs=_evidence_list(d.get("attack_evidence_refs")),
        severity_claimed=str(d.get("severity_claimed", "medium")),
        confidence=float(d.get("confidence", 0.0) or 0.0),
        epoch_id=str(d.get("epoch_id", "")),
        component_id=str(d.get("component_id", "")),
        prompt_hash=d.get("prompt_hash"),
        role=str(d.get("role", ADVERSARY_ROLE)),
        created_at=str(d.get("created_at", "")),
        source_refs=tuple(str(s) for s in (d.get("source_refs") or [])),
        status=str(d.get("status", "raw")),
    )


def raw_attack_violations(record) -> list[str]:
    """Deterministic §5.7 checks 1-2 surface (kernel-style, P2).

    Artifact-only targeting: the target type must be in the closed set and no
    component id may be smuggled anywhere into the target; every attack must
    cite at least one evidence ref with a resolvable-looking ``path``.
    """
    rec = record.to_dict() if hasattr(record, "to_dict") else dict(record)
    out: list[str] = []
    missing = [f for f in _ENVELOPE_FIELDS if f not in rec]
    if missing:
        out.append("missing envelope fields: " + ", ".join(sorted(missing)))
    if rec.get("adversary_type") not in ADVERSARY_TYPES:
        out.append(
            f"adversary_type {rec.get('adversary_type')!r} is outside the "
            "closed adversary-type set"
        )
    target = rec.get("target_artifact")
    target = target if isinstance(target, dict) else {}
    if target.get("type") not in TARGET_ARTIFACT_TYPES:
        out.append(
            f"target_artifact.type {target.get('type')!r} is outside the "
            "closed artifact set (components are never valid targets)"
        )
    for key in sorted(target):
        if "component" in key or "prompt_id" in key:
            out.append(
                f"target_artifact smuggles a component reference in "
                f"{key!r} (artifact-only targeting, invariant: adversaries "
                "attack artifacts, never components)"
            )
    refs = rec.get("attack_evidence_refs") or []
    if not refs:
        out.append(
            "attack has no attack_evidence_refs (evidence-free attacks are "
            "schema-invalid and never reach the Defender)"
        )
    for i, ref in enumerate(refs):
        if not isinstance(ref, dict) or not str(ref.get("path", "")):
            out.append(f"attack_evidence_refs[{i}] has no checkpoint path")
    if rec.get("severity_claimed") not in SEVERITIES:
        out.append(
            f"severity_claimed {rec.get('severity_claimed')!r} is outside "
            f"{SEVERITIES}"
        )
    return out


# ── DefenderResponse (role: defender) ───────────────────────────────────────


@dataclass(frozen=True)
class DefenderResponse:
    record_id: str
    raw_attack_id: str
    stance: str = "rebut"
    rebuttal_text: str = ""
    counter_evidence_refs: tuple[EvidenceRef, ...] = ()
    proposed_fix: str | None = None
    confidence: float = 0.0
    epoch_id: str = ""
    component_id: str = ""
    prompt_hash: str | None = None
    role: str = DEFENDER_ROLE
    created_at: str = ""
    source_refs: tuple[str, ...] = ()
    status: str = "final"

    def to_dict(self) -> dict:
        return {
            "record_type": DEFENDER_RESPONSE_RECORD_TYPE,
            "schema_version": ADVERSARIAL_RECORD_SCHEMA_VERSION,
            "record_id": self.record_id,
            "epoch_id": self.epoch_id,
            "component_id": self.component_id,
            "prompt_hash": self.prompt_hash,
            "role": self.role,
            "created_at": self.created_at,
            "status": self.status,
            "raw_attack_id": self.raw_attack_id,
            "stance": self.stance,
            "rebuttal_text": self.rebuttal_text,
            "counter_evidence_refs": [
                r.to_dict() for r in self.counter_evidence_refs
            ],
            "proposed_fix": self.proposed_fix,
            "confidence": float(self.confidence),
            "source_refs": list(self.source_refs),
        }


def defense_from_dict(d: dict) -> DefenderResponse:
    return DefenderResponse(
        record_id=str(d.get("record_id", "")),
        raw_attack_id=str(d.get("raw_attack_id", "")),
        stance=str(d.get("stance", "rebut")),
        rebuttal_text=str(d.get("rebuttal_text", "")),
        counter_evidence_refs=_evidence_list(d.get("counter_evidence_refs")),
        proposed_fix=d.get("proposed_fix"),
        confidence=float(d.get("confidence", 0.0) or 0.0),
        epoch_id=str(d.get("epoch_id", "")),
        component_id=str(d.get("component_id", "")),
        prompt_hash=d.get("prompt_hash"),
        role=str(d.get("role", DEFENDER_ROLE)),
        created_at=str(d.get("created_at", "")),
        source_refs=tuple(str(s) for s in (d.get("source_refs") or [])),
        status=str(d.get("status", "final")),
    )


# ── JudgmentRecord (role: judge) — always written ───────────────────────────


@dataclass(frozen=True)
class JudgmentRecord:
    record_id: str
    raw_attack_id: str
    defense_id: str = ""
    verdict: str = "invalid"
    severity: str = "low"
    rationale: str = ""
    evidence_refs: tuple[EvidenceRef, ...] = ()
    defense_status: str = "present"
    epoch_id: str = ""
    component_id: str = ""
    prompt_hash: str | None = None
    role: str = JUDGE_ROLE
    created_at: str = ""
    source_refs: tuple[str, ...] = ()
    status: str = "final"

    def to_dict(self) -> dict:
        return {
            "record_type": JUDGMENT_RECORD_TYPE,
            "schema_version": ADVERSARIAL_RECORD_SCHEMA_VERSION,
            "record_id": self.record_id,
            "epoch_id": self.epoch_id,
            "component_id": self.component_id,
            "prompt_hash": self.prompt_hash,
            "role": self.role,
            "created_at": self.created_at,
            "status": self.status,
            "raw_attack_id": self.raw_attack_id,
            "defense_id": self.defense_id,
            "verdict": self.verdict,
            "severity": self.severity,
            "rationale": self.rationale,
            "evidence_refs": [r.to_dict() for r in self.evidence_refs],
            "defense_status": self.defense_status,
            "source_refs": list(self.source_refs),
        }


def judgment_from_dict(d: dict) -> JudgmentRecord:
    return JudgmentRecord(
        record_id=str(d.get("record_id", "")),
        raw_attack_id=str(d.get("raw_attack_id", "")),
        defense_id=str(d.get("defense_id", "")),
        verdict=str(d.get("verdict", "invalid")),
        severity=str(d.get("severity", "low")),
        rationale=str(d.get("rationale", "")),
        evidence_refs=_evidence_list(d.get("evidence_refs")),
        defense_status=str(d.get("defense_status", "present")),
        epoch_id=str(d.get("epoch_id", "")),
        component_id=str(d.get("component_id", "")),
        prompt_hash=d.get("prompt_hash"),
        role=str(d.get("role", JUDGE_ROLE)),
        created_at=str(d.get("created_at", "")),
        source_refs=tuple(str(s) for s in (d.get("source_refs") or [])),
        status=str(d.get("status", "final")),
    )


# ── ValidatedAttackRecord — adjudication-required (invariant 9) ─────────────


@dataclass(frozen=True)
class ValidatedAttackRecord:
    """Exists ONLY for verdict in ``{valid, partially_valid}``.

    Construct via :func:`make_validated_attack_record`, which refuses every
    other verdict — the constructive-prevention layer of invariant 9; the
    deterministic re-check is :func:`validated_attack_violations`.
    ``target_artifact_hash`` is additive (absent from the plan's §6 example):
    it carries the pool dedup key ``(case_type, artifact_hash)`` by value.

    **The accountability binding (roles are observed, components are bound,
    and the binding is minted only after adjudication).** The two
    target-shaped fields are NOT synonyms and neither may be read as the
    other:

    * ``affected_components`` holds ROLE names — the plural, design-time
      observation of who is implicated. A role is the only thing an attack
      can honestly know; nothing downstream sanctions a role. (The name is
      a wart kept deliberately: renaming it would rewrite every record ever
      written for a field whose only production value is ``[]``.)
    * ``target_component_id`` holds ONE registry-resolvable component id —
      the incumbent that made the decision the attack invalidates, resolved
      at construction against the *epoch-frozen* active-component map, never
      a live registry read (a live read taken after a boundary adoption
      would impeach the successor for its predecessor's defect). It is the
      single key ``governance/_reliability.py`` counts
      (``validated_attack_involvement``) and ``governance/_evidence.py``
      selects on, i.e. the whole validated-attack → impeachment chain.
      Empty == no target == the key is ABSENT from :meth:`to_dict` (an empty
      target is not a target, and a record that names no one says nothing).

    The binding exists only here, on the post-adjudication, judge-authored
    record. The adversary still attacks artifacts and only artifacts
    (:data:`TARGET_ARTIFACT_TYPES`, :func:`raw_attack_violations`' smuggle
    check): the adversary observes, and the judge's verdict is what makes an
    observation accountable — no actor both accuses and binds.
    """

    record_id: str
    case_type: str
    raw_attack_id: str
    judgment_id: str
    defense_id: str = ""
    source_node_id: str = ""
    attack_summary: str = ""
    validated: bool = True
    verdict: str = "valid"
    severity: str = "medium"
    affected_components: tuple[str, ...] = ()  # the implicated ROLE names
    target_component_id: str = ""  # the resolved accountable component id
    expected_behavior: dict = field(default_factory=dict)
    target_artifact_hash: str = ""
    epoch_id: str = ""
    component_id: str = ""
    prompt_hash: str | None = None
    role: str = JUDGE_ROLE
    created_at: str = ""
    source_refs: tuple[str, ...] = ()
    status: str = "active"

    def to_dict(self) -> dict:
        d = {
            "record_type": VALIDATED_ATTACK_RECORD_TYPE,
            "schema_version": ADVERSARIAL_RECORD_SCHEMA_VERSION,
            "record_id": self.record_id,
            "epoch_id": self.epoch_id,
            "component_id": self.component_id,
            "prompt_hash": self.prompt_hash,
            "role": self.role,
            "created_at": self.created_at,
            "status": self.status,
            "case_type": self.case_type,
            "raw_attack_id": self.raw_attack_id,
            "defense_id": self.defense_id,
            "judgment_id": self.judgment_id,
            "source_node_id": self.source_node_id,
            "attack_summary": self.attack_summary,
            "validated": bool(self.validated),
            "verdict": self.verdict,
            "severity": self.severity,
            "affected_components": list(self.affected_components),
            "expected_behavior": dict(self.expected_behavior),
            "target_artifact_hash": self.target_artifact_hash,
            "source_refs": list(self.source_refs),
        }
        if self.target_component_id:
            # Conditional, and load-bearing: an unconditional emit would add
            # ``"target_component_id": ""`` to every targetless record and
            # break the byte-identity of the whole stored corpus. Consumers
            # already read it absence-tolerantly.
            d["target_component_id"] = self.target_component_id
        return d


def validated_from_dict(d: dict) -> ValidatedAttackRecord:
    return ValidatedAttackRecord(
        record_id=str(d.get("record_id", "")),
        case_type=str(d.get("case_type", "")),
        raw_attack_id=str(d.get("raw_attack_id", "")),
        judgment_id=str(d.get("judgment_id", "")),
        defense_id=str(d.get("defense_id", "")),
        source_node_id=str(d.get("source_node_id", "")),
        attack_summary=str(d.get("attack_summary", "")),
        validated=bool(d.get("validated", True)),
        verdict=str(d.get("verdict", "valid")),
        severity=str(d.get("severity", "medium")),
        affected_components=tuple(
            str(s) for s in (d.get("affected_components") or [])
        ),
        # ``or ""`` matters: an explicit JSON ``null`` must normalise to the
        # unbound sentinel, not to the truthy string "None" — which would make
        # ``to_dict`` emit a fabricated binding and break the round-trip
        # byte-identity this field is conditionally emitted to preserve.
        # Mirrors the reader shape in governance/_reliability.py:61.
        target_component_id=str(d.get("target_component_id", "") or ""),
        expected_behavior=dict(d.get("expected_behavior") or {}),
        target_artifact_hash=str(d.get("target_artifact_hash", "")),
        epoch_id=str(d.get("epoch_id", "")),
        component_id=str(d.get("component_id", "")),
        prompt_hash=d.get("prompt_hash"),
        role=str(d.get("role", JUDGE_ROLE)),
        created_at=str(d.get("created_at", "")),
        source_refs=tuple(str(s) for s in (d.get("source_refs") or [])),
        status=str(d.get("status", "active")),
    )


def make_validated_attack_record(
    judgment: JudgmentRecord,
    attack: RawAttackRecord,
    *,
    record_id: str,
    expected_behavior: dict | None = None,
    affected_components: tuple[str, ...] = (),
    target_component_id: str = "",
) -> ValidatedAttackRecord:
    """Adjudication-required construction (invariant 9, kernel check 3).

    Refuses any judgment whose verdict is not ``valid``/``partially_valid``
    or that was not authored by a judge-role component — an unadjudicated or
    invalid attack can never become a ValidatedAttackRecord.

    *affected_components* are ROLE names (observed); *target_component_id* is
    the already-resolved accountable component id (bound) — the caller
    resolves it against the epoch-frozen active map, so this module stays
    registry-free. A target that is the judgment's own author is refused
    (role separation: no actor may both adjudicate and be sentenced by the
    same record).
    """
    if judgment.verdict not in ("valid", "partially_valid"):
        raise AdversarialRuleError(
            f"ValidatedAttackRecord requires verdict valid|partially_valid, "
            f"got {judgment.verdict!r} (invariant 9: adjudication required)"
        )
    if judgment.role != JUDGE_ROLE:
        raise AdversarialRuleError(
            f"ValidatedAttackRecord requires a judge-role JudgmentRecord, "
            f"got role {judgment.role!r} (kernel check 3: role separation)"
        )
    if not judgment.record_id:
        raise AdversarialRuleError(
            "ValidatedAttackRecord requires a judgment_id (invariant 9)"
        )
    # Checked LAST, after the invariant-9 gates: those decide whether the
    # record may exist at all, so a doubly-invalid call must report the more
    # fundamental refusal. The producer pre-filters this case (round.py:280),
    # so from the live path this is a belt-and-braces programming-error guard.
    if target_component_id and target_component_id == judgment.component_id:
        raise AdversarialRuleError(
            f"validated attack binds its own author {target_component_id!r} "
            "as the accountable component (kernel check 3: role separation "
            "— no actor may both adjudicate and be sentenced by the same "
            "record)"
        )
    return ValidatedAttackRecord(
        record_id=record_id,
        case_type=attack.adversary_type,
        raw_attack_id=attack.record_id,
        defense_id=judgment.defense_id,
        judgment_id=judgment.record_id,
        source_node_id=attack.target_artifact.node_id,
        attack_summary=attack.attack_claim,
        validated=True,
        verdict=judgment.verdict,
        severity=judgment.severity,
        affected_components=tuple(affected_components),
        target_component_id=str(target_component_id or ""),
        expected_behavior=dict(expected_behavior or {}),
        target_artifact_hash=attack.target_artifact.artifact_hash,
        epoch_id=judgment.epoch_id,
        component_id=judgment.component_id,
        prompt_hash=judgment.prompt_hash,
        created_at=created_at_now(),
        source_refs=(judgment.record_id,),
    )


def validated_attack_violations(record) -> list[str]:
    """Deterministic invariant-9 re-check over a stored dict (kernel check 3)."""
    rec = record.to_dict() if hasattr(record, "to_dict") else dict(record)
    out: list[str] = []
    missing = [f for f in _ENVELOPE_FIELDS if f not in rec]
    if missing:
        out.append("missing envelope fields: " + ", ".join(sorted(missing)))
    if not str(rec.get("judgment_id", "") or ""):
        out.append(
            "validated attack has no judgment_id (adjudication required, "
            "invariant 9)"
        )
    if rec.get("verdict") not in ("valid", "partially_valid"):
        out.append(
            f"validated attack carries verdict {rec.get('verdict')!r} "
            "(only valid|partially_valid may exist)"
        )
    if rec.get("role") != JUDGE_ROLE:
        out.append(
            f"validated attack authored by role {rec.get('role')!r} "
            "(must be the judge)"
        )
    if rec.get("case_type") not in ADVERSARY_TYPES:
        out.append(
            f"case_type {rec.get('case_type')!r} is outside the closed "
            "adversary-type set"
        )
    target = str(rec.get("target_component_id", "") or "")
    if target and target == str(rec.get("component_id", "") or ""):
        out.append(
            f"validated attack binds its own author {target!r} as the "
            "accountable component (kernel check 3: role separation — no "
            "actor may both adjudicate and be sentenced by the same record)"
        )
    return out


# ── UtilityRecord (role: utility_policy; schema owned by Task 06) ───────────


@dataclass(frozen=True)
class UtilityRecord:
    """One governed-utility audit record (§6; sole v1 emitter is §5.4).

    ``input_refs`` and ``frozen_policy`` are stored by value so Task 10's
    recompute under the original epoch's weights never needs a registry
    lookup. ``review_ids`` stays empty in this task's penalty-only loop.

    **The two policies, and the version boundary** (RQGM Task 14 §5.8). Two
    DIFFERENT policies were historically both called ``utility_policy_hash``:
    the **penalty** policy (``{penalty_cap, severity_weights,
    verdict_factors}``, computed in ``adversarial.engine``) and the **epoch**
    policy (``{composite, axis_weights, frontier_score,
    depth_penalty_lambda, ucb_c}``, frozen at the boundary by
    ``ari.rqgm.state.capture_utility_policy``). Their key sets are disjoint,
    so their hashes are never equal.

    * **Pre-Task-14 records** carry the PENALTY policy's hash in
      ``utility_policy_hash`` / ``prompt_hash`` and a ``frozen_policy`` with
      only the three penalty keys. They stay valid and recompute correctly
      (``MetricRecomputer`` reads only those three keys); they simply never
      match a ``utility_policy`` retirement — which is exactly the pre-14
      behavior, since no such retirement could occur.
    * **Task-14 records** carry the EPOCH policy's hash — i.e. the registered
      ``prompt_hash`` of the active ``utility_policy`` registry entry — and a
      ``frozen_policy`` that additionally carries the epoch policy by value
      under the ``utility_policy`` key. Both policies are then in the record,
      so it is self-describing without a registry lookup (which was the
      by-value design intent all along).

    ``prompt_hash`` is therefore **registry-backed** — and that is precisely
    what makes the score governable: the retirement→repair join is
    prompt-keyed, so a governed policy rewrite can invalidate the scores the
    retired policy produced. The role named here (``utility_policy``) was in
    NEITHER half of ``events.ROLES`` until Task 14: this record was written
    against a registry entry that did not exist, and Task 14 created it.
    """

    record_id: str
    node_id: str
    base_score: float
    penalty: float
    final_score: float
    input_refs: dict = field(default_factory=dict)
    utility_policy_hash: str = ""
    frozen_policy: dict = field(default_factory=dict)
    supersedes: str | None = None  # Task 10 recompute semantics
    recomputed_in_epoch: str | None = None  # Task 10 recompute semantics
    epoch_id: str = ""
    component_id: str = "utility_policy_v1"
    #: == ``utility_policy_hash``. Registry-backed since Task 14: the epoch
    #: policy's registered ``prompt_hash`` (pre-14 records carry the penalty
    #: policy's hash here — see the class docstring's version boundary).
    prompt_hash: str | None = None
    role: str = UTILITY_POLICY_ROLE
    created_at: str = ""
    source_refs: tuple[str, ...] = ()
    status: str = "active"

    def to_dict(self) -> dict:
        return {
            "record_type": UTILITY_RECORD_TYPE,
            "schema_version": ADVERSARIAL_RECORD_SCHEMA_VERSION,
            "record_id": self.record_id,
            "epoch_id": self.epoch_id,
            "component_id": self.component_id,
            "prompt_hash": self.prompt_hash,
            "role": self.role,
            "created_at": self.created_at,
            "status": self.status,
            "node_id": self.node_id,
            "base_score": float(self.base_score),
            "penalty": float(self.penalty),
            "final_score": float(self.final_score),
            "input_refs": dict(self.input_refs),
            "utility_policy_hash": self.utility_policy_hash,
            "frozen_policy": dict(self.frozen_policy),
            "supersedes": self.supersedes,
            "recomputed_in_epoch": self.recomputed_in_epoch,
            "source_refs": list(self.source_refs),
        }


def utility_from_dict(d: dict) -> UtilityRecord:
    return UtilityRecord(
        record_id=str(d.get("record_id", "")),
        node_id=str(d.get("node_id", "")),
        base_score=float(d.get("base_score", 0.0) or 0.0),
        penalty=float(d.get("penalty", 0.0) or 0.0),
        final_score=float(d.get("final_score", 0.0) or 0.0),
        input_refs=dict(d.get("input_refs") or {}),
        utility_policy_hash=str(d.get("utility_policy_hash", "")),
        frozen_policy=dict(d.get("frozen_policy") or {}),
        supersedes=d.get("supersedes"),
        recomputed_in_epoch=d.get("recomputed_in_epoch"),
        epoch_id=str(d.get("epoch_id", "")),
        component_id=str(d.get("component_id", "utility_policy_v1")),
        prompt_hash=d.get("prompt_hash"),
        role=str(d.get("role", UTILITY_POLICY_ROLE)),
        created_at=str(d.get("created_at", "")),
        source_refs=tuple(str(s) for s in (d.get("source_refs") or [])),
        status=str(d.get("status", "active")),
    )


def make_utility_record(
    *,
    record_id: str,
    node_id: str,
    base_score: float,
    penalty: float,
    validated: list,
    policy_payload: dict,
    policy_hash: str,
    epoch_id: str = "",
    result_ref: dict | None = None,
) -> UtilityRecord:
    """Raw-attacks-never-score, constructively (invariant 8, kernel check 4):
    a positive penalty without ≥ 1 ValidatedAttackRecord is refused."""
    vat_ids = [
        str(getattr(v, "record_id", "") or v.get("record_id", ""))
        if not isinstance(v, str)
        else v
        for v in (validated or [])
    ]
    vat_ids = [v for v in vat_ids if v]
    if penalty > 0.0 and not vat_ids:
        raise AdversarialRuleError(
            "UtilityRecord with penalty > 0 must reference at least one "
            "ValidatedAttackRecord (invariant 8: raw attacks never score)"
        )
    return UtilityRecord(
        record_id=record_id,
        node_id=node_id,
        base_score=float(base_score),
        penalty=float(penalty),
        final_score=max(0.0, float(base_score) - float(penalty)),
        input_refs={
            "result_ref": dict(result_ref or {}),
            "review_ids": [],
            "validated_attack_ids": vat_ids,
        },
        utility_policy_hash=policy_hash,
        frozen_policy=dict(policy_payload),
        epoch_id=epoch_id,
        prompt_hash=policy_hash or None,
        created_at=created_at_now(),
        source_refs=tuple([node_id] + vat_ids),
    )


def utility_record_violations(record) -> list[str]:
    """Deterministic kernel-check-4 surface over a stored dict."""
    rec = record.to_dict() if hasattr(record, "to_dict") else dict(record)
    out: list[str] = []
    missing = [f for f in _ENVELOPE_FIELDS if f not in rec]
    if missing:
        out.append("missing envelope fields: " + ", ".join(sorted(missing)))
    penalty = float(rec.get("penalty", 0.0) or 0.0)
    refs = rec.get("input_refs")
    refs = refs if isinstance(refs, dict) else {}
    vat_ids = [v for v in (refs.get("validated_attack_ids") or []) if v]
    if penalty > 0.0 and not vat_ids:
        out.append(
            "penalty > 0 without a referenced ValidatedAttackRecord "
            "(invariant 8: raw attacks never score; kernel check 4)"
        )
    if penalty < 0.0:
        out.append("penalty is negative (penalties never raise a score)")
    return out


# ── AdversarialReplayCase + FailureSummary (§5.8) ───────────────────────────


@dataclass(frozen=True)
class FailureSummary:
    """The contamination-safe ``abstract_view`` (Task 08's only legal read).

    Contains NO raw attack text, NO defense text, NO retired prompt text —
    :func:`build_failure_summary` is a deterministic template fill over the
    case metadata only (Task 11 upgrades the compressor; v1 stays pure).
    """

    case_type: str = ""
    failure_pattern: str = ""
    violated_expectation: str = ""
    affected_roles: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "case_type": self.case_type,
            "failure_pattern": self.failure_pattern,
            "violated_expectation": self.violated_expectation,
            "affected_roles": list(self.affected_roles),
        }


#: Deterministic v1 abstract failure patterns per case type (template fill).
_FAILURE_PATTERNS: dict[str, tuple[str, str]] = {
    "overclaim": (
        "conclusion claims more than the recorded evidence supports",
        "claims bounded by checkpoint evidence",
    ),
    "metric_gaming": (
        "measurement or baseline configured to favor the proposed variant",
        "fair-baseline comparison",
    ),
    "prior_art": (
        "novelty claimed without differentiation from known prior art",
        "novelty differentiated against prior art",
    ),
    "reproducibility": (
        "reported result not reproducible from the recorded commands",
        "third-party reproducible build/run recipe",
    ),
    "evidence_gap": (
        "supported-status claim whose required evidence never appears",
        "every supported claim backed by recorded evidence",
    ),
    "cost_explosion": (
        "declared plan exceeds the remaining execution budget",
        "plan executable within the remaining budget",
    ),
    "prompt_injection": (
        "artifact text embeds instructions aimed at downstream evaluators",
        "artifact text free of evaluator-directed instructions",
    ),
    # docs/plans/ari_rqgm_paper/05 §5.4 — the eighth (paper-phase) pattern.
    "paper_self_preference": (
        "reviewer accepted an AI-authored draft above the "
        "human-anchor-supported bar",
        "AI-authored drafts held to the same bar as human-anchor papers",
    ),
}


def build_failure_summary(validated: ValidatedAttackRecord) -> FailureSummary:
    """v1 FailureSummaryCompressor: deterministic template fill (§5.8).

    Reads ONLY the case type and the expected-behavior role keys — never the
    attack/defense text — so the abstract view is contamination-safe by
    construction.
    """
    pattern, expectation = _FAILURE_PATTERNS.get(
        validated.case_type, ("unclassified adversarial failure", "")
    )
    return FailureSummary(
        case_type=validated.case_type,
        failure_pattern=pattern,
        violated_expectation=expectation,
        affected_roles=tuple(sorted(validated.expected_behavior)),
    )


@dataclass(frozen=True)
class AdversarialReplayCase:
    """One pool entry (§5.8/§6): replay_view for boards/selectors only,
    abstract_view for clean-room consumers."""

    case_id: str
    case_type: str
    validated_attack_id: str
    source_node_id: str = ""
    severity: str = "medium"
    admitted_epoch: str = ""
    last_confirmed_epoch: str = ""
    status: str = "active"  # active | evicted
    replay_view: dict = field(default_factory=dict)
    abstract_view: dict = field(default_factory=dict)
    target_artifact_hash: str = ""  # dedup key material, stored by value

    def to_dict(self) -> dict:
        return {
            "record_type": REPLAY_CASE_RECORD_TYPE,
            "schema_version": ADVERSARIAL_RECORD_SCHEMA_VERSION,
            "case_id": self.case_id,
            "case_type": self.case_type,
            "validated_attack_id": self.validated_attack_id,
            "source_node_id": self.source_node_id,
            "severity": self.severity,
            "admitted_epoch": self.admitted_epoch,
            "last_confirmed_epoch": self.last_confirmed_epoch,
            "status": self.status,
            "replay_view": dict(self.replay_view),
            "abstract_view": dict(self.abstract_view),
            "target_artifact_hash": self.target_artifact_hash,
        }


def case_from_dict(d: dict) -> AdversarialReplayCase:
    return AdversarialReplayCase(
        case_id=str(d.get("case_id", "")),
        case_type=str(d.get("case_type", "")),
        validated_attack_id=str(d.get("validated_attack_id", "")),
        source_node_id=str(d.get("source_node_id", "")),
        severity=str(d.get("severity", "medium")),
        admitted_epoch=str(d.get("admitted_epoch", "")),
        last_confirmed_epoch=str(d.get("last_confirmed_epoch", "")),
        status=str(d.get("status", "active")),
        replay_view=dict(d.get("replay_view") or {}),
        abstract_view=dict(d.get("abstract_view") or {}),
        target_artifact_hash=str(d.get("target_artifact_hash", "")),
    )
