from __future__ import annotations

import json
import re

import pytest
import yaml

from ari.assurance.catalog import (
    build_harness_catalog_snapshot,
    load_harness_catalog,
)
from ari.assurance.lock import validate_harness_revision
from ari.assurance.models import (
    AuxiliaryVerificationRequestV1,
    BaselineHarnessLockV1,
    ContainerPinV1,
    HarnessLockRevisionV1,
    HarnessManifestV1,
    HarnessPropertyCoverageV1,
    HarnessResourceRequirementsV1,
    HarnessPromotionApprovalV1,
    HarnessRegistrationEvidenceV1,
    LockedHarnessV1,
    PinnedHarnessAssetV1,
    VerificationContractV1,
    VerificationRequirementProposalV1,
    VerificationRequirementV1,
    VerificationScopeV1,
)
from ari.assurance.registration import HARNESS_REGISTRATION_GATES, registration_report
from ari.assurance.registration_models import HarnessRegistrationGateV1
from ari.assurance.resolver import (
    HarnessResolutionError,
    mint_baseline_harness_lock,
    resolve_harness_suite,
)
from ari.assurance.suite import (
    assert_monotonic_requirement_revision,
    union_verification_requirements,
)
from ari.protocols.integrity import SHA256_DIGEST_PATTERN, canonical_digest
from ari.protocols.scientific_requirements import EnvironmentSnapshotV1


SHA = "sha256:" + ("4" * 64)


def _real_head() -> str | None:
    """HEAD of the repository the gate will consult, or None outside one."""
    import subprocess

    from ari.assurance.registration_run import repository_root

    try:
        done = subprocess.run(["git", "-C", str(repository_root()), "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() if done.returncode == 0 else None



def _requirement(
    *,
    methods=("differential-testing",),
    tier="screen",
    property_id="numerical-equivalence",
):
    return VerificationRequirementV1.create(
        property_id=property_id,
        target_kind="shared-library",
        required_methods=methods,
        required_tier=tier,
        failure_policy="exclude-from-scientific-frontier",
        scope=VerificationScopeV1(
            values={"language": ("c",), "hardware": ("cpu",), "dtype": ("float64",)}
        ),
        tolerance_policy_ref="hpc.float64/v1",
        tolerance_policy_digest=SHA,
        source_requirement_refs=("research:metric",),
    )


def _contract(requirements=None, *, run_id="run-1"):
    reqs = tuple(requirements or (_requirement(),))
    return VerificationContractV1.create(
        run_id=run_id,
        research_contract_digest=SHA,
        requirements=tuple(sorted(reqs, key=lambda item: item.requirement_digest)),
        admission_confidence=1.0,
        property_vocabulary_digest=SHA,
    )


def _asset(revision):
    return PinnedHarnessAssetV1(revision=revision, sha256=canonical_digest(revision), license="MIT")


def _manifest(
    harness_id="hpc/gemm-correctness",
    *,
    kind="artifact_verifier",
    accepts_external_target=True,
    methods=("differential-testing",),
    tiers=("screen",),
    status="verified",
    cost=1,
    property_id="numerical-equivalence",
    assets="v1",
):
    return HarnessManifestV1.create(
        id=harness_id,
        version="1.0.0",
        kind=kind,
        status=status,
        description="GEMM correctness verifier",
        maintainer="ari",
        tags=("hpc",),
        subject_types=("program",),
        target_kinds=("shared-library",),
        accepts_external_target=accepts_external_target,
        supported_languages=("c",),
        supported_hardware=("cpu",),
        supported_architectures=("x86_64",),
        supported_dtypes=("float64",),
        supported_domains=("gemm",),
        properties=(
            HarnessPropertyCoverageV1(
                property_id=property_id,
                methods=methods,
                tiers=tiers,
                scope=VerificationScopeV1(
                    values={
                        "language": ("c",),
                        "hardware": ("cpu",),
                        "dtype": ("float64",),
                    }
                ),
                tolerance_policy_digest=SHA,
            ),
        ),
        target_interface_contract="gemm-c-abi/v1",
        target_interface_digest=SHA,
        source_repository="https://example.invalid/harness",
        # A REAL commit: the source pin is checked for ancestry against the
        # repository, so "4"*40 names nothing and the gate correctly fails.
        source_full_commit_sha=_real_head() or "4" * 40,
        implementation_license="MIT",
        dataset=_asset("dataset-" + assets),
        oracle=_asset("oracle-" + assets),
        driver=_asset("native-" + assets),
        model=_asset("none"),
        container=ContainerPinV1(reference="example.invalid/harness@sha256:4", resolved_digest=SHA, license="MIT"),
        network_policy="deny",
        credential_policy="none",
        filesystem_policy="isolated-readonly-target",
        resources=HarnessResourceRequirementsV1(
            cpu_cores=cost, memory_bytes=1024, accelerators=0, disk_bytes=1024
        ),
        timeout_seconds=60,
        scorer_determinism="deterministic",
        nondeterminism_declaration="none",
        hidden_test_policy="verifier-only",
        oracle_independence="independent",
        tolerance_policy_digest=SHA,
        expected_result_schema="ari.native-hpc-result/v1",
        expected_result_schema_digest=SHA,
        infrastructure_failure_policy="separate",
        retry_limit=1,
        negative_control_report_digest=SHA,
        upstream_parity_report_digest=SHA,
    )


def _catalog(manifests):
    return build_harness_catalog_snapshot(
        catalog_source_revision="test",
        property_vocabulary_digest=SHA,
        driver_protocol_version="v1",
        manifests=tuple(manifests),
        registration_report_digests={item.id: SHA for item in manifests},
        registration_evidence_digests={item.id: SHA for item in manifests},
        promotion_approval_digests={
            item.id: SHA for item in manifests if item.status == "verified"
        },
    )


def _environment():
    return EnvironmentSnapshotV1.create(
        resource_types=("process", "cpu"),
        features=(),
    )


def test_harness_exact_set_cover_is_byte_deterministic():
    cheap = _manifest("hpc/a-gemm", cost=1)
    expensive = _manifest("hpc/z-gemm", cost=4)
    first = resolve_harness_suite(
        contract=_contract(), catalog=_catalog((expensive, cheap)), environment=_environment()
    )
    second = resolve_harness_suite(
        contract=_contract(), catalog=_catalog((cheap, expensive)), environment=_environment()
    )
    assert first.model_dump_json() == second.model_dump_json()
    assert first.harness_manifest_digests == (cheap.manifest_digest,)


def test_benchmark_kind_separation():
    """Task 20 criterion 46: a benchmark kind is not an artifact verifier.

    ``_coverage`` refuses a ``benchmark`` manifest that does not accept an
    external target for any atom outside {model, agent, benchmark-submission}:
    a fixed benchmark task evaluates its own subjects, so it can never be
    resolved into the suite that judges an arbitrary node's artifact.
    """

    benchmark = _manifest(
        "science/benchmark", kind="benchmark", accepts_external_target=False
    )
    with pytest.raises(HarnessResolutionError, match="unsatisfied"):
        resolve_harness_suite(
            contract=_contract(), catalog=_catalog((benchmark,)), environment=_environment()
        )


def test_unsatisfied_coverage_never_falls_back_to_weaker_method():
    weak = _manifest(methods=("smoke-test",))
    with pytest.raises(HarnessResolutionError, match="unsatisfied"):
        resolve_harness_suite(
            contract=_contract(), catalog=_catalog((weak,)), environment=_environment()
        )


# ── criteria 34 / 35: the baseline Lock is immutable, and a revision only
# ── adds to it ──────────────────────────────────────────────────────────────


def _minted_baseline_lock(run_id: str = "run-1"):
    """A real Lock, minted by the resolver from a real contract and catalog."""
    contract = _contract()
    catalog = _catalog((_manifest(),))
    return mint_baseline_harness_lock(
        run_id=run_id,
        research_contract_digest=SHA,
        contract=contract,
        catalog=catalog,
        environment=_environment(),
        oracle_bundle_digest=SHA,
        suite=resolve_harness_suite(
            contract=contract, catalog=catalog, environment=_environment()
        ),
    )


def _changed_json(value):
    """A different value of the same JSON shape, for the field loop below."""
    if isinstance(value, list):
        return value[1:] if value else ["sha256:" + "e" * 64]
    if isinstance(value, str):
        if re.fullmatch(SHA256_DIGEST_PATTERN, value):
            return "sha256:" + "e" * 64
        return value + "-changed"
    if value is None:
        return "no-longer-none"
    raise AssertionError(f"no mutation defined for {type(value).__name__}")


def _populated_baseline_lock():
    """A minted Lock with something to change in every field.

    The loop in criterion 34 changes each field in turn and an empty list has
    nothing to take away, so the one field a clean resolution leaves empty --
    there is no unsatisfied atom when the suite covers the contract -- is
    filled before minting. Still minted through ``create``, so ``lock_digest``
    is the real digest over exactly these bytes.
    """
    payload = _minted_baseline_lock().model_dump(mode="json")
    payload.pop("lock_digest")
    payload["unsatisfied_atom_digests"] = ["sha256:" + "9" * 64]
    lock = BaselineHarnessLockV1.create(**payload)
    empty = sorted(
        name
        for name in type(lock).model_fields
        if name != "prompt_hash" and getattr(lock, name) in ((), "", None)
    )
    assert not empty, f"nothing to change in {empty}; the field loop is vacuous"
    return lock


def test_baseline_harness_lock_immutable(tmp_path):
    """Task 20 section 8 criterion 34.

    Three ways a baseline Lock could stop being immutable, each asserted where
    it would happen: the minted object taking an assignment, a changed payload
    validating back into a Lock, and the file on disk being replaced by a
    second write. The field loops are taken off ``model_fields`` rather than
    off a list kept here, so a field added to the Lock is covered by this test
    on the day it lands.
    """
    from pydantic import ValidationError

    from ari.assurance.lock import write_immutable_harness_lock

    lock = _populated_baseline_lock()
    fields = tuple(type(lock).model_fields)
    assert fields, "the Lock declares no fields; every loop below is vacuous"

    # 1. The minted object refuses assignment outright.
    for name in fields:
        with pytest.raises(ValidationError, match="frozen"):
            setattr(lock, name, "changed")

    # 2. A changed payload does not validate back into a Lock. The digest
    #    covers every other field, so there is no field to change quietly --
    #    including the ones a schema rule would not have caught.
    payload = lock.model_dump(mode="json")
    for name in fields:
        if name == "lock_digest":
            continue
        with pytest.raises(ValidationError):
            BaselineHarnessLockV1.model_validate(
                {**payload, name: _changed_json(payload[name])}
            )
    with pytest.raises(ValidationError, match="lock_digest does not match"):
        BaselineHarnessLockV1.model_validate({**payload, "run_id": "run-2"})
    # ... and the digest itself cannot be re-pointed at the changed payload.
    with pytest.raises(ValidationError, match="lock_digest does not match"):
        BaselineHarnessLockV1.model_validate(
            {**payload, "run_id": "run-2", "lock_digest": "sha256:" + "e" * 64}
        )

    # 3. The file. One Lock, written once: rewriting the same bytes is a
    #    no-op, different bytes and a symlink are refused, and what is on disk
    #    does not move either way.
    path = tmp_path / "rqgm" / "kca" / "baseline_harness_lock.json"
    write_immutable_harness_lock(path, lock)
    written = path.read_bytes()
    write_immutable_harness_lock(path, lock)
    assert path.read_bytes() == written

    second = BaselineHarnessLockV1.create(
        **{key: value for key, value in payload.items()
           if key != "lock_digest"} | {"run_id": "run-2"}
    )
    with pytest.raises(ValueError, match="immutable Harness lock mismatch"):
        write_immutable_harness_lock(path, second)
    assert path.read_bytes() == written

    # A symlink standing where the Lock should be is refused even when it
    # resolves to bytes that match: the writer would otherwise follow it
    # anywhere the link points.
    link = tmp_path / "link" / "baseline_harness_lock.json"
    link.parent.mkdir()
    link.symlink_to(path)
    with pytest.raises(ValueError, match="immutable Harness lock mismatch"):
        write_immutable_harness_lock(link, lock)
    assert path.read_bytes() == written


def _pinned_fields_compared_by(function) -> tuple[str, ...]:
    """The digests the strengthening branch refuses to see swapped.

    Read off the guard's own comparison rather than restated here, so a sixth
    digest added to it is covered on the day it lands. Scoped to the loop over
    ``added_or_strengthened_harnesses`` because that is the branch this
    inventory is for. ``harness_id`` is excluded: it is the key the baseline
    entry is looked up BY, not one of the bytes pinned under it -- an entry
    carrying a new id is a new Harness, which the test below admits.
    """
    import ast
    import inspect
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
    loops = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.For)
        and isinstance(node.iter, ast.Attribute)
        and node.iter.attr == "added_or_strengthened_harnesses"
    ]
    assert len(loops) == 1, "the strengthening branch was not found"
    names = {
        node.attr
        for node in ast.walk(loops[0])
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id in {"item", "previous"}
    }
    return tuple(sorted(names - {"harness_id"}))


def _changed_locked_field(name: str, value):
    """A different, still schema-valid value for one ``LockedHarnessV1`` field.

    Schema-valid because the revision is minted through ``create``: an
    out-of-vocabulary ``kind`` would be refused by pydantic before the guard
    under test ever saw it, and the refusal being asserted is the guard's.
    """
    from typing import Literal, get_args, get_origin

    annotation = LockedHarnessV1.model_fields[name].annotation
    if get_origin(annotation) is Literal:
        others = [item for item in get_args(annotation) if item != value]
        assert others, f"{name} allows exactly one value"
        return others[0]
    if isinstance(value, tuple):
        return value[1:] if value else (SHA,)
    if isinstance(value, str):
        if re.fullmatch(SHA256_DIGEST_PATTERN, value):
            return canonical_digest("changed-" + name)
        return value + "-changed"
    raise AssertionError(f"no mutation defined for {name}")


def test_harness_revision_monotonic():
    """Task 20 section 8 criterion 35: a Lock revision is a superset or a
    strengthening.

    So the four things it must not be, asserted against the guard rather than
    against a description of it: a revision of some other baseline, a removal,
    a rewrite of what a baseline entry pinned, and a "strengthening" that
    swaps the dataset, oracle, driver, container or tolerance out from under a
    Harness id that was already locked. The two loops are derived -- the
    rewrite loop off ``LockedHarnessV1.model_fields``, the swap loop off the
    guard's own comparison -- and both are floored against arriving empty.

    The two accepting cases come first on purpose: a guard that refused every
    revision would pass every refusal below and stop the mechanism it exists
    to bound.
    """
    baseline = _minted_baseline_lock()
    locked = baseline.harnesses[0]

    def _revision(*, active, added=(), baseline_digest=None):
        return HarnessLockRevisionV1.create(
            run_id="run-1",
            next_epoch_id="epoch_001",
            parent_lock_digest=baseline.lock_digest,
            baseline_lock_digest=baseline_digest or baseline.lock_digest,
            added_requirement_refs=(),
            added_or_strengthened_harnesses=tuple(added),
            active_harnesses=tuple(active),
            coverage_proof_digest=baseline.coverage_proof_digest,
        )

    # Accepted: the identity revision, and one that ADDS a Harness beside the
    # baseline without touching it.
    validate_harness_revision(
        baseline=baseline, revision=_revision(active=baseline.harnesses)
    )
    fresh = locked.model_copy(
        update={
            "harness_id": "hpc/second-verifier",
            "manifest_digest": canonical_digest("second-manifest"),
        }
    )
    validate_harness_revision(
        baseline=baseline,
        revision=_revision(active=baseline.harnesses + (fresh,), added=(fresh,)),
    )

    # Refused: a revision of a different baseline is not a revision of this one.
    with pytest.raises(ValueError, match="another baseline"):
        validate_harness_revision(
            baseline=baseline,
            revision=_revision(
                active=baseline.harnesses,
                baseline_digest=canonical_digest("some other baseline"),
            ),
        )

    # Refused: dropping the baseline Harness is not a superset.
    with pytest.raises(ValueError, match="cannot remove a baseline Harness"):
        validate_harness_revision(baseline=baseline, revision=_revision(active=()))

    # Refused: every field of a locked baseline entry, rewritten under it.
    fields = tuple(LockedHarnessV1.model_fields)
    assert fields, "LockedHarnessV1 declares no fields; the loop is vacuous"
    for name in fields:
        rewritten = locked.model_copy(
            update={name: _changed_locked_field(name, getattr(locked, name))}
        )
        # Changing the manifest digest takes the pinned entry out of the
        # revision entirely, which is the removal rule; every other field is
        # the same entry carrying different bytes.
        expected = (
            "cannot remove a baseline Harness"
            if name == "manifest_digest"
            else "cannot replace pinned baseline bytes"
        )
        with pytest.raises(ValueError, match=expected):
            validate_harness_revision(
                baseline=baseline, revision=_revision(active=(rewritten,))
            )

    # Refused: a new manifest for an already-locked Harness id may strengthen,
    # but it may not swap what the baseline pinned.
    pinned = _pinned_fields_compared_by(validate_harness_revision)
    assert pinned, "no pinned digest comparison found in the strengthening branch"
    for name in pinned:
        swapped = locked.model_copy(
            update={
                "manifest_digest": canonical_digest("restrengthened-" + name),
                name: canonical_digest("swapped-" + name),
            }
        )
        with pytest.raises(ValueError, match="cannot swap"):
            validate_harness_revision(
                baseline=baseline,
                revision=_revision(
                    active=baseline.harnesses + (swapped,), added=(swapped,)
                ),
            )


def test_verification_union_only_strengthens():
    screen = _requirement(methods=("differential-testing",), tier="screen")
    certify = _requirement(
        methods=("differential-testing", "metamorphic-testing"), tier="certify"
    )
    merged = union_verification_requirements((screen, certify))
    assert len(merged) == 1
    assert merged[0].required_tier == "certify"
    assert set(merged[0].required_methods) == {
        "differential-testing",
        "metamorphic-testing",
    }
    assert_monotonic_requirement_revision((screen,), merged)
    with pytest.raises(ValueError, match="downgraded"):
        assert_monotonic_requirement_revision((certify,), (screen,))


def _passing_gate_evidence(manifest):
    """Evidence a well-formed registration would have produced.

    Synthetic on purpose: this file tests the RESOLVER, so it states what a
    passing probe looks like rather than spending a real one. The gates that
    read the manifest read the real manifest.
    """
    from ari.assurance.registration import GateEvidence

    probe = {
        "driver_digest": manifest.driver.sha256,
        "passed": True,
        # The COMMON vocabulary both drivers emit; a gate should not have to
        # know which one answered it.
        "controls": {
            "clean": {"verdict": "pass", "relative_spread": 0.01, "resolved": True},
            "negatives": [
                {"name": "slow", "verdict": "fail", "detail": "below the threshold"},
                {"name": "wrong", "verdict": "fail", "detail": "failed the residual bound"},
            ],
        },
    }
    return GateEvidence(
        manifest=manifest, parity=probe, driver_digest=manifest.driver.sha256,
        report_schema={"$id": "test", "properties": {"verdict": {}}},
        # WHAT THE DRIVER EMITS, which the gate compares against what the
        # manifest independently declares. Supplying only the schema left the
        # manifest's own two fields checked by nothing -- the hole that let one
        # shipped manifest name a report type its driver never produces.
        report_schema_version=manifest.expected_result_schema,
        report_schema_digest=manifest.expected_result_schema_digest,
        stability={"runs": 3, "relative_spread": 0.02},
        # The source pin is checked for ANCESTRY against a real repository now,
        # so a synthetic sha names nothing and the gate fails. Registering "at
        # the commit you pinned" is the case a fixture should model.
        repo_commit=_real_head() or manifest.source_full_commit_sha,
    )


def _write_verified_catalog(tmp_path):
    manifest = _manifest()
    evidence_digest = canonical_digest("harness-registration-evidence")
    # A registration is minted from EVIDENCE now; there is no way to hand it a
    # pre-decided gate, which is what this fixture used to do and what let every
    # shipped report carry fifteen gates nothing had evaluated. This resolver
    # test needs a verified catalog, so it supplies evidence that satisfies the
    # gates rather than asserting the answers.
    report = registration_report(
        harness_id=manifest.id,
        manifest_digest=manifest.manifest_digest,
        evidence=_passing_gate_evidence(manifest),
    )
    evidence = HarnessRegistrationEvidenceV1.create(
        harness_id=manifest.id,
        harness_version=manifest.version,
        manifest_digest=manifest.manifest_digest,
        # A REAL commit: the source pin is checked for ancestry against the
        # repository, so "4"*40 names nothing and the gate correctly fails.
        source_full_commit_sha=_real_head() or "4" * 40,
        environment_digest=evidence_digest,
        evidence_artifact_digests={"builtin/fixture.json": evidence_digest},
        attestation_digests=(evidence_digest,),
        clean_control_verdict="pass",
        negative_control_verdict="fail",
        official_runner_parity=True,
        result_schema_conformant=True,
        network_isolation="proved",
        target_write_isolation="proved",
        oracle_visibility="denied",
        run_count=3,
    )
    approval = HarnessPromotionApprovalV1.create(
        harness_id=manifest.id,
        harness_version=manifest.version,
        actor_kind="human-maintainer",
        actor_id="test-maintainer",
        authorization_basis="test fixture promotion",
        approved_date="2026-08-05",
        harness_manifest_digest=manifest.manifest_digest,
        registration_report_digest=report.report_digest,
        evidence_bundle_digest=evidence.evidence_digest,
    )
    builtin = tmp_path / "builtin"
    builtin.mkdir()
    manifest_path = builtin / "gemm.yaml"
    report_path = builtin / "gemm.registration.json"
    approval_path = builtin / "gemm.approval.json"
    evidence_path = builtin / "gemm.evidence.json"
    fixture_path = builtin / "fixture.json"
    manifest_path.write_text(
        yaml.safe_dump(manifest.model_dump(mode="json"), sort_keys=True),
        encoding="utf-8",
    )
    report_path.write_text(report.model_dump_json(), encoding="utf-8")
    evidence_path.write_text(evidence.model_dump_json(), encoding="utf-8")
    fixture_path.write_text('"harness-registration-evidence"', encoding="utf-8")
    approval_path.write_text(approval.model_dump_json(), encoding="utf-8")
    (tmp_path / "property_vocabulary.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "version": "test/v1",
                "properties": {
                    "numerical-equivalence": ["differential-testing"]
                },
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    catalog_path = tmp_path / "catalog.yaml"
    catalog_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "catalog_source_revision": "test-catalog/v1",
                "driver_protocol_version": "ari.harness-driver/v1",
                "entries": [
                    {
                        "id": manifest.id,
                        "manifest": "builtin/gemm.yaml",
                        "registration_report": "builtin/gemm.registration.json",
                        "registration_report_digest": report.report_digest,
                        "registration_evidence": "builtin/gemm.evidence.json",
                        "registration_evidence_digest": evidence.evidence_digest,
                        "promotion_approval": "builtin/gemm.approval.json",
                        "promotion_approval_digest": approval.approval_digest,
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return catalog_path, manifest, report, approval_path


def test_verified_catalog_requires_exact_registration_and_human_approval(tmp_path):
    catalog_path, manifest, report, _ = _write_verified_catalog(tmp_path)
    snapshot = load_harness_catalog(catalog_path)
    assert snapshot.manifests == (manifest,)
    assert snapshot.registration_report_digests == {manifest.id: report.report_digest}
    assert set(snapshot.promotion_approval_digests) == {manifest.id}


def test_verified_catalog_rejects_tampered_promotion_approval(tmp_path):
    catalog_path, _, _, approval_path = _write_verified_catalog(tmp_path)
    document = json.loads(approval_path.read_text(encoding="utf-8"))
    document["actor_id"] = "substituted-actor"
    approval_path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ValueError, match="approval_digest"):
        load_harness_catalog(catalog_path)


def test_verified_catalog_rejects_tampered_registration_evidence_artifact(tmp_path):
    catalog_path, _, _, _ = _write_verified_catalog(tmp_path)
    (tmp_path / "builtin" / "fixture.json").write_text(
        '"substituted-registration-evidence"', encoding="utf-8"
    )

    with pytest.raises(ValueError, match="evidence artifact differs"):
        load_harness_catalog(catalog_path)


# ---------------------------------------------------------------------------
# Task 20 criterion 30 -- an Evaluator's Harness ID is a hint, not a selection
# ---------------------------------------------------------------------------


def _hint_carrying_models():
    """Every assurance model that carries an Evaluator's Harness hint.

    Read out of ``ari.assurance.models`` rather than listed here: the criterion
    is about whatever field the system uses to carry a proposed Harness ID, and
    a list written down in a test stops describing the system the moment a
    third carrier appears or the field is renamed.
    """
    import inspect

    from pydantic import BaseModel

    import ari.assurance.models as models

    found: dict[str, tuple[str, ...]] = {}
    for name, obj in vars(models).items():
        if not (inspect.isclass(obj) and issubclass(obj, BaseModel)):
            continue
        fields = tuple(
            sorted(item for item in obj.model_fields if "harness_hint" in item)
        )
        if fields:
            found[name] = fields
    return found


def _authoritative_resolution_models():
    """The typed models the authoritative resolution path actually takes.

    ``get_type_hints`` over the two entry points, so this follows the
    signatures instead of restating them: wiring a hint-bearing document into
    either function puts that document in this set.
    """
    import inspect
    import typing

    from pydantic import BaseModel

    models: set[type] = set()
    for function in (resolve_harness_suite, mint_baseline_harness_lock):
        for annotation in typing.get_type_hints(function).values():
            if inspect.isclass(annotation) and issubclass(annotation, BaseModel):
                models.add(annotation)
    return models


def test_evaluator_harness_hint_non_authoritative():
    """Task 20 criterion 30: an Evaluator's Harness ID stays a hint.

    Two halves, because "not blindly selected" is a claim about both the
    plumbing and the decision.

    STRUCTURE.  The documents that may carry a proposed Harness ID are found by
    scanning the assurance models for the field, and every typed model the
    authoritative path takes is read off ``resolve_harness_suite`` /
    ``mint_baseline_harness_lock`` themselves.  No model on the authoritative
    side carries the field and neither signature has a hint-shaped parameter,
    so there is no seam through which a proposal could be honoured.  Because
    both sets are derived, wiring a hint document into either entry point, or
    adding a third carrier and forgetting it here, turns this red.

    DECISION.  The same hint is held fixed across two catalogs that differ only
    in the resolver's own cost objective.  The selection moves with the
    objective -- disagreeing with the hint once and agreeing with it once -- so
    the hint predicts nothing about what was chosen.  Asserting only the
    disagreement would leave "the resolver ignores the hint AND everything
    else" passing.
    """
    carriers = _hint_carrying_models()
    assert carriers, (
        "no assurance model carries an Evaluator Harness hint any more; "
        "criterion 30 has nothing left to be non-authoritative about"
    )

    authoritative = _authoritative_resolution_models()
    assert authoritative, "the authoritative resolution path takes no typed model"
    for model in authoritative:
        assert model.__name__ not in carriers, (
            f"{model.__name__} both carries a Harness hint and is an input to "
            f"authoritative Harness resolution"
        )
    import inspect as _inspect

    for function in (resolve_harness_suite, mint_baseline_harness_lock):
        assert not [
            name
            for name in _inspect.signature(function).parameters
            if "hint" in name
        ], f"{function.__name__} accepts a Harness hint"

    # Both carriers are minted, so the field has to exist and hold the value:
    # a renamed or dropped field cannot pass this quietly.
    cheap = _manifest("hpc/a-gemm", cost=1)
    expensive = _manifest("hpc/z-gemm", cost=4)
    contract = _contract()
    proposal = VerificationRequirementProposalV1.create(
        run_id="run-1",
        epoch_id="epoch_001",
        proposer_component_id="evaluator",
        proposer_prompt_hash=canonical_digest("evaluator-prompt"),
        evidence_refs=(),
        requested_requirement=_requirement(),
        parent_verification_contract_digest=contract.contract_digest,
        active_harness_lock_digest=SHA,
        non_authoritative_harness_hint=expensive.id,
    )
    request = AuxiliaryVerificationRequestV1.create(
        run_id="run-1",
        next_epoch_id="epoch_001",
        proposer_component_id="reviewer",
        proposer_prompt_hash=canonical_digest("reviewer-prompt"),
        requested_requirements=(_requirement(),),
        parent_verification_contract_digest=contract.contract_digest,
        active_harness_lock_digest=SHA,
        non_authoritative_harness_hints=(expensive.id,),
    )
    exercised = {
        "VerificationRequirementProposalV1": proposal,
        "AuxiliaryVerificationRequestV1": request,
    }
    assert set(carriers) == set(exercised), (
        "a model carrying a Harness hint is not exercised here: "
        f"{sorted(set(carriers) ^ set(exercised))}"
    )
    for name, document in exercised.items():
        for field in carriers[name]:
            value = getattr(document, field)
            assert expensive.id in ((value,) if isinstance(value, str) else value)

    # The hint names ``hpc/z-gemm`` in both resolutions below.
    hinted = expensive.id
    as_proposed = resolve_harness_suite(
        contract=contract,
        catalog=_catalog((cheap, expensive)),
        environment=_environment(),
    )
    assert as_proposed.harness_manifest_digests == (cheap.manifest_digest,), (
        "the resolver did not choose on its own objective"
    )

    flipped_cheap = _manifest("hpc/a-gemm", cost=4)
    flipped_hinted = _manifest("hpc/z-gemm", cost=1)
    as_flipped = resolve_harness_suite(
        contract=contract,
        catalog=_catalog((flipped_cheap, flipped_hinted)),
        environment=_environment(),
    )
    assert as_flipped.harness_manifest_digests == (flipped_hinted.manifest_digest,)

    # Same hint, two answers: the objective decided, the hint did not.
    assert as_proposed.harness_manifest_digests != as_flipped.harness_manifest_digests

    lock = mint_baseline_harness_lock(
        run_id="run-1",
        research_contract_digest=SHA,
        contract=contract,
        catalog=_catalog((cheap, expensive)),
        environment=_environment(),
        oracle_bundle_digest=SHA,
        suite=as_proposed,
    )
    rendered = lock.model_dump_json()
    assert cheap.id in rendered
    assert hinted not in rendered, (
        "the hinted Harness reached the authoritative lock without being selected"
    )


# ---------------------------------------------------------------------------
# Task 20 criterion 32 -- byte-identical baseline Harness Lock
# ---------------------------------------------------------------------------


def _two_harness_inputs(*, assets="v1"):
    """Requirements and manifests that make the lock pin TWO harnesses.

    Determinism asserted over a one-element structure is close to no assertion
    at all -- a 1-tuple compares equal to itself under every ordering.  Two
    requirements, each covered by a different manifest, give the lock a
    ``harnesses`` tuple whose order is a real choice and a coverage proof over
    more than one atom.
    """

    requirements = (
        _requirement(),
        _requirement(
            property_id="interface-conformance", methods=("interface-check",)
        ),
    )
    manifests = (
        _manifest("hpc/a-differential", assets=assets),
        _manifest(
            "hpc/z-conformance",
            property_id="interface-conformance",
            methods=("interface-check",),
        ),
    )
    return requirements, manifests


def _mint_lock(
    *,
    requirements,
    manifests,
    environment=None,
    research_contract_digest=SHA,
    oracle_bundle_digest=SHA,
    contract_run_id="run-1",
):
    environment = environment if environment is not None else _environment()
    contract = _contract(requirements, run_id=contract_run_id)
    catalog = _catalog(manifests)
    suite = resolve_harness_suite(
        contract=contract, catalog=catalog, environment=environment
    )
    return mint_baseline_harness_lock(
        run_id="run-1",
        research_contract_digest=research_contract_digest,
        contract=contract,
        catalog=catalog,
        environment=environment,
        oracle_bundle_digest=oracle_bundle_digest,
        suite=suite,
    )


def _determinism_lock():
    """The baseline lock, rebuilt end to end.  Also the subprocess entry point."""

    requirements, manifests = _two_harness_inputs()
    return _mint_lock(requirements=requirements, manifests=manifests)


def _lock_digest_under_hash_seed(seed: str) -> str:
    """``_determinism_lock().lock_digest`` from a fresh interpreter."""

    import os
    import subprocess
    import sys
    from pathlib import Path

    source = str(Path(__file__).resolve())
    program = (
        "import importlib.util, sys\n"
        f"spec = importlib.util.spec_from_file_location('lock_determinism', {source!r})\n"
        "module = importlib.util.module_from_spec(spec)\n"
        "sys.modules['lock_determinism'] = module\n"
        "spec.loader.exec_module(module)\n"
        "print(module._determinism_lock().lock_digest)\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONHASHSEED": seed},
        timeout=600,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


def test_harness_lock_determinism():
    """Task 20 criterion 32: identical contract/catalog/environment yields a
    byte-identical baseline Harness Lock.

    The suite-level determinism test above stops at ``HarnessSuiteV1``.  The
    LOCK is the different object the criterion names: it adds the pinned
    dataset/oracle/driver/container digests, the coverage proof, and the four
    identities the run is admitted under.

    Byte-equality alone would also hold for a lock that ignored its inputs, so
    the second half is the complement: every ``*_digest`` field the lock
    declares is perturbed by one of the inputs the lock claims to be a function
    of.  The inventory of fields comes from the model, so a digest added to the
    lock and wired to nothing turns this red rather than riding along.
    """

    first = _determinism_lock()
    second = _determinism_lock()

    _, manifests = _two_harness_inputs()
    assert len(manifests) > 1
    assert sorted(item.harness_id for item in first.harnesses) == sorted(
        item.id for item in manifests
    ), "the fixture did not lock one harness per requirement"
    assert len(first.requirements) == len(manifests)
    assert first.unsatisfied_atom_digests == ()

    assert first.model_dump_json() == second.model_dump_json()
    assert first.lock_digest == second.lock_digest

    # A fresh interpreter, twice, under different string-hash seeds: set and
    # dict iteration order is the way "byte-identical" quietly stops being true.
    assert {
        _lock_digest_under_hash_seed("0"),
        _lock_digest_under_hash_seed("1"),
    } == {first.lock_digest}

    requirements, manifests = _two_harness_inputs()
    baseline = dict(requirements=requirements, manifests=manifests)
    perturbations = {
        "research_contract_digest": dict(
            baseline, research_contract_digest=canonical_digest("other-research")
        ),
        "verification_contract_digest": dict(baseline, contract_run_id="run-2"),
        "harness_catalog_snapshot_digest": dict(
            baseline, manifests=_two_harness_inputs(assets="v2")[1]
        ),
        "verification_environment_digest": dict(
            baseline,
            environment=EnvironmentSnapshotV1.create(
                resource_types=("cpu", "gpu", "process"), features=()
            ),
        ),
        "oracle_bundle_digest": dict(
            baseline, oracle_bundle_digest=canonical_digest("other-oracle")
        ),
    }

    rendered = json.loads(first.model_dump_json())
    moved: set[str] = set()
    for named_field, keywords in perturbations.items():
        other = json.loads(_mint_lock(**keywords).model_dump_json())
        changed = {key for key in rendered if rendered[key] != other.get(key)}
        assert named_field in changed, (
            f"changing the {named_field} input left it unchanged in the lock"
        )
        moved |= changed

    declared = {
        name
        for name in type(first).model_fields
        if name.endswith("_digest")
    }
    assert declared, "the baseline Harness Lock declares no digest at all"
    assert declared <= moved, (
        "the lock pins digests that none of its declared inputs moves: "
        f"{sorted(declared - moved)}"
    )
