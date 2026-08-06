"""The performance harness fills a slot that was reserved and empty.

`performance-regression` is in the property vocabulary and three knowledge-skill
import profiles already REQUIRE it, so until now that requirement resolved to
``no_candidate``. These tests pin the contracts that make the new driver a
harness rather than a stopwatch. The measurement itself needs a compute node and
is exercised there; everything here runs anywhere.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ari.assurance.drivers import builtin_driver_map
from ari.assurance.drivers.perf import (
    PERF_DRIVER_REVISION,
    NativePerfDriver,
    perf_driver_digest,
)
from ari.assurance.native_perf_common import (
    NativePerfReportV1,
    PerfCaseResultV1,
    PerfRepetitionV1,
    crosses_compiler_boundary,
    isa_flags_for,
    kernels_root,
    measurement_placement,
    relative_spread,
    resolve_compiler,
    screen_flags,
)

CORE = Path(__file__).resolve().parents[1]


def test_the_driver_is_registered_and_its_revision_is_unique():
    drivers = builtin_driver_map()
    assert PERF_DRIVER_REVISION in drivers
    assert isinstance(drivers[PERF_DRIVER_REVISION], NativePerfDriver)
    assert len(drivers) == len({type(d).__name__ for d in drivers.values()})


def test_the_driver_digest_covers_the_frozen_scaffolding(tmp_path, monkeypatch):
    """The denominator is part of the instrument.

    A driver digest over python only would let the frozen reference change under
    a manifest that still pinned the same driver — the scaffolding is what the
    ratio is measured against, so it has to be inside the content address.
    """
    before = perf_driver_digest()
    reference = kernels_root() / "gemm" / "reference_gemm.c"
    original = reference.read_bytes()
    try:
        reference.write_bytes(original + b"\n/* drift */\n")
        assert perf_driver_digest() != before, (
            "editing the frozen reference did not move the driver digest")
    finally:
        reference.write_bytes(original)
    assert perf_driver_digest() == before


def test_the_scaffolding_is_present_and_compilable_in_core():
    """The point of the move: a registered harness must not need a workspace."""
    kdir = kernels_root() / "gemm"
    for name in ("gemm_kernel.h", "gemm_main.c", "reference_gemm.c"):
        assert (kdir / name).is_file(), f"{name} is missing from ari-core"
    text = (kdir / "gemm_main.c").read_text()
    # the properties the measurement rests on, asserted rather than assumed
    assert "double t0 = now_sec();" in text
    assert "NAN" in text, "the output must be poisoned so a no-op fails the oracle"
    assert "#pragma omp parallel for" in text, "the team must exist before the timer"


# --- what prepare() must refuse ------------------------------------------------

class _Asset:
    def __init__(self, revision, sha256):
        self.revision = revision
        self.sha256 = sha256


class _Manifest:
    def __init__(self, **kw):
        self.driver = _Asset(kw.get("driver_revision", PERF_DRIVER_REVISION),
                             kw.get("driver_sha256", perf_driver_digest()))
        self.kind = kw.get("kind", "benchmark")
        self.network_policy = kw.get("network_policy", "deny")
        self.credential_policy = kw.get("credential_policy", "none")


class _Atom:
    def __init__(self, property_id="performance-regression"):
        self.property_id = property_id
        self.method = "benchmark-comparison"
        self.tier = "validate"
        self.scope = {}
        self.atom_digest = "sha256:" + "0" * 64


class _Exec:
    network = "deny"


class _Request:
    def __init__(self, atoms=None):
        self.property_atoms = tuple(atoms or (_Atom(),))
        self.execution_request = _Exec()
        self.run_id = "run"


def test_prepare_accepts_a_well_formed_benchmark_request():
    NativePerfDriver().prepare(_Manifest(), _Request())


@pytest.mark.parametrize("manifest_kw,request_atoms,expected", [
    ({"driver_revision": "other/v1"}, None, "another driver revision"),
    ({"driver_sha256": "sha256:" + "1" * 64}, None, "driver bytes drifted"),
    ({"kind": "artifact_verifier"}, None, "requires a benchmark harness"),
    ({"network_policy": "allowlisted"}, None, "network-denied"),
    ({"credential_policy": "scoped"}, None, "credential-free"),
    ({}, (_Atom("numerical-equivalence"),), "only decides performance-regression"),
])
def test_prepare_refuses_a_mismatched_pairing(manifest_kw, request_atoms, expected):
    """A driver that accepted any manifest would make the pin decorative."""
    with pytest.raises(ValueError, match=expected):
        NativePerfDriver().prepare(_Manifest(**manifest_kw), _Request(request_atoms))


def test_the_driver_does_not_decide_properties_it_cannot_measure():
    """A performance run says nothing about numerical equivalence, and fanning one
    verdict across unrelated atoms is how a determinism failure becomes
    indistinguishable from a numerical one."""
    with pytest.raises(ValueError):
        NativePerfDriver().prepare(
            _Manifest(), _Request((_Atom("performance-regression"),
                                   _Atom("reproducibility"))))


# --- the report is a closed, digest-bound contract ------------------------------

def _report(**kw):
    rep = PerfRepetitionV1(index=0, input_seed=0, credited_seconds=1.0,
                           reference_seconds=2.0, speedup=2.0, correct=True,
                           max_rel_error=0.5)
    case = PerfCaseResultV1(case_id="c", verdict="pass", detail="d", speedup=2.0,
                            relative_spread=None, repetitions=(rep,))
    values = dict(kind="gemm", tier="validate", verdict="pass",
                  case_results=(case,), regression_threshold=1.0,
                  default_toolchain="cc", candidate_toolchain="cc",
                  crossed_compiler_boundary=False, placement={})
    values.update(kw)
    return NativePerfReportV1.create(**values)


def test_the_report_binds_its_own_digest():
    rep = _report()
    assert rep.report_digest.startswith("sha256:")
    with pytest.raises(ValueError):
        NativePerfReportV1.model_validate(
            {**json.loads(rep.model_dump_json()), "verdict": "fail"})


def test_the_report_names_its_denominator_and_threshold():
    """A ratio whose denominator is implied is a number, not a measurement."""
    rep = _report()
    assert rep.denominator == "frozen-reference-anchor"
    assert rep.regression_threshold == 1.0
    assert "placement" in json.loads(rep.model_dump_json())


def test_the_report_rejects_an_unknown_field():
    with pytest.raises(Exception):
        _report(surprise=1)


# --- the pieces that decide what gets measured ---------------------------------

def test_naming_the_default_compiler_is_not_a_compiler_boundary():
    """`selected` only means the candidate named an allowlisted compiler. The
    allowlist contains the default, and cc and gcc are often one binary — a
    matched denominator built against itself reports the reference's own flags
    as a toolchain effect."""
    status, resolved = resolve_compiler("cc")
    assert status == "selected"
    assert crosses_compiler_boundary(status, resolved) is False
    assert crosses_compiler_boundary("default", resolved) is False
    assert crosses_compiler_boundary("selected", "/nonexistent/vendor/bin/fcc") is True


def test_the_isa_flag_is_chosen_per_compiler():
    """Measured on an aarch64 compute node: the vendor driver accepts
    -march=native in its traditional mode but rejects it under -Nclang, which is
    the mode it is worth selecting in."""
    assert "-march=native" in isa_flags_for("cc")
    assert isa_flags_for("/opt/vendor/bin/fcc") == ()


def test_instrumentation_flags_are_refused():
    """Compiler instrumentation carries state between repetitions, and link-time
    optimisation defeats the object-level checks."""
    accepted, rejected = screen_flags("-O3 -fprofile-generate -flto -funroll-loops")
    assert "-O3" in accepted and "-funroll-loops" in accepted
    assert "-fprofile-generate" in rejected and "-flto" in rejected


def test_one_repetition_has_no_spread():
    """Reporting 0.0 for a single point would read as perfect stability."""
    assert relative_spread([1.0]) is None
    # (max - min) / MEDIAN, so two points spread over a median of 1.05 read 9.5%,
    # not 10%: the denominator is the centre the median is quoted at.
    assert relative_spread([1.0, 1.1]) == pytest.approx(0.1 / 1.05, rel=1e-9)
    assert relative_spread([1.0, 1.05, 1.1]) == pytest.approx(0.1 / 1.05, rel=1e-9)


def test_the_placement_record_says_nothing_is_pinned():
    """Every field is an inherited default: there is no numactl, taskset or
    mbind anywhere on this path, and a reader who assumed otherwise would draw
    the opposite conclusion from the same numbers."""
    place = measurement_placement()
    assert place["placement_is_set_by_the_harness"] is False
    for key in ("machine", "page_size_bytes", "cpus_allowed", "numa_nodes_total"):
        assert key in place


# --- degradation ---------------------------------------------------------------

class _Result:
    status = "timed_out"
    artifacts = ()


def test_a_timed_out_run_is_infrastructure_not_a_slow_candidate():
    """Scoring a substrate failure as a regression would make an overloaded node
    look like a bad kernel."""
    out = NativePerfDriver().normalize_result(_Manifest(), _Request(), _Result())
    assert out.verdict == "infrastructure_error"
    assert out.infrastructure_status == "failed"
    assert all(p.verdict == "infrastructure_error" for p in out.property_results)


def test_the_parity_probe_requires_two_different_failure_reasons():
    """A probe whose only negative control is a slow kernel cannot tell a
    performance harness from a stopwatch. Source-level, because running it needs
    a compute node."""
    source = (CORE / "ari" / "assurance" / "drivers" / "perf.py").read_text()
    assert "negative_control_slow" in source and "negative_control_wrong" in source
    assert '"threshold" in slow_detail' in source
    assert '"residual bound" in wrong_detail' in source
