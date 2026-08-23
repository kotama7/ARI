"""Harness promotion gate aggregation; status transitions are admin-only.

WHAT CHANGED AND WHY. This module used to take a tuple of gates and set the
decision to ``eligible-for-verified`` when every ``passed`` was True. It never
computed a ``passed``, and nothing else did either: every gate in every shipped
report carries the identical string "passed by immutable native promotion
evidence", and ``parity_probe`` -- the only code that establishes an instrument
is not a stopwatch -- had no caller outside tests. A registration recorded that
fifteen gates were satisfied, a maintainer signed that record, and no gate had
been evaluated. The signature was real; what it attested to was not measured.

So the report is now MINTED FROM EVIDENCE. The caller supplies what was
observed -- the parity probe, the manifest, repeated-run spread, the schema, the
commit -- and each gate is computed by ``ari.assurance.registration_gates``. A
gate that cannot be decided from what it was given fails; none passes by
default, because answering True without looking is the defect being fixed.

There is deliberately no way to hand this function a pre-decided gate. A
registration is either the output of evaluating evidence or it is not a
registration.
"""

from __future__ import annotations

from ari.assurance.registration_gates import GateEvidence, evaluate_gates
from ari.assurance.registration_models import (
    HarnessRegistrationGateV1,
    HarnessRegistrationReportV1,
)


HARNESS_REGISTRATION_GATES = (
    "reference_oracle_pass",
    "negative_control_fail",
    "clean_control_pass",
    "official_runner_parity",
    "target_oracle_test_isolation",
    "determinism_declaration",
    "infrastructure_failure_separation",
    "timeout_resource_enforcement",
    "license_completeness",
    "source_revision_digest_pin",
    "hidden_test_isolation",
    "multiple_run_stability",
    "result_schema_conformance",
    "full_sha256_integrity",
    "malicious_harness_sandbox",
)


def registration_report(
    *, harness_id: str, manifest_digest: str, evidence: GateEvidence
) -> HarnessRegistrationReportV1:
    """Evaluate every gate against ``evidence`` and mint the report it earns."""
    gates = evaluate_gates(evidence)
    if tuple(item.gate_id for item in gates) != HARNESS_REGISTRATION_GATES:
        raise ValueError("Harness registration gates are incomplete or out of order")
    decision = "eligible-for-verified" if all(item.passed for item in gates) else "rejected"
    return HarnessRegistrationReportV1.create(
        harness_id=harness_id,
        manifest_digest=manifest_digest,
        gates=gates,
        decision=decision,
    )


__all__ = ["HARNESS_REGISTRATION_GATES", "GateEvidence", "HarnessRegistrationGateV1",
           "registration_report"]
