"""Scoring a node from a pinned problem instead of an untracked harness tree.

THE PROPERTY THIS FILE EXISTS FOR is the distinction between a candidate that
was WRONG and a candidate that was SLOW. The registered property is
``performance-regression``, so the harness's verdict is "did it regress against
the frozen reference" -- and the frozen reference is a COMPETENT kernel. Reading
that verdict as node validity collapsed the search the first time it was wired:
the seeded naive kernel measures about 0.008-0.02x of the reference, so every
case read invalid, every geomean was 0.0, and every node in the tree ranked 0.0
until one happened to beat a tuned kernel outright. The run still produced a
tree; it just had no gradient in it, and nothing said so.

So validity here means CORRECTNESS, the ratio is reported whatever it is, and
the regression verdict travels beside the numbers where nothing ranks on it.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ari.assurance.native_perf_common import (
    NativePerfReportV1, PerfBuildError, PerfCaseResultV1, PerfInfrastructureError,
    PerfRepetitionV1, measurement_placement)
from ari.evaluator import assurance_measure as am
from ari.evaluator.deterministic_evaluator import DeterministicEvaluator

PROBLEM = "gemm-dense-fp64/v1@2026q3"


@pytest.fixture(autouse=True)
def _named_problem(monkeypatch):
    monkeypatch.setenv(am.PROBLEM_ENV, PROBLEM)


def _rep(index=0, *, correct=True, speedup=0.02):
    return PerfRepetitionV1(
        index=index, input_seed=index, credited_seconds=50.0,
        reference_seconds=50.0 * speedup, speedup=speedup, correct=correct,
        max_rel_error=0.5 if correct else 9e11)


def _report(cases, *, verdict="fail"):
    return NativePerfReportV1.create(
        problem_id="gemm-dense-fp64", problem_revision=PROBLEM,
        problem_digest="sha256:" + "1" * 64, family="gemm", tier="screen",
        verdict=verdict, case_results=tuple(cases), regression_threshold=0.95,
        default_toolchain={"resolved_path": "/usr/bin/cc"},
        candidate_toolchain={"resolved_path": "/usr/bin/cc", "status": "default"},
        crossed_compiler_boundary=False, base_flags=("-O3",),
        reference_flags=("-ffast-math",), accepted_flags=("-O2",),
        rejected_flags=("-lblas",),
        environment={"variables": {}, "sha256": "sha256:" + "0" * 64},
        dataset_revision="native-perf-gemm-cases/v1@smoke",
        dataset_sha256="sha256:" + "0" * 64,
        placement=measurement_placement())


def _case(case_id, *, verdict, correct, speedup):
    return PerfCaseResultV1(
        case_id=case_id, verdict=verdict, detail="d", speedup=speedup,
        relative_spread=0.01, repetitions=(_rep(correct=correct, speedup=speedup),))


# --- wrong vs slow, which is the whole point -----------------------------------

def test_a_correct_but_slow_candidate_is_valid_and_keeps_its_ratio():
    """The gradient BFTS climbs. Against a competent denominator almost every
    early candidate is slower than the reference; if that read as invalid the
    whole tree would rank 0.0 and the search would have nothing to follow."""
    report = _report([_case("c1", verdict="fail", correct=True, speedup=0.02)])
    result = am.report_to_measurement(report)
    assert result["families"]["c1"]["valid"] is True
    assert result["families"]["c1"]["speedup"] == pytest.approx(0.02)
    assert result["evaluation_status"] == "valid"
    # And the harness's own answer is still recorded -- not ranked on, and not
    # in the family's scalars either, because those are rendered into the
    # child's prompt and would change the treatment.
    assert "regression_verdict" not in result["families"]["c1"]
    assert result["families"]["c1"]["diagnostics"][0]["regression_verdict"] == "fail"
    assert result["regression_verdict"] == "fail"


def test_a_wrong_candidate_is_invalid_however_fast_it_was():
    report = _report([_case("c1", verdict="fail", correct=False, speedup=900.0)])
    result = am.report_to_measurement(report)
    assert result["families"]["c1"]["valid"] is False
    assert result["evaluation_status"] == "candidate_invalid"


def test_the_two_reach_different_ranks_through_the_real_scorer():
    """End of the wire: a slow-but-correct kernel must outrank a fast wrong one."""
    evaluator = DeterministicEvaluator()
    slow = evaluator.score_result(am.report_to_measurement(
        _report([_case("c1", verdict="fail", correct=True, speedup=0.02)])))
    wrong = evaluator.score_result(am.report_to_measurement(
        _report([_case("c1", verdict="fail", correct=False, speedup=900.0)])))
    assert slow["metrics"]["_scientific_score"] == pytest.approx(0.02)
    assert wrong["metrics"]["_scientific_score"] == 0.0
    assert slow["metrics"]["_scientific_score"] > wrong["metrics"]["_scientific_score"]


def test_one_unresolved_case_among_correct_ones_is_not_silently_dropped():
    """A case with no completed repetition zeroes the node rather than letting
    the survivors carry it -- geomean's positivity filter would have hidden it."""
    good = _case("c1", verdict="pass", correct=True, speedup=1.5)
    empty = PerfCaseResultV1(case_id="c2", verdict="inconclusive", detail="none",
                             speedup=0.0, relative_spread=None, repetitions=())
    result = am.report_to_measurement(_report([good, empty]))
    assert result["families"]["c2"]["valid"] is False
    assert result["evaluation_status"] == "measurement_invalid"
    scored = DeterministicEvaluator().score_result(result)
    assert scored["metrics"]["_scientific_score"] == 0.0


# --- the two error classes, which item 2 made load-bearing ----------------------

def test_a_candidate_that_did_not_build_is_scored_not_raised(monkeypatch, tmp_path):
    """A build failure is a fact about the candidate, so it ranks 0.0."""
    work = tmp_path / "node"
    am.seed_work_dir(work)

    def _boom(*_a, **_k):
        raise PerfBuildError("candidate failed to compile: expected ';'")

    monkeypatch.setattr(am, "verify_performance", _boom)
    result = am.measure(str(work))
    assert result["compile_ok"] is False
    assert result["families"] == {}
    scored = DeterministicEvaluator().score_result(result)
    assert scored["metrics"]["_scientific_score"] == 0.0
    assert scored["valid"] is False


def test_an_instrument_failure_is_raised_so_the_node_goes_unranked(monkeypatch,
                                                                   tmp_path):
    """Which is what makes it reach evaluate_sync's unranked path instead of
    being recorded as a kernel that ran and lost."""
    work = tmp_path / "node"
    am.seed_work_dir(work)

    def _boom(*_a, **_k):
        raise PerfInfrastructureError("case set pin no longer matches")

    monkeypatch.setattr(am, "verify_performance", _boom)
    with pytest.raises(PerfInfrastructureError):
        am.measure(str(work))

    evaluator = DeterministicEvaluator(measure_fn=lambda _w: _boom())
    out = evaluator.evaluate_sync("g", [], "s")
    assert out["evaluation_status"] == "infrastructure_error"
    assert out["metrics"] == {}
    assert "scientific_score" not in out


def test_an_unnamed_problem_refuses_rather_than_defaulting(monkeypatch):
    """ARI_TASK unset used to fall through to SpMM: a typo scored a DIFFERENT
    benchmark and reported it under the requested name."""
    monkeypatch.delenv(am.PROBLEM_ENV, raising=False)
    with pytest.raises(PerfInfrastructureError, match="no question to measure"):
        am.problem_revision()


def test_a_work_dir_that_was_never_seeded_is_an_instrument_failure(tmp_path):
    """The seed puts the scored input there, so its absence is not the
    candidate's doing and must not be scored as a build failure."""
    empty = tmp_path / "unseeded"
    empty.mkdir()
    with pytest.raises(PerfInfrastructureError, match="never seeded"):
        am.measure(str(empty))


# --- seeding -------------------------------------------------------------------

def test_seeding_never_overwrites_an_inherited_candidate(tmp_path):
    """A child's work dir is a copy of its parent's and the parent's candidate IS
    the handoff. Re-seeding would restart every node from the naive seed while
    the run still reported a tree."""
    work = tmp_path / "node"
    first = am.seed_work_dir(work)
    assert first["already_seeded"] is False

    candidate = work / "candidate_gemm.c"
    candidate.write_text("/* the parent's improvement */\n")
    second = am.seed_work_dir(work)
    assert second["already_seeded"] is True
    assert second["seeded"] == []
    assert candidate.read_text() == "/* the parent's improvement */\n"


def test_the_seeded_node_gets_the_question_and_not_the_denominator(tmp_path):
    work = tmp_path / "node"
    record = am.seed_work_dir(work)
    written = {item["name"] for item in record["seeded"]}
    assert "problem_statement.md" in written
    assert "Make `gemm`" in (work / "problem_statement.md").read_text()
    assert not (work / "reference_gemm.c").exists()
    assert record["withheld"] == ["reference_gemm.c"]


def test_the_compiler_declaration_is_a_scored_input(tmp_path):
    """The prototype left it out of that list, so a node that changed ONLY its
    compiler read as an unchanged copy to the sterility gate while moving the
    score across a toolchain boundary."""
    from ari.assurance.problems import load_problem

    assert am.CANDIDATE_COMPILER_FILE in load_problem(PROBLEM).definition.score_inputs
    assert am.CANDIDATE_FLAGS_FILE in load_problem(PROBLEM).definition.score_inputs


def test_the_sterility_gate_reads_the_problems_score_inputs(monkeypatch):
    from ari.cli.bfts_loop import _score_inputs_for_task

    _score_inputs_for_task.__dict__.pop("_cache", None)
    assert _score_inputs_for_task() == (
        "candidate_gemm.c", am.CANDIDATE_FLAGS_FILE, am.CANDIDATE_COMPILER_FILE)


def test_a_declared_toolchain_is_read_from_the_work_dir(tmp_path):
    work = tmp_path / "node"
    am.seed_work_dir(work)
    assert am._declared_text(work, am.CANDIDATE_FLAGS_FILE) is None
    (work / am.CANDIDATE_FLAGS_FILE).write_text("  -O2 -ffast-math \n")
    assert am._declared_text(work, am.CANDIDATE_FLAGS_FILE) == "-O2 -ffast-math"
    # Junk does not break the measurement; it just is not honoured, and the
    # instrument's screen decides what is used either way.
    (work / am.CANDIDATE_FLAGS_FILE).write_bytes(b"\xff\xfe\x00binary")
    assert am._declared_text(work, am.CANDIDATE_FLAGS_FILE) is None


def test_the_evaluator_reaches_the_problem_path_only_when_one_is_named(monkeypatch):
    """The prototype registry is still there for a run configured the old way,
    and must not be consulted when a problem IS named."""
    import ari.evaluator.deterministic_evaluator as de

    called = {}
    monkeypatch.setattr(am, "measure", lambda wd: called.setdefault("problem", wd))
    monkeypatch.setattr(de, "_harness",
                        lambda: called.setdefault("registry", True))
    de._default_measure("/some/dir")
    assert called == {"problem": "/some/dir"}

    called.clear()
    monkeypatch.delenv(am.PROBLEM_ENV, raising=False)

    class _H:
        def measure(self, wd):
            return called.setdefault("registry", wd)

    monkeypatch.setattr(de, "_harness", lambda: _H())
    de._default_measure("/some/dir")
    assert called == {"registry": "/some/dir"}


# --- what reaches the AGENT, which is a treatment and not a report -------------

def test_the_handoff_text_carries_no_field_the_prototype_did_not():
    """``evaluation_cases`` is rendered VERBATIM into the child's prompt.

    ``orchestrator/node_summary_view.py`` prints it into the handoff, so every
    scalar in a family is treatment text. This study compares handoff arms, so
    adding a field here changes the thing being measured and quietly makes runs
    incomparable with earlier ones -- it is not a free improvement.

    Absolute wall-clock seconds are the sharpest case: they tell an agent about
    the machine rather than about its kernel, and the prototype never showed
    them.
    """
    report = _report([_case("c1", verdict="fail", correct=True, speedup=0.02)])
    scored = DeterministicEvaluator().score_result(am.report_to_measurement(report))
    shown = scored["evaluation_cases"]["c1"]["measurements"]
    assert set(shown) <= {"speedup", "max_relative_error"}, (
        f"new fields reached the handoff prompt: {sorted(set(shown))}")
    assert "credited_seconds" not in shown
    assert "regression_verdict" not in shown


def test_the_diagnostics_survive_in_the_audit_channel():
    """Kept out of the prompt is not the same as thrown away."""
    report = _report([_case("c1", verdict="fail", correct=True, speedup=0.02)])
    scored = DeterministicEvaluator().score_result(am.report_to_measurement(report))
    diag = scored["measurement_audit"]["case_diagnostics"]["c1"][0]
    assert diag["regression_verdict"] == "fail"
    assert diag["credited_seconds"] == pytest.approx(50.0)
    assert scored["measurement_audit"]["cases"]["c1"], "raw repetitions were dropped"


def test_a_scored_node_records_which_instrument_produced_it():
    """Without this the numbers survive and the question does not: a checkpoint
    held a speedup with nothing saying which problem, which sizes, or which
    frozen bytes it was measured against."""
    report = _report([_case("c1", verdict="pass", correct=True, speedup=1.5)])
    scored = DeterministicEvaluator().score_result(am.report_to_measurement(report))
    provenance = scored["measurement_audit"]["measurement_provenance"]
    assert provenance["problem_revision"] == PROBLEM
    assert provenance["dataset_revision"] == "native-perf-gemm-cases/v1@smoke"
    assert provenance["report_digest"] == report.report_digest
    assert provenance["regression_threshold"] == pytest.approx(0.95)
