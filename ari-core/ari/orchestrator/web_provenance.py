"""BFTS web-access provenance marker.

When the operator opts into web search during BFTS node exploration
(``ARI_BFTS_ALLOW_WEB`` / ``bfts.allow_web``), the search trajectory is no
longer guaranteed reproducible: live web / search results are time-varying, so
re-running the same experiment may explore a different tree. This module writes
(and reads) a small ``bfts_web_provenance.json`` marker at the checkpoint root
so the fact is durably auditable and downstream reproducibility tooling can
surface the trajectory caveat.

This mirrors the v0.6.0 precedent where the memory backend is recorded so
trajectory divergence stays interpretable — see ``docs/concepts/PHILOSOPHY.md``
(P5, reproducibility-first). The default-off path never writes this file, so a
reproducible run leaves no marker (absence == reproducible loop).
"""

from __future__ import annotations

import json
from pathlib import Path

_FILENAME = "bfts_web_provenance.json"

_NOTE = (
    "Web / search tools were exposed to the BFTS node agent (opt-in via "
    "ARI_BFTS_ALLOW_WEB / bfts.allow_web). Live web results are time-varying, "
    "so the BFTS search trajectory is NOT guaranteed reproducible across "
    "re-runs. See docs/concepts/PHILOSOPHY.md (P5)."
)


def write_provenance(checkpoint_dir: Path | str) -> dict:
    """Write ``bfts_web_provenance.json`` recording web-on-bfts. Best-effort.

    Returns the dict that was written (returned even when the disk write
    fails, so the caller can still log the same payload).
    """
    info = {
        "web_search_enabled_during_bfts": True,
        "trajectory_reproducible": False,
        "note": _NOTE,
    }
    out = Path(checkpoint_dir) / _FILENAME
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(info, indent=2))
    except OSError:
        pass
    return info


def read_provenance(checkpoint_dir: Path | str) -> dict:
    """Read ``bfts_web_provenance.json`` if present, else ``{}``.

    Returns ``{}`` when the file is missing or unparseable. The absence of the
    file means web search was not enabled during BFTS (reproducible loop).
    """
    p = Path(checkpoint_dir) / _FILENAME
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
