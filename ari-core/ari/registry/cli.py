"""``ari registry`` CLI: serve / token / gc subcommands."""
from __future__ import annotations

import os
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .auth import TokenStore

console = Console()
registry_app = typer.Typer(name="registry", help="ari-registry server administration.")
token_app = typer.Typer(name="token", help="Issue / revoke / list bearer tokens.")
registry_app.add_typer(token_app, name="token")


def _data_dir() -> Path:
    return Path(os.environ.get("ARI_REGISTRY_DATA") or Path.home() / ".ari" / "registry-data")


@registry_app.command("serve")
def serve(
    host: str = typer.Option("0.0.0.0", "--host"),
    port: int = typer.Option(8290, "--port"),
    data_dir: Path | None = typer.Option(None, "--data-dir"),
) -> None:
    """Start the FastAPI app via uvicorn."""
    try:
        import uvicorn  # type: ignore
    except ImportError:
        console.print("[red]uvicorn is required to run the registry. pip install uvicorn[/red]")
        raise typer.Exit(2)
    if data_dir:
        os.environ["ARI_REGISTRY_DATA"] = str(data_dir)
    from .app import build_app
    uvicorn.run(build_app(_data_dir()), host=host, port=port)


@token_app.command("issue")
def issue(
    user: str = typer.Argument(..., help="User / service name to attach to the token."),
) -> None:
    """Mint a new bearer token. Plaintext is shown ONCE — store it securely."""
    store = TokenStore(_data_dir() / "tokens.db")
    tok_id, plaintext = store.issue(user)
    console.print(f"[green]issued[/green] token id={tok_id} for user={user}")
    console.print("[bold yellow]Plaintext (shown once):[/bold yellow]")
    console.print(plaintext)


@token_app.command("revoke")
def revoke(token_id: str = typer.Argument(...)) -> None:
    store = TokenStore(_data_dir() / "tokens.db")
    if store.revoke(token_id):
        console.print(f"[green]revoked[/green] {token_id}")
    else:
        console.print(f"[yellow]no active token with id={token_id}[/yellow]")


@token_app.command("list")
def list_tokens() -> None:
    store = TokenStore(_data_dir() / "tokens.db")
    rows = store.list_users()
    table = Table(title="ari-registry tokens")
    table.add_column("id"); table.add_column("user"); table.add_column("created_at"); table.add_column("revoked_at")
    for r in rows:
        table.add_row(r["id"], r["user"], r["created_at"], r["revoked_at"] or "-")
    console.print(table)


__all__ = ["registry_app"]
