"""Paper draft-archive search substrate (paper-archive Task 02,
docs/plans/ari_rqgm_paper/02).

The paper phase searches the SAME way the exploration phase searches: a
best-first tree, expanded one child at a time, pruned by hard cutoffs, ranked
by a governed score. :class:`PaperArchiveStrategy` is a standalone
``ari.protocols.search.SearchStrategy`` (satisfied structurally, like
``ari.rqgm.runtime.GovernedSearchStrategy``) over DRAFT space:

    paper_root (depth 0)
      -> K = archive.width seed drafts (depth 1, distinct framings)
        -> up to archive.refine_rounds refine children per draft (depth 2..archive.depth)

It REUSES ``bfts.py``'s pruning/counting logic and BFTS's deterministic
frontier-ranking SHAPE (``_fallback_score`` / ``_select_fallback``) but owns
the draft-tree ``expand`` / ``select`` — it does not subclass or import BFTS
internals. Cost is bounded by ``archive.max_expansions`` (-> BFTS
``max_total_nodes``) at ANY depth, because ``should_prune`` checks the total
cap BEFORE the depth cap (bfts.py:501-503) — never by flattening the topology.

No co-evolution here (Tasks 03/04): the writer prompt population and the
reviewer utility are frozen inputs for one paper epoch. This module owns only
the search substrate and the ``paper_draft_archive.jsonl`` draft population.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING

from ari.orchestrator.node import Node, NodeLabel

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ari.memory.client import MemoryClient

log = logging.getLogger(__name__)

PAPER_DRAFT_ARCHIVE_FILENAME = "paper_draft_archive.jsonl"
PAPER_DRAFT_ARCHIVE_SCHEMA_VERSION = 1

# Diversity-history window — the same 20-run window as BFTS (bfts.py:248).
_FRAMING_WINDOW = 20


def archive_node_budget(knobs) -> int:
    """The §5.4.1 per-epoch draft-population bound:
    ``min(width * (1 + refine_rounds), max_expansions)``.

    This is the value :class:`PaperArchiveStrategy` uses as its effective BFTS
    ``max_total_nodes`` (Task 06 §5.6): the tree is capped by the node budget at
    ANY depth, because ``should_prune`` retires a frontier node the moment the
    total-node cutoff binds (bfts.py:501-502) BEFORE the depth test. Independent
    of ``archive.depth`` — a deeper tree redistributes the same M nodes, it never
    multiplies them (no ``width^depth`` term). At the default config the two
    terms coincide (4·(1+2) = 12 = max_expansions); the ``min`` makes the model's
    formula the ACTUAL cap when they diverge. Pure, duck-typed over a typed model
    OR a raw dict (``paper_expansion_budget`` delegates here for both)."""
    def _g(name: str, default: int) -> int:
        v = knobs.get(name, default) if isinstance(knobs, dict) else getattr(
            knobs, name, default)
        try:
            return max(0, int(v))
        except (TypeError, ValueError):
            return default
    return min(_g("width", 4) * (1 + _g("refine_rounds", 2)),
               _g("max_expansions", 12))


class PaperArchiveStrategy:
    """Best-first draft tree over draft space (satisfies ``SearchStrategy``).

    One ``paper_root`` (depth 0), up to ``width`` seed drafts (depth 1), each
    expandable into up to ``refine_rounds`` refine/variant children down to
    ``depth``. Reuses ``bfts.py``'s ``should_prune`` cutoffs (total cap before
    depth cap); owns an LLM-free deterministic frontier selection and a real
    framing-keyed ``diversity_bonus``.
    """

    def __init__(self, knobs, *, root_task: Node) -> None:
        # knobs = cfg.rqgm.paper.archive
        self.width = int(getattr(knobs, "width", 4))            # K -> root branch factor
        self.depth = int(getattr(knobs, "depth", 3))           # -> max_depth
        self.refine_rounds = int(getattr(knobs, "refine_rounds", 2))   # draft branch factor
        self.max_expansions = int(getattr(knobs, "max_expansions", 12))  # raw config knob
        # The EFFECTIVE per-epoch node cap = min(width·(1+refine_rounds),
        # max_expansions) (§5.6). Using the raw max_expansions alone would let
        # the cost model's formula diverge from the real bound; this is the
        # single source of truth both the strategy and paper_expansion_budget use.
        self.node_budget = archive_node_budget(knobs)          # -> BFTS max_total_nodes
        self._root = root_task                                 # paper_root Node
        self._expansions = 0                                   # per-epoch budget accounting
        self._fanout: dict[str, int] = {}                      # parent_id -> children created
        self._framings: list[str] = []                         # recent framing keys (diversity)

    # ── fan-out shape ────────────────────────────────────────────────────
    def _fanout_cap(self, node: Node) -> int:
        """The root fans out into ``width`` framings; a draft fans out into
        ``refine_rounds`` refinements/variants. Cost is capped by
        ``max_expansions`` regardless (§5.1) — these only shape WHERE the
        budget may land."""
        return self.width if node.depth == 0 else self.refine_rounds

    # ── reused BFTS logic (total/depth cutoff), specialized to the tree ──
    def should_prune(self, node: Node, *, current_total: int) -> bool:
        """BFTS.should_prune's clauses in BFTS's ORDER (bfts.py:481-514): the
        TOTAL cap (bfts.py:501) binds BEFORE the depth cap (bfts.py:503) —
        exactly why depth costs nothing (§5.1) — plus one archive-specific
        clause (the per-parent fan-out cap)."""
        if current_total >= 1 + self.node_budget:      # per-epoch budget = max_total_nodes
            return True
        if node.depth >= self.depth:                   # depth==3 -> refine chain ends
            return True
        if self._fanout.get(node.id, 0) >= self._fanout_cap(node):
            return True                                # this parent's fan-out is spent
        m = node.metrics or {}
        if m.get("_sterile") is True:
            return True
        if m.get("_valid_for_frontier", True) is False:   # selective erasure (Task 10 reuse)
            return True
        return False

    def select_best_to_expand(
        self, frontier: list[Node], experiment_goal: str, memory: "MemoryClient"
    ) -> Node:
        """REAL best-first frontier selection — the thing that makes this a
        search. bfts.py:512 is the LLM analog; this is its DETERMINISTIC
        sibling, shaped like ``_select_fallback`` / ``_fallback_score``:

        1. Seeds first: the root outranks every draft until ``width`` framings
           exist — an unsampled framing beats a marginal refine of a sampled
           one, and that is what ``width`` buys (§5.1).
        2. Then rank every expandable DRAFT by the governed paper_reviewer
           composite in ``metrics["_scientific_score"]`` (Task 04) +
           ``diversity_bonus``.

        No LLM: the ranking key is already a governed score, so asking a model
        to re-rank it would only buy nondeterminism (P2) and cost. ``max``
        keeps the FIRST maximal element, so ties resolve to creation order
        (P2).
        """
        if not frontier:
            raise ValueError("No frontier nodes to select from")
        if (
            self._fanout.get(self._root.id, 0) < self.width
            and any(n is self._root for n in frontier)
        ):
            return self._root
        return max(
            frontier,
            key=lambda n: (
                float((n.metrics or {}).get("_scientific_score") or 0.0)
                + self.diversity_bonus(n)
            ),
        )

    def select_next_node(
        self, candidates: list[Node], experiment_goal: str, memory: "MemoryClient"
    ) -> Node:
        """DETERMINISTIC (P2): pick the next not-yet-run draft in creation
        order. No LLM — draft candidates carry a fixed ``seed`` / ``refine``
        direction, so the semantic pick BFTS uses for experiments buys nothing
        here."""
        if not candidates:
            raise ValueError("No candidates to select from")
        return candidates[0]

    def expand(
        self, node: Node, *args, existing_children: list[Node] | None = None, **kwargs
    ) -> list[Node]:
        """ONE child per call (bfts.py:643 invariant preserved). Creates a
        draft placeholder ``Node``; ``PaperDraftExecutor.run()`` does the real
        generation."""
        if self._expansions >= self.node_budget:
            return []                                  # per-epoch budget spent
        idx = self._fanout.get(node.id, 0)
        if idx >= self._fanout_cap(node) or node.depth >= self.depth:
            return []                                  # fan-out full / chain at max depth
        child = Node(
            id=f"draft_{idx}" if node.depth == 0 else f"{node.id}.r{idx + 1}",
            parent_id=node.id,
            depth=node.depth + 1,
            label=NodeLabel.DRAFT,
            ancestor_ids=list(node.ancestor_ids) + [node.id],
        )
        child.original_direction = "seed" if node.depth == 0 else "refine"
        node.children.append(child.id)
        self._fanout[node.id] = idx + 1
        self._expansions += 1
        return [child]

    def record_run(self, node: Node) -> None:
        """Diversity accounting, mirroring ``BFTS.record_run`` (bfts.py:262)
        but keyed on the draft's FRAMING (``writer_prompt_hash``, §5.4.5)
        instead of ``NodeLabel``: every draft is ``NodeLabel.DRAFT``, so the
        label carries no signal here."""
        if node is None:
            return
        key = (node.metrics or {}).get("_framing_key") or ""
        if key:
            self._framings.append(str(key))
            self._framings = self._framings[-_FRAMING_WINDOW:]

    def expansion_count(self, node_id: str) -> int:
        return self._fanout.get(node_id, 0)

    def diversity_bonus(self, node: Node) -> float:
        """REAL, and the same contract as bfts.py:285-310: +0.05 when this
        draft's framing is at most half as frequent as the most common framing
        among recently-run drafts, 0.0 otherwise. Deterministic (P2) — a pure
        function of run history, no LLM, no clock."""
        if not self._framings:
            return 0.0
        key = (node.metrics or {}).get("_framing_key") or ""
        if not key:
            return 0.0
        counts = Counter(self._framings)
        return 0.05 if counts.get(str(key), 0) * 2 <= max(counts.values()) else 0.0


# ─────────────────────────────────────────────────────────────────────────────
# paper_draft_archive.jsonl — the scored draft population (§6.1)
# ─────────────────────────────────────────────────────────────────────────────


def _warn_on_seed_collapse(checkpoint_dir, record: dict) -> None:
    """R1's collapse detector (plan 02 §5.4/R1): warn when an incoming ``seed``
    record's ``tex_sha256`` matches a seed already in the archive.

    ``(writer_prompt_hash, decode_seed)`` is R1's named mitigation against "K
    candidates are near-identical and the archive degrades to K copies". With
    ``n == 1`` writer prompts by design (doc 03), `decode_seed` is the ONLY
    diversity lever left, and litellm's `seed` is provider-dependent and
    best-effort — so a backend that ignores it collapses the archive silently
    while every record still advertises a distinct seed. This is the detector
    that makes the collapse visible instead. Observability only: never raises,
    never blocks a write (a duplicate draft is legal, just worth knowing about).

    Scoped to a DISTINCT ``decode_seed``, which is what R1's claim is about: two
    candidates that differ only by seed producing identical bytes is the
    collapse. The SAME seed reproducing the same text is determinism working as
    designed (a resume, or a re-minted node id across rounds), and warning on it
    would bury the real signal in false positives.
    """
    if str(record.get("kind")) != "seed":
        return
    sha = str(record.get("tex_sha256") or "")
    if not sha:
        return
    seed = record.get("decode_seed")
    try:
        for prior in read_paper_draft_archive(checkpoint_dir):
            if (str(prior.get("kind")) == "seed"
                    and str(prior.get("tex_sha256") or "") == sha
                    and prior.get("decode_seed") != seed):
                log.warning(
                    "paper draft seed collapse: %s (decode_seed=%s) produced "
                    "BYTE-IDENTICAL .tex to seed %s (decode_seed=%s) "
                    "[tex_sha256=%s]. Seed diversity is not being honoured — "
                    "the archive is degrading toward K copies of one draft "
                    "(plan 02 R1); litellm `seed` is provider-dependent, so "
                    "check the backend honours it.",
                    record.get("node_id"), record.get("decode_seed"),
                    prior.get("node_id"), prior.get("decode_seed"), sha[:12],
                )
                return
    except Exception:
        log.debug("seed-collapse check failed (best-effort)", exc_info=True)


def write_paper_draft_record(checkpoint_dir: str | Path, record: dict) -> None:
    """Append one draft record to ``{ckpt}/paper_draft_archive.jsonl``.

    Append-only, byte-fixed (``ensure_ascii=False``, one compact object per
    line). Best-effort — a record-write failure must never break the paper
    phase (fail-open, migration §8.5)."""
    _warn_on_seed_collapse(checkpoint_dir, record)
    try:
        path = Path(checkpoint_dir) / PAPER_DRAFT_ARCHIVE_FILENAME
        line = json.dumps(record, ensure_ascii=False, sort_keys=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        log.warning(
            "failed to append draft record to %s under %s",
            PAPER_DRAFT_ARCHIVE_FILENAME, checkpoint_dir, exc_info=True,
        )


def mark_paper_draft_flags(
    checkpoint_dir: str | Path, node_id: str, *,
    epoch_id: str | None = None, **flags: bool,
) -> None:
    """Best-effort update of a draft record's boolean flags (``is_best_belief``
    / ``compiled``, §5.5). Reads the whole archive, marks the ONE record the
    flags describe, and rewrites the file byte-fixed. Never raises into the run.

    **Exactly one record carries each flag (§6.1).** Node ids are re-minted every
    round by a fresh ``PaperArchiveStrategy``, so several records can share a
    ``node_id``; this marked EVERY match and cleared nothing, so ONE compile
    stamped ``compiled: true`` on two records and a reader counting compiles or
    resolving "the best belief" got two answers to a question with one. The LAST
    matching record wins — the archive is append-only, so the last write is the
    current state of that node — and the flag is CLEARED on every other record
    that carries it, which is what makes "exactly one" true rather than merely
    intended.

    ``epoch_id`` is optional. Legacy/final-round callers may omit it and retain
    the last-write-wins behavior; the P0-P4 shared-archive comparison supplies
    it because a no-erasure winner may come from an earlier epoch. Duplicate
    ``node_id``s can still exist within one epoch, so last-write-wins remains
    load-bearing even with the filter."""
    path = Path(checkpoint_dir) / PAPER_DRAFT_ARCHIVE_FILENAME
    records = read_paper_draft_archive(checkpoint_dir)
    if not records:
        return
    matches = [
        i for i, r in enumerate(records)
        if str(r.get("node_id")) == str(node_id)
        and (
            epoch_id is None
            or str(r.get("epoch_id") or "") == str(epoch_id)
        )
    ]
    if not matches:
        return
    winner = matches[-1]
    changed = False
    for i, r in enumerate(records):
        if i == winner:
            if any(r.get(k) != v for k, v in flags.items()):
                changed = True
            r.update(flags)
            continue
        # Clear the flags this call OWNS on every other record. Only flags set
        # True are exclusive, and only a record that actually carries one is
        # touched — an unrelated key is never invented on a record.
        for k, v in flags.items():
            if v and r.get(k):
                r[k] = False
                changed = True
    if not changed:
        return
    try:
        lines = [
            json.dumps(r, ensure_ascii=False, sort_keys=True) for r in records
        ]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        log.warning(
            "failed to rewrite %s under %s", PAPER_DRAFT_ARCHIVE_FILENAME,
            checkpoint_dir, exc_info=True,
        )


def record_paper_draft_manuscript_evaluation(
    checkpoint_dir: str | Path,
    node_id: str,
    *,
    epoch_id: str,
    evaluation: dict,
) -> None:
    """Attach deterministic Manuscript Complete diagnostics to one draft.

    Draft creation remains append-first so an interruption never loses the
    generated artifact.  This targeted, last-record-wins rewrite then binds the
    preliminary hard-gate result to the exact epoch/node record.  A failed
    write is deliberately *not* hidden: enforce-mode eligibility relies on
    these diagnostics, and the caller verifies that the record round-trips.
    """

    path = Path(checkpoint_dir) / PAPER_DRAFT_ARCHIVE_FILENAME
    records = read_paper_draft_archive(checkpoint_dir)
    matches = [
        index
        for index, record in enumerate(records)
        if str(record.get("node_id") or "") == str(node_id)
        and str(record.get("epoch_id") or "") == str(epoch_id)
    ]
    if not matches:
        raise ValueError("paper draft record is absent for manuscript evaluation")
    records[matches[-1]].update(dict(evaluation))
    try:
        path.write_text(
            "\n".join(
                json.dumps(record, ensure_ascii=False, sort_keys=True)
                for record in records
            )
            + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise ValueError("paper draft manuscript evaluation could not be persisted") from exc

    persisted = read_paper_draft_archive(checkpoint_dir)
    matching = [
        record
        for record in persisted
        if str(record.get("node_id") or "") == str(node_id)
        and str(record.get("epoch_id") or "") == str(epoch_id)
    ]
    if not matching or any(
        matching[-1].get(key) != value for key, value in evaluation.items()
    ):
        raise ValueError("paper draft manuscript evaluation did not round-trip")


def erase_paper_reviewer_utilities(
    checkpoint_dir: str | Path,
    reviewer_prompt_hash: str,
    *,
    replacement_epoch_id: str,
    replacement_prompt_hash: str,
) -> list[dict]:
    """Logically erase scores produced by one displaced paper reviewer.

    RQGM selective erasure removes the displaced evaluator's utility rows, not
    the underlying artifacts.  We preserve each draft record for provenance
    but mark its score ineligible for archive selection.  The operation is
    deterministic and idempotent and returns the newly-staled record refs.
    """

    old_hash = str(reviewer_prompt_hash or "")
    if not old_hash:
        return []
    path = Path(checkpoint_dir) / PAPER_DRAFT_ARCHIVE_FILENAME
    records = read_paper_draft_archive(checkpoint_dir)
    if not records:
        return []
    changed: list[dict] = []
    for rec in records:
        if str(rec.get("reviewer_prompt_hash") or "") != old_hash:
            continue
        if bool(rec.get("review_score_stale", False)):
            continue
        rec["review_score_stale"] = True
        rec["stale_at_epoch"] = str(replacement_epoch_id or "")
        rec["replacement_reviewer_prompt_hash"] = str(
            replacement_prompt_hash or ""
        )
        rec["is_best_belief"] = False
        changed.append({
            "epoch_id": str(rec.get("epoch_id") or ""),
            "node_id": str(rec.get("node_id") or ""),
        })
    if not changed:
        return []
    try:
        lines = [
            json.dumps(r, ensure_ascii=False, sort_keys=True) for r in records
        ]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        log.warning(
            "failed to persist paper reviewer utility erasure under %s",
            checkpoint_dir, exc_info=True,
        )
        return []
    return changed


def epoch_draft_records(
    checkpoint_dir: str | Path, epoch_id: str
) -> list[dict]:
    """The persisted draft records for ONE epoch, content-hash verified (§8.6).

    Scoped to ``epoch_id`` because each round rebuilds under freshly adopted
    prompts — a prior epoch's records must never restore into this one. Last-wins
    on a duplicate ``node_id`` (the archive is append-only, so the last write is
    that node's current state; a pre-existing archive may hold duplicates from a
    re-invocation predating the resume path).

    The content-hash gate is what makes resume "content-hash safe" (§8.6): a
    record is kept only if the bytes at its own ``tex_path`` still hash to its
    recorded ``tex_sha256``. A missing or mismatched file DROPS the record so the
    node regenerates rather than restoring a node whose artifact is gone or
    stale. Returned in first-recorded (creation) order — the order ``_seed_index``
    and the diversity window depend on for P2.
    """
    by_node: dict[str, dict] = {}
    order: list[str] = []
    for r in read_paper_draft_archive(checkpoint_dir):
        if str(r.get("epoch_id", "")) != str(epoch_id):
            continue
        nid = str(r.get("node_id") or "")
        if not nid:
            continue
        if nid not in by_node:
            order.append(nid)
        by_node[nid] = r                       # last write wins
    out: list[dict] = []
    ckpt = Path(checkpoint_dir)
    for nid in order:
        rec = by_node[nid]
        rel = str(rec.get("tex_path") or "")
        want = str(rec.get("tex_sha256") or "")
        if not rel or not want:
            continue
        try:
            got = hashlib.sha256(
                (ckpt / rel).read_text(encoding="utf-8").encode("utf-8")
            ).hexdigest()
        except OSError:
            continue                           # artifact gone => regenerate
        if got != want:
            continue                           # bytes moved => regenerate
        out.append(rec)
    return out


def restore_archive_round(
    checkpoint_dir: str | Path, strat: "PaperArchiveStrategy", root: Node,
    epoch_id: str,
) -> list[Node]:
    """Rebuild one epoch's draft tree from ``paper_draft_archive.jsonl`` and
    PRIME ``strat`` so the round continues rather than restarts (§8.6, §9 Resume;
    Task 06 §8.5/§9.11 "a resume must not re-fund the round").

    Every record is a node (§6.1), so the records rebuild the tree: ``node_id`` /
    ``parent_draft_id`` restore the EDGES, ``review_score`` / ``writer_prompt_hash``
    restore ``_scientific_score`` / ``_framing_key``, and the restored frontier
    hands ``select_best_to_expand`` the same state it had before the interrupt —
    a best-first continuation, not a positional cursor (§8.6 rejects those).

    Priming the strategy is what stops a re-fund AND a re-mint: ``_expansions``
    restores the epoch's spent budget, and ``_fanout`` restores the per-parent
    child count so ``expand`` mints the NEXT index instead of re-minting an id
    that already exists. ``record_run`` replays the diversity window.

    Returns the restored nodes in creation order (empty on a fresh checkpoint —
    absence-tolerant, so a first run is unaffected).
    """
    recs = epoch_draft_records(checkpoint_dir, epoch_id)
    if not recs:
        return []
    ckpt = Path(checkpoint_dir)
    nodes: list[Node] = []
    by_id: dict[str, Node] = {}
    for rec in recs:
        nid = str(rec.get("node_id"))
        kind = str(rec.get("kind") or "seed")
        parent_id = str(rec.get("parent_draft_id") or "") or root.id
        try:
            refine_pass = int(rec.get("refine_pass") or 0)
        except (TypeError, ValueError):
            refine_pass = 0
        parent = by_id.get(parent_id)
        ancestors = (list(parent.ancestor_ids) + [parent.id]) if parent is not None \
            else [root.id]
        n = Node(
            id=nid,
            parent_id=parent_id,
            depth=refine_pass + 1,             # mirrors executor: refine_pass = depth - 1
            label=NodeLabel.DRAFT,
            ancestor_ids=ancestors,
        )
        n.original_direction = kind
        n.artifacts = [str(ckpt / str(rec.get("tex_path")))]
        n.has_real_data = True
        n.metrics = {
            "_scientific_score": float(rec.get("review_score") or 0.0),
            "_framing_key": str(rec.get("writer_prompt_hash") or ""),
            "_paper_epoch_id": str(rec.get("epoch_id") or ""),
            "_reviewer_prompt_hash": str(
                rec.get("reviewer_prompt_hash") or ""
            ),
            "_valid_for_frontier": not bool(
                rec.get("review_score_stale", False)
            ) and not bool(rec.get("manuscript_hard_disqualified", False)),
            "_manuscript_hard_disqualified": bool(
                rec.get("manuscript_hard_disqualified", False)
            ),
            "_manuscript_input_fingerprint": str(
                rec.get("manuscript_input_fingerprint") or ""
            ),
            "_manuscript_binding_digest": str(
                rec.get("manuscript_binding_digest") or ""
            ),
        }
        if parent is not None:
            parent.children.append(n.id)
        elif parent_id == root.id:
            root.children.append(n.id)
        nodes.append(n)
        by_id[nid] = n
    # Prime the strategy: spent budget + per-parent fan-out + diversity window.
    strat._expansions = len(nodes)
    for n in nodes:
        pid = n.parent_id or root.id
        strat._fanout[pid] = strat._fanout.get(pid, 0) + 1
    for n in nodes:
        strat.record_run(n)
    return nodes


def read_paper_draft_archive(checkpoint_dir: str | Path) -> list[dict]:
    """Absence-tolerant read: an empty list when the file is missing or
    unparseable (a linear paper run leaves no archive behind)."""
    path = Path(checkpoint_dir) / PAPER_DRAFT_ARCHIVE_FILENAME
    if not path.exists():
        return []
    out: list[dict] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                out.append(obj)
    except OSError:
        return out
    return out
