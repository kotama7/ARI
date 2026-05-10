"""CLI entry point — a thin wrapper with zero domain knowledge.

All construction logic is delegated to ari.core.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

from ari.config import load_config, auto_config
from ari.core import build_runtime, generate_paper_section
from ari.paths import PathManager
from ari.pipeline import _extract_plan_sections


# ---------------------------------------------------------------------------
# lineage decision config + executor (extracted to ari.cli.lineage in Phase 3A)
# ---------------------------------------------------------------------------

from ari.cli.lineage import (
    _LINEAGE_LOG,
    _load_lineage_decision_config,
    _mark_parent_terminated,
    _execute_lineage_decision,
    _build_idea_ctx_for_expand,
)

app = typer.Typer(name="ari", help="ARI - Artificial Research Intelligence")
console = Console()

# `ari memory` subparser.
try:
    from ari.memory_cli import memory_app as _memory_app
    app.add_typer(_memory_app, name="memory")
except Exception as _e:  # pragma: no cover - import guard
    logging.getLogger(__name__).warning("ari memory subcommand unavailable: %s", _e)

# `ari ear` subparser (curation/publish/promote/status).
try:
    from ari.cli_ear import ear_app as _ear_app
    app.add_typer(_ear_app, name="ear")
except Exception as _e:  # pragma: no cover - import guard
    logging.getLogger(__name__).warning("ari ear subcommand unavailable: %s", _e)

# `ari registry` subparser (server admin — only loaded when CLI is invoked).
try:
    from ari.registry.cli import registry_app as _registry_app
    app.add_typer(_registry_app, name="registry")
except Exception as _e:  # pragma: no cover - import guard
    logging.getLogger(__name__).warning("ari registry subcommand unavailable: %s", _e)


# ── ari migrate ───────────────────────────────────────────────────────
# v0.7.0: best-effort backfill of node_report.json into legacy checkpoints.
# Implementation lives in ``ari.cli.migrate`` (Phase 3A extraction).
from ari.cli.migrate import migrate_app, cmd_migrate_node_reports
app.add_typer(migrate_app, name="migrate")
# Phase 3A — Typer commands + helpers extracted into sibling modules.
# Importing the modules below registers their commands on ``app``.
from ari.cli.run import (  # noqa: F401
    _apply_profile,
    _resolve_cfg,
    _setup_logging,
    run,
    resume,
)
from ari.cli.projects import (  # noqa: F401
    list_projects,
    paper,
    show_project,
    status,
)
from ari.cli.commands import (  # noqa: F401
    _safe_backup,
    cmd_clone,
    delete_project,
    settings_cmd,
    skills_list,
    viz,
)

# Phase 3A — BFTS run-loop + checkpoint persistence extracted to
# ``ari.cli.bfts_loop``.
from ari.cli.bfts_loop import (  # noqa: F401
    _save_tree_incremental,
    _run_loop,
    _save_checkpoint,
)


# Phase 3A — restore the pre-split ``--help`` ordering.  The Typer
# decorators on each sub-module register commands in import order,
# but the canonical user-facing order is fixed: clone first, then
# run/resume/paper/status, then skills-list/viz, then projects/show
# /delete/settings.  We reorder ``app.registered_commands`` here so
# the ``ari --help`` output is byte-identical to the pre-Phase-3A
# baseline regardless of which sub-module owns the body.
def _reorder_commands_for_compat() -> None:
    canonical = [
        # First the legacy ``cmd_clone`` (originally line 76 of
        # ``cli.py``).
        "cmd_clone",
        "run",
        "resume",
        "paper",
        "status",
        "skills_list",
        "viz",
        "list_projects",
        "show_project",
        "delete_project",
        "settings_cmd",
    ]
    by_callback = {c.callback.__name__: c for c in app.registered_commands if c.callback is not None}
    ordered = [by_callback[n] for n in canonical if n in by_callback]
    extras = [c for c in app.registered_commands if c not in ordered]
    app.registered_commands[:] = ordered + extras


_reorder_commands_for_compat()


if __name__ == "__main__":
    app()
