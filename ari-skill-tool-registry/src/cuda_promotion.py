"""Verification for the exact exclusive-node CUDA self-test Provider lock."""

from __future__ import annotations

import json
from pathlib import Path

from capability_pins import capability_environment_requirements
from provider_promotion import load_json_artifact, verify_provider_verified_lock
from providers import ProviderProtocolError


CUDA_PROVIDER_ID = "ari-cuda-environment-validator"
CUDA_PROVIDER_VERSION = "1.0.0+cuda12.9-sm70"
CUDA_CAPABILITY_REF = "ari.environment.cuda.validate/v1"
CUDA_LOCK_SCHEMA = "ari.cuda-environment-provider-lock/v1"
CUDA_MANIFEST_SCHEMA = "ari.cuda-environment-provider-manifest/v1"
CUDA_EVIDENCE_SCHEMA = "ari.cuda-environment-registration-evidence/v1"
CUDA_BUNDLE = (
    Path(__file__).resolve().parents[1]
    / "providers/cuda/1.0.0+cuda12.9-sm70-exclusive-node"
)


def verify_cuda_verified_lock(
    path: str | Path, *, expected_lock_digest: str
) -> dict:
    lock_path = Path(path)
    document = load_json_artifact(lock_path, label="CUDA verified Provider lock")
    lock = verify_provider_verified_lock(
        lock_path,
        lock_schema=CUDA_LOCK_SCHEMA,
        evidence_schema=CUDA_EVIDENCE_SCHEMA,
        manifest_schema=CUDA_MANIFEST_SCHEMA,
        provider_id=CUDA_PROVIDER_ID,
        provider_version=CUDA_PROVIDER_VERSION,
        expected_lock_digest=expected_lock_digest,
        expected_artifact=document.get("artifact"),
        expected_scope=document.get("capability_scope"),
        expected_adapter=document.get("adapter"),
        expected_runtime_target=document.get("runtime_target"),
    )
    scope = lock["capability_scope"]
    target = lock["runtime_target"]
    if (
        scope.get("capability_ref") != CUDA_CAPABILITY_REF
        or scope.get("tool_names") != ["ari_cuda_validate__exclusive_node_sm70"]
        or scope.get("credential_scope_ids") != []
        # Read from the contract rather than restated. The literal list here
        # went on asserting `exclusive-node` and `slurm` after both were retired
        # from the contract, so the verifier was pinning a shape the ontology no
        # longer describes -- and would have passed a lock that disagreed with
        # the capability it claims.
        or scope.get("environment_requirements")
        != capability_environment_requirements(CUDA_CAPABILITY_REF)
        or target.get("identity_disclosure") != "salted-digest-only"
        or set(target)
        != {
            "accelerator_count",
            "accelerator_model",
            "compute_capability",
            "cuda_compiler_version",
            "driver_version",
            "identity_disclosure",
            "inventory_identity_digest",
            "memory_bytes_per_device",
            "site_identity_digest",
        }
    ):
        raise ProviderProtocolError("CUDA verified Provider scope is invalid")
    evidence_path = lock_path.parent / lock["registration"]["evidence_path"]
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    validation = evidence.get("observations", {}).get("cuda_self_test", {})
    if (
        validation.get("verdict") != "pass"
        or validation.get("device_count") != target.get("accelerator_count")
        or validation.get("all_negative_controls_detected") is not True
        or validation.get("all_repeats_equal") is not True
        or validation.get("maximum_absolute_error", 1) > 1e-6
    ):
        raise ProviderProtocolError("CUDA verified Provider evidence did not pass")
    return lock


__all__ = [
    "CUDA_BUNDLE",
    "CUDA_CAPABILITY_REF",
    "CUDA_EVIDENCE_SCHEMA",
    "CUDA_LOCK_SCHEMA",
    "CUDA_MANIFEST_SCHEMA",
    "CUDA_PROVIDER_ID",
    "CUDA_PROVIDER_VERSION",
    "verify_cuda_verified_lock",
]
