"""Configuration models for ARI using Pydantic."""

from __future__ import annotations

import os
import re
from pathlib import Path

import yaml
from pydantic import BaseModel


class LLMConfig(BaseModel):
    backend: str = "ollama"
    model: str = "qwen3:8b"
    api_key: str | None = None
    base_url: str | None = None
    temperature: float = 0.7


class SkillConfig(BaseModel):
    name: str
    path: str
    description: str = ""
    # Single phase string ("bfts" | "paper" | "reproduce" | "all" | "none")
    # or a list of phases ([..., "reproduce"]) declaring every phase in which
    # this skill is exposed to the AgentLoop ReAct. "all" matches any phase;
    # "none" disables the skill entirely.
    phase: str | list[str] = "all"


class BFTSConfig(BaseModel):
    max_depth: int = 5
    max_total_nodes: int = 50
    max_react_steps: int = 80
    timeout_per_node: int = 7200
    max_parallel_nodes: int = 4


class CheckpointConfig(BaseModel):
    dir: str = "./checkpoints/{run_id}/"


class LoggingConfig(BaseModel):
    level: str = "INFO"
    dir: str = "./checkpoints/{run_id}/"
    format: str = "json"


class EvaluatorConfig(BaseModel):
    # Weights for the five judge axes. Empty dict → evaluator uses its
    # hardcoded equal-weight default (0.2 each). Override per-axis as needed;
    # only keys in the canonical axis set are honoured.
    axis_weights: dict[str, float] = {}


class ARIConfig(BaseModel):
    llm: LLMConfig = LLMConfig()
    skills: list[SkillConfig] = []
    disabled_tools: list[str] = []  # Tool names to hide from the agent
    bfts: BFTSConfig = BFTSConfig()
    checkpoint: CheckpointConfig = CheckpointConfig()
    logging: LoggingConfig = LoggingConfig()
    evaluator: EvaluatorConfig = EvaluatorConfig()
    resources: dict = {}  # Generic resource config (cpus, timeout_minutes, etc.)
    model_config = {"extra": "allow"}  # Accept unknown top-level keys


def _resolve_env_vars(value: str) -> str:
    pattern = re.compile(r"\$\{(\w+)\}")
    return pattern.sub(lambda m: os.environ.get(m.group(1), ""), value)


def _resolve_env_recursive(data):
    if isinstance(data, dict):
        return {k: _resolve_env_recursive(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_resolve_env_recursive(item) for item in data]
    if isinstance(data, str):
        return _resolve_env_vars(data)
    return data


def _apply_memory_section(raw: dict) -> None:
    """Export the workflow.yaml ``memory:`` section as env vars.

    settings.json and env vars override these values; absence of the
    section logs a deprecation WARNING so v0.5.x workflow.yaml imports
    are visible to the operator.
    """
    import logging
    log = logging.getLogger(__name__)
    mem = raw.get("memory")
    if mem is None:
        log.warning(
            "workflow.yaml has no `memory:` section — defaulting to "
            "backend=letta, base_url=http://localhost:8283."
        )
        return
    backend = (mem.get("backend") or "letta").strip().lower()
    os.environ.setdefault("ARI_MEMORY_BACKEND", backend)
    letta = mem.get("letta") or {}
    if letta.get("base_url"):
        os.environ.setdefault("LETTA_BASE_URL", str(letta["base_url"]))
    if letta.get("embedding_config"):
        os.environ.setdefault(
            "LETTA_EMBEDDING_CONFIG", str(letta["embedding_config"])
        )


def load_config(path: str) -> ARIConfig:
    """Load configuration from config.yaml. Returns auto_config if the file does not exist."""
    config_path = Path(path)
    if not config_path.exists():
        return auto_config()
    with open(config_path) as f:
        raw = yaml.safe_load(f) or {}
    raw = _resolve_env_recursive(raw)
    _apply_memory_section(raw)
    # Resolve {{ari_root}} in skill paths (and anywhere else in config)
    _ari_root = os.environ.get("ARI_ROOT", str(Path(__file__).resolve().parents[2]))
    def _resolve_ari_root(data):
        if isinstance(data, dict):
            return {k: _resolve_ari_root(v) for k, v in data.items()}
        if isinstance(data, list):
            return [_resolve_ari_root(item) for item in data]
        if isinstance(data, str):
            return data.replace("{{ari_root}}", _ari_root)
        return data
    raw = _resolve_ari_root(raw)
    if "skills" not in raw:
        cfg = ARIConfig(**{k: v for k, v in raw.items() if k in ARIConfig.model_fields})
        cfg.skills = _discover_skills()
        _merge_bfts_disabled_tools(cfg, raw)
        _apply_llm_env_overrides(cfg)
        _apply_checkpoint_env_overrides(cfg)
        return cfg
    cfg = ARIConfig(**{k: v for k, v in raw.items() if k in ARIConfig.model_fields})
    _merge_bfts_disabled_tools(cfg, raw)
    _apply_llm_env_overrides(cfg)
    _apply_checkpoint_env_overrides(cfg)
    return cfg


def _apply_checkpoint_env_overrides(cfg: "ARIConfig") -> None:
    """Let ARI_CHECKPOINT_DIR override checkpoint.dir from YAML.

    The GUI launcher pre-creates a checkpoint directory and passes its path via
    ARI_CHECKPOINT_DIR so the spawned CLI writes tree.json to the same place the
    GUI is watching. Without this override, load_config() ignores the env var
    and the CLI creates a sibling {run_id} directory, so the GUI sees no nodes.
    """
    _ckpt = os.environ.get("ARI_CHECKPOINT_DIR", "")
    if _ckpt:
        cfg.checkpoint.dir = _ckpt
    _log = os.environ.get("ARI_LOG_DIR", "")
    if _log:
        cfg.logging.dir = _log
    elif _ckpt:
        cfg.logging.dir = _ckpt


def apply_bfts_env_overrides(cfg: "ARIConfig") -> None:
    """Let GUI-injected ARI_MAX_NODES/DEPTH/REACT/PARALLEL/TIMEOUT_NODE win over YAML.

    Without this, workflow.yaml and environment profiles (laptop/hpc/cloud) are
    authoritative and silently contradict the caps the GUI wizard specifies.
    Call this AFTER any profile overrides so the explicit user choice wins.
    """
    _n = os.environ.get("ARI_MAX_NODES")
    if _n:
        try: cfg.bfts.max_total_nodes = int(_n)
        except ValueError: pass
    _d = os.environ.get("ARI_MAX_DEPTH")
    if _d:
        try: cfg.bfts.max_depth = int(_d)
        except ValueError: pass
    _r = os.environ.get("ARI_MAX_REACT")
    if _r:
        try: cfg.bfts.max_react_steps = int(_r)
        except ValueError: pass
    _p = os.environ.get("ARI_PARALLEL")
    if _p:
        try: cfg.bfts.max_parallel_nodes = int(_p)
        except ValueError: pass
    _t = os.environ.get("ARI_TIMEOUT_NODE")
    if _t:
        try: cfg.bfts.timeout_per_node = int(_t)
        except ValueError: pass


def _apply_llm_env_overrides(cfg: "ARIConfig") -> None:
    """Let GUI-injected ARI_MODEL / ARI_BACKEND / ARI_LLM_API_BASE override YAML.

    Without this, workflow.yaml's `llm.model` is authoritative and silently
    contradicts the model the GUI wizard/settings pass via env vars.
    """
    _m = os.environ.get("ARI_MODEL") or os.environ.get("ARI_LLM_MODEL")
    if _m:
        cfg.llm.model = _m
    _b = os.environ.get("ARI_BACKEND")
    if _b:
        cfg.llm.backend = _b
    _u = os.environ.get("ARI_LLM_API_BASE")
    if _u is not None and _u != "":
        cfg.llm.base_url = _u


def _merge_bfts_disabled_tools(cfg: "ARIConfig", raw: dict) -> None:
    """Auto-disable MCP tools whose bfts_pipeline stage is disabled.

    When a user toggles a BFTS stage off in the GUI, the stage's `tool`
    is added to `disabled_tools` so the AgentLoop cannot call it either.
    """
    for stage in raw.get("bfts_pipeline") or []:
        if not stage.get("enabled", True):
            tool = stage.get("tool", "")
            if tool and tool not in cfg.disabled_tools:
                cfg.disabled_tools.append(tool)


def _discover_skills(base_dir: Path | None = None) -> list[SkillConfig]:
    """Auto-detect ari-skill-* directories and return a list of SkillConfig."""
    if base_dir is None:
        base_dir = Path(__file__).resolve().parents[2]
    skills = []
    for skill_dir in sorted(base_dir.glob("ari-skill-*")):
        server = skill_dir / "src" / "server.py"
        if server.exists():
            skills.append(SkillConfig(name=skill_dir.name, path=str(skill_dir)))
    return skills


def auto_config() -> ARIConfig:
    """Default configuration when config.yaml is omitted. Can be overridden by environment variables."""
    # Determine backend from model name
    _model = os.environ.get("ARI_MODEL", "qwen3:8b")
    # Backend is determined solely by ARI_BACKEND env var (set by GUI wizard or user).
    # No model-name guessing here — that violates the Zero Domain Knowledge Principle.
    _backend = os.environ.get("ARI_BACKEND", "ollama")
    _base_url = os.environ.get("OLLAMA_HOST", "http://localhost:11434") if _backend == "ollama" else os.environ.get("LLM_API_BASE", None)
    # Checkpoint dir: ARI_CHECKPOINT_DIR (explicit) > workspace/checkpoints/{run_id}/
    # Use PathManager-based workspace path so CLI and GUI share the same location.
    _ckpt_dir = os.environ.get("ARI_CHECKPOINT_DIR", "")
    if not _ckpt_dir:
        _ari_root = Path(__file__).resolve().parents[2]  # ARI/
        _ckpt_dir = str(_ari_root / "workspace" / "checkpoints" / "{run_id}")
    _log_dir = os.environ.get("ARI_LOG_DIR", _ckpt_dir)
    return ARIConfig(
        llm=LLMConfig(
            backend=_backend,
            model=_model,
            base_url=_base_url,
        ),
        skills=_discover_skills(),
        bfts=BFTSConfig(
            max_depth=int(os.environ.get("ARI_MAX_DEPTH", 5)),
            max_total_nodes=int(os.environ.get("ARI_MAX_NODES", 50)),
            max_react_steps=int(os.environ.get("ARI_MAX_REACT", 80)),
            timeout_per_node=int(os.environ.get("ARI_TIMEOUT_NODE", 7200)),
            max_parallel_nodes=int(os.environ.get("ARI_PARALLEL", 4)),
        ),
        checkpoint=CheckpointConfig(
            dir=_ckpt_dir,
        ),
        logging=LoggingConfig(
            dir=_log_dir,
            level=os.environ.get("ARI_LOG_LEVEL", "INFO"),
        ),
        resources={
            k: v for k, v in {
                "cpus": os.environ.get("ARI_SLURM_CPUS"),
                "memory_gb": os.environ.get("ARI_SLURM_MEM_GB"),
                "gpus": os.environ.get("ARI_SLURM_GPUS"),
                "walltime": os.environ.get("ARI_SLURM_WALLTIME"),
                "partition": os.environ.get("ARI_SLURM_PARTITION"),
            }.items() if v is not None
        },
    )


# Backward-compatible alias
AppConfig = ARIConfig
