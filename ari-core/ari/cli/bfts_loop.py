"""BFTS run-loop driver + checkpoint persistence (Phase 3A — PR-3A bfts_loop).

Hosts the heavyweight BFTS plumbing extracted from ``ari/cli/__init__.py``:

- :func:`_run_loop` — orchestrates the parallel ReAct execution of the
  pending node list, including sibling-node spawning, lineage-decision
  hooks, idea.json reload, and tree.json mid-run flushes.
- :func:`_save_tree_incremental` — throttled, thread-safe wrapper that
  delegates to ``ari.checkpoint.save_tree_incremental``.
- :func:`_save_checkpoint` — write the final
  ``{tree,nodes_tree,results}.json`` triple at the end of a run.

The Typer commands ``run`` / ``resume`` import these names from
``ari.cli.bfts_loop`` (or via the package re-export in ``__init__``).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console

from ari.cli.lineage import (
    _LINEAGE_LOG,
    _build_idea_ctx_for_expand,
    _execute_lineage_decision,
    _load_lineage_decision_config,
    _mark_parent_terminated,
)
from ari.paths import PathManager


log = logging.getLogger(__name__)
console = Console()




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
    # lineage decisions: runner-up idea indexes already pivoted to, so the
    # deterministic stagnation pivot moves to a FRESH alternative each time
    # rather than re-trying the same one.
    _lineage_used_indexes: set = set()
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
                # P3: append run-level claim coverage to the selection goal so the
                # (already cross-branch) scheduler can prefer a node whose next
                # experiment evidences a STILL-UNCOVERED claim — without it a real
                # 10-node run produced ten variations of the headline experiment.
                # Node reasoning context is untouched (scheduler-only signal).
                _goal_for_select = experiment_data["goal"]
                try:
                    from ari.agent.metric_contract import build_expand_coverage_hint
                    _goal_for_select = _goal_for_select + build_expand_coverage_hint(
                        str(checkpoint_dir))
                except Exception:
                    pass
                best = bfts.select_best_to_expand(_eligible, _goal_for_select, agent.memory)
            except Exception as exc:
                logging.getLogger(__name__).warning("select_best_to_expand failed: %s", exc)
                best = _eligible[0]
            if bfts.should_prune(best, current_total=len(all_nodes)):
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
                                Path(__file__).resolve().parent.parent.parent / "config" / "workflow.yaml"
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
                    budget_remaining=cfg.bfts.max_total_nodes - len(all_nodes),
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
                # I-7: record run AFTER completion so the diversity bonus
                # reflects what actually ran (success or failure), not what we
                # intended to run.
                try:
                    bfts.record_run(result)
                except Exception:
                    pass
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

                # B-6 Rule A: when the child beat its parent's scientific
                # score, retire the parent — there is nothing more to gain
                # from re-expanding a node a child already surpassed.
                _parent_id_for_retire = getattr(result, "parent_id", None)
                if _parent_id_for_retire and isinstance(result.metrics, dict):
                    _child_score = float(result.metrics.get("_scientific_score") or 0.0)
                    for _fn in list(frontier):
                        if _fn.id != _parent_id_for_retire:
                            continue
                        _parent_score = float(
                            (_fn.metrics or {}).get("_scientific_score") or 0.0
                        )
                        if _child_score > _parent_score:
                            frontier.remove(_fn)
                            console.print(
                                f"    Retired parent {_fn.id[-8:]} from frontier "
                                f"(child {result.id[-8:]} beat it)"
                            )
                        break

                # B-6 Rule B: retire frontier nodes that have already been
                # expanded ``max_expansions_per_node`` times — spread the
                # search rather than mining the same parent indefinitely.
                _max_exp = int(getattr(cfg.bfts, "max_expansions_per_node", 4) or 4)
                _ec_fn = getattr(bfts, "expansion_count", None)
                if callable(_ec_fn):
                    for _fn in list(frontier):
                        try:
                            _cnt = int(_ec_fn(_fn.id))
                        except (TypeError, ValueError):
                            continue
                        if _cnt >= _max_exp:
                            frontier.remove(_fn)
                            console.print(
                                f"    Retired {_fn.id[-8:]} from frontier "
                                f"(reached max_expansions_per_node={_max_exp})"
                            )

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

                # Phase 3: populate typed research-memory from the node_report
                # just written. Default ON (config.consolidation_enabled); the
                # typed store feeds the verifiable / paper-context layer
                # (search_research_memory, get_verified_context), NOT Phase 0
                # working-context injection, which keeps using result_summary.
                # Best-effort: never breaks the loop. CoW via cow_node_id=result.id.
                from ari.config import consolidation_enabled as _cons_on
                if _cons_on():
                    try:
                        _cwd = Path(
                            getattr(result, "work_dir", "")
                            or _pm.node_work_dir(run_id, result.id)
                        )
                        _nr_path = _cwd / "node_report.json"
                        _nr = json.loads(_nr_path.read_text()) if _nr_path.exists() else None
                        if _nr and getattr(agent, "mcp", None) is not None:
                            agent.mcp.call_tool(
                                "consolidate_node_memory",
                                {
                                    "node_id": result.id,
                                    "node_report": _nr,
                                    "work_dir": str(_cwd),
                                    "run_id": run_id,
                                },
                                cow_node_id=result.id,
                            )
                    except Exception as _ce:
                        logging.getLogger(__name__).warning(
                            "consolidate_node_memory failed for %s: %s", result.id, _ce
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
                            deterministic_stagnation_pivot,
                        )
                        # Pull current composite scores for stagnation check.
                        _composites = []
                        for _n in all_nodes:
                            _s = (_n.metrics if hasattr(_n, "metrics") else {}).get(
                                "_scientific_score"
                            )
                            if isinstance(_s, (int, float)):
                                _composites.append(float(_s))
                        _stagnated = detect_stagnation(
                            _composites,
                            window=_lineage_window,
                            threshold=_lineage_threshold,
                        )
                        _should_call = (_lineage_mode == "every_node" or _stagnated)
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
                            # lineage decisions: on CONFIRMED stagnation, pivot
                            # deterministically to the strongest unused runner-up
                            # idea (agreed policy: use the 2nd idea to break a
                            # plateau) — the judge's "prefer continue" bias tends
                            # to let runner-ups die. Defer continue-vs-terminate to
                            # the LLM judge only when no eligible alternative remains.
                            _decision = None
                            if _stagnated:
                                _decision = deterministic_stagnation_pivot(
                                    _state, _lineage_used_indexes
                                )
                            if _decision is None:
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
                            # Remember the runner-up we pivoted to, so the next
                            # stagnation pivot moves to a fresh alternative.
                            if (_decision.action in ("switch_to_idea", "fanout")
                                    and isinstance(_decision.target_idea_index, int)):
                                _lineage_used_indexes.add(_decision.target_idea_index)
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



# L-4: cache experiment-file sha256 keyed by (path, mtime_ns) so the
# per-node checkpoint flush does not re-hash the same .md file on every
# call. Keyed by path string so different experiment files coexist.
_EXP_FILE_HASH_CACHE: dict[str, tuple[int, str, int]] = {}


def _hash_experiment_file(path: Path) -> tuple[str, int]:
    """Return ``(sha256_short, byte_len)`` for ``path``, memoised by mtime_ns."""
    import hashlib as _hl_ck
    if not path.exists():
        return "", 0
    try:
        mtime_ns = path.stat().st_mtime_ns
    except OSError:
        return "", 0
    key = str(path)
    cached = _EXP_FILE_HASH_CACHE.get(key)
    if cached and cached[0] == mtime_ns:
        return cached[1], cached[2]
    data = path.read_bytes()
    sha = _hl_ck.sha256(data).hexdigest()[:16]
    n = len(data)
    _EXP_FILE_HASH_CACHE[key] = (mtime_ns, sha, n)
    return sha, n


def _save_checkpoint(checkpoint_dir, run_id, experiment_file, nodes):
    """Build the (tree, nodes_tree, results) payload and write all three files.

    JSON file names + key order are fixed by the GUI / paper pipeline
    contract; the actual write is delegated to ``ari.checkpoint`` so
    only one place owns ``json.dumps(..., indent=2)`` (Phase 2 §6-1).
    """
    from ari.checkpoint import (
        save_tree_json as _save_tree,
        save_nodes_tree_json as _save_nodes_tree,
        save_results_json as _save_results,
    )
    # ── Trace: record experiment file hash in tree.json for post-mortem ──
    _exp_path = Path(experiment_file)
    _exp_sha, _exp_len = _hash_experiment_file(_exp_path)
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

