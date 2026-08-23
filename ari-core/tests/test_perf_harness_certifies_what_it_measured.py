"""What ``hpc/gemm-performance`` pins must be what its measurement actually was.

The two contradictions this Harness was registered with -- an interface contract
naming a shared-library ABI it does not consume, and a placement naming an
architecture its own supported set excluded -- are fixed and re-registered.
``test_harness_applicability`` now asserts both as live invariants rather than
xfails.

THREE RESIDUALS SURVIVED THAT REPAIR, and each is the same species of defect:
something the manifest asserts is not something any execution established. They
are recorded as strict xfails rather than fixed because every one of them moves a
digest -- ``supported_dtypes`` and the driver bytes are manifest fields, and the
evidence bundle is pinned by the catalog row -- so each repair is a full
re-registration needing the control sequence and a maintainer signature. A strict
xfail turns red the moment one is fixed, which is the only way a repair here
cannot land silently against a stale pin.

WHY THEY WERE NOT FIXED IN THE SAME BREATH. A re-registration must measure a
STILL instrument, and it must be able to produce a container attestation whose
placement is the placement the manifest pins. The third test below is the reason
the second condition does not hold on a host whose physical core count differs
from the pinned budget: the placement gate is enforced on the host, and the
measurement happens on the other side of a ``--cleanenv`` wall.

TWO OF THE THREE ARE NOW LIVE INVARIANTS. ``supported_dtypes`` and the missing
container assertion were repaired together, in ONE re-registration -- separately
would have re-signed the same harness twice for one moved digest -- and both
tests are asserted rather than expected to fail. Their xfails were STRICT, so
each turned red the moment its repair landed, which is the whole reason they
were written that way; what removes them here is the registration that earned
the evidence for the manifest they now describe. The third stands.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

BUILTIN = Path(__file__).resolve().parents[1] / "config" / "harnesses" / "builtin"
PERF = BUILTIN / "hpc_gemm_performance.yaml"


def _perf_manifest_document() -> dict:
    return yaml.safe_load(PERF.read_text())


def test_the_dtypes_it_admits_are_the_dtypes_its_property_covers():
    """A declaration it accepts must be one its only property has a scope for.

    FIXED AND RE-REGISTERED; kept as the invariant. The manifest advertised
    float32 AND float64 -- the two halves of the ``gemm-c-abi/v1`` shared
    library (``ari_gemm_f32`` and ``ari_gemm_f64``) this Harness stopped
    consuming; correcting the interface contract moved one field and left this
    one behind. Its single property, ``performance-regression``, declares
    ``dtype: [float64]``, its problem is ``gemm-dense-fp64``, and its sibling
    over that identical problem advertises float64 alone.

    MEASURED BEFORE THE FIX, because a defect nobody reached is a different
    finding from one that was live: ``harness_inapplicability`` returned ``''``
    -- applicable -- for a float32 declaration identical in every other field,
    and ``request.py:89`` is the ONLY reader of ``declaration.dtype`` anywhere
    in the assurance package, so nothing further down asked again. The float32
    candidate was admitted, measured against an fp64 problem whose measurement
    path reads every buffer as ``np.float64``, and the attestation carried a
    property whose tested scope did not contain the dtype the declaration named.

    This was not hypothetical plumbing: ``supported_dtypes[0]`` is what a
    declaration builder reaches for first, so float32 was the DEFAULT choice,
    not an exotic one.
    """
    from ari.assurance.models import HarnessManifestV1, HarnessTargetDeclarationV1
    from ari.assurance.request import harness_inapplicability

    manifest = HarnessManifestV1.model_validate(_perf_manifest_document())
    covered = set(manifest.properties[0].scope.values["dtype"])
    admitted = set()
    for dtype in manifest.supported_dtypes:
        declaration = HarnessTargetDeclarationV1.create(
            logical_name="candidate_gemm.c",
            target_kind=manifest.target_kinds[0],
            subject_type=manifest.subject_types[0],
            language=manifest.supported_languages[0],
            hardware=manifest.supported_hardware[0],
            architecture=manifest.supported_architectures[0],
            dtype=dtype,
            interface_contract=manifest.target_interface_contract,
            target_digest="sha256:" + "6" * 64,
        )
        if not harness_inapplicability(manifest=manifest, declaration=declaration):
            admitted.add(dtype)
    assert admitted <= covered, (
        f"{manifest.id} admits {sorted(admitted - covered)}, which its only "
        f"property scopes to {sorted(covered)}")


def test_prepare_refuses_a_request_that_runs_in_another_container():
    """The pinned image must be asserted on the request, as the siblings assert it.

    FIXED AND RE-REGISTERED; kept as the invariant. ``NativeHPCDriver.prepare``
    and ``ProblemCorrectnessDriver.prepare`` both raise "lacks the pinned
    container identity" when the request names an image other than
    ``manifest.container.resolved_digest``. The performance driver checked
    driver bytes, the problem, the case set, both policies and the placement --
    and never the container; the word did not occur in ``perf.py`` at all.

    It matters more here than for either sibling, not less. ``runner`` stamps the
    attestation's ``container_digest`` from the MANIFEST rather than from the
    execution, so nothing downstream can notice either; and a timed verdict is a
    statement about a toolchain as much as about a machine, so a measurement
    taken in a different image is a different measurement wearing this
    manifest's name.
    """
    from ari.assurance.drivers.perf import NativePerfDriver
    from ari.assurance.models import HarnessManifestV1

    manifest = HarnessManifestV1.model_validate(_perf_manifest_document())
    atom = SimpleNamespace(
        property_id="performance-regression", method="benchmark-comparison",
        tier="validate", scope={}, atom_digest="sha256:" + "0" * 64)
    request = SimpleNamespace(
        property_atoms=(atom,),
        execution_request=SimpleNamespace(
            network="deny",
            container=SimpleNamespace(digest="sha256:" + "2" * 64)),
        run_id="run")
    with pytest.raises(ValueError, match="pinned container identity"):
        NativePerfDriver().prepare(manifest, request)


@pytest.mark.xfail(strict=True, reason=(
    "The placement gate runs on the host; the measurement runs inside a "
    "--cleanenv container that is handed only PYTHONPATH, so the pinned thread "
    "budget cannot reach the process that times anything."))
def test_the_pinned_placement_reaches_the_process_that_measures():
    """Otherwise the gate certifies a placement the measurement never had.

    ``NativePerfDriver.prepare`` compares ``registered_placement`` against
    ``measurement_placement()`` evaluated ON THE HOST, and refuses a mismatch --
    "a timed verdict does not transfer across machines any more than it
    transfers across sizes". The verifier that produces the number then runs
    inside the pinned container, which ``PinnedContainerExecutor`` launches with
    ``--cleanenv`` and exactly one ``--env``, ``PYTHONPATH``.

    ``measurement_placement`` derives ``thread_budget`` from ``ARI_PERF_THREADS``
    when it is set and from the physical core count otherwise. Neither the
    variable nor any OpenMP variable is carried across, so the in-container
    budget is always the host's physical core count. On a host whose cores equal
    the pinned budget the two agree by luck; on any other host the gate passes
    on the host's value while the container measures at its own, and the
    attestation certifies the pinned placement regardless.

    The failure is silent in the direction that matters: setting
    ``ARI_PERF_THREADS`` to the pinned budget makes ``prepare`` accept a host
    that does not have it, which is exactly the case the gate exists to refuse.
    """
    from ari.assurance.executors import PinnedContainerExecutor

    document = _perf_manifest_document()
    pinned_budget = document["registered_placement"]["thread_budget"]
    executor = PinnedContainerExecutor(
        package_root=Path(__file__).resolve().parents[1])
    request = SimpleNamespace(
        container=SimpleNamespace(
            reference=document["container"]["reference"],
            runtime="singularity",
            digest=document["container"]["resolved_digest"],
            resolution_status="resolved"),
        limits=SimpleNamespace(max_processes=64))
    argv = executor._container_argv(request, Path("."), ["true"])
    carried = [argv[index + 1] for index, item in enumerate(argv)
               if item == "--env"]
    assert any(pinned_budget == value.split("=", 1)[-1] for value in carried), (
        f"the container is launched with {carried} and --cleanenv, so the "
        f"pinned thread budget {pinned_budget!r} never reaches the measurement; "
        f"the placement gate is enforced on the host side of that wall")


def test_the_placement_gate_is_evaluated_on_the_host():
    """The fact the xfail above rests on, asserted so it cannot drift quietly.

    Not an xfail: this is TRUE today and is the mechanism, not the defect. If
    ``prepare`` ever moves its placement check to something the container
    reports, this test is where that shows up.
    """
    import inspect

    from ari.assurance.drivers import perf

    source = inspect.getsource(perf.NativePerfDriver.prepare)
    assert "measurement_placement()" in source, (
        "prepare no longer reads the host's own placement; the xfail above "
        "describes a wall that may have moved")
