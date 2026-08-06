"""Pydantic v2 DTOs for ``/api/v1`` (gui_refresh Wave 2a, ADR-02/ADR-08).

Every resource model carries ``schema_version: Literal[1]`` so consumers can
detect the contract revision; changes are additive by policy (plan 04 §API
principles). pydantic v2 is already a core dependency (ADR-02: zero new
runtime dependencies).

Conventions pinned here:

- ``run_id`` is the checkpoint directory name (ADR-08 — stable opaque ID,
  compatible with the existing fixtures/contracts);
- ``display_name`` is derived presentation only (timestamp prefix stripped),
  never an identity;
- ``mtime_utc`` is an ISO 8601 UTC string (``YYYY-MM-DDTHH:MM:SSZ``) — plan
  04 §API principles (timestamps are UTC ISO 8601);
- ``TreeV1.nodes`` passes the ``tree_view.build_tree_view`` node list through
  byte-preserving (no key added/removed/reordered — 024 §7 contract);
- ``RunDetailV1.capabilities`` is a feature map derived from artifact
  existence only (``rqgm`` == ``rqgm_state.json`` present; ``ari.rqgm`` is
  deliberately NOT imported — task 08 owns the RQGM domain DTOs).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ProjectV1(BaseModel):
    """One project. Wave 2a serves exactly one: the virtual ``default``
    project aggregating the checkpoint search bases (ADR-08)."""

    schema_version: Literal[1] = 1
    project_id: str
    name: str
    checkpoint_roots: list[str]
    run_count: int


class RunSummaryV1(BaseModel):
    """Listing/summary card for one run (checkpoint).

    ``best_metric`` surfaces the best ``metrics._scientific_score`` across
    the run's nodes (``None`` when no node carries one); ``review_score``
    mirrors ``review_report.json`` ``overall_score``/``score``.
    """

    schema_version: Literal[1] = 1
    run_id: str
    project_id: str
    display_name: str
    status: str
    node_count: int
    review_score: float | None = None
    best_metric: float | None = None
    mtime_utc: str
    checkpoint_path: str
    has_paper: bool = False


class RunDetailV1(RunSummaryV1):
    """RunSummaryV1 plus detail-only fields (artifact-derived, read-only)."""

    phase: str | None = None
    capabilities: dict[str, bool] = Field(default_factory=dict)


class TreeV1(BaseModel):
    """Node tree for one run. ``nodes`` is the byte-preserved pass-through of
    the canonical tree loader; ``revision`` is the resolved tree file's
    ``st_mtime_ns`` (0 when no tree file exists) for cheap change detection."""

    schema_version: Literal[1] = 1
    run_id: str
    revision: int
    nodes: list[dict]


# ── secret readiness (gui_refresh Wave 3a, ADR-11 / RR-P0-2) ───────────────


class SecretV1(BaseModel):
    """Readiness of ONE known secret — never its value (ADR-11).

    ``source_class`` says where the winning definition lives (``project_env``
    = active checkpoint .env, ``repo_env`` = ARI/.env or ari-core/.env,
    ``user_env`` = ~/.env, ``process_env`` = os.environ fallback; ``None``
    when not configured). ``last_updated`` is the source .env file's mtime as
    UTC ISO 8601 (``None`` for ``process_env`` / not configured).
    """

    name: str
    configured: bool
    source_class: (
        Literal["project_env", "repo_env", "user_env", "process_env"] | None
    ) = None
    last_updated: str | None = None


class SecretStatusV1(BaseModel):
    """Envelope for ``GET /api/v1/secrets/status`` — the allowlisted secret
    names (``ari.viz.v1.secrets.SECRET_NAMES``) in fixed order. Values are
    structurally impossible here: :class:`SecretV1` has no value field."""

    schema_version: Literal[1] = 1
    secrets: list[SecretV1]


# ── secret assignment (gui_refresh task 06 Wave 4d, ADR-05) ────────────────


class SecretValueRequestV1(BaseModel):
    """PUT /api/v1/secrets/{secret_id} body — the write-only value channel
    (plan 05 §Configuration API).  The value never appears in any response,
    manifest, or log; the target name is the path's ``secret_id`` and must
    be on the ``ari.viz.v1.secrets.SECRET_NAMES`` allowlist."""

    value: str


class SecretUpdatedV1(BaseModel):
    """PUT /api/v1/secrets/{secret_id} acknowledgment — READINESS-shaped
    (ADR-05/ADR-11): the post-write :class:`SecretV1` readiness row for the
    assigned name.  Returning the value is structurally impossible —
    ``SecretV1`` has no value field."""

    schema_version: Literal[1] = 1
    secret: SecretV1


# ── model/provider catalog (gui_refresh task 06 Wave 4d, plan 05) ──────────


class ModelProviderV1(BaseModel):
    """One LLM provider row of the server-side model catalog: the static
    suggestion list the legacy ``GET /api/models`` serves, plus the
    provider's API-key env name (``None`` for keyless providers) so the
    Studio SecretField can target ``PUT /api/v1/secrets/{env_key}`` without
    a frontend provider->key constant."""

    id: str
    name: str
    models: list[str] = Field(default_factory=list)
    env_key: str | None = None


class ModelCatalogV1(BaseModel):
    """GET /api/v1/config/catalogs/models envelope (plan 05 §Configuration
    API; plan 06 §Schema-driven rendering: frontend model/provider constants
    are replaced by this server catalog)."""

    schema_version: Literal[1] = 1
    providers: list[ModelProviderV1] = Field(default_factory=list)


# ── list envelopes (success payloads for the collection endpoints) ─────────


class ProjectListV1(BaseModel):
    schema_version: Literal[1] = 1
    projects: list[ProjectV1]


class RunListV1(BaseModel):
    schema_version: Literal[1] = 1
    project_id: str
    runs: list[RunSummaryV1]


# ── config schema (gui_refresh task 05 Wave 3a) ────────────────────────────


class ConfigFieldV1(BaseModel):
    """One canonical config field: an ``ARIConfig`` leaf merged with the
    hand-authored ``ari.config.field_registry.FIELD_META`` overlay (plan 05
    §Canonical field metadata).  Metadata only — never an effective value;
    ``sensitivity == "secret_reference"`` fields additionally carry NO
    default (the registry redacts it before this DTO is built)."""

    path: str
    value_type: str
    default: Any = None
    enum: list[Any] | None = None
    required: bool = False
    category: str
    level: Literal["basic", "advanced", "expert"]
    scope: Literal["preference", "installation", "project", "template", "run"]
    sensitivity: Literal["public", "internal", "secret_reference"]
    mutability: Literal["draft", "new_run_only", "resume_mutable", "read_only"]
    applies_when: str | None = None
    notes: str | None = None
    source: Literal["pydantic"] = "pydantic"
    env_override: str | None = None


class ConfigSchemaV1(BaseModel):
    """GET /api/v1/config/schema envelope.  ``resolver_version`` is pinned to
    the plan-05 initial resolver identity (``legacy-compatible-1``) and is
    versioned separately from ``schema_version`` by design."""

    schema_version: Literal[1] = 1
    resolver_version: Literal["legacy-compatible-1"] = "legacy-compatible-1"
    fields: list[ConfigFieldV1]


# ── resolved config manifest (gui_refresh task 05 Wave 3a) ─────────────────


class ProvenanceEntryV1(BaseModel):
    """Where one resolved leaf's effective value came from (plan 05
    §Resolved manifest).  ``confidence`` is ``high`` when the source file
    was present, ``low`` for reconstructed/current-env layers."""

    source: Literal[
        "default", "workflow", "launch_config", "env", "checkpoint_state"
    ]
    mutable: bool
    confidence: Literal["high", "low"]


class SecretReferenceV1(BaseModel):
    """Configured-flag entry for one secret_reference leaf — never a value
    (structurally impossible: no value field)."""

    provider: str
    configured: bool


class ResolvedConfigV1(BaseModel):
    """GET /api/v1/runs/{run_id}/resolved-config envelope: the plan-05
    resolved manifest reconstructed post-hoc by
    ``ari.config.resolver.resolve_run_config`` (legacy-compatible-1).

    ``resolved_at`` is derived from source-file mtimes (never ``now()``) so
    repeated GETs are byte-stable; ``digest`` is ``sha256:`` over the
    redacted canonical ``values`` JSON only.  Secrets never appear in
    ``values``/``provenance`` — only as :class:`SecretReferenceV1` flags."""

    schema_version: Literal[1] = 1
    resolver_version: Literal["legacy-compatible-1"] = "legacy-compatible-1"
    run_id: str
    resolved_at: str | None = None
    digest: str
    source_stack: list[str]
    values: dict
    provenance: dict[str, ProvenanceEntryV1]
    secret_references: dict[str, SecretReferenceV1] = Field(
        default_factory=dict
    )
    warnings: list[str] = Field(default_factory=list)


# ── new-run preview resolution (gui_refresh task 05 Wave 3b) ───────────────


class RejectedOverrideV1(BaseModel):
    """One rejected/ignored override kept as an explanation (plan 05
    §Resolution model: rejected overrides are returned, never silently
    dropped).  ``reason`` vocabulary: the ``validate_patch`` closed set
    (``invalid_enum``/``invalid_type``/``read_only``/``not_project_scope``)
    plus ``invalid_value`` (pydantic construction rejected it) and
    ``interlock_mismatch`` (warn+fallback ``resolve_effective_mode``
    semantics).  Secret values are structurally impossible here: secret
    paths never reach provenance."""

    source: Literal["workflow", "profile", "project", "template", "draft", "env"]
    value: Any = None
    reason: str
    expected: Any = None


class NewRunProvenanceV1(BaseModel):
    """Provenance for one leaf of the NEW-RUN preview chain (plan 05
    §Resolution model / New run).  ``mutable`` is true for every
    non-read_only field — before launch even ``new_run_only`` windows are
    open.  ``confidence`` is ``low`` only for the env overlay (the
    launch-time environment may differ from the preview-time one)."""

    source: Literal[
        "default", "workflow", "profile", "project", "template", "draft", "env"
    ]
    mutable: bool
    confidence: Literal["high", "low"]
    rejected_override: RejectedOverrideV1 | None = None


class ResolvedNewRunConfigV1(BaseModel):
    """POST /api/v1/run-drafts/{draft_id}/resolve-config envelope: the
    plan-05 resolved manifest for a run that does not exist yet
    (``ari.config.resolver.resolve_new_run_config``).

    Same manifest shape as :class:`ResolvedConfigV1`; ``run_id`` carries the
    DRAFT id (no run exists yet), ``source_stack`` lists only the layers
    actually present, and ``resolved_at`` derives from the store document
    mtimes (never ``now()``).  Secrets never appear in ``values`` — only as
    :class:`SecretReferenceV1` flags (``provider`` names the layer)."""

    schema_version: Literal[1] = 1
    resolver_version: Literal["legacy-compatible-1"] = "legacy-compatible-1"
    run_id: str
    resolved_at: str | None = None
    digest: str
    source_stack: list[str]
    values: dict
    provenance: dict[str, NewRunProvenanceV1]
    secret_references: dict[str, SecretReferenceV1] = Field(
        default_factory=dict
    )
    warnings: list[str] = Field(default_factory=list)


class DraftResolveRequestV1(BaseModel):
    """POST body for both /run-drafts/{draft_id}/resolve-config and
    /validate — the optional execution profile to preview with (the same
    three bundled profiles the CLI ``--profile`` flag accepts)."""

    profile: Literal["laptop", "hpc", "cloud"] | None = None


class DraftValidationErrorV1(BaseModel):
    """One draft-validation error.  ``reason`` vocabulary: the
    ``validate_patch`` closed set (``field_registry.PATCH_REASONS``,
    including the ADR-09 ``mode_interlock_mismatch`` a half-set/disagreeing
    mode pair raises) plus ``invalid_value`` and ``interlock_mismatch``
    (plan 05 §Interlocks: draft validation treats an inconsistent intent
    pair as an ERROR even though the runtime resolves it warn+fallback)."""

    path: str
    reason: str
    message: str
    expected: Any = None


class DraftValidationV1(BaseModel):
    """POST /api/v1/run-drafts/{draft_id}/validate envelope — distilled from
    the same resolution run as resolve-config: ``errors`` are the
    draft-attributable rejections (strict), ``warnings`` the full manifest
    warning list (other layers' rejections stay warnings)."""

    schema_version: Literal[1] = 1
    draft_id: str
    valid: bool
    errors: list[DraftValidationErrorV1] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# ── config CRUD documents (gui_refresh task 05 Wave 3b, ADR-12) ────────────
#
# GUI-only configuration documents persisted by ari/viz/v1/store.py under
# {workspace_root}/gui_store/.  ``values`` is always a FLAT map of
# ``{"dotted.path": value}`` validated against the canonical field registry
# (``ari.config.field_registry.validate_patch``); ``revision`` is the store's
# per-document optimistic-concurrency counter (ETag/If-Match); ``updated_at``
# is the document file's mtime as UTC ISO 8601 — never ``now()`` (P2).


class ProjectConfigV1(BaseModel):
    """GET/PATCH /api/v1/projects/{project_id}/config envelope.  A missing
    document reads as ``revision 0`` with empty values — the matching PATCH
    ``If-Match: "0"`` is the create path."""

    schema_version: Literal[1] = 1
    revision: int
    values: dict[str, Any] = Field(default_factory=dict)
    updated_paths_count: int = 0


class RunTemplateSummaryV1(BaseModel):
    """Listing row for GET /api/v1/run-templates."""

    schema_version: Literal[1] = 1
    template_id: str
    name: str
    revision: int
    updated_at: str


class RunTemplateListV1(BaseModel):
    schema_version: Literal[1] = 1
    templates: list[RunTemplateSummaryV1]


class RunTemplateV1(BaseModel):
    """One run template (GET/POST/PATCH /api/v1/run-templates[/{id}])."""

    schema_version: Literal[1] = 1
    template_id: str
    name: str
    revision: int
    values: dict[str, Any] = Field(default_factory=dict)
    updated_at: str


class RunTemplateDeletedV1(BaseModel):
    """DELETE /api/v1/run-templates/{template_id} acknowledgment."""

    schema_version: Literal[1] = 1
    template_id: str
    deleted: Literal[True] = True


class RunDraftV1(BaseModel):
    """One run draft (POST /api/v1/run-drafts, GET/PATCH .../{draft_id}).
    ``draft_id`` is server-generated (``draft-<12 hex>``); ``template_id``
    is an optional immutable link to the template the draft started from.
    ``goal`` (Wave 4e, additive) is the free-text research goal the launch
    materializes into ``{ckpt}/experiment.md`` — it is a document field, not
    a dotted config path, so it never rides ``values``."""

    schema_version: Literal[1] = 1
    draft_id: str
    template_id: str | None = None
    revision: int
    values: dict[str, Any] = Field(default_factory=dict)
    goal: str | None = None
    updated_at: str


# Request bodies (documented in OpenAPI; parsing/validation happens in
# ari/viz/v1/config_api.py — unknown top-level keys are a 400, not ignored).


class ValuesPatchRequestV1(BaseModel):
    """PATCH body for every config document: a partial ``{dotted.path:
    value}`` update validated against the canonical field registry."""

    values: dict[str, Any]


class RunTemplateCreateRequestV1(BaseModel):
    """POST /api/v1/run-templates body.  ``template_id`` is caller-chosen
    (``^[a-z0-9][a-z0-9_-]{0,63}$`` — stricter lowercase profile of the
    store grammar, stable on case-insensitive filesystems)."""

    template_id: str
    name: str
    values: dict[str, Any] = Field(default_factory=dict)


class RunDraftCreateRequestV1(BaseModel):
    """POST /api/v1/run-drafts body — all fields optional; the server
    generates the ``draft_id``.  ``goal`` (Wave 4e, additive) is the
    free-text research goal a later ``POST /api/v1/runs`` writes into
    ``{ckpt}/experiment.md``."""

    template_id: str | None = None
    values: dict[str, Any] = Field(default_factory=dict)
    goal: str | None = None


# ── idempotent launch (gui_refresh tasks 04/06 Wave 4e) ────────────────────


class RunLaunchRequestV1(BaseModel):
    """POST /api/v1/runs body (plan 06 §Launch protocol).

    ``draft_id`` names the durable run draft to launch; ``display_name``
    only seeds the human-readable slug half of the run id (never identity —
    plan 04 §Run identity); ``profile`` is the CLI ``--profile`` closed set;
    ``idempotency_key`` makes the POST retriable — a duplicate key replays
    the SAME ``run_id`` and spawns nothing (double-click safety)."""

    draft_id: str
    display_name: str | None = None
    profile: Literal["laptop", "hpc", "cloud"] | None = None
    idempotency_key: str | None = None


class RunLaunchedV1(BaseModel):
    """POST /api/v1/runs accepted envelope (plan 04 §Run identity and
    lifecycle: the collision-resistant ``run_id`` + status URL + checkpoint
    path/intent, returned before any slow work).  ``idempotent_replay`` is
    True when the response acknowledges an earlier launch for the same
    idempotency key (nothing was spawned by THIS request)."""

    schema_version: Literal[1] = 1
    run_id: str
    status_url: str
    checkpoint_path: str
    accepted: Literal[True] = True
    idempotent_replay: bool = False


# ── RQGM read models (gui_refresh task 08 Wave 4a — plan 08) ───────────────
#
# Server-only read DTOs over committed RQGM checkpoint artifacts (readers in
# ari/viz/v1/rqgm.py — ``ari.rqgm`` is never imported; the GUI re-executes no
# kernel/score-policy decision).  Truth rules enforced structurally:
#
# - registry lifecycle statuses are the closed 10-value implementation
#   vocabulary (``RegistryStatusV1``) and node score states the separate
#   5-value vocabulary (``NodeScoreStateV1``) — two state machines, never
#   mixed in one field;
# - raw adversarial output is only representable as ``RqgmRawAttackV1``,
#   which has NO numeric score/penalty field at all — a raw attack can never
#   be displayed as a validated penalty;
# - score observations always carry their ``policy_hash`` (plan 08: a score
#   is never shown without policy identity) and the two lineage channels
#   (penalty vs epoch-policy rewrite) are separate lists that no consumer
#   can accidentally merge into one series.

#: Registry lifecycle vocabulary — verbatim ``ari.rqgm.events.STATUS_VALUES``
#: (a frozen contract; parity is pinned by tests/test_gui_v1_rqgm.py).
RegistryStatusV1 = Literal[
    "candidate",
    "validated",
    "shadow",
    "probationary_active",
    "active",
    "warning",
    "probation",
    "quarantine",
    "retired",
    "banned",
]

#: Node score-state vocabulary (plan 08 §Governance state model) — DISTINCT
#: from the registry lifecycle; stale/invalidated/removed are logical states,
#: never physical deletion.
NodeScoreStateV1 = Literal[
    "computed", "recomputed", "stale", "invalidated", "removed"
]


class RqgmCapabilitiesV1(BaseModel):
    """GET /api/v1/runs/{run_id}/rqgm/capabilities.

    Capability detection from artifact presence only: no ``rqgm_state.json``
    ⇒ ``enabled=false`` with reason ``'simple_bfts run'``; ``paper_mode`` is
    ``paper_archive_state.json`` presence (execution mode and paper mode are
    independent axes — plan 08 §Paper Archive)."""

    schema_version: Literal[1] = 1
    run_id: str
    enabled: bool
    mode: str | None = None
    mode_source: str | None = None
    paper_mode: bool = False
    reasons: list[str] = Field(default_factory=list)


class RqgmIntegrityV1(BaseModel):
    """Tri-state integrity flags: ``True`` verified, ``False`` broken,
    ``None`` source missing (a missing source is never displayed as clean —
    plan 08 §Truth rules)."""

    transitions_chain_ok: bool | None = None
    registry_verified: bool | None = None
    audit_chain_ok: bool | None = None


class RqgmRegistrySummaryV1(BaseModel):
    """Bounded by-status counts (overview never embeds entry lists)."""

    component_count: int = 0
    prompt_count: int = 0
    components_by_status: dict[RegistryStatusV1, int] = Field(
        default_factory=dict
    )
    prompts_by_status: dict[RegistryStatusV1, int] = Field(
        default_factory=dict
    )


class RqgmOverviewV1(BaseModel):
    """GET /api/v1/runs/{run_id}/rqgm/overview — bounded summary; current
    state is the COMMITTED-transition replay (a torn/uncommitted tail is
    never adopted), snapshots are used for verification only."""

    schema_version: Literal[1] = 1
    run_id: str
    current_epoch: str | None = None
    utility_policy_hash: str | None = None
    constitution_hash: str | None = None
    registry_summary: RqgmRegistrySummaryV1
    last_committed_transition_at: str | None = None
    integrity: RqgmIntegrityV1
    degraded_reasons: list[str] = Field(default_factory=list)


class RqgmComponentV1(BaseModel):
    """One governed component from committed replay (plus the event ids that
    produced its current state)."""

    component_id: str
    role: str
    tier: str
    status: RegistryStatusV1
    prompt_id: str | None = None
    epoch_id_registered: str = ""
    source_event_ids: list[str] = Field(default_factory=list)
    capabilities: dict = Field(default_factory=dict)


class RqgmPromptV1(BaseModel):
    """One governed prompt/policy entry from committed replay."""

    prompt_id: str
    role: str
    status: RegistryStatusV1
    prompt_hash: str
    prompt_sha256: str = ""
    source: dict = Field(default_factory=dict)
    spec_ref: str | None = None
    epoch_id_registered: str = ""
    source_event_ids: list[str] = Field(default_factory=list)


class RqgmRegistryV1(BaseModel):
    """GET /api/v1/runs/{run_id}/rqgm/registry.

    Entries come from committed replay of ``rqgm_transitions.jsonl`` (the
    truth log); the ``rqgm_registry.json`` rollup is read only to compute
    ``verified`` (rollup ``as_of_event_hash`` == replay tail — plan 08
    §Truth rules)."""

    schema_version: Literal[1] = 1
    run_id: str
    verified: bool | None = None
    rollup_as_of_event_hash: str | None = None
    replay_tail_event_hash: str | None = None
    components: list[RqgmComponentV1] = Field(default_factory=list)
    prompts: list[RqgmPromptV1] = Field(default_factory=list)
    active_components: dict[str, str] = Field(default_factory=dict)
    active_prompt_hashes: dict[str, str] = Field(default_factory=dict)
    degraded_reasons: list[str] = Field(default_factory=list)


class RqgmTransitionEntryV1(BaseModel):
    """One committed transition-log entry: a prepare..commit transaction or
    a committed standalone event (initial ``epoch_open`` /
    ``emergency_quarantine``).  Arrays are summarized as counts; ``events``
    carries the full raw line dicts only on ``?expand=1`` (unknown artifact
    fields pass through untouched — additive tolerance)."""

    kind: Literal["transaction", "standalone"]
    transition_id: str | None = None
    byte_offset: int
    event_count: int
    event_type_counts: dict[str, int] = Field(default_factory=dict)
    rule_ids: list[str] = Field(default_factory=list)
    epoch_closed: str | None = None
    epoch_opened: str | None = None
    first_event_id: str = ""
    last_event_id: str = ""
    committed_at: str | None = None
    events: list[dict] | None = None


class RqgmTransitionsPageV1(BaseModel):
    """GET /api/v1/runs/{run_id}/rqgm/transitions?cursor=&limit=&expand=.

    ``cursor`` is a stable byte offset into ``rqgm_transitions.jsonl`` (an
    entry's ``byte_offset``); pages select entries with ``byte_offset >=
    cursor`` so paging has no gaps/duplicates over an append-only file.
    ``source_revision`` is the parsed byte length (a trailing partial line is
    excluded — committed-only)."""

    schema_version: Literal[1] = 1
    run_id: str
    entries: list[RqgmTransitionEntryV1] = Field(default_factory=list)
    next_cursor: int | None = None
    total_entries: int = 0
    chain_ok: bool | None = None
    source_revision: int = 0
    degraded_reasons: list[str] = Field(default_factory=list)


class RqgmAuditEntryV1(BaseModel):
    """One ``rqgm_audit.jsonl`` line.  ``summary`` keeps scalars and
    summarizes arrays as ``<key>_count``; the raw payload rides only on
    ``?expand=1`` (passthrough — unknown fields preserved)."""

    byte_offset: int
    event_id: str = ""
    event_type: str = ""
    record_id: str | None = None
    record_type: str | None = None
    epoch_id: str | None = None
    event_hash: str = ""
    ts_iso: str | None = None
    summary: dict = Field(default_factory=dict)
    payload: dict | None = None


class RqgmAuditPageV1(BaseModel):
    """GET /api/v1/runs/{run_id}/rqgm/audit?cursor=&limit=&record_type=&epoch=
    — same byte-offset cursor semantics as the transitions page."""

    schema_version: Literal[1] = 1
    run_id: str
    entries: list[RqgmAuditEntryV1] = Field(default_factory=list)
    next_cursor: int | None = None
    total_entries: int = 0
    chain_ok: bool | None = None
    source_revision: int = 0
    degraded_reasons: list[str] = Field(default_factory=list)


class RqgmScoreObservationV1(BaseModel):
    """One score-lineage observation (plan 08 §Score Lineage).

    ``policy_hash`` is always the EPOCH utility-policy hash the observation
    was made under (the penalty-side frozen weights live inside the source
    record, plan 08's naming-subtlety rule).  ``state`` is ``None`` when the
    source asserts a frontier fact rather than a node score state (never
    guessed).  ``values`` carries the source fields verbatim (sentinel key
    names included) — passthrough, no re-computation."""

    source: Literal["utility_record", "node_metrics", "erasure_event"]
    record_id: str | None = None
    epoch_id: str | None = None
    policy_hash: str | None = None
    values: dict = Field(default_factory=dict)
    state: NodeScoreStateV1 | None = None
    validated_attack_ids: list[str] = Field(default_factory=list)


class RqgmRawAttackV1(BaseModel):
    """A RAW adversarial claim (``atk_*``): kind is pinned to ``'raw'`` and
    the model has NO score/penalty/confidence field — a raw attack is
    structurally incapable of carrying a score (plan 08: raw attacks never
    score; severity_claimed is the attacker's CLAIM, not a penalty)."""

    kind: Literal["raw"] = "raw"
    record_id: str
    adversary_type: str | None = None
    severity_claimed: str | None = None
    status: str | None = None
    epoch_id: str | None = None
    target_node_id: str | None = None


class RqgmValidatedAttackV1(BaseModel):
    """An adjudicated ``vat_*`` record — the only attack kind that may drive
    a penalty (via a UtilityRecord referencing its id)."""

    kind: Literal["validated"] = "validated"
    record_id: str
    raw_attack_id: str | None = None
    judgment_id: str | None = None
    verdict: str | None = None
    severity: str | None = None
    affected_components: list[str] = Field(default_factory=list)
    target_component_id: str | None = None
    epoch_id: str | None = None


class RqgmNodeLineageV1(BaseModel):
    """GET /api/v1/runs/{run_id}/rqgm/nodes/{node_id}/lineage — the TWO
    independent score channels (plan 08 §Score Lineage), never merged into
    one series: ``penalty_channel`` (adversarial penalty inside an epoch)
    and ``policy_channel`` (epoch-boundary utility-policy rewrite /
    invalidation)."""

    schema_version: Literal[1] = 1
    run_id: str
    node_id: str
    penalty_channel: list[RqgmScoreObservationV1] = Field(
        default_factory=list
    )
    policy_channel: list[RqgmScoreObservationV1] = Field(default_factory=list)
    raw_attacks: list[RqgmRawAttackV1] = Field(default_factory=list)
    validated_attacks: list[RqgmValidatedAttackV1] = Field(
        default_factory=list
    )
    degraded_reasons: list[str] = Field(default_factory=list)


class RqgmScoreRewriteV1(BaseModel):
    """One epoch-boundary score rewrite: a T20 utility-policy supersession
    joined with its ``SelectiveErasureEvent`` / ``FrontierRebuildEvent``
    consequences (node sets come from the real event fields, never
    recomputed)."""

    rewrite_id: str
    transition_id: str | None = None
    epoch_id: str | None = None
    from_policy_hash: str | None = None
    to_policy_hash: str | None = None
    invalidated_node_count: int = 0
    invalidated_node_ids: list[str] = Field(default_factory=list)
    recompute_node_ids: list[str] = Field(default_factory=list)
    frontier_removed_node_ids: list[str] = Field(default_factory=list)
    frontier_reinstated_node_ids: list[str] = Field(default_factory=list)
    source_event_ids: list[str] = Field(default_factory=list)


class RqgmScoreRewritesPageV1(BaseModel):
    """GET /api/v1/runs/{run_id}/rqgm/score-rewrites?cursor=&limit= —
    ``cursor`` is an integer index into the deterministic joined rewrite
    list (transition order, then unjoined audit events in file order)."""

    schema_version: Literal[1] = 1
    run_id: str
    entries: list[RqgmScoreRewriteV1] = Field(default_factory=list)
    next_cursor: int | None = None
    total_entries: int = 0
    degraded_reasons: list[str] = Field(default_factory=list)


class RqgmPolicyV1(BaseModel):
    """One epoch utility policy (a governed ``utility_policy``-role prompt):
    write-once body (the 5 hashed keys) + hash + adoption provenance.
    ``body`` is ``None`` when the stored bytes no longer hash to the
    registered ``prompt_hash`` (refused, surfaced as degraded — never served
    silently)."""

    prompt_id: str
    policy_hash: str
    status: RegistryStatusV1
    epoch_id_registered: str = ""
    adopted_via: str | None = None
    body: dict | None = None
    epochs_used: list[str] = Field(default_factory=list)


class RqgmPoliciesV1(BaseModel):
    """GET /api/v1/runs/{run_id}/rqgm/policies."""

    schema_version: Literal[1] = 1
    run_id: str
    current_policy_hash: str | None = None
    policies: list[RqgmPolicyV1] = Field(default_factory=list)
    degraded_reasons: list[str] = Field(default_factory=list)


# ── RQGM Wave 4b (task 08): epochs / evolution / paper-archive read models ─


class RqgmEpochTransitionCountsV1(BaseModel):
    """Status-change counts of the committed boundary transaction that
    CLOSED an epoch, counted from the real ``*_status_change`` /
    ``emergency_quarantine`` events (registrations are not status changes
    and are never counted).  ``fallbacks`` has no event-level representation
    in the transitions log; it is joined from the ``epoch_transition`` audit
    record's real ``fallbacks`` array when present and stays ``None``
    otherwise — an absent source is never displayed as zero (plan 08 §Truth
    rules)."""

    adoptions: int = 0
    sanctions: int = 0
    retirements: int = 0
    bans: int = 0
    fallbacks: int | None = None


class RqgmEpochV1(BaseModel):
    """One committed epoch from transitions replay (plan 08 §Epoch
    Timeline).

    Every epoch carries its own ``utility_policy_hash`` so a consumer can
    refuse naive cross-epoch comparison: scores under different policy
    hashes are never one continuous series (plan 08: epoch comparison only
    after compatibility is confirmed).  ``boundary_committed`` is True when
    a committed boundary transaction CLOSED this epoch (its terminal
    boundary exists in the truth log); the latest epoch of a live run is
    still open, so its ``transition_counts`` is ``None`` — a boundary that
    has not happened is never rendered as zero activity."""

    epoch_id: str
    opened_at_event: str = ""
    opened_by_transition_id: str | None = None
    utility_policy_hash: str | None = None
    boundary_committed: bool = False
    closed_by_transition_id: str | None = None
    transition_counts: RqgmEpochTransitionCountsV1 | None = None


class RqgmEpochsV1(BaseModel):
    """GET /api/v1/runs/{run_id}/rqgm/epochs — committed ``epoch_open``
    replay order (deterministic file order of the truth log)."""

    schema_version: Literal[1] = 1
    run_id: str
    epochs: list[RqgmEpochV1] = Field(default_factory=list)
    current_epoch: str | None = None
    degraded_reasons: list[str] = Field(default_factory=list)


class RqgmTransactionRefV1(BaseModel):
    """A reference to one committed transition-log entry (deep-link shape:
    ``byte_offset`` addresses the raw artifact; the full events ride
    GET .../rqgm/transitions?expand=1)."""

    kind: Literal["transaction", "standalone"]
    transition_id: str | None = None
    byte_offset: int
    first_event_id: str = ""
    last_event_id: str = ""
    event_count: int = 0
    committed_at: str | None = None


class RqgmEpochDetailV1(BaseModel):
    """GET /api/v1/runs/{run_id}/rqgm/epochs/{epoch_id}.

    Scalars come from the committed ``epoch_open`` event's ``epoch_state``
    payload (truth log, never the ``epoch_state.json`` snapshot).
    ``policy_body`` is resolved through the policies reader (registered
    ``utility_policy`` prompt whose hash matches; write-once bytes verified)
    — ``None`` with a degraded reason when unresolvable, never guessed."""

    schema_version: Literal[1] = 1
    run_id: str
    epoch: RqgmEpochV1
    epoch_seq: int | None = None
    status: str | None = None
    node_count_at_open: int | None = None
    previous_epoch_id: str | None = None
    registry_version: str | None = None
    epoch_fingerprint: str | None = None
    active_components: dict[str, str] = Field(default_factory=dict)
    active_prompt_hashes: dict[str, str] = Field(default_factory=dict)
    opening_transaction: RqgmTransactionRefV1 | None = None
    closing_transaction: RqgmTransactionRefV1 | None = None
    policy_prompt_id: str | None = None
    policy_body: dict | None = None
    governance_report_present: bool = False
    governance_report_record_id: str | None = None
    degraded_reasons: list[str] = Field(default_factory=list)


class RqgmEvolutionEntryV1(BaseModel):
    """One evolution-lineage entry (plan 08 §Evolution and Frontier Repair).

    Raw candidate vs validated candidate vs adopted policy are structurally
    separate here, never conflated:

    - the entry itself IS the raw proposal record (its own ``status`` is the
      record's candidate-vocabulary status, and the proposed artifact hash
      is normalized into ``proposed_prompt_hash`` / ``proposed_policy_hash``
      — the plan-08 naming-subtlety rule);
    - ``validation_record_count`` / ``validation_passed_count`` count the
      candidate's ``prompt_candidate_validation`` records (lifecycle stage
      executions), which is evidence of validation, not adoption;
    - ``adopted`` is ONLY ever derived by joining the candidate's proposed
      hash against the committed registry replay (a prompt of the same role
      that reached the active set), with the citing transition in
      ``adopted_via``.  It is ``None`` for ``meta`` entries: a meta-agent
      output is inert provenance, not an adoptable candidate."""

    kind: Literal["prompt", "utility_policy", "meta"]
    record_id: str
    candidate_id: str | None = None
    parent_ref: str | None = None
    proposed_prompt_hash: str | None = None
    proposed_policy_hash: str | None = None
    epoch_id: str | None = None
    role: str | None = None
    mutation_kind: str | None = None
    status: str | None = None
    validation_record_count: int = 0
    validation_passed_count: int = 0
    adopted: bool | None = None
    adopted_via: str | None = None
    adopted_prompt_id: str | None = None
    output_kind: str | None = None
    target_role: str | None = None
    source: Literal["prompt_evolution", "meta_outputs"]
    source_offset: int


class RqgmEvolutionV1(BaseModel):
    """GET /api/v1/runs/{run_id}/rqgm/evolution — ``prompt_evolution.jsonl``
    lineage (+ ``rqgm_meta_outputs.jsonl`` when present).  Presence flags
    are explicit: a missing log is ``*_present=False`` with no entries, never
    an empty-but-healthy claim."""

    schema_version: Literal[1] = 1
    run_id: str
    evolution_present: bool = False
    meta_outputs_present: bool = False
    entries: list[RqgmEvolutionEntryV1] = Field(default_factory=list)
    degraded_reasons: list[str] = Field(default_factory=list)


class RqgmPaperAnchorV1(BaseModel):
    """Anchor capability state.  ``enabled`` comes only from the frozen
    ``paper_utility_policy.anchor_enabled`` in ``paper_archive_state.json``;
    when no policy was frozen it is ``None`` (unknown), never guessed.
    With the anchor disabled the archive is reviewed best-of-N and writer
    sanctions cannot fire (plan 08 §Paper Archive)."""

    enabled: bool | None = None
    corpus_present: bool = False


class RqgmPaperSelfPreferenceV1(BaseModel):
    """Bounded scalars of ``rqgm/paper_self_preference_stat.json`` —
    summary only (per-case scores stay in the artifact).  All values are
    ``None`` when ``stat_present`` is False (absent, not zero)."""

    stat_present: bool = False
    epoch_id: str | None = None
    margin: float | None = None
    ai_mean: float | None = None
    human_mean: float | None = None
    sample_count: int | None = None


class RqgmPaperWinnerV1(BaseModel):
    """The archive's best-belief draft.  ``node_id`` is the recorded
    ``is_best_belief`` draft (a REVIEWED selection — never to be equated
    with the governance winner or the research result, plan 08 §Paper
    Archive); ``materialized`` is ``full_paper.tex`` presence."""

    node_id: str | None = None
    materialized: bool = False


class RqgmPaperArchiveV1(BaseModel):
    """GET /api/v1/runs/{run_id}/rqgm/paper-archive — bounded scalars only.

    ``paper_mode`` reports the persisted mode when
    ``paper_archive_state.json`` exists; absence of that file MEANS mode
    ``linear`` by the source contract (plan 08 §Source artifacts), which is
    why ``state_present=False`` rides along — the derivation is transparent,
    not fabricated.  ``draft_count`` is ``None`` (not 0) when the draft
    archive file is absent."""

    schema_version: Literal[1] = 1
    run_id: str
    state_present: bool = False
    paper_mode: str | None = None
    mode_source: str | None = None
    rqgm_paper_enabled: bool | None = None
    paper_epoch_fingerprint: str | None = None
    archive_present: bool = False
    epochs: list[str] = Field(default_factory=list)
    draft_count: int | None = None
    anchor: RqgmPaperAnchorV1 = Field(default_factory=RqgmPaperAnchorV1)
    self_preference: RqgmPaperSelfPreferenceV1 = Field(
        default_factory=RqgmPaperSelfPreferenceV1
    )
    winner: RqgmPaperWinnerV1 = Field(default_factory=RqgmPaperWinnerV1)
    degraded_reasons: list[str] = Field(default_factory=list)


# ── idea read model (gui_refresh Wave 4c) ──────────────────────────────────


class RunIdeaV1(BaseModel):
    """GET /api/v1/runs/{run_id}/idea — pure read of ``{ckpt}/idea.json``.

    Mirrors exactly what the legacy IdeaPage consumes from the ``/state``
    payload today (``state_service`` keys ``ideas`` / ``gap_analysis`` /
    ``primary_metric`` / ``metric_rationale``), but with honest absence
    semantics: ``present`` is False when ``idea.json`` does not exist or is
    unreadable, and every content field then stays at its empty default —
    an absent file is never fabricated into empty-but-healthy strings
    (the legacy path serves ``""``; here absence is ``None``).  ``ideas``
    entries are the on-disk VirSci idea dicts passed through verbatim
    (title / description / novelty_score / feasibility_score /
    overall_score / experiment_plan ... — loose schema by design)."""

    schema_version: Literal[1] = 1
    run_id: str
    present: bool = False
    ideas: list[dict] = Field(default_factory=list)
    gap_analysis: str | None = None
    primary_metric: str | None = None
    metric_rationale: str | None = None
    degraded_reasons: list[str] = Field(default_factory=list)


# ── results / EAR read models (gui_refresh task 07 Wave 4d) ────────────────
#
# Server-only read DTOs over committed result artifacts (readers in
# ari/viz/v1/results.py).  Truth rules: every block carries explicit presence
# flags derived from artifact existence alone — an absent artifact is never
# fabricated into empty-but-healthy scalars; parse failures degrade (200 +
# ``degraded_reasons``), never 500.  Bounded scalars only: no file contents,
# no markdown bodies, no paper text (the legacy #/results page remains the
# full editor/PDF workspace).


class ResultPaperV1(BaseModel):
    """Paper artifact presence — never content.  Both flags probe the two
    historical locations (checkpoint root and ``paper/``) independently."""

    pdf_present: bool = False
    tex_present: bool = False


class ReviewDimensionV1(BaseModel):
    """One rubric score dimension from ``review_report.json``
    ``score_dimensions`` (name + value + scale bounds; malformed entries are
    dropped with a degraded reason, never coerced)."""

    name: str
    value: float | None = None
    scale_min: float | None = None
    scale_max: float | None = None


class ResultReviewV1(BaseModel):
    """Bounded review scalars.  ``report_present`` is ``review_report.json``
    existence; scores are served only when the file parses (an unreadable
    report keeps ``report_present=True`` with a degraded reason and ``None``
    scores — presence and readability are separate facts)."""

    report_present: bool = False
    overall_score: float | None = None
    abstract_score: float | None = None
    body_score: float | None = None
    decision: str | None = None
    confidence: float | None = None
    rubric_id: str | None = None
    dimensions: list[ReviewDimensionV1] = Field(default_factory=list)


class ResultOrsV1(BaseModel):
    """ORS reproducibility-chain summary (plan 07: rubric → replicator →
    phase1 reproduce → judge grade, the ``OrsChainSection`` lineage).

    Stage flags are per-artifact presence (``ors_rubric.meta.json`` /
    ``ors_rubric.json``, ``ors_replicator.json``, ``ors_seed.json``,
    ``ors_phase1.json``, ``ors_grade.json``); ``chain_present`` is their OR.
    ``verdict``/``summary``/scores reuse the ``ari.viz.ear``
    ``_synth_repro_report_from_ors`` synthesis READ-ONLY (the same verdict
    the legacy Results page shows) — ``None`` when the synthesis has no
    usable grade, never guessed."""

    chain_present: bool = False
    rubric_present: bool = False
    replicator_present: bool = False
    seed_present: bool = False
    phase1_present: bool = False
    grade_present: bool = False
    verdict: str | None = None
    summary: str | None = None
    ors_score: float | None = None
    raw_score: float | None = None
    passed_leaves: int | None = None
    total_leaves: int | None = None
    judge_model: str | None = None


class ResultEarV1(BaseModel):
    """EAR / publication lineage flags (plan 07 §Evidence, Results, and
    PaperBench: curate → preview → publish → promote as a traceability
    chain).  ``present`` = ``ear/`` directory, ``curated`` =
    ``ear_published/manifest.lock`` presence, ``published`` =
    ``publish_record.json`` presence.  ``visibility`` comes from the publish
    record when published, else from the curated manifest's declared
    ``publish.visibility`` (``visibility_source`` says which); ``promoted_at``
    / ``dry_run`` are publish-record scalars (``None`` until published)."""

    present: bool = False
    curated: bool = False
    published: bool = False
    visibility: str | None = None
    visibility_source: Literal["publish_record", "manifest_lock"] | None = None
    dry_run: bool | None = None
    promoted_at: str | None = None


class RunResultsV1(BaseModel):
    """GET /api/v1/runs/{run_id}/results — the bounded result read model
    (gui_refresh task 07 Wave 4d).  Composition only; every block keeps its
    own presence flags so a consumer can render honest per-section absence."""

    schema_version: Literal[1] = 1
    run_id: str
    paper: ResultPaperV1 = Field(default_factory=ResultPaperV1)
    review: ResultReviewV1 = Field(default_factory=ResultReviewV1)
    ors: ResultOrsV1 = Field(default_factory=ResultOrsV1)
    ear: ResultEarV1 = Field(default_factory=ResultEarV1)
    degraded_reasons: list[str] = Field(default_factory=list)


class EarFileV1(BaseModel):
    """One ``ear/`` tree entry — path/kind/size metadata only, never
    content.  ``size`` is ``None`` for directories or when ``stat`` fails."""

    path: str
    kind: Literal["file", "dir"]
    size: int | None = None


class EarManifestV1(BaseModel):
    """Curated-bundle digest scalars from ``ear_published/manifest.lock``
    (bundle sha256, counts, declared visibility) — the bundle files
    themselves are never inlined."""

    manifest_present: bool = False
    bundle_sha256: str | None = None
    file_count: int | None = None
    excluded_count: int | None = None
    visibility: str | None = None
    created_at: str | None = None


class EarPublishRecordV1(BaseModel):
    """Publish/promote scalars from ``{ckpt}/publish_record.json`` (written
    by ``ari.publish.publish``; ``promoted_at`` appears after promote)."""

    record_present: bool = False
    backend: str | None = None
    ref: str | None = None
    bundle_sha256: str | None = None
    visibility: str | None = None
    dry_run: bool | None = None
    timestamp: str | None = None
    promoted_at: str | None = None


class RunEarV1(BaseModel):
    """GET /api/v1/runs/{run_id}/ear — EAR listing + lineage scalars
    (gui_refresh task 07 Wave 4d).

    ``files`` is the deterministic sorted ``ear/`` tree METADATA (bounded:
    at most the first ``results._MAX_EAR_FILES`` entries, ``truncated=True``
    beyond that; ``file_count`` still counts every file).  No file content
    ever rides this endpoint — README/RESULTS bodies stay on the legacy
    surface."""

    schema_version: Literal[1] = 1
    run_id: str
    present: bool = False
    publish_yaml_present: bool = False
    files: list[EarFileV1] = Field(default_factory=list)
    file_count: int = 0
    truncated: bool = False
    curated: EarManifestV1 = Field(default_factory=EarManifestV1)
    published: EarPublishRecordV1 = Field(default_factory=EarPublishRecordV1)
    degraded_reasons: list[str] = Field(default_factory=list)


# ── run log read model (gui_refresh task 07 tail — cursor log explorer) ────
#
# Plan 07 §Artifacts, logs, and diagnostics: log reads use cursor/tail
# semantics — a 5 MB whole-file read is never the primary UX.  Reader in
# ari/viz/v1/logs.py; the cursor is a RAW byte offset into the append-only
# plain-text ``{ckpt}/ari.log`` so pagination is stable under any filter.


class LogEntryV1(BaseModel):
    """One committed ``ari.log`` line: the raw byte offset where the line
    starts (a valid ``cursor`` value) plus its decoded text (trailing
    newline stripped, bytes decoded UTF-8 with replacement)."""

    offset: int
    line: str


class RunLogsV1(BaseModel):
    """GET /api/v1/runs/{run_id}/logs — one bounded cursor page over the
    append-only ``{ckpt}/ari.log``.

    Honest absence: a run whose log does not exist yet answers
    ``present=false`` (200, never a 404 — only an unknown run 404s).
    ``next_cursor`` is ALWAYS the byte offset where the next scan resumes
    (also at ``eof``, so a tail-follow client polls the same value until
    new committed lines appear).  ``eof=true`` means no further committed
    line was known at scan time; a trailing partial line (no ``\\n``) is
    never emitted — ``next_cursor`` parks at its first byte until the line
    completes (plan 04 committed-only reads).  Each request scans at most
    ``logs.SCAN_WINDOW_BYTES``; when the window ends before ``limit``
    matches were found the page returns early with ``eof=false`` and the
    advanced cursor — the client continues, no request scans unboundedly."""

    schema_version: Literal[1] = 1
    run_id: str
    present: bool = False
    entries: list[LogEntryV1] = Field(default_factory=list)
    next_cursor: int = 0
    eof: bool = True
    file_size: int = 0
    degraded_reasons: list[str] = Field(default_factory=list)


# ── confirmation challenges (gui_refresh task 09 Wave 5a, MN-6) ────────────


class ChallengeRequestV1(BaseModel):
    """POST /api/v1/challenges body — which dangerous operation the client
    is about to attempt (RR-P0-6/RR-P0-9): ``action`` names the operation,
    ``target`` what it destroys (checkpoint path for ``delete-checkpoint``;
    the literal ``"*"`` for ``stop-all`` / ``gpu-monitor-stop``)."""

    action: Literal["delete-checkpoint", "stop-all", "gpu-monitor-stop"]
    target: str


class ChallengeV1(BaseModel):
    """One server-issued, single-use confirmation challenge (MN-6).

    The echoed ``action``/``target`` are the UI's impact preview (plan 09
    §Dangerous operations); ``expires_at`` is display-only wall clock —
    expiry is enforced server-side on a monotonic deadline
    (``ttl_seconds`` after issuance)."""

    schema_version: Literal[1] = 1
    challenge_id: str
    action: Literal["delete-checkpoint", "stop-all", "gpu-monitor-stop"]
    target: str
    expires_at: str
    ttl_seconds: int


# ── operational diagnostics (gui_refresh task 09 Wave 5b, MN-9) ────────────


class DiagnosticsSseV1(BaseModel):
    """SSE event-bus scalars (``ari.viz.v1.events.bus_stats``): live
    ``/api/v1/events/stream`` subscriber count, ring-buffer fill, and the
    last published event id (0 = nothing published this process)."""

    subscribers: int = 0
    buffer_len: int = 0
    last_event_id: int = 0


class DiagnosticsWatcherV1(BaseModel):
    """Filesystem-watcher scalars: thread liveness plus seconds since the
    last completed scan tick (``None`` = the watcher never ran)."""

    alive: bool = False
    last_scan_age_s: float | None = None


class DiagnosticsProcessV1(BaseModel):
    """Process-supervision scalars — a count only, never the checkpoint
    path keys of the tracking table (plan 09: no path leakage)."""

    tracked_runs: int = 0


class DiagnosticsV1(BaseModel):
    """GET /api/v1/diagnostics envelope (plan 09 §Operational visibility)
    — bounded scalars only: no secrets, no filesystem paths, nothing
    beyond counts/ages/versions.  ``cache`` is the literal ``false`` —
    no cache subsystem exists yet, stated explicitly rather than omitted;
    ``openapi_version`` mirrors the served OpenAPI ``info.version``."""

    schema_version: Literal[1] = 1
    sse: DiagnosticsSseV1 = Field(default_factory=DiagnosticsSseV1)
    watcher: DiagnosticsWatcherV1 = Field(default_factory=DiagnosticsWatcherV1)
    process: DiagnosticsProcessV1 = Field(default_factory=DiagnosticsProcessV1)
    cache: Literal[False] = False
    openapi_version: str


# ── error envelope (wire shape documented for OpenAPI; built by errors.py) ─


class ErrorBodyV1(BaseModel):
    code: Literal[
        "not_found",
        "invalid_request",
        "internal",
        "revision_conflict",
        "already_exists",
    ]
    message: str
    details: Any = None
    request_id: str
    retryable: bool = False


class ErrorEnvelopeV1(BaseModel):
    error: ErrorBodyV1
