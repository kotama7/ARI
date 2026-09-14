"""Read-only conversion of pre-v1 Skill manifests.

Runtime discovery must use :func:`ari.skill_manifest.load_skill_manifest` and
therefore rejects unversioned documents.  This module is intentionally under the
migration namespace so old package metadata can be inspected and converted
without becoming an admission path again.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from ari.skill_manifest import (
    LEGACY_MCP_RESULT_V1,
    SkillManifestError,
    SkillManifestV1,
    load_skill_manifest,
)


def _legacy_document(raw: dict, path: Path) -> dict:
    package = path.parent.name
    entrypoint = raw.get("entrypoint", "src/server.py")
    if isinstance(entrypoint, str):
        entrypoint = {
            "transport": "stdio",
            "command_kind": raw.get("runtime", "python"),
            "module": entrypoint,
        }
    tools = []
    capability_prefix = package.removeprefix("ari-skill-").replace("-", ".")
    for tool in raw.get("tools") or []:
        if isinstance(tool, str):
            tools.append(
                {
                    "name": tool,
                    "capability_ref": f"ari.legacy.{capability_prefix}.{tool}",
                }
            )
        elif isinstance(tool, dict):
            tools.append(tool)
    return {
        "schema_version": 1,
        "name": raw.get("name") or package,
        "package": package,
        "version": str(raw.get("version") or "0.0.0"),
        "display_name": raw.get("display_name", ""),
        "description": raw.get("description", ""),
        "enabled_by_default": False,
        "environment_policy": "audit-pending",
        "entrypoint": entrypoint,
        "required_env": raw.get("required_env", raw.get("requires_env", [])) or [],
        "optional_env": raw.get("optional_env", []) or [],
        "tool_defaults": {
            "phases": ["all"],
            "side_effects": "stateful",
            "determinism": "conditional",
            "timeout_class": "default",
            "permissions": [],
            "context_requirement": "none",
            "result_schema": LEGACY_MCP_RESULT_V1,
        },
        "tools": tools,
    }


def load_legacy_skill_manifest(path: str | Path) -> SkillManifestV1:
    """Convert an old manifest in memory without admitting or rewriting it."""

    manifest_path = Path(path)
    try:
        raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise SkillManifestError(f"cannot read {manifest_path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise SkillManifestError(f"{manifest_path}: manifest root must be a mapping")
    if "schema_version" in raw:
        return load_skill_manifest(manifest_path)
    try:
        return SkillManifestV1.model_validate(_legacy_document(raw, manifest_path))
    except ValidationError as exc:
        raise SkillManifestError(
            f"cannot migrate legacy manifest {manifest_path}: {exc}"
        ) from exc


__all__ = ["load_legacy_skill_manifest"]
