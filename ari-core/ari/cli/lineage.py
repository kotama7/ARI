"""Lineage-decision helpers extracted from cli.py (Phase 3A).

Hosts the four pure helpers ``_run_loop`` and ``_resolve_cfg`` use to
decide what to do at the end of a BFTS phase: load lineage thresholds
(workflow.yaml + active rubric overlay), persist the
``parent_terminated`` flag, dispatch the chosen lineage action, and
build the §-tag-aware idea context for expand().

No behaviour changes — file split only.  Top-level CLI entry continues
to import these names from ``ari.cli`` for backwards compatibility.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from ari.pipeline import _extract_plan_sections


_LINEAGE_LOG = logging.getLogger("ari.cli.lineage")


def _load_lineage_decision_config() -> dict:
    """Read lineage_decision settings from workflow.yaml + active rubric.

    Schema in workflow.yaml::

        lineage_decision:
          mode: off | stagnation_rule | every_node   # default off
          stagnation_window: 5      # only used when mode = stagnation_rule
          stagnation_threshold: 0.02
          min_nodes_before_decision: 3
          rate_limit_per_run: 5     # max actions per run (cap)

    lineage decisions: the active rubric (``ARI_RUBRIC``) may override these
    via a ``lineage_thresholds:`` field, so different venues can tune
    when escalation fires (HPC kernel runs may need a longer window
    than ML training runs):

        # ari-core/config/reviewer_rubrics/<id>.yaml
        lineage_thresholds:
          stagnation_window: 8
          stagnation_threshold: 0.01
          min_nodes_before_decision: 5

    Precedence: rubric override > workflow.yaml > built-in defaults.
    """
    base: dict = {}
    try:
        import yaml as _yaml
        from ari.config.finder import package_config_root
        _candidates = [
            package_config_root() / "workflow.yaml",
            Path.cwd() / "config" / "workflow.yaml",
        ]
        for p in _candidates:
            if p.exists():
                base = (_yaml.safe_load(p.read_text()) or {}).get(
                    "lineage_decision", {}
                ) or {}
                break
    except Exception:
        base = {}

    # Overlay rubric-specific thresholds when present.
    try:
        rid = (os.environ.get("ARI_RUBRIC") or "").strip()
        if rid:
            import yaml as _yaml2
            from ari.config.finder import package_config_root
            rubric_path = (
                package_config_root()
                / "reviewer_rubrics" / f"{rid}.yaml"
            )
            if rubric_path.exists():
                rubric_data = _yaml2.safe_load(rubric_path.read_text()) or {}
                overrides = rubric_data.get("lineage_thresholds") or {}
                if isinstance(overrides, dict):
                    merged = dict(base)
                    for k in (
                        "stagnation_window",
                        "stagnation_threshold",
                        "min_nodes_before_decision",
                        "rate_limit_per_run",
                    ):
                        if k in overrides:
                            merged[k] = overrides[k]
                    base = merged
    except Exception:
        pass
    return base


def _mark_parent_terminated(parent_ckpt: Path, rationale: str) -> None:
    """lineage decisions: write parent_terminated=true into meta.json so any
    descendant run started later can decide whether to cancel itself.

    Existing children (already running) are not signalled — they have
    their own BFTS loops and their own lineage_decision hooks. The
    flag is purely a hint that propagates *forward* through future
    sub-experiment launches.
    """
    meta_p = parent_ckpt / "meta.json"
    try:
        meta = json.loads(meta_p.read_text()) if meta_p.exists() else {}
        if not isinstance(meta, dict):
            meta = {}
        meta["parent_terminated"] = True
        meta["parent_terminated_rationale"] = rationale[:300]
        meta_p.write_text(json.dumps(meta, indent=2))
    except Exception as _e_meta:
        _LINEAGE_LOG.warning("could not mark parent_terminated: %s", _e_meta)


def _execute_lineage_decision(
    decision,                    # LineageDecision
    *,
    parent_run_id: str,
    parent_ckpt: Path,
    experiment_data: dict,
) -> bool:
    """Carry out the LLM-chosen action via Phase 2.5 plumbing.

    Returns True iff the BFTS loop should stop expanding new nodes
    (the ``terminate`` action).
    """
    action = decision.action
    if action in ("continue", None, ""):
        return False
    if action == "terminate":
        _LINEAGE_LOG.info(
            "lineage decision: terminate (rationale=%s)", decision.rationale[:140]
        )
        # lineage decisions: persist the terminate signal in meta.json so
        # descendants spawned after this point can opt out.
        _mark_parent_terminated(parent_ckpt, decision.rationale)
        return True
    if action in ("switch_to_idea", "fanout"):
        if decision.target_idea_index is None:
            _LINEAGE_LOG.warning(
                "lineage decision: %s with no target_idea_index — skipping",
                action,
            )
            return False
        try:
            from ari.viz.api_orchestrator import _api_launch_sub_experiment
        except Exception as e:
            _LINEAGE_LOG.warning("lineage decision: import launch API failed: %s", e)
            return False
        body = {
            "experiment_md": (
                f"Auto-spawned by parent {parent_run_id} via lineage decision "
                f"({action}). Rationale: {decision.rationale[:300]}\n"
            ),
            "parent_run_id": parent_run_id,
            "inherit_idea_index": int(decision.target_idea_index),
        }
        if decision.disable_generate_ideas:
            # lineage decisions: child runs the inherited idea verbatim, no resampling.
            os.environ.setdefault("ARI_DISABLED_TOOLS_FOR_CHILD", "")
        try:
            res = _api_launch_sub_experiment(json.dumps(body).encode())
            _LINEAGE_LOG.info(
                "lineage decision: %s → child %s (rationale=%s)",
                action, res.get("run_id", "?"), decision.rationale[:140],
            )
        except Exception as e:
            _LINEAGE_LOG.warning("lineage decision: launch failed: %s", e)
        return False  # parent continues; child runs in parallel
    return False


def _build_idea_ctx_for_expand(idea_data: dict) -> str:
    """Build the BFTS-expand idea context with §-tag extraction.

    Replaces the legacy 400-char truncation that dropped §4-§6 of the
    VirSci experiment_plan (model calibration / comparisons), causing
    BFTS to never explore those branches. Each section title is always
    included; bodies are truncated only if the total context grows large.
    """
    ideas = idea_data.get("ideas") or []
    if not ideas:
        return ""
    best = ideas[0]
    gap = idea_data.get("gap_analysis", "")
    parts = [
        f"Gap: {gap[:1500]}",
        f"Idea: {best.get('title', '')}",
        f"Description: {best.get('description', '')[:2000]}",
    ]
    plan_text = best.get("experiment_plan", "")
    if plan_text:
        sections = _extract_plan_sections(plan_text)
        if sections:
            plan_lines = ["Plan sections:"]
            # Total body budget for the plan portion. Per-section trimming
            # falls back when overall context grows too large.
            per_section_budget = max(400, 6000 // max(1, len(sections)))
            for tag, title, body in sections:
                plan_lines.append(f"  {tag} {title}")
                if body:
                    plan_lines.append(f"    {body[:per_section_budget]}")
            parts.append("\n".join(plan_lines))
        else:
            parts.append(f"Plan: {plan_text[:4000]}")
    return "\n".join(parts)
