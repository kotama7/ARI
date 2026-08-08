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

WHAT THE GATING RULE IS. The pinned image is a site artifact and is not in this
repository, so a machine without it cannot run the launch test -- that is a
legitimately absent artifact, not a defect, and it skips. But a machine that HAS
the image is a machine set up to verify, and there the pinned runtime must exist
and the pinned bound must be large enough to launch it. Those do not skip: they
are the two failures above.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from ari.assurance.executors import PinnedContainerExecutor
from ari.assurance.models import HarnessManifestV1
from ari.execution import ContainerIdentityV1, ExecutionRequestV1, WorkspaceRefV1


CORE = Path(__file__).resolve().parents[1]
REPOSITORY = CORE.parent
BUILTIN = CORE / "config" / "harnesses" / "builtin"
CANDIDATE_SOURCE = CORE / "tests" / "fixtures" / "assurance" / "native_reference_candidate.c"

#: The smallest RLIMIT_AS at which the pinned container runtime can start.
#:
#: MEASURED, on an exclusive compute node, against the image the catalog pins:
#: 4 GiB aborts with ``runtime/cgo: pthread_create failed: Resource temporarily
#: unavailable`` before the verifier runs at all; 8 GiB succeeds, and the full
#: certify tier then returns the SAME report digest at 8 and at 16 GiB, so the
#: verdict does not depend on where above this floor the bound sits.
#:
#: This is a bound on the verifier AND on the launcher that starts it, because
#: RLIMIT_AS is applied to the process that is exec'd and inherited by what it
#: execs. It is therefore not the verifier's own working set, and a manifest
#: that sizes it as if it were cannot run.
CONTAINER_LAUNCHER_ADDRESS_SPACE_FLOOR = 8 * 1024**3

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


# --- what holds on every machine ----------------------------------------------

def test_every_containerised_harness_clears_the_launcher_address_space_floor():
    """A bound below the floor cannot start the runtime, so the harness cannot
    run anywhere -- and nothing else in this repository notices."""
    for manifest in _containerised():
        assert manifest.resources.memory_bytes >= CONTAINER_LAUNCHER_ADDRESS_SPACE_FLOOR, (
            f"{manifest.id} pins {manifest.resources.memory_bytes} bytes of address "
            f"space, below the {CONTAINER_LAUNCHER_ADDRESS_SPACE_FLOOR} the container "
            f"runtime needs before it can create a thread; the verifier would never "
            f"start and the failure would read as infrastructure_error")


def test_every_container_reference_names_a_runtime_the_executor_can_launch():
    """The prefix is not decoration: it selects the binary that gets exec'd."""
    for manifest in _manifests():
        runtime = manifest.container.reference.split(":", 1)[0]
        assert runtime in LAUNCHABLE_RUNTIMES, (
            f"{manifest.id} names runtime {runtime!r}, which the executor has no "
            f"branch for")


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
