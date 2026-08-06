"""Project brokered catalog leaves onto Capability Provisions.

The Provider catalog answers "which of ARI's own Providers offers this
capability".  It cannot answer the other half: a domain instrument that arrives
through a broker is not an ARI Provider and never appears in ``SKILLS.lock``,
so the capabilities the ontology already declares for those domains have a
contract and no supply.

``CapabilityProvisionV1`` has carried the shape for that case from the start --
``subject_tool_ref``, ``dispatch_tool_ref``, ``nested_source_lock_digests``,
with a validator demanding all three together -- but nothing built one.  This
module does.  The callable identity of a composite provision is the broker's
dispatch tool, because that is the only ``tool_ref`` the run lock contains and
the only one the authorization view can gate; the semantic identity is the leaf
behind it.

Two properties are the reason this is not a passthrough:

*Authority is the envelope of both hops.*  A call travels through the broker
and then into the leaf, so the side-effect class is the worse of the two
declarations and a contract's required permissions must be granted by both.
Declaring only the leaf's would let a run bind an external-write instrument
under a ceiling that forbids it; declaring only the broker's would erase what
the instrument actually does.

*The mapping is never the broker's to make.*  A descriptor's own
``capability_ref`` is the broker's namespace, not ARI's ontology.  It is
recorded on the provision as ``declared_capability_ref`` for drift detection
and is never read as a mapping: only the reviewed table in the checked-in
Provider catalog decides which ARI capability a leaf may supply.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ari.capability_binding.models import (
    CapabilityContractV1,
    CapabilityOntologySnapshotV1,
    CapabilityProvisionV1,
    CatalogStatus,
)
from ari.protocols.integrity import canonical_digest

# The broker's admission ladder.  A leaf may supply a capability only at or
# above the level its own policy demanded of it.
_ADMISSION_RANK = {
    "discovered": 0,
    "callable": 1,
    "reproducible": 2,
    "scientifically_admitted": 3,
}
# Reproducibility a leaf may claim, capped by how far its admission actually
# got.  A leaf that was only proven callable has no replay evidence, whatever
# its determinism field says.
_ADMISSION_REPRODUCIBILITY = {
    "discovered": "unknown",
    "callable": "unknown",
    "reproducible": "bounded",
    "scientifically_admitted": "exact",
}
_REPRODUCIBILITY_RANK = {"exact": 0, "bounded": 1, "external": 2, "unknown": 3}
_SIDE_EFFECT_RANK = {
    "read-only": 0,
    "workspace-write": 1,
    "scheduler-submit": 2,
    "external-write": 3,
    "physical-actuation": 4,
}
# The broker's determinism vocabulary is wider than the ontology's. "seeded" is
# reproducible only given the seed, which is what "conditional" already means
# here; it is not promoted to "deterministic".
_DETERMINISM_ALIASES = {"seeded": "conditional"}
_PERMISSION_ALIASES = {
    "process": "process-execute",
    "scheduler": "scheduler-submit",
    "network": "network-read",
}
_DETERMINISM_REPRODUCIBILITY = {
    "deterministic": "exact",
    "conditional": "bounded",
    "stochastic": "bounded",
    "live-data": "external",
}
# The broker hashes with ensure_ascii=True and sorts a few schema keys that are
# semantically sets. ARI's canonical_digest does neither, so the lock's
# self-authenticating digest has to be recomputed under the broker's own rule
# rather than ARI's.
_SET_LIKE_SCHEMA_KEYS = frozenset({"required", "enum", "type"})


class BrokeredCatalogError(ValueError):
    """Raised when a brokered catalog cannot be projected onto provisions."""


@dataclass(frozen=True)
class BrokerDispatchV1:
    """The ARI-side half of a composite: what the run can actually call.

    Everything here comes from the broker's own entry in the Provider catalog
    and from ``SKILLS.lock``; nothing is taken from the brokered catalog, which
    is data the broker produced about third-party software.
    """

    provider_id: str
    provider_identity_digest: str
    provider_status: CatalogStatus
    tool_ref: str
    provider_lock_digest: str
    manifest_digest: str
    registration_report_digest: str
    policy: dict[str, Any]
    credential_scope_ids: tuple[str, ...] = ()


def _canonical_value(value: Any, *, parent_key: str = "") -> Any:
    if isinstance(value, dict):
        return {
            str(key): _canonical_value(item, parent_key=str(key))
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        items = [_canonical_value(item) for item in value]
        if parent_key in _SET_LIKE_SCHEMA_KEYS:
            return sorted(items, key=_canonical_json)
        return items
    if isinstance(value, float) and not math.isfinite(value):
        raise BrokeredCatalogError("non-finite numbers are not canonical JSON")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise BrokeredCatalogError(f"value is not JSON-compatible: {type(value).__name__}")


def _canonical_json(value: Any) -> str:
    return json.dumps(
        _canonical_value(value),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def brokered_catalog_digest(document: dict[str, Any]) -> str:
    payload = {key: item for key, item in document.items() if key != "catalog_digest"}
    return "sha256:" + hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def load_brokered_catalog(path: str | Path) -> dict[str, Any]:
    """Read a broker catalog lock and re-derive the digest it claims.

    The lock is self-authenticating by design, so ARI recomputes rather than
    trusts it: a lock edited after the broker sealed it is refused here instead
    of becoming provisions whose provenance is fiction.  Structural invariants
    the broker's own model enforces are re-checked too, because that model is
    not importable from core.
    """

    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise BrokeredCatalogError(f"brokered catalog must be a regular file: {source}")
    try:
        document = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BrokeredCatalogError(f"brokered catalog is unreadable: {exc}") from exc
    if not isinstance(document, dict):
        raise BrokeredCatalogError("brokered catalog is not an object")
    if document.get("schema_version") != "ari.catalog-lock/v1":
        raise BrokeredCatalogError("unsupported brokered catalog schema")

    expected = brokered_catalog_digest(document)
    if str(document.get("catalog_digest") or "") != expected:
        raise BrokeredCatalogError("brokered catalog digest does not match its payload")

    sources = [str(item.get("source_id")) for item in (document.get("sources") or ())]
    tools = [str(item.get("tool_ref")) for item in (document.get("tools") or ())]
    admissions = [
        str(item.get("tool_ref")) for item in (document.get("admissions") or ())
    ]
    if len(sources) != len(set(sources)):
        raise BrokeredCatalogError("brokered catalog has duplicate source ids")
    if len(tools) != len(set(tools)):
        raise BrokeredCatalogError("brokered catalog has duplicate tool refs")
    if sorted(admissions) != sorted(tools):
        raise BrokeredCatalogError("brokered catalog needs one admission per tool")
    policy_digest = str(document.get("policy_digest") or "")
    for decision in document.get("admissions") or ():
        if str(decision.get("policy_digest") or "") != policy_digest:
            raise BrokeredCatalogError("admission was decided under a different policy")
    return document


def _leaf_side_effect(descriptor: dict[str, Any]) -> str:
    """Normalize the broker's vocabulary the way the Provider catalog does."""

    declared = str(descriptor.get("side_effects") or "stateful")
    permissions = {str(item) for item in (descriptor.get("permissions") or ())}
    if declared in {"read-only", "workspace-write"}:
        return declared
    if "scheduler" in permissions or "scheduler-submit" in permissions:
        return "scheduler-submit"
    return "external-write" if declared == "destructive" else "workspace-write"


def _dispatch_side_effect(policy: dict[str, Any]) -> str:
    declared = str(policy.get("side_effects") or "read-only")
    permissions = {str(item) for item in (policy.get("permissions") or ())}
    if declared in {"read-only", "workspace-write"}:
        return declared
    if "scheduler" in permissions or "scheduler-submit" in permissions:
        return "scheduler-submit"
    return "external-write" if declared == "destructive" else "workspace-write"


def _granted(permissions: Any) -> frozenset[str]:
    return frozenset(
        _PERMISSION_ALIASES.get(str(item), str(item)) for item in (permissions or ())
    )


def _admission(
    document: dict[str, Any], leaf: str
) -> tuple[dict[str, Any], str]:
    decision = next(
        (
            item
            for item in (document.get("admissions") or ())
            if str(item.get("tool_ref")) == leaf
        ),
        None,
    )
    if decision is None:
        raise BrokeredCatalogError(f"brokered leaf has no admission decision: {leaf}")
    level = str(decision.get("level") or "")
    required = str(decision.get("required_level") or "callable")
    if level not in _ADMISSION_RANK or required not in _ADMISSION_RANK:
        raise BrokeredCatalogError(f"unknown admission level for {leaf}")
    if _ADMISSION_RANK[level] < _ADMISSION_RANK[required]:
        raise BrokeredCatalogError(
            f"brokered leaf is admitted below its required level: {leaf} "
            f"({level} < {required})"
        )
    return decision, level


def _composite_provision(
    descriptor: dict[str, Any],
    *,
    contract: CapabilityContractV1,
    decision: dict[str, Any],
    level: str,
    dispatch: BrokerDispatchV1,
    nested: tuple[str, ...],
) -> CapabilityProvisionV1:
    leaf = str(descriptor["tool_ref"])
    determinism = str(descriptor.get("determinism") or "conditional")
    determinism = _DETERMINISM_ALIASES.get(determinism, determinism)
    grade = max(
        _DETERMINISM_REPRODUCIBILITY.get(determinism, "unknown"),
        _ADMISSION_REPRODUCIBILITY[level],
        key=lambda item: _REPRODUCIBILITY_RANK[item],
    )
    side_effect = max(
        _leaf_side_effect(descriptor),
        _dispatch_side_effect(dispatch.policy),
        key=lambda item: _SIDE_EFFECT_RANK[item],
    )
    if side_effect != contract.side_effect_class:
        raise BrokeredCatalogError(
            f"side-effect classification mismatch for {leaf} -> "
            f"{contract.capability_ref}"
        )
    # Both hops execute, so both must be able to honour the contract: the
    # broker because the runtime gates it, the leaf because it does the work.
    honoured = _granted(descriptor.get("permissions")) & _granted(
        dispatch.policy.get("permissions")
    )
    missing = sorted(set(contract.required_permissions) - honoured)
    if missing:
        raise BrokeredCatalogError(
            f"brokered route does not grant {contract.capability_ref} for {leaf}: "
            f"missing {missing}"
        )
    return CapabilityProvisionV1.create(
        provider_id=dispatch.provider_id,
        # The composite is a distinct supplier from the bare broker: it is the
        # broker *plus* one immutable leaf, and the digest says so.
        provider_identity_digest=canonical_digest(
            {
                "brokered_by": dispatch.provider_identity_digest,
                "leaf_identity": str(descriptor.get("leaf_identity") or leaf),
                "leaf_provider_digest": str(descriptor.get("provider_digest") or ""),
                "leaf_adapter_digest": str(descriptor.get("adapter_digest") or ""),
            }
        ),
        # Admission of the leaf was checked above; the catalog status carried
        # here is the broker's, because that is the entry ARI reviewed.
        provider_status=dispatch.provider_status,
        # The callable identity is the dispatch tool: the leaf is not in
        # SKILLS.lock, so the binder could never authorize it directly.
        tool_ref=dispatch.tool_ref,
        subject_tool_ref=leaf,
        dispatch_tool_ref=dispatch.tool_ref,
        nested_source_lock_digests=nested,
        declared_capability_ref=str(descriptor.get("capability_ref") or ""),
        capability_ref=contract.capability_ref,
        capability_contract_digest=contract.contract_digest,
        provider_lock_digest=dispatch.provider_lock_digest,
        manifest_digest=dispatch.manifest_digest,
        input_schema_digest=canonical_digest(descriptor.get("input_schema") or {}),
        output_schema_digest=canonical_digest(descriptor.get("output_schema") or {}),
        policy_digest=canonical_digest(
            {
                "dispatch": dispatch.policy,
                "leaf": {
                    "side_effects": descriptor.get("side_effects"),
                    "permissions": sorted(descriptor.get("permissions") or ()),
                    "determinism": descriptor.get("determinism"),
                },
            }
        ),
        schema_compatibility_evidence_digest=canonical_digest(
            {
                "admission_evidence": str(decision.get("evidence_digest") or ""),
                "admission_level": level,
                "contract": contract.contract_digest,
                "input_schema": descriptor.get("input_schema") or {},
                "output_schema": descriptor.get("output_schema") or {},
                "reviewed_mapping": contract.capability_ref,
            }
        ),
        side_effect_class=side_effect,
        determinism_class=determinism,
        context_requirement=str(dispatch.policy.get("context_requirement") or "none"),
        roles=tuple(sorted(dispatch.policy.get("roles") or ())),
        phases=tuple(sorted(dispatch.policy.get("phases") or ())),
        permissions=tuple(sorted(honoured)),
        credential_scope_ids=dispatch.credential_scope_ids,
        environment_requirements=contract.environment_requirements,
        resource_type=contract.resource_type,
        network_class=(
            "external"
            if _granted(descriptor.get("permissions")) & {"network-read", "network-write"}
            else "none"
        ),
        reproducibility_grade=grade,
        registration_report_digest=dispatch.registration_report_digest,
    )


def build_brokered_provisions(
    document: dict[str, Any],
    *,
    dispatch: BrokerDispatchV1,
    ontology: CapabilityOntologySnapshotV1,
    reviewed_capability_refs_by_leaf: dict[str, tuple[str, ...]],
) -> tuple[CapabilityProvisionV1, ...]:
    """Emit one composite provision per reviewed brokered leaf.

    ``reviewed_capability_refs_by_leaf`` is the checked-in reviewed table keyed
    by the leaf's ``tool_ref``.  Every key must resolve: a table naming a leaf
    the catalog does not contain is stale review, and silently skipping it
    would leave a capability unsupplied for a reason nobody could see.
    """

    contracts = {item.capability_ref: item for item in ontology.contracts}
    descriptors = {
        str(item.get("tool_ref")): item for item in (document.get("tools") or ())
    }
    sources = {
        str(item.get("source_id")): item for item in (document.get("sources") or ())
    }
    quarantined = {
        str(item.get("candidate_name") or "")
        for item in (document.get("quarantined") or ())
    }

    provisions: list[CapabilityProvisionV1] = []
    for leaf, refs in sorted(reviewed_capability_refs_by_leaf.items()):
        descriptor = descriptors.get(leaf)
        if descriptor is None:
            raise BrokeredCatalogError(
                f"reviewed brokered leaf is absent from the catalog: {leaf}"
            )
        if str(descriptor.get("name") or "") in quarantined:
            raise BrokeredCatalogError(f"brokered leaf is quarantined: {leaf}")
        decision, level = _admission(document, leaf)

        source_ids = sorted({str(item) for item in (descriptor.get("source_ids") or ())})
        if not source_ids:
            raise BrokeredCatalogError(f"brokered leaf names no source: {leaf}")
        absent = [item for item in source_ids if item not in sources]
        if absent:
            raise BrokeredCatalogError(f"brokered leaf names absent sources: {absent}")
        nested = tuple(
            sorted({str(sources[item]["source_digest"]) for item in source_ids})
        )

        for ref in sorted(set(refs)):
            contract = contracts.get(ref)
            if contract is None:
                raise BrokeredCatalogError(
                    f"brokered classification uses unknown capability: {ref}"
                )
            provisions.append(
                _composite_provision(
                    descriptor,
                    contract=contract,
                    decision=decision,
                    level=level,
                    dispatch=dispatch,
                    nested=nested,
                )
            )
    return tuple(provisions)


__all__ = [
    "BrokerDispatchV1",
    "BrokeredCatalogError",
    "brokered_catalog_digest",
    "build_brokered_provisions",
    "load_brokered_catalog",
]
