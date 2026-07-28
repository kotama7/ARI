"""Role-specific context views — deterministic, capped projections (Task 12).

Each governance actor receives a **view**, never the archive (plan
``docs/plans/ari_rqgm/12`` §5.7 visibility matrix). Pure functions in the
``bfts_prompt_builder`` style: LLM-free, byte-deterministic for identical
inputs, unit-testable, no I/O.

The BFTS row is the load-bearing one: **BFTS sees ProposalSummaryView
only, never full transcripts**. Enforcement is layered (§5.7):

1. construction-time — :func:`build_bfts_summary_context` accepts a
   :class:`~ari.rqgm.proposals.records.ProposalSummaryView` dataclass, not
   a ProposalRecord, so full-record leakage is a ``TypeError``;
2. check-time — ``ConstitutionalKernel.validate_context_scope`` compares
   view keys against :data:`PROPOSAL_SUMMARY_FIELDS` (the SAME frozen
   constant, aliased from the constitution-pinned
   ``kernel_rules.CONTEXT_VIEW_WHITELISTS`` — one source, no drift, §6.5);
3. test-time — the leak-regression test asserts no archive-only field name
   (:data:`ARCHIVE_ONLY_FIELDS`) ever appears in the rendered expand
   context.

The other builders project only what the §5.7 matrix grants: the Judge
never sees frontier scores (:data:`JUDGE_EXCLUDED_KEYS` — it cannot be
biased by utility), governance never sees retired prompt text
(:data:`GOVERNANCE_EXCLUDED_KEYS`, the Task 08 rule), and same-role
outputs are simply never passed in (reviewer isolation is constructive).
"""

from __future__ import annotations

import logging

from ari.rqgm.kernel_rules import CONTEXT_VIEW_WHITELISTS
from ari.rqgm.proposals.records import (
    RENDERED_CTX_BUDGET,
    ProposalSummaryView,
    render_summary_ctx,
)

#: The BFTS whitelist — ALIASED from the constitution-pinned kernel table
#: (plan 12 §6.5: kernel check and leak test share one source). BFTS rides
#: the ``generator`` role in the Task 02 vocabulary.
BFTS_VIEW_ROLE = "generator"
PROPOSAL_SUMMARY_FIELDS: frozenset[str] = CONTEXT_VIEW_WHITELISTS[BFTS_VIEW_ROLE]

#: The paper-writer whitelist — ALIASED from the same constitution-pinned
#: table (plan 12 §5.4/§5.7 row "Paper writer"): verified context +
#: ``science_data`` + claim registry, and nothing else.
PAPER_WRITER_VIEW_ROLE = "paper_writer"
PAPER_WRITER_FIELDS: frozenset[str] = CONTEXT_VIEW_WHITELISTS[
    PAPER_WRITER_VIEW_ROLE
]

#: The paper-reviewer whitelist — ALIASED from the same constitution-pinned
#: table (plan ari_rqgm_paper/03 §5.3): the draft under review + the same
#: Layer-0 verified evidence the writer saw + the metrics backing the claims
#: + the anchor/reference-case projection (whose content is plan
#: ari_rqgm_paper/04's). One source, no drift.
PAPER_REVIEWER_VIEW_ROLE = "paper_reviewer"
PAPER_REVIEWER_FIELDS: frozenset[str] = CONTEXT_VIEW_WHITELISTS[
    PAPER_REVIEWER_VIEW_ROLE
]

#: Archive-only field names that must NEVER reach a rendered BFTS context
#: (§5.7 layer 3 — the leak-regression vocabulary).
ARCHIVE_ONLY_FIELDS: frozenset[str] = frozenset({
    "transcript",
    "discussion_log",
    "raw_proposals",
    "raw_output",
    "agent_messages",
    "attack_texts",
    "defense_texts",
    "evidence_bundles",
})

#: Utility/frontier signals the Judge view must exclude (§5.7: the Judge
#: cannot be biased by utility).
JUDGE_EXCLUDED_KEYS: frozenset[str] = frozenset({
    "frontier_scores",
    "frontier_rank",
    "scientific_score",
    "_scientific_score",
    "utility",
    "utility_score",
})

#: Retired-prompt-text keys the governance (audit) view must exclude
#: (Task 08 rule: governance sees prompt hashes, never retired bodies).
GOVERNANCE_EXCLUDED_KEYS: frozenset[str] = frozenset({
    "prompt_text",
    "prompt_body",
    "template",
    "template_text",
    "body",
})

#: Per-node epoch-charter injection cap (§5.7: ≤ 1200 chars, in line with
#: ``_IDEA_FIELD_CAP``) — the fixed budget for the Task 05 charter block
#: riding ``build_working_context_messages``.
CHARTER_BLOCK_CAP = 1200

#: Per-string truncation inside dict views (tool-result precedent: 4000).
_FIELD_CAP = 4000


def _plain(obj) -> dict:
    """Duck-typed record → plain dict (``to_dict`` / dict / empty)."""
    if isinstance(obj, dict):
        return dict(obj)
    to_dict = getattr(obj, "to_dict", None)
    if callable(to_dict):
        try:
            d = to_dict()
            return dict(d) if isinstance(d, dict) else {}
        except Exception:
            return {}
    return {}


def _scrub(value, excluded: frozenset):
    """Recursively drop *excluded* keys and truncate long strings —
    deterministic (key order preserved, pure)."""
    if isinstance(value, dict):
        return {
            k: _scrub(v, excluded)
            for k, v in value.items()
            if k not in excluded
        }
    if isinstance(value, (list, tuple)):
        return [_scrub(v, excluded) for v in value]
    if isinstance(value, str):
        return value[:_FIELD_CAP]
    return value


# ── the visibility-matrix builders (plan 12 §5.7/§7) ────────────────────────


log = logging.getLogger(__name__)


def _enforce_scope(role: str, view: dict) -> dict:
    """Run the kernel's CK-CTX-001 scope check over a freshly built view.

    ``validate_context_scope`` is the CHECK-TIME half of the two-part scope
    design (construction-time = these builders, check-time = the kernel), and
    it had NO production caller: the whitelists were declared and never
    enforced, so a builder that grew a foreign field would ship silently.
    Running it inside the builder makes every current AND future call site
    checked without each having to remember. Warn-only by design (§5.1: this
    never blocks node execution) — the violation is logged, never raised.
    """
    try:
        from ari.rqgm.kernel import ConstitutionalKernel

        report = ConstitutionalKernel().validate_context_scope(role, view)
        for v in getattr(report, "violations", ()) or ():
            log.warning("context scope violation %s for role %r: %s",
                        getattr(v, "code", "?"), role,
                        getattr(v, "detail", "") or getattr(v, "message", ""))
    except Exception:
        log.debug("context scope check unavailable", exc_info=True)
    return view


def build_bfts_summary_context(
    view: ProposalSummaryView, *, cap: int = RENDERED_CTX_BUDGET
) -> str:
    """BFTS row: render the expand context from a ProposalSummaryView ONLY.

    Layer-1 enforcement: a ProposalRecord (or anything else) is a
    ``TypeError`` — the only proposal content that can reach
    ``bfts.expand`` through this function is the bounded summary.
    """
    if not isinstance(view, ProposalSummaryView):
        raise TypeError(
            "build_bfts_summary_context accepts a ProposalSummaryView only "
            f"(got {type(view).__name__}); BFTS never sees full proposal "
            "records (plan 12 §5.7)"
        )
    _enforce_scope("generator", _plain(view))
    return render_summary_ctx(view, budget=int(cap))


def build_reviewer_context(record, evidence_refs) -> dict:
    """Reviewer row: proposal core + evidence-plan refs. Other reviewers'
    outputs and raw attacks are never passed in (same-role isolation is
    constructive — this builder has no parameter for them)."""
    summary = getattr(record, "summary", None)
    return {
        "role": "reviewer",
        "proposal": _scrub(_plain(summary if summary is not None else record),
                           frozenset()),
        "evidence_refs": [
            str(r)[:_FIELD_CAP] for r in list(evidence_refs or ())[:20]
        ],
    }


def build_adversary_context(view, metrics, claims) -> dict:
    """Adversary row: claims + novelty risks + metric details. Defender
    strategy and registry state have no parameter here."""
    return {
        "role": "adversary",
        "summary": _scrub(_plain(view), frozenset()),
        "metrics": _scrub(dict(metrics or {}), frozenset()),
        "claim_refs": [
            str(c)[:_FIELD_CAP] for c in list(claims or ())[:20]
        ],
    }


def build_judge_context(attack, defense, bundle) -> dict:
    """Judge row: raw attack + defense + evidence bundle, with every
    frontier/utility signal scrubbed (the Judge cannot be biased by
    utility; registry write access is structural — the Judge never holds a
    registry handle)."""
    return {
        "role": "judge",
        "attack": _scrub(_plain(attack), JUDGE_EXCLUDED_KEYS),
        "defense": _scrub(_plain(defense), JUDGE_EXCLUDED_KEYS),
        "evidence_bundle": _scrub(_plain(bundle), JUDGE_EXCLUDED_KEYS),
    }


def build_governance_context(prompt_hashes, bundles, replay_results) -> dict:
    """Governance (audit_epoch) row: prompt hashes + evidence bundles +
    replay results; retired prompt TEXT is scrubbed (Task 08 rule)."""
    return {
        "role": "governance",
        "prompt_hashes": _scrub(dict(prompt_hashes or {}),
                                GOVERNANCE_EXCLUDED_KEYS),
        "evidence_bundles": [
            _scrub(_plain(b), GOVERNANCE_EXCLUDED_KEYS)
            for b in list(bundles or ())
        ],
        "replay_results": [
            _scrub(_plain(r), GOVERNANCE_EXCLUDED_KEYS)
            for r in list(replay_results or ())
        ],
    }


def build_paper_writer_context(
    verified_context, science_data, claim_registry
) -> dict:
    """Paper-writer row (plan 12 §5.4/§5.7): a deterministic projection
    exposing EXACTLY verified context + ``science_data`` + the claim
    registry. Raw transcripts and governance internals have no parameter
    here (the exclusion is constructive, like the reviewer's same-role
    isolation).

    The returned key set is exactly :data:`PAPER_WRITER_FIELDS`, so
    ``ConstitutionalKernel.validate_context_scope("paper_writer", view)``
    passes on this projection and flags any foreign field a caller adds
    (the whitelist constant is shared, kernel-enforced, and
    constitution-pinned — no drift)."""
    return _enforce_scope("paper_writer", {
        "verified_context": _scrub(_plain(verified_context), frozenset()),
        "science_data": _scrub(_plain(science_data), frozenset()),
        "claim_registry": _scrub(_plain(claim_registry), frozenset()),
    })


def build_paper_reviewer_context(
    draft_manuscript, verified_context, science_data, reference_context
) -> dict:
    """Paper-reviewer row (plan ari_rqgm_paper/03 §5.3): a deterministic
    projection exposing EXACTLY the four whitelisted fields — the archive
    draft under review, the same Layer-0 verified evidence the writer saw,
    the metrics backing the claims, and the anchor/reference-case projection
    (whose content is plan ari_rqgm_paper/04's).

    Other drafts' reviews, the writer transcript, and every frontier/utility
    signal have NO parameter here — same-role isolation is constructive, like
    :func:`build_reviewer_context`. The returned key set is exactly
    :data:`PAPER_REVIEWER_FIELDS`, so
    ``ConstitutionalKernel.validate_context_scope("paper_reviewer", view)``
    passes on this projection and flags any foreign field a caller adds (the
    whitelist constant is shared, kernel-enforced, and constitution-pinned)."""
    return _enforce_scope("paper_reviewer", {
        "draft_manuscript": _scrub(_plain(draft_manuscript), frozenset()),
        "verified_context": _scrub(_plain(verified_context), frozenset()),
        "science_data": _scrub(_plain(science_data), frozenset()),
        "reference_context": _scrub(_plain(reference_context), frozenset()),
    })


def bfts_view_violations(view) -> list[str]:
    """Key-set check against :data:`PROPOSAL_SUMMARY_FIELDS` — the same
    predicate ``ConstitutionalKernel.validate_context_scope`` applies
    (shared constant; convenience surface for tests and callers)."""
    return [
        f"field {name!r} is outside the BFTS ProposalSummaryView whitelist"
        for name in sorted(set(_plain(view)) - PROPOSAL_SUMMARY_FIELDS)
    ]
