"""Configuration models for ARI using Pydantic."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


class LLMConfig(BaseModel):
    backend: str = Field(
        "ollama",
        description="LLM backend identifier consumed by the agent loop "
                    "(`ollama`, `openai`, `litellm`, ...). Overridden by "
                    "the `ARI_BACKEND` environment variable.",
    )
    model: str = Field(
        "qwen3:8b",
        description="LiteLLM-style model identifier. Overridden by "
                    "`ARI_MODEL` / `ARI_LLM_MODEL` env vars at load time.",
    )
    api_key: str | None = Field(
        None,
        description="API key for the chosen backend. Prefer setting via "
                    "the provider-specific env var (`OPENAI_API_KEY`, ...).",
    )
    base_url: str | None = Field(
        None,
        description="API base URL override. Required when pointing at a "
                    "self-hosted Ollama / OpenAI-compatible endpoint; "
                    "overridden by `ARI_LLM_API_BASE` / `OLLAMA_HOST`.",
    )
    temperature: float = Field(
        0.7,
        description="Sampling temperature applied to non-judge LLM calls.",
    )


class SkillConfig(BaseModel):
    name: str = Field(
        ...,
        description="Skill package directory name (e.g. `ari-skill-coding`).",
    )
    path: str = Field(
        ...,
        description="Filesystem path to the skill package root.",
    )
    description: str = Field(
        "",
        description="Optional human-readable description; mirrors "
                    "`mcp.json:description` when present.",
    )
    phase: str | list[str] = Field(
        "all",
        description="Pipeline phase(s) in which this skill is exposed to "
                    "the AgentLoop ReAct. Single string (`bfts` / `paper` "
                    "/ `reproduce` / `all` / `none`) or a list. `all` "
                    "matches any phase; `none` disables the skill.",
    )


class BFTSConfig(BaseModel):
    max_depth: int = Field(
        5,
        description="Hard cap on BFTS tree depth. Overridden by "
                    "`ARI_MAX_DEPTH`.",
    )
    max_total_nodes: int = Field(
        50,
        description="Hard cap on total BFTS nodes per run. Overridden "
                    "by `ARI_MAX_NODES`.",
    )
    max_react_steps: int = Field(
        80,
        description="Maximum ReAct iterations within a single node. "
                    "Overridden by `ARI_MAX_REACT`.",
    )
    timeout_per_node: int = Field(
        7200,
        description="Per-node wall-time budget in seconds. Overridden "
                    "by `ARI_TIMEOUT_NODE`.",
    )
    max_parallel_nodes: int = Field(
        4,
        description="Maximum BFTS nodes that may execute concurrently. "
                    "Overridden by `ARI_PARALLEL`.",
    )
    max_expansions_per_node: int = Field(
        4,
        description="Maximum times a single frontier node may be re-expanded "
                    "before BFTS retires it. Higher values let one good "
                    "parent spawn more siblings; lower values force the "
                    "search to spread.",
    )
    label_saturation_threshold: int = Field(
        2,
        description="When ≥ this many children of the SAME parent share a "
                    "label, expand() flags that label as 'saturated' in the "
                    "next prompt and asks the planner to pick a different "
                    "one. Default 2 matches the pre-audit behaviour.",
    )
    frontier_score: Literal[
        "scientific_plus_diversity",
        "scientific_only",
        "depth_penalized",
        "ucb_like",
    ] = Field(
        "scientific_plus_diversity",
        description="Strategy used by BFTS's deterministic fallback when "
                    "the LLM selector cannot pick a candidate. "
                    "`scientific_plus_diversity` (default) matches the "
                    "previous behaviour. `scientific_only` drops the "
                    "diversity bonus. `depth_penalized` subtracts "
                    "`depth_penalty_lambda * depth`. `ucb_like` adds a "
                    "UCB1-style exploration term scaled by `ucb_c`.",
    )
    depth_penalty_lambda: float = Field(
        0.05,
        description="Per-depth penalty applied when frontier_score="
                    "`depth_penalized`. Ignored by other strategies.",
    )
    ucb_c: float = Field(
        0.5,
        description="Exploration coefficient for frontier_score="
                    "`ucb_like`. The exploration term is "
                    "`ucb_c * sqrt(log(N) / (visits + 1))`. Ignored by "
                    "other strategies.",
    )
    select_prompt: str = Field(
        "orchestrator/bfts_select",
        description="FilesystemPromptLoader key for select_next_node. "
                    "The .md template must accept {experiment_goal}, "
                    "{memory_context}, and {candidates} placeholders and "
                    "must reply with a single 0-based integer index.",
    )
    expand_select_prompt: str = Field(
        "orchestrator/bfts_expand_select",
        description="FilesystemPromptLoader key for select_best_to_expand. "
                    "Template must accept {experiment_goal} and "
                    "{candidates} and reply with a 0-based integer index.",
    )


class CheckpointConfig(BaseModel):
    dir: str = Field(
        "./checkpoints/{run_id}/",
        description="Checkpoint root template. `{run_id}` is substituted "
                    "at run start. Overridden by `ARI_CHECKPOINT_DIR` "
                    "(an explicit env path always wins).",
    )


class LoggingConfig(BaseModel):
    level: str = Field(
        "INFO",
        description="Python `logging` level. Overridden by "
                    "`ARI_LOG_LEVEL`.",
    )
    dir: str = Field(
        "./checkpoints/{run_id}/",
        description="Log directory. Defaults to the active checkpoint "
                    "(via `ARI_LOG_DIR` or `ARI_CHECKPOINT_DIR`).",
    )
    format: str = Field(
        "json",
        description="Log record format (`json` for machine-parseable "
                    "lines or `text` for human-readable).",
    )


class CustomAxisSpec(BaseModel):
    """One user-defined evaluation axis used when EvaluatorConfig.axis_mode=`custom`."""

    name: str = Field(..., description="Axis identifier (snake_case).")
    description: str = Field(
        "",
        description="Short prose describing what the axis measures. Sent to "
                    "the judge LLM so it knows how to score this axis.",
    )
    weight: float = Field(
        0.2,
        description="Per-axis weight used by the composite formula. "
                    "Normalisation is handled by the formula itself.",
    )


class EvaluatorConfig(BaseModel):
    axis_weights: dict[str, float] = Field(
        default_factory=dict,
        description="Per-axis weight overrides for the BFTS judge. "
                    "Empty → equal weights (0.2 each). Only keys in "
                    "the canonical axis set are honoured; unknown keys "
                    "are silently dropped.",
    )
    composite: Literal[
        "harmonic_mean",
        "arithmetic_mean",
        "weighted_min",
        "geometric_mean",
    ] = Field(
        "harmonic_mean",
        description="Formula used to collapse per-axis scores into the "
                    "scalar `_scientific_score`. `harmonic_mean` (default) "
                    "matches the pre-audit behaviour and heavily penalises "
                    "any weak axis. `arithmetic_mean` is permissive. "
                    "`weighted_min` returns the lowest axis (bottleneck "
                    "view). `geometric_mean` is between harmonic and "
                    "arithmetic.",
    )
    axis_mode: Literal["legacy", "dynamic", "custom"] = Field(
        "dynamic",
        description="`dynamic` (default) builds axes from the active rubric "
                    "and idea.json plan keywords. `legacy` pins to the "
                    "fixed 5-axis canonical set. `custom` uses the "
                    "`custom_axes` list verbatim.",
    )
    custom_axes: list[CustomAxisSpec] = Field(
        default_factory=list,
        description="Axis definitions consulted only when "
                    "axis_mode=`custom`.",
    )


class ARIConfig(BaseModel):
    llm: LLMConfig = Field(
        default_factory=LLMConfig,
        description="LLM backend configuration shared by the agent loop "
                    "and most LLM-using skills.",
    )
    skills: list[SkillConfig] = Field(
        default_factory=list,
        description="Skills to register with the agent. Auto-discovered "
                    "via `_discover_skills()` when the YAML omits the "
                    "section.",
    )
    disabled_tools: list[str] = Field(
        default_factory=list,
        description="MCP tool names hidden from the agent. The viz "
                    "wizard appends to this list when stages are toggled "
                    "off.",
    )
    bfts: BFTSConfig = Field(
        default_factory=BFTSConfig,
        description="BFTS exploration limits.",
    )
    checkpoint: CheckpointConfig = Field(
        default_factory=CheckpointConfig,
        description="Checkpoint directory configuration.",
    )
    logging: LoggingConfig = Field(
        default_factory=LoggingConfig,
        description="Logging configuration.",
    )
    evaluator: EvaluatorConfig = Field(
        default_factory=EvaluatorConfig,
        description="Evaluator (BFTS judge) configuration.",
    )
    resources: dict = Field(
        default_factory=dict,
        description="Generic resource defaults (cpus, memory_gb, gpus, "
                    "walltime, partition) used by the HPC skill when a "
                    "stage does not override them.",
    )
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
    # Resolve {{ari_root}} in skill paths (and anywhere else in config).
    # Phase 2 converted ``config.py`` → ``config/__init__.py`` so this
    # file now sits one level deeper; ``parents[3]`` reaches the repo
    # root (the parent of ``ari-core/``) where the ``ari-skill-*``
    # directories live.
    _ari_root = os.environ.get("ARI_ROOT", str(Path(__file__).resolve().parents[3]))
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
    from ari.paths import PathManager
    _ckpt_path = PathManager.checkpoint_dir_from_env()
    _ckpt = str(_ckpt_path) if _ckpt_path is not None else ""
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
    # GUI wizard's frontier-selection strategy choice. Pydantic does not
    # validate on assignment, so guard against unknown values from env.
    _fs = os.environ.get("ARI_FRONTIER_SCORE")
    if _fs in (
        "scientific_plus_diversity",
        "scientific_only",
        "depth_penalized",
        "ucb_like",
    ):
        cfg.bfts.frontier_score = _fs


def apply_evaluator_env_overrides(cfg: "ARIConfig") -> None:
    """Let GUI-injected ARI_COMPOSITE / ARI_AXIS_MODE win over YAML.

    Mirrors apply_bfts_env_overrides for the evaluator's per-experiment knobs.
    Pydantic does not validate on assignment, so each value is checked against
    its allowed set before being written. Call this AFTER any profile overrides
    so the explicit GUI choice wins.
    """
    _comp = os.environ.get("ARI_COMPOSITE")
    if _comp in (
        "harmonic_mean",
        "arithmetic_mean",
        "weighted_min",
        "geometric_mean",
    ):
        cfg.evaluator.composite = _comp
    _am = os.environ.get("ARI_AXIS_MODE")
    if _am in ("legacy", "dynamic", "custom"):
        cfg.evaluator.axis_mode = _am


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
        # Phase 2 — file moved into a package; ``parents[3]`` reaches
        # the repo root (alongside the ``ari-skill-*`` directories).
        base_dir = Path(__file__).resolve().parents[3]
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
    from ari.paths import PathManager
    _ckpt_path = PathManager.checkpoint_dir_from_env()
    _ckpt_dir = str(_ckpt_path) if _ckpt_path is not None else ""
    if not _ckpt_dir:
        # Phase 2 — file moved into a package, so we walk up one extra
        # parent to reach the repo root (``ARI/``).
        _ari_root = Path(__file__).resolve().parents[3]  # ARI/
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
