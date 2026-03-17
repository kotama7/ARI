"""
ari/pipeline.py — Generic workflow execution engine

Driven entirely by workflow.yaml (or pipeline.yaml for backward compat).
No hardcoded tool names. Data flow is declared in the YAML.
Adding a new skill or stage requires only YAML changes — no code changes.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Workflow / Pipeline loading
# ---------------------------------------------------------------------------

def load_pipeline(config_yaml: str | Path) -> list[dict]:
    """Load pipeline stages from workflow.yaml or legacy pipeline.yaml.

    Returns only stages with enabled != false.
    """
    path = Path(config_yaml).expanduser()
    if not path.exists():
        log.warning("Config not found: %s", path)
        return []
    data = yaml.safe_load(path.read_text())
    stages = data.get("pipeline", [])
    return [s for s in stages if s.get("enabled", True)]


def load_workflow(config_dir: str | Path) -> dict:
    """Load workflow.yaml if present, else fall back to pipeline.yaml.

    Returns full workflow dict including skills list.
    """
    base = Path(config_dir)
    for name in ("workflow.yaml", "pipeline.yaml"):
        p = base / name
        if p.exists():
            data = yaml.safe_load(p.read_text())
            data["_source"] = str(p)
            return data
    return {"pipeline": [], "skills": []}


# ---------------------------------------------------------------------------
# Template resolution
# ---------------------------------------------------------------------------

def _resolve_templates(value: Any, vars_: dict) -> Any:
    """Recursively resolve {{var}} templates in strings, lists, dicts."""
    if isinstance(value, str):
        def _sub(m: re.Match) -> str:
            key = m.group(1).strip()
            # Support dot-notation: stages.search_related_work.output
            parts = key.split(".")
            v = vars_
            try:
                for p in parts:
                    v = v[p]
                return str(v)
            except (KeyError, TypeError):
                return m.group(0)  # leave unresolved
        return re.sub(r"\{\{(.+?)\}\}", _sub, value)
    elif isinstance(value, dict):
        return {k: _resolve_templates(v, vars_) for k, v in value.items()}
    elif isinstance(value, list):
        return [_resolve_templates(v, vars_) for v in value]
    return value


# ---------------------------------------------------------------------------
# Context-building from BFTS nodes
# ---------------------------------------------------------------------------

def build_best_nodes_context(all_nodes, experiment_goal: str = "") -> tuple[str, dict]:
    """Build experiment context for paper writing from SUCCESS nodes.

    Returns ONLY scientific data (configurations, metrics, results).
    Does NOT include internal system identifiers (node IDs, labels, checkpoints).
    This ensures the generated paper reads as a direct scientific report,
    not as a description of how the automation system found the results.
    """
    from ari.orchestrator.node import NodeStatus

    results = [
        n for n in all_nodes
        if n.status == NodeStatus.SUCCESS and n.has_real_data
    ]
    if not results:
        return "", {}

    results.sort(
        key=lambda n: max(n.metrics.values()) if n.metrics else 0,
        reverse=True,
    )

    # Strip execution-context lines from experiment_goal before passing to paper LLM.
    # Remove file paths, job/work directory details, and hardware cluster specifics —
    # these are internal execution details, not scientific content for the paper.
    import re as _re_g
    goal_lines = experiment_goal.split("\n")
    _EXEC_PATTERNS = [
        r"^[-*]?\s*(source|work\s*dir|compiler|job\s*output|partition|max\s*cpu|do\s*not\s*modify)",
        r"/[a-zA-Z0-9_/.-]{5,}",   # file paths
        r"^#\s*(resources|hardware|success metric)",  # section headers about infra
    ]
    clean_goal_lines = []
    for line in goal_lines:
        skip = any(_re_g.search(pat, line, _re_g.IGNORECASE) for pat in _EXEC_PATTERNS)
        if not skip:
            clean_goal_lines.append(line)
    clean_goal = "\n".join(clean_goal_lines).strip()
    # Also strip HTML comments from goal
    clean_goal = _re_g.sub(r"<!--.*?-->", "", clean_goal, flags=_re_g.DOTALL).strip()

    context_lines = [f"Experiment goal: {clean_goal[:400]}"]
    context_lines.append(f"\nBest results (top {min(5, len(results))} configurations):")
    for i, r in enumerate(results[:5]):
        rank = "Best" if i == 0 else f"#{i+1}"
        metrics_str = str(r.metrics)
        context_lines.append(f"  [{rank}] metrics={metrics_str}")
    return "\n".join(context_lines), results[0].metrics if results else {}


def _extract_keywords_from_nodes(nodes_json_path: str, base_topic: str = "") -> str:
    """Extract search keywords from BFTS nodes_tree.json. Domain-agnostic."""
    keywords = set()
    if base_topic:
        keywords.update(w for w in base_topic.split() if len(w) > 3)
    if nodes_json_path:
        try:
            data = json.loads(Path(nodes_json_path).read_text())
            nodes = data if isinstance(data, list) else data.get("nodes", [])
            for node in nodes:
                for mem in (node.get("memory") or []):
                    text = mem if isinstance(mem, str) else mem.get("content", "")
                    keywords.update(re.findall(r"-O[0-9s]|-march=\S+|-f[a-z-]+", text))
                for art in (node.get("artifacts") or []):
                    text = art if isinstance(art, str) else (art.get("stdout") or art.get("content") or "")
                    keywords.update(w.lower() for w in re.findall(r"[A-Z]{2,}", text) if len(w) <= 8)
        except Exception:
            pass
    extras = [k for k in keywords if len(k) > 3][:5]
    base = base_topic if base_topic else "performance optimization benchmark"
    return (base + " " + " ".join(extras)).strip() if extras else base


# ---------------------------------------------------------------------------
# Stage execution
# ---------------------------------------------------------------------------

def _run_stage_subprocess(tool: str, args: dict, config_path: str, skill_name: str = "") -> Any:
    """Call an MCP tool via subprocess and return parsed result."""
    script = f"""
import json, sys
from ari.mcp.client import MCPClient
from ari.config import load_config
cfg = load_config({repr(config_path)})
if {repr(skill_name)}:
    skills = [s for s in cfg.skills if s.name == {repr(skill_name)}]
else:
    skills = cfg.skills
mcp = MCPClient(skills)
mcp.list_tools()
result_raw = mcp.call_tool({repr(tool)}, {repr(args)})
if isinstance(result_raw, dict) and "result" in result_raw:
    try:
        inner = result_raw["result"]
        result = json.loads(inner) if isinstance(inner, str) else inner
    except Exception:
        result = result_raw
elif isinstance(result_raw, str):
    result = json.loads(result_raw)
else:
    result = result_raw
print(json.dumps(result, ensure_ascii=False))
"""
    proc = subprocess.run([sys.executable, "-c", script], timeout=5400, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"stderr: {proc.stderr[:2000]}\nstdout: {proc.stdout[:500]}")
    if proc.stderr.strip():
        log.debug("Stage stderr: %s", proc.stderr[:300])
    raw = proc.stdout.strip()
    if not raw:
        raise RuntimeError(f"Empty stdout. stderr: {proc.stderr[:1000]}")
    return json.loads(raw)


# ---------------------------------------------------------------------------
# Generic pipeline execution
# ---------------------------------------------------------------------------


def build_scientific_data(nodes_json_path: str) -> dict:
    """Convert BFTS nodes_tree.json to science-facing data only.

    Strips all BFTS-internal fields (label, depth, node_id, status, parent_id).
    Returns: configurations (param dicts) + metric values.
    This is the ONLY format passed to plot-skill / paper-skill.
    """
    import re as _re_sci
    try:
        data = json.loads(Path(nodes_json_path).read_text())
        nodes = data if isinstance(data, list) else data.get("nodes", [])
    except Exception:
        return {"configurations": [], "metric_name": "metric"}

    science_nodes = []
    for n in nodes:
        if not (n.get("has_real_data") and n.get("metrics")):
            continue
        cfg = {}
        for mem in (n.get("memory") or []):
            text = mem if isinstance(mem, str) else mem.get("content", "")
            for flag in _re_sci.findall(r"-O[0-9s]\S*|-march=\S+|-f[a-z_-]+=?\S*", text):
                cfg.setdefault("flags", [])
                if flag not in cfg["flags"]:
                    cfg["flags"].append(flag)
            for tc in _re_sci.findall(r"OMP_NUM_THREADS=?(\d+)|threads?[=: ]+(\d+)", text, _re_sci.IGNORECASE):
                t = tc[0] or tc[1]
                if t:
                    cfg["threads"] = int(t)
        science_nodes.append({
            "configuration": cfg or {"index": len(science_nodes) + 1},
            "metrics": n.get("metrics", {}),
        })

    def _best(node):
        m = node["metrics"]
        return max(m.values()) if m else 0

    science_nodes.sort(key=_best, reverse=True)
    metric_name = list(science_nodes[0]["metrics"].keys())[0] if science_nodes else "metric"

    return {
        "configurations": science_nodes,
        "metric_name": metric_name,
        "best_value": _best(science_nodes[0]) if science_nodes else 0,
        "count": len(science_nodes),
    }

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
    """
    experiment_goal = experiment_data.get("goal", "")
    context, best_metrics = build_best_nodes_context(all_nodes, experiment_goal)

    # Save nodes_tree.json (referenced by downstream stages via {{ckpt}}/nodes_tree.json)
    nodes_json_path = str(checkpoint_dir / "nodes_tree.json")
    try:
        nodes_data = [n.to_dict() for n in all_nodes]
        Path(nodes_json_path).write_text(
            json.dumps({"experiment_goal": experiment_goal, "nodes": nodes_data},
                       ensure_ascii=False, indent=2)
        )
    except Exception as _e:
        log.warning("Failed to save nodes_tree.json: %s", _e)
        nodes_json_path = ""

    keywords = _extract_keywords_from_nodes(nodes_json_path, experiment_data.get("topic", ""))

    # Load paper_context from workflow.yaml (developer-defined paper description).
    # Falls back to {{context}} if not set. Keeps org names / cluster details
    # out of the paper while BFTS still sees the full experiment_goal.
    try:
        import yaml as _yaml
        _wf_cfg = _yaml.safe_load(Path(config_path).read_text()) if config_path else {}
    except Exception:
        _wf_cfg = {}
    _paper_ctx = (_wf_cfg.get("paper_context") or "").strip()
    if not _paper_ctx:
        _paper_ctx = context

    # Template variable registry — grows as stages complete
    import os as _os
    tpl_vars: dict = {
        "ckpt":              str(checkpoint_dir),
        "context":           context,
        "paper_context":     _paper_ctx,
        "slurm_partition":   (_wf_cfg.get("slurm_partition") or "cpu"),
        "keywords":          keywords,
        "stages":            {},
        "ari_root":          _os.environ.get("ARI_ROOT", str(Path(__file__).parents[2])),
        "experiment_source_file": _os.environ.get("ARI_SOURCE_FILE", ""),
        # Expose all top-level string/int config values for template substitution
        **{k: str(v) for k, v in _wf_cfg.items() if isinstance(v, (str, int, float)) and k not in ("paper_context",)},
    }

    stage_outputs: dict[str, Any] = {}

    for stage_cfg in stages:
        stage_name = stage_cfg.get("stage", "unknown")
        skill_key  = stage_cfg.get("skill", "")
        skill = skill_key + "-skill" if skill_key and not skill_key.endswith("-skill") else skill_key
        tool  = stage_cfg.get("tool", "")
        desc  = stage_cfg.get("description", stage_name)

        log.info("=== Stage [%s]: %s ===", stage_name, desc)

        # ── depends_on check ─────────────────────────────────────────────
        _depends = stage_cfg.get("depends_on", [])
        if isinstance(_depends, str): _depends = [_depends]
        _dep_fail = next((_d for _d in _depends if _d not in tpl_vars.get("stages", {})), None)
        if _dep_fail:
            log.warning("Stage [%s]: dep '%s' not resolved; skip", stage_name, _dep_fail)
            stage_outputs[stage_name] = {"skipped": True, "reason": f"dep: {_dep_fail}"}
            tpl_vars["stages"][stage_name] = {"output": "", "outputs": {}}
            continue

        # ── skip_if_exists check ──────────────────────────────────────────
        skip_path_tpl = stage_cfg.get("skip_if_exists", "")
        if skip_path_tpl:
            skip_path = _resolve_templates(skip_path_tpl, tpl_vars)
            if Path(skip_path).exists():
                log.info("Stage [%s]: skipping (output exists: %s)", stage_name, skip_path)
                tpl_vars["stages"][stage_name] = {"output": skip_path, "outputs": {"file": skip_path}}
                stage_outputs[stage_name] = {"skipped": True, "output": skip_path}
                continue

        # ── resolve inputs ────────────────────────────────────────────────
        # load_inputs: input keys whose resolved values (file paths) should be read as content
        load_inputs = set(stage_cfg.get("load_inputs", []))
        raw_inputs = stage_cfg.get("inputs", {})
        args = {}
        for k, v in raw_inputs.items():
            resolved = _resolve_templates(v, tpl_vars)
            # Read file content only for inputs explicitly listed in load_inputs
            if (k in load_inputs and isinstance(resolved, str) and Path(resolved).exists()):
                args[k] = Path(resolved).read_text()
            else:
                args[k] = resolved

        # ── fallbacks: paper_text and actual_metrics (backward compat) ────
        _paper_tools  = {"evaluate", "review_section", "reproducibility_report"}
        _metrics_tools = {"evaluate", "compare_with_results", "reproducibility_report"}
        if tool in _paper_tools and "paper_text" not in args:
            for _tex in ("full_paper.tex", "experiment_section.tex"):
                tp = checkpoint_dir / _tex
                if tp.exists():
                    args.setdefault("paper_text", tp.read_text())
                    break
        if tool in _metrics_tools and "actual_metrics" not in args:
            args.setdefault("actual_metrics", best_metrics)
        # ── paper_path fallback: if revised tex missing OR too short, fall back to original ──
        if "paper_path" in args:
            pp = Path(args["paper_path"])
            _orig = checkpoint_dir / "full_paper.tex"
            if not pp.exists():
                if _orig.exists():
                    log.warning("paper_path %s not found; falling back to full_paper.tex", pp)
                    args["paper_path"] = str(_orig)
            elif _orig.exists():
                # If revised is less than 60% of original size, it was likely truncated by LLM
                _rev_size = pp.stat().st_size
                _orig_size = _orig.stat().st_size
                if _orig_size > 0 and _rev_size < _orig_size * 0.6:
                    log.warning("revised paper too short (%d vs %d bytes); using original", _rev_size, _orig_size)
                    args["paper_path"] = str(_orig)

        # ── tool call ─────────────────────────────────────────────────────
        try:
            result = _run_stage_subprocess(tool, args, config_path, skill_name=skill)
            stage_outputs[stage_name] = result

            # ── save outputs ──────────────────────────────────────────────
            outputs_cfg = stage_cfg.get("outputs", {})
            primary_file = _resolve_templates(outputs_cfg.get("file", ""), tpl_vars)

            if primary_file:
                out_path = Path(primary_file)
                if primary_file.endswith(".tex"):
                    latex = (result.get("latex", "") if isinstance(result, dict) else "") or ""
                    # Fallback: unwrap nested result dict if latex is empty
                    if not latex and isinstance(result, dict):
                        _inner = result.get("result", "")
                        if isinstance(_inner, str) and _inner.startswith("{"):
                            import json as _jj
                            try:
                                _parsed = _jj.loads(_inner)
                                latex = _parsed.get("latex", "")
                            except Exception:
                                pass
                        elif isinstance(_inner, dict):
                            latex = _inner.get("latex", "")
                    if latex:
                        out_path.write_text(latex)
                        log.info("Stage [%s]: wrote %s", stage_name, out_path)
                    else:
                        # Write debug dump for diagnosis
                        _dbg = out_path.parent / f"_debug_{stage_name}.json"
                        import json as _jj
                        _dbg.write_text(_jj.dumps(result, ensure_ascii=False, default=str)[:5000])
                        log.warning("Stage [%s]: no latex in result; debug -> %s", stage_name, _dbg)
                    # Save bib alongside
                    bib_content = result.get("bib", "") if isinstance(result, dict) else ""
                    if bib_content:
                        bib_file = _resolve_templates(outputs_cfg.get("bib_file", str(out_path.parent / "refs.bib")), tpl_vars)
                        Path(bib_file).write_text(bib_content)
                        log.info("Stage [%s]: wrote %s", stage_name, bib_file)
                else:
                    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
                    log.info("Stage [%s]: wrote %s", stage_name, out_path)

                # Register primary + named outputs for template resolution
                _named = {k: _resolve_templates(v, tpl_vars)
                          for k, v in outputs_cfg.items()}
                tpl_vars["stages"][stage_name] = {
                    "output": primary_file,
                    "outputs": _named,
                }
            else:
                tpl_vars["stages"][stage_name] = {"output": "", "outputs": {}}

            # Handle figures_manifest specially
            if stage_name == "generate_figures" or "figures" in stage_name:
                figs = result.get("figures", {}) if isinstance(result, dict) else {}
                latex_snips = result.get("latex_snippets", {}) if isinstance(result, dict) else {}
                if figs and primary_file:
                    manifest = {"figures": figs}
                    if latex_snips:
                        manifest["latex_snippets"] = latex_snips
                    Path(primary_file).write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
                    log.info("Stage [%s]: wrote figures manifest %s (latex_snippets=%d)", stage_name, primary_file, len(latex_snips))

        except Exception:
            import traceback as _tb
            log.warning("Stage [%s] failed:\n%s", stage_name, _tb.format_exc())
            stage_outputs[stage_name] = {"error": "stage failed"}
            tpl_vars["stages"][stage_name] = {"output": "", "outputs": {}}

    return stage_outputs
