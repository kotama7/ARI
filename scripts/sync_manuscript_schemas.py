#!/usr/bin/env python3
"""Generate/check permanent JSON Schemas for Manuscript Complete V1."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ari.manuscript.contracts import (
    ExplorationSnapshotV1,
    ManuscriptAuthoringBindingV1,
    ManuscriptAutoRepairRoundV1,
    ManuscriptContextV1,
    ManuscriptEvaluationReportV1,
    ManuscriptRequirementProfileV1,
    ManuscriptReadinessReportV1,
    ManuscriptRepairTransactionV1,
    ManuscriptSegmentRecordV1,
    ManuscriptTransitionV1,
    ManuscriptVenueProfileV1,
    OmissionManifestV1,
    PublicationDecisionV1,
    PublicationLockV1,
    ResearchRepairPlanV1,
    ResearchRepairRequestV1,
    SectionBriefBundleV1,
)


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = ROOT / "ari-core" / "ari" / "schemas"
MODELS = {
    "manuscript_requirement_profile_v1.schema.json": ManuscriptRequirementProfileV1,
    "manuscript_venue_profile_v1.schema.json": ManuscriptVenueProfileV1,
    "manuscript_exploration_snapshot_v1.schema.json": ExplorationSnapshotV1,
    "manuscript_context_v1.schema.json": ManuscriptContextV1,
    "manuscript_evaluation_report_v1.schema.json": ManuscriptEvaluationReportV1,
    "manuscript_omission_manifest_v1.schema.json": OmissionManifestV1,
    "manuscript_readiness_v1.schema.json": ManuscriptReadinessReportV1,
    "manuscript_section_brief_bundle_v1.schema.json": SectionBriefBundleV1,
    "manuscript_authoring_binding_v1.schema.json": ManuscriptAuthoringBindingV1,
    "manuscript_segment_record_v1.schema.json": ManuscriptSegmentRecordV1,
    "research_repair_request_v1.schema.json": ResearchRepairRequestV1,
    "research_repair_plan_v1.schema.json": ResearchRepairPlanV1,
    "manuscript_repair_transaction_v1.schema.json": ManuscriptRepairTransactionV1,
    "manuscript_auto_repair_round_v1.schema.json": ManuscriptAutoRepairRoundV1,
    "manuscript_publication_decision_v1.schema.json": PublicationDecisionV1,
    "manuscript_publication_lock_v1.schema.json": PublicationLockV1,
    "manuscript_transition_v1.schema.json": ManuscriptTransitionV1,
}


def rendered(model) -> str:
    return json.dumps(
        model.model_json_schema(),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    stale: list[str] = []
    for filename, model in MODELS.items():
        path = SCHEMA_ROOT / filename
        expected = rendered(model)
        if args.check:
            if not path.is_file() or path.read_text(encoding="utf-8") != expected:
                stale.append(filename)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(expected, encoding="utf-8")
    if stale:
        print("stale manuscript schemas: " + ", ".join(stale))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
