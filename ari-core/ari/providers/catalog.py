"""Read-only Provider catalog construction, run projection, and search."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

from ari.capability_binding.models import (
    CapabilityOntologySnapshotV1,
    CapabilityProvisionV1,
)
from ari.protocols.integrity import canonical_digest, normalize_sha256
from ari.providers.brokered import (
    BrokerDispatchV1,
    build_brokered_provisions,
    load_brokered_catalog,
)
from ari.providers.models import (
    CapabilityProviderIdentityV1,
    CapabilityProviderRegistrationReportV1,
    ProviderCatalogEntryV1,
    ProviderCatalogSnapshotV1,
    ProviderRegistrationGateV1,
    ProviderSourceV1,
    derive_provider_identity,
)
from ari.providers.registration import PROVIDER_REGISTRATION_GATES, registration_report
from ari.skill_lock import SkillsLockV1
from ari.skill_manifest import load_skill_manifest, manifest_digest


def build_provider_catalog_snapshot(
    *,
    catalog_source_revision: str,
    ontology_snapshot_digest: str,
    provider_lock_digest: str,
    providers: tuple[CapabilityProviderIdentityV1, ...],
    nested_source_lock_digests: tuple[str, ...] = (),
) -> ProviderCatalogSnapshotV1:
    return ProviderCatalogSnapshotV1.create(
        catalog_source_revision=catalog_source_revision,
        ontology_snapshot_digest=ontology_snapshot_digest,
        provider_lock_digest=provider_lock_digest,
        providers=tuple(sorted(providers, key=lambda item: (item.provider_id, item.package_version))),
        nested_source_lock_digests=tuple(sorted(nested_source_lock_digests)),
    )


def search_providers(
    snapshot: ProviderCatalogSnapshotV1, query: str = ""
) -> tuple[CapabilityProviderIdentityV1, ...]:
    needle = query.strip().lower()
    return tuple(
        item
        for item in snapshot.providers
        if not needle
        or needle in item.provider_id.lower()
        or needle in item.package.lower()
    )


def describe_provider(
    snapshot: ProviderCatalogSnapshotV1, provider_id: str
) -> CapabilityProviderIdentityV1 | None:
    return next((item for item in snapshot.providers if item.provider_id == provider_id), None)


@dataclass(frozen=True)
class LoadedProviderCatalog:
    snapshot: ProviderCatalogSnapshotV1
    provisions: tuple[CapabilityProvisionV1, ...]
    registration_reports: dict[str, CapabilityProviderRegistrationReportV1]


def _side_effect(policy: dict) -> str:
    """Normalize the existing manifest vocabulary without inspecting names."""

    declared = str(policy.get("side_effects", "read-only"))
    permissions = {str(item) for item in policy.get("permissions", ())}
    if declared in {"read-only", "workspace-write"}:
        return declared
    if "scheduler" in permissions or "scheduler-submit" in permissions:
        return "scheduler-submit"
    return "external-write" if declared == "destructive" else "workspace-write"


_PERMISSION_ALIASES = {
    "process": "process-execute",
    "scheduler": "scheduler-submit",
    "network": "network-read",
}


def _granted_permissions(policy: dict) -> frozenset[str]:
    """Normalize the existing manifest vocabulary onto the contract's.

    Same posture as ``_side_effect``: the mapping is a fixed table, not an
    inspection of tool names.
    """

    return frozenset(
        _PERMISSION_ALIASES.get(str(item), str(item))
        for item in (policy.get("permissions") or ())
    )


def _reproducibility(determinism: str) -> str:
    return {
        "deterministic": "exact",
        "conditional": "bounded",
        "stochastic": "bounded",
        "live-data": "external",
    }.get(determinism, "unknown")


def _entry_report(
    *, provider_id: str, manifest_sha256: str, verified: bool, evidence: dict
) -> CapabilityProviderRegistrationReportV1:
    gates = tuple(
        ProviderRegistrationGateV1(
            gate_id=gate,
            passed=verified,
            evidence_digest=canonical_digest({**evidence, "gate": gate}),
            detail=(
                "reviewed source plus run-lock evidence"
                if verified
                else "catalog candidate; admin promotion evidence is incomplete"
            ),
        )
        for gate in PROVIDER_REGISTRATION_GATES
    )
    return registration_report(
        provider_id=provider_id,
        manifest_sha256=manifest_sha256,
        gates=gates,
    )


def _brokered_lock_path(catalog_source: Path, brokered_config: dict) -> Path:
    """Resolve the federated lock ARI reads, honouring the broker's override.

    The broker selects its lock with ``ARI_TOOL_REGISTRY_LOCK`` and falls back
    to the one packaged beside it.  ARI must follow the same selection or the
    two disagree: ARI would project the packaged lock while the broker
    dispatches a site lock, and every composite provision would describe a leaf
    that is not the one being called.  A materialized site lock also carries
    absolute local paths, so it cannot live in the repository and the override
    is the only way to reach it.
    """

    override = os.environ.get("ARI_TOOL_REGISTRY_LOCK", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return (catalog_source.parent / str(brokered_config["catalog_lock"])).resolve()


def load_provider_catalog(
    path: str | Path,
    *,
    provider_lock: SkillsLockV1,
    ontology: CapabilityOntologySnapshotV1,
    configured_skills: tuple | list,
) -> LoadedProviderCatalog:
    """Project reviewed semantics onto the existing live ``SKILLS.lock``.

    The function never launches or discovers a Provider.  Entries absent from
    the run lock are not part of the run snapshot; entries present in the lock
    must match their checked-in manifest and exact package/version identity.
    """

    source = Path(path)
    raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    lock_by_runtime = {item.name: item for item in provider_lock.skills}
    cfg_by_runtime = {str(item.name): item for item in configured_skills}
    contracts = {item.capability_ref: item for item in ontology.contracts}
    lock_digest = canonical_digest(provider_lock)
    identities: list[CapabilityProviderIdentityV1] = []
    provisions: list[CapabilityProvisionV1] = []
    reports: dict[str, CapabilityProviderRegistrationReportV1] = {}

    for document in raw.get("entries", ()):
        runtime_name = str(document["runtime_name"])
        locked_provider = lock_by_runtime.get(runtime_name)
        if locked_provider is None:
            continue
        configured = cfg_by_runtime.get(runtime_name)
        if configured is None or not getattr(configured, "manifest_path", None):
            raise ValueError(f"locked Provider {runtime_name!r} has no canonical manifest")
        manifest = load_skill_manifest(configured.manifest_path)
        observed_manifest = "sha256:" + manifest_digest(manifest)
        expected_manifest = str(document["manifest_sha256"])
        if observed_manifest != expected_manifest:
            raise ValueError(f"Provider manifest drift: {runtime_name}")
        if (
            manifest.package != str(document["package"])
            or manifest.version != str(document["package_version"])
            or locked_provider.package != manifest.package
            or locked_provider.version != manifest.version
            or normalize_sha256(locked_provider.manifest_digest) != expected_manifest
        ):
            raise ValueError(f"Provider package identity drift: {runtime_name}")

        declared = {
            str(name): tuple(str(ref) for ref in refs)
            for name, refs in dict(
                document.get("declared_capability_refs_by_tool") or {}
            ).items()
        }
        for refs in declared.values():
            for ref in refs:
                if ref not in contracts:
                    raise ValueError(f"Provider classification uses unknown capability: {ref}")
        # A broker entry carries a second, nested lock: the catalog of leaves it
        # federates.  Read it before the entry is sealed so its digest becomes
        # part of this Provider's identity -- a leaf swapped behind the broker
        # then changes the catalog snapshot the binding request pins.
        brokered_document: dict | None = None
        brokered_config = document.get("brokered")
        if brokered_config is not None:
            brokered_document = load_brokered_catalog(
                _brokered_lock_path(source, brokered_config)
            )

        verified = str(document.get("status", "candidate")) == "verified"
        evidence = {
            "provider_lock_digest": lock_digest,
            "provider_digest": locked_provider.provider_digest,
            "manifest_sha256": expected_manifest,
            "classifications": declared,
            **(
                {"brokered_catalog_digest": brokered_document["catalog_digest"]}
                if brokered_document is not None
                else {}
            ),
        }
        report = _entry_report(
            provider_id=str(document["provider_id"]),
            manifest_sha256=expected_manifest,
            verified=verified,
            evidence=evidence,
        )
        reports[report.report_digest] = report
        entry = ProviderCatalogEntryV1.create(
            provider_id=str(document["provider_id"]),
            runtime_name=runtime_name,
            package=manifest.package,
            package_version=manifest.version,
            status=str(document.get("status", "candidate")),
            maintainer=str(document["maintainer"]),
            source=ProviderSourceV1.model_validate(document["source"]),
            manifest_sha256=expected_manifest,
            registration_report_digest=report.report_digest,
            declared_capability_refs_by_tool=declared,
            nested_source_lock_digests=tuple(
                sorted(
                    set(document.get("nested_source_lock_digests") or ())
                    | (
                        {brokered_document["catalog_digest"]}
                        if brokered_document is not None
                        else set()
                    )
                )
            ),
        )
        identity = derive_provider_identity(entry, provider_lock)
        identities.append(identity)

        locked_tools = {
            item.name: item
            for item in provider_lock.tools
            if item.skill_name == runtime_name
        }
        resolved_tools = {item.name: item for item in manifest.resolved_tools()}
        # A scope whose credential is absent from the environment confers no
        # authority: the child process is built from the present values only, and
        # the call context already filters the same way. Carrying the declared
        # set instead made every provision of a multi-domain Provider demand
        # every scope it might ever use -- binding an EDA tool required granting
        # an IBM Quantum credential that is not even set. Presence is observed
        # at lock time and is part of the frozen Provider Lock, so a token that
        # appears later changes the lock rather than sneaking past this.
        scope_ids = tuple(
            sorted(
                item.scope_id
                for item in locked_provider.credential_scopes
                if item.present_env
            )
        )
        for tool_name, refs in sorted(declared.items()):
            locked_tool = locked_tools.get(tool_name)
            resolved = resolved_tools.get(tool_name)
            if locked_tool is None or resolved is None:
                raise ValueError(f"classified Provider tool is absent: {runtime_name}/{tool_name}")
            policy = dict(locked_tool.policy)
            normalized_side_effect = _side_effect(policy)
            for ref in sorted(refs):
                contract = contracts[ref]
                if normalized_side_effect != contract.side_effect_class:
                    raise ValueError(
                        f"side-effect classification mismatch for {runtime_name}/{tool_name} -> {ref}"
                    )
                # The contract states the authority the capability needs. A tool
                # classified into it while declaring less is a projection that
                # cannot be honoured at call time.
                missing = sorted(
                    set(contract.required_permissions) - _granted_permissions(policy)
                )
                if missing:
                    raise ValueError(
                        f"declared permissions do not cover {ref} for "
                        f"{runtime_name}/{tool_name}: missing {missing}"
                    )
                provisions.append(
                    CapabilityProvisionV1.create(
                        provider_id=entry.provider_id,
                        provider_identity_digest=identity.identity_digest,
                        provider_status=entry.status,
                        tool_ref=locked_tool.tool_ref,
                        declared_capability_ref=str(locked_tool.capability_ref or ""),
                        capability_ref=ref,
                        capability_contract_digest=contract.contract_digest,
                        provider_lock_digest=lock_digest,
                        manifest_digest=expected_manifest,
                        input_schema_digest=normalize_sha256(
                            locked_tool.input_schema_digest
                        ),
                        output_schema_digest=normalize_sha256(
                            locked_tool.output_schema_digest
                        ),
                        policy_digest=canonical_digest(policy),
                        schema_compatibility_evidence_digest=canonical_digest(
                            {
                                "contract": contract.contract_digest,
                                "input_schema": locked_tool.input_schema,
                                "output_schema": locked_tool.output_schema,
                                "reviewed_mapping": ref,
                            }
                        ),
                        side_effect_class=normalized_side_effect,
                        determinism_class=str(
                            policy.get("determinism", resolved.determinism)
                        ),
                        context_requirement=str(
                            policy.get("context_requirement", resolved.context_requirement)
                        ),
                        phases=tuple(sorted(policy.get("phases") or resolved.phases)),
                        permissions=tuple(sorted(policy.get("permissions") or ())),
                        credential_scope_ids=scope_ids,
                        environment_requirements=contract.environment_requirements,
                        resource_type=contract.resource_type,
                        network_class=(
                            "external" if "network" in set(policy.get("permissions") or ())
                            else "none"
                        ),
                        reproducibility_grade=_reproducibility(
                            str(policy.get("determinism", resolved.determinism))
                        ),
                        registration_report_digest=report.report_digest,
                    )
                )

        if brokered_document is not None:
            dispatch_name = str(brokered_config["dispatch_tool"])
            dispatch_tool = locked_tools.get(dispatch_name)
            if dispatch_tool is None:
                raise ValueError(
                    f"broker dispatch tool is absent from the run lock: "
                    f"{runtime_name}/{dispatch_name}"
                )
            # A composite binding is gated on which leaf the call names. That
            # gate is defeated by a direct binding on the same tool_ref: the
            # authorization view falls back to it, and a call naming a leaf
            # nobody bound is admitted under the direct binding's authority.
            # The combination is refused here rather than defended against
            # later, because a broker's dispatch surface supplying an ontology
            # capability in its own right is not a thing that should be
            # expressible -- and a defence in the view would have to choose
            # between honouring the direct binding and honouring the gate.
            conflicting = sorted(
                set(declared) & {dispatch_name, *(
                    str(item) for item in (brokered_config.get("lifecycle_tools") or ())
                )}
            )
            if conflicting:
                raise ValueError(
                    f"broker dispatch surface cannot also be classified directly: "
                    f"{runtime_name}/{conflicting}"
                )
            lifecycle_names = tuple(
                str(item) for item in (brokered_config.get("lifecycle_tools") or ())
            )
            absent_lifecycle = [
                item for item in lifecycle_names if item not in locked_tools
            ]
            if absent_lifecycle:
                raise ValueError(
                    f"broker lifecycle tools are absent from the run lock: "
                    f"{runtime_name}/{absent_lifecycle}"
                )
            provisions.extend(
                build_brokered_provisions(
                    brokered_document,
                    dispatch=BrokerDispatchV1(
                        provider_id=entry.provider_id,
                        provider_identity_digest=identity.identity_digest,
                        provider_status=entry.status,
                        tool_ref=dispatch_tool.tool_ref,
                        provider_lock_digest=lock_digest,
                        manifest_digest=expected_manifest,
                        registration_report_digest=report.report_digest,
                        policy=dict(dispatch_tool.policy),
                        credential_scope_ids=scope_ids,
                        subject_argument=str(
                            brokered_config.get("subject_argument") or "tool_ref"
                        ),
                        lifecycle_tool_refs=tuple(
                            sorted(
                                locked_tools[item].tool_ref for item in lifecycle_names
                            )
                        ),
                    ),
                    ontology=ontology,
                    reviewed_capability_refs_by_leaf={
                        str(leaf): tuple(str(ref) for ref in refs)
                        for leaf, refs in dict(
                            brokered_config.get(
                                "declared_capability_refs_by_brokered_tool"
                            )
                            or {}
                        ).items()
                    },
                )
            )

    snapshot = build_provider_catalog_snapshot(
        catalog_source_revision=str(raw.get("catalog_source_revision", "unknown")),
        ontology_snapshot_digest=ontology.snapshot_digest,
        provider_lock_digest=lock_digest,
        providers=tuple(identities),
        nested_source_lock_digests=tuple(
            sorted(
                digest
                for item in identities
                for digest in item.nested_source_lock_digests
            )
        ),
    )
    return LoadedProviderCatalog(
        snapshot=snapshot,
        provisions=tuple(
            sorted(
                provisions,
                key=lambda item: (
                    item.capability_ref,
                    item.tool_ref,
                    # Composites share one dispatch tool_ref, so the leaf is
                    # what separates them.
                    item.subject_tool_ref or "",
                ),
            )
        ),
        registration_reports=reports,
    )


__all__ = [
    "LoadedProviderCatalog",
    "build_provider_catalog_snapshot",
    "describe_provider",
    "load_provider_catalog",
    "search_providers",
]
