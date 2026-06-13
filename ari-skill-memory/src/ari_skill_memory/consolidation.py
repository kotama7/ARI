"""Consolidation — derive typed memory from a node_report (Phase 3 foundation).

``consolidate_from_node_report`` is a PURE function: node_report (+ work_dir
for hashing artifacts) -> a list of typed-memory specs. It does NOT write and
does NOT re-store node_report fields — each spec carries a ``node_report_ref``
pointer and minimal provenance refs (PLAN §2, §8.2).

The live wiring (call at node end + write via the typed MCP tools) is a thin
separate hook in ari-core; keeping the logic pure here makes it testable
against real node_reports without touching the node lifecycle.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .provenance import refs_from_node_report
from .writer import add_typed_memory

# Metric-name fragments that hint at a headline throughput/quality figure,
# in rough priority order. First numeric match becomes ``metric_ptr``.
_PRIMARY_METRIC_HINTS = ("gflop", "gb_per_s", "gb/s", "throughput", "speedup", "score")
_SUCCESS = {"success", "succeeded", "ok"}


def _primary_metric(metrics: dict) -> dict | None:
    numeric = {
        k: v for k, v in metrics.items()
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    }
    if not numeric:
        return None
    # First hint category with any match; within it pick the largest value
    # (e.g. multi-thread GFlops over the single-thread baseline) so the
    # headline figure is chosen, not an incidental T1 number.
    for hint in _PRIMARY_METRIC_HINTS:
        matches = {k: v for k, v in numeric.items() if hint in k.lower()}
        if matches:
            k = max(matches, key=lambda key: matches[key])
            return {"name": k, "value": float(matches[k])}
    k, v = next(iter(numeric.items()))
    return {"name": k, "value": float(v)}


def _summary_text(node_report: dict) -> str:
    sa = node_report.get("self_assessment") or {}
    return (
        (sa.get("headline") or "").strip()
        or (node_report.get("what_was_done") or "").strip()
        or (node_report.get("delta_vs_parent") or "").strip()
        or f"node {node_report.get('node_id', '')} report"
    )


def consolidate_from_node_report(
    node_report: dict,
    work_dir: str | Path,
    *,
    run_id: str | None = None,
) -> list[dict]:
    """Return typed-memory specs derived from one node_report (no writes).

    Each spec: ``{kind, text, metric_ptr?, artifact_refs, node_report_ref}``,
    ready to pass to ``writer.add_typed_memory`` / the typed MCP tools.
    """
    node_id = node_report.get("node_id", "")
    nrr = {"run_id": run_id, "node_id": node_id} if run_id else {"node_id": node_id}
    refs = refs_from_node_report(node_report, Path(work_dir))  # compute_missing baselines
    status = str(node_report.get("status", "")).lower()
    metrics = node_report.get("metrics") or {}
    headline = _summary_text(node_report)

    specs: list[dict] = []

    if status in _SUCCESS and metrics:
        specs.append({
            "kind": "experiment_result",
            "text": headline[:600],
            "metric_ptr": _primary_metric(metrics),
            "artifact_refs": refs,
            "node_report_ref": nrr,
        })
    elif status and status not in _SUCCESS:
        specs.append({
            "kind": "failure_case",
            "text": (headline or f"node {node_id} failed ({status})")[:600],
            "artifact_refs": refs,
            "node_report_ref": nrr,
        })

    # Reflection from the evaluator's forward-looking hints (low confidence,
    # never usable for paper claims). Derived from node_report, not the agent.
    hints = node_report.get("next_steps_hints") or []
    if hints:
        text = "; ".join(str(h) for h in hints)[:600]
        specs.append({
            "kind": "reflection",
            "text": text,
            "artifact_refs": [],
            "node_report_ref": nrr,
            "_confidence": 0.4,
        })

    return specs


def write_consolidated(backend: Any, node_id: str, specs: list[dict]) -> list[dict]:
    """Write consolidation specs via the typed writer (CoW: node_id is current).

    Returns the per-spec write results. Caller (ari-core hook) must have set
    ``$ARI_CURRENT_NODE_ID == node_id``.
    """
    out: list[dict] = []
    for spec in specs:
        extra = {}
        if "_confidence" in spec:
            extra["confidence"] = spec["_confidence"]
        out.append(
            add_typed_memory(
                backend,
                node_id,
                spec["kind"],
                spec["text"],
                metric_ptr=spec.get("metric_ptr"),
                artifact_refs=spec.get("artifact_refs"),
                node_report_ref=spec.get("node_report_ref"),
                extra=extra or None,
            )
        )
    return out
