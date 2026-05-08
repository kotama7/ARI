"""``ari migrate`` Typer sub-app (Phase 3A — extracted from cli.py).

The single command lives here so the master ``cli/__init__.py`` does not
have to carry the v0.5→v0.7 backfill body.  Phase 5 will move the
underlying logic into ``ari/migrations/v05_to_v07/`` and leave a thin
shim at ``ari.orchestrator.node_report.reconstruct_report_from_legacy``
that this command continues to call; the CLI surface stays the same.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import typer
from rich.console import Console

from ari.paths import PathManager


migrate_app = typer.Typer(name="migrate", help="One-shot data migrations.")
console = Console()


@migrate_app.command("node-reports")
def cmd_migrate_node_reports(
    checkpoint: Path = typer.Argument(..., help="Checkpoint directory to backfill."),
    overwrite: bool = typer.Option(False, "--overwrite",
                                   help="Re-write node_report.json even if one already exists."),
) -> None:
    """Backfill `node_report.json` for every node in a legacy checkpoint.

    Best-effort: fields we cannot recover (original_direction,
    delta_vs_parent, next_steps_hints) are nulled, and migration_source is
    set to "auto" so downstream filters know the report is not first-class.
    """
    from ari.orchestrator import node_report as _nr

    checkpoint = checkpoint.resolve()
    if not checkpoint.is_dir():
        console.print(f"[red]not a directory: {checkpoint}[/red]")
        raise typer.Exit(2)

    tree_path = checkpoint / "tree.json"
    if not tree_path.is_file():
        console.print(f"[red]no tree.json under {checkpoint}[/red]")
        raise typer.Exit(2)

    try:
        tree = json.loads(tree_path.read_text())
    except Exception as exc:
        console.print(f"[red]failed to read tree.json: {exc}[/red]")
        raise typer.Exit(2)

    nodes = tree.get("nodes") or []
    run_id = tree.get("run_id") or checkpoint.name

    pm = PathManager.from_checkpoint_dir(checkpoint)
    by_id = {n.get("id"): n for n in nodes}

    written = 0
    skipped = 0
    failed = 0

    for node_dict in nodes:
        nid = node_dict.get("id")
        if not nid:
            continue
        work_dir = pm.node_work_dir(run_id, nid)
        out_path = work_dir / "node_report.json"
        if out_path.exists() and not overwrite:
            skipped += 1
            continue
        parent_id = node_dict.get("parent_id")
        parent_wd = pm.node_work_dir(run_id, parent_id) if parent_id else None
        if parent_wd is not None and not parent_wd.is_dir():
            parent_wd = None
        try:
            report = _nr.reconstruct_report_from_legacy(
                node_dict=node_dict,
                work_dir=work_dir if work_dir.is_dir() else None,
                parent_work_dir=parent_wd,
            )
            work_dir.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
            written += 1
        except Exception as exc:
            logging.getLogger(__name__).warning("migrate %s failed: %s", nid, exc)
            failed += 1

    console.print(
        f"[green]migrated[/green] {written} node(s); "
        f"skipped={skipped} failed={failed} (run_id={run_id})"
    )
