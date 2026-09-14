"""Phase 1 + Phase 2 round-trip tests (Step 4 DoD)."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for p in (str(ROOT), str(SRC)):
    if p not in sys.path:
        sys.path.insert(0, p)

from rubric_contract import bind_rubric_digest  # noqa: E402
from contracts import GradeReportV1, bytes_digest  # noqa: E402

# Load this skill's server.py explicitly under a unique name to avoid
# clashing with other ari-skill-*/src/server.py modules pytest may have
# already imported.
_spec = importlib.util.spec_from_file_location("paper_re_server", SRC / "server.py")
S = importlib.util.module_from_spec(_spec)
sys.modules["paper_re_server"] = S
_spec.loader.exec_module(S)


def _envelope(leaves: list[dict], paper_text: str = "paper") -> dict:
    import hashlib

    document = {
        "version": "3",
        "paper_sha256": hashlib.sha256(paper_text.encode()).hexdigest(),
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
    return bind_rubric_digest(document, legacy=True)


def _leaf(text: str) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "requirements": text,
        "weight": 1,
        "sub_tasks": [],
        "task_category": "Code Development",
        "finegrained_task_category": "Method Implementation",
    }


def _write_rubric(
    tmp_path: Path, leaves: list[dict], paper_text: str = "paper"
) -> Path:
    path = tmp_path / "rubric.json"
    path.write_text(json.dumps(_envelope(leaves, paper_text)))
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
        network_policy="inherit",
    )
    assert res["executed"] is True
    assert res["exit_code"] == 0
    assert "reproduce.log" in res["artifacts"]
    assert any(a.endswith("summary.txt") for a in res["artifacts"])
    assert res["missing"] == []
    log_text = Path(res["log_path"]).read_text()
    assert "METRIC: 0.42" in log_text
    assert not (repo / "reproduce.log").exists()
    assert not (repo / "results").exists()


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
        network_policy="inherit",
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
        network_policy="inherit",
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
        network_policy="inherit",
    )
    assert "results/summary.txt" in res["missing"]


@pytest.mark.asyncio
async def test_run_reproduce_reuses_verified_success_idempotently(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    script = repo / "reproduce.sh"
    script.write_text(
        "#!/bin/bash\nmkdir -p results\necho stable > results/summary.txt\n"
    )
    script.chmod(0o755)
    rubric_path = _write_rubric(tmp_path, [_leaf("idempotent")])

    first = await S.run_reproduce(
        rubric_path=str(rubric_path),
        repo_dir=str(repo),
        sandbox_kind="local",
        timeout_global_sec=30,
        network_policy="inherit",
    )
    second = await S.run_reproduce(
        rubric_path=str(rubric_path),
        repo_dir=str(repo),
        sandbox_kind="local",
        timeout_global_sec=30,
        network_policy="inherit",
    )

    assert first["attempt_status"] == "succeeded"
    assert second["idempotent_replay"] is True
    assert second["attempt_id"] == first["attempt_id"]
    assert second["run_digest"] == first["run_digest"]
    assert not (repo / "results").exists()


@pytest.mark.asyncio
async def test_run_reproduce_links_retries_after_failure(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    script = repo / "reproduce.sh"
    script.write_text("#!/bin/bash\necho failed >&2\nexit 7\n")
    script.chmod(0o755)
    rubric_path = _write_rubric(tmp_path, [_leaf("retry")])

    first = await S.run_reproduce(
        rubric_path=str(rubric_path),
        repo_dir=str(repo),
        sandbox_kind="local",
        timeout_global_sec=30,
        network_policy="inherit",
    )
    second = await S.run_reproduce(
        rubric_path=str(rubric_path),
        repo_dir=str(repo),
        sandbox_kind="local",
        timeout_global_sec=30,
        network_policy="inherit",
    )

    run = json.loads(Path(second["run_record_path"]).read_text())
    assert first["attempt_status"] == "failed"
    assert second["attempt_status"] == "failed"
    assert second["idempotent_replay"] is False
    assert [attempt["ordinal"] for attempt in run["attempts"]] == [1, 2]
    assert run["attempts"][1]["parent_attempt_id"] == first["attempt_id"]


@pytest.mark.asyncio
async def test_run_reproduce_default_network_policy_fails_closed(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    script = repo / "reproduce.sh"
    script.write_text("#!/bin/bash\necho should-not-run\n")
    script.chmod(0o755)

    result = await S.run_reproduce(
        rubric_path="",
        repo_dir=str(repo),
        sandbox_kind="local",
        timeout_global_sec=30,
    )

    assert result["executed"] is False
    assert "cannot prove network denial" in result["error"]


@pytest.mark.asyncio
async def test_run_reproduce_rejects_tampered_success(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    script = repo / "reproduce.sh"
    script.write_text(
        "#!/bin/bash\nmkdir -p results\necho stable > results/summary.txt\n"
    )
    script.chmod(0o755)
    rubric_path = _write_rubric(tmp_path, [_leaf("tamper")])
    first = await S.run_reproduce(
        rubric_path=str(rubric_path),
        repo_dir=str(repo),
        sandbox_kind="local",
        timeout_global_sec=30,
        network_policy="inherit",
    )
    (Path(first["executed_repo_dir"]) / "results" / "summary.txt").write_text(
        "tampered\n"
    )

    second = await S.run_reproduce(
        rubric_path=str(rubric_path),
        repo_dir=str(repo),
        sandbox_kind="local",
        timeout_global_sec=30,
        network_policy="inherit",
    )

    assert second["executed"] is False
    assert "differs from its digest" in second["error"]


# ── grade_with_simplejudge ──
#
# These hit the real upstream PaperBench SimpleJudge → OpenAI. Skipped by
# default — set ``ARI_RUN_LIVE_LLM_TESTS=1`` to opt in. There is no local
# fallback (per spec); the upstream completer enforces a fixed list of
# supported models, so we use ``gpt-4o-2024-08-06`` as the default test
# model (PaperBench's known-good).

_LIVE_LLM = (
    os.environ.get("ARI_RUN_LIVE_LLM_TESTS", "0") == "1"
    and bool(os.environ.get("OPENAI_API_KEY"))
)
_JUDGE_MODEL = os.environ.get("ARI_TEST_JUDGE_MODEL", "gpt-4o-2024-08-06")


@pytest.mark.asyncio
@pytest.mark.skipif(not _LIVE_LLM, reason="set ARI_RUN_LIVE_LLM_TESTS=1 + OPENAI_API_KEY to opt in")
async def test_grade_low_signal_verified_repo(tmp_path):
    rubric_path = _write_rubric(tmp_path, [
        _leaf("Implement the MaskNetwork architecture for selfish-mining environment."),
        _leaf("Run Experiment II producing pre-refinement and post-refinement metrics."),
    ], paper_text="paper text")
    repo, _ = await _make_verified_repo(tmp_path, rubric_path)
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
    rubric_path = _write_rubric(tmp_path, [_leaf("Implement MaskNetwork outputs zero for critical states.")])
    repo, _ = await _make_verified_repo(tmp_path, rubric_path)
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


async def _make_verified_repo(tmp_path: Path, rubric_path: Path) -> tuple[Path, dict]:
    repo = tmp_path / "verified-repo"
    repo.mkdir()
    script = repo / "reproduce.sh"
    script.write_text(
        "#!/bin/bash\nmkdir -p results\necho result > results/summary.txt\n"
    )
    script.chmod(0o755)
    result = await S.run_reproduce(
        rubric_path=str(rubric_path),
        repo_dir=str(repo),
        sandbox_kind="local",
        timeout_global_sec=30,
        network_policy="inherit",
    )
    assert result["attempt_status"] == "succeeded"
    return repo, result


def _graded_root(*, score: float = 1.0, valid: bool = True, response: str = "raw"):
    from _paperbench_bridge import GradedTaskNode

    leaf = GradedTaskNode(
        score=score,
        valid_score=valid,
        explanation="evidence-backed decision",
        id="leaf",
        requirements="trivial",
        weight=1,
        sub_tasks=(),
        task_category="Code Development",
        judge_metadata={"full_judge_response": response, "token_usage": None},
    )
    return GradedTaskNode(
        score=score,
        valid_score=valid,
        explanation="root",
        id="root",
        requirements="root",
        weight=1,
        sub_tasks=(leaf,),
    )


def _write_fake_call(trace_dir: Path | None, *, error: str | None = None) -> None:
    assert trace_dir is not None
    trace_dir.mkdir(parents=True, exist_ok=True)
    (trace_dir / "call.json").write_text(
        json.dumps(
            {
                "schema_version": "ari.model-call-trace/v1",
                "request": {"messages": [{"role": "user", "content": "prompt"}]},
                "response": None if error else {"content": "raw"},
                "error": error,
            }
        )
    )


@pytest.mark.asyncio
async def test_grade_missing_reproduction_emits_failed_report_without_score(tmp_path):
    rubric_path = _write_rubric(tmp_path, [_leaf("trivial")])
    missing_repo = tmp_path / "missing"

    result = await S.grade_with_simplejudge(
        rubric_path=str(rubric_path),
        repo_dir=str(missing_repo),
        paper_text="paper",
        judge_model="other/judge",
        n_runs=1,
    )

    assert result["grade_status"] == "failed"
    assert "ors_score" not in result
    assert result["n_runs_completed"] == 0
    report = GradeReportV1.model_validate_json(
        Path(result["grade_report_path"]).read_text()
    )
    assert report.reproduction_status == "unavailable"
    assert report.ors_score is None


@pytest.mark.asyncio
async def test_grade_refuses_unverified_directory_even_with_log(tmp_path, monkeypatch):
    rubric_path = _write_rubric(tmp_path, [_leaf("trivial")])
    repo = tmp_path / "unverified"
    repo.mkdir()
    (repo / "reproduce.sh").write_text("#!/bin/bash\necho ok\n")
    (repo / "reproduce.log").write_text("ok\n")
    called = False

    async def fake_grade_once(*args, **kwargs):
        nonlocal called
        called = True
        return _graded_root()

    monkeypatch.setattr(S, "_grade_once", fake_grade_once)
    result = await S.grade_with_simplejudge(
        rubric_path=str(rubric_path),
        repo_dir=str(repo),
        paper_text="paper",
        judge_model="other/judge",
    )

    assert result["grade_status"] == "failed"
    assert "no verified ReproductionRunV1" in result["error"]
    assert called is False


@pytest.mark.asyncio
async def test_grade_binds_run_raw_calls_and_leaf_responses(tmp_path, monkeypatch):
    rubric_path = _write_rubric(tmp_path, [_leaf("trivial")])
    repo, reproduction = await _make_verified_repo(tmp_path, rubric_path)
    captured_code_only: list[bool] = []

    async def fake_grade_once(
        pb_taskroot,
        paper_md,
        repo_dir,
        reproduce_log,
        judge_model,
        code_only=False,
        trace_dir=None,
    ):
        captured_code_only.append(code_only)
        _write_fake_call(trace_dir)
        return _graded_root(response="verbatim raw judge response")

    async def fake_negative_control(
        pb_taskroot,
        paper_md,
        judge_model,
        code_only=False,
        trace_dir=None,
    ):
        _write_fake_call(trace_dir / "empty")
        return {"empty": 0.0, "boilerplate": 0.0, "passed": True}

    monkeypatch.setattr(S, "_grade_once", fake_grade_once)
    monkeypatch.setattr(S, "_negative_control_check", fake_negative_control)
    result = await S.grade_with_simplejudge(
        rubric_path=str(rubric_path),
        repo_dir=str(repo),
        paper_text="paper",
        judge_model="other/judge",
        n_runs=2,
        code_only=True,
    )

    assert result["grade_status"] == "valid"
    assert result["reproduction_run_digest"] == reproduction["run_digest"]
    assert result["independence_status"] == "independent-model"
    assert captured_code_only == [True, True]
    assert len(result["call_artifacts"]) == 3
    report = GradeReportV1.model_validate_json(
        Path(result["grade_report_path"]).read_text()
    )
    assert report.n_runs_completed == 2
    assert report.leaves[0].run_scores == (1.0, 1.0)
    raw_artifact = report.leaves[0].raw_response_artifacts[0]
    raw_path = repo / raw_artifact.relative_path
    assert bytes_digest(raw_path.read_bytes()) == raw_artifact.digest
    assert "verbatim raw judge response" in raw_path.read_text()


@pytest.mark.asyncio
async def test_grade_judge_failure_has_no_scientific_score(tmp_path, monkeypatch):
    rubric_path = _write_rubric(tmp_path, [_leaf("trivial")])
    repo, _ = await _make_verified_repo(tmp_path, rubric_path)

    async def failing_grade(*args, trace_dir=None, **kwargs):
        _write_fake_call(trace_dir, error="provider failed")
        raise RuntimeError("provider failed")

    monkeypatch.setattr(S, "_grade_once", failing_grade)
    result = await S.grade_with_simplejudge(
        rubric_path=str(rubric_path),
        repo_dir=str(repo),
        paper_text="paper",
        judge_model="other/judge",
    )

    assert result["grade_status"] == "failed"
    assert "ors_score" not in result
    assert result["n_runs_completed"] == 0
    assert len(result["call_artifacts"]) == 1


@pytest.mark.asyncio
async def test_same_generator_and_judge_is_reported_not_independent(
    tmp_path, monkeypatch
):
    rubric_path = _write_rubric(tmp_path, [_leaf("trivial")])
    repo, _ = await _make_verified_repo(tmp_path, rubric_path)

    async def fake_grade(*args, trace_dir=None, **kwargs):
        _write_fake_call(trace_dir)
        return _graded_root()

    async def passed_control(*args, **kwargs):
        return {"empty": 0.0, "boilerplate": 0.0, "passed": True}

    monkeypatch.setattr(S, "_grade_once", fake_grade)
    monkeypatch.setattr(S, "_negative_control_check", passed_control)
    result = await S.grade_with_simplejudge(
        rubric_path=str(rubric_path),
        repo_dir=str(repo),
        paper_text="paper",
        judge_model="test/m",
    )

    assert result["grade_status"] == "valid"
    assert result["independence_status"] == "not-independent"


@pytest.mark.asyncio
async def test_grade_negative_control_error_has_no_score(tmp_path, monkeypatch):
    rubric_path = _write_rubric(tmp_path, [_leaf("trivial")])
    repo, _ = await _make_verified_repo(tmp_path, rubric_path)

    async def fake_grade(*args, trace_dir=None, **kwargs):
        _write_fake_call(trace_dir)
        return _graded_root()

    async def failing_control(*args, **kwargs):
        raise RuntimeError("control provider failed")

    monkeypatch.setattr(S, "_grade_once", fake_grade)
    monkeypatch.setattr(S, "_negative_control_check", failing_control)
    result = await S.grade_with_simplejudge(
        rubric_path=str(rubric_path),
        repo_dir=str(repo),
        paper_text="paper",
        judge_model="other/judge",
    )

    assert result["grade_status"] == "failed"
    assert "ors_score" not in result
    assert result["n_runs_completed"] == 1
    assert "negative-control grading failed" in result["error"]


@pytest.mark.asyncio
async def test_grade_failed_negative_control_marks_score_invalid(tmp_path, monkeypatch):
    rubric_path = _write_rubric(tmp_path, [_leaf("trivial")])
    repo, _ = await _make_verified_repo(tmp_path, rubric_path)

    async def fake_grade(*args, trace_dir=None, **kwargs):
        _write_fake_call(trace_dir)
        return _graded_root()

    async def failed_control(*args, **kwargs):
        return {"empty": 0.2, "boilerplate": 0.0, "passed": False}

    monkeypatch.setattr(S, "_grade_once", fake_grade)
    monkeypatch.setattr(S, "_negative_control_check", failed_control)
    result = await S.grade_with_simplejudge(
        rubric_path=str(rubric_path),
        repo_dir=str(repo),
        paper_text="paper",
        judge_model="other/judge",
    )

    assert result["grade_status"] == "invalid-negative-control"
    assert result["ors_score"] == 1.0
    assert result["negative_control_check"]["passed"] is False


@pytest.mark.asyncio
@pytest.mark.skipif(not _LIVE_LLM, reason="set ARI_RUN_LIVE_LLM_TESTS=1 + OPENAI_API_KEY to opt in")
async def test_grade_n_runs_averages(tmp_path):
    rubric_path = _write_rubric(tmp_path, [_leaf("trivial leaf")], paper_text="p")
    repo, _ = await _make_verified_repo(tmp_path, rubric_path)
    res = await S.grade_with_simplejudge(
        rubric_path=str(rubric_path), repo_dir=str(repo),
        paper_text="p", judge_model=_JUDGE_MODEL, n_runs=3,
        skip_negative_control=True,
    )
    assert res["n_runs"] == 3
    for lg in res["leaf_grades"]:
        assert lg["n_runs"] == 3
