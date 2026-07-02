"""First-class pipeline stage objects (subtask 012).

A "stage" used to be a plain ``dict`` parsed from the ``pipeline:`` list in
``config/workflow.yaml`` and handled inline by the 913-LOC ``run_pipeline``
loop. This module introduces a thin object model over that dict so the
per-stage lifecycle (``should_skip → resolve_inputs → run →
persist_outputs``) is expressed as methods rather than inline loop branches.

The refactor is **behaviour-preserving**: every method body is the exact
logic previously inlined in ``ari/pipeline/orchestrator.py::run_pipeline``,
operating on a :class:`~ari.pipeline.stage_context.StageContext` instead of
manually threaded ``tpl_vars`` / ``stage_outputs`` dicts.

Dispatch is preserved via the package surface: ``run`` calls
``ari.pipeline._run_stage_subprocess`` / ``ari.pipeline._run_react_stage``
(never the implementations directly) so the lazy-delegator monkeypatch
surfaces the tests rely on keep working.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ari.pipeline.stage_context import StageContext
from ari.pipeline.yaml_loader import _resolve_templates

log = logging.getLogger(__name__)


class OutputSink:
    """Encapsulates a stage's on-disk output persistence.

    Owns the type-sniffing writer (``.tex`` → ``result["latex"]``, binary
    ``.pdf``/``.png``/``.jpg`` copy-if-distinct, JSON fallback) and the
    ``generate_figures`` manifest special-case that ``run_pipeline``
    previously performed inline (``orchestrator.py:757-826``). The suffix
    rules and manifest schema are ported verbatim.
    """

    @staticmethod
    def copy_if_distinct(src: Path, dst: Path) -> None:
        # Delegate to the canonical helper (kept in ``orchestrator`` so the
        # existing ``from ari.pipeline.orchestrator import
        # _copy_stage_output_if_distinct`` test import stays valid).
        from ari.pipeline.orchestrator import _copy_stage_output_if_distinct

        _copy_stage_output_if_distinct(src, dst)

    def persist(
        self,
        ctx: StageContext,
        stage_name: str,
        stage_cfg: dict,
        result: Any,
    ) -> None:
        tpl_vars = ctx.tpl_vars
        checkpoint_dir = ctx.checkpoint_dir

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
            # Ensure the output's parent dir exists. Stages may declare an output
            # in a subdir (e.g. evaluation/claim_evidence_hard_gate_draft.json);
            # the orchestrator must not assume the tool created it (it may not, or
            # may run after this write). Safe + idempotent.
            try:
                out_path.parent.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass
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
                    # Tool wrote the file itself; copy into the declared output only if
                    # it is genuinely a different file (resolves the absolute-vs-relative
                    # SameFileError that wrongly marked render_paper FAILED).
                    self.copy_if_distinct(Path(_pdf_path), out_path)
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


class BasePipelineStage:
    """One YAML-declared pipeline stage.

    Subclasses override :meth:`run` (the dispatch); the skip checks, input
    resolution, and output persistence are shared because ``run_pipeline``
    applied them uniformly to both dispatch modes.
    """

    # Tools that accept a ``paper_text`` / ``actual_metrics`` fallback arg.
    # Shared across dispatch modes to preserve the historical behaviour where
    # the fallback injection ran before the react/subprocess fork.
    _paper_tools = {"evaluate", "review_section", "reproducibility_report"}
    _metrics_tools = {"evaluate", "compare_with_results", "reproducibility_report"}

    def __init__(self, cfg: dict, wf_cfg: dict):
        self.cfg = cfg
        self.wf_cfg = wf_cfg
        self.stage_name = cfg.get("stage", "unknown")
        skill_key = cfg.get("skill", "")
        self.skill = skill_key if ("skill" in skill_key) else (skill_key + "-skill" if skill_key else "")
        self.tool = cfg.get("tool", "")
        self.desc = cfg.get("description", self.stage_name)
        self._sink = OutputSink()

    # ── should_skip: disabled_tools + depends_on + skip_if_exists ────────
    def should_skip(self, ctx: StageContext) -> bool:
        stage_cfg = self.cfg
        stage_name = self.stage_name
        tool = self.tool
        tpl_vars = ctx.tpl_vars
        stage_outputs = ctx.stage_outputs

        # ── disabled_tools check ────────────────────────────────────────
        # Honour tools toggled off in the GUI Workflow page.
        _disabled = set(ctx.wf_cfg.get("disabled_tools") or [])
        if tool and tool in _disabled:
            log.info("Stage [%s]: tool '%s' is disabled_tools; skip", stage_name, tool)
            print(f"[Paper Pipeline] Stage [{stage_name}]: SKIPPED (tool '{tool}' disabled)", flush=True)
            stage_outputs[stage_name] = {"skipped": True, "reason": f"tool disabled: {tool}"}
            tpl_vars["stages"][stage_name] = {"output": "", "outputs": {}}
            return True

        # ── depends_on check ─────────────────────────────────────────────
        _depends = stage_cfg.get("depends_on", [])
        if isinstance(_depends, str):
            _depends = [_depends]
        # A dep that is disabled (enabled: false in workflow.yaml) is a no-op
        # by design — treat it as resolved instead of cascading "not resolved"
        # to every downstream stage. The "failed or skipped" check below still
        # gates on real failures.
        _dep_missing = next(
            (_d for _d in _depends
             if _d not in tpl_vars.get("stages", {})
             and _d not in ctx.disabled_stages),
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
            return True

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
                return True

        return False

    # ── resolve_inputs: {{var}} resolution + fallback-arg injection ──────
    def resolve_inputs(self, ctx: StageContext) -> dict:
        stage_cfg = self.cfg
        tool = self.tool
        tpl_vars = ctx.tpl_vars
        checkpoint_dir = ctx.checkpoint_dir

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
        _paper_tools = self._paper_tools
        _metrics_tools = self._metrics_tools
        if tool in _paper_tools and "paper_text" not in args:
            for _tex in ("full_paper.tex", "experiment_section.tex"):
                tp = checkpoint_dir / _tex
                if tp.exists():
                    args.setdefault("paper_text", tp.read_text())
                    break
        if tool in _metrics_tools and "actual_metrics" not in args:
            args.setdefault("actual_metrics", ctx.best_metrics)
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

        return args

    def run(self, ctx: StageContext, args: dict) -> Any:
        raise NotImplementedError

    def persist_outputs(self, ctx: StageContext, result: Any) -> None:
        self._sink.persist(ctx, self.stage_name, self.cfg, result)


class SubprocessMCPStage(BasePipelineStage):
    """Default stage: invoke a single MCP tool via a fresh subprocess.

    Wraps ``ari.pipeline._run_stage_subprocess`` (called through the package
    surface so monkeypatches are honoured) with the transient-connection
    retry loop ``run_pipeline`` used inline.
    """

    def run(self, ctx: StageContext, args: dict) -> Any:
        import ari.pipeline as _p

        stage_name = self.stage_name
        tool = self.tool
        skill = self.skill
        config_path = ctx.config_path

        # ── tool call (with retry on transient connection errors) ─────────
        import time as _retry_time
        _max_retries = 5
        _last_exc = None
        result = None
        for _attempt in range(_max_retries):
            try:
                log.info("Stage [%s]: calling tool=%s skill=%s args_keys=%s (attempt %d/%d)",
                         stage_name, tool, skill, list(args.keys()), _attempt + 1, _max_retries)
                result = _p._run_stage_subprocess(tool, args, config_path, skill_name=skill)
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
        return result


class ReActStage(BasePipelineStage):
    """Stage declaring a ``react:`` block — runs a ReAct loop between an
    optional pre_tool and post_tool. Dormant in the shipped config
    (``grep -c 'react:' config/workflow.yaml == 0``) but fully supported for
    tests and per-checkpoint YAML.
    """

    def run(self, ctx: StageContext, args: dict) -> Any:
        import ari.pipeline as _p

        stage_cfg = self.cfg
        stage_name = self.stage_name
        log.info(
            "Stage [%s]: react block present; pre=%s post=%s phase=%s",
            stage_name, stage_cfg.get("pre_tool", ""),
            stage_cfg.get("post_tool", ""),
            stage_cfg.get("react", {}).get("agent_phase", "reproduce"),
        )
        return _p._run_react_stage(
            stage_cfg=stage_cfg,
            args=args,
            tpl_vars=ctx.tpl_vars,
            config_path=ctx.config_path,
            checkpoint_dir=ctx.checkpoint_dir,
            stage_name=stage_name,
        )


def make_stage(cfg: dict, wf_cfg: dict) -> BasePipelineStage:
    """Build the stage object for one YAML dict.

    Replaces the inline ``if stage_cfg.get("react")`` dispatch fork.
    """
    if cfg.get("react"):
        return ReActStage(cfg, wf_cfg)
    return SubprocessMCPStage(cfg, wf_cfg)
