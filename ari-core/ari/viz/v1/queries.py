"""Pure read queries backing ``/api/v1`` (gui_refresh Wave 2a, ADR-02/ADR-08).

Every function here answers from the filesystem alone:

- NO module-global mutation — unlike ``checkpoint_api._api_checkpoints``
  (which prunes ``_st._running_procs``) and
  ``services.state_service.build_app_state`` (which mutates
  ``_st._last_experiment_md``), nothing in this module touches ``viz.state``;
- NO ``os.environ`` writes;
- reuse, not reinvention: run resolution goes through
  ``checkpoint_finder._resolve_checkpoint_dir`` and the pid probe through the
  ``checkpoint_api`` wrapper (both defer to the ``api_state`` facade at call
  time, so tests that monkeypatch ``api_state`` are honored here too); tree
  loading goes through the byte-preserving ``tree_view.build_tree_view``
  adapter.

ADR-08: ``list_projects`` exposes a single virtual project ``default`` whose
run list is the existing checkpoint-scan result (same ``YYYYMMDDHHMMSS_*``
directory filter and skip set as ``_api_checkpoints`` — no new enumeration
semantics); no file is ever written.

Not-found results are returned as the typed 404 envelope from
:func:`ari.viz.v1.errors.error_response` with a placeholder ``request_id``
(the router injects the real one).
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from ..checkpoint_api import _check_pid_alive
from ..checkpoint_finder import _resolve_checkpoint_dir
from ..run_health import run_terminal_health
from ..tree_view import build_tree_view
from .dto import (
    ConfigFieldV1,
    ConfigSchemaV1,
    ProjectV1,
    ResolvedConfigV1,
    RunDetailV1,
    RunIdeaV1,
    RunSummaryV1,
    TreeV1,
)
from .errors import error_response

log = logging.getLogger(__name__)

DEFAULT_PROJECT_ID = "default"
DEFAULT_PROJECT_NAME = "Default project"

# Same checkpoint-dir filters as checkpoint_api._api_checkpoints (ADR-08:
# the default project's run list == the current checkpoint scan result).
_TS_PAT = re.compile(r"^[0-9]{8,14}_")
_SKIP = {"experiments", "__pycache__", ".git"}


def _search_bases() -> list[Path]:
    """Checkpoint search bases via the ``api_state`` facade (call-time deferral
    so ``monkeypatch.setattr(api_state, "_checkpoint_search_bases", ...)``
    is honored — same pattern as ``checkpoint_finder._resolve_checkpoint_dir``)."""
    from .. import api_state as _as

    return _as._checkpoint_search_bases()


def _iter_run_dirs() -> list[Path]:
    """All checkpoint dirs across the search bases, newest-mtime first per
    base — read-only mirror of the ``_api_checkpoints`` enumeration."""
    out: list[Path] = []
    seen: set[Path] = set()
    for base in _search_bases():
        if not base.exists():
            continue
        for d in sorted(
            base.iterdir(),
            key=lambda p: p.stat().st_mtime if p.exists() else 0,
            reverse=True,
        ):
            if not d.is_dir() or d in seen or d.name in _SKIP:
                continue
            if not _TS_PAT.match(d.name):
                continue
            seen.add(d)
            out.append(d)
    # A project is one portfolio across every checkpoint root. Sorting within
    # each root leaves an older run above a newer run from a later root, so
    # order only after the roots have been merged.
    return sorted(
        out,
        key=lambda path: path.stat().st_mtime if path.exists() else 0,
        reverse=True,
    )


def _display_name(run_id: str) -> str:
    """Presentation-only name: the slug after the timestamp prefix (ADR-08:
    the slug is a display name, never an identity)."""
    m = _TS_PAT.match(run_id)
    return (run_id[m.end():] if m else run_id) or run_id


def _mtime_utc(d: Path) -> str:
    """Checkpoint-dir mtime as an ISO 8601 UTC string — every v1 timestamp is
    UTC ISO 8601, never a local-time or epoch-seconds form."""
    return datetime.fromtimestamp(
        int(d.stat().st_mtime), tz=timezone.utc
    ).strftime("%Y-%m-%dT%H:%M:%SZ")


def _has_paper(d: Path) -> bool:
    """Whether a generated TeX source or PDF exists in a supported location."""
    return any(
        path.exists()
        for path in (
            d / "full_paper.tex",
            d / "full_paper.pdf",
            d / "paper" / "full_paper.tex",
            d / "paper" / "full_paper.pdf",
        )
    )


def _run_summary_from_dir(d: Path) -> RunSummaryV1:
    """Read-only status/score derivation for one checkpoint dir.

    Mirrors the read-only tiers of ``_api_checkpoints`` (pid file probe →
    tree-node refinement → ``review_report.json``) without the ``_st``
    process-tracking tier, so a GET never mutates server state.
    """
    status = "unknown"
    node_count = 0
    review_score = None
    best_metric = None

    try:
        if _check_pid_alive(d) == "running":
            status = "running"
    except Exception:
        log.debug("v1 pid probe error: %s", d.name, exc_info=True)

    tree = build_tree_view(d)
    if isinstance(tree, dict):
        nodes = [n for n in tree.get("nodes", []) if isinstance(n, dict)]
        node_count = len(nodes)
        if nodes and status == "unknown":
            statuses = {n.get("status") for n in nodes}
            # Tree says running but no live process → orphaned ("stopped").
            status = "stopped" if "running" in statuses else "completed"
        # Best VALID score (RQGM-erased nodes excluded; key absent ⇒ valid).
        sci_scores = [
            n.get("metrics", {}).get("_scientific_score")
            for n in nodes
            if isinstance(n.get("metrics"), dict)
            and n.get("metrics", {}).get("_scientific_score") is not None
            and n.get("metrics", {}).get("_valid_for_frontier", True) is not False
        ]
        if sci_scores:
            best_metric = round(max(sci_scores), 4)

    rr = d / "review_report.json"
    if rr.exists() and rr.stat().st_size > 0:
        try:
            r = json.loads(rr.read_text(encoding="utf-8", errors="replace"))
            review_score = r.get("overall_score") or r.get("score")
            status = "completed"
        except Exception:
            log.debug("v1 review_report parse error: %s", d.name, exc_info=True)

    # A review is an intermediate artifact.  The immutable build lock is the
    # terminal publication verdict and therefore has higher precedence.
    terminal_status, _ = run_terminal_health(d)
    if terminal_status is not None:
        status = terminal_status

    return RunSummaryV1(
        run_id=d.name,
        project_id=DEFAULT_PROJECT_ID,
        display_name=_display_name(d.name),
        status=status,
        node_count=node_count,
        review_score=review_score,
        best_metric=best_metric,
        mtime_utc=_mtime_utc(d),
        checkpoint_path=str(d),
        has_paper=_has_paper(d),
    )


def _tree_source_file(d: Path) -> Path | None:
    """The file ``ari.checkpoint.load_nodes_tree`` would resolve — the same
    3-tier precedence (``tree.json`` → ``nodes_tree.json`` → newest non-empty
    ``node_*/tree.json``) so ``TreeV1.revision`` tracks the served bytes."""
    p = d / "tree.json"
    if p.exists():
        return p
    p = d / "nodes_tree.json"
    if p.exists():
        return p
    candidates = sorted(
        d.glob("node_*/tree.json"),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    for c in candidates:
        try:
            if c.stat().st_size > 2:
                return c
        except OSError:
            continue
    return None


# ── query surface (one function per v1 resource) ───────────────────────────


def list_projects() -> list[ProjectV1]:
    """GET /api/v1/projects — the single virtual ``default`` project (ADR-08)."""
    roots = list(dict.fromkeys(str(b) for b in _search_bases() if b.exists()))
    return [
        ProjectV1(
            project_id=DEFAULT_PROJECT_ID,
            name=DEFAULT_PROJECT_NAME,
            checkpoint_roots=roots,
            run_count=len(_iter_run_dirs()),
        )
    ]


def list_runs(project_id: str) -> list[RunSummaryV1] | dict:
    """GET /api/v1/projects/{project_id}/runs — 404 envelope for any project
    other than the virtual ``default`` one."""
    if project_id != DEFAULT_PROJECT_ID:
        return error_response(
            "not_found",
            f"unknown project: {project_id}",
            request_id="",
            status=404,
        )
    return [_run_summary_from_dir(d) for d in _iter_run_dirs()]


def get_run_summary(run_id: str) -> RunSummaryV1 | dict:
    """GET /api/v1/runs/{run_id}/summary."""
    d = _resolve_checkpoint_dir(run_id)
    if d is None:
        return error_response(
            "not_found", f"unknown run: {run_id}", request_id="", status=404
        )
    return _run_summary_from_dir(d)


def get_run(run_id: str) -> RunDetailV1 | dict:
    """GET /api/v1/runs/{run_id} — summary + artifact-derived detail fields."""
    d = _resolve_checkpoint_dir(run_id)
    if d is None:
        return error_response(
            "not_found", f"unknown run: {run_id}", request_id="", status=404
        )
    summary = _run_summary_from_dir(d)
    has_paper = summary.has_paper
    has_review = (d / "review_report.json").exists()
    has_idea = (d / "idea.json").exists() or (d / "science_data.json").exists()
    if has_review:
        phase = "review"
    elif has_paper or (d / ".pipeline_started").exists():
        phase = "paper"
    elif has_idea:
        phase = "bfts"
    else:
        phase = None
    return RunDetailV1(
        **summary.model_dump(),
        phase=phase,
        # rqgm capability from artifact existence only — ari.rqgm is NOT
        # imported; the view layer never imports the governance package, so
        # the flag is read off disk and never asked of the engine.
        capabilities={"rqgm": (d / "rqgm_state.json").exists()},
    )


def get_run_tree(run_id: str) -> TreeV1 | dict:
    """GET /api/v1/runs/{run_id}/tree — byte-preserving node pass-through."""
    d = _resolve_checkpoint_dir(run_id)
    if d is None:
        return error_response(
            "not_found", f"unknown run: {run_id}", request_id="", status=404
        )
    tree = build_tree_view(d)
    nodes = tree.get("nodes", []) if isinstance(tree, dict) else []
    src = _tree_source_file(d)
    revision = src.stat().st_mtime_ns if src is not None else 0
    return TreeV1(run_id=run_id, revision=revision, nodes=nodes)


def get_run_idea(run_id: str) -> RunIdeaV1 | dict:
    """GET /api/v1/runs/{run_id}/idea — pure read of ``{ckpt}/idea.json``
    (gui_refresh Wave 4c).

    The same file the legacy ``/state`` idea injection reads
    (``state_service``: ``ideas`` / ``gap_analysis`` / ``primary_metric`` /
    ``metric_rationale``); nothing else is consulted and nothing is ever
    written.  Absence semantics are honest: no file ⇒ ``present=False``
    with empty defaults (never fabricated empty strings); an unreadable or
    non-object file ⇒ ``present=False`` plus a ``degraded_reasons`` entry.
    String fields pass through only when they really are strings; ``ideas``
    keeps the on-disk dicts verbatim (non-dict entries are dropped with a
    degraded reason, never coerced).
    """
    d = _resolve_checkpoint_dir(run_id)
    if d is None:
        return error_response(
            "not_found", f"unknown run: {run_id}", request_id="", status=404
        )
    p = d / "idea.json"
    if not p.is_file():
        return RunIdeaV1(run_id=run_id, present=False)
    try:
        data = json.loads(p.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError) as e:
        log.debug("v1 idea.json parse error: %s", d.name, exc_info=True)
        return RunIdeaV1(
            run_id=run_id,
            present=False,
            degraded_reasons=[f"idea.json is not valid JSON: {e}"],
        )
    if not isinstance(data, dict):
        return RunIdeaV1(
            run_id=run_id,
            present=False,
            degraded_reasons=["idea.json top level is not an object"],
        )

    degraded: list[str] = []
    raw_ideas = data.get("ideas")
    ideas: list[dict] = []
    if isinstance(raw_ideas, list):
        ideas = [i for i in raw_ideas if isinstance(i, dict)]
        dropped = len(raw_ideas) - len(ideas)
        if dropped:
            degraded.append(f"ideas: {dropped} non-object entr(y/ies) dropped")
    elif raw_ideas is not None:
        degraded.append("ideas is not a list")

    def _opt_str(key: str) -> str | None:
        v = data.get(key)
        if v is None or isinstance(v, str):
            return v
        degraded.append(f"{key} is not a string")
        return None

    return RunIdeaV1(
        run_id=run_id,
        present=True,
        ideas=ideas,
        gap_analysis=_opt_str("gap_analysis"),
        primary_metric=_opt_str("primary_metric"),
        metric_rationale=_opt_str("metric_rationale"),
        degraded_reasons=degraded,
    )


def get_config_schema() -> ConfigSchemaV1:
    """GET /api/v1/config/schema — the canonical config field registry
    (gui_refresh task 05 Wave 3a).

    Pure metadata: the deterministic ``ari.config.field_registry`` build
    (pydantic leaf walk + hand-authored FIELD_META overlay).  No effective
    values, no filesystem, no env read; ``secret_reference`` fields carry no
    default (redacted inside ``build_field_registry``).  The import is local
    so the registry module stays inert until this endpoint is dispatched
    (viz -> ari.config is an allowed boundary edge; the reverse is not).
    """
    from ari.config.field_registry import build_field_registry

    return ConfigSchemaV1(
        fields=[ConfigFieldV1(**e) for e in build_field_registry()]
    )


# Resolver source files whose mtimes define ``resolved_at`` (newest wins).
_RESOLVER_SOURCE_FILES = (
    "workflow.yaml",
    "launch_config.json",
    "rqgm_state.json",
)


def _resolved_at_from_sources(d: Path) -> str:
    """Stable ``resolved_at``: the newest mtime of the resolver's source
    files (checkpoint-dir mtime when none exists) as UTC ISO 8601 — NEVER
    ``now()``, so repeated GETs return byte-identical manifests
    (determinism / P2)."""
    mtimes = [
        (d / name).stat().st_mtime
        for name in _RESOLVER_SOURCE_FILES
        if (d / name).exists()
    ]
    ts = max(mtimes) if mtimes else d.stat().st_mtime
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def get_resolved_config(run_id: str) -> ResolvedConfigV1 | dict:
    """GET /api/v1/runs/{run_id}/resolved-config — the resolved manifest of
    an EXISTING run, reconstructed post-hoc from its checkpoint files
    (gui_refresh task 05 Wave 3a).

    Pure read: ``ari.config.resolver.resolve_run_config`` reads checkpoint
    files plus a read-only env snapshot and never writes anything; the
    import is local so the resolver module stays inert until this endpoint
    is dispatched (viz -> ari.config is the allowed boundary direction).
    Secrets never appear in ``values`` (redacted before the digest).
    """
    d = _resolve_checkpoint_dir(run_id)
    if d is None:
        return error_response(
            "not_found", f"unknown run: {run_id}", request_id="", status=404
        )
    from ari.config.resolver import resolve_run_config

    manifest = resolve_run_config(d)
    manifest["resolved_at"] = _resolved_at_from_sources(d)
    return ResolvedConfigV1(**manifest)
