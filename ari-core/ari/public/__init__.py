"""Public API surface for ARI skills (Phase 4 — REFACTORING.md §7).

Skills must only import from ``ari.public.*``.  This package is a thin
re-export layer over the corresponding ``ari.<module>`` internals so
core can refactor implementations freely while the contract stays put.

Currently exported sub-modules:

- :mod:`ari.public.container`    — container runtime helpers used by
  ari-skill-coding's regression tests.
- :mod:`ari.public.clone`        — digest-verified EAR bundle retrieval and
  extraction.
- :mod:`ari.public.execution`    — closed-workspace, bounded-process,
  artifact-log, and typed measurement contracts.
- :mod:`ari.public.analysis`     — deterministic statistical request, run
  comparison, and result contracts.
- :mod:`ari.public.knowledge` — non-executable Knowledge Skill import,
  catalog, admission, composition, and provenance contracts.
- :mod:`ari.public.providers` — Capability Provider terminology and immutable
  catalog/identity facade over the compatible MCP Provider implementation.
- :mod:`ari.public.capability_binding` — deterministic semantic Capability
  binding, lock, validation, and substitution-diagnostic contracts.
- :mod:`ari.public.assurance` — Verification Contracts, Harness catalog/lock,
  fixed verification, Attestation, and external parity contracts.
- :mod:`ari.public.memory`       — immutable research-memory records and
  retrieval provenance.
- :mod:`ari.public.science_data` — digest-bound raw, derived, and model
  interpretation sections plus the canonical numeric formula registry.
- :mod:`ari.public.figures` — declarative figure specifications, immutable
  render manifests, feedback lineage, and legacy offline reader.
- :mod:`ari.public.visual_review` — criteria-versioned multimodal findings,
  typed failures, cost/model provenance, and fail-closed review batches.
- :mod:`ari.public.cost_tracker` — LLM cost reporting used by
  ari-skill-plot to log VLM/LLM call costs.
- :mod:`ari.public.paths`        — :class:`PathManager` for callers
  that need to resolve checkpoint paths without hard-coding env vars.
- :mod:`ari.public.llm`          — :class:`LLMClient` for callers that
  proxy through the ARI-side LLM client.
- :mod:`ari.public.node_selection` — deterministic downstream node/source
  selection for transform and publication Skills.
- :mod:`ari.public.research_contract` — immutable survey, idea, metric, and
  selected research hand-off contracts.
- :mod:`ari.public.lineage` — read-only ancestor idea/artifact catalog helpers.
- :mod:`ari.public.publish`      — staged EAR publication and promotion.
- :mod:`ari.public.config_schema` — Pydantic config models for
  callers that need typed settings access.
- :mod:`ari.public.call_context` — explicit run/node/lineage context and
  signed MCP transport capability verification.
- :mod:`ari.public.skill_manifest` — canonical Skill package and tool-policy
  contract used by built-in and federated MCP providers.
- :mod:`ari.public.skill_lock` — immutable run snapshot binding manifests to
  live MCP schemas and phase-specific admission.
- :mod:`ari.public.result`        — versioned result, artifact, error, context,
  provenance, and immutable async-handle contracts for typed Skill dispatch.
- :mod:`ari.public.run_env`       — run-environment capture helpers
  (``capture_env`` / ``shell_capture_snippet``) used by
  ari-skill-coding and ari-skill-hpc.
- :mod:`ari.public.claim_gate`    — ``run_hard_gate`` (Story2Proposal
  deterministic claim_evidence_hard_gate) used by ari-skill-evaluator.
- :mod:`ari.public.evaluation`    — digest-bound metric admission, gate report,
  and advisory semantic-review contracts.
- :mod:`ari.public.verified_context` — ``render_grounded_block`` /
  ``write_verified_context`` (artifact-grounded paper claims) used by
  ari-skill-paper.
- :mod:`ari.public.manuscript` — digest-bound exploration inventory,
  manuscript context/readiness, section briefs, repair plans, and independent
  publication decisions.
"""
