"""The control sequence that lets a problem-correctness Harness EARN attestations.

WHAT WAS WRONG. Three of the five verified catalog rows ship four
``HarnessAttestationV1`` artifacts each, produced by a four-execution control
sequence. The other two ship none, because the surface that registered them --
``scripts/rqgm_assurance/repin_and_promote_harness.py`` -- writes
``clean_control_verdict="pass"`` and ``negative_control_verdict="fail"`` into
``registration_evidence.json`` as LITERALS and points ``attestation_digests`` at
its own report. Nothing ran; the record says something did.
``scripts/rqgm_assurance/attest_problem_correctness.py`` is the missing execution
path, and this file pins the two things that make it worth having.

FIRST: THE SEQUENCE MUST BE ABLE TO REFUSE. A checker that only ever accepts is
the declared constant again, spelled with more code. Every negative below feeds
``check_control_sequence`` a sequence that a careless instrument would produce --
a negative control that "failed" because it did not compile, one caught by the
element-count check instead of by the residual bound, one whose residual is
inside the bound, a clean control that passed with no measurement behind it, an
interface control that failed without an interface fault, a nondeterministic
clean control -- and requires it to raise. The positive case uses the shape of a
real run, so the negatives are one edit away from something that passes.

SECOND: THE FIFTH RUN. This manifest declares TWO properties. In all four
native-shaped runs ``interface-conformance`` comes back ``pass`` -- including in
``negative-screen``, because ``wrong_gemm.c`` keeps the contract perfectly and
only misses the numbers. A conformance claim resting on four runs none of which
ever saw it fail is the same defect one property smaller, so the sequence carries
a fifth control and the test below requires exactly one run in which conformance
is required to fail.

WHAT IS NOT HERE. The container executions themselves. They need a pinned SIF and
a singularity binary, which are per-site preconditions; the promotion surface
fails loudly rather than falling back to an uncontainerised run, and a test that
skipped when the image was absent would be a test that usually asserts nothing.
The shapes below are taken from a real five-run sequence against the registered
manifest, so what they encode is what that run produced.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = (REPO_ROOT / "scripts" / "rqgm_assurance"
               / "attest_problem_correctness.py")


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "attest_problem_correctness", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    # REGISTERED BEFORE EXECUTION. ``@dataclass`` resolves its own module out of
    # ``sys.modules`` while the class body runs, so a module executed outside it
    # raises AttributeError on a NoneType before any test is collected.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


sequence_module = _load_module()


# --------------------------------------------------------------------------
# attestation shapes taken from a real run
# --------------------------------------------------------------------------

_CASES = {
    "1000x1000x1000": {"expected": 1000000, "written": 1000000},
    "1500x600x1500": {"expected": 2250000, "written": 2250000},
    "2000x500x500": {"expected": 1000000, "written": 1000000},
}


#: What ``ProblemCorrectnessDriver.normalize_result`` publishes in every property
#: result's ``tolerance_evidence``. The bound is READ from here rather than
#: asserted by the promotion surface, so the fixture has to carry it: a ratio is
#: not interpretable without the bound it was normalised to.
_UNSET = object()


def _attestation(
    *,
    verdict: str,
    numeric: str,
    interface: str,
    case_count: int = 3,
    failed_case_count: int = 0,
    worst_residual_ratio: float | None = 0.0014,
    build_error: str | None = None,
    interface_error: str | None = None,
    sizes: dict | None = None,
    nondeterminism: tuple[str, ...] = (),
    infrastructure_status: str = "ready",
    residual_ratio_limit: object = 1.0,
) -> SimpleNamespace:
    measurements = {
        "case_count": case_count,
        "failed_case_count": failed_case_count,
        "worst_residual_ratio": worst_residual_ratio,
        "output_elements_by_case": _CASES if sizes is None else sizes,
    }
    oracle = {"build_error": build_error, "interface_error": interface_error,
              "report_digest": "sha256:" + "0" * 64}
    tolerance = {"error_model": "relative-frobenius-residual"}
    if residual_ratio_limit is not _UNSET:
        tolerance["residual_ratio_limit"] = residual_ratio_limit
    return SimpleNamespace(
        verdict=verdict,
        infrastructure_status=infrastructure_status,
        nondeterminism_observations=nondeterminism,
        attempt_id="har-" + "0" * 32 + "-0",
        attestation_digest="sha256:" + "1" * 64,
        property_results=(
            SimpleNamespace(property_id="numerical-equivalence", verdict=numeric,
                            measurements=measurements, oracle_comparison=oracle,
                            tolerance_evidence=tolerance),
            SimpleNamespace(property_id="interface-conformance", verdict=interface,
                            measurements=measurements, oracle_comparison=oracle,
                            tolerance_evidence=tolerance),
        ),
    )


def _clean(**overrides) -> SimpleNamespace:
    return _attestation(verdict="pass", numeric="pass", interface="pass",
                        **overrides)


def _wrong(**overrides) -> SimpleNamespace:
    defaults = {"failed_case_count": 3, "worst_residual_ratio": 7.85e11}
    defaults.update(overrides)
    return _attestation(verdict="fail", numeric="fail", interface="pass",
                        **defaults)


def _exports_extra_symbol(**overrides) -> SimpleNamespace:
    defaults = {
        "case_count": 0,
        "worst_residual_ratio": None,
        "sizes": {},
        "interface_error": ("candidate kernel exports symbols other than "
                            "'gemm': ['ari_problem_correctness_probe_symbol']"),
    }
    defaults.update(overrides)
    return _attestation(verdict="fail", numeric="fail", interface="fail",
                        **defaults)


def _sequence(**overrides) -> dict:
    runs = {
        "clean-screen": _clean(),
        "clean-certify": _clean(),
        "clean-certify-repeat": _clean(),
        "negative-screen": _wrong(),
        "negative-interface-screen": _exports_extra_symbol(),
    }
    runs.update(overrides)
    return runs


# --------------------------------------------------------------------------
# the sequence is the four native labels plus the one this family needs
# --------------------------------------------------------------------------

def test_the_sequence_keeps_the_native_four_and_adds_the_conformance_control() -> None:
    labels = [control.label for control in sequence_module.CONTROLS]
    assert labels[:4] == ["clean-screen", "clean-certify",
                          "clean-certify-repeat", "negative-screen"], (
        "the first four runs are the shape promote_native_harnesses.py runs for "
        "the three native families; keeping the labels is what lets a reader "
        "compare the two evidence bundles line for line")
    required = [control.verdict for control in sequence_module.CONTROLS]
    assert required[:4] == ["pass", "pass", "pass", "fail"]
    assert labels[4] == "negative-interface-screen"
    assert required[4] == "fail"


def test_exactly_one_run_is_required_to_fail_interface_conformance() -> None:
    """Otherwise the conformance claim rests on runs that never tested it.

    Not "at least one": a sequence in which several runs fail conformance would
    mean the clean controls stopped conforming, and this manifest declares only
    two properties, so there is no third place for that to show up.
    """
    failing = [control.label for control in sequence_module.CONTROLS
               if control.property_verdicts["interface-conformance"] == "fail"]
    assert failing == ["negative-interface-screen"]

    passing_numeric = [control.label for control in sequence_module.CONTROLS
                       if control.property_verdicts["numerical-equivalence"] == "pass"]
    assert passing_numeric == ["clean-screen", "clean-certify",
                               "clean-certify-repeat"], (
        "and both negatives must fail numerical equivalence -- an interface "
        "fault means nothing ran, so equivalence is not established either")


def test_no_control_kernel_is_authored_in_the_promotion_surface() -> None:
    """The controls are the PROBLEM's own files, resolved by role name.

    A control kernel written into the promotion script would be a control the
    instrument's registration could not point at, and a weakened one would be
    indistinguishable from a strengthened instrument.
    """
    roles = {control.role for control in sequence_module.CONTROLS}
    assert roles == {"reference", "negative_control_wrong",
                     "seed_candidate+extra-symbol"}
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert "#include" not in source and "double *" not in source


# --------------------------------------------------------------------------
# a discriminating sequence is accepted, and its verdicts are READ
# --------------------------------------------------------------------------

def test_a_discriminating_sequence_is_accepted_and_its_verdicts_are_observed() -> None:
    checked = sequence_module.check_control_sequence(_sequence())
    assert checked["clean_control_verdict"] == "pass"
    assert checked["negative_control_verdict"] == "fail"
    assert checked["observed_verdicts"] == {
        "clean-screen": "pass",
        "clean-certify": "pass",
        "clean-certify-repeat": "pass",
        "negative-screen": "fail",
        "negative-interface-screen": "fail",
    }
    wrong = checked["discrimination"]["negative-screen"]
    assert wrong["worst_residual_ratio"] > wrong["residual_ratio_limit"]
    assert wrong["every_case_wrote_the_expected_element_count"] is True
    assert wrong["build_error"] is None and wrong["interface_error"] is None, (
        "the wrong kernel must be caught by the ORACLE; caught by the build or "
        "the audit it would show only that the harness rejects a file")
    exports = checked["discrimination"]["negative-interface-screen"]
    assert "exports symbols other than" in exports["interface_error"]
    assert exports["every_case_wrote_the_expected_element_count"] is None, (
        "absent is not 'some case wrote the wrong count' -- the audit refused "
        "the object before any case ran")


#: Every ``HarnessRegistrationEvidenceV1`` field that BOTH shipped promotion
#: surfaces write as a constant. The two control verdicts are the loud half;
#: writing the other four fresh in a new file, having just removed those two,
#: would be the same defect with a shorter blast radius.
_DECLARED_IN_BOTH_EXISTING_SURFACES = {
    "clean_control_verdict",
    "negative_control_verdict",
    "official_runner_parity",
    "result_schema_conformant",
    "network_isolation",
    "target_write_isolation",
    "oracle_visibility",
}


def test_no_registration_evidence_field_is_written_as_a_literal() -> None:
    """The defect, pinned at the source.

    ``repin_and_promote_harness._write_promotion`` passes the string ``"pass"``
    to ``clean_control_verdict``, ``"fail"`` to ``negative_control_verdict`` and
    ``"proved"``/``"denied"``/``True`` to the four beside them;
    ``promote_native_harnesses`` writes the same six. Whatever else this module
    does, each of those keywords must be fed a value that came from somewhere --
    a subscript of the observed sequence, or a call -- and never a constant.
    """
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    seen: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg in _DECLARED_IN_BOTH_EXISTING_SURFACES:
                seen.add(keyword.arg)
                assert not isinstance(keyword.value, ast.Constant), (
                    f"{keyword.arg} is handed a literal; that is exactly the "
                    f"defect this module exists to remove")
    assert seen == _DECLARED_IN_BOTH_EXISTING_SURFACES, (
        f"not set at all: {sorted(_DECLARED_IN_BOTH_EXISTING_SURFACES - seen)}")


def test_the_weakest_derived_claim_says_what_it_rests_on() -> None:
    """``oracle_visibility`` is read off the manifest, not off an execution.

    Nothing on this path tries to reach the oracle from inside the candidate, so
    the honest thing is to say the field records what the manifest DECLARES. A
    derivation that quietly looked as strong as the other three would be a
    declared constant wearing a function call.
    """
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert "hidden_test_policy" in source
    assert "not an execution that tried to reach" in source


# --------------------------------------------------------------------------
# and it refuses
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "overrides, fragment",
    [
        pytest.param(
            {"negative-screen": _clean()},
            "control verdicts differ",
            id="a-negative-control-that-passes-is-not-a-control",
        ),
        pytest.param(
            {"clean-certify": _attestation(
                verdict="fail", numeric="fail", interface="pass",
                failed_case_count=3, worst_residual_ratio=9.0)},
            "control verdicts differ",
            id="a-clean-control-that-fails-refuses-the-whole-sequence",
        ),
        pytest.param(
            {"negative-screen": _attestation(
                verdict="fail", numeric="fail", interface="fail",
                failed_case_count=3, worst_residual_ratio=7.85e11)},
            "property verdicts",
            id="right-overall-answer-for-the-wrong-reason",
        ),
        pytest.param(
            {"negative-screen": _wrong(
                build_error="cc: error: candidate_gemm.c: no such file",
                case_count=0, sizes={}, failed_case_count=0,
                worst_residual_ratio=None)},
            "failed before the oracle ran",
            id="a-negative-control-that-did-not-compile-shows-nothing",
        ),
        pytest.param(
            {"negative-screen": _wrong(
                sizes={"1000x1000x1000": {"expected": 1000000, "written": 4}})},
            "element-count check",
            id="caught-by-a-size-check-rather-than-by-the-oracle",
        ),
        pytest.param(
            {"negative-screen": _wrong(worst_residual_ratio=0.5)},
            "does not exceed the bound",
            id="a-negative-control-inside-the-residual-bound",
        ),
        pytest.param(
            {"negative-screen": _wrong(failed_case_count=1)},
            "is not the control this claims to be",
            id="a-wrong-kernel-that-is-right-about-some-shapes",
        ),
        pytest.param(
            {"negative-interface-screen": _exports_extra_symbol(
                interface_error=None)},
            "without an interface error",
            id="conformance-claim-still-resting-on-nothing",
        ),
        pytest.param(
            {"negative-interface-screen": _exports_extra_symbol(
                case_count=3, sizes=_CASES)},
            "scored cases",
            id="the-audit-was-supposed-to-refuse-before-anything-ran",
        ),
        pytest.param(
            {"clean-screen": _clean(
                nondeterminism=("candidate output varied byte-for-byte",))},
            "nondeterministic",
            id="a-clean-control-that-did-not-repeat",
        ),
        pytest.param(
            {"clean-screen": _clean(worst_residual_ratio=None)},
            "no residual ratio at all",
            id="a-pass-with-no-measurement-behind-it",
        ),
        pytest.param(
            {"clean-screen": _clean(worst_residual_ratio=4.2)},
            "above the bound",
            id="a-pass-outside-the-bound-it-was-judged-against",
        ),
        pytest.param(
            {"clean-screen": _clean(infrastructure_status="failed")},
            "about the substrate",
            id="a-verdict-about-the-substrate-is-not-a-verdict-about-a-candidate",
        ),
        # THE BOUND IS READ, so its absence is a refusal and not a fallback to
        # the 1.0 this module used to assert.
        pytest.param(
            {"clean-screen": _clean(residual_ratio_limit=_UNSET)},
            "states no numeric residual_ratio_limit",
            id="a-ratio-normalised-to-a-bound-the-run-never-stated",
        ),
        pytest.param(
            {"clean-screen": _clean(residual_ratio_limit="1.0")},
            "states no numeric residual_ratio_limit",
            id="a-bound-that-is-not-a-number",
        ),
        pytest.param(
            {"clean-screen": _clean(residual_ratio_limit=0.0)},
            "not a positive finite number",
            id="a-bound-of-zero-accepts-nothing",
        ),
        pytest.param(
            {"clean-screen": _clean(residual_ratio_limit=float("inf"))},
            "not a positive finite number",
            id="an-infinite-bound-accepts-everything",
        ),
        pytest.param(
            {"negative-screen": _wrong(residual_ratio_limit=2.0)},
            "different residual bounds",
            id="controls-judged-against-bounds-that-disagree",
        ),
    ],
)
def test_the_sequence_refuses_a_run_that_did_not_discriminate(
    overrides, fragment
) -> None:
    with pytest.raises(sequence_module.ControlSequenceError) as caught:
        sequence_module.check_control_sequence(_sequence(**overrides))
    assert fragment in str(caught.value)


def test_a_missing_run_is_refused_rather_than_summarised() -> None:
    runs = _sequence()
    del runs["negative-interface-screen"]
    with pytest.raises(sequence_module.ControlSequenceError) as caught:
        sequence_module.check_control_sequence(runs)
    assert "negative-interface-screen" in str(caught.value)


def test_a_self_contradictory_attestation_is_refused() -> None:
    """Two results for one property with different verdicts decide nothing."""
    contradictory = _clean()
    contradictory.property_results = (
        *contradictory.property_results,
        SimpleNamespace(property_id="numerical-equivalence", verdict="fail",
                        measurements={}, oracle_comparison={}),
    )
    with pytest.raises(sequence_module.ControlSequenceError) as caught:
        sequence_module.check_control_sequence(
            _sequence(**{"clean-screen": contradictory}))
    assert "both" in str(caught.value)


# --------------------------------------------------------------------------
# the contract is derived from the manifest, not typed beside it
# --------------------------------------------------------------------------

def test_the_contract_resolves_against_the_registered_manifest() -> None:
    """Reusing the native contract verbatim would leave atoms unsatisfied.

    ``promote_native_harnesses._contract`` requires ``reproducibility @ certify``
    and stamps ``target_kind: shared-library`` with two dtypes -- true of the
    families it was written for, false of this manifest, which declares two
    properties, ``benchmark-submission`` and fp64 alone.
    """
    from ari.assurance.resolver import normalize_requirements

    manifest = sequence_module.load_manifest(
        sequence_module.BUILTIN / "hpc_gemm_problem_correctness.yaml")
    contract = sequence_module.build_control_contract(manifest)
    atoms = normalize_requirements(contract)
    assert len(atoms) == 4
    assert {atom.property_id for atom in atoms} == {
        "numerical-equivalence", "interface-conformance"}
    assert {atom.tier for atom in atoms} == {"screen", "certify"}
    assert {atom.target_kind for atom in atoms} == set(manifest.target_kinds)
    declared = {item.property_id for item in manifest.properties}
    assert {atom.property_id for atom in atoms} == declared, (
        "a contract asking for a property the manifest does not declare cannot "
        "be covered, and resolve_harness_suite refuses the suite")
    for atom in atoms:
        assert atom.scope.values["dtype"] == ("float64",)


def test_a_drifted_instrument_is_refused_before_any_container_launches(
    tmp_path,
) -> None:
    """Otherwise the refusal arrives after minutes of container work.

    ``FixedVerifier`` already refuses a drifted driver, correctly, but from
    inside the run loop. Measured: a concurrent writer touched
    `native_perf_common.py` -- which sits inside this driver's content digest --
    partway through a sequence, and the run spent 34 s launching containers
    before dying on a bare "Harness driver identity drift" traceback. Asked
    before the first launch, it is one sentence naming the repair.
    """
    manifest = sequence_module.load_manifest(
        sequence_module.BUILTIN / "hpc_gemm_problem_correctness.yaml")
    drifted = manifest.model_copy(update={
        "driver": manifest.driver.model_copy(update={"sha256": "sha256:" + "a" * 64})})
    with pytest.raises(sequence_module.ControlSequenceError) as caught:
        sequence_module.run_control_sequence(
            manifest=drifted,
            container_root=tmp_path,
            working_root=tmp_path / "runs")
    assert "no longer has" in str(caught.value)
    assert "repin_and_promote_harness.py" in str(caught.value)


def test_the_manifest_pins_a_problem_that_ships_both_controls() -> None:
    """The clean and both negative controls must exist as the PROBLEM's files."""
    manifest = sequence_module.load_manifest(
        sequence_module.BUILTIN / "hpc_gemm_problem_correctness.yaml")
    for control in sequence_module.CONTROLS:
        provenance, payload = sequence_module.candidate_source(
            manifest, control.role)
        assert payload, provenance
        assert b"gemm" in payload
    _, extra = sequence_module.candidate_source(
        manifest, "seed_candidate+extra-symbol")
    assert b"ari_problem_correctness_probe_symbol" in extra, (
        "the interface control is the driver's own mechanical transform of the "
        "problem's own seed, not a kernel written here")


# --------------------------------------------------------------------------
# nothing published may carry host identity
# --------------------------------------------------------------------------

def test_host_identity_is_refused_rather_than_scrubbed() -> None:
    """The bundle is committed and published; the worker's stdout is in it.

    Scrubbing would hide which artifact leaked, and the refusal names the
    artifact and the term's INDEX -- never the term, which would put the identity
    into the failure message and from there into CI output.
    """
    leaked = str(REPO_ROOT).encode("utf-8")
    with pytest.raises(sequence_module.ControlSequenceError) as caught:
        sequence_module.refuse_host_identity({"logs/clean-screen-stdout.log":
                                              b'{"cwd": "' + leaked + b'"}'})
    message = str(caught.value)
    assert "logs/clean-screen-stdout.log" in message
    assert str(REPO_ROOT) not in message
    sequence_module.refuse_host_identity(
        {"clean-screen.attestation.json": b'{"verdict": "pass"}'})


#: The slug ``repin_and_promote_harness._slug`` derives for this harness id. Only
#: used to spell the paths the guard must name; nothing below derives from it.
_SLUG = "hpc-gemm-dense-fp64-problem-correctness"


def _published(**overrides) -> dict[str, bytes]:
    """The map ``promote`` guards and then writes, built from plain values.

    ``_json_bytes`` falls back to ``json.dumps`` for anything without
    ``model_dump``, so the artifacts can be dicts here: what is under test is
    which PATHS the map covers, not the models' own serialisation.
    """
    kwargs: dict = {
        "slug": _SLUG,
        "artifacts": {"control_sequence.json": b'{"schema_version": "v1"}\n'},
        "evidence": {"harness_id": "hpc/gemm-dense-fp64-problem-correctness"},
        "report": {"decision": "eligible-for-verified"},
        "approval": {"actor_kind": "human-maintainer"},
        "catalog": {"entries": []},
    }
    kwargs.update(overrides)
    return sequence_module.published_artifacts(**kwargs)


def test_every_byte_written_into_the_harness_tree_is_inside_the_guard() -> None:
    """The gap: four published artifacts were written PAST ``refuse_host_identity``.

    The guard ran over the evidence bundle, and then the registration evidence,
    the registration report, the promotion approval and the catalog were built
    and written after it. All four are committed and published, which is the
    guard's whole stated reason for existing.
    """
    published = _published()
    assert set(published) == {
        f"evidence/{_SLUG}/control_sequence.json",
        f"evidence/{_SLUG}/registration_evidence.json",
        f"reports/{_SLUG}.registration.json",
        f"approvals/{_SLUG}.approval.json",
        "catalog.yaml",
    }
    # Keys are relative to the Harness root, so the refusal names the exact file
    # rather than a bare basename that appears in three directories.
    sequence_module.refuse_host_identity(published)


@pytest.mark.parametrize(
    "field, path",
    [
        pytest.param("evidence", f"evidence/{_SLUG}/registration_evidence.json",
                     id="registration-evidence"),
        pytest.param("report", f"reports/{_SLUG}.registration.json",
                     id="registration-report"),
        pytest.param("approval", f"approvals/{_SLUG}.approval.json",
                     id="promotion-approval"),
        pytest.param("catalog", "catalog.yaml", id="catalog-row"),
    ],
)
def test_a_leak_in_an_artifact_written_past_the_old_guard_is_refused(
    field, path
) -> None:
    """Each of these used to be written after the guard had already passed."""
    published = _published(**{field: {"note": str(REPO_ROOT)}})
    with pytest.raises(sequence_module.ControlSequenceError) as caught:
        sequence_module.refuse_host_identity(published)
    message = str(caught.value)
    assert path in message
    assert str(REPO_ROOT) not in message, (
        "the refusal names the artifact and the term's index, never the term")


def test_the_promotion_guards_once_and_writes_once() -> None:
    """The structural half of the repair, pinned.

    Four guard calls would have closed today's gap and left the next artifact
    outside it, because the failure mode is appending a write after a call.
    ``promote`` performs exactly one write, of one map, immediately after one
    guard, so a future unguarded artifact needs a whole new write path -- which
    is a visible thing to add rather than a line at the end of a function.
    """
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    body = next(node for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef) and node.name == "promote")
    called: list[str] = []
    for node in ast.walk(body):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            called.append(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            called.append(node.func.attr)
    assert called.count("_write_bundle") == 1, (
        "promote writes the Harness tree in one place, or the guard's coverage "
        "goes back to depending on the order of statements")
    assert called.count("refuse_host_identity") == 1
    assert called.count("published_artifacts") == 1
    for escape in ("write_text", "write_bytes", "open", "replace"):
        assert escape not in called, (
            f"promote reaches the filesystem through {escape}, which bypasses "
            f"the single guarded write")


# --------------------------------------------------------------------------
# the length floor is asked, not assumed
# --------------------------------------------------------------------------

def test_no_real_identity_term_is_dropped_by_the_length_floor() -> None:
    """The floor exists so ordinary words are not matched; it must not bite here.

    Every candidate is a filesystem path, a DNS name or a passwd name. The
    assertion is the measurement: if one of them were short, the guard would
    silently stop covering it while the bundle was published anyway.
    """
    terms = sequence_module.host_identity_terms()
    assert terms, "a guard with no terms checks nothing"
    assert str(REPO_ROOT) in terms
    assert all(len(term) >= sequence_module.MINIMUM_IDENTITY_TERM_LENGTH
               for term in terms)


def test_a_term_under_the_floor_refuses_rather_than_being_dropped(
    monkeypatch,
) -> None:
    """Silently narrowing is the defect; the floor is fail-closed instead.

    A short host name cannot be matched -- it would occur inside digests, JSON
    keys and prose, and the guard would be switched off within a day. Dropping
    it publishes a bundle that was never checked for it. Refusing says the
    honest thing: this guard cannot certify this bundle.
    """
    monkeypatch.setattr(sequence_module.socket, "gethostname", lambda: "hn01")
    monkeypatch.setattr(sequence_module.socket, "getfqdn", lambda *a: "hn01")
    monkeypatch.setattr(sequence_module.platform, "node", lambda: "hn01")
    with pytest.raises(sequence_module.ControlSequenceError) as caught:
        sequence_module.host_identity_terms()
    message = str(caught.value)
    assert "shorter than" in message
    assert "hn01" not in message, (
        "naming the short term would put the identity into CI output, which is "
        "the same leak the guard exists to prevent")


def test_an_unset_candidate_is_not_a_term_and_does_not_refuse(monkeypatch) -> None:
    """``platform.node()`` returns '' on some hosts. Absent is not unguarded."""
    monkeypatch.setattr(sequence_module.platform, "node", lambda: "")
    assert sequence_module.host_identity_terms()


# --------------------------------------------------------------------------
# the residual bound is read off the run, not asserted here
# --------------------------------------------------------------------------

def test_the_module_asserts_no_residual_bound_of_its_own() -> None:
    """``RESIDUAL_RATIO_LIMIT = 1.0`` was the declared constant, one layer down.

    It was compared against AND republished into every run's discrimination
    record as though it had been observed, so a driver that moved its bound
    would have left this module consistent with itself and wrong about the
    instrument.
    """
    assert not hasattr(sequence_module, "RESIDUAL_RATIO_LIMIT")


def test_the_published_bound_is_the_one_the_run_reported() -> None:
    checked = sequence_module.check_control_sequence(_sequence())
    for label, found in checked["discrimination"].items():
        assert found["residual_ratio_limit"] == 1.0, label


def test_a_moved_bound_moves_the_verdicts_with_it() -> None:
    """The point of reading it: the checks follow the instrument.

    A clean control at 1.5 is OUTSIDE the bound this module used to assert and
    inside the one the run reports, and a wrong kernel at 1.6 is the reverse.
    Against a local constant the first is refused and the second accepted --
    both backwards.
    """
    runs = {
        "clean-screen": _clean(worst_residual_ratio=1.5, residual_ratio_limit=2.0),
        "clean-certify": _clean(worst_residual_ratio=1.5, residual_ratio_limit=2.0),
        "clean-certify-repeat": _clean(worst_residual_ratio=1.5,
                                       residual_ratio_limit=2.0),
        "negative-screen": _wrong(worst_residual_ratio=7.85e11,
                                  residual_ratio_limit=2.0),
        "negative-interface-screen": _exports_extra_symbol(residual_ratio_limit=2.0),
    }
    checked = sequence_module.check_control_sequence(runs)
    assert checked["clean_control_verdict"] == "pass"
    assert checked["discrimination"]["clean-screen"]["residual_ratio_limit"] == 2.0

    inside = dict(runs)
    inside["negative-screen"] = _wrong(worst_residual_ratio=1.6,
                                       residual_ratio_limit=2.0)
    with pytest.raises(sequence_module.ControlSequenceError) as caught:
        sequence_module.check_control_sequence(inside)
    assert "does not exceed the bound 2.0" in str(caught.value)
