"""Checked-in Qiskit and OpenROAD promotion-lock integrity tests."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from cuda_promotion import CUDA_BUNDLE, cuda_bundle, verify_cuda_verified_lock
from models import sha256_digest
from openroad_adapter import (
    OpenRoadExperimentV1,
    OpenRoadProviderPinV1,
    openroad_provider_release_pin,
)
from openroad_promotion import OPENROAD_WRAPPER, verify_openroad_verified_lock
from openroad_promotion import (
    OPENROAD_VERIFIED_EVIDENCE_SCHEMA,
    OPENROAD_VERIFIED_LOCK_SCHEMA,
    OPENROAD_VERIFIED_MANIFEST_SCHEMA,
    OPENROAD_VERIFIED_PROVIDER_ID,
    OPENROAD_VERIFIED_PROVIDER_VERSION,
)
from provider_promotion import verify_provider_verified_lock
from providers import ProviderProtocolError, PythonStdioLauncherV1
from qiskit_adapter import (
    QiskitExperimentV1,
    QiskitProviderPinV1,
    qiskit_provider_release_pin,
)
from qiskit_promotion import verify_qiskit_verified_lock
from sources import OpenRoadSourceSpecV1, QiskitSourceSpecV1


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
QISKIT_BUNDLE = PACKAGE_ROOT / "providers/qiskit/core-0.3.1+aer-0.17.2-local-ideal"
OPENROAD_BUNDLE = PACKAGE_ROOT / "providers/openroad/0.6.1+orfs-26q3-gcd-nangate45"
OPENROAD_SLURM_BUNDLE = (
    PACKAGE_ROOT
    / "providers/openroad/0.6.1+orfs-26q3-gcd-nangate45-slurm-cpu"
)
OPENROAD_SLURM_LOCK_DIGEST = (
    "sha256:d640dd226c101f9027e11f11c2201afd694b4914c11d7d45b458d142bc2971fd"
)
CUDA_LOCK_DIGEST = (
    "sha256:0d57e5c240cfb8cbf71a1f8ffb675764a8ca8600924fe122a0d7882b578caf7c"
)
PROMOTION_FILES = (
    "provider-manifest-v1.json",
    "registration-evidence-v1.json",
    "registration-report-v1.json",
    "promotion-approval-v1.json",
    "verified-lock-v1.json",
)


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _qiskit_profile() -> tuple[QiskitExperimentV1, str]:
    materialized = _read(QISKIT_BUNDLE / "materialized-profile-v1.json")
    profile = materialized["profile"]
    profile["circuit"]["qpy_path"] = str(QISKIT_BUNDLE / "bell-phi-plus.qpy")
    profile["golden_fixture_path"] = str(QISKIT_BUNDLE / "local-ideal.golden.json")
    profile["replay_fixture_path"] = str(QISKIT_BUNDLE / "local-ideal.replay.json")
    return (
        QiskitExperimentV1.model_validate(profile),
        materialized["verified_lock_digest"],
    )


def _openroad_profile() -> tuple[OpenRoadExperimentV1, str]:
    materialized = _read(OPENROAD_BUNDLE / "materialized-profile-v1.json")
    profile = materialized["profile"]
    profile["toolchain"]["executable_path"] = str(OPENROAD_WRAPPER)
    profile["workspace"]["source_root"] = str(OPENROAD_BUNDLE / "workspace")
    profile["golden_fixture_path"] = str(
        OPENROAD_BUNDLE / "gcd-nangate45-26q3.golden.json"
    )
    profile["replay_fixture_path"] = str(
        OPENROAD_BUNDLE / "gcd-nangate45-26q3.replay.json"
    )
    return (
        OpenRoadExperimentV1.model_validate(profile),
        materialized["verified_lock_digest"],
    )


def _copy_promotion(source: Path, target: Path) -> Path:
    target.mkdir()
    for name in PROMOTION_FILES:
        shutil.copyfile(source / name, target / name)
    return target / "verified-lock-v1.json"


def _verify_public_openroad_slurm_lock(path: Path, *, lock_digest: str):
    document = _read(path)
    return verify_provider_verified_lock(
        path,
        lock_schema=OPENROAD_VERIFIED_LOCK_SCHEMA,
        evidence_schema=OPENROAD_VERIFIED_EVIDENCE_SCHEMA,
        manifest_schema=OPENROAD_VERIFIED_MANIFEST_SCHEMA,
        provider_id=OPENROAD_VERIFIED_PROVIDER_ID,
        provider_version=OPENROAD_VERIFIED_PROVIDER_VERSION,
        expected_lock_digest=lock_digest,
        expected_artifact=document["artifact"],
        expected_scope=document["capability_scope"],
        expected_adapter=document["adapter"],
        expected_runtime_target=document["runtime_target"],
    )


def test_qiskit_local_aer_promotion_lock_is_exact_and_excludes_ibm_runtime():
    profile, lock_digest = _qiskit_profile()
    pin = QiskitProviderPinV1.model_validate(
        qiskit_provider_release_pin("circuit", "0.3.1")
    )
    lock = verify_qiskit_verified_lock(
        QISKIT_BUNDLE / "verified-lock-v1.json",
        expected_lock_digest=lock_digest,
        core_pin=pin,
        experiments=[profile],
    )

    assert lock["status"] == "verified"
    assert lock["lock_digest"] == (
        "sha256:57b60bbdb84ba0364e038a6df51f3de2a48cdf8c776d31066efeec5ea68be195"
    )
    assert lock["capability_scope"]["credential_scope_ids"] == []
    assert [item["profile_id"] for item in lock["capability_scope"]["profiles"]] == [
        "local-ideal"
    ]
    assert "runtime_mcp" not in lock["artifact"]


def test_openroad_cpu_promotion_lock_is_exact_and_excludes_slurm_gpu():
    profile, lock_digest = _openroad_profile()
    pin = OpenRoadProviderPinV1.model_validate(openroad_provider_release_pin("0.6.1"))
    lock = verify_openroad_verified_lock(
        OPENROAD_BUNDLE / "verified-lock-v1.json",
        expected_lock_digest=lock_digest,
        pin=pin,
        experiments=[profile],
    )

    assert lock["status"] == "verified"
    assert lock["lock_digest"] == (
        "sha256:ecd7cc79542acfcfa177186d3bbe154678f1a378454834b6276efb1383eeab28"
    )
    assert lock["capability_scope"]["environment_requirements"] == [
        "cpu",
        "apptainer",
    ]
    assert lock["capability_scope"]["credential_scope_ids"] == []
    assert profile.execution.backend == "local-mcp"
    assert profile.execution.resources is None
    assert profile.execution.container is None


def test_openroad_slurm_cpu_promotion_lock_is_exact_and_site_anonymous():
    path = OPENROAD_SLURM_BUNDLE / "verified-lock-v1.json"
    lock = _verify_public_openroad_slurm_lock(
        path, lock_digest=OPENROAD_SLURM_LOCK_DIGEST
    )
    evidence = _read(OPENROAD_SLURM_BUNDLE / "registration-evidence-v1.json")
    serialized = "\n".join(
        candidate.read_text(encoding="utf-8")
        for candidate in OPENROAD_SLURM_BUNDLE.glob("*.json")
    )

    assert lock["status"] == "verified"
    assert lock["lock_digest"] == OPENROAD_SLURM_LOCK_DIGEST
    assert lock["runtime_target"]["site_identity_digest"].startswith("sha256:")
    assert lock["runtime_target"]["execution_substrate"] == "proot-sif"
    assert lock["capability_scope"]["credential_scope_ids"] == []
    assert lock["capability_scope"]["environment_requirements"] == [
        "cpu",
        "exclusive-node",
        "proot-sif",
        "slurm",
    ]
    assert evidence["observations"]["scheduler"]["identity_disclosure"] == (
        "salted-digest-only"
    )
    assert evidence["observations"]["result"]["hpc_job"]["status"][
        "reason"
    ] == "fixed-wrapper-completion-v1"
    for forbidden_key in ('"node_name"', '"nodelist"', '"cluster_name"', "NodeName="):
        assert forbidden_key not in serialized


GB10_CUDA_BUNDLE = cuda_bundle("13.2", "12.1")
GB10_CUDA_LOCK_DIGEST = (
    "sha256:8a89916cfb10622c7799188c618fcfe7cd290630b729032aac17f5a737153d55"
)


def test_cuda_promotion_lock_is_exact_and_site_anonymous():
    """The bundle promoted on the GPU this site actually has.

    Its device generation is not the V100 one below, which is the point: the
    capability contract no longer names a toolkit release or a compute
    capability, so a second generation can be promoted at all.
    """

    path = GB10_CUDA_BUNDLE / "verified-lock-v1.json"
    lock = verify_cuda_verified_lock(path, expected_lock_digest=GB10_CUDA_LOCK_DIGEST)
    evidence = _read(GB10_CUDA_BUNDLE / "registration-evidence-v1.json")
    serialized = "\n".join(
        candidate.read_text(encoding="utf-8")
        for candidate in GB10_CUDA_BUNDLE.glob("*.json")
    )

    assert lock["status"] == "verified"
    assert lock["lock_digest"] == GB10_CUDA_LOCK_DIGEST
    assert lock["provider_version"] == "1.0.0+cuda13.2-sm121"
    assert lock["capability_scope"]["tool_names"] == [
        "ari_cuda_validate__exclusive_node_sm121"
    ]
    assert lock["runtime_target"]["identity_disclosure"] == "salted-digest-only"
    assert lock["capability_scope"]["credential_scope_ids"] == []
    # From the contract, so this cannot drift away from it unnoticed again.
    assert lock["capability_scope"]["environment_requirements"] == [
        "cuda-toolkit",
        "nvidia-gpu",
        "slurm-controller",
    ]
    # The memory figure nvidia-smi reports as `[N/A]` on this unified-memory
    # device, read from the CUDA API instead. A zero here would mean the
    # promotion had inherited the probe's blind spot.
    assert lock["runtime_target"]["memory_bytes_per_device"] > 0
    validation = evidence["observations"]["cuda_self_test"]
    assert validation["verdict"] == "pass"
    assert validation["device_count"] == lock["runtime_target"]["accelerator_count"]
    assert validation["all_negative_controls_detected"] is True
    assert validation["all_repeats_equal"] is True
    assert validation["maximum_absolute_error"] == 0.0
    for forbidden in (
        '"node_name"',
        '"nodelist"',
        '"cluster_name"',
        "NodeName=",
        "GPU-",
        "MIG-",
    ):
        assert forbidden not in serialized


def test_the_v100_cuda_bundle_is_retained_evidence_that_no_longer_verifies():
    """Says out loud what the older bundle now is, rather than deleting it.

    It records a real promotion on real Tesla V100 hardware, so it is kept. It
    also predates two corrections it cannot be given retroactively: its scope
    names `exclusive-node` and `slurm`, both retired from the contract, and its
    capability_contract_digest was built locally and was never the ontology's.
    Repairing either requires promoting it again on a V100-class node, which
    this site has none of.

    This asserts the refusal so the state stays visible. It fails the moment
    someone re-promotes that bundle -- which is the correct time to revisit it.
    """

    path = CUDA_BUNDLE / "verified-lock-v1.json"
    lock = _read(path)
    assert lock["provider_version"] == "1.0.0+cuda12.9-sm70"
    assert lock["runtime_target"]["compute_capability"] == "7.0"
    assert lock["capability_scope"]["environment_requirements"] == [
        "cuda-12.9",
        "exclusive-node",
        "nvidia-sm70",
        "slurm",
    ]
    with pytest.raises(ProviderProtocolError):
        verify_cuda_verified_lock(path, expected_lock_digest=CUDA_LOCK_DIGEST)


def test_openroad_slurm_nonhuman_approval_is_rejected(tmp_path: Path):
    copied_lock = _copy_promotion(OPENROAD_SLURM_BUNDLE, tmp_path / "openroad-slurm")
    approval_path = copied_lock.parent / "promotion-approval-v1.json"
    approval = _read(approval_path)
    approval["actor_kind"] = "llm"
    approval["approval_digest"] = sha256_digest(
        {key: value for key, value in approval.items() if key != "approval_digest"}
    )
    _write(approval_path, approval)
    document = _read(copied_lock)
    document["promotion"]["approval_digest"] = approval["approval_digest"]
    document["lock_digest"] = sha256_digest(
        {key: value for key, value in document.items() if key != "lock_digest"}
    )
    _write(copied_lock, document)

    with pytest.raises(ProviderProtocolError, match="formal Provider promotion"):
        _verify_public_openroad_slurm_lock(
            copied_lock, lock_digest=document["lock_digest"]
        )


def test_qiskit_verified_lock_marks_only_the_exact_source_snapshot_verified():
    profile, lock_digest = _qiskit_profile()
    source = QiskitSourceSpecV1(
        source_id="qiskit.local-ideal.verified",
        core_provider_digest="sha256:" + "0" * 64,
        core_launcher=PythonStdioLauncherV1(
            python_executable="/not-materialized/bin/python",
            package_root="/not-materialized/qiskit_mcp_server",
            python_module="qiskit_mcp_server",
            python_callable="main",
            expected_architecture="x86_64",
            identity_globs=[
                "**/*",
                "**/*.py",
                "*.lock",
                "pyproject.toml",
                "requirements*.txt",
            ],
        ),
        verified_lock_path=str(QISKIT_BUNDLE / "verified-lock-v1.json"),
        verified_lock_digest=lock_digest,
        experiments=[profile],
    )

    locked = source.to_locked_source(verify=False)

    assert locked.runtime["provider_status"] == "verified"
    assert locked.runtime["verified_lock_digest"] == lock_digest
    assert locked.runtime["runtime_launcher"] is None


def test_openroad_verified_lock_marks_only_the_exact_source_snapshot_verified():
    profile, lock_digest = _openroad_profile()
    source = OpenRoadSourceSpecV1(
        source_id="openroad.gcd-nangate45.verified",
        provider_digest="sha256:" + "0" * 64,
        launcher=PythonStdioLauncherV1(
            python_executable="/not-materialized/bin/python",
            package_root="/not-materialized/openroad_mcp",
            python_module="openroad_mcp.main",
            python_callable="main",
            expected_architecture="x86_64",
            identity_globs=[
                "**/*",
                "**/*.py",
                "*.lock",
                "pyproject.toml",
                "requirements*.txt",
            ],
        ),
        verified_lock_path=str(OPENROAD_BUNDLE / "verified-lock-v1.json"),
        verified_lock_digest=lock_digest,
        experiments=[profile],
    )

    locked = source.to_locked_source(verify=False)

    assert locked.runtime["provider_status"] == "verified"
    assert locked.runtime["verified_lock_digest"] == lock_digest
    assert locked.runtime["experiments"][0]["execution"]["backend"] == "local-mcp"


def test_recomputed_qiskit_scope_tamper_is_rejected(tmp_path: Path):
    profile, lock_digest = _qiskit_profile()
    pin = QiskitProviderPinV1.model_validate(
        qiskit_provider_release_pin("circuit", "0.3.1")
    )
    copied_lock = _copy_promotion(QISKIT_BUNDLE, tmp_path / "qiskit")
    document = _read(copied_lock)
    document["capability_scope"]["profiles"][0]["capability_ref"] = (
        "ari.quantum.sample.ibm-hardware/v1"
    )
    document["lock_digest"] = sha256_digest(
        {key: value for key, value in document.items() if key != "lock_digest"}
    )
    _write(copied_lock, document)

    with pytest.raises(ProviderProtocolError, match="identity or scope"):
        verify_qiskit_verified_lock(
            copied_lock,
            expected_lock_digest=document["lock_digest"],
            core_pin=pin,
            experiments=[profile],
        )
    assert lock_digest != document["lock_digest"]


def test_recomputed_openroad_nonhuman_approval_is_rejected(tmp_path: Path):
    profile, _lock_digest = _openroad_profile()
    pin = OpenRoadProviderPinV1.model_validate(openroad_provider_release_pin("0.6.1"))
    copied_lock = _copy_promotion(OPENROAD_BUNDLE, tmp_path / "openroad")
    approval_path = copied_lock.parent / "promotion-approval-v1.json"
    approval = _read(approval_path)
    approval["actor_kind"] = "llm"
    approval["approval_digest"] = sha256_digest(
        {key: value for key, value in approval.items() if key != "approval_digest"}
    )
    _write(approval_path, approval)
    document = _read(copied_lock)
    document["promotion"]["approval_digest"] = approval["approval_digest"]
    document["lock_digest"] = sha256_digest(
        {key: value for key, value in document.items() if key != "lock_digest"}
    )
    _write(copied_lock, document)

    with pytest.raises(ProviderProtocolError, match="formal Provider promotion"):
        verify_openroad_verified_lock(
            copied_lock,
            expected_lock_digest=document["lock_digest"],
            pin=pin,
            experiments=[profile],
        )
