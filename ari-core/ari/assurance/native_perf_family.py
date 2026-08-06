"""The one thing a problem cannot express as data, and how it is registered.

A problem definition supplies files and text. It cannot supply "generate a pair
of random matrices with the right shapes" or "the per-element backward-error
bound for a dense GEMM" — those are code. If that code were selected by a name
in a ``Literal`` inside ARI, we would be back where we started: adding a research
theme would mean editing core.

So a family is REGISTERED, like a driver is, and a problem names one. The split
is deliberate and it is where the free/governed line falls:

  * adding a PROBLEM — new sizes, new scaffolding, a new question in an existing
    family — is a directory, no ARI edit, no signature;
  * adding a FAMILY — a kind of mathematics ARI has never measured, needing a new
    generator and a new oracle — is an ARI change, reviewed like any other.

A family is also the narrow place where an oracle lives, which is why it is not
data: an oracle that a problem file could supply would be an oracle a problem
file could weaken, and the whole reason problems can go unapproved is that they
cannot reach the instrument.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from ari.assurance.native_perf_common import PerfInfrastructureError


@runtime_checkable
class PerfFamilyPlugin(Protocol):
    """Everything the generic measurement loop cannot know on its own.

    Deliberately small. Everything else — compiling, flag screening, the timed
    window, ordering the launches, the two denominators, the placement record —
    is the instrument's and is identical for every family, because that is what
    makes two families' numbers readable next to each other.
    """

    #: Matches ``problem.family`` and a case set's ``kind``.
    name: str

    def reference_flags(self) -> tuple[str, ...]:
        """How a competent user of this toolchain would build the denominator."""

    def generate(self, case: tuple[int, ...], seed: int) -> Any:
        """A fresh problem instance. Opaque to the loop; passed back to ``check``."""

    def write(self, path: Path, instance: Any) -> None:
        """Serialize the instance into the file the frozen driver reads."""

    def output_elements(self, case: tuple[int, ...]) -> int:
        """How many fp64 the candidate must write. A short write is a failure,
        not a fast kernel."""

    def check(self, output: Any, case: tuple[int, ...], instance: Any,
              ) -> tuple[bool, float]:
        """``(within_bound, worst_ratio_to_the_bound)`` for the candidate output."""


_FAMILIES: dict[str, PerfFamilyPlugin] = {}


def register_family(plugin: PerfFamilyPlugin) -> PerfFamilyPlugin:
    """Register a family. Re-registering the same name is refused.

    Silently replacing would let an import order decide which oracle judged a
    run, which is the kind of thing that is invisible until a result is wrong.
    """
    name = getattr(plugin, "name", "")
    if not name:
        raise PerfInfrastructureError("a performance family must have a name")
    existing = _FAMILIES.get(name)
    if existing is not None and existing is not plugin:
        raise PerfInfrastructureError(
            f"performance family {name!r} is already registered; two oracles "
            f"under one name would make the judging one an import-order accident")
    _FAMILIES[name] = plugin
    return plugin


def get_family(name: str) -> PerfFamilyPlugin:
    _load_builtin_families()
    try:
        return _FAMILIES[name]
    except KeyError:
        raise PerfInfrastructureError(
            f"no registered performance family {name!r}; a problem names a "
            f"family that supplies its generator and oracle. Known: "
            f"{sorted(_FAMILIES)}") from None


def registered_families() -> tuple[str, ...]:
    _load_builtin_families()
    return tuple(sorted(_FAMILIES))


def _load_builtin_families() -> None:
    """Import the families ARI ships. Idempotent and import-cycle safe."""
    import importlib

    for module in ("ari.assurance.native_perf_gemm",
                   "ari.assurance.native_perf_spmm",
                   "ari.assurance.native_perf_stencil"):
        try:
            importlib.import_module(module)
        except ImportError:                    # a family ARI does not ship yet
            continue


__all__ = ["PerfFamilyPlugin", "get_family", "register_family",
           "registered_families"]
