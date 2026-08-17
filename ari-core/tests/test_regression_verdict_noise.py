"""A regression verdict must be a finding, not a coin flip.

The comparison was a strict ``centre < regression_threshold`` and the default
threshold was 1.0 -- exactly the value a candidate equal to the reference is
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

AND THE SPREAD IT FALLS BACK TO WAS THE ONLY ONE BOUNDED. A MEASURED spread had
no ceiling and the last branch set only ``detail``, so the pass region was
``centre >= threshold / (1 + spread)`` and grew without limit as the machine got
noisier: measured here, a candidate running the frozen reference two to four
times per call scored 0.5043x of that same reference at a spread of 1.509 and
was certified "pass". The rule was inverted against its own sibling too -- ONE
repetition with a small shortfall refused to decide, while MANY repetitions with
a huge measured spread made the stronger, positive claim. Noise widens
"inconclusive", never "pass".

THE OTHER HALF OF A VERDICT IS WHAT IT IS READ AGAINST. The parity probe
certified its controls at 0.95 while the measurement, the worker and the
evaluator each defaulted to 1.0 -- and the governed path passes no threshold at
all, so a registered run judged its candidate at a figure the evidence beside it
had never been earned at. There is one figure now and these tests hold every
entry point to it.
"""

from __future__ import annotations

import inspect
import json
import pathlib
from types import SimpleNamespace

import pytest

from ari.assurance.native_perf import (
    DEFAULT_REGRESSION_THRESHOLD,
    reference_flags,
    reference_source,
    verify_native_perf,
)
from ari.assurance.native_perf_common import MAX_TRUSTED_SPREAD
from ari.assurance.problems import load_problem

PROBLEM = "gemm-dense-fp64/v1@2026q3"
#: The parity report the performance Harness was registered on. Its negative
#: controls quote the threshold they were refused at, which is what makes it an
#: anchor for the constant rather than a copy of it.
PARITY_EVIDENCE = (pathlib.Path(__file__).resolve().parents[1] / "config"
                   / "harnesses" / "evidence" / "hpc_gemm_performance"
                   / "official_runner_parity.json")


#: THESE TESTS TIME A KERNEL, so they must time it where this instrument says
#: it can read one. Left to the ambient budget they take one thread per physical
#: core, and on a wide host the parity case then runs BELOW the driver's own
#: ``_MIN_RESOLVING_SECONDS`` floor -- where the frozen reference scored against
#: itself is not reliably 1.0 and this file's first assertion is a coin flip.
#:
#: MEASURED on an idle exclusive 96-core host, the reference against itself at
#: screen tier, forty runs per budget:
#:
#:   budget  case      worst ratio   verdicts
#:   96      3.4 ms    0.7497        24 pass, 13 inconclusive, 3 FAIL
#:   24      7.5 ms    0.7780        38 pass,  1 inconclusive, 1 FAIL
#:    8     20.8 ms    0.9764        40 pass
#:    2     80.9 ms    0.9908        40 pass
#:
#: So it failed about one full-suite run in three, on an idle machine, with no
#: order dependence and no competing load -- adding load made it PASS, because
#: load lengthened the timed region. Two is pinned for the headroom: sixteen
#: times the floor, so a host with much faster cores stays resolved. What is
#: under test here is the VERDICT RULE, and the rule is only observable where
#: the measurement it reads is one.
MEASUREMENT_BUDGET = "2"


@pytest.fixture(autouse=True)
def _resolved_measurement(monkeypatch):
    monkeypatch.setenv("ARI_PERF_THREADS", MEASUREMENT_BUDGET)


@pytest.fixture(scope="module")
def problem():
    return load_problem(PROBLEM)


def _run(problem, source, *, tier, threshold=DEFAULT_REGRESSION_THRESHOLD):
    return verify_native_perf(
        problem, source, tier=tier,
        dataset_revision=problem.definition.parity_case_set or problem.definition.case_set,
        candidate_flags=" ".join(reference_flags(problem)),
        regression_threshold=threshold)


#: Appended to a renamed copy of the frozen reference to make a candidate that
#: is about twice as slow on the median and varies wildly around it.
#:
#: The base kernel IS the denominator, so one pass measures ~1.0x of it on any
#: machine and the ratio is set by the pass COUNT rather than by how this host
#: happens to compile a hand-written kernel. The count is read out of the
#: instance, which the instrument reseeds every repetition, so the same source
#: takes a different time each time -- and every pass zeroes C before it
#: accumulates, so the repeats are idempotent and the answer stays correct.
#: Only the credited time moves, which is the axis under test.
_JITTER = r'''
/* --- how many times the (idempotent) kernel above runs, decided by the data --- */
void gemm(int n, int m, int p,
          const double *A, const double *B, double *C)
{
    static const int table[5] = {0, 3, 1, 1, 1};
    double v = A[0];
    if (v < 0.0) v = -v;
    const unsigned long long bucket = (unsigned long long)(v * 1e6) % 5ULL;
    volatile int passes = table[bucket] + 1;
    for (int r = 0; r < passes; ++r) gemm_once(n, m, p, A, B, C);
}
'''


def _jittery_candidate(problem, out_dir) -> pathlib.Path:
    """The frozen reference, renamed and run a data-dependent number of times.

    ``gemm_once`` is static, so the object still exports only ``gemm`` and the
    kernel audit passes. At seed 0 the five ``certify`` repetitions draw 1, 4, 2,
    2 and 2 passes: a median of about half the reference's speed, with a spread
    far past anything this instrument is read at.
    """
    marker = "void gemm(int n, int m, int p,"
    source = reference_source(problem).read_text(encoding="utf-8")
    assert source.count(marker) == 1, "the frozen reference's signature drifted"
    path = pathlib.Path(out_dir) / "jittery_gemm.c"
    path.write_text(
        source.replace(marker, "static void gemm_once(int n, int m, int p,") + _JITTER,
        encoding="utf-8")
    return path


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
    fail is the instrument calling its own denominator a regression.

    AT THE THRESHOLD THE INSTRUMENT ACTUALLY READS. This used to run at 1.0,
    which is a coin flip on exactly this candidate and flaked as one: the fail
    rule is ``(threshold - median) > (max - min)``, and at a threshold of 1.0 a
    reference measuring 0.9974 with a 0.0010 span fails it. Measured, both
    before and after this rule changed, from the same dictated ratios -- the
    branch is unchanged, the threshold it is asked about is not.
    """
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
    report = _run(problem, slow, tier="screen")
    assert report.verdict == "fail", report.case_results[0].detail
    assert "spread" in report.case_results[0].detail


def test_the_fallback_is_the_figure_the_instrument_is_read_at():
    """Not a new constant invented for this rule."""
    from ari.assurance.drivers.perf import _MAX_CLEAN_SPREAD

    assert MAX_TRUSTED_SPREAD == 0.1
    assert _MAX_CLEAN_SPREAD == MAX_TRUSTED_SPREAD


# --------------------------------------------------------------------------
# a measured spread is not a licence to pass
# --------------------------------------------------------------------------

def test_a_wide_measured_spread_cannot_certify_a_candidate_half_as_fast(
        problem, tmp_path):
    """The defect, end to end, on a candidate built for it.

    It is genuinely about twice as slow as the frozen reference and it lands
    inside the region the old rule called "within the spread it is read at" --
    the assertion below states that region's own arithmetic, so this test fails
    if the case stops demonstrating anything rather than passing vacuously.
    """
    report = _run(problem, _jittery_candidate(problem, tmp_path), tier="certify",
                  threshold=DEFAULT_REGRESSION_THRESHOLD)
    case = report.case_results[0]
    assert report.verdict != "pass", (
        f"{case.speedup:.4g}x of the frozen reference at a spread of "
        f"{case.relative_spread!r} was certified as not a regression")
    assert case.speedup < 0.75, (
        f"the candidate was meant to be about twice as slow: {case.detail}")
    assert case.relative_spread is not None
    assert case.relative_spread > MAX_TRUSTED_SPREAD, (
        f"the candidate was meant to vary far past what this instrument is read "
        f"at: {case.detail}")
    shortfall = DEFAULT_REGRESSION_THRESHOLD - case.speedup
    assert shortfall <= case.speedup * case.relative_spread, (
        "the case no longer sits in the region the old rule passed")
    assert case.verdict == "inconclusive", case.detail
    assert "wider than" in case.detail


def test_the_pass_region_does_not_grow_with_the_measured_spread(problem, monkeypatch):
    """The same rule with the machine taken out of it.

    Everything real stays real -- the two launches, the output files, the oracle
    that checks them -- and only the number the ratio is taken from is dictated,
    so the arithmetic is identical on every host: ratios of 1.0, 0.5 and 0.25
    give a median exactly half the threshold's worth and a spread of 1.5. Under
    the old rule ``0.45 <= 0.5 * 1.5`` made that "pass".
    """
    from ari.assurance import native_perf_measure

    launched = native_perf_measure.run_timed
    dictated = iter([1.0, 2.0, 4.0])

    def _scripted(*args, role="candidate", **kwargs):
        launched(*args, role=role, **kwargs)
        return next(dictated) if role == "candidate" else 1.0

    monkeypatch.setattr(native_perf_measure, "run_timed", _scripted)
    report = _run(problem, reference_source(problem), tier="validate",
                  threshold=DEFAULT_REGRESSION_THRESHOLD)
    case = report.case_results[0]
    assert case.speedup == pytest.approx(0.5)
    assert case.relative_spread == pytest.approx(1.5)
    assert case.verdict == "inconclusive", case.detail
    assert report.verdict == "inconclusive"


def test_a_median_above_the_threshold_is_not_a_pass_from_an_unresolved_run(
        problem, monkeypatch):
    """"Not slower than the reference" is a positive claim like any other.

    Ratios of 1.0, 2.0 and 0.5 put the median above the threshold, which is
    where the old rule stopped looking -- but the repetitions ran anywhere from
    twice the reference's speed to half of it, and that is not a run in which
    anything about this candidate's speed was established.
    """
    from ari.assurance import native_perf_measure

    launched = native_perf_measure.run_timed
    dictated = iter([1.0, 0.5, 2.0])            # ratios 1.0, 2.0, 0.5

    def _scripted(*args, role="candidate", **kwargs):
        launched(*args, role=role, **kwargs)
        return next(dictated) if role == "candidate" else 1.0

    monkeypatch.setattr(native_perf_measure, "run_timed", _scripted)
    report = _run(problem, reference_source(problem), tier="validate",
                  threshold=DEFAULT_REGRESSION_THRESHOLD)
    case = report.case_results[0]
    assert case.speedup == pytest.approx(1.0)
    assert case.relative_spread == pytest.approx(1.5)
    assert case.verdict == "inconclusive", case.detail


# --------------------------------------------------------------------------
# and one figure for what the verdict is read against
# --------------------------------------------------------------------------

def test_every_entry_point_defaults_to_the_one_threshold():
    """A threshold a verdict is read off cannot be a per-call-site default."""
    from ari.assurance.native_perf_measure import verify_performance
    from ari.evaluator.assurance_measure import measure

    for entry in (verify_performance, measure):
        parameter = inspect.signature(entry).parameters["regression_threshold"]
        assert parameter.default == DEFAULT_REGRESSION_THRESHOLD, entry.__name__


def test_the_worker_the_governed_path_launches_carries_the_same_figure(monkeypatch):
    """``_worker_argv`` builds the perf branch WITHOUT a threshold, so the
    worker's own default is what a registered manifest is judged at."""
    from ari.assurance.drivers import perf_worker

    seen: dict = {}

    def _capture(problem, candidate, **kwargs):
        seen.update(kwargs)
        return SimpleNamespace(model_dump_json=lambda: "{}")

    monkeypatch.setattr(perf_worker, "verify_native_perf", _capture)
    assert perf_worker.main(["--problem", PROBLEM, "--candidate", "candidate_gemm.c",
                             "--tier", "screen"]) == 0
    assert seen["regression_threshold"] == DEFAULT_REGRESSION_THRESHOLD


def test_the_parity_probe_certifies_at_the_figure_a_scored_run_is_judged_at(monkeypatch):
    """An instrument cannot be certified at a ratio it is not then read at."""
    from ari.assurance.drivers import perf as perf_driver

    thresholds: list[float] = []

    def _capture(problem, source, **kwargs):
        thresholds.append(kwargs["regression_threshold"])
        # ``placement`` because the probe records the placement it MEASURED at
        # rather than the one the manifest pins -- a probe that echoed the pin
        # could not be told apart from one that set nothing and got lucky.
        return SimpleNamespace(verdict="pass", case_results=(),
                               placement=None,
                               report_digest="sha256:" + "0" * 64)

    monkeypatch.setattr(perf_driver, "verify_native_perf", _capture)
    # An EMPTY placement, deliberately: the probe now times its controls at the
    # budget the manifest pins, and this test is about the threshold alone. A
    # manifest that pins none leaves the ambient regime untouched, which is the
    # path that keeps this isolated to the one question it asks.
    perf_driver.NativePerfDriver().parity_probe(
        SimpleNamespace(oracle=SimpleNamespace(revision=PROBLEM),
                        id="hpc/gemm-performance", registered_placement={}))
    assert thresholds == [DEFAULT_REGRESSION_THRESHOLD] * 3


def test_the_registered_evidence_was_earned_at_this_threshold():
    """The anchor. The shipped parity report quotes the ratio its negative
    control was refused at; if the constant moves away from it, the evidence
    beside the manifest stops describing what the instrument now does."""
    evidence = json.loads(PARITY_EVIDENCE.read_text(encoding="utf-8"))
    details = [item["detail"] for item in evidence["controls"]["negatives"]]
    assert any(f"{DEFAULT_REGRESSION_THRESHOLD:g}x threshold" in detail
               for detail in details), details
