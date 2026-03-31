"""CLI entry point — a thin wrapper with zero domain knowledge.

All construction logic is delegated to ari.core.
"""

from __future__ import annotations

import json
import logging
import os
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

app = typer.Typer(name="ari", help="ARI - Artificial Research Intelligence")
console = Console()


def _setup_logging(cfg_logging, run_id: str) -> None:
    log_dir = Path(cfg_logging.dir.replace("{run_id}", run_id))
    log_dir.mkdir(parents=True, exist_ok=True)
    level = getattr(logging, cfg_logging.level.upper(), logging.INFO)

    class JsonFormatter(logging.Formatter):
        def format(self, record: logging.LogRecord) -> str:
            return json.dumps({
                "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "msg": record.getMessage(),
                "run_id": run_id,
            }, ensure_ascii=False)

    fh = logging.FileHandler(log_dir / "ari.log", encoding="utf-8")
    fh.setFormatter(JsonFormatter() if cfg_logging.format == "json" else logging.Formatter())
    fh.setLevel(level)
    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(fh)


def _run_loop(cfg, bfts, agent, pending, all_nodes, experiment_data,
              checkpoint_dir, run_id, total_processed=0):
    from ari.orchestrator.node import NodeStatus
    max_workers = max(1, min(cfg.bfts.max_parallel_nodes, 4))

    # frontier: completed nodes not yet expanded (true BFTS: expand on demand)
    frontier: list = []

    while pending or (frontier and len(all_nodes) < cfg.bfts.max_total_nodes):
        # --- BFTS STEP: expand the best frontier node if we need more work ---
        # all_nodes tracks every node ever created (root + all children)
        _budget = cfg.bfts.max_total_nodes - len(all_nodes)
        while frontier and len(pending) < max_workers and _budget > 0:
            try:
                best = bfts.select_best_to_expand(frontier, experiment_data["goal"], agent.memory)
            except Exception as exc:
                logging.getLogger(__name__).warning("select_best_to_expand failed: %s", exc)
                best = frontier[0]
            frontier.remove(best)
            if bfts.should_prune(best):
                console.print(f"  [yellow]Pruned frontier node {best.id[-8:]}[/yellow]")
                continue
            try:
                children = bfts.expand(best, experiment_goal=experiment_data.get("goal", ""))
                all_nodes.extend(children)
                pending.extend(children)
                _budget -= len(children)
                console.print(f"  [cyan]Expanded {best.id[-8:]} (sci={best.metrics.get('_scientific_score','?') if best.metrics else '?'}) -> {len(children)} children[/cyan]")
            except Exception as exc:
                logging.getLogger(__name__).warning("expand failed: %s", exc)

        if not pending:
            break

        batch_size = min(max_workers, len(pending))
        batch = []
        for _ in range(batch_size):
            if not pending:
                break
            try:
                node = bfts.select_next_node(pending, experiment_data["goal"], agent.memory)
            except Exception as exc:
                logging.getLogger(__name__).warning("select_next_node failed: %s", exc)
                node = pending[0]
            pending.remove(node)
            batch.append(node)

        console.print(f"\n[bold]Processing {len(batch)} node(s) in parallel...[/bold]")

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Create per-node work directory: experiments/<slug>/<node_id>/
            from pathlib import Path as _Path
            import re as _re_slug
            _slug = _re_slug.sub(r"[^a-zA-Z0-9_-]", "_", experiment_data.get("topic", "exp"))[:40]
            _exp_root = _Path(checkpoint_dir).parent / "experiments" / _slug
            for _n in batch:
                _nd = _exp_root / _n.id
                _nd.mkdir(parents=True, exist_ok=True)
                _n.work_dir = str(_nd)
            # Inject work_dir into per-node experiment copy
            # Copy provided_files (parsed from .md) into each node's work_dir
            _provided = getattr(agent.hints, "provided_files", []) if hasattr(agent, "hints") else []
            for _n in batch:
                for _src, _fname in _provided:
                    try:
                        import shutil as _sh
                        _dst = _Path(_n.work_dir) / _fname
                        if _Path(_src).exists() and not _dst.exists():
                            _sh.copy2(_src, _dst)
                            logging.getLogger(__name__).info(
                                "Copied %s → %s", _src, _dst
                            )
                    except Exception as _ce:
                        logging.getLogger(__name__).warning(
                            "Could not copy provided file %s: %s", _src, _ce
                        )

            # Build HPC hints from workflow (partition, cpus)
            _partition = getattr(agent.hints, "slurm_partition", "") if hasattr(agent, "hints") else ""
            _max_cpus  = getattr(agent.hints, "slurm_max_cpus",  0) if hasattr(agent, "hints") else 0

            def _node_exp(n):
                d = dict(experiment_data)
                d["work_dir"] = n.work_dir
                # Inject HPC settings so the agent knows without reading the .md again
                if _partition:
                    d["slurm_partition"] = _partition
                if _max_cpus:
                    d["slurm_max_cpus"] = _max_cpus
                return d
            _timeout_s = cfg.bfts.timeout_per_node
            futures = {executor.submit(agent.run, n, _node_exp(n)): n for n in batch}
            for future in as_completed(futures):
                node_ref = futures[future]
                try:
                    result = future.result(timeout=_timeout_s)
                except TimeoutError:
                    logging.getLogger(__name__).warning("Node %s timed out after %ds", node_ref.id, _timeout_s)
                    node_ref.mark_failed(error_log=f"timeout: exceeded {_timeout_s}s limit")
                    result = node_ref
                except Exception as exc:
                    logging.getLogger(__name__).warning("Node %s raised exception: %s", node_ref.id, exc)
                    node_ref.mark_failed(error_log=f"exception: {exc}")
                    result = node_ref
                total_processed += 1
                color = "green" if result.status == NodeStatus.SUCCESS else "red"
                metrics_str = f" metrics={dict(list(result.metrics.items())[:2])}" if result.metrics else ""
                console.print(f"  [{color}]{result.id}[/{color}] -> {result.status.value} has_real={result.has_real_data}{metrics_str}")

                if result.status == NodeStatus.SUCCESS:
                    # Add to frontier — BFTS selects best to expand at top of loop
                    frontier.append(result)
                    console.print(f"    Added to frontier (will expand when selected by BFTS)")
                elif result.status == NodeStatus.FAILED:
                    console.print(f"    [red]Error:[/red] {result.error_log}")
                    # Failed nodes go to frontier: BFTS will expand with "debug" children
                    # (retrying the same node is not BFTS — it would repeat the same failure)
                    frontier.append(result)
                    console.print(f"    Added failed node to frontier for debug expansion")

                # Save checkpoint after each node completes (not just after batch)
                # This ensures progress is preserved if SIGTERM interrupts mid-batch
                _save_checkpoint(checkpoint_dir, run_id, experiment_data["file"], all_nodes)

        _save_checkpoint(checkpoint_dir, run_id, experiment_data["file"], all_nodes)

    return total_processed


def _apply_profile(cfg, profile_name: str) -> None:
    """Deep-merge an environment profile into the config."""
    import yaml as _yaml
    profiles_dir = Path(__file__).parent.parent.parent / "config" / "profiles"
    p = profiles_dir / f"{profile_name}.yaml"
    if not p.exists():
        return
    overrides = _yaml.safe_load(p.read_text()) or {}
    # Apply bfts overrides
    bfts_o = overrides.get("bfts", {})
    if "max_total_nodes" in bfts_o:
        cfg.bfts.max_total_nodes = bfts_o["max_total_nodes"]
    if "parallel" in bfts_o:
        cfg.bfts.parallel = bfts_o["parallel"]


@app.command()
def run(
    experiment: Path = typer.Argument(..., help="Path to experiment .md file (only required input)"),
    config: Path | None = typer.Option(None, help="Config YAML (auto-generated if omitted)"),
    profile: str | None = typer.Option(None, help="Environment profile: laptop, hpc, cloud"),
) -> None:
    """Run an experiment. Only the .md file is required."""
    from ari.orchestrator.node import Node

    experiment_text = experiment.read_text()
    if config and config.exists():
        cfg = load_config(str(config))
    else:
        cfg = auto_config()

    # Apply environment profile overrides
    if profile:
        _apply_profile(cfg, profile)
    # Build human-readable run_id: yyyymmddHHMMSS_<experiment_slug>
    import re as _re_t2
    from datetime import datetime as _dt
    # Build name from first meaningful line of the experiment text.
    # No specific format required - heading, plain text, anything works.
    # Ask LLM to generate a concise descriptive title from experiment content
    _raw_name = experiment.stem  # fallback
    try:
        from ari.llm.client import LLMClient
        _title_llm = LLMClient(cfg.llm)
        _title_resp = _title_llm.complete(
            [{"role": "user", "content":
              f"Generate a concise 3-5 word English title (snake_case, no special chars) for this research goal:\n{experiment_text[:500]}\nReply with ONLY the title."}],
            max_tokens=20, temperature=0.3,
        )
        _raw_name = _title_resp.strip().splitlines()[0].strip()
    except Exception:
        # Fallback: skip headings, use first meaningful content line
        _in_goal = False
        for _line in experiment_text.splitlines():
            _stripped = _line.strip()
            if not _stripped:
                continue
            _is_heading = _stripped.startswith('#')
            if _is_heading:
                # Check if it's the Research Goal heading
                _hcontent = _re_t2.sub(r'^#{1,3}\s*', '', _stripped).strip().lower()
                if 'research goal' in _hcontent:
                    _in_goal = True
                else:
                    _in_goal = False
                continue  # skip heading lines
            # Non-heading line
            _raw_name = _stripped[:60]
            break
    _slug = _re_t2.sub(r"[^a-zA-Z0-9_-]", "_", _raw_name).strip("_")[:40]
    _slug = _re_t2.sub(r"_+", "_", _slug)  # collapse repeated underscores
    _ts = _dt.now().strftime("%Y%m%d%H%M%S")
    run_id = f"{_ts}_{_slug}"
    _setup_logging(cfg.logging, run_id)

    console.print(Panel(
        f"[bold green]ARI Run[/bold green]  id={run_id}\nExperiment: {experiment}" + (f"\nConfig: {config}" if config else ""),
        title="ARI",
    ))

    _tp2 = _slug
    experiment_data = {
        "goal": experiment_text,
        "topic": _tp2,
        "file": str(experiment),
    }

    _, _, mcp, bfts, agent, _, _ = build_runtime(cfg, experiment_text)
    root = Node(id=f"node_{run_id}_root", parent_id=None, depth=0)
    root.name = f"root: {_slug[:40]}"
    all_nodes = [root]
    pending = [root]

    checkpoint_dir = Path(cfg.checkpoint.dir.replace("{run_id}", run_id))
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    agent.checkpoint_dir = str(checkpoint_dir)
    # Copy experiment.md into checkpoint dir so the dashboard can display it immediately
    import shutil as _shutil_cp
    try:
        _shutil_cp.copy2(str(experiment), checkpoint_dir / "experiment.md")
    except Exception:
        pass
    # Initialize cost tracker early so BFTS phase is also tracked
    try:
        from ari import cost_tracker as _ct_run
        _ct_run.init(checkpoint_dir)
    except Exception:
        pass
    # Clear stale pipeline marker from previous run (for resume correctness)
    (checkpoint_dir / ".pipeline_started").unlink(missing_ok=True)

    from ari.pidfile import pid_context
    with pid_context(checkpoint_dir):
        total = _run_loop(cfg, bfts, agent, pending, all_nodes,
                          experiment_data, checkpoint_dir, run_id)
        console.print(Panel(
            f"[bold green]Run complete.[/bold green]  Processed {total} nodes  |  Checkpoint: {checkpoint_dir}",
            title="Done",
        ))
        # Resolve config_path: use --config if given, otherwise find package workflow.yaml
        _pkg_wf = Path(__file__).parent.parent / "config" / "workflow.yaml"
        _cfg_str = str(config) if config else (str(_pkg_wf) if _pkg_wf.exists() else "")
        try:
            generate_paper_section(all_nodes, experiment_data, checkpoint_dir, mcp, _cfg_str)
        except Exception as _paper_err:
            console.print(f"[bold red]Paper pipeline failed:[/bold red] {_paper_err}")
            import traceback
            traceback.print_exc()


@app.command()
def resume(
    checkpoint_dir: Path = typer.Argument(..., help="Path to checkpoint directory"),
    config: Path | None = typer.Option(None, help="Config YAML (auto-generated if omitted)"),
) -> None:
    """Resume a run from a checkpoint."""
    from ari.orchestrator.node import Node, NodeStatus

    tree_file = checkpoint_dir / "tree.json"
    if not tree_file.exists():
        console.print(f"[red]Checkpoint not found: {tree_file}[/red]")
        raise typer.Exit(1)

    with open(tree_file) as f:
        tree_data = json.load(f)

    run_id = tree_data["run_id"]
    # Prefer checkpoint/experiment.md over tree.json path (may be stale)
    _ckpt_exp_r = checkpoint_dir / "experiment.md"
    experiment_file = str(_ckpt_exp_r) if _ckpt_exp_r.exists() else tree_data["experiment_file"]
    exp_path = Path(experiment_file)
    experiment_text = exp_path.read_text() if exp_path.exists() else ""
    import re as _re_t3
    _tm3 = _re_t3.search(r"^#\s*(.+)", experiment_text, _re_t3.MULTILINE)
    _tp3 = _re_t3.sub(r"[^a-zA-Z0-9_-]", "_", (_tm3.group(1)[:40] if _tm3 else Path(experiment_file).stem))
    experiment_data = {"goal": experiment_text, "topic": _tp3, "file": experiment_file}

    cfg = load_config(str(config)) if config and config.exists() else auto_config()
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
        # Restore label (default to DRAFT if missing from old checkpoints)
        _lbl = nd.get("label", "draft")
        if hasattr(node, "label"):
            from ari.orchestrator.node import NodeLabel as _NL
            try:
                node.label = _NL.from_str(_lbl) if hasattr(_NL, "from_str") else _NL(_lbl)
            except Exception:
                pass
        node.metrics = nd.get("metrics") or {}
        node.has_real_data = nd.get("has_real_data", False)
        node_map[node.id] = node

    all_nodes = list(node_map.values())
    completed = sum(1 for n in all_nodes if n.status == NodeStatus.SUCCESS)
    pending = [
        n for n in all_nodes
        if n.status == NodeStatus.PENDING
        or n.status == NodeStatus.FAILED
    ]
    for n in pending:
            n.status = NodeStatus.PENDING
            n.error_log = None

    console.print(Panel(
        f"[bold]Resuming {run_id}[/bold]\n{experiment_file}\n"
        f"{len(all_nodes)} total | {completed} completed | {len(pending)} pending",
        title="ARI Resume",
    ))

    if not pending:
        console.print("[yellow]No pending nodes.[/yellow]")
        raise typer.Exit(0)

    _, _, _, bfts, agent, _, _ = build_runtime(cfg, experiment_text)
    agent.checkpoint_dir = str(checkpoint_dir)
    from ari.pidfile import pid_context
    with pid_context(checkpoint_dir):
        total = _run_loop(cfg, bfts, agent, pending, all_nodes,
                          experiment_data, checkpoint_dir, run_id, total_processed=completed)
        _, _, mcp_resume, _, _, _, _ = build_runtime(cfg, experiment_text)
        console.print(Panel(
            f"[bold green]Resume complete.[/bold green]  +{total - completed} nodes",
            title="Done",
        ))
        _pkg_wf_r = Path(__file__).parent.parent / "config" / "workflow.yaml"
        _cfg_str_r = str(config) if config else (str(_pkg_wf_r) if _pkg_wf_r.exists() else "")
        try:
            generate_paper_section(all_nodes, experiment_data, checkpoint_dir, mcp_resume, _cfg_str_r)
        except Exception as _paper_err:
            console.print(f"[bold red]Paper pipeline failed:[/bold red] {_paper_err}")
            import traceback
            traceback.print_exc()


@app.command()
def paper(
    checkpoint_dir: Path = typer.Argument(..., help="Path to checkpoint directory"),
    experiment: Path | None = typer.Option(None, help="Experiment .md file (auto-detected from checkpoint if omitted)"),
    config: Path | None = typer.Option(None, help="Config YAML (auto-generated if omitted)"),
) -> None:
    """Run paper pipeline from existing checkpoint (skip experiment phase)."""
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
    _tp_tp = _re_tp.sub(r"[^a-zA-Z0-9_-]", "_", (_tm_tp.group(1)[:40] if _tm_tp else Path(experiment_file).stem))
    experiment_data = {"goal": experiment_text, "topic": _tp_tp, "file": experiment_file}

    cfg = load_config(str(config)) if config and config.exists() else auto_config()
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
    _, _, mcp_paper, _, _, _, _ = build_runtime(cfg, experiment_text)
    console.print(Panel(
        f"[bold green]Running paper pipeline[/bold green]\nCheckpoint: {checkpoint_dir}",
        title="ARI Paper",
    ))
    # Resolve config path: use --config if given, otherwise find package workflow.yaml
    from pathlib import Path as _PL
    _pkg_wf = _PL(__file__).parent.parent / "config" / "workflow.yaml"
    _cfg_str = str(config) if config else (str(_pkg_wf) if _pkg_wf.exists() else "")
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


@app.command("skills-list")
def skills_list(
    config: Path | None = typer.Option(None, help="Config YAML (auto-generated if omitted)"),
) -> None:
    """List available skills/tools."""
    from ari.mcp.client import MCPClient
    cfg = load_config(str(config)) if config and config.exists() else auto_config()
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


def _save_checkpoint(checkpoint_dir, run_id, experiment_file, nodes):
    tree = {
        "run_id": run_id, "experiment_file": experiment_file,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "nodes": [n.to_dict() for n in nodes],
    }
    (checkpoint_dir / "tree.json").write_text(json.dumps(tree, indent=2, ensure_ascii=False))
    results = {
        "run_id": run_id,
        "nodes": {n.id: {"artifacts": n.artifacts, "metrics": n.metrics,
                          "has_real_data": n.has_real_data, "eval_summary": n.eval_summary,
                          "status": n.status.value, "error_log": n.error_log}
                  for n in nodes},
    }
    (checkpoint_dir / "results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False))


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

    # Node tree
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
        console.print("[yellow]No nodes_tree.json found.[/yellow]")

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
    shutil.rmtree(p)
    console.print(f"[green]✓ Deleted {p.name}[/green]")


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

if __name__ == "__main__":
    app()
