"""claim_evidence_hard_gate — deterministic claim/evidence verification.

Story2Proposal architectural integration, Phase B (execution data fidelity).
The heavy logic lives here in ari-core; the evaluator-skill exposes a thin MCP
tool (``claim_evidence_hard_gate``) that calls :func:`run_hard_gate`.
"""

from ari.pipeline.claim_gate.gate import run_hard_gate

__all__ = ["run_hard_gate"]
