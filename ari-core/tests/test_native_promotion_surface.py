"""The native promotion surface and the evidence it may no longer declare.

WHAT WAS WRONG. ``scripts/rqgm_assurance/promote_native_harnesses.py`` runs four
container executions per native family and then handed
``HarnessRegistrationEvidenceV1.create`` seven literal keyword arguments:
``clean_control_verdict="pass"``, ``negative_control_verdict="fail"``,
``official_runner_parity=True``, ``result_schema_conformant=True``,
``network_isolation="proved"``, ``target_write_isolation="proved"`` and
``oracle_visibility="denied"``. The refusals above the call are real, so the
record happened to be true -- which is a different property from being read.
Weaken one refusal, or add a fifth run, and the seven stay exactly as written.

THE REPAIR IS DERIVATION, NOT REFUSAL, and that is the difference between this
surface and ``repin_and_promote_harness.py``, whose ``promote`` was closed at
``d85d9768`` because it ran nothing it could read (see
``test_harness_repin_surface.py``). Here the runs exist, so the fields come off
them.

WHAT IS NOT HERE. The container executions. They need a pinned SIF and a
singularity binary, which are per-site preconditions; a test that skipped when
the image was absent would be a test that usually asserts nothing. So the
subject below is the surface's SOURCE -- read as a syntax tree, which stays true
of a promotion nobody has run -- and the shared derivation exercised against the
manifest this surface actually builds, minted here with no container in sight.
"""

from __future__ import annotations

import ast
import importlib.util
import inspect
import json
import platform
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = (REPO_ROOT / "scripts" / "rqgm_assurance"
               / "promote_native_harnesses.py")


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "promote_native_harnesses", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    # REGISTERED BEFORE EXECUTION, for the same reason the sibling test does it:
    # a class body that resolves its own module out of ``sys.modules`` raises on
    # a NoneType otherwise, before any test is collected.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


promotion = _load_module()
SOURCE = MODULE_PATH.read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# the defect, pinned at the source
# --------------------------------------------------------------------------

#: Every ``HarnessRegistrationEvidenceV1`` field this surface wrote as a
#: constant. The same seven ``test_problem_correctness_control_sequence.py`` and
#: ``test_gemm_performance_control_sequence.py`` apply to their own surfaces, and
#: the same seven ``test_harness_repin_surface.py`` requires to be absent
#: entirely from a surface that runs nothing.
_DECLARED_ON_THIS_SURFACE = {
    "clean_control_verdict",
    "negative_control_verdict",
    "official_runner_parity",
    "result_schema_conformant",
    "network_isolation",
    "target_write_isolation",
    "oracle_visibility",
}


def _literal_evidence_fields(source: str) -> tuple[set[str], set[str]]:
    """``(fields set anywhere, fields handed a constant)`` for one source text.

    Taken as a function of the text rather than run on the module alone so the
    mutation below can ask whether this guard discriminates. A guard that only
    ever runs on code known to be correct has not been shown to fire.
    """
    tree = ast.parse(source)
    seen: set[str] = set()
    literal: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg in _DECLARED_ON_THIS_SURFACE:
                seen.add(keyword.arg)
                if isinstance(keyword.value, ast.Constant):
                    literal.add(keyword.arg)
    return seen, literal


def test_no_registration_evidence_field_is_written_as_a_literal() -> None:
    """Each of the seven must be fed a value that came from somewhere."""
    seen, literal = _literal_evidence_fields(SOURCE)
    assert not literal, (
        f"{sorted(literal)} handed a literal; that is exactly the defect this "
        f"surface exists to have removed")
    assert seen == _DECLARED_ON_THIS_SURFACE, (
        f"not set at all: {sorted(_DECLARED_ON_THIS_SURFACE - seen)}")


def test_the_literal_guard_actually_fires() -> None:
    """One field put back as a constant must be caught, not all seven together.

    The guard above passes on any source that never mentions the fields, so it
    is worth knowing it discriminates. Every field is restored one at a time.
    """
    for field in sorted(_DECLARED_ON_THIS_SURFACE):
        mutated = SOURCE.replace(
            f"{field}=run[", f'{field}="proved", _unused=run[', 1)
        if mutated == SOURCE:  # fed from a call rather than a subscript
            mutated = SOURCE.replace(
                f"{field}=bool(", f'{field}=True, _unused=bool(', 1)
        assert mutated != SOURCE, f"{field} is fed by neither shape any more"
        _, literal = _literal_evidence_fields(mutated)
        assert field in literal, f"a literal {field} was not caught"


#: The exact block this change replaced, restored verbatim. Kept as text rather
#: than described, so the mutation below is the defect and not an approximation
#: of it.
_THE_DECLARED_SEVEN = """                clean_control_verdict="pass",
                negative_control_verdict="fail",
                official_runner_parity=True,
                result_schema_conformant=True,
                network_isolation="proved",
                target_write_isolation="proved",
                oracle_visibility="denied",
"""


def _the_derived_block() -> str:
    start = SOURCE.index("                clean_control_verdict=run[")
    end = SOURCE.index('                run_count=len(run["attestations"]),')
    return SOURCE[start:end]


def test_the_whole_defect_restored_is_caught_and_so_is_its_removal() -> None:
    """Both directions, because the guard has two halves and they differ.

    Putting the seven back is the regression. Deleting them is what a surface
    that quietly stopped writing evidence at all would look like, and the
    ``seen ==`` half is the only thing that catches it.
    """
    regressed = SOURCE.replace(_the_derived_block(), _THE_DECLARED_SEVEN)
    assert regressed != SOURCE
    seen, literal = _literal_evidence_fields(regressed)
    assert literal == _DECLARED_ON_THIS_SURFACE

    removed = SOURCE.replace(_the_derived_block(), "")
    assert removed != SOURCE
    seen, literal = _literal_evidence_fields(removed)
    assert not literal, "no field is a literal, and the guard would pass on that"
    assert seen != _DECLARED_ON_THIS_SURFACE, (
        "a surface that writes none of the seven has not derived them")


def test_the_attestation_digests_are_the_runs_and_not_the_report() -> None:
    """The half of this surface that was already right. CONFIRMED, not changed.

    ``repin_and_promote_harness`` pointed this field at its own registration
    report, so the bundle cited itself as the execution it never performed. Here
    it has always been the attestations the four executions returned -- which is
    why the shipped native bundles, written by that other surface, disagree with
    what this one would produce.
    """
    tree = ast.parse(SOURCE)
    keywords = [keyword for node in ast.walk(tree) if isinstance(node, ast.Call)
                for keyword in node.keywords
                if keyword.arg == "attestation_digests"]
    assert len(keywords) == 1
    fed = ast.unparse(keywords[0].value)
    assert fed == "attestation_digests"
    source_of = [node for node in ast.walk(tree)
                 if isinstance(node, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == "attestation_digests"
                         for t in node.targets)]
    assert len(source_of) == 1
    built = ast.unparse(source_of[0].value)
    # ``ast.unparse`` normalises string quoting, so this reads the single-quoted
    # form whatever the file spells.
    assert "attestation_digest" in built and "run['attestations']" in built
    assert "report" not in built, (
        "pointing this at the registration report is the bundle citing itself "
        "as the execution it never performed")


# --------------------------------------------------------------------------
# derived, and derived ONCE
# --------------------------------------------------------------------------

def test_the_derivations_are_imported_rather_than_reimplemented() -> None:
    """A second copy of these rules is two claims free to drift apart.

    ``isolation_findings`` and ``_single`` already exist on the sibling
    attestation surface, and ``attest_gemm_performance`` already reaches them the
    same way. This file must not grow its own.
    """
    tree = ast.parse(SOURCE)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "attest_problem_correctness":
            imported.update(alias.name for alias in node.names)
    assert {"isolation_findings", "_single"} <= imported

    defined = {node.name for node in ast.walk(tree)
               if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert not defined & {"isolation_findings", "_single",
                          "check_control_sequence"}
    assert promotion.isolation_findings.__module__ == "attest_problem_correctness"
    assert promotion._single.__module__ == "attest_problem_correctness"

    # AND NO SECOND COPY UNDER ANOTHER NAME. The isolation vocabulary is
    # ``isolation_findings``' to produce; this surface passing it through means
    # the word should not appear as a value anywhere in this module's CODE.
    # Docstrings are excluded rather than searched, because the docstrings here
    # quote the literals that were removed -- a guard that refused an accurate
    # account of the defect is a guard that gets switched off.
    docstrings = {id(node.body[0].value) for node in ast.walk(tree)
                  if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                       ast.AsyncFunctionDef))
                  and node.body and isinstance(node.body[0], ast.Expr)
                  and isinstance(node.body[0].value, ast.Constant)
                  and isinstance(node.body[0].value.value, str)}
    spelled = {node.value for node in ast.walk(tree)
               if isinstance(node, ast.Constant) and isinstance(node.value, str)
               and id(node) not in docstrings}
    assert not spelled & {"proved", "not_proved", "denied"}, (
        "an isolation verdict word is a value in this module; either it is "
        "being written directly or there are two derivations of it")


def test_the_control_group_is_the_library_that_was_staged() -> None:
    """``role`` picks the ``.so`` AND picks the group. One field, so one fact."""
    controls = promotion.REGISTRATION_CONTROLS
    assert [item.label for item in controls] == [
        "clean-screen", "clean-certify", "clean-certify-repeat", "negative-screen"]
    assert [item.verdict for item in controls] == ["pass", "pass", "pass", "fail"]
    assert [item.tier for item in controls] == [
        "screen", "certify", "certify", "screen"], (
        "two certify executions are what the module docstring promises")
    assert [item.retry_index for item in controls] == [0, 0, 1, 0], (
        "the repeat is at a different retry index, so the claim is stability "
        "across instances rather than digest equality")
    reference = {item.label for item in controls if item.role == "reference"}
    negative = {item.label for item in controls if item.role != "reference"}
    assert reference == {"clean-screen", "clean-certify", "clean-certify-repeat"}
    assert negative == {"negative-screen"}
    assert not reference & negative


def test_the_expected_verdicts_are_not_a_second_list_of_the_same_labels() -> None:
    """They were, and a label could be checked for without ever being run."""
    for label in (item.label for item in promotion.REGISTRATION_CONTROLS):
        assert f'"{label}": "pass"' not in SOURCE
        assert f'"{label}": "fail"' not in SOURCE


def test_a_group_whose_runs_disagree_collapses_to_not_available() -> None:
    """``_single`` is the honest answer, not a pick. Unreachable, deliberately.

    ``_run_registration`` refuses before this can be reached, which is the
    point: the value that survives is never a literal even in the case the
    refusal was supposed to have caught.
    """
    assert promotion._single(["pass", "pass", "pass"]) == "pass"
    assert promotion._single(["fail"]) == "fail"
    assert promotion._single(["pass", "fail"]) == "not_available"
    assert promotion._single([]) == "not_available"


# --------------------------------------------------------------------------
# the shared derivation, against the manifest THIS surface builds
# --------------------------------------------------------------------------

def _manifest(kind: str = "gemm"):
    """Exactly what ``promote`` registers, minted with no container involved.

    Not a shipped ``builtin/*.yaml``: those were written by another surface and
    pin whatever was current when it ran, so a schema or driver move elsewhere
    would fail this file for a reason that is not about it. ``_manifest``
    computes its pins from the tree, which is what makes the assertions below
    statements about this surface.
    """
    return promotion._manifest(
        kind=kind,
        source_commit="0" * 40,
        repository="https://example.invalid/ari",
        container_digest="sha256:" + "a" * 64,
        license_inventory_digest="sha256:" + "b" * 64,
        parity={"negative_control_report_digest": "sha256:" + "c" * 64,
                "report_digest": "sha256:" + "d" * 64},
        architecture=platform.machine(),
    )


def _executions(manifest, *, network: str = "deny", container=...):
    digest = (manifest.container.resolved_digest if container is ...
              else container)
    return [{"network": network, "container_identity_digest": digest}
            for _ in promotion.REGISTRATION_CONTROLS]


def _attestations(status: str = "ready"):
    return {item.label: SimpleNamespace(infrastructure_status=status)
            for item in promotion.REGISTRATION_CONTROLS}


def _unchanged_targets():
    digest = "sha256:" + "2" * 64
    return {item.label: (digest, digest)
            for item in promotion.REGISTRATION_CONTROLS}


@pytest.mark.parametrize("kind", sorted(promotion.KIND_CONFIG))
def test_the_shared_derivation_reads_this_family_the_same_way(kind: str) -> None:
    """The shapes DO allow reuse, for every registered native family.

    ``isolation_findings`` resolves the driver from ``manifest.driver.revision``
    rather than from the family it was written for, so it answers about
    ``NativeHPCDriver`` here without an edit -- which is the property that made
    reuse the repair instead of a second implementation.
    """
    manifest = _manifest(kind)
    found = promotion.isolation_findings(
        manifest,
        executions=_executions(manifest),
        target_digests=_unchanged_targets(),
        attestations=_attestations(),
    )
    assert found["network_isolation"] == "proved"
    assert found["target_write_isolation"] == "proved"
    assert found["oracle_visibility"] == "denied"
    assert found["result_schema_conformant"] is True
    basis = found["basis"]
    assert basis["declared_networks"] == ["deny"]
    assert basis["container_identity_matched_the_manifest_pin"] is True
    assert basis["emitted_result_schema"] == manifest.expected_result_schema, (
        "the driver whose schema is compared must be the one this manifest "
        "pins; a hard-coded family here is the one-verifier assumption landing "
        "in the field that says the instrument emitted what was registered")
    assert set(basis["target_digest_unchanged_by_run"]) == {
        item.label for item in promotion.REGISTRATION_CONTROLS}


def test_every_isolation_claim_can_come_back_negative() -> None:
    """Otherwise it is the literal again, spelled with a function call."""
    manifest = _manifest()
    changed = "sha256:" + "3" * 64
    leaked = promotion.isolation_findings(
        manifest,
        executions=_executions(manifest, network="allow", container=None),
        target_digests={item.label: ("sha256:" + "2" * 64, changed)
                        for item in promotion.REGISTRATION_CONTROLS},
        attestations=_attestations(),
    )
    assert leaked["network_isolation"] == "not_proved"
    assert leaked["target_write_isolation"] == "not_proved"

    degraded = promotion.isolation_findings(
        manifest,
        executions=_executions(manifest),
        target_digests=_unchanged_targets(),
        attestations=_attestations(status="infrastructure_error"),
    )
    assert degraded["result_schema_conformant"] is False, (
        "a run whose stdout never parsed into the typed report has not shown "
        "the instrument emitted the schema the manifest registered")


def test_the_weakest_derived_claim_says_what_it_rests_on() -> None:
    """``oracle_visibility`` is read off the manifest, not off an execution."""
    manifest = _manifest()
    found = promotion.isolation_findings(
        manifest,
        executions=_executions(manifest),
        target_digests=_unchanged_targets(),
        attestations=_attestations(),
    )
    assert "not an execution that tried to reach" in (
        found["basis"]["oracle_visibility_note"])


# --------------------------------------------------------------------------
# and the runs have to carry what the derivation reads
# --------------------------------------------------------------------------

def _observe_body() -> ast.AST:
    tree = ast.parse(SOURCE)
    outer = next(node for node in ast.walk(tree)
                 if isinstance(node, ast.FunctionDef)
                 and node.name == "_run_registration")
    return next(node for node in ast.walk(outer)
                if isinstance(node, ast.FunctionDef) and node.name == "observe")


def test_the_execution_record_carries_what_the_request_carried() -> None:
    """Not what the manifest asked for. That is the whole strength of the claim.

    ``container_digest`` in the same record is copied off the manifest, so it
    says the same thing whether or not a run honoured the pin. These two are read
    from the ``ExecutionRequest`` the executor was handed, and without them
    ``isolation_findings`` has nothing to derive ``network_isolation`` from.
    """
    keys: dict[str, str] = {}
    for node in ast.walk(_observe_body()):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    keys[key.value] = ast.unparse(value)
    assert "request.execution_request.network" == keys.get("network")
    assert "request.execution_request.container" in keys.get(
        "container_identity_digest", "")
    assert "manifest" not in keys.get("network", "manifest")


def test_the_candidate_digest_is_read_back_after_every_run() -> None:
    """``target_write_isolation`` names an observation, not a known invariant.

    ``FixedVerifier`` does refuse to mint an attestation when the digest moved,
    so the claim would be true either way -- but a record whose reader has to
    know that is a record that asserts it.
    """
    tree = ast.parse(SOURCE)
    assigns = [node for node in ast.walk(tree) if isinstance(node, ast.Assign)
               and any(isinstance(t, ast.Subscript)
                       and isinstance(t.value, ast.Name)
                       and t.value.id == "target_digests" for t in node.targets)]
    assert len(assigns) == 1
    recorded = ast.unparse(assigns[0].value)
    assert "declaration.target_digest" in recorded
    assert "workspace.file_digest" in recorded, (
        "the second half must be re-read from the workspace; declaring it twice "
        "would compare a value with itself")


def test_the_derivation_is_published_beside_its_answer() -> None:
    """So a reader can recompute the seven instead of trusting them.

    The after-run candidate digest is in no other artifact, so without this the
    bundle would carry a derived ``target_write_isolation`` that nothing in it
    could check.
    """
    assert '"control_derivation.json"' in SOURCE
    tree = ast.parse(SOURCE)
    derivation = [node for node in ast.walk(tree) if isinstance(node, ast.Assign)
                  and any(isinstance(t, ast.Name) and t.id == "derivation"
                          for t in node.targets)]
    assert derivation, "the derivation record is not built"
    built = ast.unparse(derivation[0].value)
    for field in ("clean_control_verdict", "negative_control_verdict",
                  "isolation", "observed_verdict"):
        assert field in built


# --------------------------------------------------------------------------
# re-registration: replacing a signed bundle, and the ways that must refuse
#
# THE SITUATION. The three native bundles on disk were written by an older
# writer and cite their own registration report where ``attestation_digests``
# should name the four executions. The executions happened and their artifacts
# are pinned and verifiable -- this is a wrong citation, not the "nothing ran"
# defect ``repin_and_promote_harness`` had -- but the field cannot be corrected,
# because ``_immutable_outputs`` refuses every existing artifact whose bytes
# change and the surface now derives seven fields it used to declare, so a
# second promotion necessarily differs.
#
# The guard is right about what it was built for. What it did not draw is the
# line between SILENTLY CHANGING an artifact and a SIGNED RE-REGISTRATION, and
# these are the tests of that line. None of them needs a container: the subject
# is the guard and the receipt that authorises it, both of which are functions
# over paths and bytes.
# --------------------------------------------------------------------------

_REPLACED_ID = "hpc/gemm-correctness"


def _staged_bundle(root: Path, marker: str):
    """One run's complete output for one harness: ``(bundle_root, bytes, runs)``.

    Two calls with different markers are two different runs producing the same
    file NAMES with different bytes and different attestation digests, which is
    what a re-registration is. Names, not contents, are what the all-or-nothing
    rule is about.
    """
    bundle = root / "evidence" / "hpc_gemm_correctness"
    attestations: dict[str, SimpleNamespace] = {}
    outputs: dict[Path, bytes] = {}
    for index, control in enumerate(promotion.REGISTRATION_CONTROLS):
        digest = "sha256:" + f"{index}{marker}" * 32
        attestations[control.label] = SimpleNamespace(attestation_digest=digest)
        outputs[bundle / f"{control.label}.attestation.json"] = json.dumps(
            {"attestation_digest": digest, "verdict": control.verdict},
            sort_keys=True).encode("utf-8")
    outputs[bundle / "registration_evidence.json"] = (
        b'{"run": "' + marker.encode() + b'"}\n')
    outputs[bundle / "resource_measurements.json"] = (
        b'{"run": "' + marker.encode() + b'"}\n')
    outputs[bundle / "logs" / "clean-screen-stdout.log"] = marker.encode() + b"\n"
    outputs[root / "builtin" / "hpc_gemm_correctness.yaml"] = (
        b"id: hpc/gemm-correctness\n")
    outputs[root / "reports" / "hpc_gemm_correctness.registration.json"] = (
        b'{"run": "' + marker.encode() + b'"}\n')
    outputs[root / "approvals" / "hpc_gemm_correctness.approval.json"] = (
        b'{"run": "' + marker.encode() + b'"}\n')
    return bundle, outputs, attestations


def _put(outputs: dict[Path, bytes]) -> None:
    for path, payload in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)


def _receipt(bundle: Path, outputs: dict[Path, bytes], attestations):
    return promotion._bundle_replacement(
        harness_id=_REPLACED_ID,
        bundle_root=bundle,
        produced=frozenset(outputs),
        outputs=outputs,
        attestations=attestations,
    )


def test_a_plain_promotion_of_an_already_promoted_harness_still_refuses(
        tmp_path: Path) -> None:
    """The guard's original job, unchanged, and now it says where the path is.

    This is the case the three stale bundles hit today. It must keep refusing:
    rewriting registration history under a signature given for different bytes
    is the thing the immutable rule exists to stop. What is new is that the
    refusal names the act that IS allowed and what it costs, rather than leaving
    a maintainer to conclude the bundles can never be corrected.
    """
    bundle, first, _ = _staged_bundle(tmp_path, "a")
    _put(first)
    _, second, _ = _staged_bundle(tmp_path, "b")

    with pytest.raises(RuntimeError) as excinfo:
        promotion._immutable_outputs(second, mutable_catalog=tmp_path / "catalog.yaml")
    message = str(excinfo.value)
    assert "already differs" in message
    assert "--re-register" in message, "the refusal does not say the path exists"
    assert "signature" in message, "nor what it costs"
    for path, payload in first.items():
        assert path.read_bytes() == payload, "a refused promotion wrote something"


def test_the_re_registration_path_replaces_a_bundle_it_produced_whole(
        tmp_path: Path) -> None:
    """Named explicitly, every produced path lands, including the signed ones."""
    bundle, first, _ = _staged_bundle(tmp_path, "a")
    _put(first)
    _, second, attestations = _staged_bundle(tmp_path, "b")

    promotion._immutable_outputs(
        second,
        mutable_catalog=tmp_path / "catalog.yaml",
        replacements=(_receipt(bundle, second, attestations),),
    )
    for path, payload in second.items():
        assert path.read_bytes() == payload
    assert (bundle / "registration_evidence.json").read_bytes() != (
        first[bundle / "registration_evidence.json"])


def test_a_bundle_this_run_did_not_produce_whole_is_refused(
        tmp_path: Path) -> None:
    """ALL-OR-NOTHING. One survivor is one directory describing two runs.

    This is not hypothetical, and ``gate_findings.json`` is the file it happened
    to. ``01c87015`` rewrote it, ``measurement_environment.json``,
    ``multiple_run_stability.json``, ``registration_report.json`` and the
    registration evidence, and left the four attestations from an earlier day
    untouched -- one bundle, two runs, and nothing in it saying so. The rule
    below is why that cannot recur; ``_BUNDLE_ARTIFACTS_THIS_RUN_PRODUCES``
    below is why it is satisfiable, since a rule no run can meet is a rule that
    gets passed a flag instead.
    """
    bundle, first, _ = _staged_bundle(tmp_path, "a")
    _put(first)
    (bundle / "gate_findings.json").write_bytes(b'{"writer": "an older one"}\n')
    _, second, attestations = _staged_bundle(tmp_path, "b")

    with pytest.raises(RuntimeError) as excinfo:
        promotion._immutable_outputs(
            second,
            mutable_catalog=tmp_path / "catalog.yaml",
            replacements=(_receipt(bundle, second, attestations),),
        )
    message = str(excinfo.value)
    assert "partial re-registration refused" in message
    assert "gate_findings.json" in message, "the refusal must name the survivor"
    for path, payload in first.items():
        assert path.read_bytes() == payload, "a refused replacement wrote something"


def test_a_receipt_may_not_claim_a_path_this_run_did_not_write(
        tmp_path: Path) -> None:
    """The other half of all-or-nothing: no permission without a produced byte."""
    bundle, outputs, attestations = _staged_bundle(tmp_path, "a")
    smuggled = promotion.BundleReplacement(
        _REPLACED_ID, bundle,
        frozenset(outputs) | {bundle / "not_produced_here.json"})
    with pytest.raises(RuntimeError, match="did not produce"):
        promotion._immutable_outputs(
            outputs, mutable_catalog=tmp_path / "catalog.yaml",
            replacements=(smuggled,))


def test_a_receipt_cannot_be_minted_without_the_runs(tmp_path: Path) -> None:
    """THE STRUCTURAL TIE. Permission to overwrite is a receipt for executions.

    Each refusal here is a different way of holding a replacement for runs that
    did not happen: none of the controls attested, some of them attested, and --
    the one a caller could otherwise arrange -- all four attested but the bytes
    staged for the bundle belonging to a different run.
    """
    bundle, outputs, attestations = _staged_bundle(tmp_path, "a")

    with pytest.raises(RuntimeError, match="controls attested"):
        _receipt(bundle, outputs, {})

    short = dict(attestations)
    short.pop("negative-screen")
    with pytest.raises(RuntimeError, match="controls attested"):
        _receipt(bundle, outputs, short)

    foreign = dict(attestations)
    foreign["clean-screen"] = SimpleNamespace(
        attestation_digest="sha256:" + "f" * 64)
    with pytest.raises(RuntimeError, match="do not carry the digest"):
        _receipt(bundle, outputs, foreign)

    # AND A REPLACEMENT MUST RESTATE THE BUNDLE'S OWN INDEX. Leaving the old
    # registration evidence in place beside new attestations is the citation
    # defect again, this time with the artifacts moved instead of the field.
    without_index = {path: payload for path, payload in outputs.items()
                     if path.name != "registration_evidence.json"}
    with pytest.raises(RuntimeError, match="registration_evidence.json"):
        promotion._bundle_replacement(
            harness_id=_REPLACED_ID, bundle_root=bundle,
            produced=frozenset(without_index), outputs=without_index,
            attestations=attestations)


def test_the_only_place_a_receipt_is_minted_is_the_one_tied_to_the_runs() -> None:
    """Read at the source, because the tie is a property of the code's shape.

    A second construction site is a second set of rules about when replacing a
    signed artifact is allowed, and the two are free to drift apart -- which is
    the objection this surface's own docstring makes about reimplementing
    ``isolation_findings``.
    """
    tree = ast.parse(SOURCE)
    minted = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
              and isinstance(node.func, ast.Name)
              and node.func.id == "BundleReplacement"]
    assert len(minted) == 1, "a replacement is constructed somewhere else too"
    owners = [node.name for node in ast.walk(tree)
              if isinstance(node, ast.FunctionDef)
              and any(child is minted[0] for child in ast.walk(node))]
    assert owners == ["_bundle_replacement"]

    called = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
              and isinstance(node.func, ast.Name)
              and node.func.id == "_bundle_replacement"]
    assert len(called) == 1
    fed = {keyword.arg: ast.unparse(keyword.value)
           for keyword in called[0].keywords}
    assert fed["attestations"] == "run['attestations']", (
        "the receipt must be minted from what the executions returned; fed "
        "anything else it is a flag with extra steps")
    assert fed["outputs"] == "outputs", (
        "and checked against the bytes actually staged for the write")


def test_re_registration_is_never_a_default_and_never_a_fallback() -> None:
    """Explicit at the call site, per harness, or it does not happen."""
    assert inspect.signature(
        promotion._immutable_outputs).parameters["replacements"].default == ()

    tree = ast.parse(SOURCE)
    flag = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_argument"
            and node.args and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "--re-register"]
    assert len(flag) == 1, "the re-registration path has no explicit call site"
    kwargs = {keyword.arg: ast.unparse(keyword.value)
              for keyword in flag[0].keywords}
    assert kwargs["default"] == "[]", "an on-by-default re-registration"
    assert kwargs["action"] == "'append'", (
        "it names WHICH harnesses may be replaced; a boolean would replace "
        "every bundle a run touched")
    assert "const" not in kwargs and "nargs" not in kwargs
    assert "--re-register" in (promotion.__doc__ or "")


def test_an_unknown_harness_id_is_refused_before_any_container_work(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The cheap question first, and it is a real question.

    ``hpc/gemm-performance`` is a real harness that this surface does not
    register -- ``attest_gemm_performance.py`` does. Naming it here must refuse
    rather than quietly re-register nothing. The container root does not exist,
    so if the check moved below the container work this would fail with a
    missing path instead.
    """
    monkeypatch.setattr(promotion, "_source_identity",
                        lambda: ("0" * 40, "https://example.invalid/ari"))
    args = SimpleNamespace(
        re_register=["hpc/gemm-performance"],
        container_root=tmp_path / "absent",
        container_rootfs=tmp_path / "absent",
    )
    with pytest.raises(RuntimeError, match="does not register"):
        promotion.promote(args)


def test_a_promotion_that_never_mentions_the_flag_grants_nothing(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Absence is not an error, and it is not permission either."""
    monkeypatch.setattr(promotion, "_source_identity",
                        lambda: ("0" * 40, "https://example.invalid/ari"))
    args = SimpleNamespace(
        container_root=tmp_path / "absent",
        container_rootfs=tmp_path / "absent",
    )
    # Past the re-registration reading -- which granted nothing -- and stopped
    # by the missing container, which is the next thing ``promote`` asks for.
    with pytest.raises(FileNotFoundError):
        promotion.promote(args)


def test_the_re_registration_path_did_not_restore_a_declared_field() -> None:
    """The seven, re-checked at the syntax tree after this change.

    A re-registration path is exactly where a second evidence builder would be
    tempting -- "the same bundle, rewritten" -- and a second builder is a second
    place the seven can be declared. There is one, and it derives all of them.
    """
    seen, literal = _literal_evidence_fields(SOURCE)
    assert not literal, f"{sorted(literal)} is a literal again"
    assert seen == _DECLARED_ON_THIS_SURFACE

    tree = ast.parse(SOURCE)
    builders = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "create"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "HarnessRegistrationEvidenceV1"]
    assert len(builders) == 1, (
        "a second registration-evidence builder is a second place the seven "
        "can be written by hand")
    fed = {keyword.arg: ast.unparse(keyword.value)
           for keyword in builders[0].keywords}
    assert fed["attestation_digests"] == "attestation_digests"
    assert "report" not in fed["attestation_digests"], (
        "the shipped bundles point this at their own registration report; the "
        "surface that regenerates them must not")


# --------------------------------------------------------------------------
# the run produces the WHOLE bundle
#
# The all-or-nothing rule above and the artifact set this surface writes are one
# question asked twice. Every shipped native bundle carries four artifacts that
# were written by ``repin_and_promote_harness.py``'s promote -- a surface that
# ran nothing, closed at ``d85d9768`` -- while the attestations beside them came
# from a real run on another day. So the bundle could not be reproduced by the
# surface that owns it, and the rule that refuses a partial replacement would
# have refused every honest re-registration for ever.
# --------------------------------------------------------------------------

#: What the three shipped bundles hold, minus the artifacts named per control.
#: Read off the tree rather than typed, so a bundle that grows a file makes this
#: fail rather than silently leaving it outside the guard.
_BUNDLE_ARTIFACTS_THIS_RUN_PRODUCES = (
    "registration_report.json",
    "gate_findings.json",
    "multiple_run_stability.json",
    "measurement_environment.json",
    "resource_measurements.json",
    "control_derivation.json",
    "official_runner_parity.json",
    "registration_evidence.json",
)


def _promote_body() -> ast.FunctionDef:
    tree = ast.parse(SOURCE)
    functions = [node for node in ast.walk(tree)
                 if isinstance(node, ast.FunctionDef) and node.name == "promote"]
    assert len(functions) == 1
    return functions[0]


def _first_call_line(scope: ast.AST, name: str) -> int:
    """Where ``name`` is first called inside ``scope``. Order is the subject."""
    lines = [node.lineno for node in ast.walk(scope)
             if isinstance(node, ast.Call)
             and ((isinstance(node.func, ast.Name) and node.func.id == name)
                  or (isinstance(node.func, ast.Attribute)
                      and node.func.attr == name))]
    assert lines, f"{name} is not called here"
    return min(lines)


def test_the_bundle_this_surface_writes_is_the_bundle_that_is_on_disk() -> None:
    """Every file of a shipped bundle is one this run stages.

    Checked against the tree, not against a list in this file: the three
    directories are the thing the replacement rule walks, so if one of them
    holds a name the surface never writes, ``--re-register`` refuses and the
    stale citation stays. Per-control artifacts are excluded because their names
    come from ``REGISTRATION_CONTROLS`` and the logs from what each run emitted.
    """
    labels = {control.label for control in promotion.REGISTRATION_CONTROLS}
    staged = set(_BUNDLE_ARTIFACTS_THIS_RUN_PRODUCES)
    for name in staged:
        # Two shapes: a plain key, and an f-string that prefixes the evidence
        # directory onto it. Both are writes, so the name alone is the question.
        assert name in SOURCE, f"{name} is in no shipped bundle write"

    root = REPO_ROOT / "ari-core" / "config" / "harnesses" / "evidence"
    for slug in ("hpc_gemm_correctness", "hpc_spmm_correctness",
                 "hpc_stencil_correctness"):
        bundle = root / slug
        if not bundle.is_dir():  # pragma: no cover - unregistered checkout
            pytest.skip(f"{slug} is not registered in this checkout")
        unaccounted = sorted(
            path.relative_to(bundle).as_posix()
            for path in bundle.rglob("*")
            if path.is_file()
            and path.parent != bundle / "logs"
            and path.name not in staged
            and path.name not in {f"{label}.attestation.json" for label in labels}
        )
        assert not unaccounted, (
            f"{slug} holds {unaccounted}, which this surface's run does not "
            f"produce; --re-register would refuse the bundle whole")


def test_the_registration_report_is_earned_before_the_evidence_pins_it() -> None:
    """Order, because the evidence can only pin artifacts that already exist.

    ``registration_report.json`` is inside the bundle and inside
    ``evidence_artifact_digests``. Built before the report is earned, the
    evidence would pin every artifact except the report the approval it is
    signed beside names -- which is the shape the shipped bundles have.
    """
    promote = _promote_body()
    earned = _first_call_line(promote, "register_harness")
    pinned = _first_call_line(promote, "create")
    assert earned < pinned, (
        "the registration evidence is built before the report it must pin")

    tree = ast.parse(SOURCE)
    staged = [node for node in ast.walk(tree) if isinstance(node, ast.Assign)
              and any(isinstance(t, ast.Subscript)
                      and isinstance(t.slice, ast.Constant)
                      and t.slice.value == "registration_report.json"
                      for t in node.targets)]
    assert len(staged) == 1, "the report is staged into the bundle nowhere, or twice"
    assert ast.unparse(staged[0].value) == "_json_bytes(report)", (
        "the bundle's copy of the report must be the report this run earned")


def test_the_gate_findings_are_read_off_the_report_and_not_stamped() -> None:
    """The defect ``ccdedc9`` removed, checked where it would come back.

    A dict comprehension over ``report.gates`` cannot say ``passed`` about a
    gate that did not pass; a literal beside a gate id can, and that is exactly
    what this surface used to hand ``registration_report``.
    """
    tree = ast.parse(SOURCE)
    staged = [node for node in ast.walk(tree) if isinstance(node, ast.Assign)
              and any(isinstance(t, ast.Subscript)
                      and isinstance(t.slice, ast.Constant)
                      and t.slice.value == "gate_findings.json"
                      for t in node.targets)]
    assert len(staged) == 1
    built = ast.unparse(staged[0].value)
    assert "for gate in report.gates" in built, "the findings are not a reading"
    assert "gate.passed" in built and "gate.gate_id" in built
    assert "True" not in built, "a stamped verdict is back"


def test_the_environment_is_read_before_any_run_can_put_a_site_path_in_it() -> None:
    """``_run_registration`` exports ``ARI_HARNESS_CONTAINER_ROOT``.

    ``measurement_environment`` captures by prefix, so that variable's VALUE --
    a site path -- is inside the capture for exactly as long as a run lasts.
    Read before the first run it cannot be, which is a property of where the
    call sits and of nothing else.
    """
    promote = _promote_body()
    read = _first_call_line(promote, "measurement_environment")
    ran = _first_call_line(promote, "_run_registration")
    assert read < ran, (
        "the measurement environment is captured while a run has a site path "
        "exported into it")

    tree = ast.parse(SOURCE)
    scrubbed = [node for node in ast.walk(tree) if isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Subscript)
                        and isinstance(t.slice, ast.Constant)
                        and t.slice.value == "variables"
                        for t in node.targets)]
    assert len(scrubbed) == 1
    assert "scrub_host_identity" in ast.unparse(scrubbed[0].value)


def test_every_published_byte_passes_the_host_identity_guard_before_the_write(
) -> None:
    """One call, over the whole output map, above the only write.

    The sibling surface learned this as a shape rather than as more guard calls:
    four published artifacts were written past a guard that covered the evidence
    bundle only. Here there is one map and one write, so the coverage is
    structural.
    """
    promote = _promote_body()
    guarded = _first_call_line(promote, "refuse_host_identity")
    written = _first_call_line(promote, "_immutable_outputs")
    assert guarded < written, "the guard runs after the write"

    calls = [node for node in ast.walk(promote) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Name)
             and node.func.id == "refuse_host_identity"]
    assert len(calls) == 1, "a second guard call is a second answer about coverage"
    fed = ast.unparse(calls[0].args[0])
    assert "outputs.items()" in fed, (
        "the guard must see every published byte, not one bundle's worth")


def test_the_host_identity_guard_actually_refuses_this_surfaces_outputs() -> None:
    """The guard is imported, not reimplemented, and it fires on a real term."""
    assert promotion.refuse_host_identity.__module__ == "attest_problem_correctness"
    home = str(Path.home())
    with pytest.raises(Exception, match="host identity"):
        promotion.refuse_host_identity(
            {"evidence/x/measurement_environment.json":
             f'{{"variables": {{"ARI_X": "{home}/thing"}}}}'.encode("utf-8")})
    promotion.refuse_host_identity(
        {"evidence/x/measurement_environment.json": b'{"variables": {}}'})


# --- the placement pin is honoured on THIS surface too -----------------------
#
# The pin was enforced by two of the three promotion surfaces. `prepare()`
# refuses off-placement, but only once a REQUEST exists, so a surface that
# measures before minting one is unprotected -- and this was that surface. It
# was harmless only because the three families it serves pin an EMPTY
# placement, which is a fact about today's manifests, not about this code.

class _PinnedManifest:
    """Just the two attributes the refusal reads."""

    def __init__(self, placement):
        self.id = "hpc/fixture"
        self.registered_placement = placement


def test_a_manifest_that_pins_no_placement_claims_no_machine():
    # An empty pin is a pass because the comparison says so, not because it is
    # exempted -- which is what keeps the three shipped families working while
    # the guard is live for anything that does pin.
    promotion.refuse_off_pinned_placement(
        _PinnedManifest({}), here={"machine": "x86_64", "thread_budget": "96"})
    promotion.refuse_off_pinned_placement(
        _PinnedManifest(None), here={"machine": "aarch64"})


def test_measuring_off_the_pinned_placement_is_refused_before_anything_runs():
    with pytest.raises(RuntimeError, match="is not the placement"):
        promotion.refuse_off_pinned_placement(
            _PinnedManifest({"machine": "aarch64", "thread_budget": "48"}),
            here={"machine": "x86_64", "thread_budget": "96"})


def test_the_refusal_names_both_halves_so_the_reader_can_act():
    with pytest.raises(RuntimeError) as excinfo:
        promotion.refuse_off_pinned_placement(
            _PinnedManifest({"thread_budget": "2"}), here={"thread_budget": "96"})
    message = str(excinfo.value)
    # Deterministic and self-explaining: a retry loop that cannot tell this from
    # an unresolved measurement burns an allocation repeating it.
    assert "'2', '96'" in message.replace('"', "'")


def test_a_matching_placement_is_not_refused():
    promotion.refuse_off_pinned_placement(
        _PinnedManifest({"machine": "x86_64", "thread_budget": "2"}),
        here={"machine": "x86_64", "thread_budget": "2", "extra": "ignored"})


def test_promote_calls_the_refusal_before_it_runs_a_registration():
    """Order is the property, not presence: refusing after measuring is no guard."""
    tree = ast.parse(SOURCE)
    promote = next(n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef) and n.name == "promote")
    calls = [n.func.id for n in ast.walk(promote)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id in {"refuse_off_pinned_placement", "_run_registration"}]
    assert calls, "promote calls neither the refusal nor a registration"
    assert calls[0] == "refuse_off_pinned_placement", (
        f"promote reaches {calls[0]} before refusing off-placement")
