"""Server capability flags for the dashboard (gui_refresh Wave 1).

``GET /api/capabilities`` lets the frontend discover which server-side
feature flags are active before it decides what shell/chrome to render.

``gui_v2`` is the ``ARI_GUI_V2`` server capability flag from the gui_refresh
feature-flag policy (``docs/plans/gui_refresh/10_migration_testing_release_
and_docs.md`` §Wave 1 / §Feature flag policy):

* owner: gui_refresh task 03 (application shell, routing, frontend state);
* default: ON — any value except ``'0'`` / ``'false'`` enables the v2 shell;
* rollback: export ``ARI_GUI_V2=0`` before launching ``ari viz`` — an env
  kill-switch, no redeploy/rebuild needed. The frontend then skips new shell
  chrome and v2-only routes (legacy routes/URLs are shared, so nothing else
  changes);
* metrics: none in Wave 1 (loopback tool; release telemetry is a later wave);
* removal gate: G6 (legacy removal) — delete the flag together with the
  legacy shell once the rollback window closes.

The frontend treats a failed fetch as ``gui_v2: true`` so an API hiccup can
never brick the loopback dashboard into the fallback shell.

The handler returns a plain ``dict``; ``routes.py`` serialises it via
``_json`` like every other ``api_*`` module.
"""

from __future__ import annotations

import os


def _api_capabilities() -> dict:
    """GET /api/capabilities — ``{"gui_v2": bool, "server_version": "wave1"}``."""
    gui_v2 = os.environ.get("ARI_GUI_V2", "1") not in ("0", "false")
    return {"gui_v2": gui_v2, "server_version": "wave1"}
