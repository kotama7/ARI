"""Proposal generators (RQGM Task 03 §5.3) — injectable, deterministic-fallback.

Four prompt-defined generators plus the Generator protocol the router
dispatches over (the fifth, the VirSciAdapter, lives in
:mod:`ari.rqgm.proposals.virsci_adapter`). Every generator:

* is invoked through the injectable ``llm`` seam (an object exposing
  ``complete(messages, require_tool=False) -> resp`` with ``resp.content`` —
  :class:`ari.llm.client.LLMClient` structurally; tests inject deterministic
  fakes and NEVER call a real LLM);
* loads its committed ``.md`` template via ``load_versioned`` (the returned
  ``hash12`` IS the record ``prompt_hash`` — one scheme, plan 02 §5.4) and
  stamps the call via ``record_prompt_use`` (→ ``prompt_trace.jsonl``);
* returns plain :class:`ProposalDraft` values — the router owns record ids,
  envelope stamping, archiving, and store appends;
* degrades instead of raising: a parse/LLM failure yields the deterministic
  fallback draft (cheap) or no drafts (mutation / prior-art skipped).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field, replace
from typing import Protocol

from ari.rqgm.proposals.records import (
    MUTATION_FACETS,
    ProposalSummaryView,
    clamp_summary,
)

log = logging.getLogger(__name__)

CHEAP_PROMPT_KEY = "rqgm/proposal_cheap"
MUTATION_PROMPT_KEY = "rqgm/proposal_mutation"
PRIOR_ART_PROMPT_KEY = "rqgm/proposal_prior_art"

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


@dataclass(frozen=True)
class ProposalDraft:
    """One generator output before envelope stamping (router-internal)."""

    generator: str
    summary: ProposalSummaryView
    source_refs: dict = field(default_factory=dict)
    raw_output: dict = field(default_factory=dict)
    prompt_hash: str | None = None
    #: Extra 9-key idea.json fields (gap_analysis, ...) for the projection.
    projection_meta: dict = field(default_factory=dict)


class Generator(Protocol):
    """Structural contract every router generator satisfies."""

    name: str

    def generate(self, ctx: dict) -> list[ProposalDraft]:
        """Produce zero or more drafts for *ctx*; must not raise."""
        ...


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


def _summary_from_payload(payload: dict) -> ProposalSummaryView:
    """Map a generator JSON payload onto a clamped summary."""
    metric = payload.get("success_metric")
    if not isinstance(metric, dict):
        metric = {}
    scores = payload.get("scores")
    if not isinstance(scores, dict):
        scores = {}
    return clamp_summary(
        ProposalSummaryView(
            title=str(payload.get("title", "") or ""),
            short_description=str(payload.get("short_description", "") or ""),
            hypothesis=str(payload.get("hypothesis", "") or ""),
            experiment_plan=tuple(
                str(s) for s in (payload.get("experiment_plan") or [])
            ),
            success_metric={
                "name": str(metric.get("name", "") or ""),
                "higher_is_better": bool(metric.get("higher_is_better", True)),
                "rationale": str(metric.get("rationale", "") or ""),
            },
            novelty_risks=tuple(
                str(s) for s in (payload.get("novelty_risks") or [])
            ),
            expected_artifacts=tuple(
                str(s) for s in (payload.get("expected_artifacts") or [])
            ),
            dissent_summary=str(payload.get("dissent_summary", "") or ""),
            scores={
                "novelty": float(scores.get("novelty", 0.0) or 0.0),
                "feasibility": float(scores.get("feasibility", 0.0) or 0.0),
                "overall": float(scores.get("overall", 0.0) or 0.0),
            },
        )
    )


class _PromptedGenerator:
    """Shared load-format-complete-parse plumbing (template method)."""

    name = ""
    prompt_key = ""

    def __init__(self, llm=None, loader=None, checkpoint_dir=None) -> None:
        self.llm = llm
        self._loader = loader
        self.checkpoint_dir = checkpoint_dir

    def _load_prompt(self) -> tuple[str, str]:
        loader = self._loader
        if loader is None:
            from ari.prompts import FilesystemPromptLoader

            loader = FilesystemPromptLoader()
        return loader.load_versioned(self.prompt_key)

    def _complete(self, prompt: str) -> str:
        resp = self.llm.complete(
            [{"role": "user", "content": prompt}], require_tool=False
        )
        return getattr(resp, "content", "") or ""

    def _call(self, format_kwargs: dict) -> tuple[dict, str | None, str]:
        """Return ``(payload, prompt_hash, raw_text)``; never raises."""
        try:
            template, prompt_hash = self._load_prompt()
            prompt = template.format(**format_kwargs)
        except Exception:
            log.warning("%s prompt load failed", self.name, exc_info=True)
            return {}, None, ""
        try:
            from ari.prompts import record_prompt_use

            record_prompt_use(
                self.prompt_key,
                prompt_hash,
                rendered_text=prompt,
                phase="rqgm_proposal",
                checkpoint_dir=self.checkpoint_dir,
            )
        except Exception:
            pass
        if self.llm is None:
            return {}, prompt_hash, ""
        try:
            raw = self._complete(prompt)
        except Exception:
            log.warning("%s LLM call failed", self.name, exc_info=True)
            return {}, prompt_hash, ""
        return _extract_json(raw), prompt_hash, raw


class CheapGenerator(_PromptedGenerator):
    """Default one-shot proposal generator (plan 03 §5.3).

    Deterministic fallback mirrors the existing DEBUG/IMPROVE fallback-child
    semantics: when the LLM output cannot be parsed (or no LLM is injected),
    a minimal draft derived purely from the goal text is returned so the
    router always has a proposal to record.
    """

    name = "cheap"
    prompt_key = CHEAP_PROMPT_KEY

    def generate(self, ctx: dict) -> list[ProposalDraft]:
        goal = str(ctx.get("goal", "") or "")
        payload, prompt_hash, raw = self._call(
            {
                "goal": goal,
                "idea_context": str(ctx.get("idea_context", "") or ""),
            }
        )
        if payload:
            summary = _summary_from_payload(payload)
            if summary.title:
                return [
                    ProposalDraft(
                        generator=self.name,
                        summary=summary,
                        raw_output={"payload": payload, "raw_text": raw},
                        prompt_hash=prompt_hash,
                    )
                ]
        # Deterministic fallback: propose the goal itself as a draft plan.
        fallback = clamp_summary(
            ProposalSummaryView(
                title=(goal.splitlines()[0] if goal else "Baseline experiment"),
                short_description=goal,
                hypothesis="",
                experiment_plan=(
                    "### 1) Implement a minimal baseline for the goal",
                    "### 2) Measure the primary metric and iterate",
                ),
                success_metric={},
                novelty_risks=(),
                expected_artifacts=(),
                dissent_summary="",
                scores={"novelty": 0.0, "feasibility": 0.0, "overall": 0.0},
            )
        )
        return [
            ProposalDraft(
                generator=self.name,
                summary=fallback,
                raw_output={"fallback": True, "raw_text": raw},
                prompt_hash=prompt_hash,
            )
        ]


class MutationGenerator(_PromptedGenerator):
    """Mutates ONE facet of an existing ProposalRecord (plan 03 §5.3).

    Input selection is deterministic: the caller passes the parent record
    (highest-utility / current directive — the router resolves it); the facet
    cycles deterministically from ``ctx["facet"]`` or defaults to
    ``hypothesis``. The parent record is never mutated in place (mirrors the
    no-in-place-prompt-mutation invariant): the output is a NEW record with
    ``source_refs.parent_proposal_id`` set.
    """

    name = "mutation"
    prompt_key = MUTATION_PROMPT_KEY

    def generate(self, ctx: dict) -> list[ProposalDraft]:
        parent = ctx.get("parent_record")
        if parent is None:
            return []  # nothing to mutate — degrade to skipped
        facet = str(ctx.get("facet", "hypothesis") or "hypothesis")
        if facet not in MUTATION_FACETS:
            facet = "hypothesis"
        from ari.rqgm.proposals.records import render_summary_ctx

        payload, prompt_hash, raw = self._call(
            {
                "goal": str(ctx.get("goal", "") or ""),
                "facet": facet,
                "parent_summary": render_summary_ctx(parent.summary),
            }
        )
        if not payload:
            return []
        summary = _summary_from_payload(payload)
        if not summary.title:
            return []
        return [
            ProposalDraft(
                generator=self.name,
                summary=summary,
                source_refs={"parent_proposal_id": parent.record_id},
                raw_output={
                    "payload": payload,
                    "raw_text": raw,
                    "facet": facet,
                },
                prompt_hash=prompt_hash,
            )
        ]


class AttackDrivenGenerator:
    """Seam for Task 06's ValidatedAttackRecords (plan 03 §5.3).

    Disabled (and absent from the routing table) until Task 06 lands; kept
    as a concrete no-op so the router's generator registry shape is final.
    """

    name = "attack_driven"

    def __init__(self, llm=None, loader=None, checkpoint_dir=None) -> None:
        self.llm = llm

    def generate(self, ctx: dict) -> list[ProposalDraft]:
        # Requires the AdversarialReplayPool (docs/reference/rqgm_schemas.md,
        # the `rqgm_replay_pool.schema.json` section).
        return []


class PriorArtDifferentiationGenerator(_PromptedGenerator):
    """Differentiates against survey/related refs (plan 03 §5.3).

    Degrades to skipped (empty result) when no prior-art source exists in
    *ctx* — the router then falls through to the next generator.
    """

    name = "prior_art"
    prompt_key = PRIOR_ART_PROMPT_KEY

    def generate(self, ctx: dict) -> list[ProposalDraft]:
        refs = [str(r) for r in (ctx.get("survey_refs") or []) if str(r)]
        if not refs:
            return []  # no prior-art source — degrade to skipped
        payload, prompt_hash, raw = self._call(
            {
                "goal": str(ctx.get("goal", "") or ""),
                "prior_art_block": "\n".join(f"- {r}" for r in refs[:20]),
            }
        )
        if not payload:
            return []
        summary = _summary_from_payload(payload)
        if not summary.title:
            return []
        return [
            ProposalDraft(
                generator=self.name,
                summary=summary,
                source_refs={"survey_refs": refs[:20]},
                raw_output={"payload": payload, "raw_text": raw},
                prompt_hash=prompt_hash,
            )
        ]


def draft_with_record_id(draft: ProposalDraft, record_id: str) -> ProposalDraft:
    """Stamp the assigned record id into the draft's summary (router step)."""
    return replace(
        draft, summary=replace(draft.summary, proposal_record_id=record_id)
    )
