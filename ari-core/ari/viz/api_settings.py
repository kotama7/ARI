from __future__ import annotations
"""ARI viz: api_settings."""
"""ARI Experiment Tree Visualizer — WebSocket + HTTP server.

Usage:
    python -m ari.viz.server --checkpoint ./logs/my_ckpt/ [--port 8765]
"""


import argparse
import asyncio
import json
import re
import os
import subprocess
import threading
import time
import urllib.parse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Set

try:
    import websockets
    from websockets.server import serve as ws_serve
except ImportError:
    raise SystemExit("websockets package required: pip install websockets")

# ──────────────────────────────────────────────
# Shared state
# ──────────────────────────────────────────────



from . import state as _st


def _api_get_env_keys() -> dict:
    """Read API keys from project .env first, then ~/.env"""
    # Prefer .env in ARI project root (2 levels up from server.py)
    _here = Path(__file__).parent
    candidates = [
        _here.parent.parent / ".env",  # /ARI/.env
        _here.parent / ".env",          # /ARI/ari-core/.env
        Path.cwd() / ".env",
        Path.home() / ".env",
    ]
    env_path = next((p for p in candidates if p.exists()), Path.home() / ".env")
    keys = {}
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"): continue
            if "=" in line:
                k, _, v = line.partition("=")
                k = k.strip(); v = v.strip().strip('"').strip("'")
                if any(x in k.upper() for x in ["API_KEY","SECRET","TOKEN"]):
                    keys[k] = v
    # also check os.environ
    for k in ["OPENAI_API_KEY","ANTHROPIC_API_KEY","GOOGLE_API_KEY","GEMINI_API_KEY"]:
        if k not in keys and os.environ.get(k):
            keys[k] = os.environ[k]
    return {"keys": keys}



def _api_save_env_key(body: bytes) -> dict:
    """Append or update a key in ~/.env"""
    data = json.loads(body)
    key_name  = data.get("key","").strip()
    key_value = data.get("value","").strip()
    if not key_name or not key_value:
        return {"ok": False, "error": "key and value required"}
    env_path = Path.home() / ".env"
    lines = env_path.read_text().splitlines() if env_path.exists() else []
    found = False
    new_lines = []
    for line in lines:
        if line.strip().startswith(key_name + "="):
            new_lines.append(f'{key_name}="{key_value}"')
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(f'{key_name}="{key_value}"')
    env_path.write_text("\n".join(new_lines) + "\n")
    os.environ[key_name] = key_value
    return {"ok": True}



def _api_get_settings() -> dict:
    if _st._settings_path.exists():
        try:
            return json.loads(_st._settings_path.read_text())
        except Exception:
            pass
    return {
        "llm_model": os.environ.get("ARI_LLM_MODEL", "gpt-5.2"),
        "llm_api_key": "",
        "temperature": 1.0,
        "semantic_scholar_key": "",
        "slurm_partition": "",
        "slurm_cpus": 8,
        "slurm_memory_gb": 32,
        "slurm_walltime": "04:00:00",
        "mcp_skills": [],
    }





def _api_save_settings(body: bytes) -> dict:
    data = json.loads(body)
    _st._settings_path.parent.mkdir(parents=True, exist_ok=True)
    _st._settings_path.write_text(json.dumps(data, indent=2))
    return {"ok": True}



def _api_get_workflow() -> dict:
    """Return workflow.yaml as JSON with MCP tool metadata."""
    import yaml
    wf_candidates = [
        Path(__file__).parent.parent.parent / "config" / "workflow.yaml",
        Path(__file__).parent.parent.parent.parent / "config" / "workflow.yaml",
        Path.cwd() / "config" / "workflow.yaml",
    ]
    for wf in wf_candidates:
        if wf.exists():
            try:
                data = yaml.safe_load(wf.read_text())
                # Load MCP tool metadata from each skill directory
                ari_root = wf.parent.parent.parent
                skill_mcp: dict = {}
                for skill_dir in sorted(ari_root.glob("ari-skill-*")):
                    mcp_file = skill_dir / "mcp.json"
                    if mcp_file.exists():
                        try:
                            mcp_data = json.loads(mcp_file.read_text())
                            name = mcp_data.get("name") or skill_dir.name
                            skill_mcp[name] = {
                                "name": name,
                                "description": mcp_data.get("description", ""),
                                "tools": mcp_data.get("tools", []),
                                "version": mcp_data.get("version", ""),
                                "dir": skill_dir.name,
                            }
                        except Exception:
                            pass
                # Also collect from workflow.yaml skills section
                for sk in data.get("skills", []):
                    sk_name = sk.get("name", "")
                    if sk_name not in skill_mcp:
                        skill_mcp[sk_name] = {
                            "name": sk_name,
                            "description": sk.get("description", ""),
                            "tools": [],
                            "version": "",
                            "dir": "",
                        }
                # BFTS experiment loop stages (from ari-core code, not workflow.yaml)
                bfts_pipeline = [
                    {"stage": "generate_idea", "skill": "idea-skill", "tool": "generate_ideas",
                     "description": "LLM generates research hypotheses for BFTS root node",
                     "depends_on": [], "enabled": True, "phase": "bfts"},
                    {"stage": "expand_node", "skill": "evaluator-skill", "tool": "evaluate_node",
                     "description": "BFTS selects best node; LLM generates code + runs HPC job",
                     "depends_on": ["generate_idea"], "enabled": True, "phase": "bfts"},
                    {"stage": "evaluate_metrics", "skill": "evaluator-skill", "tool": "evaluate_node",
                     "description": "Parse stdout/artifacts, extract metrics, score node",
                     "depends_on": ["expand_node"], "enabled": True, "phase": "bfts"},
                    {"stage": "bfts_select_next", "skill": "idea-skill", "tool": "generate_ideas",
                     "description": "LLM selects best completed node to expand (BFTS step); loops back",
                     "depends_on": ["evaluate_metrics"], "enabled": True, "phase": "bfts",
                     "loop_back_to": "expand_node"},
                ]
                paper_pipeline = []
                for s in (data.get("pipeline") or []):
                    s2 = dict(s); s2["phase"] = "paper"; paper_pipeline.append(s2)
                # Connect BFTS → Paper: paper phase starts after BFTS loop
                for s in paper_pipeline:
                    if not s.get("depends_on"):
                        s["depends_on"] = ["bfts_select_next"]
                return {"ok": True, "workflow": data, "path": str(wf), "skill_mcp": skill_mcp,
                        "bfts_pipeline": bfts_pipeline,
                        "paper_pipeline": paper_pipeline,
                        "full_pipeline": bfts_pipeline + paper_pipeline}
            except Exception as e:
                return {"ok": False, "error": str(e)}
    return {"ok": False, "error": "workflow.yaml not found"}



def _api_save_workflow(body: bytes) -> dict:
    """Save modified workflow.yaml."""
    import yaml
    data = json.loads(body)
    wf_path = data.get("path")
    pipeline = data.get("pipeline")
    if not wf_path or not pipeline:
        return {"ok": False, "error": "missing path or pipeline"}
    wf_p = Path(wf_path)
    if not wf_p.exists():
        return {"ok": False, "error": "path not found"}
    try:
        existing = yaml.safe_load(wf_p.read_text())
        existing["pipeline"] = pipeline
        wf_p.write_text(yaml.dump(existing, allow_unicode=True, sort_keys=False))
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}




def _api_skill_detail(name: str) -> dict:
    """Return skill source files and README."""
    import yaml as _yaml
    ari_root = Path(__file__).parent.parent.parent.parent
    skill_dir = ari_root / ("ari-skill-" + name.replace("ari-skill-", "").replace("-skill", "") + "-skill" if not name.startswith("ari-") else name)
    # Try multiple candidate names
    candidates = [
        ari_root / name,
        ari_root / ("ari-" + name),
        ari_root / (name + "-skill"),
    ]
    for cand in candidates:
        if cand.exists():
            skill_dir = cand
            break
    if not skill_dir.exists():
        # Fuzzy match
        for d in sorted(ari_root.glob("ari-skill-*")):
            if name.replace("-skill","").replace("ari-","") in d.name:
                skill_dir = d
                break
    if not skill_dir.exists():
        return {"ok": False, "error": f"Skill not found: {name}"}

    result = {"ok": True, "name": name, "dir": str(skill_dir), "files": {}}
    # Collect key files
    for fname in ["README.md", "SKILL.md", "REQUIREMENTS.md", "skill.yaml", "mcp.json"]:
        fp = skill_dir / fname
        if fp.exists():
            result["files"][fname] = fp.read_text(encoding="utf-8", errors="replace")[:8000]
    # Main source file
    for src_candidate in [skill_dir/"src"/"server.py", skill_dir/"src"/"main.py"]:
        if src_candidate.exists():
            result["files"]["src/server.py"] = src_candidate.read_text(encoding="utf-8", errors="replace")[:12000]
            break
    return result


def _api_skills() -> list:
    skills = []
    try:
        # Search multiple candidate root directories for ari-skill-* packages
        _search_roots = [
            _st._ari_home,
            Path(__file__).parent.parent.parent.parent,  # ~/ARI/
            Path(__file__).parent.parent.parent,          # ~/ARI/ari-core/
        ]
        _seen = set()
        _all_dirs = []
        for _root in _search_roots:
            if _root.exists():
                for d in sorted(_root.iterdir()):
                    if d.is_dir() and d.name.startswith("ari-skill-") and d.name not in _seen:
                        _seen.add(d.name)
                        _all_dirs.append(d)
        for d in sorted(_all_dirs, key=lambda x: x.name):
            sy = d / "skill.yaml"
            if sy.exists():
                try:
                    import yaml as _yaml
                    data = _yaml.safe_load(sy.read_text()) or {}
                    data.setdefault("name", d.name)
                    data.setdefault("display_name", d.name)
                    data.setdefault("description", "")
                    data.setdefault("requires_env", [])
                    skills.append(data)
                except Exception:
                    skills.append({"name": d.name, "display_name": d.name, "description": "", "requires_env": []})
    except Exception as e:
        return [{"name": "error", "display_name": str(e), "description": "", "requires_env": []}]
    return skills


# ──────────────────────────────────────────────
# File watcher (polling thread)
# ──────────────────────────────────────────────

def _api_profiles() -> list:
    profiles = []
    profiles_dir = _st._ari_home / "ari-core" / "config" / "profiles"
    if profiles_dir.exists():
        for p in sorted(profiles_dir.glob("*.yaml")):
            profiles.append({"name": p.stem, "path": str(p)})
    return profiles



def _api_detect_scheduler() -> dict:
    try:
        from ari.env_detect import get_environment_summary
        return get_environment_summary()
    except Exception as e:
        return {"error": str(e), "scheduler": "none", "container": "none", "partitions": []}


