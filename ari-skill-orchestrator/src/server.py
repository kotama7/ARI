"""
ari-skill-orchestrator — ARI orchestrator MCP server with recursive sub-experiments

Tools (stdio + HTTP):
  run_experiment   Launch an ARI experiment, with optional parent_run_id,
                   recursion_depth, and max_recursion_depth for sub-experiment chains.
  get_status       Returns progress, results, and recursion metadata for a run_id.
  list_runs        Returns a list of past runs.
  list_children    Returns child runs of a given parent_run_id.
  get_paper        Returns the paper section (LaTeX) for a run_id.

Transports:
  stdio (default)  MCP stdio server (Claude Desktop, etc.)
  http             REST + SSE on ARI_ORCHESTRATOR_PORT (default 9890)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp import types
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False
    Server = None  # type: ignore
    stdio_server = None  # type: ignore
    types = None  # type: ignore


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ARI_WORKSPACE = Path(os.environ.get("ARI_WORKSPACE", Path.home() / "ARI"))
DEFAULT_LOGS_DIR = ARI_WORKSPACE / "logs"
ARI_CLI_DEFAULT = str(ARI_WORKSPACE / "ari-core" / ".venv" / "bin" / "ari")
ARI_CLI = ARI_CLI_DEFAULT if Path(ARI_CLI_DEFAULT).exists() else "ari"
DEFAULT_MAX_RECURSION_DEPTH = 3
DEFAULT_HTTP_PORT = int(os.environ.get("ARI_ORCHESTRATOR_PORT", "9890"))


def _logs_dir() -> Path:
    """Resolve the logs/checkpoints root, honoring ARI_ORCHESTRATOR_LOGS."""
    return Path(os.environ.get("ARI_ORCHESTRATOR_LOGS", str(DEFAULT_LOGS_DIR)))


# ---------------------------------------------------------------------------
# Filesystem helpers
# ---------------------------------------------------------------------------

def _slugify(text: str, maxlen: int = 40) -> str:
    s = re.sub(r"[^a-zA-Z0-9_-]", "_", text or "experiment")
    s = re.sub(r"_+", "_", s).strip("_")
    return s[:maxlen] or "experiment"


def _make_run_id(experiment_md: str) -> str:
    ts = datetime.now().strftime("%Y%m%d%H%M%S%f")
    first_line = ""
    for line in (experiment_md or "").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            first_line = stripped[:60]
            break
    return f"{ts}_{_slugify(first_line)}"


def _write_meta(
    ckpt_dir: Path,
    *,
    run_id: str,
    parent_run_id: str | None,
    recursion_depth: int,
    max_recursion_depth: int,
) -> Path:
    meta = {
        "run_id": run_id,
        "parent_run_id": parent_run_id,
        "recursion_depth": int(recursion_depth),
        "max_recursion_depth": int(max_recursion_depth),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    meta_path = ckpt_dir / "meta.json"
    meta_path.write_text(json.dumps(meta, indent=2))
    return meta_path


def _read_meta(ckpt_dir: Path) -> dict | None:
    meta_path = ckpt_dir / "meta.json"
    if not meta_path.exists():
        return None
    try:
        return json.loads(meta_path.read_text())
    except Exception:
        return None


def _iter_checkpoints(logs_dir: Path | None = None):
    base = logs_dir or _logs_dir()
    if not base.exists():
        return
    children = [p for p in base.iterdir() if p.is_dir()]
    children.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    for ckpt in children:
        if (ckpt / "meta.json").exists() or (ckpt / "results.json").exists():
            yield ckpt


def _runs(logs_dir: Path | None = None) -> list[dict]:
    runs = []
    for ckpt in _iter_checkpoints(logs_dir):
        meta = _read_meta(ckpt) or {}
        results: dict = {}
        if (ckpt / "results.json").exists():
            try:
                results = json.loads((ckpt / "results.json").read_text())
            except Exception:
                results = {}
        nodes = results.get("nodes", {}) if isinstance(results, dict) else {}
        success = sum(
            1 for v in nodes.values()
            if isinstance(v, dict) and v.get("status") == "success"
        )
        runs.append({
            "run_id": meta.get("run_id") or results.get("run_id") or ckpt.name,
            "checkpoint_dir": str(ckpt),
            "total_nodes": len(nodes),
            "success_nodes": success,
            "has_paper": (ckpt / "experiment_section.tex").exists()
                         or (ckpt / "full_paper.tex").exists(),
            "parent_run_id": meta.get("parent_run_id"),
            "recursion_depth": meta.get("recursion_depth", 0),
            "max_recursion_depth": meta.get(
                "max_recursion_depth", DEFAULT_MAX_RECURSION_DEPTH
            ),
            "created_at": meta.get("created_at"),
        })
    return runs


def _get_run(run_id: str, logs_dir: Path | None = None) -> dict | None:
    if not run_id:
        return None
    for run in _runs(logs_dir):
        if run["run_id"] == run_id or run_id in run["run_id"]:
            return run
    return None


def _list_children(parent_run_id: str, logs_dir: Path | None = None) -> list[dict]:
    if not parent_run_id:
        return []
    return [r for r in _runs(logs_dir) if r.get("parent_run_id") == parent_run_id]


# ---------------------------------------------------------------------------
# Tool implementations (transport-agnostic)
# ---------------------------------------------------------------------------

def tool_run_experiment(
    experiment_md: str,
    *,
    max_nodes: int = 10,
    model: str = "",
    max_recursion_depth: int = DEFAULT_MAX_RECURSION_DEPTH,
    parent_run_id: str | None = None,
    # LLM configuration
    llm_backend: str = "",
    llm_api_key: str = "",
    llm_base_url: str = "",
    # Resource configuration
    executor: str = "",
    cpus: int = 0,
    timeout_minutes: int = 0,
    # Retrieval configuration
    retrieval_backend: str = "",
    logs_dir: Path | None = None,
    ari_cli: str | None = None,
    workspace: Path | None = None,
) -> dict:
    """Launch an ARI experiment, returning a JSON-serializable status dict.

    Recursion semantics:
      max_recursion_depth >= 0: experiment itself runs.
      Child receives max_recursion_depth - 1.
      Child blocked when its max_recursion_depth < 0.
    So max_recursion_depth=0 means "run this experiment but no sub-experiments".
    """
    # Honor environment-based context propagation when called as a child.
    env_parent = os.environ.get("ARI_PARENT_RUN_ID")
    env_max = os.environ.get("ARI_MAX_RECURSION_DEPTH")
    if parent_run_id is None and env_parent:
        parent_run_id = env_parent
    if env_max is not None and max_recursion_depth == DEFAULT_MAX_RECURSION_DEPTH:
        try:
            max_recursion_depth = int(env_max)
        except ValueError:
            pass

    # Recursion guard: negative budget means a parent already exhausted it
    if max_recursion_depth < 0:
        return {
            "status": "blocked",
            "error": (
                f"Recursion budget exhausted: max_recursion_depth={max_recursion_depth}"
            ),
            "max_recursion_depth": max_recursion_depth,
            "parent_run_id": parent_run_id,
        }

    # Inherit from environment if not explicitly provided
    if not model:
        model = os.environ.get("ARI_MODEL", "qwen3:32b")
    if not llm_backend:
        llm_backend = os.environ.get("ARI_BACKEND", "")
    if not llm_api_key:
        llm_api_key = os.environ.get("OPENAI_API_KEY", "")
    if not llm_base_url:
        llm_base_url = os.environ.get("LLM_API_BASE", "")
    if not executor:
        executor = os.environ.get("ARI_EXECUTOR", "")
    if not retrieval_backend:
        retrieval_backend = os.environ.get("ARI_RETRIEVAL_BACKEND", "")

    base = Path(logs_dir) if logs_dir else _logs_dir()
    base.mkdir(parents=True, exist_ok=True)
    ws = Path(workspace) if workspace else ARI_WORKSPACE
    cli = ari_cli or ARI_CLI

    run_id = _make_run_id(experiment_md)
    ckpt_dir = base / run_id
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    _write_meta(
        ckpt_dir,
        run_id=run_id,
        parent_run_id=parent_run_id,
        recursion_depth=0,
        max_recursion_depth=max_recursion_depth,
    )

    exp_file = ckpt_dir / "experiment.md"
    try:
        exp_file.write_text(experiment_md or "", encoding="utf-8")
    except Exception:
        pass

    log_path = ckpt_dir / "orchestrator.log"
    cmd = [
        cli, "run", str(exp_file),
    ]
    proc_env = os.environ.copy()
    if max_nodes:
        proc_env["ARI_MAX_NODES"] = str(int(max_nodes))
    # Child gets max_recursion_depth - 1 so the budget naturally decreases
    proc_env["ARI_PARENT_RUN_ID"] = run_id
    proc_env["ARI_MAX_RECURSION_DEPTH"] = str(max_recursion_depth - 1)
    proc_env["ARI_CHECKPOINT_DIR"] = str(ckpt_dir)
    # Propagate LLM / resource / retrieval configuration
    if model:
        proc_env["ARI_MODEL"] = model
    if llm_backend:
        proc_env["ARI_BACKEND"] = llm_backend
    if llm_api_key:
        proc_env["OPENAI_API_KEY"] = llm_api_key
    if llm_base_url:
        proc_env["LLM_API_BASE"] = llm_base_url
    if executor:
        proc_env["ARI_EXECUTOR"] = executor
    if cpus:
        proc_env["ARI_CPUS"] = str(cpus)
    if timeout_minutes:
        proc_env["ARI_TIMEOUT_MINUTES"] = str(timeout_minutes)
    if retrieval_backend:
        proc_env["ARI_RETRIEVAL_BACKEND"] = retrieval_backend

    pid: int | None = None
    if os.environ.get("ARI_ORCHESTRATOR_DRY_RUN"):
        return {
            "status": "started",
            "run_id": run_id,
            "pid": None,
            "checkpoint_dir": str(ckpt_dir),
            "log": str(log_path),
            "parent_run_id": parent_run_id,
            "max_recursion_depth": max_recursion_depth,
            "child_max_recursion_depth": max_recursion_depth - 1,
            "model": model,
            "llm_backend": llm_backend,
            "dry_run": True,
        }

    try:
        log_fh = open(log_path, "w")
        proc = subprocess.Popen(
            cmd,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            cwd=str(ws),
            env=proc_env,
        )
        pid = proc.pid
    except FileNotFoundError as e:
        return {
            "status": "error",
            "error": f"ari CLI not found: {e}",
            "run_id": run_id,
            "checkpoint_dir": str(ckpt_dir),
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "run_id": run_id,
            "checkpoint_dir": str(ckpt_dir),
        }

    return {
        "status": "started",
        "run_id": run_id,
        "pid": pid,
        "checkpoint_dir": str(ckpt_dir),
        "log": str(log_path),
        "parent_run_id": parent_run_id,
        "max_recursion_depth": max_recursion_depth,
        "child_max_recursion_depth": max_recursion_depth - 1,
        "model": model,
        "llm_backend": llm_backend,
    }


def tool_get_status(run_id: str, logs_dir: Path | None = None) -> dict:
    run = _get_run(run_id, logs_dir)
    if run is None:
        return {"error": f"run_id '{run_id}' not found"}
    ckpt = Path(run["checkpoint_dir"])
    nodes_summary: list[dict] = []
    best_score: float | None = None
    best_node_id: str | None = None
    all_scores: list[float] = []

    # Read BFTS tree for richer node data
    tree_data: dict = {}
    for tree_file in ("nodes_tree.json", "bfts_tree.json", "results.json"):
        tf = ckpt / tree_file
        if tf.exists():
            try:
                tree_data = json.loads(tf.read_text())
                break
            except Exception:
                pass

    nodes_dict = tree_data.get("nodes") or {}
    for nid, ndata in nodes_dict.items():
        if not isinstance(ndata, dict):
            continue
        m = ndata.get("metrics") or {}
        score = ndata.get("score") or ndata.get("eval_score")
        label = ndata.get("label", "")
        status = ndata.get("status")
        if isinstance(score, (int, float)):
            all_scores.append(float(score))
            if best_score is None or float(score) > best_score:
                best_score = float(score)
                best_node_id = nid
        nodes_summary.append({
            "node_id": nid[-8:] if len(nid) > 8 else nid,
            "status": status,
            "score": score,
            "label": label[:80] if label else "",
            "has_real_data": ndata.get("has_real_data", False),
            "metrics": dict(list(m.items())[:5]),
        })

    # Read science_data.json for summary if available
    research_summary = ""
    sci_path = ckpt / "science_data.json"
    if sci_path.exists():
        try:
            sci = json.loads(sci_path.read_text())
            research_summary = sci.get("research_goal", "") or sci.get("summary", "")
        except Exception:
            pass

    result: dict = {
        "run_id": run["run_id"],
        "total_nodes": run["total_nodes"],
        "success_nodes": run["success_nodes"],
        "has_paper": run["has_paper"],
        "parent_run_id": run.get("parent_run_id"),
        "max_recursion_depth": run.get(
            "max_recursion_depth", DEFAULT_MAX_RECURSION_DEPTH
        ),
        "best_score": best_score,
        "best_node_id": best_node_id,
        "score_stats": {
            "count": len(all_scores),
            "mean": sum(all_scores) / len(all_scores) if all_scores else None,
            "max": max(all_scores) if all_scores else None,
            "min": min(all_scores) if all_scores else None,
        },
        "nodes": nodes_summary,
    }
    if research_summary:
        result["research_summary"] = research_summary[:500]
    return result


def tool_list_runs(logs_dir: Path | None = None) -> list[dict]:
    return _runs(logs_dir)


def tool_list_children(parent_run_id: str, logs_dir: Path | None = None) -> list[dict]:
    return _list_children(parent_run_id, logs_dir)


def tool_get_paper(run_id: str, logs_dir: Path | None = None) -> dict:
    run = _get_run(run_id, logs_dir)
    if run is None:
        return {"error": f"run_id '{run_id}' not found"}
    candidates = [
        Path(run["checkpoint_dir"]) / "experiment_section.tex",
        Path(run["checkpoint_dir"]) / "full_paper.tex",
    ]
    for p in candidates:
        if p.exists():
            return {
                "latex": p.read_text(encoding="utf-8", errors="replace"),
                "path": str(p),
            }
    return {"error": "Paper not generated yet."}


def tool_list_files(run_id: str, logs_dir: Path | None = None) -> dict:
    """List files in a checkpoint directory."""
    run = _get_run(run_id, logs_dir)
    if run is None:
        return {"error": f"run_id '{run_id}' not found"}
    ckpt = Path(run["checkpoint_dir"])
    files: list[dict] = []
    for p in sorted(ckpt.rglob("*")):
        if p.is_file() and "__pycache__" not in str(p):
            rel = str(p.relative_to(ckpt))
            files.append({
                "path": rel,
                "size": p.stat().st_size,
                "ext": p.suffix,
            })
    return {"run_id": run["run_id"], "checkpoint_dir": str(ckpt), "files": files}


def tool_read_file(run_id: str, filename: str, logs_dir: Path | None = None) -> dict:
    """Read a text file from a checkpoint directory."""
    run = _get_run(run_id, logs_dir)
    if run is None:
        return {"error": f"run_id '{run_id}' not found"}
    ckpt = Path(run["checkpoint_dir"])
    target = ckpt / filename
    # Prevent path traversal
    try:
        target.resolve().relative_to(ckpt.resolve())
    except ValueError:
        return {"error": "Path traversal not allowed"}
    if not target.exists():
        return {"error": f"File not found: {filename}"}
    if target.stat().st_size > 2 * 1024 * 1024:
        return {"error": f"File too large ({target.stat().st_size} bytes), max 2MB"}
    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return {"error": f"Cannot read file: {e}"}
    return {"path": filename, "content": content, "size": len(content)}


def tool_get_ear(run_id: str, logs_dir: Path | None = None) -> dict:
    """Return the Experiment Analysis Report (EAR) for a run."""
    run = _get_run(run_id, logs_dir)
    if run is None:
        return {"error": f"run_id '{run_id}' not found"}
    ckpt = Path(run["checkpoint_dir"])
    ear_dir = ckpt / "ear"
    if not ear_dir.is_dir():
        return {"error": "EAR not generated yet"}
    result: dict = {"run_id": run["run_id"], "ear_dir": str(ear_dir)}
    for name in ("README.md", "results.md", "commands.md", "environment.json"):
        f = ear_dir / name
        if f.exists():
            try:
                result[name.replace(".", "_")] = f.read_text(encoding="utf-8", errors="replace")
            except Exception:
                pass
    # File listing
    result["files"] = [
        str(p.relative_to(ear_dir))
        for p in sorted(ear_dir.rglob("*")) if p.is_file()
    ]
    return result


def tool_stop_experiment(run_id: str, logs_dir: Path | None = None) -> dict:
    """Stop a running experiment by killing its process."""
    import signal
    run = _get_run(run_id, logs_dir)
    if run is None:
        return {"error": f"run_id '{run_id}' not found"}
    ckpt = Path(run["checkpoint_dir"])
    pid_file = ckpt / "pid"
    if not pid_file.exists():
        return {"error": "No PID file found — experiment may not be running"}
    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, signal.SIGTERM)
        return {"ok": True, "run_id": run["run_id"], "pid": pid, "signal": "SIGTERM"}
    except ProcessLookupError:
        return {"ok": True, "run_id": run["run_id"], "note": "Process already exited"}
    except Exception as e:
        return {"error": str(e)}


def tool_list_skills(logs_dir: Path | None = None) -> list[dict]:
    """List available MCP skills and their tools."""
    ws = ARI_WORKSPACE
    skills: list[dict] = []
    for skill_dir in sorted(ws.glob("ari-skill-*")):
        server_py = skill_dir / "src" / "server.py"
        if not server_py.exists():
            continue
        entry: dict = {"name": skill_dir.name, "dir": str(skill_dir)}
        # Read mcp.json
        mcp_file = skill_dir / "mcp.json"
        if mcp_file.exists():
            try:
                mcp_data = json.loads(mcp_file.read_text())
                entry["description"] = mcp_data.get("description", "")
                entry["tools"] = mcp_data.get("tools", [])
            except Exception:
                pass
        # Fallback: extract tool names from server.py
        if not entry.get("tools"):
            try:
                src = server_py.read_text()
                import re as _re
                tool_names = []
                for m in _re.finditer(
                    r"@mcp\.tool\(\)\s*\n\s*(?:async\s+)?def\s+(\w+)\s*\(", src
                ):
                    tool_names.append(m.group(1))
                for m in _re.finditer(r'Tool\(\s*name\s*="(\w+)"', src):
                    if m.group(1) not in tool_names:
                        tool_names.append(m.group(1))
                entry["tools"] = tool_names
            except Exception:
                pass
        # Read skill.yaml
        skill_yaml = skill_dir / "skill.yaml"
        if skill_yaml.exists():
            try:
                import yaml as _yaml
                sk = _yaml.safe_load(skill_yaml.read_text()) or {}
                entry.setdefault("description", sk.get("description", ""))
            except Exception:
                pass
        skills.append(entry)
    return skills


def tool_get_workflow(logs_dir: Path | None = None) -> dict:
    """Return the current workflow configuration."""
    ws = ARI_WORKSPACE
    candidates = [
        ws / "ari-core" / "config" / "workflow.yaml",
        ws / "config" / "workflow.yaml",
    ]
    for wf in candidates:
        if wf.exists():
            try:
                import yaml as _yaml
                data = _yaml.safe_load(wf.read_text())
                return {
                    "path": str(wf),
                    "bfts_pipeline": data.get("bfts_pipeline", []),
                    "pipeline": data.get("pipeline", []),
                    "skills": data.get("skills", []),
                    "llm": data.get("llm", {}),
                    "resources": data.get("resources", {}),
                    "retrieval": data.get("retrieval", {}),
                }
            except Exception as e:
                return {"error": str(e)}
    return {"error": "workflow.yaml not found"}


def _dispatch_tool(name: str, arguments: dict | None):
    arguments = arguments or {}
    if name == "run_experiment":
        return tool_run_experiment(
            experiment_md=arguments.get("experiment_md", ""),
            max_nodes=int(arguments.get("max_nodes", 10) or 10),
            model=arguments.get("model", "") or "",
            max_recursion_depth=int(
                arguments["max_recursion_depth"]
                if "max_recursion_depth" in arguments
                else DEFAULT_MAX_RECURSION_DEPTH
            ),
            parent_run_id=arguments.get("parent_run_id"),
            llm_backend=arguments.get("llm_backend", "") or "",
            llm_api_key=arguments.get("llm_api_key", "") or "",
            llm_base_url=arguments.get("llm_base_url", "") or "",
            executor=arguments.get("executor", "") or "",
            cpus=int(arguments.get("cpus", 0) or 0),
            timeout_minutes=int(arguments.get("timeout_minutes", 0) or 0),
            retrieval_backend=arguments.get("retrieval_backend", "") or "",
        )
    if name == "get_status":
        return tool_get_status(arguments.get("run_id", ""))
    if name == "list_runs":
        return tool_list_runs()
    if name == "list_children":
        return tool_list_children(arguments.get("parent_run_id", ""))
    if name == "get_paper":
        return tool_get_paper(arguments.get("run_id", ""))
    if name == "list_files":
        return tool_list_files(arguments.get("run_id", ""))
    if name == "read_file":
        return tool_read_file(arguments.get("run_id", ""), arguments.get("filename", ""))
    if name == "get_ear":
        return tool_get_ear(arguments.get("run_id", ""))
    if name == "stop_experiment":
        return tool_stop_experiment(arguments.get("run_id", ""))
    if name == "list_skills":
        return tool_list_skills()
    if name == "get_workflow":
        return tool_get_workflow()
    return {"error": f"Unknown tool: {name}"}


# ---------------------------------------------------------------------------
# MCP stdio transport
# ---------------------------------------------------------------------------

if MCP_AVAILABLE:
    server = Server("ari-orchestrator")  # type: ignore[misc]

    @server.list_tools()
    async def list_tools() -> list:
        return [
            types.Tool(
                name="run_experiment",
                description=(
                    "Run an experiment using ARI. Supports recursive sub-experiment "
                    "chains. Each child receives max_recursion_depth - 1. "
                    "LLM/resource/retrieval config is inherited from parent environment "
                    "if not explicitly provided. Returns immediately with a run_id."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "experiment_md": {
                            "type": "string",
                            "description": "Experiment specification (Markdown).",
                        },
                        "max_nodes": {
                            "type": "integer",
                            "description": "Maximum BFTS nodes (default: 10)",
                            "default": 10,
                        },
                        "model": {
                            "type": "string",
                            "description": "LLM model name (inherited from env if empty)",
                        },
                        "max_recursion_depth": {
                            "type": "integer",
                            "description": (
                                "Recursion budget. Child gets this - 1. "
                                "Blocked when <= 0. Default: "
                                f"{DEFAULT_MAX_RECURSION_DEPTH}."
                            ),
                            "default": DEFAULT_MAX_RECURSION_DEPTH,
                        },
                        "parent_run_id": {
                            "type": "string",
                            "description": "Parent run_id for context propagation.",
                        },
                        "llm_backend": {
                            "type": "string",
                            "description": "LLM backend: openai, ollama, etc.",
                        },
                        "llm_api_key": {
                            "type": "string",
                            "description": "API key for LLM provider.",
                        },
                        "llm_base_url": {
                            "type": "string",
                            "description": "Base URL for LLM API.",
                        },
                        "executor": {
                            "type": "string",
                            "description": "Job executor: slurm, local, etc.",
                        },
                        "cpus": {
                            "type": "integer",
                            "description": "CPU allocation for experiments.",
                        },
                        "timeout_minutes": {
                            "type": "integer",
                            "description": "Timeout per experiment in minutes.",
                        },
                        "retrieval_backend": {
                            "type": "string",
                            "description": "Paper retrieval: semantic_scholar, alphaxiv, both.",
                        },
                    },
                    "required": ["experiment_md"],
                },
            ),
            types.Tool(
                name="get_status",
                description=(
                    "Return experiment progress including best score, metrics, "
                    "node summaries, and recursion metadata for a given run_id."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "run_id": {"type": "string"},
                    },
                    "required": ["run_id"],
                },
            ),
            types.Tool(
                name="list_runs",
                description="Return a list of past experiment runs.",
                inputSchema={"type": "object", "properties": {}},
            ),
            types.Tool(
                name="list_children",
                description="Return all child runs of a given parent_run_id.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "parent_run_id": {"type": "string"},
                    },
                    "required": ["parent_run_id"],
                },
            ),
            types.Tool(
                name="get_paper",
                description="Return the paper section (LaTeX) for a run_id.",
                inputSchema={
                    "type": "object",
                    "properties": {"run_id": {"type": "string"}},
                    "required": ["run_id"],
                },
            ),
            types.Tool(
                name="list_files",
                description="List all files in a checkpoint directory for a run_id.",
                inputSchema={
                    "type": "object",
                    "properties": {"run_id": {"type": "string"}},
                    "required": ["run_id"],
                },
            ),
            types.Tool(
                name="read_file",
                description=(
                    "Read a text file from a checkpoint. Use list_files first "
                    "to discover available files."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "run_id": {"type": "string"},
                        "filename": {
                            "type": "string",
                            "description": "Relative path within checkpoint dir.",
                        },
                    },
                    "required": ["run_id", "filename"],
                },
            ),
            types.Tool(
                name="get_ear",
                description=(
                    "Return the Experiment Analysis Report (EAR): README, results, "
                    "commands, environment, and file listing."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {"run_id": {"type": "string"}},
                    "required": ["run_id"],
                },
            ),
            types.Tool(
                name="stop_experiment",
                description="Stop a running experiment by sending SIGTERM to its process.",
                inputSchema={
                    "type": "object",
                    "properties": {"run_id": {"type": "string"}},
                    "required": ["run_id"],
                },
            ),
            types.Tool(
                name="list_skills",
                description="List all available MCP skills and their tools.",
                inputSchema={"type": "object", "properties": {}},
            ),
            types.Tool(
                name="get_workflow",
                description=(
                    "Return the current workflow configuration: pipeline stages, "
                    "skills, LLM config, and resource settings."
                ),
                inputSchema={"type": "object", "properties": {}},
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list:
        try:
            result = _dispatch_tool(name, arguments)
        except Exception as e:
            result = {"error": str(e)}
        if isinstance(result, str):
            return [types.TextContent(type="text", text=result)]
        return [types.TextContent(
            type="text",
            text=json.dumps(result, ensure_ascii=False, indent=2),
        )]


# ---------------------------------------------------------------------------
# HTTP/SSE transport
# ---------------------------------------------------------------------------

class _HTTPHandler(BaseHTTPRequestHandler):
    def log_message(self, *args, **kwargs):
        pass

    def _send_json(self, payload, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0) or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length))
        except Exception:
            return {}

    def do_GET(self):
        from urllib.parse import urlparse, parse_qs
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        if u.path == "/mcp/list_runs":
            self._send_json(tool_list_runs())
            return
        if u.path == "/mcp/get_status":
            run_id = (qs.get("run_id") or [""])[0]
            self._send_json(tool_get_status(run_id))
            return
        if u.path == "/mcp/list_children":
            parent = (qs.get("parent_run_id") or [""])[0]
            self._send_json(tool_list_children(parent))
            return
        if u.path == "/mcp/get_paper":
            run_id = (qs.get("run_id") or [""])[0]
            self._send_json(tool_get_paper(run_id))
            return
        if u.path == "/mcp/list_files":
            run_id = (qs.get("run_id") or [""])[0]
            self._send_json(tool_list_files(run_id))
            return
        if u.path == "/mcp/read_file":
            run_id = (qs.get("run_id") or [""])[0]
            filename = (qs.get("filename") or [""])[0]
            self._send_json(tool_read_file(run_id, filename))
            return
        if u.path == "/mcp/get_ear":
            run_id = (qs.get("run_id") or [""])[0]
            self._send_json(tool_get_ear(run_id))
            return
        if u.path == "/mcp/list_skills":
            self._send_json(tool_list_skills())
            return
        if u.path == "/mcp/get_workflow":
            self._send_json(tool_get_workflow())
            return
        if u.path.startswith("/mcp/logs/"):
            run_id = u.path[len("/mcp/logs/"):]
            self._sse_logs(run_id)
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        if self.path == "/mcp/run_experiment":
            data = self._read_json_body()
            self._send_json(_dispatch_tool("run_experiment", data))
            return
        if self.path == "/mcp/stop_experiment":
            data = self._read_json_body()
            self._send_json(tool_stop_experiment(data.get("run_id", "")))
            return
        self.send_response(404)
        self.end_headers()

    def _sse_logs(self, run_id: str) -> None:
        run = _get_run(run_id)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        if run is None:
            try:
                self.wfile.write(
                    f"data: {json.dumps({'error': 'run not found'})}\n\n".encode()
                )
                self.wfile.flush()
            except Exception:
                pass
            return
        log_file = Path(run["checkpoint_dir"]) / "orchestrator.log"
        offset = 0
        deadline = time.time() + float(
            os.environ.get("ARI_ORCHESTRATOR_SSE_TIMEOUT", "300")
        )
        oneshot = bool(os.environ.get("ARI_ORCHESTRATOR_SSE_ONESHOT"))
        try:
            while time.time() < deadline:
                if log_file.exists():
                    with open(log_file, "r", encoding="utf-8", errors="replace") as fh:
                        fh.seek(offset)
                        chunk = fh.read()
                        offset = fh.tell()
                    if chunk:
                        for line in chunk.splitlines():
                            payload = json.dumps({"msg": line})
                            self.wfile.write(f"data: {payload}\n\n".encode())
                        self.wfile.flush()
                if oneshot:
                    break
                time.sleep(1.0)
        except (BrokenPipeError, ConnectionResetError):
            return
        try:
            self.wfile.write(b'data: {"msg": "[end of log]"}\n\n')
            self.wfile.flush()
        except Exception:
            pass


def start_http_server(port: int = DEFAULT_HTTP_PORT) -> ThreadingHTTPServer:
    """Construct (but do not start) a ThreadingHTTPServer for the orchestrator."""
    return ThreadingHTTPServer(("", port), _HTTPHandler)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def _stdio_main() -> None:
    if not MCP_AVAILABLE:
        raise SystemExit("mcp package not installed: pip install mcp")
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream, write_stream, server.create_initialization_options()
        )


def _http_main(port: int) -> None:
    srv = start_http_server(port)
    print(
        f"ARI orchestrator HTTP listening on http://0.0.0.0:{port}/",
        file=sys.stderr,
    )
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()


def main() -> None:
    ap = argparse.ArgumentParser(description="ARI Orchestrator MCP server")
    ap.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="Transport: stdio (default) or http",
    )
    ap.add_argument(
        "--port",
        type=int,
        default=DEFAULT_HTTP_PORT,
        help="HTTP port (only used with --transport http)",
    )
    args = ap.parse_args()

    if args.transport == "http":
        _http_main(args.port)
    else:
        asyncio.run(_stdio_main())


if __name__ == "__main__":
    main()
