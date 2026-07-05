"""LLM-driven lineage action decisions (lineage decisions).

A persistence helper (``append_decision_log``) writes every executed
decision to ``{checkpoint_dir}/lineage_decisions.jsonl`` so future runs
can analyse whether lineage decisions escalations correlated with outcome quality
and whether the LLM's rationales were sound.

ARI's pipeline already delegates many local choices to LLMs (idea
generation, node evaluation, BFTS expand selection, paper review). lineage decisions
adds one more: deciding what the *lineage as a whole* should do next.

Action set (deliberately restricted so the LLM cannot invent new behaviour):

    continue       — current idea is still productive; do nothing
    switch_to_idea — current idea is stagnating; switch to alternatives[N]
                     by spawning a child run with that idea pinned and
                     ``generate_ideas`` disabled
    fanout         — current idea succeeded; spawn a child run to explore
                     a specific alternative in parallel
    terminate      — research thread is exhausted; signal the run loop to
                     stop expanding new nodes

The execution mechanism reuses the Phase 2.5 synthetic-seed +
``disabled_tools`` plumbing; the only thing this module decides is *what*
to do, not *how*. Every output goes through ``_parse_decision`` which
validates the JSON shape and constrains ``target_idea_index`` to the
alternatives pool — invalid output silently falls back to ``continue``.

This module makes no fixed-rule decisions on its own. The trigger (when
to call ``decide_lineage_action``) is the orchestrator's responsibility.
A simple stagnation detector is provided for the conservative default
(lineage decision); the continuous-monitor mode (lineage decision) calls this module
after every BFTS step regardless and lets the LLM decide whether action
is needed.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import litellm

log = logging.getLogger(__name__)


VALID_ACTIONS: frozenset[str] = frozenset(
    {"continue", "switch_to_idea", "fanout", "terminate"}
)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class LineageState:
    """Snapshot of the current run's progress used to brief the judge LLM."""

    active_idea_title: str
    active_idea_index: int
    nodes_explored: int
    best_axis_scores: dict[str, float]
    recent_composite_scores: list[float]
    budget_remaining: int
    alternatives: list[dict]   # [{"index": int, "title": str, "summary": str, "overall_score": float}]
    # lineage decisions: parallel list of (label, id_suffix) pairs for the same
    # tail used by ``recent_composite_scores``. When multiple recent
    # nodes share the same label, ``id_suffix`` lets the LLM tell them
    # apart. Empty list means scores are shown without labels.
    recent_node_descriptors: list[dict] = field(default_factory=list)
    venue_constraints: str = ""
    ancestor_thread: str = ""
    notes: str = ""
    # lineage decisions: recursion budget. The LLM should avoid switch_to_idea /
    # fanout when the next child would exceed ``max_recursion_depth`` —
    # otherwise the launch API rejects it and the action is wasted.
    recursion_depth: int = 0
    max_recursion_depth: int = 3

    def to_prompt(self) -> str:
        """Render as a human-readable block for the LLM user message."""
        lines = [
            f"Active idea: ideas[{self.active_idea_index}] = {self.active_idea_title}",
            f"BFTS nodes explored: {self.nodes_explored}",
            f"BFTS budget remaining: {self.budget_remaining}",
            f"Recursion depth: {self.recursion_depth} / {self.max_recursion_depth}",
        ]
        if self.recursion_depth >= self.max_recursion_depth:
            lines.append(
                "⚠ At recursion limit — switch_to_idea / fanout would be "
                "rejected by the launch API. Prefer continue or terminate."
            )
        if self.recent_composite_scores:
            scores = self.recent_composite_scores[-10:]
            descs = self.recent_node_descriptors[-len(scores):] if self.recent_node_descriptors else []
            if descs and len(descs) == len(scores):
                # Render score with label + disambiguating id_suffix when
                # the same label repeats inside this tail (lineage decisions J).
                rendered = []
                for i, s in enumerate(scores):
                    d = descs[i]
                    label = d.get("label") or "?"
                    suffix = d.get("id_suffix") or ""
                    if suffix:
                        rendered.append(f"{label}#{suffix}={s:.3f}")
                    else:
                        rendered.append(f"{label}={s:.3f}")
                lines.append(
                    "Recent nodes (most recent right): " + ", ".join(rendered)
                )
            else:
                tail = ", ".join(f"{x:.3f}" for x in scores)
                lines.append(f"Recent composite scores (most recent right): [{tail}]")
        if self.best_axis_scores:
            ax = ", ".join(
                f"{k}={v:.2f}" for k, v in sorted(
                    self.best_axis_scores.items(), key=lambda kv: -kv[1]
                )[:8]
            )
            lines.append(f"Best per-axis scores: {ax}")
        if self.alternatives:
            lines.append("Alternatives in pool:")
            for alt in self.alternatives:
                idx = alt.get("index")
                title = (alt.get("title") or "")[:120]
                score = alt.get("overall_score", "")
                summary = (alt.get("summary") or "")[:200]
                lines.append(f"  - ideas[{idx}] (overall_score={score}): {title}")
                if summary:
                    lines.append(f"      summary: {summary}")
        if self.venue_constraints:
            lines.append(f"Venue constraints: {self.venue_constraints[:300]}")
        if self.ancestor_thread:
            lines.append(f"Ancestor research thread:\n{self.ancestor_thread[:1000]}")
        if self.notes:
            lines.append(f"Notes: {self.notes[:300]}")
        return "\n".join(lines)


@dataclass
class LineageDecision:
    """LLM's structured output. Always normalised by ``_parse_decision``."""

    action: str
    target_idea_index: int | None
    disable_generate_ideas: bool
    rationale: str
    raw: dict = field(default_factory=dict)

    @classmethod
    def fallback_continue(cls, reason: str) -> "LineageDecision":
        return cls(
            action="continue",
            target_idea_index=None,
            disable_generate_ideas=False,
            rationale=f"fallback: {reason}",
        )

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "target_idea_index": self.target_idea_index,
            "disable_generate_ideas": self.disable_generate_ideas,
            "rationale": self.rationale,
        }


def deterministic_stagnation_pivot(
    state: "LineageState",
    used_indexes: "set[int] | None" = None,
) -> "LineageDecision | None":
    """On CONFIRMED stagnation, switch to the strongest UNUSED alternative idea.

    Encodes the agreed policy — *when the active idea stagnates, try the next
    idea to break the plateau* — DETERMINISTICALLY, so a runner-up is actually
    tried instead of dying unused. The LLM judge prompt biases toward
    ``continue`` / ``terminate`` (least-disruptive), which tends to let
    runner-ups die; this picks the pivot for it when one is warranted.

    Returns ``None`` (defer continue-vs-terminate to the LLM judge) when no
    eligible alternative remains: budget exhausted, at the recursion limit, or
    every alternative has already been used. Caller must only invoke this when
    stagnation was actually detected (not in unconditional ``every_node`` mode).
    """
    used = used_indexes or set()
    if state.budget_remaining <= 0:
        return None
    if state.recursion_depth >= state.max_recursion_depth:
        return None
    candidates = [
        a for a in (state.alternatives or [])
        if isinstance(a.get("index"), int) and a["index"] not in used
    ]
    if not candidates:
        return None

    def _score(a: dict) -> float:
        s = a.get("overall_score")
        return float(s) if isinstance(s, (int, float)) else float("-inf")

    best = max(candidates, key=lambda a: (_score(a), -a["index"]))
    return LineageDecision(
        action="switch_to_idea",
        target_idea_index=int(best["index"]),
        disable_generate_ideas=True,
        rationale=(
            f"stagnation pivot (deterministic): switch to strongest unused "
            f"alternative ideas[{best['index']}] "
            f"'{(best.get('title') or '')[:60]}' (score={best.get('overall_score')})"
        ),
    )


# ---------------------------------------------------------------------------
# Parsing / validation
# ---------------------------------------------------------------------------


def _parse_decision(raw: str, state: LineageState) -> LineageDecision:
    """Extract JSON, validate ``action`` and ``target_idea_index``.

    Any malformed output silently falls back to ``continue`` — the worst
    case is "we keep exploring", which is the safe default.
    """
    if not raw:
        return LineageDecision.fallback_continue("empty LLM output")
    cleaned = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    m = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not m:
        return LineageDecision.fallback_continue("no JSON block")
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        return LineageDecision.fallback_continue(f"JSON parse error: {e}")
    if not isinstance(data, dict):
        return LineageDecision.fallback_continue("JSON not an object")

    action = str(data.get("action", "")).strip().lower()
    if action not in VALID_ACTIONS:
        return LineageDecision.fallback_continue(f"unknown action {action!r}")

    target_idx: int | None = None
    if action in ("switch_to_idea", "fanout"):
        raw_idx = data.get("target_idea_index")
        try:
            tidx = int(raw_idx) if raw_idx is not None else None
        except (TypeError, ValueError):
            return LineageDecision.fallback_continue("non-integer target_idea_index")
        if tidx is None:
            return LineageDecision.fallback_continue(
                f"action={action!r} requires target_idea_index"
            )
        valid_indexes = {a.get("index") for a in state.alternatives if a.get("index") is not None}
        if tidx not in valid_indexes:
            return LineageDecision.fallback_continue(
                f"target_idea_index={tidx} not in alternatives pool {sorted(valid_indexes)}"
            )
        target_idx = tidx

    disable_gi = bool(data.get("disable_generate_ideas", False))
    rationale = str(data.get("rationale", ""))[:500]

    return LineageDecision(
        action=action,
        target_idea_index=target_idx,
        disable_generate_ideas=disable_gi,
        rationale=rationale,
        raw=data,
    )


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------


# Phase PC4 (PROMPTS_AND_CONFIG.md §3-2): the system prompt body lives
# in ``ari/prompts/orchestrator/lineage_decision.md``.  ``_SYSTEM_PROMPT``
# stays available via PEP-562 ``__getattr__`` for any external caller
# that imports it directly.


def _load_system_prompt_versioned() -> tuple[str, str]:
    from ari.prompts import FilesystemPromptLoader
    return FilesystemPromptLoader().load_versioned("orchestrator/lineage_decision")


def _load_system_prompt() -> str:
    return _load_system_prompt_versioned()[0]


def __getattr__(name: str):  # PEP 562 — preserve ``_SYSTEM_PROMPT`` API.
    if name == "_SYSTEM_PROMPT":
        return _load_system_prompt()
    raise AttributeError(name)


_DEFAULTS_CACHE: dict | None = None


def _config_default(key: str, fallback: str) -> str:
    """Read a model default from the bundled ``configs/defaults.yaml``.

    Phase PC7 (PROMPTS_AND_CONFIG.md §3-7) externalises hard-coded
    fallbacks like ``"gpt-4o-mini"`` so ops can update venue defaults
    without a code change.  The lookup falls back to *fallback* if the
    YAML is missing — keeps the function pure and import-safe.
    """
    global _DEFAULTS_CACHE
    try:
        if _DEFAULTS_CACHE is None:
            from ari.configs import FilesystemConfigLoader
            data = FilesystemConfigLoader().load("defaults")
            _DEFAULTS_CACHE = data if isinstance(data, dict) else {}
        models = _DEFAULTS_CACHE.get("models") or {}
        v = models.get(key)
        if isinstance(v, str) and v:
            return v
    except Exception:
        pass
    return fallback


def _default_model() -> str:
    return (
        os.environ.get("ARI_MODEL_LINEAGE")
        or os.environ.get("ARI_MODEL_EVAL")
        or os.environ.get("ARI_MODEL")
        or os.environ.get("ARI_LLM_MODEL")
        or _config_default("lineage_decision_default", "gpt-4o-mini")
    )


async def decide_lineage_action(
    state: LineageState,
    *,
    model: str | None = None,
    api_base: str | None = None,
    temperature: float = 0.2,
) -> LineageDecision:
    """LLM judge over a ``LineageState``. Always returns a ``LineageDecision``.

    Failure modes (network / parse / unknown action / out-of-pool index)
    all degrade to ``continue`` so the BFTS loop never blocks on this hook.
    """
    user = state.to_prompt()
    _sys_text, _sys_hash = _load_system_prompt_versioned()
    _resolved_model = model or _default_model()
    kwargs: dict[str, Any] = {
        "model": _resolved_model,
        "messages": [
            {"role": "system", "content": _sys_text},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": 400,
        "metadata": {
            "phase": "lineage_decision",
            "skill": "lineage_decision",
        },
    }
    # Subtask 044: prompt provenance (byte-identical system prompt).
    from ari.prompts import record_prompt_use as _record_prompt_use
    _record_prompt_use(
        "orchestrator/lineage_decision", _sys_hash, rendered_text=_sys_text,
        model=_resolved_model, phase="lineage_decision",
    )
    if api_base:
        kwargs["api_base"] = api_base
    try:
        resp = await litellm.acompletion(**kwargs)
        raw = resp.choices[0].message.content or ""
    except Exception as e:
        log.warning("lineage_decision LLM call failed: %s", e)
        return LineageDecision.fallback_continue(f"LLM error: {e}")
    return _parse_decision(raw, state)


# ---------------------------------------------------------------------------
# Stagnation detector (lineage decision rule trigger)
# ---------------------------------------------------------------------------


def detect_stagnation(
    composite_scores: list[float],
    *,
    window: int = 5,
    threshold: float = 0.02,
) -> bool:
    """Return True when the last ``window`` composite scores show
    ``max - min`` below ``threshold``. This is the conservative default
    used by lineage decision to gate calls to ``decide_lineage_action``.

    Returning False from a too-short window is intentional — early in a
    run, "no improvement yet" is normal, not stagnation.
    """
    if window <= 0 or threshold < 0:
        return False
    if len(composite_scores) < window:
        return False
    tail = composite_scores[-window:]
    return (max(tail) - min(tail)) < threshold


# ---------------------------------------------------------------------------
# State builder from BFTS context
# ---------------------------------------------------------------------------


def _node_metric(node: Any, key: str) -> Any:
    metrics = getattr(node, "metrics", None)
    if metrics is None and isinstance(node, dict):
        metrics = node.get("metrics")
    if not isinstance(metrics, dict):
        return None
    return metrics.get(key)


def build_lineage_state(
    *,
    all_nodes: list,
    idea_data: dict,
    budget_remaining: int,
    venue_constraints: str = "",
    ancestor_thread: str = "",
    notes: str = "",
    recursion_depth: int = 0,
    max_recursion_depth: int = 3,
) -> LineageState:
    """Compose a ``LineageState`` from BFTS state + idea.json catalog."""
    ideas = idea_data.get("ideas") or []
    active = ideas[0] if ideas else {}
    alternatives: list[dict] = []
    for i, idea in enumerate(ideas[1:], start=1):
        alternatives.append(
            {
                "index": i,
                "title": idea.get("title", ""),
                "summary": idea.get("description", "") or "",
                "overall_score": idea.get("overall_score"),
            }
        )

    recent: list[float] = []
    recent_descs: list[dict] = []
    _label_seen: dict[str, int] = {}
    for n in all_nodes[-10:]:
        s = _node_metric(n, "_scientific_score")
        if not isinstance(s, (int, float)):
            continue
        recent.append(float(s))
        # lineage decisions: capture label + short id suffix; only emit suffix
        # when the label collides with something already in this tail.
        label = (
            getattr(n, "label", None)
            or (n.get("label") if isinstance(n, dict) else None)
            or "?"
        )
        node_id = (
            getattr(n, "id", None)
            or (n.get("id") if isinstance(n, dict) else None)
            or ""
        )
        _label_seen[label] = _label_seen.get(label, 0) + 1
        recent_descs.append({"label": str(label), "id_suffix": str(node_id)[-6:]})
    # Strip suffixes when no collisions within the tail (cleaner prompt).
    if all(_label_seen.get(d["label"], 0) <= 1 for d in recent_descs):
        for d in recent_descs:
            d["id_suffix"] = ""

    best_axes: dict[str, float] = {}
    for n in all_nodes:
        ax = _node_metric(n, "_axis_scores") or {}
        if not isinstance(ax, dict):
            continue
        for k, v in ax.items():
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            best_axes[k] = max(best_axes.get(k, 0.0), fv)

    return LineageState(
        active_idea_title=str(active.get("title", "")),
        active_idea_index=0,
        nodes_explored=len(all_nodes),
        best_axis_scores=best_axes,
        recent_composite_scores=recent,
        budget_remaining=int(max(0, budget_remaining)),
        alternatives=alternatives,
        recent_node_descriptors=recent_descs,
        venue_constraints=venue_constraints,
        ancestor_thread=ancestor_thread,
        notes=notes,
        recursion_depth=int(recursion_depth),
        max_recursion_depth=int(max_recursion_depth),
    )


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


_DECISION_LOG_FILENAME = "lineage_decisions.jsonl"


def _state_for_log(state: LineageState) -> dict:
    """Compact state representation suitable for jsonl persistence.

    Strips long context blocks (ancestor_thread, full descriptions) so the
    log stays readable when 5–10 decisions accumulate per run.
    """
    return {
        "active_idea_title": state.active_idea_title,
        "active_idea_index": state.active_idea_index,
        "nodes_explored": state.nodes_explored,
        "budget_remaining": state.budget_remaining,
        "best_axis_scores": dict(state.best_axis_scores),
        "recent_composite_scores": list(state.recent_composite_scores),
        "alternatives": [
            {
                "index": a.get("index"),
                "title": (a.get("title") or "")[:120],
                "overall_score": a.get("overall_score"),
            }
            for a in state.alternatives
        ],
        "venue_constraints_present": bool(state.venue_constraints),
        "ancestor_thread_present": bool(state.ancestor_thread),
    }


def append_decision_log(
    checkpoint_dir: str | Path,
    *,
    state: LineageState,
    decision: LineageDecision,
    trigger: str,
    executed: bool = True,
    extra: dict | None = None,
) -> bool:
    """Append a decision record to ``{ckpt}/lineage_decisions.jsonl``.

    Returns True iff the file was successfully appended; False on any
    error (filesystem / serialisation) — the caller's BFTS loop must
    not break on logging failures.

    The format is one JSON object per line so existing tooling can read
    incrementally without holding the whole file in memory. Records are
    deliberately self-contained (timestamp + state snapshot + action +
    rationale) so a downstream analysis can reconstruct each escalation
    without joining against other files.
    """
    record: dict[str, Any] = {
        "ts": time.time(),
        "ts_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "trigger": trigger,           # "stagnation_rule" / "every_node" / "manual"
        "executed": bool(executed),
        "state": _state_for_log(state),
        "decision": decision.to_dict(),
    }
    if extra:
        try:
            record["extra"] = dict(extra)
        except Exception:
            pass
    try:
        path = Path(checkpoint_dir) / _DECISION_LOG_FILENAME
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        return True
    except Exception as e:
        log.warning("append_decision_log failed: %s", e)
        return False


def read_decision_log(checkpoint_dir: str | Path) -> list[dict]:
    """Read all decision records (oldest first). Empty list on missing
    file or unreadable lines (skipped silently)."""
    path = Path(checkpoint_dir) / _DECISION_LOG_FILENAME
    if not path.exists():
        return []
    out: list[dict] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        return []
    return out
