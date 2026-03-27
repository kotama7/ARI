"""
ARI Data Flow Integration Tests
Tests the full data contract between server.py and dashboard.html
"""
import json, os, re
from pathlib import Path

DASHBOARD = Path(__file__).parent.parent / "ari/viz/dashboard.html"
SERVER = Path(__file__).parent.parent / "ari/viz/server.py"


def _html():
    return DASHBOARD.read_text()


def _server():
    return SERVER.read_text()


# ── Wizard ──────────────────────────────────────────────────────────────────

def test_wizard_provider_default_empty():
    """launchExperiment sends empty string (not 'openai') when user hasn't set provider."""
    from pathlib import Path
    js_file = Path(_html.__code__.co_consts[0] if False else "").parent if False else Path(__file__).parent.parent / "ari/viz/static/dashboard.js"
    combined = _html() + (js_file.read_text() if js_file.exists() else "")
    idx = combined.find("llm_provider:(document.getElementById")
    assert idx > 0, "llm_provider line not found in launchExperiment"
    line = combined[idx:idx+120]
    assert "||''" in line or '||""' in line, f"Default should be empty string: {line}"


def test_wizard_wiz_llm_provider_hidden_exists():
    """Hidden wiz-llm-provider input must exist for JS to sync."""
    assert 'id="wiz-llm-provider"' in _html()


def test_wizard_provider_initial_value_empty():
    """wiz-llm-provider initial value must be '' (not 'openai')."""
    html = _html()
    idx = html.find('id="wiz-llm-provider"')
    chunk = html[idx:idx+60]
    assert 'value=""' in chunk or "value=''" in chunk, f"Expected empty initial value: {chunk}"


def test_wizard_setllm_syncs_provider():
    """setLLM() must update wiz-llm-provider hidden input."""
    html = _html()
    idx = html.find('function setLLM(l){')
    end = html.find('\n}', idx) + 2
    body = html[idx:end]
    assert 'wiz-llm-provider' in body, "setLLM must update wiz-llm-provider"
    assert 'hp.value=l' in body or ".value = l" in body, "setLLM must set value"


def test_wizard_step3_prefills_from_settings():
    """wizNext must contain settings fetch + setLLM call for step 3."""
    html = _html()
    assert "fetch('/api/settings')" in html, "missing settings fetch"
    # Find the occurrence that is followed by setLLM
    idx = 0
    found = False
    while True:
        idx = html.find("fetch('/api/settings')", idx)
        if idx < 0:
            break
        chunk = html[idx:idx+300]
        if "setLLM(" in chunk:
            found = True
            break
        idx += 1
    assert found, "No settings fetch followed by setLLM() found in wizard"


def test_wizard_ollama_free_text():
    """Ollama provider must show free-text model input."""
    html = _html()
    assert 'id="wiz-llm-model-custom"' in html


# ── Server: ARI_BACKEND ────────────────────────────────────────────────────

def test_server_ari_backend_from_settings():
    """_api_launch must set ARI_BACKEND from settings llm_provider."""
    assert 'proc_env["ARI_BACKEND"] = llm_provider' in _server()


def test_server_ari_backend_not_overridden_when_empty():
    """Wizard's ARI_BACKEND only applied if wiz_provider is non-empty."""
    server = _server()
    idx = server.find('proc_env["ARI_BACKEND"] = wiz_provider')
    assert idx > 0
    # The line should be inside an if wiz_provider: block
    context = server[max(0, idx-100):idx]
    assert 'if wiz_provider:' in context or 'if wiz_provider' in context


# ── Server: State ──────────────────────────────────────────────────────────

def test_server_experiment_md_fallback_cwd():
    """State handler falls back to cwd/experiment.md when checkpoint not set."""
    server = _server()
    assert 'cwd() / "experiment.md"' in server
    assert '_last_experiment_md' in server


def test_server_no_iterdir_running_status():
    """Checkpoint status must NOT be based on file existence (iterdir)."""
    assert 'any(d.iterdir())' not in _server()


def test_server_log_file_switches():
    """SSE log stream re-resolves log file each iteration for multi-experiment support."""
    server = _server()
    assert 'Switched to log' in server
    assert 'last_log_seen' in server or 'last_log_path' in server


def test_server_ansi_strip_in_sse():
    """ANSI escape codes are stripped before sending to browser."""
    assert r'\x1b' in _server()


# ── i18n ──────────────────────────────────────────────────────────────────

def test_i18n_no_circular_refs():
    """en i18n dict must not call t() (circular reference)."""
    html = _html()
    m = re.search(r"en:\s*\{(.+?)\n  \}", html, re.DOTALL)
    if m:
        assert "t('" not in m.group(1), "Circular t() in en dict"


def test_i18n_default_lang_ja():
    """Default language should be 'ja'."""
    assert "|| 'ja'" in _html()


def test_i18n_nav_items_have_data_i18n():
    """All sidebar nav items must use data-i18n for translations."""
    html = _html()
    for key in ['nav_home', 'nav_monitor', 'nav_tree', 'nav_results', 'nav_settings', 'nav_idea']:
        assert f'data-i18n="{key}"' in html, f"Missing data-i18n={key}"


# ── Results page ──────────────────────────────────────────────────────────

def test_results_repro_error_handled():
    """Reproducibility skill error shows friendly message, not raw error."""
    html = _html()
    assert 'Available: []' in html or 'not found' in html or 'ari-skill-paper-re' in html


def test_results_no_score_question_mark():
    """Results dropdown must not show 'score:?' for experiments without papers."""
    html = _html()
    func_idx = html.find('function populateResultsDropdown')
    func_end = html.find('\n}', func_idx) + 2
    func_body = html[func_idx:func_end]
    assert "score:'?'" not in func_body and 'score:?' not in func_body


# ── HTML structure ────────────────────────────────────────────────────────

def test_html_div_balance():
    html_only = re.sub(r'<script>.*?</script>', '', _html(), flags=re.DOTALL)
    opens = len(re.findall(r'<div[\s>]', html_only))
    closes = len(re.findall(r'</div>', html_only))
    assert opens == closes, f"Unbalanced divs: {opens}/{closes}"
