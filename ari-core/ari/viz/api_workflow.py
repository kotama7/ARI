from __future__ import annotations
"""ARI viz: api_workflow — React Flow workflow editor endpoints and converters."""

import json
import logging
from pathlib import Path

from . import state as _st

log = logging.getLogger(__name__)

# ── YAML ↔ React Flow converters ──────────────────


def workflow_yaml_to_flow(yaml_data: dict) -> dict:
    """Convert workflow YAML data to React Flow nodes/edges format.

    Parameters
    ----------
    yaml_data : dict
        Parsed workflow.yaml content (must contain ``bfts_pipeline`` and/or
        ``pipeline``).

    Returns
    -------
    dict
        ``{"nodes": [...], "edges": [...]}`` in React Flow format.
    """
    nodes = []
    edges = []
    bfts_pipeline = yaml_data.get("bfts_pipeline") or []
    paper_pipeline = yaml_data.get("pipeline") or []
    # Connect BFTS → Paper: paper stages with empty depends_on
    # link to the last BFTS stage (same logic as api_settings).
    # These auto-bridge edges are marked so they can be stripped on save.
    auto_bridge_edges: set[tuple[str, str]] = set()
    if bfts_pipeline:
        last_bfts = bfts_pipeline[-1]["stage"]
        paper_pipeline = [dict(s) for s in paper_pipeline]
        for s in paper_pipeline:
            if not s.get("depends_on"):
                s["depends_on"] = [last_bfts]
                auto_bridge_edges.add((last_bfts, s["stage"]))

    all_stages = bfts_pipeline + paper_pipeline

    # ── Layout: position BFTS and paper as separate swim-lanes ──
    col_w, row_h = 260, 120
    phase_gap_y = 180  # vertical gap between BFTS and paper lanes

    def _compute_levels(stages: list[dict]) -> dict[str, int]:
        """Compute topological depth for a list of stages."""
        stage_set = {s["stage"] for s in stages}
        dep_map: dict[str, list[str]] = {}
        for s in stages:
            dep_map[s["stage"]] = [
                d for d in (s.get("depends_on") or []) if d in stage_set
            ]
        levels: dict[str, int] = {}
        def _lv(st: str) -> int:
            if st in levels:
                return levels[st]
            deps = dep_map.get(st) or []
            lv = 0 if not deps else max(_lv(d) + 1 for d in deps)
            levels[st] = lv
            return lv
        for s in stages:
            _lv(s["stage"])
        return levels

    def _layout_pipeline(stages: list[dict], y_offset: int) -> None:
        """Position stages in a DAG layout at the given y offset."""
        levels = _compute_levels(stages)
        col_row: dict[int, int] = {}
        for s in stages:
            lv = levels.get(s["stage"], 0)
            row = col_row.get(lv, 0)
            col_row[lv] = row + 1
            nodes.append({
                "id": s["stage"],
                "type": "phase",
                "position": {"x": lv * col_w, "y": y_offset + row * row_h},
                "data": {
                    "label": s["stage"].replace("_", " ").title(),
                    "skill": s.get("skill", ""),
                    "enabled": s.get("enabled", True),
                    "tool": s.get("tool", ""),
                    "phase": s.get("phase", ""),
                    "description": s.get("description", ""),
                },
            })

    # BFTS lane at top (y=0)
    bfts_max_rows = 1
    if bfts_pipeline:
        _layout_pipeline(bfts_pipeline, 0)
        bfts_levels = _compute_levels(bfts_pipeline)
        col_counts: dict[int, int] = {}
        for s in bfts_pipeline:
            lv = bfts_levels[s["stage"]]
            col_counts[lv] = col_counts.get(lv, 0) + 1
        bfts_max_rows = max(col_counts.values()) if col_counts else 1

    # Paper lane below BFTS
    paper_y = bfts_max_rows * row_h + phase_gap_y if bfts_pipeline else 0
    if paper_pipeline:
        _layout_pipeline(paper_pipeline, paper_y)

    # ── Create edges from all stages ──
    for s in all_stages:
        for dep in s.get("depends_on") or []:
            condition = "always"
            edge_data: dict = {"condition": condition}
            if (dep, s["stage"]) in auto_bridge_edges:
                edge_data["auto_bridge"] = True
            edges.append({
                "id": f"e-{dep}-{s['stage']}",
                "source": dep,
                "target": s["stage"],
                "data": edge_data,
            })

        # Loop-back edge (routed via bottom handles)
        if s.get("loop_back_to"):
            edges.append({
                "id": f"e-loop-{s['stage']}-{s['loop_back_to']}",
                "source": s["stage"],
                "target": s["loop_back_to"],
                "sourceHandle": "loop-out",
                "targetHandle": "loop-in",
                "data": {"condition": "loop"},
                "animated": True,
            })

    return {"nodes": nodes, "edges": edges}


# Fields that React Flow carries — only these are updated from the flow editor.
_FLOW_FIELDS = {"stage", "skill", "tool", "description", "depends_on", "enabled", "phase", "loop_back_to"}


def _merge_stages(existing: list[dict], from_flow: list[dict]) -> list[dict]:
    """Merge React Flow stage data into existing YAML stages.

    Preserves fields that the flow editor doesn't carry (inputs, outputs,
    skip_if_exists, load_inputs, loop_threshold, loop_max_iterations, etc.)
    while updating the fields that it does (enabled, depends_on, skill, etc.).

    New stages from the flow editor are appended as-is.
    Stages removed from the flow editor are dropped.
    """
    existing_by_name = {s["stage"]: dict(s) for s in existing}
    flow_names = {s["stage"] for s in from_flow}

    merged = []
    for fs in from_flow:
        name = fs["stage"]
        if name in existing_by_name:
            # Start from existing (keeps inputs, outputs, etc.)
            stage = existing_by_name[name]
            # Overwrite only fields the flow editor manages
            for k in _FLOW_FIELDS:
                if k in fs:
                    stage[k] = fs[k]
            merged.append(stage)
        else:
            # New stage from flow editor — take as-is
            merged.append(fs)
    return merged


def flow_to_workflow_yaml(flow_data: dict) -> dict:
    """Convert React Flow nodes/edges back to workflow YAML structure.

    Parameters
    ----------
    flow_data : dict
        ``{"nodes": [...], "edges": [...]}`` from React Flow.

    Returns
    -------
    dict
        ``{"bfts_pipeline": [...], "pipeline": [...]}`` suitable for
        merging back into workflow.yaml.
    """
    nodes_by_id: dict[str, dict] = {}
    for n in flow_data.get("nodes") or []:
        nodes_by_id[n["id"]] = n

    # Build dependency map from edges
    deps: dict[str, list[str]] = {}
    loop_backs: dict[str, str] = {}
    edge_conditions: dict[str, str] = {}

    for e in flow_data.get("edges") or []:
        src = e.get("source", "")
        tgt = e.get("target", "")
        cond = (e.get("data") or {}).get("condition", "always")

        if cond == "loop":
            loop_backs[src] = tgt
            continue

        # Skip auto-bridge edges (BFTS→Paper) — they are re-generated on load
        if (e.get("data") or {}).get("auto_bridge"):
            continue

        deps.setdefault(tgt, []).append(src)
        edge_conditions[f"{src}->{tgt}"] = cond

    bfts_stages = []
    paper_stages = []

    for n in flow_data.get("nodes") or []:
        nid = n["id"]
        data = n.get("data") or {}
        phase = data.get("phase", "")

        stage = {
            "stage": nid,
            "skill": data.get("skill", ""),
            "tool": data.get("tool", ""),
            "description": data.get("description", ""),
            "depends_on": deps.get(nid, []),
            "enabled": data.get("enabled", True),
            "phase": phase,
        }

        if nid in loop_backs:
            stage["loop_back_to"] = loop_backs[nid]

        if phase == "bfts":
            bfts_stages.append(stage)
        else:
            paper_stages.append(stage)

    return {"bfts_pipeline": bfts_stages, "pipeline": paper_stages}


# ── API handlers ─────────────────────────────────


def _api_get_workflow_flow() -> dict:
    """GET /api/workflow/flow — Return current workflow as React Flow JSON."""
    import yaml

    wf_candidates = [
        Path(__file__).parent.parent.parent / "config" / "workflow.yaml",
        Path(__file__).parent.parent.parent.parent / "config" / "workflow.yaml",
    ]
    if _st._checkpoint_dir:
        wf_candidates.insert(0, _st._checkpoint_dir / "workflow.yaml")

    for wf in wf_candidates:
        if wf.exists():
            try:
                data = yaml.safe_load(wf.read_text())
                flow = workflow_yaml_to_flow(data)
                return {"ok": True, "flow": flow, "path": str(wf)}
            except Exception as e:
                return {"ok": False, "error": str(e)}

    return {"ok": False, "error": "workflow.yaml not found"}


def _api_save_workflow_flow(body: bytes) -> dict:
    """POST /api/workflow/flow — Save React Flow JSON back to workflow.yaml."""
    import yaml

    data = json.loads(body)
    flow = data.get("flow")
    if not flow:
        return {"ok": False, "error": "missing flow data", "_status": 400}

    # Convert back to YAML structure
    yaml_parts = flow_to_workflow_yaml(flow)

    # Locate source workflow
    wf_candidates = [
        Path(__file__).parent.parent.parent / "config" / "workflow.yaml",
        Path(__file__).parent.parent.parent.parent / "config" / "workflow.yaml",
    ]
    if _st._checkpoint_dir:
        wf_candidates.insert(0, _st._checkpoint_dir / "workflow.yaml")

    for wf in wf_candidates:
        if wf.exists():
            try:
                existing = yaml.safe_load(wf.read_text()) or {}
                # Merge flow changes into existing stages, preserving fields
                # that React Flow doesn't carry (inputs, outputs, skip_if_exists, etc.)
                existing["bfts_pipeline"] = _merge_stages(
                    existing.get("bfts_pipeline") or [], yaml_parts["bfts_pipeline"],
                )
                existing["pipeline"] = _merge_stages(
                    existing.get("pipeline") or [], yaml_parts["pipeline"],
                )
                wf.write_text(yaml.dump(existing, allow_unicode=True, sort_keys=False))
                return {"ok": True}
            except Exception as e:
                return {"ok": False, "error": str(e)}

    return {"ok": False, "error": "workflow.yaml not found"}


def _api_save_skill_phases(body: bytes) -> dict:
    """POST /api/workflow/skills — Update skill phase assignments in workflow.yaml.

    Expected body: {"skills": [{"name": "web-skill", "phase": "all"}, ...]}
    """
    import yaml

    data = json.loads(body)
    updates = data.get("skills")
    if not updates or not isinstance(updates, list):
        return {"ok": False, "error": "missing skills array", "_status": 400}

    # Build lookup: name -> phase
    phase_map = {s["name"]: s["phase"] for s in updates if "name" in s and "phase" in s}
    if not phase_map:
        return {"ok": False, "error": "no valid skill phase entries", "_status": 400}

    wf_candidates = [
        Path(__file__).parent.parent.parent / "config" / "workflow.yaml",
        Path(__file__).parent.parent.parent.parent / "config" / "workflow.yaml",
    ]
    if _st._checkpoint_dir:
        wf_candidates.insert(0, _st._checkpoint_dir / "workflow.yaml")

    for wf in wf_candidates:
        if wf.exists():
            try:
                existing = yaml.safe_load(wf.read_text()) or {}
                for sk in existing.get("skills", []):
                    sk_name = sk.get("name", "")
                    if sk_name in phase_map:
                        sk["phase"] = phase_map[sk_name]
                wf.write_text(yaml.dump(existing, allow_unicode=True, sort_keys=False))
                return {"ok": True}
            except Exception as e:
                return {"ok": False, "error": str(e)}

    return {"ok": False, "error": "workflow.yaml not found"}


def _api_save_disabled_tools(body: bytes) -> dict:
    """POST /api/workflow/disabled-tools — Update disabled tools list in workflow.yaml.

    Expected body: {"disabled_tools": ["generate_ideas", "survey"]}
    """
    import yaml

    data = json.loads(body)
    disabled = data.get("disabled_tools")
    if not isinstance(disabled, list):
        return {"ok": False, "error": "missing disabled_tools array", "_status": 400}

    wf_candidates = [
        Path(__file__).parent.parent.parent / "config" / "workflow.yaml",
        Path(__file__).parent.parent.parent.parent / "config" / "workflow.yaml",
    ]
    if _st._checkpoint_dir:
        wf_candidates.insert(0, _st._checkpoint_dir / "workflow.yaml")

    for wf in wf_candidates:
        if wf.exists():
            try:
                existing = yaml.safe_load(wf.read_text()) or {}
                existing["disabled_tools"] = disabled
                wf.write_text(yaml.dump(existing, allow_unicode=True, sort_keys=False))
                return {"ok": True}
            except Exception as e:
                return {"ok": False, "error": str(e)}

    return {"ok": False, "error": "workflow.yaml not found"}


def _api_get_default_workflow() -> dict:
    """GET /api/workflow/default — Return the default workflow from config/."""
    import yaml

    default_path = Path(__file__).parent.parent.parent / "config" / "workflow.yaml"
    if not default_path.exists():
        default_path = Path(__file__).parent.parent.parent.parent / "config" / "workflow.yaml"

    if not default_path.exists():
        return {"ok": False, "error": "default workflow.yaml not found"}

    try:
        data = yaml.safe_load(default_path.read_text())
        flow = workflow_yaml_to_flow(data)
        return {"ok": True, "flow": flow, "workflow": data, "path": str(default_path)}
    except Exception as e:
        return {"ok": False, "error": str(e)}
