"""Phase 1 + Phase 2 round-trip tests (Step 4 DoD)."""

from __future__ import annotations

import importlib.util
import json
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for p in (str(ROOT), str(SRC)):
    if p not in sys.path:
        sys.path.insert(0, p)

# Load this skill's server.py explicitly under a unique name to avoid
# clashing with other ari-skill-*/src/server.py modules pytest may have
# already imported.
_spec = importlib.util.spec_from_file_location("paper_re_server", SRC / "server.py")
S = importlib.util.module_from_spec(_spec)
sys.modules["paper_re_server"] = S
_spec.loader.exec_module(S)


def _envelope(leaves: list[dict]) -> dict:
    return {
        "version": "3",
        "paper_sha256": "a" * 64,
        "rubric_sha256": "b" * 64,
        "generator": {
            "model": "test/m",
            "prompt_sha256": "c" * 64,
            "generated_at": "2026-04-30T00:00:00Z",
            "temperature": 0.0,
        },
        "reproduce_contract": {
            "script_path": "reproduce.sh",
            "max_runtime_sec": 60,
            "expected_artifacts": ["reproduce.log", "results/summary.txt"],
        },
        "rubric": {
            "id": str(uuid.uuid4()),
            "requirements": "Replicate the paper's main contribution.",
            "weight": 1,
            "sub_tasks": leaves,
        },
    }


def _leaf(text: str) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "requirements": text,
        "weight": 1,
        "sub_tasks": [],
        "task_category": "Code Development",
        "finegrained_task_category": "Method Implementation",
    }


def _write_rubric(tmp_path: Path, leaves: list[dict]) -> Path:
    path = tmp_path / "rubric.json"
    path.write_text(json.dumps(_envelope(leaves)))
    return path


# ── run_reproduce ──

@pytest.mark.asyncio
async def test_run_reproduce_local_executes_script(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    sh = repo / "reproduce.sh"
    sh.write_text("#!/bin/bash\nmkdir -p results\necho 'METRIC: 0.42' | tee results/summary.txt\n")
    sh.chmod(0o755)
    rubric_path = _write_rubric(tmp_path, [_leaf("trivial")])

    res = await S.run_reproduce(
        rubric_path=str(rubric_path),
        repo_dir=str(repo),
        sandbox_kind="local",
        timeout_global_sec=30,
    )
    assert res["executed"] is True
    assert res["exit_code"] == 0
    assert "reproduce.log" in res["artifacts"]
    assert any(a.endswith("summary.txt") for a in res["artifacts"])
    assert res["missing"] == []
    log_text = (repo / "reproduce.log").read_text()
    assert "METRIC: 0.42" in log_text


@pytest.mark.asyncio
async def test_run_reproduce_tolerates_empty_rubric_path(tmp_path):
    """Regression: bridge.reproduce_submission drives run_reproduce
    without a rubric (the caller supplies all hints via explicit args).
    An empty rubric_path must NOT short-circuit with an error envelope —
    it should fall through to caller-arg-only execution.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    sh = repo / "reproduce.sh"
    sh.write_text("#!/bin/bash\necho 'no-rubric path' > out.txt\n")
    sh.chmod(0o755)

    res = await S.run_reproduce(
        rubric_path="",
        repo_dir=str(repo),
        sandbox_kind="local",
        timeout_global_sec=30,
    )
    assert res["executed"] is True
    assert res["exit_code"] == 0
    assert "reproduce.log" in res["artifacts"]
    # No rubric → no expected_artifacts → nothing should land in "missing".
    assert res["missing"] == []


@pytest.mark.asyncio
async def test_run_reproduce_missing_script(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    rubric_path = _write_rubric(tmp_path, [_leaf("trivial")])
    res = await S.run_reproduce(
        rubric_path=str(rubric_path), repo_dir=str(repo),
        sandbox_kind="local", timeout_global_sec=30,
    )
    assert res["executed"] is False
    assert "reproduce.sh missing" in res.get("error", "")


@pytest.mark.asyncio
async def test_run_reproduce_reports_missing_artifacts(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    sh = repo / "reproduce.sh"
    sh.write_text("#!/bin/bash\necho hi\n")
    sh.chmod(0o755)
    rubric_path = _write_rubric(tmp_path, [_leaf("trivial")])
    res = await S.run_reproduce(
        rubric_path=str(rubric_path), repo_dir=str(repo),
        sandbox_kind="local", timeout_global_sec=30,
    )
    assert "results/summary.txt" in res["missing"]


# ── grade_with_simplejudge ──
#
# These hit the real upstream PaperBench SimpleJudge → OpenAI. Skipped by
# default — set ``ARI_RUN_LIVE_LLM_TESTS=1`` to opt in. There is no local
# fallback (per spec); the upstream completer enforces a fixed list of
# supported models, so we use ``gpt-4o-2024-08-06`` as the default test
# model (PaperBench's known-good).

import os

_LIVE_LLM = (
    os.environ.get("ARI_RUN_LIVE_LLM_TESTS", "0") == "1"
    and bool(os.environ.get("OPENAI_API_KEY"))
)
_JUDGE_MODEL = os.environ.get("ARI_TEST_JUDGE_MODEL", "gpt-4o-2024-08-06")


@pytest.mark.asyncio
@pytest.mark.skipif(not _LIVE_LLM, reason="set ARI_RUN_LIVE_LLM_TESTS=1 + OPENAI_API_KEY to opt in")
async def test_grade_empty_repo_negative_control(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    rubric_path = _write_rubric(tmp_path, [
        _leaf("Implement the MaskNetwork architecture for selfish-mining environment."),
        _leaf("Run Experiment II producing pre-refinement and post-refinement metrics."),
    ])
    res = await S.grade_with_simplejudge(
        rubric_path=str(rubric_path),
        repo_dir=str(repo),
        paper_text="paper text",
        judge_model=_JUDGE_MODEL,
        n_runs=1,
        skip_negative_control=True,
    )
    assert res["ors_score"] < 0.05
    assert res["n_runs"] == 1
    assert "leaf_grades" in res
    assert isinstance(res["rubric_sha256"], str)


@pytest.mark.asyncio
@pytest.mark.skipif(not _LIVE_LLM, reason="set ARI_RUN_LIVE_LLM_TESTS=1 + OPENAI_API_KEY to opt in")
async def test_grade_invokes_negative_control(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    sh = repo / "reproduce.sh"
    sh.write_text("#!/bin/bash\necho 'no-op'\n")
    sh.chmod(0o755)
    rubric_path = _write_rubric(tmp_path, [_leaf("Implement MaskNetwork outputs zero for critical states.")])
    res = await S.grade_with_simplejudge(
        rubric_path=str(rubric_path),
        repo_dir=str(repo),
        paper_text="paper",
        judge_model=_JUDGE_MODEL,
        n_runs=1,
        skip_negative_control=False,
    )
    nc = res["negative_control_check"]
    assert nc["empty"] < 0.05
    assert nc["boilerplate"] < 0.05
    assert nc["passed"] is True


@pytest.mark.asyncio
async def test_grade_with_missing_repo_dir_degrades(tmp_path, monkeypatch):
    """`grade_with_simplejudge` must not hard-fail when `repo_dir` is absent.

    workflow.yaml §"ORS auto-rubric reproducibility" specifies that the
    grader degrades to scoring against an effectively empty submission
    when the upstream pipeline has not populated `repro_sandbox/`. The
    original bug: the function returned `{"error": "repo_dir not a
    directory: ..."}` which the orchestrator surfaced as an exception,
    skipping the report entirely.
    """
    from _paperbench_bridge import GradedTaskNode

    rubric_path = _write_rubric(tmp_path, [_leaf("trivial")])
    missing_repo = tmp_path / "no_such_sandbox"
    assert not missing_repo.exists()

    captured_repo: list[Path] = []
    captured_is_dir: list[bool] = []

    def _fake_graded_root() -> GradedTaskNode:
        leaf = GradedTaskNode(
            score=0.0, valid_score=True, explanation="empty submission",
            id="leaf", requirements="trivial", weight=1, sub_tasks=(),
            task_category="Code Development",
        )
        return GradedTaskNode(
            score=0.0, valid_score=True, explanation="root",
            id="root", requirements="root", weight=1, sub_tasks=(leaf,),
        )

    async def fake_grade_once(pb_taskroot, paper_md, repo_dir, reproduce_log, judge_model):
        captured_repo.append(Path(repo_dir))
        # Snapshot existence at call time — caller may clean up the tempdir
        # in a finally block before the assertion runs.
        captured_is_dir.append(Path(repo_dir).is_dir())
        return _fake_graded_root()

    async def fake_negative_control(pb_taskroot, paper_md, judge_model):
        return {"empty": 0.0, "boilerplate": 0.0, "passed": True}

    monkeypatch.setattr(S, "_grade_once", fake_grade_once)
    monkeypatch.setattr(S, "_negative_control_check", fake_negative_control)

    res = await S.grade_with_simplejudge(
        rubric_path=str(rubric_path),
        repo_dir=str(missing_repo),
        paper_text="paper",
        judge_model="test/m",
        n_runs=1,
        skip_negative_control=True,
    )

    assert "error" not in res, f"grade hard-failed instead of degrading: {res}"
    assert res.get("degraded") is True
    assert "degraded_reason" in res and str(missing_repo) in res["degraded_reason"]
    assert "ors_score" in res and "leaf_grades" in res
    # _grade_once must have been called against a real (temp) directory so
    # SimpleJudge's filesystem walk doesn't crash. Check the snapshot taken
    # during the call (the tempdir is cleaned up in a finally block).
    assert captured_repo, "_grade_once was not invoked"
    assert captured_is_dir[0], \
        f"_grade_once received non-directory: {captured_repo[0]}"
    assert captured_repo[0] != missing_repo, \
        "function should have substituted a tempdir, not used the missing path"


@pytest.mark.asyncio
@pytest.mark.skipif(not _LIVE_LLM, reason="set ARI_RUN_LIVE_LLM_TESTS=1 + OPENAI_API_KEY to opt in")
async def test_grade_n_runs_averages(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    rubric_path = _write_rubric(tmp_path, [_leaf("trivial leaf")])
    res = await S.grade_with_simplejudge(
        rubric_path=str(rubric_path), repo_dir=str(repo),
        paper_text="p", judge_model=_JUDGE_MODEL, n_runs=3,
        skip_negative_control=True,
    )
    assert res["n_runs"] == 3
    for lg in res["leaf_grades"]:
        assert lg["n_runs"] == 3
