"""GovernanceOrchestrator — the epoch-boundary governance facade (RQGM Task 05).

One public class, one public method, one public return type
(plan ``docs/plans/ari_rqgm/05`` §5.1/§7):

    report = GovernanceOrchestrator(cfg, kernel=kernel).audit_epoch(
        epoch_state=..., audit_log=..., component_registry=...,
        prompt_registry=..., candidate_prompts=(), adversarial_replay_pool=None,
    )

Everything else (ReliabilityAssessment, EvidenceAssembly, ProsecutionDecision,
DefenseGeneration, AdjudicationPanel, GovernanceSelfAudit) lives in
underscore-private modules and is NOT re-exported, not added to
``ari.public.*``, and not exposed as MCP tools — only the facade is a
commitment.

``audit_epoch`` is **read-only** with respect to registries, the frontier,
``tree.json`` and node state; its only writes are governance records appended
to the Task 02 audit log (``rqgm_audit.jsonl``), prompt-provenance lines, the
step-7 replay-pool append, and the returned GovernanceReport (also appended).
Applying any recommendation is Task 09's RegistryTransitionEngine; the report
is advisory input. ``llm=None`` yields a fully deterministic audit (steps 4-6
use their rule-only fallbacks) — the CI-friendly configuration and the
guaranteed-degradation floor. Under ``simple_bfts`` this package is never
imported by the run path.
"""

from __future__ import annotations

import logging

from ari.rqgm.governance._records import GovernanceReport

__all__ = ["GovernanceOrchestrator", "GovernanceReport"]

log = logging.getLogger(__name__)


class GovernanceOrchestrator:
    """The single epoch-boundary governance entry point (plan 05 §7).

    *cfg* is the ``rqgm`` config slice (``.governance`` + ``.replay`` —
    typed models, raw dicts, or absent all work); *kernel* is the Task 04
    ConstitutionalKernel (required — it re-validates every produced record in
    the self-audit step); *llm* is the governance-phase LLM seam (``None`` →
    pure-deterministic mode); *audit_writer* is the Task 02 append-only
    writer (``None`` → records collected in-memory on ``self.written`` for
    tests); *governance_cache* is the optional Task 12
    :class:`~ari.rqgm.governance_cache.GovernanceCache` consulted by the
    replay/candidate evaluation path when ``rqgm.replay.use_cached_results``
    (``None`` → pool-only scoring).
    """

    def __init__(
        self,
        cfg,
        *,
        kernel,
        llm=None,
        audit_writer=None,
        prompt_loader=None,
        governance_cache=None,
    ) -> None:
        if kernel is None:
            raise ValueError(
                "GovernanceOrchestrator requires the ConstitutionalKernel "
                "(plan 05 §7): the kernel is the role-separation authority"
            )
        self.cfg = cfg
        self.kernel = kernel
        self.llm = llm
        self.audit_writer = audit_writer
        self._prompt_loader = prompt_loader
        self.governance_cache = governance_cache
        #: In-memory sink when no audit_writer is injected (tests).
        self.written: list = []
        self.last_report: GovernanceReport | None = None

    def audit_epoch(
        self,
        *,
        epoch_state,
        audit_log,
        component_registry,
        prompt_registry,
        candidate_prompts=(),
        adversarial_replay_pool=None,
        budget_manager=None,
    ) -> GovernanceReport:
        """Run the nine-step audit (plan 05 §5.3) and append its records.

        Step failures degrade the report (``degradation_reasons``); only
        report serialization may raise — the caller's fail-open catch
        (§5.2) then applies. *budget_manager* (RQGM Task 12 §7, optional)
        is consulted before every internal LLM step; a denial degrades
        that step to its deterministic fallback.
        """
        from ari.rqgm.governance._pipeline import run_audit

        gov_cfg = getattr(self.cfg, "governance", None)
        if gov_cfg is None and isinstance(self.cfg, dict):
            gov_cfg = self.cfg.get("governance")
        replay_cfg = getattr(self.cfg, "replay", None)
        if replay_cfg is None and isinstance(self.cfg, dict):
            replay_cfg = self.cfg.get("replay")
        report, produced = run_audit(
            gov_cfg=gov_cfg,
            replay_cfg=replay_cfg,
            kernel=self.kernel,
            llm=self.llm,
            epoch_state=epoch_state,
            audit_log=audit_log,
            component_registry=component_registry,
            prompt_registry=prompt_registry,
            candidate_prompts=candidate_prompts,
            adversarial_replay_pool=adversarial_replay_pool,
            loader=self._prompt_loader,
            budget_manager=budget_manager,
            governance_cache=self.governance_cache,
        )
        for record_type, payload in produced:
            self._write(record_type, payload)
        self._write("governance_report", report.to_dict())
        self.last_report = report
        return report

    def _write(self, record_type: str, payload: dict) -> None:
        """Append one governance record (never raises; writer is no-op-safe)."""
        if self.audit_writer is None:
            self.written.append((record_type, payload))
            return
        try:
            self.audit_writer.append(record_type, payload)
        except Exception:
            log.warning("governance audit append failed for %s", record_type,
                        exc_info=True)
