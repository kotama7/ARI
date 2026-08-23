"""Venue requirement profiles extend by explicit composition, never by mutation.

Program plan open decision 4 is closed as **explicit composition**: a venue
profile declares its parents, records each parent's ``profile_digest``, and
resolution happens at read time.  The resolved artifact is an ordinary
``ManuscriptRequirementProfileV1``, so its ``profile_digest`` *is* the resolved
digest the plan requires.

Two properties are load bearing here.

``generic_empirical_v1`` is not touched.  Its ``profile_digest`` is pinned by
persisted records (``ari-core/config/harnesses/evidence/production_e2e/
manuscript_readiness.json`` and ``manuscript_authoring_binding.json``), and
:meth:`DigestBoundModel.digest_payload` hashes the *whole* model dump, so one
new field on ``ManuscriptRequirementProfileV1`` — even one defaulting to empty —
would invalidate every record that pins it.  Composition therefore lives in a
separate model, ``ManuscriptVenueProfileV1``, and
``test_generic_empirical_profile_digest_is_pinned_and_parentless`` fails the
moment that separation is broken.

A parent whose resolved digest no longer matches what the declaration recorded
is an error, never a warning.  Recording the digest exists precisely to catch a
parent that moved, so ``test_venue_profile_rejects_a_parent_whose_digest_moved``
asserts on the failure itself, not merely that something was raised.

Removal is expressible but only explicitly, through
``removed_requirement_ids``; omission never removes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ari.manuscript.contracts import (
    ManuscriptContractError,
    ManuscriptRequirementProfileV1,
    ManuscriptVenueProfileV1,
    RequirementSpecV1,
)
from ari.manuscript.digest import canonical_digest
from ari.manuscript.profiles import (
    EVALUATOR_VERSION,
    PROFILE_ID,
    VenueProfileRegistry,
    build_venue_declaration,
    generic_empirical_profile,
    parent_ref,
    resolve_profile,
    write_venue_declaration,
)


D1 = "sha256:" + "1" * 64

# The digest downstream records already pin.  Never "update" this constant to
# make a test pass: a change here means persisted evidence has been invalidated.
GENERIC_EMPIRICAL_V1_PROFILE_DIGEST = (
    "sha256:6639e048128d9e78b5b7a0f67e3b149c826a51073f6f9c5c1f7f82244c217ba4"
)

# The exact digest surface of the pinned profile.  Any added, removed or renamed
# field on either model changes the canonical dump and therefore the digest.
PINNED_PROFILE_FIELDS = frozenset(
    {
        "schema_version",
        "profile_id",
        "profile_version",
        "paper_family",
        "policy_version",
        "evaluator_compatibility",
        "requirements",
        "profile_digest",
    }
)
PINNED_REQUIREMENT_FIELDS = frozenset(
    {
        "requirement_id",
        "description",
        "section_targets",
        "applicability_rule_id",
        "authoring_blocking",
        "publication_blocking",
        "allowed_terminal_statuses",
        "resolver_kinds",
        "evidence_kinds",
    }
)


def _spec(
    requirement_id: str,
    description: str,
    *,
    sections: tuple[str, ...] = ("results",),
    rule: str = "always",
    authoring: bool = True,
    publication: bool = True,
    resolvers: tuple[str, ...] = ("projection_rebuild",),
    evidence: tuple[str, ...] = ("science-data",),
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


def _registry(*declarations: ManuscriptVenueProfileV1) -> VenueProfileRegistry:
    return VenueProfileRegistry.from_declarations(declarations)


def _venue(
    profile_id: str,
    *,
    extends: tuple,
    registry: VenueProfileRegistry,
    requirements: tuple[RequirementSpecV1, ...] = (),
    removed: tuple[str, ...] = (),
    profile_version: str = "1",
) -> ManuscriptVenueProfileV1:
    return build_venue_declaration(
        profile_id=profile_id,
        profile_version=profile_version,
        paper_family="generic_empirical",
        policy_version="1",
        evaluator_compatibility=(EVALUATOR_VERSION,),
        extends=extends,
        requirements=requirements,
        removed_requirement_ids=removed,
        registry=registry,
    )


def _requirement_ids(profile: ManuscriptRequirementProfileV1) -> tuple[str, ...]:
    return tuple(item.requirement_id for item in profile.requirements)


def _requirement(
    profile: ManuscriptRequirementProfileV1, requirement_id: str
) -> RequirementSpecV1:
    matches = [
        item for item in profile.requirements if item.requirement_id == requirement_id
    ]
    assert len(matches) == 1, (
        f"{requirement_id} appears {len(matches)} times in {profile.profile_id}: "
        f"{_requirement_ids(profile)}"
    )
    return matches[0]


def _venue_tail(profile: ManuscriptRequirementProfileV1) -> tuple[str, ...]:
    """Requirement IDs beyond the inherited generic block, in resolved order.

    The generic block stays at the front, in its own order, because a replaced
    ``requirement_id`` keeps the position it was inherited at.
    """

    inherited = _requirement_ids(generic_empirical_profile())
    ids = _requirement_ids(profile)
    assert ids[: len(inherited)] == inherited, (
        "composition must preserve the inherited requirement order; got "
        f"{ids[: len(inherited)]}"
    )
    return ids[len(inherited) :]


def test_generic_empirical_profile_digest_is_pinned_and_parentless() -> None:
    """The pinned profile resolves exactly as before, with no parents."""

    profile = generic_empirical_profile()
    assert profile.profile_id == PROFILE_ID
    assert profile.profile_digest == GENERIC_EMPIRICAL_V1_PROFILE_DIGEST
    assert canonical_digest(profile.digest_payload()) == (
        GENERIC_EMPIRICAL_V1_PROFILE_DIGEST
    )
    assert resolve_profile(PROFILE_ID).profile_digest == (
        GENERIC_EMPIRICAL_V1_PROFILE_DIGEST
    )
    assert resolve_profile(PROFILE_ID, registry=_registry()).profile_digest == (
        GENERIC_EMPIRICAL_V1_PROFILE_DIGEST
    )

    # Composition must not have been bolted onto the pinned model: the digest
    # payload is the whole dump, so one extra field invalidates every record
    # pinning this digest.
    assert set(ManuscriptRequirementProfileV1.model_fields) == PINNED_PROFILE_FIELDS
    assert set(RequirementSpecV1.model_fields) == PINNED_REQUIREMENT_FIELDS
    payload = profile.model_dump(mode="json")
    assert set(payload) == PINNED_PROFILE_FIELDS
    assert "extends" not in payload


def test_pinned_profile_digest_matches_persisted_evidence_records() -> None:
    """The pin above is the digest persisted records already carry."""

    evidence = (
        Path(__file__).resolve().parents[1]
        / "config"
        / "harnesses"
        / "evidence"
        / "production_e2e"
    )
    recorded = {
        name: json.loads((evidence / name).read_text(encoding="utf-8"))["profile_digest"]
        for name in ("manuscript_readiness.json", "manuscript_authoring_binding.json")
        if (evidence / name).is_file()
    }
    assert recorded, f"no persisted manuscript evidence found under {evidence}"
    assert set(recorded.values()) == {GENERIC_EMPIRICAL_V1_PROFILE_DIGEST}


def test_venue_profile_composes_one_parent_with_override_and_addition() -> None:
    generic = generic_empirical_profile()
    parent = _venue(
        "mc_parent_single_v1",
        extends=(parent_ref(generic),),
        requirements=(
            _spec("MC-VP-001", "Parent requirement the venue keeps"),
            _spec(
                "MC-VP-002",
                "Parent requirement the venue overrides",
                authoring=False,
                publication=False,
            ),
        ),
        registry=_registry(),
    )
    parent_profile = resolve_profile("mc_parent_single_v1", registry=_registry(parent))

    venue = _venue(
        "mc_venue_single_v1",
        extends=(parent_ref(parent_profile),),
        requirements=(
            _spec(
                "MC-VP-002",
                "Venue-tightened requirement",
                sections=("results", "limitations"),
                authoring=True,
                publication=True,
            ),
            _spec("MC-VP-003", "Venue-only requirement"),
        ),
        registry=_registry(parent),
    )
    registry = _registry(parent, venue)
    resolved = resolve_profile("mc_venue_single_v1", registry=registry)

    # Parent order first, the replaced ID in the parent's position, the new ID
    # appended.
    assert _venue_tail(resolved) == ("MC-VP-001", "MC-VP-002", "MC-VP-003")
    assert _requirement(resolved, "MC-VP-001") == _requirement(
        parent_profile, "MC-VP-001"
    )

    overridden = _requirement(resolved, "MC-VP-002")
    assert overridden.description == "Venue-tightened requirement"
    assert overridden.section_targets == ("results", "limitations")
    assert overridden.authoring_blocking is True
    assert overridden.publication_blocking is True
    assert resolved.profile_digest == venue.resolved_profile_digest

    # The parent is an input, not something composition rewrites.
    assert _requirement(parent_profile, "MC-VP-002").description == (
        "Parent requirement the venue overrides"
    )
    assert resolve_profile(
        "mc_parent_single_v1", registry=registry
    ).profile_digest == parent_profile.profile_digest
    assert generic_empirical_profile().profile_digest == (
        GENERIC_EMPIRICAL_V1_PROFILE_DIGEST
    )


def test_declared_resolved_digest_is_the_composition_and_is_enforced() -> None:
    """The pinned resolved digest is the composition's own digest, checked."""

    generic = generic_empirical_profile()
    addition = _spec("MC-VP-900", "Venue-only requirement")
    expected = ManuscriptRequirementProfileV1.create(
        profile_id="mc_venue_pinned_v1",
        profile_version="1",
        paper_family="generic_empirical",
        policy_version="1",
        evaluator_compatibility=(EVALUATOR_VERSION,),
        requirements=generic.requirements + (addition,),
    )
    declaration = ManuscriptVenueProfileV1.create(
        profile_id="mc_venue_pinned_v1",
        profile_version="1",
        paper_family="generic_empirical",
        policy_version="1",
        evaluator_compatibility=(EVALUATOR_VERSION,),
        extends=(parent_ref(generic),),
        requirements=(addition,),
        resolved_profile_digest=expected.profile_digest,
    )

    resolved = resolve_profile("mc_venue_pinned_v1", registry=_registry(declaration))
    assert resolved == expected
    assert resolved.profile_digest == expected.profile_digest
    assert resolved.profile_digest != generic.profile_digest

    mispinned = ManuscriptVenueProfileV1.create(
        profile_id="mc_venue_mispinned_v1",
        profile_version="1",
        paper_family="generic_empirical",
        policy_version="1",
        evaluator_compatibility=(EVALUATOR_VERSION,),
        extends=(parent_ref(generic),),
        requirements=(addition,),
        resolved_profile_digest=D1,
    )
    with pytest.raises(ManuscriptContractError) as excinfo:
        resolve_profile("mc_venue_mispinned_v1", registry=_registry(mispinned))
    message = str(excinfo.value)
    assert "mc_venue_mispinned_v1" in message
    assert D1 in message


def test_venue_profile_applies_parents_in_declaration_order() -> None:
    generic = generic_empirical_profile()
    first = _venue(
        "mc_parent_first_v1",
        extends=(parent_ref(generic),),
        requirements=(
            _spec("MC-VP-010", "First parent only"),
            _spec(
                "MC-VP-020",
                "Shared requirement from the first parent",
                authoring=False,
            ),
        ),
        registry=_registry(),
    )
    second = _venue(
        "mc_parent_second_v1",
        extends=(parent_ref(generic),),
        requirements=(
            _spec(
                "MC-VP-020",
                "Shared requirement from the second parent",
                authoring=True,
            ),
            _spec("MC-VP-030", "Second parent only"),
        ),
        registry=_registry(),
    )
    parents = _registry(first, second)
    first_profile = resolve_profile("mc_parent_first_v1", registry=parents)
    second_profile = resolve_profile("mc_parent_second_v1", registry=parents)
    own = (_spec("MC-VP-040", "Venue-only requirement"),)

    forward = _venue(
        "mc_venue_forward_v1",
        extends=(parent_ref(first_profile), parent_ref(second_profile)),
        requirements=own,
        registry=parents,
    )
    reverse = _venue(
        "mc_venue_reverse_v1",
        extends=(parent_ref(second_profile), parent_ref(first_profile)),
        requirements=own,
        registry=parents,
    )
    registry = _registry(first, second, forward, reverse)
    forward_resolved = resolve_profile("mc_venue_forward_v1", registry=registry)
    reverse_resolved = resolve_profile("mc_venue_reverse_v1", registry=registry)

    assert _venue_tail(forward_resolved) == (
        "MC-VP-010",
        "MC-VP-020",
        "MC-VP-030",
        "MC-VP-040",
    )
    later = _requirement(forward_resolved, "MC-VP-020")
    assert later.description == "Shared requirement from the second parent"
    assert later.authoring_blocking is True

    # Declaration order is composition order, not a set union: swapping the
    # parents hands the shared requirement to the other one.
    assert _venue_tail(reverse_resolved) == (
        "MC-VP-020",
        "MC-VP-030",
        "MC-VP-010",
        "MC-VP-040",
    )
    earlier = _requirement(reverse_resolved, "MC-VP-020")
    assert earlier.description == "Shared requirement from the first parent"
    assert earlier.authoring_blocking is False
    assert sorted(_venue_tail(reverse_resolved)) == sorted(
        _venue_tail(forward_resolved)
    )
    assert reverse_resolved.profile_digest != forward_resolved.profile_digest


def test_venue_profile_rejects_a_parent_whose_digest_moved() -> None:
    """A moved parent is an error; this check is why the digest is recorded."""

    generic = generic_empirical_profile()
    parent = _venue(
        "mc_parent_moved_v1",
        extends=(parent_ref(generic),),
        requirements=(_spec("MC-VP-100", "Parent requirement as recorded"),),
        registry=_registry(),
    )
    parent_profile = resolve_profile("mc_parent_moved_v1", registry=_registry(parent))
    venue = _venue(
        "mc_venue_moved_v1",
        extends=(parent_ref(parent_profile),),
        requirements=(_spec("MC-VP-101", "Venue-only requirement"),),
        registry=_registry(parent),
    )

    # The recorded parent resolves: the rejection below is not vacuous.
    intact = resolve_profile("mc_venue_moved_v1", registry=_registry(parent, venue))
    assert _venue_tail(intact) == ("MC-VP-100", "MC-VP-101")

    moved = _venue(
        "mc_parent_moved_v1",
        extends=(parent_ref(generic),),
        requirements=(_spec("MC-VP-100", "Parent requirement after the parent moved"),),
        registry=_registry(),
    )
    moved_profile = resolve_profile("mc_parent_moved_v1", registry=_registry(moved))
    assert moved_profile.profile_id == parent_profile.profile_id
    assert moved_profile.profile_version == parent_profile.profile_version
    assert moved_profile.profile_digest != parent_profile.profile_digest

    with pytest.raises(ManuscriptContractError) as excinfo:
        resolve_profile("mc_venue_moved_v1", registry=_registry(moved, venue))
    message = str(excinfo.value)
    assert "mc_parent_moved_v1" in message
    assert parent_profile.profile_digest in message, (
        "the error must name the digest the declaration recorded so the drift "
        f"is identifiable; got: {message}"
    )
    assert moved_profile.profile_digest in message, (
        f"the error must name the digest the parent now resolves to; got: {message}"
    )

    # The declaration is unchanged: it still names the digest it was written
    # against, so the drift stays visible instead of being re-pinned.
    assert venue.extends[0].profile_digest == parent_profile.profile_digest

    # A parent that is absent altogether is an error too, not a skipped parent.
    with pytest.raises(ValueError) as absent:
        resolve_profile("mc_venue_moved_v1", registry=_registry(venue))
    assert "mc_parent_moved_v1" in str(absent.value)


def test_resolved_profile_digest_is_new_and_stable() -> None:
    generic = generic_empirical_profile()
    first = _venue(
        "mc_parent_stable_a_v1",
        extends=(parent_ref(generic),),
        requirements=(_spec("MC-VP-200", "First parent requirement"),),
        registry=_registry(),
    )
    second = _venue(
        "mc_parent_stable_b_v1",
        extends=(parent_ref(generic),),
        requirements=(_spec("MC-VP-201", "Second parent requirement"),),
        registry=_registry(),
    )
    parents = _registry(first, second)
    first_profile = resolve_profile("mc_parent_stable_a_v1", registry=parents)
    second_profile = resolve_profile("mc_parent_stable_b_v1", registry=parents)
    venue = _venue(
        "mc_venue_stable_v1",
        extends=(parent_ref(first_profile), parent_ref(second_profile)),
        requirements=(_spec("MC-VP-202", "Venue-only requirement"),),
        registry=parents,
    )
    registry = _registry(first, second, venue)

    resolved = resolve_profile("mc_venue_stable_v1", registry=registry)
    again = resolve_profile("mc_venue_stable_v1", registry=registry)

    assert resolved == again
    assert resolved.profile_digest == again.profile_digest
    assert resolved.profile_digest == canonical_digest(resolved.digest_payload())
    assert resolved.profile_digest == venue.resolved_profile_digest

    assert resolved.profile_digest not in {
        generic.profile_digest,
        first_profile.profile_digest,
        second_profile.profile_digest,
    }
    assert resolved.profile_digest != GENERIC_EMPIRICAL_V1_PROFILE_DIGEST

    # The resolved artifact is an ordinary digest-bound profile: it survives a
    # JSON round trip under the same digest.
    round_trip = ManuscriptRequirementProfileV1.model_validate(
        json.loads(json.dumps(resolved.model_dump(mode="json")))
    )
    assert round_trip.profile_digest == resolved.profile_digest


def test_venue_declaration_records_parent_lineage_durably(tmp_path: Path) -> None:
    generic = generic_empirical_profile()
    parent = _venue(
        "mc_parent_lineage_v1",
        extends=(parent_ref(generic),),
        requirements=(_spec("MC-VP-300", "Parent requirement"),),
        registry=_registry(),
    )
    parent_profile = resolve_profile("mc_parent_lineage_v1", registry=_registry(parent))
    venue = _venue(
        "mc_venue_lineage_v1",
        extends=(parent_ref(generic), parent_ref(parent_profile)),
        requirements=(_spec("MC-VP-301", "Venue-only requirement"),),
        registry=_registry(parent),
    )
    resolved = resolve_profile("mc_venue_lineage_v1", registry=_registry(parent, venue))

    write_venue_declaration(parent, tmp_path)
    path = write_venue_declaration(venue, tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert [entry["profile_id"] for entry in payload["extends"]] == [
        generic.profile_id,
        parent_profile.profile_id,
    ]
    assert [entry["profile_version"] for entry in payload["extends"]] == [
        generic.profile_version,
        parent_profile.profile_version,
    ]
    assert [entry["profile_digest"] for entry in payload["extends"]] == [
        generic.profile_digest,
        parent_profile.profile_digest,
    ]
    assert payload["resolved_profile_digest"] == resolved.profile_digest

    # The lineage survives the round trip through disk unchanged.
    restored = VenueProfileRegistry.from_directory(tmp_path)
    assert restored.profile_ids() == ("mc_parent_lineage_v1", "mc_venue_lineage_v1")
    assert resolve_profile(
        "mc_venue_lineage_v1", registry=restored
    ).profile_digest == resolved.profile_digest

    # The lineage is inside the declaration's own digest, so editing a recorded
    # parent digest on disk breaks the declaration instead of silently
    # re-pointing it.
    payload["extends"][1]["profile_digest"] = D1
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ManuscriptContractError):
        VenueProfileRegistry.from_directory(tmp_path)


def test_venue_profile_cannot_remove_a_parent_requirement_by_omission() -> None:
    """Omission never removes: silence keeps the parent requirement."""

    generic = generic_empirical_profile()
    parent = _venue(
        "mc_parent_retained_v1",
        extends=(parent_ref(generic),),
        requirements=(
            _spec("MC-VP-400", "Parent requirement the venue never mentions"),
            _spec("MC-VP-401", "Parent requirement the venue replaces"),
            _spec("MC-VP-402", "Another parent requirement the venue never mentions"),
        ),
        registry=_registry(),
    )
    parent_profile = resolve_profile(
        "mc_parent_retained_v1", registry=_registry(parent)
    )
    venue = _venue(
        "mc_venue_retained_v1",
        extends=(parent_ref(parent_profile),),
        requirements=(_spec("MC-VP-401", "Venue replacement"),),
        registry=_registry(parent),
    )
    resolved = resolve_profile("mc_venue_retained_v1", registry=_registry(parent, venue))

    assert _venue_tail(resolved) == ("MC-VP-400", "MC-VP-401", "MC-VP-402")
    assert _requirement(resolved, "MC-VP-400") == _requirement(
        parent_profile, "MC-VP-400"
    )
    assert _requirement(resolved, "MC-VP-402") == _requirement(
        parent_profile, "MC-VP-402"
    )
    assert _requirement(resolved, "MC-VP-401").description == "Venue replacement"


def test_venue_profile_removes_a_parent_requirement_only_when_declared() -> None:
    generic = generic_empirical_profile()
    parent = _venue(
        "mc_parent_removal_v1",
        extends=(parent_ref(generic),),
        requirements=(
            _spec("MC-VP-500", "Parent requirement the venue keeps"),
            _spec("MC-VP-501", "Parent requirement the venue removes"),
        ),
        registry=_registry(),
    )
    parents = _registry(parent)
    parent_profile = resolve_profile("mc_parent_removal_v1", registry=parents)
    venue = _venue(
        "mc_venue_removal_v1",
        extends=(parent_ref(parent_profile),),
        removed=("MC-VP-501",),
        requirements=(_spec("MC-VP-502", "Venue-only requirement"),),
        registry=parents,
    )
    resolved = resolve_profile("mc_venue_removal_v1", registry=_registry(parent, venue))

    assert _venue_tail(resolved) == ("MC-VP-500", "MC-VP-502")
    assert venue.removed_requirement_ids == ("MC-VP-501",)
    assert "MC-VP-501" in _requirement_ids(parent_profile)
    assert resolved.profile_digest == venue.resolved_profile_digest

    # Removing something no parent declares is drift, not a no-op.
    with pytest.raises(ManuscriptContractError) as unknown:
        _venue(
            "mc_venue_removal_unknown_v1",
            extends=(parent_ref(parent_profile),),
            removed=("MC-VP-599",),
            registry=parents,
        )
    assert "MC-VP-599" in str(unknown.value)

    # Removing and declaring the same ID is a contradiction, not a precedence
    # puzzle for the reader to solve.
    with pytest.raises(ValueError) as collision:
        _venue(
            "mc_venue_removal_collision_v1",
            extends=(parent_ref(parent_profile),),
            removed=("MC-VP-500",),
            requirements=(_spec("MC-VP-500", "Venue replacement"),),
            registry=parents,
        )
    assert "MC-VP-500" in str(collision.value)
