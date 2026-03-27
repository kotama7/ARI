"""
ARI GUI Page Requirements Tests — auto-generated from audit script.
"""
from pathlib import Path
import pytest

HTML = (Path(__file__).parent.parent / "ari/viz/dashboard.html").read_text()
SERVER = (Path(__file__).parent.parent / "ari/viz/server.py").read_text()

def test_home_page():
    assert 'id="page-home"' in HTML
    assert 'id="home-total-runs"' in HTML
    assert 'id="home-best-score"' in HTML
    assert 'id="home-total-nodes"' in HTML
    assert 'id="home-latest"' in HTML

def test_experiments_page():
    assert 'id="page-experiments"' in HTML
    assert 'id="exp-table-wrap"' in HTML
    assert "loadExperiments" in HTML
    assert "_api_checkpoints" in SERVER

def test_monitor_page():
    assert 'id="page-monitor"' in HTML
    assert 'id="log-output"' in HTML
    assert "startLogStream" in HTML
    assert "_api_logs_sse" in SERVER
    assert 'id="mon-idea-text"' in HTML
    assert "runStage" in HTML
    assert 'id="phase-stepper"' in HTML
    assert "ARI_BACKEND" in SERVER
    assert "_last_log_path" in SERVER

def test_monitor_ansi_strip():
    """ANSI escape codes must be stripped from SSE log output."""
    assert "x1b" in SERVER or "ansi" in SERVER.lower(), "ANSI stripping not implemented"

def test_tree_page():
    assert 'id="page-tree"' in HTML
    assert 'id="tree-d3-svg"' in HTML
    assert "renderTree" in HTML
    assert 'id="detail-panel"' in HTML
    assert "closeDetail" in HTML

def test_results_page():
    assert 'id="page-results"' in HTML
    assert 'id="results-ckpt-select"' in HTML
    assert "populateResultsDropdown" in HTML
    assert "loadResults" in HTML
    # score:? removed
    assert "score:?" not in HTML
    # reproduce error handled
    assert "Available: []" in HTML and "スキル" in HTML

def test_new_experiment_wizard():
    assert 'id="page-new"' in HTML
    for i in range(1, 5):
        assert f'id="wiz-step-{i}"' in HTML
    assert "wizNext" in HTML
    assert "launchExperiment" in HTML
    assert 'id="wiz-llm-provider"' in HTML
    assert 'id="wiz-llm-model"' in HTML
    assert 'id="wiz-llm-model-custom"' in HTML
    assert "setLLM" in HTML

def test_wizard_provider_default_empty():
    """Provider must default to empty string (not openai) to avoid overriding settings."""
    assert "||''," in HTML or "|| ''," in HTML or "||'')" in HTML or "|| '')" in HTML

def test_wizard_step3_prefills_from_settings():
    """Step 3 must fetch /api/settings and call setLLM with saved provider."""
    assert "/api/settings" in HTML and "step===3" in HTML

def test_idea_page():
    assert 'id="page-idea"' in HTML
    assert 'id="idea-config-content"' in HTML
    assert 'id="idea-goal"' in HTML
    assert "loadIdeaPage" in HTML
    assert "experiment_md_content" in SERVER
    assert "Path.cwd()" in SERVER  # cwd fallback

def test_settings_page():
    assert 'id="page-settings"' in HTML
    assert 'id="s-provider"' in HTML
    assert 'id="s-model-select"' in HTML
    assert "saveSettings" in HTML
    assert "loadSettings" in HTML
    assert "_api_save_settings" in SERVER
    assert "_api_get_settings" in SERVER

def test_workflow_page():
    assert 'id="page-workflow"' in HTML
    assert "loadWorkflow" in HTML
    assert "saveWorkflow" in HTML
    assert 'id="wf-dag"' in HTML
    assert "_api_get_workflow" in SERVER
    assert "_api_save_workflow" in SERVER

def test_server_ari_backend_from_settings():
    """settings llm_provider must be injected as ARI_BACKEND."""
    assert 'proc_env["ARI_BACKEND"] = llm_provider' in SERVER

def test_server_running_status_uses_pid():
    """Running status must check actual PID, not just file presence."""
    assert "_last_proc and _last_proc.poll() is None" in SERVER

def test_i18n_three_languages():
    assert "'en'" in HTML and "'ja'" in HTML and "'zh'" in HTML

def test_i18n_no_circular_refs():
    import re
    m = re.search(r"en:\s*\{(.+?)\n  \}", HTML, re.DOTALL)
    if m:
        en_block = m.group(1)
        assert "t('" not in en_block, "Circular t() call in en dict"

def test_no_hardcoded_domain():
    for banned in ["himeno", "/hs/work0", "takanori.k"]:
        assert banned not in HTML.lower(), f"Hardcoded domain in HTML: {banned}"
