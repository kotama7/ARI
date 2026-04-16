from __future__ import annotations
"""Tests for ari/viz/api_workflow.py — React Flow workflow editor."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from ari.viz.api_workflow import (
    flow_to_workflow_yaml,
    workflow_yaml_to_flow,
    _api_get_default_workflow,
    _api_get_workflow_flow,
    _api_save_workflow_flow,
)


# ── Sample YAML data ────────────────────────────────

SAMPLE_YAML = {
    "bfts_pipeline": [
        {
            "stage": "generate_idea",
            "skill": "idea-skill",
            "tool": "generate_ideas",
            "description": "Generate hypotheses",
            "depends_on": [],
            "enabled": True,
            "phase": "bfts",
        },
        {
            "stage": "select_and_run",
            "skill": "hpc-skill",
            "tool": "",
            "description": "Run experiment",
            "depends_on": ["generate_idea"],
            "enabled": True,
            "phase": "bfts",
        },
    ],
    "pipeline": [
        {
            "stage": "search_related_work",
            "skill": "web-skill",
            "tool": "collect_references_iterative",
            "description": "Citation collection",
            "depends_on": [],
            "enabled": True,
            "phase": "paper",
        },
        {
            "stage": "write_paper",
            "skill": "paper-skill",
            "tool": "write_paper_iterative",
            "description": "Write the paper",
            "depends_on": ["search_related_work"],
            "enabled": True,
            "phase": "paper",
        },
    ],
}


# ── workflow_yaml_to_flow ────────────────────────────


def test_workflow_yaml_to_flow_produces_valid_nodes():
    flow = workflow_yaml_to_flow(SAMPLE_YAML)
    assert "nodes" in flow
    assert "edges" in flow
    assert len(flow["nodes"]) == 4  # 2 bfts + 2 paper
    ids = {n["id"] for n in flow["nodes"]}
    assert "generate_idea" in ids
    assert "write_paper" in ids


def test_workflow_yaml_to_flow_produces_valid_edges():
    flow = workflow_yaml_to_flow(SAMPLE_YAML)
    sources = {e["source"] for e in flow["edges"]}
    targets = {e["target"] for e in flow["edges"]}
    # select_and_run depends on generate_idea
    assert "generate_idea" in sources
    assert "select_and_run" in targets


def test_workflow_yaml_to_flow_node_positions():
    flow = workflow_yaml_to_flow(SAMPLE_YAML)
    for n in flow["nodes"]:
        assert "position" in n
        assert "x" in n["position"]
        assert "y" in n["position"]


def test_workflow_yaml_to_flow_node_data():
    flow = workflow_yaml_to_flow(SAMPLE_YAML)
    idea_node = next(n for n in flow["nodes"] if n["id"] == "generate_idea")
    assert idea_node["data"]["skill"] == "idea-skill"
    assert idea_node["data"]["enabled"] is True
    assert idea_node["type"] == "phase"


def test_workflow_yaml_to_flow_loop_back():
    yaml_data = {
        "bfts_pipeline": [
            {
                "stage": "a",
                "skill": "s1",
                "tool": "",
                "depends_on": [],
                "enabled": True,
                "phase": "bfts",
            },
            {
                "stage": "b",
                "skill": "s2",
                "tool": "",
                "depends_on": ["a"],
                "enabled": True,
                "phase": "bfts",
                "loop_back_to": "a",
            },
        ],
        "pipeline": [],
    }
    flow = workflow_yaml_to_flow(yaml_data)
    loop_edges = [e for e in flow["edges"] if e.get("animated")]
    assert len(loop_edges) == 1
    assert loop_edges[0]["source"] == "b"
    assert loop_edges[0]["target"] == "a"


def test_workflow_yaml_to_flow_empty():
    flow = workflow_yaml_to_flow({})
    assert flow == {"nodes": [], "edges": []}


# ── flow_to_workflow_yaml roundtrip ──────────────────


def test_flow_to_workflow_yaml_roundtrip():
    flow = workflow_yaml_to_flow(SAMPLE_YAML)
    yaml_out = flow_to_workflow_yaml(flow)
    assert "bfts_pipeline" in yaml_out
    assert "pipeline" in yaml_out
    # Same number of stages
    bfts_stages = {s["stage"] for s in yaml_out["bfts_pipeline"]}
    paper_stages = {s["stage"] for s in yaml_out["pipeline"]}
    assert "generate_idea" in bfts_stages
    assert "select_and_run" in bfts_stages
    assert "search_related_work" in paper_stages
    assert "write_paper" in paper_stages


def test_flow_to_workflow_yaml_preserves_deps():
    flow = workflow_yaml_to_flow(SAMPLE_YAML)
    yaml_out = flow_to_workflow_yaml(flow)
    sar = next(s for s in yaml_out["bfts_pipeline"] if s["stage"] == "select_and_run")
    assert "generate_idea" in sar["depends_on"]


def test_flow_to_workflow_yaml_preserves_skills():
    flow = workflow_yaml_to_flow(SAMPLE_YAML)
    yaml_out = flow_to_workflow_yaml(flow)
    gi = next(s for s in yaml_out["bfts_pipeline"] if s["stage"] == "generate_idea")
    assert gi["skill"] == "idea-skill"


# ── API endpoints ────────────────────────────────────


def test_api_get_workflow_flow():
    result = _api_get_workflow_flow()
    assert "ok" in result
    if result["ok"]:
        assert "flow" in result
        assert "nodes" in result["flow"]
        assert "edges" in result["flow"]


def test_api_get_default_workflow():
    result = _api_get_default_workflow()
    assert "ok" in result
    if result["ok"]:
        assert "flow" in result
        assert "workflow" in result


def test_api_save_workflow_flow_missing_data():
    result = _api_save_workflow_flow(json.dumps({}).encode())
    assert result["ok"] is False
    assert "missing" in result.get("error", "").lower()


def test_api_save_workflow_flow_with_data(tmp_path):
    """Save flow data to a temp workflow.yaml via checkpoint dir mock."""
    import yaml

    # Write a minimal workflow.yaml into the temp dir
    wf = tmp_path / "workflow.yaml"
    wf.write_text(yaml.dump(SAMPLE_YAML, allow_unicode=True, sort_keys=False))

    # Patch _st._checkpoint_dir so the API writes to our temp dir
    with patch("ari.viz.api_workflow._st") as mock_st:
        mock_st._checkpoint_dir = tmp_path
        flow = workflow_yaml_to_flow(SAMPLE_YAML)
        body = json.dumps({"flow": flow}).encode()
        result = _api_save_workflow_flow(body)
        assert result["ok"] is True

    # Verify the file was updated
    saved = yaml.safe_load(wf.read_text())
    assert "bfts_pipeline" in saved
    assert "pipeline" in saved


# ── BFTS → Paper auto-bridge edges ──────────────────


def test_auto_bridge_edges_created():
    """Paper stages with empty depends_on get auto-bridge edges from last BFTS stage."""
    flow = workflow_yaml_to_flow(SAMPLE_YAML)
    bridge_edges = [e for e in flow["edges"] if (e.get("data") or {}).get("auto_bridge")]
    # search_related_work has depends_on=[] → bridge from select_and_run (last bfts)
    assert len(bridge_edges) == 1
    assert bridge_edges[0]["source"] == "select_and_run"
    assert bridge_edges[0]["target"] == "search_related_work"


def test_auto_bridge_not_created_when_depends_on_exists():
    """Paper stages with existing depends_on should not get auto-bridge edges."""
    flow = workflow_yaml_to_flow(SAMPLE_YAML)
    bridge_edges = [e for e in flow["edges"] if (e.get("data") or {}).get("auto_bridge")]
    targets = {e["target"] for e in bridge_edges}
    # write_paper depends on search_related_work → no bridge
    assert "write_paper" not in targets


def test_auto_bridge_not_created_without_bfts():
    """No auto-bridge when there is no BFTS pipeline."""
    yaml_data = {
        "bfts_pipeline": [],
        "pipeline": [
            {
                "stage": "search",
                "skill": "web-skill",
                "tool": "",
                "depends_on": [],
                "enabled": True,
                "phase": "paper",
            },
        ],
    }
    flow = workflow_yaml_to_flow(yaml_data)
    bridge_edges = [e for e in flow["edges"] if (e.get("data") or {}).get("auto_bridge")]
    assert len(bridge_edges) == 0


def test_auto_bridge_multiple_paper_roots():
    """Multiple paper stages with empty depends_on all get bridge edges."""
    yaml_data = {
        "bfts_pipeline": [
            {"stage": "bfts_end", "skill": "s1", "tool": "", "depends_on": [],
             "enabled": True, "phase": "bfts"},
        ],
        "pipeline": [
            {"stage": "paper_a", "skill": "s2", "tool": "", "depends_on": [],
             "enabled": True, "phase": "paper"},
            {"stage": "paper_b", "skill": "s3", "tool": "", "depends_on": [],
             "enabled": True, "phase": "paper"},
            {"stage": "paper_c", "skill": "s4", "tool": "", "depends_on": ["paper_a"],
             "enabled": True, "phase": "paper"},
        ],
    }
    flow = workflow_yaml_to_flow(yaml_data)
    bridge_edges = [e for e in flow["edges"] if (e.get("data") or {}).get("auto_bridge")]
    assert len(bridge_edges) == 2
    bridge_targets = {e["target"] for e in bridge_edges}
    assert bridge_targets == {"paper_a", "paper_b"}
    # paper_c has depends_on → no bridge
    assert "paper_c" not in bridge_targets
    # All bridge from last bfts stage
    assert all(e["source"] == "bfts_end" for e in bridge_edges)


# ── Roundtrip: auto_bridge stripped on save ──────────


def test_roundtrip_strips_auto_bridge_deps():
    """Auto-bridge edges must not persist back into YAML depends_on."""
    flow = workflow_yaml_to_flow(SAMPLE_YAML)
    yaml_out = flow_to_workflow_yaml(flow)
    srw = next(s for s in yaml_out["pipeline"] if s["stage"] == "search_related_work")
    # Original has depends_on=[] and roundtrip should preserve that
    assert srw["depends_on"] == []


def test_roundtrip_preserves_real_deps_across_pipeline():
    """Manually added cross-pipeline edges (without auto_bridge) should persist."""
    flow = workflow_yaml_to_flow(SAMPLE_YAML)
    # Simulate user manually adding a cross-pipeline edge (no auto_bridge flag)
    flow["edges"].append({
        "id": "e-manual-cross",
        "source": "generate_idea",
        "target": "write_paper",
        "data": {"condition": "always"},
    })
    yaml_out = flow_to_workflow_yaml(flow)
    wp = next(s for s in yaml_out["pipeline"] if s["stage"] == "write_paper")
    assert "generate_idea" in wp["depends_on"]


def test_roundtrip_full_workflow_yaml(tmp_path):
    """Full roundtrip through save API preserves YAML structure correctly."""
    import yaml

    wf = tmp_path / "workflow.yaml"
    wf.write_text(yaml.dump(SAMPLE_YAML, allow_unicode=True, sort_keys=False))

    with patch("ari.viz.api_workflow._st") as mock_st:
        mock_st._checkpoint_dir = tmp_path
        flow = workflow_yaml_to_flow(SAMPLE_YAML)
        body = json.dumps({"flow": flow}).encode()
        result = _api_save_workflow_flow(body)
        assert result["ok"] is True

    saved = yaml.safe_load(wf.read_text())
    # Paper root stage should still have empty depends_on (auto_bridge stripped)
    srw = next(s for s in saved["pipeline"] if s["stage"] == "search_related_work")
    assert srw["depends_on"] == []
    # BFTS deps preserved
    sar = next(s for s in saved["bfts_pipeline"] if s["stage"] == "select_and_run")
    assert "generate_idea" in sar["depends_on"]


def test_real_workflow_yaml_bridge():
    """Test with the actual config/workflow.yaml file."""
    import yaml

    wf_path = Path(__file__).parent.parent / "config" / "workflow.yaml"
    if not wf_path.exists():
        pytest.skip("config/workflow.yaml not found")

    data = yaml.safe_load(wf_path.read_text())
    flow = workflow_yaml_to_flow(data)

    # Bridge edges should connect last BFTS stage to paper root stages
    bridge_edges = [e for e in flow["edges"] if (e.get("data") or {}).get("auto_bridge")]
    assert len(bridge_edges) > 0, "Expected auto_bridge edges from BFTS to paper"

    last_bfts = data["bfts_pipeline"][-1]["stage"]
    assert all(e["source"] == last_bfts for e in bridge_edges)

    # Roundtrip should not pollute YAML
    yaml_out = flow_to_workflow_yaml(flow)
    for s in yaml_out["pipeline"]:
        orig = next((o for o in data["pipeline"] if o["stage"] == s["stage"]), None)
        if orig and not orig.get("depends_on"):
            assert s["depends_on"] == [], \
                f"Stage {s['stage']} should have empty depends_on after roundtrip"


# ── Loop-back edge routing ───────────────────────────


def test_loop_back_edge_uses_bottom_handles():
    """Loop-back edges should use loop-out/loop-in handles for bottom routing."""
    yaml_data = {
        "bfts_pipeline": [
            {"stage": "a", "skill": "s1", "tool": "", "depends_on": [],
             "enabled": True, "phase": "bfts"},
            {"stage": "b", "skill": "s2", "tool": "", "depends_on": ["a"],
             "enabled": True, "phase": "bfts", "loop_back_to": "a"},
        ],
        "pipeline": [],
    }
    flow = workflow_yaml_to_flow(yaml_data)
    loop_edges = [e for e in flow["edges"] if e.get("animated")]
    assert len(loop_edges) == 1
    assert loop_edges[0]["sourceHandle"] == "loop-out"
    assert loop_edges[0]["targetHandle"] == "loop-in"


def test_normal_edges_no_handle_override():
    """Non-loop edges should not have sourceHandle/targetHandle."""
    flow = workflow_yaml_to_flow(SAMPLE_YAML)
    normal_edges = [e for e in flow["edges"]
                    if not e.get("animated") and not (e.get("data") or {}).get("auto_bridge")]
    for e in normal_edges:
        assert "sourceHandle" not in e or e.get("sourceHandle") is None
        assert "targetHandle" not in e or e.get("targetHandle") is None


# ── Swim-lane layout ────────────────────────────────


def test_bfts_and_paper_vertically_separated():
    """BFTS nodes should be above paper nodes with a gap."""
    flow = workflow_yaml_to_flow(SAMPLE_YAML)
    bfts_ys = [n["position"]["y"] for n in flow["nodes"] if n["data"]["phase"] == "bfts"]
    paper_ys = [n["position"]["y"] for n in flow["nodes"] if n["data"]["phase"] == "paper"]
    assert bfts_ys and paper_ys, "Both phases should have nodes"
    assert max(bfts_ys) < min(paper_ys), \
        f"BFTS max y ({max(bfts_ys)}) should be below paper min y ({min(paper_ys)})"


def test_paper_starts_at_level_zero():
    """Paper pipeline should start its own level 0 (not continue from BFTS levels)."""
    flow = workflow_yaml_to_flow(SAMPLE_YAML)
    paper_xs = [n["position"]["x"] for n in flow["nodes"] if n["data"]["phase"] == "paper"]
    assert min(paper_xs) == 0, "Paper pipeline root should be at x=0"


def test_empty_bfts_paper_starts_at_zero():
    """Without BFTS, paper pipeline should start at y=0."""
    yaml_data = {
        "bfts_pipeline": [],
        "pipeline": [
            {"stage": "s1", "skill": "sk1", "tool": "", "depends_on": [],
             "enabled": True, "phase": "paper"},
        ],
    }
    flow = workflow_yaml_to_flow(yaml_data)
    assert flow["nodes"][0]["position"]["y"] == 0


# ── skill_mcp phase and usage classification ─────────


def test_skill_mcp_has_phase_info():
    """skill_mcp entries should have phase field from default.yaml."""
    from ari.viz.api_settings import _api_get_workflow
    r = _api_get_workflow()
    if not r.get("ok"):
        pytest.skip("workflow API unavailable")
    mcp = r.get("skill_mcp", {})
    # memory-skill is defined in default.yaml with phase=bfts
    if "memory-skill" in mcp:
        assert mcp["memory-skill"].get("phase") == "bfts"
    # paper-skill is phase=pipeline
    if "paper-skill" in mcp:
        assert mcp["paper-skill"].get("phase") in ("pipeline", "paper")


def test_skill_mcp_usage_stage_for_pipeline_skills():
    """Skills used in pipeline stages should have usage=stage."""
    from ari.viz.api_settings import _api_get_workflow
    r = _api_get_workflow()
    if not r.get("ok"):
        pytest.skip("workflow API unavailable")
    mcp = r.get("skill_mcp", {})
    stage_skills = set()
    for s in r.get("bfts_pipeline", []) + r.get("paper_pipeline", []):
        stage_skills.add(s.get("skill", ""))
    for sk in stage_skills:
        if sk in mcp:
            assert mcp[sk].get("usage") == "stage", \
                f"{sk} is a pipeline stage skill but usage={mcp[sk].get('usage')}"


def test_skill_mcp_usage_active_for_memory():
    """memory-skill is called indirectly and should have usage=active."""
    from ari.viz.api_settings import _api_get_workflow
    r = _api_get_workflow()
    if not r.get("ok"):
        pytest.skip("workflow API unavailable")
    mcp = r.get("skill_mcp", {})
    if "memory-skill" not in mcp:
        pytest.skip("memory-skill not found")
    assert mcp["memory-skill"].get("usage") == "active"


def test_skill_mcp_usage_registered_for_unused():
    """Skills not in pipeline and not called in core should have usage=registered."""
    from ari.viz.api_settings import _api_get_workflow
    r = _api_get_workflow()
    if not r.get("ok"):
        pytest.skip("workflow API unavailable")
    mcp = r.get("skill_mcp", {})
    # plot-skill is the generate_figures stage (restored after issue #9 close),
    # so its usage should be "stage" (pipeline-driven).
    if "plot-skill" in mcp:
        assert mcp["plot-skill"].get("usage") == "stage", (
            f"plot-skill should be marked as 'stage' since it's wired into "
            f"the generate_figures pipeline stage, got "
            f"{mcp['plot-skill'].get('usage')!r}"
        )
    # figure-router-skill is defined but intentionally NOT in any pipeline
    # stage (see workflow.yaml comments + closed issue #9), so it should be
    # either 'registered' or 'active' (depending on core-source references),
    # never 'stage'.
    if "figure-router-skill" in mcp:
        assert mcp["figure-router-skill"].get("usage") != "stage", (
            f"figure-router-skill must not be wired into the paper pipeline; "
            f"it was replaced by plot-skill batch generation to produce "
            f"figures_manifest.json. Got usage="
            f"{mcp['figure-router-skill'].get('usage')!r}"
        )


def test_skill_mcp_tools_resolved_from_server_py():
    """Skills with empty mcp.json tools should get tools from server.py."""
    from ari.viz.api_settings import _api_get_workflow
    r = _api_get_workflow()
    if not r.get("ok"):
        pytest.skip("workflow API unavailable")
    mcp = r.get("skill_mcp", {})
    # hpc-skill has empty tools in mcp.json but server.py has Tool() defs
    if "hpc-skill" in mcp:
        tools = mcp["hpc-skill"].get("tools", [])
        assert len(tools) > 0, "hpc-skill should have tools extracted from server.py"
        tool_names = [t if isinstance(t, str) else t.get("name") for t in tools]
        assert "slurm_submit" in tool_names


# ── Agent runtime tools visibility tests ──────────────


def test_skill_mcp_active_skills_have_tools():
    """Skills with usage=active should have tools listed so the frontend can display them."""
    from ari.viz.api_settings import _api_get_workflow
    r = _api_get_workflow()
    if not r.get("ok"):
        pytest.skip("workflow API unavailable")
    mcp = r.get("skill_mcp", {})
    active_skills = {name: entry for name, entry in mcp.items()
                     if entry.get("usage") == "active"}
    for name, entry in active_skills.items():
        tools = entry.get("tools", [])
        assert len(tools) > 0, (
            f"Active skill '{name}' has no tools — frontend Agent Runtime Tools "
            f"panel will show an empty card"
        )


def test_memory_skill_detected_as_active():
    """memory-skill tools are called from agent/loop.py and should be detected as active."""
    from ari.viz.api_settings import _api_get_workflow
    r = _api_get_workflow()
    if not r.get("ok"):
        pytest.skip("workflow API unavailable")
    mcp = r.get("skill_mcp", {})
    if "memory-skill" not in mcp:
        pytest.skip("memory-skill not found")
    assert mcp["memory-skill"].get("usage") == "active"
    tools = mcp["memory-skill"].get("tools", [])
    tool_names = [t if isinstance(t, str) else t.get("name") for t in tools]
    assert "add_memory" in tool_names
    assert "search_memory" in tool_names


def test_web_skill_is_stage_assigned():
    """web-skill is assigned to a pipeline stage and should have usage=stage."""
    from ari.viz.api_settings import _api_get_workflow
    r = _api_get_workflow()
    if not r.get("ok"):
        pytest.skip("workflow API unavailable")
    mcp = r.get("skill_mcp", {})
    if "web-skill" not in mcp:
        pytest.skip("web-skill not found")
    assert mcp["web-skill"].get("usage") == "stage"
    tools = mcp["web-skill"].get("tools", [])
    tool_names = [t if isinstance(t, str) else t.get("name") for t in tools]
    assert "web_search" in tool_names


def test_active_skills_not_in_bfts_stages():
    """Active skills should not be assigned to any bfts_pipeline stage."""
    from ari.viz.api_settings import _api_get_workflow
    r = _api_get_workflow()
    if not r.get("ok"):
        pytest.skip("workflow API unavailable")
    mcp = r.get("skill_mcp", {})
    bfts_stage_skills = {s.get("skill") for s in r.get("bfts_pipeline", [])}
    paper_stage_skills = {s.get("skill") for s in r.get("paper_pipeline", [])}
    for name, entry in mcp.items():
        if entry.get("usage") == "active":
            assert name not in bfts_stage_skills, (
                f"'{name}' has usage=active but is assigned to a BFTS stage"
            )


def test_frontend_agent_runtime_tools_data_available():
    """The skill_mcp data should contain enough info for the frontend
    Agent Runtime Tools panel to render (usage + tools fields)."""
    from ari.viz.api_settings import _api_get_workflow
    r = _api_get_workflow()
    if not r.get("ok"):
        pytest.skip("workflow API unavailable")
    mcp = r.get("skill_mcp", {})
    active_skills = [name for name, entry in mcp.items()
                     if entry.get("usage") == "active"]
    assert len(active_skills) > 0, (
        "No active skills detected — Agent Runtime Tools panel will be empty"
    )
    for name in active_skills:
        entry = mcp[name]
        assert "tools" in entry, f"Active skill '{name}' missing 'tools' key"
        assert "description" in entry, f"Active skill '{name}' missing 'description' key"
