"""Deterministic exact-set-cover Harness Resolver."""

from __future__ import annotations

from functools import lru_cache

from ari.assurance.models import (
    BaselineHarnessLockV1,
    HarnessCatalogSnapshotV1,
    HarnessCoverageV1,
    HarnessManifestV1,
    HarnessRequirementV1,
    HarnessSuiteV1,
    LockedHarnessV1,
    VerificationContractV1,
)
from ari.protocols.integrity import canonical_digest
from ari.protocols.scientific_requirements import EnvironmentSnapshotV1


class HarnessResolutionError(ValueError):
    pass


_TIER_RANK = {"screen": 0, "validate": 1, "certify": 2}


def normalize_requirements(
    contract: VerificationContractV1,
) -> tuple[HarnessRequirementV1, ...]:
    atoms: list[HarnessRequirementV1] = []
    for requirement in contract.requirements:
        for method in requirement.required_methods:
            atoms.append(
                HarnessRequirementV1.create(
                    verification_requirement_digest=requirement.requirement_digest,
                    property_id=requirement.property_id,
                    method=method,
                    tier=requirement.required_tier,
                    target_kind=requirement.target_kind,
                    scope=requirement.scope,
                    tolerance_policy_digest=requirement.tolerance_policy_digest,
                    independence_requirement=requirement.independence_requirement,
                    determinism_requirement=requirement.determinism_requirement,
                    source_requirement_refs=requirement.source_requirement_refs,
                )
            )
    return tuple(sorted(atoms, key=lambda item: item.atom_digest))


def _coverage(
    manifest: HarnessManifestV1,
    atom: HarnessRequirementV1,
    environment: EnvironmentSnapshotV1,
) -> bool:
    if manifest.status != "verified":
        return False
    if atom.target_kind not in manifest.target_kinds:
        return False
    if manifest.kind == "benchmark" and not manifest.accepts_external_target:
        # Fixed benchmark tasks evaluate their own subjects, never an arbitrary node.
        if atom.target_kind not in {"model", "agent", "benchmark-submission"}:
            return False
    if not set(manifest.resources.features).issubset(set(environment.features)):
        return False
    if environment.resource_types and not (
        {"process", *manifest.supported_hardware} & set(environment.resource_types)
    ):
        return False
    for provided in manifest.properties:
        if provided.property_id != atom.property_id or atom.method not in provided.methods:
            continue
        if max(_TIER_RANK[tier] for tier in provided.tiers) < _TIER_RANK[atom.tier]:
            continue
        if provided.tolerance_policy_digest != atom.tolerance_policy_digest:
            continue
        if not atom.scope.is_covered_by(provided.scope):
            continue
        if atom.independence_requirement == "independent" and manifest.oracle_independence != "independent":
            continue
        if atom.determinism_requirement == "deterministic" and manifest.scorer_determinism != "deterministic":
            continue
        if atom.determinism_requirement == "seeded" and manifest.scorer_determinism == "nondeterministic":
            continue
        return True
    return False


def _objective(
    selected: tuple[int, ...],
    manifests: tuple[HarnessManifestV1, ...],
    atoms: tuple[HarnessRequirementV1, ...],
    coverage: tuple[frozenset[int], ...],
) -> tuple:
    covered = set().union(*(coverage[index] for index in selected)) if selected else set()
    tier_strength = 0
    for atom_index in covered:
        atom = atoms[atom_index]
        strongest = _TIER_RANK[atom.tier]
        for index in selected:
            if atom_index not in coverage[index]:
                continue
            manifest = manifests[index]
            for provided in manifest.properties:
                if provided.property_id == atom.property_id and atom.method in provided.methods:
                    strongest = max(strongest, max(_TIER_RANK[tier] for tier in provided.tiers))
        tier_strength -= strongest
    nondeterministic = sum(
        manifests[index].scorer_determinism == "nondeterministic" for index in selected
    )
    dependent = sum(
        manifests[index].oracle_independence != "independent" for index in selected
    )
    costs = tuple(
        sum(manifests[index].resources.cost_tuple()[axis] for index in selected)
        for axis in range(4)
    )
    identities = tuple(
        sorted(
            (
                manifests[index].id,
                manifests[index].version,
                manifests[index].manifest_digest,
            )
            for index in selected
        )
    )
    return (
        len(atoms) - len(covered),
        tier_strength,
        nondeterministic,
        dependent,
        costs,
        len(selected),
        identities,
    )


def resolve_harness_suite(
    *,
    contract: VerificationContractV1,
    catalog: HarnessCatalogSnapshotV1,
    environment: EnvironmentSnapshotV1,
    enforce_coverage: bool = True,
) -> HarnessSuiteV1:
    """Choose an exact minimum objective suite from the frozen reviewed catalog."""

    atoms = normalize_requirements(contract)
    if len(atoms) > 128:
        raise HarnessResolutionError("catalog_resolution_limit: more than 128 atoms")
    compatible = tuple(
        manifest
        for manifest in catalog.manifests
        if any(_coverage(manifest, atom, environment) for atom in atoms)
    )
    if len(compatible) > 64:
        raise HarnessResolutionError("catalog_resolution_limit: more than 64 candidates")
    coverage = tuple(
        frozenset(index for index, atom in enumerate(atoms) if _coverage(manifest, atom, environment))
        for manifest in compatible
    )
    by_atom: tuple[tuple[int, ...], ...] = tuple(
        tuple(index for index, covered in enumerate(coverage) if atom_index in covered)
        for atom_index in range(len(atoms))
    )
    uncovered = [atoms[index].atom_digest for index, candidates in enumerate(by_atom) if not candidates]
    if uncovered and enforce_coverage:
        raise HarnessResolutionError("unsatisfied Harness coverage: " + ", ".join(uncovered))

    @lru_cache(maxsize=None)
    def solve(remaining: frozenset[int]) -> tuple[int, ...] | None:
        if not remaining:
            return ()
        atom_index = min(remaining, key=lambda item: (len(by_atom[item]), atoms[item].atom_digest))
        best: tuple[int, ...] | None = None
        best_objective: tuple | None = None
        for candidate in by_atom[atom_index]:
            next_remaining = remaining - coverage[candidate]
            suffix = solve(frozenset(next_remaining))
            if suffix is None:
                continue
            selected = tuple(sorted({candidate, *suffix}))
            objective = _objective(selected, compatible, atoms, coverage)
            if best_objective is None or objective < best_objective:
                best, best_objective = selected, objective
        return best

    satisfiable = frozenset(
        index for index, candidates in enumerate(by_atom) if candidates
    )
    selected = solve(satisfiable)
    if selected is None:
        raise HarnessResolutionError("unsatisfied Harness coverage")
    objective = _objective(selected, compatible, atoms, coverage)
    selected_manifests = tuple(compatible[index] for index in selected)
    coverage_records = tuple(
        HarnessCoverageV1(
            harness_manifest_digest=compatible[index].manifest_digest,
            covered_atom_digests=tuple(atoms[item].atom_digest for item in sorted(coverage[index])),
        )
        for index in selected
    )
    return HarnessSuiteV1.create(
        requirements=atoms,
        harness_manifest_digests=tuple(item.manifest_digest for item in selected_manifests),
        coverage=coverage_records,
        covered_atom_digests=tuple(
            atoms[index].atom_digest
            for index in sorted(
                set().union(*(coverage[item] for item in selected)) if selected else set()
            )
        ),
        unsatisfied_atom_digests=tuple(uncovered),
        aggregate_resource_cost=objective[4],
        verification_environment_digest=environment.identity_digest,
        resolver_objective=objective,
    )


def mint_baseline_harness_lock(
    *,
    run_id: str,
    research_contract_digest: str,
    contract: VerificationContractV1,
    catalog: HarnessCatalogSnapshotV1,
    environment: EnvironmentSnapshotV1,
    oracle_bundle_digest: str,
    suite: HarnessSuiteV1,
) -> BaselineHarnessLockV1:
    if suite.verification_environment_digest != environment.identity_digest:
        raise HarnessResolutionError("suite environment identity mismatch")
    manifests = {item.manifest_digest: item for item in catalog.manifests}
    coverage = {item.harness_manifest_digest: item.covered_atom_digests for item in suite.coverage}
    locked: list[LockedHarnessV1] = []
    for digest in suite.harness_manifest_digests:
        manifest = manifests.get(digest)
        if manifest is None or manifest.status != "verified":
            raise HarnessResolutionError("suite references unavailable verified Harness")
        locked.append(
            LockedHarnessV1(
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
                covered_atom_digests=coverage[digest],
            )
        )
    proof = canonical_digest(
        {
            "requirements": [item.atom_digest for item in suite.requirements],
            "coverage": [item.model_dump(mode="json") for item in suite.coverage],
            "unsatisfied": list(suite.unsatisfied_atom_digests),
        }
    )
    return BaselineHarnessLockV1.create(
        run_id=run_id,
        research_contract_digest=research_contract_digest,
        verification_contract_digest=contract.contract_digest,
        harness_catalog_snapshot_digest=catalog.snapshot_digest,
        verification_environment_digest=environment.identity_digest,
        oracle_bundle_digest=oracle_bundle_digest,
        suite_digest=suite.suite_digest,
        requirements=suite.requirements,
        unsatisfied_atom_digests=suite.unsatisfied_atom_digests,
        harnesses=tuple(sorted(locked, key=lambda item: (item.harness_id, item.version))),
        coverage_proof_digest=proof,
    )


__all__ = [
    "HarnessResolutionError",
    "mint_baseline_harness_lock",
    "normalize_requirements",
    "resolve_harness_suite",
]
