"""Small stateful bridge between MCP discovery and the run lock contract."""

from __future__ import annotations

from pathlib import Path

from ari.config import SkillConfig
from ari.skill_lock import (
    SkillsLockV1,
    build_skills_lock,
    verify_skills_lock_subset,
    write_or_verify_skills_lock,
)


class SkillLockController:
    """Own lock configuration and the snapshot reconciled for one MCP client."""

    def __init__(
        self,
        path: str | Path | None,
        *,
        scope: str,
        strict_provider_loading: bool | None,
    ) -> None:
        if scope not in {"exact", "subset"}:
            raise ValueError("skill_lock_scope must be 'exact' or 'subset'")
        self.path = Path(path) if path else None
        self.scope = scope
        self.strict_provider_loading = (
            self.path is not None
            if strict_provider_loading is None
            else strict_provider_loading
        )
        self.snapshot: SkillsLockV1 | None = None

    def reconcile(
        self,
        *,
        skills: list[SkillConfig],
        tools: list[dict],
        disabled_tools: set[str],
    ) -> SkillsLockV1 | None:
        """Create/verify an exact snapshot or verify a stage-worker subset."""

        if self.path is None:
            return None
        current = build_skills_lock(
            run_id=self.path.parent.name,
            skills=skills,
            tools=tools,
            disabled_tools=disabled_tools,
        )
        if self.scope == "subset":
            self.snapshot = verify_skills_lock_subset(self.path, current)
        else:
            self.snapshot = write_or_verify_skills_lock(self.path, current)
        return self.snapshot

    def clear(self) -> None:
        """Forget a failed reconciliation without altering the on-disk lock."""

        self.snapshot = None


__all__ = ["SkillLockController"]
