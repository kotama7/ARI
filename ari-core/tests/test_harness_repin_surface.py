"""The re-pin surface, and the registration evidence it can no longer invent.

WHAT WAS WRONG. ``scripts/rqgm_assurance/repin_and_promote_harness.py`` had a
``promote`` mode that wrote SEVEN ``HarnessRegistrationEvidenceV1`` fields as
literal keyword arguments -- ``clean_control_verdict="pass"``,
``negative_control_verdict="fail"``, ``official_runner_parity=True``,
``result_schema_conformant=True``, ``network_isolation="proved"``,
``target_write_isolation="proved"``, ``oracle_visibility="denied"`` -- and
pointed ``attestation_digests`` at its own registration report, so the bundle
cited itself as the execution it never performed. Both harnesses that ship no
attestations were registered through it, and the surface stayed reachable after
one of them was re-registered on real executions: it would have minted declared
evidence for the next harness to arrive.

THE REPAIR IS A REFUSAL, NOT A CONTROL SEQUENCE, and the reason is the surface's
scope. A control sequence is per-driver-family --
``attest_problem_correctness.CONTROLS`` stages the PROBLEM's own reference and
wrong kernels plus the driver's own extra-symbol transform, and needs the pinned
image -- while this surface accepts any manifest under ``builtin/``. Sharing
that machinery would have closed the surface for the family that already has an
attesting surface, and left it open for ``native-perf/v1``, which is the family
whose bundle carries the declared seven today. It would also have welded the
re-pin to a container image, and a re-pin is what you need precisely when you
are somewhere the controls cannot run.

So: this surface re-pins DERIVED manifest fields, reports gates it does not
record, and names the surface where each family's evidence is earned.

WHAT IS PINNED BELOW. That the seven fields and ``attestation_digests`` are not
passed on this surface AT ALL, literal or otherwise -- the same AST guard
``test_problem_correctness_control_sequence.py`` applies to the attesting
surface, in its stronger form, because the honest count here is zero rather than
seven-derived; that neither evidence model is even imported; that the only
filesystem write in the module is the manifest re-pin, and no string constant
names a directory inside the published Harness tree; that ``check`` still runs
and writes nothing, because a pre-commit gate calls it; and that the re-pin
capability itself survives -- a drifted driver digest is still repairable, and
repairing one reproduces the registered manifest byte for byte, digest included.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = (REPO_ROOT / "scripts" / "rqgm_assurance"
               / "repin_and_promote_harness.py")
MANIFEST_NAME = "hpc_gemm_problem_correctness.yaml"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "repin_and_promote_harness", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    # Registered before execution, and under the name the attesting surface
    # imports it by, so the two never load two copies of the derived-pin rules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


repin_module = _load_module()
SOURCE = MODULE_PATH.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


#: Every ``HarnessRegistrationEvidenceV1`` field this surface used to write as a
#: constant. Each is a claim about an execution: two control verdicts, two
#: isolation properties, oracle visibility, schema conformance, runner parity.
_DECLARED_BY_THE_OLD_PROMOTION = {
    "clean_control_verdict",
    "negative_control_verdict",
    "official_runner_parity",
    "result_schema_conformant",
    "network_isolation",
    "target_write_isolation",
    "oracle_visibility",
}

#: The models a promotion is written through. Not imported here at all.
_EVIDENCE_MODELS = {"HarnessRegistrationEvidenceV1", "HarnessPromotionApprovalV1"}


def _forbid_writes(monkeypatch) -> None:
    """Any filesystem mutation from here on is a test failure, not a diff."""

    def refuse(self, *args, **kwargs):
        raise AssertionError(f"this surface wrote to {self.name}")

    for method in ("write_text", "write_bytes", "mkdir", "touch", "unlink",
                   "rename", "replace"):
        monkeypatch.setattr(Path, method, refuse)


def _shipped(name: str = MANIFEST_NAME):
    return repin_module._load(repin_module.BUILTIN / name)


def _drifted(manifest, sha256: str):
    """The same manifest with a driver pin the repository does not have.

    Minted through ``create`` rather than ``model_copy`` because
    ``DigestBoundModel`` verifies ``manifest_digest`` on load: a copy with a
    moved driver pin and the old digest cannot be read back, which is the shape
    a real drift never has -- the manifest on disk is self-consistent and merely
    describes code that has since changed.
    """
    fields = manifest.model_dump(mode="python", exclude={"manifest_digest"})
    fields["driver"] = {**fields["driver"], "sha256": sha256}
    return repin_module.HarnessManifestV1.create(**fields)


# --------------------------------------------------------------------------
# the defect, pinned at the source
# --------------------------------------------------------------------------

def test_no_control_verdict_or_isolation_property_is_passed_as_a_literal() -> None:
    """The guard the attesting surface applies to itself, applied here.

    There it must find all seven, each fed something derived. Here the same scan
    must find no literal -- and the test below requires it to find nothing at
    all, because a surface that observed no execution has nothing to derive
    them from either.
    """
    for node in ast.walk(TREE):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg in _DECLARED_BY_THE_OLD_PROMOTION:
                assert not isinstance(keyword.value, ast.Constant), (
                    f"{keyword.arg} is handed a literal on a surface that runs "
                    f"no controls; that is exactly the defect removed here")


def test_none_of_the_seven_is_written_by_this_surface_at_all() -> None:
    """Derived would be no better than declared: there is nothing to derive from.

    ``attest_problem_correctness.isolation_findings`` can derive them because it
    holds five attestations, the requests that produced them and the workspace
    digests either side of each run. This surface holds none of that, so the
    only honest number of these fields it may write is zero.
    """
    passed = {keyword.arg
              for node in ast.walk(TREE) if isinstance(node, ast.Call)
              for keyword in node.keywords
              if keyword.arg in _DECLARED_BY_THE_OLD_PROMOTION}
    assert passed == set(), (
        f"this surface still writes {sorted(passed)}; whatever it derives them "
        f"from, it did not observe an execution")


def test_the_attestation_digests_field_is_not_written_either() -> None:
    """It used to point at this surface's own registration report.

    A bundle citing itself as the execution behind its verdicts is the same
    defect as the literals, and it is the half that made the record look
    attested rather than merely optimistic.
    """
    passed = [keyword.arg
              for node in ast.walk(TREE) if isinstance(node, ast.Call)
              for keyword in node.keywords
              if keyword.arg == "attestation_digests"]
    assert passed == []


def test_neither_evidence_model_is_imported_or_named() -> None:
    """Structural, so the refusal is a property of the module, not a habit.

    A future edit that wants to write evidence here has to add the import back,
    which is a visible thing to add rather than a keyword appended to a call.
    """
    imported: set[str] = set()
    for node in ast.walk(TREE):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imported |= {alias.name for alias in node.names}
    assert not (_EVIDENCE_MODELS & imported), sorted(_EVIDENCE_MODELS & imported)

    named = {node.id for node in ast.walk(TREE) if isinstance(node, ast.Name)}
    named |= {node.attr for node in ast.walk(TREE)
              if isinstance(node, ast.Attribute)}
    assert not (_EVIDENCE_MODELS & named)


#: Calls that put bytes on disk, named unambiguously. ``replace``, ``rename``
#: and ``copy`` are absent on purpose: ``str`` has two of those names, and a
#: scanner that counted ``harness_id.replace("/", "_")`` as a write would be
#: reporting a defect that is not there -- which is how a guard stops being
#: read. The modules that spell them unambiguously are refused wholesale below.
_WRITE_CALLS = {"write_text", "write_bytes", "mkdir", "touch", "unlink",
                "rmtree", "copytree", "makedirs", "remove"}
_WRITE_MODULES = {"os", "shutil", "subprocess", "tempfile"}


def test_the_only_filesystem_write_is_the_manifest_re_pin() -> None:
    """One write, in the one mode whose whole job is to move a derived pin."""
    imported: set[str] = set()
    for node in ast.walk(TREE):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not (_WRITE_MODULES & imported), (
        f"{sorted(_WRITE_MODULES & imported)} reaches the filesystem by names "
        f"``str`` also has, so the scan below could no longer tell a write from "
        f"a substitution. ``subprocess`` went out with the approval whose date "
        f"it looked up")

    writers: dict[str, set[str]] = {}
    for function in [node for node in ast.walk(TREE)
                     if isinstance(node, ast.FunctionDef)]:
        for node in ast.walk(function):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in _WRITE_CALLS):
                writers.setdefault(function.name, set()).add(node.func.attr)
    assert set(writers) == {"repin_manifests"}, sorted(writers)
    assert writers["repin_manifests"] == {"write_text"}


#: Directories under ``config/harnesses/`` that hold PUBLISHED, signed bytes.
#: ``builtin/`` is not among them: a manifest's derived pins are what this
#: surface repairs.
_PUBLISHED_TREE = {"evidence", "approvals", "reports", "catalog.yaml"}


def test_the_module_names_no_path_inside_the_published_harness_tree() -> None:
    """It cannot write a bundle it cannot name.

    The evidence directory, the approvals directory, the reports directory and
    the catalog are where a signature and the digests over it live. This surface
    reads none of them and writes none of them.
    """
    constants = {node.value for node in ast.walk(TREE)
                 if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    assert not (_PUBLISHED_TREE & constants), sorted(_PUBLISHED_TREE & constants)


# --------------------------------------------------------------------------
# promote refuses, and says where the evidence is earned instead
# --------------------------------------------------------------------------

def test_promote_refuses_and_names_the_attesting_surface(
    monkeypatch, capsys
) -> None:
    """A refusal that only says "no" sends the caller looking for another way.

    So it names, per driver family, the surface that can run that family's
    controls -- and says plainly where there is none.
    """
    _forbid_writes(monkeypatch)
    code = repin_module.main(
        ["promote", MANIFEST_NAME, "hpc_gemm_performance.yaml"])
    assert code == 6
    out = capsys.readouterr().out
    assert "REFUSED" in out
    assert "attest_problem_correctness.py" in out, (
        "the problem-correctness family has a surface that runs five real "
        "container executions; the refusal must point at it")
    assert "attest_gemm_performance.py" in out, (
        "the performance family has a control sequence now -- five container "
        "executions that must discriminate a wrong answer from a slow one -- "
        "and the refusal must point at it rather than at the older answer that "
        "nothing could earn its evidence")


def test_a_supplied_signature_is_told_that_nothing_was_signed(
    monkeypatch, capsys
) -> None:
    """The maintainer authorising a promotion is the caller most owed an answer.

    Argparse used to require ``--actor-id``; now it is accepted so a real
    signature reaches the explanation rather than a usage error, and the
    explanation says the approval was not written.
    """
    _forbid_writes(monkeypatch)
    code = repin_module.main(
        ["promote", MANIFEST_NAME, "--actor-id", "a-maintainer",
         "--authorization-basis", "read the bundle"])
    assert code == 6
    assert "NOTHING WAS SIGNED" in capsys.readouterr().out


def test_every_shipped_manifest_knows_where_its_evidence_would_be_earned() -> None:
    """A hand-map drifts silently; a missing family must turn this red instead."""
    surfaces = repin_module.attesting_surfaces()
    shipped = sorted(repin_module.BUILTIN.glob("*.yaml"))
    assert shipped, "no manifests to check"
    for path in shipped:
        revision = repin_module._load(path).driver.revision
        assert revision in surfaces, (
            f"{path.name} pins driver {revision}, which this surface cannot "
            f"answer 'where is its evidence earned' for")


def test_every_family_is_answered_with_a_surface_that_exists() -> None:
    """``None`` was a stated gap; a name that does not resolve is a worse one.

    ``native-perf/v1`` was answered with ``None`` while nothing in this
    repository could run its controls, which was true and worth saying. It has
    a control sequence now, so the answer is a surface -- and the thing to hold
    is that every named surface is a FILE THAT EXISTS with the mode it names.
    A map that sends a caller to a script that was renamed is the same defect
    as one that sends them nowhere, and reads as though the work were done.
    """
    surfaces = repin_module.attesting_surfaces()
    assert surfaces, "no families to check"
    for revision, surface in surfaces.items():
        assert surface, (
            f"{revision} has no surface that can earn its evidence; if that is "
            f"true it must be recorded as None deliberately")
        script = (Path(repin_module.__file__).parent
                  / surface.split()[0].rstrip(",."))
        assert script.is_file(), (
            f"{revision} is answered with {script.name}, which does not exist")


# --------------------------------------------------------------------------
# the modes a pre-commit gate runs still work, and still write nothing
# --------------------------------------------------------------------------

def test_check_mode_reports_pins_and_writes_nothing(monkeypatch, capsys) -> None:
    """This is the mode the pre-commit hook calls; it must stay side-effect free.

    Exit 1 on drift is the hook's signal and is not an error here: whether a pin
    happens to be stale at HEAD is a fact about the tree, not about this mode.
    """
    _forbid_writes(monkeypatch)
    code = repin_module.main(["check", "--json"])
    assert code in (0, 1)
    findings = json.loads(capsys.readouterr().out)
    assert isinstance(findings, dict)
    for fields in findings.values():
        assert set(fields) <= {"driver.sha256", "expected_result_schema",
                               "expected_result_schema_digest"}


def test_paths_mode_still_reports_what_the_digests_read(
    monkeypatch, capsys
) -> None:
    """The hook's trigger set. Asked of the digest functions, never listed."""
    _forbid_writes(monkeypatch)
    assert repin_module.main(["paths"]) == 0
    listed = capsys.readouterr().out.split()
    assert "ari-core/ari/assurance/native_perf_common.py" in listed
    assert not any(item.startswith("scripts/") for item in listed), (
        "this surface is not inside any driver digest, so editing it moves no "
        "pin -- which is what makes this repair safe to make")


# --------------------------------------------------------------------------
# and the re-pin capability itself survives
# --------------------------------------------------------------------------

def test_a_drifted_driver_digest_is_still_repairable() -> None:
    """The capability the refusal must not have cost.

    Repairing a drifted copy of a currently-correct manifest has to reproduce
    the registered manifest exactly -- every derived pin AND the digest over
    them -- or the repair is a different manifest wearing the same id.
    """
    shipped = _shipped()
    assert not repin_module.stale_pins(shipped), (
        "this test compares a repair against the registered bytes, so it needs "
        "them to be current")

    drifted = _drifted(shipped, "sha256:" + "a" * 64)
    assert set(repin_module.stale_pins(drifted)) == {"driver.sha256"}

    repaired = repin_module.repin(drifted)
    assert not repin_module.stale_pins(repaired)
    assert repaired.driver.sha256 == shipped.driver.sha256
    assert repaired.manifest_digest == shipped.manifest_digest
    assert repaired.model_dump(mode="json") == shipped.model_dump(mode="json")


def test_a_re_pin_moves_no_field_a_human_decided() -> None:
    """The other half of the same promise, checked field by field.

    A tool that could move ``registered_placement`` could relocate a harness's
    evidence to whatever machine was at hand, which is a change to what the
    harness asserts rather than a repair.
    """
    shipped = _shipped()
    repaired = repin_module.repin(_drifted(shipped, "sha256:" + "b" * 64))
    for field in ("id", "version", "registered_placement", "target_kinds",
                  "properties", "container", "oracle", "dataset", "resources",
                  "network_policy", "hidden_test_policy", "subject_types",
                  "supported_languages", "supported_hardware",
                  "supported_dtypes"):
        assert getattr(repaired, field) == getattr(shipped, field), field


def test_the_re_pin_mode_writes_the_manifest_and_nothing_else(
    tmp_path, monkeypatch, capsys
) -> None:
    """End to end, off the repository: one file in, one file out.

    The module is pointed at a scratch tree and the WHOLE tree is counted
    afterwards, so an evidence bundle, an approval or a catalog row appearing
    beside the manifest fails this rather than needing to be predicted by name.
    Exit 3 is "re-pinned, now commit": the gate report refuses a dirty tree, so
    it cannot run in the same invocation as the write that dirtied it.
    """
    builtin = tmp_path / "builtin"
    builtin.mkdir()
    shipped = _shipped()
    drifted = _drifted(shipped, "sha256:" + "c" * 64)
    (builtin / MANIFEST_NAME).write_text(
        yaml.safe_dump(drifted.model_dump(mode="json"), sort_keys=True,
                       default_flow_style=False), encoding="utf-8")
    monkeypatch.setattr(repin_module, "BUILTIN", builtin)

    code = repin_module.repin_manifests(
        SimpleNamespace(manifests=[MANIFEST_NAME], runs=3, dry_run=False))

    assert code == 3
    written = repin_module._load(builtin / MANIFEST_NAME)
    assert written.model_dump(mode="json") == shipped.model_dump(mode="json"), (
        "a re-pin has to land on the registered bytes, not merely on something "
        "self-consistent")
    assert sorted(item.relative_to(tmp_path).as_posix()
                  for item in tmp_path.rglob("*")) == [
        "builtin", f"builtin/{MANIFEST_NAME}"], (
        "no evidence bundle, approval, report or catalog may appear beside it")

    out = capsys.readouterr().out
    assert "NOT WRITTEN" in out
    assert "attest_problem_correctness.py" in out, (
        "a re-pin moves manifest_digest, so the caller is told in the same "
        "breath that the bundle and the signature over it have to be re-earned")


def test_a_passing_gate_report_still_writes_no_evidence(
    tmp_path, monkeypatch, capsys
) -> None:
    """THE CASE THE OLD SURFACE WROTE A BUNDLE FOR.

    Pins current, every gate green, decision ``eligible-for-verified`` -- this
    is the exact state in which ``promote`` used to mint the seven literals,
    sign an approval and rewrite the catalog row. Now it reports what it saw,
    writes nothing, and says where the evidence has to be earned.

    ``register_harness`` is replaced because its verdict is not what is under
    test and it needs a clean worktree, which a repository with a concurrent
    committer cannot promise. The gates it would run are pinned elsewhere; what
    is pinned here is what happens AFTER they pass.
    """
    builtin = tmp_path / "builtin"
    builtin.mkdir()
    shipped = _shipped()
    (builtin / MANIFEST_NAME).write_text(
        yaml.safe_dump(shipped.model_dump(mode="json"), sort_keys=True,
                       default_flow_style=False), encoding="utf-8")
    monkeypatch.setattr(repin_module, "BUILTIN", builtin)
    monkeypatch.setattr(
        repin_module, "register_harness",
        lambda *a, **k: SimpleNamespace(
            decision="eligible-for-verified",
            gates=tuple(SimpleNamespace(gate_id=f"gate-{index}", passed=True,
                                        detail="")
                        for index in range(15))))
    _forbid_writes(monkeypatch)

    code = repin_module.repin_manifests(
        SimpleNamespace(manifests=[MANIFEST_NAME], runs=3, dry_run=False))

    assert code == 0
    out = capsys.readouterr().out
    assert "already current" in out
    assert "15/15" in out
    assert "NOT WRITTEN: registration evidence, promotion approval, catalog row." in out
    assert "attest_problem_correctness.py" in out
