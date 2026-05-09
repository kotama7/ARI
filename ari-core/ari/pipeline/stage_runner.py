"""Stage execution helpers (Phase 3C).

Three big helpers extracted from the legacy ``ari/pipeline.py``:

- :func:`_call_with_retry` — retry a callable on transient
  connection errors.
- :func:`_run_react_stage` — drive a YAML-declared
  pre_tool → ReAct loop → post_tool stage.
- :func:`_run_stage_subprocess` — invoke a single MCP tool via a
  one-shot Python subprocess so each stage call sees a fresh process.

The pipeline package's ``__init__`` re-exports these names; the
``run_pipeline`` orchestrator stays in ``__init__`` for now (it is the
top-level entry point).
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from ari.pipeline.yaml_loader import _resolve_templates


log = logging.getLogger(__name__)


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
          agent_phase: <phase>        # phase filter for MCP tool exposure
          max_steps: 40
          final_tool: <name>
          sandbox: '{{checkpoint_dir}}/<dir>'
          system_prompt: |
            ...
          user_prompt: |
            ...
        pre_tool:  <mcp tool name>    # one-shot MCP call before ReAct (optional)
        post_tool: <mcp tool name>    # one-shot MCP call after ReAct (optional)

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

    # ── Sandbox shims ──
    # Install <sandbox>/.shims/git and inject env vars *before* MCP spawn so
    # subprocesses inherit them. Restored in the finally block. The shim
    # rewrites `git clone <paper-URL>` to `ari clone --expect-sha256 ...`
    # and logs every clone attempt to <sandbox>/repro_clone_log.jsonl.
    from ari.agent.react_driver import setup_sandbox_shims as _setup_shims, snapshot_env as _snap_env
    _shim_env_keys = [
        "PATH", "ARI_REAL_GIT",
        "ARI_REPRO_CODE_AVAIL_REF", "ARI_REPRO_CODE_AVAIL_SHA256",
        "ARI_REPRO_CLONE_POLICY", "ARI_REPRO_CLONE_LOG",
    ]
    _shim_env_snapshot: dict[str, str | None] = {}
    if sandbox is not None:
        _shim_env_snapshot = _snap_env(_shim_env_keys)
        # Resolve ref/sha from pre_result (when the stage has a pre_tool that
        # returns code_availability_ref/_sha256) or from explicit react_cfg
        # overrides; clone policy from react_cfg (default passthrough — see
        # task.md FR-R5).
        _ref = (pre_result.get("code_availability_ref")
                if isinstance(pre_result, dict) else "") or react_cfg.get("code_availability_ref", "")
        _sha = (pre_result.get("code_availability_sha256")
                if isinstance(pre_result, dict) else "") or react_cfg.get("code_availability_sha256", "")
        _policy = react_cfg.get("clone_policy", "passthrough")
        _shim_env = _setup_shims(
            sandbox,
            code_availability_ref=str(_ref or ""),
            code_availability_sha256=str(_sha or ""),
            clone_policy=str(_policy or "passthrough"),
        )
        os.environ.update(_shim_env)
        log.info(
            "Stage [%s]: sandbox shim installed (policy=%s, ref=%s, sha=%s)",
            stage_name, _policy, (_ref or '<unset>'),
            ((_sha or '')[:16] + '…') if _sha else '<unset>',
        )

        # ── Pre-populate sandbox with the curated bundle (FR-R2). ──
        # Done *outside* the ReAct loop and *outside* MCP — direct ari.clone
        # invocation. The agent never sees this step; it just inherits a
        # populated <sandbox>/curated_bundle/ tree.
        if _ref and _sha:
            _curated_dest = sandbox / "curated_bundle"
            if _curated_dest.exists() and any(_curated_dest.iterdir()):
                log.info("Stage [%s]: curated_bundle/ already populated, skipping pre-fetch", stage_name)
            else:
                try:
                    from ari.clone import clone as _ari_clone, CloneError as _CE
                    _r = _ari_clone(_ref, dest=_curated_dest, expect_sha256=_sha)
                    log.info(
                        "Stage [%s]: curated_bundle/ populated: %d files, sha=%s",
                        stage_name, _r.file_count, (_r.bundle_sha256 or '')[:16] + '…',
                    )
                except _CE as _ce:
                    log.warning(
                        "Stage [%s]: curated_bundle pre-fetch failed: %s — continuing with empty sandbox",
                        stage_name, _ce,
                    )
                except Exception as _e:
                    log.warning(
                        "Stage [%s]: curated_bundle pre-fetch unexpected error: %s",
                        stage_name, _e,
                    )

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
            # Reverse the sandbox shim env injection.
            if _shim_env_snapshot:
                from ari.agent.react_driver import restore_env as _restore_env
                _restore_env(_shim_env_snapshot)

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

    # 2. Build the subprocess script using string concatenation (not f-string).
    # ``__file__`` is now ``ari/pipeline/stage_runner.py``; the spawned child
    # needs to add the ``ari-core/`` directory to sys.path, which is two
    # parents up (``ari-core/ari/pipeline`` → ``ari-core/ari`` → ``ari-core``).
    _ari_root = repr(str(Path(__file__).resolve().parent.parent.parent))
    _cfg = repr(config_path)
    _skill = repr(skill_name)
    _tool = repr(tool)
    _apath = repr(_args_path)
    _skill_filter = (
        "skills = [s for s in cfg.skills if s.name == " + _skill + "]\n"
        if skill_name else
        "skills = cfg.skills\n"
    )
    # Pass checkpoint_dir to subprocess so cost_tracker can write there.
    # The parent captures the env value via PathManager so this is the
    # only spot in pipeline that touches ARI_CHECKPOINT_DIR; the child
    # script itself still reads its own env at runtime (subprocess boundary).
    from ari.paths import PathManager as _PM_pipe
    _ckpt_path_pipe = _PM_pipe.checkpoint_dir_from_env()
    _ckpt_env_val = repr(str(_ckpt_path_pipe) if _ckpt_path_pipe is not None else "")
    script = (
        "import json, sys, os\n"
        "sys.path.insert(0, " + _ari_root + ")\n"
        "# Initialize cost tracker for MCP skill LLM calls\n"
        "from ari.paths import PathManager as _PM_ct\n"
        "_ckpt_dir = str(_PM_ct.checkpoint_dir_from_env() or '') or " + _ckpt_env_val + "\n"
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
