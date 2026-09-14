"""Shared verification for evidence-bound nested Provider promotion locks.

The tool registry owns several domain adapters, but all of their governed
promotion bundles use the same fifteen Provider registration gates.  This
module validates that common envelope.  Provider-specific modules remain
responsible for deriving the exact artifact and capability scope.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ari.providers.registration import PROVIDER_REGISTRATION_GATES

from models import sha256_digest
from providers import ProviderProtocolError


def self_digest(document: dict[str, Any], field: str) -> str:
    return sha256_digest(
        {key: value for key, value in document.items() if key != field}
    )


def sibling_artifact(root: Path, path_text: Any, *, label: str) -> Path:
    relative = Path(str(path_text or ""))
    if not relative.parts or relative.is_absolute() or ".." in relative.parts:
        raise ProviderProtocolError(f"{label} path is unsafe")
    path = (root / relative).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise ProviderProtocolError(f"{label} escapes its promotion bundle") from exc
    if path.is_symlink() or not path.is_file():
        raise ProviderProtocolError(f"{label} is missing")
    return path


def load_json_artifact(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderProtocolError(f"{label} is invalid: {exc}") from exc
    if not isinstance(value, dict):
        raise ProviderProtocolError(f"{label} must be a JSON object")
    return value


def verify_provider_verified_lock(
    path: str | Path,
    *,
    lock_schema: str,
    evidence_schema: str,
    manifest_schema: str,
    provider_id: str,
    provider_version: str,
    expected_lock_digest: str,
    expected_artifact: dict[str, Any],
    expected_scope: dict[str, Any],
    expected_adapter: dict[str, Any],
    expected_runtime_target: dict[str, Any],
) -> dict[str, Any]:
    """Validate one exact, approved, immutable nested Provider promotion."""

    lock_path = Path(path)
    if lock_path.is_symlink() or not lock_path.is_file():
        raise ProviderProtocolError("verified Provider lock must be a regular file")
    lock = load_json_artifact(lock_path, label="verified Provider lock")
    if lock.get("schema_version") != lock_schema:
        raise ProviderProtocolError("verified Provider lock version is invalid")
    actual_lock_digest = self_digest(lock, "lock_digest")
    if (
        lock.get("lock_digest") != actual_lock_digest
        or expected_lock_digest != actual_lock_digest
    ):
        raise ProviderProtocolError("verified Provider lock digest mismatch")
    registration = lock.get("registration")
    promotion = lock.get("promotion")
    if (
        lock.get("status") != "verified"
        or lock.get("provider_id") != provider_id
        or lock.get("provider_version") != provider_version
        or lock.get("artifact") != expected_artifact
        or lock.get("capability_scope") != expected_scope
        or lock.get("adapter") != expected_adapter
        or lock.get("runtime_target") != expected_runtime_target
        or not isinstance(registration, dict)
        or not isinstance(promotion, dict)
    ):
        raise ProviderProtocolError("verified Provider identity or scope is invalid")

    root = lock_path.parent
    manifest_path = sibling_artifact(
        root, registration.get("provider_manifest_path"), label="Provider manifest"
    )
    evidence_path = sibling_artifact(
        root, registration.get("evidence_path"), label="registration evidence"
    )
    report_path = sibling_artifact(
        root, registration.get("report_path"), label="registration report"
    )
    approval_path = sibling_artifact(
        root, promotion.get("approval_path"), label="promotion approval"
    )
    manifest = load_json_artifact(manifest_path, label="Provider manifest")
    evidence = load_json_artifact(evidence_path, label="registration evidence")
    report = load_json_artifact(report_path, label="registration report")
    approval = load_json_artifact(approval_path, label="promotion approval")

    manifest_digest = sha256_digest(manifest)
    if (
        manifest.get("schema_version") != manifest_schema
        or manifest.get("provider_id") != provider_id
        or manifest.get("provider_version") != provider_version
        or manifest.get("artifact") != expected_artifact
        or manifest.get("capability_scope") != expected_scope
        or registration.get("provider_manifest_digest") != manifest_digest
    ):
        raise ProviderProtocolError("Provider manifest differs from the verified scope")
    if (
        evidence.get("schema_version") != evidence_schema
        or evidence.get("provider_id") != provider_id
        or evidence.get("provider_version") != provider_version
        or evidence.get("artifact") != expected_artifact
        or evidence.get("capability_scope") != expected_scope
        or evidence.get("bundle_digest") != self_digest(evidence, "bundle_digest")
        or evidence.get("bundle_digest") != registration.get("evidence_bundle_digest")
    ):
        raise ProviderProtocolError("Provider registration evidence digest mismatch")
    if (
        report.get("schema_version") != "ari.capability-provider-registration-report/v1"
        or report.get("provider_id") != provider_id
        or report.get("manifest_sha256") != manifest_digest
        or report.get("decision") != "eligible-for-verified"
        or report.get("report_digest") != self_digest(report, "report_digest")
        or report.get("report_digest") != registration.get("report_digest")
    ):
        raise ProviderProtocolError("Provider registration report is not eligible")

    gates = report.get("gates")
    gate_evidence = evidence.get("gate_evidence")
    if not isinstance(gates, list) or not isinstance(gate_evidence, dict):
        raise ProviderProtocolError("Provider registration gates are missing")
    observed = tuple(item.get("gate_id") for item in gates if isinstance(item, dict))
    if observed != PROVIDER_REGISTRATION_GATES or set(gate_evidence) != set(observed):
        raise ProviderProtocolError("Provider registration gates are incomplete")
    for gate in gates:
        gate_id = gate["gate_id"]
        item = gate_evidence.get(gate_id)
        if (
            gate.get("passed") is not True
            or not isinstance(item, dict)
            or not item
            or not str(gate.get("detail") or "").strip()
            or gate.get("evidence_digest") != sha256_digest(item)
        ):
            raise ProviderProtocolError(
                f"Provider registration gate evidence mismatch: {gate_id}"
            )

    if (
        approval.get("schema_version")
        != "ari.capability-provider-promotion-approval/v1"
        or approval.get("approval_digest") != self_digest(approval, "approval_digest")
        or approval.get("approval_digest") != promotion.get("approval_digest")
        or approval.get("provider_id") != provider_id
        or approval.get("provider_version") != provider_version
        or approval.get("from_status") != "candidate"
        or approval.get("to_status") != "verified"
        or approval.get("actor_kind") != "human-maintainer"
        or not str(approval.get("actor_id") or "").strip()
        or approval.get("authorization_basis") != "explicit-maintainer-approval"
        or approval.get("provider_manifest_digest") != manifest_digest
        or approval.get("registration_report_digest") != report.get("report_digest")
        or approval.get("evidence_bundle_digest") != evidence.get("bundle_digest")
        or approval.get("capability_scope_digest") != sha256_digest(expected_scope)
    ):
        raise ProviderProtocolError("formal Provider promotion approval is invalid")
    return lock


__all__ = [
    "load_json_artifact",
    "self_digest",
    "sibling_artifact",
    "verify_provider_verified_lock",
]
