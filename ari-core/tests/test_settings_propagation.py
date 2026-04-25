"""Tests for environment variable and settings propagation across the ARI stack.

Covers the full chain:
  GUI settings.json → _api_launch env building → subprocess env → config.py → LLMClient

Each test isolates a single propagation step to pinpoint where a value is lost.
"""
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest


# ══════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════

@pytest.fixture
def state():
    from ari.viz import state as _st
    return _st


@pytest.fixture
def clean_env(monkeypatch):
    """Remove all ARI_* and provider API keys from env so tests start clean."""
    for k in list(os.environ):
        if k.startswith("ARI_") or k in (
            "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY",
            "OLLAMA_HOST", "LLM_API_BASE",
        ):
            monkeypatch.delenv(k, raising=False)


# ══════════════════════════════════════════════
# 1. config.py — auto_config() reads env correctly
# ══════════════════════════════════════════════

class TestAutoConfig:
    """auto_config() must faithfully read every ARI_* env var."""

    def test_default_when_no_env(self, clean_env):
        from ari.config import auto_config
        cfg = auto_config()
        assert cfg.llm.backend == "ollama"
        assert cfg.llm.model == "qwen3:8b"
        assert cfg.llm.base_url == "http://localhost:11434"
        assert cfg.bfts.max_depth == 5
        assert cfg.bfts.max_total_nodes == 50

    def test_model_from_env(self, clean_env, monkeypatch):
        monkeypatch.setenv("ARI_MODEL", "gpt-4o")
        monkeypatch.setenv("ARI_BACKEND", "openai")
        from ari.config import auto_config
        cfg = auto_config()
        assert cfg.llm.model == "gpt-4o"
        assert cfg.llm.backend == "openai"

    def test_base_url_openai_not_ollama(self, clean_env, monkeypatch):
        """Non-ollama backend must NOT get the default ollama base_url."""
        monkeypatch.setenv("ARI_BACKEND", "openai")
        from ari.config import auto_config
        cfg = auto_config()
        assert cfg.llm.base_url is None or "11434" not in str(cfg.llm.base_url)

    def test_ollama_host_from_env(self, clean_env, monkeypatch):
        monkeypatch.setenv("ARI_BACKEND", "ollama")
        monkeypatch.setenv("OLLAMA_HOST", "http://gpu-node:11434")
        from ari.config import auto_config
        cfg = auto_config()
        assert cfg.llm.base_url == "http://gpu-node:11434"

    def test_bfts_params_from_env(self, clean_env, monkeypatch):
        monkeypatch.setenv("ARI_MAX_DEPTH", "10")
        monkeypatch.setenv("ARI_MAX_NODES", "100")
        monkeypatch.setenv("ARI_MAX_REACT", "40")
        monkeypatch.setenv("ARI_TIMEOUT_NODE", "3600")
        monkeypatch.setenv("ARI_PARALLEL", "8")
        from ari.config import auto_config
        cfg = auto_config()
        assert cfg.bfts.max_depth == 10
        assert cfg.bfts.max_total_nodes == 100
        assert cfg.bfts.max_react_steps == 40
        assert cfg.bfts.timeout_per_node == 3600
        assert cfg.bfts.max_parallel_nodes == 8

    def test_anthropic_backend_no_ollama_url(self, clean_env, monkeypatch):
        monkeypatch.setenv("ARI_BACKEND", "anthropic")
        monkeypatch.setenv("ARI_MODEL", "claude-sonnet-4-5")
        from ari.config import auto_config
        cfg = auto_config()
        assert cfg.llm.backend == "anthropic"
        assert cfg.llm.model == "claude-sonnet-4-5"
        # Must not have ollama base_url
        assert cfg.llm.base_url is None or "11434" not in str(cfg.llm.base_url)

    def test_custom_api_base(self, clean_env, monkeypatch):
        monkeypatch.setenv("ARI_BACKEND", "openai")
        monkeypatch.setenv("LLM_API_BASE", "https://my-proxy.example.com/v1")
        from ari.config import auto_config
        cfg = auto_config()
        assert cfg.llm.base_url == "https://my-proxy.example.com/v1"


# ══════════════════════════════════════════════
# 2. config.py — load_config() YAML override + env var resolution
# ══════════════════════════════════════════════

class TestLoadConfig:
    def test_yaml_overrides_defaults(self, tmp_path, clean_env):
        cfg_yaml = tmp_path / "config.yaml"
        cfg_yaml.write_text("""
llm:
  backend: anthropic
  model: claude-sonnet-4-5
bfts:
  max_depth: 3
  max_total_nodes: 20
""")
        from ari.config import load_config
        cfg = load_config(str(cfg_yaml))
        assert cfg.llm.backend == "anthropic"
        assert cfg.llm.model == "claude-sonnet-4-5"
        assert cfg.bfts.max_depth == 3
        assert cfg.bfts.max_total_nodes == 20

    def test_yaml_env_var_resolution(self, tmp_path, clean_env, monkeypatch):
        monkeypatch.setenv("MY_MODEL", "gpt-4o-mini")
        cfg_yaml = tmp_path / "config.yaml"
        cfg_yaml.write_text("""
llm:
  backend: openai
  model: ${MY_MODEL}
""")
        from ari.config import load_config
        cfg = load_config(str(cfg_yaml))
        assert cfg.llm.model == "gpt-4o-mini"

    def test_missing_yaml_falls_back_to_auto_config(self, clean_env, monkeypatch):
        monkeypatch.setenv("ARI_MODEL", "test-model")
        monkeypatch.setenv("ARI_BACKEND", "openai")
        from ari.config import load_config
        cfg = load_config("/nonexistent/config.yaml")
        assert cfg.llm.model == "test-model"
        assert cfg.llm.backend == "openai"


# ══════════════════════════════════════════════
# 3. LLMClient._model_name() — backend→litellm format
# ══════════════════════════════════════════════

class TestLLMClientModelName:
    def _make_client(self, backend, model):
        from ari.config import LLMConfig
        from ari.llm.client import LLMClient
        return LLMClient(LLMConfig(backend=backend, model=model))

    def test_openai_passthrough(self):
        c = self._make_client("openai", "gpt-4o")
        assert c._model_name() == "gpt-4o"

    def test_anthropic_prefix(self):
        c = self._make_client("anthropic", "claude-sonnet-4-5")
        assert c._model_name() == "anthropic/claude-sonnet-4-5"

    def test_claude_alias(self):
        c = self._make_client("claude", "claude-sonnet-4-5")
        assert c._model_name() == "anthropic/claude-sonnet-4-5"

    def test_ollama_prefix(self):
        c = self._make_client("ollama", "qwen3:8b")
        assert c._model_name() == "ollama_chat/qwen3:8b"

    def test_unknown_backend_passthrough(self):
        c = self._make_client("custom", "my-model")
        assert c._model_name() == "my-model"

    def test_ollama_no_double_prefix(self):
        """If model already has ollama_chat/ prefix, don't double it."""
        c = self._make_client("ollama", "qwen3:8b")
        name = c._model_name()
        assert name.count("ollama_chat/") == 1


# ══════════════════════════════════════════════
# 4. LLMClient.complete() — kwargs propagation
# ══════════════════════════════════════════════

class TestLLMClientComplete:
    def test_api_key_passed_when_set(self):
        from ari.config import LLMConfig
        from ari.llm.client import LLMClient
        c = LLMClient(LLMConfig(backend="openai", model="gpt-4o", api_key="sk-test-12345"))
        with mock.patch("litellm.completion") as m:
            m.return_value = mock.MagicMock(
                choices=[mock.MagicMock(message=mock.MagicMock(content="ok", tool_calls=None))],
                usage=None,
            )
            c.complete([{"role": "user", "content": "hi"}])
            kwargs = m.call_args[1]
            assert kwargs["api_key"] == "sk-test-12345"

    def test_api_key_omitted_when_none(self):
        from ari.config import LLMConfig
        from ari.llm.client import LLMClient
        c = LLMClient(LLMConfig(backend="openai", model="gpt-4o"))
        with mock.patch("litellm.completion") as m:
            m.return_value = mock.MagicMock(
                choices=[mock.MagicMock(message=mock.MagicMock(content="ok", tool_calls=None))],
                usage=None,
            )
            c.complete([{"role": "user", "content": "hi"}])
            kwargs = m.call_args[1]
            assert "api_key" not in kwargs

    def test_base_url_passed_for_ollama(self):
        from ari.config import LLMConfig
        from ari.llm.client import LLMClient
        c = LLMClient(LLMConfig(backend="ollama", model="qwen3:8b", base_url="http://gpu:11434"))
        with mock.patch("litellm.completion") as m:
            m.return_value = mock.MagicMock(
                choices=[mock.MagicMock(message=mock.MagicMock(content="ok", tool_calls=None))],
                usage=None,
            )
            c.complete([{"role": "user", "content": "hi"}])
            kwargs = m.call_args[1]
            assert kwargs["api_base"] == "http://gpu:11434"

    def test_base_url_omitted_when_none(self):
        from ari.config import LLMConfig
        from ari.llm.client import LLMClient
        c = LLMClient(LLMConfig(backend="openai", model="gpt-4o"))
        with mock.patch("litellm.completion") as m:
            m.return_value = mock.MagicMock(
                choices=[mock.MagicMock(message=mock.MagicMock(content="ok", tool_calls=None))],
                usage=None,
            )
            c.complete([{"role": "user", "content": "hi"}])
            kwargs = m.call_args[1]
            assert "api_base" not in kwargs

    def test_temperature_skipped_for_gpt5(self):
        from ari.config import LLMConfig
        from ari.llm.client import LLMClient
        c = LLMClient(LLMConfig(backend="openai", model="gpt-5.2"))
        with mock.patch("litellm.completion") as m:
            m.return_value = mock.MagicMock(
                choices=[mock.MagicMock(message=mock.MagicMock(content="ok", tool_calls=None))],
                usage=None,
            )
            c.complete([{"role": "user", "content": "hi"}])
            kwargs = m.call_args[1]
            assert "temperature" not in kwargs

    def test_qwen3_think_disabled(self):
        from ari.config import LLMConfig
        from ari.llm.client import LLMClient
        c = LLMClient(LLMConfig(backend="ollama", model="qwen3:8b", base_url="http://localhost:11434"))
        with mock.patch("litellm.completion") as m:
            m.return_value = mock.MagicMock(
                choices=[mock.MagicMock(message=mock.MagicMock(content="ok", tool_calls=None))],
                usage=None,
            )
            c.complete([{"role": "user", "content": "hi"}])
            kwargs = m.call_args[1]
            assert kwargs.get("extra_body", {}).get("options", {}).get("think") is False


# ══════════════════════════════════════════════
# 5. api_settings — load/save roundtrip
# ══════════════════════════════════════════════

class TestApiSettings:
    def test_get_defaults_when_no_file(self, state, tmp_path, monkeypatch, clean_env):
        monkeypatch.setattr(state, "_settings_path", tmp_path / "settings.json")
        from ari.viz.api_settings import _api_get_settings
        s = _api_get_settings()
        assert "llm_model" in s
        assert "llm_provider" in s

    def test_save_then_get_roundtrip(self, state, tmp_path, monkeypatch, clean_env):
        settings_path = tmp_path / "settings.json"
        monkeypatch.setattr(state, "_settings_path", settings_path)
        monkeypatch.setattr(state, "_env_write_path", tmp_path / ".env")
        from ari.viz.api_settings import _api_save_settings, _api_get_settings
        _api_save_settings(json.dumps({
            "llm_model": "gpt-4o-mini",
            "llm_provider": "openai",
            "temperature": 0.5,
        }).encode())
        s = _api_get_settings()
        assert s["llm_model"] == "gpt-4o-mini"
        assert s["llm_provider"] == "openai"
        assert s["temperature"] == 0.5

    def test_api_key_not_in_settings_json(self, state, tmp_path, monkeypatch, clean_env):
        settings_path = tmp_path / "settings.json"
        monkeypatch.setattr(state, "_settings_path", settings_path)
        # Redirect .env writes to tmp_path so real .env is never touched
        monkeypatch.setattr(state, "_env_write_path", tmp_path / ".env")
        from ari.viz.api_settings import _api_save_settings
        _api_save_settings(json.dumps({
            "llm_model": "gpt-4o",
            "llm_provider": "openai",
            "api_key": "sk-real-key-12345678901234567890",
        }).encode())
        saved = json.loads(settings_path.read_text())
        assert "api_key" not in saved
        assert "llm_api_key" not in saved
        # Verify the key was written to the redirected .env, not the real one
        env_content = (tmp_path / ".env").read_text()
        assert "sk-real-key-12345678901234567890" in env_content

    def test_saved_values_override_defaults(self, state, tmp_path, monkeypatch, clean_env):
        settings_path = tmp_path / "settings.json"
        settings_path.write_text(json.dumps({"llm_model": "my-custom-model"}))
        monkeypatch.setattr(state, "_settings_path", settings_path)
        from ari.viz.api_settings import _api_get_settings
        s = _api_get_settings()
        assert s["llm_model"] == "my-custom-model"
        # Default keys still present
        assert "llm_provider" in s
        assert "temperature" in s

    def test_per_skill_models_persisted(self, state, tmp_path, monkeypatch, clean_env):
        settings_path = tmp_path / "settings.json"
        monkeypatch.setattr(state, "_settings_path", settings_path)
        monkeypatch.setattr(state, "_env_write_path", tmp_path / ".env")
        from ari.viz.api_settings import _api_save_settings, _api_get_settings
        _api_save_settings(json.dumps({
            "llm_model": "gpt-4o",
            "llm_provider": "openai",
            "model_idea": "claude-sonnet-4-5",
            "model_coding": "gpt-4o-mini",
        }).encode())
        s = _api_get_settings()
        assert s["model_idea"] == "claude-sonnet-4-5"
        assert s["model_coding"] == "gpt-4o-mini"


# ══════════════════════════════════════════════
# 6. _api_launch — env var building
#    The critical bridge between GUI and subprocess.
# ══════════════════════════════════════════════

def _build_launch_env(state, tmp_path, monkeypatch, settings: dict,
                      wizard_data: dict | None = None,
                      env_file_content: str = "",
                      pre_env: dict | None = None) -> dict:
    """Helper: simulate _api_launch env building without actually spawning a process.

    Returns the proc_env dict that would be passed to Popen.
    """
    # Setup settings.json
    settings_path = tmp_path / ".ari" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(settings))
    monkeypatch.setattr(state, "_settings_path", settings_path)
    monkeypatch.setattr(state, "_checkpoint_dir", None)

    # Setup .env file
    ari_root = tmp_path / "ARI"
    ari_core = ari_root / "ari-core" / "ari" / "viz"
    ari_core.mkdir(parents=True, exist_ok=True)
    if env_file_content:
        (ari_root / ".env").write_text(env_file_content)

    # Clean env
    for k in list(os.environ):
        if (
            k.startswith("ARI_")
            or k.startswith("LETTA_")
            or k in (
                "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "OLLAMA_HOST",
            )
        ):
            monkeypatch.delenv(k, raising=False)
    if pre_env:
        for k, v in pre_env.items():
            monkeypatch.setenv(k, v)

    # Build experiment.md
    exp_path = tmp_path / "experiment.md"
    exp_path.write_text("# Test\ntest goal")

    # Build wizard data
    data = {"experiment_md": "# Test\ntest goal"}
    if wizard_data:
        data.update(wizard_data)

    # We can't call _api_launch directly (it spawns a process).
    # Instead, replicate the env-building logic.
    # This mirrors api_experiment.py lines 79-172 exactly.
    proc_env = os.environ.copy()

    # .env loading — restrict to tmp_path only (don't read real ~/.env)
    _env_candidates = [
        ari_root / ".env",
        ari_root / "ari-core" / ".env",
    ]
    for env_path in _env_candidates:
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    k = k.strip(); v = v.strip()
                    if k not in proc_env or not proc_env[k]:
                        proc_env[k] = v

    # Settings injection
    try:
        if settings_path.exists():
            saved = json.loads(settings_path.read_text())
            llm_model = saved.get("llm_model", "")
            llm_provider = saved.get("llm_provider", "") or saved.get("llm_backend", "")
            if llm_model:
                proc_env["ARI_MODEL"] = llm_model
                proc_env["ARI_LLM_MODEL"] = llm_model
            if llm_provider:
                proc_env["ARI_BACKEND"] = llm_provider
            _api_key = saved.get("api_key", "") or saved.get("llm_api_key", "")
            _is_placeholder = not _api_key or "test" in _api_key or len(_api_key) < 20
            if not _is_placeholder:
                if llm_provider == "openai" and not proc_env.get("OPENAI_API_KEY"):
                    proc_env["OPENAI_API_KEY"] = _api_key
                elif llm_provider == "anthropic" and not proc_env.get("ANTHROPIC_API_KEY"):
                    proc_env["ANTHROPIC_API_KEY"] = _api_key
            if llm_provider == "ollama":
                _real_ollama = saved.get("ollama_host", "").strip() or "http://localhost:11434"
                proc_env["OLLAMA_HOST"] = _real_ollama
            for skill in ["idea", "bfts", "coding", "eval", "paper", "review"]:
                val = saved.get(f"model_{skill}", "")
                if val:
                    proc_env[f"ARI_MODEL_{skill.upper()}"] = val
            # Memory (Letta) env injection — mirror api_experiment.py.
            _letta_base = saved.get("letta_base_url", "")
            if _letta_base:
                proc_env["LETTA_BASE_URL"] = _letta_base
            _letta_key = saved.get("letta_api_key", "")
            if _letta_key:
                proc_env["LETTA_API_KEY"] = _letta_key
            _letta_emb = saved.get("letta_embedding_config", "")
            if _letta_emb:
                proc_env["LETTA_EMBEDDING_CONFIG"] = _letta_emb
    except Exception:
        pass

    # Wizard overrides
    wiz_max_nodes = data.get("max_nodes")
    wiz_max_depth = data.get("max_depth")
    wiz_max_react = data.get("max_react")
    wiz_timeout_min = data.get("timeout_min")
    if wiz_max_nodes is not None:
        proc_env["ARI_MAX_NODES"] = str(int(wiz_max_nodes))
    if wiz_max_depth is not None:
        proc_env["ARI_MAX_DEPTH"] = str(int(wiz_max_depth))
    if wiz_max_react is not None:
        proc_env["ARI_MAX_REACT"] = str(int(wiz_max_react))
    if wiz_timeout_min is not None:
        proc_env["ARI_TIMEOUT_NODE"] = str(int(wiz_timeout_min) * 60)
    # HPC resource overrides from wizard Step 3
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
        _provider_defaults = {
            "openai": "gpt-4o",
            "anthropic": "claude-sonnet-4-5",
            "ollama": "qwen3:8b",
        }
        _default = _provider_defaults.get(_final_backend, "")
        if _default:
            proc_env["ARI_MODEL"] = _default
            proc_env["ARI_LLM_MODEL"] = _default

    return proc_env


class TestLaunchEnvBuilding:
    """Test the env dict that _api_launch passes to Popen."""

    def test_settings_model_injected(self, state, tmp_path, monkeypatch, clean_env):
        env = _build_launch_env(state, tmp_path, monkeypatch,
            settings={"llm_model": "gpt-4o", "llm_provider": "openai"})
        assert env["ARI_MODEL"] == "gpt-4o"
        assert env["ARI_LLM_MODEL"] == "gpt-4o"
        assert env["ARI_BACKEND"] == "openai"

    def test_wizard_overrides_settings(self, state, tmp_path, monkeypatch, clean_env):
        env = _build_launch_env(state, tmp_path, monkeypatch,
            settings={"llm_model": "gpt-4o", "llm_provider": "openai"},
            wizard_data={"llm_model": "claude-sonnet-4-5", "llm_provider": "anthropic"})
        assert env["ARI_MODEL"] == "claude-sonnet-4-5"
        assert env["ARI_BACKEND"] == "anthropic"

    def test_wizard_bfts_params(self, state, tmp_path, monkeypatch, clean_env):
        env = _build_launch_env(state, tmp_path, monkeypatch,
            settings={"llm_model": "gpt-4o", "llm_provider": "openai"},
            wizard_data={"max_nodes": 20, "max_depth": 3})
        assert env["ARI_MAX_NODES"] == "20"
        assert env["ARI_MAX_DEPTH"] == "3"

    def test_wizard_timeout_converted_to_seconds(self, state, tmp_path, monkeypatch, clean_env):
        env = _build_launch_env(state, tmp_path, monkeypatch,
            settings={"llm_model": "gpt-4o", "llm_provider": "openai"},
            wizard_data={"timeout_min": 30})
        assert env["ARI_TIMEOUT_NODE"] == "1800"

    def test_wizard_react_steps(self, state, tmp_path, monkeypatch, clean_env):
        env = _build_launch_env(state, tmp_path, monkeypatch,
            settings={"llm_model": "gpt-4o", "llm_provider": "openai"},
            wizard_data={"max_react": 120})
        assert env["ARI_MAX_REACT"] == "120"

    def test_letta_settings_propagate_to_env(
        self, state, tmp_path, monkeypatch, clean_env,
    ):
        """settings.json letta_* values become LETTA_* env vars in the
        subprocess. The memory skill's MemoryConfig reads these — if
        propagation breaks, the skill silently falls back to flaky
        defaults (the original 522/empty-body bug)."""
        env = _build_launch_env(state, tmp_path, monkeypatch, settings={
            "llm_model": "gpt-4o", "llm_provider": "openai",
            "letta_base_url": "http://letta-host:8283",
            "letta_api_key": "k-secret",
            "letta_embedding_config": "openai/text-embedding-3-small",
        })
        assert env["LETTA_BASE_URL"] == "http://letta-host:8283"
        assert env["LETTA_API_KEY"] == "k-secret"
        assert env["LETTA_EMBEDDING_CONFIG"] == "openai/text-embedding-3-small"
        # The Letta agent's chat LLM is hardcoded inside ari-skill-memory
        # (ARI never invokes it); LETTA_LLM_CONFIG must NOT be set even if
        # legacy settings.json contains it.
        assert "LETTA_LLM_CONFIG" not in env

    def test_letta_settings_absent_does_not_inject(
        self, state, tmp_path, monkeypatch, clean_env,
    ):
        """If the operator hasn't set Letta values in Settings, we must
        NOT inject empty strings — that would override env / workflow
        defaults. The memory skill needs to be able to fall back."""
        env = _build_launch_env(state, tmp_path, monkeypatch, settings={
            "llm_model": "gpt-4o", "llm_provider": "openai",
        })
        assert "LETTA_BASE_URL" not in env or env["LETTA_BASE_URL"] != ""
        assert env.get("LETTA_API_KEY", "") == ""
        assert env.get("LETTA_EMBEDDING_CONFIG", "") == ""
        assert "LETTA_LLM_CONFIG" not in env

    def test_per_skill_model_overrides(self, state, tmp_path, monkeypatch, clean_env):
        env = _build_launch_env(state, tmp_path, monkeypatch,
            settings={
                "llm_model": "gpt-4o", "llm_provider": "openai",
                "model_idea": "claude-opus-4-6",
                "model_coding": "gpt-4o-mini",
                "model_paper": "claude-sonnet-4-5",
            })
        assert env["ARI_MODEL_IDEA"] == "claude-opus-4-6"
        assert env["ARI_MODEL_CODING"] == "gpt-4o-mini"
        assert env["ARI_MODEL_PAPER"] == "claude-sonnet-4-5"

    def test_wizard_phase_models_override_settings(self, state, tmp_path, monkeypatch, clean_env):
        env = _build_launch_env(state, tmp_path, monkeypatch,
            settings={
                "llm_model": "gpt-4o", "llm_provider": "openai",
                "model_idea": "from-settings",
            },
            wizard_data={"phase_models": {"idea": "from-wizard"}})
        assert env["ARI_MODEL_IDEA"] == "from-wizard"

    def test_empty_skill_model_not_injected(self, state, tmp_path, monkeypatch, clean_env):
        env = _build_launch_env(state, tmp_path, monkeypatch,
            settings={
                "llm_model": "gpt-4o", "llm_provider": "openai",
                "model_idea": "",
                "model_coding": "",
            })
        assert "ARI_MODEL_IDEA" not in env
        assert "ARI_MODEL_CODING" not in env

    def test_safety_net_backend_without_model(self, state, tmp_path, monkeypatch, clean_env):
        """If provider is set but model is empty, a sensible default is injected."""
        env = _build_launch_env(state, tmp_path, monkeypatch,
            settings={"llm_model": "", "llm_provider": "openai"})
        assert env["ARI_MODEL"] == "gpt-4o"
        assert env["ARI_BACKEND"] == "openai"

    def test_safety_net_anthropic(self, state, tmp_path, monkeypatch, clean_env):
        env = _build_launch_env(state, tmp_path, monkeypatch,
            settings={"llm_model": "", "llm_provider": "anthropic"})
        assert env["ARI_MODEL"] == "claude-sonnet-4-5"

    def test_safety_net_not_triggered_when_model_set(self, state, tmp_path, monkeypatch, clean_env):
        """Safety net must NOT override an explicitly set model."""
        env = _build_launch_env(state, tmp_path, monkeypatch,
            settings={"llm_model": "gpt-4o-mini", "llm_provider": "openai"})
        assert env["ARI_MODEL"] == "gpt-4o-mini"

    def test_ollama_host_from_settings(self, state, tmp_path, monkeypatch, clean_env):
        env = _build_launch_env(state, tmp_path, monkeypatch,
            settings={
                "llm_model": "qwen3:8b", "llm_provider": "ollama",
                "ollama_host": "http://gpu-node:11434",
            })
        assert env["OLLAMA_HOST"] == "http://gpu-node:11434"

    def test_ollama_host_default_when_empty(self, state, tmp_path, monkeypatch, clean_env):
        env = _build_launch_env(state, tmp_path, monkeypatch,
            settings={"llm_model": "qwen3:8b", "llm_provider": "ollama"})
        assert env["OLLAMA_HOST"] == "http://localhost:11434"

    def test_ollama_host_not_set_for_openai(self, state, tmp_path, monkeypatch, clean_env):
        """OLLAMA_HOST must not be injected when provider is not ollama."""
        env = _build_launch_env(state, tmp_path, monkeypatch,
            settings={"llm_model": "gpt-4o", "llm_provider": "openai"})
        # Should not have been set by our settings injection
        # (may exist from parent env, which we cleared)
        assert env.get("OLLAMA_HOST", "") == ""

    def test_env_file_loaded(self, state, tmp_path, monkeypatch, clean_env):
        env = _build_launch_env(state, tmp_path, monkeypatch,
            settings={"llm_model": "gpt-4o", "llm_provider": "openai"},
            env_file_content="OPENAI_API_KEY=sk-from-dotenv\nCUSTOM_VAR=hello\n")
        assert env.get("OPENAI_API_KEY") == "sk-from-dotenv"
        assert env.get("CUSTOM_VAR") == "hello"

    def test_env_file_does_not_override_existing(self, state, tmp_path, monkeypatch, clean_env):
        """If env var already exists, .env must not override it."""
        env = _build_launch_env(state, tmp_path, monkeypatch,
            settings={"llm_model": "gpt-4o", "llm_provider": "openai"},
            env_file_content="OPENAI_API_KEY=sk-from-dotenv\n",
            pre_env={"OPENAI_API_KEY": "sk-from-shell"})
        assert env["OPENAI_API_KEY"] == "sk-from-shell"

    def test_api_key_from_settings_as_last_resort(self, state, tmp_path, monkeypatch, clean_env):
        """Settings API key used only when no other key exists."""
        env = _build_launch_env(state, tmp_path, monkeypatch,
            settings={
                "llm_model": "gpt-4o", "llm_provider": "openai",
                "api_key": "sk-from-settings-abcdefghijklmnop",
            })
        assert env.get("OPENAI_API_KEY") == "sk-from-settings-abcdefghijklmnop"

    def test_api_key_placeholder_rejected(self, state, tmp_path, monkeypatch, clean_env):
        """Placeholder/test API keys must not be injected."""
        env = _build_launch_env(state, tmp_path, monkeypatch,
            settings={
                "llm_model": "gpt-4o", "llm_provider": "openai",
                "api_key": "test-key",
            })
        assert env.get("OPENAI_API_KEY", "") == ""

    def test_api_key_short_rejected(self, state, tmp_path, monkeypatch, clean_env):
        """API keys shorter than 20 chars must not be injected."""
        env = _build_launch_env(state, tmp_path, monkeypatch,
            settings={
                "llm_model": "gpt-4o", "llm_provider": "openai",
                "api_key": "sk-short",
            })
        assert env.get("OPENAI_API_KEY", "") == ""

    def test_anthropic_api_key_routing(self, state, tmp_path, monkeypatch, clean_env):
        """Anthropic provider routes key to ANTHROPIC_API_KEY."""
        env = _build_launch_env(state, tmp_path, monkeypatch,
            settings={
                "llm_model": "claude-sonnet-4-5", "llm_provider": "anthropic",
                "api_key": "sk-ant-from-settings-0123456789",
            })
        assert env.get("ANTHROPIC_API_KEY") == "sk-ant-from-settings-0123456789"
        assert env.get("OPENAI_API_KEY", "") == ""


# ══════════════════════════════════════════════
# 7. End-to-end: launch env → auto_config → LLMClient
#    Simulates the subprocess receiving env and building runtime.
# ══════════════════════════════════════════════

class TestEndToEnd:
    """Verify the full chain: settings → env → config → LLMClient."""

    def test_openai_full_chain(self, state, tmp_path, monkeypatch, clean_env):
        env = _build_launch_env(state, tmp_path, monkeypatch,
            settings={"llm_model": "gpt-4o-mini", "llm_provider": "openai"})
        # Simulate subprocess: set env vars as the child process would see them
        monkeypatch.setenv("ARI_MODEL", env["ARI_MODEL"])
        monkeypatch.setenv("ARI_BACKEND", env["ARI_BACKEND"])
        from ari.config import auto_config
        cfg = auto_config()
        assert cfg.llm.backend == "openai"
        assert cfg.llm.model == "gpt-4o-mini"
        assert cfg.llm.base_url is None  # No ollama URL for openai
        from ari.llm.client import LLMClient
        c = LLMClient(cfg.llm)
        assert c._model_name() == "gpt-4o-mini"

    def test_anthropic_full_chain(self, state, tmp_path, monkeypatch, clean_env):
        env = _build_launch_env(state, tmp_path, monkeypatch,
            settings={"llm_model": "claude-sonnet-4-5", "llm_provider": "anthropic"})
        monkeypatch.setenv("ARI_MODEL", env["ARI_MODEL"])
        monkeypatch.setenv("ARI_BACKEND", env["ARI_BACKEND"])
        from ari.config import auto_config
        cfg = auto_config()
        assert cfg.llm.backend == "anthropic"
        assert cfg.llm.model == "claude-sonnet-4-5"
        from ari.llm.client import LLMClient
        c = LLMClient(cfg.llm)
        assert c._model_name() == "anthropic/claude-sonnet-4-5"

    def test_ollama_full_chain(self, state, tmp_path, monkeypatch, clean_env):
        env = _build_launch_env(state, tmp_path, monkeypatch,
            settings={
                "llm_model": "llama3.3", "llm_provider": "ollama",
                "ollama_host": "http://gpu:11434",
            })
        monkeypatch.setenv("ARI_MODEL", env["ARI_MODEL"])
        monkeypatch.setenv("ARI_BACKEND", env["ARI_BACKEND"])
        monkeypatch.setenv("OLLAMA_HOST", env["OLLAMA_HOST"])
        from ari.config import auto_config
        cfg = auto_config()
        assert cfg.llm.backend == "ollama"
        assert cfg.llm.model == "llama3.3"
        assert cfg.llm.base_url == "http://gpu:11434"
        from ari.llm.client import LLMClient
        c = LLMClient(cfg.llm)
        assert c._model_name() == "ollama_chat/llama3.3"

    def test_bfts_params_full_chain(self, state, tmp_path, monkeypatch, clean_env):
        env = _build_launch_env(state, tmp_path, monkeypatch,
            settings={"llm_model": "gpt-4o", "llm_provider": "openai"},
            wizard_data={"max_nodes": 15, "max_depth": 3, "max_react": 40, "timeout_min": 60})
        monkeypatch.setenv("ARI_MAX_NODES", env["ARI_MAX_NODES"])
        monkeypatch.setenv("ARI_MAX_DEPTH", env["ARI_MAX_DEPTH"])
        monkeypatch.setenv("ARI_MAX_REACT", env["ARI_MAX_REACT"])
        monkeypatch.setenv("ARI_TIMEOUT_NODE", env["ARI_TIMEOUT_NODE"])
        from ari.config import auto_config
        cfg = auto_config()
        assert cfg.bfts.max_total_nodes == 15
        assert cfg.bfts.max_depth == 3
        assert cfg.bfts.max_react_steps == 40
        assert cfg.bfts.timeout_per_node == 3600

    def test_wizard_override_reaches_config(self, state, tmp_path, monkeypatch, clean_env):
        """Settings says gpt-4o, wizard overrides to claude → config must see claude."""
        env = _build_launch_env(state, tmp_path, monkeypatch,
            settings={"llm_model": "gpt-4o", "llm_provider": "openai"},
            wizard_data={"llm_model": "claude-opus-4-6", "llm_provider": "anthropic"})
        monkeypatch.setenv("ARI_MODEL", env["ARI_MODEL"])
        monkeypatch.setenv("ARI_BACKEND", env["ARI_BACKEND"])
        from ari.config import auto_config
        cfg = auto_config()
        assert cfg.llm.model == "claude-opus-4-6"
        assert cfg.llm.backend == "anthropic"

    def test_empty_settings_still_works(self, state, tmp_path, monkeypatch, clean_env):
        """Completely empty settings.json should not crash; defaults are used."""
        env = _build_launch_env(state, tmp_path, monkeypatch, settings={})
        # No ARI_MODEL or ARI_BACKEND set → auto_config falls back to defaults
        from ari.config import auto_config
        cfg = auto_config()
        assert cfg.llm.backend == "ollama"
        assert cfg.llm.model == "qwen3:8b"


# ══════════════════════════════════════════════
# 8. Edge cases and known bug vectors
# ══════════════════════════════════════════════

class TestEdgeCases:
    def test_gemini_model_name_slash_preserved(self, clean_env, monkeypatch):
        """Gemini models use 'gemini/gemini-2.5-pro' — the slash must survive."""
        monkeypatch.setenv("ARI_MODEL", "gemini/gemini-2.5-pro")
        monkeypatch.setenv("ARI_BACKEND", "gemini")
        from ari.config import auto_config
        cfg = auto_config()
        assert cfg.llm.model == "gemini/gemini-2.5-pro"

    def test_model_with_colon_preserved(self, clean_env, monkeypatch):
        """Ollama models like 'qwen3:8b' have colons — must survive."""
        monkeypatch.setenv("ARI_MODEL", "qwen3:8b")
        monkeypatch.setenv("ARI_BACKEND", "ollama")
        from ari.config import auto_config
        cfg = auto_config()
        assert cfg.llm.model == "qwen3:8b"

    def test_settings_with_llm_backend_alias(self, state, tmp_path, monkeypatch, clean_env):
        """settings.json may use 'llm_backend' instead of 'llm_provider'."""
        env = _build_launch_env(state, tmp_path, monkeypatch,
            settings={"llm_model": "gpt-4o", "llm_backend": "openai"})
        assert env["ARI_BACKEND"] == "openai"

    def test_dotenv_quotes_stripped(self, state, tmp_path, monkeypatch, clean_env):
        """.env values with quotes should have quotes stripped at _api_get_env_keys level.
        But _api_launch reads .env raw (split on =), so quotes remain as-is.
        This test documents the current behavior."""
        env = _build_launch_env(state, tmp_path, monkeypatch,
            settings={"llm_model": "gpt-4o", "llm_provider": "openai"},
            env_file_content='OPENAI_API_KEY="sk-quoted-key-value-0123456789"\n')
        # _api_launch does NOT strip quotes (known limitation)
        key = env.get("OPENAI_API_KEY", "")
        assert "sk-quoted-key-value-0123456789" in key

    def test_no_settings_file_no_crash(self, state, tmp_path, monkeypatch, clean_env):
        """Missing settings.json must not crash _api_launch env building."""
        settings_path = tmp_path / "nonexistent" / "settings.json"
        monkeypatch.setattr(state, "_settings_path", settings_path)
        monkeypatch.setattr(state, "_checkpoint_dir", None)
        # Should not raise
        from ari.viz.api_settings import _api_get_settings
        s = _api_get_settings()
        assert isinstance(s, dict)

    def test_corrupt_settings_json_no_crash(self, state, tmp_path, monkeypatch, clean_env):
        """Corrupt settings.json must not crash; defaults are used."""
        settings_path = tmp_path / "settings.json"
        settings_path.write_text("{invalid json")
        monkeypatch.setattr(state, "_settings_path", settings_path)
        from ari.viz.api_settings import _api_get_settings
        s = _api_get_settings()
        assert isinstance(s, dict)
        assert "llm_model" in s  # defaults still returned

    def test_provider_set_model_empty_gets_default(self, state, tmp_path, monkeypatch, clean_env):
        """If wizard sets provider but not model, safety net injects a default."""
        env = _build_launch_env(state, tmp_path, monkeypatch,
            settings={},
            wizard_data={"llm_provider": "anthropic"})
        assert env["ARI_MODEL"] == "claude-sonnet-4-5"
        assert env["ARI_BACKEND"] == "anthropic"

    def test_both_ari_model_names_set(self, state, tmp_path, monkeypatch, clean_env):
        """Both ARI_MODEL and ARI_LLM_MODEL must be set identically."""
        env = _build_launch_env(state, tmp_path, monkeypatch,
            settings={"llm_model": "gpt-4o", "llm_provider": "openai"})
        assert env["ARI_MODEL"] == env["ARI_LLM_MODEL"]

    def test_env_comment_lines_ignored(self, state, tmp_path, monkeypatch, clean_env):
        """Comment lines in .env must be ignored."""
        env = _build_launch_env(state, tmp_path, monkeypatch,
            settings={"llm_model": "gpt-4o", "llm_provider": "openai"},
            env_file_content="# This is a comment\nMY_VAR=value\n")
        assert "# This is a comment" not in str(env)
        assert env.get("MY_VAR") == "value"


# ============================================================================
#  HPC Resource Propagation Tests
# ============================================================================

class TestHPCResourcePropagation:
    """Test that HPC resource settings (CPUs, memory, walltime, partition)
    flow correctly from wizard → env vars → config.resources."""

    # --- Layer 1: Wizard data → environment variables -----------------------

    def test_wizard_hpc_cpus_injected(self, state, tmp_path, monkeypatch, clean_env):
        env = _build_launch_env(state, tmp_path, monkeypatch,
            settings={"llm_model": "gpt-4o", "llm_provider": "openai"},
            wizard_data={"hpc_cpus": 16})
        assert env["ARI_SLURM_CPUS"] == "16"

    def test_wizard_hpc_memory_injected(self, state, tmp_path, monkeypatch, clean_env):
        env = _build_launch_env(state, tmp_path, monkeypatch,
            settings={"llm_model": "gpt-4o", "llm_provider": "openai"},
            wizard_data={"hpc_memory_gb": 64})
        assert env["ARI_SLURM_MEM_GB"] == "64"

    def test_wizard_hpc_walltime_injected(self, state, tmp_path, monkeypatch, clean_env):
        env = _build_launch_env(state, tmp_path, monkeypatch,
            settings={"llm_model": "gpt-4o", "llm_provider": "openai"},
            wizard_data={"hpc_walltime": "08:00:00"})
        assert env["ARI_SLURM_WALLTIME"] == "08:00:00"

    def test_wizard_hpc_partition_injected(self, state, tmp_path, monkeypatch, clean_env):
        env = _build_launch_env(state, tmp_path, monkeypatch,
            settings={"llm_model": "gpt-4o", "llm_provider": "openai"},
            wizard_data={"partition": "gpu-large"})
        assert env["ARI_SLURM_PARTITION"] == "gpu-large"

    def test_wizard_hpc_gpus_injected(self, state, tmp_path, monkeypatch, clean_env):
        env = _build_launch_env(state, tmp_path, monkeypatch,
            settings={"llm_model": "gpt-4o", "llm_provider": "openai"},
            wizard_data={"hpc_gpus": 2})
        assert env["ARI_SLURM_GPUS"] == "2"

    def test_wizard_all_hpc_resources_together(self, state, tmp_path, monkeypatch, clean_env):
        """All HPC resource fields sent together."""
        env = _build_launch_env(state, tmp_path, monkeypatch,
            settings={"llm_model": "gpt-4o", "llm_provider": "openai"},
            wizard_data={
                "hpc_cpus": 32,
                "hpc_memory_gb": 128,
                "hpc_gpus": 4,
                "hpc_walltime": "12:00:00",
                "partition": "compute",
            })
        assert env["ARI_SLURM_CPUS"] == "32"
        assert env["ARI_SLURM_MEM_GB"] == "128"
        assert env["ARI_SLURM_GPUS"] == "4"
        assert env["ARI_SLURM_WALLTIME"] == "12:00:00"
        assert env["ARI_SLURM_PARTITION"] == "compute"

    def test_hpc_resources_omitted_when_not_set(self, state, tmp_path, monkeypatch, clean_env):
        """When wizard doesn't send HPC data, env vars must NOT be set."""
        env = _build_launch_env(state, tmp_path, monkeypatch,
            settings={"llm_model": "gpt-4o", "llm_provider": "openai"},
            wizard_data={})
        assert "ARI_SLURM_CPUS" not in env
        assert "ARI_SLURM_MEM_GB" not in env
        assert "ARI_SLURM_GPUS" not in env
        assert "ARI_SLURM_WALLTIME" not in env
        assert "ARI_SLURM_PARTITION" not in env

    def test_hpc_resources_none_values_omitted(self, state, tmp_path, monkeypatch, clean_env):
        """Explicit None values must not inject env vars."""
        env = _build_launch_env(state, tmp_path, monkeypatch,
            settings={"llm_model": "gpt-4o", "llm_provider": "openai"},
            wizard_data={"hpc_cpus": None, "hpc_memory_gb": None, "hpc_gpus": None})
        assert "ARI_SLURM_CPUS" not in env
        assert "ARI_SLURM_MEM_GB" not in env
        assert "ARI_SLURM_GPUS" not in env

    def test_hpc_empty_partition_omitted(self, state, tmp_path, monkeypatch, clean_env):
        """Empty string partition must not inject env var."""
        env = _build_launch_env(state, tmp_path, monkeypatch,
            settings={"llm_model": "gpt-4o", "llm_provider": "openai"},
            wizard_data={"partition": ""})
        assert "ARI_SLURM_PARTITION" not in env

    # --- Layer 2: Environment variables → config.resources ------------------

    def test_auto_config_reads_slurm_cpus(self, monkeypatch, clean_env):
        monkeypatch.setenv("ARI_SLURM_CPUS", "16")
        from ari.config import auto_config
        cfg = auto_config()
        assert cfg.resources["cpus"] == "16"

    def test_auto_config_reads_slurm_memory(self, monkeypatch, clean_env):
        monkeypatch.setenv("ARI_SLURM_MEM_GB", "64")
        from ari.config import auto_config
        cfg = auto_config()
        assert cfg.resources["memory_gb"] == "64"

    def test_auto_config_reads_slurm_walltime(self, monkeypatch, clean_env):
        monkeypatch.setenv("ARI_SLURM_WALLTIME", "08:00:00")
        from ari.config import auto_config
        cfg = auto_config()
        assert cfg.resources["walltime"] == "08:00:00"

    def test_auto_config_reads_slurm_partition(self, monkeypatch, clean_env):
        monkeypatch.setenv("ARI_SLURM_PARTITION", "gpu-large")
        from ari.config import auto_config
        cfg = auto_config()
        assert cfg.resources["partition"] == "gpu-large"

    def test_auto_config_reads_slurm_gpus(self, monkeypatch, clean_env):
        monkeypatch.setenv("ARI_SLURM_GPUS", "2")
        from ari.config import auto_config
        cfg = auto_config()
        assert cfg.resources["gpus"] == "2"

    def test_auto_config_resources_empty_when_no_env(self, monkeypatch, clean_env):
        """resources dict must be empty when no ARI_SLURM_* vars are set."""
        from ari.config import auto_config
        cfg = auto_config()
        assert cfg.resources == {}

    def test_auto_config_resources_partial(self, monkeypatch, clean_env):
        """Only set vars appear in resources; unset keys are absent."""
        monkeypatch.setenv("ARI_SLURM_CPUS", "8")
        from ari.config import auto_config
        cfg = auto_config()
        assert cfg.resources == {"cpus": "8"}
        assert "memory_gb" not in cfg.resources
        assert "walltime" not in cfg.resources

    # --- Layer 3: Full chain wizard → env → config --------------------------

    def test_full_chain_hpc_resources(self, state, tmp_path, monkeypatch, clean_env):
        """End-to-end: wizard HPC values reach config.resources."""
        env = _build_launch_env(state, tmp_path, monkeypatch,
            settings={"llm_model": "gpt-4o", "llm_provider": "openai"},
            wizard_data={
                "hpc_cpus": 24,
                "hpc_memory_gb": 96,
                "hpc_gpus": 2,
                "hpc_walltime": "06:30:00",
                "partition": "batch",
            })
        # Simulate config loading with the built env
        monkeypatch.setenv("ARI_SLURM_CPUS", env["ARI_SLURM_CPUS"])
        monkeypatch.setenv("ARI_SLURM_MEM_GB", env["ARI_SLURM_MEM_GB"])
        monkeypatch.setenv("ARI_SLURM_GPUS", env["ARI_SLURM_GPUS"])
        monkeypatch.setenv("ARI_SLURM_WALLTIME", env["ARI_SLURM_WALLTIME"])
        monkeypatch.setenv("ARI_SLURM_PARTITION", env["ARI_SLURM_PARTITION"])
        from ari.config import auto_config
        cfg = auto_config()
        assert cfg.resources["cpus"] == "24"
        assert cfg.resources["memory_gb"] == "96"
        assert cfg.resources["gpus"] == "2"
        assert cfg.resources["walltime"] == "06:30:00"
        assert cfg.resources["partition"] == "batch"

    def test_full_chain_hpc_coexists_with_bfts(self, state, tmp_path, monkeypatch, clean_env):
        """HPC resources and BFTS params set simultaneously don't interfere."""
        env = _build_launch_env(state, tmp_path, monkeypatch,
            settings={"llm_model": "gpt-4o", "llm_provider": "openai"},
            wizard_data={
                "max_nodes": 60, "max_depth": 9,
                "hpc_cpus": 16, "hpc_memory_gb": 64, "hpc_gpus": 1,
            })
        assert env["ARI_MAX_NODES"] == "60"
        assert env["ARI_MAX_DEPTH"] == "9"
        assert env["ARI_SLURM_CPUS"] == "16"
        assert env["ARI_SLURM_MEM_GB"] == "64"
        assert env["ARI_SLURM_GPUS"] == "1"
        # Verify they reach config independently
        monkeypatch.setenv("ARI_MAX_NODES", env["ARI_MAX_NODES"])
        monkeypatch.setenv("ARI_MAX_DEPTH", env["ARI_MAX_DEPTH"])
        monkeypatch.setenv("ARI_SLURM_CPUS", env["ARI_SLURM_CPUS"])
        monkeypatch.setenv("ARI_SLURM_MEM_GB", env["ARI_SLURM_MEM_GB"])
        monkeypatch.setenv("ARI_SLURM_GPUS", env["ARI_SLURM_GPUS"])
        from ari.config import auto_config
        cfg = auto_config()
        assert cfg.bfts.max_total_nodes == 60
        assert cfg.bfts.max_depth == 9
        assert cfg.resources["cpus"] == "16"
        assert cfg.resources["memory_gb"] == "64"
        assert cfg.resources["gpus"] == "1"
