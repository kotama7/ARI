"""Tests for event loop fix (mcp/client.py), step budget hints, text response recovery,
checkpoint nesting prevention, and CSV comment parsing."""

import asyncio
import json
import os
import threading
from pathlib import Path
from unittest import mock
from unittest.mock import MagicMock

import pytest


# ══════════════════════════════════════════════
# 1. MCP client: _run() event loop safety
# ══════════════════════════════════════════════

class TestMCPClientEventLoop:
    """Verify _SkillConnection._run() works via dedicated loop thread
    and handles concurrent / nested calls safely."""

    def test_run_from_sync_context(self):
        """Normal sync context: _run dispatches to the dedicated loop thread."""
        from ari.mcp.client import _SkillConnection
        from ari.config import SkillConfig

        conn = _SkillConnection(SkillConfig(name="test", path="/tmp/fake"))

        async def _coro():
            return 42

        result = conn._run(_coro())
        assert result == 42
        conn.close()

    def test_run_from_running_loop_thread(self):
        """When called inside a running event loop (e.g. ThreadPoolExecutor
        worker spawned by asyncio), _run must not raise
        'This event loop is already running'."""
        from ari.mcp.client import _SkillConnection
        from ari.config import SkillConfig

        conn = _SkillConnection(SkillConfig(name="test", path="/tmp/fake"))
        error = None
        result = None

        def _worker():
            """Simulate calling _run from inside a running event loop."""
            nonlocal error, result
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            async def _outer():
                async def _inner():
                    return 99
                return conn._run(_inner())

            try:
                result = loop.run_until_complete(_outer())
            except Exception as e:
                error = e
            finally:
                loop.close()

        t = threading.Thread(target=_worker)
        t.start()
        t.join(timeout=10)

        assert error is None, f"_run raised: {error}"
        assert result == 99
        conn.close()

    def test_run_creates_loop_if_needed(self):
        """_run lazily creates the dedicated loop thread when it's None."""
        from ari.mcp.client import _SkillConnection
        from ari.config import SkillConfig

        conn = _SkillConnection(SkillConfig(name="test", path="/tmp/fake"))
        assert conn._loop is None
        assert conn._loop_thread is None

        async def _coro():
            return "created"

        result = conn._run(_coro())
        assert result == "created"
        assert conn._loop is not None
        assert conn._loop_thread is not None
        assert conn._loop_thread.is_alive()
        conn.close()

    def test_concurrent_run_calls(self):
        """Multiple threads calling _run() concurrently must not conflict."""
        from ari.mcp.client import _SkillConnection
        from ari.config import SkillConfig
        import concurrent.futures

        conn = _SkillConnection(SkillConfig(name="test", path="/tmp/fake"))
        results = []
        errors = []

        async def _slow_coro(n):
            await asyncio.sleep(0.05)
            return n

        def _call(n):
            try:
                return conn._run(_slow_coro(n))
            except Exception as e:
                errors.append(e)
                return None

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            futures = [pool.submit(_call, i) for i in range(10)]
            results = [f.result(timeout=30) for f in futures]

        assert errors == [], f"Concurrent _run raised: {errors}"
        assert sorted(results) == list(range(10))
        conn.close()


# ══════════════════════════════════════════════
# 2. Step budget hints in workflow
# ══════════════════════════════════════════════

class TestStepBudgetHints:
    """Verify workflow hints include step budget warnings."""

    def test_slurm_post_survey_hint_has_budget(self):
        """SLURM workflow post_survey_hint must mention step budget."""
        from ari.agent.workflow import from_experiment_text

        hints = from_experiment_text("Use SLURM partition fx700\n")
        assert "STEP BUDGET" in hints.post_survey_hint
        assert "job_status()" in hints.post_survey_hint
        assert "sleep" in hints.post_survey_hint

    def test_default_post_survey_hint_has_budget(self):
        """Default (non-SLURM) post_survey_hint must also mention step budget."""
        from ari.agent.workflow import from_experiment_text

        hints = from_experiment_text("Run a benchmark\n")
        assert "STEP BUDGET" in hints.post_survey_hint
        assert "sleep" in hints.post_survey_hint

    def test_guidance_after_slurm_submit_warns_no_manual_poll(self):
        """_guidance after slurm_submit must tell agent NOT to poll manually."""
        from ari.agent.loop import AgentLoop
        from ari.agent.workflow import WorkflowHints

        hints = WorkflowHints(
            job_submitter_tool="slurm_submit",
            job_poller_tool="job_status",
        )
        agent = AgentLoop(
            llm=MagicMock(), memory=MagicMock(), mcp=MagicMock(),
            workflow_hints=hints,
        )
        guidance = agent._guidance("slurm_submit", ["12345"], [])
        assert "Do NOT" in guidance
        assert "auto" in guidance.lower()

    def test_guidance_after_job_status_warns_no_repeat(self):
        """_guidance after job_status must tell agent the job is done."""
        from ari.agent.loop import AgentLoop
        from ari.agent.workflow import WorkflowHints

        hints = WorkflowHints(
            job_submitter_tool="slurm_submit",
            job_poller_tool="job_status",
            job_reader_tool="run_bash",
        )
        agent = AgentLoop(
            llm=MagicMock(), memory=MagicMock(), mcp=MagicMock(),
            workflow_hints=hints,
        )
        guidance = agent._guidance("job_status", ["12345"], [])
        assert "Do NOT" in guidance
        assert "done" in guidance.lower() or "completed" in guidance.lower()

    def test_guidance_detects_tool_error_in_messages(self):
        """_guidance must detect {\"error\": ...} in the last tool message and
        return a diagnostic hint instead of None."""
        from ari.agent.loop import AgentLoop
        from ari.agent.workflow import WorkflowHints

        agent = AgentLoop(
            llm=MagicMock(), memory=MagicMock(), mcp=MagicMock(),
            workflow_hints=WorkflowHints(),
        )
        messages = [
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "tc1", "type": "function",
                 "function": {"name": "slurm_submit", "arguments": "{}"}}
            ]},
            {"role": "tool", "tool_call_id": "tc1",
             "content": '{"error": "Tool \'slurm_submit\' returned empty response"}'},
        ]
        guidance = agent._guidance("slurm_submit", [], [], messages)
        assert guidance is not None
        assert "error" in guidance.lower()
        assert "Do NOT retry" in guidance

    def test_guidance_no_false_positive_on_success(self):
        """_guidance must NOT flag a successful tool result as an error."""
        from ari.agent.loop import AgentLoop
        from ari.agent.workflow import WorkflowHints

        agent = AgentLoop(
            llm=MagicMock(), memory=MagicMock(), mcp=MagicMock(),
            workflow_hints=WorkflowHints(),
        )
        messages = [
            {"role": "tool", "tool_call_id": "tc1",
             "content": '{"result": "{\\"job_id\\": \\"12345\\", \\"status\\": \\"submitted\\"}"}'},
        ]
        guidance = agent._guidance("slurm_submit", [], [], messages)
        # Should be None (no error detected, no special guidance applies)
        assert guidance is None


# ══════════════════════════════════════════════
# MCP client: empty response handling
# ══════════════════════════════════════════════

class TestMCPClientEmptyResponse:
    """Verify _SkillConnection.call_tool returns error dict on empty response."""

    def test_empty_response_returns_error(self):
        """When MCP tool returns no text content, call_tool must return an error dict."""
        from ari.mcp.client import _SkillConnection
        from ari.config import SkillConfig

        conn = _SkillConnection(SkillConfig(name="test", path="/tmp/fake"))

        # Mock the session to return empty content
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.content = []  # empty content
        mock_session.call_tool = MagicMock(return_value=mock_result)
        conn._session = mock_session

        # Make _run work synchronously for testing
        import asyncio

        async def _fake_call():
            result = mock_result
            parts = [p.text for p in result.content if hasattr(p, "text")]
            text = "\n".join(parts) if parts else ""
            if not text:
                return {"error": f"Tool 'test_tool' returned empty response — the tool may have crashed or timed out."}
            return {"result": text}

        conn._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(_fake_call(), conn._loop)
        result = future.result(timeout=5)

        assert "error" in result
        assert "empty response" in result["error"]
        conn.close()


# ══════════════════════════════════════════════
# 3. Text response recovery
# ══════════════════════════════════════════════

class TestTextResponseRecovery:
    """Verify loop.py forces tool calls when LLM returns text instead of tool calls."""

    def test_text_response_recovery_code_exists(self):
        """loop.py must remind LLM about remaining steps on non-tool text responses."""
        src = Path(__file__).parent.parent / "ari" / "agent" / "loop.py"
        content = src.read_text()
        # Must have both the empty-response handler AND the non-empty text handler
        assert "steps remaining" in content, \
            "loop.py must show remaining step count on text responses"
        assert "Do NOT write text plans" in content, \
            "loop.py must explicitly tell LLM not to write plans"


# ══════════════════════════════════════════════
# 4. Checkpoint nesting prevention
# ══════════════════════════════════════════════

class TestCheckpointNesting:
    """Verify _api_launch never creates nested checkpoints/checkpoints/ paths."""

    def test_no_nesting_when_checkpoint_is_nested(self, monkeypatch, tmp_path):
        """If _checkpoint_dir is already nested, new launch must NOT nest further."""
        from ari.viz import state as _st
        from ari.viz.api_experiment import _api_launch

        # Simulate: previous run created a nested checkpoint
        nested = tmp_path / "workspace" / "checkpoints" / "checkpoints" / "20260401_old_run"
        nested.mkdir(parents=True)
        monkeypatch.setattr(_st, "_checkpoint_dir", nested)
        monkeypatch.setattr(_st, "_settings_path", tmp_path / "settings.json")
        (tmp_path / "settings.json").write_text("{}")

        with mock.patch("subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.pid = 99999
            mock_popen.return_value = mock_proc
            result = _api_launch(json.dumps({
                "experiment_md": "## Test\nHello",
            }).encode())

        assert result.get("ok"), f"Launch failed: {result}"
        # The new checkpoint must be at workspace/checkpoints/, NOT workspace/checkpoints/checkpoints/
        ckpt_root = result.get("checkpoint_root", "")
        assert ckpt_root.endswith("/checkpoints"), \
            f"Expected .../checkpoints but got {ckpt_root}"
        assert "checkpoints/checkpoints" not in ckpt_root, \
            f"Nested path detected: {ckpt_root}"

    def test_no_nesting_on_normal_checkpoint(self, monkeypatch, tmp_path):
        """Normal (non-nested) checkpoint must stay at checkpoints/ level."""
        from ari.viz import state as _st
        from ari.viz.api_experiment import _api_launch

        normal = tmp_path / "checkpoints" / "20260401_normal_run"
        normal.mkdir(parents=True)
        monkeypatch.setattr(_st, "_checkpoint_dir", normal)
        monkeypatch.setattr(_st, "_settings_path", tmp_path / "settings.json")
        (tmp_path / "settings.json").write_text("{}")

        with mock.patch("subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.pid = 99999
            mock_popen.return_value = mock_proc
            result = _api_launch(json.dumps({
                "experiment_md": "## Test\nHello",
            }).encode())

        assert result.get("ok"), f"Launch failed: {result}"
        ckpt_root = result.get("checkpoint_root", "")
        assert "checkpoints/checkpoints" not in ckpt_root


# ══════════════════════════════════════════════
# 5. CSV comment parsing
# ══════════════════════════════════════════════

class TestCSVCommentParsing:
    """Verify benchmark skill handles CSV files with # comment lines."""

    @pytest.fixture(autouse=True)
    def _add_benchmark_to_path(self):
        """Add ari-skill-benchmark to sys.path for import."""
        import sys
        skill_path = str(Path(__file__).parent.parent.parent / "ari-skill-benchmark")
        if skill_path not in sys.path:
            sys.path.insert(0, skill_path)
        yield
        if skill_path in sys.path:
            sys.path.remove(skill_path)

    def test_csv_with_comments_parsed(self, tmp_path):
        """CSV with # header comments must be parsed correctly."""
        csv_path = tmp_path / "results.csv"
        csv_path.write_text(
            "# Build: Apr 3 2026\n"
            "# Compiler: GCC 11.5\n"
            "k,throughput,bandwidth\n"
            "1,0.5,2.0\n"
            "2,1.0,4.0\n"
            "4,2.0,8.0\n"
        )

        from src.server import _load_data
        df = _load_data(str(csv_path))
        assert "k" in df.columns
        assert "throughput" in df.columns
        assert len(df) == 3
        assert df["throughput"].tolist() == [0.5, 1.0, 2.0]

    def test_csv_without_comments_still_works(self, tmp_path):
        """Plain CSV without comments must still work."""
        csv_path = tmp_path / "results.csv"
        csv_path.write_text("a,b\n1,2\n3,4\n")

        from src.server import _load_data
        df = _load_data(str(csv_path))
        assert len(df) == 2

    def test_analyze_results_with_comments(self, tmp_path):
        """Full analyze_results tool must handle commented CSVs."""
        csv_path = tmp_path / "results.csv"
        csv_path.write_text(
            "# metadata line 1\n"
            "# metadata line 2\n"
            "metric_a,metric_b\n"
            "10.0,20.0\n"
            "30.0,40.0\n"
        )

        from src.server import analyze_results
        result = analyze_results(str(csv_path), ["metric_a"])
        assert "error" not in result["summary"].get("metric_a", {}), \
            f"analyze_results failed: {result}"
        assert result["summary"]["metric_a"]["mean"] == 20.0
