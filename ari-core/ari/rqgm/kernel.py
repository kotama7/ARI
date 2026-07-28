"""ConstitutionalKernel — Layer-0 deterministic procedure checks (RQGM Task 04).

The kernel is **NOT an LLM judge**: it makes zero LLM calls, zero network
calls, and zero wall-clock-dependent decisions (design principle P2, plan
``docs/plans/ari_rqgm/04`` §1/§5.1). It never answers "is this research
decision correct?" — only "does this event follow permitted procedure?".
Every verdict is a pure function of the serialized inputs; the kernel writes
nothing (callers persist :class:`~ari.rqgm.kernel_types.KernelReport` verdicts
to Task 02's ``rqgm_audit.jsonl``).

The API is closed at twelve entry points (plan 04 §5.4): eight core
``validate_*`` checks plus four downstream-specified ones whose detailed
input contracts are owned by Tasks 08 (clean room), 11 (authority
non-expansion), and 12 (context scope) — implemented here minimally under
this task's determinism/verdict/severity rules.

Rules live in code (:mod:`ari.rqgm.kernel_rules`), the transition table in
:mod:`ari.rqgm.transition_rules` (Task 09's Layer-0 module — imported, never
duplicated). ``constitution_hash`` pins every table (§5.7): the kernel is
non-evolving by construction.

Enforcement principle — "block the institution, not the research" (§5.1):
a blocking report vetoes RQGM *state changes* only; adapters in mid-epoch
contexts (:func:`per_node_warn_check`) are fail-open like every existing
``_run_loop`` hook. The MCP pre-flight gate
(:class:`CapabilityGatedMCPClient`) is the one deliberate mid-epoch DENY.
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path

from ari.rqgm import clean_room_rules, kernel_rules, meta_rules, transition_rules
from ari.rqgm.events import ACTIVE_STATUSES, UTILITY_POLICY_ROLE, payload_hash
from ari.rqgm.kernel_types import (
    KernelReport,
    Violation,
    kernel_report_audit_payload,
    make_report,
)

log = logging.getLogger(__name__)

#: Numeric tolerances (plan 04 §5.7/§6): the ONLY configurable part of the
#: kernel; defaults mirror ``ari/configs/defaults.yaml`` ``rqgm.kernel.*``.
DEFAULT_TOLERANCES: dict = {
    "float_tolerance": 1e-9,
    # CK-CLN-002 shingle screen (Task 08 §5.5). Bare-constructed kernels keep
    # the Task 04 v1 ratio semantics (k=5, threshold); the ari_rqgm runtime
    # injects rqgm.clean_room.contamination_screen (k=8, fail-on-any-hit).
    "contamination_shingle_words": 5,
    "contamination_threshold": 0.2,
    "contamination_fail_on_any_hit": False,
}

#: Retired-side prompt statuses whose hashes form the forbidden frontier set.
_RETIRED_STATUSES: tuple[str, ...] = ("retired", "banned")

_EVENT_ID_RE = re.compile(r"^evt_(\d+)$")

#: Registry-status-change event types (the mid-epoch active-set mutation
#: surface checked by ``validate_epoch_invariance``).
_STATUS_CHANGE_EVENTS: frozenset = frozenset(
    {"component_status_change", "prompt_status_change"}
)


# ── input normalisation helpers (duck-typed, read-only) ─────────────────────


def _as_dict(obj) -> dict:
    """Normalise a record/transition input: dict, ``to_dict()`` dataclass,
    or attribute object. Raises ``TypeError`` on hopeless inputs
    (programmer error — the kernel raises only for wrong types)."""
    if isinstance(obj, dict):
        return obj
    to_dict = getattr(obj, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    if hasattr(obj, "__dict__"):
        return dict(vars(obj))
    raise TypeError(f"kernel input must be dict-like, got {type(obj)!r}")


def _active_prompt_hashes(registry) -> dict:
    """``role -> prompt_hash`` from an EpochState, a GovernedPromptRegistry,
    a Task 02 runtime-state rollup, or a plain mapping."""
    if registry is None:
        return {}
    attr = getattr(registry, "active_prompt_hashes", None)
    if attr is not None:
        return dict(attr() if callable(attr) else attr)
    prompts = getattr(registry, "prompts", None)
    if prompts is not None and hasattr(prompts, "active_prompt_hashes"):
        return dict(prompts.active_prompt_hashes())
    if isinstance(registry, dict):
        return dict(registry)
    return {}


def _prompt_entries(registry) -> dict:
    """``prompt_id -> GovernedPromptEntry``-like map (empty when absent)."""
    obj = getattr(registry, "prompts", registry)
    entries = getattr(obj, "entries", None)
    if callable(entries):
        return entries()
    return {}


def _component_getter(registry):
    """Return a ``component_id -> entry|None`` lookup over *registry*
    (ComponentRegistry, runtime-state rollup, or plain mapping)."""
    if registry is None:
        return lambda cid: None
    comps = getattr(registry, "components", registry)
    if hasattr(comps, "get"):
        return comps.get
    return lambda cid: None


def _retired_prompt_hashes(prompt_registry) -> frozenset:
    """The forbidden hash set: retired/banned governed prompts, or a plain
    iterable of hashes."""
    if prompt_registry is None:
        return frozenset()
    entries = _prompt_entries(prompt_registry)
    if entries:
        return frozenset(
            e.prompt_hash
            for e in entries.values()
            if getattr(e, "status", "") in _RETIRED_STATUSES
            and getattr(e, "prompt_hash", "")
        )
    if isinstance(prompt_registry, (set, frozenset, list, tuple)):
        return frozenset(str(h) for h in prompt_registry)
    return frozenset()


def _record_map(records) -> dict:
    """``record_id -> record dict`` over a mapping or an iterable."""
    out: dict = {}
    if records is None:
        return out
    if isinstance(records, dict):
        items = records.values()
    else:
        items = records
    for item in items:
        rec = _as_dict(item)
        rid = str(rec.get("record_id", ""))
        if rid:
            out[rid] = rec
    return out


def _source_ref_ids(rec: dict) -> list:
    """String refs out of a ``source_refs`` list or dict (values), sorted for
    deterministic violation order."""
    refs = rec.get("source_refs")
    if isinstance(refs, dict):
        vals = refs.values()
    elif isinstance(refs, (list, tuple)):
        vals = refs
    else:
        vals = ()
    return sorted(str(v) for v in vals if isinstance(v, str) and v)


def _erasure_edge_material(consumer: dict, referenced: "dict | None") -> bool:
    """Task 10's fixed materiality table over one source_refs edge.

    The table is owned by ``ari.rqgm.frontier_repair`` (plan 10 §5.3); the
    kernel applies the same pure (type, type) rule so CK-ERA-004 and the
    tracer agree on the closure. Unresolvable referenced records and any
    import failure default to load-bearing (conservative)."""
    if referenced is None:
        return True
    try:
        from ari.rqgm.frontier_repair import depends_materially
    except Exception:  # pragma: no cover - defensive
        return True
    return depends_materially(
        str(consumer.get("record_type", "")),
        str(referenced.get("record_type", "")),
    )


def _cites_tainted(rec: dict, tainted: set, recmap: dict) -> bool:
    """True iff *rec* materially cites a tainted record (CK-ERA-004 edge)."""
    return any(
        ref in tainted and _erasure_edge_material(rec, recmap.get(ref))
        for ref in _source_ref_ids(rec)
    )


def _record_node_anchor(rec: dict) -> str:
    """Node anchor of a record via the Task 10 reader (CK-ERA-006), so the
    kernel and the tracer resolve the identical anchor field set."""
    try:
        from ari.rqgm.frontier_repair import record_node_id
    except Exception:  # pragma: no cover - defensive
        return str(rec.get("node_id", "") or "")
    return record_node_id(rec)


def _actor_role_tier(actor) -> tuple:
    """``(role, tier)`` from a tuple, dict, or entry-like object."""
    if isinstance(actor, tuple) and len(actor) == 2:
        return str(actor[0]), str(actor[1])
    if isinstance(actor, dict):
        return str(actor.get("role", "")), str(actor.get("tier", ""))
    return (
        str(getattr(actor, "role", "")),
        str(getattr(actor, "tier", "")),
    )


def _capability_pairs(declared) -> frozenset:
    """Normalise a declared capability list — ``"action:resource"`` strings
    or ``(action, resource)`` pairs — into a frozenset of pairs."""
    out = set()
    for item in declared or ():
        if isinstance(item, str):
            action, _, resource = item.partition(":")
            out.add((action, resource))
        elif isinstance(item, (list, tuple)) and len(item) == 2:
            out.add((str(item[0]), str(item[1])))
    return frozenset(out)


def _sha256_file(path: Path) -> str:
    """Full sha256 of a file (same scheme as ``node_report/builder.py``)."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _shingles(text: str, k: int) -> frozenset:
    """Deterministic lowercase word *k*-shingles (CK-CLN-002 screen)."""
    words = re.findall(r"[a-z0-9]+", str(text).lower())
    if len(words) < k:
        return frozenset({" ".join(words)} if words else set())
    return frozenset(
        " ".join(words[i : i + k]) for i in range(len(words) - k + 1)
    )


def _transition_changes(t: dict) -> list:
    """Flatten adoptions/sanctions/retirements/bans into ``(group, entry)``
    pairs, preserving the transition's own order."""
    out = []
    for group in ("adoptions", "sanctions", "retirements", "bans"):
        for entry in t.get(group) or ():
            out.append((group, _as_dict(entry)))
    return out


class ConstitutionalKernel:
    """The non-evolving Layer-0 checker (plan 04 §5.3–§5.5).

    Pure-function core: reads the inputs passed to it (or resolved through
    the injected read-only loaders) and returns
    :class:`~ari.rqgm.kernel_types.KernelReport` verdicts, sorted and
    byte-stable for identical inputs (P2). It raises only on programmer
    error (wrong types), never on rule violations, and writes nothing.

    Severity is constitutional (``kernel_rules.SEVERITY``), never
    caller-chosen; whether a blocking report actually vetoes a state change
    is the calling context per the §5.5 blocking matrix and the
    ``rqgm.kernel.enforcement`` mode (see :func:`should_block`).
    """

    def __init__(
        self,
        *,
        records_reader=None,
        prompt_registry_reader=None,
        component_registry_reader=None,
        audit_log_reader=None,
        rules=kernel_rules,
        tolerances: dict | None = None,
    ) -> None:
        self._records_reader = records_reader
        self._prompt_registry_reader = prompt_registry_reader
        self._component_registry_reader = component_registry_reader
        self._audit_log_reader = audit_log_reader
        self.rules = rules
        self.tolerances = dict(DEFAULT_TOLERANCES)
        if tolerances:
            self.tolerances.update(tolerances)

    @property
    def constitution_hash(self) -> str:
        """The §5.7 pin over every rule table (incl. the imported Task 09
        transition tables)."""
        return self.rules.CONSTITUTION_HASH

    # ── internal ───────────────────────────────────────────────────────

    def _v(
        self, code: str, check: str, subject, rule_id: str, detail: str
    ) -> Violation:
        """Severity always resolves through the constitution's SEVERITY map
        (KeyError on an unknown code == programmer error)."""
        return Violation(
            code=code,
            check=check,
            severity=self.rules.SEVERITY[code],
            subject_ref=str(subject),
            rule_id=rule_id,
            detail=detail,
        )

    # ── 1. schema (CK-SCH-*) ───────────────────────────────────────────

    def validate_record_schema(self, record) -> KernelReport:
        """Envelope + shape check over one RQGM record (plan 04 §5.4 item 1).

        Governance record types (``kernel_rules.GOVERNANCE_RECORD_TYPES``)
        violate as CK-SCH-G01 (block); every other record type as CK-SCH-N01
        (warn). ProposalRecord summaries additionally run the Task 03 budget
        check (CK-SCH-N02).
        """
        rec = _as_dict(record)
        rtype = str(rec.get("record_type", ""))
        rid = str(rec.get("record_id", "")) or "<missing record_id>"
        governance = rtype in self.rules.GOVERNANCE_RECORD_TYPES
        code = "CK-SCH-G01" if governance else "CK-SCH-N01"
        violations = []
        missing = [f for f in self.rules.ENVELOPE_FIELDS if f not in rec]
        if missing:
            violations.append(
                self._v(
                    code, "validate_record_schema", rid, "ENVELOPE_FIELDS",
                    "missing envelope fields: " + ", ".join(sorted(missing)),
                )
            )
        for required in ("record_id", "status", "role"):
            if required in rec and not str(rec.get(required) or ""):
                violations.append(
                    self._v(
                        code, "validate_record_schema", rid,
                        "ENVELOPE_FIELDS",
                        f"envelope field {required!r} is empty",
                    )
                )
        if rtype == "proposal_record":
            try:
                from ari.rqgm.proposals.records import (
                    summary_from_dict,
                    summary_violations,
                )

                summary = summary_from_dict(
                    rec.get("summary")
                    if isinstance(rec.get("summary"), dict)
                    else {}
                )
                for finding in summary_violations(summary):
                    violations.append(
                        self._v(
                            "CK-SCH-N02", "validate_record_schema", rid,
                            "proposal_summary_budgets", finding,
                        )
                    )
            except ImportError:  # pragma: no cover - proposals always ships
                pass
        return make_report("node_record", violations)

    # ── 2. hashes (CK-HSH-*) ───────────────────────────────────────────

    def validate_hashes(self, record, registry, artifacts=None) -> KernelReport:
        """Hash provenance over one record (plan 04 §5.4 item 2).

        (a) ``prompt_hash`` vs the active registered hash for the record's
        role (scheme: the existing ``hash12 = sha256(text)[:12]``) —
        CK-HSH-001; an *active* registry entry whose own registered hash pair
        disagrees (``prompt_sha256[:12] != prompt_hash``) is the blocking
        CK-HSH-010. (b) recorded ``artifact_hashes`` vs *artifacts* (a
        mapping ``ref -> sha256-hex | Path``; Paths are recomputed with full
        sha256) — CK-HSH-002/003. (c) ``source_refs`` resolvable through the
        injected ``records_reader`` — CK-HSH-003.
        """
        rec = _as_dict(record)
        rid = str(rec.get("record_id", "")) or "<missing record_id>"
        role = str(rec.get("role", ""))
        violations = []
        active = _active_prompt_hashes(registry)
        prompt_hash = rec.get("prompt_hash")
        expected = active.get(role)
        if prompt_hash and expected and str(prompt_hash) != str(expected):
            violations.append(
                self._v(
                    "CK-HSH-001", "validate_hashes", rid, "hash12",
                    f"prompt_hash {prompt_hash} != registered active hash "
                    f"{expected} for role {role!r}",
                )
            )
        # Active-entry self-consistency (the boundary BLOCK case): the
        # registered pair prompt_sha256/prompt_hash must agree by scheme.
        for pid, entry in sorted(_prompt_entries(registry).items()):
            status = getattr(entry, "status", "")
            sha = str(getattr(entry, "prompt_sha256", "") or "")
            h12 = str(getattr(entry, "prompt_hash", "") or "")
            if status in ACTIVE_STATUSES and sha and h12 and sha[:12] != h12:
                violations.append(
                    self._v(
                        "CK-HSH-010", "validate_hashes", pid, "hash12",
                        "active entry registered prompt_hash disagrees with "
                        "its registered sha256",
                    )
                )
        recorded = rec.get("artifact_hashes")
        if isinstance(recorded, dict):
            lookup = artifacts if isinstance(artifacts, dict) else {}
            for ref in sorted(recorded):
                actual = lookup.get(ref)
                if actual is None:
                    violations.append(
                        self._v(
                            "CK-HSH-003", "validate_hashes", ref,
                            "artifact_sha256",
                            "referenced artifact is not resolvable",
                        )
                    )
                    continue
                if isinstance(actual, Path):
                    try:
                        actual = _sha256_file(actual)
                    except OSError:
                        violations.append(
                            self._v(
                                "CK-HSH-003", "validate_hashes", ref,
                                "artifact_sha256",
                                "referenced artifact file is unreadable",
                            )
                        )
                        continue
                if str(recorded[ref]) != str(actual):
                    violations.append(
                        self._v(
                            "CK-HSH-002", "validate_hashes", ref,
                            "artifact_sha256",
                            "artifact_hash mismatch vs recomputed sha256",
                        )
                    )
        if self._records_reader is not None:
            for ref in _source_ref_ids(rec):
                if not self._resolve_record_ref(ref):
                    violations.append(
                        self._v(
                            "CK-HSH-003", "validate_hashes", ref,
                            "source_refs",
                            "source_ref does not resolve to a known record",
                        )
                    )
        return make_report("node_record", violations)

    def _resolve_record_ref(self, ref: str) -> bool:
        reader = self._records_reader
        if callable(reader):
            try:
                return reader(ref) is not None
            except KeyError:
                return False
        try:
            return ref in reader
        except TypeError:
            return False

    # ── 3. capability (CK-ACC-* / CK-ROL-901) ─────────────────────────

    def validate_capability(self, actor, action, resource) -> KernelReport:
        """Pure ``CAPABILITY_MATRIX`` lookup (plan 04 §5.4 item 3).

        Used pre-flight (adapter denies before dispatch) and post-hoc
        (Task 05 self-audit replays logged events through the same table).
        Retired-prompt-text access is CK-ACC-002; a registry write / candidate
        activation by anyone but the RegistryTransitionEngine is CK-ROL-901;
        the Task 11 meta actions (``emit_*``) resolve against the actor
        entry's §6.1 capability flags (deny-by-default) instead of the
        matrix; every other miss is CK-ACC-001.
        """
        role, tier = _actor_role_tier(actor)
        action = str(action)
        resource = str(resource)
        subject = f"{role}|{tier}"
        rule_id = f"CAPABILITY_MATRIX.{role}|{tier}"
        violations = []
        if resource == "retired_prompt_text":
            violations.append(
                self._v(
                    "CK-ACC-002", "validate_capability", subject, rule_id,
                    "retired prompt text is unreadable for every role "
                    "(clean-room regeneration has its own Task 08 path)",
                )
            )
        elif (
            (action, resource) in (("write", "registry"), ("activate", "candidates"))
            and role != self.rules.REGISTRY_WRITER
        ):
            violations.append(
                self._v(
                    "CK-ROL-901", "validate_capability", subject,
                    "REGISTRY_WRITER",
                    f"only {self.rules.REGISTRY_WRITER!r} may {action} "
                    f"{resource} (invariant 10)",
                )
            )
        elif action in meta_rules.META_ACTIONS:
            # Task 11 §5.5: closed meta-action vocabulary, per-entry flags.
            for detail in meta_rules.meta_action_denials(actor, action):
                violations.append(
                    self._v(
                        "CK-ACC-001", "validate_capability", subject,
                        f"CAPABILITY_FLAGS.{meta_rules.FLAG_BY_ACTION[action]}",
                        detail,
                    )
                )
        else:
            caps = self.rules.CAPABILITY_MATRIX.get((role, tier))
            if caps is None or (action, resource) not in caps:
                violations.append(
                    self._v(
                        "CK-ACC-001", "validate_capability", subject, rule_id,
                        f"({action}, {resource}) is not granted",
                    )
                )
        return make_report("capability", violations)

    # ── 4. epoch invariance (CK-EPO-*) ─────────────────────────────────

    def validate_epoch_invariance(self, epoch_state, event_log) -> KernelReport:
        """Frozen-active-set invariance over one epoch (plan 04 §5.4 item 4).

        *event_log* mixes registry events (``event_type`` items) and records
        (``record_id`` items): a non-emergency status-change event inside the
        epoch is CK-EPO-002 (block); a record created in the epoch whose
        ``prompt_hash`` is outside the frozen active set is CK-EPO-001 (warn).
        """
        epoch = _as_dict(epoch_state) if epoch_state is not None else {}
        epoch_id = str(epoch.get("epoch_id", ""))
        # Prefer the COMPLETE frozen active-hash set; fall back to the
        # role->incumbent rollup only for pre-field snapshots (replay of an
        # epoch frozen before this field existed). The rollup under-covers roles
        # with several active prompts (e.g. ``generator``), which false-flagged
        # governed non-incumbent prompts as CK-EPO-001.
        frozen = set(epoch.get("active_prompt_hash_set") or ()) or set(
            dict(epoch.get("active_prompt_hashes") or {}).values())
        violations = []
        for item in event_log or ():
            entry = _as_dict(item)
            event_type = str(
                entry.get("event_type", "")
                or getattr(item, "event_type", "")
            )
            if event_type:
                if event_type in _STATUS_CHANGE_EVENTS:
                    payload = entry.get("payload")
                    payload = payload if isinstance(payload, dict) else entry
                    subject = str(
                        payload.get("component_id")
                        or payload.get("prompt_id")
                        or entry.get("event_id", "")
                    )
                    violations.append(
                        self._v(
                            "CK-EPO-002", "validate_epoch_invariance",
                            subject, "epoch_freeze",
                            "non-emergency active-set change inside the "
                            "epoch (invariants 1-2)",
                        )
                    )
                continue
            rid = str(entry.get("record_id", ""))
            if not rid:
                continue
            if epoch_id and str(entry.get("epoch_id", "")) != epoch_id:
                continue
            prompt_hash = entry.get("prompt_hash")
            if prompt_hash and str(prompt_hash) not in frozen:
                violations.append(
                    self._v(
                        "CK-EPO-001", "validate_epoch_invariance", rid,
                        "epoch_freeze",
                        f"record prompt_hash {prompt_hash} is outside the "
                        f"frozen active set of {epoch_id or '<epoch>'}",
                    )
                )
        return make_report("epoch_transition", violations)

    # ── 4b. governed utility policy (CK-UTL-*, plan 14 §5.6) ───────────

    def validate_utility_policy(
        self, policy, *, registered_hash: str = "", live_axes=None
    ) -> KernelReport:
        """Is *policy* a LEGAL governed utility policy (plan 14 §5.6)?

        Pure and deterministic (no LLM, no network, no randomness): a policy
        is legal iff it lives inside the closed value spaces the constitution
        pins (:data:`ari.rqgm.kernel_rules.UTILITY_POLICY_RULES`). This is
        what stands between "the boundary may re-prioritise the axes" and
        "the boundary may delete a measurement from the method".

        *policy* is the policy BODY (with or without the ``utility_policy_hash``
        seal — the seal is ignored for membership checks and used only by
        CK-UTL-008). *registered_hash*, when given, is the identity the body
        must hash to. *live_axes*, when given, is the epoch's axis set for
        the CK-UTL-006 advisory.

        One validator, two callers (§5.6): ``validate_transition`` for every
        adoption targeting the ``utility_policy`` role, and the candidate
        pipeline's constitutional stage — never a duplicate rule copy.
        """
        rules = self.rules.UTILITY_POLICY_RULES
        body = {
            k: v for k, v in (_as_dict(policy) or {}).items()
            if k != "utility_policy_hash"
        }
        subject = registered_hash or "<utility_policy>"
        violations = []

        required = set(rules["required_keys"])
        present = set(body)
        missing = sorted(required - present)
        extra = sorted(present - required)
        if missing or extra:
            violations.append(self._v(
                "CK-UTL-001", "validate_utility_policy", subject,
                "UTILITY_POLICY_RULES.required_keys",
                f"policy key set is wrong (missing: {missing or 'none'}; "
                f"unexpected: {extra or 'none'})",
            ))

        composite = body.get("composite")
        if composite is not None and composite not in rules["allowed_composite"]:
            violations.append(self._v(
                "CK-UTL-002", "validate_utility_policy", subject,
                "UTILITY_POLICY_RULES.allowed_composite",
                f"composite {composite!r} is outside the closed set "
                f"{list(rules['allowed_composite'])}",
            ))

        frontier = body.get("frontier_score")
        if (
            frontier is not None
            and frontier not in rules["allowed_frontier_score"]
        ):
            violations.append(self._v(
                "CK-UTL-003", "validate_utility_policy", subject,
                "UTILITY_POLICY_RULES.allowed_frontier_score",
                f"frontier_score {frontier!r} is outside the closed set "
                f"{list(rules['allowed_frontier_score'])}",
            ))

        weights = body.get("axis_weights")
        if isinstance(weights, dict) and weights:
            lo = float(rules["axis_weight_min"])
            hi = float(rules["axis_weight_max"])
            for axis in sorted(weights):
                try:
                    w = float(weights[axis])
                except (TypeError, ValueError):
                    violations.append(self._v(
                        "CK-UTL-004", "validate_utility_policy", subject,
                        "UTILITY_POLICY_RULES.axis_weight_min/max",
                        f"axis {axis!r} weight {weights[axis]!r} is not a "
                        f"number",
                    ))
                    continue
                if w < lo or w > hi:
                    violations.append(self._v(
                        "CK-UTL-004", "validate_utility_policy", subject,
                        "UTILITY_POLICY_RULES.axis_weight_min/max",
                        f"axis {axis!r} weight {w} is outside [{lo}, {hi}] "
                        f"(the floor makes the axis set irreducible: a "
                        f"boundary may re-prioritise, never abolish)",
                    ))
            tol = float(self.tolerances["float_tolerance"])
            try:
                total = sum(float(v) for v in weights.values())
            except (TypeError, ValueError):
                total = None
            want = float(rules["axis_weight_sum"])
            if total is not None and abs(total - want) > tol:
                violations.append(self._v(
                    "CK-UTL-005", "validate_utility_policy", subject,
                    "UTILITY_POLICY_RULES.axis_weight_sum",
                    f"axis weights sum to {total}, expected {want} "
                    f"(tolerance {tol})",
                ))
            if live_axes:
                stale = sorted(set(weights) - set(live_axes))
                if stale:
                    # WARN, not block: under ``axis_mode: dynamic`` the live
                    # axis set is not the canonical five, and
                    # EvaluatorConfig.axis_weights already documents that
                    # unknown keys are silently dropped. A stale key is
                    # harmless by construction; blocking on it would make the
                    # kernel wrong about a config the evaluator handles.
                    violations.append(self._v(
                        "CK-UTL-006", "validate_utility_policy", subject,
                        "UTILITY_POLICY_RULES.axis_weights",
                        f"axis key(s) {stale} are outside the epoch's live "
                        f"axis set (silently dropped by the evaluator)",
                    ))

        for key, cap_key in (
            ("depth_penalty_lambda", "depth_penalty_lambda_max"),
            ("ucb_c", "ucb_c_max"),
        ):
            if key not in body:
                continue
            cap = float(rules[cap_key])
            try:
                val = float(body[key])
            except (TypeError, ValueError):
                violations.append(self._v(
                    "CK-UTL-007", "validate_utility_policy", subject,
                    f"UTILITY_POLICY_RULES.{cap_key}",
                    f"{key} {body[key]!r} is not a number",
                ))
                continue
            if val < 0.0 or val > cap:
                violations.append(self._v(
                    "CK-UTL-007", "validate_utility_policy", subject,
                    f"UTILITY_POLICY_RULES.{cap_key}",
                    f"{key} {val} is outside [0, {cap}]",
                ))

        if registered_hash:
            actual = payload_hash(body)
            if actual != str(registered_hash):
                violations.append(self._v(
                    "CK-UTL-008", "validate_utility_policy", subject,
                    "UTILITY_POLICY_RULES.identity",
                    f"policy body hashes to {actual}, but is registered as "
                    f"{registered_hash} (in-place mutation is prohibited)",
                ))
        return make_report("utility_policy", violations)

    # ── 5. transition (CK-REG-*) ───────────────────────────────────────

    def validate_transition(
        self, transition, registry, epoch_state, *, at_boundary: bool = True
    ) -> KernelReport:
        """Validate one EpochTransition (plan 04 §5.4 item 5, plan 09 §5.2).

        Table membership, rule-id parity, boundary/emergency shape, RTE
        authorship, from-status agreement with the registry, required
        supporting refs, and (for adoptions declaring capabilities) the
        invariant-18 authority sub-check. The kernel never *composes*
        transitions — Task 09's engine does; ``at_boundary`` is caller
        context, never a clock read.
        """
        t = _as_dict(transition)
        tid = str(
            t.get("epoch_transition_id") or t.get("transition_id") or ""
        ) or "<missing transition id>"
        violations = []
        produced_by = str(t.get("produced_by", ""))
        if produced_by != self.rules.REGISTRY_WRITER:
            violations.append(
                self._v(
                    "CK-REG-004", "validate_transition", tid,
                    "REGISTRY_WRITER",
                    f"transition produced_by {produced_by!r} is not the "
                    f"RegistryTransitionEngine (invariant 10)",
                )
            )
        emergency = bool(t.get("emergency"))
        changes = _transition_changes(t)
        lookup = _component_getter(registry)
        if emergency:
            violations.extend(self._emergency_shape(tid, t, changes))
        else:
            for _, entry in changes:
                violations.extend(
                    self._change_violations(entry, at_boundary=at_boundary)
                )
        # From-status must agree with the registry (both shapes). Prompt-only
        # spine changes (Task 09 T1/T3/...: no component yet) are checked
        # against the governed prompt registry instead.
        if registry is not None:
            prompt_entries = _prompt_entries(registry)
            for _, entry in changes:
                cid = str(entry.get("component_id", "") or "")
                pid = str(entry.get("prompt_id", "") or "")
                frm = str(entry.get("from_status", ""))
                if cid or not pid:
                    current = lookup(cid)
                else:
                    current = prompt_entries.get(pid)
                if current is None or str(getattr(current, "status", "")) != frm:
                    violations.append(
                        self._v(
                            "CK-REG-007", "validate_transition", cid or pid,
                            "TRANSITION_TABLE",
                            f"from_status {frm!r} contradicts the registry "
                            f"({'unknown entry' if current is None else getattr(current, 'status', '')!r})",
                        )
                    )
        # Required supporting refs (retirements + clean-room requests).
        # Scoped to T17 (quarantine -> retired): the never-served rejections
        # T2/T5 are terminal without a RetirementEvent (plan 09 §5.2).
        retirement_ids = set()
        for _, entry in changes:
            if (
                str(entry.get("to_status", "")) == "retired"
                and str(entry.get("from_status", "")) == "quarantine"
            ):
                rev = str(entry.get("retirement_event_id", "") or "")
                if rev:
                    retirement_ids.add(rev)
                if not rev or not entry.get("evidence_refs"):
                    violations.append(
                        self._v(
                            "CK-REG-005", "validate_transition",
                            str(entry.get("component_id", "")),
                            "TRANSITION_TABLE.T17",
                            "retirement lacks retirement_event_id or "
                            "supporting evidence_refs",
                        )
                    )
        for req in t.get("clean_room_requests") or ():
            req = _as_dict(req)
            rev = str(req.get("retirement_event_id", "") or "")
            if not rev or (retirement_ids and rev not in retirement_ids):
                violations.append(
                    self._v(
                        "CK-REG-005", "validate_transition",
                        str(req.get("request_id", "")),
                        "TRANSITION_TABLE.T17",
                        "clean-room request does not reference a retirement "
                        "event in this transition",
                    )
                )
        # Invariant 18 (authority non-expansion) over capability-declaring
        # adoptions. #79: compare the candidate against the INCUMBENT the
        # RegistryTransitionEngine attached (``_incumbent_entry``) — the kernel
        # is stateless, so the RTE (which holds the registry) supplies the
        # incumbent on the live path. Absent (unit callers / a genuinely new
        # role with no incumbent) it stays the conservative None baseline: the
        # fixed CAPABILITY_MATRIX cap plus the meta_rules deny-all flag
        # baseline. Also fires on flag/target-carrying entries, not only the
        # v1 ``declared_capabilities`` shape, so a §6.1 successor that widens
        # allowed_targets is caught even without a declared_capabilities list.
        for group, entry in changes:
            if group != "adoptions":
                continue
            if not (entry.get("declared_capabilities")
                    or meta_rules.has_capability_fields(entry)):
                continue
            incumbent = entry.get("_incumbent_entry")
            sub = self.validate_authority_non_expansion(entry, incumbent)
            violations.extend(sub.violations)
        # Task 14 §5.6: every adoption targeting the utility_policy role
        # carries its policy body for legality checking. An illegal policy is
        # BLOCKED before it can ever score a node; the boundary then proceeds
        # with the incumbent policy, which is always safe because the
        # incumbent is what produced the current frontier. There is no path
        # in which a rewrite fails OPEN into an unvalidated score.
        for group, entry in changes:
            if group != "adoptions":
                continue
            if str(entry.get("role", "")) != UTILITY_POLICY_ROLE:
                continue
            body = entry.get("policy")
            if not isinstance(body, dict):
                continue
            sub = self.validate_utility_policy(
                body,
                registered_hash=str(entry.get("prompt_hash", "") or ""),
                live_axes=entry.get("live_axes"),
            )
            violations.extend(sub.violations)
        return make_report("epoch_transition", violations)

    def _change_violations(self, entry: dict, *, at_boundary: bool) -> list:
        pair = (
            str(entry.get("from_status", "")),
            str(entry.get("to_status", "")),
        )
        subject = str(entry.get("component_id", ""))
        rule = transition_rules.TRANSITION_TABLE.get(pair)
        out = []
        if rule is None:
            out.append(
                self._v(
                    "CK-REG-001", "validate_transition", subject,
                    "TRANSITION_TABLE",
                    f"{pair[0]} -> {pair[1]} is not a permitted transition",
                )
            )
            return out
        declared = str(entry.get("rule_id", "") or "")
        if declared and declared != rule.rule_id:
            out.append(
                self._v(
                    "CK-REG-003", "validate_transition", subject,
                    f"TRANSITION_TABLE.{rule.rule_id}",
                    f"declared rule_id {declared!r} contradicts the table "
                    f"({rule.rule_id})",
                )
            )
        # Task 14 (plan 14 §5.5): T20 (active -> retired) is the utility_policy
        # SUPERSESSION edge and is legal ONLY for that role. For every
        # behavioral component active -> retired stays forbidden (retirement
        # must stage via quarantine), so the sanction-only replacement model is
        # constitutionally intact for them — the guard is here, not merely in
        # the engine that emits it.
        if pair == ("active", "retired") and str(
            entry.get("role", "")
        ) != UTILITY_POLICY_ROLE:
            out.append(
                self._v(
                    "CK-REG-001", "validate_transition", subject,
                    "TRANSITION_TABLE.T20",
                    "active -> retired is a utility_policy-only supersession "
                    "edge (behavioral roles must stage retirement via "
                    "quarantine)",
                )
            )
        # Paper-archive Task 05 / plan 03 §5.9 (wave 3c): T21 (active ->
        # shadow) is the paper-role shadow-standby supersession edge and is
        # legal ONLY for the paper roles. For every other role active ->
        # shadow stays forbidden, so their sanction-only replacement model is
        # constitutionally intact — the guard is here, not merely in the
        # engine that emits it (the T20 discipline).
        if pair == ("active", "shadow") and str(
            entry.get("role", "")
        ) not in transition_rules.PAPER_SUPERSESSION_ROLES:
            out.append(
                self._v(
                    "CK-REG-001", "validate_transition", subject,
                    "TRANSITION_TABLE.T21",
                    "active -> shadow is a paper-role-only shadow-standby "
                    "supersession edge (behavioral roles keep the "
                    "sanction-only replacement model)",
                )
            )
        if not at_boundary:
            # Every non-emergency commit is boundary-only; the T16 row's
            # boundary_only=False applies only under the emergency shape.
            out.append(
                self._v(
                    "CK-REG-002", "validate_transition", subject,
                    f"TRANSITION_TABLE.{rule.rule_id}",
                    "boundary-only transition stamped mid-epoch without the "
                    "emergency shape",
                )
            )
        return out

    def _emergency_shape(self, tid: str, t: dict, changes: list) -> list:
        """T16 shape (plan 09 §5.4): single sanction, target quarantine over
        an EMERGENCY_EDGE pair, kernel violation attached, rule_id T16."""
        out = []
        problems = []
        if len(changes) != 1:
            problems.append(f"{len(changes)} changes (must be exactly 1)")
        if not t.get("kernel_violation"):
            problems.append("no kernel violation record attached")
        if changes:
            entry = changes[0][1]
            pair = (
                str(entry.get("from_status", "")),
                str(entry.get("to_status", "")),
            )
            if pair not in transition_rules.EMERGENCY_EDGE:
                problems.append(
                    f"{pair[0]} -> {pair[1]} is not an emergency edge"
                )
            declared = str(entry.get("rule_id", "") or "")
            if declared and declared != transition_rules.EMERGENCY_RULE_ID:
                out.append(
                    self._v(
                        "CK-REG-003", "validate_transition",
                        str(entry.get("component_id", "")),
                        f"TRANSITION_TABLE.{transition_rules.EMERGENCY_RULE_ID}",
                        f"emergency transition declares rule_id {declared!r} "
                        f"(must be {transition_rules.EMERGENCY_RULE_ID})",
                    )
                )
        if problems:
            out.append(
                self._v(
                    "CK-REG-006", "validate_transition", tid,
                    f"TRANSITION_TABLE.{transition_rules.EMERGENCY_RULE_ID}",
                    "invalid emergency shape: " + "; ".join(problems),
                )
            )
        return out

    # ── 6. role separation (CK-ROL-*) ──────────────────────────────────

    def validate_role_separation(self, record) -> KernelReport:
        """Author-role and accusation rules (plan 04 §5.4 item 6).

        ImpeachmentMotion must be authored by the Auditor (CK-ROL-001),
        EvidenceBundle by the EvidenceClerk (CK-ROL-002); accuser role must
        differ from accused role (CK-ROL-003 — same-role outputs are
        observations, never accusations, invariants 4-7); and only the
        RegistryTransitionEngine ever appears as a registry writer
        (CK-ROL-901 — Judge writing the registry is the named violation).
        """
        rec = _as_dict(record)
        rid = str(rec.get("record_id", "")) or "<missing record_id>"
        rtype = str(rec.get("record_type", ""))
        role = str(rec.get("role", ""))
        violations = []
        required = self.rules.ROLE_RULES.get(rtype)
        if required is not None and role != required:
            code = (
                "CK-ROL-001" if rtype == "impeachment_motion" else "CK-ROL-002"
            )
            violations.append(
                self._v(
                    code, "validate_role_separation", rid,
                    f"ROLE_RULES.{rtype}",
                    f"{rtype} authored by role {role!r} (must be "
                    f"{required!r})",
                )
            )
        if rtype in self.rules.ACCUSATION_RECORD_TYPES:
            accuser = str(rec.get("accuser_role", "") or role)
            accused = str(
                rec.get("accused_role", "") or rec.get("target_role", "")
            )
            if accused and accuser == accused:
                violations.append(
                    self._v(
                        "CK-ROL-003", "validate_role_separation", rid,
                        "ACCUSATION_RECORD_TYPES",
                        f"same-role accusation ({accuser!r}): same-role "
                        "outputs are observations, never accusations",
                    )
                )
        if rtype in ("epoch_transition", "registry_write"):
            writer = str(
                rec.get("produced_by", "") or rec.get("actor", "") or role
            )
            if writer != self.rules.REGISTRY_WRITER:
                violations.append(
                    self._v(
                        "CK-ROL-901", "validate_role_separation", rid,
                        "REGISTRY_WRITER",
                        f"registry writer {writer!r} is not the "
                        "RegistryTransitionEngine (invariant 10)",
                    )
                )
        return make_report("node_record", violations)

    # ── 7. selective erasure (CK-ERA-*) ────────────────────────────────

    def validate_selective_erasure(
        self, frontier, records, prompt_registry, *, known_record_ids=None,
        prompt_trace=None,
    ) -> KernelReport:
        """The spec's kernel loop over a rebuilt frontier (§5.4 item 7).

        Every frontier record: ``stale is False`` (CK-ERA-001),
        ``valid_for_frontier is True`` (CK-ERA-002), ``prompt_hash`` not
        retired (CK-ERA-003). Every record depending on a retired prompt via
        the prompt_hash/source_refs closure must already be stale
        (CK-ERA-004, invariant 12). Erasure is logical-only: any previously
        known record id that no longer resolves is CK-ERA-005 (invariant 13).
        *prompt_trace* (parsed ``prompt_trace.jsonl`` line dicts) is the
        plan 10 §5.3 secondary-evidence cross-check: every trace line
        carrying a retired ``template_hash`` must map to a record produced
        by that prompt (CK-ERA-006) — the trace never becomes a second
        source of truth, it only proves the producer index complete.
        """
        recmap = _record_map(records)
        retired = _retired_prompt_hashes(prompt_registry)
        violations = []
        frontier_recs = []
        for item in frontier or ():
            if isinstance(item, str):
                rec = recmap.get(item)
                if rec is None:
                    violations.append(
                        self._v(
                            "CK-ERA-005", "validate_selective_erasure", item,
                            "logical_only_erasure",
                            "frontier references a record id that no longer "
                            "resolves (physical deletion, invariant 13)",
                        )
                    )
                    continue
            else:
                rec = _as_dict(item)
            frontier_recs.append(rec)
        for rec in frontier_recs:
            rid = str(rec.get("record_id", ""))
            if rec.get("stale", False):
                violations.append(
                    self._v(
                        "CK-ERA-001", "validate_selective_erasure", rid,
                        "frontier_admission",
                        "stale record present in the frontier",
                    )
                )
            if not rec.get("valid_for_frontier", True):
                violations.append(
                    self._v(
                        "CK-ERA-002", "validate_selective_erasure", rid,
                        "frontier_admission",
                        "valid_for_frontier=False record in the frontier",
                    )
                )
            ph = str(rec.get("prompt_hash") or "")
            if ph and ph in retired:
                violations.append(
                    self._v(
                        "CK-ERA-003", "validate_selective_erasure", rid,
                        "frontier_admission",
                        f"retired-prompt-derived record ({ph}) in the "
                        "frontier",
                    )
                )
        # Dependency closure (invariant 12): fixpoint over source_refs,
        # filtered by the Task 10 record-type-pair materiality table
        # (plan 10 §5.3 — context-designated citations do not propagate
        # staleness; unknown pairs stay load-bearing/conservative).
        tainted = {
            rid
            for rid, rec in recmap.items()
            if str(rec.get("prompt_hash") or "") in retired
        }
        changed = True
        while changed:
            changed = False
            for rid, rec in recmap.items():
                if rid in tainted:
                    continue
                if _cites_tainted(rec, tainted, recmap):
                    tainted.add(rid)
                    changed = True
        for rid in sorted(tainted):
            if not recmap[rid].get("stale", False):
                violations.append(
                    self._v(
                        "CK-ERA-004", "validate_selective_erasure", rid,
                        "staleness_closure",
                        "record depends on a retired prompt but is not "
                        "marked stale (invariant 12)",
                    )
                )
        for rid in sorted(known_record_ids or ()):
            if rid not in recmap:
                violations.append(
                    self._v(
                        "CK-ERA-005", "validate_selective_erasure", rid,
                        "logical_only_erasure",
                        "previously known record id no longer resolves "
                        "(physical deletion, invariant 13)",
                    )
                )
        # §5.3 prompt_trace cross-check (CK-ERA-006). Every trace line with
        # a retired template_hash sits inside that prompt's activation
        # window (governance forbids invoking a hash after retirement, and
        # repair runs at the retiring boundary), so each one must map to a
        # producer-index record: same hash, and — when both sides carry a
        # node anchor — the same node.
        producers: dict = {}
        for rid in sorted(recmap):
            ph = str(recmap[rid].get("prompt_hash") or "")
            if ph and ph in retired:
                producers.setdefault(ph, []).append(recmap[rid])
        for idx, line in enumerate(prompt_trace or ()):
            ln = line if isinstance(line, dict) else _as_dict(line)
            th = str(ln.get("template_hash") or "")
            if not th or th not in retired:
                continue
            node_id = str(ln.get("node_id") or "")
            matched = any(
                not node_id or _record_node_anchor(rec) in ("", node_id)
                for rec in producers.get(th, ())
            )
            if not matched:
                violations.append(
                    self._v(
                        "CK-ERA-006", "validate_selective_erasure",
                        f"prompt_trace[{idx}]", "prompt_trace_cross_check",
                        f"trace line (retired prompt {th}, node "
                        f"{node_id or '<unanchored>'}) maps to no record "
                        "produced by that prompt (plan 10 §5.3 cross-check)",
                    )
                )
        return make_report("frontier_rebuild", violations)

    # ── 8. audit-log integrity (CK-AUD-*) ──────────────────────────────

    def validate_audit_log_integrity(
        self, audit_log, *, checkpointed=None, verify_chain: bool | None = None
    ) -> KernelReport:
        """Append-only + hash-chain verification (plan 04 §5.4 item 8).

        *audit_log* is the parsed line-dict list (Task 02's
        ``ImmutableAuditLog.read`` shape). Sequence numbers must strictly
        increase (CK-AUD-001); *checkpointed* — an optional
        ``(length, last_event_hash)`` pair recorded at the last boundary —
        pins the prefix (CK-AUD-002); the per-line hash chain is recomputed
        over the canonical payload serialization (CK-AUD-003).
        ``verify_chain=None`` is the ``audit_chain: auto`` posture: verify
        iff chain fields are present. No check-time wall clock ever enters a
        verdict (P2) — timestamps in entries are data.
        """
        entries = [
            e if isinstance(e, dict) else _as_dict(e) for e in audit_log or ()
        ]
        violations = []
        last_seq = None
        for i, entry in enumerate(entries):
            m = _EVENT_ID_RE.match(str(entry.get("event_id", "")))
            if m is None:
                continue
            seq = int(m.group(1))
            if last_seq is not None and seq <= last_seq:
                violations.append(
                    self._v(
                        "CK-AUD-001", "validate_audit_log_integrity",
                        f"line {i}", "append_only",
                        f"sequence regression: evt seq {seq} after "
                        f"{last_seq}",
                    )
                )
            last_seq = seq
        chain_present = any(str(e.get("event_hash", "")) for e in entries)
        if verify_chain is None:
            verify_chain = chain_present
        if verify_chain and chain_present:
            prev_hash = ""
            for i, entry in enumerate(entries):
                recorded = str(entry.get("event_hash", ""))
                payload = entry.get("payload")
                payload = payload if isinstance(payload, dict) else {}
                if recorded and recorded != payload_hash(payload):
                    violations.append(
                        self._v(
                            "CK-AUD-003", "validate_audit_log_integrity",
                            f"line {i}", "hash_chain",
                            "event_hash does not match the canonical "
                            "payload hash",
                        )
                    )
                if str(entry.get("prev_event_hash", "")) != prev_hash:
                    violations.append(
                        self._v(
                            "CK-AUD-003", "validate_audit_log_integrity",
                            f"line {i}", "hash_chain",
                            "prev_event_hash breaks the chain",
                        )
                    )
                prev_hash = recorded
        if checkpointed:
            length, head = int(checkpointed[0]), str(checkpointed[1])
            if len(entries) < length:
                violations.append(
                    self._v(
                        "CK-AUD-002", "validate_audit_log_integrity",
                        f"line {max(0, length - 1)}", "prefix_pin",
                        "audit log is shorter than the check-pointed prefix",
                    )
                )
            elif length > 0 and str(
                entries[length - 1].get("event_hash", "")
            ) != head:
                violations.append(
                    self._v(
                        "CK-AUD-002", "validate_audit_log_integrity",
                        f"line {length - 1}", "prefix_pin",
                        "check-pointed prefix was mutated (chain head "
                        "mismatch)",
                    )
                )
        return make_report("audit_log", violations)

    # ── downstream-specified entry points (Tasks 08 / 11 / 12) ────────
    # The kernel API is closed at these twelve checks (plan 04 §5.4);
    # detailed input contracts / whitelists / thresholds belong to the
    # owning plans, under this task's verdict + severity model.

    def validate_clean_room_bundle(self, bundle, request, registries) -> KernelReport:
        """Task 08's pre-generation bundle screen (codes CK-CLN-001).

        Two layers of deterministic shape rules. The Task 04 v1 rules always
        run: every ``contains_*`` forbidden flag must be const-``False``; a
        ``forbidden_flags`` map must be all-false; when the request declares
        ``allowed_fields``, the bundle's key set must be inside it. When the
        request carries the Task 08 closed ``allowed_inputs`` contract
        (plan 08 §6.1), additionally: forbidden input flags const-false,
        the bundle's key set inside the closed ``BUNDLE_FIELDS`` whitelist,
        flag↔field parity (a switched-off allowed input must not
        materialize), FailureSummary admissibility (§6.3), and the
        pre-generation contamination screen over the bundle's text against
        the forbidden corpus in *registries* (``forbidden_texts`` /
        ``allowlist_texts``, resolved by the caller).
        """
        b = _as_dict(bundle)
        req = _as_dict(request) if request is not None else {}
        violations = []
        for key in sorted(b):
            if key.startswith("contains_") and b[key] is not False:
                violations.append(
                    self._v(
                        "CK-CLN-001", "validate_clean_room_bundle", key,
                        "clean_room_bundle",
                        f"forbidden flag {key!r} is not const-false",
                    )
                )
        flags = b.get("forbidden_flags")
        if isinstance(flags, dict):
            for key in sorted(flags):
                if flags[key]:
                    violations.append(
                        self._v(
                            "CK-CLN-001", "validate_clean_room_bundle", key,
                            "clean_room_bundle",
                            f"forbidden_flags[{key!r}] is set",
                        )
                    )
        allowed = req.get("allowed_fields")
        if allowed:
            allowed_set = set(str(f) for f in allowed)
            for key in sorted(set(b) - allowed_set):
                violations.append(
                    self._v(
                        "CK-CLN-001", "validate_clean_room_bundle", key,
                        "clean_room_bundle",
                        f"bundle field {key!r} is outside the request's "
                        "allowed field set",
                    )
                )
        allowed_inputs = req.get("allowed_inputs")
        if isinstance(allowed_inputs, dict):
            violations.extend(self._clean_room_contract(b, allowed_inputs))
            violations.extend(self._clean_room_prescreen(b, registries))
        return make_report("clean_room", violations)

    def _clean_room_contract(self, b: dict, allowed_inputs: dict) -> list:
        """The plan-08 closed-contract rules (active only for full Task 08
        requests, so the Task 04 v1 duck-typed shapes stay valid)."""
        out = []
        for key in clean_room_rules.FORBIDDEN_INPUT_KEYS:
            if bool(allowed_inputs.get(key, False)):
                out.append(
                    self._v(
                        "CK-CLN-001", "validate_clean_room_bundle", key,
                        "clean_room_bundle.allowed_inputs",
                        f"forbidden input flag {key!r} is not const-false",
                    )
                )
        skip = {"forbidden_flags"}
        for key in sorted(set(b) - set(clean_room_rules.BUNDLE_FIELDS)):
            if key in skip or key.startswith("contains_"):
                continue  # already checked by the v1 rules above
            out.append(
                self._v(
                    "CK-CLN-001", "validate_clean_room_bundle", key,
                    "clean_room_bundle.BUNDLE_FIELDS",
                    f"bundle field {key!r} is outside the closed "
                    "CleanRoomInputBundle field set",
                )
            )
        for key in clean_room_rules.ALLOWED_INPUT_KEYS:
            if not allowed_inputs.get(key, False) and b.get(key):
                out.append(
                    self._v(
                        "CK-CLN-001", "validate_clean_room_bundle", key,
                        "clean_room_bundle.allowed_inputs",
                        f"bundle materializes {key!r} although the request "
                        "switched that input off",
                    )
                )
        summary = b.get("abstract_failure_summary")
        if summary:
            for detail in clean_room_rules.failure_summary_failures(summary):
                out.append(
                    self._v(
                        "CK-CLN-001", "validate_clean_room_bundle",
                        "abstract_failure_summary",
                        "clean_room_bundle.failure_summary", detail,
                    )
                )
        return out

    @staticmethod
    def _clean_room_corpora(registries) -> tuple:
        """``(forbidden_docs, allowlist_docs)`` out of the duck-typed
        *registries* argument (dict or attribute object; both optional)."""
        if registries is None:
            return {}, ()
        if isinstance(registries, dict):
            forbidden = registries.get("forbidden_texts")
            allowlist = registries.get("allowlist_texts")
        else:
            forbidden = getattr(registries, "forbidden_texts", None)
            allowlist = getattr(registries, "allowlist_texts", None)
        if isinstance(forbidden, dict):
            docs = {str(k): str(v) for k, v in forbidden.items()}
        elif forbidden:
            docs = {
                "forbidden_%03d" % i: str(t)
                for i, t in enumerate(forbidden)
            }
        else:
            docs = {}
        return docs, [str(t) for t in allowlist or ()]

    def _clean_room_prescreen(self, b: dict, registries) -> list:
        """Pre-generation screen (plan 08 §5.5): any surviving shingle
        overlap between the bundle's text surface and the forbidden corpus
        means the assembler (or an out-of-band edit) leaked forbidden
        material — always blocking, independent of the post-check policy."""
        forbidden_docs, _ = self._clean_room_corpora(registries)
        if not forbidden_docs:
            return []
        k = int(self.tolerances["contamination_shingle_words"])
        parts = [str(b.get("role_spec") or "")]
        parts.extend(str(c) for c in b.get("constitutional_constraints") or ())
        parts.extend(str(r) for r in b.get("replay_requirements") or ())
        summary = b.get("abstract_failure_summary")
        if isinstance(summary, dict):
            parts.extend(
                str(r) for r in summary.get("behavioral_requirements") or ()
            )
        hits = clean_room_rules.contamination_hits(
            "\n".join(parts), forbidden_docs, (), k=k
        )
        return [
            self._v(
                "CK-CLN-001", "validate_clean_room_bundle", doc_id,
                "contamination_shingles",
                f"bundle text shares {len(hits[doc_id])}+ forbidden "
                f"{k}-shingle(s) with {doc_id}",
            )
            for doc_id in sorted(hits)
        ]

    def validate_contamination_free(
        self, candidate_text, retirement_event, records
    ) -> KernelReport:
        """Task 08's post-generation contamination screen (CK-CLN-002).

        Deterministic word-shingle overlap of the candidate text against the
        forbidden corpus (the retirement event's ``forbidden_texts`` plus any
        ``text``/``prompt_text`` fields on *records*), minus the allowlist
        corpus (``retirement_event["allowlist_texts"]`` — text shared with
        allowed inputs is legitimate, plan 08 §5.5). Policy comes from the
        injected tolerances: with ``contamination_fail_on_any_hit`` any
        surviving shingle blocks (the plan-08 default via
        ``rqgm.clean_room.contamination_screen``); otherwise the Task 04 v1
        ratio-vs-threshold semantics apply. Contamination blocks the
        candidate from registration (§5.5).
        """
        k = int(self.tolerances["contamination_shingle_words"])
        threshold = float(self.tolerances["contamination_threshold"])
        fail_on_any_hit = bool(
            self.tolerances.get("contamination_fail_on_any_hit", False)
        )
        event = _as_dict(retirement_event) if retirement_event is not None else {}
        subject = str(event.get("retirement_event_id", "") or "<candidate>")
        forbidden = event.get("forbidden_texts")
        if isinstance(forbidden, dict):
            forbidden_docs = {str(i): str(t) for i, t in forbidden.items()}
        else:
            forbidden_docs = {
                "forbidden_%03d" % i: str(t)
                for i, t in enumerate(forbidden or ())
            }
        for i, rec in enumerate(
            (records or {}).values() if isinstance(records, dict)
            else (records or ())
        ):
            rec = _as_dict(rec)
            text = rec.get("text") or rec.get("prompt_text")
            if text:
                doc_id = str(rec.get("record_id", "") or "record_%03d" % i)
                forbidden_docs[doc_id] = str(text)
        allowlist = [str(t) for t in event.get("allowlist_texts") or ()]
        violations = []
        if fail_on_any_hit:
            hits = clean_room_rules.contamination_hits(
                str(candidate_text), forbidden_docs, allowlist, k=k
            )
            for doc_id in sorted(hits):
                violations.append(
                    self._v(
                        "CK-CLN-002", "validate_contamination_free",
                        doc_id, "contamination_shingles",
                        f"candidate shares forbidden {k}-shingle(s) with "
                        f"{doc_id} (fail_on_any_hit)",
                    )
                )
        else:
            candidate = _shingles(candidate_text, k)
            if candidate:
                corpus = frozenset().union(
                    *(_shingles(t, k) for t in forbidden_docs.values())
                ) if forbidden_docs else frozenset()
                allow = frozenset().union(
                    *(_shingles(t, k) for t in allowlist)
                ) if allowlist else frozenset()
                overlap = len((candidate & corpus) - allow) / len(candidate)
                if overlap >= threshold:
                    violations.append(
                        self._v(
                            "CK-CLN-002", "validate_contamination_free",
                            subject, "contamination_shingles",
                            f"shingle overlap {round(overlap, 4)} >= "
                            f"threshold {threshold}",
                        )
                    )
        return make_report("clean_room", violations)

    def validate_authority_non_expansion(
        self, candidate_entry, incumbent_entry
    ) -> KernelReport:
        """Invariant 18 as pure set arithmetic (CK-REG-101; Task 11 flow).

        Three deterministic clauses, all CK-REG-101: (a) the Task 04 v1
        ``declared_capabilities`` pair-set subset check against the
        incumbent's declaration (else the fixed ``CAPABILITY_MATRIX`` cap);
        (b) the Task 11 §5.6.1 §6.1-flag arithmetic — per-flag implication,
        ``allowed_targets`` ⊆, ``forbidden_targets`` ⊇ (narrowing passes,
        widening blocks; active only when the candidate carries flag
        fields); (c) the §5.6.2 cross-generation rule — a meta-role
        candidate produced by an incumbent of the same role is rejected
        (rule_id ``CROSS_GENERATION``).
        """
        cand = _as_dict(candidate_entry)
        declared = _capability_pairs(cand.get("declared_capabilities"))
        inc = _as_dict(incumbent_entry) if incumbent_entry is not None else None
        if inc is not None:
            inc_declared = inc.get("declared_capabilities")
            if inc_declared:
                cap = _capability_pairs(inc_declared)
            else:
                cap = self.rules.CAPABILITY_MATRIX.get(
                    _actor_role_tier(inc), frozenset()
                )
        else:
            cap = self.rules.CAPABILITY_MATRIX.get(
                _actor_role_tier(cand), frozenset()
            )
        extra = declared - cap
        violations = []
        subject = str(cand.get("component_id", ""))
        if extra:
            listing = ", ".join(sorted(f"{a}:{r}" for a, r in extra))
            violations.append(
                self._v(
                    "CK-REG-101", "validate_authority_non_expansion",
                    subject, "CAPABILITY_MATRIX",
                    f"candidate declares capabilities beyond the incumbent "
                    f"role's cap: {listing} (invariant 18)",
                )
            )
        for detail in meta_rules.authority_expansion_findings(cand, inc):
            violations.append(
                self._v(
                    "CK-REG-101", "validate_authority_non_expansion",
                    subject, "CAPABILITY_FLAGS", detail,
                )
            )
        produced_by = cand.get("produced_by")
        producer_role = str(
            cand.get("produced_by_role", "")
            or (produced_by.get("role", "")
                if isinstance(produced_by, dict) else "")
        )
        for detail in meta_rules.cross_generation_failures(
            str(cand.get("role", "")), producer_role
        ):
            violations.append(
                self._v(
                    "CK-REG-101", "validate_authority_non_expansion",
                    subject, "CROSS_GENERATION", detail,
                )
            )
        return make_report("registry_write", violations)

    def validate_context_scope(self, role, view) -> KernelReport:
        """Task 12's role-view scope check (CK-CTX-001, warn-and-flag).

        The rendered view's key set must be inside the role's whitelist
        (v1: the BFTS ``ProposalSummaryView`` whitelist for ``generator``;
        roles without a whitelist are unchecked until Task 12 defines their
        views). Per §5.1 this never blocks node execution.
        """
        v = _as_dict(view)
        whitelist = self.rules.CONTEXT_VIEW_WHITELISTS.get(str(role))
        violations = []
        if whitelist is not None:
            extra = sorted(set(v) - set(whitelist))
            if extra:
                violations.append(
                    self._v(
                        "CK-CTX-001", "validate_context_scope", str(role),
                        f"CONTEXT_VIEW_WHITELISTS.{role}",
                        "view exceeds the role whitelist: "
                        + ", ".join(extra),
                    )
                )
        return make_report("context_scope", violations)


# ── enforcement helpers / adapters (plan 04 §5.5-§5.6) ─────────────────────


def should_block(report: KernelReport, enforcement: str = "standard") -> bool:
    """Apply the enforcement mode to a report (plan 04 §6 config sketch).

    ``audit_only`` downgrades every context to warn-and-log (ablations
    B4-B6 / Stage-1 rollout); the report itself keeps its severities so the
    audit trail stays truthful.
    """
    if enforcement == "audit_only":
        if report.blocking:
            log.warning(
                "kernel blocking report downgraded (enforcement=audit_only): "
                "%s", [v.code for v in report.violations],
            )
        return False
    return report.blocking


def per_node_warn_check(
    kernel: ConstitutionalKernel,
    records,
    *,
    registry=None,
    audit_log=None,
) -> "list[KernelReport] | None":
    """The §5.6.5 per-node warn hook body: cheap checks, never raises.

    Runs ``validate_record_schema`` + ``validate_hashes`` over the node's
    new records, warns on findings, and best-effort appends ``kernel_report``
    entries to the Task 02 audit log. Fail-open like every ``_run_loop``
    hook (MAP invariant: hooks never kill the run) — any internal error is
    swallowed and ``None`` returned.
    """
    try:
        reports: list[KernelReport] = []
        for record in records or ():
            for report in (
                kernel.validate_record_schema(record),
                kernel.validate_hashes(record, registry),
            ):
                reports.append(report)
                if report.violations:
                    log.warning(
                        "kernel per-node findings: %s",
                        [v.code for v in report.violations],
                    )
                if audit_log is not None and report.violations:
                    try:
                        audit_log.append(
                            "kernel_report",
                            kernel_report_audit_payload(
                                report, kernel.constitution_hash
                            ),
                        )
                    except Exception:
                        log.warning(
                            "kernel_report audit append failed", exc_info=True
                        )
        return reports
    except Exception:
        log.warning("per-node kernel check failed (fail-open)", exc_info=True)
        return None


class CapabilityGatedMCPClient:
    """Pre-flight capability gate at the MCP choke point (plan 04 §5.6.4).

    A duck-typed wrapper — never an edit to ``MCPClient`` — preserving the
    caller surface (``list_tools`` / ``call_tool`` / ``_COW_TOOLS`` /
    ``to_claude_mcp_config`` / ``close_all``) and the ``{"result"}/{"error"}``
    envelope. *tool_policy* maps ``(tool_name, args)`` to an
    ``(actor, action, resource)`` triple or ``None`` (= ungoverned tool,
    dispatched untouched). A blocking capability verdict is DENIED by
    returning the standard ``{"error": ...}`` envelope instead of
    dispatching; under ``enforcement=audit_only`` the call dispatches and
    the verdict is only logged. The CoW ``cow_node_id`` path is preserved
    untouched. Installed only under ``ari_rqgm`` (Tasks 05/08/11 wire it);
    ``simple_bfts`` never constructs this class.
    """

    def __init__(
        self,
        inner,
        kernel: ConstitutionalKernel,
        *,
        tool_policy,
        enforcement: str = "standard",
        audit_log=None,
        on_emergency=None,
    ) -> None:
        self.inner = inner
        self.kernel = kernel
        self._tool_policy = tool_policy
        self.enforcement = enforcement
        self._audit_log = audit_log
        #: ``(violation, tool_name, actor) -> None`` — invoked when a capability
        #: verdict carries a code in ``EMERGENCY_TRIGGER_CODES``. This is the
        #: ONLY place a running agent can trip the constitution mid-epoch, so
        #: it is where T16 (the emergency quarantine, the sole mid-epoch
        #: transition) has to be raised from. Without it `emergency_quarantine`
        #: had no production caller and T16 could never fire.
        self._on_emergency = on_emergency

    @property
    def _COW_TOOLS(self):  # noqa: N802 - mirrors the MCPClient attribute
        return self.inner._COW_TOOLS

    def list_tools(self, phase=None):
        return self.inner.list_tools(phase)

    def call_tool(self, tool_name, args, *, cow_node_id=None):
        mapping = None
        try:
            mapping = self._tool_policy(tool_name, args)
        except Exception:
            # A policy bug must not wedge research execution (fail-open for
            # unmapped/unmappable tools; real denials are the mapped path).
            log.warning("capability tool_policy failed for %s", tool_name,
                        exc_info=True)
        if mapping is not None:
            actor, action, resource = mapping
            report = self.kernel.validate_capability(actor, action, resource)
            if report.violations and self._audit_log is not None:
                try:
                    self._audit_log.append(
                        "kernel_report",
                        kernel_report_audit_payload(
                            report, self.kernel.constitution_hash
                        ),
                    )
                except Exception:
                    log.warning("kernel_report audit append failed",
                                exc_info=True)
            self._maybe_raise_emergency(report, tool_name, actor)
            if should_block(report, self.enforcement):
                codes = ", ".join(v.code for v in report.violations)
                return {
                    "error": (
                        f"constitutional kernel denied {action!r} on "
                        f"{resource!r} for tool {tool_name!r} ({codes})"
                    )
                }
        return self.inner.call_tool(tool_name, args, cow_node_id=cow_node_id)

    def _maybe_raise_emergency(self, report, tool_name: str, actor=None) -> None:
        """Escalate a constitutional violation to the emergency path (T16).

        Fires for any violation whose code is in ``EMERGENCY_TRIGGER_CODES``
        regardless of ``enforcement``: ``audit_only`` downgrades BLOCKING, not
        the constitutional fact, and the emergency transition is itself
        kernel-validated before it commits. Never raises — a failing hook must
        not wedge research execution."""
        if self._on_emergency is None or not report.violations:
            return
        try:
            from ari.rqgm.transition_engine import EMERGENCY_TRIGGER_CODES

            for v in report.violations:
                if getattr(v, "code", "") in EMERGENCY_TRIGGER_CODES:
                    self._on_emergency(v, tool_name, actor)
                    return
        except Exception:
            log.warning("emergency escalation hook failed", exc_info=True)

    def to_claude_mcp_config(self, *args, **kwargs):
        return self.inner.to_claude_mcp_config(*args, **kwargs)

    def close_all(self):
        return self.inner.close_all()

    def __getattr__(self, name):
        # Duck-type passthrough for any remaining MCPClient surface.
        return getattr(self.inner, name)
