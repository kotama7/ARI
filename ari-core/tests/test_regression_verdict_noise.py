"""A regression verdict must be a finding, not a coin flip.

The comparison was a strict ``centre < regression_threshold`` and the default
threshold is 1.0 -- exactly the value a candidate equal to the reference is
trying to measure. So for the one candidate whose right answer is known, the
verdict was decided by which side of its own noise the median happened to land.

MEASURED, the frozen reference built with its own flags and scored against
itself: 0.9942 / 0.9996 / 0.9994, and on another run 0.9997 / 0.9954 / 1.0000.
Every one of those is "fail". The instrument called its own denominator a
regression, and under a design where the harness verdict sets a node's frontier
class that is not a cosmetic error.

The rule now is that a shortfall inside the spread is not something this
instrument resolved. Where a tier ran one repetition there is no measured
spread, so it falls back to the widest spread the instrument is trusted at
anywhere else -- which still leaves a negative control that is a hundred times
slower comfortably outside.
"""

from __future__ import annotations

import pytest

from ari.assurance.native_perf import (
    reference_flags,
    reference_source,
    verify_native_perf,
)
from ari.assurance.native_perf_common import MAX_TRUSTED_SPREAD
from ari.assurance.problems import load_problem

PROBLEM = "gemm-dense-fp64/v1@2026q3"


@pytest.fixture(scope="module")
def problem():
    return load_problem(PROBLEM)


def _run(problem, source, *, tier, threshold=1.0):
    return verify_native_perf(
        problem, source, tier=tier,
        dataset_revision=problem.definition.parity_case_set or problem.definition.case_set,
        candidate_flags=" ".join(reference_flags(problem)),
        regression_threshold=threshold)


def test_one_repetition_cannot_carry_a_regression_verdict(problem):
    """A single measurement does not know its own spread."""
    report = _run(problem, reference_source(problem), tier="screen")
    assert report.verdict != "fail", (
        "the frozen reference was called a regression against itself")
    case = report.case_results[0]
    if case.verdict == "inconclusive":
        assert "one measurement" in case.detail


def test_the_reference_is_not_a_regression_against_itself(problem):
    """The denominator scored as a candidate. Any verdict but fail is honest;
    fail is the instrument contradicting its own definition of 1.0."""
    report = _run(problem, reference_source(problem), tier="validate")
    assert report.verdict != "fail", report.case_results[0].detail


def test_a_hundredfold_slower_kernel_still_fails_from_one_repetition(problem):
    """The rule must not become a licence to be slow.

    This is the parity probe's own negative control, at the tier the probe runs
    it at. It is ~0.009x of the reference, which no spread explains, so the
    single-repetition fallback must still refuse it -- otherwise registration
    stops being able to tell a slow answer from a good one.
    """
    slow = problem.path(problem.definition.scaffolding.negative_control_slow)
    report = _run(problem, slow, tier="screen", threshold=0.95)
    assert report.verdict == "fail", report.case_results[0].detail
    assert "spread" in report.case_results[0].detail


def test_the_fallback_is_the_figure_the_instrument_is_read_at():
    """Not a new constant invented for this rule."""
    from ari.assurance.drivers.perf import _MAX_CLEAN_SPREAD

    assert MAX_TRUSTED_SPREAD == 0.1
    assert _MAX_CLEAN_SPREAD == MAX_TRUSTED_SPREAD
