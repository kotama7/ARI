"""Selective-erasure awareness over the published RQGM rollup.

ARI's constitutional runtime can logically erase a research node. Nothing is
deleted — the node, its records and its measurements stay on disk, auditable —
and what is withdrawn is the STANDING of the judgment attached to them: the
generator that proposed the direction, or the utility policy that scored it,
was retired. The stale node-id set is published for exactly this kind of
consumer in ``{checkpoint_dir}/rqgm_erasure_state.json``.

This module is the memory layer's reader for that file. It imports nothing
from ``ari`` (the skill is a standalone MCP package), makes no LLM call (the
skill's determinism charter), and degrades to "nothing is stale" on every
failure. Absence of the file is the normal case for a non-RQGM checkpoint, so
the whole module is inert there.

**Semantics: annotate, do not hide.** Erasure condemns the standing of a
judgment, not the facts an experiment measured, so a caller that deliberately
asks for an erased node's memory receives it LABELLED (:data:`ERASED_KEY` /
:data:`ERASURE_EVENT_KEY` / :data:`ERASURE_NOTE_KEY`) rather than silently
emptied — an invalidated measurement is still the honest record of what was
tried. Paths that PUSH memory into a decision instead HARD-EXCLUDE: the
paper's grounded claim lists (:func:`drop_erased`, applied inside
``context_builder.build_verified_context`` so the MCP tool and the in-process
funnel filter the same call), the per-node "established conclusions"
injection, and best-node selection — the latter two in ari-core, before they
reach this skill. ``limitations`` deliberately keeps erased entries, labelled:
a direction that was later invalidated is exactly what a limitations section
should record.

The annotation is applied in the BACKENDS rather than in the MCP dispatcher,
so an in-process caller of the backend sees the same labelled data the tool
surface does.

Honest scope: this is a statement about PROVENANCE, not about text that has
been re-authored. A surviving node that reads a labelled entry and restates it
in its own summary produces an unmarked record on a clean lineage; nothing
propagates the marker through re-authorship.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
from pathlib import Path
from typing import Any, Iterable

log = logging.getLogger(__name__)

#: The derived rollup ARI publishes for cross-component consumers
#: (docs/plans/ari_rqgm/10 §3/§6). Absence == nothing is stale.
ERASURE_STATE_FILENAME = "rqgm_erasure_state.json"

#: Rollup field naming the logically erased nodes: ``{node_id: event_id}``.
#: Pinned by a cross-package contract test — ari-core writes it, we read it.
INVALID_NODE_IDS_FIELD = "invalid_frontier_node_ids"

#: Highest rollup schema this reader understands. A newer file degrades to
#: "nothing is stale" rather than risking a wrong label.
SUPPORTED_SCHEMA_VERSION = 1

ERASED_KEY = "erased"
ERASURE_EVENT_KEY = "erasure_event_id"
ERASURE_NOTE_KEY = "erasure_note"

#: Fixed explanatory label. The consumer is usually an LLM, so the marker says
#: what the verdict means rather than only that one exists.
ERASURE_NOTE = (
    "This node was logically erased by ARI governance: the component that "
    "produced or scored it was retired, so the STANDING of the judgment here "
    "(its research direction, its score) is withdrawn. The recorded "
    "measurements themselves were not retracted. Do not treat this as an "
    "established conclusion and do not ground a paper claim on it."
)

#: path -> (content digest, {node_id: event_id}). Keyed on the BYTES, not on
#: ``stat``: the rollup is tiny, the writer is a non-atomic ``write_text``, and
#: a same-size rewrite inside one clock tick shares ``st_mtime_ns`` (and
#: ``st_ctime_ns`` — same coarse clock), so a timestamp signature can serve a
#: stale set for the life of this long-lived stdio process. Reading a few KB
#: per call is cheaper than being wrong; the cache still skips the JSON parse.
_CACHE: dict[str, tuple[str, dict]] = {}
_LOCK = threading.Lock()


def _rollup_path(checkpoint_dir: "str | Path | None") -> Path | None:
    try:
        if checkpoint_dir is not None:
            return Path(checkpoint_dir) / ERASURE_STATE_FILENAME
        from ari_skill_memory.config import load_config
        return load_config().checkpoint_dir / ERASURE_STATE_FILENAME
    except Exception:
        return None


def erased_nodes(checkpoint_dir: "str | Path | None" = None) -> dict:
    """``{node_id: erasure_event_id}`` for logically erased nodes.

    ``{}`` whenever the rollup is absent, unreadable, malformed, or written by
    a newer schema. Re-read when the file changes (the runtime rewrites it at
    epoch boundaries, and this skill is a long-lived stdio process), otherwise
    served from cache.
    """
    path = _rollup_path(checkpoint_dir)
    if path is None:
        return {}
    try:
        blob = path.read_bytes()
    except OSError:
        with _LOCK:
            _CACHE.pop(str(path), None)
        return {}
    key = str(path)
    digest = hashlib.sha256(blob).hexdigest()
    with _LOCK:
        cached = _CACHE.get(key)
        if cached is not None and cached[0] == digest:
            return dict(cached[1])
    try:
        data = json.loads(blob.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("rollup is not an object")
        version = data.get("schema_version", SUPPORTED_SCHEMA_VERSION)
        # Degrade on ANY version that is not an int we understand — a string
        # or float "99" must not slip past into v1 semantics and produce a
        # label this reader cannot justify.
        if not isinstance(version, int) or isinstance(version, bool) \
                or version > SUPPORTED_SCHEMA_VERSION:
            log.warning(
                "%s carries schema_version %r (this reader understands int "
                "<= %s) — treating nothing as erased rather than risking a "
                "wrong label",
                ERASURE_STATE_FILENAME, version, SUPPORTED_SCHEMA_VERSION,
            )
            out: dict = {}
        else:
            raw = data.get(INVALID_NODE_IDS_FIELD) or {}
            if isinstance(raw, dict):
                out = {str(nid): str(evt or "") for nid, evt in raw.items()}
            elif isinstance(raw, (list, tuple, set)):
                out = {str(nid): "" for nid in raw}
            else:
                # A str would iterate character-by-character and mark nodes
                # literally named "n"/"1" — `drop_erased` would then fail
                # UNSAFE (dropping live ancestors) against this module's
                # degrade-to-nothing posture.
                raise ValueError(
                    f"{INVALID_NODE_IDS_FIELD} is {type(raw).__name__}, "
                    "expected an object or list"
                )
    except Exception:
        log.warning("unreadable %s — treating nothing as erased",
                    ERASURE_STATE_FILENAME, exc_info=True)
        out = {}
    with _LOCK:
        _CACHE[key] = (digest, out)
    return dict(out)


def annotate_entry(entry: dict, event_id: str) -> dict:
    """Return *entry* labelled as erased (a copy; the store is untouched).

    The marker is written BOTH at the top level and inside ``metadata``,
    because consumers re-project entries down to a fixed key set — the
    pipeline's ``nodes_tree.json`` enrichment and the viz memory endpoint both
    keep only ``{text, metadata, ts}``, so a top-level-only marker would be
    silently stripped before it reached the reader it is meant to warn."""
    out = dict(entry)
    out[ERASED_KEY] = True
    out[ERASURE_EVENT_KEY] = event_id
    out[ERASURE_NOTE_KEY] = ERASURE_NOTE
    md = out.get("metadata")
    md = dict(md) if isinstance(md, dict) else {}
    md[ERASED_KEY] = True
    md[ERASURE_EVENT_KEY] = event_id
    md[ERASURE_NOTE_KEY] = ERASURE_NOTE
    out["metadata"] = md
    return out


def annotate_many(
    entries: Iterable[dict],
    *,
    node_id: "str | None" = None,
    checkpoint_dir: "str | Path | None" = None,
) -> list:
    """Label whichever entries belong to an erased node.

    ``node_id`` names the owning node when the entries do not carry one
    (``get_node_memory`` returns entries for a single, implicit node);
    otherwise each entry's own ``node_id`` decides.
    """
    items = list(entries or ())
    erased = erased_nodes(checkpoint_dir)
    if not erased or not items:
        return items
    out = []
    for entry in items:
        if not isinstance(entry, dict):
            out.append(entry)
            continue
        nid = str(entry.get("node_id") or node_id or "")
        event_id = erased.get(nid)
        out.append(annotate_entry(entry, event_id) if event_id is not None
                   else entry)
    return out


def drop_erased(
    node_ids: Iterable[str],
    checkpoint_dir: "str | Path | None" = None,
) -> list:
    """Hard-exclude erased ids — for the PUSH path (grounded paper claims),
    where an erased node's evidence must not reach a claim at all."""
    ids = [str(n) for n in (node_ids or ()) if n]
    erased = erased_nodes(checkpoint_dir)
    if not erased:
        return ids
    kept = [n for n in ids if n not in erased]
    if len(kept) != len(ids):
        log.info(
            "verified context: dropped %d erased ancestor(s) — grounded "
            "claims never rest on a withdrawn judgment",
            len(ids) - len(kept),
        )
    return kept


def annotate_payload(
    payload: Any,
    key: str,
    *,
    node_id: "str | None" = None,
    checkpoint_dir: "str | Path | None" = None,
) -> Any:
    """Annotate ``payload[key]`` in place-safe fashion; pass anything else
    through untouched (a backend error envelope must survive verbatim)."""
    if not isinstance(payload, dict) or not isinstance(payload.get(key), list):
        return payload
    out = dict(payload)
    out[key] = annotate_many(
        payload[key], node_id=node_id, checkpoint_dir=checkpoint_dir)
    return out
