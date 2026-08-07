"""What stops a Provider from claiming a capability it cannot honour.

The catalog turns a reviewed ``declared_capability_refs_by_tool`` entry into a
CapabilityProvisionV1 only if the tool's locked policy agrees with the contract
on two points: the side-effect class must match exactly, and the tool must
already declare every permission the contract requires. Both refusals were
untested, which matters more than usual here -- a classification that the loader
would wave through is a Provider claiming authority it never declared, and every
requirement bound to that capability inherits the claim.

The web Provider is the subject because its whole surface was unclassified until
now, so it is the one place where the checked-in table and the refusals can be
read against each other.
"""

from __future__ import annotations

import os

import pytest
import yaml

from ari.protocols.integrity import canonical_digest


WEB_PACKAGE = "ari-skill-web"
RUNTIME = "web-skill"


def _repo_root():
    from pathlib import Path

    return Path(__file__).resolve().parents[2]


def _contract(**updates):
    from ari.capability_binding.models import CapabilityContractV1

    values = dict(
        capability_ref="ari.literature.search/v1",
        contract_version="v1",
        title="Search scientific literature",
        description="Query an admitted literature index",
        side_effect_class="workspace-write",
        determinism_class="live-data",
        context_requirement="run",
        required_permissions=("network-read",),
        compatibility_rules=(),
    )
    values.update(updates)
    return CapabilityContractV1.create(**values)


def _ontology(*contracts):
    from ari.capability_binding.models import CapabilityOntologySnapshotV1

    return CapabilityOntologySnapshotV1.create(
        source_revision="test/1",
        property_vocabulary_version="v1",
        contracts=tuple(sorted(contracts, key=lambda item: item.capability_ref)),
    )


def _manifest():
    from ari.skill_manifest import load_skill_manifest

    package = _repo_root() / WEB_PACKAGE
    if not (package / "skill.yaml").is_file():  # pragma: no cover
        pytest.skip("web package is absent from this checkout")
    return package, load_skill_manifest(str(package / "skill.yaml"))


def _provider_lock(manifest, *, policy_overrides=None):
    """A run lock carrying the manifest's own tools, policy included."""

    from ari.skill_lock import (
        LockedCredentialScopeV1,
        LockedSkillV1,
        LockedToolV1,
        SkillsLockV1,
    )
    from ari.skill_manifest import manifest_digest

    overrides = policy_overrides or {}
    tools = []
    for item in manifest.resolved_tools():
        policy = {
            "side_effects": item.side_effects,
            "permissions": list(item.permissions),
            "phases": list(item.phases),
            "determinism": item.determinism,
            "context_requirement": item.context_requirement,
        }
        policy.update(overrides.get(item.name, {}))
        tools.append(
            LockedToolV1(
                tool_ref=f"{RUNTIME}::{item.name}@1",
                name=item.name,
                skill_name=RUNTIME,
                capability_ref=item.capability_ref,
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                input_schema_digest=canonical_digest({"type": "object"}),
                output_schema_digest=canonical_digest({"type": "object"}),
                policy=policy,
            )
        )

    scopes = []
    for scope in manifest.credential_scopes:
        declared = sorted(set(scope.required_env) | set(scope.optional_env))
        present = [name for name in declared if os.environ.get(name)]
        scopes.append(
            LockedCredentialScopeV1(
                scope_id=scope.id,
                declared_env=declared,
                present_env=present,
                identity_digest=canonical_digest(
                    {"scope_id": scope.id, "present_env": present}
                ),
            )
        )
    skill = LockedSkillV1(
        name=RUNTIME,
        package=manifest.package,
        version=manifest.version,
        entrypoint="python -m server",
        manifest_digest="sha256:" + manifest_digest(manifest),
        provider_digest=canonical_digest({"provider": RUNTIME}),
        configured_phases=["bfts"],
        environment_policy="complete",
        credential_scopes=scopes,
        tool_refs=sorted(item.tool_ref for item in tools),
    )
    return SkillsLockV1(
        run_id="run-1",
        registry_digest=canonical_digest({"registry": "test"}),
        skills=[skill],
        tools=tools,
        phase_active_tools={"bfts": sorted(item.tool_ref for item in tools)},
    )


def _load(tmp_path, manifest, package, *, declared_by_tool, ontology, overrides=None):
    from ari.config import SkillConfig
    from ari.providers.catalog import load_provider_catalog
    from ari.skill_manifest import manifest_digest

    document = {
        "schema_version": 1,
        "catalog_source_revision": "test/1",
        "entries": [
            {
                "provider_id": "ari.provider.web",
                "runtime_name": RUNTIME,
                "package": manifest.package,
                "package_version": manifest.version,
                "status": "verified",
                "maintainer": "ARI maintainers",
                "source": {
                    "repository": "https://github.com/kotama7/ARI.git",
                    "full_commit_sha": "0" * 40,
                    "package_sha256": "sha256:" + ("f" * 64),
                    "license": "MIT",
                },
                "manifest_sha256": "sha256:" + manifest_digest(manifest),
                "declared_capability_refs_by_tool": dict(declared_by_tool),
            }
        ],
    }
    path = tmp_path / "catalog.yaml"
    path.write_text(yaml.safe_dump(document, sort_keys=True), encoding="utf-8")
    return load_provider_catalog(
        path,
        provider_lock=_provider_lock(manifest, policy_overrides=overrides),
        ontology=ontology,
        configured_skills=(
            SkillConfig(
                name=RUNTIME,
                path=str(package),
                package=manifest.package,
                version=manifest.version,
                manifest_path=str(package / "skill.yaml"),
            ),
        ),
    )


def test_a_matching_tool_becomes_a_provision(tmp_path):
    package, manifest = _manifest()
    loaded = _load(
        tmp_path,
        manifest,
        package,
        declared_by_tool={"search_papers": ["ari.literature.search/v1"]},
        ontology=_ontology(_contract()),
        overrides={
            "search_papers": {
                "side_effects": "workspace-write",
                "permissions": ["workspace-write", "network"],
            }
        },
    )
    (provision,) = loaded.provisions
    assert provision.capability_ref == "ari.literature.search/v1"
    # The manifest's own unversioned hint is carried, not used to bind.
    assert provision.declared_capability_ref == "ari.literature.search"


def test_a_read_only_tool_cannot_claim_a_workspace_write_capability(tmp_path):
    """The shape rerank_retrieval_records is in.

    Its declared ref aliases onto ari.literature.search/v1, but reranking
    consumes retrieval records instead of fetching them, so its locked policy is
    read-only. Classifying it would let a requirement bind a capability the tool
    does not implement.
    """

    package, manifest = _manifest()
    with pytest.raises(ValueError, match="side-effect classification mismatch"):
        _load(
            tmp_path,
            manifest,
            package,
            declared_by_tool={"rerank_retrieval_records": ["ari.literature.search/v1"]},
            ontology=_ontology(_contract()),
            overrides={
                "rerank_retrieval_records": {
                    "side_effects": "read-only",
                    "permissions": ["model"],
                }
            },
        )


def test_a_tool_short_of_the_contract_permissions_is_refused(tmp_path):
    package, manifest = _manifest()
    with pytest.raises(ValueError, match="declared permissions do not cover"):
        _load(
            tmp_path,
            manifest,
            package,
            declared_by_tool={"search_papers": ["ari.literature.search/v1"]},
            ontology=_ontology(_contract()),
            overrides={
                "search_papers": {
                    "side_effects": "workspace-write",
                    # No network permission: the contract's network-read is unmet.
                    "permissions": ["workspace-write"],
                }
            },
        )


def test_the_permission_alias_table_is_what_lets_network_satisfy_network_read(tmp_path):
    """`network` is the manifest vocabulary; `network-read` is the contract's."""

    from ari.providers.catalog import _granted_permissions

    assert "network-read" in _granted_permissions({"permissions": ["network"]})
    assert "network-read" not in _granted_permissions({"permissions": ["workspace-write"]})


def test_the_checked_in_web_classification_matches_what_the_manifest_declares():
    """Every classified web tool's own hint must resolve to the ref it is bound to.

    The catalog is the only thing that creates a provision, so a table entry
    that disagrees with the manifest's `capability_ref` is a silent divergence
    between what the Provider says it does and what the run believes it does.
    """

    from ari.capability_binding.ontology import load_capability_ontology

    root = _repo_root()
    catalog = yaml.safe_load(
        (root / "ari-core" / "config" / "providers" / "catalog.yaml").read_text()
    )
    entry = next(e for e in catalog["entries"] if e["runtime_name"] == RUNTIME)
    declared = entry["declared_capability_refs_by_tool"]
    assert declared, "the web Provider surface is classified"

    package, manifest = _manifest()
    hints = {item.name: item.capability_ref for item in manifest.resolved_tools()}
    ontology = load_capability_ontology(
        root / "ari-core" / "config" / "capabilities" / "ontology.yaml"
    )
    for tool_name, refs in declared.items():
        assert tool_name in hints, f"{tool_name} is not a tool of this Provider"
        canonical = ontology.normalize(hints[tool_name])
        assert canonical in refs, (
            f"{tool_name} declares {hints[tool_name]} which normalizes to "
            f"{canonical}, but the catalog binds it to {refs}"
        )
