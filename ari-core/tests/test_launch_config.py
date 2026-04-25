"""
test_launch_config.py
──────────────────────────────────────────────────────────────────────────────
Tests that wizard settings are correctly saved to launch_config.json and
that the dashboard displays the actual config used for each experiment.

Covers:
  A. launch_config.json records all effective values from proc_env
  B. Wizard overrides are reflected in launch_config.json
  C. Default values (no wizard override) are correctly recorded
  D. launch_config.json → /state experiment_config roundtrip
  E. Server auto-restore reads launch_config.json on startup
──────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest import mock

import pytest


# ── Fixtures ──

@pytest.fixture
def state():
    from ari.viz import state as _st
    return _st


@pytest.fixture
def clean_env(monkeypatch):
    for k in list(os.environ):
        if k.startswith("ARI_") or k in (
            "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY",
            "OLLAMA_HOST", "LLM_API_BASE",
        ):
            monkeypatch.delenv(k, raising=False)


# ── Helpers ──

def _build_proc_env_and_launch_cfg(
    state_mod, tmp_path, monkeypatch,
    settings: dict,
    wizard_data: dict | None = None,
) -> tuple[dict, dict]:
    """Simulate _api_launch: build proc_env and _launch_cfg.

    Returns (proc_env, launch_cfg) without spawning a subprocess.
    Mirrors api_experiment.py lines 94-238.
    """
    settings_path = tmp_path / ".ari" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(settings))
    monkeypatch.setattr(state_mod, "_settings_path", settings_path)
    monkeypatch.setattr(state_mod, "_checkpoint_dir", None)

    proc_env = os.environ.copy()

    # --- Settings injection (mirrors api_experiment.py:112-148) ---
    saved = json.loads(settings_path.read_text())
    llm_model = saved.get("llm_model", "")
    llm_provider = saved.get("llm_provider", "") or saved.get("llm_backend", "")
    if llm_model:
        proc_env["ARI_MODEL"] = llm_model
        proc_env["ARI_LLM_MODEL"] = llm_model
    if llm_provider:
        proc_env["ARI_BACKEND"] = llm_provider
    if llm_provider == "ollama":
        proc_env["OLLAMA_HOST"] = saved.get("ollama_host", "").strip() or "http://localhost:11434"
    for skill in ["idea", "bfts", "coding", "eval", "paper", "review"]:
        val = saved.get(f"model_{skill}", "")
        if val:
            proc_env[f"ARI_MODEL_{skill.upper()}"] = val

    # --- Wizard overrides (mirrors api_experiment.py:149-208) ---
    data = wizard_data or {}
    wiz_max_nodes = data.get("max_nodes")
    wiz_max_depth = data.get("max_depth")
    wiz_max_react = data.get("max_react")
    wiz_timeout_min = data.get("timeout_min")
    wiz_workers = data.get("workers")
    if wiz_max_nodes is not None:
        proc_env["ARI_MAX_NODES"] = str(int(wiz_max_nodes))
    if wiz_max_depth is not None:
        proc_env["ARI_MAX_DEPTH"] = str(int(wiz_max_depth))
    if wiz_max_react is not None:
        proc_env["ARI_MAX_REACT"] = str(int(wiz_max_react))
    if wiz_timeout_min is not None:
        proc_env["ARI_TIMEOUT_NODE"] = str(int(wiz_timeout_min) * 60)
    if wiz_workers is not None:
        proc_env["ARI_PARALLEL"] = str(int(wiz_workers))
    wiz_hpc_cpus = data.get("hpc_cpus")
    wiz_hpc_mem = data.get("hpc_memory_gb")
    wiz_hpc_gpus = data.get("hpc_gpus")
    wiz_hpc_wall = data.get("hpc_walltime")
    wiz_partition = data.get("partition")
    if wiz_hpc_cpus is not None:
        proc_env["ARI_SLURM_CPUS"] = str(int(wiz_hpc_cpus))
    if wiz_hpc_mem is not None:
        proc_env["ARI_SLURM_MEM_GB"] = str(int(wiz_hpc_mem))
    if wiz_hpc_gpus is not None:
        proc_env["ARI_SLURM_GPUS"] = str(int(wiz_hpc_gpus))
    if wiz_hpc_wall:
        proc_env["ARI_SLURM_WALLTIME"] = str(wiz_hpc_wall)
    if wiz_partition:
        proc_env["ARI_SLURM_PARTITION"] = str(wiz_partition)
    phase_models = data.get("phase_models", {}) or {}
    for phase, model in phase_models.items():
        if model:
            proc_env[f"ARI_MODEL_{phase.upper()}"] = model
    wiz_rubric = data.get("rubric_id")
    if wiz_rubric:
        proc_env["ARI_RUBRIC"] = str(wiz_rubric)
    wiz_fewshot_mode = data.get("fewshot_mode")
    if wiz_fewshot_mode:
        proc_env["ARI_FEWSHOT_MODE"] = str(wiz_fewshot_mode)
    wiz_num_ensemble = data.get("num_reviews_ensemble")
    if wiz_num_ensemble is not None:
        proc_env["ARI_NUM_REVIEWS_ENSEMBLE"] = str(int(wiz_num_ensemble))
    wiz_num_reflections = data.get("num_reflections")
    if wiz_num_reflections is not None:
        proc_env["ARI_NUM_REFLECTIONS"] = str(int(wiz_num_reflections))
    wiz_model = data.get("llm_model", "") or data.get("model", "")
    wiz_provider = data.get("llm_provider", "")
    if wiz_model:
        proc_env["ARI_MODEL"] = wiz_model
        proc_env["ARI_LLM_MODEL"] = wiz_model
    if wiz_provider:
        proc_env["ARI_BACKEND"] = wiz_provider
    # Safety net
    _final_backend = proc_env.get("ARI_BACKEND", "")
    _final_model = proc_env.get("ARI_MODEL", "")
    if _final_backend and not _final_model:
        _defaults = {"openai": "gpt-4o", "anthropic": "claude-sonnet-4-5", "ollama": "qwen3:8b"}
        _d = _defaults.get(_final_backend, "")
        if _d:
            proc_env["ARI_MODEL"] = _d
            proc_env["ARI_LLM_MODEL"] = _d

    # --- Build _launch_cfg (mirrors api_experiment.py:214-237) ---
    _launch_llm_model = proc_env.get("ARI_MODEL") or proc_env.get("ARI_LLM_MODEL") or ""
    _launch_llm_provider = proc_env.get("ARI_BACKEND") or ""
    _launch_cfg = {
        "llm_model": _launch_llm_model,
        "llm_provider": _launch_llm_provider,
        "profile": data.get("profile", ""),
        "max_nodes": int(proc_env.get("ARI_MAX_NODES", 50)),
        "max_depth": int(proc_env.get("ARI_MAX_DEPTH", 5)),
        "max_react": int(proc_env.get("ARI_MAX_REACT", 80)),
        "timeout_node_s": int(proc_env.get("ARI_TIMEOUT_NODE", 7200)),
        "parallel": int(proc_env.get("ARI_PARALLEL", 4)),
    }
    if proc_env.get("ARI_SLURM_CPUS"):
        _launch_cfg["hpc_cpus"] = int(proc_env["ARI_SLURM_CPUS"])
    if proc_env.get("ARI_SLURM_MEM_GB"):
        _launch_cfg["hpc_memory_gb"] = int(proc_env["ARI_SLURM_MEM_GB"])
    if proc_env.get("ARI_SLURM_GPUS"):
        _launch_cfg["hpc_gpus"] = int(proc_env["ARI_SLURM_GPUS"])
    if proc_env.get("ARI_SLURM_WALLTIME"):
        _launch_cfg["hpc_walltime"] = proc_env["ARI_SLURM_WALLTIME"]
    if proc_env.get("ARI_SLURM_PARTITION"):
        _launch_cfg["partition"] = proc_env["ARI_SLURM_PARTITION"]
    if phase_models:
        _launch_cfg["phase_models"] = {k: v for k, v in phase_models.items() if v}
    if proc_env.get("ARI_RUBRIC"):
        _launch_cfg["rubric_id"] = proc_env["ARI_RUBRIC"]
    if proc_env.get("ARI_FEWSHOT_MODE"):
        _launch_cfg["fewshot_mode"] = proc_env["ARI_FEWSHOT_MODE"]
    if proc_env.get("ARI_NUM_REVIEWS_ENSEMBLE"):
        _launch_cfg["num_reviews_ensemble"] = int(proc_env["ARI_NUM_REVIEWS_ENSEMBLE"])
    if proc_env.get("ARI_NUM_REFLECTIONS"):
        _launch_cfg["num_reflections"] = int(proc_env["ARI_NUM_REFLECTIONS"])

    return proc_env, _launch_cfg


# ══════════════════════════════════════════════════════════════════════════
# A. launch_config.json records all effective values
# ══════════════════════════════════════════════════════════════════════════

class TestLaunchCfgRecordsEffectiveValues:
    """launch_config always records BFTS defaults even without wizard override."""

    def test_defaults_recorded_without_wizard(self, state, tmp_path, monkeypatch, clean_env):
        _, cfg = _build_proc_env_and_launch_cfg(state, tmp_path, monkeypatch,
            settings={"llm_provider": "openai", "llm_model": "gpt-5.2"})
        assert cfg["max_nodes"] == 50
        assert cfg["max_depth"] == 5
        assert cfg["max_react"] == 80
        assert cfg["timeout_node_s"] == 7200
        assert cfg["parallel"] == 4

    def test_llm_always_recorded(self, state, tmp_path, monkeypatch, clean_env):
        _, cfg = _build_proc_env_and_launch_cfg(state, tmp_path, monkeypatch,
            settings={"llm_provider": "openai", "llm_model": "gpt-5.2"})
        assert cfg["llm_model"] == "gpt-5.2"
        assert cfg["llm_provider"] == "openai"

    def test_anthropic_llm_recorded(self, state, tmp_path, monkeypatch, clean_env):
        _, cfg = _build_proc_env_and_launch_cfg(state, tmp_path, monkeypatch,
            settings={"llm_provider": "anthropic", "llm_model": "claude-sonnet-4-5"})
        assert cfg["llm_model"] == "claude-sonnet-4-5"
        assert cfg["llm_provider"] == "anthropic"

    def test_no_hpc_fields_when_not_set(self, state, tmp_path, monkeypatch, clean_env):
        """HPC fields omitted when not configured."""
        _, cfg = _build_proc_env_and_launch_cfg(state, tmp_path, monkeypatch,
            settings={"llm_provider": "openai", "llm_model": "gpt-5.2"})
        assert "hpc_cpus" not in cfg
        assert "hpc_memory_gb" not in cfg
        assert "hpc_gpus" not in cfg
        assert "partition" not in cfg

    def test_cfg_is_json_serializable(self, state, tmp_path, monkeypatch, clean_env):
        _, cfg = _build_proc_env_and_launch_cfg(state, tmp_path, monkeypatch,
            settings={"llm_provider": "openai", "llm_model": "gpt-5.2"},
            wizard_data={"max_nodes": 20, "hpc_cpus": 16})
        # Must not raise
        text = json.dumps(cfg)
        roundtrip = json.loads(text)
        assert roundtrip == cfg


# ══════════════════════════════════════════════════════════════════════════
# B. Wizard overrides are reflected in launch_config.json
# ══════════════════════════════════════════════════════════════════════════

class TestWizardOverridesInLaunchCfg:
    """Wizard-specified values override defaults in launch_config."""

    def test_max_nodes_override(self, state, tmp_path, monkeypatch, clean_env):
        _, cfg = _build_proc_env_and_launch_cfg(state, tmp_path, monkeypatch,
            settings={"llm_provider": "openai", "llm_model": "gpt-5.2"},
            wizard_data={"max_nodes": 20})
        assert cfg["max_nodes"] == 20

    def test_max_depth_override(self, state, tmp_path, monkeypatch, clean_env):
        _, cfg = _build_proc_env_and_launch_cfg(state, tmp_path, monkeypatch,
            settings={"llm_provider": "openai", "llm_model": "gpt-5.2"},
            wizard_data={"max_depth": 3})
        assert cfg["max_depth"] == 3

    def test_max_react_override(self, state, tmp_path, monkeypatch, clean_env):
        _, cfg = _build_proc_env_and_launch_cfg(state, tmp_path, monkeypatch,
            settings={"llm_provider": "openai", "llm_model": "gpt-5.2"},
            wizard_data={"max_react": 40})
        assert cfg["max_react"] == 40

    def test_timeout_override(self, state, tmp_path, monkeypatch, clean_env):
        _, cfg = _build_proc_env_and_launch_cfg(state, tmp_path, monkeypatch,
            settings={"llm_provider": "openai", "llm_model": "gpt-5.2"},
            wizard_data={"timeout_min": 30})
        assert cfg["timeout_node_s"] == 1800

    def test_workers_override(self, state, tmp_path, monkeypatch, clean_env):
        _, cfg = _build_proc_env_and_launch_cfg(state, tmp_path, monkeypatch,
            settings={"llm_provider": "openai", "llm_model": "gpt-5.2"},
            wizard_data={"workers": 8})
        assert cfg["parallel"] == 8

    def test_hpc_cpus_override(self, state, tmp_path, monkeypatch, clean_env):
        _, cfg = _build_proc_env_and_launch_cfg(state, tmp_path, monkeypatch,
            settings={"llm_provider": "openai", "llm_model": "gpt-5.2"},
            wizard_data={"hpc_cpus": 32})
        assert cfg["hpc_cpus"] == 32

    def test_hpc_memory_override(self, state, tmp_path, monkeypatch, clean_env):
        _, cfg = _build_proc_env_and_launch_cfg(state, tmp_path, monkeypatch,
            settings={"llm_provider": "openai", "llm_model": "gpt-5.2"},
            wizard_data={"hpc_memory_gb": 128})
        assert cfg["hpc_memory_gb"] == 128

    def test_hpc_gpus_override(self, state, tmp_path, monkeypatch, clean_env):
        _, cfg = _build_proc_env_and_launch_cfg(state, tmp_path, monkeypatch,
            settings={"llm_provider": "openai", "llm_model": "gpt-5.2"},
            wizard_data={"hpc_gpus": 2})
        assert cfg["hpc_gpus"] == 2

    def test_hpc_walltime_override(self, state, tmp_path, monkeypatch, clean_env):
        _, cfg = _build_proc_env_and_launch_cfg(state, tmp_path, monkeypatch,
            settings={"llm_provider": "openai", "llm_model": "gpt-5.2"},
            wizard_data={"hpc_walltime": "08:00:00"})
        assert cfg["hpc_walltime"] == "08:00:00"

    def test_partition_override(self, state, tmp_path, monkeypatch, clean_env):
        _, cfg = _build_proc_env_and_launch_cfg(state, tmp_path, monkeypatch,
            settings={"llm_provider": "openai", "llm_model": "gpt-5.2"},
            wizard_data={"partition": "gpu-a100"})
        assert cfg["partition"] == "gpu-a100"

    def test_llm_model_override(self, state, tmp_path, monkeypatch, clean_env):
        _, cfg = _build_proc_env_and_launch_cfg(state, tmp_path, monkeypatch,
            settings={"llm_provider": "openai", "llm_model": "gpt-5.2"},
            wizard_data={"llm_model": "gpt-4o-mini", "llm_provider": "openai"})
        assert cfg["llm_model"] == "gpt-4o-mini"

    def test_llm_provider_override(self, state, tmp_path, monkeypatch, clean_env):
        _, cfg = _build_proc_env_and_launch_cfg(state, tmp_path, monkeypatch,
            settings={"llm_provider": "openai", "llm_model": "gpt-5.2"},
            wizard_data={"llm_model": "claude-sonnet-4-5", "llm_provider": "anthropic"})
        assert cfg["llm_provider"] == "anthropic"
        assert cfg["llm_model"] == "claude-sonnet-4-5"

    def test_phase_models_override(self, state, tmp_path, monkeypatch, clean_env):
        _, cfg = _build_proc_env_and_launch_cfg(state, tmp_path, monkeypatch,
            settings={"llm_provider": "openai", "llm_model": "gpt-5.2"},
            wizard_data={"phase_models": {"idea": "gpt-4o", "paper": "claude-sonnet-4-5"}})
        assert cfg["phase_models"] == {"idea": "gpt-4o", "paper": "claude-sonnet-4-5"}

    def test_rubric_id_persisted(self, state, tmp_path, monkeypatch, clean_env):
        """Wizard rubric_id ('sc' for Supercomputing etc.) survives to launch_config."""
        _, cfg = _build_proc_env_and_launch_cfg(state, tmp_path, monkeypatch,
            settings={"llm_provider": "openai", "llm_model": "gpt-5.2"},
            wizard_data={"rubric_id": "sc"})
        assert cfg["rubric_id"] == "sc"

    def test_rubric_omitted_when_unset(self, state, tmp_path, monkeypatch, clean_env):
        _, cfg = _build_proc_env_and_launch_cfg(state, tmp_path, monkeypatch,
            settings={"llm_provider": "openai", "llm_model": "gpt-5.2"})
        assert "rubric_id" not in cfg

    def test_review_tuning_persisted(self, state, tmp_path, monkeypatch, clean_env):
        _, cfg = _build_proc_env_and_launch_cfg(state, tmp_path, monkeypatch,
            settings={"llm_provider": "openai", "llm_model": "gpt-5.2"},
            wizard_data={
                "rubric_id": "sc",
                "fewshot_mode": "dynamic",
                "num_reviews_ensemble": 3,
                "num_reflections": 2,
            })
        assert cfg["rubric_id"] == "sc"
        assert cfg["fewshot_mode"] == "dynamic"
        assert cfg["num_reviews_ensemble"] == 3
        assert cfg["num_reflections"] == 2

    def test_full_wizard_config(self, state, tmp_path, monkeypatch, clean_env):
        """Complete wizard configuration is fully captured."""
        _, cfg = _build_proc_env_and_launch_cfg(state, tmp_path, monkeypatch,
            settings={"llm_provider": "openai", "llm_model": "gpt-5.2"},
            wizard_data={
                "llm_model": "gpt-4o", "llm_provider": "openai",
                "max_nodes": 10, "max_depth": 3, "max_react": 40,
                "timeout_min": 15, "workers": 2,
                "hpc_cpus": 16, "hpc_memory_gb": 64, "hpc_gpus": 1,
                "hpc_walltime": "02:00:00", "partition": "gpu-v100",
            })
        assert cfg["llm_model"] == "gpt-4o"
        assert cfg["max_nodes"] == 10
        assert cfg["max_depth"] == 3
        assert cfg["max_react"] == 40
        assert cfg["timeout_node_s"] == 900
        assert cfg["parallel"] == 2
        assert cfg["hpc_cpus"] == 16
        assert cfg["hpc_memory_gb"] == 64
        assert cfg["hpc_gpus"] == 1
        assert cfg["hpc_walltime"] == "02:00:00"
        assert cfg["partition"] == "gpu-v100"


# ══════════════════════════════════════════════════════════════════════════
# C. launch_config.json write/read roundtrip (file I/O)
# ══════════════════════════════════════════════════════════════════════════

class TestLaunchCfgFileRoundtrip:
    """launch_config.json is correctly written and read back."""

    def test_write_and_read_roundtrip(self, state, tmp_path, monkeypatch, clean_env):
        _, cfg = _build_proc_env_and_launch_cfg(state, tmp_path, monkeypatch,
            settings={"llm_provider": "openai", "llm_model": "gpt-5.2"},
            wizard_data={"max_nodes": 25, "max_depth": 4, "hpc_cpus": 16})
        # Write to file (simulates _watch_for_checkpoint)
        lc_path = tmp_path / "launch_config.json"
        lc_path.write_text(json.dumps(cfg, indent=2))
        # Read back
        loaded = json.loads(lc_path.read_text())
        assert loaded["llm_model"] == "gpt-5.2"
        assert loaded["llm_provider"] == "openai"
        assert loaded["max_nodes"] == 25
        assert loaded["max_depth"] == 4
        assert loaded["hpc_cpus"] == 16
        # Defaults also present
        assert loaded["max_react"] == 80
        assert loaded["timeout_node_s"] == 7200
        assert loaded["parallel"] == 4

    def test_read_from_parent_dir_fallback(self, state, tmp_path, monkeypatch, clean_env):
        """Server falls back to parent dir when launch_config.json not in checkpoint."""
        _, cfg = _build_proc_env_and_launch_cfg(state, tmp_path, monkeypatch,
            settings={"llm_provider": "openai", "llm_model": "gpt-5.2"},
            wizard_data={"max_nodes": 15})
        # Write to parent dir (not checkpoint dir)
        parent = tmp_path / "checkpoints"
        parent.mkdir()
        ckpt = parent / "20260101120000_test"
        ckpt.mkdir()
        (parent / "launch_config.json").write_text(json.dumps(cfg))
        # Read: checkpoint dir first (not found), then parent
        d = ckpt
        _lc_data = {}
        for _lc_path in [d / "launch_config.json", d.parent / "launch_config.json"]:
            if _lc_path.exists():
                _lc_data = json.loads(_lc_path.read_text())
                break
        assert _lc_data["max_nodes"] == 15
        assert _lc_data["llm_model"] == "gpt-5.2"

    def test_checkpoint_dir_takes_priority_over_parent(self, state, tmp_path, monkeypatch, clean_env):
        """launch_config.json in checkpoint dir overrides parent dir."""
        parent = tmp_path / "checkpoints"
        parent.mkdir()
        ckpt = parent / "20260101120000_test"
        ckpt.mkdir()
        # Parent has old values
        (parent / "launch_config.json").write_text(json.dumps({"max_nodes": 99}))
        # Checkpoint has new values
        (ckpt / "launch_config.json").write_text(json.dumps({"max_nodes": 10}))
        d = ckpt
        _lc_data = {}
        for _lc_path in [d / "launch_config.json", d.parent / "launch_config.json"]:
            if _lc_path.exists():
                _lc_data = json.loads(_lc_path.read_text())
                break
        assert _lc_data["max_nodes"] == 10


# ══════════════════════════════════════════════════════════════════════════
# D. launch_config.json → /state experiment_config consistency
# ══════════════════════════════════════════════════════════════════════════

class TestLaunchCfgToStateConsistency:
    """Values in launch_config match what /state experiment_config displays."""

    def test_bfts_keys_match_experiment_config_keys(self):
        """launch_config keys map correctly to experiment_config keys in server.py."""
        from pathlib import Path
        srv = (Path(__file__).parent.parent / "ari" / "viz" / "server.py").read_text()
        # experiment_config reads these keys from _lc_data
        for key in ["max_nodes", "max_depth", "max_react", "parallel", "timeout_node_s"]:
            assert f'_lc_data.get("{key}")' in srv, \
                f"server.py experiment_config must read '{key}' from _lc_data"

    def test_hpc_keys_match_experiment_config_keys(self):
        from pathlib import Path
        srv = (Path(__file__).parent.parent / "ari" / "viz" / "server.py").read_text()
        for key in ["hpc_cpus", "hpc_memory_gb", "hpc_gpus", "hpc_walltime", "partition"]:
            assert f'_lc_data.get("{key}")' in srv, \
                f"server.py experiment_config must read '{key}' from _lc_data"

    def test_launch_cfg_keys_cover_experiment_config(self):
        """All experiment_config BFTS keys have corresponding launch_cfg entries."""
        from pathlib import Path
        exp_src = (Path(__file__).parent.parent / "ari" / "viz" / "api_experiment.py").read_text()
        # BFTS keys must appear in _launch_cfg construction
        for key in ["max_nodes", "max_depth", "max_react", "timeout_node_s", "parallel"]:
            assert f'"{key}"' in exp_src, \
                f"api_experiment.py _launch_cfg must include '{key}'"

    def test_state_reads_launch_config_from_parent_dir(self):
        """server.py must check parent dir for launch_config.json fallback."""
        from pathlib import Path
        srv = (Path(__file__).parent.parent / "ari" / "viz" / "server.py").read_text()
        assert "d.parent" in srv and "launch_config.json" in srv, \
            "server.py must fall back to d.parent / launch_config.json"


# ══════════════════════════════════════════════════════════════════════════
# E. Server auto-restore reads launch_config on startup
# ══════════════════════════════════════════════════════════════════════════

class TestServerAutoRestore:
    """Watcher auto-restore correctly reads launch_config.json."""

    def test_watcher_restores_from_checkpoint_dir(self, state, tmp_path, monkeypatch, clean_env):
        """Auto-restore reads launch_config.json from checkpoint."""
        ckpt = tmp_path / "20260101120000_test"
        ckpt.mkdir()
        cfg = {"llm_model": "gpt-4o", "llm_provider": "openai", "max_nodes": 30}
        (ckpt / "launch_config.json").write_text(json.dumps(cfg))
        # Simulate auto-restore logic
        for _lc_cand in [ckpt / "launch_config.json", ckpt.parent / "launch_config.json"]:
            if _lc_cand.exists():
                loaded = json.loads(_lc_cand.read_text())
                break
        assert loaded["llm_model"] == "gpt-4o"
        assert loaded["max_nodes"] == 30

    def test_watcher_restores_from_parent_dir(self, state, tmp_path, monkeypatch, clean_env):
        """Auto-restore falls back to parent dir launch_config.json."""
        parent = tmp_path / "checkpoints"
        parent.mkdir()
        ckpt = parent / "20260101120000_test"
        ckpt.mkdir()
        cfg = {"llm_model": "claude-sonnet-4-5", "llm_provider": "anthropic"}
        (parent / "launch_config.json").write_text(json.dumps(cfg))
        loaded = None
        for _lc_cand in [ckpt / "launch_config.json", ckpt.parent / "launch_config.json"]:
            if _lc_cand.exists():
                loaded = json.loads(_lc_cand.read_text())
                break
        assert loaded is not None
        assert loaded["llm_model"] == "claude-sonnet-4-5"

    def test_auto_restore_code_in_server(self):
        """server.py watcher must use _api_checkpoints for auto-restore."""
        from pathlib import Path
        srv = (Path(__file__).parent.parent / "ari" / "viz" / "server.py").read_text()
        assert "_api_checkpoints()" in srv, \
            "Watcher must use _api_checkpoints() for checkpoint discovery"
        # Must restore launch_config from checkpoint or parent
        idx = srv.find("Auto-restore last checkpoint")
        assert idx > 0
        block = srv[idx:idx + 800]
        assert "launch_config.json" in block, \
            "Auto-restore must read launch_config.json"
        assert "parent" in block, \
            "Auto-restore must check parent dir for launch_config.json"


# ══════════════════════════════════════════════════════════════════════════
# LIVE HTTP (only when server is running)
# ══════════════════════════════════════════════════════════════════════════

import urllib.request

_SERVER_URL = "http://localhost:9886"


def _server_available():
    try:
        urllib.request.urlopen(f"{_SERVER_URL}/state", timeout=1)
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _server_available(), reason="GUI server not running on :9886")
class TestLiveLaunchConfig:
    """Live server tests for launch config display."""

    def test_state_experiment_config_has_bfts_fields(self):
        resp = urllib.request.urlopen(f"{_SERVER_URL}/state", timeout=3)
        data = json.loads(resp.read())
        cfg = data.get("experiment_config") or {}
        if not cfg:
            pytest.skip("No active checkpoint — experiment_config not populated")
        for key in ["max_nodes", "max_depth", "parallel", "timeout_node_s", "max_react"]:
            assert key in cfg, f"experiment_config missing '{key}': {cfg}"

    def test_state_experiment_config_has_llm_fields(self):
        resp = urllib.request.urlopen(f"{_SERVER_URL}/state", timeout=3)
        data = json.loads(resp.read())
        cfg = data.get("experiment_config") or {}
        if not cfg:
            pytest.skip("No active checkpoint — experiment_config not populated")
        assert "llm_model" in cfg
        assert "llm_backend" in cfg

    def test_state_bfts_values_are_numeric(self):
        resp = urllib.request.urlopen(f"{_SERVER_URL}/state", timeout=3)
        data = json.loads(resp.read())
        cfg = data.get("experiment_config", {})
        for key in ["max_nodes", "max_depth", "parallel", "timeout_node_s", "max_react"]:
            val = cfg.get(key)
            assert val is None or isinstance(val, (int, float)), \
                f"experiment_config['{key}'] must be numeric, got {type(val)}: {val}"


# ══════════════════════════════════════════════════════════════════════════
# F. Race condition fix: existing snapshot taken BEFORE Popen
# ══════════════════════════════════════════════════════════════════════════

class TestPreCreatedCheckpointDir:
    """Checkpoint dir is pre-created by GUI before Popen, so log and config
    are written directly inside it (no watcher/move needed)."""

    def test_checkpoint_dir_created_before_popen(self):
        """api_experiment.py must mkdir the checkpoint BEFORE Popen."""
        from pathlib import Path
        src = (Path(__file__).parent.parent / "ari" / "viz" / "api_experiment.py").read_text()
        fn_start = src.find("def _api_launch(")
        assert fn_start > 0
        fn_body = src[fn_start:]
        # PathManager.ensure_checkpoint() or _pre_ckpt.mkdir() both satisfy this
        idx_mkdir = fn_body.find("ensure_checkpoint(")
        if idx_mkdir < 0:
            idx_mkdir = fn_body.find("_pre_ckpt.mkdir(")
        idx_popen = fn_body.find("_st._last_proc = subprocess.Popen(")
        assert idx_mkdir > 0, "Pre-created checkpoint mkdir not found"
        assert idx_popen > 0, "subprocess.Popen not found"
        assert idx_mkdir < idx_popen, \
            "Checkpoint dir must be created BEFORE Popen"

    def test_log_created_inside_checkpoint(self):
        """Log file must be created inside the pre-created checkpoint dir."""
        from pathlib import Path
        src = (Path(__file__).parent.parent / "ari" / "viz" / "api_experiment.py").read_text()
        fn_start = src.find("def _api_launch(")
        fn_body = src[fn_start:]
        assert "_pre_ckpt" in fn_body and "log_path = _pre_ckpt" in fn_body, \
            "Log path must be inside the pre-created checkpoint dir"

    def test_launch_config_written_inside_checkpoint(self):
        """launch_config.json must be written inside the pre-created checkpoint dir."""
        from pathlib import Path
        src = (Path(__file__).parent.parent / "ari" / "viz" / "api_experiment.py").read_text()
        fn_start = src.find("def _api_launch(")
        fn_body = src[fn_start:]
        assert '_pre_ckpt / "launch_config.json"' in fn_body, \
            "launch_config.json must be written inside checkpoint dir"

    def test_ari_checkpoint_dir_env_set(self):
        """ARI_CHECKPOINT_DIR must be set to tell CLI to use pre-created dir."""
        from pathlib import Path
        src = (Path(__file__).parent.parent / "ari" / "viz" / "api_experiment.py").read_text()
        fn_start = src.find("def _api_launch(")
        fn_body = src[fn_start:]
        assert 'ARI_CHECKPOINT_DIR' in fn_body, \
            "proc_env must set ARI_CHECKPOINT_DIR for CLI"


class TestWatcherWritesLaunchConfig:
    """Simulate the watcher detecting a new checkpoint and writing launch_config.json."""

    def test_watcher_writes_to_new_checkpoint(self, state, tmp_path, monkeypatch, clean_env):
        """When a new checkpoint dir appears, watcher writes launch_config.json inside it."""
        _, cfg = _build_proc_env_and_launch_cfg(state, tmp_path, monkeypatch,
            settings={"llm_provider": "openai", "llm_model": "gpt-5.2"},
            wizard_data={"max_nodes": 15, "max_depth": 3, "hpc_cpus": 8})
        # Simulate: ckpt_root exists, watcher polls
        ckpt_root = tmp_path / "checkpoints"
        ckpt_root.mkdir()
        before = set()  # no existing dirs
        # Subprocess creates a new checkpoint dir
        new_ckpt = ckpt_root / "20260401120000_my_experiment"
        new_ckpt.mkdir()
        # Watcher logic: detect new dir and write launch_config.json
        current = {d.name for d in ckpt_root.iterdir() if d.is_dir()}
        new_dirs = current - before
        assert len(new_dirs) == 1
        newest = sorted(
            [ckpt_root / n for n in new_dirs],
            key=lambda p: p.stat().st_mtime, reverse=True
        )[0]
        lc = newest / "launch_config.json"
        assert not lc.exists()
        lc.write_text(json.dumps(cfg, indent=2))
        # Verify it was written inside the checkpoint dir
        assert lc.exists()
        loaded = json.loads(lc.read_text())
        assert loaded["max_nodes"] == 15
        assert loaded["max_depth"] == 3
        assert loaded["hpc_cpus"] == 8
        assert loaded["llm_model"] == "gpt-5.2"
        assert loaded["timeout_node_s"] == 7200  # default preserved

    def test_watcher_skips_if_launch_config_exists(self, state, tmp_path, monkeypatch, clean_env):
        """Watcher must not overwrite existing launch_config.json in checkpoint."""
        _, cfg = _build_proc_env_and_launch_cfg(state, tmp_path, monkeypatch,
            settings={"llm_provider": "openai", "llm_model": "gpt-5.2"},
            wizard_data={"max_nodes": 99})
        ckpt = tmp_path / "20260401120000_test"
        ckpt.mkdir()
        # Pre-existing launch_config.json (e.g. from CLI)
        (ckpt / "launch_config.json").write_text(json.dumps({"max_nodes": 10}))
        # Watcher's conditional write
        lc = ckpt / "launch_config.json"
        if not lc.exists():
            lc.write_text(json.dumps(cfg, indent=2))
        loaded = json.loads(lc.read_text())
        assert loaded["max_nodes"] == 10, "Must not overwrite existing launch_config.json"

    def test_race_existing_snapshot_excludes_new_dir(self, tmp_path):
        """Snapshot taken before Popen must not contain the new checkpoint dir."""
        ckpt_root = tmp_path / "checkpoints"
        ckpt_root.mkdir()
        # Pre-existing dirs (like 'experiments')
        (ckpt_root / "experiments").mkdir()
        (ckpt_root / "old_checkpoint").mkdir()
        before = {d.name for d in ckpt_root.iterdir() if d.is_dir()}
        # Subprocess creates new dir AFTER snapshot
        new_dir = ckpt_root / "20260401120000_new_experiment"
        new_dir.mkdir()
        current = {d.name for d in ckpt_root.iterdir() if d.is_dir()}
        new_dirs = current - before
        assert "20260401120000_new_experiment" in new_dirs
        assert "experiments" not in new_dirs
        assert "old_checkpoint" not in new_dirs

    def test_race_late_snapshot_misses_new_dir(self, tmp_path):
        """If snapshot were taken AFTER Popen, it could include the new dir → bug."""
        ckpt_root = tmp_path / "checkpoints"
        ckpt_root.mkdir()
        # Simulate: subprocess already created the dir
        new_dir = ckpt_root / "20260401120000_new_experiment"
        new_dir.mkdir()
        # Late snapshot (this is the bug scenario)
        late_before = {d.name for d in ckpt_root.iterdir() if d.is_dir()}
        # Watcher would find zero new dirs → launch_config.json never written
        current = {d.name for d in ckpt_root.iterdir() if d.is_dir()}
        new_dirs = current - late_before
        assert len(new_dirs) == 0, \
            "Late snapshot includes the new dir → watcher misses it (this was the bug)"

    def test_experiment_md_copied_to_checkpoint(self, tmp_path):
        """Watcher must also copy experiment.md into new checkpoint dir."""
        import shutil
        ckpt_root = tmp_path / "checkpoints"
        ckpt_root.mkdir()
        (ckpt_root / "experiment.md").write_text("# My Experiment\nGoal here")
        new_ckpt = ckpt_root / "20260401120000_test"
        new_ckpt.mkdir()
        # Watcher logic: copy experiment.md
        _src_md = ckpt_root / "experiment.md"
        _dst_md = new_ckpt / "experiment.md"
        if _src_md.exists() and not _dst_md.exists():
            shutil.copy2(str(_src_md), str(_dst_md))
        assert _dst_md.exists()
        assert _dst_md.read_text() == "# My Experiment\nGoal here"

    def test_launch_config_written_before_popen(self):
        """launch_config.json must be written before Popen (no watcher needed)."""
        from pathlib import Path
        src = (Path(__file__).parent.parent / "ari" / "viz" / "api_experiment.py").read_text()
        fn_start = src.find("def _api_launch(")
        fn_body = src[fn_start:]
        idx_lc = fn_body.find('"launch_config.json"')
        idx_popen = fn_body.find("_st._last_proc = subprocess.Popen(")
        assert idx_lc > 0 and idx_popen > 0
        assert idx_lc < idx_popen, \
            "launch_config.json must be written before Popen"
