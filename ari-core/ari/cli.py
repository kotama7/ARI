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
# lineage decision config + executor
# ---------------------------------------------------------------------------

_LINEAGE_LOG = logging.getLogger("ari.cli.lineage")


def _load_lineage_decision_config() -> dict:
    """Read lineage_decision settings from workflow.yaml + active rubric.

    Schema in workflow.yaml::

        lineage_decision:
          mode: off | stagnation_rule | every_node   # default off
          stagnation_window: 5      # only used when mode = stagnation_rule
          stagnation_threshold: 0.02
          min_nodes_before_decision: 3
          rate_limit_per_run: 5     # max actions per run (cap)

    lineage decisions: the active rubric (``ARI_RUBRIC``) may override these
    via a ``lineage_thresholds:`` field, so different venues can tune
    when escalation fires (HPC kernel runs may need a longer window
    than ML training runs):

        # ari-core/config/reviewer_rubrics/<id>.yaml
        lineage_thresholds:
          stagnation_window: 8
          stagnation_threshold: 0.01
          min_nodes_before_decision: 5

    Precedence: rubric override > workflow.yaml > built-in defaults.
    """
    base: dict = {}
    try:
        import yaml as _yaml
        _candidates = [
            Path(__file__).parent.parent / "config" / "workflow.yaml",
            Path.cwd() / "config" / "workflow.yaml",
        ]
        for p in _candidates:
            if p.exists():
                base = (_yaml.safe_load(p.read_text()) or {}).get(
                    "lineage_decision", {}
                ) or {}
                break
    except Exception:
        base = {}

    # Overlay rubric-specific thresholds when present.
    try:
        rid = (os.environ.get("ARI_RUBRIC") or "").strip()
        if rid:
            import yaml as _yaml2
            rubric_path = (
                Path(__file__).parent.parent
                / "config" / "reviewer_rubrics" / f"{rid}.yaml"
            )
            if rubric_path.exists():
                rubric_data = _yaml2.safe_load(rubric_path.read_text()) or {}
                overrides = rubric_data.get("lineage_thresholds") or {}
                if isinstance(overrides, dict):
                    merged = dict(base)
                    for k in (
                        "stagnation_window",
                        "stagnation_threshold",
                        "min_nodes_before_decision",
                        "rate_limit_per_run",
                    ):
                        if k in overrides:
                            merged[k] = overrides[k]
                    base = merged
    except Exception:
        pass
    return base


def _mark_parent_terminated(parent_ckpt: Path, rationale: str) -> None:
    """lineage decisions: write parent_terminated=true into meta.json so any
    descendant run started later can decide whether to cancel itself.

    Existing children (already running) are not signalled — they have
    their own BFTS loops and their own lineage_decision hooks. The
    flag is purely a hint that propagates *forward* through future
    sub-experiment launches.
    """
    meta_p = parent_ckpt / "meta.json"
    try:
        meta = json.loads(meta_p.read_text()) if meta_p.exists() else {}
        if not isinstance(meta, dict):
            meta = {}
        meta["parent_terminated"] = True
        meta["parent_terminated_rationale"] = rationale[:300]
        meta_p.write_text(json.dumps(meta, indent=2))
    except Exception as _e_meta:
        _LINEAGE_LOG.warning("could not mark parent_terminated: %s", _e_meta)


def _execute_lineage_decision(
    decision,                    # LineageDecision
    *,
    parent_run_id: str,
    parent_ckpt: Path,
    experiment_data: dict,
) -> bool:
    """Carry out the LLM-chosen action via Phase 2.5 plumbing.

    Returns True iff the BFTS loop should stop expanding new nodes
    (the ``terminate`` action).
    """
    action = decision.action
    if action in ("continue", None, ""):
        return False
    if action == "terminate":
        _LINEAGE_LOG.info(
            "lineage decision: terminate (rationale=%s)", decision.rationale[:140]
        )
        # lineage decisions: persist the terminate signal in meta.json so
        # descendants spawned after this point can opt out.
        _mark_parent_terminated(parent_ckpt, decision.rationale)
        return True
    if action in ("switch_to_idea", "fanout"):
        if decision.target_idea_index is None:
            _LINEAGE_LOG.warning(
                "lineage decision: %s with no target_idea_index — skipping",
                action,
            )
            return False
        try:
            from ari.viz.api_orchestrator import _api_launch_sub_experiment
        except Exception as e:
            _LINEAGE_LOG.warning("lineage decision: import launch API failed: %s", e)
            return False
        body = {
            "experiment_md": (
                f"Auto-spawned by parent {parent_run_id} via lineage decision "
                f"({action}). Rationale: {decision.rationale[:300]}\n"
            ),
            "parent_run_id": parent_run_id,
            "inherit_idea_index": int(decision.target_idea_index),
        }
        if decision.disable_generate_ideas:
            # lineage decisions: child runs the inherited idea verbatim, no resampling.
            os.environ.setdefault("ARI_DISABLED_TOOLS_FOR_CHILD", "")
        try:
            res = _api_launch_sub_experiment(json.dumps(body).encode())
            _LINEAGE_LOG.info(
                "lineage decision: %s → child %s (rationale=%s)",
                action, res.get("run_id", "?"), decision.rationale[:140],
            )
        except Exception as e:
            _LINEAGE_LOG.warning("lineage decision: launch failed: %s", e)
        return False  # parent continues; child runs in parallel
    return False


def _build_idea_ctx_for_expand(idea_data: dict) -> str:
    """Build the BFTS-expand idea context with §-tag extraction.

    Replaces the legacy 400-char truncation that dropped §4-§6 of the
    VirSci experiment_plan (model calibration / comparisons), causing
    BFTS to never explore those branches. Each section title is always
    included; bodies are truncated only if the total context grows large.
    """
    ideas = idea_data.get("ideas") or []
    if not ideas:
        return ""
    best = ideas[0]
    gap = idea_data.get("gap_analysis", "")
    parts = [
        f"Gap: {gap[:1500]}",
        f"Idea: {best.get('title', '')}",
        f"Description: {best.get('description', '')[:2000]}",
    ]
    plan_text = best.get("experiment_plan", "")
    if plan_text:
        sections = _extract_plan_sections(plan_text)
        if sections:
            plan_lines = ["Plan sections:"]
            # Total body budget for the plan portion. Per-section trimming
            # falls back when overall context grows too large.
            per_section_budget = max(400, 6000 // max(1, len(sections)))
            for tag, title, body in sections:
                plan_lines.append(f"  {tag} {title}")
                if body:
                    plan_lines.append(f"    {body[:per_section_budget]}")
            parts.append("\n".join(plan_lines))
        else:
            parts.append(f"Plan: {plan_text[:4000]}")
    return "\n".join(parts)

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
migrate_app = typer.Typer(name="migrate", help="One-shot data migrations.")
app.add_typer(migrate_app, name="migrate")


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


# ─────────────────────────────────────────
# Incremental tree.json writer
# ─────────────────────────────────────────
# tree.json/nodes_tree.json drive the GUI Tree view. Writing them only at the
# end of a batch means the frontend sees nothing until every node in the batch
# finishes its ReAct loop. These helpers let the orchestrator and the agent
# loop flush current state mid-run so the GUI (polling /state every 5 s) can
# animate tree growth, RUNNING transitions, and trace_log accumulation.
#
# Phase 2 §6-1: throttling + JSON layout live in ``ari.checkpoint``;
# this wrapper just feeds it the (run_id, experiment_file, nodes)
# triple via ``_save_checkpoint``.


def _save_tree_incremental(
    checkpoint_dir,
    run_id,
    experiment_file,
    nodes,
    *,
    force: bool = False,
) -> None:
    """Thread-safe + throttled wrapper around ``_save_checkpoint``.

    Delegates locking and throttling to
    ``ari.checkpoint.save_tree_incremental``; we still own the
    "build the payload from Node objects" step here because Node is a
    BFTS concept, not a checkpoint concept.
    """
    from ari.checkpoint import save_tree_incremental as _save_inc
    nodes_snapshot = list(nodes)
    _save_inc(
        checkpoint_dir,
        lambda: _save_checkpoint(checkpoint_dir, run_id, experiment_file, nodes_snapshot),
        force=force,
    )


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
    # lineage decision bug fix: import json at function scope, not inside the
    # conditional. Otherwise, when idea.json doesn't exist at startup
    # (root node hasn't generated it yet), the reload path inside the
    # BFTS loop tries to use _json_idea before it has been imported,
    # causing every root_idea_selection attempt to fail with
    # "cannot access local variable '_json_idea' where it is not
    # associated with a value".
    import json as _json_idea
    _idea_json_path = _Path_idea(checkpoint_dir) / "idea.json"
    if _idea_json_path.exists():
        try:
            _idea_data = _json_idea.loads(_idea_json_path.read_text())
            _idea_ctx_for_expand = _build_idea_ctx_for_expand(_idea_data)
        except Exception:
            pass

    # lineage decisions: lineage decision config + per-run state
    _lineage_cfg = _load_lineage_decision_config()
    _lineage_mode = str(_lineage_cfg.get("mode", "off")).lower()
    _lineage_stop_requested = False
    _lineage_actions_taken = 0
    _lineage_rate_limit = int(_lineage_cfg.get("rate_limit_per_run", 5) or 5)
    _lineage_min_nodes = int(_lineage_cfg.get("min_nodes_before_decision", 3) or 3)
    _lineage_window = int(_lineage_cfg.get("stagnation_window", 5) or 5)
    _lineage_threshold = float(_lineage_cfg.get("stagnation_threshold", 0.02) or 0.02)
    _lineage_run_id = run_id  # captured for child launches

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
                        # lineage decision: optional LLM root idea selection — runs
                        # ONCE the first time idea.json appears, before any
                        # BFTS expand has used ideas[0]. Skipped when the
                        # idea.json was inherited (parent already chose).
                        try:
                            import yaml as _yaml_root
                            _wf_path = (
                                Path(__file__).parent.parent / "config" / "workflow.yaml"
                            )
                            _wf_for_root = (
                                _yaml_root.safe_load(_wf_path.read_text())
                                if _wf_path.exists() else {}
                            ) or {}
                            _root_cfg = (_wf_for_root.get("root_idea_selection")
                                         or {})
                            _root_enabled = bool(_root_cfg.get("enabled", False))
                        except Exception:
                            _root_enabled = False
                        if _root_enabled:
                            try:
                                _idea_data_pre = _json_idea.loads(
                                    _idea_json_path.read_text()
                                )
                                _already_inherited = (
                                    isinstance(_idea_data_pre, dict)
                                    and "_inherited_from" in _idea_data_pre
                                )
                                _already_chosen = (
                                    isinstance(_idea_data_pre, dict)
                                    and "_root_choice" in _idea_data_pre
                                )
                                if (not _already_inherited
                                    and not _already_chosen
                                    and len(_idea_data_pre.get("ideas") or []) > 1):
                                    import asyncio as _asyncio_root
                                    from ari.orchestrator.root_idea_selector import (
                                        append_root_selection_log,
                                        apply_root_choice,
                                        select_root_idea,
                                    )
                                    _choice = _asyncio_root.run(
                                        select_root_idea(_idea_data_pre)
                                    )
                                    _swapped = False
                                    if _choice.chosen_index != 0:
                                        _swapped = apply_root_choice(
                                            str(_idea_json_path),
                                            _choice.chosen_index,
                                            rationale=_choice.rationale,
                                        )
                                        _LINEAGE_LOG.info(
                                            "root_idea_selection: promoted ideas[%d] (rationale=%s)",
                                            _choice.chosen_index,
                                            _choice.rationale[:140],
                                        )
                                    try:
                                        append_root_selection_log(
                                            checkpoint_dir,
                                            pool_size=len(_idea_data_pre.get("ideas") or []),
                                            choice=_choice,
                                            swapped=_swapped,
                                        )
                                    except Exception as _re_log:
                                        _LINEAGE_LOG.warning(
                                            "root selection log append failed: %s",
                                            _re_log,
                                        )
                            except Exception as _re:
                                _LINEAGE_LOG.warning(
                                    "root_idea_selection failed: %s", _re,
                                )

                        _idea_data = _json_idea.loads(_idea_json_path.read_text())
                        _idea_ctx_for_expand = _build_idea_ctx_for_expand(_idea_data)
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
            #
            # Phase 7 — *output* artifacts (results.csv, slurm-*.out, run.log,
            # job stdout/stderr) are deliberately EXCLUDED from inheritance.
            # Without this exclusion, a child's ReAct agent finds its parent's
            # results already on disk and silently re-reads them as if its own
            # experiment had completed — producing 10 BFTS nodes that all
            # report the same numbers from a single SLURM run. Code, scripts,
            # and configs still inherit so the agent has the parent's state to
            # build on; only result files must be re-generated by the child's
            # own experiment.
            import fnmatch as _fnmatch
            import shutil as _sh_parent
            _OUTPUT_BLACKLIST = (
                "results.csv", "results_*.csv", "*_results.csv",
                "result.csv", "metrics.csv",
                "run.log", "run_*.log", "*.run.log",
                "slurm-*.out", "slurm-*.err",
                "stdout.txt", "stderr.txt", "out.txt", "err.txt",
                "*.metrics.json", "metrics.json",
                "node_report.json",
            )
            def _is_output_artifact(rel_path: str, name: str) -> bool:
                for pat in _OUTPUT_BLACKLIST:
                    if _fnmatch.fnmatch(name, pat) or _fnmatch.fnmatch(rel_path, pat):
                        return True
                return False
            for _n in batch:
                _pid = getattr(_n, "parent_id", None)
                if not _pid:
                    continue
                _parent_wd = _pm.node_work_dir(run_id, _pid)
                if not _parent_wd.is_dir():
                    continue
                _dst_root = Path(_n.work_dir)
                _skipped_outputs = 0
                try:
                    for _src in _parent_wd.rglob("*"):
                        if _src.is_dir():
                            continue
                        if PathManager.is_meta_file(_src.name):
                            continue
                        _rel = _src.relative_to(_parent_wd)
                        if _is_output_artifact(str(_rel), _src.name):
                            _skipped_outputs += 1
                            continue
                        _dst = _dst_root / _rel
                        if _dst.exists():
                            continue
                        _dst.parent.mkdir(parents=True, exist_ok=True)
                        _sh_parent.copy2(str(_src), str(_dst))
                    logging.getLogger(__name__).info(
                        "Inherited parent work_dir %s -> %s (skipped %d output artifact(s))",
                        _parent_wd, _dst_root, _skipped_outputs,
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

                # Write per-node node_report.json now that the node is fully
                # marked. This is best-effort: any failure is logged and
                # ignored so the orchestration loop continues.
                try:
                    from ari.orchestrator.node_report import (
                        compute_files_changed, write_node_report,
                    )
                    _parent_wd_for_report = (
                        _pm.node_work_dir(run_id, result.parent_id)
                        if getattr(result, "parent_id", None) else None
                    )
                    if _parent_wd_for_report is not None and not _parent_wd_for_report.is_dir():
                        _parent_wd_for_report = None

                    # Phase 7-2: sterile-node detection.
                    # When a child node finishes its ReAct loop without
                    # writing or modifying ANY file relative to its parent,
                    # the agent never actually ran a new experiment — it
                    # only re-read the inherited code/configs and reported
                    # numbers (often parent-style ones it derived from
                    # inherited artifacts that escaped the output blacklist).
                    # Without this gate, BFTS happily expands sterile chains
                    # for the rest of its budget because the LLM judge gives
                    # them small but non-zero scores.
                    if _parent_wd_for_report is not None and getattr(result, "parent_id", None):
                        try:
                            _result_wd = Path(
                                getattr(result, "work_dir", "")
                                or _pm.node_work_dir(run_id, result.id)
                            )
                            _fc = compute_files_changed(
                                _parent_wd_for_report, _result_wd,
                            )
                            _added = len(_fc.get("added") or [])
                            _modified = len(_fc.get("modified") or [])
                            _deleted = len(_fc.get("deleted") or [])
                            if _added + _modified + _deleted == 0:
                                # Sterile — clamp score and mark for BFTS to skip.
                                if isinstance(result.metrics, dict):
                                    result.metrics["_sterile"] = True
                                    result.metrics["_scientific_score"] = 0.0
                                result.has_real_data = False
                                logging.getLogger(__name__).warning(
                                    "Node %s flagged STERILE (label=%s, parent=%s): "
                                    "no files added/modified/deleted vs parent. "
                                    "Score clamped to 0.0 and has_real_data=False so "
                                    "BFTS does not expand from this no-op chain.",
                                    result.id, result.label,
                                    (result.parent_id or "")[-8:],
                                )
                        except Exception as _ster_e:
                            logging.getLogger(__name__).warning(
                                "sterile check failed for %s: %s",
                                result.id, _ster_e,
                            )

                    write_node_report(
                        node=result,
                        work_dir=Path(getattr(result, "work_dir", "") or _pm.node_work_dir(run_id, result.id)),
                        parent_work_dir=_parent_wd_for_report,
                        eval_result={
                            "scientific_score": result.metrics.get("_scientific_score"),
                            "axis_scores": result.metrics.get("_axis_scores", {}),
                            "reason": result.eval_summary or "",
                            "has_real_data": bool(result.has_real_data),
                        } if isinstance(result.metrics, dict) else None,
                    )
                except Exception as _nre:
                    logging.getLogger(__name__).warning(
                        "node_report: failed to write for %s: %s", result.id, _nre
                    )

                # Save checkpoint after each node completes (not just after batch)
                # This ensures progress is preserved if SIGTERM interrupts mid-batch
                _save_tree_incremental(
                    checkpoint_dir, run_id, experiment_data["file"], all_nodes,
                    force=True,
                )

                # lineage decisions: lineage decision hook (after per-node save).
                if (_lineage_mode in ("stagnation_rule", "every_node")
                    and not _lineage_stop_requested
                    and _lineage_actions_taken < _lineage_rate_limit
                    and len(all_nodes) >= _lineage_min_nodes
                    and _idea_json_path.exists()):
                    try:
                        import asyncio as _asyncio_l
                        from ari.orchestrator.lineage_decision import (
                            append_decision_log,
                            build_lineage_state,
                            decide_lineage_action,
                            detect_stagnation,
                        )
                        # Pull current composite scores for stagnation check.
                        _composites = []
                        for _n in all_nodes:
                            _s = (_n.metrics if hasattr(_n, "metrics") else {}).get(
                                "_scientific_score"
                            )
                            if isinstance(_s, (int, float)):
                                _composites.append(float(_s))
                        _should_call = (
                            _lineage_mode == "every_node"
                            or detect_stagnation(
                                _composites,
                                window=_lineage_window,
                                threshold=_lineage_threshold,
                            )
                        )
                        if _should_call:
                            _idea_data_l = json.loads(_idea_json_path.read_text())
                            _budget_left = (
                                cfg.bfts.max_total_nodes - len(all_nodes)
                            )
                            # lineage decisions: surface recursion budget so the
                            # judge LLM does not propose switches that
                            # would be rejected by the launch API.
                            _rec_depth = int(
                                os.environ.get("ARI_RECURSION_DEPTH", "0") or 0
                            )
                            _max_rec = int(
                                os.environ.get("ARI_MAX_RECURSION_DEPTH", "3") or 3
                            )
                            _state = build_lineage_state(
                                all_nodes=list(all_nodes),
                                idea_data=_idea_data_l,
                                budget_remaining=_budget_left,
                                recursion_depth=_rec_depth,
                                max_recursion_depth=_max_rec,
                            )
                            _decision = _asyncio_l.run(
                                decide_lineage_action(_state)
                            )
                            _LINEAGE_LOG.info(
                                "lineage decision (%s): action=%s rationale=%s",
                                _lineage_mode, _decision.action,
                                _decision.rationale[:120],
                            )
                            _stop = _execute_lineage_decision(
                                _decision,
                                parent_run_id=_lineage_run_id,
                                parent_ckpt=Path(checkpoint_dir),
                                experiment_data=experiment_data,
                            )
                            # Persist every fired decision (continue
                            # included) so the analysis log captures both
                            # actions taken and explicit "no-action" calls.
                            try:
                                append_decision_log(
                                    checkpoint_dir,
                                    state=_state,
                                    decision=_decision,
                                    trigger=_lineage_mode,
                                    executed=(_decision.action != "continue"),
                                    extra={
                                        "stop_requested": bool(_stop),
                                        "actions_taken_so_far": _lineage_actions_taken,
                                        "rate_limit": _lineage_rate_limit,
                                    },
                                )
                            except Exception as _le_persist:
                                _LINEAGE_LOG.warning(
                                    "decision log append failed: %s", _le_persist,
                                )
                            if _decision.action != "continue":
                                _lineage_actions_taken += 1
                            if _stop:
                                _lineage_stop_requested = True
                    except Exception as _le:
                        _LINEAGE_LOG.warning("lineage decision hook failed: %s", _le)

            if _lineage_stop_requested:
                _LINEAGE_LOG.info("lineage decision: stop requested — exiting BFTS loop")
                break

        _save_tree_incremental(
            checkpoint_dir, run_id, experiment_data["file"], all_nodes,
            force=True,
        )

        if _lineage_stop_requested:
            break

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
    _wf_src = config if config and config.exists() else (Path(__file__).parent.parent / "config" / "workflow.yaml")
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
        _pkg_wf = Path(__file__).parent.parent / "config" / "workflow.yaml"
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
        _pkg_wf_r = Path(__file__).parent.parent / "config" / "workflow.yaml"
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


def _save_checkpoint(checkpoint_dir, run_id, experiment_file, nodes):
    """Build the (tree, nodes_tree, results) payload and write all three files.

    JSON file names + key order are fixed by the GUI / paper pipeline
    contract; the actual write is delegated to ``ari.checkpoint`` so
    only one place owns ``json.dumps(..., indent=2)`` (Phase 2 §6-1).
    """
    import hashlib as _hl_ck
    from ari.checkpoint import (
        save_tree_json as _save_tree,
        save_nodes_tree_json as _save_nodes_tree,
        save_results_json as _save_results,
    )
    # ── Trace: record experiment file hash in tree.json for post-mortem ──
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
    _save_tree(checkpoint_dir, tree)
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
    _save_nodes_tree(checkpoint_dir, nodes_tree)
    results = {
        "run_id": run_id,
        "nodes": {n.id: {"artifacts": n.artifacts, "metrics": n.metrics,
                          "has_real_data": n.has_real_data, "eval_summary": n.eval_summary,
                          "status": n.status.value, "error_log": n.error_log}
                  for n in nodes},
    }
    _save_results(checkpoint_dir, results)


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
