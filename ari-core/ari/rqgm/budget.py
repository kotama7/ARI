"""Cost control: governance levels + per-epoch call budgets (RQGM Task 12).

Read-side budget enforcement over the passive ``ari.cost_tracker``
(plan ``docs/plans/ari_rqgm/12`` §5.1-§5.4, §7). Three concerns:

* **Governance level ladder** (§5.1/§5.2) — the pure, deterministic
  ``assign_level`` trigger function (L0 fixed … L3 adjudicated). Sterile
  nodes never exceed L0; raw adversary attacks never touch BFTS scores at
  any level (invariant 8) — the ladder only decides which *governance*
  actors may spend LLM calls on a node.
* **BudgetedAction / BudgetVerdict / GovernanceBudgetManager** (§5.4) —
  decision-point gating (``allow | degrade | skip``), never mid-call
  interruption and never an exception into the run loop. Per-action caps
  are read from their single schema homes (``rqgm.adversarial`` — Task 06;
  ``rqgm.governance`` / ``rqgm.shadow`` / ``rqgm.replay`` /
  ``rqgm.prompt_evolution`` / ``rqgm.budgets``;
  ``proposal_router.generators.virsci`` — Task 03). The L0 fixed layer is
  deliberately NOT budgetable — the constitutional floor always runs.
* **Deterministic shadow sampling** (§5.6) — the hash rule
  ``sha256(f"{run_id}:{epoch_id}:{node_id}:shadow") % 10_000 <
  sample_rate * 10_000``; no RNG state, reproducible from the checkpoint.

Persistence (resume-safety): consumption and level assignments are appended
to the Task 02 ImmutableAuditLog (``budget_consumed`` / ``budget_degraded``
/ ``governance_level`` lines) and counters are rebuilt from it at
construction — the same derive-from-durable-records discipline the
ProposalStore and AdversaryEngine budgets already use (in-memory-only
counters would silently double budgets on ``ari resume``). Deterministic:
no LLM calls, no randomness, no wall-clock in any decision (P2).
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)

# ── audit-line vocabulary (appended to rqgm_audit.jsonl) ────────────────────

BUDGET_CONSUMED_EVENT = "budget_consumed"
BUDGET_DEGRADED_EVENT = "budget_degraded"
GOVERNANCE_LEVEL_EVENT = "governance_level"

# ── budgeted-action kinds (closed v1 set, plan 12 §5.3 counters) ────────────

ADVERSARY_CALL = "adversary_call"
DEFENDER_CALL = "defender_call"
JUDGE_CALL = "judge_call"
SHADOW_CALL = "shadow_call"
REPLAY_CASE = "replay_case"
VIRSCI_CALL = "virsci_call"
PROMPT_CANDIDATE = "prompt_candidate"
CLEAN_ROOM_GENERATION = "clean_room_generation"
GOVERNANCE_LLM_CALL = "governance_llm_call"
# Paper-archive Task 06 (docs/plans/ari_rqgm_paper/06 §5.3/§6.2): the ONE
# additive action kind. Anchor-agreement utility scoring for a paper_reviewer
# candidate is O(sample_size) per candidate; capped at rqgm.paper.anchor.
# sample_size, returning 0 when anchor scoring is disabled (the
# SHADOW_CALL/VIRSCI_CALL disabled-returns-0 pattern). Every other paper actor
# reuses an EXISTING kind (adversary -> ADVERSARY_CALL, co-evolution ->
# PROMPT_CANDIDATE) or is bounded structurally by max_expansions (the reviewer
# score, D4). No exploration budget decision changes.
PAPER_ANCHOR_SCORING = "paper_anchor_scoring"

ACTION_KINDS: tuple[str, ...] = (
    ADVERSARY_CALL,
    DEFENDER_CALL,
    JUDGE_CALL,
    SHADOW_CALL,
    REPLAY_CASE,
    VIRSCI_CALL,
    PROMPT_CANDIDATE,
    CLEAN_ROOM_GENERATION,
    GOVERNANCE_LLM_CALL,
    PAPER_ANCHOR_SCORING,
)

# ── governance level ladder (plan 12 §5.1) ──────────────────────────────────

LEVEL_FIXED = 0          # fixed verifier + cheap deterministic validation
LEVEL_REVIEWED = 1       # + reviewer
LEVEL_CONTESTED = 2      # + adversary/defender
LEVEL_ADJUDICATED = 3    # + judge + evidence bundle
MAX_LEVEL = LEVEL_ADJUDICATED


@dataclass(frozen=True)
class BudgetedAction:
    """One governance action submitted to :meth:`GovernanceBudgetManager.check`.

    *role* qualifies ``prompt_candidate`` (per-role caps);
    *retirement_pending* selects the higher ``max_cases_for_retirement``
    replay cap when a RetirementEvent is under consideration (§5.3).
    """

    kind: str
    role: str = ""
    retirement_pending: bool = False

    @property
    def counter_key(self) -> str:
        return f"{self.kind}:{self.role}" if self.role else self.kind


@dataclass(frozen=True)
class BudgetVerdict:
    """``allow`` — proceed; ``degrade`` — run the deterministic fallback /
    cap the effective level; ``skip`` — drop the single action. Never an
    exception (plan 12 §5.4 failure posture)."""

    decision: str  # "allow" | "degrade" | "skip"
    action: BudgetedAction
    remaining: int | None = None  # None == unlimited
    reason: str = ""

    @property
    def allowed(self) -> bool:
        return self.decision == "allow"


def _num(raw, default):
    try:
        return type(default)(raw)
    except (TypeError, ValueError):
        return default


def _get(obj, name, default=None):
    """Duck-typed config read (typed model, raw dict, or absent)."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


class GovernanceBudgetManager:
    """Read-side budget enforcement (plan 12 §5.4/§7).

    Never raises; never blocks the run loop. *cfg* is the resolved
    :class:`ari.config.ARIConfig` (duck-typed reads — raw dicts and stub
    configs work); *epoch_state* is an ``EpochState``-like object or a
    zero-arg callable returning one (the current epoch after boundary
    transactions); *cost_tracker* is the passive
    :class:`ari.cost_tracker.CostTracker` (or ``None``) consulted for the
    ``rqgm.budgets`` spend caps; *proposal_store* (object or callable) lets
    ``virsci_call`` counting share the ProposalRouter's single durable
    count source (``count_for_epoch``); *audit_log* is the Task 02
    append-only writer used for durable consumption/level lines.
    """

    def __init__(
        self,
        cfg,
        epoch_state=None,
        cost_tracker=None,
        *,
        checkpoint_dir=None,
        audit_log=None,
        proposal_store=None,
    ) -> None:
        self.cfg = cfg
        self._epoch_state = epoch_state
        self._cost_tracker = cost_tracker
        self._checkpoint_dir = checkpoint_dir
        if audit_log is None and checkpoint_dir is not None:
            try:
                from ari.rqgm.store import ImmutableAuditLog

                audit_log = ImmutableAuditLog(checkpoint_dir)
            except Exception:
                log.warning("budget audit writer construction failed",
                            exc_info=True)
        self._audit_log = audit_log
        self._proposal_store = proposal_store
        # (epoch_id, counter_key) -> consumed count; rebuilt from the audit
        # log so budgets survive `ari resume` (plan 12 §5.3 counter homes).
        self._counters: dict[tuple[str, str], int] = {}
        self._spend_usd: dict[str, float] = {}
        self._spend_tokens: dict[str, int] = {}
        self._restore()

    # ── construction-time restore (resume-safety, §8) ─────────────────

    def _restore(self) -> None:
        if self._checkpoint_dir is None:
            return
        try:
            from ari.rqgm.store import ImmutableAuditLog

            for line in ImmutableAuditLog.read(self._checkpoint_dir):
                if line.get("event_type") != BUDGET_CONSUMED_EVENT:
                    continue
                p = line.get("payload") or {}
                epoch_id = str(p.get("epoch_id", "") or "")
                kind = str(p.get("kind", "") or "")
                if not epoch_id or kind not in ACTION_KINDS:
                    continue
                key = (epoch_id, str(p.get("counter_key", kind) or kind))
                self._counters[key] = (
                    self._counters.get(key, 0) + max(0, _num(p.get("count", 1), 1))
                )
                self._spend_usd[epoch_id] = (
                    self._spend_usd.get(epoch_id, 0.0)
                    + max(0.0, _num(p.get("cost_usd", 0.0), 0.0))
                )
                self._spend_tokens[epoch_id] = (
                    self._spend_tokens.get(epoch_id, 0)
                    + max(0, _num(p.get("tokens", 0), 0))
                )
        except Exception:
            log.warning("budget counter restore failed (starting empty)",
                        exc_info=True)

    # ── config slices (single schema homes, §5.3) ─────────────────────

    def _rqgm(self):
        return _get(self.cfg, "rqgm")

    def _epoch(self):
        st = self._epoch_state
        return st() if callable(st) else st

    def _epoch_id(self) -> str:
        ep = self._epoch()
        if isinstance(ep, dict):
            return str(ep.get("epoch_id", "") or "")
        return str(getattr(ep, "epoch_id", "") or "")

    def _run_id(self) -> str:
        ep = self._epoch()
        if isinstance(ep, dict):
            return str(ep.get("run_id", "") or "")
        return str(getattr(ep, "run_id", "") or "")

    def _store(self):
        st = self._proposal_store
        return st() if callable(st) else st

    def _cap(self, action: BudgetedAction) -> int | None:
        """Per-action per-epoch cap; ``None`` == unlimited. Each knob has
        exactly one schema home (no ``rqgm.governance.*`` aliases for the
        Task 06 adversary knobs — plan 12 §5.3 note)."""
        r = self._rqgm()
        if action.kind == ADVERSARY_CALL:
            return _num(_get(_get(r, "adversarial"),
                             "max_adversary_calls_per_epoch", 24), 24)
        if action.kind == DEFENDER_CALL:
            return _num(_get(_get(r, "governance"),
                             "max_defender_calls_per_epoch", 12), 12)
        if action.kind == JUDGE_CALL:
            return _num(_get(_get(r, "governance"),
                             "max_judge_calls_per_epoch", 8), 8)
        if action.kind == SHADOW_CALL:
            shadow = _get(r, "shadow")
            if not bool(_get(shadow, "enabled", True)):
                return 0
            return _num(_get(shadow, "max_shadow_calls_per_epoch", 10), 10)
        if action.kind == REPLAY_CASE:
            replay = _get(r, "replay")
            if action.retirement_pending:
                return _num(_get(replay, "max_cases_for_retirement", 12), 12)
            return _num(_get(replay, "max_cases_per_epoch", 8), 8)
        if action.kind == VIRSCI_CALL:
            vcfg = _get(_get(_get(self.cfg, "proposal_router"), "generators"),
                        "virsci")
            if not bool(_get(vcfg, "enabled", False)):
                return 0  # zero-cost guarantee when disabled (§8)
            cap = _num(_get(vcfg, "max_calls_per_epoch", 2), 2)
            return cap if cap > 0 else None  # router semantics: <=0 unlimited
        if action.kind == PROMPT_CANDIDATE:
            return _num(_get(_get(r, "prompt_evolution"),
                             "max_candidates_per_role_per_epoch", 1), 1)
        if action.kind == CLEAN_ROOM_GENERATION:
            return _num(_get(_get(r, "prompt_evolution"),
                             "max_clean_room_generations_per_epoch", 1), 1)
        if action.kind == GOVERNANCE_LLM_CALL:
            return _num(_get(_get(r, "governance"),
                             "max_llm_calls_per_audit", 12), 12)
        if action.kind == PAPER_ANCHOR_SCORING:
            # Paper-archive Task 06 §6.2/D5: the reviewer candidate's
            # anchor-agreement utility is measured on `sample_size` held-out
            # papers, so cost is O(candidates x sample_size). Disabled anchor
            # returns 0 (the SHADOW_CALL/VIRSCI_CALL disabled-returns-0 rule).
            anchor = _get(_get(r, "paper"), "anchor")
            if not bool(_get(anchor, "enabled", True)):
                return 0
            return _num(_get(anchor, "sample_size", 8), 8)
        return None

    def _used(self, action: BudgetedAction, epoch_id: str) -> int:
        if action.kind == VIRSCI_CALL:
            # Single count source with the ProposalRouter's own enforcement
            # (dispatch heads in proposal_records.jsonl, resume-safe).
            store = self._store()
            if store is not None:
                try:
                    return int(store.count_for_epoch("virsci", epoch_id or None))
                except Exception:
                    log.warning("virsci store count failed", exc_info=True)
        return self._counters.get((epoch_id, action.counter_key), 0)

    def _prompt_candidates_total(self, epoch_id: str) -> int:
        return sum(
            count for (eid, key), count in self._counters.items()
            if eid == epoch_id and key.split(":", 1)[0] == PROMPT_CANDIDATE
        )

    def _on_exhausted(self) -> str:
        raw = str(_get(_get(self._rqgm(), "budgets"), "on_exhausted",
                       "degrade") or "degrade")
        return raw if raw in ("degrade", "skip") else "degrade"

    def _spend_exhausted(self, epoch_id: str) -> str:
        """The ``rqgm.budgets`` spend caps (0 == unlimited, attribution
        only). Spend is read from the passive CostTracker records filtered
        by ``epoch`` + ``phase="governance"`` (§5.4.2) when a tracker is
        available, else from this manager's own ``consume`` totals."""
        budgets = _get(self._rqgm(), "budgets")
        max_usd = max(0.0, _num(_get(budgets, "max_governance_cost_usd_per_epoch",
                                     0.0), 0.0))
        max_tokens = max(0, _num(_get(budgets, "max_governance_tokens_per_epoch",
                                      0), 0))
        if max_usd <= 0 and max_tokens <= 0:
            return ""
        spent_usd = self._spend_usd.get(epoch_id, 0.0)
        spent_tokens = self._spend_tokens.get(epoch_id, 0)
        tracker = self._cost_tracker
        if tracker is not None:
            try:
                records = [
                    r for r in list(getattr(tracker, "_records", []) or [])
                    if getattr(r, "phase", "") == "governance"
                    and str(getattr(r, "epoch", "") or "") == epoch_id
                ]
                if records:
                    spent_usd = sum(
                        float(getattr(r, "estimated_cost_usd", 0.0) or 0.0)
                        for r in records
                    )
                    spent_tokens = sum(
                        int(getattr(r, "total_tokens", 0) or 0) for r in records
                    )
            except Exception:
                log.warning("cost tracker spend read failed", exc_info=True)
        if max_usd > 0 and spent_usd >= max_usd:
            return f"governance cost {spent_usd:.6f} USD >= cap {max_usd:.6f}"
        if max_tokens > 0 and spent_tokens >= max_tokens:
            return f"governance tokens {spent_tokens} >= cap {max_tokens}"
        return ""

    # ── §7 API ────────────────────────────────────────────────────────

    def check(self, action: BudgetedAction) -> BudgetVerdict:
        """Decision-point verdict for one governance action (never raises).

        L0 fixed checks never call this — they are exempt by construction
        (§5.4.4); everything that does is degradable.
        """
        try:
            epoch_id = self._epoch_id()
            remaining: int | None = None
            reason = ""
            cap = self._cap(action)
            if cap is not None:
                remaining = max(0, cap - self._used(action, epoch_id))
                if remaining <= 0:
                    reason = f"{action.counter_key} cap {cap} exhausted"
            if not reason and action.kind == PROMPT_CANDIDATE:
                total_cap = _num(
                    _get(_get(self._rqgm(), "prompt_evolution"),
                         "max_total_candidates_per_epoch", 4), 4)
                if self._prompt_candidates_total(epoch_id) >= total_cap:
                    reason = (
                        f"prompt_candidate total cap {total_cap} exhausted"
                    )
            if not reason:
                reason = self._spend_exhausted(epoch_id)
            if not reason:
                return BudgetVerdict("allow", action, remaining=remaining)
            return BudgetVerdict(
                self._on_exhausted(), action,
                remaining=0 if remaining is None else remaining,
                reason=reason,
            )
        except Exception:
            log.warning("budget check failed (fail-open allow)", exc_info=True)
            return BudgetVerdict("allow", action, reason="check_failed")

    def consume(
        self,
        action: BudgetedAction,
        *,
        count: int = 1,
        cost_usd: float = 0.0,
        tokens: int = 0,
    ) -> None:
        """Book *count* uses of *action* (never raises, even past the cap —
        budgets are caps consulted by :meth:`check`, not assertions)."""
        try:
            epoch_id = self._epoch_id()
            key = (epoch_id, action.counter_key)
            self._counters[key] = self._counters.get(key, 0) + max(0, int(count))
            self._spend_usd[epoch_id] = (
                self._spend_usd.get(epoch_id, 0.0) + max(0.0, float(cost_usd))
            )
            self._spend_tokens[epoch_id] = (
                self._spend_tokens.get(epoch_id, 0) + max(0, int(tokens))
            )
            self._append_audit(BUDGET_CONSUMED_EVENT, {
                "epoch_id": epoch_id,
                "kind": action.kind,
                "counter_key": action.counter_key,
                "count": max(0, int(count)),
                "cost_usd": max(0.0, float(cost_usd)),
                "tokens": max(0, int(tokens)),
            })
        except Exception:
            log.warning("budget consume failed (counter unchanged)",
                        exc_info=True)

    def gate(self, action: BudgetedAction, *, node_id: str = "") -> BudgetVerdict:
        """:meth:`check` + audit-log the degrade/skip outcome (§5.4.3:
        both outcomes are audit-logged)."""
        verdict = self.check(action)
        if not verdict.allowed:
            self._append_audit(BUDGET_DEGRADED_EVENT, {
                "epoch_id": self._epoch_id(),
                "node_id": str(node_id or ""),
                "kind": action.kind,
                "counter_key": action.counter_key,
                "decision": verdict.decision,
                "reason": verdict.reason,
            })
        return verdict

    # ── level ladder (§5.1/§5.2; pure decision logic) ─────────────────

    def assign_level(
        self,
        node,
        frontier=(),
        epoch_state=None,
        **kwargs,
    ) -> int:
        """Pure §5.2 trigger evaluation → level int (0..3)."""
        level, _ = self.level_with_triggers(
            node, frontier, epoch_state, **kwargs
        )
        return level

    def level_with_triggers(
        self,
        node,
        frontier=(),
        epoch_state=None,
        *,
        parent_score=None,
        review_confidence=None,
        paper_candidate: bool = False,
        novelty_risks=(),
    ) -> tuple[int, list[str]]:
        """The §5.2 triggers, in fixed evaluation order (deterministic —
        computable from ``node.metrics`` / frontier state, no LLM).

        *frontier* accepts node objects (id tie-break applies) or bare
        scores (the run-loop hook passes ``frontier_scores`` floats).
        """
        del epoch_state  # reserved: level policy is epoch-independent in v1
        metrics = getattr(node, "metrics", None) or {}
        if not isinstance(metrics, dict):
            metrics = {}
        if metrics.get("_sterile") is True:
            return LEVEL_FIXED, ["sterile"]
        gov = _get(self._rqgm(), "governance")
        level = min(MAX_LEVEL,
                    max(0, _num(_get(gov, "default_level", 1), 1)))
        triggers: list[str] = []
        score = _num(metrics.get("_scientific_score", 0.0), 0.0)
        top_k = _num(_get(gov, "full_governance_only_on_top_k", 3), 3)
        if top_k > 0 and _in_top_k(node, frontier, top_k, score):
            level = LEVEL_ADJUDICATED
            triggers.append("top_k")
        if paper_candidate:
            level = LEVEL_ADJUDICATED
            triggers.append("paper_candidate")
        # Score-jump threshold: single schema home rqgm.adversarial (Task 06).
        jump = _num(_get(_get(self._rqgm(), "adversarial"),
                         "jump_threshold", 0.25), 0.25)
        if (
            parent_score is not None
            and score - _num(parent_score, 0.0) > jump
        ):
            level = max(level, LEVEL_CONTESTED)
            triggers.append("score_jump")
        axis = metrics.get("_axis_scores") or {}
        novelty_axis = axis.get("novelty") if isinstance(axis, dict) else None
        novelty_threshold = _num(_get(gov, "novelty_claim_threshold", 0.8), 0.8)
        if tuple(novelty_risks or ()) or (
            novelty_axis is not None
            and _num(novelty_axis, 0.0) >= novelty_threshold
        ):
            level = max(level, LEVEL_CONTESTED)
            triggers.append("novelty_claim")
        low_conf = _num(_get(gov, "low_confidence_threshold", 0.4), 0.4)
        if (
            review_confidence is not None
            and _num(review_confidence, 1.0) < low_conf
        ):
            # Disputed: L2→L3 escalation (§5.2); below L2 it raises the
            # node into the contested tier first.
            level = (
                LEVEL_ADJUDICATED if level >= LEVEL_CONTESTED
                else LEVEL_CONTESTED
            )
            triggers.append("low_confidence")
        return level, triggers

    def record_level(self, node_id: str, level: int, triggers) -> None:
        """Audit-log one level assignment (§5.2: deterministic, replayable)."""
        self._append_audit(GOVERNANCE_LEVEL_EVENT, {
            "epoch_id": self._epoch_id(),
            "node_id": str(node_id or ""),
            "level": int(level),
            "triggers": [str(t) for t in (triggers or ())],
        })

    # ── deterministic shadow sampling (§5.6) ──────────────────────────

    def shadow_sample(self, node_id: str) -> bool:
        """Pure hash rule; same ``(run_id, epoch_id, node_id)`` → same
        verdict across processes (P2 — a re-run samples the same nodes)."""
        shadow = _get(self._rqgm(), "shadow")
        if not bool(_get(shadow, "enabled", True)):
            return False
        rate = min(1.0, max(0.0, _num(_get(shadow, "sample_rate", 0.2), 0.2)))
        seed = f"{self._run_id()}:{self._epoch_id()}:{node_id}:shadow"
        bucket = int(
            hashlib.sha256(seed.encode("utf-8")).hexdigest(), 16
        ) % 10_000
        return bucket < int(rate * 10_000)

    def select_shadow_nodes(self, node_ids) -> list[str]:
        """Hash-sample then truncate to ``max_shadow_calls_per_epoch`` in
        node-id order (§5.6), net of shadow calls already consumed."""
        cap = self._cap(BudgetedAction(SHADOW_CALL))
        if cap is not None:
            cap = max(
                0, cap - self._used(BudgetedAction(SHADOW_CALL),
                                    self._epoch_id())
            )
        sampled = sorted(
            str(n) for n in (node_ids or ()) if self.shadow_sample(str(n))
        )
        return sampled if cap is None else sampled[:cap]

    # ── plumbing ──────────────────────────────────────────────────────

    def _append_audit(self, event_type: str, payload: dict) -> None:
        if self._audit_log is None:
            return
        try:
            self._audit_log.append(event_type, payload)
        except Exception:
            log.warning("budget audit append failed for %s", event_type,
                        exc_info=True)


def _in_top_k(node, frontier, k: int, score: float) -> bool:
    """Frontier top-K membership; node-object frontiers break ties by node
    id (lexicographic — §5.2), bare-score frontiers use the score threshold
    (parity with ``ari.rqgm.adversarial.engine.should_attack``)."""
    items = list(frontier or ())
    node_id = str(getattr(node, "id", "") or "")
    entries: list[tuple[float, str]] = []
    scores_only = True
    for item in items:
        item_id = str(getattr(item, "id", "") or "")
        if item_id:
            scores_only = False
            m = getattr(item, "metrics", None) or {}
            s = _num(m.get("_scientific_score", 0.0) or 0.0, 0.0) if (
                isinstance(m, dict)
            ) else 0.0
            entries.append((s, item_id))
        else:
            entries.append((_num(item, 0.0), ""))
    if not entries:
        return True  # empty frontier: fewer than k nodes exist
    if scores_only or not node_id:
        ranked = sorted((s for s, _ in entries), reverse=True)
        return len(ranked) < k or score >= ranked[k - 1]
    if node_id not in {i for _, i in entries}:
        entries.append((score, node_id))
    entries.sort(key=lambda e: (-e[0], e[1]))
    return node_id in {i for _, i in entries[:k]}
