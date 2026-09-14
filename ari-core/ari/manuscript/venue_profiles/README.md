# ari.manuscript.venue_profiles

Venue and project requirement profile declarations, composed at resolution time.

One file per profile, named `<profile_id>.json`, holding one
`ManuscriptVenueProfileV1` (schema:
`ari/schemas/manuscript_venue_profile_v1.schema.json`). The filename must equal
the `profile_id` it declares, and every stored declaration must pin
`resolved_profile_digest` — the loader rejects both otherwise.

No venue profile ships today: `generic_empirical_v1` is built in code
(`profiles.py`) and is the root of every lineage. Declaring one here is what
makes `manuscript.profile: <profile_id>` (or `ARI_MANUSCRIPT_PROFILE`) resolve
to it; nothing else in the pipeline changes, because resolution yields an
ordinary `ManuscriptRequirementProfileV1`.

## Declaring one

A declaration extends by **explicit composition**. It names each parent at the
exact `profile_digest` it was written against, and states only its deltas:

- a requirement whose `requirement_id` already exists in the merged parents
  REPLACES it, in place;
- a new `requirement_id` is appended;
- a parent requirement the declaration never mentions survives unchanged —
  removal is never implicit. To drop one, name it in `removed_requirement_ids`;
- a parent whose digest or version no longer matches what the declaration
  recorded is an error, not a warning. That pin exists to catch a parent that
  moved, and the fix is to re-mint the declaration against the new parent, never
  to relax the pin.

Mint the file with `build_venue_declaration()` + `write_venue_declaration()`,
which compute `resolved_profile_digest` from the composition itself:

```python
from ari.manuscript.profiles import (
    build_venue_declaration, generic_empirical_profile, parent_ref,
    write_venue_declaration, VENUE_PROFILE_DIR,
)

declaration = build_venue_declaration(
    profile_id="<venue>_v1",
    profile_version="1",
    paper_family="generic_empirical",
    policy_version="1",
    evaluator_compatibility=("manuscript-evaluator-v1",),
    extends=(parent_ref(generic_empirical_profile()),),
    requirements=(...,),
)
write_venue_declaration(declaration, VENUE_PROFILE_DIR)
```

## Contents

- `README.md` — this file.

## See also

- **Composition rules** → the `ari/manuscript/profiles.py` module docstring
  (authoritative).
- **Requirement profile contract** → `ari/manuscript/contracts.py`
  (`ManuscriptRequirementProfileV1`, `ManuscriptVenueProfileV1`).
