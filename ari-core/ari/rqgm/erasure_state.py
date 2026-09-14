"""Erasure-state store — the derived staleness rollup (RQGM Task 10).

``{ckpt}/rqgm_erasure_state.json`` (``docs/reference/rqgm_schemas.md``, the
``erasure_state.schema.json`` section) is the
derived, rebuildable rollup of every SelectiveErasureEvent /
FrontierRebuildEvent appended to the Task 02 audit log: "JSONL is truth,
snapshot is derived" (the ``prompt_trace`` → ``prompt_versions`` precedent).
Staleness is **logical-only**: no stored record line is ever rewritten in
place — readers derive ``stale`` as ``record_id ∈ stale_record_ids``.

The JSON write funnels through :func:`ari.checkpoint.save_erasure_state_json`
(the ``save_prompt_versions_json`` shim pattern) so byte-fixed formatting
stays owned by ``ari.checkpoint``. Absence of the file means "nothing stale,
all valid" — the ``load_prompt_trace`` absence-is-no-data discipline, which is
also how pre-feature checkpoints stay valid.

Under ``simple_bfts`` nothing constructs this store and the file is never
created — the mode leaves no RQGM residue on the checkpoint. Writer posture:
best-effort, never raises into the run loop.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

RQGM_ERASURE_STATE_FILENAME = "rqgm_erasure_state.json"
ERASURE_STATE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ErasureStateView:
    """Immutable read view of the erasure state; the stored shape is
    docs/reference/rqgm_schemas.md, "`erasure_state.schema.json`".

    Mapping values record provenance: ``stale_record_ids[rid]`` /
    ``invalid_frontier_node_ids[nid]`` hold the erasure event id that flagged
    them; ``retired_prompt_hashes[hash]`` the retirement metadata dict.
    """

    retired_prompt_hashes: dict = field(default_factory=dict)
    stale_record_ids: dict = field(default_factory=dict)
    invalid_frontier_node_ids: dict = field(default_factory=dict)
    last_erasure_event_id: str = ""
    last_rebuild_event_id: str = ""

    def is_stale(self, record_id: str) -> bool:
        return str(record_id) in self.stale_record_ids

    def stale_ids(self) -> frozenset:
        return frozenset(self.stale_record_ids)

    def invalid_node_ids(self) -> frozenset:
        return frozenset(self.invalid_frontier_node_ids)

    def retired_hashes(self) -> frozenset:
        return frozenset(self.retired_prompt_hashes)

    def to_payload(self) -> dict:
        """The byte-fixed snapshot layout: key order is part of the format,
        so the file is diffable and hash-stable across writes."""
        return {
            "schema_version": ERASURE_STATE_SCHEMA_VERSION,
            "retired_prompt_hashes": {
                k: dict(v) if isinstance(v, dict) else v
                for k, v in sorted(self.retired_prompt_hashes.items())
            },
            "stale_record_ids": dict(sorted(self.stale_record_ids.items())),
            "invalid_frontier_node_ids": dict(
                sorted(self.invalid_frontier_node_ids.items())
            ),
            "last_erasure_event_id": self.last_erasure_event_id,
            "last_rebuild_event_id": self.last_rebuild_event_id,
        }


def view_from_payload(payload: dict | None) -> ErasureStateView:
    """Absence-tolerant reader twin: ``None``/malformed ⇒ empty view."""
    d = payload if isinstance(payload, dict) else {}

    def _map(key: str) -> dict:
        raw = d.get(key)
        return dict(raw) if isinstance(raw, dict) else {}

    return ErasureStateView(
        retired_prompt_hashes=_map("retired_prompt_hashes"),
        stale_record_ids=_map("stale_record_ids"),
        invalid_frontier_node_ids=_map("invalid_frontier_node_ids"),
        last_erasure_event_id=str(d.get("last_erasure_event_id", "") or ""),
        last_rebuild_event_id=str(d.get("last_rebuild_event_id", "") or ""),
    )


def fold_event(view: ErasureStateView, event: dict) -> ErasureStateView:
    """Pure fold of one erasure/rebuild event dict into a new view.

    Idempotent (re-folding the same event changes nothing) so the snapshot is
    rebuildable from the audit JSONL in file order.
    """
    ev = event if isinstance(event, dict) else {}
    rtype = str(ev.get("record_type", ""))
    rid = str(ev.get("record_id", ""))
    if rtype == "SelectiveErasureEvent":
        retired = dict(view.retired_prompt_hashes)
        for h in ev.get("retired_prompt_hashes") or ():
            retired.setdefault(
                str(h),
                {"retirement_event_id": "", "retired_in_epoch": str(
                    ev.get("epoch_id", "") or "")},
            )
        stale = dict(view.stale_record_ids)
        for key in ("direct_stale_record_ids", "transitive_stale_record_ids"):
            for r in ev.get(key) or ():
                stale.setdefault(str(r), rid)
        invalid = dict(view.invalid_frontier_node_ids)
        for n in list(ev.get("invalidated_node_ids") or ()) + list(
            ev.get("abandoned_pending_node_ids") or ()
        ):
            invalid.setdefault(str(n), rid)
        return ErasureStateView(
            retired_prompt_hashes=retired,
            stale_record_ids=stale,
            invalid_frontier_node_ids=invalid,
            last_erasure_event_id=rid or view.last_erasure_event_id,
            last_rebuild_event_id=view.last_rebuild_event_id,
        )
    if rtype == "FrontierRebuildEvent":
        return ErasureStateView(
            retired_prompt_hashes=dict(view.retired_prompt_hashes),
            stale_record_ids=dict(view.stale_record_ids),
            invalid_frontier_node_ids=dict(view.invalid_frontier_node_ids),
            last_erasure_event_id=view.last_erasure_event_id,
            last_rebuild_event_id=rid or view.last_rebuild_event_id,
        )
    return view


class RqgmErasureStateStore:
    """Implements the :class:`ari.protocols.stores.ErasureStateStore`
    Protocol over ``{ckpt}/rqgm_erasure_state.json``.

    Stateless between calls (``checkpoint_dir`` per call, the
    ``CheckpointStore`` convention); best-effort, never raises.
    """

    def load(self, checkpoint_dir: str | Path) -> ErasureStateView:
        try:
            from ari.checkpoint import load_erasure_state_json

            return view_from_payload(load_erasure_state_json(checkpoint_dir))
        except Exception:
            log.warning("erasure state load failed; empty view",
                        exc_info=True)
            return ErasureStateView()

    def save(self, checkpoint_dir: str | Path, view: ErasureStateView) -> None:
        try:
            from ari.checkpoint import save_erasure_state_json

            save_erasure_state_json(checkpoint_dir, view.to_payload())
        except Exception:
            log.warning("erasure state save failed", exc_info=True)

    def apply_event(
        self, checkpoint_dir: str | Path, event: dict
    ) -> ErasureStateView:
        """Fold *event* into the persisted state and rewrite the snapshot."""
        view = fold_event(self.load(checkpoint_dir), event)
        self.save(checkpoint_dir, view)
        return view
