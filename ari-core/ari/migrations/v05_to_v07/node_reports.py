"""Legacy ``node_report.json`` reconstruction (Phase 5).

This module owns the v0.5 → v0.7 migration logic that
``ari/orchestrator/node_report.py`` historically held inline.  The
canonical file keeps a thin re-export at the same name so external
callers that ``from ari.orchestrator.node_report import
reconstruct_report_from_legacy`` keep working.
"""

from __future__ import annotations

import re
from pathlib import Path

from ari.orchestrator.node_report import (
    SCHEMA_VERSION,
    _artifact_to_record,
    compute_files_changed,
    extract_build_run_commands,
)


def reconstruct_report_from_legacy(
    *,
    node_dict: dict,
    work_dir: Path | None,
    parent_work_dir: Path | None,
) -> dict:
    """Best-effort migration: rebuild a node_report from a legacy tree.json
    node dict + on-disk work_dir. Fields we cannot recover are nulled.
    """
    if work_dir and work_dir.exists():
        files_changed = compute_files_changed(parent_work_dir, work_dir)
        build_cmd, run_cmd = extract_build_run_commands(work_dir)
    else:
        files_changed = {"added": [], "modified": [], "deleted": [], "inherited_unchanged": []}
        build_cmd, run_cmd = ("", "")

    artifacts_out: list[dict] = []
    for a in node_dict.get("artifacts") or []:
        rec = _artifact_to_record(a, work_dir or Path("."))
        if rec is not None:
            artifacts_out.append(rec)

    eval_summary = node_dict.get("eval_summary") or ""
    evaluator_reason = ""
    if eval_summary:
        # Strip trailing "[scientific_score=X.XX]" if present.
        evaluator_reason = re.sub(r"\s*\[scientific_score=[^\]]+\]\s*$", "", eval_summary).strip()

    return {
        "schema_version": SCHEMA_VERSION,
        "node_id": node_dict.get("id", ""),
        "parent_id": node_dict.get("parent_id"),
        "ancestor_ids": list(node_dict.get("ancestor_ids") or []),
        "label": str(node_dict.get("label") or "other"),
        "raw_label": str(node_dict.get("raw_label") or ""),
        "depth": int(node_dict.get("depth") or 0),
        "status": str(node_dict.get("status") or ""),
        "started_at": node_dict.get("created_at") or "",
        "completed_at": node_dict.get("completed_at") or "",
        "original_direction": None,
        "files_changed": files_changed,
        "what_was_done": "",
        "delta_vs_parent": "",
        "metrics": dict(node_dict.get("metrics") or {}),
        "self_assessment": {
            "succeeded": bool(node_dict.get("has_real_data")),
            "headline": evaluator_reason,
            "concerns": [],
        },
        "next_steps_hints": [],
        "build_command": build_cmd,
        "run_command": run_cmd,
        "artifacts": artifacts_out,
        "evaluator_reason": evaluator_reason,
        "trace_log_summary": "",
        "migration_source": "auto",
    }
