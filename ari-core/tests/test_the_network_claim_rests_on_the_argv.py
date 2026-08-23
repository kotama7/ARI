"""``network_isolation: proved`` names a flag, and nothing held the flag in place.

WHAT THE CLAIM RESTS ON. ``isolation_findings`` reports ``network_isolation`` as
``"proved"`` when every execution's record says ``network: deny``. Its docstring
is explicit about why that is allowed to be the word "proved": *isolation is
proved by that argv rather than by a caller's boolean* -- the executor turns a
denying request into ``--network none`` and the container runtime does the rest.

THE CHAIN HAS TWO LINKS AND ONLY ONE WAS CHECKED. That every run declared deny
is derived. That a denying request becomes an isolated launch is a property of
``_container_argv``, and nothing asserted it.

MEASURED: deleting ``--net --network none`` from the apptainer branch left 518
tests green across the container, isolation, execution, promotion, evidence and
assurance suites, and every registration would still have declared
``network_isolation: proved``. The word rested on a line no test named.

These tests are the missing link. They do not prove a container was isolated --
that would need an execution that tried, and the record it would leave does not
exist yet. They prove the argv the evidence's reasoning refers to is the argv
this code builds.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from ari.assurance import executors
from ari.assurance.executors import PinnedContainerExecutor

DIGEST = "sha256:" + "a" * 64
#: A real directory, because the executor refuses a package root that is not one
#: -- the same guard that stops a verifier being mounted from a symlink.
PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def _request(runtime: str, reference: str, network: str = "deny"):
    return SimpleNamespace(
        network=network,
        container=SimpleNamespace(runtime=runtime, reference=reference,
                                  resolution_status="resolved", digest=DIGEST),
        limits=SimpleNamespace(max_processes=64, memory_bytes=1 << 30),
    )


@pytest.fixture
def _launchable(monkeypatch, tmp_path):
    """Everything the builder touches on the machine, and nothing it decides."""
    image = tmp_path / "image.sif"
    image.write_bytes(b"not a real image")
    monkeypatch.setattr(executors.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(executors, "_resolve_sif_reference", lambda ref: image)
    monkeypatch.setattr(executors, "_require_pinned_content",
                        lambda image, digest: None)
    return tmp_path


@pytest.mark.parametrize(
    "runtime,reference,expected",
    [
        ("apptainer", "apptainer:image.sif", ("--net", "--network", "none")),
        ("singularity", "singularity:image.sif", ("--net", "--network", "none")),
        ("docker", f"registry.example/x@{DIGEST}", ("--network", "none")),
    ],
)
def test_a_denying_request_becomes_an_isolated_launch(
    _launchable, runtime, reference, expected
) -> None:
    argv = PinnedContainerExecutor(package_root=PACKAGE_ROOT)._container_argv(
        _request(runtime, reference), _launchable, ["/bin/true"])
    joined = " ".join(argv)
    for flag in expected:
        assert flag in argv, (
            f"the {runtime} launch carries no {flag!r}; registration evidence "
            f"would still read network_isolation: proved, and the word rests on "
            f"this argv. Built: {joined}")
    index = argv.index("--network")
    assert argv[index + 1] == "none", (
        f"the {runtime} launch names a network other than none: {joined}")


def test_the_isolated_launch_is_not_conditional_on_the_caller(_launchable) -> None:
    """The flags are unconditional, and that is the point.

    A launcher that isolated only when asked would put the decision back in the
    caller's boolean -- the thing the evidence's reasoning explicitly refuses to
    rest on. The executor runs Harness verification and nothing else, so every
    launch it builds is isolated regardless of what the request says.
    """
    argv = PinnedContainerExecutor(package_root=PACKAGE_ROOT)._container_argv(
        _request("apptainer", "apptainer:image.sif", network="allow"),
        _launchable, ["/bin/true"])
    assert "--network" in argv and argv[argv.index("--network") + 1] == "none", (
        "a request that did not ask for isolation got an unisolated launch; "
        "the executor's isolation must not be the caller's to switch off")
