"""Declaring `verified` must exhibit the gates and the approval that acted.

Without this the sixteen registration gates decide nothing: `status` is a
field in a checked-in file, and anyone editing it promotes a Skill.  The
Harness catalog has always enforced both halves; these cases hold the
Knowledge catalog to the same bar.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from ari.knowledge.catalog import (
    GovernedKnowledgeSkillRegistry,
    load_knowledge_catalog,
)
from ari.knowledge.external_models import KnowledgeImportMaterialV1
from ari.knowledge.models import KnowledgeSkillEntryV1
from ari.knowledge.registration_models import (
    KnowledgeSkillPromotionApprovalV1,
    KnowledgeSkillRegistrationEvidenceV1,
)
from ari.protocols.integrity import canonical_digest


CONFIG_ROOT = Path(__file__).resolve().parents[1] / "config" / "knowledge_skills"
ELIGIBLE = "intel_phoronix_test_suite"
INELIGIBLE = "hpc_stencil_optimization"


def _copy(tmp_path: Path) -> Path:
    """Copy the catalog and put every entry back to `candidate`.

    The shipped catalog now carries promoted Skills, so these cases stage the
    pre-promotion state instead of assuming it.
    """

    copied = tmp_path / "knowledge_skills"
    shutil.copytree(CONFIG_ROOT, copied)
    catalog_path = copied / "catalog.yaml"
    document = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    for entry in document["entries"]:
        entry.pop("promotion_approval", None)
        entry.pop("promotion_approval_digest", None)
        stem = Path(str(entry["import_material"])).stem
        material_path = copied / "imports" / f"{stem}.json"
        material = json.loads(material_path.read_text(encoding="utf-8"))
        if material["manifest"]["status"] == "candidate":
            continue
        material.pop("material_digest")
        material["manifest"]["status"] = "candidate"
        material["manifest"]["source"]["manifest_sha256"] = _manifest_digest(
            material["manifest"]
        )
        demoted = KnowledgeImportMaterialV1.create(**material)
        material_path.write_text(demoted.model_dump_json(), encoding="utf-8")
        evidence_path = copied / "evidence" / f"{stem}.registration.json"
        body = json.loads(evidence_path.read_text(encoding="utf-8"))
        body.pop("evidence_digest")
        body["skill_ref"] = demoted.manifest.exact_ref().model_dump(mode="json")
        evidence = KnowledgeSkillRegistrationEvidenceV1.create(**body)
        evidence_path.write_text(
            json.dumps(evidence.model_dump(mode="json"), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        entry["registration_evidence_digest"] = evidence.evidence_digest
    catalog_path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return copied


def _manifest_digest(manifest: dict) -> str:
    payload = dict(manifest)
    source = dict(payload["source"])
    source.pop("manifest_sha256", None)
    payload["source"] = source
    return canonical_digest(payload)


def _reseal_evidence(root: Path, stem: str, manifest_sha256: str) -> str:
    """Re-point the registration evidence at the promoted manifest."""

    path = root / "evidence" / f"{stem}.registration.json"
    body = json.loads(path.read_text(encoding="utf-8"))
    old = body.pop("evidence_digest")
    body["skill_ref"] = {**body["skill_ref"], "manifest_sha256": manifest_sha256}
    evidence = KnowledgeSkillRegistrationEvidenceV1.create(**body)
    path.write_text(
        json.dumps(evidence.model_dump(mode="json"), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    catalog = root / "catalog.yaml"
    catalog.write_text(
        catalog.read_text(encoding="utf-8").replace(old, evidence.evidence_digest),
        encoding="utf-8",
    )
    return evidence.evidence_digest


def _promote_import(root: Path, stem: str) -> tuple[dict, str]:
    """Flip an imported Skill to `verified` and re-seal every bound digest."""

    path = root / "imports" / f"{stem}.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document.pop("material_digest")
    manifest = document["manifest"]
    manifest["status"] = "verified"
    manifest["source"]["manifest_sha256"] = _manifest_digest(manifest)
    material = KnowledgeImportMaterialV1.create(**document)
    path.write_text(material.model_dump_json(), encoding="utf-8")
    evidence_digest = _reseal_evidence(root, stem, manifest["source"]["manifest_sha256"])
    return material.manifest.exact_ref().model_dump(mode="json"), evidence_digest


def _write_approval(root: Path, stem: str, skill_ref: dict, **updates) -> None:
    values = dict(
        skill_ref=skill_ref,
        actor_kind="human-maintainer",
        actor_id="maintainer@example.invalid",
        authorization_basis="reviewed sixteen passing gates and stored evidence",
        approved_date="2026-08-07",
    )
    values.update(updates)
    approval = KnowledgeSkillPromotionApprovalV1.create(**values)
    (root / "evidence" / f"{stem}.approval.json").write_text(
        approval.model_dump_json(), encoding="utf-8"
    )
    catalog_path = root / "catalog.yaml"
    document = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    for entry in document["entries"]:
        material = str(entry.get("import_material") or entry.get("manifest") or "")
        if stem in material:
            entry["promotion_approval"] = f"evidence/{stem}.approval.json"
            entry["promotion_approval_digest"] = approval.approval_digest
    catalog_path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")


def _fail_the_clean_task(root: Path, stem: str) -> None:
    """Record the measured clean task as unsatisfied, leaving the artifact intact."""

    path = root / "evidence" / f"{stem}.registration.json"
    body = json.loads(path.read_text(encoding="utf-8"))
    old = body.pop("evidence_digest")
    body["clean_task"] = {**body["clean_task"], "status": "unsatisfied"}
    evidence = KnowledgeSkillRegistrationEvidenceV1.create(**body)
    path.write_text(
        json.dumps(evidence.model_dump(mode="json"), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    catalog = root / "catalog.yaml"
    catalog.write_text(
        catalog.read_text(encoding="utf-8").replace(old, evidence.evidence_digest),
        encoding="utf-8",
    )


def test_verified_without_passing_gates_is_refused(tmp_path: Path):
    """A Skill whose measured clean task is unsatisfied is never eligible."""

    root = _copy(tmp_path)
    _fail_the_clean_task(root, INELIGIBLE)
    skill_ref, evidence_digest = _promote_import(root, INELIGIBLE)
    _write_approval(
        root, INELIGIBLE, skill_ref, registration_evidence_digest=evidence_digest
    )

    with pytest.raises(ValueError, match="lacks passing registration gates"):
        load_knowledge_catalog(root / "catalog.yaml")


def test_verified_without_an_approval_is_refused(tmp_path: Path):
    root = _copy(tmp_path)
    _promote_import(root, ELIGIBLE)

    with pytest.raises(ValueError, match="lacks a promotion approval"):
        load_knowledge_catalog(root / "catalog.yaml")


def test_approval_for_another_manifest_is_refused(tmp_path: Path):
    """An approval that predates an edit must not carry over to the new bytes."""

    root = _copy(tmp_path)
    skill_ref, evidence_digest = _promote_import(root, ELIGIBLE)
    stale = {**skill_ref, "manifest_sha256": "sha256:" + "9" * 64}
    _write_approval(
        root, ELIGIBLE, stale, registration_evidence_digest=evidence_digest
    )

    with pytest.raises(ValueError, match="promotion approval differs"):
        load_knowledge_catalog(root / "catalog.yaml")


def test_approval_bound_to_stale_evidence_is_refused(tmp_path: Path):
    root = _copy(tmp_path)
    skill_ref, _ = _promote_import(root, ELIGIBLE)
    _write_approval(
        root,
        ELIGIBLE,
        skill_ref,
        registration_evidence_digest="sha256:" + "8" * 64,
    )

    with pytest.raises(ValueError, match="promotion approval differs"):
        load_knowledge_catalog(root / "catalog.yaml")


def test_gates_plus_approval_promote_exactly_one_skill(tmp_path: Path):
    root = _copy(tmp_path)
    skill_ref, evidence_digest = _promote_import(root, ELIGIBLE)
    _write_approval(
        root, ELIGIBLE, skill_ref, registration_evidence_digest=evidence_digest
    )

    loaded = load_knowledge_catalog(root / "catalog.yaml")

    statuses = {item.manifest.id: item.status for item in loaded.snapshot.entries}
    assert statuses["intel.phoronix-test-suite"] == "verified"
    assert set(loaded.promotion_approvals) == {"intel.phoronix-test-suite"}
    approval = loaded.promotion_approvals["intel.phoronix-test-suite"]
    assert approval.from_status == "candidate" and approval.to_status == "verified"
    assert approval.actor_id == "maintainer@example.invalid"
    # Everything else stays where it was.
    assert {value for key, value in statuses.items() if key != "intel.phoronix-test-suite"} == {
        "candidate"
    }


def test_approval_on_a_candidate_entry_is_refused(tmp_path: Path):
    """An approval must not sit beside a Skill nobody promoted."""

    root = _copy(tmp_path)
    material = json.loads(
        (root / "imports" / f"{ELIGIBLE}.json").read_text(encoding="utf-8")
    )
    _write_approval(root, ELIGIBLE, material["manifest"]["source"] and {
        "id": material["manifest"]["id"],
        "version": material["manifest"]["version"],
        "body_sha256": material["manifest"]["source"]["body_sha256"],
        "manifest_sha256": material["manifest"]["source"]["manifest_sha256"],
    })

    with pytest.raises(ValueError, match="requires a verified Knowledge Skill"):
        load_knowledge_catalog(root / "catalog.yaml")


def _registry_with(entry):
    registry = GovernedKnowledgeSkillRegistry()
    registry.register(entry)
    return registry


def _approval_for(skill_ref, **updates):
    values = dict(
        skill_ref=skill_ref.model_dump(mode="json"),
        actor_kind="human-maintainer",
        actor_id="maintainer@example.invalid",
        authorization_basis="reviewed the gates and the stored evidence",
        approved_date="2026-08-07",
    )
    values.update(updates)
    return KnowledgeSkillPromotionApprovalV1.create(**values)


def _first_entry():
    """One catalog entry restated at `candidate`.

    The shipped catalog is fully promoted, so these cases stage the state a
    promotion starts from rather than depending on one surviving candidate.
    """

    loaded = load_knowledge_catalog(CONFIG_ROOT / "catalog.yaml")
    entry = sorted(loaded.snapshot.entries, key=lambda item: item.manifest.id)[0]
    return KnowledgeSkillEntryV1.create(
        manifest=entry.manifest,
        body_store_key=entry.body_store_key,
        registration_report_digest=entry.registration_report_digest,
        importer_version=entry.importer_version,
        status="candidate",
    )


def test_ledger_promotion_without_an_approval_is_refused():
    """The in-memory ledger must not be a way around the catalog's guard."""

    entry = _first_entry()
    registry = _registry_with(entry)
    with pytest.raises(ValueError, match="requires a promotion approval"):
        registry.transition(
            skill_ref=entry.manifest.exact_ref(),
            to_status="verified",
            actor_id="maintainer@example.invalid",
            evidence_digest="sha256:" + "7" * 64,
        )


def test_ledger_promotion_records_its_approval_as_the_evidence():
    entry = _first_entry()
    skill_ref = entry.manifest.exact_ref()
    approval = _approval_for(skill_ref)
    registry = _registry_with(entry)

    with pytest.raises(ValueError, match="must record its approval"):
        registry.transition(
            skill_ref=skill_ref, to_status="verified",
            actor_id="maintainer@example.invalid",
            evidence_digest="sha256:" + "7" * 64, approval=approval,
        )

    transition = registry.transition(
        skill_ref=skill_ref, to_status="verified",
        actor_id="maintainer@example.invalid",
        evidence_digest=approval.approval_digest, approval=approval,
    )
    assert transition.to_status == "verified"
    assert transition.evidence_digest == approval.approval_digest
    assert registry.status_at(skill_ref) == "verified"


def test_ledger_promotion_refuses_an_approval_for_another_skill():
    entry = _first_entry()
    skill_ref = entry.manifest.exact_ref()
    stale = _approval_for(
        skill_ref.model_copy(update={"manifest_sha256": "sha256:" + "9" * 64})
    )
    registry = _registry_with(entry)
    with pytest.raises(ValueError, match="names another Knowledge Skill"):
        registry.transition(
            skill_ref=skill_ref, to_status="verified",
            actor_id="maintainer@example.invalid",
            evidence_digest=stale.approval_digest, approval=stale,
        )


def test_an_approval_does_not_authorise_deprecation():
    entry = _first_entry()
    skill_ref = entry.manifest.exact_ref()
    approval = _approval_for(skill_ref)
    registry = _registry_with(entry)
    with pytest.raises(ValueError, match="only authorises verification"):
        registry.transition(
            skill_ref=skill_ref, to_status="deprecated",
            actor_id="maintainer@example.invalid",
            evidence_digest=approval.approval_digest, approval=approval,
        )


PROMOTE = Path(__file__).resolve().parents[2] / "scripts" / "promote_knowledge_skill.py"


def _promote_script(root: Path, skill: str, *extra: str):
    return subprocess.run(
        [sys.executable, str(PROMOTE), "--skill", skill,
         "--actor-id", "maintainer@example.invalid",
         "--basis", "reviewed the measured clean task and abstraction report",
         "--approved-date", "2026-08-07", "--catalog-root", str(root), *extra],
        capture_output=True, text=True,
    )


def test_the_promotion_surface_refuses_a_skill_that_is_not_eligible(tmp_path: Path):
    root = _copy(tmp_path)
    _fail_the_clean_task(root, INELIGIBLE)
    completed = _promote_script(root, "hpc.stencil.optimization")
    assert completed.returncode != 0
    assert "unmet gates: clean_task" in completed.stderr


def test_the_promotion_surface_writes_an_auditable_promotion(tmp_path: Path):
    root = _copy(tmp_path)
    before = load_knowledge_catalog(root / "catalog.yaml")
    assert {item.manifest.id: item.status for item in before.snapshot.entries}[
        "intel.phoronix-test-suite"
    ] == "candidate"

    completed = _promote_script(root, "intel.phoronix-test-suite")
    assert completed.returncode == 0, completed.stderr

    after = load_knowledge_catalog(root / "catalog.yaml")
    statuses = {item.manifest.id: item.status for item in after.snapshot.entries}
    assert statuses["intel.phoronix-test-suite"] == "verified"
    assert {value for key, value in statuses.items()
            if key != "intel.phoronix-test-suite"} == {"candidate"}

    approval = after.promotion_approvals["intel.phoronix-test-suite"]
    assert approval.actor_id == "maintainer@example.invalid"
    ledger = json.loads(
        (root / "evidence" / "intel_phoronix_test_suite.transition.json").read_text(
            encoding="utf-8"
        )
    )
    # The ledger entry and the catalog approval must describe one act.
    assert ledger["from_status"] == "candidate" and ledger["to_status"] == "verified"
    assert ledger["evidence_digest"] == approval.approval_digest


def test_promoting_twice_is_refused(tmp_path: Path):
    root = _copy(tmp_path)
    assert _promote_script(root, "intel.phoronix-test-suite").returncode == 0
    again = _promote_script(root, "intel.phoronix-test-suite")
    assert again.returncode != 0
    assert "already verified" in again.stderr
