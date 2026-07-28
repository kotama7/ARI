"""Checkpoint-scoped proposal store + idea.json projection (RQGM Task 03 §6.3).

Layout under ``{ckpt}/proposals/``::

    proposal_records.jsonl       # append-only truth (one record per line)
    proposal_index.json          # derived rollup: record_id → status/generator/epoch
    archive/<record_id>/…        # raw outputs, transcripts, generator configs

Writer posture (``record_prompt_use`` pattern shared by every ARI provenance
writer): lock-guarded, best-effort, never raises into the run loop. Under a
default ``simple_bfts`` run nothing constructs this store and **no**
``proposals/`` directory is ever created.

Append discipline: records are deduplicated by
:func:`ari.rqgm.proposals.records.content_key` — a retried MCP call (the
3-retry policy) that reproduces the same proposal is a no-op, never a
duplicate line.

``idea.json`` projection (plan 03 §6.4 / §8 Stage 2): in ``ari_rqgm`` this
store is the **single writer** of ``idea.json``. The projection is always
derived from the records by one function (:meth:`ProposalStore.
build_idea_projection`); it preserves the 9-key contract, pinned-in-front
merge, and the ``_pinned`` / ``_inherited_from`` / ``_root_choice`` one-shot
markers verbatim. All projection writes happen on the ``_run_loop`` main
thread under the store lock, confined to today's rewrite windows so the
``_idea_json_signature`` axis-freeze discipline holds.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from ari.rqgm.proposals.records import (
    ProposalRecord,
    content_key,
    format_proposal_record_id,
    idea_from_summary,
    record_from_dict,
    summary_from_idea,
)

log = logging.getLogger(__name__)

PROPOSALS_DIRNAME = "proposals"
PROPOSAL_RECORDS_FILENAME = "proposal_records.jsonl"
PROPOSAL_INDEX_FILENAME = "proposal_index.json"
PROPOSAL_ARCHIVE_DIRNAME = "archive"
PROPOSAL_INDEX_SCHEMA_VERSION = 1

#: The 9-key ``generate_ideas`` / ``idea.json`` top-level contract.
IDEA_JSON_KEYS: tuple[str, ...] = (
    "gap_analysis",
    "ideas",
    "primary_metric",
    "higher_is_better",
    "metric_rationale",
    "papers_analyzed",
    "n_agents",
    "discussion_rounds",
    "virsci_integration_status",
)

# One-shot markers preserved verbatim across projection rewrites.
_PRESERVED_TOP_LEVEL_MARKERS = ("_pinned", "_inherited_from", "_root_choice")

# Serialises appends/projections (single-writer main thread + best-effort
# callers), mirroring ari.rqgm.store._LOCK.
_LOCK = threading.Lock()


def _norm_title(title: str) -> str:
    """Whitespace/case-normalised title (the idea-skill dedup convention)."""
    return " ".join((title or "").lower().split())


class ProposalStore:
    """Append-only JSONL truth + archive + projection for one checkpoint.

    Bound to a checkpoint dir (unlike the per-call ``RqgmStateStore``)
    because every method operates on the same ``proposals/`` subtree and the
    router holds exactly one instance per run.
    """

    def __init__(self, checkpoint_dir: str | Path) -> None:
        self.checkpoint_dir = Path(checkpoint_dir)

    # ── paths ─────────────────────────────────────────────────────────

    @property
    def proposals_dir(self) -> Path:
        return self.checkpoint_dir / PROPOSALS_DIRNAME

    @property
    def records_path(self) -> Path:
        return self.proposals_dir / PROPOSAL_RECORDS_FILENAME

    @property
    def index_path(self) -> Path:
        return self.proposals_dir / PROPOSAL_INDEX_FILENAME

    def archive_dir(self, record_id: str) -> Path:
        return self.proposals_dir / PROPOSAL_ARCHIVE_DIRNAME / record_id

    # ── reads (absence-tolerant) ──────────────────────────────────────

    def load_all(self) -> list[ProposalRecord]:
        """Order-preserving reader; corrupt lines skipped, absence == []."""
        out: list[ProposalRecord] = []
        path = self.records_path
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
                        out.append(record_from_dict(d))
        except OSError:
            pass
        return out

    def selected(self) -> ProposalRecord | None:
        """The current directive: the LATEST record with status ``selected``
        (the JSONL is append-only, so re-ideation supersedes by ordering)."""
        chosen: ProposalRecord | None = None
        for rec in self.load_all():
            if rec.status == "selected":
                chosen = rec
        return chosen

    def content_keys(self) -> set[str]:
        return {content_key(rec) for rec in self.load_all()}

    def next_record_id(self) -> str:
        return format_proposal_record_id(len(self.load_all()))

    def count_for_epoch(self, generator: str, epoch_id: str | None) -> int:
        """Per-epoch CALL accounting for ``max_calls_per_epoch`` budgets.

        Counts dispatch heads (the first record committed per router
        dispatch, marked ``source_refs.dispatch_head``), not records — one
        VirSci call yields several records but consumes one budget unit.
        Derived from the stored records so it is deterministic across resume
        (no in-memory-only counters); a fully deduplicated retry appends
        nothing and therefore consumes no budget.
        """
        return sum(
            1
            for rec in self.load_all()
            if rec.generator == generator
            and rec.epoch_id == epoch_id
            and rec.source_refs.get("dispatch_head")
        )

    # ── writes (lock-guarded, never raise) ────────────────────────────

    def append(self, record: ProposalRecord) -> bool:
        """Append one record; content-key dedup makes retries idempotent.

        Returns ``True`` iff a new line was written. Never raises (plan 03
        §5.2: no proposal-side error may crash the search loop).
        """
        try:
            with _LOCK:
                if content_key(record) in self.content_keys():
                    log.info(
                        "proposal %s deduplicated by content key",
                        record.record_id,
                    )
                    return False
                self.proposals_dir.mkdir(parents=True, exist_ok=True)
                with open(self.records_path, "a", encoding="utf-8") as fh:
                    fh.write(
                        json.dumps(record.to_dict(), ensure_ascii=False) + "\n"
                    )
            self._write_index()
            return True
        except Exception:
            log.warning("proposal append failed", exc_info=True)
            return False

    def write_archive(self, record_id: str, name: str, payload) -> str | None:
        """Write one archive file; returns the checkpoint-relative ref.

        ``dict``/``list`` payloads are stored as JSON, strings verbatim.
        Best-effort: ``None`` == not written (archive_refs then omit it).
        """
        try:
            adir = self.archive_dir(record_id)
            adir.mkdir(parents=True, exist_ok=True)
            path = adir / name
            if isinstance(payload, (dict, list)):
                path.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            else:
                path.write_text(str(payload), encoding="utf-8")
            return str(path.relative_to(self.checkpoint_dir))
        except Exception:
            log.warning("proposal archive write failed", exc_info=True)
            return None

    def _write_index(self) -> None:
        """Best-effort rewrite of the derived ``proposal_index.json`` rollup."""
        try:
            records = self.load_all()
            index = {
                "schema_version": PROPOSAL_INDEX_SCHEMA_VERSION,
                "records": {
                    rec.record_id: {
                        "status": rec.status,
                        "generator": rec.generator,
                        "epoch_id": rec.epoch_id,
                        "content_key": content_key(rec),
                    }
                    for rec in records
                },
            }
            self.index_path.write_text(
                json.dumps(index, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            log.warning("proposal index write failed", exc_info=True)

    # ── idea.json projection (plan 03 §6.4 / §8 Stage 2) ──────────────

    def _read_existing_idea_json(self) -> dict:
        path = self.checkpoint_dir / "idea.json"
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def build_idea_projection(self, meta: dict | None = None) -> dict | None:
        """Derive the ``idea.json`` document from the records (ONE function).

        ``meta`` optionally carries the selected generator's 9-key extras
        (VirSci ``gap_analysis`` / ``papers_analyzed`` / ...); precedence is
        meta → existing idea.json values → synthesized
        (``"router:<generator>"``). Returns ``None`` when there is nothing
        to project.
        """
        records = [
            rec
            for rec in self.load_all()
            if rec.status != "superseded"
            and rec.idea_projection.get("projected", True)
        ]
        if not records:
            return None
        existing = self._read_existing_idea_json()
        pinned = [
            idea
            for idea in (existing.get("ideas") or [])
            if isinstance(idea, dict) and idea.get("_pinned")
        ]
        directive = self._directive_record(records, existing)
        others = [r for r in records if r.record_id != directive.record_id]
        others.sort(
            key=lambda r: (
                -float(r.summary.scores.get("overall", 0.0) or 0.0),
                r.record_id,
            )
        )
        pinned_keys = {_norm_title(p.get("title", "")) for p in pinned}
        projected: list[dict] = []
        for rec in [directive] + others:
            idea = idea_from_summary(rec.summary)
            if _norm_title(idea.get("title", "")) in pinned_keys:
                continue  # pinned entry already carries this direction
            projected.append(idea)
        metric = directive.summary.success_metric
        meta = meta or {}

        def _meta(key: str, default):
            if key in meta:
                return meta[key]
            if key in existing:
                return existing[key]
            return default

        doc: dict = {
            "gap_analysis": _meta("gap_analysis", ""),
            "ideas": pinned + projected,
            "primary_metric": metric.get(
                "name", existing.get("primary_metric", "")
            ),
            "higher_is_better": metric.get(
                "higher_is_better", existing.get("higher_is_better", True)
            ),
            "metric_rationale": metric.get(
                "rationale", existing.get("metric_rationale", "")
            ),
            "papers_analyzed": _meta("papers_analyzed", 0),
            "n_agents": _meta("n_agents", 0),
            "discussion_rounds": _meta("discussion_rounds", 0),
            "virsci_integration_status": _meta(
                "virsci_integration_status", f"router:{directive.generator}"
            ),
        }
        for marker in _PRESERVED_TOP_LEVEL_MARKERS:
            if marker in existing:
                doc[marker] = existing[marker]
        return doc

    def _directive_record(
        self, records: list[ProposalRecord], existing: dict
    ) -> ProposalRecord:
        """``ideas[0]`` owner: a one-shot ``_root_choice`` swap wins over the
        latest ``selected`` record (root-selection markers respected)."""
        if "_root_choice" in existing:
            ideas = existing.get("ideas") or []
            if ideas and isinstance(ideas[0], dict):
                rid = ideas[0].get("_proposal_record_id")
                for rec in records:
                    if rec.record_id == rid:
                        return rec
        chosen = None
        for rec in records:
            if rec.status == "selected":
                chosen = rec
        return chosen if chosen is not None else records[0]

    def write_idea_projection(self, meta: dict | None = None) -> bool:
        """Emit ``idea.json`` from the records (single writer in ``ari_rqgm``).

        Content-visible rewrite (``_idea_json_signature`` axis refresh keeps
        working); best-effort, never raises. Returns ``True`` iff written.
        """
        try:
            doc = self.build_idea_projection(meta)
            if doc is None:
                return False
            if not self._projection_consistent(doc):
                log.warning(
                    "idea.json projection failed the records-consistency "
                    "check; writing anyway (records are the truth)"
                )
            with _LOCK:
                (self.checkpoint_dir / "idea.json").write_text(
                    json.dumps(doc, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            return True
        except Exception:
            log.warning("idea.json projection write failed", exc_info=True)
            return False

    def _projection_consistent(self, doc: dict) -> bool:
        """Deterministic records ↔ projection check (plan 03 §10 risk 1):
        every projected idea's ``_proposal_record_id`` resolves to a stored
        record whose summary title matches."""
        by_id = {rec.record_id: rec for rec in self.load_all()}
        for idea in doc.get("ideas") or []:
            if not isinstance(idea, dict):
                return False
            rid = idea.get("_proposal_record_id")
            if rid is None:
                if idea.get("_pinned"):
                    continue  # preserved verbatim from the seed file
                return False
            rec = by_id.get(rid)
            if rec is None or rec.summary.title != idea.get("title", ""):
                return False
        return True


def import_idea_json_records(
    checkpoint_dir: str | Path,
    *,
    epoch_id: str | None = None,
    component_id: str = "legacy_idea_json",
) -> int:
    """Import an existing ``idea.json`` as ``legacy_idea_json`` records.

    Stage-1 record-only dual-write (plan 03 §8): zero consumer changes, zero
    behavior changes — ``idea.json`` itself is NOT rewritten. ``ideas[0]``
    (today's directive) imports as ``selected``, the rest as ``candidate``.
    Content-key dedup makes repeated imports idempotent. Returns the number
    of newly appended records; never raises.
    """
    try:
        path = Path(checkpoint_dir) / "idea.json"
        if not path.exists():
            return 0
        data = json.loads(path.read_text(encoding="utf-8"))
        ideas = data.get("ideas") if isinstance(data, dict) else None
        if not ideas:
            return 0
        store = ProposalStore(checkpoint_dir)
        metric = {
            "name": data.get("primary_metric", ""),
            "higher_is_better": bool(data.get("higher_is_better", True)),
            "rationale": data.get("metric_rationale", ""),
        }
        appended = 0
        for i, idea in enumerate(ideas):
            if not isinstance(idea, dict):
                continue
            record_id = store.next_record_id()
            summary = summary_from_idea(idea, record_id=record_id)
            if metric.get("name"):
                from dataclasses import replace as _replace

                summary = _replace(summary, success_metric=dict(metric))
            from datetime import datetime, timezone

            record = ProposalRecord(
                record_id=record_id,
                generator="legacy_idea_json",
                status="selected" if i == 0 else "candidate",
                epoch_id=epoch_id,
                component_id=component_id,
                role="generator",
                prompt_hash=None,
                created_at=datetime.now(timezone.utc)
                .isoformat()
                .replace("+00:00", "Z"),
                source_refs={},
                summary=summary,
                idea_projection={"projected": True, "idea_index": i},
            )
            if store.append(record):
                appended += 1
        return appended
    except Exception:
        log.warning("legacy idea.json import failed", exc_info=True)
        return 0
