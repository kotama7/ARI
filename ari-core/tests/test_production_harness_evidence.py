from __future__ import annotations

import json
import math
from pathlib import Path

from ari.assurance.catalog import load_harness_catalog
from ari.assurance.models import (
    BaselineHarnessLockV1,
    HarnessAttestationV1,
    HarnessCatalogSnapshotV1,
    VerificationContractV1,
)
from ari.manuscript.contracts import (
    ManuscriptAuthoringBindingV1,
    ManuscriptReadinessReportV1,
    PublicationDecisionV1,
    PublicationLockV1,
)
from ari.manuscript.digest import file_digest
from ari.paper_contract import parse_paper_build
from ari.protocols.integrity import canonical_digest
from ari.protocols.scientific_requirements import EnvironmentSnapshotV1


REPOSITORY = Path(__file__).resolve().parents[2]
HARNESS_ROOT = REPOSITORY / "ari-core" / "config" / "harnesses"
E2E_ROOT = HARNESS_ROOT / "evidence" / "production_e2e"


def _model(filename: str, contract):
    return contract.model_validate_json(
        (E2E_ROOT / filename).read_text(encoding="utf-8")
    )


def test_production_native_harness_catalog_is_verified_and_closed() -> None:
    catalog = load_harness_catalog(HARNESS_ROOT / "catalog.yaml")
    by_id = {item.id: item for item in catalog.manifests}
    assert set(by_id) == {
        "hpc/gemm-correctness",
        "hpc/spmm-correctness",
        "hpc/stencil-correctness",
    }
    assert {item.status for item in by_id.values()} == {"verified"}
    assert set(catalog.promotion_approval_digests) == set(by_id)


def test_persisted_certify_publication_e2e_chain_and_cost() -> None:
    catalog = _model("harness_catalog_snapshot.json", HarnessCatalogSnapshotV1)
    contract = _model("verification_contract.json", VerificationContractV1)
    baseline = _model("baseline_harness_lock.json", BaselineHarnessLockV1)
    environment = _model("verification_environment.json", EnvironmentSnapshotV1)
    screen = _model("screen_attestation.json", HarnessAttestationV1)
    certify = _model("certify_attestation.json", HarnessAttestationV1)
    readiness = _model("manuscript_readiness.json", ManuscriptReadinessReportV1)
    binding = _model("manuscript_authoring_binding.json", ManuscriptAuthoringBindingV1)
    build = parse_paper_build(
        (E2E_ROOT / "paper_build.json").read_text(encoding="utf-8")
    )
    decision = _model("publication_decision.json", PublicationDecisionV1)
    publication_lock = _model("publication_lock.json", PublicationLockV1)

    assert baseline.verification_contract_digest == contract.contract_digest
    assert baseline.harness_catalog_snapshot_digest == catalog.snapshot_digest
    assert baseline.verification_environment_digest == environment.identity_digest
    assert not baseline.unsatisfied_atom_digests
    assert screen.baseline_harness_lock_digest == baseline.lock_digest
    assert certify.baseline_harness_lock_digest == baseline.lock_digest
    assert screen.verification_contract_digest == contract.contract_digest
    assert certify.verification_contract_digest == contract.contract_digest
    assert screen.target_digest == certify.target_digest
    assert screen.verdict == certify.verdict == "pass"
    assert {result.tier for result in screen.property_results} == {"screen"}
    assert {result.tier for result in certify.property_results} == {"certify"}

    assert readiness.publication_verdict == "ready"
    assert binding.readiness_digest == readiness.readiness_digest
    assert build.build_id == binding.target_build_id
    assert build.build_revision == binding.target_build_revision
    assert decision.decision == "publishable"
    assert {item.status for item in decision.subverdicts} == {"pass"}
    assert decision.paper_build_digest == build.build_digest
    assert decision.authoring_binding_digest == binding.binding_digest
    assert publication_lock.decision_digest == decision.decision_digest
    assert publication_lock.paper_build_digest == build.build_digest
    assert publication_lock.authoring_binding_digest == binding.binding_digest
    assert (
        file_digest(E2E_ROOT / "published_paper.pdf")[0] == publication_lock.pdf_digest
    )
    reproduction = json.loads(
        (E2E_ROOT / "reproduction.json").read_text(encoding="utf-8")
    )
    assert reproduction["executed"] is True
    assert reproduction["exit_code"] == 0
    assert reproduction["missing"] == []
    assert reproduction["error"] == ""
    assert reproduction["digest_match"] is True
    assert reproduction["expected_pdf_digest"] == publication_lock.pdf_digest
    assert reproduction["reproduced_pdf_digest"] == publication_lock.pdf_digest
    assert (
        file_digest(E2E_ROOT / "reproduced_paper.pdf")[0] == publication_lock.pdf_digest
    )

    cost = json.loads(
        (E2E_ROOT / "authoritative_verification_cost.json").read_text(encoding="utf-8")
    )
    measurement_digest = cost.pop("measurement_digest")
    assert canonical_digest(cost) == measurement_digest
    assert {item["tier"] for item in cost["records"]} == {"screen", "certify"}
    assert {item["attestation_digest"] for item in cost["records"]} == {
        screen.attestation_digest,
        certify.attestation_digest,
    }
    assert cost["totals"]["pricing_status"] == "unpriced"
    assert cost["totals"]["monetary_cost_usd"] is None
    assert math.isclose(
        cost["totals"]["wall_time_seconds"],
        sum(item["wall_time_seconds"] for item in cost["records"]),
    )
    assert math.isclose(
        cost["totals"]["cpu_core_seconds"],
        sum(item["cpu_core_seconds"] for item in cost["records"]),
    )

    report = json.loads((E2E_ROOT / "e2e_report.json").read_text(encoding="utf-8"))
    report_digest = report.pop("report_digest")
    assert canonical_digest(report) == report_digest
    assert report["harness_catalog_snapshot_digest"] == catalog.snapshot_digest
    assert report["verification_contract_digest"] == contract.contract_digest
    assert report["baseline_harness_lock_digest"] == baseline.lock_digest
    assert report["target_digest"] == certify.target_digest
    assert report["certify_attestation_digest"] == certify.attestation_digest
    assert report["manuscript_readiness_digest"] == readiness.readiness_digest
    assert report["paper_build_digest"] == build.build_digest
    assert report["publication_decision_digest"] == decision.decision_digest
    assert report["publication_lock_digest"] == publication_lock.lock_digest
    assert report["published_pdf_digest"] == publication_lock.pdf_digest
    assert report["verification_cost_measurement_digest"] == measurement_digest
    assert report["publication_decision"] == "publishable"
    assert report["physical_node_identity_persisted"] is False
