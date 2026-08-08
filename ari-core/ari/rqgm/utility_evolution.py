"""PolicyMutator — the governed score's proposer (RQGM Task 14).

Design context: docs/concepts/rqgm_architecture.md, "Governed utility
evolution".

The defining claim of Constitutional ARI-RQGM is that the search is
tree-structured **and that at each epoch boundary the entire score — the
utility function itself — is rewritten**. The consequence half of that
sentence has always been live (``ari.rqgm.frontier_repair`` can already
destroy every score a retired utility policy produced). This module is part
of the CAUSE half: something has to PROPOSE a successor policy.

Three pieces, all Task 14:

* :class:`UtilityPolicyCandidate` — the proposal record (shape:
  docs/reference/rqgm_schemas.md, "`rqgm_utility_policy_candidate.schema.json`"),
  riding the existing prompt-evolution log; no new store.
* :class:`PolicyMutator` — the boundary proposer. A ``PromptMutator`` analog
  (``prompt_evolution.py``): it emits candidates ONLY and exposes no
  registry/store write surface. Status changes are Task 09's engine,
  kernel-validated.
* :class:`UtilityPolicyStamp` — the node-side half of the invalidation
  design: a per-node provenance stamp that lets a rewrite invalidate EVERY
  node scored under the old policy, not just the attacked-and-penalised
  subset that carries a UtilityRecord.

**No absolute ruler (P3).** The thing that proposes the score is itself a
registered, sanctionable, evolvable component: ``policy_mutator_v1`` is a
founding meta component whose own template (``rqgm/policy_mutator.md``) is
evolved by the PromptMutator like any other, and a governance recommendation
against it resolves into a T9/T10/T11 sanction like any other.

**Determinism (P2).** The four default mutation kinds are pure arithmetic
over the boundary's abstract evidence — no LLM, no clock, no randomness — so
the default utility rewrite is fully reproducible. Only the opt-in
``freeform_policy_proposal`` consults an LLM, and it returns ``None`` when
none is configured.

**No collusion (P2).** ``evidence`` is the boundary's already-abstract
material (Task 06 ``abstract_view`` dicts and governance reliability
entries). A policy is NEVER proposed from the frontier's current scores: a
score policy tuned to flatter the nodes it already produced is collusive
co-evolution, which is exactly the self-referential loop P2 forbids.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from ari.rqgm.events import (
    POLICY_MUTATOR_ROLE,
    UTILITY_POLICY_ROLE,
    canonical_json,
    format_prompt_id,
    hash12,
)
from ari.rqgm.kernel_rules import UTILITY_POLICY_RULES

log = logging.getLogger(__name__)

UTILITY_POLICY_CANDIDATE_RECORD_TYPE = "utility_policy_candidate"
UTILITY_POLICY_CANDIDATE_SCHEMA_VERSION = 1

#: The closed mutation family: a proposer may emit no kind outside this
#: tuple. The first four are pure arithmetic; only
#: ``freeform_policy_proposal`` consults an LLM.
MUTATION_KINDS: tuple[str, ...] = (
    "axis_reweighting",
    "composite_swap",
    "frontier_score_swap",
    "exploration_tuning",
    "freeform_policy_proposal",
)

#: The kinds that need no LLM — the deterministic default set.
KNOB_MUTATION_KINDS: frozenset[str] = frozenset({
    "axis_reweighting",
    "composite_swap",
    "frontier_score_swap",
    "exploration_tuning",
})

#: ``Node.metrics`` sentinel key: the epoch utility policy under which this
#: node's score was formed — the marker a retirement invalidates on.
#: Additive, persisted
#: through ``tree.json``, and NEVER written under ``simple_bfts`` — the
#: ``frontier_repair`` convention (``_stale`` / ``_valid_for_frontier`` /
#: ``_stale_reason`` / ``_erasure_event_id``) and the adversarial-engine
#: convention (``_pre_penalty_score`` / ``_validated_attack_penalty``).
UTILITY_POLICY_HASH_KEY = "_utility_policy_hash"


def _rounded(value: float) -> float:
    """6-decimal rounding — the arithmetic determinism convention shared with
    ``adversarial.engine.UtilityPenaltyPolicy.compute``."""
    return round(float(value), 6)


# ── the candidate record (rqgm_utility_policy_candidate.schema.json) ────────


@dataclass(frozen=True)
class UtilityPolicyCandidate:
    """One proposed successor utility policy. Record shape:
    docs/reference/rqgm_schemas.md,
    "`rqgm_utility_policy_candidate.schema.json`".

    The envelope is the mandatory common one
    (``kernel_rules.ENVELOPE_FIELDS``) and its author is the
    **policy_mutator**, not the policy: a candidate is a PROPOSAL BY A
    COMPONENT, which is why ``component_id`` / ``role`` / ``prompt_hash``
    name the proposer rather than the proposed policy. The proposed policy
    rides ``policy`` (by value) + ``policy_hash``.
    """

    record_id: str
    candidate_id: str
    policy: dict
    policy_hash: str
    epoch_id: str = ""
    component_id: str = "policy_mutator_v1"
    prompt_hash: str = ""
    role: str = POLICY_MUTATOR_ROLE
    created_at: str = ""  # metadata only; never hashed
    status: str = "candidate"
    parent_prompt_id: str | None = None
    mutation_kind: str = ""
    rationale: str = ""
    source_refs: tuple[str, ...] = ()
    schema_version: int = UTILITY_POLICY_CANDIDATE_SCHEMA_VERSION

    def to_dict(self) -> dict:
        return {
            "record_type": UTILITY_POLICY_CANDIDATE_RECORD_TYPE,
            "schema_version": self.schema_version,
            "record_id": self.record_id,
            "epoch_id": self.epoch_id,
            "component_id": self.component_id,
            "prompt_hash": self.prompt_hash,
            "role": self.role,
            "created_at": self.created_at,
            "status": self.status,
            "candidate_id": self.candidate_id,
            "parent_prompt_id": self.parent_prompt_id,
            "mutation_kind": self.mutation_kind,
            "policy": dict(self.policy),
            "policy_hash": self.policy_hash,
            "rationale": self.rationale,
            "source_refs": list(self.source_refs),
        }


def utility_policy_candidate_from_dict(d: dict) -> UtilityPolicyCandidate:
    """Rebuild a candidate from a parsed JSONL line (replay path)."""
    return UtilityPolicyCandidate(
        record_id=str(d.get("record_id", "")),
        candidate_id=str(d.get("candidate_id", "")),
        policy=dict(d.get("policy") or {}),
        policy_hash=str(d.get("policy_hash", "")),
        epoch_id=str(d.get("epoch_id", "")),
        component_id=str(d.get("component_id", "policy_mutator_v1")),
        prompt_hash=str(d.get("prompt_hash", "")),
        role=str(d.get("role", POLICY_MUTATOR_ROLE)),
        created_at=str(d.get("created_at", "")),
        status=str(d.get("status", "candidate")),
        parent_prompt_id=d.get("parent_prompt_id"),
        mutation_kind=str(d.get("mutation_kind", "")),
        rationale=str(d.get("rationale", "")),
        source_refs=tuple(d.get("source_refs") or ()),
        schema_version=int(
            d.get("schema_version", UTILITY_POLICY_CANDIDATE_SCHEMA_VERSION)
        ),
    )


# ── the four deterministic knob kinds: pure arithmetic, no LLM ──────────────


def _evidence_axis_pressure(evidence) -> dict[str, int]:
    """``axis -> count`` over the boundary's ABSTRACT evidence.

    Reads only already-abstract fields (Task 06 ``abstract_view``'s
    ``failure_mode`` / ``affected_axes`` and the governance reliability
    entries' ``axis``). Raw attack text never reaches this function — the
    same prohibition ``prompt_spec.FORBIDDEN_PLACEHOLDERS`` states for
    templates. Deterministic: sorted, count-based, no clock, no randomness.
    """
    pressure: dict[str, int] = {}
    for item in evidence or ():
        if not isinstance(item, dict):
            continue
        axes: list = []
        raw = item.get("affected_axes")
        if isinstance(raw, (list, tuple)):
            axes.extend(str(a) for a in raw if isinstance(a, str))
        single = item.get("axis")
        if isinstance(single, str) and single:
            axes.append(single)
        for axis in axes:
            pressure[axis] = pressure.get(axis, 0) + 1
    return dict(sorted(pressure.items()))


def _renormalise(weights: dict[str, float]) -> dict[str, float]:
    """Project *weights* onto the legal simplex: clamp each into
    ``[axis_weight_min, axis_weight_max]``, then rescale to
    ``axis_weight_sum`` — re-clamping after the rescale so the bounds win.

    The projection is what makes the knob kinds legal BY CONSTRUCTION rather
    than by luck: the kernel still validates the result (fail-closed), but a
    deterministic proposer should not emit a policy it knows is illegal.
    """
    lo = float(UTILITY_POLICY_RULES["axis_weight_min"])
    hi = float(UTILITY_POLICY_RULES["axis_weight_max"])
    want = float(UTILITY_POLICY_RULES["axis_weight_sum"])
    if not weights:
        return {}
    out = {k: min(hi, max(lo, float(v))) for k, v in sorted(weights.items())}
    # Feasibility: with n axes the reachable sum is [n*lo, n*hi]. Outside
    # that range no projection exists and the caller must not propose.
    n = len(out)
    if not (n * lo - 1e-9 <= want <= n * hi + 1e-9):
        return {}
    # Water-filling projection onto {w: sum == want, lo <= w_i <= hi}.
    # Each pass moves the deficit equally across the axes that can still
    # move IN THE NEEDED DIRECTION — an axis pinned at ``lo`` can still be
    # RAISED, an axis pinned at ``hi`` can still be LOWERED, so the
    # adjustable set is direction-aware, not "strictly interior". A
    # strictly-interior set empties whenever every axis sits on a bound
    # (e.g. {0.60, 0.60, 0.05} with want 1.0), which would return an
    # out-of-simplex policy the kernel then blocks — wasting the boundary's
    # one candidate on an illegal proposal. The loop is provably finite (a
    # hard pass cap) and deterministic (P2: no wall clock, no randomness);
    # for any feasible instance it converges in a few passes.
    for _ in range(128):
        total = sum(out.values())
        deficit = want - total
        if abs(deficit) <= 1e-12:
            break
        if deficit > 0:
            movable = [k for k, v in out.items() if v < hi - 1e-15]
        else:
            movable = [k for k, v in out.items() if v > lo + 1e-15]
        if not movable:
            break  # unreachable for a feasible instance (guarded above)
        share = deficit / len(movable)
        for k in movable:
            out[k] = min(hi, max(lo, out[k] + share))
    # Round for a readable, stable policy body, then repair the rounding
    # residual onto one axis with headroom — rounding 5 weights can shift the
    # sum by ~2.5e-6, and the kernel enforces sum-to-one at ``float_tolerance``
    # (1e-9), so an unrepaired round would emit a policy CK-UTL-005 blocks.
    rounded = {k: _rounded(v) for k, v in out.items()}
    residual = round(want - sum(rounded.values()), 12)
    if residual:
        if residual > 0:
            axis = max(rounded, key=lambda k: hi - rounded[k])
        else:
            axis = max(rounded, key=lambda k: rounded[k] - lo)
        repaired = min(hi, max(lo, rounded[axis] + residual))
        if abs(repaired - lo) < 1e-12 or abs(repaired - hi) < 1e-12:
            rounded[axis] = repaired  # snapped to a bound; keep it exact
        else:
            rounded[axis] = _rounded(repaired)
    return rounded


def _axis_reweighting(policy: dict, evidence) -> dict | None:
    """Shift weight TOWARD the axes the epoch's failures pressured.

    The direction is deliberate and is the whole point of P1: when the
    epoch's abstract evidence says nodes keep failing on
    ``measurement_validity``, the next epoch's score should weigh
    ``measurement_validity`` MORE, not less. A proposer that lowered the
    weight of the axis it keeps failing would be tuning the score to flatter
    the tree — the collusion this design forbids.
    """
    weights = policy.get("axis_weights")
    if not isinstance(weights, dict) or not weights:
        return None
    pressure = _evidence_axis_pressure(evidence)
    pressed = {a: c for a, c in pressure.items() if a in weights}
    if not pressed:
        return None
    step = float(UTILITY_POLICY_RULES["axis_weight_min"])
    total_pressure = sum(pressed.values())
    proposed = {str(k): float(v) for k, v in weights.items()}
    for axis, count in pressed.items():
        proposed[axis] = proposed[axis] + step * (count / total_pressure)
    new_weights = _renormalise(proposed)
    if not new_weights or new_weights == {
        k: _rounded(v) for k, v in sorted(weights.items())
    }:
        return None
    out = dict(policy)
    out["axis_weights"] = new_weights
    return out


def _cycle_swap(current, allowed: tuple) -> str | None:
    """The next value in the closed set, cyclically — a pure, total,
    deterministic successor with no clock and no randomness."""
    ordered = list(allowed)
    if str(current) not in ordered:
        return ordered[0] if ordered else None
    idx = ordered.index(str(current))
    return ordered[(idx + 1) % len(ordered)]


def _composite_swap(policy: dict, evidence) -> dict | None:
    nxt = _cycle_swap(
        policy.get("composite"), UTILITY_POLICY_RULES["allowed_composite"]
    )
    if nxt is None or nxt == policy.get("composite"):
        return None
    out = dict(policy)
    out["composite"] = nxt
    return out


def _frontier_score_swap(policy: dict, evidence) -> dict | None:
    nxt = _cycle_swap(
        policy.get("frontier_score"),
        UTILITY_POLICY_RULES["allowed_frontier_score"],
    )
    if nxt is None or nxt == policy.get("frontier_score"):
        return None
    out = dict(policy)
    out["frontier_score"] = nxt
    return out


def _exploration_tuning(policy: dict, evidence) -> dict | None:
    """More failure pressure => explore more (a higher ``ucb_c`` and a
    lighter depth penalty), bounded by the constitutional caps."""
    lam_cap = float(UTILITY_POLICY_RULES["depth_penalty_lambda_max"])
    ucb_cap = float(UTILITY_POLICY_RULES["ucb_c_max"])
    pressure = sum(_evidence_axis_pressure(evidence).values())
    if pressure <= 0:
        return None
    try:
        lam = float(policy.get("depth_penalty_lambda", 0.0))
        ucb = float(policy.get("ucb_c", 0.0))
    except (TypeError, ValueError):
        return None
    # Saturating step: bounded, monotone, and a pure function of the count.
    factor = min(1.0, pressure / 10.0)
    new_lam = _rounded(max(0.0, min(lam_cap, lam * (1.0 - 0.5 * factor))))
    new_ucb = _rounded(max(0.0, min(ucb_cap, ucb + 0.5 * factor)))
    if new_lam == _rounded(lam) and new_ucb == _rounded(ucb):
        return None
    out = dict(policy)
    out["depth_penalty_lambda"] = new_lam
    out["ucb_c"] = new_ucb
    return out


#: ``mutation_kind -> (incumbent_policy, evidence) -> policy | None``. Pure
#: functions: no LLM, no clock, no randomness (P2; bound by the
#: ``kernel_rules`` import-grep test extended to this module).
_KNOB_PROPOSERS: dict = {
    "axis_reweighting": _axis_reweighting,
    "composite_swap": _composite_swap,
    "frontier_score_swap": _frontier_score_swap,
    "exploration_tuning": _exploration_tuning,
}


def propose_utility_policy(
    incumbent_policy: dict, *, evidence=(), mutation_kind: str
) -> dict | None:
    """The four deterministic knob kinds as pure functions of
    ``(incumbent_policy, evidence)`` — same inputs, same proposal, always.

    Returns the proposed policy BODY (without the ``utility_policy_hash``
    seal), or ``None`` when the kind is unknown, is not a knob kind, or the
    evidence supports no change. Never raises.
    """
    fn = _KNOB_PROPOSERS.get(str(mutation_kind))
    if fn is None:
        return None
    body = {
        k: v for k, v in (incumbent_policy or {}).items()
        if k != "utility_policy_hash"
    }
    if not body:
        return None
    try:
        return fn(body, evidence)
    except Exception:
        log.warning("utility policy proposal (%s) failed", mutation_kind,
                    exc_info=True)
        return None


# ── the boundary dry-run: T1 legality + T3 replay board, both LLM-free ──────


def _axis_ranking_agreement(incumbent: dict, candidate: dict) -> float:
    """Kendall-tau-like agreement of the candidate's axis ORDERING with the
    incumbent's, over the shared axes. Pure, deterministic, pool-independent
    (P2: no LLM, no clock, no randomness). A knob rewrite that leaves the
    axis weights untouched (``composite_swap`` / ``frontier_score_swap`` /
    ``exploration_tuning``) scores a perfect 1.0; an ``axis_reweighting`` that
    only re-prioritises within the legal simplex preserves the ordering and so
    scores high — which is exactly the claim a candidate has to carry to be
    adopted: a legal successor "scores at least as well on the frozen replay
    board"."""
    axes = sorted(set(incumbent) & set(candidate))
    if len(axes) < 2:
        return 1.0
    concordant = discordant = 0
    for i in range(len(axes)):
        for j in range(i + 1, len(axes)):
            a, b = axes[i], axes[j]
            try:
                di = float(incumbent[a]) - float(incumbent[b])
                dc = float(candidate[a]) - float(candidate[b])
            except (TypeError, ValueError):
                continue
            if di == 0.0 or dc == 0.0:
                continue
            if (di > 0.0) == (dc > 0.0):
                concordant += 1
            else:
                discordant += 1
    total = concordant + discordant
    return 1.0 if total == 0 else _rounded(concordant / total)


def evaluate_utility_policy_candidate(
    body: dict, *, prompt_id: str, registered_hash: str = "",
    incumbent_body: dict | None = None, kernel=None, live_axes=None,
) -> dict:
    """The deterministic dry-run evaluation of ONE pending utility_policy
    candidate. Returns a ``candidate_evaluation``
    dict keyed on *prompt_id* that ``RegistryTransitionEngine.resolve_transition``
    consumes to iterate the policy up the T1 -> T3 -> T6 spine.

    Two components, both deterministic and LLM-free (P2):

    * **T1 legality (the CK-UTL rules).** Run the frozen kernel check
      ``validate_utility_policy``; a candidate that fails the constitution
      gets ``verdict="fail"`` (the engine's T1 guard rejects it into a T2
      retirement — an illegal policy never reaches shadow).
    * **T3 replay.** The policy's replay board is its re-scoring dry
      run. The evaluation basis is the axis set the policy re-weights (a
      policy is a score over axes); a legal, non-degenerate re-weighting
      preserves the incumbent's axis ordering, scoring ``_axis_ranking_agreement``.
      Pool-independent by construction, so the criterion keeps changing at
      boundaries even before an adversarial replay pool has filled (the
      Red-Queen posture P1 demands) — and when per-axis-scored replay cases do
      exist the ordering they induce is the same ordering this board reads.

    * **T6 shadow (amended 2026-07-17).** There is no third component:
      a passive policy document is never shadow-EXECUTED, so its shadow stage
      is VACUOUS by construction. It is reported as absent
      (``shadow_samples``/``shadow_score`` ``None`` + ``shadow_basis:
      "vacuous_passive_policy"``) and the T6 count floor is waived by role at
      the decision site, rather than back-filled from the T3 basis.

    The board fields (``replay_score`` / ``case_refs`` / ``shadow_samples`` /
    ``shadow_score``) are the generic spine inputs the role-agnostic engine
    already reads; the utility policy rides them like any governed prompt — and
    reports ABSENCE where it has no basis, so no downstream consumer reads a
    count or a score that nothing produced.
    Never raises: any failure degrades to the incumbent-safe path (the kernel
    gate on the live T6 adoption is the backstop).
    """
    # Local import: ``transition_engine`` is never imported under
    # ``simple_bfts`` — no transition machinery runs there — and this module
    # is.
    from ari.rqgm.transition_engine import (
        NO_REPLAY_BASIS_KEY,
        NO_SHADOW_BASIS_KEY,
    )

    body = {
        k: v for k, v in (body or {}).items() if k != "utility_policy_hash"
    }
    incumbent = {
        k: v for k, v in (incumbent_body or {}).items()
        if k != "utility_policy_hash"
    }
    legal = True
    if kernel is not None:
        try:
            report = kernel.validate_utility_policy(
                body, registered_hash=registered_hash, live_axes=live_axes,
            )
            legal = not getattr(report, "blocking", False)
        except Exception:
            # Never raise into the boundary; the live T6 kernel gate backstops.
            log.warning("utility policy legality dry-run failed for %s",
                        prompt_id, exc_info=True)
            legal = True

    cand_w = body.get("axis_weights")
    cand_w = cand_w if isinstance(cand_w, dict) else {}
    inc_w = incumbent.get("axis_weights")
    inc_w = inc_w if isinstance(inc_w, dict) else {}
    # The evaluation basis (the "cases" of the policy's replay board): the
    # policy's own dimensions — the governed knobs it re-weights (composite,
    # axis_weights, frontier_score, depth_penalty_lambda, ucb_c). A legal
    # policy carries exactly the constitutional required_keys, so this is a
    # stable count independent of whether ``axis_weights`` is populated (it is
    # empty under ``axis_mode: dynamic`` / the default config, where axes are
    # resolved at scoring time — the score still governs, so the criterion
    # still evolves). The re-ranking AGREEMENT below is what carries the
    # "scores at least as well" signal; the basis only counts the dimensions.
    case_refs = sorted(str(k) for k in body)
    # When both static weight maps are populated (``axis_mode`` not dynamic) the
    # re-ranking agreement is a real "scores at least as well" signal. Under the
    # DEFAULT config ``axis_weights`` is empty (axes resolve at scoring time), so
    # there is NO ordering to compare: the comparison never runs, and the board
    # is reported ABSENT (``None``) rather than as a ``1.0`` nobody computed.
    # The gate then reduces to legality (CK-UTL) + non-degeneracy, which is
    # intended, and it is the gate's honest scope: with no ground-truth
    # anchor there is no "strictly better" to gate on, and a legality-bounded
    # criterion that keeps moving is the Red-Queen posture. A real quality gate
    # needs an anchored per-axis basis — the paper phase's Task-04 anchor. See
    # docs/concepts/rqgm_architecture.md, "Governed utility evolution".
    #
    # `None` costs the T3 pass nothing: the `no_replay_basis` sentinel below
    # already carries it (`scores_ok` treats an absent board as abstaining, and
    # the waiver covers the count floor). The 1.0 was load-bearing for nothing
    # while contradicting the reporting rule this module holds to: no field
    # carries a quantity nothing produced.
    agreement = (
        _axis_ranking_agreement(inc_w, cand_w) if (inc_w and cand_w) else None
    )
    # A passive policy DOCUMENT carries no ``invoke`` grant — nothing ever
    # calls it — so it is never shadow-EXECUTED: there are zero live-shadow
    # comparisons behind it by construction. Report that absence rather than
    # borrow the T3 basis count — ``shadow_samples`` claims a sample count,
    # and dict keys are not samples. The T6 ``shadow_min_samples`` floor is
    # WAIVED by role, in the open, at the decision site
    # (transition_engine.NO_REPLAY_BASIS_ROLES), so T6 reduces to CK-UTL
    # legality + non-degeneracy +
    # the supersession/adoption-cap guards. The same sentinel waives T3's
    # ``replay_min_cases`` floor: ``case_refs`` below are the policy's own
    # DIMENSIONS, not executed replay cases, so the floor has nothing honest
    # to count. The T3 ``replay_score`` gate itself is untouched — the dry-run
    # agreement is real and still has to clear its threshold.
    vacuous_shadow = {
        "shadow_samples": None,
        "shadow_score": None,
        "shadow_basis": "vacuous_passive_policy",
        # Both floors are honestly absent for a passive policy, so both are
        # declared: T6's because it is never shadow-EXECUTED, T3's because
        # `case_refs` are the policy's own DIMENSIONS — never executed cases, so
        # that floor has nothing honest to count at ANY axis_mode.
        NO_SHADOW_BASIS_KEY: True,
        NO_REPLAY_BASIS_KEY: True,
    }
    if not legal:
        return {
            "prompt_id": str(prompt_id),
            "role": UTILITY_POLICY_ROLE,
            "verdict": "fail",
            # Illegal: the dry-run never scored it, so there is no board to
            # report. `verdict: "fail"` is the finding (T2 retires on it);
            # a 0.0 would be a score nobody computed.
            "replay_score": None,
            "anchor_score": None,
            "case_refs": [],
            "cached": False,
            **vacuous_shadow,
        }
    return {
        "prompt_id": str(prompt_id),
        "role": UTILITY_POLICY_ROLE,
        "verdict": "pass",
        "replay_score": agreement,
        "anchor_score": None,
        "case_refs": list(case_refs),
        "cached": False,
        **vacuous_shadow,
    }


# ── the proposer: emits candidates only, never writes the registry ──────────


class PolicyMutator:
    """Emits :class:`UtilityPolicyCandidate` records ONLY.

    Deliberately exposes no registry/store write surface (the PromptMutator
    contract; pinned by an attribute test): status changes are Task 09's
    engine, kernel-validated. Knob kinds are pure arithmetic over the epoch's
    evidence — no LLM, no clock, no randomness (P2). The freeform kind's
    meta-prompt is the committed ``rqgm/policy_mutator.md``.

    **No same-role generation.** PolicyMutator never proposes a
    ``policy_mutator`` policy — there is none. Its OWN template is evolved by
    the PromptMutator like any other meta template (the
    ``clean_room_generator`` precedent).
    """

    ROLE = POLICY_MUTATOR_ROLE
    TARGET_ROLE = UTILITY_POLICY_ROLE
    META_PROMPT_KEY = "rqgm/policy_mutator"

    def __init__(
        self,
        component_id: str = "policy_mutator_v1",
        *,
        llm=None,
        loader=None,
        checkpoint_dir=None,
    ) -> None:
        self.component_id = component_id
        self._llm = llm
        self._loader = loader
        self._checkpoint_dir = checkpoint_dir

    def _meta_prompt(self) -> tuple[str, str]:
        loader = self._loader
        if loader is None:
            from ari.prompts import FilesystemPromptLoader

            loader = FilesystemPromptLoader()
        # Literal key (== META_PROMPT_KEY) so the reference analyzer's
        # dynamic overlay sees the template edge (scripts/analyze_references).
        return loader.load_versioned("rqgm/policy_mutator")

    def propose(
        self,
        incumbent_policy: dict,
        *,
        evidence=(),
        mutation_kind: str = "axis_reweighting",
        epoch_id: str = "",
        record_seq: int = 0,
        existing_records: list[dict] | None = None,
        cfg=None,
        parent_prompt_id: str | None = None,
        incumbent_version: int = 1,
        rationale: str = "",
    ) -> "UtilityPolicyCandidate | None":
        """Propose one successor utility policy. Never raises.

        Returns ``None`` when over budget, when the kind is unknown, when a
        freeform kind has no LLM, or when the evidence supports no change.

        *evidence* is the boundary's already-abstract material (Task 06
        ``abstract_view`` dicts + governance reliability entries). The
        frontier's current scores are deliberately NOT an input.
        """
        try:
            return self._propose(
                incumbent_policy,
                evidence=evidence,
                mutation_kind=mutation_kind,
                epoch_id=epoch_id,
                record_seq=record_seq,
                existing_records=existing_records,
                cfg=cfg,
                parent_prompt_id=parent_prompt_id,
                incumbent_version=incumbent_version,
                rationale=rationale,
            )
        except Exception:
            log.warning("policy mutation failed (fail-open: no candidate "
                        "this epoch)", exc_info=True)
            return None

    def _propose(
        self, incumbent_policy, *, evidence, mutation_kind, epoch_id,
        record_seq, existing_records, cfg, parent_prompt_id,
        incumbent_version, rationale,
    ) -> "UtilityPolicyCandidate | None":
        if mutation_kind not in MUTATION_KINDS:
            log.warning("unknown utility mutation_kind %r; skipping",
                        mutation_kind)
            return None
        if existing_records is not None:
            # Budget reuse, one schema home: utility candidates are capped by
            # the existing rqgm.prompt_evolution per-epoch caps rather than a
            # second budget, keyed on the TARGET role.
            from ari.rqgm.prompt_evolution import candidate_budget_reason

            reason = candidate_budget_reason(
                existing_records, epoch_id, self.TARGET_ROLE, cfg
            )
            if reason is not None:
                log.info("utility policy mutation skipped: %s", reason)
                return None

        body = {
            k: v for k, v in (incumbent_policy or {}).items()
            if k != "utility_policy_hash"
        }
        if not body:
            return None

        if mutation_kind in KNOB_MUTATION_KINDS:
            proposed = propose_utility_policy(
                body, evidence=evidence, mutation_kind=mutation_kind
            )
        else:
            proposed = self._propose_freeform(body, evidence, mutation_kind)
        if not proposed:
            return None
        policy_hash = hash12(canonical_json(proposed))
        if policy_hash == hash12(canonical_json(body)):
            return None  # a no-op rewrite is not a rewrite

        candidate_id = format_prompt_id(
            self.TARGET_ROLE, int(incumbent_version) + 1
        )
        return UtilityPolicyCandidate(
            record_id=f"upc_{int(record_seq):06d}",
            candidate_id=candidate_id,
            policy=proposed,
            policy_hash=policy_hash,
            epoch_id=str(epoch_id or ""),
            component_id=self.component_id,
            prompt_hash=self._meta_prompt_hash(),
            role=self.ROLE,
            created_at=_now_iso(),
            status="candidate",
            parent_prompt_id=parent_prompt_id,
            mutation_kind=str(mutation_kind),
            rationale=str(rationale or ""),
            source_refs=tuple(_evidence_refs(evidence)),
        )

    def _meta_prompt_hash(self) -> str:
        """The proposer's OWN template hash — the envelope's ``prompt_hash``
        names the author, not the proposal. Best-effort: an unresolvable
        template must not cost a boundary its candidate."""
        try:
            return self._meta_prompt()[1]
        except Exception:
            log.warning("policy_mutator meta-prompt hash unresolvable",
                        exc_info=True)
            return ""

    def _propose_freeform(self, body: dict, evidence, mutation_kind):
        """``freeform_policy_proposal``: the ONE LLM-backed kind (opt-in).

        Returns ``None`` when no LLM is configured — the exact
        ``PromptMutator`` posture. An irreproducible PROPOSAL can never
        become an unvalidated POLICY: the kernel validates it either way.
        """
        if self._llm is None:
            return None
        template, _h = self._meta_prompt()
        rules = UTILITY_POLICY_RULES
        rendered = template.format(
            mutation_kind=mutation_kind,
            incumbent_policy_block=canonical_json(body),
            evidence_block="\n".join(
                canonical_json(e) for e in (evidence or ())
            ) or "(none)",
            allowed_composite_block=", ".join(rules["allowed_composite"]),
            allowed_frontier_score_block=", ".join(
                rules["allowed_frontier_score"]
            ),
            axis_weight_min=rules["axis_weight_min"],
            axis_weight_max=rules["axis_weight_max"],
            axis_weight_sum=rules["axis_weight_sum"],
            depth_penalty_lambda_max=rules["depth_penalty_lambda_max"],
            ucb_c_max=rules["ucb_c_max"],
        )
        raw = self._llm(rendered)
        if not raw:
            return None
        try:
            parsed = json.loads(str(raw).strip())
        except (TypeError, ValueError):
            log.warning("freeform policy proposal was not JSON; skipping")
            return None
        if not isinstance(parsed, dict):
            return None
        parsed.pop("utility_policy_hash", None)
        return parsed


def utility_policy_registration_payload(candidate) -> dict:
    """The candidate-intake ``prompt_registered`` payload
    (``status="candidate"``) for a minted utility-policy candidate.

    The storage face of intake: the NEXT boundary's ``resolve_transition``
    iterates the entry through the T1→T6 spine like any other governed
    prompt (the T-table is role-agnostic — a utility policy rides the
    existing T1-T6 rule ids and needs no new ones). ``role`` is the TARGET
    role (``utility_policy``), not the
    proposer's: the registry entry IS the policy, whereas the candidate
    RECORD is a proposal by the policy_mutator.
    """
    import hashlib

    if isinstance(candidate, dict):
        candidate_id = str(candidate.get("candidate_id", ""))
        policy = dict(candidate.get("policy") or {})
        epoch_id = str(candidate.get("epoch_id", ""))
        record_id = str(candidate.get("record_id", ""))
    else:
        candidate_id = candidate.candidate_id
        policy = dict(candidate.policy)
        epoch_id = candidate.epoch_id
        record_id = candidate.record_id
    body = canonical_json(policy)
    full = hashlib.sha256(body.encode("utf-8")).hexdigest()
    from ari.rqgm.prompt_spec import utility_policy_body_path

    return {
        "prompt_id": candidate_id,
        "role": UTILITY_POLICY_ROLE,
        "status": "candidate",
        "prompt_hash": full[:12],
        "prompt_sha256": full,
        "source": {
            "kind": "policy",
            "path": utility_policy_body_path(candidate_id),
        },
        "spec_ref": candidate_id,
        "epoch_id": epoch_id,
        "source_refs": [record_id] if record_id else [],
    }


def _evidence_refs(evidence) -> list[str]:
    """Abstract evidence ids for the candidate's ``source_refs`` — never the
    evidence content itself."""
    out: list[str] = []
    for item in evidence or ():
        if not isinstance(item, dict):
            continue
        for key in ("record_id", "case_id", "summary_id", "entry_id"):
            val = item.get(key)
            if isinstance(val, str) and val:
                out.append(val)
                break
    return sorted(set(out))


def _now_iso() -> str:
    """Metadata only — never hashed (P2: the candidate's identity is its
    policy bytes)."""
    import time

    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ── the node stamp: every scored node carries the policy that scored it ─────


class UtilityPolicyStamp:
    """Stamps the epoch's utility-policy hash onto every scored node.

    **Why this exists.** ``apply_utility_penalty`` returns ``None`` when the
    penalty is 0, so ONLY attacked-and-penalised nodes carry a
    ``UtilityRecord``. If invalidation re-pointed only those records, a
    policy rewrite would invalidate the penalised subset and
    leave every unattacked node in the frontier holding an old-policy score —
    a RANDOM half-rewrite, which is worse than none: the frontier would then
    mix two incomparable score regimes with no marker saying which is which.
    P1 says the ENTIRE score is rewritten. This stamp is how a node's own
    provenance carries that answer.

    Why a stamp and not a second record type: a second ``utl_``-prefixed
    emitter would allocate ids from a second counter while
    ``frontier_repair.load_rqgm_records`` dedupes by ``record_id`` — colliding
    ids would silently DROP records. The stamp needs no allocator, no store
    and no schema, and it rides ``tree.json`` so it survives resume.

    Attached by ``RQGMRuntime.wrap_node_executor`` ONLY, so the key is never
    written under ``simple_bfts``. Best-effort: never raises into a node.
    """

    def __init__(self, *, epoch_state=None) -> None:
        self._epoch_state = epoch_state  # value or zero-arg callable

    def policy_hash(self) -> str:
        ep = self._epoch_state
        try:
            ep = ep() if callable(ep) else ep
        except Exception:
            return ""
        if ep is None:
            return ""
        policy = (
            ep.get("utility_policy") if isinstance(ep, dict)
            else getattr(ep, "utility_policy", None)
        )
        if not isinstance(policy, dict):
            return ""
        return str(policy.get("utility_policy_hash", "") or "")

    def __call__(self, node) -> str:
        """Stamp *node* with the epoch's policy hash; return what was
        stamped (``""`` == nothing).

        Only SCORED nodes are stamped: the stamp records the policy a score
        was formed under, and a node with no score has no score to
        invalidate.
        """
        try:
            metrics = getattr(node, "metrics", None)
            if not isinstance(metrics, dict):
                return ""
            if metrics.get("_scientific_score") is None:
                return ""
            h = self.policy_hash()
            if not h:
                return ""
            metrics[UTILITY_POLICY_HASH_KEY] = h
            return h
        except Exception:
            log.warning("utility policy stamp failed (node untouched)",
                        exc_info=True)
            return ""
