"""Tests for the opt-in `bfts.allow_web` toggle.

By default web-skill is gated to the paper/reproduce phases so the BFTS search
loop stays reproducible (P5). The toggle (`ARI_BFTS_ALLOW_WEB` env or
`bfts.allow_web` in workflow.yaml) exposes web-skill during exploration and
records a non-reproducible-trajectory marker. These tests pin both halves.
"""

import tempfile
from pathlib import Path

import yaml

from ari.config import (
    ARIConfig,
    BFTSConfig,
    SkillConfig,
    apply_bfts_env_overrides,
    load_config,
)
from ari.mcp.client import _phase_matches
from ari.orchestrator.web_provenance import read_provenance, write_provenance


def _cfg_with_web(phase=None) -> ARIConfig:
    """ARIConfig carrying a default-gated web-skill plus a bfts-phase skill."""
    return ARIConfig(
        skills=[
            SkillConfig(
                name="web-skill",
                path="/tmp/web",
                phase=phase if phase is not None else ["paper", "reproduce"],
            ),
            SkillConfig(name="idea-skill", path="/tmp/idea", phase="bfts"),
        ]
    )


def _web(cfg: ARIConfig) -> SkillConfig:
    return next(s for s in cfg.skills if s.name == "web-skill")


# ── default: reproducible loop, web-skill excluded from bfts ──────────────────

def test_allow_web_defaults_false():
    assert BFTSConfig().allow_web is False


def test_web_skill_excluded_from_bfts_by_default(monkeypatch):
    monkeypatch.delenv("ARI_BFTS_ALLOW_WEB", raising=False)
    cfg = _cfg_with_web()
    apply_bfts_env_overrides(cfg)
    assert cfg.bfts.allow_web is False
    assert _web(cfg).phase == ["paper", "reproduce"]
    assert _phase_matches(_web(cfg).phase, "bfts") is False
    # ...but the skill is still exposed for the phases it declares.
    assert _phase_matches(_web(cfg).phase, "paper") is True


# ── env toggle ────────────────────────────────────────────────────────────────

def test_env_enables_web_in_bfts(monkeypatch):
    monkeypatch.setenv("ARI_BFTS_ALLOW_WEB", "1")
    cfg = _cfg_with_web()
    apply_bfts_env_overrides(cfg)
    assert cfg.bfts.allow_web is True
    assert "bfts" in _web(cfg).phase
    assert _phase_matches(_web(cfg).phase, "bfts") is True
    # Existing phases preserved.
    assert "paper" in _web(cfg).phase and "reproduce" in _web(cfg).phase


def test_env_falsy_overrides_yaml_on(monkeypatch):
    monkeypatch.setenv("ARI_BFTS_ALLOW_WEB", "0")
    cfg = _cfg_with_web()
    cfg.bfts.allow_web = True  # pretend YAML turned it on
    apply_bfts_env_overrides(cfg)
    assert cfg.bfts.allow_web is False
    assert _web(cfg).phase == ["paper", "reproduce"]


def test_idempotent_no_double_append(monkeypatch):
    monkeypatch.setenv("ARI_BFTS_ALLOW_WEB", "yes")
    cfg = _cfg_with_web()
    apply_bfts_env_overrides(cfg)
    apply_bfts_env_overrides(cfg)
    assert _web(cfg).phase.count("bfts") == 1


def test_phase_all_not_mutated(monkeypatch):
    monkeypatch.setenv("ARI_BFTS_ALLOW_WEB", "true")
    cfg = _cfg_with_web(phase="all")
    apply_bfts_env_overrides(cfg)
    # `all` already matches bfts; no need to append.
    assert _web(cfg).phase == "all"
    assert _phase_matches(_web(cfg).phase, "bfts") is True


# ── YAML toggle via load_config ───────────────────────────────────────────────

def test_yaml_allow_web_via_load_config(monkeypatch):
    monkeypatch.delenv("ARI_BFTS_ALLOW_WEB", raising=False)
    data = {
        "bfts": {"allow_web": True},
        "skills": [
            {"name": "web-skill", "path": "/tmp/web", "phase": ["paper", "reproduce"]},
        ],
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(data, f)
        fpath = f.name
    cfg = load_config(fpath)
    assert cfg.bfts.allow_web is True
    assert "bfts" in _web(cfg).phase


def test_yaml_default_keeps_web_out_of_bfts(monkeypatch):
    monkeypatch.delenv("ARI_BFTS_ALLOW_WEB", raising=False)
    data = {
        "skills": [
            {"name": "web-skill", "path": "/tmp/web", "phase": ["paper", "reproduce"]},
        ],
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(data, f)
        fpath = f.name
    cfg = load_config(fpath)
    assert cfg.bfts.allow_web is False
    assert _phase_matches(_web(cfg).phase, "bfts") is False


# ── provenance marker ─────────────────────────────────────────────────────────

def test_provenance_absent_returns_empty(tmp_path):
    assert read_provenance(tmp_path) == {}


def test_provenance_roundtrip(tmp_path):
    written = write_provenance(tmp_path)
    assert written["web_search_enabled_during_bfts"] is True
    assert written["trajectory_reproducible"] is False
    read_back = read_provenance(tmp_path)
    assert read_back["web_search_enabled_during_bfts"] is True
    assert read_back["trajectory_reproducible"] is False
    assert (Path(tmp_path) / "bfts_web_provenance.json").exists()
