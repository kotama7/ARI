"""Deterministic EAR evidence hand-off helpers.

The large presentation-oriented EAR builder remains in the MCP adapter while
this module owns the immutable run/contract/evidence material copied into the
bundle.  Paths are closed and explicit; no directory is discovered from a
trace, command string, or model response.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path


class EarEvidenceError(RuntimeError):
    pass


_KNOWN_FILES: tuple[tuple[str, str], ...] = (
    ("SKILLS.lock", "locks/SKILLS.lock"),
    ("metric_contract.json", "contracts/metric_contract.json"),
    ("research_contract.json", "contracts/research_contract.json"),
    ("science_data.json", "contracts/science_data.json"),
    ("catalog/CATALOG.lock", "catalog/CATALOG.lock"),
    ("CATALOG.lock", "catalog/CATALOG.lock"),
    ("catalog/catalog-provenance.json", "catalog/catalog-provenance.json"),
    ("catalog/cassette-index.json", "catalog/cassette-index.json"),
    (
        "evaluation/claim_evidence_hard_gate_draft.json",
        "admission/claim_evidence_hard_gate_draft.json",
    ),
    (
        "evaluation/claim_evidence_hard_gate_final.json",
        "admission/claim_evidence_hard_gate_final.json",
    ),
    (
        "evaluation/evidence_grounded_semantic_review.json",
        "admission/evidence_grounded_semantic_review.json",
    ),
)

_TRANSFORM_OWNED_DIRS: tuple[str, ...] = (
    "locks",
    "contracts",
    "admission",
    "artifacts/mcp-results",
)

_TRANSFORM_GENERATED_SURFACES: tuple[str, ...] = (
    "README.md",
    "reproduce.sh",
    "environment.json",
    "evidence.index.json",
    "code",
    "data",
    "figures",
    *_TRANSFORM_OWNED_DIRS,
)


def _remove_owned_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)


def reset_transform_outputs(ear: Path) -> None:
    """Remove only transform-owned EAR outputs before deterministic rebuild.

    Author policy/license files and the registry-owned ``catalog/`` tree are
    intentionally preserved.  Everything generated from the current
    checkpoint is replaced so removed source files cannot survive a rerun.
    """

    if ear.is_symlink():
        raise EarEvidenceError(f"symbolic EAR root refused: {ear}")
    ear.mkdir(parents=True, exist_ok=True)
    for relative in _TRANSFORM_GENERATED_SURFACES:
        _remove_owned_path(ear / relative)


def _copy_verified_file(source: Path, destination: Path) -> bool:
    if not source.is_file() or source.is_symlink():
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = source.read_bytes()
    if destination.exists():
        if destination.is_symlink():
            raise EarEvidenceError(
                f"symbolic EAR evidence target refused: {destination}"
            )
        if destination.read_bytes() == payload:
            return False
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.write_bytes(payload)
    temporary.replace(destination)
    return True


def _copy_closed_tree(source: Path, destination: Path) -> int:
    if not source.is_dir() or source.is_symlink():
        return 0
    copied = 0
    for path in sorted(source.rglob("*")):
        if path.is_symlink():
            raise EarEvidenceError(f"symbolic EAR evidence source refused: {path}")
        if not path.is_file():
            continue
        relative = path.relative_to(source)
        if any(part in {"", ".", ".."} for part in relative.parts):
            raise EarEvidenceError("unsafe EAR evidence path")
        copied += int(_copy_verified_file(path, destination / relative))
    return copied


def materialize_ear_evidence(checkpoint: Path, ear: Path) -> dict:
    """Copy the exact locks/contracts/cassettes/results needed for replay."""

    if checkpoint.is_symlink() or ear.is_symlink():
        raise EarEvidenceError("symbolic checkpoint or EAR root refused")
    ear.mkdir(parents=True, exist_ok=True)
    # This helper owns these destinations. Clearing them first makes removal
    # from the source checkpoint observable in the next bundle.
    for relative in _TRANSFORM_OWNED_DIRS:
        _remove_owned_path(ear / relative)

    copied = 0
    seen_destinations: set[str] = set()
    for source_name, destination_name in _KNOWN_FILES:
        # The first CATALOG.lock location found wins deterministically.
        if destination_name in seen_destinations:
            continue
        source = checkpoint / source_name
        if _copy_verified_file(source, ear / destination_name):
            copied += 1
        if source.is_file() and not source.is_symlink():
            seen_destinations.add(destination_name)
    copied += _copy_closed_tree(
        checkpoint / "catalog" / "cassettes", ear / "catalog" / "cassettes"
    )
    copied += _copy_closed_tree(
        checkpoint / "catalog" / "raw-cassettes",
        ear / "catalog" / "raw-cassettes",
    )
    copied += _copy_closed_tree(
        checkpoint / "artifacts" / "mcp-results",
        ear / "artifacts" / "mcp-results",
    )

    records: list[dict] = []
    for path in sorted(item for item in ear.rglob("*") if item.is_file()):
        relative = path.relative_to(ear).as_posix()
        if relative == "evidence.index.json":
            continue
        payload = path.read_bytes()
        records.append(
            {
                "path": relative,
                "digest": "sha256:" + hashlib.sha256(payload).hexdigest(),
                "size_bytes": len(payload),
                "role": (
                    "skills-lock"
                    if relative == "locks/SKILLS.lock"
                    else "catalog-lock"
                    if relative == "catalog/CATALOG.lock"
                    else "cassette"
                    if "/cassettes/" in f"/{relative}"
                    else "result-envelope-artifact"
                    if relative.startswith("artifacts/mcp-results/")
                    else "admission"
                    if relative.startswith("admission/")
                    else "science-contract"
                    if relative.startswith("contracts/")
                    else "ear-output"
                ),
            }
        )
    index = {
        "schema_version": "ari.ear-evidence-index/v1",
        "records": records,
    }
    encoded = (
        json.dumps(index, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")
    index["index_digest"] = "sha256:" + hashlib.sha256(encoded).hexdigest()
    index_path = ear / "evidence.index.json"
    temporary = index_path.with_name(index_path.name + ".tmp")
    temporary.write_text(
        json.dumps(index, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(index_path)
    return {"copied": copied, "record_count": len(records), "index": index}


__all__ = [
    "EarEvidenceError",
    "materialize_ear_evidence",
    "reset_transform_outputs",
]
