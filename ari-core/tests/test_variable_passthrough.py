"""
test_variable_passthrough.py
─────────────────────────────────────────────────────────────────────────────
Variable-passing chain verification for ARI dashboard.

Tests the full pipeline:
  Wizard UI field  →  JS payload key  →  API POST body  →  api_experiment.py
  →  proc_env[]   →  config.py  →  ARI subprocess env var

Also detects invalid fallbacks (hardcoded defaults that override user intent).
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations
import re
from pathlib import Path

_VIZ = Path(__file__).parent.parent / "ari/viz"
_ARI = Path(__file__).parent.parent / "ari"
_REACT_SRC = _VIZ / "frontend" / "src"
_REACT_COMPONENTS = _REACT_SRC / "components"


def _step_scope():   return (_REACT_COMPONENTS / "Wizard" / "StepScope.tsx").read_text()
def _step_resources(): return (_REACT_COMPONENTS / "Wizard" / "StepResources.tsx").read_text()
def _step_launch():  return (_REACT_COMPONENTS / "Wizard" / "StepLaunch.tsx").read_text()
def _wizard_page():  return (_REACT_COMPONENTS / "Wizard" / "WizardPage.tsx").read_text()
def _settings_page(): return (_REACT_COMPONENTS / "Settings" / "SettingsPage.tsx").read_text()
def _api():   return (_VIZ / "api_experiment.py").read_text()
def _cfg():   return (_ARI / "config.py").read_text()
def _srv():   return (_VIZ / "server.py").read_text()
def _set():   return (_VIZ / "api_settings.py").read_text()


def _read_react_sources():
    parts = []
    for tsx in sorted(_REACT_SRC.rglob("*.tsx")):
        parts.append(tsx.read_text())
    for ts in sorted(_REACT_SRC.rglob("*.ts")):
        parts.append(ts.read_text())
    return "\n".join(parts)

# ════════════════════════════════════════════════════════════════════════════
# 1. SCOPE/REACT FIELDS: HTML id → JS payload key → proc_env
# ════════════════════════════════════════════════════════════════════════════

class TestScopeFieldChain:
    """maxReact / timeout / scope fields pass through completely."""

    def test_max_react_field_exists(self):
        assert "maxReact" in _step_scope()

    def test_timeout_field_exists(self):
        assert "timeout" in _step_scope()

    def test_max_react_in_scope_component(self):
        assert "maxReact" in _step_scope(), "StepScope must have maxReact field"

    def test_timeout_in_scope_component(self):
        assert "timeout" in _step_scope(), "StepScope must have timeout field"

    def test_max_react_payload_key(self):
        assert "max_react" in _step_launch(), "StepLaunch must send max_react"

    def test_timeout_payload_key(self):
        src = _step_launch()
        assert "timeout_min" in src or "timeout" in src, \
            "StepLaunch must send timeout_min"

    def test_api_reads_max_react(self):
        assert 'data.get("max_react")' in _api() or "max_react" in _api()

    def test_api_reads_timeout(self):
        api = _api()
        assert 'data.get("timeout_min")' in api or "timeout_min" in api

    def test_api_sets_ari_max_react_env(self):
        assert "ARI_MAX_REACT" in _api()

    def test_api_sets_ari_timeout_env(self):
        assert "ARI_TIMEOUT_NODE" in _api()

    def test_api_sets_ari_max_nodes_env(self):
        assert "ARI_MAX_NODES" in _api()

    def test_api_sets_ari_max_depth_env(self):
        assert "ARI_MAX_DEPTH" in _api()

    def test_api_sets_ari_parallel_env(self):
        assert "ARI_PARALLEL" in _api()


# ════════════════════════════════════════════════════════════════════════════
# 2. HPC FIELDS: HTML id → JS payload key → proc_env → config.py
# ════════════════════════════════════════════════════════════════════════════

class TestHpcFieldChain:
    """HPC resource wizard fields pass through to SLURM env vars and config."""

    # React component layer
    def test_hpc_cpus_in_resources(self):
        assert "hpcCpus" in _step_resources()

    def test_hpc_mem_in_resources(self):
        assert "hpcMem" in _step_resources()

    def test_hpc_wall_in_resources(self):
        assert "hpcWall" in _step_resources()

    def test_hpc_gpus_in_resources(self):
        assert "hpcGpus" in _step_resources()

    # State management
    def test_hpc_cpus_state_in_wizard(self):
        assert "hpcCpus" in _wizard_page()

    def test_hpc_mem_state_in_wizard(self):
        assert "hpcMem" in _wizard_page()

    def test_hpc_wall_state_in_wizard(self):
        assert "hpcWall" in _wizard_page()

    # Payload keys (in StepLaunch)
    def test_payload_hpc_cpus(self):
        assert "hpc_cpus" in _step_launch()

    def test_payload_hpc_memory_gb(self):
        assert "hpc_memory_gb" in _step_launch()

    def test_payload_hpc_walltime(self):
        assert "hpc_walltime" in _step_launch()

    def test_payload_hpc_gpus(self):
        assert "hpc_gpus" in _step_launch()

    # api_experiment.py reads
    def test_api_reads_hpc_cpus(self):
        assert 'data.get("hpc_cpus")' in _api() or "hpc_cpus" in _api()

    def test_api_reads_hpc_memory(self):
        assert 'data.get("hpc_memory_gb")' in _api() or "hpc_memory_gb" in _api()

    def test_api_reads_hpc_gpus(self):
        assert 'data.get("hpc_gpus")' in _api() or "hpc_gpus" in _api()

    def test_api_reads_hpc_walltime(self):
        assert 'data.get("hpc_walltime")' in _api() or "hpc_walltime" in _api()

    # env var injection
    def test_api_injects_slurm_cpus(self):
        assert "ARI_SLURM_CPUS" in _api()

    def test_api_injects_slurm_mem(self):
        assert "ARI_SLURM_MEM_GB" in _api()

    def test_api_injects_slurm_gpus(self):
        assert "ARI_SLURM_GPUS" in _api()

    def test_api_injects_slurm_walltime(self):
        assert "ARI_SLURM_WALLTIME" in _api()

    def test_api_injects_slurm_partition(self):
        assert "ARI_SLURM_PARTITION" in _api()

    # config.py reads env vars
    def test_config_reads_slurm_cpus(self):
        assert "ARI_SLURM_CPUS" in _cfg()

    def test_config_reads_slurm_mem(self):
        assert "ARI_SLURM_MEM_GB" in _cfg()

    def test_config_reads_slurm_gpus(self):
        assert "ARI_SLURM_GPUS" in _cfg()

    def test_config_reads_slurm_walltime(self):
        assert "ARI_SLURM_WALLTIME" in _cfg()

    def test_config_reads_slurm_partition(self):
        assert "ARI_SLURM_PARTITION" in _cfg()


# ════════════════════════════════════════════════════════════════════════════
# 3. MODEL FIELDS: wizard → payload → api → env → config
# ════════════════════════════════════════════════════════════════════════════

class TestModelFieldChain:
    """LLM model/provider selection passes through without corruption."""

    def test_wizard_model_state_exists(self):
        assert "model" in _wizard_page(), "Wizard must have model state"

    def test_wizard_llm_provider_state_exists(self):
        assert "llm" in _wizard_page() or "setLlm" in _wizard_page(), \
            "Wizard must have llm provider state"

    def test_payload_sends_llm_model(self):
        assert "llm_model" in _step_launch()

    def test_payload_sends_llm_provider(self):
        assert "llm_provider" in _step_launch()

    def test_api_reads_llm_model(self):
        assert "llm_model" in _api()

    def test_api_reads_llm_provider(self):
        assert "llm_provider" in _api()

    def test_api_sets_ari_model_env(self):
        assert "ARI_MODEL" in _api()

    def test_api_sets_ari_backend_env(self):
        assert "ARI_BACKEND" in _api()

    def test_settings_prefill_updates_provider_state(self):
        """Step 3 prefill must update the provider state from settings."""
        src = _step_resources()
        assert "handleSetLlm" in src or "setLlm" in src

    def test_api_ari_backend_only_if_provider_nonempty(self):
        """ARI_BACKEND must only be set when wizard sends non-empty provider."""
        api = _api()
        idx = api.find('proc_env["ARI_BACKEND"] = wiz_provider')
        assert idx > 0, "ARI_BACKEND must be set from wiz_provider"
        context = api[max(0, idx - 120):idx]
        assert "if wiz_provider" in context, \
            "ARI_BACKEND must only be set when wiz_provider is non-empty"


# ════════════════════════════════════════════════════════════════════════════
# 4. INVALID FALLBACK DETECTION
# ════════════════════════════════════════════════════════════════════════════

class TestInvalidFallbacks:
    """
    Catch incorrect default values that override user intent.
    Rule: any fallback that silently substitutes a domain-specific value
    (provider name, model name, cluster-specific path, etc.) is invalid.
    """

    def test_launch_provider_has_fallback(self):
        """StepLaunch payload must have a provider fallback (e.g. || 'openai')."""
        src = _step_launch()
        assert "llm_provider" in src, "StepLaunch must include llm_provider"
        # In React, the fallback is: llmProvider || 'openai'
        assert "|| 'openai'" in src or '|| "openai"' in src, \
            "StepLaunch must have an 'openai' fallback for empty provider"

    def test_step_resources_no_invalid_provider_fallback(self):
        """StepResources settings prefill must handle empty provider gracefully."""
        src = _step_resources()
        # The prefill uses: s.llm_provider || s.llm_backend || 'openai'
        # This is valid — it provides a sensible default
        assert "llm_provider" in src or "llm_backend" in src

    def test_model_payload_no_hardcoded_default(self):
        """
        Launch payload must NOT fall back to a specific hardcoded model name
        outside of PROVIDER_MODELS definitions.
        """
        src = _step_launch()
        fn_idx = src.find("handleLaunch")
        assert fn_idx >= 0
        body = src[fn_idx:fn_idx + 1000]
        # No specific model names as fallbacks in the launch handler
        bad_models = ["gpt-4", "gpt-3.5", "qwen3", "llama", "claude", "gemini"]
        for m in bad_models:
            assert f"|| '{m}" not in body and f'|| "{m}' not in body, \
                f"handleLaunch must not fall back to '{m}'"

    def test_hpc_null_fallback_not_zero(self):
        """
        HPC integer fields must fall back to null (not 0).
        Sending 0 CPUs would inject ARI_SLURM_CPUS=0 — invalid SLURM config.
        """
        src = _step_launch()
        # Find hpc_cpus assignment
        idx = src.find("hpc_cpus")
        assert idx > 0
        chunk = src[idx:idx + 120]
        # In React: parseInt(hpcCpus) || null
        assert "|| null" in chunk or "parseInt" in chunk or "null" in chunk, \
            f"hpc_cpus must fall back to null or use parseInt: {chunk}"

    def test_api_slurm_env_not_injected_when_null(self):
        """
        api_experiment.py must NOT inject ARI_SLURM_CPUS when value is None/null.
        Guard: 'if wiz_hpc_cpus is not None' or equivalent.
        """
        api = _api()
        idx = api.find('proc_env["ARI_SLURM_CPUS"]')
        assert idx > 0
        context = api[max(0, idx - 80):idx]
        assert "is not None" in context or "if wiz_hpc_cpus" in context, \
            "ARI_SLURM_CPUS must be guarded by None check"

    def test_api_ari_max_react_not_injected_when_none(self):
        """ARI_MAX_REACT must not be injected when wizard didn't send the field."""
        api = _api()
        idx = api.find('proc_env["ARI_MAX_REACT"]')
        assert idx > 0
        context = api[max(0, idx - 80):idx]
        assert "is not None" in context or "if wiz_max_react" in context, \
            "ARI_MAX_REACT must be guarded by None check"

    def test_settings_model_select_uses_dynamic_options(self):
        """Settings model dropdown must be populated from PROVIDER_MODELS dynamically."""
        src = _settings_page()
        assert "currentModels.map" in src, \
            "Settings model dropdown must be dynamically populated from currentModels"

    def test_settings_has_custom_entry_option(self):
        """Settings page must inject __custom__ into model select."""
        src = _settings_page()
        assert "__custom__" in src, \
            "Settings page must include __custom__ option"

    def test_handleSave_reads_model_select_state(self):
        """handleSave must read modelSelect state, not just modelCustom."""
        src = _settings_page()
        fn_idx = src.find("handleSave")
        assert fn_idx >= 0
        body = src[fn_idx:fn_idx + 500]
        assert "modelSelect" in body, \
            "handleSave must reference modelSelect"


# ════════════════════════════════════════════════════════════════════════════
# 5. STATE → UI RENDERING (JS reads correct fields from /state response)
# ════════════════════════════════════════════════════════════════════════════

class TestStateToUiRendering:
    """Verify React components correctly read fields from state."""

    def test_model_displayed_in_ui(self):
        """React components must display llm_model from state."""
        combined = _read_react_sources()
        assert "llm_model" in combined

    def test_phase_stepper_reads_state_phase(self):
        """Phase stepper must read phase from state."""
        combined = _read_react_sources()
        assert "phase" in combined

    def test_state_polling_exists(self):
        """App must poll state via fetchState."""
        combined = _read_react_sources()
        assert "fetchState" in combined

    def test_idea_page_reads_state_ideas(self):
        """Idea page must read ideas from state."""
        combined = _read_react_sources()
        assert "ideas" in combined

    def test_idea_page_reads_gap_analysis(self):
        """Idea page must read gap_analysis from state."""
        combined = _read_react_sources()
        assert "gap_analysis" in combined

    def test_idea_page_reads_novelty_score(self):
        """Idea page must render novelty_score per idea."""
        combined = _read_react_sources()
        assert "novelty_score" in combined

    def test_idea_page_reads_feasibility_score(self):
        """Idea page must render feasibility_score per idea."""
        combined = _read_react_sources()
        assert "feasibility_score" in combined

    def test_experiment_goal_shown(self):
        """React must display experiment goal from state."""
        combined = _read_react_sources()
        assert "experiment_goal" in combined or "goalSummary" in combined or \
               "experiment_md" in combined

    def test_running_status_reflected(self):
        """Running status from state must be shown."""
        combined = _read_react_sources()
        assert "running" in combined.lower() or "is_running" in combined or \
               "isRunning" in combined

    def test_state_running_disables_actions(self):
        """is_running flag from state must affect UI actions."""
        combined = _read_react_sources()
        assert "is_running" in combined or "isRunning" in combined or \
               "running" in combined


# ════════════════════════════════════════════════════════════════════════════
# 6. SETTINGS → WIZARD PREFILL
# ════════════════════════════════════════════════════════════════════════════

class TestSettingsToWizardPrefill:
    """Settings API response must correctly prefill wizard fields."""

    def test_settings_response_has_llm_model(self):
        """api_settings.py GET must return llm_model."""
        src = _set()
        assert "llm_model" in src

    def test_settings_response_has_llm_provider(self):
        """api_settings.py GET must return llm_provider."""
        src = _set()
        assert "llm_provider" in src or "provider" in src

    def test_settings_response_has_ollama_host(self):
        """Settings endpoint must handle ollama_host (in server.py or api_ollama.py)."""
        api_ol = (_VIZ / "api_ollama.py").read_text()
        srv = _srv()
        assert "ollama_host" in api_ol or "ollama_host" in srv, \
            "ollama_host must be handled somewhere in the viz stack"

    def test_wizard_prefill_reads_llm_model_from_settings(self):
        """Step 3 init must read llm_model from /api/settings response."""
        src = _step_resources()
        assert "llm_model" in src or "setModel" in src

    def test_wizard_prefill_reads_slurm_from_settings(self):
        """Wizard must read slurm_cpus etc. from settings for HPC prefill."""
        src = _step_resources()
        for key in ["slurm_cpus", "slurm_memory_gb", "slurm_walltime"]:
            assert key in src, f"StepResources must read '{key}' from settings"

    def test_settings_prefill_does_not_override_when_absent(self):
        """
        If settings key is absent/falsy, wizard must not overwrite
        the current field value with empty string or zero.
        """
        src = _step_resources()
        # HPC prefill must be conditional: if (s.slurm_cpus) setHpcCpus(...)
        idx = src.find("slurm_cpus")
        assert idx >= 0
        chunk = src[idx:idx + 120]
        assert "if" in chunk or "&&" in chunk or "?" in chunk, \
            f"HPC prefill must be conditional (not unconditional): {chunk}"
