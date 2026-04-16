"""
ARI GUI Page Requirements Tests — verifies React component source code
and server-side API functions for the dashboard.
"""
from pathlib import Path
import re

VIZ_DIR = Path(__file__).parent.parent / "ari" / "viz"
FRONTEND_DIR = VIZ_DIR / "frontend"
SRC_DIR = FRONTEND_DIR / "src"
COMPONENTS_DIR = SRC_DIR / "components"
DIST_DIR = VIZ_DIR / "static" / "dist"

# Server-side Python sources
SERVER = (VIZ_DIR / "server.py").read_text()
API_EXPERIMENT = (VIZ_DIR / "api_experiment.py").read_text()
API_SETTINGS = (VIZ_DIR / "api_settings.py").read_text()
API_STATE = (VIZ_DIR / "api_state.py").read_text()
ALL_SERVER = SERVER + API_EXPERIMENT + API_SETTINGS + API_STATE


def _read_component(rel_path: str) -> str:
    """Read a component file relative to COMPONENTS_DIR."""
    return (COMPONENTS_DIR / rel_path).read_text()


# ── Page component tests ─────────────────────────────────


def test_home_page():
    src = _read_component("Home/HomePage.tsx")
    assert "useI18n" in src, "HomePage must use useI18n"
    assert "useAppContext" in src, "HomePage must use useAppContext"
    assert "checkpoints" in src, "HomePage must use checkpoints from context"


def test_experiments_page():
    src = _read_component("Experiments/ExperimentsPage.tsx")
    assert "useI18n" in src, "ExperimentsPage must use useI18n"
    assert "useAppContext" in src, "ExperimentsPage must use useAppContext"
    assert "checkpoints" in src, "ExperimentsPage must use checkpoints from context"
    assert "_api_checkpoints" in ALL_SERVER, "Server must expose _api_checkpoints"


def test_monitor_page():
    src = _read_component("Monitor/MonitorPage.tsx")
    assert "useI18n" in src, "MonitorPage must use useI18n"
    assert "useAppContext" in src, "MonitorPage must use useAppContext"
    assert "runStage" in src, "MonitorPage must import runStage"
    assert "PhaseStepper" in src, "MonitorPage must use PhaseStepper"
    assert "_api_logs_sse" in ALL_SERVER, "Server must expose _api_logs_sse"
    assert "ARI_BACKEND" in ALL_SERVER, "Server must reference ARI_BACKEND"
    assert "_last_log_path" in ALL_SERVER, "Server must track _last_log_path"


def test_monitor_ansi_strip():
    """ANSI escape codes must be stripped from SSE log output."""
    assert "x1b" in ALL_SERVER or "ansi" in ALL_SERVER.lower(), \
        "ANSI stripping not implemented in server"


def test_tree_page():
    src = _read_component("Tree/TreePage.tsx")
    assert "useI18n" in src, "TreePage must use useI18n"
    assert "useAppContext" in src, "TreePage must use useAppContext"
    assert "TreeVisualization" in src, "TreePage must use TreeVisualization"
    assert "DetailPanel" in src, "TreePage must use DetailPanel"


def test_results_page():
    src = _read_component("Results/ResultsPage.tsx")
    assert "useI18n" in src, "ResultsPage must use useI18n"
    assert "useAppContext" in src, "ResultsPage must use useAppContext"
    assert "checkpoints" in src, "ResultsPage must use checkpoints from context"


def test_wizard_page():
    src = _read_component("Wizard/WizardPage.tsx")
    assert "useI18n" in src, "WizardPage must use useI18n"
    assert "StepGoal" in src, "WizardPage must use StepGoal"
    assert "StepScope" in src, "WizardPage must use StepScope"
    assert "StepResources" in src, "WizardPage must use StepResources"
    assert "StepLaunch" in src, "WizardPage must use StepLaunch"


def test_step_resources_openai_models_include_dated_gpt4o_snapshot():
    """Wizard's OpenAI dropdown must offer the gpt-4o-2024-08-06 dated snapshot.

    The unversioned 'gpt-4o' alias dynamically routes to newer snapshots that
    some OpenAI projects do not have access to (returns misleading
    `missing_scope: model.request`). The dated `gpt-4o-2024-08-06` is a stable
    fallback that ARI users can pick to bypass that routing surprise.
    """
    src = _read_component("Wizard/StepResources.tsx")
    # Locate the openai array entry inside PROVIDER_MODELS
    m = re.search(r"openai\s*:\s*\[([^\]]*)\]", src)
    assert m, "PROVIDER_MODELS.openai array not found in StepResources.tsx"
    openai_models_blob = m.group(1)
    assert "'gpt-4o-2024-08-06'" in openai_models_blob \
        or '"gpt-4o-2024-08-06"' in openai_models_blob, (
            "gpt-4o-2024-08-06 must be selectable from the OpenAI provider dropdown; "
            f"found: {openai_models_blob}"
        )


def test_step_resources_does_not_call_fetch_settings():
    """StepResources must NOT call api.fetchSettings() inside its useEffect.

    Why this matters: StepResources is unmounted when the user navigates from
    Resources → Launch and re-mounted when they go back. If it re-loads
    settings on every mount, the user's manual model selection (e.g.
    `gpt-4o-2024-08-06`) gets clobbered by the value from settings.json
    (`gpt-5.2`) and the experiment launches with the wrong model.

    The settings load was lifted to WizardPage so it runs exactly once
    per WizardPage mount, regardless of step navigation.
    """
    src = _read_component("Wizard/StepResources.tsx")
    assert "fetchSettings" not in src, (
        "StepResources.tsx must not call fetchSettings — that would re-clobber "
        "the user's model selection on every step remount. The load was moved "
        "to WizardPage.tsx for one-time initialization."
    )


def test_wizard_page_loads_settings_once():
    """WizardPage must load settings exactly once per mount via fetchSettings,
    guarded by a ref so the load survives StepResources remounts."""
    src = _read_component("Wizard/WizardPage.tsx")
    assert "fetchSettings" in src, (
        "WizardPage.tsx must call api.fetchSettings to pre-populate llm/model "
        "from settings.json on initial mount"
    )
    # The ref-guard pattern is the key invariant: it makes the load idempotent
    # even under React StrictMode double-invocation.
    assert "settingsLoadedRef" in src or "useRef" in src, (
        "WizardPage.tsx must use a ref guard to ensure fetchSettings runs only "
        "once per mount (otherwise React StrictMode or re-renders would refire it)"
    )
    assert "PROVIDER_MODELS" in src, (
        "WizardPage.tsx must import PROVIDER_MODELS from StepResources to "
        "validate the loaded model name against the dropdown options"
    )


def test_idea_page():
    src = _read_component("Idea/IdeaPage.tsx")
    assert "useI18n" in src, "IdeaPage must use useI18n"
    assert "useAppContext" in src, "IdeaPage must use useAppContext"
    assert "experiment_md_content" in ALL_SERVER, \
        "Server must expose experiment_md_content"


def test_settings_page():
    src = _read_component("Settings/SettingsPage.tsx")
    assert "useI18n" in src, "SettingsPage must use useI18n"
    assert "useAppContext" in src, "SettingsPage must use useAppContext"
    assert "fetchSettings" in src, "SettingsPage must call fetchSettings"
    assert "saveSettings" in src or "apiSaveSettings" in src, \
        "SettingsPage must call saveSettings"
    assert "_api_save_settings" in ALL_SERVER, "Server must expose _api_save_settings"
    assert "_api_get_settings" in ALL_SERVER, "Server must expose _api_get_settings"


def test_workflow_page():
    src = _read_component("Workflow/WorkflowPage.tsx")
    assert "useI18n" in src, "WorkflowPage must use useI18n"
    assert "fetchWorkflow" in src, "WorkflowPage must call fetchWorkflow"
    assert "saveWorkflow" in src or "apiSaveWorkflow" in src, \
        "WorkflowPage must call saveWorkflow"
    assert "_api_get_workflow" in ALL_SERVER, "Server must expose _api_get_workflow"
    assert "_api_save_workflow" in ALL_SERVER, "Server must expose _api_save_workflow"


# ── Server-side API tests ────────────────────────────────


def test_server_ari_backend_from_settings():
    """settings llm_provider must be injected as ARI_BACKEND."""
    assert 'proc_env["ARI_BACKEND"] = llm_provider' in API_EXPERIMENT


def test_server_running_status_uses_pid():
    """Running status must check actual PID, not just file presence."""
    assert "_last_proc" in ALL_SERVER and ".poll() is None" in ALL_SERVER


def test_server_exit_code_and_error():
    """Server must expose exit_code and produce Error status_label."""
    assert "exit_code" in ALL_SERVER, "Server does not expose exit_code"
    assert "Error" in ALL_SERVER, "Server does not produce Error status_label"


# ── i18n tests ───────────────────────────────────────────


def test_i18n_three_languages():
    """All three translation files must exist and be imported."""
    i18n_index = (SRC_DIR / "i18n" / "index.ts").read_text()
    for lang in ["en", "ja", "zh"]:
        assert (SRC_DIR / "i18n" / f"{lang}.ts").exists(), \
            f"Missing i18n/{lang}.ts"
        assert lang in i18n_index, \
            f"Language '{lang}' not imported in i18n/index.ts"


def test_i18n_no_circular_refs():
    """English translation file must not contain circular t() calls."""
    en_src = (SRC_DIR / "i18n" / "en.ts").read_text()
    assert "t('" not in en_src, "Circular t() call in en.ts"


# ── CSS tests ────────────────────────────────────────────


def test_stepper_error_css():
    """CSS must have .phase-step.error style."""
    css_path = SRC_DIR / "styles" / "dashboard.css"
    css = css_path.read_text() if css_path.exists() else ""
    assert ".phase-step.error" in css, "Missing .phase-step.error CSS rule"


