"""ARI-RQGM evaluation harness internals (RQGM Task 13; NOT ``ari.public.*``).

Pure, LLM-free machinery behind ``scripts/rqgm_eval/run_ablation.py``: the
metric computer, the deterministic failure-injection appliers, the scripted
component doubles, ablation-condition expansion, and the offline smoke
runner. Everything here is deterministic (P2): no LLM calls, no network, no
randomness, and no wall-clock dependence in any derived value (metric 13 is
metadata only, never hashed).

Import rule (mirrors ``ari.rqgm``): keep this ``__init__`` free of submodule
imports so merely importing ``ari.rqgm.evaluation`` stays side-effect-free.

Modules
-------
- ``conditions`` — B0-B8 exploration, B paper-archive, and RQGM-paper-aligned
  P0-P4 ablation-preset expansion over
  ``scripts/rqgm_eval/ablation_matrix.yaml`` (``inherits`` deep-merge sugar,
  workflow-overlay conversion, feature-flag flattening) plus the §5.2
  VirSci-off checkpoint assertion (``virsci_absence_violations``).
- ``paper_ablation`` — evaluation-only P0-P4 posture definitions, role-level
  paper evolution gating, and ordinary-switch consistency validation.
- ``metrics`` — ``compute_metric_report(checkpoint_dir, ...)``: the thirteen
  §5.4 metrics as pure functions over persisted checkpoint artifacts, plus
  the ``rqgm_eval_metrics.json`` writer.
- ``injection`` — the ten §5.3 failure injections: spec loading/validation
  (``eval_*`` namespace), deterministic idempotent fixture application, the
  ``rqgm_injection_provenance.json`` marker, and the claim-gate detection
  helper for fixture injections 1/2.
- ``doubles`` — scripted deterministic component doubles
  (``EVAL_DOUBLE_REGISTRY``), refused unless ``rqgm.eval.enabled``.
- ``smoke`` — the offline Tier-2 smoke runner: synthetic stub-component runs
  per condition into ``workspace/rqgm_eval/<eval_id>/`` and the
  ``ablation_report.{json,md}`` aggregation.
"""
