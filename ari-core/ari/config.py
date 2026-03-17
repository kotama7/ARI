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


class BFTSConfig(BaseModel):
    max_depth: int = 5
    max_retries_per_node: int = 3
    max_total_nodes: int = 50
    timeout_per_node: int = 7200
    max_parallel_nodes: int = 4


class CheckpointConfig(BaseModel):
    dir: str = "./checkpoints/{run_id}/"


class LoggingConfig(BaseModel):
    level: str = "INFO"
    dir: str = "./logs/{run_id}/"
    format: str = "json"


class ARIConfig(BaseModel):
    llm: LLMConfig = LLMConfig()
    skills: list[SkillConfig] = []
    bfts: BFTSConfig = BFTSConfig()
    checkpoint: CheckpointConfig = CheckpointConfig()
    logging: LoggingConfig = LoggingConfig()


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


def load_config(path: str) -> ARIConfig:
    """Load configuration from config.yaml. Returns auto_config if the file does not exist."""
    config_path = Path(path)
    if not config_path.exists():
        return auto_config()
    with open(config_path) as f:
        raw = yaml.safe_load(f) or {}
    raw = _resolve_env_recursive(raw)
    if "skills" not in raw:
        cfg = ARIConfig(**{k: v for k, v in raw.items() if k in ARIConfig.model_fields})
        cfg.skills = _discover_skills()
        return cfg
    return ARIConfig(**{k: v for k, v in raw.items() if k in ARIConfig.model_fields})


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
    return ARIConfig(
        llm=LLMConfig(
            backend="ollama",
            model=os.environ.get("ARI_MODEL", "qwen3:8b"),
            base_url=os.environ.get("OLLAMA_HOST", "http://localhost:11434"),
        ),
        skills=_discover_skills(),
        bfts=BFTSConfig(
            max_depth=int(os.environ.get("ARI_MAX_DEPTH", 5)),
            max_total_nodes=int(os.environ.get("ARI_MAX_NODES", 50)),
            max_parallel_nodes=int(os.environ.get("ARI_PARALLEL", 4)),
        ),
        checkpoint=CheckpointConfig(
            dir=os.environ.get("ARI_CHECKPOINT_DIR", "./checkpoints/{run_id}/"),
        ),
        logging=LoggingConfig(
            dir=os.environ.get("ARI_LOG_DIR", "./logs/{run_id}/"),
            level=os.environ.get("ARI_LOG_LEVEL", "INFO"),
        ),
    )


# Backward-compatible alias
AppConfig = ARIConfig
