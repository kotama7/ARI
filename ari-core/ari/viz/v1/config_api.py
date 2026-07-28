"""Config CRUD handlers for ``/api/v1`` (gui_refresh task 05 Wave 3b).

The write-side counterpart of :mod:`ari.viz.v1.queries` for the GUI-only
configuration documents (plan 05 §Configuration API / §Configuration scopes):

- ``GET/PATCH /api/v1/projects/{project_id}/config`` — the single default
  project's config document (ADR-08: only ``default`` exists);
- ``GET/POST /api/v1/run-templates`` + ``GET/PATCH/DELETE .../{template_id}``;
- ``POST /api/v1/run-drafts`` + ``GET/PATCH .../{draft_id}``.

Contract summary:

- persistence is :class:`ari.viz.v1.store.GuiStore` (ADR-12 — atomic writes,
  per-document revisions, ``{workspace_root}/gui_store/``, never read by the
  CLI / simple_bfts path);
- every mutation with a precondition maps the store revision to HTTP
  optimistic concurrency: PATCH/DELETE require ``If-Match: "<revision>"``
  (missing → 400 ``invalid_request``; stale → 409 ``revision_conflict``,
  raised as :class:`ari.viz.v1.store.RevisionConflict` and translated by the
  router); POST run-templates is create-only (existing → 409
  ``already_exists``);
- PATCH bodies are ``{"values": {"dotted.path": value}}`` partial updates
  validated by the pure ``ari.config.field_registry.validate_patch`` helper
  (unknown path / wrong type / enum violation / secret_reference / read_only
  → 400 with the offending paths in ``details.errors``); ``new_run_only``
  fields are allowed in templates/drafts but rejected in the project config
  when their scope is not ``project``;
- the MERGED document values then pass ``validate_mode_interlocks`` (ADR-09):
  the two mode intents are pairs, so a template/draft that would launch
  ``ari.mode``/``paper.mode`` without its agreeing interlock twin is 400
  ``mode_interlock_mismatch``.  Only the four mode leaves are writable this
  way — every other ``rqgm.*`` tuning leaf stays read-only in the GUI;
- ``updated_at`` is the document file's mtime as UTC ISO 8601 — never
  ``now()`` (P2: repeated GETs are byte-stable).

Handlers return plain payload dicts (optionally carrying ``"_status"``) or
typed error envelopes from :func:`ari.viz.v1.errors.error_response`; the
router injects ``request_id`` and owns the :class:`RevisionConflict` → 409
translation.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from .dto import (
    DraftValidationV1,
    ProjectConfigV1,
    ResolvedNewRunConfigV1,
    RunDraftV1,
    RunTemplateDeletedV1,
    RunTemplateListV1,
    RunTemplateSummaryV1,
    RunTemplateV1,
)
from .errors import error_response
from .queries import DEFAULT_PROJECT_ID
from .store import (
    KIND_PROJECT_CONFIG,
    KIND_RUN_DRAFT,
    KIND_RUN_TEMPLATE,
    GuiStore,
    RevisionConflict,
)

# API-level ID grammars.  ``template_id`` is a strict lowercase profile of
# the store grammar (stable across case-insensitive filesystems);
# ``draft_id`` is always server-generated, so anything else is a 404.
TEMPLATE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
DRAFT_ID_RE = re.compile(r"^draft-[0-9a-f]{12}$")

# The bundled execution profiles the CLI --profile flag accepts (plan 05
# §Resolution model; DraftResolveRequestV1 mirrors this closed set).
PROFILES = ("laptop", "hpc", "cloud")


def _store() -> GuiStore:
    """A fresh store per request: honors the canonical workspace-root policy
    (``ARI_CHECKPOINT_DIR`` wins) at call time — same deferral pattern as
    ``queries._search_bases``."""
    return GuiStore.from_env()


def _mtime_iso(store: GuiStore, kind: str, doc_id: str | None) -> str:
    """Document ``updated_at``: the store file's mtime as UTC ISO 8601.
    Layout knowledge stays single-source via the store's own path mapping
    (deliberate same-package use of ``_path_for``)."""
    ts = int(store._path_for(kind, doc_id).stat().st_mtime)
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


# ── shared request plumbing ────────────────────────────────────────────────


def _bad_request(message: str, details=None) -> dict:
    return error_response(
        "invalid_request", message, details=details, request_id="", status=400
    )


def _not_found(message: str) -> dict:
    return error_response("not_found", message, request_id="", status=404)


def _require_if_match(if_match: int | None) -> dict | None:
    if if_match is None:
        return _bad_request(
            'mutations require the If-Match: "<revision>" header '
            '(use the current document revision; "0" to create)'
        )
    return None


def _parse_values(body: dict, *, extra_keys: tuple[str, ...] = ()) -> tuple[
    dict | None, dict | None
]:
    """Extract + shape-check the ``values`` map from a request body.
    Returns ``(values, None)`` or ``(None, error_envelope)``."""
    unknown = sorted(set(body) - {"values", *extra_keys})
    if unknown:
        return None, _bad_request(
            f"unknown request body keys: {unknown}",
            details={"unknown_keys": unknown},
        )
    values = body.get("values", {})
    if not isinstance(values, dict):
        return None, _bad_request('"values" must be a JSON object')
    bad = sorted(str(k) for k in values if not isinstance(k, str))
    if bad:
        return None, _bad_request(
            "values keys must be dotted config paths (strings)",
            details={"invalid_keys": bad},
        )
    return values, None


def _validate_values(values: dict, target: str) -> dict | None:
    """Registry validation → 400 envelope with per-path errors, or None.
    Local import keeps ``ari.config`` inert until a mutation is dispatched
    (viz → ari.config is the allowed boundary direction)."""
    from ari.config.field_registry import validate_patch

    errors = validate_patch(values, target=target)
    if errors:
        return _bad_request(
            f"invalid config patch ({len(errors)} path(s) rejected): "
            + errors[0]["message"],
            details={"errors": errors},
        )
    return None


def _validate_mode_pairs(effective: dict) -> dict | None:
    """ADR-09 paired-intent pass → 400 ``mode_interlock_mismatch``, or None.

    *effective* is the document's values AFTER the merge (the map a launch
    would resolve) — never the raw patch, so a two-step edit that ENDS
    consistent is accepted while a document that would launch an intent the
    runtime cannot honor is not.  A mode leaf is only meaningful together
    with its interlock twin, and that cross-path rule is exactly what
    ``validate_patch`` (one path at a time) cannot express."""
    from ari.config.field_registry import validate_mode_interlocks

    errors = validate_mode_interlocks(effective)
    if errors:
        return _bad_request(
            f"invalid config patch ({len(errors)} path(s) rejected): "
            + errors[0]["message"],
            details={"errors": errors},
        )
    return None


# ── project config (singleton, ADR-08 default project) ─────────────────────


def get_project_config(project_id: str) -> dict:
    """GET /api/v1/projects/{project_id}/config — a missing document reads
    as revision 0 / empty values (its PATCH twin creates with If-Match 0)."""
    if project_id != DEFAULT_PROJECT_ID:
        return _not_found(f"unknown project: {project_id}")
    loaded = _store().read(KIND_PROJECT_CONFIG)
    if loaded is None:
        return ProjectConfigV1(revision=0).model_dump()
    doc, rev = loaded
    values = (doc.get("body") or {}).get("values") or {}
    return ProjectConfigV1(
        revision=rev, values=values, updated_paths_count=len(values)
    ).model_dump()


def patch_project_config(project_id: str, body: dict, if_match: int | None) -> dict:
    """PATCH /api/v1/projects/{project_id}/config — merge-validate-write."""
    if project_id != DEFAULT_PROJECT_ID:
        return _not_found(f"unknown project: {project_id}")
    err = _require_if_match(if_match)
    if err is not None:
        return err
    values, err = _parse_values(body)
    if err is not None:
        return err
    if not values:
        return _bad_request('"values" must contain at least one dotted path')
    err = _validate_values(values, "project_config")
    if err is not None:
        return err
    store = _store()
    loaded = store.read(KIND_PROJECT_CONFIG)
    current = (loaded[0].get("body") or {}).get("values") or {} if loaded else {}
    merged = {**current, **values}
    # A stale If-Match raises RevisionConflict here (router → 409); the
    # previous document stays byte-intact (atomic replace never ran).
    new_rev = store.write(
        KIND_PROJECT_CONFIG, {"values": merged}, expected_revision=if_match
    )
    return ProjectConfigV1(
        revision=new_rev, values=merged, updated_paths_count=len(merged)
    ).model_dump()


# ── run templates ──────────────────────────────────────────────────────────


def _template_payload(
    store: GuiStore, template_id: str, doc: dict, rev: int
) -> dict:
    body = doc.get("body") or {}
    return RunTemplateV1(
        template_id=template_id,
        name=body.get("name") or template_id,
        revision=rev,
        values=body.get("values") or {},
        updated_at=_mtime_iso(store, KIND_RUN_TEMPLATE, template_id),
    ).model_dump()


def list_run_templates() -> dict:
    """GET /api/v1/run-templates — codepoint-ordered listing (store order)."""
    store = _store()
    rows = []
    for template_id, doc in store.list(KIND_RUN_TEMPLATE):
        body = doc.get("body") or {}
        rows.append(
            RunTemplateSummaryV1(
                template_id=template_id,
                name=body.get("name") or template_id,
                revision=doc["revision"],
                updated_at=_mtime_iso(store, KIND_RUN_TEMPLATE, template_id),
            )
        )
    return RunTemplateListV1(templates=rows).model_dump()


def create_run_template(body: dict) -> dict:
    """POST /api/v1/run-templates — create-only (409 already_exists)."""
    unknown = sorted(set(body) - {"template_id", "name", "values"})
    if unknown:
        return _bad_request(
            f"unknown request body keys: {unknown}",
            details={"unknown_keys": unknown},
        )
    template_id = body.get("template_id")
    if not isinstance(template_id, str) or not TEMPLATE_ID_RE.fullmatch(
        template_id
    ):
        return _bad_request(
            "template_id must match ^[a-z0-9][a-z0-9_-]{0,63}$",
            details={"template_id": template_id},
        )
    name = body.get("name")
    if not isinstance(name, str) or not name.strip():
        return _bad_request("name must be a non-empty string")
    values, err = _parse_values(body, extra_keys=("template_id", "name"))
    if err is not None:
        return err
    err = _validate_values(values, "run_template")
    if err is not None:
        return err
    err = _validate_mode_pairs(values)  # create: the patch IS the document
    if err is not None:
        return err
    store = _store()
    try:
        rev = store.write(
            KIND_RUN_TEMPLATE,
            {"name": name, "values": values},
            doc_id=template_id,
            expected_revision=0,  # create-only
        )
    except RevisionConflict:
        return error_response(
            "already_exists",
            f"run template already exists: {template_id}",
            details={"template_id": template_id},
            request_id="",
            status=409,
        )
    return {
        **RunTemplateV1(
            template_id=template_id,
            name=name,
            revision=rev,
            values=values,
            updated_at=_mtime_iso(store, KIND_RUN_TEMPLATE, template_id),
        ).model_dump(),
        "_status": 201,
    }


def get_run_template(template_id: str) -> dict:
    """GET /api/v1/run-templates/{template_id}."""
    if not TEMPLATE_ID_RE.fullmatch(template_id):
        return _not_found(f"unknown run template: {template_id}")
    store = _store()
    loaded = store.read(KIND_RUN_TEMPLATE, template_id)
    if loaded is None:
        return _not_found(f"unknown run template: {template_id}")
    return _template_payload(store, template_id, *loaded)


def patch_run_template(
    template_id: str, body: dict, if_match: int | None
) -> dict:
    """PATCH /api/v1/run-templates/{template_id} — values merge only (the
    name and identity are fixed at create in v1)."""
    if not TEMPLATE_ID_RE.fullmatch(template_id):
        return _not_found(f"unknown run template: {template_id}")
    err = _require_if_match(if_match)
    if err is not None:
        return err
    values, err = _parse_values(body)
    if err is not None:
        return err
    if not values:
        return _bad_request('"values" must contain at least one dotted path')
    err = _validate_values(values, "run_template")
    if err is not None:
        return err
    store = _store()
    loaded = store.read(KIND_RUN_TEMPLATE, template_id)
    if loaded is None:
        return _not_found(f"unknown run template: {template_id}")
    doc, _rev = loaded
    stored = doc.get("body") or {}
    merged = {**(stored.get("values") or {}), **values}
    err = _validate_mode_pairs(merged)
    if err is not None:
        return err
    new_rev = store.write(
        KIND_RUN_TEMPLATE,
        {"name": stored.get("name") or template_id, "values": merged},
        doc_id=template_id,
        expected_revision=if_match,
    )
    return RunTemplateV1(
        template_id=template_id,
        name=stored.get("name") or template_id,
        revision=new_rev,
        values=merged,
        updated_at=_mtime_iso(store, KIND_RUN_TEMPLATE, template_id),
    ).model_dump()


def delete_run_template(template_id: str, if_match: int | None) -> dict:
    """DELETE /api/v1/run-templates/{template_id} — If-Match required."""
    if not TEMPLATE_ID_RE.fullmatch(template_id):
        return _not_found(f"unknown run template: {template_id}")
    err = _require_if_match(if_match)
    if err is not None:
        return err
    store = _store()
    if store.read(KIND_RUN_TEMPLATE, template_id) is None:
        return _not_found(f"unknown run template: {template_id}")
    store.delete(KIND_RUN_TEMPLATE, template_id, expected_revision=if_match)
    return RunTemplateDeletedV1(template_id=template_id).model_dump()


# ── run drafts ─────────────────────────────────────────────────────────────


def _draft_payload(store: GuiStore, draft_id: str, doc: dict, rev: int) -> dict:
    body = doc.get("body") or {}
    goal = body.get("goal")
    return RunDraftV1(
        draft_id=draft_id,
        template_id=body.get("template_id"),
        revision=rev,
        values=body.get("values") or {},
        goal=goal if isinstance(goal, str) else None,
        updated_at=_mtime_iso(store, KIND_RUN_DRAFT, draft_id),
    ).model_dump()


def create_run_draft(body: dict) -> dict:
    """POST /api/v1/run-drafts — server-generated ``draft-<12 hex>`` id.

    Wave 4e (additive): an optional ``goal`` string may accompany the draft —
    the free-text research goal ``POST /api/v1/runs`` later materializes as
    ``{ckpt}/experiment.md``.  It is a document field (not a dotted config
    path), so it bypasses the registry and never appears in ``values``.
    """
    unknown = sorted(set(body) - {"template_id", "values", "goal"})
    if unknown:
        return _bad_request(
            f"unknown request body keys: {unknown}",
            details={"unknown_keys": unknown},
        )
    goal = body.get("goal")
    if goal is not None and not isinstance(goal, str):
        return _bad_request('"goal" must be a string when given')
    values, err = _parse_values(body, extra_keys=("template_id", "goal"))
    if err is not None:
        return err
    err = _validate_values(values, "run_draft")
    if err is not None:
        return err
    err = _validate_mode_pairs(values)  # create: the patch IS the document
    if err is not None:
        return err
    store = _store()
    template_id = body.get("template_id")
    if template_id is not None:
        if not isinstance(template_id, str) or not TEMPLATE_ID_RE.fullmatch(
            template_id
        ):
            return _bad_request(
                "template_id must match ^[a-z0-9][a-z0-9_-]{0,63}$",
                details={"template_id": template_id},
            )
        if store.read(KIND_RUN_TEMPLATE, template_id) is None:
            return _bad_request(
                f"unknown template_id: {template_id}",
                details={"template_id": template_id},
            )
    draft_id = "draft-" + uuid.uuid4().hex[:12]
    rev = store.write(
        KIND_RUN_DRAFT,
        {"template_id": template_id, "values": values, "goal": goal},
        doc_id=draft_id,
        expected_revision=0,  # uuid4 collision would 409; practically never
    )
    return {
        **RunDraftV1(
            draft_id=draft_id,
            template_id=template_id,
            revision=rev,
            values=values,
            goal=goal,
            updated_at=_mtime_iso(store, KIND_RUN_DRAFT, draft_id),
        ).model_dump(),
        "_status": 201,
    }


def get_run_draft(draft_id: str) -> dict:
    """GET /api/v1/run-drafts/{draft_id}."""
    if not DRAFT_ID_RE.fullmatch(draft_id):
        return _not_found(f"unknown run draft: {draft_id}")
    store = _store()
    loaded = store.read(KIND_RUN_DRAFT, draft_id)
    if loaded is None:
        return _not_found(f"unknown run draft: {draft_id}")
    return _draft_payload(store, draft_id, *loaded)


def patch_run_draft(draft_id: str, body: dict, if_match: int | None) -> dict:
    """PATCH /api/v1/run-drafts/{draft_id} — values merge; the template link
    is immutable after create."""
    if not DRAFT_ID_RE.fullmatch(draft_id):
        return _not_found(f"unknown run draft: {draft_id}")
    err = _require_if_match(if_match)
    if err is not None:
        return err
    values, err = _parse_values(body)
    if err is not None:
        return err
    if not values:
        return _bad_request('"values" must contain at least one dotted path')
    err = _validate_values(values, "run_draft")
    if err is not None:
        return err
    store = _store()
    loaded = store.read(KIND_RUN_DRAFT, draft_id)
    if loaded is None:
        return _not_found(f"unknown run draft: {draft_id}")
    doc, _rev = loaded
    stored = doc.get("body") or {}
    merged = {**(stored.get("values") or {}), **values}
    err = _validate_mode_pairs(merged)
    if err is not None:
        return err
    goal = stored.get("goal")
    goal = goal if isinstance(goal, str) else None
    new_rev = store.write(
        KIND_RUN_DRAFT,
        # ``goal`` is preserved verbatim: PATCH is a values-merge only
        # (the goal is set at create in this wave).
        {"template_id": stored.get("template_id"), "values": merged,
         "goal": goal},
        doc_id=draft_id,
        expected_revision=if_match,
    )
    return RunDraftV1(
        draft_id=draft_id,
        template_id=stored.get("template_id"),
        revision=new_rev,
        values=merged,
        goal=goal,
        updated_at=_mtime_iso(store, KIND_RUN_DRAFT, draft_id),
    ).model_dump()


# ── new-run preview: resolve-config + validate (task 05 Wave 3b) ───────────


def _resolve_draft_manifest(
    draft_id: str, body: dict
) -> tuple[dict | None, dict | None, dict | None, dict | None]:
    """Shared preview pipeline: load project config + draft (+ its template)
    from the store, run ``resolve_new_run_config``, and fill ``run_id``/
    ``resolved_at`` (store-document mtimes — never ``now()``).

    Returns ``(manifest, draft_values, run_scope_values, None)`` on success
    or ``(None, None, None, error_envelope)``.  ``run_scope_values`` is the
    template-then-draft merge — the run-scoped layers a launch would
    resolve, and the map the ADR-09 paired-intent check runs on (the
    project layer is deliberately excluded: mode paths are rejected there
    ``not_project_scope`` and never reach the effective values)."""
    if not DRAFT_ID_RE.fullmatch(draft_id):
        return None, None, None, _not_found(f"unknown run draft: {draft_id}")
    unknown = sorted(set(body) - {"profile"})
    if unknown:
        return None, None, None, _bad_request(
            f"unknown request body keys: {unknown}",
            details={"unknown_keys": unknown},
        )
    profile = body.get("profile")
    if profile is not None and profile not in PROFILES:
        return None, None, None, _bad_request(
            f"profile must be one of {PROFILES} or null",
            details={"profile": profile},
        )
    store = _store()
    loaded = store.read(KIND_RUN_DRAFT, draft_id)
    if loaded is None:
        return None, None, None, _not_found(f"unknown run draft: {draft_id}")
    draft_body = loaded[0].get("body") or {}
    draft_values = draft_body.get("values") or {}
    mtime_paths = [store._path_for(KIND_RUN_DRAFT, draft_id)]

    template_values = None
    missing_template = None
    template_id = draft_body.get("template_id")
    if template_id:
        t = store.read(KIND_RUN_TEMPLATE, template_id)
        if t is None:
            missing_template = template_id
        else:
            template_values = (t[0].get("body") or {}).get("values") or {}
            mtime_paths.append(store._path_for(KIND_RUN_TEMPLATE, template_id))

    project_values = None
    p = store.read(KIND_PROJECT_CONFIG)
    if p is not None:
        project_values = (p[0].get("body") or {}).get("values") or {}
        mtime_paths.append(store._path_for(KIND_PROJECT_CONFIG, None))

    # Local import keeps ari.config inert until dispatched (viz -> ari.config
    # is the allowed boundary direction).  env defaults to the server process
    # environment — exactly what a launch from this server would inherit.
    from ari.config.resolver import resolve_new_run_config

    manifest = resolve_new_run_config(
        project_values=project_values,
        template_values=template_values,
        draft_values=draft_values,
        profile=profile,
    )
    if missing_template:
        manifest["warnings"].append(
            f"linked run template {missing_template!r} no longer exists — "
            "template layer skipped"
        )
    manifest["run_id"] = draft_id
    ts = max(int(path.stat().st_mtime) for path in mtime_paths)
    manifest["resolved_at"] = datetime.fromtimestamp(
        ts, tz=timezone.utc
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    run_scope_values = {**(template_values or {}), **draft_values}
    return manifest, draft_values, run_scope_values, None


def resolve_run_draft_config(draft_id: str, body: dict) -> dict:
    """POST /api/v1/run-drafts/{draft_id}/resolve-config — the plan-05
    new-run chain previewed for one draft; returns the resolved manifest."""
    manifest, _dv, _rsv, err = _resolve_draft_manifest(draft_id, body)
    if err is not None:
        return err
    return ResolvedNewRunConfigV1(**manifest).model_dump()


def _draft_validation_errors(
    manifest: dict, draft_values: dict, run_scope_values: dict | None = None
) -> list[dict]:
    """The draft-attributable validation errors distilled from one resolved
    manifest (shared by ``validate_run_draft`` and the Wave 4e launch path —
    ``POST /api/v1/runs`` rejects with exactly these errors, plan 06 §Launch
    protocol validation-first):

    - every ``validate_patch`` rejection of the draft's own values;
    - draft-sourced ``invalid_value`` rejections from ARIConfig validation;
    - an ``interlock_mismatch`` per intent pair whose REQUESTED (pre-
      fallback) mode disagrees with its interlock twin.

    ``run_scope_values`` (launch only — the template+draft merge) adds the
    ADR-09 paired-intent pass: a pair reported ``mode_interlock_mismatch``
    there suppresses the resolver-derived ``interlock_mismatch`` for the
    same pair, so one defect is reported once, by the stricter check that
    names the consistent alternatives.  Omitted (``/validate``), the
    behaviour is exactly as before.

    Returned sorted by ``(path, reason)`` (deterministic, P2)."""
    from ari.config.field_registry import (validate_mode_interlocks,
                                           validate_patch)
    from ari.config.resolver import INTERLOCK_PAIRS

    errors = validate_patch(draft_values, target="run_draft")
    paired_errors = (
        validate_mode_interlocks(run_scope_values)
        if run_scope_values is not None
        else []
    )
    paired_paths = {e["path"] for e in paired_errors}
    errors.extend(paired_errors)
    provenance = manifest["provenance"]
    for path in sorted(provenance):
        ro = provenance[path].get("rejected_override")
        if (
            ro
            and ro["source"] == "draft"
            and ro["reason"] == "invalid_value"
            and not any(e["path"] == path for e in errors)
        ):
            errors.append(
                {
                    "path": path,
                    "reason": "invalid_value",
                    "message": (
                        f"{path} was rejected by config validation; the "
                        "effective value reverted to the previous layer"
                    ),
                }
            )

    def _leaf(path: str):
        node = manifest["values"]
        for part in path.split("."):
            node = node[part]
        return node

    for mode_path, enable_path, active, _fallback in INTERLOCK_PAIRS:
        if mode_path in paired_paths:
            continue  # already reported as mode_interlock_mismatch
        ro = (provenance.get(mode_path) or {}).get("rejected_override")
        requested = (
            ro["value"]
            if ro and ro["reason"] == "interlock_mismatch"
            else _leaf(mode_path)
        )
        enabled = bool(_leaf(enable_path))
        if (requested == active) != enabled:
            errors.append(
                {
                    "path": mode_path,
                    "reason": "interlock_mismatch",
                    "message": (
                        f"{mode_path}={requested!r} and {enable_path}="
                        f"{enabled} must agree — edit the pair as one "
                        "intent (plan 05 §Interlocks; the runtime would "
                        "fall back with a warning)"
                    ),
                }
            )
    errors.sort(key=lambda e: (e["path"], e["reason"]))
    return errors


def validate_run_draft(draft_id: str, body: dict) -> dict:
    """POST /api/v1/run-drafts/{draft_id}/validate — ``{valid, errors,
    warnings}`` distilled from the same resolution run as resolve-config.

    Errors (strict — plan 05 §Interlocks: draft validation treats an
    inconsistent intent pair as an error even though the runtime only warns)
    are :func:`_draft_validation_errors`; other layers' rejections surface as
    warnings only (they are not the draft's fault) — ``warnings`` is the full
    manifest warning list."""
    manifest, draft_values, _rsv, err = _resolve_draft_manifest(draft_id, body)
    if err is not None:
        return err
    errors = _draft_validation_errors(manifest, draft_values)
    return DraftValidationV1(
        draft_id=draft_id,
        valid=not errors,
        errors=errors,
        warnings=manifest["warnings"],
    ).model_dump()
