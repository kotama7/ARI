"""Pinned Inspect adapter for SciCode and CORE-Bench official tasks."""

from __future__ import annotations

from pathlib import Path

from ari.assurance.drivers.external import LockedExternalDriver


INSPECT_DRIVER_REVISION = "ari.assurance.inspect/v1"
_ROUTES = {
    "science/scicode": "scicode.py",
    "science/core-bench": "core_bench",
}


class InspectDriver(LockedExternalDriver):
    revision = INSPECT_DRIVER_REVISION
    allowed_harness_ids = frozenset(_ROUTES)

    def validate_locked_argv(self, manifest, argv: tuple[str, ...]) -> None:
        if not argv or "eval" not in argv:
            raise ValueError("Inspect Harness must invoke the official inspect eval route")
        executable = Path(argv[0]).name
        if executable not in {"inspect", "uv"}:
            raise ValueError("Inspect Harness executable is not the reviewed CLI")
        route = _ROUTES[manifest.id]
        if not any(route in item for item in argv):
            raise ValueError("Inspect Harness task route differs from the registered upstream")


__all__ = ["INSPECT_DRIVER_REVISION", "InspectDriver"]
