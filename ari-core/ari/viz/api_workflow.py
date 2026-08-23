from __future__ import annotations
"""ARI viz: api_workflow — React Flow workflow editor endpoints and converters.

Write path (RR-P0-1 / ADR-10): every workflow-WRITE handler first passes
``_workflow_write_guard`` (frozen 400 refusal without an active checkpoint)
and then edits ONLY the per-checkpoint ``{ckpt}/workflow.yaml``. When that
copy does not exist yet, ``_checkpoint_workflow_path`` seeds it by copying
the bundled ``config/workflow.yaml`` (copy-on-write) before applying the
edit — the bundled file is never written from the GUI.

Revision layer (gui_refresh Wave 4d, plan 07 §Workflow Studio): GET
/api/workflow serves an additive weak ``revision`` (sha256[:12] of the
served bytes) and every write handler accepts an OPTIONAL ``base_revision``
— when present and stale, ``_workflow_revision_guard`` refuses with a
frozen 409 payload before anything (including the CoW seed) is written.
Legacy callers that send no ``base_revision`` keep last-write-wins.
"""

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
                    # React-driver stages expose pre_tool/post_tool instead of
                    # a single tool; carry both so the UI can show them
                    # read-only and _merge_stages round-trips them back into
                    # workflow.yaml verbatim.
                    "pre_tool": s.get("pre_tool", ""),
                    "post_tool": s.get("post_tool", ""),
                    "react": s.get("react") or None,
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
# pre_tool/post_tool are included so that react stages survive an edit roundtrip
# (_merge_stages still preserves the full `react:` block via the
# existing-YAML fallback).
_FLOW_FIELDS = {
    "stage", "skill", "tool", "description", "depends_on",
    "enabled", "phase", "loop_back_to", "pre_tool", "post_tool",
}


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

        # React-driver stages: forward pre_tool/post_tool only when set, so
        # _merge_stages does not insert empty strings into stages that never
        # had them. The `react:` block itself is preserved by the
        # existing-YAML fallback in _merge_stages.
        pre_t = str(data.get("pre_tool") or "").strip()
        post_t = str(data.get("post_tool") or "").strip()
        if pre_t:
            stage["pre_tool"] = pre_t
        if post_t:
            stage["post_tool"] = post_t
        # When the stage is driven by react_driver (pre/post tools present)
        # the flat `tool` field is redundant — drop it to keep the YAML clean.
        if pre_t or post_t:
            stage.pop("tool", None)

        if nid in loop_backs:
            stage["loop_back_to"] = loop_backs[nid]

        if phase == "bfts":
            bfts_stages.append(stage)
        else:
            paper_stages.append(stage)

    return {"bfts_pipeline": bfts_stages, "pipeline": paper_stages}


# ── Write guard (RR-P0-1 / ADR-10) ────────────────

# Frozen refusal payload text for workflow writes without an active checkpoint.
_NO_ACTIVE_CHECKPOINT_ERROR = (
    "No active project. Select a checkpoint before editing the workflow "
    "(the bundled default workflow.yaml is read-only from the GUI)."
)


def _workflow_write_guard() -> "dict | None":
    """Refuse workflow writes when no usable checkpoint is active (ADR-10).

    Shared write-path guard for every workflow-WRITE endpoint
    (POST /api/workflow, /api/workflow/flow, /api/workflow/skills,
    /api/workflow/disabled-tools) — and any future one — so the bundled
    ``config/workflow.yaml`` can never be rewritten from the GUI (RR-P0-1).
    Mirrors ``state.require_checkpoint_dir`` but returns the frozen refusal
    payload; returns ``None`` when the per-checkpoint copy may be written.
    """
    ckpt = _st._checkpoint_dir
    if ckpt is None or not Path(ckpt).exists():
        return {"ok": False, "error": _NO_ACTIVE_CHECKPOINT_ERROR, "_status": 400}
    return None


# ── Weak revision (optimistic concurrency, gui_refresh Wave 4d) ──────────

# Frozen refusal payload text for a stale ``base_revision`` (plan 07
# §Workflow Studio: the 2s blind-overwrite autosave is retired; writers
# that opt in must be revision-aware).
_REVISION_MISMATCH_ERROR = (
    "workflow changed on disk since you loaded it (revision mismatch); "
    "reload before saving"
)


def workflow_revision(data: bytes) -> str:
    """Weak content revision of workflow.yaml bytes: sha256 hex[:12].

    Additive key on GET /api/workflow and on every successful workflow
    write (plan 07 §Workflow Studio). Weak by design — it identifies the
    exact bytes served/written, not a version lineage.
    """
    import hashlib

    return hashlib.sha256(data).hexdigest()[:12]


def _served_workflow_path() -> "Path | None":
    """The workflow.yaml GET serves and a write would land on.

    Checkpoint copy when it exists; else the bundled default (which CoW
    seeding copies verbatim before an edit, so its hash IS the pre-write
    content hash). ``None`` when neither file exists.
    """
    from ari.config.finder import package_config_root

    if _st._checkpoint_dir:
        wf = Path(_st._checkpoint_dir) / "workflow.yaml"
        if wf.exists():
            return wf
    bundled = package_config_root() / "workflow.yaml"
    return bundled if bundled.exists() else None


def _workflow_revision_guard(base_revision: object) -> "dict | None":
    """Optional optimistic-concurrency check for workflow writes.

    ``base_revision`` absent/empty returns ``None`` — legacy callers keep
    last-write-wins, the check is additive opt-in. When present it must
    equal the sha256[:12] of the current on-disk bytes, or the write is
    refused with a frozen 409 payload and nothing is written (the CoW
    seed must not run either, so call this BEFORE
    :func:`_checkpoint_workflow_path`). Callers must already have passed
    :func:`_workflow_write_guard`.
    """
    if not base_revision:
        return None
    wf = _served_workflow_path()
    if wf is None:
        return None
    if str(base_revision) != workflow_revision(wf.read_bytes()):
        return {"ok": False, "error": _REVISION_MISMATCH_ERROR, "_status": 409}
    return None


def _checkpoint_workflow_path() -> "Path | None":
    """Per-checkpoint ``workflow.yaml``, CoW-seeded from the bundled default.

    ADR-10 residual fix (gui_refresh Wave 2b, follow-up to the Wave 2a
    guard): callers must already have passed :func:`_workflow_write_guard`.
    When the active checkpoint has no ``workflow.yaml`` yet, the bundled
    ``config/workflow.yaml`` is copied into the checkpoint first
    (copy-on-write seed) and the caller's edit lands on that copy — the
    bundled file is never written. Returns ``None`` only when neither the
    checkpoint copy nor the bundled default exists.
    """
    import shutil
    from ari.config.finder import package_config_root

    wf = Path(_st._checkpoint_dir) / "workflow.yaml"
    if not wf.exists():
        bundled = package_config_root() / "workflow.yaml"
        if not bundled.exists():
            return None
        shutil.copyfile(bundled, wf)
    return wf


# ── API handlers ─────────────────────────────────


def _api_get_workflow_flow() -> dict:
    """GET /api/workflow/flow — Return current workflow as React Flow JSON."""
    import yaml
    from ari.config.finder import package_config_root

    wf_candidates = [
        package_config_root() / "workflow.yaml",
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

    guard = _workflow_write_guard()
    if guard:
        return guard
    stale = _workflow_revision_guard(data.get("base_revision"))
    if stale:
        return stale

    # Convert back to YAML structure
    yaml_parts = flow_to_workflow_yaml(flow)

    # CoW seed: edit the per-checkpoint copy only (bundled file never written).
    try:
        wf = _checkpoint_workflow_path()
    except Exception as e:
        return {"ok": False, "error": str(e)}
    if wf is None:
        return {"ok": False, "error": "workflow.yaml not found"}
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
        text = yaml.dump(existing, allow_unicode=True, sort_keys=False)
        wf.write_text(text)
        return {"ok": True, "revision": workflow_revision(text.encode("utf-8"))}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _normalize_phase_value(phase: object) -> str | list[str]:
    """Coerce a client-supplied phase into the canonical YAML form.

    - A list with a single entry collapses to that string ("bfts", "all", "none")
      so single-phase skills stay compact in workflow.yaml.
    - Multi-phase lists are kept as a list, deduplicated, with "all" and "none"
      resolved (all → collapse to "all", none present with other values → "none"
      is dropped because it would disable the skill).
    - Plain strings pass through unchanged.
    """
    if isinstance(phase, list):
        seen: list[str] = []
        for p in phase:
            s = str(p).strip()
            if s and s not in seen:
                seen.append(s)
        if not seen:
            return "all"
        if "all" in seen:
            return "all"
        # "none" is exclusive: if the user unchecks everything they should send
        # ["none"] explicitly; any phase alongside "none" drops "none".
        if "none" in seen and len(seen) > 1:
            seen = [p for p in seen if p != "none"]
        if len(seen) == 1:
            return seen[0]
        return seen
    return str(phase)


def _api_save_skill_phases(body: bytes) -> dict:
    """POST /api/workflow/skills — Update skill phase assignments in workflow.yaml.

    Expected body::

        {"skills": [{"name": "web-skill", "phase": "all"}, ...]}

    or with a list phase::

        {"skills": [{"name": "web-skill", "phase": ["paper", "reproduce"]}, ...]}
    """
    import yaml

    data = json.loads(body)
    updates = data.get("skills")
    if not updates or not isinstance(updates, list):
        return {"ok": False, "error": "missing skills array", "_status": 400}

    # Build lookup: name -> normalized phase (str or list[str])
    phase_map: dict[str, str | list[str]] = {}
    for s in updates:
        if not isinstance(s, dict) or "name" not in s or "phase" not in s:
            continue
        phase_map[s["name"]] = _normalize_phase_value(s["phase"])
    if not phase_map:
        return {"ok": False, "error": "no valid skill phase entries", "_status": 400}

    guard = _workflow_write_guard()
    if guard:
        return guard
    stale = _workflow_revision_guard(data.get("base_revision"))
    if stale:
        return stale

    # CoW seed: edit the per-checkpoint copy only (bundled file never written).
    try:
        wf = _checkpoint_workflow_path()
    except Exception as e:
        return {"ok": False, "error": str(e)}
    if wf is None:
        return {"ok": False, "error": "workflow.yaml not found"}
    try:
        existing = yaml.safe_load(wf.read_text()) or {}
        for sk in existing.get("skills", []):
            sk_name = sk.get("name", "")
            if sk_name in phase_map:
                sk["phase"] = phase_map[sk_name]
        text = yaml.dump(existing, allow_unicode=True, sort_keys=False)
        wf.write_text(text)
        return {"ok": True, "revision": workflow_revision(text.encode("utf-8"))}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _api_save_disabled_tools(body: bytes) -> dict:
    """POST /api/workflow/disabled-tools — Update disabled tools list in workflow.yaml.

    Expected body: {"disabled_tools": ["generate_ideas", "survey"]}
    """
    import yaml

    data = json.loads(body)
    disabled = data.get("disabled_tools")
    if not isinstance(disabled, list):
        return {"ok": False, "error": "missing disabled_tools array", "_status": 400}

    guard = _workflow_write_guard()
    if guard:
        return guard
    stale = _workflow_revision_guard(data.get("base_revision"))
    if stale:
        return stale

    # CoW seed: edit the per-checkpoint copy only (bundled file never written).
    try:
        wf = _checkpoint_workflow_path()
    except Exception as e:
        return {"ok": False, "error": str(e)}
    if wf is None:
        return {"ok": False, "error": "workflow.yaml not found"}
    try:
        existing = yaml.safe_load(wf.read_text()) or {}
        existing["disabled_tools"] = disabled
        text = yaml.dump(existing, allow_unicode=True, sort_keys=False)
        wf.write_text(text)
        return {"ok": True, "revision": workflow_revision(text.encode("utf-8"))}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _api_get_default_workflow() -> dict:
    """GET /api/workflow/default — Return the default workflow from config/."""
    import yaml

    from ari.config.finder import package_config_root
    default_path = package_config_root() / "workflow.yaml"

    if not default_path.exists():
        return {"ok": False, "error": "default workflow.yaml not found"}

    try:
        data = yaml.safe_load(default_path.read_text())
        flow = workflow_yaml_to_flow(data)
        return {"ok": True, "flow": flow, "workflow": data, "path": str(default_path)}
    except Exception as e:
        return {"ok": False, "error": str(e)}
