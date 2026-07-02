"""Top-level pipeline orchestrator (Phase 3C).

Hosts the two top-level entry points (``build_scientific_data`` and
``run_pipeline``) that ``cli.py`` / external callers invoke.  All
helper clusters live in sibling modules under ``ari.pipeline``;
``__init__.py`` re-exports the public surface so existing
``from ari.pipeline import run_pipeline`` paths keep working.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ari.pipeline.driver import WorkflowDriver


# Lazy delegators so ``monkeypatch.setattr(ari.pipeline, '_run_react_stage',
# ...)`` / ``'_run_stage_subprocess'`` are honoured even though Phase 3C moved
# the implementations into ``ari.pipeline.stage_runner``. KEEP — these are
# load-bearing test monkeypatch surfaces (subtask 012 §10).
def _run_react_stage(*args, **kwargs):
    """Lazy delegator so ``monkeypatch.setattr(ari.pipeline,
    '_run_react_stage', ...)`` is honoured even though Phase 3C moved the
    implementation into a sibling module.
    """
    import ari.pipeline as _p
    return _p._run_react_stage(*args, **kwargs)


def _run_stage_subprocess(*args, **kwargs):
    """Same lazy-delegator pattern as :func:`_run_react_stage` so test
    monkeypatches against the package surface keep working.
    """
    import ari.pipeline as _p
    return _p._run_stage_subprocess(*args, **kwargs)


log = logging.getLogger(__name__)


def build_scientific_data(nodes_json_path: str) -> dict:
    """Convert BFTS nodes_tree.json to science-facing data only.

    Strips all BFTS-internal fields (label, depth, node_id, status, parent_id).
    Returns: configurations (param dicts) + metric values.
    This is the ONLY format passed to plot-skill / paper-skill.
    """
    try:
        data = json.loads(Path(nodes_json_path).read_text())
        nodes = data if isinstance(data, list) else data.get("nodes", [])
    except Exception:
        return {"configurations": [], "metric_name": "metric"}

    science_nodes = []
    for n in nodes:
        if not (n.get("has_real_data") and n.get("metrics")):
            continue
        # No domain-specific parameter extraction here.
        # The transform-skill (LLM-powered) handles parameter extraction from artifacts.
        science_nodes.append({
            "configuration": {"index": len(science_nodes) + 1},
            "metrics": n.get("metrics", {}),
        })

    def _best(node):
        m = node["metrics"]
        # Numeric metric tiebreaker; primary sort is BFTS depth (deeper = LLM preferred more)
        return max((v for v in m.values() if isinstance(v, (int, float))), default=0) if m else 0

    # Load primary_metric / higher_is_better from evaluation_criteria.json
    # (set autonomously by generate_ideas; no user input required)
    _primary = ""
    _higher_is_better = True
    try:
        _ec_path = Path(nodes_json_path).parent / "evaluation_criteria.json"
        if _ec_path.exists():
            _ec = json.loads(_ec_path.read_text())
            _primary = _ec.get("primary_metric", "")
            _higher_is_better = _ec.get("higher_is_better", True)
            log.info("Loaded evaluation criteria: primary_metric=%s higher_is_better=%s", _primary, _higher_is_better)
    except Exception:
        pass

    def _primary_val(node: dict) -> float:
        m = node.get("metrics", {})
        if _primary and _primary in m and isinstance(m[_primary], (int, float)):
            v = float(m[_primary])
            return v if _higher_is_better else -v  # negate so sort(reverse=True) works for both
        # Fallback: BFTS depth (deeper = more explored = LLM preferred)
        return float(node.get("depth", 0)) * 1e-6 + _best(m)

    # Sort by primary_metric (or depth as proxy for LLM preference)
    science_nodes.sort(key=lambda n: (n.get("has_real_data", False), _primary_val(n)), reverse=True)
    metric_name = list(science_nodes[0]["metrics"].keys())[0] if science_nodes else "metric"

    return {
        "configurations": science_nodes,
        "metric_name": metric_name,
        "best_value": _best(science_nodes[0]) if science_nodes else 0,
        "count": len(science_nodes),
    }


def _copy_stage_output_if_distinct(src: Path, dst: Path) -> None:
    """Copy a tool-written binary output into the stage's declared output path,
    but only when it is genuinely a different file.

    A tool (e.g. compile_paper for the render_paper stage) writes its file in place
    and returns an ABSOLUTE pdf_path, while the declared stage output may be RELATIVE
    (render_paper's ``{{checkpoint_dir}}/full_paper.pdf`` when the run was given a
    relative checkpoint path). Comparing the raw strings then treats the in-place
    write as a copy-onto-itself and ``shutil.copy2`` raises ``SameFileError`` —
    marking the stage FAILED even though the compile succeeded. Compare RESOLVED
    paths and tolerate the same-file case so an in-place compile is never a failure.
    """
    src = Path(src)
    dst = Path(dst)
    if src.resolve() == dst.resolve():
        return
    import shutil as _shu
    try:
        _shu.copy2(str(src), str(dst))
    except _shu.SameFileError:
        pass


def run_pipeline(
    stages: list[dict],
    all_nodes,
    experiment_data: dict,
    checkpoint_dir: Path,
    config_path: str,
) -> dict[str, Any]:
    """Execute pipeline stages driven by YAML stage definitions.

    Template variables resolved for each stage:
      {{ckpt}}     -> checkpoint_dir
      {{context}}  -> experiment summary text
      {{keywords}} -> auto-extracted search keywords
      {{stages.<name>.output}} -> output file path of a previous stage

    Subtask 012: the imperative stage loop was extracted into
    :class:`ari.pipeline.driver.WorkflowDriver` (pre-flight + cursor loop +
    loop-back rewind) and :mod:`ari.pipeline.stages` (per-stage lifecycle).
    This function is a thin, behaviour-preserving wrapper over the driver;
    its signature and return value are unchanged.
    """
    return WorkflowDriver(
        stages, all_nodes, experiment_data, checkpoint_dir, config_path
    ).run()
