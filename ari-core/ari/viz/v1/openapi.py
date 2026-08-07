"""Deterministic OpenAPI 3.1 generator for ``/api/v1`` (ADR-02).

The document is derived from exactly two sources — the declarative
``router.ROUTES`` table and the pydantic v2 model JSON schemas in ``dto`` —
and emitted byte-stably (sorted keys, no timestamps, no commit SHAs; design
principle P2), so regeneration is diffable and the committed file can be
drift-guarded::

    python -m ari.viz.v1.openapi            # verify (--check is the default)
    python -m ari.viz.v1.openapi --update   # regenerate ari/viz/v1/openapi.json

``tests/test_gui_v1_api.py`` asserts committed == regenerated, mirroring the
``scripts/snapshot_contracts.py`` golden-fixture pattern. Success responses
are ``model ∧ RequestIdV1`` (the router injects a top-level ``request_id``);
every operation also documents the typed 404/500 ``ErrorEnvelopeV1``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import dto
from .router import ROUTES

OPENAPI_PATH = Path(__file__).parent / "openapi.json"

# Served contract revision (the document's info.version). Single source —
# GET /api/v1/diagnostics reports it as openapi_version (MN-9).
OPENAPI_INFO_VERSION = "1.0.0"

# Route -> success response model (keyed "<METHOD> <template>").
_RESPONSE_MODELS: dict[str, str] = {
    "GET /api/v1/projects": "ProjectListV1",
    "GET /api/v1/projects/{project_id}/runs": "RunListV1",
    "GET /api/v1/runs/{run_id}": "RunDetailV1",
    # Wave 4e (tasks 04/06): idempotent launch — accepted envelope with the
    # server-minted run_id (idempotent_replay=true on a duplicate key).
    "POST /api/v1/runs": "RunLaunchedV1",
    "GET /api/v1/runs/{run_id}/summary": "RunSummaryV1",
    "GET /api/v1/runs/{run_id}/tree": "TreeV1",
    # Wave 4c: idea read model (pure {ckpt}/idea.json read).
    "GET /api/v1/runs/{run_id}/idea": "RunIdeaV1",
    # Wave 4d (task 07): results / EAR read models (bounded scalars).
    "GET /api/v1/runs/{run_id}/results": "RunResultsV1",
    "GET /api/v1/runs/{run_id}/ear": "RunEarV1",
    # Task 07 tail: cursor log explorer over {ckpt}/ari.log.
    "GET /api/v1/runs/{run_id}/logs": "RunLogsV1",
    "GET /api/v1/secrets/status": "SecretStatusV1",
    # Wave 5a (task 09, MN-6): server-issued confirmation challenges for
    # the dangerous legacy operations (RR-P0-6/RR-P0-9).
    "POST /api/v1/challenges": "ChallengeV1",
    # Wave 4d (task 06, ADR-05): write-only secret assignment (readiness-
    # shaped response, never the value) + server-side model catalog.
    "PUT /api/v1/secrets/{secret_id}": "SecretUpdatedV1",
    "GET /api/v1/config/catalogs/models": "ModelCatalogV1",
    "GET /api/v1/config/schema": "ConfigSchemaV1",
    "GET /api/v1/runs/{run_id}/resolved-config": "ResolvedConfigV1",
    # Wave 3b (task 05): config CRUD.
    "GET /api/v1/projects/{project_id}/config": "ProjectConfigV1",
    "PATCH /api/v1/projects/{project_id}/config": "ProjectConfigV1",
    "GET /api/v1/run-templates": "RunTemplateListV1",
    "POST /api/v1/run-templates": "RunTemplateV1",
    "GET /api/v1/run-templates/{template_id}": "RunTemplateV1",
    "PATCH /api/v1/run-templates/{template_id}": "RunTemplateV1",
    "DELETE /api/v1/run-templates/{template_id}": "RunTemplateDeletedV1",
    "POST /api/v1/run-drafts": "RunDraftV1",
    "GET /api/v1/run-drafts/{draft_id}": "RunDraftV1",
    "PATCH /api/v1/run-drafts/{draft_id}": "RunDraftV1",
    # Wave 3b (task 05): new-run preview resolution.
    "POST /api/v1/run-drafts/{draft_id}/resolve-config": (
        "ResolvedNewRunConfigV1"
    ),
    "POST /api/v1/run-drafts/{draft_id}/validate": "DraftValidationV1",
    # Wave 4a (task 08): RQGM governance read models (plan 08, read-only).
    "GET /api/v1/runs/{run_id}/rqgm/capabilities": "RqgmCapabilitiesV1",
    "GET /api/v1/runs/{run_id}/rqgm/overview": "RqgmOverviewV1",
    "GET /api/v1/runs/{run_id}/rqgm/registry": "RqgmRegistryV1",
    "GET /api/v1/runs/{run_id}/rqgm/transitions": "RqgmTransitionsPageV1",
    "GET /api/v1/runs/{run_id}/rqgm/audit": "RqgmAuditPageV1",
    "GET /api/v1/runs/{run_id}/rqgm/policies": "RqgmPoliciesV1",
    "GET /api/v1/runs/{run_id}/rqgm/score-rewrites": (
        "RqgmScoreRewritesPageV1"
    ),
    "GET /api/v1/runs/{run_id}/rqgm/nodes/{node_id}/lineage": (
        "RqgmNodeLineageV1"
    ),
    # Wave 4b (task 08): remaining RQGM read models (still GET-only).
    "GET /api/v1/runs/{run_id}/rqgm/epochs": "RqgmEpochsV1",
    "GET /api/v1/runs/{run_id}/rqgm/epochs/{epoch_id}": "RqgmEpochDetailV1",
    "GET /api/v1/runs/{run_id}/rqgm/evolution": "RqgmEvolutionV1",
    "GET /api/v1/runs/{run_id}/rqgm/paper-archive": "RqgmPaperArchiveV1",
    # Wave 5b (task 09, MN-9): bounded operational diagnostics (plan 09
    # §Operational visibility; builder in ari/viz/health.py).
    "GET /api/v1/diagnostics": "DiagnosticsV1",
}

# Wave 4a (task 08): documented query parameters for the paginated/filtered
# RQGM GETs (cursor = stable byte offset for the JSONL-backed pages, an
# integer list index for the joined score-rewrites list).
def _q(name: str, description: str) -> dict:
    """One optional string query parameter (documentation entry)."""
    return {
        "name": name,
        "in": "query",
        "required": False,
        "description": description,
        "schema": {"type": "string"},
    }


_CURSOR_PARAM = {
    "name": "cursor",
    "in": "query",
    "required": False,
    "description": "Stable pagination cursor (non-negative integer).",
    "schema": {"type": "string"},
}
_LIMIT_PARAM = {
    "name": "limit",
    "in": "query",
    "required": False,
    "description": "Page size, 1-100 (default 20).",
    "schema": {"type": "string"},
}
_EXPAND_PARAM = {
    "name": "expand",
    "in": "query",
    "required": False,
    "description": "expand=1 inlines the full raw record(s) per entry.",
    "schema": {"type": "string"},
}
_QUERY_PARAMS: dict[str, list[dict]] = {
    "GET /api/v1/runs/{run_id}/rqgm/transitions": [
        _CURSOR_PARAM, _LIMIT_PARAM, _EXPAND_PARAM
    ],
    "GET /api/v1/runs/{run_id}/rqgm/audit": [
        _CURSOR_PARAM,
        _LIMIT_PARAM,
        _EXPAND_PARAM,
        {
            "name": "record_type",
            "in": "query",
            "required": False,
            "description": (
                "Filter by audit event_type or payload record_type."
            ),
            "schema": {"type": "string"},
        },
        {
            "name": "epoch",
            "in": "query",
            "required": False,
            "description": "Filter by payload epoch_id.",
            "schema": {"type": "string"},
        },
    ],
    "GET /api/v1/runs/{run_id}/rqgm/score-rewrites": [
        _CURSOR_PARAM, _LIMIT_PARAM
    ],
    # Task 07 tail: cursor log explorer — the cursor is a RAW byte offset
    # into the append-only {ckpt}/ari.log, so pagination is stable under
    # any grep filter (the filter selects returned lines, never consumed
    # bytes; it is applied while scanning forward up to `limit` matches).
    "GET /api/v1/runs/{run_id}/logs": [
        _q("cursor", "Raw byte offset into ari.log to resume from "
           "(non-negative integer; default 0)."),
        _q("limit", "Maximum matching lines, 1-1000 (default 200)."),
        _q("grep", "Case-insensitive substring filter applied while "
           "scanning forward (cursor stability is filter-independent)."),
    ],
}

# GET routes that can answer 400 (invalid cursor/limit query values).
_GET_BAD_REQUEST = set(_QUERY_PARAMS)

# Route -> request-body model (mutations only).
_REQUEST_MODELS: dict[str, str] = {
    "PATCH /api/v1/projects/{project_id}/config": "ValuesPatchRequestV1",
    "POST /api/v1/run-templates": "RunTemplateCreateRequestV1",
    "PATCH /api/v1/run-templates/{template_id}": "ValuesPatchRequestV1",
    "POST /api/v1/run-drafts": "RunDraftCreateRequestV1",
    "PATCH /api/v1/run-drafts/{draft_id}": "ValuesPatchRequestV1",
    "POST /api/v1/run-drafts/{draft_id}/resolve-config": "DraftResolveRequestV1",
    "POST /api/v1/run-drafts/{draft_id}/validate": "DraftResolveRequestV1",
    # Wave 4d (task 06, ADR-05): the write-only value channel.
    "PUT /api/v1/secrets/{secret_id}": "SecretValueRequestV1",
    # Wave 5a (task 09, MN-6): confirmation challenge issuance.
    "POST /api/v1/challenges": "ChallengeRequestV1",
    # Wave 4e (tasks 04/06): idempotent launch request.
    "POST /api/v1/runs": "RunLaunchRequestV1",
}

# Creations answer 201 (the handler's transport-only "_status" key).
_CREATED = {"POST /api/v1/run-templates", "POST /api/v1/run-drafts"}

# Routes that can answer the frozen 409 envelope: If-Match preconditions
# (code 'revision_conflict') and the create-only POST (code 'already_exists').
_CONFLICT_DESCRIPTIONS: dict[str, str] = {
    "PATCH": (
        "Typed error envelope: stale If-Match revision "
        "(code 'revision_conflict', details {expected, actual})."
    ),
    "DELETE": (
        "Typed error envelope: stale If-Match revision "
        "(code 'revision_conflict', details {expected, actual})."
    ),
    "POST /api/v1/run-templates": (
        "Typed error envelope: template_id already exists "
        "(code 'already_exists')."
    ),
}

# Models exported to components.schemas (nested refs resolve via $defs merge).
_SCHEMA_MODELS = (
    dto.ProjectV1,
    dto.RunSummaryV1,
    dto.RunDetailV1,
    dto.TreeV1,
    # Wave 4c: idea read model.
    dto.RunIdeaV1,
    # Wave 4d (task 07): results / EAR read models.
    dto.ResultPaperV1,
    dto.ReviewDimensionV1,
    dto.ResultReviewV1,
    dto.ResultOrsV1,
    dto.ResultEarV1,
    dto.RunResultsV1,
    dto.EarFileV1,
    dto.EarManifestV1,
    dto.EarPublishRecordV1,
    dto.RunEarV1,
    # Task 07 tail: cursor log explorer read model.
    dto.LogEntryV1,
    dto.RunLogsV1,
    dto.SecretV1,
    dto.SecretStatusV1,
    # Wave 4d (task 06, ADR-05): secret assignment + model catalog.
    dto.SecretValueRequestV1,
    dto.SecretUpdatedV1,
    dto.ModelProviderV1,
    dto.ModelCatalogV1,
    dto.ConfigFieldV1,
    dto.ConfigSchemaV1,
    dto.ProvenanceEntryV1,
    dto.SecretReferenceV1,
    dto.ResolvedConfigV1,
    dto.ProjectConfigV1,
    dto.RunTemplateSummaryV1,
    dto.RunTemplateListV1,
    dto.RunTemplateV1,
    dto.RunTemplateDeletedV1,
    dto.RunDraftV1,
    # Wave 4e (tasks 04/06): idempotent launch.
    dto.RunLaunchRequestV1,
    dto.RunLaunchedV1,
    dto.RejectedOverrideV1,
    dto.NewRunProvenanceV1,
    dto.ResolvedNewRunConfigV1,
    dto.DraftResolveRequestV1,
    dto.DraftValidationErrorV1,
    dto.DraftValidationV1,
    dto.ValuesPatchRequestV1,
    dto.RunTemplateCreateRequestV1,
    dto.RunDraftCreateRequestV1,
    dto.ProjectListV1,
    dto.RunListV1,
    # Wave 4a (task 08): RQGM read models.
    dto.RqgmCapabilitiesV1,
    dto.RqgmIntegrityV1,
    dto.RqgmRegistrySummaryV1,
    dto.RqgmOverviewV1,
    dto.RqgmComponentV1,
    dto.RqgmPromptV1,
    dto.RqgmRegistryV1,
    dto.RqgmTransitionEntryV1,
    dto.RqgmTransitionsPageV1,
    dto.RqgmAuditEntryV1,
    dto.RqgmAuditPageV1,
    dto.RqgmScoreObservationV1,
    dto.RqgmRawAttackV1,
    dto.RqgmValidatedAttackV1,
    dto.RqgmNodeLineageV1,
    dto.RqgmScoreRewriteV1,
    dto.RqgmScoreRewritesPageV1,
    dto.RqgmPolicyV1,
    dto.RqgmPoliciesV1,
    # Wave 4b (task 08): epochs / evolution / paper-archive read models.
    dto.RqgmEpochTransitionCountsV1,
    dto.RqgmEpochV1,
    dto.RqgmEpochsV1,
    dto.RqgmTransactionRefV1,
    dto.RqgmEpochDetailV1,
    dto.RqgmEvolutionEntryV1,
    dto.RqgmEvolutionV1,
    dto.RqgmPaperAnchorV1,
    dto.RqgmPaperSelfPreferenceV1,
    dto.RqgmPaperWinnerV1,
    dto.RqgmPaperArchiveV1,
    # Wave 5a (task 09, MN-6): confirmation challenges.
    dto.ChallengeRequestV1,
    dto.ChallengeV1,
    # Wave 5b (task 09, MN-9): operational diagnostics scalars.
    dto.DiagnosticsSseV1,
    dto.DiagnosticsWatcherV1,
    dto.DiagnosticsProcessV1,
    dto.DiagnosticsV1,
    dto.ErrorBodyV1,
    dto.ErrorEnvelopeV1,
)

_REQUEST_ID_SCHEMA = {
    "type": "object",
    "properties": {
        "request_id": {"type": "string", "pattern": "^req-[0-9a-f]{12}$"}
    },
    "required": ["request_id"],
}


def _components() -> dict:
    schemas: dict[str, dict] = {}
    for model in _SCHEMA_MODELS:
        sch = model.model_json_schema(
            ref_template="#/components/schemas/{model}"
        )
        for name, sub in sch.pop("$defs", {}).items():
            schemas.setdefault(name, sub)
        schemas[model.__name__] = sch
    schemas["RequestIdV1"] = _REQUEST_ID_SCHEMA
    return {"schemas": schemas}


def _path_params(template: str) -> list[str]:
    return [
        seg[1:-1]
        for seg in template.strip("/").split("/")
        if seg.startswith("{") and seg.endswith("}")
    ]


def _error_response(description: str) -> dict:
    return {
        "description": description,
        "content": {
            "application/json": {
                "schema": {"$ref": "#/components/schemas/ErrorEnvelopeV1"}
            }
        },
    }


def _operation(method: str, template: str, handler) -> dict:
    key = f"{method} {template}"
    model = _RESPONSE_MODELS[key]
    success = "201" if key in _CREATED else "200"
    op: dict = {
        "operationId": handler.__name__.removeprefix("_handle_"),
        "responses": {
            success: {
                "description": f"{model} plus the router-injected request_id.",
                "content": {
                    "application/json": {
                        "schema": {
                            "allOf": [
                                {"$ref": f"#/components/schemas/{model}"},
                                {"$ref": "#/components/schemas/RequestIdV1"},
                            ]
                        }
                    }
                },
            },
            "404": _error_response(
                "Typed error envelope: unknown resource (code 'not_found')."
            ),
            "500": _error_response(
                "Typed error envelope: handler failure (code 'internal', retryable)."
            ),
        },
    }
    if method != "GET":
        op["responses"]["400"] = _error_response(
            "Typed error envelope: invalid body / patch path / missing or "
            "malformed If-Match (code 'invalid_request', offending paths in "
            "details)."
        )
    elif key in _GET_BAD_REQUEST:
        op["responses"]["400"] = _error_response(
            "Typed error envelope: invalid cursor/limit query value "
            "(code 'invalid_request')."
        )
    conflict = _CONFLICT_DESCRIPTIONS.get(key) or _CONFLICT_DESCRIPTIONS.get(
        method
    )
    if conflict:
        op["responses"]["409"] = _error_response(conflict)
    request_model = _REQUEST_MODELS.get(key)
    if request_model:
        op["requestBody"] = {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "$ref": f"#/components/schemas/{request_model}"
                    }
                }
            },
        }
    params = [
        {
            "name": p,
            "in": "path",
            "required": True,
            "schema": {"type": "string"},
        }
        for p in _path_params(template)
    ]
    params.extend(_QUERY_PARAMS.get(key, []))
    if method in ("PATCH", "DELETE"):
        params.append(
            {
                "name": "If-Match",
                "in": "header",
                "required": True,
                "description": (
                    'Current document revision ("0" creates the project '
                    "config); stale values answer 409 'revision_conflict'."
                ),
                "schema": {"type": "string"},
            }
        )
    if params:
        op["parameters"] = params
    return op


def build_openapi() -> dict:
    paths: dict[str, dict] = {}
    for method, template, handler in ROUTES:
        paths.setdefault(template, {})[method.lower()] = _operation(
            method, template, handler
        )
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "ARI viz /api/v1",
            "version": OPENAPI_INFO_VERSION,
            "description": (
                "Versioned dashboard API (gui_refresh Wave 2a reads, "
                "ADR-02/ADR-08; Wave 3b config CRUD with If-Match "
                "optimistic concurrency, ADR-12). Generated "
                "deterministically from ari/viz/v1/router.py + dto.py by "
                "ari/viz/v1/openapi.py — do not edit openapi.json by hand; "
                "regenerate with `python -m ari.viz.v1.openapi --update`."
            ),
        },
        "paths": paths,
        "components": _components(),
    }


def dumps(doc: dict) -> str:
    """Byte-stable JSON text (sorted keys, unicode kept, trailing newline)."""
    return json.dumps(doc, sort_keys=True, ensure_ascii=False, indent=2) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="verify (default)")
    mode.add_argument(
        "--update", action="store_true", help="regenerate openapi.json"
    )
    args = parser.parse_args(argv)

    fresh = dumps(build_openapi())
    if args.update:
        OPENAPI_PATH.write_text(fresh, encoding="utf-8")
        print(f"wrote {OPENAPI_PATH}")
        return 0
    if not OPENAPI_PATH.exists():
        print(f"missing committed OpenAPI document: {OPENAPI_PATH}", file=sys.stderr)
        return 1
    if OPENAPI_PATH.read_text(encoding="utf-8") != fresh:
        print(
            "openapi.json drift detected: regenerate with "
            "`python -m ari.viz.v1.openapi --update` if the change is intentional.",
            file=sys.stderr,
        )
        return 1
    print("openapi.json in sync")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
