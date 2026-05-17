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


# ─── execution_profile / cluster shape / HPC appendix ────────────────────


def test_format_hpc_appendix_returns_empty_for_legacy_single_node():
    """Legacy single-node paper (no artifacts, no profile, default shape)
    yields no appendix → preserves the pre-v0.7.2 behaviour exactly."""
    from _replicator_agent import _format_hpc_appendix

    out = _format_hpc_appendix(
        expected_artifacts=[],
        execution_profile={},
        cluster_shape={"SLURM_JOB_NUM_NODES": "1", "SLURM_NTASKS": "1", "GPU_LIST": "none visible"},
    )
    assert out == ""


def test_format_hpc_appendix_includes_expected_artifacts_only():
    """Domain isolation: when only artifacts are present (non-HPC paper),
    the appendix is byte-equivalent to the pre-v0.7.2 EXPECTED_ARTIFACTS-only
    block. CLUSTER SHAPE / EXECUTION PROFILE / COMPUTE-NODE CONVENTIONS
    must NOT leak into non-HPC paper runs."""
    from _replicator_agent import _format_hpc_appendix

    out = _format_hpc_appendix(
        expected_artifacts=["results.csv", "perf.csv"],
        execution_profile={},
        cluster_shape={"SLURM_JOB_NUM_NODES": "1", "SLURM_NTASKS": "1", "GPU_LIST": "none visible"},
    )
    assert "EXPECTED_ARTIFACTS" in out
    assert "- results.csv" in out
    assert "- perf.csv" in out
    # Domain-isolation: no HPC-specific content when execution_profile is empty
    assert "EXECUTION PROFILE" not in out
    assert "CLUSTER SHAPE" not in out
    assert "COMPUTE-NODE EXECUTION CONVENTIONS" not in out
    assert "SLURM" not in out
    assert "mpirun" not in out
    assert "srun" not in out


def test_format_hpc_appendix_no_hpc_leak_when_inside_unrelated_slurm():
    """Regression guard: even when ARI happens to run inside a SLURM
    allocation, a non-HPC paper (no execution_profile in its rubric) must
    NOT see CLUSTER SHAPE or COMPUTE-NODE conventions. Otherwise an NLP /
    vision / theory paper would receive HPC-flavoured agent guidance just
    because $SLURM_NTASKS is set in the environment.
    """
    from _replicator_agent import _format_hpc_appendix

    out = _format_hpc_appendix(
        expected_artifacts=["nlp_eval.csv"],
        execution_profile={},                              # non-HPC paper
        cluster_shape={                                    # but inside SLURM
            "SLURM_JOB_NUM_NODES": "4",
            "SLURM_NTASKS": "32",
            "GPU_LIST": "Tesla V100 ×4",
        },
    )
    # The agent still sees EXPECTED_ARTIFACTS, but nothing else.
    assert "EXPECTED_ARTIFACTS" in out
    assert "- nlp_eval.csv" in out
    assert "CLUSTER SHAPE" not in out
    assert "SLURM_JOB_NUM_NODES = 4" not in out
    assert "COMPUTE-NODE EXECUTION CONVENTIONS" not in out
    assert "srun" not in out
    assert "mpirun" not in out


def test_format_hpc_appendix_mpi_kind_emits_full_conventions():
    """MPI execution_profile drives the srun / mpirun / metric_columns
    convention block and the COMPUTE-NODE conventions footer."""
    from _replicator_agent import _format_hpc_appendix

    out = _format_hpc_appendix(
        expected_artifacts=["submission/results/scaling.csv"],
        execution_profile={
            "kind": "mpi_gpu",
            "paper_max_ranks": 32,
            "metric_columns": ["nodes", "ranks", "runtime_sec", "gflops"],
            "accepts_reduced_scale": True,
            "module_loads": ["cuda/12.4", "openmpi/4.1"],
        },
        cluster_shape={
            "SLURM_JOB_NUM_NODES": "4",
            "SLURM_NTASKS": "32",
            "GPU_LIST": "Tesla V100-SXM2-16GB ×4",
        },
    )
    # EXECUTION PROFILE block JSON-encoded
    assert "EXECUTION PROFILE" in out
    assert '"kind": "mpi_gpu"' in out
    assert '"metric_columns"' in out
    # CLUSTER SHAPE picked up the SLURM env
    assert "SLURM_JOB_NUM_NODES = 4" in out
    assert "SLURM_NTASKS        = 32" in out
    assert "V100" in out
    # MPI convention: srun preferred, metric_columns reflected
    assert "srun -n $SLURM_NTASKS" in out
    assert "'nodes'" in out and "'gflops'" in out
    assert "submission/mpi_aggregate.py" in out
    # accepts_reduced_scale
    assert "paper_paper_scale_point" in out
    # module_loads
    assert "module load cuda/12.4 openmpi/4.1" in out
    # COMPUTE-NODE conventions are always present
    assert "COMPUTE-NODE EXECUTION CONVENTIONS" in out
    assert "PREFER srun over mpirun" in out
    assert "Multi-node fan-out" in out
    assert "Timeout wrapping" in out


def test_format_hpc_appendix_gpu_single_warns_off_numpy():
    """A GPU-bearing kind without MPI still emits the "do NOT fall back to
    NumPy" guidance — agent must use CUDA / cupy."""
    from _replicator_agent import _format_hpc_appendix

    out = _format_hpc_appendix(
        expected_artifacts=[],
        execution_profile={"kind": "gpu_single"},
        cluster_shape={"SLURM_JOB_NUM_NODES": "1", "SLURM_NTASKS": "1", "GPU_LIST": "Tesla V100"},
    )
    assert "EXECUTION PROFILE" in out
    assert "NumPy" in out


def test_detect_cluster_shape_reads_slurm_env(monkeypatch):
    from _replicator_agent import detect_cluster_shape

    monkeypatch.setenv("SLURM_JOB_NUM_NODES", "4")
    monkeypatch.setenv("SLURM_NTASKS", "32")
    shape = detect_cluster_shape()
    assert shape["SLURM_JOB_NUM_NODES"] == "4"
    assert shape["SLURM_NTASKS"] == "32"
    # GPU_LIST is best-effort; "none visible" when nvidia-smi is absent
    assert isinstance(shape["GPU_LIST"], str)


def test_detect_cluster_shape_defaults_outside_slurm(monkeypatch):
    from _replicator_agent import detect_cluster_shape

    monkeypatch.delenv("SLURM_JOB_NUM_NODES", raising=False)
    monkeypatch.delenv("SLURM_NTASKS", raising=False)
    shape = detect_cluster_shape()
    assert shape["SLURM_JOB_NUM_NODES"] == "1"
    assert shape["SLURM_NTASKS"] == "1"


async def test_run_agent_passes_execution_profile_into_user_message(monkeypatch):
    """end-to-end: execution_profile → LocalPBTask → AriPBSolver._run_agent
    → user_msg contains EXECUTION PROFILE block.
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
    monkeypatch.setenv("SLURM_JOB_NUM_NODES", "4")
    monkeypatch.setenv("SLURM_NTASKS", "32")

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        paper = td / "paper.md"
        paper.write_text("# Paper\n\nClaim: TS-SpGEMM scales to 32 ranks.\n")
        out = td / "ws"

        await run_replicator_agent(
            paper_md_path=str(paper),
            output_dir=str(out),
            expected_artifacts=["submission/results/scaling.csv"],
            execution_profile={
                "kind": "mpi_gpu",
                "paper_max_ranks": 32,
                "metric_columns": ["nodes", "ranks", "runtime_sec", "gflops"],
                "module_loads": ["cuda/12.4"],
            },
            time_limit_sec=60,
            iterative_agent=False,
            sandbox_kind="local",
        )

        user_msg = captured["prompt"][1]["content"]
        # EXPECTED_ARTIFACTS still present
        assert "EXPECTED_ARTIFACTS" in user_msg
        assert "- submission/results/scaling.csv" in user_msg
        # NEW: EXECUTION PROFILE JSON block
        assert "EXECUTION PROFILE" in user_msg
        assert '"kind": "mpi_gpu"' in user_msg
        # NEW: CLUSTER SHAPE from SLURM env
        assert "SLURM_JOB_NUM_NODES = 4" in user_msg
        assert "SLURM_NTASKS        = 32" in user_msg
        # NEW: COMPUTE-NODE conventions footer
        assert "COMPUTE-NODE EXECUTION CONVENTIONS" in user_msg
        assert "module load cuda/12.4" in user_msg

        # MPI skeleton was auto-injected
        skel = out / "submission" / "mpi_aggregate.py"
        assert skel.is_file()
        assert "gather_and_write_csv" in skel.read_text()


async def test_run_agent_no_appendix_for_legacy_paper(monkeypatch):
    """Legacy call site without execution_profile, no artifacts: user_msg
    must contain neither EXECUTION PROFILE nor EXPECTED_ARTIFACTS blocks,
    only the vendor instructions. Verifies backward compat (P2 acceptance).
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
    monkeypatch.delenv("SLURM_JOB_NUM_NODES", raising=False)
    monkeypatch.delenv("SLURM_NTASKS", raising=False)

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        paper = td / "paper.md"
        paper.write_text("# A trivial CPU paper.\n")
        out = td / "ws"

        await run_replicator_agent(
            paper_md_path=str(paper),
            output_dir=str(out),
            expected_artifacts=[],
            time_limit_sec=60,
            iterative_agent=False,
            sandbox_kind="local",
        )

        user_msg = captured["prompt"][1]["content"]
        assert "EXECUTION PROFILE" not in user_msg
        assert "EXPECTED_ARTIFACTS" not in user_msg
        assert "COMPUTE-NODE EXECUTION CONVENTIONS" not in user_msg
        # MPI skeleton must NOT be injected for legacy papers
        assert not (out / "submission" / "mpi_aggregate.py").exists()


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
