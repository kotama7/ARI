"""
ari/pipeline.py — Generic workflow execution engine

Driven entirely by workflow.yaml (or pipeline.yaml for backward compat).
No hardcoded tool names. Data flow is declared in the YAML.
Adding a new skill or stage requires only YAML changes — no code changes.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)


def parse_metric_from_experiment_md(text: str) -> str:
    """Parse the primary metric from an experiment.md ``Metrics:`` line.

    Used as the last-resort source for ``evaluation_criteria.json`` when the
    user pre-supplies an experiment description and the agent never invokes
    ``generate_ideas``. Returns the first metric token, e.g. ``"GB/s"`` from
    ``"Metrics: GB/s, GFlops/s"``. Returns ``""`` when no Metrics line is found.
    """
    if not text:
        return ""
    m = re.search(r"(?im)^\s*Metrics?\s*[:\-]\s*(.+)$", text)
    if not m:
        return ""
    raw = m.group(1).strip()
    first = re.split(r"[,\s]+", raw, maxsplit=1)[0].strip(" .;")
    return first


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
# loop_back_to runtime helpers
# ---------------------------------------------------------------------------


def _should_loop_back(stage_cfg: dict, result: Any) -> bool:
    """Decide whether a stage's result triggers a loop_back_to jump.

    Supported YAML fields:
    - loop_threshold: numeric — loop if `result["score"] < loop_threshold`
    - loop_when_result_key: str — loop if `result[key]` is truthy

    Returns False if result is not a dict (no signal to act on).
    """
    if not isinstance(result, dict):
        return False
    threshold = stage_cfg.get("loop_threshold")
    if threshold is not None:
        try:
            score = float(result.get("score", 1.0))
        except (TypeError, ValueError):
            score = 1.0
        if score < float(threshold):
            return True
    when_key = stage_cfg.get("loop_when_result_key")
    if when_key and result.get(when_key):
        return True
    return False


def _format_vlm_feedback(result: dict) -> str:
    """Flatten a VLM-style review result dict into a text block suitable for
    injection into a regeneration stage's system prompt.

    Consumes keys produced by vlm-skill:review_figure and review_figures_all:
        score, issues, suggestions, review_text. The aggregate variant also
        emits per_figure (ignored here — feedback to the regenerator goes
        through the prefixed [fig_id] entries already in issues/suggestions).
    """
    parts: list[str] = []
    if "score" in result:
        try:
            parts.append(f"Previous VLM score: {float(result['score']):.2f}")
        except (TypeError, ValueError):
            parts.append(f"Previous VLM score: {result['score']}")
    _issues = result.get("issues") or []
    if isinstance(_issues, str):
        _issues = [_issues]
    if _issues:
        parts.append("Issues reported: " + "; ".join(str(i) for i in _issues))
    _sugg = result.get("suggestions") or []
    if isinstance(_sugg, str):
        _sugg = [_sugg]
    if _sugg:
        parts.append("Suggested improvements: " + "; ".join(str(s) for s in _sugg))
    if result.get("review_text"):
        parts.append(f"Reviewer notes: {result['review_text']}")
    return "\n".join(parts)


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

    def _sort_key(n) -> float:
        """Score a node by its scientific_score (set by LLM evaluator).

        The evaluator LLM judges scientific contribution and stores the result
        in metrics["_scientific_score"]. This is the authoritative ranking signal.
        Fallback to any float metric only when no evaluator score exists.
        """
        # Primary: LLM-assigned scientific score (0.0-1.0, set by evaluator)
        sci = (n.metrics or {}).get("_scientific_score")
        if sci is not None:
            return float(sci)
        # Secondary: eval_summary numeric score if present
        import re as _re_sk
        if n.eval_summary:
            m = _re_sk.search(r"score[: ]+([0-9.]+)", n.eval_summary, _re_sk.IGNORECASE)
            if m:
                return float(m.group(1))
        # Fallback: max of any float metric (last resort, no domain filtering)
        floats = [v for v in (n.metrics or {}).values() if isinstance(v, float) and 0 < v < 1e9]
        return max(floats, default=0.0)

    results.sort(key=_sort_key, reverse=True)

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
        summary = (r.eval_summary or "")[:300]
        context_lines.append(f"  [{rank}] metrics={metrics_str}")
        if summary:
            context_lines.append(f"    summary: {summary}")
    return "\n".join(context_lines), results[0].metrics if results else {}


def _extract_keywords_from_nodes(nodes_json_path: str, base_topic: str = "") -> str:
    """Extract search keywords from BFTS nodes_tree.json.

    Collects eval_summary text from successful nodes and asks LLM to extract
    a concise academic search query (no domain-specific hardcoding).
    Falls back to base_topic if LLM call fails.
    """
    base = base_topic.strip() if base_topic else "research experiment"
    try:
        import json as _json
        with open(nodes_json_path) as _f:
            _data = _json.load(_f)
        _nodes = _data.get("nodes", [])
        _summaries = [
            n.get("eval_summary", "")
            for n in _nodes
            if n.get("status") == "success" and n.get("eval_summary")
        ][:5]
        if not _summaries:
            return base
        _combined = " ".join(_summaries)[:1200]
        import litellm as _litellm, os as _os
        _model = _os.environ.get("ARI_MODEL", "gpt-4o-mini")
        _backend = _os.environ.get("ARI_BACKEND", "ollama")
        if _backend == "ollama" and not _model.startswith(("ollama/", "ollama_chat/")):
            _model = f"ollama_chat/{_model}"
        elif _backend in ("claude", "anthropic") and not _model.startswith("anthropic/"):
            _model = f"anthropic/{_model}"
        _kw: dict = dict(
            model=_model,
            messages=[{
                "role": "system",
                "content": (
                    "You are a research librarian. "
                    "Given experiment summaries, produce a SHORT broad academic search query "
                    "(3-6 words) for Semantic Scholar. "
                    "Use GENERAL terms (e.g. 'algorithm optimization', not 'custom 4-stage pipelined batch-norm fused kernel'). "
                    "Avoid domain-specific jargon, acronyms, or overly narrow terms. "
                    "Return ONLY the query string, no explanation."
                ),
            }, {
                "role": "user",
                "content": f"Experiment summaries:\n{_combined}",
            }],
            max_tokens=30,
        )
        # gpt-5* models only support temperature=1
        _raw_model = _os.environ.get("ARI_MODEL", "")
        if not _raw_model.startswith("gpt-5"):
            _kw["temperature"] = 0.0
        if _backend == "ollama":
            _kw["api_base"] = _os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        _kw["metadata"] = {"phase": "pipeline", "skill": "search_query"}
        _resp = _litellm.completion(**_kw)
        _query = (_resp.choices[0].message.content or "").strip().strip('"')
        return _query if _query else base
    except Exception:
        return base


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


def _run_react_stage(
    stage_cfg: dict,
    args: dict,
    tpl_vars: dict,
    config_path: str,
    checkpoint_dir: Path,
    stage_name: str,
) -> dict:
    """Drive a pre_tool → ReAct loop → post_tool stage.

    The stage YAML declares:

        react:
          agent_phase: reproduce      # phase filter for MCP tool exposure
          max_steps: 40
          final_tool: report_metric
          sandbox: '{{checkpoint_dir}}/repro_sandbox'
          system_prompt: |
            ...
          user_prompt: |
            ...
        pre_tool: extract_repro_config     # one-shot MCP call before ReAct
        post_tool: build_repro_report      # one-shot MCP call after ReAct

    Template variables available in system_prompt/user_prompt:
      - {{sandbox}} — resolved sandbox path
      - {{pre.X}}   — fields returned by pre_tool
      - {{<input>}} — any stage input key
      - {{checkpoint_dir}}, {{ari_root}}, … — the usual pipeline templates
    """
    react_cfg   = stage_cfg.get("react") or {}
    skill_name  = stage_cfg.get("skill", "")
    pre_tool    = stage_cfg.get("pre_tool", "")
    post_tool   = stage_cfg.get("post_tool", "")
    agent_phase = react_cfg.get("agent_phase", "reproduce")
    final_tool  = react_cfg.get("final_tool", "report_metric")
    try:
        max_steps = int(react_cfg.get("max_steps", 40))
    except (TypeError, ValueError):
        max_steps = 40

    # ── Sandbox ─────────────────────────────────────────────────────
    sandbox_tpl = react_cfg.get("sandbox", "")
    sandbox: Path | None = None
    if sandbox_tpl:
        sandbox_str = _resolve_templates(sandbox_tpl, tpl_vars)
        if sandbox_str:
            sandbox = Path(sandbox_str)
            sandbox.mkdir(parents=True, exist_ok=True)

    # ── Pre-tool: extract claimed config ────────────────────────────
    pre_result: dict = {}
    if pre_tool:
        log.info("Stage [%s] pre_tool: %s", stage_name, pre_tool)
        # Forward the whole args dict; the tool picks what it needs.
        try:
            pre_result = _run_stage_subprocess(
                pre_tool, dict(args), config_path, skill_name=skill_name,
            )
        except Exception as e:
            log.error("Stage [%s] pre_tool '%s' failed: %s", stage_name, pre_tool, e)
            return {"error": f"pre_tool {pre_tool} failed: {e}", "verdict": "ERROR"}
        if isinstance(pre_result, dict) and pre_result.get("error"):
            return {
                "error": f"pre_tool error: {pre_result.get('error')}",
                "verdict": "ERROR",
                "claimed_config": pre_result,
            }
        if not isinstance(pre_result, dict):
            pre_result = {"value": pre_result}

    # ── Prompt building ─────────────────────────────────────────────
    local_vars = dict(tpl_vars)
    local_vars["pre"] = pre_result
    local_vars["sandbox"] = str(sandbox) if sandbox is not None else ""
    for k, v in args.items():
        local_vars.setdefault(k, v)

    system_prompt = _resolve_templates(
        react_cfg.get("system_prompt", ""), local_vars,
    )
    user_prompt = _resolve_templates(
        react_cfg.get("user_prompt", ""), local_vars,
    )
    if not system_prompt or not user_prompt:
        return {
            "error": "react block missing system_prompt or user_prompt",
            "verdict": "ERROR",
            "claimed_config": pre_result,
        }

    # ── Build MCPClient + LLM (in-process) ──────────────────────────
    from ari.agent.react_driver import run_react as _run_react
    from ari.config import load_config as _load_cfg
    from ari.llm.client import LLMClient as _LLM
    from ari.mcp.client import MCPClient as _MCP

    # Point coding-skill's run_bash (and friends) at the sandbox before MCP
    # servers are spawned — their env is snapshotted at fork time, so setting
    # ARI_WORK_DIR *after* the spawn has no effect. We restore the original
    # value in the finally block below so the rest of the pipeline is
    # unaffected.
    _prev_work_dir = os.environ.get("ARI_WORK_DIR")
    if sandbox is not None:
        os.environ["ARI_WORK_DIR"] = str(sandbox)

    _cfg = _load_cfg(config_path)
    _llm = _LLM(_cfg.llm)
    _mcp = _MCP(
        _cfg.skills,
        disabled_tools=getattr(_cfg, "disabled_tools", []) or [],
    )
    # Warm the tool cache once; subsequent phase filters read from it.
    try:
        _mcp.list_tools()
    except Exception as _warm_exc:
        log.warning("Stage [%s]: MCP warm-up had errors: %s", stage_name, _warm_exc)

    # Paths the agent may legitimately reach outside the sandbox
    # (the paper text it's reproducing from).
    allow_paths: list[Path] = []
    for _allow_key in ("paper_path",):
        _v = args.get(_allow_key)
        if _v and Path(str(_v)).exists():
            allow_paths.append(Path(str(_v)))

    # ── Run the ReAct loop ──────────────────────────────────────────
    log.info(
        "Stage [%s]: react starts (phase=%s, final_tool=%s, max_steps=%d, "
        "sandbox=%s)",
        stage_name, agent_phase, final_tool, max_steps, sandbox,
    )
    try:
        _react_out = _run_react(
            _llm, _mcp,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            agent_phase=agent_phase,
            final_tool=final_tool,
            max_steps=max_steps,
            sandbox=sandbox,
            allow_paths=allow_paths,
            log_dir=sandbox if sandbox else checkpoint_dir,
        )
    except Exception as e:
        log.exception("Stage [%s]: react_driver crashed: %s", stage_name, e)
        return {
            "error": f"react_driver crashed: {type(e).__name__}: {e}",
            "verdict": "ERROR",
            "claimed_config": pre_result,
        }
    finally:
        try:
            _mcp.close_all()
        except Exception:
            pass
        # Restore ARI_WORK_DIR for the rest of the pipeline.
        if sandbox is not None:
            if _prev_work_dir is None:
                os.environ.pop("ARI_WORK_DIR", None)
            else:
                os.environ["ARI_WORK_DIR"] = _prev_work_dir

    # ── Post-tool: compose verdict + interpretation ─────────────────
    final_args = _react_out.get("final_args") or {}
    actual_value = final_args.get("value") if isinstance(final_args, dict) else None
    actual_unit  = final_args.get("unit", "") if isinstance(final_args, dict) else ""
    actual_notes = final_args.get("notes", "") if isinstance(final_args, dict) else ""

    report: dict = {}
    if post_tool:
        log.info("Stage [%s] post_tool: %s", stage_name, post_tool)
        _post_args: dict = {
            "claimed_config": pre_result,
            "actual_value":   actual_value,
            "actual_unit":    actual_unit,
            "actual_notes":   actual_notes,
        }
        # Forward tolerance_pct and any other scalar inputs the post_tool expects.
        for _extra_key in ("tolerance_pct",):
            if _extra_key in args:
                _post_args[_extra_key] = args[_extra_key]
        try:
            report = _run_stage_subprocess(
                post_tool, _post_args, config_path, skill_name=skill_name,
            )
        except Exception as e:
            log.error("Stage [%s] post_tool '%s' failed: %s", stage_name, post_tool, e)
            report = {
                "error": f"post_tool {post_tool} failed: {e}",
                "verdict": "ERROR",
                "claimed_config": pre_result,
                "actual_value":   actual_value,
            }

    if not isinstance(report, dict):
        report = {"value": report}
    if not report:
        report = {
            "claimed_config": pre_result,
            "actual_value":   actual_value,
            "actual_unit":    actual_unit,
            "actual_notes":   actual_notes,
        }

    # Enrich with ReAct-loop metadata for observability.
    report.setdefault("react_status", _react_out.get("status", ""))
    report.setdefault("react_steps",  _react_out.get("tool_calls_count", 0))
    if not final_args:
        report.setdefault("react_warning", "agent did not call final_tool")
    return report


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
    # Pass checkpoint_dir to subprocess so cost_tracker can write there
    _ckpt_env_val = repr(str(_os_sp.environ.get("ARI_CHECKPOINT_DIR", "")))
    script = (
        "import json, sys, os\n"
        "sys.path.insert(0, " + _ari_root + ")\n"
        "# Initialize cost tracker for MCP skill LLM calls\n"
        "_ckpt_dir = os.environ.get('ARI_CHECKPOINT_DIR', '') or " + _ckpt_env_val + "\n"
        "if _ckpt_dir:\n"
        "    try:\n"
        "        from ari import cost_tracker as _ct\n"
        "        _ct.init(_ckpt_dir)\n"
        "    except Exception:\n"
        "        pass\n"
        "from ari.mcp.client import MCPClient\n"
        "from ari.config import load_config\n"
        "from pathlib import Path as _P\n"
        "_cfg_path = " + _cfg + "\n"
        "if not _cfg_path:\n"
        "    _pkg_cfg = _P(__file__).parents[1] / 'config' / 'workflow.yaml'\n"
        "    _cfg_path = str(_pkg_cfg) if _pkg_cfg.exists() else _cfg_path\n"
        "cfg = load_config(_cfg_path)\n"
        + _skill_filter +
        "mcp = MCPClient(skills, disabled_tools=getattr(cfg, 'disabled_tools', []) or [])\n"
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
                  "ANTHROPIC_API_KEY", "SLURM_LOG_DIR", "ARI_WORK_DIR", "ARI_ROOT",
                  "ARI_CHECKPOINT_DIR"):
        if _ekey in _os_sp.environ:
            _sub_env[_ekey] = _os_sp.environ[_ekey]
    # Propagate LLM config from workflow.yaml to env so skills use the correct model
    if config_path and "ARI_LLM_MODEL" not in _sub_env:
        try:
            from ari.config import load_config as _load_cfg
            _cfg_for_env = _load_cfg(config_path)
            if _cfg_for_env.llm.model:
                _sub_env["ARI_LLM_MODEL"] = _cfg_for_env.llm.model
            if _cfg_for_env.llm.base_url is not None:
                _sub_env["ARI_LLM_API_BASE"] = _cfg_for_env.llm.base_url
        except Exception:
            pass
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
        log.warning("Stage subprocess stderr: %s", proc.stderr[:1000])
    raw = proc.stdout.strip()
    if not raw:
        raise RuntimeError(f"Empty stdout. stderr: {proc.stderr[:1000]}")
    parsed = json.loads(raw)
    # Detect MCP-level errors returned as data (e.g. "Tool '...' not found. Available: []")
    if isinstance(parsed, dict) and "error" in parsed and not any(
        k for k in parsed if k != "error"
    ):
        raise RuntimeError(f"MCP tool error: {parsed['error']}")
    return parsed


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

    # Propagate checkpoint_dir to subprocess env so cost_tracker can log there
    import os as _os_pipe
    _os_pipe.environ["ARI_CHECKPOINT_DIR"] = str(checkpoint_dir)

    # Mark paper pipeline start for GUI phase detection
    try:
        (checkpoint_dir / ".pipeline_started").touch()
    except Exception:
        pass

    # ── Initialize cost tracker ──────────────────────────────────────────────
    try:
        from ari import cost_tracker as _ct
        _ct.init(checkpoint_dir)
    except Exception as _cte:
        log.warning("Cost tracker init failed: %s", _cte)

    # Extract evaluation_criteria from nodes (set by generate_ideas in loop.py)
    # Written to checkpoint as evaluation_criteria.json for downstream use
    _eval_criteria_path = checkpoint_dir / "evaluation_criteria.json"
    if not _eval_criteria_path.exists():
        _ec = {"primary_metric": "", "higher_is_better": True, "metric_rationale": ""}
        # Strategy 1: check node memory_snapshot (populated if memory.add() succeeded)
        for _n in all_nodes:
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
        # Strategy 2: fallback to idea.json (always available when generate_ideas ran)
        if not _ec["primary_metric"]:
            try:
                _idea_ec_path = Path(checkpoint_dir) / "idea.json"
                if _idea_ec_path.exists():
                    _idea_ec = json.loads(_idea_ec_path.read_text())
                    _ec["primary_metric"] = _idea_ec.get("primary_metric", "")
                    _ec["higher_is_better"] = _idea_ec.get("higher_is_better", True)
                    _ec["metric_rationale"] = _idea_ec.get("metric_rationale", "")
            except Exception:
                pass
        # Strategy 3: parse experiment.md for a "Metrics:" line. Triggered when
        # the user pre-supplies an experiment description and the agent never
        # calls generate_ideas (so neither memory nor idea.json carry a metric).
        if not _ec["primary_metric"]:
            try:
                _exp_md = Path(checkpoint_dir) / "experiment.md"
                if _exp_md.exists():
                    _first = parse_metric_from_experiment_md(
                        _exp_md.read_text(errors="ignore")
                    )
                    if _first:
                        _ec["primary_metric"] = _first
                        _ec["metric_rationale"] = (
                            f"Parsed from experiment.md Metrics line ({_first})"
                        )
            except Exception:
                pass
        try:
            _eval_criteria_path.write_text(json.dumps(_ec, indent=2))
            log.info("Saved evaluation_criteria.json: primary_metric=%s", _ec["primary_metric"])
        except Exception as _ece:
            log.warning("Failed to save evaluation_criteria.json: %s", _ece)

    # Save nodes_tree.json (referenced by downstream stages via {{ckpt}}/nodes_tree.json)
    # enrich each node with its memory entries so
    # downstream stages (transform, paper, EAR) become memory-aware without
    # issuing an MCP call themselves.
    nodes_json_path = str(checkpoint_dir / "nodes_tree.json")
    try:
        try:
            from ari_skill_memory.backends import get_backend as _get_mem_backend
            _mem_backend = _get_mem_backend(checkpoint_dir=checkpoint_dir)
        except Exception as _mbe:
            log.warning("pipeline: memory backend unavailable: %s", _mbe)
            _mem_backend = None

        _max_entries = int(os.environ.get("ARI_TRANSFORM_MEMORY_MAX_ENTRIES", "20") or 20)
        _max_chars = int(os.environ.get("ARI_TRANSFORM_MEMORY_MAX_CHARS", "2000") or 2000)

        def _cap_memory_entries(entries: list[dict]) -> list[dict]:
            entries = sorted(
                entries or [], key=lambda e: e.get("ts", 0.0), reverse=True
            )[:_max_entries]
            capped = []
            for e in entries:
                t = e.get("text", "") or ""
                if len(t) > _max_chars:
                    t = t[:_max_chars] + "…[truncated]"
                capped.append({
                    "text": t,
                    "metadata": e.get("metadata", {}) or {},
                    "ts": e.get("ts", 0.0),
                })
            return capped

        nodes_data = []
        for _n in all_nodes:
            d = _n.to_dict()
            if _mem_backend is not None:
                try:
                    res = _mem_backend.get_node_memory(_n.id)
                    entries = res.get("entries", []) or []
                except Exception as _e_enrich:
                    log.warning(
                        "pipeline: memory enrichment failed for node %s: %s",
                        _n.id, _e_enrich,
                    )
                    entries = []
                d["memory"] = _cap_memory_entries(entries)
            else:
                d["memory"] = []
            nodes_data.append(d)
        Path(nodes_json_path).write_text(
            json.dumps({"experiment_goal": experiment_goal, "nodes": nodes_data},
                       ensure_ascii=False, indent=2)
        )
    except Exception as _e:
        log.error("CRITICAL: Failed to save nodes_tree.json: %s — paper pipeline stages may fail", _e)
        nodes_json_path = ""

    # Convert topic slug (e.g. "My_Research_Topic_v2") -> search query ("My Research Topic v2")
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
    _static_ctx = (_wf_cfg.get("paper_context") or "").strip()

    # Load LLM-extracted experiment context from science_data.json if available.
    # This contains hardware info, methodology, findings extracted by the transform stage.
    _exp_ctx_str = ""
    try:
        import json as _json
        _sd_path = Path(checkpoint_dir) / "science_data.json"
        if _sd_path.exists():
            _sd = _json.loads(_sd_path.read_text())
            _exp_ctx = _sd.get("experiment_context", {})
            if _exp_ctx and not _exp_ctx.get("error"):
                # Prioritize key_results and implementation_details at the front
                # so they survive truncation in downstream prompts.
                _priority_parts = []
                for _pk in ("_best_node_source_code", "key_results", "key_validated_results", "implementation_details", "reported_problem_instances"):
                    if _pk in _exp_ctx:
                        _priority_parts.append(f"{_pk}: {_json.dumps(_exp_ctx[_pk], ensure_ascii=False, indent=2)}")
                _rest = {k: v for k, v in _exp_ctx.items()
                         if k not in ("key_results", "implementation_details", "reported_problem_instances")}
                _exp_ctx_str = (
                    "Experiment context (LLM-extracted from raw artifacts):\n"
                    + "\n".join(_priority_parts)
                    + "\n" + _json.dumps(_rest, ensure_ascii=False, indent=2)
                )
    except Exception as _ece:
        log.warning("Could not load experiment_context from science_data.json: %s", _ece)

    # Load idea.json: inject VirSci-generated research direction into paper context
    _idea_ctx_str = ""
    try:
        _idea_path = Path(checkpoint_dir) / "idea.json"
        if _idea_path.exists():
            _idea_data = json.loads(_idea_path.read_text())
            _gap = _idea_data.get("gap_analysis", "")
            _ideas = _idea_data.get("ideas", [])
            if _ideas:
                _best_idea = _ideas[0]
                _parts_idea = []
                if _gap:
                    _parts_idea.append(f"Research gap analysis: {_gap[:500]}")
                _parts_idea.append(f"Research idea: {_best_idea.get('title', '')}")
                _desc = _best_idea.get("description", "")
                if _desc:
                    _parts_idea.append(f"Idea description: {_desc[:600]}")
                _plan = _best_idea.get("experiment_plan", "")
                if _plan:
                    _parts_idea.append(f"Experiment plan: {_plan[:400]}")
                _idea_ctx_str = "Research direction (AI-generated):\n" + "\n".join(_parts_idea)
                log.info("Loaded idea.json for paper context: %s", _best_idea.get("title", "")[:80])
    except Exception as _ide:
        log.warning("Could not load idea.json for paper context: %s", _ide)

    # Merge all context: static (workflow.yaml) + idea + LLM-extracted + dynamic results
    parts = [p for p in [_static_ctx, _idea_ctx_str, _exp_ctx_str, context] if p.strip()]
    _paper_ctx = "\n\n".join(parts) if parts else context

    # Template variable registry — grows as stages complete
    import os as _os
    tpl_vars: dict = {
        "ckpt":              str(checkpoint_dir),
        "checkpoint_dir":    str(checkpoint_dir),
        "context":           context,
        "experiment_summary": context,
        "paper_context":     _paper_ctx,
        "slurm_partition":   _wf_cfg.get("slurm_partition", ""),  # resolved at runtime via ARI_SLURM_PARTITION env
        "keywords":          keywords,
        "idea_context":      _idea_ctx_str,
        "stages":            {},
        "ari_root":          _os.environ.get("ARI_ROOT", str(Path(__file__).parents[2])),
        # Reproducibility check reads only the paper — no source_file injection.
        # Providing original source would be "repeat experiment", not "reproduce from paper".
        "experiment_source_file": _os.environ.get("ARI_SOURCE_FILE", ""),
        "author_name":       "Artificial Research Intelligence",  # default; overridden by workflow.yaml
        # Expose all top-level string/int config values for template substitution
        **{k: str(v) for k, v in _wf_cfg.items() if isinstance(v, (str, int, float)) and k not in ("paper_context",)},
        # Expose nested dicts (e.g. resources, bfts) as nested keys for dot-notation access
        **{section: sec_val
           for section, sec_val in _wf_cfg.items()
           if isinstance(sec_val, dict) and section not in ("pipeline", "skills", "stages")},
    }

    stage_outputs: dict[str, Any] = {}

    # Index-based iteration so loop_back_to can rewind the cursor. A
    # per-source-stage counter caps total iterations so a misbehaving VLM
    # reviewer cannot pin the pipeline in an infinite regenerate loop.
    _loop_iterations: dict[str, int] = {}
    # Initialise the feedback slot so {{vlm_feedback}} resolves to "" on
    # the first pass (before any loop has injected real feedback).
    tpl_vars.setdefault("vlm_feedback", "")

    _stage_idx = 0
    while _stage_idx < len(stages):
        stage_cfg = stages[_stage_idx]
        stage_name = stage_cfg.get("stage", "unknown")
        skill_key  = stage_cfg.get("skill", "")
        skill = skill_key if ("skill" in skill_key) else (skill_key + "-skill" if skill_key else "")
        tool  = stage_cfg.get("tool", "")
        desc  = stage_cfg.get("description", stage_name)

        log.info("=== Stage [%s]: %s ===", stage_name, desc)
        print(f"[Paper Pipeline] Stage [{stage_name}]: {desc} ...", flush=True)

        # ── disabled_tools check ────────────────────────────────────────
        # Honour tools toggled off in the GUI Workflow page.
        _disabled = set(_wf_cfg.get("disabled_tools") or [])
        if tool and tool in _disabled:
            log.info("Stage [%s]: tool '%s' is disabled_tools; skip", stage_name, tool)
            print(f"[Paper Pipeline] Stage [{stage_name}]: SKIPPED (tool '{tool}' disabled)", flush=True)
            stage_outputs[stage_name] = {"skipped": True, "reason": f"tool disabled: {tool}"}
            tpl_vars["stages"][stage_name] = {"output": "", "outputs": {}}
            _stage_idx += 1
            continue

        # ── depends_on check ─────────────────────────────────────────────
        _depends = stage_cfg.get("depends_on", [])
        if isinstance(_depends, str): _depends = [_depends]
        _dep_missing = next((_d for _d in _depends if _d not in tpl_vars.get("stages", {})), None)
        # Also check if any dependency actually failed (registered but has no output)
        _dep_failed = next(
            (_d for _d in _depends
             if _d in tpl_vars.get("stages", {})
             and not tpl_vars["stages"][_d].get("output")
             and _d in stage_outputs
             and isinstance(stage_outputs.get(_d), dict)
             and ("error" in stage_outputs[_d] or stage_outputs[_d].get("skipped"))),
            None,
        )
        _dep_fail = _dep_missing or _dep_failed
        if _dep_fail:
            _reason = "not resolved" if _dep_missing else "failed or skipped"
            log.warning("Stage [%s]: dep '%s' %s; skip", stage_name, _dep_fail, _reason)
            print(f"[Paper Pipeline] Stage [{stage_name}]: SKIPPED (dep '{_dep_fail}' {_reason})", flush=True)
            stage_outputs[stage_name] = {"skipped": True, "reason": f"dep {_reason}: {_dep_fail}"}
            tpl_vars["stages"][stage_name] = {"output": "", "outputs": {}}
            _stage_idx += 1
            continue

        # ── skip_if_exists check ──────────────────────────────────────────
        skip_path_tpl = stage_cfg.get("skip_if_exists", "")
        if skip_path_tpl:
            skip_path = _resolve_templates(skip_path_tpl, tpl_vars)
            _skip_file = Path(skip_path)
            _skip_ok = False
            if _skip_file.exists():
                # If the file is JSON, check it doesn't contain an "error" key at the top level
                if _skip_file.suffix == ".json":
                    try:
                        _skip_data = json.loads(_skip_file.read_text())
                        _skip_ok = isinstance(_skip_data, dict) and "error" not in _skip_data
                    except Exception:
                        _skip_ok = False
                else:
                    _skip_ok = _skip_file.stat().st_size > 0
            if _skip_ok:
                log.info("Stage [%s]: skipping (output exists: %s)", stage_name, skip_path)
                print(f"[Paper Pipeline] Stage [{stage_name}]: SKIPPED (output exists)", flush=True)
                tpl_vars["stages"][stage_name] = {"output": skip_path, "outputs": {"file": skip_path}}
                stage_outputs[stage_name] = {"skipped": True, "output": skip_path}
                _stage_idx += 1
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

        try:
            # ── tool call (with retry on transient connection errors) ─────────
            import time as _retry_time
            _max_retries = 5
            _last_exc = None
            result = None
            # Stages declaring a `react:` block run a ReAct loop between an
            # optional pre_tool (config extraction) and post_tool (report
            # building). See ari.agent.react_driver.
            if stage_cfg.get("react"):
                log.info(
                    "Stage [%s]: react block present; pre=%s post=%s phase=%s",
                    stage_name, stage_cfg.get("pre_tool", ""),
                    stage_cfg.get("post_tool", ""),
                    stage_cfg.get("react", {}).get("agent_phase", "reproduce"),
                )
                result = _run_react_stage(
                    stage_cfg=stage_cfg,
                    args=args,
                    tpl_vars=tpl_vars,
                    config_path=config_path,
                    checkpoint_dir=checkpoint_dir,
                    stage_name=stage_name,
                )
            else:
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
                        raise RuntimeError(f"Stage [{stage_name}]: tool returned no latex content")
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
                fig_kinds = result.get("figure_kinds", {}) if isinstance(result, dict) else {}
                if figs and primary_file:
                    manifest = {"figures": figs}
                    if latex_snips:
                        manifest["latex_snippets"] = latex_snips
                    if fig_kinds:
                        manifest["figure_kinds"] = fig_kinds
                    Path(primary_file).write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
                    log.info("Stage [%s]: wrote figures manifest %s (latex_snippets=%d, kinds=%d)",
                             stage_name, primary_file, len(latex_snips), len(fig_kinds))

            # Stage completed successfully
            print(f"[Paper Pipeline] Stage [{stage_name}]: DONE", flush=True)

            # ── loop_back_to runtime ─────────────────────────────────────
            # If this stage declares a `loop_back_to` target and its result
            # meets the `loop_threshold` / `loop_when_result_key` condition,
            # rewind the stage cursor to the target and re-run the range,
            # injecting any review feedback into tpl_vars so the upstream
            # stage can consume it (e.g. {{vlm_feedback}} in plot-skill).
            _loop_target = stage_cfg.get("loop_back_to")
            if _loop_target and _should_loop_back(stage_cfg, result):
                _count = _loop_iterations.get(stage_name, 0)
                try:
                    _max_iter = int(stage_cfg.get("loop_max_iterations", 2))
                except (TypeError, ValueError):
                    _max_iter = 2
                if _count >= _max_iter:
                    log.info(
                        "[loop_back] %s: loop_max_iterations (%d) reached; proceeding",
                        stage_name, _max_iter,
                    )
                    print(
                        f"[Paper Pipeline] Stage [{stage_name}]: loop max "
                        f"({_max_iter}) reached, proceeding",
                        flush=True,
                    )
                else:
                    _target_idx = next(
                        (i for i, s in enumerate(stages)
                         if s.get("stage") == _loop_target and i < _stage_idx),
                        None,
                    )
                    if _target_idx is None:
                        log.warning(
                            "[loop_back] %s: target '%s' not found earlier in "
                            "pipeline; ignoring loop directive",
                            stage_name, _loop_target,
                        )
                    else:
                        _loop_iterations[stage_name] = _count + 1
                        # Surface review feedback to downstream template vars
                        tpl_vars["vlm_feedback"] = _format_vlm_feedback(result)
                        # Reset state for stages [target_idx .. _stage_idx]
                        # so they actually re-run (don't hit skip_if_exists
                        # on their own outputs).
                        for _reset_idx in range(_target_idx, _stage_idx + 1):
                            _reset_name = stages[_reset_idx].get("stage", "")
                            tpl_vars["stages"].pop(_reset_name, None)
                            stage_outputs.pop(_reset_name, None)
                            _reset_skip = stages[_reset_idx].get("skip_if_exists", "")
                            if _reset_skip:
                                try:
                                    _reset_path = Path(
                                        _resolve_templates(_reset_skip, tpl_vars)
                                    )
                                    _reset_path.unlink(missing_ok=True)
                                except Exception as _reset_err:
                                    log.debug(
                                        "[loop_back] could not clear skip marker "
                                        "for %s: %s",
                                        _reset_name, _reset_err,
                                    )
                        log.info(
                            "[loop_back] %s → %s (iter %d/%d); feedback injected",
                            stage_name, _loop_target, _count + 1, _max_iter,
                        )
                        print(
                            f"[Paper Pipeline] Stage [{stage_name}]: LOOPING "
                            f"BACK to {_loop_target} (iter {_count + 1}/"
                            f"{_max_iter})",
                            flush=True,
                        )
                        _stage_idx = _target_idx
                        continue  # skip the _stage_idx += 1 below

        except Exception:
            import traceback as _tb
            _exc = _tb.format_exc()
            log.warning("Stage [%s] failed:\n%s", stage_name, _exc)
            print(f"[Paper Pipeline] Stage [{stage_name}]: FAILED\n{_exc[:300]}", flush=True)
            stage_outputs[stage_name] = {"error": "stage failed"}
            tpl_vars["stages"][stage_name] = {"output": "", "outputs": {}}

        _stage_idx += 1

    return stage_outputs
