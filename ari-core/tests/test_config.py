"""Tests for ari-core configuration loading."""

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
