"""Pinned Harbor adapter for ScienceAgentBench packaging."""

from __future__ import annotations

from pathlib import Path

from ari.assurance.drivers.external import LockedExternalDriver


HARBOR_DRIVER_REVISION = "ari.assurance.harbor/v1"


class HarborDriver(LockedExternalDriver):
    revision = HARBOR_DRIVER_REVISION
    allowed_harness_ids = frozenset({"science/scienceagentbench"})

    def validate_locked_argv(self, manifest, argv: tuple[str, ...]) -> None:
        if not argv or Path(argv[0]).name not in {"harbor", "uv"} or "run" not in argv:
            raise ValueError("Harbor Harness must invoke the official harbor run route")
        joined = " ".join(argv).casefold()
        if "scienceagentbench" not in joined and "science-agent-bench" not in joined:
            raise ValueError("Harbor dataset route is not ScienceAgentBench")


__all__ = ["HARBOR_DRIVER_REVISION", "HarborDriver"]
