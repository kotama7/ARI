"""Constitutional ARI-RQGM runtime (internal package, NOT ``ari.public.*``).

Home of the opt-in ``ari_rqgm`` execution mode (epoch governance and
co-evolution). Activation is config-only: ``ari.mode: ari_rqgm`` AND
``rqgm.enabled: true`` must both be set (``ari.rqgm.mode.resolve_effective_mode``
owns the interlock table); the default ``simple_bfts`` mode is byte-for-byte
current ARI and never imports this package.

Import rule (``docs/reference/internal_boundaries.md``, "RQGM mode boundary
(``ari.rqgm``)"): the composition root
(``ari.core.build_runtime``) imports ``ari.rqgm.*`` lazily inside its
``ari_rqgm`` branch only. Keep this ``__init__`` free of submodule imports so
merely importing ``ari.rqgm`` stays side-effect-free.

Modules
-------
- ``mode`` — ``EffectiveMode`` + pure ``resolve_effective_mode(cfg)``.
- ``runtime`` — ``RQGMRuntime`` facade + ``GovernedSearchStrategy`` wrapper.
- ``state`` — ``{ckpt}/rqgm_state.json`` mode provenance + ``EpochState``
  freeze (Task 02).
- ``events`` — RQGM vocabulary, id/hash formats, canonical hashing, and the
  hash-chained ``TransitionEvent`` envelope (Task 02).
- ``registry`` — ``ComponentRegistry`` + ``GovernedPromptRegistry`` (Task 02;
  NOT the discovery catalogue ``ari.prompts.registry.PromptRegistry``).
- ``store`` — ``RqgmStateStore`` (``EpochStore`` impl), ``EpochTransaction``,
  ``ImmutableAuditLog`` over the four checkpoint-root RQGM files (Task 02).
- ``kernel`` / ``kernel_types`` / ``kernel_rules`` — the deterministic,
  non-evolving Layer-0 ``ConstitutionalKernel`` (NOT an LLM judge), its
  verdict model, and the frozen rule tables pinned by ``constitution_hash``
  (Task 04).
- ``transition_rules`` — the fixed T1-T20 component/prompt transition table
  (Task 09's Layer-0 pure-data module; imported by both the kernel and the
  RegistryTransitionEngine — single source of truth).
- ``transition_engine`` — ``RegistryTransitionEngine`` + ``EpochTransition``:
  the sole registry status writer (Task 09). Deterministic resolution of
  GovernanceReport/candidate evaluations against the fixed table,
  kernel-validated epoch-boundary commits through the Task 02 transaction,
  and the emergency-quarantine mid-epoch exception.
- ``proposals/`` — ProposalRecord/SummaryView schemas, ``ProposalStore``
  (``{ckpt}/proposals/`` + the ``idea.json`` projection), the deterministic
  ``ProposalRouter`` + generators, and the MCP-only optional ``VirSciAdapter``
  (Task 03).
- ``governance/`` — the epoch-boundary ``GovernanceOrchestrator`` facade
  (``audit_epoch`` → ``GovernanceReport``): nine-step observe→report
  pipeline over the audit log, with the same-role accusation prohibition
  enforced constructively here and authoritatively by the kernel (Task 05).
- ``prompt_spec`` — ``PromptSpec`` versioned prompt identity + the founding
  bootstrap mapping the committed templates to v1 active specs (Task 07).
- ``prompt_loader`` — ``GovernedPromptLoader`` (``ari.protocols.PromptLoader``
  impl) + the write-once ``{ckpt}/rqgm_prompts/`` evolved-body store (Task 07).
- ``prompt_records`` — PromptCandidate/Validation/ComparisonObservation
  records + the fail-open ``prompt_evolution.jsonl`` writer and
  ``prompt_specs.json`` rollup (Task 07).
- ``prompt_evolution`` — the six-stage ``CandidateValidationPipeline``,
  ``PromptMutator`` (candidates only, no registry writes), budgets, shadow
  sampling, and ``build_adoption_request`` — the Task 09 adoption seam
  (Task 07).
- ``clean_room_rules`` — Layer-0 clean-room policy tables (allowed/forbidden
  input split, closed bundle field set, FailureSummary vocabulary) + the
  deterministic shingle contamination screen, shared by the kernel and the
  clean-room path (Task 08).
- ``clean_room`` — clean-room regeneration of retired-role prompts:
  request/bundle records, deterministic assembler, one-shot
  ``CleanRoomPromptGenerator`` (candidates only), the retired-text
  ``RetiredPromptAccessGuard``, the ``rqgm_cleanroom.jsonl`` event log, and
  the budget-capped epoch-boundary ``CleanRoomCoordinator`` (Task 08).
- ``meta_rules`` — Layer-0 meta-tier authority tables (capability-flag and
  meta-action vocabularies, evolving/frozen role split, the invariant-18
  flag arithmetic and cross-generation check bodies), imported by the
  kernel (Task 11).
- ``meta_evolution`` — the meta tier as an evolution target under strictly
  narrower authority: ``MetaAgentOutputRecord`` + the append-only
  ``rqgm_meta_outputs.jsonl``, frozen read-only registry views + filtered
  input bundles, ``MetaSandboxMCPProxy``/``run_meta_sandboxed``,
  ``MetaEvolutionCoordinator`` (outputs are ALWAYS Task 07 candidates),
  deterministic sandbox/shadow evaluation → ``MetaCandidateEvaluation``,
  and the §5.8 ``MetricSpecWeightCap`` (Task 11).
- ``budget`` — the Task 12 cost-control layer: governance level ladder
  (L0-L3) + deterministic escalation triggers, ``BudgetedAction`` /
  ``BudgetVerdict`` / ``GovernanceBudgetManager`` (decision-point gating
  over per-epoch call/spend caps; counters restore from the audit log),
  and hash-based deterministic shadow sampling.
- ``governance_cache`` — the spec-fixed ``cache_key`` composition and the
  append-only ``{ckpt}/rqgm_governance_cache.jsonl`` result cache
  (Task 12; ``rqgm.replay.use_cached_results`` depends on it).
- ``context_views`` — role-specific context views (Task 12 §5.7): the
  BFTS ProposalSummaryView-only renderer (typed layer-1 enforcement), the
  reviewer/adversary/judge/governance projections, and the whitelist
  constants shared with the kernel's ``validate_context_scope``.
- ``erasure_state`` — the ``{ckpt}/rqgm_erasure_state.json`` derived rollup
  of logical staleness (``ErasureStateView`` + ``RqgmErasureStateStore``;
  Task 10).
- ``frontier_repair`` — ``FrontierRepairEngine`` + the pure
  ``trace_dependents`` / ``rebuild_frontier`` helpers: selective erasure of
  retired-prompt-dependent records (logical-only, never physical),
  per-role invalidate-vs-recompute policy, declarative frontier rebuild
  with Rule-A reinstatement, and the §5.6 conservative → drain-only
  failure ladder (Task 10).
"""
