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
from ari.call_context import ToolCallContextV1  # noqa: E402
from ari.execution import (  # noqa: E402
    ExecutionRequestV1,
    ExecutionResultV1,
    MeasurementSetV1,
    WorkspaceRefV1,
)
from ari.skill_lock import SkillsLockV1  # noqa: E402
from ari.research_contract import (  # noqa: E402
    IdeaCandidateV1,
    IdeaSetV1,
    MetricContractV1,
    ResearchContractV1,
    RetrievalRecordV1,
    SurveySnapshotV1,
)


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
    outputs[schema_dir / CONTEXT_SCHEMA_PATH.name] = _json_text(context_schema_document())
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
