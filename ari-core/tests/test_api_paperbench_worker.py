"""Unit tests for ari/viz/api_paperbench_worker.py — Wizard → skill wiring.

The worker is the piece that turns "Launch all" into real PaperBench skill
invocations. We exercise the full state machine (queued → running →
completed/failed) with a stub MCPClient so the test stays hermetic —
no subprocesses, no LLM calls, no SLURM. The stub also records every
``call_tool`` invocation so the test can pin down which Wizard config
fields actually reach the four PaperBench tools.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ari.viz import api_paperbench as P
from ari.viz import api_paperbench_worker as W


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("ARI_PAPER_REGISTRY_DIR", str(tmp_path / "registry"))
    # Suppress the auto-spawn inside _api_launch_run so it doesn't race with
    # the explicit, stub-driven start_paperbench_job calls in each test.
    # The env-var gate only fires when client_factory is None, so passing a
    # stub factory below still drives the pipeline.
    monkeypatch.setenv("ARI_PAPERBENCH_WORKER_DISABLED", "1")
    P._JOBS.clear()
    yield


class _StubClient:
    """Records ``call_tool`` invocations and returns canned MCP-style envelopes.

    The MCPClient contract is ``{"result": "<json>"}`` on success or
    ``{"error": "..."}`` on transport failure; the worker decodes the
    inner JSON via :func:`api_paperbench_worker._parse_result`.
    """

    def __init__(self, responses: dict[str, dict]):
        self.responses = responses
        self.calls: list[tuple[str, dict]] = []

    def call_tool(self, tool: str, args: dict) -> dict:
        self.calls.append((tool, args))
        payload = self.responses.get(tool, {"ok": True})
        return {"result": json.dumps(payload)}


def _register_paper_with_pdf(tmp_path: Path, paper_id: str) -> Path:
    """Create a registry entry whose paper.pdf exists on disk."""
    src = tmp_path / "src.pdf"
    src.write_bytes(b"%PDF-1.4\nfake\n")
    P._api_import_paper({
        "source_type": "upload",
        "source": paper_id,
        "title": "Test paper",
        "license": "CC BY 4.0",
        "paper_id": paper_id,
        "pdf_path": str(src),
    })
    return P._papers_dir() / paper_id


def test_worker_drives_four_stages_and_marks_completed(tmp_path):
    paper_dir = _register_paper_with_pdf(tmp_path, "wp1")
    stub = _StubClient({
        "generate_rubric": {
            "rubric_path": str(paper_dir / "runs" / "x" / "rubric.json"),
            "rubric_sha256": "abc",
            "leaves_count": 12,
        },
        "build_reproduce_sh": {"populated": True, "files": ["reproduce.sh"]},
        "run_reproduce": {"executed": True, "exit_code": 0},
        "grade_with_simplejudge": {
            "ors_score": 0.73,
            "leaf_grades": [{"id": "l1", "passed": True}],
            "negative_control_check": {"empty": 0.05, "boilerplate": 0.1, "passed": True},
        },
    })

    r = P._api_launch_run({
        "paper_ids": ["wp1"],
        "rubric_config": {"model": "gemini/gemini-2.5-pro", "two_stage": True,
                          "target_leaf_count": 200, "temperature": 0.1},
        "reproduce_config": {"model": "gpt-5-mini", "time_limit_sec": 7200,
                             "iterative_agent": True, "sandbox_kind": "slurm",
                             "partition": "small", "gpus_per_task": 1,
                             "gpu_type": "v100", "exclusive": True,
                             "extra_sbatch_args": ["--account=projX"]},
        "judge_config": {"model": "gpt-5-mini", "n_runs": 3,
                         "skip_negative_control": False},
    })
    jid = r["job_ids"][0]

    # Replace MCPClient.call_tool by replaying our stub through start_paperbench_job
    # — _api_launch_run already spawned a thread using the real factory, so
    # cancel it implicitly by overriding the singleton and re-running the
    # pipeline synchronously. The _JOBS state from the original thread will
    # also flip but the assertion below tolerates either ordering.
    t = W.start_paperbench_job(jid, paper_dir,
                               configs=P._JOBS[jid]["configs"],
                               client_factory=lambda: stub)
    assert t is not None
    t.join(timeout=30)
    assert not t.is_alive(), "worker thread did not terminate in time"

    snap = P._api_run_status(jid)
    assert snap["status"] == "completed", snap
    assert snap["current_stage"] == "grade"
    assert snap["progress"] == 1.0

    # Wizard fields must reach the right tool with the right kwargs.
    calls = {t: a for t, a in stub.calls}
    assert calls["generate_rubric"]["model"] == "gemini/gemini-2.5-pro"
    assert calls["generate_rubric"]["target_leaf_count"] == 200
    assert calls["generate_rubric"]["temperature"] == 0.1
    assert calls["build_reproduce_sh"]["sandbox_kind"] == "slurm"
    assert calls["build_reproduce_sh"]["iterative_agent"] is True
    assert calls["run_reproduce"]["partition"] == "small"
    assert calls["run_reproduce"]["gpu_type"] == "v100"
    assert calls["run_reproduce"]["exclusive"] is True
    assert calls["run_reproduce"]["extra_sbatch_args"] == ["--account=projX"]
    # judge_config.model → judge_model (name translation lives in worker)
    assert calls["grade_with_simplejudge"]["judge_model"] == "gpt-5-mini"
    assert calls["grade_with_simplejudge"]["n_runs"] == 3

    # ResultsView (frontend) reads these keys directly off the job snapshot.
    results = P._api_run_results(jid)
    assert results["ors_score"] == 0.73
    assert results["leaves"] == [{"id": "l1", "passed": True}]
    assert results["negative_control"]["passed"] is True


def test_worker_aborts_when_rubric_stage_errors(tmp_path):
    paper_dir = _register_paper_with_pdf(tmp_path, "wp2")
    stub = _StubClient({
        "generate_rubric": {"error": "LLM quota exceeded"},
    })
    r = P._api_launch_run({"paper_ids": ["wp2"], "reproduce_config": {}})
    jid = r["job_ids"][0]
    t = W.start_paperbench_job(jid, paper_dir,
                               configs=P._JOBS[jid]["configs"],
                               client_factory=lambda: stub)
    t.join(timeout=10)

    snap = P._api_run_status(jid)
    assert snap["status"] == "failed"
    assert snap["current_stage"] == "rubric"
    assert "LLM quota exceeded" in snap["error"]
    # No downstream stages must have been attempted.
    assert [c[0] for c in stub.calls] == ["generate_rubric"]


def test_worker_treats_phase1_failure_as_degraded_not_fatal(tmp_path):
    """run_reproduce failure → keep going so SimpleJudge can score the
    empty/partial sandbox + negative control. Mirrors workflow.yaml's
    "ORS auto-rubric reproducibility" degraded path."""
    paper_dir = _register_paper_with_pdf(tmp_path, "wp3")
    stub = _StubClient({
        "generate_rubric": {"rubric_sha256": "x", "leaves_count": 5},
        "build_reproduce_sh": {"populated": True},
        "run_reproduce": {"error": "sbatch unavailable"},
        "grade_with_simplejudge": {"ors_score": 0.0, "leaf_grades": []},
    })
    r = P._api_launch_run({"paper_ids": ["wp3"], "reproduce_config": {}})
    jid = r["job_ids"][0]
    t = W.start_paperbench_job(jid, paper_dir,
                               configs=P._JOBS[jid]["configs"],
                               client_factory=lambda: stub)
    t.join(timeout=10)

    snap = P._api_run_status(jid)
    assert snap["status"] == "completed"
    # All four tools were still invoked.
    assert [c[0] for c in stub.calls] == [
        "generate_rubric", "build_reproduce_sh",
        "run_reproduce", "grade_with_simplejudge",
    ]


def test_worker_fails_fast_when_pdf_missing(tmp_path):
    # Register the entry but don't supply a PDF.
    P._api_import_paper({
        "source_type": "arxiv", "source": "wp4", "title": "no-pdf",
        "license": "MIT", "paper_id": "wp4",
    })
    r = P._api_launch_run({"paper_ids": ["wp4"], "reproduce_config": {}})
    jid = r["job_ids"][0]
    paper_dir = P._papers_dir() / "wp4"
    t = W.start_paperbench_job(jid, paper_dir,
                               configs=P._JOBS[jid]["configs"],
                               client_factory=lambda: pytest.fail(
                                   "should not need the client when PDF missing"
                               ))
    t.join(timeout=5)

    snap = P._api_run_status(jid)
    assert snap["status"] == "failed"
    assert "paper.pdf missing" in snap["error"]


def test_start_paperbench_job_honours_worker_disabled_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ARI_PAPERBENCH_WORKER_DISABLED", "1")
    paper_dir = _register_paper_with_pdf(tmp_path, "wp5")
    # The env-var gate only suppresses the default-factory path (which would
    # spawn real skill subprocesses); explicit factories always run so tests
    # can drive stubbed pipelines.
    t = W.start_paperbench_job("jobX", paper_dir, configs={})
    assert t is None
