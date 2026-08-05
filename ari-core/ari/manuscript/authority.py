"""Frozen authority projection inherited by manuscript repair requests."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ari.manuscript.digest import canonical_digest, file_digest


_AUTHORITY_FILES = (
    "SKILLS.lock",
    "launch_config.json",
    "workflow.yaml",
    "idea.json",
    "rqgm/kca/admission-v1/admission.json",
    "rqgm/kca/admission-v1/knowledge_skill_lock.json",
    "rqgm/kca/admission-v1/capability_binding_lock.json",
    "rqgm/kca/admission-v1/baseline_harness_lock.json",
)


def capture_repair_authority(
    checkpoint_dir: str | Path,
    *,
    run_id: str,
) -> dict[str, Any]:
    """Capture identities, never credentials or ambient authority."""

    checkpoint = Path(checkpoint_dir).resolve()
    artifacts: list[dict[str, Any]] = []
    for relative in _AUTHORITY_FILES:
        path = checkpoint / relative
        if path.is_file() and not path.is_symlink():
            digest, size = file_digest(path)
            artifacts.append(
                {
                    "relative_path": relative,
                    "status": "present",
                    "digest": digest,
                    "size_bytes": size,
                }
            )
        else:
            artifacts.append({"relative_path": relative, "status": "absent"})
    payload: dict[str, Any] = {
        "schema_version": "ari.manuscript-repair-authority/v1",
        "run_id": run_id,
        "artifacts": artifacts,
        "modes": {
            "knowledge": os.environ.get("ARI_MANUSCRIPT_KNOWLEDGE_MODE", "off"),
            "capability_binding": os.environ.get(
                "ARI_MANUSCRIPT_CAPABILITY_MODE", "legacy"
            ),
            "assurance": os.environ.get("ARI_MANUSCRIPT_ASSURANCE_MODE", "off"),
            "exploration": os.environ.get(
                "ARI_MANUSCRIPT_EXPLORATION_MODE", "simple_bfts"
            ),
        },
        "credential_material_included": False,
        "authority_semantics": "inherit-only-no-expansion-v1",
    }
    payload["authority_digest"] = canonical_digest(payload)
    return payload


def validate_repair_authority(value: dict[str, Any]) -> str:
    if value.get("schema_version") != "ari.manuscript-repair-authority/v1":
        raise ValueError("unknown manuscript repair authority schema")
    advertised = value.get("authority_digest")
    expected = canonical_digest(
        {key: item for key, item in value.items() if key != "authority_digest"}
    )
    if advertised != expected:
        raise ValueError("manuscript repair authority digest mismatch")
    if value.get("credential_material_included") is not False:
        raise ValueError("repair authority snapshot must not contain credentials")
    return expected


__all__ = ["capture_repair_authority", "validate_repair_authority"]
