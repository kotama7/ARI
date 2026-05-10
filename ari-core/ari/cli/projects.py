"""``ari paper`` / ``ari status`` / ``ari projects`` / ``ari show`` Typer commands (Phase 3A).

These four sit on the read-side of a checkpoint — turning persisted
artifacts into a paper, a status table, or a tree dump — without
mutating BFTS state.  The Typer decorators bind to ``ari.cli.app`` at
import time; ``ari/cli/__init__.py`` imports this module after defining
the app so the decorators register correctly.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

from ari.config import load_config, auto_config
from ari.core import build_runtime as _real_build_runtime, generate_paper_section as _real_generate_paper_section  # noqa: F401
from ari.paths import PathManager

from ari.cli import app, console


# Phase 3A — defer to ``ari.cli`` so test monkeypatches at the package
# surface flow into ``paper`` / ``status``.
def build_runtime(*args, **kwargs):
    from ari import cli as _cli
    return _cli.build_runtime(*args, **kwargs)


def generate_paper_section(*args, **kwargs):
    from ari import cli as _cli
    return _cli.generate_paper_section(*args, **kwargs)


log = logging.getLogger(__name__)


# Phase 3A — defer to ``ari.cli`` so test monkeypatches at the package
# surface flow into the body of ``paper`` / ``status``.
def _resolve_cfg(*args, **kwargs):
    from ari import cli as _cli
    return _cli._resolve_cfg(*args, **kwargs)


def _setup_logging(*args, **kwargs):
    from ari import cli as _cli
    return _cli._setup_logging(*args, **kwargs)




@app.command()
def paper(
    checkpoint_dir: Path = typer.Argument(..., help="Path to checkpoint directory"),
    experiment: Path | None = typer.Option(None, help="Experiment .md file (auto-detected from checkpoint if omitted)"),
    config: Path | None = typer.Option(None, help="Config YAML (auto-generated if omitted)"),
    rubric: str | None = typer.Option(None, "--rubric", help="Reviewer rubric id (neurips|iclr|icml|cvpr|acl|sc|chi|usenix_security|osdi|stoc|icra|siggraph|nature|journal_generic|workshop|generic_conference)"),
    fewshot_mode: str | None = typer.Option(None, "--fewshot-mode", help="Few-shot mode: static (default) or dynamic (OpenReview retrieval, Phase 2)"),
    num_reviews_ensemble: int | None = typer.Option(None, "--num-reviews-ensemble", help="Number of independent reviewer agents (default 1 per rubric)"),
    num_reflections: int | None = typer.Option(None, "--num-reflections", help="Reflection rounds (default 5 per rubric)"),
) -> None:
    """Run paper pipeline from existing checkpoint (skip experiment phase).

    Reviewer behaviour follows the AI Scientist v1/v2 pipeline (NeurIPS form,
    reflection loop, N-reviewer ensemble with Area Chair meta-review when N>1).
    Configure per-run via --rubric / --fewshot-mode / --num-reviews-ensemble /
    --num-reflections, or globally via ARI_RUBRIC / ARI_FEWSHOT_MODE /
    ARI_NUM_REVIEWS_ENSEMBLE / ARI_NUM_REFLECTIONS environment variables.
    """
    import os as _os_cli
    if rubric:
        _os_cli.environ["ARI_RUBRIC"] = rubric
    if fewshot_mode:
        if fewshot_mode not in ("static", "dynamic"):
            console.print(f"[red]--fewshot-mode must be static or dynamic (got {fewshot_mode!r})[/red]")
            raise typer.Exit(1)
        _os_cli.environ["ARI_FEWSHOT_MODE"] = fewshot_mode
    if num_reviews_ensemble is not None:
        _os_cli.environ["ARI_NUM_REVIEWS_ENSEMBLE"] = str(num_reviews_ensemble)
    if num_reflections is not None:
        _os_cli.environ["ARI_NUM_REFLECTIONS"] = str(num_reflections)
    from ari.orchestrator.node import Node, NodeStatus

    tree_file = checkpoint_dir / "tree.json"
    if not tree_file.exists():
        console.print(f"[red]Checkpoint not found: {tree_file}[/red]")
        raise typer.Exit(1)

    with open(tree_file) as f:
        tree_data = json.load(f)

    run_id = tree_data["run_id"]
    # Prefer: --experiment flag > checkpoint/experiment.md > tree.json path
    if experiment:
        experiment_file = str(experiment)
    else:
        _ckpt_exp = checkpoint_dir / "experiment.md"
        if _ckpt_exp.exists():
            experiment_file = str(_ckpt_exp)
        else:
            experiment_file = tree_data.get("experiment_file", "")
    exp_path = Path(experiment_file)
    experiment_text = exp_path.read_text() if exp_path.exists() else ""
    import re as _re_tp
    _tm_tp = _re_tp.search(r"^#\s*(.+)", experiment_text, _re_tp.MULTILINE)
    _tp_tp = _re_tp.sub(r"[^a-zA-Z0-9_-]", "_", (_tm_tp.group(1)[:80] if _tm_tp else Path(experiment_file).stem))
    experiment_data = {"goal": experiment_text, "topic": _tp_tp, "file": experiment_file}

    cfg = _resolve_cfg(config)
    # See the matching note in `resume`: when the checkpoint_dir argument is
    # explicit, it owns log/checkpoint paths regardless of YAML defaults.
    cfg.logging.dir = str(checkpoint_dir)
    cfg.checkpoint.dir = str(checkpoint_dir)
    _setup_logging(cfg.logging, run_id)

    node_map: dict[str, Node] = {}
    for nd in tree_data["nodes"]:
        node = Node(
            id=nd["id"], parent_id=nd.get("parent_id"), depth=nd["depth"],
            retry_count=nd.get("retry_count", 0), artifacts=nd.get("artifacts", []),
            eval_summary=nd.get("eval_summary") or nd.get("score_reason"),
            error_log=nd.get("error_log"), children=nd.get("children", []),
            created_at=nd.get("created_at", ""), completed_at=nd.get("completed_at", ""),
            ancestor_ids=nd.get("ancestor_ids") or [],
        )
        node.status = NodeStatus(nd["status"])
        _lbl = nd.get("label", "draft")
        if hasattr(node, "label"):
            from ari.orchestrator.node import NodeLabel as _NL_p
            try:
                node.label = _NL_p.from_str(_lbl) if hasattr(_NL_p, "from_str") else _NL_p(_lbl)
            except Exception:
                pass
        node.metrics = nd.get("metrics") or {}
        node.has_real_data = nd.get("has_real_data", False)
        node_map[node.id] = node

    all_nodes = list(node_map.values())
    _, _, mcp_paper, _, _, _, _ = build_runtime(cfg, experiment_text, checkpoint_dir=checkpoint_dir)
    console.print(Panel(
        f"[bold green]Running paper pipeline[/bold green]\nCheckpoint: {checkpoint_dir}",
        title="ARI Paper",
    ))
    # Prefer per-checkpoint workflow.yaml (carries launch-time rewrites) over
    # the package source.
    from pathlib import Path as _PL
    _pkg_wf = _PL(__file__).parent.parent / "config" / "workflow.yaml"
    _ckpt_wf = _PL(checkpoint_dir) / "workflow.yaml"
    if _ckpt_wf.exists():
        _cfg_str = str(_ckpt_wf)
    elif config:
        _cfg_str = str(config)
    else:
        _cfg_str = str(_pkg_wf) if _pkg_wf.exists() else ""
    from ari.pidfile import pid_context
    with pid_context(checkpoint_dir):
        generate_paper_section(all_nodes, experiment_data, checkpoint_dir, mcp_paper, _cfg_str)
    console.print("[bold green]Paper pipeline complete.[/bold green]")



@app.command()
def status(
    checkpoint_dir: Path = typer.Argument(..., help="Path to checkpoint directory"),
) -> None:
    """Show the status of a run."""
    tree_file = checkpoint_dir / "tree.json"
    if not tree_file.exists():
        console.print(f"[red]Checkpoint not found: {tree_file}[/red]")
        raise typer.Exit(1)

    with open(tree_file) as f:
        tree_data = json.load(f)

    nodes = {n["id"]: n for n in tree_data["nodes"]}
    STATUS_STYLE = {"success": "green", "failed": "red", "pending": "yellow",
                    "running": "blue", "abandoned": "dim"}

    def _add_children(rich_node, node_id: str) -> None:
        nd = nodes.get(node_id)
        if nd is None:
            return
        st = nd["status"]
        color = STATUS_STYLE.get(st, "white")
        label = f" [{nd.get('label', 'draft')}]" if nd.get('label') else ""
        score = ""  # score field deprecated
        child_rich = rich_node.add(
            f"[{color}]{nd['id']}[/{color}] [dim]d={nd['depth']} {st}{score}[/dim]"
        )
        for cid in nd.get("children", []):
            _add_children(child_rich, cid)

    rich_tree = Tree(f"[bold]Run: {tree_data['run_id']}[/bold]")
    for r in [n for n in tree_data["nodes"] if not n.get("parent_id")]:
        _add_children(rich_tree, r["id"])
    console.print(rich_tree)

    from collections import Counter
    counts = Counter(n["status"] for n in tree_data["nodes"])
    table = Table(title="Summary")
    table.add_column("Status")
    table.add_column("Count", justify="right")
    for st, cnt in sorted(counts.items()):
        table.add_row(f"[{STATUS_STYLE.get(st, 'white')}]{st}[/{STATUS_STYLE.get(st, 'white')}]", str(cnt))
    console.print(table)



# ─────────────────────────────────────────
# Extended CLI commands mirroring GUI features
# ─────────────────────────────────────────

@app.command("projects")
def list_projects(
    checkpoints: Path = typer.Option(Path("checkpoints"), help="Checkpoints directory"),
) -> None:
    """List all projects (checkpoint directories) with their status."""
    import textwrap
    if not checkpoints.exists():
        console.print(f"[red]Directory not found: {checkpoints}[/red]")
        raise typer.Exit(1)

    _SKIP = {"experiments", "__pycache__", ".git"}
    table = Table(title="ARI Projects", show_lines=False)
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Nodes", justify="right")
    table.add_column("Status", justify="center")
    table.add_column("Score", justify="right")
    table.add_column("Modified")

    import datetime
    rows = []
    for d in sorted(checkpoints.iterdir(), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True):
        if not d.is_dir() or d.name in _SKIP:
            continue
        nt = d / "tree.json"
        if not nt.exists() or nt.stat().st_size == 0:
            nt = d / "nodes_tree.json"
        rr = d / "review_report.json"
        nodes_count = 0
        status = "empty"
        score = "—"
        if nt.exists() and nt.stat().st_size > 0:
            try:
                tree = json.loads(nt.read_text(encoding="utf-8", errors="replace"))
                nodes = tree.get("nodes", [])
                nodes_count = len(nodes)
                statuses = {n.get("status") for n in nodes}
                if "running" in statuses:
                    status = "[blue]running[/blue]"
                elif nodes:
                    status = "[green]done[/green]"
            except Exception:
                status = "[red]corrupt[/red]"
        if rr.exists():
            try:
                rdata = json.loads(rr.read_text(encoding="utf-8", errors="replace"))
                s = rdata.get("scientific_score") or rdata.get("score")
                if s is not None:
                    score = f"{float(s):.2f}"
            except Exception:
                pass
        mtime = datetime.datetime.fromtimestamp(d.stat().st_mtime).strftime("%m/%d %H:%M")
        rows.append((d.name, str(nodes_count), status, score, mtime))

    if not rows:
        console.print("[yellow]No projects found.[/yellow]")
        return
    for r in rows:
        table.add_row(*r)
    console.print(table)



@app.command("show")
def show_project(
    checkpoint: Path = typer.Argument(..., help="Checkpoint directory or ID"),
    checkpoints_dir: Path = typer.Option(Path("checkpoints"), help="Checkpoints base dir"),
) -> None:
    """Show detailed info for a project: node tree + review summary."""
    # Resolve checkpoint path
    if not checkpoint.exists():
        candidate = checkpoints_dir / checkpoint
        if candidate.exists():
            checkpoint = candidate
        else:
            console.print(f"[red]Not found: {checkpoint}[/red]")
            raise typer.Exit(1)

    # Node tree (prefer tree.json, fallback to nodes_tree.json)
    nt = checkpoint / "tree.json"
    if not nt.exists():
        nt = checkpoint / "nodes_tree.json"
    if nt.exists():
        try:
            tree_data = json.loads(nt.read_text(encoding="utf-8", errors="replace"))
            nodes = {n["id"]: n for n in tree_data.get("nodes", [])}
            STATUS_STYLE = {"success": "green", "failed": "red", "pending": "yellow",
                            "running": "blue", "abandoned": "dim"}
            rich_tree = Tree(f"[bold cyan]{checkpoint.name}[/bold cyan]")

            def _add(rich_node, node_id):
                nd = nodes.get(node_id)
                if nd is None:
                    return
                st = nd.get("status", "?")
                color = STATUS_STYLE.get(st, "white")
                name = nd.get("name") or nd.get("label") or nd["id"][-8:]
                score_str = ""
                sc = nd.get("scientific_score") or nd.get("score")
                if sc is not None:
                    score_str = f" score={float(sc):.2f}"
                child_rich = rich_node.add(
                    f"[{color}]{name}[/{color}] [dim]{nd['id'][-8:]} d={nd.get('depth',0)}{score_str}[/dim]"
                )
                for cid in nd.get("children", []):
                    _add(child_rich, cid)

            roots = [n for n in tree_data.get("nodes", []) if not n.get("parent_id")]
            for r in roots:
                _add(rich_tree, r["id"])
            console.print(rich_tree)
        except Exception as e:
            console.print(f"[red]Failed to read tree: {e}[/red]")
    else:
        console.print("[yellow]No tree.json or nodes_tree.json found.[/yellow]")

    # Review summary
    rr = checkpoint / "review_report.json"
    if rr.exists():
        try:
            rdata = json.loads(rr.read_text(encoding="utf-8", errors="replace"))
            table = Table(title="Review Report", show_header=False)
            table.add_column("Key", style="dim")
            table.add_column("Value")
            for k, v in rdata.items():
                if k not in ("full_text", "latex"):
                    table.add_row(str(k), str(v)[:120])
            console.print(table)
        except Exception as e:
            console.print(f"[red]Failed to read review: {e}[/red]")

    # Artifacts
    artifacts_dir = checkpoint / "artifacts"
    if artifacts_dir.exists():
        files = list(artifacts_dir.iterdir())
        if files:
            console.print(f"\n[bold]Artifacts[/bold] ({len(files)} files):")
            for f in sorted(files)[:10]:
                console.print(f"  • {f.name}")

