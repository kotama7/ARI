"""Fail-closed offline migration from the legacy rubric envelope to V2."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from generator import _prepare_generated_envelope, _validate_envelope
from manifest import freeze
from provenance import ProvenanceRecorder, RepairLedger


LEGACY_VERSION = "3"
LEGACY_READER_ID = "ari.replication-rubric/legacy-v1"


def _canonical_bytes(value: Any, *, pretty: bool = False) -> bytes:
    if pretty:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        ).encode("utf-8")
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _legacy_digest(document: dict) -> str:
    payload = copy.deepcopy(document)
    payload.pop("rubric_sha256", None)
    # The legacy auditor mutated this field after freeze and the V1 digest
    # intentionally excluded it. V2 deletes this mutation path entirely.
    payload.pop("audit", None)
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def _strip_legacy_annotations(node: dict) -> None:
    node.pop("flags", None)
    for child in node.get("sub_tasks") or []:
        if isinstance(child, dict):
            _strip_legacy_annotations(child)


def migrate_v1_to_v2(
    *,
    legacy_document: dict,
    paper_text: str,
    output_path: str,
) -> dict:
    """Migrate a verified V1 envelope without invoking a model.

    Migration is deliberately lossless. If any node cannot be bound to an
    exact paper span (or to its already-declared external prerequisite), the
    function fails and writes no V2 rubric. The raw V1 object is retained as
    an immutable source artifact so every normalization remains auditable.
    """

    if not isinstance(legacy_document, dict):
        return {"error": "legacy rubric must be a JSON object"}
    if legacy_document.get("schema_version") is not None:
        return {"error": "legacy reader only accepts an unversioned V1 envelope"}
    if legacy_document.get("version") != LEGACY_VERSION:
        return {"error": "unsupported legacy rubric version"}
    if not paper_text:
        return {"error": "paper_text is required for exact evidence migration"}
    if not output_path:
        return {"error": "output_path is required"}
    stored_digest = legacy_document.get("rubric_sha256")
    if (
        not isinstance(stored_digest, str)
        or _legacy_digest(legacy_document) != stored_digest
    ):
        return {"error": "legacy rubric digest verification failed"}
    if not isinstance(legacy_document.get("rubric"), dict):
        return {"error": "legacy rubric is missing its TaskNode root"}

    recorder = ProvenanceRecorder(
        output_path=output_path,
        model="legacy-v1-reader",
        provider="offline",
        model_revision=LEGACY_READER_ID,
        max_model_calls=0,
    )
    source_artifact = recorder.write_input(
        "legacy-v1-source",
        _canonical_bytes(legacy_document, pretty=True),
    )
    ledger = RepairLedger(recorder)
    candidate = {
        "reproduce_contract": copy.deepcopy(
            legacy_document.get("reproduce_contract") or {}
        ),
        "rubric": copy.deepcopy(legacy_document["rubric"]),
    }
    _strip_legacy_annotations(candidate["rubric"])
    prepared, warnings = _prepare_generated_envelope(
        candidate,
        paper_text=paper_text,
        ledger=ledger,
        warning_prefix="legacy-v1",
    )
    if prepared is None:
        return {
            "error": "legacy rubric cannot be migrated losslessly",
            "warnings": warnings,
            "source_artifact": source_artifact,
        }
    if any(action.get("dropped_artifact") for action in ledger.actions):
        return {
            "error": "legacy rubric migration would drop one or more nodes",
            "warnings": warnings,
            "source_artifact": source_artifact,
        }

    ledger.record(
        action="legacy-migrate",
        target="rubric-envelope",
        before=legacy_document,
        after=prepared,
        reason=(
            "converted the verified unversioned V1 envelope into the strict "
            "V2 contract; legacy audit flags remain in the separate source artifact"
        ),
    )
    frozen = freeze(
        prepared,
        generator_model="legacy-v1-reader",
        prompt="offline lossless V1 to V2 migration",
        paper_text=paper_text,
        provider="offline",
        model_revision=LEGACY_READER_ID,
        strategy="legacy-v1-offline-migration",
        quality_profile="requires-independent-audit",
        max_model_calls=0,
        subtree_concurrency=1,
        calls=[],
        partial_failures=[],
        repair_ledger=ledger.document(),
        source_artifact=source_artifact,
    )
    schema_errors = _validate_envelope(frozen)
    if schema_errors:
        return {
            "error": "migrated rubric does not satisfy V2",
            "warnings": schema_errors,
            "source_artifact": source_artifact,
        }
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(frozen, indent=2, ensure_ascii=False))
    return {
        "rubric_path": str(destination),
        "rubric_sha256": frozen["rubric_sha256"],
        "paper_sha256": frozen["paper_sha256"],
        "source_schema": LEGACY_READER_ID,
        "target_schema": frozen["schema_version"],
        "warnings": warnings,
    }


__all__ = ["LEGACY_READER_ID", "LEGACY_VERSION", "migrate_v1_to_v2"]
