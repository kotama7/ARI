"""An infrastructure failure has to say which one it was.

The bridge caught every exception from a locked verification with a bare
``except Exception:`` and returned the label ``infrastructure_error`` alone. The
string that said WHY was in hand at that point -- the runner already wraps the
cause as ``locked Harness execution failed: <cause>`` -- and it was dropped, and
the record it wrote had twelve keys and no room for a reason.

That is not a cosmetic loss. Two unrelated defects, a container runtime
installed on no node and a memory bound too small for that runtime to start,
both came out as that same single word. Telling them apart meant replaying the
execution by hand from a saved request.

These tests pin the reason being captured, the reason reaching the record, the
verdict NOT changing because of it, and the reason being stripped of host
identity -- it is written into a checkpoint and can leave with a reproduction
bundle, and the messages that reach it quote absolute paths.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from ari.rqgm.assurance_bridge import RQGMAssuranceBridge, _failure_reason


class _Boom(RuntimeError):
    pass


def _bridge(tmp_path: Path) -> RQGMAssuranceBridge:
    """The bridge with only what these two methods read.

    Constructed without __init__ deliberately: a real one wants a contract, a
    baseline lock and a catalog snapshot, none of which decide anything here.
    """
    bridge = RQGMAssuranceBridge.__new__(RQGMAssuranceBridge)
    bridge.checkpoint_dir = tmp_path
    bridge.admission = SimpleNamespace(
        run_id="run", active_harness_lock_digest="sha256:" + "1" * 64)
    bridge.contract = SimpleNamespace(contract_digest="sha256:" + "2" * 64)
    bridge.baseline = SimpleNamespace(
        lock_digest="sha256:" + "3" * 64,
        harnesses=(SimpleNamespace(manifest_digest="sha256:" + "4" * 64,
                                   covered_atom_digests=("atom-1",)),))
    bridge.catalog = SimpleNamespace(
        manifests=(SimpleNamespace(manifest_digest="sha256:" + "4" * 64),))
    return bridge


def _node():
    return SimpleNamespace(id="node-1", property_verdicts={}, attestation_refs=[],
                           verified_target_digest="", assurance_status="",
                           assurance_tier="", frontier_class="")


def _summary(tmp_path: Path) -> dict:
    path = (tmp_path / "rqgm" / "kca" / "nodes" / "node-1" / "assurance_summary.json")
    return json.loads(path.read_text())


# --- the reason itself ---------------------------------------------------------

def test_the_reason_names_the_exception_and_its_message():
    reason = _failure_reason(_Boom("apptainer executable is unavailable"))
    assert "_Boom" in reason
    assert "apptainer executable is unavailable" in reason


def test_the_reason_carries_no_host_identity(monkeypatch, tmp_path):
    """It ends up in a checkpoint, and a substrate error quotes absolute paths."""
    home = tmp_path / "somebody"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    reason = _failure_reason(
        _Boom(f"logical SIF image is unavailable: {home}/containers/x.sif"))
    assert str(home) not in reason
    assert "x.sif" in reason, "scrubbing must not eat the diagnostic"


def test_the_reason_is_bounded():
    assert len(_failure_reason(_Boom("x" * 5000))) <= 480


# --- it survives the handler that used to discard it ---------------------------

def test_a_failed_verification_returns_the_reason_with_the_label(tmp_path):
    """THE DEFECT, as a test: the handler had no `as exc` and this was lost."""
    bridge = _bridge(tmp_path)
    bridge._verify_locked = lambda *a, **k: (_ for _ in ()).throw(
        _Boom("locked Harness execution failed: apptainer executable is unavailable"))

    attestations, status, reason = bridge._run_tier_suite(
        _node(), None, None, (SimpleNamespace(atom_digest="atom-1"),), tier="screen")

    assert attestations == []
    assert status == "infrastructure_error", (
        "recording the reason must not change the verdict")
    assert "apptainer executable is unavailable" in reason


def test_a_request_failure_is_still_inconclusive_and_now_says_why(tmp_path):
    from ari.assurance.request import HarnessRequestError

    bridge = _bridge(tmp_path)
    bridge._verify_locked = lambda *a, **k: (_ for _ in ()).throw(
        HarnessRequestError("target declaration is absent"))

    _attestations, status, reason = bridge._run_tier_suite(
        _node(), None, None, (SimpleNamespace(atom_digest="atom-1"),), tier="screen")

    assert status == "inconclusive"
    assert "target declaration is absent" in reason


def test_a_clean_suite_returns_no_reason(tmp_path):
    bridge = _bridge(tmp_path)
    bridge._verify_locked = lambda *a, **k: SimpleNamespace(property_results=())

    _attestations, status, reason = bridge._run_tier_suite(
        _node(), None, None, (SimpleNamespace(atom_digest="atom-1"),), tier="screen")

    assert status == ""
    assert reason == ""


# --- and it reaches the record ------------------------------------------------

def test_the_record_says_which_way_the_machinery_broke(tmp_path):
    """The record this replaces had twelve keys and no room for a reason."""
    bridge, node = _bridge(tmp_path), _node()
    bridge._classify(node, status="infrastructure_error",
                     frontier="uncertified_frontier",
                     reason="HarnessSubstrateError: apptainer executable is unavailable")

    summary = _summary(tmp_path)
    assert summary["assurance_status"] == "infrastructure_error"
    assert "apptainer executable is unavailable" in summary["status_reason"]


def test_an_ordinary_verdict_records_no_reason(tmp_path):
    """A pass or a fail is about the candidate and needs no excuse attached."""
    bridge, node = _bridge(tmp_path), _node()
    bridge._classify(node, status="pass", frontier="scientific_frontier")
    assert _summary(tmp_path)["status_reason"] == ""
