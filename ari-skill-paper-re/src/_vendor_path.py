"""Inject vendored PaperBench / nanoeval / preparedness_turn_completer onto sys.path.

The vendor tree is a git submodule at ``vendor/paperbench/``. Rather than
running editable pip installs of the vendored packages (which would require
network access for ``chz`` and care around environment isolation), we inject
the three relevant project roots onto :data:`sys.path` at import time. This
mirrors the pre-existing pattern in :mod:`_paperbench_bridge` (which only
injected the paperbench root) and extends it to cover the dependencies that
the BasicAgent / IterativeAgent solver pulls in.

Idempotent — safe to ``import _vendor_path`` from multiple modules; re-injection
is a no-op.

Override ``ARI_PAPERBENCH_PATH`` env var to point at a non-vendored
``project/paperbench`` directory (e.g. an editable install elsewhere).
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

log = logging.getLogger(__name__)


def _candidate_root() -> Path | None:
    """Resolve the ``vendor/paperbench/project`` root.

    Honours ``ARI_PAPERBENCH_PATH`` if set; otherwise falls back to the
    submodule at ``ari-skill-paper-re/vendor/paperbench/project/paperbench``
    (the same location :mod:`_paperbench_bridge` historically used).
    """
    override = os.environ.get("ARI_PAPERBENCH_PATH", "").strip()
    if override:
        p = Path(override).expanduser().resolve()
        if p.name == "paperbench" and p.parent.name == "project":
            return p.parent
        return p
    here = Path(__file__).resolve().parents[1]
    project = here / "vendor" / "paperbench" / "project"
    return project if project.is_dir() else None


def _inject() -> list[str]:
    """Push the three vendored package roots onto sys.path. Returns the
    paths actually added."""
    project = _candidate_root()
    if project is None:
        log.warning(
            "vendor/paperbench/ not found — agent-mode replicator will fail "
            "to import. Did you forget `git submodule update --init --recursive`?"
        )
        return []
    roots = [
        project / "paperbench",
        project / "common" / "nanoeval",
        project / "common" / "preparedness_turn_completer",
    ]
    added: list[str] = []
    for r in roots:
        s = str(r)
        if r.is_dir() and s not in sys.path:
            sys.path.insert(0, s)
            added.append(s)
    if added:
        log.info("paperbench vendor injected: %s", added)
    return added


# Inject on import.
_INJECTED: list[str] = _inject()
