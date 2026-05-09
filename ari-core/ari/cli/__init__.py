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
# Phase 3A — BFTS run-loop + checkpoint persistence extracted to
# ``ari.cli.bfts_loop``.
from ari.cli.bfts_loop import (  # noqa: F401
    _save_tree_incremental,
    _run_loop,
    _save_checkpoint,
)



def _apply_profile(cfg, profile_name: str) -> None:
    """Deep-merge an environment profile into the config."""
    import yaml as _yaml
    # Profiles live at ari-core/config/profiles/. After Phase 3A
    # ``__file__`` is ``ari-core/ari/cli/__init__.py`` so we walk up
    # three parents (cli → ari → ari-core) to reach the bundled root.
    profiles_dir = Path(__file__).resolve().parent.parent.parent / "config" / "profiles"
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
) -> None:
    """Run an experiment. Only the .md file is required."""
    from ari.orchestrator.node import Node
    import hashlib as _hl_run

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
    from ari.config import apply_bfts_env_overrides
    apply_bfts_env_overrides(cfg)

    # ── Container support ───────────────────────────────
    # Read container config from workflow.yaml; if an image is specified and
    # mode != "none", detect runtime and pull the image when policy requires.
    # Export ARI_CONTAINER_IMAGE / ARI_CONTAINER_MODE so MCP skill processes
    # (which inherit os.environ) can wrap run_bash commands in the container.
    try:
        import yaml as _yaml_ct
        _wf_ct_path = Path(__file__).resolve().parent.parent.parent / "config" / "workflow.yaml"
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
    _, _, mcp, bfts, agent, _, _ = build_runtime(cfg, experiment_text, checkpoint_dir=checkpoint_dir)
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
    _wf_src = config if config and config.exists() else (Path(__file__).resolve().parent.parent.parent / "config" / "workflow.yaml")
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
        _pkg_wf = Path(__file__).resolve().parent.parent.parent / "config" / "workflow.yaml"
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
                from ari_skill_memory.backends import get_backend
                PathManager.set_checkpoint_dir_env(checkpoint_dir)
                _b = get_backend(checkpoint_dir=checkpoint_dir)
                if not _b.list_all_nodes().get("by_node") and not _b.list_react_entries():
                    _r = _do_restore(checkpoint_dir, on_conflict="skip")
                    logging.getLogger(__name__).info(
                        "auto-restore from backup: %s", _r
                    )
        except Exception as _reerr:
            logging.getLogger(__name__).warning("auto-restore skipped: %s", _reerr)

    _, _, _, bfts, agent, _, _ = build_runtime(cfg, experiment_text, checkpoint_dir=checkpoint_dir)
    agent.checkpoint_dir = str(checkpoint_dir)
    from ari.pidfile import pid_context
    with pid_context(checkpoint_dir):
        total = _run_loop(cfg, bfts, agent, pending, all_nodes,
                          experiment_data, checkpoint_dir, run_id, total_processed=completed)
        _, _, mcp_resume, _, _, _, _ = build_runtime(cfg, experiment_text, checkpoint_dir=checkpoint_dir)
        console.print(Panel(
            f"[bold green]Resume complete.[/bold green]  +{total - completed} nodes",
            title="Done",
        ))
        # Prefer per-checkpoint workflow.yaml (carries launch-time rewrites)
        # over the package source.
        _pkg_wf_r = Path(__file__).resolve().parent.parent.parent / "config" / "workflow.yaml"
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
