"""Deterministic synthetic RQGM-checkpoint factory for the GUI refresh
program (Wave 4a — plan ``docs/plans/gui_refresh/08`` §Source artifacts /
§Governance state model).

``make_rqgm_checkpoint(dest, ...)`` first calls the Wave-0 base factory
(:func:`run_fixture_factory.make_run_checkpoint`) and then layers a
minimal-but-schema-valid RQGM governance surface on top, so the plan-08 read
model (Overview / Epoch Timeline / Registry / Accountability / Score Lineage)
has a real checkpoint shape to parse without ever running an ``ari_rqgm`` loop:

- ``rqgm_state.json``            — mode provenance (``mode=ari_rqgm``,
  ``mode_source=config``, ``switch_journal``); shape of
  ``ari.rqgm.state.build_run_start_state``.
- ``meta.json``                  — ``constitution_hash`` recorded additively
  via the real ``ari.rqgm.state.record_constitution_hash``.
- ``rqgm_transitions.jsonl``     — hash-chained TransitionEvent envelope
  lines (``ari.rqgm.events.TransitionEvent.to_line_dict`` key order):
  founding prepare..commit registrations, the initial ``epoch_open``, and one
  boundary transaction per later epoch. When ``with_policy_rewrite`` the
  first boundary carries the plan-14 ``utility_policy`` supersession: the
  successor policy prompt is registered and adopted (T6 shadow →
  probationary_active) and the incumbent retired (T20 active → retired).
- ``epoch_state.json``           — snapshot of the final open EpochState,
  built through the REAL ``ari.rqgm.state`` dataclass + fingerprint helpers
  (``utility_policy`` body 5 keys, sealed with ``hash12(canonical_json)``
  exactly as ``seal_utility_policy`` does — the helpers are imported, not
  re-implemented; the import is side-effect-free pure stdlib).
- ``rqgm_registry.json``         — rollup consistent with transition replay
  (``registry_version`` via the real ``GovernedPromptRegistry``,
  ``as_of_event_hash`` = last transition ``event_hash``); the factory folds
  its own events through ``ari.rqgm.registry.apply_registry_event`` so
  ``RqgmStateStore.replay`` reconstructs byte-equal state.
- ``rqgm_audit.jsonl``           — independent hash chain: one
  ``governance_report`` skeleton per epoch, plus one
  ``SelectiveErasureEvent`` + ``FrontierRebuildEvent`` pair when
  ``with_policy_rewrite`` (the plan-10 repair trail for the retired policy).
- ``rqgm_adversarial_cases.jsonl`` (``with_penalty``) — one full
  raw_attack → defender_response → judgment_record → validated_attack chain
  plus the UtilityRecord penalty audit record, built from the REAL
  ``ari.rqgm.adversarial.records`` dataclasses (raw attacks never score:
  the penalty references the ``vat_*`` id, invariant 8).
- ``rqgm_prompts/*.json``        — write-once canonical-JSON utility-policy
  bodies whose ``hash12`` IS the registered ``prompt_hash`` IS
  ``utility_policy_hash``.
- node ``metrics`` sentinels rewritten into ``tree.json`` /
  ``nodes_tree.json`` / ``results.json``: ``_utility_policy_hash`` on every
  scored node, ``_pre_penalty_score`` + ``_validated_attack_penalty`` on two
  penalised nodes, and ``_stale`` / ``_valid_for_frontier`` /
  ``_stale_reason`` / ``_erasure_event_id`` (+ the RETIRED policy hash) on
  one invalidated node — the plan-10 ``frontier_repair`` sentinel set.
- ``prompt_evolution.jsonl`` + ``rqgm_meta_outputs.jsonl``
  (``with_evolution``, Wave 4b) — a raw never-registered prompt candidate,
  a real ``UtilityPolicyCandidate`` proposing the v2 body (adopted only via
  the committed registry replay when ``with_policy_rewrite``), one
  validation-stage record, and one inert ``meta_agent_output``.
- paper layer (``with_paper``, Wave 4b) — ``paper_archive_state.json``
  (mode provenance + frozen ``paper_utility_policy`` with
  ``anchor_enabled``), ``paper_draft_archive.jsonl`` (four draft records,
  exactly one ``is_best_belief`` carrier) with matching
  ``archive/{epoch}/{node}/*.tex`` bytes, ``paper_anchor_corpus.jsonl``,
  ``rqgm/paper_self_preference_stat.json``, and the materialized winner at
  ``full_paper.tex``.

Determinism (P2): every value is a fixed literal or derived from
``(seed, field)`` via :mod:`hashlib` — no ``random``, no ``datetime.now()``.
The store/audit writers (``_append_chained`` / ``ImmutableAuditLog``) are NOT
used because ``finalize_event`` stamps wall-clock ``ts``; the factory writes
the identical line layout with fixed-arithmetic timestamps instead, importing
the hash arithmetic (``payload_hash`` / ``canonical_json`` / ``hash12``) from
``ari.rqgm.events`` so the chain verifies with the production tooling.

Corrupt modes (applied after a fully valid write):

- ``"broken_chain"``          — one ``prev_event_hash`` in
  ``rqgm_transitions.jsonl`` rewritten to a wrong (but pattern-valid) value.
- ``"truncated_transitions"`` — the final transitions line ends mid-record
  (torn append; replay drops the uncommitted boundary tail).
- ``"registry_mismatch"``     — ``rqgm_registry.json``'s
  ``as_of_event_hash`` reset to the FIRST event's hash (stale rollup).

Consumed by ``ari-core/tests/test_gui_rqgm_fixtures.py``. Fixture data is
generated on demand into a caller-supplied directory and never committed.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from ari.checkpoint import (
    save_epoch_state_json,
    save_nodes_tree_json,
    save_paper_archive_state_json,
    save_results_json,
    save_rqgm_registry_json,
    save_rqgm_state_json,
    save_tree_json,
)

# Pure, side-effect-free imports (stdlib + frozen constants only) — verified:
# ari.rqgm.events / .state / .registry / .adversarial.records execute no I/O
# at import time, so the fixture reuses the production hash arithmetic and
# record shapes instead of re-implementing them.
from ari.rqgm.adversarial.records import (
    DefenderResponse,
    EvidenceRef,
    JudgmentRecord,
    RawAttackRecord,
    TargetArtifact,
    UtilityRecord,
    ValidatedAttackRecord,
)
from ari.rqgm.events import (
    canonical_json,
    format_epoch_id,
    format_event_id,
    format_transition_id,
    hash12,
    payload_hash,
)
from ari.rqgm.paper_anchor import (
    AGREEMENT_METRIC_ID,
    PAPER_ANCHOR_CORPUS_FILENAME,
    WRITER_ANCHOR_DESCRIPTOR,
    PaperAnchorCase,
    corpus_digest,
)
from ari.rqgm.paper_self_preference import (
    PAPER_SELF_PREFERENCE_STAT_FILENAME,
    RQGM_SNAPSHOT_DIRNAME,
)
from ari.rqgm.registry import (
    ComponentRegistry,
    GovernedPromptRegistry,
    apply_registry_event,
)
from ari.rqgm.state import (
    EpochState,
    epoch_fingerprint,
    epoch_state_payload,
    execution_fingerprint,
    policy_fingerprint,
    record_constitution_hash,
    seal_utility_policy,
)
from ari.rqgm.store import (
    RQGM_AUDIT_FILENAME,
    RQGM_TRANSITIONS_FILENAME,
)
from ari.rqgm.utility_evolution import UtilityPolicyCandidate

#: ``ari.rqgm.prompt_records.PROMPT_EVOLUTION_FILENAME`` /
#: ``ari.rqgm.paper_archive.PAPER_DRAFT_ARCHIVE_FILENAME`` — frozen artifact
#: names duplicated as literals because those modules pull in heavier
#: runtime imports (prompt_loader / orchestrator.node) the pure fixture
#: avoids; parity is pinned by tests/test_gui_rqgm_fixtures.py.
PROMPT_EVOLUTION_FILENAME = "prompt_evolution.jsonl"
META_OUTPUTS_FILENAME = "rqgm_meta_outputs.jsonl"
PAPER_DRAFT_ARCHIVE_FILENAME = "paper_draft_archive.jsonl"

# ── base factory (same directory; loaded the way the tests load factories) ──

_BASE_FACTORY_PATH = Path(__file__).resolve().parent / "run_fixture_factory.py"


def _load_base_factory():
    spec = importlib.util.spec_from_file_location(
        "gui_refresh_run_fixture_factory_for_rqgm", _BASE_FACTORY_PATH
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_base = _load_base_factory()
make_run_checkpoint = _base.make_run_checkpoint
FIXED_CREATED_AT = _base.FIXED_CREATED_AT

RQGM_CORRUPT_MODES = (
    "broken_chain",
    "truncated_transitions",
    "registry_mismatch",
)

# Fixed time bases (pure arithmetic — never the wall clock). Transition and
# audit chains get disjoint ranges so their ts/ts_iso never collide.
_BASE_TS = datetime(2026, 7, 23, 0, 0, 0, tzinfo=timezone.utc).timestamp()
_AUDIT_TS_OFFSET = 10_000.0

#: The founding behavioural set: (role, component_id, prompt_id). Component
#: ids match the ids the RQGM runtime actually stamps
#: (``ari.rqgm.prompt_spec.FOUNDING_COMPONENT_TABLE``) so adversarial-record
#: ``component_id`` values resolve against the registry rollup.
_FOUNDING_ROLES: tuple[tuple[str, str, str], ...] = (
    ("adversary", "adversary_overclaim_v1", "adversary_overclaim_prompt_v1"),
    ("defender", "defender_v1", "defender_prompt_v1"),
    ("generator", "generator_v1", "generator_prompt_v1"),
    ("judge", "artifact_judge_v1", "artifact_judge_prompt_v1"),
)

UTILITY_POLICY_PROMPT_V1 = "utility_policy_prompt_v1"
UTILITY_POLICY_PROMPT_V2 = "utility_policy_prompt_v2"
UTILITY_POLICY_COMPONENT = "utility_policy_v1"

#: Frozen penalty policy (mirrors ``ari/configs/defaults.yaml``
#: ``rqgm.adversarial.penalty`` — the three keys ``MetricRecomputer`` reads).
_PENALTY_POLICY = {
    "penalty_cap": 0.5,
    "severity_weights": {
        "low": 0.05, "medium": 0.15, "high": 0.3, "critical": 0.5,
    },
    "verdict_factors": {"valid": 1.0, "partially_valid": 0.5},
}


def _hval(seed: int, *parts: object) -> int:
    """Deterministic 64-bit value (rqgm-namespaced sibling of the base
    factory's helper) — hashlib only, never ``random``."""
    key = ":".join(str(p) for p in ("gui_refresh_rqgm_fixture", seed, *parts))
    return int.from_bytes(
        hashlib.sha256(key.encode("utf-8")).digest()[:8], "big"
    )


def _iso(ts: float) -> str:
    """UTC ISO string by pure arithmetic (same format as
    ``ari.rqgm.events.finalize_event`` stamps)."""
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _prompt_hashes(seed: int, role: str) -> tuple[str, str]:
    """(prompt_sha256, prompt_hash) over a seed-derived pseudo template body
    — ``prompt_hash == sha256(text)[:12]``, the one production scheme."""
    text = f"gui_refresh rqgm fixture prompt body: role={role} seed={seed}\n"
    full = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return full, full[:12]


def _policy_bodies(seed: int) -> tuple[dict, dict]:
    """(v1, v2) utility-policy BODIES (the 5 hashed keys, unsealed).

    v1 is the ``ari.rqgm.state.utility_policy_body`` default shape; v2 is a
    seed-derived rewrite guaranteed to differ (delta > 0) so the two hashes
    are never equal.
    """
    v1 = {
        "composite": "harmonic_mean",
        "axis_weights": {
            "correctness": 0.4, "novelty": 0.3, "reproducibility": 0.3,
        },
        "frontier_score": "scientific_plus_diversity",
        "depth_penalty_lambda": 0.05,
        "ucb_c": 0.5,
    }
    delta = (_hval(seed, "policy_v2") % 199 + 1) / 1000.0  # (0, 0.199]
    v2 = dict(v1)
    v2["axis_weights"] = dict(v1["axis_weights"])
    v2["depth_penalty_lambda"] = round(0.05 + delta / 10.0, 6)
    v2["ucb_c"] = round(0.5 + delta, 6)
    return v1, v2


class _ChainWriter:
    """Deterministic writer for one hash-chained JSONL file.

    Byte layout mirrors ``ari.rqgm.store._append_chained``:
    ``json.dumps(TransitionEvent.to_line_dict(), ensure_ascii=False)`` per
    line, ``event_hash = hash12(canonical_json(payload))``,
    ``prev_event_hash`` chaining (``""`` for the first line). Timestamps are
    fixed arithmetic (P2), which is legal because ts/ts_iso are envelope
    metadata OUTSIDE the hash.
    """

    def __init__(self, base_ts: float) -> None:
        self._base_ts = base_ts
        self.lines: list[dict] = []
        self._prev = ""

    def add(self, event_type: str, payload: dict) -> dict:
        i = len(self.lines)
        ts = self._base_ts + float(i)
        eh = payload_hash(payload)
        line = {
            "schema_version": 1,
            "event_id": format_event_id(i),
            "event_type": event_type,
            "payload": payload,
            "event_hash": eh,
            "prev_event_hash": self._prev,
            "ts": ts,
            "ts_iso": _iso(ts),
        }
        self.lines.append(line)
        self._prev = eh
        return line

    @property
    def last_hash(self) -> str:
        return self._prev

    def write(self, path: Path) -> None:
        path.write_text(
            "".join(
                json.dumps(line, ensure_ascii=False) + "\n"
                for line in self.lines
            ),
            encoding="utf-8",
        )


def _governance_report(epoch_id: str) -> dict:
    """Minimal schema-valid ``governance_report`` skeleton (Task 05 §6.1)."""
    return {
        "record_type": "governance_report",
        "schema_version": 1,
        "record_id": f"govreport_{epoch_id}",
        "epoch_id": epoch_id,
        "component_id": "governance_orchestrator",
        "prompt_hash": None,
        "role": "governance",
        "created_at": FIXED_CREATED_AT,
        "status": "final",
        "source_refs": [],
        "governance_level": 1,
        "degraded": False,
        "degradation_reasons": [],
        "reliability": [],
        "observations": [],
        "evidence_bundles": [],
        "impeachment_motions": [],
        "defenses": [],
        "adjudications": [],
        "candidate_evaluations": [],
        "replay_pool_updates": {"added": [], "retired": []},
        "self_audit": {
            "checked_components": [],
            "kernel_violations_found": 0,
            "findings": [],
            "escalations": [],
        },
        "recommendations": [],
        "bond_accounting": {
            "posted": 0, "refunded": 0, "forfeited": 0,
            "remaining_budget": 100,
        },
        "budget_usage": {
            "llm_calls": 0,
            "replay_cases_used": 0,
            "anchor_cases_used": 0,
        },
    }


def make_rqgm_checkpoint(
    dest: Path,
    *,
    nodes: int = 10,
    epochs: int = 2,
    seed: int = 0,
    with_penalty: bool = True,
    with_policy_rewrite: bool = True,
    with_evolution: bool = True,
    with_paper: bool = False,
    corrupt: str | None = None,
) -> dict:
    """Write a deterministic synthetic ``ari_rqgm`` checkpoint into *dest*.

    Composes ON TOP of :func:`make_run_checkpoint` (which stays byte-for-byte
    what it writes for ``simple_bfts`` — the RQGM layer is purely additive
    plus the node-metrics sentinel rewrite of this checkpoint's own tree).

    Returns a manifest dict with the ids/hashes tests need without re-parsing
    the artifacts.
    """
    if epochs < 1:
        raise ValueError("epochs must be >= 1")
    if with_policy_rewrite and epochs < 2:
        raise ValueError(
            "with_policy_rewrite needs epochs >= 2 (the rewrite happens at "
            "the first epoch boundary)"
        )
    if corrupt is not None and corrupt not in RQGM_CORRUPT_MODES:
        raise ValueError(
            f"unknown corrupt mode: {corrupt!r} "
            f"(choose from {RQGM_CORRUPT_MODES})"
        )

    dest = Path(dest)
    base_manifest = make_run_checkpoint(dest, nodes=nodes, seed=seed)
    run_id = base_manifest["run_id"]

    # ── node roles: penalised pair + invalidated node (seed-fixed order) ──
    tree = json.loads((dest / "tree.json").read_text(encoding="utf-8"))
    node_dicts = tree["nodes"]
    scored = [n["id"] for n in node_dicts if n["status"] == "success"]
    need = (2 if with_penalty else 0) + (1 if with_policy_rewrite else 0)
    if len(scored) < max(need, 1):
        raise ValueError(
            f"fixture needs >= {max(need, 1)} success nodes for the requested "
            f"flags; (nodes={nodes}, seed={seed}) produced {len(scored)}"
        )
    penalty_nodes = scored[:2] if with_penalty else []
    invalidated_node = scored[-1] if with_policy_rewrite else None
    if invalidated_node is not None and invalidated_node in penalty_nodes:
        raise ValueError(
            f"fixture needs the invalidated node distinct from the penalised "
            f"pair; (nodes={nodes}, seed={seed}) has only {len(scored)} "
            f"success nodes"
        )

    # ── policy bodies + write-once body files (hash12(bytes) IS the hash) ──
    body_v1, body_v2 = _policy_bodies(seed)
    canon_v1 = canonical_json(body_v1)
    canon_v2 = canonical_json(body_v2)
    v1_hash = hash12(canon_v1)
    v2_hash = hash12(canon_v2)
    prompts_dir = dest / "rqgm_prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    (prompts_dir / f"{UTILITY_POLICY_PROMPT_V1}.json").write_text(
        canon_v1, encoding="utf-8"
    )
    if with_policy_rewrite:
        (prompts_dir / f"{UTILITY_POLICY_PROMPT_V2}.json").write_text(
            canon_v2, encoding="utf-8"
        )
    current_policy_body = body_v2 if with_policy_rewrite else body_v1
    current_hash = v2_hash if with_policy_rewrite else v1_hash
    sealed_current = seal_utility_policy(current_policy_body)

    # ── rqgm_transitions.jsonl + the replay-parity registry fold ──────────
    comp_map: dict = {}
    prompt_map: dict = {}
    chain = _ChainWriter(_BASE_TS)

    def add_registry_event(event_type: str, payload: dict) -> None:
        line = chain.add(event_type, payload)
        apply_registry_event(
            comp_map, prompt_map, event_type, payload,
            created_at=line["ts_iso"],
        )

    prompt_meta: dict[str, str] = {}  # role -> prompt_hash for records

    chain.add(
        "epoch_transaction_prepare", {"transition_id": "transition_founding"}
    )
    # Prompts first, then components (founding_registration_events order).
    for role, _cid, pid in _FOUNDING_ROLES:
        full, ph = _prompt_hashes(seed, role)
        prompt_meta[role] = ph
        add_registry_event("prompt_registered", {
            "prompt_id": pid,
            "role": role,
            "status": "active",
            "prompt_hash": ph,
            "prompt_sha256": full,
            "source": {"kind": "committed_template", "key": f"fixture/{role}"},
            "spec_ref": None,
            "epoch_id": "epoch_000",
            "source_refs": [],
        })
    add_registry_event("prompt_registered", {
        "prompt_id": UTILITY_POLICY_PROMPT_V1,
        "role": "utility_policy",
        "status": "active",
        "prompt_hash": v1_hash,
        "prompt_sha256": hashlib.sha256(
            canon_v1.encode("utf-8")
        ).hexdigest(),
        "source": {
            "kind": "policy",
            "path": f"rqgm_prompts/{UTILITY_POLICY_PROMPT_V1}.json",
        },
        "spec_ref": None,
        "epoch_id": "epoch_000",
        "source_refs": [],
    })
    for role, cid, pid in _FOUNDING_ROLES:
        add_registry_event("component_registered", {
            "component_id": cid,
            "role": role,
            "tier": "institutional",
            "status": "active",
            "prompt_id": pid,
            "epoch_id": "epoch_000",
            "source_refs": [],
            "capabilities": {},
        })
    add_registry_event("component_registered", {
        "component_id": UTILITY_POLICY_COMPONENT,
        "role": "utility_policy",
        "tier": "institutional",
        "status": "active",
        "prompt_id": UTILITY_POLICY_PROMPT_V1,
        "epoch_id": "epoch_000",
        "source_refs": [],
        "capabilities": {},
    })
    chain.add(
        "epoch_transaction_commit", {"transition_id": "transition_founding"}
    )

    def freeze(seq: int, policy_body: dict, *, node_count: int,
               prev_id: str | None, tid: str | None) -> EpochState:
        state = EpochState(
            epoch_id=format_epoch_id(seq),
            epoch_seq=seq,
            status="open",
            run_id=run_id,
            node_count_at_open=int(node_count),
            previous_epoch_id=prev_id,
            opened_by_transition_id=tid,
            active_components=ComponentRegistry(comp_map).active_set(),
            active_prompt_hashes=GovernedPromptRegistry(
                prompt_map
            ).active_prompt_hashes(),
            utility_policy=seal_utility_policy(policy_body),
            registry_version=GovernedPromptRegistry(
                prompt_map
            ).registry_version(),
            policy_settings={
                "fixture": "gui_refresh_v2",
                "governance_thresholds": "fixture-defaults",
            },
            execution_identity={
                "model_backend": "fixture",
                "model_id": "fixture-model",
                "decoding": {"temperature": 0.0},
                "skills": [],
                "disabled_tools": [],
                "provider_model_revision": "fixture-model-revision",
                "tool_bundle_revision": "fixture-tool-revision",
                "environment_digest": "fixture-environment",
                "data_snapshot_digest": "fixture-data",
                "complete": True,
            },
            epoch_fingerprint="",
            created_at=FIXED_CREATED_AT,
        )
        state = replace(
            state,
            policy_fingerprint=policy_fingerprint(state),
            execution_fingerprint=execution_fingerprint(state),
        )
        return replace(state, epoch_fingerprint=epoch_fingerprint(state))

    epoch = freeze(0, body_v1, node_count=1, prev_id=None, tid=None)
    chain.add("epoch_open", {"epoch_state": epoch_state_payload(epoch)})

    retirement_event_id = None
    first_tid = None
    for seq in range(1, epochs):
        tid = format_transition_id(seq - 1, seq)
        if seq == 1:
            first_tid = tid
        chain.add("epoch_transaction_prepare", {"transition_id": tid})
        if seq == 1 and with_policy_rewrite:
            add_registry_event("prompt_registered", {
                "prompt_id": UTILITY_POLICY_PROMPT_V2,
                "role": "utility_policy",
                "status": "shadow",
                "prompt_hash": v2_hash,
                "prompt_sha256": hashlib.sha256(
                    canon_v2.encode("utf-8")
                ).hexdigest(),
                "source": {
                    "kind": "policy",
                    "path": f"rqgm_prompts/{UTILITY_POLICY_PROMPT_V2}.json",
                },
                "spec_ref": None,
                "epoch_id": "epoch_000",
                "source_refs": [],
            })
            change_base = {
                "transition_id": tid,
                "produced_by": "registry_transition_engine",
                "inputs_sha256": "",
                "evidence_refs": [
                    f"supersession:{UTILITY_POLICY_PROMPT_V2}"
                ],
            }
            add_registry_event("prompt_status_change", dict(
                change_base,
                prompt_id=UTILITY_POLICY_PROMPT_V2,
                rule_id="T6",
                from_status="shadow",
                to_status="probationary_active",
            ))
            retirement_event_id = f"supersede_{tid}_000"
            add_registry_event("prompt_status_change", dict(
                change_base,
                prompt_id=UTILITY_POLICY_PROMPT_V1,
                rule_id="T20",
                from_status="active",
                to_status="retired",
            ))
        boundary_count = max(1, (nodes * seq) // epochs)
        chain.add("epoch_close", {
            "epoch_id": epoch.epoch_id,
            "transition_id": tid,
            "node_count_at_close": boundary_count,
        })
        policy_body = (
            body_v2 if (with_policy_rewrite and seq >= 1) else body_v1
        )
        epoch = freeze(
            seq, policy_body, node_count=boundary_count,
            prev_id=format_epoch_id(seq - 1), tid=tid,
        )
        chain.add("epoch_open", {
            "transition_id": tid,
            "epoch_state": epoch_state_payload(epoch),
        })
        chain.add("epoch_transaction_commit", {"transition_id": tid})

    chain.write(dest / RQGM_TRANSITIONS_FILENAME)

    # ── snapshots: epoch_state.json + rqgm_registry.json (replay-consistent) ─
    snap = epoch_state_payload(epoch)
    snap["created_at"] = epoch.created_at
    save_epoch_state_json(dest, snap)

    registry_rollup = {
        "schema_version": 1,
        "registry_version": GovernedPromptRegistry(
            prompt_map
        ).registry_version(),
        "as_of_event_hash": chain.last_hash,
        "components": [
            e.to_dict() for _, e in sorted(comp_map.items())
        ],
        "prompts": [
            e.to_dict() for _, e in sorted(prompt_map.items())
        ],
    }
    save_rqgm_registry_json(dest, registry_rollup)

    # ── rqgm_state.json + meta.json constitution hash ─────────────────────
    save_rqgm_state_json(dest, {
        "schema_version": 1,
        "mode": "ari_rqgm",
        "rqgm_enabled": True,
        "mode_source": "config",
        "created_at": FIXED_CREATED_AT,
        "switch_journal": [
            {"event": "run_start", "mode": "ari_rqgm", "epoch_id": None},
        ],
    })
    record_constitution_hash(dest)

    # ── rqgm_audit.jsonl (independent chain) ──────────────────────────────
    audit = _ChainWriter(_BASE_TS + _AUDIT_TS_OFFSET)
    erasure_event = None
    rebuild_event = None
    for seq in range(epochs):
        audit.add(
            "governance_report", _governance_report(format_epoch_id(seq))
        )
        if seq == 0 and with_policy_rewrite:
            frontier_before = sorted(scored)
            frontier_after = sorted(
                n for n in scored if n != invalidated_node
            )
            erasure_event = {
                "record_id": "erase_00000",
                "record_type": "SelectiveErasureEvent",
                "epoch_id": "epoch_000",
                "component_id": "frontier_repair_engine",
                "prompt_hash": None,
                "role": "kernel",
                "created_at": FIXED_CREATED_AT,
                "source_refs": [retirement_event_id, first_tid],
                "status": "applied",
                "retired_prompt_hashes": [v1_hash],
                "retired_component_ids": [],
                "direct_stale_record_ids": [],
                "transitive_stale_record_ids": [],
                "invalidated_node_ids": [invalidated_node],
                "recompute_node_ids": [],
                "abandoned_pending_node_ids": [],
                "trace_stats": {
                    "records_scanned": 0,
                    "closure_size": 0,
                    "max_ref_depth": 0,
                },
            }
            audit.add("selective_erasure", erasure_event)
            rebuild_event = {
                "record_id": "rebuild_00000",
                "record_type": "FrontierRebuildEvent",
                "epoch_id": "epoch_001",
                "component_id": "frontier_repair_engine",
                "prompt_hash": None,
                "role": "kernel",
                "created_at": FIXED_CREATED_AT,
                "source_refs": ["erase_00000"],
                "status": "applied",
                "frontier_before": frontier_before,
                "frontier_after": frontier_after,
                "removed_node_ids": [invalidated_node],
                "reinstated_node_ids": [],
                "recomputed_utility_node_ids": [],
                "kernel_validation": "passed",
            }
            audit.add("frontier_rebuild", rebuild_event)
    audit.write(dest / RQGM_AUDIT_FILENAME)

    # ── adversarial chain + UtilityRecord (with_penalty) ──────────────────
    utility_record = None
    if with_penalty:
        chain_epoch = epoch.epoch_id
        node_a = penalty_nodes[0]
        by_id = {n["id"]: n for n in node_dicts}
        base_a = float(by_id[node_a]["metrics"]["_scientific_score"])
        penalty_a = _PENALTY_POLICY["severity_weights"]["high"] * 1.0
        final_a = max(0.0, base_a - penalty_a)
        evidence = EvidenceRef(
            path=f"experiments/{run_id}/{node_a}/results.csv",
            pointer="row:1",
            artifact_hash="",
        )
        target = TargetArtifact(
            type="node_report",
            node_id=node_a,
            ref=f"{node_a}/node_report.json",
            artifact_hash=hash12(f"fixture artifact {node_a} seed {seed}"),
        )
        atk = RawAttackRecord(
            record_id="atk_000000",
            adversary_type="overclaim",
            target_artifact=target,
            attack_claim=(
                f"fixture overclaim attack: {node_a} claims more than its "
                "recorded evidence supports"
            ),
            attack_evidence_refs=(evidence,),
            severity_claimed="high",
            confidence=0.8,
            epoch_id=chain_epoch,
            component_id="adversary_overclaim_v1",
            prompt_hash=prompt_meta["adversary"],
            created_at=FIXED_CREATED_AT,
            source_refs=(node_a,),
            status="raw",
        )
        dfn = DefenderResponse(
            record_id="def_000000",
            raw_attack_id="atk_000000",
            stance="rebut",
            rebuttal_text=(
                "fixture rebuttal: the recorded metrics table bounds the "
                "claim"
            ),
            counter_evidence_refs=(evidence,),
            proposed_fix=None,
            confidence=0.6,
            epoch_id=chain_epoch,
            component_id="defender_v1",
            prompt_hash=prompt_meta["defender"],
            created_at=FIXED_CREATED_AT,
            source_refs=("atk_000000",),
            status="final",
        )
        jdg = JudgmentRecord(
            record_id="jdg_000000",
            raw_attack_id="atk_000000",
            defense_id="def_000000",
            verdict="valid",
            severity="high",
            rationale=(
                "fixture adjudication: the evidence gap the attack cites is "
                "real; the rebuttal does not close it"
            ),
            evidence_refs=(evidence,),
            defense_status="present",
            epoch_id=chain_epoch,
            component_id="artifact_judge_v1",
            prompt_hash=prompt_meta["judge"],
            created_at=FIXED_CREATED_AT,
            source_refs=("atk_000000", "def_000000"),
            status="final",
        )
        vat = ValidatedAttackRecord(
            record_id="vat_000000",
            case_type="overclaim",
            raw_attack_id="atk_000000",
            judgment_id="jdg_000000",
            defense_id="def_000000",
            source_node_id=node_a,
            attack_summary=atk.attack_claim,
            validated=True,
            verdict="valid",
            severity="high",
            # ROLE names observed; NO target_component_id: the exploration
            # generator role is unregistered as an attack target, so the
            # impeachment chain is structurally inert here (plan 08
            # §Accountability) — the key is legitimately absent.
            affected_components=("generator",),
            target_component_id="",
            expected_behavior={
                "generator": "claims bounded by checkpoint evidence",
            },
            target_artifact_hash=target.artifact_hash,
            epoch_id=chain_epoch,
            component_id="artifact_judge_v1",
            prompt_hash=prompt_meta["judge"],
            created_at=FIXED_CREATED_AT,
            source_refs=("jdg_000000",),
            status="active",
        )
        frozen_policy = {
            "penalty_cap": _PENALTY_POLICY["penalty_cap"],
            "severity_weights": dict(_PENALTY_POLICY["severity_weights"]),
            "verdict_factors": dict(_PENALTY_POLICY["verdict_factors"]),
            # Task-14 shape: the EPOCH policy by value, self-describing.
            "utility_policy": dict(sealed_current),
        }
        utl = UtilityRecord(
            record_id="utl_000000",
            node_id=node_a,
            base_score=base_a,
            penalty=penalty_a,
            final_score=final_a,
            input_refs={
                "result_ref": {
                    "path": f"experiments/{run_id}/{node_a}/results.csv",
                    "artifact_hash": "",
                },
                "review_ids": [],
                "validated_attack_ids": ["vat_000000"],
            },
            utility_policy_hash=current_hash,
            frozen_policy=frozen_policy,
            supersedes=None,
            recomputed_in_epoch=None,
            epoch_id=chain_epoch,
            component_id=UTILITY_POLICY_COMPONENT,
            prompt_hash=current_hash,
            created_at=FIXED_CREATED_AT,
            source_refs=(node_a, "vat_000000"),
            status="active",
        )
        utility_record = utl.to_dict()
        (dest / "rqgm_adversarial_cases.jsonl").write_text(
            "".join(
                json.dumps(r.to_dict(), ensure_ascii=False) + "\n"
                for r in (atk, dfn, jdg, vat, utl)
            ),
            encoding="utf-8",
        )

    # ── prompt_evolution.jsonl + rqgm_meta_outputs.jsonl (with_evolution) ──
    # Wave 4b (plan 08 §Evolution): one raw prompt candidate that is NEVER
    # registered (adopted=false forever), one UtilityPolicyCandidate whose
    # proposed policy IS the v2 body (adopted iff with_policy_rewrite — the
    # adoption join goes through the committed registry replay, never the
    # candidate record itself), and one validation-stage record for it.
    # Plain JSONL, byte layout of record_prompt_evolution_event /
    # record_meta_output (json.dumps ensure_ascii=False, one line each) — the
    # logs are NOT hash-chained.
    prompt_candidate_id = None
    utility_candidate_id = None
    meta_output_id = None
    if with_evolution:
        cand_sha, cand_hash = _prompt_hashes(seed, "adversary_candidate")
        prompt_candidate_id = "cand_adversary_00000"
        utility_candidate_id = "upc_cand_00000"
        pcand = {
            "record_type": "prompt_candidate",
            "record_id": "pcand_00000",
            "epoch_id": "epoch_000",
            "component_id": "prompt_mutator_v1",
            "prompt_hash": cand_hash,
            "role": "adversary",
            "created_at": FIXED_CREATED_AT,
            "source_refs": [],
            "status": "candidate",
            "candidate_id": prompt_candidate_id,
            "generated_by": {
                "component_id": "prompt_mutator_v1",
                "prompt_hash": "",
            },
            "generation_mode": "mutation",
            "mutation_kind": "freeform_mutation",
            "source_prompt_id": "adversary_overclaim_prompt_v1",
            "failure_summary_refs": [],
            "rationale": (
                "fixture raw candidate: proposed, never validated, never "
                "registered"
            ),
            "prompt_spec": {
                "role": "adversary",
                "template_ref": f"fixture/adversary_candidate_seed{seed}",
                "prompt_sha256": cand_sha,
            },
        }
        upc = UtilityPolicyCandidate(
            record_id="upc_000000",
            candidate_id=utility_candidate_id,
            policy=dict(body_v2),
            policy_hash=v2_hash,
            epoch_id="epoch_000",
            component_id="policy_mutator_v1",
            prompt_hash="",  # proposer template unresolvable (allowed)
            created_at=FIXED_CREATED_AT,
            status="candidate",
            parent_prompt_id=UTILITY_POLICY_PROMPT_V1,
            mutation_kind="exploration_tuning",
            rationale=(
                "fixture: seed-derived exploration_tuning successor policy"
            ),
            source_refs=("epoch_000",),
        ).to_dict()
        pval = {
            "record_type": "prompt_candidate_validation",
            "record_id": "pval_00000",
            "epoch_id": "epoch_000",
            "component_id": "constitutional_kernel",
            "prompt_hash": v2_hash,
            "role": "utility_policy",
            "created_at": FIXED_CREATED_AT,
            "source_refs": ["upc_000000"],
            "status": "final",
            "candidate_id": utility_candidate_id,
            "stage": "constitutional_validation",
            "passed": True,
            "evaluated_by": "constitutional_kernel",
            "case_results": [],
            "metrics": {},
            "details": "fixture: CK-UTL legality gate passed",
        }
        (dest / PROMPT_EVOLUTION_FILENAME).write_text(
            "".join(
                json.dumps(r, ensure_ascii=False) + "\n"
                for r in (pcand, upc, pval)
            ),
            encoding="utf-8",
        )
        meta_output_id = "meta_out_" + hash12(canonical_json([
            "meta_prompt_engineer_v1", "epoch_000",
            "prompt_candidate_suggestion",
            hash12(f"fixture meta input seed {seed}"),
            hash12(f"fixture meta output seed {seed}"),
        ]))
        meta_out = {
            "record_type": "meta_agent_output",
            "record_id": meta_output_id,
            "epoch_id": "epoch_000",
            "component_id": "meta_prompt_engineer_v1",
            "prompt_hash": None,
            "role": "meta_prompt_engineer",
            "created_at": FIXED_CREATED_AT,
            "source_refs": [],
            "status": "recorded",
            "output_kind": "prompt_candidate_suggestion",
            "target_role": "adversary",
            "candidate_ref": prompt_candidate_id,
            "expected_improvement": (
                "fixture: tighter overclaim detection"
            ),
            "shadow": False,
            "sandboxed": True,
            "input_bundle_hash": hash12(f"fixture meta input seed {seed}"),
            "output_payload_hash": hash12(f"fixture meta output seed {seed}"),
        }
        (dest / META_OUTPUTS_FILENAME).write_text(
            json.dumps(meta_out, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    # ── paper-archive layer (with_paper) ──────────────────────────────────
    # Wave 4b (plan 08 §Paper Archive): paper_archive_state.json (mode
    # provenance + frozen paper_utility_policy carrying anchor_enabled),
    # paper_draft_archive.jsonl (append-only draft population, byte layout of
    # write_paper_draft_record: sort_keys=True, ensure_ascii=False; exactly
    # ONE is_best_belief carrier), archive/{epoch}/{node}/*.tex bytes whose
    # sha256 IS each record's tex_sha256, the anchor corpus, the
    # self-preference statistic snapshot, and the materialized winner copy at
    # {ckpt}/full_paper.tex.
    paper_epoch_ids: list[str] = []
    paper_winner_node = None
    paper_draft_ids: list[str] = []
    anchor_case_ids: list[str] = []
    paper_policy_hash = None
    self_pref_margin = None
    if with_paper:
        anchor_cases = [
            PaperAnchorCase(
                case_id="anchor_000",
                ground_truth_label="accept",
                label_source="human_curated",
                manuscript_sha256=hashlib.sha256(
                    f"fixture anchor manuscript 0 seed {seed}".encode()
                ).hexdigest(),
                manuscript_ref="fixture/anchor_000.tex",
                venue="fixture-venue",
                authorship="human",
                split="held_out",
            ).to_dict(),
            PaperAnchorCase(
                case_id="anchor_001",
                ground_truth_label="reject",
                label_source="human_curated",
                manuscript_sha256=hashlib.sha256(
                    f"fixture anchor manuscript 1 seed {seed}".encode()
                ).hexdigest(),
                manuscript_ref="fixture/anchor_001.tex",
                venue="fixture-venue",
                authorship="ai",
                split="held_out",
            ).to_dict(),
        ]
        anchor_case_ids = [c["case_id"] for c in anchor_cases]
        (dest / PAPER_ANCHOR_CORPUS_FILENAME).write_text(
            "".join(
                json.dumps(c, ensure_ascii=False) + "\n"
                for c in anchor_cases
            ),
            encoding="utf-8",
        )

        paper_policy = {
            "reviewer_score_source": "paper_reviewer",
            "writer_anchor": dict(WRITER_ANCHOR_DESCRIPTOR),
            "anchor_enabled": True,
            "anchor_corpus_digest": corpus_digest(anchor_cases),
            "anchor_sample_size": 8,
            "anchor_held_out_ids": sorted(anchor_case_ids),
            "anchor_label_source_mix": {
                "human_curated": 2, "gate_bootstrap": 0,
            },
            "anchor_held_out_label_source_mix": {
                "human_curated": 2, "gate_bootstrap": 0,
            },
            "anchor_max_bootstrap_label_fraction": 0.5,
            "agreement_metric": AGREEMENT_METRIC_ID,
            "ties_favor_incumbent": True,
        }
        paper_policy["paper_utility_policy_hash"] = hash12(
            canonical_json(paper_policy)
        )
        paper_policy_hash = paper_policy["paper_utility_policy_hash"]
        save_paper_archive_state_json(dest, {
            "schema_version": 1,
            "paper_mode": "rqgm_archive",
            "rqgm_paper_enabled": True,
            "mode_source": "config",
            "created_at": FIXED_CREATED_AT,
            "exploration_mode": "ari_rqgm",
            "seed_node_id": None,
            "switch_journal": [
                {"event": "paper_phase_start",
                 "paper_mode": "rqgm_archive", "epoch_id": None},
            ],
            "paper_utility_policy": paper_policy,
            "paper_epoch_fingerprint": paper_policy_hash,
        })

        paper_epoch_ids = ["epoch_000", "epoch_001"]
        writer_hash = _prompt_hashes(seed, "paper_writer")[1]
        reviewer_hash = _prompt_hashes(seed, "paper_reviewer")[1]
        drafts = (
            # (epoch_id, node_id, kind, parent, refine_pass)
            ("epoch_000", "draft_0", "seed", None, 0),
            ("epoch_000", "draft_1", "seed", None, 0),
            ("epoch_001", "draft_0", "seed", None, 0),
            ("epoch_001", "draft_0.r1", "refine", "draft_0", 1),
        )
        paper_winner_node = drafts[-1][1]
        records = []
        for i, (eid, nid, kind, parent, rp) in enumerate(drafts):
            if kind == "seed":
                rel_tex = f"archive/{eid}/{nid}/full_paper.tex"
            else:
                rel_tex = f"archive/{eid}/{parent}/full_paper.r{rp}.tex"
            latex = (
                f"% fixture paper draft {nid} epoch {eid} seed {seed}\n"
                "\\documentclass{article}\n\\begin{document}\n"
                f"Fixture draft body {i}.\n\\end{{document}}\n"
            )
            tex_abs = dest / rel_tex
            tex_abs.parent.mkdir(parents=True, exist_ok=True)
            tex_abs.write_text(latex, encoding="utf-8")
            is_winner = nid == paper_winner_node and eid == "epoch_001"
            records.append({
                "schema_version": 1,
                "draft_id": nid,
                "node_id": nid,
                "kind": kind,
                "parent_draft_id": parent,
                "refine_pass": rp,
                "tex_path": rel_tex,
                "tex_sha256": hashlib.sha256(
                    latex.encode("utf-8")
                ).hexdigest(),
                "writer_prompt_hash": writer_hash,
                "reviewer_prompt_hash": reviewer_hash,
                "review_score": round(
                    0.6 + 0.05 * i
                    + (_hval(seed, "paper_score", i) % 40) / 10000.0,
                    6,
                ),
                "suggested_revisions_ref": "",
                "anchors_preserved": 2,
                "decode_seed": 1000 + seed + i,
                "epoch_id": eid,
                "is_best_belief": is_winner,
                "compiled": is_winner,
                "created_at": FIXED_CREATED_AT,
            })
            paper_draft_ids.append(nid)
        (dest / PAPER_DRAFT_ARCHIVE_FILENAME).write_text(
            "".join(
                json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n"
                for r in records
            ),
            encoding="utf-8",
        )
        # materialize_winner's single-writer copy of the best-belief bytes.
        winner_rec = records[-1]
        (dest / "full_paper.tex").write_text(
            (dest / winner_rec["tex_path"]).read_text(encoding="utf-8"),
            encoding="utf-8",
        )

        self_pref_margin = round(
            (_hval(seed, "self_pref_margin") % 300) / 1000.0, 6
        )
        snap = dest / RQGM_SNAPSHOT_DIRNAME
        snap.mkdir(parents=True, exist_ok=True)
        (snap / PAPER_SELF_PREFERENCE_STAT_FILENAME).write_text(
            json.dumps({
                "record_type": "paper_self_preference_stat",
                "schema_version": 1,
                "epoch_id": "epoch_001",
                "sample_ids": sorted(anchor_case_ids),
                "per_case_scores": {"anchor_000": 1.0, "anchor_001": 1.0},
                "ai_mean": 1.0,
                "human_mean": round(1.0 - self_pref_margin, 6),
                "margin": self_pref_margin,
            }, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )

    # ── node metrics sentinels (tree.json / nodes_tree.json / results.json) ─
    sentinel_updates: dict[str, dict] = {}
    for n in node_dicts:
        if n["status"] != "success":
            continue
        nid = n["id"]
        metrics = dict(n["metrics"])
        metrics["_utility_policy_hash"] = current_hash
        if with_penalty and nid in penalty_nodes:
            base_score = float(metrics["_scientific_score"])
            pen = (
                _PENALTY_POLICY["severity_weights"]["high"]
                if nid == penalty_nodes[0]
                else _PENALTY_POLICY["severity_weights"]["medium"]
            )
            metrics["_pre_penalty_score"] = base_score
            metrics["_validated_attack_penalty"] = pen
            metrics["_scientific_score"] = max(0.0, base_score - pen)
        if nid == invalidated_node:
            # Scored under the RETIRED policy; invalidated, never re-scaled.
            metrics["_utility_policy_hash"] = v1_hash
            metrics["_stale"] = True
            metrics["_valid_for_frontier"] = False
            metrics["_stale_reason"] = "utility_invalidated"
            metrics["_erasure_event_id"] = "erase_00000"
        sentinel_updates[nid] = metrics

    for n in node_dicts:
        if n["id"] in sentinel_updates:
            n["metrics"] = sentinel_updates[n["id"]]
    save_tree_json(dest, tree)

    nodes_tree = json.loads(
        (dest / "nodes_tree.json").read_text(encoding="utf-8")
    )
    for n in nodes_tree["nodes"]:
        if n["id"] in sentinel_updates:
            n["metrics"] = sentinel_updates[n["id"]]
    save_nodes_tree_json(dest, nodes_tree)

    results = json.loads((dest / "results.json").read_text(encoding="utf-8"))
    for nid, entry in results["nodes"].items():
        if nid in sentinel_updates:
            entry["metrics"] = sentinel_updates[nid]
    save_results_json(dest, results)

    # ── corruption pass (after a fully valid write) ───────────────────────
    trans_path = dest / RQGM_TRANSITIONS_FILENAME
    if corrupt == "broken_chain":
        lines = trans_path.read_text(encoding="utf-8").splitlines()
        broken = json.loads(lines[1])
        broken["prev_event_hash"] = "0" * 12  # pattern-valid, chain-wrong
        lines[1] = json.dumps(broken, ensure_ascii=False)
        trans_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    elif corrupt == "truncated_transitions":
        raw = trans_path.read_text(encoding="utf-8")
        lines = raw.splitlines()
        torn = lines[-1][: max(5, len(lines[-1]) // 2)]
        trans_path.write_text(
            "\n".join(lines[:-1]) + "\n" + torn, encoding="utf-8"
        )
    elif corrupt == "registry_mismatch":
        rollup = json.loads(
            (dest / "rqgm_registry.json").read_text(encoding="utf-8")
        )
        rollup["as_of_event_hash"] = chain.lines[0]["event_hash"]  # stale
        save_rqgm_registry_json(dest, rollup)

    files = sorted(p.name for p in dest.iterdir() if p.is_file()) + sorted(
        f"rqgm_prompts/{p.name}" for p in prompts_dir.iterdir() if p.is_file()
    )
    return {
        "run_id": run_id,
        "nodes": nodes,
        "epochs": epochs,
        "seed": seed,
        "with_penalty": with_penalty,
        "with_policy_rewrite": with_policy_rewrite,
        "with_evolution": with_evolution,
        "with_paper": with_paper,
        "corrupt": corrupt,
        "files": files,
        "prompt_candidate_id": prompt_candidate_id,
        "utility_candidate_id": utility_candidate_id,
        "meta_output_id": meta_output_id,
        "paper_epoch_ids": paper_epoch_ids,
        "paper_draft_ids": paper_draft_ids,
        "paper_winner_node_id": paper_winner_node,
        "paper_utility_policy_hash": paper_policy_hash,
        "anchor_case_ids": anchor_case_ids,
        "self_preference_margin": self_pref_margin,
        "scored_node_ids": scored,
        "penalty_node_ids": penalty_nodes,
        "invalidated_node_id": invalidated_node,
        "policy_hash_v1": v1_hash,
        "policy_hash_v2": v2_hash if with_policy_rewrite else None,
        "current_policy_hash": current_hash,
        "final_epoch_id": epoch.epoch_id,
        "transitions_last_event_hash": chain.last_hash,
        "audit_last_event_hash": audit.last_hash,
        "erasure_event": erasure_event,
        "rebuild_event": rebuild_event,
        "utility_record": utility_record,
    }
