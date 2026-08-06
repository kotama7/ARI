"""Offline migration for pre-PaperBuild rubric selection.

The runtime deliberately does not inspect ``ARI_RUBRIC`` or guess a default.
Operators can run this helper while migrating an old launch/workflow document,
then persist the returned ``paper_rubric`` field as an explicit input.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

try:
    from src.rubric import load_rubric
except ImportError:  # running from within src/
    from rubric import load_rubric  # type: ignore


def migrate_legacy_rubric_selection(
    config: Mapping[str, Any],
    *,
    legacy_environment: Mapping[str, str] | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Return a copy with an explicit, validated ``paper_rubric`` selection."""

    migrated = dict(config)
    environment = legacy_environment or {}
    selected = str(migrated.get("paper_rubric") or "").strip()
    source = "paper_rubric"
    if not selected:
        selected = str(migrated.pop("rubric_id", "") or "").strip()
        source = "rubric_id"
    if not selected:
        selected = str(environment.get("ARI_RUBRIC") or "").strip()
        source = "ARI_RUBRIC"
    if not selected:
        selected = "neurips"
        source = "pre-v1-default"
    rubric = load_rubric(selected)
    migrated["paper_rubric"] = rubric.id
    return migrated, {
        "schema_version": "ari.paper-rubric-migration/v1",
        "source": source,
        "rubric_id": rubric.id,
        "rubric_version": rubric.version,
        "rubric_digest": "sha256:" + rubric.hash,
    }


__all__ = ["migrate_legacy_rubric_selection"]
