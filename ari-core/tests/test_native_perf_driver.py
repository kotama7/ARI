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
from types import SimpleNamespace

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

#: The problem the instrument is exercised against here. A revision, not a
#: task name: ARI no longer has a list of measurable problems.
PROBLEM = "gemm-dense-fp64/v1@2026q3"


def problem_dir():
    from ari.assurance.problems import load_problem
    return load_problem(PROBLEM).directory


def test_the_driver_is_registered_and_its_revision_is_unique():
    drivers = builtin_driver_map()
    assert PERF_DRIVER_REVISION in drivers
    assert isinstance(drivers[PERF_DRIVER_REVISION], NativePerfDriver)
    assert len(drivers) == len({type(d).__name__ for d in drivers.values()})


def test_the_frozen_reference_cannot_drift_under_a_pinned_manifest():
    """The denominator is pinned — by the PROBLEM's digest, not the driver's.

    It used to be inside the driver digest, on the reasoning that the
    denominator is part of the instrument. That was the right property attached
    to the wrong thing: it made adding an unrelated research theme a
    re-registration of every harness on this driver, for a file none of them
    read. The reference belongs to its problem, so what must hold now is that
    editing it moves the PROBLEM digest and that ``prepare`` refuses when the
    manifest's pin no longer matches. Both are asserted, because the digest
    moving is useless if nothing checks it.
    """
    from ari.assurance.problems import load_problem

    before = load_problem(PROBLEM).digest
    reference = problem_dir() / "reference_gemm.c"
    original = reference.read_bytes()
    try:
        reference.write_bytes(original + b"\n/* drift */\n")
        assert load_problem(PROBLEM).digest != before, (
            "editing the frozen reference did not move the problem digest")
        with pytest.raises(ValueError, match="registered question has changed"):
            NativePerfDriver().prepare(
                _Manifest(problem_sha256=before), _Request())
    finally:
        reference.write_bytes(original)
    assert load_problem(PROBLEM).digest == before


def test_the_driver_digest_covers_the_instrument():
    """What measures, as opposed to what is measured.

    A driver digest over some of the instrument is a pin that misses the rest:
    the measurement loop decides the numbers as much as the reference does.
    """
    before = perf_driver_digest()
    for name in ("native_perf_measure.py", "native_perf_common.py",
                 "problems.py", "native_perf_family.py"):
        path = CORE / "ari" / "assurance" / name
        original = path.read_bytes()
        try:
            path.write_bytes(original + b"\n# drift\n")
            assert perf_driver_digest() != before, (
                f"editing {name} did not move the driver digest")
        finally:
            path.write_bytes(original)
    assert perf_driver_digest() == before


def test_a_deleted_instrument_file_fails_loudly_rather_than_leaving_the_digest():
    """Skip-if-absent would make deleting one of these invisible to every pin."""
    import ari.assurance.drivers.perf as perf_mod

    real = Path(perf_mod.__file__).resolve().parent.parent / "native_perf_measure.py"
    original = real.read_bytes()
    try:
        real.unlink()
        with pytest.raises(FileNotFoundError, match="native_perf_measure.py"):
            perf_driver_digest()
    finally:
        real.write_bytes(original)


def test_the_scaffolding_is_present_and_compilable_in_core():
    """The point of the move: a registered harness must not need a workspace."""
    kdir = problem_dir()
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


#: The image the fixtures agree on. ``prepare`` now refuses a request whose
#: container identity is absent or is not the one the manifest pins, so the pair
#: below has to name the same image for every OTHER refusal to be reachable --
#: a fixture that left them disagreeing would make each of those tests pass on
#: the container message instead of the one it was written for.
_PINNED_IMAGE = "sha256:" + "a" * 64


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
        # The problem rides in the manifest's ``oracle`` slot: it is what decides
        # both what a right answer is and what the ratio is against, and using an
        # existing slot means the frozen 46-field manifest did not have to grow
        # a field to make problems free.
        from ari.assurance.problems import load_problem
        loaded = load_problem(kw.get("problem_revision", PROBLEM))
        self.oracle = _Asset(loaded.definition.revision,
                             kw.get("problem_sha256", loaded.digest))
        self.kind = kw.get("kind", "benchmark")
        self.network_policy = kw.get("network_policy", "deny")
        self.credential_policy = kw.get("credential_policy", "none")
        self.id = kw.get("id", "hpc/gemm-performance")
        # A performance manifest must pin the placement its evidence was taken
        # on, and prepare() refuses a host whose placement differs. These
        # pairings are about everything ELSE prepare checks, so the fixture
        # pins THIS host; the two placement refusals below move the pin rather
        # than the machine, which is the only way to test them anywhere.
        here = measurement_placement()
        self.registered_placement = kw.get("registered_placement", {
            "machine": here["machine"], "thread_budget": here["thread_budget"]})
        self.container = SimpleNamespace(
            resolved_digest=kw.get("container_digest", _PINNED_IMAGE))


class _Atom:
    def __init__(self, property_id="performance-regression"):
        self.property_id = property_id
        self.method = "benchmark-comparison"
        self.tier = "validate"
        self.scope = {}
        self.atom_digest = "sha256:" + "0" * 64


class _Exec:
    def __init__(self, container=_PINNED_IMAGE):
        self.network = "deny"
        self.container = (None if container is None
                          else SimpleNamespace(digest=container))


class _Request:
    def __init__(self, atoms=None, container=_PINNED_IMAGE):
        self.property_atoms = tuple(atoms or (_Atom(),))
        self.execution_request = _Exec(container)
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


@pytest.mark.parametrize("carried", [None, "sha256:" + "b" * 64],
                         ids=["no-container", "another-image"])
def test_prepare_refuses_a_request_that_did_not_name_the_pinned_image(carried):
    """The image is part of what was registered, and nothing downstream re-asks.

    ``runner`` stamps the attestation's ``container_digest`` from the MANIFEST
    rather than from the execution, and its only cross-check asks that the
    RESULT's container equals the REQUEST's -- a pair that agree with each other
    however far both are from the manifest. So this refusal is the only place
    the two can be compared, which is why both siblings have carried it since
    they were written and why its absence here let a request run in any image,
    or in none, and still produce an attestation naming the pinned one.

    ``None`` is tested beside a wrong digest because the field is OPTIONAL: an
    unset container is the reading that a bare ``!=`` comparison would have
    let through as "no disagreement".
    """
    with pytest.raises(ValueError, match="pinned container identity"):
        NativePerfDriver().prepare(_Manifest(), _Request(container=carried))


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
    values = dict(problem_id="gemm-dense-fp64",
                  problem_revision=PROBLEM,
                  problem_digest="sha256:" + "1" * 64,
                  family="gemm", tier="validate", verdict="pass",
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
    d = problem_dir()
    return compile_binary(include_dir=d, driver=d / "gemm_main.c",
                          entry_point="gemm", role="candidate", source=source,
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
    lines = (CORE / "ari" / "assurance" / "native_perf_measure.py"
             ).read_text().splitlines()
    start = next(i for i, l in enumerate(lines) if "for index in range(reps):" in l)
    launches = [i for i, l in enumerate(lines[start:], start) if "run_timed(" in l]
    oracle = next(i for i, l in enumerate(lines[start:], start)
                  if "family.check(" in l)
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

    from ari.assurance.native_perf_measure import verify_performance
    params = inspect.signature(verify_performance).parameters
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


def test_prepare_refuses_a_performance_harness_that_pins_no_placement():
    """A timed verdict is a statement about a machine. The same commit and the
    same clean worktree scored 15/15 on one exclusive node and 13/15 on another,
    where the clean control did not resolve -- so an unplaced attestation would
    have covered both."""
    with pytest.raises(ValueError, match="must pin the placement"):
        NativePerfDriver().prepare(_Manifest(registered_placement={}), _Request())


def test_prepare_refuses_a_host_that_is_not_the_registered_placement(monkeypatch):
    """The pin has to be checked, not merely carried."""
    monkeypatch.setenv("ARI_PERF_THREADS", "2")
    with pytest.raises(ValueError, match="not the placement"):
        NativePerfDriver().prepare(
            _Manifest(registered_placement={"thread_budget": "3"}), _Request())


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


def test_a_non_finite_residual_does_not_crash_the_report():
    """A wrong candidate must not be able to turn its own fail into an outage.

    The family oracle answers `inf` for an output containing an infinity and
    `nan` for one that leaves the frozen driver's poisoned buffer in place.
    Neither is JSON, and `max_rel_error` was a bare float, so building the
    report raised "Out of range float values are not JSON compliant" INSIDE the
    verifier -- a non-zero worker exit, which the driver reports as
    `infrastructure_error` rather than as the failure it is.
    """
    from ari.assurance.native_perf_common import finite_ratio

    assert finite_ratio(float("inf")) is None
    assert finite_ratio(float("nan")) is None
    assert finite_ratio(2.5) == 2.5

    for bad in (float("inf"), float("nan")):
        repetition = PerfRepetitionV1(
            index=0, input_seed=0, credited_seconds=1.0, reference_seconds=1.0,
            speedup=1.0, correct=False, max_rel_error=finite_ratio(bad))
        assert repetition.max_rel_error is None
        case = PerfCaseResultV1(
            case_id="x", verdict="fail", detail=f"residual {bad}", speedup=0.0,
            repetitions_requested=1, repetitions=(repetition,))
        # The whole report must survive the round trip the driver performs.
        report = _report(case_results=(case,), verdict="fail")
        assert NativePerfReportV1.model_validate_json(
            report.model_dump_json()).report_digest == report.report_digest


def test_a_repetition_must_STATE_its_residual_even_when_there_was_none():
    """Nullable, not omissible -- those are two different contracts.

    A repetition record is appended only after the family oracle has answered for
    it, so there is no repetition for which the question was never put: an
    omission is a producer that forgot, and a field that fills itself in with
    ``None`` would answer "the oracle's answer was not a finite number" on that
    producer's behalf. That is the defect nullability was introduced to end --
    a default dressed as a measurement -- reintroduced one line lower.
    """
    stated = dict(index=0, input_seed=0, credited_seconds=1.0,
                  reference_seconds=1.0, speedup=1.0, correct=True,
                  max_rel_error=1e-7)
    assert PerfRepetitionV1(**stated).max_rel_error == pytest.approx(1e-7)
    assert PerfRepetitionV1(**{**stated, "max_rel_error": None}).max_rel_error is None
    with pytest.raises(Exception):
        PerfRepetitionV1(**{k: v for k, v in stated.items() if k != "max_rel_error"})


def test_the_shipped_schema_is_the_one_this_model_generates():
    """A manifest pins this FILE's bytes as the contract the driver emits, so a
    model that moves without it makes ``result_schema_conformance`` verify a
    schema ARI no longer keeps. Measured: ``max_rel_error`` became nullable and
    ``sandbox`` was added to the report, and the shipped schema declared neither.

    The three envelope keys are the generating script's and not the model's --
    ``$id`` names the report type, ``$schema`` the dialect, and the root
    description says why the file exists -- so they are required to be present
    and are not compared against the model's own docstring.
    """
    shipped = json.loads((CORE / "ari" / "schemas"
                          / "native_perf_report_v1.schema.json").read_text())
    generated = NativePerfReportV1.model_json_schema()
    for key in ("$id", "$schema", "description"):
        assert shipped.get(key), f"the shipped schema lost {key}"
        generated[key] = shipped[key]
    assert shipped == generated, (
        "the shipped schema no longer describes NativePerfReportV1; regenerate "
        "it from the model rather than editing the JSON")
    # And the pinned contract still REQUIRES the field it made nullable.
    assert "max_rel_error" in shipped["$defs"]["PerfRepetitionV1"]["required"]


def test_the_report_carries_no_host_path():
    """The launch's sandbox record names the per-run temporary directory.

    `writable_root` is a HOST FILESYSTEM PATH, and this report is published and
    digested evidence, so carrying it writes machine identity into an
    attestation -- and it changes every run, which makes the report digest
    non-reproducible.
    """
    from ari.assurance.native_perf_common import (SANDBOX_RECORD_KEYS,
                                                  sandbox_record)

    observed = {"filesystem_isolation": True, "mechanism": "landlock",
                "landlock_abi": 6, "does_not_restrict": ["fork"],
                "writable_root": "/tmp/tmpEXAMPLE"}
    kept = sandbox_record(observed)
    assert "writable_root" not in kept
    assert set(kept) == set(SANDBOX_RECORD_KEYS)



# --- the profiler: a diagnostic that can never become a verdict -----------------

def _profiled_pairs():
    """Every problem that declares a profiled driver, as (revision, scored, profiled)."""
    from ari.assurance.problems import load_problem, registered_problems

    out = []
    for revision in registered_problems():
        loaded = load_problem(revision)
        scaffolding = loaded.definition.scaffolding
        if scaffolding.profiled_driver:
            out.append(pytest.param(
                loaded.path(scaffolding.driver),
                loaded.path(scaffolding.profiled_driver),
                id=loaded.definition.id))
    assert out, "no problem declares a profiled driver"
    return out


@pytest.mark.parametrize("scored_path,profiled_path", _profiled_pairs())
def test_the_profiled_driver_reduces_to_the_scored_driver(scored_path, profiled_path):
    """Delete every /*GATE*/ line and the SCORED driver must come back exactly.

    The profiled driver is a checked-in copy; without this the two diverge the
    first time the timing semantics change and the profile keeps describing the
    old one while looking current. Parametrized over every problem, because the
    pair can drift per problem and a gemm-only check would not notice.
    """
    stripped = "".join(l for l in profiled_path.read_text().splitlines(keepends=True)
                       if "/*GATE*/" not in l)
    assert stripped == scored_path.read_text()


@pytest.mark.parametrize("scored_path,profiled_path", _profiled_pairs())
def test_the_gate_brackets_exactly_the_timed_call(scored_path, profiled_path):
    """The counted region must be the timed call and nothing else.

    Counting the whole process was measured at 7.16x the region's cycles, so a
    gate that drifted outside the timer would report a different program's
    behaviour under the scored program's name.
    """
    lines = profiled_path.read_text().splitlines()
    enter = next(i for i, l in enumerate(lines) if "gate_enter();" in l)
    t0 = next(i for i, l in enumerate(lines) if l.startswith("    double t0 = now_sec();"))
    el = next(i for i, l in enumerate(lines)
              if l.startswith("    double elapsed = now_sec() - t0;"))
    leave = next(i for i, l in enumerate(lines) if "gate_leave();" in l)
    assert enter < t0 < el < leave
    assert el - t0 == 2, "something moved into the timed window"


def test_the_counter_tool_is_inside_the_driver_digest():
    """Counting the whole process was measured at 7.16x the region's cycles, so
    the tool that scopes the region decides the numbers as much as the kernel."""
    before = perf_driver_digest()
    source = kernels_root() / "tools" / "region_counters.c"
    assert source.is_file()
    original = source.read_bytes()
    try:
        source.write_bytes(original + b"\n/* drift */\n")
        assert perf_driver_digest() != before
    finally:
        source.write_bytes(original)


def test_a_profile_can_never_become_a_score():
    """A profile is a second measurement channel with none of the verdict path's
    anti-gaming surface."""
    from ari.assurance.native_perf_profile import NativePerfProfileV1

    fields = NativePerfProfileV1.model_fields
    assert fields["scored"].default is False
    for scored_key in ("verdict", "speedup", "valid", "families", "case_results",
                       "regression_threshold"):
        assert scored_key not in fields, f"the profile carries {scored_key}"


def test_the_profile_says_which_problems_and_which_tool():
    from ari.assurance.native_perf_profile import NativePerfProfileV1

    fields = NativePerfProfileV1.model_fields
    for key in ("dataset_revision", "dataset_sha256", "counter_tool",
                "environment", "placement", "ratio_spread", "reps"):
        assert key in fields


def test_the_profile_spread_is_per_case():
    """Two shapes have genuinely different IPC; pooling them reports that
    difference as measurement noise."""
    from ari.assurance.native_perf_profile import ProfilePointV1, _spread

    points = [
        ProfilePointV1(case_id="a", input_seed=0, counters={"ratios": {"ipc": 1.0}}),
        ProfilePointV1(case_id="a", input_seed=1, counters={"ratios": {"ipc": 1.02}}),
        ProfilePointV1(case_id="b", input_seed=0, counters={"ratios": {"ipc": 2.0}}),
        ProfilePointV1(case_id="b", input_seed=1, counters={"ratios": {"ipc": 2.02}}),
    ]
    out = _spread(points, "ipc")
    assert set(out) == {"a", "b"}
    assert out["a"]["relative_spread"] < 0.05 and out["b"]["relative_spread"] < 0.05


def test_a_prebuilt_counter_tool_is_recorded_as_such(tmp_path, monkeypatch):
    """Recording the SOURCE digest beside someone else's executable made the one
    field a reader would use to identify the tool a false statement."""
    from ari.assurance.native_perf_profile import build_counter_tool

    fake = tmp_path / "prebuilt"
    fake.write_bytes(b"not really a counter tool")
    monkeypatch.setenv("ARI_REGION_COUNTERS", str(fake))
    path, record = build_counter_tool(tmp_path)
    assert path == fake
    assert record["built_from_source"] is False
    assert record["binary_sha256"] != record["source_sha256"]
