#!/usr/bin/env python3
"""Promote an exact credential-free OpenROAD GCD/Nangate45 SLURM CPU profile."""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PACKAGE_ROOT.parent
for dependency in (
    REPO_ROOT / "ari-core",
    REPO_ROOT / "ari-skill-hpc",
    PACKAGE_ROOT / "src",
    PACKAGE_ROOT / "scripts",
):
    if str(dependency) not in sys.path:
        sys.path.insert(0, str(dependency))

from ari_skill_hpc import (  # noqa: E402
    ArtifactPinV1,
    ContainerRequestV1,
    EnvironmentPolicyV1,
    ResourceRequestV1,
)
from models import AdmissionEvidenceV1, sha256_digest  # noqa: E402
from openroad_adapter import (  # noqa: E402
    OpenRoadExecutionV1,
    OpenRoadExperimentV1,
    OpenRoadProviderPinV1,
    openroad_effective_launcher,
    openroad_provider_release_pin,
    verify_openroad_experiment_files,
    verify_openroad_provider_package,
)
from openroad_promotion import (  # noqa: E402
    OPENROAD_SLURM_GUEST_EXECUTABLE,
    OPENROAD_SLURM_GUEST_EXECUTABLE_DIGEST,
    OPENROAD_SLURM_RUNTIME,
    OPENROAD_SLURM_SCHEDULER_SNAPSHOT,
    OPENROAD_SLURM_VERIFIED_PROFILE_ID,
)
from promote_openroad_gcd_cpu import (  # noqa: E402
    EXPECTED_IMAGE_DIGEST,
    _bundle,
    _copy_inputs,
    _file_digest,
    _git_head,
    _launcher,
    _live_observations,
    _official_orfs_observation,
    _provisional_profile,
    _tests,
    _write_json,
)
from providers import ProviderProtocolError, provider_digest  # noqa: E402
from site_privacy import (  # noqa: E402
    assert_no_private_site_identity,
    assert_repository_site_anonymous,
    load_private_site_config,
    public_site_identity,
)


EXPECTED_MCP_COMMIT = "39d78c091d9f41d217c8c28ddb20fa105942eba5"
# The reviewed PRoot/unsquashfs/worker-Python closure is still an admitted
# substrate — ``openroad_promotion`` verifies it — but this command promotes the
# container substrate, so it pins no host binaries of its own.


def _runtime_pin(path: Path, logical_name: str, media_type: str) -> ArtifactPinV1:
    if path.is_symlink() or not path.is_file():
        raise ProviderProtocolError(f"OpenROAD runtime pin is unavailable: {path}")
    return ArtifactPinV1(
        logical_name=logical_name,
        path=str(path.resolve()),
        digest=_file_digest(path),
        size_bytes=path.stat().st_size,
        media_type=media_type,
    )


def _gpu_authority_limitation() -> str:
    """State why this profile grants no GPU capability at the promoting site.

    The reason is site-dependent: a scheduler without GRES cannot express a GPU
    request at all, whereas a scheduler with GRES could, so the guarantee then
    rests on the allocated node carrying no accelerator.  Read it from the
    reviewed snapshot rather than asserting one site's situation at every site.
    """

    snapshot = json.loads(
        OPENROAD_SLURM_SCHEDULER_SNAPSHOT.read_text(encoding="utf-8")
    )
    if snapshot["cluster"]["gres_types"] is None:
        return (
            "The scheduler declares no GRES types, so no GPU can be requested; "
            "this OpenROAD profile also requests zero GPUs and grants no GPU "
            "capability."
        )
    return (
        "The scheduler declares GRES types, but the allocated node exposes no "
        "accelerator and this OpenROAD profile requests zero GPUs, so it grants "
        "no GPU capability."
    )


def _slurm_profile(
    base: OpenRoadExperimentV1,
    *,
    work_root: Path,
    site: dict[str, str],
) -> OpenRoadExperimentV1:
    image = _runtime_pin(
        OPENROAD_SLURM_RUNTIME / "openroad-orfs-26q3.sif",
        "openroad-sif-image",
        "application/vnd.sylabs.sif",
    )
    if image.digest != EXPECTED_IMAGE_DIGEST:
        raise ProviderProtocolError("OpenROAD execution image identity differs")
    execution = OpenRoadExecutionV1(
        backend="slurm",
        site_identity_digest=sha256_digest(site),
        work_root=str(work_root),
        resources=ResourceRequestV1(
            partition=site["partition"],
            nodes=1,
            tasks=1,
            tasks_per_node=1,
            cpus_per_task=1,
            walltime="00:20:00",
            nodelist=site["node_name"],
            exclusive=True,
        ),
        environment=EnvironmentPolicyV1(
            path="/usr/local/bin:/usr/bin:/bin"
        ),
        # The reviewed PRoot/unsquashfs/worker-Python build links against a
        # newer host glibc than this site provides, so the same profile runs on
        # the digest-pinned clean container instead.  Isolation is stronger:
        # the closure is the SIF rather than the SIF plus four host binaries.
        container=ContainerRequestV1(
            runtime="singularity",
            image=image,
            gpu=False,
            network="none",
            contain_all=True,
            clean_environment=True,
        ),
        terminal_evidence_policy="fixed-wrapper-marker",
    )
    payload = base.model_dump(mode="json")
    payload.update(
        {
            "profile_id": OPENROAD_SLURM_VERIFIED_PROFILE_ID,
            "description": (
                "Digest-pinned GCD Nangate45 post-placement CTS and routing on "
                "an anonymous exclusive-node CPU allocation through the retained ORFS SIF."
            ),
            "toolchain": base.toolchain.model_copy(
                update={
                    "executable_path": OPENROAD_SLURM_GUEST_EXECUTABLE,
                    "executable_digest": OPENROAD_SLURM_GUEST_EXECUTABLE_DIGEST,
                    "execution_image_digest": EXPECTED_IMAGE_DIGEST,
                }
            ).model_dump(mode="json"),
            "execution": execution.model_dump(mode="json"),
            "evidence": AdmissionEvidenceV1(
                protocol_conformance=True,
                provider_pinned=True,
                launcher_verified=True,
                dependencies_pinned=True,
                limitations_documented=True,
                semantics_documented=True,
                units_documented=True,
                method_identity_documented=True,
                architecture=(
                    "anonymous exclusive-node SLURM CPU / PRoot v5.3.1 / ORFS SIF "
                    "adeb389e7 / OpenROAD 7304ba78ad / one CPU thread"
                ),
            ).model_dump(mode="json"),
            "limitations": [
                "The verified identity covers only the fixed GCD placed database, Nangate45 data, anonymous site identity, CPU-only commands, seed, and one-thread execution.",
                _gpu_authority_limitation(),
                "PRoot is a portability mechanism rather than a security boundary; the clean job receives no credentials and retains host-network visibility.",
                "The provider capability executes a routed-artifact contract; its verified status is not a general timing-closure guarantee.",
            ],
            "command_timeout_seconds": 900,
            "poll_interval_seconds": 0.25,
        }
    )
    return OpenRoadExperimentV1.model_validate(payload)


def _verify_scheduler_snapshot(site: dict[str, str]) -> dict[str, Any]:
    snapshot = json.loads(
        OPENROAD_SLURM_SCHEDULER_SNAPSHOT.read_text(encoding="utf-8")
    )
    for identity in snapshot["controller_clients"].values():
        path = Path(identity["path"])
        if (
            path.is_symlink()
            or not path.is_file()
            or path.stat().st_size != identity["size_bytes"]
            or _file_digest(path) != identity["sha256"]
        ):
            raise ProviderProtocolError(f"SLURM client identity drifted: {path}")
    environment = {
        "HOME": "/nonexistent",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": "/usr/local/bin:/usr/bin:/bin",
    }

    def observe(argv: list[str]) -> str:
        result = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
            env=environment,
        )
        if result.returncode:
            raise ProviderProtocolError(f"scheduler identity probe failed: {argv[0]}")
        return result.stdout

    version = observe(["scontrol", "--version"]).strip()
    config = observe(["scontrol", "show", "config"])
    partition = observe(
        ["scontrol", "show", "partition", site["partition"]]
    )
    node = observe(["scontrol", "show", "node", site["node_name"]])
    def _scontrol_value(value: Any) -> str:
        return "(null)" if value is None else str(value)

    cluster = snapshot["cluster"]
    node_snapshot = snapshot["node"]
    partition_snapshot = snapshot["partition"]
    # Site characteristics are compared against the reviewed snapshot instead of
    # literals, so the same promotion can run at another scheduler site.  The
    # snapshot is the single declaration of what this site is; drift between it
    # and the live controller still fails closed.
    declared = (
        (version, f"slurm {cluster['slurm_version']}"),
        (config, f"ClusterName             = {site['cluster_name']}"),
        (
            config,
            "GresTypes               = "
            + _scontrol_value(cluster["gres_types"]),
        ),
        (partition, f"MaxTime={partition_snapshot['max_time']}"),
        (
            node,
            f"NodeName={site['node_name']} Arch={node_snapshot['architecture']}",
        ),
        (node, f"CPUTot={node_snapshot['cpu_cores']}"),
        (node, f"Sockets={node_snapshot['sockets']}"),
        (node, f"ThreadsPerCore={node_snapshot['threads_per_core']}"),
    )
    # These are not site characteristics.  The retained image is x86_64, this
    # profile requests zero GPUs, and the allocation must be exclusive.  A site
    # that cannot honour them is outside this identity whatever it declares.
    invariant = (
        (node, "Arch=x86_64"),
        (node, "Gres=(null)"),
        (partition, "OverSubscribe=EXCLUSIVE"),
    )
    if any(expected not in text for text, expected in declared + invariant):
        raise ProviderProtocolError("anonymous scheduler snapshot differs")
    if node_snapshot.get("gres") is not None or node_snapshot.get("gpu_authority"):
        raise ProviderProtocolError("scheduler snapshot claims GPU authority")
    if snapshot.get("site_identity_digest") != sha256_digest(site):
        raise ProviderProtocolError("scheduler site identity digest differs")
    return {
        "snapshot_digest": _file_digest(OPENROAD_SLURM_SCHEDULER_SNAPSHOT),
        "slurm_version": version,
        **public_site_identity(site, digest=sha256_digest(site)),
        "allocation": "exclusive-node-cpu",
        "gpu_gres": None,
    }


def _attach_fixtures(
    profile: OpenRoadExperimentV1,
    *,
    output: Path,
    observations: dict[str, Any],
) -> OpenRoadExperimentV1:
    golden_path = output / "gcd-nangate45-26q3-slurm-cpu.golden.json"
    replay_path = output / "gcd-nangate45-26q3-slurm-cpu.replay.json"
    _write_json(
        golden_path,
        {
            "schema_version": "ari.openroad-golden/v1",
            "profile_id": profile.profile_id,
            "metrics": [
                {
                    "metric_id": metric.metric_id,
                    "unit": metric.unit,
                    "corner": metric.corner,
                    "mode": metric.mode,
                    "stage": metric.stage,
                    "expected_min": metric.expected_min,
                    "expected_max": metric.expected_max,
                }
                for metric in profile.metrics
            ],
        },
    )
    replay_metrics = [
        {
            key: item[key]
            for key in ("metric_id", "value", "unit", "corner", "mode", "stage")
        }
        for item in observations["result"]["metrics"]
    ]
    _write_json(
        replay_path,
        {
            "schema_version": "ari.openroad-replay-fixture/v1",
            "profile_id": profile.profile_id,
            "experiment_digest": profile.experiment_digest,
            "arguments": {"request_id": "offline-fixture"},
            "result": {
                "status": "completed",
                "experiment_digest": profile.experiment_digest,
                "metrics": replay_metrics,
            },
        },
    )
    golden_digest = _file_digest(golden_path)
    replay_digest = _file_digest(replay_path)
    payload = profile.model_dump(mode="json")
    payload.update(
        {
            "golden_fixture_path": str(golden_path),
            "golden_fixture_digest": golden_digest,
            "replay_fixture_path": str(replay_path),
            "replay_fixture_digest": replay_digest,
            "evidence": profile.evidence.model_copy(
                update={
                    "replay_fixture_digest": replay_digest,
                    "scientific_validation_digest": golden_digest,
                    "notes": [
                        "The actual run requested zero GPUs despite the node inventory.",
                        "The upstream reference disabled CTS timing repair after a pinned-image SIGILL.",
                    ],
                }
            ).model_dump(mode="json"),
        }
    )
    observations["fixtures"] = {
        "golden_digest": golden_digest,
        "replay_digest": replay_digest,
    }
    return OpenRoadExperimentV1.model_validate(payload)


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    output = Path(args.output).resolve()
    if output != OPENROAD_SLURM_RUNTIME.parent.resolve():
        raise ValueError("OpenROAD SLURM output must be its canonical bundle directory")
    output.mkdir(parents=True, exist_ok=True)
    work_root = Path(args.slurm_work_root).resolve(strict=True)
    if work_root.is_symlink() or not work_root.is_dir():
        raise ProviderProtocolError("OpenROAD SLURM work root is unsafe")
    site_path = Path(args.site_config).resolve(strict=True)
    if site_path.is_relative_to(output):
        raise ProviderProtocolError(
            "OpenROAD site configuration must remain outside the tracked bundle"
        )
    site = load_private_site_config(site_path, repository=REPO_ROOT)
    # This scans tracked files and every non-ignored untracked file.  Clear
    # node/cluster identity or the private nonce blocks promotion before a job
    # is submitted; only the salted digest is publishable.
    assert_repository_site_anonymous(REPO_ROOT, site=site)
    execution_image = Path(args.execution_image).resolve(strict=True)
    if (
        execution_image != (OPENROAD_SLURM_RUNTIME / "openroad-orfs-26q3.sif").resolve()
        or _file_digest(execution_image) != EXPECTED_IMAGE_DIGEST
    ):
        raise ProviderProtocolError("materialized SLURM ORFS image differs")
    if _git_head(Path(args.provider_checkout).resolve(strict=True)) != EXPECTED_MCP_COMMIT:
        raise ProviderProtocolError("OpenROAD-MCP checkout commit differs")

    scheduler = _verify_scheduler_snapshot(site)
    # Registration conformance is a cheap admission prerequisite.  Run it
    # before reserving the exclusive scheduler allocation so a missing test
    # runner or local regression cannot consume a scientific execution.
    tests = _tests(args.test_python)
    workspace = _copy_inputs(args, output)
    pin = OpenRoadProviderPinV1.model_validate(openroad_provider_release_pin("0.6.1"))
    launcher = _launcher(args)
    verify_openroad_provider_package(launcher, pin.model_dump(mode="json"))
    profile = _slurm_profile(
        _provisional_profile(workspace), work_root=work_root, site=site
    )
    verify_openroad_experiment_files(profile)
    with tempfile.TemporaryDirectory(prefix="ari-openroad-slurm-promotion-") as artifacts:
        observations = await _live_observations(
            launcher=launcher,
            pin=pin,
            profile=profile,
            artifact_root=Path(artifacts),
        )
    observations["scheduler"] = scheduler
    observations["official_orfs"] = _official_orfs_observation(
        Path(args.orfs_flow_root).resolve(strict=True)
    )
    hpc_job = observations["result"].get("hpc_job")
    if not isinstance(hpc_job, dict):
        raise ProviderProtocolError(
            "OpenROAD exclusive-node typed-job evidence is incomplete"
        )
    state = hpc_job.get("status", {}).get("state")
    if state != "succeeded":
        raise ProviderProtocolError(
            f"OpenROAD exclusive-node typed job did not succeed: {state!r}"
        )
    # The job must record exactly the substrate the profile pinned: the image
    # digest for a container run, and no container at all for the PRoot run.
    container = profile.execution.container
    expected_container_digest = None if container is None else container.image.digest
    if hpc_job.get("container_digest") != expected_container_digest:
        raise ProviderProtocolError(
            "OpenROAD exclusive-node typed job ran on a different execution "
            "substrate than the profile pins"
        )
    # The scheduler handle records where the job ran as absolute paths under the
    # caller's work root.  The scope names are digest-derived and are the part
    # worth publishing; the prefix only says which machine ran the promotion, so
    # express them relative to the work root before the evidence is written.
    handle = hpc_job.get("handle")
    if isinstance(handle, dict):
        root = Path(work_root).resolve()
        for field in ("workspace_scope", "artifact_scope"):
            value = handle.get(field)
            if not isinstance(value, str) or not value:
                continue
            try:
                handle[field] = Path(value).resolve().relative_to(root).as_posix()
            except ValueError as exc:
                raise ProviderProtocolError(
                    f"OpenROAD scheduler {field} escapes the declared work root"
                ) from exc
    profile = _attach_fixtures(profile, output=output, observations=observations)
    verify_openroad_experiment_files(profile)
    result = _bundle(
        output=output,
        captured_date=args.captured_date,
        actor=args.authorized_by,
        pin=pin,
        profile=profile,
        observations=observations,
        tests=tests,
    )
    publishable = (
        OPENROAD_SLURM_SCHEDULER_SNAPSHOT,
        output / "gcd-nangate45-26q3-slurm-cpu.golden.json",
        output / "gcd-nangate45-26q3-slurm-cpu.replay.json",
        output / "provider-manifest-v1.json",
        output / "registration-evidence-v1.json",
        output / "registration-report-v1.json",
        output / "promotion-approval-v1.json",
        output / "verified-lock-v1.json",
    )
    assert_no_private_site_identity(publishable, site=site)
    _write_json(
        output / "materialized" / "materialized-profile-v1.json",
        {
            "schema_version": "ari.openroad-materialized-profile/v1",
            "profile": profile.model_dump(mode="json"),
            "provider_digest": provider_digest(openroad_effective_launcher(launcher)),
            "verified_lock_digest": result["lock_digest"],
        },
    )
    # The materialized profile intentionally retains runtime selectors, so it
    # lives under its own bundle ignore rule rather than in the workspace: the
    # workspace must stay byte-exactly the declared input set for source
    # admission, and this file is not one of those inputs.  This final scan
    # fails if the ignore protection is removed.
    assert_repository_site_anonymous(REPO_ROOT, site=site)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider-python", required=True)
    parser.add_argument("--provider-package-root", required=True)
    parser.add_argument("--provider-checkout", required=True)
    parser.add_argument("--execution-image", required=True)
    parser.add_argument("--placed-odb", required=True)
    parser.add_argument("--placed-sdc", required=True)
    parser.add_argument("--technology-lef", required=True)
    parser.add_argument("--library-lef", required=True)
    parser.add_argument("--liberty", required=True)
    parser.add_argument("--pdk-license", required=True)
    parser.add_argument("--orfs-flow-root", required=True)
    parser.add_argument("--slurm-work-root", required=True)
    parser.add_argument("--site-config", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--authorized-by", required=True)
    parser.add_argument("--captured-date", required=True)
    parser.add_argument("--test-python", default=sys.executable)
    args = parser.parse_args(argv)
    try:
        result = asyncio.run(_run(args))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}))
        return 1
    print(json.dumps({"ok": True, **result}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
