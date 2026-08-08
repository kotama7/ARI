"""The container the verifiers run in, exercised rather than described.

WHAT WAS MISSING. No test in this repository ever constructed
``PinnedContainerExecutor``. The whole containerised path -- the thing that makes
a ``verified`` catalog row mean the candidate was judged in a pinned, network-
denied environment rather than on the host -- had no coverage at all, and it was
dead for TWO independent reasons while the entire suite passed:

  * the pin named the ``apptainer`` runtime, which is installed on no node here,
    so the executor refused before it ever looked at the image; and
  * the memory requirement was smaller than the container runtime's own address
    space, so the launcher aborted in ``pthread_create`` and the verifier never
    started.

Both surfaced only as ``infrastructure_error`` with no reason attached, and only
when the end-to-end publication chain was actually run. A green suite said
nothing about either.

Both are fixed at the mechanism rather than in the numbers: the verifier is held
to the manifest's bound INSIDE the container and the launcher is given its own
allowance, so one number no longer sizes two different things.

WHAT THE GATING RULE IS. The pinned image is a site artifact and is not in this
repository, so a machine without it cannot run the launch test -- that is a
legitimately absent artifact, not a defect, and it skips. But a machine that HAS
the image is a machine set up to verify, and there the pinned runtime must exist,
the image must be bound to the content the manifests name, and a candidate must
come back judged. Those do not skip: skipping them is what let the two failures
above live.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from ari.assurance.container_identity import (
    RUNTIME_WRITTEN_METADATA,
    read_binding,
    write_binding,
)
from ari.assurance.executors import (
    CONTAINER_LAUNCHER_ADDRESS_SPACE,
    HarnessSubstrateError,
    PinnedContainerExecutor,
)
from ari.assurance.models import HarnessManifestV1
from ari.execution import ContainerIdentityV1, ExecutionRequestV1, WorkspaceRefV1


CORE = Path(__file__).resolve().parents[1]
REPOSITORY = CORE.parent
BUILTIN = CORE / "config" / "harnesses" / "builtin"
CANDIDATE_SOURCE = CORE / "tests" / "fixtures" / "assurance" / "native_reference_candidate.c"

#: Runtimes the executor knows how to launch, by reference prefix.
LAUNCHABLE_RUNTIMES = ("singularity", "apptainer", "docker")


def _manifests() -> list[HarnessManifestV1]:
    return [HarnessManifestV1.model_validate(yaml.safe_load(path.read_text()))
            for path in sorted(BUILTIN.glob("hpc_*.yaml"))]


def _containerised() -> list[HarnessManifestV1]:
    """The manifests whose verdict comes from a run inside the pinned image.

    The performance harness pins the same image for provenance but measures
    through its own driver, which never builds a container request, so its
    bound is about its own process and is not compared here.
    """
    return [m for m in _manifests() if m.kind == "artifact_verifier"]


def _container_root() -> Path:
    configured = os.environ.get("ARI_HARNESS_CONTAINER_ROOT", "").strip()
    return Path(configured) if configured else REPOSITORY / "containers"


def _pinned_image(manifest: HarnessManifestV1) -> Path | None:
    reference = manifest.container.reference
    if ":" not in reference:
        return None
    name = reference.split(":", 1)[1]
    image = _container_root() / name
    return image if image.is_file() and not image.is_symlink() else None


def _request(*, memory_bytes: int, workspace_root: str,
             reference: str = "singularity:image.sif",
             digest: str | None = None) -> ExecutionRequestV1:
    return ExecutionRequestV1(
        workspace=WorkspaceRefV1(root=workspace_root),
        argv=["/usr/bin/python3", "-m", "ari.assurance.drivers.native_worker",
              "--kind", "gemm", "--library", "candidate.so", "--tier", "screen",
              "--seed", "1"],
        limits={"memory_bytes": memory_bytes},
        network="deny",
        container=ContainerIdentityV1(
            runtime=reference.split(":", 1)[0], reference=reference,
            digest=digest or ("sha256:" + "a" * 64), resolution_status="resolved"),
    )


# --- what holds on every machine ----------------------------------------------

def test_the_launcher_is_given_its_own_allowance_and_the_verifier_the_manifest_s(tmp_path):
    """The bound the manifest names must reach the VERIFIER, not the runtime.

    One number used to bound both, because RLIMIT_AS is set on the process the
    executor exec's -- which for a containerised harness is the container
    runtime -- and inherited by what it starts. The launcher's appetite then
    decided the verifier's bound, and at the 4 GiB a verifier was given the
    launcher could not start at all.
    """
    executor = PinnedContainerExecutor(package_root=CORE)
    request = _request(memory_bytes=4 * 1024**3, workspace_root=str(tmp_path))
    inside = executor._inside_argv(request, {})
    assert inside[:2] == ["prlimit", f"--as={4 * 1024**3}"], (
        "the verifier is not held to the manifest's bound inside the container")
    assert "native_worker" in " ".join(inside), "the command itself was lost"

    outer = executor._launcher_limits(request.limits)
    assert outer.memory_bytes == 4 * 1024**3 + CONTAINER_LAUNCHER_ADDRESS_SPACE, (
        "the launcher is not given an allowance of its own, so the manifest's "
        "number is still bounding two different things")


def test_the_launcher_allowance_is_above_where_the_requirement_stopped_varying():
    """It is not a fixed number: measured eight launches per bound with nothing
    inside the container, 4 GiB never started, 5 GiB started 3 times in 8, and 6
    and 8 GiB started every time. A tight allowance buys nothing and costs
    intermittent infrastructure failures."""
    assert CONTAINER_LAUNCHER_ADDRESS_SPACE >= 6 * 1024**3


def test_every_container_reference_names_a_runtime_the_executor_can_launch():
    """The prefix is not decoration: it selects the binary that gets exec'd."""
    for manifest in _manifests():
        runtime = manifest.container.reference.split(":", 1)[0]
        assert runtime in LAUNCHABLE_RUNTIMES, (
            f"{manifest.id} names runtime {runtime!r}, which the executor has no "
            f"branch for")


# --- the pin is on the content, so re-obtaining an image is not a re-registration


def test_an_unbound_image_is_refused_rather_than_waved_through(tmp_path):
    """Nobody has established what is inside it, so nothing may run in it."""
    image = tmp_path / "image.sif"
    image.write_bytes(b"not really a SIF")
    from ari.assurance import executors

    with pytest.raises(HarnessSubstrateError, match="no site binding"):
        executors._require_pinned_content(image, "sha256:" + "b" * 64)


def test_an_image_bound_to_other_content_is_refused(tmp_path):
    image = tmp_path / "image.sif"
    image.write_bytes(b"not really a SIF")
    write_binding(tmp_path, image=image, content_digest="sha256:" + "c" * 64,
                  entry_count=3)
    from ari.assurance import executors

    with pytest.raises(HarnessSubstrateError, match="not the content"):
        executors._require_pinned_content(image, "sha256:" + "b" * 64)


def test_an_image_that_changed_since_it_was_bound_is_refused(tmp_path):
    """The binding vouches for a file, so the file has to still be that file."""
    image = tmp_path / "image.sif"
    image.write_bytes(b"not really a SIF")
    content = "sha256:" + "c" * 64
    write_binding(tmp_path, image=image, content_digest=content, entry_count=3)
    image.write_bytes(b"something else entirely")
    from ari.assurance import executors

    with pytest.raises(HarnessSubstrateError, match="has changed since"):
        executors._require_pinned_content(image, content)


def test_a_correctly_bound_image_is_accepted(tmp_path):
    image = tmp_path / "image.sif"
    image.write_bytes(b"not really a SIF")
    content = "sha256:" + "c" * 64
    write_binding(tmp_path, image=image, content_digest=content, entry_count=3)
    from ari.assurance import executors

    executors._require_pinned_content(image, content)


def test_the_pinned_image_is_bound_to_the_content_its_manifests_name():
    """MEASURED, and the reason the pin is on content at all: two independent
    pulls of one tag gave different files -- b8af5db8 and 1a25c102 -- and the
    same content, 109,596 entries agreeing on every one. Only the runtime's own
    build-date metadata differed, and it is excluded by name."""
    for manifest in _containerised():
        image = _pinned_image(manifest)
        if image is None:
            pytest.skip("the pinned Harness image is not on this machine")
        binding = read_binding(image.parent, image.name)
        assert binding is not None, (
            f"{image.name} is present but nothing records what is inside it")
        assert binding["content_digest"] == manifest.container.resolved_digest, (
            f"{manifest.id} pins content the local image does not carry")
        assert binding["excluded_paths"] == list(RUNTIME_WRITTEN_METADATA)


# --- what holds where the pinned image actually is ----------------------------

def test_the_pinned_runtime_exists_where_the_pinned_image_does():
    """THE FIRST OF THE TWO FAILURES, as a test.

    Skipping this when the runtime is missing would restate the bug: the pin
    named apptainer, apptainer was installed nowhere, and every verification
    returned infrastructure_error. The image being present is what says this
    machine is meant to verify.
    """
    for manifest in _containerised():
        if _pinned_image(manifest) is None:
            pytest.skip("the pinned Harness image is not on this machine")
        runtime = manifest.container.reference.split(":", 1)[0]
        assert shutil.which(runtime) is not None, (
            f"{manifest.id} pins the {runtime} runtime and the image for it is "
            f"present, but no {runtime} executable is on PATH; every run through "
            f"it is refused before the image is read")


def test_a_candidate_is_actually_judged_inside_the_pinned_image():
    """THE SECOND FAILURE, and the coverage that was missing entirely.

    Compiles the reference candidate, hands it to the real executor with the
    manifest's own container pin and its own limits, and requires a verdict
    back. This is the only test that proves the pinned image, the pinned
    runtime, the address-space bound, the read-only package mount and the denied
    network compose into something that can judge an artifact.
    """
    manifest = next(m for m in _containerised() if m.id == "hpc/gemm-correctness")
    image = _pinned_image(manifest)
    if image is None:
        pytest.skip("the pinned Harness image is not on this machine")
    compiler = shutil.which("cc")
    if compiler is None:
        pytest.skip("a C compiler is required to build the candidate")

    import tempfile

    with tempfile.TemporaryDirectory(prefix="ari-container-path-") as temporary:
        workspace_root = Path(temporary)
        library = workspace_root / "candidate.so"
        build = subprocess.run(
            [compiler, "-std=c11", "-O2", "-fPIC", "-shared",
             "-DARI_PROBE_ORACLE_ACCESS", str(CANDIDATE_SOURCE), "-o", str(library),
             "-lm"],
            capture_output=True, text=True, timeout=300)
        assert build.returncode == 0, build.stderr[-2000:]

        workspace = WorkspaceRefV1(root=str(workspace_root))
        request = ExecutionRequestV1(
            workspace=workspace,
            argv=["python3", "-m", "ari.assurance.drivers.native_worker",
                  "--kind", "gemm", "--library", "candidate.so",
                  "--tier", "screen", "--seed", "20260808"],
            timeout_seconds=float(manifest.timeout_seconds),
            limits={"cpu_seconds": manifest.timeout_seconds,
                    "memory_bytes": manifest.resources.memory_bytes,
                    "max_output_bytes": 256 * 1024 * 1024},
            network="deny",
            request_id="container-path-test",
            input_digests={"candidate.so": workspace.file_digest("candidate.so")},
            container=ContainerIdentityV1(
                runtime=manifest.container.reference.split(":", 1)[0],
                reference=manifest.container.reference,
                digest=manifest.container.resolved_digest,
                resolution_status="resolved"),
        )
        previous = os.environ.get("ARI_HARNESS_CONTAINER_ROOT")
        os.environ["ARI_HARNESS_CONTAINER_ROOT"] = str(_container_root().resolve())
        try:
            result = PinnedContainerExecutor()(request)
        finally:
            if previous is None:
                os.environ.pop("ARI_HARNESS_CONTAINER_ROOT", None)
            else:
                os.environ["ARI_HARNESS_CONTAINER_ROOT"] = previous

        body = json.loads(result.model_dump_json())
        stdout = ""
        for artifact in body.get("artifacts", []):
            path = workspace_root / artifact["relative_path"]
            if path.is_file() and artifact["relative_path"].endswith("stdout.log"):
                stdout = path.read_text(errors="replace")
        assert body["exit_code"] == 0, (
            f"the verifier did not complete inside the pinned image: {stdout[-1500:]}")
        assert body["network_report"] == "isolated"
        report = json.loads(stdout.strip().splitlines()[-1])
        assert report["schema_version"].startswith("ari.native-hpc-verification-report")
        assert report["deterministic"] is True
        assert report["negative_control"] is False
