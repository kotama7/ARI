"""Exact verified-scope projection for the credential-free Qiskit/Aer Provider."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from models import sha256_digest
import provider_promotion
from provider_promotion import verify_provider_verified_lock
from providers import ProviderProtocolError
from qiskit_adapter import (
    QISKIT_ADAPTER_ID,
    QISKIT_ADAPTER_VERSION,
    QiskitExperimentV1,
    QiskitLocalBackendV1,
    qiskit_adapter_digest,
    qiskit_virtual_tool,
)
from qiskit_identity import QiskitProviderPinV1, _file_sha256, qiskit_software_release


QISKIT_VERIFIED_PROVIDER_ID = "qiskit-mcp-servers"
QISKIT_VERIFIED_PROVIDER_VERSION = "core-0.3.1"
QISKIT_VERIFIED_PROFILE_ID = "local-ideal"
QISKIT_VERIFIED_LOCK_SCHEMA = "ari.qiskit-verified-lock/v1"
QISKIT_VERIFIED_EVIDENCE_SCHEMA = "ari.qiskit-registration-evidence/v1"
QISKIT_VERIFIED_MANIFEST_SCHEMA = "ari.qiskit-capability-provider-manifest/v1"


def qiskit_verified_artifact(core_pin: QiskitProviderPinV1) -> dict[str, Any]:
    return {
        "core_mcp": core_pin.model_dump(mode="json"),
        "qiskit": qiskit_software_release("qiskit", "2.5.1"),
        "qiskit_aer": qiskit_software_release("qiskit-aer", "0.17.2"),
    }


def qiskit_verified_scope(
    experiments: Iterable[QiskitExperimentV1],
) -> dict[str, Any]:
    profiles = list(experiments)
    if len(profiles) != 1 or profiles[0].profile_id != QISKIT_VERIFIED_PROFILE_ID:
        raise ProviderProtocolError(
            "Qiskit verified identity admits exactly the local-ideal profile"
        )
    profile = profiles[0]
    if not isinstance(profile.backend, QiskitLocalBackendV1) or (
        profile.backend.kind != "local-ideal"
    ):
        raise ProviderProtocolError(
            "Qiskit verified identity cannot include Runtime or noisy profiles"
        )
    tool = qiskit_virtual_tool(profile)
    return {
        "profiles": [
            {
                "profile_id": profile.profile_id,
                "leaf_name": tool.name,
                "capability_ref": profile.capability_ref,
                "experiment_digest": profile.experiment_digest,
                "method_digest": profile.method_digest,
                "qpy_digest": profile.circuit.qpy_digest,
                "qpy_version": profile.circuit.qpy_version,
                "target_digest": profile.backend.target.target_digest,
                "golden_fixture_digest": profile.golden_fixture_digest,
                "replay_fixture_digest": profile.replay_fixture_digest,
                "input_schema_digest": sha256_digest(tool.input_schema),
                "output_schema_digest": sha256_digest(tool.output_schema),
            }
        ],
        "side_effects": "workspace-write",
        "determinism": "seeded",
        "permissions": ["process", "workspace-read", "workspace-write"],
        "credential_scope_ids": [],
        "environment_requirements": ["cpu"],
        "resource_type": "quantum-simulator",
    }


def qiskit_verified_adapter() -> dict[str, str]:
    return {
        "adapter_id": QISKIT_ADAPTER_ID,
        "adapter_version": QISKIT_ADAPTER_VERSION,
        "adapter_digest": qiskit_adapter_digest(),
        "promotion_verifier_digest": sha256_digest(
            {
                "qiskit": _file_sha256(Path(__file__).resolve()),
                "shared": _file_sha256(Path(provider_promotion.__file__).resolve()),
            }
        ),
    }


def qiskit_verified_runtime_target() -> dict[str, str]:
    return {
        "architecture": "x86_64",
        "operating_system": "linux",
        "python_implementation": "CPython",
        "python_minor": "3.13",
    }


def verify_qiskit_verified_lock(
    path: str | Path,
    *,
    expected_lock_digest: str,
    core_pin: QiskitProviderPinV1,
    experiments: Iterable[QiskitExperimentV1],
) -> dict[str, Any]:
    return verify_provider_verified_lock(
        path,
        lock_schema=QISKIT_VERIFIED_LOCK_SCHEMA,
        evidence_schema=QISKIT_VERIFIED_EVIDENCE_SCHEMA,
        manifest_schema=QISKIT_VERIFIED_MANIFEST_SCHEMA,
        provider_id=QISKIT_VERIFIED_PROVIDER_ID,
        provider_version=QISKIT_VERIFIED_PROVIDER_VERSION,
        expected_lock_digest=expected_lock_digest,
        expected_artifact=qiskit_verified_artifact(core_pin),
        expected_scope=qiskit_verified_scope(experiments),
        expected_adapter=qiskit_verified_adapter(),
        expected_runtime_target=qiskit_verified_runtime_target(),
    )


__all__ = [
    "QISKIT_VERIFIED_EVIDENCE_SCHEMA",
    "QISKIT_VERIFIED_LOCK_SCHEMA",
    "QISKIT_VERIFIED_MANIFEST_SCHEMA",
    "QISKIT_VERIFIED_PROFILE_ID",
    "QISKIT_VERIFIED_PROVIDER_ID",
    "QISKIT_VERIFIED_PROVIDER_VERSION",
    "qiskit_verified_adapter",
    "qiskit_verified_artifact",
    "qiskit_verified_runtime_target",
    "qiskit_verified_scope",
    "verify_qiskit_verified_lock",
]
