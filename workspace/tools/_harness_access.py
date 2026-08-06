"""Reach a task harness the way the scorer does — through the registry.

WHY THIS EXISTS. Eight programs in this directory used to reach a harness with
``sys.path.insert(...)`` + ``__import__(f"{task}_harness")``. That import skips
``ari.harness_registry.load()``, and with it every sha256 pin and the manifest
self-digest, so these tools would happily measure a harness the registry would
refuse to score. It is not idle tooling: ``measure_resolution_band.py`` produces
the band that is copied into ``[declares].resolves``, the field
``harness_select`` accepts or refuses a study on. The number that certifies the
instrument was being produced by an unverified copy of the instrument.

WHAT YOU GET. ``verified_harness(task)`` returns ``(harness, mod)``:

* ``harness`` — the registry's :class:`ari.harness_registry.Harness`. Prefer it.
  ``harness.measure(work_dir, **overrides)`` applies the manifest's own
  ``[measure_kwargs]``, so a tool no longer restates the scored problem size and
  cannot drift from it.
* ``mod`` — a read-only view of the harness module's namespace, for the internals
  a tool legitimately needs (``_compile_kernel``, ``_REFERENCE_CFLAGS``,
  ``gen_problem``, the cached oracles). Reading is faithful: these are the same
  objects the harness itself uses. REBINDING an attribute on this view does NOT
  reach the harness — monkeypatch the module, not this.

Either way ``load()`` has already run, so a modified harness raises
``HarnessIntegrityError`` here exactly as it would during scoring.
"""
from __future__ import annotations

import pathlib
import sys
import types
from typing import Any

REPO = pathlib.Path(__file__).resolve().parents[2]


def _ensure_ari_importable() -> None:
    p = str(REPO / "ari-core")
    if p not in sys.path:
        sys.path.insert(0, p)


def verified_harness(task: str) -> tuple[Any, types.SimpleNamespace]:
    """Load *task* through the registry; return ``(harness, module_view)``.

    Raises ``ari.harness_registry.HarnessIntegrityError`` when a pinned file, or
    the manifest itself, no longer matches what it was pinned as.
    """
    _ensure_ari_importable()
    from ari.harness_registry import load

    harness = load(task)
    # _import_entry() builds the module with spec_from_file_location and does not
    # register it in sys.modules (a harness POOL would collide on the name), so
    # the module object is not retrievable by name. A function's __globals__ IS
    # its module's __dict__, which is the namespace we want.
    view = types.SimpleNamespace(**harness._measure_node.__globals__)
    return harness, view


def verified_module(task: str) -> types.SimpleNamespace:
    """``verified_harness(task)[1]`` — for tools that only need the internals."""
    return verified_harness(task)[1]
