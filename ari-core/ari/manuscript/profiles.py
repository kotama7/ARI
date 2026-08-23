"""Versioned requirement profiles and fixed applicability policy.

Two kinds of profile live here.

``generic_empirical_v1`` is built in code and is the root of every lineage.  Its
``profile_digest`` is pinned by persisted records (authoring bindings, readiness
reports, harness evidence), so the built profile — and therefore
``ManuscriptRequirementProfileV1`` itself — is append-only in the strict sense
that nothing may change its canonical payload.

A venue or project profile is declared as a ``ManuscriptVenueProfileV1`` JSON
artifact under :data:`VENUE_PROFILE_DIR` (one file per profile, named
``<profile_id>.json``) and is composed *explicitly*: it names its parents at
their exact digests and resolution happens at read time.  Resolution yields an
ordinary ``ManuscriptRequirementProfileV1``, so its ``profile_digest`` is the
resolved digest and every existing profile consumer is unchanged.

Composition rules (all explicit, none implicit):

* parents are applied in ``extends`` order; a later parent replaces an earlier
  parent's requirement with the same ``requirement_id``;
* ``removed_requirement_ids`` then drops parent requirements — removal is
  expressible but never implicit: a requirement the venue simply does not
  mention survives, and every removed id must exist in the merged parents;
* the venue's own ``requirements`` are applied last: an existing
  ``requirement_id`` is REPLACED in place (keeping the parent's position), a new
  id is appended;
* a parent whose resolved digest or version differs from what the declaration
  pinned is an error, never a warning — that pin exists to catch a parent that
  moved;
* a venue may not claim an evaluator version its parent does not support;
* when the declaration pins ``resolved_profile_digest`` (mandatory for every
  declaration read from disk) the resolved profile's digest must equal it.

Parent lookup order is fixed: the built-in ``generic_empirical_v1``; then any
profile handed to the resolver in ``parents``; then a venue declaration in the
registry, resolved recursively.  A supplied parent whose ID is also declared in
the registry is an error, so a reader never has to guess which artifact a
recorded digest refers to.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Iterable, Mapping

from ari.manuscript.contracts import (
    ManuscriptContractError,
    ManuscriptRequirementProfileV1,
    ManuscriptVenueProfileV1,
    ProfileParentRefV1,
    RequirementSpecV1,
    parse_venue_profile,
)


PROFILE_ID = "generic_empirical_v1"
EVALUATOR_VERSION = "manuscript-evaluator-v1"
VENUE_PROFILE_DIR = Path(__file__).parent / "venue_profiles"
MAX_VENUE_PROFILE_DECLARATIONS = 256


def _req(
    requirement_id: str,
    description: str,
    sections: tuple[str, ...],
    rule: str,
    *,
    authoring: bool,
    publication: bool,
    resolvers: tuple[str, ...],
    evidence: tuple[str, ...],
) -> RequirementSpecV1:
    return RequirementSpecV1(
        requirement_id=requirement_id,
        description=description,
        section_targets=sections,
        applicability_rule_id=rule,
        authoring_blocking=authoring,
        publication_blocking=publication,
        resolver_kinds=resolvers,
        evidence_kinds=evidence,
    )


@lru_cache(maxsize=1)
def generic_empirical_profile() -> ManuscriptRequirementProfileV1:
    specs = (
        _req("MC-RQ-001", "Research question and objective", ("introduction",), "always", authoring=True, publication=True, resolvers=("method_clarification", "human_decision"), evidence=("research-contract",)),
        _req("MC-RQ-002", "Hypothesis and falsification condition", ("introduction", "method"), "hypothesis_testing", authoring=True, publication=True, resolvers=("method_clarification", "human_decision"), evidence=("research-contract",)),
        _req("MC-ME-001", "Method or algorithm description", ("method",), "always", authoring=True, publication=True, resolvers=("artifact_recovery", "method_clarification"), evidence=("node", "source", "research-contract")),
        _req("MC-ME-002", "Configuration and execution environment", ("experimental-setup",), "empirical", authoring=True, publication=True, resolvers=("artifact_recovery",), evidence=("science-data", "ear-manifest", "configuration")),
        _req("MC-ME-003", "Protocol, workload, and stopping rule", ("experimental-setup",), "empirical", authoring=True, publication=True, resolvers=("artifact_recovery", "validation_experiment"), evidence=("research-contract", "ear-manifest", "source")),
        _req("MC-RS-001", "Primary metric, direction, unit, and run identities", ("results",), "result_claim", authoring=True, publication=True, resolvers=("projection_rebuild", "validation_experiment"), evidence=("science-data", "measurement")),
        _req("MC-RS-002", "Repetition and uncertainty", ("results", "limitations"), "stochastic_claim", authoring=True, publication=True, resolvers=("repetition_or_uncertainty",), evidence=("science-data", "measurement")),
        _req("MC-CP-001", "Baseline or comparator", ("experimental-setup", "results"), "comparative_claim", authoring=True, publication=True, resolvers=("baseline_comparison",), evidence=("measurement", "configuration")),
        _req("MC-CP-002", "Equivalent comparison protocol", ("experimental-setup", "results"), "comparator_exists", authoring=True, publication=True, resolvers=("validation_experiment",), evidence=("measurement", "configuration")),
        _req("MC-AB-001", "Ablation for component-causal contribution", ("results",), "multi_component_claim", authoring=True, publication=True, resolvers=("ablation",), evidence=("measurement", "configuration")),
        _req("MC-CL-001", "Claim-to-measurement coverage", ("results",), "result_claim", authoring=True, publication=True, resolvers=("projection_rebuild",), evidence=("science-data", "measurement")),
        _req("MC-CL-002", "Reproducible numeric assertions", ("results",), "numeric_result", authoring=True, publication=True, resolvers=("projection_rebuild", "validation_experiment"), evidence=("science-data", "measurement", "figure")),
        _req("MC-NG-001", "Failed, null, and inconclusive result accounting", ("results", "limitations"), "always", authoring=False, publication=True, resolvers=("projection_rebuild", "limitation_disclosure"), evidence=("node",)),
        _req("MC-SL-001", "Selection rationale and off-lineage accounting", ("method", "results"), "multiple_candidates", authoring=False, publication=True, resolvers=("projection_rebuild",), evidence=("node", "selection")),
        _req("MC-RW-001", "Recorded related-work snapshot", ("related-work",), "always", authoring=True, publication=True, resolvers=("literature_search",), evidence=("retrieval-records",)),
        _req("MC-RW-002", "Novelty distinction", ("introduction", "related-work"), "novelty_claim", authoring=True, publication=True, resolvers=("literature_search", "human_decision"), evidence=("retrieval-records", "research-contract")),
        _req("MC-LM-001", "Limitations disclosure", ("limitations",), "always", authoring=True, publication=True, resolvers=("limitation_disclosure",), evidence=("context",)),
        _req("MC-LM-002", "Threats to validity", ("limitations",), "empirical", authoring=False, publication=True, resolvers=("limitation_disclosure",), evidence=("context",)),
        _req("MC-RP-001", "EAR, source, and environment inventory", ("reproducibility",), "empirical", authoring=True, publication=True, resolvers=("artifact_recovery",), evidence=("ear-manifest", "source")),
        _req("MC-RP-002", "Reproduction commands and locks", ("reproducibility",), "reproducibility_claim", authoring=True, publication=True, resolvers=("artifact_recovery",), evidence=("ear-manifest", "code-bundle-lock")),
        _req("MC-AS-001", "Current publication certification", ("reproducibility", "limitations"), "assurance_enforce", authoring=False, publication=True, resolvers=("assurance_certification",), evidence=("harness-attestation",)),
        _req("MC-OM-001", "Complete omission accounting", ("all",), "manuscript_enabled", authoring=True, publication=True, resolvers=("projection_rebuild",), evidence=("omission-manifest",)),
    )
    return ManuscriptRequirementProfileV1.create(
        profile_id=PROFILE_ID,
        profile_version="1",
        paper_family="generic_empirical",
        policy_version="1",
        evaluator_compatibility=(EVALUATOR_VERSION,),
        requirements=specs,
    )


@dataclass(frozen=True)
class VenueProfileRegistry:
    """Immutable set of venue profile declarations addressable by profile ID."""

    declarations: Mapping[str, ManuscriptVenueProfileV1]

    @classmethod
    def from_declarations(
        cls, declarations: Iterable[ManuscriptVenueProfileV1]
    ) -> "VenueProfileRegistry":
        table: dict[str, ManuscriptVenueProfileV1] = {}
        for declaration in declarations:
            if declaration.profile_id == PROFILE_ID:
                raise ManuscriptContractError(
                    "manuscript venue profile cannot shadow the built-in profile "
                    f"{PROFILE_ID}"
                )
            if declaration.profile_id in table:
                raise ManuscriptContractError(
                    f"duplicate manuscript venue profile: {declaration.profile_id}"
                )
            table[declaration.profile_id] = declaration
        return cls(declarations=MappingProxyType(table))

    @classmethod
    def from_directory(cls, directory: str | Path) -> "VenueProfileRegistry":
        """Read ``<profile_id>.json`` declarations from one directory.

        A missing directory is an empty registry.  A malformed file, a file
        whose name does not match the ``profile_id`` it declares, or a stored
        declaration that does not pin ``resolved_profile_digest`` is an error:
        an artifact that outlives the process must carry its whole lineage.
        """

        root = Path(directory)
        if not root.is_dir():
            return cls.from_declarations(())
        paths = sorted(
            path
            for path in root.iterdir()
            if path.is_file() and path.suffix == ".json"
        )
        if len(paths) > MAX_VENUE_PROFILE_DECLARATIONS:
            raise ManuscriptContractError(
                "manuscript venue profile registry exceeds "
                f"{MAX_VENUE_PROFILE_DECLARATIONS} declarations"
            )
        declarations = []
        for path in paths:
            try:
                payload = path.read_text(encoding="utf-8")
            except OSError as exc:
                raise ManuscriptContractError(
                    f"unreadable manuscript venue profile: {path.name}"
                ) from exc
            declaration = parse_venue_profile(payload)
            if declaration.profile_id != path.stem:
                raise ManuscriptContractError(
                    f"manuscript venue profile {path.name} declares "
                    f"{declaration.profile_id}"
                )
            if declaration.resolved_profile_digest is None:
                raise ManuscriptContractError(
                    f"manuscript venue profile {path.name} does not pin "
                    "resolved_profile_digest"
                )
            declarations.append(declaration)
        return cls.from_declarations(declarations)

    def get(self, profile_id: str) -> ManuscriptVenueProfileV1 | None:
        return self.declarations.get(profile_id)

    def profile_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self.declarations))


@lru_cache(maxsize=1)
def default_venue_registry() -> VenueProfileRegistry:
    """Venue profile declarations shipped in :data:`VENUE_PROFILE_DIR`."""

    return VenueProfileRegistry.from_directory(VENUE_PROFILE_DIR)


def _parent_table(
    parents: Iterable[ManuscriptRequirementProfileV1],
    registry: VenueProfileRegistry,
) -> Mapping[str, ManuscriptRequirementProfileV1]:
    """Index caller-supplied parent profiles, refusing every ambiguous ID."""

    table: dict[str, ManuscriptRequirementProfileV1] = {}
    for profile in parents:
        if profile.profile_id == PROFILE_ID:
            raise ManuscriptContractError(
                f"supplied parent profile cannot shadow the built-in {PROFILE_ID}"
            )
        if profile.profile_id in table:
            raise ManuscriptContractError(
                f"parent profile {profile.profile_id} was supplied twice"
            )
        if registry.get(profile.profile_id) is not None:
            raise ManuscriptContractError(
                f"parent profile {profile.profile_id} is both supplied and "
                "declared in the venue profile registry"
            )
        table[profile.profile_id] = profile
    return MappingProxyType(table)


def _compose(
    *,
    profile_id: str,
    profile_version: str,
    paper_family: str,
    policy_version: str,
    evaluator_compatibility: tuple[str, ...],
    extends: tuple[ProfileParentRefV1, ...],
    removed_requirement_ids: tuple[str, ...],
    requirements: tuple[RequirementSpecV1, ...],
    registry: VenueProfileRegistry,
    parents: Mapping[str, ManuscriptRequirementProfileV1],
    stack: tuple[str, ...],
) -> ManuscriptRequirementProfileV1:
    merged: dict[str, RequirementSpecV1] = {}
    for reference in extends:
        parent = _resolve(reference.profile_id, registry, parents, stack=stack)
        if parent.profile_version != reference.profile_version:
            raise ManuscriptContractError(
                f"manuscript profile {profile_id} pins parent "
                f"{reference.profile_id} version {reference.profile_version}; "
                f"the parent is version {parent.profile_version}"
            )
        if parent.profile_digest != reference.profile_digest:
            raise ManuscriptContractError(
                f"manuscript profile {profile_id} pins parent "
                f"{reference.profile_id} at {reference.profile_digest}; "
                f"the parent now resolves to {parent.profile_digest}"
            )
        unsupported = tuple(
            sorted(set(evaluator_compatibility) - set(parent.evaluator_compatibility))
        )
        if unsupported:
            raise ManuscriptContractError(
                f"manuscript profile {profile_id} claims evaluator compatibility "
                f"parent {reference.profile_id} does not declare: "
                + ", ".join(unsupported)
            )
        for spec in parent.requirements:
            merged[spec.requirement_id] = spec
    for requirement_id in removed_requirement_ids:
        if requirement_id not in merged:
            raise ManuscriptContractError(
                f"manuscript profile {profile_id} removes {requirement_id}, "
                "which no parent declares"
            )
        del merged[requirement_id]
    for spec in requirements:
        merged[spec.requirement_id] = spec
    if not merged:
        raise ManuscriptContractError(
            f"manuscript profile {profile_id} resolves to no requirement"
        )
    return ManuscriptRequirementProfileV1.create(
        profile_id=profile_id,
        profile_version=profile_version,
        paper_family=paper_family,
        policy_version=policy_version,
        evaluator_compatibility=evaluator_compatibility,
        requirements=tuple(merged.values()),
    )


def _resolve_declaration(
    declaration: ManuscriptVenueProfileV1,
    registry: VenueProfileRegistry,
    parents: Mapping[str, ManuscriptRequirementProfileV1],
    *,
    stack: tuple[str, ...],
) -> ManuscriptRequirementProfileV1:
    resolved = _compose(
        profile_id=declaration.profile_id,
        profile_version=declaration.profile_version,
        paper_family=declaration.paper_family,
        policy_version=declaration.policy_version,
        evaluator_compatibility=declaration.evaluator_compatibility,
        extends=declaration.extends,
        removed_requirement_ids=declaration.removed_requirement_ids,
        requirements=declaration.requirements,
        registry=registry,
        parents=parents,
        stack=stack + (declaration.profile_id,),
    )
    pinned = declaration.resolved_profile_digest
    if pinned is not None and resolved.profile_digest != pinned:
        raise ManuscriptContractError(
            f"manuscript venue profile {declaration.profile_id} pins resolved "
            f"digest {pinned}; composition produced {resolved.profile_digest}"
        )
    return resolved


def _resolve(
    profile_id: str,
    registry: VenueProfileRegistry,
    parents: Mapping[str, ManuscriptRequirementProfileV1],
    *,
    stack: tuple[str, ...],
) -> ManuscriptRequirementProfileV1:
    if profile_id == PROFILE_ID:
        return generic_empirical_profile()
    supplied = parents.get(profile_id)
    if supplied is not None:
        return supplied
    if profile_id in stack:
        raise ManuscriptContractError(
            "manuscript profile extension cycle: "
            + " -> ".join(stack + (profile_id,))
        )
    declaration = registry.get(profile_id)
    if declaration is None:
        raise ValueError(f"unknown manuscript profile: {profile_id}")
    return _resolve_declaration(declaration, registry, parents, stack=stack)


def resolve_profile(
    profile_id: str,
    *,
    registry: VenueProfileRegistry | None = None,
    parents: Iterable[ManuscriptRequirementProfileV1] = (),
) -> ManuscriptRequirementProfileV1:
    """Return the requirement profile named by ``profile_id``.

    ``generic_empirical_v1`` is the built-in root.  Any other ID is looked up as
    a venue profile declaration and resolved by explicit composition; the result
    is an ordinary ``ManuscriptRequirementProfileV1`` whose ``profile_digest`` is
    the resolved digest.
    """

    resolved_registry = default_venue_registry() if registry is None else registry
    return _resolve(
        profile_id,
        resolved_registry,
        _parent_table(parents, resolved_registry),
        stack=(),
    )


def resolve_venue_profile(
    declaration: ManuscriptVenueProfileV1,
    *,
    parents: Iterable[ManuscriptRequirementProfileV1] = (),
    registry: VenueProfileRegistry | None = None,
) -> ManuscriptRequirementProfileV1:
    """Resolve one venue profile declaration against the parents it pins.

    ``parents`` are already-resolved profiles the caller holds; anything not
    supplied there is looked up in ``registry`` (the shipped declarations by
    default).  A parent that is absent, whose version differs, or whose digest
    no longer matches what the declaration recorded is an error.
    """

    resolved_registry = default_venue_registry() if registry is None else registry
    return _resolve_declaration(
        declaration,
        resolved_registry,
        _parent_table(parents, resolved_registry),
        stack=(),
    )


def build_venue_declaration(
    *,
    profile_id: str,
    profile_version: str,
    paper_family: str,
    policy_version: str,
    evaluator_compatibility: tuple[str, ...],
    extends: tuple[ProfileParentRefV1, ...],
    requirements: tuple[RequirementSpecV1, ...] = (),
    removed_requirement_ids: tuple[str, ...] = (),
    parents: Iterable[ManuscriptRequirementProfileV1] = (),
    registry: VenueProfileRegistry | None = None,
) -> ManuscriptVenueProfileV1:
    """Compose a venue profile and mint its declaration with both pins bound.

    The parent digests must already be correct in ``extends``: this only mints
    ``resolved_profile_digest`` (and the declaration's own digest) for a
    composition that resolves cleanly right now.  It never re-pins a parent, so
    a stale parent reference fails here exactly as it fails at read time.
    """

    resolved_registry = default_venue_registry() if registry is None else registry
    resolved = _compose(
        profile_id=profile_id,
        profile_version=profile_version,
        paper_family=paper_family,
        policy_version=policy_version,
        evaluator_compatibility=evaluator_compatibility,
        extends=extends,
        removed_requirement_ids=removed_requirement_ids,
        requirements=requirements,
        registry=resolved_registry,
        parents=_parent_table(parents, resolved_registry),
        stack=(profile_id,),
    )
    return ManuscriptVenueProfileV1.create(
        profile_id=profile_id,
        profile_version=profile_version,
        paper_family=paper_family,
        policy_version=policy_version,
        evaluator_compatibility=evaluator_compatibility,
        extends=extends,
        removed_requirement_ids=removed_requirement_ids,
        requirements=requirements,
        resolved_profile_digest=resolved.profile_digest,
    )


def parent_ref(profile: ManuscriptRequirementProfileV1) -> ProfileParentRefV1:
    """Pin an already-resolved profile as a parent reference."""

    return ProfileParentRefV1(
        profile_id=profile.profile_id,
        profile_version=profile.profile_version,
        profile_digest=profile.profile_digest,
    )


def write_venue_declaration(
    declaration: ManuscriptVenueProfileV1,
    directory: str | Path,
) -> Path:
    """Write one declaration as ``<profile_id>.json`` and return its path.

    ``profile_id`` is NOT a path. ``_SAFE_ID`` admits ``/`` and ``.`` because a
    profile identity may be namespaced, so interpolating it into a filename
    would let ``a/../../x`` write outside *directory*. The name is therefore
    required to be a single ordinary path segment, and the resolved target is
    re-checked against the resolved root before anything is written.
    """

    root = Path(directory)
    name = f"{declaration.profile_id}.json"
    if Path(name).name != name or declaration.profile_id in {"", ".", ".."}:
        raise ValueError(
            "venue profile_id is not writable as a filename: "
            f"{declaration.profile_id!r}"
        )
    root.mkdir(parents=True, exist_ok=True)
    path = root / name
    if path.resolve().parent != root.resolve():
        raise ValueError(
            "venue declaration would be written outside the target directory: "
            f"{declaration.profile_id!r}"
        )
    payload = json.dumps(
        declaration.model_dump(mode="json"),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"
    path.write_text(payload, encoding="utf-8")
    return path


__all__ = [
    "EVALUATOR_VERSION",
    "MAX_VENUE_PROFILE_DECLARATIONS",
    "PROFILE_ID",
    "VENUE_PROFILE_DIR",
    "VenueProfileRegistry",
    "build_venue_declaration",
    "default_venue_registry",
    "generic_empirical_profile",
    "parent_ref",
    "resolve_profile",
    "resolve_venue_profile",
    "write_venue_declaration",
]
