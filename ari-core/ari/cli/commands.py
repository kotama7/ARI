"""Misc top-level Typer commands (Phase 3A).

Holds the assorted commands that don't fit the run/paper/projects
clusters: ``ari clone``, ``ari delete``, ``ari skills-list``, ``ari
viz``, ``ari settings``.  Plus the small ``_safe_backup`` helper that
``run`` / ``resume`` invoke at exit.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ari.config import load_config, auto_config
from ari.core import build_runtime as _real_build_runtime  # noqa: F401
from ari.paths import PathManager

from ari.cli import app, console


# Phase 3A — defer to ``ari.cli`` so test monkeypatches at the package
# surface flow into the misc command bodies.
def build_runtime(*args, **kwargs):
    from ari import cli as _cli
    return _cli.build_runtime(*args, **kwargs)


log = logging.getLogger(__name__)


# Phase 3A — defer the lookup so tests that patch the package surface
# (``mock.patch("ari.cli._resolve_cfg", ...)``) keep intercepting.
def _resolve_cfg(*args, **kwargs):
    from ari import cli as _cli
    return _cli._resolve_cfg(*args, **kwargs)




# ── ari clone ────────────────────────────────────────────────────────
# v0.7.0: fetch + verify + extract a curated EAR bundle.
@app.command("clone")
def cmd_clone(
    ref: str = typer.Argument(..., help="Bundle reference: file://, https://, ari://, gh:, doi:"),
    dest: Path | None = typer.Argument(None, help="Destination directory (default: derived from ref)"),
    expect_sha256: str | None = typer.Option(None, "--expect-sha256", help="Required bundle digest. Hard fail on mismatch."),
    no_extract: bool = typer.Option(False, "--no-extract", help="Just download the tarball; do not extract."),
    registry: str | None = typer.Option(None, "--registry", help="Limit ari:// to a named registry."),
    token: str | None = typer.Option(None, "--token", help="Bearer token (env var name OR literal value)."),
) -> None:
    """Fetch a curated EAR bundle and verify its digest. No code execution."""
    from ari.clone import clone, CloneError

    # Allow --token foo or --token ENV_VAR_NAME (env var lookup is convenient
    # so tokens never appear in shell history).
    real_token = None
    if token:
        real_token = os.environ.get(token, token)

    try:
        result = clone(
            ref,
            dest=dest,
            expect_sha256=expect_sha256,
            extract=not no_extract,
            registry=registry,
            token=real_token,
        )
    except CloneError as e:
        console.print(f"[red]ari clone failed:[/red] {e}")
        raise typer.Exit(2)
    except NotImplementedError as e:
        console.print(f"[yellow]{e}[/yellow]")
        raise typer.Exit(2)

    console.print(f"[green]cloned[/green] {ref} → {result.dest}")
    if result.bundle_sha256:
        console.print(f"  bundle_sha256: {result.bundle_sha256}")
    console.print(f"  files:         {result.file_count}")
    console.print(f"  extracted:     {result.extracted}")



def _safe_backup(checkpoint_dir: "Path | None") -> None:
    """On-exit backup wrapper — swallow errors so shutdown isn't blocked."""
    try:
        from ari.memory_cli import _do_backup
        _do_backup(Path(checkpoint_dir))
    except Exception as e:
        logging.getLogger(__name__).debug("exit-backup skipped: %s", e)



@app.command("delete")
def delete_project(
    checkpoint: str = typer.Argument(..., help="Checkpoint ID or path to delete"),
    checkpoints_dir: Path = typer.Option(Path("checkpoints"), help="Checkpoints base dir"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Delete a project checkpoint directory."""
    import shutil
    p = Path(checkpoint)
    if not p.exists():
        p = checkpoints_dir / checkpoint
    if not p.exists():
        console.print(f"[red]Not found: {checkpoint}[/red]")
        raise typer.Exit(1)
    if not yes:
        confirm = typer.confirm(f"Delete project {p.name}? This cannot be undone.")
        if not confirm:
            console.print("[yellow]Aborted.[/yellow]")
            raise typer.Exit(0)
    # clean up per-checkpoint Letta namespace first.
    # Failure does NOT block local deletion — orphaned Letta entries can be
    # swept later with `ari memory prune-local`.
    try:
        PathManager.set_checkpoint_dir_env(p)
        from ari_skill_memory.backends import get_backend, clear_backend_cache
        clear_backend_cache()
        get_backend(checkpoint_dir=p).purge_checkpoint()
        clear_backend_cache()
    except Exception as e:
        import logging as _lg
        _lg.getLogger(__name__).warning(
            "memory namespace cleanup failed: %s — proceeding with rmtree", e
        )
    shutil.rmtree(p)
    console.print(f"[green]✓ Deleted {p.name}[/green]")



@app.command("skills-list")
def skills_list(
    config: Path | None = typer.Option(None, help="Config YAML (auto-generated if omitted)"),
) -> None:
    """List available skills/tools."""
    from ari.mcp.client import MCPClient
    cfg = _resolve_cfg(config)
    mcp = MCPClient(cfg.skills)
    tools = mcp.list_tools()
    mcp.close_all()
    if not tools:
        console.print("[yellow]No skills registered.[/yellow]")
        return
    table = Table(title=f"Available Tools ({len(tools)} total)")
    table.add_column("Tool Name")
    table.add_column("Skill")
    table.add_column("Description")
    for tool in tools:
        desc = tool.get("description", "")
        table.add_row(tool.get("name", ""), tool.get("skill_name", ""),
                      (desc[:80] + "…") if len(desc) > 80 else desc)
    console.print(table)




@app.command()
def viz(
    checkpoint_dir: str = typer.Argument(..., help="Path to checkpoint directory"),
    port: int = typer.Option(8765, help="Port to serve on"),
):
    """Launch real-time experiment tree visualizer."""
    import threading
    import pathlib
    import ari.viz.server as viz_srv

    ckpt = pathlib.Path(checkpoint_dir).expanduser().resolve()
    if not ckpt.exists():
        console.print(f"[red]Checkpoint directory not found: {ckpt}[/red]")
        raise typer.Exit(1)

    console.print(f"[green]ARI Visualizer[/green] -> http://localhost:{port}/")
    console.print(f"Watching: {ckpt}")
    console.print("Press Ctrl+C to stop.")

    try:
        import asyncio
        asyncio.run(viz_srv._main(ckpt, port))
    except KeyboardInterrupt:
        pass



@app.command("settings")
def settings_cmd(
    config: Path = typer.Option(Path("config.yaml"), help="Config YAML"),
    set_model: str | None = typer.Option(None, "--model", help="Set LLM model"),
    set_key: str | None = typer.Option(None, "--api-key", help="Set API key"),
    set_partition: str | None = typer.Option(None, "--partition", help="Set SLURM partition"),
    set_cpus: int | None = typer.Option(None, "--cpus", help="Set SLURM CPUs"),
    set_mem: int | None = typer.Option(None, "--mem", help="Set SLURM memory (GB)"),
) -> None:
    """View or update ARI settings (config.yaml)."""
    import yaml as _yaml
    if not config.exists():
        console.print(f"[yellow]Config not found: {config}[/yellow]")
        raise typer.Exit(1)
    cfg_data = _yaml.safe_load(config.read_text()) or {}
    # Apply overrides
    changed = False
    if set_model:
        cfg_data.setdefault("llm", {})["model"] = set_model
        changed = True
    if set_key:
        cfg_data.setdefault("llm", {})["api_key"] = set_key
        changed = True
    if set_partition:
        cfg_data.setdefault("slurm", {})["partition"] = set_partition
        changed = True
    if set_cpus:
        cfg_data.setdefault("slurm", {})["cpus_per_task"] = set_cpus
        changed = True
    if set_mem:
        cfg_data.setdefault("slurm", {})["mem_gb"] = set_mem
        changed = True
    if changed:
        config.write_text(_yaml.dump(cfg_data, allow_unicode=True))
        console.print(f"[green]✓ Config updated: {config}[/green]")
    # Display current settings
    table = Table(title=f"Settings: {config}", show_header=False)
    table.add_column("Key", style="cyan")
    table.add_column("Value")
    def _flat(d, prefix=""):
        for k, v in d.items():
            if isinstance(v, dict):
                _flat(v, prefix=f"{prefix}{k}.")
            else:
                vstr = "***" if "key" in k.lower() or "password" in k.lower() else str(v)
                table.add_row(f"{prefix}{k}", vstr)
    _flat(cfg_data)
    console.print(table)

