"""Stable public contract, read, and pure-resolution Assurance surface."""

from ari.assurance.attestation import validate_attestation
from ari.assurance.catalog import (
    build_harness_catalog_snapshot,
    describe_harness,
    load_harness_catalog,
    search_harnesses,
)
from ari.assurance.drivers.external import (
    ExternalHarnessParityReportV1,
    ExternalParityCheckV1,
)
from ari.assurance.lock import validate_harness_revision, write_immutable_harness_lock
from ari.assurance.models import (
    AuxiliaryVerificationRequestV1,
    BaselineHarnessLockV1,
    HarnessAttestationV1,
    HarnessCatalogSnapshotV1,
    HarnessLockRevisionV1,
    HarnessManifestV1,
    HarnessPromotionApprovalV1,
    HarnessPropertyResultV1,
    HarnessRegistrationReportV1,
    HarnessRegistrationEvidenceV1,
    HarnessRunRequestV1,
    HarnessTargetDeclarationV1,
    HarnessSuiteV1,
    VerificationContractV1,
    VerificationRequirementProposalV1,
    VerificationRequirementV1,
)
from ari.assurance.request import (
    HarnessRequestError,
    build_native_harness_run_request,
    load_target_declaration,
)
from ari.assurance.runner import FixedVerifier, HarnessExecutionError
from ari.assurance.resolver import (
    HarnessResolutionError,
    mint_baseline_harness_lock,
    normalize_requirements,
    resolve_harness_suite,
)
from ari.assurance.suite import (
    assert_monotonic_requirement_revision,
    mint_verification_contract,
    obligations_to_requirements,
    union_verification_requirements,
)
from ari.protocols.integrity import canonical_digest

__all__ = [
    "AuxiliaryVerificationRequestV1",
    "BaselineHarnessLockV1",
    "ExternalHarnessParityReportV1",
    "ExternalParityCheckV1",
    "FixedVerifier",
    "HarnessAttestationV1",
    "HarnessCatalogSnapshotV1",
    "HarnessExecutionError",
    "HarnessLockRevisionV1",
    "HarnessManifestV1",
    "HarnessPromotionApprovalV1",
    "HarnessPropertyResultV1",
    "HarnessRegistrationReportV1",
    "HarnessRegistrationEvidenceV1",
    "HarnessRequestError",
    "HarnessResolutionError",
    "HarnessRunRequestV1",
    "HarnessSuiteV1",
    "HarnessTargetDeclarationV1",
    "VerificationContractV1",
    "VerificationRequirementProposalV1",
    "VerificationRequirementV1",
    "assert_monotonic_requirement_revision",
    "build_harness_catalog_snapshot",
    "build_native_harness_run_request",
    "canonical_digest",
    "describe_harness",
    "load_harness_catalog",
    "load_target_declaration",
    "mint_baseline_harness_lock",
    "mint_verification_contract",
    "normalize_requirements",
    "obligations_to_requirements",
    "resolve_harness_suite",
    "search_harnesses",
    "union_verification_requirements",
    "validate_attestation",
    "validate_harness_revision",
    "write_immutable_harness_lock",
]
