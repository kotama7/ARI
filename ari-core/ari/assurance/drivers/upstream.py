"""Pinned official CLI wrappers for initial GPU/bio benchmark entries."""

from __future__ import annotations

from pathlib import Path

from ari.assurance.drivers.external import LockedExternalDriver


UPSTREAM_CLI_DRIVER_REVISION = "ari.assurance.upstream-cli/v1"
_MARKERS = {
    "gpu/kernelbench": ("run_and_check.py", "eval_from_generations.py"),
    "gpu/compute-eval": ("computeeval", "compute_eval"),
    "bio/scbench": ("scbench", "run_scbench"),
}


class UpstreamCLIDriver(LockedExternalDriver):
    revision = UPSTREAM_CLI_DRIVER_REVISION
    allowed_harness_ids = frozenset(_MARKERS)

    def validate_locked_argv(self, manifest, argv: tuple[str, ...]) -> None:
        if not argv or Path(argv[0]).name not in {"python", "python3", "uv"}:
            raise ValueError("upstream benchmark must use the reviewed CLI environment")
        joined = " ".join(argv).casefold()
        if not any(marker in joined for marker in _MARKERS[manifest.id]):
            raise ValueError("upstream benchmark route differs from its registered official runner")


__all__ = ["UPSTREAM_CLI_DRIVER_REVISION", "UpstreamCLIDriver"]
