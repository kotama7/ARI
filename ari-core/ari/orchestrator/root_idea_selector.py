"""LLM-driven root idea selection (lineage decision).

VirSci sorts ideas by ``novelty*2 + feasibility + clarity`` and the
pipeline blindly takes ``ideas[0]`` as the directive. That is reasonable
when the only signal is VirSci's internal scoring, but the lineage often
has more context — venue rubric, ancestor research thread, memory hints
— that VirSci itself doesn't see.

This module asks an LLM to pick which idea should be the run's root,
given that wider context. The LLM may pick ``ideas[0]`` (preserving
VirSci's choice), or promote ``ideas[1]``/``ideas[2]`` to the root.

Crucially, the *axes* used to score nodes are NOT touched here — root
selection is a one-shot decision at run start, not a continuous
re-weighting (lineage decision, deliberately not implemented). This keeps node
scores comparable within a run.

The chosen index is returned to the caller; reordering of idea.json
happens in ``apply_root_choice`` so the caller can audit / log the
decision before persisting.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import litellm

log = logging.getLogger(__name__)


@dataclass
class RootChoice:
    """LLM's structured output for root-idea selection."""

    chosen_index: int
    rationale: str
    raw: dict


def _default_model() -> str:
    return (
        os.environ.get("ARI_MODEL_ROOT_SELECT")
        or os.environ.get("ARI_MODEL_LINEAGE")
        or os.environ.get("ARI_MODEL")
        or os.environ.get("ARI_LLM_MODEL")
        or "gpt-4o-mini"
    )


# Phase PC4 (PROMPTS_AND_CONFIG.md §3-3): the system prompt body lives
# in ``ari/prompts/orchestrator/root_idea_selector.md``.


def _load_system_prompt_versioned() -> tuple[str, str]:
    from ari.prompts import FilesystemPromptLoader
    return FilesystemPromptLoader().load_versioned("orchestrator/root_idea_selector")


def _load_system_prompt() -> str:
    return _load_system_prompt_versioned()[0]


def __getattr__(name: str):  # PEP 562 — preserve ``_SYSTEM_PROMPT`` API.
    if name == "_SYSTEM_PROMPT":
        return _load_system_prompt()
    raise AttributeError(name)


def _format_pool(idea_data: dict) -> str:
    ideas = idea_data.get("ideas") or []
    if not ideas:
        return "(no ideas)"
    lines = []
    for i, idea in enumerate(ideas):
        title = (idea.get("title") or "")[:140]
        score = idea.get("overall_score", "")
        desc = (idea.get("description") or "")[:280]
        plan = (idea.get("experiment_plan") or "")[:200]
        lines.append(f"[{i}] (overall_score={score}) {title}")
        if desc:
            lines.append(f"     {desc}")
        if plan:
            lines.append(f"     plan: {plan}")
    return "\n".join(lines)


def _parse_choice(raw: str, n_ideas: int) -> RootChoice:
    """Parse LLM JSON; on any failure default to ``chosen_index=0``."""
    if not raw or n_ideas <= 0:
        return RootChoice(chosen_index=0, rationale="fallback: empty input", raw={})
    cleaned = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    m = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not m:
        return RootChoice(chosen_index=0, rationale="fallback: no JSON", raw={})
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        return RootChoice(chosen_index=0, rationale=f"fallback: JSON err {e}", raw={})
    if not isinstance(data, dict):
        return RootChoice(chosen_index=0, rationale="fallback: not object", raw={})
    raw_idx = data.get("chosen_index")
    try:
        idx = int(raw_idx)
    except (TypeError, ValueError):
        return RootChoice(chosen_index=0, rationale="fallback: bad index", raw=data)
    if idx < 0 or idx >= n_ideas:
        return RootChoice(
            chosen_index=0,
            rationale=f"fallback: index {idx} out of range",
            raw=data,
        )
    rationale = str(data.get("rationale", ""))[:500]
    return RootChoice(chosen_index=idx, rationale=rationale, raw=data)


async def select_root_idea(
    idea_data: dict,
    *,
    venue_constraints: str = "",
    ancestor_thread: str = "",
    notes: str = "",
    model: str | None = None,
    api_base: str | None = None,
    temperature: float = 0.2,
) -> RootChoice:
    """Ask the LLM to pick which idea should be ideas[0] for BFTS.

    Returns ``RootChoice(chosen_index=0, ...)`` when the call fails or the
    LLM's output is malformed — preserving VirSci's default ordering as
    the safe fallback.
    """
    ideas = idea_data.get("ideas") or []
    if len(ideas) <= 1:
        # Nothing to choose from; default to 0.
        return RootChoice(
            chosen_index=0, rationale="single-idea pool, no selection needed", raw={}
        )

    pool_block = _format_pool(idea_data)
    user_lines = [f"Pool of {len(ideas)} ideas:\n{pool_block}"]
    if venue_constraints:
        user_lines.append(f"\nVenue constraints:\n{venue_constraints[:500]}")
    if ancestor_thread:
        user_lines.append(f"\nAncestor research thread:\n{ancestor_thread[:1500]}")
    if notes:
        user_lines.append(f"\nNotes: {notes[:300]}")
    user = "\n".join(user_lines)

    _sys_text, _sys_hash = _load_system_prompt_versioned()
    _resolved_model = model or _default_model()
    kwargs: dict[str, Any] = {
        "model": _resolved_model,
        "messages": [
            {"role": "system", "content": _sys_text},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": 250,
        "metadata": {
            "phase": "root_idea_selection",
            "skill": "root_idea_selector",
        },
    }
    # Subtask 044: prompt provenance (byte-identical system prompt).
    from ari.prompts import record_prompt_use as _record_prompt_use
    _record_prompt_use(
        "orchestrator/root_idea_selector", _sys_hash, rendered_text=_sys_text,
        model=_resolved_model, phase="root_idea_selection",
    )
    if api_base:
        kwargs["api_base"] = api_base

    try:
        resp = await litellm.acompletion(**kwargs)
        raw = resp.choices[0].message.content or ""
    except Exception as e:
        log.warning("root_idea_selector LLM call failed: %s", e)
        return RootChoice(
            chosen_index=0, rationale=f"fallback: LLM error {e}", raw={}
        )

    return _parse_choice(raw, n_ideas=len(ideas))


def append_root_selection_log(
    checkpoint_dir: str | Path,
    *,
    pool_size: int,
    choice: RootChoice,
    swapped: bool,
) -> bool:
    """Append a root-selection record to ``{ckpt}/lineage_decisions.jsonl``.

    Shares the same file as ``decide_lineage_action`` records so analysis
    tooling has a single source of truth for lineage decisions LLM decisions. The
    ``trigger`` field disambiguates record types.

    Returns True iff the file was successfully appended.
    """
    import time as _time
    record: dict = {
        "ts": _time.time(),
        "ts_iso": _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime()),
        "trigger": "root_idea_selection",
        "executed": bool(swapped),
        "decision": {
            "action": "root_swap" if swapped else "root_keep",
            "chosen_index": int(choice.chosen_index),
            "rationale": choice.rationale[:500],
        },
        "extra": {"pool_size": int(pool_size)},
    }
    try:
        path = Path(checkpoint_dir) / "lineage_decisions.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        return True
    except Exception as e:
        log.warning("append_root_selection_log failed: %s", e)
        return False


def apply_root_choice(
    idea_path: str | Path,
    chosen_index: int,
    *,
    rationale: str = "",
) -> bool:
    """Reorder ``idea.json`` so ``ideas[chosen_index]`` becomes ``ideas[0]``.

    Returns True iff the file was rewritten (i.e. ``chosen_index != 0``).
    Leaves a ``_root_choice`` provenance field at the top level so future
    readers can see what the LLM picked and why.

    No-ops on missing file, malformed JSON, or out-of-range index.
    """
    p = Path(idea_path)
    if not p.exists():
        return False
    try:
        data = json.loads(p.read_text())
    except Exception as e:
        log.warning("apply_root_choice: malformed idea.json at %s: %s", p, e)
        return False
    ideas = data.get("ideas") if isinstance(data, dict) else None
    if not isinstance(ideas, list) or not ideas:
        return False
    if chosen_index <= 0 or chosen_index >= len(ideas):
        return False
    new_ideas = list(ideas)
    new_ideas[0], new_ideas[chosen_index] = new_ideas[chosen_index], new_ideas[0]
    data["ideas"] = new_ideas
    data["_root_choice"] = {
        "chosen_index": int(chosen_index),
        "swapped_with": 0,
        "rationale": rationale[:500],
    }
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    return True
