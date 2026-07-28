"""The nine-step ``audit_epoch`` pipeline (Task 05 §5.3).

observe → assess → assemble → prosecute → defend → adjudicate → update
replay pool → self-audit → report. Every LLM decision has a *total*
deterministic fallback (the lineage ``fallback_continue`` pattern); step
failures degrade the report (``degradation_reasons``) instead of aborting the
audit — only step-9 serialization may raise into the facade's caller.

Read-only with respect to registries, the frontier, ``tree.json`` and node
state: the pipeline returns records; the facade appends them to the Task 02
audit log. LLM calls are capped by ``rqgm.governance.max_llm_calls_per_audit``
and tagged ``phase="governance" skill="governance_orchestrator"`` for cost
attribution (the ``epoch`` tag rides the Task 02 default-metadata stamp).
"""

from __future__ import annotations

import json
import logging

from ari.rqgm.governance._adjudication import (
    adjudicate_motion,
    evaluate_candidates,
)
from ari.rqgm.governance._defense import generate_defenses
from ari.rqgm.governance._evidence import (
    assemble_evidence_bundle,
    candidate_refs_for_target,
)
from ari.rqgm.governance._prosecution import (
    BondLedger,
    classify_target,
    decide_prosecutions,
)
from ari.rqgm.governance._records import (
    AUDITOR_ROLE,
    DEFENDER_ROLE,
    EVIDENCE_CLERK_ROLE,
    GOVERNANCE_JUDGE_ROLE,
    GovernanceReport,
    ImpeachmentOutcome,
)
from ari.rqgm.governance._reliability import build_reliability_entries
from ari.rqgm.governance._self_audit import run_self_audit

log = logging.getLogger(__name__)

#: Deterministic fallback component ids used ONLY when no governed component of
#: the role is registered (``simple_bfts`` stubs / tests that skip the founding
#: bootstrap). #78b (2026-07-28): the auditor / evidence_clerk / governance_judge
#: roles are now in ``ari.rqgm.prompt_spec.FOUNDING_COMPONENT_TABLE``, so under a
#: real ``ari_rqgm`` boot ``_actor_id`` resolves each to its registered
#: ``*_v1`` component (like DEFENDER) — the whole judiciary is now inside the
#: impeachment net (P3/P4). These ``*_v0`` ids survive only as the no-registry
#: fallback; a live run never uses them.
_DEFAULT_ACTOR_IDS = {
    AUDITOR_ROLE: "auditor_v0",
    EVIDENCE_CLERK_ROLE: "evidence_clerk_v0",
    DEFENDER_ROLE: "defender_v0",
    GOVERNANCE_JUDGE_ROLE: "governance_judge_v0",
}


def _cfg(obj, name, default):
    """Duck-typed config read (typed model, raw dict, or absent)."""
    if isinstance(obj, dict):
        raw = obj.get(name, default)
    else:
        raw = getattr(obj, name, default)
    try:
        return type(default)(raw)
    except (TypeError, ValueError):
        return default


class _LLMBudget:
    """Counting wrapper enforcing ``max_llm_calls_per_audit`` (§5.3/§9.9).

    *manager* (RQGM Task 12 §7, optional GovernanceBudgetManager) is
    consulted before every call — a non-allow verdict degrades to the
    deterministic fallback (spend caps / ``on_exhausted`` posture); a
    successful call is booked back for spend attribution.
    """

    def __init__(self, llm, max_calls: int, manager=None) -> None:
        self._llm = llm
        self.max_calls = int(max_calls)
        self.used = 0
        self.exhausted = False
        self._manager = manager

    def _manager_allows(self) -> bool:
        if self._manager is None:
            return True
        try:
            from ari.rqgm.budget import GOVERNANCE_LLM_CALL, BudgetedAction

            return self._manager.gate(
                BudgetedAction(GOVERNANCE_LLM_CALL)
            ).allowed
        except Exception:
            log.warning("budget manager consult failed (fail-open)",
                        exc_info=True)
            return True

    def _manager_consume(self) -> None:
        if self._manager is None:
            return
        try:
            from ari.rqgm.budget import GOVERNANCE_LLM_CALL, BudgetedAction

            self._manager.consume(BudgetedAction(GOVERNANCE_LLM_CALL))
        except Exception:
            log.warning("budget manager consume failed", exc_info=True)

    def complete(self, prompt: str) -> str | None:
        """One governance LLM call; ``None`` means "use the deterministic
        fallback" (no LLM, budget spent, or call failure)."""
        if self._llm is None:
            return None
        if self.used >= self.max_calls:
            self.exhausted = True
            return None
        if not self._manager_allows():
            self.exhausted = True
            return None
        self.used += 1
        self._manager_consume()
        messages = [{"role": "user", "content": prompt}]
        try:
            try:
                resp = self._llm.complete(
                    messages,
                    require_tool=False,
                    phase="governance",
                    skill="governance_orchestrator",
                )
            except TypeError:
                # Duck-typed stubs without the metadata kwargs.
                resp = self._llm.complete(messages, require_tool=False)
        except Exception:
            log.warning("governance LLM call failed", exc_info=True)
            return None
        return getattr(resp, "content", "") or ""


class _GovernancePrompts:
    """Committed governance templates (``scripts/check_prompts.py``-safe:
    no inline prompt strings; ``load_versioned`` hash IS the prompt_hash)."""

    def __init__(self, loader=None) -> None:
        if loader is None:
            from ari.prompts import FilesystemPromptLoader

            loader = FilesystemPromptLoader()
        self.auditor = self.defender = self.judge = None
        try:
            self.auditor = loader.load_versioned("governance/auditor")
        except Exception:
            log.warning("governance/auditor prompt load failed", exc_info=True)
        try:
            self.defender = loader.load_versioned("governance/defender")
        except Exception:
            log.warning("governance/defender prompt load failed", exc_info=True)
        try:
            self.judge = loader.load_versioned("governance/governance_judge")
        except Exception:
            log.warning("governance/governance_judge prompt load failed",
                        exc_info=True)

    @staticmethod
    def _record_use(key: str, prompt_hash: str, rendered: str) -> None:
        try:
            from ari.prompts import record_prompt_use

            record_prompt_use(
                key, prompt_hash, rendered_text=rendered, phase="governance"
            )
        except Exception:
            pass

    def render_auditor(self, entry: dict, bundle) -> tuple[str, str] | None:
        if self.auditor is None:
            return None
        template, prompt_hash = self.auditor
        try:
            text = template.format(
                target_component_id=str(entry.get("component_id", "")),
                target_role=str(entry.get("role", "")),
                reliability_block=json.dumps(entry, sort_keys=True),
                evidence_block=json.dumps(bundle.to_dict(), sort_keys=True),
            )
        except Exception:
            return None
        self._record_use("governance/auditor", prompt_hash, text)
        return text, prompt_hash

    def render_defender(
        self, motion, bundle, target_records: list
    ) -> tuple[str, str] | None:
        if self.defender is None:
            return None
        template, prompt_hash = self.defender
        try:
            text = template.format(
                motion_block=json.dumps(motion.to_dict(), sort_keys=True),
                evidence_block=json.dumps(
                    bundle.to_dict() if bundle is not None else {},
                    sort_keys=True,
                ),
                target_outputs_block="\n".join(
                    f"- {rid}" for rid in target_records
                ),
            )
        except Exception:
            return None
        self._record_use("governance/defender", prompt_hash, text)
        return text, prompt_hash

    def render_judge(
        self, motion, defense, replay_score, anchor_score
    ) -> tuple[str, str] | None:
        if self.judge is None:
            return None
        template, prompt_hash = self.judge
        try:
            text = template.format(
                motion_block=json.dumps(motion.to_dict(), sort_keys=True),
                defense_block=json.dumps(
                    defense.to_dict() if defense is not None else {},
                    sort_keys=True,
                ),
                board_scores_block=json.dumps(
                    {"replay_score": replay_score, "anchor_score": anchor_score},
                    sort_keys=True,
                ),
            )
        except Exception:
            return None
        self._record_use("governance/governance_judge", prompt_hash, text)
        return text, prompt_hash


def _epoch_records(audit_log, epoch_id: str) -> dict:
    """Step-1 observation scan: the epoch's record slice, id → record dict.

    Accepts Task 02 ``ImmutableAuditLog.read`` line dicts (record inside
    ``payload``) or bare record dicts (test fixtures). Records without a
    ``record_id`` or from another epoch are skipped; last write wins.
    """
    out: dict = {}
    for entry in audit_log or ():
        d = entry if isinstance(entry, dict) else getattr(
            entry, "to_dict", lambda: dict(vars(entry))
        )()
        rec = d
        if isinstance(d.get("payload"), dict) and "event_type" in d:
            rec = dict(d["payload"])
            rec.setdefault("record_type", str(d.get("event_type", "")))
        rid = str(rec.get("record_id", "") or "")
        if not rid:
            continue
        if epoch_id and str(rec.get("epoch_id", "") or "") != epoch_id:
            continue
        out[rid] = rec
    return out


def _make_alloc(prefix: str, base: int):
    counter = {"n": int(base)}

    def alloc() -> str:
        counter["n"] += 1
        return f"{prefix}_{counter['n']:05d}"

    return alloc


def _actor_id(component_registry, role: str) -> str:
    active = getattr(component_registry, "active_set", None)
    if callable(active):
        try:
            found = active().get(role)
            if found:
                return str(found)
        except Exception:
            pass
    return _DEFAULT_ACTOR_IDS.get(role, f"{role}_v0")


def _epoch_field(epoch_state, name: str, default=""):
    if isinstance(epoch_state, dict):
        return epoch_state.get(name, default)
    return getattr(epoch_state, name, default)


def _retirement_pending(motion, component_registry) -> bool:
    """True when *motion* puts a RetirementEvent under consideration
    (Task 12 §5.4): it requests ``retire`` outright, or it targets a
    quarantined component — the from-status of Task 09's T17
    ``adjudication_confirmed_retirement`` edge, so an upheld outcome here
    is what confirms the retirement. Deterministic; registry reads are
    duck-typed (``get -> entry.status``) and absence-tolerant."""
    if str(getattr(motion, "requested_action", "") or "") == "retire":
        return True
    get = getattr(component_registry, "get", None)
    if not callable(get):
        return False
    try:
        entry = get(str(getattr(motion, "target_component_id", "") or ""))
    except Exception:
        log.warning("registry status read failed", exc_info=True)
        return False
    status = (
        entry.get("status") if isinstance(entry, dict)
        else getattr(entry, "status", "")
    )
    return str(status or "") == "quarantine"


def _motion_replay_cap(
    *,
    retirement: bool,
    max_cases: int,
    max_cases_retirement: int,
    budget_manager,
    motion_id: str,
) -> tuple[int, bool]:
    """The §5.4 epoch-boundary replay-selection cap for one motion:
    ``rqgm.replay.max_cases_per_epoch``, or the higher
    ``max_cases_for_retirement`` when a RetirementEvent is under
    consideration. A present Task 12 budget manager is consulted read-only
    (``REPLAY_CASE`` with ``retirement_pending``, fail-open) so booked
    replay consumption elsewhere in the epoch lowers the cap; the pipeline
    itself does not consume — the boundary audit runs once per epoch and
    an interrupted-boundary re-run must not self-starve its boards.
    Returns ``(cap, exhausted)``; *exhausted* is True only on a
    manager-reported empty budget (caller degrades by skipping board
    selection, never blocks)."""
    cap = max_cases_retirement if retirement else max_cases
    if budget_manager is None:
        return cap, False
    try:
        from ari.rqgm.budget import REPLAY_CASE, BudgetedAction

        verdict = budget_manager.gate(
            BudgetedAction(REPLAY_CASE, retirement_pending=retirement),
            node_id=motion_id,
        )
        remaining = getattr(verdict, "remaining", None)
        if remaining is not None and int(remaining) < cap:
            return max(0, int(remaining)), int(remaining) <= 0
    except Exception:
        log.warning("replay budget consult failed (config cap)",
                    exc_info=True)
    return cap, False


def run_audit(
    *,
    gov_cfg,
    replay_cfg,
    kernel,
    llm,
    epoch_state,
    audit_log,
    component_registry,
    prompt_registry,
    candidate_prompts=(),
    adversarial_replay_pool=None,
    loader=None,
    budget_manager=None,
    governance_cache=None,
) -> tuple[GovernanceReport, list]:
    """Run the nine steps; return ``(report, produced_records)`` where
    ``produced_records`` is the ordered ``(record_type, payload)`` list the
    facade appends to the audit log (the report itself is appended last by
    the facade). Only report construction may raise."""
    degradations: list = []
    findings: list = []
    epoch_id = str(_epoch_field(epoch_state, "epoch_id", "") or "")

    max_llm = _cfg(gov_cfg, "max_llm_calls_per_audit", 12)
    max_motions = _cfg(gov_cfg, "max_motions_per_epoch", 2)
    bond_units = _cfg(gov_cfg, "bond_units_per_motion", 1)
    jury_enabled = _cfg(gov_cfg, "jury_panel_enabled", False)
    default_level = _cfg(gov_cfg, "default_level", 1)
    max_cases = _cfg(replay_cfg, "max_cases_per_epoch", 8)
    max_cases_retirement = _cfg(replay_cfg, "max_cases_for_retirement", 12)
    use_cached = _cfg(replay_cfg, "use_cached_results", True)

    budget = _LLMBudget(llm, max_llm, manager=budget_manager)
    prompts = _GovernancePrompts(loader) if llm is not None else None

    # ── 1. observe (deterministic audit-log scan) ─────────────────────
    try:
        records_by_id = _epoch_records(audit_log, epoch_id)
    except Exception:
        log.warning("governance step 1 (observe) failed", exc_info=True)
        degradations.append("step_failed:observe")
        records_by_id = {}
    observation_ids = sorted(
        rid for rid, rec in records_by_id.items()
        if rec.get("record_type") == "comparison_observation"
    )

    # ── 2. assess reliability ─────────────────────────────────────────
    try:
        reliability = build_reliability_entries(
            list(records_by_id.values()), component_registry
        )
    except Exception:
        log.warning("governance step 2 (assess) failed", exc_info=True)
        degradations.append("step_failed:assess_reliability")
        reliability = []

    clerk_id = _actor_id(component_registry, EVIDENCE_CLERK_ROLE)
    auditor_id = _actor_id(component_registry, AUDITOR_ROLE)
    defender_id = _actor_id(component_registry, DEFENDER_ROLE)
    judge_id = _actor_id(component_registry, GOVERNANCE_JUDGE_ROLE)

    def _base(record_type: str) -> int:
        return sum(
            1 for rec in records_by_id.values()
            if rec.get("record_type") == record_type
        )

    next_bundle_id = _make_alloc("evb", _base("evidence_bundle"))
    next_motion_id = _make_alloc("imp", _base("impeachment_motion"))
    next_defense_id = _make_alloc("def", _base("governance_defense"))
    next_outcome_id = _make_alloc("adj", _base("impeachment_outcome"))

    # ── 3. assemble evidence for every threshold-flagged target ──────
    classifications: list = []
    bundles_by_target: dict = {}
    try:
        for entry in reliability:
            classification = classify_target(entry)
            if classification is None:
                continue
            classifications.append((entry, classification))
        for entry, _ in classifications:
            cid = str(entry.get("component_id", ""))
            bundles_by_target[cid] = assemble_evidence_bundle(
                record_id=next_bundle_id(),
                epoch_id=epoch_id,
                clerk_component_id=clerk_id,
                target_component_id=cid,
                target_role=str(entry.get("role", "") or ""),
                candidate_refs=candidate_refs_for_target(records_by_id, cid),
                records_by_id=records_by_id,
            )
    except Exception:
        log.warning("governance step 3 (assemble) failed", exc_info=True)
        degradations.append("step_failed:assemble_evidence")
        classifications, bundles_by_target = [], {}

    # ── 4. decide prosecution (rule-first, LLM-second) ────────────────
    ledger = BondLedger(
        bond_units_per_motion=bond_units, max_motions_per_epoch=max_motions
    )
    auditor_prompt_hash = None

    def _render_auditor(entry, bundle):
        nonlocal auditor_prompt_hash
        if prompts is None:
            return None
        rendered = prompts.render_auditor(entry, bundle)
        if rendered is None:
            return None
        text, auditor_prompt_hash = rendered
        return budget.complete(text)

    try:
        motions = decide_prosecutions(
            classifications=classifications,
            bundles_by_target=bundles_by_target,
            ledger=ledger,
            epoch_id=epoch_id,
            auditor_component_id=auditor_id,
            auditor_prompt_hash=lambda: auditor_prompt_hash,
            next_motion_id=next_motion_id,
            render_auditor=_render_auditor if llm is not None else None,
            degradations=degradations,
            findings=findings,
        )
    except Exception:
        log.warning("governance step 4 (prosecute) failed", exc_info=True)
        degradations.append("step_failed:prosecute")
        motions = []
    bundles_by_id = {
        b.record_id: b for b in bundles_by_target.values()
    }

    # ── 5. generate defenses ──────────────────────────────────────────
    defender_prompt_hash = None

    def _render_defender(motion, bundle, target_records):
        nonlocal defender_prompt_hash
        if prompts is None:
            return None
        rendered = prompts.render_defender(motion, bundle, target_records)
        if rendered is None:
            return None
        text, defender_prompt_hash = rendered
        return budget.complete(text)

    try:
        defenses = generate_defenses(
            motions=motions,
            bundles_by_id=bundles_by_id,
            records_by_id=records_by_id,
            epoch_id=epoch_id,
            defender_component_id=defender_id,
            defender_prompt_hash=lambda: defender_prompt_hash,
            next_defense_id=next_defense_id,
            render_defender=_render_defender if llm is not None else None,
            degradations=degradations,
        )
    except Exception:
        log.warning("governance step 5 (defend) failed", exc_info=True)
        degradations.append("step_failed:defend")
        defenses = []
    defenses_by_motion = {d.motion_id: d for d in defenses}

    # ── 6. adjudicate (bounded LLM) + candidate boards ────────────────
    judge_prompt_hash = None

    def _render_judge(motion, defense, replay_score, anchor_score):
        nonlocal judge_prompt_hash
        if prompts is None:
            return None
        rendered = prompts.render_judge(
            motion, defense, replay_score, anchor_score
        )
        if rendered is None:
            return None
        text, judge_prompt_hash = rendered
        return budget.complete(text)

    active_hashes = dict(
        _epoch_field(epoch_state, "active_prompt_hashes", {}) or {}
    )
    reliability_by_cid = {
        str(e.get("component_id", "")): e for e in reliability
    }
    adjudications: list = []
    outcomes: list = []
    outcomes_by_motion: dict = {}
    replay_cases_used = 0
    anchor_cases_used = 0
    try:
        for motion in motions:
            # adjudicator != target: the governance judge must never rule on a
            # motion targeting ITSELF (self-adjudication = the judge clearing its
            # own impeachment). No alternate adjudicator exists, so such a motion
            # is RECUSED — left unresolved (no outcome, never self-dismissed) and
            # flagged loudly for external adjudication, rather than decided by the
            # accused. Same for a defender/clerk motion adjudicated by a judge
            # that IS the target.
            if judge_id and str(motion.target_component_id) == str(judge_id):
                degradations.append(f"self_adjudication_recused:{judge_id}")
                log.warning("governance: recusing self-adjudication — motion %s "
                            "targets the judge %s; left unresolved",
                            getattr(motion, "record_id", "?"), judge_id)
                continue
            entry = reliability_by_cid.get(motion.target_component_id, {})
            subject_keys = tuple(
                k
                for k in (
                    motion.target_component_id,
                    entry.get("prompt_hash"),
                    active_hashes.get(motion.target_role),
                )
                if k
            )
            # Task 12 §5.4: a RetirementEvent under consideration lifts the
            # replay-selection cap to max_cases_for_retirement (T17's
            # coverage guard reads the resulting replay_cases_used).
            motion_cases, replay_exhausted = _motion_replay_cap(
                retirement=_retirement_pending(motion, component_registry),
                max_cases=max_cases,
                max_cases_retirement=max_cases_retirement,
                budget_manager=budget_manager,
                motion_id=motion.record_id,
            )
            verdict = adjudicate_motion(
                motion=motion,
                defense=defenses_by_motion.get(motion.record_id),
                # Exhausted REPLAY_CASE budget: no board selection at all
                # (board_score reads max_cases 0 as unlimited, so the pool
                # is dropped instead — degrade, never block).
                pool=None if replay_exhausted else adversarial_replay_pool,
                subject_keys=subject_keys,
                max_cases=motion_cases,
                jury_samples=3 if jury_enabled else 1,
                render_judge=_render_judge if llm is not None else None,
                degradations=degradations,
                findings=findings,
            )
            replay_cases_used += verdict["replay_used"]
            anchor_cases_used += verdict["anchor_used"]
            ledger.settle(verdict["outcome"])
            outcome = ImpeachmentOutcome(
                record_id=next_outcome_id(),
                epoch_id=epoch_id,
                motion_id=motion.record_id,
                outcome=verdict["outcome"],
                judge_component_id=judge_id,
                judge_prompt_hash=judge_prompt_hash,
                replay_result_ref=(
                    f"replay_{epoch_id}_{motion.target_role}"
                    if verdict["replay_score"] is not None
                    else ""
                ),
                anchor_result_ref=(
                    f"anchor_{epoch_id}_{motion.target_role}"
                    if verdict["anchor_score"] is not None
                    else ""
                ),
                rationale=verdict["rationale"],
                clamped_by_board=verdict["clamped"],
            )
            outcomes.append(outcome)
            outcomes_by_motion[motion.record_id] = verdict["outcome"]
            adjudications.append(
                {
                    "motion_id": motion.record_id,
                    "outcome": verdict["outcome"],
                    "judge_component_id": judge_id,
                    "judge_prompt_hash": judge_prompt_hash,
                    "replay_result_ref": outcome.replay_result_ref,
                    "anchor_result_ref": outcome.anchor_result_ref,
                    "rationale_ref": outcome.record_id,
                }
            )
    except Exception:
        log.warning("governance step 6 (adjudicate) failed", exc_info=True)
        degradations.append("step_failed:adjudicate")
    try:
        candidate_evaluations, cand_replay_used, cand_anchor_used = (
            evaluate_candidates(
                candidate_prompts=candidate_prompts,
                pool=adversarial_replay_pool,
                max_cases=max_cases,
                use_cached=use_cached,
                # Task 12 §5.5: with use_cached_results the governance cache
                # is consulted before the pool's stored case results.
                cache=governance_cache,
            )
        )
        replay_cases_used += cand_replay_used
        anchor_cases_used += cand_anchor_used
    except Exception:
        log.warning("governance step 6 (candidates) failed", exc_info=True)
        degradations.append("step_failed:evaluate_candidates")
        candidate_evaluations = []

    # ── 7. update replay pool (append-only projection; Task 06 rules) ──
    pool_updates = {"added": [], "retired": []}
    try:
        # Task 06 §5.8 admission (epoch boundary ONLY, never mid-epoch):
        # this epoch's ValidatedAttackRecords become replay cases, then the
        # pool is bounded and its snapshot rewritten. Duck-typed so pre-06
        # pools (append_case-only test stubs) keep working unchanged.
        admit = getattr(adversarial_replay_pool, "admit", None)
        if callable(admit):
            validated_records = sorted(
                (
                    rec for rec in records_by_id.values()
                    if rec.get("record_type") == "validated_attack"
                ),
                key=lambda r: str(r.get("record_id", "")),
            )
            for case in admit(validated_records, epoch_id) or ():
                case_id = (
                    case.get("case_id", "") if isinstance(case, dict)
                    else getattr(case, "case_id", "")
                )
                if case_id:
                    pool_updates["added"].append(str(case_id))
            evict = getattr(adversarial_replay_pool, "evict_to_cap", None)
            if callable(evict):
                evict()
            save = getattr(adversarial_replay_pool, "save_snapshot", None)
            if callable(save):
                save()
        upheld_case_refs = sorted(
            {
                str(item.get("ref", ""))
                for motion in motions
                if outcomes_by_motion.get(motion.record_id)
                in ("upheld", "partially_upheld")
                for item in (
                    bundles_by_id.get(motion.evidence_bundle_id).items
                    if bundles_by_id.get(motion.evidence_bundle_id)
                    else ()
                )
                if item.get("kind") == "validated_attack"
            }
        )
        append_case = getattr(adversarial_replay_pool, "append_case", None)
        if upheld_case_refs and not callable(append_case):
            degradations.append("replay_pool_update_skipped")
        elif callable(append_case):
            for ref in upheld_case_refs:
                append_case(
                    {"case_id": ref, "epoch_id": epoch_id, "source": "audit_epoch"}
                )
                pool_updates["added"].append(ref)
    except Exception:
        log.warning("governance step 7 (replay pool) failed", exc_info=True)
        degradations.append("step_failed:update_replay_pool")

    if budget.exhausted:
        degradations.append("llm_budget_exhausted")

    # ── 8. governance self-audit (kernel re-validation) ───────────────
    produced = (
        [("evidence_bundle", b.to_dict()) for _, b in sorted(
            bundles_by_target.items()
        )]
        + [("impeachment_motion", m.to_dict()) for m in motions]
        + [("governance_defense", d.to_dict()) for d in defenses]
        + [("impeachment_outcome", o.to_dict()) for o in outcomes]
    )
    try:
        self_audit = run_self_audit(
            kernel=kernel,
            produced_records=[payload for _, payload in produced],
            motions=motions,
            outcomes_by_motion=outcomes_by_motion,
            defenses=defenses,
            findings=findings,
            checked_components=[auditor_id, clerk_id, defender_id, judge_id],
            degradations=degradations,
        )
    except Exception:
        log.warning("governance step 8 (self-audit) failed", exc_info=True)
        degradations.append("self_audit_degraded")
        self_audit = {
            "checked_components": [],
            "kernel_violations_found": 0,
            "findings": list(findings),
            "escalations": [],
            "stats": {},
        }

    # ── 9. produce the report (only this step may raise) ──────────────
    recommendations = _build_recommendations(
        motions, outcomes, candidate_evaluations
    )
    report = GovernanceReport(
        record_id=f"govreport_{epoch_id}" if epoch_id else "govreport_unknown",
        epoch_id=epoch_id,
        governance_level=default_level,
        degraded=bool(degradations),
        degradation_reasons=list(degradations),
        reliability=reliability,
        observations=observation_ids,
        evidence_bundles=sorted(bundles_by_id),
        impeachment_motions=[m.record_id for m in motions],
        defenses=[d.record_id for d in defenses],
        adjudications=adjudications,
        candidate_evaluations=candidate_evaluations,
        replay_pool_updates=pool_updates,
        self_audit=self_audit,
        recommendations=recommendations,
        bond_accounting=ledger.to_dict(),
        budget_usage={
            "llm_calls": budget.used,
            "replay_cases_used": replay_cases_used,
            "anchor_cases_used": anchor_cases_used,
        },
    )
    return report, produced


def _build_recommendations(
    motions: list, outcomes: list, candidate_evaluations: list
) -> list:
    """Deterministic advisory recommendations (§6.1 closed action set).

    Applying them is Task 09's RegistryTransitionEngine; unknown actions must
    be droppable there the way ``_parse_decision`` drops unknown lineage
    actions.
    """
    out = []
    outcome_by_motion = {o.motion_id: o for o in outcomes}
    for motion in motions:
        outcome = outcome_by_motion.get(motion.record_id)
        if outcome is None:
            continue
        if outcome.outcome == "upheld":
            action, confidence = motion.requested_action, 0.9
        elif outcome.outcome == "partially_upheld":
            action, confidence = "warn", 0.6
        elif outcome.outcome == "dismissed" and (
            outcome.replay_result_ref or outcome.anchor_result_ref
        ):
            # EXONERATION ON THE MERITS. A dismissed motion used to emit
            # nothing at all, so the `no_action` signal T18
            # (`quarantine -> probationary_active`) consumes was never produced
            # by anything: a component that was accused, defended itself and WON
            # stayed quarantined forever and the exoneration edge could not fire.
            #
            # GATED ON EVIDENCE on purpose. A dismissal with no replay/anchor
            # result is the no-judge deterministic FALLBACK (step 5 renders no
            # judge when `llm is None`), not an acquittal — treating that as
            # exoneration would let every LLM-less run clear every accused
            # component, which is a fabricated exoneration. Those refs are set
            # exactly when the corresponding board actually scored.
            action, confidence = "no_action", 0.9
        else:
            continue          # inconclusive: no signal either way
        out.append(
            {
                "target_component_id": motion.target_component_id,
                "action": action,
                "basis_refs": [motion.record_id, outcome.record_id],
                "confidence": confidence,
            }
        )
    for i, ev in enumerate(candidate_evaluations):
        if ev.get("verdict") == "pass":
            out.append(
                {
                    "target_prompt_id": ev.get("prompt_id", ""),
                    "action": "promote_candidate",
                    "basis_refs": [f"candidate_evaluations[{i}]"],
                    "confidence": 0.8,
                }
            )
    return out
