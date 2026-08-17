"""The control sequence and promotion surface that let hpc/gemm-performance EARN.

WHAT WAS WRONG. ``hpc/gemm-performance`` carries ``status: verified`` on evidence
no execution produced. Its ``registration_evidence.json`` holds
``attestation_digests == [its own registration report's digest]`` -- the bundle
citing itself as the execution it never performed -- beside seven values that
were typed rather than observed: two control verdicts, official-runner parity,
result-schema conformance and three isolation claims. It ships no
``*.attestation.json`` and no ``logs/``. The surface that wrote it,
``repin_and_promote_harness.py``, has since been closed for exactly that, which
left this family with a ``controls`` mode that writes a scratch bundle and
NOTHING that could re-register it -- so a re-pin, which moves the manifest
digest, left the report, the evidence and the approval naming a digest that had
moved, and ``load_harness_catalog`` refused to load at all.
``scripts/rqgm_assurance/attest_gemm_performance.py``'s ``promote`` is the
missing surface, and this file pins the properties that make it worth having.

FIRST: THE SEQUENCE MUST BE ABLE TO REFUSE. A checker that only ever accepts is
the declared constant again, spelled with more code. Every negative below feeds
``check_control_sequence`` a sequence a careless instrument would produce -- a
negative control that passed, a clean control that failed, a slow-but-correct
kernel refused by the ORACLE, a fast-but-wrong one refused on the RATIO, a
negative that scored no case at all, a verdict carried by a property this
manifest does not declare -- and requires it to raise.

SECOND: THE TWO NEGATIVES ARE THE FAMILY. A correctness sequence needs one
negative; a benchmark needs two that fail for DIFFERENT reasons, or it has not
shown it can tell a wrong answer from a slow one. The ground is read from the
per-case correctness the attestation carries, never from prose -- the driver's
detail strings do not reach an attestation at all -- and the tests below pin
that reading in both directions.

THIRD: NOTHING ``promote`` PUBLISHES MAY BE A LITERAL. The AST checks require
that no ``HarnessRegistrationEvidenceV1`` field on this surface is handed a
constant, that ``check_control_sequence`` does not return the two control
verdicts it is supposed to have read, and that every published byte passes one
guard and one write in one order.

WHAT IS NOT HERE. The container executions themselves. They need a pinned SIF
and a singularity binary, which are per-site preconditions; the surface fails
loudly rather than falling back to an uncontainerised run, and a test that
skipped when the image was absent would be a test that usually asserts nothing.
The shapes below are the shapes ``NativePerfDriver.normalize_result`` publishes.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts" / "rqgm_assurance"
MODULE_PATH = SCRIPTS / "attest_gemm_performance.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "attest_gemm_performance", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    # REGISTERED BEFORE EXECUTION. ``@dataclass`` resolves its own module out of
    # ``sys.modules`` while the class body runs, so a module executed outside it
    # raises AttributeError on a NoneType before any test is collected.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


sequence_module = _load_module()
PROPERTY = sequence_module.PROPERTY

# The sibling surface. Importable by plain name because the module above inserts
# the scripts directory on ``sys.path`` at import time, and it is the module the
# family-agnostic machinery actually lives in.
import attest_problem_correctness as sibling_module  # noqa: E402


# --------------------------------------------------------------------------
# attestation shapes, as NativePerfDriver.normalize_result publishes them
# --------------------------------------------------------------------------

_CASE_IDS = ("1000x1000x1000", "1500x600x1500", "2000x500x500")

_SECONDS = {"1000x1000x1000": 0.0136, "1500x600x1500": 0.0115,
            "2000x500x500": 0.0366}


def _attestation(
    *,
    verdict: str,
    property_verdict: str | None = None,
    correct_by_case: dict | None = None,
    min_speedup: float = 1.01,
    worst_relative_spread: float | None = 0.031,
    regression_threshold: float = 1.0,
    infrastructure_status: str = "ready",
    extra_property: tuple[str, str] | None = None,
    digest_tail: str = "1",
) -> SimpleNamespace:
    """One attestation, carrying the fields this driver actually publishes.

    ``correct_by_case`` is the discriminator: ``_ground_of`` reads it and nothing
    else, because the driver's "below the threshold" / "failed the residual
    bound" detail never reaches an attestation.
    """
    if correct_by_case is None:
        correct_by_case = {case: True for case in _CASE_IDS}
    measurements = {
        "case_count": len(_CASE_IDS),
        "failed_case_count": 0 if verdict == "pass" else len(_CASE_IDS),
        "correct_by_case": dict(correct_by_case),
        "complete_by_case": {case: True for case in _CASE_IDS},
        "min_speedup": min_speedup,
        "median_speedup_by_case": {case: min_speedup for case in _CASE_IDS},
        "credited_seconds_by_case": dict(_SECONDS),
        "toolchain_gain_by_case": {},
    }
    tolerance = {
        "regression_threshold": regression_threshold,
        "denominator": "frozen-reference",
        "worst_relative_spread": worst_relative_spread,
    }
    results = [
        SimpleNamespace(
            property_id=PROPERTY,
            verdict=property_verdict or verdict,
            measurements=measurements,
            tolerance_evidence=tolerance,
            oracle_comparison={"report_digest": "sha256:" + "0" * 64},
        )
    ]
    if extra_property is not None:
        name, seen = extra_property
        results.append(SimpleNamespace(
            property_id=name, verdict=seen, measurements=measurements,
            tolerance_evidence=tolerance, oracle_comparison={}))
    return SimpleNamespace(
        verdict=verdict,
        infrastructure_status=infrastructure_status,
        nondeterminism_observations=(),
        attempt_id="har-" + "0" * 32 + "-0",
        attestation_digest="sha256:" + digest_tail * 64,
        property_results=tuple(results),
    )


def _clean(**overrides) -> SimpleNamespace:
    return _attestation(verdict="pass", **overrides)


def _slow(**overrides) -> SimpleNamespace:
    """Correct about the answer, slower than the frozen reference.

    Every case correct, so nothing but the RATIO had grounds to refuse it.
    """
    defaults = {"min_speedup": 0.11}
    defaults.update(overrides)
    return _attestation(verdict="fail", **defaults)


def _wrong(**overrides) -> SimpleNamespace:
    """Fast, and wrong. It writes every element, so only the oracle refuses it."""
    defaults = {
        "min_speedup": 4.8,
        "correct_by_case": {case: False for case in _CASE_IDS},
    }
    defaults.update(overrides)
    return _attestation(verdict="fail", **defaults)


def _sequence(**overrides) -> dict:
    runs = {
        "clean-screen": _clean(digest_tail="1"),
        "clean-validate": _clean(digest_tail="2"),
        "clean-validate-repeat": _clean(digest_tail="3"),
        "negative-slow-screen": _slow(digest_tail="4"),
        "negative-wrong-screen": _wrong(digest_tail="5"),
    }
    runs.update(overrides)
    return runs


# --------------------------------------------------------------------------
# the sequence is a benchmark's, not a correctness one's
# --------------------------------------------------------------------------

def test_the_clean_control_runs_at_the_tier_a_spread_exists_at() -> None:
    """Screen is one repetition, so it has no spread; validate is three.

    This instrument's verdict rule reads the spread, so a clean control shown
    only at screen leaves the tier a ratio is actually read at unexercised.
    """
    controls = sequence_module.CONTROLS
    clean = [control for control in controls if control.role == "reference"]
    assert [control.label for control in clean] == [
        "clean-screen", "clean-validate", "clean-validate-repeat"]
    assert {control.tier for control in clean} == {"screen", "validate"}
    repeats = [control.retry_index for control in clean
               if control.tier == "validate"]
    assert sorted(repeats) == [0, 1], (
        "the repeat is at a different retry index, so the seeds differ: the "
        "claim is that the verdict is stable across instances, which is weaker "
        "and more honest than digest equality between two runs of one input")


def test_both_negatives_are_required_and_on_different_grounds() -> None:
    """A benchmark that showed one negative would be a stopwatch with a label."""
    negatives = {control.label: control.ground
                 for control in sequence_module.CONTROLS
                 if control.role != "reference"}
    assert negatives == {"negative-slow-screen": "ratio",
                         "negative-wrong-screen": "oracle"}
    assert all(control.verdict == "fail"
               for control in sequence_module.CONTROLS
               if control.role != "reference")


def test_no_control_kernel_is_authored_in_the_promotion_surface() -> None:
    """The controls are the PROBLEM's own files, resolved by role name.

    A kernel written into this script would be one the registration could not
    point at, and a weakened one would be indistinguishable from a strengthened
    instrument.
    """
    roles = {control.role for control in sequence_module.CONTROLS}
    assert roles == {"reference", "negative_control_slow",
                     "negative_control_wrong"}
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert "#include" not in source and "double *" not in source


# --------------------------------------------------------------------------
# the ground is read off the facts, never off prose
# --------------------------------------------------------------------------

def test_the_ground_is_read_from_per_case_correctness() -> None:
    """The driver's "below the threshold" detail never reaches an attestation.

    ``measurements`` carries numbers and ``tolerance_evidence`` the threshold and
    the spread; a sequence that matched on a sentence would be reading a field
    that is not there. A candidate every repetition of which was CORRECT and was
    still refused can only have lost on the ratio.
    """
    assert sequence_module._ground_of(_slow()) == "ratio"
    assert sequence_module._ground_of(_wrong()) == "oracle"
    assert sequence_module._ground_of(_wrong(
        correct_by_case={"1000x1000x1000": True, "1500x600x1500": False,
                         "2000x500x500": True})) == "oracle", (
        "one incorrect repetition is enough; the oracle had grounds")
    assert sequence_module._ground_of(_slow(correct_by_case={})) is None, (
        "no case ran, so no ground was established and the refusal must say so")


# --------------------------------------------------------------------------
# a discriminating sequence is accepted, and its verdicts are READ
# --------------------------------------------------------------------------

def test_a_discriminating_sequence_is_accepted_and_its_verdicts_are_observed() -> None:
    checked = sequence_module.check_control_sequence(_sequence())
    assert checked["clean_control_verdict"] == "pass"
    assert checked["negative_control_verdict"] == "fail"
    assert checked["observed_verdicts"] == {
        "clean-screen": "pass",
        "clean-validate": "pass",
        "clean-validate-repeat": "pass",
        "negative-slow-screen": "fail",
        "negative-wrong-screen": "fail",
    }
    assert checked["negative_control_grounds"] == {
        "negative-slow-screen": "ratio", "negative-wrong-screen": "oracle"}
    assert checked["distinct_negative_grounds"] == ["oracle", "ratio"], (
        "two negatives failing the same way would certify a stopwatch wearing "
        "a benchmark label")


def test_the_two_control_verdicts_are_not_returned_as_literals() -> None:
    """The defect, one layer below the one everybody looks at.

    ``check_control_sequence`` used to ``return {"clean_control_verdict":
    "pass", "negative_control_verdict": "fail", ...}``. Unreachable while every
    check above refuses first, therefore never wrong, and therefore exactly the
    declared constant: a value that is right because someone typed the right
    one. ``registration_evidence`` reads both fields, so a promotion built on
    them would be declaring its control outcomes with extra steps.
    """
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    body = next(node for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef)
                and node.name == "check_control_sequence")
    seen: set[str] = set()
    for node in ast.walk(body):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if isinstance(key, ast.Constant) and key.value in {
                    "clean_control_verdict", "negative_control_verdict"}:
                seen.add(key.value)
                assert not isinstance(value, ast.Constant), (
                    f"{key.value} is returned as a literal; the sequence is "
                    f"supposed to have READ it off the attestations")
    assert seen == {"clean_control_verdict", "negative_control_verdict"}


# --------------------------------------------------------------------------
# and it refuses
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "overrides, fragment",
    [
        pytest.param(
            {"negative-slow-screen": _clean()},
            "where the sequence requires 'fail'",
            id="a-negative-control-that-passes-is-not-a-control",
        ),
        pytest.param(
            {"clean-validate": _slow()},
            "where the sequence requires 'pass'",
            id="a-clean-control-that-fails-refuses-the-whole-sequence",
        ),
        pytest.param(
            {"negative-slow-screen": _slow(
                correct_by_case={case: False for case in _CASE_IDS})},
            "was refused on 'oracle' where the sequence requires 'ratio'",
            id="a-slow-but-correct-kernel-refused-by-the-oracle-shows-nothing",
        ),
        pytest.param(
            {"negative-wrong-screen": _wrong(
                correct_by_case={case: True for case in _CASE_IDS})},
            "was refused on 'ratio' where the sequence requires 'oracle'",
            id="a-fast-but-wrong-kernel-refused-on-the-ratio-shows-nothing",
        ),
        pytest.param(
            {"negative-wrong-screen": _wrong(correct_by_case={})},
            "was refused on None",
            id="a-negative-that-scored-no-case-established-no-ground",
        ),
        pytest.param(
            {"clean-screen": _clean(property_verdict="fail")},
            "the verdict must be this property's",
            id="a-harness-verdict-that-is-not-this-propertys",
        ),
        pytest.param(
            {"clean-screen": _clean(
                extra_property=("numerical-equivalence", "pass"))},
            "declares only",
            id="a-pass-resting-on-a-property-the-manifest-does-not-declare",
        ),
    ],
)
def test_the_sequence_refuses_a_run_that_did_not_discriminate(
    overrides, fragment
) -> None:
    with pytest.raises(sequence_module.ControlSequenceError) as caught:
        sequence_module.check_control_sequence(_sequence(**overrides))
    assert fragment in str(caught.value)


def test_a_refusal_names_the_numbers_it_refused_on() -> None:
    """Otherwise the reader goes back to the container to find out why.

    The quantities that decide a timed verdict are already in the attestation
    the sequence is holding when it refuses.
    """
    with pytest.raises(sequence_module.ControlSequenceError) as caught:
        sequence_module.check_control_sequence(
            _sequence(**{"negative-slow-screen": _clean()}))
    message = str(caught.value)
    assert "worst_relative_spread=" in message
    assert "min_speedup=" in message
    assert "seconds_by_case=" in message


def test_a_missing_run_is_refused_rather_than_summarised() -> None:
    runs = _sequence()
    del runs["negative-wrong-screen"]
    with pytest.raises(sequence_module.ControlSequenceError) as caught:
        sequence_module.check_control_sequence(runs)
    assert "negative-wrong-screen" in str(caught.value)
    assert "did not run" in str(caught.value)


def test_a_self_contradictory_attestation_is_refused() -> None:
    """Two results for one property with different verdicts decide nothing."""
    contradictory = _clean()
    contradictory.property_results = (
        *contradictory.property_results,
        SimpleNamespace(property_id=PROPERTY, verdict="fail", measurements={},
                        tolerance_evidence={}, oracle_comparison={}),
    )
    with pytest.raises(sequence_module.ControlSequenceError) as caught:
        sequence_module.check_control_sequence(
            _sequence(**{"clean-screen": contradictory}))
    assert "both" in str(caught.value)


# --------------------------------------------------------------------------
# nothing this promotion publishes is a literal
# --------------------------------------------------------------------------

#: Every ``HarnessRegistrationEvidenceV1`` field that BOTH closed promotion
#: surfaces wrote as a constant, and that this family's bundle carries as one
#: today. Removing the two loud ones and writing the other five fresh would be
#: the same defect with a shorter blast radius.
_DECLARED_IN_THE_SHIPPED_BUNDLE = {
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

    ``repin_and_promote_harness._write_promotion`` passed ``"pass"`` to
    ``clean_control_verdict``, ``"fail"`` to ``negative_control_verdict`` and
    ``"proved"``/``"denied"``/``True`` to the five beside them, and
    ``hpc/gemm-performance``'s bundle carries those values today. Whatever else
    this module does, each keyword must be fed a value that came from somewhere
    -- a subscript of the observed sequence, or a call -- and never a constant.
    """
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    seen: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg in _DECLARED_IN_THE_SHIPPED_BUNDLE:
                seen.add(keyword.arg)
                assert not isinstance(keyword.value, ast.Constant), (
                    f"{keyword.arg} is handed a literal; that is exactly the "
                    f"defect this surface exists to remove")
    assert seen == _DECLARED_IN_THE_SHIPPED_BUNDLE, (
        f"not set at all: {sorted(_DECLARED_IN_THE_SHIPPED_BUNDLE - seen)}")


def test_the_attestation_digests_are_the_runs_and_not_the_report() -> None:
    """The bundle on disk cites its own registration report as its execution.

    So the field must be fed the attestations the sequence returned. Reading the
    syntax tree rather than the values keeps this true of a promotion nobody has
    run yet.
    """
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    keywords = [keyword for node in ast.walk(tree) if isinstance(node, ast.Call)
                for keyword in node.keywords
                if keyword.arg == "attestation_digests"]
    assert len(keywords) == 1
    fed = ast.unparse(keywords[0].value)
    assert "attestation_digest" in fed and "attestations" in fed
    assert "report" not in fed, (
        "pointing this at the registration report is the bundle citing itself "
        "as the execution it never performed")


def _promote_calls() -> list[tuple[str, int]]:
    """``(called name, line)`` for every call in ``promote``, in source order."""
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    body = next(node for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef) and node.name == "promote")
    found: list[tuple[str, int]] = []
    for node in ast.walk(body):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            found.append((node.func.id, node.lineno))
        elif isinstance(node.func, ast.Attribute):
            found.append((node.func.attr, node.lineno))
    return sorted(found, key=lambda item: item[1])


def test_the_promotion_guards_once_and_writes_once() -> None:
    """The structural half of the repair.

    Several guard calls would close today's gap and leave the next artifact
    outside it, because the failure mode is appending a write after a call.
    ``promote`` performs exactly one write, of one map, immediately after one
    guard, so a future unguarded artifact needs a whole new write path -- which
    is a visible thing to add rather than a line at the end of a function.
    """
    called = [name for name, _ in _promote_calls()]
    assert called.count("_write_bundle") == 1, (
        "promote writes the Harness tree in one place, or the guard's coverage "
        "goes back to depending on the order of statements")
    assert called.count("refuse_host_identity") == 1
    assert called.count("published_artifacts") == 1
    for escape in ("write_text", "write_bytes", "open", "replace", "mkdir"):
        assert escape not in called, (
            f"promote reaches the filesystem through {escape}, which bypasses "
            f"the single guarded write")


def test_the_promotion_runs_the_sequence_first_and_writes_last() -> None:
    """The ordering is the argument, not tidiness.

    The stale-pin question is free and is asked before five container launches.
    The sequence runs before the gates, so the gates are asked about an
    instrument just seen to discriminate. And NOTHING is written until both have
    passed, because the first write dirties the tree the source pin is taken
    from -- which is how a promotion comes to name a commit whose bytes are not
    the bytes that were measured.
    """
    lines = {}
    for name, line in _promote_calls():
        lines.setdefault(name, line)
    for earlier, later in (
        ("stale_pins", "run_control_sequence"),
        ("run_control_sequence", "register_harness"),
        ("register_harness", "repository_commit"),
        ("repository_commit", "published_artifacts"),
        ("published_artifacts", "refuse_host_identity"),
        ("refuse_host_identity", "_write_bundle"),
    ):
        assert lines[earlier] < lines[later], (
            f"{earlier} must be reached before {later}")


def test_a_rejected_registration_is_a_result_and_writes_nothing() -> None:
    """A refusal returns a code; it does not sign a weaker claim.

    On this family a refusal is the expected outcome wherever the cases are too
    small for the machine to resolve them, and that is the instrument working.
    """
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert "a rejected registration is a result" in source
    tree = ast.parse(source)
    body = next(node for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef) and node.name == "promote")
    returns = [node for node in ast.walk(body) if isinstance(node, ast.Return)]
    codes = {node.value.value for node in returns
             if isinstance(node.value, ast.Constant)}
    assert codes == {0, 3, 4}, (
        "a stale pin, a rejected registration and a signed promotion are three "
        "distinguishable outcomes for a caller")


# --------------------------------------------------------------------------
# the surface takes a human signature, and takes it the same way
# --------------------------------------------------------------------------

def _capture_into(store: dict, key: str):
    def _run(args) -> int:
        store[key] = vars(args)
        return 0
    return _run


_SIGNED_ARGV = [
    "promote",
    "--container-root", "/nonexistent-container-root",
    "--actor-id", "a-maintainer",
    "--authorization-basis", "read the bundle",
    "--approved-date", "2026-01-01",
]


def test_promote_takes_its_flags_the_same_way_as_the_sibling_surface(
    monkeypatch,
) -> None:
    """Not "similarly": the same names, the same defaults, the same root.

    Two promotion surfaces whose ``--harness-root`` defaults differed would put
    one family's bundle somewhere the other's rehearsal never covered.
    """
    captured: dict = {}
    monkeypatch.setattr(sequence_module, "promote",
                        _capture_into(captured, "performance"))
    monkeypatch.setattr(sibling_module, "promote",
                        _capture_into(captured, "correctness"))
    assert sequence_module.main(list(_SIGNED_ARGV)) == 0
    assert sibling_module.main(list(_SIGNED_ARGV)) == 0
    shared = ("actor_id", "authorization_basis", "approved_date",
              "harness_root", "runs", "container_root")
    assert ({key: captured["performance"][key] for key in shared}
            == {key: captured["correctness"][key] for key in shared})
    assert captured["performance"]["runs"] == 3
    assert captured["performance"]["harness_root"] == sequence_module.HARNESS_ROOT
    assert captured["performance"]["manifest"] == "hpc_gemm_performance.yaml"


@pytest.mark.parametrize(
    "dropped",
    ["--actor-id", "--authorization-basis", "--approved-date", "--container-root"],
)
def test_a_promotion_without_a_human_signature_is_a_usage_error(
    monkeypatch, dropped
) -> None:
    """``promote`` is an authenticated human-maintainer surface.

    An identity and what the person actually saw are not defaults, and a date
    that could be omitted would be one the tool chose.
    """
    captured: dict = {}
    monkeypatch.setattr(sequence_module, "promote",
                        _capture_into(captured, "performance"))
    index = _SIGNED_ARGV.index(dropped)
    argv = _SIGNED_ARGV[:index] + _SIGNED_ARGV[index + 2:]
    with pytest.raises(SystemExit):
        sequence_module.main(argv)
    assert not captured


def test_a_control_sequence_refusal_is_reported_rather_than_traced(
    monkeypatch, capsys
) -> None:
    """Both modes answer a refusal with a sentence and an exit code."""
    def _refuse(_args):
        raise sequence_module.ControlSequenceError("the controls did not resolve")

    monkeypatch.setattr(sequence_module, "promote", _refuse)
    assert sequence_module.main(list(_SIGNED_ARGV)) == 5
    assert "REFUSED: the controls did not resolve" in capsys.readouterr().out


# --------------------------------------------------------------------------
# the contract is derived from the manifest, not typed beside it
# --------------------------------------------------------------------------

def _manifest():
    return sequence_module.load_manifest(
        sequence_module.BUILTIN / "hpc_gemm_performance.yaml")


def test_the_contract_covers_the_tiers_this_sequence_actually_runs() -> None:
    """Screen and validate -- not the correctness sequence's screen and certify.

    Validate is the smallest tier at which a spread exists, and a spread is what
    this instrument's verdict rule reads. A contract built for the sibling's
    tiers would attest at a tier these controls never ran.
    """
    from ari.assurance.resolver import normalize_requirements

    manifest = _manifest()
    contract = sequence_module.build_control_contract(manifest)
    atoms = normalize_requirements(contract)
    assert {atom.property_id for atom in atoms} == {PROPERTY}
    assert {atom.tier for atom in atoms} == {"screen", "validate"}
    assert {atom.tier for atom in atoms} == {
        control.tier for control in sequence_module.CONTROLS}
    assert {atom.target_kind for atom in atoms} == set(manifest.target_kinds)


def test_a_manifest_from_another_family_is_refused_by_filename() -> None:
    """Neither sequence may be pointed at the other's family by a file name."""
    with pytest.raises(sequence_module.ControlSequenceError) as caught:
        sequence_module.load_manifest(
            sequence_module.BUILTIN / "hpc_gemm_problem_correctness.yaml")
    assert "this sequence runs" in str(caught.value)


def test_a_drifted_instrument_is_refused_before_any_container_launches(
    tmp_path,
) -> None:
    """Otherwise the refusal arrives after five container launches.

    ``FixedVerifier`` already refuses a drifted driver, correctly, but from
    inside the run loop -- so a repository whose instrument files moved while the
    sequence was running produced minutes of container work and then a bare
    "Harness driver identity drift" traceback.
    """
    drifted = _manifest().model_copy(update={
        "driver": _manifest().driver.model_copy(
            update={"sha256": "sha256:" + "a" * 64})})
    with pytest.raises(sequence_module.ControlSequenceError) as caught:
        sequence_module.run_control_sequence(
            manifest=drifted, container_root=tmp_path,
            working_root=tmp_path / "runs")
    assert "no longer has" in str(caught.value)
    assert "repin_and_promote_harness.py" in str(caught.value)


def test_the_manifest_pins_a_problem_that_ships_both_negative_controls() -> None:
    """Two negatives that fail differently need two files, and the problem has them."""
    manifest = _manifest()
    payloads = {}
    for control in sequence_module.CONTROLS:
        provenance, payload = sequence_module.candidate_source(
            manifest, control.role)
        assert payload, provenance
        payloads[control.role] = payload
    assert len(set(payloads.values())) == 3, (
        "a sequence whose 'two' negatives are the same bytes has one negative")


# --------------------------------------------------------------------------
# the derived isolation fields answer for THIS manifest's driver
# --------------------------------------------------------------------------

def _isolation_for(manifest):
    attestations = _sequence()
    executions = [
        {"network": "deny",
         "container_identity_digest": manifest.container.resolved_digest}
        for _ in attestations
    ]
    unchanged = "sha256:" + "2" * 64
    return sequence_module.isolation_findings(
        manifest,
        executions=executions,
        target_digests={label: (unchanged, unchanged) for label in attestations},
        attestations=attestations,
    )


def test_result_schema_conformance_is_decided_by_this_manifests_own_driver() -> None:
    """The one-verifier assumption, in the field that says the pin is right.

    ``isolation_findings`` is shared between the two promotion surfaces and read
    ``ProblemCorrectnessDriver()`` -- hard-coded. Against THIS manifest it
    therefore compared a pinned ``ari.native-perf-report/v1`` with the
    correctness driver's schema and could only disagree, so
    ``result_schema_conformant`` came back False for a harness whose pin is
    exactly right: a false claim, in registration evidence, about the instrument
    having emitted what was registered.
    """
    manifest = _manifest()
    found = _isolation_for(manifest)
    assert found["basis"]["emitted_result_schema"] == manifest.expected_result_schema
    assert found["result_schema_conformant"] is True
    assert found["basis"]["manifest_pins_that_schema_and_its_digest"] is True


def test_the_isolation_claims_rest_on_what_each_request_carried() -> None:
    """Not on a caller's boolean. Both are derived, and both can come back false."""
    manifest = _manifest()
    found = _isolation_for(manifest)
    assert found["network_isolation"] == "proved"
    assert found["target_write_isolation"] == "proved"
    assert found["basis"]["declared_networks"] == ["deny"]
    assert found["basis"]["container_identity_matched_the_manifest_pin"] is True

    leaked = sequence_module.isolation_findings(
        manifest,
        executions=[{"network": "allow", "container_identity_digest": None}],
        target_digests={"clean-screen": ("sha256:" + "2" * 64,
                                         "sha256:" + "3" * 64)},
        attestations=_sequence(),
    )
    assert leaked["network_isolation"] == "not_proved"
    assert leaked["target_write_isolation"] == "not_proved"


def test_the_weakest_derived_claim_says_what_it_rests_on() -> None:
    """``oracle_visibility`` is read off the manifest, not off an execution.

    Nothing on this path tries to reach the oracle from inside the candidate, so
    the honest thing is to say the field records what the manifest DECLARES.
    """
    found = _isolation_for(_manifest())
    assert found["oracle_visibility"] == "denied"
    assert "not an execution that tried to reach" in (
        found["basis"]["oracle_visibility_note"])


# --------------------------------------------------------------------------
# nothing published may carry host identity, and every byte is covered
# --------------------------------------------------------------------------

#: The evidence-directory name ``repin_and_promote_harness._slug`` derives for
#: this harness id. Only used to spell the paths the guard must name.
_SLUG = "hpc_gemm_performance"


def _published(**overrides) -> dict[str, bytes]:
    kwargs: dict = {
        "slug": _SLUG,
        "artifacts": {"control_sequence.json": b'{"schema_version": "v1"}\n',
                      "logs/clean-screen-stdout.log": b'{"verdict": "pass"}\n'},
        "evidence": {"harness_id": "hpc/gemm-performance"},
        "report": {"decision": "eligible-for-verified"},
        "approval": {"actor_kind": "human-maintainer"},
        "catalog": {"entries": []},
    }
    kwargs.update(overrides)
    return sequence_module.published_artifacts(**kwargs)


def test_every_byte_written_into_the_harness_tree_is_inside_the_guard() -> None:
    published = _published()
    assert set(published) == {
        f"evidence/{_SLUG}/control_sequence.json",
        f"evidence/{_SLUG}/logs/clean-screen-stdout.log",
        f"evidence/{_SLUG}/registration_evidence.json",
        f"reports/{_SLUG}.registration.json",
        f"approvals/{_SLUG}.approval.json",
        "catalog.yaml",
    }
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
def test_a_leak_in_any_published_artifact_is_refused(field, path) -> None:
    """The worker's stdout is the likeliest leak; it was never the only one.

    The refusal names the artifact and the term's INDEX -- never the term, which
    would put the identity into the failure message and from there into CI.
    """
    published = _published(**{field: {"note": str(REPO_ROOT)}})
    with pytest.raises(sequence_module.ControlSequenceError) as caught:
        sequence_module.refuse_host_identity(published)
    message = str(caught.value)
    assert path in message
    assert str(REPO_ROOT) not in message


def test_the_scratch_mode_may_not_write_into_the_registered_harness_tree() -> None:
    """An evidence bundle whose digests carry a signature is not a scratch dir."""
    args = SimpleNamespace(
        manifest="hpc_gemm_performance.yaml",
        container_root=Path("/nonexistent-container-root"),
        output_dir=sequence_module.HARNESS_ROOT / "evidence" / _SLUG,
    )
    with pytest.raises(sequence_module.ControlSequenceError) as caught:
        sequence_module.controls(args)
    assert "not a scratch directory" in str(caught.value)
