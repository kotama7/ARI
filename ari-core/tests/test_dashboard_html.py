"""Test React dashboard structure integrity."""
import re
from pathlib import Path

VIZ_DIR = Path(__file__).parent.parent / "ari" / "viz"
FRONTEND_DIR = VIZ_DIR / "frontend"
SRC_DIR = FRONTEND_DIR / "src"
COMPONENTS_DIR = SRC_DIR / "components"
DIST_DIR = VIZ_DIR / "static" / "dist"


def test_react_build_exists():
    """The Vite build must produce static/dist/index.html."""
    assert (DIST_DIR / "index.html").exists(), "dist/index.html not found"


def test_react_source_exists():
    """The React entry point App.tsx must exist."""
    assert (SRC_DIR / "App.tsx").exists(), "frontend/src/App.tsx not found"


def test_all_page_components_exist():
    """Every page component file must exist under src/components/."""
    pages = {
        "Home/HomePage.tsx",
        "Experiments/ExperimentsPage.tsx",
        "Monitor/MonitorPage.tsx",
        "Tree/TreePage.tsx",
        "Results/ResultsPage.tsx",
        "Wizard/WizardPage.tsx",
        "Idea/IdeaPage.tsx",
        "Workflow/WorkflowPage.tsx",
        "Settings/SettingsPage.tsx",
    }
    missing = [p for p in pages if not (COMPONENTS_DIR / p).exists()]
    assert not missing, f"Missing page components: {missing}"


def test_wizard_step_components_exist():
    """Wizard step sub-components must exist."""
    steps = ["StepGoal.tsx", "StepScope.tsx", "StepResources.tsx", "StepLaunch.tsx"]
    missing = [s for s in steps if not (COMPONENTS_DIR / "Wizard" / s).exists()]
    assert not missing, f"Missing wizard step components: {missing}"


def test_key_react_components_present():
    """Critical React components/hooks must exist in the source tree."""
    app_src = (SRC_DIR / "App.tsx").read_text()
    context_src = (SRC_DIR / "context" / "AppContext.tsx").read_text()
    i18n_src = (SRC_DIR / "i18n" / "index.ts").read_text()

    assert "AppProvider" in app_src, "App.tsx must use AppProvider"
    assert "useAppContext" in context_src, "AppContext must export useAppContext"
    assert "useI18n" in i18n_src, "i18n/index.ts must export useI18n"


def test_i18n_files_exist():
    """Translation files for en, ja, zh must exist."""
    i18n_dir = SRC_DIR / "i18n"
    for lang in ["en.ts", "ja.ts", "zh.ts"]:
        assert (i18n_dir / lang).exists(), f"Missing i18n file: {lang}"


def test_build_has_assets():
    """The Vite build must produce .js and .css files in dist/assets/."""
    assets_dir = DIST_DIR / "assets"
    assert assets_dir.exists(), "dist/assets/ directory not found"
    js_files = list(assets_dir.glob("*.js"))
    css_files = list(assets_dir.glob("*.css"))
    assert js_files, "No .js files in dist/assets/"
    assert css_files, "No .css files in dist/assets/"
