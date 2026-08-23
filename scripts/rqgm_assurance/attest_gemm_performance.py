#!/usr/bin/env python3
"""Earn the performance Harness's attestations by RUNNING its controls.

THE DEFECT THIS REPAIRS. ``hpc/gemm-performance`` CARRIED ``status: verified``
while shipping no ``HarnessAttestationV1`` at all. It had been registered through
``repin_and_promote_harness.py``, which wrote ``clean_control_verdict="pass"``
and ``negative_control_verdict="fail"`` into ``registration_evidence.json`` as
LITERALS and pointed ``attestation_digests`` at its own registration report --
the bundle citing itself as the execution it never performed. That surface now
refuses to promote and says so, naming this family as the one nothing can earn.
This module is what earns it.

WHY IT COULD NOT BE WRITTEN UNTIL NOW. The governed path could not launch this
Harness at all: ``request.py``'s ``_worker_argv`` had branches for two driver
revisions and failed closed on ``ari.assurance.native-perf/v1``, so every
request died at minting. With that branch in place a perf worker runs inside the
pinned image like any other, and a control sequence becomes possible.

WHAT A PERFORMANCE SEQUENCE HAS TO SHOW, and it is not what a correctness one
shows. A correctness sequence demonstrates that a wrong answer is caught. A
stopwatch also catches nothing else -- so the claim here is SEPARATION: that the
instrument tells a WRONG answer from a SLOW one, and does so for different
reasons. The problem ships both negatives for exactly this, and
``check_control_sequence`` refuses unless each fails on its own ground:
``slow_gemm.c`` is correct and loses on the ratio; ``wrong_gemm.c`` is fast,
writes every element -- clearing the NaN poison and the size check -- and loses
on the residual bound. Two negatives failing the same way would certify a
stopwatch wearing a benchmark label.

WHAT IS REUSED, AND THEREFORE NOT REIMPLEMENTED. Everything family-agnostic
comes from ``attest_problem_correctness``: the host-identity refusal, the
declaration builder, the candidate loader that reads the PROBLEM's own files,
the contract builder, the bundle writer and the published-artifact map that the
guard covers in one place. What is here is the control set, the check that
decides whether they discriminated, and the loop that runs them through this
driver.

THE TWO MODES, AND WHY THEY ARE TWO. ``controls`` runs the sequence into a
scratch directory: it writes nothing into the repository and needs no human
identity, so building the capability stays separate from exercising it.
``promote`` runs the same sequence, earns the registration gates and signs the
re-registration, and it is the only surface in this repository that can
re-register this family at all -- ``repin_and_promote_harness.py``'s ``promote``
was closed for declaring evidence it never ran, and a re-pin without a
re-registration leaves the report, the evidence and the approval naming a
manifest digest that has moved, which is a catalog that will not load.

WHAT IT WILL NOT DO. It will not author a control kernel. Every candidate is a
file the problem already ships, because a kernel written into this script is one
the registration could not point at, and a weakened one would be
indistinguishable from a strengthened instrument. It will not declare a control
outcome, an isolation finding or a schema-conformance claim: every field
``registration_evidence.json`` carries is read back off what a request carried
or what a run returned, and a promotion whose gates refuse writes nothing.
"""

from __future__ import annotations

import argparse
import os
import platform
import sys
import tempfile
import yaml
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
ARI_CORE = REPO_ROOT / "ari-core"
sys.path.insert(0, str(ARI_CORE))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from attest_problem_correctness import (  # noqa: E402
    ARI_CORE as _SHARED_ARI_CORE,
    BUILTIN,
    HARNESS_ROOT,
    ControlSequenceError,
    _json_bytes,
    _single,
    _wall_seconds,
    _write_bundle,
    build_declaration,
    candidate_source,
    isolation_findings,
    _tolerance_ref,
    property_map,
    published_artifacts,
    refuse_host_identity,
)
from ari.assurance.catalog import build_harness_catalog_snapshot  # noqa: E402
from ari.assurance.drivers.perf import (  # noqa: E402
    PERF_DRIVER_REVISION,
    NativePerfDriver,
)
from ari.assurance.executors import PinnedContainerExecutor  # noqa: E402
from ari.assurance.models import (  # noqa: E402
    HarnessManifestV1,
    VerificationContractV1,
    VerificationRequirementV1,
)
from ari.assurance.native_perf_common import measurement_placement  # noqa: E402
from ari.assurance.problems import load_problem  # noqa: E402
from ari.assurance.registration_models import (  # noqa: E402
    HarnessPromotionApprovalV1,
    HarnessRegistrationEvidenceV1,
)
from ari.assurance.registration_run import (  # noqa: E402
    register_harness,
    repository_commit,
)
from ari.assurance.request import build_native_harness_run_request  # noqa: E402
from ari.assurance.resolver import (  # noqa: E402
    mint_baseline_harness_lock,
    resolve_harness_suite,
)
from ari.assurance.runner import FixedVerifier  # noqa: E402
from ari.execution import WorkspaceRefV1  # noqa: E402
from ari.protocols.integrity import bytes_digest, canonical_digest  # noqa: E402
from ari.protocols.scientific_requirements import EnvironmentSnapshotV1  # noqa: E402

PROPERTY = "performance-regression"


@dataclass(frozen=True)
class PerfControl:
    """One labelled execution, the verdict it must produce, and on what ground.

    ``ground`` is the discriminator. A sequence that pinned only the verdicts
    would accept two negatives that failed the same way, which is precisely the
    thing a benchmark must not be: it would show that something was refused and
    not that a wrong answer was told apart from a slow one.
    """

    label: str
    role: str
    tier: str
    retry_index: int
    verdict: str
    ground: str | None
    why: str


#: THE SEQUENCE.
#:
#: The clean control runs at SCREEN and at VALIDATE because they are different
#: claims. Screen is one repetition and therefore has no spread; validate is
#: three, which is the smallest number from which a spread exists at all -- and
#: this instrument's verdict rule reads that spread. A clean control shown only
#: at screen would leave the tier a ratio is actually read at unexercised.
#:
#: The repeat is at a different retry index, so the seeds differ: the claim is
#: that the verdict is stable across instances, which is weaker and more honest
#: than digest equality between two runs of the same input.
#:
#: BOTH NEGATIVES, and this is the whole point of the family. A correctness
#: sequence needs one negative; a benchmark needs two that fail differently, or
#: it has not shown it can tell a wrong answer from a slow one.
CONTROLS: tuple[PerfControl, ...] = (
    PerfControl(
        label="clean-screen",
        role="reference",
        tier="screen",
        retry_index=0,
        verdict="pass",
        ground=None,
        why="the frozen reference is not a regression against itself",
    ),
    PerfControl(
        label="clean-validate",
        role="reference",
        tier="validate",
        retry_index=0,
        verdict="pass",
        ground=None,
        why=("and stays so at the tier a spread exists at, which is the tier "
             "this instrument's verdict rule reads"),
    ),
    PerfControl(
        label="clean-validate-repeat",
        role="reference",
        tier="validate",
        retry_index=1,
        verdict="pass",
        ground=None,
        why=("and again at a different derived seed: the verdict is stable "
             "across instances"),
    ),
    PerfControl(
        label="negative-slow-screen",
        role="negative_control_slow",
        tier="screen",
        retry_index=0,
        verdict="fail",
        ground="ratio",
        why=("a correct kernel that is slower than the reference must lose ON "
             "THE RATIO -- it is right about the answer, so nothing else may "
             "refuse it"),
    ),
    PerfControl(
        label="negative-wrong-screen",
        role="negative_control_wrong",
        tier="screen",
        retry_index=0,
        verdict="fail",
        ground="oracle",
        why=("a fast kernel with the wrong answer must lose ON THE ORACLE: it "
             "writes every element, so it clears the NaN poison and the size "
             "check, and only the residual bound refuses it"),
    ),
)

def load_manifest(path: Path) -> HarnessManifestV1:
    """The manifest, refused unless it is one THIS sequence can speak for.

    The problem-correctness sequence has the same guard for its own revision, so
    neither can be pointed at the other's family by a filename.
    """
    manifest = HarnessManifestV1.model_validate(
        yaml.safe_load(path.read_text(encoding="utf-8")))
    if manifest.driver.revision != PERF_DRIVER_REVISION:
        raise ControlSequenceError(
            f"{manifest.id} pins driver {manifest.driver.revision!r}; this "
            f"sequence runs {PERF_DRIVER_REVISION!r} only")
    if len(manifest.target_kinds) != 1:
        raise ControlSequenceError(
            f"{manifest.id} accepts {list(manifest.target_kinds)}; a control "
            f"sequence stages ONE artifact, so the target kind must be one")
    if [item.property_id for item in manifest.properties] != [PROPERTY]:
        raise ControlSequenceError(
            f"{manifest.id} declares "
            f"{[item.property_id for item in manifest.properties]}; this "
            f"sequence discriminates {PROPERTY} and would attest to properties "
            f"it never exercised")
    return manifest


def build_control_contract(manifest: HarnessManifestV1) -> VerificationContractV1:
    """A contract over exactly the property and tiers THIS sequence runs.

    Same construction as the problem-correctness sequence's, and local for one
    reason: that one derives its tiers from ITS ``CONTROLS``, which are screen
    and certify. This sequence runs screen and validate, because validate is the
    smallest tier at which a spread exists and a spread is what this
    instrument's verdict rule reads. Importing it would have built a contract
    for tiers these controls never run.
    """
    target_kind = manifest.target_kinds[0]
    tiers = tuple(sorted({control.tier for control in CONTROLS},
                         key=("screen", "validate", "certify").index))
    requirements: list[VerificationRequirementV1] = []
    for provided in manifest.properties:
        for tier in tiers:
            if tier not in provided.tiers:
                raise ControlSequenceError(
                    f"{manifest.id} does not declare {provided.property_id} at "
                    f"tier {tier!r}, which the control sequence runs")
            requirements.append(
                VerificationRequirementV1.create(
                    property_id=provided.property_id,
                    target_kind=target_kind,
                    required_methods=provided.methods,
                    required_tier=tier,
                    failure_policy=("block-publication" if tier == "certify"
                                    else "exclude-from-scientific-frontier"),
                    scope=provided.scope,
                    tolerance_policy_ref=_tolerance_ref(
                        provided.tolerance_policy_digest),
                    tolerance_policy_digest=provided.tolerance_policy_digest,
                    source_requirement_refs=("registration:" + manifest.id,),
                )
            )
    return VerificationContractV1.create(
        run_id="harness-registration-" + manifest.id.replace("/", "-"),
        research_contract_digest=canonical_digest(
            {"registration": manifest.id,
             "manifest_digest": manifest.manifest_digest}),
        requirements=tuple(sorted(requirements,
                                  key=lambda item: item.requirement_digest)),
        admission_confidence=1.0,
        human_review_identity=canonical_digest(
            "gemm-performance-harness-registration"),
        property_vocabulary_digest=bytes_digest(
            (HARNESS_ROOT / "property_vocabulary.yaml").read_bytes()),
    )


def _ground_of(attestation: Any) -> str | None:
    """Which ground refused this candidate, read from the FACTS.

    NOT from a sentence. The driver's case detail -- "0.009x of the frozen
    reference, below the threshold", "failed the residual bound" -- does not
    reach an attestation at all: ``measurements`` carries numbers,
    ``tolerance_evidence`` the threshold and the spread, ``oracle_comparison``
    the digests and the placement. A sequence that matched on prose would be
    reading a field that is not there.

    So the two grounds are separated by the two facts that distinguish them. A
    candidate every repetition of which was CORRECT and which was still refused
    can only have lost on the RATIO -- it was right about the answer, so nothing
    else had grounds. One with an incorrect repetition was refused by the
    ORACLE, whatever its speed. This is what the per-case correctness the
    attestation now carries is for; before it, the two were indistinguishable
    from outside, which is exactly the conflation `failed_case_count` makes.
    """
    for result in attestation.property_results:
        if result.property_id != PROPERTY:
            continue
        correct = (result.measurements or {}).get("correct_by_case")
        if not correct:
            return None
        return "ratio" if all(correct.values()) else "oracle"
    return None


def _observed(attestation: Any) -> str:
    """The measured quantities behind a verdict, for a refusal to name."""
    for result in attestation.property_results:
        if result.property_id != PROPERTY:
            continue
        tolerance = result.tolerance_evidence or {}
        measurements = result.measurements or {}
        return (f"observed worst_relative_spread="
                f"{tolerance.get('worst_relative_spread')!r}, "
                f"min_speedup={measurements.get('min_speedup')!r}, "
                f"seconds_by_case={measurements.get('credited_seconds_by_case')!r}, "
                f"threshold={tolerance.get('regression_threshold')!r}, "
                # THE GROUND'S OWN INPUTS. A refusal that says the ground was
                # None sends the reader back to the container to find out
                # whether the cases disagreed or whether there were no cases --
                # which are opposite findings. An empty map here means the run
                # produced no case at all, so the verdict was not this
                # instrument's to give.
                f"correct_by_case={measurements.get('correct_by_case')!r}, "
                f"complete_by_case={measurements.get('complete_by_case')!r}, "
                f"measurement_keys={sorted(measurements)!r}")
    return "no result for this property"


def check_control_sequence(attestations: dict[str, Any]) -> dict[str, Any]:
    """Refuse unless the controls discriminated. Nothing else decides this.

    Three things are asked, and the third is the one a benchmark exists to
    answer:

    * every control produced the verdict it must produce ON ITS OWN;
    * the property this Harness decides is the one that carried each verdict,
      so a pass cannot rest on a property the manifest does not declare;
    * the two negatives failed on DIFFERENT GROUNDS. A slow-but-correct kernel
      must lose on the ratio and a fast-but-wrong one on the oracle. If both
      lose the same way, this instrument has shown only that it refuses things,
      which is what a stopwatch does.
    """
    missing = [control.label for control in CONTROLS
               if control.label not in attestations]
    if missing:
        raise ControlSequenceError(
            f"the sequence did not run {missing}; a control that did not run is "
            f"not a control")

    for control in CONTROLS:
        attestation = attestations[control.label]
        if attestation.verdict != control.verdict:
            # WITH THE NUMBER IT REFUSED ON. A sequence that says only which
            # verdict it wanted sends the reader back to the container to find
            # out why; the two quantities that decide a timed verdict are
            # already in the attestation it is holding.
            raise ControlSequenceError(
                f"{control.label} returned {attestation.verdict!r} where the "
                f"sequence requires {control.verdict!r}: {control.why}. "
                f"{_observed(attestation)}")
        verdicts = property_map(attestation)
        if verdicts.get(PROPERTY) != control.verdict:
            raise ControlSequenceError(
                f"{control.label} carried {PROPERTY} = "
                f"{verdicts.get(PROPERTY)!r} where the harness verdict was "
                f"{attestation.verdict!r}; the verdict must be this property's")
        if set(verdicts) != {PROPERTY}:
            raise ControlSequenceError(
                f"{control.label} decided {sorted(verdicts)}, but this manifest "
                f"declares only {PROPERTY}")

    grounds: dict[str, str | None] = {}
    for control in CONTROLS:
        if control.ground is None:
            continue
        observed = _ground_of(attestations[control.label])
        if observed != control.ground:
            raise ControlSequenceError(
                f"{control.label} was refused on {observed!r} where the "
                f"sequence requires {control.ground!r}: {control.why}. A "
                f"negative that fails for the wrong reason certifies nothing "
                f"about the reason it was written for. "
                f"{_observed(attestations[control.label])}")
        grounds[control.label] = observed

    if len(set(grounds.values())) < 2:
        raise ControlSequenceError(
            f"both negative controls were refused on the same ground "
            f"({sorted(set(grounds.values()))}); this sequence has shown that "
            f"the instrument refuses things, not that it can tell a wrong "
            f"answer from a slow one")

    # READ BACK OFF THE ATTESTATIONS, never written down. These two were the
    # literals ``"pass"`` and ``"fail"`` here -- unreachable while every check
    # above refuses first, and therefore never wrong, and therefore exactly the
    # shape of the defect this family's bundle carries today: a value that is
    # correct because someone typed the correct one. ``registration_evidence``
    # reads them, so a promotion built on them would be declaring its control
    # outcomes with more steps. ``_single`` is the sibling surface's, and returns
    # ``not_available`` -- a real value in the evidence model -- when a group of
    # controls disagrees.
    observed = {control.label: attestations[control.label].verdict
                for control in CONTROLS}
    return {
        "clean_control_verdict": _single(
            [observed[item.label] for item in CONTROLS
             if item.role == "reference"]),
        "negative_control_verdict": _single(
            [observed[item.label] for item in CONTROLS
             if item.role != "reference"]),
        "observed_verdicts": dict(sorted(observed.items())),
        "negative_control_grounds": dict(sorted(grounds.items())),
        "distinct_negative_grounds": sorted(set(grounds.values())),
    }


def run_control_sequence(
    *,
    manifest: HarnessManifestV1,
    container_root: Path,
    working_root: Path,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    """Run every control through the pinned container; return what was observed.

    Nothing about the outcome is decided here.
    """
    if not container_root.is_absolute() or container_root.is_symlink() \
            or not container_root.is_dir():
        raise ControlSequenceError(
            "the pinned container root must be an absolute real directory; "
            "running this instrument outside its image is not a fallback, it is "
            "a different measurement")

    current = NativePerfDriver().identity()["driver_digest"]
    if current != manifest.driver.sha256:
        raise ControlSequenceError(
            f"{manifest.id} pins driver bytes this repository no longer has, so "
            f"nothing measured here would describe the registered instrument. "
            f"Run from a clean worktree at the pinned commit, or re-pin with "
            f"repin_and_promote_harness.py and commit first")

    # BEFORE FOUR CONTAINER LAUNCHES RATHER THAN INSIDE THE FIRST. A timed
    # verdict is a statement about a machine and this manifest pins which one;
    # ``prepare`` enforces it, but only once a request exists.
    pinned = dict(manifest.registered_placement or {})
    here = measurement_placement()
    differs = {key: (pinned[key], here.get(key)) for key in sorted(pinned)
               if here.get(key) != pinned[key]}
    if differs:
        raise ControlSequenceError(
            f"this is not the placement {manifest.id} pins: {differs}. Its "
            f"evidence describes that machine, and a timed control run "
            f"elsewhere would attest to a different one")

    problem = load_problem(manifest.oracle.revision)
    logical_name = problem.definition.score_inputs[0]
    contract = build_control_contract(manifest)
    environment = EnvironmentSnapshotV1.create(
        resource_types=("cpu", "process"),
        features=tuple(manifest.resources.features),
        transports=("local-process",),
        network_classes=(manifest.network_policy,),
        metadata={
            "architecture": platform.machine(),
            "container_digest": manifest.container.resolved_digest,
            "container_runtime": manifest.container.reference.split(":", 1)[0],
            "kernel_release": platform.release(),
        },
    )
    placeholder = canonical_digest({"phase": "pre-registration", "id": manifest.id})
    catalog = build_harness_catalog_snapshot(
        catalog_source_revision="gemm-performance-registration/v1",
        property_vocabulary_digest=contract.property_vocabulary_digest,
        driver_protocol_version="ari.harness-driver/v1",
        manifests=(manifest,),
        registration_report_digests={manifest.id: placeholder},
        registration_evidence_digests={manifest.id: placeholder},
        promotion_approval_digests={manifest.id: placeholder},
    )
    suite = resolve_harness_suite(
        contract=contract, catalog=catalog, environment=environment)
    if suite.unsatisfied_atom_digests:
        raise ControlSequenceError(
            f"{len(suite.unsatisfied_atom_digests)} contract atom(s) are not "
            f"covered by {manifest.id}; the sequence would attest to less than "
            f"it claims")
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
        executions.append({
            "attempt_id": request.attempt_id,
            "attestation_digest": attestation.attestation_digest,
            "completed_at": result.completed_at,
            "container_digest": manifest.container.resolved_digest,
            "container_identity_digest": (
                request.execution_request.container.digest
                if request.execution_request.container is not None else None),
            "cpu_core_seconds": wall * manifest.resources.cpu_cores,
            "execution_identity": result.execution_identity,
            "execution_result_digest": canonical_digest(result),
            "execution_status": result.status,
            "memory_byte_seconds": wall * manifest.resources.memory_bytes,
            "network": request.execution_request.network,
            "pricing_status": "unpriced",
            "started_at": result.started_at,
            "tier": request.property_atoms[0].tier,
            "wall_seconds": wall,
        })
        for artifact in result.artifacts:
            payload = request.execution_request.workspace.read_bytes(
                artifact.relative_path, max_bytes=result.limits.max_output_bytes)
            logs[request.node_id.replace("registration-", "") + "-"
                 + artifact.logical_role
                 + Path(artifact.relative_path).suffix] = payload

    verifier = FixedVerifier(
        {PERF_DRIVER_REVISION: NativePerfDriver()},
        executor=PinnedContainerExecutor(package_root=ARI_CORE),
        execution_observer=observe,
    )
    previous_root = os.environ.get("ARI_HARNESS_CONTAINER_ROOT")
    os.environ["ARI_HARNESS_CONTAINER_ROOT"] = str(container_root)
    attestations: dict[str, Any] = {}
    provenance: dict[str, str] = {}
    target_digests: dict[str, tuple[str, str]] = {}
    try:
        for control in CONTROLS:
            candidate_root = working_root / control.label / "candidate"
            execution_root = working_root / control.label / "verification"
            candidate_root.mkdir(parents=True)
            execution_root.mkdir(parents=True)
            origin, payload = candidate_source(manifest, control.role)
            provenance[control.label] = origin
            (candidate_root / logical_name).write_bytes(payload)
            workspace = WorkspaceRefV1(root=str(candidate_root))
            declaration = build_declaration(manifest, workspace, logical_name)
            request = build_native_harness_run_request(
                run_id=contract.run_id,
                node_id="registration-" + control.label,
                epoch_id="registration-epoch",
                workspace=workspace,
                execution_workspace=WorkspaceRefV1(root=str(execution_root)),
                declaration=declaration,
                manifest=manifest,
                locked=baseline.harnesses[0],
                baseline=baseline,
                tier=control.tier,
                retry_index=control.retry_index,
            )
            attestations[control.label] = verifier.run(
                manifest=manifest,
                request=request,
                baseline_lock=baseline,
                research_contract_digest=contract.research_contract_digest,
                verification_contract_digest=contract.contract_digest,
                knowledge_skill_use_digest=canonical_digest(
                    "registration-no-knowledge"),
                capability_binding_lock_digest=canonical_digest(
                    "registration-no-provider"),
                producer_epoch_id="registration-epoch",
            )
            target_digests[control.label] = (
                declaration.target_digest, workspace.file_digest(logical_name))
    finally:
        if previous_root is None:
            os.environ.pop("ARI_HARNESS_CONTAINER_ROOT", None)
        else:
            os.environ["ARI_HARNESS_CONTAINER_ROOT"] = previous_root

    incomplete = sorted(item["attempt_id"] for item in executions
                        if item["execution_status"] != "completed")
    if incomplete:
        raise ControlSequenceError(
            f"{len(incomplete)} execution(s) did not complete; a control that "
            f"did not run is not a control")
    checked = check_control_sequence(attestations)
    isolation = isolation_findings(
        manifest, executions=executions, target_digests=target_digests,
        attestations=attestations)

    sequence: dict[str, Any] = {
        "schema_version": "ari.harness-control-sequence/v1",
        "harness_id": manifest.id,
        "harness_version": manifest.version,
        "manifest_digest": manifest.manifest_digest,
        "driver_revision": manifest.driver.revision,
        "driver_digest": manifest.driver.sha256,
        "container_digest": manifest.container.resolved_digest,
        "container_reference": manifest.container.reference,
        "problem_revision": manifest.oracle.revision,
        "problem_digest": manifest.oracle.sha256,
        "dataset_revision": manifest.dataset.revision,
        "dataset_digest": manifest.dataset.sha256,
        "verification_contract_digest": contract.contract_digest,
        "baseline_lock_digest": baseline.lock_digest,
        "environment_digest": environment.identity_digest,
        "registered_placement": dict(sorted(pinned.items())),
        "target_logical_name": logical_name,
        "runs": [
            {
                "label": control.label,
                "candidate_provenance": provenance[control.label],
                "tier": control.tier,
                "retry_index": control.retry_index,
                "required_verdict": control.verdict,
                "observed_verdict": attestations[control.label].verdict,
                "required_ground": control.ground,
                "observed_ground": _ground_of(attestations[control.label]),
                "observed_property_verdicts": dict(
                    sorted(property_map(attestations[control.label]).items())),
                "attempt_id": attestations[control.label].attempt_id,
                "attestation_digest":
                    attestations[control.label].attestation_digest,
                "why": control.why,
            }
            for control in CONTROLS
        ],
        **checked,
        **isolation,
    }

    artifacts: dict[str, bytes] = {
        f"{label}.attestation.json": _json_bytes(attestation)
        for label, attestation in attestations.items()
    }
    for name, payload in logs.items():
        artifacts[f"logs/{name}"] = payload
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
    artifacts["control_sequence.json"] = _json_bytes(sequence)

    return ({"sequence": sequence, "attestations": attestations,
             "executions": executions}, artifacts)


def controls(args: argparse.Namespace) -> int:
    """Run the sequence and write its artifacts. No signature, no repo write."""
    manifest = load_manifest(BUILTIN / args.manifest)
    output = args.output_dir.resolve()
    if output.is_relative_to(HARNESS_ROOT):
        raise ControlSequenceError(
            "refusing to write into the registered Harness tree: an evidence "
            "bundle whose digests carry a signature is not a scratch directory")
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ari-gemm-performance-") as scratch:
        result, artifacts = run_control_sequence(
            manifest=manifest,
            container_root=args.container_root.resolve(strict=True),
            working_root=Path(scratch) / "runs",
        )
    refuse_host_identity(artifacts)
    _write_bundle(output, artifacts)
    sequence = result["sequence"]
    for run in sequence["runs"]:
        print(f"{run['label']:<24} {run['observed_verdict']:<5} "
              f"ground={run['observed_ground']}")
    print(f"distinct negative grounds : {sequence['distinct_negative_grounds']}")
    print(f"artifacts                 : {len(artifacts)}")
    return 0


def promote(args: argparse.Namespace) -> int:
    """Run the sequence, earn the gates, and sign the re-registration.

    WHY THE FAMILY HAD NOTHING LIKE THIS. ``repin_and_promote_harness.py``'s
    ``promote`` was closed because it declared evidence it never ran, and the
    surface above only ever wrote a scratch bundle -- so nothing in this
    repository could RE-register ``hpc/gemm-performance``, and its catalog row
    could not be renewed after a re-pin moved its manifest digest. This is that
    surface, and it is the same shape as
    ``attest_problem_correctness.promote``: the differences below are the ones
    the performance family forces, and nothing else.

    AN AUTHENTICATED HUMAN-MAINTAINER SURFACE. ``--actor-id`` and
    ``--authorization-basis`` are a person's identity and what they actually
    saw; an agent that supplies them is forging both. The capability is
    ``controls``.

    THE ORDER IS THE ARGUMENT, not tidiness:

    * the stale-pin question is asked FIRST, because a manifest pinning bytes
      this repository no longer has cannot be re-registered at all and the
      answer costs nothing -- asked after the container work it arrives five
      executions late;
    * the sequence runs SECOND, so the gates are asked about an instrument that
      was just seen to discriminate;
    * the gates run THIRD and refuse a dirty tree, and the parity probe behind
      them refuses a node its own clean control did not resolve on;
    * NOTHING is written until both have passed, because the first write dirties
      the tree ``repository_commit`` takes the source pin from.

    AND EVERY PUBLISHED BYTE GOES THROUGH ONE GUARD AND ONE WRITE. The evidence
    bundle, the registration evidence, the registration report, the promotion
    approval and the catalog are one map, guarded once by
    ``refuse_host_identity`` and written once -- so the guard's coverage is a
    property of this function's shape rather than of the order of its
    statements.

    A REJECTED REGISTRATION WRITES NOTHING and is reported as a result. On this
    family that is the expected outcome on a machine whose cases are too small
    to resolve: the instrument refusing to certify a measurement it could not
    make is the instrument working.
    """
    from ari.assurance.drivers import builtin_driver_map
    from ari.assurance.native_perf_common import measurement_environment
    from ari.orchestrator.node_summary_view import scrub_host_identity
    from repin_and_promote_harness import _slug, stale_pins

    manifest = load_manifest(BUILTIN / args.manifest)
    stale = stale_pins(manifest)
    if stale:
        print(f"REFUSED: {manifest.id} pins {sorted(stale)} the code no longer "
              f"has. Re-pin with repin_and_promote_harness.py, commit, re-run.")
        return 3

    with tempfile.TemporaryDirectory(prefix="ari-gemm-performance-") as scratch:
        result, artifacts = run_control_sequence(
            manifest=manifest,
            container_root=args.container_root.resolve(strict=True),
            working_root=Path(scratch) / "runs",
        )

    driver = builtin_driver_map()[manifest.driver.revision]
    report = register_harness(manifest, driver, runs=args.runs, allow_dirty=False)
    for gate in report.gates:
        if not gate.passed:
            print(f"  FAIL {gate.gate_id}: {gate.detail[:96]}")
    if report.decision != "eligible-for-verified":
        print("REFUSED: nothing is written; a rejected registration is a result")
        return 4
    commit = repository_commit(allow_dirty=False)

    probe = driver.parity_probe(manifest)
    # SCRUBBED BEFORE THE DIGEST, not after. Rewriting the values here and
    # leaving the digest alone published a hash of the values that had just been
    # replaced -- a confirmation oracle for the host path, beside a note saying
    # the values were scrubbed.
    environment = measurement_environment(scrub=scrub_host_identity)
    sequence = result["sequence"]
    artifacts["registration_report.json"] = _json_bytes(report)
    artifacts["gate_findings.json"] = _json_bytes(
        {gate.gate_id: {"passed": gate.passed, "detail": gate.detail}
         for gate in report.gates})
    artifacts["official_runner_parity.json"] = _json_bytes(probe)
    artifacts["multiple_run_stability.json"] = _json_bytes(
        {"runs": args.runs, "clean_control": (probe.get("controls") or {}).get("clean")})
    # THE PLACEMENT IS READ FROM THIS MACHINE, on the keys the manifest pins.
    # A timed verdict is a statement about a machine, so unlike the correctness
    # sibling -- which pins none and says so -- this record has one to make, and
    # ``run_control_sequence`` refused before the first launch unless every
    # pinned key matched here. Both the value and the note are derived, because
    # a perf manifest that pinned nothing would otherwise ship a sentence
    # claiming a machine its evidence never described.
    pinned = sequence["registered_placement"]
    here = measurement_placement()
    artifacts["measurement_environment.json"] = _json_bytes({
        "environment": environment,
        "registration_commit": commit,
        "placement": {key: here.get(key) for key in sorted(pinned)} or None,
        "placement_note": (
            "a timed verdict is a statement about a machine; these are the keys "
            "the manifest pins, read from the machine the controls ran on, and "
            "the sequence refused before its first launch unless they matched"
            if pinned else
            "this harness pins no placement, so its evidence does not describe "
            "a machine"),
        "environment_note": "variable VALUES are scrubbed of host identity here",
    })
    harness_root = args.harness_root.resolve()
    slug = _slug(manifest.id)
    evidence_dir = harness_root / "evidence" / slug

    digests = {f"evidence/{slug}/{name}": bytes_digest(payload)
               for name, payload in artifacts.items()}
    evidence = HarnessRegistrationEvidenceV1.create(
        harness_id=manifest.id,
        harness_version=manifest.version,
        manifest_digest=manifest.manifest_digest,
        source_full_commit_sha=commit,
        environment_digest=sequence["environment_digest"],
        evidence_artifact_digests=dict(sorted(digests.items())),
        # THE REAL ATTESTATIONS. The bundle on disk today points this field at
        # its own registration report's digest -- one entry, citing itself as
        # the execution it never performed. These are five container runs.
        attestation_digests=tuple(sorted(
            item.attestation_digest for item in result["attestations"].values())),
        # OBSERVED, every one of them. The seven values this family's bundle
        # carries today were typed: two control verdicts, parity, schema
        # conformance and three isolation claims. Here the two verdicts come
        # from ``check_control_sequence``'s read of the attestations, parity
        # from the probe this call ran, and the remaining four from
        # ``isolation_findings``' derivation over what each request carried and
        # what each run returned.
        clean_control_verdict=sequence["clean_control_verdict"],
        negative_control_verdict=sequence["negative_control_verdict"],
        official_runner_parity=bool(probe.get("passed")),
        result_schema_conformant=sequence["result_schema_conformant"],
        network_isolation=sequence["network_isolation"],
        target_write_isolation=sequence["target_write_isolation"],
        oracle_visibility=sequence["oracle_visibility"],
        run_count=len(result["attestations"]),
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
    catalog_path = harness_root / "catalog.yaml"
    catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    entry = {
        "id": manifest.id,
        "manifest": f"builtin/{args.manifest}",
        "registration_report": f"reports/{slug}.registration.json",
        "registration_report_digest": report.report_digest,
        "registration_evidence": f"evidence/{slug}/registration_evidence.json",
        "registration_evidence_digest": evidence.evidence_digest,
        "promotion_approval": f"approvals/{slug}.approval.json",
        "promotion_approval_digest": approval.approval_digest,
    }
    catalog["entries"] = sorted(
        [item for item in catalog["entries"] if item["id"] != manifest.id] + [entry],
        key=lambda item: item["id"])
    # THE LABEL MOVES WITH THE CONTENT IT NAMES. catalog_source_revision is read
    # verbatim and compared against nothing, so it moved only when a human
    # retyped it -- and a promotion that rewrites four digests under an unchanged
    # label leaves one revision string naming two catalogs, which is exactly what
    # test_harness_catalog_revision.py was written after finding on this tree.
    # promote_native_harnesses.py already mints it this way; this is the same
    # act, performed by the surface that actually cuts the new catalog.
    catalog["catalog_source_revision"] = f"ari-harness-catalog/1@{commit}"

    # NOTHING HAS BEEN WRITTEN YET. Everything above is computation, so the
    # guard below sees the complete set of bytes this mode puts into a published
    # tree. It refuses rather than scrubs: a scrub leaves a clean-looking bundle
    # and no way to tell which artifact leaked, and the leak recurs next run.
    published = published_artifacts(
        slug=slug, artifacts=artifacts, evidence=evidence, report=report,
        approval=approval, catalog=catalog)
    refuse_host_identity(published)
    _write_bundle(harness_root, published)

    print(f"attested  : {len(result['attestations'])} container executions")
    print(f"grounds   : {sequence['distinct_negative_grounds']}")
    print(f"signed    : {approval.actor_id} ({approval.actor_kind})")
    print(f"written   : {evidence_dir}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="mode", required=True)
    run = sub.add_parser(
        "controls",
        help="run the control sequence and write its attestations; no signature")
    run.add_argument("--manifest", default="hpc_gemm_performance.yaml")
    run.add_argument("--container-root", type=Path, required=True)
    run.add_argument("--output-dir", type=Path, required=True)
    run.set_defaults(func=controls)

    promoter = sub.add_parser(
        "promote",
        help="run the sequence, earn the gates and sign the re-registration")
    promoter.add_argument("--container-root", type=Path, required=True,
                          help="the private directory holding the pinned SIF")
    promoter.add_argument("--manifest", default="hpc_gemm_performance.yaml")
    promoter.add_argument("--actor-id", required=True,
                          help="the human maintainer authorizing the promotion")
    promoter.add_argument("--authorization-basis", required=True,
                          help="what the maintainer actually saw. A basis "
                               "claiming a review that did not happen is the "
                               "defect the signature exists to prevent.")
    promoter.add_argument("--approved-date", required=True)
    promoter.add_argument("--runs", type=int, default=3,
                          help="parity-probe repetitions behind the stability "
                               "gate; fewer than two cannot show stability")
    promoter.add_argument("--harness-root", type=Path, default=HARNESS_ROOT,
                          help="where the bundle, report, approval and catalog "
                               "row are written. Defaults to the repository's "
                               "config/harnesses; point it at a copy to "
                               "rehearse the write path first.")
    promoter.set_defaults(func=promote)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ControlSequenceError as exc:
        print(f"REFUSED: {exc}")
        return 5


if __name__ == "__main__":
    raise SystemExit(main())
