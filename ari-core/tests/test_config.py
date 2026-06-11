"""Tests for ari-core configuration loading."""

import contextlib
import tempfile
from pathlib import Path

import yaml

from ari.config import (
    ARIConfig,
    BFTSConfig,
    LLMConfig,
    SkillConfig,
    auto_config,
    load_config,
)


def test_default_config():
    cfg = ARIConfig()
    assert cfg.llm.backend == "ollama"
    assert cfg.llm.temperature == 0.7
    assert cfg.bfts.max_depth == 5
    assert cfg.bfts.max_total_nodes == 50


def test_bfts_defaults():
    bfts = BFTSConfig()
    assert bfts.max_parallel_nodes == 4
    assert bfts.timeout_per_node == 7200


def test_load_config_from_yaml():
    data = {
        "llm": {"backend": "openai", "model": "gpt-4o", "temperature": 0.3},
        "bfts": {"max_depth": 10},
        "skills": [{"name": "hpc", "path": "/tmp/hpc"}],
    }
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False
    ) as f:
        yaml.dump(data, f)
        fpath = f.name

    cfg = load_config(fpath)
    assert cfg.llm.backend == "openai"
    assert cfg.llm.model == "gpt-4o"
    assert cfg.llm.temperature == 0.3
    assert cfg.bfts.max_depth == 10
    assert len(cfg.skills) == 1
    assert cfg.skills[0].name == "hpc"


def test_load_config_missing_file():
    cfg = load_config("/nonexistent/path/config.yaml")
    assert isinstance(cfg, ARIConfig)


def test_auto_config_returns_ariconfig():
    cfg = auto_config()
    assert isinstance(cfg, ARIConfig)
    assert cfg.llm.backend == "ollama"


def test_env_var_resolution(monkeypatch):
    monkeypatch.setenv("MY_MODEL", "llama3:70b")
    data = {"llm": {"model": "${MY_MODEL}"}}
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False
    ) as f:
        yaml.dump(data, f)
        fpath = f.name
    cfg = load_config(fpath)
    assert cfg.llm.model == "llama3:70b"


def test_skill_config():
    sc = SkillConfig(name="paper", path="/tmp/paper")
    assert sc.name == "paper"


def _write_yaml(data: dict) -> str:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(data, f)
        return f.name


def test_env_overrides_yaml_model(monkeypatch):
    """ARI_MODEL env var must override llm.model in workflow.yaml (GUI precedence)."""
    monkeypatch.setenv("ARI_MODEL", "gpt-4o-mini")
    monkeypatch.delenv("ARI_LLM_MODEL", raising=False)
    fpath = _write_yaml({"llm": {"backend": "openai", "model": "gpt-5.2"}})
    cfg = load_config(fpath)
    assert cfg.llm.model == "gpt-4o-mini"


def test_env_overrides_yaml_backend(monkeypatch):
    monkeypatch.setenv("ARI_BACKEND", "anthropic")
    monkeypatch.delenv("ARI_MODEL", raising=False)
    monkeypatch.delenv("ARI_LLM_MODEL", raising=False)
    fpath = _write_yaml({"llm": {"backend": "openai", "model": "gpt-5.2"}})
    cfg = load_config(fpath)
    assert cfg.llm.backend == "anthropic"
    assert cfg.llm.model == "gpt-5.2"  # no model override → YAML retained


def test_ari_llm_model_env_overrides_yaml(monkeypatch):
    """ARI_LLM_MODEL is the fallback GUI injects alongside ARI_MODEL."""
    monkeypatch.delenv("ARI_MODEL", raising=False)
    monkeypatch.setenv("ARI_LLM_MODEL", "claude-sonnet-4-5")
    fpath = _write_yaml({"llm": {"backend": "openai", "model": "gpt-5.2"}})
    cfg = load_config(fpath)
    assert cfg.llm.model == "claude-sonnet-4-5"


def test_env_absent_keeps_yaml_model(monkeypatch):
    """When no LLM env vars are set, YAML model must be preserved."""
    monkeypatch.delenv("ARI_MODEL", raising=False)
    monkeypatch.delenv("ARI_LLM_MODEL", raising=False)
    monkeypatch.delenv("ARI_BACKEND", raising=False)
    fpath = _write_yaml({"llm": {"backend": "openai", "model": "gpt-5.2"}})
    cfg = load_config(fpath)
    assert cfg.llm.model == "gpt-5.2"
    assert cfg.llm.backend == "openai"


def test_ari_llm_api_base_override(monkeypatch):
    monkeypatch.setenv("ARI_LLM_API_BASE", "http://override.local:9000")
    monkeypatch.delenv("ARI_MODEL", raising=False)
    fpath = _write_yaml({"llm": {"backend": "openai", "model": "gpt-5.2", "base_url": "http://yaml.local"}})
    cfg = load_config(fpath)
    assert cfg.llm.base_url == "http://override.local:9000"


def test_ari_checkpoint_dir_env_overrides_yaml_default(monkeypatch, tmp_path):
    """ARI_CHECKPOINT_DIR must override CheckpointConfig defaults when loading YAML.

    Regression: GUI launcher pre-creates a checkpoint dir and passes it via
    ARI_CHECKPOINT_DIR; without this override, cli.run() creates a sibling
    {run_id} dir and tree.json is written where the GUI is not watching.
    """
    target = str(tmp_path / "gui_precreated_ckpt")
    monkeypatch.setenv("ARI_CHECKPOINT_DIR", target)
    fpath = _write_yaml({"llm": {"backend": "openai", "model": "gpt-5.2"}})
    cfg = load_config(fpath)
    assert cfg.checkpoint.dir == target
    assert "{run_id}" not in cfg.checkpoint.dir
    assert cfg.logging.dir == target  # logs follow checkpoint unless ARI_LOG_DIR set


def test_ari_checkpoint_dir_env_overrides_yaml_explicit(monkeypatch, tmp_path):
    """ARI_CHECKPOINT_DIR wins over an explicit checkpoint.dir in YAML."""
    target = str(tmp_path / "override")
    monkeypatch.setenv("ARI_CHECKPOINT_DIR", target)
    fpath = _write_yaml({
        "llm": {"backend": "openai", "model": "gpt-5.2"},
        "checkpoint": {"dir": "./yaml/checkpoints/{run_id}/"},
    })
    cfg = load_config(fpath)
    assert cfg.checkpoint.dir == target


def test_ari_log_dir_env_overrides_checkpoint(monkeypatch, tmp_path):
    """ARI_LOG_DIR overrides logging.dir independently of ARI_CHECKPOINT_DIR."""
    ckpt = str(tmp_path / "ckpt")
    logs = str(tmp_path / "logs")
    monkeypatch.setenv("ARI_CHECKPOINT_DIR", ckpt)
    monkeypatch.setenv("ARI_LOG_DIR", logs)
    fpath = _write_yaml({"llm": {"backend": "openai", "model": "gpt-5.2"}})
    cfg = load_config(fpath)
    assert cfg.checkpoint.dir == ckpt
    assert cfg.logging.dir == logs


def test_ari_checkpoint_absent_keeps_yaml_default(monkeypatch):
    """Without ARI_CHECKPOINT_DIR, load_config retains the YAML/pydantic default."""
    monkeypatch.delenv("ARI_CHECKPOINT_DIR", raising=False)
    monkeypatch.delenv("ARI_LOG_DIR", raising=False)
    fpath = _write_yaml({"llm": {"backend": "openai", "model": "gpt-5.2"}})
    cfg = load_config(fpath)
    assert "{run_id}" in cfg.checkpoint.dir  # default preserved


def test_ari_checkpoint_dir_with_skills_branch(monkeypatch, tmp_path):
    """The skills-absent branch of load_config also honors ARI_CHECKPOINT_DIR.

    load_config has two branches depending on whether `skills` is in the YAML;
    both must apply the checkpoint env override.
    """
    target = str(tmp_path / "with_skills_ckpt")
    monkeypatch.setenv("ARI_CHECKPOINT_DIR", target)
    fpath = _write_yaml({
        "llm": {"backend": "openai", "model": "gpt-5.2"},
        "skills": [{"name": "hpc", "path": "/tmp/hpc"}],
    })
    cfg = load_config(fpath)
    assert cfg.checkpoint.dir == target


# ── apply_bfts_env_overrides ───────────────────────────────────────────
# Regression: GUI wizard sets ARI_MAX_NODES/DEPTH/REACT/PARALLEL/TIMEOUT_NODE
# but load_config + _apply_profile silently discarded them, so GUI caps were
# bypassed and runs exceeded the user-specified limits.


def _clear_bfts_env(monkeypatch):
    for v in (
        "ARI_MAX_NODES", "ARI_MAX_DEPTH", "ARI_MAX_REACT",
        "ARI_PARALLEL", "ARI_TIMEOUT_NODE",
    ):
        monkeypatch.delenv(v, raising=False)


def test_bfts_env_overrides_all_fields(monkeypatch):
    from ari.config import ARIConfig, apply_bfts_env_overrides
    _clear_bfts_env(monkeypatch)
    monkeypatch.setenv("ARI_MAX_NODES", "10")
    monkeypatch.setenv("ARI_MAX_DEPTH", "3")
    monkeypatch.setenv("ARI_MAX_REACT", "20")
    monkeypatch.setenv("ARI_PARALLEL", "2")
    monkeypatch.setenv("ARI_TIMEOUT_NODE", "600")
    cfg = ARIConfig()
    apply_bfts_env_overrides(cfg)
    assert cfg.bfts.max_total_nodes == 10
    assert cfg.bfts.max_depth == 3
    assert cfg.bfts.max_react_steps == 20
    assert cfg.bfts.max_parallel_nodes == 2
    assert cfg.bfts.timeout_per_node == 600


def test_bfts_env_overrides_preserve_unset(monkeypatch):
    """Only env vars that are present override; others stay at YAML/default."""
    from ari.config import ARIConfig, apply_bfts_env_overrides
    _clear_bfts_env(monkeypatch)
    monkeypatch.setenv("ARI_MAX_NODES", "7")
    cfg = ARIConfig()
    cfg.bfts.max_parallel_nodes = 4  # simulate profile default
    cfg.bfts.max_depth = 5
    apply_bfts_env_overrides(cfg)
    assert cfg.bfts.max_total_nodes == 7
    assert cfg.bfts.max_parallel_nodes == 4  # untouched
    assert cfg.bfts.max_depth == 5            # untouched


def test_bfts_env_overrides_ignore_invalid(monkeypatch):
    """Non-integer env values must not raise and must leave the field intact."""
    from ari.config import ARIConfig, apply_bfts_env_overrides
    _clear_bfts_env(monkeypatch)
    monkeypatch.setenv("ARI_MAX_NODES", "not-a-number")
    cfg = ARIConfig()
    cfg.bfts.max_total_nodes = 42
    apply_bfts_env_overrides(cfg)
    assert cfg.bfts.max_total_nodes == 42


def test_bfts_env_overrides_win_over_profile(monkeypatch, tmp_path):
    """End-to-end precedence: workflow.yaml → profile → GUI env.

    Reproduces the exact failure mode the user hit: GUI specified max=10 but
    the run created 17 nodes because the profile path was broken and env vars
    were ignored. With all fixes applied, GUI env must win.
    """
    from ari.cli import _apply_profile
    from ari.config import apply_bfts_env_overrides, load_config
    _clear_bfts_env(monkeypatch)

    # Minimal YAML (no bfts block) — relies on pydantic defaults
    fpath = _write_yaml({"llm": {"backend": "openai", "model": "gpt-5.2"}})
    cfg = load_config(fpath)
    # Defaults
    assert cfg.bfts.max_total_nodes == 50
    assert cfg.bfts.max_parallel_nodes == 4

    # Apply the real laptop profile (tests the path fix too)
    _apply_profile(cfg, "laptop")
    assert cfg.bfts.max_total_nodes == 8, "laptop profile must cap nodes to 8"
    assert cfg.bfts.max_parallel_nodes == 2, (
        "laptop profile's `parallel: 2` must map to max_parallel_nodes (field-name fix)"
    )

    # GUI env override
    monkeypatch.setenv("ARI_MAX_NODES", "10")
    monkeypatch.setenv("ARI_PARALLEL", "3")
    apply_bfts_env_overrides(cfg)
    assert cfg.bfts.max_total_nodes == 10
    assert cfg.bfts.max_parallel_nodes == 3


def test_profile_file_is_findable():
    """The profile directory resolution must find the real YAMLs in ari-core/config/profiles/.

    Regression: an extra .parent hop pointed at the repo root and silently
    dropped every override (laptop/hpc/cloud) without warning.

    Phase 3A note: ``ari.cli`` became a package; ``__file__`` is now
    ``ari/cli/__init__.py`` so we walk up one extra level to land on
    ``ari-core/``.
    """
    from pathlib import Path
    from ari import cli as _cli
    cli_init = Path(_cli.__file__)
    if cli_init.parent.name == "cli":
        ari_root = cli_init.parent.parent.parent
    else:
        ari_root = cli_init.parent.parent
    profiles_dir = ari_root / "config" / "profiles"
    for name in ("laptop", "hpc", "cloud"):
        assert (profiles_dir / f"{name}.yaml").exists(), (
            f"profile {name}.yaml must be discoverable at {profiles_dir}"
        )


# ── algorithm-switch env overrides ─────────────────────────────────────
# GUI wizard exposes frontier_score / composite / axis_mode. They reach the
# subprocess as ARI_FRONTIER_SCORE / ARI_COMPOSITE / ARI_AXIS_MODE and must
# override YAML/profile defaults. Pydantic does not validate on assignment,
# so unknown values must be rejected by a membership guard.


def _clear_algo_env(monkeypatch):
    for v in ("ARI_FRONTIER_SCORE", "ARI_COMPOSITE", "ARI_AXIS_MODE"):
        monkeypatch.delenv(v, raising=False)


def test_frontier_score_env_override(monkeypatch):
    from ari.config import ARIConfig, apply_bfts_env_overrides
    _clear_algo_env(monkeypatch)
    monkeypatch.setenv("ARI_FRONTIER_SCORE", "ucb_like")
    cfg = ARIConfig()
    assert cfg.bfts.frontier_score == "scientific_plus_diversity"
    apply_bfts_env_overrides(cfg)
    assert cfg.bfts.frontier_score == "ucb_like"


def test_frontier_score_env_ignores_invalid(monkeypatch):
    from ari.config import ARIConfig, apply_bfts_env_overrides
    _clear_algo_env(monkeypatch)
    monkeypatch.setenv("ARI_FRONTIER_SCORE", "totally_bogus")
    cfg = ARIConfig()
    apply_bfts_env_overrides(cfg)
    assert cfg.bfts.frontier_score == "scientific_plus_diversity"


def test_evaluator_env_overrides(monkeypatch):
    from ari.config import ARIConfig, apply_evaluator_env_overrides
    _clear_algo_env(monkeypatch)
    monkeypatch.setenv("ARI_COMPOSITE", "weighted_min")
    monkeypatch.setenv("ARI_AXIS_MODE", "legacy")
    cfg = ARIConfig()
    assert cfg.evaluator.composite == "harmonic_mean"
    assert cfg.evaluator.axis_mode == "dynamic"
    apply_evaluator_env_overrides(cfg)
    assert cfg.evaluator.composite == "weighted_min"
    assert cfg.evaluator.axis_mode == "legacy"


def test_evaluator_env_ignores_invalid(monkeypatch):
    from ari.config import ARIConfig, apply_evaluator_env_overrides
    _clear_algo_env(monkeypatch)
    monkeypatch.setenv("ARI_COMPOSITE", "nonsense")
    monkeypatch.setenv("ARI_AXIS_MODE", "nonsense")
    cfg = ARIConfig()
    apply_evaluator_env_overrides(cfg)
    assert cfg.evaluator.composite == "harmonic_mean"
    assert cfg.evaluator.axis_mode == "dynamic"


def test_evaluator_env_preserves_unset(monkeypatch):
    """Only present env vars override; the other field stays at its default."""
    from ari.config import ARIConfig, apply_evaluator_env_overrides
    _clear_algo_env(monkeypatch)
    monkeypatch.setenv("ARI_COMPOSITE", "geometric_mean")
    cfg = ARIConfig()
    apply_evaluator_env_overrides(cfg)
    assert cfg.evaluator.composite == "geometric_mean"
    assert cfg.evaluator.axis_mode == "dynamic"  # untouched


# ── export_resolved_config_to_skill_env: cfg -> env bridge for skill subprocesses ──

@contextlib.contextmanager
def _isolated_bridge_env():
    """Snapshot+restore the bridge env vars so the bridge's os.environ.setdefault
    NEVER leaks into other tests (the export writes real env vars; monkeypatch.delenv
    would not undo them)."""
    import os
    _vars = ("ARI_LLM_MODEL", "ARI_BACKEND", "ARI_LLM_API_BASE", "ARI_SLURM_PARTITION")
    saved = {v: os.environ.get(v) for v in _vars}
    for v in _vars:
        os.environ.pop(v, None)
    try:
        yield os
    finally:
        for v, val in saved.items():
            if val is None:
                os.environ.pop(v, None)
            else:
                os.environ[v] = val


def test_export_config_bridges_llm_and_partition():
    from ari.config import ARIConfig, LLMConfig, export_resolved_config_to_skill_env
    with _isolated_bridge_env() as os:
        cfg = ARIConfig(
            llm=LLMConfig(model="gpt-5.2", backend="openai", base_url="http://localhost:8900/v1"),
            resources={"partition": "alpha"},
        )
        export_resolved_config_to_skill_env(cfg)
        assert os.environ["ARI_LLM_MODEL"] == "gpt-5.2"       # idea skill no longer -> ollama
        assert os.environ["ARI_BACKEND"] == "openai"
        assert os.environ["ARI_LLM_API_BASE"] == "http://localhost:8900/v1"
        assert os.environ["ARI_SLURM_PARTITION"] == "alpha"   # hpc skill no longer -> sinfo[0]


def test_export_config_setdefault_respects_explicit_env():
    from ari.config import ARIConfig, LLMConfig, export_resolved_config_to_skill_env
    with _isolated_bridge_env() as os:
        os.environ["ARI_LLM_MODEL"] = "explicit-model"  # user/GUI override present
        cfg = ARIConfig(llm=LLMConfig(model="gpt-5.2", backend="openai"),
                        resources={"partition": "alpha"})
        export_resolved_config_to_skill_env(cfg)
        assert os.environ["ARI_LLM_MODEL"] == "explicit-model"  # explicit wins (setdefault)
        assert os.environ["ARI_SLURM_PARTITION"] == "alpha"     # filled from cfg


def test_export_config_skips_auto_partition():
    from ari.config import ARIConfig, LLMConfig, export_resolved_config_to_skill_env
    with _isolated_bridge_env() as os:
        cfg = ARIConfig(llm=LLMConfig(model="m", backend="openai"),
                        resources={"partition": "auto"})
        export_resolved_config_to_skill_env(cfg)
        assert "ARI_SLURM_PARTITION" not in os.environ   # "auto" => let the skill auto-detect
