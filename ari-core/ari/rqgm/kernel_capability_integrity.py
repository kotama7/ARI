"""Pure CK-CAP checks for Provider identity and Capability Binding use."""

from __future__ import annotations

from ari.protocols.integrity import canonical_digest, normalize_sha256
from ari.rqgm.kernel_kca_common import (
    SIDE_EFFECT_RANK,
    as_dict,
    full_digest_matches,
    violation,
)
from ari.rqgm.kernel_types import make_report


CHECK = "validate_capability_binding_integrity"


def _add(violations, severity, code, subject, rule, detail) -> None:
    violations.append(violation(severity, code, CHECK, subject, rule, detail))


def _append_lock_findings(
    violations,
    *,
    severity,
    lock,
    subject,
    expected_lock_digest,
    expected_environment_digest,
) -> None:
    if not full_digest_matches(lock, "lock_digest"):
        _add(
            violations,
            severity,
            "CK-CAP-008",
            subject,
            "CapabilityBindingLockV1.lock_digest",
            "Binding Lock canonical digest is invalid",
        )
    if expected_lock_digest and str(lock.get("lock_digest", "")) != str(
        expected_lock_digest
    ):
        _add(
            violations,
            severity,
            "CK-CAP-014",
            subject,
            "epoch_frozen_capability_binding",
            "stale Capability Binding Lock",
        )
    if expected_environment_digest and str(
        lock.get("environment_digest", "")
    ) != str(expected_environment_digest):
        _add(
            violations,
            severity,
            "CK-CAP-018",
            subject,
            "verification_environment",
            "Binding environment differs from the active environment",
        )


def _append_contract_identity_findings(
    violations, *, severity, bindings, subject
) -> None:
    contracts_by_ref: dict[str, set[str]] = {}
    for item in bindings:
        contracts_by_ref.setdefault(
            str(item.get("capability_ref", "")), set()
        ).add(str(item.get("capability_contract_digest", "")))
    for capability_ref, digests in sorted(contracts_by_ref.items()):
        if capability_ref and len(digests) > 1:
            _add(
                violations,
                severity,
                "CK-CAP-017",
                capability_ref,
                "capability_identity_uniqueness",
                "one capability_ref is bound to divergent semantic contracts",
            )


def _append_requirement_authority_findings(
    violations,
    *,
    severity,
    subject,
    bound,
    requirement,
    granted_credential_scopes,
) -> None:
    if requirement is None:
        return
    bound_effect = SIDE_EFFECT_RANK.get(
        str(bound.get("side_effect_class", "")), 99
    )
    ceiling = SIDE_EFFECT_RANK.get(
        str(requirement.get("side_effect_ceiling", "")), -1
    )
    if bound_effect > ceiling:
        _add(
            violations,
            severity,
            "CK-CAP-010",
            subject,
            "side_effect_ceiling",
            "bound tool exceeds the requirement side-effect ceiling",
        )
    bound_scopes = {str(value) for value in bound.get("credential_scope_ids") or ()}
    permitted = {
        str(value)
        for value in requirement.get("permitted_credential_scopes") or ()
    }
    granted = (
        None
        if granted_credential_scopes is None
        else {str(value) for value in granted_credential_scopes}
    )
    exceeded = (permitted and not bound_scopes.issubset(permitted)) or (
        granted is not None and not bound_scopes.issubset(granted)
    )
    if exceeded:
        _add(
            violations,
            severity,
            "CK-CAP-011",
            subject,
            "credential_scope_ceiling",
            "bound tool exceeds permitted credential scopes",
        )


def _append_invocation_findings(
    violations,
    *,
    severity,
    subject,
    invocation_present,
    call,
    bound,
    requirements,
    granted_credential_scopes,
) -> None:
    if invocation_present and bound is None:
        _add(
            violations,
            severity,
            "CK-CAP-001",
            subject,
            "bound_tool_surface",
            "tool invocation is absent from the active Binding Lock",
        )
    if bound is None:
        return
    declared_ref = str(
        call.get("capability_ref", "") or bound.get("capability_ref", "")
    )
    if declared_ref != str(bound.get("capability_ref", "")):
        _add(
            violations,
            severity,
            "CK-CAP-002",
            subject,
            "exact_capability_ref",
            "invocation capability_ref differs from the binding",
        )
    declared_contract = str(
        call.get("capability_contract_digest", "")
        or bound.get("capability_contract_digest", "")
    )
    if declared_contract != str(bound.get("capability_contract_digest", "")):
        _add(
            violations,
            severity,
            "CK-CAP-003",
            subject,
            "CapabilityContractV1",
            "invocation semantic contract differs from the binding",
        )
    for field in ("role", "phase", "call_context"):
        if call.get(field) is not None and str(call.get(field)) != str(
            bound.get(field, "")
        ):
            _add(
                violations,
                severity,
                "CK-CAP-009",
                subject,
                "role_phase_context",
                f"invocation {field} differs from the binding",
            )
    if str(bound.get("provider_status", "")) != "verified":
        _add(
            violations,
            severity,
            "CK-CAP-015",
            subject,
            "verified_provider",
            "binding uses a non-verified or revoked Provider",
        )
    requirement = requirements.get(str(bound.get("requirement_digest", "")))
    _append_requirement_authority_findings(
        violations,
        severity=severity,
        subject=subject,
        bound=bound,
        requirement=requirement,
        granted_credential_scopes=granted_credential_scopes,
    )


def _provider_tools_and_findings(
    violations, *, severity, lock, subject, provider_lock
) -> dict[str, dict]:
    if provider_lock is None:
        return {}
    provider = as_dict(provider_lock)
    try:
        from ari.skill_lock import SkillsLockV1

        actual_digest = canonical_digest(SkillsLockV1.model_validate(provider))
    except Exception:
        actual_digest = ""
    if actual_digest != str(lock.get("provider_lock_digest", "")):
        _add(
            violations,
            severity,
            "CK-CAP-005",
            subject,
            "ProviderLock",
            "Provider Lock/manifest identity differs from the binding",
        )
    return {
        str(item.get("tool_ref", "")): item
        for item in provider.get("tools") or ()
        if isinstance(item, dict)
    }


def _schema_digest_equal(tool: dict, bound: dict, field: str) -> bool:
    try:
        return normalize_sha256(str(tool.get(field, ""))) == str(
            bound.get(field, "")
        )
    except Exception:
        return False


def _append_locked_schema_findings(
    violations,
    *,
    severity,
    subject,
    bound,
    provider_lock,
    locked_tools,
) -> None:
    if bound is None or provider_lock is None:
        return
    tool = locked_tools.get(subject)
    if tool is None:
        _add(
            violations,
            severity,
            "CK-CAP-012",
            subject,
            "ProviderLock.tools",
            "bound external tool is absent from Provider Lock",
        )
        return
    for field in ("input_schema_digest", "output_schema_digest"):
        if not _schema_digest_equal(tool, bound, field):
            _add(
                violations,
                severity,
                "CK-CAP-006",
                subject,
                "ProviderLock.live_schema",
                f"live {field} differs from binding",
            )


def _live_schema_drifted(current: dict, locked: dict) -> bool:
    from ari.skill_lock import _json_digest

    input_digest = normalize_sha256(_json_digest(current.get("inputSchema") or {}))
    output_digest = normalize_sha256(_json_digest(current.get("outputSchema") or {}))
    return input_digest != normalize_sha256(
        str(locked.get("input_schema_digest", ""))
    ) or output_digest != normalize_sha256(
        str(locked.get("output_schema_digest", ""))
    )


def _append_live_findings(
    violations, *, severity, live_tools, locked_tools
) -> None:
    if live_tools is None or not locked_tools:
        return
    live = {
        str(item.get("tool_ref", "")): item
        for item in live_tools
        if isinstance(item, dict)
    }
    for tool_ref, locked in sorted(locked_tools.items()):
        current = live.get(tool_ref)
        if current is None:
            _add(
                violations,
                severity,
                "CK-CAP-007",
                tool_ref,
                "live_provider_parity",
                "Provider tool disappeared after snapshot",
            )
        elif _live_schema_drifted(current, locked):
            _add(
                violations,
                severity,
                "CK-CAP-006",
                tool_ref,
                "live_provider_parity",
                "live Provider schema drift detected",
            )


def _append_boundary_findings(
    violations,
    *,
    severity,
    subject,
    actor_selected,
    used_name_inference,
    provider_description_effective,
    revision_rebind,
) -> None:
    findings = (
        (
            actor_selected,
            "CK-CAP-004",
            "fixed_capability_binder",
            "an unauthorized actor selected the Provider/tool",
        ),
        (
            used_name_inference,
            "CK-CAP-013",
            "exact_semantic_binding",
            "tool-name substring inference was used as authority",
        ),
        (
            provider_description_effective,
            "CK-CAP-016",
            "untrusted_provider_description",
            "Provider description changed instruction or authority",
        ),
        (
            revision_rebind,
            "CK-CAP-008",
            "append_only_binding_revision",
            "Binding revision rebound an existing capability",
        ),
    )
    for active, code, rule, detail in findings:
        if active:
            _add(violations, severity, code, subject, rule, detail)


def validate_capability_binding_integrity(
    *,
    severity: dict[str, str],
    binding_lock,
    invocation=None,
    provider_lock=None,
    live_tools=None,
    expected_lock_digest: str | None = None,
    expected_environment_digest: str | None = None,
    granted_credential_scopes=None,
    actor_selected: bool = False,
    used_name_inference: bool = False,
    provider_description_effective: bool = False,
    revision_rebind: bool = False,
):
    lock = as_dict(binding_lock)
    call = as_dict(invocation) if invocation is not None else {}
    subject = str(
        call.get("tool_ref", "") or call.get("tool_name", "") or "binding"
    )
    violations: list = []
    _append_lock_findings(
        violations,
        severity=severity,
        lock=lock,
        subject=subject,
        expected_lock_digest=expected_lock_digest,
        expected_environment_digest=expected_environment_digest,
    )
    bindings = [as_dict(item) for item in lock.get("bindings") or ()]
    requirements = {
        str(item.get("requirement_digest", "")): as_dict(item)
        for item in lock.get("requirements") or ()
        if isinstance(item, dict)
    }
    _append_contract_identity_findings(
        violations,
        severity=severity,
        bindings=bindings,
        subject=subject,
    )
    bound = next(
        (
            item
            for item in bindings
            if str(item.get("tool_ref", "")) == subject
        ),
        None,
    )
    _append_invocation_findings(
        violations,
        severity=severity,
        subject=subject,
        invocation_present=invocation is not None,
        call=call,
        bound=bound,
        requirements=requirements,
        granted_credential_scopes=granted_credential_scopes,
    )
    locked_tools = _provider_tools_and_findings(
        violations,
        severity=severity,
        lock=lock,
        subject=subject,
        provider_lock=provider_lock,
    )
    _append_locked_schema_findings(
        violations,
        severity=severity,
        subject=subject,
        bound=bound,
        provider_lock=provider_lock,
        locked_tools=locked_tools,
    )
    _append_live_findings(
        violations,
        severity=severity,
        live_tools=live_tools,
        locked_tools=locked_tools,
    )
    _append_boundary_findings(
        violations,
        severity=severity,
        subject=subject,
        actor_selected=actor_selected,
        used_name_inference=used_name_inference,
        provider_description_effective=provider_description_effective,
        revision_rebind=revision_rebind,
    )
    return make_report("capability_integrity", violations)


__all__ = ["validate_capability_binding_integrity"]
