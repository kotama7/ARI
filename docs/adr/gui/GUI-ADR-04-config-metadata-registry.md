---
sources:
  - path: ari-core/ari/config/field_registry.py
    role: implementation
  - path: ari-core/ari/config/resolver.py
    role: implementation
  - path: ari-core/ari/config/__init__.py
    role: implementation
  - path: ari-core/ari/viz/v1/dto.py
    role: implementation
  - path: ari-core/ari/viz/v1/router.py
    role: implementation
  - path: ari-core/ari/viz/frontend/src/services/api/v1types.gen.ts
    role: implementation
  - path: ari-core/ari/configs/defaults.yaml
    role: config
  - path: ari-core/tests/test_gui_config_field_registry.py
    role: test
  - path: ari-core/tests/test_gui_config_resolver.py
    role: test
  - path: docs/reference/configuration.md
    role: doc
last_verified: 2026-08-17
---

# GUI-ADR-04: config schema metadata storage and versioning

Status: accepted (2026-07-23), gate G3. Recorded as a clerical backfill — the
registry was already implemented when the decision was written down.

Decision: the metadata `ARIConfig` cannot express in its pydantic types — UI
category, level, scope, sensitivity, mutability, `applies_when`, `env_override`
— lives in code, in `ari-core/ari/config/field_registry.py`. A hand-authored
`FIELD_META` overlay (a key ending in `.` is a prefix, every other key is an
exact path; `_resolve_meta` merges all matching entries most-general-first so an
exact path overrides its prefix) is merged onto the automatic
`walk_config_leaves()` enumeration of declared model fields by
`build_field_registry()`, which serves `GET /api/v1/config/schema`. There is no
external metadata file: the module reads no filesystem, no clock and no
environment, so two builds are identical. Full coverage is a *runtime*
invariant, not only a test — `get_uncovered()` must return `[]`, and
`build_field_registry()` raises `LookupError` naming the uncovered paths when it
does not, so a config leaf cannot ship without metadata. Versioning is split on
two axes: the payload `schema_version` (`resolver.SCHEMA_VERSION = 1`, surfaced
as `ConfigSchemaV1.schema_version`) describes the displayed schema and stays put
for additive change; `resolver_version`
(`resolver.RESOLVER_VERSION = "legacy-compatible-1"`) is the identity of the
resolution algorithm and a rule change must bump it. Where GUI *documents*
(project config, run template, run draft) are stored is a separate decision —
ADR-12, `gui_store/`.

Alternatives: an external YAML/JSON metadata file, rejected because it becomes a
fourth configuration file and reproduces the parity risk the repo already
carries with `ari-core/ari/configs/defaults.yaml`, whose RQGM and
proposal-router values no loader reads: they mirror the typed pydantic
defaults, and parity between the two homes is held only by the
`ari-core/tests/test_rqgm_*.py` suites. (That file is not wholly dead — its
`models.lineage_decision_default` key is read by `_config_default` in
`ari-core/ari/orchestrator/lineage_decision.py`; the parity-mirror blocks
are.) In code, the metadata is type-checked, reviewed as code, and lives in
the same commit as the pydantic model, so a model change and its metadata
change appear in one diff. A single version number covering both the payload
shape and the resolution rules was rejected: the initial resolver deliberately
*reproduces* today's imperative precedence rather than improving it, so its
identity moves on a different cadence from the schema it is served beside.

Consequences accepted: metadata edits are Python diffs and are not editable by
non-engineers — acceptable because this program's operators are developers.
Adding a config leaf fails the build until `FIELD_META` covers it, and the test
suite additionally freezes the leaf count (`EXPECTED_LEAF_COUNT`, a
ratchet-upward number). "100 % coverage" means 100 % of *declared* pydantic
leaves: `extra="allow"` blocks that exist only as untyped YAML keys (`hpc`,
`container`, `letta`, `claim_gate_policy`, `lineage_decision`, …) produce no
leaf, and their `FIELD_META` prefix entries are forward-declared for the day
they become typed. Converting the metadata to a data file later requires a
`schema_version` bump and a record superseding this one.

Divergences from the decision as written. The shipped entry shape is a subset of
the `ConfigFieldMeta` sketch in the superseded plan: `ConfigFieldV1` carries
`path`, `value_type`, `default`, `enum`, `required`, `category`, `level`,
`scope`, `sensitivity`, `mutability`, `applies_when`, `notes`, `source` and
`env_override`; the sketch's `minimum`, `maximum`, `description_key`,
`merge_strategy`, `dependencies`, `conflicts`, `capability` and `deprecation`
exist nowhere in the registry, so the plan's field-alias/deprecation migration
functions have no counterpart. The two version values are also declared in more
than one home: `ari-core/ari/config/resolver.py` defines the constants, while
`ari-core/ari/viz/v1/dto.py` restates them as literal defaults without importing
them and the generated
`ari-core/ari/viz/frontend/src/services/api/v1types.gen.ts` pins the same
string — a bump touches all three. Finally, the "migration preview" this record
attaches to a `resolver_version` bump is a policy obligation with no machinery
behind it; the only preview that exists is new-run resolution
(`POST /api/v1/run-drafts/{draft_id}/resolve-config`), which previews values,
not a version migration.

Supersedes: nothing. Permanent documentation: `docs/reference/configuration.md`,
sections "Configuration control plane (`/api/v1/config/*`)", "Field registry
(canonical field metadata)" and "Resolution model". Owning tests:
`ari-core/tests/test_gui_config_field_registry.py` (coverage invariant, loud
failure on an uncovered leaf, frozen leaf count, closed vocabularies,
determinism, `ENV_OVERRIDES` pinned verbatim, endpoint happy path and
secret-metadata-only redaction) and `ari-core/tests/test_gui_config_resolver.py`
(resolver parity).
