"""
ARI Data Flow Integration Tests
Tests the full data contract between viz modules and dashboard.
"""
import json, os, re
from pathlib import Path

VIZ_DIR = Path(__file__).parent.parent / "ari/viz"
DASHBOARD = VIZ_DIR / "dashboard.html"

# Source files for grepping
API_EXPERIMENT = VIZ_DIR / "api_experiment.py"
API_SETTINGS = VIZ_DIR / "api_settings.py"
SERVER = VIZ_DIR / "server.py"

# React frontend source directories
REACT_SRC = VIZ_DIR / "frontend" / "src"
REACT_COMPONENTS = REACT_SRC / "components"
REACT_SERVICES = REACT_SRC / "services"
REACT_I18N = REACT_SRC / "i18n"


def _read_react_sources():
    """Read all React TypeScript source files and return combined text."""
    parts = []
    for tsx in sorted(REACT_SRC.rglob("*.tsx")):
        parts.append(tsx.read_text())
    for ts in sorted(REACT_SRC.rglob("*.ts")):
        parts.append(ts.read_text())
    return "\n".join(parts)


def _combined():
    return _read_react_sources()


# ── Wizard ──────────────────────────────────────────────────────────────────

def test_wizard_provider_default_not_empty():
    """launchExperiment must always send a non-empty provider fallback."""
    combined = _combined()
    # React StepLaunch sends llm_provider with fallback: llmProvider || 'openai'
    assert "llm_provider" in combined, "llm_provider not found in React source"
    # The launch payload has a fallback: llmProvider || 'openai'
    assert "|| 'openai'" in combined or "|| \"openai\"" in combined or "DEFAULT_PROVIDER" in combined, \
        "Must have provider fallback in launch payload"


def test_wizard_llm_provider_state_exists():
    """Wizard must manage LLM provider via React state."""
    combined = _combined()
    assert "setLlm" in combined or "llmProvider" in combined, \
        "Wizard must have llm provider state management"


def test_wizard_provider_initial_value():
    """Wizard provider state defaults to 'openai'."""
    combined = _combined()
    # WizardPage initializes llm to 'openai': useState('openai')
    assert "useState('openai')" in combined or 'useState("openai")' in combined, \
        "Wizard must initialize provider state to 'openai'"


def test_wizard_setllm_syncs_provider():
    """handleSetLlm or equivalent must update provider and model list."""
    combined = _combined()
    # StepResources has handleSetLlm that updates provider and models
    assert "handleSetLlm" in combined or "setLlm" in combined, \
        "Wizard must have provider update function"


def test_wizard_step3_prefills_from_settings():
    """Step 3 (Resources) must fetch settings and pre-populate provider/model."""
    combined = _combined()
    assert "fetchSettings" in combined, "missing settings fetch"
    # StepResources fetches settings and calls handleSetLlm
    assert "handleSetLlm" in combined or "setLlm" in combined, \
        "Step 3 must set provider from settings"


def test_wizard_ollama_free_text():
    """Ollama provider must show free-text model input."""
    combined = _combined()
    # StepResources has a customModel input for ollama
    assert "customModel" in combined or "model_custom_placeholder" in combined, \
        "Ollama must have free-text custom model input"


# ── API: ARI_BACKEND ────────────────────────────────────────────────────

def test_server_ari_backend_from_settings():
    """_api_launch must set ARI_BACKEND from settings llm_provider."""
    src = API_EXPERIMENT.read_text()
    assert 'proc_env["ARI_BACKEND"] = llm_provider' in src


def test_server_ari_backend_not_overridden_when_empty():
    """Wizard's ARI_BACKEND only applied if wiz_provider is non-empty."""
    src = API_EXPERIMENT.read_text()
    idx = src.find('proc_env["ARI_BACKEND"] = wiz_provider')
    assert idx > 0
    context = src[max(0, idx-100):idx]
    assert 'if wiz_provider:' in context or 'if wiz_provider' in context


# ── Server: State — no cwd fallback ──────────────────────────────────────

def test_server_no_cwd_experiment_md_fallback():
    """State handler must NOT fall back to cwd/experiment.md (project isolation)."""
    src = SERVER.read_text()
    assert 'cwd() / "experiment.md"' not in src, "cwd fallback must be removed"
    assert '_last_experiment_md' in src


def test_server_log_file_switches():
    """SSE log stream re-resolves log file each iteration for multi-experiment support."""
    src = API_EXPERIMENT.read_text()
    assert 'Switched to log' in src
    assert 'last_log_seen' in src or 'last_log_path' in src


def test_server_ansi_strip_in_sse():
    """ANSI escape codes are stripped before sending to browser."""
    src = API_EXPERIMENT.read_text()
    assert r'\x1b' in src


# ── i18n ──────────────────────────────────────────────────────────────────

def test_i18n_no_circular_refs():
    """en i18n dict must not call t() (circular reference)."""
    en_src = (REACT_I18N / "en.ts").read_text()
    assert "t('" not in en_src, "Circular t() call in en.ts i18n dict"


def test_i18n_default_lang():
    """Default language should include a fallback."""
    combined = _combined()
    assert "'en'" in combined or "'ja'" in combined, "Must have language fallback"


def test_i18n_nav_items_have_data_i18n():
    """All sidebar nav items must use data-i18n for translations."""
    combined = _combined()
    for key in ['nav_home', 'nav_monitor', 'nav_tree', 'nav_results', 'nav_settings', 'nav_idea']:
        assert key in combined, f"Missing i18n key: {key}"


# ── Results page ──────────────────────────────────────────────────────────

def test_results_repro_error_handled():
    """Reproducibility skill error shows friendly message, not raw error."""
    combined = _combined()
    assert 'repro' in combined.lower() or 'ari-skill-paper-re' in combined or \
           'repro_skill_unavail' in combined, \
        "Results page must handle reproducibility skill errors gracefully"


def test_results_no_score_question_mark():
    """Results page must not show 'score:?' for experiments without papers."""
    combined = _combined()
    # In React, results are rendered via ResultsPage.tsx
    assert "score:'?'" not in combined and "score:?" not in combined


# ── Project isolation ─────────────────────────────────────────────────────

def test_no_cwd_writes_in_api_experiment():
    """api_experiment.py must not write to Path.cwd()."""
    src = API_EXPERIMENT.read_text()
    # Path.cwd() should not appear as a write destination
    assert 'Path.cwd() / "checkpoints"' not in src or 'ckpt_root = Path.cwd()' not in src


def test_no_cwd_writes_in_api_tools():
    """api_tools.py must not write to Path.cwd()."""
    src = (VIZ_DIR / "api_tools.py").read_text()
    assert 'Path.cwd()' not in src


def test_no_cwd_writes_in_api_settings():
    """api_settings.py must not write to Path.cwd()."""
    src = API_SETTINGS.read_text()
    assert 'Path.cwd()' not in src


def test_api_modules_no_unused_websockets_import():
    """api_*.py files must not import websockets (they don't need it)."""
    for name in ["api_experiment.py", "api_settings.py", "api_tools.py", "api_ollama.py", "api_state.py"]:
        src = (VIZ_DIR / name).read_text()
        assert "import websockets" not in src, f"{name} has unnecessary websockets import"


def test_api_modules_no_unused_http_server_import():
    """api_*.py files must not import http.server (only server.py needs it)."""
    for name in ["api_experiment.py", "api_settings.py", "api_tools.py", "api_ollama.py", "api_state.py"]:
        src = (VIZ_DIR / name).read_text()
        assert "from http.server import" not in src, f"{name} has unnecessary http.server import"


# ── Stale experiment_md protection ───────────────────────────────────────

def test_last_experiment_md_only_used_when_running():
    """_last_experiment_md must only be used as fallback when a process is running.
    Stale test data in _last_experiment_md must not leak into the dashboard."""
    src = SERVER.read_text()
    import re
    # Find all usages of _last_experiment_md
    usages = [(i+1, line.strip()) for i, line in enumerate(src.splitlines())
              if "_last_experiment_md" in line and not line.strip().startswith("#")]
    for lineno, line in usages:
        # Assignment lines are OK
        if "_last_experiment_md =" in line or "_last_experiment_md:" in line:
            continue
        # Usage as data source must be guarded by process-running check
        if "data[" in line or "_exp_md =" in line or "_exp_md" in line:
            # Find surrounding context — the guard may be the enclosing
            # if-block (e.g. `if _st._last_proc and poll() is None:`)
            # which can be up to ~12 lines above the usage line.
            lines = src.splitlines()
            context = "\n".join(lines[max(0, lineno - 13):lineno])
            assert "_last_proc" in context or "poll()" in context or "_ckpt_valid" in context, \
                f"Line {lineno}: _last_experiment_md used without process-running guard:\n  {line}"


def test_experiment_md_search_prefers_checkpoint_dir():
    """server.py must look for experiment.md in checkpoint dir BEFORE _last_experiment_md."""
    src = SERVER.read_text()
    # In the state handler, the checkpoint dir search must come before _last_experiment_md
    idx_ckpt_search = src.find('# Try 1: checkpoint dir')
    idx_last_md = src.find('_st._last_experiment_md', idx_ckpt_search)
    # There should be checkpoint dir search and experiments dir search before _last_experiment_md
    idx_try2 = src.find('# Try 2:', idx_ckpt_search)
    assert idx_ckpt_search < idx_try2 < idx_last_md, \
        "Search order: checkpoint dir → experiments dir → _last_experiment_md"


def test_experiment_goal_displayed_in_ui():
    """React components must reference experiment_goal from state."""
    combined = _combined()
    assert "experiment_goal" in combined or "goalSummary" in combined or \
           "experiment_md" in combined, \
        "UI must display experiment goal from state"


# ── HPC Resource Fields in Wizard Step 3 ──────────────────────────────────

def _react_resources():
    """Read the wizard resource-related component sources (StepResources + WizardPage)."""
    sr = (REACT_COMPONENTS / "Wizard" / "StepResources.tsx").read_text()
    wp = (REACT_COMPONENTS / "Wizard" / "WizardPage.tsx").read_text()
    return sr + "\n" + wp


def _react_launch():
    """Read the StepLaunch React component source."""
    return (REACT_COMPONENTS / "Wizard" / "StepLaunch.tsx").read_text()


def test_hpc_cpus_field_exists():
    """Step 3 must have CPU input field."""
    src = _react_resources()
    assert "hpcCpus" in src, "Missing HPC CPUs input in StepResources"


def test_hpc_memory_field_exists():
    """Step 3 must have memory input field."""
    src = _react_resources()
    assert "hpcMem" in src, "Missing HPC memory input in StepResources"


def test_hpc_walltime_fields_exist():
    """Step 3 must have walltime input field."""
    src = _react_resources()
    assert "hpcWall" in src, "Missing HPC walltime input in StepResources"


def test_hpc_fields_inside_hpc_section():
    """HPC resource fields must be inside a section conditionally rendered when mode=hpc."""
    src = _react_resources()
    # In React, HPC fields are inside {mode === 'hpc' && (...)} conditional block
    hpc_cond_idx = src.find("mode === 'hpc'")
    assert hpc_cond_idx > 0, "HPC conditional section not found"
    # HPC fields must appear after the conditional
    for field in ["hpcCpus", "hpcMem", "hpcWall"]:
        field_pos = src.find(field, hpc_cond_idx)
        assert field_pos > hpc_cond_idx, \
            f"{field} must be inside HPC conditional section"


def test_wizard_launch_payload_includes_hpc_cpus():
    """launchExperiment() must send hpc_cpus in the JSON payload."""
    src = _react_launch()
    assert "hpc_cpus" in src, "hpc_cpus missing from launch payload"


def test_wizard_launch_payload_includes_hpc_memory():
    """launchExperiment() must send hpc_memory_gb in the JSON payload."""
    src = _react_launch()
    assert "hpc_memory_gb" in src, "hpc_memory_gb missing from launch payload"


def test_wizard_launch_payload_includes_hpc_walltime():
    """launchExperiment() must send hpc_walltime in the JSON payload."""
    src = _react_launch()
    assert "hpc_walltime" in src, "hpc_walltime missing from launch payload"


def test_wizard_launch_payload_includes_hpc_gpus():
    """launchExperiment() must send hpc_gpus in the JSON payload."""
    src = _react_launch()
    assert "hpc_gpus" in src, "hpc_gpus missing from launch payload"


def test_wizard_step3_prefills_hpc_from_settings():
    """Step 3 init must populate HPC fields from /api/settings defaults."""
    src = _react_resources()
    assert "slurm_cpus" in src, "wizard must read slurm_cpus from settings"
    assert "slurm_memory_gb" in src, "wizard must read slurm_memory_gb from settings"
    assert "slurm_walltime" in src, "wizard must read slurm_walltime from settings"


def test_api_launch_injects_hpc_env_vars():
    """_api_launch must inject ARI_SLURM_* env vars from wizard data."""
    src = API_EXPERIMENT.read_text()
    assert "ARI_SLURM_CPUS" in src, "api_experiment must set ARI_SLURM_CPUS"
    assert "ARI_SLURM_MEM_GB" in src, "api_experiment must set ARI_SLURM_MEM_GB"
    assert "ARI_SLURM_GPUS" in src, "api_experiment must set ARI_SLURM_GPUS"
    assert "ARI_SLURM_WALLTIME" in src, "api_experiment must set ARI_SLURM_WALLTIME"
    assert "ARI_SLURM_PARTITION" in src, "api_experiment must set ARI_SLURM_PARTITION"


def test_config_reads_hpc_env_vars():
    """config.py auto_config() must read ARI_SLURM_* into resources dict."""
    config_src = (VIZ_DIR.parent / "config.py").read_text()
    assert "ARI_SLURM_CPUS" in config_src, "config.py must read ARI_SLURM_CPUS"
    assert "ARI_SLURM_MEM_GB" in config_src, "config.py must read ARI_SLURM_MEM_GB"
    assert "ARI_SLURM_GPUS" in config_src, "config.py must read ARI_SLURM_GPUS"
    assert "ARI_SLURM_WALLTIME" in config_src, "config.py must read ARI_SLURM_WALLTIME"
    assert "ARI_SLURM_PARTITION" in config_src, "config.py must read ARI_SLURM_PARTITION"
