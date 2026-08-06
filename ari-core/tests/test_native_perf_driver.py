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


def _real_case_set(revision="native-perf-gemm-cases/v1@parity"):
    from ari.assurance.native_perf_common import load_case_set
    _set, digest = load_case_set(revision)
    return revision, digest


class _Manifest:
    def __init__(self, **kw):
        self.driver = _Asset(kw.get("driver_revision", PERF_DRIVER_REVISION),
                             kw.get("driver_sha256", perf_driver_digest()))
        revision, digest = _real_case_set(
            kw.get("dataset_revision", "native-perf-gemm-cases/v1@parity"))
        self.dataset = _Asset(revision, kw.get("dataset_sha256", digest))
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
                  default_toolchain={"requested": "cc", "resolved_path": "/usr/bin/cc",
                                     "version": "cc (GCC) x"},
                  candidate_toolchain={"requested": None, "resolved_path": "/usr/bin/cc",
                                       "version": "cc (GCC) x", "status": "default"},
                  crossed_compiler_boundary=False,
                  base_flags=("-O3", "-fopenmp"), reference_flags=("-ffast-math",),
                  accepted_flags=(), rejected_flags=(),
                  environment={"variables": {}, "sha256": "sha256:" + "0" * 64,
                               "note": "n"},
                  dataset_revision="native-perf-gemm-cases/v1@parity",
                  dataset_sha256="sha256:" + "0" * 64,
                  placement=measurement_placement())
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


def test_the_flag_screen_is_an_allowlist_not_a_denylist():
    """A deny-only screen let -I through, and an accepted -I lands BEFORE the
    pinned -I<kernels> in the argv — so a candidate-supplied header won the quoted
    include and the header-less staging was inert. Verified by compiling a
    candidate with its own gemm_kernel.h. -B was accepted too, which substitutes
    the compiler proper inside the scored compile."""
    accepted, rejected = screen_flags(
        "-I/tmp/evil -B/tmp/fake -D X -L/l -lm -Wl,-z -include h -o x -static "
        "-SSL2 -save-temps -nostdlib")
    assert accepted == (), f"these must never reach the compile line: {accepted}"
    assert "-I/tmp/evil" in rejected and "-B/tmp/fake" in rejected


def test_the_flag_screen_still_admits_real_optimisation_flags():
    """An allowlist that rejected the useful flags would remove the axis it is
    protecting, including the vendor's -K/-N namespaces."""
    accepted, _ = screen_flags("-O3 -march=native -funroll-loops -Kfast -Nclang "
                               "--param=max-unrolled-insns=200")
    assert len(accepted) == 6


def test_a_flag_file_written_with_literal_backslash_n_still_works():
    """54 of 2133 corpus files wrote it that way; the comment tail then glued
    itself onto the first real flag and destroyed it."""
    accepted, _ = screen_flags("-O3 # note\\n-funroll-loops")
    assert "-O3" in accepted and "-funroll-loops" in accepted


def test_one_repetition_has_no_spread():
    """Reporting 0.0 for a single point would read as perfect stability."""
    assert relative_spread([1.0]) is None
    # (max - min) / MEDIAN, so two points spread over a median of 1.05 read 9.5%,
    # not 10%: the denominator is the centre the median is quoted at.
    assert relative_spread([1.0, 1.1]) == pytest.approx(0.1 / 1.05, rel=1e-9)
    assert relative_spread([1.0, 1.05, 1.1]) == pytest.approx(0.1 / 1.05, rel=1e-9)


def test_the_placement_record_separates_what_is_set_from_what_is_not():
    """The harness DOES pin the binding regime — both sides of a comparison have
    to be measured the same way — and does NOT pin the memory policy: there is no
    numactl, taskset, mbind or set_mempolicy on this path. Reporting one flag for
    both would let a reader draw the opposite conclusion about either."""
    place = measurement_placement()
    assert place["binding_is_set_by_the_harness"] is True
    assert place["memory_policy_is_set_by_the_harness"] is False
    for key in ("machine", "page_size_bytes", "cpus_allowed", "cpus_allowed_count",
                "mems_allowed", "numa_nodes_total", "numa_node_cpulists",
                "numa_nodes_spanned", "thread_budget", "omp_dynamic", "sha256"):
        assert key in place, f"placement lost {key}"


def test_placement_carries_its_own_digest():
    """Folded into the report digest alone it identifies the whole run and
    nothing smaller — records could not be grouped by allocation shape."""
    place = measurement_placement()
    assert place["sha256"].startswith("sha256:")
    assert measurement_placement()["sha256"] == place["sha256"]


def test_a_report_without_a_real_placement_is_refused():
    """An empty placement is a valid dict and an invalid measurement."""
    with pytest.raises(Exception):
        _report(placement={})


def test_the_report_records_the_flags_that_produced_it():
    rep = _report()
    body = json.loads(rep.model_dump_json())
    for key in ("base_flags", "reference_flags", "accepted_flags", "rejected_flags",
                "environment"):
        assert key in body
    assert body["environment"]["sha256"].startswith("sha256:")


def test_the_report_records_what_the_candidate_ASKED_for():
    """A run that requested the vendor compiler, did not get it, and was scored on
    the default was indistinguishable from one that requested nothing."""
    rep = _report()
    assert set(rep.candidate_toolchain) >= {"requested", "resolved_path",
                                            "version", "status"}
    assert rep.default_toolchain["version"] is not None


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


# --- the object-level checks the flag deny list was defending -------------------

def _build(tmp_path, body: str, **kw):
    from ari.assurance.native_perf_common import compile_binary
    source = tmp_path / "cand.c"
    source.write_text(body)
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    return compile_binary(kind="gemm", role="candidate", source=source,
                          out_dir=out, compiler="cc", **kw)


_HONEST = """#include "gemm_kernel.h"
void gemm(int n,int m,int p,const double*A,const double*B,double*C){
  for(int i=0;i<n;i++)for(int j=0;j<m;j++){double s=0;
    for(int l=0;l<p;l++)s+=A[i*p+l]*B[l*m+j]; C[i*m+j]=s;} }
"""


def test_an_honest_kernel_still_builds(tmp_path):
    assert _build(tmp_path, _HONEST).is_file()


def test_a_kernel_that_runs_code_outside_the_measured_call_is_refused(tmp_path):
    """Out-of-band code exports no extra global symbol, so the name check cannot
    see it. A destructor is exactly how the prototype's own forge test cheated:
    it read /proc/self/cmdline for the private timing path and overwrote it."""
    from ari.assurance.native_perf_common import PerfBuildError
    # The destructor needs an observable side effect or -O3 deletes it and no
    # .fini_array is emitted -- the control would then pass for the wrong reason.
    body = ('#include <stdio.h>\n#include "gemm_kernel.h"\n'
            'static volatile int _sink;\n'
            '__attribute__((destructor)) static void s(void){ _sink = 1; }\n'
            + _HONEST)
    with pytest.raises(PerfBuildError, match="outside the measured call"):
        _build(tmp_path, body)


def test_a_kernel_that_defines_the_clock_is_refused(tmp_path):
    """The candidate object links into the FROZEN DRIVER, so a definition of
    clock_gettime wins the link and forges the timer."""
    from ari.assurance.native_perf_common import PerfBuildError
    body = ('#include <time.h>\n#include "gemm_kernel.h"\n'
            'int clock_gettime(clockid_t c, struct timespec *t){(void)c;'
            't->tv_sec=0;t->tv_nsec=1;return 0;}\n' + _HONEST)
    with pytest.raises(PerfBuildError, match="exports symbols other than"):
        _build(tmp_path, body)


def test_the_reference_flags_reach_the_link(tmp_path):
    """-ffast-math sets process-wide FTZ/DAZ at LINK time. Leaving it off the
    link made the anchor a different binary from the one it is supposed to be,
    so ratios were not comparable with the harness this replaces."""
    source = (CORE / "ari" / "assurance" / "native_perf_common.py").read_text()
    assert "*base, *reference_flags, str(main_o), str(kern_o)" in source


def test_a_reference_failure_is_not_charged_to_the_candidate():
    """"candidate exceeded 300s" named a program the candidate did not write."""
    from ari.assurance.native_perf_common import (
        PerfBuildError, PerfInfrastructureError, _fault)
    assert _fault("candidate") is PerfBuildError
    for role in ("reference", "reference_matched"):
        assert _fault(role) is PerfInfrastructureError


def test_the_control_side_blas_is_pinned_before_numpy_loads():
    """The oracle runs in THIS process; an unpinned pool sized to the allocation
    stays alive on the cores the next timed child will use."""
    import os
    for name in ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        assert os.environ.get(name), f"{name} is not pinned"


def test_the_oracle_does_not_run_between_the_timed_launches():
    """A full-size numpy GEMM between the candidate and the matched reference
    lands on the same cores, on one side of the comparison only — so it moved
    toolchain_gain. The property is positional: no timed launch may follow the
    oracle within a repetition."""
    lines = (CORE / "ari" / "assurance" / "native_perf_gemm.py").read_text().splitlines()
    start = next(i for i, l in enumerate(lines) if "for index in range(reps):" in l)
    launches = [i for i, l in enumerate(lines[start:], start) if "run_timed(" in l]
    oracle = next(i for i, l in enumerate(lines[start:], start) if "_residual_ok(" in l)
    assert launches, "no timed launch found"
    assert max(launches) < oracle, (
        "a timed launch happens after the oracle; the oracle's BLAS call lands "
        "between two measurements it is supposed to sit outside")


def test_the_vendor_compiler_is_looked_for_off_PATH():
    """which() alone reported "unavailable" for a compiler sitting on the disk;
    the measuring job pins a bare PATH, so the whole toolchain axis collapsed."""
    from ari.assurance.native_perf_common import COMPILER_SEARCH_GLOBS
    assert COMPILER_SEARCH_GLOBS.get("fcc")


def test_the_environment_is_captured_by_prefix_not_by_a_hand_list():
    """A hand list records exactly the variables somebody thought of — and the
    prototype's omitted the one later measured to move the same frozen source by
    5.9x."""
    from ari.assurance.native_perf_common import measurement_environment
    record = measurement_environment({"XOS_MMM_L_PAGING_POLICY": "demand:demand:demand"})
    assert record["variables"]["XOS_MMM_L_PAGING_POLICY"] == "demand:demand:demand"
    assert record["sha256"].startswith("sha256:")


def test_a_credential_value_never_reaches_the_record(monkeypatch):
    monkeypatch.setenv("ARI_LLM_API_KEY", "super-secret")
    from ari.assurance.native_perf_common import measurement_environment
    assert "super-secret" not in json.dumps(measurement_environment())


# --- which problems is registered, not requested --------------------------------

def test_a_size_is_chosen_by_naming_a_pinned_set_not_by_passing_shapes():
    """Registration evidence is established at a size and does not transfer:
    measured on an aarch64 compute node, 0.095% spread at the scored shape
    against 100x at a small one. A run free to choose its own size would carry an
    attestation saying "verified" about a problem the manifest never named."""
    import inspect

    from ari.assurance.native_perf_gemm import verify_gemm_performance
    params = inspect.signature(verify_gemm_performance).parameters
    assert "dataset_revision" in params
    assert "shapes" not in params, "the unpinned size path is back"


def test_an_unregistered_case_set_is_refused():
    from ari.assurance.native_perf_common import PerfInfrastructureError, load_case_set
    with pytest.raises(PerfInfrastructureError, match="no registered case set"):
        load_case_set("native-perf-gemm-cases/v1@invented")


def test_prepare_refuses_a_dataset_pin_that_no_longer_matches():
    """This is what makes 'verified' mean 'verified at this size'."""
    with pytest.raises(ValueError, match="registered problem set has changed"):
        NativePerfDriver().prepare(
            _Manifest(dataset_sha256="sha256:" + "9" * 64), _Request())


def test_prepare_refuses_a_case_set_that_cannot_support_a_verdict():
    """A cheap set can show a candidate built and was right; it cannot support
    'did not regress' when its own spread swamps the difference claimed."""
    with pytest.raises(ValueError, match="resolves=false"):
        NativePerfDriver().prepare(
            _Manifest(dataset_revision="native-perf-gemm-cases/v1@smoke"),
            _Request())


def test_the_report_says_which_problems_it_measured():
    rep = _report()
    body = json.loads(rep.model_dump_json())
    assert body["dataset_revision"] and body["dataset_sha256"].startswith("sha256:")

