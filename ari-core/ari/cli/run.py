"""``ari run`` / ``ari resume`` Typer commands + their helpers (Phase 3A).

Hosts the CLI entry points that drive a fresh BFTS run or resume an
existing checkpoint.  The Typer decorators register against
``ari.cli.app`` at import time; ``ari/cli/__init__.py`` imports this
module after defining ``app`` so the decorators are honoured.
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
from ari.core import build_runtime as _real_build_runtime, generate_paper_section as _real_generate_paper_section  # noqa: F401
from ari.paths import PathManager


# Phase 3A — defer build_runtime / generate_paper_section lookups to
# ``ari.cli`` so existing tests that
# ``mock.patch("ari.cli.build_runtime", ...)`` continue to intercept
# the call from inside the run / resume command bodies.
def build_runtime(*args, **kwargs):
    from ari import cli as _cli
    return _cli.build_runtime(*args, **kwargs)


def generate_paper_section(*args, **kwargs):
    from ari import cli as _cli
    return _cli.generate_paper_section(*args, **kwargs)
from ari.pipeline import _extract_plan_sections

from ari.cli import app, console
from ari.cli.bfts_loop import (
    _save_checkpoint,
    _save_tree_incremental,
)
from ari.cli.commands import _safe_backup


# Phase 3A — defer ``_run_loop`` lookup to ``ari.cli`` so tests that
# ``mock.patch("ari.cli._run_loop", ...)`` keep intercepting the call
# even though the implementation moved to ``ari.cli.bfts_loop``.
def _run_loop(*args, **kwargs):
    from ari import cli as _cli
    return _cli._run_loop(*args, **kwargs)
from ari.cli.lineage import (
    _LINEAGE_LOG,
    _build_idea_ctx_for_expand,
    _execute_lineage_decision,
    _load_lineage_decision_config,
    _mark_parent_terminated,
)


log = logging.getLogger(__name__)




def _resolve_cfg(config: "Path | None"):
    """Load config from --config, else fall back to the package workflow.yaml.

    Using auto_config() when no --config is given drops `disabled_tools`
    (saved by the GUI Workflow page) because auto_config does not read
    workflow.yaml. Falling back to the package workflow.yaml honours the
    GUI toggles in BFTS and paper phases alike.

    Package-yaml discovery is delegated to ``ari.config.finder`` so the
    bundled-fallback path lives in one place (Phase 2 §6-2).  The CLI
    only consults the package fallback (no checkpoint search) so the
    existing semantic — "explicit --config wins, then bundle, then
    auto_config()" — is preserved exactly.
    """
    if config and config.exists():
        return load_config(str(config))
    from ari.config.finder import package_config_root
    _pkg_wf = package_config_root() / "workflow.yaml"
    if _pkg_wf.exists():
        return load_config(str(_pkg_wf))
    return auto_config()



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
    # Remove FileHandlers attached by previous _setup_logging calls. Without
    # this, repeated invocations (e.g. tests, GUI relaunches) leak handlers
    # whose underlying files may have been deleted, causing FileNotFoundError
    # on subsequent log emissions.
    for existing in list(root.handlers):
        if isinstance(existing, logging.FileHandler) and Path(existing.baseFilename).name == "ari.log":
            root.removeHandler(existing)
            try:
                existing.close()
            except Exception:
                pass
    root.addHandler(fh)




def _apply_profile(cfg, profile_name: str) -> None:
    """Deep-merge an environment profile into the config."""
    import yaml as _yaml
    # Profiles live at ari-core/config/profiles/, resolved via the single
    # package-config accessor so call sites don't hardcode the walk-up depth.
    from ari.config.finder import package_config_root
    profiles_dir = package_config_root() / "profiles"
    p = profiles_dir / f"{profile_name}.yaml"
    if not p.exists():
        logging.getLogger(__name__).warning(
            "profile %r not found at %s — profile overrides ignored", profile_name, p
        )
        return
    overrides = _yaml.safe_load(p.read_text()) or {}
    # Apply bfts overrides
    bfts_o = overrides.get("bfts", {})
    if "max_total_nodes" in bfts_o:
        cfg.bfts.max_total_nodes = bfts_o["max_total_nodes"]
    # Profile YAMLs use "parallel" (historical) but BFTSConfig's field is
    # "max_parallel_nodes". Accept both spellings so the setting is not
    # silently dropped into a phantom attribute.
    if "max_parallel_nodes" in bfts_o:
        cfg.bfts.max_parallel_nodes = bfts_o["max_parallel_nodes"]
    elif "parallel" in bfts_o:
        cfg.bfts.max_parallel_nodes = bfts_o["parallel"]
    # Apply hpc overrides — controls whether Slurm workflow is used
    hpc_o = overrides.get("hpc", {})
    if "enabled" in hpc_o:
        cfg.resources["hpc_enabled"] = hpc_o["enabled"]
    if "scheduler" in hpc_o:
        cfg.resources["scheduler"] = hpc_o["scheduler"]



@app.command()
def run(
    experiment: Path = typer.Argument(..., help="Path to experiment .md file (only required input)"),
    config: Path | None = typer.Option(None, help="Config YAML (auto-generated if omitted)"),
    profile: str | None = typer.Option(None, help="Environment profile: laptop, hpc, cloud"),
    virsci_live: bool = typer.Option(
        False, "--virsci-live/--no-virsci-live",
        help="Idea skill: run VirSci's real multi-agent engine on a live Semantic Scholar snapshot (vendor-wrap). Sets ARI_IDEA_VIRSCI_REAL.",
    ),
    virsci_k: int | None = typer.Option(None, "--virsci-k", help="VirSci-live: discussion turns (group_max_discuss_iteration, default 7)."),
    virsci_team_size: int | None = typer.Option(None, "--virsci-team-size", help="VirSci-live: max team members per team (default 3)."),
    virsci_n_authors: int | None = typer.Option(None, "--virsci-n-authors", help="VirSci-live: author pool size for select_coauthors (default 16)."),
    virsci_n_papers: int | None = typer.Option(None, "--virsci-n-papers", help="VirSci-live: SPECTER2 retrieval corpus size (default 800)."),
) -> None:
    """Run an experiment. Only the .md file is required."""
    from ari.orchestrator.node import Node
    import hashlib as _hl_run

    experiment = experiment.expanduser()
    if not experiment.is_file():
        logging.getLogger(__name__).error("experiment path not found: %s", experiment.resolve())
        typer.echo(
            typer.style("File not found: ", fg=typer.colors.RED, bold=True)
            + str(experiment)
            + "\n\n"
            + "See docs/experiment_file.md for the experiment.md format.\n",
            err=True,
        )
        raise typer.Exit(1)

    # VirSci-live (idea skill vendor-wrap): set the ARI_IDEA_VIRSCI_* contract.
    # The idea skill reads these via os.getenv and mcp/client.py propagates env
    # to the skill subprocess. Mirrors projects.py's ARI_RUBRIC handling.
    if virsci_live:
        os.environ["ARI_IDEA_VIRSCI_REAL"] = "1"
    if virsci_k is not None:
        os.environ["ARI_IDEA_VIRSCI_K"] = str(virsci_k)
    if virsci_team_size is not None:
        os.environ["ARI_IDEA_VIRSCI_TEAM_SIZE"] = str(virsci_team_size)
    if virsci_n_authors is not None:
        os.environ["ARI_IDEA_VIRSCI_N_AUTHORS"] = str(virsci_n_authors)
    if virsci_n_papers is not None:
        os.environ["ARI_IDEA_VIRSCI_N_PAPERS"] = str(virsci_n_papers)

    experiment_text = experiment.read_text()
    # ── Trace: log experiment file as read from disk ────────────────
    _exp_hash = _hl_run.sha256(experiment_text.encode()).hexdigest()[:16]
    logging.getLogger(__name__).info(
        "[cli.run] experiment file read: path=%s len=%d sha256=%s",
        experiment, len(experiment_text), _exp_hash,
    )
    cfg = _resolve_cfg(config)

    # Apply environment profile overrides
    if profile:
        _apply_profile(cfg, profile)

    # GUI-supplied caps (ARI_MAX_NODES etc.) must win over profile defaults.
    from ari.config import (
        apply_bfts_env_overrides, apply_evaluator_env_overrides,
        export_resolved_config_to_skill_env,
    )
    apply_bfts_env_overrides(cfg)
    apply_evaluator_env_overrides(cfg)
    # Bridge the resolved config (model / backend / base_url / partition) to the env
    # vars skill subprocesses read, so a bare CLI run configures skills like the GUI
    # does — without this the idea skill fell back to Ollama and the HPC skill to
    # sinfo's first partition. Runs AFTER overrides so env-supplied values still win.
    export_resolved_config_to_skill_env(cfg)

    # ── Container support ───────────────────────────────
    # Read container config from workflow.yaml; if an image is specified and
    # mode != "none", detect runtime and pull the image when policy requires.
    # Export ARI_CONTAINER_IMAGE / ARI_CONTAINER_MODE so MCP skill processes
    # (which inherit os.environ) can wrap run_bash commands in the container.
    try:
        import yaml as _yaml_ct
        from ari.config.finder import package_config_root
        _wf_ct_path = package_config_root() / "workflow.yaml"
        _ct_cfg_raw = {}
        if _wf_ct_path.exists():
            _ct_cfg_raw = (_yaml_ct.safe_load(_wf_ct_path.read_text()) or {}).get("container", {})
        _ct_image = os.environ.get("ARI_CONTAINER_IMAGE") or _ct_cfg_raw.get("image", "")
        _ct_mode = os.environ.get("ARI_CONTAINER_MODE") or _ct_cfg_raw.get("mode", "auto")
        _ct_pull = _ct_cfg_raw.get("pull", "on_start")
        if _ct_image and _ct_mode != "none":
            from ari.container import ContainerConfig, detect_runtime, pull_image
            _ct_conf = ContainerConfig(image=_ct_image, mode=_ct_mode, pull=_ct_pull)
            _ct_runtime = detect_runtime() if _ct_mode == "auto" else _ct_mode
            console.print(f"[dim]Container: image={_ct_image}  runtime={_ct_runtime}  pull={_ct_pull}[/dim]")
            if _ct_pull in ("always", "on_start"):
                console.print("[dim]Pulling container image...[/dim]")
                if pull_image(_ct_conf):
                    console.print("[green]Container image pulled.[/green]")
                else:
                    console.print("[yellow]Container pull failed or skipped.[/yellow]")
            # Propagate to child processes (MCP skills) so run_bash uses the container
            os.environ["ARI_CONTAINER_IMAGE"] = _ct_image
            os.environ["ARI_CONTAINER_MODE"] = _ct_runtime
    except Exception as _ct_err:
        logging.getLogger(__name__).debug("Container setup skipped: %s", _ct_err)

    # Build human-readable run_id: yyyymmddHHMMSS_<experiment_slug>
    import re as _re_t2
    from datetime import datetime as _dt
    # When the GUI launcher pre-creates a checkpoint directory and passes its
    # path via ARI_CHECKPOINT_DIR, adopt that directory's name as the run_id.
    # This keeps checkpoints/{run_id}/ and experiments/{run_id}/ aligned so
    # deleting a project via the dashboard also cleans up the per-node work
    # directories. Without this, the CLI minted a fresh timestamp + LLM slug
    # here, producing a different name from the GUI's checkpoint dir, and the
    # delete handler (which joins experiments_root with the checkpoint name)
    # left the experiments directory as an orphan.
    _gui_ckpt_path = PathManager.checkpoint_dir_from_env()
    _adopted_run_id = _gui_ckpt_path.name if _gui_ckpt_path is not None else ""
    if _adopted_run_id:
        run_id = _adopted_run_id
        # Best-effort raw name for UI labels: strip the leading timestamp.
        _raw_name = _re_t2.sub(r"^\d{14}_", "", _adopted_run_id) or experiment.stem
        _slug = _raw_name
    else:
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
                _raw_name = _stripped[:100]
                break
        _slug = _re_t2.sub(r"[^a-zA-Z0-9_-]", "_", _raw_name).strip("_")[:80]
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
    # ── Trace: log experiment_data["goal"] hash for propagation tracking ──
    logging.getLogger(__name__).info(
        "[cli.run] experiment_data['goal']: len=%d sha256=%s",
        len(experiment_data["goal"]),
        _hl_run.sha256(experiment_data["goal"].encode()).hexdigest()[:16],
    )

    checkpoint_dir = Path(cfg.checkpoint.dir.replace("{run_id}", run_id))
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    (checkpoint_dir / "uploads").mkdir(exist_ok=True)
    # Reproducibility caveat: when web search is opted into for BFTS
    # exploration (ARI_BFTS_ALLOW_WEB / bfts.allow_web), live web results are
    # time-varying, so the search trajectory is no longer guaranteed
    # reproducible (P5). Record a durable marker + warn. Default-off = no-op.
    if getattr(cfg.bfts, "allow_web", False):
        from ari.orchestrator.web_provenance import write_provenance
        write_provenance(checkpoint_dir)
        logging.getLogger(__name__).warning(
            "[cli.run] Web search ENABLED during BFTS exploration "
            "(ARI_BFTS_ALLOW_WEB / bfts.allow_web): search trajectory is NOT "
            "guaranteed reproducible. Recorded bfts_web_provenance.json."
        )
        console.print(
            "[yellow]⚠ Web search enabled during BFTS exploration — the search "
            "trajectory is NOT guaranteed reproducible "
            "(recorded in bfts_web_provenance.json).[/yellow]"
        )
    # auto-migrate v0.5.x sources on first launch.
    try:
        from ari.memory.auto_migrate import maybe_auto_migrate
        _am = maybe_auto_migrate(checkpoint_dir)
        if _am.get("ran") and _am.get("imported"):
            logging.getLogger(__name__).info(
                "v0.5.x auto-migration: %s", _am["imported"]
            )
    except Exception as _amerr:
        logging.getLogger(__name__).warning(
            "auto-migrate skipped: %s", _amerr
        )
    # — on-exit backup.
    try:
        import atexit as _atexit_bk
        from ari.memory_cli import _do_backup as _do_bk
        _atexit_bk.register(lambda _p=checkpoint_dir: _safe_backup(_p))
    except Exception:
        pass
    _, _, mcp, bfts, agent, _ = build_runtime(cfg, experiment_text, checkpoint_dir=checkpoint_dir)
    root = Node(id=f"node_{run_id}_root", parent_id=None, depth=0)
    root.name = f"root: {_raw_name[:100]}"
    all_nodes = [root]
    pending = [root]
    agent.checkpoint_dir = str(checkpoint_dir)
    # Copy experiment.md into checkpoint dir so the dashboard can display it immediately
    import shutil as _shutil_cp
    try:
        _shutil_cp.copy2(str(experiment), checkpoint_dir / "experiment.md")
    except Exception:
        pass
    # Copy workflow.yaml into checkpoint dir for reproducibility. Skip when
    # the GUI launcher (api_experiment._api_launch) has already populated it,
    # because that copy may carry per-launch rewrites (e.g. include_ear=False
    # disabling EAR / ors_seed_sandbox stages) that an unconditional copy from
    # source would silently undo.
    from ari.config.finder import package_config_root
    _wf_src = config if config and config.exists() else (package_config_root() / "workflow.yaml")
    _wf_dst = checkpoint_dir / "workflow.yaml"
    if _wf_src and Path(_wf_src).exists() and not _wf_dst.exists():
        try:
            _shutil_cp.copy2(str(_wf_src), _wf_dst)
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
        # Resolve config_path. Prefer the per-checkpoint workflow.yaml so any
        # launch-time rewrites (e.g. include_ear=False disabling EAR / ors_seed
        # stages) actually drive the paper pipeline. Fall back to --config or
        # the package source for direct CLI runs that never wrote a checkpoint
        # copy.
        from ari.config.finder import package_config_root
        _pkg_wf = package_config_root() / "workflow.yaml"
        _ckpt_wf = checkpoint_dir / "workflow.yaml"
        if _ckpt_wf.exists():
            _cfg_str = str(_ckpt_wf)
        elif config:
            _cfg_str = str(config)
        else:
            _cfg_str = str(_pkg_wf) if _pkg_wf.exists() else ""
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
    _tp3 = _re_t3.sub(r"[^a-zA-Z0-9_-]", "_", (_tm3.group(1)[:80] if _tm3 else Path(experiment_file).stem))
    experiment_data = {"goal": experiment_text, "topic": _tp3, "file": experiment_file}

    cfg = _resolve_cfg(config)
    # The explicit checkpoint_dir argument is the single source of truth for
    # both checkpoint files and logs; ignore stale CWD-relative defaults from
    # LoggingConfig/CheckpointConfig (which would otherwise write into
    # ./checkpoints/{run_id}/ regardless of where the checkpoint actually lives).
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

    #+ — auto-migrate v0.5.x sources
    # and auto-restore from memory_backup.jsonl.gz when Letta is empty.
    try:
        from ari.memory.auto_migrate import maybe_auto_migrate
        maybe_auto_migrate(checkpoint_dir)
    except Exception as _amerr:
        logging.getLogger(__name__).warning("auto-migrate skipped: %s", _amerr)
    if os.environ.get("ARI_MEMORY_AUTO_RESTORE", "true").lower() != "false":
        try:
            from ari.memory_cli import _do_restore, _backup_path
            if _backup_path(checkpoint_dir).exists():
                from ari.memory import get_backend
                PathManager.set_checkpoint_dir_env(checkpoint_dir)
                _b = get_backend(checkpoint_dir=checkpoint_dir)
                if not _b.list_all_nodes().get("by_node") and not _b.list_react_entries():
                    _r = _do_restore(checkpoint_dir, on_conflict="skip")
                    logging.getLogger(__name__).info(
                        "auto-restore from backup: %s", _r
                    )
        except Exception as _reerr:
            logging.getLogger(__name__).warning("auto-restore skipped: %s", _reerr)

    _, _, _, bfts, agent, _ = build_runtime(cfg, experiment_text, checkpoint_dir=checkpoint_dir)
    agent.checkpoint_dir = str(checkpoint_dir)
    from ari.pidfile import pid_context
    with pid_context(checkpoint_dir):
        total = _run_loop(cfg, bfts, agent, pending, all_nodes,
                          experiment_data, checkpoint_dir, run_id, total_processed=completed)
        _, _, mcp_resume, _, _, _ = build_runtime(cfg, experiment_text, checkpoint_dir=checkpoint_dir)
        console.print(Panel(
            f"[bold green]Resume complete.[/bold green]  +{total - completed} nodes",
            title="Done",
        ))
        # Prefer per-checkpoint workflow.yaml (carries launch-time rewrites)
        # over the package source.
        from ari.config.finder import package_config_root
        _pkg_wf_r = package_config_root() / "workflow.yaml"
        _ckpt_wf_r = checkpoint_dir / "workflow.yaml"
        if _ckpt_wf_r.exists():
            _cfg_str_r = str(_ckpt_wf_r)
        elif config:
            _cfg_str_r = str(config)
        else:
            _cfg_str_r = str(_pkg_wf_r) if _pkg_wf_r.exists() else ""
        try:
            generate_paper_section(all_nodes, experiment_data, checkpoint_dir, mcp_resume, _cfg_str_r)
        except Exception as _paper_err:
            console.print(f"[bold red]Paper pipeline failed:[/bold red] {_paper_err}")
            import traceback
            traceback.print_exc()

