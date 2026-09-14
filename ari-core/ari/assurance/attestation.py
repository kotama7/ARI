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
    # AND NOTHING BEYOND THEM. Only the first direction was checked, so a driver
    # reporting on an atom it was never handed was accepted, and the digest went
    # straight into the bridge's coverage map without anyone comparing it to the
    # request.
    #
    # That matters because a request is built by filtering the requirements down
    # to what the LOCK says this harness covers, which is how an atom the
    # resolver could satisfy with no harness at all stays unsatisfiable. The
    # verdict aggregation now relies on such an atom never appearing in the
    # coverage map, so what used to be six drivers all happening to iterate
    # request.property_atoms is stated here instead.
    if not covered.issubset(required):
        raise ValueError(
            "Attestation covers property atoms the request did not grant it")


__all__ = ["validate_attestation"]
