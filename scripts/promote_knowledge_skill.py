#!/usr/bin/env python3
"""Promote one eligible Knowledge Skill to `verified`.

This is an authenticated human-maintainer surface, not an agent tool, and it
is the only writer of Knowledge promotion state. It refuses to act unless the
Skill's registration decision is already `eligible-for-verified`, and it
records who promoted it, on what basis, against exactly which bytes.

Passing sixteen gates makes a Skill eligible; it does not promote it. What
this script adds is the second half: an approval bound to the exact manifest,
body, and evidence that were reviewed, plus an append-only transition record.
Both the catalog loader and `GovernedKnowledgeSkillRegistry.transition` refuse
a promotion that lacks them.

Usage:
  python scripts/promote_knowledge_skill.py --skill intel.phoronix-test-suite \\
      --actor-id "maintainer@example.org" \\
      --basis "reviewed the measured clean task and abstraction report" \\
      --approved-date 2026-08-07 [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "ari-core"))

from ari.knowledge.catalog import (  # noqa: E402
    GovernedKnowledgeSkillRegistry,
    load_knowledge_catalog,
)
from ari.knowledge.external_models import KnowledgeImportMaterialV1  # noqa: E402
from ari.knowledge.registration_models import (  # noqa: E402
    KnowledgeSkillPromotionApprovalV1,
    KnowledgeSkillRegistrationEvidenceV1,
)
from ari.protocols.integrity import canonical_digest  # noqa: E402

CATALOG_ROOT = REPO / "ari-core" / "config" / "knowledge_skills"


def _entry_stem(catalog_text: str, skill_id: str, root: Path) -> str:
    """Return the file stem the catalog uses for this Skill."""

    import yaml

    document = yaml.safe_load(catalog_text)
    for entry in document["entries"]:
        material = entry.get("import_material")
        if material is None:
            raise SystemExit(
                f"{skill_id}: only imported Skills can be promoted by this surface"
            )
        payload = json.loads((root / str(material)).read_text(encoding="utf-8"))
        if payload["manifest"]["id"] == skill_id:
            return Path(str(material)).stem
    raise SystemExit(f"{skill_id}: not present in the catalog")


def _manifest_digest(manifest: dict) -> str:
    payload = dict(manifest)
    source = dict(payload["source"])
    source.pop("manifest_sha256", None)
    payload["source"] = source
    return canonical_digest(payload)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill", required=True, help="exact Knowledge Skill id")
    parser.add_argument("--actor-id", required=True, help="who authorises this")
    parser.add_argument("--basis", required=True, help="what was reviewed")
    parser.add_argument("--approved-date", required=True, help="ISO date of review")
    parser.add_argument(
        "--actor-kind",
        default="human-maintainer",
        choices=("human-maintainer", "authenticated-admin-cli"),
    )
    parser.add_argument(
        "--catalog-root",
        type=Path,
        default=CATALOG_ROOT,
        help="knowledge_skills directory to act on (staging copies)",
    )
    parser.add_argument("--dry-run", action="store_true")
    arguments = parser.parse_args()

    root = arguments.catalog_root
    loaded = load_knowledge_catalog(root / "catalog.yaml")
    entries = {item.manifest.id: item for item in loaded.snapshot.entries}
    entry = entries.get(arguments.skill)
    if entry is None:
        raise SystemExit(f"{arguments.skill}: not present in the catalog")
    report = loaded.registration_reports[entry.registration_report_digest]
    if entry.status != "candidate":
        raise SystemExit(f"{arguments.skill}: already {entry.status}")
    if report.decision != "eligible-for-verified":
        failed = [item.gate_id for item in report.gates if not item.passed]
        raise SystemExit(
            f"{arguments.skill}: decision is {report.decision}; unmet gates: "
            f"{', '.join(failed)}"
        )
    evidence = next(
        (
            item
            for item in loaded.registration_evidence.values()
            if item.skill_ref.id == arguments.skill
        ),
        None,
    )

    catalog_path = root / "catalog.yaml"
    catalog_text = catalog_path.read_text(encoding="utf-8")
    stem = _entry_stem(catalog_text, arguments.skill, root)

    # The promoted manifest is a different exact ref, so build the identity the
    # promotion will actually have before signing anything against it.
    material_path = root / "imports" / f"{stem}.json"
    material_document = json.loads(material_path.read_text(encoding="utf-8"))
    material_document.pop("material_digest")
    material_document["manifest"]["status"] = "verified"
    material_document["manifest"]["source"]["manifest_sha256"] = _manifest_digest(
        material_document["manifest"]
    )
    material = KnowledgeImportMaterialV1.create(**material_document)
    promoted_ref = material.manifest.exact_ref()

    evidence_path = root / "evidence" / f"{stem}.registration.json"
    evidence_document = json.loads(evidence_path.read_text(encoding="utf-8"))
    old_evidence_digest = evidence_document.pop("evidence_digest")
    evidence_document["skill_ref"] = promoted_ref.model_dump(mode="json")
    promoted_evidence = KnowledgeSkillRegistrationEvidenceV1.create(**evidence_document)

    approval = KnowledgeSkillPromotionApprovalV1.create(
        skill_ref=promoted_ref.model_dump(mode="json"),
        actor_kind=arguments.actor_kind,
        actor_id=arguments.actor_id,
        authorization_basis=arguments.basis,
        approved_date=arguments.approved_date,
        registration_evidence_digest=promoted_evidence.evidence_digest,
    )

    registry = GovernedKnowledgeSkillRegistry()
    for item in loaded.snapshot.entries:
        registry.register(item)
    registry.register(
        entry.model_copy(update={"status": "candidate"})
        if entry.manifest.exact_ref() == promoted_ref
        else entry
    )
    transition = registry.transition(
        skill_ref=entry.manifest.exact_ref(),
        to_status="verified",
        actor_id=arguments.actor_id,
        evidence_digest=approval.approval_digest,
        approval=approval.model_copy(
            update={"skill_ref": entry.manifest.exact_ref()}
        ),
    )

    print(f"skill      : {arguments.skill}")
    print(f"decision   : {report.decision}")
    print(f"approval   : {approval.approval_digest}")
    print(f"transition : {transition.transition_digest}")
    print(f"promoted to: {promoted_ref.manifest_sha256}")
    if arguments.dry_run:
        print("\ndry run: nothing written")
        return 0

    material_path.write_text(
        json.dumps(material.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    evidence_path.write_text(
        json.dumps(promoted_evidence.model_dump(mode="json"), indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    (root / "evidence" / f"{stem}.approval.json").write_text(
        json.dumps(approval.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (root / "evidence" / f"{stem}.transition.json").write_text(
        json.dumps(transition.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    catalog_text = catalog_text.replace(
        old_evidence_digest, promoted_evidence.evidence_digest
    )
    # Insert beside the line we just rewrote, carrying its own indentation:
    # the catalog is hand-formatted and a staging copy may be dumped differently.
    lines = catalog_text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if promoted_evidence.evidence_digest not in line:
            continue
        indent = line[: len(line) - len(line.lstrip())]
        lines[index + 1 : index + 1] = [
            f"{indent}promotion_approval: evidence/{stem}.approval.json\n",
            f"{indent}promotion_approval_digest: {approval.approval_digest}\n",
        ]
        break
    else:
        raise SystemExit("could not locate the catalog entry to approve")
    catalog_text = "".join(lines)
    catalog_path.write_text(catalog_text, encoding="utf-8")

    verified = load_knowledge_catalog(catalog_path)
    status = {item.manifest.id: item.status for item in verified.snapshot.entries}
    print(f"\ncatalog reloads; {arguments.skill} is now {status[arguments.skill]}")
    if evidence is not None:
        print(f"evidence re-sealed from {old_evidence_digest[:20]}…")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
