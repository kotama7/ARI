"""Task 20 section 8 criteria about what the COMPLETED K/C/A layer contains.

``test_kca_acceptance.py`` binds the criteria that are refusals.  The four
here are different in kind: each says something about the finished layer as a
whole -- what every trust anchor must look like, what the Kernel may read,
what a node must carry, and what the compatibility path must NOT leave behind.

* 45 ``test_kernel_procedural_only``
* 49 ``test_full_sha256_trust_anchors``
* 51 ``test_simple_bfts_assurance_off_artifacts``
* 64 ``test_node_kca_provenance_complete``

A criterion of that shape is exactly the one a test can pretend to cover, by
naming a handful of the places it holds and calling the set complete.  Every
inventory below is therefore DERIVED -- from the published contract surface,
from the model's own fields, from the driver registry, from the bridge modules'
own assignments -- and every derivation carries a floor that fails if it ever
comes back empty, because an empty inventory makes each of these tests pass
while checking nothing.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import sys
import types
import typing
from pathlib import Path

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError

from ari.assurance.models import (
    BaselineHarnessLockV1,
    ContainerPinV1,
    HarnessManifestV1,
    HarnessPropertyCoverageV1,
    HarnessPropertyResultV1,
    HarnessRequirementV1,
    HarnessResourceRequirementsV1,
    HarnessRunRequestV1,
    LockedHarnessV1,
    PinnedHarnessAssetV1,
    VerificationContractV1,
    VerificationRequirementV1,
    VerificationScopeV1,
)
from ari.assurance.catalog import build_harness_catalog_snapshot
from ari.assurance.drivers import builtin_driver_map
from ari.assurance.runner import FixedVerifier
from ari.execution import ExecutionRequestV1, WorkspaceRefV1
from ari.research_contract import ResearchArtifactRefV1
from ari.rqgm import kernel_rules
from ari.rqgm.admission import ADMISSION_FILENAME, ADMISSION_RELATIVE_DIR
from ari.rqgm.kernel import ConstitutionalKernel


SHA = "sha256:" + "1" * 64
TOLERANCE_SHA = "sha256:" + "2" * 64
TARGET_SHA = "sha256:" + "5" * 64
HARNESS_ID = "hpc/gemm-correctness"


# ── criterion 49: every new trust anchor is a full SHA-256 ──────────────────

#: The three published K/C/A contract surfaces.  A record only becomes a trust
#: anchor for anyone else once it crosses one of these, and a record added to
#: one joins the inventory below without this file being edited.
KCA_SURFACES = (
    "ari.public.knowledge",
    "ari.public.capability_binding",
    "ari.public.assurance",
)

#: "All *new* trust anchors" (Task 16 section 9 invariant 1).  New means the
#: three packages Tasks 16-18 added; ``ari.execution`` and
#: ``ari.research_contract`` are the pre-existing contracts Task 18 section 2
#: says the runner REUSES, and their digest fields predate the invariant.
KCA_PACKAGES = ("ari.knowledge", "ari.capability_binding", "ari.assurance")


def _nested_models(annotation) -> list[type[BaseModel]]:
    found: list[type[BaseModel]] = []
    stack = [annotation]
    while stack:
        current = stack.pop()
        if inspect.isclass(current) and issubclass(current, BaseModel):
            found.append(current)
            continue
        stack.extend(typing.get_args(current))
    return found


def _kca_contract_models() -> dict[str, type[BaseModel]]:
    """Every model reachable from the published K/C/A contract surfaces."""

    frontier: list[type[BaseModel]] = []
    for surface in KCA_SURFACES:
        module = importlib.import_module(surface)
        for name in getattr(module, "__all__", ()) or vars(module):
            value = getattr(module, name, None)
            if inspect.isclass(value) and issubclass(value, BaseModel):
                frontier.append(value)
    reached: dict[str, type[BaseModel]] = {}
    while frontier:
        model = frontier.pop()
        key = f"{model.__module__}.{model.__name__}"
        if key in reached:
            continue
        reached[key] = model
        for field in model.model_fields.values():
            frontier.extend(_nested_models(field.annotation))
    return {
        key: model
        for key, model in reached.items()
        if model.__module__.split(".")[1] in {p.split(".")[1] for p in KCA_PACKAGES}
        and model.__module__.startswith(tuple(f"{p}." for p in KCA_PACKAGES))
    }


def _is_anchor_name(name: str) -> bool:
    """A field NAME that declares the value is a digest ARI trusts.

    Kept, and no longer the only selector -- see ``_anchor_fields``. Selecting
    an inventory of trust anchors by the SUFFIX of its name misses every anchor
    named for its ROLE rather than its mechanism, and there was one: measured,
    ``HarnessAttestationV1.execution_identity`` carries
    ``Field(pattern=SHA256_DIGEST_PATTERN)`` and is invisible to this, so
    deleting that constraint left the criterion's test green while the field
    then accepted "" and "a" * 12.
    """

    lowered = name.lower()
    return (
        lowered.endswith(("digest", "digests", "hash", "hashes"))
        or "sha256" in lowered
    )


#: Trust anchors named for their ROLE rather than their mechanism, so the name
#: rule below cannot see them. PINNED BY NAME, deliberately, and not derived
#: from the constraint being present.
#:
#: Deriving this from `Field(pattern=...)` looks better and is worse: the
#: inventory then shrinks exactly when the mechanism does, so DELETING the
#: constraint removes the field from the inventory and the test goes green on
#: the defect it exists to catch. Measured -- that version passed with
#: `execution_identity`'s constraint deleted, which is the same self-defeating
#: derivation this file's criterion-35 sibling had.
#:
#: A list is the right shape here BECAUSE it is a classification and not a
#: coverage claim: a new anchor whose name does not announce it has to be added
#: here by hand, which is the deliberate act, and `_no_stale_role_anchors`
#: below fails if one is renamed or removed.
_ROLE_NAMED_ANCHORS = {
    ("ari.assurance.models.HarnessAttestationV1", "execution_identity"):
        "ties an Attestation to the execution it is about",
    ("ari.knowledge.models.KnowledgeSkillEntryV1", "body_store_key"):
        "the key a Skill BODY is fetched by",
}


def _is_role_named_anchor(key: str, name: str) -> bool:
    return (key, name) in _ROLE_NAMED_ANCHORS


#: Task 16 section 9 invariant 1 keeps ONE carve-out: "Existing RQGM ``hash12``
#: identifiers remain compatibility/display keys only."  In the source those
#: are exactly the prompt-hash fields, and the test asserts that below rather
#: than trusting the rule.
def _is_hash12_compatibility(name: str) -> bool:
    return "prompt_hash" in name.lower()


def _kca_anchor_fields() -> list[tuple[str, str, object]]:
    """(model key, field name, validating adapter) for every K/C/A anchor."""

    anchors: list[tuple[str, str, object]] = []
    for key, model in sorted(_kca_contract_models().items()):
        for name, field in model.model_fields.items():
            # TWO SELECTORS, because either alone has a blind spot. The NAME
            # finds an anchor that ought to carry the constraint and does not
            # -- which is the defect the criterion is about. The CONSTRAINT
            # finds an anchor named for its role rather than its mechanism,
            # which the name misses entirely: `execution_identity` was one.
            if not (_is_anchor_name(name) or _is_role_named_anchor(key, name)):
                continue
            if _is_hash12_compatibility(name):
                continue
            annotated = field.annotation
            if field.metadata:
                annotated = typing.Annotated[tuple([annotated, *field.metadata])]
            anchors.append((key, name, TypeAdapter(annotated)))
    return anchors


def _unwrap(annotation):
    """Strip ``Annotated`` and the ``| None`` an optional anchor declares."""

    while True:
        origin = typing.get_origin(annotation)
        if origin is typing.Annotated or (
            hasattr(typing, "get_origin") and str(origin) == "typing.Annotated"
        ):
            annotation = typing.get_args(annotation)[0]
            continue
        if origin in (typing.Union, types.UnionType):
            inner = [a for a in typing.get_args(annotation) if a is not type(None)]
            if len(inner) == 1:
                annotation = inner[0]
                continue
        return annotation


def _shaped(annotation, value):
    """*value* wrapped in whatever container the field declares, or ``None``."""

    annotation = _unwrap(annotation)
    origin = typing.get_origin(annotation)
    if origin is None:
        return value if annotation is str else None
    args = [_unwrap(a) for a in typing.get_args(annotation)]
    if origin is tuple and args and args[0] is str:
        return (value,)
    if origin in (list, set, frozenset) and args and args[0] is str:
        return origin([value])
    if origin is dict and len(args) == 2 and args[1] is str:
        return {"artifact": value}
    return None


#: Every way a value can fail to be ``sha256:<64 lowercase hex>``, read off the
#: pattern the codebase already enforces on its scalar anchors.
NOT_FULL_SHA256 = (
    "",
    "a" * 12,
    "1" * 64,
    "sha256:" + "A" * 64,
    "sha256:" + "a" * 63,
    "sha256:" + "a" * 65,
    "sha256:" + "g" * 64,
)
FULL_SHA256 = "sha256:" + "a" * 64


def test_full_sha256_trust_anchors():
    """Criterion 49 -- no anchor on the published K/C/A contract graph accepts
    anything but a full ``sha256:<64 lowercase hex>``.

    The mechanism is ``Field(pattern=SHA256_DIGEST_PATTERN)`` and the
    ``Sha256Digest`` alias that carries the same pattern INSIDE a collection.
    That second half is what was missing: a scalar ``manifest_digest`` was
    pinned while ``covered_atom_digests``, ``harness_manifest_digests``,
    ``attestation_digests``, ``ordered_knowledge_skill_hashes`` and the
    ``dict[str, str]`` digest maps were declared as bare strings, so
    ``HarnessPropertyResultV1(covered_atom_digests=("a" * 12,))`` was accepted
    and a truncated ``hash12`` could stand in for an anchor the Kernel compares.

    The inventory is walked from the three public surfaces, so this cannot
    quietly cover a subset: a record reachable from ``ari.public.assurance``
    with an unconstrained digest field fails here whether or not anyone
    remembered to add it.
    """

    models = _kca_contract_models()
    packages = {key.split(".")[1] for key in models}
    assert packages == {p.split(".")[1] for p in KCA_PACKAGES}, packages

    anchors = _kca_anchor_fields()
    assert len(anchors) > len(models), (len(anchors), len(models))

    # The floor for the class of defect this criterion is about: anchors that
    # live INSIDE a container.  If that set ever comes back empty the loop below
    # still passes while checking nothing that was ever broken.
    collections = [
        (key, name)
        for key, name, _ in anchors
        if typing.get_origin(_unwrap(_annotation_of(models, key, name)))
        in (tuple, list, set, frozenset, dict)
    ]
    assert len(collections) > 10, collections

    unconstrained: list[str] = []
    unreachable: list[str] = []
    for key, name, adapter in anchors:
        annotation = _annotation_of(models, key, name)
        good = _shaped(annotation, FULL_SHA256)
        if good is None:
            unreachable.append(f"{key}.{name}: {annotation!r}")
            continue
        adapter.validate_python(good)
        for bad in NOT_FULL_SHA256:
            try:
                adapter.validate_python(_shaped(annotation, bad))
            except ValidationError:
                continue
            unconstrained.append(f"{key}.{name} accepts {bad!r}")
    assert not unconstrained, unconstrained
    assert not unreachable, unreachable


def _annotation_of(models, key: str, name: str):
    return models[key].model_fields[name].annotation


def test_hash12_carve_out_is_only_prompt_identifiers():
    """The one carve-out invariant 1 grants, pinned so it cannot widen.

    Every field skipped by ``test_full_sha256_trust_anchors`` must be an
    existing RQGM prompt identifier.  Anything else skipped there would be a
    trust anchor silently exempted from the criterion.
    """

    exempt = [
        (key, name)
        for key, model in sorted(_kca_contract_models().items())
        for name in model.model_fields
        if _is_anchor_name(name) and _is_hash12_compatibility(name)
    ]
    assert exempt, "the carve-out matched nothing; the skip rule has gone stale"
    assert all("prompt_hash" in name for _, name in exempt), exempt
    # And the composition identity is NOT in the carve-out: Task 16 section 17
    # says the composition identity and all new anchors use full SHA-256, so
    # the ordered Skill hashes must be constrained like any other anchor.
    from ari.knowledge.models import InstructionCompositionV1

    adapter = TypeAdapter(
        InstructionCompositionV1.model_fields["ordered_knowledge_skill_hashes"].annotation
    )
    with pytest.raises(ValidationError):
        adapter.validate_python(("a" * 12,))


# ── criterion 45: the Kernel checks procedure, never scientific truth ───────


def _asset(revision: str) -> PinnedHarnessAssetV1:
    return PinnedHarnessAssetV1(revision=revision, sha256=SHA, license="MIT")


def _manifest() -> HarnessManifestV1:
    return HarnessManifestV1.create(
        id=HARNESS_ID,
        version="1.0.0",
        kind="artifact_verifier",
        status="verified",
        description="GEMM correctness verifier",
        maintainer="ari",
        tags=("hpc",),
        subject_types=("program",),
        target_kinds=("shared-library",),
        accepts_external_target=True,
        supported_languages=("c",),
        supported_hardware=("cpu",),
        supported_architectures=("x86_64",),
        supported_dtypes=("float64",),
        supported_domains=("gemm",),
        properties=(
            HarnessPropertyCoverageV1(
                property_id="numerical-equivalence",
                methods=("differential-testing",),
                tiers=("certify",),
                scope=VerificationScopeV1(values={"dtype": ("float64",)}),
                tolerance_policy_digest=TOLERANCE_SHA,
            ),
        ),
        target_interface_contract="gemm-c-abi/v1",
        target_interface_digest=SHA,
        source_repository="https://example.invalid/harness",
        source_full_commit_sha="4" * 40,
        implementation_license="MIT",
        dataset=_asset("dataset-v1"),
        oracle=_asset("oracle-v1"),
        driver=_asset("native-v1"),
        model=_asset("none"),
        container=ContainerPinV1(
            reference="example.invalid/harness@sha256:4",
            resolved_digest=SHA,
            license="MIT",
        ),
        network_policy="deny",
        credential_policy="none",
        filesystem_policy="isolated-readonly-target",
        resources=HarnessResourceRequirementsV1(
            cpu_cores=1, memory_bytes=1024, accelerators=0, disk_bytes=1024
        ),
        timeout_seconds=60,
        scorer_determinism="deterministic",
        nondeterminism_declaration="none",
        hidden_test_policy="verifier-only",
        oracle_independence="independent",
        tolerance_policy_digest=TOLERANCE_SHA,
        expected_result_schema="ari.native-hpc-result/v1",
        expected_result_schema_digest=SHA,
        infrastructure_failure_policy="separate",
        retry_limit=1,
        negative_control_report_digest=SHA,
        upstream_parity_report_digest=SHA,
    )


def _atom() -> HarnessRequirementV1:
    return HarnessRequirementV1.create(
        verification_requirement_digest=SHA,
        property_id="numerical-equivalence",
        method="differential-testing",
        tier="certify",
        target_kind="shared-library",
        scope=VerificationScopeV1(values={"dtype": ("float64",)}),
        tolerance_policy_digest=TOLERANCE_SHA,
        independence_requirement="independent",
        determinism_requirement="deterministic",
        source_requirement_refs=("research:metric",),
    )


def _contract() -> VerificationContractV1:
    requirement = VerificationRequirementV1.create(
        property_id="numerical-equivalence",
        target_kind="shared-library",
        required_methods=("differential-testing",),
        required_tier="certify",
        failure_policy="exclude-from-scientific-frontier",
        scope=VerificationScopeV1(values={"dtype": ("float64",)}),
        tolerance_policy_ref="hpc.float64/v1",
        tolerance_policy_digest=TOLERANCE_SHA,
        source_requirement_refs=("research:metric",),
    )
    return VerificationContractV1.create(
        run_id="run-1",
        research_contract_digest=SHA,
        requirements=(requirement,),
        admission_confidence=1.0,
        property_vocabulary_digest=SHA,
    )


def _coherent_state(root: Path):
    """A Harness state in which every procedural fact agrees with every other."""

    manifest = _manifest()
    atom = _atom()
    locked = LockedHarnessV1(
        harness_id=manifest.id,
        version=manifest.version,
        kind=manifest.kind,
        manifest_digest=manifest.manifest_digest,
        dataset_digest=manifest.dataset.sha256,
        oracle_digest=manifest.oracle.sha256,
        driver_digest=manifest.driver.sha256,
        container_digest=manifest.container.resolved_digest,
        result_schema_digest=manifest.expected_result_schema_digest,
        tolerance_policy_digest=manifest.tolerance_policy_digest,
        covered_atom_digests=(atom.atom_digest,),
    )
    contract = _contract()
    baseline = BaselineHarnessLockV1.create(
        run_id="run-1",
        research_contract_digest=SHA,
        verification_contract_digest=contract.contract_digest,
        harness_catalog_snapshot_digest=SHA,
        verification_environment_digest=SHA,
        oracle_bundle_digest=SHA,
        suite_digest=SHA,
        requirements=(atom,),
        harnesses=(locked,),
        coverage_proof_digest=SHA,
    )
    workspace = WorkspaceRefV1(root=str(Path(root) / "verification-workspace"))
    Path(workspace.root).mkdir(parents=True, exist_ok=True)
    Path(workspace.root).joinpath("candidate.so").write_bytes(b"candidate")
    request = HarnessRunRequestV1.create(
        run_id="run-1",
        node_id="node_001",
        epoch_id="epoch_000",
        active_harness_lock_digest=baseline.lock_digest,
        harness=locked,
        target_workspace=workspace,
        target_artifact=ResearchArtifactRefV1(
            logical_name="candidate.so",
            digest=TARGET_SHA,
            media_type="application/x-sharedlib",
            role="verification-target",
            source_run_id="run-1",
        ),
        target_logical_name="candidate.so",
        target_kind="shared-library",
        target_digest=TARGET_SHA,
        property_atoms=(atom,),
        execution_request=ExecutionRequestV1(
            workspace=workspace,
            argv=("/bin/true",),
            timeout_seconds=60,
            network="deny",
            request_id="attempt-1",
            input_digests={"candidate.so": TARGET_SHA},
        ),
        attempt_id="attempt-1",
        retry_index=0,
        expected_result_schema="ari.native-hpc-result/v1",
    )
    catalog = build_harness_catalog_snapshot(
        catalog_source_revision="acceptance",
        property_vocabulary_digest=SHA,
        driver_protocol_version="v1",
        manifests=(manifest,),
        registration_report_digests={manifest.id: SHA},
        registration_evidence_digests={manifest.id: SHA},
        promotion_approval_digests={manifest.id: SHA},
    ).model_dump(mode="json")
    return manifest, atom, locked, contract, baseline, request, catalog


def _science_payload_fields(model: type[BaseModel]) -> tuple[str, ...]:
    """The fields *model* declares as free-form MEASURED payload.

    Read off the annotation rather than named here: a ``dict[str, Any]`` on a
    property result is where a Harness records what it measured, and those are
    precisely the fields a Kernel would have to read to form a scientific
    opinion of its own.
    """

    return tuple(
        name
        for name, field in model.model_fields.items()
        if typing.get_origin(field.annotation) is dict
        and typing.get_args(field.annotation)[1] is typing.Any
    )


#: A recorded result that is scientifically indefensible: the measured error is
#: eleven orders of magnitude outside the tolerance and the oracle disagrees.
REFUTED = {
    "max_relative_error": 1.0e9,
    "tolerance": 1.0e-12,
    "within_tolerance": False,
    "oracle_agrees": False,
    "cases_failed": 33,
}
CONFIRMED = {
    "max_relative_error": 1.0e-15,
    "tolerance": 1.0e-12,
    "within_tolerance": True,
    "oracle_agrees": True,
    "cases_failed": 0,
}


def _property_result(request, *, verdict: str, science: dict) -> HarnessPropertyResultV1:
    payload = {
        name: dict(science)
        for name in _science_payload_fields(HarnessPropertyResultV1)
    }
    return HarnessPropertyResultV1(
        property_id="numerical-equivalence",
        method="differential-testing",
        tier="certify",
        tested_scope=VerificationScopeV1(values={"dtype": ("float64",)}),
        verdict=verdict,
        covered_atom_digests=tuple(
            item.atom_digest for item in request.property_atoms
        ),
        evidence_artifact_refs=(),
        **payload,
    )


def _attestation_for(
    *, request, baseline, manifest, contract, verdict="pass", science=None,
    results=None,
):
    from ari.assurance.models import HarnessAttestationV1

    return HarnessAttestationV1.create(
        run_id="run-1",
        node_id="node_001",
        epoch_id="epoch_000",
        producer_epoch_id="epoch_000",
        research_contract_digest=SHA,
        verification_contract_digest=contract.contract_digest,
        knowledge_skill_use_digest=SHA,
        capability_binding_lock_digest=SHA,
        baseline_harness_lock_digest=baseline.lock_digest,
        active_harness_lock_digest=request.active_harness_lock_digest,
        harness_manifest_digest=manifest.manifest_digest,
        driver_digest=manifest.driver.sha256,
        oracle_digest=manifest.oracle.sha256,
        dataset_digest=manifest.dataset.sha256,
        container_digest=manifest.container.resolved_digest,
        target_logical_name=request.target_logical_name,
        target_digest=request.target_digest,
        target_kind=request.target_kind,
        execution_identity=SHA,
        execution_result_digest=SHA,
        verdict=verdict,
        property_results=results
        or (
            _property_result(
                request,
                verdict=verdict,
                science=CONFIRMED if science is None else science,
            ),
        ),
        evidence_artifact_refs=(),
        infrastructure_status="ready",
        nondeterminism_declaration="none",
        nondeterminism_observations=(),
        attempt_id=request.attempt_id,
        retry_index=0,
    )


def _codes(**kwargs) -> set[str]:
    report = ConstitutionalKernel().validate_harness_integrity(**kwargs)
    return {violation.code for violation in report.violations}


def _harness_executing_modules() -> set[str]:
    """Every module that can actually RUN a Harness, from the registry itself.

    ``builtin_driver_map`` is the production driver registry, so a driver added
    to it joins this set without this test being edited.
    """

    modules = {FixedVerifier.__module__}
    modules.update(type(driver).__module__ for driver in builtin_driver_map().values())
    return modules


def _dotted_imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def test_kernel_procedural_only(tmp_path):
    """Criterion 45 -- the Kernel never recomputes a Harness verdict.

    ``docs/concepts/rqgm_architecture.md`` states the boundary this binds: the
    fixed ``CK-HAR-*`` checks "validate authority, binding, digests,
    monotonicity, and attestation scope; the kernel does not recompute
    scientific truth", and Task 18 section 1 says RQGM "governs actors that
    misuse those facts; it does not recompute them".

    Violating it means one of two things, and both are asserted here.  The
    Kernel could form its own opinion from the recorded numbers -- so every
    measured payload the result model declares is replaced with one that flatly
    refutes a recorded ``pass``, and the Kernel's findings must not move.  Or it
    could run the Harness itself -- so no module that can execute one, taken
    from the production driver registry, may appear anywhere in the Kernel's
    imports.

    The anti-vacuity half is the publication gate: with the SAME perfect
    measurements, flipping only the RECORDED verdict must add a blocking
    finding.  That is what says the Kernel reads the verdict at all, so a
    Kernel that had stopped reading anything would fail here rather than pass
    the two insensitivity assertions for free.
    """

    manifest, atom, locked, contract, baseline, request, catalog = _coherent_state(
        tmp_path
    )
    science_fields = _science_payload_fields(HarnessPropertyResultV1)
    assert science_fields, "the result model declares no measured payload"

    def kernel(attestation, **extra):
        return _codes(
            verification_contract=contract.model_dump(mode="json"),
            baseline_lock=baseline.model_dump(mode="json"),
            catalog_snapshot=catalog,
            attestation=attestation.model_dump(mode="json"),
            request=request.model_dump(mode="json"),
            current_target_digest=request.target_digest,
            active_harness_lock_digest=baseline.lock_digest,
            **extra,
        )

    confirmed = _attestation_for(
        request=request, baseline=baseline, manifest=manifest, contract=contract
    )
    baseline_codes = kernel(confirmed)
    assert baseline_codes == set(), baseline_codes

    # 1. The Kernel does not DEMOTE on the science.  One field at a time, then
    #    all of them together: a recorded pass whose own numbers refute it is
    #    still nothing the Kernel has an opinion about.
    for field in science_fields:
        results = (
            _property_result(request, verdict="pass", science=CONFIRMED)
            .model_copy(update={field: dict(REFUTED)}),
        )
        refuted = _attestation_for(
            request=request, baseline=baseline, manifest=manifest,
            contract=contract, results=results,
        )
        assert kernel(refuted) == baseline_codes, field
    all_refuted = _attestation_for(
        request=request, baseline=baseline, manifest=manifest, contract=contract,
        science=REFUTED,
    )
    assert kernel(all_refuted) == baseline_codes

    # 2. Nor at the publication gate, which is the one place a scientific
    #    recomputation would be most tempting.
    published = kernel(confirmed, publication=True)
    assert kernel(all_refuted, publication=True) == published

    # 3. But it DOES read the recorded verdict: same perfect numbers, verdict
    #    flipped, and a blocking finding appears.  The code is read out of the
    #    Kernel rather than named here, so deleting the rule empties the
    #    difference and turns this red.
    failed = _attestation_for(
        request=request, baseline=baseline, manifest=manifest, contract=contract,
        verdict="fail",
    )
    added = kernel(failed, publication=True) - published
    assert added, "the Kernel no longer reads the recorded verdict at all"
    assert all(kernel_rules.SEVERITY[code] == "block" for code in added), added

    # 4. And it cannot run a Harness: nothing that executes one is imported.
    executors = _harness_executing_modules()
    assert len(executors) > 2, executors
    kernel_dir = Path(importlib.import_module("ari.rqgm").__file__).parent
    kernel_files = sorted(kernel_dir.glob("kernel*.py")) + [
        kernel_dir / "kca_kernel_rules.py"
    ]
    assert len(kernel_files) > 5, kernel_files
    offenders = {
        path.name: sorted(
            name
            for name in _dotted_imports(path)
            if any(
                name == module or name.startswith(f"{module}.")
                for module in executors
            )
        )
        for path in kernel_files
    }
    assert {name: hit for name, hit in offenders.items() if hit} == {}


# ── criterion 51: simple_bfts + assurance.off leaves the tree as it was ─────


def _kca_artifact_names() -> frozenset[str]:
    """Every file name the K/C/A admission publishes, from the writer itself."""

    from ari.rqgm.admission import _SAFE_DOCUMENT_NAMES

    return frozenset({ADMISSION_FILENAME, *_SAFE_DOCUMENT_NAMES})


def _node_attributes_written_by(path: Path, function: str | None = None) -> set[str]:
    """Node attributes a K/C/A module ASSIGNS, read out of its own source.

    ``node.frontier_class = ...`` in a bridge is what makes ``frontier_class``
    part of the K/C/A surface; nothing here lists the fields, so a bridge that
    starts stamping a new one is covered the moment it does.
    """

    tree = ast.parse(path.read_text(encoding="utf-8"))
    if function is not None:
        tree = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == function
        )
    written: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "node"
            ):
                written.add(target.attr)
    return written


def _kca_node_attributes() -> set[str]:
    """The three places production stamps K/C/A provenance onto a node."""

    rqgm_dir = Path(importlib.import_module("ari.rqgm").__file__).parent
    return (
        _node_attributes_written_by(rqgm_dir / "knowledge_bridge.py")
        | _node_attributes_written_by(rqgm_dir / "assurance_bridge.py")
        | _node_attributes_written_by(
            rqgm_dir / "runtime.py", "_wrap_kca_node_preparation"
        )
    )


def _simple_bfts_run(tmp_path: Path):
    """One complete shipped-default run: simple_bfts, assurance.off."""

    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from ari.cli import _run_loop
    from ari.config import ARIConfig
    from ari.orchestrator.node import Node

    cfg = ARIConfig(
        bfts={"max_total_nodes": 3, "max_parallel_nodes": 1, "timeout_per_node": 60}
    )
    # The pairing the criterion names, taken from the shipped defaults rather
    # than asserted into existence here.
    assert cfg.ari.mode == "simple_bfts", cfg.ari.mode
    assert cfg.assurance.mode == "off", cfg.assurance.mode

    agent = MagicMock()
    agent.hints = SimpleNamespace(
        provided_files=[], slurm_partition="", slurm_max_cpus=0
    )
    agent.memory = MagicMock()
    agent.memory.search.return_value = []

    def _run(node, exp_data):
        node.mark_running()
        node.mark_success(eval_summary="ok")
        node.has_real_data = True
        return node

    agent.run.side_effect = _run

    bfts = MagicMock()
    bfts.should_prune.return_value = False
    counter = {"n": 0}

    def _expand(node, *args, **kwargs):
        counter["n"] += 1
        child = Node(
            id=f"child_{counter['n']}", parent_id=node.id, depth=node.depth + 1
        )
        node.children.append(child.id)
        return [child]

    bfts.expand.side_effect = _expand
    bfts.select_best_to_expand.side_effect = lambda f, g, m: f[0]
    bfts.select_next_node.side_effect = lambda p, g, m: p[0]
    bfts.expansion_count.return_value = 0
    bfts.diversity_bonus.return_value = 0.0

    root = Node(id="node_root", parent_id=None, depth=0)
    _run_loop(
        cfg,
        bfts,
        agent,
        [root],
        [root],
        {"goal": "g", "topic": "t", "file": "exp.md"},
        checkpoint_dir=tmp_path,
        run_id="kca-off-smoke",
    )
    return cfg


def _build_default_runtime(monkeypatch, checkpoint: Path):
    """``build_runtime`` on the shipped config, with the network seams stubbed."""

    from ari.config import ARIConfig
    from ari.core import build_runtime

    class _StubMCP:
        def __init__(self, skills, disabled_tools=None):
            self.skills = list(skills)

        def list_tools(self, phase=None):
            return []

    class _StubLLM:
        def __init__(self, cfg_llm, *a, **k):
            self.config = cfg_llm
            self.mcp_client = None

        def _model_name(self):
            return "stub-model"

    class _Stub:
        def __init__(self, *a, **k):
            pass

        def run(self, node, experiment):
            return node

    monkeypatch.setattr("ari.mcp.client.MCPClient", _StubMCP)
    monkeypatch.setattr("ari.llm.client.LLMClient", _StubLLM)
    monkeypatch.setattr("ari.memory.letta_client.LettaMemoryClient", _Stub)
    monkeypatch.setattr("ari.evaluator.LLMEvaluator", _Stub)
    monkeypatch.setattr("ari.agent.loop.AgentLoop", _Stub)
    for name in [n for n in list(sys.modules) if n.startswith("ari.rqgm")]:
        monkeypatch.delitem(sys.modules, name)
    return build_runtime(ARIConfig(), "goal", checkpoint_dir=checkpoint)


def test_simple_bfts_assurance_off_artifacts(monkeypatch, tmp_path):
    """Criterion 51 -- the shipped defaults add no K/C/A artifact of any kind.

    Two surfaces, both derived.  On disk, every artifact Tasks 16-19 write goes
    under one subtree, and its name comes from ``ADMISSION_RELATIVE_DIR`` and
    ``_SAFE_DOCUMENT_NAMES`` in ``ari/rqgm/admission.py`` -- the module that
    publishes them -- so a new admission document is checked for the moment it
    is added there.  In ``tree.json``, the K/C/A provenance fields are the ones
    the two bridges and ``_wrap_kca_node_preparation`` ASSIGN, read out of
    their own ASTs, and each must still hold the ``Node`` dataclass default.

    The positive control is what stops this from being a test that would pass
    against an empty directory: the same derived path and the same derived
    names are shown to be exactly what ``persist_run_admission`` writes when
    K/C/A IS on.
    """

    from ari.orchestrator.node import Node
    from ari.rqgm.admission import (
        KCAAdmissionArtifacts,
        KCAModeSnapshotV1,
        KCARunAdmissionV1,
        persist_run_admission,
    )
    from ari.rqgm.prompt_spec import KCA_FIXED_COMPONENT_TABLE

    monkeypatch.delenv("ARI_CHECKPOINT_DIR", raising=False)

    names = _kca_artifact_names()
    assert len(names) > 10, names
    attributes = _kca_node_attributes()
    assert len(attributes) > 5, attributes
    subtree = ADMISSION_RELATIVE_DIR.parent
    assert subtree.parts, ADMISSION_RELATIVE_DIR

    # Positive control: this is where, and under what names, K/C/A writes.
    live = tmp_path / "kca-on"
    live.mkdir()
    admission = KCARunAdmissionV1.create(
        run_id="control",
        modes=KCAModeSnapshotV1(
            knowledge="audit", capability_binding="audit", assurance="audit"
        ),
        constitution_sha256=SHA,
        fixed_component_ids=tuple(row[0] for row in KCA_FIXED_COMPONENT_TABLE),
        research_contract_digest=SHA,
        artifact_digests={},
    )
    written = persist_run_admission(live, KCAAdmissionArtifacts(admission, {}))
    assert written == live / ADMISSION_RELATIVE_DIR
    control_names = {path.name for path in live.rglob("*") if path.is_file()}
    assert control_names <= names and control_names, control_names
    assert (live / subtree).is_dir()

    # The gate itself: under the shipped defaults ``build_runtime`` never even
    # constructs the runtime that would write any of the above, so the strategy
    # it returns carries no ``rqgm`` controller and no K/C/A module is loaded.
    built = tmp_path / "built"
    built.mkdir()
    _, _, _, strategy, _, _ = _build_default_runtime(monkeypatch, built)
    assert getattr(strategy, "rqgm", None) is None
    assert not [name for name in sys.modules if name.startswith("ari.rqgm.")]
    assert not (built / subtree).exists()

    # The run itself, under the shipped defaults.
    checkpoint = tmp_path / "run"
    checkpoint.mkdir()
    _simple_bfts_run(checkpoint)

    produced = sorted(path for path in checkpoint.rglob("*"))
    assert produced, "the run wrote nothing at all; the assertions below are free"
    assert not (checkpoint / subtree).exists()
    stray = sorted(
        str(path.relative_to(checkpoint))
        for path in produced
        if path.name in names or subtree.as_posix() in path.as_posix()
    )
    assert stray == [], stray

    import json

    tree = json.loads((checkpoint / "tree.json").read_text(encoding="utf-8"))
    stored = tree["nodes"] if isinstance(tree, dict) else tree
    assert stored, tree
    defaults = Node(id="probe", parent_id=None, depth=0).to_dict()
    dirty = {
        (node.get("id"), name): node[name]
        for node in stored
        for name in sorted(attributes)
        if name in node and node[name] != defaults.get(name)
    }
    assert dirty == {}, dirty


# ── criterion 64: a node carries all three identities, not one of them ──────


BODIES = {
    "eval-gemm-method": "# GEMM\nUse a compile capability; never bypass verification.\n",
    "eval-profile-method": "# Profiling\nUse a profile capability before claiming a speedup.\n",
}


def _kca_admission(tmp_path: Path):
    """One run admission minted by the production minter, for two Skills."""

    from types import SimpleNamespace

    from ari.capability_binding.models import (
        CapabilityBindingRequestV1,
        CapabilityContractV1,
        CapabilityOntologySnapshotV1,
        CapabilityProvisionV1,
    )
    from ari.capability_binding.resolver import bind_capabilities
    from ari.knowledge.catalog import build_catalog_snapshot
    from ari.knowledge.models import (
        KnowledgeAdmissionContextV1,
        KnowledgeAuthorityCeilingV1,
        KnowledgeCapabilityRequirementV1,
        KnowledgeCapabilitySetV1,
        KnowledgeCompositionV1,
        KnowledgeSkillApplicabilityV1,
        KnowledgeSkillEntryV1,
        KnowledgeSkillLicenseV1,
        KnowledgeSkillManifestV1,
        KnowledgeSkillSelectionProposalV1,
        KnowledgeSkillSourceV1,
    )
    from ari.knowledge.resolver import admit_knowledge_skills
    from ari.protocols.integrity import bytes_digest, canonical_digest
    from ari.protocols.scientific_requirements import EnvironmentSnapshotV1
    from ari.rqgm.admission import (
        KCAModeSnapshotV1,
        build_run_admission,
    )

    contracts = tuple(
        CapabilityContractV1.create(
            capability_ref=ref,
            contract_version="v1",
            title=title,
            description=f"{title} a candidate",
            side_effect_class="workspace-write",
            determinism_class="conditional",
            context_requirement="node",
            compatibility_rules=("schema",),
        )
        for ref, title in (
            ("ari.execution.compile/v1", "Compile"),
            ("ari.execution.profile/v1", "Profile"),
        )
    )
    ontology = CapabilityOntologySnapshotV1.create(
        source_revision="test",
        property_vocabulary_version="v1",
        contracts=contracts,
    )
    manifests = tuple(
        KnowledgeSkillManifestV1(
            id=skill_id,
            version="1.0.0",
            title=skill_id,
            description="acceptance fixture",
            status="verified",
            source=KnowledgeSkillSourceV1(
                repository="https://example.invalid/knowledge",
                commit="2" * 40,
                path="knowledge-skills/" + skill_id,
                body_sha256=bytes_digest(body.encode()),
                manifest_sha256=SHA,
            ),
            license=KnowledgeSkillLicenseV1(body="MIT", references="MIT"),
            applies_to=KnowledgeSkillApplicabilityV1(
                roles=("generator",), phases=("bfts",), task_tags=("gemm",)
            ),
            requires=KnowledgeCapabilitySetV1(
                capabilities=(
                    KnowledgeCapabilityRequirementV1(
                        ref=contract.capability_ref, required=True
                    ),
                )
            ),
            authority_ceiling=KnowledgeAuthorityCeilingV1(
                side_effects=("read-only", "workspace-write")
            ),
            composition=KnowledgeCompositionV1(slot="domain-method", priority=100),
        )
        for (skill_id, body), contract in zip(sorted(BODIES.items()), contracts)
    )
    entries = tuple(
        KnowledgeSkillEntryV1.create(
            manifest=item,
            body_store_key=item.source.body_sha256,
            registration_report_digest=SHA,
            importer_version="test/v1",
            status="verified",
        )
        for item in manifests
    )
    catalog = build_catalog_snapshot(
        catalog_source_revision="test", importer_version="test/v1", entries=entries
    )
    proposal = KnowledgeSkillSelectionProposalV1.create(
        run_id="run-1",
        epoch_id="epoch_000",
        research_contract_digest=SHA,
        proposed=tuple(item.exact_ref() for item in manifests),
        reason="two applicable Skills",
        router_component_id="proposal_router_v1",
        router_prompt_hash=None,
    )
    context = KnowledgeAdmissionContextV1.create(
        role="generator",
        phase="bfts",
        task_tags=("gemm",),
        permitted_side_effects=("read-only", "workspace-write"),
        property_vocabulary=("numerical-equivalence",),
    )
    skill_lock = admit_knowledge_skills(
        proposal=proposal,
        catalog=catalog,
        ontology=ontology,
        context=context,
        mode="enforce",
    )
    assert len(skill_lock.admitted) > 1, skill_lock.admitted

    provider_lock_document = {"schema_version": "test/provider-lock", "skills": []}
    provider_lock_digest = canonical_digest(provider_lock_document)
    provisions = tuple(
        CapabilityProvisionV1.create(
            provider_id=f"provider-{index}",
            provider_identity_digest=canonical_digest({"provider": index}),
            provider_status="verified",
            tool_ref=f"provider-{index}.tool",
            declared_capability_ref="legacy." + contract.title.lower(),
            capability_ref=contract.capability_ref,
            capability_contract_digest=contract.contract_digest,
            provider_lock_digest=provider_lock_digest,
            manifest_digest=SHA,
            input_schema_digest=canonical_digest({"type": "object"}),
            output_schema_digest=canonical_digest({"type": "object"}),
            policy_digest=SHA,
            schema_compatibility_evidence_digest=SHA,
            side_effect_class="workspace-write",
            determinism_class="conditional",
            context_requirement="node",
            roles=("generator",),
            phases=("bfts",),
            reproducibility_grade="exact",
            declared_resource_cost=(1, 1, 1),
            registration_report_digest=SHA,
        )
        for index, contract in enumerate(contracts)
    )
    from ari.rqgm.admission_builder import _run_capability_requirements

    requirements = _run_capability_requirements(
        SimpleNamespace(capability_binding=None), ontology, skill_lock
    )
    binding_request = CapabilityBindingRequestV1.create(
        run_id="run-1",
        epoch_id="epoch_000",
        research_contract_digest=SHA,
        knowledge_skill_lock_digest=skill_lock.lock_digest,
        ontology_snapshot_digest=ontology.snapshot_digest,
        provider_catalog_snapshot_digest=SHA,
        provider_lock_digest=provider_lock_digest,
        requirements=requirements,
        provisions=provisions,
        available_tool_refs=tuple(sorted({item.tool_ref for item in provisions})),
        role="generator",
        phase="bfts",
        call_context="node",
        authorized_capability_refs=tuple(
            sorted(item.capability_ref for item in contracts)
        ),
        environment=EnvironmentSnapshotV1.create(resource_types=("process",)),
        mode="enforce",
    )
    binding_lock, _report = bind_capabilities(request=binding_request)

    manifest, atom, locked, contract, baseline, request, harness_catalog = (
        _coherent_state(tmp_path)
    )
    documents = {
        "research_contract.json": {"contract_digest": SHA},
        "knowledge_catalog_snapshot.json": catalog,
        "knowledge_skill_lock.json": skill_lock,
        "knowledge_bodies.json": {
            bytes_digest(body.encode()): body for body in BODIES.values()
        },
        "provider_lock.json": provider_lock_document,
        "capability_binding_lock.json": binding_lock,
        "verification_contract.json": contract,
        "harness_catalog_snapshot.json": harness_catalog,
        "baseline_harness_lock.json": baseline,
    }
    artifacts = build_run_admission(
        run_id="run-1",
        modes=KCAModeSnapshotV1(
            knowledge="enforce", capability_binding="audit", assurance="audit"
        ),
        research_contract=SimpleNamespace(contract_digest=SHA),
        documents=documents,
        identity_fields={
            "knowledge_catalog_snapshot_digest": catalog.snapshot_digest,
            "knowledge_skill_lock_digest": skill_lock.lock_digest,
            "provider_lock_digest": provider_lock_digest,
            "capability_binding_lock_digest": binding_lock.lock_digest,
            "verification_contract_digest": contract.contract_digest,
            "harness_catalog_snapshot_digest": harness_catalog["snapshot_digest"],
            "baseline_harness_lock_digest": baseline.lock_digest,
            "active_harness_lock_digest": baseline.lock_digest,
        },
    )
    return artifacts, skill_lock, binding_lock


def test_node_kca_provenance_complete(tmp_path):
    """Criterion 64 -- one node carries the Skill hashes, the Binding Lock and
    the Harness Lock, and each is the identity the run was admitted under.

    ``RQGMRuntime._wrap_kca_node_preparation`` is the mechanism, reached
    through ``wrap_node_executor`` -- the same call ``ari/core.py`` makes -- and
    it is the ONLY place a node is stamped before ``AgentLoop`` sees it.  A
    partial stamp is the failure this criterion exists for: a node that carries
    the Harness Lock but not the Skill hashes is unauditable in exactly the way
    a node that carries none of them is, and it looks complete.

    Nothing below names a field.  The lock digests are whichever identities the
    admission and the ``Node`` dataclass share; the Skill hashes come from the
    epoch lock's own admitted set; the tool refs come from the same
    ``bound_tool_refs`` projection that gates the calls.  Two Skills are
    admitted on purpose: a one-element ordered comparison holds under every
    ordering and would vouch for nothing.
    """

    import dataclasses
    import json

    from ari.capability_binding.resolver import bound_tool_refs
    from ari.config import ARIConfig
    from ari.orchestrator.node import Node
    from ari.protocols.integrity import is_full_sha256
    from ari.rqgm.knowledge_bridge import RQGMKnowledgeBridge
    from ari.rqgm.runtime import RQGMRuntime

    artifacts, skill_lock, binding_lock = _kca_admission(tmp_path)
    admission = artifacts.admission

    runtime = RQGMRuntime(
        ARIConfig(
            ari={"mode": "ari_rqgm"},
            rqgm={"enabled": True},
            knowledge={"mode": "enforce"},
            capability_binding={"mode": "audit"},
            assurance={"mode": "audit"},
        ),
        checkpoint_dir=tmp_path,
    )
    assert runtime._kca_feature_enabled
    runtime._run_admission = admission
    runtime._admission_artifacts = artifacts
    runtime._knowledge_bridge = RQGMKnowledgeBridge.from_admission(
        artifacts, checkpoint_dir=tmp_path
    )

    class _Executor:
        def __init__(self):
            self.seen = None

        def run(self, node, experiment):
            self.seen = node
            return node

    executor = _Executor()
    # The production seam, not the private wrapper: ``ari/core.py`` reaches the
    # stamp only through this call, so a stamp detached from it would not run.
    assert "wrap_node_executor" in Path(
        importlib.import_module("ari.core").__file__
    ).read_text(encoding="utf-8")
    wrapped = runtime.wrap_node_executor(executor)
    node = Node(id="node_001", parent_id=None, depth=0)
    wrapped.run(node, {"goal": "g"})
    assert executor.seen is node

    # 1. Every identity the admission and the node BOTH name must agree.
    node_fields = {field.name for field in dataclasses.fields(Node)}
    identity = admission.scientific_identity()
    shared = sorted(set(identity) & node_fields)
    assert len(shared) >= 3, shared
    assert [name for name in shared if "binding" in name], shared
    assert [name for name in shared if "harness" in name], shared
    assert {name: getattr(node, name) for name in shared} == {
        name: identity[name] for name in shared
    }

    # 2. The Skill hashes, from the epoch lock rather than from a literal.
    admitted = tuple(item.body_sha256 for item in skill_lock.admitted)
    assert len(set(admitted)) > 1, admitted
    assert [ref["body_sha256"] for ref in node.knowledge_skill_refs] == list(admitted)
    assert is_full_sha256(node.knowledge_skill_use_digest)
    assert is_full_sha256(node.instruction_identity_digest)
    identity_document = json.loads(
        (
            tmp_path / "rqgm" / "kca" / "nodes" / node.id / "instruction_identity.json"
        ).read_text(encoding="utf-8")
    )
    assert identity_document["instruction_digest"] == node.instruction_identity_digest
    assert tuple(identity_document["ordered_knowledge_skill_hashes"]) == admitted
    assert identity_document["capability_binding_lock_digest"] == (
        binding_lock.lock_digest
    )
    assert identity_document["active_harness_lock_digest"] == (
        admission.active_harness_lock_digest
    )

    # 3. The bound tool surface, through the projection that gates the calls.
    expected_tools = sorted(bound_tool_refs(binding_lock))
    assert len(expected_tools) > 1, expected_tools
    assert node.bound_tool_refs == expected_tools


def test_every_role_named_anchor_still_exists_where_it_is_pinned():
    """The hand-pinned list cannot go stale without saying so.

    A list is only honest while it still describes the tree. If one of these is
    renamed or removed, this fails rather than quietly narrowing the inventory
    the criterion-49 test walks.
    """
    models = _kca_contract_models()
    for (key, name), reason in sorted(_ROLE_NAMED_ANCHORS.items()):
        assert key in models, f"{key} no longer exists ({reason})"
        assert name in models[key].model_fields, (
            f"{key}.{name} no longer exists ({reason})")
        assert not _is_anchor_name(name), (
            f"{key}.{name} is now found by its name; drop it from the list")
