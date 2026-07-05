"""Sanctioned funnel for the core→skill memory edge.

Together with the sibling ``letta_client.py`` and ``auto_migrate.py``, this
module is the **sole** place in ``ari-core`` that reaches into the
``ari-skill-memory`` package.  Every other ``ari-core`` module must obtain a
``MemoryBackend`` (or build verified context) through ``ari.memory`` — which
re-exports the forwards below — rather than importing ``ari_skill_memory``
directly.  This confines the one allowed core→skill dependency (introduced
v0.6.0) to ``ari/memory/**`` so a future import-boundary checker (subtask 026)
can allow-list a single directory instead of a dozen scattered files.

Design invariants (subtask 013):

- **Thin, identity-preserving forwards.** ``get_backend`` returns the *exact*
  ``ari_skill_memory.backends.MemoryBackend`` instance the skill factory would
  return — no wrapping — so callers keep the full rich API (``react_*``,
  ``list_all_nodes``, ``bulk_import``, ``purge_checkpoint`` …) and the
  per-checkpoint instance cache.
- **Lazy skill import.** ``ari_skill_memory`` is imported inside each function,
  never at module top, so ``import ari.memory`` succeeds even when the skill
  package is not installed (mirrors the pre-existing function-local pattern in
  the call sites this funnel replaces).
- **No new dependency.** ``ari_skill_memory`` stays out of ``ari-core``'s
  declared dependencies; it is editable-installed by ``setup.sh`` (see
  ``ari-core/pyproject.toml`` and ``.github/workflows/refactor-guards.yml``).

See ``ari/memory/__init__.py`` and ``ari/memory/README.md`` for the two-tier
``MemoryClient`` (narrow) → ``MemoryBackend`` (rich) contract.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ari_skill_memory.backends.base import MemoryBackend


def get_backend(
    checkpoint_dir: str | Path | None = None,
    *,
    reset: bool = False,
) -> MemoryBackend:
    """Return the per-checkpoint ``MemoryBackend`` (verbatim skill factory).

    Sole sanctioned forward to ``ari_skill_memory.backends.get_backend``.  The
    returned object and its per-checkpoint cache are identical to a direct skill
    call — do NOT wrap the result; callers rely on the full rich backend API.

    ``checkpoint_dir`` is forwarded by keyword and ``reset`` only when set, so
    the skill sees exactly the call shape the pre-funnel sites used
    (``get_backend(checkpoint_dir=...)``).
    """
    from ari_skill_memory.backends import get_backend as _get_backend
    if reset:
        return _get_backend(checkpoint_dir=checkpoint_dir, reset=True)
    return _get_backend(checkpoint_dir=checkpoint_dir)


def clear_backend_cache() -> None:
    """Drop cached backend instances (test/CLI use).

    Forwards to ``ari_skill_memory.backends.clear_backend_cache``.
    """
    from ari_skill_memory.backends import clear_backend_cache as _clear
    _clear()


def build_verified_context(
    backend: Any,
    ancestor_ids: list[str],
    *,
    purpose: str = "paper",
    limit: int | None = None,
) -> dict:
    """Forward to ``ari_skill_memory.context_builder.build_verified_context``.

    Keeps ``context_builder`` — a second skill module beyond ``backends`` — out
    of every non-``ari/memory`` caller (e.g. ``pipeline/verified_context.py``),
    so the funnel policy holds for the whole ``ari_skill_memory`` surface, not
    just its ``backends`` factory.
    """
    from ari_skill_memory import context_builder as _cb
    if limit is None:
        return _cb.build_verified_context(backend, ancestor_ids, purpose=purpose)
    return _cb.build_verified_context(
        backend, ancestor_ids, purpose=purpose, limit=limit
    )


__all__ = ["get_backend", "clear_backend_cache", "build_verified_context"]
