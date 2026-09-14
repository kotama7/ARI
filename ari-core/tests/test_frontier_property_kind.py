"""A slow answer is a result. A wrong answer is a repair.

`_frontier` mapped the aggregate verdict alone: pass -> scientific_frontier,
fail -> debug_frontier. That is right for a candidate that computed the wrong
answer and wrong for one that computed the right answer more slowly than a tuned
reference, and the assurance layer cannot tell them apart from the aggregate
because `status` is the max over every property.

It matters the moment a performance Harness becomes reachable. The shipped
denominator is a competent blocked kernel and the seed the agent starts from is
measured at 0.008-0.02x of it, so `performance-regression` is "fail" for
essentially every node in the first generations -- and every one of them would
have been sent to repair for the crime of not yet being fast. The scoring path
already draws this line: its validity is correctness and its ranking is the
speedup. The two must not disagree about what a node IS.

FAIL-CLOSED. The exemptions are named; anything else failing still disqualifies.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ari.rqgm.assurance_bridge import _QUALITY_PROPERTIES, RQGMAssuranceBridge


def _bridge(mode: str = "enforce") -> RQGMAssuranceBridge:
    bridge = RQGMAssuranceBridge.__new__(RQGMAssuranceBridge)
    bridge.admission = SimpleNamespace(modes=SimpleNamespace(assurance=mode))
    return bridge


def test_a_slow_but_correct_candidate_stays_a_scientific_result():
    """The finding is that it is slower, not that it is broken."""
    assert _bridge()._frontier(
        "fail", {"numerical-equivalence": "pass",
                 "performance-regression": "fail"}) == "scientific_frontier"


def test_a_wrong_candidate_still_goes_to_repair():
    assert _bridge()._frontier(
        "fail", {"numerical-equivalence": "fail",
                 "performance-regression": "pass"}) == "debug_frontier"


def test_wrong_and_slow_together_is_still_a_repair():
    """The exemption is not a loophole: one disqualifying failure is enough."""
    assert _bridge()._frontier(
        "fail", {"numerical-equivalence": "fail",
                 "performance-regression": "fail"}) == "debug_frontier"


@pytest.mark.parametrize("property_id", [
    "trajectory-equivalence", "interface-conformance", "reproducibility",
    "memory-safety", "some-property-invented-next-year",
])
def test_every_other_property_still_disqualifies(property_id):
    """FAIL-CLOSED, and the reason it is an allowlist of exemptions rather than
    of disqualifiers: the vocabulary's own `correctness_properties` omits
    trajectory-equivalence, which IS the stencil verifier's primary property."""
    assert property_id not in _QUALITY_PROPERTIES
    assert _bridge()._frontier("fail", {property_id: "fail"}) == "debug_frontier"


def test_the_mapping_is_unchanged_without_verdicts():
    """Callers that pass nothing keep exactly the old behaviour."""
    bridge = _bridge()
    assert bridge._frontier("pass") == "scientific_frontier"
    assert bridge._frontier("fail") == "debug_frontier"
    assert bridge._frontier("inconclusive") == "uncertified_frontier"
    assert bridge._frontier("tampered") == "uncertified_frontier"


def test_audit_mode_is_untouched():
    assert _bridge("audit")._frontier("fail", {"numerical-equivalence": "fail"}) \
        == "scientific_frontier"


def test_no_shipped_harness_decides_a_quality_property_yet():
    """So this change moves nothing today -- it makes reachability safe later.

    Every property the reachable Harnesses decide is a disqualifying one, so the
    mapping they get is the mapping they had. If that stops being true, this
    test says so before a search does.
    """
    import pathlib

    import yaml

    root = pathlib.Path(__file__).resolve().parents[1] / "config" / "harnesses" / "builtin"
    deciding = {}
    for path in sorted(root.glob("*.yaml")):
        manifest = yaml.safe_load(path.read_text())
        for coverage in manifest["properties"]:
            deciding.setdefault(coverage["property_id"], []).append(manifest["id"])
    quality = sorted(set(deciding) & _QUALITY_PROPERTIES)
    assert quality == ["performance-regression"], (
        f"a shipped Harness now decides {quality}; check the frontier still "
        f"treats it the way this file argues it should")
