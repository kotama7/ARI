"""RQGM read models for ``/api/v1`` (gui_refresh task 08 Wave 4a, plan 08).

Pure artifact readers over one checkpoint directory — the plan-08 offline
projector.  Ground rules (plan 08 §Non-goals / §Truth and presentation
rules, program invariants):

- ``ari.rqgm`` is NEVER imported.  The read model parses the committed
  checkpoint artifacts (``rqgm_state.json``, ``rqgm_transitions.jsonl``,
  ``rqgm_audit.jsonl``, ``rqgm_adversarial_cases.jsonl``,
  ``rqgm_registry.json``, ``rqgm_prompts/*.json``, ``meta.json``, the node
  ``metrics`` sentinels) directly and re-executes no kernel/score-policy
  decision.  The only RQGM arithmetic reproduced here is the frozen hash
  contract ``event_hash = sha256(canonical_json(payload))[:12]`` — a
  byte-golden-pinned contract (``ari/rqgm/events.py`` docstring, plan 02
  §5.4), duplicated deliberately because importing the governance package
  from viz is prohibited; parity is pinned by ``tests/test_gui_v1_rqgm.py``
  against the fixture factory (which uses the production helpers).
- Committed records only: a JSONL trailing partial line (torn append) is
  silently ignored, and transition events after an
  ``epoch_transaction_prepare`` with no matching commit are never adopted
  into current state (the mirror of ``ari.rqgm.store.committed_events``).
- Degraded, never broken: a broken hash chain / stale rollup flips the
  payload's integrity flags and adds ``degraded_reasons`` — a corrupt
  artifact yields HTTP 200 with honest flags, not a 500.  A missing source
  is ``None``, never displayed as clean/zero.
- Read-only: nothing here writes a file, touches ``viz.state`` or
  ``os.environ`` (GET side-effect-freeness), and there is no mutation
  endpoint (GUI v1 RQGM surface is read-only by plan).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ..checkpoint_finder import _resolve_checkpoint_dir
from ..tree_view import build_tree_view
from .dto import (
    RqgmAuditEntryV1,
    RqgmAuditPageV1,
    RqgmCapabilitiesV1,
    RqgmComponentV1,
    RqgmEpochDetailV1,
    RqgmEpochsV1,
    RqgmEpochTransitionCountsV1,
    RqgmEpochV1,
    RqgmEvolutionEntryV1,
    RqgmEvolutionV1,
    RqgmIntegrityV1,
    RqgmNodeLineageV1,
    RqgmOverviewV1,
    RqgmPaperAnchorV1,
    RqgmPaperArchiveV1,
    RqgmPaperSelfPreferenceV1,
    RqgmPaperWinnerV1,
    RqgmPoliciesV1,
    RqgmPolicyV1,
    RqgmPromptV1,
    RqgmRawAttackV1,
    RqgmRegistrySummaryV1,
    RqgmRegistryV1,
    RqgmScoreObservationV1,
    RqgmScoreRewritesPageV1,
    RqgmScoreRewriteV1,
    RqgmTransactionRefV1,
    RqgmTransitionEntryV1,
    RqgmTransitionsPageV1,
    RqgmValidatedAttackV1,
)
from .errors import error_response

RQGM_STATE_FILENAME = "rqgm_state.json"
RQGM_TRANSITIONS_FILENAME = "rqgm_transitions.jsonl"
RQGM_AUDIT_FILENAME = "rqgm_audit.jsonl"
RQGM_REGISTRY_FILENAME = "rqgm_registry.json"
RQGM_ADVERSARIAL_FILENAME = "rqgm_adversarial_cases.jsonl"
PAPER_ARCHIVE_STATE_FILENAME = "paper_archive_state.json"
# Wave 4b sources (filenames are frozen artifact contracts — the producing
# modules under ari.rqgm are deliberately NOT imported, see module docstring):
PROMPT_EVOLUTION_FILENAME = "prompt_evolution.jsonl"
META_OUTPUTS_FILENAME = "rqgm_meta_outputs.jsonl"
PAPER_DRAFT_ARCHIVE_FILENAME = "paper_draft_archive.jsonl"
PAPER_ANCHOR_CORPUS_FILENAME = "paper_anchor_corpus.jsonl"
PAPER_SELF_PREFERENCE_STAT_RELPATH = "rqgm/paper_self_preference_stat.json"
FULL_PAPER_FILENAME = "full_paper.tex"

#: Registry statuses that are sanctions (postures) rather than adoptions /
#: retirements / bans — used only to bucket boundary status-change counts.
_SANCTION_STATUSES: tuple[str, ...] = ("warning", "probation", "quarantine")

#: Registry lifecycle vocabulary — verbatim ``ari.rqgm.events.STATUS_VALUES``
#: (frozen contract; parity pinned by tests, never imported).
REGISTRY_STATUSES: tuple[str, ...] = (
    "candidate",
    "validated",
    "shadow",
    "probationary_active",
    "active",
    "warning",
    "probation",
    "quarantine",
    "retired",
    "banned",
)

#: Statuses forming the frozen per-epoch active set (``ACTIVE_STATUSES``).
ACTIVE_STATUSES: tuple[str, ...] = ("active", "probationary_active")

_UTILITY_POLICY_ROLE = "utility_policy"

#: Bound on per-source degraded reasons so overview stays bounded.
_MAX_REASONS_PER_SOURCE = 3

_DEFAULT_LIMIT = 20
_MAX_LIMIT = 100


# ── frozen hash contract (see module docstring for why it is duplicated) ───


def _canonical_json(payload: object) -> str:
    """Mirror of ``ari.rqgm.events.canonical_json`` (sorted keys, no
    whitespace, ``ensure_ascii=False``) — the ONE canonical form."""
    return json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )


def _hash12(text: str) -> str:
    """Mirror of ``ari.prompts._provenance.hash12`` — ``sha256(text)[:12]``."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


# ── low-level artifact readers ─────────────────────────────────────────────


def _read_json(path: Path) -> dict | None:
    """Absence/corruption-tolerant JSON object read."""
    if not path.exists():
        return None
    try:
        d = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except ValueError:
        return None
    return d if isinstance(d, dict) else None


def _scan_jsonl(path: Path) -> tuple[list[dict], int, list[str]]:
    """Byte-offset JSONL scan: ``(lines, parsed_end, reasons)``.

    Each line is ``{"offset": int, "record": dict}``.  A trailing segment
    with no newline terminator is a torn append: it is included only when it
    parses as a complete JSON object, otherwise silently ignored
    (committed-only rule — never a corruption flag).  A TERMINATED line that
    fails to parse is skipped with a reason (mid-file corruption).
    ``parsed_end`` is the byte length of the parsed region (the page
    ``source_revision``): a torn tail does not advance it.
    """
    lines: list[dict] = []
    reasons: list[str] = []
    try:
        raw = path.read_bytes()
    except OSError:
        return lines, 0, [f"{path.name}: unreadable"]
    pos = 0
    parsed_end = 0
    n = len(raw)
    while pos < n:
        nl = raw.find(b"\n", pos)
        if nl == -1:
            seg = raw[pos:]
            try:
                rec = json.loads(seg.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                break  # torn append — ignored, revision unchanged
            if isinstance(rec, dict):
                lines.append({"offset": pos, "record": rec})
                parsed_end = n
            break
        seg = raw[pos:nl]
        if seg.strip():
            try:
                rec = json.loads(seg.decode("utf-8", errors="replace"))
            except ValueError:
                rec = None
            if isinstance(rec, dict):
                lines.append({"offset": pos, "record": rec})
            elif len(reasons) < _MAX_REASONS_PER_SOURCE:
                reasons.append(
                    f"{path.name}: unparseable line at byte {pos} skipped"
                )
        pos = nl + 1
        parsed_end = pos
    return lines, parsed_end, reasons


def _verify_chain(name: str, lines: list[dict]) -> tuple[bool, list[str]]:
    """Incremental hash-chain verification over parsed lines.

    Checks ``event_hash == hash12(canonical_json(payload))`` per line and
    ``prev_event_hash`` continuity (first line must chain from ``""``).
    Returns ``(chain_ok, reasons)``; scanning continues past a break so the
    data can still be served, flagged.
    """
    ok = True
    reasons: list[str] = []
    prev = ""
    for entry in lines:
        rec = entry["record"]
        payload = rec.get("payload")
        payload = payload if isinstance(payload, dict) else {}
        eh = str(rec.get("event_hash", ""))
        eid = str(rec.get("event_id", "?"))
        if eh != _hash12(_canonical_json(payload)):
            ok = False
            if len(reasons) < _MAX_REASONS_PER_SOURCE:
                reasons.append(
                    f"{name}: event_hash of {eid} does not cover its payload"
                )
        if str(rec.get("prev_event_hash", "")) != prev:
            ok = False
            if len(reasons) < _MAX_REASONS_PER_SOURCE:
                reasons.append(
                    f"{name}: hash chain broken at {eid} "
                    f"(byte {entry['offset']})"
                )
        prev = eh
    return ok, reasons


# ── committed-transaction grouping + registry replay ───────────────────────


def _group_committed(lines: list[dict]) -> list[dict]:
    """Group transition lines into committed display entries.

    Mirror of the ``ari.rqgm.store.committed_events`` crash-recovery rule:
    a prepare without a matching commit (and everything after it) is
    dropped; a new prepare abandons an unterminated predecessor; events
    outside any transaction (initial ``epoch_open``,
    ``emergency_quarantine``) are committed standalone as-is.
    """
    entries: list[dict] = []
    pending: list[dict] | None = None
    pending_tid: str | None = None

    def _entry(kind: str, tid: str | None, group: list[dict]) -> dict:
        counts: dict[str, int] = {}
        rule_ids: list[str] = []
        epoch_closed = None
        epoch_opened = None
        for ln in group:
            rec = ln["record"]
            et = str(rec.get("event_type", ""))
            counts[et] = counts.get(et, 0) + 1
            payload = rec.get("payload")
            payload = payload if isinstance(payload, dict) else {}
            rid = payload.get("rule_id")
            if isinstance(rid, str) and rid and rid not in rule_ids:
                rule_ids.append(rid)
            if et == "epoch_close":
                epoch_closed = payload.get("epoch_id")
            elif et == "epoch_open":
                es = payload.get("epoch_state")
                if isinstance(es, dict):
                    epoch_opened = es.get("epoch_id")
        last = group[-1]["record"]
        return {
            "kind": kind,
            "transition_id": tid,
            "byte_offset": group[0]["offset"],
            "lines": group,
            "event_count": len(group),
            "event_type_counts": counts,
            "rule_ids": sorted(rule_ids),
            "epoch_closed": epoch_closed,
            "epoch_opened": epoch_opened,
            "first_event_id": str(group[0]["record"].get("event_id", "")),
            "last_event_id": str(last.get("event_id", "")),
            "committed_at": last.get("ts_iso") or None,
        }

    for ln in lines:
        rec = ln["record"]
        et = str(rec.get("event_type", ""))
        payload = rec.get("payload")
        payload = payload if isinstance(payload, dict) else {}
        if et == "epoch_transaction_prepare":
            pending = [ln]
            pending_tid = payload.get("transition_id")
        elif et == "epoch_transaction_commit":
            if pending is not None:
                pending.append(ln)
                entries.append(_entry("transaction", pending_tid, pending))
                pending = None
                pending_tid = None
            # commit without prepare: malformed tail — ignored
        elif pending is not None:
            pending.append(ln)
        else:
            tid = payload.get("transition_id")
            entries.append(
                _entry("standalone", tid if isinstance(tid, str) else None,
                       [ln])
            )
    return entries


def _replay(entries: list[dict]) -> dict:
    """Fold committed entries into the registry/epoch read model.

    A viz-local mirror of ``apply_registry_event`` (storage semantics only:
    the last event wins; legality was the kernel's job at write time and is
    not re-judged here).  Tracks per-entry ``source_event_ids`` and the
    adoption transition per prompt so the API can cite its evidence.
    """
    components: dict[str, dict] = {}
    prompts: dict[str, dict] = {}
    adopted_via: dict[str, str | None] = {}
    epoch_opens: list[dict] = []
    reasons: list[str] = []
    last_committed_at: str | None = None

    for entry in entries:
        tid = entry["transition_id"]
        if entry["committed_at"]:
            last_committed_at = entry["committed_at"]
        for ln in entry["lines"]:
            rec = ln["record"]
            et = str(rec.get("event_type", ""))
            payload = rec.get("payload")
            payload = payload if isinstance(payload, dict) else {}
            eid = str(rec.get("event_id", ""))
            if et == "component_registered":
                cid = str(payload.get("component_id", ""))
                components[cid] = {
                    "component_id": cid,
                    "role": str(payload.get("role", "")),
                    "tier": str(payload.get("tier", "institutional")),
                    "status": str(payload.get("status", "candidate")),
                    "prompt_id": payload.get("prompt_id"),
                    "epoch_id_registered": str(payload.get("epoch_id", "")),
                    "capabilities": dict(payload.get("capabilities") or {}),
                    "source_event_ids": [eid],
                }
            elif et == "prompt_registered":
                pid = str(payload.get("prompt_id", ""))
                prompts[pid] = {
                    "prompt_id": pid,
                    "role": str(payload.get("role", "")),
                    "status": str(payload.get("status", "candidate")),
                    "prompt_hash": str(payload.get("prompt_hash", "")),
                    "prompt_sha256": str(payload.get("prompt_sha256", "")),
                    "source": dict(payload.get("source") or {}),
                    "spec_ref": payload.get("spec_ref"),
                    "epoch_id_registered": str(payload.get("epoch_id", "")),
                    "source_event_ids": [eid],
                }
                if prompts[pid]["status"] in ACTIVE_STATUSES:
                    # Founding registrations may be born active — there is
                    # no adoption transition to cite ("when applicable").
                    adopted_via.setdefault(pid, None)
            elif et == "component_status_change":
                cid = str(payload.get("component_id", ""))
                if cid in components:
                    components[cid]["status"] = str(
                        payload.get("to_status", "")
                    )
                    components[cid]["source_event_ids"].append(eid)
                elif len(reasons) < _MAX_REASONS_PER_SOURCE:
                    reasons.append(
                        f"component_status_change for unknown id {cid} "
                        f"skipped"
                    )
            elif et == "prompt_status_change":
                pid = str(payload.get("prompt_id", ""))
                if pid in prompts:
                    to_status = str(payload.get("to_status", ""))
                    prompts[pid]["status"] = to_status
                    prompts[pid]["source_event_ids"].append(eid)
                    if to_status in ACTIVE_STATUSES:
                        adopted_via[pid] = (
                            payload.get("transition_id") or tid
                        )
                elif len(reasons) < _MAX_REASONS_PER_SOURCE:
                    reasons.append(
                        f"prompt_status_change for unknown id {pid} skipped"
                    )
            elif et == "emergency_quarantine":
                to_status = str(payload.get("to_status", "quarantine"))
                cid = payload.get("component_id")
                pid = payload.get("prompt_id")
                if cid and cid in components:
                    components[cid]["status"] = to_status
                    components[cid]["source_event_ids"].append(eid)
                if pid and pid in prompts:
                    prompts[pid]["status"] = to_status
                    prompts[pid]["source_event_ids"].append(eid)
            elif et == "epoch_open":
                es = payload.get("epoch_state")
                if isinstance(es, dict):
                    policy = es.get("utility_policy")
                    policy = policy if isinstance(policy, dict) else {}
                    epoch_opens.append({
                        "epoch_id": es.get("epoch_id"),
                        "policy_hash": policy.get("utility_policy_hash"),
                        "transition_id": tid,
                        "event_id": eid,
                        "epoch_state": es,
                    })
    return {
        "components": components,
        "prompts": prompts,
        "adopted_via": adopted_via,
        "epoch_opens": epoch_opens,
        "reasons": reasons,
        "last_committed_at": last_committed_at,
    }


def _load_transitions(ckpt: Path) -> dict:
    """Scan + verify + group + replay ``rqgm_transitions.jsonl`` once."""
    path = ckpt / RQGM_TRANSITIONS_FILENAME
    if not path.exists():
        return {
            "present": False,
            "lines": [],
            "entries": [],
            "chain_ok": None,
            "parsed_end": 0,
            "tail_hash": None,
            "reasons": [f"{RQGM_TRANSITIONS_FILENAME} is missing"],
            "replay": _replay([]),
        }
    lines, parsed_end, scan_reasons = _scan_jsonl(path)
    chain_ok, chain_reasons = _verify_chain(path.name, lines)
    entries = _group_committed(lines)
    replay = _replay(entries)
    tail_hash = (
        str(lines[-1]["record"].get("event_hash", "")) if lines else ""
    )
    return {
        "present": True,
        "lines": lines,
        "entries": entries,
        "chain_ok": chain_ok,
        "parsed_end": parsed_end,
        "tail_hash": tail_hash,
        "reasons": scan_reasons + chain_reasons + replay["reasons"],
        "replay": replay,
    }


def _load_audit(ckpt: Path) -> dict:
    """Scan + verify ``rqgm_audit.jsonl`` (independent chain, no
    transactions: every terminated line is committed as-is)."""
    path = ckpt / RQGM_AUDIT_FILENAME
    if not path.exists():
        return {
            "present": False,
            "lines": [],
            "chain_ok": None,
            "parsed_end": 0,
            "reasons": [f"{RQGM_AUDIT_FILENAME} is missing"],
        }
    lines, parsed_end, scan_reasons = _scan_jsonl(path)
    chain_ok, chain_reasons = _verify_chain(path.name, lines)
    return {
        "present": True,
        "lines": lines,
        "chain_ok": chain_ok,
        "parsed_end": parsed_end,
        "reasons": scan_reasons + chain_reasons,
    }


def _load_adversarial(ckpt: Path) -> dict:
    """Read ``rqgm_adversarial_cases.jsonl`` (plain JSONL — not chained;
    torn trailing line ignored)."""
    path = ckpt / RQGM_ADVERSARIAL_FILENAME
    if not path.exists():
        return {"present": False, "records": [], "reasons": []}
    lines, _end, reasons = _scan_jsonl(path)
    return {
        "present": True,
        "records": [ln["record"] for ln in lines],
        "reasons": reasons,
    }


def _registry_verified(
    ckpt: Path, tail_hash: str | None
) -> tuple[bool | None, dict | None, list[str]]:
    """The rollup-vs-replay rule: ``rqgm_registry.json`` ``as_of_event_hash``
    must equal the transitions replay tail (plan 08 §Truth rules — the
    snapshot is used for verification only, never as current state)."""
    rollup = _read_json(ckpt / RQGM_REGISTRY_FILENAME)
    if rollup is None:
        return None, None, [f"{RQGM_REGISTRY_FILENAME} is missing/unreadable"]
    if tail_hash is None:
        return None, rollup, []
    claimed = rollup.get("as_of_event_hash")
    if claimed == tail_hash:
        return True, rollup, []
    return False, rollup, [
        f"{RQGM_REGISTRY_FILENAME} as_of_event_hash {claimed!r} does not "
        f"match the committed transitions tail {tail_hash!r} (stale/ahead "
        f"rollup)"
    ]


# ── query-string helpers ───────────────────────────────────────────────────


def _parse_cursor_limit(
    query: dict[str, str]
) -> tuple[int, int, bool, dict | None]:
    """Parse ``cursor``/``limit``/``expand``: returns ``(cursor, limit,
    expand, error_envelope_or_None)``."""
    cursor_raw = query.get("cursor", "0") or "0"
    limit_raw = query.get("limit", str(_DEFAULT_LIMIT)) or str(_DEFAULT_LIMIT)
    if not cursor_raw.lstrip("-").isdigit() or int(cursor_raw) < 0:
        return 0, 0, False, error_response(
            "invalid_request",
            f"cursor must be a non-negative integer (got {cursor_raw!r})",
            request_id="",
            status=400,
        )
    if not limit_raw.lstrip("-").isdigit() or not (
        1 <= int(limit_raw) <= _MAX_LIMIT
    ):
        return 0, 0, False, error_response(
            "invalid_request",
            f"limit must be an integer in [1, {_MAX_LIMIT}] "
            f"(got {limit_raw!r})",
            request_id="",
            status=400,
        )
    expand = query.get("expand", "") in ("1", "true")
    return int(cursor_raw), int(limit_raw), expand, None


def _summarize(payload: dict) -> dict:
    """Bounded payload summary: scalars kept (long strings truncated),
    arrays summarized as ``<key>_count``, nested objects deferred to
    ``?expand=1``."""
    out: dict = {}
    for k, v in payload.items():
        if isinstance(v, (list, tuple)):
            out[f"{k}_count"] = len(v)
        elif isinstance(v, str):
            out[k] = v if len(v) <= 120 else v[:117] + "..."
        elif v is None or isinstance(v, (bool, int, float)):
            out[k] = v
    return out


# ── run/RQGM gating ────────────────────────────────────────────────────────


def _resolve(run_id: str) -> Path | dict:
    d = _resolve_checkpoint_dir(run_id)
    if d is None:
        return error_response(
            "not_found", f"unknown run: {run_id}", request_id="", status=404
        )
    return d


def _require_rqgm(run_id: str) -> Path | dict:
    """404 envelope for non-RQGM runs (every endpoint except capabilities):
    artifact presence is the capability signal (absence == pure
    ``simple_bfts``)."""
    d = _resolve(run_id)
    if isinstance(d, dict):
        return d
    if not (d / RQGM_STATE_FILENAME).exists():
        return error_response(
            "not_found",
            f"run {run_id} is not an RQGM run (no {RQGM_STATE_FILENAME}; "
            f"simple_bfts run)",
            request_id="",
            status=404,
        )
    return d


# ── endpoint queries ───────────────────────────────────────────────────────


def get_capabilities(run_id: str) -> RqgmCapabilitiesV1 | dict:
    """GET /api/v1/runs/{run_id}/rqgm/capabilities."""
    d = _resolve(run_id)
    if isinstance(d, dict):
        return d
    paper_mode = (d / PAPER_ARCHIVE_STATE_FILENAME).exists()
    state_path = d / RQGM_STATE_FILENAME
    if not state_path.exists():
        return RqgmCapabilitiesV1(
            run_id=run_id,
            enabled=False,
            paper_mode=paper_mode,
            reasons=["simple_bfts run"],
        )
    state = _read_json(state_path)
    if state is None:
        return RqgmCapabilitiesV1(
            run_id=run_id,
            enabled=False,
            paper_mode=paper_mode,
            reasons=[f"{RQGM_STATE_FILENAME} is unreadable"],
        )
    mode = state.get("mode")
    enabled = bool(state.get("rqgm_enabled", mode == "ari_rqgm"))
    reasons: list[str] = []
    if not enabled:
        reasons.append(
            f"{RQGM_STATE_FILENAME} records mode {mode!r} "
            f"(rqgm_enabled false)"
        )
    return RqgmCapabilitiesV1(
        run_id=run_id,
        enabled=enabled,
        mode=mode if isinstance(mode, str) else None,
        mode_source=(
            state.get("mode_source")
            if isinstance(state.get("mode_source"), str)
            else None
        ),
        paper_mode=paper_mode,
        reasons=reasons,
    )


def get_overview(run_id: str) -> RqgmOverviewV1 | dict:
    """GET /api/v1/runs/{run_id}/rqgm/overview — bounded summary (no
    embedded transition/audit/node lists)."""
    d = _require_rqgm(run_id)
    if isinstance(d, dict):
        return d
    trans = _load_transitions(d)
    audit = _load_audit(d)
    verified, _rollup, verify_reasons = _registry_verified(
        d, trans["tail_hash"] if trans["present"] else None
    )
    replay = trans["replay"]

    current_epoch = None
    policy_hash = None
    if replay["epoch_opens"]:
        current_epoch = replay["epoch_opens"][-1]["epoch_id"]
        policy_hash = replay["epoch_opens"][-1]["policy_hash"]

    reasons = list(trans["reasons"]) + verify_reasons + list(audit["reasons"])

    # Snapshot-vs-truth epoch cross-check (verification only — the snapshot
    # never becomes current state).
    es = _read_json(d / "epoch_state.json")
    if es is not None and current_epoch is not None:
        snap_epoch = es.get("epoch_id")
        if snap_epoch != current_epoch:
            reasons.append(
                f"epoch_state.json snapshot names {snap_epoch!r} but "
                f"committed transitions end at {current_epoch!r} (snapshot "
                f"ahead of the truth log)"
            )

    meta = _read_json(d / "meta.json")
    constitution_hash = None
    if meta is not None and isinstance(meta.get("constitution_hash"), str):
        constitution_hash = meta["constitution_hash"]
    else:
        reasons.append("meta.json carries no constitution_hash")

    comp_by_status: dict[str, int] = {}
    prompt_by_status: dict[str, int] = {}
    for e in replay["components"].values():
        if e["status"] in REGISTRY_STATUSES:
            comp_by_status[e["status"]] = (
                comp_by_status.get(e["status"], 0) + 1
            )
        else:
            reasons.append(
                f"component {e['component_id']} carries unknown status "
                f"{e['status']!r} — excluded from counts"
            )
    for e in replay["prompts"].values():
        if e["status"] in REGISTRY_STATUSES:
            prompt_by_status[e["status"]] = (
                prompt_by_status.get(e["status"], 0) + 1
            )
        else:
            reasons.append(
                f"prompt {e['prompt_id']} carries unknown status "
                f"{e['status']!r} — excluded from counts"
            )

    return RqgmOverviewV1(
        run_id=run_id,
        current_epoch=current_epoch,
        utility_policy_hash=policy_hash,
        constitution_hash=constitution_hash,
        registry_summary=RqgmRegistrySummaryV1(
            component_count=len(replay["components"]),
            prompt_count=len(replay["prompts"]),
            components_by_status=comp_by_status,
            prompts_by_status=prompt_by_status,
        ),
        last_committed_transition_at=replay["last_committed_at"],
        integrity=RqgmIntegrityV1(
            transitions_chain_ok=trans["chain_ok"],
            registry_verified=verified,
            audit_chain_ok=audit["chain_ok"],
        ),
        degraded_reasons=reasons,
    )


def _active_map(entries: dict[str, dict], value_key: str) -> dict[str, str]:
    """``role -> value`` over the active statuses, latest-registered wins
    (replay order is file order — deterministic)."""
    out: dict[str, str] = {}
    for e in entries.values():
        if e["status"] in ACTIVE_STATUSES:
            out[e["role"]] = e[value_key]
    return out


def get_registry(run_id: str) -> RqgmRegistryV1 | dict:
    """GET /api/v1/runs/{run_id}/rqgm/registry."""
    d = _require_rqgm(run_id)
    if isinstance(d, dict):
        return d
    trans = _load_transitions(d)
    replay = trans["replay"]
    verified, rollup, verify_reasons = _registry_verified(
        d, trans["tail_hash"] if trans["present"] else None
    )
    reasons = list(trans["reasons"]) + verify_reasons

    components: list[RqgmComponentV1] = []
    for e in replay["components"].values():
        if e["status"] not in REGISTRY_STATUSES:
            reasons.append(
                f"component {e['component_id']} carries unknown status "
                f"{e['status']!r} — excluded"
            )
            continue
        components.append(RqgmComponentV1(**e))
    prompts: list[RqgmPromptV1] = []
    for e in replay["prompts"].values():
        if e["status"] not in REGISTRY_STATUSES:
            reasons.append(
                f"prompt {e['prompt_id']} carries unknown status "
                f"{e['status']!r} — excluded"
            )
            continue
        prompts.append(RqgmPromptV1(**e))

    return RqgmRegistryV1(
        run_id=run_id,
        verified=verified,
        rollup_as_of_event_hash=(
            rollup.get("as_of_event_hash") if rollup is not None else None
        ),
        replay_tail_event_hash=trans["tail_hash"],
        components=components,
        prompts=prompts,
        active_components=_active_map(replay["components"], "component_id"),
        active_prompt_hashes=_active_map(replay["prompts"], "prompt_hash"),
        degraded_reasons=reasons,
    )


def list_transitions(
    run_id: str, query: dict[str, str]
) -> RqgmTransitionsPageV1 | dict:
    """GET /api/v1/runs/{run_id}/rqgm/transitions?cursor=&limit=&expand=."""
    d = _require_rqgm(run_id)
    if isinstance(d, dict):
        return d
    cursor, limit, expand, err = _parse_cursor_limit(query)
    if err is not None:
        return err
    trans = _load_transitions(d)
    entries_all = trans["entries"]
    window = [e for e in entries_all if e["byte_offset"] >= cursor]
    page, rest = window[:limit], window[limit:]
    dto_entries = [
        RqgmTransitionEntryV1(
            kind=e["kind"],
            transition_id=e["transition_id"],
            byte_offset=e["byte_offset"],
            event_count=e["event_count"],
            event_type_counts=e["event_type_counts"],
            rule_ids=e["rule_ids"],
            epoch_closed=e["epoch_closed"],
            epoch_opened=e["epoch_opened"],
            first_event_id=e["first_event_id"],
            last_event_id=e["last_event_id"],
            committed_at=e["committed_at"],
            events=[ln["record"] for ln in e["lines"]] if expand else None,
        )
        for e in page
    ]
    return RqgmTransitionsPageV1(
        run_id=run_id,
        entries=dto_entries,
        next_cursor=rest[0]["byte_offset"] if rest else None,
        total_entries=len(entries_all),
        chain_ok=trans["chain_ok"],
        source_revision=trans["parsed_end"],
        degraded_reasons=list(trans["reasons"]),
    )


def list_audit(
    run_id: str, query: dict[str, str]
) -> RqgmAuditPageV1 | dict:
    """GET /api/v1/runs/{run_id}/rqgm/audit?cursor=&limit=&record_type=&epoch=."""
    d = _require_rqgm(run_id)
    if isinstance(d, dict):
        return d
    cursor, limit, expand, err = _parse_cursor_limit(query)
    if err is not None:
        return err
    record_type = query.get("record_type") or None
    epoch = query.get("epoch") or None
    audit = _load_audit(d)

    filtered: list[dict] = []
    for ln in audit["lines"]:
        rec = ln["record"]
        payload = rec.get("payload")
        payload = payload if isinstance(payload, dict) else {}
        et = str(rec.get("event_type", ""))
        rt = payload.get("record_type")
        if record_type is not None and record_type not in (et, rt):
            continue
        if epoch is not None and payload.get("epoch_id") != epoch:
            continue
        filtered.append(ln)

    window = [ln for ln in filtered if ln["offset"] >= cursor]
    page, rest = window[:limit], window[limit:]
    entries: list[RqgmAuditEntryV1] = []
    for ln in page:
        rec = ln["record"]
        payload = rec.get("payload")
        payload = payload if isinstance(payload, dict) else {}
        entries.append(RqgmAuditEntryV1(
            byte_offset=ln["offset"],
            event_id=str(rec.get("event_id", "")),
            event_type=str(rec.get("event_type", "")),
            record_id=(
                payload.get("record_id")
                if isinstance(payload.get("record_id"), str)
                else None
            ),
            record_type=(
                payload.get("record_type")
                if isinstance(payload.get("record_type"), str)
                else None
            ),
            epoch_id=(
                payload.get("epoch_id")
                if isinstance(payload.get("epoch_id"), str)
                else None
            ),
            event_hash=str(rec.get("event_hash", "")),
            ts_iso=rec.get("ts_iso") or None,
            summary=_summarize(payload),
            payload=dict(payload) if expand else None,
        ))
    return RqgmAuditPageV1(
        run_id=run_id,
        entries=entries,
        next_cursor=rest[0]["offset"] if rest else None,
        total_entries=len(filtered),
        chain_ok=audit["chain_ok"],
        source_revision=audit["parsed_end"],
        degraded_reasons=list(audit["reasons"]),
    )


def _node_state(metrics: dict) -> str:
    """Node score state from the sentinel set (plan 10/14 vocabulary):
    ``utility_invalidated`` staleness is the policy-rewrite invalidation."""
    if metrics.get("_stale_reason") == "utility_invalidated":
        return "invalidated"
    if metrics.get("_stale"):
        return "stale"
    return "computed"


_PENALTY_SENTINELS = ("_pre_penalty_score", "_validated_attack_penalty")
_POLICY_SENTINELS = (
    "_scientific_score",
    "_stale",
    "_valid_for_frontier",
    "_stale_reason",
    "_erasure_event_id",
)


def get_node_lineage(
    run_id: str, node_id: str
) -> RqgmNodeLineageV1 | dict:
    """GET /api/v1/runs/{run_id}/rqgm/nodes/{node_id}/lineage — the two
    independent channels (plan 08 §Score Lineage), never merged."""
    d = _require_rqgm(run_id)
    if isinstance(d, dict):
        return d
    tree = build_tree_view(d)
    nodes = tree.get("nodes", []) if isinstance(tree, dict) else []
    node = next(
        (n for n in nodes if isinstance(n, dict) and n.get("id") == node_id),
        None,
    )
    if node is None:
        return error_response(
            "not_found",
            f"unknown node in run {run_id}: {node_id}",
            request_id="",
            status=404,
        )
    metrics = node.get("metrics")
    metrics = metrics if isinstance(metrics, dict) else {}
    adv = _load_adversarial(d)
    audit = _load_audit(d)
    reasons = list(adv["reasons"]) + (
        list(audit["reasons"]) if audit["present"] else []
    )
    state = _node_state(metrics)
    stamp = metrics.get("_utility_policy_hash")
    stamp = stamp if isinstance(stamp, str) else None

    penalty_channel: list[RqgmScoreObservationV1] = []
    policy_channel: list[RqgmScoreObservationV1] = []
    raw_attacks: list[RqgmRawAttackV1] = []
    validated_attacks: list[RqgmValidatedAttackV1] = []

    # channel 1 — adversarial penalty (epoch-internal, node-scoped)
    if any(k in metrics for k in _PENALTY_SENTINELS):
        penalty_channel.append(RqgmScoreObservationV1(
            source="node_metrics",
            policy_hash=stamp,
            values={
                k: metrics[k]
                for k in (*_PENALTY_SENTINELS, "_scientific_score")
                if k in metrics
            },
            state=state,
        ))
    for rec in adv["records"]:
        rt = rec.get("record_type")
        if rt == "utility_record" and rec.get("node_id") == node_id:
            refs = rec.get("input_refs")
            refs = refs if isinstance(refs, dict) else {}
            vat_ids = refs.get("validated_attack_ids")
            penalty_channel.append(RqgmScoreObservationV1(
                source="utility_record",
                record_id=rec.get("record_id"),
                epoch_id=rec.get("epoch_id"),
                policy_hash=(
                    rec.get("utility_policy_hash")
                    if isinstance(rec.get("utility_policy_hash"), str)
                    else None
                ),
                values={
                    k: rec.get(k)
                    for k in (
                        "base_score", "penalty", "final_score",
                        "supersedes", "recomputed_in_epoch",
                    )
                    if k in rec
                },
                state=(
                    "recomputed" if rec.get("recomputed_in_epoch")
                    else "computed"
                ),
                validated_attack_ids=(
                    [str(v) for v in vat_ids]
                    if isinstance(vat_ids, list) else []
                ),
            ))
        elif rt == "raw_attack":
            target = rec.get("target_artifact")
            target = target if isinstance(target, dict) else {}
            if target.get("node_id") == node_id:
                raw_attacks.append(RqgmRawAttackV1(
                    record_id=str(rec.get("record_id", "")),
                    adversary_type=rec.get("adversary_type"),
                    severity_claimed=rec.get("severity_claimed"),
                    status=rec.get("status"),
                    epoch_id=rec.get("epoch_id"),
                    target_node_id=node_id,
                ))
        elif rt == "validated_attack" and rec.get("source_node_id") == node_id:
            affected = rec.get("affected_components")
            validated_attacks.append(RqgmValidatedAttackV1(
                record_id=str(rec.get("record_id", "")),
                raw_attack_id=rec.get("raw_attack_id"),
                judgment_id=rec.get("judgment_id"),
                verdict=rec.get("verdict"),
                severity=rec.get("severity"),
                affected_components=(
                    [str(c) for c in affected]
                    if isinstance(affected, list) else []
                ),
                target_component_id=rec.get("target_component_id") or None,
                epoch_id=rec.get("epoch_id"),
            ))

    # channel 2 — epoch-boundary policy rewrite (run-wide)
    if stamp is not None or any(k in metrics for k in _POLICY_SENTINELS[1:]):
        policy_channel.append(RqgmScoreObservationV1(
            source="node_metrics",
            record_id=(
                metrics.get("_erasure_event_id")
                if isinstance(metrics.get("_erasure_event_id"), str)
                else None
            ),
            policy_hash=stamp,
            values={k: metrics[k] for k in _POLICY_SENTINELS if k in metrics},
            state=state,
        ))
    for ln in audit["lines"]:
        rec = ln["record"]
        payload = rec.get("payload")
        payload = payload if isinstance(payload, dict) else {}
        rt = payload.get("record_type")
        if rt == "SelectiveErasureEvent":
            retired = payload.get("retired_prompt_hashes")
            retired = retired if isinstance(retired, list) else []
            ehash = retired[0] if len(retired) == 1 else None
            inv = payload.get("invalidated_node_ids") or []
            rec_ids = payload.get("recompute_node_ids") or []
            if node_id in inv:
                policy_channel.append(RqgmScoreObservationV1(
                    source="erasure_event",
                    record_id=payload.get("record_id"),
                    epoch_id=payload.get("epoch_id"),
                    policy_hash=ehash,
                    values={
                        "invalidated": True,
                        "retired_prompt_hashes": [str(h) for h in retired],
                    },
                    state="invalidated",
                ))
            if node_id in rec_ids:
                policy_channel.append(RqgmScoreObservationV1(
                    source="erasure_event",
                    record_id=payload.get("record_id"),
                    epoch_id=payload.get("epoch_id"),
                    policy_hash=ehash,
                    values={"recompute": True},
                    state="recomputed",
                ))
        elif rt == "FrontierRebuildEvent":
            values: dict = {}
            if node_id in (payload.get("removed_node_ids") or []):
                values["frontier_removed"] = True
            if node_id in (payload.get("reinstated_node_ids") or []):
                values["frontier_reinstated"] = True
            if node_id in (payload.get("recomputed_utility_node_ids") or []):
                values["recomputed_utility"] = True
            if values:
                policy_channel.append(RqgmScoreObservationV1(
                    source="erasure_event",
                    record_id=payload.get("record_id"),
                    epoch_id=payload.get("epoch_id"),
                    values=values,
                    state=None,  # frontier fact, not a score-state claim
                ))

    return RqgmNodeLineageV1(
        run_id=run_id,
        node_id=node_id,
        penalty_channel=penalty_channel,
        policy_channel=policy_channel,
        raw_attacks=raw_attacks,
        validated_attacks=validated_attacks,
        degraded_reasons=reasons,
    )


def _rewrite_entries(trans: dict, audit: dict) -> tuple[list[dict], list[str]]:
    """Join T20 utility-policy supersessions (committed transitions) with
    their SelectiveErasureEvent / FrontierRebuildEvent consequences (audit).
    Node sets are copied from the real event fields, never recomputed."""
    prompts = trans["replay"]["prompts"]
    reasons: list[str] = []

    erasures: list[dict] = []
    rebuilds: list[dict] = []
    for ln in audit["lines"]:
        payload = ln["record"].get("payload")
        payload = payload if isinstance(payload, dict) else {}
        rt = payload.get("record_type")
        if rt == "SelectiveErasureEvent":
            erasures.append(payload)
        elif rt == "FrontierRebuildEvent":
            rebuilds.append(payload)

    def _joined_rebuilds(erase_id: str | None) -> list[dict]:
        if not erase_id:
            return []
        return [
            rb for rb in rebuilds
            if erase_id in (rb.get("source_refs") or [])
        ]

    entries: list[dict] = []
    used_erasures: set[str] = set()
    used_rebuilds: set[str] = set()

    for e in trans["entries"]:
        if e["kind"] != "transaction":
            continue
        retired: list[tuple[str, str]] = []  # (prompt_id, hash)
        adopted: list[tuple[str, str]] = []
        source_event_ids: list[str] = []
        for ln in e["lines"]:
            rec = ln["record"]
            if rec.get("event_type") != "prompt_status_change":
                continue
            payload = rec.get("payload")
            payload = payload if isinstance(payload, dict) else {}
            pid = str(payload.get("prompt_id", ""))
            entry = prompts.get(pid)
            if entry is None or entry["role"] != _UTILITY_POLICY_ROLE:
                continue
            to_status = str(payload.get("to_status", ""))
            if to_status == "retired":
                retired.append((pid, entry["prompt_hash"]))
                source_event_ids.append(str(rec.get("event_id", "")))
            elif to_status in ACTIVE_STATUSES:
                adopted.append((pid, entry["prompt_hash"]))
                source_event_ids.append(str(rec.get("event_id", "")))
        if not retired and not adopted:
            continue
        from_hash = retired[0][1] if len(retired) == 1 else None
        to_hash = adopted[0][1] if len(adopted) == 1 else None
        if len(retired) > 1 or len(adopted) > 1:
            reasons.append(
                f"transition {e['transition_id']}: multiple utility_policy "
                f"retirements/adoptions — from/to hashes left unknown"
            )
        invalidated: list[str] = []
        recompute: list[str] = []
        removed: list[str] = []
        reinstated: list[str] = []
        for er in erasures:
            if from_hash is None or from_hash not in (
                er.get("retired_prompt_hashes") or []
            ):
                continue
            er_id = er.get("record_id")
            if isinstance(er_id, str):
                used_erasures.add(er_id)
                source_event_ids.append(er_id)
            invalidated.extend(er.get("invalidated_node_ids") or [])
            recompute.extend(er.get("recompute_node_ids") or [])
            for rb in _joined_rebuilds(
                er_id if isinstance(er_id, str) else None
            ):
                rb_id = rb.get("record_id")
                if isinstance(rb_id, str):
                    used_rebuilds.add(rb_id)
                    source_event_ids.append(rb_id)
                removed.extend(rb.get("removed_node_ids") or [])
                reinstated.extend(rb.get("reinstated_node_ids") or [])
        entries.append({
            "rewrite_id": f"rewrite_{e['transition_id']}",
            "transition_id": e["transition_id"],
            "epoch_id": e["epoch_opened"],
            "from_policy_hash": from_hash,
            "to_policy_hash": to_hash,
            "invalidated_node_ids": [str(x) for x in invalidated],
            "recompute_node_ids": [str(x) for x in recompute],
            "frontier_removed_node_ids": [str(x) for x in removed],
            "frontier_reinstated_node_ids": [str(x) for x in reinstated],
            "source_event_ids": source_event_ids,
        })

    # Unjoined audit events still surface (a rewrite without its adoption
    # transition is shown as such, never hidden).
    for er in erasures:
        er_id = er.get("record_id")
        if isinstance(er_id, str) and er_id in used_erasures:
            continue
        retired = er.get("retired_prompt_hashes") or []
        removed = []
        reinstated = []
        source_event_ids = [er_id] if isinstance(er_id, str) else []
        for rb in _joined_rebuilds(er_id if isinstance(er_id, str) else None):
            rb_id = rb.get("record_id")
            if isinstance(rb_id, str):
                used_rebuilds.add(rb_id)
                source_event_ids.append(rb_id)
            removed.extend(rb.get("removed_node_ids") or [])
            reinstated.extend(rb.get("reinstated_node_ids") or [])
        entries.append({
            "rewrite_id": f"rewrite_{er_id or 'unknown_erasure'}",
            "transition_id": None,
            "epoch_id": er.get("epoch_id"),
            "from_policy_hash": (
                str(retired[0]) if len(retired) == 1 else None
            ),
            "to_policy_hash": None,
            "invalidated_node_ids": [
                str(x) for x in (er.get("invalidated_node_ids") or [])
            ],
            "recompute_node_ids": [
                str(x) for x in (er.get("recompute_node_ids") or [])
            ],
            "frontier_removed_node_ids": [str(x) for x in removed],
            "frontier_reinstated_node_ids": [str(x) for x in reinstated],
            "source_event_ids": source_event_ids,
        })
    for rb in rebuilds:
        rb_id = rb.get("record_id")
        if isinstance(rb_id, str) and rb_id in used_rebuilds:
            continue
        entries.append({
            "rewrite_id": f"rewrite_{rb_id or 'unknown_rebuild'}",
            "transition_id": None,
            "epoch_id": rb.get("epoch_id"),
            "from_policy_hash": None,
            "to_policy_hash": None,
            "invalidated_node_ids": [],
            "recompute_node_ids": [],
            "frontier_removed_node_ids": [
                str(x) for x in (rb.get("removed_node_ids") or [])
            ],
            "frontier_reinstated_node_ids": [
                str(x) for x in (rb.get("reinstated_node_ids") or [])
            ],
            "source_event_ids": [rb_id] if isinstance(rb_id, str) else [],
        })
    return entries, reasons


def list_score_rewrites(
    run_id: str, query: dict[str, str]
) -> RqgmScoreRewritesPageV1 | dict:
    """GET /api/v1/runs/{run_id}/rqgm/score-rewrites?cursor=&limit=."""
    d = _require_rqgm(run_id)
    if isinstance(d, dict):
        return d
    cursor, limit, _expand, err = _parse_cursor_limit(query)
    if err is not None:
        return err
    trans = _load_transitions(d)
    audit = _load_audit(d)
    raw_entries, join_reasons = _rewrite_entries(trans, audit)
    page = raw_entries[cursor:cursor + limit]
    next_cursor = (
        cursor + limit if cursor + limit < len(raw_entries) else None
    )
    return RqgmScoreRewritesPageV1(
        run_id=run_id,
        entries=[
            RqgmScoreRewriteV1(
                invalidated_node_count=len(e["invalidated_node_ids"]), **e
            )
            for e in page
        ],
        next_cursor=next_cursor,
        total_entries=len(raw_entries),
        degraded_reasons=(
            list(trans["reasons"]) + list(audit["reasons"]) + join_reasons
        ),
    )


def _policy_body(
    ckpt: Path, entry: dict, reasons: list[str]
) -> dict | None:
    """Read a write-once policy body and REFUSE bytes whose ``hash12`` no
    longer matches the registered hash (the storage face of the in-place
    mutation prohibition — surfaced as degraded, never served silently)."""
    source = entry.get("source") or {}
    rel = source.get("path")
    if not isinstance(rel, str) or not rel:
        return None
    try:
        path = (ckpt / rel).resolve()
        if not str(path).startswith(str(ckpt.resolve())):
            reasons.append(
                f"policy body path {rel!r} escapes the checkpoint — refused"
            )
            return None
        text = path.read_text(encoding="utf-8")
    except OSError:
        reasons.append(f"policy body {rel!r} is unreadable")
        return None
    if _hash12(text) != entry["prompt_hash"]:
        reasons.append(
            f"policy body {rel!r} hashes to {_hash12(text)}, expected "
            f"{entry['prompt_hash']} (in-place mutation is prohibited) — "
            f"body withheld"
        )
        return None
    try:
        body = json.loads(text)
    except ValueError:
        reasons.append(f"policy body {rel!r} is not valid JSON")
        return None
    return body if isinstance(body, dict) else None


def list_policies(run_id: str) -> RqgmPoliciesV1 | dict:
    """GET /api/v1/runs/{run_id}/rqgm/policies — the governed epoch utility
    policies (role ``utility_policy``)."""
    d = _require_rqgm(run_id)
    if isinstance(d, dict):
        return d
    trans = _load_transitions(d)
    replay = trans["replay"]
    reasons = list(trans["reasons"])

    current_policy_hash = None
    if replay["epoch_opens"]:
        current_policy_hash = replay["epoch_opens"][-1]["policy_hash"]

    policies: list[RqgmPolicyV1] = []
    for e in replay["prompts"].values():
        if e["role"] != _UTILITY_POLICY_ROLE:
            continue
        if e["status"] not in REGISTRY_STATUSES:
            reasons.append(
                f"policy prompt {e['prompt_id']} carries unknown status "
                f"{e['status']!r} — excluded"
            )
            continue
        policies.append(RqgmPolicyV1(
            prompt_id=e["prompt_id"],
            policy_hash=e["prompt_hash"],
            status=e["status"],
            epoch_id_registered=e["epoch_id_registered"],
            adopted_via=replay["adopted_via"].get(e["prompt_id"]),
            body=_policy_body(d, e, reasons),
            epochs_used=[
                str(op["epoch_id"])
                for op in replay["epoch_opens"]
                if op["policy_hash"] == e["prompt_hash"]
                and op["epoch_id"] is not None
            ],
        ))
    return RqgmPoliciesV1(
        run_id=run_id,
        current_policy_hash=current_policy_hash,
        policies=policies,
        degraded_reasons=reasons,
    )


# ── Wave 4b: epochs / evolution / paper-archive ────────────────────────────


def _transaction_ref(entry: dict) -> RqgmTransactionRefV1:
    return RqgmTransactionRefV1(
        kind=entry["kind"],
        transition_id=entry["transition_id"],
        byte_offset=entry["byte_offset"],
        first_event_id=entry["first_event_id"],
        last_event_id=entry["last_event_id"],
        event_count=entry["event_count"],
        committed_at=entry["committed_at"],
    )


def _boundary_counts(entry: dict) -> dict[str, int]:
    """Bucket one committed boundary entry's REAL status-change events into
    adoptions / sanctions / retirements / bans (registrations are not status
    changes; unknown target statuses are simply not counted)."""
    counts = {"adoptions": 0, "sanctions": 0, "retirements": 0, "bans": 0}
    for ln in entry["lines"]:
        rec = ln["record"]
        et = str(rec.get("event_type", ""))
        payload = rec.get("payload")
        payload = payload if isinstance(payload, dict) else {}
        if et == "emergency_quarantine":
            counts["sanctions"] += 1
            continue
        if et not in ("component_status_change", "prompt_status_change"):
            continue
        to_status = str(payload.get("to_status", ""))
        if to_status in ACTIVE_STATUSES:
            counts["adoptions"] += 1
        elif to_status in _SANCTION_STATUSES:
            counts["sanctions"] += 1
        elif to_status == "retired":
            counts["retirements"] += 1
        elif to_status == "banned":
            counts["bans"] += 1
    return counts


def _audit_fallback_counts(audit: dict) -> dict[str, int]:
    """``transition_id -> len(fallbacks)`` joined from ``epoch_transition``
    audit records (the only artifact that carries the real ``fallbacks``
    array — the transitions log has no fallback event type)."""
    out: dict[str, int] = {}
    for ln in audit["lines"]:
        rec = ln["record"]
        if str(rec.get("event_type", "")) != "epoch_transition":
            continue
        payload = rec.get("payload")
        payload = payload if isinstance(payload, dict) else {}
        tid = payload.get("transition_id") or payload.get(
            "epoch_transition_id"
        )
        fallbacks = payload.get("fallbacks")
        if isinstance(tid, str) and isinstance(fallbacks, list):
            out[tid] = len(fallbacks)
    return out


def _epoch_entries(trans: dict, audit: dict) -> list[dict]:
    """Committed-epoch rows: each ``epoch_open`` from replay joined with the
    committed entry that CLOSED it (``boundary_committed``) and that entry's
    real status-change counts.  A live epoch has no closing boundary, so its
    ``transition_counts`` is None — never fabricated zeros."""
    closes: dict[str, dict] = {}
    opens_by_event: dict[str, dict] = {}
    for entry in trans["entries"]:
        if entry["epoch_closed"] is not None:
            closes[str(entry["epoch_closed"])] = entry
        if entry["epoch_opened"] is not None:
            opens_by_event[entry["first_event_id"]] = entry
    fallback_counts = _audit_fallback_counts(audit)

    rows: list[dict] = []
    for op in trans["replay"]["epoch_opens"]:
        epoch_id = op["epoch_id"]
        closing = (
            closes.get(str(epoch_id)) if epoch_id is not None else None
        )
        counts = None
        if closing is not None:
            counts = _boundary_counts(closing)
            counts["fallbacks"] = fallback_counts.get(
                closing["transition_id"]
            )
        # The committed entry containing this epoch_open (opening
        # transaction, or the standalone founding open).
        opening = next(
            (
                e for e in trans["entries"]
                for ln in e["lines"]
                if ln["record"].get("event_id") == op["event_id"]
            ),
            None,
        )
        rows.append({
            "epoch_id": str(epoch_id) if epoch_id is not None else "",
            "opened_at_event": op["event_id"],
            "opened_by_transition_id": op["transition_id"],
            "utility_policy_hash": op["policy_hash"],
            "boundary_committed": closing is not None,
            "closed_by_transition_id": (
                closing["transition_id"] if closing is not None else None
            ),
            "transition_counts": counts,
            "epoch_state": op["epoch_state"],
            "opening_entry": opening,
            "closing_entry": closing,
        })
    return rows


def _epoch_dto(row: dict) -> RqgmEpochV1:
    counts = row["transition_counts"]
    return RqgmEpochV1(
        epoch_id=row["epoch_id"],
        opened_at_event=row["opened_at_event"],
        opened_by_transition_id=row["opened_by_transition_id"],
        utility_policy_hash=row["utility_policy_hash"],
        boundary_committed=row["boundary_committed"],
        closed_by_transition_id=row["closed_by_transition_id"],
        transition_counts=(
            RqgmEpochTransitionCountsV1(**counts)
            if counts is not None else None
        ),
    )


def list_epochs(run_id: str) -> RqgmEpochsV1 | dict:
    """GET /api/v1/runs/{run_id}/rqgm/epochs — committed epochs from
    transitions replay, in truth-log order.  Every row carries its own
    ``utility_policy_hash`` (cross-epoch comparability is a per-policy
    question the payload makes checkable — plan 08 §Epoch Timeline)."""
    d = _require_rqgm(run_id)
    if isinstance(d, dict):
        return d
    trans = _load_transitions(d)
    audit = _load_audit(d)
    rows = _epoch_entries(trans, audit)
    return RqgmEpochsV1(
        run_id=run_id,
        epochs=[_epoch_dto(r) for r in rows],
        current_epoch=rows[-1]["epoch_id"] if rows else None,
        degraded_reasons=list(trans["reasons"]) + list(audit["reasons"]),
    )


def get_epoch(run_id: str, epoch_id: str) -> RqgmEpochDetailV1 | dict:
    """GET /api/v1/runs/{run_id}/rqgm/epochs/{epoch_id} — scalars from the
    committed ``epoch_open`` payload plus full boundary transaction refs,
    the policy body via the policies-reader path, and governance_report
    presence."""
    d = _require_rqgm(run_id)
    if isinstance(d, dict):
        return d
    trans = _load_transitions(d)
    audit = _load_audit(d)
    rows = _epoch_entries(trans, audit)
    row = next((r for r in rows if r["epoch_id"] == epoch_id), None)
    if row is None:
        return error_response(
            "not_found",
            f"run {run_id} has no committed epoch {epoch_id}",
            request_id="",
            status=404,
        )
    reasons = list(trans["reasons"]) + list(audit["reasons"])
    es = row["epoch_state"]
    es = es if isinstance(es, dict) else {}

    # Policy body through the policies reader path: the registered
    # utility_policy prompt whose hash matches this epoch's policy hash.
    policy_prompt_id = None
    policy_body = None
    phash = row["utility_policy_hash"]
    if phash is not None:
        entry = next(
            (
                e for e in trans["replay"]["prompts"].values()
                if e["role"] == _UTILITY_POLICY_ROLE
                and e["prompt_hash"] == phash
            ),
            None,
        )
        if entry is None:
            reasons.append(
                f"epoch {epoch_id}: utility policy {phash} is not a "
                f"registered utility_policy prompt — body unresolvable"
            )
        else:
            policy_prompt_id = entry["prompt_id"]
            policy_body = _policy_body(d, entry, reasons)

    report_id = None
    for ln in audit["lines"]:
        rec = ln["record"]
        payload = rec.get("payload")
        payload = payload if isinstance(payload, dict) else {}
        if (
            str(rec.get("event_type", "")) == "governance_report"
            and payload.get("epoch_id") == epoch_id
        ):
            rid = payload.get("record_id")
            report_id = rid if isinstance(rid, str) else ""
            break

    def _str_or_none(v: object) -> str | None:
        return v if isinstance(v, str) else None

    def _int_or_none(v: object) -> int | None:
        return v if isinstance(v, int) and not isinstance(v, bool) else None

    def _str_map(v: object) -> dict[str, str]:
        if not isinstance(v, dict):
            return {}
        return {
            str(k): str(val) for k, val in v.items() if isinstance(val, str)
        }

    return RqgmEpochDetailV1(
        run_id=run_id,
        epoch=_epoch_dto(row),
        epoch_seq=_int_or_none(es.get("epoch_seq")),
        status=_str_or_none(es.get("status")),
        node_count_at_open=_int_or_none(es.get("node_count_at_open")),
        previous_epoch_id=_str_or_none(es.get("previous_epoch_id")),
        registry_version=_str_or_none(es.get("registry_version")),
        epoch_fingerprint=_str_or_none(es.get("epoch_fingerprint")),
        active_components=_str_map(es.get("active_components")),
        active_prompt_hashes=_str_map(es.get("active_prompt_hashes")),
        opening_transaction=(
            _transaction_ref(row["opening_entry"])
            if row["opening_entry"] is not None else None
        ),
        closing_transaction=(
            _transaction_ref(row["closing_entry"])
            if row["closing_entry"] is not None else None
        ),
        policy_prompt_id=policy_prompt_id,
        policy_body=policy_body,
        governance_report_present=report_id is not None,
        governance_report_record_id=report_id or None,
        degraded_reasons=reasons,
    )


def get_evolution(run_id: str) -> RqgmEvolutionV1 | dict:
    """GET /api/v1/runs/{run_id}/rqgm/evolution — candidate lineage from
    ``prompt_evolution.jsonl`` plus meta outputs.  ``adopted`` comes ONLY
    from joining the proposed hash against committed registry replay; the
    raw candidate record itself can never assert adoption (plan 08: raw
    candidate, validated candidate and adopted policy are never
    conflated)."""
    d = _require_rqgm(run_id)
    if isinstance(d, dict):
        return d
    trans = _load_transitions(d)
    replay = trans["replay"]
    reasons = list(trans["reasons"])

    def _adoption(role: str, proposed_hash: str | None) -> dict:
        """Join a proposed hash against the committed replay: adopted iff a
        same-role prompt with that hash ever reached the active set."""
        if not proposed_hash:
            return {"adopted": False, "via": None, "prompt_id": None}
        for pid, entry in replay["prompts"].items():
            if entry["role"] != role:
                continue
            if entry["prompt_hash"] != proposed_hash:
                continue
            if pid in replay["adopted_via"]:
                return {
                    "adopted": True,
                    "via": replay["adopted_via"][pid],
                    "prompt_id": pid,
                }
            return {"adopted": False, "via": None, "prompt_id": pid}
        return {"adopted": False, "via": None, "prompt_id": None}

    evo_path = d / PROMPT_EVOLUTION_FILENAME
    evolution_present = evo_path.exists()
    entries: list[RqgmEvolutionEntryV1] = []
    candidates: list[dict] = []
    validations: dict[str, list[dict]] = {}
    if evolution_present:
        lines, _end, scan_reasons = _scan_jsonl(evo_path)
        reasons.extend(scan_reasons)
        for ln in lines:
            rec = ln["record"]
            rt = str(rec.get("record_type", ""))
            if rt == "prompt_candidate_validation":
                cid = str(rec.get("candidate_id", ""))
                validations.setdefault(cid, []).append(rec)
            elif rt in ("prompt_candidate", "utility_policy_candidate"):
                candidates.append(ln)
            elif rt == "comparison_observation":
                pass  # shadow observation: joins no lineage row (plan 07)
            elif len(reasons) < _MAX_REASONS_PER_SOURCE:
                reasons.append(
                    f"{PROMPT_EVOLUTION_FILENAME}: unknown record_type "
                    f"{rt!r} at byte {ln['offset']} skipped"
                )
    for ln in candidates:
        rec = ln["record"]
        rt = str(rec.get("record_type", ""))
        cid = rec.get("candidate_id")
        cid = cid if isinstance(cid, str) else None
        vals = validations.get(cid or "", [])
        role = rec.get("role")
        role = role if isinstance(role, str) else None
        if rt == "utility_policy_candidate":
            # The AUTHOR role is policy_mutator; the TARGET role — the one
            # the adoption join must use — is utility_policy (plan 14).
            proposed_policy = rec.get("policy_hash")
            proposed_policy = (
                proposed_policy if isinstance(proposed_policy, str) else None
            )
            join = _adoption(_UTILITY_POLICY_ROLE, proposed_policy)
            entries.append(RqgmEvolutionEntryV1(
                kind="utility_policy",
                record_id=str(rec.get("record_id", "")),
                candidate_id=cid,
                parent_ref=(
                    rec.get("parent_prompt_id")
                    if isinstance(rec.get("parent_prompt_id"), str)
                    else None
                ),
                proposed_policy_hash=proposed_policy,
                epoch_id=(
                    rec.get("epoch_id")
                    if isinstance(rec.get("epoch_id"), str) else None
                ),
                role=role,
                mutation_kind=(
                    rec.get("mutation_kind")
                    if isinstance(rec.get("mutation_kind"), str) else None
                ),
                status=(
                    rec.get("status")
                    if isinstance(rec.get("status"), str) else None
                ),
                validation_record_count=len(vals),
                validation_passed_count=sum(
                    1 for v in vals if v.get("passed") is True
                ),
                adopted=join["adopted"],
                adopted_via=join["via"],
                adopted_prompt_id=join["prompt_id"],
                source="prompt_evolution",
                source_offset=ln["offset"],
            ))
        else:
            proposed_prompt = rec.get("prompt_hash")
            proposed_prompt = (
                proposed_prompt if isinstance(proposed_prompt, str) else None
            )
            join = _adoption(role or "", proposed_prompt)
            entries.append(RqgmEvolutionEntryV1(
                kind="prompt",
                record_id=str(rec.get("record_id", "")),
                candidate_id=cid,
                parent_ref=(
                    rec.get("source_prompt_id")
                    if isinstance(rec.get("source_prompt_id"), str)
                    else None
                ),
                proposed_prompt_hash=proposed_prompt,
                epoch_id=(
                    rec.get("epoch_id")
                    if isinstance(rec.get("epoch_id"), str) else None
                ),
                role=role,
                mutation_kind=(
                    rec.get("mutation_kind")
                    if isinstance(rec.get("mutation_kind"), str) else None
                ),
                status=(
                    rec.get("status")
                    if isinstance(rec.get("status"), str) else None
                ),
                validation_record_count=len(vals),
                validation_passed_count=sum(
                    1 for v in vals if v.get("passed") is True
                ),
                adopted=join["adopted"],
                adopted_via=join["via"],
                adopted_prompt_id=join["prompt_id"],
                source="prompt_evolution",
                source_offset=ln["offset"],
            ))

    meta_path = d / META_OUTPUTS_FILENAME
    meta_present = meta_path.exists()
    if meta_present:
        lines, _end, scan_reasons = _scan_jsonl(meta_path)
        reasons.extend(scan_reasons)
        for ln in lines:
            rec = ln["record"]
            if str(rec.get("record_type", "")) != "meta_agent_output":
                continue
            entries.append(RqgmEvolutionEntryV1(
                kind="meta",
                record_id=str(rec.get("record_id", "")),
                candidate_id=(
                    rec.get("candidate_ref")
                    if isinstance(rec.get("candidate_ref"), str)
                    and rec.get("candidate_ref") else None
                ),
                epoch_id=(
                    rec.get("epoch_id")
                    if isinstance(rec.get("epoch_id"), str) else None
                ),
                role=(
                    rec.get("role")
                    if isinstance(rec.get("role"), str) else None
                ),
                status=(
                    rec.get("status")
                    if isinstance(rec.get("status"), str) else None
                ),
                adopted=None,  # inert provenance — not an adoptable candidate
                output_kind=(
                    rec.get("output_kind")
                    if isinstance(rec.get("output_kind"), str) else None
                ),
                target_role=(
                    rec.get("target_role")
                    if isinstance(rec.get("target_role"), str) else None
                ),
                source="meta_outputs",
                source_offset=ln["offset"],
            ))

    return RqgmEvolutionV1(
        run_id=run_id,
        evolution_present=evolution_present,
        meta_outputs_present=meta_present,
        entries=entries,
        degraded_reasons=reasons,
    )


def get_paper_archive(run_id: str) -> RqgmPaperArchiveV1 | dict:
    """GET /api/v1/runs/{run_id}/rqgm/paper-archive — bounded scalars with
    explicit absent flags (a missing artifact is never rendered as zero).
    Execution mode and paper mode are independent axes; the best-belief
    draft is a REVIEWED selection, never the governance winner."""
    d = _require_rqgm(run_id)
    if isinstance(d, dict):
        return d
    reasons: list[str] = []

    state_path = d / PAPER_ARCHIVE_STATE_FILENAME
    state_present = state_path.exists()
    state = _read_json(state_path) if state_present else None
    if state_present and state is None:
        reasons.append(f"{PAPER_ARCHIVE_STATE_FILENAME} is unreadable")
    paper_mode: str | None
    mode_source = None
    rqgm_paper_enabled = None
    fingerprint = None
    anchor_enabled = None
    if state is not None:
        paper_mode = (
            state.get("paper_mode")
            if isinstance(state.get("paper_mode"), str) else None
        )
        if paper_mode is None:
            reasons.append(
                f"{PAPER_ARCHIVE_STATE_FILENAME} carries no paper_mode"
            )
        mode_source = (
            state.get("mode_source")
            if isinstance(state.get("mode_source"), str) else None
        )
        if isinstance(state.get("rqgm_paper_enabled"), bool):
            rqgm_paper_enabled = state["rqgm_paper_enabled"]
        fingerprint = (
            state.get("paper_epoch_fingerprint")
            if isinstance(state.get("paper_epoch_fingerprint"), str)
            else None
        )
        policy = state.get("paper_utility_policy")
        if isinstance(policy, dict) and isinstance(
            policy.get("anchor_enabled"), bool
        ):
            anchor_enabled = policy["anchor_enabled"]
    else:
        # Absence of the state file IS paper mode 'linear' by the source
        # contract (plan 08 §Source artifacts); state_present=False keeps
        # the derivation transparent.
        paper_mode = "linear"

    archive_path = d / PAPER_DRAFT_ARCHIVE_FILENAME
    archive_present = archive_path.exists()
    draft_count: int | None = None
    epochs: list[str] = []
    winner_node = None
    if archive_present:
        lines, _end, scan_reasons = _scan_jsonl(archive_path)
        reasons.extend(scan_reasons)
        draft_count = len(lines)
        for ln in lines:
            rec = ln["record"]
            eid = rec.get("epoch_id")
            if isinstance(eid, str) and eid and eid not in epochs:
                epochs.append(eid)
            if rec.get("is_best_belief"):
                # Last-wins: mark_paper_draft_flags keeps exactly one flag
                # carrier, and the archive is append-only.
                nid = rec.get("node_id")
                winner_node = nid if isinstance(nid, str) else None

    stat_path = d / PAPER_SELF_PREFERENCE_STAT_RELPATH
    stat_present = stat_path.exists()
    stat = _read_json(stat_path) if stat_present else None
    if stat_present and stat is None:
        reasons.append(
            f"{PAPER_SELF_PREFERENCE_STAT_RELPATH} is unreadable"
        )

    def _num_or_none(v: object) -> float | None:
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return None
        return float(v)

    self_preference = RqgmPaperSelfPreferenceV1(stat_present=stat_present)
    if stat is not None:
        sample_ids = stat.get("sample_ids")
        self_preference = RqgmPaperSelfPreferenceV1(
            stat_present=True,
            epoch_id=(
                stat.get("epoch_id")
                if isinstance(stat.get("epoch_id"), str) else None
            ),
            margin=_num_or_none(stat.get("margin")),
            ai_mean=_num_or_none(stat.get("ai_mean")),
            human_mean=_num_or_none(stat.get("human_mean")),
            sample_count=(
                len(sample_ids) if isinstance(sample_ids, list) else None
            ),
        )

    return RqgmPaperArchiveV1(
        run_id=run_id,
        state_present=state_present,
        paper_mode=paper_mode,
        mode_source=mode_source,
        rqgm_paper_enabled=rqgm_paper_enabled,
        paper_epoch_fingerprint=fingerprint,
        archive_present=archive_present,
        epochs=epochs,
        draft_count=draft_count,
        anchor=RqgmPaperAnchorV1(
            enabled=anchor_enabled,
            corpus_present=(d / PAPER_ANCHOR_CORPUS_FILENAME).exists(),
        ),
        self_preference=self_preference,
        winner=RqgmPaperWinnerV1(
            node_id=winner_node,
            materialized=(d / FULL_PAPER_FILENAME).exists(),
        ),
        degraded_reasons=reasons,
    )
