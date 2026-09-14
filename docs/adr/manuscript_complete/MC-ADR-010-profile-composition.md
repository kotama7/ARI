---
sources:
  - path: ari-core/ari/manuscript/profiles.py
    role: implementation
  - path: ari-core/ari/manuscript/contracts.py
    role: implementation
  - path: ari-core/ari/manuscript/venue_profiles
    role: implementation
  - path: ari-core/tests/test_manuscript_venue_profile_composition.py
    role: test
  - path: ari-core/tests/test_manuscript_venue_profile_registry.py
    role: test
last_verified: 2026-08-14
---

# MC-ADR-010: venue profile composition

Decision: a venue or project profile is a `ManuscriptVenueProfileV1`
declaration that pins every parent at its exact `profile_digest`, applies
parents in `extends` order, and is resolved at read time. Resolution yields an
ordinary `ManuscriptRequirementProfileV1`, so the mandatory resolved digest is
that profile's own `profile_digest` and no consumer changes. Rejected: a fully
materialized resolved profile artifact; it stores the composition's output and
discards its inputs, so lineage is unverifiable and a parent that moved is
invisible rather than an error. Consequences:
`ManuscriptRequirementProfileV1` gains no field, because `digest_payload()` is
the whole `model_dump` and one defaulted field would move
`generic_empirical_v1`'s digest
`sha256:6639e048128d9e78b5b7a0f67e3b149c826a51073f6f9c5c1f7f82244c217ba4`,
which persisted readiness and authoring-binding evidence pins — composition
therefore lives in a separate model. Omission never removes: an unmentioned
parent requirement survives, and dropping one takes an explicit
`removed_requirement_ids` entry naming an ID some parent declares. A parent
whose version or digest moved is an error, never a warning; re-mint the
declaration, never relax the pin. Reverse only with a materialization format
that carries parent identities and a migration for every stored declaration.
Owning tests: `test_generic_empirical_profile_digest_is_pinned_and_parentless`,
`test_pinned_profile_digest_matches_persisted_evidence_records`,
`test_venue_profile_rejects_a_parent_whose_digest_moved`,
`test_venue_profile_cannot_remove_a_parent_requirement_by_omission`, and the
venue profile registry tests.
