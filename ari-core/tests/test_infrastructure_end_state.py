"""A crashed node must not be readable as a scientific result.

A node killed by the watchdog or by an exception produced NO measurement.
Recording it as a plain failure conflates "the candidate was bad" with "the
framework broke" — the first is data, the second is MISSING data — and averaging
the two together biases exactly the arm comparison the study exists to make.
ended_by already separated finish_json from max_steps but was never set on the
crash paths, so a crashed node looked identical to one that simply never
converged.
"""
from ari.cli.bfts_loop import _mark_infrastructure_end


class _Node:
    def __init__(self):
        self.ended_by = ""
        self.evaluation_status = "valid"
        self.has_real_data = True
        self.metrics = {"_scientific_score": 0.0, "valid_geomean_speedup": 12.0}
        self.evaluator_reason = "some earlier text"
        self.eval_summary = "some earlier text"


def test_timeout_is_recorded_as_infrastructure_not_as_a_zero():
    n = _Node()
    _mark_infrastructure_end(n, "timeout", "node exceeded the 7200s limit")
    assert n.ended_by == "timeout"
    assert n.evaluation_status == "infrastructure_error"
    assert n.has_real_data is False
    assert n.metrics == {}, (
        "stale metrics survived a crash; a reader would average them as a result")
    assert "infrastructure timeout" in n.evaluator_reason


def test_exception_carries_the_exception_type():
    n = _Node()
    _mark_infrastructure_end(n, "exception", "ValueError: bad shape")
    assert n.ended_by == "exception"
    assert "ValueError" in n.eval_summary


def test_it_never_raises_and_masks_the_original_failure():
    class _Hostile:
        @property
        def ended_by(self):
            return ""

        @ended_by.setter
        def ended_by(self, v):
            raise RuntimeError("cannot set")

    _mark_infrastructure_end(_Hostile(), "exception", "x")  # must not raise


def test_ended_by_values_stay_distinguishable():
    """finish_json / max_steps / timeout / exception must all be different."""
    seen = set()
    for how in ("timeout", "exception"):
        n = _Node()
        _mark_infrastructure_end(n, how, "d")
        seen.add(n.ended_by)
    assert seen == {"timeout", "exception"}
    assert "finish_json" not in seen and "max_steps" not in seen
