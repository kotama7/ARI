"""AdversarialCaseLog + AdversarialReplayPool (RQGM Task 06; snapshot shape:
docs/reference/rqgm_schemas.md, "`rqgm_replay_pool.schema.json`").

Persistence (both names registered in ``ari.paths``):

* ``{ckpt}/rqgm_adversarial_cases.jsonl`` — **truth**: append-only JSONL of
  every raw/defense/judgment/validated/utility/case record plus the per-node
  ``rqgm_adversarial_round`` idempotency marker (one JSON per line, module
  lock, never raises — the ``lineage_decisions.jsonl`` posture).
* ``{ckpt}/rqgm/adversarial_replay_pool.json`` — derived byte-fixed snapshot
  (rewritten at epoch boundaries) for fast load + resume; JSONL replay fills
  any tail the snapshot missed.

Pool rules: admission ONLY at epoch boundaries (GovernanceOrchestrator
step 7) for verdicts ``valid|partially_valid`` with severity ≥
``pool.min_severity``; dedup by ``(case_type, target_artifact_hash)`` —
re-validated attacks update ``last_confirmed_epoch``; bounded eviction keeps
a per-type floor and only marks ``status: "evicted"`` (nothing is ever
removed from the JSONL — selective-erasure philosophy); ``replay_view`` is
capability-checked (role ``clean_room_generator`` is denied, invariant 14)
while ``abstract_view`` is the contamination-safe FailureSummary.

Under ``simple_bfts`` nothing constructs these classes and neither file is
ever created.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from ari.rqgm.adversarial.records import (
    SEVERITY_RANK,
    AdversarialReplayCase,
    ValidatedAttackRecord,
    build_failure_summary,
    case_from_dict,
    format_case_id,
    validated_from_dict,
)

log = logging.getLogger(__name__)

ADVERSARIAL_CASES_FILENAME = "rqgm_adversarial_cases.jsonl"
RQGM_SNAPSHOT_DIRNAME = "rqgm"
REPLAY_POOL_SNAPSHOT_FILENAME = "adversarial_replay_pool.json"
REPLAY_POOL_SCHEMA_VERSION = 1

ROUND_MARKER_RECORD_TYPE = "rqgm_adversarial_round"

#: The invariant-14 capability rule: roles denied the replay_view outright,
#: because a clean-room reader may see ``abstract_view`` only.
_REPLAY_VIEW_DENIED_ROLES: frozenset = frozenset({"clean_room_generator"})

# Serialises appends (single-writer main thread + best-effort callers),
# mirroring ari.rqgm.store._LOCK.
_LOCK = threading.Lock()


class AdversarialCaseLog:
    """Append-only writer/reader over ``rqgm_adversarial_cases.jsonl``.

    Lock-guarded, absence-tolerant, never raises into the run loop
    (``append_decision_log`` posture). Raw attacks are appended BEFORE any
    defense/adjudication effect, so a crash mid-round leaves a consistent,
    replayable trail.
    """

    def __init__(self, checkpoint_dir: str | Path | None = None) -> None:
        self._ckpt = Path(checkpoint_dir) if checkpoint_dir is not None else None

    def _path(self, checkpoint_dir=None) -> Path | None:
        ckpt = Path(checkpoint_dir) if checkpoint_dir is not None else self._ckpt
        if ckpt is None:
            return None
        return ckpt / ADVERSARIAL_CASES_FILENAME

    def append(self, payload: dict, *, checkpoint_dir=None) -> bool:
        """Append one record line; ``False`` == not written (never raises)."""
        path = self._path(checkpoint_dir)
        if path is None:
            return False
        try:
            with _LOCK:
                path.parent.mkdir(parents=True, exist_ok=True)
                with open(path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(dict(payload), ensure_ascii=False) + "\n")
            return True
        except Exception:
            log.warning("adversarial case-log append failed", exc_info=True)
            return False

    def append_all(self, records, *, checkpoint_dir=None) -> int:
        """Append records (dataclasses or dicts) in order; count written."""
        written = 0
        for rec in records or ():
            payload = rec.to_dict() if hasattr(rec, "to_dict") else dict(rec)
            if self.append(payload, checkpoint_dir=checkpoint_dir):
                written += 1
        return written

    @staticmethod
    def read(checkpoint_dir: str | Path) -> list[dict]:
        """Absence-tolerant reader (raw line dicts, oldest first)."""
        path = Path(checkpoint_dir) / ADVERSARIAL_CASES_FILENAME
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

    # ── round idempotency marker: one round per (node, kind) ──────────

    def has_round_marker(
        self, node_id: str, *, kind: str = "exploration", checkpoint_dir=None,
    ) -> bool:
        """Has a round of THIS KIND already run for *node_id*?

        The marker used to be node-keyed only, so the paper-candidate
        escalation — which deliberately re-visits the BEST node at paper
        pre-flight — was suppressed by the exploration round's own marker and
        could never run on any node that had already been attacked. The kinds
        are independent idempotency domains; a legacy marker with no ``kind``
        counts as ``exploration`` so existing checkpoints keep their guarantee.
        """
        ckpt = checkpoint_dir if checkpoint_dir is not None else self._ckpt
        if ckpt is None:
            return False
        want = str(kind or "exploration")
        for line in self.read(ckpt):
            if (
                line.get("record_type") == ROUND_MARKER_RECORD_TYPE
                and str(line.get("node_id", "")) == str(node_id)
                and str(line.get("kind", "") or "exploration") == want
            ):
                return True
        return False

    def append_round_marker(
        self, node_id: str, epoch_id: str = "", *, kind: str = "exploration",
        checkpoint_dir=None,
    ) -> bool:
        return self.append(
            {
                "record_type": ROUND_MARKER_RECORD_TYPE,
                "node_id": str(node_id),
                "epoch_id": str(epoch_id),
                "kind": str(kind or "exploration"),
            },
            checkpoint_dir=checkpoint_dir,
        )

    def count_records(self, record_type: str, *, checkpoint_dir=None) -> int:
        """Line count for one record type (id-sequence continuation)."""
        ckpt = checkpoint_dir if checkpoint_dir is not None else self._ckpt
        if ckpt is None:
            return 0
        return sum(
            1
            for line in self.read(ckpt)
            if line.get("record_type") == record_type
        )

    def count_records_by_epoch(
        self, record_type: str, *, checkpoint_dir=None
    ) -> dict[str, int]:
        """Per-``epoch_id`` line counts for one record type.

        Seeds the engine's per-epoch call budget across a mid-epoch resume
        (the ``max_adversary_calls_per_epoch`` cap): the JSONL is the only
        durable record of budget already spent in the open epoch.
        """
        ckpt = checkpoint_dir if checkpoint_dir is not None else self._ckpt
        counts: dict[str, int] = {}
        if ckpt is None:
            return counts
        for line in self.read(ckpt):
            if line.get("record_type") != record_type:
                continue
            epoch_id = str(line.get("epoch_id", ""))
            counts[epoch_id] = counts.get(epoch_id, 0) + 1
        return counts


class AdversarialReplayPool:
    """The curated adjudicated-failure-case pool (snapshot shape:
    docs/reference/rqgm_schemas.md, "`rqgm_replay_pool.schema.json`").

    Consumers: Task 07's ReplayBoard (``cases()``/``select_for_replay``),
    Task 03's AttackDrivenGenerator, Task 08's clean-room summaries
    (``abstract_view`` only). All decision logic is deterministic (P2);
    admission happens ONLY at epoch boundaries via Task 05's step 7.
    """

    def __init__(self, checkpoint_dir=None, cfg=None) -> None:
        self.checkpoint_dir = (
            Path(checkpoint_dir) if checkpoint_dir is not None else None
        )
        pool_cfg = cfg
        if pool_cfg is not None:
            pool_cfg = (
                pool_cfg.get("pool")
                if isinstance(pool_cfg, dict)
                else getattr(pool_cfg, "pool", None)
            )
        self.max_cases = _read(pool_cfg, "max_cases", 64)
        self.min_severity = str(_read(pool_cfg, "min_severity", "medium"))
        self.min_per_type = _read(pool_cfg, "min_per_type", 2)
        self._cases: dict[str, AdversarialReplayCase] = {}
        self._case_seq = 0
        self._log = AdversarialCaseLog(self.checkpoint_dir)
        # Set by load() when the snapshot exists but is unreadable — the pool's
        # cap/eviction state is then unknown. Governance surfaces this instead
        # of trusting board scores over what looks like a governed, capped pool.
        self._snapshot_degraded: str | None = None

    # ── admission (epoch boundary ONLY — Task 05 step 7 calls this) ───

    def admit(self, validated, epoch_id: str = "") -> list[AdversarialReplayCase]:
        """ValidatedAttackRecords → replay cases: admitted at or above
        ``min_severity``, deduped by ``(case_type, target_artifact_hash)``."""
        admitted: list[AdversarialReplayCase] = []
        floor = SEVERITY_RANK.get(self.min_severity, 1)
        for item in validated or ():
            v = self._as_validated(item)
            if v is None:
                continue
            if v.verdict not in ("valid", "partially_valid"):
                continue
            if SEVERITY_RANK.get(v.severity, -1) < floor:
                continue
            key = self._dedup_key(v)
            existing = self._find_by_dedup(key)
            if existing is not None:
                updated = case_from_dict(
                    {**existing.to_dict(), "last_confirmed_epoch": epoch_id}
                )
                self._cases[existing.case_id] = updated
                continue
            case = AdversarialReplayCase(
                case_id=format_case_id(self._case_seq),
                case_type=v.case_type,
                validated_attack_id=v.record_id,
                source_node_id=v.source_node_id,
                severity=v.severity,
                admitted_epoch=epoch_id,
                last_confirmed_epoch=epoch_id,
                status="active",
                replay_view={
                    "artifact_refs": [v.source_node_id] if v.source_node_id else [],
                    "raw_attack_id": v.raw_attack_id,
                    "defense_id": v.defense_id,
                    "judgment_id": v.judgment_id,
                    "expected_behavior": dict(v.expected_behavior),
                },
                abstract_view=build_failure_summary(v).to_dict(),
                target_artifact_hash=v.target_artifact_hash,
            )
            self._case_seq += 1
            self._cases[case.case_id] = case
            self._log.append(case.to_dict())
            admitted.append(case)
        return admitted

    @staticmethod
    def _as_validated(item) -> ValidatedAttackRecord | None:
        if isinstance(item, ValidatedAttackRecord):
            return item
        if isinstance(item, dict):
            return validated_from_dict(item)
        to_dict = getattr(item, "to_dict", None)
        if callable(to_dict):
            return validated_from_dict(to_dict())
        return None

    @staticmethod
    def _dedup_key(v: ValidatedAttackRecord) -> tuple[str, str]:
        # (case_type, target artifact hash); hash-less records fall back to
        # the source node so a hashless re-validation still dedups.
        return (v.case_type, v.target_artifact_hash or v.source_node_id)

    def _find_by_dedup(self, key) -> AdversarialReplayCase | None:
        for case in self._cases.values():
            if (
                case.case_type,
                case.target_artifact_hash or case.source_node_id,
            ) == key:
                return case
        return None

    # ── eviction (bounded size, per-type floor; logical-only) ─────────

    def evict_to_cap(self) -> None:
        """Mark lowest-(severity, recency) actives ``evicted`` past the cap.

        Only the snapshot status changes — the JSONL history keeps every
        case line ever admitted (nothing physically deleted).
        """
        active = [c for c in self._cases.values() if c.status == "active"]
        if len(active) <= self.max_cases:
            return
        by_type: dict[str, int] = {}
        for c in active:
            by_type[c.case_type] = by_type.get(c.case_type, 0) + 1
        candidates = sorted(
            active,
            key=lambda c: (
                SEVERITY_RANK.get(c.severity, -1),
                c.last_confirmed_epoch,
                c.case_id,
            ),
        )
        excess = len(active) - self.max_cases
        for case in candidates:
            if excess <= 0:
                break
            if by_type.get(case.case_type, 0) <= self.min_per_type:
                continue  # type-coverage floor survives eviction
            self._cases[case.case_id] = case_from_dict(
                {**case.to_dict(), "status": "evicted"}
            )
            by_type[case.case_type] -= 1
            excess -= 1

    # ── selection (deterministic v1 ReplayCaseSelector) ───────────────

    def select_for_replay(self, max_cases: int) -> list[AdversarialReplayCase]:
        """≤ *max_cases* actives: severity desc, recency desc, round-robin
        over case_type (LLM selectors are a Task 11 concern)."""
        active = sorted(
            (c for c in self._cases.values() if c.status == "active"),
            key=lambda c: (
                -SEVERITY_RANK.get(c.severity, -1),
                # ISO/epoch-id strings sort lexicographically; newer == larger.
                _neg_str(c.last_confirmed_epoch),
                c.case_id,
            ),
        )
        queues: dict[str, list] = {}
        type_order: list[str] = []
        for case in active:
            if case.case_type not in queues:
                queues[case.case_type] = []
                type_order.append(case.case_type)
            queues[case.case_type].append(case)
        out: list[AdversarialReplayCase] = []
        while len(out) < max(0, int(max_cases)) and any(queues.values()):
            for case_type in type_order:
                if queues[case_type]:
                    out.append(queues[case_type].pop(0))
                    if len(out) >= max(0, int(max_cases)):
                        break
        return out

    # ── the two views: abstract for clean rooms, replay for the rest ──

    def abstract_view(self, case_id: str) -> dict:
        """FailureSummary fields only — the sole legal clean-room read."""
        case = self._cases[case_id]
        return dict(case.abstract_view)

    def replay_view(self, case_id: str, *, actor_role: str) -> dict:
        """Full replay materials; capability-checked (invariant 14)."""
        if str(actor_role) in _REPLAY_VIEW_DENIED_ROLES:
            raise PermissionError(
                f"role {actor_role!r} is denied replay_view access "
                "(invariant 14: clean-room readers get abstract_view only)"
            )
        case = self._cases[case_id]
        return dict(case.replay_view)

    # ── duck-typed surfaces for Task 05 (boards + step 7) ─────────────

    def cases(self) -> list[dict]:
        """Active case dicts (the ReplayBoard/AnchorBoard case source)."""
        return [
            c.to_dict()
            for c in sorted(self._cases.values(), key=lambda c: c.case_id)
            if c.status == "active"
        ]

    def all_cases(self) -> list[AdversarialReplayCase]:
        return sorted(self._cases.values(), key=lambda c: c.case_id)

    def append_case(self, case: dict) -> None:
        """Task 05 step-7 compatibility surface (governance-upheld refs)."""
        try:
            d = dict(case or {})
            case_id = str(d.get("case_id", "") or format_case_id(self._case_seq))
            if case_id in self._cases:
                return
            parsed = case_from_dict({**d, "case_id": case_id})
            if not parsed.case_type:
                parsed = case_from_dict(
                    {**parsed.to_dict(), "case_type": "overclaim"}
                )
            self._case_seq = max(self._case_seq + 1, len(self._cases) + 1)
            self._cases[case_id] = parsed
            self._log.append(parsed.to_dict())
        except Exception:
            log.warning("append_case failed", exc_info=True)

    # ── persistence (snapshot derived; JSONL is truth) ────────────────

    def snapshot_payload(self) -> dict:
        return {
            "schema_version": REPLAY_POOL_SCHEMA_VERSION,
            "case_seq": self._case_seq,
            "cases": [c.to_dict() for c in self.all_cases()],
        }

    def save_snapshot(self, checkpoint_dir=None) -> None:
        """Best-effort byte-fixed snapshot rewrite (never raises)."""
        ckpt = (
            Path(checkpoint_dir)
            if checkpoint_dir is not None
            else self.checkpoint_dir
        )
        if ckpt is None:
            return
        if self._snapshot_degraded:
            # The on-disk snapshot was unreadable at load, so this pool's status
            # state is not trustworthy. Overwriting would replace the (possibly
            # recoverable) corrupt file with an uncapped-looking pool, destroying
            # the evidence of degradation. Preserve it for inspection instead.
            log.warning("replay-pool snapshot NOT overwritten: %s",
                        self._snapshot_degraded)
            return
        try:
            from ari.checkpoint import save_adversarial_pool_json

            save_adversarial_pool_json(ckpt, self.snapshot_payload())
        except Exception:
            log.warning("replay-pool snapshot write failed", exc_info=True)

    @classmethod
    def load(cls, checkpoint_dir, cfg=None) -> "AdversarialReplayPool":
        """Resume path — snapshot plus JSONL replay: snapshot statuses win;
        JSONL case lines missing from the snapshot (crash tail) are
        re-added."""
        pool = cls(checkpoint_dir, cfg)
        try:
            from ari.checkpoint import load_adversarial_pool_json

            snap = load_adversarial_pool_json(checkpoint_dir)
        except Exception:
            snap = None
        # The snapshot is the ONLY carrier of per-case `status`: the JSONL keeps
        # every case at admission `status="active"` and evict_to_cap appends
        # nothing. So a snapshot that EXISTS but cannot be read is not "no
        # snapshot" — it means the cap/eviction state is lost, and replaying the
        # JSONL alone resurrects every evicted case as active (an uncapped pool).
        # Detect exists-but-unreadable and refuse to silently over-serve.
        if snap is None and checkpoint_dir is not None:
            _snap_path = (Path(checkpoint_dir) / "rqgm"
                          / "adversarial_replay_pool.json")
            if _snap_path.is_file():
                pool._snapshot_degraded = (
                    f"{_snap_path.name} exists but could not be read; per-case "
                    f"status (cap/eviction) is lost — pool may over-serve")
                log.warning("adversarial pool: %s", pool._snapshot_degraded)
        if isinstance(snap, dict):
            for d in snap.get("cases") or []:
                if isinstance(d, dict) and d.get("case_id"):
                    case = case_from_dict(d)
                    pool._cases[case.case_id] = case
            try:
                pool._case_seq = int(snap.get("case_seq", len(pool._cases)))
            except (TypeError, ValueError):
                pool._case_seq = len(pool._cases)
        for line in AdversarialCaseLog.read(checkpoint_dir):
            if line.get("record_type") != "adversarial_replay_case":
                continue
            case_id = str(line.get("case_id", ""))
            if case_id and case_id not in pool._cases:
                pool._cases[case_id] = case_from_dict(line)
        pool._case_seq = max(pool._case_seq, len(pool._cases))
        return pool


def _read(obj, name, default):
    if isinstance(obj, dict):
        raw = obj.get(name, default)
    else:
        raw = getattr(obj, name, default)
    try:
        return type(default)(raw)
    except (TypeError, ValueError):
        return default


class _neg_str(str):
    """Descending string sort key (newer epoch ids first) without inverting
    the surrounding tuple sort."""

    def __lt__(self, other) -> bool:  # pragma: no cover - trivial
        return str.__gt__(self, other)
