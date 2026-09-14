"""Idempotent launch — ``POST /api/v1/runs`` (Wave 4e, MN-10): run identity
is minted server-side and one idempotency key maps to exactly one run — see
the MN-10 migration note for the full before/after.

The canonical v1 launch path; the legacy ``POST /api/launch``
(``api_experiment.py``, pinned by frozen source-inspection contract tests)
is untouched and runs in parallel — this module is the declared thin
PARALLEL implementation reusing the one cleanly shared helper,
``services.launch_service.load_dotenv_files``.

Validation-first → identity → materialize → spawn: shared draft validation
plus the launch-only ``missing_goal``/``mode_locked`` checks reject with a
typed 400 and ZERO filesystem mutation.  ADR-09 (accepted 2026-07-27)
carved exactly two intents out of that lock — execution mode
(``ari.mode`` + ``rqgm.enabled``) and paper mode (``paper.mode`` +
``rqgm.paper.enabled``) — which a NEW run may select as pairs (a half-set
pair is 400 ``mode_interlock_mismatch``); every other ``rqgm.``/``Execution
mode`` path still rejects ``mode_locked``.  A non-default selection is
materialized BOTH ways — minimal ``ari:``/``rqgm:``/``paper:`` blocks merged
into the per-checkpoint ``workflow.yaml`` copy and the documented
``ARI_MODE``/``ARI_RQGM_ENABLED``/``ARI_PAPER_MODE``/
``ARI_RQGM_PAPER_ENABLED`` env vars — while the default (``simple_bfts`` +
``linear``) path writes and exports NOTHING and stays byte-identical.
Resume is untouched: ``{ckpt}/rqgm_state.json`` still wins
(``reconcile_resume_mode``).  Then a server-minted ``run_id = "<UTC
ts>_<slug>-<uuid4 6 hex>"`` (deterministic slug; NO LLM call, NO ``sinfo``
probe before the accepted response), the idempotency claim (create-only
``gui_store/launches/{key}.json`` write BEFORE any dir exists — a
duplicate POST replays the SAME run_id, ``idempotent_replay: true``, and
spawns nothing), materialization (``experiment.md`` from the draft goal,
bundled ``workflow.yaml`` CoW seed, legacy-compatible
``launch_config.json``, ``resolved_config.json`` — the resolved manifest
stops being a preview and becomes the run's committed configuration), then the SAME CLI subprocess as the legacy path
(``ARI_CHECKPOINT_DIR`` pinned; GUI-layer values translated via the
documented ``ENV_OVERRIDES`` family only, locked paths structurally
excluded).  Lifecycle rides run-scoped ``{ckpt}/launch_events.jsonl``
(draft → validating → accepted → spawned, monotonic ids; ``failed`` +
claim release on spawn error) — chosen over ``viz_access.jsonl``, the
ACTIVE checkpoint's HTTP access log.  A ``run`` bus event publishes after
spawn; the response never waits on the subprocess (target < 1 s), and the
GLOBAL active checkpoint is deliberately NOT switched — launching a run never
changes which checkpoint the rest of the GUI is looking at.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ...paths import PathManager, RuntimePathResolver
from .dto import RunLaunchedV1
from .errors import error_response
from .store import (KIND_LAUNCH, KIND_RUN_DRAFT, _DOC_ID_RE, GuiStore,
                    RevisionConflict)

log = logging.getLogger(__name__)

# Request body keys (RunLaunchRequestV1 mirrors this closed set).
_BODY_KEYS = ("draft_id", "display_name", "profile", "idempotency_key")

# Never env-translated: the launch owns the checkpoint dir; logs follow it.
_ENV_EXCLUDED_PATHS = frozenset({"checkpoint.dir", "logging.dir"})

# Only GUI document layers translate to env — defaults/workflow ride the
# seeded workflow.yaml, profile rides --profile, env already IS the process
# environment (and the resolver already let it win).
_GUI_LAYER_SOURCES = frozenset({"project", "template", "draft"})

# In-process idempotency fast path: (store_root, key) -> record body; the
# on-disk GuiStore document is the source of truth (survives restarts).
_replay_cache: dict[tuple[str, str], dict] = {}
_cache_lock = threading.Lock()


def _reset_for_tests() -> None:
    """Clear the in-process idempotency cache — test isolation only."""
    with _cache_lock:
        _replay_cache.clear()


def _bad(message: str, details=None) -> dict:
    return error_response(
        "invalid_request", message, details=details, request_id="", status=400
    )


def locked_launch_paths() -> frozenset[str]:
    """Registry paths whose presence in a launched draft is a 400
    ``mode_locked`` — the ConfigStudio governance lock: category
    ``Execution mode`` or the ``rqgm.`` prefix, MINUS the ADR-09 carve-out.

    ADR-09 (accepted 2026-07-27) opened exactly four leaves —
    ``field_registry.MODE_SELECTION_PATHS`` = the two mode+interlock pairs
    ``ari.mode``/``rqgm.enabled`` and ``paper.mode``/``rqgm.paper.enabled`` —
    for selection on a NEW run.  The carve-out is subtractive on purpose: the
    other ~96 ``rqgm.*`` governance/tuning leaves (epoch, kernel,
    adversarial, budgets, ...) keep rejecting, so widening the GUI's write
    surface can only happen by editing this one set.  Selecting a mode is not
    governance mutation: the RQGM registry/transition surfaces stay
    read-only.
    """
    from ari.config.field_registry import (MODE_SELECTION_PATHS,
                                           build_field_registry)

    return frozenset(
        e["path"]
        for e in build_field_registry()
        if (e["category"] == "Execution mode" or e["path"].startswith("rqgm."))
        and e["path"] not in MODE_SELECTION_PATHS
    )


def _leaf(values: dict, path: str):
    node = values
    for part in path.split("."):
        node = node[part]
    return node


def _env_overrides_from_manifest(manifest: dict) -> dict[str, str]:
    """Documented ``ARI_*`` translation of GUI-layer effective values —
    pure walk of ``field_registry.ENV_OVERRIDES`` emitting a var only when
    provenance names a GUI document layer.  Locked (governance) paths are
    excluded even if a TEMPLATE smuggled one in, and so are the four ADR-09
    mode leaves: their export is VALUE-gated (:func:`_mode_selection`), not
    provenance-gated, so a draft that merely restates the defaults exports
    nothing."""
    from ari.config.field_registry import ENV_OVERRIDES, MODE_SELECTION_PATHS

    locked = locked_launch_paths()
    out: dict[str, str] = {}
    for path in sorted(ENV_OVERRIDES):
        if (
            path in _ENV_EXCLUDED_PATHS
            or path in locked
            or path in MODE_SELECTION_PATHS
        ):
            continue
        prov = (manifest.get("provenance") or {}).get(path)
        if not prov or prov.get("source") not in _GUI_LAYER_SOURCES:
            continue
        try:
            value = _leaf(manifest["values"], path)
        except (KeyError, TypeError):  # pragma: no cover - resolver invariant
            continue
        if value is None:
            continue
        if isinstance(value, bool):
            out[ENV_OVERRIDES[path]] = "1" if value else "0"
        else:
            out[ENV_OVERRIDES[path]] = str(value)
    return out


def _mode_selection(manifest: dict) -> dict[str, object]:
    """The ADR-09 mode intents this run actually selects — ``{}`` on the
    default path.

    Reads the RESOLVED manifest values (post interlock resolution: the
    resolver mirrors ``resolve_effective_mode`` / ``resolve_paper_mode`` and
    already fell the mode back on a mismatch), and keeps a pair only when it
    is ACTIVE — ``ari.mode=ari_rqgm`` with ``rqgm.enabled=true``, or
    ``paper.mode=rqgm_archive`` with ``rqgm.paper.enabled=true``.

    Value-gated, never provenance-gated: a draft that explicitly restates
    ``simple_bfts``/``linear`` resolves to the defaults, so this returns
    ``{}`` and the launch writes NOTHING and exports NOTHING — the standing
    byte-identical simple_bfts invariant.
    """
    from ari.config.field_registry import MODE_INTERLOCK_PAIRS

    out: dict[str, object] = {}
    for mode_path, enable_path, active, _fallback in MODE_INTERLOCK_PAIRS:
        try:
            mode_v = _leaf(manifest["values"], mode_path)
            enable_v = _leaf(manifest["values"], enable_path)
        except (KeyError, TypeError):  # pragma: no cover - resolver invariant
            continue
        if mode_v == active and enable_v is True:
            out[mode_path] = mode_v
            out[enable_path] = True
    return out


def _mode_env(selection: dict) -> dict[str, str]:
    """``ARI_MODE``/``ARI_RQGM_ENABLED``/``ARI_PAPER_MODE``/
    ``ARI_RQGM_PAPER_ENABLED`` for a non-empty selection — the SAME
    documented ``ENV_OVERRIDES`` names ``apply_rqgm_env_overrides`` /
    ``apply_paper_env_overrides`` read in the spawned CLI."""
    from ari.config.field_registry import ENV_OVERRIDES

    return {
        ENV_OVERRIDES[path]: ("1" if value is True else str(value))
        for path, value in sorted(selection.items())
    }


def _merge_mode_blocks(wf_path: Path, selection: dict) -> None:
    """Merge the minimal ``ari:``/``rqgm:``/``paper:`` blocks for *selection*
    into the per-checkpoint ``workflow.yaml`` COPY (never the bundled file —
    the caller CoW-seeded it first), so the checkpoint is self-describing and
    every later phase reading ``{ckpt}/workflow.yaml`` (the paper pipeline's
    config path, the resolver's existing-checkpoint mode) agrees with the env.

    Empty selection → the file is not touched at all.  When none of the
    top-level keys exist yet (the bundled workflow.yaml has no ``ari:``,
    ``rqgm:`` or ``paper:`` block) the blocks are APPENDED, leaving every
    existing byte — comments included — untouched.  Only when a key already
    exists does it fall back to a load/deep-merge/dump round trip, which
    keeps unknown keys and ordering but not comments.
    """
    if not selection or not wf_path.exists():
        return
    import yaml

    tree: dict = {}
    for path, value in sorted(selection.items()):
        node = tree
        parts = path.split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
    text = wf_path.read_text(encoding="utf-8")
    try:
        loaded = yaml.safe_load(text) or {}
    except yaml.YAMLError:  # pragma: no cover - CoW seed is our own file
        loaded = {}
    raw = loaded if isinstance(loaded, dict) else {}
    banner = (
        "# ADR-09: execution/paper mode selected for THIS run at launch "
        "(new-run only).\n"
        "# The pair is one intent; the runtime falls back unless both agree.\n"
    )
    if not any(key in raw for key in tree):
        block = yaml.safe_dump(tree, sort_keys=True, default_flow_style=False)
        sep = "" if not text or text.endswith("\n") else "\n"
        wf_path.write_text(text + sep + banner + block, encoding="utf-8")
        return

    def _deep_merge(dst: dict, src: dict) -> dict:
        for k, v in src.items():
            if isinstance(v, dict) and isinstance(dst.get(k), dict):
                _deep_merge(dst[k], v)
            else:
                dst[k] = v
        return dst

    merged = _deep_merge(dict(raw), tree)
    dumped = yaml.safe_dump(merged, sort_keys=False, default_flow_style=False)
    wf_path.write_text(banner + dumped, encoding="utf-8")


def _slug_source(display_name: str | None, goal: str) -> str:
    """Slug text: display name, else the goal's first non-heading line
    (legacy heuristic minus the LLM fallback), else ``experiment``."""
    if display_name and display_name.strip():
        return display_name.strip()[:60]
    for line in goal.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped[:60]
    return "experiment"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _append_launch_events(ckpt: Path, states: list[dict]) -> None:
    """Append lifecycle events with per-file monotonic ``event_id``s."""
    path = ckpt / "launch_events.jsonl"
    next_id = 1
    if path.exists():
        try:
            next_id = sum(
                1 for ln in path.read_text(encoding="utf-8").splitlines() if ln
            ) + 1
        except OSError:  # pragma: no cover - best-effort
            pass
    with path.open("a", encoding="utf-8") as fh:
        for offset, ev in enumerate(states):
            fh.write(
                json.dumps(
                    {"event_id": next_id + offset,
                     "occurred_at": _now_utc().strftime(
                         "%Y-%m-%dT%H:%M:%SZ"), **ev},
                    ensure_ascii=False, sort_keys=True,
                ) + "\n"
            )


def _launched_payload(run_id: str, checkpoint_path: str, *,
                      replay: bool) -> dict:
    return RunLaunchedV1(
        run_id=run_id,
        status_url=f"/api/v1/runs/{run_id}",
        checkpoint_path=checkpoint_path,
        idempotent_replay=replay,
    ).model_dump()


def _read_replay(store: GuiStore, key: str) -> dict | None:
    """The stored record body for one idempotency key, or ``None``."""
    cache_key = (str(store.root), key)
    with _cache_lock:
        hit = _replay_cache.get(cache_key)
    if hit is not None:
        return hit
    loaded = store.read(KIND_LAUNCH, key)
    if loaded is None:
        return None
    record = loaded[0].get("body") or {}
    with _cache_lock:
        _replay_cache[cache_key] = record
    return record


def _legacy_launch_config(
    manifest: dict, *, profile: str | None, draft_id: str,
    display_name: str | None,
) -> dict:
    """The legacy display keys the dashboard reads (same names
    ``_api_launch`` writes) from the manifest + additive provenance."""
    v = manifest["values"]
    cfg: dict = {
        "llm_model": str(_leaf(v, "llm.model") or ""),
        "llm_provider": str(_leaf(v, "llm.backend") or ""),
        "profile": profile or "",
        "max_nodes": int(_leaf(v, "bfts.max_total_nodes")),
        "max_depth": int(_leaf(v, "bfts.max_depth")),
        "max_react": int(_leaf(v, "bfts.max_react_steps")),
        "timeout_node_s": int(_leaf(v, "bfts.timeout_per_node")),
        "parallel": int(_leaf(v, "bfts.max_parallel_nodes")),
        "frontier_score": str(_leaf(v, "bfts.frontier_score")),
        "composite": str(_leaf(v, "evaluator.composite")),
        "axis_mode": str(_leaf(v, "evaluator.axis_mode")),
        "allow_web": bool(_leaf(v, "bfts.allow_web")),
        # Additive (Wave 4e): provenance of THIS launch.
        "draft_id": draft_id,
        "resolved_config_digest": manifest["digest"],
    }
    if display_name:
        cfg["display_name"] = display_name
    return cfg


def _parse_request(body: dict) -> tuple[dict | None, dict | None]:
    """Request shape → ``(fields, None)`` or ``(None, 400 envelope)``."""
    unknown = sorted(set(body) - set(_BODY_KEYS))
    if unknown:
        return None, _bad(
            f"unknown request body keys: {unknown}",
            details={"unknown_keys": unknown},
        )
    draft_id = body.get("draft_id")
    if not isinstance(draft_id, str) or not draft_id:
        return None, _bad('"draft_id" must be a non-empty string')
    display_name = body.get("display_name")
    if display_name is not None and (
        not isinstance(display_name, str) or not display_name.strip()
    ):
        return None, _bad('"display_name" must be a non-empty string when given')
    key = body.get("idempotency_key")
    if key is not None and (
        not isinstance(key, str) or not _DOC_ID_RE.fullmatch(key)
    ):
        return None, _bad(
            '"idempotency_key" must match ^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$',
            details={"idempotency_key": key},
        )
    # profile's closed set is enforced by the resolver preview
    return {"draft_id": draft_id, "display_name": display_name, "key": key,
            "profile": body.get("profile")}, None


def _validate_for_launch(
    store: GuiStore, draft_id: str, profile
) -> tuple[dict | None, str | None, dict | None]:
    """Validation-first: ``(manifest, goal, None)`` or ``(None, None,
    err)`` — resolver preview + shared draft validation (including the
    ADR-09 paired-intent pass over the template+draft merge) + the
    launch-only ``mode_locked``/``missing_goal`` checks; store reads only."""
    from . import config_api

    manifest, draft_values, run_scope_values, err = (
        config_api._resolve_draft_manifest(
            draft_id, {"profile": profile} if profile is not None else {}
        )
    )
    if err is not None:
        return None, None, err  # typed 404 (unknown draft) / 400 (profile)
    errors = config_api._draft_validation_errors(
        manifest, draft_values, run_scope_values
    )
    for path in sorted(set(draft_values) & locked_launch_paths()):
        errors.append(
            {
                "path": path,
                "reason": "mode_locked",
                "message": (
                    f"{path} is governance-locked: RQGM tuning/governance "
                    "leaves are not part of the launch flow (ADR-09 opened "
                    "only the ari.mode/rqgm.enabled and paper.mode/"
                    "rqgm.paper.enabled pairs) — remove it from the draft"
                ),
            }
        )
    loaded = store.read(KIND_RUN_DRAFT, draft_id)
    draft_body = (loaded[0].get("body") or {}) if loaded else {}
    goal = draft_body.get("goal")
    if not isinstance(goal, str) or not goal.strip():
        errors.append(
            {
                "path": "goal",
                "reason": "missing_goal",
                "message": (
                    "the draft has no goal text — a launch materializes the "
                    "goal as {ckpt}/experiment.md, which the CLI requires"
                ),
            }
        )
    if errors:
        errors.sort(key=lambda e: (e["path"], e["reason"]))
        return None, None, _bad(
            f"draft {draft_id} failed launch validation "
            f"({len(errors)} error(s)): " + errors[0]["message"],
            details={"errors": errors},
        )
    return manifest, goal, None


def _claim_key(store: GuiStore, key: str, record: dict) -> dict | None:
    """Create-only claim of one idempotency key BEFORE any filesystem
    mutation.  ``None`` when this request owns the key; the replay payload
    when a racing POST won (a corrupt record propagates → typed 500)."""
    try:
        store.write(KIND_LAUNCH, record, doc_id=key, expected_revision=0)
    except RevisionConflict:
        existing = _read_replay(store, key)
        if existing is not None:
            return _launched_payload(
                str(existing.get("run_id", "")),
                str(existing.get("checkpoint_path", "")),
                replay=True,
            )
        raise
    with _cache_lock:
        _replay_cache[(str(store.root), key)] = record
    return None


def _materialize(
    workspace_root: Path, run_id: str, goal: str, manifest: dict, *,
    profile, draft_id: str, display_name, key,
) -> tuple[Path, dict]:
    """Checkpoint dir + all launch artifacts (before spawn); returns
    ``(ckpt, manifest)`` with the minted ``run_id`` filled in — the resolved
    manifest stops being a preview here and becomes the run's committed
    configuration."""
    ckpt = PathManager(workspace_root).ensure_checkpoint(run_id)
    (ckpt / "experiment.md").write_text(goal, encoding="utf-8")

    from ari.config.finder import package_config_root

    wf_src = package_config_root() / "workflow.yaml"
    if wf_src.exists():  # CoW seed — same bundled copy as the legacy launch
        shutil.copy2(str(wf_src), str(ckpt / "workflow.yaml"))
    # ADR-09: a non-default mode intent is materialized INTO the copy (the
    # bundled file is never touched); the default path leaves it byte-
    # identical to the seed.
    _merge_mode_blocks(ckpt / "workflow.yaml", _mode_selection(manifest))
    (ckpt / "launch_config.json").write_text(
        json.dumps(
            _legacy_launch_config(
                manifest, profile=profile, draft_id=draft_id,
                display_name=display_name,
            ),
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    manifest = dict(manifest)
    manifest["run_id"] = run_id
    (ckpt / "resolved_config.json").write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2)
        + "\n",
        encoding="utf-8",
    )
    _append_launch_events(
        ckpt,
        [
            {"state": "draft", "draft_id": draft_id},
            {"state": "validating", "draft_id": draft_id,
             "warnings": len(manifest.get("warnings") or [])},
            {"state": "accepted", "run_id": run_id,
             "idempotency_key": key or ""},
        ],
    )
    return ckpt, manifest


def _build_proc_env(manifest: dict, ckpt: Path) -> dict:
    """Subprocess env: inherited environ + best-effort ``.env`` fill (the
    shared legacy helper) + the documented GUI-layer ``ARI_*`` translation +
    the ADR-09 mode vars (only for a non-default selection) + the
    ``ARI_CHECKPOINT_DIR`` pin."""
    from .. import state as _st
    from ..services.launch_service import load_dotenv_files

    proc_env = os.environ.copy()
    ari_root = _st._ari_root
    load_dotenv_files(
        proc_env,
        [
            ckpt / ".env",
            ari_root / ".env",
            ari_root / "ari-core" / ".env",
            Path.home() / ".env",
        ],
        strip_quotes=False,  # the _api_launch parse variant
        swallow_errors=True,  # best-effort fill; a launch never dies on .env
    )
    proc_env.update(_env_overrides_from_manifest(manifest))
    proc_env.update(_mode_env(_mode_selection(manifest)))
    proc_env["ARI_CHECKPOINT_DIR"] = str(ckpt)
    return proc_env


def _spawn_failure(
    store: GuiStore, key, ckpt: Path, run_id: str, exc: OSError
) -> dict:
    """Failed lifecycle event + claim release (a retry may relaunch) +
    the typed 500 — a partial mutation is always RECORDED together with its
    recovery step, never silently left behind."""
    _append_launch_events(
        ckpt,
        [{"state": "failed", "run_id": run_id, "error": str(exc),
          "recovery": "checkpoint dir was materialized but nothing is "
                      "running; delete it or retry the launch"}],
    )
    if key is not None:
        try:
            store.delete(KIND_LAUNCH, key)
        except Exception:  # pragma: no cover - best-effort
            log.warning("failed to release launch key %s", key, exc_info=True)
        with _cache_lock:
            _replay_cache.pop((str(store.root), key), None)
    return error_response(
        "internal",
        f"subprocess spawn failed: {exc}",
        details={"run_id": run_id, "checkpoint_path": str(ckpt),
                 "partial_materialization": True},
        request_id="",
        retryable=True,
        status=500,
    )


def launch_run(body: dict) -> dict:
    """POST /api/v1/runs — see the module docstring for the full protocol."""
    req, err = _parse_request(body)
    if err is not None:
        return err
    draft_id, key = req["draft_id"], req["key"]
    display_name, profile = req["display_name"], req["profile"]
    store = GuiStore.from_env()

    # Idempotent replay fast path (double-click safety).
    if key is not None:
        record = _read_replay(store, key)
        if record is not None:
            return _launched_payload(str(record.get("run_id", "")),
                                     str(record.get("checkpoint_path", "")),
                                     replay=True)

    manifest, goal, err = _validate_for_launch(store, draft_id, profile)
    if err is not None:
        return err

    # Mint run identity — server-side and collision-resistant; a client
    # never supplies a run_id, and display_name only seeds the slug half.
    workspace_root = RuntimePathResolver.resolve_workspace_root()
    slug = PathManager.slugify(_slug_source(display_name, goal)) or "experiment"
    run_id = (
        f"{_now_utc().strftime('%Y%m%d%H%M%S')}_{slug}-{uuid.uuid4().hex[:6]}"
    )
    ckpt_intent = workspace_root / "checkpoints" / run_id

    if key is not None:  # claim BEFORE any filesystem mutation
        replay = _claim_key(
            store, key,
            {"run_id": run_id, "checkpoint_path": str(ckpt_intent),
             "draft_id": draft_id},
        )
        if replay is not None:
            return replay

    ckpt, manifest = _materialize(
        workspace_root, run_id, goal, manifest, profile=profile,
        draft_id=draft_id, display_name=display_name, key=key,
    )

    # Spawn the SAME CLI subprocess as the legacy path.
    cmd = ["python3", "-m", "ari.cli", "run", str(ckpt / "experiment.md")]
    if profile:
        cmd += ["--profile", str(profile)]
    proc_env = _build_proc_env(manifest, ckpt)
    log_path = ckpt / f"ari_run_{int(time.time())}.log"
    try:
        with open(log_path, "w", encoding="utf-8") as log_fh:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=log_fh,
                stderr=log_fh,
                text=True,
                cwd=str(workspace_root),
                env=proc_env,
                start_new_session=True,
            )
    except OSError as e:
        return _spawn_failure(store, key, ckpt, run_id, e)
    from .. import state as _st

    _st._running_procs[str(ckpt.resolve())] = proc
    _append_launch_events(
        ckpt, [{"state": "spawned", "run_id": run_id, "pid": proc.pid}]
    )

    from . import events

    events.publish("run", run_id, resource=f"/api/v1/runs/{run_id}",
                   payload={"lifecycle": "spawned"})
    return _launched_payload(run_id, str(ckpt), replay=False)
