"""Public re-export of the deterministic claim_evidence_hard_gate.

Skills (ari-skill-evaluator) call ``run_hard_gate`` from here so they reach the
ari-core implementation through the stable public contract (req 09) rather than
the private ``ari.pipeline.claim_gate`` path. Story2Proposal Phase B.
"""

from ari.pipeline.claim_gate import run_hard_gate  # noqa: F401

__all__ = ["run_hard_gate"]
