"""Declaration invariants that hold without launching a Provider.

The Provider catalog loader enforces these, but only once a live
``SKILLS.lock`` exists, which no test has. Checking them against the
checked-in manifests catches the same drift in CI: `emit_results` was
classified into `ari.result.emit/v1` for months while declaring none of the
permissions that contract requires.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from ari.assurance.contract import load_property_vocabulary
from ari.capability_binding.authority import load_role_capability_authority
from ari.capability_binding.ontology import load_capability_ontology
from ari.knowledge.catalog import load_knowledge_catalog
from ari.knowledge.models import KnowledgeAdmissionContextV1
from ari.protocols.integrity import ZERO_SHA256
from ari.providers.catalog import _granted_permissions, _side_effect
from ari.rqgm.knowledge_bridge import RQGMKnowledgeBridge
from ari.skill_manifest import load_skill_manifest


REPO = Path(__file__).resolve().parents[2]
CONFIG = Path(__file__).resolve().parents[1] / "config"


def _classified_tools():
    catalog = yaml.safe_load(
        (CONFIG / "providers" / "catalog.yaml").read_text(encoding="utf-8")
    )
    contracts = {
        item.capability_ref: item
        for item in load_capability_ontology(
            CONFIG / "capabilities" / "ontology.yaml"
        ).snapshot.contracts
    }
    for entry in catalog["entries"]:
        manifest = load_skill_manifest(REPO / str(entry["package"]) / "skill.yaml")
        tools = {item.name: item for item in manifest.resolved_tools()}
        for name, refs in (entry.get("declared_capability_refs_by_tool") or {}).items():
            for ref in refs:
                yield str(entry["package"]), name, tools[name], contracts[ref]


def test_every_classified_tool_declares_the_permissions_its_contract_requires():
    shortfalls = []
    for package, name, tool, contract in _classified_tools():
        policy = {"permissions": list(tool.permissions or ())}
        missing = sorted(
            set(contract.required_permissions) - _granted_permissions(policy)
        )
        if missing:
            shortfalls.append(f"{package}/{name} -> {contract.capability_ref}: {missing}")
    assert not shortfalls, "\n".join(shortfalls)


def test_every_classified_tool_matches_its_contract_side_effect_class():
    mismatches = []
    for package, name, tool, contract in _classified_tools():
        policy = {
            "side_effects": tool.side_effects,
            "permissions": list(tool.permissions or ()),
        }
        observed = _side_effect(policy)
        if observed != contract.side_effect_class:
            mismatches.append(
                f"{package}/{name} -> {contract.capability_ref}: "
                f"{observed} != {contract.side_effect_class}"
            )
    assert not mismatches, "\n".join(mismatches)


def test_the_router_accounts_for_every_catalog_entry():
    """A proposal of zero must say why, not look like an empty catalog."""

    ontology = load_capability_ontology(CONFIG / "capabilities" / "ontology.yaml")
    authority = load_role_capability_authority(
        CONFIG / "capabilities" / "role_authority.yaml",
        role="generator", phase="bfts", ontology=ontology.snapshot,
    )
    vocabulary, _ = load_property_vocabulary(
        CONFIG / "harnesses" / "property_vocabulary.yaml"
    )
    knowledge = load_knowledge_catalog(CONFIG / "knowledge_skills" / "catalog.yaml")
    context = KnowledgeAdmissionContextV1.create(
        role="generator", phase="bfts",
        task_tags=("benchmark", "c", "cpp", "cpu-performance", "linux", "phoronix",
                   "profiling", "simd", "x86"),
        permitted_side_effects=authority.permitted_side_effects,
        property_vocabulary=tuple(sorted(vocabulary)),
    )
    proposal = RQGMKnowledgeBridge.propose_applicable(
        run_id="invariant", epoch_id="epoch_000",
        research_contract_digest=ZERO_SHA256, catalog=knowledge.snapshot,
        context=context, router_prompt_hash=None,
    )

    accounted = len(proposal.proposed) + len(proposal.not_proposed)
    assert accounted == len(knowledge.snapshot.entries)
    assert {item.code for item in proposal.not_proposed} <= {
        "status_candidate",
        "status_deprecated",
        "status_revoked",
        "role_not_applicable",
        "phase_not_applicable",
        "task_tag_not_applicable",
    }
    # A Skill left out for its status must be one that really is not verified.
    statuses = {item.manifest.id: item.status for item in knowledge.snapshot.entries}
    for item in proposal.not_proposed:
        if item.code.startswith("status_"):
            assert statuses[item.skill_ref.id] != "verified"
