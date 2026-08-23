"""Provider promotion gate validation; status writes remain admin-only."""

from __future__ import annotations

from ari.providers.models import (
    CapabilityProviderRegistrationReportV1,
    ProviderRegistrationGateV1,
)


PROVIDER_REGISTRATION_GATES = (
    "manifest_schema",
    "source_package_digest_pin",
    "live_tools_list_parity",
    "schema_digest_pin",
    "capability_contract_conformance",
    "side_effect_declaration",
    "credential_scope",
    "environment_allowlist",
    "timeout_cancellation_process_group",
    "result_schema",
    "malicious_description_boundary",
    "workspace_isolation",
    "revocation_behavior",
    "schema_drift_detection",
    "unbound_invocation_rejection",
)


def registration_report(
    *, provider_id: str, manifest_sha256: str, gates: tuple[ProviderRegistrationGateV1, ...]
) -> CapabilityProviderRegistrationReportV1:
    observed = tuple(item.gate_id for item in gates)
    if observed != PROVIDER_REGISTRATION_GATES:
        raise ValueError("Provider registration gates are incomplete or out of order")
    decision = "eligible-for-verified" if all(item.passed for item in gates) else "rejected"
    return CapabilityProviderRegistrationReportV1.create(
        provider_id=provider_id,
        manifest_sha256=manifest_sha256,
        gates=gates,
        decision=decision,
    )


__all__ = ["PROVIDER_REGISTRATION_GATES", "registration_report"]
