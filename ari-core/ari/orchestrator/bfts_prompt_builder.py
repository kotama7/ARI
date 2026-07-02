"""Pure, deterministic prompt-context builders for BFTS (subtask 011 §7-A).

Extracts the heavy inline *context serialization* that used to live inside
:class:`ari.orchestrator.bfts.BFTS`'s ranking methods so that ``BFTS`` stays a
(near-)pure ranking/selection component:

- :func:`build_expand_context` — the ``expand()`` context blocks
  (sci_note / depth_note / budget_note + sibling / ancestor /
  existing-children / diversity blocks), returned as the ``str.format`` kwargs
  for ``ari/prompts/orchestrator/bfts_expand.md``.
- :func:`build_select_candidate_descriptions` — the per-candidate description
  lines for ``select_next_node`` (``bfts_select.md``).
- :func:`build_expand_select_candidate_descriptions` — the per-candidate
  description lines for ``select_best_to_expand`` (``bfts_expand_select.md``).

These functions are **pure** (no filesystem, no LLM, no ``BFTS`` state): every
input is passed explicitly, so identical inputs produce byte-identical strings
(design principle P2 / determinism). ``BFTS`` remains the sole LLM caller — the
builder returns *strings*, never model responses.

The shared :class:`_PromptBudget` / :data:`_BUDGET` truncation limits live here
(the lowest layer) and are re-imported by :mod:`ari.orchestrator.bfts` so the
existing ``ari.orchestrator.bfts._BUDGET`` access path keeps resolving.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ari.config import BFTSConfig
    from ari.orchestrator.node import Node


# ─────────────────────────────────────────
# Prompt budget (L-2): centralize the truncation/list limits used to keep
# expand() / select_next_node() prompts within model context windows.
# ─────────────────────────────────────────
@dataclass(frozen=True)
class _PromptBudget:
    parent_delta_chars: int = 240
    parent_concern_chars: int = 200
    parent_hint_chars: int = 200
    candidate_summary_select_chars: int = 120
    candidate_summary_expand_chars: int = 150
    sibling_direction_chars: int = 160
    list_top_n: int = 5


_BUDGET = _PromptBudget()


def build_select_candidate_descriptions(
    candidates: list[Node], diversity_bonuses: list[float]
) -> list[str]:
    """Return the per-candidate description lines for ``select_next_node``.

    ``diversity_bonuses`` must be aligned with ``candidates`` (the caller
    computes ``BFTS.diversity_bonus`` per node so this builder stays pure).
    """
    candidate_descriptions = []
    for i, node in enumerate(candidates):
        metrics_str = (
            json.dumps(node.metrics, ensure_ascii=False)
            if node.metrics else "not_yet_measured"
        )
        bonus = diversity_bonuses[i]
        bonus_note = f", diversity_bonus=+{bonus:.2f}" if bonus > 0 else ""
        label_str = (
            node.label.value if hasattr(node.label, "value") else str(node.label or "?")
        )
        desc = (
            f"[{i}] id={node.id[-8:]}, depth={node.depth}, "
            f"label={label_str}, "
            f"has_real_data={node.has_real_data}, "
            f"metrics={metrics_str}, "
            f"summary={repr((node.eval_summary or 'none')[: _BUDGET.candidate_summary_select_chars])}"
            f"{bonus_note}"
        )
        candidate_descriptions.append(desc)
    return candidate_descriptions


def build_expand_select_candidate_descriptions(frontier: list[Node]) -> list[str]:
    """Return the per-candidate description lines for ``select_best_to_expand``."""
    candidate_descriptions = []
    for i, node in enumerate(frontier):
        metrics_str = (
            json.dumps(node.metrics, ensure_ascii=False)
            if node.metrics else "not_yet_measured"
        )
        desc = (
            f"[{i}] id={node.id[-8:]}, depth={node.depth}, "
            f"label={node.label.value if node.label else 'unknown'}, "
            f"has_real_data={node.has_real_data}, "
            f"metrics={metrics_str}, "
            f"summary={repr((node.eval_summary or 'none')[: _BUDGET.candidate_summary_expand_chars])}"
        )
        candidate_descriptions.append(desc)
    return candidate_descriptions


def build_expand_context(
    node: Node,
    config: BFTSConfig,
    *,
    experiment_goal: str = "",
    idea_context: str = "",
    siblings: list[Node] | None = None,
    ancestors: list[Node] | None = None,
    all_run_nodes: list[Node] | None = None,
    existing_children: list[Node] | None = None,
    budget_remaining: int | None = None,
    parent_report_block: str = "",
    sibling_reports: dict[str, dict] | None = None,
) -> dict[str, Any]:
    """Return the ``str.format`` kwargs for ``orchestrator/bfts_expand.md``.

    Pure serialization of every context block ``expand()`` used to inline. The
    two filesystem-derived inputs (``parent_report_block`` from
    ``_format_parent_report_block`` and ``sibling_reports`` from
    ``_load_sibling_node_reports``) are resolved by the caller and passed in, so
    this builder performs no I/O.
    """
    sibling_reports = sibling_reports or {}
    parent_status = "succeeded" if node.has_real_data else "failed/no-real-data"
    goal_line = f"Experiment goal: {experiment_goal}\n" if experiment_goal else ""
    sci_score = (node.metrics or {}).get("_scientific_score")
    sci_note = (
        f"Parent scientific score: {sci_score:.2f}/1.0\n"
        if sci_score is not None
        else "Parent scientific score: not yet evaluated\n"
    )
    idea_block = (
        f"\nResearch direction (from upstream idea generation):\n{idea_context}\n"
        if idea_context
        else ""
    )

    # I-4: depth and budget signals to the planner.
    depth_note = (
        f"Current depth: {node.depth} / max_depth {config.max_depth} "
        f"(child will be at depth {node.depth + 1})\n"
    )
    budget_note = (
        f"Remaining node budget: {budget_remaining} / {config.max_total_nodes}\n"
        if budget_remaining is not None
        else ""
    )

    # ── Sibling scores at same depth ──
    sibling_lines: list[str] = []
    for s in siblings or []:
        if s.id == node.id:
            continue
        ss = (s.metrics or {}).get("_scientific_score")
        sl = s.label.value if hasattr(s.label, "value") else str(s.label or "?")
        sibling_lines.append(
            f"  - id={s.id[-8:]} label={sl} score="
            + (f"{float(ss):.2f}" if ss is not None else "n/a")
        )
    siblings_block = (
        "Sibling scores at same depth:\n" + "\n".join(sibling_lines) + "\n\n"
        if sibling_lines
        else "Sibling scores at same depth: (none)\n\n"
    )

    # ── Ancestor scores (root → parent) ──
    ancestor_lines: list[str] = []
    for a in ancestors or []:
        ass = (a.metrics or {}).get("_scientific_score")
        al = a.label.value if hasattr(a.label, "value") else str(a.label or "?")
        ancestor_lines.append(
            f"  - depth={a.depth} id={a.id[-8:]} label={al} score="
            + (f"{float(ass):.2f}" if ass is not None else "n/a")
        )
    ancestors_block = (
        "Ancestor scores:\n" + "\n".join(ancestor_lines) + "\n\n"
        if ancestor_lines
        else "Ancestor scores: (none)\n\n"
    )

    # ── Already-spawned children of this parent (avoid duplicating) ──
    sibling_label_counts: Counter = Counter()
    existing_lines: list[str] = []
    for c in (existing_children or []):
        cl = c.label.value if hasattr(c.label, "value") else str(c.label or "?")
        sibling_label_counts[cl] += 1
        cdir = (c.eval_summary or "").strip().replace("\n", " ")
        cstatus = c.status.value if hasattr(c.status, "value") else str(c.status or "?")
        cscore = (c.metrics or {}).get("_scientific_score")
        score_part = f" score={float(cscore):.2f}" if isinstance(cscore, (int, float)) else ""
        line = (
            f"  - id={c.id[-8:]} label={cl} status={cstatus}{score_part}"
            f" direction={repr(cdir[: _BUDGET.sibling_direction_chars])}"
        )
        rep = sibling_reports.get(c.id)
        if rep:
            fc = rep.get("files_changed") or {}
            added = [e.get("path") for e in (fc.get("added") or [])][: _BUDGET.list_top_n]
            if added:
                line += f" files_added={added}"
        existing_lines.append(line)

    if existing_lines:
        label_dist_str = ", ".join(
            f"{lbl}={cnt}" for lbl, cnt in sorted(sibling_label_counts.items())
        )
        # L-6: saturation threshold is now a config knob, default 2.
        threshold = int(getattr(config, "label_saturation_threshold", 2) or 2)
        saturated = sorted(
            lbl for lbl, cnt in sibling_label_counts.items() if cnt >= threshold
        )
        quota_lines = [
            f"  label distribution among THIS parent's existing children: "
            f"{{{label_dist_str}}}"
        ]
        if saturated:
            quota_lines.append(
                f"  labels already saturated (≥{threshold} appearances): {saturated} — "
                "propose a DIFFERENT label unless you have a strong scientific "
                "reason to repeat one of these."
            )
        existing_block = (
            "Already-spawned children of THIS parent (do NOT duplicate these "
            "directions; propose something complementary):\n"
            + "\n".join(existing_lines) + "\n"
            + "\n".join(quota_lines) + "\n\n"
        )
    else:
        existing_block = (
            "Already-spawned children of THIS parent: "
            "(none — this is the first child)\n\n"
        )

    # ── Tree diversity metrics ──
    seen_labels: list[str] = []
    depth_counts: dict[int, int] = {}
    for n in all_run_nodes or []:
        try:
            lbl = n.label.value if hasattr(n.label, "value") else str(n.label or "")
        except Exception:
            lbl = ""
        if lbl and lbl not in seen_labels:
            seen_labels.append(lbl)
        try:
            d = int(getattr(n, "depth", 0) or 0)
        except (TypeError, ValueError):
            d = 0
        depth_counts[d] = depth_counts.get(d, 0) + 1
    diversity_block = (
        "Tree diversity so far:\n"
        f"  unique labels observed: {seen_labels if seen_labels else '(none)'}\n"
        f"  depth distribution: {depth_counts if depth_counts else '(empty)'}\n\n"
    )

    return {
        "goal_line": goal_line,
        "parent_id_short": node.id[-8:],
        "parent_depth": node.depth,
        "parent_status": parent_status,
        "depth_note": depth_note,
        "budget_note": budget_note,
        "parent_metrics_json": json.dumps(node.metrics, ensure_ascii=False),
        "parent_summary": node.eval_summary or 'none',
        "sci_note": sci_note,
        "idea_block": idea_block,
        "parent_report_block": parent_report_block,
        "siblings_block": siblings_block,
        "ancestors_block": ancestors_block,
        "existing_block": existing_block,
        "diversity_block": diversity_block,
    }
