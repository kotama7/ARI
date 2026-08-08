"""Agent-as-judge draft scoring — the LLM seam past the discrimination ceiling.

The deterministic ``GovernedPaperReviewer`` scores each archive draft over the
venue rubric axes a *deterministic reader* can read (structure, claim anchors,
length). Axes like ``novelty`` or ``significance`` have NO deterministic reader,
so the LLM-free path leaves them ABSENT — and two mature drafts that both
saturate the readable axes then TIE at the ceiling, giving best-belief selection
nothing to choose on (the "discrimination ceiling").

This module lands the seam the deterministic path leaves open: a real
``LLMClient``-backed ``score_fn(prompt_text, draft_text) -> float`` that scores a
draft over the SAME venue rubric axes, weighted by the ACTIVE governed reviewer
prompt's emphasis — so evolving the reviewer's bytes still moves selection, and
the score can now read the axes no deterministic reader can. It is OPT-IN
(``rqgm.paper.reviewer.agent_as_judge.enabled`` / ``ARI_PAPER_AGENT_AS_JUDGE``):
the deterministic rubric stays the default so no run puts live LLM calls on the
draft path unless it asks for them (P2 on-ramp preserved).

Fail-open is absolute: any LLM error, empty reply, or unparseable score falls
back to the injected deterministic scorer — NEVER a fabricated constant. A judge
that silently returned a fixed number would collapse the very constraint it
exists to widen (the fabricated_value failure class).
"""

from __future__ import annotations

import json
import logging
import math
import re
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

_EMPHASIS_MULTIPLIER = 2.0        # mirrors paper_runtime._EMPHASIS_MULTIPLIER
#: Minimum share of the rubric's total axis weight a judge reply must score for
#: its combination to count as a rubric verdict (below => fall back).
_MIN_AXIS_COVERAGE = 0.5
_DRAFT_CAP = 20000                # the draft is the judged artifact — keep it whole
_AUX_CAP = 4000                   # aux evidence fields (mirrors context_views._FIELD_CAP)


def _clamp01(x: float) -> float:
    """Bound to [0, 1], rejecting NaN/inf.

    ``json.loads`` accepts the bare ``NaN`` literal, and NaN survives naive
    clamping (both comparisons are False), producing a score that silently
    defeats EVERY downstream comparison — best-belief selection, the compile
    threshold, the audit record. Non-finite input is not a score."""
    if not math.isfinite(x):
        raise ValueError("non-finite score")
    return 1.0 if x >= 1.0 else (0.0 if x <= 0.0 else x)


#: The three evidence channels, mapped to the checkpoint file each is built
#: from. ``PaperArchiveRuntime._build_experiment`` stores these as PATH strings
#: (``_p(name)`` -> ``str(ckpt / name)``), because the paper SKILL resolves them
#: server-side. The judge renders its prompt in-process, so it must resolve them
#: itself — interpolating a path would put "/ckpt/science_data.json" in the
#: prompt where the measurements belong.
_EVIDENCE_FILES = {
    "verified_context": "verified_context.json",
    "science_data": "science_data.json",
    "reference_context": "related_refs.json",
}


def _resolve_evidence(value, checkpoint_dir, canonical_name: str) -> str:
    """Resolve one evidence channel to TEXT.

    ``value`` may be inline content, a path to the artifact, or empty. A path is
    READ; inline content passes through; an empty value falls back to the
    canonical file in ``checkpoint_dir``. Returns ``""`` when the evidence
    genuinely does not exist — honestly empty, never a stand-in."""
    text = str(value or "").strip()
    if text:
        # A path (what `_build_experiment` stores) — read it. Guarded by length
        # so a large inline JSON blob is never probed as a filename.
        if len(text) < 4096 and "\n" not in text:
            try:
                p = Path(text)
                if p.is_file():
                    return p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                pass
        return text                                   # inline content
    if checkpoint_dir:
        try:
            p = Path(checkpoint_dir) / canonical_name
            if p.is_file():
                return p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            pass
    return ""


def _paper_reviewer_string_view(
    *, draft_manuscript, verified_context, science_data, reference_context
) -> dict:
    """The paper_reviewer context as CAPPED STRINGS, keyed by exactly the
    kernel-enforced whitelist (``PAPER_REVIEWER_FIELDS``) so same-role isolation
    still holds — the view has no slot for another reviewer's output.
    ``build_paper_reviewer_context`` is the record
    projection for structured inputs; it maps a raw string to ``{}`` (``_plain``
    keeps only dicts), which silently dropped the draft body — the judge scored
    an empty manuscript. The archive's inputs ARE strings (a ``.tex`` draft,
    JSON evidence blobs), so the judge carries them as text under the same
    whitelisted keys, and asserts the key set to keep the isolation guarantee."""
    from ari.rqgm.context_views import PAPER_REVIEWER_FIELDS

    view = {
        "draft_manuscript": str(draft_manuscript or "")[:_DRAFT_CAP],
        "verified_context": str(verified_context or "")[:_AUX_CAP],
        "science_data": str(science_data or "")[:_AUX_CAP],
        "reference_context": str(reference_context or "")[:_AUX_CAP],
    }
    assert set(view) == set(PAPER_REVIEWER_FIELDS)   # same-role isolation
    return view


def _extract_json_object(text: str) -> "dict | None":
    """Best-effort parse of the first top-level JSON object in ``text``.

    LLM replies wrap JSON in prose or ```json fences; a bare ``json.loads`` of
    the whole reply fails on those. Returns ``None`` (=> caller falls back) when
    nothing parseable is found — it never guesses a score."""
    if not text:
        return None
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except Exception:
        pass
    # strip a ```json ... ``` fence if present
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(1))
            return obj if isinstance(obj, dict) else None
        except Exception:
            pass
    # first balanced-looking {...} span
    start = text.find("{")
    if start >= 0:
        depth = 0
        for i in range(start, len(text)):
            c = text[i]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(text[start:i + 1])
                        return obj if isinstance(obj, dict) else None
                    except Exception:
                        return None
    return None


def _combine(axis_scores: dict, axes: list, prompt_text: str) -> "float | None":
    """Weighted arithmetic mean of the judge's per-axis scores, on the SAME
    scale and emphasis-doubling the deterministic ``_rubric_draft_score`` uses,
    so judge and rubric are interchangeable on one axis set.

    ``None`` (=> caller falls back) when the reply covers less than
    :data:`_MIN_AXIS_COVERAGE` of the rubric's total weight. Without that floor a
    reply naming ONE low-weight axis produced a confident-looking score that
    best-belief selection consumed as if it were a full rubric verdict — a score
    over 1/13 of the rubric presented as the whole of it."""
    from ari.evaluator.dynamic_axes import axes_to_weights
    from ari.rqgm.paper_runtime import emphasised_axes

    weights = axes_to_weights(axes)
    emphasis = emphasised_axes(prompt_text, axes)
    total_weight = 0.0
    num = 0.0
    den = 0.0
    for axis in axes:
        name = getattr(axis, "name", "")
        weight = weights.get(name, 0.0) * (
            _EMPHASIS_MULTIPLIER if name in emphasis else 1.0
        )
        total_weight += weight
        if name not in axis_scores:
            continue
        try:
            read = _clamp01(float(axis_scores[name]))
        except (TypeError, ValueError):
            continue                      # unusable value (incl. NaN/inf)
        num += weight * read
        den += weight
    if den <= 0.0 or total_weight <= 0.0:
        return None
    if den / total_weight < _MIN_AXIS_COVERAGE:
        return None                       # too little of the rubric was scored
    return round(num / den, 6)


def _render_messages(prompt_text: str, context: dict, axes: list) -> list[dict]:
    from ari.evaluator.dynamic_axes import axes_to_prompt_section

    axis_block = axes_to_prompt_section(axes)
    # The ACTIVE governed reviewer prompt bytes are the EMPHASIS instruction —
    # this is what makes an evolved reviewer score differently, so the reviewer
    # role's co-evolution actually moves best-belief selection.
    emphasis_note = (prompt_text or "").strip() or (
        "Apply the venue's standard weighting across the axes."
    )
    system = (
        "You are a rigorous peer reviewer scoring ONE draft manuscript for a "
        "research venue. Score it on each rubric axis. Reply with ONE JSON "
        "object and nothing else."
    )
    user = (
        "REVIEWER EMPHASIS (how to weight the axes for THIS venue/role):\n"
        f"{emphasis_note}\n\n"
        "RUBRIC — reply with a JSON object of this shape:\n"
        "{\n" + axis_block + "\n}\n\n"
        "DRAFT MANUSCRIPT (LaTeX):\n"
        f"{context.get('draft_manuscript', '')}\n\n"
        "VERIFIED EVIDENCE the draft may cite (Layer-0 grounded):\n"
        f"{context.get('verified_context', '')}\n\n"
        "MEASUREMENTS backing the claims:\n"
        f"{context.get('science_data', '')}\n\n"
        "REFERENCE / RELATED WORK context:\n"
        f"{context.get('reference_context', '')}\n"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def deterministic_rubric_score_fn(
    axes: "list | None" = None,
) -> "Callable[[str, str], float]":
    """The LLM-free venue-rubric scorer as a ``(prompt_text, draft_text) ->
    float`` — the SAME combination ``GovernedPaperReviewer.score``'s else-branch
    runs (``_rubric_draft_score`` over the venue axes, structural base when the
    rubric declares no readable axis). This is the fail-open target for the
    agent-as-judge: when the LLM is unavailable the draft is still scored on the
    venue's own weighting, never a fabricated constant."""
    from ari.rqgm.paper_runtime import (
        _rubric_draft_score,
        _structural_score,
        _venue_rubric,
        draft_axes,
    )

    _axes = axes if axes is not None else draft_axes(_venue_rubric())

    def _fn(prompt_text: str, draft_text: str) -> float:
        rs = _rubric_draft_score(prompt_text, draft_text, _axes)
        return _structural_score(draft_text) if rs is None else rs

    return _fn


def build_agent_as_judge_score_fn(
    llm,
    *,
    experiment_data: "dict | None" = None,
    checkpoint_dir=None,
    axes: "list | None" = None,
    fallback_score_fn: "Callable[[str, str], float] | None" = None,
    max_tokens: "int | None" = None,
) -> "Callable[[str, str], float]":
    """Return an agent-as-judge ``score_fn(prompt_text, draft_text) -> float``.

    ``llm`` is a ``.complete``-shaped ``LLMClient``. ``experiment_data`` supplies
    the verified-context / science-data / reference-context the draft was written
    from (the kernel-scoped ``build_paper_reviewer_context`` inputs). ``axes``
    defaults to the active venue rubric's draft axes. ``fallback_score_fn`` is
    the deterministic scorer the judge degrades to on ANY failure — required for
    fail-open; if omitted, a failed judge returns ``0.0`` (still never a
    fabricated non-zero).

    The prompt text is the ACTIVE governed reviewer prompt: it is threaded into
    the judge as the emphasis instruction, so a co-evolved reviewer produces a
    genuinely different score, and the score reads axes — novelty,
    significance — that no deterministic reader can, breaking the ceiling."""
    exp = experiment_data or {}
    if axes is None:
        from ari.rqgm.paper_runtime import _venue_rubric, draft_axes
        axes = draft_axes(_venue_rubric())

    # Evidence resolved ONCE: these artifacts are frozen for the paper phase, and
    # `_build_experiment` hands them over as PATHS. Resolving per-draft would
    # re-read the same files for every score.
    _evidence = {
        channel: _resolve_evidence(
            exp.get(key, ""), checkpoint_dir, _EVIDENCE_FILES[channel],
        )
        for channel, key in (
            ("verified_context", "verified_context_json"),
            ("science_data", "science_data_json"),
            ("reference_context", "refs_json"),
        )
    }
    _empty = [c for c, v in _evidence.items() if not v]
    if _empty:
        # Announced, never silent: a judge scoring with no Layer-0 evidence
        # cannot check a claim, so `measurement_validity` / `comparative_rigor` /
        # `reproducibility` become ungrounded guesses that still drive
        # best-belief selection. The operator sees WHICH channel is missing.
        log.warning(
            "agent-as-judge: no content for %s (checkpoint_dir=%s) — those "
            "rubric axes will be judged from the draft body alone",
            ", ".join(sorted(_empty)), checkpoint_dir,
        )

    # Fail-open target: the caller's deterministic scorer, else the venue rubric
    # itself. NEVER a fabricated constant — a judge that fell back to a fixed
    # number would erase the discrimination it exists to add.
    _fallback_fn = (
        fallback_score_fn
        if fallback_score_fn is not None
        else deterministic_rubric_score_fn(axes)
    )

    def _fallback(prompt_text: str, draft_text: str, reason: str) -> float:
        score_fn.degraded += 1
        score_fn.last_source = f"rubric:{reason}"
        try:
            return _clamp01(float(_fallback_fn(prompt_text, draft_text)))
        except Exception:
            return 0.0

    def score_fn(prompt_text: str, draft_text: str) -> float:
        if not (draft_text or "").strip():
            # empty draft: no LLM spend
            return _fallback(prompt_text, draft_text, "empty_draft")
        evidence = dict(_evidence)
        fixed = str(getattr(score_fn, "manuscript_fixed_block", "") or "")
        if fixed:
            evidence["verified_context"] = (
                f"{evidence['verified_context']}\n\n{fixed}"
                if evidence["verified_context"]
                else fixed
            )
        context = _paper_reviewer_string_view(
            draft_manuscript=draft_text, **evidence,
        )
        messages = _render_messages(prompt_text, context, axes)
        kw = {"require_tool": False, "phase": "paper_judge"}
        if max_tokens:
            kw["max_tokens"] = int(max_tokens)
        try:
            resp = llm.complete(messages, **kw)
        except Exception as e:
            log.warning("agent-as-judge LLM call failed (%s); "
                        "falling back to deterministic rubric", e)
            return _fallback(prompt_text, draft_text, "llm_error")
        text = getattr(resp, "content", None) or ""
        obj = _extract_json_object(text)
        if obj is None:
            log.warning("agent-as-judge reply had no parseable JSON; "
                        "falling back to deterministic rubric")
            return _fallback(prompt_text, draft_text, "unparseable")
        axis_scores = obj.get("axis_scores")
        if not isinstance(axis_scores, dict):
            # tolerate a flat {axis: score} object too
            axis_scores = {k: v for k, v in obj.items()
                           if isinstance(v, (int, float))}
        combined = _combine(axis_scores, axes, prompt_text)
        if combined is None:
            log.warning(
                "agent-as-judge reply covered too little of the venue rubric "
                "(<%.0f%% of axis weight); falling back to deterministic rubric",
                _MIN_AXIS_COVERAGE * 100,
            )
            return _fallback(prompt_text, draft_text, "low_axis_coverage")
        score_fn.judged += 1
        score_fn.last_source = "judge"
        return combined

    # Provenance counters. A judge score and a fallback rubric score are the same
    # float to every consumer, so without these a run whose LLM was down for
    # EVERY call is indistinguishable from a fully judged one. `cli/paper_dispatch.py`
    # logs the tally after the archive so the degrade is durable in ari.log.
    score_fn.judged = 0
    score_fn.degraded = 0
    score_fn.last_source = None
    score_fn.manuscript_fixed_block = ""

    def _bind_manuscript_inputs(_binding: dict, fixed_block: str) -> None:
        score_fn.manuscript_fixed_block = str(fixed_block or "")

    score_fn.bind_manuscript_inputs = _bind_manuscript_inputs
    return score_fn
