"""Shared pure helpers for K/C/A Constitutional Kernel amendments."""

from __future__ import annotations

from ari.protocols.integrity import canonical_digest
from ari.rqgm.kernel_types import Violation


SIDE_EFFECT_RANK = {
    "read-only": 0,
    "workspace-write": 1,
    "scheduler-submit": 2,
    "external-write": 3,
    "physical-actuation": 4,
}


def as_dict(obj) -> dict:
    if isinstance(obj, dict):
        return obj
    to_dict = getattr(obj, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    if hasattr(obj, "__dict__"):
        return dict(vars(obj))
    raise TypeError(f"kernel input must be dict-like, got {type(obj)!r}")


def full_digest_matches(value: dict, field: str) -> bool:
    if field not in value:
        return False
    payload = dict(value)
    recorded = str(payload.pop(field, ""))
    return recorded == canonical_digest(payload)


def actor_role(actor) -> str:
    if isinstance(actor, tuple) and len(actor) == 2:
        return str(actor[0])
    if isinstance(actor, dict):
        return str(actor.get("role", ""))
    return str(getattr(actor, "role", ""))


def violation(
    severity: dict[str, str],
    code: str,
    check: str,
    subject,
    rule_id: str,
    detail: str,
) -> Violation:
    return Violation(
        code=code,
        check=check,
        severity=severity[code],
        subject_ref=str(subject),
        rule_id=rule_id,
        detail=detail,
    )


__all__ = [
    "SIDE_EFFECT_RANK",
    "actor_role",
    "as_dict",
    "full_digest_matches",
    "violation",
]
