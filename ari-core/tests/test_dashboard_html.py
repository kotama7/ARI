"""Test dashboard.html HTML structure integrity."""
import re
from pathlib import Path

DASHBOARD = Path(__file__).parent.parent / "ari/viz/dashboard.html"


def _html_only(html: str) -> str:
    """Strip <script> blocks to get HTML-only content."""
    return re.sub(r"<script>.*?</script>", "", html, flags=re.DOTALL)


def test_dashboard_exists():
    assert DASHBOARD.exists(), "dashboard.html not found"


def test_dashboard_div_balance():
    """Every opening <div> must have a matching closing </div> (HTML-only)."""
    html = _html_only(DASHBOARD.read_text())
    opens = len(re.findall(r"<div[\s>]", html))
    closes = len(re.findall(r"</div>", html))
    assert opens == closes, f"Unbalanced divs: {opens} opens vs {closes} closes"


def test_page_new_div_balance():
    """page-new wizard must close properly before Settings section."""
    raw = DASHBOARD.read_text()
    html = _html_only(raw)
    idx_pn = html.find('<div class="page" id="page-new">')
    idx_st = html.find("<!-- SETTINGS -->")
    assert idx_pn > 0 and idx_st > 0
    chunk = html[idx_pn:idx_st]
    depth = sum(1 if chunk[i:i+4] == "<div" else (-1 if chunk[i:i+6] == "</div>" else 0) for i in range(len(chunk)))
    assert depth == 0, f"page-new not closed at SETTINGS: depth={depth}"


def test_page_settings_div_balance():
    html = _html_only(DASHBOARD.read_text())
    idx_s = html.find('id="page-settings"')
    idx_e = html.find('id="page-', idx_s + 10)
    chunk = html[idx_s:idx_e if idx_e > 0 else len(html)]
    depth = sum(1 if chunk[i:i+4] == "<div" else (-1 if chunk[i:i+6] == "</div>" else 0) for i in range(len(chunk)))
    assert depth == 0, f"page-settings imbalanced: depth={depth}"


def test_wizard_pages_exist():
    html = DASHBOARD.read_text()
    for step in range(1, 5):
        assert f'id="wiz-step-{step}"' in html, f"wiz-step-{step} missing"


def test_all_page_ids_exist():
    html = DASHBOARD.read_text()
    for page in ["home", "experiments", "monitor", "results", "new", "settings", "idea"]:
        assert f'id="page-{page}"' in html, f"page-{page} missing"


def test_no_hardcoded_domains():
    """No RIKEN/lab/person-specific content in dashboard HTML."""
    html = DASHBOARD.read_text().lower()
    banned = ["himeno", "/hs/work0", "kotama", "takanori.k"]
    found = [w for w in banned if w in html]
    assert not found, f"Hardcoded domain content in dashboard: {found}"


def test_key_js_functions_present():
    """Key JS functions must exist in dashboard.html or the companion dashboard.js."""
    html = DASHBOARD.read_text()
    js_file = DASHBOARD.parent / "static" / "dashboard.js"
    combined = html + (js_file.read_text() if js_file.exists() else "")
    for fn in ["function goto(", "function wizNext(", "function launchExperiment(", "function loadSettings("]:
        assert fn in combined, f"Missing JS function: {fn}"
