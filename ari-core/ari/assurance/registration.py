"""Harness promotion gate aggregation; status transitions are admin-only."""

from __future__ import annotations

from ari.assurance.models import (
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
    *, harness_id: str, manifest_digest: str, gates: tuple[HarnessRegistrationGateV1, ...]
) -> HarnessRegistrationReportV1:
    if tuple(item.gate_id for item in gates) != HARNESS_REGISTRATION_GATES:
        raise ValueError("Harness registration gates are incomplete or out of order")
    decision = "eligible-for-verified" if all(item.passed for item in gates) else "rejected"
    return HarnessRegistrationReportV1.create(
        harness_id=harness_id,
        manifest_digest=manifest_digest,
        gates=gates,
        decision=decision,
    )


__all__ = ["HARNESS_REGISTRATION_GATES", "registration_report"]
