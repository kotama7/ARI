"""`ari memory` subcommand.

Wired into the main Typer app in ``ari.cli`` as a sub-app. Commands:

  ari memory migrate         one-shot import of v0.5.x JSONL → Letta
  ari memory backup          snapshot Letta collections to checkpoint
  ari memory restore         inverse of backup
  ari memory start-local     bring up local Letta (docker/singularity/pip)
  ari memory stop-local      kill local Letta
  ari memory prune-local     remove local Letta data
  ari memory compact-access  summarise rotated memory_access.jsonl files
  ari memory health          proxy for backend.health()
"""
from __future__ import annotations

import gzip
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import typer
from rich.console import Console

log = logging.getLogger(__name__)
memory_app = typer.Typer(name="memory", help="Letta memory admin commands")
console = Console()


def _resolve_ckpt(path: "str | Path | None", scan: bool = False) -> Path:
    if path is None:
        env = os.environ.get("ARI_CHECKPOINT_DIR", "").strip()
        if env:
            return Path(env).expanduser().resolve()
        raise typer.BadParameter(
            "--checkpoint is required (no ARI_CHECKPOINT_DIR in env)"
        )
    return Path(path).expanduser().resolve()


def _get_backend(checkpoint_dir: Path):
    os.environ["ARI_CHECKPOINT_DIR"] = str(checkpoint_dir)
    from ari_skill_memory.backends import get_backend
    return get_backend(checkpoint_dir=checkpoint_dir)


# ─ migrate ────────────────────────────────────────────────────────────

@memory_app.command("migrate")
def migrate_cmd(
    checkpoint: "Path | None" = typer.Option(None, help="Checkpoint directory"),
    react: bool = typer.Option(False, "--react", help="Also migrate memory.json"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Import v0.5.x JSONL data into the checkpoint's Letta collections."""
    ckpt = _resolve_ckpt(checkpoint)
    if not ckpt.is_dir():
        console.print(f"[red]Not a directory: {ckpt}[/red]")
        raise typer.Exit(1)

    src_node = ckpt / "memory_store.jsonl"
    src_react = ckpt / "memory.json"

    node_entries: list[dict] = []
    react_entries: list[dict] = []

    if src_node.exists():
        for line in src_node.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                node_entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    if react and src_react.exists():
        try:
            data = json.loads(src_react.read_text(encoding="utf-8"))
            if isinstance(data, list):
                react_entries = data
        except json.JSONDecodeError as e:
            console.print(f"[red]memory.json parse failed: {e}[/red]")
            raise typer.Exit(2)

    console.print(f"[cyan]node entries: {len(node_entries)}[/cyan]")
    if react:
        console.print(f"[cyan]react entries: {len(react_entries)}[/cyan]")
    if dry_run:
        console.print("[yellow]--dry-run: no writes.[/yellow]")
        return

    backend = _get_backend(ckpt)
    ts = int(time.time())

    if node_entries:
        backend.bulk_import(node_entries, kind="node_scope")
        src_node.rename(ckpt / f"memory_store.jsonl.migrated-{ts}")
        console.print(f"[green]✓ imported {len(node_entries)} node entries[/green]")

    if react and react_entries:
        backend.bulk_import(react_entries, kind="react_step")
        src_react.rename(ckpt / f"memory.json.migrated-{ts}")
        console.print(f"[green]✓ imported {len(react_entries)} react entries[/green]")

    # Global memory: detect but do not migrate.
    global_path = Path.home() / ".ari" / "global_memory.jsonl"
    if global_path.exists():
        console.print(
            f"[yellow]WARNING: {global_path} found — global memory is removed in "
            "v0.6.0.[/yellow]"
        )


# ─ backup / restore ───────────────────────────────────────────────────

def _backup_path(ckpt: Path) -> Path:
    return ckpt / "memory_backup.jsonl.gz"


def _do_backup(ckpt: Path) -> int:
    backend = _get_backend(ckpt)
    path = _backup_path(ckpt)
    n = 0
    with gzip.open(path, "wt", encoding="utf-8") as f:
        # node_scope
        for nid, entries in backend.list_all_nodes().get("by_node", {}).items():
            for e in entries:
                f.write(json.dumps({
                    "kind": "node_scope",
                    "node_id": nid,
                    "text": e["text"],
                    "metadata": e["metadata"],
                    "ts": e["ts"],
                }, ensure_ascii=False) + "\n")
                n += 1
        # react_step
        for e in backend.list_react_entries():
            f.write(json.dumps({
                "kind": "react_step",
                "text": e["content"],
                "metadata": e["metadata"],
                "ts": e["ts"],
            }, ensure_ascii=False) + "\n")
            n += 1
        # core_seed
        ctx = backend.get_experiment_context()
        if ctx:
            f.write(json.dumps({
                "kind": "core_seed",
                "persona": "",
                "human": "",
                "context": ctx,
                "seeded_at": ctx.get("seeded_at", 0.0),
            }, ensure_ascii=False) + "\n")
            n += 1
    return n


def _do_restore(ckpt: Path, on_conflict: str = "skip") -> dict:
    path = _backup_path(ckpt)
    if not path.exists():
        return {"restored": 0, "reason": "no backup"}
    backend = _get_backend(ckpt)
    if on_conflict == "overwrite":
        backend.purge_checkpoint()
    node_entries: list[dict] = []
    react_entries: list[dict] = []
    core_entries: list[dict] = []
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = e.get("kind")
            if kind == "node_scope":
                node_entries.append(e)
            elif kind == "react_step":
                react_entries.append(e)
            elif kind == "core_seed":
                core_entries.append(e)

    if on_conflict == "skip":
        # naive dedupe by (ts, text) presence
        existing_node = {
            (e.get("ts"), e.get("text"))
            for entries in backend.list_all_nodes().get("by_node", {}).values()
            for e in entries
        }
        node_entries = [e for e in node_entries
                        if (e.get("ts"), e.get("text")) not in existing_node]
        existing_react = {
            (e.get("ts"), e.get("content")) for e in backend.list_react_entries()
        }
        react_entries = [e for e in react_entries
                         if (e.get("ts"), e.get("text")) not in existing_react]

    total = 0
    if node_entries:
        total += backend.bulk_import(node_entries, kind="node_scope")["imported"]
    if react_entries:
        total += backend.bulk_import(react_entries, kind="react_step")["imported"]
    if core_entries:
        total += backend.bulk_import(core_entries, kind="core_seed")["imported"]
    return {"restored": total}


@memory_app.command("backup")
def backup_cmd(
    checkpoint: "Path | None" = typer.Option(None, help="Checkpoint directory"),
) -> None:
    """Snapshot Letta-stored memory to ``{ckpt}/memory_backup.jsonl.gz``."""
    ckpt = _resolve_ckpt(checkpoint)
    try:
        n = _do_backup(ckpt)
    except Exception as e:
        console.print(f"[red]backup failed: {e}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]✓ wrote {_backup_path(ckpt)} ({n} entries)[/green]")


@memory_app.command("restore")
def restore_cmd(
    checkpoint: "Path | None" = typer.Option(None, help="Checkpoint directory"),
    on_conflict: str = typer.Option("skip", help="skip|overwrite|merge"),
) -> None:
    """Import ``memory_backup.jsonl.gz`` into Letta."""
    ckpt = _resolve_ckpt(checkpoint)
    res = _do_restore(ckpt, on_conflict=on_conflict)
    console.print(f"[green]✓ restored {res['restored']} entries[/green]")


# ─ local Letta lifecycle ──────────────────────────────────────────────

def _scripts_root() -> Path:
    # scripts/letta/ relative to ari-core
    return Path(__file__).resolve().parents[2] / "scripts" / "letta"


@memory_app.command("start-local")
def start_local_cmd(
    path: str = typer.Option(
        "auto", help="docker|singularity|pip|auto — deployment path"
    ),
) -> None:
    """Start a local Letta server."""
    root = _scripts_root()
    chosen = path
    if chosen == "auto":
        chosen = _detect_deployment()
    cmd: list[str] = []
    if chosen == "docker":
        cmd = ["docker", "compose", "-f", str(root / "docker-compose.yml"), "up", "-d"]
    elif chosen == "singularity":
        cmd = ["bash", str(root / "start_singularity.sh")]
    elif chosen == "pip":
        cmd = ["bash", str(root / "start_pip.sh")]
    else:
        console.print(f"[red]Unsupported path: {chosen}[/red]")
        raise typer.Exit(1)
    try:
        subprocess.run(cmd, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        console.print(f"[red]start-local failed: {e}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]✓ {chosen} started[/green]")


@memory_app.command("stop-local")
def stop_local_cmd() -> None:
    """Stop the locally-started Letta."""
    # Try each known form — best-effort.
    for cmd in (
        ["docker", "compose", "-f", str(_scripts_root() / "docker-compose.yml"), "down"],
        ["singularity", "instance", "stop", "ari-letta"],
        ["pkill", "-f", "letta server"],
    ):
        try:
            subprocess.run(cmd, check=False)
        except FileNotFoundError:
            continue
    console.print("[green]✓ stop signals sent[/green]")


@memory_app.command("prune-local")
def prune_local_cmd(
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Delete local Letta state (docker volumes / sif / venv)."""
    if not yes:
        if not typer.confirm("Remove all local Letta data?"):
            raise typer.Exit(0)
    root = _scripts_root()
    subprocess.run(
        ["docker", "compose", "-f", str(root / "docker-compose.yml"), "down", "-v"],
        check=False,
    )
    venv = Path(os.environ.get("ARI_LETTA_VENV", str(Path.home() / ".ari/letta-venv")))
    if venv.exists():
        shutil.rmtree(venv, ignore_errors=True)
    dotletta = Path.home() / ".letta"
    if dotletta.exists():
        shutil.rmtree(dotletta, ignore_errors=True)
    console.print("[green]✓ local Letta state removed[/green]")


# ─ access log ─────────────────────────────────────────────────────────

@memory_app.command("compact-access")
def compact_access_cmd(
    checkpoint: "Path | None" = typer.Option(None, help="Checkpoint directory"),
) -> None:
    """Summarise rotated memory_access.<ts>.jsonl files into a single summary."""
    ckpt = _resolve_ckpt(checkpoint)
    rotated = sorted(ckpt.glob("memory_access.*.jsonl"))
    if not rotated:
        console.print("[yellow]no rotated files to compact[/yellow]")
        return
    by_node: dict[str, dict[str, int]] = {}
    for f in rotated:
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                ev = json.loads(line)
            except Exception:
                continue
            nid = ev.get("node_id", "")
            by_node.setdefault(nid, {"writes": 0, "reads": 0})
            if ev.get("op") == "write":
                by_node[nid]["writes"] += 1
            elif ev.get("op") == "read":
                by_node[nid]["reads"] += 1
    summary = ckpt / "memory_access.summary.json"
    summary.write_text(
        json.dumps(by_node, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    for f in rotated:
        f.unlink()
    console.print(
        f"[green]✓ compacted {len(rotated)} files → {summary}[/green]"
    )


# ─ health ─────────────────────────────────────────────────────────────

@memory_app.command("health")
def health_cmd(
    checkpoint: "Path | None" = typer.Option(None, help="Checkpoint directory"),
) -> None:
    """Ping the backend and show its reachability."""
    ckpt = _resolve_ckpt(checkpoint)
    try:
        backend = _get_backend(ckpt)
        h = backend.health()
    except Exception as e:
        console.print(f"[red]unhealthy: {e}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]{h}[/green]")


# ─ helpers ────────────────────────────────────────────────────────────

def _detect_deployment() -> str:
    """Pick a local Letta deployment path."""
    on_hpc = bool(os.environ.get("SLURM_CLUSTER_NAME"))
    if shutil.which("docker") and not on_hpc:
        return "docker"
    if shutil.which("singularity") or shutil.which("apptainer"):
        return "singularity"
    if shutil.which("python") or shutil.which("python3"):
        return "pip"
    return "none"


__all__ = [
    "memory_app",
    "_do_backup",
    "_do_restore",
    "_detect_deployment",
]
