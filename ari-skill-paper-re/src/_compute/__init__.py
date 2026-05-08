"""Concrete :class:`ComputerInterface` implementations that run on ari's
existing HPC / local sandbox stack (Slurm / Apptainer / local) instead of
PaperBench upstream's Docker-based ``alcatraz``.

Public surface:

- :class:`LocalComputer`        — plain subprocess in a persistent work_dir.
- :class:`ApptainerComputer`    — subprocess wrapped with ``apptainer exec``.
- :func:`make_computer`         — factory honouring ``ARI_PHASE1_SANDBOX``.
"""

from __future__ import annotations

from .computer import (  # noqa: F401
    LocalComputer,
    ApptainerComputer,
    make_computer,
)
