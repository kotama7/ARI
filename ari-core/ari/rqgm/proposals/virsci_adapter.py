"""VirSciAdapter — MCP-only normalizer for the idea skill (RQGM Task 03).

Core-side adapter over the idea skill's ``generate_ideas`` (and optionally
``survey``) MCP tools. It imports NOTHING from ``ari-skill-idea`` and has
zero VirSci dependencies — heavy deps (torch/faiss/agentscope) stay inside
the skill process, which keeps the skill's existing three degradation tiers
and makes "tests pass without VirSci installed" structural.

``virsci.enabled=false`` guarantees: this class is only ever
constructed by :class:`ari.rqgm.proposals.router.ProposalRouter` when
``proposal_router.generators.virsci.enabled`` is true; there is no
module-level import side effect anywhere in this file, so merely importing
it requires no VirSci runtime, vendored submodule, or snapshot corpus.

Archive/summary split: the full 9-key payload (raw proposal list, gap
analysis, generator config) is archived by the router via
``ProposalDraft.raw_output``; existing on-disk artifacts
(``{ckpt}/virsci_logs/``, ``{ckpt}/virsci_snapshot/``) are *referenced* in
``archive_refs``, never copied and never rendered into any summary field.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ari.rqgm.proposals.generators import ProposalDraft
from ari.rqgm.proposals.records import (
    ProposalSummaryView,
    clamp_summary,
)

log = logging.getLogger(__name__)

#: The nine top-level keys of the ``generate_ideas`` contract.
GENERATE_IDEAS_KEYS: tuple[str, ...] = (
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


def _first_sentence(text: str, limit: int) -> str:
    head = (text or "").split(". ")[0].strip()
    return head[:limit]


def _plan_steps(plan_text: str) -> tuple[str, ...]:
    """Split a VirSci ``experiment_plan`` into bounded ``### N)`` steps via
    the existing section parser (format preserved for
    ``_extract_plan_sections`` round-trips)."""
    steps: list[str] = []
    try:
        from ari.pipeline.experiment_md import _extract_plan_sections

        for tag, title, body in _extract_plan_sections(plan_text or ""):
            step = f"{tag} {title}"
            if body:
                step += f": {body}"
            steps.append(step)
    except Exception:
        steps = []
    if not steps and (plan_text or "").strip():
        steps = [plan_text.strip()]
    return tuple(steps)


def normalize_generate_ideas_result(payload: dict) -> list[ProposalDraft]:
    """Normalize one 9-key ``generate_ideas`` payload → 1 draft per idea.

    Pure and deterministic (P2): same payload, same drafts. Summary fields
    are clamped to the ``ProposalSummaryView`` character budgets by
    ``clamp_summary``; NO transcript/discussion content enters
    any summary field — only the idea entries and the shared metric keys.
    Works identically for ``real_wrap`` and ``reimpl`` integration statuses.
    """
    if not isinstance(payload, dict):
        return []
    ideas = payload.get("ideas")
    if not isinstance(ideas, list):
        return []
    metric = {
        "name": str(payload.get("primary_metric", "") or ""),
        "higher_is_better": bool(payload.get("higher_is_better", True)),
        "rationale": str(payload.get("metric_rationale", "") or ""),
    }
    projection_meta = {
        k: payload.get(k)
        for k in (
            "gap_analysis",
            "papers_analyzed",
            "n_agents",
            "discussion_rounds",
            "virsci_integration_status",
        )
        if k in payload
    }
    drafts: list[ProposalDraft] = []
    for idea in ideas:
        if not isinstance(idea, dict) or not idea.get("title"):
            continue
        description = str(idea.get("description", "") or "")
        nov = float(idea.get("novelty_score", 0.0) or 0.0)
        feas = float(idea.get("feasibility_score", 0.0) or 0.0)
        overall = float(idea.get("overall_score", 0.0) or 0.0)
        summary = clamp_summary(
            ProposalSummaryView(
                title=str(idea.get("title", "")),
                short_description=description,
                hypothesis=_first_sentence(description, 400),
                experiment_plan=_plan_steps(
                    str(idea.get("experiment_plan", "") or "")
                ),
                success_metric=dict(metric),
                novelty_risks=(
                    (str(idea.get("novelty", "")),)
                    if idea.get("novelty")
                    else ()
                ),
                expected_artifacts=(),
                dissent_summary=str(idea.get("dissent_summary", "") or ""),
                scores={
                    "novelty": nov,
                    "feasibility": feas,
                    "overall": overall,
                },
            )
        )
        drafts.append(
            ProposalDraft(
                generator="virsci",
                summary=summary,
                source_refs={},
                raw_output={"idea": idea, "generate_ideas": payload},
                projection_meta=dict(projection_meta),
            )
        )
    return drafts


def _mcp_payload(result) -> dict:
    """Unwrap the MCPClient tool-result envelope (``{"result": ...}`` or a
    JSON string) into the raw 9-key dict; ``{}`` on anything unparseable."""
    import json

    data = result
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            return {}
    if isinstance(data, dict) and "result" in data and "ideas" not in data:
        inner = data["result"]
        if isinstance(inner, str):
            try:
                inner = json.loads(inner)
            except json.JSONDecodeError:
                return {}
        data = inner
    return data if isinstance(data, dict) else {}


class VirSciAdapter:
    """Optional high-cost deliberative generator (constructed only when
    ``proposal_router.generators.virsci.enabled`` is true)."""

    name = "virsci"

    def __init__(
        self,
        mcp,
        *,
        checkpoint_dir: str | Path | None = None,
        n_ideas: int = 3,
        survey_max_papers: int = 8,
    ) -> None:
        self.mcp = mcp
        self.checkpoint_dir = (
            Path(checkpoint_dir) if checkpoint_dir is not None else None
        )
        self.n_ideas = int(n_ideas)
        self.survey_max_papers = int(survey_max_papers)

    def generate(self, ctx: dict) -> list[ProposalDraft]:
        """Call ``survey`` + ``generate_ideas`` over MCP and normalize.

        Never raises; any tool failure degrades to zero drafts (the router
        then falls through to the cheaper generators). Content-key dedup at
        the store makes this idempotent under the MCP 3-retry policy.
        """
        topic = str(ctx.get("goal", "") or "")
        papers: list = []
        try:
            survey_res = self.mcp.call_tool(
                "survey",
                {"topic": topic, "max_papers": self.survey_max_papers},
            )
            survey_payload = _mcp_payload(survey_res)
            got = survey_payload.get("papers")
            if isinstance(got, list):
                papers = got
        except Exception:
            log.warning("VirSciAdapter survey failed; continuing without "
                        "papers", exc_info=True)
        try:
            res = self.mcp.call_tool(
                "generate_ideas",
                {
                    "topic": topic,
                    "papers": papers,
                    "experiment_context": str(
                        ctx.get("experiment_context", "") or ""
                    ),
                    "n_ideas": self.n_ideas,
                },
            )
        except Exception:
            log.warning("VirSciAdapter generate_ideas failed", exc_info=True)
            return []
        drafts = normalize_generate_ideas_result(_mcp_payload(res))
        return [self._with_archive_refs(d) for d in drafts]

    def _with_archive_refs(self, draft: ProposalDraft) -> ProposalDraft:
        """Reference (never copy) the skill's on-disk transcript artifacts."""
        if self.checkpoint_dir is None:
            return draft
        refs: dict = {}
        stdout_log = self.checkpoint_dir / "virsci_logs" / "virsci_stdout.log"
        if stdout_log.exists():
            refs["discussion_log"] = "virsci_logs/virsci_stdout.log"
        snapshot = self.checkpoint_dir / "virsci_snapshot"
        if snapshot.is_dir():
            refs["retrieval_snapshot"] = "virsci_snapshot/"
        if not refs:
            return draft
        from dataclasses import replace

        raw = dict(draft.raw_output)
        raw["archive_refs"] = refs
        return replace(draft, raw_output=raw)
