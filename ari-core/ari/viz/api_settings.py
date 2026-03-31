from __future__ import annotations
"""ARI viz: api_settings — env keys, settings, workflow, skills, profiles."""

import json
import logging
import os
from pathlib import Path

from . import state as _st

log = logging.getLogger(__name__)


def _api_get_env_keys() -> dict:
    """Read API keys from all .env files (project-specific first, then global)."""
    _here = Path(__file__).parent
    _ari_root = _here.parent.parent  # /ARI/
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
        "slurm_partition": "",
        "slurm_cpus": None,
        "slurm_memory_gb": None,
        "slurm_gpus": 0,
        "slurm_walltime": "04:00:00",
        "mcp_skills": [],
    }
    if _st._settings_path.exists():
        try:
            saved = json.loads(_st._settings_path.read_text())
            # Merge: saved values override defaults, but missing keys get defaults
            merged = {**defaults, **saved}
            # If saved values are empty, fall back to workflow.yaml defaults
            if not merged.get("llm_provider"):
                merged["llm_provider"] = _wf_provider
            if not merged.get("llm_model"):
                merged["llm_model"] = _wf_model
            return merged
        except Exception:
            log.warning("Failed to load settings.json", exc_info=True)
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
    _st._settings_path.parent.mkdir(parents=True, exist_ok=True)
    _st._settings_path.write_text(json.dumps(data, indent=2))
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
                            log.debug("skill metadata read error", exc_info=True)
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


