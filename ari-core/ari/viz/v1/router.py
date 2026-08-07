"""Declarative router for ``/api/v1`` (gui_refresh Wave 2a, ADR-02).

``ROUTES`` is the single ``(method, path_template, handler)`` table —
``{param}`` segments match exactly one non-empty, URL-decoded path segment.
:func:`dispatch` is the sole entry point ``routes.py`` calls from its
``/api/v1/`` branches; it returns a plain dict ready for the existing
``self._json(r, status=r.pop("_status", 200))`` convention.

Request correlation: every dispatch generates ``request_id = 'req-' + 12 hex
of a uuid4`` and injects it into the error envelope (``error.request_id``)
or, on success, as a top-level ``request_id`` field. The same table drives
the deterministic OpenAPI generator (:mod:`ari.viz.v1.openapi`).

Mutations (Wave 3b, task 05 config CRUD; Wave 4d adds the ADR-05 secret
PUT): POST/PATCH/PUT carry a JSON-object body (invalid JSON → 400
``invalid_request``); PATCH/DELETE carry the
``If-Match: "<revision>"`` optimistic-concurrency header (quoted or bare
integer; malformed → 400, and requiredness is enforced by the handler so a
missing header is also a 400).  A stale precondition surfaces from the
store as :class:`ari.viz.v1.store.RevisionConflict` and is translated here
into the frozen 409 ``revision_conflict`` envelope.
"""

from __future__ import annotations

import inspect
import json
import logging
import urllib.parse
import uuid
from typing import Callable, Mapping

from . import queries
from .dto import ProjectListV1, RunListV1
from .errors import error_response
from .store import RevisionConflict

log = logging.getLogger(__name__)


def _new_request_id() -> str:
    return "req-" + uuid.uuid4().hex[:12]


# ── handlers: return a payload dict (DTO.model_dump()) or an error envelope ─


def _handle_list_projects() -> dict:
    return ProjectListV1(projects=queries.list_projects()).model_dump()


def _handle_list_runs(project_id: str) -> dict:
    runs = queries.list_runs(project_id)
    if isinstance(runs, dict):  # typed 404 envelope
        return runs
    return RunListV1(project_id=project_id, runs=runs).model_dump()


def _handle_get_run(run_id: str) -> dict:
    r = queries.get_run(run_id)
    return r if isinstance(r, dict) else r.model_dump()


def _handle_get_run_summary(run_id: str) -> dict:
    r = queries.get_run_summary(run_id)
    return r if isinstance(r, dict) else r.model_dump()


def _handle_get_run_tree(run_id: str) -> dict:
    r = queries.get_run_tree(run_id)
    return r if isinstance(r, dict) else r.model_dump()


def _handle_get_run_idea(run_id: str) -> dict:
    # Wave 4c: pure {ckpt}/idea.json read (ideas / gap_analysis /
    # primary_metric / metric_rationale); absent file => present=false,
    # never fabricated empties.
    r = queries.get_run_idea(run_id)
    return r if isinstance(r, dict) else r.model_dump()


def _handle_get_run_results(run_id: str) -> dict:
    # Wave 4d (task 07): bounded result read model — paper/review/ORS/EAR
    # presence + scalars over committed artifacts (readers in results.py;
    # local import keeps the module inert until dispatched).
    from . import results

    r = results.get_run_results(run_id)
    return r if isinstance(r, dict) else r.model_dump()


def _handle_get_run_ear(run_id: str) -> dict:
    # Wave 4d (task 07): EAR listing metadata + curate/publish lineage
    # scalars — no file contents ever ride this endpoint.
    from . import results

    r = results.get_run_ear(run_id)
    return r if isinstance(r, dict) else r.model_dump()


def _handle_get_run_logs(run_id: str, query: dict) -> dict:
    # Task 07 tail (plan 07 §Artifacts, logs, and diagnostics): bounded
    # byte-offset cursor pagination over {ckpt}/ari.log — committed lines
    # only, <= 1 MiB scanned per request, absent file => present=false.
    # Local import keeps the reader module inert until dispatched.
    from . import logs

    r = logs.get_run_logs(run_id, query)
    return r if isinstance(r, dict) else r.model_dump()


def _handle_secrets_status() -> dict:
    # Wave 3a (ADR-11 / RR-P0-2): readiness only — values never leave the
    # server. Local import keeps the secrets module inert until dispatched.
    from .secrets import get_secrets_status

    return get_secrets_status().model_dump()


def _handle_put_secret(secret_id: str, body: dict) -> dict:
    # Wave 4d (task 06, ADR-05): canonical write-only secret assignment —
    # SECRET_NAMES allowlist (404 otherwise), value validated then delegated
    # to the hardened legacy _upsert_env_key writer; the response is the
    # post-write readiness row, never the value.
    from .secrets import put_secret

    return put_secret(secret_id, body)


def _handle_get_model_catalog() -> dict:
    # Wave 4d (task 06, plan 05 §Configuration API): the legacy /api/models
    # static provider/model suggestions re-served (single source) plus each
    # provider's API-key env name for the Studio SecretField.
    from .catalogs import get_model_catalog

    return get_model_catalog().model_dump()


def _handle_get_config_schema() -> dict:
    # Wave 3a (task 05): canonical field registry, metadata only — never an
    # effective value; secret_reference fields carry no default.
    return queries.get_config_schema().model_dump()


def _handle_get_run_resolved_config(run_id: str) -> dict:
    # Wave 3a (task 05): legacy-compatible-1 resolved manifest — post-hoc
    # values + provenance + digest; secrets redacted before the digest.
    r = queries.get_resolved_config(run_id)
    return r if isinstance(r, dict) else r.model_dump()


# ── Wave 3b (task 05): config CRUD — thin wrappers over config_api.py.
# Local imports keep the store/registry modules inert until dispatched.


def _handle_get_project_config(project_id: str) -> dict:
    from . import config_api

    return config_api.get_project_config(project_id)


def _handle_patch_project_config(
    project_id: str, body: dict, if_match: int | None
) -> dict:
    from . import config_api

    return config_api.patch_project_config(project_id, body, if_match)


def _handle_list_run_templates() -> dict:
    from . import config_api

    return config_api.list_run_templates()


def _handle_create_run_template(body: dict) -> dict:
    from . import config_api

    return config_api.create_run_template(body)


def _handle_get_run_template(template_id: str) -> dict:
    from . import config_api

    return config_api.get_run_template(template_id)


def _handle_patch_run_template(
    template_id: str, body: dict, if_match: int | None
) -> dict:
    from . import config_api

    return config_api.patch_run_template(template_id, body, if_match)


def _handle_delete_run_template(template_id: str, if_match: int | None) -> dict:
    from . import config_api

    return config_api.delete_run_template(template_id, if_match)


def _handle_create_run_draft(body: dict) -> dict:
    from . import config_api

    return config_api.create_run_draft(body)


def _handle_get_run_draft(draft_id: str) -> dict:
    from . import config_api

    return config_api.get_run_draft(draft_id)


def _handle_patch_run_draft(
    draft_id: str, body: dict, if_match: int | None
) -> dict:
    from . import config_api

    return config_api.patch_run_draft(draft_id, body, if_match)


def _handle_resolve_run_draft_config(draft_id: str, body: dict) -> dict:
    # Wave 3b (task 05): plan-05 new-run chain previewed for one draft —
    # defaults < bundled workflow < profile < project < template < draft <
    # documented env; rejected overrides annotated, never silently dropped.
    from . import config_api

    return config_api.resolve_run_draft_config(draft_id, body)


def _handle_validate_run_draft(draft_id: str, body: dict) -> dict:
    # Wave 3b (task 05): {valid, errors, warnings} distilled from the same
    # resolution run (interlock mismatch is an ERROR here — plan 05
    # §Interlocks — while resolve-config only warns and falls back).
    from . import config_api

    return config_api.validate_run_draft(draft_id, body)


def _handle_launch_run(body: dict) -> dict:
    # Wave 4e (tasks 04/06): idempotent launch — validation-first over the
    # draft (mode/governance fields locked per ADR-09-pending), server-minted
    # collision-resistant run_id, checkpoint materialized (experiment.md /
    # workflow.yaml seed / launch_config.json / resolved_config.json) before
    # the CLI subprocess spawns; a duplicate idempotency_key replays the same
    # run_id and spawns nothing.  Local import keeps the subprocess/env
    # plumbing inert until dispatched.
    from . import launch

    return launch.launch_run(body)


# ── Wave 4a (task 08): RQGM read models — thin wrappers over rqgm.py.
# Local imports keep the reader module inert until dispatched.  All eight
# resources are GETs (plan 08: the v1 RQGM surface is read-only — no
# mutation endpoint exists); handlers taking ``query`` receive the parsed
# query-string dict from dispatch().


def _handle_rqgm_capabilities(run_id: str) -> dict:
    from . import rqgm

    r = rqgm.get_capabilities(run_id)
    return r if isinstance(r, dict) else r.model_dump()


def _handle_rqgm_overview(run_id: str) -> dict:
    from . import rqgm

    r = rqgm.get_overview(run_id)
    return r if isinstance(r, dict) else r.model_dump()


def _handle_rqgm_registry(run_id: str) -> dict:
    from . import rqgm

    r = rqgm.get_registry(run_id)
    return r if isinstance(r, dict) else r.model_dump()


def _handle_rqgm_transitions(run_id: str, query: dict) -> dict:
    from . import rqgm

    r = rqgm.list_transitions(run_id, query)
    return r if isinstance(r, dict) else r.model_dump()


def _handle_rqgm_audit(run_id: str, query: dict) -> dict:
    from . import rqgm

    r = rqgm.list_audit(run_id, query)
    return r if isinstance(r, dict) else r.model_dump()


def _handle_rqgm_node_lineage(run_id: str, node_id: str) -> dict:
    from . import rqgm

    r = rqgm.get_node_lineage(run_id, node_id)
    return r if isinstance(r, dict) else r.model_dump()


def _handle_rqgm_score_rewrites(run_id: str, query: dict) -> dict:
    from . import rqgm

    r = rqgm.list_score_rewrites(run_id, query)
    return r if isinstance(r, dict) else r.model_dump()


def _handle_rqgm_policies(run_id: str) -> dict:
    from . import rqgm

    r = rqgm.list_policies(run_id)
    return r if isinstance(r, dict) else r.model_dump()


# ── Wave 4b (task 08): remaining RQGM read models — epochs / evolution /
# paper-archive.  Same posture as Wave 4a: GET-only, committed-artifact
# reads, local imports keep the reader module inert until dispatched.


def _handle_rqgm_epochs(run_id: str) -> dict:
    from . import rqgm

    r = rqgm.list_epochs(run_id)
    return r if isinstance(r, dict) else r.model_dump()


def _handle_rqgm_epoch_detail(run_id: str, epoch_id: str) -> dict:
    from . import rqgm

    r = rqgm.get_epoch(run_id, epoch_id)
    return r if isinstance(r, dict) else r.model_dump()


def _handle_rqgm_evolution(run_id: str) -> dict:
    from . import rqgm

    r = rqgm.get_evolution(run_id)
    return r if isinstance(r, dict) else r.model_dump()


def _handle_rqgm_paper_archive(run_id: str) -> dict:
    from . import rqgm

    r = rqgm.get_paper_archive(run_id)
    return r if isinstance(r, dict) else r.model_dump()


# ── Wave 5a (task 09, MN-6): server-issued confirmation challenges for the
# dangerous legacy operations (RR-P0-6/RR-P0-9).  Local import keeps the
# challenge store inert until dispatched.


def _handle_create_challenge(body: dict) -> dict:
    from . import challenges

    return challenges.issue_challenge(body)


# ── Wave 5b (task 09, MN-9): bounded operational diagnostics (plan 09
# §Operational visibility).  Local import keeps ari.viz.health inert until
# dispatched; auth is the normal do_GET gate (REQUIRED in remote mode).


def _handle_diagnostics() -> dict:
    from ari.viz import health as _health

    if not _health.health_enabled():
        # ARI_GUI_HEALTH=0 kill-switch: restore the pre-MN-9 wire behavior
        # (the route did not exist -> the typed 404 envelope).
        return error_response(
            "not_found",
            "GET /api/v1/diagnostics is disabled "
            "(ARI_GUI_HEALTH=0 kill-switch, MN-9)",
            request_id="",
            status=404,
        )
    return _health.diagnostics().model_dump()


# Declarative route table. Order matters only between templates with the same
# segment count; more specific templates (literal tails) are listed first.
ROUTES: list[tuple[str, str, Callable[..., dict]]] = [
    ("GET", "/api/v1/projects", _handle_list_projects),
    ("GET", "/api/v1/projects/{project_id}/runs", _handle_list_runs),
    ("GET", "/api/v1/config/schema", _handle_get_config_schema),
    ("GET", "/api/v1/runs/{run_id}/resolved-config", _handle_get_run_resolved_config),
    ("GET", "/api/v1/runs/{run_id}/summary", _handle_get_run_summary),
    ("GET", "/api/v1/runs/{run_id}/tree", _handle_get_run_tree),
    # Wave 4c: idea read model (pure idea.json read, honest absence).
    ("GET", "/api/v1/runs/{run_id}/idea", _handle_get_run_idea),
    # Wave 4d (task 07): results / EAR read models (plan 07 §Evidence,
    # Results, and PaperBench — bounded scalars, honest absence flags).
    ("GET", "/api/v1/runs/{run_id}/results", _handle_get_run_results),
    ("GET", "/api/v1/runs/{run_id}/ear", _handle_get_run_ear),
    # Task 07 tail: cursor-based log explorer over {ckpt}/ari.log (plan 07
    # §Artifacts, logs, and diagnostics — bounded reads, committed-only).
    ("GET", "/api/v1/runs/{run_id}/logs", _handle_get_run_logs),
    ("GET", "/api/v1/runs/{run_id}", _handle_get_run),
    # ── Wave 4e (tasks 04/06): the canonical idempotent launch (plan 04
    # §Run identity and lifecycle + plan 06 §Launch protocol); the legacy
    # POST /api/launch keeps running unchanged in parallel.
    ("POST", "/api/v1/runs", _handle_launch_run),
    ("GET", "/api/v1/secrets/status", _handle_secrets_status),
    # ── Wave 5a (task 09, MN-6): single-use confirmation challenges that
    # POST /api/delete-checkpoint, /api/stop, and /api/gpu-monitor stop
    # require (RR-P0-6/RR-P0-9; 60s TTL, deque cap 100, audit-logged).
    ("POST", "/api/v1/challenges", _handle_create_challenge),
    # ── Wave 4d (task 06, ADR-05): canonical write-only secret assignment.
    # 'status' is never a valid {secret_id} (not on the SECRET_NAMES
    # allowlist), so the GET above and this PUT cannot collide.
    ("PUT", "/api/v1/secrets/{secret_id}", _handle_put_secret),
    # ── Wave 4d (task 06, plan 05): server-side model/provider catalog.
    ("GET", "/api/v1/config/catalogs/models", _handle_get_model_catalog),
    # ── Wave 3b (task 05): config CRUD (ADR-12 store; If-Match concurrency) ─
    ("GET", "/api/v1/projects/{project_id}/config", _handle_get_project_config),
    ("PATCH", "/api/v1/projects/{project_id}/config", _handle_patch_project_config),
    ("GET", "/api/v1/run-templates", _handle_list_run_templates),
    ("POST", "/api/v1/run-templates", _handle_create_run_template),
    ("GET", "/api/v1/run-templates/{template_id}", _handle_get_run_template),
    ("PATCH", "/api/v1/run-templates/{template_id}", _handle_patch_run_template),
    ("DELETE", "/api/v1/run-templates/{template_id}", _handle_delete_run_template),
    ("POST", "/api/v1/run-drafts", _handle_create_run_draft),
    ("GET", "/api/v1/run-drafts/{draft_id}", _handle_get_run_draft),
    ("PATCH", "/api/v1/run-drafts/{draft_id}", _handle_patch_run_draft),
    # ── Wave 3b (task 05): new-run preview resolution over one draft ───────
    ("POST", "/api/v1/run-drafts/{draft_id}/resolve-config",
     _handle_resolve_run_draft_config),
    ("POST", "/api/v1/run-drafts/{draft_id}/validate",
     _handle_validate_run_draft),
    # ── Wave 4a (task 08): RQGM governance read models (plan 08) — GET-only
    # (read-only surface by plan; direct governance mutation is prohibited).
    ("GET", "/api/v1/runs/{run_id}/rqgm/capabilities",
     _handle_rqgm_capabilities),
    ("GET", "/api/v1/runs/{run_id}/rqgm/overview", _handle_rqgm_overview),
    ("GET", "/api/v1/runs/{run_id}/rqgm/registry", _handle_rqgm_registry),
    ("GET", "/api/v1/runs/{run_id}/rqgm/transitions",
     _handle_rqgm_transitions),
    ("GET", "/api/v1/runs/{run_id}/rqgm/audit", _handle_rqgm_audit),
    ("GET", "/api/v1/runs/{run_id}/rqgm/policies", _handle_rqgm_policies),
    ("GET", "/api/v1/runs/{run_id}/rqgm/score-rewrites",
     _handle_rqgm_score_rewrites),
    ("GET", "/api/v1/runs/{run_id}/rqgm/nodes/{node_id}/lineage",
     _handle_rqgm_node_lineage),
    # ── Wave 4b (task 08): remaining RQGM read models — still GET-only.
    ("GET", "/api/v1/runs/{run_id}/rqgm/epochs", _handle_rqgm_epochs),
    ("GET", "/api/v1/runs/{run_id}/rqgm/epochs/{epoch_id}",
     _handle_rqgm_epoch_detail),
    ("GET", "/api/v1/runs/{run_id}/rqgm/evolution", _handle_rqgm_evolution),
    ("GET", "/api/v1/runs/{run_id}/rqgm/paper-archive",
     _handle_rqgm_paper_archive),
    # ── Wave 5b (task 09, MN-9): bounded operational diagnostics — SSE bus /
    # watcher / tracked-process scalars + versions, no secrets or paths
    # (plan 09 §Operational visibility; builder in ari/viz/health.py).
    ("GET", "/api/v1/diagnostics", _handle_diagnostics),
]


def _match_template(template: str, path: str) -> dict[str, str] | None:
    """Match one template against a query-stripped path; extract params."""
    t_segs = template.strip("/").split("/")
    p_segs = path.strip("/").split("/")
    if len(t_segs) != len(p_segs):
        return None
    params: dict[str, str] = {}
    for t, p in zip(t_segs, p_segs):
        if t.startswith("{") and t.endswith("}"):
            if not p:
                return None
            params[t[1:-1]] = urllib.parse.unquote(p)
        elif t != p:
            return None
    return params


def match(
    path: str, method: str = "GET"
) -> tuple[Callable[..., dict], dict[str, str], str] | None:
    """First-match route lookup: ``(handler, params, template)`` or ``None``.

    The query string / fragment are stripped before matching; ``{param}``
    values are URL-decoded.
    """
    clean = path.split("?", 1)[0].split("#", 1)[0]
    for m, template, handler in ROUTES:
        if m != method:
            continue
        params = _match_template(template, clean)
        if params is not None:
            return handler, params, template
    return None


def _parse_query(path: str) -> dict[str, str]:
    """Query-string params as a flat first-value-wins dict (Wave 4a: the
    RQGM pagination/filter handlers declare a ``query`` parameter and
    receive this; handlers without one are dispatched exactly as before)."""
    if "?" not in path:
        return {}
    qs = path.split("?", 1)[1].split("#", 1)[0]
    parsed = urllib.parse.parse_qs(qs, keep_blank_values=True)
    return {k: v[0] for k, v in parsed.items()}


def _parse_json_body(body: bytes | None) -> tuple[dict | None, str | None]:
    """Parse a POST/PATCH body: ``(parsed_dict, None)`` or ``(None, error)``.
    An absent/empty body parses as ``{}`` (handlers enforce required keys)."""
    if not body:
        return {}, None
    try:
        parsed = json.loads(body)
    except ValueError as e:
        return None, f"invalid JSON body: {e}"
    if not isinstance(parsed, dict):
        return None, "request body must be a JSON object"
    return parsed, None


def _parse_if_match(
    headers: Mapping[str, str] | None,
) -> tuple[int | None, str | None]:
    """Parse ``If-Match: "<revision>"`` → ``(revision, None)``.

    Missing header → ``(None, None)`` (requiredness is per-handler so the
    400 message can say which mutation needs it); malformed → ``(None,
    error)``.  Both the quoted ETag form (``"3"``) and a bare integer are
    accepted; weak validators (``W/"3"``) are not — revisions are exact.
    """
    raw = headers.get("If-Match") if headers is not None else None
    if raw is None:
        return None, None
    s = raw.strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        s = s[1:-1]
    if not s.isdigit():
        return None, (
            f'malformed If-Match header {raw!r} — expected "<revision>" '
            "(a non-negative integer, optionally quoted)"
        )
    return int(s), None


def dispatch(
    method: str,
    path: str,
    body: bytes | None = None,
    headers: Mapping[str, str] | None = None,
) -> dict:
    """Route one request; always returns a dict for the ``_status`` convention."""
    request_id = _new_request_id()
    hit = match(path, method)
    if hit is None:
        return error_response(
            "not_found",
            f"no /api/v1 resource matches {method} {path.split('?', 1)[0]}",
            request_id=request_id,
            status=404,
        )
    handler, params, _template = hit
    kwargs: dict = dict(params)
    if "query" in inspect.signature(handler).parameters:
        kwargs["query"] = _parse_query(path)
    if method in ("POST", "PATCH", "PUT"):
        parsed, perr = _parse_json_body(body)
        if perr is not None:
            return error_response(
                "invalid_request", perr, request_id=request_id, status=400
            )
        kwargs["body"] = parsed
    if method in ("PATCH", "DELETE"):
        if_match, ierr = _parse_if_match(headers)
        if ierr is not None:
            return error_response(
                "invalid_request", ierr, request_id=request_id, status=400
            )
        kwargs["if_match"] = if_match
    try:
        result = handler(**kwargs)
    except RevisionConflict as e:  # stale If-Match → frozen 409 envelope
        return error_response(
            "revision_conflict",
            str(e),
            details={"expected": e.expected, "actual": e.actual},
            request_id=request_id,
            status=409,
        )
    except Exception as e:  # typed 500 — never leak a stack trace to the wire
        log.warning("v1 handler error: %s %s", method, path, exc_info=True)
        return error_response(
            "internal",
            f"{type(e).__name__}: {e}",
            request_id=request_id,
            retryable=True,
            status=500,
        )
    if isinstance(result, dict) and "error" in result and "_status" in result:
        result["error"]["request_id"] = request_id
        return result
    out = dict(result)
    out["request_id"] = request_id
    return out
