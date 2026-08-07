"""What a correctness family supplies, and how it is registered.

THE SAME SPLIT THE PERFORMANCE SIDE MAKES, applied here. A correctness verifier
cannot be data: "the hidden case set for a dense GEMM" and "the per-element
backward-error bound that decides whether an answer counts" are code, and so is
the ctypes marshalling that calls a candidate's ABI for one kernel signature.

What was wrong was not that this code exists but that the SET of it was written
out in five places -- a Literal, two dispatch dicts and two argparse ``choices``
tuples -- so ARI core enumerated the answerable questions and adding one meant
finding all five. A family registers itself now, and every dispatch site asks
the registry.

This does NOT make correctness families free the way problems are: adding a
family is still an ARI change, reviewed like any other, because an oracle a
caller could supply would be an oracle a caller could weaken. It makes the set
declared in one place per family instead of five places per set.
"""

from __future__ import annotations

from typing import Any, Callable, Protocol, runtime_checkable


class NativeFamilyError(RuntimeError):
    """A correctness family is unknown, or registered twice."""


@runtime_checkable
class NativeFamilyPlugin(Protocol):
    """The three things a correctness family owns."""

    #: Matches the ``kind`` a manifest and a worker name.
    name: str

    def verify(self, candidate: Callable, *, tier: str = "screen",
               seed: int | None = None, negative_control: bool = False) -> Any:
        """Run the hidden cases against ``candidate`` and judge the output."""

    def reference(self, case: dict[str, Any]) -> list[float]:
        """The independent implementation. Also the parity probe's clean control."""

    def call_shared_library(self, path, case: dict[str, Any]):
        """Invoke a candidate shared library through this kernel's ABI."""


_FAMILIES: dict[str, Any] = {}


def register_native_family(plugin: Any) -> Any:
    """Register a correctness family. Re-registering a name is refused.

    Silently replacing would let an import order decide which oracle judged a
    run, which stays invisible until a verdict is wrong.
    """
    name = getattr(plugin, "name", "")
    if not name:
        raise NativeFamilyError("a correctness family must have a name")
    existing = _FAMILIES.get(name)
    if existing is not None and existing is not plugin:
        raise NativeFamilyError(
            f"correctness family {name!r} is already registered; two oracles "
            f"under one name would make the judging one an import-order accident")
    _FAMILIES[name] = plugin
    return plugin


def get_native_family(name: str) -> Any:
    _load_builtin_families()
    try:
        return _FAMILIES[name]
    except KeyError:
        raise NativeFamilyError(
            f"unsupported native Harness kind: {name!r}; known: "
            f"{sorted(_FAMILIES)}") from None


def registered_native_families() -> tuple[str, ...]:
    """Every family ARI ships. Also what a worker validates ``--kind`` against,
    so the accepted set and the dispatchable set cannot drift apart."""
    _load_builtin_families()
    return tuple(sorted(_FAMILIES))


def _load_builtin_families() -> None:
    """Import the families ARI ships. Idempotent and import-cycle safe."""
    import importlib

    for module in ("ari.assurance.native_hpc_gemm",
                   "ari.assurance.native_hpc_spmm",
                   "ari.assurance.native_hpc_stencil"):
        try:
            importlib.import_module(module)
        except ImportError:                    # a family ARI does not ship yet
            continue


__all__ = [
    "NativeFamilyError",
    "NativeFamilyPlugin",
    "get_native_family",
    "register_native_family",
    "registered_native_families",
]
