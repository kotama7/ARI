"""Constants used only by the explicit offline v0.5 memory migrator.

Runtime migration was removed: ``ari run`` and ``ari resume`` never inspect or
rename legacy memory files. Operators must invoke ``ari memory migrate`` before
launching a supported checkpoint.

This is the legitimate accessor of ``~/.ari/global_memory.jsonl`` —
all *other* code in ARI must avoid that path
(see :doc:`DEPRECATION_REMOVAL.md` tier A/B).
"""

from __future__ import annotations

from pathlib import Path

# v0.5 used a single global JSONL file under ~/.ari.  Recorded here as a
# constant so call-sites can rely on a single, documented location and
# we can grep for the path during DR4 audits.
LEGACY_GLOBAL_PATH = Path.home() / ".ari" / "global_memory.jsonl"


__all__ = ["LEGACY_GLOBAL_PATH"]
