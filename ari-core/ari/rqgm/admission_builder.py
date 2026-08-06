"""Trusted orchestration of pure K/C/A binders before epoch_000.

This module owns call order only.  Catalog loading, admission, binding, and
Harness resolution remain in their RQGM-independent product packages.
"""

from __future__ import annotations

import json
from pathlib import Path

from ari.protocols.integrity import ZERO_SHA256, canonical_digest


def _research_contract(checkpoint_dir: Path):
    from ari.research_contract import parse_research_contract_document

    path = checkpoint_dir / "idea.json"
    if path.is_symlink() or not path.is_file():
        raise ValueError("KCA admission requires a regular idea.json")
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("idea.json must be an object")
    contract = parse_research_contract_document(document)
    if contract is None:
        raise ValueError(
            "KCA admission requires the mint-once typed ResearchContractV1; "
            "legacy idea.json cannot be upgraded implicitly"
        )
    return contract


def _router_prompt_hash(state) -> str | None:
    if state is None:
        return None
    component = state.components.get("proposal_router_v1")
    prompt_id = getattr(component, "prompt_id", None)
    prompt = state.prompts.get(prompt_id) if prompt_id else None
    value = str(getattr(prompt, "prompt_sha256", "") or "")
    return value or None


def build_kca_admission(
    *,
    cfg,
    checkpoint_dir: str | Path,
    run_id: str,
    mcp,
    foundation_state,
    task_tags: tuple[str, ...] = (),
):
    """Resolve and return the complete immutable baseline bundle.

    Provider discovery is completed before entering the pure Capability
    Binder.  No catalog is fetched from a branch, URL, or ``latest`` alias.
    """

    from ari.assurance.catalog import load_harness_catalog
    from ari.assurance.contract import (
        build_verification_contract,
        load_property_vocabulary,
    )
    from ari.assurance.resolver import (
        mint_baseline_harness_lock,
        resolve_harness_suite,
    )
    from ari.capability_binding.authority import load_role_capability_authority
    from ari.capability_binding.environment import build_environment_snapshot
    from ari.capability_binding.models import CapabilityBindingRequestV1
    from ari.capability_binding.ontology import load_capability_ontology
    from ari.capability_binding.resolver import bind_capabilities
    from ari.config.finder import package_config_root
    from ari.config.kca_runtime import resolve_kca_modes
    from ari.knowledge.catalog import load_knowledge_catalog
    from ari.knowledge.models import KnowledgeAdmissionContextV1
    from ari.providers.catalog import load_provider_catalog
    from ari.rqgm.admission import (
        KCAModeSnapshotV1,
        build_run_admission,
    )
    from ari.rqgm.knowledge_bridge import RQGMKnowledgeBridge

    checkpoint = Path(checkpoint_dir)
    contract = _research_contract(checkpoint)
    root = package_config_root()
    modes = resolve_kca_modes(
        cfg,
        required_verification=bool(contract.metric_contract.correctness_required),
    )
    mode_snapshot = KCAModeSnapshotV1(
        knowledge=modes.knowledge,
        capability_binding=modes.capability_binding,
        assurance=modes.assurance,
    )
    documents: dict = {"research_contract.json": contract}
    identities: dict[str, str | None] = {
        "knowledge_catalog_snapshot_digest": None,
        "knowledge_skill_lock_digest": None,
        "capability_ontology_snapshot_digest": None,
        "provider_catalog_snapshot_digest": None,
        "provider_lock_digest": None,
        "capability_binding_lock_digest": None,
        "verification_contract_digest": None,
        "harness_catalog_snapshot_digest": None,
        "baseline_harness_lock_digest": None,
        "active_harness_lock_digest": None,
        "verification_environment_digest": None,
    }

    needs_ontology = modes.knowledge != "off" or modes.capability_binding != "legacy"
    ontology = None
    authority = None
    if needs_ontology:
        ontology = load_capability_ontology(root / "capabilities" / "ontology.yaml")
        documents["capability_ontology_snapshot.json"] = ontology.snapshot
        identities["capability_ontology_snapshot_digest"] = ontology.snapshot.snapshot_digest
        authority = load_role_capability_authority(
            root / "capabilities" / "role_authority.yaml",
            role="generator",
            phase="bfts",
            ontology=ontology.snapshot,
        )

    knowledge_lock = None
    if modes.knowledge != "off":
        property_vocabulary, _ = load_property_vocabulary(
            root / "harnesses" / "property_vocabulary.yaml"
        )
        loaded_knowledge = load_knowledge_catalog(
            root / "knowledge_skills" / "catalog.yaml"
        )
        context = KnowledgeAdmissionContextV1.create(
            role="generator",
            phase="bfts",
            task_tags=tuple(sorted(set(task_tags))),
            permitted_side_effects=authority.permitted_side_effects,
            property_vocabulary=tuple(sorted(property_vocabulary)),
        )
        proposal = RQGMKnowledgeBridge.propose_applicable(
            run_id=run_id,
            epoch_id="epoch_000",
            research_contract_digest=contract.contract_digest,
            catalog=loaded_knowledge.snapshot,
            context=context,
            router_prompt_hash=_router_prompt_hash(foundation_state),
        )
        knowledge_lock = RQGMKnowledgeBridge.fixed_admit(
            proposal=proposal,
            catalog=loaded_knowledge.snapshot,
            ontology=ontology.snapshot,
            context=context,
            mode=modes.knowledge,
        )
        admitted_digests = {item.body_sha256 for item in knowledge_lock.admitted}
        bodies = {
            digest: loaded_knowledge.body_store.get_text(digest)
            for digest in sorted(admitted_digests)
        }
        documents.update(
            {
                "knowledge_catalog_snapshot.json": loaded_knowledge.snapshot,
                "knowledge_selection_proposal.json": proposal,
                "knowledge_admission_context.json": context,
                "knowledge_skill_lock.json": knowledge_lock,
                "knowledge_bodies.json": bodies,
            }
        )
        identities["knowledge_catalog_snapshot_digest"] = (
            loaded_knowledge.snapshot.snapshot_digest
        )
        identities["knowledge_skill_lock_digest"] = knowledge_lock.lock_digest

    environment = None
    if modes.capability_binding != "legacy":
        # The MCP client owns live discovery and the canonical Provider Lock.
        # It is completed before the prompt-free fixed binder is invoked.
        if getattr(mcp, "skills_lock", None) is None:
            mcp.list_tools(phase="bfts")
        provider_lock = getattr(mcp, "skills_lock", None)
        if provider_lock is None:
            raise ValueError("Capability Binding requires the existing SKILLS.lock")
        if provider_lock.run_id and provider_lock.run_id not in {
            run_id,
            checkpoint.name,
        }:
            raise ValueError("Provider Lock belongs to another run")
        loaded_providers = load_provider_catalog(
            root / "providers" / "catalog.yaml",
            provider_lock=provider_lock,
            ontology=ontology.snapshot,
            configured_skills=tuple(getattr(cfg, "skills", ()) or ()),
        )
        environment = build_environment_snapshot(cfg, provider_lock)
        requirements = (
            knowledge_lock.capability_requirements if knowledge_lock is not None else ()
        )
        request = CapabilityBindingRequestV1.create(
            run_id=run_id,
            epoch_id="epoch_000",
            research_contract_digest=contract.contract_digest,
            knowledge_skill_lock_digest=(
                knowledge_lock.lock_digest if knowledge_lock is not None else ZERO_SHA256
            ),
            ontology_snapshot_digest=ontology.snapshot.snapshot_digest,
            provider_catalog_snapshot_digest=loaded_providers.snapshot.snapshot_digest,
            provider_lock_digest=canonical_digest(provider_lock),
            requirements=requirements,
            provisions=loaded_providers.provisions,
            available_tool_refs=tuple(
                sorted(provider_lock.phase_active_tools.get("bfts", ()))
            ),
            role="generator",
            phase="bfts",
            call_context="node",
            authorized_capability_refs=authority.capability_refs,
            granted_credential_scopes=authority.credential_scope_ids,
            forbidden_capability_refs=authority.forbidden_capability_refs,
            user_disabled_tools=tuple(sorted(provider_lock.disabled_tools)),
            environment=environment,
            mode=modes.capability_binding,
        )
        binding_lock, binding_report = bind_capabilities(request)
        documents.update(
            {
                "provider_catalog_snapshot.json": loaded_providers.snapshot,
                "provider_lock.json": provider_lock,
                "capability_binding_request.json": request,
                "capability_binding_lock.json": binding_lock,
                "capability_binding_report.json": binding_report,
            }
        )
        identities.update(
            {
                "provider_catalog_snapshot_digest": loaded_providers.snapshot.snapshot_digest,
                "provider_lock_digest": canonical_digest(provider_lock),
                "capability_binding_lock_digest": binding_lock.lock_digest,
            }
        )

    oracle_bundle_digest = None
    if modes.assurance != "off":
        property_vocabulary, property_vocabulary_digest = load_property_vocabulary(
            root / "harnesses" / "property_vocabulary.yaml"
        )
        obligations = (
            knowledge_lock.evaluation_obligations if knowledge_lock is not None else ()
        )
        verification = build_verification_contract(
            run_id=run_id,
            research_contract=contract,
            knowledge_obligations=obligations,
            property_vocabulary=property_vocabulary,
            property_vocabulary_digest=property_vocabulary_digest,
        )
        harness_catalog = load_harness_catalog(root / "harnesses" / "catalog.yaml")
        if environment is None:
            # Assurance-only mode still needs a frozen environment. Provider
            # discovery supplies the existing execution substrate identity but
            # does not create a Capability Binding authority view.
            if getattr(mcp, "skills_lock", None) is None:
                mcp.list_tools(phase="bfts")
            provider_lock = getattr(mcp, "skills_lock", None)
            if provider_lock is None:
                raise ValueError("Assurance requires a frozen execution environment")
            environment = build_environment_snapshot(cfg, provider_lock)
        suite = resolve_harness_suite(
            contract=verification,
            catalog=harness_catalog,
            environment=environment,
            enforce_coverage=modes.assurance == "enforce",
        )
        manifest_by_digest = {
            item.manifest_digest: item for item in harness_catalog.manifests
        }
        oracle_bundle_digest = canonical_digest(
            tuple(
                manifest_by_digest[digest].oracle.sha256
                for digest in suite.harness_manifest_digests
            )
        )
        baseline = mint_baseline_harness_lock(
            run_id=run_id,
            research_contract_digest=contract.contract_digest,
            contract=verification,
            catalog=harness_catalog,
            environment=environment,
            oracle_bundle_digest=oracle_bundle_digest,
            suite=suite,
        )
        documents.update(
            {
                "verification_contract.json": verification,
                "harness_catalog_snapshot.json": harness_catalog,
                "harness_suite.json": suite,
                "baseline_harness_lock.json": baseline,
                "verification_environment.json": environment,
            }
        )
        identities.update(
            {
                "verification_contract_digest": verification.contract_digest,
                "harness_catalog_snapshot_digest": harness_catalog.snapshot_digest,
                "baseline_harness_lock_digest": baseline.lock_digest,
                "active_harness_lock_digest": baseline.lock_digest,
                "verification_environment_digest": environment.identity_digest,
            }
        )

    return build_run_admission(
        run_id=run_id,
        modes=mode_snapshot,
        research_contract=contract,
        documents=documents,
        identity_fields=identities,
        oracle_bundle_digest=oracle_bundle_digest,
    )


__all__ = ["build_kca_admission"]
