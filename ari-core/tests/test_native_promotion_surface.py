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
