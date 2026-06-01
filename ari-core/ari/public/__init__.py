"""Public API surface for ARI skills (Phase 4 — REFACTORING.md §7).

Skills must only import from ``ari.public.*``.  This package is a thin
re-export layer over the corresponding ``ari.<module>`` internals so
core can refactor implementations freely while the contract stays put.

Currently exported sub-modules:

- :mod:`ari.public.container`    — container runtime helpers used by
  ari-skill-coding's regression tests.
- :mod:`ari.public.cost_tracker` — LLM cost reporting used by
  ari-skill-plot to log VLM/LLM call costs.
- :mod:`ari.public.paths`        — :class:`PathManager` for callers
  that need to resolve checkpoint paths without hard-coding env vars.
- :mod:`ari.public.llm`          — :class:`LLMClient` for callers that
  proxy through the ARI-side LLM client.
- :mod:`ari.public.config_schema` — Pydantic config models for
  callers that need typed settings access.
- :mod:`ari.public.run_env`       — run-environment capture helpers
  (``capture_env`` / ``shell_capture_snippet``) used by
  ari-skill-coding and ari-skill-hpc.
"""
