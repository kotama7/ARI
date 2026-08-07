"""Adapter identity for the existing PaperBench rollout→reproduce→judge bridge."""

from __future__ import annotations

from pathlib import Path

from ari.assurance.drivers.external import LockedExternalDriver


PAPERBENCH_DRIVER_REVISION = "ari.assurance.paperbench-bridge/v1"


class PaperBenchDriver(LockedExternalDriver):
    revision = PAPERBENCH_DRIVER_REVISION
    allowed_harness_ids = frozenset({"reproduction/paperbench"})

    def validate_locked_argv(self, manifest, argv: tuple[str, ...]) -> None:
        if not argv or Path(argv[0]).name not in {"python", "python3"}:
            raise ValueError("PaperBench Harness must use the reviewed Python environment")
        joined = " ".join(argv)
        if "paperbench_assurance_worker.py" not in joined:
            raise ValueError("PaperBench Harness must use ARI's existing-bridge worker")


__all__ = ["PAPERBENCH_DRIVER_REVISION", "PaperBenchDriver"]
