"""ARI viz: api_settings — env keys, settings, workflow, skills, profiles."""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

from . import state as _st

log = logging.getLogger(__name__)
_PINNED_RETRIEVAL_BACKENDS = frozenset(
    {"semantic_scholar", "arxiv", "alphaxiv"}
)


# Redaction placeholder served instead of any non-empty secret value
# (RR-P0-2 / ADR-11 / MN-2 — GET /api/env-keys never returns plaintext).
ENV_KEY_REDACTED = "***configured***"

# POST /api/env-keys name allowlist (plan 09 §Secret policy / ADR-11):
# UPPER_SNAKE, must start with a letter, max 64 chars total. `fullmatch` is
# deliberate — `re.match` with `$` would accept a trailing newline.
_ENV_KEY_NAME_RE = re.compile(r"[A-Z][A-Z0-9_]{0,63}")


def _env_chain() -> list[tuple[Path, str]]:
    """Ordered ``(.env path, source_class)`` candidates — project > repo > user.

    Shared by the legacy ``GET /api/env-keys`` harvest and the v1 secret
    readiness endpoint (``ari.viz.v1.secrets``) so the two can never disagree
    about which file wins. ``source_class`` vocabulary is the ADR-11 one:
    ``project_env`` (active checkpoint), ``repo_env`` (ARI/.env or
    ari-core/.env), ``user_env`` (~/.env); ``process_env`` is the os.environ
    fallback handled by the callers.
    """
    _here = Path(__file__).parent
    _ari_root = _here.parent.parent.parent  # /ARI/
    chain = [
        (_ari_root / ".env", "repo_env"),              # /ARI/.env
        (_ari_root / "ari-core" / ".env", "repo_env"), # /ARI/ari-core/.env
        (Path.home() / ".env", "user_env"),            # ~/.env (global fallback)
    ]
    if _st._checkpoint_dir:
        chain.insert(0, (_st._checkpoint_dir / ".env", "project_env"))
    return chain


def _api_get_env_keys() -> dict:
    """List secret-bearing keys from the .env chain — REDACTED (RR-P0-2).

    ADR-11 / MN-2: this endpoint historically returned every value whose name
    contains ``API_KEY``/``SECRET``/``TOKEN`` in plaintext. It now serves only
    readiness: each non-empty value is replaced by :data:`ENV_KEY_REDACTED`,
    empty values stay ``""``, the ``source`` map is unchanged, and a top-level
    ``"redacted": true`` marker lets clients detect the new contract. Secret
    values can no longer be read over HTTP; the write path (POST) is separate.
    """
    keys = {}
    source = {}  # track which file each key came from
    # Read all files; first occurrence wins (project > global)
    for env_path, _cls in _env_chain():
        if not env_path.exists():
            continue
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, _, v = line.partition("=")
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if any(x in k.upper() for x in ["API_KEY", "SECRET", "TOKEN"]):
                    if k not in keys:
                        keys[k] = ENV_KEY_REDACTED if v else ""
                        source[k] = str(env_path)
    # Also check os.environ as final fallback
    for k in ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY"]:
        if k not in keys and os.environ.get(k):
            keys[k] = ENV_KEY_REDACTED
            source[k] = "os.environ"
    return {"keys": keys, "source": source, "redacted": True}



def _upsert_env_key(name: str, value: str, *, quote: bool) -> None:
    """Insert or in-place-replace ``name=value`` in the project .env file.

    Reads ``_st._env_write_path``, replaces the first line whose stripped form
    starts with ``name=`` (preserving every other line), appends if absent,
    writes back with a trailing newline, and sets ``os.environ[name]`` live.

    ``quote`` selects the on-disk form: ``True`` -> ``name="value"`` (the form
    written by the GUI env-key editor), ``False`` -> ``name=value`` (the form
    written by the settings-save API-key path). The two callers historically
    differed only by this quoting; the flag preserves each exactly (unifying it
    would be a behavior change — out of scope for a refactor).
    """
    rendered = f'{name}="{value}"' if quote else f"{name}={value}"
    env_path = _st._env_write_path
    lines = env_path.read_text().splitlines() if env_path.exists() else []
    found = False
    new_lines = []
    for line in lines:
        if line.strip().startswith(name + "="):
            new_lines.append(rendered)
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(rendered)
    # RR-P0-4 hardening (gui_refresh Wave 3b): atomic same-dir tmp + fsync +
    # os.replace so a crash mid-write can never truncate the .env, and the
    # secret-bearing file is owner-only (0o600) from the moment it exists.
    # Content is byte-identical to the historical write_text form.
    import tempfile
    payload = "\n".join(new_lines) + "\n"
    fd, tmp_path = tempfile.mkstemp(dir=str(env_path.parent), prefix=".env.tmp-")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, env_path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    try:
        os.chmod(env_path, 0o600)
    except OSError:
        pass
    os.environ[name] = value


def _api_save_env_key(body: bytes) -> dict:
    """Append or update a key in project .env (ARI root).

    Name allowlist enforcement (plan 09 §Secret policy / ADR-11): the key
    must fullmatch ``^[A-Z][A-Z0-9_]{0,63}$`` and carry no newline/control
    characters — anything else is rejected with HTTP 400 (the ``_status``
    pop convention in routes.py). The happy-path write is unchanged.
    """
    data = json.loads(body)
    key_name  = data.get("key","").strip()
    key_value = data.get("value","").strip()
    if not key_name or not key_value:
        return {"ok": False, "error": "key and value required"}
    raw_name = data.get("key", "")
    if (
        any(ord(c) < 0x20 or ord(c) == 0x7F for c in raw_name)
        or not _ENV_KEY_NAME_RE.fullmatch(key_name)
    ):
        return {
            "ok": False,
            "error": (
                "invalid key name: must match ^[A-Z][A-Z0-9_]{0,63}$ "
                "(UPPER_SNAKE, max 64 chars, no control characters)"
            ),
            "_status": 400,
        }
    _upsert_env_key(key_name, key_value, quote=True)
    return {"ok": True}



def _api_get_settings() -> dict:
    # Read workflow.yaml defaults for llm_provider / llm_model fallback
    _wf_provider = ""
    _wf_model = ""
    try:
        import yaml as _yaml
        from ari.config.finder import package_config_root
        for _wf_path in [
            package_config_root() / "workflow.yaml",
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
        # ORS (PaperBench-format auto rubric) defaults.
        "ors": {
            "replicator_model":   os.environ.get("ARI_MODEL_REPLICATE",   "claude-opus-4-7"),
            "rubric_gen_model":   os.environ.get("ARI_MODEL_RUBRIC_GEN",  "gemini-2.5-pro"),
            "rubric_audit_model": os.environ.get("ARI_MODEL_RUBRIC_AUDIT","claude-opus-4-7"),
            "judge_model":        os.environ.get("ARI_MODEL_JUDGE",       "gpt-4o-2024-11-20"),
            "rubric_gen_temperature":   0.0,
            "rubric_gen_target_leaves": 0,
            "rubric_gen_two_stage":     True,
            "judge_n_runs":             3,
            "phase1_max_runtime_sec":   21600,
            "phase1_sandbox_kind":      os.environ.get("ARI_PHASE1_SANDBOX", "auto"),
        },
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
    retrieval_backend = data.get("retrieval_backend")
    if (
        retrieval_backend is not None
        and retrieval_backend not in _PINNED_RETRIEVAL_BACKENDS
    ):
        return {
            "ok": False,
            "error": "retrieval_backend must select one pinned provider",
            "_status": 400,
        }
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
            # Unquoted form (quote=False) preserves this path's historical
            # KEY=value spelling, distinct from the env-key editor's KEY="value".
            _upsert_env_key(_env_key_name, _raw_key, quote=False)
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
    from ari.config.finder import package_config_root
    wf_candidates = [
        package_config_root() / "workflow.yaml",
    ]
    if _st._checkpoint_dir:
        wf_candidates.insert(0, _st._checkpoint_dir / "workflow.yaml")
    for wf in wf_candidates:
        if wf.exists():
            try:
                raw = wf.read_bytes()
                data = yaml.safe_load(raw)
                # Load dashboard metadata from the same canonical manifests as
                # runtime admission. Generated mcp.json and source scraping are
                # deliberately not dashboard authorities.
                from ari.skill_manifest import load_skill_manifest, manifest_digest
                ari_root = wf.parent.parent.parent
                skill_mcp: dict = {}
                dir_mcp: dict[str, dict] = {}
                for manifest_path in sorted(ari_root.glob("ari-skill-*/skill.yaml")):
                    skill_dir = manifest_path.parent
                    manifest = load_skill_manifest(manifest_path)
                    resolved_tools = manifest.resolved_tools()
                    entry = {
                        "name": manifest.name,
                        "description": manifest.description,
                        "tools": [tool.name for tool in resolved_tools],
                        "version": manifest.version,
                        "dir": skill_dir.name,
                        "manifest_digest": manifest_digest(manifest),
                        "capabilities": {
                            tool.name: tool.capability_ref for tool in resolved_tools
                        },
                    }
                    dir_mcp[skill_dir.name] = entry
                    skill_mcp[entry["name"]] = entry
                # Resolve workflow aliases to canonical manifest entries via
                # the configured package path.
                for sk in data.get("skills", []):
                    sk_name = sk.get("name", "")
                    sk_path = sk.get("path", "")
                    # Resolve {{ari_root}} and extract directory name
                    resolved = sk_path.replace("{{ari_root}}", str(ari_root))
                    dir_name = Path(resolved).name if resolved else ""
                    if dir_name and dir_name in dir_mcp:
                        # Merge canonical data under the workflow skill name.
                        src = dir_mcp[dir_name]
                        entry = {
                            "name": sk_name,
                            "description": sk.get("description") or src["description"],
                            "tools": src["tools"],
                            "version": src["version"],
                            "dir": src["dir"],
                            "manifest_digest": src["manifest_digest"],
                            "capabilities": src["capabilities"],
                        }
                        # Read phase directly from workflow.yaml skills entry
                        if sk.get("phase"):
                            entry["phase"] = sk["phase"]
                        skill_mcp[sk_name] = entry
                        # Remove the canonical alias if it differs from
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

                # Usage is declarative: pipeline-owned, configured/active, or
                # manifest-only/registered. Source-text references are not an
                # execution contract.
                configured_skills = {
                    str(skill.get("name") or "") for skill in data.get("skills", [])
                }
                for sk_name, entry in skill_mcp.items():
                    if sk_name in bfts_skills or sk_name in paper_skills:
                        entry["usage"] = "stage"
                    elif sk_name in configured_skills:
                        entry["usage"] = "active"
                    else:
                        entry["usage"] = "registered"

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
                # Weak revision of the served bytes (gui_refresh Wave 4d,
                # additive key): revision-aware clients echo it back as
                # base_revision on writes; legacy consumers ignore it.
                from .api_workflow import workflow_revision
                return {"ok": True, "workflow": data, "path": str(wf), "skill_mcp": skill_mcp,
                        "disabled_tools": data.get("disabled_tools") or [],
                        "bfts_pipeline": bfts_pipeline,
                        "paper_pipeline": paper_pipeline,
                        "full_pipeline": bfts_pipeline + paper_pipeline,
                        "revision": workflow_revision(raw)}
            except Exception as e:
                return {"ok": False, "error": str(e)}
    return {"ok": False, "error": "workflow.yaml not found"}



def _api_save_workflow(body: bytes) -> dict:
    """Save modified workflow.yaml into active checkpoint."""
    import yaml
    from .api_workflow import (
        _workflow_revision_guard,
        _workflow_write_guard,
        workflow_revision,
    )
    guard = _workflow_write_guard()
    if guard:
        return guard
    data = json.loads(body)
    pipeline = data.get("pipeline")
    if not pipeline:
        return {"ok": False, "error": "missing pipeline"}
    # Optional optimistic concurrency (gui_refresh Wave 4d): a stale
    # base_revision refuses with the frozen 409 payload before any write.
    stale = _workflow_revision_guard(data.get("base_revision"))
    if stale:
        return stale
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
        text = yaml.dump(existing, allow_unicode=True, sort_keys=False)
        wf_p.write_text(text)
        return {"ok": True, "revision": workflow_revision(text.encode("utf-8"))}
    except Exception as e:
        return {"ok": False, "error": str(e)}




def _api_skill_detail(name: str) -> dict:
    """Return skill source files and README."""
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
                    # Frontend compatibility while canonical manifests use the
                    # grammatically explicit required_env field.
                    data.setdefault("requires_env", data.get("required_env", []))
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
