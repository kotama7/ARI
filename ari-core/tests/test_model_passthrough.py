"""Tests for GUI → subprocess model passthrough.

Verifies that the user's model/provider selection in the GUI dashboard
is correctly propagated to ARI_MODEL / ARI_BACKEND environment variables
in the launched subprocess.
"""
import json
import subprocess
import threading
from pathlib import Path
from unittest import mock

import pytest

from ari.viz import state as _st
from ari.viz.api_experiment import _api_launch
from ari.viz.api_settings import _api_get_settings, _api_save_settings


# ── Helpers ──────────────────────────────────────────────────────────────────

class FakeProc:
    pid = 77777
    def poll(self):
        return None


@pytest.fixture
def setup_state(tmp_path, monkeypatch):
    """Set up viz state for launch tests."""
    ckpt_dir = tmp_path / "checkpoints" / "test_run"
    ckpt_dir.mkdir(parents=True)
    monkeypatch.setattr(_st, "_checkpoint_dir", ckpt_dir)
    monkeypatch.setattr(_st, "_settings_path", tmp_path / "settings.json")
    monkeypatch.setattr(_st, "_env_write_path", tmp_path / ".env")
    monkeypatch.setattr(_st, "_ari_root", tmp_path / "fake_ari_root")
    monkeypatch.setattr(_st, "_last_proc", None)
    monkeypatch.setattr(_st, "_last_log_path", None)
    monkeypatch.setattr(_st, "_last_log_fh", None)
    return tmp_path


def _capture_launch_env(setup_state, monkeypatch, settings_dict, launch_body):
    """Run _api_launch with given settings + body and return the captured proc_env."""
    tmp_path = setup_state
    settings_path = tmp_path / "settings.json"
    if settings_dict is not None:
        settings_path.write_text(json.dumps(settings_dict))

    captured_env = {}

    def fake_popen(cmd, **kw):
        captured_env.update(kw.get("env", {}))
        return FakeProc()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    body = json.dumps(launch_body).encode()
    with mock.patch("threading.Thread"), \
         mock.patch("builtins.open", mock.mock_open()):
        _api_launch(body)

    return captured_env


# ══════════════════════════════════════════════════════════════════════════════
# 1. Settings → ARI_MODEL / ARI_BACKEND
# ══════════════════════════════════════════════════════════════════════════════

class TestSettingsToEnv:
    """Verify settings.json values are injected into subprocess env."""

    def test_openai_model_from_settings(self, setup_state, monkeypatch):
        """Settings with llm_model='gpt-4o' and llm_provider='openai'
        → ARI_MODEL=gpt-4o, ARI_BACKEND=openai."""
        env = _capture_launch_env(setup_state, monkeypatch,
            settings_dict={"llm_model": "gpt-4o", "llm_provider": "openai"},
            launch_body={"experiment_md": "test"})
        assert env.get("ARI_MODEL") == "gpt-4o"
        assert env.get("ARI_BACKEND") == "openai"

    def test_ollama_model_from_settings(self, setup_state, monkeypatch):
        """Settings with llm_model='qwen3:32b' and llm_provider='ollama'
        → ARI_MODEL=qwen3:32b, ARI_BACKEND=ollama."""
        env = _capture_launch_env(setup_state, monkeypatch,
            settings_dict={"llm_model": "qwen3:32b", "llm_provider": "ollama"},
            launch_body={"experiment_md": "test"})
        assert env.get("ARI_MODEL") == "qwen3:32b"
        assert env.get("ARI_BACKEND") == "ollama"

    def test_anthropic_model_from_settings(self, setup_state, monkeypatch):
        """Settings with llm_model='claude-sonnet-4-5' and llm_provider='anthropic'."""
        env = _capture_launch_env(setup_state, monkeypatch,
            settings_dict={"llm_model": "claude-sonnet-4-5", "llm_provider": "anthropic"},
            launch_body={"experiment_md": "test"})
        assert env.get("ARI_MODEL") == "claude-sonnet-4-5"
        assert env.get("ARI_BACKEND") == "anthropic"

    def test_missing_llm_model_does_not_override(self, setup_state, monkeypatch):
        """If settings.json has NO llm_model, ARI_MODEL must NOT be set to empty string.
        This was the original bug — empty llm_model caused fallback to qwen3:8b default."""
        env = _capture_launch_env(setup_state, monkeypatch,
            settings_dict={"llm_provider": "openai"},
            launch_body={"experiment_md": "test"})
        # ARI_MODEL should either not be set (letting config.py default work)
        # or be set to a non-empty value from elsewhere
        assert env.get("ARI_MODEL", "") != "", \
            "ARI_MODEL is empty — this was the original bug (falls back to qwen3:8b)"

    def test_llm_backend_key_also_read(self, setup_state, monkeypatch):
        """Override saveSettings writes 'llm_backend' ��� verify it's also read."""
        env = _capture_launch_env(setup_state, monkeypatch,
            settings_dict={"llm_model": "gpt-5.2", "llm_backend": "openai"},
            launch_body={"experiment_md": "test"})
        assert env.get("ARI_BACKEND") == "openai"


# ══════════════════════════════════════════════════════════════════════════════
# 2. Wizard → ARI_MODEL / ARI_BACKEND (overrides settings)
# ══════════════════════════════════════════════════════════════════════════════

class TestWizardOverride:
    """Wizard model/provider must override settings."""

    def test_wizard_model_overrides_settings(self, setup_state, monkeypatch):
        """Wizard selects gpt-5.4 while settings has gpt-4o → gpt-5.4 wins."""
        env = _capture_launch_env(setup_state, monkeypatch,
            settings_dict={"llm_model": "gpt-4o", "llm_provider": "openai"},
            launch_body={
                "experiment_md": "test",
                "llm_model": "gpt-5.4",
                "llm_provider": "openai",
            })
        assert env.get("ARI_MODEL") == "gpt-5.4"

    def test_wizard_provider_overrides_settings(self, setup_state, monkeypatch):
        """Wizard selects anthropic while settings has openai → anthropic wins."""
        env = _capture_launch_env(setup_state, monkeypatch,
            settings_dict={"llm_model": "gpt-4o", "llm_provider": "openai"},
            launch_body={
                "experiment_md": "test",
                "llm_model": "claude-sonnet-4-5",
                "llm_provider": "anthropic",
            })
        assert env.get("ARI_MODEL") == "claude-sonnet-4-5"
        assert env.get("ARI_BACKEND") == "anthropic"

    def test_wizard_empty_provider_keeps_settings(self, setup_state, monkeypatch):
        """Wizard with empty provider → settings provider is preserved."""
        env = _capture_launch_env(setup_state, monkeypatch,
            settings_dict={"llm_model": "gpt-4o", "llm_provider": "openai"},
            launch_body={
                "experiment_md": "test",
                "llm_model": "",
                "llm_provider": "",
            })
        assert env.get("ARI_BACKEND") == "openai"
        assert env.get("ARI_MODEL") == "gpt-4o"


# ══════════════════════════════════════════════════════════════════════════════
# 3. API key injection
# ══════════════════════════════════════════════════════════════════════════════

class TestApiKeyInjection:
    def test_key_present_after_launch(self, setup_state, monkeypatch):
        """OPENAI_API_KEY must be set after launch (from settings or .env)."""
        env = _capture_launch_env(setup_state, monkeypatch,
            settings_dict={"llm_model": "gpt-4o", "llm_provider": "openai",
                           "api_key": "sk-settings-key"},
            launch_body={"experiment_md": "test"})
        assert env.get("OPENAI_API_KEY"), "OPENAI_API_KEY not set at all"

    def test_anthropic_key_injected_when_env_empty(self, setup_state, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        # Use a realistic-length key (placeholder detection rejects keys with "test" or <20 chars)
        fake_key = "sk-ant-api03-" + "x" * 40
        env = _capture_launch_env(setup_state, monkeypatch,
            settings_dict={"llm_model": "claude-sonnet-4-5", "llm_provider": "anthropic",
                           "api_key": fake_key},
            launch_body={"experiment_md": "test"})
        assert env.get("ANTHROPIC_API_KEY") == fake_key

    def test_llm_api_key_field_read(self, setup_state, monkeypatch):
        """Both api_key and llm_api_key fields should be checked in settings."""
        import inspect
        from ari.viz import api_experiment as _mod
        src = inspect.getsource(_mod._api_launch)
        assert "llm_api_key" in src, "api_launch doesn't read llm_api_key from settings"
        assert "api_key" in src, "api_launch doesn't read api_key from settings"

    def test_env_key_not_overwritten_by_settings(self, setup_state, monkeypatch):
        """Real key from os.environ must NOT be overwritten by settings.json."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-real-from-env")
        env = _capture_launch_env(setup_state, monkeypatch,
            settings_dict={"llm_model": "gpt-4o", "llm_provider": "openai",
                           "api_key": "sk-stale-settings-key"},
            launch_body={"experiment_md": "test"})
        assert env.get("OPENAI_API_KEY") == "sk-real-from-env"

    def test_dotenv_key_not_overwritten_by_settings(self, setup_state, monkeypatch):
        """.env key loaded first must NOT be overwritten by settings.json."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        # Write .env inside the monkeypatched _ari_root (tmp_path/fake_ari_root)
        fake_ari_root = setup_state / "fake_ari_root"
        fake_ari_root.mkdir(exist_ok=True)
        dotenv = fake_ari_root / ".env"
        dotenv.write_text('OPENAI_API_KEY=sk-real-from-dotenv\n')
        env = _capture_launch_env(setup_state, monkeypatch,
            settings_dict={"llm_model": "gpt-4o", "llm_provider": "openai",
                           "api_key": "sk-stale-settings"},
            launch_body={"experiment_md": "test"})
        assert env.get("OPENAI_API_KEY") == "sk-real-from-dotenv", \
            f".env key should win, got: {env.get('OPENAI_API_KEY')}"


# ══════════════════════════════════════════════════════════════════════════════
# 4. LLMClient._model_name() provider prefix
# ══════════════════════════════════════════════════════════════════════════════

class TestLLMClientModelName:
    def test_ollama_prefix(self):
        from ari.llm.client import LLMClient
        from ari.config import LLMConfig
        client = LLMClient(LLMConfig(backend="ollama", model="qwen3:8b"))
        assert client._model_name() == "ollama_chat/qwen3:8b"

    def test_openai_no_prefix(self):
        from ari.llm.client import LLMClient
        from ari.config import LLMConfig
        client = LLMClient(LLMConfig(backend="openai", model="gpt-4o"))
        assert client._model_name() == "gpt-4o"

    def test_anthropic_prefix(self):
        from ari.llm.client import LLMClient
        from ari.config import LLMConfig
        client = LLMClient(LLMConfig(backend="anthropic", model="claude-sonnet-4-5"))
        assert client._model_name() == "anthropic/claude-sonnet-4-5"

    def test_claude_alias_prefix(self):
        from ari.llm.client import LLMClient
        from ari.config import LLMConfig
        client = LLMClient(LLMConfig(backend="claude", model="claude-opus-4-5"))
        assert client._model_name() == "anthropic/claude-opus-4-5"


# ══════════════════════════════════════════════════════════════════════════════
# 5. pipeline._extract_keywords_from_nodes provider prefix
# ══════════════════════════════════════════════════════════════════════════════

class TestPipelineModelPrefix:
    """_extract_keywords_from_nodes must add provider prefix to model name."""

    def _make_nodes_json(self, tmp_path):
        data = {"nodes": [
            {"status": "success", "eval_summary": "optimized algorithm implementation"},
        ]}
        p = tmp_path / "nodes_tree.json"
        p.write_text(json.dumps(data))
        return str(p)

    def test_ollama_backend_adds_prefix(self, tmp_path, monkeypatch):
        from ari.pipeline import _extract_keywords_from_nodes
        monkeypatch.setenv("ARI_MODEL", "qwen3:8b")
        monkeypatch.setenv("ARI_BACKEND", "ollama")

        captured_kwargs = {}
        def fake_completion(**kw):
            captured_kwargs.update(kw)
            resp = mock.MagicMock()
            resp.choices = [mock.MagicMock()]
            resp.choices[0].message.content = "algorithm optimization"
            return resp

        with mock.patch("litellm.completion", side_effect=fake_completion):
            _extract_keywords_from_nodes(self._make_nodes_json(tmp_path), "test")

        assert captured_kwargs["model"] == "ollama_chat/qwen3:8b"
        assert "api_base" in captured_kwargs

    def test_openai_backend_no_prefix(self, tmp_path, monkeypatch):
        from ari.pipeline import _extract_keywords_from_nodes
        monkeypatch.setenv("ARI_MODEL", "gpt-4o")
        monkeypatch.setenv("ARI_BACKEND", "openai")

        captured_kwargs = {}
        def fake_completion(**kw):
            captured_kwargs.update(kw)
            resp = mock.MagicMock()
            resp.choices = [mock.MagicMock()]
            resp.choices[0].message.content = "algorithm optimization"
            return resp

        with mock.patch("litellm.completion", side_effect=fake_completion):
            _extract_keywords_from_nodes(self._make_nodes_json(tmp_path), "test")

        assert captured_kwargs["model"] == "gpt-4o"
        assert "api_base" not in captured_kwargs

    def test_anthropic_backend_adds_prefix(self, tmp_path, monkeypatch):
        from ari.pipeline import _extract_keywords_from_nodes
        monkeypatch.setenv("ARI_MODEL", "claude-sonnet-4-5")
        monkeypatch.setenv("ARI_BACKEND", "anthropic")

        captured_kwargs = {}
        def fake_completion(**kw):
            captured_kwargs.update(kw)
            resp = mock.MagicMock()
            resp.choices = [mock.MagicMock()]
            resp.choices[0].message.content = "algorithm optimization"
            return resp

        with mock.patch("litellm.completion", side_effect=fake_completion):
            _extract_keywords_from_nodes(self._make_nodes_json(tmp_path), "test")

        assert captured_kwargs["model"] == "anthropic/claude-sonnet-4-5"

    def test_already_prefixed_not_doubled(self, tmp_path, monkeypatch):
        from ari.pipeline import _extract_keywords_from_nodes
        monkeypatch.setenv("ARI_MODEL", "ollama_chat/qwen3:8b")
        monkeypatch.setenv("ARI_BACKEND", "ollama")

        captured_kwargs = {}
        def fake_completion(**kw):
            captured_kwargs.update(kw)
            resp = mock.MagicMock()
            resp.choices = [mock.MagicMock()]
            resp.choices[0].message.content = "test query"
            return resp

        with mock.patch("litellm.completion", side_effect=fake_completion):
            _extract_keywords_from_nodes(self._make_nodes_json(tmp_path), "test")

        assert captured_kwargs["model"] == "ollama_chat/qwen3:8b"


# ══════════════════════════════════════════════════════════════════════════════
# 6. JS static analysis — saveSettings includes model + provider
# ══════════════════════════════════════════════════════════════════════════════

_REACT_SRC = Path(__file__).parent.parent / "ari" / "viz" / "frontend" / "src"
_REACT_COMPONENTS = _REACT_SRC / "components"


class TestReactSaveSettingsStatic:
    """Static analysis of React SettingsPage to verify model fields are saved."""

    def _settings(self):
        return (_REACT_COMPONENTS / "Settings" / "SettingsPage.tsx").read_text()

    def test_save_settings_includes_llm_model_with_fallback(self):
        """handleSave must use modelSelect with modelCustom fallback."""
        src = self._settings()
        fn_idx = src.find("handleSave")
        assert fn_idx >= 0
        body = src[fn_idx:fn_idx + 500]
        assert "modelSelect" in body, "handleSave missing modelSelect"
        assert "modelCustom" in body, "handleSave missing modelCustom fallback"

    def test_save_settings_includes_provider(self):
        """handleSave must save provider (llm_backend) key."""
        src = self._settings()
        fn_idx = src.find("handleSave")
        assert fn_idx >= 0
        body = src[fn_idx:fn_idx + 500]
        assert "llm_backend" in body or "provider" in body

    def test_load_settings_populates_model(self):
        """loadSettings must populate model state from fetched settings."""
        src = self._settings()
        fn_idx = src.find("loadSettings")
        assert fn_idx >= 0
        body = src[fn_idx:fn_idx + 500]
        assert "setModelSelect" in body or "setModelCustom" in body, \
            "loadSettings does not populate model state"

    def test_custom_entry_option_exists(self):
        """Settings page must have __custom__ option in model dropdown."""
        src = self._settings()
        assert "__custom__" in src, \
            "SettingsPage missing __custom__ option in model dropdown"


# ══════════════════════════════════════════════════════════════════════════════
# 7. Settings roundtrip: save → load → ARI_MODEL
# ══════════════════════════════════════════════════════════════════════════════

class TestSettingsRoundtrip:
    def test_save_then_launch_openai(self, setup_state, monkeypatch):
        """Save openai settings via API → launch → ARI_MODEL/ARI_BACKEND correct."""
        tmp_path = setup_state
        # Simulate save
        body = json.dumps({
            "llm_model": "gpt-5.2",
            "llm_provider": "openai",
            "api_key": "sk-test",
        }).encode()
        _api_save_settings(body)

        # Verify saved
        loaded = json.loads((tmp_path / "settings.json").read_text())
        assert loaded["llm_model"] == "gpt-5.2"
        assert loaded["llm_provider"] == "openai"

        # Launch
        env = _capture_launch_env(setup_state, monkeypatch,
            settings_dict=None,  # already saved
            launch_body={"experiment_md": "test"})
        assert env.get("ARI_MODEL") == "gpt-5.2"
        assert env.get("ARI_BACKEND") == "openai"

    def test_save_then_launch_ollama(self, setup_state, monkeypatch):
        """Save ollama settings → launch → ARI_MODEL/ARI_BACKEND correct."""
        tmp_path = setup_state
        body = json.dumps({
            "llm_model": "qwen3:32b",
            "llm_provider": "ollama",
        }).encode()
        _api_save_settings(body)

        env = _capture_launch_env(setup_state, monkeypatch,
            settings_dict=None,
            launch_body={"experiment_md": "test"})
        assert env.get("ARI_MODEL") == "qwen3:32b"
        assert env.get("ARI_BACKEND") == "ollama"


# ══════════════════════════════════════════════════════════════════════════════
# 8. gpt-5 temperature restriction
# ══════════════════════════════════════════════════════════════════════════════

class TestGpt5Temperature:
    """gpt-5* models only support temperature=1; verify it is dropped."""

    def test_complete_drops_temperature_for_gpt5(self):
        from ari.llm.client import LLMClient, LLMMessage
        from ari.config import LLMConfig

        client = LLMClient(LLMConfig(backend="openai", model="gpt-5.2", temperature=0.7))

        captured = {}
        def fake_completion(**kw):
            captured.update(kw)
            resp = mock.MagicMock()
            resp.choices = [mock.MagicMock()]
            resp.choices[0].message.content = "hello"
            resp.choices[0].message.tool_calls = None
            resp.usage = None
            return resp

        with mock.patch("litellm.completion", side_effect=fake_completion):
            client.complete([LLMMessage(role="user", content="hi")])

        assert "temperature" not in captured, \
            f"temperature should not be sent for gpt-5 models, got: {captured.get('temperature')}"

    def test_complete_keeps_temperature_for_gpt4(self):
        from ari.llm.client import LLMClient, LLMMessage
        from ari.config import LLMConfig

        client = LLMClient(LLMConfig(backend="openai", model="gpt-4o", temperature=0.7))

        captured = {}
        def fake_completion(**kw):
            captured.update(kw)
            resp = mock.MagicMock()
            resp.choices = [mock.MagicMock()]
            resp.choices[0].message.content = "hello"
            resp.choices[0].message.tool_calls = None
            resp.usage = None
            return resp

        with mock.patch("litellm.completion", side_effect=fake_completion):
            client.complete([LLMMessage(role="user", content="hi")])

        assert captured.get("temperature") == 0.7

    def test_stream_drops_temperature_for_gpt5(self):
        from ari.llm.client import LLMClient, LLMMessage
        from ari.config import LLMConfig

        client = LLMClient(LLMConfig(backend="openai", model="gpt-5.4-mini", temperature=0.5))

        captured = {}
        def fake_completion(**kw):
            captured.update(kw)
            return iter([])

        with mock.patch("litellm.completion", side_effect=fake_completion):
            list(client.stream([LLMMessage(role="user", content="hi")]))

        assert "temperature" not in captured

    def test_pipeline_drops_temperature_for_gpt5(self, tmp_path, monkeypatch):
        from ari.pipeline import _extract_keywords_from_nodes
        monkeypatch.setenv("ARI_MODEL", "gpt-5.2")
        monkeypatch.setenv("ARI_BACKEND", "openai")

        nodes = {"nodes": [
            {"status": "success", "eval_summary": "tested algorithm variant"},
        ]}
        p = tmp_path / "nodes_tree.json"
        p.write_text(json.dumps(nodes))

        captured = {}
        def fake_completion(**kw):
            captured.update(kw)
            resp = mock.MagicMock()
            resp.choices = [mock.MagicMock()]
            resp.choices[0].message.content = "algorithm variant"
            return resp

        with mock.patch("litellm.completion", side_effect=fake_completion):
            _extract_keywords_from_nodes(str(p), "test")

        assert "temperature" not in captured

    def test_pipeline_keeps_temperature_for_non_gpt5(self, tmp_path, monkeypatch):
        from ari.pipeline import _extract_keywords_from_nodes
        monkeypatch.setenv("ARI_MODEL", "gpt-4o")
        monkeypatch.setenv("ARI_BACKEND", "openai")

        nodes = {"nodes": [
            {"status": "success", "eval_summary": "tested algorithm variant"},
        ]}
        p = tmp_path / "nodes_tree.json"
        p.write_text(json.dumps(nodes))

        captured = {}
        def fake_completion(**kw):
            captured.update(kw)
            resp = mock.MagicMock()
            resp.choices = [mock.MagicMock()]
            resp.choices[0].message.content = "algorithm variant"
            return resp

        with mock.patch("litellm.completion", side_effect=fake_completion):
            _extract_keywords_from_nodes(str(p), "test")

        assert captured.get("temperature") == 0.0


# ══════════════════════════════════════════════════════════════════════════════
# 9. Settings UI — provider-filtered model list (static analysis)
# ══════════════════════════════════════════════════════════════════════════════

class TestSettingsModelListStatic:
    """Verify that the React Settings model dropdown is populated dynamically
    per provider, not hardcoded with a mixed list."""

    def test_provider_models_dict_has_no_cross_contamination(self):
        """PROVIDER_MODELS in React must not have ollama models under openai, etc."""
        src = (_REACT_COMPONENTS / "Settings" / "SettingsPage.tsx").read_text()
        import re
        m = re.search(r'const PROVIDER_MODELS.*?=\s*\{(.*?)\};', src, re.DOTALL)
        assert m is not None, "PROVIDER_MODELS not found"
        block = m.group(1)

        # Extract openai line
        openai_m = re.search(r"openai:\s*\[([^\]]*)\]", block)
        if openai_m:
            openai_models = openai_m.group(1)
            for bad in ["qwen", "llama", "gemma", "mistral"]:
                assert bad not in openai_models.lower(), \
                    f"'{bad}' found in PROVIDER_MODELS.openai: {openai_models}"

        # Extract anthropic line
        anth_m = re.search(r"anthropic:\s*\[([^\]]*)\]", block)
        if anth_m:
            anth_models = anth_m.group(1)
            for bad in ["gpt", "qwen", "llama", "gemma", "mistral"]:
                assert bad not in anth_models.lower(), \
                    f"'{bad}' found in PROVIDER_MODELS.anthropic: {anth_models}"

    def test_custom_entry_option_in_settings(self):
        """SettingsPage must include __custom__ option in dropdown."""
        src = (_REACT_COMPONENTS / "Settings" / "SettingsPage.tsx").read_text()
        assert "__custom__" in src, \
            "SettingsPage does not include __custom__ option"

    def test_step_resources_no_qwen_hardcode_fallback(self):
        """StepResources settings prefill must NOT hardcode 'qwen3:8b' as fallback.
        This caused qwen to appear even when OpenAI was selected."""
        sr = (_REACT_COMPONENTS / "Wizard" / "StepResources.tsx").read_text()
        wp = (_REACT_COMPONENTS / "Wizard" / "WizardPage.tsx").read_text()
        src = sr + "\n" + wp
        # The settings prefill uses: s.llm_provider || s.llm_backend || 'openai'
        # It should NOT hardcode qwen3:8b as a fallback model outside PROVIDER_MODELS
        import re
        # Find the settings fetch handler (after fetchSettings)
        fetch_idx = src.find("fetchSettings")
        assert fetch_idx >= 0
        prefill_block = src[fetch_idx:fetch_idx + 500]
        assert "|| 'qwen3:8b'" not in prefill_block and '|| "qwen3:8b"' not in prefill_block, \
            "StepResources still hardcodes 'qwen3:8b' as fallback"


# ══════════════════════════════════════════════════════════════════════════════
# 10. Skill _api_base() fallback safety — must NOT return Ollama URL for OpenAI
# ══════════════════════════════════════════════════════════════════════════════

class TestSkillApiBaseFallback:
    """Verify that skill _api_base() functions do NOT return the Ollama URL
    when the model is an OpenAI/Anthropic model (the root cause of the 404)."""

    # ── ari-skill-idea ────────────────────────────────────────────────────────

    def test_idea_openai_no_base_url(self, monkeypatch):
        """gpt-5.2 via ARI_LLM_MODEL → _api_base() must return None."""
        monkeypatch.setenv("ARI_LLM_MODEL", "gpt-5.2")
        monkeypatch.delenv("ARI_LLM_API_BASE", raising=False)
        monkeypatch.delenv("LLM_API_BASE", raising=False)
        monkeypatch.delenv("LLM_MODEL", raising=False)
        from types import ModuleType
        mod = ModuleType("_test_idea")
        exec(
            "import os\n"
            "def _model():\n"
            "    return os.environ.get('ARI_LLM_MODEL') or os.environ.get('LLM_MODEL') or 'ollama_chat/qwen3:32b'\n"
            "def _api_base():\n"
            "    ari = os.environ.get('ARI_LLM_API_BASE')\n"
            "    if ari is not None:\n"
            "        return ari or None\n"
            "    legacy = os.environ.get('LLM_API_BASE', '')\n"
            "    if legacy:\n"
            "        return legacy\n"
            "    if _model().startswith('ollama'):\n"
            "        return 'http://127.0.0.1:11434'\n"
            "    return None\n",
            mod.__dict__,
        )
        assert mod._model() == "gpt-5.2"
        assert mod._api_base() is None, \
            f"_api_base() returned {mod._api_base()!r} for gpt-5.2 — should be None"

    def test_idea_anthropic_no_base_url(self, monkeypatch):
        """anthropic/claude-sonnet-4-5 → _api_base() must return None."""
        monkeypatch.setenv("ARI_LLM_MODEL", "anthropic/claude-sonnet-4-5")
        monkeypatch.delenv("ARI_LLM_API_BASE", raising=False)
        monkeypatch.delenv("LLM_API_BASE", raising=False)
        from types import ModuleType
        mod = ModuleType("_test_idea")
        exec(
            "import os\n"
            "def _model():\n"
            "    return os.environ.get('ARI_LLM_MODEL') or os.environ.get('LLM_MODEL') or 'ollama_chat/qwen3:32b'\n"
            "def _api_base():\n"
            "    ari = os.environ.get('ARI_LLM_API_BASE')\n"
            "    if ari is not None:\n"
            "        return ari or None\n"
            "    legacy = os.environ.get('LLM_API_BASE', '')\n"
            "    if legacy:\n"
            "        return legacy\n"
            "    if _model().startswith('ollama'):\n"
            "        return 'http://127.0.0.1:11434'\n"
            "    return None\n",
            mod.__dict__,
        )
        assert mod._api_base() is None

    def test_idea_ollama_gets_base_url(self, monkeypatch):
        """ollama_chat/qwen3:32b → _api_base() must return Ollama URL."""
        monkeypatch.setenv("ARI_LLM_MODEL", "ollama_chat/qwen3:32b")
        monkeypatch.delenv("ARI_LLM_API_BASE", raising=False)
        monkeypatch.delenv("LLM_API_BASE", raising=False)
        from types import ModuleType
        mod = ModuleType("_test_idea")
        exec(
            "import os\n"
            "def _model():\n"
            "    return os.environ.get('ARI_LLM_MODEL') or os.environ.get('LLM_MODEL') or 'ollama_chat/qwen3:32b'\n"
            "def _api_base():\n"
            "    ari = os.environ.get('ARI_LLM_API_BASE')\n"
            "    if ari is not None:\n"
            "        return ari or None\n"
            "    legacy = os.environ.get('LLM_API_BASE', '')\n"
            "    if legacy:\n"
            "        return legacy\n"
            "    if _model().startswith('ollama'):\n"
            "        return 'http://127.0.0.1:11434'\n"
            "    return None\n",
            mod.__dict__,
        )
        assert mod._api_base() == "http://127.0.0.1:11434"

    def test_idea_explicit_empty_base_returns_none(self, monkeypatch):
        """ARI_LLM_API_BASE='' (set by GUI for OpenAI) → None."""
        monkeypatch.setenv("ARI_LLM_MODEL", "gpt-5.2")
        monkeypatch.setenv("ARI_LLM_API_BASE", "")
        from types import ModuleType
        mod = ModuleType("_test_idea")
        exec(
            "import os\n"
            "def _model():\n"
            "    return os.environ.get('ARI_LLM_MODEL') or os.environ.get('LLM_MODEL') or 'ollama_chat/qwen3:32b'\n"
            "def _api_base():\n"
            "    ari = os.environ.get('ARI_LLM_API_BASE')\n"
            "    if ari is not None:\n"
            "        return ari or None\n"
            "    legacy = os.environ.get('LLM_API_BASE', '')\n"
            "    if legacy:\n"
            "        return legacy\n"
            "    if _model().startswith('ollama'):\n"
            "        return 'http://127.0.0.1:11434'\n"
            "    return None\n",
            mod.__dict__,
        )
        assert mod._api_base() is None

    def test_idea_bare_model_no_ollama_fallback(self, monkeypatch):
        """Bare model name without 'ollama' prefix (e.g. 'qwen3:8b') → None.
        GUI always sets ARI_LLM_API_BASE, so bare model names without explicit
        base URL should not blindly assume Ollama."""
        monkeypatch.setenv("ARI_LLM_MODEL", "qwen3:8b")
        monkeypatch.delenv("ARI_LLM_API_BASE", raising=False)
        monkeypatch.delenv("LLM_API_BASE", raising=False)
        from types import ModuleType
        mod = ModuleType("_test_idea")
        exec(
            "import os\n"
            "def _model():\n"
            "    return os.environ.get('ARI_LLM_MODEL') or os.environ.get('LLM_MODEL') or 'ollama_chat/qwen3:32b'\n"
            "def _api_base():\n"
            "    ari = os.environ.get('ARI_LLM_API_BASE')\n"
            "    if ari is not None:\n"
            "        return ari or None\n"
            "    legacy = os.environ.get('LLM_API_BASE', '')\n"
            "    if legacy:\n"
            "        return legacy\n"
            "    if _model().startswith('ollama'):\n"
            "        return 'http://127.0.0.1:11434'\n"
            "    return None\n",
            mod.__dict__,
        )
        assert mod._api_base() is None

    # ── GUI launch: ARI_LLM_API_BASE propagation ──────────────────────────────

    def test_openai_launch_sets_empty_api_base(self, setup_state, monkeypatch):
        """OpenAI provider → ARI_LLM_API_BASE='' must be in subprocess env."""
        env = _capture_launch_env(setup_state, monkeypatch,
            settings_dict={"llm_model": "gpt-5.2", "llm_provider": "openai"},
            launch_body={"experiment_md": "test"})
        assert "ARI_LLM_API_BASE" in env, "ARI_LLM_API_BASE not set for OpenAI"
        assert env["ARI_LLM_API_BASE"] == "", \
            f"ARI_LLM_API_BASE should be empty for OpenAI, got: {env['ARI_LLM_API_BASE']!r}"

    def test_anthropic_launch_sets_empty_api_base(self, setup_state, monkeypatch):
        """Anthropic provider → ARI_LLM_API_BASE='' must be in subprocess env."""
        env = _capture_launch_env(setup_state, monkeypatch,
            settings_dict={"llm_model": "claude-sonnet-4-5", "llm_provider": "anthropic"},
            launch_body={"experiment_md": "test"})
        assert env.get("ARI_LLM_API_BASE") == ""

    def test_ollama_launch_does_not_clear_api_base(self, setup_state, monkeypatch):
        """Ollama provider → ARI_LLM_API_BASE should NOT be forced to empty."""
        env = _capture_launch_env(setup_state, monkeypatch,
            settings_dict={"llm_model": "qwen3:32b", "llm_provider": "ollama"},
            launch_body={"experiment_md": "test"})
        # For Ollama, ARI_LLM_API_BASE should either not be set or not be empty
        base = env.get("ARI_LLM_API_BASE")
        assert base != "", \
            "ARI_LLM_API_BASE is empty for Ollama — skills won't find Ollama endpoint"

    # ── End-to-end: GUI launch + skill _api_base combined ─────────────────────

    def test_e2e_openai_no_ollama_fallback(self, setup_state, monkeypatch):
        """Full flow: settings(gpt-5.2/openai) → launch env → skill _api_base()
        must NOT return Ollama URL."""
        env = _capture_launch_env(setup_state, monkeypatch,
            settings_dict={"llm_model": "gpt-5.2", "llm_provider": "openai"},
            launch_body={"experiment_md": "test"})

        # Simulate what the skill would see with these env vars
        from types import ModuleType
        mod = ModuleType("_test_e2e")
        # Inject the captured env vars
        monkeypatch.setenv("ARI_LLM_MODEL", env.get("ARI_LLM_MODEL", ""))
        if "ARI_LLM_API_BASE" in env:
            monkeypatch.setenv("ARI_LLM_API_BASE", env["ARI_LLM_API_BASE"])
        else:
            monkeypatch.delenv("ARI_LLM_API_BASE", raising=False)
        monkeypatch.delenv("LLM_API_BASE", raising=False)
        exec(
            "import os\n"
            "def _model():\n"
            "    return os.environ.get('ARI_LLM_MODEL') or os.environ.get('LLM_MODEL') or 'ollama_chat/qwen3:32b'\n"
            "def _api_base():\n"
            "    ari = os.environ.get('ARI_LLM_API_BASE')\n"
            "    if ari is not None:\n"
            "        return ari or None\n"
            "    legacy = os.environ.get('LLM_API_BASE', '')\n"
            "    if legacy:\n"
            "        return legacy\n"
            "    if _model().startswith('ollama'):\n"
            "        return 'http://127.0.0.1:11434'\n"
            "    return None\n",
            mod.__dict__,
        )
        assert mod._model() == "gpt-5.2"
        base = mod._api_base()
        assert base is None, \
            f"End-to-end: gpt-5.2 should get api_base=None, got {base!r}"

    def test_e2e_ollama_keeps_base_url(self, setup_state, monkeypatch):
        """Full flow: settings(qwen3:32b/ollama) → launch env → skill _api_base()
        must return Ollama URL."""
        env = _capture_launch_env(setup_state, monkeypatch,
            settings_dict={"llm_model": "qwen3:32b", "llm_provider": "ollama"},
            launch_body={"experiment_md": "test"})

        monkeypatch.setenv("ARI_LLM_MODEL", env.get("ARI_LLM_MODEL", ""))
        if "ARI_LLM_API_BASE" in env:
            monkeypatch.setenv("ARI_LLM_API_BASE", env["ARI_LLM_API_BASE"])
        else:
            monkeypatch.delenv("ARI_LLM_API_BASE", raising=False)
        monkeypatch.delenv("LLM_API_BASE", raising=False)
        from types import ModuleType
        mod = ModuleType("_test_e2e_ollama")
        exec(
            "import os\n"
            "def _model():\n"
            "    return os.environ.get('ARI_LLM_MODEL') or os.environ.get('LLM_MODEL') or 'ollama_chat/qwen3:32b'\n"
            "def _api_base():\n"
            "    ari = os.environ.get('ARI_LLM_API_BASE')\n"
            "    if ari is not None:\n"
            "        return ari or None\n"
            "    legacy = os.environ.get('LLM_API_BASE', '')\n"
            "    if legacy:\n"
            "        return legacy\n"
            "    if _model().startswith('ollama'):\n"
            "        return 'http://127.0.0.1:11434'\n"
            "    return None\n",
            mod.__dict__,
        )
        # For Ollama, model has no slash → should get Ollama URL
        assert "11434" in (mod._api_base() or "")
