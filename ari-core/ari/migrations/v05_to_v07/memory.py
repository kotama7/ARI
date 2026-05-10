"""v0.5 global JSONL → v0.6 checkpoint-scoped Letta migration (Phase 5).

The actual logic lives in :mod:`ari.memory.auto_migrate` and continues
to be invoked from there by ``ari run`` / ``ari resume`` (the canonical
hooks).  This module exists so callers that already understand the
migration package layout can ``from ari.migrations.v05_to_v07.memory
import maybe_auto_migrate`` without reaching back into the memory
implementation tree, and so v1.0 has a single home for the eventual
deletion.

This is the legitimate accessor of ``~/.ari/global_memory.jsonl`` —
all *other* code in ARI must avoid that path
(see :doc:`DEPRECATION_REMOVAL.md` tier A/B).
"""

from __future__ import annotations

from pathlib import Path

from ari.memory.auto_migrate import maybe_auto_migrate  # noqa: F401


# v0.5 used a single global JSONL file under ~/.ari.  Recorded here as a
# constant so call-sites can rely on a single, documented location and
# we can grep for the path during DR4 audits.
LEGACY_GLOBAL_PATH = Path.home() / ".ari" / "global_memory.jsonl"


__all__ = ["maybe_auto_migrate", "LEGACY_GLOBAL_PATH"]
