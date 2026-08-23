"""Public facade for the ARI-native performance harnesses.

Mirrors ``ari.assurance.native_hpc``: it owns the instrument and the frozen
denominator's build rules but neither selects a Harness nor mutates RQGM state.
Production execution stays in the isolated driver.

What it no longer owns is the list of measurable problems. ``verify_native_perf``
took a name out of a ``Literal`` and looked it up in a dict written here; it now
takes a pinned problem revision, which is a directory under
``config/harnesses/problems/`` that nobody had to edit ARI to add.
"""

from __future__ import annotations

from pathlib import Path

from ari.assurance.native_perf_common import (
    NativePerfReportV1,
    PerfBuildError,
    PerfFamily,
    PerfInfrastructureError,
    PerfTier,
)
from ari.assurance.native_perf_family import get_family, registered_families
from ari.assurance.native_perf_measure import (DEFAULT_REGRESSION_THRESHOLD,
                                               resolve_problem,
                                               verify_performance)
from ari.assurance.problems import (LoadedProblemV1, ProblemError, load_problem,
                                    materialize, registered_problems)


def verify_native_perf(
    problem: str | LoadedProblemV1,
    candidate_source: str | Path,
    *,
    tier: PerfTier = "screen",
    seed: int = 0,
    **kwargs,
) -> NativePerfReportV1:
    """Measure a candidate against a pinned problem's frozen reference."""
    return verify_performance(problem, Path(candidate_source),
                              tier=tier, seed=seed, **kwargs)


def reference_source(problem: str | LoadedProblemV1) -> Path:
    """The problem's frozen reference.

    Also the natural clean control: scoring it as the candidate must give a ratio
    of about 1 -- provided it is built the reference's way, which it is not by
    default. See ``NativePerfDriver.parity_probe``.
    """
    loaded = resolve_problem(problem)
    return loaded.path(loaded.definition.scaffolding.reference)


def reference_flags(problem: str | LoadedProblemV1) -> tuple[str, ...]:
    """How the denominator is built. A property of the FAMILY, not the problem:
    a problem that could choose the reference's flags could choose its own bar."""
    loaded = resolve_problem(problem)
    return get_family(loaded.definition.family).reference_flags()


__all__ = [
    "DEFAULT_REGRESSION_THRESHOLD",
    "LoadedProblemV1",
    "NativePerfReportV1",
    "PerfBuildError",
    "PerfFamily",
    "PerfInfrastructureError",
    "ProblemError",
    "load_problem",
    "materialize",
    "reference_flags",
    "reference_source",
    "registered_families",
    "registered_problems",
    "resolve_problem",
    "verify_native_perf",
]
