"""The correctness Harness that fits a PINNED PROBLEM's own contract.

Every registered correctness Harness verified the ARI-native ABI out of a shared
library; every pinned problem submits C source against its own header. Nothing
verified the second, so a governed run over a problem reached the one correctness
Harness available to it, could not load its target, and reported 33 failing cases
with every error 0.0 -- a mismatch dressed as a verdict about the candidate.

These tests hold the two halves of the fix in place: that the new instrument
decides what it claims to decide, and that adding it left the three already
registered Harnesses pinned to the drivers they were registered against.
"""

from __future__ import annotations

import pathlib

import pytest
import yaml

from ari.assurance.drivers.native import native_driver_digest
from ari.assurance.drivers.perf import perf_driver_digest
from ari.assurance.drivers.problem_correctness import (
    PROBLEM_CORRECTNESS_DRIVER_REVISION,
    ProblemCorrectnessDriver,
    problem_correctness_driver_digest,
)
from ari.assurance.native_problem_correctness import verify_problem_correctness
from ari.assurance.problems import load_problem

PROBLEM = "gemm-dense-fp64/v1@2026q3"
#: 256x256x256. The oracle is shape-generic, so the cheapest registered set is
#: the honest one to exercise it on.
SMOKE = "native-perf-gemm-cases/v1@smoke"
BUILTIN = (pathlib.Path(__file__).resolve().parents[1]
           / "config" / "harnesses" / "builtin")
MANIFEST = BUILTIN / "hpc_gemm_problem_correctness.yaml"


@pytest.fixture(scope="module")
def problem():
    return load_problem(PROBLEM)


def _verify(problem, source, **kwargs):
    return verify_problem_correctness(problem, source, tier="screen",
                                      dataset_revision=SMOKE, **kwargs)


# --- adding this must not have unpinned anything -------------------------------

def test_the_existing_harnesses_still_pin_the_drivers_they_were_registered_against():
    """The whole reason this driver has its own digest.

    A problem-shaped correctness verifier placed inside ``native_driver_digest``
    would have re-registered the three ARI-native Harnesses for a file none of
    them read. The performance driver's docstring worked this out first; this
    asserts the outcome rather than the intention.
    """
    shipped = {path.name: yaml.safe_load(path.read_text(encoding="utf-8"))
               for path in sorted(BUILTIN.glob("*.yaml"))}
    native = [m for m in shipped.values()
              if m["driver"]["revision"] == "ari.assurance.native-hpc/v1"]
    assert len(native) == 3, "the three ARI-native correctness harnesses"
    for manifest in native:
        assert manifest["driver"]["sha256"] == native_driver_digest()
    perf = [m for m in shipped.values()
            if m["driver"]["revision"] == "ari.assurance.native-perf/v1"]
    assert perf and all(m["driver"]["sha256"] == perf_driver_digest() for m in perf)


def test_the_new_manifest_pins_the_driver_that_exists():
    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["driver"]["revision"] == PROBLEM_CORRECTNESS_DRIVER_REVISION
    assert manifest["driver"]["sha256"] == problem_correctness_driver_digest()


def test_the_new_manifest_does_not_reuse_the_ari_native_contract_name():
    """The collision is the defect, so the fix must not reproduce it.

    ``gemm-c-abi/v1`` already means "resolves ari_gemm_f32/f64 out of a shared
    library". Naming the pinned problem instead makes the interface contract and
    the oracle pin the same object, so they cannot come to disagree.
    """
    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["target_interface_contract"] != "gemm-c-abi/v1"
    assert manifest["target_interface_contract"] == f"problem:{PROBLEM}"
    assert manifest["oracle"]["revision"] == PROBLEM
    assert manifest["oracle"]["sha256"] == load_problem(PROBLEM).digest
    # fp64 only, because that is what gemm_kernel.h declares. The ARI-native
    # verifier declares float32 too, which is one of the ways the two contracts
    # differ while sharing a name.
    assert tuple(manifest["supported_dtypes"]) == ("float64",)


def test_the_new_manifest_pins_no_placement():
    """A residual bound is not a statement about a machine.

    The performance manifest must pin one and its driver refuses to run off it.
    Pinning one here would claim something that cannot vary, and would make this
    Harness unusable on every node but the one it was registered on for no
    reason anybody could state.
    """
    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["registered_placement"] == {}


# --- what the instrument decides ------------------------------------------------

def test_the_frozen_reference_passes_its_own_problem(problem):
    report = _verify(problem, problem.path(problem.definition.scaffolding.reference))
    assert report.verdict == "pass"
    assert report.property_verdicts == {"numerical-equivalence": "pass",
                                        "interface-conformance": "pass"}
    assert report.problem_digest == problem.digest


def test_a_wrong_kernel_fails_on_the_residual_bound_and_still_conforms(problem):
    """The two properties are two claims, and this candidate breaks one of them.

    ``wrong_gemm.c`` writes the right number of elements and the wrong numbers.
    Reporting one overall verdict against both atoms is how a run would learn
    "the interface was wrong" from a Harness that only checked the numbers.
    """
    report = _verify(problem,
                     problem.path(problem.definition.scaffolding.negative_control_wrong))
    assert report.verdict == "fail"
    assert report.property_verdicts["numerical-equivalence"] == "fail"
    assert report.property_verdicts["interface-conformance"] == "pass"
    assert "residual bound" in report.case_results[0].detail
    assert report.case_results[0].worst_residual_ratio > 1.0


def test_a_correct_but_slow_kernel_passes(problem):
    """The specificity direction, and the reason this is not a stopwatch.

    ``slow_gemm.c`` is the performance harness's negative control: it must FAIL
    there and PASS here. An instrument that refused it would be scoring speed
    while reporting correctness, and every verdict it emitted would be
    unreadable.
    """
    report = _verify(problem,
                     problem.path(problem.definition.scaffolding.negative_control_slow))
    assert report.verdict == "pass"
    assert report.property_verdicts["numerical-equivalence"] == "pass"


def test_a_kernel_that_exports_an_extra_symbol_is_refused(tmp_path, problem):
    source = tmp_path / "extra_symbol.c"
    source.write_text(
        problem.path(problem.definition.scaffolding.seed_candidate)
        .read_text(encoding="utf-8")
        + "\nint sneaky_scratch = 0;\n", encoding="utf-8")
    report = _verify(problem, source)
    assert report.verdict == "fail"
    assert report.interface_error and "sneaky_scratch" in report.interface_error
    # An object audit failure is not a compiler failure, and conflating them
    # would report a contract violation as an outage.
    assert report.build_error is None


def test_a_candidate_that_does_not_compile_is_a_result_not_an_outage(tmp_path, problem):
    source = tmp_path / "broken.c"
    source.write_text("void gemm(int n) { this is not c }\n", encoding="utf-8")
    report = _verify(problem, source)
    assert report.verdict == "fail"
    assert report.build_error and report.interface_error is None
    assert report.case_results == ()


def test_a_kernel_that_faults_is_not_reported_as_an_interface_violation(
        tmp_path, problem):
    """A crash is a failure this verifier reports without claiming to locate.

    The aggregate used to infer "wrote the wrong number of elements" from
    ``written != expected``, and a candidate that never ran wrote nothing -- so a
    segfault was reported as a statement about the candidate's interface that
    nothing had established. Equivalence fails; conformance is left alone.
    """
    source = tmp_path / "faulting.c"
    source.write_text(
        '#include "gemm_kernel.h"\n'
        "void gemm(int n, int m, int p, const double *A, const double *B,\n"
        "          double *C) { (void)n; (void)m; (void)p; (void)A; (void)B;\n"
        "  (void)C; *(volatile int *)0 = 1; }\n", encoding="utf-8")
    report = _verify(problem, source)
    assert report.verdict == "fail"
    assert report.property_verdicts["numerical-equivalence"] == "fail"
    assert report.property_verdicts["interface-conformance"] == "pass"
    assert report.case_results[0].output_elements_written == 0


def test_the_report_carries_no_timing(problem):
    """A correctness verdict that carried seconds would be read as a performance
    result taken without a denominator."""
    report = _verify(problem, problem.path(problem.definition.scaffolding.reference))
    fields = set(report.model_dump(mode="json"))
    assert not {name for name in fields
                if "second" in name or "speedup" in name or "elapsed" in name}


# --- the declaration a problem candidate can actually make ----------------------

def test_a_problem_candidate_declares_a_contract_it_keeps_and_reaches_this_harness(
        tmp_path, problem):
    """End to end, the gap this Harness was authored to close.

    ``declare_target`` used to have exactly one contract to offer a candidate --
    the ARI-native shared-library ABI -- so a kernel written against the
    problem's own header either falsely claimed to keep it (33/33 missing-symbol
    failures read as a verdict) or, once that claim was checked, declared nothing
    at all and left the node unverifiable. It now declares the contract the
    candidate does keep, and exactly one shipped Harness accepts it.
    """
    import shutil

    from ari.assurance.models import HarnessManifestV1, HarnessTargetDeclarationV1
    from ari.assurance.request import harness_inapplicability
    from ari.evaluator.assurance_measure import declare_target

    definition = problem.definition
    shutil.copy2(problem.path(definition.scaffolding.contract_header),
                 tmp_path / definition.scaffolding.contract_header)
    shutil.copy2(problem.path(definition.scaffolding.seed_candidate),
                 tmp_path / definition.score_inputs[0])

    document = declare_target(tmp_path, problem)
    assert document["logical_name"] == definition.score_inputs[0]
    assert document["target_kind"] == "benchmark-submission"
    assert document["interface_contract"] == f"problem:{definition.revision}"

    declaration = HarnessTargetDeclarationV1.model_validate(document)
    applicable = sorted(
        path.name for path in BUILTIN.glob("*.yaml")
        if not harness_inapplicability(
            manifest=HarnessManifestV1.model_validate(
                yaml.safe_load(path.read_text(encoding="utf-8"))),
            declaration=declaration)
    )
    assert applicable == ["hpc_gemm_problem_correctness.yaml"], (
        "a problem candidate must reach the Harness written for its contract, "
        "and only that one")


# --- what prepare() must refuse -------------------------------------------------

class _Asset:
    def __init__(self, revision, sha256):
        self.revision = revision
        self.sha256 = sha256


class _ManifestContainer:
    """The manifest names it ``resolved_digest``; the request names it
    ``digest``. Two names for the thing whose equality prepare() checks."""

    def __init__(self, resolved_digest):
        self.resolved_digest = resolved_digest


class _RequestContainer:
    def __init__(self, digest):
        self.digest = digest


class _Manifest:
    def __init__(self, **kw):
        from ari.assurance.native_perf_common import load_case_set
        shipped = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
        self.driver = _Asset(kw.get("driver_revision",
                                    PROBLEM_CORRECTNESS_DRIVER_REVISION),
                             kw.get("driver_sha256",
                                    problem_correctness_driver_digest()))
        dataset_revision = kw.get("dataset_revision", SMOKE)
        _set, digest = load_case_set(dataset_revision)
        self.dataset = _Asset(dataset_revision, kw.get("dataset_sha256", digest))
        loaded = load_problem(kw.get("problem_revision", PROBLEM))
        self.oracle = _Asset(loaded.definition.revision,
                             kw.get("problem_sha256", loaded.digest))
        self.kind = kw.get("kind", "artifact_verifier")
        self.accepts_external_target = kw.get("accepts_external_target", True)
        self.network_policy = kw.get("network_policy", "deny")
        self.credential_policy = kw.get("credential_policy", "none")
        self.container = _ManifestContainer(
            shipped["container"]["resolved_digest"])
        self.id = "hpc/gemm-dense-fp64-problem-correctness"
        # Deliberately absent for a deterministic verifier; see the manifest test
        # above. Present here as {} so a prepare() that grew a placement check
        # would fail loudly rather than read a missing attribute.
        self.registered_placement = {}


class _Atom:
    def __init__(self, property_id="numerical-equivalence"):
        self.property_id = property_id
        self.method = "differential-testing"
        self.tier = "screen"
        self.scope = {}
        self.atom_digest = "sha256:" + "0" * 64


class _Exec:
    network = "deny"

    def __init__(self, container):
        self.container = container


class _Request:
    def __init__(self, atoms=None, container_digest=None):
        self.property_atoms = tuple(atoms or (_Atom(),))
        shipped = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
        self.execution_request = _Exec(_RequestContainer(
            container_digest or shipped["container"]["resolved_digest"]))
        self.run_id = "run"


def test_prepare_accepts_a_well_formed_request():
    ProblemCorrectnessDriver().prepare(_Manifest(), _Request())


def test_prepare_does_not_require_a_registered_placement():
    """The difference from the performance driver, asserted so it stays deliberate.

    ``NativePerfDriver.prepare`` refuses a manifest that pins no placement. If
    this driver ever grew the same check it would refuse its own shipped
    manifest, and the failure would look like a broken Harness rather than a
    copied requirement.
    """
    ProblemCorrectnessDriver().prepare(_Manifest(registered_placement={}),
                                       _Request())


@pytest.mark.parametrize("manifest_kw,atoms,expected", [
    ({"driver_revision": "other/v1"}, None, "another driver revision"),
    ({"driver_sha256": "sha256:" + "1" * 64}, None, "driver bytes drifted"),
    ({"kind": "benchmark"}, None, "external artifact verifier"),
    ({"accepts_external_target": False}, None, "external artifact verifier"),
    ({"network_policy": "allowlisted"}, None, "network-denied"),
    ({"credential_policy": "scoped"}, None, "network-denied"),
    ({"problem_sha256": "sha256:" + "3" * 64}, None,
     "the registered question has changed"),
    ({"dataset_sha256": "sha256:" + "4" * 64}, None,
     "the registered problem set has changed"),
    (None, (_Atom("performance-regression"),), "does not decide"),
])
def test_prepare_refuses(manifest_kw, atoms, expected):
    with pytest.raises(ValueError, match=expected):
        ProblemCorrectnessDriver().prepare(_Manifest(**(manifest_kw or {})),
                                           _Request(atoms))


def test_prepare_refuses_a_request_that_runs_in_another_container():
    """The container is pinned on the manifest and asserted on the request.

    A verifier that ran outside the image it was registered in is measuring a
    toolchain nobody pinned; the compiler is part of what decides whether a
    kernel is right.
    """
    with pytest.raises(ValueError, match="pinned container identity"):
        ProblemCorrectnessDriver().prepare(
            _Manifest(), _Request(container_digest="sha256:" + "2" * 64))


def test_prepare_refuses_a_case_set_from_another_family():
    with pytest.raises(ValueError, match="is for family"):
        ProblemCorrectnessDriver().prepare(
            _Manifest(dataset_revision="native-perf-stencil-cases/v1@smoke"),
            _Request())
