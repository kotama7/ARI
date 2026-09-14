"""Adversarial actors + trigger policy + utility-penalty channel
(``docs/reference/rqgm_schemas.md``, "Adversarial-loop schemas (Task 06)").

Three prompt-defined institutional actors — :class:`AdversaryEngine`
(dispatcher over the adversary types), :class:`Defender`,
:class:`ArtifactJudge` — plus the deterministic pieces around them: the
per-type pre-signal filters (cheap and LLM-free), the per-node trigger
predicate :func:`should_attack` (P2-safe hash sampling), the
epoch-frozen :class:`UtilityPenaltyPolicy` and :func:`apply_utility_penalty`
(the sterile-gate precedent: ``_scientific_score`` is rewritten, the
pre-penalty value preserved in additive reserved keys).

LLM posture: all three actors run **in-process** through the
injectable ``llm`` seam (``complete(messages, require_tool=False)`` with
``phase="governance", skill="rqgm_adversarial"`` metadata; duck-typed
TypeError fallback for stubs) — never as MCP tools, so the 3-retry
double-logging hazard never arises. Every failure degrades: adversary fails →
no attacks; defender fails → ``defense_status: absent_infrastructure``;
judge fails → **fail-open** ``invalid`` verdicts (no ValidatedAttackRecord,
no penalty — safe precisely because of invariant 8).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from ari.rqgm.events import canonical_json, hash12
from ari.rqgm.adversarial.records import (
    ADVERSARY_TYPES,
    SEVERITIES,
    VERDICT_FACTOR,
    VERDICTS,
    DEFENSE_STANCES,
    DefenderResponse,
    EvidenceRef,
    JudgmentRecord,
    RawAttackRecord,
    TargetArtifact,
    UtilityRecord,
    created_at_now,
    format_utility_id,
    make_utility_record,
    raw_attack_violations,
)

log = logging.getLogger(__name__)

DEFENDER_PROMPT_KEY = "rqgm/defender"
JUDGE_PROMPT_KEY = "rqgm/judge_adjudication"

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)

#: Deterministic prompt-injection pre-filter patterns (the PromptInjection
#: adversary's pre-signal):
#: imperative-to-evaluator phrases and marker smuggling. Pure regex — the
#: LLM confirmation call happens only after a hit.
_INJECTION_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"ignore\s+(all\s+)?(previous|prior)\s+instructions", re.I),
    re.compile(r"score\s+(all\s+)?axes", re.I),
    re.compile(r"(reviewer|evaluator|judge)\s*:\s*(score|rate|assign)", re.I),
    re.compile(r"you\s+are\s+the\s+(reviewer|evaluator|judge)", re.I),
    re.compile(r"system\s*prompt", re.I),
    re.compile(r"<\s*/?\s*(system|instruction)s?\s*>", re.I),
)

#: Strong-novelty-claim keywords — the deterministic ``novelty`` clause of
#: :func:`should_attack`, and the extra condition the PriorArt/Overclaim
#: pre-signals require before they fall back to node text.
_NOVELTY_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"first[-\s]ever", re.I),
    re.compile(r"\bnovel\b", re.I),
    re.compile(r"state[-\s]of[-\s]the[-\s]art", re.I),
    re.compile(r"unprecedented", re.I),
    re.compile(r"\bfirst\s+to\b", re.I),
)

#: Host-local path smell in build/run commands — the Reproducibility
#: adversary's pre-signal.
_HOST_LOCAL_RE = re.compile(r"(^|[\s='\"])/(home|tmp|Users|scratch)/")


def _cfg(obj, name, default):
    """Duck-typed config read (typed model, raw dict, or absent)."""
    if isinstance(obj, dict):
        raw = obj.get(name, default)
    else:
        raw = getattr(obj, name, default)
    if raw is None:
        return default
    if isinstance(default, (list, tuple)):
        return list(raw) if isinstance(raw, (list, tuple)) else list(default)
    if isinstance(default, dict):
        if isinstance(raw, dict):
            return dict(raw)
        d = getattr(raw, "model_dump", None) or getattr(raw, "dict", None)
        try:
            return dict(d()) if callable(d) else default
        except Exception:
            return default
    try:
        return type(default)(raw)
    except (TypeError, ValueError):
        return default


def _extract_json(text: str) -> dict:
    """Deterministic best-effort JSON extraction (idea-skill convention)."""
    m = _JSON_RE.search(text or "")
    if not m:
        return {}
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def injection_pre_filter(text: str) -> list[str]:
    """Deterministic injection screen: matched pattern sources (may be [])."""
    hits: list[str] = []
    for pat in _INJECTION_PATTERNS:
        if pat.search(text or ""):
            hits.append(pat.pattern)
    return hits


def novelty_signal(text: str) -> bool:
    """Deterministic strong-novelty-claim keyword signal (a trigger clause of
    :func:`should_attack`)."""
    return any(pat.search(text or "") for pat in _NOVELTY_PATTERNS)


# ── artifact bundle (deterministic attack-surface snapshot) ─────────────────


@dataclass(frozen=True)
class ArtifactBundle:
    """The context-visibility slice the actors see: claims + novelty
    risks + metric details — never full VirSci transcripts."""

    node_id: str = ""
    proposal_text: str = ""
    eval_summary: str = ""
    node_report: dict = field(default_factory=dict)
    gate_findings: tuple = ()  # claim-gate finding dicts
    validate_metrics_flags: tuple = ()  # deterministic pre-check strings
    related_refs: tuple = ()  # prior-art refs (absent → no prior-art attacks)
    # Fixed K/C/A premises.  These are supplied to adversaries as immutable
    # evidence; the LLM may identify a contradictory claim/decision but may
    # not recompute a Binding or re-judge a Harness verdict.
    knowledge_skill_use_records: tuple = ()
    capability_binding_records: tuple = ()
    harness_attestations: tuple = ()
    verification_findings: tuple = ()
    active_harness_lock_digest: str = ""
    verification_contract_digest: str = ""
    score: float | None = None
    parent_score: float | None = None
    plan_step_count: int = 0
    remaining_node_budget: int = -1  # -1 == unknown (never triggers)
    node_report_path: str = ""
    # ── paper-archive self-preference fields (docs/reference/rqgm_schemas.md
    # "Paper-archive schemas": the eighth adversary type, inert off the paper
    # phase; ``self_preference_margin`` is that section's
    # ``paper_self_preference_stat.json`` AI-vs-human margin). Additive,
    # fail-safe defaults: read ONLY in PAPER_RQGM_ARCHIVE, so the seven
    # exploration adversaries and every existing bundle caller are
    # byte-identical. ``paper_candidate`` False and ``reviewer_accept_score``
    # None both make ``_pre_paper_self_preference`` return ``[]`` — off the
    # paper phase the eighth type never fires and costs zero LLM calls.
    paper_candidate: bool = False
    reviewer_accept_score: float | None = None  # None == not paper-scored
    accept_threshold: float = 0.6               # rqgm.paper.self_preference.accept_threshold
    self_preference_margin: float = 0.0         # computed AI-vs-human gap (0.0 == none)
    self_preference_threshold: float = 0.1      # rqgm.paper.self_preference.margin
    #: The anchor ``case_id`` the frozen incumbent reviewer OVER-ACCEPTED (its
    #: human ground truth is ``reject``) — the DIRECT per-draft signal, a
    #: different subject from the population statistic above. ``""`` == no
    #: per-draft over-acceptance recorded (every exploration node).
    anchor_over_accepted_case: str = ""


def _read_json_artifact(path):
    """Absence-tolerant JSON read (never raises; ``None`` == absent/invalid)."""
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return data
    except Exception:
        log.debug("artifact bundle: read failed for %s", path, exc_info=True)
    return None


#: Claim-evidence hard-gate phases, final-first so a re-run's authoritative
#: final findings sort ahead of the earlier draft ones (deterministic order).
_GATE_PHASES: tuple[str, ...] = ("final", "draft")


def _collect_gate_findings(ckpt) -> tuple:
    """Paper-phase claim-gate + verified-context pre-signals,
    normalized to the bundle's ``{kind, path, pointer}`` shape the
    ``_pre_*`` filters consume. Absent artifacts → ``()`` (fail-open).

    Sources (whatever exists in the checkpoint):

    * ``evaluation/claim_evidence_hard_gate_{final,draft}.json`` — the
      deterministic ``numeric_mismatch`` / ``missing_evidence`` /
      ``uncovered_numeric`` / ``invariant_violation`` findings the Overclaim
      and EvidenceGap adversaries cite (gate → adversary; plan 04 keeps the
      gate a separate fixed layer — the kernel never wraps it, adversaries
      only CONSUME its output).
    * ``verified_context.json`` limitations — grounding gaps for a stated
      claim become ``missing_evidence`` pre-signals for the Overclaim
      adversary.
    """
    out: list[dict] = []
    for phase in _GATE_PHASES:
        rel = f"evaluation/claim_evidence_hard_gate_{phase}.json"
        report = _read_json_artifact(ckpt / "evaluation"
                                     / f"claim_evidence_hard_gate_{phase}.json")
        if not isinstance(report, dict):
            continue
        for bucket in ("errors", "warnings"):
            for finding in report.get(bucket) or ():
                if not isinstance(finding, dict):
                    continue
                kind = str(finding.get("type", "") or "")
                if not kind:
                    continue
                pointer = str(
                    finding.get("claim_id")
                    or finding.get("numeric_id")
                    or finding.get("section")
                    or ""
                )
                out.append({"kind": kind, "path": rel, "pointer": pointer})
    verified = _read_json_artifact(ckpt / "verified_context.json")
    if isinstance(verified, dict):
        for lim in verified.get("limitations") or ():
            pointer = (
                str(lim.get("claim_id", "") or lim.get("ref", ""))
                if isinstance(lim, dict) else str(lim)[:120]
            )
            out.append({
                "kind": "missing_evidence",
                "path": "verified_context.json",
                "pointer": pointer,
            })
    return tuple(out)


def _collect_related_refs(ckpt) -> tuple:
    """Prior-art refs from ``related_refs.json`` — the PriorArt adversary's
    only evidence source. List, or a dict under any of the common ref keys;
    absent → ()."""
    data = _read_json_artifact(ckpt / "related_refs.json")
    if isinstance(data, list):
        refs = data
    elif isinstance(data, dict):
        refs = (
            data.get("refs")
            or data.get("related")
            or data.get("related_refs")
            or data.get("references")
            or []
        )
    else:
        refs = []
    return tuple(refs) if isinstance(refs, (list, tuple)) else ()


#: ``fixed_verifier_claim_contradiction`` vocabulary, split into the two
#: things an account of a fixed verdict can say.  The SUCCESS side is the
#: original pattern, unchanged on purpose: what counts as a success claim was
#: never the defect, so widening it here would smuggle a coverage change into
#: a precision repair.
#:
#: What WAS defective is how it was read.  Matching this pattern against
#: ``eval_summary + node.plan + json.dumps(report)`` fired on three things
#: that are not misrepresentations at all:
#:
#: * an honest failure report -- "the candidate is not numerically
#:   equivalent" matches ``numerically equivalent``, so a truthful evaluator
#:   and a lying one were indistinguishable, which is the entire distinction
#:   the finding exists to draw;
#: * a Generator plan -- "I will verify the kernel is correct by comparing
#:   ..." matches ``correct``, but the plan is written BEFORE the verdict
#:   exists and so cannot be an override of it;
#: * the system's own data -- a report carrying ``{"harness": {"status":
#:   "verified"}}`` matches ``verified``, the catalog's own status word
#:   appearing as a field VALUE.
_SUCCESS_CLAIM_RE = re.compile(
    r"\b(correct|verified|validated|certified|all\s+tests?\s+pass(?:ed)?|"
    r"numerically\s+equivalent|no\s+regressions?)\b",
    re.I,
)

#: The other half of the discriminator: the words by which an account ADMITS
#: the recorded outcome.  An account that states the failure is reporting it,
#: whatever else it also says; only an account that asserts success *and*
#: never admits the failure is misrepresenting one.
#:
#: Restricted to the verdict itself rather than to trouble in general: if an
#: incidental "compile error" counted as owning up to a failed Attestation, a
#: misrepresentation could buy silence with one unrelated sentence.
_FAILURE_ADMISSION_RE = re.compile(
    r"\b(fail(?:s|ed|ing|ure|ures)?|did\s+not\s+pass|does\s+not\s+pass|"
    r"mismatch(?:es|ed)?|discrepanc(?:y|ies)|diverg(?:e|es|ed|ence)|"
    r"incorrect(?:ly|ness)?|wrong|regressions?|inconclusive|tampered|"
    r"exceed(?:s|ed)?\s+(?:the\s+)?tolerance|tolerance\s+exceeded)\b",
    re.I,
)

#: Left-context markers that invert a term.  A NEGATED success word is not a
#: weaker claim, it is an admission ("not numerically equivalent" says the
#: same thing the Attestation says); a negated failure word ("no mismatch")
#: is not an admission.
_CLAIM_NEGATION_RE = re.compile(
    r"(\bnot\b|\bno\b|\bnever\b|\bnor\b|\bneither\b|\bwithout\b|"
    r"\bcannot\b|\bunable\s+to\b|\blacks?\b|\bmissing\b|\babsent\b|"
    r"\bfail(?:s|ed)\s+to\b|\b(?:is|are|was|were|does|do|did|has|have|had|"
    r"would|could|should|will|ca|wo)n['’]t\b)",
    re.I,
)

#: Left-context markers that make a sentence a PROPOSAL rather than a report.
#: An intention to establish correctness is not a claim to have established
#: it.  ``node.plan`` is excluded outright, but ``eval_summary`` is
#: documented dual-use state that can still hold planner direction when no
#: evaluator ran (``node_report/builder.py``), so the same category error can
#: arrive through a surface that is legitimately read.
_CLAIM_HEDGE_RE = re.compile(
    r"\b(will|would|shall|should|must|may|might|could|"
    r"plans?\s+to|planned\s+to|planning\s+to|intends?\s+to|intended\s+to|"
    r"aims?\s+to|aimed\s+to|expects?\s+to|expected\s+to|hopes?\s+to|"
    r"tr(?:y|ies|ied)\s+to|attempts?\s+to|attempted\s+to|going\s+to|"
    r"needs?\s+to|needed\s+to|wants?\s+to|in\s+order\s+to|so\s+that|"
    r"to\s+(?:confirm|ensure|check|prove|show|demonstrate|establish|verify)|"
    r"if|whether|unless|todo|next\s+step)\b",
    re.I,
)

#: Clause boundary.  Sentence terminators are kept at the END of the clause
#: they close so an interrogative can be told from an assertion, and
#: contrastive conjunctions split too, so "the kernel is correct but the
#: harness reported a fail" is read as a claim beside its own retraction
#: rather than as one undifferentiated string.
_CLAUSE_SPLIT_RE = re.compile(
    r"(?<=[.;!?\n])\s*|\b(?:but|however|although|though|whereas|yet)\b",
    re.I,
)

#: How far back a negation or hedge is allowed to reach.  Unbounded
#: left-context leaks both ways: a marker several clauses back would silence a
#: real claim, and splitting more aggressively (on commas) would strip a
#: negation off the term it modifies.  English puts both kinds of marker close
#: to what they modify.
_CLAIM_CONTEXT_CHARS = 96


def _account_polarity(text: str) -> tuple[bool, bool]:
    """Read *text* as an account of a fixed verdict.

    Returns ``(asserts_success, admits_failure)``.  The two are independent:
    text can do both (an honest mixed report), neither (a bare failure
    detail), or one alone.  Only ``asserts and not admits`` misrepresents.
    """

    asserts = False
    admits = False
    for clause in _CLAUSE_SPLIT_RE.split(text or ""):
        clause = (clause or "").strip()
        if not clause or clause.endswith("?"):
            continue
        for match in _SUCCESS_CLAIM_RE.finditer(clause):
            left = clause[max(0, match.start() - _CLAIM_CONTEXT_CHARS):match.start()]
            if _CLAIM_NEGATION_RE.search(left):
                admits = True
            elif not _CLAIM_HEDGE_RE.search(left):
                asserts = True
        for match in _FAILURE_ADMISSION_RE.finditer(clause):
            left = clause[max(0, match.start() - _CLAIM_CONTEXT_CHARS):match.start()]
            if not _CLAIM_NEGATION_RE.search(left):
                admits = True
    return asserts, admits


def _claim_surfaces(node, report) -> str:
    """The node's own account of the OUTCOME, and only that.

    Excluded, each for a different reason:

    * ``node.plan`` -- written by the Generator before the verdict exists.
      Whatever it says about correctness is a proposal, and a proposal cannot
      override a result that has not happened yet.
    * ``json.dumps(report)`` -- the report carries the catalog's own status
      vocabulary as field VALUES, plus file names, metric keys, command lines
      and trace text.  A detector that matches its own system's data is
      matching noise.  Named prose fields are read instead.
    * ``self_assessment`` unless ``self_report_stage`` is ``post_evaluation``
      -- the report records whether the agent wrote its self-review after
      being scored.  When it did not, that text is a plan by another name.
    """

    parts = [str(getattr(node, "eval_summary", "") or "")]
    if isinstance(report, dict):
        parts.append(str(report.get("evaluator_reason", "") or ""))
        parts.append(str(report.get("what_was_done", "") or ""))
        if str(report.get("self_report_stage", "") or "") == "post_evaluation":
            assessment = report.get("self_assessment")
            if isinstance(assessment, dict):
                parts.append(str(assessment.get("headline", "") or ""))
                parts.extend(
                    str(item) for item in (assessment.get("concerns") or ())
                )
    return "\n".join(part for part in parts if part)


def _failing_attestations_for(node, attestations) -> list:
    """Failing Attestations about what THIS node produced.

    An account can only misrepresent the verdict on the artifact it is an
    account OF.  Reading every failing record in the log instead means a
    REPAIRED node -- one whose predecessor failed and whose own candidate
    passed -- is accused by its own honest success report, because the audit
    log still holds the earlier candidate's failing Attestation.  Measured: a
    node with ``assurance_status`` "pass" on the scientific frontier, reporting
    its pass truthfully, raised the finding on a failing Attestation for a
    digest it had already replaced.

    Where the node names no ``verified_target_digest`` the subject cannot be
    established, and every failing record is kept rather than none: the sibling
    records arm answers "unknown subject" with silence because it compares two
    records and needs both, while this arm would lose its whole reach.  A
    false positive there is a wrong accusation; silence here would be a missed
    one, and of the two the wrong accusation is the one a repaired node meets
    on an ordinary day.
    """

    records = [item for item in attestations
               if isinstance(item, dict) and str(item.get("verdict", "")) == "fail"]
    target = str(getattr(node, "verified_target_digest", "") or "")
    if not target:
        return records
    scoped = [item for item in records
              if str(item.get("target_digest", "") or "") == target]
    # A record carrying no target digest at all cannot be excluded on one:
    # it is un-attributed rather than attributed elsewhere.
    scoped.extend(item for item in records if not item.get("target_digest"))
    return scoped


def _verdicts_misreported_against(node, attestations) -> str:
    """``record_id`` of a failing Attestation whose failed properties the
    node's own merged ``property_verdicts`` records as ``pass``.

    The same accusation as the prose arm, made against records instead of
    words, so it survives an attacker who writes nothing -- or writes
    carefully.  The bridge merges the WORST verdict per property from the
    Attestations it just wrote, so ``pass`` standing against a ``fail`` for
    the same property on the same artifact means the merge was rewritten
    after the verdict was fixed.  Only ``pass`` counts: ``inconclusive``
    beside ``fail`` is a lesser record, not a claim of success.

    Scoped to Attestations bound to the node's CURRENT
    ``verified_target_digest`` -- after a repair the audit log still holds the
    previous candidate's failing Attestation, and a pass on a different
    artifact does not contradict it.  Without both digests the comparison has
    no subject, so this arm stays silent rather than guessing; the prose arm
    is unaffected by that silence.
    """

    target = str(getattr(node, "verified_target_digest", "") or "")
    claimed = {
        str(name): str(verdict)
        for name, verdict in (getattr(node, "property_verdicts", None) or {}).items()
    }
    if not target or not claimed:
        return ""
    for item in attestations:
        if not isinstance(item, dict) or str(item.get("verdict", "")) != "fail":
            continue
        if str(item.get("target_digest", "") or "") != target:
            continue
        nested = item.get("attestation")
        results = item.get("property_results") or (
            (nested.get("property_results") or ())
            if isinstance(nested, dict) else ()
        )
        for result in results:
            if not isinstance(result, dict):
                continue
            if str(result.get("verdict", "")) != "fail":
                continue
            if claimed.get(str(result.get("property_id", "") or "")) == "pass":
                return str(item.get("record_id", ""))
    return ""


def _kca_audit_records(ckpt, node_id: str):
    knowledge: list[dict] = []
    bindings: list[dict] = []
    attestations: list[dict] = []
    try:
        from ari.rqgm.store import ImmutableAuditLog

        buckets = {
            "knowledge_skill_use": knowledge,
            "capability_binding": bindings,
            "harness_attestation": attestations,
        }
        for line in ImmutableAuditLog.read(ckpt):
            payload = line.get("payload") if isinstance(line, dict) else None
            if not isinstance(payload, dict) or str(payload.get("node_id", "")) != node_id:
                continue
            bucket = buckets.get(str(payload.get("record_type", "")))
            if bucket is not None:
                bucket.append(payload)
    except Exception:
        log.debug("artifact bundle: KCA audit scan failed", exc_info=True)
    return knowledge, bindings, attestations


def _binding_integrity_findings(bindings: list[dict]) -> list[dict]:
    findings: list[dict] = []
    for record in bindings:
        pointer = str(record.get("record_id", ""))
        decisions = record.get("invocation_decisions") or ()
        if record.get("unbound_tool_refs") or any(
            str(item.get("reason_code", "")) != "bound"
            for item in decisions
            if isinstance(item, dict)
        ):
            findings.append({
                "kind": "unbound_tool_invocation",
                "path": "rqgm_audit.jsonl",
                "pointer": pointer,
            })
        if record.get("provider_schema_drift"):
            findings.append({
                "kind": "provider_schema_drift",
                "path": "rqgm_audit.jsonl",
                "pointer": pointer,
            })
    return findings


def _assurance_contradiction_findings(node, report, attestations, node_id):
    status = str(getattr(node, "assurance_status", "") or "")
    if status == "infrastructure_error":
        return []
    findings: list[dict] = []
    failed = _failing_attestations_for(node, attestations)
    if failed:
        # Two independent arms for one accusation -- an evaluator asserting
        # success over a failing Attestation -- because it can be made in
        # either medium.  The records arm is checked first so its pointer,
        # which names the exact Attestation whose properties were rewritten,
        # wins over the prose arm's first-failing-record pointer.
        pointer = _verdicts_misreported_against(node, attestations)
        if not pointer:
            asserts, admits = _account_polarity(_claim_surfaces(node, report))
            if asserts and not admits:
                pointer = str(failed[0].get("record_id", ""))
        if pointer:
            findings.append({
                "kind": "fixed_verifier_claim_contradiction",
                "path": "rqgm_audit.jsonl",
                "pointer": pointer,
            })
    if status == "inconclusive" and not attestations:
        findings.append({
            "kind": "required_attestation_missing",
            "path": f"rqgm/kca/nodes/{node_id}/assurance_summary.json",
            "pointer": "/assurance_status",
        })
    if status == "tampered":
        findings.append({
            "kind": "assurance_integrity_failure",
            "path": f"rqgm/kca/nodes/{node_id}/assurance_summary.json",
            "pointer": "/assurance_status",
        })
    if status not in {"", "pass"} and str(
        getattr(node, "frontier_class", "") or ""
    ) == "scientific_frontier":
        findings.append({
            "kind": "verifier_result_ignored",
            "path": f"rqgm/kca/nodes/{node_id}/assurance_summary.json",
            "pointer": "/frontier_class",
        })
    return findings


def _knowledge_authority_findings(ckpt, knowledge: list[dict]) -> list[dict]:
    findings: list[dict] = []
    try:
        admission = ckpt / "rqgm" / "kca" / "admission-v1"
        bodies = _read_json_artifact(admission / "knowledge_bodies.json") or {}
        used_hashes = {
            str(ref.get("body_sha256", ""))
            for record in knowledge
            for ref in ((record.get("node_use") or {}).get("ordered_skills") or ())
            if isinstance(ref, dict)
        }
        forbidden = (
            "bypass verification",
            "skip the harness",
            "read the secret",
            "rewrite the registry",
            "increase authority",
        )
        for body_hash in sorted(used_hashes):
            body = str(bodies.get(body_hash, ""))
            if injection_pre_filter(body) or any(
                phrase in body.lower() for phrase in forbidden
            ):
                findings.append({
                    "kind": "knowledge_authority_instruction",
                    "path": "rqgm/kca/admission-v1/knowledge_bodies.json",
                    "pointer": body_hash,
                })
    except Exception:
        log.debug("artifact bundle: locked Knowledge scan failed", exc_info=True)
    return findings


def _collect_kca_evidence(ckpt, node, report: dict) -> tuple:
    """Return typed K/C/A records and deterministic contradiction signals.

    A plain candidate ``fail`` is intentionally not a governance signal.  It
    becomes one only when a claim, score, frontier decision, or provenance
    record contradicts the fixed result.  Infrastructure failure is always
    excluded from attack pre-signals.
    """

    node_id = str(getattr(node, "id", "") or "")
    knowledge, bindings, attestations = _kca_audit_records(ckpt, node_id)
    findings = _binding_integrity_findings(bindings)
    findings.extend(
        _assurance_contradiction_findings(node, report, attestations, node_id)
    )
    findings.extend(_knowledge_authority_findings(ckpt, knowledge))

    key = lambda item: str(item.get("record_id", ""))
    finding_key = lambda item: (
        str(item.get("kind", "")), str(item.get("path", "")),
        str(item.get("pointer", "")),
    )
    return (
        tuple(sorted(knowledge, key=key)),
        tuple(sorted(bindings, key=key)),
        tuple(sorted(attestations, key=key)),
        tuple(sorted(findings, key=finding_key)),
    )


def _validate_metrics_flags_from_gate(gate_findings) -> tuple:
    """Deterministic metric-gaming flags derived from the gate findings
    (the MetricGaming evidence source: ``validate_metrics`` flags + env
    mismatch). Numeric-mismatch / environment-mismatch gate findings are the
    persisted, checkpoint-resolvable form of those pre-checks."""
    kinds = {str(f.get("kind", "")) for f in gate_findings}
    flags = [
        kind for kind in ("numeric_mismatch", "environment_mismatch")
        if kind in kinds
    ]
    return tuple(flags)


def _normalize_report_commands(report: dict) -> None:
    """Bridge the node_report's singular ``build_command`` / ``run_command``
    (builder shape) to the plural ``build_commands`` / ``run_commands`` lists
    the Reproducibility pre-signal scans for host-local paths. Additive and
    idempotent; a report already carrying the plural keys is left untouched."""
    if not report.get("build_commands"):
        bc = report.get("build_command")
        report["build_commands"] = [bc] if bc else []
    if not report.get("run_commands"):
        rc = report.get("run_command")
        report["run_commands"] = [rc] if rc else []


def build_artifact_bundle(
    node, checkpoint_dir=None, *, remaining_node_budget: int = -1,
) -> ArtifactBundle:
    """Deterministic bundle assembly off the completed node (never raises).

    Reads the node's ``node_report.json`` plus, when *checkpoint_dir* is
    given, the paper-phase pre-signal artifacts (claim-evidence hard-gate
    reports, ``verified_context.json``, ``related_refs.json``) so the paper
    adversaries fire on real signals instead of degrading to the node-text
    fallback — each type's evidence source is the artifact its ``_pre_*``
    filter reads. Absent artifacts →
    empty pre-signals (fail-open). No LLM, no network (P2).
    """
    from pathlib import Path

    metrics = getattr(node, "metrics", None) or {}
    score = metrics.get("_scientific_score")
    report: dict = {}
    report_path = ""
    try:
        wd = str(getattr(node, "work_dir", "") or "")
        if wd:
            p = Path(wd) / "node_report.json"
            if p.exists():
                loaded = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    report = loaded
                    report_path = str(p)
    except Exception:
        log.debug("artifact bundle: node_report read failed", exc_info=True)
    if not report:
        # The per-node round runs BEFORE `write_node_report` on purpose — so the
        # written report carries the GOVERNED (post-attack) score
        # (`ari/cli/bfts_loop.py`:777-781). The consequence was that the file
        # this bundle documents itself as reading does not exist yet, and
        # `node_report` was `{}` on EVERY per-node round: `_pre_reproducibility`
        # (build/run commands), `_pre_metric_gaming` (compute_env) and the
        # prompt-injection text scan all had nothing to read, so the
        # reproducibility adversary could never fire. Build the same report in
        # memory instead of reordering the hook — that keeps the governed-score
        # guarantee intact and costs a build only when a round actually runs.
        try:
            wd = str(getattr(node, "work_dir", "") or "")
            if wd and Path(wd).is_dir():
                from ari.orchestrator.node_report import build_node_report

                built = build_node_report(
                    node=node, work_dir=Path(wd), parent_work_dir=None,
                )
                if isinstance(built, dict):
                    report = built
        except Exception:
            log.debug("artifact bundle: in-memory node_report build failed",
                      exc_info=True)
    if report:
        _normalize_report_commands(report)
    gate_findings: tuple = ()
    related_refs: tuple = ()
    validate_metrics_flags: tuple = ()
    knowledge_records: tuple = ()
    capability_records: tuple = ()
    harness_attestations: tuple = ()
    verification_findings: tuple = ()
    active_harness_lock_digest = str(
        getattr(node, "active_harness_lock_digest", "") or ""
    )
    verification_contract_digest = ""
    if checkpoint_dir is not None:
        try:
            ckpt = Path(checkpoint_dir)
            gate_findings = _collect_gate_findings(ckpt)
            related_refs = _collect_related_refs(ckpt)
            validate_metrics_flags = _validate_metrics_flags_from_gate(
                gate_findings
            )
            (
                knowledge_records,
                capability_records,
                harness_attestations,
                verification_findings,
            ) = _collect_kca_evidence(ckpt, node, report)
            admission = _read_json_artifact(
                ckpt / "rqgm" / "kca" / "admission-v1" / "run_admission.json"
            )
            if isinstance(admission, dict):
                verification_contract_digest = str(
                    admission.get("verification_contract_digest", "") or ""
                )
        except Exception:
            log.debug("artifact bundle: pre-signal artifact read failed",
                      exc_info=True)
    plan_text = str(getattr(node, "plan", "") or "")
    # Paper-archive self-preference fields (docs/reference/rqgm_schemas.md
    # "Paper-archive schemas").
    # Read ONLY from the node's reserved paper metrics keys — the paper
    # runtime stamps them on the synthetic over-accepted-draft node it drives
    # the round against. For every exploration/linear node these keys are
    # absent, so the block is a no-op and the bundle is byte-identical to
    # today's (fail-safe defaults never trigger the eighth type).
    paper_candidate = bool(metrics.get("_paper_self_preference_candidate"))
    accept_raw = metrics.get("_reviewer_accept_score")
    reviewer_accept_score = (
        float(accept_raw) if isinstance(accept_raw, (int, float)) else None
    )
    return ArtifactBundle(
        node_id=str(getattr(node, "id", "") or ""),
        proposal_text=plan_text,
        eval_summary=str(getattr(node, "eval_summary", "") or ""),
        node_report=report,
        gate_findings=gate_findings,
        validate_metrics_flags=validate_metrics_flags,
        related_refs=related_refs,
        knowledge_skill_use_records=knowledge_records,
        capability_binding_records=capability_records,
        harness_attestations=harness_attestations,
        verification_findings=verification_findings,
        active_harness_lock_digest=active_harness_lock_digest,
        verification_contract_digest=verification_contract_digest,
        score=float(score) if isinstance(score, (int, float)) else None,
        plan_step_count=plan_text.count("###"),
        remaining_node_budget=int(remaining_node_budget),
        node_report_path=report_path,
        paper_candidate=paper_candidate,
        reviewer_accept_score=reviewer_accept_score,
        accept_threshold=_metric_float(metrics, "_self_preference_accept_threshold", 0.6),
        self_preference_margin=_metric_float(metrics, "_self_preference_margin", 0.0),
        self_preference_threshold=_metric_float(metrics, "_self_preference_threshold", 0.1),
        anchor_over_accepted_case=str(
            metrics.get("_paper_anchor_over_accepted_case", "") or ""
        ),
    )


def _metric_float(metrics: dict, key: str, default: float) -> float:
    """Read a reserved paper metrics key as a float (absent/invalid ->
    *default*), so an exploration node with none of these keys yields the
    fail-safe defaults and the bundle is byte-identical to today's."""
    raw = metrics.get(key)
    return float(raw) if isinstance(raw, (int, float)) else float(default)


# ── trigger predicate (pure, P2-safe) ───────────────────────────────────────


def deterministic_sample(node_id: str, epoch_id: str, sample_mod: int) -> bool:
    """``hash(node_id + epoch_id) mod N == 0`` — content hash, never RNG."""
    if sample_mod <= 0:
        return False
    return int(hash12(str(node_id) + str(epoch_id)), 16) % int(sample_mod) == 0


def should_attack(
    *,
    node_id: str,
    epoch_id: str = "",
    score: float | None = None,
    parent_score: float | None = None,
    frontier_scores=(),
    novelty: bool = False,
    pre_signal: bool = False,
    paper_candidate: bool = False,
    top_k: int = 3,
    jump_threshold: float = 0.25,
    sample_mod: int = 5,
) -> bool:
    """The trigger disjunction — deterministic per completed node: frontier
    top-K membership, a score jump over the parent, a novelty/pre-signal/
    paper-candidate flag, or the 1-in-N deterministic sample.

    Numbers are Task 12's to tune; the clause shape is fixed here.
    """
    if score is not None and top_k > 0:
        ranked = sorted(
            (float(s) for s in frontier_scores or ()), reverse=True
        )
        if len(ranked) < top_k or float(score) >= ranked[top_k - 1]:
            return True
    if (
        score is not None
        and parent_score is not None
        and float(score) - float(parent_score) > float(jump_threshold)
    ):
        return True
    if novelty or pre_signal or paper_candidate:
        return True
    return deterministic_sample(node_id, epoch_id, sample_mod)


# ── the adversary specs (target class + pre-signal per type) ────────────────


def _gate_evidence(bundle: ArtifactBundle, kinds: tuple) -> list[EvidenceRef]:
    out = []
    for f in bundle.gate_findings:
        d = f if isinstance(f, dict) else {}
        if str(d.get("kind", "")) in kinds:
            out.append(
                EvidenceRef(
                    path=str(d.get("path", "") or "claims.json"),
                    pointer=str(d.get("pointer", "") or ""),
                )
            )
    return out


def _verification_evidence(
    bundle: ArtifactBundle, kinds: tuple[str, ...]
) -> list[EvidenceRef]:
    """Evidence refs for deterministic K/C/A findings, without re-judgment."""

    out: list[EvidenceRef] = []
    # Duck-typed test/legacy bundles predate Task 19. Absence means there is
    # no fixed K/C/A pre-signal; it must not fail the ordinary adversarial
    # round open or manufacture evidence.
    for finding in getattr(bundle, "verification_findings", ()) or ():
        item = finding if isinstance(finding, dict) else {}
        if str(item.get("kind", "")) not in kinds:
            continue
        out.append(EvidenceRef(
            path=str(item.get("path", "") or "rqgm_audit.jsonl"),
            pointer=str(item.get("pointer", "") or ""),
        ))
    return out


def _report_ref(bundle: ArtifactBundle, pointer: str) -> EvidenceRef:
    return EvidenceRef(
        path=bundle.node_report_path or "node_report.json", pointer=pointer
    )


def _pre_overclaim(bundle: ArtifactBundle) -> list[EvidenceRef]:
    refs = _gate_evidence(
        bundle, ("numeric_mismatch", "missing_evidence", "invariant_violation")
    )
    if not refs and novelty_signal(bundle.eval_summary + bundle.proposal_text):
        refs = [_report_ref(bundle, "/self_assessment")]
    refs.extend(_verification_evidence(
        bundle, ("fixed_verifier_claim_contradiction", "verifier_result_ignored")
    ))
    return refs


def _pre_metric_gaming(bundle: ArtifactBundle) -> list[EvidenceRef]:
    fixed = _verification_evidence(
        bundle, ("fixed_verifier_claim_contradiction", "verifier_result_ignored")
    )
    if fixed:
        return fixed
    if bundle.validate_metrics_flags:
        return [_report_ref(bundle, "/eval_result")]
    env = bundle.node_report.get("compute_env")
    if isinstance(env, dict) and env.get("env_signature_mismatch"):
        return [_report_ref(bundle, "/compute_env")]
    return []


def _pre_prior_art(bundle: ArtifactBundle) -> list[EvidenceRef]:
    # Degrades to "no prior-art attacks" without a refs source (§8: VirSci /
    # web independence).
    if bundle.related_refs and novelty_signal(
        bundle.eval_summary + bundle.proposal_text
    ):
        return [EvidenceRef(path="related_refs.json")]
    return []


def _pre_reproducibility(bundle: ArtifactBundle) -> list[EvidenceRef]:
    fixed = _verification_evidence(
        bundle, ("provider_schema_drift", "assurance_integrity_failure")
    )
    if fixed:
        return fixed
    commands = bundle.node_report.get("build_commands") or []
    commands = list(commands) + list(bundle.node_report.get("run_commands") or [])
    for cmd in commands:
        if _HOST_LOCAL_RE.search(str(cmd)):
            return [_report_ref(bundle, "/run_commands")]
    return []


def _pre_evidence_gap(bundle: ArtifactBundle) -> list[EvidenceRef]:
    return _gate_evidence(
        bundle, ("missing_evidence", "uncovered_numeric")
    ) + _verification_evidence(
        bundle,
        (
            "required_attestation_missing",
            "unbound_tool_invocation",
            "verifier_result_ignored",
        ),
    )


def _pre_cost_explosion(bundle: ArtifactBundle) -> list[EvidenceRef]:
    if (
        bundle.remaining_node_budget >= 0
        and bundle.plan_step_count > bundle.remaining_node_budget
    ):
        return [EvidenceRef(path="cost_trace.jsonl")]
    return []


def _pre_prompt_injection(bundle: ArtifactBundle) -> list[EvidenceRef]:
    # Scans EVERY node's proposal + node_report text — a firing pre-signal is
    # itself a trigger clause, so injection is caught on nodes the top-K and
    # 1-in-N sampling clauses would have skipped. Includes memory entries /
    # tool outputs quoted into them.
    text = bundle.proposal_text + "\n" + json.dumps(
        bundle.node_report, ensure_ascii=False, sort_keys=True
    )
    refs = [_report_ref(bundle, "/text")] if injection_pre_filter(text) else []
    refs.extend(_verification_evidence(
        bundle, ("knowledge_authority_instruction",)
    ))
    return refs


#: The audit artifact the self-preference pre-signal's POPULATION signal cites:
#: the per-epoch deterministic AI-vs-human margin statistic
#: (paper_self_preference.py writes it under ``{ckpt}/rqgm/``).
PAPER_SELF_PREFERENCE_STAT_REF = "rqgm/paper_self_preference_stat.json"

#: The corpus the PER-DRAFT anchor over-acceptance signal cites, pinpointed by
#: the over-accepted ``case_id`` in the ref's ``pointer``. Deliberately a
#: separate ref from :data:`PAPER_SELF_PREFERENCE_STAT_REF`: the two signals
#: have different subjects (one anchor case vs the authorship population), and
#: citing the statistic for a per-draft finding was what let a raw_attack carry
#: a `{"margin": 0.0}` artifact as the evidence for its own trigger. Mirrors
#: this module's existing literal-ref precedent (the constant name lives in
#: ``paper_anchor.PAPER_ANCHOR_CORPUS_FILENAME``; the path is
#: ``rqgm.paper.anchor.corpus_path``-resolved, checkpoint-relative by default).
PAPER_ANCHOR_CORPUS_REF = "paper_anchor_corpus.jsonl"


def _pre_paper_self_preference(bundle: ArtifactBundle) -> list[EvidenceRef]:
    """Deterministic, LLM-free over-acceptance pre-signal.

    Inert off the paper phase and for un-accepted drafts (fail-safe defaults):
    fires ONLY when the node is a paper candidate, the frozen incumbent
    ``paper_reviewer`` ACCEPTED the draft (``reviewer_accept_score >=
    accept_threshold``), AND at least one of the THREE over-acceptance signals
    below is present. With no signal the type produces zero attacks
    and costs zero LLM calls (mirrors the web-less PriorArtAdversary
    degradation).

    Each signal cites the evidence for ITS OWN subject: the population statistic
    is cited only when the population statistic fires, and a per-draft finding
    cites the anchor CASE it was measured on. That separation is the point — a
    per-draft signal citing `paper_self_preference_stat.json` handed Defender and
    Judge an artifact reading `{"margin": 0.0}` as the evidence for its own
    trigger.

    ``getattr`` with fail-safe defaults so a duck-typed bundle without the
    paper fields (an exploration or mocked bundle) reads as "off the paper
    phase" and returns ``[]`` — never an AttributeError."""
    accept_score = getattr(bundle, "reviewer_accept_score", None)
    if not getattr(bundle, "paper_candidate", False) or accept_score is None:
        return []
    if float(accept_score) < float(getattr(bundle, "accept_threshold", 0.6)):
        return []
    # Over-acceptance signal 1: the fixed claim gate already flagged the draft.
    refs = _gate_evidence(
        bundle,
        ("numeric_mismatch", "missing_evidence",
         "uncovered_numeric", "invariant_violation"),
    )
    # Over-acceptance signal 2: authorship-corpus self-preference margin — the
    # POPULATION statistic, cited to the artifact that records it. `0.0` (an
    # all-human corpus / no authorship split) is below every sane threshold, so
    # this signal is correctly silent where there is no population evidence.
    if float(getattr(bundle, "self_preference_margin", 0.0)) >= float(
        getattr(bundle, "self_preference_threshold", 0.1)
    ):
        refs.append(EvidenceRef(path=PAPER_SELF_PREFERENCE_STAT_REF))
    # Over-acceptance signal 3 (amended 2026-07-17): the DIRECT per-draft
    # anchor over-acceptance — the incumbent
    # accepted this specific anchor case whose human ground truth is `reject`.
    # Real and deterministic per draft, and unlike signal 2 it does not need an
    # authorship split, so an all-human corpus still prosecutes over-acceptance
    # on the evidence that actually exists: the case itself.
    case_id = str(getattr(bundle, "anchor_over_accepted_case", "") or "")
    if case_id:
        refs.append(
            EvidenceRef(path=PAPER_ANCHOR_CORPUS_REF, pointer=case_id)
        )
    return refs


@dataclass(frozen=True)
class AdversarySpec:
    """One adversary type: target class, prompt, deterministic pre-signal."""

    adversary_type: str
    prompt_key: str
    default_target_type: str
    pre_signal: object  # (bundle) -> list[EvidenceRef]


ADVERSARY_SPECS: dict[str, AdversarySpec] = {
    "overclaim": AdversarySpec(
        "overclaim", "rqgm/adversary_overclaim", "paper_claim", _pre_overclaim
    ),
    "metric_gaming": AdversarySpec(
        "metric_gaming", "rqgm/adversary_metric_gaming", "metric_result",
        _pre_metric_gaming,
    ),
    "prior_art": AdversarySpec(
        "prior_art", "rqgm/adversary_prior_art", "novelty_claim",
        _pre_prior_art,
    ),
    "reproducibility": AdversarySpec(
        "reproducibility", "rqgm/adversary_reproducibility",
        "reproducibility_claim", _pre_reproducibility,
    ),
    "evidence_gap": AdversarySpec(
        "evidence_gap", "rqgm/adversary_evidence_gap", "paper_claim",
        _pre_evidence_gap,
    ),
    "cost_explosion": AdversarySpec(
        "cost_explosion", "rqgm/adversary_cost_explosion", "experiment_plan",
        _pre_cost_explosion,
    ),
    "prompt_injection": AdversarySpec(
        "prompt_injection", "rqgm/adversary_prompt_injection", "proposal",
        _pre_prompt_injection,
    ),
    # The eighth (paper-phase) adversary — docs/reference/rqgm_schemas.md
    # "Paper-archive schemas" ("The eighth adversary type"). Reuses the
    # existing closed ``paper_claim`` target class (the ``raw_attack`` row of
    # "Adversarial-loop schemas": a ``target_artifact.type`` is never a
    # component): the attacked artifact is the over-accepted draft's
    # manuscript; the implicated ROLE (paper_reviewer) is carried by the
    # round's ``_AFFECTED_ROLES_BY_TYPE`` row, never by a component-shaped
    # target here.
    "paper_self_preference": AdversarySpec(
        "paper_self_preference", "rqgm/adversary_paper_self_preference",
        "paper_claim", _pre_paper_self_preference,
    ),
}


# ── shared prompted-actor plumbing ──────────────────────────────────────────


#: ``{role}_v{N}`` / ``{family}_v{N}`` trailing version suffix.
_VERSION_SUFFIX_RE = re.compile(r"_v\d+$")


class _PromptedActor:
    """Load-format-complete plumbing shared by the three actors.

    ``llm`` is the injectable seam (deterministic fakes in tests); calls are
    tagged ``phase="governance", skill="rqgm_adversarial"`` for Task 12 cost
    metering, with the duck-typed TypeError fallback for metadata-less stubs.
    *active_components* is an optional zero-arg callable yielding the frozen
    epoch's ``role -> component_id`` map (Task 02 EpochState) so record
    ``component_id`` fields resolve to the REGISTERED governed component
    when one exists — the ad-hoc v1 ids stay as the fallback.
    """

    def __init__(self, llm=None, loader=None, checkpoint_dir=None, *,
                 active_components=None) -> None:
        self.llm = llm
        self._loader = loader
        self.checkpoint_dir = checkpoint_dir
        self._active_components = active_components

    def _component_id(self, role: str, default_id: str) -> str:
        """Registry-resolved component id for *role*, family-guarded.

        Returns the frozen active component for *role* only when it belongs
        to the same versioned family as *default_id* (``defender_v1`` →
        family ``defender``), so an unrelated same-role rollup winner (e.g.
        the lineage judge for the artifact judge) can never claim another
        actor's records. Absent/failed lookups keep the deterministic
        fallback id (never raises)."""
        getter = self._active_components
        if getter is None:
            return default_id
        try:
            active = getter() or {}
            candidate = str(active.get(str(role), "") or "")
        except Exception:
            log.warning("active-component lookup failed", exc_info=True)
            return default_id
        if not candidate:
            return default_id
        family = _VERSION_SUFFIX_RE.sub("", default_id)
        if _VERSION_SUFFIX_RE.sub("", candidate) == family:
            return candidate
        return default_id

    def _load_prompt(self, key: str) -> tuple[str, str]:
        loader = self._loader
        if loader is None:
            from ari.prompts import FilesystemPromptLoader

            loader = FilesystemPromptLoader()
        return loader.load_versioned(key)

    def _complete(self, prompt: str) -> str:
        messages = [{"role": "user", "content": prompt}]
        try:
            resp = self.llm.complete(
                messages,
                require_tool=False,
                phase="governance",
                skill="rqgm_adversarial",
            )
        except TypeError:
            resp = self.llm.complete(messages, require_tool=False)
        return getattr(resp, "content", "") or ""

    def _call(self, key: str, format_kwargs: dict) -> tuple[dict, str | None]:
        """Return ``(payload, prompt_hash)``; never raises."""
        try:
            template, prompt_hash = self._load_prompt(key)
            prompt = template.format(**format_kwargs)
        except Exception:
            log.warning("adversarial prompt load failed for %s", key,
                        exc_info=True)
            return {}, None
        try:
            from ari.prompts import record_prompt_use

            record_prompt_use(
                key,
                prompt_hash,
                rendered_text=prompt,
                phase="governance",
                checkpoint_dir=self.checkpoint_dir,
            )
        except Exception:
            pass
        if self.llm is None:
            return {}, prompt_hash
        try:
            raw = self._complete(prompt)
        except Exception:
            log.warning("adversarial LLM call failed for %s", key,
                        exc_info=True)
            return {}, prompt_hash
        return _extract_json(raw), prompt_hash


# ── AdversaryEngine ─────────────────────────────────────────────────────────


class AdversaryEngine(_PromptedActor):
    """Dispatcher over the adversary types in :data:`ADVERSARY_SPECS`.

    Deterministic pre-signals run first; the LLM adversary call happens only
    for triggered types, under ``max_attacks_per_node`` and the per-epoch
    call budget. Records that fail :func:`raw_attack_violations` are dropped
    before they can reach the Defender (evidence-free attacks are
    schema-invalid).
    """

    def __init__(
        self,
        llm=None,
        loader=None,
        cfg=None,
        epoch_state=None,
        checkpoint_dir=None,
        *,
        next_attack_id=None,
        calls_by_epoch=None,
        active_components=None,
    ) -> None:
        super().__init__(llm, loader, checkpoint_dir,
                         active_components=active_components)
        self.cfg = cfg
        self.epoch_state = epoch_state
        self._next_attack_id = next_attack_id or _seq_alloc("atk")
        # Per-epoch LLM call budget (`max_adversary_calls_per_epoch`): keyed
        # by epoch_id so the count
        # resets at every epoch boundary instead of accumulating over the
        # process lifetime. *calls_by_epoch* seeds the spent budget on resume
        # (derived from the JSONL raw-attack lines keyed by epoch_id), so a
        # mid-epoch restart cannot exceed the cap.
        self._calls_by_epoch: dict[str, int] = {
            str(k): int(v) for k, v in dict(calls_by_epoch or {}).items()
        }

    @property
    def calls_this_epoch(self) -> int:
        """Adversary LLM calls spent in the CURRENT epoch (per-epoch cap)."""
        return self._calls_by_epoch.get(_epoch_id(self.epoch_state), 0)

    def attack(self, bundle: ArtifactBundle) -> list[RawAttackRecord]:
        """0..max_attacks_per_node raw attacks for *bundle*; never raises."""
        max_attacks = _cfg(self.cfg, "max_attacks_per_node", 3)
        max_calls = _cfg(self.cfg, "max_adversary_calls_per_epoch", 24)
        types = [
            t for t in _cfg(self.cfg, "types", list(ADVERSARY_TYPES))
            if t in ADVERSARY_SPECS
        ]
        epoch_id = _epoch_id(self.epoch_state)
        calls = self._calls_by_epoch.get(epoch_id, 0)
        out: list[RawAttackRecord] = []
        for adversary_type in types:
            if len(out) >= max_attacks:
                break
            if calls >= max_calls:
                break
            spec = ADVERSARY_SPECS[adversary_type]
            try:
                evidence = spec.pre_signal(bundle)
            except Exception:
                log.warning("pre-signal failed for %s", adversary_type,
                            exc_info=True)
                continue
            if not evidence:
                continue  # event-driven: no pre-signal, no LLM cost
            if self.llm is None:
                continue  # no adversary LLM → no attacks this node
            calls += 1
            self._calls_by_epoch[epoch_id] = calls
            payload, prompt_hash = self._call(
                spec.prompt_key,
                {
                    "target_block": _target_block(bundle),
                    "evidence_block": _evidence_block(evidence),
                },
            )
            record = self._record_from_payload(
                payload, spec, bundle, evidence, prompt_hash, epoch_id
            )
            if record is None:
                continue
            findings = raw_attack_violations(record)
            if findings:
                log.warning(
                    "dropping schema-invalid %s attack: %s",
                    adversary_type, findings,
                )
                continue
            out.append(record)
        return out

    def _record_from_payload(
        self, payload, spec, bundle, evidence, prompt_hash, epoch_id
    ) -> RawAttackRecord | None:
        if not payload:
            return None
        claim = str(payload.get("attack_claim", "") or "")
        if not claim:
            return None
        target = payload.get("target_artifact")
        target = target if isinstance(target, dict) else {}
        target_type = str(target.get("type", "") or spec.default_target_type)
        severity = str(payload.get("severity_claimed", "") or "medium")
        if severity not in SEVERITIES:
            severity = "medium"
        refs = list(evidence)
        for r in payload.get("attack_evidence_refs") or []:
            if isinstance(r, dict) and str(r.get("path", "")):
                refs.append(
                    EvidenceRef(
                        path=str(r.get("path", "")),
                        pointer=str(r.get("pointer", "") or ""),
                        artifact_hash=str(r.get("artifact_hash", "") or ""),
                    )
                )
        try:
            confidence = float(payload.get("confidence", 0.0) or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        return RawAttackRecord(
            record_id=self._next_attack_id(),
            adversary_type=spec.adversary_type,
            target_artifact=TargetArtifact(
                type=target_type,
                node_id=bundle.node_id,
                ref=str(target.get("ref", "") or ""),
                artifact_hash=str(target.get("artifact_hash", "") or ""),
            ),
            attack_claim=claim,
            attack_evidence_refs=tuple(refs),
            severity_claimed=severity,
            confidence=confidence,
            epoch_id=epoch_id,
            # Registry-resolved when the founding (or an evolved) component
            # of this adversary family is the frozen active one; the
            # deterministic per-type id remains the fallback.
            component_id=self._component_id(
                "adversary", f"adversary_{spec.adversary_type}_v1"
            ),
            prompt_hash=prompt_hash,
            created_at=created_at_now(),
            source_refs=(bundle.node_id,) if bundle.node_id else (),
            status="raw",
        )


# ── Defender ────────────────────────────────────────────────────────────────


class Defender(_PromptedActor):
    """One DefenderResponse per attack. A failed/absent defense is a
    MISSING response — the Judge then adjudicates with
    ``defense_status: absent_infrastructure`` (never auto-valid)."""

    def __init__(
        self, llm=None, loader=None, checkpoint_dir=None, *,
        next_defense_id=None, active_components=None,
    ) -> None:
        super().__init__(llm, loader, checkpoint_dir,
                         active_components=active_components)
        self._next_defense_id = next_defense_id or _seq_alloc("def")

    def respond(self, attacks, bundle: ArtifactBundle) -> list[DefenderResponse]:
        out: list[DefenderResponse] = []
        for attack in attacks or ():
            if self.llm is None:
                continue
            payload, prompt_hash = self._call(
                DEFENDER_PROMPT_KEY,
                {
                    "attack_block": canonical_json(attack.to_dict()),
                    "artifact_block": _target_block(bundle),
                },
            )
            if not payload:
                continue
            stance = str(payload.get("stance", "") or "")
            if stance not in DEFENSE_STANCES:
                continue
            try:
                confidence = float(payload.get("confidence", 0.0) or 0.0)
            except (TypeError, ValueError):
                confidence = 0.0
            out.append(
                DefenderResponse(
                    record_id=self._next_defense_id(),
                    raw_attack_id=attack.record_id,
                    stance=stance,
                    rebuttal_text=str(payload.get("rebuttal_text", "") or ""),
                    proposed_fix=payload.get("proposed_fix"),
                    confidence=confidence,
                    epoch_id=attack.epoch_id,
                    component_id=self._component_id("defender", "defender_v1"),
                    prompt_hash=prompt_hash,
                    created_at=created_at_now(),
                    source_refs=(attack.record_id,),
                )
            )
        return out


# ── ArtifactJudge ───────────────────────────────────────────────────────────


class ArtifactJudge(_PromptedActor):
    """Adjudicates (attack, defense) pairs.

    Total deterministic fallback: on ANY failure the verdict is ``invalid``
    (fail-open — no ValidatedAttackRecord, no penalty; safe because of
    invariant 8). Never raises. Distinct from Task 05's GovernanceJudge:
    this judge rules only on artifact-level disputes.
    """

    def __init__(
        self, llm=None, loader=None, checkpoint_dir=None, *,
        next_judgment_id=None, active_components=None,
    ) -> None:
        super().__init__(llm, loader, checkpoint_dir,
                         active_components=active_components)
        self._next_judgment_id = next_judgment_id or _seq_alloc("jdg")

    def adjudicate(
        self, attacks, defenses, bundle: ArtifactBundle
    ) -> list[JudgmentRecord]:
        by_attack = {d.raw_attack_id: d for d in defenses or ()}
        out: list[JudgmentRecord] = []
        for attack in attacks or ():
            defense = by_attack.get(attack.record_id)
            defense_status = (
                "present" if defense is not None else "absent_infrastructure"
            )
            verdict, severity, rationale, prompt_hash = self._judge_one(
                attack, defense, defense_status
            )
            out.append(
                JudgmentRecord(
                    record_id=self._next_judgment_id(),
                    raw_attack_id=attack.record_id,
                    defense_id=defense.record_id if defense is not None else "",
                    verdict=verdict,
                    severity=severity,
                    rationale=rationale,
                    evidence_refs=attack.attack_evidence_refs,
                    defense_status=defense_status,
                    epoch_id=attack.epoch_id,
                    component_id=self._component_id(
                        "judge", "artifact_judge_v1"
                    ),
                    prompt_hash=prompt_hash,
                    created_at=created_at_now(),
                    source_refs=tuple(
                        r
                        for r in (
                            attack.record_id,
                            defense.record_id if defense is not None else "",
                        )
                        if r
                    ),
                )
            )
        return out

    def _judge_one(self, attack, defense, defense_status):
        """(verdict, severity, rationale, prompt_hash); total fallback."""
        fallback = (
            "invalid",
            "low",
            "judge unavailable; fail-open (unadjudicated attacks have no "
            "effect — invariant 8)",
        )
        try:
            if self.llm is None:
                return (*fallback, None)
            payload, prompt_hash = self._call(
                JUDGE_PROMPT_KEY,
                {
                    "attack_block": canonical_json(attack.to_dict()),
                    "defense_block": (
                        canonical_json(defense.to_dict())
                        if defense is not None
                        else json.dumps({"defense_status": defense_status})
                    ),
                    "evidence_block": _evidence_block(
                        attack.attack_evidence_refs
                    ),
                },
            )
            if not payload:
                return (*fallback, prompt_hash)
            verdict = str(payload.get("verdict", "") or "")
            if verdict not in VERDICTS:
                return (*fallback, prompt_hash)
            severity = str(payload.get("severity", "") or "")
            if severity not in SEVERITIES:
                severity = attack.severity_claimed
            rationale = str(payload.get("rationale", "") or "")
            return verdict, severity, rationale, prompt_hash
        except Exception:
            log.warning("artifact judge failed (fail-open)", exc_info=True)
            return (*fallback, None)


# ── UtilityPenaltyPolicy + apply_utility_penalty (the penalty channel) ──────


class UtilityPenaltyPolicy:
    """Epoch-frozen penalty arithmetic — pure, deterministic (P2).

    ``severity_weights``, ``penalty_cap``, and ``verdict_factors`` cannot
    change mid-epoch (global invariant 1); the arithmetic after adjudication
    is a pure function of the JudgmentRecords.
    """

    def __init__(
        self,
        *,
        penalty_cap: float = 0.5,
        severity_weights: dict | None = None,
        verdict_factors: dict | None = None,
    ) -> None:
        self.penalty_cap = float(penalty_cap)
        self.severity_weights = dict(
            severity_weights
            or {"low": 0.05, "medium": 0.15, "high": 0.3, "critical": 0.5}
        )
        self.verdict_factors = dict(verdict_factors or VERDICT_FACTOR)

    @classmethod
    def from_config(cls, adversarial_cfg) -> "UtilityPenaltyPolicy":
        penalty = adversarial_cfg
        if penalty is not None:
            penalty = (
                penalty.get("penalty")
                if isinstance(penalty, dict)
                else getattr(penalty, "penalty", None)
            )
        return cls(
            penalty_cap=_cfg(penalty, "cap", 0.5),
            severity_weights=_cfg(
                penalty,
                "severity_weights",
                {"low": 0.05, "medium": 0.15, "high": 0.3, "critical": 0.5},
            ),
        )

    def payload(self) -> dict:
        """The by-value frozen weights embedded in every UtilityRecord."""
        return {
            "penalty_cap": self.penalty_cap,
            "severity_weights": {
                str(k): float(v)
                for k, v in sorted(self.severity_weights.items())
            },
            "verdict_factors": {
                str(k): float(v)
                for k, v in sorted(self.verdict_factors.items())
            },
        }

    @property
    def policy_hash(self) -> str:
        return hash12(canonical_json(self.payload()))

    def compute(self, validated) -> float:
        """min(cap, Σ weight(severity) × factor(verdict)) — pure arithmetic."""
        if not validated:
            return 0.0
        total = 0.0
        for v in validated:
            severity = str(getattr(v, "severity", "") or "")
            verdict = str(getattr(v, "verdict", "") or "")
            total += float(
                self.severity_weights.get(severity, 0.0)
            ) * float(self.verdict_factors.get(verdict, 0.0))
        return round(min(self.penalty_cap, total), 6)


def apply_utility_penalty(
    node,
    validated,
    policy: UtilityPenaltyPolicy,
    *,
    epoch_id: str = "",
    next_utility_seq: int = 0,
    epoch_utility_policy: dict | None = None,
) -> UtilityRecord | None:
    """The utility-penalty channel — sterile-gate precedent, invariant 8/16.

    Consumes ONLY ValidatedAttackRecords. Never resurrects a sterile node,
    never touches an unscored node, never raises a score; the pre-penalty
    value and the penalty ride additive reserved keys. Returns the
    UtilityRecord to append (caller logs it), or ``None`` when nothing
    changed.

    *epoch_utility_policy* (additive; ``None`` ⇒ this
    function's exact pre-Task-14 record) is the EPOCH's frozen utility policy
    (``ari.rqgm.state.capture_utility_policy``). Two DIFFERENT policies were
    both called ``utility_policy_hash``:

    * the **penalty** policy — ``{penalty_cap, severity_weights,
      verdict_factors}``, computed right here;
    * the **epoch** policy — ``{composite, axis_weights, frontier_score,
      depth_penalty_lambda, ucb_c}``, frozen at the boundary and carried in
      ``EpochState.utility_policy`` and the epoch fingerprint.

    Their key sets are disjoint, so their hashes were never equal — and the
    record wrote the PENALTY hash into ``prompt_hash``, which is the key
    ``frontier_repair`` joins retirements on. Retiring the ``utility_policy``
    registry entry therefore matched NO record: the cause fired into a join
    that could not match. When given, this argument re-points
    ``utility_policy_hash`` / ``prompt_hash`` at the EPOCH policy (the
    registered ``prompt_hash`` of the active ``utility_policy`` entry) and
    carries the epoch policy by value under ``frozen_policy["utility_policy"]``.

    The forcing function is the kernel, not aesthetics: once
    ``utility_policy`` is an active registry entry,
    ``epoch.active_prompt_hashes["utility_policy"]`` IS the epoch policy hash,
    and ``validate_epoch_invariance`` raises CK-EPO-001 on every UtilityRecord
    whose ``prompt_hash`` falls outside that frozen set.
    """
    if not validated:
        return None
    metrics = getattr(node, "metrics", None)
    if not isinstance(metrics, dict):
        return None
    base = metrics.get("_scientific_score")
    if base is None or metrics.get("_sterile") is True:
        return None
    penalty = policy.compute(validated)
    if penalty <= 0.0:
        return None
    base = float(base)
    metrics["_pre_penalty_score"] = base
    metrics["_validated_attack_penalty"] = penalty
    metrics["_scientific_score"] = max(0.0, base - penalty)
    payload = policy.payload()
    policy_hash = policy.policy_hash
    if epoch_utility_policy:
        # Additive only. The three schema-required keys are untouched
        # (MetricRecomputer reads only those and copies the record forward,
        # so the additive sub-object is invisible to it); the by-value
        # promise — "Task 10's recompute under the original epoch's weights
        # never needs a registry lookup" — now covers BOTH policies.
        epoch_policy = dict(epoch_utility_policy)
        epoch_hash = str(epoch_policy.get("utility_policy_hash", "") or "")
        payload["utility_policy"] = epoch_policy
        if epoch_hash:
            policy_hash = epoch_hash
    return make_utility_record(
        record_id=format_utility_id(next_utility_seq),
        node_id=str(getattr(node, "id", "") or ""),
        base_score=base,
        penalty=penalty,
        validated=list(validated),
        policy_payload=payload,
        policy_hash=policy_hash,
        epoch_id=epoch_id,
    )


# ── small shared helpers ────────────────────────────────────────────────────


def _seq_alloc(prefix: str, base: int = 0):
    counter = {"n": int(base) - 1}

    def alloc() -> str:
        counter["n"] += 1
        return f"{prefix}_{counter['n']:06d}"

    return alloc


def _epoch_id(epoch_state) -> str:
    if epoch_state is None:
        return ""
    state = epoch_state() if callable(epoch_state) else epoch_state
    if state is None:
        return ""
    if isinstance(state, dict):
        return str(state.get("epoch_id", ""))
    return str(getattr(state, "epoch_id", "") or "")


def _target_block(bundle: ArtifactBundle) -> str:
    """The adversary-visible artifact slice — the context-visibility
    boundary: claims, metrics and the fixed K/C/A premises, never the full
    VirSci transcript."""
    return canonical_json(
        {
            "node_id": bundle.node_id,
            "proposal_text": bundle.proposal_text[:4000],
            "eval_summary": bundle.eval_summary[:2000],
            "node_report": bundle.node_report,
            "score": bundle.score,
            "knowledge_skill_use_records": bundle.knowledge_skill_use_records,
            "capability_binding_records": bundle.capability_binding_records,
            "harness_attestations": bundle.harness_attestations,
            "verification_findings": bundle.verification_findings,
            "active_harness_lock_digest": bundle.active_harness_lock_digest,
            "verification_contract_digest": bundle.verification_contract_digest,
        }
    )


def _evidence_block(evidence) -> str:
    return canonical_json([r.to_dict() for r in evidence or ()])
