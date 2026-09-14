from __future__ import annotations

import copy
import hashlib
import json
import uuid
from pathlib import Path

import pytest

import auditor as A
import migration as X
from manifest import verify


QUOTE = "The benchmark writes results.json after every completed run."
PAPER = f"Methods. {QUOTE} Results are measured in milliseconds."


def _legacy() -> dict:
    document = {
        "version": "3",
        "paper_sha256": hashlib.sha256(PAPER.encode()).hexdigest(),
        "generator": {
            "model": "legacy/model",
            "prompt_sha256": "a" * 64,
            "generated_at": "2026-01-01T00:00:00Z",
            "temperature": 0.0,
        },
        "audit": {
            "auditor_model": "legacy/auditor",
            "audited_at": "2026-01-02T00:00:00Z",
            "flags_count": 1,
        },
        "reproduce_contract": {
            "script_path": "reproduce.sh",
            "max_runtime_sec": 600,
            "expected_artifacts": ["results.json"],
        },
        "rubric": {
            "id": str(uuid.uuid4()),
            "requirements": "Replicate the benchmark results from the paper.",
            "weight": 1,
            "sub_tasks": [
                {
                    "id": str(uuid.uuid4()),
                    "requirements": "Write the completed benchmark results artifact.",
                    "weight": 1,
                    "sub_tasks": [],
                    "task_category": "Code Execution",
                    "finegrained_task_category": "Experimental Setup",
                    "rationale_from_paper": {
                        "section": "Methods",
                        "quote": QUOTE,
                    },
                    "flags": ["unverifiable"],
                }
            ],
        },
    }
    document["rubric_sha256"] = X._legacy_digest(document)
    return document


@pytest.mark.asyncio
async def test_lossless_v1_migration_is_artifact_backed_and_auditable(tmp_path: Path):
    output = tmp_path / "rubric-v2.json"
    result = X.migrate_v1_to_v2(
        legacy_document=_legacy(), paper_text=PAPER, output_path=str(output)
    )
    assert "error" not in result, result
    migrated = json.loads(output.read_text())
    assert migrated["schema_version"] == "ari.replication-rubric/v2"
    assert migrated["generator"]["strategy"] == "legacy-v1-offline-migration"
    assert migrated["generator"]["max_model_calls"] == 0
    assert migrated["generator"]["source_artifact"]["sha256"]
    assert migrated["repair_ledger"]["actions"][-1]["action"] == "legacy-migrate"
    assert "audit" not in migrated
    assert verify(migrated)

    async def audit_call(prompt: str) -> dict:
        return {"vague_qualifier": False, "unverifiable": False}

    audited = await A.audit_rubric_async(
        rubric_path=str(output),
        paper_text=PAPER,
        auditor_model="fixture/auditor",
        llm_call=audit_call,
    )
    assert audited["llm_status"] == "completed"


def test_v1_migration_rejects_tampered_source(tmp_path: Path):
    legacy = _legacy()
    legacy["rubric"]["requirements"] = "Tampered legacy rubric requirement."
    result = X.migrate_v1_to_v2(
        legacy_document=legacy,
        paper_text=PAPER,
        output_path=str(tmp_path / "rubric-v2.json"),
    )
    assert result["error"] == "legacy rubric digest verification failed"


def test_v1_migration_rejects_lossy_evidence_mapping(tmp_path: Path):
    legacy = _legacy()
    legacy["rubric"]["sub_tasks"][0]["rationale_from_paper"]["quote"] = (
        "This sentence is not present in the supplied paper."
    )
    legacy["rubric_sha256"] = X._legacy_digest(legacy)
    output = tmp_path / "rubric-v2.json"
    result = X.migrate_v1_to_v2(
        legacy_document=copy.deepcopy(legacy),
        paper_text=PAPER,
        output_path=str(output),
    )
    assert "cannot be migrated losslessly" in result["error"]
    assert not output.exists()


def test_v1_reader_rejects_unknown_or_already_versioned_input(tmp_path: Path):
    legacy = _legacy()
    legacy["schema_version"] = "ari.replication-rubric/v999"
    result = X.migrate_v1_to_v2(
        legacy_document=legacy,
        paper_text=PAPER,
        output_path=str(tmp_path / "rubric-v2.json"),
    )
    assert "only accepts an unversioned V1" in result["error"]
