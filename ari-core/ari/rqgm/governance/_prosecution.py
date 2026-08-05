"""Auditor + Prosecutor + BondAccounting (Task 05 §5.3 step 4, §5.5).

**Rule-first, LLM-second.** The Prosecutor applies deterministic thresholds
(≥N validated attacks affecting a component; reliability below floor); only
threshold-borderline cases consult the LLM Auditor, and an LLM failure or
malformed reply files NO motion (incumbent presumption — the lineage
``fallback_continue`` pattern). BondAccounting is pure arithmetic: a fixed
bond per filed motion against the epoch's prosecution budget, refunded on
``upheld``/``partially_upheld``, forfeited on ``dismissed``, reset each epoch
(v1; carry-over penalties are a plan-05 §10 refinement).

Thresholds are module constants (deterministic, documented); the budget
knobs come from ``rqgm.governance`` (Task 12 owns the numbers).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from ari.rqgm.governance._records import (
    AUDITOR_ROLE,
    MOTION_ACTIONS,
    GovernanceRuleError,
    build_impeachment_motion,
)

log = logging.getLogger(__name__)

#: Deterministic prosecution thresholds (§5.3 step 4). Fixed in code like the
#: kernel's rule tables; only budgets are config.
ATTACK_THRESHOLD = 2          # ≥ N validated attacks → clear-file
RELIABILITY_FLOOR = 0.4       # score < floor → clear-file
BORDERLINE_MARGIN = 0.1       # floor ≤ score < floor+margin → LLM Auditor

CLASSIFY_FILE = "file"
CLASSIFY_BORDERLINE = "borderline"

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


@dataclass
class BondLedger:
    """§5.5 bond arithmetic — a pure function of adjudication outcomes."""

    bond_units_per_motion: int
    max_motions_per_epoch: int
    posted: int = 0
    refunded: int = 0
    forfeited: int = 0

    @property
    def budget(self) -> int:
        return self.max_motions_per_epoch * self.bond_units_per_motion

    @property
    def remaining_budget(self) -> int:
        return self.budget - self.posted * self.bond_units_per_motion

    def can_post(self) -> bool:
        return (
            self.posted < self.max_motions_per_epoch
            and self.remaining_budget >= self.bond_units_per_motion
        )

    def post(self) -> None:
        self.posted += 1

    def settle(self, outcome: str) -> None:
        if outcome in ("upheld", "partially_upheld"):
            self.refunded += 1
        elif outcome == "dismissed":
            self.forfeited += 1
        # "inconclusive": bond stays posted (motion carried to next epoch).

    def to_dict(self) -> dict:
        return {
            "posted": self.posted,
            "refunded": self.refunded,
            "forfeited": self.forfeited,
            "remaining_budget": self.remaining_budget,
        }


def classify_target(entry: dict) -> str | None:
    """Deterministic threshold classification of one reliability entry."""
    # Fixed procedures are constitutional mechanisms, not institutional
    # incumbents.  Their integrity findings suspend/repair the affected
    # artifact or run; they never enter incumbent impeachment competition.
    if str(entry.get("tier", "")) == "fixed":
        return None
    attacks = int(entry.get("validated_attack_involvement", 0) or 0)
    score = entry.get("reliability_score")
    if attacks >= ATTACK_THRESHOLD:
        return CLASSIFY_FILE
    if score is not None and float(score) < RELIABILITY_FLOOR:
        return CLASSIFY_FILE
    if attacks == ATTACK_THRESHOLD - 1 and attacks >= 1:
        return CLASSIFY_BORDERLINE
    if (
        score is not None
        and RELIABILITY_FLOOR <= float(score) < RELIABILITY_FLOOR + BORDERLINE_MARGIN
    ):
        return CLASSIFY_BORDERLINE
    return None


def _deterministic_charge(entry: dict) -> str:
    attacks = int(entry.get("validated_attack_involvement", 0) or 0)
    if attacks >= ATTACK_THRESHOLD:
        return "validated_attack_threshold_exceeded"
    return "reliability_below_floor"


def _parse_auditor_reply(raw: str) -> dict | None:
    """Total parser: malformed output → ``None`` (== no motion filed)."""
    m = _JSON_RE.search(raw or "")
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("file_motion"), bool):
        return None
    return data


def decide_prosecutions(
    *,
    classifications: list,
    bundles_by_target: dict,
    ledger: BondLedger,
    epoch_id: str,
    auditor_component_id: str,
    auditor_prompt_hash: str | None,
    next_motion_id,
    render_auditor=None,
    degradations: list,
    findings: list,
) -> list:
    """Step 4: file motions for classified targets, bounded by the ledger.

    *classifications* is a sorted list of ``(entry, classification)`` pairs;
    *render_auditor* is the injected LLM seam
    (``entry, bundle -> raw_text | None``) — ``None``/failure means the
    borderline case defaults to no motion. *auditor_prompt_hash* may be a
    zero-arg callable (read after the render so the LLM path stamps the real
    template hash). Returns the filed
    :class:`~ari.rqgm.governance._records.ImpeachmentMotion` list.
    """

    def _prompt_hash():
        return (
            auditor_prompt_hash()
            if callable(auditor_prompt_hash)
            else auditor_prompt_hash
        )

    motions = []
    for entry, classification in classifications:
        cid = str(entry.get("component_id", ""))
        role = str(entry.get("role", "") or "")
        if role == AUDITOR_ROLE:
            # Same-role prosecution is structurally impossible (§5.4 rule 1);
            # surfaced as a self-audit finding, never silently dropped.
            findings.append(
                {"kind": "same_role_prosecution_skipped", "component_id": cid}
            )
            continue
        if not ledger.can_post():
            break  # depleted budget: no further motions this epoch (§5.5)
        bundle = bundles_by_target.get(cid)
        if bundle is None or not bundle.items:
            # No independently verified evidence — no motion (a bundle never
            # silently pads, so an empty one cannot support prosecution).
            findings.append(
                {"kind": "no_admissible_evidence", "component_id": cid}
            )
            continue
        charge = _deterministic_charge(entry)
        requested_action = "demote"
        if classification == CLASSIFY_BORDERLINE:
            raw = render_auditor(entry, bundle) if render_auditor else None
            reply = _parse_auditor_reply(raw) if raw is not None else None
            if reply is None:
                degradations.append(f"auditor_llm_fallback:{cid}")
                continue  # incumbent presumption
            if not reply["file_motion"]:
                continue
            charge = str(reply.get("charge") or charge)
            action = str(reply.get("requested_action") or requested_action)
            requested_action = action if action in MOTION_ACTIONS else "demote"
        try:
            motion = build_impeachment_motion(
                author_role=AUDITOR_ROLE,
                record_id=next_motion_id(),
                epoch_id=epoch_id,
                auditor_component_id=auditor_component_id,
                target_component_id=cid,
                target_role=role,
                charge=charge,
                evidence_bundle_id=bundle.record_id,
                bond_units=ledger.bond_units_per_motion,
                requested_action=requested_action,
                prompt_hash=(
                    _prompt_hash()
                    if classification == CLASSIFY_BORDERLINE
                    else None
                ),
            )
        except GovernanceRuleError as exc:
            findings.append(
                {"kind": "motion_refused", "component_id": cid,
                 "detail": str(exc)}
            )
            continue
        ledger.post()
        motions.append(motion)
    return motions
