from __future__ import annotations

import json

import pytest
import yaml

from ari.assurance.catalog import (
    build_harness_catalog_snapshot,
    load_harness_catalog,
)
from ari.assurance.lock import validate_harness_revision
from ari.assurance.models import (
    ContainerPinV1,
    HarnessLockRevisionV1,
    HarnessManifestV1,
    HarnessPropertyCoverageV1,
    HarnessResourceRequirementsV1,
    HarnessPromotionApprovalV1,
    HarnessRegistrationEvidenceV1,
    PinnedHarnessAssetV1,
    VerificationContractV1,
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
from ari.protocols.integrity import canonical_digest
from ari.protocols.scientific_requirements import EnvironmentSnapshotV1


SHA = "sha256:" + ("4" * 64)


def _requirement(*, methods=("differential-testing",), tier="screen"):
    return VerificationRequirementV1.create(
        property_id="numerical-equivalence",
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


def _contract(requirements=None):
    reqs = tuple(requirements or (_requirement(),))
    return VerificationContractV1.create(
        run_id="run-1",
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
                property_id="numerical-equivalence",
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
        source_full_commit_sha="4" * 40,
        implementation_license="MIT",
        dataset=_asset("dataset-v1"),
        oracle=_asset("oracle-v1"),
        driver=_asset("native-v1"),
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


def test_benchmark_cannot_cover_arbitrary_artifact_requirement():
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


def test_baseline_lock_and_revision_are_monotonic():
    manifest = _manifest()
    contract = _contract()
    catalog = _catalog((manifest,))
    suite = resolve_harness_suite(
        contract=contract, catalog=catalog, environment=_environment()
    )
    baseline = mint_baseline_harness_lock(
        run_id="run-1",
        research_contract_digest=SHA,
        contract=contract,
        catalog=catalog,
        environment=_environment(),
        oracle_bundle_digest=SHA,
        suite=suite,
    )
    revision = HarnessLockRevisionV1.create(
        run_id="run-1",
        next_epoch_id="epoch_001",
        parent_lock_digest=baseline.lock_digest,
        baseline_lock_digest=baseline.lock_digest,
        added_requirement_refs=(),
        added_or_strengthened_harnesses=(),
        active_harnesses=baseline.harnesses,
        coverage_proof_digest=baseline.coverage_proof_digest,
    )
    validate_harness_revision(baseline=baseline, revision=revision)
    changed = baseline.harnesses[0].model_copy(update={"oracle_digest": canonical_digest("changed")})
    bad = HarnessLockRevisionV1.create(
        run_id="run-1",
        next_epoch_id="epoch_001",
        parent_lock_digest=baseline.lock_digest,
        baseline_lock_digest=baseline.lock_digest,
        added_requirement_refs=(),
        added_or_strengthened_harnesses=(changed,),
        active_harnesses=(changed,),
        coverage_proof_digest=baseline.coverage_proof_digest,
    )
    with pytest.raises(ValueError, match="replace pinned"):
        validate_harness_revision(baseline=baseline, revision=bad)


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


def _write_verified_catalog(tmp_path):
    manifest = _manifest()
    evidence_digest = canonical_digest("harness-registration-evidence")
    report = registration_report(
        harness_id=manifest.id,
        manifest_digest=manifest.manifest_digest,
        gates=tuple(
            HarnessRegistrationGateV1(
                gate_id=gate_id,
                passed=True,
                evidence_digest=evidence_digest,
            )
            for gate_id in HARNESS_REGISTRATION_GATES
        ),
    )
    evidence = HarnessRegistrationEvidenceV1.create(
        harness_id=manifest.id,
        harness_version=manifest.version,
        manifest_digest=manifest.manifest_digest,
        source_full_commit_sha="4" * 40,
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
