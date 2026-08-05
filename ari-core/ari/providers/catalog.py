"""Read-only Provider catalog construction, run projection, and search."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from ari.capability_binding.models import (
    CapabilityOntologySnapshotV1,
    CapabilityProvisionV1,
)
from ari.protocols.integrity import canonical_digest, normalize_sha256
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
        verified = str(document.get("status", "candidate")) == "verified"
        evidence = {
            "provider_lock_digest": lock_digest,
            "provider_digest": locked_provider.provider_digest,
            "manifest_sha256": expected_manifest,
            "classifications": declared,
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
                sorted(document.get("nested_source_lock_digests") or ())
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
        scope_ids = tuple(sorted(item.scope_id for item in locked_provider.credential_scopes))
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
            sorted(provisions, key=lambda item: (item.capability_ref, item.tool_ref))
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
