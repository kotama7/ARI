"""Pure CK-HAR checks for Harness locks, pins, and Attestations."""

from __future__ import annotations

from ari.rqgm.kernel_kca_common import as_dict, full_digest_matches, violation
from ari.rqgm.kernel_types import make_report


CHECK = "validate_harness_integrity"
TIER_RANK = {"screen": 0, "validate": 1, "certify": 2}


def _add(violations, severity, code, subject, rule, detail) -> None:
    violations.append(violation(severity, code, CHECK, subject, rule, detail))


def _matching_requirements(old: dict, current: list[dict]) -> list[dict]:
    return [
        item
        for item in current
        if str(item.get("property_id", "")) == str(old.get("property_id", ""))
        and str(item.get("target_kind", "")) == str(old.get("target_kind", ""))
        and as_dict(item.get("scope") or {}) == as_dict(old.get("scope") or {})
    ]


def _append_requirement_monotonicity(
    violations,
    *,
    severity,
    subject,
    contract,
    previous_verification_contract,
) -> None:
    if previous_verification_contract is None:
        return
    previous = as_dict(previous_verification_contract)
    current = [as_dict(item) for item in contract.get("requirements") or ()]
    for old_raw in previous.get("requirements") or ():
        old = as_dict(old_raw)
        candidates = _matching_requirements(old, current)
        methods = set().union(
            *(set(item.get("required_methods") or ()) for item in candidates)
        )
        if not candidates or not set(old.get("required_methods") or ()).issubset(
            methods
        ):
            _add(
                violations,
                severity,
                "CK-HAR-004",
                subject,
                "monotonic_verification_requirements",
                "a previously required property or method was removed",
            )
            continue
        strongest = max(
            TIER_RANK.get(str(item.get("required_tier", "")), -1)
            for item in candidates
        )
        if strongest < TIER_RANK.get(str(old.get("required_tier", "")), -1):
            _add(
                violations,
                severity,
                "CK-HAR-016",
                subject,
                "monotonic_verification_tier",
                "a Verification requirement tier was downgraded",
            )
        changed_tolerance = any(
            str(item.get("tolerance_policy_digest", ""))
            != str(old.get("tolerance_policy_digest", ""))
            for item in candidates
        )
        if changed_tolerance:
            _add(
                violations,
                severity,
                "CK-HAR-017",
                subject,
                "immutable_tolerance_policy",
                "a Verification requirement tolerance policy changed",
            )


def _append_baseline_findings(
    violations, *, severity, subject, baseline, selector_component_id
) -> None:
    if selector_component_id != "harness_resolver_v1":
        _add(
            violations,
            severity,
            "CK-HAR-003",
            selector_component_id,
            "fixed_harness_resolver",
            "authoritative Harness selection used a non-fixed actor",
        )
    if not full_digest_matches(baseline, "lock_digest"):
        _add(
            violations,
            severity,
            "CK-HAR-006",
            subject,
            "BaselineHarnessLockV1.lock_digest",
            "baseline Harness Lock digest is invalid",
        )
    required = {
        str(item.get("atom_digest", ""))
        for item in baseline.get("requirements") or ()
        if isinstance(item, dict)
    }
    covered = {
        str(atom)
        for item in baseline.get("harnesses") or ()
        if isinstance(item, dict)
        for atom in item.get("covered_atom_digests") or ()
    }
    if not required.issubset(covered):
        _add(
            violations,
            severity,
            "CK-HAR-001",
            subject,
            "required_property_coverage",
            "Harness Lock does not cover every required atom",
        )


def _manifest_path(manifest: dict, path: str):
    current = manifest
    for part in path.split("."):
        current = current.get(part, {}) if isinstance(current, dict) else {}
    return current


def _append_manifest_findings(
    violations, *, severity, baseline, catalog
) -> None:
    manifests = {
        str(item.get("manifest_digest", "")): item
        for item in catalog.get("manifests") or ()
        if isinstance(item, dict)
    }
    pin_codes = (
        ("manifest_digest", "manifest_digest", "CK-HAR-007"),
        ("oracle_digest", "oracle.sha256", "CK-HAR-008"),
        ("dataset_digest", "dataset.sha256", "CK-HAR-009"),
        ("driver_digest", "driver.sha256", "CK-HAR-010"),
        ("container_digest", "container.resolved_digest", "CK-HAR-011"),
    )
    for locked in baseline.get("harnesses") or ():
        item = as_dict(locked)
        harness_id = str(item.get("harness_id", ""))
        manifest = manifests.get(str(item.get("manifest_digest", "")))
        if manifest is None or str(manifest.get("status", "")) != "verified":
            _add(
                violations,
                severity,
                "CK-HAR-002",
                harness_id,
                "verified_harness_catalog",
                "locked Harness is not an exact verified catalog entry",
            )
            continue
        if not full_digest_matches(manifest, "manifest_digest"):
            _add(
                violations,
                severity,
                "CK-HAR-007",
                harness_id,
                "HarnessManifestV1.manifest_digest",
                "Harness Manifest canonical digest is invalid",
            )
        for lock_field, manifest_path, code in pin_codes:
            if str(item.get(lock_field, "")) != str(
                _manifest_path(manifest, manifest_path)
            ):
                _add(
                    violations,
                    severity,
                    code,
                    harness_id,
                    f"HarnessManifestV1.{manifest_path}",
                    f"locked {lock_field} differs from manifest",
                )


def _append_revision_findings(
    violations, *, severity, subject, baseline, revision
) -> None:
    if revision is None:
        return
    rev = as_dict(revision)
    baseline_harnesses = {
        str(item.get("manifest_digest", ""))
        for item in baseline.get("harnesses") or ()
        if isinstance(item, dict)
    }
    active_harnesses = {
        str(item.get("manifest_digest", ""))
        for item in rev.get("active_harnesses") or ()
        if isinstance(item, dict)
    }
    if not baseline_harnesses.issubset(active_harnesses):
        _add(
            violations,
            severity,
            "CK-HAR-004",
            subject,
            "required_harness_retention",
            "a required baseline Harness was removed from the active revision",
        )
    try:
        from ari.assurance.lock import validate_harness_revision
        from ari.assurance.models import (
            BaselineHarnessLockV1,
            HarnessLockRevisionV1,
        )

        validate_harness_revision(
            baseline=BaselineHarnessLockV1.model_validate(baseline),
            revision=HarnessLockRevisionV1.model_validate(rev),
        )
    except Exception as exc:
        detail = str(exc)
        code = (
            "CK-HAR-017"
            if "cannot swap" in detail.lower()
            and "tolerance" in detail.lower()
            else "CK-HAR-005"
        )
        _add(
            violations,
            severity,
            code,
            subject,
            "monotonic_harness_revision",
            detail,
        )


def _attestation_covered_atoms(attestation: dict) -> set[str]:
    return {
        str(atom)
        for result in attestation.get("property_results") or ()
        if isinstance(result, dict)
        for atom in result.get("covered_atom_digests") or ()
    }


def _append_attestation_findings(
    violations,
    *,
    severity,
    subject,
    attestation,
    request,
    baseline,
    current_target_digest,
    active_harness_lock_digest,
) -> dict | None:
    if attestation is None:
        return None
    att = as_dict(attestation)
    fixed_author = (
        str(att.get("producer_component_id", "")) == "fixed_verifier_v1"
        and att.get("producer_prompt_hash") is None
    )
    if not full_digest_matches(att, "attestation_digest") or not fixed_author:
        _add(
            violations,
            severity,
            "CK-HAR-014",
            subject,
            "HarnessAttestationV1",
            "Attestation is malformed or not fixed-verifier-authored",
        )
    expected_lock = active_harness_lock_digest or str(
        baseline.get("lock_digest", "")
    )
    if str(att.get("active_harness_lock_digest", "")) != expected_lock:
        _add(
            violations,
            severity,
            "CK-HAR-013",
            subject,
            "active_harness_lock",
            "Attestation belongs to a stale Harness Lock",
        )
    if current_target_digest is not None and str(
        att.get("target_digest", "")
    ) != str(current_target_digest):
        _add(
            violations,
            severity,
            "CK-HAR-012",
            subject,
            "immutable_target_snapshot",
            "Attestation target differs from current candidate",
        )
    if request is not None:
        req = as_dict(request)
        requested = {
            str(item.get("atom_digest", ""))
            for item in req.get("property_atoms") or ()
            if isinstance(item, dict)
        }
        if not requested.issubset(_attestation_covered_atoms(att)):
            _add(
                violations,
                severity,
                "CK-HAR-015",
                subject,
                "attestation_scope",
                "Attestation does not cover requested property scope",
            )
    return att


def _append_publication_finding(
    violations, *, severity, subject, publication, contract, attestation
) -> None:
    if not publication:
        return
    requirements = contract.get("requirements") or ()
    certify_required = any(
        str(item.get("required_tier", "")) == "certify"
        or str(item.get("failure_policy", "")) == "block-publication"
        for item in requirements
        if isinstance(item, dict)
    )
    certify_pass = bool(attestation) and any(
        str(item.get("tier", "")) == "certify"
        and str(item.get("verdict", "")) == "pass"
        for item in attestation.get("property_results") or ()
        if isinstance(item, dict)
    )
    passing = bool(attestation) and str(attestation.get("verdict", "")) == "pass"
    if not passing or (certify_required and not certify_pass):
        _add(
            violations,
            severity,
            "CK-HAR-018",
            subject,
            "certification_publication_gate",
            "publication lacks a passing required certification",
        )


def _append_boundary_findings(
    violations, *, severity, subject, result_overridden, hidden_oracle_access
) -> None:
    if result_overridden:
        _add(
            violations,
            severity,
            "CK-HAR-019",
            subject,
            "fixed_verifier_verdict",
            "fixed verifier result was suppressed or overwritten",
        )
    if hidden_oracle_access:
        _add(
            violations,
            severity,
            "CK-HAR-020",
            subject,
            "hidden_oracle_isolation",
            "candidate attempted to access hidden oracle/tests",
        )


def validate_harness_integrity(
    *,
    severity: dict[str, str],
    verification_contract,
    baseline_lock,
    catalog_snapshot,
    attestation=None,
    request=None,
    current_target_digest: str | None = None,
    active_harness_lock_digest: str | None = None,
    revision=None,
    previous_verification_contract=None,
    selector_component_id: str = "harness_resolver_v1",
    publication: bool = False,
    result_overridden: bool = False,
    hidden_oracle_access: bool = False,
):
    contract = as_dict(verification_contract)
    baseline = as_dict(baseline_lock)
    catalog = as_dict(catalog_snapshot)
    raw_attestation = as_dict(attestation) if attestation is not None else {}
    subject = str(raw_attestation.get("node_id", "") or "harness-lock")
    violations: list = []
    _append_requirement_monotonicity(
        violations,
        severity=severity,
        subject=subject,
        contract=contract,
        previous_verification_contract=previous_verification_contract,
    )
    _append_baseline_findings(
        violations,
        severity=severity,
        subject=subject,
        baseline=baseline,
        selector_component_id=selector_component_id,
    )
    _append_manifest_findings(
        violations,
        severity=severity,
        baseline=baseline,
        catalog=catalog,
    )
    _append_revision_findings(
        violations,
        severity=severity,
        subject=subject,
        baseline=baseline,
        revision=revision,
    )
    att = _append_attestation_findings(
        violations,
        severity=severity,
        subject=subject,
        attestation=attestation,
        request=request,
        baseline=baseline,
        current_target_digest=current_target_digest,
        active_harness_lock_digest=active_harness_lock_digest,
    )
    _append_publication_finding(
        violations,
        severity=severity,
        subject=subject,
        publication=publication,
        contract=contract,
        attestation=att,
    )
    _append_boundary_findings(
        violations,
        severity=severity,
        subject=subject,
        result_overridden=result_overridden,
        hidden_oracle_access=hidden_oracle_access,
    )
    return make_report("harness_integrity", violations)


__all__ = ["validate_harness_integrity"]
