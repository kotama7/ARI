from __future__ import annotations
"""ARI viz: api_settings — env keys, settings, workflow, skills, profiles."""

import json
import logging
import os
import re
from pathlib import Path

from . import state as _st

log = logging.getLogger(__name__)


def _extract_tools_from_server(skill_dir: Path) -> list[str]:
    """Extract MCP tool names from server.py when mcp.json has no tools.

    Looks for two patterns:
    - ``@mcp.tool()`` decorator followed by ``async def <name>(`` or ``def <name>(``
    - ``Tool(name="<name>"`` in ``list_tools()`` style registration
    """
    server_py = skill_dir / "src" / "server.py"
    if not server_py.exists():
        return []
    try:
        src = server_py.read_text()
    except Exception:
        return []
    tools: list[str] = []
    # Pattern 1: @mcp.tool() decorator
    for m in re.finditer(r"@mcp\.tool\(\)\s*\n\s*(?:async\s+)?def\s+(\w+)\s*\(", src):
        tools.append(m.group(1))
    # Pattern 2: Tool(name="...")
    for m in re.finditer(r'Tool\(\s*name\s*=\s*"(\w+)"', src):
        if m.group(1) not in tools:
            tools.append(m.group(1))
    return tools


def _api_get_env_keys() -> dict:
    """Read API keys from all .env files (project-specific first, then global)."""
    _here = Path(__file__).parent
    _ari_root = _here.parent.parent.parent  # /ARI/
    candidates = [
        _ari_root / ".env",             # /ARI/.env (project root — highest priority)
        _ari_root / "ari-core" / ".env", # /ARI/ari-core/.env
        Path.home() / ".env",            # ~/.env (global fallback)
    ]
    if _st._checkpoint_dir:
        candidates.insert(0, _st._checkpoint_dir / ".env")
    keys = {}
    source = {}  # track which file each key came from
    # Read all files; first occurrence wins (project > global)
    for env_path in candidates:
        if not env_path.exists():
            continue
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, _, v = line.partition("=")
                k = k.strip(); v = v.strip().strip('"').strip("'")
                if any(x in k.upper() for x in ["API_KEY", "SECRET", "TOKEN"]):
                    if k not in keys:
                        keys[k] = v
                        source[k] = str(env_path)
    # Also check os.environ as final fallback
    for k in ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY"]:
        if k not in keys and os.environ.get(k):
            keys[k] = os.environ[k]
            source[k] = "os.environ"
    return {"keys": keys, "source": source}



def _api_save_env_key(body: bytes) -> dict:
    """Append or update a key in project .env (ARI root)."""
    data = json.loads(body)
    key_name  = data.get("key","").strip()
    key_value = data.get("value","").strip()
    if not key_name or not key_value:
        return {"ok": False, "error": "key and value required"}
    env_path = _st._env_write_path
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
    # Read workflow.yaml defaults for llm_provider / llm_model fallback
    _wf_provider = ""
    _wf_model = ""
    try:
        import yaml as _yaml
        for _wf_path in [
            Path(__file__).parent.parent.parent / "config" / "workflow.yaml",
            Path(__file__).parent.parent.parent.parent / "config" / "workflow.yaml",
        ]:
            if _wf_path.exists():
                _wf = _yaml.safe_load(_wf_path.read_text()) or {}
                _wf_llm = _wf.get("llm", {})
                _wf_provider = _wf_llm.get("backend", "")
                _wf_model = _wf_llm.get("model", "")
                break
    except Exception:
        pass
    defaults = {
        "llm_model": os.environ.get("ARI_LLM_MODEL", "") or _wf_model,
        "llm_provider": os.environ.get("ARI_BACKEND", "") or _wf_provider,
        "llm_api_key": "",
        "ollama_host": os.environ.get("OLLAMA_HOST", "http://localhost:11434"),
        "temperature": 1.0,
        "semantic_scholar_key": "",
        "retrieval_backend": os.environ.get("ARI_RETRIEVAL_BACKEND", "semantic_scholar"),
        "slurm_partition": "",
        "slurm_cpus": None,
        "slurm_memory_gb": None,
        "slurm_gpus": 0,
        "slurm_walltime": "04:00:00",
        "mcp_skills": [],
        "container_mode": "auto",
        "container_image": "",
        "container_pull": "on_start",
        "vlm_review_enabled": True,
        "vlm_review_model": "openai/gpt-4o",
        "vlm_review_max_iter": 3,
        "vlm_review_threshold": 0.7,
        # Memory (Letta) card.
        "letta_deployment": "auto",
        "letta_deployment_image": "",
        "letta_deployment_venv": "",
        "letta_base_url": os.environ.get("LETTA_BASE_URL", "http://localhost:8283"),
        "letta_api_key": "",
        "letta_embedding_config": os.environ.get(
            "LETTA_EMBEDDING_CONFIG", "letta-default"
        ),
    }
    # Read project-scoped settings only.  When no checkpoint is selected the
    # GUI displays built-in defaults (workflow.yaml + hardcoded values) — ARI
    # no longer maintains any global ~/.ari/settings.json fallback.
    _active = _st._settings_path
    if _active is not None and _active.exists():
        try:
            saved = json.loads(_active.read_text())
            merged = {**defaults, **saved}
            if not merged.get("llm_provider"):
                merged["llm_provider"] = _wf_provider
            if not merged.get("llm_model"):
                merged["llm_model"] = _wf_model
            return merged
        except Exception:
            log.warning("Failed to load settings file %s", _active, exc_info=True)
    return defaults





def _api_save_settings(body: bytes) -> dict:
    data = json.loads(body)
    # Extract API key — write to .env instead of settings.json
    _raw_key = data.pop("api_key", "") or data.pop("llm_api_key", "") or ""
    # Also remove from the dict so it's never persisted in settings.json
    data.pop("api_key", None)
    data.pop("llm_api_key", None)
    if _raw_key and "test" not in _raw_key and len(_raw_key) >= 20:
        _provider = data.get("llm_provider", "") or data.get("llm_backend", "")
        _env_key_name = {
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "gemini": "GOOGLE_API_KEY",
        }.get(_provider, "")
        if _env_key_name:
            _env_path = _st._env_write_path
            _lines = _env_path.read_text().splitlines() if _env_path.exists() else []
            _found = False
            _new_lines = []
            for _line in _lines:
                if _line.strip().startswith(_env_key_name + "="):
                    _new_lines.append(f"{_env_key_name}={_raw_key}")
                    _found = True
                else:
                    _new_lines.append(_line)
            if not _found:
                _new_lines.append(f"{_env_key_name}={_raw_key}")
            _env_path.write_text("\n".join(_new_lines) + "\n")
            os.environ[_env_key_name] = _raw_key
    # Settings are always project-scoped now.  Without an active checkpoint
    # there is nowhere to persist, so refuse the write and prompt the user.
    _active = _st._settings_path
    if _active is None:
        return {
            "ok": False,
            "error": "No active project. Create or select a checkpoint before saving settings.",
            "_status": 400,
        }
    _active.parent.mkdir(parents=True, exist_ok=True)
    _active.write_text(json.dumps(data, indent=2))
    return {"ok": True}



def _api_get_workflow() -> dict:
    """Return workflow.yaml as JSON with MCP tool metadata."""
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
                # Load MCP tool metadata from each skill directory
                ari_root = wf.parent.parent.parent
                skill_mcp: dict = {}
                # Build dir-name → mcp data mapping first
                dir_mcp: dict[str, dict] = {}
                for skill_dir in sorted(ari_root.glob("ari-skill-*")):
                    mcp_file = skill_dir / "mcp.json"
                    tools: list = []
                    mcp_name = skill_dir.name
                    mcp_desc = ""
                    mcp_ver = ""
                    if mcp_file.exists():
                        try:
                            mcp_data = json.loads(mcp_file.read_text())
                            mcp_name = mcp_data.get("name") or skill_dir.name
                            mcp_desc = mcp_data.get("description", "")
                            tools = mcp_data.get("tools", [])
                            mcp_ver = mcp_data.get("version", "")
                        except Exception:
                            log.debug("skill metadata read error", exc_info=True)
                    # Fallback: extract tool names from server.py if
                    # mcp.json has no tools listed
                    if not tools:
                        tools = _extract_tools_from_server(skill_dir)
                    entry = {
                        "name": mcp_name,
                        "description": mcp_desc,
                        "tools": tools,
                        "version": mcp_ver,
                        "dir": skill_dir.name,
                    }
                    dir_mcp[skill_dir.name] = entry
                    skill_mcp[entry["name"]] = entry
                # Resolve workflow.yaml skills section: map workflow skill
                # names to their mcp.json tools via the path field
                for sk in data.get("skills", []):
                    sk_name = sk.get("name", "")
                    sk_path = sk.get("path", "")
                    # Resolve {{ari_root}} and extract directory name
                    resolved = sk_path.replace("{{ari_root}}", str(ari_root))
                    dir_name = Path(resolved).name if resolved else ""
                    if dir_name and dir_name in dir_mcp:
                        # Merge mcp.json data under the workflow skill name
                        src = dir_mcp[dir_name]
                        entry = {
                            "name": sk_name,
                            "description": sk.get("description") or src["description"],
                            "tools": src["tools"],
                            "version": src["version"],
                            "dir": src["dir"],
                        }
                        # Read phase directly from workflow.yaml skills entry
                        if sk.get("phase"):
                            entry["phase"] = sk["phase"]
                        skill_mcp[sk_name] = entry
                        # Remove the mcp.json alias if it differs from
                        # the workflow name (e.g. vlm-review-skill vs
                        # vlm-skill) to avoid duplicate entries
                        mcp_alias = src["name"]
                        if mcp_alias != sk_name and mcp_alias in skill_mcp:
                            del skill_mcp[mcp_alias]
                    elif sk_name not in skill_mcp:
                        skill_mcp[sk_name] = {
                            "name": sk_name,
                            "description": sk.get("description", ""),
                            "tools": [],
                            "version": "",
                            "phase": sk.get("phase", "all"),
                            "dir": dir_name,
                        }
                # Enrich skill_mcp with phase info from default.yaml
                default_yaml = ari_root / "ari-core" / "config" / "default.yaml"
                if not default_yaml.exists():
                    default_yaml = wf.parent / "default.yaml"
                if default_yaml.exists():
                    try:
                        import yaml as _yaml
                        default_data = _yaml.safe_load(default_yaml.read_text()) or {}
                        for sk_def in default_data.get("skills", []):
                            sk_name = sk_def.get("name", "")
                            sk_phase = sk_def.get("phase", "")
                            if sk_name in skill_mcp:
                                skill_mcp[sk_name]["phase"] = sk_phase
                            # Also resolve dir-based entries
                            sk_dir = Path(sk_def.get("path", "")).name
                            if sk_dir in dir_mcp and dir_mcp[sk_dir]["name"] in skill_mcp:
                                skill_mcp[dir_mcp[sk_dir]["name"]]["phase"] = sk_phase
                    except Exception:
                        log.debug("default.yaml phase read error", exc_info=True)
                # Also set phase from pipeline stage assignments
                bfts_skills = set()
                paper_skills = set()
                for s in data.get("bfts_pipeline") or []:
                    bfts_skills.add(s.get("skill", ""))
                for s in data.get("pipeline") or []:
                    paper_skills.add(s.get("skill", ""))
                for sk_name, entry in skill_mcp.items():
                    if "phase" not in entry:
                        if sk_name in bfts_skills:
                            entry["phase"] = "bfts"
                        elif sk_name in paper_skills:
                            entry["phase"] = "pipeline"

                # Determine usage: stage / active / registered
                # Scan core source for tool name references
                core_dir = ari_root / "ari-core" / "ari"
                _core_src = ""
                if core_dir.is_dir():
                    for py in core_dir.rglob("*.py"):
                        if "viz/" in str(py) or "__pycache__" in str(py):
                            continue
                        try:
                            _core_src += py.read_text(errors="ignore")
                        except Exception:
                            pass
                for sk_name, entry in skill_mcp.items():
                    if sk_name in bfts_skills or sk_name in paper_skills:
                        entry["usage"] = "stage"
                    else:
                        tool_names = [
                            t if isinstance(t, str) else t.get("name", "")
                            for t in entry.get("tools", [])
                        ]
                        called = any(
                            f'"{tn}"' in _core_src or f"'{tn}'" in _core_src
                            for tn in tool_names if tn
                        )
                        entry["usage"] = "active" if called else "registered"

                # Read BFTS and paper pipelines from YAML (no hardcoded stages)
                bfts_pipeline = data.get("bfts_pipeline") or []
                paper_pipeline = data.get("pipeline") or []
                # Connect BFTS → Paper: paper stages with empty depends_on
                # link to the last BFTS stage
                if bfts_pipeline:
                    last_bfts = bfts_pipeline[-1]["stage"]
                    paper_pipeline = [dict(s) for s in paper_pipeline]
                    for s in paper_pipeline:
                        if not s.get("depends_on"):
                            s["depends_on"] = [last_bfts]
                return {"ok": True, "workflow": data, "path": str(wf), "skill_mcp": skill_mcp,
                        "disabled_tools": data.get("disabled_tools") or [],
                        "bfts_pipeline": bfts_pipeline,
                        "paper_pipeline": paper_pipeline,
                        "full_pipeline": bfts_pipeline + paper_pipeline}
            except Exception as e:
                return {"ok": False, "error": str(e)}
    return {"ok": False, "error": "workflow.yaml not found"}



def _api_save_workflow(body: bytes) -> dict:
    """Save modified workflow.yaml into active checkpoint."""
    import yaml
    err = _st.require_checkpoint_dir()
    if err:
        return {"ok": False, "error": err, "_status": 400}
    data = json.loads(body)
    pipeline = data.get("pipeline")
    if not pipeline:
        return {"ok": False, "error": "missing pipeline"}
    # Always write to checkpoint dir, not arbitrary path
    wf_p = _st._checkpoint_dir / "workflow.yaml"
    try:
        existing = {}
        # Read from source workflow if checkpoint copy doesn't exist yet
        src_path = data.get("path")
        if not wf_p.exists() and src_path and Path(src_path).exists():
            existing = yaml.safe_load(Path(src_path).read_text()) or {}
        elif wf_p.exists():
            existing = yaml.safe_load(wf_p.read_text()) or {}
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
            _st._ari_root,
            Path(__file__).parent.parent.parent.parent,  # ARI/
            Path(__file__).parent.parent.parent,          # ARI/ari-core/
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
    profiles_dir = _st._ari_root / "ari-core" / "config" / "profiles"
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


def _api_rubrics() -> list:
    """Return reviewer rubrics available under ari-core/config/reviewer_rubrics/.

    Used by the New Experiment wizard dropdown and the ReviewPanel header.
    """
    try:
        import yaml  # type: ignore
    except ImportError:
        return []
    rubrics_dir = _st._ari_root / "ari-core" / "config" / "reviewer_rubrics"
    out: list[dict] = []
    if not rubrics_dir.exists():
        return out
    for p in sorted(rubrics_dir.glob("*.yaml")):
        try:
            data = yaml.safe_load(p.read_text()) or {}
            if not isinstance(data, dict):
                continue
            out.append({
                "id": str(data.get("id", p.stem)),
                "venue": str(data.get("venue", "")),
                "domain": str(data.get("domain", "")),
                "version": str(data.get("version", "")),
                "closed_review": bool(data.get("closed_review", False)),
                "path": str(p),
            })
        except Exception:
            continue
    return out


