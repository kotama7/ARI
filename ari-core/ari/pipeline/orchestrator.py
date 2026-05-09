"""Top-level pipeline orchestrator (Phase 3C).

Hosts the two top-level entry points (``build_scientific_data`` and
``run_pipeline``) that ``cli.py`` / external callers invoke.  All
helper clusters live in sibling modules under ``ari.pipeline``;
``__init__.py`` re-exports the public surface so existing
``from ari.pipeline import run_pipeline`` paths keep working.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

# These names are read by `run_pipeline` from the package surface so
# pipeline-internal cross-references continue to resolve at the same
# module path.
from ari.pipeline.context_builder import (
    _extract_keywords_from_nodes,
    build_best_nodes_context,
)
from ari.pipeline.experiment_md import (
    _AUTO_APPEND_BEGIN,
    _AUTO_APPEND_END,
    _build_auto_append_block,
    _extract_plan_sections,
    _promote_plan_to_experiment_md,
    parse_metric_from_experiment_md,
)
from ari.pipeline.stage_control import _format_vlm_feedback, _should_loop_back
from ari.pipeline.stage_runner import _call_with_retry


def _run_react_stage(*args, **kwargs):
    """Lazy delegator so ``monkeypatch.setattr(ari.pipeline,
    '_run_react_stage', ...)`` is honoured by ``run_pipeline`` even
    though Phase 3C moved the implementation into a sibling module.
    """
    import ari.pipeline as _p
    return _p._run_react_stage(*args, **kwargs)


def _run_stage_subprocess(*args, **kwargs):
    """Same lazy-delegator pattern as :func:`_run_react_stage` so test
    monkeypatches against the package surface keep working.
    """
    import ari.pipeline as _p
    return _p._run_stage_subprocess(*args, **kwargs)
from ari.pipeline.yaml_loader import (
    _resolve_templates,
    load_disabled_stage_names,
    load_pipeline,
    load_workflow,
)


log = logging.getLogger(__name__)


def build_scientific_data(nodes_json_path: str) -> dict:
    """Convert BFTS nodes_tree.json to science-facing data only.

    Strips all BFTS-internal fields (label, depth, node_id, status, parent_id).
    Returns: configurations (param dicts) + metric values.
    This is the ONLY format passed to plot-skill / paper-skill.
    """
    import re as _re_sci
    try:
        data = json.loads(Path(nodes_json_path).read_text())
        nodes = data if isinstance(data, list) else data.get("nodes", [])
    except Exception:
        return {"configurations": [], "metric_name": "metric"}

    science_nodes = []
    for n in nodes:
        if not (n.get("has_real_data") and n.get("metrics")):
            continue
        # No domain-specific parameter extraction here.
        # The transform-skill (LLM-powered) handles parameter extraction from artifacts.
        science_nodes.append({
            "configuration": {"index": len(science_nodes) + 1},
            "metrics": n.get("metrics", {}),
        })

    def _best(node):
        m = node["metrics"]
        # Numeric metric tiebreaker; primary sort is BFTS depth (deeper = LLM preferred more)
        return max((v for v in m.values() if isinstance(v, (int, float))), default=0) if m else 0

    # Load primary_metric / higher_is_better from evaluation_criteria.json
    # (set autonomously by generate_ideas; no user input required)
    _primary = ""
    _higher_is_better = True
    try:
        _ec_path = Path(nodes_json_path).parent / "evaluation_criteria.json"
        if _ec_path.exists():
            _ec = json.loads(_ec_path.read_text())
            _primary = _ec.get("primary_metric", "")
            _higher_is_better = _ec.get("higher_is_better", True)
            log.info("Loaded evaluation criteria: primary_metric=%s higher_is_better=%s", _primary, _higher_is_better)
    except Exception:
        pass

    def _primary_val(node: dict) -> float:
        m = node.get("metrics", {})
        if _primary and _primary in m and isinstance(m[_primary], (int, float)):
            v = float(m[_primary])
            return v if _higher_is_better else -v  # negate so sort(reverse=True) works for both
        # Fallback: BFTS depth (deeper = more explored = LLM preferred)
        return float(node.get("depth", 0)) * 1e-6 + _best(m)

    # Sort by primary_metric (or depth as proxy for LLM preference)
    science_nodes.sort(key=lambda n: (n.get("has_real_data", False), _primary_val(n)), reverse=True)
    metric_name = list(science_nodes[0]["metrics"].keys())[0] if science_nodes else "metric"

    return {
        "configurations": science_nodes,
        "metric_name": metric_name,
        "best_value": _best(science_nodes[0]) if science_nodes else 0,
        "count": len(science_nodes),
    }

def run_pipeline(
    stages: list[dict],
    all_nodes,
    experiment_data: dict,
    checkpoint_dir: Path,
    config_path: str,
) -> dict[str, Any]:
    """Execute pipeline stages driven by YAML stage definitions.

    Template variables resolved for each stage:
      {{ckpt}}     -> checkpoint_dir
      {{context}}  -> experiment summary text
      {{keywords}} -> auto-extracted search keywords
      {{stages.<name>.output}} -> output file path of a previous stage
    """
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
            from ari_skill_memory.backends import get_backend as _get_mem_backend
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

    # Convert topic slug (e.g. "My_Research_Topic_v2") -> search query ("My Research Topic v2")
    _raw_topic = experiment_data.get("topic", "")
    _search_topic = re.sub(r"[_-]+", " ", _raw_topic).strip()
    keywords = _extract_keywords_from_nodes(nodes_json_path, _search_topic)

    # Load paper_context from workflow.yaml (developer-defined paper description).
    # Falls back to {{context}} if not set. Keeps org names / cluster details
    # out of the paper while BFTS still sees the full experiment_goal.
    try:
        import yaml as _yaml
        _cfg_candidates = [
            Path(config_path) if config_path else None,
            Path(config_path).parent / "workflow.yaml" if config_path else None,
            # Phase 3C — orchestrator.py is now under ``ari/pipeline/``
            # so the bundled ``config/`` lives 3 parents up.
            Path(__file__).resolve().parent.parent.parent / "config" / "workflow.yaml",
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
        # Phase 3C — ``__file__`` is now ``ari/pipeline/orchestrator.py``;
        # one extra parent hop reaches the repo root (where the
        # ``ari-skill-*`` directories live alongside ``ari-core``).
        "ari_root":          _os.environ.get("ARI_ROOT", str(Path(__file__).parents[3])),
        # Reproducibility check reads only the paper — no source_file injection.
        # Providing original source would be "repeat experiment", not "reproduce from paper".
        "experiment_source_file": _os.environ.get("ARI_SOURCE_FILE", ""),
        "author_name":       "Artificial Research Intelligence",  # default; overridden by workflow.yaml
        "launch_config":     _launch_cfg_for_tpl,
        # Expose all top-level string/int config values for template substitution
        **{k: str(v) for k, v in _wf_cfg.items() if isinstance(v, (str, int, float)) and k not in ("paper_context",)},
        # Expose nested dicts (e.g. resources, bfts) as nested keys for dot-notation access
        **{section: sec_val
           for section, sec_val in _wf_cfg.items()
           if isinstance(sec_val, dict) and section not in ("pipeline", "skills", "stages")},
    }

    stage_outputs: dict[str, Any] = {}

    # Index-based iteration so loop_back_to can rewind the cursor. A
    # per-source-stage counter caps total iterations so a misbehaving VLM
    # reviewer cannot pin the pipeline in an infinite regenerate loop.
    _loop_iterations: dict[str, int] = {}
    # Initialise the feedback slot so {{vlm_feedback}} resolves to "" on
    # the first pass (before any loop has injected real feedback).
    tpl_vars.setdefault("vlm_feedback", "")

    _stage_idx = 0
    while _stage_idx < len(stages):
        stage_cfg = stages[_stage_idx]
        stage_name = stage_cfg.get("stage", "unknown")
        skill_key  = stage_cfg.get("skill", "")
        skill = skill_key if ("skill" in skill_key) else (skill_key + "-skill" if skill_key else "")
        tool  = stage_cfg.get("tool", "")
        desc  = stage_cfg.get("description", stage_name)

        log.info("=== Stage [%s]: %s ===", stage_name, desc)
        print(f"[Paper Pipeline] Stage [{stage_name}]: {desc} ...", flush=True)

        # ── disabled_tools check ────────────────────────────────────────
        # Honour tools toggled off in the GUI Workflow page.
        _disabled = set(_wf_cfg.get("disabled_tools") or [])
        if tool and tool in _disabled:
            log.info("Stage [%s]: tool '%s' is disabled_tools; skip", stage_name, tool)
            print(f"[Paper Pipeline] Stage [{stage_name}]: SKIPPED (tool '{tool}' disabled)", flush=True)
            stage_outputs[stage_name] = {"skipped": True, "reason": f"tool disabled: {tool}"}
            tpl_vars["stages"][stage_name] = {"output": "", "outputs": {}}
            _stage_idx += 1
            continue

        # ── depends_on check ─────────────────────────────────────────────
        _depends = stage_cfg.get("depends_on", [])
        if isinstance(_depends, str): _depends = [_depends]
        # A dep that is disabled (enabled: false in workflow.yaml) is a no-op
        # by design — treat it as resolved instead of cascading "not resolved"
        # to every downstream stage. The "failed or skipped" check below still
        # gates on real failures.
        _dep_missing = next(
            (_d for _d in _depends
             if _d not in tpl_vars.get("stages", {})
             and _d not in _disabled_stages),
            None,
        )
        # Also check if any dependency actually failed (registered but has no output)
        _dep_failed = next(
            (_d for _d in _depends
             if _d in tpl_vars.get("stages", {})
             and not tpl_vars["stages"][_d].get("output")
             and _d in stage_outputs
             and isinstance(stage_outputs.get(_d), dict)
             and ("error" in stage_outputs[_d] or stage_outputs[_d].get("skipped"))),
            None,
        )
        _dep_fail = _dep_missing or _dep_failed
        if _dep_fail:
            _reason = "not resolved" if _dep_missing else "failed or skipped"
            log.warning("Stage [%s]: dep '%s' %s; skip", stage_name, _dep_fail, _reason)
            print(f"[Paper Pipeline] Stage [{stage_name}]: SKIPPED (dep '{_dep_fail}' {_reason})", flush=True)
            stage_outputs[stage_name] = {"skipped": True, "reason": f"dep {_reason}: {_dep_fail}"}
            tpl_vars["stages"][stage_name] = {"output": "", "outputs": {}}
            _stage_idx += 1
            continue

        # ── skip_if_exists check ──────────────────────────────────────────
        skip_path_tpl = stage_cfg.get("skip_if_exists", "")
        if skip_path_tpl:
            skip_path = _resolve_templates(skip_path_tpl, tpl_vars)
            _skip_file = Path(skip_path)
            _skip_ok = False
            if _skip_file.exists():
                # If the file is JSON, check it doesn't contain an "error" key at the top level
                if _skip_file.suffix == ".json":
                    try:
                        _skip_data = json.loads(_skip_file.read_text())
                        _skip_ok = isinstance(_skip_data, dict) and "error" not in _skip_data
                    except Exception:
                        _skip_ok = False
                else:
                    _skip_ok = _skip_file.stat().st_size > 0
            if _skip_ok:
                log.info("Stage [%s]: skipping (output exists: %s)", stage_name, skip_path)
                print(f"[Paper Pipeline] Stage [{stage_name}]: SKIPPED (output exists)", flush=True)
                tpl_vars["stages"][stage_name] = {"output": skip_path, "outputs": {"file": skip_path}}
                stage_outputs[stage_name] = {"skipped": True, "output": skip_path}
                _stage_idx += 1
                continue

        # ── resolve inputs ────────────────────────────────────────────────
        # load_inputs: input keys whose resolved values (file paths) should be read as content
        load_inputs = set(stage_cfg.get("load_inputs", []))
        # Support both "inputs:" and "input:" YAML keys
        raw_inputs = stage_cfg.get("inputs") or stage_cfg.get("input") or {}
        # Resolve *_from shorthand: "refs_json_from: related_refs.json" -> key=refs_json, value=<ckpt>/related_refs.json
        _resolved_input = {}
        for k, v in raw_inputs.items():
            if k.endswith("_from"):
                base_key = k[:-5]  # strip _from
                file_path = str(checkpoint_dir / v) if not Path(str(v)).is_absolute() else str(v)
                _resolved_input[base_key] = file_path
                load_inputs.add(base_key)  # auto-load file content
            else:
                _resolved_input[k] = v
        raw_inputs = _resolved_input
        args = {}
        # params are static values passed directly to the tool (with template expansion)
        for k, v in stage_cfg.get("params", {}).items():
            args[k] = _resolve_templates(v, tpl_vars) if isinstance(v, str) else v
        for k, v in raw_inputs.items():
            resolved = _resolve_templates(v, tpl_vars)
            # Read file content only for inputs explicitly listed in load_inputs
            if (k in load_inputs and isinstance(resolved, str) and Path(resolved).exists()):
                args[k] = Path(resolved).read_text()
            else:
                args[k] = resolved

        # ── fallbacks: paper_text and actual_metrics (backward compat) ────
        _paper_tools  = {"evaluate", "review_section", "reproducibility_report"}
        _metrics_tools = {"evaluate", "compare_with_results", "reproducibility_report"}
        if tool in _paper_tools and "paper_text" not in args:
            for _tex in ("full_paper.tex", "experiment_section.tex"):
                tp = checkpoint_dir / _tex
                if tp.exists():
                    args.setdefault("paper_text", tp.read_text())
                    break
        if tool in _metrics_tools and "actual_metrics" not in args:
            args.setdefault("actual_metrics", best_metrics)
        # ── paper_path fallback: if revised tex missing OR too short, fall back to original ──
        if "paper_path" in args:
            pp = Path(args["paper_path"])
            _orig = checkpoint_dir / "full_paper.tex"
            if not pp.exists():
                if _orig.exists():
                    log.warning("paper_path %s not found; falling back to full_paper.tex", pp)
                    args["paper_path"] = str(_orig)
            elif _orig.exists():
                # If revised is less than 60% of original size, it was likely truncated by LLM
                _rev_size = pp.stat().st_size
                _orig_size = _orig.stat().st_size
                if _orig_size > 0 and _rev_size < _orig_size * 0.6:
                    log.warning("revised paper too short (%d vs %d bytes); using original", _rev_size, _orig_size)
                    args["paper_path"] = str(_orig)

        try:
            # ── tool call (with retry on transient connection errors) ─────────
            import time as _retry_time
            _max_retries = 5
            _last_exc = None
            result = None
            # Stages declaring a `react:` block run a ReAct loop between an
            # optional pre_tool (config extraction) and post_tool (report
            # building). See ari.agent.react_driver.
            if stage_cfg.get("react"):
                log.info(
                    "Stage [%s]: react block present; pre=%s post=%s phase=%s",
                    stage_name, stage_cfg.get("pre_tool", ""),
                    stage_cfg.get("post_tool", ""),
                    stage_cfg.get("react", {}).get("agent_phase", "reproduce"),
                )
                result = _run_react_stage(
                    stage_cfg=stage_cfg,
                    args=args,
                    tpl_vars=tpl_vars,
                    config_path=config_path,
                    checkpoint_dir=checkpoint_dir,
                    stage_name=stage_name,
                )
            else:
                for _attempt in range(_max_retries):
                    try:
                        log.info("Stage [%s]: calling tool=%s skill=%s args_keys=%s (attempt %d/%d)",
                                 stage_name, tool, skill, list(args.keys()), _attempt + 1, _max_retries)
                        result = _run_stage_subprocess(tool, args, config_path, skill_name=skill)
                        # Check if result itself contains a connection error (MCP returned error dict)
                        if isinstance(result, dict):
                            _r_str = result.get("result", "")
                            if isinstance(_r_str, str) and ("connection error" in _r_str.lower() or
                                                             "internalservererror" in _r_str.lower()):
                                raise RuntimeError(f"MCP tool returned connection error: {_r_str[:200]}")
                        _last_exc = None
                        break
                    except Exception as _retry_exc:
                        _msg = str(_retry_exc).lower()
                        if any(x in _msg for x in ("connection error", "connection reset", "timeout",
                                                    "internalservererror", "mcp tool returned connection")):
                            _last_exc = _retry_exc
                            if _attempt < _max_retries - 1:
                                _wait = 30 * (_attempt + 1)  # 30, 60, 90, 120s backoff
                                log.warning("Stage [%s] attempt %d failed (transient): %s. Retrying in %ds...",
                                            stage_name, _attempt + 1, _retry_exc, _wait)
                                _retry_time.sleep(_wait)
                                continue
                        raise
                if _last_exc:
                    raise _last_exc
            stage_outputs[stage_name] = result
            # ── save outputs ──────────────────────────────────────────────
            outputs_cfg = stage_cfg.get("outputs", {})
            # Support both "output_file: foo.json" (shorthand) and "outputs: {file: foo.json}" (full)
            _output_file_shorthand = stage_cfg.get("output_file", "")
            if _output_file_shorthand and not outputs_cfg.get("file"):
                _resolved_shorthand = _resolve_templates(_output_file_shorthand, tpl_vars)
                _abs_shorthand = str(checkpoint_dir / _resolved_shorthand) if not Path(_resolved_shorthand).is_absolute() else _resolved_shorthand
                primary_file = _abs_shorthand
                outputs_cfg = {"file": primary_file}
            else:
                primary_file = _resolve_templates(outputs_cfg.get("file", ""), tpl_vars)

            if primary_file:
                out_path = Path(primary_file)
                if primary_file.endswith(".tex"):
                    latex = (result.get("latex", "") if isinstance(result, dict) else "") or ""
                    # Fallback: unwrap nested result dict if latex is empty
                    if not latex and isinstance(result, dict):
                        _inner = result.get("result", "")
                        if isinstance(_inner, str) and _inner.startswith("{"):
                            import json as _jj
                            try:
                                _parsed = _jj.loads(_inner)
                                latex = _parsed.get("latex", "")
                            except Exception:
                                pass
                        elif isinstance(_inner, dict):
                            latex = _inner.get("latex", "")
                    if latex:
                        out_path.write_text(latex)
                        log.info("Stage [%s]: wrote %s", stage_name, out_path)
                    else:
                        # Write debug dump for diagnosis
                        _dbg = out_path.parent / f"_debug_{stage_name}.json"
                        import json as _jj
                        _dbg.write_text(_jj.dumps(result, ensure_ascii=False, default=str)[:5000])
                        log.warning("Stage [%s]: no latex in result; debug -> %s", stage_name, _dbg)
                        raise RuntimeError(f"Stage [{stage_name}]: tool returned no latex content")
                    # Save bib alongside
                    bib_content = result.get("bib", "") if isinstance(result, dict) else ""
                    if bib_content:
                        bib_file = _resolve_templates(outputs_cfg.get("bib_file", str(out_path.parent / "refs.bib")), tpl_vars)
                        Path(bib_file).write_text(bib_content)
                        log.info("Stage [%s]: wrote %s", stage_name, bib_file)
                else:
                    # For binary outputs (PDF etc.) the tool writes the file itself;
                    # only write JSON if the output_file doesn't already exist as a real file
                    _pdf_path = result.get("pdf_path", "") if isinstance(result, dict) else ""
                    if _pdf_path and Path(_pdf_path).exists() and Path(_pdf_path).stat().st_size > 1024:
                        # Tool wrote the file — just log it
                        out_path_real = Path(_pdf_path)
                        if str(out_path_real) != str(out_path):
                            import shutil as _shu
                            _shu.copy2(str(out_path_real), str(out_path))
                        log.info("Stage [%s]: wrote %s", stage_name, out_path)
                    elif out_path.suffix in (".pdf", ".png", ".jpg") and out_path.exists() and out_path.stat().st_size > 1024:
                        log.info("Stage [%s]: output already at %s", stage_name, out_path)
                    else:
                        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
                        log.info("Stage [%s]: wrote %s", stage_name, out_path)

                # Register primary + named outputs for template resolution
                _named = {k: _resolve_templates(v, tpl_vars)
                          for k, v in outputs_cfg.items()}
                tpl_vars["stages"][stage_name] = {
                    "output": primary_file,
                    "outputs": _named,
                }
            else:
                tpl_vars["stages"][stage_name] = {"output": "", "outputs": {}}

            # Handle figures_manifest specially
            if stage_name == "generate_figures" or "figures" in stage_name:
                figs = result.get("figures", {}) if isinstance(result, dict) else {}
                latex_snips = result.get("latex_snippets", {}) if isinstance(result, dict) else {}
                fig_kinds = result.get("figure_kinds", {}) if isinstance(result, dict) else {}
                if figs and primary_file:
                    manifest = {"figures": figs}
                    if latex_snips:
                        manifest["latex_snippets"] = latex_snips
                    if fig_kinds:
                        manifest["figure_kinds"] = fig_kinds
                    Path(primary_file).write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
                    log.info("Stage [%s]: wrote figures manifest %s (latex_snippets=%d, kinds=%d)",
                             stage_name, primary_file, len(latex_snips), len(fig_kinds))

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
                        tpl_vars["vlm_feedback"] = _format_vlm_feedback(result)
                        # Reset state for stages [target_idx .. _stage_idx]
                        # so they actually re-run (don't hit skip_if_exists
                        # on their own outputs).
                        for _reset_idx in range(_target_idx, _stage_idx + 1):
                            _reset_name = stages[_reset_idx].get("stage", "")
                            tpl_vars["stages"].pop(_reset_name, None)
                            stage_outputs.pop(_reset_name, None)
                            _reset_skip = stages[_reset_idx].get("skip_if_exists", "")
                            if _reset_skip:
                                try:
                                    _reset_path = Path(
                                        _resolve_templates(_reset_skip, tpl_vars)
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
            stage_outputs[stage_name] = {"error": "stage failed"}
            tpl_vars["stages"][stage_name] = {"output": "", "outputs": {}}

        _stage_idx += 1

    return stage_outputs
