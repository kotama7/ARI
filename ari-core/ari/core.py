"""Generic ARI runtime builder — zero domain-specific code.

cli.py only reads arguments and calls this module.
MetricSpec generation is delegated to evaluator-skill and not returned to cli.py.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ari.protocols import NodeExecutor, SearchStrategy

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Phase 3: rubric loader for dynamic-axis evaluator wiring
# ---------------------------------------------------------------------------


def _load_rubric_dict_for_axes() -> "dict | None":
    """Load the active rubric as a parsed YAML dict.

    The dict is the **same shape** the rubric YAML files have on disk
    (id / score_dimensions / decision / etc.) — no Rubric dataclass is
    constructed because ``ari.evaluator.dynamic_axes.rubric_to_axes``
    accepts both shapes and we want to avoid a hard dependency on
    ari-skill-paper from ari-core.

    Source: ``ARI_RUBRIC`` env var (default ``neurips``) → YAML under
    ``ari-core/config/reviewer_rubrics/<id>.yaml``. Returns None when no
    rubric file is found, in which case the evaluator runs with the
    generic floor + plan-derived axes only.
    """
    rid = (os.environ.get("ARI_RUBRIC") or "neurips").strip()
    from ari.config.finder import package_config_root
    rubrics_dir = package_config_root() / "reviewer_rubrics"
    candidates = [rubrics_dir / f"{rid}.yaml"]
    if rid != "neurips":
        candidates.append(rubrics_dir / "neurips.yaml")  # safe fallback
    try:
        import yaml as _y
    except Exception:
        return None
    for p in candidates:
        if not p.exists():
            continue
        try:
            data = _y.safe_load(p.read_text())
            if isinstance(data, dict):
                return data
        except Exception as e:
            log.warning("failed to load rubric %s: %s", p, e)
    return None


# ---------------------------------------------------------------------------
# MetricSpec: auto-generated from evaluator-skill
# ---------------------------------------------------------------------------

def _make_metric_spec():
    """Always returns the same generic MetricSpec. Zero domain knowledge.

    Evaluation is autonomously determined by LLMEvaluator from the goal text.
    No branching. No keyword parsing.
    """
    from ari.evaluator import MetricSpec
    import re as _re_num
    _pat = _re_num.compile(r"\b(\d+\.\d+|\d{4,})\b")

    def _generic_extractor(text: str) -> dict:
        nums = [float(x) for x in _pat.findall(text) if float(x) >= 1.0]
        return {"result_" + str(i): v for i, v in enumerate(nums[:20])}

    return MetricSpec(name="generic experiment", artifact_extractor=_generic_extractor)


# ---------------------------------------------------------------------------
# Runtime builder
# ---------------------------------------------------------------------------


def _install_capability_gate(cfg, mcp, rqgm, checkpoint_dir):
    """Wrap *mcp* in the constitutional capability gate; identity on failure.

    Unmapped tools dispatch untouched and the mappings ordinary research work
    produces are ones the institutional ``generator`` holds, so a well-behaved
    run is unaffected — what the gate adds is an audit record for every
    governed call and, for the violation codes the constitution treats as
    critical, the T16 emergency escalation that had no caller before.
    """
    try:
        from ari.rqgm.kernel import CapabilityGatedMCPClient
        from ari.rqgm.store import ImmutableAuditLog
        from ari.rqgm.tool_policy import default_tool_policy

        kernel = getattr(rqgm, "kernel", None)
        if kernel is None:
            return mcp
        engine = getattr(rqgm, "transition_engine", None)

        def _on_emergency(violation, tool_name, actor=None):
            """T16: the sole mid-epoch transition, raised from the only place a
            running agent can trip the constitution."""
            if engine is None:
                log.warning(
                    "constitutional emergency %s on tool %s, but no transition "
                    "engine is available to quarantine",
                    getattr(violation, "code", "?"), tool_name,
                )
                return
            epoch = getattr(rqgm, "current_epoch", None)
            # Quarantine the ACTING COMPONENT, not the tool: a tool name is not
            # a registry entry, so passing it made the engine reject every
            # escalation as "unknown component" — T16 would have fired and then
            # always degraded. The actor at this choke point is the epoch's
            # active `generator` (see ari/rqgm/tool_policy.AGENT_ACTOR).
            component_id = str(getattr(violation, "component_id", "") or "")
            if not component_id and actor is not None:
                role = actor[0] if isinstance(actor, tuple) else getattr(
                    actor, "role", "")
                active = getattr(epoch, "active_components", None) or {}
                if isinstance(active, dict):
                    component_id = str(active.get(str(role), "") or "")
            if not component_id:
                # The acting role is not a governed COMPONENT (the research
                # agent's `generator` role has an active prompt but no registry
                # entry). The call was still DENIED and the verdict audited —
                # T16 exists for a REGISTERED component tripping a critical
                # code, which is a different subject.
                log.warning(
                    "constitutional emergency %s on tool %s: actor is not a "
                    "registered component; denial stands, no quarantine",
                    getattr(violation, "code", "?"), tool_name,
                )
                return
            try:
                # The registries are REQUIRED: without them the engine cannot
                # resolve the component and rejects every escalation as
                # "unknown component" — T16 would fire and always degrade.
                st = getattr(rqgm, "state", None)
                transition = engine.emergency_quarantine(
                    violation=violation,
                    component_id=component_id,
                    epoch_state=epoch,
                    components=getattr(st, "components", None),
                    prompts=getattr(st, "prompts", None),
                    checkpoint_dir=checkpoint_dir,
                    node_count=getattr(rqgm, "_last_node_count", None),
                    run_id=str(getattr(epoch, "run_id", "") or ""),
                )
                if getattr(transition, "status", "") == "committed":
                    refreshed = getattr(rqgm, "_store", None).load_state(
                        checkpoint_dir
                    )
                    if refreshed is not None:
                        rqgm._epoch_state = refreshed
            except Exception:
                log.warning("emergency quarantine failed (fail-open)",
                            exc_info=True)

        return CapabilityGatedMCPClient(
            mcp, kernel,
            tool_policy=default_tool_policy,
            enforcement=str(getattr(rqgm, "kernel_enforcement", "standard")),
            audit_log=ImmutableAuditLog(checkpoint_dir),
            on_emergency=_on_emergency,
        )
    except Exception:
        log.warning("capability gate install failed; continuing ungated",
                    exc_info=True)
        return mcp


def _construct_mcp_client(factory, skills, disabled_tools, skill_lock_path):
    """Construct the canonical locked client, tolerating only legacy doubles."""

    try:
        return factory(
            skills,
            disabled_tools=disabled_tools,
            skill_lock_path=skill_lock_path,
        )
    except TypeError as lock_error:
        # Pre-v1 injected MCP clients and narrow test doubles do not know the
        # immutable lock path yet. Preserve their construction seam while the
        # canonical MCPClient always receives (and persists) the lock.
        message = str(lock_error)
        if "skill_lock_path" not in message or "unexpected keyword" not in message:
            raise
        return factory(skills, disabled_tools=disabled_tools)


def build_runtime(cfg, experiment_text: str = "", checkpoint_dir: "str | Path | None" = None):
    """Build and return a generic ARI runtime. No domain-specific code.

    Parameters
    ----------
    checkpoint_dir : str | Path
        Required.  Agent memory is stored per-run at
        ``{checkpoint_dir}/memory.json``.  ARI no longer supports a global
        fallback under ``~/.ari``.
    """
    from ari.agent.loop import AgentLoop
    from ari.agent.workflow import from_experiment_text, enrich_hints_from_mcp
    from ari.evaluator import LLMEvaluator
    from ari.llm.client import LLMClient
    from ari.mcp.client import MCPClient, ToolNameCollisionError
    # ReAct trace now lives in Letta. The
    # v0.5.x FileMemoryClient is kept only as a v0.5.x → v0.6.0 migration
    # source (`ari memory migrate --react`).
    from ari.memory.letta_client import LettaMemoryClient
    from ari.orchestrator.bfts import BFTS
    from ari.skill_lock import SKILLS_LOCK_FILENAME, SkillLockError

    if checkpoint_dir is None:
        raise ValueError(
            "build_runtime requires checkpoint_dir — agent memory is "
            "project-scoped and no global fallback exists."
        )
    # Phase-specific model overrides: the GUI Settings page writes
    # ARI_MODEL_CODING / ARI_MODEL_BFTS / ARI_MODEL_EVAL so callers can use a
    # different LLM for the ReAct agent, the BFTS orchestrator, and evaluation.
    # Skills running as subprocesses read their own phase env directly; BFTS
    # and the AgentLoop live in-process and share the same LLMClient class, so
    # we construct a dedicated client per phase here.
    import os as _os_phase
    from copy import copy as _copy_phase

    def _phase_llm(phase: str) -> LLMClient:
        _override = _os_phase.environ.get(f"ARI_MODEL_{phase.upper()}")
        if not _override:
            return LLMClient(cfg.llm)
        _pc = _copy_phase(cfg.llm)
        _pc.model = _override
        return LLMClient(_pc)

    llm = _phase_llm("coding")          # AgentLoop / ReAct
    bfts_llm = _phase_llm("bfts")       # BFTS orchestrator
    # the one-line swap.
    memory = LettaMemoryClient(checkpoint_dir=str(checkpoint_dir))
    _disabled = list(cfg.disabled_tools)
    _skills = list(cfg.skills)
    if not cfg.resources.get("hpc_enabled", True):
        # Laptop profile: drop the hpc-skill entirely. Its SLURM/Singularity
        # scheduler tools (job_submit, container_submit, slurm_submit) would
        # otherwise submit sbatch jobs from inside the skill even when the
        # agent is not supposed to use HPC at all. run_bash lives in
        # coding-skill, so removing hpc-skill does not remove shell access.
        _skills = [s for s in _skills if getattr(s, "name", "") != "hpc-skill"]
    mcp = _construct_mcp_client(
        MCPClient,
        _skills,
        _disabled,
        Path(checkpoint_dir) / SKILLS_LOCK_FILENAME,
    )
    # Wire the MCPClient into both LLMClients so cli-shim-targeted calls can
    # forward (--mcp-config + --allowedTools mcp__*) to the Claude
    # subprocess. With this, the text-catalog tool protocol is bypassed and
    # claude can ONLY call ari-skill MCP servers (no native Bash / Write /
    # Edit on the login node — see the 2026-05-28 hallucinated-environment incident).
    llm.mcp_client = mcp
    bfts_llm.mcp_client = mcp
    bfts: SearchStrategy = BFTS(cfg.bfts, bfts_llm)
    # RQGM execution-mode switch (docs/plans/ari_rqgm Task 01). Guarded on the
    # raw config flags so the default simple_bfts path never imports any
    # ari.rqgm module (identity-default guarantee); resolve_effective_mode
    # owns the interlock table and the disagreement fallback warnings.
    _ari_mode = getattr(getattr(cfg, "ari", None), "mode", "simple_bfts")
    _rqgm_enabled = bool(getattr(getattr(cfg, "rqgm", None), "enabled", False))
    if _ari_mode == "ari_rqgm" or _rqgm_enabled:
        from ari.rqgm.mode import EffectiveMode, resolve_effective_mode
        if resolve_effective_mode(cfg) is EffectiveMode.ARI_RQGM:
            from ari.rqgm.runtime import RQGMRuntime  # lazy: ari_rqgm only
            # llm/mcp feed the ProposalRouter generators (Task 03); the
            # VirSciAdapter is constructed inside the router only when
            # proposal_router.generators.virsci.enabled is true.
            rqgm = RQGMRuntime(
                cfg, checkpoint_dir=checkpoint_dir, llm=bfts_llm, mcp=mcp
            )
            # Wrap, never extend: the 6-tuple return shape is relied on
            # positionally. The controller stays discoverable via
            #   getattr(bfts, "rqgm", None) -> RQGMRuntime | None
            bfts = rqgm.wrap_search_strategy(bfts)
            # Install the constitutional choke point (plan 04 §5.6.4). It
            # shipped complete but was NEVER constructed outside tests, so no
            # tool call was ever checked against CAPABILITY_MATRIX and the codes
            # that make the constitution enforceable at the one place a running
            # agent touches the world (CK-ACC-001/002, CK-ROL-901) could not be
            # raised — which in turn left `emergency_quarantine` (T16, the sole
            # mid-epoch transition) with no production caller at all.
            mcp = _install_capability_gate(cfg, mcp, rqgm, checkpoint_dir)
            llm.mcp_client = mcp
            bfts_llm.mcp_client = mcp

    # MetricSpec: auto-generated from experiment file by evaluator-skill
    metric_spec = _make_metric_spec()

    # Evaluator may also use a phase-specific model override (ARI_MODEL_EVAL).
    _eval_model = _os_phase.environ.get("ARI_MODEL_EVAL") or llm._model_name()
    _eval_cfg = getattr(cfg, "evaluator", None)
    _axis_weights = getattr(_eval_cfg, "axis_weights", None) or None
    _composite = getattr(_eval_cfg, "composite", "harmonic_mean")
    _axis_mode = getattr(_eval_cfg, "axis_mode", "dynamic")
    # Layer C: dispatch on axis_mode.
    # - legacy: pin to the canonical 5-axis set (AXIS_NAMES); no rubric / plan input.
    # - custom: build AxisDef list from cfg.evaluator.custom_axes verbatim.
    # - dynamic (default): existing rubric + idea.json driven build.
    _eval_extra_kwargs: dict = {}
    if _axis_mode == "legacy":
        pass  # no axes / rubric / checkpoint_dir → llm_evaluator picks legacy
    elif _axis_mode == "custom":
        from ari.evaluator.dynamic_axes import AxisDef as _AxisDef
        _custom = getattr(_eval_cfg, "custom_axes", None) or []
        _eval_extra_kwargs["axes"] = [
            _AxisDef(
                name=a.name,
                description=a.description,
                source="custom",
                weight=float(a.weight),
            )
            for a in _custom
        ]
    else:
        # dynamic — Phase 3 path (rubric + plan-derived axes).
        _rubric_for_axes = _load_rubric_dict_for_axes()
        _eval_extra_kwargs["checkpoint_dir"] = str(checkpoint_dir)
        _eval_extra_kwargs["rubric"] = _rubric_for_axes
    # Forward the configured base_url to the judge whenever the evaluator is
    # pointed at the same local / OpenAI-compatible endpoint as the main client
    # (ollama, or a shim such as ari.llm.cli_server). A cloud ARI_MODEL_EVAL
    # override that swaps the model keeps api_base=None so litellm uses the
    # provider default rather than dialling the local endpoint.
    _eval_override = _os_phase.environ.get("ARI_MODEL_EVAL")
    _eval_uses_main_backend = (not _eval_override) or _eval_override == llm._model_name()
    _eval_api_base = (
        llm.config.base_url
        if (llm.config.base_url and _eval_uses_main_backend)
        else None
    )
    # Evaluator dispatch (handoff study B2). ARI_EVALUATOR=deterministic swaps the
    # LLM judge for a fixed, non-LLM evaluator that owns the measurement (PREREG:
    # LLM judge excluded from the main metric). Default keeps LLMEvaluator.
    if _os_phase.environ.get("ARI_EVALUATOR", "").strip().lower() == "deterministic":
        from ari.evaluator.deterministic_evaluator import DeterministicEvaluator
        evaluator = DeterministicEvaluator()
    else:
        evaluator = LLMEvaluator(
            model=_eval_model,
            api_base=_eval_api_base,
            metric_spec=metric_spec,
            axis_weights=_axis_weights,
            composite=_composite,
            **_eval_extra_kwargs,
        )

    # ari_rqgm: bind the evaluator so the epoch's FROZEN utility_policy actually
    # drives scoring (the objective co-evolves per-epoch — RQGM paper claim A).
    # Without this the adopted policy was captured but inert. simple_bfts has no
    # rqgm object, so this is a no-op there.
    _rq = getattr(bfts, "rqgm", None)
    if _rq is not None and hasattr(_rq, "bind_evaluator"):
        _rq.bind_evaluator(evaluator)

    # WorkflowHints: auto-extracted from experiment file
    hpc_enabled = cfg.resources.get("hpc_enabled", True)
    wf_hints = from_experiment_text(experiment_text, hpc_enabled=hpc_enabled)

    # Enrich hints with dynamically discovered MCP tools (phase=bfts)
    try:
        bfts_tools = mcp.list_tools(phase="bfts")
        enrich_hints_from_mcp(wf_hints, bfts_tools, hpc_enabled=hpc_enabled)
    except Exception as exc:
        if isinstance(exc, (SkillLockError, ToolNameCollisionError)):
            raise
        pass  # Graceful fallback — static hints still work

    # metric_extractor: generated by workflow.py from metric_keyword; falls back to MetricSpec extractor
    if wf_hints.metric_extractor is None and metric_spec and metric_spec.artifact_extractor:
        wf_hints.metric_extractor = metric_spec.artifact_extractor

    agent: NodeExecutor = AgentLoop(
        llm, memory, mcp, evaluator=evaluator, workflow_hints=wf_hints,
        max_react_steps=cfg.bfts.max_react_steps,
        timeout_per_node=cfg.bfts.timeout_per_node,
        handoff=getattr(cfg, "handoff", None),
    )
    # RQGM Task 11 §5.8: under ari_rqgm the runtime attaches the
    # metric-spec weight cap to the executor (additive attribute; identity
    # otherwise). Duck-typed discovery — never isinstance.
    _rqgm_runtime = getattr(bfts, "rqgm", None)
    if _rqgm_runtime is not None:
        agent = _rqgm_runtime.wrap_node_executor(agent)
    return llm, memory, mcp, bfts, agent, metric_spec


# ---------------------------------------------------------------------------
# Paper section generation (generic)
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# Post-BFTS pipeline (driven by pipeline.yaml)
# ---------------------------------------------------------------------------

def generate_paper_section(
    all_nodes, experiment_data: dict, checkpoint_dir: Path, mcp, config_path: str,
    *, disable_stages=frozenset(), include_segments: frozenset[str] | None = None,
) -> None:
    """Run the post-BFTS pipeline according to pipeline.yaml. No hardcoding.

    ``disable_stages`` lets a CALLER declare that it has already produced some
    stages' outputs itself, so those stages must not run. It exists for the
    ``rqgm_archive`` handoff (docs/plans/ari_rqgm_paper/07 §5.1/§5.4/R5: "the
    archive substitutes for `write_paper` + `paper_refine`"; "`full_paper.tex` is
    overwritten in place exactly once, by `materialize_winner`"), which owns the
    generation stages and needs the tail to run on ITS winner rather than refine
    over it.

    ``include_segments`` is the additive Manuscript Complete runner seam.  It
    selects ``evidence | authoring | verification`` metadata from the same
    resolved workflow; the default ``None`` still runs every enabled stage.
    Excluded segments are represented as disabled stages in a derived workflow
    so cross-segment ``depends_on`` edges remain satisfied by durable outputs.

    Deliberately plain, mode-agnostic parameters and NOT config reads: this
    function never learns what `paper.mode` is, so §5.1's "no stage conditionals,
    no dual code paths, no `paper.mode` reads in the pipeline" holds. It defaults
    to empty, so the linear path is byte-identical by construction — the derived
    config is not even written unless a caller asks for a disable.
    """
    from ari.pipeline import load_pipeline, run_pipeline
    from ari.pipeline.yaml_loader import derive_workflow_with_disabled

    log.info("Starting paper pipeline (config_path=%s, checkpoint=%s)", config_path, checkpoint_dir)
    print(f"\n{'='*60}")
    print("  Paper Pipeline Starting")
    print(f"  Checkpoint: {checkpoint_dir}")
    print(f"{'='*60}", flush=True)

    # Load pipeline from workflow.yaml (preferred) or pipeline.yaml (legacy
    # fallback). The per-checkpoint copy is searched first so launch-time
    # rewrites (e.g. include_ear=False disabling EAR / ors_seed_sandbox stages)
    # actually take effect — symmetrical with how the BFTS phase already reads
    # the checkpoint copy at cli.py:478.
    from ari.config.finder import package_config_root
    _pkg_cfg_root = package_config_root()
    pipeline_yaml_candidates = [
        Path(checkpoint_dir) / "workflow.yaml",
        Path(checkpoint_dir) / "pipeline.yaml",
        Path(config_path).parent / "workflow.yaml",
        Path(config_path).parent / "pipeline.yaml",
        _pkg_cfg_root / "workflow.yaml",
        _pkg_cfg_root / "pipeline.yaml",
    ]
    pipeline_yaml = next((p for p in pipeline_yaml_candidates if p.exists()), None)

    if pipeline_yaml is None:
        log.error("pipeline.yaml not found in any candidate path; skipping post-BFTS pipeline. Searched: %s",
                  [str(p) for p in pipeline_yaml_candidates])
        print("[Paper Pipeline] ERROR: workflow.yaml not found, skipping paper generation", flush=True)
        return

    log.info("Using pipeline config: %s (%d candidates searched)", pipeline_yaml,
             len(pipeline_yaml_candidates))

    # A caller-declared stage disable is applied to the RESOLVED workflow (the
    # candidate search above owns which file is effective, and the caller cannot
    # know it). Both the stage list AND the driver then read the SAME derived
    # file, so `depends_on` on a disabled stage resolves via
    # `ctx.disabled_stages` instead of cascade-skipping the tail. Fail-open: a
    # derivation error leaves the original workflow in force.
    _driver_cfg = config_path
    _segment_execution = None
    resolved_disables = {str(name) for name in disable_stages}
    if include_segments is not None:
        selected = {str(value) for value in include_segments}
        allowed = {"evidence", "authoring", "verification"}
        if not selected or not selected.issubset(allowed):
            raise ValueError(
                "paper pipeline segments must be a non-empty subset of "
                "evidence/authoring/verification"
            )
        all_enabled = load_pipeline(pipeline_yaml)
        unsegmented = [
            str(stage.get("stage") or "?")
            for stage in all_enabled
            if stage.get("segment") not in allowed
        ]
        if unsegmented:
            raise ValueError(
                "segmented paper execution found stages without valid segment: "
                + ", ".join(unsegmented)
            )
        if os.environ.get("ARI_MANUSCRIPT_RUNTIME_MODE", "off") != "off":
            from ari.manuscript.segments import prepare_segment_execution

            _segment_execution = prepare_segment_execution(
                checkpoint_dir,
                pipeline_yaml,
                all_enabled,
                selected,
            )
            if _segment_execution.reusable:
                record = _segment_execution.reusable_record
                log.info(
                    "Paper pipeline segment %s reused immutable record %s",
                    sorted(selected),
                    getattr(record, "record_digest", ""),
                )
                print(
                    "[Paper Pipeline] Segment reuse: "
                    + ", ".join(sorted(selected)),
                    flush=True,
                )
                return
        resolved_disables.update(
            str(stage.get("stage"))
            for stage in all_enabled
            if stage.get("segment") not in selected
        )
    if resolved_disables:
        suffix = (
            "-".join(sorted(include_segments))
            if include_segments is not None
            else "caller"
        )
        _handoff = derive_workflow_with_disabled(
            pipeline_yaml,
            Path(checkpoint_dir) / f"workflow.segment-{suffix}.yaml",
            resolved_disables,
        )
        if _handoff is not None:
            log.info("Paper pipeline: %s disabled by the caller; using %s",
                     sorted(resolved_disables), _handoff)
            pipeline_yaml = _handoff
            _driver_cfg = str(_handoff)

    stages = load_pipeline(pipeline_yaml)
    if not stages:
        log.error("No enabled pipeline stages in %s", pipeline_yaml)
        print(f"[Paper Pipeline] ERROR: No enabled stages in {pipeline_yaml}", flush=True)
        if _segment_execution is not None:
            _segment_execution.finish(
                status="blocked",
                blocking_reason="no_enabled_stages",
            )
        return

    stage_names = [s.get("stage", "?") for s in stages]
    log.info("Paper pipeline: %d stages to execute", len(stages))
    print(f"[Paper Pipeline] {len(stages)} stages: {', '.join(stage_names)}", flush=True)
    try:
        result = run_pipeline(
            stages, all_nodes, experiment_data, checkpoint_dir, _driver_cfg
        )
    except Exception as exc:
        if _segment_execution is not None:
            _segment_execution.finish(
                status="failed",
                blocking_reason=f"pipeline_exception:{type(exc).__name__}",
            )
        raise
    if _segment_execution is not None:
        if isinstance(result, dict) and result.get("_aborted"):
            reason = str((result.get("_aborted") or {}).get("reason") or "pipeline_aborted")
            _segment_execution.finish(status="blocked", blocking_reason=reason)
        else:
            failed_stages = sorted(
                str(name)
                for name, value in (result or {}).items()
                if isinstance(value, dict) and value.get("error")
            )
            _segment_execution.finish(
                status=("failed" if failed_stages else "completed"),
                blocking_reason=(
                    "failed_stages:" + ",".join(failed_stages)
                    if failed_stages
                    else ""
                ),
            )
    log.info("Paper pipeline completed: %s", list(result.keys()) if result else "no result")
    print(f"[Paper Pipeline] Complete: {list(result.keys()) if result else 'no result'}", flush=True)

    # Every integrity check already wrote a finding somewhere; nothing read them
    # together, so a run could ship a paper containing a fabricated verification
    # claim and print only DONE eighteen times. Collect them into one artifact
    # and say the concerns out loud. Fail-open: never breaks a completed run.
    try:
        from ari.pipeline.integrity import write_integrity_report

        write_integrity_report(checkpoint_dir)
    except Exception:  # pragma: no cover - defensive
        log.warning("run-integrity summary failed", exc_info=True)
