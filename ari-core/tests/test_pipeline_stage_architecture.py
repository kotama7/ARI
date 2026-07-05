"""Characterization tests for the subtask-012 stage architecture.

These lock the new seam introduced when the 913-LOC ``run_pipeline`` loop was
decomposed into ``WorkflowDriver`` + ``BasePipelineStage`` subclasses +
``StageContext``. They assert the *structural* contract (importability,
dispatch selection, package-surface routing, ReAct reachability) without
running any real MCP subprocess or LLM call. Behaviour equivalence of the
full pipeline is covered by test_pipeline_e2e / test_workflow_contract.
"""

from __future__ import annotations

from pathlib import Path

from ari import pipeline as _pipe


def test_new_symbols_importable_from_package():
    # AC#2 / §8-8: the additive re-exports resolve from ``ari.pipeline``.
    assert _pipe.BasePipelineStage is not None
    assert _pipe.SubprocessMCPStage is not None
    assert _pipe.ReActStage is not None
    assert _pipe.WorkflowDriver is not None
    assert _pipe.StageContext is not None
    assert callable(_pipe.make_stage)
    # The historical persistence helper stays importable from orchestrator.
    from ari.pipeline.orchestrator import _copy_stage_output_if_distinct
    assert callable(_copy_stage_output_if_distinct)


def test_make_stage_selects_subclass_by_react_key():
    sub = _pipe.make_stage({"stage": "s", "skill": "web", "tool": "t"}, {})
    assert isinstance(sub, _pipe.SubprocessMCPStage)
    react = _pipe.make_stage(
        {"stage": "r", "react": {"agent_phase": "reproduce"}}, {}
    )
    assert isinstance(react, _pipe.ReActStage)


def test_stage_identity_fields():
    st = _pipe.make_stage(
        {"stage": "search", "skill": "web", "tool": "collect_refs",
         "description": "d"},
        {},
    )
    assert st.stage_name == "search"
    # bare skill name gets the ``-skill`` suffix, matching run_pipeline.
    assert st.skill == "web-skill"
    assert st.tool == "collect_refs"
    assert st.desc == "d"


def test_subprocess_stage_routes_through_package_surface(monkeypatch):
    """run() must dispatch via ``ari.pipeline._run_stage_subprocess`` so the
    lazy-delegator monkeypatch surface keeps working (subtask 012 §10)."""
    seen = {}

    def fake_sub(tool, args, config_path, skill_name=""):
        seen.update(tool=tool, args=args, config_path=config_path, skill=skill_name)
        return {"result": "ok"}

    monkeypatch.setattr(_pipe, "_run_stage_subprocess", fake_sub)
    st = _pipe.make_stage({"stage": "s", "skill": "web", "tool": "t"}, {})
    ctx = _pipe.StageContext(
        checkpoint_dir=Path("."), config_path="cfg.yaml", wf_cfg={},
        disabled_stages=set(),
    )
    out = st.run(ctx, {"k": "v"})
    assert out == {"result": "ok"}
    assert seen == {"tool": "t", "args": {"k": "v"},
                    "config_path": "cfg.yaml", "skill": "web-skill"}


def test_react_stage_reachable_via_cfg_react_key(monkeypatch):
    """AC#7: the ReAct path stays reachable through cfg['react'] and dispatches
    to the ``ari.pipeline._run_react_stage`` package-surface delegator."""
    captured = {}

    def fake_react(**kwargs):
        captured.update(kwargs)
        return {"verdict": "REPRODUCED"}

    monkeypatch.setattr(_pipe, "_run_react_stage", fake_react)
    cfg = {"stage": "repro", "skill": "coding",
           "react": {"agent_phase": "reproduce"}, "pre_tool": "p", "post_tool": "q"}
    st = _pipe.make_stage(cfg, {})
    assert isinstance(st, _pipe.ReActStage)
    ctx = _pipe.StageContext(
        checkpoint_dir=Path("/tmp"), config_path="cfg.yaml", wf_cfg={},
        disabled_stages=set(), tpl_vars={"stages": {}},
    )
    out = st.run(ctx, {"a": 1})
    assert out == {"verdict": "REPRODUCED"}
    assert captured["stage_cfg"] is cfg
    assert captured["args"] == {"a": 1}
    assert captured["stage_name"] == "repro"


def test_should_skip_honours_disabled_tools():
    st = _pipe.make_stage(
        {"stage": "s", "skill": "web", "tool": "banned"},
        {"disabled_tools": ["banned"]},
    )
    ctx = _pipe.StageContext(
        checkpoint_dir=Path("."), config_path="", wf_cfg={"disabled_tools": ["banned"]},
        disabled_stages=set(), tpl_vars={"stages": {}}, stage_outputs={},
    )
    assert st.should_skip(ctx) is True
    assert ctx.stage_outputs["s"]["skipped"] is True
    assert "disabled" in ctx.stage_outputs["s"]["reason"]
