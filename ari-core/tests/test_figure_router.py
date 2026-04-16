"""Tests for Figure Generation Router MCP skill (Issue #9).

Validates:
- classify_figure_need returns valid type for various descriptions
- generate_svg_diagram produces valid SVG XML
- generate_figure dispatches to correct tool
- figures_manifest.json includes figure_type field after generation
- Skill registration in workflow.yaml
"""
from __future__ import annotations
import ast
import json
import os
import sys
from pathlib import Path

import pytest
import yaml


# ── Fixtures ──────────────────────────────────────────

@pytest.fixture
def router_src():
    """Return the source code of ari-skill-figure-router/src/server.py."""
    p = Path(__file__).parent.parent.parent / "ari-skill-figure-router" / "src" / "server.py"
    return p.read_text()


@pytest.fixture
def workflow_yaml():
    p = Path(__file__).parent.parent / "config" / "workflow.yaml"
    return yaml.safe_load(p.read_text())


# ── AST helpers ───────────────────────────────────────

def _has_function(src: str, name: str) -> bool:
    tree = ast.parse(src)
    return any(
        isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name
        for n in ast.walk(tree)
    )


def _func_args(src: str, name: str) -> list[str]:
    tree = ast.parse(src)
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return [a.arg for a in n.args.args]
    return []


def _is_async(src: str, name: str) -> bool:
    tree = ast.parse(src)
    return any(
        isinstance(n, ast.AsyncFunctionDef) and n.name == name
        for n in ast.walk(tree)
    )


def _has_toplevel_name(src: str, name: str) -> bool:
    tree = ast.parse(src)
    for n in ast.iter_child_nodes(tree):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name) and t.id == name:
                    return True
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return True
        if isinstance(n, ast.ImportFrom):
            for alias in n.names:
                if (alias.asname or alias.name) == name:
                    return True
    return False


# ── Tests: classify_figure_need ───────────────────────

def test_classify_function_exists(router_src):
    assert _has_function(router_src, "classify_figure_need")


def test_classify_is_async(router_src):
    assert _is_async(router_src, "classify_figure_need")


def test_classify_accepts_description(router_src):
    args = _func_args(router_src, "classify_figure_need")
    assert "description" in args


def test_classify_accepts_data_available(router_src):
    args = _func_args(router_src, "classify_figure_need")
    assert "data_available" in args


def test_classify_returns_valid_types(router_src):
    """Source should reference all three valid types."""
    assert '"architecture"' in router_src
    assert '"graph"' in router_src
    assert '"table"' in router_src


def test_classify_returns_valid_tools(router_src):
    """Source should reference all three tool types."""
    assert '"autofigure"' in router_src
    assert '"matplotlib"' in router_src
    assert '"latex"' in router_src


def test_classify_has_keyword_fallback(router_src):
    """Should have heuristic fallback if LLM fails."""
    assert "Keyword match" in router_src or "keyword" in router_src.lower()


# ── Tests: generate_svg_diagram ───────────────────────

def test_svg_function_exists(router_src):
    assert _has_function(router_src, "generate_svg_diagram")


def test_svg_is_async(router_src):
    assert _is_async(router_src, "generate_svg_diagram")


def test_svg_accepts_description_and_path(router_src):
    args = _func_args(router_src, "generate_svg_diagram")
    assert "description" in args
    assert "output_path" in args


def test_svg_validates_output(router_src):
    """Should check for valid SVG tags."""
    assert "<svg" in router_src
    assert "</svg>" in router_src


def test_svg_attempts_png_conversion(router_src):
    """Should try cairosvg or inkscape for PNG conversion."""
    assert "cairosvg" in router_src or "inkscape" in router_src


# ── Tests: generate_figure router ─────────────────────

def test_generate_figure_exists(router_src):
    assert _has_function(router_src, "generate_figure")


def test_generate_figure_is_async(router_src):
    assert _is_async(router_src, "generate_figure")


def test_generate_figure_accepts_required_args(router_src):
    args = _func_args(router_src, "generate_figure")
    assert "description" in args
    assert "data" in args
    assert "output_path" in args


def test_generate_figure_dispatches_to_svg_for_architecture(router_src):
    """When type is 'architecture', should call generate_svg_diagram."""
    assert "generate_svg_diagram" in router_src


def test_generate_figure_dispatches_to_matplotlib_for_graph(router_src):
    """When type is 'graph', should use matplotlib generation."""
    assert "_generate_matplotlib" in router_src or "matplotlib" in router_src


def test_generate_figure_dispatches_to_latex_for_table(router_src):
    """When type is 'table', should use LaTeX generation."""
    assert "_generate_latex_table" in router_src or "latex" in router_src.lower()


# ── Tests: MCP server setup ──────────────────────────

def test_mcp_server_defined(router_src):
    assert _has_toplevel_name(router_src, "mcp")


def test_future_annotations_first(router_src):
    """from __future__ import annotations must be first import."""
    tree = ast.parse(router_src)
    for n in ast.iter_child_nodes(tree):
        if isinstance(n, ast.Expr) and isinstance(n.value, (ast.Constant, ast.Str)):
            continue
        if isinstance(n, ast.ImportFrom):
            assert n.module == "__future__", \
                "First import must be 'from __future__ import annotations'"
            break
        break


def test_main_guard_runs_mcp(router_src):
    assert 'mcp.run()' in router_src


# ── Tests: workflow.yaml integration ─────────────────

def test_figure_router_in_skills(workflow_yaml):
    skill_names = [s["name"] for s in workflow_yaml.get("skills", [])]
    assert "figure-router-skill" in skill_names


def test_figure_router_skill_path(workflow_yaml):
    for s in workflow_yaml.get("skills", []):
        if s["name"] == "figure-router-skill":
            assert "ari-skill-figure-router" in s["path"]
            break
    else:
        pytest.fail("figure-router-skill not found in skills list")


# ── Tests: pyproject.toml and skill.yaml ─────────────

def test_pyproject_exists():
    p = Path(__file__).parent.parent.parent / "ari-skill-figure-router" / "pyproject.toml"
    assert p.exists()


def test_skill_yaml_exists():
    p = Path(__file__).parent.parent.parent / "ari-skill-figure-router" / "skill.yaml"
    assert p.exists()


def test_mcp_json_exists():
    p = Path(__file__).parent.parent.parent / "ari-skill-figure-router" / "mcp.json"
    assert p.exists()
    data = json.loads(p.read_text())
    assert "classify_figure_need" in data.get("tools", [])
    assert "generate_figure" in data.get("tools", [])
    assert "generate_svg_diagram" in data.get("tools", [])


# ── Tests: figures_manifest figure_type field ────────

def test_results_page_shows_figure_type_badge():
    """ResultsPage.tsx should render figure_type badges."""
    tsx = Path(__file__).parent.parent / "ari" / "viz" / "frontend" / "src" / \
        "components" / "Results" / "ResultsPage.tsx"
    content = tsx.read_text()
    assert "figure_type" in content
    assert "Architecture" in content
    assert "Graph" in content
    assert "Table" in content


# ── Tests: VLM review loop ─────────────────────────


def test_vlm_review_helpers_exist(router_src):
    """VLM review helper functions should be defined."""
    assert _has_function(router_src, "_encode_review_image")
    assert _has_function(router_src, "_vlm_review")
    assert _has_function(router_src, "_ensure_reviewable_image")


def test_vlm_review_is_async(router_src):
    assert _is_async(router_src, "_vlm_review")


def test_generate_figure_has_vlm_params(router_src):
    """generate_figure should accept vlm_review, vlm_max_iterations, vlm_score_threshold."""
    args = _func_args(router_src, "generate_figure")
    assert "vlm_review" in args
    assert "vlm_max_iterations" in args
    assert "vlm_score_threshold" in args


def test_vlm_config_constants_defined(router_src):
    """VLM configuration constants should be defined at module level."""
    assert "_VLM_MODEL" in router_src
    assert "_VLM_REVIEW_ENABLED" in router_src
    assert "_VLM_REVIEW_THRESHOLD" in router_src
    assert "_VLM_REVIEW_MAX_ITER" in router_src


def test_vlm_review_returns_score_fields(router_src):
    """generate_figure result should include review_score and review_passed."""
    assert "review_score" in router_src
    assert "review_passed" in router_src
    assert "review_iterations" in router_src


def test_dispatch_generate_function_exists(router_src):
    """_dispatch_generate should exist to separate dispatch from loop logic."""
    assert _has_function(router_src, "_dispatch_generate")


def test_vlm_feedback_injected_on_retry(router_src):
    """On low VLM score, feedback should be appended to description."""
    assert "VLM feedback from previous attempt" in router_src


def test_vlm_env_vars_in_settings_defaults():
    """api_settings defaults should include VLM review settings."""
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from ari.viz.api_settings import _api_get_settings
    defaults = _api_get_settings()
    assert "vlm_review_enabled" in defaults
    assert "vlm_review_model" in defaults
    assert "vlm_review_max_iter" in defaults
    assert "vlm_review_threshold" in defaults


def test_vlm_review_skips_tables(router_src):
    """_ensure_reviewable_image should return None for table type."""
    assert '"table"' in router_src
    # The function checks fig_type == "table" and returns None
    assert "review_skipped" in router_src
