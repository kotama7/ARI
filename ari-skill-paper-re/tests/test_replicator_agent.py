"""Tests for :mod:`_replicator_agent` — the agent-mode Replicator entry.

The full agent rollout requires real LLM API access and a 12-hour wall-clock
budget, so end-to-end execution is out of scope for unit tests. We verify
the *integration boundaries* with vendor / sandbox / Pydantic instead:

* :class:`AriPBSolver` is a real chz subclass of :class:`BasicAgentSolver`
  that yields the full vendor tool set.
* :func:`_bypass_docker_sanity_check` actually swaps the module function.
* :func:`run_replicator_agent` builds real Computer + Task + Solver
  instances and starts ``task.setup`` against a real LocalComputer (we
  short-circuit the LLM-driven loop by patching only the inner
  ``_execute_agent_and_periodically_upload_logs`` to a no-op so we can
  verify the surrounding wiring without burning API spend).
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for p in (str(ROOT), str(SRC)):
    if p not in sys.path:
        sys.path.insert(0, p)

import _vendor_path  # noqa: F401, E402

from _replicator_agent import (  # noqa: E402
    AriPBSolver,
    _bypass_docker_sanity_check,
    run_replicator_agent,
)
from paperbench.solvers.basicagent.solver import BasicAgentSolver  # noqa: E402
import paperbench.solvers.utils as _pb_solver_utils  # noqa: E402
from paperbench.solvers.basicagent.completer import (  # noqa: E402
    OpenAIResponsesTurnCompleterConfig,
)


pytestmark = pytest.mark.asyncio


def test_aripb_solver_is_real_subclass_with_full_tool_set():
    solver = AriPBSolver(
        completer_config=OpenAIResponsesTurnCompleterConfig(model="gpt-5-mini"),
        time_limit=60,
        iterative_agent=False,
    )
    assert isinstance(solver, BasicAgentSolver)
    tools = solver._get_tools()
    # Identify tools by their declared name() — non-submit tools are
    # transparently wrapped in ``_BoundedOutputTool`` so ``type(t).__name__``
    # would only see the wrapper class.
    names = {t.name() for t in tools}
    assert {"bash", "python-tool", "search_file", "read_file_chunk", "submit"} <= names


def test_aripb_solver_iterative_mode_drops_python_and_searchfile():
    """Vendor: when iterative_agent=True, tools=[Bash, ReadFileChunk] only
    (paper §5.3 — agent should focus on bash + file-read for diagnosis)."""
    solver = AriPBSolver(
        completer_config=OpenAIResponsesTurnCompleterConfig(model="gpt-5-mini"),
        time_limit=60,
        iterative_agent=True,
    )
    names = {t.name() for t in solver._get_tools()}
    assert "bash" in names
    assert "read_file_chunk" in names
    # Submit is still included by default (use_submit_tool=True)
    assert "submit" in names
    # PythonTool / SearchFile are NOT in the iterative tool set
    assert "python-tool" not in names
    assert "search_file" not in names


async def test_bypass_docker_sanity_swap_and_restore():
    orig = _pb_solver_utils.sanity_check_docker
    async with _bypass_docker_sanity_check():
        assert _pb_solver_utils.sanity_check_docker is not orig
        # The replacement must accept a computer arg without raising.
        await _pb_solver_utils.sanity_check_docker(None)
    assert _pb_solver_utils.sanity_check_docker is orig


async def test_bypass_also_neuters_alcatraz_upload_helpers():
    """``upload_heavy_logs`` would ``cp -rp /home/submission /tmp/...`` on
    the host under LocalComputer. That must not happen — bypass it.
    """
    import paperbench.solvers.upload as _pb_upload
    import paperbench.solvers.basicagent.utils as _pb_ba_utils

    orig_heavy = _pb_upload.upload_heavy_logs
    orig_optional = _pb_ba_utils.optionally_upload_heavy_logs

    async with _bypass_docker_sanity_check():
        assert _pb_upload.upload_heavy_logs is not orig_heavy
        assert _pb_ba_utils.optionally_upload_heavy_logs is not orig_optional
        # Both replacements must accept the same call signatures upstream
        # uses, even if we don't exercise every kwarg.
        await _pb_upload.upload_heavy_logs(
            computer=None, agent_start_time=0,
            agent_dir_config=None, run_dir="", run_group_id="",
            runs_dir="", run_id="",
        )
        out = await _pb_ba_utils.optionally_upload_heavy_logs(
            computer=None, task=None, run_dir="",
            num_steps=0, start_time=0.0, last_time_uploaded=0.0,
            upload_interval_messages=None, upload_interval_seconds=None,
        )
        # The replacement returns a duck-typed object with the two
        # attributes upstream's caller unpacks.
        assert hasattr(out, "last_time_uploaded")
        assert hasattr(out, "upload_task")

    assert _pb_upload.upload_heavy_logs is orig_heavy
    assert _pb_ba_utils.optionally_upload_heavy_logs is orig_optional


async def test_bypass_patches_solver_module_local_names():
    """solver.py imports these via ``from X import Y`` at module load — so
    the local references survive any patch on the source modules. The bypass
    MUST also patch ``paperbench.solvers.basicagent.solver`` namespace,
    otherwise the post-rollout ``upload_heavy_logs(...)`` call inside
    solver.py runs the upstream version and ``mkdir -p /home/submission``
    blows up on a non-alcatraz host.
    """
    import paperbench.solvers.basicagent.solver as _pb_ba_solver

    orig_solver_heavy = _pb_ba_solver.upload_heavy_logs
    orig_solver_optional = _pb_ba_solver.optionally_upload_heavy_logs
    orig_solver_sanity = _pb_ba_solver.sanity_check_docker

    async with _bypass_docker_sanity_check():
        assert _pb_ba_solver.upload_heavy_logs is not orig_solver_heavy
        assert _pb_ba_solver.optionally_upload_heavy_logs is not orig_solver_optional
        assert _pb_ba_solver.sanity_check_docker is not orig_solver_sanity

    assert _pb_ba_solver.upload_heavy_logs is orig_solver_heavy
    assert _pb_ba_solver.optionally_upload_heavy_logs is orig_solver_optional
    assert _pb_ba_solver.sanity_check_docker is orig_solver_sanity


async def test_run_replicator_agent_writes_workspace_layout(monkeypatch):
    """Smoke test the entry-point wiring without burning API spend.

    Strategy: patch ``BasicAgentSolver._execute_agent_and_periodically_upload_logs``
    (the inner LLM-driven loop) to a no-op that simulates the agent writing
    a ``reproduce.sh`` to ``submission/``. Everything else (computer
    construction, task setup, sanity-check bypass, file promotion) runs for
    real.
    """
    async def _fake_execute(self, *, computer, task, prompt):
        # Simulate an agent that writes reproduce.sh into submission/.
        await computer.upload(
            b"#!/usr/bin/env bash\nset -euo pipefail\necho ok\n",
            "submission/reproduce.sh",
        )

    monkeypatch.setattr(
        BasicAgentSolver,
        "_execute_agent_and_periodically_upload_logs",
        _fake_execute,
        raising=True,
    )

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        paper = td / "paper.md"
        paper.write_text("# Test\n\nClaim: x.\n")
        out = td / "workspace"

        result = await run_replicator_agent(
            paper_md_path=str(paper),
            output_dir=str(out),
            expected_artifacts=["results.csv"],
            time_limit_sec=60,
            iterative_agent=False,
            sandbox_kind="local",
        )

        # Promotion: submission/reproduce.sh → workspace root.
        assert (out / "reproduce.sh").is_file()
        # Real envelope shape (not a stub dict).
        assert result["populated"] is True
        assert "reproduce.sh" in result["files"]
        assert result["expected_artifacts"] == ["results.csv"]
        assert result["max_runtime_sec"] == 60
        assert result["iterative_agent"] is False
        # Workspace was bootstrapped by task.setup
        assert (out / "paper" / "paper.md").is_file()
        assert (out / "instructions.txt").is_file()


# ─── vendor prompt adoption ──────────────────────────────────────────────


def test_adapt_vendor_paths_rewrites_alcatraz_hardcodes():
    """Path adapter rewrites every ``/home/*`` hardcode upstream's prompt
    files use, but leaves unrelated text intact."""
    from _replicator_agent import _adapt_vendor_paths

    raw = (
        "Your repository should be located at /home/submission/ and the "
        "reproduce script at /home/submission/reproduce.sh.\n"
        "The paper is at /home/paper/paper.md and addendum at /home/paper/addendum.md.\n"
        "API keys are at /home/agent.env.\n"
        "Logs go to /home/logs.\n"
        "Unrelated text mentioning /home/user-data should NOT be touched."
    )
    out = _adapt_vendor_paths(raw)
    assert "/home/submission" not in out
    assert "/home/paper" not in out
    assert "/home/agent.env" not in out
    assert "/home/logs" not in out
    assert "submission/reproduce.sh" in out
    assert "paper/paper.md" in out
    assert "paper/addendum.md" in out
    assert "./agent.env" in out
    assert "./logs" in out
    # Untouched
    assert "/home/user-data" in out


async def test_run_agent_uses_vendor_prompts(monkeypatch):
    """The conversation prompt fed to the LLM comes from PaperBench upstream
    (``get_instructions`` + ``get_system_message``), with absolute paths
    rewritten to ari's workspace-flat layout, plus a rubric-driven
    EXPECTED_ARTIFACTS section appended.
    """
    captured: dict = {}

    async def _capture(self, *, computer, task, prompt):
        captured["prompt"] = prompt

    monkeypatch.setattr(
        BasicAgentSolver,
        "_execute_agent_and_periodically_upload_logs",
        _capture,
        raising=True,
    )

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        paper = td / "paper.md"
        paper.write_text("# Paper\n\nClaim: SpMM at 5.67 GB/s.\n")
        out = td / "ws"

        await run_replicator_agent(
            paper_md_path=str(paper),
            output_dir=str(out),
            expected_artifacts=["results.csv", "perf.csv"],
            time_limit_sec=12 * 3600,
            iterative_agent=False,
            sandbox_kind="local",
        )

    sys_msg = captured["prompt"][0]["content"]
    user_msg = captured["prompt"][1]["content"]

    # 1) System message is upstream's, recognisable by the strong-effort wording
    assert "You are a helpful agent attempting to solve a task" in sys_msg
    assert "Use as much of the available time as possible" in sys_msg

    # 2) User instructions come from upstream's code_only_instructions.txt;
    #    we don't pin a verbatim sentence (vendor may revise) but the
    #    SUBMISSION section header is upstream-specific.
    assert "SUBMISSION" in user_msg
    assert "reproduce.sh" in user_msg

    # 3) ari-side: no /home/{submission,paper,agent.env,logs} hardcodes
    for hardcode in ("/home/submission", "/home/paper", "/home/agent.env", "/home/logs"):
        assert hardcode not in sys_msg, f"{hardcode!r} leaked into system message"
        assert hardcode not in user_msg, f"{hardcode!r} leaked into user message"

    # 4) ari-side: rubric-driven EXPECTED_ARTIFACTS appended for the grader
    assert "EXPECTED_ARTIFACTS" in user_msg
    assert "- results.csv" in user_msg
    assert "- perf.csv" in user_msg

    # 5) ari NEVER inherits its own former early-submit license
    for forbidden in (
        "5-minute proof-of-concept",
        "Truncated reproduction is fine",
    ):
        assert forbidden not in sys_msg
        assert forbidden not in user_msg


# ─── tool output truncation ──────────────────────────────────────────────


def test_truncate_tool_output_passthrough_when_short():
    from _replicator_agent import _truncate_tool_output

    text = "small output\n"
    assert _truncate_tool_output(text, max_bytes=1024) == text


def test_truncate_tool_output_caps_oversized_payload():
    from _replicator_agent import _truncate_tool_output

    big = "x" * (300 * 1024)  # 300 KB > 200 KB cap
    out = _truncate_tool_output(big, max_bytes=200 * 1024)
    encoded = out.encode("utf-8")
    # Always under the cap (incl. marker)
    assert len(encoded) <= 200 * 1024
    # Marker present so the agent knows it was cut
    assert "TOOL OUTPUT TRUNCATED" in out
    # Original size preserved in the marker for diagnostics
    assert "307,200" in out  # 300 KB == 307200 bytes


def test_truncate_tool_output_handles_unicode_at_boundary():
    """Cutting bytes (not chars) can land mid-multibyte; replace silently."""
    from _replicator_agent import _truncate_tool_output

    # 100k of "あ" (3 bytes each in UTF-8) = 300 KB, hard to land cleanly
    big = "あ" * 100_000
    out = _truncate_tool_output(big, max_bytes=1024)
    # Must be valid Python str (no UnicodeDecodeError raised)
    assert isinstance(out, str)
    assert "TOOL OUTPUT TRUNCATED" in out


async def test_aripb_solver_wraps_tools_with_bounded_output():
    """All non-submit tools returned by ``_get_tools`` are wrapped so a
    runaway stdout never reaches the OpenAI API verbatim. Submit is the
    only exception (its ``execute`` is never invoked by handle_tool_call).
    """
    from _replicator_agent import _BoundedOutputTool

    solver = AriPBSolver(
        completer_config=OpenAIResponsesTurnCompleterConfig(model="gpt-5-mini"),
        time_limit=12 * 3600,
        use_submit_tool=True,
        use_real_time_limit=True,
        iterative_agent=False,
    )
    tools = solver._get_tools()
    names = [t.name() for t in tools]
    assert "bash" in names
    assert "submit" in names

    for t in tools:
        if t.name() == "submit":
            assert not isinstance(t, _BoundedOutputTool)
        else:
            assert isinstance(t, _BoundedOutputTool), f"{t.name()} not wrapped"


async def test_bounded_output_tool_proxies_truncated_execute(monkeypatch):
    """Wrapper actually intercepts a long stdout from the inner tool and
    replaces it with the truncated marker before returning."""
    from _replicator_agent import _BoundedOutputTool, _truncate_tool_output
    from paperbench.solvers.basicagent.tools.basic import BashTool

    bash = BashTool()
    big_output = "x" * (500 * 1024)  # 500 KB

    async def _fake_execute(self_inner, computer, cmd):  # noqa: ARG001
        return big_output

    # Patch at class level so the wrapper's stored ``inner`` reference picks
    # up the new behaviour.
    monkeypatch.setattr(BashTool, "execute", _fake_execute, raising=True)

    wrapped = _BoundedOutputTool(inner=bash, max_bytes=200 * 1024)
    result = await wrapped.execute(None, cmd="ls /")
    assert "TOOL OUTPUT TRUNCATED" in result
    assert len(result.encode("utf-8")) <= 200 * 1024
    # Forwarding identity: name + schema unchanged
    assert wrapped.name() == bash.name() == "bash"
    assert wrapped.get_oai_tool_call() == bash.get_oai_tool_call()


async def test_instructions_txt_is_brief_stub(monkeypatch):
    """The workspace's ``instructions.txt`` is now just a pointer, not the
    canonical prompt. The full task brief is delivered via the LLM
    conversation only."""
    async def _noop(self, *, computer, task, prompt):
        pass

    monkeypatch.setattr(
        BasicAgentSolver,
        "_execute_agent_and_periodically_upload_logs",
        _noop,
        raising=True,
    )

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        paper = td / "paper.md"
        paper.write_text("# x")
        out = td / "ws"

        await run_replicator_agent(
            paper_md_path=str(paper),
            output_dir=str(out),
            expected_artifacts=["x.csv"],
            time_limit_sec=60,
            iterative_agent=False,
            sandbox_kind="local",
        )

        text = (out / "instructions.txt").read_text()
        assert "conversation" in text.lower()
        # Must be short (stub, not the full task brief)
        assert len(text) < 500
