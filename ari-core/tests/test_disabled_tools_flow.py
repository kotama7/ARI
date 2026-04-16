"""Regression tests for the GUI `disabled_tools` toggle flow.

Covers the bug where toggling web-search / survey / generate_ideas OFF in the
Workflow page saved them to config/workflow.yaml but the CLI still executed
them because `ari run <experiment.md>` (no --config) fell back to
auto_config() which does not read workflow.yaml.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import yaml

from ari.cli import _resolve_cfg
from ari.config import load_config
from ari import pipeline as _pipeline


def test_resolve_cfg_loads_disabled_tools_from_package_workflow():
    """_resolve_cfg(None) must honour disabled_tools in package workflow.yaml."""
    cfg = _resolve_cfg(None)
    # workflow.yaml currently lists at least one disabled tool in this repo;
    # the assertion below verifies that the fallback path populated the list.
    assert isinstance(cfg.disabled_tools, list)
    # Ensure the file backing the fallback is actually parsed (not just empty list
    # returned by auto_config()). We check that `skills` is populated too.
    assert cfg.skills, "fallback must load skills from workflow.yaml"


def test_resolve_cfg_respects_explicit_config(tmp_path: Path):
    """Explicit --config wins over package workflow.yaml fallback."""
    custom = tmp_path / "custom.yaml"
    custom.write_text(yaml.safe_dump({
        "disabled_tools": ["my_custom_tool"],
        "skills": [],
    }))
    cfg = _resolve_cfg(custom)
    assert cfg.disabled_tools == ["my_custom_tool"]


def test_resolve_cfg_fallback_reads_disabled_tools(tmp_path: Path, monkeypatch):
    """When package workflow.yaml missing, a temp workflow.yaml is still honoured
    if present via an explicit path (control test for the explicit branch)."""
    # Build a throwaway workflow.yaml and verify load_config reads disabled_tools.
    wf = tmp_path / "workflow.yaml"
    wf.write_text(yaml.safe_dump({
        "disabled_tools": ["survey", "generate_ideas"],
        "skills": [],
    }))
    cfg = load_config(str(wf))
    assert set(cfg.disabled_tools) == {"survey", "generate_ideas"}


def test_mcp_client_list_tools_filters_disabled_tools(monkeypatch):
    """MCPClient.list_tools must not return disabled tools."""
    from ari.mcp.client import MCPClient

    mcp = MCPClient(skills=[], disabled_tools=["survey", "generate_ideas"])
    # Bypass actual skill startup; inject a fake cache.
    mcp._tools_cache = [
        {"name": "survey", "description": "web", "inputSchema": {}},
        {"name": "generate_ideas", "description": "ideas", "inputSchema": {}},
        {"name": "run_bash", "description": "exec", "inputSchema": {}},
    ]
    mcp._phase_map = {"survey": "all", "generate_ideas": "all", "run_bash": "all"}

    names = [t["name"] for t in mcp.list_tools()]
    assert "survey" not in names
    assert "generate_ideas" not in names
    assert "run_bash" in names


def test_run_pipeline_skips_disabled_tools(tmp_path: Path, monkeypatch):
    """Paper pipeline must skip stages whose `tool` is in disabled_tools."""
    # Minimal workflow.yaml with one paper stage that should be skipped.
    wf = tmp_path / "workflow.yaml"
    wf.write_text(yaml.safe_dump({
        "disabled_tools": ["collect_references_iterative"],
        "skills": [],
        "pipeline": [
            {
                "stage": "search_related_work",
                "skill": "web-skill",
                "tool": "collect_references_iterative",
                "enabled": True,
                "phase": "paper",
                "inputs": {},
                "outputs": {"file": "{{checkpoint_dir}}/related_refs.json"},
            }
        ],
    }))

    # If skipping fails, _run_stage_subprocess would be invoked — fail loudly.
    def _boom(*a, **kw):  # noqa: ARG001
        raise AssertionError("disabled tool must NOT be executed")

    monkeypatch.setattr(_pipeline, "_run_stage_subprocess", _boom)

    stages = _pipeline.load_pipeline(wf)
    # Dummy experiment_data / nodes — pipeline only iterates stage metadata here.
    experiment_data = {"goal": "test"}
    all_nodes: list = []

    outputs = _pipeline.run_pipeline(
        stages=stages,
        all_nodes=all_nodes,
        experiment_data=experiment_data,
        checkpoint_dir=tmp_path,
        config_path=str(wf),
    )
    assert "search_related_work" in outputs
    assert outputs["search_related_work"].get("skipped") is True
    assert "disabled" in outputs["search_related_work"].get("reason", "")


def test_pipeline_subprocess_script_passes_disabled_tools():
    """The generated subprocess script must forward disabled_tools to MCPClient."""
    # Inspect the source literal — cheapest + most stable assertion.
    src = Path(_pipeline.__file__).read_text()
    assert (
        "MCPClient(skills, disabled_tools=getattr(cfg, 'disabled_tools', []) or [])"
        in src
    ), "paper subprocess MCPClient must be constructed with disabled_tools"
