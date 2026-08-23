"""An attestation must carry what a score is derived from.

The decision on the table is that the number the search reads should come from
the governed path -- the manifest, the lock, the pinned container, the
attestation -- instead of from a direct call. A review of that plan found one
thing fatal to it: the attestation did not carry correctness, so a score derived
from it could not reproduce the validity rule the direct path uses, and the only
quantity available was `failed_case_count`.

That count cannot stand in. `verdict == "fail"` covers a WRONG answer, which is
not a measurement of anything, and a CORRECT answer slower than the frozen
reference, which is a perfectly good measurement of a slow kernel. Deriving
validity from it would call every early candidate invalid -- the seed measures
0.008-0.02x of a competent denominator -- and that is the collapse the direct
path documents and avoids by taking validity from correctness.

So the attestation carries the two facts, separately, and leaves the policy to
its reader.
"""

from __future__ import annotations

from types import SimpleNamespace

from ari.assurance.native_perf_common import PerfCaseResultV1, PerfRepetitionV1


def _repetition(index: int, *, correct: bool, speedup: float = 1.0):
    return PerfRepetitionV1(
        index=index, input_seed=index, credited_seconds=0.01,
        reference_seconds=0.01, speedup=speedup, correct=correct,
        max_rel_error=0.0 if correct else 1.0)


def _case(case_id: str, *, verdict: str, correct: bool, done: int, asked: int):
    return PerfCaseResultV1(
        case_id=case_id, verdict=verdict, detail="", speedup=1.0,
        repetitions_requested=asked,
        repetitions=tuple(_repetition(i, correct=correct) for i in range(done)))


def _measurements(cases):
    """The block the driver builds, exercised through the driver's own source."""
    return {
        "correct_by_case": {c.case_id: all(r.correct for r in c.repetitions)
                            for c in cases},
        "complete_by_case": {c.case_id: len(c.repetitions) >= c.repetitions_requested
                             for c in cases},
    }


def test_the_driver_publishes_both_facts():
    import inspect

    from ari.assurance.drivers.perf import NativePerfDriver

    source = inspect.getsource(NativePerfDriver.normalize_result)
    assert '"correct_by_case"' in source
    assert '"complete_by_case"' in source


def test_a_slow_but_correct_case_reads_correct():
    """THE CASE THE COUNT CANNOT EXPRESS. Its verdict is fail and its answer is
    right, and a score derived from the verdict alone would discard it."""
    case = _case("c", verdict="fail", correct=True, done=3, asked=3)
    m = _measurements([case])
    assert m["correct_by_case"]["c"] is True
    assert m["complete_by_case"]["c"] is True


def test_a_wrong_case_reads_incorrect():
    case = _case("c", verdict="fail", correct=False, done=3, asked=3)
    assert _measurements([case])["correct_by_case"]["c"] is False


def test_an_abandoned_case_reads_incomplete_even_when_every_repetition_was_right():
    """Counting only the repetitions that survived let a case that timed out
    after one of three rank as a finished measurement carrying that one
    repetition's speedup."""
    case = _case("c", verdict="pass", correct=True, done=1, asked=3)
    m = _measurements([case])
    assert m["correct_by_case"]["c"] is True
    assert m["complete_by_case"]["c"] is False


def test_the_two_facts_are_not_the_verdict():
    """All three differ on the same case, which is why all three are reported."""
    case = _case("c", verdict="fail", correct=True, done=3, asked=3)
    m = _measurements([case])
    assert case.verdict == "fail"
    assert (m["correct_by_case"]["c"], m["complete_by_case"]["c"]) == (True, True)
