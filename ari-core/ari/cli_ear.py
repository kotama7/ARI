"""`ari ear ...` subcommands.

This module owns the EAR curation / publish / promote / status CLI surface.
Per P1 (ari-core ↔ skill split), the curate semantics live in
``ari-skill-transform``; ari-core only resolves checkpoint paths and
imports the curator.

the ``curate`` subcommand. ``publish``, ``promote`` and
``status`` are added in later PRs and intentionally stubbed here so the
CLI surface is stable across releases.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import typer
from rich.console import Console

console = Console()
ear_app = typer.Typer(name="ear", help="EAR (Experiment Artifact Repository) curation, publishing, and promotion.")


def _import_curate():
    """Locate the transform skill's curate module without forcing a heavy import.

    The skill is installed in editable mode by setup.sh; the layout is
    ``ari-skill-transform/src/{server,curate}.py``. We add the src dir to
    sys.path defensively so the CLI works in dev checkouts where the
    editable install is not active.
    """
    try:
        import curate  # type: ignore
        return curate
    except ModuleNotFoundError:
        pass
    here = Path(__file__).resolve()
    # Walk up until we hit the ARI repo root (contains ari-skill-transform/).
    for parent in [here, *here.parents]:
        candidate = parent / "ari-skill-transform" / "src"
        if candidate.is_dir():
            sys.path.insert(0, str(candidate))
            break
    import curate  # type: ignore
    return curate


def _resolve_checkpoint(checkpoint: Path) -> Path:
    """Accept either a path or a checkpoint id (resolved against ./checkpoints)."""
    if checkpoint.exists():
        return checkpoint.resolve()
    candidate = Path("checkpoints") / checkpoint
    if candidate.exists():
        return candidate.resolve()
    raise typer.BadParameter(f"checkpoint not found: {checkpoint}")


@ear_app.command("curate")
def cmd_curate(
    checkpoint: Path = typer.Argument(..., help="Checkpoint directory or id"),
    show_files: bool = typer.Option(False, "--show-files", help="Print included files"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Curate <checkpoint>/ear/ into <checkpoint>/ear_published/ using publish.yaml.

    If publish.yaml is absent, the command exits 0 and prints "skipped".
    The bundle digest in manifest.lock is the value to be baked into the
    paper's Code Availability section.
    """
    ckpt = _resolve_checkpoint(checkpoint)
    curate = _import_curate()
    try:
        result = curate.curate(ckpt)
    except curate.CurateError as e:
        console.print(f"[red]curate failed:[/red] {e}")
        raise typer.Exit(2)

    if json_output:
        payload = {
            "ear_published_dir": str(result.ear_published_dir),
            "manifest_path": str(result.manifest_path),
            "bundle_sha256": result.bundle_sha256,
            "included_files": result.included_files,
            "excluded_count": result.excluded_count,
            "skipped": result.skipped,
        }
        typer.echo(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    if result.skipped:
        console.print(f"[yellow]publish.yaml absent — curation skipped for {ckpt.name}[/yellow]")
        return

    console.print(f"[green]curated[/green] {len(result.included_files)} file(s) → {result.ear_published_dir}")
    console.print(f"[bold]bundle sha256:[/bold] {result.bundle_sha256}")
    if result.excluded_count:
        console.print(f"[dim]{result.excluded_count} file(s) removed by built-in/exclude rules (paths not recorded)[/dim]")
    if show_files:
        for rel in result.included_files:
            console.print(f"  {rel}")


@ear_app.command("status")
def cmd_status(
    checkpoint: Path = typer.Argument(..., help="Checkpoint directory or id"),
) -> None:
    """Show curation / publish status for a checkpoint.

    only curation is wired. publish_record.json display lands.
    """
    ckpt = _resolve_checkpoint(checkpoint)
    out = ckpt / "ear_published"
    manifest = out / "manifest.lock"
    if not manifest.exists():
        console.print(f"[yellow]not curated:[/yellow] {ckpt.name}")
        raise typer.Exit(0)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    console.print(f"[bold]{ckpt.name}[/bold]")
    console.print(f"  bundle_sha256: {data.get('bundle_sha256', '')}")
    console.print(f"  files:         {len(data.get('files', []))}")
    console.print(f"  visibility:    {data.get('publish', {}).get('visibility')}")
    console.print(f"  excluded:      {data.get('excluded_count', 0)}")
    record = ckpt / "publish_record.json"
    if record.exists():
        rec = json.loads(record.read_text(encoding="utf-8"))
        console.print(f"  publish:       backend={rec.get('backend')} ref={rec.get('ref')} visibility={rec.get('visibility')}")


@ear_app.command("publish")
def cmd_publish(
    checkpoint: Path = typer.Argument(..., help="Checkpoint directory or id"),
    backend: str = typer.Option("ari-registry", "--backend", help="Publish backend"),
    visibility: str = typer.Option("staged", "--visibility", help="Initial visibility"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Compute ref/sha without uploading"),
) -> None:
    """Publish a curated EAR to a backend. Always starts at visibility=staged."""
    from ari.publish import publish, PublishError
    ckpt = _resolve_checkpoint(checkpoint)
    try:
        record = publish(ckpt, backend=backend, visibility=visibility, dry_run=dry_run)
    except PublishError as e:
        console.print(f"[red]ari ear publish failed:[/red] {e}")
        raise typer.Exit(2)
    console.print(f"[green]published[/green] {ckpt.name} → {record.ref}")
    console.print(f"  backend:       {record.backend}")
    console.print(f"  visibility:    {record.visibility}")
    console.print(f"  bundle_sha256: {record.bundle_sha256}")
    if record.dry_run:
        console.print("[yellow](dry-run — no upload performed)[/yellow]")


@ear_app.command("promote")
def cmd_promote(
    checkpoint: Path = typer.Argument(..., help="Checkpoint directory or id"),
    target: str = typer.Option("public", "--target", help="Target visibility (public|unlisted)"),
) -> None:
    """Promote a previously-published artifact (staged → unlisted/public)."""
    from ari.publish import promote, PublishError
    ckpt = _resolve_checkpoint(checkpoint)
    try:
        record = promote(ckpt, target=target)
    except PublishError as e:
        console.print(f"[red]ari ear promote failed:[/red] {e}")
        raise typer.Exit(2)
    console.print(f"[green]promoted[/green] {ckpt.name} → {record.visibility}")
    console.print(f"  ref: {record.ref}")


__all__ = ["ear_app"]
