"""AdversarialRound — the in-run attack→defense→adjudication loop (§5.3).

One coordinator per RQGMRuntime, invoked once per completed node by the
``_run_loop`` step-5 hook (after evaluation + the sterile gate, before
``write_node_report``). Loop invariant I-2 (failure isolation): every stage
is best-effort — the coordinator NEVER raises into the run loop.

Ordering + idempotency (§5.3): the per-node ``rqgm_adversarial_round``
marker is appended first (at-most-once, resume-safe), then raw attacks are
logged BEFORE defense/adjudication, so a crash mid-round leaves a
consistent, replayable record trail. Every record also lands in Task 02's
``rqgm_audit.jsonl`` through the ImmutableAuditLog envelope, which is what
Task 05's epoch audit scans for validated attacks.
"""

from __future__ import annotations

import logging

from ari.rqgm.adversarial.engine import (
    AdversaryEngine,
    ArtifactJudge,
    Defender,
    UtilityPenaltyPolicy,
    _cfg,
    _seq_alloc,
    apply_utility_penalty,
    build_artifact_bundle,
    novelty_signal,
    should_attack,
)
from ari.rqgm.adversarial.pool import AdversarialCaseLog
from ari.rqgm.adversarial.records import (
    RAW_ATTACK_RECORD_TYPE,
    UTILITY_RECORD_TYPE,
    make_validated_attack_record,
)

log = logging.getLogger(__name__)

#: Deterministic v1 expected-behavior template per case (§6 example shape).
_EXPECTED_BEHAVIOR = {
    "reviewer": "flag the validated defect class in review",
    "generator": "avoid reproducing the validated defect class",
    "judge": "mark recurrences of this attack as valid or partially valid",
}

#: ``case_type -> expected-behavior map`` for case types that need
#: role-specific replay expectations (docs/plans/ari_rqgm_paper/05 §5.2).
#: The seven exploration types use the module-level generic generator
#: expectation; the paper case supplies separate reviewer/writer behavior.
_EXPECTED_BEHAVIOR_BY_TYPE: dict[str, dict[str, str]] = {
    "paper_self_preference": {
        "paper_reviewer": "reject AI-authored drafts whose accepted quality "
                          "exceeds the human-anchor-supported bar",
        "paper_writer": "produce drafts whose claims are anchor-supported",
    },
}

#: ``case_type -> the implicated ROLE names``, in priority order. The round
#: emits ONE validated record per resolvable role
#: (:meth:`AdversarialRound._resolve_bindings`), with the per-node
#: ``paper_writer`` gate in :meth:`AdversarialRound._roles_for_node`. A closed,
#: design-time table: the ordering is a constant, so the binding needs no
#: sort, no wall clock, no registry iteration order and no LLM (P2).
#:
#: The seven exploration types implicate the registered ``generator`` only
#: when the attacked node carries a matching epoch-frozen
#: ``producer_component_id``. The runtime stamps that provenance before the
#: adversarial round. A legacy, ambiguous, or mismatched node remains
#: targetless: no semantic guess is converted into a sanction.
#:
#: The paper set adds its one row (docs/plans/ari_rqgm_paper/05 §5.4): a
#: ``paper_self_preference`` case implicates BOTH the ``paper_reviewer`` role
#: (which ACCEPTED the draft) AND the ``paper_writer`` role (which PRODUCED it)
#: — the over-accepted-AND-unfaithful draft has TWO culpable components (§5.1,
#: revised 2026-07-16). Both — unlike the seven's ``generator`` — HAVE a
#: registered incumbent (``paper_reviewer_v1`` / ``paper_writer_v1`` under
#: PAPER_RQGM_ARCHIVE), so the Task-15 resolution binds ``target_component_id``
#: and the validated-attack -> impeachment chain fires in production for each.
#: The round emits ONE validated attack per RESOLVABLE role
#: (:meth:`AdversarialRound._resolve_bindings`); the ``paper_writer`` binding is
#: gated per-node on the draft's Layer-0 claim-gate faithfulness
#: (``_paper_writer_unfaithful``), so a FAITHFUL over-accepted draft binds the
#: reviewer ONLY (the writer's sanction is causal in the writer's own drafts,
#: never the reviewer's leniency). Both paper roles resolve to ``""`` off the
#: paper phase (no paper_* in the frozen active map).
_AFFECTED_ROLES_BY_TYPE: dict[str, tuple[str, ...]] = {
    "overclaim": ("generator",),
    "metric_gaming": ("generator",),
    "prior_art": ("generator",),
    "reproducibility": ("generator",),
    "evidence_gap": ("generator",),
    "cost_explosion": ("generator",),
    "prompt_injection": ("generator",),
    "paper_self_preference": ("paper_reviewer", "paper_writer"),
}


class AdversarialRound:
    """Constructs the three actors + policy + case log for one checkpoint.

    *cfg* is the ``rqgm.adversarial`` slice (typed model or dict); *llm* the
    injectable governance-phase seam (``None`` → deterministic no-attack
    floor); *epoch_state* a zero-arg callable or object yielding the frozen
    EpochState (epoch_id + envelope provenance).
    """

    def __init__(
        self,
        cfg,
        *,
        llm=None,
        loader=None,
        checkpoint_dir=None,
        epoch_state=None,
        audit_writer=None,
        budget_manager=None,
        governance_cfg=None,
    ) -> None:
        self.cfg = cfg
        self.checkpoint_dir = checkpoint_dir
        self._epoch_state = epoch_state
        # RQGM Task 12 §5.4: optional read-side budget gates for the
        # defender/judge stages (adversary calls stay capped inside the
        # engine). ``None`` == ungated (status-quo Task 06 behavior).
        self._budget_manager = budget_manager
        self._governance_cfg = governance_cfg
        self.case_log = AdversarialCaseLog(checkpoint_dir)
        if audit_writer is None and checkpoint_dir is not None:
            from ari.rqgm.store import ImmutableAuditLog

            audit_writer = ImmutableAuditLog(checkpoint_dir)
        self.audit_writer = audit_writer
        # Id sequences continue across resume: count existing JSONL lines.
        atk_base = self.case_log.count_records(RAW_ATTACK_RECORD_TYPE)
        self._utility_seq = self.case_log.count_records(UTILITY_RECORD_TYPE)
        self._validated_alloc = _seq_alloc(
            "vat", self.case_log.count_records("validated_attack")
        )
        self.engine = AdversaryEngine(
            llm,
            loader,
            cfg,
            epoch_state,
            checkpoint_dir,
            next_attack_id=_seq_alloc("atk", atk_base),
            # Resume seed for the per-epoch call cap (§5.5): raw-attack lines
            # keyed by epoch_id are the durable lower bound on calls already
            # spent, so a mid-epoch restart cannot restart the budget at 0.
            calls_by_epoch=self.case_log.count_records_by_epoch(
                RAW_ATTACK_RECORD_TYPE
            ),
            active_components=self._active_components,
        )
        self.defender = Defender(
            llm, loader, checkpoint_dir,
            next_defense_id=_seq_alloc(
                "def", self.case_log.count_records("defender_response")
            ),
            active_components=self._active_components,
        )
        self.judge = ArtifactJudge(
            llm, loader, checkpoint_dir,
            next_judgment_id=_seq_alloc(
                "jdg", self.case_log.count_records("judgment_record")
            ),
            active_components=self._active_components,
        )
        self.policy = UtilityPenaltyPolicy.from_config(cfg)

    @property
    def epoch_id(self) -> str:
        state = self._epoch_state
        state = state() if callable(state) else state
        if state is None:
            return ""
        if isinstance(state, dict):
            return str(state.get("epoch_id", ""))
        return str(getattr(state, "epoch_id", "") or "")

    def _epoch_utility_policy(self) -> dict:
        """The frozen epoch's utility policy (Task 02 ``EpochState``), or
        ``{}`` while no epoch is open (plan 14 §5.8 delta 1).

        Same ``_epoch_state`` handle ``epoch_id`` already resolves — the
        record's ``prompt_hash`` must name the EPOCH policy, not the penalty
        policy, or a ``utility_policy`` retirement matches no record and the
        kernel's CK-EPO-001 fires on every UtilityRecord.
        """
        state = self._epoch_state
        state = state() if callable(state) else state
        if state is None:
            return {}
        if isinstance(state, dict):
            return dict(state.get("utility_policy") or {})
        return dict(getattr(state, "utility_policy", None) or {})

    def _active_components(self) -> dict:
        """The frozen epoch's ``role -> component_id`` map (Task 02
        EpochState) for the actors' registry-resolved record ids; ``{}``
        while no epoch is open (the ad-hoc fallback ids then apply)."""
        state = self._epoch_state
        state = state() if callable(state) else state
        if state is None:
            return {}
        if isinstance(state, dict):
            return dict(state.get("active_components") or {})
        return dict(getattr(state, "active_components", None) or {})

    def _active_prompt_hashes(self) -> dict:
        """The epoch-frozen ``role -> prompt hash`` map."""
        state = self._epoch_state
        state = state() if callable(state) else state
        if state is None:
            return {}
        if isinstance(state, dict):
            return dict(state.get("active_prompt_hashes") or {})
        return dict(getattr(state, "active_prompt_hashes", None) or {})

    def _expected_behavior(self, case_type: str) -> dict:
        """Case-typed expected-behavior map (docs/plans/ari_rqgm_paper/05
        §5.2), falling back to the module-level generic
        :data:`_EXPECTED_BEHAVIOR` for the seven exploration types (whose
        records thereby stay byte-identical). The keys become the record's
        ``affected_roles`` in ``build_failure_summary``."""
        return dict(_EXPECTED_BEHAVIOR_BY_TYPE.get(case_type, _EXPECTED_BEHAVIOR))

    @staticmethod
    def _roles_for_node(roles, node) -> tuple[str, ...]:
        """Per-node filter of the implicated roles (§5.1, revised 2026-07-16).

        ``paper_writer`` is a culpable component ONLY for a draft the Layer-0
        claim gate confirms UNFAITHFUL — the node carries
        ``_paper_writer_unfaithful`` when the paper runtime scored the active
        writer's draft below the faithfulness bar. A faithful (or unscored)
        draft binds the reviewer ONLY, so the writer's sanction is causal in the
        writer's own drafts, never the reviewer's leniency. Every node WITHOUT
        the flag (all exploration nodes, reviewer-only paper nodes) is unchanged
        — the filter only ever DROPS ``paper_writer``, never adds a role."""
        if "paper_writer" not in (roles or ()):
            return tuple(roles or ())
        metrics = getattr(node, "metrics", None) or {}
        if bool(metrics.get("_paper_writer_unfaithful")):
            return tuple(roles)
        return tuple(r for r in roles if r != "paper_writer")

    def _resolve_bindings(self, roles, judgment, node=None) -> list[tuple[str, str]]:
        """``[(role, component_id)]`` for every implicated role that resolves to
        a frozen-active incumbent OTHER than the judgment's own author.

        One entry per RESOLVABLE role — the round emits one validated attack per
        entry (the over-accepted-AND-unfaithful draft implicates BOTH the
        reviewer and the writer, §5.1). A role that resolves to ``""`` (off the
        paper phase, or an unfiltered writer with no incumbent) contributes no
        entry, so ambiguous or legacy exploration yields ``[]`` and the caller
        emits exactly one targetless record. Role separation (a record may not
        bind its own
        adjudicator, kernel check 3) is pre-filtered here, mirroring the
        single-target path: the binding is DROPPED (the finding survives with no
        accountable component), never raised."""
        out: list[tuple[str, str]] = []
        try:
            active = self._active_components() or {}
            active_prompts = self._active_prompt_hashes() or {}
        except Exception:
            log.warning("active-component target lookup failed (fail-open)",
                        exc_info=True)
            return out
        for role in roles or ():
            cid = str(active.get(str(role), "") or "")
            if not cid:
                continue
            if str(role) == "generator":
                producer = str(
                    getattr(node, "producer_component_id", "") or ""
                )
                producer_epoch = str(
                    getattr(node, "producer_epoch_id", "") or ""
                )
                producer_prompt = str(
                    getattr(node, "producer_prompt_hash", "") or ""
                )
                frozen_prompt = str(active_prompts.get(str(role), "") or "")
                if (
                    producer != cid
                    or not producer_epoch
                    or producer_epoch != self.epoch_id
                    or not producer_prompt
                    or producer_prompt != frozen_prompt
                ):
                    # No explicit same-epoch provenance means no blame. This
                    # prevents a successor from inheriting an old artifact's
                    # defect and keeps legacy checkpoints targetless.
                    continue
            if cid == judgment.component_id:
                log.warning(
                    "validated attack would bind its own adjudicator %r for "
                    "role %r; binding dropped (role separation).",
                    cid, role,
                )
                continue
            out.append((str(role), cid))
        return out

    def run(
        self,
        node,
        *,
        frontier_scores=(),
        parent_score=None,
        paper_candidate=False,
        remaining_node_budget: int = -1,
    ) -> dict | None:
        """Run at most one adversarial round for *node*; never raises.

        Returns a summary dict (test/observability surface) or ``None`` when
        the round did not run (disabled, duplicate, or not triggered).
        """
        try:
            return self._run(
                node,
                frontier_scores=frontier_scores,
                parent_score=parent_score,
                paper_candidate=paper_candidate,
                remaining_node_budget=remaining_node_budget,
            )
        except Exception:
            log.warning("adversarial round failed (fail-open)", exc_info=True)
            return None

    def _run(self, node, *, frontier_scores, parent_score, paper_candidate,
             remaining_node_budget: int = -1):
        if not _cfg(self.cfg, "enabled", True):
            return None
        node_id = str(getattr(node, "id", "") or "")
        if not node_id:
            return None
        _round_kind = "paper_candidate" if paper_candidate else "exploration"
        if self.case_log.has_round_marker(node_id, kind=_round_kind):
            return None  # §5.3 no-re-runs: at most one round per node
        bundle = build_artifact_bundle(
            node, self.checkpoint_dir,
            remaining_node_budget=remaining_node_budget,
        )
        pre_signal = any(
            bool(spec.pre_signal(bundle))
            for spec in _iter_specs(self.cfg)
        )
        triggered = should_attack(
            node_id=node_id,
            epoch_id=self.epoch_id,
            score=bundle.score,
            parent_score=parent_score,
            frontier_scores=frontier_scores,
            novelty=novelty_signal(bundle.eval_summary + bundle.proposal_text),
            pre_signal=pre_signal,
            paper_candidate=paper_candidate,
            top_k=_cfg(self.cfg, "full_governance_only_on_top_k", 3),
            jump_threshold=_cfg(self.cfg, "jump_threshold", 0.25),
            sample_mod=_cfg(self.cfg, "sample_mod", 5),
        )
        if not triggered:
            return None
        # Marker FIRST: at-most-once even across a mid-round crash + resume.
        self.case_log.append_round_marker(
            node_id, self.epoch_id, kind=_round_kind,
        )
        raw_attacks = self.engine.attack(bundle)
        self._log_all(raw_attacks)  # logged BEFORE any effect (§5.3)
        self._budget_consume("adversary_call", len(raw_attacks))
        if not raw_attacks:
            return {"node_id": node_id, "attacks": 0, "validated": 0,
                    "penalty": 0.0}
        # RQGM Task 12 §5.4 decision-point gates: a denied defender means
        # the attacks lapse as observations; a denied judge means no
        # validated records (raw attacks never touch scores — invariant 8).
        defenses = []
        defender_gated = not self._budget_allows("defender_call", node_id)
        if not defender_gated:
            defenses = self.defender.respond(raw_attacks, bundle)
            self._log_all(defenses)
            self._budget_consume("defender_call", len(defenses) or 1)
        judgments = []
        judge_skip = defender_gated and self._judge_on_disputed_only()
        if not judge_skip and self._budget_allows("judge_call", node_id):
            judgments = self.judge.adjudicate(raw_attacks, defenses, bundle)
            self._log_all(judgments)
            self._budget_consume("judge_call", len(judgments) or 1)
        attacks_by_id = {a.record_id: a for a in raw_attacks}
        validated = []
        for judgment in judgments:
            if judgment.verdict not in ("valid", "partially_valid"):
                continue
            attack = attacks_by_id.get(judgment.raw_attack_id)
            if attack is None:
                continue
            # The accountability binding is minted HERE, at construction —
            # never at the _log_all mirror: the JSONL truth and its audit-log
            # twin receive identical bytes, and AdversarialCaseLog (which reads
            # the record, not the payload) can never see a record that lacks its
            # twin's binding.
            #
            # The over-accepted-AND-unfaithful draft implicates TWO components
            # (§5.1, revised 2026-07-16): the reviewer that ACCEPTED it and the
            # writer that PRODUCED it. The round emits ONE validated attack per
            # RESOLVABLE role — the writer binding gated per-node on the draft's
            # Layer-0 claim-gate faithfulness (``_roles_for_node``). Role
            # separation (kernel check 3) is pre-filtered in ``_resolve_bindings``
            # so ``make_validated_attack_record``'s refusal stays a belt-and-
            # braces guard that never raises from this per-item-isolation-less
            # loop (``run``'s blanket handler would else swallow the node's whole
            # penalty).
            roles = self._roles_for_node(
                _AFFECTED_ROLES_BY_TYPE.get(attack.adversary_type, ()), node
            )
            expected = self._expected_behavior(attack.adversary_type)
            bindings = self._resolve_bindings(roles, judgment, node=node)
            if bindings:
                # One accountable record per resolvable role; each names the
                # single role it targets in ``affected_components`` (the reviewer
                # record stays byte-identical to the pre-writer single-role one).
                for role, target in bindings:
                    validated.append(
                        make_validated_attack_record(
                            judgment, attack,
                            record_id=self._validated_alloc(),
                            expected_behavior=expected,
                            affected_components=(role,),
                            target_component_id=target,
                        )
                    )
            else:
                # No resolvable role (every exploration record; or a paper record
                # whose only role resolves to its own adjudicator): exactly ONE
                # targetless record, byte-identical to a pre-binding one.
                validated.append(
                    make_validated_attack_record(
                        judgment, attack,
                        record_id=self._validated_alloc(),
                        expected_behavior=expected,
                        affected_components=roles,
                        target_component_id="",
                    )
                )
        self._log_all(validated)
        utility = apply_utility_penalty(
            node,
            validated,
            self.policy,
            epoch_id=self.epoch_id,
            next_utility_seq=self._utility_seq,
            epoch_utility_policy=self._epoch_utility_policy(),
        )
        penalty = 0.0
        if utility is not None:
            self._utility_seq += 1
            self._log_all([utility])
            penalty = utility.penalty
        return {
            "node_id": node_id,
            "attacks": len(raw_attacks),
            "defenses": len(defenses),
            "judgments": len(judgments),
            "validated": len(validated),
            "penalty": penalty,
        }

    def _judge_on_disputed_only(self) -> bool:
        """``rqgm.governance.judge_on_disputed_only`` (plan 12 §5.2): with
        a budget-skipped defender the attack is uncontested — it lapses as
        an observation instead of reaching the judge."""
        gc = self._governance_cfg
        if isinstance(gc, dict):
            return bool(gc.get("judge_on_disputed_only", True))
        return bool(getattr(gc, "judge_on_disputed_only", True))

    def _budget_allows(self, kind: str, node_id: str) -> bool:
        """Consult the optional Task 12 gate (fail-open, never raises)."""
        if self._budget_manager is None:
            return True
        try:
            from ari.rqgm.budget import BudgetedAction

            return self._budget_manager.gate(
                BudgetedAction(kind), node_id=node_id
            ).allowed
        except Exception:
            log.warning("budget gate failed (fail-open)", exc_info=True)
            return True

    def _budget_consume(self, kind: str, count: int) -> None:
        if self._budget_manager is None or count <= 0:
            return
        try:
            from ari.rqgm.budget import BudgetedAction

            self._budget_manager.consume(BudgetedAction(kind), count=count)
        except Exception:
            log.warning("budget consume failed", exc_info=True)

    def _log_all(self, records) -> None:
        """JSONL truth + Task 02 audit-log envelope, in §5.3 order."""
        self.case_log.append_all(records)
        if self.audit_writer is None:
            return
        for rec in records or ():
            payload = rec.to_dict() if hasattr(rec, "to_dict") else dict(rec)
            try:
                self.audit_writer.append(
                    str(payload.get("record_type", "adversarial_record")),
                    payload,
                )
            except Exception:
                log.warning("adversarial audit append failed", exc_info=True)


def _iter_specs(cfg):
    from ari.rqgm.adversarial.engine import ADVERSARY_SPECS

    for t in _cfg(cfg, "types", list(ADVERSARY_SPECS)):
        spec = ADVERSARY_SPECS.get(t)
        if spec is not None:
            yield spec
