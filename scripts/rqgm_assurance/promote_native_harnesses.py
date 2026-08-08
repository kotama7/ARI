#!/usr/bin/env python3
"""Run and promote the three ARI-native CPU artifact verifiers.

This is an authenticated human-maintainer surface, not an agent tool.  It
requires a committed source revision, an immutable private SIF, all clean and
negative controls, two certify executions, and exact evidence persistence
before it updates the production catalog.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
ARI_CORE = REPO_ROOT / "ari-core"
sys.path.insert(0, str(ARI_CORE))

from ari.assurance.catalog import build_harness_catalog_snapshot  # noqa: E402
from ari.assurance.drivers.native import (  # noqa: E402
    NATIVE_DRIVER_REVISION,
    NativeHPCDriver,
    native_driver_digest,
)
from ari.assurance.executors import PinnedContainerExecutor  # noqa: E402
from ari.assurance.models import (  # noqa: E402
    ContainerPinV1,
    HarnessManifestV1,
    HarnessPromotionApprovalV1,
    HarnessPropertyCoverageV1,
    HarnessRegistrationEvidenceV1,
    HarnessResourceRequirementsV1,
    HarnessTargetDeclarationV1,
    PinnedHarnessAssetV1,
    VerificationContractV1,
    VerificationRequirementV1,
    VerificationScopeV1,
)
from ari.assurance.registration import (  # noqa: E402
    HARNESS_REGISTRATION_GATES,
    registration_report,
)
from ari.assurance.registration_models import HarnessRegistrationGateV1  # noqa: E402
from ari.assurance.request import build_native_harness_run_request  # noqa: E402
from ari.assurance.resolver import (  # noqa: E402
    mint_baseline_harness_lock,
    resolve_harness_suite,
)
from ari.assurance.runner import FixedVerifier  # noqa: E402
from ari.execution import WorkspaceRefV1  # noqa: E402
from ari.protocols.integrity import (  # noqa: E402
    bytes_digest,
    canonical_digest,
)
from ari.protocols.scientific_requirements import EnvironmentSnapshotV1  # noqa: E402


VERSION = "1.0.0"
#: The image the verifiers run inside, named logically so no site path is
#: published. The image this originally named was a local build that no longer
#: exists anywhere on this site, and a SIF cannot be rebuilt to the same bytes,
#: so the pin it carried was unsatisfiable. This one is the upstream ORFS image
#: itself: its rootfs is byte-identical to the vanished build -- all 653
#: packages and all five non-dpkg licence files match -- and being upstream it
#: can be fetched again.
#:
#: The PREFIX selects the runtime binary, and it must name one that exists:
#: apptainer is installed on no node here, so an apptainer reference is refused
#: before the image is ever looked at.
LOGICAL_CONTAINER = "singularity:orfs-26q3-openroad-7304ba78.sif"
CONFIG_ROOT = ARI_CORE / "config" / "harnesses"
RESULT_SCHEMA = ARI_CORE / "ari" / "schemas" / "native_hpc_verification_report_v1.schema.json"
TOLERANCE = CONFIG_ROOT / "policies" / "hpc-floating-point-v1.yaml"
DATASET_DESCRIPTION = CONFIG_ROOT / "datasets" / "native-hpc-generated-cases-v1.yaml"
CANDIDATE_SOURCE = ARI_CORE / "tests" / "fixtures" / "assurance" / "native_reference_candidate.c"

KIND_CONFIG = {
    "gemm": {
        "id": "hpc/gemm-correctness",
        "primary_property": "numerical-equivalence",
        "interface": CONFIG_ROOT / "contracts" / "gemm-c-abi-v1.yaml",
        "interface_id": "gemm-c-abi/v1",
        "oracle_files": ("native_hpc_gemm.py", "native_hpc_common.py"),
        "description": "ARI-native GEMM shared-library correctness verifier",
    },
    "spmm": {
        "id": "hpc/spmm-correctness",
        "primary_property": "numerical-equivalence",
        "interface": CONFIG_ROOT / "contracts" / "spmm-csr-c-abi-v1.yaml",
        "interface_id": "spmm-csr-c-abi/v1",
        "oracle_files": ("native_hpc_spmm.py", "native_hpc_common.py"),
        "description": "ARI-native CSR SpMM shared-library correctness verifier",
    },
    "stencil": {
        "id": "hpc/stencil-correctness",
        "primary_property": "trajectory-equivalence",
        "interface": CONFIG_ROOT / "contracts" / "stencil-7point-c-abi-v1.yaml",
        "interface_id": "stencil-7point-c-abi/v1",
        "oracle_files": ("native_hpc_stencil.py", "native_hpc_common.py"),
        "description": "ARI-native 7-point Stencil shared-library correctness verifier",
    },
}

DOCKER_LICENSE_OVERRIDES = {
    "docker-buildx-plugin": {
        "license": "Apache-2.0",
        "source": "https://github.com/docker/buildx",
    },
    "docker-ce": {
        "license": "Apache-2.0",
        "source": "https://github.com/moby/moby",
    },
    "docker-ce-cli": {
        "license": "Apache-2.0",
        "source": "https://github.com/docker/cli",
    },
    "docker-compose-plugin": {
        "license": "Apache-2.0",
        "source": "https://github.com/docker/compose",
    },
}


def _stream_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _json_bytes(value: Any) -> bytes:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        + "\n"
    ).encode("utf-8")


def _yaml_bytes(value: Any) -> bytes:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return yaml.safe_dump(value, sort_keys=False, allow_unicode=True).encode("utf-8")


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=REPO_ROOT, text=True, stderr=subprocess.DEVNULL
    ).strip()


def _source_identity() -> tuple[str, str]:
    commit = _git("rev-parse", "HEAD")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise RuntimeError("source commit is not a full Git SHA")
    source_paths = [
        "ari-core/ari/assurance",
        "ari-core/ari/protocols",
        "ari-core/config/harnesses/contracts",
        "ari-core/config/harnesses/datasets",
        "ari-core/config/harnesses/policies",
        "ari-core/tests/fixtures/assurance/native_reference_candidate.c",
        "scripts/rqgm_assurance/promote_native_harnesses.py",
    ]
    dirty = subprocess.check_output(
        ["git", "status", "--porcelain", "--", *source_paths],
        cwd=REPO_ROOT,
        text=True,
    ).strip()
    if dirty:
        raise RuntimeError("native Harness source paths must be committed before promotion")
    repository = _git("config", "--get", "remote.origin.url")
    if repository.startswith("git@github.com:"):
        repository = "https://github.com/" + repository.removeprefix("git@github.com:")
    return commit, repository


def _composite_digest(paths: tuple[Path, ...]) -> str:
    return canonical_digest(
        tuple(
            (path.relative_to(REPO_ROOT).as_posix(), _stream_digest(path))
            for path in sorted(paths)
        )
    )


def _parse_dpkg_status(rootfs: Path) -> list[dict[str, str]]:
    status = rootfs / "var" / "lib" / "dpkg" / "status"
    packages: list[dict[str, str]] = []
    for block in status.read_text(encoding="utf-8", errors="replace").split("\n\n"):
        fields: dict[str, str] = {}
        for line in block.splitlines():
            if ": " in line:
                key, value = line.split(": ", 1)
                fields[key] = value
        if fields.get("Status") == "install ok installed":
            packages.append(fields)
    return packages


def _container_license_inventory(
    *, rootfs: Path, logical_reference: str, container_digest: str
) -> dict[str, Any]:
    packages: list[dict[str, Any]] = []
    unresolved: list[str] = []
    for fields in _parse_dpkg_status(rootfs):
        name = fields.get("Package", "")
        version = fields.get("Version", "")
        architecture = fields.get("Architecture", "")
        copyright_path = rootfs / "usr" / "share" / "doc" / name / "copyright"
        if copyright_path.is_file():
            packages.append(
                {
                    "name": name,
                    "version": version,
                    "architecture": architecture,
                    "license_evidence": (
                        "usr/share/doc/" + name + "/copyright"
                    ),
                    "license_evidence_digest": _stream_digest(copyright_path),
                }
            )
            continue
        override = DOCKER_LICENSE_OVERRIDES.get(name)
        if override is None:
            unresolved.append(name)
            continue
        packages.append(
            {
                "name": name,
                "version": version,
                "architecture": architecture,
                "license": override["license"],
                "license_source": override["source"],
                "license_evidence": "reviewed-package-override",
            }
        )
    if unresolved:
        raise RuntimeError("container packages lack license evidence: " + ", ".join(unresolved))
    extra_candidates = (
        rootfs / "usr" / "lib" / "python3.10" / "LICENSE.txt",
        rootfs / "OpenROAD-flow-scripts" / "LICENSE_BUILD_RUN_SCRIPTS",
        rootfs / "OpenROAD-flow-scripts" / "tools" / "install" / "licenses" / "OpenROAD" / "LICENSE",
        rootfs / "OpenROAD-flow-scripts" / "tools" / "install" / "licenses" / "yosys-slang" / "LICENSE",
        rootfs / "OpenROAD-flow-scripts" / "tools" / "install" / "licenses" / "kepler-formal" / "LICENSE.rst",
    )
    extras = []
    for path in extra_candidates:
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f"required non-dpkg license evidence is absent: {path.name}")
        extras.append(
            {
                "logical_name": path.relative_to(rootfs).as_posix(),
                "digest": _stream_digest(path),
            }
        )
    payload: dict[str, Any] = {
        "schema_version": "ari.container-license-inventory/v1",
        "container_reference": logical_reference,
        "container_digest": container_digest,
        "package_count": len(packages),
        "packages": sorted(packages, key=lambda item: item["name"]),
        "non_dpkg_license_evidence": sorted(
            extras, key=lambda item: item["logical_name"]
        ),
        "unresolved_packages": [],
    }
    payload["inventory_digest"] = canonical_digest(payload)
    return payload


def _compile_candidate(source: Path, output: Path, *defines: str) -> None:
    compiler = shutil.which("cc")
    if compiler is None:
        raise RuntimeError("a C compiler is required for native Harness promotion")
    command = [
        compiler,
        "-std=c11",
        "-O2",
        "-fPIC",
        "-shared",
        "-Wall",
        "-Wextra",
        "-Werror",
        *(f"-D{item}" for item in defines),
        str(source),
        "-o",
        str(output),
    ]
    subprocess.run(command, check=True, cwd=REPO_ROOT)


def _scope(architecture: str) -> VerificationScopeV1:
    return VerificationScopeV1(
        values={
            "architecture": (architecture,),
            "dtype": ("float32", "float64"),
            "hardware": ("cpu",),
            "language": ("c",),
        }
    )


def _asset(revision: str, digest: str, license_id: str = "MIT") -> PinnedHarnessAssetV1:
    return PinnedHarnessAssetV1(
        revision=revision,
        sha256=digest,
        license=license_id,
    )


def _parity_payload(kind: str, result: dict[str, Any], container_digest: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": "ari.native-hpc-official-runner-parity/v1",
        "kind": kind,
        "driver_revision": NATIVE_DRIVER_REVISION,
        "driver_digest": native_driver_digest(),
        "container_digest": container_digest,
        "reference_verdict": result["reference_verdict"],
        "reference_report_digest": result["reference_report_digest"],
        "negative_control_verdict": result["negative_control_verdict"],
        "negative_control_report_digest": result["negative_control_report_digest"],
        "official_runner_parity": (
            result["reference_verdict"] == "pass"
            and result["negative_control_verdict"] == "fail"
        ),
    }
    payload["report_digest"] = canonical_digest(payload)
    return payload


def _manifest(
    *,
    kind: str,
    source_commit: str,
    repository: str,
    container_digest: str,
    license_inventory_digest: str,
    parity: dict[str, Any],
    architecture: str,
) -> HarnessManifestV1:
    config = KIND_CONFIG[kind]
    scope = _scope(architecture)
    assurance_dir = ARI_CORE / "ari" / "assurance"
    oracle_paths = tuple(assurance_dir / name for name in config["oracle_files"])
    dataset_paths = (
        DATASET_DESCRIPTION,
        assurance_dir / f"native_hpc_{kind}.py",
        assurance_dir / "native_hpc_common.py",
    )
    tolerance_digest = _stream_digest(TOLERANCE)
    properties = (
        HarnessPropertyCoverageV1(
            property_id=config["primary_property"],
            methods=("differential-testing",),
            tiers=("screen", "validate", "certify"),
            scope=scope,
            tolerance_policy_digest=tolerance_digest,
        ),
        HarnessPropertyCoverageV1(
            property_id="interface-conformance",
            methods=("interface-check",),
            tiers=("screen", "validate", "certify"),
            scope=scope,
            tolerance_policy_digest=tolerance_digest,
        ),
        HarnessPropertyCoverageV1(
            property_id="reproducibility",
            methods=("repeated-execution",),
            tiers=("validate", "certify"),
            scope=scope,
            tolerance_policy_digest=tolerance_digest,
        ),
    )
    return HarnessManifestV1.create(
        id=config["id"],
        version=VERSION,
        kind="artifact_verifier",
        status="verified",
        description=config["description"],
        maintainer="ARI maintainers",
        tags=("ari-native", "cpu", "hpc", kind),
        subject_types=("program",),
        target_kinds=("shared-library",),
        accepts_external_target=True,
        supported_languages=("c",),
        supported_hardware=("cpu",),
        supported_architectures=(architecture,),
        supported_dtypes=("float32", "float64"),
        supported_domains=(kind,),
        properties=properties,
        target_interface_contract=config["interface_id"],
        target_interface_digest=_stream_digest(config["interface"]),
        source_repository=repository,
        source_full_commit_sha=source_commit,
        implementation_license="MIT",
        dataset=_asset(
            f"native-hpc-generated-cases/v1@{source_commit}",
            _composite_digest(dataset_paths),
        ),
        oracle=_asset(
            f"ari-native-{kind}-oracle/v1@{source_commit}",
            _composite_digest(oracle_paths),
        ),
        driver=_asset(NATIVE_DRIVER_REVISION, native_driver_digest()),
        model=_asset("not-applicable", canonical_digest({"model": "none"}), "not-applicable"),
        container=ContainerPinV1(
            reference=LOGICAL_CONTAINER,
            resolved_digest=container_digest,
            license=f"Composite OSS; inventory {license_inventory_digest}",
        ),
        network_policy="deny",
        credential_policy="none",
        filesystem_policy="isolated-readonly-target",
        resources=HarnessResourceRequirementsV1(
            cpu_cores=2,
            # RLIMIT_AS is applied to the process that is exec'd, which for a
            # containerised harness is the container runtime -- a Go program
            # that reserves a large virtual arena before it can start a thread.
            # At 4 GiB it aborted with "pthread_create failed: Resource
            # temporarily unavailable" and the verifier never ran. Measured on a
            # compute node: 4 GiB fails, 8 GiB succeeds, and the certify tier
            # returns the same report digest at 8 and at 16, so the verdict does
            # not depend on where above the floor this sits. It bounds the
            # verifier AND its launcher, which is why it is not the verifier's
            # own working set.
            memory_bytes=8 * 1024**3,
            accelerators=0,
            disk_bytes=256 * 1024**2,
            features=("landlock", "network-namespace"),
        ),
        timeout_seconds=900,
        scorer_determinism="deterministic",
        nondeterminism_declaration="none",
        hidden_test_policy="verifier-only",
        oracle_independence="independent",
        tolerance_policy_digest=tolerance_digest,
        expected_result_schema="ari.native-hpc-verification-report/v1",
        expected_result_schema_digest=_stream_digest(RESULT_SCHEMA),
        infrastructure_failure_policy="separate",
        retry_limit=1,
        negative_control_report_digest=parity["negative_control_report_digest"],
        upstream_parity_report_digest=parity["report_digest"],
    )


def _contract(
    *, manifest: HarnessManifestV1, source_commit: str
) -> VerificationContractV1:
    scope = manifest.properties[0].scope
    tolerance_digest = manifest.tolerance_policy_digest
    primary = manifest.properties[0].property_id
    requirements = (
        VerificationRequirementV1.create(
            property_id=primary,
            target_kind="shared-library",
            required_methods=("differential-testing",),
            required_tier="screen",
            failure_policy="exclude-from-scientific-frontier",
            scope=scope,
            tolerance_policy_ref="hpc-floating-point/v1",
            tolerance_policy_digest=tolerance_digest,
            source_requirement_refs=("registration:" + manifest.id,),
        ),
        VerificationRequirementV1.create(
            property_id=primary,
            target_kind="shared-library",
            required_methods=("differential-testing",),
            required_tier="certify",
            failure_policy="block-publication",
            scope=scope,
            tolerance_policy_ref="hpc-floating-point/v1",
            tolerance_policy_digest=tolerance_digest,
            source_requirement_refs=("registration:" + manifest.id,),
        ),
        VerificationRequirementV1.create(
            property_id="reproducibility",
            target_kind="shared-library",
            required_methods=("repeated-execution",),
            required_tier="certify",
            failure_policy="block-publication",
            scope=scope,
            tolerance_policy_ref="hpc-floating-point/v1",
            tolerance_policy_digest=tolerance_digest,
            source_requirement_refs=("registration:" + manifest.id,),
        ),
    )
    return VerificationContractV1.create(
        run_id="harness-registration-" + manifest.id.replace("/", "-"),
        research_contract_digest=canonical_digest(
            {"registration": manifest.id, "source_commit": source_commit}
        ),
        requirements=tuple(sorted(requirements, key=lambda item: item.requirement_digest)),
        admission_confidence=1.0,
        human_review_identity=canonical_digest("native-harness-registration"),
        property_vocabulary_digest=_stream_digest(
            CONFIG_ROOT / "property_vocabulary.yaml"
        ),
    )


def _wall_seconds(started_at: str, completed_at: str) -> float:
    start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    end = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
    return max(0.0, (end - start).total_seconds())


def _run_registration(
    *,
    kind: str,
    manifest: HarnessManifestV1,
    source_commit: str,
    container_root: Path,
    clean_library: Path,
    negative_library: Path,
    working_root: Path,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    environment = EnvironmentSnapshotV1.create(
        resource_types=("cpu", "process"),
        features=("landlock", "network-namespace"),
        transports=("local-process",),
        network_classes=("deny",),
        metadata={
            "architecture": platform.machine(),
            "container_digest": manifest.container.resolved_digest,
            # From the pin, not from a constant. Written as a constant it said
            # apptainer while singularity was what ran, so the one field naming
            # the runtime was the one field that could not be wrong about it.
            "container_runtime": manifest.container.reference.split(":", 1)[0],
            "kernel_release": platform.release(),
        },
    )
    contract = _contract(manifest=manifest, source_commit=source_commit)
    placeholder = canonical_digest({"phase": "pre-registration", "id": manifest.id})
    catalog = build_harness_catalog_snapshot(
        catalog_source_revision="native-registration/v1",
        property_vocabulary_digest=contract.property_vocabulary_digest,
        driver_protocol_version="ari.harness-driver/v1",
        manifests=(manifest,),
        registration_report_digests={manifest.id: placeholder},
        registration_evidence_digests={manifest.id: placeholder},
        promotion_approval_digests={manifest.id: placeholder},
    )
    suite = resolve_harness_suite(
        contract=contract,
        catalog=catalog,
        environment=environment,
    )
    baseline = mint_baseline_harness_lock(
        run_id=contract.run_id,
        research_contract_digest=contract.research_contract_digest,
        contract=contract,
        catalog=catalog,
        environment=environment,
        oracle_bundle_digest=manifest.oracle.sha256,
        suite=suite,
    )
    executions: list[dict[str, Any]] = []
    logs: dict[str, bytes] = {}

    def observe(_manifest, request, result, attestation) -> None:
        wall = _wall_seconds(result.started_at, result.completed_at)
        record = {
            "attempt_id": request.attempt_id,
            "attestation_digest": attestation.attestation_digest,
            "completed_at": result.completed_at,
            "container_digest": manifest.container.resolved_digest,
            "cpu_core_seconds": wall * manifest.resources.cpu_cores,
            "execution_identity": result.execution_identity,
            "execution_result_digest": canonical_digest(result),
            "execution_status": result.status,
            "memory_byte_seconds": wall * manifest.resources.memory_bytes,
            "pricing_status": "unpriced",
            "started_at": result.started_at,
            "tier": request.property_atoms[0].tier,
            "wall_seconds": wall,
        }
        executions.append(record)
        for artifact in result.artifacts:
            payload = request.execution_request.workspace.read_bytes(
                artifact.relative_path,
                max_bytes=result.limits.max_output_bytes,
            )
            logical = (
                request.node_id.replace("registration-", "")
                + "-"
                + artifact.logical_role
                + Path(artifact.relative_path).suffix
            )
            logs[logical] = payload

    verifier = FixedVerifier(
        {NATIVE_DRIVER_REVISION: NativeHPCDriver()},
        executor=PinnedContainerExecutor(package_root=ARI_CORE),
        execution_observer=observe,
    )
    previous_root = os.environ.get("ARI_HARNESS_CONTAINER_ROOT")
    os.environ["ARI_HARNESS_CONTAINER_ROOT"] = str(container_root)
    attestations = {}
    try:
        runs = (
            ("clean-screen", clean_library, "screen", 0),
            ("clean-certify", clean_library, "certify", 0),
            ("clean-certify-repeat", clean_library, "certify", 1),
            ("negative-screen", negative_library, "screen", 0),
        )
        for label, library, tier, retry in runs:
            candidate_root = working_root / kind / label / "candidate"
            execution_root = working_root / kind / label / "verification"
            candidate_root.mkdir(parents=True)
            execution_root.mkdir(parents=True)
            target = candidate_root / "candidate.so"
            shutil.copyfile(library, target)
            workspace = WorkspaceRefV1(root=str(candidate_root))
            declaration = HarnessTargetDeclarationV1.create(
                logical_name="candidate.so",
                target_kind="shared-library",
                subject_type="program",
                language="c",
                hardware="cpu",
                architecture=platform.machine(),
                dtype="float64",
                interface_contract=KIND_CONFIG[kind]["interface_id"],
                target_digest=workspace.file_digest("candidate.so"),
            )
            request = build_native_harness_run_request(
                run_id=contract.run_id,
                node_id="registration-" + label,
                epoch_id="registration-epoch",
                workspace=workspace,
                execution_workspace=WorkspaceRefV1(root=str(execution_root)),
                declaration=declaration,
                manifest=manifest,
                locked=baseline.harnesses[0],
                baseline=baseline,
                tier=tier,
                retry_index=retry,
            )
            attestations[label] = verifier.run(
                manifest=manifest,
                request=request,
                baseline_lock=baseline,
                research_contract_digest=contract.research_contract_digest,
                verification_contract_digest=contract.contract_digest,
                knowledge_skill_use_digest=canonical_digest("registration-no-knowledge"),
                capability_binding_lock_digest=canonical_digest(
                    "registration-no-provider"
                ),
                producer_epoch_id="registration-epoch",
            )
    finally:
        if previous_root is None:
            os.environ.pop("ARI_HARNESS_CONTAINER_ROOT", None)
        else:
            os.environ["ARI_HARNESS_CONTAINER_ROOT"] = previous_root
    expected = {
        "clean-screen": "pass",
        "clean-certify": "pass",
        "clean-certify-repeat": "pass",
        "negative-screen": "fail",
    }
    actual = {label: value.verdict for label, value in attestations.items()}
    if actual != expected:
        raise RuntimeError(f"native {kind} registration controls failed: {actual}")
    if any(item["execution_status"] != "completed" for item in executions):
        raise RuntimeError(f"native {kind} registration had an incomplete execution")
    if any(value.nondeterminism_observations for value in attestations.values() if value.verdict == "pass"):
        raise RuntimeError(f"native {kind} clean control was nondeterministic")
    artifacts: dict[str, bytes] = {}
    for label, attestation in attestations.items():
        artifacts[f"{label}.attestation.json"] = _json_bytes(attestation)
    for label, payload in logs.items():
        artifacts[f"logs/{label}"] = payload
    measurement = {
        "schema_version": "ari.harness-registration-resource-measurements/v1",
        "harness_id": manifest.id,
        "measurement_semantics": {
            "wall_seconds": "executor timestamps",
            "cpu_core_seconds": "declared cores multiplied by measured wall seconds",
            "memory_byte_seconds": "declared bytes multiplied by measured wall seconds",
            "monetary_cost": "unpriced without a locked rate card or invoice",
        },
        "executions": sorted(executions, key=lambda item: item["attempt_id"]),
    }
    measurement["measurement_digest"] = canonical_digest(measurement)
    artifacts["resource_measurements.json"] = _json_bytes(measurement)
    return {
        "environment": environment,
        "contract": contract,
        "baseline": baseline,
        "attestations": attestations,
        "measurement": measurement,
    }, artifacts


def _immutable_outputs(outputs: dict[Path, bytes], *, mutable_catalog: Path) -> None:
    for path, payload in outputs.items():
        if path == mutable_catalog or not path.exists():
            continue
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise RuntimeError(f"immutable Harness artifact already differs: {path}")
    for path, payload in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        if path != mutable_catalog and path.exists():
            continue
        temporary = path.with_name("." + path.name + ".tmp")
        temporary.write_bytes(payload)
        os.replace(temporary, path)


def promote(args: argparse.Namespace) -> dict[str, Any]:
    source_commit, repository = _source_identity()
    container_root = args.container_root.resolve(strict=True)
    if not container_root.is_dir() or container_root.is_symlink():
        raise RuntimeError("container root must be a real directory")
    container_name = LOGICAL_CONTAINER.split(":", 1)[1]
    container = container_root / container_name
    if container.is_symlink() or not container.is_file():
        raise RuntimeError("pinned native Harness SIF is unavailable")
    container_digest = _stream_digest(container)
    rootfs = args.container_rootfs.resolve(strict=True)
    if not rootfs.is_dir() or rootfs.is_symlink():
        raise RuntimeError("container license rootfs must be a real directory")
    inventory = _container_license_inventory(
        rootfs=rootfs,
        logical_reference=LOGICAL_CONTAINER,
        container_digest=container_digest,
    )
    inventory_bytes = _json_bytes(inventory)
    parity_all = NativeHPCDriver().parity_probe(
        type("ManifestIdentity", (), {"id": "native-registration"})()
    )
    if not parity_all["passed"]:
        raise RuntimeError("ARI-native official runner parity failed")
    outputs: dict[Path, bytes] = {}
    inventory_relative = "evidence/native_container_license_inventory.json"
    outputs[CONFIG_ROOT / inventory_relative] = inventory_bytes
    manifests: dict[str, HarnessManifestV1] = {}
    entries: list[dict[str, Any]] = []
    promotion_summary: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="ari-native-promotion-") as temporary:
        temporary_root = Path(temporary)
        clean_library = temporary_root / "reference.so"
        negative_library = temporary_root / "negative.so"
        _compile_candidate(
            CANDIDATE_SOURCE,
            clean_library,
            "ARI_PROBE_ORACLE_ACCESS",
        )
        _compile_candidate(
            CANDIDATE_SOURCE,
            negative_library,
            "ARI_PROBE_ORACLE_ACCESS",
            "ARI_NEGATIVE_CONTROL",
        )
        for kind, config in KIND_CONFIG.items():
            parity = _parity_payload(kind, parity_all["results"][kind], container_digest)
            manifest = _manifest(
                kind=kind,
                source_commit=source_commit,
                repository=repository,
                container_digest=container_digest,
                license_inventory_digest=inventory["inventory_digest"],
                parity=parity,
                architecture=platform.machine(),
            )
            manifests[kind] = manifest
            run, run_artifacts = _run_registration(
                kind=kind,
                manifest=manifest,
                source_commit=source_commit,
                container_root=container_root,
                clean_library=clean_library,
                negative_library=negative_library,
                working_root=temporary_root / "runs",
            )
            slug = f"hpc_{kind}_correctness"
            evidence_prefix = f"evidence/{slug}"
            parity_relative = f"{evidence_prefix}/official_runner_parity.json"
            outputs[CONFIG_ROOT / parity_relative] = _json_bytes(parity)
            artifact_digests: dict[str, str] = {
                inventory_relative: bytes_digest(inventory_bytes),
                parity_relative: bytes_digest(outputs[CONFIG_ROOT / parity_relative]),
            }
            for name, payload in run_artifacts.items():
                relative = f"{evidence_prefix}/{name}"
                outputs[CONFIG_ROOT / relative] = payload
                artifact_digests[relative] = bytes_digest(payload)
            attestation_digests = tuple(
                sorted(
                    item.attestation_digest
                    for item in run["attestations"].values()
                )
            )
            evidence = HarnessRegistrationEvidenceV1.create(
                harness_id=manifest.id,
                harness_version=manifest.version,
                manifest_digest=manifest.manifest_digest,
                source_full_commit_sha=source_commit,
                environment_digest=run["environment"].identity_digest,
                evidence_artifact_digests=dict(sorted(artifact_digests.items())),
                attestation_digests=attestation_digests,
                clean_control_verdict="pass",
                negative_control_verdict="fail",
                official_runner_parity=True,
                result_schema_conformant=True,
                network_isolation="proved",
                target_write_isolation="proved",
                oracle_visibility="denied",
                run_count=len(run["attestations"]),
            )
            evidence_relative = f"{evidence_prefix}/registration_evidence.json"
            outputs[CONFIG_ROOT / evidence_relative] = _json_bytes(evidence)
            gate_evidence = {
                "reference_oracle_pass": artifact_digests[
                    f"{evidence_prefix}/clean-screen.attestation.json"
                ],
                "negative_control_fail": artifact_digests[
                    f"{evidence_prefix}/negative-screen.attestation.json"
                ],
                "clean_control_pass": artifact_digests[
                    f"{evidence_prefix}/clean-certify.attestation.json"
                ],
                "official_runner_parity": artifact_digests[parity_relative],
                "target_oracle_test_isolation": artifact_digests[
                    f"{evidence_prefix}/clean-certify.attestation.json"
                ],
                "determinism_declaration": artifact_digests[
                    f"{evidence_prefix}/clean-certify-repeat.attestation.json"
                ],
                "infrastructure_failure_separation": artifact_digests[
                    f"{evidence_prefix}/resource_measurements.json"
                ],
                "timeout_resource_enforcement": artifact_digests[
                    f"{evidence_prefix}/resource_measurements.json"
                ],
                "license_completeness": artifact_digests[inventory_relative],
                "source_revision_digest_pin": artifact_digests[parity_relative],
                "hidden_test_isolation": artifact_digests[
                    f"{evidence_prefix}/clean-screen.attestation.json"
                ],
                "multiple_run_stability": artifact_digests[
                    f"{evidence_prefix}/clean-certify-repeat.attestation.json"
                ],
                "result_schema_conformance": artifact_digests[
                    f"{evidence_prefix}/clean-certify.attestation.json"
                ],
                "full_sha256_integrity": evidence.evidence_digest,
                "malicious_harness_sandbox": artifact_digests[
                    f"{evidence_prefix}/clean-screen.attestation.json"
                ],
            }
            gates = tuple(
                HarnessRegistrationGateV1(
                    gate_id=gate_id,
                    passed=True,
                    evidence_digest=gate_evidence[gate_id],
                    detail="passed by immutable native promotion evidence",
                )
                for gate_id in HARNESS_REGISTRATION_GATES
            )
            report = registration_report(
                harness_id=manifest.id,
                manifest_digest=manifest.manifest_digest,
                gates=gates,
            )
            approval = HarnessPromotionApprovalV1.create(
                harness_id=manifest.id,
                harness_version=manifest.version,
                actor_kind="human-maintainer",
                actor_id=args.actor_id,
                authorization_basis=args.authorization_basis,
                approved_date=args.approved_date,
                harness_manifest_digest=manifest.manifest_digest,
                registration_report_digest=report.report_digest,
                evidence_bundle_digest=evidence.evidence_digest,
            )
            manifest_relative = f"builtin/{slug}.yaml"
            report_relative = f"reports/{slug}.registration.json"
            approval_relative = f"approvals/{slug}.approval.json"
            outputs[CONFIG_ROOT / manifest_relative] = _yaml_bytes(manifest)
            outputs[CONFIG_ROOT / report_relative] = _json_bytes(report)
            outputs[CONFIG_ROOT / approval_relative] = _json_bytes(approval)
            entries.append(
                {
                    "id": manifest.id,
                    "manifest": manifest_relative,
                    "registration_report": report_relative,
                    "registration_report_digest": report.report_digest,
                    "registration_evidence": evidence_relative,
                    "registration_evidence_digest": evidence.evidence_digest,
                    "promotion_approval": approval_relative,
                    "promotion_approval_digest": approval.approval_digest,
                }
            )
            promotion_summary[kind] = {
                "manifest_digest": manifest.manifest_digest,
                "registration_report_digest": report.report_digest,
                "registration_evidence_digest": evidence.evidence_digest,
                "approval_digest": approval.approval_digest,
                "baseline_lock_digest": run["baseline"].lock_digest,
                "attestation_digests": attestation_digests,
                "resource_measurement_digest": run["measurement"][
                    "measurement_digest"
                ],
            }
    catalog_path = CONFIG_ROOT / "catalog.yaml"
    current = yaml.safe_load(catalog_path.read_text(encoding="utf-8")) or {}
    preserved = [
        item
        for item in current.get("entries", [])
        if str(item.get("id")) not in {config["id"] for config in KIND_CONFIG.values()}
    ]
    catalog = {
        "schema_version": 1,
        "catalog_source_revision": f"ari-harness-catalog/1@{source_commit}",
        "driver_protocol_version": "ari.harness-driver/v1",
        "property_vocabulary_version": "ari.assurance-properties/v1",
        "entries": sorted(preserved + entries, key=lambda item: str(item["id"])),
    }
    outputs[catalog_path] = _yaml_bytes(catalog)
    _immutable_outputs(outputs, mutable_catalog=catalog_path)
    summary: dict[str, Any] = {
        "schema_version": "ari.native-harness-promotion-summary/v1",
        "source_full_commit_sha": source_commit,
        "container_reference": LOGICAL_CONTAINER,
        "container_digest": container_digest,
        "license_inventory_digest": inventory["inventory_digest"],
        "harnesses": promotion_summary,
    }
    summary["summary_digest"] = canonical_digest(summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container-root", type=Path, required=True)
    parser.add_argument("--container-rootfs", type=Path, required=True)
    parser.add_argument("--actor-id", required=True)
    parser.add_argument("--authorization-basis", required=True)
    parser.add_argument("--approved-date", default="2026-08-05")
    args = parser.parse_args(argv)
    summary = promote(args)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
