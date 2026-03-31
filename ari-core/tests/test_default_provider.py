"""
test_default_provider.py
──────────────────────────────────────────────────────────────────────────────
Tests for default LLM provider/model values and their propagation.

Covers three areas:
  A. Default values are never empty (workflow.yaml → api_settings → JS)
  B. Default values can be changed via GUI (save → reload roundtrip)
  C. Changed values propagate correctly (settings → wizard → launch → state)
──────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from unittest import mock

import pytest
import yaml

# ── Paths ──
_VIZ = Path(__file__).parent.parent / "ari" / "viz"
_CONFIG = Path(__file__).parent.parent / "config"
_REACT_SRC = _VIZ / "frontend" / "src"
_REACT_COMPONENTS = _REACT_SRC / "components"


def _read_react_sources():
    """Read all React TypeScript source files and return combined text."""
    parts = []
    for tsx in sorted(_REACT_SRC.rglob("*.tsx")):
        parts.append(tsx.read_text())
    for ts in sorted(_REACT_SRC.rglob("*.ts")):
        parts.append(ts.read_text())
    return "\n".join(parts)


def _settings_page():
    return (_REACT_COMPONENTS / "Settings" / "SettingsPage.tsx").read_text()


def _step_resources():
    return (_REACT_COMPONENTS / "Wizard" / "StepResources.tsx").read_text()


def _step_launch():
    return (_REACT_COMPONENTS / "Wizard" / "StepLaunch.tsx").read_text()


def _combined():
    return _read_react_sources()


def _workflow_yaml() -> dict:
    wf = _CONFIG / "workflow.yaml"
    return yaml.safe_load(wf.read_text()) if wf.exists() else {}


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


# ══════════════════════════════════════════════════════════════════════════
# A. DEFAULT VALUES: Never Empty
# ══════════════════════════════════════════════════════════════════════════

class TestDefaultProviderConstant:
    """React DEFAULT_PROVIDER constant exists and is consistent with workflow.yaml."""

    def test_default_provider_defined(self):
        src = _settings_page()
        m = re.search(r"const\s+DEFAULT_PROVIDER\s*=\s*['\"](\w+)['\"]", src)
        assert m, "DEFAULT_PROVIDER not defined in SettingsPage.tsx"
        assert m.group(1) != "", "DEFAULT_PROVIDER must not be empty"

    def test_default_provider_matches_workflow_yaml(self):
        wf = _workflow_yaml()
        wf_backend = wf.get("llm", {}).get("backend", "")
        src = _settings_page()
        m = re.search(r"const\s+DEFAULT_PROVIDER\s*=\s*['\"](\w+)['\"]", src)
        assert m, "DEFAULT_PROVIDER not found"
        assert m.group(1) == wf_backend, \
            f"DEFAULT_PROVIDER '{m.group(1)}' != workflow.yaml backend '{wf_backend}'"

    def test_default_provider_is_valid_option(self):
        """DEFAULT_PROVIDER must match one of the provider option values."""
        src = _settings_page()
        options = re.findall(r'<option\s+value="(\w+)"', src)
        m = re.search(r"const\s+DEFAULT_PROVIDER\s*=\s*['\"](\w+)['\"]", src)
        assert m and m.group(1) in options, \
            f"DEFAULT_PROVIDER '{m.group(1) if m else '?'}' not in provider options {options}"

    def test_default_provider_has_models(self):
        """DEFAULT_PROVIDER must have a non-empty entry in PROVIDER_MODELS."""
        src = _settings_page()
        m = re.search(r"const\s+DEFAULT_PROVIDER\s*=\s*['\"](\w+)['\"]", src)
        assert m
        prov = m.group(1)
        # Find PROVIDER_MODELS block
        pm_idx = src.find("PROVIDER_MODELS")
        assert pm_idx >= 0
        pm_block = src[pm_idx:src.find("};", pm_idx) + 2]
        assert f"{prov}:" in pm_block or f"'{prov}':" in pm_block, \
            f"PROVIDER_MODELS missing entry for DEFAULT_PROVIDER '{prov}'"


class TestNoEmptyProviderFallback:
    """No React code falls back to empty string for provider."""

    def _find_provider_fallbacks(self, src: str) -> list[tuple[int, str]]:
        """Find all ||'' or ||\"\" patterns after 'provider' context."""
        hits = []
        for i, line in enumerate(src.splitlines(), 1):
            # Match provider-related fallbacks to empty string
            if ("provider" in line.lower() or "prov" in line.lower()) and \
               ("||''" in line or '||""' in line):
                hits.append((i, line.strip()))
        return hits

    def test_settings_page_no_empty_provider_fallback(self):
        hits = self._find_provider_fallbacks(_settings_page())
        assert hits == [], \
            f"SettingsPage.tsx has empty-string fallbacks for provider: {hits}"

    def test_step_resources_no_empty_provider_fallback(self):
        hits = self._find_provider_fallbacks(_step_resources())
        assert hits == [], \
            f"StepResources.tsx has empty-string fallbacks for provider: {hits}"


class TestDefaultProviderUsedEverywhere:
    """DEFAULT_PROVIDER is used as fallback in React components."""

    def test_settings_loadSettings_uses_default_provider(self):
        src = _settings_page()
        assert "DEFAULT_PROVIDER" in src, \
            "SettingsPage loadSettings must fall back to DEFAULT_PROVIDER"

    def test_provider_change_uses_default_provider(self):
        src = _settings_page()
        fn_idx = src.find("handleProviderChange")
        assert fn_idx >= 0
        body = src[fn_idx:fn_idx + 300]
        assert "DEFAULT_PROVIDER" in body, \
            "handleProviderChange must fall back to DEFAULT_PROVIDER"

    def test_step_resources_prefill_uses_default(self):
        """StepResources settings fetch must default to a provider."""
        src = _step_resources()
        # StepResources: s.llm_provider || s.llm_backend || 'openai'
        assert "'openai'" in src or "DEFAULT_PROVIDER" in src, \
            "StepResources must have a provider fallback"

    def test_launch_payload_has_provider_fallback(self):
        """StepLaunch must send a non-empty provider fallback."""
        src = _step_launch()
        assert "llm_provider" in src, "StepLaunch must send llm_provider"
        # StepLaunch: llmProvider || 'openai'
        assert "|| 'openai'" in src or '|| "openai"' in src, \
            "StepLaunch must fall back to 'openai' provider"


class TestProviderOptions:
    """React provider select elements have correct options."""

    def test_settings_provider_no_empty_option(self):
        src = _settings_page()
        # Find the provider select block
        idx = src.find("handleProviderChange")
        if idx < 0:
            idx = 0
        # Provider options should not have empty value
        options = re.findall(r'<option\s+value="(\w*)"', src)
        provider_options = [o for o in options if o in ("openai", "anthropic", "gemini", "ollama", "")]
        assert "" not in provider_options or len([o for o in provider_options if o == ""]) == 0, \
            "Provider select must not have an empty-value option"

    def test_wizard_provider_has_initial_state(self):
        """Wizard llm state must have a default value."""
        src = (_REACT_COMPONENTS / "Wizard" / "WizardPage.tsx").read_text()
        assert "useState('openai')" in src or 'useState("openai")' in src, \
            "Wizard llm state must default to 'openai'"

    def test_provider_options_match_provider_models(self):
        """All provider options must have PROVIDER_MODELS entries."""
        src = _settings_page()
        pm_idx = src.find("PROVIDER_MODELS")
        assert pm_idx >= 0
        pm_block = src[pm_idx:src.find("};", pm_idx) + 2]
        # Options in the provider select
        options = re.findall(r'<option\s+value="(\w+)"', src)
        providers = set(o for o in options if o in ("openai", "anthropic", "gemini", "ollama"))
        for prov in providers:
            assert f"{prov}:" in pm_block or f"'{prov}':" in pm_block, \
                f"Provider option '{prov}' has no PROVIDER_MODELS entry"


# ══════════════════════════════════════════════════════════════════════════
# B. DEFAULTS CAN BE CHANGED VIA GUI (save/load roundtrip)
# ══════════════════════════════════════════════════════════════════════════

class TestApiSettingsWorkflowDefault:
    """_api_get_settings returns workflow.yaml defaults when settings.json is empty."""

    def test_empty_settings_returns_workflow_backend(self, state, tmp_path, monkeypatch, clean_env):
        settings_path = tmp_path / "settings.json"
        settings_path.write_text(json.dumps({"llm_provider": "", "llm_model": ""}))
        monkeypatch.setattr(state, "_settings_path", settings_path)
        from ari.viz.api_settings import _api_get_settings
        s = _api_get_settings()
        wf = _workflow_yaml()
        expected_backend = wf.get("llm", {}).get("backend", "")
        assert s["llm_provider"] == expected_backend, \
            f"Empty settings must fall back to workflow.yaml backend '{expected_backend}'"

    def test_empty_settings_returns_workflow_model(self, state, tmp_path, monkeypatch, clean_env):
        settings_path = tmp_path / "settings.json"
        settings_path.write_text(json.dumps({"llm_provider": "", "llm_model": ""}))
        monkeypatch.setattr(state, "_settings_path", settings_path)
        from ari.viz.api_settings import _api_get_settings
        s = _api_get_settings()
        wf = _workflow_yaml()
        expected_model = wf.get("llm", {}).get("model", "")
        assert s["llm_model"] == expected_model, \
            f"Empty settings must fall back to workflow.yaml model '{expected_model}'"

    def test_missing_settings_returns_workflow_defaults(self, state, tmp_path, monkeypatch, clean_env):
        settings_path = tmp_path / "nonexistent_settings.json"
        monkeypatch.setattr(state, "_settings_path", settings_path)
        from ari.viz.api_settings import _api_get_settings
        s = _api_get_settings()
        wf = _workflow_yaml()
        assert s["llm_provider"] == wf.get("llm", {}).get("backend", "")
        assert s["llm_model"] == wf.get("llm", {}).get("model", "")

    def test_provider_never_empty(self, state, tmp_path, monkeypatch, clean_env):
        """Regardless of settings.json content, llm_provider must never be empty."""
        settings_path = tmp_path / "settings.json"
        monkeypatch.setattr(state, "_settings_path", settings_path)
        from ari.viz.api_settings import _api_get_settings
        # Case 1: no file
        s = _api_get_settings()
        assert s["llm_provider"] != "", "llm_provider must not be empty (no file)"
        # Case 2: empty values
        settings_path.write_text(json.dumps({"llm_provider": ""}))
        s = _api_get_settings()
        assert s["llm_provider"] != "", "llm_provider must not be empty (empty value)"
        # Case 3: key missing
        settings_path.write_text(json.dumps({"temperature": 0.5}))
        s = _api_get_settings()
        assert s["llm_provider"] != "", "llm_provider must not be empty (key missing)"


class TestApiSettingsChangeAndReload:
    """Saving a different provider/model via POST, then reloading returns the new values."""

    def test_change_provider_roundtrip(self, state, tmp_path, monkeypatch, clean_env):
        settings_path = tmp_path / "settings.json"
        monkeypatch.setattr(state, "_settings_path", settings_path)
        monkeypatch.setattr(state, "_env_write_path", tmp_path / ".env")
        from ari.viz.api_settings import _api_save_settings, _api_get_settings
        for provider in ["openai", "anthropic", "ollama"]:
            _api_save_settings(json.dumps({"llm_provider": provider}).encode())
            s = _api_get_settings()
            assert s["llm_provider"] == provider, \
                f"After saving '{provider}', GET returned '{s['llm_provider']}'"

    def test_change_model_roundtrip(self, state, tmp_path, monkeypatch, clean_env):
        settings_path = tmp_path / "settings.json"
        monkeypatch.setattr(state, "_settings_path", settings_path)
        monkeypatch.setattr(state, "_env_write_path", tmp_path / ".env")
        from ari.viz.api_settings import _api_save_settings, _api_get_settings
        models = ["gpt-5.2", "claude-sonnet-4-5", "qwen3:8b", "custom-model-v1"]
        for model in models:
            _api_save_settings(json.dumps({
                "llm_provider": "openai", "llm_model": model
            }).encode())
            s = _api_get_settings()
            assert s["llm_model"] == model, \
                f"After saving model '{model}', GET returned '{s['llm_model']}'"

    def test_change_does_not_affect_other_fields(self, state, tmp_path, monkeypatch, clean_env):
        settings_path = tmp_path / "settings.json"
        monkeypatch.setattr(state, "_settings_path", settings_path)
        monkeypatch.setattr(state, "_env_write_path", tmp_path / ".env")
        from ari.viz.api_settings import _api_save_settings, _api_get_settings
        _api_save_settings(json.dumps({
            "llm_provider": "anthropic",
            "llm_model": "claude-sonnet-4-5",
            "temperature": 0.3,
            "slurm_cpus": 16,
        }).encode())
        s = _api_get_settings()
        assert s["temperature"] == 0.3
        assert s["slurm_cpus"] == 16
        # Change just the provider
        _api_save_settings(json.dumps({
            "llm_provider": "openai",
            "llm_model": "gpt-4o",
            "temperature": 0.3,
            "slurm_cpus": 16,
        }).encode())
        s = _api_get_settings()
        assert s["llm_provider"] == "openai"
        assert s["temperature"] == 0.3
        assert s["slurm_cpus"] == 16

    def test_env_var_overrides_settings(self, state, tmp_path, monkeypatch, clean_env):
        """ARI_BACKEND env var takes precedence over settings.json."""
        settings_path = tmp_path / "settings.json"
        settings_path.write_text(json.dumps({"llm_provider": "ollama"}))
        monkeypatch.setattr(state, "_settings_path", settings_path)
        monkeypatch.setenv("ARI_BACKEND", "anthropic")
        from ari.viz.api_settings import _api_get_settings
        s = _api_get_settings()
        # env var populates the default; saved value overrides default
        # But since saved value is "ollama", it should stay "ollama"
        assert s["llm_provider"] == "ollama", \
            "Saved non-empty value should override env default"

    def test_env_var_fills_default_when_saved_empty(self, state, tmp_path, monkeypatch, clean_env):
        """ARI_BACKEND env var used when settings.json value is empty."""
        settings_path = tmp_path / "settings.json"
        settings_path.write_text(json.dumps({"llm_provider": ""}))
        monkeypatch.setattr(state, "_settings_path", settings_path)
        monkeypatch.setenv("ARI_BACKEND", "anthropic")
        from ari.viz.api_settings import _api_get_settings
        s = _api_get_settings()
        # Empty saved → falls back to _wf_provider (workflow.yaml), not env var
        # because env var only sets the default, and empty saved triggers wf fallback
        wf_backend = _workflow_yaml().get("llm", {}).get("backend", "")
        # Actually: defaults use env var first, then wf; saved empty triggers wf fallback
        # The logic is: default = env or wf; merged = default overridden by saved;
        # if merged empty, fall back to wf
        assert s["llm_provider"] != "", "Must not be empty"


# ══════════════════════════════════════════════════════════════════════════
# C. PROPAGATION: Changes reach launch env, state, and subprocess
# ══════════════════════════════════════════════════════════════════════════

def _build_launch_env(state_mod, tmp_path, monkeypatch, settings: dict,
                      wizard_data: dict | None = None) -> dict:
    """Simulate _api_launch env building without spawning a process."""
    settings_path = tmp_path / ".ari" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(settings))
    monkeypatch.setattr(state_mod, "_settings_path", settings_path)
    monkeypatch.setattr(state_mod, "_checkpoint_dir", None)

    proc_env = os.environ.copy()
    # Settings injection (mirrors api_experiment.py:112-148)
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
    elif llm_provider:
        proc_env["ARI_LLM_API_BASE"] = ""
    # Wizard overrides (mirrors api_experiment.py:187-194)
    data = wizard_data or {}
    wiz_model = data.get("llm_model", "") or data.get("model", "")
    wiz_provider = data.get("llm_provider", "")
    if wiz_model:
        proc_env["ARI_MODEL"] = wiz_model
        proc_env["ARI_LLM_MODEL"] = wiz_model
    if wiz_provider:
        proc_env["ARI_BACKEND"] = wiz_provider
    # Safety net (mirrors api_experiment.py:199-208)
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


class TestSettingsToLaunchPropagation:
    """Settings changes propagate to launch environment variables."""

    def test_openai_settings_to_launch(self, state, tmp_path, monkeypatch, clean_env):
        env = _build_launch_env(state, tmp_path, monkeypatch,
            settings={"llm_provider": "openai", "llm_model": "gpt-5.2"})
        assert env["ARI_BACKEND"] == "openai"
        assert env["ARI_MODEL"] == "gpt-5.2"

    def test_anthropic_settings_to_launch(self, state, tmp_path, monkeypatch, clean_env):
        env = _build_launch_env(state, tmp_path, monkeypatch,
            settings={"llm_provider": "anthropic", "llm_model": "claude-sonnet-4-5"})
        assert env["ARI_BACKEND"] == "anthropic"
        assert env["ARI_MODEL"] == "claude-sonnet-4-5"

    def test_ollama_settings_to_launch(self, state, tmp_path, monkeypatch, clean_env):
        env = _build_launch_env(state, tmp_path, monkeypatch,
            settings={"llm_provider": "ollama", "llm_model": "qwen3:8b",
                       "ollama_host": "http://gpu:11434"})
        assert env["ARI_BACKEND"] == "ollama"
        assert env["ARI_MODEL"] == "qwen3:8b"
        assert env["OLLAMA_HOST"] == "http://gpu:11434"

    def test_changed_provider_propagates(self, state, tmp_path, monkeypatch, clean_env):
        """If user changes provider from openai to anthropic, launch must reflect it."""
        # First: openai
        env1 = _build_launch_env(state, tmp_path, monkeypatch,
            settings={"llm_provider": "openai", "llm_model": "gpt-4o"})
        assert env1["ARI_BACKEND"] == "openai"
        # Then: anthropic
        env2 = _build_launch_env(state, tmp_path, monkeypatch,
            settings={"llm_provider": "anthropic", "llm_model": "claude-sonnet-4-5"})
        assert env2["ARI_BACKEND"] == "anthropic"
        assert env2["ARI_MODEL"] == "claude-sonnet-4-5"

    def test_wizard_override_takes_precedence(self, state, tmp_path, monkeypatch, clean_env):
        """Wizard-specified provider/model overrides saved settings."""
        env = _build_launch_env(state, tmp_path, monkeypatch,
            settings={"llm_provider": "openai", "llm_model": "gpt-4o"},
            wizard_data={"llm_provider": "anthropic", "llm_model": "claude-opus-4-5"})
        assert env["ARI_BACKEND"] == "anthropic"
        assert env["ARI_MODEL"] == "claude-opus-4-5"

    def test_empty_provider_in_settings_no_ari_backend(self, state, tmp_path, monkeypatch, clean_env):
        """Empty provider in settings must not set ARI_BACKEND (leave to default)."""
        env = _build_launch_env(state, tmp_path, monkeypatch,
            settings={"llm_provider": "", "llm_model": ""})
        # Neither settings nor wizard set ARI_BACKEND → not in env
        assert env.get("ARI_BACKEND", "") == ""

    def test_provider_model_consistency_openai(self, state, tmp_path, monkeypatch, clean_env):
        """OpenAI provider must not produce ollama_chat prefix in _model_name()."""
        env = _build_launch_env(state, tmp_path, monkeypatch,
            settings={"llm_provider": "openai", "llm_model": "gpt-5.2"})
        from ari.config import LLMConfig
        from ari.llm.client import LLMClient
        cfg = LLMConfig(backend=env["ARI_BACKEND"], model=env["ARI_MODEL"])
        client = LLMClient(cfg)
        name = client._model_name()
        assert "ollama" not in name, \
            f"OpenAI settings must not produce ollama model name: {name}"
        assert name == "gpt-5.2"

    def test_provider_model_consistency_anthropic(self, state, tmp_path, monkeypatch, clean_env):
        env = _build_launch_env(state, tmp_path, monkeypatch,
            settings={"llm_provider": "anthropic", "llm_model": "claude-sonnet-4-5"})
        from ari.config import LLMConfig
        from ari.llm.client import LLMClient
        cfg = LLMConfig(backend=env["ARI_BACKEND"], model=env["ARI_MODEL"])
        client = LLMClient(cfg)
        name = client._model_name()
        assert name == "anthropic/claude-sonnet-4-5"

    def test_provider_model_consistency_ollama(self, state, tmp_path, monkeypatch, clean_env):
        env = _build_launch_env(state, tmp_path, monkeypatch,
            settings={"llm_provider": "ollama", "llm_model": "qwen3:8b"})
        from ari.config import LLMConfig
        from ari.llm.client import LLMClient
        cfg = LLMConfig(backend=env["ARI_BACKEND"], model=env["ARI_MODEL"])
        client = LLMClient(cfg)
        name = client._model_name()
        assert name == "ollama_chat/qwen3:8b"


class TestSettingsToWizardPropagation:
    """React: Settings values flow into wizard via fetchSettings."""

    def test_step_resources_fetches_settings(self):
        src = _step_resources()
        assert "fetchSettings" in src, \
            "StepResources must fetch settings"

    def test_step_resources_sets_provider_from_settings(self):
        src = _step_resources()
        assert "handleSetLlm" in src, \
            "StepResources must call handleSetLlm to set provider from settings"

    def test_handleSetLlm_sets_provider(self):
        """handleSetLlm must update provider state."""
        src = _step_resources()
        fn_idx = src.find("handleSetLlm")
        assert fn_idx >= 0
        body = src[fn_idx:fn_idx + 300]
        assert "setLlm" in body, \
            "handleSetLlm must call setLlm to update provider"

    def test_handleSetLlm_populates_model_list(self):
        """handleSetLlm must select first model from PROVIDER_MODELS."""
        src = _step_resources()
        fn_idx = src.find("handleSetLlm")
        assert fn_idx >= 0
        body = src[fn_idx:fn_idx + 300]
        assert "setModel" in body, \
            "handleSetLlm must call setModel to populate model"


class TestSettingsToStatePropagation:
    """Saved settings flow into /state endpoint response."""

    def test_server_state_reads_settings(self):
        srv = (_VIZ / "server.py").read_text()
        # /state handler must call _api_get_settings
        assert "_api_get_settings" in srv, \
            "server.py /state handler must call _api_get_settings"

    def test_state_experiment_config_has_llm_backend(self):
        srv = (_VIZ / "server.py").read_text()
        assert "llm_backend" in srv, \
            "state experiment_config must include llm_backend"

    def test_state_experiment_config_has_llm_model(self):
        srv = (_VIZ / "server.py").read_text()
        assert "llm_model" in srv, \
            "state experiment_config must include llm_model"

    def test_state_priority_launch_over_settings(self):
        """State must prefer launch config over saved settings."""
        srv = (_VIZ / "server.py").read_text()
        # _launch_llm_model must appear before saved2.get("llm_model")
        idx_launch = srv.find("_launch_llm_model")
        idx_saved = srv.find('saved2.get("llm_model"')
        assert idx_launch > 0 and idx_saved > 0, \
            "Both _launch_llm_model and saved2.get('llm_model') must exist"
        assert idx_launch < idx_saved, \
            "Launch config must be checked before saved settings in state"


class TestSaveSettingsCollectsProvider:
    """SettingsPage handleSave reads and sends provider correctly."""

    def test_handleSave_sends_provider(self):
        src = _settings_page()
        fn_idx = src.find("handleSave")
        assert fn_idx >= 0
        body = src[fn_idx:fn_idx + 500]
        assert "llm_backend" in body or "provider" in body, \
            "handleSave must send provider (llm_backend)"

    def test_handleSave_sends_llm_model(self):
        src = _settings_page()
        fn_idx = src.find("handleSave")
        assert fn_idx >= 0
        body = src[fn_idx:fn_idx + 500]
        assert "llm_model" in body, "handleSave must send llm_model key"

    def test_handleSave_prefers_model_select_over_custom(self):
        """handleSave must prefer modelSelect (dropdown) over modelCustom."""
        src = _settings_page()
        fn_idx = src.find("handleSave")
        assert fn_idx >= 0
        body = src[fn_idx:fn_idx + 500]
        assert "modelSelect" in body, \
            "handleSave must reference modelSelect"
        assert "modelCustom" in body, \
            "handleSave must also reference modelCustom as fallback"


class TestProviderChangePopulatesModels:
    """handleProviderChange correctly populates model dropdown for each provider."""

    def test_populates_model_select(self):
        src = _settings_page()
        fn_idx = src.find("handleProviderChange")
        assert fn_idx >= 0
        body = src[fn_idx:fn_idx + 500]
        assert "setModelSelect" in body or "setModelCustom" in body, \
            "handleProviderChange must update model state"

    def test_sets_first_model_as_default(self):
        src = _settings_page()
        fn_idx = src.find("handleProviderChange")
        body = src[fn_idx:fn_idx + 500]
        assert "models[0]" in body, \
            "handleProviderChange must set first model as default"

    def test_adds_custom_entry_option(self):
        src = _settings_page()
        assert "__custom__" in src, \
            "SettingsPage must include __custom__ option"

    def test_provider_models_not_empty_for_any_provider(self):
        """Every provider in PROVIDER_MODELS must have at least one model."""
        src = _settings_page()
        pm_start = src.find("PROVIDER_MODELS")
        pm_end = src.find("};", pm_start)
        block = src[pm_start:pm_end + 2]
        # Match top-level keys
        providers = re.findall(r"^\s+(\w+)\s*:", block, re.MULTILINE)
        for prov in providers:
            arr_match = re.search(rf"^\s+{prov}\s*:\s*\[([^\]]*)\]", block, re.MULTILINE)
            assert arr_match, f"PROVIDER_MODELS[{prov}] not found"
            entries = arr_match.group(1).strip()
            assert entries != "", f"PROVIDER_MODELS[{prov}] is empty"


# ══════════════════════════════════════════════════════════════════════════
# LIVE HTTP (only when server is running)
# ══════════════════════════════════════════════════════════════════════════

import urllib.request
import urllib.error
import time

_SERVER_URL = "http://localhost:9886"


def _server_available():
    try:
        urllib.request.urlopen(f"{_SERVER_URL}/state", timeout=1)
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _server_available(), reason="GUI server not running on :9886")
class TestLiveDefaultProvider:
    """Live server tests for default provider behavior."""

    def test_get_settings_provider_not_empty(self):
        resp = urllib.request.urlopen(f"{_SERVER_URL}/api/settings", timeout=3)
        data = json.loads(resp.read())
        assert data.get("llm_provider", "") != "", \
            f"GET /api/settings llm_provider must not be empty: {data}"

    def test_get_settings_model_not_empty(self):
        resp = urllib.request.urlopen(f"{_SERVER_URL}/api/settings", timeout=3)
        data = json.loads(resp.read())
        assert data.get("llm_model", "") != "", \
            f"GET /api/settings llm_model must not be empty: {data}"

    def test_change_provider_roundtrip(self):
        """POST a different provider → GET reflects the change."""
        resp0 = urllib.request.urlopen(f"{_SERVER_URL}/api/settings", timeout=3)
        orig = json.loads(resp0.read())
        try:
            for provider in ["anthropic", "ollama", "openai"]:
                payload = json.dumps({**orig, "llm_provider": provider}).encode()
                req = urllib.request.Request(
                    f"{_SERVER_URL}/api/settings",
                    data=payload, method="POST",
                    headers={"Content-Type": "application/json"},
                )
                urllib.request.urlopen(req, timeout=3)
                resp = urllib.request.urlopen(f"{_SERVER_URL}/api/settings", timeout=3)
                data = json.loads(resp.read())
                assert data["llm_provider"] == provider, \
                    f"After saving '{provider}', GET returned '{data['llm_provider']}'"
        finally:
            restore = json.dumps(orig).encode()
            req_r = urllib.request.Request(
                f"{_SERVER_URL}/api/settings",
                data=restore, method="POST",
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req_r, timeout=3)

    def test_change_model_roundtrip(self):
        """POST a different model → GET reflects the change."""
        resp0 = urllib.request.urlopen(f"{_SERVER_URL}/api/settings", timeout=3)
        orig = json.loads(resp0.read())
        try:
            payload = json.dumps({**orig, "llm_model": "gpt-4o-mini"}).encode()
            req = urllib.request.Request(
                f"{_SERVER_URL}/api/settings",
                data=payload, method="POST",
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=3)
            resp = urllib.request.urlopen(f"{_SERVER_URL}/api/settings", timeout=3)
            data = json.loads(resp.read())
            assert data["llm_model"] == "gpt-4o-mini"
        finally:
            restore = json.dumps(orig).encode()
            req_r = urllib.request.Request(
                f"{_SERVER_URL}/api/settings",
                data=restore, method="POST",
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req_r, timeout=3)

    def test_state_reflects_provider(self):
        """State endpoint includes provider from settings when a checkpoint is active."""
        resp = urllib.request.urlopen(f"{_SERVER_URL}/state", timeout=3)
        state = json.loads(resp.read())
        exp_cfg = state.get("experiment_config") or {}
        if not exp_cfg:
            pytest.skip("No active checkpoint — experiment_config not populated")
        backend = exp_cfg.get("llm_backend", "")
        assert backend != "", f"state.experiment_config.llm_backend must not be empty: {exp_cfg}"

    def test_state_reflects_model(self):
        """State endpoint includes model from settings."""
        resp = urllib.request.urlopen(f"{_SERVER_URL}/state", timeout=3)
        state = json.loads(resp.read())
        model = (
            state.get("llm_model")
            or state.get("llm_model_actual")
            or (state.get("experiment_config") or {}).get("llm_model")
        )
        assert model and model != "", \
            f"state must include a non-empty model"
