#!/usr/bin/env python3
"""Run and promote the three ARI-native CPU artifact verifiers.

This is an authenticated human-maintainer surface, not an agent tool.  It
requires a committed source revision, an immutable private SIF, all clean and
negative controls, two certify executions, and exact evidence persistence
before it updates the production catalog.

WHAT THE REGISTRATION EVIDENCE RESTS ON. This surface really does run its
controls -- four container executions per family, below -- and it used to throw
the answer away: ``HarnessRegistrationEvidenceV1.create`` was handed
``clean_control_verdict="pass"``, ``negative_control_verdict="fail"``,
``official_runner_parity=True``, ``result_schema_conformant=True``,
``network_isolation="proved"``, ``target_write_isolation="proved"`` and
``oracle_visibility="denied"`` as literal keyword arguments, so the bundle said
the same seven things whatever the executions returned. The refusals above the
call meant the record happened to be true, which is a different property from
being read: weaken one refusal and the record keeps its claim. Every one of the
seven is now derived -- the two control verdicts by role from the attestations,
the four isolation and schema fields by the sibling surface's
``isolation_findings`` over what each ``ExecutionRequest`` carried and what each
run returned, and parity from this family's own probe result. This was the last
surface still declaring them; ``d85d9768`` closed the same defect in
``repin_and_promote_harness.py`` by refusing instead, because that surface runs
nothing it could read.

AND WHY THAT DERIVATION COULD NOT REACH THE SHIPPED BUNDLES. The three native
bundles on disk were written by an older writer, and ``_immutable_outputs``
refuses any existing artifact whose bytes change -- so a second promotion was
refused outright and the stale bundles could not be regenerated at all. The
guard is right about what it was built for: rewriting registration history under
a signature that was given for different bytes must stay refused. What it did
not draw is the distinction between that and a SIGNED RE-REGISTRATION -- running
every control again, deriving every field from those runs again, and signing the
whole bundle again -- which is a legitimate act and the one the two sibling
surfaces (``attest_problem_correctness.py``, ``attest_gemm_performance.py``)
already perform for their families.

``--re-register`` is that act, and it is deliberately awkward:

* it is EXPLICIT at the call site and never a fallback. It names the harness ids
  whose bundles this maintainer accepts replacing; a plain promotion of an
  already-promoted harness still refuses, and says where the path is;
* it is ALL-OR-NOTHING per harness. ``BundleReplacement`` carries every path this
  run produced for one harness, and ``_immutable_outputs`` refuses if a single
  artifact of that bundle on disk is not among them -- because a new bundle
  standing beside one old artifact is one evidence directory describing two
  different runs;
* it cannot be exercised without the runs. A ``BundleReplacement`` is minted only
  by ``_bundle_replacement``, which refuses unless the four controls of
  ``REGISTRATION_CONTROLS`` all attested and the attestation bytes about to be
  written carry those runs' own digests. Permission to overwrite is therefore a
  RECEIPT for executions that happened, not a flag;
* the signature is unchanged and still required.

AND THE RUN PRODUCES THE WHOLE BUNDLE, which is what makes the all-or-nothing
rule satisfiable rather than merely strict. The three shipped bundles carry four
artifacts this surface used to leave to another writer -- ``registration_report``
, ``gate_findings``, ``multiple_run_stability`` and ``measurement_environment``
-- and that is how they came to describe two runs at once: ``01c87015`` rewrote
exactly those four and the registration evidence beside attestations minted on a
different day, and it is the run that never happened there whose digest ended up
in ``attestation_digests``. All four are derived from things this surface already
computes -- the registration report it earns, the gates that report carries, the
parity probe's own clean-control record, and the process environment -- so it
writes them itself, and ``register_harness`` is therefore called BEFORE the
registration evidence is built rather than after, so the evidence can pin the
report the approval signs. The last published byte then passes
``refuse_host_identity``: ``measurement_environment`` captures variable VALUES,
which is the artifact measured elsewhere in this repository to have carried a
home directory and a username into a committed bundle.
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
from typing import Any, NamedTuple

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
ARI_CORE = REPO_ROOT / "ari-core"
sys.path.insert(0, str(ARI_CORE))
# The sibling attestation surface, for the derivations this file must not grow a
# second copy of. Inserted at import time, the same way that file reaches
# ``repin_and_promote_harness`` and ``attest_gemm_performance`` reaches this one.
sys.path.insert(0, str(Path(__file__).resolve().parent))

# THE DERIVATIONS, NOT A SECOND IMPLEMENTATION OF THEM. ``isolation_findings``
# already reads ``network_isolation``, ``target_write_isolation``,
# ``oracle_visibility`` and ``result_schema_conformant`` off what each request
# carried and what each run returned, and it resolves the driver from
# ``manifest.driver.revision`` rather than from a family constant -- so it is
# correct for ``NativeHPCDriver`` without an edit. ``_single`` is the honest
# collapse of a group of control verdicts, returning ``not_available`` when they
# disagree instead of picking one. Writing either afresh here would put the same
# claim in two places, free to drift apart.
from attest_problem_correctness import (  # noqa: E402
    _single,
    isolation_findings,
    refuse_host_identity,
)
from ari.assurance.catalog import build_harness_catalog_snapshot  # noqa: E402
from ari.assurance.drivers.native import (  # noqa: E402
    NATIVE_DRIVER_REVISION,
    NativeHPCDriver,
    native_driver_digest,
)
from ari.assurance.container_identity import read_binding  # noqa: E402
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
from ari.assurance.registration_run import register_harness  # noqa: E402
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


class RegistrationControl(NamedTuple):
    """One labelled execution, the artifact its role stages, and its own verdict.

    ``role`` does two jobs on purpose. It selects which library is copied into
    the candidate workspace, AND it decides which of the two registration-
    evidence verdicts that run counts toward. One field for both means the group
    a verdict lands in cannot disagree with the ``.so`` that produced it -- which
    is the only thing that makes ``clean_control_verdict`` a reading rather than
    a restatement of the label it was written beside.
    """

    label: str
    role: str
    tier: str
    retry_index: int
    verdict: str


#: THE FOUR EXECUTIONS a native family is registered on. The expected verdicts
#: used to be a second dict spelling the same four labels out again beside the
#: run table; with one table a label cannot be checked for and never run, or run
#: and never checked.
REGISTRATION_CONTROLS: tuple[RegistrationControl, ...] = (
    RegistrationControl("clean-screen", "reference", "screen", 0, "pass"),
    RegistrationControl("clean-certify", "reference", "certify", 0, "pass"),
    RegistrationControl("clean-certify-repeat", "reference", "certify", 1, "pass"),
    RegistrationControl("negative-screen", "negative-control", "screen", 0, "fail"),
)

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
            # WHAT THE REQUEST ACTUALLY CARRIED, not what the manifest asked
            # for. ``container_digest`` above is copied off the manifest, so it
            # says the same thing whether or not a run honoured it; these two
            # are read from the reviewed ``ExecutionRequest`` the executor was
            # handed, which is what lets ``isolation_findings`` derive
            # ``network_isolation`` instead of the caller asserting it.
            "container_identity_digest": (
                request.execution_request.container.digest
                if request.execution_request.container is not None else None),
            "network": request.execution_request.network,
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
    libraries = {"reference": clean_library, "negative-control": negative_library}
    previous_root = os.environ.get("ARI_HARNESS_CONTAINER_ROOT")
    os.environ["ARI_HARNESS_CONTAINER_ROOT"] = str(container_root)
    attestations = {}
    #: ``label -> (digest declared before the run, digest read after it)``.
    #: ``FixedVerifier`` refuses to mint an attestation when they differ, so this
    #: is recorded rather than inferred: ``target_write_isolation`` then names an
    #: observation a reader can recompute from the bundle.
    target_digests: dict[str, tuple[str, str]] = {}
    try:
        for control in REGISTRATION_CONTROLS:
            label, tier, retry = control.label, control.tier, control.retry_index
            candidate_root = working_root / kind / label / "candidate"
            execution_root = working_root / kind / label / "verification"
            candidate_root.mkdir(parents=True)
            execution_root.mkdir(parents=True)
            target = candidate_root / "candidate.so"
            shutil.copyfile(libraries[control.role], target)
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
            target_digests[label] = (
                declaration.target_digest, workspace.file_digest("candidate.so"))
    finally:
        if previous_root is None:
            os.environ.pop("ARI_HARNESS_CONTAINER_ROOT", None)
        else:
            os.environ["ARI_HARNESS_CONTAINER_ROOT"] = previous_root
    expected = {control.label: control.verdict for control in REGISTRATION_CONTROLS}
    actual = {label: value.verdict for label, value in attestations.items()}
    if actual != expected:
        raise RuntimeError(f"native {kind} registration controls failed: {actual}")
    if any(item["execution_status"] != "completed" for item in executions):
        raise RuntimeError(f"native {kind} registration had an incomplete execution")
    if any(value.nondeterminism_observations for value in attestations.values() if value.verdict == "pass"):
        raise RuntimeError(f"native {kind} clean control was nondeterministic")

    # THE FIELDS registration evidence used to be handed as literals, taken
    # instead off the four executions above. The refusals before this point are
    # what make the derivation worth anything -- a run whose controls did not
    # discriminate never reaches here -- but they are not a substitute for it:
    # the previous shape ran the same four executions and then wrote "pass",
    # "fail", "proved", "proved", "denied" and two ``True``s regardless of what
    # came back, so the record was true only by coincidence of the guard above
    # it, and any weakening of that guard would have gone unrecorded.
    controls = {
        "clean_control_verdict": _single(
            [actual[control.label] for control in REGISTRATION_CONTROLS
             if control.role == "reference"]),
        "negative_control_verdict": _single(
            [actual[control.label] for control in REGISTRATION_CONTROLS
             if control.role != "reference"]),
    }
    isolation = isolation_findings(
        manifest,
        executions=executions,
        target_digests=target_digests,
        attestations=attestations,
    )

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

    # AND THE DERIVATION IS PUBLISHED, not only its answer. Most of it is
    # recomputable from bytes this bundle already pins -- the attestations, and
    # the per-execution ``network`` and ``container_identity_digest`` above --
    # but the digest of the candidate AFTER each run is held in no artifact at
    # all, so ``target_write_isolation`` would have been derived and still
    # unauditable, which is only one step better than the literal it replaces.
    # ``isolation["basis"]`` carries it, beside what each of the other claims
    # rests on. ``official_runner_parity`` is the one field absent here, and on
    # purpose: it comes from the parity probe, which this bundle already
    # publishes whole as ``official_runner_parity.json``.
    derivation = {
        "schema_version": "ari.harness-registration-control-derivation/v1",
        "harness_id": manifest.id,
        "harness_version": manifest.version,
        "manifest_digest": manifest.manifest_digest,
        "runs": [
            {
                "label": control.label,
                "role": control.role,
                "tier": control.tier,
                "retry_index": control.retry_index,
                "required_verdict": control.verdict,
                "observed_verdict": actual[control.label],
                "attestation_digest": attestations[
                    control.label].attestation_digest,
            }
            for control in REGISTRATION_CONTROLS
        ],
        "clean_control_verdict": controls["clean_control_verdict"],
        "negative_control_verdict": controls["negative_control_verdict"],
        "isolation": isolation,
        "verdict_source": (
            "read back off HarnessAttestationV1 artifacts minted from container "
            "executions and off the ExecutionRequest each run carried; no field "
            "in this record was asserted"),
    }
    derivation["derivation_digest"] = canonical_digest(derivation)
    artifacts["control_derivation.json"] = _json_bytes(derivation)

    return {
        "environment": environment,
        "contract": contract,
        "baseline": baseline,
        "attestations": attestations,
        "measurement": measurement,
        "controls": controls,
        "isolation": isolation,
        "derivation": derivation,
    }, artifacts


class BundleReplacement(NamedTuple):
    """Permission to overwrite ONE harness's registration artifacts, this run.

    Not a flag and not a set of paths a caller may assemble: the only way to hold
    one is ``_bundle_replacement``, which refuses unless the four controls of
    ``REGISTRATION_CONTROLS`` all attested and the attestation bytes this run is
    about to write carry those runs' own digests. So the permission to replace an
    artifact and the executions that justify replacing it cannot come apart --
    which is the whole difference between a re-registration and an edit.

    ``produced`` is every path this run wrote for this harness, bundle and
    manifest and report and approval alike. ``bundle_root`` is the evidence
    directory, and it is separate because it is the one place where a file can
    survive a replacement it was not part of: the guard walks it and refuses if
    anything there is not in ``produced``.
    """

    harness_id: str
    bundle_root: Path
    produced: frozenset[Path]


def _bundle_replacement(
    *,
    harness_id: str,
    bundle_root: Path,
    produced: frozenset[Path],
    outputs: dict[Path, bytes],
    attestations: dict[str, Any],
) -> BundleReplacement:
    """Mint the receipt, or refuse. THE TIE BETWEEN THE WRITE AND THE RUN.

    Every check here asks the same question in a different place: are the bytes
    that are about to replace a signed artifact the bytes THIS run's container
    executions produced? A ``--re-register`` that only had to be typed would be a
    way to replace registration history without re-earning it, which is the
    defect one flag away from the one this surface just repaired.
    """
    labels = {control.label for control in REGISTRATION_CONTROLS}
    if set(attestations) != labels:
        raise RuntimeError(
            f"{harness_id}: re-registration needs all {len(labels)} controls "
            f"attested; this run has {sorted(attestations)}")
    for control in REGISTRATION_CONTROLS:
        path = bundle_root / f"{control.label}.attestation.json"
        payload = outputs.get(path)
        if payload is None:
            raise RuntimeError(
                f"{harness_id}: re-registration would not rewrite {path.name}, "
                f"so the replaced bundle would keep another run's attestation")
        if path not in produced:
            raise RuntimeError(
                f"{harness_id}: {path.name} is written but not claimed by the "
                f"replacement, which would leave it outside the guard")
        carried = json.loads(payload.decode("utf-8")).get("attestation_digest")
        if carried != attestations[control.label].attestation_digest:
            raise RuntimeError(
                f"{harness_id}: the bytes staged for {path.name} do not carry "
                f"the digest this run's {control.label} execution returned")
    evidence = bundle_root / "registration_evidence.json"
    if evidence not in produced or evidence not in outputs:
        raise RuntimeError(
            f"{harness_id}: a replacement that does not rewrite "
            f"registration_evidence.json leaves the bundle's own index naming "
            f"artifacts it no longer contains")
    return BundleReplacement(harness_id, bundle_root, frozenset(produced))


def _immutable_outputs(
    outputs: dict[Path, bytes],
    *,
    mutable_catalog: Path,
    replacements: tuple[BundleReplacement, ...] = (),
) -> None:
    """Write the promotion, refusing any silent change to a signed artifact.

    THE DEFAULT IS STILL REFUSAL. ``replacements`` is empty unless ``promote``
    was given ``--re-register``, so an ordinary promotion whose bytes differ from
    what is on disk fails exactly as before -- and now says where the path is.
    """
    replaceable: set[Path] = set()
    for replacement in replacements:
        unproduced = sorted(str(path) for path in replacement.produced
                            if path not in outputs)
        if unproduced:
            raise RuntimeError(
                f"{replacement.harness_id}: the replacement claims "
                f"{len(unproduced)} path(s) this run did not produce, first "
                f"{unproduced[0]}; a bundle may only be replaced by one this "
                f"run produced whole")
        replaceable |= replacement.produced
    for replacement in replacements:
        leftover = sorted(
            str(path.relative_to(replacement.bundle_root))
            for path in replacement.bundle_root.rglob("*")
            if not (path.is_dir() and not path.is_symlink())
            and path not in replacement.produced
        ) if replacement.bundle_root.is_dir() else []
        if leftover:
            raise RuntimeError(
                f"{replacement.harness_id}: partial re-registration refused. "
                f"{len(leftover)} artifact(s) of the bundle on disk were not "
                f"produced by this run: {', '.join(leftover)}. Keeping an old "
                f"artifact beside new ones leaves one evidence directory "
                f"describing two different runs. Remove the superseded files in "
                f"a committed change, then re-run.")
    for path, payload in outputs.items():
        if path == mutable_catalog or path in replaceable or not path.exists():
            continue
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise RuntimeError(
                f"immutable Harness artifact already differs: {path}. Those "
                f"bytes carry a maintainer signature given for what is on disk, "
                f"so rewriting them here would move registration history under "
                f"it. Replacing them is a re-registration, not a promotion: pass "
                f"--re-register with the harness id that owns this artifact, "
                f"which re-runs all four controls, re-derives every evidence "
                f"field from those runs, replaces that harness's bundle whole "
                f"and needs a fresh maintainer signature")
    for path, payload in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        if path != mutable_catalog and path not in replaceable and path.exists():
            continue
        temporary = path.with_name("." + path.name + ".tmp")
        temporary.write_bytes(payload)
        os.replace(temporary, path)


def promote(args: argparse.Namespace) -> dict[str, Any]:
    # Imported here, the way the sibling surface imports them: both pull in
    # subpackages this module otherwise never touches, and the AST tests over
    # this file parse it without executing it.
    from ari.assurance.native_perf_common import measurement_environment
    from ari.orchestrator.node_summary_view import scrub_host_identity

    source_commit, repository = _source_identity()
    # ASKED FIRST, BECAUSE IT COSTS NOTHING. A mistyped harness id arrives twelve
    # container executions late if it is read where it is used. Absent, this is
    # the empty set and every existing artifact stays immutable.
    requested = tuple(dict.fromkeys(getattr(args, "re_register", None) or ()))
    registered_ids = {config["id"] for config in KIND_CONFIG.values()}
    unknown = sorted(set(requested) - registered_ids)
    if unknown:
        raise RuntimeError(
            f"--re-register names {unknown}, which this surface does not "
            f"register; it registers {sorted(registered_ids)}")
    re_registering = frozenset(requested)
    container_root = args.container_root.resolve(strict=True)
    if not container_root.is_dir() or container_root.is_symlink():
        raise RuntimeError("container root must be a real directory")
    container_name = LOGICAL_CONTAINER.split(":", 1)[1]
    container = container_root / container_name
    if container.is_symlink() or not container.is_file():
        raise RuntimeError("pinned native Harness SIF is unavailable")
    # THE CONTENT DIGEST, WHICH IS WHAT A MANIFEST PINS. This was
    # _stream_digest(container) -- sha256 over the SIF's bytes -- and the
    # executor compares a manifest's resolved_digest against the site binding's
    # CONTENT digest, so a manifest built here pinned the wrong kind of thing
    # and every run refused with "the bound image is not the content this
    # Harness pins". Measured on the pinned OpenROAD image: file digest
    # sha256:b8af5db8..., content digest sha256:91248e07..., and the three
    # shipped manifests all pin the latter.
    #
    # Read from the binding rather than recomputed: reading the whole rootfs
    # costs more than the verification does, which is why the binding exists.
    # An unbound image is refused here rather than pinned on its file bytes,
    # because an unbound image is one nobody has checked.
    binding = read_binding(container_root, container_name)
    if binding is None:
        raise RuntimeError(
            f"no site binding records what is inside {container_name}; run "
            f"scripts/rqgm_assurance/bind_container_image.py against it first")
    container_digest = str(binding.get("content_digest") or "")
    if not container_digest:
        raise RuntimeError(f"the site binding for {container_name} records no content")
    if binding.get("file_digest") != _stream_digest(container):
        raise RuntimeError(
            f"{container_name} has changed since its content was established; "
            f"the binding no longer describes this file")
    rootfs = args.container_rootfs.resolve(strict=True)
    if not rootfs.is_dir() or rootfs.is_symlink():
        raise RuntimeError("container license rootfs must be a real directory")
    inventory = _container_license_inventory(
        rootfs=rootfs,
        logical_reference=LOGICAL_CONTAINER,
        container_digest=container_digest,
    )
    inventory_bytes = _json_bytes(inventory)
    driver = NativeHPCDriver()
    parity_all = driver.parity_probe(
        type("ManifestIdentity", (), {"id": "native-registration"})()
    )
    if not parity_all["passed"]:
        raise RuntimeError("ARI-native official runner parity failed")
    # WHAT THE MEASUREMENTS WERE TAKEN UNDER, read ONCE and read HERE. The
    # capture is by prefix, so it takes any ``ARI_*`` variable's value --
    # and ``_run_registration`` sets ``ARI_HARNESS_CONTAINER_ROOT`` to a site
    # path for the duration of its executions. Read before the first run it
    # cannot be captured; read after one it would be, restored or not, and a
    # published bundle would name this machine's filesystem. Values are scrubbed
    # of host identity as the sibling surface scrubs them, and every published
    # byte is checked again below.
    environment_record = measurement_environment()
    environment_record["variables"] = {
        key: scrub_host_identity(value)
        for key, value in environment_record["variables"].items()
    }
    outputs: dict[Path, bytes] = {}
    inventory_relative = "evidence/native_container_license_inventory.json"
    outputs[CONFIG_ROOT / inventory_relative] = inventory_bytes
    # THE ONE ARTIFACT NO SINGLE HARNESS OWNS. All three bundles pin the licence
    # inventory, so it may only move when all three are being reproduced in the
    # same run; re-registering one family and letting its inventory bytes land
    # under the other two signatures is the silent change this guard is for. When
    # the family is not being replaced whole this stays empty and the inventory
    # falls back to the immutable rule, which refuses and says why.
    shared_paths: tuple[Path, ...] = (
        (CONFIG_ROOT / inventory_relative,)
        if re_registering == registered_ids else ())
    replacements: list[BundleReplacement] = []
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
            # THE GATES ARE EARNED, NOT ASSERTED. This block used to map each
            # gate id to some artifact digest, stamp passed=True on all fifteen
            # with the detail "passed by immutable native promotion evidence",
            # and hand the set to registration_report. That is precisely the
            # shape ccdedc9 removed -- its docstring says there is deliberately
            # no way to hand this function a pre-decided gate -- and the call
            # has raised TypeError ever since, so this promotion surface has
            # been dead code rather than a checked one.
            #
            # The evidence above is not discarded: the container executions,
            # the attestations, the licence inventory and the resource
            # measurements are still written and still pinned by
            # registration_evidence. What changed is that the VERDICT now comes
            # from a probe this call ran, through the same driver-agnostic path
            # every other harness uses. A promotion that cannot pass its own
            # gates now fails here instead of recording that it passed.
            #
            # IT RUNS BEFORE THE BUNDLE IS STAGED, not after, because the bundle
            # PINS the report: an evidence record built first can only pin the
            # artifacts that already exist, which is how a bundle ends up citing
            # a registration report it does not contain. Nothing has been
            # written at this point -- every output lands in one map and is
            # flushed once at the end -- so the clean-tree requirement this call
            # makes is still asked of the tree the source pin was taken from.
            report = register_harness(
                manifest, driver, runs=args.probe_runs, allow_dirty=False)
            if report.decision != "eligible-for-verified":
                failed = [g.gate_id for g in report.gates if not g.passed]
                raise RuntimeError(
                    f"{manifest.id}: registration rejected on {failed}; nothing "
                    f"is promoted. A rejected registration is a result.")
            # AND WHAT THE GATES FOUND IS PUBLISHED BESIDE THE RUNS. These four
            # are in every shipped bundle and were written by a surface that ran
            # nothing, which is exactly how one evidence directory came to hold
            # today's attestations and another day's findings. Every one of them
            # is a reading of something this run did: the report it just earned,
            # that report's own gate list, the clean-control record the parity
            # probe returned, and the environment read before the first
            # execution.
            run_artifacts["registration_report.json"] = _json_bytes(report)
            run_artifacts["gate_findings.json"] = _json_bytes(
                {gate.gate_id: {"passed": gate.passed, "detail": gate.detail}
                 for gate in report.gates})
            run_artifacts["multiple_run_stability.json"] = _json_bytes(
                {"runs": args.probe_runs,
                 "clean_control": (parity_all.get("controls") or {}).get("clean")})
            run_artifacts["measurement_environment.json"] = _json_bytes({
                "environment": environment_record,
                "registration_commit": source_commit,
                "placement": None,
                "placement_note": ("this harness pins no placement, so its "
                                   "evidence does not describe a machine"),
                "environment_note": ("variable VALUES are scrubbed of host "
                                     "identity here"),
            })
            # SAID WHILE IT IS STILL RUNNING, on stderr so stdout stays the one
            # machine-readable summary. Twelve container executions and three
            # gate sweeps behind a single JSON line at the end is a surface that
            # cannot be watched, and a run that ends in a refusal -- the ordinary
            # outcome of a promotion whose bundles are already on disk -- would
            # otherwise report none of what it established on the way there.
            print(f"{manifest.id:<24} "
                  f"clean={run['controls']['clean_control_verdict']:<4} "
                  f"negative={run['controls']['negative_control_verdict']:<4} "
                  f"runs={len(run['attestations'])} "
                  f"gates={sum(1 for gate in report.gates if gate.passed)}"
                  f"/{len(report.gates)}",
                  file=sys.stderr, flush=True)
            parity_relative = f"{evidence_prefix}/official_runner_parity.json"
            outputs[CONFIG_ROOT / parity_relative] = _json_bytes(parity)
            # EVERY PATH THIS RUN WROTE FOR THIS HARNESS, accumulated as it is
            # written rather than re-derived afterwards: a second list of the
            # same paths is free to omit one, and an omitted path is an artifact
            # of the old bundle surviving into the new one.
            produced: set[Path] = {CONFIG_ROOT / parity_relative, *shared_paths}
            artifact_digests: dict[str, str] = {
                inventory_relative: bytes_digest(inventory_bytes),
                parity_relative: bytes_digest(outputs[CONFIG_ROOT / parity_relative]),
            }
            for name, payload in run_artifacts.items():
                relative = f"{evidence_prefix}/{name}"
                outputs[CONFIG_ROOT / relative] = payload
                produced.add(CONFIG_ROOT / relative)
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
                # OBSERVED, NOT DECLARED. Every one of the seven below was a
                # literal on this surface: "pass", "fail", True, True, "proved",
                # "proved", "denied", written whatever the four executions
                # returned. They now come from the runs -- the two control
                # verdicts by role from the attestations, the four isolation and
                # schema fields from ``isolation_findings`` over what each request
                # carried and what each run returned, and parity from THIS kind's
                # probe result rather than the whole-probe boolean, because this
                # evidence is about this kind's manifest.
                clean_control_verdict=run["controls"]["clean_control_verdict"],
                negative_control_verdict=run["controls"][
                    "negative_control_verdict"],
                official_runner_parity=bool(parity["official_runner_parity"]),
                result_schema_conformant=run["isolation"][
                    "result_schema_conformant"],
                network_isolation=run["isolation"]["network_isolation"],
                target_write_isolation=run["isolation"]["target_write_isolation"],
                oracle_visibility=run["isolation"]["oracle_visibility"],
                run_count=len(run["attestations"]),
            )
            evidence_relative = f"{evidence_prefix}/registration_evidence.json"
            outputs[CONFIG_ROOT / evidence_relative] = _json_bytes(evidence)
            produced.add(CONFIG_ROOT / evidence_relative)
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
            produced.update({CONFIG_ROOT / manifest_relative,
                             CONFIG_ROOT / report_relative,
                             CONFIG_ROOT / approval_relative})
            # THE RECEIPT IS TAKEN HERE OR NOWHERE. It is minted from this
            # harness's own attestations against the bytes staged above, after
            # the controls have run and the gates have passed, so a replacement
            # cannot exist for a harness whose executions did not happen. A kind
            # nobody named is simply absent from the list, and every artifact it
            # already has stays immutable.
            if manifest.id in re_registering:
                replacements.append(_bundle_replacement(
                    harness_id=manifest.id,
                    bundle_root=CONFIG_ROOT / evidence_prefix,
                    produced=frozenset(produced),
                    outputs=outputs,
                    attestations=run["attestations"],
                ))
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
    # EVERY PUBLISHED BYTE, ONCE, IMMEDIATELY BEFORE THE ONLY WRITE. ``outputs``
    # is the complete set this surface puts into a committed tree -- bundle,
    # manifests, reports, approvals and the catalog alike -- so the guard's
    # coverage is a property of the shape rather than of statement order. It
    # refuses rather than scrubs: a scrub leaves a clean-looking bundle and no
    # way to tell which artifact leaked, and the leak recurs on the next run.
    # Keyed by repository-relative path so a refusal names the file without
    # printing the very prefix it refused.
    refuse_host_identity({path.relative_to(REPO_ROOT).as_posix(): payload
                          for path, payload in outputs.items()})
    _immutable_outputs(outputs, mutable_catalog=catalog_path,
                       replacements=tuple(replacements))
    summary: dict[str, Any] = {
        "schema_version": "ari.native-harness-promotion-summary/v1",
        "source_full_commit_sha": source_commit,
        "container_reference": LOGICAL_CONTAINER,
        "container_digest": container_digest,
        "license_inventory_digest": inventory["inventory_digest"],
        # WHICH SIGNED BUNDLES THIS RUN REPLACED, in the record the run prints.
        # A re-registration is a heavier act than a promotion and the summary
        # should not have to be inferred from the absence of a refusal.
        "re_registered": sorted(item.harness_id for item in replacements),
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
    parser.add_argument("--probe-runs", type=int, default=3,
                        help="how many times the parity probe runs to establish "
                             "stability. Fewer than two cannot show it, and "
                             "gather_evidence refuses.")
    parser.add_argument("--re-register", action="append", default=[],
                        metavar="HARNESS_ID",
                        help="replace this harness's already-promoted bundle "
                             "with the one this run produces. Repeatable, and "
                             "never a default: without it an existing artifact "
                             "whose bytes changed is refused. It costs a fresh "
                             "set of container executions, replacement of that "
                             "harness's WHOLE bundle -- a single artifact on "
                             "disk this run did not produce refuses it -- a "
                             "moved registration evidence digest and hence a "
                             "moved catalog row, and a fresh signature.")
    args = parser.parse_args(argv)
    summary = promote(args)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
