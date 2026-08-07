"""RQGM Task 12 — role-specific context views
(docs/reference/rqgm_schemas.md §``proposal_summary_view.schema.json`` — the
only proposal representation BFTS may consume; §Constitutional violation
codes, CK-CTX-001 "a rendered role view exceeds its field whitelist").

Covers the three-layer ProposalSummaryView-only enforcement for BFTS
(typed renderer input → ``TypeError``; kernel ``validate_context_scope``
sharing the SAME whitelist constant; the leak-regression test asserting no
archive-only field name ever appears in a rendered expand context for a
fixture ProposalRecord carrying all of them), plus the §5.7 visibility
matrix exclusions: the Judge never sees frontier scores, governance never
sees retired prompt text, and same-role isolation is constructive.

All builders are pure and deterministic — no LLM, no I/O (P2).
"""

from __future__ import annotations

import pytest

from ari.rqgm.context_views import (
    ARCHIVE_ONLY_FIELDS,
    BFTS_VIEW_ROLE,
    CHARTER_BLOCK_CAP,
    GOVERNANCE_EXCLUDED_KEYS,
    JUDGE_EXCLUDED_KEYS,
    PROPOSAL_SUMMARY_FIELDS,
    bfts_view_violations,
    build_adversary_context,
    build_bfts_summary_context,
    build_governance_context,
    build_judge_context,
    build_reviewer_context,
)
from ari.rqgm.kernel import ConstitutionalKernel
from ari.rqgm.kernel_rules import CONTEXT_VIEW_WHITELISTS
from ari.rqgm.proposals.records import (
    ProposalRecord,
    ProposalSummaryView,
    render_summary_ctx,
)

_SENTINEL = "ARCHIVE_LEAK_SENTINEL"


def _summary() -> ProposalSummaryView:
    return ProposalSummaryView(
        proposal_record_id="prop_000001",
        title="Cache-aware scheduling",
        short_description="Improve locality on NUMA nodes.",
        hypothesis="Pinning halves stalls.",
        experiment_plan=("### 1) profile baseline", "### 2) pin threads"),
        success_metric={"name": "stall_rate", "higher_is_better": False},
        novelty_risks=("overlaps with 2019 work",),
        expected_artifacts=("results.json",),
        dissent_summary="One agent doubted portability.",
        scores={"overall": 0.7},
    )


def _record_with_archive_fields() -> ProposalRecord:
    """Fixture ProposalRecord populated with every archive-only field the
    §9.7 leak test names (transcript / discussion_log / raw_proposals)."""
    return ProposalRecord(
        record_id="prop_000001",
        generator="virsci",
        summary=_summary(),
        source_refs={"transcript": f"{_SENTINEL}_ref"},
        archive_refs={
            "transcript": f"{_SENTINEL}_transcript.json",
            "discussion_log": f"{_SENTINEL}_discussion.json",
            "raw_proposals": f"{_SENTINEL}_raw.json",
            "raw_output": f"{_SENTINEL}_out.json",
        },
        idea_projection={"discussion_log": _SENTINEL},
    )


# ── layer 1: typed renderer input ───────────────────────────────────────────


def test_bfts_renderer_rejects_anything_but_a_summary_view():
    record = _record_with_archive_fields()
    with pytest.raises(TypeError):
        build_bfts_summary_context(record)  # full record: type error
    with pytest.raises(TypeError):
        build_bfts_summary_context(record.summary.to_dict())  # raw dict too
    assert build_bfts_summary_context(record.summary)  # the summary renders


def test_bfts_renderer_respects_the_cap():
    ctx = build_bfts_summary_context(_summary(), cap=50)
    assert len(ctx) <= 50
    assert len(build_bfts_summary_context(_summary())) <= 6000


# ── layer 3: leak-regression (§9.7) ─────────────────────────────────────────


def test_no_archive_field_reaches_the_rendered_expand_context():
    record = _record_with_archive_fields()
    rendered = build_bfts_summary_context(record.summary)
    assert rendered == render_summary_ctx(record.summary)  # same channel
    assert _SENTINEL not in rendered
    for name in ARCHIVE_ONLY_FIELDS:
        assert name not in rendered
    # Byte-deterministic: identical input -> identical bytes (P2).
    assert rendered == build_bfts_summary_context(record.summary)


# ── layer 2: kernel check shares the whitelist constant ─────────────────────


def test_whitelist_constant_is_the_kernel_table_entry():
    # One source (plan 12 §6.5): the module constant IS the pinned kernel
    # rules entry — no copy that could drift.
    assert PROPOSAL_SUMMARY_FIELDS is CONTEXT_VIEW_WHITELISTS[BFTS_VIEW_ROLE]
    assert set(_summary().to_dict()) <= set(PROPOSAL_SUMMARY_FIELDS)


def test_kernel_context_scope_and_helper_agree():
    kernel = ConstitutionalKernel()
    clean = _summary().to_dict()
    assert kernel.validate_context_scope(BFTS_VIEW_ROLE, clean).ok
    assert bfts_view_violations(clean) == []
    leaky = dict(clean, transcript=_SENTINEL)
    report = kernel.validate_context_scope(BFTS_VIEW_ROLE, leaky)
    assert [v.code for v in report.violations] == ["CK-CTX-001"]
    assert "transcript" in report.violations[0].detail
    assert bfts_view_violations(leaky) == [
        "field 'transcript' is outside the BFTS ProposalSummaryView whitelist"
    ]


def test_live_expand_context_hook_warns_and_flags_out_of_scope_views(
    tmp_path,
):
    """Layer-2 runtime enforcement: the ari_rqgm expand-context hook runs
    ``validate_context_scope`` on the live view — a whitelist violation is
    audit-flagged (``kernel_report``) and the leaky view is never rendered
    (the caller keeps its idea.json fallback); a clean summary renders with
    no flag. Warn-and-flag only — the run never blocks (plan 12 §5.7)."""
    import json
    from types import SimpleNamespace

    from ari.config import ARIConfig
    from ari.rqgm.runtime import RQGMRuntime
    from ari.rqgm.store import ImmutableAuditLog

    cfg = ARIConfig(ari={"mode": "ari_rqgm"}, rqgm={"enabled": True})
    runtime = RQGMRuntime(cfg, checkpoint_dir=tmp_path)

    def _select(summary):
        runtime._proposal_store = SimpleNamespace(
            selected=lambda: SimpleNamespace(summary=summary)
        )

    _select(_summary())
    assert "Cache-aware scheduling" in runtime.render_expand_context()
    assert not [
        l for l in ImmutableAuditLog.read(tmp_path)
        if l.get("event_type") == "kernel_report"
    ]  # clean view: no flag
    _select(dict(_summary().to_dict(), transcript=_SENTINEL))
    assert runtime.render_expand_context() == ""  # layer 1: never rendered
    reports = [
        l for l in ImmutableAuditLog.read(tmp_path)
        if l.get("event_type") == "kernel_report"
    ]
    assert reports and "CK-CTX-001" in json.dumps(reports[-1])


# ── §5.7 visibility matrix exclusions ───────────────────────────────────────


def test_judge_view_never_sees_frontier_scores():
    attack = {"record_id": "atk_1", "claim": "overclaim",
              "frontier_scores": [0.9, 0.8], "_scientific_score": 0.9}
    defense = {"record_id": "def_1", "utility": 0.5, "argument": "contested"}
    bundle = {"items": [{"ref": "r1", "frontier_rank": 1}],
              "scientific_score": 0.7}
    view = build_judge_context(attack, defense, bundle)
    assert view["role"] == "judge"
    flat = str(view)
    for key in JUDGE_EXCLUDED_KEYS:
        assert key not in flat
    assert view["attack"]["claim"] == "overclaim"  # substance preserved
    assert view["defense"]["argument"] == "contested"


def test_governance_view_never_sees_retired_prompt_text():
    bundles = [{"bundle_id": "evb_1", "prompt_text": _SENTINEL,
                "template": _SENTINEL}]
    replay = [{"case_id": "adv_case_00001", "body": _SENTINEL,
               "score": 0.4}]
    view = build_governance_context(
        {"reviewer": "a" * 12, "prompt_body": _SENTINEL}, bundles, replay
    )
    flat = str(view)
    assert _SENTINEL not in flat
    for key in GOVERNANCE_EXCLUDED_KEYS:
        assert key not in flat
    assert view["prompt_hashes"]["reviewer"] == "a" * 12
    assert view["replay_results"][0]["score"] == 0.4


def test_reviewer_and_adversary_views_are_bounded_projections():
    record = _record_with_archive_fields()
    rev = build_reviewer_context(record, ["node_report.json#claims"])
    assert rev["role"] == "reviewer"
    assert rev["proposal"] == record.summary.to_dict()
    assert _SENTINEL not in str(rev)  # archive refs never enter the view
    adv = build_adversary_context(
        record.summary, {"_scientific_score": 0.7},
        ["claim_00001", "claim_00002"],
    )
    assert adv["role"] == "adversary"
    assert adv["summary"]["novelty_risks"] == ["overlaps with 2019 work"]
    assert adv["claim_refs"] == ["claim_00001", "claim_00002"]
    long_ref = "x" * 10_000
    capped = build_reviewer_context(record, [long_ref])
    assert len(capped["evidence_refs"][0]) <= 4000  # per-field truncation


def test_charter_cap_matches_the_agent_loop_field_caps():
    from ari.agent.loop import _IDEA_FIELD_CAP

    assert CHARTER_BLOCK_CAP == 1200
    assert CHARTER_BLOCK_CAP <= _IDEA_FIELD_CAP  # in line with idea caps


# ── the whitelists must be ENFORCED, not merely declared (dead-seam sweep) ───
#
# Scope control is a two-part design: construction-time (these builders) and
# check-time (`ConstitutionalKernel.validate_context_scope`, CK-CTX-001). The
# check-time half had NO production caller, so a builder that grew a foreign
# field would ship silently. The check now runs INSIDE the whitelisted
# builders, so every current and future call site is covered.

def test_scope_check_is_silent_on_a_clean_view(caplog):
    import logging

    from ari.rqgm.context_views import _enforce_scope

    with caplog.at_level(logging.WARNING):
        _enforce_scope("generator", {"title": "T", "hypothesis": "H"})
    assert not [r for r in caplog.records if "CK-CTX-001" in r.getMessage()]


def test_scope_check_flags_a_foreign_field(caplog):
    import logging

    from ari.rqgm.context_views import _enforce_scope

    with caplog.at_level(logging.WARNING):
        _enforce_scope("generator",
                       {"title": "T", "defender_strategy": "LEAKED"})
    msgs = [r.getMessage() for r in caplog.records]
    assert any("CK-CTX-001" in m for m in msgs), msgs
    assert any("defender_strategy" in m for m in msgs), msgs


def test_a_role_without_a_whitelist_is_unchecked(caplog):
    """v1 defines whitelists for three roles; the rest are unchecked by design
    (§5.1) — the check must not invent violations for them."""
    import logging

    from ari.rqgm.context_views import _enforce_scope

    with caplog.at_level(logging.WARNING):
        _enforce_scope("adversary", {"anything": "goes"})
    assert not [r for r in caplog.records if "CK-CTX-001" in r.getMessage()]


def test_every_whitelisted_builder_runs_the_check():
    """All three whitelisted roles must be covered — not just the one that
    happened to have a production call site."""
    import inspect

    from ari.rqgm import context_views as cv

    for fn in ("build_bfts_summary_context", "build_paper_writer_context",
               "build_paper_reviewer_context"):
        src = inspect.getsource(getattr(cv, fn))
        assert "_enforce_scope(" in src, f"{fn} does not run the scope check"


def test_the_builders_still_return_their_whitelisted_key_set():
    from ari.rqgm.context_views import (
        PAPER_REVIEWER_FIELDS,
        PAPER_WRITER_FIELDS,
        build_paper_reviewer_context,
        build_paper_writer_context,
    )

    rv = build_paper_reviewer_context(
        draft_manuscript={}, verified_context={}, science_data={},
        reference_context={},
    )
    assert set(rv) == set(PAPER_REVIEWER_FIELDS)
    wv = build_paper_writer_context(
        verified_context={}, science_data={}, claim_registry={},
    )
    assert set(wv) == set(PAPER_WRITER_FIELDS)
