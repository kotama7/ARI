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

app = typer.Typer(name="ari", help="ARI - Artificial Research Intelligence")
console = Console()


def _resolve_cfg(config: "Path | None"):
    """Load config from --config, else fall back to the package workflow.yaml.

    Using auto_config() when no --config is given drops `disabled_tools`
    (saved by the GUI Workflow page) because auto_config does not read
    workflow.yaml. Falling back to the package workflow.yaml honours the
    GUI toggles in BFTS and paper phases alike.
    """
    if config and config.exists():
        return load_config(str(config))
    _pkg_wf = Path(__file__).parent.parent / "config" / "workflow.yaml"
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
    root.addHandler(fh)


# ─────────────────────────────────────────
# Incremental tree.json writer
# ─────────────────────────────────────────
# tree.json/nodes_tree.json drive the GUI Tree view. Writing them only at the
# end of a batch means the frontend sees nothing until every node in the batch
# finishes its ReAct loop. These helpers let the orchestrator and the agent
# loop flush current state mid-run so the GUI (polling /state every 5 s) can
# animate tree growth, RUNNING transitions, and trace_log accumulation.

_tree_save_lock = threading.Lock()
_tree_save_min_interval_s = 1.0
_tree_last_save_mono: dict[str, float] = {}


def _save_tree_incremental(
    checkpoint_dir,
    run_id,
    experiment_file,
    nodes,
    *,
    force: bool = False,
) -> None:
    """Thread-safe + throttled wrapper around ``_save_checkpoint``.

    Multiple worker threads call this concurrently while agents run in
    parallel. The lock serialises writes so partial JSON never reaches the
    GUI; the throttle avoids thrashing disk on every ReAct step. ``force``
    bypasses the throttle (used on node terminal state transitions).
    """
    key = str(checkpoint_dir)
    now = time.monotonic()
    with _tree_save_lock:
        if not force:
            last = _tree_last_save_mono.get(key, 0.0)
            if now - last < _tree_save_min_interval_s:
                return
        _tree_last_save_mono[key] = now
        try:
            _save_checkpoint(checkpoint_dir, run_id, experiment_file, list(nodes))
        except Exception:
            logging.getLogger(__name__).debug("incremental tree save failed", exc_info=True)


def _run_loop(cfg, bfts, agent, pending, all_nodes, experiment_data,
              checkpoint_dir, run_id, total_processed=0):
    from ari.orchestrator.node import NodeStatus
    max_workers = max(1, min(cfg.bfts.max_parallel_nodes, 4))

    # Read bfts_pipeline enabled flags from workflow.yaml
    _bfts_disabled_stages: set[str] = set()
    try:
        import yaml as _yaml_bfts
        from pathlib import Path as _P_bfts
        _wf_path = _P_bfts(checkpoint_dir) / "workflow.yaml"
        if not _wf_path.exists():
            _wf_path = _P_bfts(__file__).parent.parent / "config" / "workflow.yaml"
        if _wf_path.exists():
            _wf_data = _yaml_bfts.safe_load(_wf_path.read_text()) or {}
            for _s in _wf_data.get("bfts_pipeline") or []:
                if not _s.get("enabled", True):
                    _bfts_disabled_stages.add(_s.get("stage", ""))
    except Exception:
        pass
    _expand_enabled = "frontier_expand" not in _bfts_disabled_stages

    # Install a progress callback on the agent so the ReAct loop can flush
    # tree.json mid-run (status transitions, trace_log growth). Every worker
    # thread shares the same callback; throttling is handled inside.
    def _flush_tree_progress(force: bool = False) -> None:
        _save_tree_incremental(
            checkpoint_dir, run_id, experiment_data["file"], all_nodes,
            force=force,
        )
    agent._progress_cb = _flush_tree_progress

    # Seed tree.json immediately so the GUI can render the root node while the
    # very first ReAct loop is still running.
    _flush_tree_progress(force=True)

    # frontier: completed nodes not yet expanded (true BFTS: expand on demand)
    frontier: list = []

    # Load idea context from checkpoint for BFTS expansion
    _idea_ctx_for_expand = ""
    from pathlib import Path as _Path_idea
    _idea_json_path = _Path_idea(checkpoint_dir) / "idea.json"
    if _idea_json_path.exists():
        try:
            import json as _json_idea
            _idea_data = _json_idea.loads(_idea_json_path.read_text())
            _ideas = _idea_data.get("ideas", [])
            _gap = _idea_data.get("gap_analysis", "")
            if _ideas:
                _best = _ideas[0]
                _idea_ctx_for_expand = (
                    f"Gap: {_gap[:300]}\n"
                    f"Idea: {_best.get('title', '')}\n"
                    f"Description: {_best.get('description', '')[:400]}\n"
                    f"Plan: {_best.get('experiment_plan', '')[:400]}"
                )
        except Exception:
            pass

    while pending or (_expand_enabled and frontier and len(all_nodes) < cfg.bfts.max_total_nodes):
        # --- BFTS STEP: fill empty worker slots one at a time ---
        # Each iteration of the inner loop calls expand() ONCE and produces ONE
        # new child. Frontier nodes are NOT removed when expanded — they stay
        # available for re-expansion when the worker pool still has free slots
        # and no fresher frontier candidate exists. Two round-local sets:
        #   _touched_this_round  — already expanded at least once this round
        #                          (still re-selectable as a fallback)
        #   _failed_this_round   — expand() raised; do NOT retry until next
        #                          outer iteration (prevents tight retry loops)
        _budget = cfg.bfts.max_total_nodes - len(all_nodes)
        _touched_this_round: set[str] = set()
        _failed_this_round: set[str] = set()
        while frontier and len(pending) < max_workers and _budget > 0:
            # Prefer untouched frontier nodes (spreads work across parents).
            _untouched = [
                n for n in frontier
                if n.id not in _touched_this_round and n.id not in _failed_this_round
            ]
            if _untouched:
                _eligible = _untouched
            else:
                # All frontier nodes have already been expanded once this round;
                # allow re-expansion of any that did not fail. The LLM receives
                # existing_children so it does not propose duplicate directions.
                _eligible = [n for n in frontier if n.id not in _failed_this_round]
            if not _eligible:
                # Every frontier node failed this round → bail out and let the
                # next outer iteration retry with a fresh round.
                break
            try:
                best = bfts.select_best_to_expand(_eligible, experiment_data["goal"], agent.memory)
            except Exception as exc:
                logging.getLogger(__name__).warning("select_best_to_expand failed: %s", exc)
                best = _eligible[0]
            if bfts.should_prune(best):
                # Pruned nodes are removed permanently from the frontier.
                if best in frontier:
                    frontier.remove(best)
                _touched_this_round.discard(best.id)
                console.print(f"  [yellow]Pruned frontier node {best.id[-8:]}[/yellow]")
                continue
            try:
                # Reload idea context if not yet loaded (root node creates idea.json during run)
                if not _idea_ctx_for_expand and _idea_json_path.exists():
                    try:
                        _idea_data = _json_idea.loads(_idea_json_path.read_text())
                        _ideas = _idea_data.get("ideas", [])
                        _gap = _idea_data.get("gap_analysis", "")
                        if _ideas:
                            _best = _ideas[0]
                            _idea_ctx_for_expand = (
                                f"Gap: {_gap[:300]}\n"
                                f"Idea: {_best.get('title', '')}\n"
                                f"Description: {_best.get('description', '')[:400]}\n"
                                f"Plan: {_best.get('experiment_plan', '')[:400]}"
                            )
                    except Exception:
                        pass
                # Build context for label-free expansion: siblings (same depth, same parent),
                # ancestors (chain from root to parent), all run nodes (for diversity),
                # and existing children of `best` (so the LLM doesn't duplicate directions
                # when we re-expand the same parent multiple times).
                _id_to_node = {_n.id: _n for _n in all_nodes}
                _siblings = [
                    _n for _n in all_nodes
                    if _n.id != best.id and _n.parent_id == best.parent_id
                ]
                _ancestors = [
                    _id_to_node[_aid] for _aid in (best.ancestor_ids or [])
                    if _aid in _id_to_node
                ]
                _existing_children = [
                    _id_to_node[_cid] for _cid in (best.children or [])
                    if _cid in _id_to_node
                ]
                children = bfts.expand(
                    best,
                    experiment_goal=experiment_data.get("goal", ""),
                    idea_context=_idea_ctx_for_expand,
                    siblings=_siblings,
                    ancestors=_ancestors,
                    all_run_nodes=list(all_nodes),
                    existing_children=_existing_children,
                )
                all_nodes.extend(children)
                pending.extend(children)
                _budget -= len(children)
                _touched_this_round.add(best.id)
                console.print(f"  [cyan]Expanded {best.id[-8:]} (sci={best.metrics.get('_scientific_score','?') if best.metrics else '?'}) -> {len(children)} children[/cyan]")
                # Flush so new PENDING children show up in the GUI Tree view
                # before the batch starts running them.
                _flush_tree_progress(force=True)
            except Exception as exc:
                logging.getLogger(__name__).warning("expand failed: %s", exc)
                # Don't tight-loop on a broken node: skip it for the rest of
                # this round. The next outer iteration will retry it.
                _failed_this_round.add(best.id)

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
            # Track recently-run labels so the diversity bonus can react.
            try:
                bfts.record_run(node)
            except Exception:
                pass
            batch.append(node)

        console.print(f"\n[bold]Processing {len(batch)} node(s) in parallel...[/bold]")
        # Flush again so the selected batch is visible while work_dirs are set
        # up and files are being copied (this can take a few seconds for large
        # uploads on HPC filesystems).
        _flush_tree_progress(force=True)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Create per-node work directory via PathManager.
            # Key by run_id (not topic slug) so concurrent/serial runs with the
            # same experiment name never share experiments/{bucket}/ and risk
            # collisions between UUID-suffixed child nodes.
            _pm = PathManager.from_checkpoint_dir(checkpoint_dir)
            for _n in batch:
                _nd = _pm.ensure_node_work_dir(run_id, _n.id)
                _n.work_dir = str(_nd)
            # Inherit parent node's work_dir contents (directory tree, configs,
            # generated files, scripts, intermediate artifacts). This gives
            # improve/debug/ablation/validation children the full parent state
            # to build on, not just a textual summary. Runs BEFORE provided/
            # checkpoint copies so the parent's (possibly modified) versions
            # take precedence via the `not _dst.exists()` guards below.
            import shutil as _sh_parent
            for _n in batch:
                _pid = getattr(_n, "parent_id", None)
                if not _pid:
                    continue
                _parent_wd = _pm.node_work_dir(run_id, _pid)
                if not _parent_wd.is_dir():
                    continue
                _dst_root = Path(_n.work_dir)
                try:
                    for _src in _parent_wd.rglob("*"):
                        if _src.is_dir():
                            continue
                        if PathManager.is_meta_file(_src.name):
                            continue
                        _rel = _src.relative_to(_parent_wd)
                        _dst = _dst_root / _rel
                        if _dst.exists():
                            continue
                        _dst.parent.mkdir(parents=True, exist_ok=True)
                        _sh_parent.copy2(str(_src), str(_dst))
                    logging.getLogger(__name__).info(
                        "Inherited parent work_dir %s -> %s", _parent_wd, _dst_root
                    )
                except Exception as _pe:
                    logging.getLogger(__name__).warning(
                        "Could not inherit parent work_dir %s: %s", _parent_wd, _pe
                    )
            # Inject work_dir into per-node experiment copy
            # Copy provided_files (parsed from .md) into each node's work_dir
            _provided = getattr(agent.hints, "provided_files", []) if hasattr(agent, "hints") else []
            for _n in batch:
                for _src, _fname in _provided:
                    try:
                        import shutil as _sh
                        _dst = Path(_n.work_dir) / _fname
                        if Path(_src).exists() and not _dst.exists():
                            _sh.copy2(_src, _dst)
                            logging.getLogger(__name__).info(
                                "Copied %s → %s", _src, _dst
                            )
                    except Exception as _ce:
                        logging.getLogger(__name__).warning(
                            "Could not copy provided file %s: %s", _src, _ce
                        )
            # Plan B: copy all user files from checkpoint dir into each node's work_dir
            _ckpt_path = Path(checkpoint_dir)
            if _ckpt_path.is_dir():
                import shutil as _sh_ckpt
                for _cf in _ckpt_path.iterdir():
                    if not _cf.is_file():
                        continue
                    if PathManager.is_meta_file(_cf.name):
                        continue
                    for _n in batch:
                        try:
                            _dst_ckpt = Path(_n.work_dir) / _cf.name
                            if not _dst_ckpt.exists():
                                _sh_ckpt.copy2(str(_cf), str(_dst_ckpt))
                                logging.getLogger(__name__).info(
                                    "Copied checkpoint file %s → %s", _cf.name, _dst_ckpt
                                )
                        except Exception as _ce2:
                            logging.getLogger(__name__).warning(
                                "Could not copy checkpoint file %s: %s", _cf.name, _ce2
                            )

            # Plan B extension: also copy files from checkpoint_dir/uploads/.
            # Recurse so nested subdirectories and their files are preserved,
            # and mirror each file at two locations in the node work_dir:
            #   1. {work_dir}/{rel_path}              (e.g. ./foo.csv)
            #   2. {work_dir}/uploads/{rel_path}      (e.g. ./uploads/foo.csv)
            # This lets user scripts reference uploads either by bare name or
            # by uploads/ prefix, matching however they wrote the paths.
            _uploads_path = _ckpt_path / "uploads"
            if _uploads_path.is_dir():
                import shutil as _sh_up
                for _uf in _uploads_path.rglob("*"):
                    if _uf.is_dir():
                        continue
                    if PathManager.is_meta_file(_uf.name):
                        continue
                    _rel = _uf.relative_to(_uploads_path)
                    for _n in batch:
                        for _dst_upload in (
                            Path(_n.work_dir) / _rel,
                            Path(_n.work_dir) / "uploads" / _rel,
                        ):
                            try:
                                if _dst_upload.exists():
                                    continue
                                _dst_upload.parent.mkdir(parents=True, exist_ok=True)
                                _sh_up.copy2(str(_uf), str(_dst_upload))
                                logging.getLogger(__name__).info(
                                    "Copied uploaded file %s -> %s", _rel, _dst_upload
                                )
                            except Exception as _ce3:
                                logging.getLogger(__name__).warning(
                                    "Could not copy uploaded file %s: %s", _rel, _ce3
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
                _save_tree_incremental(
                    checkpoint_dir, run_id, experiment_data["file"], all_nodes,
                    force=True,
                )

        _save_tree_incremental(
            checkpoint_dir, run_id, experiment_data["file"], all_nodes,
            force=True,
        )

    return total_processed


def _apply_profile(cfg, profile_name: str) -> None:
    """Deep-merge an environment profile into the config."""
    import yaml as _yaml
    # Profiles live at ari-core/config/profiles/. __file__ is ari-core/ari/cli.py
    # so two .parent hops reach ari-core; a third hop overshoots to the repo root
    # (where no config/ exists) and silently drops every profile override.
    profiles_dir = Path(__file__).parent.parent / "config" / "profiles"
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
        _wf_ct_path = Path(__file__).parent.parent / "config" / "workflow.yaml"
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
    _gui_ckpt = os.environ.get("ARI_CHECKPOINT_DIR", "").strip()
    _adopted_run_id = ""
    if _gui_ckpt:
        _adopted_run_id = Path(_gui_ckpt).name
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
    # Copy workflow.yaml into checkpoint dir for reproducibility
    _wf_src = config if config and config.exists() else (Path(__file__).parent.parent / "config" / "workflow.yaml")
    if _wf_src and Path(_wf_src).exists():
        try:
            _shutil_cp.copy2(str(_wf_src), checkpoint_dir / "workflow.yaml")
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
    _tp3 = _re_t3.sub(r"[^a-zA-Z0-9_-]", "_", (_tm3.group(1)[:80] if _tm3 else Path(experiment_file).stem))
    experiment_data = {"goal": experiment_text, "topic": _tp3, "file": experiment_file}

    cfg = _resolve_cfg(config)
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
    _tp_tp = _re_tp.sub(r"[^a-zA-Z0-9_-]", "_", (_tm_tp.group(1)[:80] if _tm_tp else Path(experiment_file).stem))
    experiment_data = {"goal": experiment_text, "topic": _tp_tp, "file": experiment_file}

    cfg = _resolve_cfg(config)
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


def _save_checkpoint(checkpoint_dir, run_id, experiment_file, nodes):
    # ── Trace: record experiment file hash in tree.json for post-mortem ──
    import hashlib as _hl_ck
    _exp_path = Path(experiment_file)
    _exp_sha = ""
    _exp_len = 0
    if _exp_path.exists():
        _exp_bytes = _exp_path.read_bytes()
        _exp_sha = _hl_ck.sha256(_exp_bytes).hexdigest()[:16]
        _exp_len = len(_exp_bytes)
    tree = {
        "run_id": run_id, "experiment_file": experiment_file,
        "experiment_file_sha256": _exp_sha,
        "experiment_file_len": _exp_len,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "nodes": [n.to_dict() for n in nodes],
    }
    (checkpoint_dir / "tree.json").write_text(json.dumps(tree, indent=2, ensure_ascii=False))
    # Also write lightweight nodes_tree.json for backward compat with pipeline stages
    _exp_goal = ""
    try:
        _exp_md_path = checkpoint_dir / "experiment.md"
        if _exp_md_path.exists():
            _exp_goal = _exp_md_path.read_text(encoding="utf-8", errors="replace")[:3000]
    except Exception:
        pass
    nodes_tree = {
        "experiment_goal": _exp_goal,
        "nodes": tree["nodes"],
    }
    (checkpoint_dir / "nodes_tree.json").write_text(json.dumps(nodes_tree, indent=2, ensure_ascii=False))
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
