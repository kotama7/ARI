"""Workflow driver for the post-BFTS pipeline (subtask 012).

``WorkflowDriver`` owns what ``run_pipeline`` used to inline: the pre-flight
(cost-tracker init, ``evaluation_criteria.json`` derivation,
``nodes_tree.json`` write, verified-context wiring, paper-context assembly,
template-var registry, and the BFTS sanity gate) plus the index-based stage
cursor loop with its ``loop_back_to`` rewind.

Per-stage work is delegated to the objects in :mod:`ari.pipeline.stages`
(``make_stage`` → ``SubprocessMCPStage`` / ``ReActStage``). The driver keeps
the loop skeleton, the ``try``/``except`` boundary, and the loop-back cursor
manipulation because those own shared run state.

The extraction is **behaviour-preserving**: the body below is the exact
logic previously in ``ari/pipeline/orchestrator.py::run_pipeline``, reading
and writing the same ``tpl_vars`` / ``stage_outputs`` maps (now carried by a
:class:`~ari.pipeline.stage_context.StageContext`).
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from ari.pipeline.context_builder import (
    _extract_keywords_from_nodes,
    build_best_nodes_context,
)
from ari.pipeline.experiment_md import (
    _extract_plan_sections,
    _promote_plan_to_experiment_md,
    parse_metric_from_experiment_md,
)
from ari.pipeline.stage_context import StageContext
from ari.pipeline.stage_control import _format_vlm_feedback, _should_loop_back
from ari.pipeline.stages import make_stage
from ari.pipeline.yaml_loader import _resolve_templates

log = logging.getLogger(__name__)


class WorkflowDriver:
    """Drive one post-BFTS pipeline run to completion.

    Constructed with the same arguments ``run_pipeline`` received; ``run()``
    returns the identical ``stage_outputs`` dict (or the ``{"_aborted": ...}``
    sentinel when the BFTS sanity gate fires).
    """

    def __init__(
        self,
        stages: list[dict],
        all_nodes,
        experiment_data: dict,
        checkpoint_dir: Path,
        config_path: str,
    ):
        self.stages = stages
        self.all_nodes = all_nodes
        self.experiment_data = experiment_data
        self.checkpoint_dir = checkpoint_dir
        self.config_path = config_path

    def run(self) -> dict[str, Any]:
        # Local aliases keep the pre-flight body identical to the historical
        # ``run_pipeline`` implementation.
        stages = self.stages
        all_nodes = self.all_nodes
        experiment_data = self.experiment_data
        checkpoint_dir = self.checkpoint_dir
        config_path = self.config_path

        experiment_goal = experiment_data.get("goal", "")
        context, best_metrics = build_best_nodes_context(all_nodes, experiment_goal)

        # Propagate checkpoint_dir to subprocess env so cost_tracker can log there
        from ari.paths import PathManager as _PM_pipe_set
        _PM_pipe_set.set_checkpoint_dir_env(checkpoint_dir)

        # Mark paper pipeline start for GUI phase detection
        try:
            (checkpoint_dir / ".pipeline_started").touch()
        except Exception:
            pass

        # ── Initialize cost tracker ──────────────────────────────────────────────
        try:
            from ari import cost_tracker as _ct
            _ct.init(checkpoint_dir)
        except Exception as _cte:
            log.warning("Cost tracker init failed: %s", _cte)

        # Extract evaluation_criteria from nodes (set by generate_ideas in loop.py)
        # Written to checkpoint as evaluation_criteria.json for downstream use
        _eval_criteria_path = checkpoint_dir / "evaluation_criteria.json"
        if not _eval_criteria_path.exists():
            _ec = {"primary_metric": "", "higher_is_better": True, "metric_rationale": ""}
            # Strategy 1: check node memory_snapshot (populated if memory.add() succeeded)
            for _n in all_nodes:
                for _snap in (_n.memory_snapshot if hasattr(_n, "memory_snapshot") else []):
                    if isinstance(_snap, str) and "EVALUATION_CRITERIA:" in _snap:
                        import re as _re_ec
                        _pm = _re_ec.search(r"primary_metric=([\w_]+)", _snap)
                        _hib = _re_ec.search(r"higher_is_better=(\w+)", _snap)
                        if _pm:
                            _ec["primary_metric"] = _pm.group(1)
                        if _hib:
                            _ec["higher_is_better"] = _hib.group(1).lower() != "false"
                        break
                if _ec["primary_metric"]:
                    break
            # Strategy 2: fallback to idea.json (always available when generate_ideas ran)
            if not _ec["primary_metric"]:
                try:
                    _idea_ec_path = Path(checkpoint_dir) / "idea.json"
                    if _idea_ec_path.exists():
                        _idea_ec = json.loads(_idea_ec_path.read_text())
                        _ec["primary_metric"] = _idea_ec.get("primary_metric", "")
                        _ec["higher_is_better"] = _idea_ec.get("higher_is_better", True)
                        _ec["metric_rationale"] = _idea_ec.get("metric_rationale", "")
                except Exception:
                    pass
            # Strategy 3: parse experiment.md for a "Metrics:" line. Triggered when
            # the user pre-supplies an experiment description and the agent never
            # calls generate_ideas (so neither memory nor idea.json carry a metric).
            if not _ec["primary_metric"]:
                try:
                    _exp_md = Path(checkpoint_dir) / "experiment.md"
                    if _exp_md.exists():
                        _first = parse_metric_from_experiment_md(
                            _exp_md.read_text(errors="ignore")
                        )
                        if _first:
                            _ec["primary_metric"] = _first
                            _ec["metric_rationale"] = (
                                f"Parsed from experiment.md Metrics line ({_first})"
                            )
                except Exception:
                    pass
            try:
                _eval_criteria_path.write_text(json.dumps(_ec, indent=2))
                log.info("Saved evaluation_criteria.json: primary_metric=%s", _ec["primary_metric"])
            except Exception as _ece:
                log.warning("Failed to save evaluation_criteria.json: %s", _ece)

        # Save nodes_tree.json (referenced by downstream stages via {{ckpt}}/nodes_tree.json)
        # enrich each node with its memory entries so
        # downstream stages (transform, paper, EAR) become memory-aware without
        # issuing an MCP call themselves.
        nodes_json_path = str(checkpoint_dir / "nodes_tree.json")
        try:
            try:
                from ari.memory import get_backend as _get_mem_backend
                _mem_backend = _get_mem_backend(checkpoint_dir=checkpoint_dir)
            except Exception as _mbe:
                log.warning("pipeline: memory backend unavailable: %s", _mbe)
                _mem_backend = None

            _max_entries = int(os.environ.get("ARI_TRANSFORM_MEMORY_MAX_ENTRIES", "20") or 20)
            _max_chars = int(os.environ.get("ARI_TRANSFORM_MEMORY_MAX_CHARS", "2000") or 2000)

            def _cap_memory_entries(entries: list[dict]) -> list[dict]:
                entries = sorted(
                    entries or [], key=lambda e: e.get("ts", 0.0), reverse=True
                )[:_max_entries]
                capped = []
                for e in entries:
                    t = e.get("text", "") or ""
                    if len(t) > _max_chars:
                        t = t[:_max_chars] + "…[truncated]"
                    capped.append({
                        "text": t,
                        "metadata": e.get("metadata", {}) or {},
                        "ts": e.get("ts", 0.0),
                    })
                return capped

            nodes_data = []
            for _n in all_nodes:
                d = _n.to_dict()
                if _mem_backend is not None:
                    try:
                        res = _mem_backend.get_node_memory(_n.id)
                        entries = res.get("entries", []) or []
                    except Exception as _e_enrich:
                        log.warning(
                            "pipeline: memory enrichment failed for node %s: %s",
                            _n.id, _e_enrich,
                        )
                        entries = []
                    d["memory"] = _cap_memory_entries(entries)
                else:
                    d["memory"] = []
                nodes_data.append(d)
            Path(nodes_json_path).write_text(
                json.dumps({"experiment_goal": experiment_goal, "nodes": nodes_data},
                           ensure_ascii=False, indent=2)
            )
        except Exception as _e:
            log.error("CRITICAL: Failed to save nodes_tree.json: %s — paper pipeline stages may fail", _e)
            nodes_json_path = ""

        # Artifact-grounded verified context for write_paper (verifiable-memory layer).
        # Default ON (config.consolidation_enabled — same switch that populates the typed
        # store this reads). With it disabled the store is empty / not built, no
        # verified_context.json is written, and write_paper injects nothing. Best-effort;
        # never fails the pipeline. This writes an ARTIFACT (not a stage) so it does NOT
        # affect the stage/tool resolution order.
        from ari.config import consolidation_enabled as _cons_on
        if _cons_on():
            try:
                from ari.pipeline.verified_context import write_verified_context as _wvc
                _vc = _wvc(checkpoint_dir, all_nodes)
                log.info(
                    "pipeline: verified_context.json built (usable_for_claims=%d)",
                    len(_vc.get("usable_for_claims", []) or []),
                )
            except Exception as _vce:
                log.warning("pipeline: verified_context build failed: %s", _vce)

        # Convert topic slug (e.g. "My_Research_Topic_v2") -> search query ("My Research Topic v2")
        _raw_topic = experiment_data.get("topic", "")
        _search_topic = re.sub(r"[_-]+", " ", _raw_topic).strip()
        keywords = _extract_keywords_from_nodes(nodes_json_path, _search_topic)

        # Load paper_context from workflow.yaml (developer-defined paper description).
        # Falls back to {{context}} if not set. Keeps org names / cluster details
        # out of the paper while BFTS still sees the full experiment_goal.
        try:
            import yaml as _yaml
            from ari.config.finder import package_config_root
            _cfg_candidates = [
                Path(config_path) if config_path else None,
                Path(config_path).parent / "workflow.yaml" if config_path else None,
                # Bundled package config, located via the single accessor.
                package_config_root() / "workflow.yaml",
            ]
            _cfg_path = next((p for p in _cfg_candidates if p and p.exists()), None)
            _wf_cfg = _yaml.safe_load(_cfg_path.read_text()) if _cfg_path else {}
        except Exception:
            _wf_cfg = {}
        _static_ctx = (_wf_cfg.get("paper_context") or "").strip()
        # Stages the user / launch-config intentionally turned off (enabled: false).
        # The depends_on check below treats these as resolved so a disabled
        # upstream (e.g. EAR-off skipping generate_ear) does not cascade-skip
        # every downstream consumer.
        _disabled_stages: set[str] = {
            s.get("stage", "")
            for s in (_wf_cfg.get("pipeline") or [])
            if not s.get("enabled", True) and s.get("stage")
        }

        # Load LLM-extracted experiment context from science_data.json if available.
        # This contains hardware info, methodology, findings extracted by the transform stage.
        _exp_ctx_str = ""
        try:
            import json as _json
            _sd_path = Path(checkpoint_dir) / "science_data.json"
            if _sd_path.exists():
                _sd = _json.loads(_sd_path.read_text())
                _exp_ctx = _sd.get("experiment_context", {})
                if _exp_ctx and not _exp_ctx.get("error"):
                    # Prioritize key_results and implementation_details at the front
                    # so they survive truncation in downstream prompts.
                    _priority_parts = []
                    for _pk in ("_best_node_source_code", "key_results", "key_validated_results", "implementation_details", "reported_problem_instances"):
                        if _pk in _exp_ctx:
                            _priority_parts.append(f"{_pk}: {_json.dumps(_exp_ctx[_pk], ensure_ascii=False, indent=2)}")
                    _rest = {k: v for k, v in _exp_ctx.items()
                             if k not in ("key_results", "implementation_details", "reported_problem_instances")}
                    _exp_ctx_str = (
                        "Experiment context (LLM-extracted from raw artifacts):\n"
                        + "\n".join(_priority_parts)
                        + "\n" + _json.dumps(_rest, ensure_ascii=False, indent=2)
                    )
        except Exception as _ece:
            log.warning("Could not load experiment_context from science_data.json: %s", _ece)

        # Load idea.json: inject VirSci-generated research direction into paper context.
        # NOTE: this is the *directive* path — it reads only the current ckpt's idea.json
        # (no ancestor walk). Catalog-level ancestor access lives in ari/lineage.py and
        # is invoked explicitly by VirSci / sub-experiment launch, not here.
        _idea_ctx_str = ""
        try:
            _idea_path = Path(checkpoint_dir) / "idea.json"
            if _idea_path.exists():
                _idea_data = json.loads(_idea_path.read_text())
                _gap = _idea_data.get("gap_analysis", "")
                _ideas = _idea_data.get("ideas", [])
                if _ideas:
                    # Phase 1: auto-append plan/alternatives to checkpoint experiment.md.
                    # Mode is read from workflow.yaml (default index_only). Idempotent —
                    # safe to call repeatedly across pipeline retries.
                    try:
                        _plan_promote_mode = str(_wf_cfg.get("plan_promote", "index_only")).lower()
                        if _plan_promote_mode in ("full", "index_only"):
                            _did_promote = _promote_plan_to_experiment_md(
                                checkpoint_dir, _idea_data, mode=_plan_promote_mode
                            )
                            if _did_promote:
                                log.info(
                                    "plan-promote: appended VirSci block to %s/experiment.md (mode=%s)",
                                    checkpoint_dir, _plan_promote_mode,
                                )
                    except Exception as _epp:
                        log.warning("plan-promote failed (non-fatal): %s", _epp)

                    _best_idea = _ideas[0]
                    _parts_idea = []
                    if _gap:
                        _parts_idea.append(f"Research gap analysis: {_gap[:500]}")
                    _parts_idea.append(f"Research idea: {_best_idea.get('title', '')}")
                    _desc = _best_idea.get("description", "")
                    if _desc:
                        _parts_idea.append(f"Idea description: {_desc[:600]}")
                    # Phase 1: pass the full plan via §-tagged structure so paper-skill
                    # gets §4 (model calibration) and §6 (comparisons) — previously
                    # truncated to 400 chars which dropped both sections.
                    _plan = _best_idea.get("experiment_plan", "")
                    if _plan:
                        _plan_sections = _extract_plan_sections(_plan)
                        if _plan_sections:
                            _plan_lines = ["Experiment plan sections:"]
                            for _tag, _t, _body in _plan_sections:
                                _plan_lines.append(f"  {_tag} {_t}")
                                if _body:
                                    _plan_lines.append(f"    {_body[:600]}")
                            _parts_idea.append("\n".join(_plan_lines))
                        else:
                            _parts_idea.append(f"Experiment plan: {_plan[:1500]}")
                    _idea_ctx_str = "Research direction (AI-generated):\n" + "\n".join(_parts_idea)
                    log.info("Loaded idea.json for paper context: %s", _best_idea.get("title", "")[:80])
        except Exception as _ide:
            log.warning("Could not load idea.json for paper context: %s", _ide)

        # Merge all context: static (workflow.yaml) + idea + LLM-extracted + dynamic results
        parts = [p for p in [_static_ctx, _idea_ctx_str, _exp_ctx_str, context] if p.strip()]
        _paper_ctx = "\n\n".join(parts) if parts else context

        # Template variable registry — grows as stages complete
        import os as _os
        # Surface primary_metric / higher_is_better from evaluation_criteria.json
        # so downstream stages (transform_data, plot, paper) can be direction-
        # aware when reducing per-key metrics. Falls back to empty / True when
        # the criteria file is absent (legacy path).
        _eval_criteria_for_tpl: dict = {}
        try:
            _ec_path = Path(checkpoint_dir) / "evaluation_criteria.json"
            if _ec_path.exists():
                _eval_criteria_for_tpl = json.loads(_ec_path.read_text())
        except Exception:
            pass
        # Surface launch_config.json under the ``launch_config`` template key so
        # workflow.yaml stages can read user wizard choices (e.g.
        # ``launch_config.ors.iterative_agent``) via dot notation. Note that
        # _resolve_templates is a regex substitution, not Jinja2 — no filters
        # are supported, so the YAML must use plain ``{{ a.b.c }}`` references
        # (no ``| default(...)``); MCP tools should themselves apply defaults
        # when the templated string is empty or sentinel-like.
        _launch_cfg_for_tpl: dict = {}
        try:
            _lc_path = Path(checkpoint_dir) / "launch_config.json"
            if _lc_path.exists():
                _launch_cfg_for_tpl = json.loads(_lc_path.read_text())
        except Exception:
            pass

        tpl_vars: dict = {
            "ckpt":              str(checkpoint_dir),
            "checkpoint_dir":    str(checkpoint_dir),
            "context":           context,
            "experiment_summary": context,
            "paper_context":     _paper_ctx,
            "slurm_partition":   _wf_cfg.get("slurm_partition", ""),  # resolved at runtime via ARI_SLURM_PARTITION env
            "keywords":          keywords,
            "idea_context":      _idea_ctx_str,
            "primary_metric":    str(_eval_criteria_for_tpl.get("primary_metric", "")),
            "higher_is_better":  str(bool(_eval_criteria_for_tpl.get("higher_is_better", True))),
            "stages":            {},
            # Phase 3C — ``__file__`` is now ``ari/pipeline/driver.py``;
            # one extra parent hop reaches the repo root (where the
            # ``ari-skill-*`` directories live alongside ``ari-core``).
            "ari_root":          _os.environ.get("ARI_ROOT", str(Path(__file__).parents[3])),
            # Reproducibility check reads only the paper — no source_file injection.
            # Providing original source would be "repeat experiment", not "reproduce from paper".
            "experiment_source_file": _os.environ.get("ARI_SOURCE_FILE", ""),
            "author_name":       "Autonomous Research Infrastructure",  # default; overridden by workflow.yaml
            "launch_config":     _launch_cfg_for_tpl,
            # Expose all top-level string/int config values for template substitution
            **{k: str(v) for k, v in _wf_cfg.items() if isinstance(v, (str, int, float)) and k not in ("paper_context",)},
            # Expose nested dicts (e.g. resources, bfts) as nested keys for dot-notation access
            **{section: sec_val
               for section, sec_val in _wf_cfg.items()
               if isinstance(sec_val, dict) and section not in ("pipeline", "skills", "stages")},
        }

        stage_outputs: dict[str, Any] = {}

        # ── BFTS sanity gate ───────────────────────────────────────────────────
        # If no node produced real (numeric) experimental data, the downstream
        # paper / review stages will happily compose a "we report no data"
        # meta-paper that has nothing to do with the user's actual research goal
        # (observed in run 20260521155637_, where every Slurm job died with
        # ENOEXEC and the pipeline still generated a 7-page failure-analysis
        # paper). Abort the post-BFTS pipeline in that case and surface the
        # failure to the user. Override with ARI_FORCE_PAPER=1 when the operator
        # explicitly wants a paper anyway.
        _has_real_data = any(
            bool(getattr(_n, "has_real_data", False)) and getattr(_n, "metrics", None)
            for _n in all_nodes
        )
        # Fire only when BFTS actually attempted experiments — i.e. at least one
        # node carries artifacts or metrics. Empty / bare-Node inputs come from
        # paper-resume entry points or unit tests exercising stage dispatch and
        # should not trigger the abort.
        _bfts_attempted = any(
            getattr(_n, "artifacts", None) or getattr(_n, "metrics", None)
            for _n in all_nodes
        )
        if _bfts_attempted and not _has_real_data and not _os.environ.get("ARI_FORCE_PAPER", "").strip():
            _abort_msg = (
                "BFTS produced no real experimental data — every node either "
                "failed to execute or returned has_real_data=False. Skipping "
                "paper / review stages to avoid generating an unrelated "
                "meta-paper from empty inputs. Set ARI_FORCE_PAPER=1 to override."
            )
            log.error("[Paper Pipeline] %s", _abort_msg)
            print(f"[Paper Pipeline] ABORTED: {_abort_msg}", flush=True)
            try:
                (checkpoint_dir / "bfts_no_real_data.json").write_text(
                    json.dumps({
                        "skipped": True,
                        "reason": "no_real_data",
                        "message": _abort_msg,
                        "node_count": len(all_nodes),
                    }, ensure_ascii=False, indent=2)
                )
            except Exception:
                pass
            return {"_aborted": {"reason": "no_real_data", "message": _abort_msg}}

        # State value object replacing the manual tpl_vars / stage_outputs threading.
        ctx = StageContext(
            checkpoint_dir=checkpoint_dir,
            config_path=config_path,
            wf_cfg=_wf_cfg,
            disabled_stages=_disabled_stages,
            best_metrics=best_metrics,
            tpl_vars=tpl_vars,
            stage_outputs=stage_outputs,
        )

        # Index-based iteration so loop_back_to can rewind the cursor. A
        # per-source-stage counter caps total iterations so a misbehaving VLM
        # reviewer cannot pin the pipeline in an infinite regenerate loop.
        _loop_iterations: dict[str, int] = {}
        # Initialise the feedback slot so {{vlm_feedback}} resolves to "" on
        # the first pass (before any loop has injected real feedback).
        ctx.tpl_vars.setdefault("vlm_feedback", "")

        _stage_idx = 0
        while _stage_idx < len(stages):
            stage_cfg = stages[_stage_idx]
            stage = make_stage(stage_cfg, ctx.wf_cfg)
            stage_name = stage.stage_name
            desc = stage.desc

            log.info("=== Stage [%s]: %s ===", stage_name, desc)
            print(f"[Paper Pipeline] Stage [{stage_name}]: {desc} ...", flush=True)

            # ── skip checks (disabled_tools + depends_on + skip_if_exists) ──
            if stage.should_skip(ctx):
                _stage_idx += 1
                continue

            # ── resolve inputs (+ fallback-arg injection) ──────────────────
            args = stage.resolve_inputs(ctx)

            try:
                # ── dispatch (subprocess MCP call, or ReAct loop) ──────────
                result = stage.run(ctx, args)
                ctx.stage_outputs[stage_name] = result
                # ── save outputs (type-sniff writer + figures manifest) ────
                stage.persist_outputs(ctx, result)

                # Stage completed successfully
                print(f"[Paper Pipeline] Stage [{stage_name}]: DONE", flush=True)

                # ── loop_back_to runtime ─────────────────────────────────────
                # If this stage declares a `loop_back_to` target and its result
                # meets the `loop_threshold` / `loop_when_result_key` condition,
                # rewind the stage cursor to the target and re-run the range,
                # injecting any review feedback into tpl_vars so the upstream
                # stage can consume it (e.g. {{vlm_feedback}} in plot-skill).
                _loop_target = stage_cfg.get("loop_back_to")
                if _loop_target and _should_loop_back(stage_cfg, result):
                    _count = _loop_iterations.get(stage_name, 0)
                    try:
                        _max_iter = int(stage_cfg.get("loop_max_iterations", 2))
                    except (TypeError, ValueError):
                        _max_iter = 2
                    if _count >= _max_iter:
                        log.info(
                            "[loop_back] %s: loop_max_iterations (%d) reached; proceeding",
                            stage_name, _max_iter,
                        )
                        print(
                            f"[Paper Pipeline] Stage [{stage_name}]: loop max "
                            f"({_max_iter}) reached, proceeding",
                            flush=True,
                        )
                    else:
                        _target_idx = next(
                            (i for i, s in enumerate(stages)
                             if s.get("stage") == _loop_target and i < _stage_idx),
                            None,
                        )
                        if _target_idx is None:
                            log.warning(
                                "[loop_back] %s: target '%s' not found earlier in "
                                "pipeline; ignoring loop directive",
                                stage_name, _loop_target,
                            )
                        else:
                            _loop_iterations[stage_name] = _count + 1
                            # Surface review feedback to downstream template vars
                            ctx.tpl_vars["vlm_feedback"] = _format_vlm_feedback(result)
                            # Reset state for stages [target_idx .. _stage_idx]
                            # so they actually re-run (don't hit skip_if_exists
                            # on their own outputs).
                            for _reset_idx in range(_target_idx, _stage_idx + 1):
                                _reset_name = stages[_reset_idx].get("stage", "")
                                ctx.tpl_vars["stages"].pop(_reset_name, None)
                                ctx.stage_outputs.pop(_reset_name, None)
                                _reset_skip = stages[_reset_idx].get("skip_if_exists", "")
                                if _reset_skip:
                                    try:
                                        _reset_path = Path(
                                            _resolve_templates(_reset_skip, ctx.tpl_vars)
                                        )
                                        _reset_path.unlink(missing_ok=True)
                                    except Exception as _reset_err:
                                        log.debug(
                                            "[loop_back] could not clear skip marker "
                                            "for %s: %s",
                                            _reset_name, _reset_err,
                                        )
                            log.info(
                                "[loop_back] %s → %s (iter %d/%d); feedback injected",
                                stage_name, _loop_target, _count + 1, _max_iter,
                            )
                            print(
                                f"[Paper Pipeline] Stage [{stage_name}]: LOOPING "
                                f"BACK to {_loop_target} (iter {_count + 1}/"
                                f"{_max_iter})",
                                flush=True,
                            )
                            _stage_idx = _target_idx
                            continue  # skip the _stage_idx += 1 below

            except Exception:
                import traceback as _tb
                _exc = _tb.format_exc()
                log.warning("Stage [%s] failed:\n%s", stage_name, _exc)
                print(f"[Paper Pipeline] Stage [{stage_name}]: FAILED\n{_exc[:300]}", flush=True)
                ctx.stage_outputs[stage_name] = {"error": "stage failed"}
                ctx.tpl_vars["stages"][stage_name] = {"output": "", "outputs": {}}

            _stage_idx += 1

        return ctx.stage_outputs
