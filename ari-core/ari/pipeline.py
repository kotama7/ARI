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
        key=lambda n: max((v for v in n.metrics.values() if isinstance(v, (int, float))), default=0) if n.metrics else 0,
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
    extras = [k for k in keywords if len(k) > 3 and k.lower() not in base_topic.lower()][:5]
    base = base_topic if base_topic else "performance optimization benchmark"
    return (base + " " + " ".join(extras)).strip() if extras else base


# ---------------------------------------------------------------------------
# Stage execution
# ---------------------------------------------------------------------------

def _call_with_retry(fn, max_retries: int = 3, delay: float = 5.0):
    """Retry a function on transient connection errors."""
    import time as _time
    last_exc = None
    for attempt in range(max_retries):
        try:
            return fn()
        except Exception as e:
            msg = str(e).lower()
            if any(x in msg for x in ("connection error", "connection reset", "timeout", "temporary")):
                last_exc = e
                if attempt < max_retries - 1:
                    _time.sleep(delay * (attempt + 1))
                    continue
            raise
    raise last_exc


def _run_stage_subprocess(tool: str, args: dict, config_path: str, skill_name: str = "") -> Any:
    """Call an MCP tool via subprocess and return parsed result.

    Uses a temp JSON file to pass args safely — avoids f-string injection
    when args values contain braces, quotes, or large JSON payloads.
    """
    import tempfile as _tmpmod_sp
    import os as _os_sp

    # 1. Serialize args to a temp file (safe for any content)
    _args_fd, _args_path = _tmpmod_sp.mkstemp(suffix=".json", prefix="ari_args_")
    _os_sp.close(_args_fd)
    with open(_args_path, "w", encoding="utf-8") as _f:
        json.dump(args, _f, ensure_ascii=False)

    # 2. Build the subprocess script using string concatenation (not f-string)
    _ari_root = repr(str(Path(__file__).parent.parent))
    _cfg = repr(config_path)
    _skill = repr(skill_name)
    _tool = repr(tool)
    _apath = repr(_args_path)
    _skill_filter = (
        "skills = [s for s in cfg.skills if s.name == " + _skill + "]\n"
        if skill_name else
        "skills = cfg.skills\n"
    )
    script = (
        "import json, sys\n"
        "sys.path.insert(0, " + _ari_root + ")\n"
        "from ari.mcp.client import MCPClient\n"
        "from ari.config import load_config\n"
        "from pathlib import Path as _P\n"
        "_cfg_path = " + _cfg + "\n"
        "if not _cfg_path:\n"
        "    _pkg_cfg = _P(__file__).parents[1] / 'config' / 'workflow.yaml'\n"
        "    _cfg_path = str(_pkg_cfg) if _pkg_cfg.exists() else _cfg_path\n"
        "cfg = load_config(_cfg_path)\n"
        + _skill_filter +
        "mcp = MCPClient(skills)\n"
        "mcp.list_tools()\n"
        "with open(" + _apath + ") as _af:\n"
        "    _call_args = json.load(_af)\n"
        "result_raw = mcp.call_tool(" + _tool + ", _call_args)\n"
        "if isinstance(result_raw, dict) and 'result' in result_raw:\n"
        "    try:\n"
        "        inner = result_raw['result']\n"
        "        result = json.loads(inner) if isinstance(inner, str) else inner\n"
        "    except Exception:\n"
        "        result = result_raw\n"
        "elif isinstance(result_raw, str):\n"
        "    result = json.loads(result_raw)\n"
        "else:\n"
        "    result = result_raw\n"
        "print(json.dumps(result, ensure_ascii=False))\n"
    )

    # 3. Build env for subprocess — include API keys and ARI settings
    _sub_env = {**_os_sp.environ}
    for _ekey in ("ARI_LLM_MODEL", "ARI_LLM_API_BASE", "OPENAI_API_KEY",
                  "ANTHROPIC_API_KEY", "SLURM_LOG_DIR", "ARI_WORK_DIR", "ARI_ROOT"):
        if _ekey in _os_sp.environ:
            _sub_env[_ekey] = _os_sp.environ[_ekey]
    # Ensure ARI_LLM_API_BASE="" when using OpenAI (prevents fallback to Ollama URL)
    if "ARI_LLM_API_BASE" not in _sub_env:
        _sub_env["ARI_LLM_API_BASE"] = ""
    # Load ~/.env if OPENAI_API_KEY not yet set (source ~/.env doesn't export to Python)
    if "OPENAI_API_KEY" not in _sub_env:
        _env_file = _os_sp.path.expanduser("~/.env")
        if _os_sp.path.exists(_env_file):
            try:
                for _eline in open(_env_file).read().splitlines():
                    _eline = _eline.strip()
                    if not _eline or _eline.startswith("#") or "=" not in _eline:
                        continue
                    _ek, _, _ev = _eline.partition("=")
                    _ek = _ek.strip().removeprefix("export").strip()
                    _ev = _ev.strip()
                    if len(_ev) >= 2 and _ev[0] in (chr(34), chr(39)) and _ev[-1] == _ev[0]:
                        _ev = _ev[1:-1]
                    if _ek and _ek not in _sub_env:
                        _sub_env[_ek] = _ev
            except Exception:
                pass

    # 4. Run subprocess and clean up temp file
    try:
        proc = subprocess.run(
            [sys.executable, "-c", script],
            timeout=5400, capture_output=True, text=True, env=_sub_env,
        )
    finally:
        try:
            _os_sp.unlink(_args_path)
        except Exception:
            pass

    if proc.returncode != 0:
        raise RuntimeError(f"stderr: {proc.stderr[:2000]}\nstdout: {proc.stdout[:500]}")
    if proc.stderr.strip():
        log.debug("Stage stderr: %s", proc.stderr[:300])
    raw = proc.stdout.strip()
    if not raw:
        raise RuntimeError(f"Empty stdout. stderr: {proc.stderr[:1000]}")
    return json.loads(raw)


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

    # Extract evaluation_criteria from nodes (set by generate_ideas in loop.py)
    # Written to checkpoint as evaluation_criteria.json for downstream use
    _eval_criteria_path = checkpoint_dir / "evaluation_criteria.json"
    if not _eval_criteria_path.exists():
        _ec = {"primary_metric": "", "higher_is_better": True, "metric_rationale": ""}
        for _n in all_nodes:
            # Each node stores its memory snapshots; look for EVALUATION_CRITERIA entries
            for _snap in (_n.memory_snapshot if hasattr(_n, "memory_snapshot") else []):
                if isinstance(_snap, str) and "EVALUATION_CRITERIA:" in _snap:
                    import re as _re_ec
                    _pm = _re_ec.search(r"primary_metric=([\w_]+)", _snap)
                    _hib = _re_ec.search(r"higher_is_better=(\w+)", _snap)
                    if _pm:
                        _ec["primary_metric"] = _pm.group(1)
                    if _hib:
                        _ec["higher_is_better"] = _hib.group(1).lower() != "false"
                    break
            if _ec["primary_metric"]:
                break
        try:
            _eval_criteria_path.write_text(json.dumps(_ec, indent=2))
            log.info("Saved evaluation_criteria.json: primary_metric=%s", _ec["primary_metric"])
        except Exception as _ece:
            log.warning("Failed to save evaluation_criteria.json: %s", _ece)

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

    # Convert topic slug (e.g. "Accurate_FP32_GEMM_v2") -> search query ("Accurate FP32 GEMM v2")
    _raw_topic = experiment_data.get("topic", "")
    _search_topic = re.sub(r"[_-]+", " ", _raw_topic).strip()
    keywords = _extract_keywords_from_nodes(nodes_json_path, _search_topic)

    # Load paper_context from workflow.yaml (developer-defined paper description).
    # Falls back to {{context}} if not set. Keeps org names / cluster details
    # out of the paper while BFTS still sees the full experiment_goal.
    try:
        import yaml as _yaml
        _cfg_candidates = [
            Path(config_path) if config_path else None,
            Path(config_path).parent / "workflow.yaml" if config_path else None,
            Path(__file__).parent.parent / "config" / "workflow.yaml",
        ]
        _cfg_path = next((p for p in _cfg_candidates if p and p.exists()), None)
        _wf_cfg = _yaml.safe_load(_cfg_path.read_text()) if _cfg_path else {}
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
        "slurm_partition":   _wf_cfg.get("slurm_partition", ""),  # resolved at runtime via ARI_SLURM_PARTITION env
        "keywords":          keywords,
        "stages":            {},
        "ari_root":          _os.environ.get("ARI_ROOT", str(Path(__file__).parents[2])),
        # Reproducibility check reads only the paper — no source_file injection.
        # Providing original source would be "repeat experiment", not "reproduce from paper".
        "experiment_source_file": _os.environ.get("ARI_SOURCE_FILE", ""),
        "author_name":       "Artificial Research Intelligence",  # default; overridden by workflow.yaml
        # Expose all top-level string/int config values for template substitution
        **{k: str(v) for k, v in _wf_cfg.items() if isinstance(v, (str, int, float)) and k not in ("paper_context",)},
    }

    stage_outputs: dict[str, Any] = {}

    for stage_cfg in stages:
        stage_name = stage_cfg.get("stage", "unknown")
        skill_key  = stage_cfg.get("skill", "")
        skill = skill_key if ("skill" in skill_key) else (skill_key + "-skill" if skill_key else "")
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
        # Support both "inputs:" and "input:" YAML keys
        raw_inputs = stage_cfg.get("inputs") or stage_cfg.get("input") or {}
        # Resolve *_from shorthand: "refs_json_from: related_refs.json" -> key=refs_json, value=<ckpt>/related_refs.json
        _resolved_input = {}
        for k, v in raw_inputs.items():
            if k.endswith("_from"):
                base_key = k[:-5]  # strip _from
                file_path = str(checkpoint_dir / v) if not Path(str(v)).is_absolute() else str(v)
                _resolved_input[base_key] = file_path
                load_inputs.add(base_key)  # auto-load file content
            else:
                _resolved_input[k] = v
        raw_inputs = _resolved_input
        args = {}
        # params are static values passed directly to the tool (with template expansion)
        for k, v in stage_cfg.get("params", {}).items():
            args[k] = _resolve_templates(v, tpl_vars) if isinstance(v, str) else v
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

        # ── tool call (with retry on transient connection errors) ─────────
        import time as _retry_time
        _max_retries = 5
        _last_exc = None
        result = None
        for _attempt in range(_max_retries):
            try:
                log.info("Stage [%s]: calling tool=%s skill=%s args_keys=%s (attempt %d/%d)",
                         stage_name, tool, skill, list(args.keys()), _attempt + 1, _max_retries)
                result = _run_stage_subprocess(tool, args, config_path, skill_name=skill)
                # Check if result itself contains a connection error (MCP returned error dict)
                if isinstance(result, dict):
                    _r_str = result.get("result", "")
                    if isinstance(_r_str, str) and ("connection error" in _r_str.lower() or
                                                     "internalservererror" in _r_str.lower()):
                        raise RuntimeError(f"MCP tool returned connection error: {_r_str[:200]}")
                _last_exc = None
                break
            except Exception as _retry_exc:
                _msg = str(_retry_exc).lower()
                if any(x in _msg for x in ("connection error", "connection reset", "timeout",
                                            "internalservererror", "mcp tool returned connection")):
                    _last_exc = _retry_exc
                    if _attempt < _max_retries - 1:
                        _wait = 30 * (_attempt + 1)  # 30, 60, 90, 120s backoff
                        log.warning("Stage [%s] attempt %d failed (transient): %s. Retrying in %ds...",
                                    stage_name, _attempt + 1, _retry_exc, _wait)
                        _retry_time.sleep(_wait)
                        continue
                raise
        if _last_exc:
            raise _last_exc
        stage_outputs[stage_name] = result

        try:
            # ── save outputs ──────────────────────────────────────────────
            outputs_cfg = stage_cfg.get("outputs", {})
            # Support both "output_file: foo.json" (shorthand) and "outputs: {file: foo.json}" (full)
            _output_file_shorthand = stage_cfg.get("output_file", "")
            if _output_file_shorthand and not outputs_cfg.get("file"):
                _resolved_shorthand = _resolve_templates(_output_file_shorthand, tpl_vars)
                _abs_shorthand = str(checkpoint_dir / _resolved_shorthand) if not Path(_resolved_shorthand).is_absolute() else _resolved_shorthand
                primary_file = _abs_shorthand
                outputs_cfg = {"file": primary_file}
            else:
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
                    # For binary outputs (PDF etc.) the tool writes the file itself;
                    # only write JSON if the output_file doesn't already exist as a real file
                    _pdf_path = result.get("pdf_path", "") if isinstance(result, dict) else ""
                    if _pdf_path and Path(_pdf_path).exists() and Path(_pdf_path).stat().st_size > 1024:
                        # Tool wrote the file — just log it
                        out_path_real = Path(_pdf_path)
                        if str(out_path_real) != str(out_path):
                            import shutil as _shu
                            _shu.copy2(str(out_path_real), str(out_path))
                        log.info("Stage [%s]: wrote %s", stage_name, out_path)
                    elif out_path.suffix in (".pdf", ".png", ".jpg") and out_path.exists() and out_path.stat().st_size > 1024:
                        log.info("Stage [%s]: output already at %s", stage_name, out_path)
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
            _exc = _tb.format_exc()
            log.warning("Stage [%s] failed:\n%s", stage_name, _exc)
            stage_outputs[stage_name] = {"error": "stage failed"}
            tpl_vars["stages"][stage_name] = {"output": "", "outputs": {}}

    return stage_outputs
