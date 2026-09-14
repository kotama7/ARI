"""Exact verified-scope projection for the OpenROAD/ORFS GCD Provider."""

from __future__ import annotations

from pathlib import Path
import json
from typing import Any, Iterable

import provider_promotion
from capability_pins import capability_contract_digest
from models import sha256_digest
from openroad_adapter import (
    OPENROAD_ADAPTER_ID,
    OPENROAD_ADAPTER_VERSION,
    OpenRoadExperimentV1,
    openroad_adapter_digest,
    openroad_virtual_tool,
)
from openroad_identity import (
    OpenRoadProviderPinV1,
    _file_sha256,
    openroad_execution_image,
    openroad_toolchain_line,
)
from provider_promotion import verify_provider_verified_lock
from providers import ProviderProtocolError


OPENROAD_CAPABILITY_REF = "ari.eda.openroad.place-route/v1"
OPENROAD_VERIFIED_PROVIDER_ID = "openroad-mcp"
OPENROAD_VERIFIED_PROVIDER_VERSION = "0.6.1"
OPENROAD_VERIFIED_PROFILE_ID = "gcd-nangate45-26q3"
OPENROAD_SLURM_VERIFIED_PROFILE_ID = "gcd-nangate45-26q3-slurm-cpu"
OPENROAD_VERIFIED_LOCK_SCHEMA = "ari.openroad-verified-lock/v1"
OPENROAD_VERIFIED_EVIDENCE_SCHEMA = "ari.openroad-registration-evidence/v1"
OPENROAD_VERIFIED_MANIFEST_SCHEMA = "ari.openroad-capability-provider-manifest/v1"
OPENROAD_IMAGE_ID = "orfs-26q3-openroad-7304ba78"
_BUNDLE_ROOT = (
    Path(__file__).resolve().parent.parent
    / "providers"
    / "openroad"
    / "0.6.1+orfs-26q3-gcd-nangate45"
)
_SLURM_BUNDLE_ROOT = (
    Path(__file__).resolve().parent.parent
    / "providers"
    / "openroad"
    / "0.6.1+orfs-26q3-gcd-nangate45-slurm-cpu"
)
OPENROAD_WRAPPER = _BUNDLE_ROOT / "runtime" / "openroad"
OPENROAD_SLURM_RUNTIME = _SLURM_BUNDLE_ROOT / "runtime"
OPENROAD_SLURM_SCHEDULER_SNAPSHOT = (
    _SLURM_BUNDLE_ROOT / "scheduler-snapshot-v1.json"
)
OPENROAD_SLURM_GUEST_EXECUTABLE = (
    "/OpenROAD-flow-scripts/tools/install/OpenROAD/bin/openroad"
)
OPENROAD_SLURM_GUEST_EXECUTABLE_DIGEST = (
    "sha256:e69cc5011dc319a46c2f677b94ec7f7abab28f3f136e788071e5125c89daf1d9"
)


def _scheduler_snapshot() -> dict[str, Any]:
    try:
        value = json.loads(
            OPENROAD_SLURM_SCHEDULER_SNAPSHOT.read_text(encoding="utf-8")
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderProtocolError("OpenROAD scheduler snapshot is invalid") from exc
    if (
        not isinstance(value, dict)
        or value.get("schema_version")
        != "ari.openroad-scheduler-snapshot/v1"
    ):
        raise ProviderProtocolError("OpenROAD scheduler snapshot has the wrong shape")
    return value


def _one_profile(
    experiments: Iterable[OpenRoadExperimentV1] | None,
) -> OpenRoadExperimentV1 | None:
    if experiments is None:
        return None
    profiles = list(experiments)
    if len(profiles) != 1:
        raise ProviderProtocolError("OpenROAD verified identity admits one profile")
    return profiles[0]


def openroad_verified_artifact(
    pin: OpenRoadProviderPinV1,
    experiments: Iterable[OpenRoadExperimentV1] | None = None,
) -> dict[str, Any]:
    profile = _one_profile(experiments)
    if profile is not None and profile.profile_id == OPENROAD_SLURM_VERIFIED_PROFILE_ID:
        if not OPENROAD_SLURM_SCHEDULER_SNAPSHOT.is_file():
            raise ProviderProtocolError("OpenROAD scheduler snapshot is missing")
        container = profile.execution.container
        if container is not None:
            # A site whose host glibc cannot run the reviewed PRoot/unsquashfs/
            # worker-Python build uses the digest-pinned clean container instead.
            # Both substrates are admitted by the execution contract; only one
            # may be present, and each pins its own closure.
            expected_image = OPENROAD_SLURM_RUNTIME / "openroad-orfs-26q3.sif"
            if (
                Path(container.image.path).resolve() != expected_image.resolve()
                or _file_sha256(expected_image) != container.image.digest
            ):
                raise ProviderProtocolError(
                    "OpenROAD SLURM execution image is outside its canonical bundle"
                )
            return {
                "openroad_mcp": pin.model_dump(mode="json"),
                "toolchain_line": openroad_toolchain_line("orfs-26q3"),
                "execution_image": openroad_execution_image(OPENROAD_IMAGE_ID),
                "container_runtime": {
                    "runtime": container.runtime,
                    "image_digest": container.image.digest,
                    "image_size_bytes": container.image.size_bytes,
                    "network": container.network,
                    "contain_all": container.contain_all,
                    "clean_environment": container.clean_environment,
                    "gpu": container.gpu,
                },
                "scheduler_snapshot_digest": _file_sha256(
                    OPENROAD_SLURM_SCHEDULER_SNAPSHOT
                ),
            }
        portable = profile.execution.portable_runtime
        if portable is None:
            raise ProviderProtocolError("OpenROAD SLURM verified runtime is missing")
        for pin_value, expected_path in (
            (portable.proot, OPENROAD_SLURM_RUNTIME / "proot"),
            (portable.image, OPENROAD_SLURM_RUNTIME / "openroad-orfs-26q3.sif"),
            (portable.unsquashfs, OPENROAD_SLURM_RUNTIME / "unsquashfs"),
        ):
            if Path(pin_value.path).resolve() != expected_path.resolve():
                raise ProviderProtocolError(
                    "OpenROAD SLURM runtime is outside its canonical bundle"
                )
            if _file_sha256(expected_path) != pin_value.digest:
                raise ProviderProtocolError("OpenROAD SLURM runtime digest drifted")
        worker_python = profile.execution.worker_python_pin
        if (
            worker_python is None
            or Path(worker_python.path).resolve()
            != (OPENROAD_SLURM_RUNTIME / "python3.12").resolve()
            or _file_sha256(Path(worker_python.path)) != worker_python.digest
        ):
            raise ProviderProtocolError("OpenROAD SLURM worker Python drifted")
        license_path = OPENROAD_SLURM_RUNTIME / "PROOT-COPYING"
        return {
            "openroad_mcp": pin.model_dump(mode="json"),
            "toolchain_line": openroad_toolchain_line("orfs-26q3"),
            "execution_image": openroad_execution_image(OPENROAD_IMAGE_ID),
            "portable_runtime": {
                "kind": portable.kind,
                "squashfs_offset": portable.squashfs_offset,
                "network_policy": portable.network_policy,
                "proot_digest": portable.proot.digest,
                "proot_size_bytes": portable.proot.size_bytes,
                "proot_source_repository": "https://gitlab.com/proot/proot.git",
                "proot_source_commit": "99a8417521645c6d0b6d2b64a504bf27fea5d4da",
                "proot_release": "v5.3.1",
                "proot_license_digest": _file_sha256(license_path),
                "image_digest": portable.image.digest,
                "image_size_bytes": portable.image.size_bytes,
                "unsquashfs_digest": portable.unsquashfs.digest,
                "unsquashfs_size_bytes": portable.unsquashfs.size_bytes,
                "unsquashfs_version": "4.6.1",
                "worker_python_digest": worker_python.digest,
                "worker_python_size_bytes": worker_python.size_bytes,
            },
            "scheduler_snapshot_digest": _file_sha256(
                OPENROAD_SLURM_SCHEDULER_SNAPSHOT
            ),
        }
    if OPENROAD_WRAPPER.is_symlink() or not OPENROAD_WRAPPER.is_file():
        raise ProviderProtocolError("OpenROAD verified wrapper is missing")
    return {
        "openroad_mcp": pin.model_dump(mode="json"),
        "toolchain_line": openroad_toolchain_line("orfs-26q3"),
        "execution_image": openroad_execution_image(OPENROAD_IMAGE_ID),
        "wrapper_digest": _file_sha256(OPENROAD_WRAPPER),
    }


def openroad_verified_scope(
    experiments: Iterable[OpenRoadExperimentV1],
) -> dict[str, Any]:
    profiles = list(experiments)
    if len(profiles) != 1 or profiles[0].profile_id not in {
        OPENROAD_VERIFIED_PROFILE_ID,
        OPENROAD_SLURM_VERIFIED_PROFILE_ID,
    }:
        raise ProviderProtocolError(
            "OpenROAD verified identity admits one exact GCD Nangate45 26Q3 profile"
        )
    profile = profiles[0]
    image = openroad_execution_image(OPENROAD_IMAGE_ID)
    slurm = profile.profile_id == OPENROAD_SLURM_VERIFIED_PROFILE_ID
    if not slurm:
        if profile.execution.backend != "local-mcp":
            raise ProviderProtocolError("OpenROAD local verified profile is CPU-only")
        if (
            profile.toolchain.execution_image_digest != image["retained_sif_digest"]
            or profile.toolchain.executable_digest != _file_sha256(OPENROAD_WRAPPER)
            or Path(profile.toolchain.executable_path).resolve()
            != OPENROAD_WRAPPER.resolve()
        ):
            raise ProviderProtocolError(
                "OpenROAD wrapper or execution image identity differs"
            )
    else:
        execution = profile.execution
        resources = execution.resources
        # Exactly one pinned execution substrate, either the reviewed PRoot/SIF
        # portable runtime or the digest-pinned clean container.  Which one is a
        # site property; that there is exactly one is the invariant.
        substrates = (execution.portable_runtime, execution.container)
        if (
            execution.backend != "slurm"
            or resources is None
            or sum(item is not None for item in substrates) != 1
            or not resources.partition
            or not resources.nodelist
            or not resources.exclusive
            or resources.nodes != 1
            or resources.tasks != 1
            or resources.cpus_per_task != 1
            or resources.gpus_per_node != 0
            or resources.gpus_per_task != 0
            or execution.terminal_evidence_policy != "fixed-wrapper-marker"
            or execution.site_identity_digest
            != _scheduler_snapshot().get("site_identity_digest")
            or profile.toolchain.execution_image_digest
            != image["retained_sif_digest"]
            or profile.toolchain.executable_path
            != OPENROAD_SLURM_GUEST_EXECUTABLE
            or profile.toolchain.executable_digest
            != OPENROAD_SLURM_GUEST_EXECUTABLE_DIGEST
        ):
            raise ProviderProtocolError(
                "OpenROAD SLURM profile differs from the fixed anonymous CPU scope"
            )
    tool = openroad_virtual_tool(
        profile,
        provider_version="0.6.1",
        provider_commit=profile.toolchain.openroad_commit,
    )
    scope = {
        "profiles": [
            {
                "profile_id": profile.profile_id,
                "leaf_name": tool.name,
                "capability_ref": OPENROAD_CAPABILITY_REF,
                "capability_contract_digest": capability_contract_digest(
                    OPENROAD_CAPABILITY_REF
                ),
                "experiment_digest": profile.experiment_digest,
                "method_digest": profile.method_digest,
                "workspace_input_digest": profile.workspace.input_digest,
                "pdk_digest": profile.technology.pdk_digest,
                "library_digest": profile.technology.standard_cell_library_digest,
                "golden_fixture_digest": profile.golden_fixture_digest,
                "replay_fixture_digest": profile.replay_fixture_digest,
                "input_schema_digest": sha256_digest(tool.input_schema),
                "output_schema_digest": sha256_digest(tool.output_schema),
                "output_contract_digest": sha256_digest(
                    [item.model_dump(mode="json") for item in profile.output_artifacts]
                ),
            }
        ],
        "side_effects": "workspace-write",
        "determinism": "seeded",
        "permissions": ["process", "workspace-read", "workspace-write"],
        "credential_scope_ids": [],
        "environment_requirements": ["cpu", "apptainer"],
        "resource_type": "eda-cpu",
    }
    if slurm:
        scope.update(
            {
                "permissions": [
                    "process",
                    "scheduler-submit",
                    "workspace-read",
                    "workspace-write",
                ],
                # The substrate a site requires is the one its profile pins, so
                # a container run must not advertise a PRoot requirement.
                "environment_requirements": sorted(
                    {
                        "cpu",
                        "exclusive-node",
                        "slurm",
                        (
                            f"{profile.execution.container.runtime}-sif"
                            if profile.execution.container is not None
                            else "proot-sif"
                        ),
                    }
                ),
                "resource_type": "eda-cpu-slurm",
            }
        )
    return scope


def openroad_verified_adapter() -> dict[str, str]:
    return {
        "adapter_id": OPENROAD_ADAPTER_ID,
        "adapter_version": OPENROAD_ADAPTER_VERSION,
        "adapter_digest": openroad_adapter_digest(),
        "promotion_verifier_digest": sha256_digest(
            {
                "openroad": _file_sha256(Path(__file__).resolve()),
                "shared": _file_sha256(Path(provider_promotion.__file__).resolve()),
            }
        ),
    }


def openroad_verified_runtime_target(
    experiments: Iterable[OpenRoadExperimentV1] | None = None,
) -> dict[str, str]:
    profile = _one_profile(experiments)
    if profile is not None and profile.profile_id == OPENROAD_SLURM_VERIFIED_PROFILE_ID:
        container = profile.execution.container
        return {
            "architecture": "x86_64",
            "operating_system": "linux",
            "provider_python": "CPython-3.13",
            # The worker interpreter and the isolation boundary follow the
            # substrate this profile actually declares, not one site's choice.
            "worker_python": (
                "container-provided" if container is not None else "CPython-3.12"
            ),
            "execution_substrate": (
                f"{container.runtime}-sif" if container is not None else "proot-sif"
            ),
            "network": (
                "isolated"
                if container is not None and container.network == "none"
                else "host-uncredentialed"
            ),
            "site_identity_digest": str(
                _scheduler_snapshot()["site_identity_digest"]
            ),
            "scheduler_snapshot_digest": _file_sha256(
                OPENROAD_SLURM_SCHEDULER_SNAPSHOT
            ),
        }
    return {
        "architecture": "x86_64",
        "operating_system": "linux",
        "python_implementation": "CPython",
        "python_minor": "3.13",
        "container_runtime": "apptainer-1.5.0-rc.1",
        "network": "none",
    }


def verify_openroad_verified_lock(
    path: str | Path,
    *,
    expected_lock_digest: str,
    pin: OpenRoadProviderPinV1,
    experiments: Iterable[OpenRoadExperimentV1],
) -> dict[str, Any]:
    profiles = list(experiments)
    return verify_provider_verified_lock(
        path,
        lock_schema=OPENROAD_VERIFIED_LOCK_SCHEMA,
        evidence_schema=OPENROAD_VERIFIED_EVIDENCE_SCHEMA,
        manifest_schema=OPENROAD_VERIFIED_MANIFEST_SCHEMA,
        provider_id=OPENROAD_VERIFIED_PROVIDER_ID,
        provider_version=OPENROAD_VERIFIED_PROVIDER_VERSION,
        expected_lock_digest=expected_lock_digest,
        expected_artifact=openroad_verified_artifact(pin, profiles),
        expected_scope=openroad_verified_scope(profiles),
        expected_adapter=openroad_verified_adapter(),
        expected_runtime_target=openroad_verified_runtime_target(profiles),
    )


__all__ = [
    "OPENROAD_IMAGE_ID",
    "OPENROAD_VERIFIED_EVIDENCE_SCHEMA",
    "OPENROAD_VERIFIED_LOCK_SCHEMA",
    "OPENROAD_VERIFIED_MANIFEST_SCHEMA",
    "OPENROAD_VERIFIED_PROFILE_ID",
    "OPENROAD_SLURM_VERIFIED_PROFILE_ID",
    "OPENROAD_VERIFIED_PROVIDER_ID",
    "OPENROAD_VERIFIED_PROVIDER_VERSION",
    "OPENROAD_WRAPPER",
    "OPENROAD_SLURM_GUEST_EXECUTABLE",
    "OPENROAD_SLURM_GUEST_EXECUTABLE_DIGEST",
    "OPENROAD_SLURM_RUNTIME",
    "OPENROAD_SLURM_SCHEDULER_SNAPSHOT",
    "openroad_verified_adapter",
    "openroad_verified_artifact",
    "openroad_verified_runtime_target",
    "openroad_verified_scope",
    "verify_openroad_verified_lock",
]
