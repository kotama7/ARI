"""RqgmStateStore + EpochTransaction + ImmutableAuditLog (RQGM Task 02).

Checkpoint-scoped persistence for the RQGM state layer (plan 02 §5.1):

* ``{ckpt}/rqgm_transitions.jsonl`` — **source of truth**: append-only,
  hash-chained event log of every epoch open/close, registration, and status
  change. Small by design (registry/epoch events only) so resume replay is
  cheap (§5.7).
* ``{ckpt}/rqgm_audit.jsonl`` — the **ImmutableAuditLog** (§5.9). This task
  owns the file: fixed name, identical append-only hash-chained envelope with
  an independent per-file chain. Task 05 writes the governance content;
  Task 04 verifies the chain and never writes.
* ``{ckpt}/epoch_state.json`` / ``{ckpt}/rqgm_registry.json`` — derived
  rewrite-whole snapshots (fast-path reads). Disposable: validated against
  replay on load and rebuilt on mismatch, so a torn snapshot can never
  corrupt governance state.

Transaction discipline (§5.6): status changes happen ONLY inside an
epoch-boundary :class:`EpochTransaction` (prepare … commit), single-writer
(the ``_run_loop`` main thread). Crash recovery: on replay, events after the
last ``epoch_transaction_prepare`` without a matching commit are ignored.
An ``emergency_quarantine`` forces an immediate boundary; legacy schema-v1
checkpoints may still contain a standalone mid-epoch event and remain
replayable.

Writer posture (shared with every ARI provenance writer): lock-guarded,
no-op without a resolvable checkpoint dir (run pin), never raises into the
run loop. Deterministic decision logic — timestamps are envelope metadata
only, never hashed (P2).

Under ``rqgm.enabled=false`` / ``simple_bfts`` nothing constructs this store
and none of the four files is ever created (§5.8).
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field, replace
from pathlib import Path

from ari.rqgm.events import (
    EMERGENCY_EVENT_TYPE,
    EVENT_TYPES,
    TransitionEvent,
    event_from_line_dict,
    expected_event_hash,
    finalize_event,
    format_transition_id,
)
from ari.rqgm.registry import (
    ComponentRegistry,
    GovernedPromptRegistry,
    apply_registry_event,
)
from ari.rqgm.state import (
    EpochState,
    epoch_state_from_payload,
    epoch_state_payload,
    freeze_epoch,
)

log = logging.getLogger(__name__)

RQGM_TRANSITIONS_FILENAME = "rqgm_transitions.jsonl"
RQGM_AUDIT_FILENAME = "rqgm_audit.jsonl"
EPOCH_STATE_FILENAME = "epoch_state.json"
RQGM_REGISTRY_FILENAME = "rqgm_registry.json"

RQGM_REGISTRY_SCHEMA_VERSION = 1

#: Reserved directory name for Task 07 evolved prompt text (§5.1); nothing
#: writes it in Task 02.
RQGM_PROMPTS_DIRNAME = "rqgm_prompts"

# Event types a transaction may add (prepare/commit are transaction-managed).
_TX_ADDABLE: frozenset[str] = frozenset(EVENT_TYPES) - {
    "epoch_transaction_prepare",
    "epoch_transaction_commit",
}

# Serialises appends from the (single-writer) loop vs. best-effort callers.
_LOCK = threading.Lock()


class EventLogIntegrityError(RuntimeError):
    """The physical event sequence cannot be safely replayed or extended."""


def _resolve_checkpoint_dir(checkpoint_dir: str | Path | None) -> Path | None:
    """Explicit arg first, then the ``ARI_CHECKPOINT_DIR`` run pin (like
    ``ari.prompts._provenance``); ``None`` == no-op writer."""
    if checkpoint_dir is not None:
        return Path(checkpoint_dir)
    try:
        from ari.paths import PathManager

        return PathManager.checkpoint_dir_from_env()
    except Exception:
        return None


def _read_chain_tail(path: Path) -> tuple[int, str]:
    """Return ``(next_event_seq, last_event_hash)`` over the PHYSICAL lines.

    The hash chain covers every line ever appended (including events later
    ignored by crash recovery) — Task 04 verifies the physical chain.
    """
    if not path.exists():
        return 0, ""
    events = _read_events(path)
    _require_valid_chain(events, path)
    return len(events), events[-1].event_hash if events else ""


def _read_events(
    path: Path, *, allow_torn_tail: bool = False
) -> list[TransitionEvent]:
    """Order-preserving reader.

    Replay may ignore one unterminated, malformed final segment as a crashed
    append.  Writers never do: they refuse to extend a physically torn log.
    """
    out: list[TransitionEvent] = []
    if not path.exists():
        return out
    try:
        raw_lines = path.read_bytes().splitlines(keepends=True)
        for index, raw_line in enumerate(raw_lines):
            terminated = raw_line.endswith((b"\n", b"\r"))
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError as exc:
                if (
                    allow_torn_tail
                    and index == len(raw_lines) - 1
                    and not terminated
                ):
                    break
                raise EventLogIntegrityError(
                    f"{path.name}: malformed JSON event line"
                ) from exc
            if not isinstance(d, dict):
                raise EventLogIntegrityError(
                    f"{path.name}: event line is not an object"
                )
            out.append(event_from_line_dict(d))
    except OSError as exc:
        raise EventLogIntegrityError(f"{path.name}: unreadable event log") from exc
    return out


def _require_valid_chain(events: list[TransitionEvent], path: Path) -> None:
    """Fail closed on identifier, digest, predecessor, or schema changes."""
    previous = ""
    for seq, event in enumerate(events):
        expected_id = f"evt_{seq:06d}"
        if event.event_id != expected_id:
            raise EventLogIntegrityError(
                f"{path.name}: expected {expected_id}, got {event.event_id!r}"
            )
        if event.schema_version not in (1, 2):
            raise EventLogIntegrityError(
                f"{path.name}: unsupported event schema {event.schema_version}"
            )
        if event.prev_event_hash != previous:
            raise EventLogIntegrityError(
                f"{path.name}: predecessor mismatch at {event.event_id}"
            )
        if event.event_hash != expected_event_hash(event):
            raise EventLogIntegrityError(
                f"{path.name}: digest mismatch at {event.event_id}"
            )
        previous = event.event_hash


def _append_chained(path: Path, events: list[TransitionEvent]) -> bool:
    """Finalize + append *events* to *path* under the module lock.

    Returns True iff all lines were written; never raises (plan 02 §5.6:
    a state-layer failure degrades to "epoch continues").
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _LOCK:
            next_seq, prev_hash = _read_chain_tail(path)
            with open(path, "a", encoding="utf-8") as fh:
                for ev in events:
                    fin = finalize_event(
                        ev, event_seq=next_seq, prev_event_hash=prev_hash
                    )
                    fh.write(
                        json.dumps(fin.to_line_dict(), ensure_ascii=False) + "\n"
                    )
                    next_seq += 1
                    prev_hash = fin.event_hash
        return True
    except Exception:
        log.warning("RQGM append to %s failed", path.name, exc_info=True)
        return False


def committed_events(events: list[TransitionEvent]) -> list[TransitionEvent]:
    """Crash-recovery filter (plan 02 §5.6): drop every event that belongs to
    a prepare without a matching commit. Events outside any transaction
    (initial ``epoch_open`` and legacy ``emergency_quarantine``) are committed
    as-is."""
    out: list[TransitionEvent] = []
    pending: list[TransitionEvent] | None = None
    pending_id = ""
    for ev in events:
        if ev.event_type == "epoch_transaction_prepare":
            # A new prepare abandons any unterminated predecessor.
            pending = [ev]
            pending_id = ev.transaction_id or str(
                ev.payload.get("transition_id", "")
            )
        elif ev.event_type == "epoch_transaction_commit":
            commit_id = ev.transaction_id or str(
                ev.payload.get("transition_id", "")
            )
            if pending is not None and commit_id == pending_id:
                pending.append(ev)
                out.extend(pending)
                pending = None
                pending_id = ""
            # commit without prepare: ignore (malformed tail)
        elif pending is not None:
            event_id = ev.transaction_id or pending_id
            if event_id == pending_id:
                pending.append(ev)
        else:
            out.append(ev)
    return out


@dataclass
class RqgmRuntimeState:
    """In-memory rollup of the replayed event log (plan 02 §7).

    ``last_event_hash`` / ``next_event_seq`` describe the PHYSICAL file tail
    (chain continuation), not the committed subset.
    """

    epoch: EpochState | None = None
    components: ComponentRegistry = field(default_factory=ComponentRegistry)
    prompts: GovernedPromptRegistry = field(default_factory=GovernedPromptRegistry)
    last_event_hash: str = ""
    next_event_seq: int = 0


class EpochTransaction:
    """Context manager over one epoch-boundary transaction (plan 02 §5.6).

    ``__enter__`` appends ``epoch_transaction_prepare``; :meth:`add` appends
    validated events immediately (single-writer, so interleaving is
    impossible); a clean exit appends ``epoch_transaction_commit``. On an
    exception the commit is withheld — replay then discards the whole tail,
    which is the crash-recovery abort path.
    """

    def __init__(
        self,
        store: "RqgmStateStore",
        checkpoint_dir: str | Path,
        transition_id: str,
    ) -> None:
        self._store = store
        self._ckpt = Path(checkpoint_dir)
        self.transition_id = transition_id
        self._entered = False
        self._committed = False

    def __enter__(self) -> "EpochTransaction":
        self._entered = True
        # ``append_events`` RETURNS False on failure and never raises (see its
        # docstring). Discarding that bool let a transaction whose events never
        # reached rqgm_transitions.jsonl still be marked committed, so the audit
        # log listed sanctions/retirements that were never applied and the
        # snapshot-vs-replay integrity check agreed — because the replay was
        # missing the same event. ``open_epoch`` in this module already checks
        # the bool; this was an omission, not house style.
        if not self._store.append_events(
            self._ckpt,
            [
                TransitionEvent(
                    event_type="epoch_transaction_prepare",
                    transaction_id=self.transition_id,
                    payload={"transition_id": self.transition_id},
                )
            ],
        ):
            raise RuntimeError(
                f"epoch transaction {self.transition_id}: could not write the "
                f"prepare event; refusing to open a transaction whose events "
                f"cannot be persisted"
            )
        return self

    def add(self, event: TransitionEvent) -> None:
        """Append one registry/epoch event inside the transaction.

        The write API that makes invariant 10 hold at the storage layer:
        prepare/commit are transaction-managed and unknown event types are
        rejected outright.
        """
        if not self._entered or self._committed:
            raise RuntimeError("EpochTransaction is not open")
        if event.event_type not in _TX_ADDABLE:
            raise ValueError(
                f"event type {event.event_type!r} cannot be added to an "
                f"epoch-boundary transaction"
            )
        event = replace(event, transaction_id=self.transition_id)
        if not self._store.append_events(self._ckpt, [event]):
            raise RuntimeError(
                f"epoch transaction {self.transition_id}: could not persist "
                f"{event.event_type!r}; aborting so replay discards the partial "
                f"tail rather than reporting an applied change that is not there"
            )

    def commit(self) -> None:
        if not self._entered or self._committed:
            raise RuntimeError("EpochTransaction is not open")
        if not self._store.append_events(
            self._ckpt,
            [
                TransitionEvent(
                    event_type="epoch_transaction_commit",
                    transaction_id=self.transition_id,
                    payload={"transition_id": self.transition_id},
                )
            ],
        ):
            raise RuntimeError(
                f"epoch transaction {self.transition_id}: could not write the "
                f"commit marker; the transaction is NOT committed (replay "
                f"ignores events after a prepare with no matching commit)"
            )
        self._committed = True

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is None and not self._committed:
            self.commit()
        # On exception: no commit — the tail is ignored at replay (abort).
        return False


class RqgmStateStore:
    """Implements the :class:`ari.protocols.stores.EpochStore` Protocol.

    Stateless between calls (``checkpoint_dir`` passed per call, matching
    ``CheckpointStore``); the JSONL event log is the single source of truth
    and every mutation path funnels through :meth:`append_events` under the
    module lock.
    """

    # ── EpochStore Protocol surface ───────────────────────────────────

    def load_state(
        self, checkpoint_dir: str | Path
    ) -> RqgmRuntimeState | None:
        """Replay the event log, then validate the derived snapshots against
        it and rebuild them on mismatch (plan 02 §5.1/§5.7). A checkpoint
        with no RQGM files returns ``None`` — "RQGM never ran", not an
        error."""
        state = self.replay(checkpoint_dir)
        if state is None:
            return None
        try:
            from ari.checkpoint import (
                load_epoch_state_json,
                load_rqgm_registry_json,
            )

            es = load_epoch_state_json(checkpoint_dir)
            rg = load_rqgm_registry_json(checkpoint_dir)
            in_sync = (
                rg is not None
                and rg.get("registry_version") == state.prompts.registry_version()
                and rg.get("as_of_event_hash") == state.last_event_hash
            )
            if state.epoch is not None:
                in_sync = (
                    in_sync
                    and es is not None
                    and es.get("epoch_id") == state.epoch.epoch_id
                    and es.get("status") == state.epoch.status
                    and es.get("epoch_fingerprint")
                    == state.epoch.epoch_fingerprint
                )
            if not in_sync:
                log.warning(
                    "RQGM snapshots missing or out of sync with %s; rebuilding",
                    RQGM_TRANSITIONS_FILENAME,
                )
                self.save_snapshots(checkpoint_dir, state)
        except Exception:
            log.warning("RQGM snapshot validation failed", exc_info=True)
        return state

    def append_events(
        self, checkpoint_dir: str | Path, events: list[TransitionEvent]
    ) -> bool:
        """Low-level chained append to ``rqgm_transitions.jsonl``.

        Storage primitive — policy callers are :class:`EpochTransaction`
        (boundary) and :meth:`append_mid_epoch_event` (emergency). Returns
        ``False`` (never raises) on failure or when no checkpoint dir is
        resolvable.
        """
        ckpt = _resolve_checkpoint_dir(checkpoint_dir)
        if ckpt is None:
            return False
        return _append_chained(ckpt / RQGM_TRANSITIONS_FILENAME, list(events))

    def save_snapshots(
        self, checkpoint_dir: str | Path, state: RqgmRuntimeState
    ) -> None:
        """Best-effort rewrite of the two derived rollups (never raises)."""
        try:
            from ari.checkpoint import (
                save_epoch_state_json,
                save_rqgm_registry_json,
            )

            if state.epoch is not None:
                snap = epoch_state_payload(state.epoch)
                snap["created_at"] = state.epoch.created_at
                save_epoch_state_json(checkpoint_dir, snap)
            save_rqgm_registry_json(
                checkpoint_dir,
                {
                    "schema_version": RQGM_REGISTRY_SCHEMA_VERSION,
                    "registry_version": state.prompts.registry_version(),
                    "as_of_event_hash": state.last_event_hash,
                    "components": [
                        e.to_dict()
                        for _, e in sorted(state.components.entries().items())
                    ],
                    "prompts": [
                        e.to_dict()
                        for _, e in sorted(state.prompts.entries().items())
                    ],
                },
            )
        except Exception:
            log.warning("RQGM snapshot write failed", exc_info=True)

    def replay(self, checkpoint_dir: str | Path) -> RqgmRuntimeState | None:
        """Rebuild registries + EpochState from ``rqgm_transitions.jsonl``.

        Applies the crash-recovery filter first, then folds the committed
        events in file order. Returns ``None`` when the log is absent.
        """
        ckpt = _resolve_checkpoint_dir(checkpoint_dir)
        if ckpt is None:
            return None
        path = ckpt / RQGM_TRANSITIONS_FILENAME
        if not path.exists():
            return None
        events = _read_events(path, allow_torn_tail=True)
        _require_valid_chain(events, path)
        components: dict = {}
        prompts: dict = {}
        epoch: EpochState | None = None
        for ev in committed_events(events):
            if ev.event_type == "epoch_open":
                payload = ev.payload.get("epoch_state")
                if isinstance(payload, dict):
                    epoch = epoch_state_from_payload(
                        payload, created_at=ev.ts_iso
                    )
            elif ev.event_type == "epoch_close":
                if epoch is not None and ev.payload.get("epoch_id") == epoch.epoch_id:
                    from dataclasses import replace as _replace

                    epoch = _replace(epoch, status="closed")
            else:
                apply_registry_event(
                    components, prompts, ev.event_type, ev.payload,
                    created_at=ev.ts_iso,
                )
        next_seq = len(events)
        last_hash = events[-1].event_hash if events else ""
        return RqgmRuntimeState(
            epoch=epoch,
            components=ComponentRegistry(components),
            prompts=GovernedPromptRegistry(prompts),
            last_event_hash=last_hash,
            next_event_seq=next_seq,
        )

    # ── transaction / lifecycle API ───────────────────────────────────

    def begin_transaction(
        self, checkpoint_dir: str | Path, transition_id: str
    ) -> EpochTransaction:
        return EpochTransaction(self, checkpoint_dir, transition_id)

    def apply_transition(
        self,
        checkpoint_dir: str | Path,
        transition_id: str,
        events: list[TransitionEvent],
    ) -> RqgmRuntimeState | None:
        """Convenience: run *events* through one prepare..commit transaction
        and return the replayed state (plan 02 §5.3's sole mutation path)."""
        with self.begin_transaction(checkpoint_dir, transition_id) as tx:
            for ev in events:
                tx.add(ev)
        state = self.replay(checkpoint_dir)
        if state is not None:
            self.save_snapshots(checkpoint_dir, state)
        return state

    def append_mid_epoch_event(
        self, checkpoint_dir: str | Path, event: TransitionEvent
    ) -> bool:
        """Refuse all new mid-epoch writes.

        Kept as a compatibility surface for callers that should now migrate
        to :meth:`run_boundary`; T16 is transactionally committed at an
        emergency boundary.
        """
        raise ValueError(
            f"mid-epoch event {event.event_type!r} refused; "
            f"{EMERGENCY_EVENT_TYPE!r} must force an epoch boundary"
        )

    def open_epoch(
        self,
        checkpoint_dir: str | Path,
        cfg,
        *,
        node_count: int,
        run_id: str = "",
        prior: RqgmRuntimeState | None = None,
        scientific_identity: dict | None = None,
    ) -> RqgmRuntimeState | None:
        """Open the initial epoch (``epoch_000``, or the next sequence when a
        closed prior epoch exists). Appends one bare ``epoch_open`` event —
        committed-by-default under the recovery rule — then replays and
        rewrites snapshots (plan 02 §5.6 freeze steps 3-4)."""
        base = prior if prior is not None else RqgmRuntimeState()
        if base.epoch is None:
            seq, prev_id = 0, None
        else:
            seq, prev_id = base.epoch.epoch_seq + 1, base.epoch.epoch_id
        new_epoch = freeze_epoch(
            base,
            cfg,
            epoch_seq=seq,
            node_count=node_count,
            run_id=run_id,
            previous_epoch_id=prev_id,
            opened_by_transition_id=None,
            checkpoint_dir=checkpoint_dir,
            scientific_identity=scientific_identity,
        )
        ok = self.append_events(
            checkpoint_dir,
            [
                TransitionEvent(
                    event_type="epoch_open",
                    payload={"epoch_state": epoch_state_payload(new_epoch)},
                )
            ],
        )
        if not ok:
            return prior
        state = self.replay(checkpoint_dir)
        if state is not None:
            self.save_snapshots(checkpoint_dir, state)
        return state

    def run_boundary(
        self,
        checkpoint_dir: str | Path,
        state: RqgmRuntimeState,
        cfg,
        *,
        node_count: int,
        run_id: str = "",
        registry_events: list[TransitionEvent] | tuple = (),
        utility_policy_override: dict | None = None,
        scientific_identity: dict | None = None,
    ) -> RqgmRuntimeState | None:
        """Execute the §5.6 epoch-boundary transaction.

        *registry_events* are the adopt/sanction/retire events provided by
        Task 09's RegistryTransitionEngine and validated by Task 04's kernel
        — empty in v1. The new epoch is frozen over the registries AS OF the
        end of the transaction. Returns the post-commit replayed state (the
        prior *state* on append failure — epoch continues).
        """
        ep = state.epoch
        if ep is None:
            raise ValueError("run_boundary requires an open epoch")
        tid = format_transition_id(ep.epoch_seq, ep.epoch_seq + 1)
        # Freeze over the post-transition registries: apply the provided
        # events to copies first (the log is still the only mutation path —
        # these copies never escape).
        comp_map = state.components.entries()
        prompt_map = state.prompts.entries()
        for ev in registry_events:
            apply_registry_event(comp_map, prompt_map, ev.event_type, ev.payload)
        tentative = RqgmRuntimeState(
            epoch=ep,
            components=ComponentRegistry(comp_map),
            prompts=GovernedPromptRegistry(prompt_map),
        )
        new_epoch = freeze_epoch(
            tentative,
            cfg,
            epoch_seq=ep.epoch_seq + 1,
            node_count=node_count,
            run_id=run_id or ep.run_id,
            previous_epoch_id=ep.epoch_id,
            opened_by_transition_id=tid,
            checkpoint_dir=checkpoint_dir,
            utility_policy_override=utility_policy_override,
            scientific_identity=(
                scientific_identity
                if scientific_identity is not None
                else dict(getattr(ep, "scientific_identity", {}) or {})
            ),
        )
        with self.begin_transaction(checkpoint_dir, tid) as tx:
            for ev in registry_events:
                tx.add(ev)
            tx.add(
                TransitionEvent(
                    event_type="epoch_close",
                    payload={
                        "epoch_id": ep.epoch_id,
                        "transition_id": tid,
                        "node_count_at_close": int(node_count),
                    },
                )
            )
            tx.add(
                TransitionEvent(
                    event_type="epoch_open",
                    payload={
                        "transition_id": tid,
                        "epoch_state": epoch_state_payload(new_epoch),
                    },
                )
            )
        new_state = self.replay(checkpoint_dir)
        if new_state is None or new_state.epoch is None:
            return state
        self.save_snapshots(checkpoint_dir, new_state)
        return new_state


class ImmutableAuditLog:
    """``{ckpt}/rqgm_audit.jsonl`` — the RQGM ImmutableAuditLog (§5.9).

    This class owns the FILE: fixed name, append-only, the same hash-chained
    envelope as ``rqgm_transitions.jsonl`` with an independent per-file
    chain. The governance record *content* appended through it is Task 05's;
    chain verification is Task 04's (``validate_audit_log_integrity``).
    Writer posture: lock-guarded, no-op without a run pin, never raises.
    """

    def __init__(self, checkpoint_dir: str | Path | None = None) -> None:
        self._ckpt = Path(checkpoint_dir) if checkpoint_dir is not None else None

    def append(
        self,
        event_type: str,
        payload: dict,
        *,
        checkpoint_dir: str | Path | None = None,
    ) -> bool:
        """Append one governance record line; ``False`` == not written."""
        ckpt = _resolve_checkpoint_dir(
            checkpoint_dir if checkpoint_dir is not None else self._ckpt
        )
        if ckpt is None:
            return False
        return _append_chained(
            ckpt / RQGM_AUDIT_FILENAME,
            [TransitionEvent(event_type=str(event_type), payload=dict(payload))],
        )

    @staticmethod
    def read(checkpoint_dir: str | Path) -> list[dict]:
        """Absence-tolerant reader (raw line dicts, oldest first)."""
        path = Path(checkpoint_dir) / RQGM_AUDIT_FILENAME
        out: list[dict] = []
        if not path.exists():
            return out
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(d, dict):
                        out.append(d)
        except OSError:
            pass
        return out
