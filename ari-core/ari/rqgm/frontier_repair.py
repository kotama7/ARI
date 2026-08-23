"""FrontierRepairEngine + selective erasure (RQGM Task 10).

Implements the "selective erasure is logical-only" invariant
(``docs/concepts/rqgm_architecture.md``, "Key invariants"): after Task 09's
RegistryTransitionEngine commits an :class:`~ari.rqgm.transition_engine.
EpochTransition` with a non-empty ``retirements`` list, every record produced
by — or transitively, materially dependent on — a retired ``prompt_hash`` is
contaminated evidence and must stop influencing BFTS frontier scoring.

Design principles:

* **P-A logical-only erasure** — nothing is physically deleted or rewritten.
  Staleness lives in (i) SelectiveErasureEvent / FrontierRebuildEvent lines
  appended to the Task 02 audit log, (ii) the derived
  ``rqgm_erasure_state.json`` rollup (:mod:`ari.rqgm.erasure_state`), and
  (iii) additive ``Node.metrics`` sentinels (``_stale``,
  ``_valid_for_frontier``, ``_stale_reason``, ``_erasure_event_id``)
  persisted through ``tree.json``.
* **P-B slot-scoped** — retiring a reviewer stales that reviewer's records
  and their downstream utility consequences, never unrelated work on the
  same node and never a node's descendants automatically.
* **P-C deterministic** — :func:`trace_dependents` and
  :func:`rebuild_frontier` are pure functions of (records, nodes, erasure
  state, config); no LLM, no randomness, no wall clock in any decision (P2).
* **P-D no cross-epoch re-scoring** — utilities are recomputed from
  surviving inputs under the ORIGINAL epoch's frozen weights (stored by
  value in every UtilityRecord, Task 06); when that is impossible the node
  becomes frontier-invalid instead (erase, don't re-scale).
* **P-E simple_bfts untouched** — this module is only imported by the
  ``ari_rqgm`` runtime; under ``simple_bfts`` no sentinel key is ever
  written, so the additive ``should_prune`` clause can never fire.

Failure posture (a documented deviation from the fail-open hook convention,
scoped to the boundary where no node is in flight): kernel validation failure ⇒
conservative re-repair (flagged nodes dropped outright), still failing ⇒
drain-only degradation (``halted_expansion``; the run finishes pending work
but expands no further). The run never crashes.
"""

from __future__ import annotations

import json
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from ari.rqgm.erasure_state import (
    ErasureStateView,
    RqgmErasureStateStore,
    fold_event,
)

log = logging.getLogger(__name__)

SELECTIVE_ERASURE_RECORD_TYPE = "SelectiveErasureEvent"
FRONTIER_REBUILD_RECORD_TYPE = "FrontierRebuildEvent"

#: Audit-log event types (the payload is the §6 record dict).
SELECTIVE_ERASURE_EVENT_TYPE = "selective_erasure"
FRONTIER_REBUILD_EVENT_TYPE = "frontier_rebuild"

#: Kernel-authored events: no LLM prompt behind them (§6 envelope rule).
FRONTIER_REPAIR_COMPONENT_ID = "frontier_repair_engine"
FRONTIER_REPAIR_ROLE = "kernel"

#: ``status`` vocabulary shared by both event records (§6).
REPAIR_STATUSES: tuple[str, ...] = (
    "applied",
    "conservative",
    "halted_expansion",
)

#: Node.metrics sentinel keys (additive, persisted through tree.json; never
#: written in simple_bfts — §6).
STALE_KEY = "_stale"
VALID_FOR_FRONTIER_KEY = "_valid_for_frontier"
STALE_REASON_KEY = "_stale_reason"
ERASURE_EVENT_KEY = "_erasure_event_id"

#: The epoch utility policy a node's score was formed under (RQGM Task 14;
#: written by ``ari.rqgm.utility_evolution.UtilityPolicyStamp``
#: at the ``wrap_node_executor`` seam, never under ``simple_bfts``).
#:
#: Why the node and not just the record: ``apply_utility_penalty`` returns
#: ``None`` when the penalty is 0, so only attacked-and-penalised nodes carry
#: a UtilityRecord. Matching retirements against records ALONE would
#: invalidate the penalised subset and leave every unattacked node holding an
#: old-policy score — a random half-rewrite, worse than none, because the
#: frontier would then mix two incomparable score regimes with no marker
#: saying which is which. P1 says the ENTIRE score is rewritten.
UTILITY_POLICY_HASH_KEY = "_utility_policy_hash"

#: ``_stale_reason`` vocabulary — diagnostic provenance only (no reader
#: branches on it), one value per invalidation cause: a retired
#: generator/router, a retired utility policy, or the conservative sweep of
#: everything still reachable past the trace depth cap.
GENERATOR_RETIRED_REASON = "generator_retired"
UTILITY_INVALIDATED_REASON = "utility_invalidated"
DEPTH_CAP_REASON = "trace_depth_exceeded"

#: Retired role → the reason stamped on nodes it invalidates.
_ROLE_STALE_REASONS: dict = {
    "generator": GENERATOR_RETIRED_REASON,
    "router": GENERATOR_RETIRED_REASON,
    "utility_policy": UTILITY_INVALIDATED_REASON,
}

#: Roles whose stale records INVALIDATE the carrying node: the node's
#: very direction (generator/router) or its score's policy (utility_policy)
#: came from the retired prompt — no recompute can launder that.
INVALIDATE_ROLES: frozenset = frozenset(
    {"generator", "router", "utility_policy"}
)

#: Roles whose stale records trigger utility RECOMPUTE from surviving inputs
#: under the original epoch's frozen weights — an evaluator's retirement
#: changes what the evidence says, not what the node set out to do.
RECOMPUTE_ROLES: frozenset = frozenset(
    {"reviewer", "adversary", "defender", "judge"}
)

#: The materiality table: *(consumer record type, referenced record type)*
#: pairs designated background CONTEXT — a citation that is not load-bearing
#: for the consumer's conclusion, so staleness does NOT propagate through it
#: (P-B slot-scoping). Every pair NOT listed here is load-bearing
#: (conservative default).
MATERIALITY_CONTEXT_PAIRS: frozenset = frozenset(
    {
        # A proposal citing an ancestor's proposal only as inspiration.
        ("proposal_record", "proposal_record"),
    }
)


def depends_materially(consumer_type: str, referenced_type: str) -> bool:
    """Pure (type, type) lookup in the fixed table — never content-based."""
    return (
        str(consumer_type),
        str(referenced_type),
    ) not in MATERIALITY_CONTEXT_PAIRS


def _as_dict(obj) -> dict:
    if isinstance(obj, dict):
        return obj
    to_dict = getattr(obj, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    return {}


def _source_ref_ids(rec: dict) -> list:
    """String refs out of a ``source_refs`` list or dict (values), matching
    the kernel's reader so both sides trace the identical edge set."""
    refs = rec.get("source_refs")
    if isinstance(refs, dict):
        vals = refs.values()
    elif isinstance(refs, (list, tuple)):
        vals = refs
    else:
        vals = ()
    return sorted(str(v) for v in vals if isinstance(v, str) and v)


def record_node_id(rec: dict) -> str:
    """The node anchor of a record: ``node_id`` field, then
    ``source_node_id`` (validated attacks), then the ``source_refs`` /
    ``target_artifact`` dict keys. ``""`` when un-anchored."""
    for key in ("node_id", "source_node_id"):
        v = rec.get(key)
        if isinstance(v, str) and v:
            return v
    refs = rec.get("source_refs")
    if isinstance(refs, dict):
        v = refs.get("node_id")
        if isinstance(v, str) and v:
            return v
    target = rec.get("target_artifact")
    if isinstance(target, dict):
        v = target.get("node_id")
        if isinstance(v, str) and v:
            return v
    return ""


# ── dependency tracing (pure) ───────────────────────────────────────────────


@dataclass(frozen=True)
class DependencyClosure:
    """Output of :func:`trace_dependents` — the whole result of one trace, so
    a caller never re-derives staleness from a partial view."""

    direct: frozenset = frozenset()
    transitive: frozenset = frozenset()
    invalidated_node_ids: frozenset = frozenset()
    recompute_node_ids: frozenset = frozenset()
    #: record_ids swept in past the BFS depth cap (conservative invalidate).
    depth_exceeded: frozenset = frozenset()
    #: node_id → §6 ``_stale_reason`` value for every invalidated node.
    invalidation_reasons: dict = field(default_factory=dict)
    stats: dict = field(default_factory=dict)

    def all_stale(self) -> frozenset:
        return self.direct | self.transitive


def trace_dependents(
    retired_hashes: "set[str] | frozenset",
    records: Sequence,
    *,
    max_depth: int = 8,
    already_stale: frozenset = frozenset(),
) -> DependencyClosure:
    """Pure, deterministic, cycle-safe stale closure.

    ``direct`` = records whose ``prompt_hash`` is retired; ``transitive`` =
    records reached by BFS over reverse ``source_refs`` edges, filtered by
    the type-pair materiality table. Past *max_depth* the materiality
    exemption no longer applies — everything still reachable is swept in
    (conservative invalidate). Records in *already_stale* are skipped
    idempotently (they and their consequences are already flagged).
    """
    retired = frozenset(str(h) for h in retired_hashes if h)
    recmap: dict = {}
    for item in records or ():
        rec = _as_dict(item)
        rid = str(rec.get("record_id", ""))
        if rid:
            recmap[rid] = rec
    # consumer index: referenced record_id -> sorted consumer record_ids.
    by_ref: dict = {}
    for rid in sorted(recmap):
        for ref in _source_ref_ids(recmap[rid]):
            by_ref.setdefault(ref, []).append(rid)

    direct = {
        rid
        for rid, rec in recmap.items()
        if str(rec.get("prompt_hash") or "") in retired
        and rid not in already_stale
    }
    closure = set(direct)
    depth_exceeded: set = set()
    queue = deque((rid, 0) for rid in sorted(direct))
    max_seen_depth = 0
    while queue:
        rid, depth = queue.popleft()
        max_seen_depth = max(max_seen_depth, depth)
        for dep in by_ref.get(rid, ()):  # already sorted
            if dep in closure or dep in already_stale:
                continue
            over_cap = depth + 1 > int(max_depth)
            if not over_cap and not depends_materially(
                str(recmap[dep].get("record_type", "")),
                str(recmap.get(rid, {}).get("record_type", "")),
            ):
                continue
            closure.add(dep)
            if over_cap:
                depth_exceeded.add(dep)
            queue.append((dep, depth + 1))

    invalidated: set = set()
    recompute: set = set()
    reasons: dict = {}
    for rid in sorted(closure):
        rec = recmap[rid]
        node_id = record_node_id(rec)
        if not node_id:
            continue
        role = str(rec.get("role", ""))
        if rid in direct and role in INVALIDATE_ROLES:
            invalidated.add(node_id)
            # A role-specific cause always wins over the depth-cap label;
            # among roles the first in sorted record-id order sticks.
            if reasons.get(node_id, DEPTH_CAP_REASON) == DEPTH_CAP_REASON:
                reasons[node_id] = _ROLE_STALE_REASONS[role]
        elif rid in depth_exceeded:
            invalidated.add(node_id)  # conservative past the depth cap
            reasons.setdefault(node_id, DEPTH_CAP_REASON)
        else:
            recompute.add(node_id)
    return DependencyClosure(
        direct=frozenset(direct),
        transitive=frozenset(closure - direct),
        invalidated_node_ids=frozenset(invalidated),
        recompute_node_ids=frozenset(recompute - invalidated),
        depth_exceeded=frozenset(depth_exceeded),
        invalidation_reasons=dict(sorted(reasons.items())),
        stats={
            "records_scanned": len(recmap),
            "closure_size": len(closure),
            "max_ref_depth": max_seen_depth,
        },
    )


# ── frontier rebuild (pure) ─────────────────────────────────────────────────


def rebuild_frontier(
    all_nodes: Sequence, erasure_state, cfg
) -> list:
    """Pure, declarative recomputation of the frontier — the frontier is
    recomputed from eligibility, never patched incrementally.

    Grounded in the actual representation: the frontier is the in-memory
    list in ``_run_loop`` whose durable form is ``tree.json``. Eligibility =
    completed (SUCCESS/FAILED), frontier-valid, not stale, not sterile,
    below ``max_depth``, and below Rule B via ``len(node.children)`` — the
    durable proxy that is exact only while the one-child-per-expand
    invariant (I-1) holds; ``BFTS._expansion_count`` is in-memory-only and
    empty after resume, so rebuilds must never depend on it.

    Rule-A re-check considers only VALID children, which is the
    reinstatement rule: a parent retired because a now-erased child beat it
    re-enters the frontier. Output sorted by node id (deterministic).
    """
    from ari.orchestrator.node import NodeStatus

    invalid_ids = (
        erasure_state.invalid_node_ids()
        if erasure_state is not None
        else frozenset()
    )
    max_depth = int(getattr(cfg, "max_depth", 5) or 5)
    max_exp = int(getattr(cfg, "max_expansions_per_node", 4) or 4)
    nodes = list(all_nodes or ())
    by_id = {n.id: n for n in nodes}

    def valid(n) -> bool:
        m = n.metrics or {}
        return (
            m.get(VALID_FOR_FRONTIER_KEY, True) is not False
            and m.get(STALE_KEY, False) is not True
            and n.id not in invalid_ids
        )

    def eligible(n) -> bool:
        m = n.metrics or {}
        return (
            n.status in (NodeStatus.SUCCESS, NodeStatus.FAILED)
            and valid(n)
            and m.get("_sterile") is not True
            and n.depth < max_depth
            and len(n.children or ()) < max_exp  # Rule B (len == expansions
            # only while the one-child-per-expand invariant I-1 holds)
        )

    def score(n) -> float:
        try:
            return float((n.metrics or {}).get("_scientific_score") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def dominated(n) -> bool:  # Rule A over valid children only
        for cid in n.children or ():
            child = by_id.get(cid)
            if child is None or not valid(child):
                continue
            if child.status not in (NodeStatus.SUCCESS, NodeStatus.FAILED):
                continue
            if score(child) > score(n):
                return True
        return False

    return sorted(
        (n for n in nodes if eligible(n) and not dominated(n)),
        key=lambda n: n.id,
    )


# ── MetricRecomputer (Layer 0, non-evolving) ────────────────────────────────


class MetricRecomputer:
    """Deterministic utility recomputation from surviving inputs.

    Never re-scores under a new policy: the penalty is recomputed with the
    ORIGINAL epoch's frozen weights stored by value in the UtilityRecord
    (``frozen_policy``, Task 06). Reversal happens by recomputation from the
    surviving ValidatedAttackRecords, never by arithmetic un-scaling.
    Returns the superseding UtilityRecord dict, or ``None`` when no valid
    utility survives (⇒ the caller invalidates the node instead).
    """

    def recompute(
        self,
        node,
        utility_rec: dict,
        recmap: dict,
        stale_ids: frozenset,
        *,
        epoch_id: str,
        new_record_id: str,
    ) -> dict | None:
        frozen = utility_rec.get("frozen_policy")
        if not isinstance(frozen, dict) or not frozen:
            return None  # original weights unrecoverable ⇒ invalidate (P-D)
        input_refs = utility_rec.get("input_refs")
        input_refs = input_refs if isinstance(input_refs, dict) else {}
        vat_ids = [
            str(v) for v in (input_refs.get("validated_attack_ids") or [])
        ]
        surviving = []
        for vid in sorted(vat_ids):
            if vid in stale_ids:
                continue
            rec = recmap.get(vid)
            if rec is None or rec.get("verdict") not in (
                "valid", "partially_valid",
            ):
                continue
            surviving.append(rec)
        weights = frozen.get("severity_weights") or {}
        factors = frozen.get("verdict_factors") or {}
        try:
            cap = float(frozen.get("penalty_cap", 0.5))
        except (TypeError, ValueError):
            return None
        total = 0.0
        for rec in surviving:
            total += float(
                weights.get(str(rec.get("severity", "")), 0.0)
            ) * float(factors.get(str(rec.get("verdict", "")), 0.0))
        penalty = round(min(cap, total), 6)
        try:
            base = float(utility_rec.get("base_score", 0.0) or 0.0)
        except (TypeError, ValueError):
            return None
        out = dict(utility_rec)
        out["record_id"] = new_record_id
        out["penalty"] = penalty
        out["final_score"] = max(0.0, base - penalty)
        out["input_refs"] = dict(
            input_refs,
            validated_attack_ids=[
                str(r.get("record_id", "")) for r in surviving
            ],
        )
        out["supersedes"] = str(utility_rec.get("record_id", ""))
        out["recomputed_in_epoch"] = epoch_id
        refs = {str(utility_rec.get("node_id", "") or "")} | {
            str(r.get("record_id", "")) for r in surviving
        }
        out["source_refs"] = sorted(refs - {""})
        return out


# ── the engine ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RepairResult:
    """Result of one :meth:`FrontierRepairEngine.repair` call (§7)."""

    erasure_event: dict | None
    rebuild_event: dict | None
    status: str  # applied | conservative | halted_expansion | noop


def load_rqgm_records(checkpoint_dir: str | Path) -> list:
    """Absence-tolerant aggregation of every RQGM record store — the input a
    trace runs over, so a missing store narrows the trace, never fails it.

    Reads ``proposals/proposal_records.jsonl``,
    ``rqgm_adversarial_cases.jsonl``, and the record payloads inside
    ``rqgm_audit.jsonl`` envelopes. Read-only; corrupt lines skipped.
    """
    ckpt = Path(checkpoint_dir)
    out: list = []
    seen: set = set()

    def _add(rec: dict) -> None:
        rid = str(rec.get("record_id", ""))
        if rid and rid not in seen and rec.get("record_type"):
            seen.add(rid)
            out.append(rec)

    def _read_jsonl(path: Path) -> None:
        if not path.exists():
            return
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
                        _add(d)
        except OSError:
            pass

    _read_jsonl(ckpt / "proposals" / "proposal_records.jsonl")
    _read_jsonl(ckpt / "rqgm_adversarial_cases.jsonl")
    try:
        from ari.rqgm.store import ImmutableAuditLog

        for line in ImmutableAuditLog.read(ckpt):
            payload = line.get("payload")
            if isinstance(payload, dict):
                _add(payload)
    except Exception:
        log.warning("audit-log record aggregation failed", exc_info=True)
    return out


class FrontierRepairEngine:
    """Trace → stale → recompute/invalidate → rebuild → validate (§7).

    Constructed only under ``ari_rqgm`` (``RQGMRuntime.frontier_repair``);
    ``simple_bfts`` never imports this module. All collaborators are
    injectable so tests use deterministic fakes; the default wiring is the
    concrete Task 02/10 stores. Runs on the main thread at the epoch
    boundary only — no node is in flight.
    """

    def __init__(
        self,
        *,
        cfg=None,
        kernel=None,
        erasure_store=None,
        audit_log=None,
        recomputer=None,
        record_loader=load_rqgm_records,
        enforcement: str = "standard",
    ) -> None:
        self.cfg = cfg  # the rqgm.frontier_repair block (typed/dict/None)
        self.kernel = kernel
        self.erasure_store = (
            erasure_store if erasure_store is not None
            else RqgmErasureStateStore()
        )
        self.audit_log = audit_log
        self.recomputer = (
            recomputer if recomputer is not None else MetricRecomputer()
        )
        self.record_loader = record_loader
        self.enforcement = enforcement
        self.expansion_halted = False

    # ── config reads (duck-typed; the default is used whenever the block
    # is absent or the value will not coerce) ─────────────────────────

    def _cfg(self, name: str, default):
        block = self.cfg
        if isinstance(block, dict):
            raw = block.get(name, default)
        else:
            raw = getattr(block, name, default)
        try:
            return type(default)(raw)
        except (TypeError, ValueError):
            return default

    @property
    def enabled(self) -> bool:
        return self._cfg("enabled", True)

    @property
    def max_trace_depth(self) -> int:
        return self._cfg("max_trace_depth", 8)

    @property
    def recompute_utilities(self) -> bool:
        return self._cfg("recompute_utilities", True)

    @property
    def abandon_stale_pending(self) -> bool:
        return self._cfg("abandon_stale_pending", True)

    # ── the boundary entry point ──────────────────────────────────────

    def repair(
        self,
        *,
        transition,
        frontier: list,
        pending: list,
        all_nodes: list,
        checkpoint_dir: str | Path,
        bfts_cfg=None,
        epoch_id: str = "",
        new_utility_policy: dict | None = None,
    ) -> RepairResult:
        """Run once per applied EpochTransition that carries retirements.

        Mutates *frontier* in place (``frontier[:] = rebuilt``), removes
        stale pending children, and writes node-metrics sentinels. Never
        raises — any internal failure degrades to a logged no-op so the
        boundary (and the run) continues.

        *new_utility_policy* is the NEWLY-FROZEN epoch's sealed utility policy
        (``EpochState.utility_policy``). When supplied, a node scored under a
        RETIRED utility policy is RE-WEIGHTED under the new criterion from its
        stored per-axis raw scores instead of being dropped (Task 14,
        amended #77). Absent/unusable ⇒ the pre-#77 total-invalidation
        behaviour, so no stale-criterion score ever survives either way.
        """
        try:
            return self._repair(
                transition=transition,
                frontier=frontier,
                pending=pending,
                all_nodes=all_nodes,
                checkpoint_dir=checkpoint_dir,
                bfts_cfg=bfts_cfg,
                epoch_id=epoch_id,
                new_utility_policy=new_utility_policy,
            )
        except Exception:
            log.warning("frontier repair failed (degrading to no-op)",
                        exc_info=True)
            return RepairResult(None, None, "noop")

    def _repair(
        self, *, transition, frontier, pending, all_nodes,
        checkpoint_dir, bfts_cfg, epoch_id, new_utility_policy=None,
    ) -> RepairResult:
        retirements = [
            _as_dict(e) for e in (getattr(transition, "retirements", ()) or ())
        ]
        if not retirements or not self.enabled:
            return RepairResult(None, None, "noop")
        ckpt = Path(checkpoint_dir)
        retired_hashes = sorted(
            {str(e.get("prompt_hash")) for e in retirements
             if e.get("prompt_hash")}
        )
        retired_components = sorted(
            {str(e.get("component_id")) for e in retirements
             if e.get("component_id")}
        )
        transition_id = str(
            getattr(transition, "epoch_transition_id", "") or ""
        )
        from_epoch = str(getattr(transition, "from_epoch", "") or "")
        to_epoch = str(
            epoch_id or getattr(transition, "to_epoch", "") or ""
        )

        state = self.erasure_store.load(ckpt)
        records = [_as_dict(r) for r in (self.record_loader(ckpt) or ())]
        recmap = {
            str(r.get("record_id", "")): r
            for r in records
            if r.get("record_id")
        }
        closure = trace_dependents(
            set(retired_hashes),
            records,
            max_depth=self.max_trace_depth,
            already_stale=state.stale_ids(),
        )

        erase_id = _next_id("erase", state.last_erasure_event_id)
        node_map = {n.id: n for n in (all_nodes or ())}

        # (a) invalidate nodes whose direction/policy came from a retired
        # prompt (the generator/router and utility_policy rows of the
        # invalidate-vs-recompute policy), stamping the per-cause reason.
        for nid in sorted(closure.invalidated_node_ids):
            node = node_map.get(nid)
            if node is not None:
                self._flag_node(
                    node,
                    closure.invalidation_reasons.get(
                        nid, GENERATOR_RETIRED_REASON
                    ),
                    erase_id,
                )

        # (a2) Task 14, amended #77: a ``utility_policy``
        # retirement re-scores every node whose own provenance stamp names the
        # retired policy — reached by the node's stamp instead of by a record it
        # may not have. This is what makes the rewrite TOTAL rather than a random
        # half-rewrite over the attacked-and-penalised subset (see
        # UTILITY_POLICY_HASH_KEY).
        #
        # #77 (DELIBERATE reversal of "invalidate never re-weight" for the
        # policy-retirement case): when the newly-frozen epoch's policy is
        # available AND a node carries its per-axis raw scores, the node is
        # RE-WEIGHTED in place under the NEW criterion (``_rescore_node_under_
        # policy``) so a still-comparable node keeps a score on the new axis —
        # the "boundary re-scores the tree under the new criterion" pillar. The
        # raw per-axis scores are the judge's policy-INDEPENDENT measurements, so
        # re-weighting them is a faithful application of the new criterion, not a
        # laundering of an old composite. Any node that cannot be re-weighted
        # (no raw axes, unusable/absent new policy) still falls back to total
        # invalidation, so no stale-criterion score ever survives.
        retired_policy_hashes = {
            str(e.get("prompt_hash"))
            for e in retirements
            if str(e.get("role", "")) == "utility_policy"
            and e.get("prompt_hash")
        }
        policy_invalidated: list = []
        policy_rescored: list = []
        if retired_policy_hashes:
            # Nodes (a) already invalidated for a NON-policy reason (their
            # generator/direction was retired in this same transition) are
            # hard-invalidated — never re-scored, whatever their stamp says.
            hard_invalidated = {
                nid for nid in closure.invalidated_node_ids
                if closure.invalidation_reasons.get(
                    nid, GENERATOR_RETIRED_REASON
                ) != UTILITY_INVALIDATED_REASON
            }
            for node in sorted(
                (n for n in (all_nodes or ())), key=lambda n: str(n.id)
            ):
                metrics = getattr(node, "metrics", None)
                if not isinstance(metrics, dict):
                    continue
                stamped = str(metrics.get(UTILITY_POLICY_HASH_KEY, "") or "")
                if not (stamped and stamped in retired_policy_hashes):
                    continue
                if node.id in hard_invalidated:
                    # (a) already flagged it for a hard reason; keep it.
                    policy_invalidated.append(node.id)
                    continue
                if new_utility_policy and self._rescore_node_under_policy(
                    node, new_utility_policy
                ):
                    # (a) may have flagged this SAME node utility_invalidated
                    # (via its own utility_record) — clear that policy-only
                    # flag so the freshly re-weighted node re-enters the
                    # frontier. Safe: hard-invalidated nodes were excluded.
                    self._clear_policy_invalidation(node)
                    policy_rescored.append(node.id)
                else:
                    self._flag_node(
                        node, UTILITY_INVALIDATED_REASON, erase_id
                    )
                    policy_invalidated.append(node.id)
            if policy_rescored:
                log.info(
                    "frontier repair: re-scored %d node(s) under the new "
                    "epoch utility policy (composite=%s); invalidated %d",
                    len(policy_rescored),
                    new_utility_policy.get("composite"),
                    len(policy_invalidated),
                )

        # (b) abandon pending children authored by a retired generator
        # BEFORE they ever run — contaminated work is stopped, not finished
        # and then discounted.
        abandoned: list = []
        if self.abandon_stale_pending:
            stale_all = closure.all_stale()
            for child in list(pending or ()):
                anchor = self._pending_anchor(child.id, recmap, stale_all)
                if anchor:
                    pending.remove(child)
                    child.mark_abandoned()
                    role = str(recmap.get(anchor, {}).get("role", ""))
                    self._flag_node(
                        child,
                        _ROLE_STALE_REASONS.get(
                            role, GENERATOR_RETIRED_REASON
                        ),
                        erase_id,
                    )
                    abandoned.append(child.id)

        # (c) recompute utilities from surviving inputs under the original
        # epoch's frozen weights — or invalidate when impossible.
        # Nodes whose scored evidence did NOT go stale (e.g. only a raw
        # attack targeting them was staled — never scored, invariant 8) are
        # left untouched.
        recomputed: list = []
        stale_ids = closure.all_stale() | state.stale_ids()
        policy_handled_ids = set(policy_invalidated) | set(policy_rescored)
        for nid in sorted(closure.recompute_node_ids):
            node = node_map.get(nid)
            if node is None:
                continue
            if nid in policy_handled_ids:
                # A node scored under a RETIRED utility policy is settled by
                # (a2) — re-weighted under the NEW criterion (#77) or
                # invalidated — and is NEVER also run through the
                # surviving-inputs recompute below. That recompute re-derives
                # the penalty under the node's ORIGINAL frozen weights;
                # running it after (a2) would overwrite the fresh
                # new-criterion score with old-weight arithmetic. The pre-#77
                # invariant ("a rewrite INVALIDATES; it never re-weights an old
                # score in place") is deliberately amended ONLY for the
                # policy-retirement case, and ONLY by re-weighting the judge's
                # policy-independent per-axis raw scores — never by converting
                # an old composite into a new one.
                continue
            base_rec = self._latest_utility(node.id, recmap)
            if base_rec is None or str(
                base_rec.get("record_id", "")
            ) not in stale_ids:
                continue  # nothing scored went stale for this node
            new_rec = None
            if self.recompute_utilities:
                new_rec = self._recompute_node(
                    node, base_rec, recmap, stale_ids, to_epoch
                )
            if new_rec is None:
                self._flag_node(node, UTILITY_INVALIDATED_REASON, erase_id)
            else:
                recomputed.append(nid)
                self._append_audit("utility_record", new_rec)
                recmap[str(new_rec.get("record_id", ""))] = new_rec
                records.append(new_rec)

        erasure_event = {
            "record_id": erase_id,
            "record_type": SELECTIVE_ERASURE_RECORD_TYPE,
            "epoch_id": from_epoch,
            "component_id": FRONTIER_REPAIR_COMPONENT_ID,
            "prompt_hash": None,
            "role": FRONTIER_REPAIR_ROLE,
            "created_at": _now_iso(),
            "source_refs": sorted(
                {str(e.get("retirement_event_id")) for e in retirements
                 if e.get("retirement_event_id")}
            ) + ([transition_id] if transition_id else []),
            "status": "applied",
            "retired_prompt_hashes": retired_hashes,
            "retired_component_ids": retired_components,
            "direct_stale_record_ids": sorted(closure.direct),
            "transitive_stale_record_ids": sorted(closure.transitive),
            "invalidated_node_ids": sorted(
                (set(closure.invalidated_node_ids) | set(policy_invalidated))
                - set(policy_rescored)
            ),
            "policy_rescored_node_ids": sorted(policy_rescored),
            "recompute_node_ids": sorted(
                set(closure.recompute_node_ids) - policy_handled_ids
            ),
            "abandoned_pending_node_ids": sorted(abandoned),
            "trace_stats": dict(closure.stats),
        }
        state = self._persist_state(ckpt, state, erasure_event, retirements)

        # (d) declarative frontier rebuild + in-place replacement.
        before = sorted(n.id for n in (frontier or ()))
        rebuilt = rebuild_frontier(all_nodes, state, bfts_cfg)
        frontier[:] = rebuilt
        status = "applied"

        # (e) kernel validation + the degradation ladder: applied →
        # conservative (drop the flagged nodes outright) → halted_expansion
        # (drain-only). Trace lines feed the CK-ERA-006 cross-check, which is
        # secondary evidence only — a missing trace never fails validation.
        trace_lines = _load_prompt_trace_lines(ckpt)
        if self.kernel is not None:
            if not self._validate(
                frontier, records, state, retired_hashes, trace_lines
            ):
                status = "conservative"
                self._conservative_drop(frontier, state)
                if not self._validate(
                    frontier, records, state, retired_hashes, trace_lines
                ):
                    status = "halted_expansion"
                    self.expansion_halted = True
                    log.error(
                        "frontier repair: kernel validation failed twice — "
                        "degrading to drain-only (no further expansion)"
                    )

        erasure_event["status"] = status
        self._append_audit(SELECTIVE_ERASURE_EVENT_TYPE, erasure_event)
        after = sorted(n.id for n in frontier)
        rebuild_event = {
            "record_id": _next_id("rebuild", state.last_rebuild_event_id),
            "record_type": FRONTIER_REBUILD_RECORD_TYPE,
            "epoch_id": to_epoch,
            "component_id": FRONTIER_REPAIR_COMPONENT_ID,
            "prompt_hash": None,
            "role": FRONTIER_REPAIR_ROLE,
            "created_at": _now_iso(),
            "source_refs": [erase_id],
            "status": status,
            "frontier_before": before,
            "frontier_after": after,
            "removed_node_ids": sorted(set(before) - set(after)),
            "reinstated_node_ids": sorted(set(after) - set(before)),
            "recomputed_utility_node_ids": sorted(recomputed),
            "kernel_validation": (
                "passed" if status == "applied" else "failed"
            ),
        }
        self._append_audit(FRONTIER_REBUILD_EVENT_TYPE, rebuild_event)
        state = fold_event(state, rebuild_event)
        self.erasure_store.save(ckpt, state)
        return RepairResult(erasure_event, rebuild_event, status)

    # ── internals ─────────────────────────────────────────────────────

    @staticmethod
    def _flag_node(node, reason: str, erase_id: str) -> None:
        if not isinstance(getattr(node, "metrics", None), dict):
            node.metrics = {}
        node.metrics[STALE_KEY] = True
        node.metrics[VALID_FOR_FRONTIER_KEY] = False
        node.metrics[STALE_REASON_KEY] = reason
        node.metrics[ERASURE_EVENT_KEY] = erase_id

    @staticmethod
    def _clear_policy_invalidation(node) -> None:
        """#77: undo a utility-policy-only invalidation on a node that is being
        re-scored under the new criterion, so it re-enters the frontier. Only
        the policy-invalidation sentinels are touched; called solely for nodes
        proven NOT hard-invalidated (their generator/direction survives)."""
        metrics = getattr(node, "metrics", None)
        if not isinstance(metrics, dict):
            return
        metrics[STALE_KEY] = False
        metrics[VALID_FOR_FRONTIER_KEY] = True
        metrics.pop(STALE_REASON_KEY, None)
        metrics.pop(ERASURE_EVENT_KEY, None)
        node.metrics = metrics

    @staticmethod
    def _rescore_node_under_policy(node, new_policy: dict) -> bool:
        """#77: re-weight a node scored under the RETIRED utility policy so it
        carries a score under the NEW criterion, in place. Returns True iff the
        node was re-scored.

        The composite is recomputed from the node's stored per-axis raw scores
        (``_axis_scores`` — the judge's policy-INDEPENDENT measurements) under
        the new policy's ``composite`` + ``axis_weights``, mirroring the live
        scoring path (``LLMEvaluator._compose_fn(axes, weights,
        axis_names=...)``). The node's EXISTING validated attack penalty is then
        re-applied exactly as the adversarial engine does
        (``_scientific_score = max(0, base - penalty)``): attack VALIDITY is
        independent of the utility policy (plan 08), so only the base composite
        is re-weighted. The node is re-stamped with the new
        ``utility_policy_hash`` so a later boundary sees it as current.

        Fails CLOSED (returns False, no mutation of the score keys) whenever the
        raw axis scores or the new policy are missing/invalid — the caller then
        falls back to total invalidation, so no stale-criterion score survives.
        Only the SAME axis set the judge actually scored can be re-weighted; a
        policy that introduces brand-new axes has no stored raw for them, and
        the compose fn treats those as absent (documented limitation)."""
        try:
            metrics = getattr(node, "metrics", None)
            if not isinstance(metrics, dict):
                return False
            raw_axes = metrics.get("_axis_scores")
            if not isinstance(raw_axes, dict) or not raw_axes:
                return False
            axis_scores: dict[str, float] = {}
            for k, v in raw_axes.items():
                try:
                    axis_scores[str(k)] = float(v)
                except (TypeError, ValueError):
                    return False
            weights_in = new_policy.get("axis_weights")
            composite = str(new_policy.get("composite", "") or "")
            if not composite:
                return False
            # axis_weights may be EMPTY — a composite-only policy change (the
            # PolicyMutator's ``composite_swap``, the most common utility
            # mutation, leaves axis_weights={}). An empty/absent weight map is
            # NOT a reason to fail-closed: the compose fns fall back to equal
            # per-axis weights (``_iter_weighted_values``), exactly as the live
            # LLMEvaluator does when cfg weights are unset — so re-weighting the
            # SAME raw axes under the new composite with equal weights IS the
            # new criterion. (Discovered live: a 6-epoch codex run evolved the
            # composite harmonic_mean->weighted_min with axis_weights={}, and
            # the old `not weights_in` guard fail-closed every stamped node to
            # invalidation instead of re-scoring — #77 never fired.)
            if weights_in is not None and not isinstance(weights_in, dict):
                return False
            weights: dict[str, float] = {}
            for k, v in (weights_in or {}).items():
                try:
                    weights[str(k)] = float(v)
                except (TypeError, ValueError):
                    return False
            from ari.evaluator.llm_evaluator import _COMPOSITE_REGISTRY
            if composite not in _COMPOSITE_REGISTRY:
                return False
            compose_fn = _COMPOSITE_REGISTRY.resolve(composite)
            base = float(compose_fn(
                axis_scores, weights, axis_names=tuple(axis_scores.keys())
            ))
            try:
                penalty = float(
                    metrics.get("_validated_attack_penalty", 0.0) or 0.0
                )
            except (TypeError, ValueError):
                penalty = 0.0
            metrics["_pre_penalty_score"] = base
            metrics["_scientific_score"] = max(0.0, base - penalty)
            new_hash = str(new_policy.get("utility_policy_hash", "") or "")
            if new_hash:
                metrics[UTILITY_POLICY_HASH_KEY] = new_hash
            node.metrics = metrics
            return True
        except Exception:
            log.warning(
                "policy re-score failed for node %s (fail-closed to "
                "invalidation)", getattr(node, "id", "?"), exc_info=True
            )
            return False

    @staticmethod
    def _pending_anchor(node_id: str, recmap: dict, stale: frozenset) -> str:
        """The stale generator-side proposal record anchored on *node_id*
        (its direction was authored by a retired prompt), or ``""``."""
        for rid in sorted(stale):
            rec = recmap.get(rid)
            if rec is None:
                continue
            if str(rec.get("role", "")) not in INVALIDATE_ROLES:
                continue
            if record_node_id(rec) == node_id:
                return rid
        return ""

    @staticmethod
    def _latest_utility(node_id: str, recmap: dict) -> dict | None:
        """Latest non-superseded utility record anchored on *node_id* (ids
        are monotonic per run; the read rule of the append-only store)."""
        superseded = {
            str(rec.get("supersedes"))
            for rec in recmap.values()
            if rec.get("supersedes")
        }
        candidates = sorted(
            rid
            for rid, rec in recmap.items()
            if rec.get("record_type") == "utility_record"
            and record_node_id(rec) == node_id
            and rid not in superseded
        )
        return recmap.get(candidates[-1]) if candidates else None

    def _recompute_node(
        self, node, base_rec: dict, recmap: dict, stale_ids: frozenset,
        epoch_id: str,
    ) -> dict | None:
        """Stale utility record of *node* → superseding recompute (the old
        record is never edited; a new record supersedes it)."""
        new_id = "%s_r%03d" % (
            base_rec.get("record_id", "utl"),
            sum(1 for r in recmap.values() if r.get("supersedes")),
        )
        new_rec = self.recomputer.recompute(
            node,
            base_rec,
            recmap,
            stale_ids,
            epoch_id=epoch_id,
            new_record_id=new_id,
        )
        if new_rec is None:
            return None
        # Sentinel effects: metrics values are run state, not an append-only
        # store — tree.json is a rewrite-snapshot by contract, so overwriting
        # a node's metric values there is legal where record edits are not.
        metrics = node.metrics if isinstance(node.metrics, dict) else {}
        try:
            metrics["_pre_penalty_score"] = float(
                new_rec.get("base_score", 0.0)
            )
            metrics["_validated_attack_penalty"] = float(
                new_rec.get("penalty", 0.0)
            )
            metrics["_scientific_score"] = float(
                new_rec.get("final_score", 0.0)
            )
        except (TypeError, ValueError):
            return None
        node.metrics = metrics
        return new_rec

    def _persist_state(
        self, ckpt: Path, state: ErasureStateView, event: dict,
        retirements: list,
    ) -> ErasureStateView:
        new_state = fold_event(state, event)
        # Enrich retirement provenance beyond the fold's defaults.
        for entry in retirements:
            h = str(entry.get("prompt_hash") or "")
            if h:
                new_state.retired_prompt_hashes[h] = {
                    "retirement_event_id": str(
                        entry.get("retirement_event_id", "") or ""
                    ),
                    "retired_in_epoch": str(event.get("epoch_id", "") or ""),
                }
        self.erasure_store.save(ckpt, new_state)
        return new_state

    def _append_audit(self, event_type: str, payload: dict) -> None:
        if self.audit_log is None:
            return
        try:
            self.audit_log.append(event_type, payload)
        except Exception:
            log.warning("%s audit append failed", event_type, exc_info=True)

    def _validate(
        self, frontier: list, records: list, state: ErasureStateView,
        retired_hashes: list, trace_lines: list,
    ) -> bool:
        """Kernel assertions via Task 04's
        ``validate_selective_erasure``; a blocking report is what steps the
        degradation ladder. Records are handed over with the
        LOGICAL staleness view materialised (read-time derivation);
        *trace_lines* drive the CK-ERA-006 prompt_trace cross-check."""
        try:
            from ari.rqgm.kernel import should_block

            stale = state.stale_ids()
            records_view = [
                dict(
                    rec,
                    stale=(str(rec.get("record_id", "")) in stale),
                    valid_for_frontier=(
                        str(rec.get("record_id", "")) not in stale
                    ),
                )
                for rec in records
            ]
            frontier_view = [
                {
                    "record_id": n.id,
                    "stale": bool((n.metrics or {}).get(STALE_KEY, False))
                    or n.id in state.invalid_node_ids(),
                    "valid_for_frontier": (
                        (n.metrics or {}).get(VALID_FOR_FRONTIER_KEY, True)
                        is not False
                    )
                    and n.id not in state.invalid_node_ids(),
                    "prompt_hash": None,
                }
                for n in frontier
            ]
            report = self.kernel.validate_selective_erasure(
                frontier_view,
                records_view,
                state.retired_hashes() | frozenset(retired_hashes),
                prompt_trace=trace_lines,
            )
            return not should_block(report, self.enforcement)
        except Exception:
            log.warning("selective-erasure validation errored; treating as "
                        "failed (fail-closed at the boundary)", exc_info=True)
            return False

    @staticmethod
    def _conservative_drop(frontier: list, state: ErasureStateView) -> None:
        """Ladder step 1 (conservative): drop every flagged node outright,
        with no recompute — correctness over retained work."""
        invalid = state.invalid_node_ids()
        frontier[:] = [
            n
            for n in frontier
            if (n.metrics or {}).get(STALE_KEY, False) is not True
            and (n.metrics or {}).get(VALID_FOR_FRONTIER_KEY, True)
            is not False
            and n.id not in invalid
        ]


def _load_prompt_trace_lines(ckpt: Path) -> list:
    """Read-only ``prompt_trace.jsonl`` lines for the CK-ERA-006 cross-check
    (absence = no data, never an error — the ``load_prompt_trace``
    discipline; a read failure only skips the secondary evidence)."""
    try:
        from ari.prompts._provenance import load_prompt_trace

        return load_prompt_trace(ckpt)
    except Exception:
        log.warning("prompt_trace read failed; CK-ERA-006 cross-check skipped",
                    exc_info=True)
        return []


def _next_id(prefix: str, last_id: str) -> str:
    """``erase_00007``-style monotonic ids continued from the state file."""
    seq = 0
    tail = str(last_id or "").rsplit("_", 1)
    if len(tail) == 2 and tail[1].isdigit():
        seq = int(tail[1]) + 1
    return "%s_%05d" % (prefix, seq)


def _now_iso() -> str:
    """UTC metadata timestamp (never hashed, never read by decisions — P2)."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
