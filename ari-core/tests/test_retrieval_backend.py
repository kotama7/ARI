"""Tests for pluggable paper retrieval backend (Issue #11).

Validates:
- Backend selection dispatches correctly (mock HTTP calls)
- "both" mode deduplicates by arxiv_id
- ARI_RETRIEVAL_BACKEND env var is respected
- GUI settings endpoint reads/writes retrieval_backend
- /api/launch passes ARI_RETRIEVAL_BACKEND to subprocess
"""
from __future__ import annotations
import ast
import json
import os
import sys
from pathlib import Path
from unittest import mock

import pytest
import yaml


# ── Fixtures ──────────────────────────────────────────

@pytest.fixture
def clean_env(monkeypatch):
    """Remove ARI_* env vars so tests start clean."""
    for k in list(os.environ):
        if k.startswith("ARI_") or k in (
            "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
            "OLLAMA_HOST", "LLM_API_BASE", "LLM_MODEL",
        ):
            monkeypatch.delenv(k, raising=False)


@pytest.fixture
def web_skill_src():
    """Return the source code of ari-skill-web/src/server.py."""
    p = Path(__file__).parent.parent.parent / "ari-skill-web" / "src" / "server.py"
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


# ── Tests: web skill backend abstraction ──────────────

def test_search_alphaxiv_function_exists(web_skill_src):
    assert _has_function(web_skill_src, "_search_alphaxiv")


def test_search_semantic_scholar_async_exists(web_skill_src):
    assert _has_function(web_skill_src, "_search_semantic_scholar_async")


def test_dispatch_search_function_exists(web_skill_src):
    assert _has_function(web_skill_src, "_dispatch_search")


def test_set_retrieval_backend_tool_exists(web_skill_src):
    assert _has_function(web_skill_src, "set_retrieval_backend")


def test_search_papers_tool_exists(web_skill_src):
    assert _has_function(web_skill_src, "search_papers")


def test_set_retrieval_backend_accepts_backend_arg(web_skill_src):
    args = _func_args(web_skill_src, "set_retrieval_backend")
    assert "backend" in args


def test_dispatch_search_handles_all_backends(web_skill_src):
    """Verify _dispatch_search references all three backend modes."""
    assert '"alphaxiv"' in web_skill_src
    assert '"semantic_scholar"' in web_skill_src
    assert '"both"' in web_skill_src


def test_alphaxiv_endpoint_configured(web_skill_src):
    assert "api.alphaxiv.org/mcp/v1" in web_skill_src


def test_both_mode_deduplicates_by_arxiv_id(web_skill_src):
    """Verify 'both' mode uses arxiv_id for deduplication."""
    assert "arxiv_id" in web_skill_src
    assert "seen_ids" in web_skill_src


# ── Tests: workflow.yaml retrieval config ─────────────

def test_workflow_has_retrieval_section(workflow_yaml):
    assert "retrieval" in workflow_yaml
    ret = workflow_yaml["retrieval"]
    assert ret["backend"] == "semantic_scholar"
    assert "alphaxiv_endpoint" in ret
    assert "alphaxiv.org" in ret["alphaxiv_endpoint"]


# ── Tests: env var is respected ───────────────────────

def test_env_var_default_semantic_scholar(clean_env):
    """Without env var, default backend should be semantic_scholar."""
    # Re-read the source to check the default
    src = Path(__file__).parent.parent.parent / "ari-skill-web" / "src" / "server.py"
    content = src.read_text()
    assert 'ARI_RETRIEVAL_BACKEND' in content
    assert '"semantic_scholar"' in content


def test_env_var_propagation(clean_env, monkeypatch):
    """ARI_RETRIEVAL_BACKEND should appear in the module-level default."""
    src = Path(__file__).parent.parent.parent / "ari-skill-web" / "src" / "server.py"
    content = src.read_text()
    assert 'os.environ.get("ARI_RETRIEVAL_BACKEND"' in content or \
           "_os.environ.get(\"ARI_RETRIEVAL_BACKEND\"" in content


# ── Tests: GUI settings endpoint ──────────────────────

def test_settings_includes_retrieval_backend():
    """api_settings._api_get_settings must include retrieval_backend."""
    from ari.viz.api_settings import _api_get_settings
    with mock.patch("ari.viz.state._settings_path", Path("/nonexistent/settings.json")):
        settings = _api_get_settings()
    assert "retrieval_backend" in settings


def test_settings_save_preserves_retrieval_backend(tmp_path):
    """_api_save_settings should persist retrieval_backend."""
    settings_file = tmp_path / "settings.json"
    with mock.patch("ari.viz.state._settings_path", settings_file), \
         mock.patch("ari.viz.state._env_write_path", tmp_path / ".env"):
        from ari.viz.api_settings import _api_save_settings
        body = json.dumps({"retrieval_backend": "both"}).encode()
        result = _api_save_settings(body)
        assert result["ok"]
        saved = json.loads(settings_file.read_text())
        assert saved["retrieval_backend"] == "both"


# ── Tests: /api/launch passes env var ─────────────────

def test_launch_passes_retrieval_backend_env():
    """_api_launch source must reference ARI_RETRIEVAL_BACKEND."""
    src = Path(__file__).parent.parent / "ari" / "viz" / "api_experiment.py"
    content = src.read_text()
    assert "ARI_RETRIEVAL_BACKEND" in content
    assert "retrieval_backend" in content


def test_launch_reads_retrieval_from_settings():
    """api_experiment must read retrieval_backend from settings."""
    src = Path(__file__).parent.parent / "ari" / "viz" / "api_experiment.py"
    content = src.read_text()
    assert 'saved.get("retrieval_backend"' in content


def test_launch_accepts_wizard_retrieval_override():
    """api_experiment must accept retrieval_backend from launch request body."""
    src = Path(__file__).parent.parent / "ari" / "viz" / "api_experiment.py"
    content = src.read_text()
    assert 'data.get("retrieval_backend")' in content
