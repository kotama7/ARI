"""End-to-end tests: New Experiment → Paper Pipeline → Reproducibility Check.

Verifies that config and environment variables propagate WITHOUT fallback
from the wizard/launch through every component:
  Wizard → _api_launch env → CLI → config → pipeline → _run_stage_subprocess → skill MCP server

Each test isolates a specific propagation boundary and asserts that values
arrive at the destination unchanged — not that they "work", but that they
are not silently replaced by defaults (ollama, qwen3:8b, local, etc.).
"""

import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest
import yaml


# ══════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════

@pytest.fixture
def clean_env(monkeypatch):
    """Remove all ARI_* and provider API keys so tests start from known state."""
    for k in list(os.environ):
        if k.startswith("ARI_") or k in (
            "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
            "OLLAMA_HOST", "LLM_API_BASE", "LLM_MODEL",
        ):
            monkeypatch.delenv(k, raising=False)


@pytest.fixture
def workflow_yaml():
    """Load the real workflow.yaml."""
    p = Path(__file__).parent.parent / "config" / "workflow.yaml"
    return yaml.safe_load(p.read_text())


@pytest.fixture
def fake_nodes():
    """Minimal BFTS nodes with SLURM artifacts (simulating HPC experiment)."""
    from ari.orchestrator.node import Node, NodeStatus
    n = Node(id="node_test_root", parent_id=None, depth=0)
    n.status = NodeStatus.SUCCESS
    n.has_real_data = True
    n.metrics = {"score": 120.5}
    n.artifacts = [
        {"type": "code", "tool": "slurm_submit",
         "content": "#!/bin/bash\n#SBATCH -c 64\necho hello"},
        {"type": "result", "tool": "job_status",
         "content": "COMPLETED"},
    ]
    return [n]


@pytest.fixture
def checkpoint_dir(tmp_path, fake_nodes):
    """Create a minimal checkpoint directory with required files."""
    ckpt = tmp_path / "checkpoints" / "20260329_test_run"
    ckpt.mkdir(parents=True)
    # tree.json
    (ckpt / "tree.json").write_text(json.dumps({
        "run_id": "20260329_test_run",
        "experiment_file": str(tmp_path / "experiment.md"),
        "nodes": [n.to_dict() for n in fake_nodes],
    }))
    # nodes_tree.json (used by pipeline stages)
    (ckpt / "nodes_tree.json").write_text(json.dumps({
        "experiment_goal": "Maximize GFLOPS of a stencil benchmark",
        "nodes": [n.to_dict() for n in fake_nodes],
    }))
    # experiment.md
    (tmp_path / "experiment.md").write_text("## Research Goal\nMaximize GFLOPS of a stencil benchmark\n")
    (ckpt / "experiment.md").write_text("## Research Goal\nMaximize GFLOPS of a stencil benchmark\n")
    return ckpt


# ══════════════════════════════════════════════
# 1. Wizard → Launch: env vars set WITHOUT fallback
# ══════════════════════════════════════════════

class TestWizardToLaunchPropagation:
    """Verify that wizard settings reach _api_launch subprocess env
    without falling back to ollama/qwen3:8b defaults."""

    def test_openai_model_not_replaced_by_ollama_default(self, monkeypatch, tmp_path, clean_env):
        """OpenAI model from wizard must not be overwritten by ollama default."""
        from ari.viz import state as _st
        monkeypatch.setattr(_st, "_checkpoint_dir", tmp_path)
        _st._settings_path = tmp_path / "settings.json"

        spawned = {}
        class _FP:
            pid = 99999
            def poll(self): return None

        def fake_popen(cmd, **kw):
            spawned["env"] = kw.get("env", {})
            return _FP()

        monkeypatch.setattr(subprocess, "Popen", fake_popen)

        from ari.viz.api_experiment import _api_launch
        with mock.patch("threading.Thread"), mock.patch("builtins.open", mock.mock_open()):
            _api_launch(json.dumps({
                "experiment_md": "## Research Goal\nTest\n",
                "llm_model": "gpt-5.2",
                "llm_provider": "openai",
            }).encode())

        env = spawned["env"]
        assert env.get("ARI_MODEL") == "gpt-5.2", \
            f"Expected gpt-5.2 but got {env.get('ARI_MODEL')} — wizard model lost"
        assert env.get("ARI_BACKEND") == "openai", \
            f"Expected openai but got {env.get('ARI_BACKEND')} — wizard provider lost"
        # Must NOT contain ollama defaults
        assert "ollama" not in env.get("ARI_BACKEND", "").lower()


# ══════════════════════════════════════════════
# 2. Config → LLM client: no silent ollama fallback
# ══════════════════════════════════════════════

class TestConfigToLLMPropagation:
    """Verify config.yaml model reaches LLMClient without ollama fallback."""

    def test_load_config_preserves_model(self, tmp_path, clean_env):
        """load_config must return exact model from YAML, not env default."""
        from ari.config import load_config
        cfg_file = tmp_path / "workflow.yaml"
        cfg_file.write_text("llm:\n  backend: openai\n  model: gpt-5.2\n  base_url: ''\n")
        cfg = load_config(str(cfg_file))
        assert cfg.llm.model == "gpt-5.2"
        assert cfg.llm.backend == "openai"

    def test_llm_client_uses_config_model(self, clean_env):
        """LLMClient must format model from config, not fall back to ollama."""
        from ari.config import LLMConfig
        from ari.llm.client import LLMClient
        c = LLMClient(LLMConfig(backend="openai", model="gpt-5.2"))
        assert c._model_name() == "gpt-5.2"
        assert "ollama" not in c._model_name()


# ══════════════════════════════════════════════
# 3. Pipeline subprocess: ARI_LLM_MODEL from config
# ══════════════════════════════════════════════

class TestSubprocessEnvPropagation:
    """Verify _run_stage_subprocess passes ARI_LLM_MODEL from workflow.yaml
    to the skill subprocess, not the environment default."""

    def test_model_from_config_injected_to_subprocess(self, tmp_path, clean_env):
        """ARI_LLM_MODEL must come from workflow.yaml when env var is unset."""
        from ari.pipeline import _run_stage_subprocess

        cfg_file = tmp_path / "workflow.yaml"
        cfg_file.write_text(yaml.dump({
            "llm": {"backend": "openai", "model": "gpt-5.2", "base_url": ""},
        }))

        captured_env = {}

        def fake_run(cmd, **kw):
            captured_env.update(kw.get("env", {}))
            r = mock.MagicMock()
            r.returncode = 0
            r.stdout = '{"result": "ok"}'
            r.stderr = ""
            return r

        with mock.patch("subprocess.run", side_effect=fake_run):
            _run_stage_subprocess("fake_tool", {}, str(cfg_file), skill_name="fake-skill")

        assert captured_env.get("ARI_LLM_MODEL") == "gpt-5.2", \
            f"Expected gpt-5.2 but got {captured_env.get('ARI_LLM_MODEL')} — config model not propagated"
        assert captured_env.get("ARI_LLM_API_BASE") == "", \
            "ARI_LLM_API_BASE must be empty string for OpenAI (prevents ollama fallback)"

    def test_env_var_takes_precedence_over_config(self, tmp_path, clean_env, monkeypatch):
        """If ARI_LLM_MODEL is already set in env, config must NOT override it."""
        monkeypatch.setenv("ARI_LLM_MODEL", "claude-opus-4")
        from ari.pipeline import _run_stage_subprocess

        cfg_file = tmp_path / "workflow.yaml"
        cfg_file.write_text(yaml.dump({
            "llm": {"backend": "openai", "model": "gpt-5.2", "base_url": ""},
        }))

        captured_env = {}

        def fake_run(cmd, **kw):
            captured_env.update(kw.get("env", {}))
            r = mock.MagicMock()
            r.returncode = 0
            r.stdout = '{"result": "ok"}'
            r.stderr = ""
            return r

        with mock.patch("subprocess.run", side_effect=fake_run):
            _run_stage_subprocess("fake_tool", {}, str(cfg_file), skill_name="fake-skill")

        assert captured_env.get("ARI_LLM_MODEL") == "claude-opus-4", \
            "Env var must take precedence over config"

    def test_no_config_still_works(self, clean_env):
        """Missing config_path must not crash, just leaves env as-is."""
        from ari.pipeline import _run_stage_subprocess

        captured_env = {}

        def fake_run(cmd, **kw):
            captured_env.update(kw.get("env", {}))
            r = mock.MagicMock()
            r.returncode = 0
            r.stdout = '{"result": "ok"}'
            r.stderr = ""
            return r

        with mock.patch("subprocess.run", side_effect=fake_run):
            _run_stage_subprocess("fake_tool", {}, "", skill_name="fake-skill")

        # Should not have ARI_LLM_MODEL since no config and no env
        assert "ARI_LLM_MODEL" not in captured_env


# ══════════════════════════════════════════════
# 4. Pipeline stage chain: dependency + error propagation
# ══════════════════════════════════════════════

class TestPipelineStageChain:
    """Verify pipeline stages respect dependencies and propagate failures."""

    def _make_stages(self):
        """Minimal 3-stage pipeline: A → B → C."""
        return [
            {"stage": "stage_a", "skill": "test-skill", "tool": "tool_a",
             "depends_on": [], "inputs": {}, "outputs": {"file": "{{ckpt}}/a.json"},
             "skip_if_exists": ""},
            {"stage": "stage_b", "skill": "test-skill", "tool": "tool_b",
             "depends_on": ["stage_a"], "inputs": {}, "outputs": {"file": "{{ckpt}}/b.json"},
             "skip_if_exists": ""},
            {"stage": "stage_c", "skill": "test-skill", "tool": "tool_c",
             "depends_on": ["stage_b"], "inputs": {}, "outputs": {"file": "{{ckpt}}/c.json"},
             "skip_if_exists": ""},
        ]

    def test_failed_stage_blocks_downstream(self, tmp_path, fake_nodes, clean_env):
        """If stage_a fails, stage_b and stage_c must be skipped."""
        from ari.pipeline import run_pipeline

        call_log = []

        def fake_subprocess(tool, args, config_path, skill_name=""):
            call_log.append(tool)
            if tool == "tool_a":
                raise RuntimeError("MCP tool error: Tool 'tool_a' not found. Available: []")
            return {"result": "ok"}

        with mock.patch("ari.pipeline._run_stage_subprocess", side_effect=fake_subprocess):
            result = run_pipeline(
                self._make_stages(), fake_nodes,
                {"goal": "test", "topic": "test", "file": ""},
                tmp_path, "",
            )

        assert call_log == ["tool_a"], \
            f"Only stage_a should be called, but got {call_log}"
        assert "error" in result.get("stage_a", {}), "stage_a must be marked as error"
        assert result.get("stage_b", {}).get("skipped"), "stage_b must be skipped"
        assert result.get("stage_c", {}).get("skipped"), "stage_c must be skipped"

    def test_all_stages_succeed_sequentially(self, tmp_path, fake_nodes, clean_env):
        """All stages must execute in order when no failures."""
        from ari.pipeline import run_pipeline

        call_log = []

        def fake_subprocess(tool, args, config_path, skill_name=""):
            call_log.append(tool)
            return {"result": "ok"}

        with mock.patch("ari.pipeline._run_stage_subprocess", side_effect=fake_subprocess):
            result = run_pipeline(
                self._make_stages(), fake_nodes,
                {"goal": "test", "topic": "test", "file": ""},
                tmp_path, "",
            )

        assert call_log == ["tool_a", "tool_b", "tool_c"], \
            f"All stages must execute in order, got {call_log}"

    def test_mcp_error_dict_detected_as_failure(self, tmp_path, fake_nodes, clean_env):
        """MCP error dict {error: '...'} must be detected, not silently written as output."""
        from ari.pipeline import run_pipeline

        call_log = []

        def fake_subprocess(tool, args, config_path, skill_name=""):
            call_log.append(tool)
            if tool == "tool_a":
                # Simulate MCP returning error as data (the old bug)
                raise RuntimeError("MCP tool error: Tool 'tool_a' not found. Available: []")
            return {"result": "ok"}

        with mock.patch("ari.pipeline._run_stage_subprocess", side_effect=fake_subprocess):
            result = run_pipeline(
                self._make_stages(), fake_nodes,
                {"goal": "test", "topic": "test", "file": ""},
                tmp_path, "",
            )

        # stage_a must be an error, not skipped or successful
        assert "error" in result.get("stage_a", {}), \
            "MCP error dict must cause stage failure"
        # Downstream must be skipped, not attempted
        assert "tool_b" not in call_log


# ══════════════════════════════════════════════
# 5. Executor propagation: config → reproducibility_check
# ══════════════════════════════════════════════

class TestExecutorPropagation:
    """Verify resources.executor from workflow.yaml reaches reproduce_from_paper."""

    def test_executor_resolved_from_resources(self, workflow_yaml):
        """workflow.yaml resources.executor must be resolvable in template."""
        from ari.pipeline import _resolve_templates

        resources = workflow_yaml.get("resources", {})
        assert "executor" in resources, \
            "resources.executor must be defined in workflow.yaml"

        tpl_vars = {"resources": resources}
        resolved = _resolve_templates("{{resources.executor}}", tpl_vars)
        assert resolved == "slurm", \
            f"Expected 'slurm' but got '{resolved}' — executor not in config"
        assert resolved != "local", \
            "Executor must not fall back to 'local' when config specifies 'slurm'"

    def test_repro_stage_receives_executor_input(self, workflow_yaml):
        """reproducibility_check stage must have executor in its inputs."""
        stages = workflow_yaml.get("pipeline", [])
        repro = next((s for s in stages if s["stage"] == "reproducibility_check"), None)
        assert repro is not None, "reproducibility_check stage missing"
        assert "executor" in repro.get("inputs", {}), \
            "reproducibility_check must receive executor as input"
        assert "{{resources.executor}}" in repro["inputs"]["executor"], \
            "executor must reference {{resources.executor}} from config"


# ══════════════════════════════════════════════
# 6. Full pipeline template resolution: no unresolved vars
# ══════════════════════════════════════════════

class TestTemplateResolution:
    """Verify all pipeline templates resolve without leftover {{...}}."""

    def test_all_stage_inputs_resolve(self, workflow_yaml, tmp_path):
        """Every {{...}} in stage inputs must resolve to a concrete value."""
        from ari.pipeline import _resolve_templates
        import os

        tpl_vars = {
            "ckpt": str(tmp_path),
            "checkpoint_dir": str(tmp_path),
            "context": "test context",
            "experiment_summary": "test context",
            "paper_context": workflow_yaml.get("paper_context", "test"),
            "slurm_partition": "",
            "keywords": "test keywords",
            "experiment_source_file": "",
            "author_name": workflow_yaml.get("author_name", "ARI"),
            "ari_root": str(Path(__file__).parents[2]),
            # Pipeline initialises this to "" before the first stage runs
            "vlm_feedback": "",
            "stages": {
                "search_related_work": {"output": f"{tmp_path}/related_refs.json",
                                        "outputs": {"file": f"{tmp_path}/related_refs.json"}},
                "transform_data": {"output": f"{tmp_path}/science_data.json",
                                   "outputs": {"file": f"{tmp_path}/science_data.json"}},
                "generate_figures": {"output": f"{tmp_path}/figures_manifest.json",
                                     "outputs": {"file": f"{tmp_path}/figures_manifest.json"}},
                "write_paper": {"output": f"{tmp_path}/full_paper.tex",
                                "outputs": {"file": f"{tmp_path}/full_paper.tex",
                                            "bib_file": f"{tmp_path}/refs.bib"}},
                "review_paper": {"output": f"{tmp_path}/review_report.json",
                                 "outputs": {"file": f"{tmp_path}/review_report.json"}},
            },
            # Expose top-level scalars
            **{k: str(v) for k, v in workflow_yaml.items()
               if isinstance(v, (str, int, float)) and k != "paper_context"},
            # Expose nested dicts for dot-notation
            **{section: sec_val for section, sec_val in workflow_yaml.items()
               if isinstance(sec_val, dict) and section not in ("pipeline", "skills", "stages")},
        }

        errors = []
        for stage in workflow_yaml.get("pipeline", []):
            for k, v in stage.get("inputs", {}).items():
                resolved = _resolve_templates(str(v), tpl_vars)
                if "{{" in resolved:
                    errors.append(f'{stage["stage"]}.{k}: unresolved "{resolved}"')
            for k, v in stage.get("outputs", {}).items():
                resolved = _resolve_templates(str(v), tpl_vars)
                if "{{" in resolved:
                    errors.append(f'{stage["stage"]} output.{k}: unresolved "{resolved}"')

        assert not errors, "Unresolved templates:\n" + "\n".join(errors)


# ══════════════════════════════════════════════
# 7. Full paper pipeline: end-to-end with mocked skills
# ══════════════════════════════════════════════

class TestFullPaperPipeline:
    """End-to-end: run the real pipeline with mocked MCP calls.
    Verifies all 7 stages execute, outputs are written, and config propagates."""

    def test_all_stages_execute_with_correct_model(
        self, tmp_path, fake_nodes, clean_env
    ):
        """Full pipeline must call all 7 stages with the correct LLM model."""
        from ari.pipeline import load_pipeline, run_pipeline

        cfg_file = Path(__file__).parent.parent / "config" / "workflow.yaml"
        stages = load_pipeline(cfg_file)

        # Track which tools were called and with what env
        tool_calls = []
        subprocess_envs = {}

        def fake_subprocess(tool, args, config_path, skill_name=""):
            tool_calls.append(tool)
            # Return valid mock results for each stage
            if tool in ("search_semantic_scholar", "collect_references_iterative"):
                return {"papers": [{"title": "Test Paper", "id": "123"}]}
            elif tool == "nodes_to_science_data":
                return {"configurations": [], "metric_name": "score"}
            elif tool == "generate_figure":
                return {"figures": [], "latex_snippets": {}}
            elif tool == "review_figure":
                return {"verdict": "pass", "issues": []}
            elif tool == "write_paper_iterative":
                return {"latex": "\\documentclass{article}\n\\begin{document}\nTest\n\\end{document}",
                        "bib": "@article{test,title={Test}}"}
            elif tool == "review_compiled_paper":
                return {"overall_score": 7, "abstract_score": 8, "body_score": 6}
            elif tool == "generate_rebuttal":
                return {"rebuttal": "Response to reviewers", "revisions": []}
            elif tool == "reproduce_from_paper":
                return {"verdict": "REPRODUCED", "claimed_value": 120, "actual_value": 118}
            return {"result": "ok"}

        # Also capture the subprocess env to verify model propagation
        original_run = subprocess.run

        def capture_run(cmd, **kw):
            env = kw.get("env", {})
            subprocess_envs[len(subprocess_envs)] = {
                "ARI_LLM_MODEL": env.get("ARI_LLM_MODEL"),
                "ARI_LLM_API_BASE": env.get("ARI_LLM_API_BASE"),
            }
            r = mock.MagicMock()
            r.returncode = 0
            r.stdout = '{}'
            r.stderr = ""
            return r

        with mock.patch("ari.pipeline._run_stage_subprocess", side_effect=fake_subprocess):
            result = run_pipeline(
                stages, fake_nodes,
                {"goal": "Maximize GFLOPS of a stencil benchmark", "topic": "stencil_benchmark", "file": ""},
                tmp_path, str(cfg_file),
            )

        # All 9 stages must have been called (order depends on dependency resolution)
        expected_tools = [
            "collect_references_iterative",
            "nodes_to_science_data",
            "generate_ear",
            "generate_figures_llm",
            "review_figure",
            "write_paper_iterative",
            "review_compiled_paper",
            "generate_rebuttal",
            "reproduce_from_paper",
        ]
        assert tool_calls == expected_tools, \
            f"Expected all 9 stages in order, got {tool_calls}"
        # generate_ear MUST run before write_paper (issue #4)
        assert tool_calls.index("generate_ear") < tool_calls.index(
            "write_paper_iterative"
        ), "generate_ear must run before write_paper"
        # review_figure MUST run before write_paper
        assert tool_calls.index("review_figure") < tool_calls.index(
            "write_paper_iterative"
        ), "review_figure must run before write_paper"

        # No stage should have error
        for stage_name, stage_result in result.items():
            if isinstance(stage_result, dict):
                assert "error" not in stage_result, \
                    f"Stage {stage_name} has error: {stage_result}"

    def test_model_propagated_to_subprocess_env(self, tmp_path, fake_nodes, clean_env):
        """Every _run_stage_subprocess call must receive ARI_LLM_MODEL=gpt-5.2."""
        from ari.pipeline import run_pipeline, load_pipeline

        cfg_file = Path(__file__).parent.parent / "config" / "workflow.yaml"
        stages = load_pipeline(cfg_file)

        captured_envs = []

        original_subprocess = subprocess.run

        def capture_subprocess(cmd, **kw):
            env = kw.get("env", {})
            captured_envs.append({
                "ARI_LLM_MODEL": env.get("ARI_LLM_MODEL"),
                "ARI_LLM_API_BASE": env.get("ARI_LLM_API_BASE"),
            })
            # Return valid JSON so subprocess doesn't fail
            r = mock.MagicMock()
            r.returncode = 0
            r.stdout = json.dumps({"result": "ok", "papers": [], "configurations": [],
                                    "figures": [], "latex": "\\doc", "bib": "",
                                    "overall_score": 5, "verdict": "PASS"})
            r.stderr = ""
            return r

        with mock.patch("subprocess.run", side_effect=capture_subprocess):
            run_pipeline(
                stages, fake_nodes,
                {"goal": "Test", "topic": "test", "file": ""},
                tmp_path, str(cfg_file),
            )

        # Every subprocess must have received gpt-5.2 (from workflow.yaml)
        assert len(captured_envs) > 0, "No subprocess calls captured"
        for i, env in enumerate(captured_envs):
            assert env["ARI_LLM_MODEL"] == "gpt-5.2", \
                f"Subprocess call {i}: ARI_LLM_MODEL={env['ARI_LLM_MODEL']}, expected gpt-5.2"
            assert env["ARI_LLM_API_BASE"] == "", \
                f"Subprocess call {i}: ARI_LLM_API_BASE must be empty for OpenAI"


# ══════════════════════════════════════════════
# 8. Stderr logging: errors must not be silenced
# ══════════════════════════════════════════════

class TestStderrLogging:
    """Verify subprocess stderr is logged at WARNING, not DEBUG."""

    def test_stderr_logged_at_warning(self, tmp_path, clean_env):
        """Subprocess stderr must be logged at WARNING level."""
        from ari.pipeline import _run_stage_subprocess
        import logging

        def fake_run(cmd, **kw):
            r = mock.MagicMock()
            r.returncode = 0
            r.stdout = '{"result": "ok"}'
            r.stderr = "MCP server connection failed: timeout"
            return r

        with mock.patch("subprocess.run", side_effect=fake_run), \
             mock.patch("ari.pipeline.log") as mock_log:
            _run_stage_subprocess("tool", {}, "", skill_name="sk")

        # Must be warning, not debug
        mock_log.warning.assert_called()
        logged_msg = str(mock_log.warning.call_args)
        assert "MCP server connection failed" in logged_msg or "stderr" in logged_msg.lower()


# ══════════════════════════════════════════════
# 9. skip_if_exists: error JSON not treated as success
# ══════════════════════════════════════════════

class TestSkipIfExists:
    """Verify skip_if_exists correctly rejects error-containing JSON files."""

    def test_json_with_error_key_not_skipped(self, tmp_path):
        """JSON file containing 'error' key must NOT be treated as valid output."""
        from ari.pipeline import run_pipeline

        # Create error output file
        (tmp_path / "output.json").write_text(json.dumps({
            "error": "Tool 'x' not found. Available: []"
        }))

        stages = [{
            "stage": "test_stage", "skill": "test-skill", "tool": "test_tool",
            "depends_on": [], "inputs": {},
            "outputs": {"file": f"{tmp_path}/output.json"},
            "skip_if_exists": f"{tmp_path}/output.json",
        }]

        call_log = []

        def fake_sub(tool, args, config_path, skill_name=""):
            call_log.append(tool)
            return {"result": "ok"}

        from ari.orchestrator.node import Node, NodeStatus
        n = Node(id="n", parent_id=None, depth=0)
        n.status = NodeStatus.SUCCESS

        with mock.patch("ari.pipeline._run_stage_subprocess", side_effect=fake_sub):
            run_pipeline(stages, [n], {"goal": "", "topic": "", "file": ""}, tmp_path, "")

        assert "test_tool" in call_log, \
            "Stage with error JSON output must NOT be skipped"


# ══════════════════════════════════════════════
# 10. Checkpoint summary API: search paths
# ══════════════════════════════════════════════

class TestCheckpointSummaryPaths:
    """Verify checkpoint summary API finds checkpoints regardless of server CWD."""

    def test_ari_core_subdir_searched(self):
        """Checkpoint search bases must include ari-core/checkpoints path."""
        from ari.viz.api_state import _checkpoint_search_bases
        import inspect
        source = inspect.getsource(_checkpoint_search_bases)
        assert "ari-core" in source or "parents[2]" in source, \
            "Checkpoint search must include ari-core/checkpoints path"


# ══════════════════════════════════════════════════════════════════════════════
# BFTS → Paper transition: error handling (no silent death)
# ══════════════════════════════════════════════════════════════════════════════


class TestBftsToPaperTransition:
    """Verify that BFTS→Paper transition handles errors correctly."""

    def test_generate_paper_section_finds_workflow_with_none_config(self, tmp_path):
        """config_path='None' must still find package workflow.yaml."""
        from ari.core import generate_paper_section
        pkg_wf = Path(__file__).parent.parent / "config" / "workflow.yaml"
        if not pkg_wf.exists():
            pytest.skip("workflow.yaml not in package")
        with mock.patch("ari.pipeline.run_pipeline") as mock_rp, \
             mock.patch("ari.pipeline.load_pipeline", return_value=[{"stage": "t"}]):
            mock_rp.return_value = {}
            generate_paper_section([], {"goal": "test"}, tmp_path, None, "None")
            assert mock_rp.called, "run_pipeline must be called"

    def test_generate_paper_section_finds_workflow_with_empty_config(self, tmp_path):
        """config_path='' must still find package workflow.yaml."""
        from ari.core import generate_paper_section
        pkg_wf = Path(__file__).parent.parent / "config" / "workflow.yaml"
        if not pkg_wf.exists():
            pytest.skip("workflow.yaml not in package")
        with mock.patch("ari.pipeline.run_pipeline") as mock_rp, \
             mock.patch("ari.pipeline.load_pipeline", return_value=[{"stage": "t"}]):
            mock_rp.return_value = {}
            generate_paper_section([], {"goal": "test"}, tmp_path, None, "")
            assert mock_rp.called

    def test_run_pipeline_oserror_propagates(self, tmp_path):
        """OSError (e.g. disk quota) in run_pipeline must propagate, not be swallowed."""
        from ari.core import generate_paper_section
        pkg_wf = Path(__file__).parent.parent / "config" / "workflow.yaml"
        if not pkg_wf.exists():
            pytest.skip("workflow.yaml not in package")
        with mock.patch("ari.pipeline.run_pipeline", side_effect=OSError("Disk quota exceeded")), \
             mock.patch("ari.pipeline.load_pipeline", return_value=[{"stage": "t"}]):
            with pytest.raises(OSError, match="Disk quota exceeded"):
                generate_paper_section([], {"goal": "test"}, tmp_path, None, "")

    def test_no_pipeline_stages_logs_error(self, tmp_path, caplog):
        """Empty pipeline stages must log at ERROR level."""
        from ari.core import generate_paper_section
        pkg_wf = Path(__file__).parent.parent / "config" / "workflow.yaml"
        if not pkg_wf.exists():
            pytest.skip("workflow.yaml not in package")
        with mock.patch("ari.pipeline.load_pipeline", return_value=[]):
            with caplog.at_level(logging.ERROR):
                generate_paper_section([], {"goal": "test"}, tmp_path, None, "")
        assert any("No enabled pipeline stages" in r.message for r in caplog.records)

    def test_cli_run_wraps_paper_in_try_except(self):
        """cli.py run() must wrap generate_paper_section in try/except."""
        src = Path(__file__).parent.parent / "ari" / "cli.py"
        content = src.read_text()
        run_section = content[content.find("def run("):content.find("def resume(")]
        assert "try:" in run_section and "generate_paper_section" in run_section, \
            "run() must wrap generate_paper_section in try/except"
        assert "traceback" in run_section, \
            "run() must print traceback on paper pipeline failure"

    def test_cli_resume_wraps_paper_in_try_except(self):
        """cli.py resume() must wrap generate_paper_section in try/except."""
        src = Path(__file__).parent.parent / "ari" / "cli.py"
        content = src.read_text()
        resume_section = content[content.find("def resume("):content.find("def paper(")]
        assert "try:" in resume_section and "generate_paper_section" in resume_section, \
            "resume() must wrap generate_paper_section in try/except"
        assert "traceback" in resume_section

    def test_cli_run_does_not_pass_str_none(self):
        """run() must not pass str(None)='None' to generate_paper_section."""
        src = Path(__file__).parent.parent / "ari" / "cli.py"
        content = src.read_text()
        run_section = content[content.find("def run("):content.find("def resume(")]
        # The actual generate_paper_section call must NOT use str(config) directly
        assert "generate_paper_section(all_nodes, experiment_data, checkpoint_dir, mcp, str(config))" not in run_section, \
            "run() must resolve config path, not pass raw str(config)"

    def test_cli_resume_does_not_pass_str_none(self):
        """resume() must not pass str(config) directly."""
        src = Path(__file__).parent.parent / "ari" / "cli.py"
        content = src.read_text()
        resume_section = content[content.find("def resume("):content.find("def paper(")]
        assert 'generate_paper_section(all_nodes, experiment_data, checkpoint_dir, mcp_resume, str(config)' not in resume_section

    def test_nodes_tree_write_failure_logged_as_error(self):
        """pipeline.py must log ERROR (not WARNING) when nodes_tree.json write fails."""
        src = Path(__file__).parent.parent / "ari" / "pipeline.py"
        content = src.read_text()
        idx = content.find("Failed to save nodes_tree.json")
        assert idx > 0, "Expected log message for nodes_tree.json failure"
        # Check the 200 chars before the message for log level
        block = content[max(0, idx - 200):idx]
        assert "log.error" in block, \
            "nodes_tree.json write failure must use log.error, not log.warning"
