"""RQGM runtime facade + governed SearchStrategy wrapper (Task 01 skeleton).

All RQGM construction funnels through :class:`RQGMRuntime`, and the facade is
imported lazily inside ``ari.core.build_runtime``'s ``ari_rqgm`` branch —
under ``simple_bfts`` no ``ari.rqgm`` module is imported at all (import-cost
and fault-isolation guarantee, mirroring the ``hpc_enabled`` skill-drop
precedent in ``build_runtime``).

Task-01 scope: the facade constructs nothing but itself and the state writer;
:class:`GovernedSearchStrategy` is pure delegation, so an ``ari_rqgm`` run
produces the same node lifecycle as ``simple_bfts``. Task 02 adds the epoch
state layer: :meth:`RQGMRuntime.ensure_epoch` is the single best-effort hook
``_run_loop`` calls (loop start + outer-loop head) to open ``epoch_000``,
restore state on resume, and fire the node-count epoch boundary. Later tasks
add members inside ``RQGMRuntime.__init__`` (ProposalRouter + optional
VirSciAdapter — Task 03, ConstitutionalKernel — Task 04,
GovernanceOrchestrator / TransitionEngine / FrontierRepair — Tasks 05/09/10)
and policy inside the wrapper methods.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from ari.rqgm.mode import EffectiveMode

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ari.config import ARIConfig
    from ari.memory.client import MemoryClient
    from ari.orchestrator.node import Node
    from ari.protocols import NodeExecutor, SearchStrategy

log = logging.getLogger(__name__)


class GovernedSearchStrategy:
    """Pure-delegation :class:`ari.protocols.search.SearchStrategy` wrapper.

    Implements all seven Protocol methods by forwarding to the wrapped
    strategy (Task 01 adds no policy). Carries the public ``rqgm`` attribute —
    the reserved discovery handle ``_run_loop`` reads once at loop start
    (``getattr(bfts, "rqgm", None)``). Detection is duck-typed attribute
    presence, never ``isinstance`` of this concrete class (contract-snapshot
    robustness convention).
    """

    def __init__(self, inner: "SearchStrategy", rqgm: "RQGMRuntime") -> None:
        self.inner = inner
        self.rqgm = rqgm

    def select_next_node(
        self, candidates: "list[Node]", experiment_goal: str, memory: "MemoryClient"
    ) -> "Node":
        return self.inner.select_next_node(candidates, experiment_goal, memory)

    def select_best_to_expand(
        self, frontier: "list[Node]", experiment_goal: str, memory: "MemoryClient"
    ) -> "Node":
        return self.inner.select_best_to_expand(frontier, experiment_goal, memory)

    def should_prune(self, node: "Node", *, current_total: int) -> bool:
        return self.inner.should_prune(node, current_total=current_total)

    def expand(self, node: "Node", *args, **kwargs) -> "list[Node]":
        """Delegate expansion; Task 03 adds the recording decorator.

        Before delegation, an ``idea_context`` kwarg is re-rendered from the
        active ProposalSummaryView (``render_summary_ctx``) when one exists —
        the ``ari_rqgm`` summary-only channel with the caller's ``idea.json``
        string as fallback. After delegation, each child direction is
        captured as a CheapGenerator ProposalRecord (observation only; zero
        behavior change to expansion). Both hooks are best-effort and no-ops
        while the router is absent (Task-01 pure-delegation parity).
        """
        try:
            if "idea_context" in kwargs:
                summary_ctx = self.rqgm.render_expand_context()
                if summary_ctx:
                    kwargs["idea_context"] = summary_ctx
        except Exception:
            log.warning("summary expand-context render failed; using the "
                        "caller's idea.json context", exc_info=True)
        children = self.inner.expand(node, *args, **kwargs)
        try:
            for child in list(children or []):
                self.rqgm.stamp_node_producer(child)
            if self.rqgm.router is not None:
                for child in list(children or []):
                    self.rqgm.record_expansion_proposal(node, child)
        except Exception:
            log.warning("expansion proposal recording failed", exc_info=True)
        return children

    def record_run(self, node: "Node") -> None:
        self.inner.record_run(node)

    def expansion_count(self, node_id: str) -> int:
        return self.inner.expansion_count(node_id)

    def diversity_bonus(self, node: "Node") -> float:
        return self.inner.diversity_bonus(node)


class RQGMRuntime:
    """Facade owning every RQGM component (construction sites: plan 01 §5.3).

    Constructed by ``build_runtime`` only when the effective mode is
    ``ari_rqgm``; the Task-01 version holds just the config and checkpoint
    handle. ``wrap_node_executor`` is identity — the NodeExecutor seam is
    reserved for Tasks 05/06.
    """

    # Paper-archive seam defaults (docs/plans/ari_rqgm_paper/03) as CLASS
    # attributes so an instance built via ``RQGMRuntime.__new__`` (test
    # harnesses that exercise a single method in isolation) still resolves
    # them to the exploration defaults without an __init__ run.
    _paper_phase = False
    _anchor_pool = None
    _paper_candidate_evaluator = None

    def __init__(
        self,
        cfg: "ARIConfig",
        checkpoint_dir: "str | Path | None" = None,
        *,
        llm=None,
        mcp=None,
        paper_phase: bool = False,
        anchor_pool=None,
        paper_candidate_evaluator=None,
    ) -> None:
        self.cfg = cfg
        # Paper-archive co-evolution seam (docs/plans/ari_rqgm_paper/03, /04).
        # ``paper_phase`` is set ONLY by ``PaperArchiveRuntime`` — an
        # exploration ``ari_rqgm`` boot never passes it (default False), so
        # its founding registration / incumbent rebuild / epoch sizing are
        # byte-identical. When True: the founding bootstrap ALSO registers the
        # paper_writer/paper_reviewer rows (paper-mode-gated), the mutator can
        # rebuild the paper incumbents, ``anchor_pool`` (a PaperAnchorPool)
        # feeds the audit's board/anchor scoring, and
        # ``paper_candidate_evaluator`` supplies the paper candidates'
        # full-spine evaluations merged into resolve_transition (the same
        # pattern the utility_policy criterion rides).
        self._paper_phase = bool(paper_phase)
        self._anchor_pool = anchor_pool
        self._paper_candidate_evaluator = paper_candidate_evaluator
        if self._paper_phase:
            # P0-P4 are evaluation presets over ordinary runtime switches.
            # Fail fast on a mislabeled experimental arm: silently running a
            # different mechanism set would invalidate the comparison.
            from ari.rqgm.evaluation.paper_ablation import config_violations

            violations = config_violations(cfg)
            if violations:
                raise ValueError(
                    "invalid RQGM paper-ablation posture: "
                    + "; ".join(violations)
                )
        self.checkpoint_dir: Path | None = (
            Path(checkpoint_dir) if checkpoint_dir is not None else None
        )
        # Injected collaborators for the ProposalRouter generators (Task 03):
        # llm is the BFTS-phase LLMClient; mcp the shared MCPClient. Both are
        # optional so unit tests can construct a bare runtime.
        self.llm = llm
        self.mcp = mcp
        # Task 02 epoch state layer — constructed lazily on the first
        # ensure_epoch() call so build_runtime stays write-free.
        self._store = None
        self._epoch_state = None
        self._last_node_count = 0
        # The live LLMEvaluator, bound by build_runtime AFTER construction (the
        # evaluator does not exist yet when the runtime is built). Used to make
        # the epoch's FROZEN utility_policy actually drive scoring — otherwise
        # the adopted policy was captured but inert (the objective never
        # co-evolved). None under any path that never binds it (tests).
        self._evaluator = None
        # Task 04 Layer-0 kernel — stateless, pure, cheap; constructed for
        # every ari_rqgm runtime (never under simple_bfts, where this class
        # itself is never built). Failure degrades to kernel=None (the
        # adapters below all tolerate its absence).
        self.governance_suspended = False
        self.kernel = None
        try:
            from ari.rqgm.kernel import ConstitutionalKernel

            self.kernel = ConstitutionalKernel(
                tolerances=self._kernel_tolerances(cfg)
            )
        except Exception:
            log.warning("ConstitutionalKernel construction failed",
                        exc_info=True)
        # Task 03 proposal layer — constructed lazily on first use so a bare
        # runtime (and build_runtime itself) stays write-free; the store only
        # touches disk on append/projection.
        self._proposal_store = None
        self._router = None
        # Task 05 governance facade — constructed lazily at the first epoch
        # boundary (never under simple_bfts, where this class is never built).
        self._governance = None
        # Task 09 RegistryTransitionEngine — the sole registry status writer,
        # constructed lazily at the first epoch boundary.
        self._transition_engine = None
        # Task 06 adversarial loop — coordinator + replay pool, constructed
        # lazily on first use and only when rqgm.adversarial.enabled.
        self._adversarial = None
        self._adversarial_pool = None
        # Task 08 clean-room coordinator — constructed lazily at the first
        # boundary that carries clean_room_requests.
        self._clean_room = None
        # Task 10 frontier repair — constructed lazily at the first committed
        # boundary that carries retirements. `expansion_halted` is the §5.6
        # drain-only degradation flag `_run_loop` reads after each tick.
        self._frontier_repair = None
        self.expansion_halted = False
        # Task 11 meta-evolution coordinator — constructed lazily at the
        # first epoch boundary (SPEC steps 12→13: after audit_epoch, before
        # resolve_transition).
        self._meta_evolution = None
        # Task 12 read-side budget layer — constructed lazily on first use
        # (counters restore from the audit log; never under simple_bfts,
        # where this class itself is never built).
        self._budget_manager = None

    @property
    def mode(self) -> EffectiveMode:
        """The effective mode this runtime was constructed for (fixed)."""
        return EffectiveMode.ARI_RQGM

    def _paper_ablation_posture(self):
        """Active P0-P4 posture, only inside an evaluation paper phase."""

        if not self._paper_phase:
            return None
        from ari.rqgm.evaluation.paper_ablation import posture_from_config

        return posture_from_config(getattr(self, "cfg", None))

    def stamp_node_producer(self, node, role: str = "generator") -> bool:
        """Stamp epoch-frozen producer provenance on one research node.

        The fields are write-once. Missing epoch/component provenance leaves
        the node unbound rather than consulting a later live registry. This
        is an application-level identity boundary, not an OS or
        cryptographic identity claim.
        """
        if str(getattr(node, "producer_component_id", "") or ""):
            return True
        st = self._epoch_state
        epoch = getattr(st, "epoch", None) if st is not None else None
        if epoch is None:
            return False
        active_components = dict(
            getattr(epoch, "active_components", None) or {}
        )
        component_id = str(active_components.get(str(role), "") or "")
        if not component_id:
            return False
        active_prompts = dict(
            getattr(epoch, "active_prompt_hashes", None) or {}
        )
        setattr(node, "producer_component_id", component_id)
        setattr(
            node, "producer_prompt_hash",
            str(active_prompts.get(str(role), "") or ""),
        )
        setattr(
            node, "producer_epoch_id",
            str(getattr(epoch, "epoch_id", "") or ""),
        )
        return True

    # ── Task 04: ConstitutionalKernel posture ─────────────────────────

    @staticmethod
    def _kernel_tolerances(cfg) -> dict:
        """Numeric tolerances from ``rqgm.kernel.*`` plus the Task 08
        contamination-screen knobs from ``rqgm.clean_room.*`` (duck-typed
        reads; the screen policy itself is kernel code)."""
        rqgm_cfg = getattr(cfg, "rqgm", None)
        kernel_cfg = getattr(rqgm_cfg, "kernel", None)
        try:
            tol = float(getattr(kernel_cfg, "float_tolerance", 1e-9))
        except (TypeError, ValueError):
            tol = 1e-9
        screen = getattr(
            getattr(rqgm_cfg, "clean_room", None), "contamination_screen",
            None,
        )
        try:
            shingle_k = int(getattr(screen, "shingle_k", 8))
        except (TypeError, ValueError):
            shingle_k = 8
        return {
            "float_tolerance": tol,
            "contamination_shingle_words": shingle_k,
            "contamination_fail_on_any_hit": bool(
                getattr(screen, "fail_on_any_hit", True)
            ),
        }

    @property
    def kernel_enforcement(self) -> str:
        """``rqgm.kernel.enforcement`` (plan 04 §6): ``standard`` applies
        the blocking matrix; ``audit_only`` downgrades everything to
        warn-and-log. Read at construction/boundaries, never hot-switched."""
        kernel_cfg = getattr(getattr(self.cfg, "rqgm", None), "kernel", None)
        value = str(getattr(kernel_cfg, "enforcement", "standard"))
        return value if value in ("standard", "audit_only") else "standard"

    def resume_integrity_check(self, checkpoint_dir) -> None:
        """The §5.6.6 resume integrity pass (best-effort, never raises).

        Verifies the restored audit log; blocking findings put the run into
        governance-suspended carry-over (active set frozen for Tasks 05/09;
        the flag is advisory until those tasks land) — never a refusal to
        resume.
        """
        if self.kernel is None:
            return
        try:
            from ari.rqgm.kernel import should_block
            from ari.rqgm.store import ImmutableAuditLog

            lines = ImmutableAuditLog.read(checkpoint_dir)
            if not lines:
                return
            report = self.kernel.validate_audit_log_integrity(lines)
            if should_block(report, self.kernel_enforcement):
                self.governance_suspended = True
                log.warning(
                    "resume integrity: audit-log findings %s — governance "
                    "suspended carry-over (state changes frozen; run "
                    "continues)", [v.code for v in report.violations],
                )
        except Exception:
            log.warning("resume integrity pass failed (fail-open)",
                        exc_info=True)

    @property
    def state(self):
        """The replayed ``ari.rqgm.store.RqgmRuntimeState`` (or ``None``)."""
        return self._epoch_state

    @property
    def current_epoch(self):
        """The frozen open :class:`ari.rqgm.state.EpochState` (or ``None``)."""
        st = self._epoch_state
        return st.epoch if st is not None else None

    def bind_evaluator(self, evaluator) -> None:
        """Register the live LLMEvaluator so the epoch's frozen utility_policy
        can drive scoring. build_runtime calls this AFTER the evaluator exists.
        Without it the adopted policy is captured but inert (the objective never
        actually co-evolves — the paper's central guarantee)."""
        self._evaluator = evaluator

    def _apply_epoch_policy_to_scoring(self, st) -> None:
        """Apply the epoch's FROZEN utility_policy to the live scoring targets
        so the objective evolves per-epoch (plan 14 §5.6 / RQGM paper claim A).

        The frontier reads ``cfg.bfts`` live, so updating cfg suffices there;
        the LLMEvaluator caches its composite/axis-weights at construction, so
        the bound instance is re-synced too. Applied ONCE at each epoch open, so
        the criterion stays frozen WITHIN the epoch and changes only at the next
        boundary. Only knobs present in the policy are applied; fail-open (this
        runs on the main loop — a hook must never kill the run)."""
        try:
            policy = dict(getattr(st, "utility_policy", None) or {})
            if not policy:
                return
            ev_cfg = getattr(self.cfg, "evaluator", None)
            bf_cfg = getattr(self.cfg, "bfts", None)
            # Frontier knobs (read live from cfg.bfts).
            for key in ("frontier_score", "depth_penalty_lambda", "ucb_c"):
                if key in policy and bf_cfg is not None and hasattr(bf_cfg, key):
                    setattr(bf_cfg, key, policy[key])
            # Evaluator knobs. A composite is applied to cfg AND the evaluator
            # only when it is a REGISTERED formula — never write an unknown
            # composite the evaluator can't resolve (leave both untouched).
            aw = policy.get("axis_weights") or None
            comp = policy.get("composite")
            _reg = None
            comp_valid = False
            if comp:
                try:
                    from ari.evaluator.llm_evaluator import _COMPOSITE_REGISTRY as _reg
                    comp_valid = comp in _reg
                except Exception:
                    comp_valid = False
            if ev_cfg is not None:
                if aw is not None and hasattr(ev_cfg, "axis_weights"):
                    setattr(ev_cfg, "axis_weights", dict(aw))
                if comp_valid and hasattr(ev_cfg, "composite"):
                    setattr(ev_cfg, "composite", comp)
            # Re-sync the LIVE evaluator instance (it cached these at ctor).
            ev = self._evaluator
            if ev is not None:
                if aw is not None and hasattr(ev, "_ctor_axis_weights"):
                    ev._ctor_axis_weights = dict(aw)
                if comp_valid and _reg is not None and hasattr(ev, "_composite_name"):
                    ev._composite_name = comp
                    ev._compose_fn = _reg.resolve(comp)
            log.info("RQGM: applied epoch %s utility_policy to scoring "
                     "(composite=%s frontier=%s)",
                     getattr(getattr(st, "epoch", None), "epoch_id", "?"),
                     comp, policy.get("frontier_score"))
        except Exception:
            log.warning("apply epoch utility_policy to scoring failed "
                        "(fail-open)", exc_info=True)

    # ── Task 02: epoch lifecycle hook ─────────────────────────────────

    def ensure_epoch(
        self,
        node_count: int,
        *,
        checkpoint_dir: "str | Path | None" = None,
        run_id: str = "",
        search_state: "dict | None" = None,
    ):
        """Idempotent best-effort epoch hook (plan 02 §5.6-§5.7).

        First call: replay-restore the checkpoint's RQGM state (resume) or
        open ``epoch_000`` fresh. Subsequent calls: fire the node-count
        epoch-boundary transaction once ``nodes_per_epoch`` new nodes exist
        (v1 trigger; richer trigger policy is Task 05's). Never raises into
        the run loop — a state-layer failure degrades to "epoch continues".
        Returns the currently open :class:`~ari.rqgm.state.EpochState` or
        ``None``.

        *search_state* (Task 10, plan 10 §5.2) is the run loop's live BFTS
        state dict (``frontier`` / ``pending`` / ``all_nodes`` lists plus a
        ``flush_tree`` callable) handed in at the outer-loop head so
        FrontierRepairEngine.repair can run inside the boundary window —
        main thread, no node in flight. ``None`` (any other caller) skips
        repair.
        """
        ckpt = (
            Path(checkpoint_dir)
            if checkpoint_dir is not None
            else self.checkpoint_dir
        )
        if ckpt is None:
            return None
        self._last_node_count = int(node_count)
        try:
            from ari.rqgm.store import RqgmStateStore

            if self._store is None:
                self._store = RqgmStateStore()
            if self._epoch_state is None or self._epoch_state.epoch is None:
                st = self._store.load_state(ckpt)
                if st is not None:
                    # Restored state == resume: §5.6.6 integrity pass
                    # (best-effort; degrades to carry-over, never refusal).
                    self.resume_integrity_check(ckpt)
                if st is None or st.epoch is None or st.epoch.status != "open":
                    # Founding registration (plan 07 §5.2 bootstrap, wired
                    # here): BEFORE ``epoch_000`` opens on a fresh RQGM
                    # checkpoint, the founding prompt/component set is
                    # registered through the Task 02 transaction seam, so
                    # the first freeze carries a non-empty active set.
                    # Write-once (persist_run_start discipline): any resume
                    # — an epoch or committed registrations already in the
                    # log — never re-registers.
                    st = self._register_founding(ckpt, st)
                    st = self._store.open_epoch(
                        ckpt, self.cfg,
                        node_count=node_count, run_id=run_id, prior=st,
                    )
                self._epoch_state = st
                self._stamp_cost_epoch()
                self._apply_epoch_policy_to_scoring(st)
            else:
                ep = self._epoch_state.epoch
                nodes_per_epoch = self._nodes_per_epoch()
                if (
                    nodes_per_epoch > 0
                    and node_count - ep.node_count_at_open >= nodes_per_epoch
                ):
                    # Task 05 (plan 05 §5.2): the closing epoch is audited
                    # BEFORE the boundary transaction so the GovernanceReport
                    # is available to Task 09's RegistryTransitionEngine.
                    # Best-effort: a failed audit never delays the boundary.
                    self._epoch_state = self._run_epoch_boundary(
                        ckpt, node_count=node_count,
                        run_id=run_id or ep.run_id,
                        search_state=search_state,
                    )
                    self._stamp_cost_epoch()
                    self._apply_epoch_policy_to_scoring(self._epoch_state)
        except Exception:
            log.warning(
                "RQGM epoch hook failed; epoch state unchanged", exc_info=True
            )
        return self.current_epoch

    #: transaction_id of the one-time founding registration transaction
    #: (precedes ``epoch_000``; not an epoch-to-epoch transition).
    FOUNDING_TRANSITION_ID = "transition_founding"

    def _register_founding(self, ckpt, prior):
        """One-time founding registration at run start (fresh RQGM checkpoint).

        Emits every ``prompt_registered`` / ``component_registered`` payload
        from the frozen founding tables (``ari.rqgm.prompt_spec``) through
        the Task 02 ``EpochTransaction`` seam (prepare..commit on
        ``rqgm_transitions.jsonl``), so replay reconstructs the registries
        identically on every resume. Deterministic: table-order payloads,
        bytes-derived hashes, no wall clock in any hashed field (P2).

        Write-once discipline: *prior* being a state with an epoch or with
        any committed registration means the founding transaction (or a
        legacy pre-founding run) already happened — never re-register.
        A crashed founding transaction (prepare without commit) is invisible
        to replay and is safely re-run. Best-effort: on failure the prior
        state is returned and the run continues with an empty registry.
        """
        if prior is not None and (
            prior.epoch is not None
            or prior.prompts.entries()
            or prior.components.entries()
        ):
            return prior
        try:
            from ari.rqgm.events import TransitionEvent
            from ari.rqgm.prompt_spec import founding_registration_events

            # Task 14 (plan 14 §5.3): the founding utility policy is
            # cfg-derived, so the bootstrap passes the resolved cfg and
            # writes the policy BODY before registering the entry that
            # references it (text is referenced by source, never inlined).
            self._write_founding_policy_body(ckpt)
            events = [
                TransitionEvent(event_type=event_type, payload=payload)
                for event_type, payload in founding_registration_events(
                    self.cfg, include_paper=self._paper_phase
                )
            ]
            state = self._store.apply_transition(
                ckpt, self.FOUNDING_TRANSITION_ID, events
            )
            return state if state is not None else prior
        except Exception:
            log.warning("founding registration failed; continuing with an "
                        "empty registry", exc_info=True)
            return prior

    def _write_founding_policy_body(self, ckpt) -> None:
        """Write the epoch-0 utility-policy body (plan 14 §5.3/§6.1).

        Write-once canonical JSON under ``{ckpt}/rqgm_prompts/``: the
        registry entry references the path, this file carries the bytes, and
        ``hash12`` of these bytes IS the entry's ``prompt_hash`` IS
        ``utility_policy_hash``. Idempotent by construction (identical bytes
        re-write to a no-op), so a re-run founding transaction is safe.

        Best-effort like the bootstrap around it: on failure the entry is
        still registered but its body will not resolve, and
        ``capture_utility_policy`` falls back to the cfg policy — which is
        byte-identical to what this body holds anyway.
        """
        try:
            from ari.rqgm.prompt_loader import write_evolved_policy_body
            from ari.rqgm.prompt_spec import founding_utility_policy_spec

            spec = founding_utility_policy_spec(self.cfg)
            from ari.rqgm.events import canonical_json
            from ari.rqgm.state import utility_policy_body

            write_evolved_policy_body(
                ckpt,
                spec.prompt_id,
                canonical_json(utility_policy_body(self.cfg)),
            )
        except Exception:
            log.warning(
                "founding utility-policy body write failed; the cfg policy "
                "(byte-identical) still governs epoch 0", exc_info=True
            )

    def _nodes_per_epoch(self) -> int:
        """``rqgm.epoch.nodes_per_epoch`` (typed model or raw dict), ≥ 0.

        Paper phase (docs/plans/ari_rqgm_paper/01 §5.7, landed deviation
        2026-07-17): ONE archive round = ONE paper epoch, config-independently.
        The paper driver calls ``ensure_epoch`` once per round head with the
        ROUND INDEX (0, 1, …) — the archive round counter, NOT the archive's
        live draft population — so a per-epoch size of 1 fires the boundary at
        each round edge regardless of how many drafts a round built. The trigger
        KIND stays the inherited node-count trigger; this only SIZES it for the
        paper phase. Tradeoff (doc 01 §5.7 residual): the hashed epoch payload
        records the round index as node_count_at_open, not the real draft count;
        no consumer reads it beyond the self-consistent trigger compare."""
        if self._paper_phase:
            return 1
        epoch_cfg = getattr(getattr(self.cfg, "rqgm", None), "epoch", None)
        if isinstance(epoch_cfg, dict):
            raw = epoch_cfg.get("nodes_per_epoch", 10)
        else:
            raw = getattr(epoch_cfg, "nodes_per_epoch", 10)
        try:
            return max(0, int(raw))
        except (TypeError, ValueError):
            return 10

    def _stamp_cost_epoch(self) -> None:
        """Per-epoch cost attribution (plan 02 §5.5): every litellm call in
        this process (skills included, via the metadata injector) now carries
        ``epoch=<epoch_id>`` and lands in ``CallRecord.epoch``."""
        ep = self.current_epoch
        if ep is None:
            return
        try:
            from ari import cost_tracker

            cost_tracker.set_default_metadata(epoch=ep.epoch_id)
        except Exception:
            log.debug("cost epoch stamping failed", exc_info=True)

    # ── Task 12: GovernanceBudgetManager (read-side cost control) ─────

    @property
    def budget_manager(self):
        """Lazily constructed
        :class:`ari.rqgm.budget.GovernanceBudgetManager` (plan 12 §5.4/§7).

        Decision-point gating only — the manager never raises and never
        blocks the loop; construction failure degrades to ``None`` (every
        consumer tolerates its absence). The L0 fixed layer never consults
        it (the constitutional floor is not budgetable).
        """
        if self._budget_manager is None:
            try:
                from ari import cost_tracker
                from ari.rqgm.budget import GovernanceBudgetManager
                from ari.rqgm.store import ImmutableAuditLog

                self._budget_manager = GovernanceBudgetManager(
                    self.cfg,
                    epoch_state=lambda: self.current_epoch,
                    cost_tracker=cost_tracker.get(),
                    checkpoint_dir=self.checkpoint_dir,
                    audit_log=ImmutableAuditLog(self.checkpoint_dir),
                    proposal_store=lambda: self._proposal_store,
                )
            except Exception:
                log.warning("GovernanceBudgetManager construction failed",
                            exc_info=True)
        return self._budget_manager

    # ── Task 05: GovernanceOrchestrator (epoch-boundary audit) ────────

    @property
    def governance(self):
        """Lazily constructed
        :class:`ari.rqgm.governance.GovernanceOrchestrator` (plan 05 §5.1).

        The plan's ``build_runtime`` construction site is realised through
        this facade: ``RQGMRuntime`` IS the wrapped object ``build_runtime``
        hands to ``_run_loop`` (plan 05 §4), so constructing the orchestrator
        here keeps the wiring config-conditional (``ari_rqgm`` only) without
        touching the 6-tuple. ``None`` when the kernel is unavailable — the
        kernel is the required role-separation authority (§7).
        """
        if self._governance is None and self.kernel is not None:
            try:
                from ari.rqgm.governance import GovernanceOrchestrator
                from ari.rqgm.store import ImmutableAuditLog

                self._governance = GovernanceOrchestrator(
                    getattr(self.cfg, "rqgm", None),
                    kernel=self.kernel,
                    llm=self.llm,
                    audit_writer=ImmutableAuditLog(self.checkpoint_dir),
                    # Task 12 §5.5: the replay/candidate evaluation path
                    # consults the governance cache first when
                    # rqgm.replay.use_cached_results (default true).
                    governance_cache=self._build_governance_cache(),
                )
            except Exception:
                log.warning("GovernanceOrchestrator construction failed",
                            exc_info=True)
        return self._governance

    def _build_governance_cache(self):
        """The Task 12 GovernanceCache, or ``None`` when replay caching is
        off (``rqgm.replay.use_cached_results: false``) or unavailable —
        every consumer tolerates its absence (fail-open)."""
        if self.checkpoint_dir is None:
            return None
        replay_cfg = getattr(getattr(self.cfg, "rqgm", None), "replay", None)
        if isinstance(replay_cfg, dict):
            use_cached = bool(replay_cfg.get("use_cached_results", True))
        else:
            use_cached = bool(getattr(replay_cfg, "use_cached_results", True))
        if not use_cached:
            return None
        try:
            from ari.rqgm.governance_cache import GovernanceCache

            return GovernanceCache(self.checkpoint_dir)
        except Exception:
            log.warning("GovernanceCache construction failed", exc_info=True)
            return None

    def _governance_enabled(self) -> bool:
        """``rqgm.governance.enabled`` (RQGM Task 13 §5.1 flag on Task 05's
        block): ablation rungs B2-B4 run ``ari_rqgm`` with the epoch audit
        off. Default true — the master interlock still gates everything."""
        gov = getattr(getattr(self.cfg, "rqgm", None), "governance", None)
        if isinstance(gov, dict):
            return bool(gov.get("enabled", True))
        return bool(getattr(gov, "enabled", True)) if gov is not None else True

    def run_epoch_audit(self, checkpoint_dir: "str | Path | None" = None):
        """Best-effort ``audit_epoch`` invocation at the epoch boundary
        (plan 05 §5.2 lineage-hook discipline: fail-open, never raises).

        Returns the GovernanceReport or ``None``. Under the Task 04 resume
        integrity carry-over (``governance_suspended``) the audit is skipped
        — the active set stays frozen and no new governance records are
        produced until the suspension clears (Tasks 04/09). With
        ``rqgm.governance.enabled: false`` (ablation rungs B2-B4) the audit
        is skipped entirely and no governance records are produced.
        """
        if not self._governance_enabled():
            log.info("rqgm.governance.enabled=false; epoch audit skipped")
            return None
        if self.governance_suspended:
            log.warning("governance suspended (resume integrity carry-over); "
                        "epoch audit skipped")
            return None
        gov = self.governance
        st = self._epoch_state
        if gov is None or st is None or st.epoch is None:
            return None
        ckpt = (
            Path(checkpoint_dir)
            if checkpoint_dir is not None
            else self.checkpoint_dir
        )
        if ckpt is None:
            return None
        # Task 07 (plan 07 §5.4): boundary candidate generation runs in the
        # same window that assembles the audit inputs, BEFORE audit_epoch,
        # so this epoch's candidates ride the report's
        # candidate_evaluations into Task 09's adoption path. Fail-open:
        # the helper never raises; a generation failure degrades to an
        # empty candidate set and the audit proceeds unchanged.
        candidates = self._generate_prompt_candidates(ckpt)
        try:
            from ari.rqgm.store import ImmutableAuditLog

            # Paper phase (docs/plans/ari_rqgm_paper/04): the anchor pool (a
            # PaperAnchorPool carrying held-out anchor_cases with per-reviewer
            # results) feeds board/anchor scoring so the ReliabilityMonitor +
            # AnchorBoard can assess and — for a reviewer that disagrees with
            # ground truth — sanction the incumbent. Exploration is unchanged.
            audit_pool = (
                self._anchor_pool
                if (self._paper_phase and self._anchor_pool is not None)
                else self.adversarial_pool
            )
            report = gov.audit_epoch(
                epoch_state=st.epoch,
                audit_log=ImmutableAuditLog.read(ckpt),
                component_registry=st.components,
                prompt_registry=st.prompts,
                candidate_prompts=candidates,
                # Task 06: pool admission/eviction/snapshot is the audit's
                # internal step 7 (epoch-boundary-only pool updates).
                adversarial_replay_pool=audit_pool,
                # Task 12 §7: every internal LLM step consults the budget
                # manager (spend caps / degrade posture) before spending.
                budget_manager=self.budget_manager,
            )
            # The report is advisory input to Task 09's transition engine;
            # v1 stops here (it is already appended to the audit log).
            return report
        except Exception:
            log.warning("governance audit failed; continuing without report",
                        exc_info=True)
            return None

    # ── Task 07: boundary prompt evolution (candidate generation) ─────

    #: The founding PromptMutator component id (the registered meta-tier
    #: emitter every ``prompt_candidate`` record is attributed to).
    PROMPT_MUTATOR_ID = "prompt_mutator_v1"

    #: LLM-less knob kinds (plan 07 §5.4): deterministic candidates a calm,
    #: LLM-free boundary can still mint (bytes stay the incumbent's).
    _KNOB_MUTATION_KINDS: tuple[str, ...] = (
        "threshold_tuning", "schema_tightening",
    )

    def _prompt_evolution_cfg(self):
        pe = getattr(getattr(self.cfg, "rqgm", None), "prompt_evolution",
                     None)
        if pe is None:
            rqgm_cfg = getattr(self.cfg, "rqgm", None)
            if isinstance(rqgm_cfg, dict):
                pe = rqgm_cfg.get("prompt_evolution")
        return pe

    def _prompt_evolution_enabled(self) -> bool:
        # Paper phase (docs/plans/ari_rqgm_paper/03 §5.9): the on-ramp toggle
        # is rqgm.paper.prompt_evolution.enabled — DISTINCT from the
        # exploration rqgm.prompt_evolution.enabled. false => the roles are
        # registered (scoring works) but never co-evolve.
        if self._paper_phase:
            pe = getattr(
                getattr(getattr(self.cfg, "rqgm", None), "paper", None),
                "prompt_evolution", None,
            )
            if isinstance(pe, dict):
                return bool(pe.get("enabled", True))
            return bool(getattr(pe, "enabled", True)) if pe is not None else True
        pe = self._prompt_evolution_cfg()
        if isinstance(pe, dict):
            return bool(pe.get("enabled", True))
        return bool(getattr(pe, "enabled", True)) if pe is not None else True

    def _configured_mutation_kinds(self) -> tuple[str, ...]:
        """``rqgm.prompt_evolution.mutation_kinds`` filtered to the closed
        Task 07 vocabulary, order preserved (selection is order-first)."""
        from ari.rqgm.prompt_evolution import MUTATION_KINDS

        pe = self._prompt_evolution_cfg()
        raw = (
            pe.get("mutation_kinds") if isinstance(pe, dict)
            else getattr(pe, "mutation_kinds", None)
        )
        if raw is None:
            return MUTATION_KINDS
        return tuple(str(k) for k in raw if str(k) in MUTATION_KINDS)

    def _mutator_llm_callable(self):
        """The PromptMutator's ``prompt -> str`` seam over the injected
        LLM (``None`` degrades to the LLM-less knob kinds). Duck-typed like
        ``clean_room.CleanRoomPromptGenerator._complete``: an
        ``LLMClient``-style object or a bare callable both work."""
        llm = self.llm
        if llm is None:
            return None
        complete = getattr(llm, "complete", None)
        if not callable(complete):
            return llm if callable(llm) else None

        def call(prompt: str) -> str:
            messages = [{"role": "user", "content": prompt}]
            try:
                resp = complete(
                    messages,
                    require_tool=False,
                    phase="governance",
                    skill="prompt_mutator",
                )
            except TypeError:
                resp = complete(messages, require_tool=False)
            return str(getattr(resp, "content", "") or "")

        return call

    def _select_mutation_kind(self) -> "tuple[str | None, bool]":
        """``(kind, llm_backed)`` for this proposal — the first configured
        kind when an LLM is available and the governance call budget allows,
        else the first configured LLM-less knob kind (plan 07 §5.4 gating:
        budget degradation falls back, it never blocks the boundary).

        The ``GOVERNANCE_LLM_CALL`` consult is READ-ONLY (the
        ``_motion_replay_cap`` precedent): ``max_llm_calls_per_audit`` is
        the audit's own budget, so the mutator degrades to knob kinds when
        it is exhausted but never books against it — mutator LLM spend is
        structurally bounded by the candidate caps instead.
        """
        kinds = self._configured_mutation_kinds()
        knob = tuple(k for k in kinds if k in self._KNOB_MUTATION_KINDS)
        llm_ok = self._mutator_llm_callable() is not None
        manager = self.budget_manager
        if llm_ok and manager is not None:
            try:
                from ari.rqgm.budget import (
                    GOVERNANCE_LLM_CALL,
                    BudgetedAction,
                )

                llm_ok = manager.check(
                    BudgetedAction(GOVERNANCE_LLM_CALL)
                ).allowed
            except Exception:
                log.warning("mutation-kind budget consult failed "
                            "(fail-open)", exc_info=True)
        if not llm_ok:
            return (knob[0], False) if knob else (None, False)
        if not kinds:
            return None, False
        return kinds[0], kinds[0] not in self._KNOB_MUTATION_KINDS

    def _active_evolvable_incumbents(self, st, ckpt, records) -> dict:
        """``role -> (PromptSpec, template_text)`` over every role whose
        latest ACTIVE registry entry resolves to an ``evolvable`` PromptSpec
        (founding specs rebuilt from the committed tables; evolved specs
        from the Task 07 candidate records). The mutator's own role is
        excluded — same-role generation is a constitutional violation
        (plan 07 §5.3 stage 2)."""
        from ari.rqgm.events import ACTIVE_STATUSES, UTILITY_POLICY_ROLE
        from ari.rqgm.prompt_evolution import PromptMutator
        from ari.rqgm.prompt_spec import (
            build_founding_specs,
            prompt_spec_from_dict,
        )

        latest: dict = {}
        for entry in st.prompts.entries().values():
            if entry.status in ACTIVE_STATUSES:
                latest[entry.role] = entry  # replay order: latest wins
        latest.pop(PromptMutator.ROLE, None)
        # Paper phase (docs/plans/ari_rqgm_paper/03 §5.9): co-evolve ONLY the
        # paper roles. The paper checkpoint registers the full founding set so
        # the governance/kernel machinery is complete, but the paper boundary
        # exercises paper_writer/paper_reviewer — focusing the per-epoch
        # candidate budget on them (and never spending it on exploration roles
        # that this phase does not run). Exploration is unaffected (gated).
        if self._paper_phase:
            latest = {
                role: entry
                for role, entry in latest.items()
                if str(role).startswith("paper_")
            }
            posture = self._paper_ablation_posture()
            if posture is not None:
                latest = {
                    role: entry
                    for role, entry in latest.items()
                    if posture.role_evolution_enabled(role)
                }
        # Task 14 (plan 14 §5.3): the utility policy is a policy DOCUMENT,
        # evolved by PolicyMutator — asking a template-rewriting LLM to
        # mutate canonical JSON as prose is exactly the confusion the
        # separate proposer exists to prevent. The role would be skipped
        # anyway (its founding spec is not in build_founding_specs(), so
        # ``spec is None -> continue`` below), but the explicit pop makes
        # the intent load-bearing rather than incidental.
        latest.pop(UTILITY_POLICY_ROLE, None)
        founding: dict = {}
        try:
            founding = {
                s.prompt_id: s
                for s in build_founding_specs(include_paper=self._paper_phase)
            }
        except Exception:
            log.warning("founding spec rebuild failed; founding incumbents "
                        "skipped this boundary", exc_info=True)
        evolved = {
            str(r.get("candidate_id", "")): dict(r.get("prompt_spec") or {})
            for r in records
            if r.get("record_type") == "prompt_candidate"
        }
        out: dict = {}
        for role in sorted(latest):
            entry = latest[role]
            spec = founding.get(entry.prompt_id)
            if spec is None and evolved.get(entry.prompt_id):
                try:
                    spec = prompt_spec_from_dict(evolved[entry.prompt_id])
                except Exception:
                    spec = None
            if spec is None or not spec.evolvable:
                continue
            try:
                text, _ = st.prompts.resolve_text(
                    entry.prompt_id, checkpoint_dir=ckpt
                )
            except Exception:
                log.warning("incumbent text resolve failed for %s",
                            entry.prompt_id, exc_info=True)
                continue
            out[role] = (spec, text)
        return out

    def _abstract_failure_summaries(self) -> list:
        """Task 06 ``abstract_view`` dicts only (contamination-free); the
        Red-Queen posture: failure signals enrich candidate generation and
        evaluation, they never gate it."""
        pool = self.adversarial_pool
        if pool is None:
            return []
        try:
            return [dict(c.get("abstract_view") or {}) for c in pool.cases()]
        except Exception:
            return []

    def _generate_prompt_candidates(self, ckpt) -> tuple:
        """Mint this boundary's prompt candidates (plan 07 §5.4).

        Governed, budgeted, epoch-boundary-only: one PromptMutator proposal
        per EVOLVABLE role with an ACTIVE incumbent, deterministic role
        order, capped by ``rqgm.prompt_evolution`` (per-role and total) and
        gated per-candidate through the Task 12 budget manager. Candidates
        persist through the Task 07 record layer
        (``prompt_evolution.jsonl`` + the write-once ``rqgm_prompts/``
        body); the return value is the ``candidate_prompts`` view
        ``audit_epoch``'s board scoring consumes. Resume-safe: the
        deterministic ``candidate_id`` is the dedup key, so a re-run
        boundary never duplicates a candidate record. Never raises
        (``run_epoch_audit`` fail-open discipline) and never delays the
        boundary; with ``rqgm.prompt_evolution.enabled: false`` it emits a
        ``prompt_evolution_skipped`` audit line (the
        ``meta_evolution_skipped`` pattern) and mints nothing.
        """
        try:
            st = self._epoch_state
            if st is None or st.epoch is None or ckpt is None:
                return ()
            epoch_id = str(st.epoch.epoch_id or "")
            if not self._prompt_evolution_enabled():
                self._append_audit_event(
                    "prompt_evolution_skipped",
                    {"epoch_id": epoch_id,
                     "reason": "prompt_evolution.enabled=false"},
                    checkpoint_dir=ckpt,
                )
                return ()
            from ari.rqgm.events import format_prompt_id
            from ari.rqgm.prompt_evolution import PromptMutator
            from ari.rqgm.prompt_records import (
                load_prompt_evolution_log,
                record_prompt_evolution_event,
            )

            records = load_prompt_evolution_log(ckpt)
            existing_ids = {
                str(r.get("candidate_id", ""))
                for r in records
                if r.get("record_type") == "prompt_candidate"
            }
            seq = sum(
                1 for r in records
                if str(r.get("record_id", "")).startswith("pcand_")
            )
            incumbents = self._active_evolvable_incumbents(st, ckpt, records)
            mutator = PromptMutator(
                self.PROMPT_MUTATOR_ID,
                llm=self._mutator_llm_callable(),
                checkpoint_dir=ckpt,
            )
            failure_summaries = self._abstract_failure_summaries()
            manager = self.budget_manager
            proposed: list = []
            skipped: list[str] = []
            for role in sorted(incumbents):
                incumbent, incumbent_text = incumbents[role]
                candidate_id = format_prompt_id(
                    role, int(incumbent.version) + 1
                )
                if candidate_id in existing_ids:
                    # Resume/idempotency: the content-derived id already
                    # exists in the Task 07 log (interrupted-boundary
                    # re-run, or a still-pending candidate from an earlier
                    # epoch) — never a duplicate record.
                    skipped.append(
                        f"{role}: {candidate_id} already recorded"
                    )
                    continue
                if manager is not None:
                    try:
                        from ari.rqgm.budget import (
                            PROMPT_CANDIDATE,
                            BudgetedAction,
                        )

                        verdict = manager.gate(
                            BudgetedAction(PROMPT_CANDIDATE, role=role)
                        )
                        if not verdict.allowed:
                            skipped.append(f"{role}: {verdict.reason}")
                            continue
                    except Exception:
                        log.warning("prompt-candidate budget gate failed "
                                    "(fail-open)", exc_info=True)
                kind, llm_backed = self._select_mutation_kind()
                if kind is None:
                    skipped.append(f"{role}: no permitted mutation kind")
                    continue
                candidate = self._propose_candidate(
                    mutator, role, incumbent, incumbent_text, kind,
                    failure_summaries, epoch_id=epoch_id, record_seq=seq,
                    records=records, cfg=self.cfg,
                )
                if candidate is None and llm_backed:
                    # LLM-backed kind failed or declined: deterministic
                    # knob fallback so a degraded boundary still evolves.
                    knob = tuple(
                        k for k in self._configured_mutation_kinds()
                        if k in self._KNOB_MUTATION_KINDS
                    )
                    if knob:
                        kind, llm_backed = knob[0], False
                        candidate = self._propose_candidate(
                            mutator, role, incumbent, incumbent_text, kind,
                            failure_summaries, epoch_id=epoch_id,
                            record_seq=seq, records=records, cfg=self.cfg,
                        )
                if candidate is None:
                    skipped.append(f"{role}: mutator declined ({kind})")
                    continue
                _val_fail = self._deterministic_candidate_failures(
                    candidate, ckpt
                )
                if _val_fail:
                    # DROPPED before scoring: it never enters
                    # candidate_evaluations, so it can never be adopted.
                    log.warning(
                        "candidate %s (%s) DROPPED: deterministic validation "
                        "failed %s", candidate.candidate_id, role, _val_fail,
                    )
                    skipped.append(f"{role}: validation failed {_val_fail}")
                    continue
                record_prompt_evolution_event(ckpt, candidate)
                records.append(candidate.to_dict())
                existing_ids.add(candidate.candidate_id)
                seq += 1
                proposed.append(candidate)
                if manager is not None:
                    try:
                        from ari.rqgm.budget import (
                            PROMPT_CANDIDATE,
                            BudgetedAction,
                        )

                        manager.consume(
                            BudgetedAction(PROMPT_CANDIDATE, role=role)
                        )
                    except Exception:
                        log.warning("prompt-candidate budget consume "
                                    "failed", exc_info=True)
            self._append_audit_event(
                "prompt_evolution",
                {
                    "epoch_id": epoch_id,
                    "outcome": "proposed" if proposed else "no_candidates",
                    "candidate_ids": [c.candidate_id for c in proposed],
                    "skipped": skipped,
                },
                checkpoint_dir=ckpt,
            )
            return tuple(
                {
                    "prompt_id": c.candidate_id,
                    "role": c.role,
                    "prompt_hash": c.prompt_hash,
                }
                for c in proposed
            )
        except Exception:
            log.warning("prompt evolution failed (fail-open; boundary "
                        "continues without candidates)", exc_info=True)
            return ()

    @staticmethod
    def _propose_candidate(
        mutator, role, incumbent, incumbent_text, kind, failure_summaries,
        *, epoch_id, record_seq, records, cfg,
    ):
        """One fail-open ``PromptMutator.propose`` call (per-role isolation:
        a single bad template never aborts the other roles' proposals)."""
        try:
            return mutator.propose(
                role,
                incumbent,
                failure_summaries,
                incumbent_text=incumbent_text,
                mutation_kind=kind,
                epoch_id=epoch_id,
                record_seq=record_seq,
                existing_records=records,
                cfg=cfg,
                rationale=f"epoch-boundary {kind}",
            )
        except Exception:
            log.warning("prompt mutation proposal failed for role %s "
                        "(fail-open)", role, exc_info=True)
            return None

    def _deterministic_candidate_failures(self, candidate, ckpt) -> list:
        """Run the DETERMINISTIC candidate-validation stages (plan 07 §5.4
        stages 1-3) and return the failures, or ``[]`` when the candidate is
        clean. Never raises.

        ``CandidateValidationPipeline`` — the documented six-stage validation —
        is never instantiated in production, so on the EXPLORATION path a minted
        candidate went straight into ``candidate_evaluations`` unvalidated: a
        candidate that violates the static/constitutional/role-instruction rules
        could be board-scored and adopted. The paper path already re-implements
        these three stages inline (``paper_runtime`` §5.9 step 2); this is the
        exploration half, calling the SAME single definitions so there is
        exactly one implementation of each stage.
        """
        from ari.rqgm.prompt_evolution import (
            constitutional_validation_failures,
            role_instruction_constraint_failures,
            static_validation_failures,
        )

        failures: list = []
        try:
            spec = getattr(candidate, "prompt_spec", None) or {}
            if not isinstance(spec, dict):
                spec = getattr(spec, "to_dict", lambda: {})() or {}
            # Stage 1 — static_validation. Needs the candidate's resolved body;
            # when it cannot be read the stage is SKIPPED (announced), never
            # silently passed.
            text = ""
            try:
                st = self._epoch_state
                prompts = getattr(st, "prompts", None) if st else None
                pid = str(spec.get("prompt_id") or "")
                if prompts is not None and pid:
                    text, _ = prompts.resolve_text(pid, checkpoint_dir=ckpt)
            except Exception:
                text = ""
            if text:
                failures.extend(static_validation_failures(candidate, text))
            else:
                log.debug("candidate %s: static_validation skipped (no "
                          "resolvable body)", getattr(candidate, "candidate_id", "?"))
            # Stage 2 — constitutional_validation (no text needed).
            failures.extend(constitutional_validation_failures(candidate))
            # Stage 3 — role instruction constraints.
            role = str(getattr(candidate, "role", "") or "")
            instruction = str(spec.get("role_instruction") or "")
            if role and instruction:
                failures.extend(
                    role_instruction_constraint_failures(role, instruction)
                )
        except Exception:
            log.warning("candidate validation failed (fail-open: candidate "
                        "kept)", exc_info=True)
            return []
        return [str(f) for f in failures]

    def _append_audit_event(
        self, event_type: str, payload: dict, *, checkpoint_dir=None,
    ) -> None:
        """Best-effort ImmutableAuditLog append (never raises)."""
        ckpt = checkpoint_dir if checkpoint_dir is not None \
            else self.checkpoint_dir
        if ckpt is None:
            return
        try:
            from ari.rqgm.store import ImmutableAuditLog

            ImmutableAuditLog(ckpt).append(event_type, dict(payload))
        except Exception:
            log.warning("audit append failed for %s", event_type,
                        exc_info=True)

    # ── Task 09: RegistryTransitionEngine (epoch-boundary transaction) ─

    @property
    def transition_engine(self):
        """Lazily constructed
        :class:`ari.rqgm.transition_engine.RegistryTransitionEngine`
        (plan 09 §5.5): the sole registry status writer, built only under
        ``ari_rqgm``. ``None`` when the kernel is unavailable — every
        transition must be kernel-validated (global invariant 11)."""
        if self._transition_engine is None and self.kernel is not None:
            try:
                from ari.rqgm.store import ImmutableAuditLog, RqgmStateStore
                from ari.rqgm.transition_engine import (
                    RegistryTransitionEngine,
                )

                if self._store is None:
                    self._store = RqgmStateStore()
                self._transition_engine = RegistryTransitionEngine(
                    getattr(self.cfg, "rqgm", None),
                    self.kernel,
                    store=self._store,
                    enforcement=self.kernel_enforcement,
                    audit_log=ImmutableAuditLog(self.checkpoint_dir),
                )
            except Exception:
                log.warning("RegistryTransitionEngine construction failed",
                            exc_info=True)
        return self._transition_engine

    def _run_epoch_boundary(self, ckpt, *, node_count: int, run_id: str,
                            search_state: "dict | None" = None):
        """Plan 09 §5.3 at the ``ensure_epoch`` boundary: audit → resolve →
        kernel-validate → apply/commit via the Task 02 transaction. Always
        returns a state (the prior state on failure — epoch continues);
        without an engine it degrades to the plain Task 02 boundary."""
        report = self.run_epoch_audit(ckpt)
        # Task 11 (plan 11 §5.4): the meta tier runs after audit_epoch and
        # before resolve_transition. Best-effort — a meta failure degrades
        # to "no candidates this epoch", never a delayed boundary.
        self._run_meta_evolution(report)
        # Task 14 (plan 14 §5.4): the utility policy's proposer runs in the
        # SAME candidate-minting window, with the same best-effort posture.
        # Its candidate is registered at status='candidate' through the
        # boundary transaction by the existing intake path, so the NEXT
        # boundary can iterate it up the T1->T6 spine.
        self._run_utility_evolution(report, ckpt)
        st = self._epoch_state
        # Task 07 candidate intake (plan 07 §5.3, plan 09 T1): every
        # candidate minted this boundary (the FIX-A + meta channels ran just
        # above) is registered into the GovernedPromptRegistry at
        # status='candidate' through the SAME boundary transaction, so the
        # NEXT boundary's resolve_transition can iterate it up the T1–T6
        # spine. Gathered from the evolution log, deduped against the
        # registry, so it is idempotent/resume-safe and never re-registers.
        intake = self._intake_registration_events(ckpt, st)
        engine = self.transition_engine
        if engine is not None:
            transition = None
            # Task 14 (plan 14 §5.5, blocker 1): the pending utility_policy
            # candidates' §5.5 deterministic dry-run evaluations join the
            # candidate_evaluations resolve_transition consumes, so the policy
            # iterates the T1->T3->T6 spine on the role-agnostic engine. The
            # governance report scores behavioral prompt candidates; the
            # utility policy is a score over axes, not scored over cases, so
            # its board is computed here and merged in (never inside the
            # governance judge, which keeps governance policy-agnostic).
            # Paper phase (docs/plans/ari_rqgm_paper/03 §5.9, /04 §5.4): the
            # pending paper_writer/paper_reviewer candidates' full-spine
            # evaluations join the same candidate_evaluations the role-agnostic
            # engine consumes, exactly as the utility_policy criterion does.
            # The reviewer is scored on held-out anchor agreement; the writer
            # (no anchor) is epoch-local. These lead the list so they WIN the
            # first-per-prompt dedup in resolve_transition over the governance
            # board's zero-coverage "inconclusive" for a not-yet-scored paper
            # candidate hash.
            candidate_evals = (
                self._paper_candidate_evaluations(st, ckpt)
                + list(getattr(report, "candidate_evaluations", None) or ())
                + self._utility_policy_candidate_evaluations(st, ckpt)
            )
            # T6 for BEHAVIOURAL roles reads `shadow_samples` / `shadow_score`,
            # and the governance board — the only producer of exploration
            # evaluations — emits neither, so the adoption edge was unreachable
            # for every exploration role: candidates were minted, scored, and
            # then stranded in `shadow` forever. Attach the LIVE side-by-side
            # evidence recorded during the epoch. Absent observations stay
            # {0, None} — honestly no basis, so T6 simply does not open.
            for _ev in candidate_evals:
                if not isinstance(_ev, dict):
                    continue
                if _ev.get("shadow_samples") is not None:
                    continue          # paper / utility_policy already declared
                _ev.update(self.shadow_evidence(
                    str(_ev.get("prompt_hash") or ""),
                    str(_ev.get("candidate_id") or ""),
                ))
            try:
                transition = engine.resolve_transition(
                    epoch_state=st.epoch,
                    governance_report=report,
                    candidate_evaluations=candidate_evals,
                    components=st.components,
                    prompts=st.prompts,
                    status_history=engine.load_status_history(ckpt),
                    governance_suspended=self.governance_suspended,
                )
            except Exception:
                log.warning("transition resolve failed; boundary continues "
                            "without registry changes", exc_info=True)
            if transition is not None:
                try:
                    applied = engine.apply(
                        transition, checkpoint_dir=ckpt, state=st,
                        cfg=self.cfg, node_count=node_count, run_id=run_id,
                        intake_events=intake,
                    )
                    new_state = (
                        applied.state if applied.state is not None else st
                    )
                    if applied.committed:
                        # Task 10 (plan 10 §5.2): repair strictly after the
                        # committed apply and strictly before the boundary
                        # window closes (main thread, no node in flight).
                        self._run_frontier_repair(
                            applied.transition, new_state, ckpt,
                            search_state,
                        )
                        # Task 08 (plan 08 §5.1): pending clean-room
                        # requests execute inside the boundary window,
                        # right after the committed apply, on this thread.
                        self._process_clean_room(applied.transition,
                                                 new_state, ckpt)
                    return new_state
                except Exception:
                    log.warning("transition apply failed; epoch state "
                                "unchanged", exc_info=True)
                    return st
        return self._store.run_boundary(
            ckpt, st, self.cfg, node_count=node_count, run_id=run_id,
            registry_events=intake,
        )

    def _intake_registration_events(self, ckpt, st) -> list:
        """Task 07 candidate-intake events (plan 07 §5.3, plan 09 T1).

        Reads ``prompt_evolution.jsonl`` and returns one ``prompt_registered``
        event (status=``candidate``) per minted candidate NOT already in the
        governed registry — the single log covers all three candidate
        channels (FIX-A ``_generate_prompt_candidates``, the meta channel,
        and the Task 08 clean-room pass), so intake is uniform and no channel
        is missed. Dedup by registry membership AND the deterministic
        candidate id, so a re-run / resumed boundary never emits a duplicate
        ``prompt_registered`` for the same id. Fail-open: a read failure logs
        and returns ``[]`` — a registration failure never stalls the
        boundary (which keeps serving the incumbent set)."""
        try:
            if st is None or ckpt is None:
                return []
            from ari.rqgm.events import TransitionEvent
            from ari.rqgm.prompt_evolution import candidate_registration_payload
            from ari.rqgm.prompt_records import load_prompt_evolution_log
            from ari.rqgm.utility_evolution import (
                UTILITY_POLICY_CANDIDATE_RECORD_TYPE,
                utility_policy_registration_payload,
            )

            # Task 14: the utility-policy candidate rides the SAME log and
            # the SAME intake, so a governed policy enters the registry at
            # status='candidate' exactly like a prompt candidate and iterates
            # the same role-agnostic T-table (plan 14 §5.5).
            builders = {
                "prompt_candidate": candidate_registration_payload,
                UTILITY_POLICY_CANDIDATE_RECORD_TYPE: (
                    utility_policy_registration_payload
                ),
            }
            registered = set(st.prompts.entries())
            events: list = []
            seen: set[str] = set()
            for rec in load_prompt_evolution_log(ckpt):
                builder = builders.get(str(rec.get("record_type", "")))
                if builder is None:
                    continue
                cid = str(rec.get("candidate_id", ""))
                if not cid or cid in registered or cid in seen:
                    continue
                seen.add(cid)
                events.append(TransitionEvent(
                    event_type="prompt_registered",
                    payload=builder(rec),
                ))
            return events
        except Exception:
            log.warning("candidate intake registration failed (fail-open; "
                        "boundary continues without intake)", exc_info=True)
            return []

    # ── Task 14: governed utility evolution (boundary window) ─────────

    #: The one PolicyMutator component id (plan 14 §5.3 founding table).
    POLICY_MUTATOR_ID = "policy_mutator_v1"

    def _utility_evolution_cfg(self):
        return getattr(getattr(self.cfg, "rqgm", None), "utility_evolution",
                       None)

    def _utility_evolution_enabled(self) -> bool:
        ue = self._utility_evolution_cfg()
        if ue is None:
            return True
        if isinstance(ue, dict):
            return bool(ue.get("enabled", True))
        return bool(getattr(ue, "enabled", True))

    def _utility_mutation_kinds(self) -> list:
        ue = self._utility_evolution_cfg()
        default = ["axis_reweighting", "composite_swap",
                   "frontier_score_swap", "exploration_tuning"]
        if ue is None:
            return default
        raw = (
            ue.get("mutation_kinds", default) if isinstance(ue, dict)
            else getattr(ue, "mutation_kinds", default)
        )
        return [str(k) for k in (raw or [])]

    def _run_utility_evolution(self, report, ckpt) -> None:
        """Mint at most one utility-policy candidate for this boundary
        (plan 14 §5.4). Best-effort: a failure degrades to "no candidate
        this epoch", never a delayed boundary and never a raise.

        This is the CAUSE half of P1. The candidate is registered at
        ``status='candidate'`` through the boundary transaction by the
        existing intake path, so the NEXT boundary's ``resolve_transition``
        iterates it up the T1→T6 spine and, on adoption, ``freeze_epoch``
        reads it as the epoch's frozen policy.

        Fail-open at the loop, fail-closed at the constitution: a proposer
        failure costs a candidate; an ILLEGAL policy is blocked by the kernel
        and the boundary proceeds with the incumbent — which is always safe,
        because the incumbent is what produced the current frontier.
        """
        try:
            st = self._epoch_state
            if st is None or st.epoch is None or ckpt is None:
                return
            epoch_id = str(st.epoch.epoch_id or "")
            if not self._utility_evolution_enabled():
                self._append_audit_event(
                    "utility_evolution_skipped",
                    {"epoch_id": epoch_id,
                     "reason": "utility_evolution.enabled=false"},
                    checkpoint_dir=ckpt,
                )
                return
            incumbent = dict(getattr(st.epoch, "utility_policy", None) or {})
            if not incumbent:
                return
            from ari.rqgm.prompt_records import (
                load_prompt_evolution_log,
                record_prompt_evolution_event,
            )
            from ari.rqgm.utility_evolution import (
                UTILITY_POLICY_CANDIDATE_RECORD_TYPE,
                PolicyMutator,
            )

            records = load_prompt_evolution_log(ckpt)
            if self._utility_rewrite_too_recent(records, st):
                self._append_audit_event(
                    "utility_evolution_skipped",
                    {"epoch_id": epoch_id,
                     "reason": "min_epochs_between_rewrites"},
                    checkpoint_dir=ckpt,
                )
                return
            existing_ids = {
                str(r.get("candidate_id", "")) for r in records
                if r.get("record_type") == UTILITY_POLICY_CANDIDATE_RECORD_TYPE
            }
            seq = sum(
                1 for r in records
                if str(r.get("record_id", "")).startswith("upc_")
            )
            parent_id, version = self._active_utility_policy_identity(st)
            mutator = PolicyMutator(
                self.POLICY_MUTATOR_ID,
                llm=self._mutator_llm_callable(),
                checkpoint_dir=ckpt,
            )
            kinds = self._utility_mutation_kinds()
            candidate = None
            skipped: list[str] = []
            for kind in kinds:
                cand = mutator.propose(
                    incumbent,
                    evidence=self._utility_evidence(report),
                    mutation_kind=kind,
                    epoch_id=epoch_id,
                    record_seq=seq,
                    existing_records=records,
                    cfg=self.cfg,
                    parent_prompt_id=parent_id,
                    incumbent_version=version,
                    rationale=f"boundary {epoch_id}: {kind}",
                )
                if cand is None:
                    skipped.append(f"{kind}: no proposal")
                    continue
                if cand.candidate_id in existing_ids:
                    # Resume/idempotency: the deterministic id already exists
                    # (interrupted-boundary re-run, or a still-pending
                    # candidate from an earlier epoch).
                    skipped.append(f"{kind}: {cand.candidate_id} already recorded")
                    break
                candidate = cand
                break
            if candidate is None:
                self._append_audit_event(
                    "utility_evolution",
                    {"epoch_id": epoch_id, "outcome": "no_candidates",
                     "skipped": skipped},
                    checkpoint_dir=ckpt,
                )
                return
            # The body must be on disk BEFORE the entry that references it:
            # text is referenced by source, never inlined.
            from ari.rqgm.events import canonical_json
            from ari.rqgm.prompt_loader import write_evolved_policy_body

            write_evolved_policy_body(
                ckpt, candidate.candidate_id, canonical_json(candidate.policy)
            )
            record_prompt_evolution_event(ckpt, candidate)
            self._append_audit_event(
                "utility_evolution",
                {"epoch_id": epoch_id, "outcome": "proposed",
                 "candidate_id": candidate.candidate_id,
                 "policy_hash": candidate.policy_hash,
                 "mutation_kind": candidate.mutation_kind,
                 "skipped": skipped},
                checkpoint_dir=ckpt,
            )
        except Exception:
            log.warning("utility evolution failed (boundary continues with "
                        "the incumbent policy)", exc_info=True)

    def _live_axis_set(self):
        """The epoch's LIVE axis set for the CK-UTL-006 advisory (plan 14 §5.6):
        the axes the evaluator will actually score, per
        ``cfg.evaluator.axis_mode`` — NOT the incumbent policy's static
        ``axis_weights`` keys, which are empty under the default
        ``axis_mode: dynamic`` and made the advisory dead in the very mode its
        rationale is written for. Best-effort: ``None`` disables the advisory."""
        from ari.evaluator.dynamic_axes import resolve_live_axis_set
        return resolve_live_axis_set(self.cfg, self.checkpoint_dir)

    def _utility_policy_candidate_evaluations(self, st, ckpt) -> list:
        """Plan 14 §5.5 (blocker 1): the §5.5 deterministic dry-run evaluation
        for every pending utility_policy registry entry (status candidate /
        validated / shadow), merged into the ``candidate_evaluations``
        ``resolve_transition`` consumes so the criterion iterates the
        T1 -> T3 -> T6 spine. Reads the successor body write-once from the
        checkpoint (apply happens later; resolve stays pure because this runs
        in the runtime, not the engine). Fail-open: never raises into the
        boundary — an unreadable/unevaluable candidate is simply omitted."""
        import json

        out: list = []
        try:
            if st is None or st.epoch is None or ckpt is None:
                return out
            from ari.rqgm.events import UTILITY_POLICY_ROLE
            from ari.rqgm.utility_evolution import (
                evaluate_utility_policy_candidate,
            )

            incumbent = dict(getattr(st.epoch, "utility_policy", None) or {})
            # The epoch's LIVE axis set (plan 14 §5.6) — the axes the evaluator
            # scores, per axis_mode — NOT the incumbent policy's static
            # axis_weights keys (empty under the default axis_mode: dynamic,
            # which made CK-UTL-006 dead on the live path).
            live_axes = self._live_axis_set()
            for pid, entry in (st.prompts.entries() or {}).items():
                if str(getattr(entry, "role", "")) != UTILITY_POLICY_ROLE:
                    continue
                if str(getattr(entry, "status", "")) not in (
                    "candidate", "validated", "shadow"
                ):
                    continue
                try:
                    text, _h = st.prompts.resolve_text(pid, checkpoint_dir=ckpt)
                    body = json.loads(text)
                except Exception:
                    log.warning("utility policy candidate %s unreadable; "
                                "skipped this boundary", pid, exc_info=True)
                    continue
                out.append(evaluate_utility_policy_candidate(
                    body,
                    prompt_id=pid,
                    registered_hash=str(getattr(entry, "prompt_hash", "") or ""),
                    incumbent_body=incumbent,
                    kernel=self.kernel,
                    live_axes=live_axes,
                ))
        except Exception:
            log.warning("utility policy candidate evaluation failed "
                        "(fail-open; boundary continues)", exc_info=True)
        return out

    def _paper_candidate_evaluations(self, st, ckpt) -> list:
        """Paper-archive candidate evaluations (docs/plans/ari_rqgm_paper/03
        §5.9, /04 §5.4), merged into ``candidate_evaluations`` exactly like
        the utility_policy criterion.

        Only fires in the paper phase with an injected evaluator. The
        evaluator (built by ``PaperArchiveRuntime``) scores each pending
        paper_writer/paper_reviewer candidate: the reviewer on held-out anchor
        agreement (the APReS utility), the writer epoch-locally (no anchor).
        It returns full-spine eval dicts (verdict / replay_score / anchor_score
        / case_refs / shadow_samples / shadow_score) so the candidates iterate
        the role-agnostic T1 -> T3 -> T6 spine. A board with no basis is
        reported ``None`` and carries the ``no_replay_basis`` sentinel, so the
        engine's role-scoped waiver — never a fabricated score — is what keeps a
        zero-coverage candidate moving.

        Both pools are injected: the anchor pool for the held-out corpus board,
        and the ``AdversarialReplayPool`` for the §5.5 self-preference replay
        board (the pool's READ side; admission is
        ``_admit_paper_validated_attacks``). Fail-open: never raises."""
        if not self._paper_phase or self._paper_candidate_evaluator is None:
            return []
        try:
            if st is None or st.epoch is None or ckpt is None:
                return []
            return list(
                self._paper_candidate_evaluator(
                    st, ckpt, self._anchor_pool, self.adversarial_pool
                ) or ()
            )
        except Exception:
            log.warning("paper candidate evaluation failed (fail-open; "
                        "boundary continues)", exc_info=True)
            return []

    def _active_utility_policy_identity(self, st) -> tuple:
        """``(prompt_id, version)`` of the active ``utility_policy`` entry —
        the lineage parent of the candidate this boundary mints. Falls back
        to the founding identity when no entry exists (a pre-14 resume)."""
        from ari.rqgm.events import ACTIVE_STATUSES, UTILITY_POLICY_ROLE
        from ari.rqgm.prompt_spec import UTILITY_POLICY_PROMPT_ID

        pid = UTILITY_POLICY_PROMPT_ID
        for entry_id, entry in (st.prompts.entries() or {}).items():
            if (
                str(getattr(entry, "role", "")) == UTILITY_POLICY_ROLE
                and str(getattr(entry, "status", "")) in ACTIVE_STATUSES
            ):
                pid = str(entry_id)
        version = 1
        tail = pid.rsplit("_v", 1)
        if len(tail) == 2 and tail[1].isdigit():
            version = int(tail[1])
        return pid, version

    def _utility_rewrite_too_recent(self, records, st) -> bool:
        """``rqgm.utility_evolution.min_epochs_between_rewrites`` (plan 14
        §6.3 / R1): bounds how often the frontier pays a rewrite's
        invalidation cost."""
        ue = self._utility_evolution_cfg()
        raw = (
            ue.get("min_epochs_between_rewrites", 1) if isinstance(ue, dict)
            else getattr(ue, "min_epochs_between_rewrites", 1)
        ) if ue is not None else 1
        try:
            gap = max(0, int(raw))
        except (TypeError, ValueError):
            gap = 1
        if gap <= 0:
            return False
        from ari.rqgm.utility_evolution import (
            UTILITY_POLICY_CANDIDATE_RECORD_TYPE,
        )

        seqs = []
        for rec in records:
            if rec.get("record_type") != UTILITY_POLICY_CANDIDATE_RECORD_TYPE:
                continue
            eid = str(rec.get("epoch_id", ""))
            tail = eid.rsplit("_", 1)
            if len(tail) == 2 and tail[1].isdigit():
                seqs.append(int(tail[1]))
        if not seqs:
            return False
        return (int(st.epoch.epoch_seq) - max(seqs)) < gap

    def _utility_evidence(self, report) -> list:
        """The boundary's ABSTRACT evidence for the PolicyMutator (plan 14
        §5.4): Task 06 ``abstract_view`` dicts + the governance report's
        reliability entries. Raw attack text never reaches it, and the
        frontier's current SCORES are deliberately not an input — a policy
        tuned to flatter the nodes it already produced is collusive
        co-evolution (P2)."""
        out = list(self._abstract_failure_summaries())
        try:
            entries = getattr(report, "reliability", None) or ()
            for entry in entries:
                out.append(
                    dict(entry) if isinstance(entry, dict)
                    else dict(getattr(entry, "to_dict", lambda: {})())
                )
        except Exception:
            log.warning("reliability evidence unreadable (proposer continues "
                        "on failure summaries alone)", exc_info=True)
        return out

    # ── Task 10: frontier repair + selective erasure (boundary window) ─

    @property
    def frontier_repair(self):
        """Lazily constructed
        :class:`ari.rqgm.frontier_repair.FrontierRepairEngine` (plan 10
        §5.7): built only under ``ari_rqgm``, and only when
        ``rqgm.frontier_repair.enabled`` (default true). ``None`` when
        disabled or construction fails."""
        if self._frontier_repair is None:
            fr_cfg = getattr(getattr(self.cfg, "rqgm", None),
                             "frontier_repair", None)
            if fr_cfg is not None and not bool(
                getattr(fr_cfg, "enabled", True)
            ):
                return None
            try:
                from ari.rqgm.frontier_repair import FrontierRepairEngine
                from ari.rqgm.store import ImmutableAuditLog

                self._frontier_repair = FrontierRepairEngine(
                    cfg=fr_cfg,
                    kernel=self.kernel,
                    audit_log=ImmutableAuditLog(self.checkpoint_dir),
                    enforcement=self.kernel_enforcement,
                )
            except Exception:
                log.warning("FrontierRepairEngine construction failed",
                            exc_info=True)
        return self._frontier_repair

    def _run_frontier_repair(self, transition, state, ckpt,
                             search_state: "dict | None") -> None:
        """Best-effort repair pass inside the boundary window (plan 10
        §5.2/§5.6). No-op without retirements or without the run loop's
        search state. A ``halted_expansion`` outcome raises the
        ``expansion_halted`` flag the loop reads (drain-only degradation) —
        the run itself never crashes."""
        posture = self._paper_ablation_posture()
        if posture is not None and not posture.selective_erasure:
            return
        if search_state is None:
            return
        if not (getattr(transition, "retirements", None) or ()):
            return
        engine = self.frontier_repair
        if engine is None:
            return
        try:
            epoch = getattr(state, "epoch", None)
            result = engine.repair(
                transition=transition,
                frontier=search_state.get("frontier", []),
                pending=search_state.get("pending", []),
                all_nodes=search_state.get("all_nodes", []),
                checkpoint_dir=ckpt,
                bfts_cfg=getattr(self.cfg, "bfts", None),
                epoch_id=str(getattr(epoch, "epoch_id", "") or ""),
                # #77: the newly-frozen epoch's sealed utility policy so repair
                # re-weights the tree under the NEW criterion rather than only
                # invalidating it. state == applied.state (RqgmRuntimeState);
                # state.epoch is the new EpochState carrying utility_policy.
                new_utility_policy=dict(
                    getattr(epoch, "utility_policy", None) or {}
                ),
            )
            if result.status == "halted_expansion":
                self.expansion_halted = True
            if result.status != "noop":
                flush = search_state.get("flush_tree")
                if callable(flush):
                    flush()
        except Exception:
            log.warning("frontier repair pass failed (boundary continues)",
                        exc_info=True)

    # ── Task 11: meta-agent evolution (boundary window) ──────────────

    @property
    def meta_evolution(self):
        """Lazily constructed
        :class:`ari.rqgm.meta_evolution.MetaEvolutionCoordinator`
        (plan 11 §5.4): non-evolving, fixed-tier trust, constructed only
        under ``ari_rqgm``. ``None`` when the kernel is unavailable —
        every meta output must be kernel-gated (invariant 18).

        Constructed WITH the live invoker map (the final wiring gap fix:
        the v10 audit showed every registered+active meta agent skipping
        on ``no invoker registered`` because the runtime built the
        coordinator without invokers)."""
        if self._meta_evolution is None and self.kernel is not None:
            try:
                from ari.rqgm.meta_evolution import MetaEvolutionCoordinator
                from ari.rqgm.store import ImmutableAuditLog

                self._meta_evolution = MetaEvolutionCoordinator(
                    getattr(self.cfg, "rqgm", None),
                    self.kernel,
                    audit_log=ImmutableAuditLog(self.checkpoint_dir),
                    checkpoint_dir=self.checkpoint_dir,
                    invokers=self._meta_invokers(),
                )
            except Exception:
                log.warning("MetaEvolutionCoordinator construction failed",
                            exc_info=True)
        return self._meta_evolution

    def _run_meta_evolution(self, report) -> None:
        """Best-effort meta-tier step inside the boundary window (plan 11
        §5.4). Skipped under the governance-suspended carry-over; a failure
        never delays the boundary or the run.

        Always audit-visible: every boundary leaves either the
        coordinator's own ``meta_evolution`` / ``meta_evolution_skipped``
        line or a runtime-level ``meta_evolution`` line carrying the skip
        or failure reason (the silent-enabled-path gap fix — the B8 v9
        boundary ran with meta enabled yet emitted nothing).
        """
        st = self._epoch_state
        epoch_id = str(
            getattr(getattr(st, "epoch", None), "epoch_id", "") or ""
        )
        if self.governance_suspended:
            self._append_audit_event("meta_evolution", {
                "epoch_id": epoch_id,
                "outcome": "skipped",
                "reason": "governance_suspended",
            })
            return
        coordinator = self.meta_evolution
        if coordinator is None or st is None or st.epoch is None:
            self._append_audit_event("meta_evolution", {
                "epoch_id": epoch_id,
                "outcome": "skipped",
                "reason": (
                    "no MetaEvolutionCoordinator (kernel unavailable or "
                    "construction failed)"
                    if coordinator is None else "no open epoch"
                ),
            })
            return
        try:
            coordinator.run_epoch_boundary_step(
                epoch_state=st.epoch,
                governance_report=report,
                components=st.components,
                prompts=st.prompts,
                replay_pool=self.adversarial_pool,
            )
        except Exception as exc:
            log.warning("meta-evolution step failed (fail-open)",
                        exc_info=True)
            self._append_audit_event("meta_evolution", {
                "epoch_id": epoch_id,
                "outcome": "failed",
                "reason": f"{type(exc).__name__}: {exc}",
            })

    def _meta_invokers(self) -> dict:
        """Deterministic invoker map for the registered+active meta roles
        that have a LIVE actor today (plan 11 §5.4 — the final wiring gap
        fix: without this map every boundary skipped every meta agent with
        ``no invoker registered``).

        Shape: ``role -> callable(inputs, prompt_view=None) -> dict|None``
        (the coordinator's injectable-invoker seam; tests may still inject
        deterministic fakes through the coordinator directly). Only roles
        with a real actor appear here — ``prompt_mutator`` (delegates to
        :class:`ari.rqgm.prompt_evolution.PromptMutator`),
        ``clean_room_generator`` (a reached deterministic no-op that
        defers to the Task 08 boundary pass), and the plan-11 §5.2
        recommendation roles ``replay_selector`` / ``failure_summary_``
        ``compressor``, whose actors are pure functions of the epoch's
        abstract inputs. Any other registered+active meta role keeps the
        coordinator's explicit ``no invoker`` skip line — actors are never
        faked.

        Division of labor with the plan-07 boundary path (no
        double-generation): ``_generate_prompt_candidates`` (FIX-A)
        remains the pre-audit candidate-minting authority under the
        ``rqgm.prompt_evolution`` caps, riding ``candidate_evaluations``
        into the SAME epoch's audit. The meta channel here is the meta
        agent's OWN per-epoch proposal (plan 11 budget:
        ``rqgm.meta_evolution.max_meta_candidates_per_epoch``), routed
        post-audit through the coordinator's kernel-gated forwarding into
        the Task 07 intake at ``status: candidate``. The two channels can
        never mint the same record: both dedup by the deterministic
        candidate id (``format_prompt_id(role, version+1)``), and the meta
        invoker skips every role whose successor id already exists.
        """
        return {
            "prompt_mutator": self._invoke_prompt_mutator,
            "clean_room_generator": self._invoke_clean_room_generator,
            "replay_selector": self._invoke_replay_selector,
            "failure_summary_compressor":
                self._invoke_failure_summary_compressor,
        }

    def _meta_channel_budget(self) -> int:
        """``rqgm.meta_evolution.max_meta_candidates_per_epoch`` (the same
        duck-typed read the coordinator applies), ≥ 0."""
        me = getattr(getattr(self.cfg, "rqgm", None), "meta_evolution", None)
        if isinstance(me, dict):
            raw = me.get("max_meta_candidates_per_epoch", 1)
        else:
            raw = getattr(me, "max_meta_candidates_per_epoch", 1)
        try:
            return max(0, int(raw))
        except (TypeError, ValueError):
            return 1

    def _meta_candidates_emitted(self, ckpt, epoch_id: str):
        """Resume-safe floor from ``rqgm_meta_outputs.jsonl`` mirroring the
        coordinator's ``_candidates_already_emitted``: ``(total non-shadow
        recorded candidate-kind outputs this epoch, whether the
        PromptMutator already emitted one)``. In-memory state is never
        relied on — a crashed boundary window re-runs against the log."""
        from ari.rqgm.meta_evolution import load_meta_outputs_log

        total = 0
        mutator_done = False
        for rec in load_meta_outputs_log(ckpt):
            if (
                str(rec.get("epoch_id", "")) == epoch_id
                and str(rec.get("status", "")) == "recorded"
                and str(rec.get("output_kind", "")) in (
                    "prompt_candidate", "clean_room_candidate"
                )
                and not rec.get("shadow", False)
            ):
                total += 1
                if str(rec.get("component_id", "")) == \
                        self.PROMPT_MUTATOR_ID:
                    mutator_done = True
        return total, mutator_done

    def _invoke_prompt_mutator(self, inputs, prompt_view=None):
        """Live ``prompt_mutator`` invoker (plan 11 §5.4).

        One deterministic proposal per epoch: the first (sorted) evolvable
        role with an ACTIVE incumbent whose successor candidate id does
        NOT already exist in the Task 07 log — i.e. the highest-priority
        role the plan-07 boundary path left uncovered this epoch. The
        mutation kind uses the SAME degrade ladder as FIX-A
        (``_select_mutation_kind``: LLM-less knob kinds when ``self.llm``
        is ``None`` or the governance call budget is exhausted, the first
        configured LLM kind otherwise, knob fallback on LLM decline). The
        returned dict is inert — the coordinator records, kernel-gates and
        routes it (invariants 15/18: this method never writes a registry
        or the audit log).

        Deterministic no-ops (``None``): no open epoch/checkpoint, the
        Task 07 intake disabled (``rqgm.prompt_evolution.enabled=false``,
        the ``_process_clean_room`` precedent), the plan-11 budget already
        consumed this epoch (resume idempotency: a re-run boundary window
        finds this channel's output on disk and stands down), no permitted
        mutation kind, or every role already covered.
        """
        st = self._epoch_state
        ckpt = self.checkpoint_dir
        if st is None or st.epoch is None or ckpt is None:
            return None
        if not self._prompt_evolution_enabled():
            return None
        epoch_id = str(st.epoch.epoch_id or "")
        emitted, mutator_done = self._meta_candidates_emitted(ckpt, epoch_id)
        if mutator_done or emitted >= self._meta_channel_budget():
            return None
        from ari.rqgm.events import ACTIVE_STATUSES, format_prompt_id
        from ari.rqgm.prompt_evolution import PromptMutator
        from ari.rqgm.prompt_records import load_prompt_evolution_log

        records = load_prompt_evolution_log(ckpt)
        existing_ids = {
            str(r.get("candidate_id", ""))
            for r in records
            if r.get("record_type") == "prompt_candidate"
        }
        seq = sum(
            1 for r in records
            if str(r.get("record_id", "")).startswith("pcand_")
        )
        incumbents = self._active_evolvable_incumbents(st, ckpt, records)
        if prompt_view is not None:
            # Handoff parity with the coordinator's no-handle views: only
            # roles visibly ACTIVE in the filtered view are targeted.
            view_roles = {
                v.role
                for v in getattr(prompt_view, "entries", ()) or ()
                if getattr(v, "status", "") in ACTIVE_STATUSES
            }
            incumbents = {
                role: v for role, v in incumbents.items()
                if role in view_roles
            }
        kind, llm_backed = self._select_mutation_kind()
        if kind is None:
            return None
        mutator = PromptMutator(
            self.PROMPT_MUTATOR_ID,
            llm=self._mutator_llm_callable(),
            checkpoint_dir=ckpt,
        )
        # Coordinator-filtered abstract failure views only (M7): the input
        # bundle is the invoker's sole failure-signal source.
        failure_summaries = (
            list(inputs.get("failure_summaries") or ())
            if isinstance(inputs, dict) else []
        )
        for role in sorted(incumbents):
            incumbent, incumbent_text = incumbents[role]
            candidate_id = format_prompt_id(role, int(incumbent.version) + 1)
            if candidate_id in existing_ids:
                # Cross-channel dedup by the deterministic candidate id:
                # FIX-A (or an earlier epoch) already minted this
                # successor — the meta channel never duplicates it.
                continue
            candidate = self._propose_candidate(
                mutator, role, incumbent, incumbent_text, kind,
                failure_summaries, epoch_id=epoch_id, record_seq=seq,
                records=None, cfg=self.cfg,
            )
            if candidate is None and llm_backed:
                knob = tuple(
                    k for k in self._configured_mutation_kinds()
                    if k in self._KNOB_MUTATION_KINDS
                )
                if knob:
                    candidate = self._propose_candidate(
                        mutator, role, incumbent, incumbent_text, knob[0],
                        failure_summaries, epoch_id=epoch_id,
                        record_seq=seq, records=None, cfg=self.cfg,
                    )
            if candidate is None:
                continue
            return {
                "output_kind": "prompt_candidate",
                "target_role": role,
                "expected_improvement": (
                    f"boundary {candidate.mutation_kind} proposal for "
                    f"uncovered role {role!r}"
                ),
                "candidate": candidate.to_dict(),
                "source_refs": [candidate.record_id],
            }
        return None

    def _invoke_clean_room_generator(self, inputs, prompt_view=None):
        """Live ``clean_room_generator`` invoker: a REACHED deterministic
        no-op (plan 11 §5.4).

        The clean-room generator's live actor is the Task 08 boundary pass
        (:meth:`_process_clean_room`, right after the committed apply):
        retirement requests are persisted, budget-capped, kernel
        pre/post-screened and handed to the Task 07 intake at
        ``status: candidate`` THERE. Re-driving a generation here would
        emit the same candidate through two channels (the
        double-generation hazard this wiring explicitly resolves), and
        with no retirement pending there is nothing to regenerate — so
        this invoker always returns ``None``. Its purpose is to prove the
        role is reached: the coordinator logs an ``empty output`` skip
        instead of the old ``no invoker registered`` gap.
        """
        return None

    # ── plan 11 §5.2 items 3-4: the recommendation roles ─────────────
    #
    # Both were role-vocabulary entries with a capability-matrix row and
    # nothing behind them: no founding prompt, no founding component, no
    # invoker. They are deliberately the SIMPLEST kind of meta agent —
    # pure functions of the abstract input bundle, no LLM, no clock, no
    # randomness (P2: byte-identical re-runs). Neither can affect this
    # epoch: ``_route_output`` returns their output as inert data, and the
    # replay board unions the mandated minimum set regardless of what the
    # selector recommends.
    #
    # The degrade ladder mirrors the PolicyMutator's (plan 14): the
    # deterministic computation is the DEFAULT and the only path a run
    # without an LLM ever takes, so a default boundary stays byte-identical
    # across re-runs (P2). When an LLM IS configured the role's committed
    # template drives it, and a reply that fails its founding output_schema
    # degrades back to the deterministic answer rather than emitting
    # nothing. That is what makes the prompt bytes load-bearing — a
    # registered template no code ever renders would be governance
    # vocabulary again, just one layer down.

    def _meta_recommendation_reply(self, prompt_key: str, inputs: dict,
                                   role: str):
        """Render *prompt_key* with the bundle and return the parsed reply.

        ``None`` on every failure path (no LLM, empty reply, non-conforming
        reply) — the caller then keeps its deterministic result. Literal
        prompt keys are passed in by the two call sites below so the
        reference analyzer sees the template edge statically (the
        ``PolicyMutator._meta_prompt`` convention).
        """
        llm = getattr(self, "llm", None)
        if llm is None:
            return None
        try:
            import json as _json

            from ari.prompts import FilesystemPromptLoader
            from ari.rqgm.clean_room import role_output_schema
            from ari.rqgm.events import canonical_json
            from ari.rqgm.prompt_evolution import check_output_against_schema

            template = FilesystemPromptLoader().load(prompt_key)
            rendered = template.format(
                bundle_json=canonical_json(inputs or {})
            )
            reply = llm.complete([{"role": "user", "content": rendered}],
                                 require_tool=False)
            text = getattr(reply, "content", reply) or ""
            if check_output_against_schema(str(text), role_output_schema(role)):
                return None
            return _json.loads(str(text))
        except Exception:
            log.warning("meta recommendation LLM path failed for %s; "
                        "falling back to the deterministic result", role,
                        exc_info=True)
            return None

    @staticmethod
    def _replay_case_id(summary: dict, index: int) -> str:
        """The case id for one abstract failure summary.

        ``abstract_view`` (``adversarial/records.build_failure_summary``)
        carries no ``case_id`` — it is deliberately the contamination-safe
        projection. When the bundle does carry one, use it; otherwise fall
        back to a stable positional id so a recommendation is still
        checkable against the bundle it came from. Ids the pool does not
        recognise are simply not replayed, so a wrong guess here degrades
        to "no recommendation", never to a wrong replay set.
        """
        for key in ("case_id", "id"):
            val = summary.get(key)
            if isinstance(val, str) and val:
                return val
        return f"case_{index:04d}"

    def _invoke_replay_selector(self, inputs, prompt_view=None):
        """Live ``replay_selector`` invoker (plan 11 §5.2 item 3).

        Recommends replay cases from the bundle's abstract failure
        summaries, breadth first: one case per distinct ``case_type`` in
        the bundle's own order, then a second pass for the remainder. That
        is the same breadth-before-depth property as
        ``AdversarialReplayPool.select_for_replay``'s round-robin, computed
        over the abstract projection the meta tier is allowed to read (the
        pool's own selector sorts by severity and recency, fields
        ``abstract_view`` does not expose — this recommendation is a
        complement to it, not a replacement).

        Note what the ordering does and does not buy: ``_route_output``
        SORTS the returned ids, so the order here is discarded. What
        survives is the SET — breadth-first decides which ids remain after
        the cap truncates, which is the whole point. With five overclaim
        cases ahead of one metric_gaming and one prior_art, a cap of 3
        yields three distinct case types where taking the first three
        would yield three identical ones.

        Non-binding by construction. Returns ``None`` (a reached no-op)
        when the bundle carries no summaries.
        """
        summaries = [s for s in (inputs or {}).get("failure_summaries") or ()
                     if isinstance(s, dict)]
        if not summaries:
            return None
        cap = self._replay_recommendation_cap()
        seen_types: set[str] = set()
        first_pass: list[str] = []
        rest: list[str] = []
        for i, summary in enumerate(summaries):
            case_type = str(summary.get("case_type", ""))
            target = first_pass if case_type not in seen_types else rest
            seen_types.add(case_type)
            target.append(self._replay_case_id(summary, i))
        case_ids = (first_pass + rest)[:cap]

        # Literal key (== the FOUNDING_PROMPT_TABLE row) so the reference
        # analyzer resolves the template edge statically.
        reply = self._meta_recommendation_reply(
            "rqgm/replay_selector", inputs, "replay_selector"
        )
        if isinstance(reply, dict):
            known = {self._replay_case_id(s, i)
                     for i, s in enumerate(summaries)}
            # An id the bundle does not contain is discarded, not trusted:
            # the recommendation is checkable against its own inputs.
            chosen = [str(c) for c in reply.get("replay_case_ids") or ()
                      if str(c) in known]
            if chosen:
                case_ids = chosen[:cap]
        return {
            "output_kind": "replay_case_recommendation",
            "replay_case_ids": case_ids,
        }

    def _replay_recommendation_cap(self) -> int:
        """``rqgm.replay.max_cases_per_epoch`` — the same bound the
        adjudication board applies, so the recommendation can never be
        longer than the set that could be replayed anyway. Duck-typed with
        the module default; a non-numeric value degrades to it rather than
        raising inside the boundary window."""
        replay = getattr(getattr(self.cfg, "rqgm", None), "replay", None)
        if isinstance(replay, dict):
            raw = replay.get("max_cases_per_epoch", 3)
        else:
            raw = getattr(replay, "max_cases_per_epoch", 3)
        try:
            return max(0, int(raw))
        except (TypeError, ValueError):
            return 3

    def _invoke_failure_summary_compressor(self, inputs, prompt_view=None):
        """Live ``failure_summary_compressor`` invoker (plan 11 §5.2 item 4).

        Compresses the epoch's abstract failure summaries into ONE summary
        per invocation: the most frequent ``case_type`` in the bundle
        (ties broken by first appearance, so the result is a pure function
        of bundle order), with the union of that type's affected roles.

        The output reuses the committed ``FailureSummary`` field set
        (``adversarial/records.FailureSummary``) rather than inventing a
        shape, so what this emits is interchangeable with what
        ``build_failure_summary`` emits — which is what
        ``records.FailureSummary``'s own docstring means by "Task 11
        upgrades the compressor".

        Contamination safety is structural, not promised: the inputs are
        already ``abstract_view`` projections (``assemble_filtered_inputs``
        →``_abstract_failure_summaries``), so there is no raw attack,
        defense, or prompt text in scope to leak. Returns ``None`` when the
        bundle carries no summaries.
        """
        summaries = [s for s in (inputs or {}).get("failure_summaries") or ()
                     if isinstance(s, dict)]
        if not summaries:
            return None
        order: list[str] = []
        counts: dict[str, int] = {}
        for summary in summaries:
            case_type = str(summary.get("case_type", ""))
            if case_type not in counts:
                counts[case_type] = 0
                order.append(case_type)
            counts[case_type] += 1
        # max() over the first-appearance order is stable: equal counts keep
        # the earlier type, so the result never depends on dict iteration.
        dominant = max(order, key=lambda t: counts[t])
        members = [s for s in summaries
                   if str(s.get("case_type", "")) == dominant]
        roles: list[str] = []
        for summary in members:
            for role in summary.get("affected_roles") or ():
                if str(role) not in roles:
                    roles.append(str(role))
        patterns = [str(s.get("failure_pattern", "")) for s in members
                    if s.get("failure_pattern")]
        expectations = [str(s.get("violated_expectation", ""))
                        for s in members if s.get("violated_expectation")]

        # Literal key (== the FOUNDING_PROMPT_TABLE row); see above.
        reply = self._meta_recommendation_reply(
            "rqgm/failure_summary_compressor", inputs,
            "failure_summary_compressor",
        )
        if isinstance(reply, dict):
            summary = reply.get("failure_summary")
            if isinstance(summary, dict) and summary.get("case_type"):
                # ``occurrences`` stays OURS: it is a count over the bundle,
                # not a judgement, and a model-supplied count would be an
                # unverifiable number in a governance record.
                return {
                    "output_kind": "failure_summary",
                    "failure_summary": {
                        "case_type": str(summary.get("case_type", "")),
                        "failure_pattern": str(
                            summary.get("failure_pattern", "")),
                        "violated_expectation": str(
                            summary.get("violated_expectation", "")),
                        "affected_roles": sorted(
                            str(r) for r in
                            summary.get("affected_roles") or ()
                        ),
                        "occurrences": len(members),
                    },
                }
        return {
            "output_kind": "failure_summary",
            "failure_summary": {
                "case_type": dominant,
                # The members of one case_type share a template-filled
                # pattern today, so the first is representative rather than
                # arbitrary; recorded here so a later divergence is visible
                # instead of silently dropping the others.
                "failure_pattern": patterns[0] if patterns else "",
                "violated_expectation": (
                    expectations[0] if expectations else ""
                ),
                "affected_roles": sorted(roles),
                "occurrences": len(members),
            },
        }

    # ── Task 08: clean-room regeneration (boundary window) ───────────

    def _process_clean_room(self, transition, state, ckpt) -> None:
        """Best-effort clean-room pass (plan 08 §5.1/§5.3): persist the
        transition's requests, execute up to the per-epoch budget with the
        kernel's pre/post screens, hand admissible candidates to the Task 07
        lifecycle at ``status=candidate``. Fail-open — a failure here never
        delays the boundary or the run."""
        try:
            pe = getattr(getattr(self.cfg, "rqgm", None),
                         "prompt_evolution", None)
            if pe is not None and not bool(getattr(pe, "enabled", True)):
                return
            from ari.rqgm.clean_room import CleanRoomCoordinator

            if self._clean_room is None:
                self._clean_room = CleanRoomCoordinator(
                    getattr(self.cfg, "rqgm", None), self.kernel,
                    llm=self.llm, checkpoint_dir=ckpt,
                )
            epoch = getattr(state, "epoch", None)
            summaries = []
            pool = self.adversarial_pool
            if pool is not None:
                try:
                    summaries = [
                        dict(c.get("abstract_view") or {})
                        for c in pool.cases()
                    ]
                except Exception:
                    summaries = []
            self._clean_room.process_boundary(
                transition,
                epoch_id=getattr(epoch, "epoch_id", "") or "",
                prompts=getattr(state, "prompts", None),
                failure_summaries=summaries,
            )
        except Exception:
            log.warning("clean-room boundary pass failed (fail-open)",
                        exc_info=True)

    # ── Task 06: adversarial loop (per-node round + replay pool) ──────

    def _adversarial_enabled(self) -> bool:
        adv = getattr(getattr(self.cfg, "rqgm", None), "adversarial", None)
        if isinstance(adv, dict):
            return bool(adv.get("enabled", True))
        return bool(getattr(adv, "enabled", True)) if adv is not None else True

    @property
    def adversarial(self):
        """Lazily constructed
        :class:`ari.rqgm.adversarial.AdversarialRound` (plan 06 §5.1/§7).

        ``None`` without a checkpoint dir or with
        ``rqgm.adversarial.enabled: false`` (the adapter-never-initialized
        guarantee). Construction failure degrades to ``None`` — the run
        loop's hook is best-effort.
        """
        if self._adversarial is None:
            if self.checkpoint_dir is None or not self._adversarial_enabled():
                return None
            try:
                from ari.rqgm.adversarial import AdversarialRound

                self._adversarial = AdversarialRound(
                    getattr(getattr(self.cfg, "rqgm", None), "adversarial",
                            None),
                    llm=self.llm,
                    # Without this the actors load the COMMITTED template and
                    # an adopted evolved prompt is never rendered.
                    loader=self.governed_loader,
                    checkpoint_dir=self.checkpoint_dir,
                    epoch_state=lambda: self.current_epoch,
                    # Task 12 §5.4: per-role epoch caps gate defender/judge
                    # inside the round (decision-point, degrade-never-block).
                    budget_manager=self.budget_manager,
                    governance_cfg=getattr(getattr(self.cfg, "rqgm", None),
                                           "governance", None),
                )
            except Exception:
                log.warning("AdversarialRound construction failed",
                            exc_info=True)
        return self._adversarial

    @property
    def adversarial_pool(self):
        """Lazily loaded :class:`ari.rqgm.adversarial.AdversarialReplayPool`
        (snapshot + JSONL replay; ``None`` when the loop is disabled)."""
        if self._adversarial_pool is None:
            if self.checkpoint_dir is None or not self._adversarial_enabled():
                return None
            try:
                from ari.rqgm.adversarial import AdversarialReplayPool

                self._adversarial_pool = AdversarialReplayPool.load(
                    self.checkpoint_dir,
                    getattr(getattr(self.cfg, "rqgm", None), "adversarial",
                            None),
                )
            except Exception:
                log.warning("AdversarialReplayPool load failed", exc_info=True)
        return self._adversarial_pool

    def run_per_node_kernel_check(self, node) -> int:
        """The §5.6.5 per-node kernel warn hook. Returns the report count.

        ``per_node_warn_check`` — schema + hash provenance over the records a
        node produced, warn-only, audit-logged — had NO production caller, so
        CK-HSH-001/002/003/010 were never evaluated at the one point a node's
        records exist. Fail-open like every run-loop hook.
        """
        kernel = self.kernel
        st = self._epoch_state
        if kernel is None or st is None:
            return 0
        node_id = str(getattr(node, "id", "") or "")
        if not node_id:
            return 0
        try:
            from ari.rqgm.adversarial.pool import (
                ROUND_MARKER_RECORD_TYPE,
                AdversarialCaseLog,
            )
            from ari.rqgm.kernel import per_node_warn_check
            from ari.rqgm.store import ImmutableAuditLog

            audit = ImmutableAuditLog(self.checkpoint_dir)
            # The node's RQGM RECORDS — not audit-log entries. This hook feeds
            # ``validate_record_schema`` + ``validate_hashes``, which require the
            # ``rqgm_record_base`` envelope (record_id / component_id /
            # prompt_hash / role / …) at the TOP level. An audit entry is a
            # different shape entirely ({event_id, event_type, payload, …}) and
            # carries NONE of those, so feeding the audit log made CK-SCH-N01
            # fire on every node of every run — a standing false positive that
            # trains a reader to ignore the one code that flags a malformed
            # governed record. Round MARKERS are idempotency bookkeeping, not
            # governed records, and are excluded for the same reason.
            records = [
                r for r in (AdversarialCaseLog.read(self.checkpoint_dir) or ())
                if isinstance(r, dict)
                and str(r.get("node_id", "")) == node_id
                and str(r.get("record_type", "")) != ROUND_MARKER_RECORD_TYPE
            ]
            if not records:
                return 0
            reports = per_node_warn_check(
                kernel, records, registry=getattr(st, "prompts", None),
                audit_log=audit,
            )
            return len(reports or ())
        except Exception:
            log.warning("per-node kernel check failed (fail-open)",
                        exc_info=True)
            return 0

    def check_epoch_invariance(self) -> int:
        """Run ``validate_epoch_invariance`` over the epoch's event log
        (plan 04 §5.4 item 4). Returns the violation count; never raises.

        CK-EPO-001/002 — a record scored under a prompt outside the frozen
        active set, and an out-of-band status change inside an epoch — were
        never evaluated because nothing called this validator.
        """
        kernel = self.kernel
        st = self._epoch_state
        if kernel is None or st is None or st.epoch is None:
            return 0
        try:
            from ari.rqgm.store import ImmutableAuditLog

            # The validator has TWO halves and they take different shapes:
            # items carrying `event_type` are EVENTS (CK-EPO-002, out-of-band
            # status change), items carrying a top-level `record_id` are
            # RECORDS (CK-EPO-001, scored under a hash outside the frozen
            # set). Audit-log reads are event-shaped only, so passing them
            # alone would leave the record half permanently unevaluated —
            # the check would run and find nothing, forever.
            from ari.rqgm.frontier_repair import load_rqgm_records

            event_log = list(ImmutableAuditLog.read(self.checkpoint_dir) or [])
            try:
                event_log += list(load_rqgm_records(self.checkpoint_dir) or [])
            except Exception:
                log.debug("record load for epoch invariance failed",
                          exc_info=True)
            report = kernel.validate_epoch_invariance(st.epoch, event_log)
            violations = list(getattr(report, "violations", ()) or ())
            if violations:
                self._append_audit_event(
                    "kernel_report",
                    {
                        "epoch_id": str(getattr(st.epoch, "epoch_id", "")),
                        "check": "epoch_invariance",
                        "codes": sorted({v.code for v in violations}),
                    },
                )
                log.warning("epoch invariance violations: %s",
                            sorted({v.code for v in violations}))
            return len(violations)
        except Exception:
            log.warning("epoch invariance check failed (fail-open)",
                        exc_info=True)
            return 0

    @property
    def governed_loader(self):
        """The epoch-frozen :class:`GovernedPromptLoader`, or ``None``.

        The governed actors (adversary / defender / judge) were constructed
        with ``loader=None``, so they fell back to ``FilesystemPromptLoader``
        and read the COMMITTED TEMPLATE off disk — meaning an ADOPTED evolved
        prompt was never rendered and prompt evolution had no effect on their
        behaviour at all. This loader resolves governed keys through the
        epoch-frozen PromptSpec view and degrades byte-identically to the
        filesystem for ungoverned keys.
        """
        st = self._epoch_state
        if st is None or getattr(st, "prompts", None) is None:
            return None
        try:
            from types import SimpleNamespace

            from ari.rqgm.prompt_loader import (
                ACTIVE_STATUSES,
                POLICY_TEMPLATE_REF_KIND,
                GovernedPromptLoader,
            )

            # The registry and the loader speak DIFFERENT source vocabularies:
            # entries carry `source.kind` in {committed_template,
            # checkpoint_file, policy} while the loader reads
            # `template_ref.kind` in {package, checkpoint}. Bridge them here
            # rather than teaching either side the other's words. A `policy`
            # body is never RENDERED, so it is filtered out (plan 14 §5.3).
            _KIND = {"committed_template": "package",
                     "checkpoint_file": "checkpoint"}
            view: dict = {}
            for entry in (st.prompts.entries() or {}).values():
                if str(getattr(entry, "status", "")) not in ACTIVE_STATUSES:
                    continue
                source = dict(getattr(entry, "source", None) or {})
                kind = str(source.get("kind", ""))
                if kind == POLICY_TEMPLATE_REF_KIND:
                    continue
                mapped = _KIND.get(kind)
                if mapped is None:
                    continue
                key = str(source.get("key") or source.get("path") or "")
                if not key:
                    continue
                view[key] = SimpleNamespace(
                    template_ref={"kind": mapped, "key": key},
                    prompt_id=str(getattr(entry, "prompt_id", "")),
                    prompt_hash=str(getattr(entry, "prompt_hash", "") or ""),
                    status=str(getattr(entry, "status", "")),
                )
            if not view:
                return None
            return GovernedPromptLoader(
                view, checkpoint_dir=self.checkpoint_dir,
            )
        except Exception:
            log.warning("governed prompt loader unavailable; the committed "
                        "templates stay authoritative", exc_info=True)
            return None

    @property
    def validation_pipeline(self):
        """The lazily-built :class:`CandidateValidationPipeline` (plan 07 §5.3).

        It carries the shadow budget, the deterministic sampler and the
        observation chain, and persists every record to the prompt-evolution
        log. Nothing constructed it in production, so the whole shadow stage was
        unreachable.
        """
        if getattr(self, "_validation_pipeline", None) is None:
            try:
                from ari.rqgm.prompt_evolution import CandidateValidationPipeline

                self._validation_pipeline = CandidateValidationPipeline(
                    checkpoint_dir=self.checkpoint_dir,
                    cfg=self.cfg,
                    llm=self.llm,
                )
            except Exception:
                log.warning("candidate validation pipeline unavailable",
                            exc_info=True)
                self._validation_pipeline = None
        return self._validation_pipeline

    def shadow_evidence(self, prompt_hash: str, candidate_id: str = "") -> dict:
        """``{shadow_samples, shadow_score}`` for one candidate, aggregated from
        its LIVE ``ComparisonObservation`` chain (plan 07 §5.3 stage 6).

        ``shadow_score`` is the AGREEMENT RATE with the incumbent across the
        sampled live invocations. It is consumed ONLY by the T6 adoption gate —
        never by BFTS scoring, node metrics or the frontier, which is the
        observation-only contract the observation record itself states. Absent
        observations yield ``{0, None}``: honestly no basis, never a stand-in
        number, so T6 simply does not open.
        """
        pipeline = self.validation_pipeline
        if pipeline is None:
            return {"shadow_samples": 0, "shadow_score": None}
        try:
            obs = [
                r for r in pipeline.records()
                if r.get("record_type") == "comparison_observation"
                and (
                    (candidate_id and r.get("candidate_id") == candidate_id)
                    or (prompt_hash and r.get("prompt_hash") == prompt_hash)
                )
            ]
        except Exception:
            return {"shadow_samples": 0, "shadow_score": None}
        if not obs:
            return {"shadow_samples": 0, "shadow_score": None}
        agreed = sum(
            1 for r in obs if bool((r.get("divergence") or {}).get("agreed"))
        )
        return {
            "shadow_samples": len(obs),
            "shadow_score": round(agreed / len(obs), 6),
        }

    def run_shadow_comparison(self, node, *, input_context: str = "") -> int:
        """LIVE shadow: run each ``shadow``-status candidate ALONGSIDE the
        incumbent on the SAME live input and record the side-by-side.

        Returns the number of observations recorded. Never raises.

        The candidate's output goes ONLY into the ``ComparisonObservation``
        (hashes + divergence) — never into node metrics, the frontier, memory,
        or any BFTS score. It informs the ADOPTION decision (T6) and nothing
        else. Sampling and the per-epoch call cap are the existing
        ``should_shadow`` / ``shadow_budget_left`` rules, so
        ``rqgm.shadow.enabled: false`` zeroes this path entirely.
        """
        pipeline = self.validation_pipeline
        st = self._epoch_state
        if pipeline is None or st is None or st.epoch is None or self.llm is None:
            return 0
        epoch_id = str(getattr(st.epoch, "epoch_id", "") or "")
        node_id = str(getattr(node, "id", "") or "")
        if not epoch_id or not node_id:
            return 0
        try:
            if not pipeline.should_shadow(epoch_id, node_id):
                return 0
        except Exception:
            return 0
        recorded = 0
        try:
            from ari.rqgm.prompt_evolution import candidate_from_dict

            cand_records = {
                str(r.get("prompt_hash") or r.get("candidate_id")): r
                for r in pipeline.records()
                if r.get("record_type") == "prompt_candidate"
            }
            active = getattr(st.epoch, "active_prompt_hashes", None) or {}
            for pid, entry in (st.prompts.entries() or {}).items():
                if str(getattr(entry, "status", "")) != "shadow":
                    continue
                if pipeline.shadow_budget_left(epoch_id) <= 0:
                    break
                role = str(getattr(entry, "role", "") or "")
                rec = cand_records.get(str(getattr(entry, "prompt_hash", "")))
                cand = candidate_from_dict(rec) if rec else None
                if cand is None:
                    continue
                cand_text, _ = st.prompts.resolve_text(
                    pid, checkpoint_dir=self.checkpoint_dir,
                )
                inc_id = str(active.get(role, "") or "")
                inc_text = ""
                for ipid, ientry in (st.prompts.entries() or {}).items():
                    if (str(getattr(ientry, "role", "")) == role
                            and str(getattr(ientry, "status", "")) == "active"):
                        inc_text, _ = st.prompts.resolve_text(
                            ipid, checkpoint_dir=self.checkpoint_dir,
                        )
                        inc_id = inc_id or str(ipid)
                        break
                if not cand_text or not inc_text:
                    continue
                cand_out = self._shadow_complete(cand_text, input_context)
                inc_out = self._shadow_complete(inc_text, input_context)
                if cand_out is None or inc_out is None:
                    continue
                pipeline.record_shadow_observation(
                    cand, inc_id, node_id=node_id,
                    input_context=input_context,
                    candidate_output=cand_out,
                    incumbent_output=inc_out,
                    divergence={"agreed": cand_out.strip() == inc_out.strip()},
                )
                recorded += 1
        except Exception:
            log.warning("live shadow comparison failed (fail-open)",
                        exc_info=True)
        return recorded

    def _shadow_complete(self, prompt_text: str, input_context: str):
        """One shadow LLM call; ``None`` on failure (the pair is then dropped
        so a half-observation is never recorded)."""
        try:
            resp = self.llm.complete(
                [{"role": "system", "content": prompt_text},
                 {"role": "user", "content": input_context}],
                require_tool=False, phase="rqgm_shadow",
            )
            return getattr(resp, "content", "") or ""
        except Exception:
            log.debug("shadow completion failed", exc_info=True)
            return None

    def run_adversarial_round(
        self,
        node,
        *,
        frontier_scores=(),
        parent_score=None,
        paper_candidate=False,
        remaining_node_budget: int = -1,
    ):
        """Best-effort per-node round hook for ``_run_loop`` step 5
        (plan 06 §5.3). Never raises; ``None`` when the round did not run.

        Before the round, the Task 12 level ladder is evaluated and
        audit-logged (plan 12 §5.2: ``{node_id, epoch_id, level,
        triggers}`` — deterministic and replayable). Assignment is
        observational in v1; gating stays with the Task 06 trigger
        disjunction plus the per-role budget gates inside the round.
        """
        self.stamp_node_producer(node)
        try:
            manager = self.budget_manager
            if manager is not None:
                level, triggers = manager.level_with_triggers(
                    node,
                    frontier=frontier_scores,
                    parent_score=parent_score,
                    paper_candidate=paper_candidate,
                )
                manager.record_level(
                    str(getattr(node, "id", "") or ""), level, triggers
                )
        except Exception:
            log.warning("governance level assignment failed (fail-open)",
                        exc_info=True)
        adv = self.adversarial
        if adv is None:
            return None
        try:
            return adv.run(
                node,
                frontier_scores=frontier_scores,
                parent_score=parent_score,
                paper_candidate=paper_candidate,
                remaining_node_budget=remaining_node_budget,
            )
        except Exception:
            log.warning("adversarial round failed (fail-open)", exc_info=True)
            return None

    def replay_utility_penalties(self, all_nodes) -> int:
        """Deterministically re-apply persisted utility penalties to freshly
        loaded nodes. Returns the number of nodes updated.

        Exploration-round penalties reach ``tree.json`` through the run
        loop's flush, but the paper pre-flight escalation round mutates only
        in-memory nodes and no entry writes ``tree.json`` after the paper
        phase (the loop's last flush precedes it). The durable truth is the ``UtilityRecord`` line
        in ``rqgm_adversarial_cases.jsonl`` (base/penalty/final stored by
        value — pure arithmetic, P2-safe). Replaying it on load makes the
        ranking reproducible across re-invocations, which the §5.3 one-round
        marker alone cannot (it suppresses the round but not the score
        reversion).

        Idempotent and conservative: a record applies only when the node's
        CURRENT score equals the record's ``base_score`` (records chain
        naturally in log order — a paper-time penalty's base is the
        exploration-penalized value); a score already at ``final_score`` or
        since rewritten by recompute/re-score is left alone. Sterile nodes
        are skipped (the ``apply_utility_penalty`` guard). Fail-open.
        """
        try:
            from ari.rqgm.adversarial.pool import AdversarialCaseLog
            from ari.rqgm.adversarial.records import UTILITY_RECORD_TYPE

            if not self.checkpoint_dir:
                return 0
            by_id = {
                str(getattr(n, "id", "") or ""): n for n in (all_nodes or [])
            }
            records = [
                rec for rec in AdversarialCaseLog.read(self.checkpoint_dir)
                if rec.get("record_type") == UTILITY_RECORD_TYPE
            ]
            # Frontier repair reverses a penalty by RECOMPUTATION: a
            # superseding record (``supersedes: <record_id>``) with the
            # surviving penalty — 0.0 when every validated attack behind the
            # original was retired. A superseded record must never be
            # re-applied (the reversal restored the base score in tree.json,
            # so the stale original would otherwise base-match and re-demote
            # a formally exonerated node).
            superseded = {
                str(r.get("supersedes"))
                for r in records if r.get("supersedes")
            }
            applied = 0
            for rec in records:
                if str(rec.get("record_id", "") or "") in superseded:
                    continue  # reversed/recomputed by frontier repair
                node = by_id.get(str(rec.get("node_id", "") or ""))
                if node is None:
                    continue
                metrics = getattr(node, "metrics", None)
                if not isinstance(metrics, dict):
                    continue
                if metrics.get("_sterile") is True:
                    continue
                cur = metrics.get("_scientific_score")
                if not isinstance(cur, (int, float)) or isinstance(cur, bool):
                    continue
                try:
                    base = float(rec.get("base_score", 0.0) or 0.0)
                    penalty = float(rec.get("penalty", 0.0) or 0.0)
                    final = float(rec.get("final_score", 0.0) or 0.0)
                except (TypeError, ValueError):
                    continue
                if penalty <= 0.0 or abs(float(cur) - final) < 1e-9:
                    continue  # no-op record, or already reflected
                if abs(float(cur) - base) >= 1e-9:
                    continue  # score since recomputed/re-scored — keep it
                metrics["_pre_penalty_score"] = base
                metrics["_validated_attack_penalty"] = penalty
                metrics["_scientific_score"] = final
                applied += 1
            if applied:
                log.info(
                    "replayed %d persisted utility penalt%s onto loaded "
                    "nodes (paper-time penalties are not in tree.json)",
                    applied, "y" if applied == 1 else "ies",
                )
            return applied
        except Exception:
            log.warning("utility-penalty replay failed (fail-open)",
                        exc_info=True)
            return 0

    def run_paper_candidate_escalation(
        self,
        best_node,
        *,
        all_nodes=None,
        frontier_scores=None,
        parent_score=None,
    ):
        """Paper pre-flight escalation of the chosen paper-candidate node
        (plan 03 trigger table ``paper_candidate``; plan 06 §5.5 disjunction
        "node is a paper candidate (best-node lineage at paper phase)";
        plan 12 §5.2 "Paper candidates → L3").

        LIGHT-TOUCH, through EXISTING per-node machinery — no parallel
        governance loop, no wrapping of the claim gate:

        1. Reconstruct the minimal RQGM context from the checkpoint
           (:meth:`ensure_epoch` restores the exploration epoch on a fresh
           ``ari paper`` process, or opens ``epoch_000`` when none exists).
        2. Run ONE final adversarial round on *best_node* with
           ``paper_candidate=True`` (:meth:`run_adversarial_round`), so
           :func:`should_attack` fires the paper-candidate clause and the
           Task 12 level ladder assigns L3 — the paper/novelty/prior-art/
           reproducibility claim adversaries attack the best node's real
           artifacts (populated by ``build_artifact_bundle``).
        3. Admit this round's ValidatedAttackRecords into the
           AdversarialReplayPool through the SAME admission call Task 05's
           epoch-boundary step 7 uses (:meth:`AdversarialReplayPool.admit`
           → evict → snapshot), delivering paper → RQGM feedback.

        NOT merely observational: judge-validated attacks apply the bounded
        utility penalty (plan 06 §5.4 — ``_scientific_score`` is rewritten in
        place, and every downstream consumer incl. best-node selection sees
        the governed value). A penalized candidate can therefore lose the
        subsequent seed/verified-context re-selection. Callers must
        (a) re-select after escalating and escalate any NEW winner too (the
        fixpoint loop in ``ari.cli.paper_dispatch``, shared by all three CLI
        entries), and (b) replay persisted penalties when reloading nodes
        (:meth:`replay_utility_penalties`) — no entry writes ``tree.json``
        after the paper phase, so without replay a re-run would revert the
        ranking while the §5.3 round marker suppresses a second round (a P2
        determinism violation).

        Gated on ``ari_rqgm`` (this runtime exists only then). Fail-open:
        every step is best-effort and the whole method never raises, so a
        failure logs and never blocks the paper pipeline. Returns the round
        summary dict or ``None``.
        """
        try:
            if best_node is None:
                return None
            # Reconstruct minimal RQGM context from the checkpoint (a fresh
            # ``ari paper`` process has no open epoch): best-effort — the
            # round still runs with an empty epoch_id if this degrades.
            # Skipped when an epoch is ALREADY open (the one-pass entries call
            # this on the LIVE exploration runtime): the restore would be a
            # no-op except for resetting `_last_node_count` to 0, which is
            # what an emergency quarantine stamps as the next epoch's
            # `node_count_at_open` — poisoning the boundary arithmetic.
            try:
                if self.current_epoch is None:
                    self.ensure_epoch(0, run_id="paper")
            except Exception:
                log.warning("paper-candidate epoch restore failed "
                            "(fail-open)", exc_info=True)
            scores = frontier_scores
            if scores is None:
                scores = self._paper_frontier_scores(all_nodes)
            if parent_score is None:
                parent_score = self._paper_parent_score(best_node, all_nodes)
            summary = self.run_adversarial_round(
                best_node,
                frontier_scores=scores,
                parent_score=parent_score,
                paper_candidate=True,
            )
            self._admit_paper_validated_attacks(best_node)
            return summary
        except Exception:
            log.warning("paper-candidate escalation failed (fail-open)",
                        exc_info=True)
            return None

    @staticmethod
    def _node_score(node) -> float:
        metrics = getattr(node, "metrics", None) or {}
        try:
            return float(metrics.get("_scientific_score") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def _paper_frontier_scores(self, all_nodes) -> list:
        """Frontier scores for the L3 top-K / trigger inputs (best-effort).

        Erased nodes are excluded for audit-record hygiene: the paper
        candidate's level is forced to L3 regardless, so an erased score
        here could only mis-state the recorded ``triggers`` list."""
        return [
            self._node_score(n) for n in (all_nodes or ())
            if not isinstance(getattr(n, "metrics", None), dict)
            or n.metrics.get("_valid_for_frontier", True) is not False
        ]

    def _paper_parent_score(self, node, all_nodes):
        """The best node's parent ``_scientific_score`` (score-jump trigger).

        An erased parent's retained stale score would suppress the
        score-jump clause — treated as no-parent instead."""
        parent_id = getattr(node, "parent_id", None)
        if not parent_id or not all_nodes:
            return None
        for n in all_nodes:
            if getattr(n, "id", None) == parent_id:
                metrics = getattr(n, "metrics", None)
                if (isinstance(metrics, dict)
                        and metrics.get("_valid_for_frontier", True) is False):
                    return None
                return self._node_score(n)
        return None

    def _admit_paper_validated_attacks(self, node) -> None:
        """Admit the paper-candidate round's ValidatedAttackRecords into the
        replay pool via the existing Task 06 admission machinery (the same
        ``admit`` → ``evict_to_cap`` → ``save_snapshot`` sequence Task 05
        step 7 runs). Reads the validated records the round just wrote to
        ``rqgm_adversarial_cases.jsonl`` for this node. Idempotent: pool
        admission dedups by ``(case_type, artifact_hash)``, so a re-run
        paper pass never duplicates a case. Best-effort; never raises."""
        pool = self.adversarial_pool
        if pool is None or self.checkpoint_dir is None:
            return
        try:
            from ari.rqgm.adversarial.pool import AdversarialCaseLog

            node_id = str(getattr(node, "id", "") or "")
            validated = [
                line
                for line in AdversarialCaseLog.read(self.checkpoint_dir)
                if line.get("record_type") == "validated_attack"
                and str(line.get("source_node_id", "")) == node_id
            ]
            if not validated:
                return
            pool.admit(validated, self.epoch_id_or_empty())
            pool.evict_to_cap()
            pool.save_snapshot()
        except Exception:
            log.warning("paper-candidate pool admission failed (fail-open)",
                        exc_info=True)

    def epoch_id_or_empty(self) -> str:
        """The current epoch id, or ``""`` when no epoch is open."""
        ep = self.current_epoch
        return str(getattr(ep, "epoch_id", "") or "") if ep is not None else ""

    # ── Task 03: proposal layer (ProposalStore + ProposalRouter) ──────

    @property
    def proposal_store(self):
        """Lazily constructed :class:`ari.rqgm.proposals.store.ProposalStore`
        (``None`` without a checkpoint dir)."""
        if self._proposal_store is None and self.checkpoint_dir is not None:
            from ari.rqgm.proposals.store import ProposalStore

            self._proposal_store = ProposalStore(self.checkpoint_dir)
        return self._proposal_store

    @property
    def router(self):
        """Lazily constructed :class:`ari.rqgm.proposals.router.ProposalRouter`.

        The VirSciAdapter is only constructed inside the router when
        ``proposal_router.generators.virsci.enabled`` is true (plan 03 §5.4
        guarantee list). ``None`` when no checkpoint dir is available.
        """
        if self._router is None:
            store = self.proposal_store
            if store is None:
                return None
            try:
                from ari.rqgm.proposals.router import ProposalRouter

                self._router = ProposalRouter(
                    self.cfg,
                    self.llm,
                    self.mcp,
                    store,
                    epoch_state=lambda: self.current_epoch,
                )
            except Exception:
                log.warning("ProposalRouter construction failed",
                            exc_info=True)
                return None
        return self._router

    def generate_root_proposals(self, ctx: "dict | None" = None) -> bool:
        """Best-effort root ideation hook for ``_run_loop`` (main thread).

        Returns ``True`` when the proposal channel is live for this run —
        i.e. records exist and ``idea.json`` is the router's projection —
        so the caller may suppress the agent-initiated root
        ``generate_ideas``. ``False`` means fall back to the status-quo
        path. Never raises.
        """
        router = self.router
        if router is None:
            return False
        try:
            router.generate_root_proposals(ctx or {})
            store = self.proposal_store
            return bool(store is not None and store.load_all())
        except Exception:
            log.warning("root proposal generation failed; status-quo path "
                        "continues", exc_info=True)
            return False

    def reideate(self, event: str, ctx: "dict | None" = None) -> list:
        """Best-effort RE-IDEATION hook for the three non-root trigger events
        (plan 03 §5.2: ``frontier_stagnation`` / ``major_pivot`` /
        ``paper_candidate``). Never raises; ``[]`` when nothing was produced.

        ``ProposalRouter.on_event`` — documented as "the re-ideation surface" —
        had NO production caller, so three of the four rows of the router's
        ``_EVENT_PRIORITY`` table were dead and, because only
        ``initial_exploration`` (``virsci``, ``cheap``) ever dispatched,
        ``MutationGenerator`` and ``PriorArtDifferentiationGenerator`` were
        unreachable in production despite being enabled by default with real
        per-epoch budgets.
        """
        router = self.router
        if router is None:
            return []
        try:
            return list(router.on_event(str(event), ctx or {}) or [])
        except Exception:
            log.warning("re-ideation on %s failed; the run continues",
                        event, exc_info=True)
            return []

    def record_expansion_proposal(self, node, direction):
        """Best-effort expansion-direction recording (observation only)."""
        router = self.router
        if router is None:
            return None
        return router.record_expansion_proposal(node, direction)

    def render_expand_context(self) -> str:
        """Render the expand ``idea_context`` from the selected summary.

        The ``ari_rqgm`` summary-only channel (plan 03 §5.5 layer 2):
        ``""`` when no selected ProposalRecord exists yet, letting callers
        keep their ``idea.json`` fallback. Enforcement is layered per
        plan 12 §5.7: the kernel's ``validate_context_scope`` runs
        warn-and-flag on the live view (layer 2), then the typed renderer
        (layer 1) refuses anything but a ProposalSummaryView — an
        out-of-scope view falls back to the caller's ``idea.json`` context
        and never blocks the expand. Never raises.
        """
        try:
            store = self.proposal_store
            if store is None:
                return ""
            selected = store.selected()
            if selected is None:
                return ""
            from ari.rqgm.context_views import build_bfts_summary_context

            view = selected.summary
            self._flag_bfts_view_scope(view)
            budget = getattr(
                getattr(self.cfg, "proposal_router", None),
                "summary_budget_chars",
                6000,
            )
            return build_bfts_summary_context(view, cap=int(budget))
        except Exception:
            log.warning("render_expand_context failed", exc_info=True)
            return ""

    def _flag_bfts_view_scope(self, view) -> None:
        """Layer-2 check-time enforcement on the live expand context
        (plan 12 §5.7): warn and append a ``kernel_report`` audit line on
        whitelist violations; never blocks node execution (fail-open)."""
        if self.kernel is None:
            return
        try:
            from ari.rqgm.context_views import BFTS_VIEW_ROLE

            report = self.kernel.validate_context_scope(BFTS_VIEW_ROLE, view)
            if not report.violations:
                return
            log.warning(
                "BFTS expand-context scope violations (view exceeds the "
                "ProposalSummaryView whitelist): %s",
                [v.detail for v in report.violations],
            )
            from ari.rqgm.kernel import kernel_report_audit_payload
            from ari.rqgm.store import ImmutableAuditLog

            ImmutableAuditLog(self.checkpoint_dir).append(
                "kernel_report",
                kernel_report_audit_payload(
                    report, self.kernel.constitution_hash
                ),
            )
        except Exception:
            log.warning("context-scope check failed (fail-open)",
                        exc_info=True)

    def wrap_search_strategy(self, bfts: "SearchStrategy") -> GovernedSearchStrategy:
        """Wrap *bfts* without changing ``build_runtime``'s 6-tuple shape."""
        return GovernedSearchStrategy(bfts, self)

    def wrap_node_executor(self, agent: "NodeExecutor") -> "NodeExecutor":
        """Attach the Task 11 §5.8 metric-spec weight cap and the Task 14
        §5.8 utility-policy stamp; otherwise identity (the seam stays
        reserved for Tasks 05/06).

        The cap is an additive attribute read by the single
        ``make_metric_spec`` handler site in ``ari/agent/loop.py``; under
        ``simple_bfts`` this wrapper never runs, the attribute is absent,
        and the handler is byte-for-byte unchanged.
        """
        try:
            me = getattr(getattr(self.cfg, "rqgm", None), "meta_evolution",
                         None)
            if me is None or bool(
                getattr(me, "metric_spec_weight_cap", True)
            ):
                from ari.rqgm.meta_evolution import MetricSpecWeightCap
                from ari.rqgm.store import ImmutableAuditLog

                agent.rqgm_weight_cap = MetricSpecWeightCap(
                    audit_log=ImmutableAuditLog(self.checkpoint_dir),
                    epoch_state=lambda: self.current_epoch,
                )
        except Exception:
            log.warning("metric-spec weight cap attach failed", exc_info=True)
        return self._wrap_utility_policy_stamp(agent)

    def _wrap_utility_policy_stamp(self, agent: "NodeExecutor"):
        """Stamp every scored node with the epoch's utility-policy hash
        (plan 14 §5.8 delta 2).

        Wraps ``run`` rather than adding a call site in ``ari/agent/loop.py``:
        the stamp must cover EVERY node the executor scores (that is the
        whole point — an unattacked node carries no UtilityRecord, so the
        node's own provenance is the only thing that can say which policy
        scored it), and ``run`` returning is exactly "this node has been
        scored". Post-hoc and best-effort: the node is already complete, so a
        stamp failure can never affect it.

        ``simple_bfts`` never reaches here (``wrap_node_executor`` is only
        called when ``bfts.rqgm`` exists), so the sentinel is never written
        and ``tree.json`` is byte-identical to today.
        """
        try:
            from ari.rqgm.utility_evolution import UtilityPolicyStamp

            stamp = UtilityPolicyStamp(epoch_state=lambda: self.current_epoch)
            inner = agent.run

            def run(node, experiment):
                result = inner(node, experiment)
                stamp(result if result is not None else node)
                return result

            agent.run = run
            agent.rqgm_utility_policy_stamp = stamp
        except Exception:
            log.warning("utility policy stamp attach failed", exc_info=True)
        return agent

    def persist_mode(
        self,
        checkpoint_dir: "str | Path | None" = None,
        *,
        mode_source: str = "config",
    ) -> None:
        """Write-once run-start persistence of ``{ckpt}/rqgm_state.json``."""
        from ari.rqgm.state import persist_run_start

        ckpt = checkpoint_dir if checkpoint_dir is not None else self.checkpoint_dir
        if ckpt is None:
            log.warning("persist_mode: no checkpoint_dir — rqgm_state.json not written")
            return
        persist_run_start(
            ckpt,
            mode=self.mode.value,
            rqgm_enabled=True,
            mode_source=mode_source,
        )
