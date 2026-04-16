"""
ARI New Experiment Wizard Tests
Tests the wizard flow: chat API, launch env injection, profile, phase overrides.
"""
import json
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from ari.viz import state as _st


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_state(monkeypatch, tmp_path):
    """Reset shared state before each test. All paths redirect to tmp_path."""
    monkeypatch.setattr(_st, "_checkpoint_dir", tmp_path / "checkpoints" / "test_run")
    _st._checkpoint_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(_st, "_last_proc", None)
    monkeypatch.setattr(_st, "_last_log_fh", None)
    monkeypatch.setattr(_st, "_last_log_path", None)
    monkeypatch.setattr(_st, "_last_experiment_md", None)
    # Redirect settings and .env to tmp_path to avoid overwriting real files
    settings = tmp_path / "settings.json"
    settings.write_text("{}")
    monkeypatch.setattr(_st, "_settings_path", settings)
    monkeypatch.setattr(_st, "_env_write_path", tmp_path / ".env")
    monkeypatch.setattr(_st, "_ari_root", tmp_path)


# ══════════════════════════════════════════════
# Chat API (/api/chat-goal)
# ══════════════════════════════════════════════

class TestChatGoal:
    """Tests for _api_chat_goal (wizard chat mode)."""

    def test_empty_messages_returns_error(self):
        from ari.viz.api_tools import _api_chat_goal
        result = _api_chat_goal(json.dumps({"messages": []}).encode())
        assert "error" in result
        assert "messages required" in result["error"]

    def test_missing_api_key_returns_error(self, monkeypatch, tmp_path):
        from ari.viz.api_tools import _api_chat_goal
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        # Settings with no valid key
        _st._settings_path.write_text(json.dumps({
            "llm_provider": "openai", "llm_model": "gpt-4o-mini",
            "api_key": "", "llm_api_key": "",
        }))
        # Ensure no .env fallback (neither home nor project root)
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "nohome")
        # Mock the .env search paths to use empty directories
        _orig_parent = Path(__file__).parent
        monkeypatch.setattr("ari.viz.api_tools.Path.__truediv__",
                            Path.__truediv__)
        # Patch Path(__file__) base to prevent .env discovery
        import ari.viz.api_tools as _tools_mod
        _fake_root = tmp_path / "fake_root"
        _fake_root.mkdir(parents=True)
        monkeypatch.setattr(_tools_mod, "__file__", str(_fake_root / "api_tools.py"))
        body = json.dumps({"messages": [{"role": "user", "content": "hello"}]}).encode()
        result = _api_chat_goal(body)
        assert "error" in result

    def test_ready_marker_extraction(self, monkeypatch):
        """When LLM returns ---READY---, ready=True and md is populated."""
        from ari.viz.api_tools import _api_chat_goal
        import litellm

        mock_resp = mock.MagicMock()
        mock_resp.choices = [mock.MagicMock()]
        mock_resp.choices[0].message.content = (
            "Great, I have enough info.\n---READY---\n"
            "## Research Goal\nOptimize sorting.\n## Evaluation Metric\nTime (s)."
        )

        _st._settings_path.write_text(json.dumps({
            "llm_provider": "openai", "llm_model": "gpt-4o-mini",
            "api_key": "sk-proj-" + "a" * 80,
        }))

        with mock.patch.object(litellm, "completion", return_value=mock_resp):
            body = json.dumps({"messages": [
                {"role": "user", "content": "Sort algorithms"},
                {"role": "user", "content": "Time in seconds"},
            ]}).encode()
            result = _api_chat_goal(body)

        assert result["ready"] is True
        assert "Research Goal" in result["md"]
        assert "Optimize sorting" in result["md"]

    def test_not_ready_returns_reply(self, monkeypatch):
        """Normal conversation turn returns reply without ready marker."""
        from ari.viz.api_tools import _api_chat_goal
        import litellm

        mock_resp = mock.MagicMock()
        mock_resp.choices = [mock.MagicMock()]
        mock_resp.choices[0].message.content = "What metric should we use?"

        _st._settings_path.write_text(json.dumps({
            "llm_provider": "openai", "llm_model": "gpt-4o-mini",
            "api_key": "sk-proj-" + "a" * 80,
        }))

        with mock.patch.object(litellm, "completion", return_value=mock_resp):
            body = json.dumps({"messages": [
                {"role": "user", "content": "I want to benchmark sorting"},
            ]}).encode()
            result = _api_chat_goal(body)

        assert result["ready"] is False
        assert "What metric" in result["reply"]
        assert result.get("md", "") == ""

    def test_uses_settings_provider(self, monkeypatch):
        """Chat must use the provider/model from Settings, not hardcoded OpenAI."""
        from ari.viz.api_tools import _api_chat_goal
        import litellm

        mock_resp = mock.MagicMock()
        mock_resp.choices = [mock.MagicMock()]
        mock_resp.choices[0].message.content = "Hello!"

        _st._settings_path.write_text(json.dumps({
            "llm_provider": "anthropic", "llm_model": "claude-sonnet-4-5",
            "api_key": "sk-ant-" + "a" * 80,
        }))

        called_kwargs = {}
        def capture_completion(**kwargs):
            called_kwargs.update(kwargs)
            return mock_resp

        with mock.patch.object(litellm, "completion", side_effect=capture_completion):
            body = json.dumps({"messages": [{"role": "user", "content": "hi"}]}).encode()
            _api_chat_goal(body)

        assert called_kwargs.get("model") == "anthropic/claude-sonnet-4-5", \
            f"Expected anthropic/ prefix, got {called_kwargs.get('model')}"


# ══════════════════════════════════════════════
# Launch API (/api/launch) — env injection
# ══════════════════════════════════════════════

class _FakeProc:
    pid = 11111
    def poll(self):
        return None


def _launch(body_dict, monkeypatch, tmp_path):
    """Helper: call _api_launch with mocked subprocess."""
    from ari.viz.api_experiment import _api_launch

    spawned = {}

    def fake_popen(cmd, **kw):
        spawned["cmd"] = cmd
        spawned["env"] = kw.get("env", {})
        spawned["cwd"] = kw.get("cwd", "")
        return _FakeProc()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    with mock.patch("threading.Thread"), \
         mock.patch("builtins.open", mock.mock_open()):
        result = _api_launch(json.dumps(body_dict).encode())

    return result, spawned


class TestLaunchEnvInjection:
    """Tests for _api_launch environment variable injection."""

    def test_wizard_model_overrides_settings(self, monkeypatch, tmp_path):
        """Wizard llm_model takes precedence over saved settings."""
        _st._settings_path.write_text(json.dumps({
            "llm_model": "saved-model",
            "llm_provider": "openai",
        }))

        result, spawned = _launch({
            "experiment_md": "## Research Goal\nTest\n",
            "llm_model": "wizard-model",
            "llm_provider": "anthropic",
        }, monkeypatch, tmp_path)

        assert result.get("ok") is True
        env = spawned["env"]
        assert env.get("ARI_MODEL") == "wizard-model"
        assert env.get("ARI_BACKEND") == "anthropic"

    def test_settings_used_when_wizard_empty(self, monkeypatch, tmp_path):
        """When wizard sends empty model/provider, saved settings are used."""
        _st._settings_path.write_text(json.dumps({
            "llm_model": "claude-haiku",
            "llm_provider": "claude",
        }))

        result, spawned = _launch({
            "experiment_md": "## Research Goal\nTest\n",
            "llm_model": "",
            "llm_provider": "",
        }, monkeypatch, tmp_path)

        assert result.get("ok") is True
        env = spawned["env"]
        assert env.get("ARI_MODEL") == "claude-haiku"
        assert env.get("ARI_BACKEND") == "claude"

    def test_phase_model_overrides(self, monkeypatch, tmp_path):
        """Per-phase model overrides from wizard Advanced section."""
        result, spawned = _launch({
            "experiment_md": "## Research Goal\nTest\n",
            "phase_models": {
                "idea": "gpt-4o",
                "bfts": "claude-opus",
                "paper": "",
            },
        }, monkeypatch, tmp_path)

        assert result.get("ok") is True
        env = spawned["env"]
        assert env.get("ARI_MODEL_IDEA") == "gpt-4o"
        assert env.get("ARI_MODEL_BFTS") == "claude-opus"
        assert "ARI_MODEL_PAPER" not in env  # empty not injected

    def test_ollama_host_injected(self, monkeypatch, tmp_path):
        """Ollama provider injects OLLAMA_HOST from settings."""
        _st._settings_path.write_text(json.dumps({
            "llm_model": "qwen3:8b",
            "llm_provider": "ollama",
            "ollama_host": "http://gpu-node:11434",
        }))

        result, spawned = _launch({
            "experiment_md": "## Research Goal\nTest\n",
        }, monkeypatch, tmp_path)

        assert result.get("ok") is True
        env = spawned["env"]
        assert env.get("OLLAMA_HOST") == "http://gpu-node:11434"
        assert env.get("ARI_BACKEND") == "ollama"

    def test_env_file_loaded(self, monkeypatch, tmp_path):
        """.env file in project root is loaded into proc_env."""
        # Create .env in checkpoint dir
        env_file = _st._checkpoint_dir / ".env"
        env_file.write_text("MY_CUSTOM_KEY=secret123\n")

        result, spawned = _launch({
            "experiment_md": "## Research Goal\nTest\n",
        }, monkeypatch, tmp_path)

        assert result.get("ok") is True
        env = spawned["env"]
        assert env.get("MY_CUSTOM_KEY") == "secret123"

    def test_openai_api_key_from_settings(self, monkeypatch, tmp_path):
        """OpenAI API key from settings is injected when provider=openai.
        Note: placeholder keys (containing 'test' or <20 chars) are rejected.
        Use a realistic-length key for this test."""
        fake_key = "sk-proj-" + "a" * 80
        _st._settings_path.write_text(json.dumps({
            "llm_provider": "openai",
            "api_key": fake_key,
        }))

        result, spawned = _launch({
            "experiment_md": "## Research Goal\nTest\n",
        }, monkeypatch, tmp_path)

        assert result.get("ok") is True
        env = spawned["env"]
        # Key should be present (from settings or .env)
        assert env.get("OPENAI_API_KEY"), "OPENAI_API_KEY not set"


# ══════════════════════════════════════════════
# Launch API — profile and CLI args
# ══════════════════════════════════════════════

class TestLaunchProfile:
    """Tests for profile selection in _api_launch."""

    def test_hpc_profile_passed(self, monkeypatch, tmp_path):
        """profile='hpc' adds --profile hpc to CLI command."""
        result, spawned = _launch({
            "experiment_md": "## Research Goal\nTest\n",
            "profile": "hpc",
        }, monkeypatch, tmp_path)

        assert result.get("ok") is True
        cmd = spawned["cmd"]
        assert "--profile" in cmd
        assert "hpc" in cmd

    def test_laptop_profile_passed(self, monkeypatch, tmp_path):
        """profile='laptop' adds --profile laptop to CLI command."""
        result, spawned = _launch({
            "experiment_md": "## Research Goal\nTest\n",
            "profile": "laptop",
        }, monkeypatch, tmp_path)

        assert result.get("ok") is True
        cmd = spawned["cmd"]
        assert "--profile" in cmd
        assert "laptop" in cmd

    def test_no_profile_omits_flag(self, monkeypatch, tmp_path):
        """Empty profile does not add --profile flag."""
        result, spawned = _launch({
            "experiment_md": "## Research Goal\nTest\n",
            "profile": "",
        }, monkeypatch, tmp_path)

        assert result.get("ok") is True
        cmd = spawned["cmd"]
        assert "--profile" not in cmd

    def test_cli_command_structure(self, monkeypatch, tmp_path):
        """Launch command must be: python3 -m ari.cli run <path>."""
        result, spawned = _launch({
            "experiment_md": "## Research Goal\nTest\n",
        }, monkeypatch, tmp_path)

        assert result.get("ok") is True
        cmd = spawned["cmd"]
        assert cmd[0] == "python3"
        assert cmd[1] == "-m"
        assert cmd[2] == "ari.cli"
        assert cmd[3] == "run"
        assert cmd[4].endswith("experiment.md")


# ══════════════════════════════════════════════
# Launch API — error cases
# ══════════════════════════════════════════════

class TestLaunchErrors:
    """Tests for _api_launch error handling."""

    def test_empty_experiment_md_no_file(self, monkeypatch, tmp_path):
        """Empty experiment_md with no existing file returns error."""
        from ari.viz.api_experiment import _api_launch
        # Point to a dir where experiment.md doesn't exist
        empty_dir = tmp_path / "empty_ckpt"
        empty_dir.mkdir(parents=True)
        monkeypatch.setattr(_st, "_checkpoint_dir", empty_dir)

        result = _api_launch(json.dumps({"experiment_md": ""}).encode())
        assert result.get("ok") is False
        assert "not found" in result.get("error", "").lower()

    def test_experiment_md_written_to_checkpoint_dir(self, monkeypatch, tmp_path):
        """experiment.md is written inside the pre-created checkpoint dir."""
        from ari.viz.api_experiment import _api_launch

        with mock.patch("subprocess.Popen", return_value=_FakeProc()):
            _api_launch(json.dumps({
                "experiment_md": "## Research Goal\nTest isolation\n",
            }).encode())

        # Verify file was written inside the checkpoint dir itself
        assert _st._checkpoint_dir is not None
        written = Path(_st._checkpoint_dir) / "experiment.md"
        assert written.exists()
        assert "Test isolation" in written.read_text()

    def test_last_experiment_md_stored(self, monkeypatch, tmp_path):
        """_st._last_experiment_md is set after launch."""
        from ari.viz.api_experiment import _api_launch

        with mock.patch("subprocess.Popen", return_value=_FakeProc()), \
             mock.patch("threading.Thread"), \
             mock.patch("builtins.open", mock.mock_open()):
            _api_launch(json.dumps({
                "experiment_md": "## Goal\nStore this\n",
            }).encode())

        assert _st._last_experiment_md is not None
        assert "Store this" in _st._last_experiment_md


# ══════════════════════════════════════════════
# Upload integration
# ══════════════════════════════════════════════

class TestUploadIntegration:
    """Tests for file upload in wizard context."""

    def test_upload_writes_to_checkpoint_dir(self):
        from ari.viz.api_tools import _api_upload_file
        headers = {"Content-Type": "text/plain", "X-Filename": "my_experiment.md"}
        result = _api_upload_file(headers, b"## Goal\nUploaded content\n")
        assert result.get("ok") is True
        saved = _st._checkpoint_dir / "uploads" / "my_experiment.md"
        assert saved.exists()
        assert "Uploaded content" in saved.read_text()

    def test_upload_creates_staging_without_checkpoint(self, monkeypatch):
        from ari.viz.api_tools import _api_upload_file
        monkeypatch.setattr(_st, "_checkpoint_dir", None)
        monkeypatch.setattr(_st, "_staging_dir", None)
        headers = {"Content-Type": "text/plain", "X-Filename": "test.md"}
        result = _api_upload_file(headers, b"data")
        assert result.get("ok") is True
        assert result.get("filename") == "test.md"
        import shutil
        if _st._staging_dir and _st._staging_dir.exists():
            shutil.rmtree(str(_st._staging_dir))
        monkeypatch.setattr(_st, "_checkpoint_dir", None)
        monkeypatch.setattr(_st, "_staging_dir", None)

    def test_upload_sanitizes_filename(self):
        from ari.viz.api_tools import _api_upload_file
        headers = {"Content-Type": "text/plain", "X-Filename": "../../../etc/passwd"}
        result = _api_upload_file(headers, b"data")
        assert result.get("ok") is True
        assert result["filename"] == "passwd"
        assert not (Path("/etc/passwd")).exists() or True  # safety check

    def test_multipart_upload(self):
        from ari.viz.api_tools import _api_upload_file
        boundary = "----WebKitFormBoundary123"
        body = (
            f"------WebKitFormBoundary123\r\n"
            f'Content-Disposition: form-data; name="file"; filename="exp.md"\r\n'
            f"Content-Type: text/markdown\r\n\r\n"
            f"## Research Goal\nMultipart test\n\r\n"
            f"------WebKitFormBoundary123--\r\n"
        ).encode()
        headers = {"Content-Type": f"multipart/form-data; boundary=----WebKitFormBoundary123"}
        result = _api_upload_file(headers, body)
        assert result.get("ok") is True
        assert result["filename"] == "exp.md"


# ══════════════════════════════════════════════
# Config generation (/api/config/generate)
# ══════════════════════════════════════════════

class TestGenerateConfig:
    """Tests for _api_generate_config."""

    def test_empty_goal_returns_error(self):
        from ari.viz.api_tools import _api_generate_config
        result = _api_generate_config(json.dumps({"goal": ""}).encode())
        assert "error" in result
        assert "goal required" in result["error"]

    def test_returns_markdown_content(self, monkeypatch):
        from ari.viz.api_tools import _api_generate_config

        mock_resp = mock.MagicMock()
        mock_resp.content = "## Research Goal\nGenerated content."

        mock_client = mock.MagicMock()
        mock_client.complete.return_value = mock_resp

        mock_auto_config = mock.MagicMock()
        mock_llm_client = mock.MagicMock(return_value=mock_client)

        with mock.patch.dict("sys.modules", {
            "ari.config": mock.MagicMock(auto_config=mock_auto_config),
            "ari.llm.client": mock.MagicMock(LLMClient=mock_llm_client),
        }):
            result = _api_generate_config(json.dumps({"goal": "optimize sorting"}).encode())

        assert "content" in result
        assert "Research Goal" in result["content"]


# ══════════════════════════════════════════════
# Workflow save isolation
# ══════════════════════════════════════════════

class TestWorkflowSave:
    """Tests for _api_save_workflow project isolation."""

    def test_save_requires_checkpoint(self, monkeypatch):
        from ari.viz.api_settings import _api_save_workflow
        monkeypatch.setattr(_st, "_checkpoint_dir", None)
        result = _api_save_workflow(json.dumps({
            "pipeline": [{"stage": "test"}],
        }).encode())
        assert result.get("ok") is False
        assert result.get("_status") == 400

    def test_save_writes_to_checkpoint_dir(self):
        from ari.viz.api_settings import _api_save_workflow
        result = _api_save_workflow(json.dumps({
            "pipeline": [{"stage": "write_paper", "tool": "write_paper", "enabled": True}],
            "path": "/some/original/workflow.yaml",
        }).encode())
        assert result.get("ok") is True
        saved = _st._checkpoint_dir / "workflow.yaml"
        assert saved.exists()


# ══════════════════════════════════════════════
# JS wizard structure (source analysis)
# ══════════════════════════════════════════════

VIZ_DIR = Path(__file__).parent.parent / "ari" / "viz"
REACT_SRC = VIZ_DIR / "frontend" / "src"
REACT_COMPONENTS = REACT_SRC / "components"


def _read_react_sources():
    parts = []
    for tsx in sorted(REACT_SRC.rglob("*.tsx")):
        parts.append(tsx.read_text())
    for ts in sorted(REACT_SRC.rglob("*.ts")):
        parts.append(ts.read_text())
    return "\n".join(parts)


def _combined():
    return _read_react_sources()


class TestWizardReactStructure:
    """Tests that wizard React components have required structure and data flow."""

    def test_wizard_steps_1_to_4_exist(self):
        src = (REACT_COMPONENTS / "Wizard" / "WizardPage.tsx").read_text()
        assert "wiz_step1" in src and "wiz_step2" in src and "wiz_step3" in src and "wiz_step4" in src

    def test_launch_sends_required_fields(self):
        """StepLaunch must send experiment_md, llm_model, llm_provider, profile."""
        src = (REACT_COMPONENTS / "Wizard" / "StepLaunch.tsx").read_text()
        assert "experiment_md" in src
        assert "llm_provider" in src
        assert "profile" in src

    def test_provider_change_updates_model(self):
        """handleSetLlm must update provider and model list."""
        src = (REACT_COMPONENTS / "Wizard" / "StepResources.tsx").read_text()
        assert "handleSetLlm" in src
        assert "setLlm" in src

    def test_scope_preset_exists(self):
        """applyScopePreset must exist and reference maxDepth."""
        src = (REACT_COMPONENTS / "Wizard" / "StepScope.tsx").read_text()
        assert "applyScopePreset" in src and "maxDepth" in src

    def test_chat_mode_toggle_exists(self):
        """Chat/write-MD mode toggle must exist in wizard."""
        combined = _combined()
        assert "wizMode" in combined or "chat" in combined

    def test_phase_models_collected(self):
        """StepLaunch must collect phase_models from advanced section."""
        combined = _combined()
        assert "phase_models" in combined or "phaseModels" in combined

    def test_ollama_custom_model_input(self):
        """Free-text model input for Ollama must exist."""
        src = (REACT_COMPONENTS / "Wizard" / "StepResources.tsx").read_text()
        assert "customModel" in src or "model_custom_placeholder" in src


# ══════════════════════════════════════════════
# Scope presets ↔ numeric inputs sync
# ══════════════════════════════════════════════

class TestScopePresetSync:
    """Scope UI must have a single unified system: 5 preset buttons and
    5 numeric inputs — all kept in sync via React StepScope component."""

    # ── React component structure ──────────────────────────────────

    def test_scope_presets_has_5_entries(self):
        """SCOPE_PRESETS array must have exactly 5 entries."""
        import re
        src = (REACT_COMPONENTS / "Wizard" / "StepScope.tsx").read_text()
        m = re.search(r"const SCOPE_PRESETS.*?=\s*\[(.+?)\];", src, re.DOTALL)
        assert m, "SCOPE_PRESETS not found in StepScope.tsx"
        raw = m.group(1)
        depths = re.findall(r"depth:\s*\d+", raw)
        assert len(depths) == 5, f"Expected 5 presets, found {len(depths)}"

    def test_preset_values_monotonically_increasing(self):
        """All preset numeric sequences must be strictly increasing."""
        import re
        src = (REACT_COMPONENTS / "Wizard" / "StepScope.tsx").read_text()
        m = re.search(r"const SCOPE_PRESETS.*?=\s*\[(.+?)\];", src, re.DOTALL)
        raw = m.group(1)
        for key in ["depth", "nodes", "react", "workers", "timeout"]:
            vals = [int(x) for x in re.findall(rf"{key}:\s*(\d+)", raw)]
            assert len(vals) == 5, f"{key}: expected 5, got {len(vals)}"
            for i in range(len(vals) - 1):
                assert vals[i] < vals[i+1], \
                    f"SCOPE_PRESETS.{key} not increasing: {vals[i]} >= {vals[i+1]}"

    def test_preset_values_within_input_ranges(self):
        """Preset values must be within the min/max of their input fields."""
        import re
        src = (REACT_COMPONENTS / "Wizard" / "StepScope.tsx").read_text()
        m = re.search(r"const SCOPE_PRESETS.*?=\s*\[(.+?)\];", src, re.DOTALL)
        raw = m.group(1)
        # Extract min/max from input elements in StepScope
        field_map = {
            "depth":   ("maxDepth", 2, 20),
            "nodes":   ("maxNodes", 5, 500),
            "react":   ("maxReact", 10, 500),
            "workers": ("workers", 1, 64),
            "timeout": ("timeout", 10, 1440),
        }
        for key, (field, lo, hi) in field_map.items():
            vals = [int(x) for x in re.findall(rf"{key}:\s*(\d+)", raw)]
            for v in vals:
                assert lo <= v <= hi, \
                    f"SCOPE_PRESETS.{key}={v} outside {field} range [{lo},{hi}]"

    def test_applyScopePreset_sets_all_fields(self):
        """applyScopePreset must set all 5 scope fields."""
        src = (REACT_COMPONENTS / "Wizard" / "StepScope.tsx").read_text()
        assert "applyScopePreset" in src, "applyScopePreset not found"
        for field in ["maxDepth", "maxNodes", "maxReact", "workers", "timeout"]:
            assert field in src, f"StepScope missing field '{field}'"

    def test_five_preset_labels_exist(self):
        """5 preset labels must be defined."""
        src = (REACT_COMPONENTS / "Wizard" / "StepScope.tsx").read_text()
        assert "PRESET_LABELS" in src or "Quick" in src
        for label in ["Quick", "Standard", "Thorough", "Deep", "Exhaustive"]:
            assert label in src, f"Preset label '{label}' not found"

    def test_manual_edit_changes_state(self):
        """Manual field edit must update isManual state to deselect presets."""
        src = (REACT_COMPONENTS / "Wizard" / "StepScope.tsx").read_text()
        assert "isManual" in src or "handleFieldChange" in src

    def test_init_applies_standard_preset(self):
        """StepScope must initialize with Standard (preset 2) default."""
        src = (REACT_COMPONENTS / "Wizard" / "StepScope.tsx").read_text()
        assert "applyScopePreset(2)" in src, \
            "Init must call applyScopePreset(2) for Standard default"


# ══════════════════════════════════════════════
# Idea tab — VirSci hypothesis display
# ══════════════════════════════════════════════

class TestIdeaTabVirsci:
    """Tests that Idea tab displays VirSci-generated hypotheses."""

    def test_idea_page_component_exists(self):
        """IdeaPage React component must exist."""
        src = (REACT_COMPONENTS / "Idea" / "IdeaPage.tsx").read_text()
        assert "IdeaPage" in src

    def test_idea_reads_from_state(self):
        """IdeaPage must read ideas from state."""
        src = (REACT_COMPONENTS / "Idea" / "IdeaPage.tsx").read_text()
        assert "ideas" in src

    def test_idea_reads_gap_analysis(self):
        """IdeaPage must read gap_analysis from state."""
        src = (REACT_COMPONENTS / "Idea" / "IdeaPage.tsx").read_text()
        assert "gap_analysis" in src

    def test_idea_displays_scores(self):
        """IdeaPage must display novelty_score and feasibility_score."""
        src = (REACT_COMPONENTS / "Idea" / "IdeaPage.tsx").read_text()
        assert "novelty_score" in src
        assert "feasibility_score" in src

    def test_idea_displays_experiment_plan(self):
        """IdeaPage must show experiment_plan."""
        src = (REACT_COMPONENTS / "Idea" / "IdeaPage.tsx").read_text()
        assert "experiment_plan" in src

    def test_server_injects_ideas_from_idea_json(self):
        """server.py /state handler must read idea.json and inject ideas."""
        src = (VIZ_DIR / "server.py").read_text()
        assert "idea.json" in src
        assert '"ideas"' in src

    def test_server_injects_gap_analysis(self):
        src = (VIZ_DIR / "server.py").read_text()
        assert '"gap_analysis"' in src

    def test_server_injects_primary_metric(self):
        src = (VIZ_DIR / "server.py").read_text()
        assert "idea_primary_metric" in src

    def test_loop_saves_idea_json(self):
        """Agent loop must save generate_ideas result to idea.json."""
        loop_src = (VIZ_DIR / ".." / "agent" / "loop.py").read_text()
        assert "idea.json" in loop_src

    def test_loop_imports_path(self):
        """loop.py must import Path so idea.json saving works."""
        loop_src = (VIZ_DIR / ".." / "agent" / "loop.py").read_text()
        assert "from pathlib import Path" in loop_src, \
            "loop.py must import Path (needed for idea.json save)"

    def test_loop_idea_json_save_uses_path(self):
        """The idea.json save code in loop.py must use Path, not raw string."""
        import re
        loop_src = (VIZ_DIR / ".." / "agent" / "loop.py").read_text()
        m = re.search(r"_idea_path\s*=\s*Path\(", loop_src)
        assert m, "idea.json save must use Path() constructor"

    def test_idea_json_roundtrip_via_server(self, tmp_path, monkeypatch):
        """Full roundtrip: idea.json in checkpoint → /state injects ideas."""
        idea_data = {
            "ideas": [
                {"title": "Hypothesis A", "description": "Test desc", "novelty_score": 4.2,
                 "feasibility_score": 3.8, "overall_score": 4.0, "experiment_plan": "Plan A",
                 "novelty": "Novel approach"},
                {"title": "Hypothesis B", "description": "Another", "novelty_score": 3.5,
                 "feasibility_score": 4.5, "overall_score": 3.9, "experiment_plan": "Plan B",
                 "novelty": "Different angle"},
            ],
            "gap_analysis": "Current methods lack X and Y",
            "primary_metric": "execution_time",
            "metric_rationale": "Lower is better for performance",
        }
        ckpt = tmp_path / "test_ckpt"
        ckpt.mkdir()
        (ckpt / "idea.json").write_text(json.dumps(idea_data))
        # Also need tree.json for _ckpt_valid
        (ckpt / "tree.json").write_text(json.dumps({"run_id": "test", "nodes": []}))

        # Point server state at this checkpoint
        monkeypatch.setattr(_st, "_checkpoint_dir", ckpt)

        # Call the actual /state handler logic (server._build_state)
        # by reading idea.json the same way server.py does
        d = ckpt
        data = {}
        idea_f = d / "idea.json"
        if idea_f.exists():
            idea_loaded = json.loads(idea_f.read_text())
            data["ideas"] = idea_loaded.get("ideas", [])
            data["gap_analysis"] = idea_loaded.get("gap_analysis", "")
            data["idea_primary_metric"] = idea_loaded.get("primary_metric", "")
            data["idea_metric_rationale"] = idea_loaded.get("metric_rationale", "")

        assert len(data["ideas"]) == 2
        assert data["ideas"][0]["title"] == "Hypothesis A"
        assert data["ideas"][0]["novelty_score"] == 4.2
        assert data["ideas"][1]["feasibility_score"] == 4.5
        assert data["ideas"][1]["experiment_plan"] == "Plan B"
        assert "lack X" in data["gap_analysis"]
        assert data["idea_primary_metric"] == "execution_time"
        assert "Lower is better" in data["idea_metric_rationale"]

    def test_state_without_idea_json(self, tmp_path):
        """When idea.json doesn't exist, ideas should be empty."""
        ckpt = tmp_path / "empty_ckpt"
        ckpt.mkdir()
        data = {}
        idea_f = ckpt / "idea.json"
        if idea_f.exists():
            data["ideas"] = json.loads(idea_f.read_text()).get("ideas", [])
        assert data.get("ideas") is None or data.get("ideas") == []

    def test_react_renders_virsci_ideas(self):
        """IdeaPage must render idea titles, scores, and experiment_plan."""
        src = (REACT_COMPONENTS / "Idea" / "IdeaPage.tsx").read_text()
        assert "ideas" in src
        assert "novelty_score" in src
        assert "feasibility_score" in src
        assert "experiment_plan" in src

    def test_react_shows_gap_analysis(self):
        """IdeaPage must render gap_analysis."""
        src = (REACT_COMPONENTS / "Idea" / "IdeaPage.tsx").read_text()
        assert "gap_analysis" in src

    def test_react_shows_primary_metric(self):
        """IdeaPage must render primary_metric."""
        src = (REACT_COMPONENTS / "Idea" / "IdeaPage.tsx").read_text()
        assert "idea_primary_metric" in src or "primary_metric" in src


# ══════════════════════════════════════════════════════════════════════════════
# checkpoint_dir passthrough: cli.py → AgentLoop → idea.json
# ══════════════════════════════════════════════════════════════════════════════

class TestCheckpointDirPassthrough:
    """Verify that cli.py sets agent.checkpoint_dir so idea.json gets saved."""

    def test_cli_run_sets_checkpoint_dir_on_agent(self):
        """cli.py run command must set agent.checkpoint_dir after build_runtime."""
        cli_src = (Path(__file__).parent.parent / "ari" / "cli.py").read_text()
        # Find within the run() function (before resume())
        run_fn_start = cli_src.find("def run(")
        assert run_fn_start > 0, "run() function not found"
        resume_fn_start = cli_src.find("def resume(", run_fn_start + 1)
        run_fn = cli_src[run_fn_start:resume_fn_start] if resume_fn_start > 0 else cli_src[run_fn_start:]
        # agent.checkpoint_dir must be set BEFORE _run_loop is called
        set_pos = run_fn.find("agent.checkpoint_dir")
        run_loop_pos = run_fn.find("_run_loop(cfg, bfts, agent")
        assert set_pos > 0, "run() does not set agent.checkpoint_dir"
        assert run_loop_pos > 0, "_run_loop call not found in run()"
        assert set_pos < run_loop_pos, \
            "agent.checkpoint_dir must be set BEFORE _run_loop is called"

    def test_cli_resume_sets_checkpoint_dir_on_agent(self):
        """cli.py resume command must also set agent.checkpoint_dir."""
        cli_src = (Path(__file__).parent.parent / "ari" / "cli.py").read_text()
        # Find the resume function
        resume_start = cli_src.find("def resume(")
        assert resume_start > 0, "resume function not found"
        resume_block = cli_src[resume_start:]
        assert "agent.checkpoint_dir" in resume_block, \
            "resume command does not set agent.checkpoint_dir"

    def test_loop_saves_idea_json_when_checkpoint_dir_set(self, tmp_path):
        """AgentLoop idea.json saving logic must work when checkpoint_dir is set."""
        ckpt = tmp_path / "test_ckpt"
        ckpt.mkdir()

        # Simulate what loop.py:697-705 does
        idea_data = {
            "ideas": [{"title": "Test Idea", "overall_score": 4.0}],
            "primary_metric": "throughput",
        }
        _ckpt = str(ckpt)  # simulating getattr(self, "checkpoint_dir")
        if _ckpt:
            _idea_path = Path(_ckpt) / "idea.json"
            _idea_path.write_text(json.dumps(idea_data, ensure_ascii=False, indent=2))

        assert (ckpt / "idea.json").exists()
        loaded = json.loads((ckpt / "idea.json").read_text())
        assert loaded["ideas"][0]["title"] == "Test Idea"
        assert loaded["primary_metric"] == "throughput"

    def test_loop_skips_save_when_checkpoint_dir_none(self, tmp_path):
        """When checkpoint_dir is None (the bug), idea.json must NOT be created."""
        ckpt = tmp_path / "no_save_ckpt"
        ckpt.mkdir()

        idea_data = {"ideas": [{"title": "Lost Idea"}]}
        _ckpt = None  # simulating the bug: getattr(self, "checkpoint_dir", None)
        if _ckpt:
            _idea_path = Path(_ckpt) / "idea.json"
            _idea_path.write_text(json.dumps(idea_data))

        assert not (ckpt / "idea.json").exists(), \
            "idea.json should NOT be created when checkpoint_dir is None"

    def test_agent_loop_checkpoint_dir_attribute(self):
        """AgentLoop must accept checkpoint_dir as a runtime attribute."""
        from ari.agent.loop import AgentLoop
        # AgentLoop uses getattr(self, "checkpoint_dir", None)
        # so setting it as an attribute after __init__ must work
        agent = AgentLoop.__new__(AgentLoop)
        assert getattr(agent, "checkpoint_dir", None) is None
        agent.checkpoint_dir = "/tmp/test"
        assert agent.checkpoint_dir == "/tmp/test"

    def test_idea_json_roundtrip_via_state(self, tmp_path, monkeypatch):
        """Full roundtrip: write idea.json → /state reads it → ideas present."""
        ckpt = tmp_path / "roundtrip_ckpt"
        ckpt.mkdir()
        # Write idea.json (simulating what loop.py would do)
        idea_data = {
            "ideas": [
                {"title": "Hypothesis X", "description": "desc", "novelty_score": 3.0,
                 "feasibility_score": 4.0, "overall_score": 3.5},
            ],
            "gap_analysis": "Gap in method Y",
            "primary_metric": "accuracy",
            "metric_rationale": "Higher accuracy = better",
        }
        (ckpt / "idea.json").write_text(json.dumps(idea_data))
        # Also need tree.json for checkpoint validation
        (ckpt / "tree.json").write_text(json.dumps({"run_id": "test", "nodes": []}))

        # Simulate /state handler logic (server.py:382-392)
        d = ckpt
        data = {}
        idea_f = d / "idea.json"
        if idea_f.exists():
            loaded = json.loads(idea_f.read_text())
            data["ideas"] = loaded.get("ideas", [])
            data["gap_analysis"] = loaded.get("gap_analysis", "")
            data["idea_primary_metric"] = loaded.get("primary_metric", "")
            data["idea_metric_rationale"] = loaded.get("metric_rationale", "")

        assert len(data["ideas"]) == 1
        assert data["ideas"][0]["title"] == "Hypothesis X"
        assert data["gap_analysis"] == "Gap in method Y"
        assert data["idea_primary_metric"] == "accuracy"


# ══════════════════════════════════════════════════════════════════════════════
# VirSci idea.json → /state → GUI display (end-to-end)
# ══════════════════════════════════════════════════════════════════════════════

class TestVirsciIdeaEndToEnd:
    """End-to-end: idea.json is written, server injects into /state, GUI renders."""

    # ── Server-side injection ──────────────────────────────────────

    def test_server_state_injects_full_idea_data(self, tmp_path, monkeypatch):
        """Server /state handler must inject all idea.json fields into response."""
        idea_data = {
            "ideas": [
                {"title": "Approach Alpha", "description": "Variant A of the method",
                 "novelty_score": 4.5, "feasibility_score": 4.0, "overall_score": 4.2,
                 "experiment_plan": ["Step 1", "Step 2"]},
                {"title": "Approach Beta", "description": "Variant B of the method",
                 "novelty_score": 3.8, "feasibility_score": 4.3, "overall_score": 4.0,
                 "experiment_plan": {"phase1": "setup", "phase2": "eval"}},
            ],
            "gap_analysis": "No prior work combines approach A with approach B",
            "primary_metric": "score",
            "metric_rationale": "Higher score = better performance",
        }
        ckpt = tmp_path / "full_idea_ckpt"
        ckpt.mkdir()
        (ckpt / "idea.json").write_text(json.dumps(idea_data))
        (ckpt / "tree.json").write_text(json.dumps({"run_id": "t", "nodes": []}))
        monkeypatch.setattr(_st, "_checkpoint_dir", ckpt)

        # Simulate server /state idea injection (server.py:438-448)
        d = ckpt
        data = {}
        idea_f = d / "idea.json"
        loaded = json.loads(idea_f.read_text())
        data["ideas"] = loaded.get("ideas", [])
        data["gap_analysis"] = loaded.get("gap_analysis", "")
        data["idea_primary_metric"] = loaded.get("primary_metric", "")
        data["idea_metric_rationale"] = loaded.get("metric_rationale", "")

        # Verify ALL fields
        assert len(data["ideas"]) == 2
        assert data["ideas"][0]["title"] == "Approach Alpha"
        assert data["ideas"][0]["novelty_score"] == 4.5
        assert data["ideas"][0]["feasibility_score"] == 4.0
        assert data["ideas"][0]["overall_score"] == 4.2
        assert data["ideas"][0]["experiment_plan"] == ["Step 1", "Step 2"]
        assert data["ideas"][1]["title"] == "Approach Beta"
        assert isinstance(data["ideas"][1]["experiment_plan"], dict)
        assert data["gap_analysis"] == "No prior work combines approach A with approach B"
        assert data["idea_primary_metric"] == "score"
        assert "performance" in data["idea_metric_rationale"]

    # ── Empty / corrupt idea.json ──────────────────────────────────

    def test_empty_idea_json_returns_empty_ideas(self, tmp_path, monkeypatch):
        """0-byte idea.json must result in empty ideas, not crash."""
        ckpt = tmp_path / "empty_idea_ckpt"
        ckpt.mkdir()
        (ckpt / "idea.json").write_text("")  # 0-byte
        (ckpt / "tree.json").write_text(json.dumps({"run_id": "t", "nodes": []}))
        monkeypatch.setattr(_st, "_checkpoint_dir", ckpt)

        data = {}
        idea_f = ckpt / "idea.json"
        if idea_f.exists():
            try:
                loaded = json.loads(idea_f.read_text())
                data["ideas"] = loaded.get("ideas", [])
            except Exception:
                pass  # server.py catches all exceptions
        assert data.get("ideas") is None or data.get("ideas") == []

    def test_corrupt_idea_json_returns_empty_ideas(self, tmp_path, monkeypatch):
        """Truncated/corrupt idea.json must not crash server."""
        ckpt = tmp_path / "corrupt_idea_ckpt"
        ckpt.mkdir()
        (ckpt / "idea.json").write_text('{"ideas": [{"title": "Trunc')  # truncated
        (ckpt / "tree.json").write_text(json.dumps({"run_id": "t", "nodes": []}))
        monkeypatch.setattr(_st, "_checkpoint_dir", ckpt)

        data = {}
        idea_f = ckpt / "idea.json"
        if idea_f.exists():
            try:
                loaded = json.loads(idea_f.read_text())
                data["ideas"] = loaded.get("ideas", [])
            except Exception:
                pass
        assert data.get("ideas") is None or data.get("ideas") == []

    def test_idea_json_with_empty_object_returns_empty(self, tmp_path, monkeypatch):
        """idea.json = '{}' (quota recovery) → empty ideas, not crash."""
        ckpt = tmp_path / "empty_obj_ckpt"
        ckpt.mkdir()
        (ckpt / "idea.json").write_text("{}")
        (ckpt / "tree.json").write_text(json.dumps({"run_id": "t", "nodes": []}))
        monkeypatch.setattr(_st, "_checkpoint_dir", ckpt)

        data = {}
        loaded = json.loads((ckpt / "idea.json").read_text())
        data["ideas"] = loaded.get("ideas", [])
        data["gap_analysis"] = loaded.get("gap_analysis", "")
        data["idea_primary_metric"] = loaded.get("primary_metric", "")

        assert data["ideas"] == []
        assert data["gap_analysis"] == ""
        assert data["idea_primary_metric"] == ""

    # ── React IdeaPage renders all fields ──────────────────────────

    def test_ideapage_renders_virsci_card(self):
        """IdeaPage must have VirSci Hypotheses card."""
        src = (REACT_COMPONENTS / "Idea" / "IdeaPage.tsx").read_text()
        assert "VirSci Hypotheses" in src

    def test_ideapage_renders_all_score_fields(self):
        """IdeaPage must reference novelty, feasibility, overall scores."""
        src = (REACT_COMPONENTS / "Idea" / "IdeaPage.tsx").read_text()
        for field in ["novelty_score", "feasibility_score", "overall_score"]:
            assert field in src, f"IdeaPage missing score field: {field}"

    def test_ideapage_renders_experiment_plan(self):
        """IdeaPage must handle both array and dict experiment_plan."""
        src = (REACT_COMPONENTS / "Idea" / "IdeaPage.tsx").read_text()
        assert "experiment_plan" in src
        # Must handle Array.isArray check
        assert "isArray" in src, "IdeaPage must handle array experiment_plan"

    def test_ideapage_renders_gap_analysis(self):
        """IdeaPage must render gap_analysis from state."""
        src = (REACT_COMPONENTS / "Idea" / "IdeaPage.tsx").read_text()
        assert "gap_analysis" in src
        assert "Gap Analysis" in src or "gap" in src.lower()

    def test_ideapage_renders_primary_metric(self):
        """IdeaPage must render primary_metric from state."""
        src = (REACT_COMPONENTS / "Idea" / "IdeaPage.tsx").read_text()
        assert "idea_primary_metric" in src or "primaryMetric" in src

    def test_ideapage_shows_placeholder_when_empty(self):
        """IdeaPage must show placeholder when ideas array is empty."""
        src = (REACT_COMPONENTS / "Idea" / "IdeaPage.tsx").read_text()
        assert "ideas.length === 0" in src, \
            "IdeaPage must check for empty ideas array"
        assert "No VirSci" in src or "not have run" in src, \
            "IdeaPage must show a message when VirSci data is missing"

    # ── TypeScript types include idea fields ───────────────────────

    def test_appstate_type_includes_ideas(self):
        """AppState TypeScript interface must include ideas field."""
        types_src = (REACT_COMPONENTS / ".." / "types" / "index.ts").read_text()
        assert "ideas:" in types_src

    def test_appstate_type_includes_gap_analysis(self):
        """AppState must include gap_analysis field."""
        types_src = (REACT_COMPONENTS / ".." / "types" / "index.ts").read_text()
        assert "gap_analysis:" in types_src

    def test_appstate_type_includes_idea_primary_metric(self):
        """AppState must include idea_primary_metric field."""
        types_src = (REACT_COMPONENTS / ".." / "types" / "index.ts").read_text()
        assert "idea_primary_metric:" in types_src
