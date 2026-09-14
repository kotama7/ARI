"""ProposalRecord + ProposalSummaryView schemas (RQGM Task 03, plan 03 §6).

Two dataclasses mirror ``ari/schemas/proposal_record.schema.json`` /
``proposal_summary_view.schema.json`` (both ``schema_version: 1``,
additive-only evolution):

* :class:`ProposalRecord` — the archival, provenance-complete record of one
  generated proposal ("store everything"). Carries the mandatory common
  record fields of the ``rqgm_record_base`` envelope (plan 02 §6) plus the
  Task-10-owned ``stale`` / ``valid_for_frontier`` flags, which are
  **logical-only**: written once at their defaults and never rewritten in
  stored JSONL — staleness is materialized only in the erasure state and
  derived by readers as ``record_id ∈ stale_record_ids``.
* :class:`ProposalSummaryView` — the bounded summary that is the ONLY
  proposal representation BFTS may consume. Eight spec-mandated fields with
  hard character budgets; :func:`render_summary_ctx` is the pure renderer
  whose total budget matches today's ``_build_idea_ctx_for_expand`` channel
  (~6000 chars).

Hash discipline (P2): ``prompt_hash`` is the existing ``hash12`` scheme —
no second scheme; ``created_at`` is wall-clock metadata and NEVER enters any
content hash. :func:`content_key` is the deterministic dedup key (retry
idempotency under the MCP 3-retry policy). Pure stdlib, no LLM calls.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from ari.rqgm.events import canonical_json, hash12

PROPOSAL_RECORD_SCHEMA_VERSION = 1
PROPOSAL_RECORD_TYPE = "proposal_record"

#: Closed generator vocabulary (plan 03 §6.1).
GENERATORS: tuple[str, ...] = (
    "cheap",
    "mutation",
    "attack_driven",
    "prior_art",
    "virsci",
    "legacy_idea_json",
)

#: Proposal lifecycle statuses (plan 03 §6.1) — set at append time; the JSONL
#: store is append-only, so "the latest selected record wins" is the read rule.
PROPOSAL_STATUSES: tuple[str, ...] = (
    "candidate",
    "selected",
    "expanded",
    "superseded",
)

#: Mutation facets accepted by the MutationGenerator (plan 03 §5.3).
MUTATION_FACETS: tuple[str, ...] = (
    "hypothesis",
    "plan_step",
    "success_metric",
    "scope",
)

# ── ProposalSummaryView size budgets (plan 03 §6.2, hard limits) ────────────

TITLE_BUDGET = 200
SHORT_DESCRIPTION_BUDGET = 600
HYPOTHESIS_BUDGET = 400
PLAN_MAX_STEPS = 6
PLAN_STEP_BUDGET = 400
NOVELTY_RISKS_MAX = 3
NOVELTY_RISK_BUDGET = 200
EXPECTED_ARTIFACTS_MAX = 5
EXPECTED_ARTIFACT_BUDGET = 120
DISSENT_BUDGET = 400

#: Rendered total budget (parity with ``_build_idea_ctx_for_expand``).
RENDERED_CTX_BUDGET = 6000


def format_proposal_record_id(seq: int) -> str:
    """``prop_%06d`` — stable, monotonic per run (plan 03 §6.1 example)."""
    return "prop_%06d" % int(seq)


@dataclass(frozen=True)
class ProposalSummaryView:
    """The bounded summary — the ONLY shape BFTS sees (plan 03 §6.2)."""

    proposal_record_id: str = ""
    title: str = ""
    short_description: str = ""
    hypothesis: str = ""
    experiment_plan: tuple[str, ...] = ()
    success_metric: dict = field(default_factory=dict)
    novelty_risks: tuple[str, ...] = ()
    expected_artifacts: tuple[str, ...] = ()
    dissent_summary: str = ""
    scores: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "proposal_record_id": self.proposal_record_id,
            "title": self.title,
            "short_description": self.short_description,
            "hypothesis": self.hypothesis,
            "experiment_plan": list(self.experiment_plan),
            "success_metric": dict(self.success_metric),
            "novelty_risks": list(self.novelty_risks),
            "expected_artifacts": list(self.expected_artifacts),
            "dissent_summary": self.dissent_summary,
            "scores": dict(self.scores),
        }


def summary_from_dict(d: dict) -> ProposalSummaryView:
    return ProposalSummaryView(
        proposal_record_id=str(d.get("proposal_record_id", "")),
        title=str(d.get("title", "")),
        short_description=str(d.get("short_description", "")),
        hypothesis=str(d.get("hypothesis", "")),
        experiment_plan=tuple(str(s) for s in (d.get("experiment_plan") or [])),
        success_metric=dict(d.get("success_metric") or {}),
        novelty_risks=tuple(str(s) for s in (d.get("novelty_risks") or [])),
        expected_artifacts=tuple(
            str(s) for s in (d.get("expected_artifacts") or [])
        ),
        dissent_summary=str(d.get("dissent_summary", "")),
        scores=dict(d.get("scores") or {}),
    )


def clamp_summary(view: ProposalSummaryView) -> ProposalSummaryView:
    """Deterministically truncate every field to its §6.2 budget.

    Generators run raw LLM output through this before a summary is stored,
    so stored summaries are in-budget by construction.
    """
    plan = tuple(
        s[:PLAN_STEP_BUDGET] for s in view.experiment_plan[:PLAN_MAX_STEPS]
    )
    risks = tuple(
        s[:NOVELTY_RISK_BUDGET] for s in view.novelty_risks[:NOVELTY_RISKS_MAX]
    )
    artifacts = tuple(
        s[:EXPECTED_ARTIFACT_BUDGET]
        for s in view.expected_artifacts[:EXPECTED_ARTIFACTS_MAX]
    )
    return replace(
        view,
        title=view.title[:TITLE_BUDGET],
        short_description=view.short_description[:SHORT_DESCRIPTION_BUDGET],
        hypothesis=view.hypothesis[:HYPOTHESIS_BUDGET],
        experiment_plan=plan,
        novelty_risks=risks,
        expected_artifacts=artifacts,
        dissent_summary=view.dissent_summary[:DISSENT_BUDGET],
    )


def summary_violations(view: ProposalSummaryView) -> list[str]:
    """Deterministic budget check — the Task 04 kernel-check surface.

    Returns one human-readable violation per over-budget field (empty ==
    valid). No LLM, no wall clock, no randomness (P2).
    """
    out: list[str] = []
    if len(view.title) > TITLE_BUDGET:
        out.append(f"title exceeds {TITLE_BUDGET} chars")
    if len(view.short_description) > SHORT_DESCRIPTION_BUDGET:
        out.append(f"short_description exceeds {SHORT_DESCRIPTION_BUDGET} chars")
    if len(view.hypothesis) > HYPOTHESIS_BUDGET:
        out.append(f"hypothesis exceeds {HYPOTHESIS_BUDGET} chars")
    if len(view.experiment_plan) > PLAN_MAX_STEPS:
        out.append(f"experiment_plan exceeds {PLAN_MAX_STEPS} steps")
    for i, step in enumerate(view.experiment_plan):
        if len(step) > PLAN_STEP_BUDGET:
            out.append(f"experiment_plan[{i}] exceeds {PLAN_STEP_BUDGET} chars")
    if len(view.novelty_risks) > NOVELTY_RISKS_MAX:
        out.append(f"novelty_risks exceeds {NOVELTY_RISKS_MAX} items")
    for i, risk in enumerate(view.novelty_risks):
        if len(risk) > NOVELTY_RISK_BUDGET:
            out.append(f"novelty_risks[{i}] exceeds {NOVELTY_RISK_BUDGET} chars")
    if len(view.expected_artifacts) > EXPECTED_ARTIFACTS_MAX:
        out.append(
            f"expected_artifacts exceeds {EXPECTED_ARTIFACTS_MAX} items"
        )
    for i, art in enumerate(view.expected_artifacts):
        if len(art) > EXPECTED_ARTIFACT_BUDGET:
            out.append(
                f"expected_artifacts[{i}] exceeds "
                f"{EXPECTED_ARTIFACT_BUDGET} chars"
            )
    if len(view.dissent_summary) > DISSENT_BUDGET:
        out.append(f"dissent_summary exceeds {DISSENT_BUDGET} chars")
    return out


def render_summary_ctx(
    view: ProposalSummaryView, budget: int = RENDERED_CTX_BUDGET
) -> str:
    """Render the expand-context string from a summary (pure, P2).

    The ``ari_rqgm`` replacement for the ``idea.json``-derived
    ``_build_idea_ctx_for_expand`` channel: byte-identical output for
    identical input, total length ≤ *budget*, and NOTHING outside the
    summary's own fields ever enters the string (archive content cannot
    leak into prompts through this function).
    """
    parts = [
        f"Idea: {view.title}",
        f"Description: {view.short_description}",
    ]
    if view.hypothesis:
        parts.append(f"Hypothesis: {view.hypothesis}")
    if view.experiment_plan:
        plan_lines = ["Plan sections:"]
        for step in view.experiment_plan:
            plan_lines.append(f"  {step}")
        parts.append("\n".join(plan_lines))
    metric = view.success_metric
    if metric.get("name"):
        direction = "higher" if metric.get("higher_is_better", True) else "lower"
        line = f"Success metric: {metric['name']} ({direction} is better)"
        if metric.get("rationale"):
            line += f" — {metric['rationale']}"
        parts.append(line)
    if view.novelty_risks:
        parts.append(
            "Novelty risks: " + "; ".join(view.novelty_risks)
        )
    if view.expected_artifacts:
        parts.append(
            "Expected artifacts: " + "; ".join(view.expected_artifacts)
        )
    if view.dissent_summary:
        parts.append(f"Dissent: {view.dissent_summary}")
    return "\n".join(parts)[: max(0, int(budget))]


# ── ProposalRecord ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ProposalRecord:
    """One archival proposal record (plan 03 §6.1).

    ``epoch_id`` is ``None`` in ``simple_bfts`` record-only mode;
    ``prompt_hash`` is ``None`` for legacy imports and expansion-recorded
    observations. ``stale`` / ``valid_for_frontier`` are logical-only (their
    read-time semantics are Task 10's) and stay at their write-once defaults
    in stored JSONL.
    """

    record_id: str
    generator: str
    status: str = "candidate"
    epoch_id: str | None = None
    component_id: str = ""
    role: str = "generator"
    prompt_hash: str | None = None
    created_at: str = ""  # metadata; never hashed (P2)
    stale: bool = False
    valid_for_frontier: bool = True
    source_refs: dict = field(default_factory=dict)
    summary: ProposalSummaryView = field(default_factory=ProposalSummaryView)
    archive_refs: dict = field(default_factory=dict)
    idea_projection: dict = field(default_factory=dict)
    record_type: str = PROPOSAL_RECORD_TYPE
    schema_version: int = PROPOSAL_RECORD_SCHEMA_VERSION

    def to_dict(self) -> dict:
        """JSONL line layout, key order fixed to the plan's §6.1 example."""
        return {
            "record_id": self.record_id,
            "record_type": self.record_type,
            "schema_version": self.schema_version,
            "epoch_id": self.epoch_id,
            "component_id": self.component_id,
            "role": self.role,
            "generator": self.generator,
            "prompt_hash": self.prompt_hash,
            "created_at": self.created_at,
            "status": self.status,
            "stale": self.stale,
            "valid_for_frontier": self.valid_for_frontier,
            "source_refs": dict(self.source_refs),
            "summary": self.summary.to_dict(),
            "archive_refs": dict(self.archive_refs),
            "idea_projection": dict(self.idea_projection),
        }


def record_from_dict(d: dict) -> ProposalRecord:
    summary = summary_from_dict(
        d.get("summary") if isinstance(d.get("summary"), dict) else {}
    )
    return ProposalRecord(
        record_id=str(d.get("record_id", "")),
        generator=str(d.get("generator", "")),
        status=str(d.get("status", "candidate")),
        epoch_id=d.get("epoch_id"),
        component_id=str(d.get("component_id", "")),
        role=str(d.get("role", "generator")),
        prompt_hash=d.get("prompt_hash"),
        created_at=str(d.get("created_at", "")),
        stale=bool(d.get("stale", False)),
        valid_for_frontier=bool(d.get("valid_for_frontier", True)),
        source_refs=dict(d.get("source_refs") or {}),
        summary=summary,
        archive_refs=dict(d.get("archive_refs") or {}),
        idea_projection=dict(d.get("idea_projection") or {}),
        record_type=str(d.get("record_type", PROPOSAL_RECORD_TYPE)),
        schema_version=int(
            d.get("schema_version", PROPOSAL_RECORD_SCHEMA_VERSION)
        ),
    )


def content_key(record: ProposalRecord) -> str:
    """Deterministic dedup key over the proposal CONTENT (plan 03 §9).

    Excludes ``record_id`` / ``created_at`` / ``status`` so a retried MCP
    call (3-retry policy) that reproduces the same proposal maps to the same
    key — dedup by content, never by wall clock.
    """
    summary = record.summary.to_dict()
    summary.pop("proposal_record_id", None)
    return hash12(
        canonical_json(
            {
                "generator": record.generator,
                "source_refs": dict(record.source_refs),
                "summary": summary,
            }
        )
    )


def content_key_from_dict(d: dict) -> str:
    """:func:`content_key` over a parsed JSONL line (reader-side twin)."""
    return content_key(record_from_dict(d))


# ── idea.json projection mapping (plan 03 §6.4) ─────────────────────────────


def _plan_step_tagged(step: str, index: int) -> str:
    """Ensure a plan step carries the ``### N)`` section format so
    ``_extract_plan_sections`` keeps parsing projected plans."""
    s = step.strip()
    if s.startswith("#"):
        return s
    return f"### {index}) {s}"


def idea_from_summary(view: ProposalSummaryView) -> dict:
    """Project one summary into an ``ideas[i]`` entry (§6.4 mapping)."""
    scores = view.scores
    nov = float(scores.get("novelty", 0.0) or 0.0)
    feas = float(scores.get("feasibility", 0.0) or 0.0)
    overall = float(scores.get("overall", 0.0) or 0.0)
    plan_parts: list[str] = []
    if view.hypothesis:
        plan_parts.append(f"Hypothesis: {view.hypothesis}")
    for i, step in enumerate(view.experiment_plan, start=1):
        plan_parts.append(_plan_step_tagged(step, i))
    novelty = (
        "; ".join(view.novelty_risks)
        if view.novelty_risks
        else f"Novelty score: {round(nov * 10, 1)}"
    )
    return {
        "title": view.title,
        "description": view.short_description,
        "novelty": novelty,
        "feasibility": f"Feasibility score: {round(feas * 10, 1)}",
        "experiment_plan": "\n\n".join(plan_parts),
        "novelty_score": nov,
        "feasibility_score": feas,
        "overall_score": overall,
        # Underscore-key precedent (_pinned / _inherited_from): traceability
        # link back into proposal_records.jsonl.
        "_proposal_record_id": view.proposal_record_id,
    }


def summary_from_idea(idea: dict, *, record_id: str = "") -> ProposalSummaryView:
    """Inverse §6.4 mapping for legacy ``idea.json`` imports (Stage 1/3).

    Splits the joined ``experiment_plan`` back into bounded steps via the
    existing ``_extract_plan_sections`` parser and clamps every field.
    """
    plan_text = str(idea.get("experiment_plan", "") or "")
    steps: list[str] = []
    try:
        from ari.pipeline.experiment_md import _extract_plan_sections

        for tag, title, body in _extract_plan_sections(plan_text):
            step = f"{tag} {title}"
            if body:
                step += f": {body}"
            steps.append(step)
    except Exception:
        steps = []
    if not steps and plan_text.strip():
        steps = [plan_text.strip()]
    nov = float(idea.get("novelty_score", 0.0) or 0.0)
    feas = float(idea.get("feasibility_score", 0.0) or 0.0)
    overall = float(idea.get("overall_score", 0.0) or 0.0)
    return clamp_summary(
        ProposalSummaryView(
            proposal_record_id=record_id,
            title=str(idea.get("title", "") or ""),
            short_description=str(idea.get("description", "") or ""),
            hypothesis="",
            experiment_plan=tuple(steps),
            success_metric={},
            novelty_risks=(),
            expected_artifacts=(),
            dissent_summary="",
            scores={"novelty": nov, "feasibility": feas, "overall": overall},
        )
    )
