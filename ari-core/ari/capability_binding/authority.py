"""Reviewed role/phase authority independent of Knowledge content."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from ari.capability_binding.models import CapabilityOntologySnapshotV1


@dataclass(frozen=True)
class RoleCapabilityAuthority:
    capability_refs: tuple[str, ...]
    credential_scope_ids: tuple[str, ...]
    forbidden_capability_refs: tuple[str, ...]
    permitted_side_effects: tuple[str, ...]


def load_role_capability_authority(
    path: str | Path,
    *,
    role: str,
    phase: str,
    ontology: CapabilityOntologySnapshotV1,
) -> RoleCapabilityAuthority:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    try:
        document = raw["roles"][role]["phases"][phase]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"no reviewed Capability authority for {role}/{phase}") from exc
    refs = tuple(sorted(set(document.get("capability_refs") or ())))
    forbidden = tuple(sorted(set(document.get("forbidden_capability_refs") or ())))
    known = {item.capability_ref for item in ontology.contracts}
    unknown = (set(refs) | set(forbidden)) - known
    if unknown:
        raise ValueError(f"role authority references unknown capabilities: {sorted(unknown)}")
    if set(refs) & set(forbidden):
        raise ValueError("role authority cannot both allow and forbid a capability")
    effects = tuple(document.get("permitted_side_effects") or ())
    if not effects:
        raise ValueError("role authority requires an explicit side-effect ceiling")
    return RoleCapabilityAuthority(
        capability_refs=refs,
        credential_scope_ids=tuple(
            sorted(set(document.get("credential_scope_ids") or ()))
        ),
        forbidden_capability_refs=forbidden,
        permitted_side_effects=effects,
    )


__all__ = ["RoleCapabilityAuthority", "load_role_capability_authority"]
