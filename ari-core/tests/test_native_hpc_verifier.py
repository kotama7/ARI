from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from ari.assurance.catalog import build_harness_catalog_snapshot
from ari.assurance.drivers.native import (
    NATIVE_DRIVER_REVISION,
    NativeHPCDriver,
    native_driver_digest,
)
from ari.assurance.drivers import native_worker
from ari.assurance.executors import HarnessSubstrateError, _resolve_sif_reference
from ari.assurance.models import (
    ContainerPinV1,
    HarnessManifestV1,
    HarnessPropertyCoverageV1,
    HarnessResourceRequirementsV1,
    HarnessTargetDeclarationV1,
    PinnedHarnessAssetV1,
    VerificationContractV1,
    VerificationRequirementV1,
    VerificationScopeV1,
)
from ari.assurance.native_hpc import (
    native_reference,
    registered_native_families,
    verify_native_hpc,
)
from ari.assurance.request import build_native_harness_run_request
from ari.assurance.resolver import mint_baseline_harness_lock, resolve_harness_suite
from ari.assurance.runner import FixedVerifier, HarnessExecutionError
from ari.execution import WorkspaceRefV1, record_completed_execution
from ari.protocols.integrity import bytes_digest
from ari.protocols.scientific_requirements import EnvironmentSnapshotV1


SHA = "sha256:" + "5" * 64
# Built from the REGISTRY, not written out. A family added everywhere else but
# missing here would have been dispatchable, scored and attested while nothing
# in this file ever ran it -- and the suite would still have been green.
REFERENCES = {kind: native_reference(kind)
              for kind in registered_native_families()}


@pytest.mark.parametrize("kind", tuple(REFERENCES))
def test_native_hpc_reference_and_negative_controls(kind):
    reference = REFERENCES[kind]
    clean = verify_native_hpc(kind, reference, tier="screen", seed=41)

    def corrupted(case):
        output = reference(case)
        if output:
            output[0] += 1.0
        return output

    negative = verify_native_hpc(
        kind, corrupted, tier="screen", seed=41, negative_control=True
    )
    assert clean.verdict == "pass"
    assert negative.verdict == "fail"
    assert clean.case_results
    assert clean.categories_covered
    assert negative.negative_control is True


@pytest.mark.parametrize("kind", tuple(REFERENCES))
def test_native_case_generation_and_reports_are_byte_deterministic(kind):
    first = verify_native_hpc(kind, REFERENCES[kind], tier="validate", seed=73)
    second = verify_native_hpc(kind, REFERENCES[kind], tier="validate", seed=73)
    assert first.model_dump_json() == second.model_dump_json()


def test_native_suite_covers_non_degenerate_case_families():
    gemm = verify_native_hpc("gemm", REFERENCES["gemm"])
    spmm = verify_native_hpc("spmm", REFERENCES["spmm"])
    stencil = verify_native_hpc("stencil", REFERENCES["stencil"])
    assert {"shape-transpose-leading-dimension", "nan-inf-policy"}.issubset(
        gemm.categories_covered
    )
    assert {"zero-nnz", "duplicate-index", "unsorted-index"}.issubset(
        spmm.categories_covered
    )
    assert {"boundary-halo-trajectory", "constant-field-metamorphic"}.issubset(
        stencil.categories_covered
    )


def _asset(revision: str, digest: str = SHA) -> PinnedHarnessAssetV1:
    return PinnedHarnessAssetV1(revision=revision, sha256=digest, license="MIT")


def _native_fixture():
    scope = VerificationScopeV1(
        values={
            "language": ("c",),
            "hardware": ("cpu",),
            "dtype": ("float64",),
        }
    )
    requirement = VerificationRequirementV1.create(
        property_id="numerical-equivalence",
        target_kind="shared-library",
        required_methods=("differential-testing",),
        required_tier="screen",
        failure_policy="exclude-from-scientific-frontier",
        scope=scope,
        tolerance_policy_ref="hpc.float64/v1",
        tolerance_policy_digest=SHA,
        source_requirement_refs=("research:metric",),
    )
    contract = VerificationContractV1.create(
        run_id="run-1",
        research_contract_digest=SHA,
        requirements=(requirement,),
        admission_confidence=1.0,
        property_vocabulary_digest=SHA,
    )
    manifest = HarnessManifestV1.create(
        id="hpc/gemm-correctness",
        version="1.0.0",
        kind="artifact_verifier",
        status="verified",
        description="native GEMM verifier fixture",
        maintainer="ari",
        tags=("hpc",),
        subject_types=("program",),
        target_kinds=("shared-library",),
        accepts_external_target=True,
        supported_languages=("c",),
        supported_hardware=("cpu",),
        supported_architectures=("x86_64",),
        supported_dtypes=("float64",),
        supported_domains=("gemm",),
        properties=(
            HarnessPropertyCoverageV1(
                property_id="numerical-equivalence",
                methods=("differential-testing",),
                tiers=("screen",),
                scope=scope,
                tolerance_policy_digest=SHA,
            ),
        ),
        target_interface_contract="gemm-c-abi/v1",
        target_interface_digest=SHA,
        source_repository="https://example.invalid/ari",
        source_full_commit_sha="5" * 40,
        implementation_license="MIT",
        dataset=_asset("native-generated-cases/v1"),
        oracle=_asset("ari-independent-reference/v1"),
        driver=_asset(NATIVE_DRIVER_REVISION, native_driver_digest()),
        model=_asset("none"),
        container=ContainerPinV1(
            reference="example.invalid/ari-harness@sha256:" + "5" * 64,
            resolved_digest=SHA,
            license="MIT",
        ),
        network_policy="deny",
        credential_policy="none",
        filesystem_policy="isolated-readonly-target",
        resources=HarnessResourceRequirementsV1(
            cpu_cores=2,
            memory_bytes=64 * 1024 * 1024,
            accelerators=0,
            disk_bytes=16 * 1024 * 1024,
        ),
        timeout_seconds=60,
        scorer_determinism="deterministic",
        nondeterminism_declaration="none",
        hidden_test_policy="verifier-only",
        oracle_independence="independent",
        tolerance_policy_digest=SHA,
        expected_result_schema="ari.native-hpc-verification-report/v1",
        expected_result_schema_digest=SHA,
        infrastructure_failure_policy="separate",
        retry_limit=1,
        negative_control_report_digest=SHA,
        upstream_parity_report_digest=SHA,
    )
    catalog = build_harness_catalog_snapshot(
        catalog_source_revision="test",
        property_vocabulary_digest=SHA,
        driver_protocol_version="v1",
        manifests=(manifest,),
        registration_report_digests={manifest.id: SHA},
        registration_evidence_digests={manifest.id: SHA},
        promotion_approval_digests={manifest.id: SHA},
    )
    environment = EnvironmentSnapshotV1.create(
        resource_types=("process", "cpu"),
        features=(),
    )
    suite = resolve_harness_suite(
        contract=contract, catalog=catalog, environment=environment
    )
    baseline = mint_baseline_harness_lock(
        run_id="run-1",
        research_contract_digest=SHA,
        contract=contract,
        catalog=catalog,
        environment=environment,
        oracle_bundle_digest=SHA,
        suite=suite,
    )
    return manifest, baseline


def test_native_request_uses_separate_read_only_target_snapshot(tmp_path):
    manifest, baseline = _native_fixture()
    candidate_root = tmp_path / "candidate"
    execution_root = tmp_path / "verification"
    candidate = WorkspaceRefV1(root=str(candidate_root))
    verification = WorkspaceRefV1(root=str(execution_root))
    payload = b"ELF fixture bytes"
    candidate.atomic_write_bytes("candidate.so", payload)
    target_digest = bytes_digest(payload)
    declaration = HarnessTargetDeclarationV1.create(
        logical_name="candidate.so",
        target_kind="shared-library",
        subject_type="program",
        language="c",
        hardware="cpu",
        architecture="x86_64",
        dtype="float64",
        interface_contract="gemm-c-abi/v1",
        target_digest=target_digest,
    )
    request = build_native_harness_run_request(
        run_id="run-1",
        node_id="node-1",
        epoch_id="epoch_000",
        workspace=candidate,
        execution_workspace=verification,
        declaration=declaration,
        manifest=manifest,
        locked=baseline.harnesses[0],
        baseline=baseline,
    )
    assert request.target_workspace.root == str(candidate_root)
    assert request.execution_request.workspace.root == str(execution_root)
    assert verification.file_digest("candidate.so") == target_digest
    assert (execution_root / "candidate.so").stat().st_mode & 0o222 == 0
    assert not (candidate_root / ".ari-assurance-inputs").exists()

    result = record_completed_execution(
        request.execution_request,
        stdout="{}\n",
        stderr="",
        returncode=0,
        inputs_verified=True,
        network_verified=True,
    )
    FixedVerifier._validate_execution_result(request.execution_request, result)
    stale = result.model_copy(update={"request_id": "another-request"})
    with pytest.raises(HarnessExecutionError, match="another request"):
        FixedVerifier._validate_execution_result(request.execution_request, stale)


def test_native_driver_reference_negative_parity_report():
    manifest, _ = _native_fixture()
    report = NativeHPCDriver().parity_probe(manifest)
    assert report["driver_digest"] == native_driver_digest()
    assert report["passed"] is True


def test_logical_sif_reference_uses_private_runtime_root(tmp_path, monkeypatch):
    image = tmp_path / "ari-native-v1.sif"
    image.write_bytes(b"SIF fixture")
    monkeypatch.setenv("ARI_HARNESS_CONTAINER_ROOT", str(tmp_path))
    assert _resolve_sif_reference("apptainer:ari-native-v1.sif") == image

    monkeypatch.delenv("ARI_HARNESS_CONTAINER_ROOT")
    with pytest.raises(HarnessSubstrateError, match="requires"):
        _resolve_sif_reference("apptainer:ari-native-v1.sif")


def test_candidate_host_landlock_hides_oracle_source(tmp_path):
    compiler = shutil.which("cc")
    if compiler is None:
        pytest.skip("C compiler is unavailable")
    source = (
        Path(__file__).parent
        / "fixtures"
        / "assurance"
        / "native_reference_candidate.c"
    )
    library = tmp_path / "probe.so"
    subprocess.run(
        [
            compiler,
            "-std=c11",
            "-O2",
            "-fPIC",
            "-shared",
            "-DARI_PROBE_ORACLE_ACCESS",
            str(source),
            "-o",
            str(library),
        ],
        check=True,
    )
    case = {
        "dtype": "float64",
        "m": 1,
        "n": 1,
        "k": 1,
        "transpose_a": False,
        "transpose_b": False,
        "lda": 1,
        "ldb": 1,
        "ldc": 1,
        "alpha": 1.0,
        "beta": 0.0,
        "a": [2.0],
        "b": [3.0],
        "c": [0.0],
        "thread_count": 1,
    }
    environment = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "PYTHONPATH": str(Path(__file__).parents[1]),
    }
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "ari.assurance.drivers.native_candidate_host",
            "--kind",
            "gemm",
            "--library",
            str(library),
        ],
        input=json.dumps(case),
        text=True,
        capture_output=True,
        check=False,
        env=environment,
    )
    assert completed.returncode == 0, completed.stdout
    assert json.loads(completed.stdout) == {"ok": True, "result": [6.0]}


def test_shared_library_import_does_not_preload_oracle_modules():
    environment = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "PYTHONPATH": str(Path(__file__).parents[1]),
    }
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import ari.assurance.drivers.shared_library; "
                "assert 'ari.assurance.native_hpc' not in sys.modules"
            ),
        ],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )
    assert completed.returncode == 0, completed.stderr


def test_native_worker_scientific_fail_is_a_completed_process(monkeypatch, capsys):
    monkeypatch.setattr(
        native_worker,
        "verify_native_hpc",
        lambda *_args, **_kwargs: SimpleNamespace(
            model_dump_json=lambda: '{"verdict":"fail"}'
        ),
    )

    status = native_worker.main(
        [
            "--kind",
            "gemm",
            "--library",
            "unused-by-fixture.so",
            "--tier",
            "screen",
            "--seed",
            "7",
        ]
    )

    assert status == 0
    assert json.loads(capsys.readouterr().out) == {"verdict": "fail"}
