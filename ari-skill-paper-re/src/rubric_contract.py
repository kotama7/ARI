"""Version negotiation and digest verification for replication rubrics."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


RUBRIC_V2 = "ari.replication-rubric/v2"
LEGACY_V1 = "ari.replication-rubric/legacy-v1"
PAPERBENCH_ENVELOPE_VERSION = "3"
_HEX64 = re.compile(r"^[a-f0-9]{64}$")


class RubricContractError(ValueError):
    """The rubric is unsupported, malformed, unbound, or tampered with."""


@dataclass(frozen=True)
class LoadedRubric:
    document: dict[str, Any]
    schema_version: str
    migration_required: bool


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise RubricContractError("rubric must contain finite JSON values") from exc


def compute_rubric_digest(document: dict[str, Any], *, legacy: bool) -> str:
    payload = copy.deepcopy(document)
    payload.pop("rubric_sha256", None)
    if legacy:
        # Legacy audits mutated the frozen envelope and were excluded from its
        # digest. V2 audits are separate artifacts and receive no exception.
        payload.pop("audit", None)
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def bind_rubric_digest(document: dict[str, Any], *, legacy: bool) -> dict[str, Any]:
    """Return a copy with the canonical digest bound (fixture/migration helper)."""

    bound = copy.deepcopy(document)
    bound["rubric_sha256"] = compute_rubric_digest(bound, legacy=legacy)
    return bound


def _validate_task_node(node: Any, path: str) -> None:
    if not isinstance(node, dict):
        raise RubricContractError(f"{path} must be a TaskNode object")
    if not isinstance(node.get("id"), str) or not node["id"]:
        raise RubricContractError(f"{path}.id is required")
    if not isinstance(node.get("requirements"), str) or not node["requirements"]:
        raise RubricContractError(f"{path}.requirements is required")
    if not isinstance(node.get("weight"), int) or node["weight"] < 0:
        raise RubricContractError(f"{path}.weight must be a non-negative integer")
    children = node.get("sub_tasks")
    if not isinstance(children, list):
        raise RubricContractError(f"{path}.sub_tasks must be an array")
    for index, child in enumerate(children):
        _validate_task_node(child, f"{path}.sub_tasks[{index}]")
    if not children and node.get("task_category") is None:
        raise RubricContractError(f"{path} leaf is missing task_category")


def _negotiate(document: dict[str, Any], allow_legacy: bool) -> tuple[str, bool]:
    schema_version = document.get("schema_version")
    bridge_version = document.get("version")
    if schema_version == RUBRIC_V2 and bridge_version == PAPERBENCH_ENVELOPE_VERSION:
        return RUBRIC_V2, False
    if schema_version is None and bridge_version == PAPERBENCH_ENVELOPE_VERSION:
        if not allow_legacy:
            raise RubricContractError(
                "legacy V1 rubric requires explicit offline migration to V2"
            )
        return LEGACY_V1, True
    raise RubricContractError(
        "unsupported rubric contract: expected ari.replication-rubric/v2 "
        "or the support-window unversioned V1 reader"
    )


def validate_rubric_document(
    document: Any,
    *,
    paper_text: str = "",
    allow_legacy: bool = True,
) -> LoadedRubric:
    if not isinstance(document, dict):
        raise RubricContractError("rubric envelope must be a JSON object")
    schema_version, migration_required = _negotiate(document, allow_legacy)
    legacy = schema_version == LEGACY_V1
    stored_digest = document.get("rubric_sha256")
    if not isinstance(stored_digest, str) or not _HEX64.fullmatch(stored_digest):
        raise RubricContractError("rubric_sha256 must be a lowercase SHA-256 digest")
    if compute_rubric_digest(document, legacy=legacy) != stored_digest:
        raise RubricContractError("rubric_sha256 does not match the rubric envelope")
    paper_digest = document.get("paper_sha256")
    if not isinstance(paper_digest, str) or not _HEX64.fullmatch(paper_digest):
        raise RubricContractError("paper_sha256 must be a lowercase SHA-256 digest")
    if paper_text:
        supplied_digest = hashlib.sha256(paper_text.encode("utf-8")).hexdigest()
        if supplied_digest != paper_digest:
            raise RubricContractError("paper text does not match rubric paper_sha256")
    contract = document.get("reproduce_contract")
    if not isinstance(contract, dict):
        raise RubricContractError("rubric is missing reproduce_contract")
    if contract.get("script_path", "reproduce.sh") != "reproduce.sh":
        raise RubricContractError("reproduce_contract.script_path must be reproduce.sh")
    _validate_task_node(document.get("rubric"), "rubric")
    if not legacy:
        generator = document.get("generator")
        if not isinstance(generator, dict):
            raise RubricContractError("V2 rubric is missing generator provenance")
        if not isinstance(document.get("repair_ledger"), dict):
            raise RubricContractError("V2 rubric is missing repair provenance")
        calls = generator.get("calls")
        strategy = generator.get("strategy")
        if strategy == "legacy-v1-offline-migration":
            if not isinstance(generator.get("source_artifact"), dict):
                raise RubricContractError(
                    "migrated V2 rubric is missing its legacy source artifact"
                )
        elif not isinstance(calls, list) or not calls:
            raise RubricContractError(
                "generated V2 rubric has no artifact-backed model-call records"
            )
    return LoadedRubric(
        document=copy.deepcopy(document),
        schema_version=schema_version,
        migration_required=migration_required,
    )


def load_rubric(
    rubric_path: str,
    *,
    paper_text: str = "",
    allow_legacy: bool = True,
) -> LoadedRubric:
    try:
        document = json.loads(Path(rubric_path).read_text())
    except Exception as exc:
        raise RubricContractError(f"cannot read rubric: {exc}") from exc
    return validate_rubric_document(
        document,
        paper_text=paper_text,
        allow_legacy=allow_legacy,
    )


def to_paperbench_format(document: dict[str, Any]) -> dict[str, Any]:
    keep = {
        "id",
        "requirements",
        "weight",
        "sub_tasks",
        "task_category",
        "finegrained_task_category",
    }

    def strip(node: dict[str, Any]) -> dict[str, Any]:
        output = {key: value for key, value in node.items() if key in keep}
        output["weight"] = int(node.get("weight", 1))
        output["sub_tasks"] = [strip(child) for child in node.get("sub_tasks") or []]
        return output

    root = document.get("rubric")
    if not isinstance(root, dict):
        raise RubricContractError("rubric envelope is missing its TaskNode root")
    return strip(root)


__all__ = [
    "LEGACY_V1",
    "RUBRIC_V2",
    "LoadedRubric",
    "RubricContractError",
    "bind_rubric_digest",
    "compute_rubric_digest",
    "load_rubric",
    "to_paperbench_format",
    "validate_rubric_document",
]
