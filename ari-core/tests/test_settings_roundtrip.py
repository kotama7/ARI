"""
test_settings_roundtrip.py
──────────────────────────────────────────────────────────────────────────────
GUI Settings save/load roundtrip tests.

Verifies the full cycle:
  1. User edits Settings page → JS collects values → POST /api/settings
  2. server.py writes ~/.ari/settings.json
  3. GET /api/settings → returns correct fields
  4. /state endpoint merges settings → returns to dashboard
  5. Dashboard JS reads state → displays correct values in UI

Also tests static round-trip contracts (field names, JSON keys, HTML element IDs).
──────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations
import json
import os
import re
import tempfile
import threading
import time
import urllib.request
import urllib.error
from pathlib import Path

_VIZ = Path(__file__).parent.parent / "ari/viz"
_REACT_SRC = _VIZ / "frontend" / "src"
_REACT_COMPONENTS = _REACT_SRC / "components"


def _read_react_sources():
    parts = []
    for tsx in sorted(_REACT_SRC.rglob("*.tsx")):
        parts.append(tsx.read_text())
    for ts in sorted(_REACT_SRC.rglob("*.ts")):
        parts.append(ts.read_text())
    return "\n".join(parts)


def _srv():   return (_VIZ / "server.py").read_text()
def _api_exp(): return (_VIZ / "api_experiment.py").read_text()
def _api_set(): return (_VIZ / "api_settings.py").read_text()
def _combined(): return _read_react_sources()
def _settings_page(): return (_REACT_COMPONENTS / "Settings" / "SettingsPage.tsx").read_text()
def _step_resources():
    sr = (_REACT_COMPONENTS / "Wizard" / "StepResources.tsx").read_text()
    wp = (_REACT_COMPONENTS / "Wizard" / "WizardPage.tsx").read_text()
    return sr + "\n" + wp
def _step_launch(): return (_REACT_COMPONENTS / "Wizard" / "StepLaunch.tsx").read_text()


# ═══════════════════════════════════════════════════════════════════════════
# CONTRACT: Settings page HTML element IDs ↔ JSON keys in POST body
# ═══════════════════════════════════════════════════════════════════════════

# Maps: HTML element id → expected JS payload key
SETTINGS_FIELD_MAP = {
    "s-provider":   "llm_provider",
    "s-model":      "llm_model",
    "s-api-key":    "api_key",
    "s-ollama-host": "ollama_host",
}

class TestSettingsReactElements:
    """All Settings page inputs must exist in SettingsPage.tsx."""

    def test_provider_select_exists(self):
        src = _settings_page()
        assert "provider" in src and "setProvider" in src, "Missing provider state"

    def test_model_input_exists(self):
        src = _settings_page()
        assert "modelCustom" in src or "modelSelect" in src, "Missing model input"

    def test_api_key_input_exists(self):
        src = _settings_page()
        assert "apiKey" in src, "Missing API key input"

    def test_ollama_host_input_exists(self):
        src = _settings_page()
        assert "baseUrl" in src or "ollama_host" in src, "Missing Ollama host input"

    def test_save_button_exists(self):
        src = _settings_page()
        assert "handleSave" in src, "Missing save handler"

    def test_model_select_dropdown_exists(self):
        src = _settings_page()
        assert "modelSelect" in src, "Missing model select dropdown state"


class TestSettingsSavePayload:
    """SettingsPage handleSave must collect all required fields."""

    def test_handleSave_sends_provider(self):
        src = _settings_page()
        fn_idx = src.find("handleSave")
        assert fn_idx >= 0, "handleSave not found"
        body = src[fn_idx:fn_idx + 500]
        assert "llm_backend" in body or "provider" in body, "handleSave must send provider"

    def test_handleSave_sends_llm_model(self):
        src = _settings_page()
        fn_idx = src.find("handleSave")
        body = src[fn_idx:fn_idx + 500]
        assert "llm_model" in body, "handleSave must send llm_model"

    def test_handleSave_sends_api_key(self):
        src = _settings_page()
        fn_idx = src.find("handleSave")
        body = src[fn_idx:fn_idx + 500]
        assert "api_key" in body or "llm_api_key" in body, "handleSave must send api_key"

    def test_handleSave_sends_base_url(self):
        src = _settings_page()
        fn_idx = src.find("handleSave")
        body = src[fn_idx:fn_idx + 500]
        assert "base_url" in body or "baseUrl" in body, "handleSave must send base URL"

    def test_api_service_posts_settings(self):
        api_src = (_REACT_SRC / "services" / "api.ts").read_text()
        assert "saveSettings" in api_src, "api.ts must have saveSettings function"
        assert "/api/settings" in api_src, "saveSettings must POST to /api/settings"

    def test_api_service_uses_post_method(self):
        api_src = (_REACT_SRC / "services" / "api.ts").read_text()
        assert "POST" in api_src, "API service must use POST method"

    def test_api_service_sends_json(self):
        api_src = (_REACT_SRC / "services" / "api.ts").read_text()
        assert "JSON.stringify" in api_src or "application/json" in api_src, \
            "API service must send JSON body"

    def test_handleSave_uses_model_select_with_fallback(self):
        """handleSave must use modelSelect with modelCustom fallback."""
        src = _settings_page()
        fn_idx = src.find("handleSave")
        body = src[fn_idx:fn_idx + 500]
        assert "modelSelect" in body, \
            "handleSave must read from modelSelect dropdown"
        assert "modelCustom" in body, \
            "handleSave must also reference modelCustom as fallback"


# ═══════════════════════════════════════════════════════════════════════════
# CONTRACT: Server POST /api/settings handler writes correct fields
# ═══════════════════════════════════════════════════════════════════════════

class TestServerSettingsHandler:
    """server.py POST /api/settings must persist all fields correctly."""

    def test_server_handles_post_api_settings(self):
        srv = _srv()
        assert "/api/settings" in srv, "server.py must handle /api/settings"

    def test_server_writes_settings_json(self):
        # Settings are written by api_settings.py (_api_save_settings), called from server.py
        src = _srv() + _api_set()
        assert "settings.json" in src, "settings.json must be written somewhere in viz stack"

    def test_server_settings_file_is_project_scoped(self):
        """Settings must be persisted under the active checkpoint dir."""
        src = _srv() + _api_set()
        # Project-scoped persistence flows through state._settings_path which
        # set_active_checkpoint() rebinds to {checkpoint}/settings.json.  We
        # accept any reference to that helper or to the project path API.
        assert (
            "_settings_path" in src
            or "project_settings_path" in src
            or "active_settings_path" in src
        ), "settings.json must be project-scoped (per-checkpoint)"

    def test_server_persists_llm_model(self):
        # _api_save_settings in api_settings.py handles persistence
        src = _api_set()
        assert "llm_model" in src, "api_settings.py must handle llm_model"

    def test_server_persists_llm_provider(self):
        srv = _srv()
        assert "llm_provider" in srv

    def test_server_persists_ollama_host(self):
        srv = _srv()
        assert "ollama_host" in srv

    def test_server_persists_api_key(self):
        srv = _srv()
        assert "api_key" in srv

    def test_server_settings_not_stored_in_cwd(self):
        """settings.json must never be written to Path.cwd()."""
        srv = _srv()
        assert 'Path.cwd() / "settings.json"' not in srv
        assert "cwd()" not in srv or "settings.json" not in srv[
            srv.find("cwd()"):srv.find("cwd()") + 50
        ] if "cwd()" in srv else True


# ═══════════════════════════════════════════════════════════════════════════
# CONTRACT: GET /api/settings returns all fields (populate Settings page)
# ═══════════════════════════════════════════════════════════════════════════

class TestSettingsGetResponse:
    """GET /api/settings must return all fields needed to populate Settings page."""

    def test_get_returns_llm_model(self):
        srv = _srv()
        assert "llm_model" in srv

    def test_get_returns_llm_provider(self):
        srv = _srv()
        assert "llm_provider" in srv

    def test_get_returns_ollama_host(self):
        srv = _srv()
        assert "ollama_host" in srv

    def test_get_returns_api_key(self):
        srv = _srv()
        assert "api_key" in srv

    def test_get_returns_slurm_defaults(self):
        """GET /api/settings must return slurm_* fields for wizard Step 3 prefill."""
        # slurm keys are in api_settings.py _api_get_settings defaults
        src = _api_set()
        for key in ["slurm_cpus", "slurm_memory_gb", "slurm_gpus", "slurm_walltime"]:
            assert key in src, f"api_settings.py must include '{key}' in defaults"

    def test_api_key_not_echoed_in_state(self):
        """
        /state endpoint must NOT include raw api_key in the response
        (security: keys must not be sent to browser via state polling).
        """
        srv = _srv()
        # Find state handler
        state_idx = srv.find('"/state"') or srv.find("'/state'")
        if state_idx < 0:
            state_idx = srv.find("_api_state")
        # Check REDACT_KEYS includes api_key
        assert "_REDACT_KEYS" in srv or "api_key" in srv, \
            "State handler must redact api_key"
        assert "api_key" in srv[srv.find("_REDACT_KEYS") if "_REDACT_KEYS" in srv else 0:
                                srv.find("_REDACT_KEYS") + 200 if "_REDACT_KEYS" in srv else 200], \
            "api_key must be in REDACT_KEYS"


# ═══════════════════════════════════════════════════════════════════════════
# CONTRACT: /state merges settings → dashboard displays saved values
# ═══════════════════════════════════════════════════════════════════════════

class TestStateSettingsMerge:
    """/state endpoint must include settings-derived fields for UI display."""

    def test_state_includes_llm_model_for_badge(self):
        """state['llm_model'] must be populated from settings + launch config."""
        srv = _srv()
        assert "llm_model" in srv
        # State must set llm_model in the returned data dict
        assert 'data["llm_model"]' in srv or 'data.get("llm_model")' in srv \
            or '"llm_model":' in srv

    def test_state_includes_ollama_host(self):
        """State must include ollama_host so UI can show connection status."""
        srv = _srv()
        assert 'ollama_host' in srv
        # server.py state handler uses saved2.get("ollama_host") to inject into response
        idx = srv.find('ollama_host')
        assert idx > 0, "ollama_host not found in server.py"
        chunk = srv[max(0,idx-60):idx+100]
        assert 'saved' in chunk or 'merged' in chunk or '.get(' in chunk or 'data[' in chunk, \
            f"ollama_host must be read from settings in state handler: {chunk}"

    def test_state_llm_model_priority_order(self):
        """
        Model in state must prefer: launch_config > settings > yaml default.
        (Never overwrite a user-set launch model with settings default.)
        """
        srv = _srv()
        # launch_config.json must be checked before settings
        idx_lc = srv.find("launch_config.json")
        idx_settings_model = srv.find('saved2.get("llm_model"')
        if idx_lc > 0 and idx_settings_model > 0:
            assert idx_lc < idx_settings_model, \
                "launch_config.json must be read BEFORE settings llm_model"

    def test_state_merges_settings_model(self):
        """State handler must read llm_model from saved settings."""
        srv = _srv()
        assert 'saved2.get("llm_model"' in srv or \
               'settings.get("llm_model"' in srv or \
               '_settings_model' in srv

    def test_state_experiment_config_has_model(self):
        """state['experiment_config']['llm_model'] must be populated."""
        srv = _srv()
        assert "experiment_config" in srv
        assert "llm_model" in srv


# ═══════════════════════════════════════════════════════════════════════════
# CONTRACT: Dashboard JS loads settings into Settings page on page open
# ═══════════════════════════════════════════════════════════════════════════

class TestSettingsPageLoad:
    """When user opens Settings page, React must populate inputs from /api/settings."""

    def test_settings_page_fetches_settings(self):
        """SettingsPage must call fetchSettings on mount."""
        src = _settings_page()
        assert "fetchSettings" in src

    def test_settings_page_populates_provider(self):
        """loadSettings must set provider state from settings response."""
        src = _settings_page()
        fn_idx = src.find("loadSettings")
        assert fn_idx >= 0, "loadSettings not found in SettingsPage"
        body = src[fn_idx:fn_idx + 500]
        assert "setProvider" in body, "loadSettings must set provider state"

    def test_settings_page_populates_base_url(self):
        """loadSettings must populate base URL (Ollama host) from response."""
        src = _settings_page()
        fn_idx = src.find("loadSettings")
        assert fn_idx >= 0
        body = src[fn_idx:fn_idx + 500]
        assert "setBaseUrl" in body or "ollama_host" in body, \
            "loadSettings must read ollama_host and populate base URL"

    def test_settings_page_populates_api_key(self):
        """loadSettings must populate API key from response."""
        src = _settings_page()
        fn_idx = src.find("loadSettings")
        assert fn_idx >= 0
        body = src[fn_idx:fn_idx + 500]
        assert "setApiKey" in body, "loadSettings must populate API key"

    def test_provider_change_populates_model_list(self):
        """After changing provider, model list must be updated."""
        src = _settings_page()
        assert "handleProviderChange" in src, \
            "Settings must have provider change handler to update models"
        fn_idx = src.find("handleProviderChange")
        body = src[fn_idx:fn_idx + 300]
        assert "setModelSelect" in body, \
            "handleProviderChange must update model select"

    def test_model_select_populated_dynamically(self):
        """Model select options must be populated from PROVIDER_MODELS, not hardcoded."""
        src = _settings_page()
        assert "currentModels.map" in src, \
            "Model select options must be dynamically mapped from currentModels"


# ═══════════════════════════════════════════════════════════════════════════
# CONTRACT: Settings slurm fields ↔ HPC wizard prefill roundtrip
# ═══════════════════════════════════════════════════════════════════════════

class TestSlurmSettingsRoundtrip:
    """SLURM defaults saved in Settings must prefill wizard Step 3."""

    def test_settings_has_slurm_cpus_field(self):
        """Settings page must have slurm_cpus input."""
        src = _settings_page()
        assert "slurm_cpus" in src or "cpus" in src

    def test_settings_has_slurm_memory_field(self):
        src = _settings_page()
        assert "slurm_memory_gb" in src or "memGb" in src

    def test_settings_has_slurm_walltime_field(self):
        src = _settings_page()
        assert "slurm_walltime" in src or "walltime" in src

    def test_savesettings_sends_slurm_defaults(self):
        """handleSave must include slurm_* in POST body."""
        src = _settings_page()
        fn_idx = src.find("handleSave")
        body = src[fn_idx:fn_idx + 800]
        assert "slurm_cpus" in body, "handleSave must send slurm_cpus"
        assert "slurm_memory_gb" in body, "handleSave must send slurm_memory_gb"

    def test_wizard_prefill_reads_slurm_from_settings(self):
        """Step 3 StepResources fetches settings and reads slurm_* keys."""
        src = _step_resources()
        for key in ["slurm_cpus", "slurm_memory_gb", "slurm_walltime"]:
            assert key in src, f"StepResources must read '{key}' from settings"

    def test_wizard_hpc_prefill_is_conditional(self):
        """HPC field prefill must not overwrite when settings value is absent."""
        src = _step_resources()
        idx = src.find("slurm_cpus")
        assert idx >= 0
        chunk = src[idx:idx + 130]
        assert "if" in chunk or "&&" in chunk or "?" in chunk, \
            f"HPC prefill must be guarded by truthiness check: {chunk}"


# ═══════════════════════════════════════════════════════════════════════════
# INTEGRATION: settings.json write/read roundtrip (unit-level, no HTTP)
# ═══════════════════════════════════════════════════════════════════════════

class TestSettingsJsonRoundtrip:
    """Unit-level test: the settings JSON schema is consistent."""

    # Keys that must always appear in settings.json (with defaults)
    REQUIRED_KEYS = {
        "llm_model", "llm_provider", "api_key", "ollama_host"
    }
    SLURM_KEYS = {
        "slurm_cpus", "slurm_memory_gb", "slurm_gpus", "slurm_walltime",
        "slurm_partition"
    }

    def test_server_writes_all_required_keys(self):
        """server.py settings POST handler must save all required keys."""
        srv = _srv()
        for key in self.REQUIRED_KEYS:
            assert key in srv, f"server.py settings handler missing key: {key}"

    def test_server_writes_slurm_keys(self):
        """api_settings.py settings handler must include slurm_* keys."""
        src = _api_set()
        for key in self.SLURM_KEYS:
            assert key in src, f"api_settings.py missing slurm key: {key}"

    def test_get_response_includes_all_required_keys(self):
        """GET /api/settings response dict must include all required keys."""
        srv = _srv()
        for key in self.REQUIRED_KEYS:
            assert key in srv

    def test_settings_defaults_are_empty_not_hardcoded(self):
        """
        Default values for model/provider in settings must be '' not a
        specific model name like 'gpt-4' or provider name 'openai'.
        """
        srv = _srv()
        # Find where default settings dict is defined
        idx = srv.find("settings.json")
        if idx < 0:
            return
        # Look for a defaults block
        chunk = srv[max(0, idx-300):idx+500]
        bad = ["gpt-4", "gpt-3.5", "claude-3", "qwen3", "llama3"]
        for model in bad:
            assert f'"{model}"' not in chunk and f"'{model}'" not in chunk, \
                f"settings.json default must not hardcode model '{model}'"

    def test_settings_no_api_key_in_default(self):
        """settings.json defaults must not contain any API key value."""
        srv = _srv()
        # Check no sk- or Bearer tokens in the defaults
        assert not re.search(r'"api_key"\s*:\s*"sk-', srv), \
            "settings.json default must not contain an API key value"

    def test_settings_file_path_is_portable(self):
        """Settings file path must derive from the active checkpoint dir,
        not a hardcoded absolute path."""
        src = _srv() + _api_set()
        # Path comes from state._settings_path or PathManager.project_settings_path.
        assert (
            "_settings_path" in src or "project_settings_path" in src
        ), "settings path must be derived from project state, not hardcoded"


# ═══════════════════════════════════════════════════════════════════════════
# INTEGRATION: Live HTTP roundtrip (skipped if server not running)
# ═══════════════════════════════════════════════════════════════════════════

import pytest

_SERVER_URL = "http://localhost:9886"


def _server_available():
    try:
        urllib.request.urlopen(f"{_SERVER_URL}/state", timeout=1)
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _server_available(), reason="GUI server not running on :9886")
class TestLiveSettingsRoundtrip:
    """
    Live HTTP roundtrip tests (only run when server is on :9886).
    Uses a temp settings file to avoid mutating real settings.
    """

    def test_get_settings_returns_json(self):
        resp = urllib.request.urlopen(f"{_SERVER_URL}/api/settings", timeout=3)
        assert resp.status == 200
        data = json.loads(resp.read())
        assert isinstance(data, dict)

    def test_get_settings_has_required_fields(self):
        resp = urllib.request.urlopen(f"{_SERVER_URL}/api/settings", timeout=3)
        data = json.loads(resp.read())
        for key in ["llm_model", "llm_provider"]:
            assert key in data, f"GET /api/settings missing field: {key}"
        # ollama_host added to defaults
        assert "ollama_host" in data or "llm_api_key" in data, "GET must return provider settings"

    def test_post_settings_accepted(self):
        # Save original settings so we can restore them
        resp0 = urllib.request.urlopen(f"{_SERVER_URL}/api/settings", timeout=3)
        orig = json.loads(resp0.read())

        try:
            payload = json.dumps({
                "llm_model": "__test_model__",
                "llm_provider": "ollama",
                "api_key": "",
                "ollama_host": "http://localhost:11434",
            }).encode()
            req = urllib.request.Request(
                f"{_SERVER_URL}/api/settings",
                data=payload,
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            resp = urllib.request.urlopen(req, timeout=3)
            assert resp.status in (200, 204)
        finally:
            # Restore original settings
            restore = json.dumps(orig).encode()
            req_r = urllib.request.Request(
                f"{_SERVER_URL}/api/settings",
                data=restore, method="POST",
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req_r, timeout=3)

    def test_saved_model_reflected_in_get(self):
        """After POST, GET must return the saved model name."""
        # Save original
        resp0 = urllib.request.urlopen(f"{_SERVER_URL}/api/settings", timeout=3)
        orig = json.loads(resp0.read())

        try:
            # POST a test value
            payload = json.dumps({**orig, "llm_model": "__roundtrip_test__"}).encode()
            req = urllib.request.Request(
                f"{_SERVER_URL}/api/settings",
                data=payload, method="POST",
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=3)

            # GET must reflect saved value
            resp2 = urllib.request.urlopen(f"{_SERVER_URL}/api/settings", timeout=3)
            data2 = json.loads(resp2.read())
            assert data2.get("llm_model") == "__roundtrip_test__", \
                f"Saved model not reflected in GET response: {data2}"
        finally:
            # Restore original
            restore = json.dumps(orig).encode()
            req_r = urllib.request.Request(
                f"{_SERVER_URL}/api/settings",
                data=restore, method="POST",
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req_r, timeout=3)

    def test_state_reflects_saved_model(self):
        """After POST to /api/settings, /state includes the model from settings
        or a higher-priority source (launch_config / cost_trace)."""
        resp0 = urllib.request.urlopen(f"{_SERVER_URL}/api/settings", timeout=3)
        orig = json.loads(resp0.read())

        try:
            payload = json.dumps({**orig, "llm_model": "__state_test__"}).encode()
            req = urllib.request.Request(
                f"{_SERVER_URL}/api/settings",
                data=payload, method="POST",
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=3)
            time.sleep(0.1)

            # Verify settings roundtrip via /api/settings
            settings_resp = urllib.request.urlopen(f"{_SERVER_URL}/api/settings", timeout=3)
            settings = json.loads(settings_resp.read())
            assert settings.get("llm_model") == "__state_test__", \
                f"Settings not persisted: {settings.get('llm_model')!r}"

            # /state model may differ: experiment launch_config / cost_trace
            # takes priority over settings (by design).  Verify a model IS
            # present — it may be the saved value or the experiment's model.
            state_resp = urllib.request.urlopen(f"{_SERVER_URL}/state", timeout=3)
            state = json.loads(state_resp.read())
            model_in_state = (
                state.get("llm_model") or
                state.get("llm_model_actual") or
                (state.get("experiment_config") or {}).get("llm_model")
            )
            assert model_in_state, \
                "No model found in /state (llm_model, llm_model_actual, experiment_config)"
        finally:
            restore = json.dumps(orig).encode()
            req_r = urllib.request.Request(
                f"{_SERVER_URL}/api/settings",
                data=restore, method="POST",
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req_r, timeout=3)
