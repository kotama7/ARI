#!/usr/bin/env python3
"""Generate compatibility metadata from canonical ``skill.yaml`` files.

The canonical manifests are reviewed source.  ``mcp.json`` and the published
JSON Schema are deterministic derived artifacts.  Run with ``--write`` after a
manifest/model change; CI uses the default ``--check`` mode.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ARI_CORE = REPO_ROOT / "ari-core"
sys.path.insert(0, str(ARI_CORE))

from ari.skill_manifest import (  # noqa: E402
    SkillManifestV1,
    legacy_mcp_document,
    load_skill_manifest,
)
from ari.result import ResultEnvelopeV1  # noqa: E402
from ari.async_tools import AsyncToolHandleV1  # noqa: E402
from ari.analysis import (  # noqa: E402
    AnalysisRequestV1,
    AnalysisResultV1,
    RunComparisonRequestV1,
    StatisticalTestRequestV1,
)
from ari.memory_contract import (  # noqa: E402
    MemoryBackupV1,
    MemoryRecordV1,
    MemoryRetrievalV1,
)
from ari.paper_contract import PaperBuildV1, PaperModelCallBatchV1  # noqa: E402
from ari.call_context import ToolCallContextV1  # noqa: E402
from ari.claim_gate_contract import (  # noqa: E402
    GateReportV1,
    MetricAdmissionDecisionV1,
    MetricContractProposalV1,
    MetricGateContractV1,
    SemanticReviewV1,
)
from ari.execution import (  # noqa: E402
    ExecutionRequestV1,
    ExecutionResultV1,
    MeasurementSetV1,
    WorkspaceRefV1,
)
from ari.figure_contract import FigureBatchV1  # noqa: E402
from ari.skill_lock import SkillsLockV1  # noqa: E402
from ari.research_contract import (  # noqa: E402
    IdeaCandidateV1,
    IdeaSetV1,
    MetricContractV1,
    ResearchContractV1,
    RetrievalRecordV1,
    SurveySnapshotV1,
)
from ari.science_data_contract import ScienceDataV1  # noqa: E402
from ari.visual_review_contract import VisualReviewBatchV1  # noqa: E402
from ari.knowledge.models import (  # noqa: E402
    EpochKnowledgeSkillLockV1,
    KnowledgeSkillCatalogSnapshotV1,
    KnowledgeSkillManifestV1,
    NodeKnowledgeSkillUseV1,
)
from ari.knowledge.registration_models import (  # noqa: E402
    KnowledgeSkillRegistrationEvidenceV1,
)
from ari.capability_binding.models import (  # noqa: E402
    CapabilityBindingLockV1,
    CapabilityContractV1,
)
from ari.assurance.models import (  # noqa: E402
    BaselineHarnessLockV1,
    HarnessAttestationV1,
    HarnessCatalogSnapshotV1,
    HarnessLockRevisionV1,
    HarnessManifestV1,
    HarnessPromotionApprovalV1,
    HarnessRegistrationEvidenceV1,
    HarnessRegistrationReportV1,
    HarnessRunRequestV1,
    VerificationContractV1,
)
from ari.assurance.native_hpc import NativeHPCVerificationReportV1  # noqa: E402


SKILL_SCHEMA_PATH = ARI_CORE / "ari" / "schemas" / "skill_manifest_v1.schema.json"
RESULT_SCHEMA_PATH = ARI_CORE / "ari" / "schemas" / "result_envelope_v1.schema.json"
ASYNC_HANDLE_SCHEMA_PATH = (
    ARI_CORE / "ari" / "schemas" / "async_tool_handle_v1.schema.json"
)
CONTEXT_SCHEMA_PATH = ARI_CORE / "ari" / "schemas" / "call_context_v1.schema.json"
LOCK_SCHEMA_PATH = ARI_CORE / "ari" / "schemas" / "skills_lock_v1.schema.json"
WORKSPACE_SCHEMA_PATH = ARI_CORE / "ari" / "schemas" / "workspace_ref_v1.schema.json"
EXECUTION_REQUEST_SCHEMA_PATH = (
    ARI_CORE / "ari" / "schemas" / "execution_request_v1.schema.json"
)
EXECUTION_RESULT_SCHEMA_PATH = (
    ARI_CORE / "ari" / "schemas" / "execution_result_v1.schema.json"
)
MEASUREMENT_SET_SCHEMA_PATH = (
    ARI_CORE / "ari" / "schemas" / "measurement_set_v1.schema.json"
)
RETRIEVAL_RECORD_SCHEMA_PATH = (
    ARI_CORE / "ari" / "schemas" / "retrieval_record_v1.schema.json"
)
SURVEY_SNAPSHOT_SCHEMA_PATH = (
    ARI_CORE / "ari" / "schemas" / "survey_snapshot_v1.schema.json"
)
METRIC_CONTRACT_SCHEMA_PATH = (
    ARI_CORE / "ari" / "schemas" / "metric_contract_v1.schema.json"
)
IDEA_CANDIDATE_SCHEMA_PATH = (
    ARI_CORE / "ari" / "schemas" / "idea_candidate_v1.schema.json"
)
IDEA_SET_SCHEMA_PATH = ARI_CORE / "ari" / "schemas" / "idea_set_v1.schema.json"
RESEARCH_CONTRACT_SCHEMA_PATH = (
    ARI_CORE / "ari" / "schemas" / "research_contract_v1.schema.json"
)
ANALYSIS_REQUEST_SCHEMA_PATH = (
    ARI_CORE / "ari" / "schemas" / "analysis_request_v1.schema.json"
)
STATISTICAL_TEST_REQUEST_SCHEMA_PATH = (
    ARI_CORE / "ari" / "schemas" / "statistical_test_request_v1.schema.json"
)
RUN_COMPARISON_REQUEST_SCHEMA_PATH = (
    ARI_CORE / "ari" / "schemas" / "run_comparison_request_v1.schema.json"
)
ANALYSIS_RESULT_SCHEMA_PATH = (
    ARI_CORE / "ari" / "schemas" / "analysis_result_v1.schema.json"
)
MEMORY_RECORD_SCHEMA_PATH = (
    ARI_CORE / "ari" / "schemas" / "memory_record_v1.schema.json"
)
MEMORY_RETRIEVAL_SCHEMA_PATH = (
    ARI_CORE / "ari" / "schemas" / "memory_retrieval_v1.schema.json"
)
MEMORY_BACKUP_SCHEMA_PATH = (
    ARI_CORE / "ari" / "schemas" / "memory_backup_v1.schema.json"
)
GATE_REPORT_SCHEMA_PATH = ARI_CORE / "ari" / "schemas" / "gate_report_v1.schema.json"
METRIC_GATE_CONTRACT_SCHEMA_PATH = (
    ARI_CORE / "ari" / "schemas" / "metric_gate_contract_v1.schema.json"
)
METRIC_CONTRACT_PROPOSAL_SCHEMA_PATH = (
    ARI_CORE / "ari" / "schemas" / "metric_contract_proposal_v1.schema.json"
)
METRIC_ADMISSION_DECISION_SCHEMA_PATH = (
    ARI_CORE / "ari" / "schemas" / "metric_admission_decision_v1.schema.json"
)
SEMANTIC_REVIEW_SCHEMA_PATH = (
    ARI_CORE / "ari" / "schemas" / "semantic_review_v1.schema.json"
)
SCIENCE_DATA_SCHEMA_PATH = ARI_CORE / "ari" / "schemas" / "science_data_v1.schema.json"
FIGURE_BATCH_SCHEMA_PATH = ARI_CORE / "ari" / "schemas" / "figure_batch_v1.schema.json"
VISUAL_REVIEW_BATCH_SCHEMA_PATH = (
    ARI_CORE / "ari" / "schemas" / "visual_review_batch_v1.schema.json"
)
PAPER_BUILD_SCHEMA_PATH = ARI_CORE / "ari" / "schemas" / "paper_build_v1.schema.json"
PAPER_MODEL_CALL_BATCH_SCHEMA_PATH = (
    ARI_CORE / "ari" / "schemas" / "paper_model_call_batch_v1.schema.json"
)
# Compatibility alias for scripts that imported the original constant.
SCHEMA_PATH = SKILL_SCHEMA_PATH


def _json_text(document: dict) -> str:
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def skill_schema_document() -> dict:
    schema = SkillManifestV1.model_json_schema()
    schema["$id"] = "https://ari.dev/schemas/skill-manifest-v1.schema.json"
    schema["title"] = "ARI Skill Manifest v1"
    return schema


def result_schema_document() -> dict:
    schema = ResultEnvelopeV1.model_json_schema()
    schema["$id"] = "https://ari.dev/schemas/result-envelope-v1.schema.json"
    schema["title"] = "ARI Result Envelope v1"
    return schema


def async_handle_schema_document() -> dict:
    schema = AsyncToolHandleV1.model_json_schema()
    schema["$id"] = "https://ari.dev/schemas/async-tool-handle-v1.schema.json"
    schema["title"] = "ARI Async Tool Handle v1"
    return schema


def context_schema_document() -> dict:
    schema = ToolCallContextV1.model_json_schema()
    schema["$id"] = "https://ari.dev/schemas/call-context-v1.schema.json"
    schema["title"] = "ARI Tool Call Context v1"
    return schema


def lock_schema_document() -> dict:
    schema = SkillsLockV1.model_json_schema()
    schema["$id"] = "https://ari.dev/schemas/skills-lock-v1.schema.json"
    schema["title"] = "ARI Skills Lock v1"
    return schema


def workspace_schema_document() -> dict:
    schema = WorkspaceRefV1.model_json_schema()
    schema["$id"] = "https://ari.dev/schemas/workspace-ref-v1.schema.json"
    schema["title"] = "ARI Workspace Reference v1"
    return schema


def execution_request_schema_document() -> dict:
    schema = ExecutionRequestV1.model_json_schema()
    schema["$id"] = "https://ari.dev/schemas/execution-request-v1.schema.json"
    schema["title"] = "ARI Execution Request v1"
    return schema


def execution_result_schema_document() -> dict:
    schema = ExecutionResultV1.model_json_schema()
    schema["$id"] = "https://ari.dev/schemas/execution-result-v1.schema.json"
    schema["title"] = "ARI Execution Result v1"
    return schema


def measurement_set_schema_document() -> dict:
    schema = MeasurementSetV1.model_json_schema()
    schema["$id"] = "https://ari.dev/schemas/measurement-set-v1.schema.json"
    schema["title"] = "ARI Measurement Set v1"
    return schema


def _research_schema_document(model, slug: str, title: str) -> dict:
    schema = model.model_json_schema()
    schema["$id"] = f"https://ari.dev/schemas/{slug}.schema.json"
    schema["title"] = title
    return schema


# Compatibility alias for callers that generated only the original schema.
schema_document = skill_schema_document


def expected_outputs(repo_root: Path = REPO_ROOT) -> dict[Path, str]:
    outputs: dict[Path, str] = {}
    for manifest_path in sorted(repo_root.glob("ari-skill-*/skill.yaml")):
        manifest = load_skill_manifest(manifest_path)
        outputs[manifest_path.parent / "mcp.json"] = _json_text(
            legacy_mcp_document(manifest)
        )
    schema_dir = repo_root / "ari-core" / "ari" / "schemas"
    outputs[schema_dir / SKILL_SCHEMA_PATH.name] = _json_text(skill_schema_document())
    outputs[schema_dir / RESULT_SCHEMA_PATH.name] = _json_text(result_schema_document())
    outputs[schema_dir / ASYNC_HANDLE_SCHEMA_PATH.name] = _json_text(
        async_handle_schema_document()
    )
    outputs[schema_dir / CONTEXT_SCHEMA_PATH.name] = _json_text(
        context_schema_document()
    )
    outputs[schema_dir / LOCK_SCHEMA_PATH.name] = _json_text(lock_schema_document())
    outputs[schema_dir / WORKSPACE_SCHEMA_PATH.name] = _json_text(
        workspace_schema_document()
    )
    outputs[schema_dir / EXECUTION_REQUEST_SCHEMA_PATH.name] = _json_text(
        execution_request_schema_document()
    )
    outputs[schema_dir / EXECUTION_RESULT_SCHEMA_PATH.name] = _json_text(
        execution_result_schema_document()
    )
    outputs[schema_dir / MEASUREMENT_SET_SCHEMA_PATH.name] = _json_text(
        measurement_set_schema_document()
    )
    for path, model, slug, title in (
        (
            GATE_REPORT_SCHEMA_PATH,
            GateReportV1,
            "gate-report-v1",
            "ARI Gate Report v1",
        ),
        (
            METRIC_GATE_CONTRACT_SCHEMA_PATH,
            MetricGateContractV1,
            "metric-gate-contract-v1",
            "ARI Metric Gate Contract v1",
        ),
        (
            METRIC_CONTRACT_PROPOSAL_SCHEMA_PATH,
            MetricContractProposalV1,
            "metric-contract-proposal-v1",
            "ARI Metric Contract Proposal v1",
        ),
        (
            METRIC_ADMISSION_DECISION_SCHEMA_PATH,
            MetricAdmissionDecisionV1,
            "metric-admission-decision-v1",
            "ARI Metric Admission Decision v1",
        ),
        (
            SEMANTIC_REVIEW_SCHEMA_PATH,
            SemanticReviewV1,
            "semantic-review-v1",
            "ARI Semantic Review v1",
        ),
        (
            SCIENCE_DATA_SCHEMA_PATH,
            ScienceDataV1,
            "science-data-v1",
            "ARI Science Data v1",
        ),
        (
            FIGURE_BATCH_SCHEMA_PATH,
            FigureBatchV1,
            "figure-batch-v1",
            "ARI Figure Batch v1",
        ),
        (
            VISUAL_REVIEW_BATCH_SCHEMA_PATH,
            VisualReviewBatchV1,
            "visual-review-batch-v1",
            "ARI Visual Review Batch v1",
        ),
        (
            PAPER_BUILD_SCHEMA_PATH,
            PaperBuildV1,
            "paper-build-v1",
            "ARI Paper Build v1",
        ),
        (
            PAPER_MODEL_CALL_BATCH_SCHEMA_PATH,
            PaperModelCallBatchV1,
            "paper-model-call-batch-v1",
            "ARI Paper Model Call Batch v1",
        ),
        (
            MEMORY_BACKUP_SCHEMA_PATH,
            MemoryBackupV1,
            "memory-backup-v1",
            "ARI Memory Backup v1",
        ),
        (
            MEMORY_RECORD_SCHEMA_PATH,
            MemoryRecordV1,
            "memory-record-v1",
            "ARI Memory Record v1",
        ),
        (
            MEMORY_RETRIEVAL_SCHEMA_PATH,
            MemoryRetrievalV1,
            "memory-retrieval-v1",
            "ARI Memory Retrieval v1",
        ),
        (
            ANALYSIS_REQUEST_SCHEMA_PATH,
            AnalysisRequestV1,
            "analysis-request-v1",
            "ARI Analysis Request v1",
        ),
        (
            STATISTICAL_TEST_REQUEST_SCHEMA_PATH,
            StatisticalTestRequestV1,
            "statistical-test-request-v1",
            "ARI Statistical Test Request v1",
        ),
        (
            RUN_COMPARISON_REQUEST_SCHEMA_PATH,
            RunComparisonRequestV1,
            "run-comparison-request-v1",
            "ARI Run Comparison Request v1",
        ),
        (
            ANALYSIS_RESULT_SCHEMA_PATH,
            AnalysisResultV1,
            "analysis-result-v1",
            "ARI Analysis Result v1",
        ),
        (
            RETRIEVAL_RECORD_SCHEMA_PATH,
            RetrievalRecordV1,
            "retrieval-record-v1",
            "ARI Retrieval Record v1",
        ),
        (
            SURVEY_SNAPSHOT_SCHEMA_PATH,
            SurveySnapshotV1,
            "survey-snapshot-v1",
            "ARI Survey Snapshot v1",
        ),
        (
            METRIC_CONTRACT_SCHEMA_PATH,
            MetricContractV1,
            "metric-contract-v1",
            "ARI Metric Contract v1",
        ),
        (
            IDEA_CANDIDATE_SCHEMA_PATH,
            IdeaCandidateV1,
            "idea-candidate-v1",
            "ARI Idea Candidate v1",
        ),
        (IDEA_SET_SCHEMA_PATH, IdeaSetV1, "idea-set-v1", "ARI Idea Set v1"),
        (
            RESEARCH_CONTRACT_SCHEMA_PATH,
            ResearchContractV1,
            "research-contract-v1",
            "ARI Research Contract v1",
        ),
        (
            schema_dir / "knowledge_skill_manifest_v1.schema.json",
            KnowledgeSkillManifestV1,
            "knowledge-skill-manifest-v1",
            "ARI Knowledge Skill Manifest v1",
        ),
        (
            schema_dir / "knowledge_skill_catalog_snapshot_v1.schema.json",
            KnowledgeSkillCatalogSnapshotV1,
            "knowledge-skill-catalog-snapshot-v1",
            "ARI Knowledge Skill Catalog Snapshot v1",
        ),
        (
            schema_dir / "knowledge_skill_registration_evidence_v1.schema.json",
            KnowledgeSkillRegistrationEvidenceV1,
            "knowledge-skill-registration-evidence-v1",
            "ARI Knowledge Skill Registration Evidence v1",
        ),
        (
            schema_dir / "epoch_knowledge_skill_lock_v1.schema.json",
            EpochKnowledgeSkillLockV1,
            "epoch-knowledge-skill-lock-v1",
            "ARI Epoch Knowledge Skill Lock v1",
        ),
        (
            schema_dir / "node_knowledge_skill_use_v1.schema.json",
            NodeKnowledgeSkillUseV1,
            "node-knowledge-skill-use-v1",
            "ARI Node Knowledge Skill Use v1",
        ),
        (
            schema_dir / "capability_contract_v1.schema.json",
            CapabilityContractV1,
            "capability-contract-v1",
            "ARI Capability Contract v1",
        ),
        (
            schema_dir / "capability_binding_lock_v1.schema.json",
            CapabilityBindingLockV1,
            "capability-binding-lock-v1",
            "ARI Capability Binding Lock v1",
        ),
        (
            schema_dir / "verification_contract_v1.schema.json",
            VerificationContractV1,
            "verification-contract-v1",
            "ARI Verification Contract v1",
        ),
        (
            schema_dir / "harness_manifest_v1.schema.json",
            HarnessManifestV1,
            "harness-manifest-v1",
            "ARI Harness Manifest v1",
        ),
        (
            schema_dir / "harness_registration_report_v1.schema.json",
            HarnessRegistrationReportV1,
            "harness-registration-report-v1",
            "ARI Harness Registration Report v1",
        ),
        (
            schema_dir / "harness_registration_evidence_v1.schema.json",
            HarnessRegistrationEvidenceV1,
            "harness-registration-evidence-v1",
            "ARI Harness Registration Evidence v1",
        ),
        (
            schema_dir / "harness_promotion_approval_v1.schema.json",
            HarnessPromotionApprovalV1,
            "harness-promotion-approval-v1",
            "ARI Harness Promotion Approval v1",
        ),
        (
            schema_dir / "harness_catalog_snapshot_v1.schema.json",
            HarnessCatalogSnapshotV1,
            "harness-catalog-snapshot-v1",
            "ARI Harness Catalog Snapshot v1",
        ),
        (
            schema_dir / "harness_lock_v1.schema.json",
            BaselineHarnessLockV1,
            "harness-lock-v1",
            "ARI Baseline Harness Lock v1",
        ),
        (
            schema_dir / "harness_lock_revision_v1.schema.json",
            HarnessLockRevisionV1,
            "harness-lock-revision-v1",
            "ARI Harness Lock Revision v1",
        ),
        (
            schema_dir / "harness_run_request_v1.schema.json",
            HarnessRunRequestV1,
            "harness-run-request-v1",
            "ARI Harness Run Request v1",
        ),
        (
            schema_dir / "harness_attestation_v1.schema.json",
            HarnessAttestationV1,
            "harness-attestation-v1",
            "ARI Harness Attestation v1",
        ),
        (
            schema_dir / "native_hpc_verification_report_v1.schema.json",
            NativeHPCVerificationReportV1,
            "native-hpc-verification-report-v1",
            "ARI Native HPC Verification Report v1",
        ),
    ):
        outputs[schema_dir / path.name] = _json_text(
            _research_schema_document(model, slug, title)
        )
    return outputs


def sync(*, write: bool, repo_root: Path = REPO_ROOT) -> list[Path]:
    drift: list[Path] = []
    for path, expected in expected_outputs(repo_root).items():
        actual = path.read_text(encoding="utf-8") if path.is_file() else None
        if actual == expected:
            continue
        drift.append(path)
        if write:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(expected, encoding="utf-8")
    return drift


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write",
        action="store_true",
        help="rewrite generated mcp.json files and JSON Schemas",
    )
    args = parser.parse_args(argv)
    drift = sync(write=args.write)
    if not drift:
        print("skill metadata is up to date")
        return 0
    action = "updated" if args.write else "out of date"
    for path in drift:
        print(f"{action}: {path.relative_to(REPO_ROOT)}")
    return 0 if args.write else 1


if __name__ == "__main__":
    raise SystemExit(main())
