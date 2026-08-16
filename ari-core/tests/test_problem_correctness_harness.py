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
    case = report.case_results[0]
    # NOT 0. Nothing was read, so there is no element count and no residual to
    # report; this used to publish the loop's initialisers (0 elements, 0.0
    # residual, deterministic=True) as though they had been observed.
    assert case.output_elements_written is None
    assert case.worst_residual_ratio is None
    assert case.repeat_identical is None
    assert case.repetitions_completed == 0
    assert "did not complete" in case.detail


def test_a_candidate_writing_infinities_is_a_failure_not_an_outage(tmp_path, problem):
    """A wrong candidate must not be able to crash the verifier.

    The family oracle answers `inf` for an output containing an infinity and
    `nan` for one left at the driver's poisoned buffer. Neither is JSON, and
    `worst_residual_ratio` was a bare float, so building the report raised "Out
    of range float values are not JSON compliant" INSIDE the verifier. In the
    worker that is a non-zero exit, which the driver reports as
    `infrastructure_error` -- so a candidate writing infinities escaped its fail
    verdict and was recorded as the harness having broken. The registered
    `hpc/gemm-performance` harness still has this defect in `PerfRepetitionV1`.
    """
    source = tmp_path / "inf_gemm.c"
    source.write_text(
        '#include "gemm_kernel.h"\n'
        "void gemm(int n, int m, int p, const double *A, const double *B,\n"
        "          double *C) { (void)A; (void)B; (void)p;\n"
        "  for (int i = 0; i < n*m; ++i) C[i] = 1.0/0.0; }\n", encoding="utf-8")
    report = _verify(problem, source)
    assert report.verdict == "fail"
    case = report.case_results[0]
    assert case.worst_residual_ratio is None, "a non-finite ratio is not a number"
    assert "failed the residual bound" in case.detail
    assert "non-finite" in case.detail
    # And the whole report must survive the round trip the driver performs.
    from ari.assurance.native_problem_correctness import (
        NativeProblemCorrectnessReportV1)
    assert NativeProblemCorrectnessReportV1.model_validate_json(
        report.model_dump_json()).report_digest == report.report_digest


def test_the_report_identifies_which_candidate_was_verified(problem):
    """Three different candidates must not produce one report.

    Every other field is about the problem, the case set, the toolchain or the
    machine, so before `candidate_digest` existed the frozen reference, the
    correct-but-slow control and the naive seed produced BYTE-IDENTICAL reports
    and therefore one `report_digest` -- which a manifest pins as
    `negative_control_report_digest` and an attestation cites to say what was
    verified.
    """
    scaffolding = problem.definition.scaffolding
    digests = {}
    for name in (scaffolding.reference, scaffolding.negative_control_slow,
                 scaffolding.seed_candidate):
        report = _verify(problem, problem.path(name))
        assert report.verdict == "pass", f"{name} should pass"
        digests[name] = report.report_digest
    assert len(set(digests.values())) == 3, (
        f"distinct candidates produced the same report: {digests}")


def test_a_compile_error_quoting_the_audit_is_not_a_proven_interface_violation(
        tmp_path, problem):
    """The classification must not read text the candidate controls.

    A compile failure's message embeds the compiler's stderr, so matching the
    audit's wording anywhere in it let a candidate label its own build failure
    as a proven contract violation -- a finding about the artifact that nothing
    established.
    """
    source = tmp_path / "quoting.c"
    source.write_text(
        '#include "gemm_kernel.h"\n'
        '#error candidate kernel exports symbols other than \'gemm\'\n',
        encoding="utf-8")
    report = _verify(problem, source)
    assert report.verdict == "fail"
    assert report.build_error is not None
    assert report.interface_error is None, (
        "a compile failure quoting the audit is still a compile failure")


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
    # EVERY Harness written for this problem's contract, which is more than one
    # and is meant to be. A lock is resolved for a CONTRACT and a node produces
    # ONE artifact, so several Harnesses legitimately apply to the same
    # candidate as long as each decides a different property: this one checks
    # the numbers and the interface, the performance Harness times it. The
    # assertion here used to demand exactly one, which was true only while the
    # performance Harness still named the ARI-native ABI it could not verify.
    #
    # What must hold is that NOTHING WHICH CANNOT LOAD THE CANDIDATE is
    # reached -- the three ARI-native verifiers resolve
    # ari_gemm_f32/ari_gemm_f64 out of a shared library and would report 33
    # missing-symbol failures as a verdict about it.
    assert applicable == ["hpc_gemm_performance.yaml",
                          "hpc_gemm_problem_correctness.yaml"], (
        "a problem candidate must reach exactly the Harnesses written for its "
        "contract")
    decided = set()
    for name in applicable:
        manifest = yaml.safe_load((BUILTIN / name).read_text(encoding="utf-8"))
        properties = {p["property_id"] for p in manifest["properties"]}
        assert not (decided & properties), (
            f"{name} decides a property another applicable Harness already "
            f"decides: {sorted(decided & properties)}")
        decided |= properties


# --- the resolver must actually SELECT it ---------------------------------------

class _Tolerance:
    @staticmethod
    def model_dump(mode=None):
        return {"absolute": 1e-9, "relative": 1e-9}


class _Provenance:
    source = "llm"
    source_digest = None


class _Metric:
    correctness_required = True
    contract_digest = "sha256:" + "a" * 64
    tolerance = _Tolerance
    formula_provenance = _Provenance
    confidence = 0.9


class _ResearchContract:
    metric_contract = _Metric
    contract_digest = "sha256:" + "b" * 64


def _selection(artifact_target_kind):
    """Which shipped manifests a correctness requirement resolves to."""
    from ari.assurance.contract import (build_verification_contract,
                                        load_property_vocabulary,
                                        load_tolerance_policy)
    from ari.assurance.models import HarnessManifestV1
    from ari.assurance.resolver import _coverage, normalize_requirements
    from ari.protocols.scientific_requirements import EnvironmentSnapshotV1

    root = BUILTIN.parent
    vocabulary, digest = load_property_vocabulary(root / "property_vocabulary.yaml")
    policy = load_tolerance_policy(root / "policies" / "hpc-floating-point-v1.yaml")
    environment = EnvironmentSnapshotV1.create(
        features=("landlock", "network-namespace"),
        resource_types=("process", "cpu"))
    contract = build_verification_contract(
        run_id="r", research_contract=_ResearchContract, knowledge_obligations=(),
        property_vocabulary=vocabulary, property_vocabulary_digest=digest,
        tolerance_policy=policy, artifact_target_kind=artifact_target_kind)
    atoms = normalize_requirements(contract)
    selected = {}
    for path in sorted(BUILTIN.glob("*.yaml")):
        manifest = HarnessManifestV1.model_validate(
            yaml.safe_load(path.read_text(encoding="utf-8")))
        # status is settled by registration, which is a separate act; this test
        # is about target-kind resolution, so it asks what WOULD be selected.
        promoted = manifest.model_copy(update={"status": "verified"})
        covered = sorted({atom.property_id for atom in atoms
                          if _coverage(promoted, atom, environment)})
        if covered:
            selected[path.name] = covered
    return sorted({atom.target_kind for atom in atoms}), selected


def test_the_pinned_problem_target_kind_is_derived_not_guessed():
    from ari.assurance.target_abi import problem_target_kind

    definition = load_problem(PROBLEM).definition
    # `gemm` is not one of the gemm family's ABI symbols (ari_gemm_f32/f64), so
    # a candidate keeping this problem's header is a submission.
    assert problem_target_kind(definition.entry_point, definition.family) == (
        "benchmark-submission")
    # A problem whose entry point IS the family ABI keeps the shared-library
    # answer, so this override cannot restamp the three registered harnesses.
    assert problem_target_kind("ari_gemm_f64", "gemm") == "shared-library"
    # An unknown family has no ABI record and cannot be a shared library.
    assert problem_target_kind("whatever", "no-such-family") == "benchmark-submission"


def test_without_a_pinned_problem_nothing_moves():
    """The override is additive: no problem, no change to any existing run."""
    kinds, selected = _selection(None)
    assert kinds == ["shared-library"]
    assert "hpc_gemm_correctness.yaml" in selected


def test_a_pinned_problem_run_resolves_to_the_harness_written_for_it():
    """THE DEFECT THIS FIXES, measured on the shipped catalog.

    `property_vocabulary.yaml` stamps correctness atoms with one target kind per
    property, and that was the whole truth while the only correctness harnesses
    were the three ARI-native ones. With the atom stamped `shared-library`, a
    pinned-problem run resolved its correctness obligation to the ARI-native
    GEMM, SpMM AND Stencil verifiers -- none of which can load a candidate
    written against the problem's own header, all of which would have reported
    missing-symbol failures as verdicts about the candidate -- while the harness
    written for that contract was never selected at all.
    """
    before_kinds, before = _selection(None)
    after_kinds, after = _selection("benchmark-submission")

    assert before_kinds == ["shared-library"]
    assert MANIFEST.name not in before, (
        "regression guard: the harness written for the problem was invisible")
    assert {"hpc_gemm_correctness.yaml", "hpc_spmm_correctness.yaml"} <= set(before)

    assert after_kinds == ["benchmark-submission"]
    assert set(after) == {MANIFEST.name}, (
        "a pinned-problem run must resolve to the Harness written for its "
        "contract, and to nothing that cannot load its candidate")
    assert after[MANIFEST.name] == ["interface-conformance", "numerical-equivalence"]


def test_the_declaration_and_the_resolution_cannot_disagree(tmp_path, problem):
    """THE PROBLEM decides the contract; the artifact only decides whether it keeps it.

    `declare_target` used to ask the built library first: a candidate exporting
    BOTH the problem's entry point and the family's ABI symbols was declared a
    `shared-library`, while the resolver -- which runs before any candidate
    exists and can read only the pinned problem -- had already stamped this
    run's atoms `benchmark-submission`. The resolved Harness would then be
    inapplicable to the declared target, so the node would get no verification
    at all and nothing would report an error.
    """
    from ari.assurance.target_abi import problem_target_kind
    from ari.evaluator.assurance_measure import TargetABIMismatch, declare_target

    definition = problem.definition
    header = definition.scaffolding.contract_header
    kernel = ('void gemm(int n, int m, int p, const double *A, const double *B,\n'
              '          double *C) { (void)n; (void)m; (void)p; (void)A;\n'
              '  (void)B; (void)C; }\n')
    native = "int ari_gemm_f32(void) { return 0; }\nint ari_gemm_f64(void) { return 0; }\n"
    expected = problem_target_kind(definition.entry_point, definition.family)

    for label, body in (("problem contract only", kernel),
                        ("problem contract and native ABI", kernel + native)):
        work = tmp_path / label.replace(" ", "_")
        work.mkdir()
        (work / header).write_bytes(problem.path(header).read_bytes())
        (work / definition.score_inputs[0]).write_text(
            f'#include "{header}"\n' + body, encoding="utf-8")
        document = declare_target(work, problem)
        assert document["target_kind"] == expected, label
        assert document["interface_contract"] == f"problem:{definition.revision}", label

    # And a candidate that does NOT keep the problem's contract is refused,
    # even though it exports a contract some other harness would accept.
    work = tmp_path / "native_only"
    work.mkdir()
    (work / header).write_bytes(problem.path(header).read_bytes())
    (work / definition.score_inputs[0]).write_text(
        f'#include "{header}"\n' + native, encoding="utf-8")
    with pytest.raises(TargetABIMismatch):
        declare_target(work, problem)


def test_admission_derives_the_kind_from_the_pinned_problem(monkeypatch):
    from ari.evaluator.assurance_measure import PROBLEM_ENV
    from ari.rqgm.admission_builder import _pinned_problem_target_kind

    monkeypatch.delenv(PROBLEM_ENV, raising=False)
    assert _pinned_problem_target_kind() is None
    monkeypatch.setenv(PROBLEM_ENV, PROBLEM)
    assert _pinned_problem_target_kind() == "benchmark-submission"
    # A problem that cannot be loaded must not fail admission with a message
    # about target kinds; the evaluator raises it where it can be acted on.
    monkeypatch.setenv(PROBLEM_ENV, "no-such-problem/v1@never")
    assert _pinned_problem_target_kind() is None


# --- the request must launch THIS harness's worker -------------------------------

def _shipped(name):
    from ari.assurance.models import HarnessManifestV1
    return HarnessManifestV1.model_validate(
        yaml.safe_load((BUILTIN / name).read_text(encoding="utf-8")))


class _Declaration:
    def __init__(self, logical_name, target_kind):
        self.logical_name = logical_name
        self.target_kind = target_kind


def test_the_request_launches_the_worker_the_pinned_driver_can_parse():
    """THE DEFECT THIS FIXES, one layer below resolution.

    `build_native_harness_run_request` built one argv -- the ARI-native worker
    -- and derived its `--kind` by string surgery on the harness id. For this
    manifest that yields `--kind gemm-dense-fp64-problem`, which names no
    registered family, and `--library candidate_gemm.c`, which is C source and
    not a library. So a correctly resolved, correctly locked Harness would have
    launched the wrong verifier, whose output its own driver cannot parse, and
    returned `infrastructure_error` on every node.
    """
    from ari.assurance.request import _worker_argv

    argv = _worker_argv(_shipped(MANIFEST.name),
                        _Declaration("candidate_gemm.c", "benchmark-submission"),
                        tier="screen", seed=7)
    assert "ari.assurance.drivers.problem_correctness_worker" in argv
    assert "ari.assurance.drivers.native_worker" not in argv
    # The problem and the case set come from the MANIFEST PINS, not from the
    # harness id: those pins are what `prepare` re-checks.
    assert argv[argv.index("--problem") + 1] == PROBLEM
    assert argv[argv.index("--candidate") + 1] == "candidate_gemm.c"
    assert argv[argv.index("--dataset-revision") + 1] == (
        _shipped(MANIFEST.name).dataset.revision)
    assert "--library" not in argv and "--kind" not in argv


def test_the_request_carries_the_toolchain_the_candidate_declared(tmp_path, problem):
    """A SOURCE target is compiled again by the Harness, so it must be told how.

    Both source-compiling workers take `--compiler` and `--flags` and hand them
    to `resolve_compiler`/`screen_flags` and thence to `compile_binary`; neither
    branch passed either, so the Harness rebuilt the candidate with the
    instrument's defaults and every governed verdict was about a different
    binary from the one that was scored. Measured on this problem: the same
    source with and without its declared `-Ofast -funroll-loops -march=native`
    produced kernel objects of 2080 and 1504 bytes.

    They cannot be read from the workspace -- `input_digests` admits exactly one
    file, the declared target -- so they travel on the declaration, where
    `declaration_digest` binds them.
    """
    import shutil

    from ari.assurance.models import HarnessTargetDeclarationV1
    from ari.assurance.request import _worker_argv
    from ari.evaluator.assurance_measure import declare_target

    definition = problem.definition
    shutil.copy2(problem.path(definition.scaffolding.contract_header),
                 tmp_path / definition.scaffolding.contract_header)
    shutil.copy2(problem.path(definition.scaffolding.seed_candidate),
                 tmp_path / definition.score_inputs[0])
    (tmp_path / "candidate_cc.txt").write_text("gcc\n", encoding="utf-8")
    (tmp_path / "candidate_flags.txt").write_text("-Ofast -funroll-loops\n",
                                                  encoding="utf-8")

    declaration = HarnessTargetDeclarationV1.model_validate(
        declare_target(tmp_path, problem))
    assert declaration.declared_compiler == "gcc"
    assert declaration.declared_flags == "-Ofast -funroll-loops"

    for name in ("hpc_gemm_problem_correctness.yaml", "hpc_gemm_performance.yaml"):
        argv = _worker_argv(_shipped(name), declaration, tier="screen", seed=1)
        assert argv[argv.index("--compiler") + 1] == "gcc", name
        # ONE argument, joined. `['--flags', '-O3']` is read by argparse as an
        # option, so a candidate declaring exactly one flag would fail as a
        # verifier crash rather than as a candidate.
        assert "--flags=-Ofast -funroll-loops" in argv, name
        assert not any(a == "--flags" for a in argv), name


def test_a_candidate_that_declared_no_toolchain_asks_for_none(tmp_path, problem):
    """"Declared no compiler" and "declared the default" are different claims."""
    import shutil

    from ari.assurance.models import HarnessTargetDeclarationV1
    from ari.assurance.request import _worker_argv
    from ari.evaluator.assurance_measure import declare_target

    definition = problem.definition
    shutil.copy2(problem.path(definition.scaffolding.contract_header),
                 tmp_path / definition.scaffolding.contract_header)
    shutil.copy2(problem.path(definition.scaffolding.seed_candidate),
                 tmp_path / definition.score_inputs[0])
    declaration = HarnessTargetDeclarationV1.model_validate(
        declare_target(tmp_path, problem))
    assert declaration.declared_compiler is None
    assert declaration.declared_flags is None
    argv = _worker_argv(_shipped(MANIFEST.name), declaration, tier="screen", seed=1)
    assert not [a for a in argv if a == "--compiler" or a.startswith("--flags")]


def test_the_ari_native_request_is_unchanged():
    """The three registered harnesses must launch exactly what they always did."""
    from ari.assurance.request import _worker_argv

    manifest = _shipped("hpc_gemm_correctness.yaml")
    argv = _worker_argv(manifest,
                        _Declaration("assurance_target.so", "shared-library"),
                        tier="screen", seed=7)
    assert argv[1:] == ["-m", "ari.assurance.drivers.native_worker",
                        "--kind", "gemm", "--library", "assurance_target.so",
                        "--tier", "screen", "--seed", "7"]


#: Shipped manifests declaring a result schema their driver does not emit.
#: EMPTY, and it must stay empty. `hpc/gemm-performance` used to say
#: `ari.native-hpc-verification-report/v1` while `NativePerfDriver` emits
#: `ari.native-perf-report/v1`, so a consumer reading
#: `HarnessRunRequestV1.expected_result_schema` was told to expect a report type
#: that harness never produces.
_KNOWN_SCHEMA_MISMATCH: set[str] = set()

#: Shipped manifests whose `expected_result_schema_digest` is STALE: it is the
#: byte digest of the schema file as it stood at `d303a4c`, the commit these
#: three were registered from, and the file changed afterwards -- the `kind`
#: enum `[gemm, spmm, stencil]` was dropped when families became data-driven, so
#: each of them pins a STRICTER schema than the one ARI now ships.
#:
#: NOT corrected here, and that is the point. All three are REGISTERED with a
#: `human-maintainer` approval that signs over `harness_manifest_digest`; editing
#: the manifest moves that digest and voids a signature no test may forge. The
#: pin records what was registered, and only a re-registration may move it.
#: `result_schema_conformance` now refuses them, so the next registration
#: surfaces this where a human is present to decide.
#: EMPTY, and it must stay empty. All three were re-registered against the
#: schema ARI ships once `result_schema_conformance` learned to compare the
#: manifest; `scripts/rqgm_assurance/repin_and_promote_harness.py check` is the
#: maintained way to ask, and the pre-commit hook runs it.
_STALE_SCHEMA_PIN: set[str] = set()


def test_every_manifest_declares_the_result_schema_its_driver_emits():
    """The manifest names the type, and pins the file, its driver actually emits.

    `result_schema_conformance` used to resolve the schema from the DRIVER's
    declared type and ask only that one exist. The manifest declares the same
    two facts independently -- `expected_result_schema` and
    `expected_result_schema_digest` -- and nothing anywhere compared them:
    `resolver` copies the digest into the lock and no reader checks it. Both
    halves were wrong on the shipped catalog and neither was visible.
    """
    from ari.assurance.drivers import builtin_driver_map
    from ari.assurance.registration_run import result_schema_digest

    drivers = builtin_driver_map()
    mismatched, stale = set(), set()
    for path in sorted(BUILTIN.glob("*.yaml")):
        manifest = yaml.safe_load(path.read_text(encoding="utf-8"))
        driver = drivers.get(manifest["driver"]["revision"])
        assert driver is not None, f"{path.name} pins a driver that does not exist"
        emitted = driver.report_schema_version
        if manifest["expected_result_schema"] != emitted:
            mismatched.add(path.name)
        elif manifest["expected_result_schema_digest"] != result_schema_digest(emitted):
            stale.add(path.name)
    assert mismatched == _KNOWN_SCHEMA_MISMATCH, (
        f"a manifest declares a result schema its pinned driver does not emit: "
        f"{sorted(mismatched ^ _KNOWN_SCHEMA_MISMATCH)}")
    assert stale == _STALE_SCHEMA_PIN, (
        f"the set of manifests pinning a drifted result schema changed: "
        f"{sorted(stale ^ _STALE_SCHEMA_PIN)}. If one was re-registered, drop it "
        f"from _STALE_SCHEMA_PIN; if a new one appeared, it was minted with a "
        f"hand-typed digest instead of result_schema_digest().")


def test_the_drift_surface_covers_every_pin_prepare_refuses_on(tmp_path):
    """`prepare` refuses on four pins; the surface enumerated two.

    It reported the driver digest and the result schema, and not the problem or
    the case set -- both computed from repository bytes exactly like the driver
    digest, and both refused by `prepare` with "the registered question has
    changed" / "the registered problem set has changed". Demonstrated before the
    fix: appending a comment to the pinned problem's frozen reference left the
    surface reporting that harness clean while `prepare` raised.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_repin", pathlib.Path(__file__).resolve().parents[2]
        / "scripts" / "rqgm_assurance" / "repin_and_promote_harness.py")
    repin = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(repin)

    manifest = _shipped(MANIFEST.name)
    pins = set(repin.derived_pins(manifest))
    assert {"driver.sha256", "oracle.sha256", "dataset.sha256"} <= pins

    # A harness whose oracle slot is NOT a pinned problem must not be reported
    # as drifted against a pin that is not of this kind. The three ARI-native
    # manifests pin a generated oracle revision their driver never resolves;
    # treating "cannot resolve" as drift reported all three stale, which a
    # blocking gate would have turned into three harnesses nobody could commit
    # against.
    native = _shipped("hpc_gemm_correctness.yaml")
    assert "oracle.sha256" not in repin.derived_pins(native)
    assert not repin.stale_pins(native).keys() & {"oracle.sha256", "dataset.sha256"}


def test_the_pre_commit_trigger_set_includes_the_question(tmp_path):
    """A commit that edits a problem must be examined, not waved through."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_repin2", pathlib.Path(__file__).resolve().parents[2]
        / "scripts" / "rqgm_assurance" / "repin_and_promote_harness.py")
    repin = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(repin)

    import contextlib, io
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        repin.paths(None)
    listed = set(buffer.getvalue().split())
    assert any(p.startswith("ari-core/config/harnesses/problems/") for p in listed)
    assert any(p.startswith("ari-core/config/harnesses/case_sets/") for p in listed)


def test_the_gate_refuses_a_drifted_result_schema_pin():
    """The mechanism, not just the current values.

    Before this, `expected_result_schema_digest` was carried into the lock and
    read by nobody, so a pin could name any 32 bytes at all. This asserts the
    gate that now compares it, on both a manifest that agrees and one that does
    not -- otherwise the set above would be a list of known-bad values with
    nothing enforcing it.
    """
    from ari.assurance.drivers import builtin_driver_map
    from ari.assurance.models import HarnessManifestV1
    from ari.assurance.registration_gates import GateEvidence, evaluate_gates
    from ari.assurance.registration_run import result_schema_digest, result_schema_for

    def _verdict(manifest):
        driver = builtin_driver_map()[manifest.driver.revision]
        emitted = driver.report_schema_version
        evidence = GateEvidence(
            manifest=manifest, report_schema=result_schema_for(emitted),
            report_schema_version=emitted,
            report_schema_digest=result_schema_digest(emitted))
        return {g.gate_id: g for g in evaluate_gates(evidence)}[
            "result_schema_conformance"]

    good = HarnessManifestV1.model_validate(
        yaml.safe_load(MANIFEST.read_text(encoding="utf-8")))
    assert _verdict(good).passed

    # DRIFTED SYNTHETICALLY, not by naming a shipped manifest that happens to be
    # broken. This test used to point at hpc_gemm_correctness, which WAS drifted
    # -- and then it was re-registered, so the test failed for the best possible
    # reason and had to be rewritten anyway. A gate test should not depend on
    # the catalog being wrong.
    fields = good.model_dump(mode="python", exclude={"manifest_digest"})
    fields["expected_result_schema_digest"] = "sha256:" + "9" * 64
    verdict = _verdict(HarnessManifestV1.create(**fields))
    assert not verdict.passed
    assert "drifted under the pin" in verdict.detail

    # And a manifest naming a report type its driver does not emit.
    fields = good.model_dump(mode="python", exclude={"manifest_digest"})
    fields["expected_result_schema"] = "ari.some-other-report/v1"
    verdict = _verdict(HarnessManifestV1.create(**fields))
    assert not verdict.passed
    assert "but this harness emits" in verdict.detail



def test_an_unknown_driver_cannot_be_launched_at_all():
    """Fail closed. Falling back to the ARI-native worker is the removed bug."""
    from ari.assurance.request import HarnessRequestError, _worker_argv

    manifest = _shipped(MANIFEST.name).model_copy(
        update={"driver": _shipped(MANIFEST.name).driver.model_copy(
            update={"revision": "ari.assurance.not-a-driver/v1"})})
    with pytest.raises(HarnessRequestError, match="no worker is registered"):
        _worker_argv(manifest, _Declaration("x.c", "benchmark-submission"),
                     tier="screen", seed=1)


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


# --- what normalize_result may publish as a measurement -------------------------

class _Stdout:
    relative_path = "stdout.txt"
    digest = "sha256:" + "0" * 64
    media_type = "text/plain"
    logical_role = "stdout"


class _Limits:
    max_output_bytes = 1 << 20


class _Completed:
    status = "completed"
    artifacts = (_Stdout(),)
    limits = _Limits()


class _Workspace:
    def __init__(self, payload):
        self._payload = payload

    def read_bytes(self, relative_path, max_bytes=None):
        return self._payload


def _case(case_id, ratio, verdict="fail"):
    from ari.assurance.native_problem_correctness import (
        ProblemCorrectnessCaseResultV1)

    ran = ratio is not None
    return ProblemCorrectnessCaseResultV1(
        case_id=case_id, verdict=verdict,
        detail="within the residual bound" if ran else "candidate run did not "
                                                       "complete: exit 139",
        worst_residual_ratio=ratio, output_elements_expected=65536,
        output_elements_written=65536 if ran else None,
        repetitions_requested=1, repetitions_completed=1 if ran else 0)


def _normalized(cases, verdict="fail"):
    """Drive the driver over a report the verifier could really have printed."""
    from ari.assurance.native_perf_common import (
        load_case_set, measurement_environment, measurement_placement)
    from ari.assurance.native_problem_correctness import (
        NativeProblemCorrectnessReportV1)

    loaded = load_problem(PROBLEM)
    _set, dataset_digest = load_case_set(SMOKE)
    report = NativeProblemCorrectnessReportV1.create(
        problem_id=loaded.definition.id,
        problem_revision=loaded.definition.revision, problem_digest=loaded.digest,
        family=loaded.definition.family, entry_point=loaded.definition.entry_point,
        candidate_digest="sha256:" + "9" * 64, tier="screen", verdict=verdict,
        case_results=tuple(cases),
        property_verdicts={"numerical-equivalence": verdict,
                           "interface-conformance": "pass"},
        deterministic=True, oracle="gemm-family-residual-bound",
        error_model="per-element backward-error bound (family oracle)",
        build_error=None, interface_error=None, accepted_flags=(),
        rejected_flags=(),
        candidate_toolchain={"resolved_path": "cc", "status": "default"},
        crossed_compiler_boundary=False, dataset_revision=SMOKE,
        dataset_sha256=dataset_digest, environment=measurement_environment(),
        placement=measurement_placement(), sandbox={}, negative_control=False)
    request = _Request()
    request.execution_request.workspace = _Workspace(
        (report.model_dump_json() + "\n").encode("utf-8"))
    return ProblemCorrectnessDriver().normalize_result(
        _Manifest(), request, _Completed()).property_results[0].measurements


def test_a_case_that_measured_no_residual_is_not_published_as_a_perfect_one():
    """A missing residual is not a small one, and 0.0 is the PERFECT answer.

    A case reports none when no finite ratio was observed -- the launch did not
    complete, or the oracle answered inf/NaN. The aggregate crashed on it:
    ``max((case.worst_residual_ratio for case in cases), default=0.0)`` covers
    only the EMPTY sequence, so a single ``None`` among real ratios raised
    ``TypeError: '>' not supported between instances of 'NoneType' and 'float'``
    -- from inside the driver, which turns a candidate that segfaulted on one
    shape into an outage report about the harness.
    """
    measurements = _normalized([_case("64x64x64", 0.4, verdict="pass"),
                                _case("128x128x128", None)])
    assert measurements["worst_residual_ratio"] is None, (
        "0.4 was published as the worst residual of a case set one of whose "
        "cases produced no residual at all")
    assert measurements["worst_residual_ratio_by_case"] == {
        "64x64x64": 0.4, "128x128x128": None}


def test_the_aggregate_is_still_the_worst_when_every_case_measured_one():
    """Otherwise the fix would be 'never report it', which is the same silence."""
    measurements = _normalized([_case("64x64x64", 0.4, verdict="pass"),
                                _case("128x128x128", 2.5)])
    assert measurements["worst_residual_ratio"] == pytest.approx(2.5)


def test_a_candidate_that_never_built_publishes_no_residual_at_all():
    """``verify_problem_correctness`` returns ``case_results=()`` for a build
    failure, and ``default=0.0`` published "exactly zero error" as the
    measurement behind a candidate that never compiled."""
    measurements = _normalized([])
    assert measurements["case_count"] == 0
    assert measurements["worst_residual_ratio"] is None
