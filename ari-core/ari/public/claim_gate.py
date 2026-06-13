"""Public re-export of the deterministic claim_evidence_hard_gate.

Skills (ari-skill-evaluator, ari-skill-transform) call into the gate through this
stable public contract (req 09) rather than the private
``ari.pipeline.claim_gate`` path. Story2Proposal Phase B + metric-correctness
contract (Phase 1-4):
  - ``run_hard_gate`` — the gate entry point.
  - ``classify_concept`` / ``CONCEPT_INVARIANTS`` / ``scan_science_data`` — the
    domain-general concept->invariant registry, re-exported so the transform and
    evaluator skills reuse the SAME universal-invariant logic the gate blocks on
    (single source of truth — no duplicated domain math).
  - ``check_emission`` — point-of-emission contract feedback, re-exported so the
    coding skill's emit_results can warn the agent (with the gate's OWN presence
    semantics) the moment evidence is missing, instead of the paper silently
    blocking at finalize long after the node is gone.
"""

from ari.pipeline.claim_gate import run_hard_gate  # noqa: F401
from ari.pipeline.claim_gate.contract import check_emission  # noqa: F401
from ari.pipeline.claim_gate.invariants import (  # noqa: F401
    CONCEPT_INVARIANTS,
    classify_concept,
    scan_science_data,
)

__all__ = [
    "run_hard_gate", "check_emission", "classify_concept", "scan_science_data",
    "CONCEPT_INVARIANTS",
]
