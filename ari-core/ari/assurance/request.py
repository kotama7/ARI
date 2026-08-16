"""Build immutable Harness requests from a declared, digest-verified target."""

from __future__ import annotations

import re
import sys

from ari.assurance.models import (
    BaselineHarnessLockV1,
    HarnessManifestV1,
    HarnessRunRequestV1,
    HarnessTargetDeclarationV1,
    LockedHarnessV1,
)
from ari.execution import (
    ContainerIdentityV1,
    ExecutionLimitsV1,
    ExecutionPolicyError,
    ExecutionRequestV1,
    WorkspaceRefV1,
)
from ari.protocols.integrity import canonical_digest
from ari.research_contract import ResearchArtifactRefV1


class HarnessRequestError(ValueError):
    pass


_NODE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,255}$")


def _container_runtime(reference: str) -> str:
    prefix = reference.split(":", 1)[0].lower()
    if prefix in {"docker", "singularity", "apptainer"}:
        return prefix
    if "@sha256:" in reference:
        return "docker"
    if reference.endswith(".sif"):
        return "apptainer"
    return "unknown"


def load_target_declaration(
    workspace: WorkspaceRefV1,
    *,
    declaration_name: str = "assurance_target.json",
) -> HarnessTargetDeclarationV1:
    import json

    document = json.loads(
        workspace.read_bytes(declaration_name, max_bytes=256 * 1024).decode("utf-8")
    )
    declaration = HarnessTargetDeclarationV1.model_validate(document)
    current = workspace.file_digest(declaration.logical_name)
    if current != declaration.target_digest:
        raise HarnessRequestError("Harness target declaration uses a stale digest")
    return declaration


def harness_inapplicability(
    *,
    manifest: HarnessManifestV1,
    declaration: HarnessTargetDeclarationV1,
) -> str:
    """Why this Harness cannot judge this target, or "" when it can.

    NOT an error in itself. A lock is resolved for a CONTRACT and a node
    produces ONE artifact, so a lock can perfectly well hold a Harness that
    scores benchmark submissions beside one that verifies shared libraries, and
    the shipped catalog does exactly that -- three verifiers over three
    different interface contracts and one benchmark over a fourth target kind.
    Whichever does not match the artifact in hand cannot say anything about it.

    Separated from the validator so the caller can decide what that means.
    Reaching for the Harness anyway and treating the refusal as a request
    failure abandoned the whole tier -- every Harness after it went unrun.
    Measured on the shipped catalog that costs nothing today, because the lock
    sorts by harness id and puts the inapplicable one last; the defect is latent
    and waiting on an id that sorts the other way.
    """
    for actual, supported, label in (
        (declaration.target_kind, manifest.target_kinds, "target kind"),
        (declaration.subject_type, manifest.subject_types, "subject type"),
        (declaration.language, manifest.supported_languages, "target language"),
        (declaration.hardware, manifest.supported_hardware, "target hardware"),
        (declaration.architecture, manifest.supported_architectures,
         "target architecture"),
        (declaration.dtype, manifest.supported_dtypes, "target dtype"),
    ):
        if actual not in supported:
            return f"declared {label} is incompatible with Harness"
    if declaration.interface_contract != manifest.target_interface_contract:
        return "declared target interface differs from Harness contract"
    return ""


#: What the declared target IS, for the evidence reference. Keyed on the kind the
#: declaration carries rather than assumed, and defaulting to a generic type
#: rather than to whichever one happened to be written first.
_TARGET_MEDIA_TYPES = {
    "shared-library": "application/x-sharedlib",
    "benchmark-submission": "text/x-c",
}


#: WHICH WORKER RUNS, keyed on the driver the manifest pins.
#:
#: THE DEFECT THIS FIXES. This module built ONE argv -- ``native_worker`` with
#: ``--kind`` and ``--library`` -- and derived the kind by string surgery on the
#: harness id (``rsplit('/')[-1].removesuffix('-correctness')``). That was the
#: whole truth while every artifact verifier was an ARI-native one. For the
#: problem-correctness harness it produces ``--kind gemm-dense-fp64-problem``,
#: which names no registered family, and hands ``--library candidate_gemm.c``,
#: which is C source and not a library. Both are wrong in the same direction:
#: the request would launch the wrong verifier, whose output the pinned driver
#: cannot parse, so a correctly resolved and correctly locked Harness would
#: return ``infrastructure_error`` on every node -- the mismatch surfacing as an
#: outage instead of as an error, one layer further down.
#:
#: Keyed on ``driver.revision`` because that is what ``resolver`` locks and what
#: ``prepare`` re-checks; deriving the worker from the harness ID means the ID
#: is load-bearing text, which is how the string surgery above happened.
def _worker_argv(manifest, declaration, *, tier: str, seed: int) -> list[str]:
    revision = manifest.driver.revision
    if revision == "ari.assurance.problem-correctness/v1":
        # The problem IS the question, and the manifest pins it in ``oracle``;
        # the candidate is the declared artifact. Neither is derived from the
        # harness id. ``--flags=`` form is mandatory -- see the worker.
        return [
            sys.executable, "-m",
            "ari.assurance.drivers.problem_correctness_worker",
            "--problem", manifest.oracle.revision,
            "--candidate", declaration.logical_name,
            "--tier", tier,
            "--seed", str(seed),
            "--dataset-revision", manifest.dataset.revision,
        ]
    if revision == "ari.assurance.native-perf/v1":
        # THE GOVERNED PATH COULD NOT LAUNCH THIS HARNESS AT ALL. The driver is
        # wired, undrifted and registered; every request for it died here, at
        # the fail-closed raise below, because no branch named its revision. The
        # bridge turns that into "inconclusive", so a Harness that had been
        # measured, gated 15/15 and signed produced nothing on every node and
        # said nothing about why.
        #
        # Same shape as the problem-correctness branch: the PROBLEM is what the
        # manifest pins in ``oracle`` and the candidate is the declared
        # artifact, so neither is derived from the harness id.
        return [
            sys.executable, "-m", "ari.assurance.drivers.perf_worker",
            "--problem", manifest.oracle.revision,
            "--candidate", declaration.logical_name,
            "--tier", tier,
            "--seed", str(seed),
            "--dataset-revision", manifest.dataset.revision,
        ]
    if revision == "ari.assurance.native-hpc/v1":
        return [
            sys.executable, "-m", "ari.assurance.drivers.native_worker",
            "--kind", manifest.id.rsplit("/", 1)[-1].removesuffix("-correctness"),
            "--library", declaration.logical_name,
            "--tier", tier,
            "--seed", str(seed),
        ]
    # Fail closed. A silent fallback to the ARI-native worker is exactly the
    # behaviour being removed: it would run the wrong verifier and report the
    # result as this manifest's.
    raise HarnessRequestError(
        f"no worker is registered for driver {revision!r}; this Harness cannot "
        f"be launched, which is a different thing from failing to verify")


def _validate_native_inputs(
    *,
    node_id: str,
    workspace: WorkspaceRefV1,
    execution_workspace: WorkspaceRefV1,
    declaration: HarnessTargetDeclarationV1,
    manifest: HarnessManifestV1,
    locked: LockedHarnessV1,
    baseline: BaselineHarnessLockV1,
) -> None:
    if not _NODE_ID.fullmatch(node_id):
        raise HarnessRequestError("unsafe node identity")
    if locked.manifest_digest != manifest.manifest_digest:
        raise HarnessRequestError("Harness manifest differs from lock")
    if locked not in baseline.harnesses:
        raise HarnessRequestError("Harness is absent from baseline lock")
    inapplicable = harness_inapplicability(manifest=manifest, declaration=declaration)
    if inapplicable:
        raise HarnessRequestError(inapplicable)
    if workspace.file_digest(declaration.logical_name) != declaration.target_digest:
        raise HarnessRequestError("candidate target changed before request minting")
    if execution_workspace.root == workspace.root:
        raise HarnessRequestError(
            "Harness execution workspace must be separate from candidate workspace"
        )


def _snapshot_target(
    *,
    source: WorkspaceRefV1,
    destination: WorkspaceRefV1,
    declaration: HarnessTargetDeclarationV1,
) -> None:
    payload = source.read_bytes(
        declaration.logical_name, max_bytes=256 * 1024 * 1024
    )
    try:
        snapshot_digest = destination.file_digest(declaration.logical_name)
    except (FileNotFoundError, OSError, ExecutionPolicyError):
        destination.atomic_write_bytes(declaration.logical_name, payload)
        snapshot_digest = destination.file_digest(declaration.logical_name)
    if snapshot_digest != declaration.target_digest:
        raise HarnessRequestError(
            "verification workspace target snapshot differs from candidate"
        )
    destination.resolve(declaration.logical_name, require_file=True).chmod(0o400)


def build_native_harness_run_request(
    *,
    run_id: str,
    node_id: str,
    epoch_id: str,
    workspace: WorkspaceRefV1,
    execution_workspace: WorkspaceRefV1,
    declaration: HarnessTargetDeclarationV1,
    manifest: HarnessManifestV1,
    locked: LockedHarnessV1,
    baseline: BaselineHarnessLockV1,
    tier: str = "screen",
    retry_index: int = 0,
) -> HarnessRunRequestV1:
    """Build the exact request consumed by :class:`NativeHPCDriver`.

    The target is copied by the execution substrate through the existing
    ``ExecutionRequestV1.input_digests`` mechanism.  No command comes from a
    Knowledge body or Provider description.
    """

    _validate_native_inputs(
        node_id=node_id,
        workspace=workspace,
        execution_workspace=execution_workspace,
        declaration=declaration,
        manifest=manifest,
        locked=locked,
        baseline=baseline,
    )
    atoms = tuple(
        item
        for item in baseline.requirements
        if item.atom_digest in set(locked.covered_atom_digests) and item.tier == tier
    )
    if not atoms:
        raise HarnessRequestError("Harness has no locked property atoms for requested tier")
    identity_input = {
        "run_id": run_id,
        "node_id": node_id,
        "epoch_id": epoch_id,
        "harness": locked.manifest_digest,
        "target": declaration.target_digest,
        "tier": tier,
        "retry_index": retry_index,
    }
    token = canonical_digest(identity_input).removeprefix("sha256:")
    attempt_id = f"har-{token[:32]}-{retry_index}"
    seed = int(token[:8], 16)
    _snapshot_target(
        source=workspace,
        destination=execution_workspace,
        declaration=declaration,
    )
    execution = ExecutionRequestV1(
        workspace=execution_workspace,
        argv=_worker_argv(manifest, declaration, tier=tier, seed=seed),
        timeout_seconds=manifest.timeout_seconds,
        limits=ExecutionLimitsV1(
            cpu_seconds=min(manifest.timeout_seconds, 86_400),
            memory_bytes=(
                manifest.resources.memory_bytes
                if manifest.resources.memory_bytes >= 16 * 1024 * 1024
                else None
            ),
            max_output_bytes=max(1024 * 1024, min(manifest.resources.disk_bytes, 1024**3)),
        ),
        network="deny",
        request_id=attempt_id,
        input_digests={declaration.logical_name: declaration.target_digest},
        container=ContainerIdentityV1(
            runtime=_container_runtime(manifest.container.reference),
            reference=manifest.container.reference,
            digest=manifest.container.resolved_digest,
            resolution_status="resolved",
        ),
    )
    artifact = ResearchArtifactRefV1(
        logical_name=declaration.logical_name,
        digest=declaration.target_digest,
        # FROM THE DECLARATION, not a constant. The one constant was true while
        # every verification target was a shared library; a candidate submitted
        # against a problem's own header is C source, and calling it
        # x-sharedlib mislabels the evidence a reader uses to find it.
        media_type=_TARGET_MEDIA_TYPES.get(declaration.target_kind,
                                           "application/octet-stream"),
        role="verification-target",
        source_run_id=run_id,
    )
    return HarnessRunRequestV1.create(
        run_id=run_id,
        node_id=node_id,
        epoch_id=epoch_id,
        active_harness_lock_digest=baseline.lock_digest,
        harness=locked,
        target_workspace=workspace,
        target_artifact=artifact,
        target_logical_name=declaration.logical_name,
        target_kind=declaration.target_kind,
        target_digest=declaration.target_digest,
        property_atoms=atoms,
        execution_request=execution,
        attempt_id=attempt_id,
        retry_index=retry_index,
        expected_result_schema=manifest.expected_result_schema,
    )


__all__ = [
    "harness_inapplicability",
    "HarnessRequestError",
    "build_native_harness_run_request",
    "load_target_declaration",
]
