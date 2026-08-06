"""Procedural validation of artifact-bound Harness Attestations."""

from __future__ import annotations

from ari.assurance.models import (
    BaselineHarnessLockV1,
    HarnessAttestationV1,
    HarnessRunRequestV1,
)


def validate_attestation(
    *,
    attestation: HarnessAttestationV1,
    request: HarnessRunRequestV1,
    baseline_lock: BaselineHarnessLockV1,
    current_target_digest: str,
) -> None:
    if attestation.producer_component_id != "fixed_verifier_v1" or attestation.producer_prompt_hash is not None:
        raise ValueError("Attestation producer is not the prompt-free fixed verifier")
    if request.active_harness_lock_digest != attestation.active_harness_lock_digest:
        raise ValueError("Attestation uses a stale active Harness lock")
    if attestation.baseline_harness_lock_digest != baseline_lock.lock_digest:
        raise ValueError("Attestation uses another baseline Harness lock")
    if attestation.target_digest != request.target_digest or attestation.target_digest != current_target_digest:
        raise ValueError("Attestation target digest does not equal the current candidate")
    if attestation.harness_manifest_digest != request.harness.manifest_digest:
        raise ValueError("Attestation Harness identity mismatch")
    if (
        attestation.driver_digest != request.harness.driver_digest
        or attestation.oracle_digest != request.harness.oracle_digest
        or attestation.dataset_digest != request.harness.dataset_digest
        or attestation.container_digest != request.harness.container_digest
    ):
        raise ValueError("Attestation source identity mismatch")
    required = {item.atom_digest for item in request.property_atoms}
    covered = {
        digest
        for result in attestation.property_results
        for digest in result.covered_atom_digests
    }
    if not required.issubset(covered):
        raise ValueError("Attestation does not cover every requested property atom")


__all__ = ["validate_attestation"]
