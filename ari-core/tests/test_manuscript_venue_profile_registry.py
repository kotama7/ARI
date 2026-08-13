"""Venue profile declarations: registry, pins, removal, and consumption.

Companion to ``test_manuscript_venue_profile_composition.py``, which fixes the
composition algebra itself.  This module covers the artifact lifecycle around
it: a declaration is minted, written as ``<profile_id>.json``, read back by
``VenueProfileRegistry``, resolved by ``resolve_profile()`` — the same call the
coordinator already makes — and finally consumed by the readiness evaluator and
the section-brief builder, which never learn that the profile was composed.

The pins are the point of the exercise.  ``extends`` records each parent at the
digest the venue was written against and ``resolved_profile_digest`` records
what that composition produced, so a parent that moves out from under a stored
declaration fails closed instead of silently re-scoring a manuscript against
requirements nobody approved.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ari.manuscript.briefs import build_section_briefs
from ari.manuscript.contracts import (
    ManuscriptContextV1,
    ManuscriptContractError,
    ManuscriptVenueProfileV1,
    ProfileParentRefV1,
    RequirementSpecV1,
)
from ari.manuscript.coordinator import compile_manuscript
from ari.manuscript.profiles import (
    EVALUATOR_VERSION,
    PROFILE_ID,
    VENUE_PROFILE_DIR,
    VenueProfileRegistry,
    build_venue_declaration,
    default_venue_registry,
    generic_empirical_profile,
    parent_ref,
    resolve_profile,
    write_venue_declaration,
)
from ari.manuscript.readiness import evaluate_readiness


D1 = "sha256:" + "1" * 64


def _spec(
    requirement_id: str,
    description: str,
    *,
    sections: tuple[str, ...] = ("results",),
    rule: str = "always",
    authoring: bool = True,
    publication: bool = True,
) -> RequirementSpecV1:
    return RequirementSpecV1(
        requirement_id=requirement_id,
        description=description,
        section_targets=sections,
        applicability_rule_id=rule,
        authoring_blocking=authoring,
        publication_blocking=publication,
        resolver_kinds=("projection_rebuild",),
        evidence_kinds=("science-data",),
    )


def _declare(
    profile_id: str,
    *,
    extends: tuple[ProfileParentRefV1, ...],
    requirements: tuple[RequirementSpecV1, ...] = (),
    removed_requirement_ids: tuple[str, ...] = (),
    registry: VenueProfileRegistry | None = None,
    evaluator_compatibility: tuple[str, ...] = (EVALUATOR_VERSION,),
) -> ManuscriptVenueProfileV1:
    return build_venue_declaration(
        profile_id=profile_id,
        profile_version="1",
        paper_family="generic_empirical",
        policy_version="1",
        evaluator_compatibility=evaluator_compatibility,
        extends=extends,
        requirements=requirements,
        removed_requirement_ids=removed_requirement_ids,
        registry=registry,
    )


def _ids(profile) -> tuple[str, ...]:
    return tuple(item.requirement_id for item in profile.requirements)


def _audit_outcome(tmp_path: Path):
    """A minimal audited checkpoint: the context/omissions a profile consumes."""

    checkpoint = tmp_path / "run-venue"
    checkpoint.mkdir()
    (checkpoint / "tree.json").write_text(
        json.dumps({"run_id": "run-venue", "nodes": []}), encoding="utf-8"
    )
    return compile_manuscript(checkpoint, [], mode="audit", persist=False)


def test_every_shipped_declaration_resolves_and_none_shadows_the_built_in() -> None:
    """The shipped registry is a gate: a parent that moved fails here."""

    assert VENUE_PROFILE_DIR.is_dir()
    registry = default_venue_registry()
    assert PROFILE_ID not in registry.profile_ids()
    for profile_id in registry.profile_ids():
        resolved = resolve_profile(profile_id)
        assert resolved.profile_id == profile_id
        assert resolved.profile_digest == (
            registry.get(profile_id).resolved_profile_digest
        )
    assert resolve_profile(PROFILE_ID) is generic_empirical_profile()


def test_declaration_round_trips_through_the_registry_directory(tmp_path: Path) -> None:
    generic = generic_empirical_profile()
    generic_digest = generic.profile_digest
    declaration = _declare(
        "mc_venue_registry_v1",
        extends=(parent_ref(generic),),
        requirements=(
            _spec(
                "MC-LM-002",
                "Threats to validity, unconditional for this venue",
                sections=("limitations",),
            ),
            _spec("MC-VR-001", "Venue-only requirement"),
        ),
    )
    assert declaration.resolved_profile_digest is not None

    path = write_venue_declaration(declaration, tmp_path)
    assert path.name == "mc_venue_registry_v1.json"

    registry = VenueProfileRegistry.from_directory(tmp_path)
    assert registry.profile_ids() == ("mc_venue_registry_v1",)
    resolved = resolve_profile("mc_venue_registry_v1", registry=registry)

    assert resolved.profile_id == "mc_venue_registry_v1"
    assert resolved.profile_digest == declaration.resolved_profile_digest
    # The override keeps the parent's position; the addition is appended.
    assert _ids(resolved) == _ids(generic) + ("MC-VR-001",)
    tightened = resolved.requirements[_ids(resolved).index("MC-LM-002")]
    assert tightened.applicability_rule_id == "always"
    assert tightened.authoring_blocking is True

    # The parent is an input, never a thing composition edits.
    assert generic_empirical_profile().profile_digest == generic_digest
    assert (
        generic.requirements[_ids(generic).index("MC-LM-002")].applicability_rule_id
        == "empirical"
    )


def test_registry_rejects_a_filename_that_disagrees_with_the_declaration(
    tmp_path: Path,
) -> None:
    declaration = _declare(
        "mc_venue_named_v1",
        extends=(parent_ref(generic_empirical_profile()),),
        requirements=(_spec("MC-VR-010", "Venue-only requirement"),),
    )
    written = write_venue_declaration(declaration, tmp_path)
    written.rename(tmp_path / "mc_venue_other_v1.json")

    with pytest.raises(ManuscriptContractError) as excinfo:
        VenueProfileRegistry.from_directory(tmp_path)
    assert "mc_venue_other_v1.json" in str(excinfo.value)
    assert "mc_venue_named_v1" in str(excinfo.value)


def test_registry_rejects_a_stored_declaration_without_a_resolved_digest_pin(
    tmp_path: Path,
) -> None:
    """An in-memory draft may skip the pin; a stored artifact may not."""

    unpinned = ManuscriptVenueProfileV1.create(
        profile_id="mc_venue_unpinned_v1",
        profile_version="1",
        paper_family="generic_empirical",
        policy_version="1",
        evaluator_compatibility=(EVALUATOR_VERSION,),
        extends=(parent_ref(generic_empirical_profile()),),
        requirements=(_spec("MC-VR-020", "Venue-only requirement"),),
    )
    assert unpinned.resolved_profile_digest is None
    write_venue_declaration(unpinned, tmp_path)

    with pytest.raises(ManuscriptContractError) as excinfo:
        VenueProfileRegistry.from_directory(tmp_path)
    assert "resolved_profile_digest" in str(excinfo.value)


def test_resolution_rejects_a_declaration_whose_resolved_pin_is_wrong() -> None:
    """The resolved pin is verified, not decorative."""

    mispinned = ManuscriptVenueProfileV1.create(
        profile_id="mc_venue_mispinned_v1",
        profile_version="1",
        paper_family="generic_empirical",
        policy_version="1",
        evaluator_compatibility=(EVALUATOR_VERSION,),
        extends=(parent_ref(generic_empirical_profile()),),
        requirements=(_spec("MC-VR-030", "Venue-only requirement"),),
        resolved_profile_digest=D1,
    )
    registry = VenueProfileRegistry.from_declarations((mispinned,))

    with pytest.raises(ManuscriptContractError) as excinfo:
        resolve_profile("mc_venue_mispinned_v1", registry=registry)
    assert D1 in str(excinfo.value)


def test_stored_declaration_rejects_a_parent_that_moved_under_it(
    tmp_path: Path,
) -> None:
    """A venue chain fails closed when its parent venue is re-declared."""

    base = _declare(
        "mc_venue_base_v1",
        extends=(parent_ref(generic_empirical_profile()),),
        requirements=(_spec("MC-VR-040", "Base venue requirement as recorded"),),
    )
    write_venue_declaration(base, tmp_path)
    base_registry = VenueProfileRegistry.from_directory(tmp_path)
    base_resolved = resolve_profile("mc_venue_base_v1", registry=base_registry)

    child = _declare(
        "mc_venue_child_v1",
        extends=(parent_ref(base_resolved),),
        requirements=(_spec("MC-VR-041", "Child venue requirement"),),
        registry=base_registry,
    )
    write_venue_declaration(child, tmp_path)
    intact = resolve_profile(
        "mc_venue_child_v1", registry=VenueProfileRegistry.from_directory(tmp_path)
    )
    assert _ids(intact)[-2:] == ("MC-VR-040", "MC-VR-041")

    # The base venue is re-declared under the same ID and version.
    moved = _declare(
        "mc_venue_base_v1",
        extends=(parent_ref(generic_empirical_profile()),),
        requirements=(_spec("MC-VR-040", "Base venue requirement after it moved"),),
    )
    write_venue_declaration(moved, tmp_path)
    moved_resolved = resolve_profile(
        "mc_venue_base_v1", registry=VenueProfileRegistry.from_directory(tmp_path)
    )
    assert moved_resolved.profile_digest != base_resolved.profile_digest

    with pytest.raises(ManuscriptContractError) as excinfo:
        resolve_profile(
            "mc_venue_child_v1", registry=VenueProfileRegistry.from_directory(tmp_path)
        )
    message = str(excinfo.value)
    assert "mc_venue_base_v1" in message
    assert base_resolved.profile_digest in message
    assert moved_resolved.profile_digest in message


def test_explicit_removal_drops_a_parent_requirement(tmp_path: Path) -> None:
    """Removal is expressible, but only when it is spelled out."""

    generic = generic_empirical_profile()
    declaration = _declare(
        "mc_venue_removal_v1",
        extends=(parent_ref(generic),),
        requirements=(_spec("MC-VR-050", "Venue-only requirement"),),
        removed_requirement_ids=("MC-AB-001",),
    )
    resolved = resolve_profile(
        "mc_venue_removal_v1",
        registry=VenueProfileRegistry.from_directory(
            write_venue_declaration(declaration, tmp_path).parent
        ),
    )

    assert "MC-AB-001" in _ids(generic)
    assert "MC-AB-001" not in _ids(resolved)
    assert declaration.removed_requirement_ids == ("MC-AB-001",)
    # Everything the declaration stays silent about survives.
    assert set(_ids(generic)) - set(_ids(resolved)) == {"MC-AB-001"}


def test_removing_a_requirement_no_parent_declares_is_rejected() -> None:
    with pytest.raises(ManuscriptContractError) as excinfo:
        _declare(
            "mc_venue_bad_removal_v1",
            extends=(parent_ref(generic_empirical_profile()),),
            requirements=(_spec("MC-VR-060", "Venue-only requirement"),),
            removed_requirement_ids=("MC-VR-999",),
        )
    assert "MC-VR-999" in str(excinfo.value)


def test_a_requirement_cannot_be_both_removed_and_declared() -> None:
    with pytest.raises(ValueError) as excinfo:
        ManuscriptVenueProfileV1.create(
            profile_id="mc_venue_conflict_v1",
            profile_version="1",
            paper_family="generic_empirical",
            policy_version="1",
            evaluator_compatibility=(EVALUATOR_VERSION,),
            extends=(parent_ref(generic_empirical_profile()),),
            requirements=(_spec("MC-AB-001", "Replacement the venue also removes"),),
            removed_requirement_ids=("MC-AB-001",),
        )
    assert "MC-AB-001" in str(excinfo.value)


def test_venue_cannot_claim_evaluator_compatibility_its_parent_lacks() -> None:
    with pytest.raises(ManuscriptContractError) as excinfo:
        _declare(
            "mc_venue_evaluator_v1",
            extends=(parent_ref(generic_empirical_profile()),),
            requirements=(_spec("MC-VR-070", "Venue-only requirement"),),
            evaluator_compatibility=(EVALUATOR_VERSION, "manuscript-evaluator-v2"),
        )
    assert "manuscript-evaluator-v2" in str(excinfo.value)


def test_extension_cycle_is_rejected() -> None:
    """Two declarations that name each other terminate with an error."""

    first = ManuscriptVenueProfileV1.create(
        profile_id="mc_venue_cycle_a_v1",
        profile_version="1",
        paper_family="generic_empirical",
        policy_version="1",
        evaluator_compatibility=(EVALUATOR_VERSION,),
        extends=(
            ProfileParentRefV1(
                profile_id="mc_venue_cycle_b_v1",
                profile_version="1",
                profile_digest=D1,
            ),
        ),
        requirements=(_spec("MC-VR-080", "First venue requirement"),),
    )
    second = ManuscriptVenueProfileV1.create(
        profile_id="mc_venue_cycle_b_v1",
        profile_version="1",
        paper_family="generic_empirical",
        policy_version="1",
        evaluator_compatibility=(EVALUATOR_VERSION,),
        extends=(
            ProfileParentRefV1(
                profile_id="mc_venue_cycle_a_v1",
                profile_version="1",
                profile_digest=D1,
            ),
        ),
        requirements=(_spec("MC-VR-081", "Second venue requirement"),),
    )
    registry = VenueProfileRegistry.from_declarations((first, second))

    with pytest.raises(ManuscriptContractError) as excinfo:
        resolve_profile("mc_venue_cycle_a_v1", registry=registry)
    assert "cycle" in str(excinfo.value)


def test_supplied_parent_cannot_shadow_a_declared_or_built_in_profile() -> None:
    """An ambiguous parent identity is refused instead of silently picked."""

    with pytest.raises(ManuscriptContractError) as excinfo:
        resolve_profile(PROFILE_ID, parents=(generic_empirical_profile(),))
    assert PROFILE_ID in str(excinfo.value)

    declaration = ManuscriptVenueProfileV1.create(
        profile_id="mc_venue_shadowed_v1",
        profile_version="1",
        paper_family="generic_empirical",
        policy_version="1",
        evaluator_compatibility=(EVALUATOR_VERSION,),
        extends=(parent_ref(generic_empirical_profile()),),
        requirements=(_spec("MC-VR-090", "Venue-only requirement"),),
    )
    registry = VenueProfileRegistry.from_declarations((declaration,))
    impostor = resolve_profile("mc_venue_shadowed_v1", registry=registry)

    with pytest.raises(ManuscriptContractError) as excinfo:
        resolve_profile(
            "mc_venue_shadowed_v1", registry=registry, parents=(impostor,)
        )
    assert "mc_venue_shadowed_v1" in str(excinfo.value)


def test_a_registry_declaration_cannot_shadow_the_built_in_profile() -> None:
    declaration = ManuscriptVenueProfileV1.create(
        profile_id=PROFILE_ID,
        profile_version="2",
        paper_family="generic_empirical",
        policy_version="1",
        evaluator_compatibility=(EVALUATOR_VERSION,),
        extends=(
            ProfileParentRefV1(
                profile_id="mc_venue_root_v1",
                profile_version="1",
                profile_digest=D1,
            ),
        ),
        requirements=(_spec("MC-VR-100", "Venue-only requirement"),),
    )
    with pytest.raises(ManuscriptContractError) as excinfo:
        VenueProfileRegistry.from_declarations((declaration,))
    assert PROFILE_ID in str(excinfo.value)


def test_resolved_venue_profile_drives_readiness_and_section_briefs(
    tmp_path: Path,
) -> None:
    """The composed profile reaches the existing consumers unchanged."""

    outcome = _audit_outcome(tmp_path)
    declaration = _declare(
        "mc_venue_consumed_v1",
        extends=(parent_ref(generic_empirical_profile()),),
        requirements=(_spec("MC-VR-110", "Venue submission obligation"),),
    )
    resolved = resolve_profile(
        "mc_venue_consumed_v1",
        registry=VenueProfileRegistry.from_directory(
            write_venue_declaration(declaration, tmp_path).parent
        ),
    )

    payload = outcome.context.digest_payload()
    payload["profile_digest"] = resolved.profile_digest
    context = ManuscriptContextV1.create(**payload)

    readiness = evaluate_readiness(resolved, context, outcome.omissions)
    briefs = build_section_briefs(resolved, context, readiness)

    assert readiness.profile_digest == resolved.profile_digest
    assert briefs.profile_digest == resolved.profile_digest
    assert len(readiness.requirement_results) == len(resolved.requirements)
    assert len(resolved.requirements) == len(generic_empirical_profile().requirements) + 1

    # A venue requirement no evaluator implements fails closed rather than
    # counting as satisfied.
    added = next(
        item
        for item in readiness.requirement_results
        if item.requirement_id == "MC-VR-110"
    )
    assert added.status == "missing"
    assert added.reason_code == "unimplemented_requirement_evaluator"
    assert readiness.publication_verdict == "blocked"
